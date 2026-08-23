"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { fetchSession, readCachedSession } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  install_hint: string | null;
};

type DiscoverablePlugin = {
  plugin_name: string;
  capability: string;
  trust_tier: TrustTier;
  status: "missing_extra" | "blocked" | "not_registered";
  extra: string | null;
  install_hint: string;
  docs_url: string | null;
};

type PluginCatalog = {
  enabled: boolean;
  allow_core_override: boolean;
  allowlist: string[] | null;
  selections: PluginSelection[];
  items: PluginItem[];
  discoverable: DiscoverablePlugin[];
};

type McpToolInfo = {
  name: string;
  description: string;
};

type McpOpsStatus = {
  enabled: boolean;
  endpoint: string;
  tools: McpToolInfo[];
  auth_headers_required: string[];
  notes: string[];
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
    case "mcp":
      return "MCP";
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

function statusLabel(status: DiscoverablePlugin["status"]): string {
  switch (status) {
    case "blocked":
      return "blocked";
    case "missing_extra":
      return "extra missing";
    default:
      return "not registered";
  }
}

function mcpPublicUrl(endpoint: string): string {
  const base =
    (typeof process !== "undefined" &&
      process.env.NEXT_PUBLIC_RAG_API_URL?.replace(/\/$/, "")) ||
    "https://YOUR_API_HOST";
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  return `${base}${path}`;
}

function cursorMcpConfig(url: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        graphrag: {
          url,
          headers: {
            "X-Api-Service-Key": "YOUR_API_SERVICE_KEY",
            "X-Tenant-Key": "demo",
            "X-Principal": "cursor-operator",
          },
        },
      },
    },
    null,
    2,
  );
}

