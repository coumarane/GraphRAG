"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchSession, readCachedSession } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  EMPTY_PERMISSIONS,
  UserPermissionFields,
  permissionPayload,
  permissionsFromAttributes,
  type UserPermissionValues,
} from "@/components/UserPermissionFields";

type UserRow = {
  user_id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
  attributes: Record<string, unknown>;
};

function statusVariant(status: string) {
  if (status === "active") return "success" as const;
  if (status === "suspended") return "warning" as const;
  return "danger" as const;
}

export default function UsersPage() {
  const router = useRouter();
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState<UserPermissionValues>(EMPTY_PERMISSIONS);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<UserPermissionValues>(EMPTY_PERMISSIONS);
  const [savingId, setSavingId] = useState<string | null>(null);

  async function loadUsers() {
    const res = await fetch("/api/admin/users", { credentials: "include" });
    if (res.status === 403) {
      setAllowed(false);
      setError("Admin access required");
      return;
    }
    if (!res.ok) {
      setError(`Unable to load users (${res.status})`);
      return;
    }
    const data = (await res.json()) as { items?: UserRow[] };
    setUsers(data.items || []);
    setAllowed(true);
    setError(null);
  }

  useEffect(() => {
    void (async () => {
      const session = readCachedSession() || (await fetchSession());
      if (!session || session.user.role !== "admin") {
        setAllowed(false);
        setLoading(false);
        return;
      }
      setCurrentUserId(session.user.user_id);
      try {
        await loadUsers();
      } catch {
        setError("Unable to load users");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function beginEdit(user: UserRow) {
    setEditingId(user.user_id);
    setDraft(permissionsFromAttributes(user));
    setError(null);
  }

  async function onSave(user: UserRow) {
    setSavingId(user.user_id);
    setError(null);
    try {
      const payload = permissionPayload(draft);
      const res = await fetch(`/api/admin/users/${user.user_id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || `Update failed (${res.status})`,
        );
      }
      setEditingId(null);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setSavingId(null);
    }
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const payload = permissionPayload(invite);
      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: payload.display_name,
          role: payload.role,
          attributes: payload.attributes,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : body.message || `Create failed (${res.status})`,
        );
      }
      setEmail("");
      setPassword("");
      setInvite(EMPTY_PERMISSIONS);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted">Loading users…</p>;
  }

  if (!allowed) {
    return (
      <div className="mx-auto max-w-xl space-y-3">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Users</h1>
        <p className="text-sm text-muted">
          {error || "Only workspace admins can manage users."}
        </p>
        <Button variant="secondary" onClick={() => router.push("/settings")}>
          Back to configuration
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Users</h1>
        <p className="text-sm text-muted">
          Invite members and manage ABAC permissions for this workspace
        </p>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Workspace members</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {users.length === 0 ? (
            <p className="text-muted">No users found.</p>
          ) : (
            users.map((user) => {
              const attrs = user.attributes || {};
              const isSelf = user.user_id === currentUserId;
              const isEditing = editingId === user.user_id;
              const groups = Array.isArray(attrs.groups)
                ? attrs.groups.map(String)
                : [];
              return (
                <div
                  key={user.user_id}
                  className="rounded-lg border border-border/60 px-3 py-3"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <p className="font-medium">
                        {user.display_name || user.email}
                        {isSelf ? (
                          <span className="ml-2 text-xs text-muted">(you)</span>
                        ) : null}
                      </p>
                      <p className="truncate text-xs text-muted">{user.email}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge variant={user.role === "admin" ? "default" : "muted"}>
                          {user.role}
                        </Badge>
                        <Badge variant={statusVariant(user.status)}>{user.status}</Badge>
                        {attrs.can_ingest !== false ? (
                          <Badge variant="muted">ingest</Badge>
                        ) : null}
                        {attrs.clearance_level != null ? (
                          <Badge variant="muted">
                            clearance {String(attrs.clearance_level)}
                          </Badge>
                        ) : null}
                        {attrs.country ? (
                          <Badge variant="muted">{String(attrs.country)}</Badge>
                        ) : null}
                        {attrs.department ? (
                          <Badge variant="muted">{String(attrs.department)}</Badge>
                        ) : null}
                        {groups.map((group) => (
                          <Badge key={group} variant="muted">
                            {group}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        isEditing ? setEditingId(null) : beginEdit(user)
                      }
                    >
                      {isEditing ? "Close" : "Manage permissions"}
                    </Button>
                  </div>
                  {isEditing ? (
                    <div className="mt-4 space-y-4 border-t border-border/50 pt-4">
                      <UserPermissionFields
                        values={draft}
                        onChange={setDraft}
                        showStatus
                        lockAdmin={isSelf}
                      />
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          disabled={savingId === user.user_id}
                          onClick={() => void onSave(user)}
                        >
                          {savingId === user.user_id ? "Saving…" : "Save permissions"}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => setEditingId(null)}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Invite user</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(event) => void onCreate(event)}>
            <label className="block space-y-1.5">
              <Label className="text-xs uppercase tracking-wide">Email</Label>
              <Input
                type="email"
                required
                placeholder="email@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label className="block space-y-1.5">
              <Label className="text-xs uppercase tracking-wide">Password</Label>
              <Input
                type="password"
                required
                minLength={12}
                placeholder="Password (min 12 chars)"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <UserPermissionFields values={invite} onChange={setInvite} />
            <Button type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create user"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
