import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CUSTOM_MODEL_KEY, type DocumentIntelligenceModelSummary } from "./types";

type ModelSelectorProps = {
  models: DocumentIntelligenceModelSummary[];
  loading: boolean;
  error: string | null;
  value: string;
  onChange: (modelKey: string) => void;
  disabled?: boolean;
};

export function ModelSelector({
  models,
  loading,
  error,
  value,
  onChange,
  disabled,
}: ModelSelectorProps) {
  return (
    <div className="space-y-1">
      <Select value={value} onValueChange={onChange} disabled={disabled || loading}>
        <SelectTrigger aria-label="Extraction model">
          <SelectValue placeholder={loading ? "Loading models…" : "Choose a model"} />
        </SelectTrigger>
        <SelectContent>
          {models.map((model) => (
            <SelectItem key={model.model_key} value={model.model_key}>
              {model.name}
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM_MODEL_KEY}>Custom fields…</SelectItem>
        </SelectContent>
      </Select>
      {error ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}
