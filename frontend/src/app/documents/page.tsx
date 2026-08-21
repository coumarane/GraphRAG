"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type DocumentItem = {
  document_id: string;
  title: string | null;
  document_type: string | null;
  status: string;
  current_version_id: string | null;
  tags: string[];
};

type ListResponse = {
  items: DocumentItem[];
  total: number;
  offset: number;
  limit: number;
};

type RunProgress = {
  status: string;
  current_stage?: string | null;
  estimated_completion_percent?: number;
  error_message?: string | null;
  latest_warning?: string | null;
};

const TERMINAL = new Set(["ready", "failed", "deleted", "partial"]);
// Statuses worth polling ingestion-run progress for.
const IN_PROGRESS = new Set(["ingesting", "registered", "pending"]);

function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "";
  return stage
    .toLowerCase()
    .split("_")
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
}

function DocumentsPageContent() {
  const searchParams = useSearchParams();
  const statusFilter = searchParams.get("status");
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [reprocessingId, setReprocessingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [runProgress, setRunProgress] = useState<Record<string, RunProgress>>({});
  const pollRefs = useRef<Map<string, number>>(new Map());

  const visibleItems = useMemo(() => {
    const items = data?.items ?? [];
    if (!statusFilter) return items;
    return items.filter(
      (item) => item.status.toLowerCase() === statusFilter.toLowerCase(),
    );
  }, [data?.items, statusFilter]);

  const pageTitle =
    statusFilter === "failed" ? "Failed Processing" : "Documents";
  const pageHint =
    statusFilter === "failed"
      ? "Documents that failed ingestion. Use Reprocess to retry from the stored original."
      : "Use Reprocess to rebuild indexes from the stored original — no re-upload needed.";

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/documents?limit=100", {
        credentials: "include",
        headers: { "X-Tenant-Key": readTenantKey() },
        cache: "no-store",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || response.statusText,
        );
      }
      const list = body as ListResponse;
      setData(list);
      for (const item of list.items) {
        if (IN_PROGRESS.has(item.status)) startStatusPoll(item.document_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load();
    const refs = pollRefs.current;
    return () => {
      for (const id of refs.values()) window.clearInterval(id);
      refs.clear();
    };
  }, [load]);

  function stopPolling(documentId: string) {
    const id = pollRefs.current.get(documentId);
    if (id != null) {
      window.clearInterval(id);
      pollRefs.current.delete(documentId);
    }
  }

  function startStatusPoll(documentId: string) {
    if (pollRefs.current.has(documentId)) return;
    const tick = async () => {
      try {
        const res = await fetch(`/api/documents/${documentId}`, {
          headers: { "X-Tenant-Key": readTenantKey() },
          cache: "no-store",
        });
        if (!res.ok) return;
        const body = (await res.json()) as DocumentItem;
        setData((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            items: prev.items.map((item) =>
              item.document_id === documentId
                ? { ...item, status: body.status }
                : item,
            ),
          };
        });

        if (TERMINAL.has(body.status)) {
          stopPolling(documentId);
          setRunProgress((prev) => {
            const next = { ...prev };
            delete next[documentId];
            return next;
          });
          setReprocessingId((current) =>
            current === documentId ? null : current,
          );
          if (reprocessingId === documentId) {
            setActionMessage(
              body.status === "ready"
                ? "Reprocess finished — document is ready."
                : `Reprocess ended with status: ${body.status}`,
            );
          }
          void load();
          return;
        }

        const runRes = await fetch(
          `/api/documents/${documentId}/ingestion-runs/latest`,
          { headers: { "X-Tenant-Key": readTenantKey() }, cache: "no-store" },
        );
        if (runRes.ok) {
          const run = (await runRes.json()) as RunProgress;
          setRunProgress((prev) => ({ ...prev, [documentId]: run }));
        }
      } catch {
        /* keep polling */
      }
    };
    void tick();
    pollRefs.current.set(
      documentId,
      window.setInterval(() => void tick(), 1500),
    );
  }

  async function reprocess(documentId: string) {
    setError(null);
    setActionMessage(null);
    setReprocessingId(documentId);
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
      setActionMessage(
        `Reprocess accepted (run ${body.ingestion_run_id || "n/a"}). Indexing…`,
      );
      startStatusPoll(documentId);
    } catch (err) {
      setReprocessingId(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{pageTitle}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            {statusFilter === "failed" ? (
              pageHint
            ) : (
              <>
                Use{" "}
                <strong className="font-medium text-foreground">Reprocess</strong>{" "}
                to rebuild indexes from the stored original — no re-upload needed.
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={busy}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-foreground hover:border-accent disabled:opacity-60"
          >
            {busy ? "Refreshing…" : "Refresh"}
          </button>
          <Link
            href="/upload"
            className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Upload
          </Link>
        </div>
      </div>

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {actionMessage ? (
        <p className="rounded border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-foreground">
          {actionMessage}
        </p>
      ) : null}

      {!error && data && visibleItems.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
          {statusFilter === "failed" ? (
            <>No failed documents right now.</>
          ) : (
            <>
              No documents yet.{" "}
              <Link href="/upload" className="text-accent underline">
                Upload one
              </Link>
              .
            </>
          )}
        </p>
      ) : null}

      {data && visibleItems.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-sm">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-border bg-background/80 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">Title</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Document ID</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((doc) => (
                <tr
                  key={doc.document_id}
                  className="border-b border-border last:border-0"
                >
                  <td className="px-4 py-3 font-medium text-foreground">
                    <Link
                      href={`/documents/${doc.document_id}`}
                      className="text-accent hover:underline"
                    >
                      {doc.title || "(untitled)"}
                    </Link>
                    {doc.tags.length ? (
                      <span className="mt-1 block font-normal text-xs text-muted">
                        {doc.tags.join(", ")}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`font-mono text-xs ${
                        doc.status === "ready"
                          ? "text-accent"
                          : doc.status === "failed"
                            ? "text-danger"
                            : "text-muted"
                      }`}
                    >
                      {doc.status}
                    </span>
                    {IN_PROGRESS.has(doc.status) && runProgress[doc.document_id] ? (
                      <div className="mt-1.5 w-32 space-y-1">
                        <div className="h-1.5 overflow-hidden rounded-full bg-border">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{
                              width: `${Math.round(
                                runProgress[doc.document_id]
                                  .estimated_completion_percent ?? 0,
                              )}%`,
                            }}
                          />
                        </div>
                        <p className="text-[11px] text-muted">
                          {Math.round(
                            runProgress[doc.document_id]
                              .estimated_completion_percent ?? 0,
                          )}
                          %
                          {runProgress[doc.document_id].current_stage
                            ? ` · ${stageLabel(runProgress[doc.document_id].current_stage)}`
                            : ""}
                        </p>
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-muted">
                    {doc.document_type || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {doc.document_id}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Link
                        href={`/documents/${doc.document_id}`}
                        className="inline-flex rounded border border-border bg-background px-3 py-1.5 text-xs font-medium hover:border-accent"
                      >
                        Preview
                      </Link>
                      <button
                        type="button"
                        disabled={reprocessingId === doc.document_id}
                        onClick={() => void reprocess(doc.document_id)}
                        className="inline-flex rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-60"
                      >
                        {reprocessingId === doc.document_id
                          ? "Reprocessing…"
                          : "Reprocess"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-border px-4 py-2 font-mono text-xs text-muted">
            {visibleItems.length} document{visibleItems.length === 1 ? "" : "s"}
            {statusFilter ? ` · filtered by status=${statusFilter}` : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}

export default function DocumentsPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <DocumentsPageContent />
    </Suspense>
  );
}
