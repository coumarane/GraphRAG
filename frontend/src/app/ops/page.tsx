"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Health = { status: string };
type Metrics = Record<string, unknown>;

export default function OpsPage() {
  const [ready, setReady] = useState<Health | null>(null);
  const [live, setLive] = useState<Health | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [liveRes, readyRes, metricsRes] = await Promise.all([
          fetch("/api/health/live").catch(() => null),
          fetch("/api/health/ready").catch(() => null),
          fetch("/api/ops/dashboard", { credentials: "include" }),
        ]);
        if (liveRes?.ok) setLive(await liveRes.json());
        if (readyRes?.ok) setReady(await readyRes.json());
        if (metricsRes.ok) setMetrics(await metricsRes.json());
        else {
          const body = await metricsRes.json().catch(() => ({}));
          setError(
            typeof body.detail === "string"
              ? body.detail
              : body.message || metricsRes.statusText,
          );
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Observability</h1>
        <p className="text-sm text-muted">
          Live readiness and tenant operational snapshot
        </p>
      </div>
      {error ? (
        <Card className="border-danger/40">
          <CardContent className="pt-5 text-sm text-danger">{error}</CardContent>
        </Card>
      ) : null}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted">API live</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={live?.status === "ok" ? "success" : "warning"}>
              {live?.status || "unknown"}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted">API ready</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={ready?.status === "ready" ? "success" : "warning"}>
              {ready?.status || "unknown"}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted">Documents</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {typeof metrics?.documents_total === "number"
              ? metrics.documents_total
              : "—"}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Status breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded-lg bg-surface-elevated p-4 text-xs text-muted">
            {JSON.stringify(metrics?.documents_by_status || {}, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
