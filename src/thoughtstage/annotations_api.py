"""Researcher-only annotation API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from thoughtstage.annotations import (
    AnnotationDraft,
    AnnotationError,
    AnnotationUpdate,
    create_annotation,
    delete_annotation,
    list_annotations,
    update_annotation,
)
from thoughtstage.observer import RunBundleNotFoundError, resolve_run_bundle_path

router = APIRouter(prefix="/api/runs/{run_id}/annotations", tags=["annotations"])


def _root(run_id: str):
    try:
        return resolve_run_bundle_path(run_id)
    except RunBundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def annotations(run_id: str) -> dict:
    """List annotations without merging them into either experiment stream."""

    try:
        items = list_annotations(_root(run_id))
    except AnnotationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run_id, "annotations": [item.model_dump(mode="json") for item in items]}


@router.post("", status_code=status.HTTP_201_CREATED)
def add_annotation(run_id: str, draft: AnnotationDraft) -> dict:
    """Bookmark or annotate one typed public or private event."""

    try:
        return create_annotation(_root(run_id), draft).model_dump(mode="json")
    except AnnotationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{annotation_id}")
def edit_annotation(run_id: str, annotation_id: str, update: AnnotationUpdate) -> dict:
    """Update researcher-authored annotation fields only."""

    try:
        return update_annotation(_root(run_id), annotation_id, update).model_dump(mode="json")
    except AnnotationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_annotation(run_id: str, annotation_id: str) -> Response:
    """Delete an annotation while preserving its target event unchanged."""

    try:
        delete_annotation(_root(run_id), annotation_id)
    except AnnotationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
