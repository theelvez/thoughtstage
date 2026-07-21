from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoughtstage.config import LoadedExperiment
from thoughtstage.engine import ExperimentEngine, UnknownProviderError
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelOutput,
    PrivateMemory,
    Schedule,
    TurnOrder,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[AgentConfig, AgentTurnContext]] = []

    def generate(self, *, agent: AgentConfig, context: AgentTurnContext, seed: int) -> ModelOutput:
        self.calls.append((agent, context))
        return ModelOutput(
            post=f"public-{agent.id}-r{context.round_number}",
            soliloquy=f"private-{agent.id}-r{context.round_number}",
        )


def test_simultaneous_visibility_boundary(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    recorder = RecordingProvider()
    engine = ExperimentEngine({"mock": recorder})

    result = engine.run(loaded_experiment, output_root=tmp_path / "runs", run_id="boundary")

    assert len(result.public_posts) == 4
    assert len(result.soliloquies) == 4
    assert [len(context.public_feed) for _agent, context in recorder.calls] == [0, 0, 2, 2]
    assert all(context.own_soliloquies == () for _agent, context in recorder.calls)
    assert {context.system_prompt for _agent, context in recorder.calls} == {
        loaded_experiment.config.system_prompt
    }
    for _agent, context in recorder.calls:
        serialized = context.model_dump_json()
        assert "private-alpha" not in serialized
        assert "private-beta" not in serialized
        assert "deterministic-v1" not in serialized
        assert "TEST_PROVIDER_KEY" not in serialized


def test_private_and_public_streams_are_separate(
    loaded_experiment: LoadedExperiment, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "this-secret-must-not-be-written")
    result = ExperimentEngine().run(
        loaded_experiment, output_root=tmp_path / "runs", run_id="separate"
    )
    bundle = Path(result.bundle_path)
    public_text = (bundle / "public.jsonl").read_text(encoding="utf-8")
    private_text = (bundle / "private" / "soliloquies.jsonl").read_text(encoding="utf-8")
    manifest_text = (bundle / "manifest.json").read_text(encoding="utf-8")

    assert "soliloquy" not in public_text.casefold()
    assert "I want" in private_text
    assert "this-secret-must-not-be-written" not in manifest_text
    assert "TEST_PROVIDER_KEY" in manifest_text
    assert json.loads(manifest_text)["status"] == "completed"


def test_mock_provider_is_deterministic(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    engine = ExperimentEngine()
    first = engine.run(loaded_experiment, output_root=tmp_path / "one", run_id="same")
    second = engine.run(loaded_experiment, output_root=tmp_path / "two", run_id="same")

    first_path = Path(first.bundle_path)
    second_path = Path(second.bundle_path)
    assert (first_path / "public.jsonl").read_bytes() == (second_path / "public.jsonl").read_bytes()
    assert (first_path / "private" / "soliloquies.jsonl").read_bytes() == (
        second_path / "private" / "soliloquies.jsonl"
    ).read_bytes()


def test_sequential_mode_sees_earlier_same_round(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    recorder = RecordingProvider()
    sequential_config = loaded_experiment.config.model_copy(
        update={"rounds": 1, "schedule": Schedule.SEQUENTIAL}
    )
    loaded = LoadedExperiment(
        config=sequential_config,
        source_path=loaded_experiment.source_path,
        source_bytes=loaded_experiment.source_bytes,
        files_root=loaded_experiment.files_root,
    )

    ExperimentEngine({"mock": recorder}).run(
        loaded, output_root=tmp_path / "runs", run_id="sequential"
    )

    assert [len(context.public_feed) for _agent, context in recorder.calls] == [0, 1]


def test_agent_can_receive_only_its_own_private_history(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    recorder = RecordingProvider()
    memory_config = loaded_experiment.config.model_copy(
        update={"private_memory": PrivateMemory.OWN_HISTORY}
    )
    loaded = LoadedExperiment(
        config=memory_config,
        source_path=loaded_experiment.source_path,
        source_bytes=loaded_experiment.source_bytes,
        files_root=loaded_experiment.files_root,
    )

    ExperimentEngine({"mock": recorder}).run(
        loaded, output_root=tmp_path / "runs", run_id="own-history"
    )

    assert [len(context.own_soliloquies) for _agent, context in recorder.calls] == [0, 0, 1, 1]
    assert recorder.calls[2][1].own_soliloquies == ("private-alpha-r1",)
    assert recorder.calls[3][1].own_soliloquies == ("private-beta-r1",)


def test_seeded_random_order_is_repeatable(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    config = loaded_experiment.config.model_copy(update={"turn_order": TurnOrder.SEEDED_RANDOM})
    loaded = LoadedExperiment(
        config=config,
        source_path=loaded_experiment.source_path,
        source_bytes=loaded_experiment.source_bytes,
        files_root=loaded_experiment.files_root,
    )
    first = RecordingProvider()
    second = RecordingProvider()

    ExperimentEngine({"mock": first}).run(loaded, output_root=tmp_path / "one", run_id="random")
    ExperimentEngine({"mock": second}).run(loaded, output_root=tmp_path / "two", run_id="random")

    assert [agent.id for agent, _context in first.calls] == [
        agent.id for agent, _context in second.calls
    ]


def test_unknown_provider_fails_explicitly(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    agent = loaded_experiment.config.agents[0].model_copy(update={"provider": "missing"})
    config = loaded_experiment.config.model_copy(update={"agents": (agent,)})
    loaded = LoadedExperiment(
        config=config,
        source_path=loaded_experiment.source_path,
        source_bytes=loaded_experiment.source_bytes,
        files_root=loaded_experiment.files_root,
    )

    with pytest.raises(UnknownProviderError, match="missing"):
        ExperimentEngine().run(loaded, output_root=tmp_path / "runs", run_id="missing")
