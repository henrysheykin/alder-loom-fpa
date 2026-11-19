# ABC Inc. FP&A Studio

**Demo company · synthetic data.** ABC Inc. is fictional (the raw source files use the placeholder name "Alder & Loom"; the pipeline renames it on output); every figure is generated for demonstration.

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

## Links
One site, a separate link per demo company (nothing is shared between them except the AI chat proxy):
- ABC Inc. (e-commerce): `/ecommerce` (old link `/dashboard` still works), data `/api/data`
- ABC Agency (marketing agency): `/agency`, data `/api/data/agency`
- ABC SaaS (B2B subscription software): `/saas`, data `/api/data/saas`
- ABC Restaurants (restaurant group): `/restaurants`, data `/api/data/restaurants`

## Second company: ABC Agency — `/agency`
A fictional performance-marketing agency (Meta & Google Ads management, creative, analytics), 24 months of synthetic data
from 12 simulated systems (HubSpot, contracts, timekeeping, Gusto, freelancers, client-owned Meta/Google ad accounts,
delivery approvals, QuickBooks, bank, planning, debt). Pipeline: `pipeline/agency/build_datamart.py` (61 checks).
Tabs: Company overview · P&L vs budget · Client profitability · Team & utilization · Scope & delivery · Receivables ·
Retention & pipeline · 13-week cash (scenarios + drill-down) · Data sources · Data quality, plus the AI analyst.
Refresh with `npm run refresh:agency`.

## Third company: ABC SaaS — `/saas`
A fictional B2B SaaS (seat-based Starter/Team/Scale plans, monthly and annual billing), 24 months of synthetic data from 16 simulated
systems (Stripe Billing & Payments, contracts, revenue subledger, product analytics, HubSpot, AWS, Gusto, QuickBooks, bank, Meta/Google Ads,
first-party tracking, procurement, planning, equity register). Pipeline: `pipeline/saas/build_datamart.py` (169 checks).
Tabs: Business overview · MRR & retention (bridge, cohorts, price versions) · Revenue · billing · cash · Budget vs actual · Department spend ·
Rolling forecast (driver sliders) · 13-week cash (scenarios + drill-down) · Data sources · Data quality, plus the AI analyst.
Refresh with `npm run refresh:saas`.

## Fourth company: ABC Restaurants — `/restaurants`
A fictional group of three full-service restaurants (Raleigh, Durham, Cary) with dine-in, takeaway and DoorDash / Uber Eats
delivery, plus a shared management office. 24 months of synthetic data from 15 simulated systems (POS, card processor,
delivery platforms, payroll, timekeeping, kitchen inventory, procurement, QuickBooks, bank, treasury, ads, planning).
Pipeline: `pipeline/restaurants/` (50 checks). Tabs: Company overview · Month review · P&L vs budget · Restaurants ·
Menu & channels · Labor · Food cost & waste · Delivery & ads · 13-week cash (scenarios + drill-down) · Data sources ·
Data quality, plus the AI analyst. Refresh with `npm run refresh:restaurants`.

## Dashboards (ABC Inc., `/dashboard`)
- **Company overview** — L12M KPIs, revenue vs budget, margins, working capital, categories, channels, SKUs, suppliers
- **P&L vs budget** — month / YTD / full-year outlook, variance table, EBITDA bridge, plan extension methodology
- **Product profitability** — fully allocated P&L by category, SKU, supplier; overhead basis switch
- **Marketing ROAS** — platform-claimed vs store last-click ROAS, POAS, break-even ROAS, CAC, campaign scorecard
- **13-week cash** — weekly forecast with scenario sliders and drill-down; versions (edit cells with comments, add lines, save named versions to `forecasts/cash/`), forecast vs actual and version vs version
- **Data quality** — reconciliation results and refresh flow

## Deploy on Vercel (one time, ~5 minutes)
1. vercel.com → **Add New… → Project → Import** this GitHub repository. Framework is detected as Next.js; keep defaults.
2. **Settings → Environment Variables** (Production and Preview):
   | Name | Value |
   |---|---|
   | `REQUIRE_LOGIN` | optional; `true` puts the whole portal behind the password (default: public view, sign-in needed only to save versions) |
   | `SITE_PASSWORD` | shared password for sign-in |
   | `SITE_USERS` | optional named logins: `anna:pass1,ivan:pass2` |
   | `AUTH_SECRET` | random 32+ characters (`openssl rand -hex 32`) |
   | `ANTHROPIC_API_KEY` | key from console.anthropic.com (AI analyst) |
   | `CLAUDE_MODEL` | optional, default `claude-sonnet-5-5` |
   | `GITHUB_TOKEN` | fine-grained token, this repository only, *Contents: Read and write* — lets the site save forecast versions |
   | `GITHUB_REPO` | optional, default `henrysheykin/alder-loom-fpa` |
3. **Deploy.** Every push to `main` redeploys automatically.

Without `ANTHROPIC_API_KEY` the dashboards work and the AI analyst shows a "not configured" message.

## Forecast versions
- System versions are rebuilt by the pipeline: the live forecast plus weekly forecasts reconstructed as of earlier Saturdays (backtests), so forecast vs actual works on history.
- Saved versions are JSON files in `forecasts/cash/` (one commit per save, immutable). `vercel.json` skips a redeploy when only `forecasts/` changed.
- Each saved version keeps the full weekly table plus the list of adjustments (line, week, from, to, comment, author, time).

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
