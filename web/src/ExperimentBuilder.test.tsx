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

describe("ExperimentBuilder", () => {
  it("enables Launch for mock-only drafts after environment probe succeeds", async () => {
    stubBuilderApis({ ok: true, required: [], missing: [] });
    render(<ExperimentBuilder />);

    continueFrom("Research question");
    fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
    continueFrom("Participants");
    continueFrom("Interaction");
    continueFrom("Materials");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
    });
    expect(screen.queryByText(/Launch is blocked/)).not.toBeInTheDocument();
  });

  it("disables Launch and lists missing Foundry env names from the probe", async () => {
    stubBuilderApis({
      ok: false,
      required: ["AZURE_FOUNDRY_ENDPOINT"],
      missing: ["AZURE_FOUNDRY_ENDPOINT"],
    });
    render(<ExperimentBuilder />);

    continueFrom("Research question");
    fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "azure_foundry" } });
    continueFrom("Participants");
    continueFrom("Interaction");
    continueFrom("Materials");

    await waitFor(() => {
      expect(screen.getByText(/Missing AZURE_FOUNDRY_ENDPOINT/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Launch is blocked until these are set: AZURE_FOUNDRY_ENDPOINT/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeDisabled();
  });
});
