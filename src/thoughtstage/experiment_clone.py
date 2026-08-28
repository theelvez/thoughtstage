"""Create controlled, one-variable experiment clones from verified runs."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError

from thoughtstage.experiment_design import (
    ExperimentDraft,
    ExperimentLineage,
    ExperimentMaterial,
    save_experiment_draft,
)
from thoughtstage.integrity import verify_run_bundle
from thoughtstage.models import ExperimentConfig, StrictModel

ScalarValue = str | int | float | bool | None
OptionKind = Literal["text", "integer", "number", "choice"]

AGENT_PATH = re.compile(
    r"^agents\[(?P<id>[a-z][a-z0-9_-]{1,63})\]\."
    r"(?P<field>model|temperature|persona_prompt|private_briefing)$"
)
STIMULUS_PATH = re.compile(r"^stimuli\[(?P<id>[a-z][a-z0-9_-]{1,63})\]\.content$")


class ExperimentCloneError(ValueError):
    """Raised when a controlled clone cannot be created safely."""


class CloneVariable(StrictModel):
    """The single experimental variable to change."""

    path: str = Field(min_length=1, max_length=160)
    value: ScalarValue


class ExperimentCloneRequest(StrictModel):
    """Researcher request for one controlled variant."""

    experiment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    change: CloneVariable


class CloneOption(StrictModel):
    """One scalar variable that can be changed without ambiguous merging."""

    path: str
    label: str
    kind: OptionKind
    current: ScalarValue
    choices: tuple[str, ...] = ()


class CloneOptions(StrictModel):
    run_id: str
    source_experiment_id: str
    source_name: str
    suggested_experiment_id: str
    suggested_name: str
    options: tuple[CloneOption, ...]


class ExperimentCloneResult(StrictModel):
    created: bool = True
    parent_run_id: str
    experiment_id: str
    directory: str
    manifest: str
    lineage: str
    change_path: str
    before: ScalarValue
    after: ScalarValue


def _load_bundle_config(root: Path) -> ExperimentConfig:
    try:
        raw = yaml.safe_load((root / "experiment.yaml").read_bytes())
        return ExperimentConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise ExperimentCloneError("the run does not contain experiment.yaml") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise ExperimentCloneError("the bundled experiment is invalid") from exc


def _suggest_id(source_id: str) -> str:
    suffix = "-variant"
    return f"{source_id[: 64 - len(suffix)].rstrip('-_')}{suffix}"


def clone_options(bundle_path: str | Path) -> CloneOptions:
    root = Path(bundle_path).resolve(strict=True)
    report = verify_run_bundle(root)
    if not report.valid or not report.complete:
        raise ExperimentCloneError("only completed, integrity-valid runs can be cloned")
    config = _load_bundle_config(root)
    options: list[CloneOption] = [
        CloneOption(
            path="system_prompt",
            label="Shared system prompt",
            kind="text",
            current=config.system_prompt,
        ),
        CloneOption(path="rounds", label="Number of rounds", kind="integer", current=config.rounds),
        CloneOption(
            path="schedule",
            label="Schedule",
            kind="choice",
            current=config.schedule.value,
            choices=("simultaneous", "sequential"),
        ),
        CloneOption(
            path="turn_order",
            label="Turn order",
            kind="choice",
            current=config.turn_order.value,
            choices=("declared", "seeded_random"),
        ),
        CloneOption(
            path="private_memory",
            label="Private memory policy",
            kind="choice",
            current=config.private_memory.value,
            choices=("none", "own_history"),
        ),
        CloneOption(path="seed", label="Experiment seed", kind="integer", current=config.seed),
    ]
    for agent in config.agents:
        prefix = f"{agent.display_name} ({agent.id})"
        options.extend(
            (
                CloneOption(
                    path=f"agents[{agent.id}].model",
                    label=f"{prefix}: model or deployment",
                    kind="text",
                    current=agent.model,
                ),
                CloneOption(
                    path=f"agents[{agent.id}].temperature",
                    label=f"{prefix}: temperature",
                    kind="number",
                    current=agent.temperature,
                ),
                CloneOption(
                    path=f"agents[{agent.id}].persona_prompt",
                    label=f"{prefix}: persona",
                    kind="text",
                    current=agent.persona_prompt,
                ),
                CloneOption(
                    path=f"agents[{agent.id}].private_briefing",
                    label=f"{prefix}: private briefing",
                    kind="text",
                    current=agent.private_briefing,
                ),
            )
        )
    for stimulus in config.stimuli:
        options.append(
            CloneOption(
                path=f"stimuli[{stimulus.id}].content",
                label=f"Stimulus {stimulus.display_name} ({stimulus.id}): content",
                kind="text",
                current=stimulus.content,
            )
        )
    return CloneOptions(
        run_id=root.name,
        source_experiment_id=config.id,
        source_name=config.name,
        suggested_experiment_id=_suggest_id(config.id),
        suggested_name=f"{config.name} - controlled variant",
        options=tuple(options),
    )


def _coerce_value(option: CloneOption, value: ScalarValue) -> ScalarValue:
    if option.kind == "text":
        if value is None and option.path.endswith(".private_briefing"):
            return None
        if not isinstance(value, str):
            raise ExperimentCloneError(f"{option.label} must be text")
        return value
    if option.kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ExperimentCloneError(f"{option.label} must be an integer")
        return value
    if option.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ExperimentCloneError(f"{option.label} must be a number")
        return float(value)
    if not isinstance(value, str) or value not in option.choices:
        raise ExperimentCloneError(f"{option.label} must be one of: {', '.join(option.choices)}")
    return value


def _apply_change(
    config: ExperimentConfig,
    option: CloneOption,
    value: ScalarValue,
) -> ExperimentConfig:
    payload: dict[str, Any] = config.model_dump(mode="json")
    if option.path in {
        "system_prompt",
        "rounds",
        "schedule",
        "turn_order",
        "private_memory",
        "seed",
    }:
        payload[option.path] = value
    elif match := AGENT_PATH.fullmatch(option.path):
        agent = next(
            (item for item in payload["agents"] if item["id"] == match.group("id")),
            None,
        )
        if agent is None:
            raise ExperimentCloneError("the selected participant no longer exists")
        agent[match.group("field")] = value
    elif match := STIMULUS_PATH.fullmatch(option.path):
        stimulus = next(
            (item for item in payload["stimuli"] if item["id"] == match.group("id")),
            None,
        )
        if stimulus is None:
            raise ExperimentCloneError("the selected stimulus no longer exists")
        stimulus["content"] = value
    else:
        raise ExperimentCloneError("the selected clone variable is not supported")
    try:
        return ExperimentConfig.model_validate(payload)
    except ValidationError as exc:
        raise ExperimentCloneError(
            "the requested single-variable change makes the experiment invalid: "
            f"{exc.errors()[0]['msg']}"
        ) from exc


def _snapshot_materials(root: Path, config: ExperimentConfig) -> tuple[ExperimentMaterial, ...]:
    if config.files_dir is None:
        return ()
    try:
        metadata = json.loads((root / "files.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ExperimentCloneError("input-file metadata is missing or invalid") from exc
    if not isinstance(metadata, list):
        raise ExperimentCloneError("input-file metadata has an invalid shape")
    snapshot_root = root / "inputs" / "files"
    if not snapshot_root.is_dir():
        raise ExperimentCloneError(
            "this legacy run has no input snapshots and cannot be cloned exactly"
        )
    materials: list[ExperimentMaterial] = []
    for item in metadata:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ExperimentCloneError("input-file metadata has an invalid shape")
        logical = PurePosixPath(item["path"])
        if logical.is_absolute() or ".." in logical.parts:
            raise ExperimentCloneError("input-file metadata contains an unsafe path")
        candidate = snapshot_root.joinpath(*logical.parts)
        try:
            content = candidate.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ExperimentCloneError(f"missing input snapshot: {item['path']}") from exc
        except UnicodeDecodeError as exc:
            raise ExperimentCloneError(
                f"input snapshot is not UTF-8 text and cannot be edited: {item['path']}"
            ) from exc
        materials.append(ExperimentMaterial(path=item["path"], content=content))
    return tuple(materials)


def clone_run_as_experiment(
    bundle_path: str | Path,
    request: ExperimentCloneRequest,
    experiments_root: Path,
) -> ExperimentCloneResult:
    """Create an atomic clone that differs in exactly one declared scalar variable."""

    root = Path(bundle_path).resolve(strict=True)
    options = clone_options(root)
    source = _load_bundle_config(root)
    option = next((item for item in options.options if item.path == request.change.path), None)
    if option is None:
        raise ExperimentCloneError("the requested clone variable is not supported")
    after = _coerce_value(option, request.change.value)
    before = option.current
    if after == before:
        raise ExperimentCloneError("the controlled variable must differ from the parent run")

    changed = _apply_change(source, option, after).model_copy(
        update={"id": request.experiment_id, "name": request.name}
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    parent_hash = manifest.get("experiment", {}).get("config_sha256")
    lineage = ExperimentLineage(
        parent_run_id=root.name,
        parent_config_sha256=parent_hash,
        change_path=option.path,
        before=before,
        after=after,
    )
    draft = ExperimentDraft(
        experiment=changed,
        materials=_snapshot_materials(root, source),
        lineage=lineage,
    )
    directory = save_experiment_draft(draft, experiments_root)
    return ExperimentCloneResult(
        parent_run_id=root.name,
        experiment_id=changed.id,
        directory=str(directory),
        manifest=str(directory / "experiment.yaml"),
        lineage=str(directory / "lineage.json"),
        change_path=option.path,
        before=before,
        after=after,
    )
