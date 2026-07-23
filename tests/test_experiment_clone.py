from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.config import load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.experiment_clone import (
    CloneVariable,
    ExperimentCloneError,
    ExperimentCloneRequest,
    clone_options,
    clone_run_as_experiment,
)
from thoughtstage.integrity import verify_run_bundle


def _completed_run(loaded_experiment, tmp_path: Path) -> Path:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="clone-parent",
    )
    return Path(result.bundle_path)


def test_clone_options_expose_scalar_variables_without_credentials(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _completed_run(loaded_experiment, tmp_path)

    result = clone_options(bundle)

    paths = {item.path for item in result.options}
    assert "system_prompt" in paths
    assert "seed" in paths
    assert "agents[alpha].model" in paths
    assert "agents[alpha].temperature" in paths
    assert all("credential" not in item.path for item in result.options)
    assert result.suggested_experiment_id == "test-stage-variant"


def test_clone_changes_exactly_one_experimental_variable_and_records_lineage(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _completed_run(loaded_experiment, tmp_path)
    request = ExperimentCloneRequest(
        experiment_id="test-stage-seed-99",
        name="Test Stage - Seed 99",
        change=CloneVariable(path="seed", value=99),
    )

    result = clone_run_as_experiment(bundle, request, tmp_path / "experiments")

    parent = loaded_experiment.config.model_dump(mode="json")
    clone = load_experiment(Path(result.manifest)).config.model_dump(mode="json")
    parent["id"] = clone["id"]
    parent["name"] = clone["name"]
    parent["seed"] = 99
    assert clone == parent
    assert (Path(result.directory) / "files" / "brief.txt").read_text(encoding="utf-8") == (
        "Evidence matters.\nTest the claim.\n"
    )
    lineage = json.loads(Path(result.lineage).read_text(encoding="utf-8"))
    assert lineage["kind"] == "single_variable_clone"
    assert lineage["parent_run_id"] == "clone-parent"
    assert lineage["change_path"] == "seed"
    assert lineage["before"] == 17
    assert lineage["after"] == 99
    assert lineage["administrative_changes"] == ["id", "name"]

    child_result = ExperimentEngine().run(
        load_experiment(Path(result.manifest)),
        output_root=tmp_path / "runs",
        run_id="clone-child",
    )
    child_bundle = Path(child_result.bundle_path)
    child_manifest = json.loads((child_bundle / "manifest.json").read_text(encoding="utf-8"))
    assert child_manifest["lineage"] == lineage
    assert json.loads((child_bundle / "lineage.json").read_text(encoding="utf-8")) == lineage
    report = verify_run_bundle(child_bundle)
    assert report.valid is True
    assert (
        next(item for item in report.checks if item.code == "experiment-lineage").status == "pass"
    )


def test_clone_rejects_unchanged_or_unavailable_variables(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _completed_run(loaded_experiment, tmp_path)
    unchanged = ExperimentCloneRequest(
        experiment_id="same-seed",
        name="Same Seed",
        change=CloneVariable(path="seed", value=17),
    )
    unsupported = ExperimentCloneRequest(
        experiment_id="credential-change",
        name="Credential Change",
        change=CloneVariable(path="agents[alpha].credential_env", value="OTHER_KEY"),
    )

    with pytest.raises(ExperimentCloneError, match="must differ"):
        clone_run_as_experiment(bundle, unchanged, tmp_path / "experiments")
    with pytest.raises(ExperimentCloneError, match="not supported"):
        clone_run_as_experiment(bundle, unsupported, tmp_path / "experiments")


def test_clone_refuses_legacy_run_without_input_snapshots(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _completed_run(loaded_experiment, tmp_path)
    snapshot = bundle / "inputs" / "files" / "brief.txt"
    snapshot.unlink()
    snapshot.parent.rmdir()
    snapshot.parent.parent.rmdir()
    request = ExperimentCloneRequest(
        experiment_id="legacy-clone",
        name="Legacy Clone",
        change=CloneVariable(path="seed", value=18),
    )

    with pytest.raises(ExperimentCloneError, match="no input snapshots"):
        clone_run_as_experiment(bundle, request, tmp_path / "experiments")


def test_clone_api_creates_variant_and_rejects_duplicate(
    loaded_experiment, tmp_path: Path, monkeypatch
) -> None:
    runs_root = tmp_path / "runs"
    experiments_root = tmp_path / "experiments"
    ExperimentEngine().run(
        loaded_experiment,
        output_root=runs_root,
        run_id="clone-api-parent",
    )
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(runs_root))
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(experiments_root))
    client = TestClient(app)
    request = {
        "experiment_id": "clone-api-variant",
        "name": "Clone API Variant",
        "change": {"path": "schedule", "value": "sequential"},
    }

    options = client.get("/api/runs/clone-api-parent/clone-options")
    created = client.post("/api/runs/clone-api-parent/clone", json=request)
    duplicate = client.post("/api/runs/clone-api-parent/clone", json=request)

    assert options.status_code == 200
    assert created.status_code == 201
    assert created.json()["change_path"] == "schedule"
    assert duplicate.status_code == 409
