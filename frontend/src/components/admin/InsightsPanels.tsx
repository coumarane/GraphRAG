"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { adminJson, formatSeconds } from "@/lib/admin";
import { AdminButton, AdminCard, ErrorBanner, Stat, adminInputClass } from "@/components/admin/widgets";

type HealthItem = {
  document_id: string;
  title: string;
  score: number;
  status: string;
  pages_ok: number;
  pages_total: number;
};

type GraphPayload = {
  entities: number;
  documents: number;
  relationships: number;
  cross_document: number;
  duplicate_groups: number;
  duplicate_nodes: number;
  example: string | null;
};

type FeedbackPayload = {
  rated: number;
  positive: number;
  negative: number;
  satisfaction: number;
  knowledge_gaps: number;
  gaps: Array<{ question: string; answer_excerpt: string; created_at: string }>;
  flagged_documents: Array<{ title: string; thumbs_up: number; thumbs_down: number }>;
};

type Benchmark = {
  run_id: string;
  status: string;
  config: string;
  ndcg5: number;
  ndcg10: number;
  p50_seconds: number;
  p95_seconds: number;
  queries: number;
  created_at: string;
  errors: number;
};

type IngestionRun = {
  ingestion_run_id: string;
  status: string;
  parser: string | null;
  pages: number;
  duration_ms: number | null;
  completed_at: string | null;
  elements_detected: number;
  elements_processed: number;
  failed: number;
  skipped: number;
  warnings: number;
  errors: number;
  stages: Array<{
    name: string;
    status: string;
    tool: string | null;
    model: string | null;
    duration_ms: number | null;
  }>;
};

