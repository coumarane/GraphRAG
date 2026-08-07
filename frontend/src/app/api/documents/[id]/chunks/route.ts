import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id } = await params;
  const qs = new URL(request.url).searchParams.toString();
  const path = qs
    ? `/api/v1/documents/${id}/chunks?${qs}`
    : `/api/v1/documents/${id}/chunks`;
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
