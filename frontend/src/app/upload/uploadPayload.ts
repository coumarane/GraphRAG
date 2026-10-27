import type { DocumentIntelligencePanelValue } from "@/components/document-intelligence/types";

export function buildUploadSessionBody(
  file: File,
  title: string,
  di: DocumentIntelligencePanelValue,
): { filename: string; byte_size: number; title?: string; document_intelligence?: DocumentIntelligencePanelValue["payload"] } {
  const body: {
    filename: string;
    byte_size: number;
    title?: string;
    document_intelligence?: DocumentIntelligencePanelValue["payload"];
  } = {
    filename: file.name,
    byte_size: file.size,
  };
  if (title.trim()) body.title = title.trim();
  if (di.enabled && di.payload) body.document_intelligence = di.payload;
  return body;
}

export function directPutHeaders(
  upload: { headers?: Record<string, unknown> } | null | undefined,
): Record<string, string> {
  const headers = upload?.headers;
  if (!headers) return {};
  const resolved: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    if (typeof value === "string" && value.length > 0) resolved[key] = value;
  }
  return resolved;
}

export function buildIngestFormData(
  file: File,
  title: string,
  di: DocumentIntelligencePanelValue,
): FormData {
  const form = new FormData();
  form.append("file", file);
  if (title.trim()) form.append("title", title.trim());
  form.append("parser_requested", "auto");
  if (di.enabled && di.payload) {
    form.append("document_intelligence", JSON.stringify(di.payload));
  }
  return form;
}
