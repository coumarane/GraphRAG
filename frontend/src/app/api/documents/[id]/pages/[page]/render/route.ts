import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string; page: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id, page } = await params;
  const qs = new URL(request.url).searchParams.toString();
  const path = qs
    ? `/api/v1/documents/${id}/pages/${page}/render?${qs}`
    : `/api/v1/documents/${id}/pages/${page}/render`;
  const upstream = await fetch(`${getRagApiUrl()}${path}`, {
    headers: tenantHeaders(request),
    cache: "no-store",
  });
  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") || "application/json",
      },
    });
  }
  const buffer = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set("Content-Type", upstream.headers.get("Content-Type") || "image/png");
  const cacheControl = upstream.headers.get("Cache-Control");
  if (cacheControl) headers.set("Cache-Control", cacheControl);
  return new Response(buffer, { status: 200, headers });
}
