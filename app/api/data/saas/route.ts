import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC SaaS data mart (built by pipeline/saas/build_datamart.py; never placed in /public).
export async function GET() {
  const body = await readFile(path.join(process.cwd(), "private", "saas", "datamart.json"));
  return new Response(body, { headers: { "content-type": "application/json", "cache-control": "private, no-store" } });
}
