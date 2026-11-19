# ABC Restaurants (Cedar & Skillet synthetic package) datamart builder.
# Stdlib only. Money in integer cents.
# Usage: python3 -I pipeline/restaurants/build_datamart.py data/abc_restaurants_data/sources data/output/restaurants/datamart_raw.json
# Then site_datamart.py turns it into private/restaurants/datamart.json (npm run refresh:restaurants).
import csv, glob, os, sys, json, statistics
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import date, timedelta

SRC = sys.argv[1]; OUT = sys.argv[2]
ROOT = os.path.dirname(SRC.rstrip('/'))  # package root (contains validation/)
ENT = ['R01', 'R02', 'R03', 'HQ']
REST = ['R01', 'R02', 'R03']

def rd_all(pattern):
    for p in sorted(glob.glob(os.path.join(SRC, pattern))):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                yield r

def rd(rel):
    return list(rd_all(rel))

def cents(s):
    if s is None or s == '':
        return 0
    return int((Decimal(s) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def usd(c):
    return float(Decimal(c) / 100)

def mon(d):
    return d[:7]

# ---------- chart of accounts + P&L / balances from monthly trial balance ----------
coa = {r['account_id']: r for r in rd('quickbooks/chart_of_accounts.csv')}
PL_SIGN = {'Revenue': -1, 'ContraRevenue': -1, 'Expense': 1}

pl = defaultdict(int)       # (month, entity, acct) -> cents, presentation sign
bal = defaultdict(int)      # (month, entity, acct) -> closing debit-minus-credit cents
tb_activity = defaultdict(int)  # (month, entity, acct) raw dr-cr
for r in rd('quickbooks/monthly_trial_balance.csv'):
    m, e, a = mon(r['service_month']), r['restaurant_id'], r['account_id']
    t = coa[a]['account_type']
    dr, cr = cents(r['debit_usd']), cents(r['credit_usd'])
    if t in PL_SIGN:
        pl[(m, e, a)] += PL_SIGN[t] * (dr - cr)
    bal[(m, e, a)] = cents(r['closing_balance_usd'])

bud = defaultdict(int)
for r in rd('management_planning/approved_budget.csv'):
    m, e, a = mon(r['service_month']), r['restaurant_id'], r['account_id']
    t = coa[a]['account_type']
    if t in PL_SIGN:
        bud[(m, e, a)] += PL_SIGN[t] * cents(r['budget_amount_usd'])

MONTHS = sorted({k[0] for k in pl})
assert len(MONTHS) == 24, len(MONTHS)

def acct_group(a, grp):
    return sum(v for (m, e, x), v in grp.items() if x in a)

REV = [a for a, r in coa.items() if r['account_type'] in ('Revenue', 'ContraRevenue')]
EXP = [a for a, r in coa.items() if r['account_type'] == 'Expense']
COGS = [a for a in EXP if coa[a]['statement_group'] == 'COGS']
LABOR = [a for a in EXP if coa[a]['statement_group'] == 'Labor']
MKT = [a for a in EXP if coa[a]['statement_group'] == 'Marketing']
FEES = [a for a in EXP if coa[a]['statement_group'] == 'Fees']
DEP = ['6300']; INT = ['6400']

def sum_accts(store, month, ent_list, accts):
    return sum(store.get((month, e, a), 0) for e in ent_list for a in accts)

def entity_list(ent):
    return ENT if ent == 'COMPANY' else [ent]

def pl_metric(store, m, ent, accts):
    return sum(store.get((m, e, a), 0) for e in entity_list(ent) for a in accts)

# ---------- sales from POS ----------
checks = {}
sales = defaultdict(lambda: [0] * 7)   # (m, rest, channel) -> [closed, guests, gross, disc, comp, net, tax]
voids = defaultdict(int)
card_tips = defaultdict(int); cash_tips = defaultdict(int)
for r in rd('toast_pos/checks/checks_*.csv'):
    m, rr, ch, st = mon(r['business_date']), r['restaurant_id'], r['channel'], r['status']
    checks[r['check_id']] = (m, rr, ch, st)
    if st == 'CLOSED':
        v = sales[(m, rr, ch)]
        v[0] += 1; v[1] += int(r['guests'] or 0)
        v[2] += cents(r['gross_sales_usd']); v[3] += cents(r['discount_usd'])
        v[4] += cents(r['comp_usd']); v[5] += cents(r['net_sales_usd']); v[6] += cents(r['sales_tax_usd'])
        card_tips[(m, rr)] += cents(r['card_tips_usd']); cash_tips[(m, rr)] += cents(r['cash_tips_usd'])
    else:
        voids[(m, rr)] += 1

menu_items = {r['menu_item_id']: r for r in rd('toast_pos/menu_items.csv')}
menu = defaultdict(lambda: [0] * 6)  # (m, rest, ch, item) -> [qty, gross, mod_gross, disc, comp, net]
for r in rd('toast_pos/check_lines/check_lines_*.csv'):
    c = checks.get(r['check_id'])
    if not c or c[3] != 'CLOSED' or r['line_status'] != 'SERVED':
        continue
    m, rr, ch, _ = c
    v = menu[(m, rr, ch, r['menu_item_id'])]
    v[0] += int(Decimal(r['quantity'])); v[1] += cents(r['gross_sales_usd'])
    v[2] += cents(r['modifier_gross_usd']); v[3] += cents(r['discount_usd'])
    v[4] += cents(r['comp_usd']); v[5] += cents(r['net_sales_usd'])

refunds = defaultdict(lambda: [0, 0])  # (m, rest) -> [net sales refund, tax refund] by refund_date
for r in rd('toast_pos/refunds/refunds_*.csv'):
    v = refunds[(mon(r['refund_date']), r['restaurant_id'])]
    v[0] += cents(r['net_sales_refund_usd']); v[1] += cents(r['tax_refund_usd'])

# ---------- labor ----------
scheduled = defaultdict(int); sched_shifts = defaultdict(int)
for r in rd('timekeeping/scheduled_shifts/scheduled_shifts_*.csv'):
    k = (mon(r['business_date']), r['restaurant_id'])
    scheduled[k] += int(r['scheduled_paid_minutes']); sched_shifts[k] += 1
lab = defaultdict(lambda: [0, 0, 0, 0, 0, set()])  # paid_min, ot_min, wage, shifts, reg_min, employees
for r in rd('timekeeping/timesheets/timesheets_*.csv'):
    k = (mon(r['business_date']), r['restaurant_id'])
    v = lab[k]
    v[0] += int(r['paid_minutes']); v[1] += int(r['overtime_minutes'])
    v[2] += cents(r['wage_expense_usd']); v[3] += 1; v[4] += int(r['regular_minutes'])
    v[5].add(r['employee_id'])

# ---------- kitchen: theoretical usage, waste, counts, inventory ----------
ing_class = {r['ingredient_id']: r['inventory_class'] for r in rd('kitchen_inventory/ingredients.csv')}
theo = defaultdict(int)     # (m, rest, usage_type, class) -> cents
for r in rd('kitchen_inventory/theoretical_usage/theoretical_usage_*.csv'):
    theo[(mon(r['business_date']), r['restaurant_id'], r['usage_type'], ing_class[r['ingredient_id']])] += cents(r['usage_cost_usd'])
waste = defaultdict(int)    # (m, rest, reason) -> cents
waste_class = defaultdict(int)
waste_qty = defaultdict(float)
for r in rd('kitchen_inventory/waste_events/waste_events_*.csv'):
    m = mon(r['business_date']); c = cents(r['waste_cost_usd'])
    waste[(m, r['restaurant_id'], r['reason'])] += c
    waste_class[(m, r['restaurant_id'], ing_class[r['ingredient_id']])] += c
count_var = defaultdict(int)
for r in rd('kitchen_inventory/physical_stock_counts.csv'):
    count_var[(mon(r['count_date']), r['restaurant_id'])] += cents(r['adjustment_value_usd'])
inv_day = defaultdict(int)
for r in rd('kitchen_inventory/inventory_daily_balances/inventory_daily_balances_*.csv'):
    inv_day[(r['restaurant_id'], r['business_date'])] += cents(r['closing_value_usd'])
inv_end = {}
for (rr, d), v in inv_day.items():
    k = (mon(d), rr)
    if k not in inv_end or d > inv_end[k][0]:
        inv_end[k] = (d, v)

# ---------- marketplaces ----------
mkt = defaultdict(lambda: [0] * 6)  # (m, rest, platform) -> [orders, net_sales, commission, promo, svc_adj, net_receivable]
for plat, pattern in [('DOORDASH', 'doordash/doordash_orders/doordash_orders_*.csv'),
                      ('UBEREATS', 'ubereats/ubereats_orders/ubereats_orders_*.csv')]:
    for r in rd_all(pattern):
        v = mkt[(mon(r['order_date']), r['restaurant_id'], plat)]
        v[0] += 1; v[1] += cents(r['merchant_net_sales_usd']); v[2] += cents(r['commission_usd'])
        v[3] += cents(r['merchant_promotion_fee_usd']); v[4] += cents(r['service_adjustment_usd'])
        v[5] += cents(r['merchant_net_receivable_usd'])

# ---------- advertising ----------
ads = defaultdict(lambda: [0] * 4)  # (m, rest, channel) -> [spend, impressions, clicks, conversions, attributed]
ads = defaultdict(lambda: [0] * 5)
for ch, pattern in [('META', 'meta_ads/meta_ads_daily/meta_ads_daily_*.csv'),
                    ('GOOGLE', 'google_ads/google_ads_daily/google_ads_daily_*.csv')]:
    for r in rd_all(pattern):
        v = ads[(mon(r['activity_date']), r['restaurant_id'], ch)]
        v[0] += cents(r['spend_usd']); v[1] += int(r['impressions']); v[2] += int(r['clicks'])
        v[3] += int(r['conversions']); v[4] += cents(r['attributed_revenue_usd'])

# ---------- bank ----------
bank_stmt = rd('bank/bank_monthly_statements.csv')
bank_type = defaultdict(lambda: [0, 0, 0])  # (m, type) -> [count, in, out]
bank_tx = rd('bank/bank_transactions/bank_transactions_*.csv')
bank_weekly = defaultdict(int)  # (sunday-start date, type) -> signed cents
for r in bank_tx:
    m = mon(r['transaction_date']); a = cents(r['amount_usd'])
    v = bank_type[(m, r['transaction_type'])]
    v[0] += 1
    if a >= 0: v[1] += a
    else: v[2] += a
    d = date.fromisoformat(r['transaction_date'])
    wk = d - timedelta(days=(d.weekday() + 1) % 7)
    bank_weekly[(wk.isoformat(), r['transaction_type'])] += a

# ---------- obligations / commitments ----------
commit_raw = rd('management_planning/cash_commitments.csv')
seen = set(); commitments = []; dup_dropped = 0
for r in commit_raw:
    k = r['overlap_key']
    if k in seen:
        dup_dropped += 1; continue
    seen.add(k)
    commitments.append(r)

START = date(2026, 11, 1); HORIZON_DAYS = 91  # 13 Sunday-Saturday weeks
def wk_index(d):
    dd = (date.fromisoformat(d) - START).days
    return dd // 7 if 0 <= dd < HORIZON_DAYS else None

commit_rows = []
commit_beyond = 0
for r in commitments:
    w = wk_index(r['expected_cash_date'])
    if w is None:
        commit_beyond += 1
        continue
    commit_rows.append([w, r['expected_cash_date'], r['restaurant_id'], r['direction'],
                        r['commitment_type'], cents(r['amount_usd']), r['source_table'], r['certainty']])
commit_rows.sort()

payroll_runs = rd('gusto_payroll/payroll_runs.csv')
pr_sorted = sorted(payroll_runs, key=lambda r: r['period_end'])
offsets = [(date.fromisoformat(r['funding_date']) - date.fromisoformat(r['period_end'])).days
           for r in pr_sorted if r['funding_date']]
pay_offset = int(statistics.median(offsets[-6:]))
pay_amount = int(round(statistics.mean(cents(r['total_funding_usd']) for r in pr_sorted[-4:])))
pay_cycle_ends = [date(2026, 11, 15), date(2026, 11, 30), date(2026, 12, 15), date(2026, 12, 31), date(2027, 1, 15), date(2027, 1, 31)]
payroll_future = []
for pe in pay_cycle_ends:
    fd = pe + timedelta(days=pay_offset)
    w = wk_index(fd.isoformat())
    if w is not None:
        payroll_future.append([w, fd.isoformat(), 'HQ', 'OUTFLOW', 'FUTURE_PAYROLL_FUNDING', pay_amount,
                               'payroll_runs (run-rate)', 'RUN_RATE'])

tax = rd('treasury/sales_tax_obligations.csv')
tax_by_m = defaultdict(int)
for r in tax:
    tax_by_m[mon(r['service_month'])] += cents(r['net_tax_payable_usd'])
tax_months = sorted(tax_by_m)
tax_avg3 = int(round(statistics.mean(tax_by_m[m] for m in tax_months[-3:])))
tax_future = []
for due in [date(2026, 12, 20), date(2027, 1, 20)]:
    w = wk_index(due.isoformat())
    tax_future.append([w, due.isoformat(), 'ALL', 'OUTFLOW', 'FUTURE_SALES_TAX_REMITTANCE', tax_avg3,
                       'sales_tax_obligations (run-rate)', 'RUN_RATE'])

LAST8_START = date(2026, 9, 6)  # 8 full Sunday-Saturday weeks ending 2026-10-31
def last8(types, sign):
    tot = 0
    for (wk, t), v in bank_weekly.items():
        d = date.fromisoformat(wk)
        if LAST8_START <= d <= date(2026, 10, 31) and t in types:
            tot += v
    return tot // 8 if sign > 0 else -(-tot // 8)

receipt_types = ['CARD_PAYOUT', 'CASH_DEPOSIT', 'DOORDASH_SETTLEMENT', 'UBEREATS_SETTLEMENT']
receipt_weekly = sum(v for (wk, t), v in bank_weekly.items()
                     if LAST8_START <= date.fromisoformat(wk) <= date(2026, 10, 31) and t in receipt_types) // 8
vendor_weekly = -sum(v for (wk, t), v in bank_weekly.items()
                     if LAST8_START <= date.fromisoformat(wk) <= date(2026, 10, 31) and t == 'VENDOR_PAYMENT') // 8

# cash balance at cutoff from bank statement
bank_open = [r for r in bank_stmt if r['service_month'] == '2026-10-01'][0]
bank_close_oct = cents(bank_open['closing_balance_usd'])

# ---------- assemble datasets ----------
DS = {}
def dataset(name, columns, rows, grain, desc):
    DS[name] = {'columns': columns, 'rows': rows, 'grain': grain, 'description': desc, 'row_count': len(rows)}

ACCT_NAME = {a: coa[a]['account_name'] for a in coa}
# P&L: actual and budget per month/entity/account
pl_rows = []
keys = set(k for k in pl) | set(k for k in bud)
for (m, e, a) in sorted(keys):
    act = pl.get((m, e, a), 0); b = bud.get((m, e, a), 0)
    if act == 0 and b == 0: continue
    pl_rows.append([m, e, a, ACCT_NAME[a], coa[a]['account_type'], coa[a]['statement_group'], usd(act), usd(b)])
dataset('pnl_monthly',
        ['service_month', 'entity', 'account_id', 'account_name', 'account_type', 'statement_group', 'actual_usd', 'budget_usd'],
        pl_rows, 'month x entity x GL account',
        'P&L by GL account from monthly trial-balance activity (revenue and expense shown as positive, contra-revenue negative) and original approved budget on the same sign basis. HQ is a common-cost entity.')

sales_rows = []
for (m, rr, ch), v in sorted(sales.items()):
    sales_rows.append([m, rr, ch, v[0], v[1], usd(v[2]), usd(v[3]), usd(v[4]), usd(v[5]), usd(v[6])])
dataset('sales_monthly',
        ['service_month', 'restaurant_id', 'channel', 'closed_checks', 'guests', 'gross_sales_usd', 'discount_usd', 'comp_usd', 'net_sales_usd', 'sales_tax_usd'],
        sales_rows, 'month x restaurant x channel (closed POS checks)',
        'Closed POS checks by channel. Marketplace orders are already inside POS sales; not added again.')

menu_rows = []
for (m, rr, ch, it), v in sorted(menu.items()):
    mi = menu_items[it]
    menu_rows.append([m, rr, ch, it, mi['item_name'], mi['category'], v[0], usd(v[1]), usd(v[2]), usd(v[3]), usd(v[4]), usd(v[5])])
dataset('menu_monthly',
        ['service_month', 'restaurant_id', 'channel', 'menu_item_id', 'item_name', 'category', 'quantity', 'gross_sales_usd', 'modifier_gross_usd', 'discount_usd', 'comp_usd', 'net_sales_usd'],
        menu_rows, 'month x restaurant x channel x menu item (served lines of closed checks)',
        'Served menu lines. Modifier gross is already inside line gross.')

refund_rows = [[m, rr, usd(v[0]), usd(v[1])] for (m, rr), v in sorted(refunds.items())]
dataset('refunds_monthly', ['service_month', 'restaurant_id', 'refund_net_sales_usd', 'refund_tax_usd'], refund_rows,
        'month x restaurant (refund date)', 'Dated refunds by refund date. Prepared food is not restocked.')

lab_rows = []
for (m, rr), v in sorted(lab.items()):
    lab_rows.append([m, rr, round(v[0] / 60, 2), round(v[1] / 60, 2), round(scheduled[(m, rr)] / 60, 2),
                     usd(v[2]), len(v[5]), v[3], sched_shifts[(m, rr)],
                     usd(card_tips.get((m, rr), 0)) if False else None])
# tips from POS checks (card + cash), labour cost from timesheets (excludes tips)
lab_rows = [[m, rr, round(v[0] / 60, 2), round(v[1] / 60, 2), round(scheduled[(m, rr)] / 60, 2),
             usd(v[2]), len(v[5]), v[3], sched_shifts[(m, rr)]]
            for (m, rr), v in sorted(lab.items()) for m_ in [m]]
dataset('labor_monthly',
        ['service_month', 'restaurant_id', 'paid_hours', 'overtime_hours', 'scheduled_hours', 'hourly_wage_expense_usd', 'active_employees', 'worked_shifts', 'scheduled_shifts'],
        lab_rows, 'month x restaurant',
        'Actual paid hours from timesheets against planned scheduled hours. Wage expense excludes tips.')

cost_rows = []
for (m, rr, ut, cl), c in sorted(theo.items()):
    cost_rows.append([m, rr, ut, cl, usd(c)])
dataset('theoretical_cost_monthly', ['service_month', 'restaurant_id', 'usage_type', 'inventory_class', 'theoretical_cost_usd'],
        cost_rows, 'month x restaurant x usage type x inventory class', 'Recipe-driven theoretical usage at actual issue cost.')

waste_rows = [[m, rr, rs, usd(c)] for (m, rr, rs), c in sorted(waste.items())]
dataset('waste_monthly', ['service_month', 'restaurant_id', 'reason', 'waste_cost_usd'], waste_rows,
        'month x restaurant x waste reason', 'Measured ingredient loss at cost.')

cv_rows = [[m, rr, usd(c)] for (m, rr), c in sorted(count_var.items())]
dataset('count_variance_monthly', ['service_month', 'restaurant_id', 'count_variance_usd'], cv_rows,
        'month x restaurant', 'Physical count adjustments at cost.')

inv_rows = [[m, rr, d, usd(v)] for (m, rr), (d, v) in sorted(inv_end.items())]
dataset('inventory_month_end', ['service_month', 'restaurant_id', 'snapshot_date', 'inventory_value_usd'], inv_rows,
        'month x restaurant (last daily snapshot)', 'Ingredient inventory value at month end.')

mk_rows = []
for (m, rr, pf), v in sorted(mkt.items()):
    mk_rows.append([m, rr, pf, v[0], usd(v[1]), usd(v[2]), usd(v[3]), usd(v[4]), usd(v[5])])
dataset('marketplace_monthly',
        ['service_month', 'restaurant_id', 'platform', 'orders', 'merchant_net_sales_usd', 'commission_usd', 'promotion_fee_usd', 'service_adjustment_usd', 'net_receivable_usd'],
        mk_rows, 'month x restaurant x platform', 'Platform order economics. Sales are already in POS; commissions and promotion fees are platform costs.')

ad_rows = [[m, rr, ch, usd(v[0]), v[1], v[2], v[3], usd(v[4])] for (m, rr, ch), v in sorted(ads.items())]
dataset('ads_monthly', ['service_month', 'restaurant_id', 'channel', 'spend_usd', 'impressions', 'clicks', 'conversions', 'attributed_revenue_usd'],
        ad_rows, 'month x restaurant x ad platform', 'Daily ad metrics summed by month. Platform attribution overlaps and is not total sales.')

bal_rows = []
BAL_ACCTS = ['1000', '1010', '1020', '1030', '1040', '1050', '1100', '1110', '1120', '1500', '1510',
             '2000', '2010', '2011', '2020', '2021', '2030', '2040', '3000']
for m in MONTHS:
    for e in ENT:
        for a in BAL_ACCTS:
            v = bal.get((m, e, a), 0)
            sign = -1 if coa[a]['normal_balance'] == 'Credit' else 1
            bal_rows.append([m, e, a, ACCT_NAME[a], usd(sign * v)])
dataset('balances_monthly', ['service_month', 'entity', 'account_id', 'account_name', 'balance_usd'], bal_rows,
        'month-end x entity x balance account', 'Closing balances, presented with natural sign (assets, liabilities positive).')

bank_rows = [[r['service_month'][:7], usd(cents(r['opening_balance_usd'])), usd(cents(r['inflows_usd'])),
              usd(cents(r['outflows_usd'])), usd(cents(r['closing_balance_usd'])), int(r['transaction_count'])]
             for r in bank_stmt]
dataset('bank_monthly', ['service_month', 'opening_usd', 'inflows_usd', 'outflows_usd', 'closing_usd', 'transactions'], bank_rows,
        'month', 'Operating bank statements.')

bt_rows = [[m, t, v[0], usd(v[1]), usd(v[2])] for (m, t), v in sorted(bank_type.items())]
dataset('bank_type_monthly', ['service_month', 'transaction_type', 'transactions', 'inflows_usd', 'outflows_usd'], bt_rows,
        'month x bank transaction type', 'Bank transactions grouped by source type.')

cc_rows = [[w, d, rr, dr, t, usd(a), src, cert] for (w, d, rr, dr, t, a, src, cert) in commit_rows]
cc_rows += [[w, d, rr, dr, t, usd(a), src, cert] for (w, d, rr, dr, t, a, src, cert) in payroll_future + tax_future]
cc_rows.sort(key=lambda r: (r[0], r[1]))
dataset('cash_schedule_13w',
        ['week_index', 'expected_cash_date', 'restaurant_id', 'direction', 'commitment_type', 'amount_usd', 'source', 'certainty'],
        cc_rows, 'dated cash item in 13-week horizon 2026-11-01..2027-01-30',
        'Deduplicated source-linked commitments (cash_commitments by overlap_key) plus run-rate payroll and sales tax items that have no commitment yet.')

wk_hist = []
for (wk, t), v in sorted(bank_weekly.items()):
    if date.fromisoformat(wk) >= date(2026, 9, 6):
        wk_hist.append([wk, t, usd(v)])
dataset('bank_weekly_recent', ['week_start_sunday', 'transaction_type', 'net_usd'], wk_hist,
        'week x transaction type (last 8 full weeks)', 'Recent bank cash flows used for run-rate drivers.')

drivers = {
    'receipt_weekly_run_rate_usd': usd(receipt_weekly),
    'vendor_weekly_run_rate_usd': usd(vendor_weekly),
    'payroll_cycle_funding_usd': usd(pay_amount),
    'payroll_funding_offset_days': pay_offset,
    'sales_tax_monthly_run_rate_usd': usd(tax_avg3),
    'opening_bank_usd': usd(bank_close_oct),
    'run_rate_start_week_index': 1,
    'commitments_beyond_horizon': commit_beyond,
    'duplicate_commitments_dropped': dup_dropped,
}

# ---------- reconciliation to verified control totals ----------
ctrl = {}
for r in csv.DictReader(open(os.path.join(ROOT, 'validation', 'monthly_control_totals.csv'), encoding='utf-8-sig', newline='')):
    ctrl[(r['service_month'][:7], r['entity_id'])] = r

def pl_val(store, m, ent, accts):
    return sum(store.get((m, e, a), 0) for e in entity_list(ent) for a in accts)

ACC = dict(
    gross=['4000', '4010', '4020'], disc=['4090'], comp=['4091'], refund=['4092'],
)
recon = []
def rc(m, ent, metric, mine_cents, ctrl_usd_str, scale=100):
    cv = ctrl.get((m, ent))
    if cv is None: return
    ctrl_c = cents(ctrl_usd_str) if scale == 100 else int(Decimal(ctrl_usd_str))
    recon.append([m, ent, metric, usd(mine_cents) if scale == 100 else mine_cents, usd(ctrl_c) if scale == 100 else ctrl_c,
                  (mine_cents - ctrl_c) if scale == 100 else 0])

def ent_key(ent):
    return 'COMPANY' if ent == 'COMPANY' else ent

for m in MONTHS:
    for ent in ['COMPANY', 'R01', 'R02', 'R03']:
        cv = ctrl.get((m, ent))
        if cv is None: continue
        ents = entity_list(ent)
        # sales from POS
        g = sum(v[2] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent))
        d = sum(v[3] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent))
        c = sum(v[4] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent))
        rf = sum(v[0] for (mm, rr), v in refunds.items() if mm == m and (ent == 'COMPANY' or rr == ent))
        n = sum(v[5] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent))
        rc(m, ent, 'gross_sales_usd', g, cv['gross_sales_usd'])
        rc(m, ent, 'discount_usd', d, cv['discount_usd'])
        rc(m, ent, 'comp_usd', c, cv['comp_usd'])
        rc(m, ent, 'refunds_usd', rf, cv['refunds_usd'])
        rc(m, ent, 'net_revenue_usd', pl_val(pl, m, ent, REV), cv['net_revenue_usd'])
        rc(m, ent, 'net_revenue_usd_from_pos', n - rf, cv['net_revenue_usd'])
        rc(m, ent, 'closed_check_count', sum(v[0] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent)) * 100,
           str(int(cv['closed_check_count'])) + '.00')
        rc(m, ent, 'guest_count', sum(v[1] for (mm, rr, ch), v in sales.items() if mm == m and (ent == 'COMPANY' or rr == ent)) * 100,
           str(int(cv['guest_count'])) + '.00')
        rc(m, ent, 'card_tips_usd', sum(card_tips[(m, rr)] for rr in ents if (m, rr) in card_tips), cv['card_tips_collected_usd'])
        rc(m, ent, 'cash_tips_usd', sum(cash_tips[(m, rr)] for rr in ents if (m, rr) in cash_tips), cv['cash_tips_collected_usd'])
        paid = sum(lab[(m, rr)][0] for rr in ents if (m, rr) in lab)
        ot = sum(lab[(m, rr)][1] for rr in ents if (m, rr) in lab)
        rc(m, ent, 'paid_minutes', paid * 100, str(int(cv['paid_minutes'])) + '.00')
        rc(m, ent, 'overtime_minutes', ot * 100, str(int(cv['overtime_minutes'])) + '.00')
        rc(m, ent, 'food_theoretical_cost_usd', pl_val(pl, m, ent, ['5000']), cv['food_theoretical_cost_usd'])
        rc(m, ent, 'beverage_theoretical_cost_usd', pl_val(pl, m, ent, ['5010']), cv['beverage_theoretical_cost_usd'])
        rc(m, ent, 'packaging_cost_usd', pl_val(pl, m, ent, ['5020']), cv['packaging_cost_usd'])
        rc(m, ent, 'waste_cost_usd', pl_val(pl, m, ent, ['5030']), cv['waste_cost_usd'])
        rc(m, ent, 'staff_meals_cost_usd', pl_val(pl, m, ent, ['5040']), cv['staff_meals_cost_usd'])
        rc(m, ent, 'count_variance_cost_usd', pl_val(pl, m, ent, ['5050']), cv['count_variance_cost_usd'])
        rc(m, ent, 'hourly_wages_usd', pl_val(pl, m, ent, ['6000']), cv['hourly_wages_usd'])
        rc(m, ent, 'salary_wages_usd', pl_val(pl, m, ent, ['6010']), cv['salary_wages_usd'])
        rc(m, ent, 'employer_payroll_taxes_usd', pl_val(pl, m, ent, ['6020']), cv['employer_payroll_taxes_usd'])
        rc(m, ent, 'benefits_usd', pl_val(pl, m, ent, ['6030']), cv['benefits_usd'])
        rc(m, ent, 'rent_usd', pl_val(pl, m, ent, ['6100']), cv['rent_usd'])
        rc(m, ent, 'utilities_usd', pl_val(pl, m, ent, ['6110']), cv['utilities_usd'])
        rc(m, ent, 'card_fees_usd', pl_val(pl, m, ent, ['6160']), cv['card_fees_usd'])
        rc(m, ent, 'marketplace_commissions_usd', pl_val(pl, m, ent, ['6170']), cv['marketplace_commissions_usd'])
        rc(m, ent, 'marketplace_promotion_fees_usd', pl_val(pl, m, ent, ['6180']), cv['marketplace_promotion_fees_usd'])
        rc(m, ent, 'meta_ad_spend_usd', pl_val(pl, m, ent, ['6190']), cv['meta_ad_spend_usd'])
        rc(m, ent, 'google_ad_spend_usd', pl_val(pl, m, ent, ['6191']), cv['google_ad_spend_usd'])
        rc(m, ent, 'depreciation_usd', pl_val(pl, m, ent, DEP), cv['depreciation_usd'])
        rc(m, ent, 'interest_usd', pl_val(pl, m, ent, INT), cv['interest_usd'])
        rc(m, ent, 'total_ingredient_cost_usd', pl_val(pl, m, ent, COGS), cv['total_ingredient_cost_usd'])
        rc(m, ent, 'total_labor_cost_usd', pl_val(pl, m, ent, LABOR), cv['total_labor_cost_usd'])
        pretax = pl_val(pl, m, ent, REV) - pl_val(pl, m, ent, EXP)
        rc(m, ent, 'pretax_income_usd', pretax, cv['pretax_income_usd'])
        rc(m, ent, 'budget_net_revenue_usd', pl_val(bud, m, ent, REV), cv['budget_net_revenue_usd'])
        bpre = pl_val(bud, m, ent, REV) - pl_val(bud, m, ent, EXP)
        rc(m, ent, 'budget_pretax_income_usd', bpre, cv['budget_pretax_income_usd'])
        rc(m, ent, 'ap_balance_usd', -sum(bal.get((m, e, '2000'), 0) for e in ents), cv['ap_balance_usd'])
        rc(m, ent, 'inventory_value_usd', sum(bal.get((m, e, a), 0) for e in ents for a in ['1100', '1110', '1120']), cv['inventory_value_usd'])
        rc(m, ent, 'drawer_cash_usd', sum(bal.get((m, e, '1010'), 0) for e in ents), cv['drawer_cash_usd'])
        rc(m, ent, 'sales_tax_payable_usd', -sum(bal.get((m, e, '2030'), 0) for e in ents), cv['sales_tax_payable_usd'])
        rc(m, ent, 'debt_principal_usd', -sum(bal.get((m, e, '2040'), 0) for e in ents), cv['debt_principal_usd'])
        rc(m, ent, 'payroll_net_payable_usd', -sum(bal.get((m, e, '2010'), 0) for e in ents), cv['payroll_net_payable_usd'])
        rc(m, ent, 'payroll_tax_payable_usd', -sum(bal.get((m, e, '2011'), 0) for e in ents), cv['payroll_tax_payable_usd'])
        rc(m, ent, 'card_tip_liability_usd', -sum(bal.get((m, e, '2020'), 0) for e in ents), cv['card_tip_liability_usd'])
        rc(m, ent, 'cash_in_transit_usd', sum(bal.get((m, e, '1020'), 0) for e in ents), cv['cash_in_transit_usd'])
        rc(m, ent, 'processor_clearing_usd', sum(bal.get((m, e, '1030'), 0) for e in ents), cv['processor_clearing_usd'])
        rc(m, ent, 'doordash_clearing_usd', sum(bal.get((m, e, '1040'), 0) for e in ents), cv['doordash_clearing_usd'])
        rc(m, ent, 'ubereats_clearing_usd', sum(bal.get((m, e, '1050'), 0) for e in ents), cv['ubereats_clearing_usd'])
        if ent == 'COMPANY':
            rc(m, ent, 'central_bank_balance_usd', bal.get((m, 'HQ', '1000'), 0), cv['central_bank_balance_usd'])
        bs = [r for r in bank_stmt if r['service_month'][:7] == m][0]
        rc(m, ent, 'bank_inflows_usd', 0, '0') if False else None

