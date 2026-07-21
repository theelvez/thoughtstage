"""Microsoft Foundry adapter using the GA OpenAI/v1 Responses API."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any, Literal, Protocol

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.models import AgentConfig, AgentTurnContext, ModelOutput

DEFAULT_ENDPOINT_ENV = "AZURE_FOUNDRY_ENDPOINT"
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"


class AzureFoundryError(RuntimeError):
    """Base exception for Foundry provider failures."""


class AzureFoundryConfigurationError(AzureFoundryError):
    """Raised when an agent's Foundry binding is incomplete or invalid."""


class AzureFoundryResponseError(AzureFoundryError):
    """Raised when Foundry returns an unusable dual output."""


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _FoundryClient(Protocol):
    responses: _ResponsesResource


class FoundrySettings(BaseModel):
    """Strict provider-specific settings recorded in the experiment manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint_env: str = Field(default=DEFAULT_ENDPOINT_ENV, pattern=r"^[A-Z][A-Z0-9_]*$")
    output_mode: Literal["json_schema", "reflect_then_post"] = "json_schema"
    max_output_tokens: int = Field(default=1000, ge=64, le=100_000)
    private_max_output_tokens: int = Field(default=500, ge=32, le=100_000)
    public_max_output_tokens: int = Field(default=500, ge=32, le=100_000)
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    max_retries: int = Field(default=8, ge=0, le=20)
    send_temperature: bool = True


ClientFactory = Callable[..., _FoundryClient]
TokenProviderFactory = Callable[[], Callable[[], str]]


def _default_token_provider_factory() -> Callable[[], str]:
    return get_bearer_token_provider(DefaultAzureCredential(), FOUNDRY_TOKEN_SCOPE)


def _normalize_base_url(endpoint: str) -> str:
    trimmed = endpoint.strip().rstrip("/")
    if not trimmed:
        raise AzureFoundryConfigurationError("Foundry endpoint cannot be empty")
    if trimmed.endswith("/openai/v1"):
        return f"{trimmed}/"
    return f"{trimmed}/openai/v1/"


def _response_text(response: Any) -> str:
    value = getattr(response, "output_text", None)
    if not isinstance(value, str) or not value.strip():
        raise AzureFoundryResponseError("Foundry returned no text output")
    return value.strip()


def _render_context(context: AgentTurnContext) -> str:
    public_feed = (
        "\n".join(
            f"- [round {post.round_number}] {post.display_name}: {post.content}"
            for post in context.public_feed
        )
        or "- No public posts are visible yet."
    )
    own_history = "\n".join(f"- {item}" for item in context.own_soliloquies) or "- None."
    available_files = "\n".join(f"- {path}" for path in context.available_files) or "- None."
    return (
        f"Your persona:\n{context.persona_prompt}\n\n"
        f"Current experiment round: {context.round_number}\n\n"
        f"Eligible public feed:\n{public_feed}\n\n"
        f"Your own prior private soliloquies:\n{own_history}\n\n"
        f"Available experiment files:\n{available_files}"
    )


def _safety_identifier(context: AgentTurnContext, agent: AgentConfig) -> str:
    stable_id = f"{context.experiment_id}:{agent.id}".encode()
    return hashlib.sha256(stable_id).hexdigest()[:32]


class AzureFoundryProvider:
    """Generate Thoughtstage turns through a Microsoft Foundry deployment.

    The adapter never adds provider, model, endpoint, or credential metadata to
    model-visible context. Foundry receives the deployment name only through the
    API's ``model`` field.
    """

    def __init__(
        self,
        *,
        client_factory: ClientFactory = OpenAI,
        token_provider_factory: TokenProviderFactory = _default_token_provider_factory,
    ) -> None:
        self._client_factory = client_factory
        self._token_provider_factory = token_provider_factory

    def _settings(self, agent: AgentConfig) -> FoundrySettings:
        try:
            return FoundrySettings.model_validate(agent.parameters)
        except ValidationError as exc:
            raise AzureFoundryConfigurationError(
                f"invalid azure_foundry parameters for agent {agent.id!r}: {exc}"
            ) from exc

    def _client(self, agent: AgentConfig, settings: FoundrySettings) -> _FoundryClient:
        endpoint = os.getenv(settings.endpoint_env)
        if endpoint is None or not endpoint.strip():
            raise AzureFoundryConfigurationError(
                f"environment variable {settings.endpoint_env!r} must contain a Foundry endpoint "
                f"for agent {agent.id!r}"
            )

        if agent.credential_env is None:
            credential: str | Callable[[], str] = self._token_provider_factory()
        else:
            credential = os.getenv(agent.credential_env, "")
            if not credential:
                raise AzureFoundryConfigurationError(
                    f"credential environment variable {agent.credential_env!r} is not set"
                )

        return self._client_factory(
            base_url=_normalize_base_url(endpoint),
            api_key=credential,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    @staticmethod
    def _common_request(
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: FoundrySettings,
        *,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": agent.model,
            "max_output_tokens": max_output_tokens,
            "safety_identifier": _safety_identifier(context, agent),
            "store": False,
        }
        if settings.send_temperature:
            request["temperature"] = agent.temperature
        return request

    def _generate_structured(
        self,
        client: _FoundryClient,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: FoundrySettings,
    ) -> ModelOutput:
        request = self._common_request(
            agent, context, settings, max_output_tokens=settings.max_output_tokens
        )
        response = client.responses.create(
            **request,
            instructions=(
                f"{context.system_prompt}\n\n"
                "Thoughtstage output contract: produce a public post and a separate "
                "researcher-private soliloquy. The soliloquy is an explicitly elicited "
                "reflection, not hidden chain of thought. Never claim access to another "
                "participant's private reasoning or model identity."
            ),
            input=_render_context(context),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "thoughtstage_turn",
                    "strict": True,
                    "schema": ModelOutput.model_json_schema(),
                }
            },
        )
        try:
            return ModelOutput.model_validate_json(_response_text(response))
        except ValidationError as exc:
            raise AzureFoundryResponseError(
                f"Foundry returned an invalid dual output for agent {agent.id!r}"
            ) from exc

    def _generate_reflect_then_post(
        self,
        client: _FoundryClient,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: FoundrySettings,
    ) -> ModelOutput:
        rendered_context = _render_context(context)
        private_request = self._common_request(
            agent, context, settings, max_output_tokens=settings.private_max_output_tokens
        )
        private_response = client.responses.create(
            **private_request,
            instructions=(
                f"{context.system_prompt}\n\n"
                "Write a concise researcher-private soliloquy for this turn. This is an "
                "explicitly elicited reflection, not hidden chain of thought. Do not address "
                "the public audience and do not claim access to anyone else's private state."
            ),
            input=rendered_context,
        )
        soliloquy = _response_text(private_response)

        public_request = self._common_request(
            agent, context, settings, max_output_tokens=settings.public_max_output_tokens
        )
        public_response = client.responses.create(
            **public_request,
            instructions=(
                f"{context.system_prompt}\n\n"
                "Write only the public social-feed post for this turn. Use your private "
                "reflection to inform the post, but never quote, label, or disclose it."
            ),
            input=f"{rendered_context}\n\nYour private reflection for this turn:\n{soliloquy}",
        )
        return ModelOutput(post=_response_text(public_response), soliloquy=soliloquy)

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
    ) -> ModelOutput:
        del seed  # Foundry does not expose a portable seed across all catalog models.
        settings = self._settings(agent)
        client = self._client(agent, settings)
        if settings.output_mode == "reflect_then_post":
            return self._generate_reflect_then_post(
                client, agent=agent, context=context, settings=settings
            )
        return self._generate_structured(client, agent=agent, context=context, settings=settings)
