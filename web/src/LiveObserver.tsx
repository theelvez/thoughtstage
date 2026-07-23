import { useEffect, useMemo, useRef, useState } from "react";
import AnnotationEditorDialog, {
  type AnnotationTarget,
  type AnnotationTargetType,
  type ResearchAnnotation,
} from "./AnnotationEditorDialog";
import "./live-observer.css";
import ResearchWorkbenchDialog from "./ResearchWorkbenchDialog";
import RunSummaryDialog from "./RunSummaryDialog";

type Agent = {
  id: string;
  display_name: string;
  provider: string;
  model: string;
};

type Counts = {
  public_posts: number;
  public_stimuli: number;
  soliloquies: number;
  model_calls: number;
  file_tool_calls: number;
};

type RunSummary = {
  run_id: string;
  status: string;
  created_at: string | null;
  completed_at: string | null;
  failure?: { type?: string; message?: string } | null;
  thoughtstage?: { version?: string; source_revision?: string | null };
  experiment: {
    id?: string;
    name?: string;
    system_prompt?: string;
    config_sha256?: string;
  };
  execution: {
    rounds?: number;
    schedule?: string;
    turn_order?: string;
    private_memory?: string;
    seed?: number;
    scheduled_stimuli?: number;
  };
  agents: Agent[];
  counts: Counts;
};

type PublicPost = {
  event_type?: "post";
  event_id: string;
  sequence: number;
  experiment_id: string;
  round_number: number;
  agent_id: string;
  display_name: string;
  content: string;
};

type PublicStimulus = {
  event_type: "stimulus";
  event_id: string;
  sequence: number;
  experiment_id: string;
  round_number: number;
  stimulus_id: string;
  source_id: string;
  display_name: string;
  content: string;
};

type PublicEvent = PublicPost | PublicStimulus;

type Soliloquy = {
  event_id: string;
  post_event_id: string;
  sequence: number;
  experiment_id: string;
  round_number: number;
  agent_id: string;
  content: string;
};

type UsageSummary = {
  totals: {
    model_calls: number;
    input_tokens: number;
    cached_input_tokens?: number;
    output_tokens: number;
    reasoning_tokens?: number;
    total_tokens?: number;
  };
  by_agent?: Record<string, {
    model_calls?: number;
    total_tokens?: number;
  }>;
};

type RunDetail = RunSummary & {
  posts: PublicEvent[];
  stimuli: PublicStimulus[];
  soliloquies: Soliloquy[];
  usage_summary: UsageSummary;
  private_briefings: Record<string, string>;
};

const AGENT_COLORS = ["#4734d3", "#dd5f39", "#26766c", "#9a6814", "#8a4ca8", "#2776a3"];

