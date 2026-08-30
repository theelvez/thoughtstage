from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.experiment_launch import mark_run_failed


def _mock_draft(experiment_id: str = "launch-study") -> dict:
    return {
        "experiment": {
            "schema_version": "0.1",
            "id": experiment_id,
            "name": "Launch Study",
            "system_prompt": "Reach one evidence-backed decision.",
            "rounds": 2,
            "schedule": "simultaneous",
            "turn_order": "declared",
            "private_memory": "none",
            "seed": 42,
            "agents": [
                {
                    "id": "atlas",
                    "display_name": "Atlas",
                    "persona_prompt": "Prioritize falsifiable claims.",
                    "private_briefing": "SEALED-LAUNCH-BRIEFING",
                    "provider": "mock",
                    "model": "deterministic-mock",
                    "temperature": 0.4,
                    "parameters": {},
                },
                {
                    "id": "sage",
                    "display_name": "Sage",
                    "persona_prompt": "Seek the strongest counterargument.",
                    "provider": "mock",
                    "model": "deterministic-mock",
                    "temperature": 0.4,
                    "parameters": {},
                },
            ],
        },
        "materials": [],
    }


def _foundry_draft(experiment_id: str = "foundry-ready") -> dict:
    draft = _mock_draft(experiment_id)
    agent = draft["experiment"]["agents"][0]
    agent["provider"] = "azure_foundry"
    agent["model"] = "gpt-4o"
    agent["parameters"] = {
        "endpoint_env": "AZURE_FOUNDRY_ENDPOINT",
        "output_mode": "reflect_then_post",
        "send_temperature": False,
    }
    return draft


def _bedrock_draft(experiment_id: str = "bedrock-ready") -> dict:
    draft = _mock_draft(experiment_id)
    agent = draft["experiment"]["agents"][0]
    agent["provider"] = "bedrock"
    agent["model"] = "us.amazon.nova-2-lite-v1:0"
    agent["credential_env"] = "THOUGHTSTAGE_AWS_PROFILE"
    agent["parameters"] = {
        "region": "us-east-2",
        "private_max_output_tokens": 400,
        "public_max_output_tokens": 400,
        "max_attempts": 5,
    }
    return draft


def test_launch_api_runs_saved_experiment_and_preserves_private_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiments = tmp_path / "experiments"
    runs = tmp_path / "runs"
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(experiments))
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(runs))
    client = TestClient(app)

    created = client.post("/api/experiments", json=_mock_draft())
    launched = client.post("/api/experiments/launch-study/launch")

    assert created.status_code == 201
    assert launched.status_code == 202
    launch = launched.json()
    assert launch["accepted"] is True
    assert launch["observer_url"] == f"/?run={launch['run_id']}"

    bundle = runs / launch["run_id"]
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    public_stream = (bundle / "public.jsonl").read_text(encoding="utf-8")
    briefings = json.loads(
        (bundle / "private" / "agent_briefings.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["counts"]["public_posts"] == 4
    assert "SEALED-LAUNCH-BRIEFING" not in public_stream
    assert briefings == {"atlas": "SEALED-LAUNCH-BRIEFING"}


def test_launch_api_reports_missing_provider_environment_names_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _mock_draft("foundry-launch")
    agent = draft["experiment"]["agents"][0]
    agent["provider"] = "azure_foundry"
    agent["model"] = "gpt-4o"
    agent["credential_env"] = "LAUNCH_SECRET_KEY"
    agent["parameters"] = {
        "endpoint_env": "LAUNCH_FOUNDRY_ENDPOINT",
        "output_mode": "reflect_then_post",
        "send_temperature": False,
    }
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path / "experiments"))
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("LAUNCH_SECRET_KEY", raising=False)
    monkeypatch.delenv("LAUNCH_FOUNDRY_ENDPOINT", raising=False)
    client = TestClient(app)

    assert client.post("/api/experiments", json=draft).status_code == 201
    response = client.post("/api/experiments/foundry-launch/launch")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "LAUNCH_FOUNDRY_ENDPOINT" in detail
    assert "LAUNCH_SECRET_KEY" in detail
    assert not (tmp_path / "runs").exists()


