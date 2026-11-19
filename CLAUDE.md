# Instructions for Claude (scheduled and interactive runs)

This repository is a **demo** FP&A portal for a fictional company, ABC Inc. (raw source files use the placeholder name "Alder & Loom"; the pipeline renames it to ABC Inc. on output). All data is synthetic.
Every output (dashboard, message, deck) must keep the label "Demo company / Synthetic data" and must never be
presented as a real client's results.

## Layout
- `data/alder_loom_data/sources/` — raw extracts from 11 simulated systems (read-only inputs; new extracts replace files with the same columns)
- `pipeline/build_datamart.py` — builds `data/output/datamart.json` and `data/output/reconciliation_report.csv`
- `private/datamart.json` — the data mart the site serves (copied from `data/output` only after checks pass)
- `private/dashboard.html` — the dashboard page (same page as the Claude artifact)
- `forecasts/cash/*.json` — user-saved forecast versions (immutable; never edit or delete, create new ones)
- `config/data_schedule.json` — data collection and job schedule (Central Time); scheduled tasks follow it
- `app/`, `middleware.ts`, `lib/` — Next.js site deployed by Vercel from `main`
- Links are separate per company on one domain: ABC Inc. at `/ecommerce` (alias of `/dashboard`), ABC Agency at `/agency`, ABC SaaS at `/saas`, ABC Restaurants at `/restaurants`, ABC Hotels at `/hotels`. Do not merge them into one page.

## Second company: ABC Agency (marketing agency)
Raw source files use the placeholder name "Signal Harbor Performance"; the pipeline renames it to **ABC Agency** on output. Same demo/synthetic rules apply.
- `data/abc_agency_data/` — raw package (12 simulated systems, 80 tables, docs, metadata, validation control totals). Facts come only from `sources/`.
- `pipeline/agency/build_datamart.py` — standard-library Python, integer cents; writes `data/output/agency/datamart.json` + `reconciliation_report.csv` (61 checks, incl. 47 metrics × 24 months vs `validation/monthly_control_totals.csv`).
- `private/agency/dashboard.html`, `private/agency/datamart.json` — served at `/agency` and `/api/data/agency`.
- Refresh: `npm run refresh:agency` (or `python3 -I pipeline/agency/build_datamart.py data/abc_agency_data data/output/agency`), then the same rule: any FAIL → stop and report; all PASS → copy, commit, push.
- Claude artifact: https://claude.ai/artifact/HpX2eZAkqMic74pd78N8bw — publish `private/agency/dashboard.html` as `index.html` and `private/agency/datamart.json` as `datamart.json`.
- Agency commentary rules: fee revenue (earned on service approval), client media spend (client-paid, not agency money), contract value, invoices and cash are different metrics — never add them. Meta and Google attributed values overlap. Gusto project allocations re-cut payroll already in the GL. Cite client/contract IDs (CLI-…, CON-…, FREE-…).

## Third company: ABC SaaS (B2B subscription software)
Raw source files use the placeholder name "RelayNest Workflow, Inc."; the pipeline renames it to **ABC SaaS** on output. Same demo/synthetic rules apply.
- `data/abc_saas_data/` — raw package (16 simulated systems, 78 tables, docs, metadata, validation control totals). `product_analytics/user_daily_activity` (112 MB) is not stored in the repo; no dashboard metric needs it.
- `pipeline/saas/build_datamart.py` — standard-library Python, integer cents; writes `data/output/saas/datamart.json` + `reconciliation_report.csv` (169 checks, incl. 38 metrics × 24 months vs `validation/monthly_control_totals.csv`, GL/TB/bank/revenue-schedule tie-outs, PK/FK).
- `private/saas/dashboard.html`, `private/saas/datamart.json` — served at `/saas` and `/api/data/saas`.
- Refresh: `npm run refresh:saas`; any FAIL → stop and report; all PASS → copy, commit, push.
- SaaS commentary rules: MRR comes from subscription status/price history, not invoices, cash or revenue. Bookings, billings, recognized revenue, captured cash and bank receipts are different metrics — never add them. Deferred revenue never creates a second future receipt. Equity funding is not revenue. Cite subscription/contract/invoice/requisition IDs.

