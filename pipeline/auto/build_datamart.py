# ABC Auto (raw placeholder "Cedar Bend Auto Care LLC"): three general-repair auto shops + HQ.
# Builds the site data mart {meta, datasets:{name:{rows,columns,grain,description}}} from the raw package.
# Standard library only; money in integer cents. Any FAIL check -> exit 1, nothing written.
# Usage: python3 -I pipeline/auto/build_datamart.py data/abc_auto_data data/output/auto
import csv, glob, json, os, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ROOT, OUTDIR = sys.argv[1], sys.argv[2]
SRC = os.path.join(ROOT, "sources")
CUTOFF = "2026-10-31"
LOCS = ["LOC-01", "LOC-02", "LOC-03"]
ENTS = ["COMPANY"] + LOCS + ["HQ"]
NAMES = {"COMPANY": "ABC Auto (company)", "LOC-01": "North Creek", "LOC-02": "River West", "LOC-03": "Oak Junction", "HQ": "Shared office (HQ)"}


def c(v):  # USD string -> cents
    if v in ("", None): return 0
    s = v.strip(); neg = s.startswith("-"); s = s.lstrip("-")
    w, _, f = s.partition("."); f = (f + "00")[:2]
    n = int(w or 0) * 100 + int(f); return -n if neg else n

u = lambda n: round(n / 100, 2)
fy = lambda p: "FY2025" if p < "2025-11" else "FY2026"


def read(rel):
    p = os.path.join(SRC, rel)
    files = sorted(glob.glob(os.path.join(p, "*.csv"))) if os.path.isdir(p) else [p + ".csv" if not p.endswith(".csv") else p]
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as h:
            yield from csv.DictReader(h)

CHECKS = []
def check(area, name, ok, detail):
    CHECKS.append({"area": area, "check": name, "detail": detail, "status": "PASS" if ok else "FAIL"})

OUT = {}
def ds(name, rows, grain, desc):
    OUT[name] = {"rows": rows, "columns": list(rows[0].keys()) if rows else [], "grain": grain, "description": desc}

# ------------------------------------------------------------------ chart of accounts, TB, GL
COA = {r["account_code"]: r for r in read("accounting/chart_of_accounts")}
PL_TYPES = {"revenue", "contra_revenue", "expense", "contra_expense"}
GROUP = {"labor_sales": "Revenue", "parts_sales": "Revenue", "fee_sales": "Revenue", "sublet_sales": "Revenue", "discounts": "Revenue",
         "direct_labor": "Technician labor", "parts_cogs": "Parts COGS", "warranty": "Warranty (net)", "inventory_loss": "Inventory loss",
         "sublet_cogs": "Sublet COGS", "location_payroll": "Shop staff payroll", "shared_payroll": "HQ payroll", "rent": "Rent",
         "utilities": "Occupancy & overhead", "insurance": "Occupancy & overhead", "software": "Occupancy & overhead",
         "maintenance": "Equipment maintenance", "other_opex": "Occupancy & overhead", "marketing": "Marketing",
         "merchant_fees": "Merchant fees", "depreciation": "Depreciation", "interest": "Interest"}
DIRECT = {"5000", "5010", "5015", "5100", "5110", "5120", "5130", "5200"}

tb = defaultdict(lambda: [0, 0, 0])  # (month, loc, acct) -> debits, credits, closing
for r in read("accounting/monthly_trial_balance"):
    k = (r["month"], r["location_id"], r["account_code"])
    tb[k] = [c(r["period_debits_usd"]), c(r["period_credits_usd"]), c(r["closing_signed_balance_usd"])]
PERIODS = sorted({k[0] for k in tb})
check("Coverage", "24 months Nov 2024–Oct 2026", PERIODS[0] == "2024-11" and PERIODS[-1] == "2026-10" and len(PERIODS) == 24, f"{PERIODS[0]}…{PERIODS[-1]} ({len(PERIODS)})")

gl = defaultdict(lambda: [0, 0]); gl_ids = set(); gl_rows = 0
for r in read("accounting/general_ledger"):
    k = (r["journal_date"][:7], r["location_id"], r["account_code"])
    gl[k][0] += c(r["debit_usd"]); gl[k][1] += c(r["credit_usd"]); gl_rows += 1; gl_ids.add(r["journal_line_id"])
diff = sum(1 for k in set(tb) | set(gl) if (tb[k][0], tb[k][1]) != tuple(gl[k]))
check("Ledger", "GL lines = TB period debits/credits (month × location × account)", diff == 0, f"{len(tb)} TB cells, {gl_rows:,} GL lines, {diff} mismatches")
check("Ledger", "GL journal line IDs unique", len(gl_ids) == gl_rows, f"{gl_rows:,} lines")
tot_d = sum(v[0] for v in gl.values()); tot_c = sum(v[1] for v in gl.values())
check("Ledger", "GL debits = credits", tot_d == tot_c, f"{u(tot_d):,.2f} each")

def econ(acct, d, cr):  # positive = revenue for revenue lines, cost for expense lines
    t = COA[acct]["account_type"]
    return cr - d if t == "revenue" else d - cr  # contra revenue/expense/contra expense: debit - credit

bud = defaultdict(int)
for r in read("planning/monthly_budget"):
    if r["budget_version_id"] != "BUDGET-ORIGINAL-20241018": continue
    a = r["account_code"]; v = c(r["budget_amount_usd"])
    if COA[a]["account_type"] == "contra_expense": v = -v
    bud[(r["month"], r["location_id"], a)] += v

