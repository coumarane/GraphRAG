import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { ModelFieldSummary } from "./types";

type FieldChecklistProps = {
  fields: ModelFieldSummary[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  disabled?: boolean;
};

export function FieldChecklist({ fields, selected, onChange, disabled }: FieldChecklistProps) {
  function toggle(name: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) next.add(name);
    else next.delete(name);
    onChange(next);
  }

  function selectAll() {
    onChange(new Set(fields.map((field) => field.name)));
  }

  function clearAll() {
    onChange(new Set());
  }

  function recommended() {
    onChange(new Set(fields.filter((field) => field.default_selected).map((field) => field.name)));
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Button type="button" variant="outline" size="sm" onClick={selectAll} disabled={disabled}>
          Select all
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={clearAll} disabled={disabled}>
          Clear all
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={recommended} disabled={disabled}>
          Recommended
        </Button>
      </div>
      <ul className="space-y-1.5">
        {fields.map((field) => {
          const id = `di-field-${field.name}`;
          return (
            <li key={field.name} className="flex items-center gap-2">
              <Checkbox
                id={id}
                checked={selected.has(field.name)}
                onCheckedChange={(checked) => toggle(field.name, checked === true)}
                disabled={disabled}
              />
              <Label htmlFor={id} className="font-normal text-foreground">
                {field.label}
              </Label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
