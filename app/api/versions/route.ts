import { NextRequest, NextResponse } from "next/server";
import { COOKIE, verifySession } from "../../../lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Forecast versions are stored as JSON files in the GitHub repository (forecasts/<type>/<id>.json).
// Every save is a commit, so the history, author and time of each version are auditable.
const REPO = process.env.GITHUB_REPO || "henrysheykin/alder-loom-fpa";
const BRANCH = process.env.GITHUB_BRANCH || "main";
const TYPES = new Set(["cash", "pnl"]);

function gh(path: string, init: RequestInit = {}) {
  return fetch(`https://api.github.com/repos/${REPO}/${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "alder-loom-fpa", ...(init.headers || {}) },
    cache: "no-store",
  });
}

export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") || "cash";
  if (!TYPES.has(type)) return NextResponse.json({ error: "Unknown type" }, { status: 400 });
  if (!process.env.GITHUB_TOKEN) return NextResponse.json({ versions: [], storage: "none", message: "Saving versions needs GITHUB_TOKEN on the server." });
  const list = await gh(`contents/forecasts/${type}?ref=${BRANCH}`);
  if (list.status === 404) return NextResponse.json({ versions: [], storage: "github" });
  if (!list.ok) return NextResponse.json({ versions: [], storage: "github", message: `GitHub error ${list.status}` }, { status: 502 });
  const files = ((await list.json()) as { name: string; path: string }[]).filter((f) => f.name.endsWith(".json")).sort((a, b) => (a.name < b.name ? 1 : -1)).slice(0, 60);
  const versions = (await Promise.all(files.map(async (f) => {
    const r = await gh(`contents/${f.path}?ref=${BRANCH}`, { headers: { Accept: "application/vnd.github.raw+json" } });
    if (!r.ok) return null;
    try { return await r.json(); } catch { return null; }
  }))).filter(Boolean);
  return NextResponse.json({ versions, storage: "github" });
}

type Line = { line: string; section: string; group?: string; amounts: number[] };

export async function POST(req: NextRequest) {
  const user = (await verifySession(req.cookies.get(COOKIE)?.value)) || "unknown";
  if (!process.env.GITHUB_TOKEN) return NextResponse.json({ error: "Saving versions isn't set up on this site yet (GITHUB_TOKEN is missing).", code: "no_storage" }, { status: 503 });
  const raw = await req.text();
  if (raw.length > 400_000) return NextResponse.json({ error: "Version too large" }, { status: 413 });
  let v: Record<string, unknown>;
  try { v = JSON.parse(raw); } catch { return NextResponse.json({ error: "Bad JSON" }, { status: 400 }); }
  const type = String(v.type || "cash");
  const name = String(v.name || "").trim().slice(0, 80);
  const lines = v.lines as Line[];
  const weeks = v.weeks as unknown[];
  if (!TYPES.has(type) || !name || !Array.isArray(lines) || lines.length > 60 || !Array.isArray(weeks) || weeks.length > 24 ||
      !lines.every((l) => typeof l.line === "string" && Array.isArray(l.amounts) && l.amounts.length === weeks.length && l.amounts.every((x) => typeof x === "number" && isFinite(x)))) {
    return NextResponse.json({ error: "Version is not valid" }, { status: 400 });
  }
  const now = new Date();
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "version";
  const id = `${now.toISOString().slice(0, 19).replace(/[-:T]/g, "")}-${slug}`;
  const doc = { ...v, version_id: id, name, type, kind: "saved", author: user, created_at: now.toISOString() };
  const path = `forecasts/${type}/${id}.json`;
  const put = await gh(`contents/${path}`, {
    method: "PUT",
    body: JSON.stringify({ message: `Save ${type} forecast version: ${name} (by ${user})`, content: Buffer.from(JSON.stringify(doc, null, 2)).toString("base64"), branch: BRANCH }),
  });
  if (!put.ok) {
    const j = await put.json().catch(() => ({}));
    return NextResponse.json({ error: `GitHub refused the save: ${j?.message || put.status}`, code: "storage_error" }, { status: 502 });
  }
  return NextResponse.json({ version: doc });
}
