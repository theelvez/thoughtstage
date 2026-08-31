import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ExperimentBuilder from "./ExperimentBuilder";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

function catalogFor(path: string) {
  const query = new URLSearchParams(path.split("?")[1] ?? "");
  const provider = query.get("provider") ?? "mock";
  if (provider === "azure_foundry") {
    return {
      ok: true,
      source: "endpoint",
      models: [
        { id: "gpt-4o", label: "gpt-4o" },
        { id: "Llama-3.3-70B-Instruct", label: "Llama-3.3-70B-Instruct" },
        { id: "grok-4-1-fast-reasoning", label: "grok-4-1-fast-reasoning" },
      ],
      error: null,
      missing: [],
    };
  }
  if (provider === "openai_compatible") {
    return {
      ok: true,
      source: "endpoint",
      models: [{ id: "llama3.2", label: "llama3.2" }],
      error: null,
      missing: [],
    };
  }
  return {
    ok: true,
    source: "builtin",
    models: [
      { id: "deterministic-mock", label: "Deterministic mock · recommended" },
      { id: "deterministic-v1", label: "Deterministic mock · legacy example ID" },
    ],
    error: null,
    missing: [],
  };
}

function stubBuilderApis(readiness: { ok: boolean; required: string[]; missing: string[] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      if (path.startsWith("/api/provider-models")) {
        return jsonResponse(catalogFor(path));
      }
      if (path === "/api/experiments/preview" || path.endsWith("/api/experiments/preview")) {
        return jsonResponse({
          valid: true,
          experiment_id: "untitled-experiment",
          yaml: "id: untitled-experiment\n",
          artifacts: ["experiment.yaml"],
        });
      }
      if (path.includes("provider-readiness")) {
        return jsonResponse(readiness);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

function continueFrom(stepHeading: string) {
  expect(screen.getByRole("heading", { name: stepHeading })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
}

async function walkToReview(provider?: "azure_foundry" | "openai_compatible") {
  render(<ExperimentBuilder />);
  continueFrom("Research question");
  fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
  if (provider) {
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: provider } });
    await waitFor(() => {
      expect(screen.getByLabelText("Model or deployment")).not.toHaveValue("");
    });
  }
  continueFrom("Participants");
  continueFrom("Interaction");
  continueFrom("Materials");
}

describe("ExperimentBuilder", () => {
  it("enables Launch for mock-only drafts after environment probe succeeds", async () => {
    stubBuilderApis({ ok: true, required: [], missing: [] });
    await walkToReview();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
    });
    expect(screen.getByText("Mock needs no environment variables. Launch is ready.")).toBeInTheDocument();
    expect(screen.queryByText(/Launch is blocked/)).not.toBeInTheDocument();
  });

  it("disables Launch and lists missing Foundry env names from the probe", async () => {
    stubBuilderApis({
      ok: false,
      required: ["AZURE_FOUNDRY_ENDPOINT"],
      missing: ["AZURE_FOUNDRY_ENDPOINT"],
    });
    await walkToReview("azure_foundry");

    await waitFor(() => {
      expect(screen.getByText(/Missing AZURE_FOUNDRY_ENDPOINT/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Launch is blocked until these are set: AZURE_FOUNDRY_ENDPOINT/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeDisabled();
    expect(document.body.textContent).not.toContain("sk-");
    expect(document.body.textContent).not.toContain("secret-value");
  });

  it("shows openai_compatible adapter env names without blocking local defaults", async () => {
    stubBuilderApis({ ok: true, required: [], missing: [] });
    await walkToReview("openai_compatible");

    await waitFor(() => {
      expect(screen.getByText(/Selected providers are ready/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/OPENAI_BASE_URL — unset/)).toBeInTheDocument();
    expect(screen.getByText(/OPENAI_API_KEY — unset/)).toBeInTheDocument();
    expect(screen.getByText(/as the adapter does/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
    expect(document.body.textContent).not.toContain("sk-");
  });

  it("keeps the Foundry model list open after provider auto-suggest fills the field", async () => {
    stubBuilderApis({ ok: true, required: ["AZURE_FOUNDRY_ENDPOINT"], missing: [] });
    render(<ExperimentBuilder />);
    continueFrom("Research question");
    fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "azure_foundry" } });

    await waitFor(() => {
      expect(screen.getByLabelText("Model or deployment")).toHaveValue("gpt-4o");
    });

    fireEvent.click(screen.getByRole("button", { name: /show model list/i }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Llama-3.3-70B-Instruct/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /grok-4-1-fast-reasoning/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("option", { name: /Llama-3.3-70B-Instruct/i }));
    expect(screen.getByLabelText("Model or deployment")).toHaveValue("Llama-3.3-70B-Instruct");
    expect(document.body.textContent).not.toContain("sk-");
  });
});
