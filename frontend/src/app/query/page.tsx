"use client";

import {
  FormEvent,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";
import {
  AtSign,
  Check,
  Copy,
  History,
  MessageCircle,
  Paperclip,
  Search,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { readTenantKey } from "@/components/AppShell";
import { ChatHistorySidebar } from "@/components/ChatHistorySidebar";
import { FormattedAnswer, wantsRenderedChart } from "@/components/FormattedAnswer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { readCachedSession } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  createConversation,
  createEmptyThread,
  createMessage,
  createProject,
  createProjectRemote,
  deleteConversation,
  fetchConversations,
  fetchProjects,
  isScopeExpandAffirmative,
  patchConversation,
  patchProject,
  titleFromQuestion,
  upsertProject,
  upsertThread,
  type ChatCitation,
  type ChatGraphPath,
  type ChatMessage,
  type ChatProject,
  type ChatThread,
  type InteractionMode,
} from "@/lib/chatApi";

const MODES = [
  "auto",
  "naive",
  "local",
  "global",
  "hybrid",
  "multimodal",
  "mix",
] as const;

const MENTION_COMMANDS: {
  key: InteractionMode;
  label: string;
  description: string;
}[] = [
  { key: "chat", label: "chat", description: "Plain conversation, no document search" },
  { key: "search", label: "search", description: "Search your documents with citations" },
];

const LEADING_MODE_PATTERN = /^@(chat|search)(?=\s|$)/i;

function detectMentionTrigger(
  text: string,
  cursor: number,
): { query: string; start: number } | null {
  const before = text.slice(0, cursor);
  const match = before.match(/@(\w*)$/);
  if (!match) return null;
  return { query: match[1].toLowerCase(), start: cursor - match[0].length };
}

/** Resolve a message's mode, falling back to citation presence for older
 * history rows that predate the interaction_mode field entirely. */
function resolveMessageMode(message: ChatMessage): "chat" | "search" | null {
  if (message.interaction_mode) return message.interaction_mode;
  if (message.citations && message.citations.length) return "search";
  return null;
}

function ModeTag({ mode }: { mode: "chat" | "search" | null }) {
  if (!mode) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase",
        mode === "search"
          ? "bg-accent-soft text-accent"
          : "bg-surface-elevated text-muted border border-border",
      )}
    >
      {mode === "search" ? (
        <Search className="h-2.5 w-2.5" aria-hidden />
      ) : (
        <MessageCircle className="h-2.5 w-2.5" aria-hidden />
      )}
      {mode}
    </span>
  );
}

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

function userInitials(): string {
  const session = readCachedSession();
  const source =
    session?.user.display_name?.trim() ||
    session?.user.email?.trim() ||
    "U";
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  const letters = ((parts[0]?.[0] || "U") + (parts[1]?.[0] || "")).toUpperCase();
  return letters || "U";
}

function estimateConfidence(
  citationCount: number,
  warnings: string[] | undefined,
): number {
  let score = Math.min(96.8, 88 + 2.5 * citationCount);
  const joined = (warnings || []).join(" ").toLowerCase();
  if (
    /weak_evidence|insufficient|answer_missing_citations/.test(joined)
  ) {
    score -= 15;
  }
  return Math.max(0, Math.min(100, Math.round(score * 10) / 10));
}

