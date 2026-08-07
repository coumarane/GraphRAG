"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { readTenantKey } from "@/components/AppShell";

const MODES = [
  "auto",
  "naive",
  "local",
  "global",
  "hybrid",
  "multimodal",
  "mix",
] as const;

type Citation = {
  citation_id?: string;
  chunk_id?: string;
  document_id?: string;
  quote?: string;
  page_start?: number | null;
  page_end?: number | null;
};

type QueryResult = {
  answer: string;
  citations?: Citation[];
  warnings?: string[];
  mode?: string;
  retrieval_trace_id?: string;
};

function QueryForm() {
  const searchParams = useSearchParams();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<(typeof MODES)[number]>("auto");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);

  useEffect(() => {
    const fromUrl = searchParams.get("document_id");
    if (fromUrl) setDocumentId(fromUrl);
  }, [searchParams]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      setError("Enter a question.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Key": readTenantKey(),
        },
        body: JSON.stringify({
          question: question.trim(),
          mode,
          document_ids: documentId.trim() ? [documentId.trim()] : [],
          include_graph_paths: true,
          rerank: true,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || response.statusText,
        );
      }
      setResult(body as QueryResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-lg border border-border bg-surface p-6 shadow-sm"
      >
        <label className="block text-sm">
          <span className="text-muted">Question</span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={4}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            placeholder="What does the document say about …?"
          />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-muted">Mode</span>
            <select
              value={mode}
              onChange={(e) =>
                setMode(e.target.value as (typeof MODES)[number])
              }
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-muted">Document ID filter (optional)</span>
            <input
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value.trim())}
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-accent"
              placeholder="Leave empty for all documents"
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {busy ? "Running…" : "Ask"}
        </button>
      </form>

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {result ? (
        <article className="space-y-4 rounded-lg border border-border bg-surface p-6 shadow-sm">
          <div>
            <h3 className="text-sm font-medium text-muted">Answer</h3>
            <p className="mt-2 whitespace-pre-wrap leading-relaxed">
              {result.answer}
            </p>
          </div>
          {result.mode || result.retrieval_trace_id ? (
            <p className="font-mono text-xs text-muted">
              mode={result.mode ?? "?"}
              {result.retrieval_trace_id
                ? ` · trace=${result.retrieval_trace_id}`
                : ""}
            </p>
          ) : null}
          {result.warnings?.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {result.citations?.length ? (
            <div>
              <h3 className="text-sm font-medium text-muted">Citations</h3>
              <ul className="mt-2 space-y-3">
                {result.citations.map((c, i) => (
                  <li
                    key={c.citation_id || c.chunk_id || i}
                    className="rounded border border-border bg-background px-3 py-2 text-sm"
                  >
                    <p className="font-mono text-xs text-muted">
                      {c.document_id}
                      {c.page_start != null
                        ? ` · p.${c.page_start}${
                            c.page_end != null && c.page_end !== c.page_start
                              ? `–${c.page_end}`
                              : ""
                          }`
                        : ""}
                    </p>
                    {c.quote ? (
                      <p className="mt-1 text-foreground/90">{c.quote}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </article>
      ) : null}
    </>
  );
}

export default function QueryPage() {
  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Query</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Ask grounded questions over ingested documents. Same contract as the
          CLI <code className="font-mono text-xs">enterprise-rag query</code>.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <QueryForm />
      </Suspense>
    </section>
  );
}
