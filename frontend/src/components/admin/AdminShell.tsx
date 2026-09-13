"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  Boxes,
  ClipboardList,
  Cloud,
  Database,
  FileSearch,
  HeartPulse,
  MessageSquareText,
  Network,
  Plug,
  ScrollText,
  Settings,
  Sparkles,
  Tags,
  Users,
  Wallet,
} from "lucide-react";
import { fetchSession, readCachedSession, type AuthSession } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

export const ADMIN_NAV: NavGroup[] = [
  {
    label: "Operations",
    items: [
      { href: "/admin/connectors", label: "Connectors", icon: Plug },
      { href: "/admin/categories", label: "Categories", icon: Tags },
      { href: "/admin/chat-contexts", label: "Chat Contexts", icon: MessageSquareText },
      { href: "/admin/logs", label: "Application Logs", icon: ScrollText },
    ],
  },
  {
    label: "Organization",
    items: [{ href: "/users", label: "Users", icon: Users }],
  },
  {
    label: "Insights",
    items: [
      { href: "/admin/document-health", label: "Document Health", icon: HeartPulse },
      { href: "/admin/processing", label: "Processing", icon: Activity },
      { href: "/admin/knowledge-graph", label: "Knowledge Graph", icon: Network },
      { href: "/admin/feedback", label: "Feedback", icon: Sparkles },
      { href: "/admin/benchmarks", label: "Benchmarks", icon: BarChart3 },
      { href: "/admin/ingestion-audit", label: "Ingestion Audit", icon: ClipboardList },
      { href: "/admin/retrieval-audit", label: "Retrieval Audit", icon: FileSearch },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/admin/providers", label: "AI Providers", icon: Boxes },
      { href: "/admin/infrastructure", label: "Infrastructure", icon: Database },
      { href: "/admin/billing", label: "Billing", icon: Wallet },
      { href: "/admin/cloud-costs", label: "Cloud Costs", icon: Cloud },
      { href: "/admin/settings", label: "System Settings", icon: Settings },
    ],
  },
];

function isActive(href: string, pathname: string | null): boolean {
  if (!pathname) return false;
  if (href === "/users") return pathname === "/users" || pathname.startsWith("/users/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => {
    setSession(readCachedSession());
    void fetchSession().then(setSession).catch(() => setSession(null));
  }, [pathname]);

  const allowed = !session || session.user.role === "admin";

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="w-full shrink-0 lg:w-56">
        <nav className="space-y-5 lg:sticky lg:top-20">
          {ADMIN_NAV.map((group) => (
            <div key={group.label}>
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                {group.label}
              </p>
              <div className="flex gap-1 overflow-x-auto pb-1 lg:block lg:space-y-0.5 lg:overflow-visible lg:pb-0">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item.href, pathname);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        "flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
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
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1 space-y-4">
        <header>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Admin</h1>
          <p className="text-sm text-muted">
            Manage connectors, providers, and platform operations without leaving the workspace.
          </p>
        </header>
        {!allowed ? (
          <Card>
            <CardContent className="space-y-3 pt-5 text-sm text-danger">
              <p>Admin access required.</p>
              <Button variant="outline" size="sm" onClick={() => router.push("/")}>
                Back to dashboard
              </Button>
            </CardContent>
          </Card>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
