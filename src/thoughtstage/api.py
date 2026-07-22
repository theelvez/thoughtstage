"""Local research API."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from thoughtstage import __version__
from thoughtstage.models import ExperimentConfig
from thoughtstage.observer import (
    RunBundleNotFoundError,
    RunBundleUnavailableError,
    list_run_bundles,
    read_run_bundle,
)

app = FastAPI(
    title="Thoughtstage",
    summary="An open social laboratory for AI agents",
    version=__version__,
)


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
