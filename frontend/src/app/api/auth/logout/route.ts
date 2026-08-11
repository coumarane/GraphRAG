import { getRagApiUrl, upstreamHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const upstream = await fetch(`${getRagApiUrl()}/api/v1/auth/logout`, {
    method: "POST",
    headers: upstreamHeaders(request),
  });
  const text = await upstream.text();
  const headers = new Headers({
    "Content-Type": upstream.headers.get("Content-Type") || "application/json",
  });
  headers.append(
    "set-cookie",
    "erag_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
  );
  return new Response(text || JSON.stringify({ status: "ok" }), {
    status: upstream.status,
    headers,
  });
}
