from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from thoughtstage.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_validate_command(experiment_file: Path) -> None:
    result = runner.invoke(app, ["validate", str(experiment_file)])

    assert result.exit_code == 0
    assert '"valid": true' in result.stdout
    assert '"agents": 2' in result.stdout


def test_run_command_writes_bundle(experiment_file: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            str(experiment_file),
            "--output",
            str(tmp_path / "runs"),
            "--run-id",
            "cli-run",
        ],
    )

    assert result.exit_code == 0
    assert '"run_id": "cli-run"' in result.stdout
    assert (tmp_path / "runs" / "cli-run" / "manifest.json").exists()

    usage_result = runner.invoke(app, ["usage", str(tmp_path / "runs" / "cli-run")])
    assert usage_result.exit_code == 0
    assert '"provider_reported": true' in usage_result.stdout
    assert '"model_calls": 0' in usage_result.stdout

    integrity_result = runner.invoke(
        app,
        ["integrity", str(tmp_path / "runs" / "cli-run")],
    )
    assert integrity_result.exit_code == 0
    assert '"boundary_valid": true' in integrity_result.stdout

    archive_path = tmp_path / "exports" / "cli-run.zip"
    export_result = runner.invoke(
        app,
        [
            "export-bundle",
            str(tmp_path / "runs" / "cli-run"),
            "--output",
            str(archive_path),
        ],
    )
    assert export_result.exit_code == 0
    assert archive_path.read_bytes().startswith(b"PK")


def test_validate_reports_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "invalid.yaml"
    manifest.write_text("not: an experiment\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", str(manifest)])

    assert result.exit_code == 1
    assert "Invalid experiment" in result.stderr
