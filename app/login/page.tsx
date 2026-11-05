export const dynamic = "force-dynamic";

export default async function Login({ searchParams }: { searchParams: Promise<{ e?: string; out?: string; next?: string }> }) {
  const sp = await searchParams;
  const next = sp.next && sp.next.startsWith("/") && !sp.next.startsWith("//") ? sp.next : "/dashboard";
  return (
    <main className="login-wrap">
      <form className="login" method="post" action="/api/login">
        <div className="brand"><b>ABC Inc.</b><span>FP&amp;A Studio</span></div>
        <span className="demo">Demo company · Synthetic data</span>
        <h1>Sign in to the finance portal</h1>
        {sp.e ? <div className="msg err" role="alert">That password didn&apos;t work. Check it and try again.</div> : null}
        {sp.out ? <div className="msg ok">You&apos;re signed out.</div> : null}
        <label htmlFor="user">Name (optional)</label>
        <input id="user" name="user" autoComplete="username" placeholder="e.g. anna" />
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required autoFocus />
        <input type="hidden" name="next" value={next} />
        <button type="submit">Sign in</button>
        <div className="lock">🔒 Encrypted connection · session expires after 12 hours</div>
        <p className="fine">ABC Inc. is a fictional company. All figures are synthetic and generated for demonstration.</p>
      </form>
    </main>
  );
}
