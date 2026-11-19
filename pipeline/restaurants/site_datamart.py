# ABC Restaurants: turn the pipeline datamart into the site data mart
# ({meta, datasets:{name:{rows(objects), columns, grain, description}}}), same shape as /agency.
# Stdlib only. Usage: python3 -I site_datamart.py <datamart.json> <package_root> <out.json>
import csv, json, os, sys, statistics
from collections import defaultdict
from datetime import datetime, timezone

SRC, ROOT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
raw = json.load(open(SRC, encoding="utf-8"))
RD, RM = raw["datasets"], raw["meta"]
REST = ["R01", "R02", "R03"]
ENTS = ["COMPANY", "R01", "R02", "R03", "HQ"]
NAMES = {"COMPANY": "ABC Restaurants (company)", "R01": "Raleigh Warehouse District", "R02": "Durham Central",
         "R03": "Cary Commons", "HQ": "Shared management (HQ)"}
SHORT = {"COMPANY": "Company", "R01": "Raleigh", "R02": "Durham", "R03": "Cary", "HQ": "HQ"}
r2 = lambda v: round(float(v), 2)

def objs(name):
    d = RD[name]; c = d["columns"]
    return [dict(zip(c, r)) for r in d["rows"]]

OUTDS = {}
def ds(name, rows, grain, desc):
    cols = list(rows[0].keys()) if rows else []
    OUTDS[name] = {"rows": rows, "columns": cols, "grain": grain, "description": desc}

fy = lambda p: "FY2025" if p < "2025-11" else "FY2026"

# ---------------- P&L (expenses positive, revenue net of contra-revenue positive)
GROUP = {"Revenue": "Net revenue", "COGS": "Cost of goods sold", "Labor": "Labor", "Occupancy": "Occupancy",
         "Operating": "Operating expenses", "Fees": "Card and marketplace fees", "Marketing": "Marketing",
         "Depreciation": "Depreciation", "Interest": "Interest"}
pnl = []
for r in objs("pnl_monthly"):
    e = r["entity"]
    pnl.append({"period": r["service_month"], "fy": fy(r["service_month"]), "entity": e, "account_id": r["account_id"],
                "line": r["account_name"], "group": r["statement_group"], "account_type": r["account_type"],
                "actual": r2(r["actual_usd"]), "budget": r2(r["budget_usd"])})
company_rows = defaultdict(lambda: [0.0, 0.0]); meta_rows = {}
for r in pnl:
    if r["entity"] == "COMPANY":
        break
else:
    for r in list(pnl):
        k = (r["period"], r["account_id"]); company_rows[k][0] += r["actual"]; company_rows[k][1] += r["budget"]; meta_rows[r["account_id"]] = r
    for (p, a), (act, bud) in sorted(company_rows.items()):
        m = meta_rows[a]
        pnl.append({"period": p, "fy": fy(p), "entity": "COMPANY", "account_id": a, "line": m["line"], "group": m["group"],
                    "account_type": m["account_type"], "actual": r2(act), "budget": r2(bud)})
ds("pnl_monthly", pnl, "period × entity × GL account",
   "QuickBooks GL activity by month, entity (R01–R03, HQ, COMPANY = sum) and account, actual vs the original approved budget. Revenue is net of discounts, comps and refunds; expenses are positive.")

PERIODS = sorted({r["period"] for r in pnl})

# ---------------- monthly KPIs per entity
K = {(p, e): defaultdict(float) for p in PERIODS for e in ENTS}
for r in pnl:
    k = K[(r["period"], r["entity"])]
    if r["group"] == "Revenue":
        k["net_revenue"] += r["actual"]; k["budget_net_revenue"] += r["budget"]
    else:
        g = r["group"].lower()
        k[g] += r["actual"]; k["budget_" + g] += r["budget"]
        k["expense"] += r["actual"]; k["budget_expense"] += r["budget"]
def add(ent, p, key, v):
    K[(p, ent)][key] += v
    if ent in REST: K[(p, "COMPANY")][key] += v
for r in objs("sales_monthly"):
    p, e = r["service_month"], r["restaurant_id"]
    add(e, p, "pos_net_sales", r["net_sales_usd"]); add(e, p, "checks", r["closed_checks"]); add(e, p, "guests", r["guests"])
    if r["channel"] in ("DOORDASH", "UBEREATS"): add(e, p, "delivery_sales", r["net_sales_usd"])
    if r["channel"] == "DINE_IN": add(e, p, "dine_in_sales", r["net_sales_usd"])
for r in objs("labor_monthly"):
    p, e = r["service_month"], r["restaurant_id"]
    for c in ("paid_hours", "overtime_hours", "scheduled_hours"): add(e, p, c, r[c])
