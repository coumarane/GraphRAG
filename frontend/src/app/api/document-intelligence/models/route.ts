import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  return proxyJson("/api/v1/document-intelligence/models", { request, method: "GET" });
}

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/api/v1/document-intelligence/models", {
    request,
    method: "POST",
    body,
  });
}
