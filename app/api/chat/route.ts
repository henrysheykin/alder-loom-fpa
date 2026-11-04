import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 60;

// Thin, authenticated proxy to the Claude Messages API. The page runs the tool loop:
// it sends the conversation and tool definitions, executes tool calls on its own data,
// and posts the results back. The API key never leaves the server.
const MODEL = process.env.CLAUDE_MODEL || "claude-sonnet-5-5";
const MAX_BODY = 600_000;

export async function POST(req: NextRequest) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return NextResponse.json({ error: "The AI analyst is not configured: ANTHROPIC_API_KEY is missing on the server.", code: "no_api_key" }, { status: 503 });
  const raw = await req.text();
  if (raw.length > MAX_BODY) return NextResponse.json({ error: "Request too large. Ask a narrower question.", code: "prompt_too_large" }, { status: 413 });
  let body: { system?: string; messages?: unknown[]; tools?: unknown[] };
  try { body = JSON.parse(raw); } catch { return NextResponse.json({ error: "Bad request", code: "invalid_request" }, { status: 400 }); }
  if (!Array.isArray(body.messages) || body.messages.length === 0 || body.messages.length > 60) {
    return NextResponse.json({ error: "Bad request", code: "invalid_request" }, { status: 400 });
  }
  const payload: Record<string, unknown> = {
    model: MODEL,
    max_tokens: 4096,
    messages: body.messages,
    ...(body.system ? { system: String(body.system).slice(0, 300_000) } : {}),
    ...(Array.isArray(body.tools) && body.tools.length ? { tools: body.tools.slice(0, 16) } : {}),
  };
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const code = r.status === 429 ? "rate_limited" : r.status === 401 ? "no_api_key" : "error";
    return NextResponse.json({ error: j?.error?.message || `Claude API error ${r.status}`, code }, { status: r.status === 429 ? 429 : 502 });
  }
  return NextResponse.json({ content: j.content, stop_reason: j.stop_reason, usage: j.usage, model: j.model });
}
