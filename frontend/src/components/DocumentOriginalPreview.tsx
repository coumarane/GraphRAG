"use client";

import { useEffect, useState } from "react";
import { readTenantKey } from "@/components/AppShell";

type Props = {
  documentId: string;
};

export function DocumentOriginalPreview({ documentId }: Props) {
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

  if (busy) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-10 text-sm text-muted">
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
      <pre className="max-h-[70vh] overflow-auto rounded-lg border border-border bg-surface p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {textPreview}
      </pre>
    );
  }

  if (objectUrl && (contentType.includes("pdf") || /\.pdf$/i.test(filename))) {
    return (
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-sm">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <p className="font-mono text-xs text-muted">{filename}</p>
          <a
            href={objectUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-accent hover:underline"
          >
            Open in new tab
          </a>
        </div>
        <iframe
          src={objectUrl}
          title={`Preview ${filename}`}
          className="h-[70vh] w-full bg-[#f7f8fa]"
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
        className="max-h-[70vh] w-auto max-w-full rounded-lg border border-border bg-surface object-contain p-2"
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
