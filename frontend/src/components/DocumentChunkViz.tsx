"use client";

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

type PageGroup = {
  page: number;
  chunks: Chunk[];
};

function groupByPage(chunks: Chunk[]): PageGroup[] {
  const map = new Map<number, Chunk[]>();
  for (const chunk of chunks) {
    const page = chunk.page_start;
    const list = map.get(page) ?? [];
    list.push(chunk);
    map.set(page, list);
  }
  return [...map.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([page, pageChunks]) => ({ page, chunks: pageChunks }));
}

export function DocumentChunkViz({ chunks }: { chunks: Chunk[] }) {
  const pages = groupByPage(chunks);
  if (!pages.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        No indexed chunks yet. Wait until status is{" "}
        <code className="font-mono text-xs">ready</code>, then refresh.
      </p>
    );
  }

  const maxTokens = Math.max(
    1,
    ...chunks.map((c) => c.token_count || c.text.length / 4),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {pages.map(({ page, chunks: pageChunks }) => {
          const weight = pageChunks.reduce(
            (sum, c) => sum + (c.token_count || c.text.length / 4),
            0,
          );
          const intensity = 0.25 + 0.75 * Math.min(1, weight / (maxTokens * 3));
          return (
            <a
              key={page}
              href={`#page-${page}`}
              className="flex h-14 w-11 flex-col items-center justify-end rounded border border-border px-1 pb-1 pt-2 text-[10px] font-mono text-foreground transition-transform hover:-translate-y-0.5"
              style={{
                background: `linear-gradient(to top, rgba(13,115,119,${intensity}), rgba(255,255,255,0.9))`,
              }}
              title={`Page ${page} · ${pageChunks.length} chunks`}
            >
              <span className="mb-auto text-muted">p{page}</span>
              <span>{pageChunks.length}</span>
            </a>
          );
        })}
      </div>

      <div className="space-y-8">
        {pages.map(({ page, chunks: pageChunks }) => (
          <section
            key={page}
            id={`page-${page}`}
            className="scroll-mt-8 rounded-lg border border-border bg-surface shadow-sm"
          >
            <header className="flex items-center justify-between border-b border-border px-4 py-3">
              <h3 className="text-sm font-semibold">Page {page}</h3>
              <span className="font-mono text-xs text-muted">
                {pageChunks.length} chunk{pageChunks.length === 1 ? "" : "s"}
              </span>
            </header>
            <div className="divide-y divide-border">
              {pageChunks.map((chunk) => (
                <article key={chunk.chunk_id} className="px-4 py-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
                    <span className="rounded bg-background px-1.5 py-0.5">
                      {chunk.chunk_type}
                    </span>
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
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
