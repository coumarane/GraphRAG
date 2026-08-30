import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params) {
  const { id } = await params;
  const qs = new URL(request.url).searchParams.toString();
  const path = qs
    ? `/api/v1/documents/${id}/reprocess?${qs}`
    : `/api/v1/documents/${id}/reprocess`;
  const body = await request.text();
  return proxyJson(path, { request, method: "POST", body: body || undefined });
}
