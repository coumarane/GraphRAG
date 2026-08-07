import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  const path = qs
    ? `/api/v1/documents?${qs}`
    : "/api/v1/documents";
  const upstream = await fetch(`${getRagApiUrl()}${path}`, {
    headers: tenantHeaders(request),
    cache: "no-store",
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
