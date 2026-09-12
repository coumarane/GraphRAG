import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/api/v1/documents/search", {
    request,
    method: "POST",
    body,
  });
}
