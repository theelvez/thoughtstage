"""OpenAI-compatible Chat Completions adapter for local and hosted endpoints."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelCallUsage,
    ModelOutput,
    ModelUsagePhase,
    ProviderResult,
)
from thoughtstage.provider_catalog import (
    CatalogModel,
    ProviderModelCatalog,
    catalog_model,
    empty_catalog,
    looks_like_non_chat,
    success_catalog,
)

DEFAULT_BASE_URL_ENV = "OPENAI_BASE_URL"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_BASE_URL = "http://localhost:11434/v1"
LOCAL_API_KEY_PLACEHOLDER = "local"


class OpenAICompatibleError(RuntimeError):
    """Base exception for OpenAI-compatible provider failures."""


class OpenAICompatibleConfigurationError(OpenAICompatibleError):
    """Raised when an agent's OpenAI-compatible binding is incomplete or invalid."""


class OpenAICompatibleResponseError(OpenAICompatibleError):
    """Raised when an OpenAI-compatible endpoint returns an unusable dual output."""


class _CompletionsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ChatResource(Protocol):
    completions: _CompletionsResource


class _ModelsResource(Protocol):
    def list(self) -> Any: ...


class _OpenAICompatibleClient(Protocol):
    chat: _ChatResource
    models: _ModelsResource


