import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const form = await request.formData();
  const upstream = await fetch(`${getRagApiUrl()}/api/v1/documents/ingest`, {
    method: "POST",
    headers: tenantHeaders(request),
    body: form,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
