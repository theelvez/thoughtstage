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
    r"|(?m:^\s*\*{0,2}winner\s*:)"
    r"|\bfinal\s+vote\s*[:=])"
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