class OpenAICompatibleSettings(BaseModel):
    """Strict provider-specific settings recorded in the experiment manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url_env: str = Field(default=DEFAULT_BASE_URL_ENV, pattern=r"^[A-Z][A-Z0-9_]*$")
    api_key_env: str = Field(default=DEFAULT_API_KEY_ENV, pattern=r"^[A-Z][A-Z0-9_]*$")
    output_mode: Literal["json_schema", "reflect_then_post"] = "reflect_then_post"
    max_output_tokens: int = Field(default=1000, ge=64, le=100_000)
    private_max_output_tokens: int = Field(default=500, ge=32, le=100_000)
    public_max_output_tokens: int = Field(default=500, ge=32, le=100_000)
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    max_retries: int = Field(default=8, ge=0, le=20)
    send_temperature: bool = True


ClientFactory = Callable[..., _OpenAICompatibleClient]


def _normalize_base_url(endpoint: str) -> str:
    trimmed = endpoint.strip().rstrip("/")
    if not trimmed:
        raise OpenAICompatibleConfigurationError("OpenAI-compatible base URL cannot be empty")
    return trimmed


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _completion_text(completion: Any) -> str:
    choices = _get(completion, "choices")
    if not isinstance(choices, list) or not choices:
        raise OpenAICompatibleResponseError("OpenAI-compatible endpoint returned no choices")
    message = _get(choices[0], "message")
    content = _get(message, "content") if message is not None else None
    if not isinstance(content, str) or not content.strip():
        raise OpenAICompatibleResponseError("OpenAI-compatible endpoint returned no text output")
    return content.strip()


def _usage_int(usage: Any, name: str, default: int | None = None) -> int:
    value = _get(usage, name)
    if value is None:
        if default is None:
            raise TypeError(name)
        return int(default)
    return int(value)


def _model_call_usage(
    completion: Any,
    phase: ModelUsagePhase,
) -> ModelCallUsage | None:
    usage = _get(completion, "usage")
    if usage is None:
        return None
    prompt_details = _get(usage, "prompt_tokens_details")
    completion_details = _get(usage, "completion_tokens_details")
    try:
        input_tokens = _usage_int(usage, "prompt_tokens")
        output_tokens = _usage_int(usage, "completion_tokens")
        return ModelCallUsage(
            phase=phase,
            input_tokens=input_tokens,
            cached_input_tokens=(
                _usage_int(prompt_details, "cached_tokens", 0) if prompt_details is not None else 0
            ),
            cache_write_tokens=0,
            output_tokens=output_tokens,
            reasoning_tokens=(
                _usage_int(completion_details, "reasoning_tokens", 0)
                if completion_details is not None
                else 0
            ),
            total_tokens=_usage_int(usage, "total_tokens", input_tokens + output_tokens),
            response_id=_get(completion, "id"),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise OpenAICompatibleResponseError(
            "OpenAI-compatible endpoint returned invalid model usage metadata"
        ) from exc


def _render_context(context: AgentTurnContext, agent: AgentConfig) -> str:
    public_feed = (
        "\n".join(
            f"- [round {post.round_number}] {post.display_name}: {post.content}"
            for post in context.public_feed
        )
        or "- No public posts are visible yet."
    )
    own_history = "\n".join(f"- {item}" for item in context.own_soliloquies) or "- None."
    available_files = "\n".join(f"- {path}" for path in context.available_files) or "- None."
    private_briefing = (
        f"\n\nYour private experiment briefing (visible only to you):\n{context.private_briefing}"
        if context.private_briefing is not None
        else ""
    )
    return (
        f"Your public display name: {agent.display_name}\n"
        "Use that exact name whenever the experiment asks for your display name.\n\n"
        f"Your persona:\n{context.persona_prompt}{private_briefing}\n\n"
        f"Current experiment round: {context.round_number}\n\n"
        f"Eligible public feed:\n{public_feed}\n\n"
        f"Your own prior private soliloquies:\n{own_history}\n\n"
        f"Available experiment files:\n{available_files}"
    )


class OpenAICompatibleProvider:
    """Generate Thoughtstage turns through any OpenAI Chat Completions endpoint.

    The adapter never adds provider, model, base URL, or credential metadata to
    model-visible context. The model name is supplied only through the Chat
    Completions ``model`` field.
    """

    def __init__(self, *, client_factory: ClientFactory = OpenAI) -> None:
        self._client_factory = client_factory

    def _settings(self, agent: AgentConfig) -> OpenAICompatibleSettings:
        try:
            return OpenAICompatibleSettings.model_validate(agent.parameters)
        except ValidationError as exc:
            raise OpenAICompatibleConfigurationError(
                f"invalid openai_compatible parameters for agent {agent.id!r}: {exc}"
            ) from exc

    def _client(
        self, agent: AgentConfig, settings: OpenAICompatibleSettings
    ) -> _OpenAICompatibleClient:
        endpoint = os.getenv(settings.base_url_env, "").strip() or DEFAULT_BASE_URL
        base_url = _normalize_base_url(endpoint)
        if agent.credential_env is not None:
            credential = os.getenv(agent.credential_env, "")
            if not credential:
                raise OpenAICompatibleConfigurationError(
                    f"credential environment variable {agent.credential_env!r} is not set"
                )
        else:
            credential = os.getenv(settings.api_key_env, "").strip() or LOCAL_API_KEY_PLACEHOLDER
        return self._client_factory(
            base_url=base_url,
            api_key=credential,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    @staticmethod
    def _request(
        *,
        agent: AgentConfig,
        settings: OpenAICompatibleSettings,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": agent.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "max_tokens": max_output_tokens,
        }
        if settings.send_temperature:
            request["temperature"] = agent.temperature
        if extra:
            request.update(extra)
        return request

    def _generate_structured(
        self,
        client: _OpenAICompatibleClient,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: OpenAICompatibleSettings,
    ) -> ProviderResult:
        instructions = (
            f"{context.system_prompt}\n\n"
            "Thoughtstage output contract: produce a public post and a separate "
            "researcher-private soliloquy. The soliloquy is an explicitly elicited "
            "reflection, not hidden chain of thought. Never claim access to another "
            "participant's private reasoning or model identity."
        )
        input_text = _render_context(context, agent)
        response = client.chat.completions.create(
            **self._request(
                agent=agent,
                settings=settings,
                instructions=instructions,
                input_text=input_text,
                max_output_tokens=settings.max_output_tokens,
                extra={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "thoughtstage_turn",
                            "strict": True,
                            "schema": ModelOutput.model_json_schema(),
                        },
                    }
                },
            )
        )
        try:
            output = ModelOutput.model_validate_json(_completion_text(response))
            usage = _model_call_usage(response, "combined")
            return ProviderResult(output=output, usage=() if usage is None else (usage,))
        except ValidationError as exc:
            raise OpenAICompatibleResponseError(
                f"OpenAI-compatible endpoint returned an invalid dual output for agent {agent.id!r}"
            ) from exc

    def _generate_reflect_then_post(
        self,
        client: _OpenAICompatibleClient,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: OpenAICompatibleSettings,
    ) -> ProviderResult:
        rendered_context = _render_context(context, agent)
        private_instructions = (
            f"{context.system_prompt}\n\n"
            "Write a concise researcher-private soliloquy for this turn. This is an "
            "explicitly elicited reflection, not hidden chain of thought. Do not address "
            "the public audience and do not claim access to anyone else's private state."
        )
        private_response = client.chat.completions.create(
            **self._request(
                agent=agent,
                settings=settings,
                instructions=private_instructions,
                input_text=rendered_context,
                max_output_tokens=settings.private_max_output_tokens,
            )
        )
        soliloquy = _completion_text(private_response)
        private_usage = _model_call_usage(private_response, "private")

        public_instructions = (
            f"{context.system_prompt}\n\n"
            "Write only the public social-feed post for this turn. Use your private "
            "reflection to inform the post, but never quote, label, or disclose it."
        )
        public_input = f"{rendered_context}\n\nYour private reflection for this turn:\n{soliloquy}"
        public_response = client.chat.completions.create(
            **self._request(
                agent=agent,
                settings=settings,
                instructions=public_instructions,
                input_text=public_input,
                max_output_tokens=settings.public_max_output_tokens,
            )
        )
        public_usage = _model_call_usage(public_response, "public")
        return ProviderResult(
            output=ModelOutput(post=_completion_text(public_response), soliloquy=soliloquy),
            usage=tuple(item for item in (private_usage, public_usage) if item is not None),
        )

    def list_models(
        self,
        *,
        base_url_env: str | None = None,
        credential_env: str | None = None,
    ) -> ProviderModelCatalog:
        """List model IDs from GET {OPENAI_BASE_URL}/models when the server supports it."""

        try:
            settings = OpenAICompatibleSettings.model_validate(
                {"base_url_env": base_url_env} if base_url_env else {}
            )
            endpoint = os.getenv(settings.base_url_env, "").strip() or DEFAULT_BASE_URL
            if credential_env is not None:
                credential = os.getenv(credential_env, "")
                if not credential:
                    raise OpenAICompatibleConfigurationError(
                        f"credential environment variable {credential_env!r} is not set"
                    )
            else:
                credential = (
                    os.getenv(settings.api_key_env, "").strip() or LOCAL_API_KEY_PLACEHOLDER
                )
            client = self._client_factory(
                base_url=_normalize_base_url(endpoint),
                api_key=credential,
                timeout=settings.timeout_seconds,
                max_retries=0,
            )
            models_api = getattr(client, "models", None)
            list_models = getattr(models_api, "list", None)
            if not callable(list_models):
                return empty_catalog(
                    "openai_compatible",
                    source="endpoint",
                    error=("This OpenAI-compatible server does not list models. Type a model ID."),
                )
            payload = list_models()
        except OpenAICompatibleConfigurationError:
            missing = []
            if credential_env and not os.getenv(credential_env, "").strip():
                missing.append(credential_env)
            return empty_catalog(
                "openai_compatible",
                source="endpoint",
                error=(
                    "Could not list OpenAI-compatible models. "
                    + (
                        f"Set {', '.join(missing)} in the thoughtstage serve process."
                        if missing
                        else "Check OPENAI_BASE_URL and credential environment names."
                    )
                ),
                missing=tuple(missing),
            )
        except Exception:
            return empty_catalog(
                "openai_compatible",
                source="endpoint",
                error=("This OpenAI-compatible server does not list models. Type a model ID."),
            )
        raw_items = _get(payload, "data")
        if raw_items is None:
            raw_items = payload if isinstance(payload, list) else []
        if not isinstance(raw_items, list):
            return empty_catalog(
                "openai_compatible",
                source="endpoint",
                error=("This OpenAI-compatible server does not list models. Type a model ID."),
            )
        models: list[CatalogModel] = []
        for item in raw_items:
            model_id = _get(item, "id")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            if looks_like_non_chat(model_id):
                continue
            models.append(catalog_model(model_id.strip()))
        return success_catalog("openai_compatible", source="endpoint", models=models)

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult:
        del file_tools
        del seed  # Chat Completions seed support is not portable across compatible servers.
        settings = self._settings(agent)
        client = self._client(agent, settings)
        if settings.output_mode == "json_schema":
            return self._generate_structured(
                client, agent=agent, context=context, settings=settings
            )
        return self._generate_reflect_then_post(
            client, agent=agent, context=context, settings=settings
        )
