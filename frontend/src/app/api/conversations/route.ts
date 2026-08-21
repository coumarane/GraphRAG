import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  const path = qs ? `/api/v1/conversations?${qs}` : "/api/v1/conversations";
  return proxyJson(path, { request, method: "GET" });
}

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/api/v1/conversations", {
    request,
    method: "POST",
    body,
  });
}
