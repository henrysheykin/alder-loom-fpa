import { NextRequest, NextResponse } from "next/server";
import { COOKIE, verifySession } from "./lib/session";

// Everything except the login page, the login endpoint and Next's own static chunks requires a valid session.
export async function middleware(req: NextRequest) {
  const user = await verifySession(req.cookies.get(COOKIE)?.value);
  if (user) return NextResponse.next();
  const { pathname, search } = req.nextUrl;
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Not signed in", code: "not_signed_in" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname + search)}` : "";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!login|api/login|_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
