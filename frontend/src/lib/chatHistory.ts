/** Client-side chat history persistence (per tenant). */

export type ChatCitation = {
  citation_id?: string;
  chunk_id?: string;
  document_id?: string;
  document_name?: string;
  evidence?: string;
  quote?: string;
  page_start?: number | null;
  page_end?: number | null;
  section_path?: string[];
  modality?: string;
};

export type ChatGraphPath = {
  nodes?: string[];
  relationships?: string[];
  supporting_citations?: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  citations?: ChatCitation[];
  warnings?: string[];
  retrieval_mode?: string;
  retrieval_trace_id?: string;
  graph_paths?: ChatGraphPath[];
};

export type ConversationContext = {
  label: string;
  documentIds: string[];
  entities?: string[];
};

export type ChatThread = {
  id: string;
  title: string;
  documentId: string;
  mode: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  /** Last user question waiting for "yes" to search beyond conversation context. */
  pendingExpandQuestion?: string | null;
  /** Sticky context established by the first Q/A (not a manual UUID filter). */
  conversationContext?: ConversationContext | null;
};

const STORAGE_PREFIX = "enterprise-rag-chats:";

function storageKey(tenantKey: string): string {
  return `${STORAGE_PREFIX}${tenantKey || "demo"}`;
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `chat_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function createEmptyThread(
  overrides?: Partial<Pick<ChatThread, "mode" | "documentId">>,
): ChatThread {
  const now = new Date().toISOString();
  return {
    id: newId(),
    title: "New chat",
    documentId: overrides?.documentId ?? "",
    mode: overrides?.mode ?? "auto",
    createdAt: now,
    updatedAt: now,
    messages: [],
    pendingExpandQuestion: null,
    conversationContext: null,
  };
}

export function isScopeExpandAffirmative(text: string): boolean {
  return /^(yes|y|yeah|yep|sure|ok|okay|please do|go ahead|search(?:\s+all)?|expand|broader|all documents)\.?$/i.test(
    text.trim(),
  );
}

export function loadChatThreads(tenantKey: string): ChatThread[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey(tenantKey));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatThread[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((thread) => thread && typeof thread.id === "string")
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  } catch {
    return [];
  }
}

export function saveChatThreads(tenantKey: string, threads: ChatThread[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(tenantKey), JSON.stringify(threads));
}

export function upsertThread(
  threads: ChatThread[],
  thread: ChatThread,
): ChatThread[] {
  const others = threads.filter((item) => item.id !== thread.id);
  return [thread, ...others].sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
}

export function titleFromQuestion(question: string): string {
  const cleaned = question.replace(/\s+/g, " ").trim();
  if (!cleaned) return "New chat";
  return cleaned.length > 48 ? `${cleaned.slice(0, 48).trimEnd()}…` : cleaned;
}

export function buildConversationalQuestion(
  history: ChatMessage[],
  latestQuestion: string,
): string {
  const prior = history.slice(-4);
  if (!prior.length) return latestQuestion;
  // Keep prior USER turns for pronoun resolution; truncate assistant text hard so
  // earlier product lines (e.g. METASHINE) do not dominate retrieval embeddings.
  const transcript = prior
    .map((message) => {
      const role = message.role === "user" ? "User" : "Assistant";
      const limit = message.role === "assistant" ? 160 : 400;
      const text = message.content.replace(/\s+/g, " ").trim().slice(0, limit);
      return `${role}: ${text}`;
    })
    .join("\n");
  return [
    "Conversation so far:",
    transcript,
    "",
    `Current question: ${latestQuestion}`,
    "",
    "Answer the current question using retrieved document evidence.",
    "Use prior turns only to resolve references (e.g. \"that product\", \"those values\").",
    "Do not invent facts from chat history that are not grounded in retrieved evidence.",
    "Do not keep answering about a prior product line unless the current question asks about it.",
  ].join("\n");
}

export function createMessage(
  role: ChatMessage["role"],
  content: string,
  extras?: Partial<ChatMessage>,
): ChatMessage {
  return {
    id: newId(),
    role,
    content,
    createdAt: new Date().toISOString(),
    ...extras,
  };
}
