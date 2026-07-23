from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.config import LoadedExperiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.run_comparison import (
    ComparisonRole,
    ComparisonSelection,
    RunComparisonRequest,
    compare_runs,
)


def _variant(loaded_experiment, **updates) -> LoadedExperiment:
    config = loaded_experiment.config.model_copy(update=updates)
    source = yaml.safe_dump(
        config.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
    ).encode()
    return LoadedExperiment(
        config=config,
        source_path=loaded_experiment.source_path,
        source_bytes=source,
        files_root=loaded_experiment.files_root,
    )


def _comparison_runs(loaded_experiment, tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    ExperimentEngine().run(
        loaded_experiment,
        output_root=root,
        run_id="comparison-control",
    )
    ExperimentEngine().run(
        _variant(loaded_experiment, seed=99),
        output_root=root,
        run_id="comparison-treatment",
    )
    return root


def test_compare_runs_identifies_exact_single_variable_change(
    loaded_experiment, tmp_path: Path
) -> None:
    root = _comparison_runs(loaded_experiment, tmp_path)
    request = RunComparisonRequest(
        runs=(
            ComparisonSelection(
                run_id="comparison-control",
                role=ComparisonRole.CONTROL,
                label="Control",
            ),
            ComparisonSelection(
                run_id="comparison-treatment",
                role=ComparisonRole.TREATMENT,
                label="Seed treatment",
            ),
        )
    )

    result = compare_runs(request, root=root)

    assert result.baseline_run_id == "comparison-control"
    assert [item.role for item in result.runs] == [
        ComparisonRole.CONTROL,
        ComparisonRole.TREATMENT,
    ]
    assert all(item.integrity_valid for item in result.runs)
    assert all(item.boundary_valid for item in result.runs)
    assert result.runs[0].public_posts == 4
    assert len(result.runs[0].final_posts) == 2
    delta = result.deltas[0]
    assert delta.single_variable_change is True
    assert delta.changed_variable_count == 1
    assert [(item.path, item.baseline, item.candidate) for item in delta.differences] == [
        ("seed", 17, 99)
    ]


def test_compare_runs_reports_multiple_changes(loaded_experiment, tmp_path: Path) -> None:
    root = tmp_path / "runs"
    ExperimentEngine().run(loaded_experiment, output_root=root, run_id="multi-control")
    ExperimentEngine().run(
        _variant(loaded_experiment, seed=99, rounds=3),
        output_root=root,
        run_id="multi-treatment",
    )
    request = RunComparisonRequest(
        runs=(
            ComparisonSelection(run_id="multi-control"),
            ComparisonSelection(run_id="multi-treatment"),
        )
    )

    result = compare_runs(request, root=root)

    delta = result.deltas[0]
    assert delta.single_variable_change is False
    assert delta.changed_variable_count == 2
    assert {item.path for item in delta.differences} == {"rounds", "seed"}


def test_run_comparison_api(loaded_experiment, tmp_path: Path, monkeypatch) -> None:
    root = _comparison_runs(loaded_experiment, tmp_path)
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(root))
    response = TestClient(app).post(
        "/api/run-comparisons",
        json={
            "runs": [
                {"run_id": "comparison-control", "role": "control"},
                {"run_id": "comparison-treatment", "role": "treatment"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["deltas"][0]["single_variable_change"] is True


def test_run_comparison_requires_unique_run_ids() -> None:
    response = TestClient(app).post(
        "/api/run-comparisons",
        json={
            "runs": [
                {"run_id": "same-run"},
                {"run_id": "same-run"},
            ]
        },
    )

    assert response.status_code == 422
    assert "must be unique" in response.text
