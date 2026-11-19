import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC Hotels data mart (built by pipeline/hotels/build_datamart.py; never placed in /public).
export async function GET() {
  const body = await readFile(path.join(process.cwd(), "private", "hotels", "datamart.json"));
  return new Response(body, { headers: { "content-type": "application/json", "cache-control": "private, no-store" } });
}
