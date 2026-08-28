from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from thoughtstage.bundle_export import (
    ReproducibilityExportError,
    build_reproducibility_archive,
    export_reproducibility_archive,
)
from thoughtstage.engine import ExperimentEngine


def _archive_files(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_reproducibility_archive_is_deterministic_complete_and_self_verifying(
    loaded_experiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="export-pass",
    )

    first, first_report = build_reproducibility_archive(result.bundle_path)
    second, second_report = build_reproducibility_archive(result.bundle_path)

    assert first == second
    assert first_report == second_report
    files = _archive_files(first)
    prefix = "thoughtstage-export-pass/"
    assert f"{prefix}manifest.json" in files
    assert f"{prefix}experiment.yaml" in files
    assert f"{prefix}public.jsonl" in files
    assert f"{prefix}private/soliloquies.jsonl" in files
    assert f"{prefix}private/model_usage.jsonl" not in files
    assert f"{prefix}inputs/files/brief.txt" in files
    assert f"{prefix}integrity-report.json" in files
    assert b"researcher-private archive" in files[f"{prefix}README.md"]

    checksum_lines = files[f"{prefix}checksums.sha256"].decode().splitlines()
    checksums = dict(line.split("  ", maxsplit=1) for line in checksum_lines)
    for relative, expected in checksums.items():
        assert hashlib.sha256(files[f"{prefix}{expected}"]).hexdigest() == relative


def test_export_writes_requested_archive(loaded_experiment, tmp_path: Path) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="export-write",
    )
    target = tmp_path / "exports" / "run.zip"

    report = export_reproducibility_archive(result.bundle_path, target)

    assert report.valid is True
    assert target.read_bytes().startswith(b"PK")


def test_export_refuses_tampered_bundle(loaded_experiment, tmp_path: Path) -> None:
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=tmp_path / "runs",
        run_id="export-tampered",
    )
    public_path = Path(result.bundle_path) / "public.jsonl"
    public_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ReproducibilityExportError, match="integrity verification failed"):
        build_reproducibility_archive(result.bundle_path)
