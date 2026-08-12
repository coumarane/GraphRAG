import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id } = await params;
  const url = new URL(request.url);
  const runA = url.searchParams.get("run_a");
  const runB = url.searchParams.get("run_b");
  if (!runA || !runB) {
    return Response.json(
      { detail: "run_a and run_b query params are required" },
      { status: 400 },
    );
  }
  const upstream = await fetch(
    `${getRagApiUrl()}/api/v1/documents/${id}/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`,
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
