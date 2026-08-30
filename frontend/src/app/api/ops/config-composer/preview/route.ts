import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/api/v1/ops/config-composer/preview", {
    request,
    method: "POST",
    body,
  });
}
