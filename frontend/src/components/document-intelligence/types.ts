export const FIELD_TYPES = [
  "string",
  "number",
  "integer",
  "boolean",
  "date",
  "currency",
  "percentage",
  "list",
  "object",
  "table",
] as const;

export type FieldType = (typeof FIELD_TYPES)[number];

export type ModelFieldSummary = {
  name: string;
  label: string;
  field_type: FieldType;
  default_selected: boolean;
};

export type DocumentIntelligenceModelSummary = {
  model_key: string;
  model_id: string | null;
  name: string;
  model_type: string;
  is_builtin: boolean;
  fields: ModelFieldSummary[];
};

// The synthetic client-only dropdown option for ad-hoc fields with no persisted model.
export const CUSTOM_MODEL_KEY = "custom";

export type DocumentIntelligenceCustomField = {
  name: string;
  label: string;
  field_type: FieldType;
  default_selected?: boolean;
};

/** Mirrors backend `DocumentIntelligenceIngestOptions` field-for-field (extra="forbid" server-side). */
export type DocumentIntelligencePayload = {
  enabled: boolean;
  model_id: string | null;
  selected_fields: string[] | null;
  custom_fields: DocumentIntelligenceCustomField[] | null;
};

export type DocumentIntelligencePanelValue = {
  enabled: boolean;
  payload: DocumentIntelligencePayload | null;
};

export type ExtractedFieldItem = {
  name: string;
  value: unknown;
  confidence: number;
  confidence_band: string;
  page?: number | null;
  source_text?: string | null;
};

export type DocumentExtractionRunItem = {
  run_id: string;
  status: string;
  model_key: string | null;
  fields: ExtractedFieldItem[];
};
