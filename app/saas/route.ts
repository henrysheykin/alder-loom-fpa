import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ABC SaaS dashboard. private/saas/dashboard.html is a complete HTML document and the
// same page as the Claude artifact; outside Claude it loads /api/data/saas and uses /api/chat.
export async function GET() {
  const html = await readFile(path.join(process.cwd(), "private", "saas", "dashboard.html"), "utf8");
  return new Response(html.replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow">'), {
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "private, no-store" },
  });
}
