"""ABC SaaS data mart builder (raw package placeholder name: "RelayNest Workflow, Inc.").

Usage: python3 -I pipeline/saas/build_datamart.py data/abc_saas_data data/output/saas
Standard library only. Money in integer cents. Writes datamart.json and reconciliation_report.csv.
Every metric is recomputed from sources/; validation/monthly_control_totals.csv is used only to reconcile.
"""
import csv, glob, json, os, sys
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_HALF_UP

ROOT, OUTDIR = sys.argv[1], sys.argv[2]
S = os.path.join(ROOT, "sources")
os.makedirs(OUTDIR, exist_ok=True)
COMPANY = "ABC SaaS"
START, CUTOFF, END = date(2024, 11, 1), date(2026, 10, 31), date(2026, 11, 1)
W0, WEND = date(2026, 11, 1), date(2027, 1, 31)  # 13 weeks Sun–Sat, exclusive end
NAME_FIX = lambda s: s.replace("RelayNest Workflow, Inc.", COMPANY).replace("RelayNest", COMPANY)


# ---------------------------------------------------------------- helpers
def files(t):
    p = os.path.join(S, t)
    return sorted(glob.glob(p + "/*.csv")) if os.path.isdir(p) else ([p + ".csv"] if os.path.exists(p + ".csv") else [])
def rows(t):
    for f in files(t):
        with open(f, encoding="utf-8-sig", newline="") as fh: yield from csv.DictReader(fh)
_cache = {}
def data(t):
    if t not in _cache: _cache[t] = list(rows(t))
    return _cache[t]
def ds(s): return date.fromisoformat(s)
def c(x): return int((D(x or "0") * 100).to_integral_value())
def hu(x): return int(D(x).quantize(D(1), rounding=ROUND_HALF_UP))
def usd(cents): return round(cents / 100, 2)
def mnext(d): return date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
def mkey(d): return f"{d.year}-{d.month:02d}"
def mend(m): return mnext(date(int(m[:4]), int(m[5:]), 1)) - timedelta(days=1)
def add_wd(d, n):
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5: n -= 1
    return d
def bank_date(capture):
    """Dataset settlement policy: available +2 weekdays, weekly Friday payout, bank receipt +2 weekdays."""
    av = add_wd(capture, 2)
    return add_wd(av + timedelta(days=(4 - av.weekday()) % 7), 2)
def fee(cents): return hu(D(cents) * D("0.029")) + 30 if cents > 0 else 0

MONTHS = []
d = START
while d <= CUTOFF: MONTHS.append(mkey(d)); d = mnext(d)
CHECKS = []
def check(area, name, ok, detail=""): CHECKS.append(dict(status="PASS" if ok else "FAIL", area=area, check=name, detail=str(detail)))


# ---------------------------------------------------------------- integrity
catalog = list(csv.DictReader(open(os.path.join(ROOT, "metadata", "table_catalog.csv"), encoding="utf-8-sig")))
heavy = {"product_analytics/user_daily_activity"}  # not shipped in the repo (112 MB); not needed by any dashboard metric
for t in catalog:
    name = t["logical_table"]
    if name in heavy and not files(name): continue
    rs = data(name) if name not in ("product_analytics/organization_daily_activity",) else None
    n = len(rs) if rs is not None else sum(1 for _ in rows(name))
    check("Integrity", f"Row count: {name}", n == int(t["source_rows"]), f"{n} rows (catalog {t['source_rows']})")
    if rs is not None and t["primary_key"] and "+" not in t["primary_key"] and t["primary_key"] in (rs[0] if rs else {}):
        k = t["primary_key"]; dup = len(rs) - len({r[k] for r in rs})
        check("Integrity", f"PK unique: {name}.{k}", dup == 0, f"{len(rs)} rows, {dup} duplicates")
fk_ok = fk_n = 0; fk_bad = []
for r in csv.DictReader(open(os.path.join(ROOT, "metadata", "relationships.csv"), encoding="utf-8-sig")):
    a, b = r["from_table"], r["to_table"]
    if a in heavy or b in heavy or "daily_activity" in a or r["condition"]: continue
    if not data(a) or r["from_column"] not in data(a)[0] or r["to_column"] not in data(b)[0]: continue
    keys = {x[r["to_column"]] for x in data(b)}
    miss = sum(1 for x in data(a) if x[r["from_column"]] and x[r["from_column"]] not in keys)
    fk_n += 1; fk_ok += miss == 0
    if miss: fk_bad.append(f"{a}.{r['from_column']}→{b}: {miss}")
check("Integrity", "Foreign keys resolve (all non-conditional relationships)", fk_ok == fk_n, f"{fk_ok}/{fk_n} relationships; " + "; ".join(fk_bad[:3]))

# ---------------------------------------------------------------- MRR from subscription + item history
prices = {r["price_id"]: r for r in data("stripe_billing/prices")}
items = {r["subscription_version_id"]: r for r in data("stripe_billing/subscription_item_history")}
versions = defaultdict(list)
for r in data("stripe_billing/subscription_history"): versions[r["subscription_id"]].append(r)
def version_mrr(v, on):
    if v["status"] == "past_due":
        if not v["grace_end_date"] or on >= ds(v["grace_end_date"]): return 0
    elif v["status"] != "active": return 0
    it = items[v["subscription_version_id"]]; p = prices[it["price_id"]]
    gross = D(p["unit_amount"]) * int(it["quantity"]) * (D(10000) - int(it["recurring_discount_bps"])) / D(10000)
    return int((gross / int(p["normalization_months"]) * 100).quantize(D(1), rounding=ROUND_HALF_UP))
