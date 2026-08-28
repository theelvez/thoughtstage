"""Local research API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.responses import Response

from thoughtstage import __version__
from thoughtstage.analysis_api import router as analysis_router
from thoughtstage.annotations_api import router as annotations_router
from thoughtstage.bundle_export import (
    ReproducibilityExportError,
    build_reproducibility_archive,
)
from thoughtstage.experiment_clone import (
    ExperimentCloneError,
    ExperimentCloneRequest,
    clone_options,
    clone_run_as_experiment,
)
from thoughtstage.experiment_design import (
    ExperimentAlreadyExistsError,
    ExperimentDraft,
    artifact_paths,
    render_experiment_yaml,
    save_experiment_draft,
)
from thoughtstage.experiment_launch import (
    ExperimentLaunchError,
    ExperimentNotFoundError,
    ProviderReadinessError,
    execute_launch,
    prepare_launch,
)
from thoughtstage.integrity import RunIntegrityError, verify_run_bundle
from thoughtstage.models import ExperimentConfig
from thoughtstage.observer import (
    RunBundleNotFoundError,
    RunBundleUnavailableError,
    list_run_bundles,
    read_run_bundle,
    resolve_run_bundle_path,
)
from thoughtstage.participant_roster import (
    ParticipantRosterRequest,
    generate_participant_roster,
)
from thoughtstage.run_comparison import (
    RunComparisonError,
    RunComparisonRequest,
    compare_runs,
)

app = FastAPI(
    title="Thoughtstage",
    summary="An open social laboratory for AI agents",
    version=__version__,
)

app.include_router(annotations_router)

app.include_router(analysis_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/schema/experiment")
def experiment_schema() -> dict:
    return ExperimentConfig.model_json_schema()


@app.get("/api/design-contract")
def design_contract() -> dict:
    return {
        "shared_system_prompt": "byte-identical for every agent",
        "public_channel": "all eligible posts and stimuli are visible to all agents",
        "scheduled_stimuli": "typed public events declared in the experiment manifest",
        "private_channel": "soliloquies are researcher-only",
        "model_identity": "provider and model metadata are never placed in agent context",
        "default_private_memory": "none",
    }


@app.post("/api/participant-rosters")
def participant_roster(request: ParticipantRosterRequest) -> dict:
    """Suggest seeded display names without writing experiment data."""

    return generate_participant_roster(request).model_dump(mode="json")


def _experiments_root() -> Path:
    return Path(os.getenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", "experiments"))


@app.post("/api/experiments/preview")
def preview_experiment(draft: ExperimentDraft) -> dict:
    """Compile a typed wizard draft without writing researcher data."""

    return {
        "valid": True,
        "experiment_id": draft.experiment.id,
        "yaml": render_experiment_yaml(draft),
        "artifacts": artifact_paths(draft),
    }


@app.post("/api/experiments", status_code=status.HTTP_201_CREATED)
def create_experiment(draft: ExperimentDraft) -> dict:
    """Atomically materialize a new, validated experiment workspace."""

    try:
        directory = save_experiment_draft(draft, _experiments_root())
    except ExperimentAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "created": True,
        "experiment_id": draft.experiment.id,
        "directory": str(directory),
        "manifest": str(directory / "experiment.yaml"),
        "artifacts": artifact_paths(draft),
    }


@app.post(
    "/api/experiments/{experiment_id}/launch",
    status_code=status.HTTP_202_ACCEPTED,
)
def launch_experiment(experiment_id: str, background_tasks: BackgroundTasks) -> dict:
    """Validate provider readiness and launch a saved experiment asynchronously."""

    try:
        prepared = prepare_launch(
            experiment_id,
            experiments_root=_experiments_root(),
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderReadinessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ExperimentLaunchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background_tasks.add_task(execute_launch, prepared)
    return {
        "accepted": True,
        "experiment_id": experiment_id,
        "run_id": prepared.run_id,
        "observer_url": f"/?run={prepared.run_id}",
    }


@app.get("/api/runs")
def runs() -> dict:
    """List researcher-visible run bundles with live stream counts."""

    return {"runs": list_run_bundles()}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    """Read one run's public and private streams without mutating it."""

    try:
        return read_run_bundle(run_id)
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunBundleUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/integrity")
def run_integrity(run_id: str) -> dict:
    """Return machine-readable evidence for persisted run-bundle integrity."""

    try:
        path = resolve_run_bundle_path(run_id)
        return verify_run_bundle(path).model_dump(mode="json")
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunIntegrityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/reproducibility-bundle")
def reproducibility_bundle(run_id: str) -> Response:
    """Download a completed run's self-verifying researcher-private archive."""

    try:
        path = resolve_run_bundle_path(run_id)
        payload, report = build_reproducibility_archive(path)
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RunIntegrityError, ReproducibilityExportError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = f"thoughtstage-{report.run_id}-reproducibility.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Thoughtstage-Integrity": "verified",
        },
    )


@app.get("/api/runs/{run_id}/clone-options")
def run_clone_options(run_id: str) -> dict:
    """List scalar variables available for a controlled one-variable clone."""

    try:
        path = resolve_run_bundle_path(run_id)
        return clone_options(path).model_dump(mode="json")
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RunIntegrityError, ExperimentCloneError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/runs/{run_id}/clone",
    status_code=status.HTTP_201_CREATED,
)
def clone_run(run_id: str, request: ExperimentCloneRequest) -> dict:
    """Create a new experiment with exactly one declared variable changed."""

    try:
        path = resolve_run_bundle_path(run_id)
        return clone_run_as_experiment(
            path,
            request,
            _experiments_root(),
        ).model_dump(mode="json")
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RunIntegrityError, ExperimentCloneError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/run-comparisons")
def run_comparison(request: RunComparisonRequest) -> dict:
    """Compare control, treatment, counterbalance, or replication runs."""

    try:
        return compare_runs(request).model_dump(mode="json")
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RunIntegrityError, RunComparisonError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
