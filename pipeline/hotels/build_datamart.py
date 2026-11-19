#!/usr/bin/env python3
"""ABC Hotels data mart builder (demo company, synthetic data).

Reads the raw "Juniper Quay Hospitality" package (placeholder name; renamed to ABC Hotels on output),
rebuilds the model in integer cents from source CSVs only, reconciles every month x scope against
validation/monthly_control_totals.csv and writes datamart.json + reconciliation_report.csv.
If any check fails it prints the failures, writes only the report and exits 1.

Usage: python3 -I pipeline/hotels/build_datamart.py data/abc_hotels_data data/output/hotels
Standard library only.
"""
import csv, glob, json, os, sys, subprocess, calendar
from collections import defaultdict, Counter
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal

PKG, OUT = sys.argv[1], sys.argv[2]
SRC = os.path.join(PKG, "sources")
CUT = "2026-10-31"
PROPS = ["RAL", "WIL", "DUR"]
CENTRES = PROPS + ["CORP"]
ENTS = ["COMPANY"] + CENTRES
COMPANY = "ABC Hotels"
PNAMES = {"RAL": "ABC Raleigh Station", "WIL": "ABC Cape Landing (Wilmington)", "DUR": "ABC Durham Residences", "CORP": "Shared corporate (CORP)"}
SHORT = {"RAL": "Raleigh", "WIL": "Wilmington", "DUR": "Durham", "CORP": "CORP", "COMPANY": "Company"}
CH_NAMES = {"DIRECT": "Direct (web & front desk)", "BOOKING": "Booking-style OTA (agency)", "EXPEDIA": "Expedia-style OTA (merchant)", "CORPORATE": "Corporate accounts", "INTERNAL": "Comp & house use"}


def cents(s):
    if s is None or s == "":
        return 0
    return int((Decimal(s) * 100).to_integral_value())


def usd(c):
    return round(c / 100, 2)


def read(rel):
    """Read one logical table: a single CSV or all monthly partitions in a folder."""
    p = os.path.join(SRC, rel)
    files = sorted(glob.glob(os.path.join(p, "*.csv"))) if os.path.isdir(p) else [p + ".csv"]
    rows = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rows.extend(csv.DictReader(fh))
    return rows, len(files)


def D(s):
    return date.fromisoformat(s)


def bday(d):
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


