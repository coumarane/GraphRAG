"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { readTenantKey } from "@/components/AppShell";
import { DocumentChunkViz } from "@/components/DocumentChunkViz";
import { DocumentOriginalPreview } from "@/components/DocumentOriginalPreview";
import { DocumentParseReport } from "@/components/DocumentParseReport";

type DocumentMeta = {
  document_id: string;
  title: string | null;
  document_type: string | null;
  status: string;
  current_version_id: string | null;
  tags: string[];
};

type Chunk = {
  chunk_id: string;
  page_start: number;
  page_end: number;
  chunk_type: string;
  modality: string;
  section_path: string[];
  text: string;
  token_count: number;
};

type Tab = "original" | "indexed" | "report";

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const documentId = params.id;
  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);
  const [tab, setTab] = useState<Tab>("original");

  const load = useCallback(async () => {
    if (!documentId) return;
    setBusy(true);
    setError(null);
    try {
      const headers = { "X-Tenant-Key": readTenantKey() };
      const [docRes, chunkRes] = await Promise.all([
        fetch(`/api/documents/${documentId}`, { headers, cache: "no-store" }),
        fetch(`/api/documents/${documentId}/chunks?limit=500`, {
          headers,
          cache: "no-store",
        }),
      ]);
      const docBody = await docRes.json().catch(() => ({}));
      if (!docRes.ok) {
        throw new Error(
          typeof docBody.detail === "string"
            ? docBody.detail
            : docBody.message || docRes.statusText,
        );
      }
      setMeta(docBody as DocumentMeta);

      const chunkBody = await chunkRes.json().catch(() => ({}));
      if (!chunkRes.ok) {
        throw new Error(
          typeof chunkBody.detail === "string"
            ? chunkBody.detail
            : chunkBody.message || chunkRes.statusText,
        );
      }
      setChunks((chunkBody.items || []) as Chunk[]);
      setChunkTotal(chunkBody.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [documentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function downloadOriginal() {
    const res = await fetch(`/api/documents/${documentId}/original`, {
      headers: { "X-Tenant-Key": readTenantKey() },
    });
    if (!res.ok) {
      setError(`Download failed (${res.status})`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/.exec(disposition);
    anchor.download = match?.[1] || "document.pdf";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function reprocess() {
    if (!documentId) return;
    setReprocessing(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/documents/${documentId}/reprocess?scope=full`,
        {
          method: "POST",
          headers: { "X-Tenant-Key": readTenantKey() },
        },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || response.statusText,
        );
      }
      for (let i = 0; i < 40; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        await load();
        const statusRes = await fetch(`/api/documents/${documentId}`, {
          headers: { "X-Tenant-Key": readTenantKey() },
          cache: "no-store",
        });
        if (!statusRes.ok) continue;
        const statusBody = (await statusRes.json()) as DocumentMeta;
        if (["ready", "failed", "partial"].includes(statusBody.status)) {
          break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReprocessing(false);
      await load();
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link
            href="/documents"
            className="text-sm text-muted hover:text-foreground"
          >
            ← Documents
          </Link>
          <h2 className="mt-2 text-xl font-semibold">
            {meta?.title || (busy ? "Loading…" : "Document")}
          </h2>
          {meta ? (
            <p className="mt-1 font-mono text-xs text-muted">
              {meta.document_id} ·{" "}
              <span
                className={
                  meta.status === "ready"
                    ? "text-accent"
                    : meta.status === "failed"
                      ? "text-danger"
                      : ""
                }
              >
                {meta.status}
              </span>
              {meta.tags.length ? ` · ${meta.tags.join(", ")}` : ""}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={busy}
            className="rounded border border-border bg-surface px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-60"
          >
            {busy ? "Refreshing…" : "Refresh"}
          </button>
          <button
            type="button"
            className="rounded border border-border bg-surface px-3 py-2 text-sm font-medium hover:border-accent"
            onClick={() => void downloadOriginal()}
          >
            Download
          </button>
          <button
            type="button"
            disabled={reprocessing}
            className="rounded border border-border bg-surface px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-60"
            onClick={() => void reprocess()}
          >
            {reprocessing ? "Reprocessing…" : "Reprocess"}
          </button>
          <Link
            href={`/query?document_id=${documentId}`}
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Query this doc
          </Link>
        </div>
      </div>

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className="flex gap-1 border-b border-border">
        {(
          [
            ["original", "Original preview"],
            ["indexed", `Indexed text (${chunkTotal})`],
            ["report", "Parse report"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              tab === id
                ? "border-accent text-foreground"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "original" && documentId ? (
        <DocumentOriginalPreview documentId={documentId} />
      ) : null}

      {tab === "indexed" ? <DocumentChunkViz chunks={chunks} /> : null}

      {tab === "report" && documentId ? (
        <DocumentParseReport documentId={documentId} />
      ) : null}
    </section>
  );
}
