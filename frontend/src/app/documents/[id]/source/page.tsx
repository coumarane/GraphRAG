"use client";

import { Suspense, use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { DocumentOriginalPreview } from "@/components/DocumentOriginalPreview";
import { readTenantKey } from "@/components/AppShell";

type Props = {
  params: Promise<{ id: string }>;
};

function parsePage(raw: string | null): number | null {
  if (!raw) return null;
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value < 1) return null;
  return value;
}

function DocumentSourceView({ id }: { id: string }) {
  const searchParams = useSearchParams();
  const page = parsePage(searchParams.get("page"));
  const [title, setTitle] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`/api/documents/${id}`, {
          headers: { "X-Tenant-Key": readTenantKey() },
          cache: "no-store",
        });
        if (!res.ok) return;
        const body = (await res.json()) as { title?: string | null };
        if (!cancelled && body.title?.trim()) {
          setTitle(body.title.trim());
        }
      } catch {
        // Keep filename-only header if metadata fetch fails.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const heading = title || "Document";

  return (
    <section className="flex min-h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-4">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold text-foreground">
            {heading}
          </h1>
          <p className="truncate text-xs text-muted">
            {page != null ? `Page ${page}` : "Original file"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => window.close()}
          className="shrink-0 rounded border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-accent hover:text-foreground"
        >
          Close
        </button>
      </header>
      <div className="min-h-0 flex-1">
        <DocumentOriginalPreview documentId={id} page={page} fillViewport />
      </div>
    </section>
  );
}

export default function DocumentSourcePage({ params }: Props) {
  const { id } = use(params);

  return (
    <Suspense
      fallback={
        <p className="px-4 py-10 text-sm text-muted">Loading document…</p>
      }
    >
      <DocumentSourceView id={id} />
    </Suspense>
  );
}