def add_bdays(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def month_end(m):
    y, mo = map(int, m.split("-"))
    return date(y, mo, calendar.monthrange(y, mo)[1])


def next_month(m):
    y, mo = map(int, m.split("-"))
    return f"{y + (mo == 12)}-{1 if mo == 12 else mo + 1:02d}"


def fy(m):
    y, mo = map(int, m.split("-"))
    return f"FY{y + 1 if mo >= 11 else y}"


checks = []


def check(area, name, ok, detail):
    checks.append({"area": area, "check": name, "detail": detail, "status": "PASS" if ok else "FAIL"})


# ------------------------------------------------------------------ load
T = {}
FILES = {}
for rel in ["quickbooks/chart_of_accounts", "quickbooks/general_ledger", "quickbooks/monthly_trial_balance", "quickbooks/bills",
            "availability/room_dates", "availability/room_blocks", "pms/actual_stay_nights", "pms/reservations", "pms/properties", "pms/room_types",
            "night_audit/folio_lines", "channel_manager/commissions", "channel_manager/agency_invoices", "channel_manager/settlements",
            "corporate_billing/companies", "corporate_billing/invoices", "corporate_billing/receipts", "corporate_billing/receipt_applications", "corporate_billing/prepayments",
            "operations/housekeeping_tasks", "operations/agency_shifts", "gusto/time_entries", "gusto/employees", "gusto/compensation_history", "gusto/payroll_runs",
            "marketing/daily_campaigns", "marketing/direct_funnel", "marketing/billing", "bank/monthly_balances", "bank/statement",
            "planning/approved_budget", "planning/approved_room_plan", "planning/shared_cost_allocations", "planning/known_cash_inputs",
            "planning/booked_payment_terms", "planning/on_books_nights", "planning/forecast_weeks", "planning/incremental_demand_assumptions",
            "planning/recurring_contracts", "planning/future_payroll_calendar", "planning/future_capacity", "planning/capex_commitments",
            "night_audit/tax_policies", "procurement/vendors", "fixed_assets_finance/debt_schedule"]:
    T[rel], FILES[rel] = read(rel)

COA = {r["account_code"]: r for r in T["quickbooks/chart_of_accounts"]}
MONTHS = sorted({r["service_month"] for r in T["bank/monthly_balances"]})
assert len(MONTHS) == 24 and MONTHS[-1] == CUT[:7], MONTHS

# ------------------------------------------------------------------ package verifier
ver = {"failed_conditions": None}
try:
    pr = subprocess.run([sys.executable, "-I", os.path.join(PKG, "reproducibility", "verify_dataset.py"), PKG], capture_output=True, text=True, timeout=3000)
    last = [l for l in pr.stdout.strip().splitlines() if l.startswith("{")][-1]
    ver = json.loads(last)
except Exception as e:  # report as a failed check
    ver = {"failed_conditions": -1, "error": str(e)}
check("Source package", "Independent package verifier over all source tables",
      ver.get("failed_conditions") == 0,
      f"{ver.get('check_groups', '?')} check groups, {ver.get('evaluated_conditions', 0):,} conditions; {ver.get('failed_conditions')} failures" if ver.get("failed_conditions") is not None and ver.get("failed_conditions") >= 0 else f"verifier did not run: {ver.get('error')}")

# ------------------------------------------------------------------ GL
gl = defaultdict(int)  # (month, centre, account) -> signed debit-credit cents
journals = defaultdict(int)
for r in T["quickbooks/general_ledger"]:
    v = cents(r["debit_usd"]) - cents(r["credit_usd"])
    gl[(r["accounting_date"][:7], r["property_id"], r["account_code"])] += v
    journals[r["journal_id"]] += v
check("Ledger", "Every journal balances (debits = credits)", all(v == 0 for v in journals.values()), f"{len(journals):,} journals, {len(T['quickbooks/general_ledger']):,} lines")

TB = {(r["service_month"], r["property_id"], r["account_code"]): cents(r["closing_signed_usd"]) for r in T["quickbooks/monthly_trial_balance"]}
tbact = defaultdict(int)
for r in T["quickbooks/monthly_trial_balance"]:
    tbact[(r["service_month"], r["property_id"], r["account_code"])] = cents(r["period_debit_usd"]) - cents(r["period_credit_usd"])
bad = [k for k in set(gl) | set(tbact) if gl.get(k, 0) != tbact.get(k, 0)]
check("Ledger", "GL monthly activity equals trial balance activity", not bad, f"{len(tbact):,} month × centre × account rows; {len(bad)} differ")

REV_ACC = [a for a, r in COA.items() if r["account_type"] in ("revenue", "contra_revenue")]
EXP_ACC = [a for a, r in COA.items() if r["account_type"] == "expense"]


def pnl_val(m, c, a):
    v = gl.get((m, c, a), 0)
    return -v if a in REV_ACC else v


# ------------------------------------------------------------------ budget & allocations
bud = defaultdict(int)
for r in T["planning/approved_budget"]:
    bud[(r["service_month"], r["property_id"], r["account_code"])] += cents(r["budget_usd"])
alloc = defaultdict(int)
alloc_acc = defaultdict(int)
alloc_sum = defaultdict(int)
for r in T["planning/shared_cost_allocations"]:
    v = cents(r["allocated_expense_usd"])
    alloc[(r["service_month"], r["property_id"])] += v
    alloc_acc[(r["service_month"], r["property_id"], r["account_code"])] += v
    alloc_sum[r["service_month"]] += v
check("Shared costs", "CORP allocation bridge sums to zero each month", all(v == 0 for v in alloc_sum.values()), f"{len(T['planning/shared_cost_allocations'])} lines, keys 60:52:44")
corp_exp = {m: sum(pnl_val(m, "CORP", a) for a in EXP_ACC if a not in ("5600", "5700")) for m in MONTHS}
check("Shared costs", "Allocated amount equals CORP operating expense", all(-alloc[(m, "CORP")] == corp_exp[m] for m in MONTHS), "24 months; CORP is fully allocated to RAL/WIL/DUR")
room_plan = {(r["service_month"], r["property_id"]): r for r in T["planning/approved_room_plan"]}

# ------------------------------------------------------------------ operations: capacity and stays
ops = defaultdict(Counter)
OPS_F = ["physical_nights", "available_nights", "sold_nights", "complimentary_nights", "house_use_nights", "occupied_nights", "out_of_order_nights", "out_of_service_nights", "arrivals_count", "departures_count"]
for r in T["availability/room_dates"]:
    k = (r["service_date"][:7], r["property_id"])
    for f in OPS_F:
        ops[k][f] += int(r[f])
stay_sold = Counter()
for r in T["pms/actual_stay_nights"]:
    stay_sold[(r["service_date"][:7], r["property_id"], r["stay_status"])] += 1
bad = [k for k in ops if ops[k]["sold_nights"] != stay_sold[(k[0], k[1], "sold")] or ops[k]["complimentary_nights"] != stay_sold[(k[0], k[1], "complimentary")]]
check("Rooms", "Sold and complimentary nights: availability ledger = PMS stay nights", not bad, f"{len(T['pms/actual_stay_nights']):,} stay nights; {len(bad)} month × property differ")
bad = [k for k in ops if ops[k]["available_nights"] != ops[k]["physical_nights"] - ops[k]["out_of_order_nights"] - ops[k]["out_of_service_nights"]]
check("Rooms", "Available = physical − out of order − out of service", not bad, f"{len(T['availability/room_dates']):,} room-dates")

RES = {r["reservation_id"]: r for r in T["pms/reservations"]}

# ------------------------------------------------------------------ folio revenue
FOL = {}
revc = defaultdict(Counter)  # (m, p) -> charge_type -> cents
chan = defaultdict(Counter)  # (m, p, channel) -> metrics
for r in T["night_audit/folio_lines"]:
    FOL[r["folio_line_id"]] = r
    m, p, ct = r["service_date"][:7], r["property_id"], r["charge_type"]
    v = cents(r["net_revenue_usd"])
    revc[(m, p)][ct] += v
    ch = RES[r["reservation_id"]]["channel_id"]
    k = "room" if ct in ("room", "room_credit") else "fees" if ct in ("cancellation_fee", "no_show_fee") else "ancillary"
    chan[(m, p, ch)][k + "_c"] += v
for r in T["pms/actual_stay_nights"]:
    if r["stay_status"] == "sold":
        chan[(r["service_date"][:7], r["property_id"], RES[r["reservation_id"]]["channel_id"])]["sold_nights"] += 1
    else:
        chan[(r["service_date"][:7], r["property_id"], RES[r["reservation_id"]]["channel_id"])]["nonpaid_nights"] += 1
room_comm = defaultdict(int)
for r in T["channel_manager/commissions"]:
    m, p = r["service_date"][:7], r["property_id"]
    v = cents(r["commission_usd"])
    chan[(m, p, r["channel_id"])]["commission_c"] += v
    if FOL[r["folio_line_id"]]["charge_type"] in ("room", "room_credit"):
        room_comm[(m, p)] += v
        chan[(m, p, r["channel_id"])]["room_commission_c"] += v
for r in T["pms/reservations"]:
    m = r["scheduled_checkin_date"][:7]
    if m < MONTHS[0] or m > MONTHS[-1]:
        continue
    k = chan[(m, r["property_id"], r["channel_id"])]
    k["arrivals_scheduled"] += 1
    k["cancelled"] += r["status_as_of_cutoff"] == "cancelled"
    k["no_show"] += r["status_as_of_cutoff"] == "no_show"

# ------------------------------------------------------------------ KPI rows
CONTROL = {(r["service_month"], r["scope_id"]): r for r in csv.DictReader(open(os.path.join(PKG, "validation/monthly_control_totals.csv"), encoding="utf-8-sig"))}
BAL = [("closing_bank_usd", "1000", 1), ("closing_gateway_clearing_usd", "1010", 1), ("closing_cash_transit_usd", "1020", 1), ("closing_corporate_ar_usd", "1100", 1),
       ("closing_ota_ar_usd", "1120", 1), ("closing_vendor_ap_usd", "2000", -1), ("closing_guest_deposits_usd", "2200", -1), ("closing_security_deposits_usd", "2210", -1),
       ("closing_corporate_deposits_usd", "2220", -1), ("closing_hotel_tax_payable_usd", "2100", -1), ("closing_ota_tax_clearing_usd", "2110", -1),
       ("closing_payroll_net_payable_usd", "2300", -1), ("closing_payroll_other_payable_usd", "2310", -1), ("closing_term_debt_usd", "2400", -1)]


def scope_centres(e):
    return CENTRES if e == "COMPANY" else [e]


def control_metrics(m, e):
    pp = scope_centres(e)
    oc = Counter()
    rv = Counter()
    g = Counter()
    b = Counter()
    for p in pp:
        oc.update(ops[(m, p)])
        rv.update(revc[(m, p)])
        for a in COA:
            g[a] += gl.get((m, p, a), 0)
            b[a] += bud.get((m, p, a), 0)
    ac = sum(alloc[(m, p)] for p in pp)
    room = rv["room"] + rv["room_credit"]
    anc = sum(rv[c] for c in ("parking", "breakfast", "cleaning", "late_checkout"))
    fees = rv["cancellation_fee"] + rv["no_show_fee"]
    revenue = room + anc + fees
    expenses = sum(g[a] for a in EXP_ACC)
    ebitda = revenue - expenses + g["5600"] + g["5700"]
    rc = sum(room_comm[(m, p)] for p in pp)
    sold, av, occd = oc["sold_nights"], oc["available_nights"], oc["occupied_nights"]
    hk = sum(g[a] for a in ("5100", "5150", "5200", "5210"))
    brev = sum(v for a, v in b.items() if a in REV_ACC)
    bexp = sum(v for a, v in b.items() if a in EXP_ACC)
    bebitda = brev - bexp + b["5600"] + b["5700"]
    out = {f: oc[f] for f in OPS_F[:8]}
    out.update(net_room_revenue_usd=room, ancillary_revenue_usd=anc, cancellation_no_show_fees_usd=fees, total_revenue_usd=revenue,
               sold_occupancy=f"{Decimal(sold) / av:.8f}" if av else "0.00000000", occupied_occupancy=f"{Decimal(occd) / av:.8f}" if av else "0.00000000",
               adr_usd=f"{Decimal(room) / 100 / sold:.6f}" if sold else "0.000000", revpar_usd=f"{Decimal(room) / 100 / av:.6f}" if av else "0.000000",
               ota_distribution_cost_usd=g["5000"], room_related_ota_commission_usd=rc,
               net_adr_after_ota_commission_usd=f"{Decimal(room - rc) / 100 / sold:.6f}" if sold else "0.000000",
               housekeeping_defined_cost_usd=hk, housekeeping_cost_per_occupied_night_usd=f"{Decimal(hk) / 100 / occd:.6f}" if occd else "0.000000",
               gross_payroll_usd=g["5100"] + g["5110"] + g["5120"], ebitda_before_shared_allocation_usd=ebitda, shared_allocated_cost_usd=ac,
               ebitda_after_shared_allocation_usd=ebitda - ac, net_income_usd=revenue - expenses, original_budget_revenue_usd=brev,
               original_budget_ebitda_usd=bebitda, revenue_bva_usd=revenue - brev, ebitda_bva_usd=ebitda - bebitda, cash_movement_usd=g["1000"])
    for name, acc, sign in BAL:
        out[name] = sign * sum(TB[(m, p, acc)] for p in pp)
    return out


ctrl_fields = [k for k in next(iter(CONTROL.values())).keys() if k not in ("service_month", "scope_id")]
diffs = defaultdict(list)
maxd = defaultdict(int)
for m in MONTHS:
    for e in ["COMPANY"] + PROPS:
        mine = control_metrics(m, e)
        c = CONTROL[(m, e)]
        for f in ctrl_fields:
            a = mine[f]
            if isinstance(a, int) and not f.endswith("_nights"):
                d = abs(a - cents(c[f]))
                maxd[f] = max(maxd[f], d)
                if d:
                    diffs[f].append((m, e))
            else:
                if str(a) != c[f]:
                    diffs[f].append((m, e, a, c[f]))
for f in ctrl_fields:
    unit = "cents" if (f.endswith("_usd") and not any(x in f for x in ("adr", "revpar", "per_occupied"))) else ""
    det = f"96 month × scope comparisons; {len(diffs[f])} differ" + (f"; largest difference {maxd[f]} cents" if unit else "; exact match at published precision")
    area = ("Rooms" if f.endswith("_nights") or "occupancy" in f or f in ("adr_usd", "revpar_usd", "net_adr_after_ota_commission_usd") else
            "Balance sheet" if f.startswith("closing_") or f == "cash_movement_usd" else "Budget" if "budget" in f or "bva" in f else "Revenue" if "revenue" in f or "fees" in f else "P&L")
    check(area, f"{f} matches control totals", not diffs[f], det)

# ------------------------------------------------------------------ extra tie-outs
for m in MONTHS:
    pass
glroom_bad = [(m, p) for m in MONTHS for p in CENTRES if (revc[(m, p)]["room"] + revc[(m, p)]["room_credit"]) != -(gl.get((m, p, "4000"), 0) + gl.get((m, p, "4010"), 0) + gl.get((m, p, "4020"), 0))]
check("Revenue", "Folio net room revenue = GL 4000−4010−4020 by month and property", not glroom_bad, f"{len(T['night_audit/folio_lines']):,} folio lines; {len(glroom_bad)} differ")
bank_bad = [r["service_month"] for r in T["bank/monthly_balances"] if cents(r["closing_balance_usd"]) != sum(TB[(r["service_month"], p, "1000")] for p in CENTRES)]
check("Cash", "Bank statement month-end balance = GL operating bank", not bank_bad, f"24 month-ends; {len(bank_bad)} differ")
stm = defaultdict(int)
for r in T["bank/statement"]:
    stm[r["posted_date"][:7]] += cents(r["signed_amount_usd"])
mb = {r["service_month"]: r for r in T["bank/monthly_balances"]}
bad = [m for m in MONTHS if stm[m] != cents(mb[m]["credits_usd"]) - cents(mb[m]["debits_usd"])]
check("Cash", "Bank transactions sum to monthly statement flows", not bad, f"{len(T['bank/statement']):,} bank transactions; {len(bad)} months differ")
mk = defaultdict(int)
for r in T["marketing/daily_campaigns"]:
    mk[(r["metric_date"][:7], r["property_id"])] += cents(r["spend_usd"])
bad = [(m, p) for m in MONTHS for p in PROPS if mk[(m, p)] != gl.get((m, p, "5400"), 0)]
check("Marketing", "Daily ad spend = GL own advertising 5400 (one expense)", not bad, f"{len(T['marketing/daily_campaigns']):,} campaign-days; {len(bad)} month × property differ")
inv_open = sum(cents(r["open_ar_usd"]) for r in T["corporate_billing/invoices"])
check("Corporate AR", "Open invoices = GL corporate AR 1100 at cutoff", inv_open == sum(TB[(CUT[:7], p, "1100")] for p in CENTRES), f"{sum(1 for r in T['corporate_billing/invoices'] if cents(r['open_ar_usd']))} open invoices, ${inv_open / 100:,.2f}")
bad = [r["invoice_id"] for r in T["corporate_billing/invoices"] if cents(r["total_usd"]) != cents(r["prepayment_applied_usd"]) + cents(r["cash_applied_usd"]) + cents(r["open_ar_usd"])]
check("Corporate AR", "Each invoice: total = prepayment + cash applied + open", not bad, f"{len(T['corporate_billing/invoices'])} invoices; {len(bad)} differ")
ap_open = sum(cents(r["open_ap_usd"]) for r in T["quickbooks/bills"])
check("Payables", "Open bills = GL vendor AP 2000 at cutoff", ap_open == -sum(TB[(CUT[:7], p, "2000")] for p in CENTRES), f"{sum(1 for r in T['quickbooks/bills'] if cents(r['open_ap_usd']))} open bills, ${ap_open / 100:,.2f}")

# ------------------------------------------------------------------ housekeeping & labor
hk = defaultdict(Counter)
for r in T["operations/housekeeping_tasks"]:
    k = hk[(r["service_date"][:7], r["property_id"])]
    k["tasks"] += 1
    k[r["task_type"]] += 1
    k["approved_minutes"] += int(r["approved_work_minutes"])
    k["linen_sets"] += int(r["linen_sets"])
    k["agency_tasks"] += 1 if r["contractor_vendor_id"] else 0
for r in T["operations/agency_shifts"]:
    k = hk[(r["work_date"][:7], r["property_id"])]
    k["agency_minutes"] += int(r["approved_minutes"])
    k["agency_shifts"] += 1
    k["agency_worker_days"] += int(r["worker_count"])
EMP = {r["employee_id"]: r for r in T["gusto/employees"]}
for r in T["gusto/time_entries"]:
    k = hk[(r["work_date"][:7], r["property_id"])]
    k["paid_minutes"] += int(r["total_minutes"])
    k["overtime_minutes"] += int(r["overtime_minutes"])
    k["absence_minutes"] += int(r["absence_minutes"])
    if EMP[r["employee_id"]]["role"] == "housekeeper":
        k["hk_paid_minutes"] += int(r["total_minutes"])
        k["hk_overtime_minutes"] += int(r["overtime_minutes"])
        k["hk_approved_minutes"] += int(r["approved_housekeeping_minutes"])

funnel = defaultdict(Counter)
for r in T["marketing/direct_funnel"]:
    k = funnel[(r["metric_date"][:7], r["property_id"])]
    for f in ("sessions", "availability_searches", "checkout_starts", "confirmed_reservations"):
        k[f] += int(r[f])

kpi_rows = []
for m in MONTHS:
    for e in ENTS:
        pp = scope_centres(e)
        c = control_metrics(m, e)
        g = lambda a: sum(pnl_val(m, p, a) for p in pp)
        b = lambda a: sum(bud.get((m, p, a), 0) for p in pp)
        h = Counter()
        f = Counter()
        cm = Counter()
        for p in pp:
            h.update(hk[(m, p)])
            f.update(funnel[(m, p)])
            for ch in CH_NAMES:
                for kk, vv in chan[(m, p, ch)].items():
                    cm[ch + ":" + kk] += vv
        plan = [room_plan.get((m, p)) for p in pp if room_plan.get((m, p))]
        b_sold = sum(int(x["planned_sold_nights"]) for x in plan)
        b_avail = sum(int(x["available_nights"]) for x in plan)
        b_room = sum(cents(x["planned_net_room_revenue_usd"]) for x in plan)
        lab = sum(g(a) for a in ("5100", "5110", "5120", "5130", "5140", "5150"))
        opex_b = c["total_revenue_usd"] - c["ebitda_before_shared_allocation_usd"]
        row = {"period": m, "fy": fy(m), "entity": e, "name": SHORT[e],
               "physical_nights": c["physical_nights"], "available_nights": c["available_nights"], "sold_nights": c["sold_nights"],
               "complimentary_nights": c["complimentary_nights"], "house_use_nights": c["house_use_nights"], "occupied_nights": c["occupied_nights"],
               "out_of_order_nights": c["out_of_order_nights"], "out_of_service_nights": c["out_of_service_nights"],
               "net_room_revenue": usd(c["net_room_revenue_usd"]), "ancillary_revenue": usd(c["ancillary_revenue_usd"]), "fee_revenue": usd(c["cancellation_no_show_fees_usd"]),
               "total_revenue": usd(c["total_revenue_usd"]), "occupancy": round(c["sold_nights"] / c["available_nights"], 6) if c["available_nights"] else None,
               "adr": round(c["net_room_revenue_usd"] / 100 / c["sold_nights"], 2) if c["sold_nights"] else None,
               "revpar": round(c["net_room_revenue_usd"] / 100 / c["available_nights"], 2) if c["available_nights"] else None,
               "trevpar": round(c["total_revenue_usd"] / 100 / c["available_nights"], 2) if c["available_nights"] else None,
               "ota_commission": usd(c["ota_distribution_cost_usd"]), "room_ota_commission": usd(c["room_related_ota_commission_usd"]),
               "processing_fees": usd(g("5010")), "own_advertising": usd(g("5400")), "labor": usd(lab), "gross_payroll": usd(c["gross_payroll_usd"]),
               "housekeeping_cost": usd(c["housekeeping_defined_cost_usd"]), "rent": usd(g("5320")), "utilities": usd(g("5310")), "maintenance": usd(g("5300")),
               "opex": usd(opex_b), "ebitda": usd(c["ebitda_before_shared_allocation_usd"]), "shared_allocated": usd(c["shared_allocated_cost_usd"]),
               "ebitda_after_shared": usd(c["ebitda_after_shared_allocation_usd"]), "depreciation": usd(g("5600")), "interest": usd(g("5700")),
               "net_income": usd(c["net_income_usd"]), "budget_total_revenue": usd(c["original_budget_revenue_usd"]), "budget_ebitda": usd(c["original_budget_ebitda_usd"]),
               "budget_net_room_revenue": usd(sum(b(a) for a in ("4000", "4010", "4020"))), "budget_sold_nights": b_sold, "budget_available_nights": b_avail,
               "budget_occupancy": round(b_sold / b_avail, 6) if b_avail else None, "budget_adr": round(b_room / 100 / b_sold, 2) if b_sold else None,
               "budget_net_income": usd(sum(b(a) for a in REV_ACC) - sum(b(a) for a in EXP_ACC)),
               "hk_tasks": h["tasks"], "hk_departures": h["departure"], "hk_stayovers": h["stayover"] + h["weekly_stayover"], "hk_approved_minutes": h["approved_minutes"],
               "agency_minutes": h["agency_minutes"], "agency_worker_days": h["agency_worker_days"], "agency_cost": usd(g("5150")), "laundry_cost": usd(g("5200")), "consumables_cost": usd(g("5210")),
               "paid_hours": round(h["paid_minutes"] / 60, 1), "overtime_hours": round(h["overtime_minutes"] / 60, 1), "hk_paid_hours": round(h["hk_paid_minutes"] / 60, 1),
               "hk_overtime_hours": round(h["hk_overtime_minutes"] / 60, 1),
               "web_sessions": f["sessions"], "web_searches": f["availability_searches"], "web_checkouts": f["checkout_starts"], "web_bookings": f["confirmed_reservations"],
               "direct_sold_nights": cm["DIRECT:sold_nights"], "agency_sold_nights": cm["BOOKING:sold_nights"], "merchant_sold_nights": cm["EXPEDIA:sold_nights"], "corporate_sold_nights": cm["CORPORATE:sold_nights"],
               "arrivals_scheduled": sum(cm[ch + ":arrivals_scheduled"] for ch in CH_NAMES), "cancelled": sum(cm[ch + ":cancelled"] for ch in CH_NAMES), "no_shows": sum(cm[ch + ":no_show"] for ch in CH_NAMES)}
        for name, acc, sign in BAL:
            row[name.replace("closing_", "").replace("_usd", "")] = usd(c[name])
        kpi_rows.append(row)
# channel sold nights add up
bad = [(r["period"], r["entity"]) for r in kpi_rows if r["direct_sold_nights"] + r["agency_sold_nights"] + r["merchant_sold_nights"] + r["corporate_sold_nights"] != r["sold_nights"]]
check("Channels", "Sold nights by channel add up to sold nights", not bad, f"120 month × entity rows; {len(bad)} differ")
bad = [(m, p) for m in MONTHS for p in PROPS if sum(chan[(m, p, ch)]["room_c"] for ch in CH_NAMES) != revc[(m, p)]["room"] + revc[(m, p)]["room_credit"]]
check("Channels", "Net room revenue by channel adds up to property total", not bad, f"72 month × property; {len(bad)} differ")

# ------------------------------------------------------------------ P&L dataset
GROUP = {"rooms": "Rooms", "ancillary": "Ancillary", "fees": "Fees"}
EXPG = {"5000": "Distribution", "5010": "Distribution", "5400": "Marketing", "5100": "Housekeeping", "5150": "Housekeeping", "5200": "Housekeeping", "5210": "Housekeeping",
        "5110": "Labor", "5130": "Labor", "5140": "Labor", "5120": "Corporate", "5500": "Corporate", "5220": "Operating", "5300": "Operating", "5310": "Operating",
        "5340": "Operating", "5320": "Rent & property", "5330": "Rent & property", "5600": "Depreciation", "5700": "Interest"}
pnl_rows = []
for m in MONTHS:
    for e in ENTS:
        pp = scope_centres(e)
        for a in REV_ACC + EXP_ACC:
            act = sum(pnl_val(m, p, a) for p in pp)
            bu = sum(bud.get((m, p, a), 0) for p in pp)
            al = sum(alloc_acc.get((m, p, a), 0) for p in pp)
            if act == 0 and bu == 0 and al == 0:
                continue
            grp = GROUP.get(COA[a]["report_group"], "Revenue") if a in REV_ACC else EXPG[a]
            pnl_rows.append({"period": m, "fy": fy(m), "entity": e, "account_id": a, "line": COA[a]["account_name"], "group": "Revenue" if a in REV_ACC else grp,
                             "revenue_group": GROUP.get(COA[a]["report_group"]) if a in REV_ACC else None, "account_type": COA[a]["account_type"],
                             "actual": usd(act), "budget": usd(bu), "allocated_shared": usd(al)})
bad = [(r["period"], r["entity"]) for r in kpi_rows if abs(sum(x["actual"] * (1 if x["group"] == "Revenue" else -1) for x in pnl_rows if x["period"] == r["period"] and x["entity"] == r["entity"]) - r["net_income"]) > 0.005]
check("P&L", "P&L lines rebuild net income for every month × entity", not bad, f"{len(pnl_rows):,} lines; {len(bad)} differ")

# ------------------------------------------------------------------ channels dataset
channel_rows = []
for (m, p, ch), v in sorted(chan.items()):
    if m not in MONTHS or p not in PROPS:
        continue
    channel_rows.append({"period": m, "fy": fy(m), "property_id": p, "channel": ch, "channel_name": CH_NAMES[ch], "sold_nights": v["sold_nights"],
                         "comp_house_nights": v["nonpaid_nights"], "net_room_revenue_usd": usd(v["room_c"]), "ancillary_usd": usd(v["ancillary_c"]), "fees_usd": usd(v["fees_c"]),
                         "commission_usd": usd(v["commission_c"]), "room_commission_usd": usd(v["room_commission_c"]),
                         "arrivals_scheduled": v["arrivals_scheduled"], "cancelled": v["cancelled"], "no_shows": v["no_show"]})

# ------------------------------------------------------------------ corporate accounts
COMP = {r["company_id"]: r for r in T["corporate_billing/companies"]}
CLIENT = {cid: f"Corporate client {cid[-1]}" for cid in sorted(COMP)}
invoices = []
for r in T["corporate_billing/invoices"]:
    invoices.append({"invoice_id": r["invoice_id"], "company_id": r["company_id"], "client": CLIENT[r["company_id"]], "property_id": r["property_id"], "service_month": r["service_month"],
                     "invoice_date": r["invoice_date"], "due_date": r["due_date"], "total_usd": usd(cents(r["total_usd"])), "prepayment_applied_usd": usd(cents(r["prepayment_applied_usd"])),
                     "cash_applied_usd": usd(cents(r["cash_applied_usd"])), "open_ar_usd": usd(cents(r["open_ar_usd"])), "days_past_due": int(r["days_past_due_at_cutoff"] or 0),
                     "aging_bucket": r["aging_bucket"], "expected_collection_date": r["expected_collection_date"]})
# days-to-pay: cash-weighted receipt date minus due date per invoice (fully paid only)
rcp = {r["receipt_id"]: r for r in T["corporate_billing/receipts"]}
pay = defaultdict(list)
for a in T["corporate_billing/receipt_applications"]:
    if a["application_type"] != "prepayment" and a["receipt_id"]:
        pay[a["invoice_id"]].append((a["application_date"], cents(a["amount_usd"])))
corp_rows = []
agg = defaultdict(lambda: Counter())
for r in T["corporate_billing/invoices"]:
    k = agg[(r["invoice_date"][:7], r["company_id"])]
    k["invoiced_c"] += cents(r["total_usd"])
    k["prepay_c"] += cents(r["prepayment_applied_usd"])
    if cents(r["open_ar_usd"]) == 0 and pay[r["invoice_id"]]:
        last = max(d for d, _ in pay[r["invoice_id"]])
        k["paid_invoices"] += 1
        k["days_late_sum"] += (D(last) - D(r["due_date"])).days
        k["days_to_pay_sum"] += (D(last) - D(r["invoice_date"])).days
for r in T["corporate_billing/receipts"]:
    agg[(r["receipt_date"][:7], r["company_id"])]["receipts_c"] += cents(r["amount_usd"])
for r in T["corporate_billing/prepayments"]:
    d = r.get("received_date") or r.get("receipt_date") or r.get("payment_date") or ""
    if d:
        agg[(d[:7], r["company_id"])]["advances_c"] += cents(r.get("amount_usd") or "0")
for (m, cid), v in sorted(agg.items()):
    if m not in MONTHS:
        continue
    corp_rows.append({"period": m, "fy": fy(m), "company_id": cid, "client": CLIENT[cid], "invoiced_usd": usd(v["invoiced_c"]), "prepayment_applied_usd": usd(v["prepay_c"]),
                      "receipts_usd": usd(v["receipts_c"]), "advances_usd": usd(v["advances_c"]), "paid_invoices": v["paid_invoices"],
                      "avg_days_late": round(v["days_late_sum"] / v["paid_invoices"], 1) if v["paid_invoices"] else None,
                      "avg_days_to_pay": round(v["days_to_pay_sum"] / v["paid_invoices"], 1) if v["paid_invoices"] else None})
companies = [{"company_id": cid, "client": CLIENT[cid], "credit_limit_usd": usd(cents(COMP[cid]["credit_limit_usd"])),
              "payment_terms_days": 45 if cid == "CO-001" else 30} for cid in sorted(COMP)]
corp_sold = Counter()
corp_room = Counter()
for r in T["pms/actual_stay_nights"]:
    cid = RES[r["reservation_id"]]["company_id"]
    if cid and r["stay_status"] == "sold":
        corp_sold[(r["service_date"][:7], cid)] += 1
for r in T["night_audit/folio_lines"]:
    cid = RES[r["reservation_id"]]["company_id"]
    if cid and r["charge_type"] in ("room", "room_credit"):
        corp_room[(r["service_date"][:7], cid)] += cents(r["net_revenue_usd"])
for x in corp_rows:
    x["sold_nights"] = corp_sold[(x["period"], x["company_id"])]
    x["net_room_revenue_usd"] = usd(corp_room[(x["period"], x["company_id"])])

# ------------------------------------------------------------------ marketing
mkt = defaultdict(Counter)
for r in T["marketing/daily_campaigns"]:
    k = mkt[(r["metric_date"][:7], r["property_id"], r["platform"])]
    k["spend_c"] += cents(r["spend_usd"])
    k["impressions"] += int(r["impressions"])
    k["clicks"] += int(r["clicks"])
    k["attr_bookings"] += float(r["attributed_bookings"])
    k["attr_value_c"] += cents(r["attributed_booking_value_usd"])
ads_rows = [{"period": m, "fy": fy(m), "property_id": p, "platform": pl, "spend_usd": usd(v["spend_c"]), "impressions": v["impressions"], "clicks": v["clicks"],
             "attributed_bookings": round(v["attr_bookings"], 1), "attributed_value_usd": usd(v["attr_value_c"])} for (m, p, pl), v in sorted(mkt.items()) if m in MONTHS]

# ------------------------------------------------------------------ bank
bank_rows = [{"period": r["service_month"], "opening_usd": usd(cents(r["opening_balance_usd"])), "inflows_usd": usd(cents(r["credits_usd"])), "outflows_usd": usd(cents(r["debits_usd"])),
              "closing_usd": usd(cents(r["closing_balance_usd"]))} for r in T["bank/monthly_balances"]]
btype = defaultdict(Counter)
for r in T["bank/statement"]:
    k = btype[(r["posted_date"][:7], r["transaction_type"])]
    k["n"] += 1
    k["in"] += cents(r["credit_usd"])
    k["out"] += cents(r["debit_usd"])
bank_type_rows = [{"period": m, "transaction_type": t, "transactions": v["n"], "inflows_usd": usd(v["in"]), "outflows_usd": usd(v["out"])} for (m, t), v in sorted(btype.items())]

# ------------------------------------------------------------------ on the books (forward view)
otb = defaultdict(Counter)
for r in T["planning/on_books_nights"]:
    k = otb[(r["service_date"][:7], r["property_id"])]
    if r["is_sold_commitment"] == "true":
        k["sold"] += 1
        k["room_c"] += cents(r["booked_room_usd"])
        k[r["channel_id"]] += 1
    else:
        k["other"] += 1
fcap = defaultdict(Counter)
for r in T["planning/future_capacity"]:
    fcap[(r["service_date"][:7], r["property_id"])]["avail"] += int(r["available_nights"])
otb_rows = []
for (m, p) in sorted(fcap):
    v = otb[(m, p)]
    ly = f"{int(m[:4]) - 1}{m[4:]}"
    lyo = ops.get((ly, p), Counter())
    otb_rows.append({"period": m, "property_id": p, "available_nights": fcap[(m, p)]["avail"], "otb_sold_nights": v["sold"], "otb_comp_house_nights": v["other"],
                     "otb_room_revenue_usd": usd(v["room_c"]), "otb_occupancy": round(v["sold"] / fcap[(m, p)]["avail"], 4),
                     "otb_direct": v["DIRECT"], "otb_agency": v["BOOKING"], "otb_merchant": v["EXPEDIA"], "otb_corporate": v["CORPORATE"],
                     "ly_sold_nights": lyo["sold_nights"], "ly_occupancy": round(lyo["sold_nights"] / lyo["available_nights"], 4) if lyo["available_nights"] else None,
                     "ly_adr": round((revc[(ly, p)]["room"] + revc[(ly, p)]["room_credit"]) / 100 / lyo["sold_nights"], 2) if lyo["sold_nights"] else None})

# ------------------------------------------------------------------ 13-week cash
W0 = date(2026, 11, 1)
WEND = date(2027, 1, 30)
TAXR = {r["property_id"]: Decimal(r["lodging_tax_rate"]) for r in T["night_audit/tax_policies"]}
VTERMS = {r["vendor_id"]: int(r["payment_terms_days"]) for r in T["procurement/vendors"]}
INV = {r["invoice_id"]: r for r in T["corporate_billing/invoices"]}
cash = []
beyond = Counter()


def wk(d):
    return (d - W0).days // 7


def add(d, prop, direction, cat, ctype, amt_c, source, source_id, basis, company=""):
    if amt_c == 0:
        return
    if d > WEND:
        beyond[ctype] += amt_c
        return
    if d < W0:
        d = W0
    cash.append({"id": "", "week_index": wk(d), "expected_cash_date": d.isoformat(), "property_id": prop, "direction": direction, "category": cat,
                 "commitment_type": ctype, "amount_usd": usd(amt_c), "source": source, "source_id": source_id, "basis": basis, "company_id": company})


KMAP = {"open_corporate_ar": ("corporate", "OPEN_CORPORATE_AR"), "earned_ota_net_remittance": ("settlements", "OTA_NET_REMITTANCE"),
        "gateway_transit": ("settlements", "GATEWAY_IN_TRANSIT"), "gateway_unreleased_balance": ("settlements", "GATEWAY_UNRELEASED"),
        "earned_unfunded_payroll": ("payroll", "EARNED_PAYROLL_OCT_H2"), "hotel_lodging_tax": ("tax", "LODGING_TAX_OCT"),
        "agency_commission": ("tax", "AGENCY_COMMISSION_OCT"), "open_vendor_ap": ("vendors", "OPEN_AP"), "scheduled_debt_service": ("debt", "DEBT_SERVICE"),
        "security_return": ("capex", "SECURITY_RETURN"), "unreceived_capex": ("capex", "CAPEX_PO")}
known_tot = Counter()
for r in T["planning/known_cash_inputs"]:
    cat, ct = KMAP[r["input_type"]]
    a = cents(r["amount_usd"])
    known_tot[r["input_type"]] += a
    company = INV[r["source_id"]]["company_id"] if r["input_type"] == "open_corporate_ar" else ""
    add(bday(D(r["expected_cash_date"])), r["property_id"], "IN" if r["direction"] == "in" else "OUT", cat, ct, a, r["source_table"], r["source_id"], "KNOWN", company)
# tie the copy/index to primary balances (index used instead of source tables, never both)
tb = lambda acc: sum(TB[(CUT[:7], p, acc)] for p in CENTRES)
for typ, acc, sign in [("open_corporate_ar", "1100", 1), ("open_vendor_ap", "2000", -1), ("hotel_lodging_tax", "2100", -1), ("security_return", "2210", -1), ("gateway_unreleased_balance", "1010", 1)]:
    check("13-week cash", f"Known cash input {typ} = GL {acc} at cutoff", known_tot[typ] == sign * tb(acc), f"${known_tot[typ] / 100:,.2f}")
check("13-week cash", "Known payroll funding = GL 2300 + 2310 at cutoff", known_tot["earned_unfunded_payroll"] == -(tb("2300") + tb("2310")), f"${known_tot['earned_unfunded_payroll'] / 100:,.2f}")

# booked stays (on the books) — guest/agency via gateway, corporate by invoice tranches
GW_RATE, GW_FIX = Decimal("0.0275"), 25


def gateway_bank_date(d):
    d = add_bdays(d, 2)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return add_bdays(d, 1)


otb_tax = defaultdict(int)
otb_agency = defaultdict(int)
otb_sold_m = defaultdict(int)
for r in T["planning/booked_payment_terms"]:
    inc = cents(r["incremental_guest_collect_usd"])
    if inc <= 0:
        continue
    if r["collection_model"] in ("hotel_collect", "agency"):
        first = int((Decimal(inc) * Decimal(r["first_tranche_share"])).to_integral_value())
        for t, dd, amt in ((1, r["expected_first_collect_date"], first), (2, r["expected_collect_date"], inc - first)):
            if amt:
                fee = int((Decimal(amt) * GW_RATE).to_integral_value()) + GW_FIX
                add(gateway_bank_date(D(dd)), r["property_id"], "IN", "booked", "OTB_GUEST_RECEIPTS", amt - fee, "planning/booked_payment_terms", f"{r['reservation_id']}/{r['service_month']}/T{t}", "BOOKED")
    elif r["collection_model"] == "invoice":
        first = int((Decimal(inc) * Decimal(r["first_tranche_share"])).to_integral_value())
        add(bday(D(r["expected_first_collect_date"])), r["property_id"], "IN", "corporate", "OTB_CORPORATE_65", first, "planning/booked_payment_terms", f"{r['reservation_id']}/{r['service_month']}", "BOOKED", r["company_id"])
        add(bday(D(r["expected_collect_date"])), r["property_id"], "IN", "corporate", "OTB_CORPORATE_35", inc - first, "planning/booked_payment_terms", f"{r['reservation_id']}/{r['service_month']}", "BOOKED", r["company_id"])
assump = {(r["week_id"], r["property_id"]): r for r in T["planning/incremental_demand_assumptions"]}
A0 = {p: assump[("FW-01", p)] for p in PROPS}
merch = defaultdict(int)
for r in T["planning/on_books_nights"]:
    if r["is_sold_commitment"] != "true":
        continue
    sd = D(r["service_date"])
    m = r["service_date"][:7]
    room = cents(r["booked_room_usd"])
    otb_sold_m[(m, r["property_id"])] += 1
    if r["collection_model"] == "merchant":
        rate = Decimal(A0[r["property_id"]]["merchant_commission_rate"])
        sat = sd + timedelta(days=(5 - sd.weekday()) % 7) + timedelta(days=7)
        merch[(add_bdays(sat, 1), r["property_id"])] += room - int((Decimal(room) * rate).to_integral_value())
    else:
        otb_tax[(m, r["property_id"])] += cents(r["booked_lodging_tax_usd"])
        if r["collection_model"] == "agency":
            otb_agency[(m, r["property_id"])] += int((Decimal(room) * Decimal(A0[r["property_id"]]["agency_commission_rate"])).to_integral_value())
for (d, p), a in sorted(merch.items()):
    add(d, p, "IN", "booked", "OTB_MERCHANT_NET", a, "planning/on_books_nights", f"{p}-merchant-{d.isoformat()}", "BOOKED")
for (m, p), a in sorted(otb_tax.items()):
    add(bday(month_end(m) + timedelta(days=20)), p, "OUT", "tax", "OTB_LODGING_TAX", a, "planning/on_books_nights", f"{p}-{m}-tax", "BOOKED")
for (m, p), a in sorted(otb_agency.items()):
    add(bday(month_end(m) + timedelta(days=15)), p, "OUT", "tax", "OTB_AGENCY_COMMISSION", a, "planning/on_books_nights", f"{p}-{m}-agency", "BOOKED")

# new bookings beyond OTB (assumption version FC-2026-10-31-BASE)
weeks = T["planning/forecast_weeks"]
fc_day = {(r["property_id"], r["service_date"]): int(r["available_nights"]) for r in T["planning/future_capacity"]}
otb_day = Counter()
otb_all_day = Counter()
for r in T["planning/on_books_nights"]:
    otb_all_day[(r["property_id"], r["service_date"])] += 1
    if r["is_sold_commitment"] == "true":
        otb_day[(r["property_id"], r["service_date"])] += 1
new_nights = Counter()
new_month = defaultdict(Counter)
demand_rows = []
for w in weeks:
    ws, we = D(w["week_start_date"]), D(w["week_end_date"])
    for p in PROPS:
        a = assump[(w["week_id"], p)]
        days = [(ws + timedelta(days=i)).isoformat() for i in range(7)]
        avail = sum(fc_day[(p, d)] for d in days)
        sold = sum(otb_day[(p, d)] for d in days)
        occd = sum(otb_all_day[(p, d)] for d in days)
        n = max(0, min(round(Decimal(a["target_total_sold_occupancy"]) * avail - sold), avail - occd))
        adr = cents(a["target_new_booking_adr_usd"])
        demand_rows.append({"week_id": w["week_id"], "week_start": w["week_start_date"], "property_id": p, "available_nights": avail, "otb_sold_nights": sold,
                            "target_occupancy": float(a["target_total_sold_occupancy"]), "new_nights": n, "new_adr_usd": usd(adr), "new_room_revenue_usd": usd(n * adr),
                            "assumption_version": a["assumption_version"]})
        if not n:
            continue
        mid = ws + timedelta(days=3)
        rev = n * adr
        tax = Decimal(a["lodging_tax_rate"])
        mix = {k: Decimal(a[k + "_mix"]) for k in ("direct", "agency", "merchant", "corporate")}
        gw = int((Decimal(rev) * (mix["direct"] + mix["agency"]) * (1 + tax)).to_integral_value())
        add(gateway_bank_date(mid), p, "IN", "new", "NEW_DIRECT_AGENCY", gw - int((Decimal(gw) * Decimal(a["gateway_percent_rate"])).to_integral_value()), "planning/incremental_demand_assumptions", f"{w['week_id']}-{p}", "ESTIMATE")
        sat = ws + timedelta(days=6 + 7)
        add(add_bdays(sat, 1), p, "IN", "new", "NEW_MERCHANT_NET", int((Decimal(rev) * mix["merchant"] * (1 - Decimal(a["merchant_commission_rate"]))).to_integral_value()), "planning/incremental_demand_assumptions", f"{w['week_id']}-{p}", "ESTIMATE")
        mm = mid.isoformat()[:7]
        add(bday(month_end(mm) + timedelta(days=int(a["corporate_collection_days"]))), p, "IN", "new", "NEW_CORPORATE", int((Decimal(rev) * mix["corporate"] * (1 + tax)).to_integral_value()), "planning/incremental_demand_assumptions", f"{w['week_id']}-{p}", "ESTIMATE")
        new_month[(mm, p)]["tax"] += int((Decimal(rev) * (1 - mix["merchant"]) * tax).to_integral_value())
        new_month[(mm, p)]["agency"] += int((Decimal(rev) * mix["agency"] * Decimal(a["agency_commission_rate"])).to_integral_value())
        new_month[(mm, p)]["nights"] += n
        new_nights[p] += n
for (m, p), v in sorted(new_month.items()):
    add(bday(month_end(m) + timedelta(days=20)), p, "OUT", "tax", "NEW_LODGING_TAX", v["tax"], "planning/incremental_demand_assumptions", f"{p}-{m}", "ESTIMATE")
    add(bday(month_end(m) + timedelta(days=15)), p, "OUT", "tax", "NEW_AGENCY_COMMISSION", v["agency"], "planning/incremental_demand_assumptions", f"{p}-{m}", "ESTIMATE")
    a = A0[p]
    add(bday(month_end(m) + timedelta(days=VTERMS["VEN-LAUNDRY"])), p, "OUT", "variable", "NEW_LAUNDRY", v["nights"] * cents(a["variable_laundry_cost_per_sold_night_usd"]), "planning/incremental_demand_assumptions", f"{p}-{m}", "ESTIMATE")
    add(bday(month_end(m) + timedelta(days=VTERMS["VEN-SUPPLY"])), p, "OUT", "variable", "NEW_CONSUMABLES", v["nights"] * cents(a["variable_consumables_per_sold_night_usd"]), "planning/incremental_demand_assumptions", f"{p}-{m}", "ESTIMATE")

# operating run costs for Nov-Jan service months (October bills are already in open AP)
FUT = ["2026-11", "2026-12", "2027-01"]
for m in FUT:
    for p in PROPS:
        a = A0[p]
        add(bday(month_end(m) + timedelta(days=VTERMS["VEN-UTIL"])), p, "OUT", "variable", "UTILITIES", cents(a["utilities_monthly_base_usd"]), "planning/incremental_demand_assumptions", f"{p}-{m}-util", "ESTIMATE")
        add(bday(month_end(m) + timedelta(days=VTERMS["VEN-MAINT"])), p, "OUT", "variable", "MAINTENANCE", cents(a["maintenance_monthly_base_usd"]), "planning/incremental_demand_assumptions", f"{p}-{m}-maint", "ESTIMATE")
        n = otb_sold_m[(m, p)]
        add(bday(month_end(m) + timedelta(days=VTERMS["VEN-LAUNDRY"])), p, "OUT", "variable", "OTB_LAUNDRY", n * cents(a["variable_laundry_cost_per_sold_night_usd"]), "planning/on_books_nights", f"{p}-{m}-laundry", "BOOKED")
        add(bday(month_end(m) + timedelta(days=VTERMS["VEN-SUPPLY"])), p, "OUT", "variable", "OTB_CONSUMABLES", n * cents(a["variable_consumables_per_sold_night_usd"]), "planning/on_books_nights", f"{p}-{m}-supply", "BOOKED")
        # breakfast food and own advertising: trailing 3-month average of billed cost (same payment terms)
        for acc, ven, ct in (("5220", "VEN-FOOD", "BREAKFAST_FOOD"), ("5400", "VEN-META", "OWN_ADVERTISING")):
            avg = sum(pnl_val(x, p, acc) for x in MONTHS[-3:]) // 3
            add(bday(month_end(m) + timedelta(days=VTERMS[ven])), p, "OUT", "variable", ct, avg, "quickbooks/general_ledger", f"{p}-{acc}-trailing3", "ESTIMATE")
for r in T["planning/recurring_contracts"]:
    m = r["next_service_month"]
    while m <= FUT[-1]:
        amt = Decimal(r["base_monthly_usd"])
        if r["escalation_from"] and m >= r["escalation_from"][:7]:
            amt *= 1 + Decimal(r["escalation_rate"])
        if r["account_code"] == "5320":
            due = date(int(m[:4]), int(m[5:]), 1)
        else:
            due = month_end(m) + timedelta(days=VTERMS[r["vendor_id"]])
        add(bday(due), r["property_id"], "OUT", "vendors", "RECURRING_CONTRACT", cents(str(amt.quantize(Decimal("0.01")))), "planning/recurring_contracts", f"{r['recurring_contract_id']}-{m}", "CONTRACT")
        m = next_month(m)

# future payroll from active employees, effective rates and the calendar assumptions
comp = defaultdict(list)
for r in T["gusto/compensation_history"]:
    comp[r["employee_id"]].append(r)
pay_check = []
for cal in T["planning/future_payroll_calendar"]:
    s, e = D(cal["period_start_date"]), D(cal["period_end_date"])
    days = (e - s).days + 1
    by_prop = Counter()
    for emp in T["gusto/employees"]:
        if emp["termination_date"] and emp["termination_date"] < cal["period_start_date"]:
            continue
        rate = [c for c in comp[emp["employee_id"]] if c["effective_from"] <= cal["period_start_date"] <= c["effective_through"]][0]
        if emp["pay_type"] == "hourly":
            hrs = Decimal(cal["hourly_regular_weekly_hours"] if emp["role"] == "housekeeper" else cal["other_hourly_weekly_hours"]) * days / 7
            gross = Decimal(rate["hourly_rate_usd"]) * hrs + Decimal(rate["hourly_rate_usd"]) * Decimal("1.5") * Decimal(cal["assumed_overtime_weekly_hours"]) * days / 7
        else:
            gross = Decimal(rate["annual_salary_usd"]) / 24
        cost = gross * (1 + Decimal(cal["employer_tax_rate"])) + Decimal(cal["benefit_per_employee_halfmonth_usd"])
        by_prop[emp["home_property_id"]] += int((cost * 100).to_integral_value())
    for p, a in sorted(by_prop.items()):
        add(bday(D(cal["scheduled_funding_date"])), p, "OUT", "payroll", "FUTURE_PAYROLL", a, "planning/future_payroll_calendar", f"{cal['forecast_payroll_id']}-{p}", "ESTIMATE")
    pay_check.append((cal["forecast_payroll_id"], sum(by_prop.values())))
last_actual = cents([r for r in T["gusto/payroll_runs"]][-1]["total_employer_cost_usd"])
check("13-week cash", "Future payroll cycle within 10% of last earned cycle", all(abs(a - last_actual) <= last_actual * 0.10 for _, a in pay_check),
      f"last earned cycle ${last_actual / 100:,.0f}; generated cycles " + ", ".join(f"${a / 100:,.0f}" for _, a in pay_check))

for i, r in enumerate(sorted(cash, key=lambda x: (x["week_index"], x["direction"], x["category"], -x["amount_usd"]))):
    r["id"] = f"CF-{i + 1:04d}"
cash.sort(key=lambda x: x["id"])
opening = tb("1000")
ids = Counter((r["commitment_type"], r["source_id"], r["expected_cash_date"]) for r in cash)
dups = [k for k, v in ids.items() if v > 1]
check("13-week cash", "Each commitment enters the forecast once", not dups, f"{len(cash)} lines in 13 weeks; {sum(beyond.values()) / 100:,.0f} USD dated after 30 Jan 2027 kept out")
otb_terms = sum(cents(r["future_booked_charges_usd"]) for r in T["planning/booked_payment_terms"] if r["collection_model"] != "merchant")
otb_nights = sum(cents(r["booked_room_usd"]) + cents(r["booked_lodging_tax_usd"]) for r in T["planning/on_books_nights"] if r["collection_model"] != "merchant" and r["is_sold_commitment"] == "true")
held = sum(cents(r["existing_advance_cover_usd"]) for r in T["planning/booked_payment_terms"])
check("13-week cash", "Held guest and corporate advances are not collected again", held == -(tb("2200") + tb("2220")) or held <= -(tb("2200") + tb("2220")),
      f"${held / 100:,.2f} of on-the-books charges already prepaid (GL 2200+2220 ${-(tb('2200') + tb('2220')) / 100:,.2f})")

wk_close = []
bal = opening
for w in range(13):
    bal += sum(cents(str(r["amount_usd"])) * (1 if r["direction"] == "IN" else -1) for r in cash if r["week_index"] == w)
    wk_close.append(bal)

# ------------------------------------------------------------------ stories (computed)
def K(e, m):
    return next(r for r in kpi_rows if r["entity"] == e and r["period"] == m)


def S(e, ms, k):
    return sum(K(e, m)[k] for m in ms)


F25, F26 = MONTHS[:12], MONTHS[12:]
stories = []
a, b = S("COMPANY", F26, "total_revenue"), S("COMPANY", F25, "total_revenue")
occ26 = S("COMPANY", F26, "sold_nights") / S("COMPANY", F26, "available_nights")
occ25 = S("COMPANY", F25, "sold_nights") / S("COMPANY", F25, "available_nights")
adr26 = S("COMPANY", F26, "net_room_revenue") / S("COMPANY", F26, "sold_nights")
adr25 = S("COMPANY", F25, "net_room_revenue") / S("COMPANY", F25, "sold_nights")
stories.append({"id": "RATE-VS-OCC", "story": f"FY2026 revenue ${a / 1e6:.2f}M ({(a / b - 1) * 100:+.1f}% YoY): ADR ${adr25:.2f}→${adr26:.2f} ({(adr26 / adr25 - 1) * 100:+.1f}%) but sold occupancy {occ25 * 100:.1f}%→{occ26 * 100:.1f}%."})
lost = sum(K("WIL", m)["out_of_order_nights"] + K("WIL", m)["out_of_service_nights"] for m in ("2026-02", "2026-03"))
stories.append({"id": "WIL-REFURB", "story": f"Wilmington (WIL) lost {lost:,} room-nights to the Feb–Mar 2026 refurbishment closures; budget kept full capacity, capex $64,000 capitalized in 2026-03."})
hv = K("RAL", "2026-07")["out_of_order_nights"]
stories.append({"id": "RAL-HVAC", "story": f"Raleigh (RAL) had {hv} out-of-order room-nights in 2026-07 (HVAC); maintenance stays in opex, not capex."})
def share(e, ms, k):
    return S(e, ms, k) / S(e, ms, "sold_nights")
ota25 = (S("COMPANY", MONTHS[8:11], "agency_sold_nights") + S("COMPANY", MONTHS[8:11], "merchant_sold_nights")) / S("COMPANY", MONTHS[8:11], "sold_nights")
ota26 = (S("COMPANY", MONTHS[20:23], "agency_sold_nights") + S("COMPANY", MONTHS[20:23], "merchant_sold_nights")) / S("COMPANY", MONTHS[20:23], "sold_nights")
cpn25 = S("COMPANY", MONTHS[8:11], "ota_commission") / S("COMPANY", MONTHS[8:11], "sold_nights")
cpn26 = S("COMPANY", MONTHS[20:23], "ota_commission") / S("COMPANY", MONTHS[20:23], "sold_nights")
stories.append({"id": "OTA-SHIFT", "story": f"Summer OTA share of sold nights rose from {ota25 * 100:.1f}% (Jul–Sep 2025) to {ota26 * 100:.1f}% (Jul–Sep 2026); commission per sold night ${cpn25:.2f}→${cpn26:.2f}."})
co1 = [x for x in invoices if x["company_id"] == "CO-001" and x["open_ar_usd"] > 0]
since = [x for x in invoices if x["company_id"] == "CO-001" and x["service_month"] >= "2026-07"]
stories.append({"id": "CO-001-AR", "story": f"Corporate client CO-001 holds ${sum(x['open_ar_usd'] for x in co1):,.0f} of ${inv_open / 100:,.0f} open corporate AR ({len(co1)} invoices, up to {max(x['days_past_due'] for x in co1)} days past due); {sum(1 for x in since if x['open_ar_usd'] > 0)} of its {len(since)} invoices since Jul 2026 service are still open."})
def bv(e, k):
    return S(e, F26, k) - S(e, F26, "budget_" + k)
kk = lambda v: ("+" if v >= 0 else "−") + f"${abs(v) / 1e3:,.0f}k"
stories.append({"id": "BUDGET-FY26", "story": f"FY2026 revenue {kk(bv('COMPANY', 'total_revenue'))} vs original budget ({bv('COMPANY', 'total_revenue') / S('COMPANY', F26, 'budget_total_revenue') * 100:+.1f}%): RAL {kk(bv('RAL', 'total_revenue'))}, WIL {kk(bv('WIL', 'total_revenue'))}, DUR {kk(bv('DUR', 'total_revenue'))}. EBITDA {kk(bv('COMPANY', 'ebitda'))} vs budget, of which DUR {kk(bv('DUR', 'ebitda'))}."})
agc = S("WIL", ["2026-06", "2026-07", "2026-08"], "agency_cost")
stories.append({"id": "WIL-AGENCY", "story": f"Wilmington (WIL) paid ${agc:,.0f} for agency housekeepers in Jun–Aug 2026 while three staff housekeepers were on unpaid absence."})
lo = min(range(13), key=lambda i: wk_close[i])
stories.append({"id": "CASH-13W", "story": f"13-week cash: opening ${opening / 100 / 1e6:.2f}M, base-case low ${wk_close[lo] / 100 / 1e6:.2f}M (week of {(W0 + timedelta(days=7 * lo)).strftime('%b %d')}), ${wk_close[12] / 100 / 1e6:.2f}M on 30 Jan 2027."})

# ------------------------------------------------------------------ sources
cat = list(csv.DictReader(open(os.path.join(PKG, "metadata/source_catalog.csv"), encoding="utf-8-sig")))
fm = list(csv.DictReader(open(os.path.join(PKG, "metadata/file_manifest.csv"), encoding="utf-8-sig")))
files_by = Counter(r["relative_path"].split("/")[1] for r in fm)
USE = {"pms": "Reservations, guests, stay nights. Bookings are not revenue; only consumed nights count.",
       "availability": "Room-by-date capacity, out-of-order and out-of-service closures (occupancy denominator).",
       "night_audit": "Folio charges and credits by service date: room, breakfast, parking, cleaning, fees, lodging tax.",
       "channel_manager": "OTA reservations, commissions, agency invoices, merchant settlements (gross-to-net).",
       "payments": "Gateway captures, refunds, deposits, security, payouts. Cash timing only, never extra sales.",
       "corporate_billing": "Corporate contracts, group blocks, month-end invoices, partial receipts and advances.",
       "operations": "Housekeeping tasks, linen, agency shifts, work orders, utilities: supporting detail of GL costs.",
       "procurement": "Purchase orders and receipts; open capex commitment.",
       "gusto": "Employees, rates, time entries with weekly overtime, semi-monthly payroll and funding.",
       "fixed_assets_finance": "Assets, depreciation, term loan schedule, lodging tax remittances, member distributions.",
       "marketing": "Own Meta/Google spend (same expense as the monthly bill), platform attribution, website funnel.",
       "quickbooks": "Chart of accounts, general ledger, bills, trial balances. Authoritative financial actuals.",
       "bank": "One consolidated operating account: posted transactions and month-end balances.",
       "planning": "Original budget, on-the-books future nights, cash-forecast inputs and assumptions."}
sources = [{"source": r["source_system"], "name": r["system_style"], "tables": int(r["logical_tables"]), "files": files_by[r["source_system"]], "records": int(r["row_count"]),
            "usage": USE.get(r["source_system"], r["description_en"]), "status": "Synthetic extract"} for r in cat]

# ------------------------------------------------------------------ write
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "reconciliation_report.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["area", "check", "detail", "status"])
    w.writeheader()
    w.writerows(checks)
fails = [c for c in checks if c["status"] != "PASS"]
print(f"{len(checks) - len(fails)}/{len(checks)} checks pass")
if fails:
    for f in fails:
        print("FAIL:", f["area"], "|", f["check"], "|", f["detail"])
    sys.exit(1)


def ds(rows, grain, desc):
    return {"rows": rows, "columns": list(rows[0].keys()) if rows else [], "grain": grain, "description": desc}


build = json.load(open(os.path.join(PKG, "metadata/build_summary.json")))
meta = {"company": COMPANY, "label": "Demo company / Synthetic data",
        "business": "Three NC lodging properties operated by one LLC: select-service hotel in Raleigh (owned, 60 rooms), coastal leisure hotel in Wilmington (leased, 52 rooms), aparthotel in Durham (leased, 44 apartments), plus a shared corporate office",
        "hq": "Raleigh, NC (fictional)", "currency": "USD", "cutoff": CUT, "first_period": MONTHS[0], "last_period": MONTHS[-1],
        "fiscal_year_note": "Fiscal year runs November–October; FY2026 = Nov 2025–Oct 2026", "fiscal_years": ["FY2025", "FY2026"],
        "properties": PNAMES, "keys": {"RAL": 60, "WIL": 52, "DUR": 44}, "channels": CH_NAMES, "clients": CLIENT,
        "opening_cash": usd(opening), "cash_week_convention": "13 Sunday–Saturday weeks from 2026-11-01 to 2027-01-30.",
        "cash_rules": ["Opening cash is the operating bank only. Gateway clearing, cash in transit and earned OTA remittances enter once, as inflows on their expected dates.",
                       "Known balances at cutoff (open corporate AR, vendor AP, October payroll, lodging tax, agency commission, debt service, security returns, capex PO) come from the source subledgers, each once.",
                       "On-the-books stays: prepaid amounts already held as deposits are not collected again; guest balances arrive via the gateway (2 business days + weekly payout), merchant OTA nights as weekly net releases, corporate stays 65%/35% after the month-end invoice.",
                       "New bookings fill only capacity left after on-the-books nights (target occupancy × available − OTB), using assumption version FC-2026-10-31-BASE; this is the only estimated revenue.",
                       "Future payroll is generated from active employees, effective rates and the payroll calendar; October H2 payroll is a known obligation and not repeated.",
                       "Recurring contracts start with November service (October bills are already in open AP). Member distributions and new capital projects beyond the approved PO are excluded."],
        "cash_floor": 2000000, "cash_floor_note": f"The $2.0M cash floor is a demo assumption, not a covenant: about {2000000 / (sum(cents(r['debits_usd']) for r in T['bank/monthly_balances'][-12:]) / 1200):.1f} months of average bank outflows (${sum(cents(r['debits_usd']) for r in T['bank/monthly_balances'][-12:]) / 1200:,.0f}/month over the last 12 months).",
        "assumption_version": "FC-2026-10-31-BASE", "beyond_horizon_usd": usd(sum(beyond.values())),
        "recon_pass": len(checks), "recon_total": len(checks), "source_rows": build["source_rows"], "source_files": build["csv_files"], "source_tables": build["tables"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
out = {"meta": meta, "datasets": {
    "kpi_monthly": ds(kpi_rows, "period × entity (COMPANY, RAL, WIL, DUR, CORP)", "Monthly rooms KPIs, revenue, costs, EBITDA before/after shared allocation, budget drivers, housekeeping, labor hours, web funnel and month-end balances. COMPANY includes CORP; never add COMPANY to properties."),
    "pnl_monthly": ds(pnl_rows, "period × entity × GL account", "QuickBooks P&L activity (revenue and expense shown positive; contra-revenue negative) with original budget and the analytical CORP allocation per account."),
    "channel_monthly": ds(channel_rows, "period × property × channel", "Sold nights, net room revenue, ancillary, fees and OTA commission by booking channel; scheduled arrivals, cancellations and no-shows by arrival month."),
    "corporate_invoices": ds(invoices, "corporate invoice", "Month-end corporate invoices with prepayment and cash applied, open AR, days past due and aging at cutoff."),
    "corporate_monthly": ds(corp_rows, "period × corporate client", "Invoiced amounts, receipts, advances, sold nights and payment speed by client."),
    "corporate_clients": ds(companies, "corporate client", "Corporate clients (neutral display names), credit limits and terms."),
    "ads_monthly": ds(ads_rows, "period × property × platform", "Own Meta/Google spend and platform-attributed bookings. Attribution overlaps across platforms and is not company revenue."),
    "bank_monthly": ds(bank_rows, "period", "Operating bank opening, inflows, outflows and closing."),
    "bank_type_monthly": ds(bank_type_rows, "period × transaction type", "Bank inflows and outflows by transaction type."),
    "on_the_books": ds(otb_rows, "future month × property", "Future booked sold nights at cutoff vs capacity, with same month last year actuals for pace."),
    "demand_assumptions": ds(demand_rows, "forecast week × property", "Incremental new-booking nights = max(0, target occupancy × available − OTB sold), capped by remaining capacity."),
    "cash_schedule_13w": ds(cash, "cash line", "Every inflow and outflow in the 13-week forecast with date, category, source table and ID, and basis (KNOWN, CONTRACT, BOOKED, ESTIMATE)."),
    "reconciliations": ds(checks, "check", "Build checks: package verifier, 47 control metrics × 96 month-scope pairs, ledger, bank, AR/AP, channel and cash-input tie-outs."),
    "data_sources": ds(sources, "source system", "Simulated source systems feeding the model."),
    "stories": ds(stories, "finding", "Findings computed from the data on each build."),
}}
with open(os.path.join(OUT, "datamart.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
print("wrote", os.path.join(OUT, "datamart.json"), f"{os.path.getsize(os.path.join(OUT, 'datamart.json')) / 1e6:.2f} MB")
for s in stories:
    print("-", s["story"])
print("weekly closing:", [round(x / 100) for x in wk_close])