for r in objs("waste_monthly"): add(r["restaurant_id"], r["service_month"], "waste", r["waste_cost_usd"])
for r in objs("theoretical_cost_monthly"):
    if r["usage_type"] in ("MENU", "MODIFIER"): add(r["restaurant_id"], r["service_month"], "theoretical_menu_cost", r["theoretical_cost_usd"])
for r in objs("marketplace_monthly"):
    add(r["restaurant_id"], r["service_month"], "marketplace_net_sales", r["merchant_net_sales_usd"])
    add(r["restaurant_id"], r["service_month"], "marketplace_commission", r["commission_usd"])
    add(r["restaurant_id"], r["service_month"], "marketplace_promotion", r["promotion_fee_usd"])
for r in objs("ads_monthly"): add(r["restaurant_id"], r["service_month"], "ad_spend", r["spend_usd"])
for r in objs("inventory_month_end"): add(r["restaurant_id"], r["service_month"], "inventory", r["inventory_value_usd"])
bank = {r["service_month"]: r for r in objs("bank_monthly")}
bal = defaultdict(float)
for r in objs("balances_monthly"): bal[(r["service_month"], r["entity"], r["account_id"])] += r["balance_usd"]
def balc(p, acc):  # company total of an account
    return sum(bal[(p, e, acc)] for e in ("R01", "R02", "R03", "HQ"))
kpi = []
for p in PERIODS:
    for e in ENTS:
        k = K[(p, e)]; nr = k["net_revenue"]
        row = {"period": p, "fy": fy(p), "entity": e, "name": SHORT[e]}
        for c in ("net_revenue", "budget_net_revenue", "cogs", "budget_cogs", "labor", "budget_labor", "occupancy", "budget_occupancy",
                  "operating", "budget_operating", "fees", "budget_fees", "marketing", "budget_marketing", "depreciation", "interest",
                  "expense", "budget_expense"):
            row[c] = r2(k[c])
        row["prime_cost"] = r2(k["cogs"] + k["labor"])
        row["ebitda"] = r2(nr - (k["expense"] - k["depreciation"] - k["interest"]))
        row["budget_ebitda"] = r2(k["budget_net_revenue"] - (k["budget_expense"] - k["budget_depreciation"] - k["budget_interest"]))
        row["pretax"] = r2(nr - k["expense"]); row["budget_pretax"] = r2(k["budget_net_revenue"] - k["budget_expense"])
        for c in ("pos_net_sales", "delivery_sales", "dine_in_sales", "waste", "theoretical_menu_cost", "marketplace_net_sales",
                  "marketplace_commission", "marketplace_promotion", "ad_spend", "inventory", "paid_hours", "overtime_hours", "scheduled_hours"):
            row[c] = r2(k[c])
        row["checks"] = int(k["checks"]); row["guests"] = int(k["guests"])
        row["avg_check"] = r2(k["pos_net_sales"] / k["checks"]) if k["checks"] else None
        if e == "COMPANY" and p in bank:
            b = bank[p]; row["bank_cash"] = r2(b["closing_usd"]); row["bank_inflows"] = r2(b["inflows_usd"]); row["bank_outflows"] = r2(b["outflows_usd"])
            row["ap"] = r2(balc(p, "2000")); row["sales_tax_payable"] = r2(balc(p, "2030")); row["debt"] = r2(balc(p, "2040"))
        kpi.append(row)
ds("kpi_monthly", kpi, "period × entity",
   "Monthly KPIs per restaurant, HQ and COMPANY: P&L by statement group (actual and budget), prime cost, EBITDA, pretax income, POS sales, checks, guests, labor hours, waste, theoretical menu cost, marketplace and ads; bank cash, AP, sales tax payable and debt for COMPANY.")

# ---------------- operational datasets (objects)
def conv(name, rename=None, keep=None):
    out = []
    for r in objs(name):
        o = {}
        for c, v in r.items():
            if keep and c not in keep: continue
            o[(rename or {}).get(c, c)] = r2(v) if isinstance(v, float) else v
        out.append(o)
    return out
ren = {"service_month": "period"}
ds("sales_channel_monthly", conv("sales_monthly", ren), "period × restaurant × channel",
   "Toast POS closed checks by channel (DINE_IN, TAKEAWAY, DOORDASH, UBEREATS): checks, guests, gross sales, discounts, comps, net sales and sales tax. Marketplace orders are already inside POS sales.")
menu = {}
for r in objs("menu_monthly"):
    k = (r["service_month"], r["restaurant_id"], r["menu_item_id"])
    o = menu.setdefault(k, {"period": k[0], "restaurant_id": k[1], "menu_item_id": k[2], "item_name": r["item_name"], "category": r["category"], "quantity": 0, "net_sales_usd": 0.0})
    o["quantity"] += r["quantity"]; o["net_sales_usd"] = r2(o["net_sales_usd"] + r["net_sales_usd"])
