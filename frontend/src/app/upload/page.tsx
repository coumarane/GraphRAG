"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { FileUp, Upload as UploadIcon, X } from "lucide-react";
import { readTenantKey } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type IngestResult = {
  ingestion_run_id: string;
  document_id: string;
  version_id: string;
  status: string;
  duplicate_version?: boolean;
};

type StageProgress = {
  stage: string;
  status: string;
  attempt_count?: number;
  warning?: string | null;
  error_message?: string | null;
};

type RunStatus = {
  status: string;
  error_message?: string | null;
  latest_warning?: string | null;
  pages_processed?: number;
  elements_processed?: number;
  parser_used?: string | null;
  current_stage?: string | null;
  estimated_completion_percent?: number;
  worker_id?: string | null;
  stages?: StageProgress[];
};

const TERMINAL = new Set([
  "completed",
  "completed_with_warnings",
  "partial",
  "failed",
  "cancelled",
]);

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [run, setRun] = useState<RunStatus | null>(null);
  const pollRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dragDepth = useRef(0);

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
          credentials: "include",
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

  function titleFromFilename(name: string): string {
    return name.replace(/\.[^.]+$/, "");
  }

  function acceptFile(next: File | null | undefined) {
    if (!next) return;
    // Always refresh the title from the newly chosen file so a prior
    // upload's title cannot stick to a different document.
    setFile(next);
    setTitle(titleFromFilename(next.name));
    setError(null);
    setResult(null);
    setRun(null);
  }

  function clearFile() {
    setFile(null);
    setTitle("");
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDragEnter(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current += 1;
    setDragging(true);
  }

  function onDragLeave(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  }

  function onDragOver(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
  }

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = 0;
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    acceptFile(dropped);
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
        credentials: "include",
        method: "POST",
        headers: { "X-Tenant-Key": readTenantKey() },
        body: form,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409) {
          const existingId =
            typeof body.metadata?.document_id === "string"
              ? body.metadata.document_id
              : null;
          const base =
            body.detail ||
            body.message ||
            "This document is already uploaded.";
          throw new Error(
            existingId
              ? `${base} Open Documents to view the existing file (${existingId.slice(0, 8)}…).`
              : base,
          );
        }
        throw new Error(body.detail || body.message || response.statusText);
      }
      setResult(body as IngestResult);
      setFile(null);
      setTitle("");
      if (inputRef.current) inputRef.current.value = "";
      startPolling(body.ingestion_run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Upload</h1>
        <p className="mt-1 text-sm text-muted">
          Browse or drag and drop a document. Parsing and indexing continue in
          the background.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-5">
        <Card>
          <CardContent className="pt-5">
            <input
              ref={inputRef}
              type="file"
              className="sr-only"
              onChange={(e) => acceptFile(e.target.files?.[0])}
            />

            <div
              role="button"
              tabIndex={0}
              aria-label="Browse or drag and drop a document"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragEnter={onDragEnter}
              onDragLeave={onDragLeave}
              onDragOver={onDragOver}
              onDrop={onDrop}
              className={cn(
                "flex min-h-[12rem] cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center transition-colors",
                dragging
                  ? "border-accent bg-accent-soft"
                  : "border-border bg-surface-elevated/40 hover:border-accent/60 hover:bg-surface-elevated/70",
              )}
            >
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-accent">
                <UploadIcon className="h-5 w-5" />
              </div>
              <p className="text-sm font-medium text-foreground">
                {dragging
                  ? "Drop the file to upload"
                  : "Browse or drag and drop"}
              </p>
              <p className="mt-1 max-w-sm text-xs text-muted">
                PDF, Word, PowerPoint, Excel, images, Markdown, and plain text
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="mt-4"
                onClick={(event) => {
                  event.stopPropagation();
                  inputRef.current?.click();
                }}
              >
                Browse files
              </Button>
            </div>

            {file ? (
              <div className="mt-4 flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
                  <FileUp className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted">{formatBytes(file.size)}</p>
                </div>
                <button
                  type="button"
                  aria-label="Remove file"
                  className="rounded-md p-1.5 text-muted hover:bg-surface-elevated hover:text-foreground"
                  onClick={clearFile}
                  disabled={busy}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-2">
          <Label htmlFor="title">Title (optional)</Label>
          <Input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Defaults to filename"
            disabled={busy}
          />
        </div>

        <Button type="submit" disabled={busy || !file}>
          {busy ? "Processing…" : "Upload & register"}
        </Button>
      </form>

      {error ? (
        <p className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {result ? (
        <Card>
          <CardContent className="space-y-2 pt-5 font-mono text-sm">
            <p>
              <span className="text-muted">status</span> {result.status}
              {result.duplicate_version ? " (duplicate version)" : ""}
            </p>
            <p>
              <span className="text-muted">document_id</span>{" "}
              {result.document_id}
            </p>
            <p>
              <span className="text-muted">version_id</span> {result.version_id}
            </p>
            <p>
              <span className="text-muted">ingestion_run_id</span>{" "}
              {result.ingestion_run_id}
            </p>
            {run ? (
              <div className="space-y-2 border-t border-border pt-2">
                <p>
                  <span className="text-muted">run</span> {run.status}
                  {typeof run.estimated_completion_percent === "number"
                    ? ` · ${Math.round(run.estimated_completion_percent)}%`
                    : ""}
                  {run.current_stage ? ` · ${run.current_stage}` : ""}
                  {run.parser_used ? ` · ${run.parser_used}` : ""}
                  {run.pages_processed ? ` · ${run.pages_processed} pages` : ""}
                  {run.elements_processed
                    ? ` · ${run.elements_processed} elements`
                    : ""}
                  {run.latest_warning ? ` — ${run.latest_warning}` : ""}
                  {run.error_message ? ` — ${run.error_message}` : ""}
                </p>
                {run.stages && run.stages.length > 0 ? (
                  <ol className="max-h-56 space-y-1 overflow-auto text-xs">
                    {run.stages.map((stage) => (
                      <li key={stage.stage} className="flex justify-between gap-3">
                        <span className="text-muted">{stage.stage}</span>
                        <span>
                          {stage.status}
                          {stage.attempt_count ? ` ×${stage.attempt_count}` : ""}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
