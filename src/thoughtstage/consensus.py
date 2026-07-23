"""Deterministic, explicitly heuristic stance and consensus analysis."""

from __future__ import annotations

import itertools
import re
from collections import Counter
from typing import Any, Literal

from pydantic import Field

from thoughtstage.models import StrictModel

_RANKING_PATTERN = re.compile(
    r"(?:\b1(?:st)?\s+place\b|\btop\s+choice\b|\bwinner\b)"
    r"\s*(?:is|[:=.-])?\s*[\"']?(?P<label>[A-Za-z0-9][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_CHOICE_PATTERN = re.compile(
    r"\b(?:i\s+)?(?:would\s+|now\s+)?"
    r"(?P<verb>choose|select|vote\s+for|support|prefer|recommend|remove)"
    r"\s+(?:the\s+)?(?:letter\s+|option\s+|submission\s+|candidate\s+)?"
    r"[\"']?(?P<label>[A-Za-z0-9][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "before",
    "being",
    "between",
    "could",
    "does",
    "from",
    "have",
    "into",
    "more",
    "most",
    "only",
    "other",
    "should",
    "some",
    "such",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
}


class StanceObservation(StrictModel):
    event_id: str
    agent_id: str
    display_name: str
    round_number: int
    sequence: int
    stance: str | None
    extraction_method: Literal["ranking", "choice_statement", "none"]
    extraction_confidence: float = Field(ge=0, le=1)
    transition: Literal["initial", "unchanged", "possible_shift", "undetermined"]
    excerpt: str


class RoundConsensus(StrictModel):
    round_number: int
    participants: int
    detected_stances: int
    stance_coverage: float = Field(ge=0, le=1)
    leading_stance: str | None
    explicit_agreement: float | None = Field(default=None, ge=0, le=1)
    lexical_alignment: float = Field(ge=0, le=1)
    classification: Literal["consensus", "leaning", "divided", "insufficient_signal"]
    stance_counts: dict[str, int]


class ConsensusTimeline(StrictModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    heuristic: Literal[True] = True
    method: str = (
        "Deterministic explicit-choice extraction plus public-post lexical overlap; "
        "no model judge is used."
    )
    limitations: tuple[str, ...] = (
        "A detected phrase is not proof of the participant's complete position.",
        "Missing or indirect stances reduce coverage and are never imputed.",
        "Lexical similarity can reflect shared vocabulary without genuine agreement.",
        "Possible shifts are descriptive cues for researcher review, not ground truth.",
        "Only public posts are analyzed; soliloquies remain a separate research channel.",
    )
    observations: tuple[StanceObservation, ...]
    rounds: tuple[RoundConsensus, ...]
    final_classification: str


def _canonical(label: str) -> str:
    stripped = label.strip(" \t\r\n.,;:!?()[]{}\"'")
    return stripped.upper() if len(stripped) == 1 else stripped.casefold()


def _excerpt(content: str, match: re.Match[str] | None) -> str:
    if match is None:
        return content.strip().replace("\n", " ")[:240]
    for sentence in _SENTENCE_SPLIT.split(content):
        if match.group(0) in sentence:
            return sentence.strip()[:240]
    return content[max(0, match.start() - 80) : match.end() + 120].strip()[:240]


def _extract(content: str) -> tuple[str | None, str, float, str]:
    ranking = _RANKING_PATTERN.search(content)
    if ranking is not None:
        label = ranking.group("label")
        return label, "ranking", 0.95, _excerpt(content, ranking)
    choice = _CHOICE_PATTERN.search(content)
    if choice is not None:
        label = choice.group("label")
        return label, "choice_statement", 0.9, _excerpt(content, choice)
    return None, "none", 0.0, _excerpt(content, None)


def _tokens(content: str) -> set[str]:
    return {
        token.casefold() for token in _TOKEN.findall(content) if token.casefold() not in _STOPWORDS
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _lexical_alignment(posts: list[dict[str, Any]]) -> float:
    token_sets = [_tokens(post["content"]) for post in posts]
    pairs = list(itertools.combinations(token_sets, 2))
    if not pairs:
        return 1.0 if token_sets else 0.0
    return sum(_jaccard(left, right) for left, right in pairs) / len(pairs)


def analyze_consensus(run_id: str, public_events: list[dict[str, Any]]) -> ConsensusTimeline:
    """Analyze explicit public stance signals without modifying the run."""

    posts = sorted(
        (item for item in public_events if item.get("event_type") == "post"),
        key=lambda item: item["sequence"],
    )
    previous_by_agent: dict[str, str | None] = {}
    observations: list[StanceObservation] = []
    posts_by_round: dict[int, list[dict[str, Any]]] = {}
    for post in posts:
        posts_by_round.setdefault(post["round_number"], []).append(post)
        label, method, confidence, excerpt = _extract(post["content"])
        canonical = _canonical(label) if label else None
        if post["agent_id"] not in previous_by_agent:
            transition = "initial" if canonical is not None else "undetermined"
        elif canonical is None or previous_by_agent[post["agent_id"]] is None:
            transition = "undetermined"
        elif canonical == previous_by_agent[post["agent_id"]]:
            transition = "unchanged"
        else:
            transition = "possible_shift"
        previous_by_agent[post["agent_id"]] = canonical
        observations.append(
            StanceObservation(
                event_id=post["event_id"],
                agent_id=post["agent_id"],
                display_name=post["display_name"],
                round_number=post["round_number"],
                sequence=post["sequence"],
                stance=label,
                extraction_method=method,
                extraction_confidence=confidence,
                transition=transition,
                excerpt=excerpt,
            )
        )

    rounds: list[RoundConsensus] = []
    observations_by_round: dict[int, list[StanceObservation]] = {}
    for item in observations:
        observations_by_round.setdefault(item.round_number, []).append(item)
    for round_number in sorted(posts_by_round):
        round_posts = posts_by_round[round_number]
        round_observations = observations_by_round[round_number]
        display_by_canonical: dict[str, str] = {}
        canonical_stances: list[str] = []
        for item in round_observations:
            if item.stance is None:
                continue
            canonical = _canonical(item.stance)
            canonical_stances.append(canonical)
            display_by_canonical.setdefault(canonical, item.stance)
        counts = Counter(canonical_stances)
        participants = len(round_posts)
        detected = len(canonical_stances)
        coverage = detected / participants if participants else 0.0
        leading_canonical, leading_count = counts.most_common(1)[0] if counts else (None, 0)
        agreement = leading_count / detected if detected else None
        if coverage < 0.5 or agreement is None:
            classification = "insufficient_signal"
        elif agreement >= 0.8:
            classification = "consensus"
        elif agreement >= 0.6:
            classification = "leaning"
        else:
            classification = "divided"
        rounds.append(
            RoundConsensus(
                round_number=round_number,
                participants=participants,
                detected_stances=detected,
                stance_coverage=round(coverage, 4),
                leading_stance=(
                    display_by_canonical[leading_canonical]
                    if leading_canonical is not None
                    else None
                ),
                explicit_agreement=round(agreement, 4) if agreement is not None else None,
                lexical_alignment=round(_lexical_alignment(round_posts), 4),
                classification=classification,
                stance_counts={
                    display_by_canonical[key]: value for key, value in sorted(counts.items())
                },
            )
        )

    final = rounds[-1].classification if rounds else "insufficient_signal"
    return ConsensusTimeline(
        run_id=run_id,
        observations=tuple(observations),
        rounds=tuple(rounds),
        final_classification=final,
    )
