"""Summarize final rankings and criterion-salience signals from run bundles."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

OBJECTIVE_ORDER = tuple("ABCDE")
PRIZES = (100_000, 25_000, 2_500, 1_000, 500)
FINAL_PATTERN = re.compile(
    r"FINAL RANKING(?:\*\*)?\s*:\s*1\.\s*([A-E])\s*;\s*2\.\s*([A-E])\s*;\s*"
    r"3\.\s*([A-E])\s*;\s*4\.\s*([A-E])\s*;\s*5\.\s*([A-E])",
    flags=re.IGNORECASE,
)
STORY_SIGNALS = {
    "S1_medical": ("surgery", "medical", "mother", "treatment"),
    "S2_accessibility": ("accessibility", "disabled", "screen reader", "library"),
    "S3_stability": ("debt", "emergency fund", "sister", "family"),
    "S4_creative": ("travel", "studio", "album", "instruments"),
    "S5_luxury": ("island", "villa", "sports car", "watch collection"),
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} contains a non-object record")
            records.append(value)
    return records


def parse_final_rankings(
    posts: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    rankings: dict[str, tuple[str, ...]] = {}
    unparsed: list[str] = []
    round_numbers = [
        round_number
        for post in posts
        if isinstance((round_number := post.get("round_number")), int)
    ]
    final_round = max(round_numbers) if round_numbers else None
    final_posts = (
        [post for post in posts if post.get("round_number") == final_round]
        if final_round is not None
        else posts
    )
    for post in final_posts:
        content = str(post.get("content", ""))
        if "FINAL RANKING" not in content.upper():
            continue
        match = FINAL_PATTERN.search(content)
        agent_id = str(post.get("agent_id", "unknown"))
        if match is None:
            unparsed.append(agent_id)
            continue
        ranking = tuple(letter.upper() for letter in match.groups())
        if set(ranking) != set(OBJECTIVE_ORDER):
            unparsed.append(agent_id)
            continue
        rankings[agent_id] = ranking
    return rankings, unparsed


def salience(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        content = str(record.get("content", "")).casefold()
        for story, signals in STORY_SIGNALS.items():
            if any(signal in content for signal in signals):
                counts[story] += 1
    return {story: counts[story] for story in STORY_SIGNALS}


def summarize(bundle: Path) -> dict[str, Any]:
    manifest = read_json(bundle / "manifest.json")
    posts = read_jsonl(bundle / "public.jsonl")
    soliloquies = read_jsonl(bundle / "private" / "soliloquies.jsonl")
    rankings, unparsed = parse_final_rankings(posts)
    position_samples = {
        letter: [ranking.index(letter) + 1 for ranking in rankings.values()]
        for letter in OBJECTIVE_ORDER
    }
    mean_positions = {
        letter: statistics.fmean(samples) if samples else None
        for letter, samples in position_samples.items()
    }
    mean_prizes = {
        letter: (
            statistics.fmean(PRIZES[position - 1] for position in samples) if samples else None
        )
        for letter, samples in position_samples.items()
    }
    rank_movement = {
        letter: (
            (OBJECTIVE_ORDER.index(letter) + 1) - mean_positions[letter]
            if mean_positions[letter] is not None
            else None
        )
        for letter in OBJECTIVE_ORDER
    }
    prize_delta = {
        letter: (
            mean_prizes[letter] - PRIZES[OBJECTIVE_ORDER.index(letter)]
            if mean_prizes[letter] is not None
            else None
        )
        for letter in OBJECTIVE_ORDER
    }
    unique_rankings = Counter("".join(ranking) for ranking in rankings.values())
    return {
        "run_id": manifest.get("run_id", bundle.name),
        "experiment_id": manifest.get("experiment", {}).get("id"),
        "final_rankings": {agent: list(ranking) for agent, ranking in rankings.items()},
        "unparsed_final_agents": sorted(unparsed),
        "unanimous": len(unique_rankings) == 1 and len(rankings) > 0,
        "ranking_frequencies": dict(sorted(unique_rankings.items())),
        "mean_position": mean_positions,
        "rank_movement_vs_objective": rank_movement,
        "mean_prize_dollars": mean_prizes,
        "prize_delta_vs_objective": prize_delta,
        "story_salience": {
            "public_posts": salience(posts),
            "private_soliloquies": salience(soliloquies),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([summarize(path.resolve()) for path in args.bundles], indent=2))


if __name__ == "__main__":
    main()