pnl_rows = []; agg = defaultdict(lambda: [0, 0])
for p in PERIODS:
    for loc in LOCS + ["HQ"]:
        for a, m in COA.items():
            if m["account_type"] not in PL_TYPES: continue
            d, cr, _ = tb[(p, loc, a)]; act = econ(a, d, cr); b = bud[(p, loc, a)]
            if act == 0 and b == 0: continue
            for e in (loc, "COMPANY"):
                agg[(p, e, a)][0] += act; agg[(p, e, a)][1] += b
for (p, e, a), (act, b) in sorted(agg.items()):
    m = COA[a]
    pnl_rows.append({"period": p, "fy": fy(p), "entity": e, "account_id": a, "line": m["account_name"], "group": GROUP[m["reporting_group"]],
                     "account_type": m["account_type"], "actual": u(act), "budget": u(b)})
ds("pnl_monthly", pnl_rows, "period × entity × GL account",
   "Monthly P&L from trial-balance period debits/credits (not closing balances) by location (LOC-01..03, HQ; COMPANY = sum, HQ once) and account, vs the original budget approved 2024-10-18. Revenue lines positive; contra-revenue 4090 (customer concessions) positive and subtracted; expenses positive; supplier warranty recoveries 5120 negative.")

# ------------------------------------------------------------------ P&L KPI aggregates
K = {(p, e): defaultdict(int) for p in PERIODS for e in ENTS}
for (p, e, a), (act, b) in agg.items():
    t = COA[a]["account_type"]; k = K[(p, e)]
    if t == "revenue": k["net_revenue"] += act; k["b_net_revenue"] += b
    elif t == "contra_revenue": k["net_revenue"] -= act; k["b_net_revenue"] -= b; k["concessions"] += act
    else:
        g = GROUP[COA[a]["reporting_group"]]; k["x:" + g] += act; k["bx:" + g] += b
        if a in DIRECT: k["direct"] += act; k["b_direct"] += b
        if a not in ("6600", "6700"): k["opex_all"] += act; k["b_opex_all"] += b
        k["expense"] += act; k["b_expense"] += b
    if a == "4000": k["labor_sales"] += act
    if a == "4010": k["parts_sales"] += act
    if a == "5100": k["parts_cogs"] += act
for k in K.values():
    k["contribution"] = k["net_revenue"] - k["direct"]; k["b_contribution"] = k["b_net_revenue"] - k["b_direct"]
    k["ebitda"] = k["net_revenue"] - k["opex_all"]; k["b_ebitda"] = k["b_net_revenue"] - k["b_opex_all"]
    k["net_income"] = k["net_revenue"] - k["expense"]; k["b_net_income"] = k["b_net_revenue"] - k["b_expense"]

# balances at month end (TB closing, positive magnitudes)
BAL = {"1000": "bank", "1010": "processor_clearing", "1020": "undeposited", "1100": "ar", "1200": "inventory", "1210": "wip",
       "2000": "ap", "2100": "sales_tax_payable", "2200": "deposits", "2300": "payroll_payable", "2500": "debt"}
for p in PERIODS:
    for loc in LOCS + ["HQ"]:
        for a, nm in BAL.items():
            v = tb[(p, loc, a)][2]; v = v if a < "2000" else -v
            K[(p, loc)][nm] += v; K[(p, "COMPANY")][nm] += v

# control totals (package validation, recomputed independently)
ctrl = list(read("../validation/monthly_control_totals"))
lctrl = list(read("../validation/location_monthly_control_totals"))
CMAP = {"earned_net_sales_usd": "net_revenue", "net_income_usd": "net_income", "gl1000_balance_usd": "bank", "gl1010_balance_usd": "processor_clearing",
        "gl1020_balance_usd": "undeposited", "gl1100_balance_usd": "ar", "gl1200_balance_usd": "inventory", "gl1210_balance_usd": "wip",
        "gl2000_balance_usd": "ap", "gl2100_balance_usd": "sales_tax_payable", "gl2200_balance_usd": "deposits", "gl2300_balance_usd": "payroll_payable",
        "gl2500_balance_usd": "debt"}
n = bad = 0; ex = []
for r in ctrl + lctrl:
    e = r.get("location_id", "COMPANY")
    for col, key in CMAP.items():
        n += 1
        if c(r[col]) != K[(r["month"], e)][key]:
            bad += 1; ex.append(f"{r['month']} {e} {key}")
check("Control totals", "13 metrics × 24 months × company + 4 locations vs validation control totals", bad == 0, f"{n:,} comparisons, {bad} differences {ex[:3]}")
src_diff = sum(1 for r in ctrl + lctrl for col in r if col.endswith("difference_usd") and c(r[col]) != 0)
check("Control totals", "Package sub-ledger vs GL differences all zero", src_diff == 0, f"{len(ctrl) + len(lctrl)} rows checked")

# FY profile figures (COMPANY_PROFILE_RU.md)
PROFILE = {("FY2025", "net_revenue"): 819112003, ("FY2026", "net_revenue"): 861422210, ("FY2025", "ebitda"): 325232162,
           ("FY2026", "ebitda"): 309764093, ("FY2025", "contribution"): 493725722, ("FY2026", "contribution"): 485381304}
for (f, key), exp in PROFILE.items():
    got = sum(K[(p, "COMPANY")][key] for p in PERIODS if fy(p) == f)
    check("Company profile", f"{f} {key.replace('_', ' ')} = profile", got == exp, f"expected {u(exp):,.2f}, got {u(got):,.2f}")
last = K[("2026-10", "COMPANY")]
for key, exp in {"bank": 71115178, "ar": 22791466, "ap": 27044363, "inventory": 7817267, "wip": 338629, "deposits": 261786,
                 "payroll_payable": 10937069, "sales_tax_payable": 2180351, "debt": 10800000, "processor_clearing": 6573741, "undeposited": 1027316}.items():
    check("Company profile", f"Cutoff balance {key.replace('_', ' ')}", last[key] == exp, f"expected {u(exp):,.2f}, got {u(last[key]):,.2f}")