ds("menu_monthly", list(menu.values()), "period × restaurant × menu item", "Served POS lines on closed checks: quantity and net sales by menu item, all channels.")
ds("labor_monthly", conv("labor_monthly", ren), "period × restaurant",
   "Timekeeping: paid, overtime and scheduled hours, hourly wage expense, active employees and shifts.")
ds("waste_monthly", conv("waste_monthly", ren), "period × restaurant × reason", "Measured ingredient loss at cost by reason.")
ds("theoretical_cost_monthly", conv("theoretical_cost_monthly", ren), "period × restaurant × usage × class",
   "Recipe-driven theoretical ingredient cost (menu, modifiers, packaging, staff meals).")
ds("count_variance_monthly", conv("count_variance_monthly", ren), "period × restaurant", "Physical count variance at cost (positive = loss).")
ds("marketplace_monthly", conv("marketplace_monthly", ren), "period × restaurant × platform",
   "DoorDash and Uber Eats: orders, merchant net sales, commission, promotion fees, service adjustments, net receivable.")
ds("ads_monthly", conv("ads_monthly", ren), "period × restaurant × channel",
   "Meta and Google: spend, impressions, clicks, conversions, platform-attributed revenue (overlaps; not company sales).")
ds("bank_monthly", conv("bank_monthly", ren), "period", "Operating bank: opening, inflows, outflows, closing, transaction count.")
ds("bank_type_monthly", conv("bank_type_monthly", ren), "period × transaction type", "Bank inflows and outflows by transaction type.")
cash = []
for i, r in enumerate(objs("cash_schedule_13w")):
    o = {"id": "CF-%03d" % (i + 1)}
    for c, v in r.items(): o[c] = r2(v) if isinstance(v, float) else v
    cash.append(o)
ds("cash_schedule_13w", cash, "commitment line",
   "13-week cash schedule from 2026-11-01 (Sun–Sat weeks): committed items deduplicated by overlap key plus run-rate payroll and sales tax. week_index 0–12.")

# ---------------- reconciliations
rec = objs("reconciliation_to_control")
bym = defaultdict(lambda: [0, 0, 0])
for r in rec:
    a = bym[r["metric"]]; d = abs(int(r["difference_cents"])); a[0] += 1; a[1] += d != 0; a[2] = max(a[2], d)
V = RM["verification"]
checks = [{"area": "Source package", "check": "Independent verifier over all source tables",
           "detail": f'{V["check_groups"]} check groups, {V["evaluated_conditions"]:,} conditions over {V["source_rows"]:,} rows in {V["source_files"]} files; {V["failures"]} failures',
           "status": "PASS" if V["failures"] == 0 else "FAIL"}]
AREA = lambda m: ("Sales" if any(x in m for x in ("sales", "discount", "comp", "refund", "check", "guest")) else
                  "Labor" if any(x in m for x in ("wage", "labor", "benefit", "payroll_tax", "minutes", "tips")) else
                  "Cost of goods" if any(x in m for x in ("cost", "waste", "packaging", "meals", "inventory")) else
                  "Balance sheet" if any(x in m for x in ("balance", "payable", "clearing", "cash", "principal", "liability")) else "P&L")
for m, (n, bad, mx) in sorted(bym.items()):
    checks.append({"area": AREA(m), "check": f"{m} matches control totals", "detail": f"{n} month × entity comparisons; {bad} differ; largest difference {mx} cents",
                   "status": "PASS" if bad == 0 else "FAIL"})
