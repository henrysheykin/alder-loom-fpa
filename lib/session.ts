// Signed session cookie: "<expiryEpochSeconds>.<hex HMAC-SHA256(AUTH_SECRET, 'v1.<expiry>.<user>')>.<user>"
// Uses Web Crypto so it runs in both the edge middleware and Node route handlers.
export const COOKIE = "al_session";
export const SESSION_HOURS = 12;

const enc = new TextEncoder();

async function hmac(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function secret(): string {
  const s = process.env.AUTH_SECRET;
  if (!s || s.length < 16) throw new Error("AUTH_SECRET is missing or shorter than 16 characters");
  return s;
}

export async function createSession(user: string): Promise<string> {
  const exp = Math.floor(Date.now() / 1000) + SESSION_HOURS * 3600;
  const u = user.replace(/[^a-zA-Z0-9_.@-]/g, "").slice(0, 64) || "guest";
  return `${exp}.${await hmac(secret(), `v1.${exp}.${u}`)}.${u}`;
}

export async function verifySession(value: string | undefined): Promise<string | null> {
  if (!value) return null;
  const [expS, sig, user] = value.split(".");
  const exp = Number(expS);
  if (!exp || !sig || !user || exp < Date.now() / 1000) return null;
  let expected: string;
  try { expected = await hmac(secret(), `v1.${exp}.${user}`); } catch { return null; }
  if (expected.length !== sig.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= expected.charCodeAt(i) ^ sig.charCodeAt(i);
  return diff === 0 ? user : null;
}
