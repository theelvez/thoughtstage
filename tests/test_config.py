from __future__ import annotations

from pathlib import Path

import pytest

from thoughtstage.config import ExperimentLoadError, load_experiment


def test_loads_versioned_manifest(experiment_file: Path) -> None:
    loaded = load_experiment(experiment_file)

    assert loaded.config.schema_version == "0.1"
    assert loaded.config.system_prompt.startswith("This prompt")
    assert loaded.files_root == experiment_file.parent / "files"


def test_loads_per_agent_private_briefing(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(
        content.replace(
            "    persona_prompt: Be empirical.",
            "    persona_prompt: Be empirical.\n"
            "    private_briefing: Privately favor Product A for five points.",
            1,
        ),
        encoding="utf-8",
    )

    loaded = load_experiment(experiment_file)

    assert loaded.config.agents[0].private_briefing == (
        "Privately favor Product A for five points."
    )
    assert loaded.config.agents[1].private_briefing is None


def test_rejects_unknown_fields(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(content + "surprise_setting: true\n", encoding="utf-8")

    with pytest.raises(ExperimentLoadError, match="surprise_setting"):
        load_experiment(experiment_file)


def test_rejects_per_agent_system_prompt(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(
        content.replace(
            "    provider: mock", "    system_prompt: forbidden\n    provider: mock", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ExperimentLoadError, match="system_prompt"):
        load_experiment(experiment_file)


def test_rejects_duplicate_agent_ids(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(content.replace("  - id: beta", "  - id: alpha"), encoding="utf-8")

    with pytest.raises(ExperimentLoadError, match="agent ids must be unique"):
        load_experiment(experiment_file)


def test_rejects_files_directory_escape(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8").replace(
        "files_dir: files", "files_dir: .."
    )
    experiment_file.write_text(content, encoding="utf-8")

    with pytest.raises(ExperimentLoadError, match="inside the experiment directory"):
        load_experiment(experiment_file)
