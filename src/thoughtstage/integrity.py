"""Evidence-backed integrity verification for Thoughtstage run bundles.

The verifier proves properties of the persisted research record. It does not
claim to recover provider-hidden reasoning or prove facts about a provider's
internal request handling that were not recorded by Thoughtstage.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.annotations import AnnotationTarget, ResearchAnnotation
from thoughtstage.experiment_design import ExperimentLineage
from thoughtstage.models import (
    ExperimentConfig,
    FileToolEvent,
    ModelUsageEvent,
    PublicPost,
    PublicStimulus,
    Soliloquy,
)
from thoughtstage.reproducibility import sha256_bytes


class IntegrityStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class IntegrityCheck(BaseModel):
    """One independently inspectable integrity assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    status: IntegrityStatus
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ArtifactDigest(BaseModel):
    """Digest and size for one regular run-bundle artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunIntegrityReport(BaseModel):
    """Deterministic verification report for a run bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    valid: bool
    complete: bool
    boundary_valid: bool
    checks: tuple[IntegrityCheck, ...]
    artifacts: tuple[ArtifactDigest, ...]
    assurance_scope: tuple[str, ...] = (
        "Validates the persisted run bundle, typed streams, hashes, counts, and links.",
        "Confirms that public artifacts contain only typed public records and no "
        "private-channel fields.",
        "Does not claim access to provider-hidden chain of thought.",
        "Does not prove unrecorded provider-side behavior or semantic non-disclosure "
        "by an agent in its own public prose.",
    )


class RunIntegrityError(ValueError):
    """Raised when the requested bundle cannot be inspected safely."""


RecordT = TypeVar("RecordT", bound=BaseModel)


