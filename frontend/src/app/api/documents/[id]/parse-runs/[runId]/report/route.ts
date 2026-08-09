import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string; runId: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id, runId } = await params;
  const upstream = await fetch(
    `${getRagApiUrl()}/api/v1/documents/${id}/ingestion-runs/${runId}/report`,
    {
      headers: tenantHeaders(request),
      cache: "no-store",
    },
  );
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
