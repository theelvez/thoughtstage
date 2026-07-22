from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.observer import RunBundleNotFoundError, list_run_bundles, read_run_bundle

client = TestClient(app)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_live_bundle(root: Path, run_id: str = "live-run") -> Path:
    bundle = root / run_id
    (bundle / "private").mkdir(parents=True)
    _write_json(
        bundle / "manifest.json",
        {
            "run_id": run_id,
            "status": "running",
            "created_at": "2026-07-21T12:00:00+00:00",
            "completed_at": None,
            "experiment": {
                "id": "observer-test",
                "name": "Observer Test",
                "system_prompt": "Reach one evidence-backed decision.",
            },
            "execution": {"rounds": 8, "schedule": "sequential"},
            "agents": [
                {
                    "id": "atlas",
                    "display_name": "Atlas",
                    "provider": "azure_foundry",
                    "model": "gpt-4o",
                }
            ],
            "counts": {"public_posts": 0, "soliloquies": 0},
        },
    )
    post = {
        "event_id": "post-r0001-atlas-000001",
        "sequence": 1,
        "experiment_id": "observer-test",
        "round_number": 1,
        "agent_id": "atlas",
        "display_name": "Atlas",
        "content": "A public proposal.",
    }
    soliloquy = {
        "event_id": "soliloquy-r0001-atlas-000001",
        "post_event_id": post["event_id"],
        "sequence": 1,
        "experiment_id": "observer-test",
        "round_number": 1,
        "agent_id": "atlas",
        "content": "A private reflection.",
    }
    (bundle / "public.jsonl").write_text(json.dumps(post) + "\n", encoding="utf-8")
    (bundle / "private" / "soliloquies.jsonl").write_text(
        json.dumps(soliloquy) + "\n{partial", encoding="utf-8"
    )
    _write_json(
        bundle / "private" / "agent_briefings.json",
        {"atlas": "Privately advocate Product A for five points."},
    )
    usage = {
        "event_id": "usage-r0001-atlas-000001-call01",
        "post_event_id": post["event_id"],
        "sequence": 1,
        "call_index": 1,
        "experiment_id": "observer-test",
        "round_number": 1,
        "agent_id": "atlas",
        "provider": "azure_foundry",
        "model": "gpt-4o",
        "phase": "combined",
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "cache_write_tokens": 0,
        "output_tokens": 30,
        "reasoning_tokens": 5,
        "total_tokens": 150,
        "response_id": "response-1",
    }
    (bundle / "private" / "model_usage.jsonl").write_text(
        json.dumps(usage) + "\n", encoding="utf-8"
    )
    return bundle


def test_list_run_bundles_uses_live_stream_counts(tmp_path: Path) -> None:
    _make_live_bundle(tmp_path)

    runs = list_run_bundles(root=tmp_path)

    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["counts"] == {
        "public_posts": 1,
        "soliloquies": 1,
        "model_calls": 1,
    }


def test_read_run_bundle_preserves_separate_streams(tmp_path: Path) -> None:
    _make_live_bundle(tmp_path)

    run = read_run_bundle("live-run", root=tmp_path)

    assert run["posts"][0]["content"] == "A public proposal."
    assert run["soliloquies"][0]["content"] == "A private reflection."
    assert "soliloquies" not in run["posts"][0]
    assert run["model_usage"][0]["response_id"] == "response-1"
    assert run["usage_summary"]["totals"]["model_calls"] == 1
    assert run["usage_summary"]["by_model"]["azure_foundry:gpt-4o"]["total_tokens"] == 150
    assert run["experiment"]["system_prompt"] == "Reach one evidence-backed decision."
    assert run["private_briefings"] == {"atlas": "Privately advocate Product A for five points."}


def test_run_id_cannot_traverse_outside_root(tmp_path: Path) -> None:
    with pytest.raises(RunBundleNotFoundError, match="invalid run id"):
        read_run_bundle("../elsewhere", root=tmp_path)


def test_observer_api_lists_and_reads_live_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_live_bundle(tmp_path)
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(tmp_path))

    listing = client.get("/api/runs")
    detail = client.get("/api/runs/live-run")

    assert listing.status_code == 200
    assert listing.json()["runs"][0]["counts"]["public_posts"] == 1
    assert detail.status_code == 200
    assert detail.json()["soliloquies"][0]["post_event_id"].startswith("post-")
    assert detail.json()["counts"]["model_calls"] == 1
    assert detail.json()["usage_summary"]["totals"]["input_tokens"] == 120


def test_observer_api_returns_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(tmp_path))

    response = client.get("/api/runs/missing")

    assert response.status_code == 404