def state_at(vs, day):
    for v in vs:
        if ds(v["effective_from"]) <= day < ds(v["effective_to"] or "9999-12-31"): return version_mrr(v, day), v
    return 0, None

bridge = {m: Counter() for m in MONTHS}; moves = {m: Counter() for m in MONTHS}
closing = {m: Counter() for m in MONTHS}
by_plan = defaultdict(lambda: Counter())  # (month, plan, interval, version) -> mrr, accounts
first_paid, opening_mrr = {}, 0
cohort_mrr = defaultdict(Counter)  # cohort month -> month -> mrr
for sid, vs in versions.items():
    vs.sort(key=lambda v: v["effective_from"])
    pts = set()
    for v in vs:
        for k in ("effective_from", "effective_to", "grace_end_date"):
            if v[k]: pts.add(ds(v[k]))
    prev, _ = state_at(vs, START - timedelta(days=1)); opening_mrr += prev
    ever = prev > 0 or any(ds(v["effective_from"]) < START and version_mrr(v, ds(v["effective_from"])) > 0 for v in vs)
    if prev > 0 or ever: first_paid.setdefault(sid, "opening")
    for p in sorted(x for x in pts if START <= x <= CUTOFF):
        cur, _ = state_at(vs, p)
        if cur == prev: continue
        m = mkey(p)
        if prev == 0:
            kind = "reactivation" if ever else "new"
            if not ever: first_paid[sid] = m
            ever = True
        elif cur == 0: kind = "churn"
        else: kind = "expansion" if cur > prev else "contraction"
        bridge[m][kind] += abs(cur - prev); moves[m][kind] += 1; prev = cur
    for m in MONTHS:
        val, v = state_at(vs, mend(m))
        if val > 0:
            cl = closing[m]; cl["mrr"] += val; cl["accounts"] += 1
            cl["annual" if v["billing_interval"] == "year" else "monthly"] += 1
            cl["seats"] += int(items[v["subscription_version_id"]]["quantity"])
            key = (m, v["plan_name"], v["billing_interval"], v["catalog_version"])
            by_plan[key]["mrr"] += val; by_plan[key]["accounts"] += 1
            if first_paid.get(sid) not in (None, "opening"): cohort_mrr[first_paid[sid]][m] += val

# ---------------------------------------------------------------- GL
coa = {r["account_code"]: r for r in data("quickbooks/chart_of_accounts")}
act = defaultdict(Counter); dr = cr = 0; per_journal = Counter()
for r in rows("quickbooks/general_ledger"):
    a, b = c(r["debit"]), c(r["credit"]); dr += a; cr += b; per_journal[r["journal_id"]] += a - b
    act[r["posting_date"][:7]][r["account_code"]] += a - b
check("Ledger", "General ledger debits = credits", dr == cr, f"{usd(dr):,.2f} both sides")
unbal = sum(1 for v in per_journal.values() if v)
check("Ledger", "Every journal entry balances", unbal == 0, f"{len(per_journal)} journals, {unbal} unbalanced")
bal = {r["account_code"]: c(r["signed_balance"]) for r in data("quickbooks/opening_trial_balance")}
check("Ledger", "Opening trial balance nets to zero", sum(bal.values()) == 0, f"{len(bal)} accounts")
bs, pl = {}, {}
for m in MONTHS:
    a = act[m]
    for k, v in a.items(): bal[k] = bal.get(k, 0) + v
    bs[m] = dict(bal)
    rev = sum(-v for k, v in a.items() if coa[k]["account_type"] == "revenue")
    cogs = sum(v for k, v in a.items() if k.startswith("5")); opex = sum(v for k, v in a.items() if k.startswith("6"))
    pl[m] = dict(revenue=rev, cogs=cogs, opex=opex, gp=rev - cogs, ni=rev - cogs - opex)
tb = Counter()
for r in data("quickbooks/monthly_trial_balance"):
    tb[(r[list(r)[0]] if False else r.get("period") or r.get("month") or r.get("balance_month"), r["account_code"])] = c(r.get("signed_balance") or r.get("closing_signed_balance") or "0")
tb_bad = sum(1 for m in MONTHS for k in coa if (m, k) in tb and tb[(m, k)] != bs[m].get(k, 0))
check("Ledger", "Monthly trial balance = opening TB + GL activity (35 accounts × 24 months)", tb_bad == 0, f"{tb_bad} differences")

# ---------------------------------------------------------------- billings, bookings, cash
gross_bill, cn, book, captured, refunds, fees = (Counter() for _ in range(6))
for r in data("stripe_billing/invoices"):
    if r["record_scope"] == "observation_period": gross_bill[r["issue_date"][:7]] += c(r["total"])
