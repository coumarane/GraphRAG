import { describe, expect, it } from "vitest";
import { buildIngestFormData } from "./uploadPayload";

function keys(form: FormData): string[] {
  return Array.from(form.keys()).sort();
}

const file = new File(["hello"], "hello.pdf", { type: "application/pdf" });

describe("buildIngestFormData", () => {
  it("produces the byte-identical unchecked-path FormData with no title", () => {
    const form = buildIngestFormData(file, "", { enabled: false, payload: null });
    expect(keys(form)).toEqual(["file", "parser_requested"]);
    expect(form.get("parser_requested")).toBe("auto");
  });

  it("includes title when non-empty, still no document_intelligence key when disabled", () => {
    const form = buildIngestFormData(file, "My Title", { enabled: false, payload: null });
    expect(keys(form)).toEqual(["file", "parser_requested", "title"]);
    expect(form.get("title")).toBe("My Title");
  });

  it("appends document_intelligence with the exact payload shape when enabled", () => {
    const payload = {
      enabled: true,
      model_id: "sds",
      selected_fields: ["product_name"],
      custom_fields: null,
    };
    const form = buildIngestFormData(file, "", { enabled: true, payload });
    expect(keys(form)).toEqual(["document_intelligence", "file", "parser_requested"]);
    expect(JSON.parse(form.get("document_intelligence") as string)).toEqual(payload);
  });

  it("never appends document_intelligence when enabled is true but payload is null", () => {
    const form = buildIngestFormData(file, "", { enabled: true, payload: null });
    expect(keys(form)).toEqual(["file", "parser_requested"]);
  });
});
