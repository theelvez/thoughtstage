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

function seedStripNote(seed: number | undefined, agents: Agent[] | undefined) {
  if (seed === undefined) return "";
  const hosted = (agents ?? []).some((agent) => agent.provider !== "mock");
  return hosted
    ? ` · seed ${seed} (does not control hosted decoding)`
    : ` · seed ${seed}`;
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
          <span className="agent-avatar">{stimulus ? "\u25c6" : post.display_name.charAt(0).toUpperCase()}</span>
          <span className="post-byline">
            <strong>{post.display_name}</strong>
            <small>{stimulus ? "scripted public stimulus" : agent ? shortModel(agent.model) : "participant"}</small>
          </span>
          <span className="post-index">
            Round {String(post.round_number).padStart(2, "0")} \u00b7 #{String(post.sequence).padStart(2, "0")}
          </span>
          <button
            className={`moment-annotation ${publicAnnotation ? "annotated" : ""}`}
            type="button"
            onClick={onAnnotatePublic}
            title={publicAnnotation ? "Edit researcher annotation" : "Bookmark or annotate this public event"}
          >\u2605</button>
        </header>

        <p className="post-content">{post.content}</p>

        {stimulus ? (
          <div className="stimulus-note">Declared in the experiment manifest \u00b7 visible to every participant</div>
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
            {soliloquy && <span aria-hidden="true">{revealed ? "\u2212" : "+"}</span>}
          </button>
        )}

        {revealed && soliloquy && (
          <section className="soliloquy-panel" aria-label={`${post.display_name} private soliloquy`}>
            <div className="soliloquy-label">
              <span>Researcher channel</span>
              <span>Private \u00b7 same agent</span>
            </div>
            <button
              className={`soliloquy-annotation ${privateAnnotation ? "annotated" : ""}`}
              type="button"
              onClick={onAnnotatePrivate}
            >
              \u2605 {privateAnnotation ? "Edit annotation" : "Annotate soliloquy"}
            </button>
            <p>{soliloquy.content}</p>
          </section>
        )}
      </div>
    </article>
  );
}
