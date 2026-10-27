import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(
  request: Request,
  context: { params: Promise<{ uploadId: string }> },
) {
  const { uploadId } = await context.params;
  const body = await request.text();
  const upstream = await fetch(
    `${getRagApiUrl()}/api/v1/documents/uploads/${uploadId}/complete`,
    {
      method: "POST",
      headers: {
        ...tenantHeaders(request),
        "Content-Type": "application/json",
      },
      body,
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
