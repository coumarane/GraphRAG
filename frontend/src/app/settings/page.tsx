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

export default function SettingsPage() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(readCachedSession());

  useEffect(() => {
    void fetchSession().then(setSession);
  }, []);

  async function onLogout() {
    await logoutRequest();
    router.replace("/login");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Configuration</h1>
        <p className="text-sm text-muted">Profile and workspace identity</p>
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