function formatGraphPathPill(path: ChatGraphPath): string {
  const nodes = (path.nodes || []).map(String).filter(Boolean);
  const rels = (path.relationships || []).map(String).filter(Boolean);
  if (!nodes.length) return "";
  const parts: string[] = [];
  for (let i = 0; i < nodes.length; i += 1) {
    parts.push(`[${nodes[i]}]`);
    if (i < nodes.length - 1) {
      const rel = rels[i] || rels[0] || "RELATED";
      parts.push(`--(${rel})-->`);
    }
  }
  return parts.join(" ");
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
              credentials: "include",
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
      <ul className="grid gap-3 sm:grid-cols-2">
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
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent">
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
                  className="block h-full rounded-xl border border-border bg-surface-elevated px-3.5 py-3 transition-colors hover:border-accent/50 hover:bg-surface"
                  title={`Open ${name}${page != null ? ` at page ${page}` : ""}`}
                >
                  {card}
                </a>
              ) : (
                <div className="h-full rounded-xl border border-border bg-surface-elevated px-3.5 py-3">
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

function CompactSourceBadges({ citations }: { citations: ChatCitation[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {citations.map((citation, index) => {
        const name = sourceLabel(citation);
        const page =
          typeof citation.page_start === "number" && citation.page_start >= 1
            ? citation.page_start
            : null;
        const label = page != null ? `${name} - p.${page}` : name;
        const href = sourceHrefFor(citation);
        const key = citation.citation_id || citation.chunk_id || String(index);
        if (href) {
          return (
            <a
              key={key}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex"
            >
              <Badge variant="muted" className="max-w-[14rem] truncate font-normal">
                {label}
              </Badge>
            </a>
          );
        }
        return (
          <Badge
            key={key}
            variant="muted"
            className="max-w-[14rem] truncate font-normal"
          >
            {label}
          </Badge>
        );
      })}
    </div>
  );
}

function RetrievalDetails({ message }: { message: ChatMessage }) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-background/50 px-3 py-2 text-xs text-muted">
      {message.retrieval_mode ? (
        <p className="font-mono">
          mode={message.retrieval_mode}
          {message.retrieval_trace_id
            ? ` · trace=${message.retrieval_trace_id}`
            : ""}
        </p>
      ) : (
        <p>No retrieval mode recorded.</p>
      )}
      {message.warnings?.length ? (
        <ul className="list-disc space-y-1 pl-4 text-warning">
          {message.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : (
        <p>No warnings.</p>
      )}
    </div>
  );
}

function CopyMessageButton({
  text,
  className,
  label = "Copy",
}: {
  text: string;
  className?: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const value = text.trim();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Ignore clipboard failures (permissions / insecure context).
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/10 hover:text-foreground",
        className,
      )}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
    >
      {copied ? (
        <Check className="h-4 w-4" aria-hidden />
      ) : (
        <Copy className="h-4 w-4" aria-hidden />
      )}
    </button>
  );
}

