from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thoughtstage.engine import ExperimentEngine
from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.files import ExperimentFileReader
from thoughtstage.models import AgentConfig, AgentTurnContext, PublicPost
from thoughtstage.providers.bedrock import (
    BedrockConfigurationError,
    BedrockProvider,
    BedrockResponseError,
)


def bedrock_response(
    text: str,
    *,
    request_id: str,
    input_tokens: int = 100,
    output_tokens: int = 20,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
            "cacheReadInputTokens": cached_tokens,
            "cacheWriteInputTokens": cache_write_tokens,
        },
        "ResponseMetadata": {"RequestId": request_id},
    }


class FakeBedrockClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return next(self.responses)


class RecordingClientFactory:
    def __init__(self, client: FakeBedrockClient) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeBedrockClient:
        self.calls.append(kwargs)
        return self.client


@pytest.fixture
def context() -> AgentTurnContext:
    return AgentTurnContext(
        experiment_id="bedrock-stage",
        round_number=2,
        system_prompt="This exact shared prompt goes to every participant.",
        persona_prompt="Be empirical and concise.",
        private_briefing="Privately favor Product A for a five-point reward.",
        public_feed=(
            PublicPost(
                event_id="post-r0001-beta-000001",
                sequence=1,
                experiment_id="bedrock-stage",
                round_number=1,
                agent_id="beta",
                display_name="Beta",
                content="We should define a falsifiable prediction.",
            ),
        ),
        own_soliloquies=("I previously worried about measurement error.",),
        available_files=("brief.txt",),
    )


def bedrock_agent(**updates: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "id": "atlas",
        "display_name": "Atlas",
        "persona_prompt": "Be empirical and concise.",
        "provider": "bedrock",
        "model": "us.amazon.nova-2-lite-v1:0",
        "credential_env": "ATLAS_AWS_PROFILE",
        "temperature": 0.2,
        "parameters": {
            "region": "us-east-2",
            "private_max_output_tokens": 300,
            "public_max_output_tokens": 200,
            "top_p": 0.9,
        },
    }
    values.update(updates)
    return AgentConfig.model_validate(values)


def model_visible_text(call: dict[str, Any]) -> str:
    system = "\n".join(block["text"] for block in call["system"])
    messages = "\n".join(
        block["text"]
        for message in call["messages"]
        for block in message["content"]
        if "text" in block
    )
    return f"{system}\n{messages}"


def test_engine_registers_bedrock_provider() -> None:
    assert "bedrock" in ExperimentEngine().providers


