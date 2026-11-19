#!/usr/bin/env python3
"""ABC Agency (synthetic) — build datamart.json + reconciliation_report.csv.

Reads ONLY <data_root>/sources/. Money in integer cents. Raw source company name
"Signal Harbor Performance LLC" is renamed to "ABC Agency" on output.

Usage: python -I build_datamart.py <data_root> <out_dir>
"""
import csv, glob, json, os, sys
from collections import defaultdict, Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

DATA, OUT = sys.argv[1], sys.argv[2]
SRC = os.path.join(DATA, 'sources')
CUTOFF = date(2026, 10, 31)
DISPLAY_NAME = 'ABC Agency'
RAW_NAMES = ['Signal Harbor Performance LLC', 'Signal Harbor Performance', 'Signal Harbor']

def months_between(a, b):
    y, m = a; out = []
    while (y, m) <= b:
        out.append(f'{y:04d}-{m:02d}'); m += 1
        if m == 13: y, m = y + 1, 1
    return out
MONTHS = months_between((2024, 11), (2026, 10))
FY = {m: ('FY2025' if m <= '2025-10' else 'FY2026') for m in MONTHS}

def c(v):
    """str USD -> int cents"""
    if v is None or v == '': return 0
    return int((Decimal(v) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
def usd(cents): return round(cents / 100, 2)
def d(s): return date.fromisoformat(s)
def ym(s): return s[:7]

def load(table):
    p = os.path.join(SRC, table)
    files = sorted(glob.glob(p + '/*.csv')) if os.path.isdir(p) else [p + '.csv']
    rows = []
    for f in files:
        with open(f, encoding='utf-8-sig', newline='') as fh:
            rows += list(csv.DictReader(fh))
    return rows

T = {}
for t in ['hubspot/companies', 'hubspot/deals', 'hubspot/deal_monthly_snapshots', 'hubspot/pipeline_stages',
          'contracts/contracts', 'contracts/monthly_terms', 'contracts/change_orders', 'contracts/billing_schedule',
          'contracts/milestones', 'timekeeping/projects', 'timekeeping/timesheets', 'timekeeping/daily_capacity',
          'gusto/employees', 'gusto/payroll_runs', 'gusto/payroll_earnings', 'gusto/payroll_funding',
          'gusto/cost_allocations', 'gusto/compensation_rates', 'freelancers/approved_work', 'freelancers/contractors',
          'freelancers/rate_history', 'meta_ads/daily_metrics', 'google_ads/daily_metrics',
          'delivery/recognition_events', 'delivery/service_obligations', 'delivery/monthly_contract_balances',
          'delivery/opening_service_balances',
          'quickbooks/chart_of_accounts', 'quickbooks/opening_trial_balance', 'quickbooks/general_ledger',
          'quickbooks/journals', 'quickbooks/monthly_trial_balance', 'quickbooks/client_invoices',
          'quickbooks/client_invoice_lines', 'quickbooks/credit_notes', 'quickbooks/client_receipts',
          'quickbooks/receipt_applications', 'quickbooks/vendor_bills', 'quickbooks/vendor_payments',
          'quickbooks/vendor_payment_applications', 'quickbooks/ar_open_items', 'quickbooks/ap_open_items',
          'quickbooks/vendors',
          'bank/transactions', 'bank/monthly_statements', 'bank/accounts',
          'planning/monthly_budget', 'planning/headcount_capacity_plan', 'planning/signed_future_commitments',
          'planning/collection_expectations', 'planning/recurring_obligations', 'planning/payroll_commitments',
          'planning/contractor_accruals', 'finance/debt_schedule', 'finance/debt_service',
          'finance/owner_distributions', 'finance/debt_register']:
    T[t] = load(t)

CHECKS = []
def check(name, ok, detail=''):
    CHECKS.append({'check': name, 'status': 'PASS' if ok else 'FAIL', 'detail': str(detail)})

# ---------------------------------------------------------------- reference data
companies = {r['client_id']: r for r in T['hubspot/companies']}
employees = {r['employee_id']: r for r in T['gusto/employees']}
contracts = {r['contract_id']: r for r in T['contracts/contracts']}
coa = {r['account_id']: r for r in T['quickbooks/chart_of_accounts']}
projects = {r['project_id']: r for r in T['timekeeping/projects']}

# ---------------------------------------------------------------- integrity checks (PK / FK)
PKS = {'hubspot/companies': 'client_id', 'hubspot/deals': 'deal_id', 'contracts/contracts': 'contract_id',
       'timekeeping/timesheets': 'time_entry_id', 'gusto/payroll_earnings': 'payroll_earning_id',
       'gusto/cost_allocations': 'cost_allocation_id', 'freelancers/approved_work': 'approved_work_id',
       'delivery/recognition_events': 'recognition_id', 'delivery/service_obligations': 'service_id',
       'quickbooks/general_ledger': 'gl_line_id', 'quickbooks/journals': 'journal_id',
       'quickbooks/client_invoices': 'invoice_id', 'quickbooks/client_receipts': 'receipt_id',
       'bank/transactions': 'bank_transaction_id', 'meta_ads/daily_metrics': 'metric_id',
       'google_ads/daily_metrics': 'metric_id'}
for t, k in PKS.items():
    vals = [r[k] for r in T[t]]
    check(f'PK unique: {t}.{k}', len(vals) == len(set(vals)), f'{len(vals)} rows')
services = {r['service_id']: r for r in T['delivery/service_obligations']}
journals = {r['journal_id']: r for r in T['quickbooks/journals']}
FKS = [('delivery/recognition_events', 'service_id', services), ('delivery/recognition_events', 'client_id', companies),
       ('quickbooks/client_invoice_lines', 'service_id', services), ('quickbooks/general_ledger', 'journal_id', journals),
       ('quickbooks/general_ledger', 'account_id', coa), ('timekeeping/timesheets', 'employee_id', employees),
       ('timekeeping/timesheets', 'project_id', projects), ('gusto/cost_allocations', 'employee_id', employees),
       ('contracts/contracts', 'client_id', companies), ('freelancers/approved_work', 'contract_id', contracts)]
for t, k, ref in FKS:
    bad = [r[k] for r in T[t] if r[k] and r[k] not in ref]
    check(f'FK {t}.{k}', not bad, f'{len(bad)} orphans')

# ---------------------------------------------------------------- GL / ledger
gl_act = defaultdict(lambda: defaultdict(int))          # account -> month -> signed (debit-credit) cents
gl_by_journal = defaultdict(int)
for g in T['quickbooks/general_ledger']:
    s = c(g['debit_usd']) - c(g['credit_usd'])
    gl_act[g['account_id']][ym(g['journal_date'])] += s
    gl_by_journal[g['journal_id']] += s
check('All journals balance (debits = credits)', all(v == 0 for v in gl_by_journal.values()),
      f'{len(gl_by_journal)} journals')
future_gl = [g for g in T['quickbooks/general_ledger'] if d(g['journal_date']) > CUTOFF]
check('No GL activity after cutoff 2026-10-31', not future_gl, len(future_gl))

opening = {r['account_id']: c(r['signed_balance_usd']) for r in T['quickbooks/opening_trial_balance']}
check('Opening trial balance nets to zero', sum(opening.values()) == 0)
tb = defaultdict(dict)
for r in T['quickbooks/monthly_trial_balance']:
    tb[r['account_id']][r['service_month']] = r
tb_bad = 0
for a in coa:
    bal = opening.get(a, 0)
    for m in MONTHS:
        bal += gl_act[a][m]
        row = tb[a].get(m)
        if row is None or c(row['closing_signed_balance_usd']) != bal: tb_bad += 1
check('Opening TB + monthly GL activity = closing TB (every account, every month)', tb_bad == 0, f'{tb_bad} mismatches')

def closing(a, m):
    return opening.get(a, 0) + sum(gl_act[a][x] for x in MONTHS if x <= m)

def acc_sum(accs, m, sign=1):
    return sign * sum(gl_act[a][m] for a in accs)
REV_ACC = ['4000', '4010', '4020', '4030', '4090']
COS_ACC = ['5000', '5001', '5002', '5010']
OPEX_ACC = ['6000', '6001', '6002', '6100', '6110', '6120', '6130', '6140', '6150', '6300']

# ---------------------------------------------------------------- revenue (delivery recognition events)
rev_m = defaultdict(int); rev_type_m = defaultdict(lambda: defaultdict(int))
rev_client_m = defaultdict(lambda: defaultdict(int)); rev_contract = defaultdict(int)
rev_client_contract_m = defaultdict(int)
for r in T['delivery/recognition_events']:
    m = ym(r['recognition_date']); v = c(r['recognized_fee_usd'])
    rev_m[m] += v; rev_type_m[r['revenue_account_id']][m] += v
    rev_client_m[r['client_id']][m] += v; rev_contract[r['contract_id']] += v
check('No recognition events after cutoff', all(d(r['recognition_date']) <= CUTOFF for r in T['delivery/recognition_events']))
for m in MONTHS:
    if rev_m[m] != acc_sum(REV_ACC, m, -1):
        check(f'Recognition events = GL 4000-4090 ({m})', False); break
else:
    check('Recognition events = GL revenue 4000–4090, all 24 months', True)

# invoices / credits / receipts
inv_m = defaultdict(int); inv_client_m = defaultdict(lambda: defaultdict(int))
invoices = {r['invoice_id']: r for r in T['quickbooks/client_invoices']}
for r in T['quickbooks/client_invoices']:
    if r['record_scope'] == 'in_period':
        inv_m[ym(r['invoice_date'])] += c(r['invoice_total_usd'])
        inv_client_m[r['client_id']][ym(r['invoice_date'])] += c(r['invoice_total_usd'])
cn_m = defaultdict(int)
for r in T['quickbooks/credit_notes']: cn_m[ym(r['credit_date'])] += c(r['amount_usd'])
rcpt_m = defaultdict(int); rcpt_client_m = defaultdict(lambda: defaultdict(int))
for r in T['quickbooks/client_receipts']:
    rcpt_m[ym(r['receipt_date'])] += c(r['receipt_amount_usd'])
    rcpt_client_m[r['client_id']][ym(r['receipt_date'])] += c(r['receipt_amount_usd'])
app_by_rcpt = defaultdict(int)
for a in T['quickbooks/receipt_applications']: app_by_rcpt[a['receipt_id']] += c(a['applied_amount_usd'])
check('Every client receipt fully applied to invoices',
      all(app_by_rcpt[r['receipt_id']] == c(r['receipt_amount_usd']) for r in T['quickbooks/client_receipts']))

# AR roll-forward per month from subledger vs GL 1100
ar_bad = 0
ar_open = opening.get('1100', 0)
for m in MONTHS:
    ar_open = ar_open + inv_m[m] - cn_m[m] - rcpt_m[m]
    if ar_open != closing('1100', m): ar_bad += 1
check('AR roll-forward: opening + invoices − credits − receipts = GL 1100', ar_bad == 0, f'{ar_bad} months off')
ar_items = T['quickbooks/ar_open_items']
check('AR open items = GL 1100 at cutoff', sum(c(r['open_amount_usd']) for r in ar_items) == closing('1100', '2026-10'),
      usd(sum(c(r['open_amount_usd']) for r in ar_items)))

# revenue bridge: net earned = invoices − credits − Δdeferred + Δunbilled
br_bad = 0
for i, m in enumerate(MONTHS):
    prev = MONTHS[i - 1] if i else None
    dd = closing('2300', m) - (closing('2300', prev) if prev else opening.get('2300', 0))
    du = closing('1150', m) - (closing('1150', prev) if prev else opening.get('1150', 0))
    # deferred is credit balance (negative signed) -> increase in deferred liability = -dd
    if rev_m[m] != inv_m[m] - cn_m[m] - (-dd) + du: br_bad += 1
check('Revenue bridge: net fees = invoices − credits − Δdeferred + Δunbilled', br_bad == 0, f'{br_bad} months off')

# ---------------------------------------------------------------- media (client-direct)
media_m = defaultdict(int); media_client_m = defaultdict(lambda: defaultdict(int))
media_plat_m = defaultdict(lambda: defaultdict(int)); conv_value_client_m = defaultdict(lambda: defaultdict(int))
for plat in ['meta_ads', 'google_ads']:
    for r in T[f'{plat}/daily_metrics']:
        m = ym(r['metric_date']); v = c(r['spend_usd'])
        media_m[m] += v; media_client_m[r['client_id']][m] += v; media_plat_m[plat][m] += v
        conv_value_client_m[r['client_id']][m] += c(r['attributed_conversion_value_usd'])
        if r['funding_responsibility'] != 'CLIENT_DIRECT': check('Media funding all CLIENT_DIRECT', False, r['metric_id'])
check('Client media is client-direct (no agency media cash in bank / GL)',
      all(not str(g['source_type']).startswith('media') for g in T['quickbooks/general_ledger']))
gmic_bad = sum(1 for r in T['google_ads/daily_metrics'] if int(r['cost_micros']) != c(r['spend_usd']) * 10000)
check('Google cost_micros = spend × 1,000,000 (same money, not additive)', gmic_bad == 0, gmic_bad)

# spend-based fee check: fee = max(minimum, rate × mapped spend)
fee_bad = 0
for r in load('contracts/fee_calculations'):
    exp = max(c(r['minimum_fee_usd']), int((Decimal(r['spend_fee_rate']) * Decimal(r['media_spend_usd']) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)))
    if exp != c(r['earned_fee_usd']): fee_bad += 1
check('Spend-based fees = max(minimum, % × mapped client spend)', fee_bad == 0, fee_bad)

# ---------------------------------------------------------------- payroll
earn_m = defaultdict(int)
for r in T['gusto/payroll_earnings']:
    if r['record_scope'] == 'in_period': earn_m[ym(r['earned_end_date'])] += c(r['total_employer_cost_usd'])
for m in MONTHS:
    if earn_m[m] != acc_sum(['5000', '5001', '5002', '6000', '6001', '6002'], m): check(f'Gusto = GL payroll {m}', False); break
else:
    check('Gusto employer cost = GL payroll 5000–5002 + 6000–6002, all months', True)
alloc_by_earn = defaultdict(int)
alloc_cat_m = defaultdict(lambda: defaultdict(int)); alloc_client_m = defaultdict(lambda: defaultdict(int))
alloc_contract = defaultdict(int)
for r in T['gusto/cost_allocations']:
    v = c(r['allocated_employer_cost_usd']); alloc_by_earn[r['payroll_earning_id']] += v
    alloc_cat_m[r['allocation_category']][r['service_month']] += v
    if r['allocation_category'] == 'project_delivery':
        alloc_client_m[r['client_id']][r['service_month']] += v; alloc_contract[r['contract_id']] += v
earn_in = [r for r in T['gusto/payroll_earnings'] if r['record_scope'] == 'in_period']
check('Cost allocations sum to employer cost per employee-period (to the cent)',
      all(alloc_by_earn[r['payroll_earning_id']] == c(r['total_employer_cost_usd']) for r in earn_in), f'{len(earn_in)} earnings')

# ---------------------------------------------------------------- freelancers
fl_m = defaultdict(int); fl_client_m = defaultdict(lambda: defaultdict(int)); fl_contract = defaultdict(int)
fl_hours_client_m = defaultdict(lambda: defaultdict(float)); fl_contractor_m = defaultdict(lambda: defaultdict(int))
for r in T['freelancers/approved_work']:
    m = ym(r['approved_date']); v = c(r['earned_cost_usd'])
    fl_m[m] += v; fl_client_m[r['client_id']][m] += v; fl_contract[r['contract_id']] += v
    fl_hours_client_m[r['client_id']][m] += float(r['approved_hours'])
    fl_contractor_m[r['contractor_id']][m] += v
for m in MONTHS:
    if fl_m[m] != gl_act['5010'][m]: check(f'Freelance = GL 5010 {m}', False); break
else:
    check('Accepted freelance work = GL 5010 (expense only at acceptance)', True)
accr = sum(c(r['earned_cost_usd']) for r in T['planning/contractor_accruals'])
check('Contractor accruals (planning) = GL 2200 at cutoff', accr == -closing('2200', '2026-10'), usd(accr))
ap_items = T['quickbooks/ap_open_items']
check('AP open items = GL 2000 at cutoff', sum(c(r['open_amount_usd']) for r in ap_items) == -closing('2000', '2026-10'))
pc = sum(c(r['total_funding_usd']) for r in T['planning/payroll_commitments'])
check('Payroll commitments = GL 2100+2110+2120 at cutoff',
      pc == -(closing('2100', '2026-10') + closing('2110', '2026-10') + closing('2120', '2026-10')), usd(pc))

# ---------------------------------------------------------------- bank
bank_m_close = {}
for r in T['bank/monthly_statements']: bank_m_close[r['service_month']] = c(r['closing_balance_usd'])
check('Bank statement closing = GL 1000, all months', all(bank_m_close[m] == closing('1000', m) for m in MONTHS))
check('No bank transactions after cutoff', all(d(r['transaction_date']) <= CUTOFF for r in T['bank/transactions']))
check('No future actual payroll funding (October 16–31 run unfunded)',
      all(r['actual_funding_date'] == '' or d(r['actual_funding_date']) <= CUTOFF for r in T['gusto/payroll_runs']))
dist_m = defaultdict(int)
for r in T['finance/owner_distributions']: dist_m[ym(r['distribution_date'])] += c(r['amount_usd'])

# ---------------------------------------------------------------- time & capacity
emp_cls = {e: employees[e]['cost_class'] for e in employees}
cap = defaultdict(lambda: defaultdict(float))   # month -> key -> hours
cap_emp_m = defaultdict(lambda: defaultdict(float))
active_emp_m = defaultdict(set)
for r in T['timekeeping/daily_capacity']:
    m = ym(r['work_date']); e = r['employee_id']
    cap[m]['paid'] += float(r['paid_capacity_hours']); cap[m]['leave'] += float(r['paid_time_off_hours'])
    cap[m]['avail'] += float(r['available_work_hours'])
    if emp_cls[e] == 'delivery': cap[m]['deliv_avail'] += float(r['available_work_hours'])
    cap_emp_m[e][m] += float(r['available_work_hours']); active_emp_m[m].add(e)
hrs = defaultdict(lambda: defaultdict(float))
hrs_client_m = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
hrs_emp_m = defaultdict(lambda: defaultdict(float))
hrs_dept_m = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
for r in T['timekeeping/timesheets']:
    m = ym(r['work_date']); h = float(r['hours']); e = r['employee_id']; dep = employees[e]['department']
    hrs_dept_m[dep][m]['work'] += h
    if r['billable'] == 'True':
        if r['approval_status'] == 'approved':
            hrs[m]['bill_appr'] += h; hrs_emp_m[e][m] += h; hrs_dept_m[dep][m]['bill'] += h
            hrs_client_m[r['client_id']][m]['hours'] += h
            if r['is_scope_rework'] == 'True': hrs_client_m[r['client_id']][m]['rework'] += h
            if r['billing_treatment'] == 'included_in_retainer': hrs_client_m[r['client_id']][m]['retainer_hours'] += h
        else:
            hrs[m]['bill_unappr'] += h
    else:
        hrs[m]['nonbill'] += h
for dep in hrs_dept_m:
    for m in MONTHS:
        pass
cap_bad = 0
for m in MONTHS:
    if abs(cap[m]['avail'] - (hrs[m]['bill_appr'] + hrs[m]['bill_unappr'] + hrs[m]['nonbill'])) > 0.01: cap_bad += 1
check('Logged time = available work hours (paid capacity − leave), all months', cap_bad == 0, cap_bad)
dept_avail_m = defaultdict(lambda: defaultdict(float))
for e in cap_emp_m:
    for m, h in cap_emp_m[e].items(): dept_avail_m[employees[e]['department']][m] += h

# hourly revenue = approved T&M hours × rate
hourly_tm = defaultdict(int)
for r in T['timekeeping/timesheets']:
    if r['billing_treatment'] == 'approved_hours_times_rate' and r['approval_status'] == 'approved':
        hourly_tm[ym(r['work_date'])] += int((Decimal(r['hours']) * Decimal(r['billable_rate_usd']) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
check('Hourly revenue = approved T&M hours × effective role rate',
      all(hourly_tm[m] == -gl_act['4030'][m] for m in MONTHS))
check('Submitted (unapproved) October hours not recognized',
      sum(hrs[m]['bill_unappr'] for m in MONTHS) == hrs['2026-10']['bill_unappr'], f"{hrs['2026-10']['bill_unappr']} h")

# ---------------------------------------------------------------- budget
bud_acc_m = defaultdict(lambda: defaultdict(int)); bud_client_m = defaultdict(lambda: defaultdict(int))
bud_stream_m = defaultdict(lambda: defaultdict(int))
for r in T['planning/monthly_budget']:
    v = c(r['budget_amount_usd']); bud_acc_m[r['account_id']][r['service_month']] += v
    if r['account_id'].startswith('4'):
        bud_stream_m[r['revenue_stream']][r['service_month']] += v
        bud_client_m[r['client_id'] or '(new business)'][r['service_month']] += v

# ---------------------------------------------------------------- pipeline snapshots
pipe_m = defaultdict(int)
for r in T['hubspot/deal_monthly_snapshots']:
    if r['include_in_pipeline'] == 'True': pipe_m[ym(r['snapshot_date'])] += c(r['weighted_pipeline_usd'])
signed_deal_contracts = [r for r in T['hubspot/deals'] if r['stage_id'] not in ('closed_won',) and r['contract_id']]
check('Open pipeline excludes signed (closed-won) contracts', not signed_deal_contracts, len(signed_deal_contracts))

# ---------------------------------------------------------------- monthly fact table
monthly = []
for i, m in enumerate(MONTHS):
    rev = rev_m[m]; cos = acc_sum(COS_ACC, m); opex = acc_sum(OPEX_ACC, m); dep = gl_act['6300'][m]
    intr = gl_act['6400'][m]; gp = rev - cos
    last3 = [x for x in MONTHS[max(0, i - 2):i + 1]]
    ar = closing('1100', m); r3 = sum(rev_m[x] for x in last3)
    dso = ar / r3 * 30 * len(last3) if r3 else 0
    deliv_pay = acc_sum(['5000', '5001', '5002'], m)
    proj_pay = alloc_cat_m['project_delivery'][m]
    row = {
        'month': m, 'fy': FY[m],
        'net_fee_revenue': rev, 'flat_retainer': -gl_act['4000'][m], 'spend_based_fee': -gl_act['4010'][m],
        'fixed_project': -gl_act['4020'][m], 'hourly': -gl_act['4030'][m], 'fee_concessions': -gl_act['4090'][m],
        'gross_invoices': inv_m[m], 'credit_notes': cn_m[m], 'client_cash_collected': rcpt_m[m],
        'client_media_spend': media_m[m], 'meta_spend': media_plat_m['meta_ads'][m], 'google_spend': media_plat_m['google_ads'][m],
        'employer_payroll_cost': earn_m[m], 'delivery_payroll': deliv_pay, 'project_allocated_payroll': proj_pay,
        'delivery_bench_leave': deliv_pay - proj_pay, 'overhead_payroll': acc_sum(['6000', '6001', '6002'], m),
        'freelancer_cost': fl_m[m], 'cost_of_services': cos, 'gross_profit': gp,
        'opex_incl_dep': opex, 'rent': gl_act['6100'][m], 'saas': gl_act['6110'][m],
        'other_opex': acc_sum(['6120', '6130', '6140', '6150'], m),
        'ebitda': gp - opex + dep, 'depreciation': dep, 'interest': intr, 'net_profit': gp - opex - intr,
        'bank_cash': closing('1000', m), 'ar': ar, 'ap': -closing('2000', m), 'unbilled': closing('1150', m),
        'deferred': -closing('2300', m),
        'payroll_liability': -(closing('2100', m) + closing('2110', m) + closing('2120', m)),
        'contractor_accrual': -closing('2200', m), 'prepaid_insurance': closing('1200', m),
        'loan_principal': -closing('2500', m), 'owner_distributions': dist_m[m],
        'headcount': len(active_emp_m[m]), 'paid_capacity_hours': cap[m]['paid'], 'paid_leave_hours': cap[m]['leave'],
        'available_hours': cap[m]['avail'], 'billable_hours': hrs[m]['bill_appr'], 'unapproved_billable_hours': hrs[m]['bill_unappr'],
        'nonbillable_hours': hrs[m]['nonbill'], 'delivery_available_hours': cap[m]['deliv_avail'],
        'delivery_utilization': hrs[m]['bill_appr'] / cap[m]['deliv_avail'] if cap[m]['deliv_avail'] else 0,
        'firmwide_utilization': hrs[m]['bill_appr'] / cap[m]['avail'] if cap[m]['avail'] else 0,
        'budget_fee_revenue': sum(bud_acc_m[a][m] for a in bud_acc_m if a.startswith('4')),
        'budget_cost_of_services': sum(bud_acc_m[a][m] for a in COS_ACC),
        'budget_opex': sum(bud_acc_m[a][m] for a in OPEX_ACC),
        'budget_total_expenses': sum(bud_acc_m[a][m] for a in bud_acc_m if a[0] in '56'),
        'open_weighted_pipeline': pipe_m[m], 'dso': round(dso, 2),
    }
    row['budget_gross_profit'] = row['budget_fee_revenue'] - row['budget_cost_of_services']
    row['budget_ebitda'] = row['budget_gross_profit'] - row['budget_opex'] + bud_acc_m['6300'][m]
    monthly.append(row)

bridge_bad = 0
for r in monthly:
    m = r['month']
    contrib = sum(rev_client_m[cl][m] - alloc_client_m[cl][m] - fl_client_m[cl][m] for cl in set(rev_client_m) | set(alloc_client_m) | set(fl_client_m))
    if contrib - r['delivery_bench_leave'] != r['gross_profit']: bridge_bad += 1
check('Σ client contributions − delivery bench & paid leave = consolidated gross profit, all months', bridge_bad == 0, f'{bridge_bad} months off')

# ---------------------------------------------------------------- compare with reference control totals (independent)
ctl_path = os.path.join(DATA, 'validation', 'monthly_control_totals.csv')
MAP = {'agency_net_fee_revenue_usd': 'net_fee_revenue', 'flat_retainer_revenue_usd': 'flat_retainer',
       'spend_based_fee_revenue_usd': 'spend_based_fee', 'fixed_project_revenue_usd': 'fixed_project',
       'hourly_revenue_usd': 'hourly', 'gross_fee_invoices_usd': 'gross_invoices', 'credit_notes_usd': 'credit_notes',
       'client_collected_cash_usd': 'client_cash_collected', 'client_media_spend_usd': 'client_media_spend',
       'employee_employer_cost_usd': 'employer_payroll_cost', 'delivery_payroll_cost_usd': 'delivery_payroll',
       'project_allocated_payroll_usd': 'project_allocated_payroll',
       'delivery_bench_and_paid_leave_cost_usd': 'delivery_bench_leave', 'overhead_payroll_usd': 'overhead_payroll',
       'freelancer_earned_cost_usd': 'freelancer_cost', 'cost_of_services_usd': 'cost_of_services',
       'gross_profit_usd': 'gross_profit', 'operating_expenses_including_depreciation_usd': 'opex_incl_dep',
       'ebitda_usd': 'ebitda', 'depreciation_usd': 'depreciation', 'interest_usd': 'interest', 'net_profit_usd': 'net_profit',
       'bank_cash_usd': 'bank_cash', 'ar_usd': 'ar', 'ap_usd': 'ap', 'unbilled_earned_fees_usd': 'unbilled',
       'deferred_fees_usd': 'deferred', 'payroll_liability_usd': 'payroll_liability',
       'contractor_accrual_usd': 'contractor_accrual', 'prepaid_insurance_usd': 'prepaid_insurance',
       'loan_principal_usd': 'loan_principal', 'owner_distributions_usd': 'owner_distributions',
       'budget_fee_revenue_usd': 'budget_fee_revenue', 'budget_total_expenses_usd': 'budget_total_expenses',
       'open_weighted_pipeline_usd': 'open_weighted_pipeline'}
HMAP = {'active_headcount': 'headcount', 'paid_capacity_hours': 'paid_capacity_hours', 'paid_leave_hours': 'paid_leave_hours',
        'available_work_hours': 'available_hours', 'approved_billable_hours': 'billable_hours',
        'unapproved_billable_hours': 'unapproved_billable_hours', 'nonbillable_work_hours': 'nonbillable_hours',
        'delivery_available_work_hours': 'delivery_available_hours'}
RMAP = {'dso_3month_30day_convention': ('dso', 0.011), 'delivery_billable_utilization': ('delivery_utilization', 1e-5),
        'firmwide_billable_utilization': ('firmwide_utilization', 1e-5)}
ctl_mismatch = []
with open(ctl_path, encoding='utf-8-sig') as fh:
    ctl = {r['service_month']: r for r in csv.DictReader(fh)}
by_m = {r['month']: r for r in monthly}
for m in MONTHS:
    ref = ctl[m]; me = by_m[m]
    for k, mine in MAP.items():
        if c(ref[k]) != me[mine]: ctl_mismatch.append((m, k, ref[k], usd(me[mine])))
    for k, mine in HMAP.items():
        if abs(float(ref[k]) - me[mine]) > 0.001: ctl_mismatch.append((m, k, ref[k], me[mine]))
    for k, (mine, tol) in RMAP.items():
        if abs(float(ref[k]) - me[mine]) > tol: ctl_mismatch.append((m, k, ref[k], me[mine]))
check('Independent monthly aggregates = validation/monthly_control_totals.csv (47 metrics × 24 months)',
      not ctl_mismatch, f'{len(ctl_mismatch)} mismatches' + (f'; first: {ctl_mismatch[:3]}' if ctl_mismatch else ''))

# ---------------------------------------------------------------- P&L by account (actual + budget)
pl_accounts = []
for a in REV_ACC + COS_ACC + OPEX_ACC + ['6400']:
    sign = -1 if a.startswith('4') else 1
    pl_accounts.append({'account_id': a, 'name': coa[a]['account_name'], 'type': coa[a]['account_type'],
                        'actual': {m: sign * gl_act[a][m] for m in MONTHS},
                        'budget': {m: bud_acc_m[a][m] for m in MONTHS}})

# ---------------------------------------------------------------- clients
terms_by_client_m = defaultdict(dict)
for r in T['contracts/monthly_terms']:
    terms_by_client_m[r['client_id']][r['service_month']] = r
retainer_clients_m = defaultdict(set)
for r in T['contracts/monthly_terms']:
    if r['service_month'] in MONTHS: retainer_clients_m[r['service_month']].add(r['client_id'])

clients = []
for cid, co in sorted(companies.items()):
    if co['lifecycle_stage'] != 'customer' and cid not in rev_client_m: continue
    ms = {}
    for m in MONTHS:
        t = terms_by_client_m[cid].get(m)
        h = hrs_client_m[cid][m]
        ms[m] = {'revenue': rev_client_m[cid][m], 'payroll_cost': alloc_client_m[cid][m], 'freelancer_cost': fl_client_m[cid][m],
                 'media_spend': media_client_m[cid][m], 'platform_conv_value': conv_value_client_m[cid][m],
                 'hours': round(h['hours'], 2), 'retainer_hours': round(h['retainer_hours'], 2), 'rework_hours': round(h['rework'], 2),
                 'freelancer_hours': fl_hours_client_m[cid][m],
                 'scope_hours': float(t['scope_hours_budget']) if t else None,
                 'retainer_fee': c(t['monthly_minimum_fee_usd']) if t else None,
                 'fee_model': t['fee_model'] if t else None,
                 'invoiced': inv_client_m[cid][m], 'collected': rcpt_client_m[cid][m],
                 'budget_revenue': bud_client_m[cid][m]}
    ccs = [k for k in contracts.values() if k['client_id'] == cid]
    clients.append({'client_id': cid, 'name': co['company_name'], 'industry': co['industry'], 'state': co['state_code'],
                    'contracts': sorted(k['contract_id'] for k in ccs),
                    'active_retainer_at_cutoff': cid in retainer_clients_m['2026-10'],
                    'first_month': next((m for m in MONTHS if ms[m]['revenue']), None), 'months': ms})

# contracts (whole-SOW margins)
contract_rows = []
for k in contracts.values():
    cid = k['contract_id']
    contract_rows.append({'contract_id': cid, 'client_id': k['client_id'], 'type': k['contract_type'], 'name': k['sow_name'],
                          'parent': k['parent_contract_id'], 'signed': k['signed_date'], 'start': k['service_start_date'],
                          'end': k['current_end_date'], 'status': k['status_asof'],
                          'contract_value': c(k['current_committed_minimum_usd']), 'value_basis': k['contract_value_basis'],
                          'ceiling': c(k['contract_ceiling_usd']),
                          'revenue_to_date': rev_contract[cid], 'payroll_cost_to_date': alloc_contract[cid],
                          'freelancer_cost_to_date': fl_contract[cid]})
milestones = [{'milestone_id': r['milestone_id'], 'contract_id': r['contract_id'], 'seq': r['sequence'], 'deliverable': r['deliverable'],
               'planned': r['planned_approval_date'], 'actual': r['actual_approved_date'], 'status': r['approval_status'],
               'fee': c(r['agreed_fee_usd']), 'hours_budget': float(r['original_hours_budget'] or 0)}
              for r in T['contracts/milestones']]
change_orders = [{k: r[k] for k in ('change_order_id', 'contract_id', 'signed_date', 'effective_date', 'change_type', 'fee_change_usd', 'scope_hours_change', 'reason')}
                 for r in T['contracts/change_orders']]

# ---------------------------------------------------------------- retention / churn
churn = []
all_ret = {cl for m in MONTHS for cl in retainer_clients_m[m]}
for i, m in enumerate(MONTHS):
    cur = retainer_clients_m[m]; prev = retainer_clients_m[MONTHS[i - 1]] if i else set()
    churn.append({'month': m, 'active': len(cur), 'new': sorted(cur - prev) if i else [], 'churned': sorted(prev - cur)})
renewals = []
for k in contracts.values():
    if k['contract_type'] == 'retainer':
        child = [x for x in contracts.values() if x['parent_contract_id'] == k['contract_id']]
        renewals.append({'contract_id': k['contract_id'], 'client_id': k['client_id'], 'end': k['current_end_date'],
                         'original_end': k['original_end_date'], 'status': k['status_asof'],
                         'renewed_by': child[0]['contract_id'] if child else None,
                         'renewal_signed': child[0]['signed_date'] if child else None})

# ---------------------------------------------------------------- AR aging / AP
ar_aging = [{'invoice_id': r['invoice_id'], 'client_id': r['client_id'], 'contract_id': r['contract_id'],
             'invoice_date': r['invoice_date'], 'due_date': r['due_date'], 'original': c(r['original_amount_usd']),
             'credit': c(r['credit_applied_usd']), 'paid': c(r['cash_applied_usd']), 'open': c(r['open_amount_usd']),
             'days_past_due': int(r['days_past_due']), 'bucket': r['aging_bucket']} for r in ar_items]
vend = {r['vendor_id']: r for r in T['quickbooks/vendors']}
ap_aging = [{'bill_id': r['bill_id'], 'vendor_id': r['vendor_id'], 'vendor': vend.get(r['vendor_id'], {}).get('vendor_name', ''),
             'due_date': r['due_date'], 'open': c(r['open_amount_usd']), 'bucket': r['aging_bucket']} for r in ap_items]
# historical payment speed per client: amount-weighted days invoice -> receipt
pay_days = defaultdict(list)
for a in T['quickbooks/receipt_applications']:
    inv = invoices[a['invoice_id']]
    pay_days[inv['client_id']].append(((d(a['applied_date']) - d(inv['invoice_date'])).days, c(a['applied_amount_usd']), a['applied_date']))

# ---------------------------------------------------------------- utilization by department / employee
util_dept = {dep: {m: {'available': round(dept_avail_m[dep][m], 2), 'billable': round(hrs_dept_m[dep][m]['bill'], 2)} for m in MONTHS}
             for dep in sorted(dept_avail_m)}
emp_rows = []
for e, r in sorted(employees.items()):
    emp_rows.append({'employee_id': e, 'name': r['employee_name'], 'role': r['role'], 'department': r['department'],
                     'cost_class': r['cost_class'], 'hire_date': r['hire_date'], 'termination_date': r['termination_date'],
                     'available': {m: cap_emp_m[e][m] for m in MONTHS if cap_emp_m[e][m]},
                     'billable': {m: hrs_emp_m[e][m] for m in MONTHS if hrs_emp_m[e][m]}})
contractor_rows = []
for r in T['freelancers/contractors']:
    rates = sorted([x for x in T['freelancers/rate_history'] if x['contractor_id'] == r['contractor_id']], key=lambda x: x['effective_start_date'])
    contractor_rows.append({'contractor_id': r['contractor_id'], 'name': r['contractor_name'], 'role': r['role'],
                            'rates': [{'from': x['effective_start_date'], 'rate': float(x['hourly_cost_rate_usd'])} for x in rates],
                            'cost': dict(fl_contractor_m[r['contractor_id']])})

# ---------------------------------------------------------------- pipeline & contracted forecast
stages = {r['stage_id']: r for r in T['hubspot/pipeline_stages']}
open_deals = [{'deal_id': r['deal_id'], 'client_id': r['client_id'], 'company': companies.get(r['client_id'], {}).get('company_name', ''),
               'name': r['deal_name'], 'type': r['deal_type'], 'stage': stages[r['stage_id']]['stage_name'],
               'probability': float(r['probability']), 'expected_close': r['expected_close_date'],
               'quote': c(r['quoted_value_usd']), 'value_basis': r['value_basis'],
               'weighted': int(round(c(r['quoted_value_usd']) * float(r['probability'])))}
              for r in T['hubspot/deals'] if r['stage_id'] not in ('closed_won', 'closed_lost')]
win_loss = Counter(r['stage_id'] for r in T['hubspot/deals'])
contracted = defaultdict(lambda: defaultdict(int))   # month -> type -> cents (signed future service minimum)
for s in T['delivery/service_obligations']:
    if s['recognition_status'] != 'approved' and s['service_month'] > '2026-10':
        contracted[s['service_month']][s['service_type']] += c(s['agreed_minimum_fee_usd'])
contracted_forecast = [{'month': m, **{k: v for k, v in contracted[m].items()}, 'total': sum(contracted[m].values())}
                       for m in sorted(contracted)]
unapproved_past = [s for s in T['delivery/service_obligations'] if s['recognition_status'] != 'approved' and s['service_month'] <= '2026-10']

# ---------------------------------------------------------------- 13-week cash forecast
H_START = date(2026, 11, 1); WEEKS = 13; H_END = H_START + timedelta(days=7 * WEEKS - 1)  # Sun 2026-11-01 .. Sat 2027-01-30
def wk(dt):
    i = (dt - H_START).days // 7
    return i if 0 <= i < WEEKS else None
def bizday(dt):
    while dt.weekday() >= 5: dt += timedelta(days=1)
    return dt
lines = []   # each: category, item, source_id, date, amount (signed cents), basis, scenario
def add(cat, item, src, dt, amt, basis, kind='committed'):
    lines.append({'category': cat, 'item': item, 'source_id': src, 'date': dt.isoformat(), 'amount': amt,
                  'basis': basis, 'kind': kind, 'week': wk(dt)})

# (1) existing AR -> collection expectations
coll = T['planning/collection_expectations']
check('Collection expectations cover open AR exactly (no overlap)',
      sum(c(r['open_amount_usd']) for r in coll) == closing('1100', '2026-10'))
for r in coll:
    add('Receipts: existing AR', f"{r['client_id']} {r['invoice_id']}", r['invoice_id'], d(r['expected_receipt_date']),
        c(r['open_amount_usd']), f"collection_expectations ({r['collection_risk']} risk)")
# (2) future signed billings -> receipts using each client's historic invoice->cash lag profile (last 12 months)
def lag_profile(cid):
    rows = [x for x in pay_days.get(cid, []) if x[2] >= '2025-11-01']
    if not rows: rows = [x for v in pay_days.values() for x in v if x[2] >= '2025-11-01']
    tot = sum(a for _, a, _ in rows); prof = defaultdict(int)
    for days, a, _ in rows: prof[days] += a
    return [(dd, a / tot) for dd, a in sorted(prof.items())]
billing = {r['schedule_line_id']: r for r in T['contracts/billing_schedule']}
fut = [r for r in T['planning/signed_future_commitments']]
check('signed_future_commitments ⊆ future billing_schedule (overlap_key = schedule_line_id, no double count)',
      all(r['overlap_key'] == r['schedule_line_id'] and billing[r['schedule_line_id']]['status_asof'] == 'scheduled' for r in fut)
      and len(fut) == sum(1 for b in billing.values() if b['status_asof'] == 'scheduled'))
check('No future scheduled billing duplicates an already-issued invoice',
      all(not b['actual_invoice_line_id'] for b in billing.values() if b['status_asof'] == 'scheduled'))
lag_cache = {}
for r in fut:
    cid = r['client_id']; inv_dt = d(r['scheduled_invoice_date']); amt = c(r['scheduled_amount_usd'])
    if inv_dt > H_END: continue
    prof = lag_cache.setdefault(cid, lag_profile(cid))
    alloc = 0
    for j, (days, share) in enumerate(prof):
        part = amt - alloc if j == len(prof) - 1 else int(round(amt * share))
        alloc += part
        if part:
            add('Receipts: new signed billings', f"{cid} {r['schedule_line_id']}", r['schedule_line_id'],
                bizday(inv_dt + timedelta(days=days)), part,
                f"billing_schedule {r['amount_basis']}; invoice {r['scheduled_invoice_date']}; client's L12M invoice→cash lag profile")
# (3) payroll: earned-unfunded October run + future semimonthly runs
for r in T['planning/payroll_commitments']:
    add('Payroll', f"Payroll {r['payroll_run_id']} (Oct 16–31, earned)", r['payroll_commitment_id'],
        d(r['scheduled_funding_date']), -c(r['total_funding_usd']), 'payroll_commitments (covers GL 2100/2110/2120)')
active_now = [e for e in employees.values() if not e['termination_date'] or d(e['termination_date']) > CUTOFF]
def comp_for(e, on):
    rs = [x for x in T['gusto/compensation_rates'] if x['employee_id'] == e and x['effective_start_date'] <= on.isoformat() <= x['effective_end_date']]
    if rs: return rs[0], False
    last = max((x for x in T['gusto/compensation_rates'] if x['employee_id'] == e), key=lambda x: x['effective_end_date'])
    return last, True
def period_cost(on):
    tot = 0; merit = False
    for e in active_now:
        r, ext = comp_for(e['employee_id'], on)
        sal = Decimal(r['annual_salary_usd']) * (Decimal('1.04') if ext else 1); merit |= ext
        gross = (sal / 24 * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        tax = (gross * Decimal(r['employer_tax_rate'])).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        tot += int(gross + tax) + c(r['monthly_employer_benefit_usd']) // 2
    return tot, merit
pe = date(2026, 11, 15)
while True:
    fund = bizday(pe + timedelta(days=2))
    if fund > H_END: break
    amt, merit = period_cost(pe)
    add('Payroll', f"Payroll period ending {pe}", f"FCST-PAY-{pe}", fund, -amt,
        'current roster × current salary rates' + (' + 4% January merit review (A14)' if merit else '') + '; funding = earned end + 2 days, next weekday (A15)')
    pe = (pe.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1) if pe.day == 15 else (pe + timedelta(days=1)).replace(day=15)
check('Forecast payroll run-rate matches last actual run (current roster/rates)',
      period_cost(date(2026, 11, 15))[0] == c(T['planning/payroll_commitments'][0]['total_funding_usd']),
      f"{usd(period_cost(date(2026, 11, 15))[0])} vs {T['planning/payroll_commitments'][0]['total_funding_usd']}")
# (4) open AP bills — pay on due date (overdue -> first business day)
for r in ap_items:
    dt = max(d(r['due_date']), date(2026, 11, 2))
    add('Vendors: open AP', f"{vend.get(r['vendor_id'], {}).get('vendor_name', r['vendor_id'])} {r['bill_id']}", r['bill_id'],
        bizday(dt), -c(r['open_amount_usd']), 'ap_open_items (GL 2000); overdue paid first business day')
# (5) October accepted-uninvoiced contractor work (GL 2200)
for r in T['planning/contractor_accruals']:
    add('Freelancers', f"{r['contractor_id']} Oct accepted work", r['contractor_accrual_id'], bizday(d(r['expected_due_date'])),
        -c(r['earned_cost_usd']), 'contractor_accruals (GL 2200) — expected due date')
# (6) future freelancer work: trailing-3-month accepted cost per contractor, invoiced 3rd of next month, net 30
for k in contractor_rows:
    l3 = [k['cost'].get(m, 0) for m in ('2026-08', '2026-09', '2026-10')]
    run = int(round(sum(l3) / 3))
    for svc in ('2026-11', '2026-12'):
        y, mo = map(int, svc.split('-')); nm = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 3)
        add('Freelancers', f"{k['contractor_id']} {svc} work (run-rate)", f"FCST-FL-{k['contractor_id']}-{svc}",
            bizday(nm + timedelta(days=30)), -run, 'trailing 3-month accepted cost; invoice 3rd + net30 (A18)', 'estimate')
# (7) recurring operating obligations — next cycles only (current open bill already in AP)
for r in T['planning/recurring_obligations']:
    if r['cadence'] != 'monthly':
        if d(r['next_expected_bill_date']) <= H_END:
            add('Vendors: recurring', r['description'], r['obligation_id'], d(r['next_expected_bill_date']), -c(r['current_cycle_fee_usd']), 'recurring_obligations')
        continue
    start = d(r['next_service_start_date'])
    while True:
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        due = bizday(end + timedelta(days=int(r['payment_terms_days'])))
        if due > H_END: break
        add('Vendors: recurring', f"{r['description']} ({start:%b %Y})", r['obligation_id'], due, -c(r['current_cycle_fee_usd']),
            f"recurring_obligations next cycle; bill at month-end, net{r['payment_terms_days']}")
        start = end + timedelta(days=1)
# (8) debt service
for r in T['finance/debt_schedule']:
    dt = d(r['scheduled_payment_date'])
    if dt <= H_END:
        add('Debt service', f"Term loan {r['scheduled_payment_date']} (principal {r['scheduled_principal_usd']} + interest {r['scheduled_interest_usd']})",
            r['debt_schedule_id'], dt, -c(r['scheduled_total_usd']), 'debt_schedule (contractual)')
# scenarios (not in base)
scen = []
for dl in open_deals:
    scen.append({'scenario': 'Weighted open pipeline', 'item': f"{dl['company']} — {dl['name']}", 'source_id': dl['deal_id'],
                 'probability': dl['probability'], 'quote': dl['quote'], 'weighted': dl['weighted'], 'expected_close': dl['expected_close']})
outside = [l for l in lines if l['week'] is None]
inside = [l for l in lines if l['week'] is not None]
open_cash = closing('1000', '2026-10')
weeks = []; bal = open_cash
cats = ['Receipts: existing AR', 'Receipts: new signed billings', 'Payroll', 'Freelancers', 'Vendors: open AP', 'Vendors: recurring', 'Debt service']
for w in range(WEEKS):
    ws = H_START + timedelta(days=7 * w); we = ws + timedelta(days=6)
    row = {'week': w + 1, 'start': ws.isoformat(), 'end': we.isoformat(), 'opening': bal}
    for cat in cats: row[cat] = sum(l['amount'] for l in inside if l['week'] == w and l['category'] == cat)
    row['net'] = sum(row[cat] for cat in cats); bal += row['net']; row['closing'] = bal
    weeks.append(row)
cash_forecast = {'opening_cash': open_cash, 'as_of': '2026-10-31', 'horizon_start': H_START.isoformat(), 'horizon_end': H_END.isoformat(),
                 'week_convention': 'Consecutive 7-day intervals Sunday–Saturday starting 2026-11-01 (13 full weeks, ends 2027-01-30); no partial weeks.',
                 'categories': cats, 'weeks': weeks, 'lines': sorted(inside, key=lambda x: x['date']),
                 'beyond_horizon': sorted(outside, key=lambda x: x['date']), 'scenarios': scen,
                 'owner_distribution_policy': 'Discretionary: up to $200k per quarter while keeping ≥ $420k cash at decision (A23). Not included in base forecast.',
                 'excluded_overlaps': [
                     'signed_future_commitments counted once via schedule_line_id (copy of billing_schedule)',
                     'Existing AR collected via collection_expectations; issued invoices not re-forecast',
                     'CLI-002 Nov 2026–Jan 2027 retainer already invoiced and collected Oct 22 — no future inflow when earned',
                     'Payroll commitments cover GL 2100/2110/2120; contractor accruals cover GL 2200; AP open items cover GL 2000',
                     'Recurring obligations start from next_service_start_date (current open bill already in AP)',
                     'Spend-based retainer fees forecast at signed monthly minimum; media-driven upside excluded']}
check('13-week forecast: every committed line dated within or explicitly beyond horizon', len(inside) + len(outside) == len(lines))
check('13-week forecast covers 2026-11-01 to 2027-01-30 with no gaps', weeks[0]['start'] == '2026-11-01' and weeks[-1]['end'] == '2027-01-30')

# ---------------------------------------------------------------- stories (key facts for AI commentary)
def series(cid, key): return {m: next(cl for cl in clients if cl['client_id'] == cid)['months'][m][key] for m in MONTHS}
stories = {
    'CLI-001': 'Media spend grows while flat retainer fee stays $12,000/month.',
    'CLI-003': 'Scope creep Apr–Sep 2026 (TSK-REWORK), $2,500 credit note CN-001 on Jul 12 for June service, change order CO-CON-R-003-2-1 reprices to $15,500 from Oct 2026.',
    'CLI-004': 'From Apr 2026 invoices paid ~35% after ~48 days and rest after ~105 days; $1,000 fee concession on August fee; overdue AR at cutoff.',
    'CLI-005': 'Moved media buying in-house after Jul 2026 (churn); Aug–Sep delivery utilization dip; CLI-022 added.',
    'FREE-004': 'Video producer cost rate rises $95 → $122/hour from Aug 2026 (CLI-007 work, 28 h/month).',
    'CLI-002': 'Quarterly advance: Nov 2026–Jan 2027 renewal invoiced Oct 15 and paid Oct 22 — deferred revenue, no future cash inflow.',
    'CON-F-009': 'Second milestone accepted 18 days late — margin vs revenue vs cash timing.',
}

# ---------------------------------------------------------------- data sources catalog
src_catalog = []
with open(os.path.join(DATA, 'metadata', 'table_catalog.csv'), encoding='utf-8-sig') as fh:
    for r in csv.DictReader(fh):
        src_catalog.append({'table': r['logical_table'], 'system': r['source_system'], 'grain': r['grain'],
                            'rows': int(r['row_count']), 'files': int(r['physical_file_count'])})
loaded_rows = {t: len(v) for t, v in T.items()}
mism = [t for t in loaded_rows if any(s['table'] == t and s['rows'] != loaded_rows[t] for s in src_catalog)]
check('Loaded row counts = metadata/table_catalog.csv', not mism, mism)

# ---------------------------------------------------------------- export (dashboard format: meta + datasets{rows,columns,grain,description}; USD in dollars)
D = usd
DATASETS = {}
def ds(name, rows, grain, description):
    cols = list(rows[0].keys()) if rows else []
    DATASETS[name] = {'grain': grain, 'description': description, 'columns': cols, 'rows': rows}

MONEY_KEYS = {k for k in monthly[0] if k not in ('month', 'fy', 'headcount', 'paid_capacity_hours', 'paid_leave_hours', 'available_hours',
              'billable_hours', 'unapproved_billable_hours', 'nonbillable_hours', 'delivery_available_hours', 'delivery_utilization',
              'firmwide_utilization', 'dso')}
kpi = []
for i, r in enumerate(monthly):
    o = {('period' if k == 'month' else k): (D(v) if k in MONEY_KEYS else (round(v, 6) if isinstance(v, float) else v)) for k, v in r.items()}
    rev = r['net_fee_revenue']
    o['gross_margin_pct'] = round(r['gross_profit'] / rev, 6) if rev else None
    o['ebitda_pct'] = round(r['ebitda'] / rev, 6) if rev else None
    o['fee_pct_of_client_media'] = round(rev / r['client_media_spend'], 6) if r['client_media_spend'] else None
    hrs_all = r['billable_hours'] + sum(fl_hours_client_m[cl][r['month']] for cl in fl_hours_client_m)
    o['freelancer_hours'] = sum(fl_hours_client_m[cl][r['month']] for cl in fl_hours_client_m)
    o['effective_billable_rate'] = round(rev / 100 / hrs_all, 2) if hrs_all else None
    l12 = monthly[max(0, i - 11):i + 1]
    o['revenue_per_employee_t12'] = round(sum(x['net_fee_revenue'] for x in l12) / 100 / (sum(x['headcount'] for x in l12) / len(l12)), 2) if i >= 11 else None
    o['active_retainer_clients'] = len(retainer_clients_m[r['month']])
    kpi.append(o)
ds('kpi_monthly', kpi, 'month', 'One row per month Nov 2024–Oct 2026: P&L (GL activity), budget, balances (month-end TB), payroll split, client media (client-direct, NOT agency money), hours, utilization, DSO, pipeline. USD.')

SECTION = {'4': 'Revenue', '5': 'Cost of services', '6': 'Operating expenses'}
pnl_rows = []
for a in pl_accounts:
    sec = 'Interest' if a['account_id'] == '6400' else ('Depreciation' if a['account_id'] == '6300' else SECTION[a['account_id'][0]])
    for m in MONTHS:
        pnl_rows.append({'period': m, 'fy': FY[m], 'account_id': a['account_id'], 'line': a['name'], 'section': sec,
                         'sign': 1 if a['account_id'].startswith('4') else -1, 'actual': D(a['actual'][m]), 'budget': D(a['budget'][m])})
ds('pnl_monthly', pnl_rows, 'account × month', 'GL period activity by account (revenue positive, contra 4090 negative; costs positive) vs immutable original budget BUDGET-FY2025/FY2026. sign = +1 revenue, −1 cost for variance direction.')

stream_name = {'4000': 'Flat retainer', '4010': 'Spend-based fee', '4020': 'Fixed projects', '4030': 'Hourly (T&M)', '4090': 'Fee concessions'}

# client × month
proj_type = {k: v['project_type'] for k, v in projects.items()}
fl_ret_hours = defaultdict(lambda: defaultdict(float))
for r in T['freelancers/approved_work']:
    if proj_type.get(r['project_id']) == 'retainer': fl_ret_hours[r['client_id']][ym(r['approved_date'])] += float(r['approved_hours'])
cm_rows = []; client_rows = []
for cl in clients:
    cid = cl['client_id']
    for m in MONTHS:
        x = cl['months'][m]
        if not any([x['revenue'], x['media_spend'], x['hours'], x['invoiced'], x['collected'], x['budget_revenue'], x['scope_hours']]): continue
        contrib = x['revenue'] - x['payroll_cost'] - x['freelancer_cost']
        cm_rows.append({'period': m, 'fy': FY[m], 'client_id': cid, 'client': cl['name'], 'net_fee_revenue': D(x['revenue']),
                        'project_payroll_cost': D(x['payroll_cost']), 'freelancer_cost': D(x['freelancer_cost']), 'contribution': D(contrib),
                        'staff_hours': x['hours'], 'retainer_staff_hours': x['retainer_hours'], 'retainer_scope_hours': x['scope_hours'],
                        'scope_overrun_hours': round(x['retainer_hours'] - x['scope_hours'], 2) if x['scope_hours'] is not None else None,
                        'rework_hours': x['rework_hours'], 'freelancer_hours': x['freelancer_hours'], 'retainer_freelancer_hours': fl_ret_hours[cid][m],
                        'retainer_monthly_minimum_fee': D(x['retainer_fee']) if x['retainer_fee'] is not None else None, 'fee_model': x['fee_model'],
                        'client_media_spend': D(x['media_spend']), 'platform_attributed_value': D(x['platform_conv_value']),
                        'invoiced': D(x['invoiced']), 'collected': D(x['collected']), 'budget_revenue': D(x['budget_revenue'])})
    L12 = [cl['months'][m] for m in MONTHS[-12:]]
    rv = sum(x['revenue'] for x in L12); co = rv - sum(x['payroll_cost'] + x['freelancer_cost'] for x in L12)
    client_rows.append({'client_id': cid, 'client': cl['name'], 'industry': cl['industry'], 'state': cl['state'],
                        'status': 'Active retainer' if cl['active_retainer_at_cutoff'] else ('Churned' if any(cid in retainer_clients_m[m] for m in MONTHS) else 'Projects only'),
                        'first_revenue_month': cl['first_month'], 'contracts': ' '.join(cl['contracts']),
                        'l12m_revenue': D(rv), 'l12m_contribution': D(co), 'l12m_contribution_pct': round(co / rv, 4) if rv else None,
                        'l12m_media_spend': D(sum(x['media_spend'] for x in L12)), 'ar_open': D(sum(a['open'] for a in ar_aging if a['client_id'] == cid)),
                        'story': stories.get(cid, '')})
ds('client_monthly', cm_rows, 'client × month', 'Per client per month: net fees earned, project-allocated employer payroll (Gusto allocation, not extra expense), accepted freelancer cost, contribution, staff hours vs retainer scope hours, rework (TSK-REWORK), client media spend & platform-attributed value (client money, overlapping, NOT agency revenue), invoiced, collected, budget.')
ds('clients', client_rows, 'client', 'Client master with status at cutoff, last-12-month revenue/contribution, open AR and story notes.')
ds('contracts', [{**k, 'contract_value': D(k['contract_value']), 'ceiling': D(k['ceiling']) if k['ceiling'] else None,
                  'revenue_to_date': D(k['revenue_to_date']), 'payroll_cost_to_date': D(k['payroll_cost_to_date']),
                  'freelancer_cost_to_date': D(k['freelancer_cost_to_date']),
                  'contribution_to_date': D(k['revenue_to_date'] - k['payroll_cost_to_date'] - k['freelancer_cost_to_date'])} for k in contract_rows],
   'contract (SOW/renewal)', 'Signed SOWs: retainer / fixed_project / hourly. contract_value = signed minimum (not revenue). Whole-SOW revenue and cost to date.')
ds('milestones', [{**x, 'fee': D(x['fee']), 'days_late': ((d(x['actual']) - d(x['planned'])).days if x['actual'] else None)} for x in milestones],
   'fixed-project milestone', 'Fixed-project deliverables: planned vs actual acceptance date; revenue recognized only on acceptance.')
ds('change_orders', change_orders, 'change order', 'Signed amendments (repricing, scope reset, termination).')
ds('retention_monthly', [{'period': r['month'], 'active_retainer_clients': r['active'], 'new_clients': ' '.join(r['new']), 'churned_clients': ' '.join(r['churned'])} for r in churn],
   'month', 'Active retainer clients from signed monthly terms; new and churned client IDs.')
ds('renewals', renewals, 'retainer contract', 'Each retainer SOW and the renewal that followed it (if any).')
ds('ar_open_items', [{**a, 'original': D(a['original']), 'credit': D(a['credit']), 'paid': D(a['paid']), 'open': D(a['open']),
                      'client': companies[a['client_id']]['company_name'],
                      'expected_receipt_date': next((c_['expected_receipt_date'] for c_ in coll if c_['invoice_id'] == a['invoice_id']), None),
                      'collection_risk': next((c_['collection_risk'] for c_ in coll if c_['invoice_id'] == a['invoice_id']), None)} for a in ar_aging],
   'open invoice at cutoff', 'Unpaid client invoices on 2026-10-31 with aging bucket and management collection expectation.')
ds('ap_open_items', [{**a, 'open': D(a['open'])} for a in ap_aging], 'open bill at cutoff', 'Unpaid vendor bills on 2026-10-31.')
inv_pay = []
for cid, lst in pay_days.items():
    for days, amt, dt in lst:
        inv_pay.append({'client_id': cid, 'receipt_month': dt[:7], 'days_invoice_to_cash': days, 'amount': D(amt)})
ds('collections', inv_pay, 'receipt application', 'Every client cash receipt applied to an invoice: days from invoice date to cash. Basis for DSO and collection lags.')
ds('utilization_monthly', [{'period': m, 'department': dep, 'available_hours': v[m]['available'], 'billable_hours': v[m]['billable'],
                            'utilization': round(v[m]['billable'] / v[m]['available'], 4) if v[m]['available'] else None}
                           for dep, v in util_dept.items() for m in MONTHS], 'department × month',
   'Approved billable staff hours / available work hours (paid capacity minus paid leave). Retainer/fixed time is billable delivery but not separately invoiced.')
ds('employees', [{'employee_id': e['employee_id'], 'name': e['name'], 'role': e['role'], 'department': e['department'], 'cost_class': e['cost_class'],
                  'hire_date': e['hire_date'], 'termination_date': e['termination_date'] or None,
                  'l12m_available_hours': round(sum(e['available'].get(m, 0) for m in MONTHS[-12:]), 2),
                  'l12m_billable_hours': round(sum(e['billable'].get(m, 0) for m in MONTHS[-12:]), 2)} for e in emp_rows],
   'employee', 'Fictional roster (24 people over the window) with last-12-month hours.')
fl_rows = []
rate_at = lambda k, m: next((x['rate'] for x in reversed(k['rates']) if x['from'][:7] <= m), None)
for k in contractor_rows:
    for m in MONTHS:
        if k['cost'].get(m):
            fl_rows.append({'period': m, 'contractor_id': k['contractor_id'], 'name': k['name'], 'role': k['role'], 'accepted_cost': D(k['cost'][m]), 'hourly_cost_rate': rate_at(k, m)})
ds('freelancers_monthly', fl_rows, 'contractor × month', 'Accepted freelance work cost (expense at acceptance) and effective hourly cost rate.')
ds('pipeline_open_deals', [{**x, 'quote': D(x['quote']), 'weighted': D(x['weighted'])} for x in open_deals], 'open deal',
   'Open unsigned CRM deals at cutoff. Quote = estimated 12-month fee, NOT revenue; weighted = quote × stage probability.')
ds('contracted_forecast', [{'period': r['month'], 'retainer': D(r.get('retainer', 0)), 'fixed_milestone': D(r.get('fixed_milestone', 0)),
                            'hourly': D(r.get('hourly', 0)), 'total': D(r['total'])} for r in contracted_forecast], 'future service month',
   'Signed future service minimum by month (retainer minimums incl. CLI-002 prepaid quarter, signed milestones). Spend-based upside and unsold work excluded.')
# cash forecast
cash_items = []
SECT = {'Receipts: existing AR': 'Inflows', 'Receipts: new signed billings': 'Inflows'}
for l in cash_forecast['lines'] + cash_forecast['beyond_horizon']:
    cash_items.append({'date': l['date'], 'week': (l['week'] + 1) if l['week'] is not None else None, 'line': l['category'],
                       'section': SECT.get(l['category'], 'Financing' if l['category'] == 'Debt service' else 'Outflows'),
                       'amount': D(l['amount']), 'kind': 'Estimate' if l['kind'] == 'estimate' else 'Known', 'item': l['item'],
                       'source': l['source_id'], 'basis': l['basis'], 'in_horizon': l['week'] is not None})
ds('cash_forecast_items', cash_items, 'cash line item', 'Base 13-week cash forecast line items from 2026-11-01 (weeks Sun–Sat). Known = documents/contracts; Estimate = run-rate. in_horizon=false items fall after 2027-01-30.')
ds('cash_forecast_weeks', [{'week': w['week'], 'start': w['start'], 'end': w['end'], 'opening': D(w['opening']),
                            **{k: D(w[k]) for k in cash_forecast['categories']}, 'net': D(w['net']), 'closing': D(w['closing'])} for w in cash_forecast['weeks']],
   'week', 'Base forecast by week and category (no pipeline, no owner distributions).')
ds('cash_scenarios', [{**s, 'quote': D(s['quote']), 'weighted': D(s['weighted'])} for s in cash_forecast['scenarios']], 'scenario item',
   'Optional scenario inputs (not in base): probability-weighted open pipeline.')
ds('stories', [{'id': k, 'story': v} for k, v in stories.items()], 'story', 'Known business stories in the case, with IDs for commentary.')
# data sources
SYS = {'hubspot': ('HubSpot CRM', 'Companies, leads, deals, stage history, pipeline snapshots'),
       'contracts': ('Contracts & SOWs', 'SOWs, versions, monthly terms, change orders, rate cards, milestones, billing schedule'),
       'timekeeping': ('Timekeeping (Harvest/Clockify-style)', 'Projects, tasks, daily capacity, leave, allocations, timesheets'),
       'gusto': ('Gusto payroll', 'Employees, salary rates, semimonthly payroll runs, funding, project cost allocation'),
       'freelancers': ('Freelancer portal', 'Contractors, rates, work orders, accepted work, invoices'),
       'meta_ads': ('Meta Ads (client-owned)', 'Client ad accounts, campaigns, daily metrics, monthly spend statements'),
       'google_ads': ('Google Ads (client-owned)', 'Client ad accounts, campaigns, daily metrics, monthly spend statements'),
       'delivery': ('Delivery & revenue', 'Service obligations, approvals, recognition events, contract balances'),
       'quickbooks': ('QuickBooks Online', 'Chart of accounts, GL, journals, TB, invoices, receipts, bills, payments, AR/AP'),
       'bank': ('Operating bank', 'Account, daily transactions, monthly statements'),
       'planning': ('FP&A planning', 'Budgets, capacity plan, future commitments, collection and payroll commitments'),
       'finance': ('Treasury & debt', 'Term loan register, schedule and payments, owner distributions, prepaid amortization')}
DATECOL = {'hubspot': ('hubspot/deals', 'created_date'), 'contracts': ('contracts/contracts', 'signed_date'), 'timekeeping': ('timekeeping/timesheets', 'work_date'),
           'gusto': ('gusto/payroll_earnings', 'earned_end_date'), 'freelancers': ('freelancers/approved_work', 'approved_date'),
           'meta_ads': ('meta_ads/daily_metrics', 'metric_date'), 'google_ads': ('google_ads/daily_metrics', 'metric_date'),
           'delivery': ('delivery/recognition_events', 'recognition_date'), 'quickbooks': ('quickbooks/general_ledger', 'journal_date'),
           'bank': ('bank/transactions', 'transaction_date'), 'planning': ('planning/monthly_budget', 'service_month'),
           'finance': ('finance/debt_service', 'payment_date')}
src_rows = []; act_rows = []
with open(os.path.join(DATA, 'metadata', 'source_catalog.csv'), encoding='utf-8-sig') as fh:
    scat = {r['source_system']: r for r in csv.DictReader(fh)}
for s, (nm, desc) in SYS.items():
    t, col = DATECOL[s]
    dates = [r[col][:10] for r in T[t] if r[col]]
    past = [x for x in dates if x <= '2026-10-31']
    cnt = Counter(x[:7] for x in dates)
    for m in MONTHS: act_rows.append({'source': s, 'period': m, 'records': cnt.get(m, 0)})
    src_rows.append({'source': s, 'name': nm, 'description': desc, 'status': 'Synced', 'connection': 'Synthetic CSV extract',
                     'tables': int(scat[s]['table_count']), 'files': int(scat[s]['physical_csv_count']), 'records': int(scat[s]['row_count']),
                     'last_record_date': max(past) if past else None, 'activity_table': t})
ds('data_sources', src_rows, 'source system', '12 modeled source systems with record counts (from metadata catalog, re-verified on load) and latest actual record date.')
ds('source_activity_monthly', act_rows, 'source × month', 'Records per month in each source\'s main activity table.')
RULES_AREA = [('Integrity', ('PK ', 'FK ', 'Loaded')), ('Cash forecast', ('13-week', 'Forecast', 'Collection', 'signed_future', 'future scheduled')),
              ('Control totals', ('control_totals',)), ('Cutoff', ('after cutoff', 'future actual', 'unapproved')),
              ('Margin bridge', ('client contributions',)), ('Revenue & AR', ('Recognition', 'receipt', 'AR ', 'Revenue bridge', 'Spend-based', 'Hourly')),
              ('Payroll & time', ('Gusto', 'allocations', 'Payroll commitments', 'Logged time')),
              ('Freelancers & AP', ('freelance', 'Contractor', 'AP open')), ('Media', ('media', 'micros')),
              ('Ledger', ('journals', 'trial', 'TB')), ('Bank', ('Bank',)), ('CRM', ('pipeline',))]
def AREA(n):
    for a, keys in RULES_AREA:
        if any(k in n for k in keys): return a
    return 'Other'
ds('reconciliations', [{'status': x['status'], 'area': AREA(x['check']), 'check': x['check'], 'detail': x['detail']} for x in CHECKS],
   'check', 'Every reconciliation run on the raw sources; dashboards publish only when all pass.')

recon_pass = sum(1 for x in CHECKS if x['status'] == 'PASS')
meta = {'company': DISPLAY_NAME, 'label': 'Demo company / Synthetic data', 'business': 'Performance marketing agency (Meta & Google Ads management, creative, analytics)',
        'hq': 'Denver, CO (fictional)', 'currency': 'USD', 'cutoff': '2026-10-31', 'first_period': MONTHS[0], 'last_period': MONTHS[-1],
        'fiscal_year_note': 'Fiscal year runs November–October; FY2026 = Nov 2025–Oct 2026', 'fiscal_years': ['FY2025', 'FY2026'],
        'opening_cash': D(cash_forecast['opening_cash']), 'cash_week_convention': cash_forecast['week_convention'],
        'cash_excluded_overlaps': cash_forecast['excluded_overlaps'], 'owner_distribution_policy': cash_forecast['owner_distribution_policy'],
        'recon_pass': recon_pass, 'recon_total': len(CHECKS), 'source_rows': sum(int(r['row_count']) for r in scat.values()),
        'source_files': sum(int(r['physical_csv_count']) for r in scat.values()), 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stream_names': stream_name}
datamart = {'meta': meta, 'datasets': DATASETS}
txt = json.dumps(datamart, separators=(',', ':'), default=lambda o: sorted(o) if isinstance(o, set) else str(o))
for raw in RAW_NAMES: txt = txt.replace(raw, DISPLAY_NAME)
assert 'Signal Harbor' not in txt
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'datamart.json'), 'w') as fh: fh.write(txt)
with open(os.path.join(OUT, 'reconciliation_report.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=['check', 'status', 'detail']); w.writeheader(); w.writerows(CHECKS)
fails = [x for x in CHECKS if x['status'] != 'PASS']
print(f"{len(CHECKS)} checks, {len(fails)} failed; datamart {len(txt)/1e6:.2f} MB; datasets {len(DATASETS)}")
for x in fails: print('FAIL', x['check'], x['detail'])