def _artifact_digests(root: Path) -> tuple[list[ArtifactDigest], list[str]]:
    artifacts: list[ArtifactDigest] = []
    unsafe: list[str] = []
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            unsafe.append(relative)
            continue
        if not candidate.is_file():
            continue
        payload = candidate.read_bytes()
        artifacts.append(
            ArtifactDigest(
                path=relative,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    return artifacts, unsafe


def _read_json(path: Path, expected: type[dict] | type[list]) -> dict[str, Any] | list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunIntegrityError(f"missing artifact: {path.name}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunIntegrityError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, expected):
        raise RunIntegrityError(f"unexpected JSON shape: {path.name}")
    return value


def _read_typed_jsonl(path: Path, model: type[RecordT]) -> list[RecordT]:
    if not path.exists():
        return []
    values: list[RecordT] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RunIntegrityError(f"invalid UTF-8 event stream: {path.name}") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            values.append(model.model_validate(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RunIntegrityError(
                f"{path.as_posix()} line {line_number} violates the {model.__name__} schema"
            ) from exc
    return values


def _load_config(path: Path) -> ExperimentConfig:
    try:
        raw = yaml.safe_load(path.read_bytes())
        return ExperimentConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise RunIntegrityError("missing artifact: experiment.yaml") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise RunIntegrityError("experiment.yaml violates the experiment schema") from exc


def _check(
    checks: list[IntegrityCheck],
    code: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
    *,
    evidence: dict[str, Any] | None = None,
    warning: bool = False,
) -> None:
    checks.append(
        IntegrityCheck(
            code=code,
            status=(
                IntegrityStatus.PASS
                if passed
                else IntegrityStatus.WARNING
                if warning
                else IntegrityStatus.FAIL
            ),
            message=pass_message if passed else fail_message,
            evidence=evidence or {},
        )
    )


def _early_report(
    root: Path,
    artifacts: list[ArtifactDigest],
    checks: list[IntegrityCheck],
    code: str,
    message: str,
) -> RunIntegrityReport:
    checks.append(
        IntegrityCheck(
            code=code,
            status=IntegrityStatus.FAIL,
            message=message,
        )
    )
    return RunIntegrityReport(
        run_id=root.name,
        valid=False,
        complete=False,
        boundary_valid=False,
        checks=tuple(checks),
        artifacts=tuple(artifacts),
    )


def _validate_private_briefings(
    root: Path,
    manifest: dict[str, Any],
    checks: list[IntegrityCheck],
) -> None:
    try:
        briefings = _read_json(root / "private" / "agent_briefings.json", dict)
    except RunIntegrityError as exc:
        _check(
            checks,
            "private-briefing-hashes",
            False,
            "",
            str(exc),
        )
        return
    declared = manifest.get("inputs", {}).get("private_briefings", [])
    actual = sorted(
        (
            {"agent_id": agent_id, "sha256": sha256_bytes(content.encode("utf-8"))}
            for agent_id, content in briefings.items()
            if isinstance(agent_id, str) and isinstance(content, str)
        ),
        key=lambda item: item["agent_id"],
    )
    expected = sorted(
        (item for item in declared if isinstance(item, dict)),
        key=lambda item: str(item.get("agent_id", "")),
    )
    valid_shape = len(actual) == len(briefings)
    _check(
        checks,
        "private-briefing-hashes",
        valid_shape and actual == expected,
        "Private briefing contents match the hashes recorded in the manifest.",
        "Private briefing contents or declarations do not match their recorded hashes.",
        evidence={"declared": len(expected), "stored": len(actual)},
    )


def _validate_input_files(
    root: Path,
    manifest: dict[str, Any],
    files: list[Any],
    checks: list[IntegrityCheck],
) -> None:
    declared = manifest.get("inputs", {}).get("files", [])
    metadata_matches = files == declared
    _check(
        checks,
        "input-file-metadata",
        metadata_matches,
        "Input-file metadata matches the manifest.",
        "files.json does not match the input-file metadata recorded in the manifest.",
        evidence={"declared": len(declared), "indexed": len(files)},
    )

    if not files:
        _check(
            checks,
            "input-file-snapshots",
            True,
            "The experiment declared no external input files.",
            "",
            evidence={"declared": 0, "snapshotted": 0},
        )
        return

    snapshot_root = root / "inputs" / "files"
    if not snapshot_root.is_dir():
        _check(
            checks,
            "input-file-snapshots",
            False,
            "",
            "This legacy run records input hashes but does not contain byte snapshots.",
            evidence={"declared": len(files), "snapshotted": 0},
            warning=True,
        )
        return

    mismatches: list[str] = []
    snapshotted = 0
    for item in files:
        if not isinstance(item, dict):
            mismatches.append("<invalid metadata>")
            continue
        path = item.get("path")
        if not isinstance(path, str):
            mismatches.append("<missing path>")
            continue
        logical = PurePosixPath(path)
        if logical.is_absolute() or ".." in logical.parts:
            mismatches.append(path)
            continue
        candidate = snapshot_root.joinpath(*logical.parts)
        if candidate.is_symlink() or not candidate.is_file():
            mismatches.append(path)
            continue
        payload = candidate.read_bytes()
        snapshotted += 1
        if len(payload) != item.get("size") or sha256_bytes(payload) != item.get("sha256"):
            mismatches.append(path)
    _check(
        checks,
        "input-file-snapshots",
        not mismatches and snapshotted == len(files),
        "Every declared input file is snapshotted and matches its recorded digest.",
        "One or more input-file snapshots are missing or differ from their recorded digest.",
        evidence={
            "declared": len(files),
            "snapshotted": snapshotted,
            "mismatches": mismatches,
        },
    )


def _validate_streams(
    root: Path,
    config: ExperimentConfig,
    manifest: dict[str, Any],
    checks: list[IntegrityCheck],
) -> tuple[
    list[PublicPost],
    list[PublicStimulus],
    list[Soliloquy],
    list[ModelUsageEvent],
    list[FileToolEvent],
]:
    stream_specs: tuple[tuple[str, Path, type[BaseModel]], ...] = (
        ("public-post-schema", root / "public.jsonl", PublicPost),
        ("public-stimulus-schema", root / "public" / "stimuli.jsonl", PublicStimulus),
        (
            "private-soliloquy-schema",
            root / "private" / "soliloquies.jsonl",
            Soliloquy,
        ),
        ("private-usage-schema", root / "private" / "model_usage.jsonl", ModelUsageEvent),
        ("private-file-tool-schema", root / "private" / "file_tools.jsonl", FileToolEvent),
    )
    loaded: list[list[BaseModel]] = []
    for code, path, model in stream_specs:
        try:
            records = _read_typed_jsonl(path, model)
        except RunIntegrityError as exc:
            _check(checks, code, False, "", str(exc))
            records = []
        else:
            _check(
                checks,
                code,
                True,
                f"{len(records)} record(s) satisfy the {model.__name__} schema.",
                "",
                evidence={"records": len(records), "path": path.relative_to(root).as_posix()},
            )
        loaded.append(records)

    posts = [item for item in loaded[0] if isinstance(item, PublicPost)]
    stimuli = [item for item in loaded[1] if isinstance(item, PublicStimulus)]
    soliloquies = [item for item in loaded[2] if isinstance(item, Soliloquy)]
    usage = [item for item in loaded[3] if isinstance(item, ModelUsageEvent)]
    file_tools = [item for item in loaded[4] if isinstance(item, FileToolEvent)]

    experiment_ids = {
        item.experiment_id for item in [*posts, *stimuli, *soliloquies, *usage, *file_tools]
    }
    _check(
        checks,
        "experiment-identity",
        not experiment_ids or experiment_ids == {config.id},
        "Every event belongs to the declared experiment.",
        "One or more events use an unexpected experiment identifier.",
        evidence={"expected": config.id, "observed": sorted(experiment_ids)},
    )

    public_events: list[PublicPost | PublicStimulus] = sorted(
        [*posts, *stimuli],
        key=lambda item: item.sequence,
    )
    sequences = [item.sequence for item in public_events]
    _check(
        checks,
        "public-sequence",
        sequences == list(range(1, len(sequences) + 1)),
        "The public event sequence is unique, contiguous, and ordered.",
        "The public event sequence contains a gap, duplicate, or ordering error.",
        evidence={"events": len(sequences), "observed": sequences},
    )

    expected_turns = config.rounds * len(config.agents)
    turn_counts = Counter((post.round_number, post.agent_id) for post in posts)
    expected_turn_keys = {
        (round_number, agent.id)
        for round_number in range(1, config.rounds + 1)
        for agent in config.agents
    }
    observed_turn_keys = set(turn_counts)
    complete_turn_matrix = (
        len(posts) == expected_turns
        and observed_turn_keys == expected_turn_keys
        and all(count == 1 for count in turn_counts.values())
    )
    status_completed = manifest.get("status") == "completed"
    _check(
        checks,
        "turn-matrix-completeness",
        complete_turn_matrix if status_completed else observed_turn_keys <= expected_turn_keys,
        (
            "Every declared participant has exactly one public post in every round."
            if status_completed
            else "The partial turn matrix is a valid prefix of the declared experiment."
        ),
        "The public turn matrix is missing, duplicating, or introducing undeclared turns.",
        evidence={"expected": expected_turns, "observed": len(posts)},
    )

    posts_by_id = {post.event_id: post for post in posts}
    soliloquies_by_post: dict[str, list[Soliloquy]] = defaultdict(list)
    for item in soliloquies:
        soliloquies_by_post[item.post_event_id].append(item)
    pairing_errors: list[str] = []
    for post in posts:
        paired = soliloquies_by_post.get(post.event_id, [])
        if len(paired) != 1:
            pairing_errors.append(post.event_id)
            continue
        private = paired[0]
        if (
            private.sequence != post.sequence
            or private.experiment_id != post.experiment_id
            or private.round_number != post.round_number
            or private.agent_id != post.agent_id
        ):
            pairing_errors.append(post.event_id)
    orphaned = sorted(set(soliloquies_by_post) - set(posts_by_id))
    _check(
        checks,
        "public-private-pairing",
        not pairing_errors and not orphaned and len(soliloquies) == len(posts),
        "Every public post has exactly one field-consistent private soliloquy.",
        "Public posts and private soliloquies do not form a one-to-one field-consistent pairing.",
        evidence={"pairing_errors": pairing_errors, "orphaned_private_records": orphaned},
    )

    agent_bindings = {agent.id: (agent.provider, agent.model) for agent in config.agents}
    telemetry_errors: list[str] = []
    for item in [*usage, *file_tools]:
        post = posts_by_id.get(item.post_event_id)
        binding = agent_bindings.get(item.agent_id)
        if (
            post is None
            or post.agent_id != item.agent_id
            or post.sequence != item.sequence
            or post.round_number != item.round_number
            or binding != (item.provider, item.model)
        ):
            telemetry_errors.append(item.event_id)
    _check(
        checks,
        "private-telemetry-links",
        not telemetry_errors,
        "Every private telemetry record links to the correct post and agent binding.",
        "One or more private telemetry records have an invalid post or binding link.",
        evidence={"records": len(usage) + len(file_tools), "errors": telemetry_errors},
    )

    public_fields = (
        set().union(*(set(item.model_dump().keys()) for item in public_events))
        if public_events
        else set()
    )
    prohibited = {
        "soliloquy",
        "post_event_id",
        "provider",
        "model",
        "credential_env",
        "private_briefing",
        "input_tokens",
        "output_tokens",
        "response_id",
    }
    leaked_fields = sorted(public_fields & prohibited)
    _check(
        checks,
        "public-metadata-isolation",
        not leaked_fields,
        "Public records contain no private-channel, provider, model, credential, or usage fields.",
        "Public records contain fields reserved for researcher-private channels.",
        evidence={"prohibited_fields_found": leaked_fields},
    )

    event_ids = [item.event_id for item in [*posts, *stimuli, *soliloquies, *usage, *file_tools]]
    duplicates = sorted(item for item, count in Counter(event_ids).items() if count > 1)
    _check(
        checks,
        "event-identity-uniqueness",
        not duplicates,
        "Every persisted event identifier is unique.",
        "One or more event identifiers are duplicated.",
        evidence={"duplicates": duplicates},
    )

    return posts, stimuli, soliloquies, usage, file_tools


def _validate_stimuli(
    config: ExperimentConfig,
    stimuli: list[PublicStimulus],
    manifest: dict[str, Any],
    checks: list[IntegrityCheck],
) -> None:
    declared = manifest.get("inputs", {}).get("scheduled_stimuli", [])
    expected_by_id = {item.id: item for item in config.stimuli}
    actual_by_id = {item.stimulus_id: item for item in stimuli}
    errors: list[str] = []
    for item in declared:
        if not isinstance(item, dict):
            errors.append("<invalid declaration>")
            continue
        stimulus_id = item.get("id")
        config_item = expected_by_id.get(stimulus_id)
        event = actual_by_id.get(stimulus_id)
        if config_item is None or event is None:
            errors.append(str(stimulus_id))
            continue
        if (
            item.get("round") != config_item.round
            or item.get("source_id") != config_item.source_id
            or item.get("sha256") != sha256_bytes(config_item.content.encode("utf-8"))
            or event.round_number != config_item.round
            or event.source_id != config_item.source_id
            or event.content != config_item.content
        ):
            errors.append(str(stimulus_id))
    valid = (
        not errors and len(declared) == len(config.stimuli) and len(stimuli) == len(config.stimuli)
    )
    _check(
        checks,
        "scheduled-stimulus-provenance",
        valid,
        "Every scheduled public stimulus matches its declaration and content hash.",
        "Scheduled public stimuli differ from the experiment or manifest provenance.",
        evidence={"declared": len(config.stimuli), "observed": len(stimuli), "errors": errors},
    )


def _validate_counts(
    manifest: dict[str, Any],
    posts: list[PublicPost],
    stimuli: list[PublicStimulus],
    soliloquies: list[Soliloquy],
    usage: list[ModelUsageEvent],
    file_tools: list[FileToolEvent],
    checks: list[IntegrityCheck],
) -> None:
    actual = {
        "public_posts": len(posts),
        "public_stimuli": len(stimuli),
        "soliloquies": len(soliloquies),
        "model_calls": len(usage),
        "file_tool_calls": len(file_tools),
    }
    recorded = manifest.get("counts", {})
    _check(
        checks,
        "manifest-counts",
        recorded == actual,
        "Manifest counts match every persisted event stream.",
        "Manifest counts differ from the persisted event streams.",
        evidence={"recorded": recorded, "actual": actual},
    )


def _validate_annotations(
    root: Path,
    posts: list[PublicPost],
    stimuli: list[PublicStimulus],
    soliloquies: list[Soliloquy],
    checks: list[IntegrityCheck],
) -> None:
    path = root / "private" / "annotations.json"
    if not path.exists():
        _check(
            checks,
            "private-annotation-schema",
            True,
            "The run has no researcher annotations.",
            "",
            evidence={"annotations": 0},
        )
        return
    try:
        raw = _read_json(path, list)
        assert isinstance(raw, list)
        annotations = [ResearchAnnotation.model_validate(item) for item in raw]
    except (RunIntegrityError, ValidationError, AssertionError) as exc:
        _check(
            checks,
            "private-annotation-schema",
            False,
            "",
            f"The researcher annotation store is invalid: {exc}",
        )
        return

    targets = (
        {(AnnotationTarget.POST, item.event_id) for item in posts}
        | {(AnnotationTarget.STIMULUS, item.event_id) for item in stimuli}
        | {(AnnotationTarget.SOLILOQUY, item.event_id) for item in soliloquies}
    )
    invalid = [
        item.annotation_id
        for item in annotations
        if item.run_id != root.name or (item.target_type, item.target_event_id) not in targets
    ]
    duplicates = [
        annotation_id
        for annotation_id, count in Counter(item.annotation_id for item in annotations).items()
        if count > 1
    ]
    _check(
        checks,
        "private-annotation-schema",
        not invalid and not duplicates,
        "Every researcher annotation is typed and links to one event in this run.",
        "One or more researcher annotations are duplicated or target an invalid event.",
        evidence={
            "annotations": len(annotations),
            "invalid": invalid,
            "duplicates": duplicates,
        },
    )


def _validate_lineage(
    root: Path,
    manifest: dict[str, Any],
    checks: list[IntegrityCheck],
) -> None:
    path = root / "lineage.json"
    declared = manifest.get("lineage")
    if not path.exists() and declared is None:
        _check(
            checks,
            "experiment-lineage",
            True,
            "This run does not claim controlled-clone lineage.",
            "",
            evidence={"present": False},
        )
        return
    try:
        raw = _read_json(path, dict)
        assert isinstance(raw, dict)
        lineage = ExperimentLineage.model_validate(raw).model_dump(mode="json")
    except (RunIntegrityError, ValidationError, AssertionError) as exc:
        _check(checks, "experiment-lineage", False, "", f"Run lineage is invalid: {exc}")
        return
    _check(
        checks,
        "experiment-lineage",
        lineage == declared,
        "Controlled-clone lineage is typed and matches the run manifest.",
        "Controlled-clone lineage differs from the run manifest declaration.",
        evidence={"present": True, "parent_run_id": lineage["parent_run_id"]},
    )


def verify_run_bundle(bundle_path: str | Path) -> RunIntegrityReport:
    """Verify a run bundle without modifying it."""

    try:
        root = Path(bundle_path).resolve(strict=True)
    except FileNotFoundError as exc:
        raise RunIntegrityError("run bundle was not found") from exc
    if not root.is_dir():
        raise RunIntegrityError("run bundle must be a directory")

    checks: list[IntegrityCheck] = []
    artifacts, unsafe = _artifact_digests(root)
    _check(
        checks,
        "artifact-path-safety",
        not unsafe,
        "Every artifact is a regular file confined to the run bundle.",
        "The run bundle contains symbolic links or unsafe artifact paths.",
        evidence={"unsafe_paths": unsafe, "regular_files": len(artifacts)},
    )

    required = {
        "manifest.json",
        "experiment.yaml",
        "files.json",
        "public.jsonl",
        "private/agent_briefings.json",
        "private/soliloquies.jsonl",
    }
    present = {item.path for item in artifacts}
    missing = sorted(required - present)
    _check(
        checks,
        "required-artifacts",
        not missing,
        "Every required run artifact is present.",
        "The run bundle is missing required artifacts.",
        evidence={"missing": missing},
    )

    try:
        manifest_raw = _read_json(root / "manifest.json", dict)
        assert isinstance(manifest_raw, dict)
        manifest = manifest_raw
    except (RunIntegrityError, AssertionError) as exc:
        return _early_report(root, artifacts, checks, "manifest-schema", str(exc))
    _check(
        checks,
        "manifest-schema",
        True,
        "The run manifest is a JSON object.",
        "",
        evidence={"schema_version": manifest.get("schema_version")},
    )

    run_id_matches = manifest.get("run_id") == root.name
    _check(
        checks,
        "run-identity",
        run_id_matches,
        "The manifest run identifier matches its bundle directory.",
        "The manifest run identifier does not match its bundle directory.",
        evidence={"directory": root.name, "manifest": manifest.get("run_id")},
    )

    try:
        config = _load_config(root / "experiment.yaml")
    except RunIntegrityError as exc:
        return _early_report(root, artifacts, checks, "experiment-schema", str(exc))
    _check(
        checks,
        "experiment-schema",
        True,
        "The bundled experiment satisfies the typed experiment schema.",
        "",
        evidence={"experiment_id": config.id, "participants": len(config.agents)},
    )

    source_bytes = (root / "experiment.yaml").read_bytes()
    recorded_config_hash = manifest.get("experiment", {}).get("config_sha256")
    actual_config_hash = sha256_bytes(source_bytes)
    _check(
        checks,
        "experiment-config-digest",
        actual_config_hash == recorded_config_hash,
        "The bundled experiment bytes match the manifest SHA-256.",
        "The bundled experiment bytes differ from the manifest SHA-256.",
        evidence={"recorded": recorded_config_hash, "actual": actual_config_hash},
    )

    identity_matches = manifest.get("experiment", {}).get("id") == config.id
    _check(
        checks,
        "experiment-config-identity",
        identity_matches,
        "The bundled experiment identity matches the manifest.",
        "The bundled experiment identity differs from the manifest.",
        evidence={
            "manifest": manifest.get("experiment", {}).get("id"),
            "experiment": config.id,
        },
    )
    _validate_lineage(root, manifest, checks)

    try:
        files_raw = _read_json(root / "files.json", list)
        assert isinstance(files_raw, list)
        files = files_raw
    except (RunIntegrityError, AssertionError) as exc:
        return _early_report(root, artifacts, checks, "input-file-metadata", str(exc))
    _validate_input_files(root, manifest, files, checks)
    _validate_private_briefings(root, manifest, checks)

    posts, stimuli, soliloquies, usage, file_tools = _validate_streams(
        root,
        config,
        manifest,
        checks,
    )
    _validate_stimuli(config, stimuli, manifest, checks)
    _validate_counts(
        manifest,
        posts,
        stimuli,
        soliloquies,
        usage,
        file_tools,
        checks,
    )
    _validate_annotations(root, posts, stimuli, soliloquies, checks)

    status_completed = manifest.get("status") == "completed"
    expected_turns = config.rounds * len(config.agents)
    complete = (
        status_completed
        and len(posts) == expected_turns
        and len(soliloquies) == expected_turns
        and len(stimuli) == len(config.stimuli)
    )
    _check(
        checks,
        "run-completion",
        complete,
        "The run is terminal and contains every declared turn and stimulus.",
        (
            "The run is incomplete or its terminal streams do not contain every "
            "declared turn and stimulus."
        ),
        evidence={
            "status": manifest.get("status"),
            "expected_turns": expected_turns,
            "public_posts": len(posts),
            "soliloquies": len(soliloquies),
            "expected_stimuli": len(config.stimuli),
            "public_stimuli": len(stimuli),
        },
        warning=not status_completed,
    )

    valid = all(item.status is not IntegrityStatus.FAIL for item in checks)
    boundary_codes = {
        "public-post-schema",
        "public-stimulus-schema",
        "private-soliloquy-schema",
        "public-private-pairing",
        "public-metadata-isolation",
    }
    boundary_valid = all(
        item.status is IntegrityStatus.PASS for item in checks if item.code in boundary_codes
    ) and boundary_codes <= {item.code for item in checks}
    return RunIntegrityReport(
        run_id=root.name,
        valid=valid,
        complete=complete,
        boundary_valid=boundary_valid,
        checks=tuple(checks),
        artifacts=tuple(artifacts),
    )
