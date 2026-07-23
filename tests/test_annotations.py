from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thoughtstage.annotations import (
    AnnotationDraft,
    AnnotationError,
    AnnotationTarget,
    AnnotationUpdate,
    create_annotation,
    delete_annotation,
    list_annotations,
    update_annotation,
)
from thoughtstage.api import app
from thoughtstage.engine import ExperimentEngine
from thoughtstage.integrity import IntegrityStatus, verify_run_bundle


def _run(loaded_experiment, tmp_path: Path, run_id: str = "annotation-run") -> Path:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id=run_id,
    )
    return Path(result.bundle_path)


def _first_event(bundle: Path, stream: str) -> dict:
    path = bundle / stream
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def test_annotations_are_typed_researcher_only_and_integrity_checked(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _run(loaded_experiment, tmp_path)
    post = _first_event(bundle, "public.jsonl")
    secret_note = "This shift may be the decisive qualitative moment."
    original_public = (bundle / "public.jsonl").read_bytes()
    original_private = (bundle / "private" / "soliloquies.jsonl").read_bytes()

    annotation = create_annotation(
        bundle,
        AnnotationDraft(
            target_type=AnnotationTarget.POST,
            target_event_id=post["event_id"],
            note=secret_note,
            tags=("position-shift", "review"),
            bookmarked=True,
        ),
    )

    assert annotation.target_event_id == post["event_id"]
    assert list_annotations(bundle) == (annotation,)
    assert (bundle / "public.jsonl").read_bytes() == original_public
    assert (bundle / "private" / "soliloquies.jsonl").read_bytes() == original_private
    assert secret_note not in original_public.decode()
    assert secret_note not in original_private.decode()
    assert secret_note in (bundle / "private" / "annotations.json").read_text(encoding="utf-8")
    report = verify_run_bundle(bundle)
    check = next(item for item in report.checks if item.code == "private-annotation-schema")
    assert report.valid is True
    assert check.status is IntegrityStatus.PASS


def test_annotation_update_delete_and_duplicate_protection(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _run(loaded_experiment, tmp_path)
    soliloquy = _first_event(bundle, "private/soliloquies.jsonl")
    draft = AnnotationDraft(
        target_type=AnnotationTarget.SOLILOQUY,
        target_event_id=soliloquy["event_id"],
    )
    created = create_annotation(bundle, draft)

    with pytest.raises(AnnotationError, match="already has"):
        create_annotation(bundle, draft)

    updated = update_annotation(
        bundle,
        created.annotation_id,
        AnnotationUpdate(
            note="Revisit during coding.",
            tags=("candidate-theme",),
            bookmarked=False,
        ),
    )
    assert updated.note == "Revisit during coding."
    assert updated.bookmarked is False
    assert updated.created_at == created.created_at

    delete_annotation(bundle, created.annotation_id)
    assert list_annotations(bundle) == ()


def test_annotation_rejects_cross_run_or_wrong_channel_target(
    loaded_experiment, tmp_path: Path
) -> None:
    bundle = _run(loaded_experiment, tmp_path)
    post = _first_event(bundle, "public.jsonl")

    with pytest.raises(AnnotationError, match="does not exist"):
        create_annotation(
            bundle,
            AnnotationDraft(
                target_type=AnnotationTarget.SOLILOQUY,
                target_event_id=post["event_id"],
            ),
        )


def test_annotation_api_round_trip(loaded_experiment, tmp_path: Path, monkeypatch) -> None:
    bundle = _run(loaded_experiment, tmp_path, run_id="annotation-api")
    post = _first_event(bundle, "public.jsonl")
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(bundle.parent))
    client = TestClient(app)

    created = client.post(
        "/api/runs/annotation-api/annotations",
        json={
            "target_type": "post",
            "target_event_id": post["event_id"],
            "note": "Opening position.",
            "tags": ["opening"],
            "bookmarked": True,
        },
    )
    listed = client.get("/api/runs/annotation-api/annotations")
    annotation_id = created.json()["annotation_id"]
    updated = client.put(
        f"/api/runs/annotation-api/annotations/{annotation_id}",
        json={"note": "Updated note.", "tags": [], "bookmarked": True},
    )
    deleted = client.delete(f"/api/runs/annotation-api/annotations/{annotation_id}")

    assert created.status_code == 201
    assert listed.json()["annotations"][0]["note"] == "Opening position."
    assert updated.json()["note"] == "Updated note."
    assert deleted.status_code == 204
    assert client.get("/api/runs/annotation-api/annotations").json()["annotations"] == []
