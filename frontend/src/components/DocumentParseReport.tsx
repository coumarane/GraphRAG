"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type DocumentReport = {
  report_id: string;
  ingestion_run_id: string;
  original_filename: string | null;
  total_pages: number;
  duration_ms: number | null;
  ingestion_status: string | null;
  primary_parser: string | null;
  parser_version: string | null;
  fallback_parsers: string[];
  ocr_strategy: string | null;
  vision_strategy: string | null;
  vision_llm: string | null;
  text_llm: string | null;
  embedding_model: string | null;
  total_detected_elements: number;
  total_processed_elements: number;
  total_failed_elements: number;
  total_skipped_elements: number;
  total_normalized_elements: number;
  total_warnings: number;
  total_errors: number;
  extraction_completeness: number | null;
  normalization_completeness: number | null;
  element_processing_coverage: number | null;
};

type PageReport = {
  page_number: number;
  status: string;
  page_parser: string | null;
  detected_elements: number;
  processed_elements: number;
  failed_elements: number;
  skipped_elements: number;
  normalized_elements: number;
  element_type_counts: Record<string, number>;
  warnings: string[];
  errors: string[];
};

type ElementReport = {
  element_report_id: string;
  page_number: number | null;
  normalized_element_type: string | null;
  status: string;
  detector: string | null;
  parser_name: string | null;
  model_name: string | null;
  processing_tool: string | null;
  reached_normalized: boolean;
  content_loss_reason: string | null;
  failure_reason: string | null;
  skip_reason: string | null;
};

type StageRun = {
  stage_name: string;
  status: string;
  tool: string | null;
  model_name: string | null;
  duration_ms: number | null;
  input_count: number | null;
  output_count: number | null;
};

type RoutingDecision = {
  reason_code: string;
  message: string | null;
  selected_tool: string | null;
  selected_model: string | null;
};

type Issue = {
  severity: string;
  code: string | null;
  message: string;
  page_number: number | null;
};

type ContentLoss = {
  page_number: number | null;
  element_type: string | null;
  reason: string;
  message: string | null;
};

type ParseSnapshot = {
  document: DocumentReport;
  pages: PageReport[];
  elements: ElementReport[];
  stages: StageRun[];
  routing_decisions: RoutingDecision[];
  issues: Issue[];
  content_losses: ContentLoss[];
};

