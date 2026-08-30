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

type ProviderEnvReport = {
  ready: boolean;
  missing: string[];
  variables: Array<{
    name: string;
    required: boolean;
    present: boolean;
    detail: string;
  }>;
};

function stubReviewApis(verify: ProviderEnvReport) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/experiments/preview")) {
        return jsonResponse({
          valid: true,
          experiment_id: "untitled-experiment",
          yaml: "id: untitled-experiment\n",
          artifacts: ["experiment.yaml"],
        });
      }
      if (url.includes("/api/experiments/verify-providers")) {
        return jsonResponse(verify);
      }
      return jsonResponse({ detail: "unexpected" }, 500);
    }),
  );
}

function continueStep() {
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
}

async function goToReview(provider?: "azure_foundry" | "openai_compatible") {
  render(<ExperimentBuilder />);
  continueStep();
  fireEvent.click(screen.getByRole("button", { name: /manually add participants/i }));
  if (provider) {
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: provider } });
  }
  continueStep();
  continueStep();
  continueStep();
}

describe("ExperimentBuilder review verify", () => {
  it("lets mock launch without environment variables", async () => {
    stubReviewApis({ ready: true, missing: [], variables: [] });
    await goToReview();

    await waitFor(() => {
      expect(screen.getByText("Mock needs no environment variables. Launch is ready.")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
  });

  it("blocks launch with a missing-env list for paid providers", async () => {
    stubReviewApis({
      ready: false,
      missing: ["AZURE_FOUNDRY_ENDPOINT"],
      variables: [
        {
          name: "AZURE_FOUNDRY_ENDPOINT",
          required: true,
          present: false,
          detail: "Full Foundry resource URL. Microsoft Entra is the default.",
        },
      ],
    });
    await goToReview("azure_foundry");

    await waitFor(() => {
      expect(screen.getByText(/Launch is blocked/i)).toBeInTheDocument();
    });
    expect(screen.getByText("Missing: AZURE_FOUNDRY_ENDPOINT")).toBeInTheDocument();
    expect(screen.getByText(/AZURE_FOUNDRY_ENDPOINT — missing/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeDisabled();
    expect(document.body.textContent).not.toContain("sk-");
    expect(document.body.textContent).not.toContain("secret-value");
  });

  it("shows openai_compatible adapter env names without blocking local defaults", async () => {
    stubReviewApis({
      ready: true,
      missing: [],
      variables: [
        {
          name: "OPENAI_API_KEY",
          required: false,
          present: false,
          detail: "Used for hosted Chat Completions endpoints. Local servers can omit this.",
        },
        {
          name: "OPENAI_BASE_URL",
          required: false,
          present: false,
          detail: "Chat Completions base such as https://api.openai.com/v1 or https://api.x.ai/v1. Local Ollama can omit this.",
        },
      ],
    });
    await goToReview("openai_compatible");

    await waitFor(() => {
      expect(screen.getByText(/Selected providers are ready/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/OPENAI_BASE_URL — unset/)).toBeInTheDocument();
    expect(screen.getByText(/OPENAI_API_KEY — unset/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create, validate & launch/i })).toBeEnabled();
    expect(document.body.textContent).not.toContain("sk-");
  });
});
