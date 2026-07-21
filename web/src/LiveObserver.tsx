import { useEffect, useMemo, useRef, useState } from "react";
import "./live-observer.css";

type Agent = {
  id: string;
  display_name: string;
  provider: string;
  model: string;
};

type Counts = {
  public_posts: number;
  soliloquies: number;
};

type RunSummary = {
  run_id: string;
  status: string;
  created_at: string | null;
  completed_at: string | null;
  experiment: { id?: string; name?: string };
  execution: { rounds?: number; schedule?: string };
  agents: Agent[];
  counts: Counts;
};

type PublicPost = {
  event_id: string;
  sequence: number;
  experiment_id: string;
  round_number: number;
  agent_id: string;
  display_name: string;
  content: string;
};

type Soliloquy = {
  event_id: string;
  post_event_id: string;
  sequence: number;
  experiment_id: string;
  round_number: number;
  agent_id: string;
  content: string;
};

type RunDetail = RunSummary & {
  posts: PublicPost[];
  soliloquies: Soliloquy[];
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

function PostCard({
  post,
  soliloquy,
  agent,
  color,
  revealed,
  newest,
  onToggle,
}: {
  post: PublicPost;
  soliloquy?: Soliloquy;
  agent?: Agent;
  color: string;
  revealed: boolean;
  newest: boolean;
  onToggle: () => void;
}) {
  return (
    <article className={`feed-card ${newest ? "newest" : ""}`} style={{ "--agent": color } as React.CSSProperties}>
      <div className="feed-card-rail" aria-hidden="true" />
      <div className="feed-card-body">
        <header className="post-header">
          <span className="agent-avatar">{post.display_name.charAt(0).toUpperCase()}</span>
          <span className="post-byline">
            <strong>{post.display_name}</strong>
            <small>{agent ? shortModel(agent.model) : "participant"}</small>
          </span>
          <span className="post-index">
            Round {String(post.round_number).padStart(2, "0")} · #{String(post.sequence).padStart(2, "0")}
          </span>
        </header>

        <p className="post-content">{post.content}</p>

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

        {revealed && soliloquy && (
          <section className="soliloquy-panel" aria-label={`${post.display_name} private soliloquy`}>
            <div className="soliloquy-label">
              <span>Researcher channel</span>
              <span>Private · same agent</span>
            </div>
            <p>{soliloquy.content}</p>
          </section>
        )}
      </div>
    </article>
  );
}

function LiveObserver() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [manualSelection, setManualSelection] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [followLive, setFollowLive] = useState(true);
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

  const posts = detail?.posts ?? [];
  const newestPost = posts.at(-1);
  const currentRound = posts.reduce((highest, post) => Math.max(highest, post.round_number), 0);
  const totalRounds = detail?.execution.rounds ?? 0;
  const expectedTurns = totalRounds * (detail?.agents.length ?? 0);
  const turnProgress = expectedTurns ? Math.min((posts.length / expectedTurns) * 100, 100) : 0;
  const allRevealed = posts.length > 0 && posts.every((post) => revealed.has(post.event_id));

  const toggleAll = () => {
    if (allRevealed) {
      setRevealed(new Set());
      return;
    }
    setRevealed(new Set(posts.filter((post) => soliloquies.has(post.event_id)).map((post) => post.event_id)));
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
            {runs.length === 0 && <option value="">No runs found</option>}
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

        <div className={`connection-state ${connected ? "connected" : "disconnected"}`}>
          <span aria-hidden="true" />
          {connected ? "Observer connected" : "Observer offline"}
        </div>
      </header>

      <section className="run-strip">
        <div className="run-title">
          <span className={`run-state ${detail?.status === "running" ? "is-live" : ""}`}>
            {detail?.status === "running" ? "Live experiment" : detail?.status ?? "Standby"}
          </span>
          <h1>{detail?.experiment.name ?? "Waiting for a run"}</h1>
          <p>{detail ? `${detail.execution.schedule ?? "unknown"} schedule · started ${formatRunTime(detail.created_at)}` : "Start a Thoughtstage run to populate the observer."}</p>
        </div>
        <div className="run-metrics">
          <div><strong>{String(currentRound).padStart(2, "0")}</strong><span>/ {String(totalRounds).padStart(2, "0")} rounds</span></div>
          <div><strong>{posts.length}</strong><span>/ {expectedTurns || "—"} turns</span></div>
          <div><strong>{detail?.soliloquies.length ?? 0}</strong><span>private</span></div>
        </div>
        <div className="progress-track" aria-label={`${Math.round(turnProgress)} percent complete`}>
          <span style={{ width: `${turnProgress}%` }} />
        </div>
      </section>

      {error && <div className="observer-error">{error}</div>}

      <div className="observer-layout">
        <section className="feed-column" aria-label="Public conversation">
          <div className="column-toolbar">
            <div><span>Public channel</span><strong>Conversation feed</strong></div>
            <div className="toolbar-actions">
              <button type="button" className={followLive ? "active" : ""} onClick={() => setFollowLive(!followLive)}>
                {followLive ? "Following live" : "Follow live"}
              </button>
              <button type="button" onClick={toggleAll} disabled={posts.length === 0}>
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
              posts.map((post) => (
                <PostCard
                  key={post.event_id}
                  post={post}
                  soliloquy={soliloquies.get(post.event_id)}
                  agent={agents.get(post.agent_id)}
                  color={colors.get(post.agent_id) ?? AGENT_COLORS[0]}
                  revealed={revealed.has(post.event_id)}
                  newest={post.event_id === newestPost?.event_id && detail?.status === "running"}
                  onToggle={() => {
                    setRevealed((current) => {
                      const next = new Set(current);
                      if (next.has(post.event_id)) next.delete(post.event_id);
                      else next.add(post.event_id);
                      return next;
                    });
                  }}
                />
              ))
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
              const agentPosts = posts.filter((post) => post.agent_id === agent.id);
              const last = agentPosts.at(-1);
              const active = newestPost?.agent_id === agent.id && detail?.status === "running";
              const color = colors.get(agent.id) ?? AGENT_COLORS[0];
              return (
                <article className={`agent-card ${active ? "active" : ""}`} key={agent.id} style={{ "--agent": color } as React.CSSProperties}>
                  <span className="rail-avatar">{agent.display_name.charAt(0).toUpperCase()}</span>
                  <div className="agent-identity">
                    <strong>{agent.display_name}</strong>
                    <small>{shortModel(agent.model)}</small>
                  </div>
                  <div className="agent-count"><strong>{agentPosts.length}</strong><small>turns</small></div>
                  <div className="agent-status">
                    <span>{active ? "On stage" : last ? `Last seen R${last.round_number}` : "Waiting"}</span>
                  </div>
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
    </main>
  );
}

export default LiveObserver;