## Fourth company: ABC Restaurants (restaurant group)
Raw source files use the placeholder name "Cedar & Skillet Hospitality"; the pipeline renames it to **ABC Restaurants** on output. Same demo/synthetic rules apply.
- Three restaurants R01 Raleigh, R02 Durham, R03 Cary plus HQ; 24 months Nov 2024–Oct 2026, cutoff 2026-10-31, FY Nov–Oct.
- `data/abc_restaurants_data/` — docs, metadata, validation control totals and the package verifier are in git. The 578 MB `sources/` folder (15 simulated systems, 92 tables, 736 CSVs, 4.4M rows) is git-ignored: unpack `cedar_skillet_complete.zip` there before a refresh.
- `pipeline/restaurants/build_datamart.py` (stdlib, integer cents) → `data/output/restaurants/datamart_raw.json`; `pipeline/restaurants/site_datamart.py` → `datamart.json` in the site shape with 50 checks (package verifier + 49 metrics × 24 months × COMPANY/R01–R03 vs `validation/monthly_control_totals.csv`). It exits with an error and writes nothing if a check fails.
- `private/restaurants/dashboard.html`, `private/restaurants/datamart.json` — served at `/restaurants` and `/api/data/restaurants`.
- Refresh: `npm run refresh:restaurants`; then the same rule: any FAIL → stop and report; all PASS → commit, push.
- Commentary rules: net revenue = POS sales less discounts, comps, refunds; excludes sales tax and tips. DoorDash/Uber Eats orders are already in POS sales — never add marketplace sales to POS sales. Meta and Google attributed revenue overlaps. Prime cost = COGS + labor. Cite restaurant IDs (R01–R03, HQ).
- Demo assumptions shown on the page: sales tax due 2026-11-20; $500k cash floor.

## Fifth company: ABC Hotels (hotel operator)
Raw source files use the placeholder name "Juniper Quay Hospitality"; the pipeline renames it to **ABC Hotels** on output (properties "ABC Raleigh Station", "ABC Cape Landing (Wilmington)", "ABC Durham Residences"; corporate clients shown as "Corporate client 1–6" by ID; vendor names are not shown). Same demo/synthetic rules apply.
- Properties RAL (60 keys), WIL (52), DUR (44) plus shared CORP; 24 months Nov 2024–Oct 2026, cutoff 2026-10-31, FY Nov–Oct.
- `data/abc_hotels_data/` — docs, metadata, validation control totals and the package verifier are in git. The 138 MB `sources/` folder (14 simulated systems, 95 tables, 235 CSVs, 1.4M rows) is git-ignored: unpack `juniper_quay_hotels_24m_full.zip` and copy `juniper_quay_data/sources` there before a refresh.
- `pipeline/hotels/build_datamart.py` (stdlib, integer cents) → `data/output/hotels/datamart.json` + `reconciliation_report.csv`: 71 checks (package verifier, 47 metrics × 24 months × COMPANY/RAL/WIL/DUR vs `validation/monthly_control_totals.csv`, GL/TB, bank, AR/AP, channels, cash inputs). Exits with an error and writes no datamart if a check fails.
- `private/hotels/dashboard.html`, `private/hotels/datamart.json` — served at `/hotels` and `/api/data/hotels`.
- Refresh: `npm run refresh:hotels`; any FAIL → stop and report; all PASS → commit, push.
- Commentary rules: revenue = consumed nights and services by service date, net of discounts/credits, excluding lodging tax. On-the-books bookings, corporate invoices, gateway payouts and OTA net settlements are not revenue. Agency (Booking-style) commission is owed by the hotel; merchant (Expedia-style) revenue is gross with commission as expense. Sold occupancy uses available nights (physical − OOO − OOS); compute ADR/RevPAR from totals. COMPANY already includes CORP; CORP allocation (60:52:44 keys) is analytical and zero-sum. Cite property IDs (RAL, WIL, DUR, CORP), client IDs (CO-…) and cash-line IDs.
- 13-week cash: opening = operating bank only; known balances from subledgers once; on-the-books stays net of held deposits; new bookings only fill capacity left after OTB (assumption version FC-2026-10-31-BASE). Demo assumption on the page: $2.0M cash floor.

## Data refresh procedure (ABC Inc.)
1. `pip install pandas --break-system-packages -q` if pandas is missing.
2. `python3 pipeline/build_datamart.py data/alder_loom_data data/output`
3. Read `data/output/reconciliation_report.csv`. **If any row is FAIL: stop, do not copy or commit anything, report the failing checks with expected vs actual values.**
4. If all PASS: `cp data/output/datamart.json private/datamart.json`, commit with a message like `data refresh <cutoff date>: 33/33 checks pass`, push to `main` (Vercel redeploys).
5. Republish the Claude artifact https://claude.ai/artifact/CncwySPciA8vEFiRddYbSF with `private/dashboard.html` as the page and `private/datamart.json` published as `datamart.json`.

## Commentary rules
- Use only numbers computed by the pipeline (datamart.json); cite the dataset names.
- Revenue is recognized at dispatch, net of discounts and returns, excluding sales tax. Platform-attributed ad values overlap: never add Meta and Google values as company sales.
- Cash forecast: known items come from documents/contracts; estimated items are driver-based. Say which is which when it matters.
- Keep messages short: the headline, 3-5 numbered drivers, and what changed since the last run.

## Do not
- Edit files in `data/alder_loom_data/` except to drop in new extracts supplied by the user.
- Commit secrets. The site reads `SITE_PASSWORD`, `SITE_USERS`, `AUTH_SECRET`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` from Vercel environment variables.
