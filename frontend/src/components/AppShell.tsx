"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpen,
  CircleDollarSign,
  Files,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Network,
  Search,
  Settings,
  Upload,
  AlertTriangle,
  Users,
} from "lucide-react";
import {
  AuthSession,
  fetchSession,
  logoutRequest,
  readCachedSession,
} from "@/lib/auth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ href: "/", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Knowledge",
    items: [{ href: "/documents", label: "Documents", icon: Files }],
  },
  {
    label: "Workspace",
    items: [
      { href: "/query", label: "Chat", icon: MessageSquare },
      { href: "/graph", label: "Knowledge Graph", icon: Network },
    ],
  },
  {
    label: "Ingestion",
    items: [
      { href: "/upload", label: "Upload", icon: Upload },
      { href: "/documents?status=failed", label: "Failed Processing", icon: AlertTriangle },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/ops", label: "Observability", icon: Activity },
      { href: "/usage", label: "Usage", icon: CircleDollarSign },
      { href: "/users", label: "Users", icon: Users, adminOnly: true },
      { href: "/settings", label: "Configuration", icon: Settings },
    ],
  },
];

function initials(name: string | null | undefined, email: string): string {
  const source = (name || email || "U").trim();
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] || "U") + (parts[1]?.[0] || "")).toUpperCase();
}

function navItemActive(
  href: string,
  pathname: string | null,
  searchParams: URLSearchParams,
): boolean {
  if (!pathname) return false;
  const [base, query = ""] = href.split("?");
  const required = new URLSearchParams(query);

  if (base === "/") {
    return pathname === "/";
  }

  const pathMatches =
    pathname === base || pathname.startsWith(`${base}/`);
  if (!pathMatches) return false;

  // Query-scoped items (e.g. Failed Processing) must match their params.
  if ([...required.keys()].length > 0) {
    for (const [key, value] of required.entries()) {
      if (searchParams.get(key) !== value) return false;
    }
    return true;
  }

  // Plain /documents must not stay active when a status filter is applied.
  if (base === "/documents" && searchParams.get("status")) {
    return false;
  }

  return true;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const isLogin = pathname === "/login";
  const isBareSource = Boolean(
    pathname && /\/documents\/[^/]+\/source\/?$/.test(pathname),
  );

  useEffect(() => {
    setSession(readCachedSession());
    void fetchSession().then(setSession).catch(() => setSession(null));
  }, [pathname]);

  const crumbs = useMemo(() => {
    if (!pathname || pathname === "/") return ["Dashboard"];
    const leaf = pathname.split("/").filter(Boolean)[0] || "Dashboard";
    return [leaf.charAt(0).toUpperCase() + leaf.slice(1)];
  }, [pathname]);

  if (isLogin || isBareSource) {
    return <div className="min-h-screen bg-background">{children}</div>;
  }

  const workspace =
    session?.tenant.display_name ||
    session?.tenant.tenant_key ||
    "Workspace";
  const displayName =
    session?.user.display_name || session?.user.email || "User";

  async function onLogout() {
    await logoutRequest();
    setSession(null);
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-border bg-sidebar">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">
            G
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">GraphRAG</p>
            <p className="text-[11px] text-muted">Enterprise platform</p>
          </div>
        </div>
        <div className="px-4 pb-3">
          <div className="rounded-lg border border-border bg-surface px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">
              Workspace
            </p>
            <p className="truncate text-sm font-medium">{workspace}</p>
          </div>
        </div>
        <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
          {NAV_GROUPS.map((group) => {
            const items = group.items.filter(
              (item) => !item.adminOnly || session?.user.role === "admin",
            );
            if (items.length === 0) return null;
            return (
            <div key={group.label}>
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {items.map((item) => {
                  const Icon = item.icon;
                  const active = navItemActive(item.href, pathname, searchParams);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                        active
                          ? "bg-accent-soft text-foreground"
                          : "text-muted hover:bg-surface hover:text-foreground",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
            );
          })}
        </nav>
        <Separator />
        <div className="flex items-center gap-3 px-4 py-4">
          <Avatar>
            <AvatarFallback>
              {initials(session?.user.display_name, session?.user.email || "U")}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{displayName}</p>
            <p className="truncate text-xs text-muted">
              {session?.user.role || "member"}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Sign out"
            onClick={() => void onLogout()}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-border bg-background/90 px-6 backdrop-blur">
          <div className="flex items-center gap-2 text-sm text-muted">
            <BookOpen className="h-4 w-4" />
            <span>{workspace}</span>
            <span>/</span>
            <span className="text-foreground">{crumbs.join(" / ")}</span>
          </div>
          <div className="mx-auto hidden w-full max-w-md md:block">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <Input
                className="h-9 pl-9"
                placeholder="Search documents, entities…"
                aria-label="Search"
              />
              <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted">
                ⌘K
              </kbd>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button asChild size="sm">
              <Link href="/upload">
                <Upload className="h-4 w-4" />
                Upload
              </Link>
            </Button>
            <Avatar className="h-8 w-8">
              <AvatarFallback>
                {initials(session?.user.display_name, session?.user.email || "U")}
              </AvatarFallback>
            </Avatar>
          </div>
        </header>
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}

/** @deprecated Tenant key is derived from the authenticated session. */
export function readTenantKey(): string {
  const session = readCachedSession();
  return session?.tenant.tenant_key || "demo";
}
