"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Files, AlertTriangle, CheckCircle2, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type DashboardPayload = {
  documents_total: number;
  documents_by_status: Record<string, number>;
  failed_processing: number;
  processing: number;
  ready: number;
  queries_total: number;
  recent_documents: Array<{
    document_id: string;
    title: string | null;
    status: string;
    updated_at: string | null;
  }>;
  processing_health: Array<{
    name: string;
    status: string;
    detail: string | null;
  }>;
  tenant_label: string | null;
};

function MetricCard({
  title,
  value,
  hint,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted">{title}</CardTitle>
        <Icon className="h-4 w-4 text-accent" />
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight">{value}</div>
        <p className="mt-1 text-xs text-muted">{hint}</p>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch("/api/ops/dashboard", {
          credentials: "include",
          cache: "no-store",
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(
            typeof body.detail === "string"
              ? body.detail
              : body.message || response.statusText,
          );
        }
        setData(body as DashboardPayload);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          Operations Dashboard
        </h1>
        <p className="text-sm text-muted">
          Live tenant metrics
          {data?.tenant_label ? ` · ${data.tenant_label}` : ""}
        </p>
      </div>

      {error ? (
        <Card className="border-danger/40">
          <CardContent className="pt-5 text-sm text-danger">{error}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Documents"
          value={data?.documents_total ?? "—"}
          hint={`${data?.ready ?? 0} ready`}
          icon={Files}
        />
        <MetricCard
          title="Failed Processing"
          value={data?.failed_processing ?? "—"}
          hint={`${data?.processing ?? 0} in progress`}
          icon={AlertTriangle}
        />
        <MetricCard
          title="Ready"
          value={data?.ready ?? "—"}
          hint="Indexed and queryable"
          icon={CheckCircle2}
        />
        <MetricCard
          title="RAG Queries"
          value={data?.queries_total ?? "—"}
          hint="Process counter snapshot"
          icon={MessageSquare}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Recent ingestion activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-muted">
                  <tr className="border-b border-border">
                    <th className="pb-2 font-medium">Document</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2 font-medium">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.recent_documents || []).map((row) => (
                    <tr key={row.document_id} className="border-b border-border/60">
                      <td className="py-3">
                        <Link
                          className="text-foreground hover:text-accent"
                          href={`/documents/${row.document_id}`}
                        >
                          {row.title || row.document_id.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="py-3">
                        <Badge
                          variant={
                            row.status === "ready"
                              ? "success"
                              : row.status === "failed"
                                ? "danger"
                                : "muted"
                          }
                        >
                          {row.status}
                        </Badge>
                      </td>
                      <td className="py-3 text-muted">
                        {row.updated_at
                          ? new Date(row.updated_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                  {!data?.recent_documents?.length ? (
                    <tr>
                      <td className="py-6 text-muted" colSpan={3}>
                        No documents yet. Upload to start ingestion.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Processing health</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(data?.processing_health || []).map((item) => (
              <div
                key={item.name}
                className="flex items-start justify-between rounded-lg border border-border bg-surface-elevated px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium">{item.name}</p>
                  {item.detail ? (
                    <p className="text-xs text-muted">{item.detail}</p>
                  ) : null}
                </div>
                <Badge
                  variant={
                    item.status === "ok"
                      ? "success"
                      : item.status === "down"
                        ? "danger"
                        : "warning"
                  }
                >
                  {item.status}
                </Badge>
              </div>
            ))}
            {!data?.processing_health?.length ? (
              <p className="text-sm text-muted">Health checks loading…</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
