"""Read-only views over in-progress and completed run bundles."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from thoughtstage.usage import summarize_model_usage

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RunBundleNotFoundError(FileNotFoundError):
    """Raised when a requested run bundle is absent or invalid."""


class RunBundleUnavailableError(RuntimeError):
    """Raised when a run bundle is between writer updates."""


def configured_runs_root() -> Path:
    """Resolve the researcher-controlled run-bundle directory."""

    return Path(os.getenv("THOUGHTSTAGE_RUNS_DIR", "runs")).resolve()


def _run_path(run_id: str, root: Path) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise RunBundleNotFoundError("invalid run id")
    candidate = (root / run_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RunBundleNotFoundError("invalid run id") from exc
    if not candidate.is_dir():
        raise RunBundleNotFoundError(f"run {run_id!r} was not found")
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunBundleNotFoundError(f"missing run manifest: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RunBundleUnavailableError(f"run manifest is being updated: {path.name}") from exc
    if not isinstance(value, dict):
        raise RunBundleUnavailableError(f"run manifest is not an object: {path.name}")
    return value


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path)


def _read_system_prompt(path: Path) -> str | None:
    try:
        value = yaml.safe_load(path.read_bytes())
    except (FileNotFoundError, yaml.YAMLError):
        return None
    if not isinstance(value, dict):
        return None
    system_prompt = value.get("system_prompt")
    return system_prompt if isinstance(system_prompt, str) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            # A poll can overlap the writer's final append. The complete record
            # will be returned on the next poll.
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _summary(
    manifest: dict[str, Any],
    posts: int,
    stimuli: int,
    soliloquies: int,
    model_calls: int,
    file_tool_calls: int,
) -> dict[str, Any]:
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status", "unknown"),
        "created_at": manifest.get("created_at"),
        "completed_at": manifest.get("completed_at"),
        "failure": manifest.get("failure"),
        "experiment": manifest.get("experiment", {}),
        "execution": manifest.get("execution", {}),
        "agents": manifest.get("agents", []),
        "counts": {
            "public_posts": posts,
            "public_stimuli": stimuli,
            "soliloquies": soliloquies,
            "model_calls": model_calls,
            "file_tool_calls": file_tool_calls,
        },
    }


def read_run_bundle(run_id: str, *, root: Path | None = None) -> dict[str, Any]:
    """Return a researcher view of one run's separated event streams."""

    runs_root = (root or configured_runs_root()).resolve()
    path = _run_path(run_id, runs_root)
    manifest = _read_json(path / "manifest.json")
    posts = _read_jsonl(path / "public.jsonl")
    stimuli = _read_jsonl(path / "public" / "stimuli.jsonl")
    public_events = sorted(
        [*posts, *stimuli],
        key=lambda event: event.get("sequence", 0),
    )
    soliloquies = _read_jsonl(path / "private" / "soliloquies.jsonl")
    model_usage = _read_jsonl(path / "private" / "model_usage.jsonl")
    file_tools = _read_jsonl(path / "private" / "file_tools.jsonl")
    private_briefings = _read_optional_json(path / "private" / "agent_briefings.json")
    summary = _summary(
        manifest,
        len(posts),
        len(stimuli),
        len(soliloquies),
        len(model_usage),
        len(file_tools),
    )
    experiment = summary["experiment"]
    if "system_prompt" not in experiment:
        system_prompt = _read_system_prompt(path / "experiment.yaml")
        if system_prompt is not None:
            summary["experiment"] = {**experiment, "system_prompt": system_prompt}
    return {
        **summary,
        "posts": public_events,
        "stimuli": stimuli,
        "model_usage": model_usage,
        "file_tools": file_tools,
        "usage_summary": summarize_model_usage(model_usage),
        "soliloquies": soliloquies,
        "private_briefings": private_briefings,
    }


def list_run_bundles(*, root: Path | None = None) -> list[dict[str, Any]]:
    """List readable run bundles, newest first, with live event counts."""

    runs_root = (root or configured_runs_root()).resolve()
    if not runs_root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in runs_root.iterdir():
        if not path.is_dir() or RUN_ID_PATTERN.fullmatch(path.name) is None:
            continue
        try:
            manifest = _read_json(path / "manifest.json")
        except (RunBundleNotFoundError, RunBundleUnavailableError):
            continue
        posts = _read_jsonl(path / "public.jsonl")
        stimuli = _read_jsonl(path / "public" / "stimuli.jsonl")
        soliloquies = _read_jsonl(path / "private" / "soliloquies.jsonl")
        model_usage = _read_jsonl(path / "private" / "model_usage.jsonl")
        file_tools = _read_jsonl(path / "private" / "file_tools.jsonl")
        runs.append(
            _summary(
                manifest,
                len(posts),
                len(stimuli),
                len(soliloquies),
                len(model_usage),
                len(file_tools),
            )
        )
    return sorted(runs, key=lambda item: item.get("created_at") or "", reverse=True)
