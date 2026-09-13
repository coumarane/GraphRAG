import { proxyJson } from "@/lib/rag";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ path: string[] }> };

async function forward(request: Request, path: string[], method: string) {
  const joined = path.join("/");
  const search = new URL(request.url).search;
  const init: RequestInit & { request: Request } = { request, method };
  if (method !== "GET" && method !== "HEAD" && method !== "DELETE") {
    init.body = await request.text();
  }
  return proxyJson(`/api/v1/admin/console/${joined}${search}`, init);
}

export async function GET(request: Request, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path, "GET");
}

export async function POST(request: Request, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path, "POST");
}

export async function PATCH(request: Request, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path, "PATCH");
}

export async function DELETE(request: Request, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path, "DELETE");
}
