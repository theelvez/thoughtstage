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

function stubBuilderApis(readiness: { ok: boolean; required: string[]; missing: string[] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "");
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

function walkToReview(provider?: "azure_foundry" | "openai_compatible") {
  render(<ExperimentBuilder />);
  continueFrom("Research question");
  fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
  if (provider) {
    fireEvent.change(screen.getByRole("combobox"), { target: { value: provider } });
  }
  continueFrom("Participants");
  continueFrom("Interaction");
  continueFrom("Materials");
}

describe("ExperimentBuilder", () => {
  it("enables Launch for mock-only drafts after environment probe succeeds", async () => {
    stubBuilderApis({ ok: true, required: [], missing: [] });
    walkToReview();

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
    walkToReview("azure_foundry");

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
    walkToReview("openai_compatible");

    await waitFor(() => {
      expect(screen.getByText(/Selected providers are ready/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/OPENAI_BASE_URL — unset/)).toBeInTheDocument();
    expect(screen.getByText(/OPENAI_API_KEY — unset/)).toBeInTheDocument();
    expect(screen.getByText(/as the adapter does/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
    expect(document.body.textContent).not.toContain("sk-");
  });
});
