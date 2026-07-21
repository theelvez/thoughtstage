"""Researcher-only aggregation for provider-reported model token usage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def _empty_totals() -> dict[str, int]:
    return {"model_calls": 0, **dict.fromkeys(TOKEN_FIELDS, 0)}


def _add_usage(totals: dict[str, int], record: Mapping[str, Any]) -> None:
    totals["model_calls"] += 1
    for field in TOKEN_FIELDS:
        value = record.get(field, 0)
        if isinstance(value, int) and value >= 0:
            totals[field] += value


def summarize_model_usage(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate successful model calls without inspecting prompts or outputs."""

    totals = _empty_totals()
    groups: dict[str, dict[str, dict[str, int]]] = {
        "by_agent": {},
        "by_model": {},
        "by_phase": {},
    }
    for record in records:
        _add_usage(totals, record)
        keys = {
            "by_agent": str(record.get("agent_id", "unknown")),
            "by_model": f"{record.get('provider', 'unknown')}:{record.get('model', 'unknown')}",
            "by_phase": str(record.get("phase", "unknown")),
        }
        for group_name, key in keys.items():
            bucket = groups[group_name].setdefault(key, _empty_totals())
            _add_usage(bucket, record)

    return {
        "totals": totals,
        **{group_name: dict(sorted(values.items())) for group_name, values in groups.items()},
    }
