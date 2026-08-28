"""Read-only researcher analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from thoughtstage.consensus import analyze_consensus
from thoughtstage.integrity import RunIntegrityError, verify_run_bundle
from thoughtstage.observer import (
    RunBundleNotFoundError,
    RunBundleUnavailableError,
    read_run_bundle,
    resolve_run_bundle_path,
)

router = APIRouter(prefix="/api/runs/{run_id}/analysis", tags=["analysis"])


@router.get("/consensus")
def consensus_timeline(run_id: str) -> dict:
    """Return an explicitly heuristic timeline derived from public posts only."""

    try:
        path = resolve_run_bundle_path(run_id)
        report = verify_run_bundle(path)
        if not report.valid:
            raise RunIntegrityError("run integrity verification failed")
        detail = read_run_bundle(run_id)
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunBundleUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RunIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return analyze_consensus(run_id, detail["posts"]).model_dump(mode="json")
