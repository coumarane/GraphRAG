import { getRagApiUrl, upstreamHeaders } from "@/lib/rag";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();
  const upstream = await fetch(`${getRagApiUrl()}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      ...upstreamHeaders(request),
      "Content-Type": "application/json",
    },
    body,
  });
  const text = await upstream.text();
  const headers = new Headers({
    "Content-Type": upstream.headers.get("Content-Type") || "application/json",
  });
  if (upstream.ok) {
    try {
      const parsed = JSON.parse(text) as { access_token?: string };
      if (parsed.access_token) {
        const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
        headers.set(
          "set-cookie",
          `erag_session=${parsed.access_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200${secure}`,
        );
      }
    } catch {
      // keep upstream body as-is
    }
  }
  return new Response(text, { status: upstream.status, headers });
}