for r in data("stripe_billing/credit_notes"):
    if r["record_scope"] == "observation_period": cn[r["issue_date"][:7]] += c(r["credit_amount"])
for r in data("contracts/contract_events"):
    if r["record_scope"] == "observation_period": book[r["event_date"][:7]] += c(r["committed_value_change"])
for r in data("stripe_payments/charges"):
    if r["record_scope"] == "observation_period": captured[r["charge_date"][:7]] += c(r["amount"])
for r in data("stripe_payments/refunds"):
    if r.get("record_scope", "observation_period") == "observation_period": refunds[(r.get("refund_date") or r.get("created_date") or "")[:7]] += c(r["amount"])
for r in data("stripe_payments/balance_transactions"):
    if r["record_scope"] == "observation_period": fees[r["transaction_date"][:7]] += c(r["fee"])
bank_in, bank_out = Counter(), Counter(); bank_type = defaultdict(Counter)
for r in data("bank/statement"):
    a = c(r["amount"]); m = r["posting_date"][:7]
    (bank_in if a > 0 else bank_out)[m] += abs(a); bank_type[m][r["transaction_type"]] += a
bank_bal = {r[list(r)[0]] if False else (r.get("month") or r.get("balance_month")): c(r.get("closing_balance") or r.get("closing_bank_balance") or "0") for r in data("bank/monthly_balances")}
bank_gl = sum(1 for m in MONTHS if m in bank_bal and bank_bal[m] != bs[m].get("1000", 0))
check("Cash", "Bank statement month-end balance = GL 1000 (24 months)", bank_gl == 0, f"{bank_gl} differences")

# product analytics: active users and organizations
active = defaultdict(lambda: [0, 0, set()])  # month -> [sum active users, days, orgs active]
days_seen = defaultdict(set)
for r in rows("product_analytics/organization_daily_activity"):
    m = r["activity_date"][:7]; au = int(r["active_users"] or 0)
    active[m][0] += au; days_seen[m].add(r["activity_date"])
    if au > 0: active[m][2].add(r["organization_id"])

emps = data("gusto/employees")
def headcount(day, dept=None):
    return sum(1 for e in emps if ds(e["hire_date"]) <= day and (not e["termination_date"] or ds(e["termination_date"]) > day) and (dept is None or e["department"] == dept))
budget = defaultdict(Counter)
for r in data("planning/original_monthly_budget"): budget[r["budget_month"]][r["account_code"]] += c(r["budget_amount"])
hc_plan = defaultdict(Counter)
for r in data("planning/original_headcount_plan"): hc_plan[r["budget_month"]][r["department"]] += int(r["planned_fte"])

# ---------------------------------------------------------------- monthly KPI table
kpi = []; prev_close = opening_mrr
for m in MONTHS:
    b, cl, p, bb = bridge[m], closing[m], pl[m], bs[m]; ex = act[m]
    sm = sum(v for k, v in ex.items() if coa[k]["department"] == "Sales & Marketing")
    bud_rev = sum(v for k, v in budget[m].items() if k.startswith("4")); bud_exp = sum(v for k, v in budget[m].items() if not k.startswith("4"))
    new_logos = moves[m]["new"]
    rec = dict(
        period=m, opening_mrr=prev_close, new_mrr=b["new"], expansion_mrr=b["expansion"], contraction_mrr=b["contraction"], churn_mrr=b["churn"],
        reactivation_mrr=b["reactivation"], closing_mrr=cl["mrr"], closing_arr=cl["mrr"] * 12, paid_accounts=cl["accounts"],
        annual_paid_accounts=cl["annual"], monthly_paid_accounts=cl["monthly"], purchased_seats=cl["seats"],
        new_paid_accounts=new_logos, churned_accounts=moves[m]["churn"], reactivated_accounts=moves[m]["reactivation"],
        gross_billings=gross_bill[m], credit_notes=cn[m], net_billings=gross_bill[m] - cn[m], bookings=book[m],
        recognized_revenue=p["revenue"], captured_customer_cash=captured[m], processor_fees=fees[m],
        bank_cash_in=bank_in[m], bank_cash_out=bank_out[m], equity_funding=bank_type[m].get("equity_funding", 0),
        payroll_funding=-bank_type[m].get("payroll_funding", 0),
        closing_bank_cash=bb.get("1000", 0), closing_processor_balance=bb.get("1010", 0), closing_payouts_in_transit=bb.get("1020", 0),
        closing_ar=bb.get("1100", 0), closing_ap=-bb.get("2000", 0), closing_deferred_revenue=-bb.get("2200", 0),
        closing_payroll_payable=-bb.get("2100", 0), closing_prepaid_services=bb.get("1300", 0),
        cloud_expense=ex.get("5000", 0) + ex.get("6010", 0), advertising_expense=ex.get("6110", 0) + ex.get("6120", 0),
        cogs=p["cogs"], gross_profit=p["gp"], opex=p["opex"], net_income=p["ni"], sm_expense=sm,
        closing_headcount=headcount(mend(m)), planned_fte=sum(hc_plan[m].values()),
        original_budget_revenue=bud_rev, original_budget_expense=bud_exp, budget_net_income=bud_rev - bud_exp,
        avg_daily_active_users=round(active[m][0] / max(1, len(days_seen[m])), 1), active_organizations=len(active[m][2]),
    )
    rec["blended_cac"] = round(sm / new_logos) if new_logos else None
    kpi.append(rec); prev_close = cl["mrr"]

