# Alder & Loom FP&A Studio

**Demo company · synthetic data.** Alder & Loom Commerce LLC is fictional; every figure is generated for demonstration.

A password-protected finance portal for a mid-size e-commerce business: six dashboards over 11 source systems,
an AI analyst that answers questions and draws charts, and a data pipeline that rebuilds everything from raw
extracts with 33 reconciliation checks. Updates are produced by scheduled Claude tasks and deployed by Vercel.

```
raw extracts (data/alder_loom_data/sources)
      │  pipeline/build_datamart.py  — joins sources, applies accounting rules, 33 checks
      ▼
private/datamart.json  ──git push──►  GitHub  ──auto deploy──►  Vercel
                                                                  ├─ /login        password sign-in (signed cookie, 12h)
                                                                  ├─ /dashboard    6 dashboards + AI analyst
                                                                  ├─ /api/data     data mart, signed-in users only
                                                                  └─ /api/chat     proxy to Claude API (key stays on server)
```

## Dashboards
- **Company overview** — L12M KPIs, revenue vs budget, margins, working capital, categories, channels, SKUs, suppliers
- **P&L vs budget** — month / YTD / full-year outlook, variance table, EBITDA bridge, plan extension methodology
- **Product profitability** — fully allocated P&L by category, SKU, supplier; overhead basis switch
- **Marketing ROAS** — platform-claimed vs store last-click ROAS, POAS, break-even ROAS, CAC, campaign scorecard
- **13-week cash** — weekly forecast with scenario sliders and drill-down to line items
- **Data quality** — reconciliation results and refresh flow

## Deploy on Vercel (one time, ~5 minutes)
1. vercel.com → **Add New… → Project → Import** this GitHub repository. Framework is detected as Next.js; keep defaults.
2. **Settings → Environment Variables** (Production and Preview):
   | Name | Value |
   |---|---|
   | `SITE_PASSWORD` | shared password for the demo |
   | `SITE_USERS` | optional named logins: `anna:pass1,ivan:pass2` |
   | `AUTH_SECRET` | random 32+ characters (`openssl rand -hex 32`) |
   | `ANTHROPIC_API_KEY` | key from console.anthropic.com (AI analyst) |
   | `CLAUDE_MODEL` | optional, default `claude-sonnet-5-5` |
3. **Deploy.** Every push to `main` redeploys automatically.

Without `ANTHROPIC_API_KEY` the dashboards work and the AI analyst shows a "not configured" message.

## Refresh the data
```
npm run refresh        # python3 pipeline/build_datamart.py data/alder_loom_data data/output && copy to private/
git commit -am "data refresh" && git push
```
Publish only when every check in `data/output/reconciliation_report.csv` is PASS.
Scheduled tasks do exactly this — see [SCHEDULED_TASKS.md](SCHEDULED_TASKS.md).

## Local run
```
cp .env.example .env.local   # fill in values
npm install && npm run dev   # http://localhost:3000
```

## Security notes
- All pages and data require a session; the data mart is not in `/public`.
- Session cookie is HttpOnly, Secure, SameSite=Lax, HMAC-signed, 12-hour expiry; failed logins are slowed down.
- The Claude API key exists only as a server environment variable.
- `noindex` headers and robots.txt keep the portal out of search engines.
- For production use, replace the shared password with SSO (e.g. Clerk, Auth0, or Vercel's own protection).
