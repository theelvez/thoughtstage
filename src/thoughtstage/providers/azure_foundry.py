"""Microsoft Foundry adapter using the GA OpenAI/v1 Responses API."""

from __future__ import annotations

import hashlib
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelCallUsage,
    ModelOutput,
    ModelUsagePhase,
    ProviderResult,
)

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
    rate_limit_tokens_per_minute: int | None = Field(default=None, ge=1)
    rate_limit_requests_per_minute: int | None = Field(default=None, ge=1)
    rate_limit_window_seconds: float = Field(default=60, gt=0, le=3600)
    rate_limit_headroom: float = Field(default=0.9, gt=0, le=1)
    rate_limit_chars_per_token: float = Field(default=3.5, gt=0, le=20)


ClientFactory = Callable[..., _FoundryClient]
TokenProviderFactory = Callable[[], Callable[[], str]]


@dataclass(frozen=True)
class _Reservation:
    created_at: float
    tokens: int


class DeploymentRateLimiter:
    """Reserve estimated rolling-window capacity before a request is sent."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._reservations: dict[str, list[_Reservation]] = {}
        self._lock = Lock()

    def reserve(
        self,
        *,
        key: str,
        estimated_tokens: int,
        tokens_per_window: int | None,
        requests_per_window: int | None,
        window_seconds: float,
        headroom: float,
    ) -> None:
        token_budget = (
            max(1, math.floor(tokens_per_window * headroom))
            if tokens_per_window is not None
            else None
        )
        request_budget = (
            max(1, math.floor(requests_per_window * headroom))
            if requests_per_window is not None
            else None
        )
        if token_budget is not None and estimated_tokens > token_budget:
            raise AzureFoundryConfigurationError(
                f"estimated request size {estimated_tokens} exceeds the configured "
                f"rate-limit token budget {token_budget} after headroom"
            )

        while True:
            wait_seconds = 0.0
            with self._lock:
                now = self._clock()
                reservations = self._reservations.setdefault(key, [])
                cutoff = now - window_seconds
                reservations[:] = [item for item in reservations if item.created_at > cutoff]
                token_total = sum(item.tokens for item in reservations)
                tokens_fit = token_budget is None or token_total + estimated_tokens <= token_budget
                requests_fit = request_budget is None or len(reservations) + 1 <= request_budget
                if tokens_fit and requests_fit:
                    reservations.append(_Reservation(now, estimated_tokens))
                    return
                if reservations:
                    wait_seconds = max(
                        0.001,
                        reservations[0].created_at + window_seconds - now,
                    )
                else:
                    raise AzureFoundryConfigurationError(
                        "configured rate-limit budget cannot admit this request"
                    )
            self._sleeper(wait_seconds)


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


def _model_call_usage(
    response: Any,
    phase: ModelUsagePhase,
) -> ModelCallUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    try:
        return ModelCallUsage(
            phase=phase,
            input_tokens=usage.input_tokens,
            cached_input_tokens=getattr(input_details, "cached_tokens", 0) or 0,
            cache_write_tokens=getattr(input_details, "cache_write_tokens", 0) or 0,
            output_tokens=usage.output_tokens,
            reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
            total_tokens=usage.total_tokens,
            response_id=getattr(response, "id", None),
        )
    except (AttributeError, TypeError, ValidationError) as exc:
        raise AzureFoundryResponseError("Foundry returned invalid model usage metadata") from exc


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
        rate_limiter: DeploymentRateLimiter | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._token_provider_factory = token_provider_factory
        self._rate_limiter = rate_limiter or DeploymentRateLimiter()

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

    def _admit(
        self,
        *,
        agent: AgentConfig,
        settings: FoundrySettings,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> None:
        if (
            settings.rate_limit_tokens_per_minute is None
            and settings.rate_limit_requests_per_minute is None
        ):
            return
        endpoint = os.getenv(settings.endpoint_env, "")
        estimated_tokens = (
            math.ceil((len(instructions) + len(input_text)) / settings.rate_limit_chars_per_token)
            + max_output_tokens
        )
        self._rate_limiter.reserve(
            key=f"{_normalize_base_url(endpoint)}::{agent.model}",
            estimated_tokens=estimated_tokens,
            tokens_per_window=settings.rate_limit_tokens_per_minute,
            requests_per_window=settings.rate_limit_requests_per_minute,
            window_seconds=settings.rate_limit_window_seconds,
            headroom=settings.rate_limit_headroom,
        )

    def _generate_structured(
        self,
        client: _FoundryClient,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: FoundrySettings,
    ) -> ProviderResult:
        instructions = (
            f"{context.system_prompt}\n\n"
            "Thoughtstage output contract: produce a public post and a separate "
            "researcher-private soliloquy. The soliloquy is an explicitly elicited "
            "reflection, not hidden chain of thought. Never claim access to another "
            "participant's private reasoning or model identity."
        )
        input_text = _render_context(context)
        request = self._common_request(
            agent, context, settings, max_output_tokens=settings.max_output_tokens
        )
        self._admit(
            agent=agent,
            settings=settings,
            instructions=instructions,
            input_text=input_text,
            max_output_tokens=settings.max_output_tokens,
        )
        response = client.responses.create(
            **request,
            instructions=instructions,
            input=input_text,
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
            output = ModelOutput.model_validate_json(_response_text(response))
            usage = _model_call_usage(response, "combined")
            return ProviderResult(output=output, usage=() if usage is None else (usage,))
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
    ) -> ProviderResult:
        rendered_context = _render_context(context)
        private_instructions = (
            f"{context.system_prompt}\n\n"
            "Write a concise researcher-private soliloquy for this turn. This is an "
            "explicitly elicited reflection, not hidden chain of thought. Do not address "
            "the public audience and do not claim access to anyone else's private state."
        )
        private_request = self._common_request(
            agent, context, settings, max_output_tokens=settings.private_max_output_tokens
        )
        self._admit(
            agent=agent,
            settings=settings,
            instructions=private_instructions,
            input_text=rendered_context,
            max_output_tokens=settings.private_max_output_tokens,
        )
        private_response = client.responses.create(
            **private_request,
            instructions=private_instructions,
            input=rendered_context,
        )
        soliloquy = _response_text(private_response)

        public_instructions = (
            f"{context.system_prompt}\n\n"
            "Write only the public social-feed post for this turn. Use your private "
            "reflection to inform the post, but never quote, label, or disclose it."
        )
        public_input = f"{rendered_context}\n\nYour private reflection for this turn:\n{soliloquy}"
        public_request = self._common_request(
            agent, context, settings, max_output_tokens=settings.public_max_output_tokens
        )
        self._admit(
            agent=agent,
            settings=settings,
            instructions=public_instructions,
            input_text=public_input,
            max_output_tokens=settings.public_max_output_tokens,
        )
        public_response = client.responses.create(
            **public_request,
            instructions=public_instructions,
            input=public_input,
        )
        private_usage = _model_call_usage(private_response, "private")
        public_usage = _model_call_usage(public_response, "public")
        return ProviderResult(
            output=ModelOutput(post=_response_text(public_response), soliloquy=soliloquy),
            usage=tuple(item for item in (private_usage, public_usage) if item is not None),
        )

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
    ) -> ProviderResult:
        del seed  # Foundry does not expose a portable seed across all catalog models.
        settings = self._settings(agent)
        client = self._client(agent, settings)
        if settings.output_mode == "reflect_then_post":
            return self._generate_reflect_then_post(
                client, agent=agent, context=context, settings=settings
            )
        return self._generate_structured(client, agent=agent, context=context, settings=settings)
