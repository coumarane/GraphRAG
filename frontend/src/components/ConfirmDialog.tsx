"use client";

import { useEffect } from "react";

export type ConfirmChecklistItem = {
  id: string;
  label: string;
  checked: boolean;
};

export function ConfirmDialog({
  open,
  title,
  description,
  checklist,
  onToggleChecklistItem,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  busy = false,
  danger = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  checklist?: ConfirmChecklistItem[];
  onToggleChecklistItem?: (id: string) => void;
  confirmLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={busy ? undefined : onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        className="w-full max-w-sm rounded-xl border border-border bg-surface-elevated p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="text-base font-semibold text-foreground">
          {title}
        </h2>
        <p
          id="confirm-dialog-description"
          className={
            danger
              ? "mt-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
              : "mt-2 text-sm text-muted"
          }
        >
          {description}
        </p>
        {checklist && checklist.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {checklist.map((item) => (
              <li key={item.id}>
                <label className="flex items-center gap-2 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={item.checked}
                    disabled={busy}
                    onChange={() => onToggleChecklistItem?.(item.id)}
                    className="h-4 w-4 rounded border-border accent-danger"
                  />
                  {item.label}
                </label>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded border border-border bg-background px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-60"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            autoFocus
            className={`rounded px-3 py-2 text-sm font-medium text-white disabled:opacity-60 ${
              danger ? "bg-danger hover:bg-danger/90" : "bg-accent hover:bg-accent-hover"
            }`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
