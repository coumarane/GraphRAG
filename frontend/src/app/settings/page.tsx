"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AuthSession,
  fetchSession,
  logoutRequest,
  readCachedSession,
} from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type QuotaRow = {
  metric: string;
  period: string;
  limit: number;
  used: number;
  remaining: number;
  reset_at: string;
};

export default function SettingsPage() {
  const router = useRouter();
  // Start null so SSR and the first client render match (avoid hydration mismatch).
  const [session, setSession] = useState<AuthSession | null>(null);
  const [quotas, setQuotas] = useState<QuotaRow[]>([]);
  const [quotaError, setQuotaError] = useState<string | null>(null);

  useEffect(() => {
    setSession(readCachedSession());
    void fetchSession().then(setSession);
    void (async () => {
      try {
        const res = await fetch("/api/users/me/quotas", { credentials: "include" });
        if (!res.ok) {
          setQuotaError(`Unable to load quotas (${res.status})`);
          return;
        }
        const data = (await res.json()) as { items?: QuotaRow[] };
        setQuotas(data.items || []);
      } catch {
        setQuotaError("Unable to load quotas");
      }
    })();
  }, []);

  async function onLogout() {
    await logoutRequest();
    router.replace("/login");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Configuration</h1>
        <p className="text-sm text-muted">Profile, workspace identity, and quotas</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Signed-in user</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted">Email: </span>
            {session?.user.email || "—"}
          </p>
          <p>
            <span className="text-muted">Name: </span>
            {session?.user.display_name || "—"}
          </p>
          <p>
            <span className="text-muted">Role: </span>
            {session?.user.role || "—"}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>My quotas</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {quotaError ? <p className="text-muted">{quotaError}</p> : null}
          {!quotaError && quotas.length === 0 ? (
            <p className="text-muted">No quota assignments yet.</p>
          ) : null}
          {quotas.map((row) => (
            <div
              key={`${row.metric}-${row.period}`}
              className="flex items-center justify-between border-b border-border/40 py-2 last:border-0"
            >
              <div>
                <p className="font-medium">
                  {row.metric} / {row.period}
                </p>
                <p className="text-xs text-muted">Resets {row.reset_at}</p>
              </div>
              <p className="font-mono text-xs">
                {row.used} / {row.limit} ({row.remaining} left)
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted">Tenant: </span>
            {session?.tenant.display_name || session?.tenant.tenant_key || "—"}
          </p>
          <p>
            <span className="text-muted">Tenant ID: </span>
            <span className="font-mono text-xs">
              {session?.tenant.tenant_id || "—"}
            </span>
          </p>
          <Button variant="danger" className="mt-4" onClick={() => void onLogout()}>
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
