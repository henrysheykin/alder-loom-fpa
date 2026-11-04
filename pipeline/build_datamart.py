"""
Alder & Loom Commerce (DEMO COMPANY / SYNTHETIC DATA) - FP&A data mart builder.

Reads the raw source extracts in <data_root>/sources, normalizes them, runs
reconciliations and writes one compact JSON data mart for the dashboard:

    python build_datamart.py <data_root> <output_dir>

Money is handled in integer cents. Nothing is read from validation/ except for
the reconciliation step, where control totals are compared with values computed
from raw sources.
"""
import sys, os, glob, json, datetime as dt
import pandas as pd
import numpy as np

ROOT = sys.argv[1] if len(sys.argv) > 1 else "alder_loom_data"
OUT = sys.argv[2] if len(sys.argv) > 2 else "output"
SRC = os.path.join(ROOT, "sources")
os.makedirs(OUT, exist_ok=True)


def rd(rel, **kw):
    return pd.read_csv(os.path.join(SRC, rel), encoding="utf-8-sig", dtype=str, keep_default_na=False, na_values=[""], **kw)


def c(s):
    """decimal string column -> int64 cents"""
    return (pd.to_numeric(s, errors="coerce").fillna(0) * 100).round().astype("int64")


def usd(x):
    return round(float(x) / 100.0, 2)


D = lambda s: dt.date.fromisoformat(s)

# ---------------------------------------------------------------- reference
coa = rd("quickbooks/chart_of_accounts.csv")
LINE_OF = dict(zip(coa.account_code, coa.reporting_line))

PNL = [  # (reporting_line, section, sign in profit)
    ("Gross product sales", "Revenue", 1),
    ("Sales discounts", "Revenue", -1),
    ("Merchandise returns", "Revenue", -1),
    ("Shipping income", "Revenue", 1),
    ("Merchandise COGS", "Cost of sales", -1),
    ("Inventory writeoffs", "Cost of sales", -1),
    ("Merchant fees", "Fulfillment & payments", -1),
    ("Outbound fulfillment", "Fulfillment & payments", -1),
    ("Warehouse storage", "Fulfillment & payments", -1),
    ("Returns handling", "Fulfillment & payments", -1),
    ("Meta advertising", "Marketing", -1),
    ("Google advertising", "Marketing", -1),
    ("Salaries", "People", -1),
    ("Employer payroll taxes", "People", -1),
    ("Health benefits", "People", -1),
    ("Office rent", "G&A", -1),
    ("Software subscriptions", "G&A", -1),
    ("Insurance", "G&A", -1),
    ("Professional fees", "G&A", -1),
    ("Depreciation", "Below EBITDA", -1),
    ("Interest", "Below EBITDA", -1),
]
SIGN = {l: s for l, _, s in PNL}
SECTION = {l: sec for l, sec, _ in PNL}
FIXED_LINES = {"Salaries", "Employer payroll taxes", "Health benefits", "Office rent", "Software subscriptions",
               "Insurance", "Professional fees", "Depreciation"}


def subtotals(v):
    """v: dict line->cents (positive natural amounts). returns dict of subtotals."""
    g = lambda l: v.get(l, 0)
    net_rev = g("Gross product sales") - g("Sales discounts") - g("Merchandise returns") + g("Shipping income")
    gp = net_rev - g("Merchandise COGS") - g("Inventory writeoffs")
    contrib_ful = gp - sum(g(l) for l in ["Merchant fees", "Outbound fulfillment", "Warehouse storage", "Returns handling"])
    contrib = contrib_ful - g("Meta advertising") - g("Google advertising")
    ebitda = contrib - sum(g(l) for l in ["Salaries", "Employer payroll taxes", "Health benefits", "Office rent",
                                          "Software subscriptions", "Insurance", "Professional fees"])
    ni = ebitda - g("Depreciation") - g("Interest")
    return {"Net revenue": net_rev, "Gross profit": gp, "Contribution after fulfillment": contrib_ful,
            "Contribution margin": contrib, "EBITDA": ebitda, "Net income": ni}


recon = []


def add_recon(area, check, expected, actual, sources, tol=0, unit="USD", note=""):
    diff = (actual - expected) if (expected is not None and actual is not None) else None
    ok = diff is not None and abs(diff) <= tol
    recon.append({"area": area, "check": check, "expected": expected, "actual": actual,
                  "difference": diff, "status": "PASS" if ok else "FAIL", "sources": sources, "unit": unit, "note": note})


# ---------------------------------------------------------------- general ledger
gl_parts = []
for f in sorted(glob.glob(os.path.join(SRC, "quickbooks/general_ledger/*.csv"))):
    d = pd.read_csv(f, encoding="utf-8-sig", dtype=str, usecols=["journal_id", "transaction_date", "account_code", "debit", "credit"])
    d["dr"], d["cr"] = c(d.debit), c(d.credit)
    d["period"] = d.transaction_date.str[:7]
    gl_parts.append(d[["journal_id", "period", "transaction_date", "account_code", "dr", "cr"]])
gl = pd.concat(gl_parts, ignore_index=True)
del gl_parts
CUTOFF = D(gl.transaction_date.max())
PERIODS = sorted(gl.period.unique())
gl_lines = len(gl)

jb = gl.groupby("journal_id")[["dr", "cr"]].sum()
add_recon("Ledger", "Every journal balances (debits = credits)", 0, int((jb.dr != jb.cr).sum()),
          "quickbooks/general_ledger/*.csv", unit="journals", note=f"{len(jb):,} journals, {gl_lines:,} lines")

pa = gl.groupby(["period", "account_code"])[["dr", "cr"]].sum().reset_index()
del gl

# natural positive amount per P&L line
pa["line"] = pa.account_code.map(LINE_OF)
pnl_rows = pa[pa.line.isin(SIGN)].copy()
inc_lines = {"Gross product sales", "Shipping income"}
pnl_rows["amt"] = np.where(pnl_rows.line.isin(inc_lines), pnl_rows.cr - pnl_rows.dr, pnl_rows.dr - pnl_rows.cr)
ACT = {(p, l): int(a) for p, l, a in pnl_rows.groupby(["period", "line"]).amt.sum().reset_index().itertuples(index=False)}

# trial balance check: GL cumulative vs TB closing
otb = rd("quickbooks/opening_trial_balance.csv")
tb = rd("quickbooks/monthly_trial_balance.csv")
tb["close"] = c(tb.closing_signed_balance)
open_bal = dict(zip(otb.account_code, c(otb.debit) - c(otb.credit)))
pa["net"] = pa.dr - pa.cr
cum = pa.pivot_table(index="period", columns="account_code", values="net", aggfunc="sum", fill_value=0).cumsum()
mism = 0
for r in tb.itertuples(index=False):
    calc = open_bal.get(r.account_code, 0) + (cum.at[r.period, r.account_code] if r.account_code in cum.columns else 0)
    mism += int(calc != r.close)
add_recon("Ledger", "GL running balances = monthly trial balance (all accounts x 24 months)", 0, mism,
          "general_ledger + opening_trial_balance vs monthly_trial_balance", unit="mismatches", note=f"{len(tb)} account-months")
TB = {(r.period, r.account_code): int(r.close) for r in tb.itertuples(index=False)}

# ---------------------------------------------------------------- budget + plan extension + latest estimate
bud = rd("planning/approved_budget_monthly.csv")
bud["amt"] = c(bud.amount)
BUD = {(r.period, r.reporting_line): int(r.amt) for r in bud.itertuples(index=False)}
BUD_VER = dict(zip(bud.period, bud.budget_version))


def mlist(a, b):
    out, y, m = [], int(a[:4]), int(a[5:])
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13: y, m = y + 1, 1
    return out


def yago(p):
    return f"{int(p[:4]) - 1}{p[4:]}"


LAST = PERIODS[-1]                      # 2026-10
FY = LAST[:4]                           # 2026
FY_REST = mlist(f"{int(LAST[:4])}-{int(LAST[5:]) + 1:02d}", f"{FY}-12") if LAST[5:] != "12" else []
FY_YTD = mlist(f"{FY}-01", LAST)
LINES = [l for l, _, _ in PNL]

# Plan extension: same planning logic as the approved FY plan (plan vs prior-year actual), applied to the
# missing months of the fiscal year. Fixed-cost lines continue at the last approved monthly amount.
plan_ext, plan_basis = {}, {}
for l in LINES:
    b_ytd = sum(BUD.get((p, l), 0) for p in FY_YTD)
    a_ly = sum(ACT.get((yago(p), l), 0) for p in FY_YTD)
    ratio = b_ytd / a_ly if a_ly else 1.0
    for p in FY_REST:
        if l in FIXED_LINES or l == "Interest":
            plan_ext[(p, l)] = BUD.get((LAST, l), 0)
            plan_basis[l] = f"Last approved monthly amount ({LAST})"
        else:
            plan_ext[(p, l)] = int(round(ACT.get((yago(p), l), 0) * ratio))
            plan_basis[l] = f"Same month last year x {ratio:.3f} (approved FY{FY} plan Jan-{LAST[5:]} / FY{int(FY)-1} actual)"

# Latest estimate (forecast) for remaining months: trailing 3-month YoY run rate on variable lines,
# current run rate on fixed lines, contractual interest.
T3 = PERIODS[-3:]
le, le_basis = {}, {}
term_bal = 0
dr_ = rd("finance/debt_register_asof.csv")
term = dr_[dr_.facility_type == "amortizing_term_loan"].iloc[0]
tb_principal = int(c(pd.Series([term.principal_outstanding]))[0])
tb_rate = float(term.annual_interest_rate)
tb_amort = int(c(pd.Series([term.monthly_principal_payment]))[0])
for l in LINES:
    cur = sum(ACT.get((p, l), 0) for p in T3)
    ly = sum(ACT.get((yago(p), l), 0) for p in T3)
    ratio = cur / ly if ly else 1.0
    bal = tb_principal
    for p in FY_REST:
        if l == "Interest":
            le[(p, l)] = int(round(bal * tb_rate / 12))
            bal -= tb_amort
            le_basis[l] = "Contractual: 9% x outstanding term-loan principal / 12"
        elif l in FIXED_LINES:
            le[(p, l)] = ACT.get((LAST, l), 0)
            le_basis[l] = f"Current monthly run rate ({LAST} actual)"
        else:
            le[(p, l)] = int(round(ACT.get((yago(p), l), 0) * ratio))
            le_basis[l] = f"Same month last year x {ratio:.3f} (trailing 3-month YoY)"

