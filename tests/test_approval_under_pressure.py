from __future__ import annotations

from pathlib import Path

from thoughtstage.config import load_experiment

ROOT = Path(__file__).resolve().parents[1] / "examples" / "bedrock" / "approval-under-pressure"
MANIFESTS = {
    (code, treatment): ROOT / f"panel-{code}-{treatment}.yaml"
    for code in ("unsafe", "safe")
    for treatment in ("neutral", "pressure")
}


def _agent_contract(config) -> list[dict]:
    return [agent.model_dump(mode="json") for agent in config.agents]


def _word_count(value: str) -> int:
    return len(value.split())


def test_approval_pressure_pilot_is_a_controlled_two_by_two_matrix() -> None:
    configs = {cell: load_experiment(path).config for cell, path in MANIFESTS.items()}
    baseline = configs[("unsafe", "neutral")]

    assert {config.system_prompt for config in configs.values()} == {baseline.system_prompt}
    assert all(_agent_contract(config) == _agent_contract(baseline) for config in configs.values())
    assert all(config.rounds == 8 for config in configs.values())
    assert all(config.schedule.value == "simultaneous" for config in configs.values())
    assert all(config.private_memory.value == "own_history" for config in configs.values())
    assert all(len(config.stimuli) == 8 for config in configs.values())
    assert all(agent.private_briefing is None for agent in baseline.agents)

    for treatment in ("neutral", "pressure"):
        assert configs[("unsafe", treatment)].stimuli == configs[("safe", treatment)].stimuli

    neutral = configs[("unsafe", "neutral")].stimuli
    pressure = configs[("unsafe", "pressure")].stimuli
    assert neutral[0].content == pressure[0].content
    assert [item.round for item in neutral] == list(range(1, 9))
    assert [item.id for item in neutral] == [
        f"developer-r{round_number}" for round_number in range(1, 9)
    ]
    assert {item.source_id for item in neutral + pressure} == {"developer-alex"}
    for neutral_item, pressure_item in zip(neutral[1:], pressure[1:], strict=True):
        assert neutral_item.content != pressure_item.content
        ratio = _word_count(pressure_item.content) / _word_count(neutral_item.content)
        assert 0.7 <= ratio <= 1.3


def test_code_condition_files_have_the_same_declared_shape() -> None:
    unsafe = load_experiment(MANIFESTS[("unsafe", "neutral")])
    safe = load_experiment(MANIFESTS[("safe", "neutral")])

    assert unsafe.files_root is not None
    assert safe.files_root is not None
    assert {path.name for path in unsafe.files_root.iterdir()} == {
        "REVIEW_TARGET.md",
        "submission.py",
        "verification.txt",
    }
    assert {path.name for path in safe.files_root.iterdir()} == {
        "REVIEW_TARGET.md",
        "submission.py",
        "verification.txt",
    }
    assert (unsafe.files_root / "REVIEW_TARGET.md").read_bytes() == (
        safe.files_root / "REVIEW_TARGET.md"
    ).read_bytes()
    assert (unsafe.files_root / "submission.py").read_bytes() != (
        safe.files_root / "submission.py"
    ).read_bytes()
