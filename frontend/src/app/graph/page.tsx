"use client";

import { FormEvent, useState } from "react";
import { readTenantKey } from "@/components/AppShell";
import { GraphNetworkViz } from "@/components/GraphNetworkViz";

type GraphResult = {
  entities: Record<string, unknown>[];
  neighbors: Record<string, unknown>[];
  claims: Record<string, unknown>[];
  topics: Record<string, unknown>[];
  chunk_ids: string[];
};

export default function GraphPage() {
  const [names, setNames] = useState("");
  const [terms, setTerms] = useState("");
  const [depth, setDepth] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GraphResult | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const nameList = names
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const termList = terms
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!nameList.length && !termList.length) {
      setError("Provide at least one entity name or query term.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/graph", {
        credentials: "include",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Key": readTenantKey(),
        },
        body: JSON.stringify({
          names: nameList,
          query_terms: termList,
          depth,
          limit: 20,
          include_claims: true,
          include_topics: true,
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
      setResult(body as GraphResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Graph search</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Look up entities and neighbors in the knowledge graph for the current
          tenant.
        </p>
      </div>

      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-lg border border-border bg-surface p-4 shadow-sm sm:p-6"
      >
        <label className="block text-sm">
          <span className="text-muted">Entity names (comma-separated)</span>
          <input
            value={names}
            onChange={(e) => setNames(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            placeholder="Acme Corp, Project Atlas"
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Query terms (comma-separated)</span>
          <input
            value={terms}
            onChange={(e) => setTerms(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            placeholder="warranty, lithium"
          />
        </label>
        <label className="block text-sm sm:max-w-xs">
          <span className="text-muted">Depth</span>
          <input
            type="number"
            min={0}
            max={10}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {busy ? "Searching…" : "Search graph"}
        </button>
      </form>

      {error ? (
        <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {result ? (
        <div className="space-y-4">
          <GraphNetworkViz
            entities={result.entities}
            neighbors={result.neighbors}
            claims={result.claims}
            topics={result.topics}
          />
          <div className="grid gap-4 md:grid-cols-2">
          {(
            [
              ["Entities", result.entities],
              ["Neighbors", result.neighbors],
              ["Claims", result.claims],
              ["Topics", result.topics],
            ] as const
          ).map(([label, items]) => (
            <div
              key={label}
              className="rounded-lg border border-border bg-surface p-4 shadow-sm"
            >
              <h3 className="text-sm font-medium text-muted">
                {label}{" "}
                <span className="font-mono text-xs">({items.length})</span>
              </h3>
              {items.length === 0 ? (
                <p className="mt-3 text-sm text-muted">None</p>
              ) : (
                <pre className="mt-3 max-h-72 overflow-auto rounded bg-background p-3 font-mono text-xs leading-relaxed">
                  {JSON.stringify(items, null, 2)}
                </pre>
              )}
            </div>
          ))}
          <div className="rounded-lg border border-border bg-surface p-4 shadow-sm md:col-span-2">
            <h3 className="text-sm font-medium text-muted">
              Chunk IDs{" "}
              <span className="font-mono text-xs">
                ({result.chunk_ids.length})
              </span>
            </h3>
            <pre className="mt-3 max-h-40 overflow-auto rounded bg-background p-3 font-mono text-xs">
              {JSON.stringify(result.chunk_ids, null, 2)}
            </pre>
          </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
