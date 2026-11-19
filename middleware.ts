import { NextRequest, NextResponse } from "next/server";
import { COOKIE, verifySession } from "./lib/session";

// Public by default: anyone with the link can view the dashboards and use the AI analyst.
// Writing (saving forecast versions) always needs a signed-in user.
// Set REQUIRE_LOGIN=true in Vercel to put the whole portal behind the password again.
export async function middleware(req: NextRequest) {
  const user = await verifySession(req.cookies.get(COOKIE)?.value);
  if (user) return NextResponse.next();
  const { pathname, search } = req.nextUrl;
  const isWrite = pathname.startsWith("/api/versions") && req.method !== "GET";
  if (process.env.REQUIRE_LOGIN !== "true" && !isWrite) return NextResponse.next();
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: isWrite ? "Sign in to save forecast versions." : "Not signed in", code: "not_signed_in" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname + search)}` : "";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!login|api/login|api/me|_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