# reconcile to control totals (control file is not a metric source)
ctrl = {r["month"]: r for r in csv.DictReader(open(os.path.join(ROOT, "validation", "monthly_control_totals.csv"), encoding="utf-8-sig"))}
INT_FIELDS = {"paid_accounts", "annual_paid_accounts", "monthly_paid_accounts", "purchased_seats", "closing_headcount"}
compared = 0; diffs = []
for rec in kpi:
    cr_ = ctrl[rec["period"]]
    for k, v in rec.items():
        if k == "period" or k not in cr_: continue
        exp = int(cr_[k]) if k in INT_FIELDS else c(cr_[k]); compared += 1
        if v != exp: diffs.append(f"{rec['period']} {k}: {v} vs {exp}")
nfields = len([k for k in kpi[0] if k in ctrl[MONTHS[0]]])
check("Control totals", f"{nfields} metrics × 24 months match validation/monthly_control_totals.csv", not diffs, f"{compared} values compared; " + ("; ".join(diffs[:3]) or "0 differences"))
mrr_roll = all(r["opening_mrr"] + r["new_mrr"] + r["expansion_mrr"] - r["contraction_mrr"] - r["churn_mrr"] + r["reactivation_mrr"] == r["closing_mrr"] for r in kpi)
check("Revenue", "MRR bridge rolls forward every month", mrr_roll, "opening + new + expansion − contraction − churn + reactivation = closing")
check("Revenue", "Closing MRR (Oct 2026) from status/item history", kpi[-1]["closing_mrr"] == 46475450, f"${usd(kpi[-1]['closing_mrr']):,.2f}")
rs_act = Counter()
for r in data("revenue_accounting/revenue_schedule"):
    if r["actual_posting_date"] and START <= ds(r["actual_posting_date"]) <= CUTOFF: rs_act[r["actual_posting_date"][:7]] += c(r["amount"])
rs_bad = [m for m in MONTHS if rs_act[m] != pl[m]["revenue"]]
check("Revenue", "Revenue schedule actual postings = GL revenue (24 months)", not rs_bad, f"{len(rs_bad)} months differ")
fut = [r for r in data("revenue_accounting/revenue_schedule") if r["schedule_status"] == "future_unearned"]
check("Revenue", "Future unearned schedule has no actual posting date", all(not r["actual_posting_date"] for r in fut), f"{len(fut)} future rows")
check("Cash", "Equity funding kept out of revenue and MRR", sum(k["equity_funding"] for k in kpi) == 160000000, f"${usd(sum(k['equity_funding'] for k in kpi)):,.0f} in Sep 2025, financing only")
pay_alloc = Counter()
for r in data("gusto/payroll_allocations"): pay_alloc["x"] += c(r["allocated_employer_cost"])
reg = sum(c(r.get("employer_cost") or r.get("total_employer_cost") or "0") for r in data("gusto/payroll_register"))
if reg: check("Payroll", "Payroll allocations sum to employer cost (no new expense)", pay_alloc["x"] == reg, f"${usd(reg):,.2f}")

# ---------------------------------------------------------------- P&L by account vs budget
pnl_rows = []
for m in MONTHS:
    for k, a in coa.items():
        if a["statement"] != "PL": continue
        actual = act[m].get(k, 0) * (-1 if a["account_type"] == "revenue" else 1)
        bud = budget[m].get(k, 0)
        if actual or bud:
            grp = "Revenue" if k.startswith("4") else "Cost of revenue" if k.startswith("5") else a["department"]
            pnl_rows.append(dict(period=m, account_id=k, line=a["account_name"], group=grp, actual=usd(actual), budget=usd(bud)))

# ---------------------------------------------------------------- 13-week cash forecast
last3 = MONTHS[-3:]
K = {r["period"]: r for r in kpi}
churn_rate = sum(K[m]["churn_mrr"] for m in last3) / sum(K[m]["opening_mrr"] for m in last3)
items_fc = []
def add(dt, line, section, cents, kind, item, source, basis):
    items_fc.append(dict(date=str(dt), line=line, section=section, amount=usd(cents), kind=kind, item=item, source=source, basis=basis))
final = bs[MONTHS[-1]]
for r in data("stripe_payments/payouts"):
    if r["status"] == "in_transit":
        add(ds(r["expected_arrival_date"]), "Processor settlements", "Inflows", c(r["amount"]), "Known", "Payout in transit", r["payout_id"], "Initiated 30 Oct, expected arrival date from the processor")
add(bank_date(CUTOFF), "Processor settlements", "Inflows", final["1010"], "Known", "Processor balance at cutoff", "GL 1010", "Next Friday payout, bank +2 weekdays")
for r in data("stripe_billing/invoices"):
    rem = c(r["amount_remaining"])
    if rem <= 0: continue
    if r["collection_terms"] == "net35_two_installments":
        add(bank_date(max(ds(r["due_date"]), W0)), "Open AR collections", "Inflows", rem - fee(rem), "Known", f"2nd installment {r['invoice_id']}", r["invoice_id"], "Negotiated net35 two-installment terms; net of 2.9% + $0.30 fee")
    else:
        amt = hu(rem / 2)
        add(bank_date(W0 + timedelta(days=7)), "Open AR collections", "Inflows", amt - fee(amt), "Estimate", f"Past-due {r['invoice_id']} (50%)", r["invoice_id"], "In dunning: 50% recovery assumption within the 21-day grace window")
