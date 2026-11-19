import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC Auto data mart (built by pipeline/auto/build_datamart.py; never placed in /public).
export async function GET() {
  const body = await readFile(path.join(process.cwd(), "private", "auto", "datamart.json"));
  return new Response(body, { headers: { "content-type": "application/json", "cache-control": "private, no-store" } });
}
