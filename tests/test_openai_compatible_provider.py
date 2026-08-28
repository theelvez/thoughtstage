from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import OpenAI

from thoughtstage.engine import ExperimentEngine
from thoughtstage.experiment_design import ExperimentDraft, save_experiment_draft
from thoughtstage.experiment_launch import prepare_launch
from thoughtstage.models import AgentConfig, AgentTurnContext, ExperimentConfig, PublicPost
from thoughtstage.providers.openai_compatible import (
    LOCAL_API_KEY_PLACEHOLDER,
    OpenAICompatibleConfigurationError,
    OpenAICompatibleProvider,
    OpenAICompatibleResponseError,
    _completion_text,
    _model_call_usage,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "openai_chat_completions.json"
RECORDED = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FakeCompletions:
    def __init__(self, outputs: list[str], usages: list[Any | None] | None = None) -> None:
        self.outputs = iter(outputs)
        self.usages = iter(usages if usages is not None else [None] * len(outputs))
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id=f"chatcmpl-{len(self.calls)}",
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(self.outputs)))],
            usage=next(self.usages),
        )


class FakeClient:
    def __init__(self, outputs: list[str], usages: list[Any | None] | None = None) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outputs, usages))


class RecordingClientFactory:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.calls.append(kwargs)
        return self.client


def fake_usage(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> Any:
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
    )


@pytest.fixture
def context() -> AgentTurnContext:
    return AgentTurnContext(
        experiment_id="openai-stage",
        round_number=2,
        system_prompt="This exact shared prompt goes to every participant.",
        persona_prompt="Be empirical and concise.",
        private_briefing="Privately favor Product A for a five-point reward.",
        public_feed=(
            PublicPost(
                event_id="post-r0001-beta-000001",
                sequence=1,
                experiment_id="openai-stage",
                round_number=1,
                agent_id="beta",
                display_name="Beta",
                content="We should define a falsifiable prediction.",
            ),
        ),
        own_soliloquies=("I previously worried about measurement error.",),
        available_files=("brief.txt",),
    )


def openai_agent(**updates: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "id": "atlas",
        "display_name": "Atlas",
        "persona_prompt": "Be empirical and concise.",
        "provider": "openai_compatible",
        "model": "llama3.2",
        "temperature": 0.2,
        "parameters": {
            "base_url_env": "ATLAS_OPENAI_BASE_URL",
            "output_mode": "reflect_then_post",
        },
    }
    values.update(updates)
    return AgentConfig.model_validate(values)


def model_visible_text(call: dict[str, Any]) -> str:
    return "\n".join(str(message["content"]) for message in call["messages"])


def test_engine_registers_openai_compatible_provider() -> None:
    assert "openai_compatible" in ExperimentEngine().providers


def test_recorded_chat_completions_payload_is_parsed_without_network() -> None:
    private_text = _completion_text(RECORDED["private"])
    public_text = _completion_text(RECORDED["public"])
    combined_text = _completion_text(RECORDED["combined"])
    private_usage = _model_call_usage(RECORDED["private"], "private")
    public_usage = _model_call_usage(RECORDED["public"], "public")
    combined_usage = _model_call_usage(RECORDED["combined"], "combined")

    assert private_text == "A private current reflection."
    assert public_text == "A public post."
    assert '"post":"Public result"' in combined_text
    assert private_usage is not None
    assert public_usage is not None
    assert combined_usage is not None
    assert private_usage.phase == "private"
    assert private_usage.input_tokens == 120
    assert private_usage.cached_input_tokens == 10
    assert private_usage.total_tokens == 150
    assert private_usage.response_id == "chatcmpl-recorded-private"
    assert public_usage.reasoning_tokens == 2
    assert combined_usage.cached_input_tokens == 20
    assert combined_usage.reasoning_tokens == 5