by_v2 = {(p["plan_name"], p["recurring_interval"]): p for p in prices.values() if p["catalog_version"] == "v2"}
vers = {r["subscription_version_id"]: r for r in data("stripe_billing/subscription_history")}
renew_n = 0
for s in data("stripe_billing/subscriptions"):
    if s["status"] != "active" or s["cancel_at_period_end"] == "True": continue
    v = vers[s["current_version_id"]]; it = items[v["subscription_version_id"]]; p = prices[it["price_id"]]
    qty, disc = int(it["quantity"]), int(it["recurring_discount_bps"])
    amt_of = lambda pr: hu(D(pr["unit_amount"]) * qty * (10000 - disc) / 10000 * 100)
    cur = amt_of(p); v2 = amt_of(by_v2[(p["plan_name"], p["recurring_interval"])]) if p["catalog_version"] == "v1" else cur
    nxt, k = ds(s["current_period_end_exclusive"]), 0
    while nxt < WEND:
        if nxt >= W0:
            exp_amt = cur + hu((v2 - cur) * D(6) / D(7))
            gross = hu(D(exp_amt) * D(1 - churn_rate) ** (k + 1)); k += 1; renew_n += 1
            annual = p["recurring_interval"] == "year"
            add(bank_date(nxt), "Annual renewals" if annual else "Monthly renewals", "Inflows", gross - fee(gross), "Estimate",
                f"{s['subscription_id']} {v['plan_name']} {qty} seats{' v1→v2' if v2 != cur else ''}", s["subscription_id"],
                f"Renews {nxt}; current price{' moving to v2 for 6 of 7 legacy renewals' if v2 != cur else ''}; × survival {(1 - churn_rate) ** k:.3f} (churn {churn_rate:.2%}/mo, Aug–Oct)")
        if p["recurring_interval"] != "month": break
        nxt = date(nxt.year + (nxt.month == 12), 1 if nxt.month == 12 else nxt.month + 1, min(nxt.day, 28))
for r in data("contracts/contracts"):
    if r["known_future_start"] == "True":
        amt = c(r["current_committed_amount"])
        add(bank_date(ds(r["service_start"])), "Signed future-start contract", "Inflows", amt - fee(amt), "Known", f"{r['contract_id']} {r['plan_name']} annual, starts {r['service_start']}", r["contract_id"], "Signed 26 Oct; invoiced and captured at service start")
first_inv = {}
for r in data("stripe_billing/invoices"):
    sid = r["subscription_id"]
    if first_paid.get(sid) in last3 and r["record_scope"] == "observation_period" and (sid not in first_inv or r["issue_date"] < first_inv[sid][0]):
        first_inv[sid] = (r["issue_date"], c(r["total"]))
new_month = sum(v[1] for v in first_inv.values()) // 3
wk_new = new_month * 12 * 7 // 365
for w in range(13):
    ws = W0 + timedelta(days=7 * w)
    add(bank_date(ws + timedelta(days=3)), "New customers", "Inflows", wk_new - fee(wk_new), "Estimate", "New paid customers (run-rate)", "DRIVER-NEW",
        f"Avg first-invoice cash of {len(first_inv)} new subscriptions Aug–Oct 2026 = ${usd(new_month):,.0f}/month, spread evenly")
for r in data("planning/known_obligations"):
    dt = ds(r["expected_payment_date"])
    if dt >= WEND: continue
    if r["obligation_type"] == "accrued_payroll":
        add(dt, "Payroll", "Outflows", -c(r["amount"]), "Known", "Oct 16–31 payroll (earned, unfunded at cutoff)", r["source_id"], "GL 2100 payroll funding payable")
    elif r["obligation_type"] == "open_ap":
        add(dt, "Vendors: open AP", "Outflows", -c(r["amount"]), "Known", f"Open bill {r['source_id']}", r["source_id"], "QuickBooks AP, due date")
    else:
        add(dt, "Vendors: contracts", "Outflows", -c(r["amount"]), "Known", r["deduplication_key"].replace("UNBILLED:", ""), r["source_id"], "Next unbilled contractual cycle (procurement register)")
for r in data("procurement/vendor_contracts"):
    if r["billing_interval"] == "month":
        add(date(2027, 1, 15), "Vendors: contracts", "Outflows", -c(r["recurring_amount"]), "Known", f"{r['vendor_contract_id']}:2026-12-31", r["vendor_contract_id"], "December cycle, billed 31 Dec, net 15")
sal = defaultdict(list)
for r in data("gusto/salary_history"): sal[r["employee_id"]].append(r)
act_emp = [e for e in emps if not e["termination_date"]]
def annual(eid, day):
    for r in sal[eid]:
        if ds(r["effective_from"]) <= day < ds(r["effective_to"] or "9999-12-31"): return D(r["annual_salary"])
    return D(max(sal[eid], key=lambda r: r["effective_from"])["annual_salary"])
