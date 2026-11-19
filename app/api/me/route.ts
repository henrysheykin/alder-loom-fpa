import { NextRequest, NextResponse } from "next/server";
import { COOKIE, verifySession } from "../../../lib/session";

export const dynamic = "force-dynamic";

// Who is signed in (null when browsing the public dashboard).
export async function GET(req: NextRequest) {
  const user = await verifySession(req.cookies.get(COOKIE)?.value);
  return NextResponse.json({ user }, { headers: { "cache-control": "private, no-store" } });
}
