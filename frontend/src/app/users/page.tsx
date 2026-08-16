"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchSession, readCachedSession } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type UserRow = {
  user_id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
  attributes: Record<string, unknown>;
};

export default function UsersPage() {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState("member");
  const [creating, setCreating] = useState(false);

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
      try {
        await loadUsers();
      } catch {
        setError("Unable to load users");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName || null,
          role,
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
      setDisplayName("");
      setRole("member");
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
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
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
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <p className="text-sm text-muted">
          Invite and manage members for this workspace
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace members</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {users.length === 0 ? (
            <p className="text-muted">No users found.</p>
          ) : (
            users.map((user) => (
              <div
                key={user.user_id}
                className="flex items-center justify-between border-b border-border/40 py-2 last:border-0"
              >
                <div>
                  <p className="font-medium">
                    {user.display_name || user.email}
                  </p>
                  <p className="text-xs text-muted">{user.email}</p>
                </div>
                <div className="text-right text-xs text-muted">
                  <p className="font-mono uppercase">{user.role}</p>
                  <p>{user.status}</p>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Invite user</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={(event) => void onCreate(event)}>
            <Input
              type="email"
              required
              placeholder="email@company.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Input
              type="password"
              required
              minLength={12}
              placeholder="Password (min 12 chars)"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <Input
              placeholder="Display name (optional)"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
            <select
              className="h-10 w-full rounded-md border border-border bg-surface px-3 text-sm"
              value={role}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <Button type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create user"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
