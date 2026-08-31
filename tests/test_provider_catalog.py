from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from thoughtstage.api import app
from thoughtstage.provider_catalog import (
    ProviderModelQuery,
    list_provider_models,
    looks_like_non_chat,
)
from thoughtstage.providers.azure_foundry import AzureFoundryProvider
from thoughtstage.providers.bedrock import BedrockProvider
from thoughtstage.providers.mock import MOCK_MODELS, MockProvider
from thoughtstage.providers.openai_compatible import OpenAICompatibleProvider


def _foundry_deployments() -> dict[str, Any]:
    return {
        "data": [
            {"id": "Llama-3.3-70B-Instruct", "status": "succeeded"},
            {"id": "gpt-4o", "status": "succeeded"},
            {"id": "grok-4-1-fast-reasoning", "status": "succeeded"},
            {"id": "DeepSeek-V3.2", "status": "succeeded"},
            {"id": "grok-4-20-reasoning", "status": "succeeded"},
            {"id": "text-embedding-3-small", "status": "succeeded"},
            {"id": "gpt-oss-120b", "status": "succeeded"},
            {
                "id": "whisper-1",
                "capabilities": {"embeddings": False, "chat_completion": False},
            },
        ]
    }


class RecordingJsonGetter:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> Any:
        del timeout
        self.calls.append((url, headers))
        return self.payload


class FailingJsonGetter:
    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> Any:
        del url, headers, timeout
        raise RuntimeError("https://secret-foundry.example/do-not-return token=SECRET-TOKEN")


class FakeBedrockCatalog:
    def __init__(self) -> None:
        self.foundation_calls: list[dict[str, Any]] = []
        self.profile_calls: list[dict[str, Any]] = []

    def list_foundation_models(self, **kwargs: Any) -> dict[str, Any]:
        self.foundation_calls.append(kwargs)
        return {
            "modelSummaries": [
                {
                    "modelId": "amazon.nova-lite-v1:0",
                    "modelName": "Nova Lite",
                    "outputModalities": ["TEXT"],
                    "inferenceTypesSupported": ["ON_DEMAND"],
                },
                {
                    "modelId": "amazon.titan-embed-text-v2:0",
                    "modelName": "Titan Embeddings",
                    "outputModalities": ["EMBEDDING"],
                    "inferenceTypesSupported": ["ON_DEMAND"],
                },
            ]
        }

    def list_inference_profiles(self, **kwargs: Any) -> dict[str, Any]:
        self.profile_calls.append(kwargs)
        return {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "us.amazon.nova-2-lite-v1:0",
                    "inferenceProfileName": "US Nova 2 Lite",
                    "status": "ACTIVE",
                },
                {
                    "inferenceProfileId": "us.amazon.titan-embed-text-v2:0",
                    "inferenceProfileName": "Titan embed profile",
                    "status": "ACTIVE",
                },
            ]
        }


class RecordingCatalogFactory:
    def __init__(self, client: FakeBedrockCatalog) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeBedrockCatalog:
        self.calls.append(kwargs)
        return self.client


class FakeOpenAIModels:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.calls = 0

    def list(self) -> Any:
        self.calls += 1
        return SimpleNamespace(data=[SimpleNamespace(id=item) for item in self.ids])


class FakeOpenAICatalogClient:
    def __init__(self, ids: list[str]) -> None:
        self.chat = SimpleNamespace()
        self.models = FakeOpenAIModels(ids)


class RecordingOpenAIFactory:
    def __init__(self, client: FakeOpenAICatalogClient) -> None:
        self.client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeOpenAICatalogClient:
        self.calls.append(kwargs)
        return self.client


def test_looks_like_non_chat_filters_embeddings() -> None:
    assert looks_like_non_chat("text-embedding-3-small")
    assert not looks_like_non_chat("gpt-4o")
    assert not looks_like_non_chat("Llama-3.3-70B-Instruct")


def test_mock_catalog_is_builtin_roster() -> None:
    catalog = MockProvider().list_models()
    assert catalog.ok is True
    assert catalog.source == "builtin"
    assert [model.id for model in catalog.models] == [item.id for item in MOCK_MODELS]


def test_foundry_lists_chat_deployments_and_drops_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_endpoint = "https://secret-foundry.example/do-not-return"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", secret_endpoint)
    getter = RecordingJsonGetter(_foundry_deployments())
    catalog = AzureFoundryProvider(
        token_provider_factory=lambda: lambda: "token-value",
        json_getter=getter,
    ).list_models()

    assert catalog.ok is True
    ids = [model.id for model in catalog.models]
    assert ids == [
        "DeepSeek-V3.2",
        "gpt-4o",
        "gpt-oss-120b",
        "grok-4-1-fast-reasoning",
        "grok-4-20-reasoning",
        "Llama-3.3-70B-Instruct",
    ]
    assert "text-embedding-3-small" not in ids
    assert "whisper-1" not in ids
    dumped = catalog.model_dump_json()
    assert secret_endpoint not in dumped
    assert "token-value" not in dumped
    assert getter.calls
    assert "openai/deployments" in getter.calls[0][0]


def test_foundry_missing_endpoint_does_not_invent_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    catalog = AzureFoundryProvider(json_getter=FailingJsonGetter()).list_models()
    assert catalog.ok is False
    assert catalog.models == ()
    assert catalog.missing == ("AZURE_FOUNDRY_ENDPOINT",)
    assert "AZURE_FOUNDRY_ENDPOINT" in (catalog.error or "")
    assert "gpt-4o" not in (catalog.error or "")


