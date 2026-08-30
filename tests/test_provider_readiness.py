from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.experiment_launch import inspect_provider_environment
from thoughtstage.models import AgentConfig, ExperimentConfig


def _agent(**overrides: object) -> dict:
    payload: dict = {
        "id": "atlas",
        "display_name": "Atlas",
        "persona_prompt": "Prioritize falsifiable claims.",
        "provider": "mock",
        "model": "deterministic-mock",
        "temperature": 0.4,
        "parameters": {},
    }
    payload.update(overrides)
    return payload


def _draft(*agents: dict, experiment_id: str = "verify-study") -> dict:
    return {
        "experiment": {
            "schema_version": "0.1",
            "id": experiment_id,
            "name": "Verify Study",
            "system_prompt": "Reach one evidence-backed decision.",
            "rounds": 1,
            "schedule": "simultaneous",
            "turn_order": "declared",
            "private_memory": "none",
            "seed": 42,
            "agents": list(agents),
        },
        "materials": [],
    }


def _config(*agents: AgentConfig) -> ExperimentConfig:
    return ExperimentConfig(
        id="verify-study",
        name="Verify Study",
        system_prompt="Reach one evidence-backed decision.",
        rounds=1,
        agents=agents,
    )


def test_inspect_mock_only_requires_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    report = inspect_provider_environment(
        _config(
            AgentConfig(
                id="atlas",
                display_name="Atlas",
                persona_prompt="Prioritize falsifiable claims.",
                provider="mock",
                model="deterministic-mock",
            )
        )
    )
    assert report.ok is True
    assert report.required == ()
    assert report.missing == ()


def test_inspect_foundry_missing_endpoint_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    report = inspect_provider_environment(
        _config(
            AgentConfig(
                id="atlas",
                display_name="Atlas",
                persona_prompt="Prioritize falsifiable claims.",
                provider="azure_foundry",
                model="gpt-4o",
                parameters={
                    "endpoint_env": "AZURE_FOUNDRY_ENDPOINT",
                    "output_mode": "reflect_then_post",
                    "send_temperature": False,
                },
            )
        )
    )
    assert report.ok is False
    assert report.required == ("AZURE_FOUNDRY_ENDPOINT",)
    assert report.missing == ("AZURE_FOUNDRY_ENDPOINT",)


def test_inspect_bedrock_missing_profile_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    report = inspect_provider_environment(
        _config(
            AgentConfig(
                id="atlas",
                display_name="Atlas",
                persona_prompt="Prioritize falsifiable claims.",
                provider="bedrock",
                model="us.amazon.nova-2-lite-v1:0",
                credential_env="THOUGHTSTAGE_AWS_PROFILE",
                parameters={
                    "region": "us-east-2",
                    "private_max_output_tokens": 400,
                    "public_max_output_tokens": 400,
                    "max_attempts": 5,
                },
            )
        )
    )
    assert report.ok is False
    assert report.required == ("THOUGHTSTAGE_AWS_PROFILE",)
    assert report.missing == ("THOUGHTSTAGE_AWS_PROFILE",)


def test_inspect_ok_after_env_set_never_includes_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "presence-only-not-a-secret"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", marker)
    monkeypatch.setenv("THOUGHTSTAGE_AWS_PROFILE", marker)
    report = inspect_provider_environment(
        _config(
            AgentConfig(
                id="foundry",
                display_name="Foundry",
                persona_prompt="Prioritize falsifiable claims.",
                provider="azure_foundry",
                model="gpt-4o",
                parameters={"endpoint_env": "AZURE_FOUNDRY_ENDPOINT"},
            ),
            AgentConfig(
                id="bedrock",
                display_name="Bedrock",
                persona_prompt="Seek the strongest counterargument.",
                provider="bedrock",
                model="us.amazon.nova-2-lite-v1:0",
                credential_env="THOUGHTSTAGE_AWS_PROFILE",
                parameters={"region": "us-east-2"},
            ),
        )
    )
    assert report.ok is True
    assert report.required == ("AZURE_FOUNDRY_ENDPOINT", "THOUGHTSTAGE_AWS_PROFILE")
    assert report.missing == ()
    assert marker not in repr(report)


def test_inspect_openai_compatible_local_omits_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    report = inspect_provider_environment(
        _config(
            AgentConfig(
                id="local",
                display_name="Local",
                persona_prompt="Prioritize falsifiable claims.",
                provider="openai_compatible",
                model="llama3.2",
                parameters={
                    "base_url_env": "OPENAI_BASE_URL",
                    "output_mode": "reflect_then_post",
                },
            )
        )
    )
    assert report.ok is True
    assert report.required == ()
    assert report.missing == ()


