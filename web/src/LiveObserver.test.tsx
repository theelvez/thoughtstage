import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LiveObserver from "./LiveObserver";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

const helloStageAgents = [
  { id: "atlas", display_name: "Atlas", provider: "mock", model: "deterministic-v1" },
  { id: "ember", display_name: "Ember", provider: "mock", model: "deterministic-v1" },
  { id: "rowan", display_name: "Rowan", provider: "mock", model: "deterministic-v1" },
];

const helloStageSummary = {
  run_id: "hello-stage-demo",
  status: "completed",
  created_at: "2026-08-28T19:00:00.000Z",
  completed_at: "2026-08-28T19:00:08.000Z",
  thoughtstage: { version: "0.1.0", source_revision: null },
  experiment: {
    id: "hello-stage",
    name: "Hello, Stage",
    system_prompt:
      "You are participating in a small social research experiment.\nWork with the group to define a useful, falsifiable next step.",
    config_sha256: "0".repeat(64),
  },
  execution: {
    rounds: 2,
    schedule: "simultaneous",
    turn_order: "declared",
    private_memory: "none",
    seed: 42,
    scheduled_stimuli: 0,
  },
  agents: helloStageAgents,
  counts: {
    public_posts: 2,
    public_stimuli: 0,
    soliloquies: 2,
    model_calls: 2,
    file_tool_calls: 0,
  },
};

const helloStageDetail = {
  ...helloStageSummary,
  posts: [
    {
      event_type: "post" as const,
      event_id: "post-r0001-atlas-000001",
      sequence: 1,
      experiment_id: "hello-stage",
      round_number: 1,
      agent_id: "atlas",
      display_name: "Atlas",
      content: "Define the evidence that would change our minds before we choose the experiment.",
    },
    {
      event_type: "post" as const,
      event_id: "post-r0001-ember-000002",
      sequence: 2,
      experiment_id: "hello-stage",
      round_number: 1,
      agent_id: "ember",
      display_name: "Ember",
      content: "Name an overlooked stakeholder, not only a metric.",
    },
  ],
  stimuli: [],
  soliloquies: [
    {
      event_id: "soliloquy-r0001-atlas-000001",
      post_event_id: "post-r0001-atlas-000001",
      sequence: 1,
      experiment_id: "hello-stage",
      round_number: 1,
      agent_id: "atlas",
      content: "Keep the public post empirical; the group is converging too quickly.",
    },
  ],
  usage_summary: {
    totals: {
      model_calls: 2,
      input_tokens: 240,
      output_tokens: 80,
      total_tokens: 320,
    },
    by_agent: {
      atlas: { model_calls: 1, total_tokens: 160 },
      ember: { model_calls: 1, total_tokens: 160 },
    },
  },
  private_briefings: {},
};

function stubObserver(options: {
  runs?: typeof helloStageSummary[];
  detail?: typeof helloStageDetail | null;
}) {
  const runs = options.runs ?? [];
  const detail = options.detail ?? null;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      if (path === "/api/runs" || path.endsWith("/api/runs")) {
        return jsonResponse({ runs });
      }
      if (path.includes("/annotations")) {
        return jsonResponse({ annotations: [] });
      }
      const match = path.match(/\/api\/runs\/([^/?]+)$/);
      if (match && detail && decodeURIComponent(match[1]) === detail.run_id) {
        return jsonResponse(detail);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

describe("LiveObserver", () => {
  it("shows the empty run strip when no bundles exist", async () => {
    stubObserver({ runs: [] });
    render(<LiveObserver />);

    expect(screen.getByRole("heading", { name: "Waiting for a run" })).toBeInTheDocument();
    expect(screen.getByText("Standby")).toBeInTheDocument();
    expect(screen.getByText("The stage is quiet.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /watching/i })).toHaveDisplayValue("No runs found");

    await waitFor(() => {
      expect(screen.getByText("Observer connected")).toBeInTheDocument();
    });
  });

  it("renders a completed hello-stage run from the compose demo query", async () => {
    window.history.replaceState({}, "", "/?run=hello-stage-demo");
    stubObserver({ runs: [helloStageSummary], detail: helloStageDetail });
    render(<LiveObserver />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Hello, Stage" })).toBeInTheDocument();
    });

    const runStrip = document.querySelector(".run-strip");
    expect(runStrip).toHaveTextContent("completed");
    expect(runStrip).toHaveTextContent("seed 42");
    expect(runStrip).not.toHaveTextContent("does not control hosted decoding");
    expect(runStrip).toHaveTextContent("simultaneous schedule");

    expect(screen.getByRole("combobox", { name: /watching/i })).toHaveDisplayValue(
      "Hello, Stage · completed",
    );
    expect(screen.getByText("Define the evidence that would change our minds before we choose the experiment.")).toBeInTheDocument();
    expect(screen.getByText("Name an overlooked stakeholder, not only a metric.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open soliloquy" }));
    expect(screen.getByText("Keep the public post empirical; the group is converging too quickly.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Research workbench" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Experiment results summary" })).toBeInTheDocument();
    expect(screen.getAllByText("Atlas").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ember").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rowan").length).toBeGreaterThan(0);
    expect(screen.getByText("Observer connected")).toBeInTheDocument();
  });
});
