"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type IngestResult = {
  ingestion_run_id: string;
  document_id: string;
  version_id: string;
  status: string;
  duplicate_version?: boolean;
};

type RunStatus = {
  status: string;
  error_message?: string | null;
  latest_warning?: string | null;
  pages_processed?: number;
  elements_processed?: number;
  parser_used?: string | null;
};

const TERMINAL = new Set([
  "completed",
  "completed_with_warnings",
  "partial",
  "failed",
  "cancelled",
]);

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [run, setRun] = useState<RunStatus | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, []);

  function stopPolling() {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPolling(runId: string) {
    stopPolling();
    const tick = async () => {
      try {
        const runRes = await fetch(`/api/ingestion-runs/${runId}`, {
          headers: { "X-Tenant-Key": readTenantKey() },
        });
        if (!runRes.ok) return;
        const body = (await runRes.json()) as RunStatus;
        setRun(body);
        if (TERMINAL.has(body.status)) {
          stopPolling();
          setBusy(false);
        }
      } catch {
        /* keep polling */
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => void tick(), 1500);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a file to upload.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    setRun(null);
    stopPolling();
    try {
      const form = new FormData();
      form.append("file", file);
      if (title.trim()) form.append("title", title.trim());
      form.append("parser_requested", "auto");

      const response = await fetch("/api/ingest", {
        method: "POST",
        headers: { "X-Tenant-Key": readTenantKey() },
        body: form,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || body.message || response.statusText);
      }
      setResult(body as IngestResult);
      startPolling(body.ingestion_run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Upload document</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Files go through the API into object storage (MinIO when configured).
          The API then parses, chunks, and indexes the document in the
          background — status updates below until complete.
        </p>
      </div>

      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-lg border border-border bg-surface p-6 shadow-sm"
      >
        <label className="block text-sm">
          <span className="text-muted">File</span>
          <input
            type="file"
            className="mt-1 block w-full text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Title (optional)</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            placeholder="Defaults to filename"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {busy ? "Processing…" : "Upload & register"}
        </button>
      </form>

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {result ? (
        <div className="space-y-2 rounded-lg border border-border bg-surface p-5 font-mono text-sm">
          <p>
            <span className="text-muted">status</span> {result.status}
            {result.duplicate_version ? " (duplicate version)" : ""}
          </p>
          <p>
            <span className="text-muted">document_id</span> {result.document_id}
          </p>
          <p>
            <span className="text-muted">version_id</span> {result.version_id}
          </p>
          <p>
            <span className="text-muted">ingestion_run_id</span>{" "}
            {result.ingestion_run_id}
          </p>
          {run ? (
            <p className="border-t border-border pt-2">
              <span className="text-muted">run</span> {run.status}
              {run.parser_used ? ` · ${run.parser_used}` : ""}
              {run.pages_processed
                ? ` · ${run.pages_processed} pages`
                : ""}
              {run.elements_processed
                ? ` · ${run.elements_processed} elements`
                : ""}
              {run.latest_warning ? ` — ${run.latest_warning}` : ""}
              {run.error_message ? ` — ${run.error_message}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