# ------------------------------------------------------------------ operations: RO, jobs, lines, segments
SERVICES = {r["service_id"]: r["service_name"] for r in read("shop/service_catalog")}
ros = {r["ro_id"]: r for r in read("shop/repair_orders")}
jobs = {}
for r in read("shop/jobs"): jobs[r["ro_id"]] = r
inv_by_ro = defaultdict(lambda: defaultdict(int))
for r in read("billing/invoice_lines"):
    inv_by_ro[r["ro_id"]][r["line_type"]] += c(r["net_usd"]); inv_by_ro[r["ro_id"]]["net"] += c(r["net_usd"])
book = defaultdict(int)  # hundredths of hour
for r in read("shop/ro_lines"):
    if r["line_type"] == "labor" and r["is_customer_charge"] == "True": book[r["ro_id"]] += c(r["book_hours"])
clock = defaultdict(int)
for r in read("schedule/job_segments"):
    if r["actual_end_at"]: clock[r["ro_id"]] += int(r["approved_clock_minutes"] or 0)
invoices = {r["invoice_id"]: r for r in read("billing/invoices")}
check("Shop", "RO IDs unique and count = 27,348", len(ros) == 27348, f"{len(ros):,} RO")
deliv = [r for r in ros.values() if r["actual_delivery_date"] and r["actual_delivery_date"] <= CUTOFF]
cust = [r for r in deliv if r["is_warranty"] == "False"]; warr = [r for r in deliv if r["is_warranty"] == "True"]
check("Shop", "Delivered RO 27,330 = 26,812 customer invoices + 518 warranty", (len(deliv), len(cust), len(warr)) == (27330, 26812, 518), f"{len(deliv)}/{len(cust)}/{len(warr)}")
check("Billing", "One invoice per delivered customer RO", len(invoices) == len(cust) and all(r["invoice_id"] in invoices for r in cust), f"{len(invoices):,} invoices")

fleet_ro = lambda r: bool(r["fleet_account_id"])
svc_rows = defaultdict(lambda: defaultdict(int))
for r in deliv:
    p = r["actual_delivery_date"][:7]; loc = r["location_id"]
    for e in (loc, "COMPANY"):
        k = K[(p, e)]
        if r["is_warranty"] == "True":
            k["warranty_ros"] += 1; k["warranty_clock_min"] += clock[r["ro_id"]]; continue
        k["customer_ros"] += 1; k["fleet_ros"] += fleet_ro(r); k["ro_net"] += inv_by_ro[r["ro_id"]]["net"]
        k["labor_net"] += inv_by_ro[r["ro_id"]]["labor"]; k["book_hh"] += book[r["ro_id"]]; k["cohort_clock_min"] += clock[r["ro_id"]]
        if fleet_ro(r): k["fleet_net"] += inv_by_ro[r["ro_id"]]["net"]
    j = jobs.get(r["ro_id"]); s = j["service_id"] if j else "?"
    if r["is_warranty"] == "False":
        v = svc_rows[(p, loc, s)]; v["ros"] += 1; v["net"] += inv_by_ro[r["ro_id"]]["net"]; v["labor"] += inv_by_ro[r["ro_id"]]["labor"]
        v["parts"] += inv_by_ro[r["ro_id"]]["parts"]; v["book"] += book[r["ro_id"]]; v["clock"] += clock[r["ro_id"]]; v["fleet"] += fleet_ro(r)
ds("service_mix_monthly", [{"period": p, "location_id": l, "service_id": s, "service": SERVICES.get(s, s), "delivered_ros": v["ros"], "fleet_ros": v["fleet"],
    "net_sales_usd": u(v["net"]), "labor_sales_usd": u(v["labor"]), "parts_sales_usd": u(v["parts"]), "book_hours": round(v["book"] / 100, 2),
    "clock_hours": round(v["clock"] / 60, 1)} for (p, l, s), v in sorted(svc_rows.items())], "period × location × service",
   "Delivered customer (non-warranty) repair orders by delivery month and service template; invoice-line net sales, billed book hours and actual technician clock of exactly this cohort (efficiency = book / clock may exceed 100%).")

# approvals
for r in read("shop/approvals"):
    p = (r["decision_date"] or "")[:7]; ro = ros.get(r["ro_id"]) if r["ro_id"] else None
    if p not in PERIODS: continue
    loc = ro["location_id"] if ro else None
    for e in ([loc, "COMPANY"] if loc else ["COMPANY"]):
        K[(p, e)]["est_decisions"] += r["decision"] in ("approved", "declined"); K[(p, e)]["est_approved"] += r["decision"] == "approved"

# capacity
for r in read("schedule/daily_capacity"):
    p = r["work_date"][:7]
    for e in (r["location_id"], "COMPANY"):
        k = K[(p, e)]; k["tech_avail_min"] += int(r["technician_available_minutes"]); k["tech_work_min"] += int(r["actual_work_minutes"])
        k["tech_paid_min"] += int(r["paid_attendance_minutes"]); k["tech_days"] += 1; k["ramp_days"] += r["new_hire_ramp"] == "True"
techs = defaultdict(set)
for r in read("schedule/daily_capacity"): techs[(r["work_date"][:7], r["location_id"])].add(r["employee_id"]); techs[(r["work_date"][:7], "COMPANY")].add(r["employee_id"])
for (p, e), s in techs.items(): K[(p, e)]["technicians"] = len(s)
for r in read("schedule/bay_calendar"):
    p = r["work_date"][:7]
    for e in (r["location_id"], "COMPANY"):
        k = K[(p, e)]; k["bay_open_min"] += int(r["bay_open_minutes"]); k["bay_prod_min"] += int(r["actual_productive_minutes"]); k["bay_occ_min"] += int(r["occupied_open_minutes"])