def test_provider_readiness_api_mock_only_is_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    response = TestClient(app).post(
        "/api/experiments/provider-readiness",
        json=_draft(_agent()),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"ok": True, "required": [], "missing": []}
    assert set(payload) == {"ok", "required", "missing"}


def test_provider_readiness_api_foundry_missing_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    draft = _draft(
        _agent(
            provider="azure_foundry",
            model="gpt-4o",
            parameters={
                "endpoint_env": "AZURE_FOUNDRY_ENDPOINT",
                "output_mode": "reflect_then_post",
                "send_temperature": False,
            },
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["required"] == ["AZURE_FOUNDRY_ENDPOINT"]
    assert payload["missing"] == ["AZURE_FOUNDRY_ENDPOINT"]


def test_provider_readiness_api_bedrock_missing_profile_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    draft = _draft(
        _agent(
            provider="bedrock",
            model="us.amazon.nova-2-lite-v1:0",
            credential_env="THOUGHTSTAGE_AWS_PROFILE",
            parameters={
                "region": "us-east-2",
                "private_max_output_tokens": 400,
                "public_max_output_tokens": 400,
                "max_attempts": 5,
            },
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["required"] == ["THOUGHTSTAGE_AWS_PROFILE"]
    assert payload["missing"] == ["THOUGHTSTAGE_AWS_PROFILE"]


def test_provider_readiness_api_ok_after_env_never_returns_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "presence-only-not-a-secret"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", marker)
    monkeypatch.setenv("CUSTOM_FOUNDRY_KEY", marker)
    draft = _draft(
        _agent(
            id="foundry",
            provider="azure_foundry",
            model="gpt-4o",
            credential_env="CUSTOM_FOUNDRY_KEY",
            parameters={"endpoint_env": "AZURE_FOUNDRY_ENDPOINT"},
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ok": True,
        "required": ["AZURE_FOUNDRY_ENDPOINT", "CUSTOM_FOUNDRY_KEY"],
        "missing": [],
    }
    assert marker not in response.text
    assert "values" not in payload


def test_provider_readiness_api_whitespace_env_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "   ")
    draft = _draft(
        _agent(
            provider="azure_foundry",
            model="gpt-4o",
            parameters={"endpoint_env": "AZURE_FOUNDRY_ENDPOINT"},
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    assert response.json()["ok"] is False
    assert response.json()["missing"] == ["AZURE_FOUNDRY_ENDPOINT"]


def test_provider_readiness_does_not_write_experiment_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path))
    response = TestClient(app).post(
        "/api/experiments/provider-readiness",
        json=_draft(_agent()),
    )
    assert response.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_provider_readiness_agrees_with_launch_missing_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path / "experiments"))
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    draft = deepcopy(
        _draft(
            _agent(),
            _agent(
                id="foundry",
                display_name="Foundry",
                provider="azure_foundry",
                model="gpt-4o",
                parameters={"endpoint_env": "AZURE_FOUNDRY_ENDPOINT"},
            ),
            experiment_id="agree-study",
        )
    )
    client = TestClient(app)
    readiness = client.post("/api/experiments/provider-readiness", json=draft)
    created = client.post("/api/experiments", json=draft)
    launched = client.post("/api/experiments/agree-study/launch")

    assert readiness.status_code == 200
    assert readiness.json()["missing"] == ["AZURE_FOUNDRY_ENDPOINT"]
    assert created.status_code == 201
    assert launched.status_code == 409
    assert "AZURE_FOUNDRY_ENDPOINT" in launched.json()["detail"]
    assert "Set environment variables:" in launched.json()["detail"]


def test_provider_readiness_openai_compatible_local_omits_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    draft = _draft(
        _agent(
            provider="openai_compatible",
            model="llama3.2",
            parameters={
                "base_url_env": "OPENAI_BASE_URL",
                "output_mode": "reflect_then_post",
            },
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    assert response.json() == {"ok": True, "required": [], "missing": []}


def test_provider_readiness_openai_compatible_named_key_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    draft = _draft(
        _agent(
            provider="openai_compatible",
            model="gpt-4o-mini",
            credential_env="OPENAI_API_KEY",
            parameters={"base_url_env": "OPENAI_BASE_URL"},
        )
    )
    response = TestClient(app).post("/api/experiments/provider-readiness", json=draft)
    payload = response.json()
    assert payload["ok"] is False
    assert payload["required"] == ["OPENAI_API_KEY"]
    assert payload["missing"] == ["OPENAI_API_KEY"]