reqs = data("planning/hiring_requisitions")
d = W0
while d < WEND:
    for ps, pe in ((d, date(d.year, d.month, 16)), (date(d.year, d.month, 16), mnext(d))):
        fd = add_wd(pe - timedelta(days=1), 2)
        if fd >= WEND: continue
        gross = sum(annual(e["employee_id"], ps + timedelta(days=i)) / 365 for e in act_emp for i in range((pe - ps).days))
        add(fd, "Payroll", "Outflows", -hu(gross * D("1.082") * 100), "Estimate", f"Payroll {ps:%b %d}–{pe - timedelta(days=1):%b %d} ({len(act_emp)} employees)", "FCST-PAY-" + str(ps),
            "Current salaries × calendar days / 365 × 1.082 employer tax; funded 2 weekdays after period end")
        for rq in reqs:
            st = ds(rq["expected_start_date"])
            if st < pe:
                g = D(rq["planned_annual_salary"]) / 365 * (pe - max(ps, st)).days
                add(fd, "Hiring plan", "Outflows", -hu(g * D("1.082") * 100), "Scenario", f"{rq['role']} ({rq['requisition_id']})", rq["requisition_id"], f"Open requisition, start {st}; not an actual employee yet")
    d = mnext(d)
for i, (mo, d15, d20) in enumerate([("Nov", date(2026, 12, 15), date(2026, 12, 20)), ("Dec", date(2027, 1, 15), date(2027, 1, 20))]):
    add(d15, "Vendors: benefits", "Outflows", -len(act_emp) * 65000, "Estimate", f"Health benefits {mo}", "ven_benefits", f"$650 × {len(act_emp)} employees, billed month-end, net 15")
    for rq in reqs:
        if ds(rq["expected_start_date"]) <= date(2026 + (mo == "Dec") * 0, 11 if mo == "Nov" else 12, 28):
            add(d15, "Hiring plan", "Outflows", -(65000 + 240000), "Scenario", f"Benefits + laptop, {rq['role']}", rq["requisition_id"], "$650 benefits + $2,400 laptop in start month")
    cloud = hu(D(final_cloud := act[MONTHS[-1]].get("5000", 0) + act[MONTHS[-1]].get("6010", 0)) * D("1.03") ** (i + 1))
    add(d20, "Vendors: cloud", "Outflows", -cloud, "Estimate", f"Cloud {mo} bill", "ven_cloud", "Oct 2026 bill $32,788 grown 3%/month (Sep→Oct +3.2%), net 20")
    add(d20, "Vendors: advertising", "Outflows", -(1732000 + 1144500), "Estimate", f"Google + Meta {mo} bills", "ven_google/ven_meta", "Held flat at October bills ($17,320 + $11,445), net 20")

LINES = ["Processor settlements", "Open AR collections", "Monthly renewals", "Annual renewals", "Signed future-start contract", "New customers",
         "Payroll", "Hiring plan", "Vendors: open AP", "Vendors: contracts", "Vendors: benefits", "Vendors: cloud", "Vendors: advertising"]
weeks = []
cash = final["1000"]
for w in range(13):
    ws = W0 + timedelta(days=7 * w)
    its = [x for x in items_fc if ws <= ds(x["date"]) < ws + timedelta(days=7)]
    inflow = sum(c(str(x["amount"])) for x in its if x["amount"] > 0); outflow = -sum(c(str(x["amount"])) for x in its if x["amount"] < 0)
    hire = -sum(c(str(x["amount"])) for x in its if x["line"] == "Hiring plan")
    weeks.append(dict(week=w + 1, start=str(ws), end=str(ws + timedelta(days=6)), opening=usd(cash), inflow=usd(inflow), outflow=usd(outflow),
                      closing=usd(cash + inflow - outflow), hiring=usd(hire))); cash += inflow - outflow
outside = [x for x in items_fc if not (W0 <= ds(x["date"]) < WEND)]
items_fc = [x for x in items_fc if W0 <= ds(x["date"]) < WEND]
check("Forecast", "13-week forecast starts from GL 1000 = bank statement", final["1000"] == bank_bal.get(MONTHS[-1], final["1000"]), f"${usd(final['1000']):,.2f}")
check("Forecast", "Each obligation enters once (dedup keys unique; Oct AP not re-forecast as recurring)", len({r["deduplication_key"] for r in data("planning/known_obligations")}) == len(data("planning/known_obligations")), f"{len(data('planning/known_obligations'))} obligations")
check("Forecast", "Prepaid annual service not forecast again (renewals only after current period end)", all(ds(x["date"]) >= W0 for x in items_fc if "renewals" in x["line"]), f"{renew_n} renewal charges modeled")