bays = {r["bay_id"] for r in read("schedule/bay_calendar")}
check("Capacity", "Bay calendar covers all 18 physical bays", len(bays) == 18, f"{len(bays)} bays")

# comebacks
cb_rows = defaultdict(lambda: [0, 0, 0])
for r in read("warranty/comebacks"):
    p = r["reported_date"][:7]
    if p not in PERIODS: continue
    for e in (r["location_id"], "COMPANY"): K[(p, e)]["comebacks"] += 1
    v = cb_rows[(p, r["location_id"], r["reason"])]; v[0] += 1; v[1] += int(r["corrective_actual_minutes"] or 0); v[2] += c(r["corrective_parts_cost_usd"])
ds("comebacks_monthly", [{"period": p, "location_id": l, "reason": rs, "comebacks": v[0], "corrective_hours": round(v[1] / 60, 1), "corrective_parts_cost_usd": u(v[2])}
    for (p, l, rs), v in sorted(cb_rows.items())], "period × location × reason",
   "Free corrective (warranty comeback) repair orders by reported month: count, technician hours and parts cost. Supplier recoveries are booked separately in GL 5120.")

# marketing
mk = defaultdict(lambda: defaultdict(int))
for r in read("marketing/daily_performance"):
    v = mk[(r["performance_date"][:7], r["location_id"], r["platform"])]
    v["spend"] += c(r["spend_usd"]); v["impr"] += int(r["impressions"]); v["clicks"] += int(r["clicks"]); v["conv"] += int(r["platform_claimed_conversions"]); v["claim"] += c(r["platform_claimed_value_usd"])
for r in read("marketing/leads"):
    p = r["lead_date"][:7]
    if p not in PERIODS: continue
    v = mk[(p, r["location_id"], r["source_channel"])]; v["leads"] += 1; v["booked"] += r["lead_status"] == "appointment_booked"
mrows = []
for (p, l, ch), v in sorted(mk.items()):
    if p not in PERIODS: continue
    mrows.append({"period": p, "location_id": l, "channel": ch, "spend_usd": u(v["spend"]), "impressions": v["impr"], "clicks": v["clicks"],
                  "claimed_conversions": v["conv"], "claimed_value_usd": u(v["claim"]), "leads": v["leads"], "booked_leads": v["booked"]})
    for e in (l, "COMPANY"):
        K[(p, e)]["ad_spend"] += v["spend"]; K[(p, e)]["leads"] += v["leads"]; K[(p, e)]["booked_leads"] += v["booked"]
ds("marketing_monthly", mrows, "period × location × channel",
   "Ad spend (daily platform data), platform-claimed conversions/value (overlapping attribution claims, not revenue) and observed leads by source channel; booked = lead became an appointment.")
gl_ads = sum(K[(p, "COMPANY")]["x:Marketing"] for p in PERIODS); daily_ads = sum(K[(p, "COMPANY")]["ad_spend"] for p in PERIODS)
check("Marketing", "Daily ad spend = GL 6400 advertising (24 months)", gl_ads == daily_ads, f"GL {u(gl_ads):,.2f} vs daily {u(daily_ads):,.2f}")

