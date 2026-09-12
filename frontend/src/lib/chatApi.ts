/** Server-persisted chat history (conversations/messages/projects live in the backend). */

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

export type InteractionMode = "chat" | "search";

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
  interaction_mode?: InteractionMode;
};

export type ConversationContext = {
  label: string;
  documentIds: string[];
  entities?: string[];
};

export type ChatProject = {
  id: string;
  name: string;
  pinned?: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ChatThread = {
  id: string;
  title: string;
  documentId: string;
  mode: string;
  interactionMode: InteractionMode;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  /** Last user question waiting for "yes" to search beyond conversation context. */
  pendingExpandQuestion?: string | null;
  /** Sticky context established by the first Q/A (not a manual UUID filter). */
  conversationContext?: ConversationContext | null;
  pinned?: boolean;
  archived?: boolean;
  projectId?: string | null;
};

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `chat_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function createEmptyThread(
  overrides?: Partial<
    Pick<ChatThread, "mode" | "interactionMode" | "documentId" | "projectId" | "title">
  >,
): ChatThread {
  const now = new Date().toISOString();
  return {
    id: newId(),
    title: overrides?.title ?? "New chat",
    documentId: overrides?.documentId ?? "",
    mode: overrides?.mode ?? "auto",
    interactionMode: overrides?.interactionMode ?? "chat",
    createdAt: now,
    updatedAt: now,
    messages: [],
    pendingExpandQuestion: null,
    conversationContext: null,
    pinned: false,
    archived: false,
    projectId: overrides?.projectId ?? null,
  };
}

export function createProject(name: string): ChatProject {
  const now = new Date().toISOString();
  return {
    id: newId(),
    name: name.trim() || "Untitled project",
    pinned: false,
    createdAt: now,
    updatedAt: now,
  };
}

export function isScopeExpandAffirmative(text: string): boolean {
  return /^(yes|y|yeah|yep|sure|ok|okay|please do|go ahead|search(?:\s+all)?|expand|broader|all documents)\.?$/i.test(
    text.trim(),
  );
}

function normalizeThread(thread: ChatThread): ChatThread {
  return {
    ...thread,
    pinned: Boolean(thread.pinned),
    archived: Boolean(thread.archived),
    projectId: thread.projectId ?? null,
  };
}

export function upsertThread(
  threads: ChatThread[],
  thread: ChatThread,
): ChatThread[] {
  const others = threads.filter((item) => item.id !== thread.id);
  return [normalizeThread(thread), ...others].sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
}

export function upsertProject(
  projects: ChatProject[],
  project: ChatProject,
): ChatProject[] {
  const others = projects.filter((item) => item.id !== project.id);
  return [project, ...others].sort((a, b) =>
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

// --- Server-backed persistence ---------------------------------------------

type ConversationApiResponse = {
  conversation_id: string;
  title: string;
  mode: string;
  interaction_mode?: InteractionMode;
  document_id?: string | null;
  pending_expand_question?: string | null;
  conversation_context?: {
    label: string;
    document_ids: string[];
    entities?: string[];
  } | null;
  pinned: boolean;
  archived: boolean;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
};

type ConversationDetailApiResponse = ConversationApiResponse & {
  messages: {
    message_id: string;
    role: "user" | "assistant";
    content: string;
    citations?: ChatCitation[];
    warnings?: string[];
    retrieval_mode?: string | null;
    retrieval_trace_id?: string | null;
    graph_paths?: ChatGraphPath[];
    interaction_mode?: InteractionMode;
    created_at: string;
  }[];
};

type ProjectApiResponse = {
  project_id: string;
  name: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
};

function threadFromDetail(detail: ConversationDetailApiResponse): ChatThread {
  return {
    id: detail.conversation_id,
    title: detail.title,
    documentId: detail.document_id ?? "",
    mode: detail.mode,
    interactionMode: detail.interaction_mode ?? "chat",
    createdAt: detail.created_at,
    updatedAt: detail.updated_at,
    messages: detail.messages.map((message) => ({
      id: message.message_id,
      role: message.role,
      content: message.content,
      createdAt: message.created_at,
      citations: message.citations ?? [],
      warnings: message.warnings ?? [],
      retrieval_mode: message.retrieval_mode ?? undefined,
      retrieval_trace_id: message.retrieval_trace_id ?? undefined,
      graph_paths: message.graph_paths ?? [],
      interaction_mode: message.interaction_mode ?? "search",
    })),
    pendingExpandQuestion: detail.pending_expand_question ?? null,
    conversationContext: detail.conversation_context
      ? {
          label: detail.conversation_context.label,
          documentIds: detail.conversation_context.document_ids,
          entities: detail.conversation_context.entities ?? [],
        }
      : null,
    pinned: detail.pinned,
    archived: detail.archived,
    projectId: detail.project_id ?? null,
  };
}

function projectFromApi(project: ProjectApiResponse): ChatProject {
  return {
    id: project.project_id,
    name: project.name,
    pinned: project.pinned,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
  };
}

async function apiGet<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status}`);
  return (await response.json()) as T;
}

async function apiSend<T>(
  url: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown,
): Promise<T | null> {
  const response = await fetch(url, {
    credentials: "include",
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${url} failed: ${response.status}`);
  if (response.status === 204) return null;
  return (await response.json()) as T;
}

export async function fetchConversations(): Promise<ChatThread[]> {
  const list = await apiGet<{ items: ConversationApiResponse[] }>(
    "/api/conversations",
  );
  const details = await Promise.all(
    list.items.map((item) =>
      apiGet<ConversationDetailApiResponse>(
        `/api/conversations/${item.conversation_id}`,
      ),
    ),
  );
  return details.map(threadFromDetail).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
}

export async function fetchProjects(): Promise<ChatProject[]> {
  const list = await apiGet<ProjectApiResponse[]>("/api/chat-projects");
  return list.map(projectFromApi).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
}

export async function createConversation(thread: ChatThread): Promise<void> {
  await apiSend("/api/conversations", "POST", {
    conversation_id: thread.id,
    title: thread.title,
    mode: thread.mode,
    interaction_mode: thread.interactionMode,
    document_id: thread.documentId || null,
    project_id: thread.projectId ?? null,
  });
}

export async function patchConversation(
  id: string,
  patch: Partial<{
    title: string;
    mode: string;
    interaction_mode: InteractionMode;
    document_id: string | null;
    project_id: string | null;
    pinned: boolean;
    archived: boolean;
  }>,
): Promise<void> {
  await apiSend(`/api/conversations/${id}`, "PATCH", patch);
}

export async function deleteConversation(id: string): Promise<void> {
  await apiSend(`/api/conversations/${id}`, "DELETE");
}

export async function createProjectRemote(project: ChatProject): Promise<void> {
  await apiSend("/api/chat-projects", "POST", {
    project_id: project.id,
    name: project.name,
  });
}

export async function patchProject(
  id: string,
  patch: Partial<{ name: string; pinned: boolean }>,
): Promise<void> {
  await apiSend(`/api/chat-projects/${id}`, "PATCH", patch);
}

export async function deleteProjectRemote(id: string): Promise<void> {
  await apiSend(`/api/chat-projects/${id}`, "DELETE");
}
