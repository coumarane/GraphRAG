export function getRagApiUrl(): string {
  return (
    process.env.RAG_API_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_RAG_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000"
  );
}

export function tenantHeaders(request: Request): HeadersInit {
  const tenantKey =
    request.headers.get("x-tenant-key") ||
    process.env.NEXT_PUBLIC_DEFAULT_TENANT_KEY ||
    "demo";
  const correlation =
    request.headers.get("x-correlation-id") || crypto.randomUUID();
  return {
    "X-Tenant-Key": tenantKey,
    "X-Correlation-ID": correlation,
  };
}

export async function proxyJson(
  path: string,
  init: RequestInit & { request: Request },
): Promise<Response> {
  const { request, ...rest } = init;
  const upstream = await fetch(`${getRagApiUrl()}${path}`, {
    ...rest,
    headers: {
      ...tenantHeaders(request),
      ...(rest.headers || {}),
      "Content-Type": "application/json",
    },
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
