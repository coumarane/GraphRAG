"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Folder,
  Pencil,
  Plus,
  RefreshCw,
  Shield,
  Trash2,
  FolderSearch,
} from "lucide-react";
import { adminJson, formatWhen } from "@/lib/admin";
import {
  AdminButton,
  AdminCard,
  AdminField,
  AdminModal,
  AdminToggle,
  ErrorBanner,
  adminInputClass,
} from "@/components/admin/widgets";

type Connector = {
  connector_id: string;
  name: string;
  source_type: string;
  description: string;
  status: string;
  enabled: boolean;
  last_synced_at: string | null;
  document_count: number;
  last_error: string | null;
  site_url: string | null;
};

type Category = {
  category_id: string;
  name: string;
  parser: string;
  description: string;
  color: string;
  is_default: boolean;
};

type ChatContext = {
  context_id: string;
  name: string;
  description: string;
  order: number;
  visible: boolean;
  built_in: boolean;
  system_prompt: string;
};

type LogEvent = {
  timestamp?: string;
  level?: string;
  event?: string;
  logger?: string;
  correlation_id?: string;
  document_id?: string;
};

export function ConnectorsPanel() {
  const [items, setItems] = useState<Connector[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "", site_url: "" });

  async function load() {
    try {
      const data = await adminJson<{ items: Connector[] }>("/connectors");
      setItems(data.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    await adminJson<unknown>("/connectors", {
      method: "POST",
      body: JSON.stringify({ ...draft, source_type: "sharepoint" }),
    });
    setOpen(false);
    setDraft({ name: "", description: "", site_url: "" });
    await load();
  }

  return (
    <AdminCard>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Connectors</h2>
          <p className="text-sm text-[var(--muted)]">
            Browse files from external sources and import selected ones into the knowledge base.
          </p>
        </div>
        <AdminButton onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> Add connector
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <div className="space-y-3">
        {items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--muted)]">
            No connectors yet. Add a SharePoint source to import documents.
          </p>
        ) : null}
        {items.map((item) => (
          <div
            key={item.connector_id}
            className="flex flex-wrap items-center gap-3 rounded-2xl border border-[var(--border)] px-4 py-3"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-warning/15 text-warning">
              <Folder className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">{item.name}</p>
                <span className="text-xs text-[var(--muted)] capitalize">{item.source_type}</span>
              </div>
              <p className="text-sm text-[var(--muted)]">{item.description || "No description"}</p>
              <p className="text-xs text-[var(--muted)]">
                {item.last_synced_at
                  ? `${formatWhen(item.last_synced_at)} · ${item.document_count} docs`
                  : "Never synced"}
              </p>
              {item.last_error ? (
                <p className="text-xs text-danger">{item.last_error}</p>
              ) : null}
            </div>
            <span
              className={
                item.status === "active"
                  ? "text-sm text-success"
                  : "text-sm text-danger"
              }
            >
              {item.status === "active" ? "● Active" : "● Error"}
            </span>
            <AdminButton variant="ghost">
              <FolderSearch className="h-4 w-4" /> Browse
            </AdminButton>
            <AdminButton
              variant="ghost"
              onClick={() =>
                void adminJson<unknown>(`/connectors/${item.connector_id}/test`, { method: "POST" }).then(load)
              }
            >
              <Shield className="h-4 w-4" /> Test
            </AdminButton>
            <AdminButton
              variant="ghost"
              onClick={() =>
                void adminJson<unknown>(`/connectors/${item.connector_id}/disable`, {
                  method: "POST",
                }).then(load)
              }
            >
              Disable
            </AdminButton>
            <button
              type="button"
              className="rounded-lg p-2 text-muted hover:bg-surface-elevated"
              onClick={() => void load()}
              aria-label="Refresh"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="rounded-lg p-2 text-danger hover:bg-danger/15"
              onClick={() =>
                void adminJson<unknown>(`/connectors/${item.connector_id}`, { method: "DELETE" }).then(load)
              }
              aria-label="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <AdminModal open={open} title="Add connector" onClose={() => setOpen(false)}>
        <form className="space-y-3" onSubmit={(event) => void create(event)}>
          <AdminField label="Name">
            <input
              className={adminInputClass}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              required
            />
          </AdminField>
          <AdminField label="Description">
            <input
              className={adminInputClass}
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </AdminField>
          <AdminField label="SharePoint site URL">
            <input
              className={adminInputClass}
              value={draft.site_url}
              onChange={(event) => setDraft({ ...draft, site_url: event.target.value })}
              placeholder="https://contoso.sharepoint.com/sites/docs"
            />
          </AdminField>
          <div className="flex justify-end gap-2 pt-2">
            <AdminButton variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </AdminButton>
            <AdminButton type="submit">Create</AdminButton>
          </div>
        </form>
      </AdminModal>
    </AdminCard>
  );
}

export function CategoriesPanel() {
  const [items, setItems] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", parser: "docling", description: "" });

  async function load() {
    try {
      const data = await adminJson<{ items: Category[] }>("/categories");
      setItems(data.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    await adminJson<unknown>("/categories", { method: "POST", body: JSON.stringify(draft) });
    setOpen(false);
    await load();
  }

  return (
    <AdminCard>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Document Categories</h2>
          <p className="text-sm text-[var(--muted)]">
            Each category maps to a parser. Users select a category at upload — the parser is chosen automatically.
          </p>
        </div>
        <AdminButton onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> New category
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="pb-3 font-medium">Category</th>
              <th className="pb-3 font-medium">Parser</th>
              <th className="pb-3 font-medium">Description</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.category_id} className="border-t border-[var(--border)]">
                <td className="py-3">
                  <span className="inline-flex items-center gap-2 font-medium">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: item.color }}
                    />
                    {item.name}
                    {item.is_default ? (
                      <span className="rounded-full bg-surface-elevated px-2 py-0.5 text-[10px] uppercase text-muted">
                        default
                      </span>
                    ) : null}
                  </span>
                </td>
                <td className="py-3 text-[var(--muted)]">{item.parser}</td>
                <td className="py-3 text-[var(--muted)]">{item.description}</td>
                <td className="py-3 text-right">
                  {!item.is_default ? (
                    <button
                      type="button"
                      className="text-danger"
                      onClick={() =>
                        void adminJson<unknown>(`/categories/${item.category_id}`, {
                          method: "DELETE",
                        }).then(load)
                      }
                      aria-label={`Delete ${item.name}`}
                    >
                      <Trash2 className="inline h-4 w-4" />
                    </button>
                  ) : (
                    <Pencil className="inline h-4 w-4 text-[var(--muted)]" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AdminModal open={open} title="New category" onClose={() => setOpen(false)}>
        <form className="space-y-3" onSubmit={(event) => void create(event)}>
          <AdminField label="Name">
            <input
              className={adminInputClass}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              required
            />
          </AdminField>
          <AdminField label="Parser">
            <select
              className={adminInputClass}
              value={draft.parser}
              onChange={(event) => setDraft({ ...draft, parser: event.target.value })}
            >
              {["auto", "docling", "marker", "mineru"].map((parser) => (
                <option key={parser}>{parser}</option>
              ))}
            </select>
          </AdminField>
          <AdminField label="Description">
            <input
              className={adminInputClass}
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </AdminField>
          <div className="flex justify-end gap-2">
            <AdminButton variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </AdminButton>
            <AdminButton type="submit">Create</AdminButton>
          </div>
        </form>
      </AdminModal>
    </AdminCard>
  );
}

export function ChatContextsPanel() {
  const [items, setItems] = useState<ChatContext[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "", system_prompt: "" });

  async function load() {
    try {
      const data = await adminJson<{ items: ChatContext[] }>("/chat-contexts");
      setItems(data.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    await adminJson<unknown>("/chat-contexts", { method: "POST", body: JSON.stringify(draft) });
    setOpen(false);
    await load();
  }

  return (
    <AdminCard>
      <div className="mb-4 flex items-center justify-between">
        <p className="max-w-2xl text-sm text-[var(--muted)]">
          Chat contexts (“Expert modes”) steer how the assistant answers. Selecting one adds
          expertise rules to the system prompt — the user’s question is never changed.
        </p>
        <AdminButton onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> New context
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <table className="w-full text-left text-sm">
        <thead className="text-[var(--muted)]">
          <tr>
            <th className="pb-3 font-medium">Name</th>
            <th className="pb-3 font-medium">Description</th>
            <th className="pb-3 font-medium">Order</th>
            <th className="pb-3 font-medium">Visible</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.context_id} className="border-t border-[var(--border)]">
              <td className="py-3 font-medium">
                {item.name}
                {item.built_in ? (
                  <span className="ml-2 text-xs text-[var(--muted)]">built-in</span>
                ) : null}
              </td>
              <td className="py-3 text-[var(--muted)]">{item.description}</td>
              <td className="py-3">{item.order}</td>
              <td className="py-3">
                <AdminToggle
                  checked={item.visible}
                  onChange={(visible) =>
                    void adminJson<unknown>(`/chat-contexts/${item.context_id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ visible }),
                    }).then(load)
                  }
                />
              </td>
              <td className="py-3 text-right">
                {!item.built_in ? (
                  <button
                    type="button"
                    className="text-danger"
                    onClick={() =>
                      void adminJson<unknown>(`/chat-contexts/${item.context_id}`, {
                        method: "DELETE",
                      }).then(load)
                    }
                  >
                    <Trash2 className="inline h-4 w-4" />
                  </button>
                ) : (
                  <Pencil className="inline h-4 w-4 text-[var(--muted)]" />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <AdminModal open={open} title="New chat context" onClose={() => setOpen(false)}>
        <form className="space-y-3" onSubmit={(event) => void create(event)}>
          <AdminField label="Name">
            <input
              className={adminInputClass}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              required
            />
          </AdminField>
          <AdminField label="Description">
            <input
              className={adminInputClass}
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </AdminField>
          <AdminField label="System prompt">
            <textarea
              className={`${adminInputClass} h-24 py-2`}
              value={draft.system_prompt}
              onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })}
            />
          </AdminField>
          <div className="flex justify-end gap-2">
            <AdminButton variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </AdminButton>
            <AdminButton type="submit">Create</AdminButton>
          </div>
        </form>
      </AdminModal>
    </AdminCard>
  );
}

export function LogsPanel() {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("All levels");
  const [items, setItems] = useState<LogEvent[]>([]);
  const [counts, setCounts] = useState({ ERROR: 0, INFO: 0, WARNING: 0 });
  const [error, setError] = useState<string | null>(null);

  const search = useMemo(() => {
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    if (level && level !== "All levels") params.set("level", level);
    return params.toString();
  }, [query, level]);

  async function load() {
    try {
      const data = await adminJson<{ items: LogEvent[]; counts: typeof counts }>(
        `/logs${search ? `?${search}` : ""}`,
      );
      setItems(data.items || []);
      setCounts(data.counts || counts);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial log fetch
  }, []);

  return (
    <AdminCard>
      <h2 className="text-lg font-semibold">Application logs</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Search backend and worker diagnostics. Logs are retained in-process for the current API.
        Sensitive fields and document text are redacted.
      </p>
      <div className="mt-3 flex flex-wrap gap-3 text-sm">
        <span className="text-danger">ERROR: {counts.ERROR}</span>
        <span className="text-sky-700">INFO: {counts.INFO}</span>
        <span className="text-warning">WARNING: {counts.WARNING}</span>
      </div>
      <ErrorBanner error={error} />
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <AdminField label="Search event or context">
          <input
            className={adminInputClass}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="cpu_embedding, batch_number…"
          />
        </AdminField>
        <AdminField label="Level">
          <select
            className={adminInputClass}
            value={level}
            onChange={(event) => setLevel(event.target.value)}
          >
            {["All levels", "ERROR", "WARNING", "INFO", "DEBUG"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </AdminField>
      </div>
      <div className="mt-4">
        <AdminButton onClick={() => void load()}>Apply filters</AdminButton>
      </div>
      <div className="mt-4 space-y-2">
        {items.map((item, index) => (
          <div key={`${item.timestamp}-${index}`} className="rounded-xl border border-[var(--border)] px-3 py-2 text-sm">
            <span className="mr-2 font-mono text-xs text-[var(--muted)]">{item.timestamp}</span>
            <span className="mr-2 font-semibold">{item.level}</span>
            <span>{item.event}</span>
            {item.logger ? <span className="ml-2 text-[var(--muted)]">{item.logger}</span> : null}
          </div>
        ))}
      </div>
    </AdminCard>
  );
}
