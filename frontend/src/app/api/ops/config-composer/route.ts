import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  return proxyJson("/api/v1/ops/config-composer", {
    request,
    method: "GET",
  });
}
