"use client";

import {
  FormEvent,
  Suspense,
  useEffect,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";
import { readTenantKey } from "@/components/AppShell";
import { FormattedAnswer, wantsRenderedChart } from "@/components/FormattedAnswer";
import {
  createEmptyThread,
  createMessage,
  isScopeExpandAffirmative,
  loadChatThreads,
  saveChatThreads,
  titleFromQuestion,
  upsertThread,
  type ChatCitation,
  type ChatMessage,
  type ChatThread,
} from "@/lib/chatHistory";

const MODES = [
  "auto",
  "naive",
  "local",
  "global",
  "hybrid",
  "multimodal",
  "mix",
] as const;

function unwrapAnswerPayload(raw: string): {
  answer: string;
  warnings: string[];
} {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("{")) {
    return { answer: trimmed, warnings: [] };
  }
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    if (typeof parsed.answer !== "string" || !parsed.answer.trim()) {
      return { answer: trimmed, warnings: [] };
    }
    const warningsRaw = parsed.warnings;
    const warnings = Array.isArray(warningsRaw)
      ? warningsRaw.map(String).filter(Boolean)
      : typeof warningsRaw === "string" && warningsRaw.trim()
        ? [warningsRaw.trim()]
        : [];
    return { answer: parsed.answer.trim(), warnings };
  } catch {
    return { answer: trimmed, warnings: [] };
  }
}

function looksLikeUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  );
}

function sourceLabel(citation: ChatCitation, resolvedTitle?: string): string {
  const candidates = [resolvedTitle, citation.document_name]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  for (const name of candidates) {
    if (name !== citation.document_id && !looksLikeUuid(name)) return name;
  }
  return "Untitled document";
}

function sourceHrefFor(citation: ChatCitation): string | null {
  if (!citation.document_id) return null;
  const page =
    typeof citation.page_start === "number" && citation.page_start >= 1
      ? citation.page_start
      : null;
  const qs = page != null ? `?page=${page}` : "";
  return `/documents/${citation.document_id}/source${qs}`;
}

