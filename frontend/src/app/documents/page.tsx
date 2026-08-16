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

const TERMINAL = new Set(["ready", "failed", "deleted", "partial"]);

function DocumentsPageContent() {
  const searchParams = useSearchParams();
  const statusFilter = searchParams.get("status");
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [reprocessingId, setReprocessingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

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
      setData(body as ListResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [load]);

  function stopPolling() {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startStatusPoll(documentId: string) {
    stopPolling();
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
          stopPolling();
          setReprocessingId(null);
          setActionMessage(
            body.status === "ready"
              ? "Reprocess finished — document is ready."
              : `Reprocess ended with status: ${body.status}`,
          );
          void load();
        }
      } catch {
        /* keep polling */
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => void tick(), 1500);
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
