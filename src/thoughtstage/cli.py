"""Thoughtstage command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from thoughtstage import __version__
from thoughtstage.config import ExperimentLoadError, load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.observer import (
    RunBundleNotFoundError,
    RunBundleUnavailableError,
    read_run_bundle,
)
from thoughtstage.reproducibility import RunBundleResumeError

app = typer.Typer(
    name="thoughtstage",
    help="Run reproducible multi-agent social experiments.",
    no_args_is_help=True,
)


@app.command()
def validate(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate an experiment manifest without running it."""
    try:
        loaded = load_experiment(manifest)
    except ExperimentLoadError as exc:
        typer.echo(f"Invalid experiment: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "valid": True,
                "experiment": loaded.config.id,
                "agents": len(loaded.config.agents),
                "rounds": loaded.config.rounds,
                "schedule": loaded.config.schedule.value,
            },
            indent=2,
        )
    )


@app.command("run")
def run_experiment(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("runs"),
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Run an experiment and write a reproducibility bundle."""
    try:
        loaded = load_experiment(manifest)
    except ExperimentLoadError as exc:
        typer.echo(f"Invalid experiment: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    result = ExperimentEngine().run(loaded, output_root=output, run_id=run_id)
    typer.echo(
        json.dumps(
            {
                "run_id": result.run_id,
                "bundle": result.bundle_path,
                "public_posts": len(result.public_posts),
                "soliloquies": len(result.soliloquies),
                "model_calls": len(result.model_usage),
            },
            indent=2,
        )
    )


@app.command("resume")
def resume_experiment(
    bundle: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", exists=True, dir_okay=False, readable=True),
    ] = None,
) -> None:
    """Resume an interrupted run without repeating its completed event prefix."""

    source = manifest or bundle / "experiment.yaml"
    try:
        loaded = load_experiment(source)
        result = ExperimentEngine().run(loaded, resume_path=bundle)
    except (ExperimentLoadError, RunBundleResumeError) as exc:
        typer.echo(f"Cannot resume experiment: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "resumed": True,
                "run_id": result.run_id,
                "bundle": result.bundle_path,
                "public_posts": len(result.public_posts),
                "soliloquies": len(result.soliloquies),
                "model_calls": len(result.model_usage),
            },
            indent=2,
        )
    )


@app.command()
def usage(
    bundle: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Summarize provider-reported token usage for a run bundle."""

    resolved = bundle.resolve()
    try:
        detail = read_run_bundle(resolved.name, root=resolved.parent)
    except (RunBundleNotFoundError, RunBundleUnavailableError) as exc:
        typer.echo(f"Cannot read usage: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "run_id": detail["run_id"],
                "provider_reported": True,
                "usage": detail["usage_summary"],
            },
            indent=2,
        )
    )


@app.command("files-mcp")
def files_mcp(
    root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Start the read-only experiment file MCP over stdio."""
    from thoughtstage.mcp.files import run_server

    run_server(root)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "0.0.0.0",
    port: Annotated[int, typer.Option(min=1, max=65_535)] = 8000,
) -> None:
    """Serve the local research API."""
    import uvicorn

    uvicorn.run("thoughtstage.api:app", host=host, port=port)


@app.command()
def version() -> None:
    """Print the installed Thoughtstage version."""
    typer.echo(__version__)