function MessageBubble({
  message,
  uploaderName,
  allowCharts = false,
  initials,
}: {
  message: ChatMessage;
  uploaderName: string;
  allowCharts?: boolean;
  initials: string;
}) {
  const isUser = message.role === "user";
  const [showWhy, setShowWhy] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const citations = message.citations || [];
  const graphPaths = message.graph_paths || [];
  const confidence = estimateConfidence(citations.length, message.warnings);
  const mode = resolveMessageMode(message);

  if (isUser) {
    return (
      <div className="group flex items-end justify-end gap-2 sm:gap-2.5">
        <div className="flex max-w-[min(100%,36rem)] flex-col items-end gap-1">
          <div className="flex items-center gap-1">
            <ModeTag mode={mode} />
            <CopyMessageButton
              text={message.content}
              label="Copy"
              className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
            />
          </div>
          <div className="rounded-2xl bg-surface-elevated px-3 py-2.5 text-foreground shadow-sm sm:px-4 sm:py-3">
            <p className="select-text whitespace-pre-wrap break-words text-[15px] leading-7">
              {message.content}
            </p>
          </div>
        </div>
        <div
          className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-white sm:flex"
          aria-hidden
        >
          {initials}
        </div>
      </div>
    );
  }

  return (
    <div className="group flex items-start gap-2 sm:gap-3">
      <div className="mt-1 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent sm:flex">
        <Sparkles className="h-4 w-4" aria-hidden />
      </div>
      <div className="relative min-w-0 flex-1 max-w-[min(100%,48rem)] rounded-2xl border border-border bg-surface px-3 py-2.5 shadow-sm sm:px-4 sm:py-3">
        <div className="absolute right-2 top-2 z-10 opacity-60 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <CopyMessageButton text={message.content} label="Copy" />
        </div>
        <div className="space-y-4 pr-8">
          <ModeTag mode={mode} />
          <div className="select-text">
            <FormattedAnswer
              answer={message.content}
              allowCharts={allowCharts}
            />
          </div>

          {citations.length ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs font-medium text-muted">
                  Confidence: {confidence.toFixed(1)}%
                </span>
                <div className="h-1.5 min-w-[6rem] flex-1 overflow-hidden rounded-full bg-border">
                  <div
                    className="h-full rounded-full bg-success transition-[width]"
                    style={{ width: `${confidence}%` }}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setShowWhy((value) => !value)}
                  className="text-xs font-medium text-accent hover:underline"
                >
                  Why this answer?
                </button>
              </div>
              {showWhy ? <RetrievalDetails message={message} /> : null}
            </div>
          ) : null}

          {graphPaths.length ? (
            <div className="space-y-2">
              <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">
                Graph reasoning
              </p>
              <div className="flex flex-wrap gap-2">
                {graphPaths.map((path, index) => {
                  const pill = formatGraphPathPill(path);
                  if (!pill) return null;
                  return (
                    <span
                      key={`${pill}-${index}`}
                      className="inline-flex max-w-full rounded-md border border-border bg-surface-elevated px-2.5 py-1 font-mono text-[11px] leading-5 text-foreground/90"
                    >
                      {pill}
                    </span>
                  );
                })}
              </div>
            </div>
          ) : null}

          {citations.length ? (
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setShowEvidence((value) => !value)}
                className="text-xs font-medium text-accent hover:underline"
              >
                {showEvidence
                  ? "Hide evidence chunks"
                  : `Show ${citations.length} evidence chunk${citations.length === 1 ? "" : "s"}`}
              </button>
              {showEvidence ? (
                <SourcesGrid
                  citations={citations}
                  uploaderName={uploaderName}
                />
              ) : null}
              <CompactSourceBadges citations={citations} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ChatWorkspace() {
  const searchParams = useSearchParams();
  const [tenantKey, setTenantKey] = useState("demo");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [showInspect, setShowInspect] = useState(false);
  const [showChangeContext, setShowChangeContext] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [mention, setMention] = useState<{
    query: string;
    start: number;
    highlight: number;
  } | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const initials = useMemo(() => userInitials(), [hydrated, tenantKey]);

  const activeThread =
    threads.find((thread) => thread.id === activeId) ?? threads[0] ?? null;

  const lastAssistant = useMemo(() => {
    if (!activeThread) return null;
    for (let i = activeThread.messages.length - 1; i >= 0; i -= 1) {
      if (activeThread.messages[i].role === "assistant") {
        return activeThread.messages[i];
      }
    }
    return null;
  }, [activeThread]);

  const contextLabel =
    activeThread?.conversationContext?.label?.trim() || "Open corpus";
  const hasScopedContext = Boolean(
    activeThread?.conversationContext?.documentIds?.length ||
      activeThread?.documentId?.trim(),
  );
  const mentionMatches = mention
    ? MENTION_COMMANDS.filter((command) => command.label.startsWith(mention.query))
    : [];

  useEffect(() => {
    const syncTenant = () => setTenantKey(readTenantKey());
    syncTenant();
    window.addEventListener("focus", syncTenant);
    return () => window.removeEventListener("focus", syncTenant);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setHydrated(false);
    async function hydrate() {
      let loaded: ChatThread[] = [];
      let loadedProjects: ChatProject[] = [];
      try {
        [loaded, loadedProjects] = await Promise.all([
          fetchConversations(),
          fetchProjects(),
        ]);
      } catch {
        // Fall through to the empty-state branch below on failure.
      }
      if (cancelled) return;
      setProjects(loadedProjects);
      if (loaded.length) {
        setThreads(loaded);
        setActiveId(loaded[0].id);
      } else {
        const fresh = createEmptyThread();
        setThreads([fresh]);
        setActiveId(fresh.id);
        void createConversation(fresh).catch(() => {});
      }
      setSelectedProjectId(null);
      setHydrated(true);
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [tenantKey]);

  useEffect(() => {
    const fromUrl = searchParams.get("document_id");
    if (!fromUrl || !hydrated || !activeThread) return;
    if (activeThread.documentId === fromUrl) return;
    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === activeThread.id
          ? { ...thread, documentId: fromUrl, updatedAt: new Date().toISOString() }
          : thread,
      ),
    );
    void patchConversation(activeThread.id, { document_id: fromUrl }).catch(() => {});
  }, [searchParams, hydrated, activeThread]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeThread?.messages.length, busy]);

  function remoteThreadPatch(patch: Partial<ChatThread>) {
    const mapped: Partial<{
      title: string;
      mode: string;
      interaction_mode: InteractionMode;
      document_id: string | null;
      project_id: string | null;
      pinned: boolean;
      archived: boolean;
    }> = {};
    if (patch.title !== undefined) mapped.title = patch.title;
    if (patch.mode !== undefined) mapped.mode = patch.mode;
    if (patch.interactionMode !== undefined) mapped.interaction_mode = patch.interactionMode;
    if (patch.documentId !== undefined) mapped.document_id = patch.documentId || null;
    if (patch.projectId !== undefined) mapped.project_id = patch.projectId ?? null;
    if (patch.pinned !== undefined) mapped.pinned = patch.pinned;
    if (patch.archived !== undefined) mapped.archived = patch.archived;
    return mapped;
  }

  function startNewChat() {
    const fresh = createEmptyThread({
      mode: activeThread?.mode ?? "auto",
      interactionMode: activeThread?.interactionMode ?? "chat",
      documentId: activeThread?.documentId ?? "",
      projectId: selectedProjectId,
    });
    setThreads((prev) => upsertThread(prev, fresh));
    setActiveId(fresh.id);
    setDraft("");
    setError(null);
    setShowInspect(false);
    setShowChangeContext(false);
    textareaRef.current?.focus();
    void createConversation(fresh).catch(() => {});
  }

  function deleteChat(threadId: string) {
    setThreads((prev) => {
      const remaining = prev.filter((thread) => thread.id !== threadId);
      if (!remaining.length) {
        const fresh = createEmptyThread({ projectId: selectedProjectId });
        setActiveId(fresh.id);
        void createConversation(fresh).catch(() => {});
        return [fresh];
      }
      if (activeId === threadId) setActiveId(remaining[0].id);
      return remaining;
    });
    void deleteConversation(threadId).catch(() => {});
  }

  function patchThread(threadId: string, patch: Partial<ChatThread>) {
    setThreads((prev) => {
      const current = prev.find((thread) => thread.id === threadId);
      if (!current) return prev;
      return upsertThread(prev, {
        ...current,
        ...patch,
        updatedAt: new Date().toISOString(),
      });
    });
    void patchConversation(threadId, remoteThreadPatch(patch)).catch(() => {});
  }

  function handleCreateProject(name: string): string {
    const project = createProject(name);
    setProjects((prev) => upsertProject(prev, project));
    void createProjectRemote(project).catch(() => {});
    return project.id;
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
    void patchConversation(activeThread.id, remoteThreadPatch(patch)).catch(() => {});
  }

  function openMentionMenu() {
    const insertion = !draft || draft.endsWith(" ") || draft.endsWith("\n") ? "@" : " @";
    const nextDraft = `${draft}${insertion}`;
    setDraft(nextDraft);
    setMention({ query: "", start: nextDraft.length - 1, highlight: 0 });
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextDraft.length, nextDraft.length);
    });
  }

  function selectMention(command: (typeof MENTION_COMMANDS)[number]) {
    if (!mention) return;
    const cursor = textareaRef.current?.selectionStart ?? draft.length;
    const nextDraft = `${draft.slice(0, mention.start)}${draft.slice(cursor)}`;
    setDraft(nextDraft);
    setMention(null);
    if (activeThread && activeThread.interactionMode !== command.key) {
      updateActive({ interactionMode: command.key });
    }
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      const pos = mention.start;
      textareaRef.current?.setSelectionRange(pos, pos);
    });
  }

  async function sendMessage(questionRaw: string) {
    if (!activeThread || busy) return;
    let question = questionRaw.trim();
    if (!question) {
      setError("Enter a message.");
      return;
    }

    let interactionMode: InteractionMode = activeThread.interactionMode ?? "chat";
    const modeMatch = question.match(LEADING_MODE_PATTERN);
    if (modeMatch) {
      interactionMode = modeMatch[1].toLowerCase() as InteractionMode;
      question = question.slice(modeMatch[0].length).trim();
      if (!question) {
        setError(`Type a message after @${modeMatch[1].toLowerCase()}.`);
        return;
      }
    }
    if (interactionMode !== activeThread.interactionMode) {
      updateActive({ interactionMode });
    }

    setBusy(true);
    setError(null);
    const userMessage = createMessage("user", question, { interaction_mode: interactionMode });
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
          conversation_id: activeThread.id,
          mode: activeThread.mode,
          interaction_mode: interactionMode,
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
      const graphPaths: ChatGraphPath[] = Array.isArray(body.graph_paths)
        ? body.graph_paths.map((item: ChatGraphPath) => ({
            nodes: Array.isArray(item?.nodes)
              ? item.nodes.map(String)
              : [],
            relationships: Array.isArray(item?.relationships)
              ? item.relationships.map(String)
              : [],
            supporting_citations: Array.isArray(item?.supporting_citations)
              ? item.supporting_citations.map(String)
              : [],
          }))
        : [];
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
        interaction_mode:
          (body.interaction_mode as InteractionMode | undefined) ?? interactionMode,
        graph_paths: graphPaths,
      });
      setThreads((prev) => {
        const current = prev.find((thread) => thread.id === activeThread.id);
        if (!current) return prev;
        return upsertThread(prev, {
          ...current,
          title: titled,
          messages: [...current.messages, assistantMessage],
          pendingExpandQuestion:
            typeof body.pending_expand_question === "string"
              ? body.pending_expand_question
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

  useEffect(() => {
    if (!historyOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setHistoryOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  if (!hydrated || !activeThread) {
    return <p className="text-sm text-muted">Loading chats…</p>;
  }

  const uploaderName = tenantKey.trim()
    ? tenantKey.trim().charAt(0).toUpperCase() + tenantKey.trim().slice(1)
    : "Workspace";

  const historySidebarProps = {
    threads,
    projects,
    activeId: activeThread.id,
    selectedProjectId,
    onSelectThread: setActiveId,
    onSelectProject: setSelectedProjectId,
    onNewChat: startNewChat,
    onRenameThread: (threadId: string, title: string) =>
      patchThread(threadId, { title }),
    onTogglePinThread: (threadId: string) => {
      const thread = threads.find((item) => item.id === threadId);
      if (!thread) return;
      patchThread(threadId, { pinned: !thread.pinned });
    },
    onArchiveThread: (threadId: string) =>
      patchThread(threadId, { archived: true, pinned: false }),
    onDeleteThread: deleteChat,
    onMoveThread: (threadId: string, projectId: string | null) =>
      patchThread(threadId, { projectId }),
    onTogglePinProject: (projectId: string) => {
      const project = projects.find((item) => item.id === projectId);
      if (!project) return;
      const pinned = !project.pinned;
      setProjects((prev) =>
        upsertProject(prev, { ...project, pinned, updatedAt: new Date().toISOString() }),
      );
      void patchProject(projectId, { pinned }).catch(() => {});
    },
    onCreateProject: handleCreateProject,
    onRenameProject: (projectId: string, name: string) => {
      const project = projects.find((item) => item.id === projectId);
      if (!project) return;
      setProjects((prev) =>
        upsertProject(prev, { ...project, name, updatedAt: new Date().toISOString() }),
      );
      void patchProject(projectId, { name }).catch(() => {});
    },
  };

  return (
    <div className="-mx-3 -my-4 grid h-[calc(100dvh-3.5rem)] min-h-[24rem] overflow-hidden sm:-mx-6 sm:-my-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <ChatHistorySidebar className="hidden lg:flex" {...historySidebarProps} />

      {historyOpen ? (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Chat history"
        >
          <button
            type="button"
            className="absolute inset-0 bg-black/55 backdrop-blur-[1px]"
            aria-label="Close chat history"
            onClick={() => setHistoryOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-[min(18rem,90vw)] flex-col bg-sidebar shadow-2xl">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <p className="text-sm font-medium">Chats</p>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Close chat history"
                onClick={() => setHistoryOpen(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <ChatHistorySidebar
              className="min-h-0 flex-1 border-r-0"
              onNavigate={() => setHistoryOpen(false)}
              {...historySidebarProps}
            />
          </div>
        </div>
      ) : null}

      <section className="flex min-h-0 min-w-0 flex-col bg-background">
        <div className="shrink-0 border-b border-border px-3 py-2.5 sm:px-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="lg:hidden"
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen(true)}
            >
              <History className="h-4 w-4" />
              Chats
            </Button>
            <span className="text-xs font-medium text-muted">Context:</span>
            <Badge variant="default" className="max-w-[min(18rem,55vw)] truncate">
              {contextLabel}
            </Badge>
            <span className="hidden text-xs text-muted sm:inline">
              {hasScopedContext
                ? "Conversation is scoped to this document"
                : "Searching the open corpus"}
            </span>
            <div className="ml-auto flex flex-wrap items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowInspect((value) => !value);
                  setShowChangeContext(false);
                }}
              >
                <span className="sm:hidden">Inspect</span>
                <span className="hidden sm:inline">Inspect retrieval</span>
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowChangeContext((value) => !value);
                  setShowInspect(false);
                }}
              >
                <span className="sm:hidden">Context</span>
                <span className="hidden sm:inline">Change context</span>
              </Button>
            </div>
          </div>

          {showInspect ? (
            <div className="mt-3">
              {lastAssistant ? (
                <RetrievalDetails message={lastAssistant} />
              ) : (
                <p className="text-xs text-muted">
                  No assistant reply yet to inspect.
                </p>
              )}
            </div>
          ) : null}

          {showChangeContext ? (
            <div className="mt-3 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface px-3 py-3">
              <label className="min-w-[8rem] flex-1 text-sm">
                <span className="text-xs text-muted">Mode</span>
                <select
                  value={activeThread.mode}
                  onChange={(event) => updateActive({ mode: event.target.value })}
                  className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  {MODES.map((mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  ))}
                </select>
              </label>
              <label className="min-w-[12rem] flex-[2] text-sm">
                <span className="text-xs text-muted">
                  Manual document override (optional)
                </span>
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
              </label>
              {activeThread.pendingExpandQuestion ? (
                <p className="w-full text-xs text-warning">
                  Waiting for Yes to search other documents.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-4 sm:py-5">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
            {activeThread.messages.length === 0 ? (
              <div className="px-1 py-10 text-center sm:py-16">
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
                    initials={initials}
                    uploaderName={uploaderName}
                  />
                );
              })
            )}
            {busy ? (
              <div className="flex items-start gap-2 sm:gap-3">
                <div className="mt-1 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent sm:flex">
                  <Sparkles className="h-4 w-4 animate-pulse" aria-hidden />
                </div>
                <div className="rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-muted">
                  Retrieving and answering…
                </div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
        </div>

        {error ? (
          <p className="mx-4 mb-2 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <form onSubmit={onSubmit} className="shrink-0 px-3 pb-3 sm:px-4 sm:pb-4">
          <div className="relative mx-auto w-full max-w-3xl rounded-2xl border border-border bg-surface p-2.5 shadow-sm sm:p-3">
            {mention && mentionMatches.length ? (
              <div className="absolute bottom-full left-2 z-20 mb-2 w-64 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
                {mentionMatches.map((command, index) => (
                  <button
                    key={command.key}
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      selectMention(command);
                    }}
                    className={cn(
                      "flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm",
                      index === mention.highlight
                        ? "bg-accent-soft text-accent"
                        : "hover:bg-surface-elevated",
                    )}
                  >
                    <span className="font-medium">@{command.label}</span>
                    <span className="text-xs text-muted">{command.description}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {activeThread.interactionMode === "search" ? (
              <div className="mb-2">
                <Badge variant="default" className="text-xs">
                  Search mode — type @chat to switch back
                </Badge>
              </div>
            ) : null}
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(event) => {
                const value = event.target.value;
                setDraft(value);
                const cursor = event.target.selectionStart ?? value.length;
                const trigger = detectMentionTrigger(value, cursor);
                if (!trigger) {
                  setMention(null);
                  return;
                }
                const matches = MENTION_COMMANDS.filter((command) =>
                  command.label.startsWith(trigger.query),
                );
                setMention(
                  matches.length
                    ? { query: trigger.query, start: trigger.start, highlight: 0 }
                    : null,
                );
              }}
              onKeyDown={(event) => {
                if (mention && mentionMatches.length) {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setMention((prev) =>
                      prev
                        ? { ...prev, highlight: (prev.highlight + 1) % mentionMatches.length }
                        : prev,
                    );
                    return;
                  }
                  if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setMention((prev) =>
                      prev
                        ? {
                            ...prev,
                            highlight:
                              (prev.highlight - 1 + mentionMatches.length) %
                              mentionMatches.length,
                          }
                        : prev,
                    );
                    return;
                  }
                  if (event.key === "Enter" || event.key === "Tab") {
                    event.preventDefault();
                    selectMention(mentionMatches[mention.highlight] ?? mentionMatches[0]);
                    return;
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setMention(null);
                    return;
                  }
                }
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(draft);
                }
              }}
              rows={3}
              placeholder={`Ask about ${contextLabel}… (@search or @chat to switch modes)`}
              className="max-h-40 min-h-[4.5rem] w-full resize-y bg-transparent px-1 py-1 text-[15px] outline-none placeholder:text-muted"
              disabled={busy}
            />
            <div className="mt-2 flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openMentionMenu}
                disabled={busy}
              >
                <AtSign className="h-4 w-4" />
                <span className="hidden sm:inline">chat / search</span>
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled
                title="Coming soon"
              >
                <Paperclip className="h-4 w-4" />
                <span className="hidden sm:inline">Attach</span>
              </Button>
              <Button
                type="submit"
                size="sm"
                className="ml-auto"
                disabled={busy || !draft.trim()}
              >
                <Send className="h-4 w-4" />
                Send
              </Button>
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function QueryPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <ChatWorkspace />
    </Suspense>
  );
}
