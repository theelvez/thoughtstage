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
