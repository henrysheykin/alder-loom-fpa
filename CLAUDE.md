# Instructions for Claude (scheduled and interactive runs)

This repository is a **demo** FP&A portal for a fictional company, Alder & Loom Commerce LLC. All data is synthetic.
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

## Data refresh procedure
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
