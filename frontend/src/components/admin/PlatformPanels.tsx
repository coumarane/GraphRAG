"use client";

import { useEffect, useState } from "react";
import { adminJson, formatEur } from "@/lib/admin";
import {
  AdminButton,
  AdminCard,
  AdminField,
  AdminToggle,
  ErrorBanner,
  Stat,
  adminInputClass,
} from "@/components/admin/widgets";
import { ConfirmDialog } from "@/components/ConfirmDialog";

type Provider = {
  id: string;
  name: string;
  model: string;
  active: boolean;
  health: string;
  has_key: boolean;
  secret_name: string;
  base_url?: string;
  default?: boolean;
};

export function ProvidersPanel() {
  const [data, setData] = useState<{ items: Provider[]; default_provider: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(await adminJson<{ items: Provider[]; default_provider: string }>("/providers"));
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
      <p className="text-sm text-[var(--muted)]">
        Use Set API key for chat & documents on the Default provider. Keys are never stored as plaintext.
      </p>
      <ErrorBanner error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        {(data?.items || []).map((item) => (
          <AdminCard key={item.id} className={item.default ? "ring-2 ring-[var(--accent)]" : ""}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{item.name}</h3>
              <div className="flex gap-2 text-xs">
                {item.default ? (
                  <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[var(--accent)]">
                    Default
                  </span>
                ) : null}
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">
                  {item.active ? "Active" : "Idle"}
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm text-[var(--muted)]">{item.model}</p>
            <p className="mt-1 text-xs text-[var(--muted)]">API key {item.secret_name}</p>
            <p className="mt-1 text-sm">
              Health{" "}
              <span className={item.health === "healthy" ? "text-emerald-600" : "text-rose-600"}>
                {item.health}
              </span>
            </p>
            <div className="mt-4 space-y-2">
              <AdminButton>Set API key for chat & documents</AdminButton>
              <AdminButton
                variant="ghost"
                onClick={() =>
                  void adminJson<unknown>(`/providers/${item.id}/sync`, { method: "POST" }).then(load)
                }
              >
                Sync models
              </AdminButton>
            </div>
          </AdminCard>
        ))}
      </div>
    </div>
  );
}

