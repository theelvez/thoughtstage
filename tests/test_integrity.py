from __future__ import annotations

import json
from pathlib import Path

from thoughtstage.engine import ExperimentEngine
from thoughtstage.integrity import IntegrityStatus, verify_run_bundle


def _check(report, code: str):
    return next(item for item in report.checks if item.code == code)


def test_completed_bundle_passes_integrity_and_snapshots_inputs(
    loaded_experiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="integrity-pass",
    )
    bundle = Path(result.bundle_path)

    report = verify_run_bundle(bundle)

    assert report.valid is True
    assert report.complete is True
    assert report.boundary_valid is True
    assert all(item.status is IntegrityStatus.PASS for item in report.checks)
    assert (bundle / "inputs" / "files" / "brief.txt").read_text(encoding="utf-8") == (
        "Evidence matters.\nTest the claim.\n"
    )
    assert _check(report, "input-file-snapshots").evidence == {
        "declared": 1,
        "snapshotted": 1,
        "mismatches": [],
    }


def test_integrity_rejects_private_metadata_in_public_stream(
    loaded_experiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="integrity-public-leak",
    )
    bundle = Path(result.bundle_path)
    public_path = bundle / "public.jsonl"
    records = [json.loads(line) for line in public_path.read_text(encoding="utf-8").splitlines()]
    records[0]["provider"] = "must-not-be-public"
    public_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    report = verify_run_bundle(bundle)

    assert report.valid is False
    assert report.boundary_valid is False
    assert _check(report, "public-post-schema").status is IntegrityStatus.FAIL


def test_integrity_rejects_mismatched_public_private_pairing(
    loaded_experiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="integrity-pairing",
    )
    bundle = Path(result.bundle_path)
    private_path = bundle / "private" / "soliloquies.jsonl"
    records = [json.loads(line) for line in private_path.read_text(encoding="utf-8").splitlines()]
    records[0]["post_event_id"] = "post-does-not-exist"
    private_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    report = verify_run_bundle(bundle)

    assert report.valid is False
    assert report.boundary_valid is False
    assert _check(report, "public-private-pairing").status is IntegrityStatus.FAIL


def test_integrity_detects_manifest_and_input_tampering(loaded_experiment, tmp_path: Path) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="integrity-tamper",
    )
    bundle = Path(result.bundle_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["public_posts"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "inputs" / "files" / "brief.txt").write_text(
        "Changed after the run.\n",
        encoding="utf-8",
    )

    report = verify_run_bundle(bundle)

    assert report.valid is False
    assert _check(report, "manifest-counts").status is IntegrityStatus.FAIL
    assert _check(report, "input-file-snapshots").status is IntegrityStatus.FAIL


def test_legacy_bundle_without_input_snapshot_is_valid_with_warning(
    loaded_experiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="integrity-legacy",
    )
    bundle = Path(result.bundle_path)
    snapshot = bundle / "inputs" / "files" / "brief.txt"
    snapshot.unlink()
    snapshot.parent.rmdir()
    snapshot.parent.parent.rmdir()

    report = verify_run_bundle(bundle)

    assert report.valid is True
    assert report.complete is True
    assert _check(report, "input-file-snapshots").status is IntegrityStatus.WARNING
