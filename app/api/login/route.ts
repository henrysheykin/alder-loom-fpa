import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual, createHash } from "node:crypto";
import { COOKIE, SESSION_HOURS, createSession } from "../../../lib/session";

export const runtime = "nodejs";

// SITE_USERS = "anna:pass1,ivan:pass2"  (optional, named logins)
// SITE_PASSWORD = "shared-password"     (one shared password; username optional)
function check(user: string, password: string): string | null {
  const h = (s: string) => createHash("sha256").update(s).digest();
  const same = (a: string, b: string) => timingSafeEqual(h(a), h(b));
  const users = (process.env.SITE_USERS || "").split(",").map((x) => x.trim()).filter(Boolean);
  for (const pair of users) {
    const i = pair.indexOf(":");
    if (i > 0 && same(user.toLowerCase(), pair.slice(0, i).toLowerCase()) && same(password, pair.slice(i + 1))) return pair.slice(0, i);
  }
  const shared = process.env.SITE_PASSWORD;
  if (shared && same(password, shared)) return user || "guest";
  return null;
}

function safeNext(n: string | null): string {
  return n && n.startsWith("/") && !n.startsWith("//") ? n : "/dashboard";
}

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const user = String(form.get("user") || "").trim().slice(0, 64);
  const password = String(form.get("password") || "");
  const next = safeNext(String(form.get("next") || ""));
  const ok = password ? check(user, password) : null;
  if (!ok) {
    await new Promise((r) => setTimeout(r, 600)); // slow down guessing
    return NextResponse.redirect(new URL(`/login?e=1&next=${encodeURIComponent(next)}`, req.url), 303);
  }
  const res = NextResponse.redirect(new URL(next, req.url), 303);
  res.cookies.set(COOKIE, await createSession(ok), {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: SESSION_HOURS * 3600,
  });
  return res;
}