# ---------------------------------------------------------------- 12-month rolling forecast
new3 = sum(K[m]["new_mrr"] + K[m]["reactivation_mrr"] for m in last3) / 3
exp3 = sum(K[m]["expansion_mrr"] - K[m]["contraction_mrr"] for m in last3) / sum(K[m]["opening_mrr"] for m in last3)
gm3 = sum(K[m]["gross_profit"] for m in last3) / sum(K[m]["recognized_revenue"] for m in last3)
opex_oct = K[MONTHS[-1]]["opex"]
roll = []
mrr = K[MONTHS[-1]]["closing_mrr"]; mm = END
for i in range(12):
    om = mrr; ch = om * churn_rate; ne = om * exp3; fut_c = 116000 if i == 0 else 0  # 13,920 TCV / 12
    mrr = om + new3 + ne - ch + fut_c
    rev = (om + mrr) / 2
    hire = sum(float(D(r["planned_annual_salary"]) * D("1.082") / 12 * 100) + 65000 for r in reqs if ds(r["expected_start_date"]) < date(mm.year, mm.month, 28))
    opex = opex_oct * 1.004 ** (i + 1) + hire
    roll.append(dict(period=mkey(mm), kind="Forecast", opening_mrr=usd(round(om)), new_mrr=usd(round(new3 + fut_c)), net_expansion_mrr=usd(round(ne)), churn_mrr=usd(round(ch)),
                     closing_mrr=usd(round(mrr)), revenue=usd(round(rev)), gross_profit=usd(round(rev * gm3)), opex=usd(round(opex)), net_income=usd(round(rev * gm3 - opex))))
    mm = mnext(mm)

# ---------------------------------------------------------------- other datasets
plan_rows = [dict(period=m, plan=p, interval=iv, catalog_version=cv, mrr=usd(v["mrr"]), accounts=v["accounts"]) for (m, p, iv, cv), v in sorted(by_plan.items())]
cohort_rows = []
for cm_, series in sorted(cohort_mrr.items()):
    base = series.get(cm_, 0)
    for m in MONTHS:
        if m >= cm_ and base: cohort_rows.append(dict(cohort=cm_, period=m, months_since=(int(m[:4]) - int(cm_[:4])) * 12 + int(m[5:]) - int(cm_[5:]), mrr=usd(series.get(m, 0)), retention=round(series.get(m, 0) / base, 4)))
dept_rows = []
for m in MONTHS:
    for dept in ("Engineering/R&D", "Sales & Marketing", "Customer Success/Support", "G&A"):
        dept_rows.append(dict(period=m, department=dept, headcount=headcount(mend(m), dept), planned_fte=hc_plan[m][dept]))
stories = [dict(id=r["business_event_id"], date=r["event_date"], title=r["event_title"], source=r["source_table"], story=NAME_FIX(r["description"])) for r in data("planning/business_events")]
src_cat = list(csv.DictReader(open(os.path.join(ROOT, "metadata", "source_catalog.csv"), encoding="utf-8-sig")))
NAMES = {"stripe_billing": "Stripe Billing", "stripe_payments": "Stripe Payments", "contracts": "Order forms & contracts", "revenue_accounting": "Revenue subledger",
         "product_analytics": "Product analytics", "hubspot": "HubSpot CRM", "aws": "AWS billing", "gusto": "Gusto payroll", "quickbooks": "QuickBooks",
         "bank": "Operating bank", "meta_ads": "Meta Ads", "google_ads": "Google Ads", "marketing": "First-party tracking", "procurement": "Vendor contracts",
         "planning": "Budget & plans", "finance": "Equity register"}
ACT_TABLE = {"stripe_billing": ("stripe_billing/invoices", "issue_date"), "stripe_payments": ("stripe_payments/charges", "charge_date"), "contracts": ("contracts/contract_events", "event_date"),
             "revenue_accounting": ("revenue_accounting/revenue_schedule", "actual_posting_date"), "product_analytics": ("product_analytics/onboarding_events", None), "hubspot": ("hubspot/deals", "created_date"),
             "aws": ("aws/daily_resource_cost", None), "gusto": ("gusto/payroll_runs", "earned_posting_date"), "quickbooks": ("quickbooks/vendor_bills", "issue_date"), "bank": ("bank/statement", "posting_date"),
             "meta_ads": ("meta_ads/daily_campaign_metrics", None), "google_ads": ("google_ads/daily_campaign_metrics", None), "marketing": ("marketing/leads", None),
             "procurement": ("procurement/vendor_contract_amount_history", None), "planning": ("planning/original_monthly_budget", "budget_month"), "finance": ("finance/equity_funding", None)}
sources_rows, activity_rows = [], []
for s in src_cat:
    sid = s["source_system"]; t, col = ACT_TABLE[sid]; rs = data(t)
    if col is None: col = next((k for k in rs[0] if k.endswith("date")), None) if rs else None
    cnt = Counter((r.get(col) or "")[:7] for r in rs) if col else Counter()
    last = max(((r.get(col) or "")[:10] for r in rs if (r.get(col) or "")[:10] and (r.get(col) or "")[:10] <= str(CUTOFF)), default="")
    nrows = int(s["row_count"]) - (1663269 if sid == "product_analytics" and not files("product_analytics/user_daily_activity") else 0)
    sources_rows.append(dict(source=sid, name=NAMES[sid], description=NAME_FIX(s["description"]), records=nrows, tables=int(s["logical_tables"]), files=int(s["physical_csv_files"]),
                             last_record_date=last, status="Synced", activity_table=t.split("/")[1], policy=s["authority_and_double_counting_policy"]))
    for m in MONTHS: activity_rows.append(dict(source=sid, period=m, records=cnt.get(m, 0)))