function sectionLabel(citation: ChatCitation): string | null {
  const path = (citation.section_path || []).map((part) => part.trim()).filter(Boolean);
  if (path.length) return path[path.length - 1];
  const evidence = (citation.evidence || citation.quote || "").trim();
  if (!evidence) return null;
  const firstLine = evidence.split(/\n/)[0]?.replace(/^[#*\-\s|]+/, "").trim();
  if (!firstLine) return null;
  return firstLine.length > 48 ? `${firstLine.slice(0, 48).trimEnd()}…` : firstLine;
}

function snippetText(citation: ChatCitation): string {
  const raw = (citation.evidence || citation.quote || "").trim().replace(/\s+/g, " ");
  if (!raw) return "";
  return raw.length > 160 ? `${raw.slice(0, 160).trimEnd()}…` : raw;
}

function citationNumber(citation: ChatCitation, index: number): number {
  const id = citation.citation_id || "";
  const match = /^C(\d+)$/i.exec(id);
  if (match) return Number.parseInt(match[1], 10);
  return index + 1;
}

type DocMeta = { title: string | null; page_count: number | null };

function SourcesGrid({
  citations,
  uploaderName,
}: {
  citations: ChatCitation[];
  uploaderName: string;
}) {
  const [metaById, setMetaById] = useState<Record<string, DocMeta>>({});

  useEffect(() => {
    const ids = [
      ...new Set(
        citations
          .map((citation) => citation.document_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ];
    if (!ids.length) return;
    let cancelled = false;
    void (async () => {
      const entries = await Promise.all(
        ids.map(async (id) => {
          try {
            const res = await fetch(`/api/documents/${id}`, {
              headers: { "X-Tenant-Key": readTenantKey() },
              cache: "no-store",
            });
            if (!res.ok) return [id, { title: null, page_count: null }] as const;
            const body = (await res.json()) as {
              title?: string | null;
              page_count?: number | null;
            };
            return [
              id,
              {
                title: body.title?.trim() || null,
                page_count:
                  typeof body.page_count === "number" ? body.page_count : null,
              },
            ] as const;
          } catch {
            return [id, { title: null, page_count: null }] as const;
          }
        }),
      );
      if (!cancelled) {
        setMetaById(Object.fromEntries(entries));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [citations]);

  return (
    <div className="mt-1">
      <p className="text-[11px] font-medium tracking-[0.14em] text-muted uppercase">
        Sources
      </p>
      <ul className="mt-3 grid gap-3 sm:grid-cols-2">
        {citations.map((citation, index) => {
          const meta = citation.document_id
            ? metaById[citation.document_id]
            : undefined;
          const name = sourceLabel(citation, meta?.title ?? undefined);
          const href = sourceHrefFor(citation);
          const number = citationNumber(citation, index);
          const page = citation.page_start;
          const total = meta?.page_count;
          const section = sectionLabel(citation);
          const snippet = snippetText(citation);
          const pageText =
            page != null
              ? total != null
                ? `Page ${page} /${total}`
                : citation.page_end != null && citation.page_end !== page
                  ? `Page ${page}–${citation.page_end}`
                  : `Page ${page}`
              : null;

          const card = (
            <>
              <div className="flex items-start gap-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#ece7f5] text-[12px] font-semibold text-[#5b4b8a]">
                  {number}
                </span>
                <p className="min-w-0 text-[13px] leading-5 font-semibold tracking-wide text-foreground uppercase">
                  {name}
                </p>
              </div>
              <div className="mt-2 space-y-1 pl-[2.125rem] text-[12px] leading-5 text-muted">
                {pageText || section ? (
                  <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 16 16"
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-70"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    >
                      <path d="M4 2.5h5.5L12 5v8.5H4v-11z" />
                      <path d="M9.5 2.5V5H12" />
                    </svg>
                    {pageText ? <span>{pageText}</span> : null}
                    {pageText && section ? <span>·</span> : null}
                    {section ? <span className="line-clamp-1">{section}</span> : null}
                  </p>
                ) : null}
                <p className="flex items-center gap-1.5">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 16 16"
                    className="h-3.5 w-3.5 shrink-0 opacity-70"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  >
                    <circle cx="8" cy="5.5" r="2.25" />
                    <path d="M3.5 13c.8-2 2.2-3 4.5-3s3.7 1 4.5 3" />
                  </svg>
                  <span>Uploaded by {uploaderName}</span>
                </p>
              </div>
              {snippet ? (
                <p className="mt-2 line-clamp-2 pl-[2.125rem] text-[12px] leading-5 text-foreground/70">
                  {snippet}
                </p>
              ) : null}
            </>
          );

          return (
            <li key={citation.citation_id || citation.chunk_id || index}>
              {href ? (
                <a
                  id={`cite-C${number}`}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block h-full rounded-xl border border-border bg-[#f3f5f7] px-3.5 py-3 transition-colors hover:border-accent/50 hover:bg-white"
                  title={`Open ${name}${page != null ? ` at page ${page}` : ""}`}
                >
                  {card}
                </a>
              ) : (
                <div className="h-full rounded-xl border border-border bg-[#f3f5f7] px-3.5 py-3">
                  {card}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CopyMessageButton({
  text,
  tone,
}: {
  text: string;
  tone: "user" | "assistant";
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    const value = text.trim();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  const isUser = tone === "user";
  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      className={`rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors ${
        isUser
          ? "text-white/70 hover:bg-white/15 hover:text-white"
          : "text-muted hover:bg-background hover:text-foreground"
      }`}
      aria-label={isUser ? "Copy question" : "Copy answer"}
      title={copied ? "Copied" : isUser ? "Copy question" : "Copy answer"}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function MessageBubble({
  message,
  uploaderName,
  allowCharts = false,
}: {
  message: ChatMessage;
  uploaderName: string;
  allowCharts?: boolean;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`rounded-2xl px-4 py-3 ${
          isUser
            ? "max-w-[min(100%,42rem)] bg-accent text-white"
            : "w-full max-w-[min(100%,52rem)] border border-border bg-surface text-foreground shadow-sm"
        }`}
      >
        <div className="mb-1 flex items-center justify-between gap-3">
          <p
            className={`text-[11px] font-medium uppercase tracking-wide ${
              isUser ? "text-white/70" : "text-muted"
            }`}
          >
            {isUser ? "You" : "Assistant"}
          </p>
          <CopyMessageButton
            text={message.content}
            tone={isUser ? "user" : "assistant"}
          />
        </div>
        {isUser ? (
          <p className="select-text whitespace-pre-wrap text-[15px] leading-7">
            {message.content}
          </p>
        ) : (
          <div className="space-y-4">
            <div className="select-text">
              <FormattedAnswer
                answer={message.content}
                allowCharts={allowCharts}
              />
            </div>
            {message.retrieval_mode ? (
              <p className="font-mono text-[11px] text-muted">
                mode={message.retrieval_mode}
                {message.retrieval_trace_id
                  ? ` · trace=${message.retrieval_trace_id}`
                  : ""}
              </p>
            ) : null}
            {message.warnings?.length ? (
              <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                <p className="text-xs font-medium text-amber-800">Notes</p>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-amber-900/90">
                  {message.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {message.citations?.length ? (
              <SourcesGrid
                citations={message.citations}
                uploaderName={uploaderName}
              />
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function ChatWorkspace() {
  const searchParams = useSearchParams();
  const [tenantKey, setTenantKey] = useState("demo");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const activeThread =
    threads.find((thread) => thread.id === activeId) ?? threads[0] ?? null;

  useEffect(() => {
    const syncTenant = () => setTenantKey(readTenantKey());
    syncTenant();
    window.addEventListener("focus", syncTenant);
    return () => window.removeEventListener("focus", syncTenant);
  }, []);

  useEffect(() => {
    const loaded = loadChatThreads(tenantKey);
    if (loaded.length) {
      setThreads(loaded);
      setActiveId(loaded[0].id);
    } else {
      const fresh = createEmptyThread();
      setThreads([fresh]);
      setActiveId(fresh.id);
    }
    setHydrated(true);
  }, [tenantKey]);

  useEffect(() => {
    const fromUrl = searchParams.get("document_id");
    if (!fromUrl || !hydrated || !activeThread) return;
    if (activeThread.documentId === fromUrl) return;
    setThreads((prev) => {
      const next = prev.map((thread) =>
        thread.id === activeThread.id
          ? { ...thread, documentId: fromUrl, updatedAt: new Date().toISOString() }
          : thread,
      );
      saveChatThreads(tenantKey, next);
      return next;
    });
  }, [searchParams, hydrated, activeThread, tenantKey]);

  useEffect(() => {
    if (!hydrated) return;
    saveChatThreads(tenantKey, threads);
  }, [threads, tenantKey, hydrated]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeThread?.messages.length, busy]);

  function startNewChat() {
    const fresh = createEmptyThread({
      mode: activeThread?.mode ?? "auto",
      documentId: activeThread?.documentId ?? "",
    });
    setThreads((prev) => upsertThread(prev, fresh));
    setActiveId(fresh.id);
    setDraft("");
    setError(null);
    textareaRef.current?.focus();
  }

  function deleteChat(threadId: string) {
    setThreads((prev) => {
      const remaining = prev.filter((thread) => thread.id !== threadId);
      if (!remaining.length) {
        const fresh = createEmptyThread();
        setActiveId(fresh.id);
        return [fresh];
      }
      if (activeId === threadId) setActiveId(remaining[0].id);
      return remaining;
    });
  }

  function updateActive(patch: Partial<ChatThread>) {
    if (!activeThread) return;
    setThreads((prev) =>
      upsertThread(prev, {
        ...activeThread,
        ...patch,
        updatedAt: new Date().toISOString(),
      }),
    );
  }

  async function sendMessage(questionRaw: string) {
    if (!activeThread || busy) return;
    const question = questionRaw.trim();
    if (!question) {
      setError("Enter a message.");
      return;
    }

    setBusy(true);
    setError(null);
    const userMessage = createMessage("user", question);
    const historyForContext = activeThread.messages;
    const nextMessages = [...activeThread.messages, userMessage];
    const titled =
      activeThread.messages.length === 0
        ? titleFromQuestion(question)
        : activeThread.title;

    const pending = (activeThread.pendingExpandQuestion || "").trim();
    const expandScope =
      Boolean(pending) && isScopeExpandAffirmative(question);
    const questionForApi = expandScope ? pending : question;
    const stickyIds = activeThread.conversationContext?.documentIds ?? [];
    const manualId = activeThread.documentId.trim();
    const documentIds = expandScope
      ? []
      : manualId
        ? [manualId]
        : stickyIds;

    const optimistic: ChatThread = {
      ...activeThread,
      title: titled,
      messages: nextMessages,
      updatedAt: new Date().toISOString(),
    };
    setThreads((prev) => upsertThread(prev, optimistic));
    setDraft("");

    try {
      const response = await fetch("/api/query", {
        credentials: "include",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Key": tenantKey,
        },
        body: JSON.stringify({
          question: questionForApi,
          conversation_history: historyForContext.map((message) => ({
            role: message.role,
            content: message.content,
          })),
          mode: activeThread.mode,
          document_ids: documentIds,
          expand_document_scope: expandScope,
          include_graph_paths: true,
          rerank: true,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || response.statusText,
        );
      }
      const unwrapped = unwrapAnswerPayload(
        typeof body.answer === "string" ? body.answer : "",
      );
      const warnings = [
        ...(Array.isArray(body.warnings) ? body.warnings.map(String) : []),
        ...unwrapped.warnings,
      ];
      const uniqueWarnings = [...new Set(warnings)];
      const awaitingExpand = uniqueWarnings.includes("awaiting_scope_expand");
      const rawCtx = body.active_conversation_context;
      let nextContext = activeThread.conversationContext ?? null;
      if (
        rawCtx &&
        typeof rawCtx === "object" &&
        typeof rawCtx.label === "string" &&
        Array.isArray(rawCtx.document_ids)
      ) {
        let docIds = rawCtx.document_ids.map(String).filter(Boolean);
        // Backend may return a label with empty ids; recover pin from citations.
        if (
          docIds.length === 0 &&
          Array.isArray(body.citations) &&
          body.citations.length
        ) {
          docIds = [
            ...new Set(
              body.citations
                .map((item: ChatCitation) =>
                  item?.document_id ? String(item.document_id) : "",
                )
                .filter(Boolean),
            ),
          ];
        }
        // Keep prior pin when backend returns label-only (empty ids) for same topic.
        if (
          docIds.length === 0 &&
          activeThread.conversationContext?.documentIds?.length
        ) {
          const priorLabel = (
            activeThread.conversationContext.label || ""
          ).toLowerCase();
          const nextLabel = rawCtx.label.toLowerCase();
          if (
            !priorLabel ||
            !nextLabel ||
            priorLabel === nextLabel ||
            priorLabel.includes(nextLabel) ||
            nextLabel.includes(priorLabel)
          ) {
            docIds = [...activeThread.conversationContext.documentIds];
          }
        }
        nextContext = {
          label: rawCtx.label,
          documentIds: docIds,
          entities: Array.isArray(rawCtx.entities)
            ? rawCtx.entities.map(String)
            : [],
        };
      } else if (uniqueWarnings.includes("context_switch_detected")) {
        nextContext = null;
      } else if (
        Array.isArray(body.citations) &&
        body.citations.length &&
        !nextContext?.documentIds?.length
      ) {
        // First answer with sources but missing active_conversation_context ids.
        const docIds: string[] = Array.from(
          new Set(
            body.citations
              .map((item: ChatCitation) =>
                item?.document_id ? String(item.document_id) : "",
              )
              .filter((id: string): id is string => id.length > 0),
          ),
        );
        if (docIds.length) {
          const label =
            (typeof rawCtx === "object" &&
            rawCtx &&
            typeof (rawCtx as { label?: unknown }).label === "string"
              ? (rawCtx as { label: string }).label
              : null) ||
            body.citations.find(
              (item: ChatCitation) => item?.document_name,
            )?.document_name ||
            "active document";
          const entitiesRaw =
            typeof rawCtx === "object" &&
            rawCtx &&
            Array.isArray((rawCtx as { entities?: unknown }).entities)
              ? ((rawCtx as { entities: unknown[] }).entities.map(String) as string[])
              : [];
          nextContext = {
            label: String(label),
            documentIds: docIds,
            entities: entitiesRaw,
          };
        }
      }
      const assistantMessage = createMessage("assistant", unwrapped.answer, {
        citations: Array.isArray(body.citations)
          ? body.citations.map((item: ChatCitation) => ({
              ...item,
              document_name:
                typeof item.document_name === "string" &&
                item.document_name.trim() &&
                !looksLikeUuid(item.document_name.trim())
                  ? item.document_name.trim()
                  : item.document_name,
              section_path: Array.isArray(item.section_path)
                ? item.section_path
                : [],
            }))
          : [],
        warnings: uniqueWarnings,
        retrieval_mode: body.retrieval_mode || body.mode,
        retrieval_trace_id: body.retrieval_trace_id,
      });
      setThreads((prev) => {
        const current = prev.find((thread) => thread.id === activeThread.id);
        if (!current) return prev;
        return upsertThread(prev, {
          ...current,
          title: titled,
          messages: [...current.messages, assistantMessage],
          pendingExpandQuestion: awaitingExpand
            ? expandScope
              ? pending
              : question
            : null,
          conversationContext: nextContext,
          updatedAt: new Date().toISOString(),
        });
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setThreads((prev) => {
        const current = prev.find((thread) => thread.id === activeThread.id);
        if (!current) return prev;
        return upsertThread(prev, {
          ...current,
          messages: [
            ...current.messages,
            createMessage(
              "assistant",
              `I could not complete that request: ${message}`,
              { warnings: ["request_failed"] },
            ),
          ],
          updatedAt: new Date().toISOString(),
        });
      });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(draft);
  }

  if (!hydrated || !activeThread) {
    return <p className="text-sm text-muted">Loading chats…</p>;
  }

  return (
    <div className="grid min-h-[calc(100vh-14rem)] gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="flex flex-col rounded-lg border border-border bg-surface">
        <div className="border-b border-border p-3">
          <button
            type="button"
            onClick={startNewChat}
            className="w-full rounded bg-accent px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
          >
            New chat
          </button>
        </div>
        <ul className="flex-1 space-y-1 overflow-y-auto p-2">
          {threads.map((thread) => {
            const active = thread.id === activeThread.id;
            return (
              <li key={thread.id} className="group relative">
                <button
                  type="button"
                  onClick={() => setActiveId(thread.id)}
                  className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                    active
                      ? "bg-accent/10 text-foreground"
                      : "text-muted hover:bg-background hover:text-foreground"
                  }`}
                >
                  <span className="line-clamp-2 pr-6">{thread.title}</span>
                  <span className="mt-1 block font-mono text-[10px] text-muted">
                    {thread.messages.length} msg
                  </span>
                </button>
                <button
                  type="button"
                  aria-label="Delete chat"
                  onClick={() => deleteChat(thread.id)}
                  className="absolute top-2 right-2 hidden rounded px-1.5 py-0.5 text-[11px] text-muted hover:bg-danger/10 hover:text-danger group-hover:inline-flex"
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <section className="flex min-h-[32rem] flex-col rounded-lg border border-border bg-surface shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          <label className="min-w-[8rem] flex-1 text-sm">
            <span className="text-muted">Mode</span>
            <select
              value={activeThread.mode}
              onChange={(event) => updateActive({ mode: event.target.value })}
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 outline-none focus:border-accent"
            >
              {MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {mode}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-[12rem] flex-[2] text-sm">
            <span className="text-muted">Manual document override (optional)</span>
            <input
              value={activeThread.documentId}
              onChange={(event) =>
                updateActive({
                  documentId: event.target.value.trim(),
                  pendingExpandQuestion: null,
                })
              }
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-accent"
              placeholder="Usually leave empty — context sticks from chat"
            />
            {activeThread.conversationContext?.label ? (
              <p className="mt-1 text-xs text-foreground">
                Active conversation context:{" "}
                <span className="font-medium">
                  {activeThread.conversationContext.label}
                </span>
                . Follow-ups stay here unless you change topic or reply Yes to
                widen.
              </p>
            ) : (
              <p className="mt-1 text-xs text-muted">
                Context is established by your first question and answer.
              </p>
            )}
            {activeThread.pendingExpandQuestion ? (
              <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                Waiting for Yes to search other documents.
              </p>
            ) : null}
          </label>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5">
          {activeThread.messages.length === 0 ? (
            <div className="mx-auto max-w-lg py-16 text-center">
              <h3 className="text-lg font-semibold tracking-tight">
                Grounded document chat
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted">
                Ask follow-up questions like ChatGPT. Each reply stays grounded
                in retrieved evidence, and this conversation is saved in your
                browser.
              </p>
            </div>
          ) : (
            activeThread.messages.map((message, index) => {
              const priorUser = [...activeThread.messages.slice(0, index)]
                .reverse()
                .find((item) => item.role === "user");
              const allowCharts = priorUser
                ? wantsRenderedChart(priorUser.content)
                : false;
              return (
                <MessageBubble
                  key={message.id}
                  message={message}
                  allowCharts={allowCharts}
                  uploaderName={
                    tenantKey.trim()
                      ? tenantKey.trim().charAt(0).toUpperCase() +
                        tenantKey.trim().slice(1)
                      : "Workspace"
                  }
                />
              );
            })
          )}
          {busy ? (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-muted shadow-sm">
                Retrieving and answering…
              </div>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>

        {error ? (
          <p className="mx-4 mb-2 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <form
          onSubmit={onSubmit}
          className="border-t border-border bg-background/60 px-4 py-3"
        >
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(draft);
                }
              }}
              rows={3}
              placeholder="Ask a follow-up… (Enter to send, Shift+Enter for newline)"
              className="max-h-40 min-h-[4.5rem] flex-1 resize-y rounded-xl border border-border bg-surface px-3 py-2 text-[15px] outline-none focus:border-accent"
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="rounded-xl bg-accent px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
            >
              Send
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function QueryPage() {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Chat</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Conversational grounded Q&amp;A with saved chat history in this
          browser.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <ChatWorkspace />
      </Suspense>
    </section>
  );
}
