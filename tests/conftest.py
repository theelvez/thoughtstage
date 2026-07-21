from __future__ import annotations

from pathlib import Path

import pytest

from thoughtstage.config import LoadedExperiment, load_experiment


@pytest.fixture
def experiment_file(tmp_path: Path) -> Path:
    files = tmp_path / "files"
    files.mkdir()
    (files / "brief.txt").write_text("Evidence matters.\nTest the claim.\n", encoding="utf-8")
    manifest = tmp_path / "experiment.yaml"
    manifest.write_text(
        """\
schema_version: "0.1"
id: test-stage
name: Test Stage
system_prompt: |
  This prompt is identical for every participant.
rounds: 2
schedule: simultaneous
turn_order: declared
private_memory: none
seed: 17
files_dir: files
agents:
  - id: alpha
    display_name: Alpha
    persona_prompt: Be empirical.
    provider: mock
    model: deterministic-v1
    credential_env: TEST_PROVIDER_KEY
    temperature: 0
  - id: beta
    display_name: Beta
    persona_prompt: Be imaginative.
    provider: mock
    model: deterministic-v1
    temperature: 0
""",
        encoding="utf-8",
    )
    return manifest


@pytest.fixture
def loaded_experiment(experiment_file: Path) -> LoadedExperiment:
    return load_experiment(experiment_file)