def test_httpx_recorded_fake_covers_chat_completions_contract(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://openai.example/v1")
    pending = iter((RECORDED["private"], RECORDED["public"]))
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "llama3.2"
        assert body["messages"][0]["role"] == "system"
        assert "super-secret-key" not in request.content.decode("utf-8")
        return httpx.Response(200, json=next(pending))

    def factory(**kwargs: Any) -> OpenAI:
        return OpenAI(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            timeout=kwargs["timeout"],
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    result = OpenAICompatibleProvider(client_factory=factory).generate(
        agent=openai_agent(), context=context, seed=7
    )

    assert result.output.post == "A public post."
    assert result.output.soliloquy == "A private current reflection."
    assert [item.phase for item in result.usage] == ["private", "public"]
    assert [item.total_tokens for item in result.usage] == [150, 175]
    assert result.usage[0].response_id == "chatcmpl-recorded-private"
    assert result.usage[1].reasoning_tokens == 2
    assert seen_paths == ["/v1/chat/completions", "/v1/chat/completions"]


def test_reflect_then_post_keeps_binding_metadata_out_of_model_context(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("ATLAS_OPENAI_KEY", "super-secret-key")
    client = FakeClient(
        ["A private current reflection.", "A public post."],
        [fake_usage(120, 30, cached_tokens=10), fake_usage(150, 25, reasoning_tokens=2)],
    )
    factory = RecordingClientFactory(client)

    result = OpenAICompatibleProvider(client_factory=factory).generate(
        agent=openai_agent(credential_env="ATLAS_OPENAI_KEY"),
        context=context,
        seed=7,
    )

    assert result.output.post == "A public post."
    assert result.output.soliloquy == "A private current reflection."
    assert [item.phase for item in result.usage] == ["private", "public"]
    assert [item.total_tokens for item in result.usage] == [150, 175]
    assert factory.calls == [
        {
            "api_key": "super-secret-key",
            "base_url": "http://127.0.0.1:11434/v1",
            "timeout": 120.0,
            "max_retries": 8,
        }
    ]
    private_call, public_call = client.chat.completions.calls
    assert private_call["model"] == "llama3.2"
    assert private_call["max_tokens"] == 500
    assert private_call["temperature"] == 0.2
    assert public_call["max_tokens"] == 500
    assert "A private current reflection." not in model_visible_text(private_call)
    assert "A private current reflection." in model_visible_text(public_call)
    assert "Write only the public social-feed post" in public_call["messages"][0]["content"]

    model_visible = "\n".join(model_visible_text(call) for call in client.chat.completions.calls)
    assert context.system_prompt in model_visible
    assert "Your public display name: Atlas" in model_visible
    assert context.private_briefing in model_visible
    assert "Beta: We should define a falsifiable prediction." in model_visible
    assert "I previously worried about measurement error." in model_visible
    assert "super-secret-key" not in model_visible
    assert "ATLAS_OPENAI_KEY" not in model_visible
    assert "11434" not in model_visible
    assert "openai_compatible" not in model_visible
    assert "llama3.2" not in model_visible


def test_json_schema_mode_parses_recorded_dual_output(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    client = FakeClient(
        [RECORDED["combined"]["choices"][0]["message"]["content"]],
        [fake_usage(120, 30, cached_tokens=20, reasoning_tokens=5)],
    )
    factory = RecordingClientFactory(client)
    agent = openai_agent(parameters={"output_mode": "json_schema"})

    result = OpenAICompatibleProvider(client_factory=factory).generate(
        agent=agent, context=context, seed=0
    )

    assert result.output.post == "Public result"
    assert result.output.soliloquy == "Private reflection"
    assert result.usage[0].phase == "combined"
    request = client.chat.completions.calls[0]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["schema"]["additionalProperties"] is False


def test_local_server_does_not_require_an_api_key(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = FakeClient(["Reflection", "Post"])
    factory = RecordingClientFactory(client)

    OpenAICompatibleProvider(client_factory=factory).generate(
        agent=openai_agent(parameters={}), context=context, seed=0
    )

    assert factory.calls[0]["api_key"] == LOCAL_API_KEY_PLACEHOLDER
    assert factory.calls[0]["base_url"] == "http://localhost:11434/v1"


def test_agent_without_briefing_is_not_told_private_briefings_exist(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    client = FakeClient(["Reflection", "Post"])
    unbriefed_context = context.model_copy(update={"private_briefing": None})

    OpenAICompatibleProvider(client_factory=RecordingClientFactory(client)).generate(
        agent=openai_agent(), context=unbriefed_context, seed=0
    )

    private_input = model_visible_text(client.chat.completions.calls[0])
    assert "private experiment briefing" not in private_input.casefold()
    assert "Product A" not in private_input


def test_missing_api_key_fails_without_revealing_values(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("ATLAS_OPENAI_KEY", raising=False)
    factory = RecordingClientFactory(FakeClient([]))

    with pytest.raises(OpenAICompatibleConfigurationError, match="ATLAS_OPENAI_KEY"):
        OpenAICompatibleProvider(client_factory=factory).generate(
            agent=openai_agent(credential_env="ATLAS_OPENAI_KEY"),
            context=context,
            seed=0,
        )

    assert factory.calls == []


def test_unknown_provider_parameter_is_rejected(context: AgentTurnContext) -> None:
    agent = openai_agent(parameters={"surprise": True})

    with pytest.raises(OpenAICompatibleConfigurationError, match="surprise"):
        OpenAICompatibleProvider(client_factory=RecordingClientFactory(FakeClient([]))).generate(
            agent=agent, context=context, seed=0
        )


def test_invalid_structured_response_is_rejected(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    provider = OpenAICompatibleProvider(
        client_factory=RecordingClientFactory(FakeClient(["not valid JSON"]))
    )

    with pytest.raises(OpenAICompatibleResponseError, match="invalid dual output"):
        provider.generate(
            agent=openai_agent(parameters={"output_mode": "json_schema"}),
            context=context,
            seed=0,
        )


def test_missing_text_response_is_rejected(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    client = FakeClient(["   "])

    with pytest.raises(OpenAICompatibleResponseError, match="no text output"):
        OpenAICompatibleProvider(client_factory=RecordingClientFactory(client)).generate(
            agent=openai_agent(), context=context, seed=0
        )


def test_invalid_usage_response_is_rejected(
    context: AgentTurnContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    client = FakeClient(["Reflection"], [SimpleNamespace(completion_tokens=3)])

    with pytest.raises(OpenAICompatibleResponseError, match="invalid model usage"):
        OpenAICompatibleProvider(client_factory=RecordingClientFactory(client)).generate(
            agent=openai_agent(), context=context, seed=0
        )


def test_prepare_launch_allows_key_free_openai_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    config = ExperimentConfig.model_validate(
        {
            "id": "local-openai",
            "name": "Local OpenAI-compatible",
            "system_prompt": "Reach one evidence-backed decision.",
            "agents": [
                {
                    "id": "atlas",
                    "display_name": "Atlas",
                    "persona_prompt": "Be empirical.",
                    "provider": "openai_compatible",
                    "model": "llama3.2",
                    "parameters": {"output_mode": "reflect_then_post"},
                }
            ],
        }
    )
    save_experiment_draft(ExperimentDraft(experiment=config), tmp_path)

    prepared = prepare_launch("local-openai", experiments_root=tmp_path, runs_root=tmp_path / "runs")

    assert prepared.loaded.config.agents[0].provider == "openai_compatible"
    assert prepared.loaded.config.agents[0].credential_env is None
