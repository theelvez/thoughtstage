import { useEffect, useMemo, useState } from "react";
import type { ResearchAnnotation } from "./AnnotationEditorDialog";
import "./research-workbench.css";

export type WorkbenchRunSummary = {
  run_id: string;
  status: string;
  experiment: { id?: string; name?: string };
};

type IntegrityCheck = {
  code: string;
  status: "pass" | "fail" | "warning";
  message: string;
  evidence: Record<string, unknown>;
};

type IntegrityReport = {
  run_id: string;
  valid: boolean;
  complete: boolean;
  boundary_valid: boolean;
  checks: IntegrityCheck[];
  artifacts: { path: string; size: number; sha256: string }[];
  assurance_scope: string[];
};

type CloneOption = {
  path: string;
  label: string;
  kind: "text" | "integer" | "number" | "choice";
  current: string | number | boolean | null;
  choices: string[];
};

type CloneOptions = {
  suggested_experiment_id: string;
  suggested_name: string;
  options: CloneOption[];
};

type CloneResult = {
  experiment_id: string;
  change_path: string;
  before: string | number | boolean | null;
  after: string | number | boolean | null;
};

type ComparisonRun = {
  run_id: string;
  role: string;
  label: string;
  experiment_name: string;
  integrity_valid: boolean;
  boundary_valid: boolean;
  duration_seconds: number | null;
  rounds: number;
  participants: { id: string; display_name: string; provider: string; model: string }[];
  public_posts: number;
  model_calls: number;
  total_tokens: number;
  final_posts: { agent_id: string; display_name: string; round_number: number; content: string }[];
};

type ComparisonResult = {
  baseline_run_id: string;
  runs: ComparisonRun[];
  deltas: {
    candidate_run_id: string;
    changed_variable_count: number;
    single_variable_change: boolean;
    differences: {
      path: string;
      category: "experimental" | "administrative" | "input";
      baseline: string | number | boolean | null;
      candidate: string | number | boolean | null;
    }[];
  }[];
};

type ConsensusTimeline = {
  heuristic: true;
  method: string;
  limitations: string[];
  final_classification: string;
  rounds: {
    round_number: number;
    participants: number;
    detected_stances: number;
    stance_coverage: number;
    leading_stance: string | null;
    explicit_agreement: number | null;
    lexical_alignment: number;
    classification: string;
    stance_counts: Record<string, number>;
  }[];
  observations: {
    event_id: string;
    agent_id: string;
    display_name: string;
    round_number: number;
    stance: string | null;
    extraction_method: string;
    extraction_confidence: number;
    transition: string;
    excerpt: string;
  }[];
};

type Tab = "integrity" | "clone" | "compare" | "annotations" | "timeline";
type Role = "control" | "treatment" | "counterbalance" | "replication" | "unassigned";

const tabs: { id: Tab; label: string; number: string }[] = [
  { id: "integrity", label: "Integrity & export", number: "01" },
  { id: "clone", label: "Controlled clone", number: "02" },
  { id: "compare", label: "Compare runs", number: "03" },
  { id: "annotations", label: "Annotations", number: "04" },
  { id: "timeline", label: "Stance timeline", number: "05" },
];

