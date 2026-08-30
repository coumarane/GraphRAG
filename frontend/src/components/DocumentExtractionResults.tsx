"use client";

import { useCallback, useEffect, useState } from "react";
import { readTenantKey } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { DocumentExtractionRunItem } from "@/components/document-intelligence/types";

const CONFIDENCE_BADGE_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  HIGH: "success",
  MEDIUM: "warning",
  LOW: "danger",
};

export function DocumentExtractionResults({ documentId }: { documentId: string }) {
  const [items, setItems] = useState<DocumentExtractionRunItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/documents/${documentId}/extractions`, {
        headers: { "X-Tenant-Key": readTenantKey() },
        cache: "no-store",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : body.message || res.statusText,
        );
      }
      setItems((body.items || []) as DocumentExtractionRunItem[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [documentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (busy) {
    return <p className="text-sm text-muted">Loading…</p>;
  }

  if (error) {
    return (
      <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
        {error}
      </p>
    );
  }

  if (!items || items.length === 0) {
    return (
      <p className="text-sm text-muted">
        No structured fields were extracted for this document. Document Intelligence is opt-in
        per upload — re-upload with a model or custom fields selected to see results here.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {items.map((run) => (
        <Card key={run.run_id}>
          <CardContent className="space-y-3 pt-5">
            <p className="text-xs text-muted">
              {run.model_key || "ad hoc"} · {run.status}
            </p>
            {run.fields.length === 0 ? (
              <p className="text-sm text-muted">No fields resolved for this run.</p>
            ) : (
              <ul className="space-y-1.5">
                {run.fields.map((field) => (
                  <li key={field.name} className="flex items-center gap-2 text-sm">
                    <span className="min-w-40 text-muted">{field.name}</span>
                    <span className="flex-1 truncate">{String(field.value ?? "")}</span>
                    <Badge variant={CONFIDENCE_BADGE_VARIANT[field.confidence_band] || "muted"}>
                      {field.confidence_band}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
