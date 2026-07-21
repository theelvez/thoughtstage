from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thoughtstage.cli import app
from thoughtstage.config import LoadedExperiment, load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.models import AgentConfig, AgentTurnContext, ModelOutput
from thoughtstage.reproducibility import RunBundleResumeError

runner = CliRunner()


class StopAfterOneProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, agent: AgentConfig, context: AgentTurnContext, seed: int) -> ModelOutput:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated provider interruption")
        return ModelOutput(
            post=f"original-public-{agent.id}",
            soliloquy=f"original-private-{agent.id}",
        )


class ResumeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[AgentConfig, AgentTurnContext]] = []

    def generate(self, *, agent: AgentConfig, context: AgentTurnContext, seed: int) -> ModelOutput:
        self.calls.append((agent, context))
        return ModelOutput(
            post=f"resumed-public-{agent.id}",
            soliloquy=f"resumed-private-{agent.id}",
        )


def _sequential_experiment(experiment_file: Path) -> LoadedExperiment:
    source = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(
        source.replace("rounds: 2", "rounds: 1").replace(
            "schedule: simultaneous", "schedule: sequential"
        ),
        encoding="utf-8",
    )
    return load_experiment(experiment_file)


def _interrupted_bundle(loaded: LoadedExperiment, root: Path) -> Path:
    with pytest.raises(RuntimeError, match="simulated provider interruption"):
        ExperimentEngine({"mock": StopAfterOneProvider()}).run(
            loaded, output_root=root, run_id="interrupted"
        )
    return root / "interrupted"


def test_resume_replays_completed_turns_and_generates_only_the_missing_turn(
    experiment_file: Path, tmp_path: Path
) -> None:
    loaded = _sequential_experiment(experiment_file)
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    provider = ResumeProvider()

    result = ExperimentEngine({"mock": provider}).run(loaded, resume_path=bundle)

    assert [post.content for post in result.public_posts] == [
        "original-public-alpha",
        "resumed-public-beta",
    ]
    assert [agent.id for agent, _context in provider.calls] == ["beta"]
    assert len(provider.calls[0][1].public_feed) == 1
    assert len((bundle / "public.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert len(manifest["resumptions"]) == 1


def test_resume_rejects_an_event_prefix_that_does_not_match_the_manifest(
    experiment_file: Path, tmp_path: Path
) -> None:
    loaded = _sequential_experiment(experiment_file)
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    public_path = bundle / "public.jsonl"
    event = json.loads(public_path.read_text(encoding="utf-8"))
    event["agent_id"] = "beta"
    public_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(RunBundleResumeError, match="does not match"):
        ExperimentEngine({"mock": ResumeProvider()}).run(loaded, resume_path=bundle)


def test_completed_bundle_cannot_be_resumed(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment, output_root=tmp_path / "runs", run_id="completed"
    )

    with pytest.raises(RunBundleResumeError, match="already completed"):
        ExperimentEngine().run(loaded_experiment, resume_path=result.bundle_path)


def test_resume_cli_completes_an_interrupted_bundle(experiment_file: Path, tmp_path: Path) -> None:
    loaded = _sequential_experiment(experiment_file)
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")

    result = runner.invoke(
        app,
        ["resume", str(bundle), "--manifest", str(experiment_file)],
    )

    assert result.exit_code == 0
    assert '"resumed": true' in result.stdout
    assert len((bundle / "public.jsonl").read_text(encoding="utf-8").splitlines()) == 2
