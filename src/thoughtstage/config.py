"""Load and validate versioned experiment manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from thoughtstage.models import ExperimentConfig


class ExperimentLoadError(ValueError):
    """Raised when an experiment file cannot be loaded safely."""


@dataclass(frozen=True)
class LoadedExperiment:
    config: ExperimentConfig
    source_path: Path
    source_bytes: bytes
    files_root: Path | None


def _resolve_files_root(source_path: Path, raw_value: str | None) -> Path | None:
    if raw_value is None:
        return None
    declared = Path(raw_value)
    if declared.is_absolute():
        raise ExperimentLoadError("files_dir must be relative to the experiment manifest")
    experiment_dir = source_path.parent.resolve()
    candidate = (experiment_dir / declared).resolve(strict=True)
    try:
        candidate.relative_to(experiment_dir)
    except ValueError as exc:
        raise ExperimentLoadError("files_dir must remain inside the experiment directory") from exc
    if not candidate.is_dir():
        raise ExperimentLoadError("files_dir must refer to a directory")
    return candidate


def load_experiment(path: str | Path) -> LoadedExperiment:
    source_path = Path(path).resolve(strict=True)
    if not source_path.is_file():
        raise ExperimentLoadError(f"experiment manifest is not a file: {source_path}")

    source_bytes = source_path.read_bytes()
    try:
        raw: Any = yaml.safe_load(source_bytes)
    except yaml.YAMLError as exc:
        raise ExperimentLoadError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExperimentLoadError("experiment manifest must contain a YAML mapping")

    try:
        config = ExperimentConfig.model_validate(raw)
    except ValidationError as exc:
        raise ExperimentLoadError(str(exc)) from exc

    return LoadedExperiment(
        config=config,
        source_path=source_path,
        source_bytes=source_bytes,
        files_root=_resolve_files_root(source_path, config.files_dir),
    )
