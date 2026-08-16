"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ChevronRight,
  Folder,
  MoreHorizontal,
  Pencil,
  Pin,
  Plus,
  Share,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ChatProject, ChatThread } from "@/lib/chatHistory";

type ChatHistorySidebarProps = {
  threads: ChatThread[];
  projects: ChatProject[];
  activeId: string | null;
  selectedProjectId: string | null;
  onSelectThread: (threadId: string) => void;
  onSelectProject: (projectId: string | null) => void;
  onNewChat: () => void;
  onRenameThread: (threadId: string, title: string) => void;
  onTogglePinThread: (threadId: string) => void;
  onArchiveThread: (threadId: string) => void;
  onDeleteThread: (threadId: string) => void;
  onMoveThread: (threadId: string, projectId: string | null) => void;
  onTogglePinProject: (projectId: string) => void;
  onCreateProject: (name: string) => string;
  onRenameProject: (projectId: string, name: string) => void;
  className?: string;
  onNavigate?: () => void;
};

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2 pb-1 pt-3 text-[11px] font-medium tracking-wide text-muted/80">
      {children}
    </p>
  );
}

function ThreadMenu({
  thread,
  projects,
  onClose,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
  onMove,
  onCreateProject,
}: {
  thread: ChatThread;
  projects: ChatProject[];
  onClose: () => void;
  onRename: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onMove: (projectId: string | null) => void;
  onCreateProject: () => void;
}) {
  const [moveOpen, setMoveOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onDoc(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  async function onShare() {
    const text = thread.title;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // ignore
    }
    onClose();
  }

  return (
    <div
      ref={ref}
      className="absolute top-8 right-1 z-40 min-w-[11.5rem] rounded-xl border border-border bg-surface-elevated py-1 shadow-xl"
      role="menu"
    >
      <MenuItem icon={Share} label="Share" onClick={() => void onShare()} />
      <MenuItem icon={Pencil} label="Rename" onClick={onRename} />
      <MenuItem
        icon={Pin}
        label={thread.pinned ? "Unpin chat" : "Pin chat"}
        onClick={onTogglePin}
      />
      <MenuItem icon={Archive} label="Archive" onClick={onArchive} />
      <MenuItem icon={Trash2} label="Delete" danger onClick={onDelete} />
      <div className="my-1 border-t border-border" />
      <div className="relative">
        <button
          type="button"
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-surface"
          onClick={() => setMoveOpen((value) => !value)}
        >
          <Folder className="h-4 w-4 text-muted" />
          <span className="flex-1">Move to project</span>
          <ChevronRight className="h-3.5 w-3.5 text-muted" />
        </button>
        {moveOpen ? (
          <div className="absolute top-0 left-full z-50 ml-1 min-w-[10.5rem] rounded-xl border border-border bg-surface-elevated py-1 shadow-xl">
            <button
              type="button"
              className="flex w-full px-3 py-2 text-left text-sm hover:bg-surface"
              onClick={() => onMove(null)}
            >
              No project
            </button>
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className="flex w-full px-3 py-2 text-left text-sm hover:bg-surface"
                onClick={() => onMove(project.id)}
              >
                {project.name}
              </button>
            ))}
            <div className="my-1 border-t border-border" />
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-accent hover:bg-surface"
              onClick={onCreateProject}
            >
              <Plus className="h-3.5 w-3.5" />
              New project
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface",
        danger ? "text-danger" : "text-foreground",
      )}
      onClick={onClick}
    >
      <Icon className={cn("h-4 w-4", danger ? "text-danger" : "text-muted")} />
      {label}
    </button>
  );
}