def test_foundry_list_failure_is_empty_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_endpoint = "https://secret-foundry.example/do-not-return"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", secret_endpoint)
    catalog = AzureFoundryProvider(
        token_provider_factory=lambda: lambda: "SECRET-TOKEN",
        json_getter=FailingJsonGetter(),
    ).list_models()
    dumped = catalog.model_dump_json()
    assert catalog.ok is False
    assert catalog.models == ()
    assert secret_endpoint not in dumped
    assert "SECRET-TOKEN" not in dumped
    assert "https://" not in dumped


def test_bedrock_lists_text_models_for_profile_and_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_profile = "secret-aws-profile-value"
    monkeypatch.setenv("THOUGHTSTAGE_AWS_PROFILE", secret_profile)
    client = FakeBedrockCatalog()
    factory = RecordingCatalogFactory(client)
    catalog = BedrockProvider(catalog_client_factory=factory).list_models(region="us-east-2")

    assert catalog.ok is True
    ids = [model.id for model in catalog.models]
    assert "us.amazon.nova-2-lite-v1:0" in ids
    assert "amazon.nova-lite-v1:0" in ids
    assert "amazon.titan-embed-text-v2:0" not in ids
    assert "us.amazon.titan-embed-text-v2:0" not in ids
    assert factory.calls[0]["profile_name"] == secret_profile
    assert factory.calls[0]["region_name"] == "us-east-2"
    dumped = catalog.model_dump_json()
    assert secret_profile not in dumped


def test_bedrock_missing_profile_does_not_invent_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    catalog = BedrockProvider(
        catalog_client_factory=RecordingCatalogFactory(FakeBedrockCatalog()),
    ).list_models(region="us-east-2")
    assert catalog.ok is False
    assert catalog.models == ()
    assert catalog.missing == ("THOUGHTSTAGE_AWS_PROFILE",)


def test_openai_compatible_lists_models_and_filters_embeddings() -> None:
    factory = RecordingOpenAIFactory(
        FakeOpenAICatalogClient(["llama3.2", "text-embedding-3-small", "gpt-4o-mini"]),
    )
    catalog = OpenAICompatibleProvider(client_factory=factory).list_models()
    assert catalog.ok is True
    assert [model.id for model in catalog.models] == ["gpt-4o-mini", "llama3.2"]
    assert factory.calls[0]["base_url"] == "http://localhost:11434/v1"


def test_openai_compatible_without_models_api_stays_empty() -> None:
    factory = RecordingOpenAIFactory(SimpleNamespace(chat=SimpleNamespace()))  # type: ignore[arg-type]
    catalog = OpenAICompatibleProvider(client_factory=factory).list_models()
    assert catalog.ok is False
    assert catalog.models == ()
    assert "Type a model ID" in (catalog.error or "")


def test_query_rejects_anthropic() -> None:
    with pytest.raises(ValidationError):
        ProviderModelQuery(provider="anthropic")  # type: ignore[arg-type]


def test_query_rejects_invalid_region() -> None:
    with pytest.raises(ValidationError):
        ProviderModelQuery(provider="bedrock", region="US-EAST-2")
    assert ProviderModelQuery(provider="bedrock", region="  ").region is None


def test_list_provider_models_dispatches_without_inventing_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    mock = list_provider_models(ProviderModelQuery(provider="mock"))
    foundry = list_provider_models(ProviderModelQuery(provider="azure_foundry"))
    bedrock = list_provider_models(
        ProviderModelQuery(provider="bedrock", region="us-east-2"),
    )

    assert mock.ok is True
    assert [model.id for model in mock.models] == [item.id for item in MOCK_MODELS]
    assert foundry.ok is False and foundry.models == ()
    assert bedrock.ok is False and bedrock.models == ()


def test_provider_models_api_mock_and_never_returns_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_endpoint = "https://secret-foundry.example/do-not-return"
    secret_profile = "secret-aws-profile-value"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", secret_endpoint)
    monkeypatch.setenv("THOUGHTSTAGE_AWS_PROFILE", secret_profile)
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    client = TestClient(app)

    mock = client.get("/api/provider-models", params={"provider": "mock"})
    foundry = client.get("/api/provider-models", params={"provider": "azure_foundry"})
    anthropic = client.get("/api/provider-models", params={"provider": "anthropic"})

    assert mock.status_code == 200
    assert mock.json()["ok"] is True
    assert mock.json()["source"] == "builtin"
    assert {item["id"] for item in mock.json()["models"]} == {
        "deterministic-mock",
        "deterministic-v1",
    }
    assert foundry.status_code == 200
    foundry_body = foundry.json()
    assert foundry_body["ok"] is False
    assert foundry_body["models"] == []
    assert foundry_body["missing"] == ["AZURE_FOUNDRY_ENDPOINT"]
    assert secret_endpoint not in foundry.text
    assert secret_profile not in foundry.text
    assert "https://" not in foundry.text
    assert anthropic.status_code == 422
    bad_region = client.get(
        "/api/provider-models",
        params={"provider": "bedrock", "region": "US-EAST-2"},
    )
    assert bad_region.status_code == 422
