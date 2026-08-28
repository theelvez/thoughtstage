from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thoughtstage.cli import app
from thoughtstage.config import LoadedExperiment, load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelCallUsage,
    ModelOutput,
    ProviderResult,
    ScheduledStimulus,
)
from thoughtstage.reproducibility import RunBundleResumeError

runner = CliRunner()


class StopAfterOneProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated provider interruption")
        return ProviderResult(
            output=ModelOutput(
                post=f"original-public-{agent.id}",
                soliloquy=f"original-private-{agent.id}",
            ),
            usage=(
                ModelCallUsage(
                    phase="combined",
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                    response_id=f"original-{agent.id}",
                ),
            ),
        )


class ResumeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[AgentConfig, AgentTurnContext]] = []

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult:
        self.calls.append((agent, context))
        return ProviderResult(
            output=ModelOutput(
                post=f"resumed-public-{agent.id}",
                soliloquy=f"resumed-private-{agent.id}",
            ),
            usage=(
                ModelCallUsage(
                    phase="combined",
                    input_tokens=200,
                    output_tokens=20,
                    total_tokens=220,
                    response_id=f"resumed-{agent.id}",
                ),
            ),
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
    manifest_path = bundle / "manifest.json"
    interrupted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    interrupted_manifest["status"] = "failed"
    interrupted_manifest["failure"] = {"type": "RuntimeError", "message": "safe failure"}
    manifest_path.write_text(json.dumps(interrupted_manifest), encoding="utf-8")
    provider = ResumeProvider()

    result = ExperimentEngine({"mock": provider}).run(loaded, resume_path=bundle)

    assert [post.content for post in result.public_posts] == [
        "original-public-alpha",
        "resumed-public-beta",
    ]
    assert [agent.id for agent, _context in provider.calls] == ["beta"]
    assert len(provider.calls[0][1].public_feed) == 1
    assert len((bundle / "public.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert [item.total_tokens for item in result.model_usage] == [110, 220]
    assert (
        len((bundle / "private" / "model_usage.jsonl").read_text(encoding="utf-8").splitlines())
        == 2
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert "failure" not in manifest
    assert manifest["counts"]["model_calls"] == 2
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


def test_resume_repairs_single_trailing_partial_record(
    experiment_file: Path, tmp_path: Path
) -> None:
    loaded = _sequential_experiment(experiment_file)
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    public_path = bundle / "public.jsonl"
    with public_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write('{"partial"')

    ExperimentEngine({"mock": ResumeProvider()}).run(loaded, resume_path=bundle)

    lines = public_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_resume_rejects_terminated_invalid_json(experiment_file: Path, tmp_path: Path) -> None:
    loaded = _sequential_experiment(experiment_file)
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    public_path = bundle / "public.jsonl"
    with public_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("{invalid-json}\n")

    with pytest.raises(RunBundleResumeError, match="invalid JSON"):
        ExperimentEngine({"mock": ResumeProvider()}).run(loaded, resume_path=bundle)


def _with_round_one_stimulus(loaded: LoadedExperiment) -> LoadedExperiment:
    stimulus = ScheduledStimulus(
        id="developer-opening",
        round=1,
        source_id="developer",
        display_name="Developer Alex",
        content="Please review the code and state whether it is safe to approve.",
    )
    config = loaded.config.model_copy(update={"stimuli": (stimulus,)})
    return LoadedExperiment(
        config=config,
        source_path=loaded.source_path,
        source_bytes=json.dumps(config.model_dump(mode="json")).encode(),
        files_root=loaded.files_root,
    )


def test_resume_replays_scheduled_stimulus_without_regenerating_it(
    experiment_file: Path, tmp_path: Path
) -> None:
    loaded = _with_round_one_stimulus(_sequential_experiment(experiment_file))
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    manifest_path = bundle / "manifest.json"
    interrupted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    interrupted_manifest["status"] = "failed"
    interrupted_manifest["failure"] = {"type": "RuntimeError", "message": "safe failure"}
    manifest_path.write_text(json.dumps(interrupted_manifest), encoding="utf-8")
    provider = ResumeProvider()

    result = ExperimentEngine({"mock": provider}).run(loaded, resume_path=bundle)

    assert [stimulus.sequence for stimulus in result.public_stimuli] == [1]
    assert [post.sequence for post in result.public_posts] == [2, 3]
    assert [len(context.public_feed) for _agent, context in provider.calls] == [2]
    assert len((bundle / "public" / "stimuli.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_resume_rejects_tampered_public_stimulus(experiment_file: Path, tmp_path: Path) -> None:
    loaded = _with_round_one_stimulus(_sequential_experiment(experiment_file))
    bundle = _interrupted_bundle(loaded, tmp_path / "runs")
    stimulus_path = bundle / "public" / "stimuli.jsonl"
    event = json.loads(stimulus_path.read_text(encoding="utf-8"))
    event["content"] = "The recorded condition was changed after the interruption."
    stimulus_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(RunBundleResumeError, match="public stimulus prefix"):
        ExperimentEngine({"mock": ResumeProvider()}).run(loaded, resume_path=bundle)