export function ChatHistorySidebar({
  threads,
  projects,
  activeId,
  selectedProjectId,
  onSelectThread,
  onSelectProject,
  onNewChat,
  onRenameThread,
  onTogglePinThread,
  onArchiveThread,
  onDeleteThread,
  onMoveThread,
  onTogglePinProject,
  onCreateProject,
  onRenameProject,
  className,
  onNavigate,
}: ChatHistorySidebarProps) {
  const [menuThreadId, setMenuThreadId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [showAllProjects, setShowAllProjects] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const pinnedProjects = useMemo(
    () => projects.filter((project) => project.pinned),
    [projects],
  );
  const unpinnedProjects = useMemo(
    () => projects.filter((project) => !project.pinned),
    [projects],
  );
  const visibleProjects = showAllProjects
    ? unpinnedProjects
    : unpinnedProjects.slice(0, 5);

  const pinnedChats = useMemo(
    () =>
      threads.filter((thread) => thread.pinned && !thread.archived),
    [threads],
  );

  const chatList = useMemo(() => {
    return threads.filter((thread) => {
      if (thread.archived) return showArchived;
      if (thread.pinned && !selectedProjectId) return false;
      if (selectedProjectId && thread.projectId !== selectedProjectId) {
        return false;
      }
      return true;
    });
  }, [threads, selectedProjectId, showArchived]);

  function beginRename(thread: ChatThread) {
    setRenamingId(thread.id);
    setRenameValue(thread.title);
    setMenuThreadId(null);
  }

  function commitRename(threadId: string) {
    const next = renameValue.trim();
    if (next) onRenameThread(threadId, next);
    setRenamingId(null);
  }

  function createAndMove(threadId: string) {
    const name = window.prompt("Project name");
    if (!name?.trim()) return;
    const projectId = onCreateProject(name.trim());
    onMoveThread(threadId, projectId);
    setMenuThreadId(null);
  }

  function selectThread(threadId: string) {
    onSelectThread(threadId);
    onNavigate?.();
  }

  return (
    <aside
      className={cn(
        "flex min-h-0 flex-col border-r border-border bg-sidebar",
        className,
      )}
    >
      <div className="border-b border-border p-3">
        <Button
          type="button"
          onClick={() => {
            onNewChat();
            onNavigate?.();
          }}
          className="w-full"
          size="sm"
        >
          <Plus className="h-4 w-4" />
          New chat
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {(pinnedProjects.length > 0 || pinnedChats.length > 0) && (
          <div>
            <SectionLabel>Pinned</SectionLabel>
            <ul className="space-y-0.5">
              {pinnedProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    onClick={() =>
                      onSelectProject(
                        selectedProjectId === project.id ? null : project.id,
                      )
                    }
                    onDoubleClick={() => {
                      const name = window.prompt("Rename project", project.name);
                      if (name?.trim()) onRenameProject(project.id, name.trim());
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition-colors",
                      selectedProjectId === project.id
                        ? "bg-surface-elevated text-foreground"
                        : "text-foreground/90 hover:bg-surface",
                    )}
                  >
                    <Folder className="h-4 w-4 shrink-0 text-muted" />
                    <span className="truncate">{project.name}</span>
                  </button>
                </li>
              ))}
              {pinnedChats.map((thread) => (
                <ThreadRow
                  key={thread.id}
                  thread={thread}
                  active={thread.id === activeId}
                  menuOpen={menuThreadId === thread.id}
                  renaming={renamingId === thread.id}
                  renameValue={renameValue}
                  showPin
                  onSelect={() => selectThread(thread.id)}
                  onOpenMenu={() =>
                    setMenuThreadId((id) =>
                      id === thread.id ? null : thread.id,
                    )
                  }
                  onRenameValue={setRenameValue}
                  onCommitRename={() => commitRename(thread.id)}
                  onCancelRename={() => setRenamingId(null)}
                  menu={
                    menuThreadId === thread.id ? (
                      <ThreadMenu
                        thread={thread}
                        projects={projects}
                        onClose={() => setMenuThreadId(null)}
                        onRename={() => beginRename(thread)}
                        onTogglePin={() => {
                          onTogglePinThread(thread.id);
                          setMenuThreadId(null);
                        }}
                        onArchive={() => {
                          onArchiveThread(thread.id);
                          setMenuThreadId(null);
                        }}
                        onDelete={() => {
                          onDeleteThread(thread.id);
                          setMenuThreadId(null);
                        }}
                        onMove={(projectId) => {
                          onMoveThread(thread.id, projectId);
                          setMenuThreadId(null);
                        }}
                        onCreateProject={() => createAndMove(thread.id)}
                      />
                    ) : null
                  }
                />
              ))}
            </ul>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between px-2 pb-1 pt-3">
            <p className="text-[11px] font-medium tracking-wide text-muted/80">
              Projects
            </p>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface hover:text-foreground"
              title="New project"
              onClick={() => {
                const name = window.prompt("Project name");
                if (name?.trim()) onCreateProject(name.trim());
              }}
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <ul className="space-y-0.5">
            {visibleProjects.map((project) => (
              <li key={project.id} className="group relative">
                <button
                  type="button"
                  onClick={() =>
                    onSelectProject(
                      selectedProjectId === project.id ? null : project.id,
                    )
                  }
                  onDoubleClick={() => {
                    const name = window.prompt("Rename project", project.name);
                    if (name?.trim()) onRenameProject(project.id, name.trim());
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition-colors",
                    selectedProjectId === project.id
                      ? "bg-surface-elevated text-foreground"
                      : "text-foreground/90 hover:bg-surface",
                  )}
                >
                  <Folder className="h-4 w-4 shrink-0 text-muted" />
                  <span className="truncate pr-6">{project.name}</span>
                </button>
                <button
                  type="button"
                  title={project.pinned ? "Unpin project" : "Pin project"}
                  className="absolute top-1.5 right-1.5 hidden rounded-md p-1 text-muted hover:bg-surface-elevated hover:text-foreground group-hover:inline-flex"
                  onClick={() => onTogglePinProject(project.id)}
                >
                  <Pin className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
            {!visibleProjects.length ? (
              <li className="px-2.5 py-2 text-xs text-muted">No projects yet</li>
            ) : null}
          </ul>
          {unpinnedProjects.length > 5 ? (
            <button
              type="button"
              className="mt-1 px-2.5 py-1.5 text-xs text-muted hover:text-foreground"
              onClick={() => setShowAllProjects((value) => !value)}
            >
              {showAllProjects ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>

        <div>
          <SectionLabel>
            {selectedProjectId
              ? `Chats · ${projects.find((item) => item.id === selectedProjectId)?.name || "Project"}`
              : "Chats"}
          </SectionLabel>
          {selectedProjectId ? (
            <button
              type="button"
              className="mb-1 px-2.5 text-xs text-accent hover:underline"
              onClick={() => onSelectProject(null)}
            >
              Show all chats
            </button>
          ) : null}
          <ul className="space-y-0.5">
            {chatList.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                active={thread.id === activeId}
                menuOpen={menuThreadId === thread.id}
                renaming={renamingId === thread.id}
                renameValue={renameValue}
                showPin={Boolean(thread.pinned)}
                onSelect={() => selectThread(thread.id)}
                onOpenMenu={() =>
                  setMenuThreadId((id) => (id === thread.id ? null : thread.id))
                }
                onRenameValue={setRenameValue}
                onCommitRename={() => commitRename(thread.id)}
                onCancelRename={() => setRenamingId(null)}
                menu={
                  menuThreadId === thread.id ? (
                    <ThreadMenu
                      thread={thread}
                      projects={projects}
                      onClose={() => setMenuThreadId(null)}
                      onRename={() => beginRename(thread)}
                      onTogglePin={() => {
                        onTogglePinThread(thread.id);
                        setMenuThreadId(null);
                      }}
                      onArchive={() => {
                        onArchiveThread(thread.id);
                        setMenuThreadId(null);
                      }}
                      onDelete={() => {
                        onDeleteThread(thread.id);
                        setMenuThreadId(null);
                      }}
                      onMove={(projectId) => {
                        onMoveThread(thread.id, projectId);
                        setMenuThreadId(null);
                      }}
                      onCreateProject={() => createAndMove(thread.id)}
                    />
                  ) : null
                }
              />
            ))}
            {!chatList.length ? (
              <li className="px-2.5 py-2 text-xs text-muted">No chats yet</li>
            ) : null}
          </ul>
          <button
            type="button"
            className="mt-2 px-2.5 py-1.5 text-xs text-muted hover:text-foreground"
            onClick={() => setShowArchived((value) => !value)}
          >
            {showArchived ? "Hide archived" : "Show archived"}
          </button>
        </div>
      </div>
    </aside>
  );
}

function ThreadRow({
  thread,
  active,
  menuOpen,
  renaming,
  renameValue,
  showPin,
  onSelect,
  onOpenMenu,
  onRenameValue,
  onCommitRename,
  onCancelRename,
  menu,
}: {
  thread: ChatThread;
  active: boolean;
  menuOpen: boolean;
  renaming: boolean;
  renameValue: string;
  showPin?: boolean;
  onSelect: () => void;
  onOpenMenu: () => void;
  onRenameValue: (value: string) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
  menu: React.ReactNode;
}) {
  return (
    <li className="group relative">
      {renaming ? (
        <input
          autoFocus
          value={renameValue}
          onChange={(event) => onRenameValue(event.target.value)}
          onBlur={onCommitRename}
          onKeyDown={(event) => {
            if (event.key === "Enter") onCommitRename();
            if (event.key === "Escape") onCancelRename();
          }}
          className="w-full rounded-xl border border-accent bg-surface px-2.5 py-2 text-sm outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          className={cn(
            "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition-colors",
            active || menuOpen
              ? "bg-surface-elevated text-foreground"
              : "text-foreground/90 hover:bg-surface",
            thread.archived ? "opacity-60" : "",
          )}
        >
          <span className="min-w-0 flex-1 truncate pr-8">{thread.title}</span>
          {showPin ? <Pin className="h-3.5 w-3.5 shrink-0 text-muted" /> : null}
        </button>
      )}
      {!renaming ? (
        <button
          type="button"
          aria-label="Chat actions"
          onClick={(event) => {
            event.stopPropagation();
            onOpenMenu();
          }}
          className={cn(
            "absolute top-1.5 right-1.5 rounded-md p-1 text-muted hover:bg-background hover:text-foreground",
            menuOpen ? "inline-flex" : "hidden group-hover:inline-flex",
          )}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      ) : null}
      {menu}
    </li>
  );
}
