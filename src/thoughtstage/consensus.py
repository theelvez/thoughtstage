"""Deterministic, explicitly heuristic stance and consensus analysis."""

from __future__ import annotations

import itertools
import re
from collections import Counter
from typing import Any, Literal

from pydantic import Field

from thoughtstage.models import StrictModel

_RANKING_PATTERN = re.compile(
    r"(?:\b1(?:st)?\s+place\b\s*(?:is|[:=-])"
    r"|\btop\s+choice\b\s*(?:is|[:=-])"
    r"|\bwinner\b\s+is"
    r"|(?m:^\s*\*{0,2}winner\s*:))"
    r"\s*\*{0,2}[\"']?"
    r"(?:the\s+)?(?:letter\s+|option\s+|submission\s+|candidate\s+)?"
    r"(?P<label>[A-Za-z][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_LABELED_STANCE_PATTERN = re.compile(
    r"\b(?:my\s+)?(?:(?:final|current|closing)\s+)?"
    r"(?:stance|position|verdict|choice)\s*(?:is|[:=-])\s*"
    r"\*{0,2}[\"']?\s*(?:that\s+)?(?:the\s+)?"
    r"(?:letter\s+|option\s+|submission\s+|candidate\s+)?"
    r"(?P<label>[A-Za-z][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_CHOICE_PATTERN = re.compile(
    r"\b(?:i|we)\s+(?:would\s+|now\s+|still\s+|firmly\s+)?"
    r"(?P<verb>choose|select|vote\s+for|support|prefer|recommend|remove)"
    r"\s+(?:the\s+)?(?:letter\s+|option\s+|submission\s+|candidate\s+)?"
    r"\*{0,2}[\"']?(?P<label>[A-Za-z0-9][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_LANDING_PATTERN = re.compile(
    r"\b(?:i've|i\s+have|i)\s+(?:now\s+)?(?:land|landed)\s+"
    r"(?:firmly\s+)?(?:on\s+|in\s+(?:the\s+)?)"
    r"\*{0,2}[\"']?(?P<label>[A-Za-z][A-Za-z0-9_-]{0,39})",
    re.IGNORECASE,
)
_INVALID_LABELS = {
    "a",
    "an",
    "and",
    "because",
    "for",
    "i",
    "if",
    "in",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "these",
    "they",
    "this",
    "those",
    "to",
    "we",
    "with",
    "you",
}
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
        "Deterministic high-precision explicit-choice extraction plus public-post "
        "lexical overlap; no model judge is used."
    )
    limitations: tuple[str, ...] = (
        "A detected phrase is not proof of the participant's complete position.",
        "Indirect, hedged, or unlabeled positions may remain undetected by design.",
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
    normalized = content.replace("’", "'")
    patterns = (
        (_RANKING_PATTERN, "ranking", 0.97),
        (_LABELED_STANCE_PATTERN, "choice_statement", 0.96),
        (_CHOICE_PATTERN, "choice_statement", 0.94),
        (_LANDING_PATTERN, "choice_statement", 0.92),
    )
    for pattern, method, confidence in patterns:
        match = pattern.search(normalized)
        if match is None:
            continue
        label = match.group("label")
        if label.casefold() not in _INVALID_LABELS or (len(label) == 1 and label.isupper()):
            return label, method, confidence, _excerpt(content, match)
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
    previous_by_agent: dict[str, str] = {}
    observations: list[StanceObservation] = []
    posts_by_round: dict[int, list[dict[str, Any]]] = {}
    for post in posts:
        posts_by_round.setdefault(post["round_number"], []).append(post)
        label, method, confidence, excerpt = _extract(post["content"])
        canonical = _canonical(label) if label else None
        previous = previous_by_agent.get(post["agent_id"])
        if canonical is None:
            transition = "undetermined"
        elif previous is None:
            transition = "initial"
        elif canonical == previous:
            transition = "unchanged"
        else:
            transition = "possible_shift"
        if canonical is not None:
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
        elif agreement >= 0.8 and coverage >= 0.8:
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
