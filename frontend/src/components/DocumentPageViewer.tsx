"use client";

import { useEffect, useMemo, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type Chunk = {
  chunk_id: string;
  page_start: number;
  page_end: number;
  chunk_type: string;
  modality: string;
  section_path: string[];
  text: string;
  token_count: number;
};

type PageBoundingBox = { x0: number; y0: number; x1: number; y1: number };

type PageElement = {
  element_id: string;
  element_type: string;
  page_start: number;
  page_end: number;
  bounding_box: PageBoundingBox | null;
  text: string;
};

export function DocumentPageViewer({
  documentId,
  chunks,
}: {
  documentId: string;
  chunks: Chunk[];
}) {
  const pageCount = useMemo(
    () => chunks.reduce((max, chunk) => Math.max(max, chunk.page_end), 1),
    [chunks],
  );
  const [page, setPage] = useState(1);
  const clampedPage = Math.min(Math.max(page, 1), pageCount);

  const [elements, setElements] = useState<PageElement[]>([]);
  const [layoutBusy, setLayoutBusy] = useState(true);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [activeElementId, setActiveElementId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLayoutBusy(true);
    setLayoutError(null);
    setImageError(false);
    setActiveElementId(null);
    void (async () => {
      try {
        const res = await fetch(
          `/api/documents/${documentId}/pages/${clampedPage}/layout`,
          { headers: { "X-Tenant-Key": readTenantKey() }, cache: "no-store" },
        );
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(
            typeof body.detail === "string" ? body.detail : `Layout failed (${res.status})`,
          );
        }
        if (!cancelled) setElements(body.elements ?? []);
      } catch (err) {
        if (!cancelled) setLayoutError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLayoutBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, clampedPage]);

  if (!chunks.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        No indexed content yet. Wait until status is{" "}
        <code className="font-mono text-xs">ready</code>, then refresh.
      </p>
    );
  }

  const imageSrc = `/api/documents/${documentId}/pages/${clampedPage}/render`;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={clampedPage <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          className="rounded border border-border bg-surface px-2 py-1 text-sm hover:border-accent disabled:opacity-40"
          aria-label="Previous page"
        >
          ‹
        </button>
        <span className="font-mono text-xs text-muted">
          Page {clampedPage} of {pageCount}
        </span>
        <button
          type="button"
          disabled={clampedPage >= pageCount}
          onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          className="rounded border border-border bg-surface px-2 py-1 text-sm hover:border-accent disabled:opacity-40"
          aria-label="Next page"
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="relative overflow-hidden rounded-lg border border-border bg-[#f7f8fa]">
          {imageError ? (
            <p className="px-5 py-10 text-sm text-danger">Unable to render this page.</p>
          ) : (
            <div className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                key={imageSrc}
                src={imageSrc}
                alt={`Page ${clampedPage}`}
                className="block w-full"
                onError={() => setImageError(true)}
              />
              {elements.map((el) =>
                el.bounding_box ? (
                  <div
                    key={el.element_id}
                    onMouseEnter={() => setActiveElementId(el.element_id)}
                    onMouseLeave={() =>
                      setActiveElementId((cur) => (cur === el.element_id ? null : cur))
                    }
                    onClick={() => setActiveElementId(el.element_id)}
                    className={`absolute cursor-pointer border transition-colors ${
                      activeElementId === el.element_id
                        ? "border-accent bg-accent/20"
                        : "border-transparent hover:border-accent/50 hover:bg-accent/10"
                    }`}
                    style={{
                      left: `${el.bounding_box.x0 * 100}%`,
                      top: `${el.bounding_box.y0 * 100}%`,
                      width: `${(el.bounding_box.x1 - el.bounding_box.x0) * 100}%`,
                      height: `${(el.bounding_box.y1 - el.bounding_box.y0) * 100}%`,
                    }}
                  />
                ) : null,
              )}
            </div>
          )}
        </div>

        <div className="max-h-[70vh] space-y-3 overflow-auto rounded-lg border border-border bg-surface p-4">
          {layoutBusy ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : layoutError ? (
            <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
              {layoutError}
            </p>
          ) : elements.length === 0 ? (
            <p className="text-sm text-muted">No indexed content on this page.</p>
          ) : (
            elements.map((el) => (
              <article
                key={el.element_id}
                onMouseEnter={() => setActiveElementId(el.element_id)}
                onMouseLeave={() =>
                  setActiveElementId((cur) => (cur === el.element_id ? null : cur))
                }
                onClick={() => setActiveElementId(el.element_id)}
                className={`cursor-pointer rounded-lg border px-3 py-2.5 transition-colors ${
                  activeElementId === el.element_id
                    ? "border-accent bg-accent/10"
                    : "border-border/60 bg-background hover:border-accent/40"
                }`}
              >
                <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
                  <span className="rounded bg-surface px-1.5 py-0.5">{el.element_type}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                  {el.text}
                </p>
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
