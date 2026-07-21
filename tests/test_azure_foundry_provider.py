from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from thoughtstage.engine import ExperimentEngine
from thoughtstage.models import AgentConfig, AgentTurnContext, PublicPost
from thoughtstage.providers.azure_foundry import (
    AzureFoundryConfigurationError,
    AzureFoundryProvider,
    AzureFoundryResponseError,
)


class FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=next(self.outputs))


class FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = FakeResponses(outputs)


class RecordingClientFactory:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.calls.append(kwargs)
        return self.client


@pytest.fixture
def context() -> AgentTurnContext:
    return AgentTurnContext(
        experiment_id="foundry-stage",
        round_number=2,
        system_prompt="This exact shared prompt goes to every participant.",
        persona_prompt="Be empirical and concise.",
        public_feed=(
            PublicPost(
                event_id="post-r0001-beta-000001",
                sequence=1,
                experiment_id="foundry-stage",
                round_number=1,
                agent_id="beta",
                display_name="Beta",
                content="We should define a falsifiable prediction.",
            ),
        ),
        own_soliloquies=("I previously worried about measurement error.",),
        available_files=("brief.txt",),
    )


def foundry_agent(**updates: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "id": "atlas",
        "display_name": "Atlas",
        "persona_prompt": "Be empirical and concise.",
        "provider": "azure_foundry",
        "model": "gpt-4o",
        "credential_env": "ATLAS_FOUNDRY_KEY",
        "temperature": 0,
        "parameters": {"endpoint_env": "ATLAS_FOUNDRY_ENDPOINT"},
    }
    values.update(updates)
    return AgentConfig.model_validate(values)


def test_engine_registers_foundry_provider() -> None:
    assert "azure_foundry" in ExperimentEngine().providers


def test_json_schema_mode_keeps_binding_metadata_out_of_model_context(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_FOUNDRY_ENDPOINT", "https://resource.services.ai.azure.com")
    monkeypatch.setenv("ATLAS_FOUNDRY_KEY", "super-secret-key")
    client = FakeClient(['{"post":"Public result","soliloquy":"Private reflection"}'])
    factory = RecordingClientFactory(client)

    output = AzureFoundryProvider(client_factory=factory).generate(
        agent=foundry_agent(), context=context, seed=7
    )

    assert output.post == "Public result"
    assert output.soliloquy == "Private reflection"
    assert factory.calls == [
        {
            "api_key": "super-secret-key",
            "base_url": "https://resource.services.ai.azure.com/openai/v1/",
            "timeout": 120.0,
            "max_retries": 8,
        }
    ]
    request = client.responses.calls[0]
    assert request["model"] == "gpt-4o"
    assert request["store"] is False
    assert request["temperature"] == 0
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["schema"]["additionalProperties"] is False

    model_visible = f"{request['instructions']}\n{request['input']}"
    assert context.system_prompt in request["instructions"]
    assert "Beta: We should define a falsifiable prediction." in request["input"]
    assert "I previously worried about measurement error." in request["input"]
    assert "super-secret-key" not in model_visible
    assert "ATLAS_FOUNDRY_KEY" not in model_visible
    assert "resource.services.ai.azure.com" not in model_visible
    assert "azure_foundry" not in model_visible
    assert "gpt-4o" not in model_visible


def test_entra_auth_uses_injected_token_provider(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://resource/openai/v1/")
    token_provider = lambda: "short-lived-token"  # noqa: E731
    client = FakeClient(['{"post":"Post","soliloquy":"Reflection"}'])
    factory = RecordingClientFactory(client)
    provider = AzureFoundryProvider(
        client_factory=factory,
        token_provider_factory=lambda: token_provider,
    )

    provider.generate(
        agent=foundry_agent(credential_env=None, parameters={}), context=context, seed=0
    )

    assert factory.calls[0]["api_key"] is token_provider
    assert factory.calls[0]["base_url"] == "https://resource/openai/v1/"


def test_reflect_then_post_is_explicitly_two_pass(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_FOUNDRY_ENDPOINT", "https://resource.services.ai.azure.com")
    monkeypatch.setenv("ATLAS_FOUNDRY_KEY", "secret")
    client = FakeClient(["A private current reflection.", "A public post."])
    factory = RecordingClientFactory(client)
    agent = foundry_agent(
        parameters={
            "endpoint_env": "ATLAS_FOUNDRY_ENDPOINT",
            "output_mode": "reflect_then_post",
            "send_temperature": False,
        }
    )

    output = AzureFoundryProvider(client_factory=factory).generate(
        agent=agent, context=context, seed=11
    )

    assert output.post == "A public post."
    assert output.soliloquy == "A private current reflection."
    assert len(client.responses.calls) == 2
    private_call, public_call = client.responses.calls
    assert "temperature" not in private_call
    assert "temperature" not in public_call
    assert "A private current reflection." not in private_call["input"]
    assert "A private current reflection." in public_call["input"]
    assert "Write only the public social-feed post" in public_call["instructions"]


def test_missing_endpoint_fails_before_client_creation(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATLAS_FOUNDRY_ENDPOINT", raising=False)
    factory = RecordingClientFactory(FakeClient([]))

    with pytest.raises(AzureFoundryConfigurationError, match="ATLAS_FOUNDRY_ENDPOINT"):
        AzureFoundryProvider(client_factory=factory).generate(
            agent=foundry_agent(), context=context, seed=0
        )

    assert factory.calls == []


def test_missing_api_key_fails_without_revealing_values(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_FOUNDRY_ENDPOINT", "https://resource.services.ai.azure.com")
    monkeypatch.delenv("ATLAS_FOUNDRY_KEY", raising=False)

    with pytest.raises(AzureFoundryConfigurationError, match="ATLAS_FOUNDRY_KEY"):
        AzureFoundryProvider(client_factory=RecordingClientFactory(FakeClient([]))).generate(
            agent=foundry_agent(), context=context, seed=0
        )


def test_unknown_provider_parameter_is_rejected(context: AgentTurnContext) -> None:
    agent = foundry_agent(parameters={"surprise": True})

    with pytest.raises(AzureFoundryConfigurationError, match="surprise"):
        AzureFoundryProvider(client_factory=RecordingClientFactory(FakeClient([]))).generate(
            agent=agent, context=context, seed=0
        )


def test_invalid_structured_response_is_rejected(
    context: AgentTurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_FOUNDRY_ENDPOINT", "https://resource.services.ai.azure.com")
    monkeypatch.setenv("ATLAS_FOUNDRY_KEY", "secret")
    provider = AzureFoundryProvider(
        client_factory=RecordingClientFactory(FakeClient(["not valid JSON"]))
    )

    with pytest.raises(AzureFoundryResponseError, match="invalid dual output"):
        provider.generate(agent=foundry_agent(), context=context, seed=0)
