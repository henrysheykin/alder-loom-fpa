"""Independent delivery-cohort RO cost to earned-period GL contribution bridge.
Reads saved CSV only. No import of or shared objects with event generator.
"""
from pathlib import Path
import csv,json,argparse
from collections import defaultdict
from decimal import Decimal
candidate=Path(__file__).resolve().parents[1]
defaultroot=candidate if (candidate/'metadata/table_schemas.json').exists() else candidate/'outputs'/'cedar_bend_auto_data'
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=defaultroot)
ROOT=parser.parse_args().root.resolve()
S=json.loads((ROOT/'metadata/table_schemas.json').read_text(encoding='utf-8'))
def read(t):
    for f in S[t]['physical_files']:
        with (ROOT/'sources'/f).open(encoding='utf-8-sig',newline='') as h:yield from csv.DictReader(h)
def c(v):return int(Decimal(v)*100)
def m(v):return f'{Decimal(v)/100:.2f}'
def save(path,rr):
    with path.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
ro={r['ro_id']:r for r in read('shop/repair_orders')}
by=defaultdict(lambda:defaultdict(int));ro_alloc=defaultdict(int);ro_parts=defaultdict(int);ro_sublet=defaultdict(int)
for r in read('payroll/job_cost_allocations'):
    v=c(r['allocated_actual_payroll_usd']);key=(r['allocation_month'],r['location_id']);by[key]['period_productive_allocated_labor']+=v;ro_alloc[r['ro_id']]+=v
    if ro[r['ro_id']]['is_warranty']=='True':by[key]['period_warranty_allocated_labor']+=v
for r in read('inventory/ro_parts_usage'):ro_parts[r['ro_id']]+=c(r['issued_carrying_cost_usd'])
for r in read('operating/sublet_services'):ro_sublet[r['ro_id']]+=c(r['cost_usd'])
for r in read('billing/invoices'):
    rid=r['ro_id'];key=(r['invoice_date'][:7],r['location_id']);x=by[key]
    x['delivered_customer_ro_count']+=1;x['delivered_customer_ro_net_revenue']+=c(r['net_usd']);x['delivered_customer_parts_cogs']+=ro_parts[rid];x['delivered_customer_sublet_cogs']+=ro_sublet[rid];x['delivered_customer_cohort_allocated_labor']+=ro_alloc[rid]
gl=defaultdict(lambda:defaultdict(int))
for r in read('accounting/general_ledger'):
    key=(r['journal_date'][:7],r['location_id']);gl[key][r['account_code']]+=c(r['debit_usd'])-c(r['credit_usd'])
rows=[];checks=[]
for key in sorted(gl):
    mo,loc=key;x=by[key];g=gl[key]
    earned=sum(g[a] for a in ['5000','5010','5015']);unallocated=earned-x['period_productive_allocated_labor'];war=x['period_warranty_allocated_labor'];timing=x['period_productive_allocated_labor']-war-x['delivered_customer_cohort_allocated_labor'];concession=g['4090'];shrink=g['5130'];warparts=g['5110'];recovery=-g['5120']
    cohort=x['delivered_customer_ro_net_revenue']-x['delivered_customer_parts_cogs']-x['delivered_customer_sublet_cogs']-x['delivered_customer_cohort_allocated_labor']
    bridge=cohort-concession-unallocated-war-timing-warparts+recovery-shrink
    glcontrib=-sum(g[a] for a in ['4000','4010','4020','4030','4090'])-sum(g[a] for a in ['5000','5010','5015','5100','5110','5120','5130','5200'])
    difference=bridge-glcontrib
    assert difference==0,(key,difference)
    assert unallocated>=0,(key,unallocated)
    row=dict(month=mo,location_id=loc,delivered_customer_ro_count=x['delivered_customer_ro_count'],delivered_customer_ro_net_revenue_usd=m(x['delivered_customer_ro_net_revenue']),delivered_customer_parts_cogs_usd=m(x['delivered_customer_parts_cogs']),delivered_customer_sublet_cogs_usd=m(x['delivered_customer_sublet_cogs']),delivered_customer_cohort_allocated_labor_usd=m(x['delivered_customer_cohort_allocated_labor']),ro_cohort_margin_before_warranty_usd=m(cohort),period_customer_concessions_usd=m(concession),period_earned_tech_payroll_usd=m(earned),period_all_ro_labor_allocation_usd=m(x['period_productive_allocated_labor']),period_idle_pto_unallocated_labor_usd=m(unallocated),period_warranty_labor_allocation_usd=m(war),labor_earned_vs_delivery_cohort_timing_usd=m(timing),period_warranty_parts_usd=m(warparts),period_supplier_warranty_recoveries_usd=m(recovery),period_stock_writeoffs_usd=m(shrink),bridged_period_contribution_usd=m(bridge),gl_period_direct_contribution_usd=m(glcontrib),difference_usd=m(difference),posting_status='derived_control_only_not_source')
    rows.append(row)
company=[]
for mo in sorted({k[0] for k in gl}):
    rr=[r for r in rows if r['month']==mo];r=dict(month=mo,location_id='COMPANY')
    for f in rows[0]:
        if f.endswith('_usd'):r[f]=m(sum(c(x[f]) for x in rr))
        elif f=='delivered_customer_ro_count':r[f]=sum(int(x[f]) for x in rr)
    r['posting_status']='derived_control_only_not_source';company.append(r)
dest=ROOT/'validation';dest.mkdir(exist_ok=True)
save(dest/'location_monthly_margin_bridge.csv',rows);save(dest/'monthly_margin_bridge.csv',company)
save(dest/'margin_bridge_validation.csv',[dict(check_name='Saved CSV RO cohort margins bridge to GL direct contribution',status='PASS',evaluated=len(rows)+len(company),failures=0,max_difference_cents=0),dict(check_name='Productive allocations plus unallocated earned cost reconcile payroll',status='PASS',evaluated=len(rows),failures=0,max_difference_cents=0)])
(dest/'MARGIN_BRIDGE_RU.md').write_text('''# RO margin и P&L: временной мост

Два CSV содержат 24 company и 96 location/HQ строк, вычисленных заново из сохранённых sources. Они являются control outputs, не источниками новых фактов.

RO cohort margin = net invoices выданных клиентских RO − FIFO parts COGS этих RO − outsourced cost − фактический payroll, распределённый на все их сегменты, включая другие earned periods.

Чтобы перейти к GL contribution периода, вычтите текущие concessions, непродуктивную/неразнесённую оплату, warranty labor allocation и `labor_earned_vs_delivery_cohort_timing`; вычтите warranty parts и stock writeoffs, прибавьте supplier recovery. Timing может быть отрицательным: это перенос между периодом выполнения и периодом выдачи.

Consolidated direct contribution = net earned revenue − debit-net 5000/5010/5015/5100/5110/5120/5130/5200. Следующий уровень location contribution вычитает локальные overhead GL. Shared cost allocation — отдельная нулевая по компании управленческая таблица, к consolidated expense второй раз не добавляется.

Зарплата полностью признаётся по earned payroll. RO allocation и этот bridge не создают проводок. WIP содержит issued parts и completed sublet, без капитализации labor. Все расхождения должны равняться 0.00 USD; скрипт `add_margin_controls.py` останавливается при любом ненулевом расхождении.
''',encoding='utf-8')
print(json.dumps({'margin_bridge_location_rows':len(rows),'company_rows':len(company),'failures':0}))
