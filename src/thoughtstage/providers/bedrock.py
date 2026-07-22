"""Amazon Bedrock adapter using the unified Converse API."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal, Protocol

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelCallUsage,
    ModelOutput,
    ModelUsagePhase,
    ProviderResult,
)

DEFAULT_REGION = "us-east-2"


class BedrockError(RuntimeError):
    """Base exception for Bedrock provider failures."""


class BedrockConfigurationError(BedrockError):
    """Raised when an agent's Bedrock binding is incomplete or invalid."""


class BedrockResponseError(BedrockError):
    """Raised when Bedrock returns an unusable response."""


class _BedrockRuntimeClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


class BedrockSettings(BaseModel):
    """Strict provider-specific settings recorded in the experiment manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    region: str = Field(default=DEFAULT_REGION, pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
    private_max_output_tokens: int = Field(default=400, ge=32, le=100_000)
    public_max_output_tokens: int = Field(default=400, ge=32, le=100_000)
    connect_timeout_seconds: float = Field(default=10, gt=0, le=3600)
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    max_attempts: int = Field(default=5, ge=1, le=20)
    send_temperature: bool = True
    top_p: float | None = Field(default=None, gt=0, le=1)
    service_tier: Literal["default", "flex", "priority"] | None = None


ClientFactory = Callable[..., _BedrockRuntimeClient]


def _default_client_factory(
    *,
    profile_name: str | None,
    region_name: str,
    config: Config,
) -> _BedrockRuntimeClient:
    session = boto3.Session(profile_name=profile_name, region_name=region_name)
    return session.client("bedrock-runtime", config=config)


def _response_text(response: dict[str, Any]) -> str:
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise BedrockResponseError("Bedrock returned no message content") from exc
    if not isinstance(content, list):
        raise BedrockResponseError("Bedrock returned invalid message content")
    text = "".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ).strip()
    if not text:
        raise BedrockResponseError("Bedrock returned no text output")
    return text


def _model_call_usage(
    response: dict[str, Any],
    phase: ModelUsagePhase,
) -> ModelCallUsage | None:
    usage = response.get("usage")
    if usage is None:
        return None
    metadata = response.get("ResponseMetadata", {})
    try:
        return ModelCallUsage(
            phase=phase,
            input_tokens=usage["inputTokens"],
            cached_input_tokens=usage.get("cacheReadInputTokens", 0) or 0,
            cache_write_tokens=usage.get("cacheWriteInputTokens", 0) or 0,
            output_tokens=usage["outputTokens"],
            reasoning_tokens=usage.get("reasoningTokens", 0) or 0,
            total_tokens=usage["totalTokens"],
            response_id=metadata.get("RequestId"),
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise BedrockResponseError("Bedrock returned invalid model usage metadata") from exc


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


class BedrockProvider:
    """Generate Thoughtstage turns through Amazon Bedrock Converse.

    The adapter never adds provider, model, region, profile, or credential
    metadata to model-visible context. The model ID is supplied only through
    Converse's ``modelId`` field.
    """

    def __init__(self, *, client_factory: ClientFactory = _default_client_factory) -> None:
        self._client_factory = client_factory

    def _settings(self, agent: AgentConfig) -> BedrockSettings:
        try:
            return BedrockSettings.model_validate(agent.parameters)
        except ValidationError as exc:
            raise BedrockConfigurationError(
                f"invalid bedrock parameters for agent {agent.id!r}: {exc}"
            ) from exc

    def _client(
        self,
        agent: AgentConfig,
        settings: BedrockSettings,
    ) -> _BedrockRuntimeClient:
        profile_name: str | None = None
        if agent.credential_env is not None:
            profile_name = os.getenv(agent.credential_env, "").strip()
            if not profile_name:
                raise BedrockConfigurationError(
                    f"credential environment variable {agent.credential_env!r} must contain "
                    f"an AWS profile name for agent {agent.id!r}"
                )
        config = Config(
            retries={"max_attempts": settings.max_attempts, "mode": "adaptive"},
            connect_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.timeout_seconds,
        )
        return self._client_factory(
            profile_name=profile_name,
            region_name=settings.region,
            config=config,
        )

    @staticmethod
    def _request(
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        settings: BedrockSettings,
        phase: ModelUsagePhase,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        inference_config: dict[str, Any] = {"maxTokens": max_output_tokens}
        if settings.send_temperature:
            inference_config["temperature"] = agent.temperature
        if settings.top_p is not None:
            inference_config["topP"] = settings.top_p
        request: dict[str, Any] = {
            "modelId": agent.model,
            "system": [{"text": instructions}],
            "messages": [{"role": "user", "content": [{"text": input_text}]}],
            "inferenceConfig": inference_config,
            "requestMetadata": {
                "thoughtstage-experiment": context.experiment_id,
                "thoughtstage-agent": agent.id,
                "thoughtstage-phase": phase,
            },
        }
        if settings.service_tier is not None:
            request["serviceTier"] = {"type": settings.service_tier}
        return request

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
    ) -> ProviderResult:
        del seed  # Converse does not expose a portable seed across Bedrock models.
        settings = self._settings(agent)
        client = self._client(agent, settings)
        rendered_context = _render_context(context, agent)

        private_instructions = (
            f"{context.system_prompt}\n\n"
            "Write a concise researcher-private soliloquy for this turn. This is an "
            "explicitly elicited reflection, not hidden chain of thought. Do not address "
            "the public audience and do not claim access to anyone else's private state."
        )
        private_response = client.converse(
            **self._request(
                agent=agent,
                context=context,
                settings=settings,
                phase="private",
                instructions=private_instructions,
                input_text=rendered_context,
                max_output_tokens=settings.private_max_output_tokens,
            )
        )
        soliloquy = _response_text(private_response)

        public_instructions = (
            f"{context.system_prompt}\n\n"
            "Write only the public social-feed post for this turn. Use your private "
            "reflection to inform the post, but never quote, label, or disclose it."
        )
        public_input = f"{rendered_context}\n\nYour private reflection for this turn:\n{soliloquy}"
        public_response = client.converse(
            **self._request(
                agent=agent,
                context=context,
                settings=settings,
                phase="public",
                instructions=public_instructions,
                input_text=public_input,
                max_output_tokens=settings.public_max_output_tokens,
            )
        )

        private_usage = _model_call_usage(private_response, "private")
        public_usage = _model_call_usage(public_response, "public")
        return ProviderResult(
            output=ModelOutput(post=_response_text(public_response), soliloquy=soliloquy),
            usage=tuple(item for item in (private_usage, public_usage) if item is not None),
        )
