"""Amazon Bedrock adapter using the unified Converse API."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any, Literal, Protocol

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    FileToolCall,
    ModelCallUsage,
    ModelOutput,
    ModelUsagePhase,
    ProviderResult,
)

DEFAULT_REGION = "us-east-2"
_BEDROCK_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


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
    max_tool_rounds: int = Field(default=12, ge=1, le=100)
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


def _response_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["output"]["message"]
    except (KeyError, TypeError) as exc:
        raise BedrockResponseError("Bedrock returned no message content") from exc
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        raise BedrockResponseError("Bedrock returned invalid message content")
    return message


def _response_text(response: dict[str, Any]) -> str:
    content = _response_message(response)["content"]
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


def _bedrock_tool_config(file_tools: ExperimentFileTools) -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "inputSchema": {"json": definition["input_schema"]},
                }
            }
            for definition in file_tools.definitions
        ]
    }


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
            retries={"total_max_attempts": settings.max_attempts, "mode": "adaptive"},
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
        file_tools: ExperimentFileTools | None,
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
        if file_tools is not None and context.available_files:
            request["toolConfig"] = _bedrock_tool_config(file_tools)
        return request

    @staticmethod
    def _converse_text(
        *,
        client: _BedrockRuntimeClient,
        request: dict[str, Any],
        phase: ModelUsagePhase,
        file_tools: ExperimentFileTools | None,
        max_tool_rounds: int,
    ) -> tuple[str, tuple[ModelCallUsage, ...], tuple[FileToolCall, ...]]:
        usage: list[ModelCallUsage] = []
        calls: list[FileToolCall] = []
        tool_rounds = 0
        evidence_by_hash: dict[str, str] = {}

        try:
            initial_input = request["messages"][0]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - internal contract
            raise BedrockResponseError("Bedrock request has no initial text input") from exc

        def complete_without_tools(
            reason: str,
        ) -> tuple[str, tuple[ModelCallUsage, ...], tuple[FileToolCall, ...]]:
            evidence = "\n\n".join(evidence_by_hash.values())[:200_000]
            fallback_request = {
                key: value
                for key, value in request.items()
                if key not in {"messages", "toolConfig"}
            }
            fallback_request["system"] = [
                *request["system"],
                {
                    "text": (
                        f"{reason} Do not request additional tools. Complete the requested "
                        "output now using only the validated evidence already gathered."
                    )
                },
            ]
            fallback_request["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"{initial_input}\n\nValidated evidence gathered from "
                                f"experiment files:\n{evidence or '- None.'}"
                            )
                        }
                    ],
                }
            ]
            fallback_response = client.converse(**fallback_request)
            fallback_usage = _model_call_usage(fallback_response, phase)
            if fallback_usage is not None:
                usage.append(fallback_usage)
            return _response_text(fallback_response), tuple(usage), tuple(calls)

        while True:
            response = client.converse(**request)
            call_usage = _model_call_usage(response, phase)
            if call_usage is not None:
                usage.append(call_usage)
            message = _response_message(response)
            tool_blocks = [
                block["toolUse"]
                for block in message["content"]
                if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
            ]
            if not tool_blocks:
                return _response_text(response), tuple(usage), tuple(calls)
            if file_tools is None or "toolConfig" not in request:
                raise BedrockResponseError("Bedrock requested an unavailable experiment file tool")

            tool_rounds += 1
            if tool_rounds > max_tool_rounds:
                return complete_without_tools("The experiment file-tool budget is exhausted.")

            validated_tool_blocks: list[tuple[dict[str, Any], str, str]] = []
            for tool_use in tool_blocks:
                tool_use_id = tool_use.get("toolUseId")
                name = tool_use.get("name")
                if (
                    not isinstance(tool_use_id, str)
                    or not tool_use_id
                    or len(tool_use_id) > 256
                    or not isinstance(name, str)
                    or _BEDROCK_TOOL_NAME.fullmatch(name) is None
                ):
                    return complete_without_tools(
                        "A requested experiment file tool had malformed metadata."
                    )
                validated_tool_blocks.append((tool_use, tool_use_id, name))

            request["messages"].append(message)
            tool_results: list[dict[str, Any]] = []
            for tool_use, tool_use_id, name in validated_tool_blocks:
                result_text, call = file_tools.execute(
                    name=name,
                    tool_use_id=tool_use_id,
                    phase=phase,
                    raw_input=tool_use.get("input"),
                )
                calls.append(call)
                evidence_by_hash.setdefault(call.result_sha256, result_text)
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": result_text}],
                            "status": "success" if call.success else "error",
                        }
                    }
                )
            request["messages"].append({"role": "user", "content": tool_results})

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
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
        soliloquy, private_usage, private_tool_calls = self._converse_text(
            client=client,
            request=self._request(
                agent=agent,
                context=context,
                settings=settings,
                phase="private",
                instructions=private_instructions,
                input_text=rendered_context,
                max_output_tokens=settings.private_max_output_tokens,
                file_tools=file_tools,
            ),
            phase="private",
            file_tools=file_tools,
            max_tool_rounds=settings.max_tool_rounds,
        )

        public_instructions = (
            f"{context.system_prompt}\n\n"
            "Write only the public social-feed post for this turn. Use your private "
            "reflection to inform the post, but never quote, label, or disclose it."
        )
        public_input = f"{rendered_context}\n\nYour private reflection for this turn:\n{soliloquy}"
        post, public_usage, public_tool_calls = self._converse_text(
            client=client,
            request=self._request(
                agent=agent,
                context=context,
                settings=settings,
                phase="public",
                instructions=public_instructions,
                input_text=public_input,
                max_output_tokens=settings.public_max_output_tokens,
                file_tools=None,
            ),
            phase="public",
            file_tools=None,
            max_tool_rounds=settings.max_tool_rounds,
        )
        return ProviderResult(
            output=ModelOutput(post=post, soliloquy=soliloquy),
            usage=private_usage + public_usage,
            file_tool_calls=private_tool_calls + public_tool_calls,
        )
