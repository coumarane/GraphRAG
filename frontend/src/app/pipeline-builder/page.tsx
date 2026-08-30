"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchSession, readCachedSession } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ChunkingConfig = {
  strategy: string;
  parent_target_tokens: number;
  child_target_tokens: number;
  overlap_tokens: number;
  preserve_tables: boolean;
  preserve_equations: boolean;
  preserve_figure_context: boolean;
  generate_table_row_chunks: boolean;
  generate_image_chunks: boolean;
  generate_composite_chunks: boolean;
};

type RetrievalConfig = {
  default_mode: string;
  top_k: number;
  graph_depth: number;
  rerank: boolean;
};

type CurrentConfig = {
  chunking: ChunkingConfig;
  retrieval: RetrievalConfig;
  parser_default_profile: string;
  parser_profile_primary: string | null;
  parser_profile_editable: boolean;
};

type PreviewResponse = {
  valid: boolean;
  errors: string[];
  diff: string;
  target_file: string;
};

const RETRIEVAL_MODES = ["auto", "naive", "local", "global", "hybrid", "multimodal", "mix"];

function diffOf<T extends Record<string, unknown>>(original: T, current: T): Partial<T> {
  const changed: Partial<T> = {};
  for (const key of Object.keys(original) as (keyof T)[]) {
    if (original[key] !== current[key]) changed[key] = current[key];
  }
  return changed;
}

