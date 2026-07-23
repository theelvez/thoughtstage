from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.config import load_experiment


def _draft(experiment_id: str = "wizard-study") -> dict:
    return {
        "experiment": {
            "schema_version": "0.1",
            "id": experiment_id,
            "name": "Wizard Study",
            "description": "A generated experiment.",
            "system_prompt": "Reach one evidence-backed decision.",
            "rounds": 3,
            "schedule": "simultaneous",
            "turn_order": "declared",
            "private_memory": "none",
            "seed": 42,
            "files_dir": "files",
            "stimuli": [
                {
                    "id": "midpoint-check",
                    "round": 2,
                    "source_id": "researcher",
                    "display_name": "Research team",
                    "content": "State what evidence would change your position.",
                }
            ],
            "agents": [
                {
                    "id": "atlas",
                    "display_name": "Atlas",
                    "persona_prompt": "Prioritize falsifiable claims.",
                    "private_briefing": "Privately test the strongest counterargument.",
                    "provider": "azure_foundry",
                    "model": "gpt-4o",
                    "credential_env": "AZURE_FOUNDRY_API_KEY",
                    "temperature": 0.4,
                    "parameters": {
                        "endpoint_env": "AZURE_FOUNDRY_ENDPOINT",
                        "output_mode": "reflect_then_post",
                        "send_temperature": False,
                    },
                }
            ],
        },
        "materials": [
            {
                "path": "research-brief.md",
                "content": "# Research brief\n\nEvaluate the supplied evidence.",
            }
        ],
    }


def test_preview_compiles_readable_yaml_without_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path))
    response = TestClient(app).post("/api/experiments/preview", json=_draft())

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["artifacts"] == ["experiment.yaml", "files/research-brief.md"]
    rendered = yaml.safe_load(payload["yaml"])
    assert rendered["system_prompt"] == "Reach one evidence-backed decision."
    assert rendered["agents"][0]["credential_env"] == "AZURE_FOUNDRY_API_KEY"
    assert list(tmp_path.iterdir()) == []


def test_create_materializes_a_loadable_experiment_atomically(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_EXPERIMENTS_ROOT", str(tmp_path))
    client = TestClient(app)

    response = client.post("/api/experiments", json=_draft())

    assert response.status_code == 201
    experiment_root = tmp_path / "wizard-study"
    loaded = load_experiment(experiment_root / "experiment.yaml")
    assert loaded.config.agents[0].private_briefing == (
        "Privately test the strongest counterargument."
    )
    assert loaded.files_root == experiment_root / "files"
    assert (experiment_root / "files/research-brief.md").read_text(encoding="utf-8") == (
        "# Research brief\n\nEvaluate the supplied evidence."
    )
    assert not any(path.name.startswith(".wizard-study-") for path in tmp_path.iterdir())

    duplicate = client.post("/api/experiments", json=_draft())
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_material_paths_cannot_escape_the_experiment_root() -> None:
    draft = deepcopy(_draft())
    draft["materials"][0]["path"] = "../outside.txt"

    response = TestClient(app).post("/api/experiments/preview", json=draft)

    assert response.status_code == 422
    assert "remain inside" in response.text


def test_material_paths_reject_windows_incompatible_names() -> None:
    draft = deepcopy(_draft())
    draft["materials"][0]["path"] = "notes/CON.txt"

    response = TestClient(app).post("/api/experiments/preview", json=draft)

    assert response.status_code == 422
    assert "portable across Windows and Linux" in response.text


def test_wizard_requires_files_dir_to_match_generated_materials() -> None:
    draft = deepcopy(_draft())
    draft["experiment"]["files_dir"] = None

    response = TestClient(app).post("/api/experiments/preview", json=draft)

    assert response.status_code == 422
    assert "files_dir: files" in response.text