function formatRunTime(value: string | null) {
  if (!value) return "in progress";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function shortModel(model: string) {
  return model.split("/").at(-1) ?? model;
}

function isStimulus(event: PublicEvent): event is PublicStimulus {
  return event.event_type === "stimulus";
}

function formatTokens(value: number) {
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function PostCard({
  post,
  soliloquy,
  agent,
  color,
  revealed,
  newest,
  onToggle,
  publicAnnotation,
  privateAnnotation,
  onAnnotatePublic,
  onAnnotatePrivate,
}: {
  post: PublicEvent;
  soliloquy?: Soliloquy;
  agent?: Agent;
  color: string;
  revealed: boolean;
  newest: boolean;
  onToggle: () => void;
  publicAnnotation?: ResearchAnnotation;
  privateAnnotation?: ResearchAnnotation;
  onAnnotatePublic: () => void;
  onAnnotatePrivate: () => void;
}) {
  const stimulus = isStimulus(post);
  return (
    <article
      id={`event-${post.event_id}`}
      className={`feed-card ${stimulus ? "stimulus" : ""} ${newest ? "newest" : ""}`}
      style={{ "--agent": color } as React.CSSProperties}
    >
      <div className="feed-card-rail" aria-hidden="true" />
      <div className="feed-card-body">
        <header className="post-header">
          <span className="agent-avatar">{stimulus ? "◆" : post.display_name.charAt(0).toUpperCase()}</span>
          <span className="post-byline">
            <strong>{post.display_name}</strong>
            <small>{stimulus ? "scripted public stimulus" : agent ? shortModel(agent.model) : "participant"}</small>
          </span>
          <span className="post-index">
            Round {String(post.round_number).padStart(2, "0")} · #{String(post.sequence).padStart(2, "0")}
          </span>
          <button
            className={`moment-annotation ${publicAnnotation ? "annotated" : ""}`}
            type="button"
            onClick={onAnnotatePublic}
            title={publicAnnotation ? "Edit researcher annotation" : "Bookmark or annotate this public event"}
          >★</button>
        </header>

        <p className="post-content">{post.content}</p>

        {stimulus ? (
          <div className="stimulus-note">Declared in the experiment manifest · visible to every participant</div>
        ) : (
          <button
            className={`soliloquy-toggle ${revealed ? "open" : ""}`}
            type="button"
            disabled={!soliloquy}
            aria-expanded={revealed}
            onClick={onToggle}
          >
            <span className="lock-dot" aria-hidden="true" />
            {!soliloquy
              ? "Soliloquy pending"
              : revealed
                ? "Close backstage"
                : "Open soliloquy"}
            {soliloquy && <span aria-hidden="true">{revealed ? "−" : "+"}</span>}
          </button>
        )}

        {revealed && soliloquy && (
          <section className="soliloquy-panel" aria-label={`${post.display_name} private soliloquy`}>
            <div className="soliloquy-label">
              <span>Researcher channel</span>
              <span>Private · same agent</span>
            </div>
            <button
              className={`soliloquy-annotation ${privateAnnotation ? "annotated" : ""}`}
              type="button"
              onClick={onAnnotatePrivate}
            >
              ★ {privateAnnotation ? "Edit annotation" : "Annotate soliloquy"}
            </button>
            <p>{soliloquy.content}</p>
          </section>
        )}
      </div>
    </article>
  );
}

function LiveObserver() {
  const requestedRunId = new URLSearchParams(window.location.search).get("run") ?? "";
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(requestedRunId);
  const [manualSelection, setManualSelection] = useState(Boolean(requestedRunId));
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [followLive, setFollowLive] = useState(true);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const [briefingAgentId, setBriefingAgentId] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [workbenchOpen, setWorkbenchOpen] = useState(false);
  const [annotations, setAnnotations] = useState<ResearchAnnotation[]>([]);
  const [annotationTarget, setAnnotationTarget] = useState<AnnotationTarget | null>(null);
  const feedEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/runs", { cache: "no-store" });
        if (!response.ok) throw new Error(`observer returned ${response.status}`);
        const payload = (await response.json()) as { runs: RunSummary[] };
        if (!active) return;
        setRuns(payload.runs);
        setConnected(true);
        setError("");
        if (!manualSelection) {
          const preferred = payload.runs.find((run) => run.status === "running") ?? payload.runs[0];
          if (preferred) setSelectedRunId(preferred.run_id);
        }
      } catch (reason) {
        if (!active) return;
        setConnected(false);
        setError(reason instanceof Error ? reason.message : "observer unavailable");
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 1_500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [manualSelection]);

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`/api/runs/${encodeURIComponent(selectedRunId)}`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`run returned ${response.status}`);
        const payload = (await response.json()) as RunDetail;
        if (!active) return;
        setDetail(payload);
        setConnected(true);
        setError("");
      } catch (reason) {
        if (!active) return;
        setConnected(false);
        setError(reason instanceof Error ? reason.message : "run unavailable");
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 800);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) {
      setAnnotations([]);
      return;
    }
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(
          `/api/runs/${encodeURIComponent(selectedRunId)}/annotations`,
          { cache: "no-store" },
        );
        if (!response.ok) return;
        const payload = (await response.json()) as { annotations: ResearchAnnotation[] };
        if (active) setAnnotations(payload.annotations);
      } catch {
        // Annotation availability must not interrupt the live observer.
      }
    };
    void refresh();
    return () => { active = false; };
  }, [selectedRunId]);

  useEffect(() => {
    setPromptExpanded(false);
    setBriefingAgentId(null);
    setSummaryOpen(false);
    setWorkbenchOpen(false);
    setAnnotationTarget(null);
  }, [selectedRunId]);

  useEffect(() => {
    if (briefingAgentId === null) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBriefingAgentId(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [briefingAgentId]);

  useEffect(() => {
    if (followLive && detail?.status === "running") feedEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [detail?.posts.length, detail?.status, followLive]);

  const soliloquies = useMemo(
    () => new Map((detail?.soliloquies ?? []).map((item) => [item.post_event_id, item])),
    [detail?.soliloquies],
  );
  const agents = useMemo(
    () => new Map((detail?.agents ?? []).map((agent) => [agent.id, agent])),
    [detail?.agents],
  );
  const colors = useMemo(
    () => new Map((detail?.agents ?? []).map((agent, index) => [agent.id, AGENT_COLORS[index % AGENT_COLORS.length]])),
    [detail?.agents],
  );
  const annotationsByTarget = useMemo(
    () => new Map(
      annotations.map((annotation) => [
        `${annotation.target_type}:${annotation.target_event_id}`,
        annotation,
      ]),
    ),
    [annotations],
  );

  const systemPrompt = detail?.experiment.system_prompt?.trim() ?? "";
  const briefingAgent = briefingAgentId ? agents.get(briefingAgentId) : undefined;
  const briefingContent = briefingAgentId
    ? detail?.private_briefings?.[briefingAgentId]
    : undefined;
  const posts = detail?.posts ?? [];
  const newestPost = posts.at(-1);
  const agentPosts = posts.filter((post): post is PublicPost => !isStimulus(post));
  const currentRound = posts.reduce((highest, post) => Math.max(highest, post.round_number), 0);
  const totalRounds = detail?.execution.rounds ?? 0;
  const expectedTurns = totalRounds * (detail?.agents.length ?? 0);
  const turnProgress = expectedTurns ? Math.min((agentPosts.length / expectedTurns) * 100, 100) : 0;
  const revealablePosts = posts.filter((post) => soliloquies.has(post.event_id));
  const allRevealed = revealablePosts.length > 0
    && revealablePosts.every((post) => revealed.has(post.event_id));

  const toggleAll = () => {
    if (allRevealed) {
      setRevealed(new Set());
      return;
    }
    setRevealed(new Set(revealablePosts.map((post) => post.event_id)));
  };

  const openAnnotation = (
    type: AnnotationTargetType,
    eventId: string,
    label: string,
    preview: string,
  ) => {
    setAnnotationTarget({
      type,
      eventId,
      label,
      preview,
      annotation: annotationsByTarget.get(`${type}:${eventId}`),
    });
  };

  const targetForAnnotation = (annotation: ResearchAnnotation): AnnotationTarget | null => {
    if (!detail) return null;
    if (annotation.target_type === "soliloquy") {
      const soliloquy = detail.soliloquies.find(
        (item) => item.event_id === annotation.target_event_id,
      );
      const post = soliloquy
        ? detail.posts.find((item) => item.event_id === soliloquy.post_event_id)
        : undefined;
      if (!soliloquy) return null;
      return {
        type: "soliloquy",
        eventId: soliloquy.event_id,
        label: `${post?.display_name ?? soliloquy.agent_id} · round ${soliloquy.round_number} soliloquy`,
        preview: soliloquy.content,
        annotation,
      };
    }
    const event = detail.posts.find((item) => item.event_id === annotation.target_event_id);
    if (!event) return null;
    return {
      type: annotation.target_type,
      eventId: event.event_id,
      label: `${event.display_name} · round ${event.round_number} ${annotation.target_type}`,
      preview: event.content,
      annotation,
    };
  };

  const jumpToEvent = (eventId: string) => {
    const soliloquy = detail?.soliloquies.find((item) => item.event_id === eventId);
    const publicEventId = soliloquy?.post_event_id ?? eventId;
    if (soliloquy) {
      setRevealed((current) => new Set(current).add(publicEventId));
    }
    setWorkbenchOpen(false);
    window.setTimeout(() => {
      document.getElementById(`event-${publicEventId}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 80);
  };

  return (
    <main className="observer-app">
      <header className="observer-header">
        <div className="observer-brand">
          <span className="observer-mark" aria-hidden="true">TS</span>
          <div>
            <strong>Thoughtstage</strong>
            <small>Live observer</small>
          </div>
        </div>

        <div className="run-picker">
          <label htmlFor="run-select">Watching</label>
          <select
            id="run-select"
            value={selectedRunId}
            onChange={(event) => {
              setSelectedRunId(event.target.value);
              setManualSelection(true);
              setRevealed(new Set());
            }}
          >
            {runs.length === 0 && !selectedRunId && <option value="">No runs found</option>}
            {selectedRunId && !runs.some((run) => run.run_id === selectedRunId) && (
              <option value={selectedRunId}>Starting run…</option>
            )}
            {runs.map((run) => (
              <option value={run.run_id} key={run.run_id}>
                {run.experiment.name ?? run.run_id} · {run.status}
              </option>
            ))}
          </select>
          {manualSelection && (
            <button type="button" onClick={() => setManualSelection(false)}>Follow newest</button>
          )}
        </div>

        <div className="observer-header-actions">
          {detail?.status === "completed" && (
            <>
              <button className="workbench-launch" type="button" onClick={() => setWorkbenchOpen(true)}>Research workbench</button>
              <button className="results-summary-button" type="button" onClick={() => setSummaryOpen(true)}>Experiment results summary</button>
            </>
          )}
          <a className="builder-launch" href="/?view=builder">+ New experiment</a>
          <div className={`connection-state ${connected ? "connected" : "disconnected"}`}>
            <span aria-hidden="true" />
            {connected ? "Observer connected" : "Observer offline"}
          </div>
        </div>
      </header>

      <section className="run-strip">
        <div className="run-title">
          <span className={`run-state ${detail?.status === "running" ? "is-live" : ""} ${detail?.status === "failed" ? "is-failed" : ""}`}>
            {detail?.status === "running" ? "Live experiment" : detail?.status === "failed" ? "Run failed" : detail?.status ?? "Standby"}
          </span>
          <h1>{detail?.experiment.name ?? "Waiting for a run"}</h1>
          <p>{detail ? `${detail.execution.schedule ?? "unknown"} schedule · started ${formatRunTime(detail.created_at)}` : "Start a Thoughtstage run to populate the observer."}</p>
        </div>
        <div className="run-metrics">
          <div><strong>{String(currentRound).padStart(2, "0")}</strong><span>/ {String(totalRounds).padStart(2, "0")} rounds</span></div>
          <div><strong>{agentPosts.length}</strong><span>/ {expectedTurns || "—"} turns</span></div>
          <div><strong>{detail?.counts.public_stimuli ?? 0}</strong><span>stimuli</span></div>
          <div><strong>{detail?.soliloquies.length ?? 0}</strong><span>private</span></div>
          <div><strong>{detail?.counts.model_calls ?? 0}</strong><span>model calls</span></div>
          <div><strong>{detail?.counts.file_tool_calls ?? 0}</strong><span>file reads</span></div>
          <div>
            <strong title={`${detail?.usage_summary.totals.input_tokens ?? 0} input / ${detail?.usage_summary.totals.output_tokens ?? 0} output tokens`}>
              {formatTokens(detail?.usage_summary.totals.input_tokens ?? 0)} / {formatTokens(detail?.usage_summary.totals.output_tokens ?? 0)}
            </strong>
            <span>input / output tokens</span>
          </div>
        </div>
        <div className="progress-track" aria-label={`${Math.round(turnProgress)} percent complete`}>
          <span style={{ width: `${turnProgress}%` }} />
        </div>
      </section>

      {error && <div className="observer-error">{error}</div>}
      {detail?.status === "failed" && (
        <div className="observer-error">
          {detail.failure?.message ?? "Experiment execution failed."}
          {detail.failure?.type ? ` (${detail.failure.type})` : ""}
        </div>
      )}

      <div className="observer-layout">
        <section className="feed-column" aria-label="Public conversation">
          <div className="column-toolbar">
            <div className="prompt-summary">
              <div><span>Shared system prompt</span><strong>Visible to every agent</strong></div>
              <p id="shared-system-prompt" className={promptExpanded ? "expanded" : ""}>
                {systemPrompt || "Prompt unavailable for this legacy run."}
              </p>
              {systemPrompt && (
                <button
                  type="button"
                  className="prompt-toggle"
                  aria-expanded={promptExpanded}
                  aria-controls="shared-system-prompt"
                  onClick={() => setPromptExpanded(!promptExpanded)}
                >
                  {promptExpanded ? "Collapse" : "Read full prompt"}
                </button>
              )}
            </div>
            <div className="toolbar-actions">
              <button type="button" className={followLive ? "active" : ""} onClick={() => setFollowLive(!followLive)}>
                {followLive ? "Following live" : "Follow live"}
              </button>
              <button type="button" onClick={toggleAll} disabled={revealablePosts.length === 0}>
                {allRevealed ? "Seal all" : "Reveal all"}
              </button>
            </div>
          </div>

          <div className="feed-scroll">
            {posts.length === 0 ? (
              <div className="empty-feed">
                <span className="empty-orbit" aria-hidden="true"><i /><i /><i /><i /></span>
                <h2>{detail?.status === "running" ? "The agents are thinking." : "The stage is quiet."}</h2>
                <p>Public posts and their sealed soliloquies will appear here as the run bundle is written.</p>
              </div>
            ) : (
              posts.map((post) => {
                const soliloquy = soliloquies.get(post.event_id);
                const targetType: AnnotationTargetType = isStimulus(post) ? "stimulus" : "post";
                return (
                  <PostCard
                    key={post.event_id}
                    post={post}
                    soliloquy={soliloquy}
                    agent={isStimulus(post) ? undefined : agents.get(post.agent_id)}
                    color={isStimulus(post) ? "#9a6814" : colors.get(post.agent_id) ?? AGENT_COLORS[0]}
                    revealed={revealed.has(post.event_id)}
                    newest={post.event_id === newestPost?.event_id && detail?.status === "running"}
                    publicAnnotation={annotationsByTarget.get(`${targetType}:${post.event_id}`)}
                    privateAnnotation={soliloquy
                      ? annotationsByTarget.get(`soliloquy:${soliloquy.event_id}`)
                      : undefined}
                    onAnnotatePublic={() => openAnnotation(
                      targetType,
                      post.event_id,
                      `${post.display_name} · round ${post.round_number} ${targetType}`,
                      post.content,
                    )}
                    onAnnotatePrivate={() => {
                      if (!soliloquy) return;
                      openAnnotation(
                        "soliloquy",
                        soliloquy.event_id,
                        `${post.display_name} · round ${post.round_number} soliloquy`,
                        soliloquy.content,
                      );
                    }}
                    onToggle={() => {
                      setRevealed((current) => {
                        const next = new Set(current);
                        if (next.has(post.event_id)) next.delete(post.event_id);
                        else next.add(post.event_id);
                        return next;
                      });
                    }}
                  />
                );
              })
            )}
            <div ref={feedEnd} />
          </div>
        </section>

        <aside className="research-rail">
          <div className="rail-heading">
            <span>Research channel</span>
            <strong>Participants</strong>
            <p>Model bindings are visible here only to the researcher.</p>
          </div>

          <div className="agent-list">
            {(detail?.agents ?? []).map((agent) => {
              const participantPosts = posts.filter(
                (post): post is PublicPost => !isStimulus(post) && post.agent_id === agent.id,
              );
              const last = participantPosts.at(-1);
              const active = newestPost !== undefined
                && !isStimulus(newestPost)
                && newestPost.agent_id === agent.id
                && detail?.status === "running";
              const color = colors.get(agent.id) ?? AGENT_COLORS[0];
              const privateBriefing = detail?.private_briefings?.[agent.id];
              return (
                <article className={`agent-card ${active ? "active" : ""}`} key={agent.id} style={{ "--agent": color } as React.CSSProperties}>
                  <span className="rail-avatar">{agent.display_name.charAt(0).toUpperCase()}</span>
                  <div className="agent-identity">
                    <strong>{agent.display_name}</strong>
                    <small>{shortModel(agent.model)}</small>
                  </div>
                  <div className="agent-count"><strong>{participantPosts.length}</strong><small>turns</small></div>
                  <div className="agent-status">
                    <span>{active ? "On stage" : last ? `Last seen R${last.round_number}` : "Waiting"}</span>
                  </div>
                  {privateBriefing && (
                    <button
                      type="button"
                      className="private-briefing-button"
                      onClick={() => setBriefingAgentId(agent.id)}
                    >
                      View private briefing
                    </button>
                  )}
                </article>
              );
            })}
          </div>

          <div className="privacy-note">
            <span aria-hidden="true">◆</span>
            <div><strong>Backstage is sealed</strong><p>Soliloquies are shown to you, never placed in another agent’s context.</p></div>
          </div>
        </aside>
      </div>

      {summaryOpen && detail && (
        <RunSummaryDialog detail={detail} onClose={() => setSummaryOpen(false)} />
      )}

      {workbenchOpen && detail && (
        <ResearchWorkbenchDialog
          runId={detail.run_id}
          runName={detail.experiment.name ?? detail.run_id}
          runs={runs}
          annotations={annotations}
          onClose={() => setWorkbenchOpen(false)}
          onEditAnnotation={(annotation) => {
            const target = targetForAnnotation(annotation);
            if (target) setAnnotationTarget(target);
          }}
          onJumpToEvent={jumpToEvent}
        />
      )}

      {annotationTarget && detail && (
        <AnnotationEditorDialog
          runId={detail.run_id}
          target={annotationTarget}
          onClose={() => setAnnotationTarget(null)}
          onSaved={(annotation) => {
            setAnnotations((current) => {
              const without = current.filter(
                (item) => item.annotation_id !== annotation.annotation_id,
              );
              return [...without, annotation];
            });
          }}
          onDeleted={(annotationId) => {
            setAnnotations((current) => current.filter(
              (item) => item.annotation_id !== annotationId,
            ));
          }}
        />
      )}

      {briefingAgent && briefingContent && (
        <div
          className="briefing-backdrop"
          onMouseDown={() => setBriefingAgentId(null)}
        >
          <section
            className="briefing-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="briefing-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>Researcher-only input</span>
                <h2 id="briefing-title">{briefingAgent.display_name} · private briefing</h2>
              </div>
              <button type="button" onClick={() => setBriefingAgentId(null)} aria-label="Close private briefing">×</button>
            </header>
            <p>{briefingContent}</p>
            <small>
              Delivered only to this participant; never placed in another agent's context.
            </small>
          </section>
        </div>
      )}
    </main>
  );
}

export default LiveObserver;
