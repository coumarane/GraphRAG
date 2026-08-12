"use client";

import { useEffect, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type Props = {
  documentId: string;
  /** 1-based PDF page to open when available. */
  page?: number | null;
  /** Fill the viewport (source viewer tab). */
  fillViewport?: boolean;
};

export function DocumentOriginalPreview({
  documentId,
  page,
  fillViewport = false,
}: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [contentType, setContentType] = useState("");
  const [filename, setFilename] = useState("document");
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;

    void (async () => {
      setBusy(true);
      setError(null);
      setObjectUrl(null);
      setTextPreview(null);
      try {
        const res = await fetch(`/api/documents/${documentId}/original`, {
          headers: { "X-Tenant-Key": readTenantKey() },
          cache: "no-store",
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            typeof body.detail === "string"
              ? body.detail
              : `Preview failed (${res.status})`,
          );
        }
        const type =
          res.headers.get("Content-Type") || "application/octet-stream";
        const disposition = res.headers.get("Content-Disposition") || "";
        const match = /filename="([^"]+)"/.exec(disposition);
        const name = match?.[1] || "document";
        const blob = await res.blob();
        if (cancelled) return;

        setContentType(type);
        setFilename(name);

        const isText =
          type.startsWith("text/") ||
          type.includes("json") ||
          /\.(txt|md|csv|json)$/i.test(name);

        if (isText) {
          setTextPreview(await blob.text());
        } else {
          const url = URL.createObjectURL(blob);
          revoked = url;
          setObjectUrl(url);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();

    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [documentId]);

  const frameClass = fillViewport
    ? "h-[calc(100vh-3.5rem)] w-full bg-[#f7f8fa]"
    : "h-[70vh] w-full bg-[#f7f8fa]";
  const pageFragment =
    typeof page === "number" && Number.isFinite(page) && page >= 1
      ? `#page=${Math.floor(page)}`
      : "";

  if (busy) {
    return (
      <p
        className={`rounded-lg border border-border bg-surface px-5 py-10 text-sm text-muted ${
          fillViewport ? "min-h-[50vh]" : ""
        }`}
      >
        Loading original preview…
      </p>
    );
  }

  if (error) {
    return (
      <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
        {error}
      </p>
    );
  }

  if (textPreview != null) {
    return (
      <pre
        className={`overflow-auto rounded-lg border border-border bg-surface p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap ${
          fillViewport ? "max-h-[calc(100vh-3.5rem)]" : "max-h-[70vh]"
        }`}
      >
        {textPreview}
      </pre>
    );
  }

  if (objectUrl && (contentType.includes("pdf") || /\.pdf$/i.test(filename))) {
    return (
      <div
        className={`overflow-hidden bg-surface ${
          fillViewport
            ? "border-0"
            : "rounded-lg border border-border shadow-sm"
        }`}
      >
        {!fillViewport ? (
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <p className="font-mono text-xs text-muted">{filename}</p>
            <a
              href={`${objectUrl}${pageFragment}`}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent hover:underline"
            >
              Open in new tab
            </a>
          </div>
        ) : null}
        <iframe
          key={`${objectUrl}${pageFragment}`}
          src={`${objectUrl}${pageFragment}`}
          title={`Preview ${filename}`}
          className={frameClass}
        />
      </div>
    );
  }

  if (objectUrl && contentType.startsWith("image/")) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={objectUrl}
        alt={filename}
        className={`max-w-full rounded-lg border border-border bg-surface object-contain p-2 ${
          fillViewport ? "max-h-[calc(100vh-3.5rem)]" : "max-h-[70vh]"
        } w-auto`}
      />
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
      <p>
        Inline preview is not available for{" "}
        <code className="font-mono text-xs">{contentType || "this file type"}</code>
        .
      </p>
      {objectUrl ? (
        <a
          href={objectUrl}
          download={filename}
          className="mt-3 inline-block text-accent hover:underline"
        >
          Download {filename}
        </a>
      ) : null}
    </div>
  );
}
