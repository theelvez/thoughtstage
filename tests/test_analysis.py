from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoughtstage.analysis import (
    ANALYSIS_ARTIFACT,
    AnalysisContext,
    UnknownAnalyzerError,
    analyze_consensus_outcome,
    resolve_analyzer,
    run_declared_analyzer,
)
from thoughtstage.config import ExperimentLoadError, LoadedExperiment, load_experiment
from thoughtstage.engine import ExperimentEngine
from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.integrity import IntegrityStatus, verify_run_bundle
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    AnalyzerConfig,
    ModelOutput,
    ProviderResult,
    PublicPost,
)


class StanceProvider:
    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult:
        del seed, file_tools
        letter = "X" if agent.id == "alpha" else "Q"
        if context.round_number == 1:
            post = f"I choose {letter} because the evidence is still narrow."
        else:
            post = "I still support X as the least disruptive choice."
        return ProviderResult(
            output=ModelOutput(post=post, soliloquy=f"private-{agent.id}")
        )


def _with_analyzer(
    loaded: LoadedExperiment,
    analyzer: AnalyzerConfig | None,
) -> LoadedExperiment:
    config = loaded.config.model_copy(update={"analyzer": analyzer})
    return LoadedExperiment(
        config=config,
        source_path=loaded.source_path,
        source_bytes=json.dumps(config.model_dump(mode="json")).encode(),
        files_root=loaded.files_root,
    )


