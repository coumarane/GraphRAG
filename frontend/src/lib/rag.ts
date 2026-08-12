export function getRagApiUrl(): string {
  return (
    process.env.RAG_API_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_RAG_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000"
  );
}

export function upstreamHeaders(request: Request): HeadersInit {
  const correlation =
    request.headers.get("x-correlation-id") || crypto.randomUUID();
  const headers: Record<string, string> = {
    "X-Correlation-ID": correlation,
  };
  const cookie = request.headers.get("cookie");
  if (cookie) headers.Cookie = cookie;
  const authorization = request.headers.get("authorization");
  if (authorization) headers.Authorization = authorization;
  const serviceKey = request.headers.get("x-api-service-key");
  if (serviceKey) headers["X-Api-Service-Key"] = serviceKey;
  // Legacy fallback when auth is disabled on the API.
  const tenantKey =
    request.headers.get("x-tenant-key") ||
    process.env.NEXT_PUBLIC_DEFAULT_TENANT_KEY ||
    "demo";
  headers["X-Tenant-Key"] = tenantKey;
  return headers;
}

/** @deprecated Prefer session-derived tenant; kept for gradual migration. */
export function tenantHeaders(request: Request): HeadersInit {
  return upstreamHeaders(request);
}

export async function proxyJson(
  path: string,
  init: RequestInit & { request: Request },
): Promise<Response> {
  const { request, ...rest } = init;
  const upstream = await fetch(`${getRagApiUrl()}${path}`, {
    ...rest,
    headers: {
      ...upstreamHeaders(request),
      ...(rest.headers || {}),
      "Content-Type": "application/json",
    },
  });
  const text = await upstream.text();
  const headers = new Headers({
    "Content-Type": upstream.headers.get("Content-Type") || "application/json",
  });
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) headers.set("set-cookie", setCookie);
  return new Response(text, {
    status: upstream.status,
    headers,
  });
}
