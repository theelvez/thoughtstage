"""Researcher-side comparison of completed Thoughtstage run bundles."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from thoughtstage.integrity import verify_run_bundle
from thoughtstage.models import ExperimentConfig, StrictModel
from thoughtstage.observer import read_run_bundle, resolve_run_bundle_path
from thoughtstage.reproducibility import sha256_bytes

ScalarValue = str | int | float | bool | None


class ComparisonRole(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"
    COUNTERBALANCE = "counterbalance"
    REPLICATION = "replication"
    UNASSIGNED = "unassigned"


class ComparisonSelection(StrictModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    role: ComparisonRole = ComparisonRole.UNASSIGNED
    label: str | None = Field(default=None, min_length=1, max_length=80)


class RunComparisonRequest(StrictModel):
    runs: tuple[ComparisonSelection, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> RunComparisonRequest:
        run_ids = [item.run_id for item in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("comparison run ids must be unique")
        return self


class ComparisonParticipant(StrictModel):
    id: str
    display_name: str
    provider: str
    model: str


class ComparisonFinalPost(StrictModel):
    agent_id: str
    display_name: str
    round_number: int
    content: str


class ComparisonRun(StrictModel):
    run_id: str
    role: ComparisonRole
    label: str
    experiment_id: str
    experiment_name: str
    status: str
    integrity_valid: bool
    boundary_valid: bool
    config_sha256: str | None
    source_revision: str | None
    created_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    rounds: int
    schedule: str
    seed: int
    participants: tuple[ComparisonParticipant, ...]
    public_posts: int
    soliloquies: int
    model_calls: int
    total_tokens: int
    final_posts: tuple[ComparisonFinalPost, ...]


class VariableDifference(StrictModel):
    path: str
    category: Literal["experimental", "administrative", "input"]
    baseline: ScalarValue
    candidate: ScalarValue


class RunDelta(StrictModel):
    baseline_run_id: str
    candidate_run_id: str
    changed_variable_count: int
    single_variable_change: bool
    differences: tuple[VariableDifference, ...]


class RunComparisonResult(StrictModel):
    schema_version: Literal["0.1"] = "0.1"
    baseline_run_id: str
    runs: tuple[ComparisonRun, ...]
    deltas: tuple[RunDelta, ...]


class RunComparisonError(ValueError):
    """Raised when selected runs cannot be compared safely."""


def _duration_seconds(created_at: str | None, completed_at: str | None) -> float | None:
    if not created_at or not completed_at:
        return None
    try:
        return max(
            0.0,
            (
                datetime.fromisoformat(completed_at) - datetime.fromisoformat(created_at)
            ).total_seconds(),
        )
    except ValueError:
        return None


def _load_config(root: Path) -> ExperimentConfig:
    try:
        raw = yaml.safe_load((root / "experiment.yaml").read_bytes())
        return ExperimentConfig.model_validate(raw)
    except (FileNotFoundError, yaml.YAMLError, ValidationError) as exc:
        raise RunComparisonError(f"run {root.name!r} has an invalid experiment snapshot") from exc


def _normalize_config(config: ExperimentConfig) -> dict[str, Any]:
    payload = config.model_dump(mode="json")
    payload["agents"] = {item["id"]: item for item in payload["agents"]}
    payload["stimuli"] = {item["id"]: item for item in payload["stimuli"]}
    return payload


def _flatten(
    value: Any,
    *,
    path: str = "",
    output: dict[str, ScalarValue],
) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{path}.{key}" if path else str(key)
            _flatten(value[key], path=child, output=output)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(item, path=f"{path}[{index}]", output=output)
        return
    if path.endswith("private_briefing") and isinstance(value, str):
        output[path] = f"sha256:{sha256_bytes(value.encode())}"
        return
    if value is None or isinstance(value, (str, int, float, bool)):
        output[path] = value
        return
    output[path] = json.dumps(value, sort_keys=True, ensure_ascii=False)


def _variables(root: Path, config: ExperimentConfig) -> dict[str, tuple[str, ScalarValue]]:
    flattened: dict[str, ScalarValue] = {}
    _flatten(_normalize_config(config), output=flattened)
    variables: dict[str, tuple[str, ScalarValue]] = {}
    for path, value in flattened.items():
        category = "administrative" if path in {"id", "name", "description"} else "experimental"
        variables[path] = (category, value)

    try:
        files = json.loads((root / "files.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RunComparisonError(f"run {root.name!r} has invalid input-file metadata") from exc
    if not isinstance(files, list):
        raise RunComparisonError(f"run {root.name!r} has invalid input-file metadata")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise RunComparisonError(f"run {root.name!r} has invalid input-file metadata")
        variables[f"files[{item['path']}].sha256"] = ("input", item.get("sha256"))
    return variables


def _final_posts(detail: dict[str, Any]) -> tuple[ComparisonFinalPost, ...]:
    by_agent: dict[str, dict[str, Any]] = {}
    for event in detail["posts"]:
        if event.get("event_type") != "post":
            continue
        current = by_agent.get(event["agent_id"])
        if current is None or (
            event.get("round_number", 0),
            event.get("sequence", 0),
        ) > (
            current.get("round_number", 0),
            current.get("sequence", 0),
        ):
            by_agent[event["agent_id"]] = event
    return tuple(
        ComparisonFinalPost(
            agent_id=agent["id"],
            display_name=agent["display_name"],
            round_number=by_agent[agent["id"]]["round_number"],
            content=by_agent[agent["id"]]["content"],
        )
        for agent in detail["agents"]
        if agent["id"] in by_agent
    )


def _comparison_run(
    selection: ComparisonSelection,
    root: Path,
    detail: dict[str, Any],
) -> ComparisonRun:
    report = verify_run_bundle(root)
    usage = detail["usage_summary"]["totals"]
    return ComparisonRun(
        run_id=selection.run_id,
        role=selection.role,
        label=selection.label or selection.role.value.replace("_", " ").title(),
        experiment_id=detail["experiment"].get("id") or "unknown",
        experiment_name=detail["experiment"].get("name") or "Untitled experiment",
        status=detail["status"],
        integrity_valid=report.valid,
        boundary_valid=report.boundary_valid,
        config_sha256=detail["experiment"].get("config_sha256"),
        source_revision=detail.get("thoughtstage", {}).get("source_revision"),
        created_at=detail.get("created_at"),
        completed_at=detail.get("completed_at"),
        duration_seconds=_duration_seconds(
            detail.get("created_at"),
            detail.get("completed_at"),
        ),
        rounds=int(detail.get("execution", {}).get("rounds") or 0),
        schedule=str(detail.get("execution", {}).get("schedule") or "unknown"),
        seed=int(detail.get("execution", {}).get("seed") or 0),
        participants=tuple(
            ComparisonParticipant(
                id=agent["id"],
                display_name=agent["display_name"],
                provider=agent["provider"],
                model=agent["model"],
            )
            for agent in detail["agents"]
        ),
        public_posts=detail["counts"]["public_posts"],
        soliloquies=detail["counts"]["soliloquies"],
        model_calls=usage["model_calls"],
        total_tokens=usage["total_tokens"],
        final_posts=_final_posts(detail),
    )


def _delta(
    baseline_run_id: str,
    candidate_run_id: str,
    baseline: dict[str, tuple[str, ScalarValue]],
    candidate: dict[str, tuple[str, ScalarValue]],
) -> RunDelta:
    differences: list[VariableDifference] = []
    for path in sorted(set(baseline) | set(candidate)):
        baseline_category, baseline_value = baseline.get(path, ("experimental", None))
        candidate_category, candidate_value = candidate.get(path, (baseline_category, None))
        if baseline_value == candidate_value:
            continue
        category = (
            "input"
            if "input" in {baseline_category, candidate_category}
            else "administrative"
            if {baseline_category, candidate_category} == {"administrative"}
            or baseline_category == candidate_category == "administrative"
            else "experimental"
        )
        differences.append(
            VariableDifference(
                path=path,
                category=category,
                baseline=baseline_value,
                candidate=candidate_value,
            )
        )
    experimental = [item for item in differences if item.category != "administrative"]
    return RunDelta(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        changed_variable_count=len(experimental),
        single_variable_change=len(experimental) == 1,
        differences=tuple(differences),
    )


def compare_runs(request: RunComparisonRequest, *, root: Path | None = None) -> RunComparisonResult:
    """Compare completed runs using persisted configs, streams, usage, and integrity."""

    run_rows: list[ComparisonRun] = []
    variable_sets: list[dict[str, tuple[str, ScalarValue]]] = []
    for selection in request.runs:
        path = resolve_run_bundle_path(selection.run_id, root=root)
        detail = read_run_bundle(selection.run_id, root=root)
        report = verify_run_bundle(path)
        if not report.complete:
            raise RunComparisonError(f"run {selection.run_id!r} is not complete")
        config = _load_config(path)
        run_rows.append(_comparison_run(selection, path, detail))
        variable_sets.append(_variables(path, config))

    baseline_id = request.runs[0].run_id
    deltas = tuple(
        _delta(
            baseline_id,
            request.runs[index].run_id,
            variable_sets[0],
            variable_sets[index],
        )
        for index in range(1, len(request.runs))
    )
    return RunComparisonResult(
        baseline_run_id=baseline_id,
        runs=tuple(run_rows),
        deltas=deltas,
    )
