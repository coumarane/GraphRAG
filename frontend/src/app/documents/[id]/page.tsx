"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { readTenantKey } from "@/components/AppShell";
import { DocumentChunkViz } from "@/components/DocumentChunkViz";
import { DocumentExtractionResults } from "@/components/DocumentExtractionResults";
import { DocumentOriginalPreview } from "@/components/DocumentOriginalPreview";
import { DocumentPageViewer } from "@/components/DocumentPageViewer";
import { DocumentParseReport } from "@/components/DocumentParseReport";
import { DocumentIntelligencePanel } from "@/components/document-intelligence/DocumentIntelligencePanel";
import type {
  DocumentIntelligencePanelValue,
  DocumentIntelligencePayload,
} from "@/components/document-intelligence/types";

type DocumentMeta = {
  document_id: string;
  title: string | null;
  document_type: string | null;
  status: string;
  current_version_id: string | null;
  tags: string[];
};

type RunProgress = {
  status: string;
  current_stage?: string | null;
  estimated_completion_percent?: number;
  error_message?: string | null;
  latest_warning?: string | null;
};

const TERMINAL = new Set(["ready", "failed", "deleted", "partial"]);
const IN_PROGRESS = new Set(["ingesting", "registered", "pending"]);

function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "";
  return stage
    .toLowerCase()
    .split("_")
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
}

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

type Tab = "original" | "pages" | "indexed" | "report" | "extractions";

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const documentId = params.id;
  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);
  const [reprocessPanelOpen, setReprocessPanelOpen] = useState(false);
  const [diValue, setDiValue] = useState<DocumentIntelligencePanelValue>({
    enabled: false,
    payload: null,
  });
  const [tab, setTab] = useState<Tab>("original");
  const [runProgress, setRunProgress] = useState<RunProgress | null>(null);
  const pollRef = useRef<number | null>(null);

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
    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [load]);

  useEffect(() => {
    if (!meta) return;
    if (IN_PROGRESS.has(meta.status)) {
      startProgressPoll();
    } else if (meta.status === "failed" && documentId) {
      // Not a live poll transition (e.g. a plain page load/refresh landing
      // on an already-failed document) -- still worth fetching once so the
      // error banner below has something to show.
      void fetch(`/api/documents/${documentId}/ingestion-runs/latest`, {
        headers: { "X-Tenant-Key": readTenantKey() },
        cache: "no-store",
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((run) => {
          if (run) setRunProgress(run as RunProgress);
        })
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta?.status]);

  function stopProgressPoll() {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startProgressPoll() {
    if (pollRef.current != null || !documentId) return;
    const tick = async () => {
      try {
        const headers = { "X-Tenant-Key": readTenantKey() };
        const statusRes = await fetch(`/api/documents/${documentId}`, {
          headers,
          cache: "no-store",
        });
        let terminal = false;
        if (statusRes.ok) {
          const statusBody = (await statusRes.json()) as DocumentMeta;
          setMeta(statusBody);
          terminal = TERMINAL.has(statusBody.status);
        }
        // Fetch the run's final state (error_message/latest_warning) even on
        // the tick that detects termination -- an early return here used to
        // discard it before it was ever read, so a failed run showed no
        // diagnostic info anywhere in the UI.
        const runRes = await fetch(
          `/api/documents/${documentId}/ingestion-runs/latest`,
          { headers, cache: "no-store" },
        );
        if (runRes.ok) setRunProgress((await runRes.json()) as RunProgress);
        if (terminal) {
          stopProgressPoll();
          setReprocessing(false);
          await load();
        }
      } catch {
        /* keep polling */
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => void tick(), 1500);
  }

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

  async function reprocess(
    scope: "full" | "document_intelligence",
    diPayload?: DocumentIntelligencePayload,
  ) {
    if (!documentId) return;
    setReprocessing(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/documents/${documentId}/reprocess?scope=${scope}`,
        {
          method: "POST",
          headers: {
            "X-Tenant-Key": readTenantKey(),
            "Content-Type": "application/json",
          },
          body: diPayload
            ? JSON.stringify({ document_intelligence: diPayload })
            : undefined,
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
      setReprocessPanelOpen(false);
      startProgressPoll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setReprocessing(false);
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
          {meta && IN_PROGRESS.has(meta.status) && runProgress ? (
            <div className="mt-2 w-56 space-y-1">
              <div className="h-1.5 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{
                    width: `${Math.round(runProgress.estimated_completion_percent ?? 0)}%`,
                  }}
                />
              </div>
              <p className="text-xs text-muted">
                {Math.round(runProgress.estimated_completion_percent ?? 0)}%
                {runProgress.current_stage
                  ? ` · ${stageLabel(runProgress.current_stage)}`
                  : ""}
              </p>
            </div>
          ) : null}
          {meta?.status === "failed" &&
          (runProgress?.error_message || runProgress?.latest_warning) ? (
            <p className="mt-2 max-w-xl rounded border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
              {runProgress.error_message || runProgress.latest_warning}
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
            onClick={() => void reprocess("full")}
          >
            {reprocessing ? "Reprocessing…" : "Reprocess"}
          </button>
          <button
            type="button"
            disabled={reprocessing}
            className="rounded border border-border bg-surface px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-60"
            onClick={() => setReprocessPanelOpen((open) => !open)}
          >
            Reprocess with Document Intelligence
          </button>
          <Link
            href={`/query?document_id=${documentId}`}
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Query this doc
          </Link>
        </div>
      </div>

      {reprocessPanelOpen ? (
        <div className="space-y-3 rounded-xl border border-border bg-surface p-4">
          <DocumentIntelligencePanel
            value={diValue}
            onChange={setDiValue}
            disabled={reprocessing}
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={reprocessing || !diValue.enabled || !diValue.payload}
              onClick={() =>
                diValue.payload &&
                void reprocess("document_intelligence", diValue.payload)
              }
              className="rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
            >
              {reprocessing ? "Reprocessing…" : "Reprocess with these fields"}
            </button>
            <button
              type="button"
              onClick={() => setReprocessPanelOpen(false)}
              className="rounded border border-border px-3 py-2 text-sm font-medium hover:border-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className="flex gap-1 border-b border-border">
        {(
          [
            ["original", "Original preview"],
            ["pages", "Parsed content"],
            ["indexed", `Indexed text (${chunkTotal})`],
            ["report", "Parse report"],
            ["extractions", "Extracted fields"],
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

      {tab === "pages" && documentId ? (
        <DocumentPageViewer documentId={documentId} chunks={chunks} />
      ) : null}

      {tab === "indexed" ? <DocumentChunkViz chunks={chunks} /> : null}

      {tab === "report" && documentId ? (
        <DocumentParseReport documentId={documentId} />
      ) : null}

      {tab === "extractions" && documentId ? (
        <DocumentExtractionResults documentId={documentId} />
      ) : null}
    </section>
  );
}
