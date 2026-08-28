from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from thoughtstage.config import load_experiment
from thoughtstage.files import ExperimentFileReader

ROOT = Path(__file__).resolve().parents[1] / "examples" / "bedrock" / "stories-before-scores"
STORY_SIGNATURES = {
    "S1": "mother's scheduled heart surgery",
    "S2": "volunteer-built accessibility lab",
    "S3": "education and housing debt",
    "S4": "long international trip",
    "S5": "private island resort",
}


def _analysis_module():
    module_path = ROOT / "research" / "analyze_runs.py"
    spec = importlib.util.spec_from_file_location("stories_before_scores_analysis", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _story_mapping(prompt: str) -> dict[str, str]:
    blocks = re.findall(
        r"Submission ([A-E]): (.*?)(?=\n\nSubmission [A-E]:|\n\nUse the experiment)",
        prompt,
        flags=re.DOTALL,
    )
    mapping: dict[str, str] = {}
    for submission, story in blocks:
        normalized_story = " ".join(story.split())
        matches = [
            story_id
            for story_id, signature in STORY_SIGNATURES.items()
            if signature in normalized_story
        ]
        assert len(matches) == 1
        mapping[submission] = matches[0]
    return mapping


def test_story_conditions_form_declared_latin_square() -> None:
    paths = [ROOT / "counterbalance-1-reverse.yaml"] + [
        ROOT / f"counterbalance-{index}.yaml" for index in range(2, 6)
    ]
    mappings = [_story_mapping(load_experiment(path).config.system_prompt) for path in paths]

    assert mappings[0] == {"A": "S5", "B": "S4", "C": "S3", "D": "S2", "E": "S1"}
    assert all(set(mapping) == set("ABCDE") for mapping in mappings)
    assert all(set(mapping.values()) == set(STORY_SIGNATURES) for mapping in mappings)
    for submission in "ABCDE":
        assert {mapping[submission] for mapping in mappings} == set(STORY_SIGNATURES)


def test_all_conditions_use_same_panel_and_confined_technical_files() -> None:
    paths = [ROOT / "blind.yaml", ROOT / "counterbalance-1-reverse.yaml"] + [
        ROOT / f"counterbalance-{index}.yaml" for index in range(2, 6)
    ]
    loaded = [load_experiment(path) for path in paths]
    panel = tuple(agent.model_dump() for agent in loaded[0].config.agents)

    assert all(
        tuple(agent.model_dump() for agent in item.config.agents) == panel for item in loaded
    )
    assert all(item.config.schedule.value == "simultaneous" for item in loaded)
    assert all(item.config.rounds == 8 for item in loaded)
    assert "mother's scheduled heart surgery" not in loaded[0].config.system_prompt

    reader = ExperimentFileReader(loaded[0].files_root)
    visible_paths = {item["path"] for item in reader.list_files()}
    assert "SPEC.md" in visible_paths
    assert "validation-report.md" in visible_paths
    assert {f"submissions/{letter}.py" for letter in "abcde"} <= visible_paths
    assert not any(path.startswith("research/") for path in visible_paths)


def test_final_ranking_parser_accepts_plain_and_markdown_labels() -> None:
    analysis = _analysis_module()
    posts = [
        {
            "agent_id": "plain",
            "round_number": 8,
            "content": "FINAL RANKING: 1. A; 2. B; 3. C; 4. D; 5. E",
        },
        {
            "agent_id": "markdown",
            "round_number": 7,
            "content": "FINAL RANKING appears in the instructions but is not an answer",
        },
        {
            "agent_id": "markdown",
            "round_number": 8,
            "content": "**FINAL RANKING**: 1. A; 2. B; 3. C; 4. D; 5. E",
        },
    ]

    rankings, unparsed = analysis.parse_final_rankings(posts)

    assert rankings == {
        "plain": tuple("ABCDE"),
        "markdown": tuple("ABCDE"),
    }
    assert unparsed == []
