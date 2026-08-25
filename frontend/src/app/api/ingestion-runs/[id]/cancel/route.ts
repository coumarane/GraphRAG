import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params) {
  const { id } = await params;
  return proxyJson(`/api/v1/ingestion-runs/${id}/cancel`, {
    request,
    method: "POST",
  });
}
