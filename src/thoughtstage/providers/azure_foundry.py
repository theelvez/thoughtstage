"""Microsoft Foundry adapter using the GA OpenAI/v1 Responses API."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI, RateLimitError
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

DEFAULT_ENDPOINT_ENV = "AZURE_FOUNDRY_ENDPOINT"
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
COGNITIVE_SERVICES_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
FOUNDRY_DEPLOYMENTS_API_VERSION = "2024-10-21"
FOUNDRY_LIST_TIMEOUT_SECONDS = 20.0


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
    capacity_retry_attempts: int = Field(default=3, ge=0, le=10)
    capacity_cooldown_seconds: float = Field(default=60, gt=0, le=3600)


ClientFactory = Callable[..., _FoundryClient]
TokenProviderFactory = Callable[[], Callable[[], str]]
JsonGetter = Callable[[str, dict[str, str], float], Any]


def _default_json_getter(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AzureFoundryError(f"Foundry catalog HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise AzureFoundryError("Foundry catalog request failed") from exc
    except json.JSONDecodeError as exc:
        raise AzureFoundryError("Foundry catalog returned invalid JSON") from exc
    return payload


def _resource_root(endpoint: str) -> str:
    trimmed = endpoint.strip().rstrip("/")
    if trimmed.endswith("/openai/v1"):
        return trimmed[: -len("/openai/v1")]
    return trimmed


def _deployment_id(item: Any) -> str | None:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if not isinstance(item, dict):
        return None
    for key in ("id", "name", "deployment_name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip() and "/" not in value:
            return value.strip()
    properties = item.get("properties")
    if isinstance(properties, dict):
        for key in ("id", "name"):
            value = properties.get(key)
            if isinstance(value, str) and value.strip() and "/" not in value:
                return value.strip()
    return None


def _capability_flags(item: Any) -> dict[str, bool]:
    if not isinstance(item, dict):
        return {}
    raw = item.get("capabilities")
    if raw is None and isinstance(item.get("properties"), dict):
        raw = item["properties"].get("capabilities")
    if not isinstance(raw, dict):
        return {}
    flags: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            flags[str(key).replace("_", "").lower()] = value
    return flags


def _is_chat_deployment(item: Any, deployment_id: str) -> bool:
    flags = _capability_flags(item)
    chat = flags.get("chatcompletion") or flags.get("completion")
    embeddings = flags.get("embeddings")
    if chat is False and embeddings is True:
        return False
    if embeddings is True and chat is not True:
        return False
    return not looks_like_non_chat(deployment_id)


def _iter_catalog_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "value", "deployments", "models"):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    return []


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
        json_getter: JsonGetter = _default_json_getter,
        rate_limiter: DeploymentRateLimiter | None = None,
        capacity_sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client_factory = client_factory
        self._token_provider_factory = token_provider_factory
        self._json_getter = json_getter
        self._rate_limiter = rate_limiter or DeploymentRateLimiter()
        self._capacity_sleeper = capacity_sleeper

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

    @staticmethod
    def _is_no_capacity(error: RateLimitError) -> bool:
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            detail = body.get("error", body)
            if isinstance(detail, dict) and detail.get("code") == "no_capacity":
                return True
        return "no_capacity" in str(error)

    def _create_response(
        self,
        client: _FoundryClient,
        *,
        agent: AgentConfig,
        settings: FoundrySettings,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        request: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Any:
        for attempt in range(settings.capacity_retry_attempts + 1):
            if attempt > 0:
                self._admit(
                    agent=agent,
                    settings=settings,
                    instructions=instructions,
                    input_text=input_text,
                    max_output_tokens=max_output_tokens,
                )
            try:
                return client.responses.create(
                    **request,
                    instructions=instructions,
                    input=input_text,
                    **(extra or {}),
                )
            except RateLimitError as exc:
                if not self._is_no_capacity(exc) or attempt >= settings.capacity_retry_attempts:
                    raise
                self._capacity_sleeper(settings.capacity_cooldown_seconds)
        raise AssertionError("capacity retry loop did not return or raise")

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
        input_text = _render_context(context, agent)
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
        response = self._create_response(
            client,
            agent=agent,
            settings=settings,
            instructions=instructions,
            input_text=input_text,
            max_output_tokens=settings.max_output_tokens,
            request=request,
            extra={
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "thoughtstage_turn",
                        "strict": True,
                        "schema": ModelOutput.model_json_schema(),
                    }
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
        rendered_context = _render_context(context, agent)
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
        private_response = self._create_response(
            client,
            agent=agent,
            settings=settings,
            instructions=private_instructions,
            input_text=rendered_context,
            max_output_tokens=settings.private_max_output_tokens,
            request=private_request,
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
        public_response = self._create_response(
            client,
            agent=agent,
            settings=settings,
            instructions=public_instructions,
            input_text=public_input,
            max_output_tokens=settings.public_max_output_tokens,
            request=public_request,
        )
        private_usage = _model_call_usage(private_response, "private")
        public_usage = _model_call_usage(public_response, "public")
        return ProviderResult(
            output=ModelOutput(post=_response_text(public_response), soliloquy=soliloquy),
            usage=tuple(item for item in (private_usage, public_usage) if item is not None),
        )

    def _catalog_headers(self, credential_env: str | None) -> dict[str, str]:
        if credential_env is not None:
            credential = os.getenv(credential_env, "")
            if not credential.strip():
                raise AzureFoundryConfigurationError(
                    f"credential environment variable {credential_env!r} is not set"
                )
            return {"api-key": credential, "Accept": "application/json"}
        token = self._token_provider_factory()()
        if not token or not str(token).strip():
            raise AzureFoundryConfigurationError("Entra token provider returned an empty token")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _fetch_foundry_items(self, endpoint: str, headers: dict[str, str]) -> list[Any]:
        root = _resource_root(endpoint)
        deployments_url = f"{root}/openai/deployments?api-version={FOUNDRY_DEPLOYMENTS_API_VERSION}"
        last_error: AzureFoundryError | None = None
        saw_success = False
        for url in (
            deployments_url,
            f"{_normalize_base_url(endpoint).rstrip('/')}/models",
        ):
            try:
                payload = self._json_getter(url, headers, FOUNDRY_LIST_TIMEOUT_SECONDS)
            except AzureFoundryError as exc:
                last_error = exc
                continue
            saw_success = True
            items = _iter_catalog_items(payload)
            if items:
                return items
        if last_error is not None and not saw_success:
            raise last_error
        return []

    def list_models(
        self,
        *,
        endpoint_env: str | None = None,
        credential_env: str | None = None,
    ) -> ProviderModelCatalog:
        """List chat-capable deployments on the configured Foundry endpoint."""

        env_name = endpoint_env or DEFAULT_ENDPOINT_ENV
        endpoint = os.getenv(env_name, "").strip()
        missing: list[str] = []
        if not endpoint:
            missing.append(env_name)
        if credential_env and not os.getenv(credential_env, "").strip():
            missing.append(credential_env)
        if missing:
            return empty_catalog(
                "azure_foundry",
                source="endpoint",
                error=(
                    "Could not list Foundry deployments. Set "
                    + ", ".join(missing)
                    + " in the thoughtstage serve process."
                ),
                missing=tuple(missing),
            )
        try:
            headers = self._catalog_headers(credential_env)
            items = self._fetch_foundry_items(endpoint, headers)
        except Exception:
            return empty_catalog(
                "azure_foundry",
                source="endpoint",
                error=(f"Could not list Foundry deployments. Check Entra login and {env_name}."),
                missing=(),
            )
        models: list[CatalogModel] = []
        for item in items:
            deployment_id = _deployment_id(item)
            if deployment_id is None or not _is_chat_deployment(item, deployment_id):
                continue
            models.append(catalog_model(deployment_id))
        return success_catalog("azure_foundry", source="endpoint", models=models)

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult:
        del file_tools
        del seed  # Foundry does not expose a portable seed across all catalog models.
        settings = self._settings(agent)
        client = self._client(agent, settings)
        if settings.output_mode == "reflect_then_post":
            return self._generate_reflect_then_post(
                client, agent=agent, context=context, settings=settings
            )
        return self._generate_structured(client, agent=agent, context=context, settings=settings)
