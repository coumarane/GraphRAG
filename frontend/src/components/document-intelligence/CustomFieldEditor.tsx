import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FIELD_TYPES, type DocumentIntelligenceCustomField, type FieldType } from "./types";

type CustomFieldEditorProps = {
  rows: DocumentIntelligenceCustomField[];
  onChange: (rows: DocumentIntelligenceCustomField[]) => void;
  saveForReuse: boolean;
  onSaveForReuseChange: (checked: boolean) => void;
  disabled?: boolean;
};

function emptyRow(): DocumentIntelligenceCustomField {
  return { name: "", label: "", field_type: "string" };
}

export function CustomFieldEditor({
  rows,
  onChange,
  saveForReuse,
  onSaveForReuseChange,
  disabled,
}: CustomFieldEditorProps) {
  function updateRow(index: number, patch: Partial<DocumentIntelligenceCustomField>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function addRow() {
    onChange([...rows, emptyRow()]);
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {rows.map((row, index) => (
          <li key={index} className="flex items-center gap-2">
            <Input
              placeholder="field_name"
              value={row.name}
              onChange={(e) => updateRow(index, { name: e.target.value })}
              disabled={disabled}
              aria-label="Field name"
              className="flex-1"
            />
            <Input
              placeholder="Label"
              value={row.label}
              onChange={(e) => updateRow(index, { label: e.target.value })}
              disabled={disabled}
              aria-label="Field label"
              className="flex-1"
            />
            <Select
              value={row.field_type}
              onValueChange={(value) => updateRow(index, { field_type: value as FieldType })}
              disabled={disabled}
            >
              <SelectTrigger aria-label="Field type" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FIELD_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <button
              type="button"
              aria-label="Remove field"
              className="rounded-md p-1.5 text-muted hover:bg-surface-elevated hover:text-foreground"
              onClick={() => removeRow(index)}
              disabled={disabled}
            >
              <X className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>
      <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={disabled}>
        Add field
      </Button>
      <div className="flex items-center gap-2 border-t border-border pt-3">
        <Checkbox
          id="di-save-for-reuse"
          checked={saveForReuse}
          onCheckedChange={(checked) => onSaveForReuseChange(checked === true)}
          disabled={disabled}
        />
        <Label htmlFor="di-save-for-reuse" className="font-normal text-foreground">
          Save this schema for reuse
        </Label>
      </div>
    </div>
  );
}