pnl_out = []
for p in PERIODS + FY_REST:
    for l in LINES:
        is_act = p in PERIODS
        a = ACT.get((p, l), 0) if is_act else None
        b = BUD.get((p, l)) if (p, l) in BUD else plan_ext.get((p, l))
        pnl_out.append({"period": p, "fiscal_year": p[:4], "line": l, "section": SECTION[l], "sign": SIGN[l],
                        "actual": usd(a) if a is not None else None,
                        "budget": usd(b) if b is not None else None,
                        "budget_version": BUD_VER.get(p, f"FY{p[:4]}_PLAN_EXT_v1 (drafted by Claude)"),
                        "forecast": usd(le[(p, l)]) if (p, l) in le else None,
                        "scenario": "Actual" if is_act else "Forecast"})

# control total reconciliation: P&L subtotals vs validation/monthly_control_totals.csv (validation only)
ctl_path = os.path.join(ROOT, "validation/monthly_control_totals.csv")
ctl = pd.read_csv(ctl_path, encoding="utf-8-sig", dtype=str).set_index("period") if os.path.exists(ctl_path) else None
mrows = []
for p in PERIODS:
    v = {l: ACT.get((p, l), 0) for l in LINES}
    st = subtotals(v)
    mrows.append((p, st))
if ctl is not None:
    for key, col in [("Net revenue", "recognized_net_revenue"), ("Gross profit", "gross_profit"), ("EBITDA", "ebitda"), ("Net income", "net_income")]:
        bad = sum(1 for p, st in mrows if p in ctl.index and st[key] != int(round(float(ctl.at[p, col]) * 100)))
        add_recon("P&L", f"{key} by month = control totals", 0, bad, "general_ledger vs validation/monthly_control_totals.csv", unit="months off")
    for acct, col, nm in [("1000", "cash_closing", "Bank cash"), ("1200", "inventory_closing", "Inventory"), ("1300", "supplier_advances", "Supplier advances"),
                          ("2000", "accounts_payable", "Accounts payable"), ("2110", "payroll_payable", "Payroll payable")]:
        sign = 1 if acct[0] == "1" else -1
        bad = sum(1 for p in PERIODS if TB[(p, acct)] * sign != int(round(float(ctl.at[p, col]) * 100)))
        add_recon("Balance sheet", f"{nm} month-end = control totals", 0, bad, "monthly_trial_balance vs control totals", unit="months off")

# ---------------------------------------------------------------- balance sheet schedule
BS = [("1000", "Cash", 1), ("1010", "Processor clearing", 1), ("1200", "Inventory", 1), ("1300", "Supplier advances", 1),
      ("2000", "Accounts payable", -1), ("2100", "Sales tax payable", -1), ("2110", "Payroll payable", -1),
      ("2200", "Customer deposits (paid, unshipped)", -1), ("2300", "Term loan", -1), ("2400", "Revolver", -1)]
bs_out = [{"period": p, "item": nm, "account_code": a, "balance": usd(TB[(p, a)] * s)} for p in PERIODS for a, nm, s in BS]

# ---------------------------------------------------------------- bank
bank = rd("bank/operating_account_statement.csv")
bank["amt"] = c(bank.amount) * np.where(bank.direction == "CREDIT", 1, -1)
ob = rd("bank/account_opening_balance.csv")
bank_open = int(c(ob.opening_balance)[0])
bank["period"] = bank.posted_date.str[:7]
bank_close = bank_open + int(bank.amt.sum())
bad = 0
run = bank_open
for p in PERIODS:
    run += int(bank[bank.period == p].amt.sum())
    bad += int(run != TB[(p, "1000")])
add_recon("Cash", "Bank statement month-end balance = GL cash (1000)", 0, bad, "bank statement vs general ledger", unit="months off")
add_recon("Cash", "Bank running balance column is consistent", bank_close, int(c(bank.running_balance.iloc[[-1]]).iloc[0]), "bank/operating_account_statement.csv")

# ---------------------------------------------------------------- Shopify orders / sales
orders = rd("shopify/orders.csv")
orders["created"] = orders.created_at.str[:10]
orders["period"] = orders.created.str[:7]
orders["paid"] = orders.financial_status != "voided"
for col in ["gross_merchandise", "discounts", "subtotal_net", "shipping_charged", "total_tax", "net_customer_payment"]:
    orders[col + "_c"] = c(orders[col])
lines = rd("shopify/order_line_items.csv")
for col in ["gross_line_amount", "discount_amount", "net_line_amount"]:
    lines[col + "_c"] = c(lines[col])
lines["qty"] = lines.quantity.astype(int)
prods = rd("shopify/products.csv")
SKU_CAT = dict(zip(prods.sku, prods.product_category))
SKU_TITLE = dict(zip(prods.sku, prods.title))
SKU_SUP = dict(zip(prods.sku, prods.supplier_id))
lines["category"] = lines.sku.map(SKU_CAT)

txn = rd("shopify/order_transactions.csv")
txn = txn[txn.status == "success"].copy()
txn["amt"] = c(txn.amount)
txn["date"] = txn.processed_at.str[:10]
txn["period"] = txn.date.str[:7]
refunds = rd("shopify/refunds.csv")
refunds["period"] = refunds.processed_at.str[:7]
for col in ["merchandise_refund", "shipping_refund", "tax_refund", "total_refund"]:
    refunds[col + "_c"] = c(refunds[col])
rfl = rd("shopify/refund_line_items.csv")
rfl["merch_c"] = c(rfl.merchandise_refund)
rfl["qty"] = rfl.quantity.astype(int)
rfl = rfl.merge(refunds[["refund_id", "period"]], on="refund_id", how="left")
rfl["category"] = rfl.sku.map(SKU_CAT)

ful = rd("warehouse_3pl/fulfillments.csv")
ful["period"] = ful.fulfilled_date.str[:7]
ful["cost_c"] = c(ful.total_fulfillment_cost)
ful["units"] = ful.units_shipped.astype(int)
ful_orders = set(ful.order_id)
orders["shipped"] = orders.order_id.isin(ful_orders)

# reconciliation: recognized product sales from Shopify lines at dispatch date = GL 4000 / 4050, refunds = GL 4060
lines = lines.merge(ful[["order_id", "fulfilled_date"]], on="order_id", how="left")
lines["rec_period"] = lines.fulfilled_date.str[:7]
shipped_lines = lines[lines.fulfilled_date.notna()]
g4000 = shipped_lines.groupby("rec_period").gross_line_amount_c.sum()
g4050 = shipped_lines.groupby("rec_period").discount_amount_c.sum()
bad = sum(int(g4000.get(p, 0) != ACT.get((p, "Gross product sales"), 0)) + int(g4050.get(p, 0) != ACT.get((p, "Sales discounts"), 0)) for p in PERIODS)
add_recon("Revenue", "Shopify shipped order lines = GL gross sales (4000) and discounts (4050)", 0, bad, "order_line_items + fulfillments vs general_ledger", unit="month-lines off")
r4060 = rfl.groupby("period").merch_c.sum()
bad = sum(int(r4060.get(p, 0) != ACT.get((p, "Merchandise returns"), 0)) for p in PERIODS)
add_recon("Revenue", "Shopify merchandise refunds = GL returns (4060)", 0, bad, "refund_line_items vs general_ledger", unit="months off")
sale_c = txn[txn.kind == "sale"]
add_recon("Revenue", "Captured sales only on paid orders (voided orders have no capture)", 0,
          int(sale_c.order_id.isin(orders[~orders.paid].order_id).sum()), "order_transactions vs orders", unit="captures")

# processor -> bank
bt = rd("shopify_payments/balance_transactions.csv")
bt["net_c"] = c(bt.net)
bt["fee_c"] = c(bt.fee)
payouts = rd("shopify_payments/payouts.csv")
payouts["amt"] = c(payouts.payout_amount)
paid_po = payouts[payouts.status == "paid"]
bank_shop = bank[bank.counterparty_name == "SHOPIFY PAYMENTS"]
add_recon("Cash", "Shopify payouts paid = Shopify deposits in bank", int(paid_po.amt.sum()), int(bank_shop.amt.sum()), "shopify_payments/payouts vs bank statement")
bt_by_po = bt.groupby("payout_id").net_c.sum()
add_recon("Cash", "Payout amounts = sum of their processor balance transactions", 0,
          int((payouts.set_index("payout_id").amt - bt_by_po.reindex(payouts.payout_id).fillna(0).astype("int64").values).ne(0).sum()),
          "payouts vs balance_transactions", unit="payouts off")
unpaid_bt = int(bt[~bt.payout_id.isin(paid_po.payout_id)].net_c.sum())
add_recon("Cash", "Processor balance not yet in bank = GL processor clearing (1010)", TB[(LAST, "1010")], unpaid_bt, "balance_transactions vs GL 1010")
fees_m = bt.assign(period=bt.transaction_date.str[:7]).groupby("period").fee_c.sum()
bad = sum(int(fees_m.get(p, 0) != ACT.get((p, "Merchant fees"), 0)) for p in PERIODS)
add_recon("P&L", "Processor fees = GL merchant fees (6010)", 0, bad, "balance_transactions vs general_ledger", unit="months off")

# ---------------------------------------------------------------- customers (new vs returning)
cust = rd("shopify/customers.csv")
opening = set(cust[cust.opening_customer == "True"].customer_id)
po_ = orders[orders.paid].sort_values("created_at")
first = po_.groupby("customer_id").created_at.min()
po_ = po_.assign(is_first=po_.created_at.values == first.reindex(po_.customer_id).values)
po_["new_customer"] = po_.is_first & ~po_.customer_id.isin(opening)

# ---------------------------------------------------------------- monthly business KPIs
o_m = orders.groupby("period").agg(orders=("order_id", "size"), paid_orders=("paid", "sum")).reset_index()
pm = po_.groupby("period").agg(new_customers=("new_customer", "sum"), active_customers=("customer_id", "nunique"),
                               merch_net=("subtotal_net_c", "sum"), ship_charged=("shipping_charged_c", "sum")).reset_index()
units_m = lines[lines.order_id.isin(po_.order_id)].merge(orders[["order_id", "period"]], on="order_id").groupby("period").qty.sum()
cap_m = txn[txn.kind == "sale"].groupby("period").amt.sum()
ref_m = refunds.groupby("period").agg(refunds=("refund_id", "size"), refund_amt=("total_refund_c", "sum"))
ful_m = ful.groupby("period").agg(shipped=("order_id", "size"), ful_cost=("cost_c", "sum"), units_shipped=("units", "sum"))
sfa = rd("shopify/storefront_daily_analytics.csv")
sfa["period"] = sfa.analytics_date.str[:7]
for col in ["sessions", "add_to_cart_sessions", "checkout_sessions", "paid_orders", "cancelled_orders"]:
    sfa[col] = sfa[col].astype(int)
