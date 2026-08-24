import type { DocumentIntelligencePanelValue } from "@/components/document-intelligence/types";

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
