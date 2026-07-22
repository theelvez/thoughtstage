from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from thoughtstage.config import LoadedExperiment
from thoughtstage.engine import ExperimentEngine, UnknownProviderError
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelCallUsage,
    ModelOutput,
    PrivateMemory,
    ProviderResult,
    Schedule,
    TurnOrder,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[AgentConfig, AgentTurnContext]] = []

    def generate(
        self, *, agent: AgentConfig, context: AgentTurnContext, seed: int
    ) -> ProviderResult:
        self.calls.append((agent, context))
        return ProviderResult(
            output=ModelOutput(
                post=f"public-{agent.id}-r{context.round_number}",
                soliloquy=f"private-{agent.id}-r{context.round_number}",
            )
        )


class UsageProvider:
    def generate(
        self, *, agent: AgentConfig, context: AgentTurnContext, seed: int
    ) -> ProviderResult:
        return ProviderResult(
            output=ModelOutput(
                post=f"public-{agent.id}-r{context.round_number}",
                soliloquy=f"private-{agent.id}-r{context.round_number}",
            ),
            usage=(
                ModelCallUsage(
                    phase="combined",
                    input_tokens=100,
                    cached_input_tokens=25,
                    output_tokens=20,
                    reasoning_tokens=5,
                    total_tokens=120,
                    response_id=f"response-{agent.id}-{context.round_number}",
                ),
            ),
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


def test_private_briefing_is_visible_only_to_assigned_agent_and_researcher(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    secret_briefing = "Promote Product A; a successful placement earns five points."
    agents = tuple(
        agent.model_copy(
            update={"private_briefing": secret_briefing if agent.id == "alpha" else None}
        )
        for agent in loaded_experiment.config.agents
    )
    config = loaded_experiment.config.model_copy(update={"agents": agents})
    source_bytes = json.dumps(config.model_dump(mode="json")).encode()
    loaded = LoadedExperiment(
        config=config,
        source_path=loaded_experiment.source_path,
        source_bytes=source_bytes,
        files_root=loaded_experiment.files_root,
    )
    recorder = RecordingProvider()

    result = ExperimentEngine({"mock": recorder}).run(
        loaded, output_root=tmp_path / "runs", run_id="private-briefing"
    )

    alpha_contexts = [context for agent, context in recorder.calls if agent.id == "alpha"]
    beta_contexts = [context for agent, context in recorder.calls if agent.id == "beta"]
    assert all(context.private_briefing == secret_briefing for context in alpha_contexts)
    assert all(context.private_briefing is None for context in beta_contexts)
    assert all(secret_briefing not in context.model_dump_json() for context in beta_contexts)

    bundle = Path(result.bundle_path)
    public_text = (bundle / "public.jsonl").read_text(encoding="utf-8")
    soliloquy_text = (bundle / "private" / "soliloquies.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    briefings = json.loads(
        (bundle / "private" / "agent_briefings.json").read_text(encoding="utf-8")
    )

    assert secret_briefing not in public_text
    assert secret_briefing not in soliloquy_text
    assert secret_briefing not in json.dumps(manifest)
    assert briefings == {"alpha": secret_briefing}
    assert manifest["inputs"]["private_briefings"] == [
        {
            "agent_id": "alpha",
            "sha256": hashlib.sha256(secret_briefing.encode()).hexdigest(),
        }
    ]


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


def test_provider_usage_is_persisted_only_in_the_researcher_channel(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    result = ExperimentEngine({"mock": UsageProvider()}).run(
        loaded_experiment, output_root=tmp_path / "runs", run_id="usage-ledger"
    )
    bundle = Path(result.bundle_path)
    usage_path = bundle / "private" / "model_usage.jsonl"
    usage_records = [json.loads(line) for line in usage_path.read_text().splitlines()]

    assert len(result.model_usage) == 4
    assert len(usage_records) == 4
    assert {item["phase"] for item in usage_records} == {"combined"}
    assert all(item["post_event_id"].startswith("post-") for item in usage_records)
    assert "input_tokens" not in (bundle / "public.jsonl").read_text(encoding="utf-8")
    assert "input_tokens" not in (bundle / "private" / "soliloquies.jsonl").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["model_calls"] == 4


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