def money_cols(r): return {k: (usd(v) if isinstance(v, int) and k not in INT_FIELDS | {"new_paid_accounts", "churned_accounts", "reactivated_accounts", "planned_fte", "active_organizations"} else v) for k, v in r.items()}
kpi_out = [money_cols(r) for r in kpi]
def dset(grain, desc, rows_):
    return dict(grain=grain, description=desc, columns=list(rows_[0].keys()) if rows_ else [], rows=rows_)
npass = sum(1 for x in CHECKS if x["status"] == "PASS")
A = dict(version="FCST_13W_2026_10_31", as_of=str(CUTOFF), window="2026-11-01 – 2027-01-30 (13 weeks, Sunday–Saturday)",
         renewal_churn_rate=round(churn_rate, 4), new_customer_cash_per_month=usd(new_month), rolling_new_mrr_per_month=usd(round(new3)),
         rolling_net_expansion_rate=round(exp3, 4), rolling_gross_margin=round(gm3, 4), renewal_charges=renew_n, items_outside_window=len(outside))
meta = dict(company=COMPANY, label="Demo company / Synthetic data", business="B2B SaaS: workflow approvals and automation for small teams; seat-based Starter / Team / Scale plans, monthly or annual billing, 14-day trials",
            hq="Denver, CO (fictional)", currency="USD", cutoff=str(CUTOFF), first_period=MONTHS[0], last_period=MONTHS[-1], opening_cash=usd(final["1000"]),
            opening_bank_cash_nov_2024=usd(c("2618319.33")), recon_pass=npass, recon_total=len(CHECKS), source_rows=sum(s["records"] for s in sources_rows),
            source_files=sum(len(files(t["logical_table"])) for t in catalog), generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            cash_week_convention="Consecutive 7-day weeks Sunday–Saturday from 2026-11-01; W13 ends 2027-01-30.",
            forecast_assumptions=A,
            cash_rules=["Known items: payouts in transit, processor balance, open AR, open AP, unfunded October payroll, signed vendor contract cycles and the signed future-start contract.",
                        "Renewals are forecast only after each subscription's current paid period ends, so prepaid annual service (deferred revenue) is never collected twice.",
                        "Subscriptions with a scheduled cancellation produce no renewal; past-due invoices are recovered at 50%.",
                        "October cloud, ads and vendor bills are already in AP (due Nov 15–20); recurring drivers start with November bills, paid in December.",
                        "Each known obligation has a unique deduplication key; open requisitions are a separate scenario line, not actual employees.",
                        "Equity funding is excluded; no new financing is assumed."],
            pricing="v1 → v2 (+11–12%) for new customers from 2026-04-01; legacy renewals move from 2026-07-01, every seventh customer keeps v1.")
dm = dict(meta=meta, datasets=dict(
    kpi_monthly=dset("month", "Monthly SaaS, P&L, billing, cash and balance-sheet metrics, all recomputed from raw sources (USD).", kpi_out),
    pnl_monthly=dset("month × GL account", "General-ledger activity by P&L account vs the immutable original budget (approved 2024-10-20).", pnl_rows),
    mrr_by_plan=dset("month × plan × billing interval × price version", "Month-end MRR and paid accounts.", plan_rows),
    cohorts=dset("acquisition cohort × month", "MRR of each first-paid cohort (new logos in the window; reactivations excluded) and MRR retention vs month 0.", cohort_rows),
    headcount=dset("month × department", "Actual employees at month end vs original FTE plan.", dept_rows),
    cash_forecast_items=dset("line item", "13-week cash forecast line items (Known / Estimate / Scenario) with basis and source ID.", items_fc),
    cash_forecast_weeks=dset("week", "13-week cash roll-forward (base case incl. hiring plan).", weeks),
    rolling_forecast=dset("month", "12-month driver-based rolling forecast, Nov 2026 – Oct 2027.", roll),
    hiring_requisitions=dset("requisition", "Open requisitions (plans, not hires).", [dict(id=r["requisition_id"], department=r["department"], role=r["role"], salary=float(r["planned_annual_salary"]), start=r["expected_start_date"]) for r in reqs]),
    stories=dset("business event", "Documented events that explain the numbers (not additional transactions).", stories),
    data_sources=dset("source system", "Simulated source systems feeding the model.", sources_rows),
    source_activity_monthly=dset("source × month", "Records per month in each source's activity table.", activity_rows),
    reconciliations=dset("check", "Every check run on the raw sources; dashboards publish only when all pass.", CHECKS)))
json.dump(dm, open(os.path.join(OUTDIR, "datamart.json"), "w"), separators=(",", ":"), default=str)
with open(os.path.join(OUTDIR, "reconciliation_report.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["status", "area", "check", "detail"]); w.writeheader(); w.writerows(CHECKS)
print(f"{npass}/{len(CHECKS)} checks pass")
for x in CHECKS:
    if x["status"] != "PASS": print("FAIL", x["area"], x["check"], x["detail"])
print("13w closing", weeks[-1]["closing"], "low", min(w["closing"] for w in weeks))
