import { getRagApiUrl, upstreamHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const upstream = await fetch(`${getRagApiUrl()}/api/v1/auth/me`, {
    method: "GET",
    headers: upstreamHeaders(request),
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
