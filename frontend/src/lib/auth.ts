export type AuthSession = {
  user: {
    user_id: string;
    email: string;
    display_name: string | null;
    role: string;
    tenant_id: string;
  };
  tenant: {
    tenant_id: string;
    tenant_key: string;
    display_name: string | null;
  };
};

const SESSION_KEY = "enterprise-rag-session";

export function cacheSession(session: AuthSession | null): void {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(SESSION_KEY);
    return;
  }
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function readCachedSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
}

export async function fetchSession(): Promise<AuthSession | null> {
  const response = await fetch("/api/auth/me", { credentials: "include" });
  if (!response.ok) {
    cacheSession(null);
    return null;
  }
  const body = (await response.json()) as AuthSession;
  cacheSession(body);
  return body;
}

export async function loginRequest(
  email: string,
  password: string,
): Promise<AuthSession> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.message || "Login failed",
    );
  }
  const session: AuthSession = {
    user: body.user,
    tenant: body.tenant,
  };
  cacheSession(session);
  return session;
}

export async function logoutRequest(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  cacheSession(null);
}
