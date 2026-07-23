"""Typed researcher-only bookmarks and annotations for run events."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from thoughtstage.models import StrictModel
from thoughtstage.observer import read_run_bundle

_ANNOTATION_LOCK = threading.RLock()


class AnnotationTarget(StrEnum):
    POST = "post"
    STIMULUS = "stimulus"
    SOLILOQUY = "soliloquy"


class AnnotationError(ValueError):
    """Raised when researcher annotation data is invalid or unavailable."""


class AnnotationDraft(StrictModel):
    target_type: AnnotationTarget
    target_event_id: str = Field(min_length=1, max_length=256)
    note: str = Field(default="", max_length=5_000)
    tags: tuple[str, ...] = Field(default=(), max_length=16)
    bookmarked: bool = True

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 40 for item in normalized):
            raise ValueError("annotation tags must contain 1 to 40 characters")
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("annotation tags must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_content(self) -> AnnotationDraft:
        if not self.bookmarked and not self.note.strip() and not self.tags:
            raise ValueError("an annotation needs a bookmark, note, or tag")
        return self


class AnnotationUpdate(StrictModel):
    note: str = Field(default="", max_length=5_000)
    tags: tuple[str, ...] = Field(default=(), max_length=16)
    bookmarked: bool = True

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return AnnotationDraft.validate_tags(value)

    @model_validator(mode="after")
    def validate_content(self) -> AnnotationUpdate:
        if not self.bookmarked and not self.note.strip() and not self.tags:
            raise ValueError("an annotation needs a bookmark, note, or tag")
        return self


class ResearchAnnotation(StrictModel):
    schema_version: str = "0.1"
    annotation_id: str = Field(pattern=r"^annotation-[0-9a-f]{32}$")
    run_id: str
    target_type: AnnotationTarget
    target_event_id: str
    note: str
    tags: tuple[str, ...]
    bookmarked: bool
    created_at: str
    updated_at: str


def _annotations_path(root: Path) -> Path:
    return root / "private" / "annotations.json"


def _read_annotations(root: Path) -> list[ResearchAnnotation]:
    path = _annotations_path(root)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnnotationError("the researcher annotation store is invalid") from exc
    if not isinstance(raw, list):
        raise AnnotationError("the researcher annotation store has an invalid shape")
    try:
        return [ResearchAnnotation.model_validate(item) for item in raw]
    except ValueError as exc:
        raise AnnotationError("the researcher annotation store violates its schema") from exc


def _write_annotations(root: Path, annotations: list[ResearchAnnotation]) -> None:
    private = root / "private"
    private.mkdir(exist_ok=True)
    target = _annotations_path(root)
    temporary = private / ".annotations.json.tmp"
    temporary.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in annotations],
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(target)


def _target_exists(root: Path, target_type: AnnotationTarget, event_id: str) -> bool:
    detail = read_run_bundle(root.name, root=root.parent)
    if target_type is AnnotationTarget.SOLILOQUY:
        return any(item.get("event_id") == event_id for item in detail["soliloquies"])
    return any(
        item.get("event_id") == event_id and item.get("event_type") == target_type.value
        for item in detail["posts"]
    )


def list_annotations(root: Path) -> tuple[ResearchAnnotation, ...]:
    """Return researcher annotations in stable creation order."""

    with _ANNOTATION_LOCK:
        return tuple(_read_annotations(root))


def create_annotation(root: Path, draft: AnnotationDraft) -> ResearchAnnotation:
    """Create one researcher-only annotation after validating its typed target."""

    with _ANNOTATION_LOCK:
        if not _target_exists(root, draft.target_type, draft.target_event_id):
            raise AnnotationError("the annotation target does not exist in this run")
        annotations = _read_annotations(root)
        if any(
            item.target_type is draft.target_type and item.target_event_id == draft.target_event_id
            for item in annotations
        ):
            raise AnnotationError("this event already has an annotation")
        now = datetime.now(UTC).isoformat()
        annotation = ResearchAnnotation(
            annotation_id=f"annotation-{uuid.uuid4().hex}",
            run_id=root.name,
            target_type=draft.target_type,
            target_event_id=draft.target_event_id,
            note=draft.note.strip(),
            tags=draft.tags,
            bookmarked=draft.bookmarked,
            created_at=now,
            updated_at=now,
        )
        annotations.append(annotation)
        _write_annotations(root, annotations)
        return annotation


def update_annotation(
    root: Path,
    annotation_id: str,
    update: AnnotationUpdate,
) -> ResearchAnnotation:
    """Replace the editable fields of one existing annotation."""

    with _ANNOTATION_LOCK:
        annotations = _read_annotations(root)
        index = next(
            (
                position
                for position, item in enumerate(annotations)
                if item.annotation_id == annotation_id
            ),
            None,
        )
        if index is None:
            raise AnnotationError("the annotation was not found")
        current = annotations[index]
        changed = current.model_copy(
            update={
                "note": update.note.strip(),
                "tags": update.tags,
                "bookmarked": update.bookmarked,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        annotations[index] = changed
        _write_annotations(root, annotations)
        return changed


def delete_annotation(root: Path, annotation_id: str) -> None:
    """Delete one researcher annotation without touching the target run event."""

    with _ANNOTATION_LOCK:
        annotations = _read_annotations(root)
        remaining = [item for item in annotations if item.annotation_id != annotation_id]
        if len(remaining) == len(annotations):
            raise AnnotationError("the annotation was not found")
        _write_annotations(root, remaining)
