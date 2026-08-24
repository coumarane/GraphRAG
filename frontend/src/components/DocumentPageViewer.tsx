"use client";

import { useMemo, useState } from "react";
import { DocumentOriginalPreview } from "@/components/DocumentOriginalPreview";

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
  const pageChunks = useMemo(
    () =>
      chunks
        .filter((chunk) => chunk.page_start <= clampedPage && clampedPage <= chunk.page_end)
        .sort((a, b) => a.page_start - b.page_start),
    [chunks, clampedPage],
  );

  if (!chunks.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        No indexed content yet. Wait until status is{" "}
        <code className="font-mono text-xs">ready</code>, then refresh.
      </p>
    );
  }

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
        <DocumentOriginalPreview documentId={documentId} page={clampedPage} />

        <div className="max-h-[70vh] space-y-3 overflow-auto rounded-lg border border-border bg-surface p-4">
          {pageChunks.length === 0 ? (
            <p className="text-sm text-muted">No indexed content on this page.</p>
          ) : (
            pageChunks.map((chunk) => (
              <article
                key={chunk.chunk_id}
                className="rounded-lg border border-border/60 bg-background px-3 py-2.5"
              >
                <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
                  <span className="rounded bg-surface px-1.5 py-0.5">{chunk.chunk_type}</span>
                  <span>{chunk.modality}</span>
                  {chunk.section_path.length ? (
                    <span>{chunk.section_path.join(" / ")}</span>
                  ) : null}
                  <span>{chunk.token_count} tok</span>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                  {chunk.text}
                </p>
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
