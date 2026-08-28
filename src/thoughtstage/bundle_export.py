"""Create deterministic, self-verifying Thoughtstage reproducibility archives."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from thoughtstage.integrity import RunIntegrityReport, verify_run_bundle


class ReproducibilityExportError(ValueError):
    """Raised when a run cannot be exported as a trustworthy archive."""


def _readme(report: RunIntegrityReport) -> bytes:
    warnings = [item for item in report.checks if item.status.value == "warning"]
    warning_lines = (
        "\n".join(f"- `{item.code}`: {item.message}" for item in warnings)
        if warnings
        else "- None."
    )
    return (
        f"""# Thoughtstage reproducibility bundle

Run: `{report.run_id}`

This archive contains the exact persisted run artifacts, public and
researcher-private event streams, provider-reported usage records, input
metadata and available input snapshots, software provenance, and a deterministic
integrity report.

## Privacy

This is a **researcher-private archive**. It may contain agent briefings,
soliloquies, and private telemetry. Do not expose the archive to participating
agents or publish it without reviewing those materials.

## Verification

`checksums.sha256` covers every file in this archive except itself. Verify it
with a standard SHA-256 tool, then inspect `integrity-report.json`.

## Integrity warnings

{warning_lines}

External model services may change behind stable model identifiers. This bundle
supports exact replay of the observed record and an evidence-rich rerun; it
cannot guarantee byte-identical outputs from mutable providers.
"""
    ).encode()


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _checksum_manifest(payloads: dict[str, bytes]) -> bytes:
    lines = [
        f"{hashlib.sha256(payload).hexdigest()}  {path}"
        for path, payload in sorted(payloads.items())
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_reproducibility_archive(
    bundle_path: str | Path,
) -> tuple[bytes, RunIntegrityReport]:
    """Return a deterministic ZIP plus the report that authorized its export."""

    root = Path(bundle_path).resolve(strict=True)
    report = verify_run_bundle(root)
    if not report.valid:
        failed = [item.code for item in report.checks if item.status.value == "fail"]
        raise ReproducibilityExportError("run integrity verification failed: " + ", ".join(failed))
    if not report.complete:
        raise ReproducibilityExportError("only completed runs can be exported")

    payloads: dict[str, bytes] = {}
    for artifact in report.artifacts:
        candidate = root.joinpath(*Path(artifact.path).parts)
        payload = candidate.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.sha256 or len(payload) != artifact.size:
            raise ReproducibilityExportError(f"run artifact changed during export: {artifact.path}")
        payloads[artifact.path] = payload

    payloads["integrity-report.json"] = (
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    payloads["README.md"] = _readme(report)
    payloads["checksums.sha256"] = _checksum_manifest(payloads)

    prefix = f"thoughtstage-{report.run_id}"
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for path, payload in sorted(payloads.items()):
            archive.writestr(_zip_info(f"{prefix}/{path}"), payload)
    return output.getvalue(), report


def export_reproducibility_archive(
    bundle_path: str | Path,
    destination: str | Path,
) -> RunIntegrityReport:
    """Write a deterministic archive to an explicit researcher destination."""

    payload, report = build_reproducibility_archive(bundle_path)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return report