ds("reconciliations", checks, "check", "Every check run on build: source verifier plus each metric vs validation/monthly_control_totals.csv (24 months × COMPANY, R01, R02, R03).")
# ---------------- data sources
srcs = []
with open(os.path.join(ROOT, "metadata", "source_catalog.csv"), encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        srcs.append({"source": r["source_system"], "name": r["modeled_system"], "tables": int(r["logical_table_count"]),
                     "files": int(r["source_csv_file_count"]), "records": int(r["row_count"]), "usage": r["accounting_usage"], "status": "Synthetic extract"})
ds("data_sources", srcs, "source system", "Simulated source systems with table, file and record counts (from metadata/source_catalog.csv).")

# ---------------- stories (computed, not typed)
st = []
mk = objs("marketplace_monthly")
dd = defaultdict(lambda: [0.0, 0.0])
for r in mk:
    if r["platform"] == "DOORDASH": dd[r["service_month"]][0] += r["commission_usd"]; dd[r["service_month"]][1] += r["merchant_net_sales_usd"]
ps = sorted(dd); rate = {p: dd[p][0] / dd[p][1] for p in ps}
for a, b in zip(ps, ps[1:]):
    if rate[b] - rate[a] > 0.005:
        st.append({"id": "DOORDASH-RATE", "story": f"DoorDash commission rate stepped from {rate[a]*100:.1f}% to {rate[b]*100:.1f}% of platform net sales in {b}."}); break
kp = {(r["period"], r["entity"]): r for r in kpi}
sh = lambda p, e: kp[(p, e)]["delivery_sales"] / kp[(p, e)]["pos_net_sales"]
st.append({"id": "R03-DELIVERY", "story": f"Cary (R03) delivery share of POS sales moved from {sh(PERIODS[0],'R03')*100:.1f}% ({PERIODS[0]}) to {sh(PERIODS[-1],'R03')*100:.1f}% ({PERIODS[-1]}); company {sh(PERIODS[-1],'COMPANY')*100:.1f}%."})
w = max((r for r in kpi if r["entity"] in REST), key=lambda r: r["waste"])
medw = statistics.median(r["waste"] for r in kpi if r["entity"] == w["entity"] and r["period"] != w["period"])
st.append({"id": f'{w["entity"]}-WASTE', "story": f'{SHORT[w["entity"]]} ({w["entity"]}) waste was ${w["waste"]:,.0f} in {w["period"]}, vs a ${medw:,.0f} monthly median for that restaurant.'})
o = max((r for r in kpi if r["entity"] in REST), key=lambda r: r["overtime_hours"])
st.append({"id": f'{o["entity"]}-OVERTIME', "story": f'Peak overtime: {SHORT[o["entity"]]} ({o["entity"]}) in {o["period"]} with {o["overtime_hours"]:,.0f} overtime hours of {o["paid_hours"]:,.0f} paid.'})
c26 = [r for r in kpi if r["entity"] == "COMPANY" and r["fy"] == "FY2026"]
nr, bn, pt, bp = (sum(r[k] for r in c26) for k in ("net_revenue", "budget_net_revenue", "pretax", "budget_pretax"))
st.append({"id": "FY2026-BUDGET", "story": f"FY2026 net revenue ${nr:,.0f} is {(nr/bn-1)*100:+.1f}% vs budget, yet pretax income ${pt:,.0f} is ${bp-pt:,.0f} below budget: costs grew faster than sales."})
ds("stories", st, "finding", "Findings computed from the data on each build.")

# ---------------- meta
D = RM["drivers"]
meta = {"company": "ABC Restaurants", "label": "Demo company / Synthetic data",
        "business": "Three full-service restaurants with dine-in, takeaway and DoorDash / Uber Eats delivery, plus a shared management office",
        "hq": "Raleigh, NC (fictional)", "currency": "USD", "cutoff": RM["snapshot_date"], "first_period": PERIODS[0], "last_period": PERIODS[-1],
        "fiscal_year_note": "Fiscal year runs November–October; FY2026 = Nov 2025–Oct 2026", "fiscal_years": ["FY2025", "FY2026"],
        "restaurants": {e: NAMES[e] for e in REST + ["HQ"]},
        "opening_cash": D["opening_bank_usd"], "cash_drivers": D,
        "cash_week_convention": "Consecutive 7-day intervals Sunday–Saturday starting 2026-11-01 (13 full weeks, ends 2027-01-30).",
        "cash_rules": ["Known commitments (approved payroll, open AP, unreceived POs, pending card/cash/marketplace settlements, accrued sales tax, debt service, recurring contracts) apply in full, deduplicated by overlap key.",
                       "Customer receipts and vendor purchases run at the trailing 8-week average from the chosen start week; a week takes the larger of known items and run rate, so nothing is counted twice.",
                       "Future payroll = average of the last four funding cycles, funded one day before pay date; future sales tax = trailing monthly average.",
                       "Owner distributions, new capital spending and income tax (pass-through LLC) are excluded."],
        "sales_tax_due": "2026-11-20", "sales_tax_due_note": "Due date chosen for the demo; the accrued October liability is OPEN in the tax ledger.",
        "cash_floor": 500000, "cash_floor_note": "Minimum cash floor is a demo assumption, not in the source data.",
        "recon_pass": sum(c["status"] == "PASS" for c in checks), "recon_total": len(checks),
        "source_rows": V["source_rows"], "source_files": V["source_files"], "source_tables": V["source_tables"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
if meta["recon_pass"] != meta["recon_total"]:
    for c in checks:
        if c["status"] != "PASS": print("FAIL", c["check"], "-", c["detail"])
    sys.exit("Checks failed: nothing written. Do not copy or commit.")
json.dump({"meta": meta, "datasets": OUTDS}, open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"{OUT}: {os.path.getsize(OUT)/1e6:.2f} MB, {len(OUTDS)} datasets, checks {meta['recon_pass']}/{meta['recon_total']}")
for s in st: print(" -", s["story"])