recon_fail = [r for r in recon if r[5] != 0] if recon and isinstance(recon[0][5], int) else []
dataset('reconciliation_to_control', ['service_month', 'entity', 'metric', 'datamart_value', 'control_value', 'difference_cents'],
        recon, 'month x entity x metric', 'Datamart values compared with validation/monthly_control_totals.csv. Difference in cents for money metrics; counts in units.')

ver = json.load(open(os.path.join(ROOT, 'validation', 'validation_summary.json'), encoding='utf-8'))
meta = {
    'company': 'ABC Restaurants (synthetic restaurant group; source package Cedar & Skillet Hospitality LLC)',
    'label': 'Demo company / Synthetic data',
    'actual_period': ['2024-11-01', '2026-10-31'], 'snapshot_date': '2026-10-31', 'currency': 'USD',
    'entities': ['COMPANY', 'R01', 'R02', 'R03', 'HQ'],
    'restaurants': {'R01': 'Raleigh Warehouse District', 'R02': 'Durham Central', 'R03': 'Cary Commons', 'HQ': 'Shared management (Raleigh)'},
    'cash_horizon': ['2026-11-01', '2027-01-30'],
    'drivers': drivers,
    'verification': ver,
    'reconciliation_rows': len(recon),
    'reconciliation_nonzero': sum(1 for r in recon if isinstance(r[5], int) and r[5] != 0),
}
out = {'meta': meta, 'datasets': DS}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('datasets', {k: v['row_count'] for k, v in DS.items()})
print('drivers', json.dumps(drivers, ensure_ascii=False))
print('recon rows', len(recon), 'nonzero', meta['reconciliation_nonzero'])