sfa["sales_c"] = c(sfa.booked_sales_ex_tax)
ses_m = sfa.groupby("period").sessions.sum()

meta = rd("meta_ads/daily_insights.csv")
meta["period"] = meta.date_start.str[:7]
meta["spend_c"] = c(meta.spend)
meta["cv_c"] = c(meta.purchase_conversion_value)
for col in ["impressions", "clicks"]:
    meta[col] = meta[col].astype(int)
meta["purchases"] = meta.purchases.astype(float)
goo = rd("google_ads/daily_campaign_metrics.csv")
goo["period"] = goo.segments_date.str[:7]
goo["spend_c"] = (goo.metrics_cost_micros.astype("int64") / 10000).round().astype("int64")
goo["cv_c"] = c(goo.metrics_conversions_value)
goo["impressions"] = goo.metrics_impressions.astype(int)
goo["clicks"] = goo.metrics_clicks.astype(int)
goo["purchases"] = goo.metrics_conversions.astype(float)
mb = rd("meta_ads/billing_statements.csv"); mb["amt"] = c(mb.amount)
gb = rd("google_ads/billing_statements.csv"); gb["amt"] = c(gb.amount)
for nm, daily, bill, line in [("Meta", meta, mb, "Meta advertising"), ("Google", goo, gb, "Google advertising")]:
    dm = daily.groupby("period").spend_c.sum()
    bm = bill.set_index("billing_period").amt
    bad = sum(int(dm.get(p, 0) != bm.get(p, 0)) + int(dm.get(p, 0) != ACT.get((p, line), 0)) for p in PERIODS)
    add_recon("Marketing", f"{nm} daily spend = monthly bill = GL", 0, bad, f"{nm.lower()}_ads daily + billing vs general_ledger", unit="month checks off")

pr = rd("gusto/payroll_runs.csv")
pr["period"] = pr.pay_period_end.str[:7]
for col in ["gross_pay", "employer_payroll_tax", "total_cash_debit"]:
    pr[col + "_c"] = c(pr[col])
pr["employee_count"] = pr.employee_count.astype(int)
pr_m = pr.groupby("period").agg(gross=("gross_pay_c", "sum"), er_tax=("employer_payroll_tax_c", "sum"), headcount=("employee_count", "max"))
bad = sum(int(pr_m.gross.get(p, 0) != ACT.get((p, "Salaries"), 0)) + int(pr_m.er_tax.get(p, 0) != ACT.get((p, "Employer payroll taxes"), 0)) for p in PERIODS)
add_recon("Payroll", "Payroll register (earned period) = GL salaries and employer taxes", 0, bad, "gusto/payroll_runs vs general_ledger", unit="month checks off")

inv3 = rd("warehouse_3pl/monthly_invoices.csv")
for col in ["pick_pack_and_carrier_cost", "storage_cost", "returns_processing_cost", "total_amount"]:
    inv3[col + "_c"] = c(inv3[col])
i3 = inv3.set_index("billing_period")
bad = sum(int(i3.pick_pack_and_carrier_cost_c.get(p, 0) != ACT.get((p, "Outbound fulfillment"), 0)) + int(i3.storage_cost_c.get(p, 0) != ACT.get((p, "Warehouse storage"), 0)) +
          int(i3.returns_processing_cost_c.get(p, 0) != ACT.get((p, "Returns handling"), 0)) for p in PERIODS)
add_recon("Fulfillment", "3PL monthly invoices = GL fulfillment, storage and returns handling", 0, bad, "warehouse_3pl/monthly_invoices vs general_ledger", unit="month checks off")
bad = sum(int(ful_m.ful_cost.get(p, 0) != i3.pick_pack_and_carrier_cost_c.get(p, 0)) for p in PERIODS)
add_recon("Fulfillment", "Per-order dispatch costs = 3PL pick/pack and carrier invoice", 0, bad, "fulfillments vs monthly_invoices", unit="months off")

# inventory
mei = rd("warehouse_3pl/month_end_inventory.csv")
mei["period"] = mei.snapshot_date.str[:7]
mei["val_c"] = c(mei.inventory_value)
for col in ["quantity_on_hand", "quantity_reserved", "quantity_available"]:
    mei[col] = mei[col].astype(int)
inv_m = mei.groupby("period").agg(inv_value=("val_c", "sum"), inv_units=("quantity_on_hand", "sum"),
                                  stockout_skus=("quantity_available", lambda s: int((s <= 0).sum())))
bad = sum(int(inv_m.inv_value.get(p, 0) != TB[(p, "1200")]) for p in PERIODS)
add_recon("Inventory", "3PL month-end stock value = GL inventory (1200)", 0, bad, "month_end_inventory vs general_ledger", unit="months off")
mov = rd("warehouse_3pl/inventory_movements.csv")
mov["val_c"] = c(mov.inventory_value_delta)
mov["qty"] = mov.quantity_delta.astype(int)
mov["period"] = mov.movement_date.str[:7]
mov["category"] = mov.sku.map(SKU_CAT)
issue = mov[mov.movement_type == "ORDER_FULFILLMENT"]
restock = mov[mov.movement_type == "CUSTOMER_RETURN_RESTOCK"]
cogs_mv = (-issue.groupby("period").val_c.sum()).sub(restock.groupby("period").val_c.sum(), fill_value=0)
bad = sum(int(cogs_mv.get(p, 0) != ACT.get((p, "Merchandise COGS"), 0)) for p in PERIODS)
add_recon("Inventory", "Stock issues less accepted restocks = GL merchandise COGS (5000)", 0, bad, "inventory_movements vs general_ledger", unit="months off")

kpi = []
for p in PERIODS:
    st = dict(mrows[PERIODS.index(p)][1])
    ad = ACT.get((p, "Meta advertising"), 0) + ACT.get((p, "Google advertising"), 0)
    row = o_m[o_m.period == p].iloc[0]
    prow = pm[pm.period == p].iloc[0]
    paid_n = int(row.paid_orders)
    shipped = int(ful_m.shipped.get(p, 0))
    kpi.append({
        "period": p, "orders": int(row.orders), "paid_orders": paid_n, "cancelled_orders": int(row.orders) - paid_n,
        "shipped_orders": shipped, "units_sold": int(units_m.get(p, 0)),
        "new_customers": int(prow.new_customers), "active_customers": int(prow.active_customers),
        "repeat_order_share": round(1 - int(prow.new_customers) / paid_n, 4) if paid_n else None,
        "aov": usd((prow.merch_net + prow.ship_charged) / paid_n) if paid_n else None,
        "captured_sales": usd(cap_m.get(p, 0)), "refunds_count": int(ref_m.refunds.get(p, 0)), "refunds_amount": usd(ref_m.refund_amt.get(p, 0)),
        "sessions": int(ses_m.get(p, 0)), "conversion_rate": round(paid_n / int(ses_m.get(p, 1)), 4),
        "net_revenue": usd(st["Net revenue"]), "gross_profit": usd(st["Gross profit"]), "contribution_margin": usd(st["Contribution margin"]),
        "ebitda": usd(st["EBITDA"]), "net_income": usd(st["Net income"]),
        "gross_margin_pct": round(st["Gross profit"] / st["Net revenue"], 4), "contribution_pct": round(st["Contribution margin"] / st["Net revenue"], 4),
        "ebitda_pct": round(st["EBITDA"] / st["Net revenue"], 4),
        "ad_spend": usd(ad), "mer": round(st["Net revenue"] / ad, 3) if ad else None,
        "cac_blended": usd(ad / int(prow.new_customers)) if int(prow.new_customers) else None,
        "fulfillment_cost_per_order": usd(ful_m.ful_cost.get(p, 0) / shipped) if shipped else None,
        "return_rate_pct_of_gross": round(ACT.get((p, "Merchandise returns"), 0) / ACT.get((p, "Gross product sales"), 1), 4),
        "headcount": int(pr_m.headcount.get(p, 0)),
        "cash": usd(TB[(p, "1000")]), "inventory_value": usd(inv_m.inv_value.get(p, 0)), "inventory_units": int(inv_m.inv_units.get(p, 0)),
        "stockout_skus": int(inv_m.stockout_skus.get(p, 0)),
        "supplier_advances": usd(TB[(p, "1300")]), "accounts_payable": usd(-TB[(p, "2000")]),
    })
if ctl is not None:
    bad = sum(1 for k in kpi if k["orders"] != int(ctl.at[k["period"], "orders"]) or k["paid_orders"] != int(ctl.at[k["period"], "paid_orders"]))
    add_recon("Revenue", "Order counts (all / paid) = control totals", 0, bad, "shopify/orders vs control totals", unit="months off")

# ---------------------------------------------------------------- category and SKU economics (recognized at dispatch)
cat_rows = []
sl = shipped_lines.copy()
sl_c = sl.groupby(["rec_period", "category"]).agg(gross=("gross_line_amount_c", "sum"), disc=("discount_amount_c", "sum"), units=("qty", "sum"))
rf_c = rfl.groupby(["period", "category"]).agg(ret=("merch_c", "sum"), ret_units=("qty", "sum"))
iss_c = (-issue.groupby(["period", "category"]).val_c.sum())
rst_c = restock.groupby(["period", "category"]).val_c.sum()
for p in PERIODS:
    for cat in sorted(set(SKU_CAT.values())):
        g = sl_c.loc[(p, cat)] if (p, cat) in sl_c.index else None
        gross = int(g.gross) if g is not None else 0
        disc = int(g.disc) if g is not None else 0
        ret = int(rf_c.ret.get((p, cat), 0))
        cogs = int(iss_c.get((p, cat), 0)) - int(rst_c.get((p, cat), 0))
        net = gross - disc - ret
        cat_rows.append({"period": p, "category": cat, "gross_sales": usd(gross), "discounts": usd(disc), "returns": usd(ret),
                         "net_product_sales": usd(net), "cogs": usd(cogs), "gross_profit": usd(net - cogs),
                         "gross_margin_pct": round((net - cogs) / net, 4) if net else None,
                         "units_shipped": int(g.units) if g is not None else 0, "units_returned": int(rf_c.ret_units.get((p, cat), 0))})

