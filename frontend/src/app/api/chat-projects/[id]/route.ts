import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;
  const body = await request.text();
  return proxyJson(`/api/v1/chat-projects/${id}`, {
    request,
    method: "PATCH",
    body,
  });
}

export async function DELETE(request: Request, { params }: Params) {
  const { id } = await params;
  return proxyJson(`/api/v1/chat-projects/${id}`, { request, method: "DELETE" });
}
