import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ userId: string }> };

export async function PATCH(request: Request, { params }: Params) {
  const { userId } = await params;
  const body = await request.text();
  return proxyJson(`/api/v1/admin/users/${userId}`, {
    request,
    method: "PATCH",
    body,
  });
}