L12 = PERIODS[-12:]
P12 = PERIODS[-24:-12]
mei_last = mei[mei.period == LAST].set_index("sku")
sku_rows = []
last90 = (CUTOFF - dt.timedelta(days=89)).isoformat()
u90 = issue[issue.movement_date >= last90].groupby("sku").qty.sum().abs()
for sku in sorted(SKU_CAT):
    a = sl[(sl.sku == sku) & sl.rec_period.isin(L12)]
    b = sl[(sl.sku == sku) & sl.rec_period.isin(P12)]
    ret = int(rfl[(rfl.sku == sku) & rfl.period.isin(L12)].merch_c.sum())
    cogs = int(-issue[(issue.sku == sku) & issue.period.isin(L12)].val_c.sum() - restock[(restock.sku == sku) & restock.period.isin(L12)].val_c.sum())
    net = int(a.gross_line_amount_c.sum() - a.discount_amount_c.sum()) - ret
    net_py = int(b.gross_line_amount_c.sum() - b.discount_amount_c.sum()) - int(rfl[(rfl.sku == sku) & rfl.period.isin(P12)].merch_c.sum())
    mi = mei_last.loc[sku] if sku in mei_last.index else None
    avail = int(mi.quantity_available) if mi is not None else 0
    dly = u90.get(sku, 0) / 90
    sku_rows.append({"sku": sku, "title": SKU_TITLE[sku], "category": SKU_CAT[sku], "supplier_id": SKU_SUP[sku],
                     "l12m_net_sales": usd(net), "p12m_net_sales": usd(net_py), "yoy_growth": round(net / net_py - 1, 4) if net_py else None,
                     "l12m_units": int(a.qty.sum()), "l12m_cogs": usd(cogs), "l12m_gross_margin_pct": round((net - cogs) / net, 4) if net else None,
                     "l12m_return_rate": round(ret / int(a.gross_line_amount_c.sum()), 4) if len(a) else None,
                     "on_hand_units": int(mi.quantity_on_hand) if mi is not None else 0, "available_units": avail,
                     "inventory_value": usd(mi.val_c) if mi is not None else 0,
                     "days_of_cover": round(avail / dly, 1) if dly > 0 else None})

# ---------------------------------------------------------------- channels / marketing
ch_rows = sfa.groupby(["period", "channel_group"]).agg(sessions=("sessions", "sum"), add_to_cart=("add_to_cart_sessions", "sum"), checkouts=("checkout_sessions", "sum"),
                                                       paid_orders=("paid_orders", "sum"), booked_sales_ex_tax=("sales_c", "sum")).reset_index()
ch_out = [{"period": r.period, "channel": r.channel_group, "sessions": int(r.sessions), "add_to_cart_sessions": int(r.add_to_cart), "checkout_sessions": int(r.checkouts),
           "paid_orders": int(r.paid_orders), "booked_sales_ex_tax": usd(r.booked_sales_ex_tax), "conversion_rate": round(r.paid_orders / r.sessions, 4) if r.sessions else None}
          for r in ch_rows.itertuples(index=False)]
mk_out = []
mcamp = dict(zip(rd("meta_ads/campaigns.csv").campaign_id, rd("meta_ads/campaigns.csv").iloc[:, 1]))
gcamp = dict(zip(rd("google_ads/campaigns.csv").campaign_id, rd("google_ads/campaigns.csv").iloc[:, 1]))
for nm, daily, cmap in [("Meta", meta, mcamp), ("Google", goo, gcamp)]:
    g = daily.groupby(["period", "campaign_id"]).agg(spend=("spend_c", "sum"), impressions=("impressions", "sum"), clicks=("clicks", "sum"),
                                                     purchases=("purchases", "sum"), conv_value=("cv_c", "sum")).reset_index()
    for r in g.itertuples(index=False):
        mk_out.append({"period": r.period, "platform": nm, "campaign": cmap.get(r.campaign_id, r.campaign_id), "spend": usd(r.spend),
                       "impressions": int(r.impressions), "clicks": int(r.clicks), "platform_purchases": round(float(r.purchases), 2),
                       "platform_attributed_value": usd(r.conv_value), "platform_roas": round(r.conv_value / r.spend, 3) if r.spend else None,
                       "cpc": usd(r.spend / r.clicks) if r.clicks else None, "ctr": round(r.clicks / r.impressions, 4) if r.impressions else None})

# ---------------------------------------------------------------- suppliers
sup = rd("purchasing/suppliers.csv")
pos = rd("purchasing/purchase_orders.csv")
pos["total_c"] = c(pos.total_amount)
inb = rd("purchasing/inbound_shipments.csv")
rcv = inb[inb.actual_arrival_date.notna()].copy()
rcv["delay"] = (pd.to_datetime(rcv.actual_arrival_date) - pd.to_datetime(rcv.original_expected_arrival_date)).dt.days
rcv = rcv.merge(pos[["purchase_order_id", "supplier_id"]], on="purchase_order_id")
sched = rd("purchasing/payment_schedule.csv")
sched["out_c"] = c(sched.outstanding_amount)
sup_rows = []
for s in sup.itertuples(index=False):
    sp = pos[pos.supplier_id == s.supplier_id]
    sr = rcv[rcv.supplier_id == s.supplier_id]
    sup_rows.append({"supplier_id": s.supplier_id, "supplier": s.legal_name, "country": s.country_code, "category": s.category,
                     "standard_lead_days": int(s.standard_lead_days), "purchase_orders": int(len(sp)),
                     "l12m_po_value": usd(sp[sp.order_date >= f"{L12[0]}-01"].total_c.sum()),
                     "open_pos": int((sp.status != "received").sum()),
                     "on_time_share": round(float((sr.delay <= 0).mean()), 3) if len(sr) else None,
                     "avg_delay_days": round(float(sr.delay.mean()), 1) if len(sr) else None,
                     "open_payment_commitments": usd(sched[(sched.supplier_id == s.supplier_id)].out_c.sum()),
                     "supplier_advance_balance": usd(c(sp.supplier_advance_balance).sum())})

# ---------------------------------------------------------------- 13-week cash forecast
H0 = CUTOFF + dt.timedelta(days=1)
WEEKS = [(H0 + dt.timedelta(days=7 * i), H0 + dt.timedelta(days=7 * i + 6)) for i in range(13)]
H1 = WEEKS[-1][1]


def wk(d):
    i = (d - H0).days // 7
    return i + 1 if 0 <= i < 13 else None


