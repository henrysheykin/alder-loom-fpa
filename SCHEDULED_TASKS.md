# Scheduled tasks (run by Claude)

Each task is a stored instruction that Claude runs on a schedule in a fresh session. It clones this repository,
works only on its files, and never publishes numbers that failed reconciliation.

| # | Task | When | Does | Publishes |
|---|---|---|---|---|
| 1 | Data refresh & reconciliation | Daily 06:40 | New extracts → `npm run refresh` → 33 checks | If all PASS: commit `private/datamart.json` → Vercel redeploys; Claude artifact republished. If any FAIL: no publish, alert with the failing checks |
| 2 | 13-week cash forecast | Monday 07:10 | Rebuild forecast, compare with last week's version, check $250k floor | Summary: low point, weeks below floor, biggest changes; forecast version saved in `forecasts/` |
| 3 | Weekly KPI digest | Monday 07:40 | Revenue, margin, MER/ROAS, returns, stock cover for the week vs prior | Short digest to phone/email |
| 4 | Alerts | Daily 12:10 | SKUs under 14 days of cover, refund spike, ad spend above plan, campaigns below break-even ROAS, unmatched bank items | Message only when something is found |
| 5 | Month-end close pack | Business day 4 | P&L vs budget with variance commentary, rolling forecast re-version, product and marketing highlights | Updated dashboards + draft management deck |
| 6 | Owner distribution check | Quarterly, before the 25th | Policy: min($200k, cash above $250k), stress-tested on the cash forecast | Recommendation with the calculation |

## How a run works
1. The schedule fires; Claude opens a new session with the task's instruction.
2. Pulls the latest extracts (repository `data/`, a connected Google Drive folder, or the user's computer).
3. Runs the pipeline and the reconciliation checks. Any FAIL stops the run and reports what broke.
4. Commits the refreshed data mart to GitHub (Vercel deploys) and republishes the Claude artifact.
5. Writes commentary from the computed numbers only, with sources, and sends the notification.
6. Each run is visible as its own session for audit.
