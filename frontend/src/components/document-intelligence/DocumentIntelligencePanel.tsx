import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CustomFieldEditor } from "./CustomFieldEditor";
import { FieldChecklist } from "./FieldChecklist";
import { ModelSelector } from "./ModelSelector";
import {
  CUSTOM_MODEL_KEY,
  type DocumentIntelligenceCustomField,
  type DocumentIntelligenceModelSummary,
  type DocumentIntelligencePanelValue,
} from "./types";

type DocumentIntelligencePanelProps = {
  value: DocumentIntelligencePanelValue;
  onChange: (next: DocumentIntelligencePanelValue) => void;
  disabled?: boolean;
};

export function DocumentIntelligencePanel({
  value,
  onChange,
  disabled,
}: DocumentIntelligencePanelProps) {
  const [models, setModels] = useState<DocumentIntelligenceModelSummary[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [modelKey, setModelKey] = useState("");
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set());
  const [customRows, setCustomRows] = useState<DocumentIntelligenceCustomField[]>([]);
  const [saveForReuse, setSaveForReuse] = useState(false);
  const [schemaName, setSchemaName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!value.enabled || models.length > 0) return;
    let cancelled = false;
    setLoadingModels(true);
    setModelsError(null);
    fetch("/api/document-intelligence/models", { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load models (${res.status})`);
        return res.json();
      })
      .then((body: { items: DocumentIntelligenceModelSummary[] }) => {
        if (!cancelled) setModels(body.items || []);
      })
      .catch((err) => {
        if (!cancelled) setModelsError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
  }, [value.enabled, models.length]);

  const activeModel = useMemo(
    () => models.find((model) => model.model_key === modelKey) || null,
    [models, modelKey],
  );

  useEffect(() => {
    if (!value.enabled) return;
    let payload: DocumentIntelligencePanelValue["payload"] = null;
    if (modelKey && modelKey !== CUSTOM_MODEL_KEY) {
      payload = {
        enabled: true,
        model_id: modelKey,
        selected_fields: Array.from(selectedFields),
        custom_fields: null,
      };
    } else if (modelKey === CUSTOM_MODEL_KEY && customRows.length > 0) {
      payload = {
        enabled: true,
        model_id: null,
        selected_fields: null,
        custom_fields: customRows.filter((row) => row.name.trim() && row.label.trim()),
      };
    }
    onChange({ enabled: true, payload });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.enabled, modelKey, selectedFields, customRows]);

  function handleTopToggle(checked: boolean) {
    if (!checked) {
      setModelKey("");
      setSelectedFields(new Set());
      setCustomRows([]);
      onChange({ enabled: false, payload: null });
      return;
    }
    onChange({ enabled: true, payload: null });
  }

  function handleModelChange(nextKey: string) {
    setModelKey(nextKey);
    if (nextKey === CUSTOM_MODEL_KEY) {
      setSelectedFields(new Set());
      if (customRows.length === 0) setCustomRows([{ name: "", label: "", field_type: "string" }]);
    } else {
      const model = models.find((m) => m.model_key === nextKey);
      setSelectedFields(
        new Set((model?.fields || []).filter((f) => f.default_selected).map((f) => f.name)),
      );
    }
  }

  async function saveSchema() {
    if (!schemaName.trim()) {
      setSaveError("Give this schema a name first.");
      return;
    }
    const fields = customRows.filter((row) => row.name.trim() && row.label.trim());
    if (fields.length === 0) {
      setSaveError("Add at least one field first.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const response = await fetch("/api/document-intelligence/models", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: schemaName.trim().toLowerCase().replace(/\s+/g, "-"),
          name: schemaName.trim(),
          fields,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || body.message || "Could not save schema");
      }
      const created = body as DocumentIntelligenceModelSummary;
      setModels((prev) => [...prev, created]);
      setModelKey(created.model_key);
      setSelectedFields(new Set(created.fields.map((f) => f.name)));
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        <Checkbox
          id="di-enabled"
          checked={value.enabled}
          onCheckedChange={(checked) => handleTopToggle(checked === true)}
          disabled={disabled}
        />
        <Label htmlFor="di-enabled" className="font-medium text-foreground">
          Extract structured fields
        </Label>
      </div>

      {value.enabled ? (
        <div className="space-y-3 pl-6">
          <ModelSelector
            models={models}
            loading={loadingModels}
            error={modelsError}
            value={modelKey}
            onChange={handleModelChange}
            disabled={disabled}
          />

          {modelKey && modelKey !== CUSTOM_MODEL_KEY && activeModel ? (
            <FieldChecklist
              fields={activeModel.fields}
              selected={selectedFields}
              onChange={setSelectedFields}
              disabled={disabled}
            />
          ) : null}

          {modelKey === CUSTOM_MODEL_KEY ? (
            <div className="space-y-3">
              <CustomFieldEditor
                rows={customRows}
                onChange={setCustomRows}
                saveForReuse={saveForReuse}
                onSaveForReuseChange={setSaveForReuse}
                disabled={disabled || saving}
              />
              {saveForReuse ? (
                <div className="space-y-2 rounded-lg border border-border p-3">
                  <Label htmlFor="di-schema-name">Schema name</Label>
                  <Input
                    id="di-schema-name"
                    value={schemaName}
                    onChange={(e) => setSchemaName(e.target.value)}
                    placeholder="e.g. Invoice"
                    disabled={disabled || saving}
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void saveSchema()}
                    disabled={disabled || saving}
                  >
                    {saving ? "Saving…" : "Save schema"}
                  </Button>
                  {saveError ? <p className="text-xs text-danger">{saveError}</p> : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
