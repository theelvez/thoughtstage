"""Local research API."""

from __future__ import annotations

from fastapi import FastAPI

from thoughtstage import __version__
from thoughtstage.models import ExperimentConfig

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
        "public_channel": "all eligible posts are visible to all agents",
        "private_channel": "soliloquies are researcher-only",
        "model_identity": "provider and model metadata are never placed in agent context",
        "default_private_memory": "none",
    }
