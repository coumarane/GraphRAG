import { getRagApiUrl, tenantHeaders } from "@/lib/rag";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params) {
  const { id } = await params;
  const upstream = await fetch(
    `${getRagApiUrl()}/api/v1/documents/${id}/original`,
    {
      headers: tenantHeaders(request),
      cache: "no-store",
    },
  );
  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/json",
      },
    });
  }
  const buffer = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set(
    "Content-Type",
    upstream.headers.get("Content-Type") || "application/octet-stream",
  );
  const disposition = upstream.headers.get("Content-Disposition");
  if (disposition) headers.set("Content-Disposition", disposition);
  return new Response(buffer, { status: 200, headers });
}
