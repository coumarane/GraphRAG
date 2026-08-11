import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  const path = qs ? `/api/v1/ops/usage?${qs}` : "/api/v1/ops/usage";
  return proxyJson(path, {
    request,
    method: "GET",
  });
}
