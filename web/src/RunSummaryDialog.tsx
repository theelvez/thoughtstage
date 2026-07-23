import { useEffect, useMemo } from "react";
import "./run-summary.css";

type SummaryAgent = {
  id: string;
  display_name: string;
  provider: string;
  model: string;
};

type SummaryPublicEvent = {
  event_type?: "post" | "stimulus";
  agent_id?: string;
  display_name: string;
  round_number: number;
  content: string;
};

type TokenTotals = {
  model_calls?: number;
  input_tokens?: number;
  cached_input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
};

export type SummaryRunDetail = {
  run_id: string;
  status: string;
  created_at: string | null;
  completed_at: string | null;
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
  agents: SummaryAgent[];
  counts: {
    public_posts: number;
    public_stimuli: number;
    soliloquies: number;
    model_calls: number;
    file_tool_calls: number;
  };
  posts: SummaryPublicEvent[];
  usage_summary: {
    totals: TokenTotals;
    by_agent?: Record<string, TokenTotals>;
  };
};

function formatNumber(value: number | undefined) {
  return new Intl.NumberFormat().format(value ?? 0);
}

function formatDate(value: string | null) {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatDuration(start: string | null, end: string | null) {
  if (!start || !end) return "Unavailable";
  const seconds = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1_000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function tableCell(value: string) {
  return value.replaceAll("|", "\\|").replaceAll("\n", " ");
}

function finalPosts(detail: SummaryRunDetail) {
  return detail.agents.flatMap((agent) => {
    const post = detail.posts
      .filter((event) => event.event_type !== "stimulus" && event.agent_id === agent.id)
      .at(-1);
    return post ? [{ agent, post }] : [];
  });
}

function summaryMarkdown(detail: SummaryRunDetail) {
  const totals = detail.usage_summary.totals;
  const final = finalPosts(detail);
  const lines = [
    `# ${detail.experiment.name ?? detail.run_id}`,
    "",
    "## Run",
    "",
    `- Run ID: \`${detail.run_id}\``,
    `- Status: ${detail.status}`,
    `- Started: ${formatDate(detail.created_at)}`,
    `- Completed: ${formatDate(detail.completed_at)}`,
    `- Duration: ${formatDuration(detail.created_at, detail.completed_at)}`,
    `- Thoughtstage: ${detail.thoughtstage?.version ?? "unknown"}`,
    `- Configuration SHA-256: \`${detail.experiment.config_sha256 ?? "unavailable"}\``,
    "",
    "## Design",
    "",
    `- Experiment ID: \`${detail.experiment.id ?? "unknown"}\``,
    `- Rounds: ${detail.execution.rounds ?? 0}`,
    `- Schedule: ${detail.execution.schedule ?? "unknown"}`,
    `- Turn order: ${detail.execution.turn_order ?? "unknown"}`,
    `- Private memory: ${detail.execution.private_memory ?? "unknown"}`,
    `- Seed: ${detail.execution.seed ?? "unknown"}`,
    `- Scheduled stimuli: ${detail.execution.scheduled_stimuli ?? detail.counts.public_stimuli}`,
    "",
    "### Shared system prompt",
    "",
    detail.experiment.system_prompt ?? "Unavailable",
    "",
    "## Output",
    "",
    `- Public posts: ${detail.counts.public_posts}`,
    `- Public stimuli: ${detail.counts.public_stimuli}`,
    `- Researcher-private soliloquies: ${detail.counts.soliloquies}`,
    `- Model calls: ${detail.counts.model_calls}`,
    `- File-tool calls: ${detail.counts.file_tool_calls}`,
    `- Input tokens: ${totals.input_tokens ?? 0}`,
    `- Output tokens: ${totals.output_tokens ?? 0}`,
    `- Total tokens: ${totals.total_tokens ?? 0}`,
    "",
    "## Participants",
    "",
    "| Participant | Provider | Model | Posts | Model calls | Total tokens |",
    "| --- | --- | --- | ---: | ---: | ---: |",
    ...detail.agents.map((agent) => {
      const usage = detail.usage_summary.by_agent?.[agent.id];
      const posts = detail.posts.filter(
        (event) => event.event_type !== "stimulus" && event.agent_id === agent.id,
      ).length;
      return `| ${tableCell(agent.display_name)} | ${tableCell(agent.provider)} | ${tableCell(agent.model)} | ${posts} | ${usage?.model_calls ?? 0} | ${usage?.total_tokens ?? 0} |`;
    }),
    "",
    "## Final public posts",
    "",
    ...final.flatMap(({ agent, post }) => [
      `### ${agent.display_name} · round ${post.round_number}`,
      "",
      post.content,
      "",
    ]),
    "---",
    "",
    "This deterministic Thoughtstage summary contains public outputs and researcher-visible run metadata. It excludes private briefings and soliloquy content.",
    "",
  ];
  return lines.join("\n");
}

function downloadSummary(detail: SummaryRunDetail) {
  const blob = new Blob([summaryMarkdown(detail)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${detail.run_id}-summary.md`;
  link.click();
  URL.revokeObjectURL(url);
}

function RunSummaryDialog({
  detail,
  onClose,
}: {
  detail: SummaryRunDetail;
  onClose: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const final = useMemo(() => finalPosts(detail), [detail]);
  const totals = detail.usage_summary.totals;

  return (
    <div className="summary-backdrop" onMouseDown={onClose}>
      <section
        className="summary-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="summary-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="summary-header">
          <div>
            <span>Deterministic research record</span>
            <h2 id="summary-title">Experiment results summary</h2>
            <p>{detail.experiment.name ?? detail.run_id}</p>
          </div>
          <div className="summary-header-actions">
            <button type="button" onClick={() => downloadSummary(detail)}>Download Markdown</button>
            <button type="button" className="summary-close" onClick={onClose} aria-label="Close results summary">×</button>
          </div>
        </header>

        <div className="summary-status">
          <div><span>Status</span><strong>{detail.status}</strong></div>
          <div><span>Duration</span><strong>{formatDuration(detail.created_at, detail.completed_at)}</strong></div>
          <div><span>Participants</span><strong>{detail.agents.length}</strong></div>
          <div><span>Rounds</span><strong>{detail.execution.rounds ?? 0}</strong></div>
          <div><span>Public posts</span><strong>{detail.counts.public_posts}</strong></div>
          <div><span>Total tokens</span><strong>{formatNumber(totals.total_tokens)}</strong></div>
        </div>

        <div className="summary-body">
          <section className="summary-panel summary-design">
            <span>Experimental design</span>
            <dl>
              <div><dt>Run ID</dt><dd>{detail.run_id}</dd></div>
              <div><dt>Schedule</dt><dd>{detail.execution.schedule ?? "Unknown"}</dd></div>
              <div><dt>Turn order</dt><dd>{detail.execution.turn_order ?? "Unknown"}</dd></div>
              <div><dt>Private memory</dt><dd>{detail.execution.private_memory ?? "Unknown"}</dd></div>
              <div><dt>Seed</dt><dd>{detail.execution.seed ?? "Unknown"}</dd></div>
              <div><dt>Started</dt><dd>{formatDate(detail.created_at)}</dd></div>
              <div><dt>Completed</dt><dd>{formatDate(detail.completed_at)}</dd></div>
            </dl>
          </section>

          <section className="summary-panel summary-provenance">
            <span>Provenance</span>
            <dl>
              <div><dt>Thoughtstage</dt><dd>{detail.thoughtstage?.version ?? "Unknown"}</dd></div>
              <div><dt>Source revision</dt><dd>{detail.thoughtstage?.source_revision ?? "Unavailable"}</dd></div>
              <div><dt>Config SHA-256</dt><dd>{detail.experiment.config_sha256 ?? "Unavailable"}</dd></div>
              <div><dt>Soliloquies</dt><dd>{detail.counts.soliloquies}</dd></div>
              <div><dt>Model calls</dt><dd>{detail.counts.model_calls}</dd></div>
              <div><dt>File reads</dt><dd>{detail.counts.file_tool_calls}</dd></div>
            </dl>
          </section>

          <section className="summary-panel summary-prompt">
            <span>Shared system prompt</span>
            <p>{detail.experiment.system_prompt ?? "Unavailable"}</p>
          </section>

          <section className="summary-panel summary-participants">
            <span>Participant output and usage</span>
            <div className="summary-table-wrap">
              <table>
                <thead>
                  <tr><th>Participant</th><th>Provider</th><th>Model</th><th>Posts</th><th>Calls</th><th>Tokens</th></tr>
                </thead>
                <tbody>
                  {detail.agents.map((agent) => {
                    const usage = detail.usage_summary.by_agent?.[agent.id];
                    const posts = detail.posts.filter(
                      (event) => event.event_type !== "stimulus" && event.agent_id === agent.id,
                    ).length;
                    return (
                      <tr key={agent.id}>
                        <td>{agent.display_name}</td>
                        <td>{agent.provider}</td>
                        <td>{agent.model}</td>
                        <td>{posts}</td>
                        <td>{usage?.model_calls ?? 0}</td>
                        <td>{formatNumber(usage?.total_tokens)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="summary-panel summary-final-posts">
            <span>Final public posts</span>
            {final.map(({ agent, post }) => (
              <article key={agent.id}>
                <header><strong>{agent.display_name}</strong><small>Round {post.round_number}</small></header>
                <p>{post.content}</p>
              </article>
            ))}
          </section>

          <p className="summary-boundary-note">
            This summary is computed from the immutable run bundle. Downloaded summaries exclude private briefings and soliloquy content.
          </p>
        </div>
      </section>
    </div>
  );
}

export default RunSummaryDialog;
