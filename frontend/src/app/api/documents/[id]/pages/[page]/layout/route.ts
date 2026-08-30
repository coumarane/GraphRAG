import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string; page: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id, page } = await params;
  const search = new URL(request.url).search;
  return proxyJson(`/api/v1/documents/${id}/pages/${page}/layout${search}`, {
    request,
    method: "GET",
  });
}
