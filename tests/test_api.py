from pathlib import Path

from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.engine import ExperimentEngine

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_experiment_schema_has_one_shared_prompt() -> None:
    schema = client.get("/api/schema/experiment").json()
    properties = schema["properties"]

    assert "system_prompt" in properties
    assert "stimuli" in properties
    assert "agents" in properties


def test_design_contract_is_explicit() -> None:
    contract = client.get("/api/design-contract").json()

    assert contract["private_channel"] == "soliloquies are researcher-only"
    assert contract["scheduled_stimuli"] == (
        "typed public events declared in the experiment manifest"
    )
    assert contract["default_private_memory"] == "none"


def test_integrity_and_reproducibility_bundle_endpoints(
    loaded_experiment, tmp_path: Path, monkeypatch
) -> None:
    runs_root = tmp_path / "runs"
    ExperimentEngine().run(
        loaded_experiment,
        output_root=runs_root,
        run_id="api-integrity",
    )
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(runs_root))

    integrity = client.get("/api/runs/api-integrity/integrity")
    archive = client.get("/api/runs/api-integrity/reproducibility-bundle")

    assert integrity.status_code == 200
    assert integrity.json()["valid"] is True
    assert integrity.json()["boundary_valid"] is True
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert archive.headers["x-thoughtstage-integrity"] == "verified"
    assert archive.content.startswith(b"PK")


def test_integrity_endpoint_rejects_path_traversal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(tmp_path))

    assert client.get("/api/runs/bad%2Fid/integrity").status_code == 404
