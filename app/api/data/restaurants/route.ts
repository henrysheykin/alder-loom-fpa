import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC Restaurants data mart (built by pipeline/restaurants/*.py; never placed in /public).
export async function GET() {
  const body = await readFile(path.join(process.cwd(), "private", "restaurants", "datamart.json"));
  return new Response(body, { headers: { "content-type": "application/json", "cache-control": "private, no-store" } });
}
