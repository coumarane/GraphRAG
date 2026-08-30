import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentIntelligencePanel } from "./DocumentIntelligencePanel";
import type { DocumentIntelligencePanelValue } from "./types";

const MODELS = {
  items: [
    {
      model_key: "sds",
      model_id: null,
      name: "Safety Data Sheet",
      model_type: "prebuilt",
      is_builtin: true,
      fields: [
        { name: "product_name", label: "Product name", field_type: "string", default_selected: true },
        { name: "manufacturer", label: "Manufacturer", field_type: "string", default_selected: true },
        { name: "cas_number", label: "CAS number", field_type: "string", default_selected: false },
      ],
    },
    {
      model_key: "invoice",
      model_id: "11111111-1111-1111-1111-111111111111",
      name: "Invoice",
      model_type: "custom",
      is_builtin: false,
      fields: [
        { name: "invoice_number", label: "Invoice number", field_type: "string", default_selected: true },
      ],
    },
  ],
};

function Harness() {
  const [value, setValue] = useState<DocumentIntelligencePanelValue>({
    enabled: false,
    payload: null,
  });
  return <DocumentIntelligencePanel value={value} onChange={setValue} />;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.toString().includes("/api/document-intelligence/models")) {
        return new Response(JSON.stringify(MODELS), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentIntelligencePanel", () => {
  it("is unchecked by default and hides the model selector", () => {
    render(<Harness />);
    const toggle = screen.getByRole("checkbox", { name: /extract structured fields/i });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByLabelText(/extraction model/i)).not.toBeInTheDocument();
  });

  it("reveals the model selector when the top checkbox is checked", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("checkbox", { name: /extract structured fields/i }));
    await waitFor(() => expect(screen.getByLabelText(/extraction model/i)).toBeInTheDocument());
  });

  it("selecting a model populates the checked set from default_selected fields", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("checkbox", { name: /extract structured fields/i }));
    await waitFor(() => expect(screen.getByLabelText(/extraction model/i)).toBeInTheDocument());

    await user.click(screen.getByLabelText(/extraction model/i));
    await user.click(await screen.findByText("Safety Data Sheet"));

    const productName = await screen.findByLabelText("Product name");
    const manufacturer = screen.getByLabelText("Manufacturer");
    const casNumber = screen.getByLabelText("CAS number");
    expect(productName).toBeChecked();
    expect(manufacturer).toBeChecked();
    expect(casNumber).not.toBeChecked();
  });

  it("Select all / Clear all / Recommended behave correctly", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("checkbox", { name: /extract structured fields/i }));
    await user.click(await screen.findByLabelText(/extraction model/i));
    await user.click(await screen.findByText("Safety Data Sheet"));
    await screen.findByLabelText("Product name");

    await user.click(screen.getByRole("button", { name: /select all/i }));
    expect(screen.getByLabelText("CAS number")).toBeChecked();

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    expect(screen.getByLabelText("Product name")).not.toBeChecked();
    expect(screen.getByLabelText("CAS number")).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: /recommended/i }));
    expect(screen.getByLabelText("Product name")).toBeChecked();
    expect(screen.getByLabelText("Manufacturer")).toBeChecked();
    expect(screen.getByLabelText("CAS number")).not.toBeChecked();
  });

  it("selecting the custom option swaps in the custom field editor", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("checkbox", { name: /extract structured fields/i }));
    await user.click(await screen.findByLabelText(/extraction model/i));
    await user.click(await screen.findByText("Custom fields…"));

    expect(await screen.findByPlaceholderText("field_name")).toBeInTheDocument();
    expect(screen.queryByLabelText("Product name")).not.toBeInTheDocument();
  });
});