# ------------------------------------------------------------------ KPI table
kpi = []
r1 = lambda a, b, d=1: round(a / b * 100, d) if b else None
for p in PERIODS:
    for e in ENTS:
        k = K[(p, e)]; g = lambda x: u(k["x:" + x]); bg = lambda x: u(k["bx:" + x])
        kpi.append({"period": p, "fy": fy(p), "entity": e, "name": NAMES[e],
            "net_revenue": u(k["net_revenue"]), "budget_net_revenue": u(k["b_net_revenue"]), "labor_sales": u(k["labor_sales"]), "parts_sales": u(k["parts_sales"]),
            "concessions": u(k["concessions"]), "technician_labor": g("Technician labor"), "budget_technician_labor": bg("Technician labor"),
            "parts_cogs": g("Parts COGS"), "budget_parts_cogs": bg("Parts COGS"), "warranty_net": g("Warranty (net)"), "budget_warranty_net": bg("Warranty (net)"),
            "inventory_loss": g("Inventory loss"), "sublet_cogs": g("Sublet COGS"),
            "contribution": u(k["contribution"]), "budget_contribution": u(k["b_contribution"]),
            "shop_payroll": g("Shop staff payroll"), "hq_payroll": g("HQ payroll"), "rent": g("Rent"), "overhead": g("Occupancy & overhead"),
            "maintenance": g("Equipment maintenance"), "marketing": g("Marketing"), "merchant_fees": g("Merchant fees"),
            "ebitda": u(k["ebitda"]), "budget_ebitda": u(k["b_ebitda"]), "depreciation": g("Depreciation"), "interest": g("Interest"),
            "net_income": u(k["net_income"]), "budget_net_income": u(k["b_net_income"]),
            "parts_margin_pct": r1(k["parts_sales"] - k["parts_cogs"], k["parts_sales"]),
            "customer_ros": k["customer_ros"], "fleet_ros": k["fleet_ros"], "warranty_ros": k["warranty_ros"],
            "aro": u(k["ro_net"] // k["customer_ros"]) if k["customer_ros"] else None, "ro_net_sales": u(k["ro_net"]), "fleet_net_sales": u(k["fleet_net"]),
            "book_hours": round(k["book_hh"] / 100, 1), "cohort_clock_hours": round(k["cohort_clock_min"] / 60, 1),
            "efficiency_pct": r1(k["book_hh"] / 100, k["cohort_clock_min"] / 60), "effective_labor_rate": round(k["labor_net"] / k["book_hh"], 2) if k["book_hh"] else None,
            "tech_available_hours": round(k["tech_avail_min"] / 60, 1), "tech_worked_hours": round(k["tech_work_min"] / 60, 1), "tech_paid_hours": round(k["tech_paid_min"] / 60, 1),
            "utilization_pct": r1(k["tech_work_min"], k["tech_avail_min"]), "technicians": k["technicians"], "ramp_days": k["ramp_days"],
            "bay_productive_pct": r1(k["bay_prod_min"], k["bay_open_min"]), "bay_occupied_pct": r1(k["bay_occ_min"], k["bay_open_min"]),
            "warranty_clock_hours": round(k["warranty_clock_min"] / 60, 1), "comebacks": k["comebacks"], "comeback_flow_pct": r1(k["comebacks"], k["customer_ros"], 2),
            "approval_rate_pct": r1(k["est_approved"], k["est_decisions"]), "ad_spend": u(k["ad_spend"]), "leads": k["leads"], "booked_leads": k["booked_leads"],
            "bank": u(k["bank"]), "processor_clearing": u(k["processor_clearing"]), "undeposited": u(k["undeposited"]), "ar": u(k["ar"]), "ap": u(k["ap"]),
            "inventory": u(k["inventory"]), "wip": u(k["wip"]), "deposits": u(k["deposits"]), "payroll_payable": u(k["payroll_payable"]),
            "sales_tax_payable": u(k["sales_tax_payable"]), "debt": u(k["debt"])})
ds("kpi_monthly", kpi, "period × entity",
   "One row per month and entity (COMPANY, LOC-01..03, HQ): P&L subtotals vs budget (contribution = net revenue − technician payroll, parts COGS, net warranty, stock loss, sublet; EBITDA excludes 6600/6700), shop KPIs (customer RO by delivery date, ARO, book vs clock hours, efficiency, effective labor rate, technician utilization, physical bay utilization of all 18 bays, comebacks, estimate approval rate, ads/leads) and month-end balances from the trial balance.")

# ------------------------------------------------------------------ margin bridge (package derived control)
mb = []
for r in list(read("../validation/monthly_margin_bridge")) + list(read("../validation/location_monthly_margin_bridge")):
    mb.append({"period": r["month"], "entity": r["location_id"], "ro_cohort_margin": u(c(r["ro_cohort_margin_before_warranty_usd"])),
               "concessions": -u(c(r["period_customer_concessions_usd"])), "idle_pto_labor": -u(c(r["period_idle_pto_unallocated_labor_usd"])),
               "warranty_labor": -u(c(r["period_warranty_labor_allocation_usd"])), "labor_timing": -u(c(r["labor_earned_vs_delivery_cohort_timing_usd"])),
               "warranty_parts": -u(c(r["period_warranty_parts_usd"])), "supplier_recoveries": u(c(r["period_supplier_warranty_recoveries_usd"])),
               "stock_writeoffs": -u(c(r["period_stock_writeoffs_usd"])), "gl_contribution": u(c(r["gl_period_direct_contribution_usd"])), "difference": u(c(r["difference_usd"]))})
mbd = sum(1 for r in mb if r["difference"] != 0)
mbx = sum(1 for r in mb if c(f"{r['gl_contribution']:.2f}") != K[(r["period"], r["entity"])]["contribution"])
check("Margin bridge", "RO-cohort margin bridges to GL contribution (120 rows, difference 0)", mbd == 0 and len(mb) == 120, f"{len(mb)} rows, {mbd} non-zero")
check("Margin bridge", "Bridge GL contribution = pipeline contribution", mbx == 0, f"{mbx} differences")
ds("margin_bridge_monthly", mb, "period × entity",
   "Package bridge from delivered RO-cohort margin (allocated technician labor) to the period GL contribution: concessions, idle/PTO labor, warranty labor and parts, labor timing, supplier recoveries, stock write-offs. Negative = reduces contribution. Management memo, not GL postings.")

# ------------------------------------------------------------------ bank
bm = [{"period": r["month"], "opening_usd": u(c(r["opening_balance_usd"])), "inflows_usd": u(c(r["inflows_usd"])), "outflows_usd": u(c(r["outflows_usd"])),
       "closing_usd": u(c(r["closing_balance_usd"])), "transactions": int(r["transaction_count"])} for r in read("bank/monthly_statements")]
ds("bank_monthly", bm, "period", "Operating bank statement by month (one physical account; location tags are analytical).")
bt = defaultdict(lambda: [0, 0, 0]); bank = list(read("bank/statement"))
for r in bank:
    v = bt[(r["posted_date"][:7], r["transaction_type"])]; a = c(r["amount_usd"]); v[0] += 1; v[1] += max(a, 0); v[2] += -min(a, 0)
ds("bank_type_monthly", [{"period": p, "transaction_type": t, "transactions": v[0], "inflows_usd": u(v[1]), "outflows_usd": u(v[2])} for (p, t), v in sorted(bt.items())],
   "period × transaction type", "Bank movements by type: processor payouts, customer ACH, cash deposits, vendor payments, payroll funding, sales tax, debt service, owner distributions.")
bal = c(bm[0]["opening_usd"] and f"{bm[0]['opening_usd']:.2f}") + sum(c(r["amount_usd"]) for r in bank)
check("Bank", "Opening + all transactions = cutoff bank balance", bal == 71115178 and bm[-1]["closing_usd"] == 711151.78, f"{u(bal):,.2f}")
own = [{"id": r["distribution_id"], "date": r["distribution_date"], "amount_usd": u(c(r["amount_usd"]))} for r in read("finance/owner_distributions")]
ds("owner_distributions", own, "distribution", "Quarterly owner sweeps (equity, not expense). Synthetic policy: ≤ $1M each, keeping ≥ $450k in the bank; none assumed in the forecast.")

# ------------------------------------------------------------------ open AR / AP at cutoff
oar = []
for r in read("billing/open_ar"):
    dpd = int(r["days_past_due"] or 0)
    bucket = "Current" if dpd <= 0 else "1–30" if dpd <= 30 else "31–60" if dpd <= 60 else "61–90" if dpd <= 90 else "90+"
    oar.append({"invoice_id": r["invoice_id"], "ro_id": r["ro_id"], "location_id": r["location_id"], "customer": r["fleet_account_id"] or "Retail",
                "invoice_date": r["invoice_date"], "due_date": r["due_date"], "open_usd": u(c(r["open_amount_usd"])), "days_past_due": dpd, "bucket": bucket,
                "expected_collection_date": r["expected_collection_date"]})
check("Working capital", "Open AR list = GL 1100 at cutoff", sum(c(f"{r['open_usd']:.2f}") for r in oar) == last["ar"], f"{len(oar)} invoices")
ds("open_ar", oar, "open invoice at cutoff", "Unpaid customer invoices at 2026-10-31 after credits and allocations; fleet accounts (FLEET-…) pay partially and late; expected collection date is an assumption.")
oap = []
for r in read("accounting/open_ap"):
    oap.append({"bill_id": r["bill_id"], "vendor_id": r["vendor_id"], "location_id": r["location_id"], "bill_date": r["bill_date"], "due_date": r["due_date"],
                "open_usd": u(c(r["open_amount_usd"])), "po_id": r["po_id"], "contract_id": r["contract_id"], "expected_payment_date": r["expected_payment_date"]})
check("Working capital", "Open AP list = GL 2000 at cutoff", sum(c(f"{r['open_usd']:.2f}") for r in oap) == last["ap"], f"{len(oap)} bills")
ds("open_ap", oap, "open bill at cutoff", "Open vendor bills at 2026-10-31 (parts suppliers SUP-…, operating vendors VEN-…). Payroll, tax, debt and deposits are not AP.")

# recent RO drill-down (last 3 months)
rr = []
for r in deliv:
    if r["actual_delivery_date"] < "2026-10-01": continue
    j = jobs.get(r["ro_id"], {}); i = inv_by_ro[r["ro_id"]]
    rr.append({"ro_id": r["ro_id"], "location_id": r["location_id"], "delivered": r["actual_delivery_date"], "opened": r["opened_date"],
               "service": SERVICES.get(j.get("service_id"), ""), "warranty": r["is_warranty"] == "True", "fleet": r["fleet_account_id"] or "",
               "invoice_id": r["invoice_id"], "net_usd": u(i["net"]), "labor_usd": u(i["labor"]), "parts_usd": u(i["parts"]),
               "book_hours": round(book[r["ro_id"]] / 100, 2), "clock_hours": round(clock[r["ro_id"]] / 60, 2), "technician": j.get("employee_id", "")})
ds("ro_recent", sorted(rr, key=lambda x: x["delivered"]), "delivered RO (Oct 2026)",
   "Drill-down: every repair order delivered in October 2026 with invoice ID, service, net sales split, billed book hours vs actual clock and technician.")

# ------------------------------------------------------------------ 13-week cash forecast
D = lambda s: date.fromisoformat(s)
W0 = date(2026, 11, 1)
wk = lambda d: (d - W0).days // 7 + 1
def bday_fwd(d):
    while d.weekday() >= 5: d += timedelta(days=1)
    return d
def add_bdays(d, n):
    d = bday_fwd(d)
    for _ in range(n):
        d += timedelta(days=1); d = bday_fwd(d)
    return d
CASH = []
def cash(id_, d, loc, typ, amt, source, certainty, ovl):
    CASH.append({"id": id_, "week_index": wk(d), "expected_cash_date": d.isoformat(), "location_id": loc, "direction": "in" if amt >= 0 else "out",
                 "commitment_type": typ, "amount_usd": u(amt), "source": source, "certainty": certainty, "overlap_key": ovl})
LABEL = {"customer_collection": "Open AR collection", "open_AP_payment": "Open AP payment", "unreceived_PO_payment": "Unreceived PO",
         "earned_payroll_funding": "Earned payroll (Oct)", "contractual_debt_payment": "Debt service", "tax_payable_remittance": "Sales tax (Oct)",
         "recurring_contract_next_cycle": "Contracts (Nov cycle)"}
seen = set(); dup = 0; beyond = 0; appts = 0
for r in read("planning/commitments"):
    if r["commitment_type"] == "agreed_future_appointment": appts += 1; continue
    if r["overlap_key"] in seen: dup += 1; continue
    seen.add(r["overlap_key"]); d = D(r["expected_date"])
    if wk(d) > 13: beyond += 1; continue
    cash(r["commitment_id"], d, r["location_id"], LABEL[r["commitment_type"]], c(r["expected_amount_usd"]), r["source_table"] + " " + r["source_id"], "known", r["overlap_key"])
# processor clearing and undeposited receipts at cutoff settle in week 1 (not new revenue)
for loc in LOCS + ["HQ"]:
    pc = tb[("2026-10", loc, "1010")][2]; ud = tb[("2026-10", loc, "1020")][2]
    if pc: cash(f"CLEAR-1010-{loc}", date(2026, 11, 3), loc, "Processor settlement", pc, "GL 1010 at cutoff", "known", f"1010-{loc}")
    if ud: cash(f"CLEAR-1020-{loc}", date(2026, 11, 2), loc, "Undeposited cash/ACH", ud, "GL 1020 at cutoff", "known", f"1020-{loc}")

# drivers (trailing 8 weeks to cutoff = 2026-09-06..2026-10-31)
T0 = date(2026, 9, 6); T1 = D(CUTOFF)
inv_l8 = [r for r in invoices.values() if T0 <= D(r["invoice_date"]) <= T1]
retail_w = sum(c(r["total_usd"]) - c(r["credit_total_usd"]) for r in inv_l8 if not r["fleet_account_id"]) // 8
fleet_w = sum(c(r["total_usd"]) for r in inv_l8 if r["fleet_account_id"]) // 8
# fleet collection lag: amount-weighted days invoice -> payment, invoices of the last 6 months fully paid
pays = defaultdict(list)
for r in read("billing/payments"):
    if r["payment_type"] == "receipt" and r["invoice_id"]: pays[r["invoice_id"]].append((D(r["payment_date"]), c(r["amount_usd"])))
num = den = 0
for r in invoices.values():
    if r["fleet_account_id"] and "2026-03-01" <= r["invoice_date"] <= "2026-08-31":
        for d, a in pays[r["invoice_id"]]: num += (d - D(r["invoice_date"])).days * a; den += a
fleet_lag = round(num / den) if den else 60
supp_w = -sum(c(r["amount_usd"]) for r in bank if r["transaction_type"] == "vendor_payment" and T0 <= D(r["posted_date"]) <= T1) // 8
runs = sorted(read("payroll/runs"), key=lambda r: r["period_end"])
ends = sorted({r["period_end"] for r in runs})[-4:]
pay_cycle = sum(c(r["total_funding_usd"]) for r in runs if r["period_end"] in ends) // 4
tax_m = sum(c(r["net_tax_collected_usd"]) for r in read("finance/tax_register") if r["tax_month"] in ("2026-08", "2026-09", "2026-10")) // 3
contracts = list(read("operating/recurring_contracts"))
# future payroll cycles (period ends after cutoff), funded period end + 2 business days
for pe in ["2026-11-15", "2026-11-30", "2026-12-15", "2026-12-31", "2027-01-15"]:
    d = add_bdays(D(pe), 2)
    if wk(d) <= 13: cash(f"PAYROLL-{pe}", d, "ALL", "Payroll (future cycles)", -pay_cycle, "avg of last 4 funded cycles", "driver", f"payroll-{pe}")
for tm, due in [("2026-11", "2026-12-21"), ("2026-12", "2027-01-20")]:
    cash(f"SALESTAX-{tm}", D(due), "ALL", "Sales tax (future months)", -tax_m, "trailing 3-month avg collected", "driver", f"tax-{tm}")
for r in contracts:  # December service cycle due 2027-01-15 (November cycle is a known commitment)
    cash(f"{r['contract_id']}-2026-12", D("2027-01-15"), r["location_id"], "Contracts (Dec cycle)", -c(r["monthly_base_usd"]), "current monthly_base_usd", "driver", f"{r['contract_id']}-2026-12")
check("Cash forecast", "Commitments: one row per overlap key", dup == 0, f"{len(seen)} keys, {dup} duplicates, {beyond} beyond 13 weeks, {appts} appointment rows have no amount (demand only)")
opening = last["bank"]
check("Cash forecast", "Forecast opens at actual bank balance", opening == 71115178, f"{u(opening):,.2f}")
ds("cash_schedule_13w", sorted(CASH, key=lambda x: (x["expected_cash_date"], x["id"])), "cash line",
   "Known cash events after cutoff (open AR/AP, unreceived POs, earned payroll, Oct sales tax, debt service, Nov contract cycle, processor/undeposited settlement) deduplicated by overlap key, plus driver lines (future payroll cycles, sales tax, December contract cycle). New-sales receipts and parts purchases are added on the page from cash_drivers.")

# ------------------------------------------------------------------ sources, events, stories
cat = {r["source_system"]: r for r in read("../metadata/source_catalog")}
USE = {"shop": "RO, jobs, lines, estimates/approvals → ARO, mix, book hours", "schedule": "segments, capacity, bay calendar → efficiency, utilization",
       "inventory": "stock, WIP, parts usage", "purchasing": "PO, receipts, supplier terms", "billing": "invoices, payments, open AR, deposits",
       "warranty": "comebacks, supplier recoveries", "processor": "card clearing, payouts", "payroll": "runs, funding", "operating": "contracts, assets, sublet",
       "finance": "debt, sales tax, owner distributions", "marketing": "ad spend, leads", "accounting": "GL, TB, budget actuals, open AP",
       "bank": "statement, monthly balances", "planning": "budget, commitments, assumptions"}
ds("data_sources", [{"source": s, "tables": int(r["logical_tables"]), "records": int(r["row_count"]), "description": r["description"], "usage": USE.get(s, ""), "status": "Loaded"} for s, r in cat.items()],
   "source system", "Simulated source systems of the raw package (custom synthetic extracts, no native API fidelity claimed).")
ds("business_events", [{"date": r["effective_date"], "event": r["event_name"], "evidence": r["evidence_tables"]} for r in read("planning/business_events")],
   "event", "Designed business events of the synthetic case.")
vs = json.load(open(os.path.join(ROOT, "validation", "validation_summary.json"), encoding="utf-8"))
check("Package verifier", "validation_summary.json status", vs["status"] == "PASS" and vs["failed_checks"] == 0, f"{vs['checks']} checks, {vs['evaluated_assertions']:,} assertions, {vs['failed_checks']} failed")

def fyv(e, key, f): return sum(K[(p, e)][key] for p in PERIODS if fy(p) == f)
def fyx(e, f): return {k: fyv(e, k, f) for k in ("net_revenue", "ebitda", "contribution", "b_net_revenue", "b_ebitda", "customer_ros", "ro_net")}
c25, c26 = fyx("COMPANY", "FY2025"), fyx("COMPANY", "FY2026")
oj = {p: K[(p, "LOC-03")] for p in PERIODS}
cb_pre = sum(oj[p]["comebacks"] for p in PERIODS if p < "2026-05"); cb_post = sum(oj[p]["comebacks"] for p in PERIODS if p >= "2026-05")
pm25 = (fyv("COMPANY", "parts_sales", "FY2025") - fyv("COMPANY", "parts_cogs", "FY2025")) / fyv("COMPANY", "parts_sales", "FY2025") * 100
pm26 = (fyv("COMPANY", "parts_sales", "FY2026") - fyv("COMPANY", "parts_cogs", "FY2026")) / fyv("COMPANY", "parts_sales", "FY2026") * 100
lab25 = fyv("COMPANY", "x:Technician labor", "FY2025"); lab26 = fyv("COMPANY", "x:Technician labor", "FY2026")
stories = [
    f"FY2026 net revenue ${u(c26['net_revenue'])/1e6:.2f}M (+{(c26['net_revenue']/c25['net_revenue']-1)*100:.1f}% YoY) but EBITDA ${u(c26['ebitda'])/1e6:.2f}M ({c26['ebitda']/c26['net_revenue']*100:.1f}% margin vs {c25['ebitda']/c25['net_revenue']*100:.1f}% in FY2025).",
    f"Fewer but bigger jobs: customer RO {c25['customer_ros']:,} → {c26['customer_ros']:,}, ARO ${u(c25['ro_net']//c25['customer_ros']):,.0f} → ${u(c26['ro_net']//c26['customer_ros']):,.0f}.",
    f"Parts margin squeezed {pm25:.1f}% → {pm26:.1f}%: supplier costs +9% from Jul 2025 vs retail parts prices +4%.",
    f"Technician payroll ${u(lab25)/1e6:.2f}M → ${u(lab26)/1e6:.2f}M (+4.5% pay from Jan 2026, sixth technician per shop ramping up).",
    f"Oak Junction (LOC-03) comebacks: {cb_pre} in 18 months to Apr 2026 vs {cb_post} in May–Oct 2026.",
]
ds("stories", [{"id": i + 1, "story": s} for i, s in enumerate(stories)], "finding", "Headline findings computed from the data mart.")

fails = [x for x in CHECKS if x["status"] != "PASS"]
ds("reconciliations", CHECKS, "check", "Pipeline checks against the package control totals, company profile and ledger identities.")
for x in CHECKS: print(x["status"], x["area"], "|", x["check"], "|", x["detail"])
if fails:
    print(f"{len(fails)} FAIL — nothing written"); sys.exit(1)

meta = {"company": "ABC Auto", "label": "Demo company / Synthetic data",
        "business": "Three general auto-repair shops (6 bays each, 18 bays) plus a shared office; no vehicle sales",
        "currency": "USD", "cutoff": CUTOFF, "first_period": PERIODS[0], "last_period": PERIODS[-1],
        "fiscal_year_note": "Fiscal year runs November–October; FY2026 = Nov 2025–Oct 2026", "fiscal_years": ["FY2025", "FY2026"],
        "entities": NAMES, "locations": {l: NAMES[l] for l in LOCS},
        "opening_cash": u(opening),
        "cash_drivers": {"retail_receipts_weekly_usd": u(retail_w), "fleet_invoicing_weekly_usd": u(fleet_w), "fleet_collection_lag_days": fleet_lag,
                         "supplier_vendor_payments_weekly_usd": u(supp_w), "payroll_cycle_funding_usd": u(pay_cycle), "sales_tax_monthly_usd": u(tax_m),
                         "trailing_window": "2026-09-06 to 2026-10-31 (8 weeks)"},
        "cash_week_convention": "Consecutive 7-day weeks Sunday–Saturday starting 2026-11-01 (13 weeks, ends 2027-01-30).",
        "cash_rules": ["Opening = actual operating bank 2026-10-31; processor clearing (GL 1010) and undeposited cash/ACH (GL 1020) settle in week 1 — not new revenue.",
                       "Known events from planning/commitments apply once per overlap key (open AR, open AP, unreceived POs, earned October payroll, October sales tax, debt service, November contract cycle). Appointment rows carry no amount and are demand only.",
                       "New retail sales are collected the same week at the trailing 8-week run rate; new fleet invoices are collected after the observed fleet lag.",
                       "Vendor/supplier payments: a week takes the larger of known AP/PO/contract items and the trailing 8-week vendor run rate, so nothing is counted twice.",
                       "Future payroll = average of the last four semi-monthly cycles, funded period end + 2 business days; future sales tax = trailing 3-month average, due the 20th.",
                       "Owner distributions, capital spending and income tax are excluded."],
        "cash_floor": 450000, "cash_floor_note": "Minimum bank reserve from the synthetic owner-distribution policy (planning data).",
        "scenarios": {"base": {"sales": 100, "vendor": 100, "fleet_delay_weeks": 0}, "improved": {"sales": 105, "vendor": 98, "fleet_delay_weeks": 0},
                      "stress": {"sales": 90, "vendor": 105, "fleet_delay_weeks": 2}},
        "recon_pass": len(CHECKS) - len(fails), "recon_total": len(CHECKS), "package_checks": vs["checks"], "source_rows": vs["source_csv_rows"], "source_tables": vs["logical_tables"],
        "source_files": 370, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
os.makedirs(OUTDIR, exist_ok=True)
json.dump({"meta": meta, "datasets": OUT}, open(os.path.join(OUTDIR, "datamart.json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"OK {len(CHECKS)}/{len(CHECKS)} checks; wrote {os.path.join(OUTDIR, 'datamart.json')}")
