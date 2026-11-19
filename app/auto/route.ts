import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC Auto dashboard. private/auto/dashboard.html is a complete HTML document;
// outside Claude it loads /api/data/auto and uses /api/chat.
export async function GET() {
  const html = await readFile(path.join(process.cwd(), "private", "auto", "dashboard.html"), "utf8");
  return new Response(html.replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow">'), {
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "private, no-store" },
  });
}
