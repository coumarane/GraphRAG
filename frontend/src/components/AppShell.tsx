"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/documents", label: "Documents" },
  { href: "/upload", label: "Upload" },
  { href: "/query", label: "Chat" },
  { href: "/graph", label: "Graph" },
] as const;

const TENANT_KEY = "enterprise-rag-tenant-key";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [tenantKey, setTenantKey] = useState("demo");
  const [ready, setReady] = useState(false);
  const isBareSource = Boolean(
    pathname && /\/documents\/[^/]+\/source\/?$/.test(pathname),
  );

  useEffect(() => {
    const stored = window.localStorage.getItem(TENANT_KEY);
    if (stored) setTenantKey(stored);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    window.localStorage.setItem(TENANT_KEY, tenantKey);
  }, [tenantKey, ready]);

  if (isBareSource) {
    return <div className="min-h-screen bg-background">{children}</div>;
  }

  return (
    <div
      className={`mx-auto flex min-h-screen flex-col px-4 pb-16 pt-8 sm:px-6 ${
        pathname === "/query" ? "max-w-7xl" : "max-w-5xl"
      }`}
    >
      <header className="mb-10 flex flex-col gap-6 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-xs tracking-[0.18em] text-muted uppercase">
            Enterprise RAG
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Document workspace
          </h1>
        </div>
        <label className="flex flex-col gap-1 text-sm text-muted">
          Tenant key
          <input
            value={tenantKey}
            onChange={(e) => setTenantKey(e.target.value.trim() || "demo")}
            className="min-w-[12rem] rounded border border-border bg-surface px-3 py-2 font-mono text-sm text-foreground outline-none focus:border-accent"
            aria-label="Tenant key"
            suppressHydrationWarning
          />
        </label>
      </header>

      <nav className="mb-8 flex gap-1 border-b border-border">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-accent text-foreground"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <main className="flex-1">{children}</main>
    </div>
  );
}

export function readTenantKey(): string {
  if (typeof window === "undefined") return "demo";
  return window.localStorage.getItem(TENANT_KEY) || "demo";
}
