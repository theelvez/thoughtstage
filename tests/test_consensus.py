from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.consensus import analyze_consensus
from thoughtstage.engine import ExperimentEngine


def _post(
    sequence: int,
    round_number: int,
    agent_id: str,
    display_name: str,
    content: str,
) -> dict:
    return {
        "event_type": "post",
        "event_id": f"post-{sequence}",
        "sequence": sequence,
        "experiment_id": "alphabet",
        "round_number": round_number,
        "agent_id": agent_id,
        "display_name": display_name,
        "content": content,
    }


def test_consensus_timeline_detects_explicit_shift_and_convergence() -> None:
    posts = [
        _post(1, 1, "oak", "Oak", "I would remove Q because it is often replaceable."),
        _post(2, 1, "pine", "Pine", "I choose X because its function is narrow."),
        _post(3, 2, "oak", "Oak", "After considering the evidence, I now support X."),
        _post(4, 2, "pine", "Pine", "I still support X as the least disruptive choice."),
    ]

    result = analyze_consensus("alphabet-run", posts)

    assert result.heuristic is True
    assert result.final_classification == "consensus"
    assert result.rounds[0].classification == "divided"
    assert result.rounds[1].leading_stance == "X"
    assert result.rounds[1].explicit_agreement == 1.0
    oak_round_two = next(
        item for item in result.observations if item.agent_id == "oak" and item.round_number == 2
    )
    assert oak_round_two.transition == "possible_shift"
    assert oak_round_two.stance == "X"


def test_consensus_timeline_does_not_impute_indirect_positions() -> None:
    posts = [
        _post(1, 1, "oak", "Oak", "The evidence is incomplete and deserves more study."),
        _post(2, 1, "pine", "Pine", "Several tradeoffs remain unresolved."),
    ]

    result = analyze_consensus("indirect-run", posts)

    assert result.final_classification == "insufficient_signal"
    assert result.rounds[0].detected_stances == 0
    assert result.rounds[0].explicit_agreement is None
    assert all(item.transition == "undetermined" for item in result.observations)


def test_ranking_extraction_uses_declared_winner() -> None:
    posts = [
        _post(
            1,
            1,
            "judge",
            "Judge",
            "Final ranking: 1st place: A; 2nd place: B; 3rd place: C.",
        )
    ]

    result = analyze_consensus("ranking-run", posts)

    assert result.observations[0].stance == "A"
    assert result.observations[0].extraction_method == "ranking"


def test_consensus_api_is_read_only_and_public_only(
    loaded_experiment, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "runs"
    result = ExperimentEngine().run(
        loaded_experiment,
        output_root=root,
        run_id="consensus-api",
    )
    bundle = Path(result.bundle_path)
    public_before = (bundle / "public.jsonl").read_bytes()
    private_before = (bundle / "private" / "soliloquies.jsonl").read_bytes()
    monkeypatch.setenv("THOUGHTSTAGE_RUNS_DIR", str(root))

    response = TestClient(app).get("/api/runs/consensus-api/analysis/consensus")

    assert response.status_code == 200
    assert response.json()["heuristic"] is True
    assert "public posts" in response.json()["limitations"][-1]
    assert (bundle / "public.jsonl").read_bytes() == public_before
    assert (bundle / "private" / "soliloquies.jsonl").read_bytes() == private_before
