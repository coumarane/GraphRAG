"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { fetchSession, readCachedSession } from "@/lib/auth";
import {
  AdminButton,
  AdminCard,
  AdminField,
  AdminModal,
  ErrorBanner,
  adminInputClass,
} from "@/components/admin/widgets";

type UserRow = {
  user_id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
  created_at: string | null;
};

export function UsersPanel() {
  const [items, setItems] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ email: "", password: "", display_name: "", role: "user" });

  async function load() {
    try {
      const res = await fetch("/api/admin/users", { credentials: "include" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail || body.message || `Unable to load users (${res.status})`);
      }
      setItems(body.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    const session = readCachedSession();
    setMe(session?.user.user_id || null);
    void fetchSession().then((value) => setMe(value?.user.user_id || null));
    void load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    const res = await fetch("/api/admin/users", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: draft.email,
        password: draft.password,
        display_name: draft.display_name || null,
        role: draft.role === "user" ? "member" : draft.role,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Unable to create user");
    }
    setOpen(false);
    await load();
  }

  async function patchRole(userId: string, role: string) {
    await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: role === "user" ? "member" : role }),
    });
    await load();
  }

  return (
    <AdminCard>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Users</h2>
          <p className="text-sm text-[var(--muted)]">
            Manage roles and access for all users in the platform.
          </p>
        </div>
        <AdminButton onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> Create user
        </AdminButton>
      </div>
      <ErrorBanner error={error} />
      <div className="space-y-2">
        {items.map((user) => (
          <div
            key={user.user_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] px-4 py-3"
          >
            <div>
              <p className="font-medium">
                {user.display_name || user.email.split("@")[0]}
                {user.user_id === me ? (
                  <span className="ml-2 text-xs text-[var(--muted)]">(you)</span>
                ) : null}
                {user.status !== "active" ? (
                  <span className="ml-2 rounded-full bg-danger/15 px-2 py-0.5 text-xs text-danger">
                    {user.status}
                  </span>
                ) : null}
              </p>
              <p className="text-sm text-[var(--muted)]">{user.email}</p>
              {user.created_at ? (
                <p className="text-xs text-[var(--muted)]">
                  Joined {new Date(user.created_at).toLocaleString()}
                </p>
              ) : null}
            </div>
            <select
              className={`${adminInputClass} w-40`}
              value={user.role === "member" ? "user" : user.role}
              onChange={(event) => void patchRole(user.user_id, event.target.value)}
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
              <option value="system admin">system admin</option>
            </select>
          </div>
        ))}
      </div>
      <AdminModal open={open} title="Create user" onClose={() => setOpen(false)}>
        <form className="space-y-3" onSubmit={(event) => void create(event)}>
          <AdminField label="Email">
            <input
              className={adminInputClass}
              type="email"
              value={draft.email}
              onChange={(event) => setDraft({ ...draft, email: event.target.value })}
              required
            />
          </AdminField>
          <AdminField label="Password">
            <input
              className={adminInputClass}
              type="password"
              value={draft.password}
              onChange={(event) => setDraft({ ...draft, password: event.target.value })}
              required
            />
          </AdminField>
          <AdminField label="Display name">
            <input
              className={adminInputClass}
              value={draft.display_name}
              onChange={(event) => setDraft({ ...draft, display_name: event.target.value })}
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