def test_launch_api_rejects_invalid_and_missing_experiment_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path))
    client = TestClient(app)

    assert client.post("/api/experiments/missing/launch").status_code == 404
    assert client.post("/api/experiments/..%2Foutside/launch").status_code == 404


def test_failed_run_status_never_records_exception_message(tmp_path: Path) -> None:
    bundle = tmp_path / "failed-run"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"run_id": "failed-run", "status": "running"}),
        encoding="utf-8",
    )

    mark_run_failed(bundle, RuntimeError("provider leaked SUPER-SECRET-VALUE"))

    manifest_text = (bundle / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["status"] == "failed"
    assert manifest["failure"]["type"] == "RuntimeError"
    assert "SUPER-SECRET-VALUE" not in manifest_text


def test_provider_readiness_mock_needs_no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=_mock_draft())

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "required": [], "missing": []}
    assert set(body) == {"ok", "required", "missing"}


def test_provider_readiness_foundry_missing_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=_foundry_draft())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["required"] == ["AZURE_FOUNDRY_ENDPOINT"]
    assert body["missing"] == ["AZURE_FOUNDRY_ENDPOINT"]


def test_provider_readiness_bedrock_missing_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOUGHTSTAGE_AWS_PROFILE", raising=False)
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=_bedrock_draft())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["required"] == ["THOUGHTSTAGE_AWS_PROFILE"]
    assert body["missing"] == ["THOUGHTSTAGE_AWS_PROFILE"]


def test_provider_readiness_ok_after_env_set_never_returns_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_endpoint = "https://secret-foundry.example/do-not-return"
    secret_profile = "secret-aws-profile-value"
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", secret_endpoint)
    monkeypatch.setenv("THOUGHTSTAGE_AWS_PROFILE", secret_profile)
    client = TestClient(app)

    foundry = client.post("/api/experiments/provider-readiness", json=_foundry_draft())
    bedrock = client.post("/api/experiments/provider-readiness", json=_bedrock_draft())

    foundry_body = foundry.json()
    bedrock_body = bedrock.json()
    assert foundry.status_code == 200
    assert bedrock.status_code == 200
    assert foundry_body == {
        "ok": True,
        "required": ["AZURE_FOUNDRY_ENDPOINT"],
        "missing": [],
    }
    assert bedrock_body == {
        "ok": True,
        "required": ["THOUGHTSTAGE_AWS_PROFILE"],
        "missing": [],
    }
    combined = foundry.text + bedrock.text
    assert secret_endpoint not in combined
    assert secret_profile not in combined
    assert "https://" not in combined


def test_provider_readiness_openai_compatible_local_default_needs_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _mock_draft("ollama-ready")
    agent = draft["experiment"]["agents"][0]
    agent["provider"] = "openai_compatible"
    agent["model"] = "llama3.2"
    agent["parameters"] = {
        "base_url_env": "OPENAI_BASE_URL",
        "output_mode": "reflect_then_post",
    }
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=draft)

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "required": [], "missing": []}
    assert "OPENAI_API_KEY" not in response.text
    assert "OPENAI_BASE_URL" not in response.text


def test_provider_readiness_openai_named_key_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _mock_draft("openai-key-ready")
    agent = draft["experiment"]["agents"][0]
    agent["provider"] = "openai_compatible"
    agent["model"] = "gpt-4o-mini"
    agent["credential_env"] = "OPENAI_API_KEY"
    agent["parameters"] = {
        "base_url_env": "OPENAI_BASE_URL",
        "output_mode": "reflect_then_post",
    }
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://paid-endpoint.example/v1")
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=draft)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": False,
        "required": ["OPENAI_API_KEY"],
        "missing": ["OPENAI_API_KEY"],
    }
    assert "https://paid-endpoint.example/v1" not in response.text
    assert set(body) == {"ok", "required", "missing"}


def test_provider_readiness_rejects_native_anthropic() -> None:
    draft = _mock_draft("anthropic-ready")
    draft["experiment"]["agents"][0]["provider"] = "anthropic"
    client = TestClient(app)

    response = client.post("/api/experiments/provider-readiness", json=draft)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "anthropic" in detail
    assert "Unsupported provider" in detail