async function jsonResponse<T>(response: Response): Promise<T> {
  const body = await response.json() as T | { detail?: unknown };
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? String(body.detail)
      : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body as T;
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "None";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDuration(seconds: number | null) {
  if (seconds === null) return "—";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function ResearchWorkbenchDialog({
  runId,
  runName,
  runs,
  annotations,
  onClose,
  onEditAnnotation,
  onJumpToEvent,
}: {
  runId: string;
  runName: string;
  runs: WorkbenchRunSummary[];
  annotations: ResearchAnnotation[];
  onClose: () => void;
  onEditAnnotation: (annotation: ResearchAnnotation) => void;
  onJumpToEvent: (eventId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("integrity");
  const [integrity, setIntegrity] = useState<IntegrityReport | null>(null);
  const [cloneOptions, setCloneOptions] = useState<CloneOptions | null>(null);
  const [timeline, setTimeline] = useState<ConsensusTimeline | null>(null);
  const [loadError, setLoadError] = useState("");
  const [clonePath, setClonePath] = useState("");
  const [cloneValue, setCloneValue] = useState("");
  const [cloneId, setCloneId] = useState("");
  const [cloneName, setCloneName] = useState("");
  const [cloning, setCloning] = useState(false);
  const [cloneResult, setCloneResult] = useState<CloneResult | null>(null);
  const [actionError, setActionError] = useState("");
  const completedRuns = useMemo(
    () => runs.filter((item) => item.status === "completed"),
    [runs],
  );
  const firstOther = completedRuns.find((item) => item.run_id !== runId)?.run_id;
  const [selectedRuns, setSelectedRuns] = useState<string[]>(
    firstOther ? [runId, firstOther] : [runId],
  );
  const [roles, setRoles] = useState<Record<string, Role>>({
    [runId]: "control",
    ...(firstOther ? { [firstOther]: "treatment" as Role } : {}),
  });
  const [comparing, setComparing] = useState(false);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    let active = true;
    const encoded = encodeURIComponent(runId);
    const load = async () => {
      const results = await Promise.allSettled([
        fetch(`/api/runs/${encoded}/integrity`, { cache: "no-store" })
          .then((response) => jsonResponse<IntegrityReport>(response)),
        fetch(`/api/runs/${encoded}/clone-options`, { cache: "no-store" })
          .then((response) => jsonResponse<CloneOptions>(response)),
        fetch(`/api/runs/${encoded}/analysis/consensus`, { cache: "no-store" })
          .then((response) => jsonResponse<ConsensusTimeline>(response)),
      ]);
      if (!active) return;
      if (results[0].status === "fulfilled") setIntegrity(results[0].value);
      if (results[1].status === "fulfilled") {
        const options = results[1].value;
        setCloneOptions(options);
        setCloneId(options.suggested_experiment_id);
        setCloneName(options.suggested_name);
        const preferred = options.options.find((item) => item.path === "seed")
          ?? options.options[0];
        if (preferred) {
          setClonePath(preferred.path);
          setCloneValue(formatValue(preferred.current) === "None" ? "" : String(preferred.current));
        }
      }
      if (results[2].status === "fulfilled") setTimeline(results[2].value);
      const rejected = results.find((item) => item.status === "rejected");
      if (rejected?.status === "rejected") {
        setLoadError(rejected.reason instanceof Error ? rejected.reason.message : "Research data unavailable");
      }
    };
    void load();
    return () => { active = false; };
  }, [runId]);

  const selectedCloneOption = cloneOptions?.options.find((item) => item.path === clonePath);

  const changeClonePath = (path: string) => {
    setClonePath(path);
    const option = cloneOptions?.options.find((item) => item.path === path);
    setCloneValue(option?.current === null || option?.current === undefined ? "" : String(option.current));
    setCloneResult(null);
    setActionError("");
  };

  const createClone = async () => {
    if (!selectedCloneOption) return;
    setCloning(true);
    setActionError("");
    let value: string | number | null = cloneValue;
    if (selectedCloneOption.kind === "integer") value = Number.parseInt(cloneValue, 10);
    if (selectedCloneOption.kind === "number") value = Number.parseFloat(cloneValue);
    if (
      selectedCloneOption.path.endsWith(".private_briefing")
      && cloneValue.trim() === ""
    ) value = null;
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/clone`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          experiment_id: cloneId,
          name: cloneName,
          change: { path: clonePath, value },
        }),
      });
      setCloneResult(await jsonResponse<CloneResult>(response));
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Clone could not be created");
    } finally {
      setCloning(false);
    }
  };

  const launchClone = async () => {
    if (!cloneResult) return;
    setCloning(true);
    setActionError("");
    try {
      const response = await fetch(
        `/api/experiments/${encodeURIComponent(cloneResult.experiment_id)}/launch`,
        { method: "POST" },
      );
      const result = await jsonResponse<{ observer_url: string }>(response);
      window.location.assign(result.observer_url);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Clone could not be launched");
      setCloning(false);
    }
  };

  const toggleComparisonRun = (candidate: string) => {
    if (candidate === runId) return;
    setSelectedRuns((current) => {
      if (current.includes(candidate)) return current.filter((item) => item !== candidate);
      if (current.length >= 8) return current;
      return [...current, candidate];
    });
    setRoles((current) => ({
      ...current,
      [candidate]: current[candidate] ?? "treatment",
    }));
    setComparison(null);
  };

  const compare = async () => {
    setComparing(true);
    setActionError("");
    try {
      const response = await fetch("/api/run-comparisons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runs: selectedRuns.map((selected) => ({
            run_id: selected,
            role: roles[selected] ?? "unassigned",
          })),
        }),
      });
      setComparison(await jsonResponse<ComparisonResult>(response));
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Runs could not be compared");
    } finally {
      setComparing(false);
    }
  };

  const renderCloneInput = () => {
    if (!selectedCloneOption) return null;
    if (selectedCloneOption.kind === "choice") {
      return (
        <select value={cloneValue} onChange={(event) => setCloneValue(event.target.value)}>
          {selectedCloneOption.choices.map((choice) => (
            <option value={choice} key={choice}>{choice}</option>
          ))}
        </select>
      );
    }
    if (selectedCloneOption.kind === "text") {
      return (
        <textarea
          rows={selectedCloneOption.path.includes("prompt") || selectedCloneOption.path.includes("briefing") ? 7 : 3}
          value={cloneValue}
          onChange={(event) => setCloneValue(event.target.value)}
        />
      );
    }
    return (
      <input
        type="number"
        step={selectedCloneOption.kind === "number" ? "0.1" : "1"}
        value={cloneValue}
        onChange={(event) => setCloneValue(event.target.value)}
      />
    );
  };

  return (
    <div className="workbench-backdrop" onMouseDown={onClose}>
      <section
        className="workbench-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workbench-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="workbench-header">
          <div>
            <span>Research lifecycle</span>
            <h2 id="workbench-title">Research workbench</h2>
            <p>{runName}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close research workbench">×</button>
        </header>
        <div className="workbench-shell">
          <nav className="workbench-tabs" aria-label="Research tools">
            {tabs.map((item) => (
              <button
                type="button"
                className={tab === item.id ? "active" : ""}
                onClick={() => {
                  setTab(item.id);
                  setActionError("");
                }}
                key={item.id}
              >
                <span>{item.number}</span>
                {item.label}
              </button>
            ))}
          </nav>
          <div className="workbench-content">
            {loadError && <div className="workbench-warning">{loadError}</div>}

            {tab === "integrity" && (
              <section className="workbench-section">
                <div className="workbench-section-heading">
                  <div>
                    <span>Trust the record</span>
                    <h3>Run integrity</h3>
                    <p>Typed streams, hashes, event links, completeness, and public/private separation.</p>
                  </div>
                  <a
                    className="workbench-primary-link"
                    href={`/api/runs/${encodeURIComponent(runId)}/reproducibility-bundle`}
                    download
                  >
                    Export reproducibility bundle
                  </a>
                </div>
                {!integrity ? (
                  <div className="workbench-loading">Verifying persisted evidence…</div>
                ) : (
                  <>
                    <div className="integrity-scoreboard">
                      <div className={integrity.valid ? "pass" : "fail"}><span>Bundle</span><strong>{integrity.valid ? "Valid" : "Failed"}</strong></div>
                      <div className={integrity.complete ? "pass" : "fail"}><span>Completeness</span><strong>{integrity.complete ? "Complete" : "Incomplete"}</strong></div>
                      <div className={integrity.boundary_valid ? "pass" : "fail"}><span>Boundary</span><strong>{integrity.boundary_valid ? "Verified" : "Failed"}</strong></div>
                      <div><span>Artifacts</span><strong>{integrity.artifacts.length}</strong></div>
                    </div>
                    <div className="integrity-checks">
                      {integrity.checks.map((check) => (
                        <article className={check.status} key={check.code}>
                          <span>{check.status === "pass" ? "✓" : check.status === "warning" ? "!" : "×"}</span>
                          <div><strong>{check.code}</strong><p>{check.message}</p></div>
                        </article>
                      ))}
                    </div>
                    <div className="privacy-export-note">
                      <strong>Researcher-private export</strong>
                      <p>The ZIP contains soliloquies, private briefings, usage records, annotations, checksums, and all available input snapshots. Review it before publishing.</p>
                    </div>
                  </>
                )}
              </section>
            )}

            {tab === "clone" && (
              <section className="workbench-section">
                <div className="workbench-section-heading">
                  <div>
                    <span>Change one thing</span>
                    <h3>Clone as a controlled variant</h3>
                    <p>Identity and name are administrative; exactly one experimental scalar must change.</p>
                  </div>
                </div>
                {!cloneOptions ? (
                  <div className="workbench-loading">Reading cloneable variables…</div>
                ) : (
                  <div className="clone-grid">
                    <label><span>New experiment ID</span><input value={cloneId} onChange={(event) => setCloneId(event.target.value)} /></label>
                    <label><span>New experiment name</span><input value={cloneName} onChange={(event) => setCloneName(event.target.value)} /></label>
                    <label className="clone-variable"><span>Experimental variable</span><select value={clonePath} onChange={(event) => changeClonePath(event.target.value)}>{cloneOptions.options.map((option) => <option value={option.path} key={option.path}>{option.label}</option>)}</select></label>
                    <div className="clone-before"><span>Parent value</span><code>{formatValue(selectedCloneOption?.current)}</code></div>
                    <label className="clone-after"><span>New value</span>{renderCloneInput()}</label>
                    <button className="primary-action clone-create" type="button" disabled={cloning} onClick={createClone}>{cloning ? "Creating…" : "Create controlled clone"}</button>
                  </div>
                )}
                {cloneResult && (
                  <div className="clone-success">
                    <div><span>Controlled variant ready</span><strong>{cloneResult.experiment_id}</strong><p><code>{cloneResult.change_path}</code>: {formatValue(cloneResult.before)} → {formatValue(cloneResult.after)}</p></div>
                    <button type="button" disabled={cloning} onClick={launchClone}>Validate & launch clone</button>
                  </div>
                )}
              </section>
            )}

            {tab === "compare" && (
              <section className="workbench-section">
                <div className="workbench-section-heading">
                  <div>
                    <span>Control versus treatment</span>
                    <h3>Compare completed runs</h3>
                    <p>The first run is the baseline. Select up to eight controls, treatments, counterbalances, or replications.</p>
                  </div>
                  <button className="primary-action" type="button" disabled={selectedRuns.length < 2 || comparing} onClick={compare}>{comparing ? "Comparing…" : "Compare selected"}</button>
                </div>
                <div className="comparison-picker">
                  {completedRuns.map((candidate) => {
                    const selected = selectedRuns.includes(candidate.run_id);
                    return (
                      <article className={selected ? "selected" : ""} key={candidate.run_id}>
                        <label>
                          <input type="checkbox" checked={selected} disabled={candidate.run_id === runId} onChange={() => toggleComparisonRun(candidate.run_id)} />
                          <span><strong>{candidate.experiment.name ?? candidate.run_id}</strong><small>{candidate.run_id}</small></span>
                        </label>
                        {selected && (
                          <select value={roles[candidate.run_id] ?? "unassigned"} onChange={(event) => setRoles((current) => ({ ...current, [candidate.run_id]: event.target.value as Role }))}>
                            <option value="control">Control</option>
                            <option value="treatment">Treatment</option>
                            <option value="counterbalance">Counterbalance</option>
                            <option value="replication">Replication</option>
                            <option value="unassigned">Unassigned</option>
                          </select>
                        )}
                      </article>
                    );
                  })}
                </div>
                {comparison && (
                  <>
                    <div className="comparison-table-wrap">
                      <table className="comparison-table">
                        <thead><tr><th>Run</th><th>Role</th><th>Integrity</th><th>Rounds</th><th>Participants</th><th>Posts</th><th>Duration</th><th>Tokens</th></tr></thead>
                        <tbody>{comparison.runs.map((item) => <tr key={item.run_id}><td><strong>{item.experiment_name}</strong><small>{item.run_id}</small></td><td>{item.role}</td><td>{item.integrity_valid && item.boundary_valid ? "Verified" : "Review"}</td><td>{item.rounds}</td><td>{item.participants.length}</td><td>{item.public_posts}</td><td>{formatDuration(item.duration_seconds)}</td><td>{item.total_tokens.toLocaleString()}</td></tr>)}</tbody>
                      </table>
                    </div>
                    <div className="comparison-deltas">
                      {comparison.deltas.map((delta) => (
                        <article className={delta.single_variable_change ? "controlled" : "multi"} key={delta.candidate_run_id}>
                          <header><div><span>Versus baseline</span><strong>{delta.candidate_run_id}</strong></div><b>{delta.single_variable_change ? "✓ Single-variable treatment" : `${delta.changed_variable_count} experimental changes`}</b></header>
                          <ul>{delta.differences.map((difference) => <li key={`${delta.candidate_run_id}-${difference.path}`}><code>{difference.path}</code><span>{formatValue(difference.baseline)} → {formatValue(difference.candidate)}</span><small>{difference.category}</small></li>)}</ul>
                        </article>
                      ))}
                    </div>
                  </>
                )}
              </section>
            )}

            {tab === "annotations" && (
              <section className="workbench-section">
                <div className="workbench-section-heading">
                  <div>
                    <span>Qualitative analysis</span>
                    <h3>Bookmarked and annotated moments</h3>
                    <p>Notes are stored in a separate researcher-only record and never enter agent context.</p>
                  </div>
                  <strong className="annotation-count">{annotations.length} moments</strong>
                </div>
                {annotations.length === 0 ? (
                  <div className="workbench-empty"><strong>No annotations yet</strong><p>Use the star beside any public post, stimulus, or opened soliloquy.</p></div>
                ) : (
                  <div className="annotation-list">
                    {annotations.map((annotation) => (
                      <article key={annotation.annotation_id}>
                        <button type="button" className="annotation-jump" onClick={() => onJumpToEvent(annotation.target_event_id)}>★</button>
                        <div><span>{annotation.target_type} · {annotation.target_event_id}</span><p>{annotation.note || "Bookmarked without a note."}</p><div>{annotation.tags.map((tag) => <small key={tag}>{tag}</small>)}</div></div>
                        <button type="button" className="annotation-edit" onClick={() => onEditAnnotation(annotation)}>Edit</button>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}

            {tab === "timeline" && (
              <section className="workbench-section">
                <div className="workbench-section-heading">
                  <div>
                    <span>Heuristic · not ground truth</span>
                    <h3>Consensus and stance timeline</h3>
                    <p>{timeline?.method ?? "Analyzing explicit public stance signals…"}</p>
                  </div>
                  {timeline && <strong className={`timeline-verdict ${timeline.final_classification}`}>{timeline.final_classification.replaceAll("_", " ")}</strong>}
                </div>
                {!timeline ? (
                  <div className="workbench-loading">Extracting explicit public stance signals…</div>
                ) : (
                  <>
                    <div className="timeline-rounds">
                      {timeline.rounds.map((round) => (
                        <article className={round.classification} key={round.round_number}>
                          <header><span>Round {String(round.round_number).padStart(2, "0")}</span><strong>{round.classification.replaceAll("_", " ")}</strong></header>
                          <div className="alignment-meter"><span style={{ width: `${(round.explicit_agreement ?? 0) * 100}%` }} /></div>
                          <dl><div><dt>Leading stance</dt><dd>{round.leading_stance ?? "Not detected"}</dd></div><div><dt>Explicit agreement</dt><dd>{round.explicit_agreement === null ? "—" : `${Math.round(round.explicit_agreement * 100)}%`}</dd></div><div><dt>Coverage</dt><dd>{Math.round(round.stance_coverage * 100)}%</dd></div><div><dt>Lexical alignment</dt><dd>{Math.round(round.lexical_alignment * 100)}%</dd></div></dl>
                        </article>
                      ))}
                    </div>
                    <div className="stance-observations">
                      <header><span>Review cues</span><strong>Possible shifts and explicit positions</strong></header>
                      {timeline.observations.filter((item) => item.stance || item.transition === "possible_shift").map((item) => (
                        <button type="button" className={item.transition === "possible_shift" ? "shift" : ""} onClick={() => onJumpToEvent(item.event_id)} key={item.event_id}>
                          <span>R{item.round_number} · {item.display_name}</span><strong>{item.stance ?? "Undetected"}</strong><p>{item.excerpt}</p><small>{item.transition.replaceAll("_", " ")} · {Math.round(item.extraction_confidence * 100)}% extraction confidence</small>
                        </button>
                      ))}
                    </div>
                    <div className="heuristic-note"><strong>Interpretation boundary</strong><ul>{timeline.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
                  </>
                )}
              </section>
            )}

            {actionError && <div className="workbench-error">{actionError}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

export default ResearchWorkbenchDialog;
