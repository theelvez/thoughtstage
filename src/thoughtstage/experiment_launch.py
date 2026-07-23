"""Validate and launch saved experiments without exposing credential values."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from thoughtstage.config import ExperimentLoadError, LoadedExperiment, load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.observer import configured_runs_root
from thoughtstage.providers.azure_foundry import FoundrySettings
from thoughtstage.providers.bedrock import BedrockSettings

EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
KNOWN_PROVIDERS = frozenset({"azure_foundry", "bedrock", "mock"})
GENERIC_FAILURE_MESSAGE = (
    "Experiment execution failed. Check provider configuration and server logs."
)

logger = logging.getLogger(__name__)


class ExperimentLaunchError(ValueError):
    """Raised when a saved experiment cannot be safely launched."""


class ExperimentNotFoundError(ExperimentLaunchError):
    """Raised when a requested saved experiment does not exist."""


class ProviderReadinessError(ExperimentLaunchError):
    """Raised when required provider configuration is absent."""


@dataclass(frozen=True)
class PreparedLaunch:
    """A validated launch request containing no credential values."""

    loaded: LoadedExperiment
    run_id: str
    runs_root: Path


def _experiment_manifest(experiment_id: str, experiments_root: Path) -> Path:
    if EXPERIMENT_ID_PATTERN.fullmatch(experiment_id) is None:
        raise ExperimentNotFoundError("invalid experiment id")
    root = experiments_root.resolve()
    candidate = (root / experiment_id / "experiment.yaml").resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ExperimentNotFoundError("invalid experiment id") from exc
    if not candidate.is_file():
        raise ExperimentNotFoundError(f"experiment {experiment_id!r} was not found")
    return candidate


def _missing_environment(loaded: LoadedExperiment) -> tuple[str, ...]:
    missing: set[str] = set()
    unknown = sorted({agent.provider for agent in loaded.config.agents} - KNOWN_PROVIDERS)
    if unknown:
        raise ProviderReadinessError("Unsupported provider bindings: " + ", ".join(unknown))

    for agent in loaded.config.agents:
        if agent.credential_env and not os.getenv(agent.credential_env, "").strip():
            missing.add(agent.credential_env)
        if agent.provider == "azure_foundry":
            try:
                settings = FoundrySettings.model_validate(agent.parameters)
            except ValidationError as exc:
                raise ProviderReadinessError(
                    f"Invalid Microsoft Foundry settings for participant {agent.id!r}."
                ) from exc
            if not os.getenv(settings.endpoint_env, "").strip():
                missing.add(settings.endpoint_env)
        elif agent.provider == "bedrock":
            try:
                BedrockSettings.model_validate(agent.parameters)
            except ValidationError as exc:
                raise ProviderReadinessError(
                    f"Invalid Amazon Bedrock settings for participant {agent.id!r}."
                ) from exc
    return tuple(sorted(missing))


def prepare_launch(
    experiment_id: str,
    *,
    experiments_root: Path,
    runs_root: Path | None = None,
) -> PreparedLaunch:
    """Load a saved experiment and verify non-secret provider readiness."""

    manifest = _experiment_manifest(experiment_id, experiments_root)
    try:
        loaded = load_experiment(manifest)
    except (ExperimentLoadError, OSError) as exc:
        raise ExperimentLaunchError("saved experiment is invalid") from exc
    if loaded.config.id != experiment_id:
        raise ExperimentLaunchError("saved experiment id does not match its directory")

    missing = _missing_environment(loaded)
    if missing:
        raise ProviderReadinessError(
            "Provider configuration is incomplete. Set environment variables: " + ", ".join(missing)
        )

    resolved_runs_root = (runs_root or configured_runs_root()).resolve()
    resolved_runs_root.mkdir(parents=True, exist_ok=True)
    while True:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{experiment_id}-{secrets.token_hex(3)}"
        if not (resolved_runs_root / run_id).exists():
            break
    return PreparedLaunch(loaded=loaded, run_id=run_id, runs_root=resolved_runs_root)


def mark_run_failed(path: Path, failure: BaseException) -> None:
    """Give an existing bundle a terminal, secret-free failure state."""

    manifest_path = path / "manifest.json"
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(manifest, dict):
        return
    manifest["status"] = "failed"
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    manifest["failure"] = {
        "type": type(failure).__name__,
        "message": GENERIC_FAILURE_MESSAGE,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    try:
        temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(manifest_path)
    except OSError:
        logger.error("could not mark run %s failed", path.name)


def execute_launch(prepared: PreparedLaunch) -> None:
    """Run an experiment in a background worker and record safe failure metadata."""

    try:
        ExperimentEngine().run(
            prepared.loaded,
            output_root=prepared.runs_root,
            run_id=prepared.run_id,
        )
    except Exception as exc:  # The worker must always leave a terminal run state.
        mark_run_failed(prepared.runs_root / prepared.run_id, exc)
        logger.error(
            "experiment run %s failed with %s",
            prepared.run_id,
            type(exc).__name__,
        )
