from __future__ import annotations

from pathlib import Path

from thoughtstage.config import load_experiment

ROOT = Path(__file__).parents[1] / "examples" / "bedrock" / "approval-under-pressure"
SOLO = ROOT
MODEL_AGENTS = {
    "nova2": "alder",
    "llama-scout": "birch",
    "llama-maverick": "cedar",
    "mistral-large": "elm",
}
CODE_STATES = ("safe", "unsafe")
TREATMENTS = ("neutral", "pressure")


def _load_solo() -> dict[tuple[str, str, str], object]:
    return {
        (model, code_state, treatment): load_experiment(
            SOLO / f"solo-{model}-{code_state}-{treatment}.yaml"
        )
        for model in MODEL_AGENTS
        for code_state in CODE_STATES
        for treatment in TREATMENTS
    }


def test_solo_follow_up_is_controlled_four_by_two_by_two() -> None:
    loaded = _load_solo()
    assert len(loaded) == 16
    assert len(list(SOLO.glob("solo-*.yaml"))) == 16

    prompts = {item.config.system_prompt for item in loaded.values()}
    assert len(prompts) == 1
    prompt = prompts.pop()
    assert "sole senior security reviewer" in prompt
    assert "No peer reviewers participate" in prompt
    assert "panel" not in prompt.lower()
    assert "DECISION: <APPROVE or REJECT>" in prompt
    assert "SECURITY FINDING: <NONE or BLOCKING>" in prompt

    panel = load_experiment(ROOT / "panel-safe-neutral.yaml").config
    panel_agents = {agent.id: agent for agent in panel.agents}
    for (model, code_state, treatment), item in loaded.items():
        config = item.config
        assert config.id == f"approval-pressure-solo-{model}-{code_state}-{treatment}"
        assert config.rounds == 8
        assert config.schedule == "simultaneous"
        assert config.turn_order == "seeded_random"
        assert config.private_memory == "own_history"
        assert config.seed == 20260722
        assert item.files_root.name == code_state
        assert len(config.agents) == 1
        agent = config.agents[0]
        expected = panel_agents[MODEL_AGENTS[model]]
        assert agent.id == expected.id
        assert agent.provider == expected.provider
        assert agent.model == expected.model
        assert agent.credential_env == expected.credential_env
        assert agent.temperature == expected.temperature
        assert agent.parameters == expected.parameters
        assert "another reviewer" not in agent.persona_prompt
        assert [stimulus.round for stimulus in config.stimuli] == list(range(1, 9))
        assert all("panel" not in stimulus.content.lower() for stimulus in config.stimuli)

    for model in MODEL_AGENTS:
        for treatment in TREATMENTS:
            safe = loaded[(model, "safe", treatment)].config
            unsafe = loaded[(model, "unsafe", treatment)].config
            assert [item.content for item in safe.stimuli] == [
                item.content for item in unsafe.stimuli
            ]

        neutral = loaded[(model, "safe", "neutral")].config
        pressure = loaded[(model, "safe", "pressure")].config
        assert neutral.stimuli[0].content == pressure.stimuli[0].content
        assert all(
            neutral.stimuli[index].content != pressure.stimuli[index].content
            for index in range(1, 8)
        )

    reference = loaded[("nova2", "safe", "neutral")].config
    for model in MODEL_AGENTS:
        candidate = loaded[(model, "safe", "neutral")].config
        assert [item.content for item in candidate.stimuli] == [
            item.content for item in reference.stimuli
        ]
