"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type DailySpend = {
  date: string;
  spend_usd: number;
  tokens: number;
  requests: number;
};

type CapabilitySpend = {
  capability: string;
  spend_usd: number;
  tokens: number;
  requests: number;
  input_tokens: number;
};

type ModelSpend = {
  model_name: string;
  spend_usd: number;
  tokens: number;
  requests: number;
};

type UsagePayload = {
  from_date: string;
  to_date: string;
  total_spend_usd: number;
  total_tokens: number;
  total_requests: number;
  month_spend_usd: number;
  daily_spend: DailySpend[];
  by_capability: CapabilitySpend[];
  by_model: ModelSpend[];
};

const RANGES = [
  { label: "7d", days: 7 },
  { label: "14d", days: 14 },
  { label: "30d", days: 30 },
] as const;

function isoDaysAgo(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setUTCDate(to.getUTCDate() - (days - 1));
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "$0.00";
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function capabilityLabel(raw: string): string {
  switch (raw) {
    case "chat_completions":
      return "Chat Completions";
    case "vision":
      return "Vision";
    case "embeddings":
      return "Embeddings";
    default:
      return raw;
  }
}

export default function UsagePage() {
  const [days, setDays] = useState<7 | 14 | 30>(14);
  const [data, setData] = useState<UsagePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (rangeDays: 7 | 14 | 30) => {
    setLoading(true);
    setError(null);
    const { from, to } = isoDaysAgo(rangeDays);
    try {
      const res = await fetch(`/api/ops/usage?from=${from}&to=${to}`, {
        credentials: "include",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || `Usage API failed (${res.status})`,
        );
      }
      setData(body as UsagePayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const maxDaily = useMemo(() => {
    if (!data?.daily_spend?.length) return 1;
    return Math.max(0.0001, ...data.daily_spend.map((row) => row.spend_usd));
  }, [data]);

  const capabilityMap = useMemo(() => {
    const map = new Map<string, CapabilitySpend>();
    for (const row of data?.by_capability || []) {
      map.set(row.capability, row);
    }
    return map;
  }, [data]);

  const caps = ["chat_completions", "vision", "embeddings"] as const;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
          <p className="text-sm text-muted">
            Estimated OpenAI spend from chat, vision, and embedding calls
          </p>
        </div>
        <div className="flex items-center gap-2">
          {RANGES.map((range) => (
            <Button
              key={range.label}
              size="sm"
              variant={days === range.days ? "default" : "outline"}
              onClick={() => setDays(range.days)}
            >
              {range.label}
            </Button>
          ))}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void load(days)}
            disabled={loading}
          >
            Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <Card className="border-danger/40">
          <CardContent className="pt-5 text-sm text-danger">{error}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Total spend</CardTitle>
              <p className="mt-1 text-3xl font-semibold tracking-tight">
                {formatUsd(data?.total_spend_usd ?? 0)}
              </p>
            </div>
            <Badge variant="muted">
              {data ? `${data.from_date} → ${data.to_date}` : "—"}
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="flex h-48 items-end gap-1.5">
              {(data?.daily_spend || []).map((row) => {
                const height = Math.max(2, (row.spend_usd / maxDaily) * 100);
                return (
                  <div
                    key={row.date}
                    className="group relative flex min-w-0 flex-1 flex-col items-center justify-end"
                    title={`${row.date}: ${formatUsd(row.spend_usd)} · ${row.requests} req`}
                  >
                    <div
                      className="w-full rounded-t bg-foreground/80 transition-opacity group-hover:opacity-90"
                      style={{ height: `${height}%` }}
                    />
                    <span className="mt-1 hidden text-[10px] text-muted sm:block">
                      {row.date.slice(5)}
                    </span>
                  </div>
                );
              })}
              {!data?.daily_spend?.length && !loading ? (
                <p className="text-sm text-muted">No usage in this range yet.</p>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm text-muted">Month to date</CardTitle>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {formatUsd(data?.month_spend_usd ?? 0)}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm text-muted">Total tokens</CardTitle>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {formatTokens(data?.total_tokens ?? 0)}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm text-muted">Total requests</CardTitle>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {formatTokens(data?.total_requests ?? 0)}
            </CardContent>
          </Card>
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium text-muted">API capabilities</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {caps.map((cap) => {
            const row = capabilityMap.get(cap);
            return (
              <Card key={cap}>
                <CardHeader>
                  <CardTitle className="text-base">{capabilityLabel(cap)}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted">Requests</span>
                    <span>{formatTokens(row?.requests ?? 0)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Input tokens</span>
                    <span>{formatTokens(row?.input_tokens ?? 0)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Spend</span>
                    <span>{formatUsd(row?.spend_usd ?? 0)}</span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Models</CardTitle>
        </CardHeader>
        <CardContent>
          {(data?.by_model || []).length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-muted">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-4 font-medium">Model</th>
                    <th className="py-2 pr-4 font-medium">Requests</th>
                    <th className="py-2 pr-4 font-medium">Tokens</th>
                    <th className="py-2 font-medium">Spend</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.by_model.map((row) => (
                    <tr key={row.model_name} className="border-b border-border/60">
                      <td className="py-2 pr-4 font-mono text-xs">{row.model_name}</td>
                      <td className="py-2 pr-4">{formatTokens(row.requests)}</td>
                      <td className="py-2 pr-4">{formatTokens(row.tokens)}</td>
                      <td className="py-2">{formatUsd(row.spend_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted">
              {loading ? "Loading…" : "No model usage recorded yet."}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