def bday(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def next_bday(d):
    return bday(d + dt.timedelta(days=1))


items = []


def item(d, section, line, cents, kind, basis, source, driver=None):
    if isinstance(d, str): d = D(d)
    if d < H0 or d > H1 or cents == 0: return
    items.append({"date": d.isoformat(), "week": wk(d), "section": section, "line": line, "amount": usd(cents),
                  "kind": kind, "basis": basis, "source": source, "driver": driver})


ratio = lambda num, den: (num / den) if den else 1.0
sales_g = ratio(sum(cap_m.get(p, 0) for p in T3), sum(cap_m.get(yago(p), 0) for p in T3))
ref_amt_m = refunds.groupby("period").total_refund_c.sum()
refund_g = ratio(sum(ref_amt_m.get(p, 0) for p in T3), sum(ref_amt_m.get(yago(p), 0) for p in T3))
cogs_g = ratio(sum(ACT.get((p, "Merchandise COGS"), 0) for p in T3), sum(ACT.get((yago(p), "Merchandise COGS"), 0) for p in T3))

# 1) processor balance at cutoff (already captured, not yet in bank)
pend = payouts[payouts.status != "paid"]
for r in pend.itertuples(index=False):
    item(r.estimated_bank_arrival_date, "Inflows", "Shopify payouts in transit", int(r.amt), "Known", f"{r.payout_id} issued {r.issued_date}", "shopify_payments/payouts.csv")
rest = TB[(LAST, "1010")] - int(pend.amt.sum())
item(next_bday(CUTOFF), "Inflows", "Shopify payouts in transit", rest, "Known", "Processor balance at cutoff not yet batched (GL 1010 less in-transit payout)", "general_ledger 1010")

# 2) customer receipts: same weekday last year (364 days back) x trailing-3M YoY growth, less refunds and fees
bt["date"] = bt.transaction_date
charges = bt[bt.type == "CHARGE"].copy()
charges["amt_c"] = c(charges.amount)
ch_d = charges.groupby("date").agg(amt=("amt_c", "sum"), n=("amt_c", "size"))
rf_bt = bt[bt.type != "CHARGE"].copy()
rf_bt["amt_c"] = c(rf_bt.amount)
rf_d = rf_bt.groupby("date").amt_c.sum()
fee_pct, fee_fix = 0.029, 30
d = H0
while d <= H1:
    ly = (d - dt.timedelta(days=364)).isoformat()
    cap = ch_d.amt.get(ly, 0) * sales_g
    n = ch_d.n.get(ly, 0) * sales_g
    refund = rf_d.get(ly, 0) * refund_g  # refund rows carry negative amounts
    fee = cap * fee_pct + n * fee_fix
    arrive = next_bday(d)
    if arrive <= H1:
        items.append({"date": arrive.isoformat(), "week": wk(arrive), "section": "Inflows", "line": "Customer receipts (net of refunds and fees)",
                      "amount": usd(round(cap + refund - fee)), "kind": "Estimated", "driver": "sales",
                      "basis": f"Same weekday last year x {sales_g:.3f} sales growth; refunds x {refund_g:.3f}; fees 2.9% + $0.30",
                      "source": "shopify_payments/balance_transactions.csv"})
    d += dt.timedelta(days=1)

# 3) supplier PO balances (schedule covers open merchandise bills of the same PO - no double count)
open_sched = sched[sched.out_c > 0]
for r in open_sched.itertuples(index=False):
    item(r.scheduled_payment_date, "Outflows", "Supplier payments - open POs", -int(r.out_c), "Known",
         f"{r.purchase_order_id} {r.installment} ({r.supplier_id})", "purchasing/payment_schedule.csv")
bills = rd("quickbooks/bills.csv")
bills["bal_c"] = c(bills.balance_due)
openb = bills[bills.bal_c > 0]
merch_b = openb[openb.purchase_order_id.notna()]
uncovered = merch_b[~merch_b.purchase_order_id.isin(open_sched.purchase_order_id)]
for r in uncovered.itertuples(index=False):
    item(r.due_date, "Outflows", "Supplier payments - open POs", -int(r.bal_c), "Known", f"{r.bill_id} not covered by a PO schedule", "quickbooks/bills.csv")
ov_po = merch_b[merch_b.purchase_order_id.isin(open_sched.purchase_order_id)]
add_recon("Cash forecast", "Open supplier bills already inside PO payment schedules (counted once)", int(ov_po.bal_c.sum()),
          int(sum(min(open_sched[open_sched.purchase_order_id == p].out_c.sum(), ov_po[ov_po.purchase_order_id == p].bal_c.sum()) for p in ov_po.purchase_order_id.unique())),
          "bills vs payment_schedule", note=f"{ov_po.purchase_order_id.nunique()} POs; excluded from forecast as separate lines")

# 4) new replenishment POs not yet placed: last year's cash paid in the same window on POs ordered after last year's cutoff
spay = rd("purchasing/supplier_payments.csv")
spay["amt"] = c(spay.amount)
spay = spay.merge(pos[["purchase_order_id", "order_date"]], on="purchase_order_id", how="left")
ly0, ly1 = (H0 - dt.timedelta(days=364)).isoformat(), (H1 - dt.timedelta(days=364)).isoformat()
ly_cut = (CUTOFF - dt.timedelta(days=364)).isoformat()
lyp = spay[(spay.payment_date >= ly0) & (spay.payment_date <= ly1) & (spay.order_date > ly_cut)]
for r in lyp.itertuples(index=False):
    item(D(r.payment_date) + dt.timedelta(days=364), "Outflows", "Supplier payments - new POs (not yet placed)", -int(round(r.amt * cogs_g)), "Estimated",
         f"Last-year analog x {cogs_g:.3f} COGS growth", "purchasing/supplier_payments.csv", driver="purchasing")

# 5) payroll: accrued at cutoff + future semi-monthly runs at current salaries
pdb = rd("gusto/payroll_bank_debits.csv")
item(next_bday(CUTOFF), "Outflows", "Payroll (net pay + taxes)", TB[(LAST, "2110")], "Known", "Earned Oct 16-31, funded on check date", "GL 2110 / gusto/payroll_runs.csv")
emp = rd("gusto/employees.csv")
sh = rd("gusto/salary_history.csv")
act_emp = emp[emp.employment_status == "active"].employee_id
cur_sal = sh[sh.employee_id.isin(act_emp) & sh.effective_to.isna()]
run_gross = int(round(c(cur_sal.annual_salary).sum() / 24))
run_tax = int(round(run_gross * 0.081))
y, m = H0.year, H0.month
while True:
    for a, b in [(1, 15), (16, None)]:
        end = dt.date(y, m, b) if b else (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        chk = next_bday(end)
        if chk > H1: break
        item(chk, "Outflows", "Payroll (net pay + taxes)", -(run_gross + run_tax), "Known",
             f"Period to {end.isoformat()}: {len(act_emp)} active salaries / 24 + 8.1% employer tax", "gusto/salary_history.csv")
    m += 1
    if m == 13: y, m = y + 1, 1
    if dt.date(y, m, 1) > H1: break

# 6) open operating bills (ads, 3PL, contracts) at due date
VLINE = {"V-META": "Meta advertising", "V-GOOGLE": "Google advertising", "V-3PL": "3PL fulfillment & storage"}
for r in openb[openb.purchase_order_id.isna()].itertuples(index=False):
    item(r.due_date, "Outflows", VLINE.get(r.vendor_id, "Rent, software, insurance, benefits, fees"), -int(r.bal_c), "Known", f"{r.bill_id} open bill", "quickbooks/bills.csv")

# 7) future monthly bills: ads and 3PL use LE spend; contracts use contract terms (next cycles after the open bills)
FUT = [p for p in FY_REST + [f"{int(FY)+1}-01"]]
for vend, bill_df, line in [("V-META", mb, "Meta advertising"), ("V-GOOGLE", gb, "Google advertising")]:
    for p in FUT:
        lyrow = bill_df[bill_df.billing_period == yago(p)]
        if lyrow.empty: continue
        lag = (D(lyrow.due_date.iloc[0]) - D(lyrow.invoice_date.iloc[0])).days
        inv_d = (dt.date(int(p[:4]) + (p[5:] == "12"), int(p[5:]) % 12 + 1, 1) - dt.timedelta(days=1))
        amt = le.get((p, line))
        if amt is None:
            amt = int(round(ACT.get((yago(p), line), 0) * ratio(sum(ACT.get((q, line), 0) for q in T3), sum(ACT.get((yago(q), line), 0) for q in T3))))
        item(inv_d + dt.timedelta(days=lag), "Outflows", line, -amt, "Estimated", f"{p} spend (forecast) billed month-end, paid +{lag} days", f"{line} forecast", driver="ads")
for p in FUT:
    lyrow = inv3[inv3.billing_period == yago(p)]
    if lyrow.empty: continue
    lag = (D(lyrow.due_date.iloc[0]) - D(lyrow.invoice_date.iloc[0])).days
    inv_d = (dt.date(int(p[:4]) + (p[5:] == "12"), int(p[5:]) % 12 + 1, 1) - dt.timedelta(days=1))
    amt = 0
    for line in ["Outbound fulfillment", "Warehouse storage", "Returns handling"]:
        v = le.get((p, line))
        if v is None:
            v = int(round(ACT.get((yago(p), line), 0) * ratio(sum(ACT.get((q, line), 0) for q in T3), sum(ACT.get((yago(q), line), 0) for q in T3))))
        amt += v
    item(inv_d + dt.timedelta(days=lag), "Outflows", "3PL fulfillment & storage", -amt, "Estimated", f"{p} 3PL invoice (forecast), paid +{lag} days", "warehouse_3pl forecast", driver="sales")
obl = rd("planning/recurring_obligations_asof.csv")
n_act = len(act_emp)
for r in obl.itertuples(index=False):
    if r.amount_basis not in ("fixed_amount", "fixed_plus_active_employee", "per_active_employee"): continue
    base = int(c(pd.Series([r.amount_or_rate]))[0])
    per = {"V-SAAS": 2200, "V-GUSTO": 1200}.get(r.vendor_or_source, 0)
    amt = base * n_act if r.amount_basis == "per_active_employee" else base + per * n_act
    nd = D(r.next_due_date)
    has_bill = not openb[(openb.vendor_id == r.vendor_or_source) & (openb.due_date == r.next_due_date)].empty
    k = 1 if has_bill else 0   # next_due_date already represented by an open bill -> start with the following cycle
    while True:
        mm = nd.month - 1 + k
        due = dt.date(nd.year + mm // 12, mm % 12 + 1, min(nd.day, 28))
        if due > H1: break
        item(due, "Outflows", "Rent, software, insurance, benefits, fees", -amt, "Known",
             f"{r.obligation_id} {r.cost_category}: contract cycle" + (" (open bill covers the first due date)" if has_bill else ""), "planning/recurring_obligations_asof.csv")
        k += 1

# 8) sales tax: open remittance + forecast for future collection months
stx = rd("finance/sales_tax_remittances.csv")
stx["amt"] = c(stx.amount)
for r in stx[stx.paid_date.isna()].itertuples(index=False):
    item(r.due_date, "Outflows", "Sales tax remittance", -int(r.amt), "Known", f"{r.remittance_id} collected {r.collection_period}", "finance/sales_tax_remittances.csv")
for p in FUT:
    lyrow = stx[stx.collection_period == yago(p)]
    if lyrow.empty: continue
    due = bday(dt.date(int(p[:4]) + (p[5:] == "12"), int(p[5:]) % 12 + 1, 20))
    item(due, "Outflows", "Sales tax remittance", -int(round(lyrow.amt.iloc[0] * sales_g)), "Estimated", f"{p} collections: last year x {sales_g:.3f}", "finance/sales_tax_remittances.csv", driver="sales")

# 9) term loan
bal = tb_principal
nd = D(term.next_payment_date)
while nd <= H1:
    intr = int(round(bal * tb_rate / 12))
    item(nd, "Financing", "Term loan principal + interest", -(tb_amort + intr), "Known", f"Principal ${tb_amort/100:,.0f} + 9% interest on ${bal/100:,.0f}", "finance/debt_register_asof.csv")
    bal -= tb_amort
    nd = dt.date(nd.year + (nd.month == 12), nd.month % 12 + 1, nd.day)

# 10) owner distribution policy: quarterly on the 25th, up to $200k while keeping $250k working cash
DIST_MAX, DIST_FLOOR = 20000000, 25000000
items.sort(key=lambda x: x["date"])
open_cash = TB[(LAST, "1000")]
dist_dates = [dt.date(y, mth, 25) for y in (H0.year, H0.year + 1) for mth in (3, 6, 9, 12) if H0 <= dt.date(y, mth, 25) <= H1]
for dd in dist_dates:
    bal_before = open_cash + sum(int(round(x["amount"] * 100)) for x in items if x["date"] < dd.isoformat())
    amt = max(0, min(DIST_MAX, bal_before - DIST_FLOOR))
    items.append({"date": dd.isoformat(), "week": wk(dd), "section": "Financing", "line": "Owner distribution (policy, discretionary)",
                  "amount": usd(-amt), "kind": "Policy", "driver": "distribution",
                  "basis": f"Quarterly: min($200k, cash above $250k floor); cash before = ${bal_before/100:,.0f}", "source": "finance/owner_distributions.csv (pattern)"})
items.sort(key=lambda x: (x["date"], x["section"]))

weeks_out = [{"week": i + 1, "start": a.isoformat(), "end": b.isoformat(), "label": f"W{i+1} {a.strftime('%b')} {a.day}-{b.day if a.month == b.month else b.strftime('%b ') + str(b.day)}"} for i, (a, b) in enumerate(WEEKS)]
cash_assump = [
    {"assumption": "Sales growth vs last year (receipts, sales tax)", "value": round(sales_g, 4), "basis": f"Captured sales {T3[0]}..{T3[-1]} vs same months last year"},
    {"assumption": "Refund growth vs last year", "value": round(refund_g, 4), "basis": "Refund payments, trailing 3 months YoY"},
    {"assumption": "COGS growth vs last year (new POs)", "value": round(cogs_g, 4), "basis": "GL 5000, trailing 3 months YoY"},
    {"assumption": "Processing fee", "value": "2.9% + $0.30", "basis": "Case parameter"},
    {"assumption": "Payroll per semi-monthly run", "value": usd(run_gross + run_tax), "basis": f"{n_act} active employees, current salaries / 24, +8.1% employer tax"},
    {"assumption": "Owner distribution policy", "value": "min($200k, cash - $250k)", "basis": "Observed quarterly pattern on the 25th (Mar/Jun/Sep/Dec)"},
    {"assumption": "Revolver available", "value": usd(int(c(dr_[dr_.facility_type == 'revolving_credit_line'].original_or_limit_amount).iloc[0]) - int(c(dr_[dr_.facility_type == 'revolving_credit_line'].principal_outstanding).iloc[0])), "basis": "LOC-001, 10.5%, undrawn"},
]

# ---------------------------------------------------------------- product profitability (cost allocation to SKU)
# Every monthly P&L pool is pushed down to SKU level, either directly (sales, discounts, returns, COGS,
# write-offs) or with an activity driver. Allocated pools are rounded with the largest-remainder method so
# that the SKU rows add up to the general ledger to the cent.
WEIGHT = dict(zip(prods.sku, pd.to_numeric(prods.unit_weight_kg)))
SKUS = sorted(SKU_CAT)


def alloc(pool, drv):
    """pool: int cents; drv: dict sku->driver (>=0). returns dict sku->int cents summing to pool"""
    drv = {k: max(0.0, float(v)) for k, v in drv.items() if v and v > 0}
    tot = sum(drv.values())
    if pool == 0: return {}
    if tot <= 0: return {"_unallocated": pool}
    raw = {k: pool * v / tot for k, v in drv.items()}
    base = {k: int(np.floor(x)) for k, x in raw.items()}
    rem = pool - sum(base.values())
    for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[:rem]:
        base[k] += 1
    return base


lines["w"] = lines.qty * lines.sku.map(WEIGHT)
ord_net = lines.groupby("order_id").net_line_amount_c.transform("sum")
lines["net_share"] = np.where(ord_net > 0, lines.net_line_amount_c / ord_net.replace(0, 1), 0)
ord_w = lines.groupby("order_id").w.transform("sum")
lines["w_share"] = np.where(ord_w > 0, lines.w / ord_w.replace(0, 1), 0)
lines["order_period"] = lines.order_id.map(dict(zip(orders.order_id, orders.period)))

# drivers by month x sku
ship_ord = dict(zip(orders.order_id, orders.shipping_charged_c))
sl2 = lines[lines.fulfilled_date.notna()].copy()
sl2["ship_drv"] = sl2.order_id.map(ship_ord).fillna(0) * sl2.net_share
fee_ord = bt[bt.type == "CHARGE"].assign(period=lambda d: d.transaction_date.str[:7]).groupby(["order_id", "period"]).fee_c.sum().reset_index()
fl = lines.merge(fee_ord, on="order_id")
fl["fee_drv"] = fl.fee_c * fl.net_share
fcost = dict(zip(ful.order_id, ful.cost_c))
sl2["ful_drv"] = sl2.order_id.map(fcost).fillna(0) * sl2.w_share
mei["cube"] = mei.quantity_on_hand * mei.sku.map(WEIGHT)
rets = rd("warehouse_3pl/customer_returns.csv")
rets["rp"] = rets.actual_receipt_date.str[:7]
rets["qty"] = rets.quantity.astype(int)
adj = rd("warehouse_3pl/stock_adjustments.csv")
adj["period"] = adj.adjustment_date.str[:7]
adj["cost_c"] = c(adj.inventory_cost_removed)

# campaign attribution (Shopify last non-direct click: utm_campaign_id on paid orders)
paid_ord = orders[orders.paid & orders.utm_campaign_id.notna()][["order_id", "utm_campaign_id", "period", "customer_id", "subtotal_net_c", "shipping_charged_c"]]
att_lines = lines.merge(paid_ord[["order_id", "utm_campaign_id"]], on="order_id")
spend_cm = pd.concat([meta.groupby(["period", "campaign_id"]).spend_c.sum().reset_index().assign(platform="Meta"),
                      goo.groupby(["period", "campaign_id"]).spend_c.sum().reset_index().assign(platform="Google")])

G = {k: v.to_dict() for k, v in {
    "gross": sl2.groupby(["rec_period", "sku"]).gross_line_amount_c.sum(),
    "disc": sl2.groupby(["rec_period", "sku"]).discount_amount_c.sum(),
    "units": sl2.groupby(["rec_period", "sku"]).qty.sum(),
    "lines_n": sl2.groupby(["rec_period", "sku"]).order_line_id.count(),
    "ret": rfl.groupby(["period", "sku"]).merch_c.sum(),
    "ret_units": rfl.groupby(["period", "sku"]).qty.sum(),
    "ship": sl2.groupby(["rec_period", "sku"]).ship_drv.sum(),
    "fee": fl.groupby(["period", "sku"]).fee_drv.sum(),
    "ful": sl2.groupby(["rec_period", "sku"]).ful_drv.sum(),
    "cube": mei.groupby(["period", "sku"]).cube.sum(),
    "rq": rets[rets.rp.notna()].groupby(["rp", "sku"]).qty.sum(),
    "iss": (-issue.groupby(["period", "sku"]).val_c.sum()),
    "rst": restock.groupby(["period", "sku"]).val_c.sum(),
    "adj": adj.groupby(["period", "sku"]).cost_c.sum(),
}.items()}


def by_sku(key, p):
    d = G[key]
    return {s: d.get((p, s), 0) for s in SKUS}


ATT = att_lines.groupby(["order_period", "utm_campaign_id", "sku"]).net_line_amount_c.sum().to_dict()
prod_rows, unalloc = [], 0
OVH_PEOPLE = ["Salaries", "Employer payroll taxes", "Health benefits"]
OVH_GA = ["Office rent", "Software subscriptions", "Insurance", "Professional fees"]
for p in PERIODS:
    gross, disc, ret = by_sku("gross", p), by_sku("disc", p), by_sku("ret", p)
    cogs = {s: by_sku("iss", p)[s] - by_sku("rst", p)[s] for s in SKUS}
    A = {}
    A["shipping_income"] = alloc(ACT.get((p, "Shipping income"), 0), by_sku("ship", p))
    A["writeoffs"] = alloc(ACT.get((p, "Inventory writeoffs"), 0), by_sku("adj", p))
    A["merchant_fees"] = alloc(ACT.get((p, "Merchant fees"), 0), by_sku("fee", p))
    A["fulfillment"] = alloc(ACT.get((p, "Outbound fulfillment"), 0), by_sku("ful", p))
    A["storage"] = alloc(ACT.get((p, "Warehouse storage"), 0), by_sku("cube", p))
    rq = by_sku("rq", p)
    A["returns_handling"] = alloc(ACT.get((p, "Returns handling"), 0), rq if sum(rq.values()) else by_sku("ret_units", p))
    mk = {}
    for r in spend_cm[spend_cm.period == p].itertuples(index=False):
        drv = {s: ATT.get((p, r.campaign_id, s), 0) for s in SKUS}
        if sum(drv.values()) <= 0: drv = {s: gross[s] - disc[s] for s in SKUS}
        for s, v in alloc(int(r.spend_c), drv).items(): mk[s] = mk.get(s, 0) + v
    A["marketing"] = mk
    net = {s: gross[s] - disc[s] - ret[s] + A["shipping_income"].get(s, 0) for s in SKUS}
    rev_drv = {s: max(0, net[s]) for s in SKUS}
    lines_drv = by_sku("lines_n", p)
    people, ga = sum(ACT.get((p, l), 0) for l in OVH_PEOPLE), sum(ACT.get((p, l), 0) for l in OVH_GA)
    below = ACT.get((p, "Depreciation"), 0) + ACT.get((p, "Interest"), 0)
    A["people_rev"], A["ga_rev"], A["below_rev"] = alloc(people, rev_drv), alloc(ga, rev_drv), alloc(below, rev_drv)
    A["people_lines"], A["ga_lines"] = alloc(people, lines_drv), alloc(ga, lines_drv)
    unalloc += sum(v.get("_unallocated", 0) for v in A.values())
    for s in SKUS:
        g = lambda k: A[k].get(s, 0)
        gp = net[s] - cogs[s] - g("writeoffs")
        cm1 = gp - g("merchant_fees") - g("fulfillment") - g("storage") - g("returns_handling")
        cm2 = cm1 - g("marketing")
        prod_rows.append({"period": p, "sku": s, "title": SKU_TITLE[s], "category": SKU_CAT[s], "supplier_id": SKU_SUP[s],
                          "units": int(by_sku("units", p)[s]), "order_lines": int(lines_drv[s]), "units_returned": int(by_sku("ret_units", p)[s]),
                          "gross_sales": usd(gross[s]), "discounts": usd(disc[s]), "returns": usd(ret[s]), "shipping_income": usd(g("shipping_income")),
                          "net_revenue": usd(net[s]), "cogs": usd(cogs[s]), "writeoffs": usd(g("writeoffs")), "gross_profit": usd(gp),
                          "merchant_fees": usd(g("merchant_fees")), "fulfillment": usd(g("fulfillment")), "storage": usd(g("storage")),
                          "returns_handling": usd(g("returns_handling")), "contribution_after_fulfillment": usd(cm1),
                          "marketing": usd(g("marketing")), "contribution_after_marketing": usd(cm2),
                          "overhead_people_rev": usd(g("people_rev")), "overhead_ga_rev": usd(g("ga_rev")),
                          "overhead_people_lines": usd(g("people_lines")), "overhead_ga_lines": usd(g("ga_lines")),
                          "ebitda_rev": usd(cm2 - g("people_rev") - g("ga_rev")), "ebitda_lines": usd(cm2 - g("people_lines") - g("ga_lines")),
                          "below_ebitda": usd(g("below_rev"))})
pp = pd.DataFrame(prod_rows)
bad = 0
for p in PERIODS:
    q = pp[pp.period == p]
    st = dict(mrows[PERIODS.index(p)][1])
    bad += int(round(q.net_revenue.sum() * 100) != st["Net revenue"]) + int(round(q.gross_profit.sum() * 100) != st["Gross profit"]) + \
           int(round(q.contribution_after_marketing.sum() * 100) != st["Contribution margin"]) + int(round(q.ebitda_rev.sum() * 100) != st["EBITDA"]) + \
           int(round(q.ebitda_lines.sum() * 100) != st["EBITDA"])
add_recon("Product P&L", "SKU-level P&L adds up to the ledger (net revenue, gross profit, contribution, EBITDA) every month", 0, bad,
          "allocation model vs general_ledger", unit="month checks off", note=f"{len(SKUS)} SKUs x {len(PERIODS)} months; unallocated ${unalloc/100:,.2f}")
add_recon("Product P&L", "Ad spend allocated to SKUs = Meta + Google spend", int(round(sum(ACT.get((p, l), 0) for p in PERIODS for l in ["Meta advertising", "Google advertising"]))),
          int(round(pp.marketing.sum() * 100)), "campaign spend via attributed order lines")

alloc_rules = [
    {"cost_pool": "Gross sales, discounts", "method": "Direct", "driver": "Shopify order lines shipped in the month (dispatch date)"},
    {"cost_pool": "Merchandise returns", "method": "Direct", "driver": "Refund lines by SKU on refund date"},
    {"cost_pool": "Shipping income", "method": "Allocated", "driver": "Shipping charged per shipped order, split to lines by net value"},
    {"cost_pool": "Merchandise COGS", "method": "Direct", "driver": "Weighted-average landed cost of units dispatched, less accepted restocks"},
    {"cost_pool": "Inventory write-offs", "method": "Direct", "driver": "3PL damage and cycle-count adjustments by SKU"},
    {"cost_pool": "Merchant fees", "method": "Allocated", "driver": "Actual processor fee per order, split to lines by net value"},
    {"cost_pool": "Outbound fulfillment", "method": "Allocated", "driver": "Actual 3PL pick/pack + label cost per order, split to lines by shipped weight"},
    {"cost_pool": "Warehouse storage", "method": "Allocated", "driver": "Month-end units on hand x unit weight (space proxy)"},
    {"cost_pool": "Returns handling", "method": "Allocated", "driver": "Returned units received by the 3PL in the month"},
    {"cost_pool": "Meta and Google advertising", "method": "Allocated", "driver": "Each campaign's monthly spend split by the order lines it brought in (Shopify last non-direct click); campaigns with no orders by sales mix"},
    {"cost_pool": "People and G&A overhead", "method": "Allocated", "driver": "Selectable: share of net revenue, or share of order lines (handling effort)"},
    {"cost_pool": "Depreciation and interest", "method": "Allocated", "driver": "Share of net revenue (only for net profit)"},
]

# ---------------------------------------------------------------- marketing ROAS
cm1_pct = {(r["period"], r["sku"]): (r["contribution_after_fulfillment"] / r["net_revenue"]) if r["net_revenue"] > 0 else 0 for r in prod_rows}
po_new = po_[po_.new_customer][["order_id"]].assign(nc=1)
paid_ord = paid_ord.merge(po_new, on="order_id", how="left").fillna({"nc": 0})
ref_by_order = refunds.groupby("order_id").total_refund_c.sum() - refunds.groupby("order_id").tax_refund_c.sum()
paid_ord["refund_ex_tax"] = paid_ord.order_id.map(ref_by_order).fillna(0)
att_contrib = att_lines.assign(cm=lambda d: [v * cm1_pct.get((p, s), 0) for v, p, s in zip(d.net_line_amount_c, d.order_period, d.sku)]) \
    .groupby(["order_period", "utm_campaign_id"]).cm.sum()
camp_names = {**{k: v for k, v in mcamp.items()}, **{k: v for k, v in gcamp.items()}}
mcamp_df, gcamp_df = rd("meta_ads/campaigns.csv"), rd("google_ads/campaigns.csv")
camp_type = {**dict(zip(mcamp_df.campaign_id, mcamp_df.campaign_name.str.split(" \\| ").str[0])), **dict(zip(gcamp_df.campaign_id, gcamp_df.advertising_channel_type.str.title()))}
plat_g = pd.concat([meta.groupby(["period", "campaign_id"]).agg(spend=("spend_c", "sum"), impressions=("impressions", "sum"), clicks=("clicks", "sum"), purchases=("purchases", "sum"), value=("cv_c", "sum")).reset_index().assign(platform="Meta"),
                    goo.groupby(["period", "campaign_id"]).agg(spend=("spend_c", "sum"), impressions=("impressions", "sum"), clicks=("clicks", "sum"), purchases=("purchases", "sum"), value=("cv_c", "sum")).reset_index().assign(platform="Google")])
sf = paid_ord.groupby(["period", "utm_campaign_id"]).agg(orders=("order_id", "size"), rev=("subtotal_net_c", "sum"), ship=("shipping_charged_c", "sum"),
                                                          refunds=("refund_ex_tax", "sum"), new_customers=("nc", "sum")).reset_index()
roas_rows = []
for r in plat_g.itertuples(index=False):
    s = sf[(sf.period == r.period) & (sf.utm_campaign_id == r.campaign_id)]
    o_ = int(s.orders.sum()); rev = int(s.rev.sum() + s.ship.sum()); nc = int(s.new_customers.sum()); refd = int(s.refunds.sum())
    cm = float(att_contrib.get((r.period, r.campaign_id), 0))
    roas_rows.append({"period": r.period, "platform": r.platform, "campaign": camp_names.get(r.campaign_id, r.campaign_id), "campaign_type": camp_type.get(r.campaign_id, ""),
                      "spend": usd(r.spend), "impressions": int(r.impressions), "clicks": int(r.clicks),
                      "cpm": usd(r.spend / r.impressions * 1000) if r.impressions else None, "ctr": round(r.clicks / r.impressions, 4) if r.impressions else None,
                      "cpc": usd(r.spend / r.clicks) if r.clicks else None,
                      "platform_conversions": round(float(r.purchases), 1), "platform_value": usd(r.value), "platform_roas": round(r.value / r.spend, 3) if r.spend else None,
                      "store_orders": o_, "store_revenue": usd(rev), "store_refunds": usd(refd), "store_roas": round(rev / r.spend, 3) if r.spend else None,
                      "new_customers": nc, "cac": usd(r.spend / nc) if nc else None,
                      "attributed_contribution": usd(cm), "poas": round(cm / r.spend, 3) if r.spend else None,
                      "profit_after_ads": usd(cm - r.spend), "platform_overclaim": round(r.value / rev, 3) if rev else None,
                      "click_to_order_rate": round(o_ / r.clicks, 4) if r.clicks else None})
eff_rows = []
for p in PERIODS:
    st = dict(mrows[PERIODS.index(p)][1])
    spend = ACT.get((p, "Meta advertising"), 0) + ACT.get((p, "Google advertising"), 0)
    rr = [x for x in roas_rows if x["period"] == p]
    sm = lambda k, pl=None: sum((x[k] or 0) for x in rr if pl is None or x["platform"] == pl)
    cm1 = st["Contribution after fulfillment"]
    nc_all = int(po_[(po_.period == p) & po_.new_customer].shape[0])
    eff_rows.append({"period": p, "ad_spend": usd(spend), "meta_spend": sm("spend", "Meta"), "google_spend": sm("spend", "Google"),
                     "net_revenue": usd(st["Net revenue"]), "contribution_before_marketing": usd(cm1),
                     "mer": round(st["Net revenue"] / spend, 3) if spend else None,
                     "break_even_roas": round(st["Net revenue"] / cm1, 3) if cm1 else None,
                     "meta_platform_roas": round(sm("platform_value", "Meta") / sm("spend", "Meta"), 3) if sm("spend", "Meta") else None,
                     "google_platform_roas": round(sm("platform_value", "Google") / sm("spend", "Google"), 3) if sm("spend", "Google") else None,
                     "platform_claimed_value": round(sm("platform_value"), 2), "store_paid_revenue": round(sm("store_revenue"), 2),
                     "store_roas": round(sm("store_revenue") / (spend / 100), 3) if spend else None,
                     "poas": round(sm("attributed_contribution") / (spend / 100), 3) if spend else None,
                     "paid_share_of_revenue": round(sm("store_revenue") * 100 / st["Net revenue"], 4) if st["Net revenue"] else None,
                     "new_customers_all": nc_all, "new_customers_paid": int(sm("new_customers")),
                     "blended_cac": usd(spend / nc_all) if nc_all else None})
add_recon("Marketing", "Campaign spend in ROAS model = GL advertising", int(sum(ACT.get((p, l), 0) for p in PERIODS for l in ["Meta advertising", "Google advertising"])),
          int(round(sum(x["spend"] for x in roas_rows) * 100)), "meta/google daily vs general_ledger")
add_recon("Marketing", "Every paid-channel order maps to a known campaign", 0,
          int((~paid_ord.utm_campaign_id.isin(set(mcamp) | set(gcamp))).sum()), "shopify/orders.utm_campaign_id vs campaigns", unit="orders")


# ---------------------------------------------------------------- data sources (connector status page)
# Real statistics of every source extract; connection labels are illustrative (demo).
def _rows(path):
    with open(path, "rb") as fh:
        return max(0, sum(1 for _ in fh) - 1)


RUN_AT = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
SRC_META = {
    "shopify": ("Shopify", "Storefront, orders, customers", "API connector"),
    "shopify_payments": ("Shopify Payments", "Card processing and payouts", "API connector"),
    "quickbooks": ("QuickBooks Online", "General ledger, bills, AP", "API connector"),
    "bank": ("Operating bank account", "Bank statement feed", "Bank feed"),
    "gusto": ("Gusto", "Payroll and employees", "API connector"),
    "meta_ads": ("Meta Ads", "Facebook and Instagram campaigns", "API connector"),
    "google_ads": ("Google Ads", "Search and Shopping campaigns", "API connector"),
    "warehouse_3pl": ("3PL warehouse (WMS)", "Receipts, stock, dispatches, returns", "SFTP file drop"),
    "purchasing": ("Procurement register", "Suppliers, POs, payment schedules", "SFTP file drop"),
    "planning": ("Budget & contracts", "Approved budget, recurring obligations", "Spreadsheet upload"),
    "finance": ("Treasury & debt", "Loans, tax remittances, distributions", "Spreadsheet upload"),
}
src_rows, src_act = [], []
gl_month_lines = {}
for f in sorted(glob.glob(os.path.join(SRC, "quickbooks/general_ledger/*.csv"))):
    gl_month_lines[os.path.basename(f)[:7]] = _rows(f)


def month_counts(series):
    s = pd.Series(series).dropna().astype(str).str[:7]
    return s[s.isin(PERIODS)].value_counts().to_dict()


ACT_SRC = {
    "shopify": month_counts(orders.created_at),
    "shopify_payments": month_counts(bt.transaction_date),
    "quickbooks": gl_month_lines,
    "bank": month_counts(bank.posted_date),
    "gusto": month_counts(rd("gusto/payroll_employee_details.csv").payroll_run_id.map(dict(zip(pr.payroll_run_id, pr.pay_period_end)))),
    "meta_ads": month_counts(meta.date_start),
    "google_ads": month_counts(goo.segments_date),
    "warehouse_3pl": month_counts(mov.movement_date),
    "purchasing": month_counts(pos.order_date),
    "planning": month_counts(bud.period),
    "finance": month_counts(pd.concat([rd("finance/term_loan_payments.csv").payment_date, stx.due_date, rd("finance/owner_distributions.csv").payment_date])),
}
L12_ = PERIODS[-12:]
KEY = {
    "shopify": [("Orders", f"{len(orders):,}"), ("Customers", f"{len(cust):,}"), ("Products", f"{len(prods)}"), ("Refunds", f"{len(refunds):,}")],
    "shopify_payments": [("Transactions", f"{len(bt):,}"), ("Payouts", f"{len(payouts)}"), ("In transit", f"${TB[(LAST, '1010')]/100:,.0f}")],
    "quickbooks": [("Ledger lines", f"{gl_lines:,}"), ("Accounts", f"{len(coa)}"), ("Bills", f"{len(bills):,}"), ("Open AP", f"${-TB[(LAST, '2000')]/100:,.0f}")],
    "bank": [("Transactions", f"{len(bank):,}"), ("Closing balance", f"${bank_close/100:,.0f}"), ("Shopify deposits", f"{len(bank_shop):,}")],
    "gusto": [("Active employees", f"{len(act_emp)}"), ("Employees on file", f"{len(emp)}"), ("Payroll runs", f"{len(pr)}")],
    "meta_ads": [("Campaigns", f"{meta.campaign_id.nunique()}"), ("Spend L12M", f"${meta[meta.period.isin(L12_)].spend_c.sum()/100:,.0f}"), ("Impressions L12M", f"{meta[meta.period.isin(L12_)].impressions.sum()/1e6:,.1f}M")],
    "google_ads": [("Campaigns", f"{goo.campaign_id.nunique()}"), ("Spend L12M", f"${goo[goo.period.isin(L12_)].spend_c.sum()/100:,.0f}"), ("Clicks L12M", f"{goo[goo.period.isin(L12_)].clicks.sum():,}")],
    "warehouse_3pl": [("Dispatches", f"{len(ful):,}"), ("Stock movements", f"{len(mov):,}"), ("SKUs", f"{mei.sku.nunique()}"), ("Stock value", f"${TB[(LAST, '1200')]/100:,.0f}")],
    "purchasing": [("Purchase orders", f"{len(pos)}"), ("Suppliers", f"{len(sup)}"), ("Open POs", f"{int((pos.status != 'received').sum())}"), ("Open commitments", f"${sched.out_c.sum()/100:,.0f}")],
    "planning": [("Budget lines", f"{len(bud)}"), ("Budget versions", f"{bud.budget_version.nunique()}"), ("Contracts", f"{len(obl)}")],
    "finance": [("Facilities", f"{len(dr_)}"), ("Loan principal", f"${tb_principal/100:,.0f}"), ("Tax remittances", f"{len(stx)}")],
}
LAST_DATE = {
    "shopify": orders.created_at.max()[:10], "shopify_payments": bt.transaction_date.max()[:10], "quickbooks": CUTOFF.isoformat(),
    "bank": bank.posted_date.max(), "gusto": pr[pr.check_date <= CUTOFF.isoformat()].check_date.max(), "meta_ads": meta.date_start.max(),
    "google_ads": goo.segments_date.max(), "warehouse_3pl": mov.movement_date.max(), "purchasing": pos.order_date.max(),
    "planning": bud.approved_date.max() if "approved_date" in bud.columns else "", "finance": rd("finance/term_loan_payments.csv").payment_date.max(),
}
for key, (name, what, method) in SRC_META.items():
    files = sorted(glob.glob(os.path.join(SRC, key, "**", "*.csv"), recursive=True))
    nrows = sum(_rows(f) for f in files)
    nbytes = sum(os.path.getsize(f) for f in files)
    tables = len({os.path.dirname(f) if "general_ledger" in f else f for f in files})
    src_rows.append({"source": key, "name": name, "description": what, "connection": method, "status": "Synced",
                     "last_sync": RUN_AT, "last_record_date": LAST_DATE.get(key) or "", "period_from": PERIODS[0], "period_to": LAST,
                     "tables": tables, "files": len(files), "records": nrows, "size_mb": round(nbytes / 1e6, 1),
                     "key_stats": [{"label": a, "value": b} for a, b in KEY[key]]})
    for p in PERIODS:
        src_act.append({"source": key, "period": p, "records": int(ACT_SRC[key].get(p, 0))})
add_recon("Sources", "All 11 source systems delivered files", 11, sum(1 for r in src_rows if r["files"] > 0), "sources/*", unit="sources")



# ---------------------------------------------------------------- data collection schedule (config/data_schedule.json)
SCHED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "data_schedule.json")
sched_rows, sched_meta = [], {}
if os.path.exists(SCHED_PATH):
    cfg = json.load(open(SCHED_PATH))
    sched_meta = {"timezone": cfg.get("timezone"), "timezone_label": cfg.get("timezone_label")}
    for r in cfg.get("sources", []):
        nm = SRC_META.get(r["source"], (r["source"], "", ""))
        sched_rows.append({"kind": "Source sync", "name": nm[0], "source": r["source"], "connection": nm[2], **{k: v for k, v in r.items() if k != "source"}})
    for r in cfg.get("jobs", []):
        sched_rows.append({"kind": "Processing job", "name": r["job"], "source": "", "connection": "Claude scheduled task", **{k: v for k, v in r.items() if k != "job"}})

# ---------------------------------------------------------------- assemble
def ds(desc, grain, rows):
    cols = list(rows[0].keys()) if rows else []
    return {"description": desc, "grain": grain, "columns": cols, "rows": rows}


assumptions = [{"area": "Plan extension", "line": l, "basis": plan_basis[l]} for l in LINES] + \
              [{"area": "Latest estimate", "line": l, "basis": le_basis[l]} for l in LINES]
summary_ok = sum(1 for r in recon if r["status"] == "PASS")
mart = {
    "meta": {"company": "Alder & Loom Commerce LLC", "synthetic": True, "label": "Demo company / Synthetic data", "currency": "USD",
             "cutoff": CUTOFF.isoformat(), "first_period": PERIODS[0], "last_period": LAST, "fiscal_year": FY,
             "forecast_periods": FY_REST, "schedule_tz": sched_meta.get("timezone"), "schedule_tz_label": sched_meta.get("timezone_label"), "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
             "source_rows_gl": gl_lines, "opening_cash": usd(TB[(LAST, "1000")]),
             "recon_pass": summary_ok, "recon_total": len(recon),
             "pnl_lines": [{"line": l, "section": s, "sign": g} for l, s, g in PNL],
             "subtotals": ["Net revenue", "Gross profit", "Contribution after fulfillment", "Contribution margin", "EBITDA", "Net income"]},
    "datasets": {
        "pnl_monthly": ds("P&L by month and reporting line. actual from GL (period activity); budget = approved original plan, extended by Claude for months the plan does not cover; forecast = latest estimate for remaining months. Amounts are positive natural amounts; sign=+1 adds to profit, -1 deducts.",
                          "period x line", pnl_out),
        "kpi_monthly": ds("Company KPIs by month: orders, customers, AOV, P&L subtotals and margins, ad spend, MER, CAC, fulfillment cost, headcount and month-end balances.", "period", kpi),
        "balance_sheet_monthly": ds("Month-end balances from the trial balance (assets positive, liabilities positive).", "period x item", bs_out),
        "category_monthly": ds("Product category economics recognized at warehouse dispatch: gross sales, discounts, returns (refund date), COGS from stock issues less restocks.", "period x category", cat_rows),
        "sku_l12m": ds(f"SKU scorecard for last 12 months ({L12[0]}..{L12[-1]}) with prior-12-month comparison and stock position at {CUTOFF}.", "sku", sku_rows),
        "channel_monthly": ds("Storefront sessions, funnel and booked sales by channel group (Shopify last non-direct click).", "period x channel", ch_out),
        "marketing_monthly": ds("Meta and Google campaign spend and platform-attributed results. Platform attribution overlaps: never add platform values to get company sales.", "period x platform x campaign", mk_out),
        "suppliers": ds("Supplier scorecard: PO volume, on-time arrival vs original ETA, open payment commitments, advances.", "supplier", sup_rows),
        "cash_forecast_items": ds(f"13-week cash forecast line items from {H0} to {H1}. Negative = cash out. kind: Known (document/contract), Estimated (driver-based), Policy (discretionary).", "date x line", items),
        "cash_forecast_weeks": ds("Week definitions for the 13-week cash forecast.", "week", weeks_out),
        "cash_assumptions": ds("Assumptions used by the cash forecast.", "assumption", cash_assump),
        "plan_assumptions": ds("How the plan extension and the latest estimate were built, per P&L line.", "area x line", assumptions),
        "product_pnl_monthly": ds("Fully allocated P&L by month and SKU (adds up to the ledger). Direct: sales, discounts, returns, COGS, write-offs. Allocated: shipping income, fees, fulfillment, storage, returns handling, ads (by campaign-attributed order lines), overhead (two bases: _rev = share of net revenue, _lines = share of order lines).", "period x sku", prod_rows),
        "allocation_rules": ds("How each P&L cost pool is assigned to SKUs.", "cost pool", alloc_rules),
        "campaign_roas_monthly": ds("Campaign performance by month: platform-reported conversions/value (Meta 7d click 1d view, Google data-driven; these overlap) vs storefront last-click orders and revenue from utm_campaign_id; POAS = attributed contribution after fulfillment / spend.", "period x campaign", roas_rows),
        "marketing_efficiency_monthly": ds("Company marketing efficiency by month: spend, MER, break-even ROAS (net revenue / contribution before marketing), platform ROAS, storefront ROAS, POAS, CAC.", "period", eff_rows),
        "data_sources": ds("Status and statistics of every connected source system (records, tables, period, last record, key figures). Connection labels are illustrative in this demo.", "source", src_rows),
        "source_activity_monthly": ds("Records per month in each source's main table.", "source x period", src_act),
        "data_schedule": ds("Data collection and processing schedule (times in the company time zone). rule: daily | business_days | weekly | monthly_day | business_day_n | quarterly_before.", "source or job", sched_rows),
        "reconciliations": ds("Automated reconciliation checks run on every refresh.", "check", recon),
    },
}
with open(os.path.join(OUT, "datamart.json"), "w") as f:
    json.dump(mart, f, separators=(",", ":"), default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o))
pd.DataFrame(recon).to_csv(os.path.join(OUT, "reconciliation_report.csv"), index=False)
print(f"cutoff {CUTOFF}  periods {PERIODS[0]}..{LAST}  recon {summary_ok}/{len(recon)} PASS")
for r in recon:
    if r["status"] != "PASS": print("FAIL", r["check"], r["expected"], r["actual"])
print("datamart.json", round(os.path.getsize(os.path.join(OUT, "datamart.json")) / 1e6, 2), "MB")
