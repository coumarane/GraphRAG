import { getRagApiUrl } from "@/lib/rag";

export const runtime = "nodejs";

export async function GET() {
  const upstream = await fetch(`${getRagApiUrl()}/api/v1/health/ready`);
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
    },
  });
}