export function DocumentHealthPanel() {
  const [data, setData] = useState<{
    healthy: number;
    degraded: number;
    critical: number;
    items: HealthItem[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(
        await adminJson<{
          healthy: number;
          degraded: number;
          critical: number;
          items: HealthItem[];
        }>("/document-health"),
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-4 text-sm">
          <span className="text-emerald-600">● {data?.healthy ?? 0} healthy</span>
          <span className="text-amber-600">▲ {data?.degraded ?? 0} degraded</span>
          <span className="text-rose-600">● {data?.critical ?? 0} critical</span>
        </div>
        <AdminButton variant="ghost" onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <AdminCard>
        <div className="space-y-2">
          {(data?.items || []).map((item) => (
            <div
              key={item.document_id}
              className="flex flex-wrap items-center gap-3 rounded-xl px-1 py-2"
            >
              <span className="text-emerald-600">●</span>
              <p className="min-w-0 flex-1 truncate font-medium">{item.title}</p>
              <div className="h-2 w-40 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-emerald-500"
                  style={{ width: `${item.score}%` }}
                />
              </div>
              <span className="w-10 text-right text-sm text-[var(--muted)]">{item.score}%</span>
              <span className="rounded-full border border-emerald-200 px-2 py-0.5 text-xs text-emerald-700">
                {item.status}
              </span>
              <span className="text-xs text-[var(--muted)]">
                {item.pages_ok}/{item.pages_total} p.
              </span>
            </div>
          ))}
          {!data?.items.length ? (
            <p className="py-8 text-center text-sm text-[var(--muted)]">No documents yet.</p>
          ) : null}
        </div>
      </AdminCard>
    </div>
  );
}

export function ProcessingPanel() {
  const [data, setData] = useState<{
    documents: number;
    p50_seconds: number;
    p95_seconds: number;
    p99_seconds: number;
    trend: Array<{ date: string; p50: number; p95: number }>;
    stages: Array<{ name: string; avg_seconds: number }>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void adminJson<{
      documents: number;
      p50_seconds: number;
      p95_seconds: number;
      p99_seconds: number;
      trend: Array<{ date: string; p50: number; p95: number }>;
      stages: Array<{ name: string; avg_seconds: number }>;
    }>("/processing")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const maxTrend = Math.max(1, ...(data?.trend || []).map((row) => row.p95));
  const maxStage = Math.max(1, ...(data?.stages || []).map((row) => row.avg_seconds));

  return (
    <div className="space-y-4">
      <AdminCard>
        <h2 className="text-lg font-semibold">Document Processing</h2>
        <p className="text-sm text-[var(--muted)]">
          End-to-end ingestion timings by stage. Document names are never shown.
        </p>
      </AdminCard>
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Documents" value={data?.documents ?? 0} />
        <Stat label="p50 latency" value={formatSeconds(data?.p50_seconds || 0)} />
        <Stat label="p95 latency" value={formatSeconds(data?.p95_seconds || 0)} />
        <Stat label="p99 latency" value={formatSeconds(data?.p99_seconds || 0)} hint="UTC window" />
      </div>
      <AdminCard>
        <h3 className="mb-3 font-medium">Processing time trend</h3>
        <div className="flex h-40 items-end gap-1">
          {(data?.trend || []).map((row) => (
            <div key={row.date} className="flex flex-1 flex-col items-center gap-1">
              <div
                className="w-full rounded-t bg-[var(--accent)]/70"
                style={{ height: `${(row.p95 / maxTrend) * 100}%` }}
                title={`${row.date} p95 ${formatSeconds(row.p95)}`}
              />
            </div>
          ))}
        </div>
      </AdminCard>
      <AdminCard>
        <h3 className="mb-3 font-medium">Stage duration breakdown</h3>
        <div className="space-y-2">
          {(data?.stages || []).map((stage) => (
            <div key={stage.name} className="flex items-center gap-3 text-sm">
              <span className="w-24 capitalize">{stage.name}</span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-[var(--accent)]"
                  style={{ width: `${(stage.avg_seconds / maxStage) * 100}%` }}
                />
              </div>
              <span className="w-16 text-right text-[var(--muted)]">
                {formatSeconds(stage.avg_seconds)}
              </span>
            </div>
          ))}
        </div>
      </AdminCard>
    </div>
  );
}

export function KnowledgeGraphPanel() {
  const [data, setData] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await adminJson<GraphPayload>("/graph"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex gap-3 text-sm text-[var(--muted)]">
        <span className="border-b-2 border-[var(--accent)] pb-1 text-[var(--foreground)]">Overview</span>
        <span>Duplicates</span>
        <span>Entity Explorer</span>
        <span>Graph View</span>
      </div>
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Entities" value={data?.entities ?? 0} hint="unique named entities" />
        <Stat label="Documents" value={data?.documents ?? 0} hint="linked in graph" />
        <Stat label="Relationships" value={data?.relationships ?? 0} hint="typed edges" />
        <Stat label="Cross-document" value={data?.cross_document ?? 0} hint="entities in 2+ docs" />
        <Stat label="Duplicate groups" value={data?.duplicate_groups ?? 0} hint="nodes to merge" />
      </div>
      {(data?.duplicate_groups || 0) > 0 ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {data?.duplicate_groups} duplicate entity groups detected
          {data?.example ? `. Example: “${data.example}”` : "."}
        </div>
      ) : null}
      <div className="flex gap-2">
        <AdminButton variant="ghost" onClick={() => void load()}>
          Refresh
        </AdminButton>
        <AdminButton
          disabled={busy || !(data?.duplicate_groups || 0)}
          onClick={() => {
            setBusy(true);
            void adminJson<unknown>("/graph/consolidate", { method: "POST" })
              .then(load)
              .finally(() => setBusy(false));
          }}
        >
          Consolidate ({data?.duplicate_nodes ?? 0} nodes)
        </AdminButton>
      </div>
    </div>
  );
}

export function FeedbackPanel() {
  const [data, setData] = useState<FeedbackPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void adminJson<FeedbackPayload>("/feedback")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <div className="space-y-4">
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Rated answers" value={data?.rated ?? 0} hint="total feedback received" />
        <Stat
          label="Positive"
          value={data?.positive ?? 0}
          hint={`${(data?.satisfaction || 0).toFixed(1)}% satisfaction`}
        />
        <Stat label="Negative" value={data?.negative ?? 0} hint="answers to improve" />
        <Stat label="Knowledge gaps" value={data?.knowledge_gaps ?? 0} hint="questions with no sources" />
      </div>
      <AdminCard>
        <h3 className="font-medium text-amber-700">Knowledge gaps — documents may be missing</h3>
        <div className="mt-3 space-y-3">
          {(data?.gaps || []).map((gap) => (
            <div key={gap.question} className="rounded-xl border border-[var(--border)] p-3">
              <p className="font-medium">{gap.question}</p>
              <p className="mt-1 text-sm text-[var(--muted)]">{gap.answer_excerpt}</p>
            </div>
          ))}
          {!data?.gaps?.length ? (
            <p className="text-sm text-[var(--muted)]">No knowledge-gap feedback yet.</p>
          ) : null}
        </div>
      </AdminCard>
      <AdminCard>
        <h3 className="font-medium text-amber-700">
          Documents flagged by feedback ({data?.flagged_documents.length || 0})
        </h3>
        <div className="mt-3 space-y-2">
          {(data?.flagged_documents || []).map((doc) => (
            <div key={doc.title} className="flex items-center justify-between text-sm">
              <span>{doc.title}</span>
              <span className="text-[var(--muted)]">
                ▲ {doc.thumbs_up} ▼ {doc.thumbs_down}
              </span>
            </div>
          ))}
        </div>
      </AdminCard>
    </div>
  );
}

export function BenchmarksPanel() {
  const [items, setItems] = useState<Benchmark[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const data = await adminJson<{ items: Benchmark[] }>("/benchmarks");
      setItems(data.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const best = items[0];

  return (
    <AdminCard>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Retrieval benchmarks</h2>
          <p className="text-sm text-[var(--muted)]">
            Measure retrieval-only NDCG@5/@10 against p50/p95 latency across hybrid and rerank configs.
          </p>
        </div>
        <AdminButton
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void adminJson<Benchmark>("/benchmarks/run", {
              method: "POST",
              body: JSON.stringify({ config: "hybrid_rerank_k15" }),
            })
              .then(load)
              .finally(() => setBusy(false));
          }}
        >
          Run benchmark
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Best NDCG@10" value={best ? best.ndcg10.toFixed(3) : "—"} tone="soft" />
        <Stat label="Best config p95" value={best ? formatSeconds(best.p95_seconds) : "—"} />
        <Stat label="Queries / config" value={best?.queries ?? 0} hint={best?.config} />
      </div>
      <div className="mt-4 space-y-2">
        {items.map((item) => (
          <div key={item.run_id} className="rounded-xl border border-[var(--border)] px-3 py-2 text-sm">
            <span className="mr-2 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
              {item.status}
            </span>
            {item.config} · NDCG@10 {item.ndcg10.toFixed(3)} · p95 {formatSeconds(item.p95_seconds)}
          </div>
        ))}
      </div>
    </AdminCard>
  );
}

export function IngestionAuditPanel() {
  const [query, setQuery] = useState("");
  const [payload, setPayload] = useState<{
    document: { title: string } | null;
    runs: IngestionRun[];
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(next = query) {
    try {
      const data = await adminJson<{ document: { title: string } | null; runs: IngestionRun[] }>(
        `/ingestion-audit${next ? `?q=${encodeURIComponent(next)}` : ""}`,
      );
      setPayload(data);
      setSelected(data.runs[0]?.ingestion_run_id || null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial fetch
  }, []);

  const run = payload?.runs.find((item) => item.ingestion_run_id === selected) || payload?.runs[0];

  return (
    <AdminCard>
      <h2 className="text-lg font-semibold">Ingestion audit</h2>
      <p className="text-sm text-[var(--muted)]">
        Per-run, per-page, and per-element parsing provenance for a document.
      </p>
      <input
        className={`${adminInputClass} mt-3`}
        placeholder="Search document title"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void load(query);
        }}
      />
      <ErrorBanner error={error} />
      <div className="mt-4 grid gap-4 lg:grid-cols-[240px_1fr]">
        <div className="space-y-2">
          {(payload?.runs || []).map((item, index) => (
            <button
              key={item.ingestion_run_id}
              type="button"
              onClick={() => setSelected(item.ingestion_run_id)}
              className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                item.ingestion_run_id === run?.ingestion_run_id
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)]"
              }`}
            >
              Run #{payload!.runs.length - index} · {item.parser || "auto"}
              <div className="text-xs text-[var(--muted)]">{item.status}</div>
            </button>
          ))}
        </div>
        {run ? (
          <div>
            <p className="font-medium">{payload?.document?.title}</p>
            <div className="mt-3 grid grid-cols-4 gap-2 text-center text-sm">
              <Stat label="Elements" value={run.elements_detected} />
              <Stat label="Processed" value={run.elements_processed} />
              <Stat label="Failed / Skipped" value={`${run.failed} / ${run.skipped}`} />
              <Stat label="Warnings / Errors" value={`${run.warnings} / ${run.errors}`} />
            </div>
            <table className="mt-4 w-full text-left text-sm">
              <thead className="text-[var(--muted)]">
                <tr>
                  <th className="pb-2">Step</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Tool / Model</th>
                  <th className="pb-2">Duration</th>
                </tr>
              </thead>
              <tbody>
                {run.stages.map((stage) => (
                  <tr key={stage.name} className="border-t border-[var(--border)]">
                    <td className="py-2">{stage.name}</td>
                    <td className="py-2">{stage.status}</td>
                    <td className="py-2 text-[var(--muted)]">
                      {stage.tool || "—"} {stage.model || ""}
                    </td>
                    <td className="py-2">
                      {stage.duration_ms != null ? formatSeconds(stage.duration_ms / 1000) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">No ingestion runs for this document.</p>
        )}
      </div>
    </AdminCard>
  );
}

export function RetrievalAuditPanel() {
  const [items, setItems] = useState<
    Array<{
      conversation_id: string;
      question: string;
      retrieval_mode: string | null;
      grounded: boolean;
      citations: number;
      updated_at: string | null;
      graph_paths: number;
    }>
  >([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void adminJson<{ items: typeof items }>("/retrieval-audit")
      .then((data) => {
        setItems(data.items || []);
        setSelected(data.items?.[0]?.conversation_id || null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const current = items.find((item) => item.conversation_id === selected) || items[0];

  return (
    <AdminCard>
      <h2 className="text-lg font-semibold">Retrieval audit</h2>
      <p className="text-sm text-[var(--muted)]">
        Per-query retrieval provenance — HyDE/rerank usage, candidate counts, and citations.
      </p>
      <ErrorBanner error={error} />
      <div className="mt-4 grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="space-y-2">
          {items.map((item) => (
            <button
              key={item.conversation_id}
              type="button"
              className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                item.conversation_id === current?.conversation_id
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)]"
              }`}
              onClick={() => setSelected(item.conversation_id)}
            >
              {item.question}
              <div className="text-xs text-[var(--muted)]">{item.updated_at}</div>
            </button>
          ))}
          {!items.length ? (
            <p className="text-sm text-[var(--muted)]">No recent queries.</p>
          ) : null}
        </div>
        {current ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Stat label="Grounded" value={current.grounded ? "yes" : "no"} />
            <Stat label="Citations" value={current.citations} />
            <Stat label="Mode" value={current.retrieval_mode || "—"} />
            <Stat label="Graph paths" value={current.graph_paths} />
          </div>
        ) : null}
      </div>
    </AdminCard>
  );
}