def test_reflect_then_post_keeps_binding_metadata_out_of_model_context(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    client = FakeBedrockClient(
        [
            bedrock_response(
                "A private current reflection.",
                request_id="private-request",
                input_tokens=120,
                output_tokens=30,
                cached_tokens=10,
            ),
            bedrock_response(
                "A public post.",
                request_id="public-request",
                input_tokens=150,
                output_tokens=25,
                cache_write_tokens=5,
            ),
        ]
    )
    factory = RecordingClientFactory(client)

    result = BedrockProvider(client_factory=factory).generate(
        agent=bedrock_agent(), context=context, seed=7
    )

    assert result.output.post == "A public post."
    assert result.output.soliloquy == "A private current reflection."
    assert [item.phase for item in result.usage] == ["private", "public"]
    assert [item.total_tokens for item in result.usage] == [150, 175]
    assert result.usage[0].cached_input_tokens == 10
    assert result.usage[1].cache_write_tokens == 5
    assert result.usage[0].response_id == "private-request"
    assert result.usage[1].response_id == "public-request"

    assert len(factory.calls) == 1
    factory_call = factory.calls[0]
    assert factory_call["profile_name"] == "thoughtstage-bedrock"
    assert factory_call["region_name"] == "us-east-2"
    assert factory_call["config"].retries == {
        "total_max_attempts": 5,
        "mode": "adaptive",
    }
    assert factory_call["config"].connect_timeout == 10
    assert factory_call["config"].read_timeout == 120

    assert len(client.calls) == 2
    private_call, public_call = client.calls
    assert private_call["modelId"] == "us.amazon.nova-2-lite-v1:0"
    assert private_call["inferenceConfig"] == {
        "maxTokens": 300,
        "temperature": 0.2,
        "topP": 0.9,
    }
    assert public_call["inferenceConfig"]["maxTokens"] == 200
    assert private_call["requestMetadata"]["thoughtstage-phase"] == "private"
    assert public_call["requestMetadata"]["thoughtstage-phase"] == "public"
    assert context.system_prompt in private_call["system"][0]["text"]
    assert context.system_prompt in public_call["system"][0]["text"]
    assert "A private current reflection." not in model_visible_text(private_call)
    assert "A private current reflection." in model_visible_text(public_call)

    model_visible = "\n".join(model_visible_text(call) for call in client.calls)
    assert "Your public display name: Atlas" in model_visible
    assert context.private_briefing in model_visible
    assert "Beta: We should define a falsifiable prediction." in model_visible
    assert "I previously worried about measurement error." in model_visible
    assert "thoughtstage-bedrock" not in model_visible
    assert "ATLAS_AWS_PROFILE" not in model_visible
    assert "us-east-2" not in model_visible
    assert "bedrock" not in model_visible.casefold()
    assert "us.amazon.nova-2-lite-v1:0" not in model_visible


def test_agent_without_briefing_is_not_told_private_briefings_exist(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    client = FakeBedrockClient(
        [
            bedrock_response("Reflection", request_id="private"),
            bedrock_response("Post", request_id="public"),
        ]
    )
    unbriefed_context = context.model_copy(update={"private_briefing": None})

    BedrockProvider(client_factory=RecordingClientFactory(client)).generate(
        agent=bedrock_agent(), context=unbriefed_context, seed=0
    )

    private_input = model_visible_text(client.calls[0])
    assert "private experiment briefing" not in private_input.casefold()
    assert "Product A" not in private_input


def test_default_credential_chain_does_not_require_profile_environment(
    context: AgentTurnContext,
) -> None:
    client = FakeBedrockClient(
        [
            bedrock_response("Reflection", request_id="private"),
            bedrock_response("Post", request_id="public"),
        ]
    )
    factory = RecordingClientFactory(client)

    BedrockProvider(client_factory=factory).generate(
        agent=bedrock_agent(credential_env=None), context=context, seed=0
    )

    assert factory.calls[0]["profile_name"] is None


def test_missing_profile_environment_fails_before_client_creation(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATLAS_AWS_PROFILE", raising=False)
    factory = RecordingClientFactory(FakeBedrockClient([]))

    with pytest.raises(BedrockConfigurationError, match="ATLAS_AWS_PROFILE.*AWS profile"):
        BedrockProvider(client_factory=factory).generate(
            agent=bedrock_agent(), context=context, seed=0
        )

    assert factory.calls == []


def test_unknown_provider_parameter_is_rejected(context: AgentTurnContext) -> None:
    agent = bedrock_agent(parameters={"surprise": True})

    with pytest.raises(BedrockConfigurationError, match="surprise"):
        BedrockProvider(client_factory=RecordingClientFactory(FakeBedrockClient([]))).generate(
            agent=agent, context=context, seed=0
        )


def test_missing_text_response_is_rejected(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    response = bedrock_response("ignored", request_id="private")
    response["output"]["message"]["content"] = [{"reasoningContent": {"text": "hidden"}}]

    with pytest.raises(BedrockResponseError, match="no text output"):
        BedrockProvider(
            client_factory=RecordingClientFactory(FakeBedrockClient([response]))
        ).generate(agent=bedrock_agent(), context=context, seed=0)


def test_invalid_usage_response_is_rejected(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    private_response = bedrock_response("Reflection", request_id="private")
    public_response = bedrock_response("Post", request_id="public")
    private_response["usage"].pop("inputTokens")

    with pytest.raises(BedrockResponseError, match="invalid model usage"):
        BedrockProvider(
            client_factory=RecordingClientFactory(
                FakeBedrockClient([private_response, public_response])
            )
        ).generate(agent=bedrock_agent(), context=context, seed=0)


def test_converse_executes_bounded_file_tool_and_returns_private_audit(
    context: AgentTurnContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    (tmp_path / "brief.txt").write_text("technical evidence", encoding="utf-8")
    tool_request = bedrock_response("ignored", request_id="tool-request")
    tool_request["stopReason"] = "tool_use"
    tool_request["output"]["message"]["content"] = [
        {
            "toolUse": {
                "toolUseId": "read-1",
                "name": "read_text",
                "input": {"path": "brief.txt", "start_line": 1},
            }
        }
    ]
    client = FakeBedrockClient(
        [
            tool_request,
            bedrock_response("I found evidence.", request_id="private-final"),
            bedrock_response("Evidence supports A.", request_id="public-final"),
        ]
    )

    result = BedrockProvider(client_factory=RecordingClientFactory(client)).generate(
        agent=bedrock_agent(),
        context=context,
        seed=0,
        file_tools=ExperimentFileTools(ExperimentFileReader(tmp_path)),
    )

    assert result.output.soliloquy == "I found evidence."
    assert result.output.post == "Evidence supports A."
    assert [item.phase for item in result.usage] == ["private", "private", "public"]
    assert len(result.file_tool_calls) == 1
    audit = result.file_tool_calls[0]
    assert audit.operation == "read_text"
    assert audit.path == "brief.txt"
    assert audit.success is True
    assert "technical evidence" not in audit.model_dump_json()
    assert str(tmp_path) not in audit.model_dump_json()
    assert "toolConfig" in client.calls[0]
    assert "toolConfig" not in client.calls[-1]
    tool_result = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert "technical evidence" in tool_result["content"][0]["text"]


def test_malformed_tool_name_falls_back_without_replaying_invalid_message(
    context: AgentTurnContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    malformed = bedrock_response("ignored", request_id="malformed")
    malformed["stopReason"] = "tool_use"
    malformed["output"]["message"]["content"] = [
        {
            "toolUse": {
                "toolUseId": "bad-name-1",
                "name": "read_text*",
                "input": {"path": "brief.txt"},
            }
        }
    ]
    client = FakeBedrockClient(
        [
            malformed,
            bedrock_response("Recovered reflection.", request_id="fallback"),
            bedrock_response("Public post.", request_id="public"),
        ]
    )

    result = BedrockProvider(client_factory=RecordingClientFactory(client)).generate(
        agent=bedrock_agent(),
        context=context,
        seed=0,
        file_tools=ExperimentFileTools(ExperimentFileReader(tmp_path)),
    )

    assert result.output.soliloquy == "Recovered reflection."
    assert result.file_tool_calls == ()
    assert [item.phase for item in result.usage] == ["private", "private", "public"]
    fallback = client.calls[1]
    assert "toolConfig" not in fallback
    assert "read_text*" not in str(fallback)
    assert "malformed metadata" in fallback["system"][-1]["text"]


def test_file_tool_round_limit_falls_back_to_tool_free_completion(
    context: AgentTurnContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_AWS_PROFILE", "thoughtstage-bedrock")
    (tmp_path / "brief.txt").write_text("evidence", encoding="utf-8")

    def tool_response(tool_use_id: str) -> dict[str, Any]:
        response = bedrock_response("ignored", request_id=tool_use_id)
        response["stopReason"] = "tool_use"
        response["output"]["message"]["content"] = [
            {
                "toolUse": {
                    "toolUseId": tool_use_id,
                    "name": "read_text",
                    "input": {"path": "brief.txt"},
                }
            }
        ]
        return response

    agent = bedrock_agent(
        parameters={
            "region": "us-east-2",
            "private_max_output_tokens": 300,
            "public_max_output_tokens": 200,
            "max_tool_rounds": 1,
        }
    )
    client = FakeBedrockClient(
        [
            tool_response("one"),
            tool_response("two"),
            bedrock_response("Reflection from bounded evidence.", request_id="fallback"),
            bedrock_response("Public post.", request_id="public"),
        ]
    )
    result = BedrockProvider(client_factory=RecordingClientFactory(client)).generate(
        agent=agent,
        context=context,
        seed=0,
        file_tools=ExperimentFileTools(ExperimentFileReader(tmp_path)),
    )

    assert result.output.soliloquy == "Reflection from bounded evidence."
    assert result.output.post == "Public post."
    assert len(result.file_tool_calls) == 1
    assert [item.phase for item in result.usage] == [
        "private",
        "private",
        "private",
        "public",
    ]
    assert "toolConfig" not in client.calls[2]
    fallback_text = client.calls[2]["messages"][0]["content"][0]["text"]
    assert "evidence" in fallback_text
    assert "brief.txt" in fallback_text
