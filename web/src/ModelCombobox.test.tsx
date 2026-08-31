import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ModelCombobox from "./ModelCombobox";

afterEach(() => {
  cleanup();
});

const foundryModels = [
  { value: "gpt-4o", label: "gpt-4o" },
  { value: "Llama-3.3-70B-Instruct", label: "Llama-3.3-70B-Instruct" },
  { value: "grok-4-1-fast-reasoning", label: "grok-4-1-fast-reasoning" },
];

describe("ModelCombobox", () => {
  it("opens the full list while the field already matches an option", () => {
    render(
      <ModelCombobox
        value="gpt-4o"
        options={foundryModels}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /show model list/i }));

    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /gpt-4o/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Llama-3.3-70B-Instruct/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /grok-4-1-fast-reasoning/i })).toBeInTheDocument();
  });

  it("selects another model without clearing the field first", () => {
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="gpt-4o"
        options={foundryModels}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /show model list/i }));
    fireEvent.click(screen.getByRole("option", { name: /Llama-3.3-70B-Instruct/i }));

    expect(onChange).toHaveBeenCalledWith("Llama-3.3-70B-Instruct");
  });

  it("keeps typing available when the catalog is empty or failed", () => {
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value=""
        options={[]}
        error="Could not list Foundry deployments. Set AZURE_FOUNDRY_ENDPOINT in the thoughtstage serve process."
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /show model list/i }));
    expect(screen.getByText(/Could not list Foundry deployments/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "custom-deployment" } });
    expect(onChange).toHaveBeenCalledWith("custom-deployment");
  });
});
