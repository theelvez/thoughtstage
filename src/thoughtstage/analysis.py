"""Optional, deterministic analyzers that write analysis.json into a run bundle."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from thoughtstage.consensus import analyze_consensus
from thoughtstage.models import (
    AnalyzerConfig,
    FileToolEvent,
    ModelUsageEvent,
    PublicPost,
    PublicStimulus,
    Soliloquy,
    StrictModel,
)

ANALYSIS_ARTIFACT = "analysis.json"
_THOUGHTSTAGE_MODULE_PREFIX = "thoughtstage."


class UnknownAnalyzerError(ValueError):
    """Raised when a declared analyzer cannot be resolved."""


class AnalysisContext(StrictModel):
    """Completed-bundle records an analyzer may read.

    Analyzers never receive another agent's generation-time context. They may
    inspect the public stream and researcher-private records already persisted
    in the bundle.
    """

    run_id: str
    experiment_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    public_posts: tuple[dict[str, Any], ...]
    public_stimuli: tuple[dict[str, Any], ...] = ()
    soliloquies: tuple[dict[str, Any], ...] = ()
    model_usage: tuple[dict[str, Any], ...] = ()
    file_tool_events: tuple[dict[str, Any], ...] = ()
    private_briefings: dict[str, str] = Field(default_factory=dict)


class AnalysisDocument(StrictModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    analyzer: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any]


AnalyzerFn = Callable[[AnalysisContext], Mapping[str, Any]]


def analyze_consensus_outcome(context: AnalysisContext) -> dict[str, Any]:
    """Wrap the public-only consensus heuristic as a plug-in analyzer."""

    timeline = analyze_consensus(context.run_id, list(context.public_posts))
    return timeline.model_dump(mode="json")


analyze = analyze_consensus_outcome

BUILTIN_ANALYZERS: dict[str, AnalyzerFn] = {
    "consensus": analyze_consensus_outcome,
}


def _split_analyzer_ref(name: str) -> tuple[str, str] | None:
    stripped = name.strip()
    if not stripped:
        return None
    if ":" in stripped:
        module_name, _, attr = stripped.partition(":")
        if module_name and attr.isidentifier():
            return module_name, attr
        return None
    if "." in stripped:
        return stripped, "analyze"
    return None


def resolve_analyzer(name: str) -> AnalyzerFn:
    """Resolve a built-in analyzer name or a thoughtstage module path."""

    if name in BUILTIN_ANALYZERS:
        return BUILTIN_ANALYZERS[name]
    ref = _split_analyzer_ref(name)
    if ref is None:
        raise UnknownAnalyzerError(f"unknown analyzer {name!r}")
    module_name, attr = ref
    if not module_name.startswith(_THOUGHTSTAGE_MODULE_PREFIX):
        raise UnknownAnalyzerError(
            f"analyzer {name!r} must be a built-in name or a thoughtstage module path"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise UnknownAnalyzerError(f"unknown analyzer {name!r}") from exc
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise UnknownAnalyzerError(f"unknown analyzer {name!r}")
    return fn


def analysis_context_from_records(
    *,
    run_id: str,
    experiment_id: str,
    parameters: Mapping[str, Any],
    public_posts: Sequence[PublicPost],
    public_stimuli: Sequence[PublicStimulus] = (),
    soliloquies: Sequence[Soliloquy] = (),
    model_usage: Sequence[ModelUsageEvent] = (),
    file_tool_events: Sequence[FileToolEvent] = (),
    private_briefings: Mapping[str, str] | None = None,
) -> AnalysisContext:
    """Build a secret-free analysis context from records already in the bundle."""

    return AnalysisContext(
        run_id=run_id,
        experiment_id=experiment_id,
        parameters=dict(parameters),
        public_posts=tuple(item.model_dump(mode="json") for item in public_posts),
        public_stimuli=tuple(item.model_dump(mode="json") for item in public_stimuli),
        soliloquies=tuple(item.model_dump(mode="json") for item in soliloquies),
        model_usage=tuple(item.model_dump(mode="json") for item in model_usage),
        file_tool_events=tuple(item.model_dump(mode="json") for item in file_tool_events),
        private_briefings=dict(private_briefings or {}),
    )


def run_declared_analyzer(
    analyzer: AnalyzerConfig,
    context: AnalysisContext,
) -> AnalysisDocument:
    """Execute a declared analyzer and wrap its JSON object result."""

    fn = resolve_analyzer(analyzer.name)
    result = fn(context)
    if not isinstance(result, dict):
        raise TypeError(f"analyzer {analyzer.name!r} must return a JSON object")
    return AnalysisDocument(
        run_id=context.run_id,
        analyzer=analyzer.name,
        parameters=dict(analyzer.parameters),
        result=dict(result),
    )