function ArrowDivider() {
  return (
    <div className="hidden items-center justify-center px-1 text-muted lg:flex" aria-hidden>
      <svg width="28" height="16" viewBox="0 0 28 16" fill="none">
        <path
          d="M0 8h24m0 0-6-6m6 6-6 6"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export default function PipelineBuilderPage() {
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [original, setOriginal] = useState<CurrentConfig | null>(null);
  const [chunking, setChunking] = useState<ChunkingConfig | null>(null);
  const [retrieval, setRetrieval] = useState<RetrievalConfig | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void (async () => {
      const session = readCachedSession() || (await fetchSession().catch(() => null));
      if (!session || session.user.role !== "admin") {
        setAllowed(false);
        setLoading(false);
        return;
      }
      try {
        const res = await fetch("/api/ops/config-composer", { credentials: "include" });
        if (res.status === 403) {
          setAllowed(false);
          setError("Admin access required");
          return;
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setError(
            typeof body.detail === "string"
              ? body.detail
              : `Unable to load config (${res.status})`,
          );
          return;
        }
        const data = (await res.json()) as CurrentConfig;
        setOriginal(data);
        setChunking(data.chunking);
        setRetrieval(data.retrieval);
        setAllowed(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load config");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const chunkingChanges = useMemo(
    () => (original && chunking ? diffOf(original.chunking, chunking) : {}),
    [original, chunking],
  );
  const retrievalChanges = useMemo(
    () => (original && retrieval ? diffOf(original.retrieval, retrieval) : {}),
    [original, retrieval],
  );
  const hasChanges =
    Object.keys(chunkingChanges).length > 0 || Object.keys(retrievalChanges).length > 0;

  function resetChanges() {
    if (!original) return;
    setChunking(original.chunking);
    setRetrieval(original.retrieval);
    setPreview(null);
  }

  async function runPreview() {
    setPreviewing(true);
    setPreview(null);
    setCopied(false);
    try {
      const res = await fetch("/api/ops/config-composer/preview", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunking: chunkingChanges, retrieval: retrievalChanges }),
      });
      const body = (await res.json()) as PreviewResponse;
      setPreview(body);
    } catch (err) {
      setPreview({
        valid: false,
        errors: [err instanceof Error ? err.message : "Preview request failed"],
        diff: "",
        target_file: "",
      });
    } finally {
      setPreviewing(false);
    }
  }

  async function copyDiff() {
    if (!preview?.diff) return;
    await navigator.clipboard.writeText(preview.diff);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Pipeline Builder</h1>
        <p className="text-sm text-muted">Loading current configuration…</p>
      </div>
    );
  }

  if (!allowed || !original || !chunking || !retrieval) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Pipeline Builder</h1>
        <p className="text-sm text-danger">{error || "Admin access required"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Pipeline Builder</h1>
        <p className="text-sm text-muted">
          Compose the ingestion/retrieval defaults this tenant runs with. Changes are
          previewed as a YAML diff you copy into a pull request — nothing here writes to
          the running system directly, so a change only takes effect once it&apos;s merged
          and deployed through the normal pipeline.
        </p>
      </div>

      <div className="grid gap-0 lg:grid-cols-[1fr_auto_1fr_auto_1fr] lg:items-stretch">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Parser Profile
              <Badge variant="muted">read-only</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <p className="text-xs text-muted">Default profile</p>
              <p className="font-medium">{original.parser_default_profile}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Primary parser</p>
              <p className="font-medium">{original.parser_profile_primary || "—"}</p>
            </div>
            <p className="text-xs text-muted">
              Profile content isn&apos;t wired into ingestion routing yet — this reflects
              config, not a live decision.
            </p>
          </CardContent>
        </Card>

        <ArrowDivider />

        <Card>
          <CardHeader>
            <CardTitle>Chunking</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Parent tokens</Label>
                <Input
                  type="number"
                  min={1}
                  value={chunking.parent_target_tokens}
                  onChange={(e) =>
                    setChunking({
                      ...chunking,
                      parent_target_tokens: Number(e.target.value),
                    })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Child tokens</Label>
                <Input
                  type="number"
                  min={1}
                  value={chunking.child_target_tokens}
                  onChange={(e) =>
                    setChunking({ ...chunking, child_target_tokens: Number(e.target.value) })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Overlap tokens</Label>
                <Input
                  type="number"
                  min={0}
                  value={chunking.overlap_tokens}
                  onChange={(e) =>
                    setChunking({ ...chunking, overlap_tokens: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              {(
                [
                  ["preserve_tables", "Preserve tables"],
                  ["preserve_equations", "Preserve equations"],
                  ["preserve_figure_context", "Preserve figure context"],
                  ["generate_table_row_chunks", "Table-row chunks"],
                  ["generate_image_chunks", "Image chunks"],
                  ["generate_composite_chunks", "Composite chunks"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border"
                    checked={chunking[key]}
                    onChange={(e) => setChunking({ ...chunking, [key]: e.target.checked })}
                  />
                  {label}
                </label>
              ))}
            </div>
          </CardContent>
        </Card>

        <ArrowDivider />

        <Card>
          <CardHeader>
            <CardTitle>Retrieval</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Default mode</Label>
              <select
                className="flex h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={retrieval.default_mode}
                onChange={(e) => setRetrieval({ ...retrieval, default_mode: e.target.value })}
              >
                {RETRIEVAL_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Top K</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={retrieval.top_k}
                  onChange={(e) => setRetrieval({ ...retrieval, top_k: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Graph depth</Label>
                <Input
                  type="number"
                  min={0}
                  max={10}
                  value={retrieval.graph_depth}
                  onChange={(e) =>
                    setRetrieval({ ...retrieval, graph_depth: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border"
                checked={retrieval.rerank}
                onChange={(e) => setRetrieval({ ...retrieval, rerank: e.target.checked })}
              />
              Rerank results
            </label>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2">
            <span>Preview</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={resetChanges} disabled={!hasChanges}>
                Reset
              </Button>
              <Button size="sm" onClick={() => void runPreview()} disabled={!hasChanges || previewing}>
                {previewing ? "Previewing…" : "Preview diff"}
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!hasChanges ? (
            <p className="text-sm text-muted">No changes yet.</p>
          ) : null}
          {preview && !preview.valid ? (
            <div className="space-y-1 rounded-lg border border-danger/40 bg-danger/5 p-3 text-sm text-danger">
              {preview.errors.map((err) => (
                <p key={err}>{err}</p>
              ))}
            </div>
          ) : null}
          {preview && preview.valid && preview.diff ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted">
                  Copy this into <code>{preview.target_file}</code> in a PR — nothing has
                  been written yet.
                </p>
                <Button variant="ghost" size="sm" onClick={() => void copyDiff()}>
                  {copied ? "Copied" : "Copy diff"}
                </Button>
              </div>
              <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-3 text-xs">
                {preview.diff}
              </pre>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