function claudeMcpConfig(url: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        graphrag: {
          type: "http",
          url,
          headers: {
            "X-Api-Service-Key": "YOUR_API_SERVICE_KEY",
            "X-Tenant-Key": "demo",
            "X-Principal": "claude-desktop",
          },
        },
      },
    },
    null,
    2,
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function PluginsPage() {
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [catalog, setCatalog] = useState<PluginCatalog | null>(null);
  const [mcp, setMcp] = useState<McpOpsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const session = readCachedSession() || (await fetchSession().catch(() => null));
      if (!session || session.user.role !== "admin") {
        setAllowed(false);
        setLoading(false);
        return;
      }
      try {
        const [pluginsRes, mcpRes] = await Promise.all([
          fetch("/api/ops/plugins", { credentials: "include" }),
          fetch("/api/ops/mcp", { credentials: "include" }),
        ]);
        if (pluginsRes.status === 403 || mcpRes.status === 403) {
          setAllowed(false);
          setError("Admin access required");
          return;
        }
        if (!pluginsRes.ok) {
          const body = await pluginsRes.json().catch(() => ({}));
          setError(
            typeof body.detail === "string"
              ? body.detail
              : `Unable to load plugins (${pluginsRes.status})`,
          );
          return;
        }
        setCatalog((await pluginsRes.json()) as PluginCatalog);
        if (mcpRes.ok) {
          setMcp((await mcpRes.json()) as McpOpsStatus);
        }
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

  const profilePrimary = catalog?.selections.find(
    (row) => row.role === "profile_primary",
  );

  async function onCopy(label: string, text: string) {
    const ok = await copyText(text);
    setCopied(ok ? label : "failed");
    window.setTimeout(() => setCopied(null), 2000);
  }

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

  const mcpUrl = mcpPublicUrl(mcp?.endpoint || "/api/v1/mcp/");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Plugins</h1>
          <p className="text-sm text-muted">
            Installed factories in this process. Install and allowlist stay in
            packaging and YAML, not this page.
          </p>
        </div>
        <Button asChild variant="secondary" size="sm">
          <Link href="/pipeline-builder">Open Pipeline Builder</Link>
        </Button>
      </div>
      {error ? (
        <Card className="border-danger/40">
          <CardContent className="pt-5 text-sm text-danger">{error}</CardContent>
        </Card>
      ) : null}

      <div className="flex flex-wrap gap-2 text-xs text-muted">
        <span>Trust tiers:</span>
        <Badge variant="default">core</Badge>
        <Badge variant="success">verified</Badge>
        <Badge variant="warning">community</Badge>
      </div>

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
                <div className="flex items-center gap-2">
                  <code className="text-xs">{row.name}</code>
                  {row.role === "profile_primary" ? (
                    <Button asChild variant="ghost" size="sm">
                      <Link href="/pipeline-builder">Edit defaults</Link>
                    </Button>
                  ) : null}
                </div>
              </div>
            ))
          )}
          {profilePrimary ? (
            <p className="text-xs text-muted">
              Default parser profile primary is{" "}
              <code>{profilePrimary.name}</code>. Chunking and retrieval knobs
              live in Pipeline Builder.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Discover</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {(catalog?.discoverable || []).length === 0 ? (
            <p className="text-muted">
              Nothing to discover — all registered plugins are installed and
              allowed.
            </p>
          ) : (
            (catalog?.discoverable || []).map((row) => (
              <div
                key={`${row.capability}-${row.plugin_name}-${row.status}`}
                className="rounded-lg border border-border px-3 py-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{row.plugin_name}</span>
                  <Badge variant="muted">{capabilityLabel(row.capability)}</Badge>
                  <Badge variant={tierVariant(row.trust_tier)}>{row.trust_tier}</Badge>
                  <Badge
                    variant={
                      row.status === "blocked"
                        ? "muted"
                        : row.status === "missing_extra"
                          ? "warning"
                          : "default"
                    }
                  >
                    {statusLabel(row.status)}
                  </Badge>
                </div>
                <p className="mt-2 text-muted">{row.install_hint}</p>
                {row.extra ? (
                  <p className="mt-1 text-xs text-muted">
                    Extra: <code>{row.extra}</code>
                  </p>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>MCP server</CardTitle>
            <Badge variant={mcp?.enabled ? "success" : "warning"}>
              {mcp?.enabled ? "enabled" : "disabled"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          {!mcp ? (
            <p className="text-muted">Unable to load MCP status.</p>
          ) : (
            <>
              <div className="space-y-1">
                <p>
                  Endpoint: <code>{mcp.endpoint}</code>
                </p>
                <p className="text-xs text-muted">
                  Public URL for clients: <code>{mcpUrl}</code>
                </p>
                <p className="text-xs text-muted">
                  Required headers: {mcp.auth_headers_required.join(", ")}
                </p>
              </div>
              {(mcp.notes || []).length > 0 ? (
                <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
                  {mcp.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void onCopy("cursor", cursorMcpConfig(mcpUrl))}
                >
                  {copied === "cursor" ? "Copied Cursor config" : "Copy Cursor config"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void onCopy("claude", claudeMcpConfig(mcpUrl))}
                >
                  {copied === "claude" ? "Copied Claude config" : "Copy Claude config"}
                </Button>
                {copied === "failed" ? (
                  <span className="text-xs text-danger">Clipboard unavailable</span>
                ) : null}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[28rem] text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="pb-2 pr-3 font-medium">Tool</th>
                      <th className="pb-2 font-medium">Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mcp.tools.map((tool) => (
                      <tr key={tool.name} className="border-t border-border">
                        <td className="py-2 pr-3 font-mono text-xs">{tool.name}</td>
                        <td className="py-2 text-muted">{tool.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {grouped.map((group) => (
        <Card key={group.capability}>
          <CardHeader>
            <CardTitle>{capabilityLabel(group.capability)}</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Name</th>
                  <th className="pb-2 pr-3 font-medium">Trust</th>
                  <th className="pb-2 pr-3 font-medium">Origin</th>
                  <th className="pb-2 pr-3 font-medium">Status</th>
                  <th className="pb-2 font-medium">Hint</th>
                </tr>
              </thead>
              <tbody>
                {group.items.map((item) => (
                  <tr
                    key={`${item.capability}-${item.plugin_name}`}
                    className="border-t border-border align-top"
                  >
                    <td className="py-2.5 pr-3">
                      <span className="font-medium">{item.plugin_name}</span>
                      {item.selected ? (
                        <Badge className="ml-2" variant="success">
                          selected
                        </Badge>
                      ) : null}
                      {item.extra ? (
                        <p className="mt-1 text-xs text-muted">
                          extra <code>{item.extra}</code>
                        </p>
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
                    <td className="py-2.5 text-xs text-muted">
                      {item.install_hint || (item.structured ? "structured" : "—")}
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