export function InfrastructurePanel() {
  const [data, setData] = useState<{
    services: Array<{ name: string; ok: boolean; detail: string }>;
    semantic_cache: {
      redis_keys: number;
      redis_memory_bytes: number;
      qdrant_vectors: number;
      qdrant_disk_bytes: number;
    };
    database: Record<string, number>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(
        await adminJson<{
          services: Array<{ name: string; ok: boolean; detail: string }>;
          semantic_cache: {
            redis_keys: number;
            redis_memory_bytes: number;
            qdrant_vectors: number;
            qdrant_disk_bytes: number;
          };
          database: Record<string, number>;
        }>("/infrastructure"),
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
      <ErrorBanner error={error} />
      <AdminCard>
        <h2 className="mb-3 font-semibold">Service Health</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {(data?.services || []).map((service) => (
            <div key={service.name} className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3">
              <p className="text-sm font-medium">{service.name}</p>
              <p className="text-xs text-emerald-700">{service.ok ? "OK" : "Down"}</p>
              <p className="text-xs text-[var(--muted)]">{service.detail}</p>
            </div>
          ))}
        </div>
      </AdminCard>
      <AdminCard>
        <h2 className="mb-3 font-semibold">Semantic Cache</h2>
        <div className="grid grid-cols-4 gap-3 text-center">
          <Stat label="Redis keys" value={data?.semantic_cache.redis_keys ?? 0} />
          <Stat
            label="Redis memory"
            value={`${(((data?.semantic_cache.redis_memory_bytes || 0) / 1024 / 1024) || 0).toFixed(2)} MB`}
          />
          <Stat label="Qdrant vectors" value={data?.semantic_cache.qdrant_vectors ?? 0} />
          <Stat
            label="Qdrant disk"
            value={`${(((data?.semantic_cache.qdrant_disk_bytes || 0) / 1024 / 1024) || 0).toFixed(0)} MB`}
          />
        </div>
        <div className="mt-3">
          <AdminButton
            variant="danger"
            onClick={() =>
              void adminJson<unknown>("/infrastructure/cache/clear", { method: "POST" }).then(load)
            }
          >
            Clear cache
          </AdminButton>
        </div>
      </AdminCard>
      <AdminCard>
        <h2 className="mb-3 font-semibold">Database</h2>
        <div className="grid grid-cols-4 gap-3">
          <Stat label="Documents" value={data?.database.documents ?? 0} />
          <Stat label="Chunks" value={data?.database.chunks ?? 0} />
          <Stat label="Messages" value={data?.database.messages ?? 0} />
          <Stat label="Conversations" value={data?.database.conversations ?? 0} />
        </div>
      </AdminCard>
    </div>
  );
}

export function BillingPanel() {
  const [data, setData] = useState<{
    all_time_eur: number;
    month_eur: number;
    today_eur: number;
    daily: Array<{ date: string; eur: number }>;
    by_provider: Array<{ provider: string; requests: number; eur: number; share: number }>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void adminJson<{
      all_time_eur: number;
      month_eur: number;
      today_eur: number;
      daily: Array<{ date: string; eur: number }>;
      by_provider: Array<{ provider: string; requests: number; eur: number; share: number }>;
    }>("/billing")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const max = Math.max(0.01, ...(data?.daily || []).map((row) => row.eur));

  return (
    <div className="space-y-4">
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="All-time spend" value={formatEur(data?.all_time_eur || 0)} tone="soft" />
        <Stat label="This month (UTC)" value={formatEur(data?.month_eur || 0)} />
        <Stat label="Today (UTC)" value={formatEur(data?.today_eur || 0)} />
      </div>
      <AdminCard>
        <h3 className="mb-3 font-medium">Daily Spend — Last 30 Days (UTC)</h3>
        <div className="flex h-40 items-end gap-1">
          {(data?.daily || []).map((row) => (
            <div
              key={row.date}
              className="flex-1 rounded-t bg-[var(--accent)]"
              style={{ height: `${(row.eur / max) * 100}%` }}
              title={`${row.date} ${formatEur(row.eur)}`}
            />
          ))}
        </div>
      </AdminCard>
      <AdminCard>
        <h3 className="mb-3 font-medium">Spend by Provider</h3>
        {(data?.by_provider || []).map((row) => (
          <div key={row.provider} className="mb-2 flex items-center gap-3 text-sm">
            <span className="w-40">{row.provider}</span>
            <span className="w-20 text-[var(--muted)]">{row.requests}</span>
            <span className="w-24">{formatEur(row.eur)}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full bg-[var(--accent)]"
                style={{ width: `${Math.round(row.share * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </AdminCard>
    </div>
  );
}

export function CloudCostsPanel() {
  const [data, setData] = useState<{
    month_eur: number;
    note: string;
    items: Array<{ service: string; eur: number; detail: string }>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void adminJson<{
      month_eur: number;
      note: string;
      items: Array<{ service: string; eur: number; detail: string }>;
    }>("/cloud-costs")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <AdminCard>
      <h2 className="text-lg font-semibold">Cloud Costs</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">{data?.note}</p>
      <ErrorBanner error={error} />
      <div className="mt-4">
        <Stat label="Estimated month" value={formatEur(data?.month_eur || 0)} tone="soft" />
      </div>
      <div className="mt-4 space-y-2">
        {(data?.items || []).map((item) => (
          <div key={item.service} className="flex items-center justify-between rounded-xl border border-[var(--border)] px-3 py-2 text-sm">
            <div>
              <p className="font-medium">{item.service}</p>
              <p className="text-[var(--muted)]">{item.detail}</p>
            </div>
            <p>{formatEur(item.eur)}</p>
          </div>
        ))}
      </div>
    </AdminCard>
  );
}

export function SettingsPanel() {
  const [data, setData] = useState<{
    parse_acceleration_mode: string;
    pipeline_audit_enabled: boolean;
    semantic_cache_enabled: boolean;
    danger_zone_enabled: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "chat" | "graph" | "vectors" | "reprocess">(null);

  async function load() {
    try {
      setData(
        await adminJson<{
          parse_acceleration_mode: string;
          pipeline_audit_enabled: boolean;
          semantic_cache_enabled: boolean;
          danger_zone_enabled: boolean;
        }>("/settings"),
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function runDanger() {
    const path =
      confirm === "chat"
        ? "/danger/clear-chat"
        : confirm === "graph"
          ? "/danger/wipe-graph"
          : confirm === "vectors"
            ? "/danger/wipe-vectors"
            : "/danger/reprocess-all";
    await adminJson<unknown>(path, { method: "POST" });
    setConfirm(null);
  }

  return (
    <AdminCard>
      <h2 className="text-lg font-semibold">System Settings</h2>
      <p className="text-sm text-[var(--muted)]">
        Live-editable runtime parameters. Changes apply immediately for this process.
      </p>
      <ErrorBanner error={error} />
      <div className="mt-4 space-y-4">
        <AdminField label="PARSE_ACCELERATION_MODE">
          <select
            className={adminInputClass}
            value={data?.parse_acceleration_mode || "cpu"}
            onChange={(event) =>
              void adminJson<unknown>("/settings", {
                method: "PATCH",
                body: JSON.stringify({ parse_acceleration_mode: event.target.value }),
              }).then(load)
            }
          >
            <option value="cpu">cpu — always CPU worker</option>
            <option value="auto">auto — scanned / vision-heavy PDFs on GPU</option>
            <option value="gpu">gpu — dedicated GPU worker</option>
          </select>
        </AdminField>
        <div className="flex items-center justify-between rounded-xl border border-[var(--border)] px-3 py-3">
          <div>
            <p className="font-medium">PIPELINE_AUDIT_ENABLED</p>
            <p className="text-sm text-[var(--muted)]">
              Record step timings and page/element provenance for every document ingestion.
            </p>
          </div>
          <AdminToggle
            checked={Boolean(data?.pipeline_audit_enabled)}
            onChange={(pipeline_audit_enabled) =>
              void adminJson<unknown>("/settings", {
                method: "PATCH",
                body: JSON.stringify({ pipeline_audit_enabled }),
              }).then(load)
            }
          />
        </div>
      </div>
      <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-4">
        <h3 className="font-semibold text-rose-700">Danger zone</h3>
        <p className="mt-1 text-sm text-rose-700">
          Development-only data resets. Automatically disabled in production.
        </p>
        {!data?.danger_zone_enabled ? (
          <p className="mt-2 text-sm">Danger zone is disabled in this environment.</p>
        ) : (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between">
              <span>Clear chat history</span>
              <AdminButton variant="danger" onClick={() => setConfirm("chat")}>
                Clear chat
              </AdminButton>
            </div>
            <div className="flex items-center justify-between">
              <span>Wipe knowledge graph</span>
              <AdminButton variant="danger" onClick={() => setConfirm("graph")}>
                Wipe graph
              </AdminButton>
            </div>
            <div className="flex items-center justify-between">
              <span>Wipe vector store</span>
              <AdminButton variant="danger" onClick={() => setConfirm("vectors")}>
                Wipe vectors
              </AdminButton>
            </div>
            <div className="flex items-center justify-between">
              <span>Reprocess all documents</span>
              <AdminButton onClick={() => setConfirm("reprocess")}>Reprocess all</AdminButton>
            </div>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={Boolean(confirm)}
        title="Irreversible action"
        description="This cannot be undone. Continue only if you intend to reset tenant data."
        danger
        confirmLabel="Confirm"
        onCancel={() => setConfirm(null)}
        onConfirm={() => void runDanger()}
      />
    </AdminCard>
  );
}