type CompareDiff = {
  summary: Record<string, number>;
  document_deltas: Record<
    string,
    { run_a: unknown; run_b: unknown; changed: boolean }
  >;
};

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function ms(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

export function DocumentParseReport({ documentId }: { documentId: string }) {
  const [runIds, setRunIds] = useState<string[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [compareRun, setCompareRun] = useState<string | null>(null);
  const [report, setReport] = useState<ParseSnapshot | null>(null);
  const [diff, setDiff] = useState<CompareDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [showAllElements, setShowAllElements] = useState(false);

  const headers = useMemo(
    () => ({ "X-Tenant-Key": readTenantKey() }),
    // Re-read when document changes; tenant key is sync localStorage.
    [documentId],
  );

  const loadRuns = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/documents/${documentId}/parse-runs`, {
        headers,
        cache: "no-store",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || res.statusText,
        );
      }
      const ids = (body.ingestion_run_ids || []) as string[];
      // Newest last from API sort by string; reverse for UX (latest first).
      const ordered = [...ids].reverse();
      setRunIds(ordered);
      setSelectedRun((prev) => prev && ordered.includes(prev) ? prev : ordered[0] ?? null);
      setCompareRun((prev) => {
        if (prev && ordered.includes(prev)) return prev;
        return ordered.length > 1 ? ordered[1] : null;
      });
      if (!ordered.length) {
        setReport(null);
        setDiff(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRunIds([]);
      setReport(null);
    } finally {
      setBusy(false);
    }
  }, [documentId, headers]);

  const loadReport = useCallback(async () => {
    if (!selectedRun) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/documents/${documentId}/parse-runs/${selectedRun}/report`,
        { headers, cache: "no-store" },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || res.statusText,
        );
      }
      setReport(body as ParseSnapshot);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setReport(null);
    } finally {
      setBusy(false);
    }
  }, [documentId, headers, selectedRun]);

  const loadCompare = useCallback(async () => {
    if (!selectedRun || !compareRun || selectedRun === compareRun) {
      setDiff(null);
      return;
    }
    try {
      const res = await fetch(
        `/api/documents/${documentId}/parse-compare?run_a=${encodeURIComponent(compareRun)}&run_b=${encodeURIComponent(selectedRun)}`,
        { headers, cache: "no-store" },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDiff(null);
        return;
      }
      setDiff(body as CompareDiff);
    } catch {
      setDiff(null);
    }
  }, [compareRun, documentId, headers, selectedRun]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  useEffect(() => {
    void loadCompare();
  }, [loadCompare]);

  if (busy && !report && !runIds.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        Loading parse report…
      </p>
    );
  }

  if (error) {
    return (
      <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
        {error}
      </p>
    );
  }

  if (!runIds.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        No parse audit report yet. Reprocess this document to generate one.
      </p>
    );
  }

  const doc = report?.document;
  const losses = report?.content_losses ?? [];
  const issues = report?.issues ?? [];
  const elements = report?.elements ?? [];
  const visibleElements = showAllElements ? elements : elements.slice(0, 40);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <label className="block text-xs font-medium uppercase tracking-wide text-muted">
            Ingestion run
          </label>
          <select
            value={selectedRun ?? ""}
            onChange={(e) => setSelectedRun(e.target.value)}
            className="min-w-[16rem] rounded border border-border bg-background px-3 py-2 font-mono text-xs"
          >
            {runIds.map((id) => (
              <option key={id} value={id}>
                {shortId(id)}
                {id === runIds[0] ? " (latest)" : ""}
              </option>
            ))}
          </select>
        </div>
        {runIds.length > 1 ? (
          <div className="space-y-2">
            <label className="block text-xs font-medium uppercase tracking-wide text-muted">
              Compare with
            </label>
            <select
              value={compareRun ?? ""}
              onChange={(e) => setCompareRun(e.target.value || null)}
              className="min-w-[16rem] rounded border border-border bg-background px-3 py-2 font-mono text-xs"
            >
              <option value="">None</option>
              {runIds
                .filter((id) => id !== selectedRun)
                .map((id) => (
                  <option key={id} value={id}>
                    {shortId(id)}
                  </option>
                ))}
            </select>
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => {
            void loadRuns().then(() => loadReport());
          }}
          className="rounded border border-border px-3 py-2 text-sm font-medium hover:border-accent"
        >
          Refresh report
        </button>
      </div>

      {doc ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Pages", String(doc.total_pages)],
              ["Detected", String(doc.total_detected_elements)],
              ["Normalized", String(doc.total_normalized_elements)],
              ["Failed / skipped", `${doc.total_failed_elements} / ${doc.total_skipped_elements}`],
              ["Parser", doc.primary_parser || "—"],
              ["Duration", ms(doc.duration_ms)],
              ["Completeness", pct(doc.normalization_completeness)],
              ["Coverage", pct(doc.element_processing_coverage)],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded-lg border border-border bg-surface px-4 py-3"
              >
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted">
                  {label}
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          <div className="rounded-lg border border-border bg-surface px-4 py-3 text-sm">
            <p className="font-medium">Run details</p>
            <dl className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">Status</dt>
                <dd className="font-mono text-xs">{doc.ingestion_status || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">File</dt>
                <dd className="truncate text-xs">{doc.original_filename || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Vision strategy</dt>
                <dd className="text-xs">
                  {doc.vision_strategy || "—"}
                  {doc.vision_llm ? ` · ${doc.vision_llm}` : ""}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Text LLM</dt>
                <dd className="text-xs">{doc.text_llm || doc.vision_llm || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Embedding</dt>
                <dd className="text-xs">{doc.embedding_model || "—"}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted">Image handling</dt>
                <dd className="text-xs text-muted">
                  Layout parser detects image/chart regions; vision LLM
                  ({doc.vision_llm || "disabled"}) interprets those pages.
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted">Run id</dt>
                <dd className="break-all font-mono text-[11px]">{doc.ingestion_run_id}</dd>
              </div>
            </dl>
          </div>
        </>
      ) : null}

      {diff ? (
        <div className="rounded-lg border border-border bg-surface px-4 py-3">
          <p className="text-sm font-medium">Comparison vs prior run</p>
          <p className="mt-1 text-xs text-muted">
            Element changes: {diff.summary?.element_changes ?? 0} · Content losses A/B:{" "}
            {diff.summary?.content_losses_a ?? 0}/{diff.summary?.content_losses_b ?? 0}
          </p>
          <ul className="mt-3 space-y-1 text-xs">
            {Object.entries(diff.document_deltas || {})
              .filter(([, v]) => v?.changed)
              .map(([key, v]) => (
                <li key={key} className="flex flex-wrap gap-x-2 font-mono">
                  <span className="text-muted">{key}</span>
                  <span>{String(v.run_a)}</span>
                  <span className="text-muted">→</span>
                  <span>{String(v.run_b)}</span>
                </li>
              ))}
            {!Object.values(diff.document_deltas || {}).some((v) => v?.changed) ? (
              <li className="text-muted">No document-level metric changes.</li>
            ) : null}
          </ul>
        </div>
      ) : null}

      {report?.routing_decisions?.length ? (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Routing decisions</h3>
          <ul className="space-y-2">
            {report.routing_decisions.map((item, idx) => (
              <li
                key={`${item.reason_code}-${idx}`}
                className="rounded border border-border bg-surface px-3 py-2 text-sm"
              >
                <span className="font-mono text-xs text-accent">{item.reason_code}</span>
                <p className="mt-1 text-sm">
                  {item.message || "—"}
                  {item.selected_tool ? ` · tool ${item.selected_tool}` : ""}
                  {item.selected_model ? ` · model ${item.selected_model}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {report?.stages?.length ? (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Pipeline stages</h3>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-surface text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Stage</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Tool</th>
                  <th className="px-3 py-2 font-medium">In / Out</th>
                  <th className="px-3 py-2 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {report.stages.map((stage) => (
                  <tr key={stage.stage_name} className="border-t border-border">
                    <td className="px-3 py-2 font-mono">{stage.stage_name}</td>
                    <td className="px-3 py-2">{stage.status}</td>
                    <td className="px-3 py-2">
                      {stage.tool || "—"}
                      {stage.model_name ? ` / ${stage.model_name}` : ""}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {stage.input_count ?? "—"} / {stage.output_count ?? "—"}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{ms(stage.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {report?.pages?.length ? (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Pages</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {report.pages.map((page) => (
              <div
                key={page.page_number}
                className="rounded-lg border border-border bg-surface px-4 py-3 text-sm"
              >
                <p className="font-medium">
                  Page {page.page_number}{" "}
                  <span className="font-normal text-muted">· {page.status}</span>
                </p>
                <p className="mt-1 text-xs text-muted">
                  detected {page.detected_elements} · normalized {page.normalized_elements} ·
                  failed {page.failed_elements} · skipped {page.skipped_elements}
                </p>
                {Object.keys(page.element_type_counts || {}).length ? (
                  <p className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries(page.element_type_counts).map(([type, count]) => (
                      <span
                        key={type}
                        className="rounded bg-background px-1.5 py-0.5 font-mono text-[11px] text-muted"
                      >
                        {type}:{count}
                      </span>
                    ))}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {(losses.length > 0 || issues.length > 0) && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Losses & issues</h3>
          {losses.length ? (
            <ul className="space-y-2">
              {losses.map((loss, idx) => (
                <li
                  key={`loss-${idx}`}
                  className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm"
                >
                  <span className="font-mono text-xs">{loss.reason}</span>
                  {loss.element_type ? ` · ${loss.element_type}` : ""}
                  {loss.page_number != null ? ` · page ${loss.page_number}` : ""}
                  <p className="mt-1 text-xs text-muted">{loss.message || "—"}</p>
                </li>
              ))}
            </ul>
          ) : null}
          {issues.length ? (
            <ul className="mt-2 space-y-2">
              {issues.map((issue, idx) => (
                <li
                  key={`issue-${idx}`}
                  className={`rounded border px-3 py-2 text-sm ${
                    issue.severity === "error"
                      ? "border-danger/30 bg-danger/5"
                      : "border-border bg-surface"
                  }`}
                >
                  <span className="text-xs uppercase text-muted">{issue.severity}</span>
                  {issue.code ? (
                    <span className="ml-2 font-mono text-xs">{issue.code}</span>
                  ) : null}
                  <p className="mt-1">{issue.message}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      )}

      {elements.length ? (
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">
              Elements ({elements.length})
            </h3>
            {elements.length > 40 ? (
              <button
                type="button"
                className="text-xs text-accent hover:underline"
                onClick={() => setShowAllElements((v) => !v)}
              >
                {showAllElements ? "Show fewer" : "Show all"}
              </button>
            ) : null}
          </div>
          <p className="text-xs text-muted">
            Detector = layout source (e.g. Docling). LLM model = vision model when
            the page was interpreted ({doc?.vision_llm || "none"}).
          </p>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-surface text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Page</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Detector</th>
                  <th className="px-3 py-2 font-medium">LLM model</th>
                  <th className="px-3 py-2 font-medium">Normalized</th>
                </tr>
              </thead>
              <tbody>
                {visibleElements.map((el) => {
                  const hybrid =
                    el.detector === "vision" ||
                    (el.detector || "").includes("+vision") ||
                    (el.processing_tool || "").includes("vision");
                  const llmModel =
                    el.model_name ||
                    (hybrid ? doc?.vision_llm || doc?.text_llm || null : null);
                  return (
                  <tr key={el.element_report_id} className="border-t border-border">
                    <td className="px-3 py-2 tabular-nums">{el.page_number ?? "—"}</td>
                    <td className="px-3 py-2 font-mono">
                      {el.normalized_element_type || "—"}
                    </td>
                    <td className="px-3 py-2">{el.status}</td>
                    <td className="px-3 py-2">
                      {el.detector || el.parser_name || "—"}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {llmModel || "layout only"}
                    </td>
                    <td className="px-3 py-2">
                      {el.reached_normalized ? "yes" : "no"}
                      {el.failure_reason || el.skip_reason
                        ? ` · ${el.failure_reason || el.skip_reason}`
                        : ""}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