def test_declared_consensus_analyzer_writes_analysis_json(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    loaded = _with_analyzer(
        loaded_experiment,
        AnalyzerConfig(name="consensus", parameters={"task": "letter-removal"}),
    )

    result = ExperimentEngine({"mock": StanceProvider()}).run(
        loaded, output_root=tmp_path / "runs", run_id="analysis-happy"
    )
    bundle = Path(result.bundle_path)
    artifact = bundle / ANALYSIS_ARTIFACT
    payload = artifact.read_text(encoding="utf-8")
    document = json.loads(payload)

    assert artifact.is_file()
    assert document["schema_version"] == "0.1"
    assert document["run_id"] == "analysis-happy"
    assert document["analyzer"] == "consensus"
    assert document["parameters"] == {"task": "letter-removal"}
    assert document["result"]["heuristic"] is True
    assert document["result"]["final_classification"] == "consensus"
    assert document["result"]["rounds"][0]["classification"] == "divided"
    assert document["result"]["rounds"][1]["leading_stance"] == "X"
    assert "private-alpha" not in payload
    assert "TEST_PROVIDER_KEY" not in payload

    report = verify_run_bundle(bundle)
    assert report.valid is True
    analysis_check = next(item for item in report.checks if item.code == "declared-analysis")
    assert analysis_check.status is IntegrityStatus.PASS


def test_module_path_analyzer_is_resolved_and_persisted(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    loaded = _with_analyzer(
        loaded_experiment,
        AnalyzerConfig(name="thoughtstage.analysis:analyze_consensus_outcome"),
    )

    result = ExperimentEngine({"mock": StanceProvider()}).run(
        loaded, output_root=tmp_path / "runs", run_id="analysis-module"
    )
    document = json.loads(
        (Path(result.bundle_path) / ANALYSIS_ARTIFACT).read_text(encoding="utf-8")
    )

    assert document["analyzer"] == "thoughtstage.analysis:analyze_consensus_outcome"
    assert document["result"]["heuristic"] is True
    assert resolve_analyzer("thoughtstage.analysis") is analyze_consensus_outcome


def test_unknown_analyzer_fails_before_writing_a_bundle(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    loaded = _with_analyzer(loaded_experiment, AnalyzerConfig(name="not-a-real-analyzer"))
    output_root = tmp_path / "runs"

    with pytest.raises(UnknownAnalyzerError, match="not-a-real-analyzer"):
        ExperimentEngine().run(loaded, output_root=output_root, run_id="analysis-unknown")

    assert not (output_root / "analysis-unknown").exists()


def test_missing_analyzer_name_is_rejected_by_the_manifest(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(
        content.replace("seed: 17\n", "seed: 17\nanalyzer: {}\n"),
        encoding="utf-8",
    )

    with pytest.raises(ExperimentLoadError, match="name"):
        load_experiment(experiment_file)


def test_manifest_loads_optional_analyzer_declaration(experiment_file: Path) -> None:
    content = experiment_file.read_text(encoding="utf-8")
    experiment_file.write_text(
        content.replace(
            "seed: 17\n",
            "seed: 17\nanalyzer:\n  name: consensus\n  parameters:\n    task: demo\n",
        ),
        encoding="utf-8",
    )

    loaded = load_experiment(experiment_file)

    assert loaded.config.analyzer is not None
    assert loaded.config.analyzer.name == "consensus"
    assert loaded.config.analyzer.parameters == {"task": "demo"}


def test_no_analyzer_run_does_not_write_analysis_json(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    result = ExperimentEngine().run(
        loaded_experiment, output_root=tmp_path / "runs", run_id="analysis-absent"
    )
    bundle = Path(result.bundle_path)

    assert not (bundle / ANALYSIS_ARTIFACT).exists()
    report = verify_run_bundle(bundle)
    analysis_check = next(item for item in report.checks if item.code == "declared-analysis")
    assert analysis_check.status is IntegrityStatus.PASS
    assert analysis_check.evidence["declared"] is False


def test_unknown_module_paths_are_rejected() -> None:
    with pytest.raises(UnknownAnalyzerError, match="os:getcwd"):
        resolve_analyzer("os:getcwd")
    with pytest.raises(UnknownAnalyzerError, match="thoughtstage.missing_analyzer"):
        resolve_analyzer("thoughtstage.missing_analyzer")
    with pytest.raises(UnknownAnalyzerError, match="thoughtstage.consensus:missing"):
        resolve_analyzer("thoughtstage.consensus:missing")
    with pytest.raises(UnknownAnalyzerError, match="thoughtstage.analysis:"):
        resolve_analyzer("thoughtstage.analysis:")
    with pytest.raises(UnknownAnalyzerError, match="unknown analyzer"):
        resolve_analyzer("   ")


def test_analyzer_must_return_a_json_object() -> None:
    from thoughtstage import analysis as analysis_mod

    def _not_an_object(_context: AnalysisContext) -> list[str]:
        return ["not", "an", "object"]

    original = analysis_mod.BUILTIN_ANALYZERS["consensus"]
    analysis_mod.BUILTIN_ANALYZERS["consensus"] = _not_an_object
    try:
        context = AnalysisContext(
            run_id="bad-result",
            experiment_id="test-stage",
            public_posts=(
                PublicPost(
                    event_id="post-1",
                    sequence=1,
                    experiment_id="test-stage",
                    round_number=1,
                    agent_id="alpha",
                    display_name="Alpha",
                    content="I choose X.",
                ).model_dump(mode="json"),
            ),
        )
        with pytest.raises(TypeError, match="JSON object"):
            run_declared_analyzer(AnalyzerConfig(name="consensus"), context)
    finally:
        analysis_mod.BUILTIN_ANALYZERS["consensus"] = original


def test_completed_run_without_analysis_json_fails_integrity(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    loaded = _with_analyzer(loaded_experiment, AnalyzerConfig(name="consensus"))
    result = ExperimentEngine({"mock": StanceProvider()}).run(
        loaded, output_root=tmp_path / "runs", run_id="analysis-missing-artifact"
    )
    artifact = Path(result.bundle_path) / ANALYSIS_ARTIFACT
    artifact.unlink()

    report = verify_run_bundle(result.bundle_path)
    analysis_check = next(item for item in report.checks if item.code == "declared-analysis")
    assert report.valid is False
    assert analysis_check.status is IntegrityStatus.FAIL


def test_analysis_json_identity_mismatch_fails_integrity(
    loaded_experiment: LoadedExperiment, tmp_path: Path
) -> None:
    loaded = _with_analyzer(loaded_experiment, AnalyzerConfig(name="consensus"))
    result = ExperimentEngine({"mock": StanceProvider()}).run(
        loaded, output_root=tmp_path / "runs", run_id="analysis-identity"
    )
    artifact = Path(result.bundle_path) / ANALYSIS_ARTIFACT
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["run_id"] = "other-run"
    artifact.write_text(json.dumps(document) + "\n", encoding="utf-8")

    report = verify_run_bundle(result.bundle_path)
    analysis_check = next(item for item in report.checks if item.code == "declared-analysis")
    assert report.valid is False
    assert analysis_check.status is IntegrityStatus.FAIL
