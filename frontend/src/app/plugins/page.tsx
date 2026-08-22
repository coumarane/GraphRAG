"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchSession, readCachedSession } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type TrustTier = "core" | "verified" | "community";

type PluginSelection = {
  capability: string;
  name: string;
  role: "backend" | "inspector" | "profile_primary";
};

type PluginItem = {
  plugin_name: string;
  capability: string;
  trust_tier: TrustTier;
  origin: "core" | "discovered";
  enabled: boolean;
  installed: boolean;
  extra: string | null;
  modules: string[];
  structured: boolean;
  selected: boolean;
};

type PluginCatalog = {
  enabled: boolean;
  allow_core_override: boolean;
  allowlist: string[] | null;
  selections: PluginSelection[];
  items: PluginItem[];
};

function capabilityLabel(raw: string): string {
  switch (raw) {
    case "parser":
      return "Parsers";
    case "object_store":
      return "Object store";
    case "vector_store":
      return "Vector store";
    case "graph_store":
      return "Graph store";
    case "metadata_store":
      return "Metadata store";
    case "ingest_queue":
      return "Ingest queue";
    default:
      return raw.replaceAll("_", " ");
  }
}

function roleLabel(role: PluginSelection["role"]): string {
  switch (role) {
    case "inspector":
      return "Inspector";
    case "profile_primary":
      return "Default profile";
    default:
      return "Selected backend";
  }
}

function allowlistLabel(allowlist: string[] | null): string {
  if (allowlist === null) return "Open (dev)";
  if (allowlist.length === 0) return "Core only";
  return `${allowlist.length} allowed`;
}

function tierVariant(tier: TrustTier) {
  if (tier === "core") return "default" as const;
  if (tier === "verified") return "success" as const;
  return "warning" as const;
}

export default function PluginsPage() {
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [catalog, setCatalog] = useState<PluginCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const session = readCachedSession() || (await fetchSession().catch(() => null));
      if (!session || session.user.role !== "admin") {
        setAllowed(false);
        setLoading(false);
        return;
      }
      try {
        const res = await fetch("/api/ops/plugins", { credentials: "include" });
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
              : `Unable to load plugins (${res.status})`,
          );
          return;
        }
        setCatalog((await res.json()) as PluginCatalog);
        setAllowed(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load plugins");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const grouped = useMemo(() => {
    const items = catalog?.items ?? [];
    const order: string[] = [];
    const byCapability = new Map<string, PluginItem[]>();
    for (const item of items) {
      if (!byCapability.has(item.capability)) {
        order.push(item.capability);
        byCapability.set(item.capability, []);
      }
      byCapability.get(item.capability)?.push(item);
    }
    return order.map((capability) => ({
      capability,
      items: byCapability.get(capability) || [],
    }));
  }, [catalog]);

  if (loading) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Plugins</h1>
        <p className="text-sm text-muted">Loading installed plugins…</p>
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Plugins</h1>
        <p className="text-sm text-danger">{error || "Admin access required"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Plugins</h1>
        <p className="text-sm text-muted">
          Installed factories in this process. Install and allowlist stay in
          packaging and YAML, not this page.
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
            <CardTitle className="text-sm text-muted">Discovery</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={catalog?.enabled ? "success" : "warning"}>
              {catalog?.enabled ? "enabled" : "disabled"}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted">Allowlist</CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-medium">
            {allowlistLabel(catalog?.allowlist ?? null)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted">Factories</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {catalog?.items.length ?? 0}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Active selections</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {(catalog?.selections || []).length === 0 ? (
            <p className="text-muted">No backend selections configured.</p>
          ) : (
            (catalog?.selections || []).map((row) => (
              <div
                key={`${row.capability}-${row.role}-${row.name}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2"
              >
                <div>
                  <p className="font-medium">{capabilityLabel(row.capability)}</p>
                  <p className="text-xs text-muted">{roleLabel(row.role)}</p>
                </div>
                <code className="text-xs">{row.name}</code>
              </div>
            ))
          )}
        </CardContent>
      </Card>
      {grouped.map((group) => (
        <Card key={group.capability}>
          <CardHeader>
            <CardTitle>{capabilityLabel(group.capability)}</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Name</th>
                  <th className="pb-2 pr-3 font-medium">Trust</th>
                  <th className="pb-2 pr-3 font-medium">Origin</th>
                  <th className="pb-2 pr-3 font-medium">Status</th>
                  <th className="pb-2 font-medium">Extra</th>
                </tr>
              </thead>
              <tbody>
                {group.items.map((item) => (
                  <tr key={`${item.capability}-${item.plugin_name}`} className="border-t border-border">
                    <td className="py-2.5 pr-3">
                      <span className="font-medium">{item.plugin_name}</span>
                      {item.selected ? (
                        <Badge className="ml-2" variant="success">
                          selected
                        </Badge>
                      ) : null}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge variant={tierVariant(item.trust_tier)}>{item.trust_tier}</Badge>
                    </td>
                    <td className="py-2.5 pr-3 text-muted">{item.origin}</td>
                    <td className="py-2.5 pr-3">
                      {!item.enabled ? (
                        <Badge variant="muted">blocked</Badge>
                      ) : item.installed ? (
                        <Badge variant="success">installed</Badge>
                      ) : (
                        <Badge variant="warning">extra missing</Badge>
                      )}
                    </td>
                    <td className="py-2.5 text-muted">
                      {item.extra || (item.structured ? "structured" : "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
