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
  FolderTree,
  HeartPulse,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  Network,
  Plug,
  ScrollText,
  Settings,
  Shield,
  Sparkles,
  Tags,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { fetchSession, readCachedSession, type AuthSession } from "@/lib/auth";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavGroup = {
  label: string;
  system?: boolean;
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
    items: [{ href: "/admin/users", label: "Users", icon: Users }],
  },
  {
    label: "Insights",
    system: true,
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
    system: true,
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
  return pathname === href || Boolean(pathname?.startsWith(`${href}/`));
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setSession(readCachedSession());
    void fetchSession().then(setSession).catch(() => setSession(null));
  }, [pathname]);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const allowed = !session || session.user.role === "admin";

  return (
    <div className="mx-auto flex min-h-screen max-w-[1400px] gap-5 px-4 py-5 sm:px-6">
      <aside className="sticky top-5 hidden h-[calc(100vh-2.5rem)] w-[260px] shrink-0 flex-col lg:flex">
        <AdminSidebar pathname={pathname} />
      </aside>

      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-[min(18rem,90vw)] overflow-y-auto bg-[#f4f5fb] p-3">
            <div className="mb-2 flex justify-end">
              <button type="button" onClick={() => setOpen(false)} aria-label="Close">
                <X className="h-5 w-5" />
              </button>
            </div>
            <AdminSidebar pathname={pathname} />
          </aside>
        </div>
      ) : null}

      <div className="min-w-0 flex-1">
        <div className="mb-4 flex items-start justify-between gap-3 lg:hidden">
          <button
            type="button"
            className="rounded-lg border border-[var(--border)] bg-white p-2"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>
        <header className="mb-4">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
              System
            </span>
          </div>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Manage connectors, users, AI providers, and infrastructure.
          </p>
        </header>
        {!allowed ? (
          <div className="rounded-2xl border border-[var(--border)] bg-white p-6 text-sm text-rose-600">
            Admin access required.
            <button
              type="button"
              className="ml-3 text-[var(--accent)] underline"
              onClick={() => router.push("/")}
            >
              Back to workspace
            </button>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

function AdminSidebar({ pathname }: { pathname: string | null }) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto pb-4">
      {ADMIN_NAV.map((group) => (
        <section
          key={group.label}
          className="rounded-2xl border border-[var(--border)] bg-white p-3 shadow-[0_8px_30px_rgba(28,34,55,0.04)]"
        >
          <button
            type="button"
            className={cn(
              "mb-2 flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm font-medium",
              group.items.some((item) => isActive(item.href, pathname))
                ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                : "text-[var(--foreground)]",
            )}
          >
            <span className="flex items-center gap-2">
              {group.label === "Operations" ? (
                <LayoutDashboard className="h-4 w-4" />
              ) : group.label === "Organization" ? (
                <FolderTree className="h-4 w-4" />
              ) : group.label === "Insights" ? (
                <Activity className="h-4 w-4" />
              ) : (
                <Shield className="h-4 w-4" />
              )}
              {group.label}
            </span>
            {group.system ? (
              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-amber-700">
                System
              </span>
            ) : null}
          </button>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href, pathname);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-xl px-3 py-2 text-sm",
                    active
                      ? "bg-[var(--accent-soft)] font-medium text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-[#f7f8fc] hover:text-[var(--foreground)]",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
