"""Cedar Bend Auto Care: deterministic synthetic economic event generator.
Only stdlib; monetary internal representation integer cents, quantities milli-base-unit.
"""
from __future__ import annotations
import csv, json, random, calendar, hashlib, zipfile, shutil, argparse
import heapq
from pathlib import Path
from datetime import date, datetime, timedelta
from collections import defaultdict, deque
from decimal import Decimal, ROUND_HALF_UP

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / 'outputs' / 'cedar_bend_auto_data'
START, CUT = date(2024,11,1), date(2026,10,31)
R = random.Random(19631119)
T, META, REL = defaultdict(list), {}, []
COUNTS = defaultdict(int)
def uid(prefix):
    COUNTS[prefix]+=1
    return f'{prefix}-{COUNTS[prefix]:08d}'
def ds(x): return x.isoformat() if x is not None else ''
def money(c): return f'{c/100:.2f}'
def qty(q): return f'{q/1000:.3f}'
def roundi(x): return int(Decimal(str(x)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def cents(s): return roundi(Decimal(str(s))*100)
def days(a,b):
    while a<=b:
        yield a
        a+=timedelta(days=1)
def monthend(d): return date(d.year,d.month,calendar.monthrange(d.year,d.month)[1])
def addmonth(d,n):
    y,m=divmod(d.year*12+d.month-1+n,12)
    return date(y,m+1,min(d.day,calendar.monthrange(y,m+1)[1]))
MONTHS=[addmonth(START,i) for i in range(24)]
def biz(d,n=0):
    while d.weekday()>4: d+=timedelta(days=1)
    for _ in range(n):
        d+=timedelta(days=1)
        while d.weekday()>4:d+=timedelta(days=1)
    return d
def decl(t,pk,grain,note='',partition=''):
    META[t]={'primary_key':pk.split(','),'grain':grain,'notes':note,'partition_column':partition,'fields':[]}
def emit(t,**row):
    if t not in META: raise KeyError(t)
    for k in row:
        if k not in META[t]['fields']:META[t]['fields'].append(k)
    row={k:ds(v) if isinstance(v,(date,datetime)) else str(v) if v is not None else '' for k,v in row.items()}
    T[t].append(row)
    return row
def link(t,col,target,tc,note=''):
    REL.append(dict(from_table=t,from_column=col,to_table=target,to_column=tc,cardinality='many_to_one',note=note or 'Blank permitted only when not applicable.'))

def setup():
    tables=[
      ('shop/locations','location_id','One operating shop or shared cost center'),
      ('shop/bays','bay_id','One physical service bay'),
      ('shop/customers','customer_id','One fictional retail or commercial customer'),
      ('shop/fleet_accounts','fleet_account_id','One commercial account and agreed credit policy'),
      ('shop/vehicles','vehicle_id','One synthetic vehicle; DEMO identifiers are not VINs/plates'),
      ('shop/service_catalog','service_id','One standard job template'),
      ('shop/labor_rate_history','rate_id','One location and effective pricing period'),
      ('shop/estimates','estimate_id','One estimate version (one base plus optional change order)'),
      ('shop/estimate_lines','estimate_line_id','One quoted line in a specific estimate version'),
      ('shop/approvals','approval_id','One estimate approval/decline/pending decision'),
      ('shop/repair_orders','ro_id','One repair order as of cutoff; not automatically revenue'),
      ('shop/jobs','job_id','One service job inside a repair order'),
      ('shop/ro_lines','ro_line_id','One approved parts/labor/fee/sublet RO line'),
      ('shop/status_events','status_event_id','One actual status transition'),
      ('schedule/appointments','appointment_id','One agreed appointment including cancellations/no-shows/future bookings'),
      ('schedule/technician_availability','availability_id','One technician working date; physical available minutes'),
      ('schedule/job_segments','segment_id','One uninterrupted physical technician job interval; future intervals have blank actual times'),
      ('schedule/bay_occupancy','occupancy_id','One RO continuous bay occupation, including overnight waiting'),
      ('schedule/daily_capacity','capacity_id','One bay/technician/date, actual work and idle minutes'),
      ('schedule/bay_calendar','bay_calendar_id','One physical bay/calendar date, including unstaffed bays and closed dates'),
      ('inventory/parts_catalog','sku','One base inventory SKU and purchase pack conversion'),
      ('inventory/opening_stock','opening_stock_id','One location/SKU opening FIFO lot'),
      ('inventory/movements','movement_id','One physical stock/value event, ordered by event_sequence'),
      ('inventory/reservations','reservation_id','One part reservation with issued/released/open status; not physical stock'),
      ('inventory/transfers','transfer_id','One inter-shop paired transfer'),
      ('inventory/cycle_counts','count_id','One counted SKU adjustment; damage/shrink recorded separately'),
      ('inventory/month_end_balances','balance_id','One month/location/SKU closing quantity and carrying value'),
      ('inventory/wip_balances','wip_balance_id','One open RO at each month end; parts-only WIP'),
      ('inventory/ro_parts_usage','part_usage_id','One RO/SKU issue/install/delivered cost bridge; not an additional stock movement'),
      ('purchasing/suppliers','supplier_id','One fictional automotive supplier'),
      ('purchasing/terms_history','terms_id','One supplier contract period'),
      ('purchasing/purchase_price_history','price_id','One SKU purchase price effective version'),
      ('purchasing/purchase_orders','po_id','One purchase order; open quantity is not a second AP obligation'),
      ('purchasing/po_lines','po_line_id','One SKU purchase commitment in purchase and base units'),
      ('purchasing/receipts','receipt_id','One received PO line'),
      ('purchasing/supplier_returns','supplier_return_id','One stock return at original lot cost and supplier credit'),
      ('purchasing/supplier_statements','statement_id','One monthly supplier/location summary of existing bills/credits'),
      ('purchasing/statement_items','statement_item_id','One bill or credit referenced by a statement; not new purchases'),
      ('purchasing/payment_schedule','schedule_id','One residual supplier bill or unreceived PO commitment at cutoff'),
      ('billing/invoices','invoice_id','One customer invoice created on actual vehicle delivery'),
      ('billing/invoice_lines','invoice_line_id','One billed RO line; original remains unchanged after credits'),
      ('billing/payments','payment_id','One actual customer receipt or refund, signed cash amount'),
      ('billing/payment_allocations','allocation_id','One payment or deposit application to invoice'),
      ('billing/deposits','deposit_id','One special-order deposit received before recognition'),
      ('billing/deposit_events','deposit_event_id','One deposit receipt/application/refund event; signed liability change'),
      ('billing/credit_notes','credit_note_id','One post-invoice service concession and tax reversal'),
      ('billing/credit_lines','credit_line_id','One original invoice line credited; no restock assumed'),
      ('billing/open_ar','invoice_id','One unpaid invoice at cutoff after credits and allocations'),
      ('billing/open_deposits','deposit_id','One unapplied deposit liability at cutoff'),
      ('warranty/comebacks','comeback_id','One free corrective RO linked to original completed RO'),
      ('warranty/supplier_recoveries','recovery_id','One supplier credit recovery for defective part; separate from customer revenue'),
      ('processor/balance_transactions','balance_transaction_id','One card capture/refund/processing fee settlement component'),
      ('processor/payouts','payout_id','One settled or in-transit payout batch by location'),
      ('payroll/employees','employee_id','One fictional employee with employment dates'),
      ('payroll/compensation_history','compensation_id','One effective compensation policy per employee'),
      ('payroll/attendance','attendance_id','One employee/date approved paid attendance/PTO'),
      ('payroll/runs','payroll_run_id','One location semi-monthly earned payroll run and funding status'),
      ('payroll/earnings','earning_id','One employee/run gross-to-net including employer burden'),
      ('payroll/job_cost_allocations','labor_allocation_id','One RO/month allocation of earned actual technician payroll; management memo only'),
      ('payroll/funding','funding_id','One actual payroll funding debit covering net pay/remittances/benefits'),
      ('operating/vendors','vendor_id','One operating vendor; suppliers are separate mirrored vendor IDs'),
      ('operating/recurring_contracts','contract_id','One recurring contract with cash timing and overlap key'),
      ('operating/assets','asset_id','One fixed asset with opening or in-period in-service date'),
      ('operating/depreciation','depreciation_id','One asset/month straight-line charge'),
      ('operating/sublet_services','sublet_id','One outsourced job tied to RO and vendor bill'),
      ('finance/loans','loan_id','One equipment loan contract'),
      ('finance/debt_schedule','debt_schedule_id','One loan installment; future rows are contractual plans only'),
      ('finance/tax_register','tax_period_id','One location/month synthetic sales tax liability and remittance'),
      ('finance/owner_distributions','distribution_id','One actual quarterly owner cash distribution; equity, not operating expense'),
      ('marketing/campaigns','campaign_id','One synthetic Meta/Google campaign'),
      ('marketing/daily_performance','performance_id','One platform/campaign/date spend and overlapping platform claims'),
      ('marketing/leads','lead_id','One observed lead with source attribution and appointment/RO outcome'),
      ('marketing/billing','ad_bill_id','One platform/location/month bill; summarizes daily spend'),
      ('accounting/chart_of_accounts','account_code','One ledger account and reporting classification'),
      ('accounting/opening_trial_balance','opening_id','One account/location opening signed debit-minus-credit balance'),
      ('accounting/general_ledger','journal_line_id','One double-entry journal line; no opening entries inside GL'),
      ('accounting/bills','bill_id','One supplier/operating invoice recognized at receipt/service period'),
      ('accounting/bill_lines','bill_line_id','One supplier bill accounting line'),
      ('accounting/vendor_credits','vendor_credit_id','One supplier credit or warranty recovery'),
      ('accounting/ap_allocations','ap_allocation_id','One bill cash-payment or credit allocation'),
      ('accounting/vendor_payments','vendor_payment_id','One actual cash disbursement to vendor'),
      ('accounting/open_ap','bill_id','One unpaid bill at cutoff net of credits and payments'),
      ('accounting/monthly_trial_balance','trial_balance_id','One month/location/account period activity plus signed cumulative closing'),
      ('accounting/shared_cost_allocations','shared_allocation_id','One zero-sum HQ expense management allocation; not GL'),
      ('bank/accounts','bank_account_id','One physical USD operating bank account'),
      ('bank/statement','bank_transaction_id','One posted bank movement with chronological running balance'),
      ('bank/monthly_statements','bank_statement_id','One bank month opening/inflow/outflow/closing'),
      ('planning/budget_versions','budget_version_id','One original approved budget version'),
      ('planning/monthly_budget','budget_line_id','One approved month/location/account budget amount'),
      ('planning/driver_plan','driver_plan_id','One approved month/shop labor/headcount/volume/pricing plan'),
      ('planning/forecast_assumptions','assumption_id','One explicit forecast driver as of cutoff, not actual or approved budget'),
      ('planning/commitments','commitment_id','One future obligation/demand driver with overlap identifiers'),
      ('planning/business_events','event_id','One scenario change with effective date and evidence table references'),
    ]
    for t,pk,g in tables:decl(t,pk,g)
    META['inventory/wip_balances']['grain']='One undelivered RO/month end: issued parts plus completed outsourced service WIP; labor expensed as earned'
    META['schedule/daily_capacity']['notes']='Staffed technician/bay availability only. Total physical-bay denominator is schedule/bay_calendar, including unstaffed bays.'
    for t,col in [('shop/repair_orders','opened_date'),('shop/jobs','opened_date'),('shop/ro_lines','opened_date'),('shop/estimate_lines','estimate_date'),('shop/status_events','event_date'),('schedule/job_segments','work_date'),('schedule/technician_availability','work_date'),('schedule/daily_capacity','work_date'),('payroll/attendance','work_date'),('inventory/movements','movement_date'),('billing/invoice_lines','invoice_date'),('accounting/general_ledger','journal_date')]:META[t]['partition_column']=col

ACCOUNTS={
 '1000':('Operating bank','asset','cash','debit'), '1010':('Card processor clearing','asset','processor','debit'),
 '1020':('Cash till and undeposited ACH','asset','undeposited','debit'), '1100':('Customer accounts receivable','asset','ar','debit'),
 '1200':('Parts inventory','asset','inventory','debit'), '1210':('RO parts work in process','asset','wip','debit'),
 '1300':('Inter-shop transfer clearing','asset','internal_clearing','debit'),
 '1500':('Shop tools and equipment cost','asset','fixed_assets','debit'), '1590':('Accumulated depreciation','contra_asset','fixed_assets','credit'),
 '2000':('Accounts payable','liability','ap','credit'), '2100':('Synthetic sales tax payable','liability','tax','credit'),
 '2200':('Customer deposits','liability','deposits','credit'), '2300':('Payroll funding payable','liability','payroll','credit'),
 '2500':('Equipment term debt','liability','debt','credit'), '3000':('Opening owner equity','equity','equity','credit'),
 '3100':('Owner distributions','equity','owner_distributions','debit'),
 '4000':('Labor sales','revenue','labor_sales','credit'), '4010':('Parts sales','revenue','parts_sales','credit'),
 '4020':('Shop supplies fees','revenue','fee_sales','credit'), '4030':('Sublet sales','revenue','sublet_sales','credit'),
 '4090':('Customer concessions','contra_revenue','discounts','debit'), '5000':('Technician gross wages and bonuses','expense','direct_labor','debit'),
 '5010':('Technician employer payroll taxes','expense','direct_labor','debit'), '5015':('Technician employer benefits','expense','direct_labor','debit'),
 '5100':('Delivered parts COGS','expense','parts_cogs','debit'), '5110':('Warranty parts expense','expense','warranty','debit'),
 '5120':('Supplier warranty recoveries','contra_expense','warranty','credit'), '5130':('Inventory damage and shrink','expense','inventory_loss','debit'),
 '5200':('Delivered outsourced service cost','expense','sublet_cogs','debit'),
 '6100':('Location non-technician wages','expense','location_payroll','debit'), '6110':('Location non-technician payroll burden','expense','location_payroll','debit'),
 '6200':('Shared management payroll','expense','shared_payroll','debit'), '6210':('Shared payroll burden','expense','shared_payroll','debit'),
 '6300':('Property rent','expense','rent','debit'), '6310':('Utilities','expense','utilities','debit'), '6320':('Insurance','expense','insurance','debit'),
 '6330':('Software and subscriptions','expense','software','debit'), '6340':('Equipment maintenance','expense','maintenance','debit'),
 '6350':('Waste disposal and shop overhead','expense','other_opex','debit'), '6400':('Advertising media spend','expense','marketing','debit'),
 '6500':('Merchant processor fees','expense','merchant_fees','debit'), '6600':('Depreciation','expense','depreciation','debit'),
 '6700':('Loan interest','expense','interest','debit')}
J=[]; BANK=[]; OPEN=defaultdict(int); BILLS={}; ROS={}; EMP={}; SKUS={}; INV={}; LOTS={}; WIP=defaultdict(int)
def post(d,loc,source,typ,ref,entries,memo=''):
    assert START<=d<=CUT,(d,typ)
    assert sum(v for a,v in entries)==0,(typ,ref,entries)
    jid=uid('J')
    for a,v in entries:
        if not v:continue
        row=emit('accounting/general_ledger',journal_line_id=uid('JL'),journal_id=jid,journal_date=d,location_id=loc,account_code=a,debit_usd=money(max(v,0)),credit_usd=money(max(-v,0)),source_system=source,source_type=typ,source_id=ref,memo=memo)
        J.append((d,loc,a,v,row))
    return jid
def bank(d,loc,amount,typ,ref,counterparty):
    assert d<=CUT
    bid=uid('BANK')
    BANK.append(dict(bank_transaction_id=bid,bank_account_id='BANK-OPERATING-DEMO',posted_date=d,location_id=loc,transaction_type=typ,source_id=ref,counterparty=counterparty,amount_cents=amount))
    return bid
def opening(loc,a,v):OPEN[(loc,a)]+=v

def masters():
    emit('bank/accounts',bank_account_id='BANK-OPERATING-DEMO',account_name='Cedar Bend operating DEMO',currency='USD',opening_balance_usd='900000.00',opening_date=START-timedelta(days=1))
    for a,(name,typ,group,norm) in ACCOUNTS.items():emit('accounting/chart_of_accounts',account_code=a,account_name=name,account_type=typ,reporting_group=group,normal_balance=norm)
    for i,(name,city) in enumerate([('North Creek','DEMO North Metro'),('River West','DEMO West Metro'),('Oak Junction','DEMO East Metro')],1):
        loc=f'LOC-{i:02d}'
        emit('shop/locations',location_id=loc,location_name=name,city=city,state_region='Synthetic US jurisdiction',timezone='America/Chicago',bay_count=6,opening_date='2018-01-01',cost_center_type='operating_shop',currency='USD')
        opening(loc,'1000',25000000)
        for b in range(1,7):emit('shop/bays',bay_id=f'{loc}-B{b}',location_id=loc,bay_type='general_repair_lift',available_from='2020-01-01',nominal_weekday_minutes=480)
        for n,(eff,rate) in enumerate([('2024-01-01',138+i*3),('2025-06-01',143+i*3),('2026-03-01',148+i*3)]):
            emit('shop/labor_rate_history',rate_id=f'RATE-{i}-{n}',location_id=loc,effective_from=eff,effective_to=['2025-05-31','2026-02-28',''][n],retail_hourly_rate_usd=f'{rate}.00',fleet_discount_pct='5.00')
    emit('shop/locations',location_id='HQ',location_name='Shared office',city='DEMO Central Metro',state_region='Synthetic US jurisdiction',timezone='America/Chicago',bay_count=0,opening_date='2018-01-01',cost_center_type='shared',currency='USD')
    opening('HQ','1000',15000000)
    supplier_names=['Demo Metro Parts Supply','Demo Tire Distribution','Demo Lubricants Wholesale','Demo Precision Components']
    for i,name in enumerate(supplier_names,1):
        sid=f'SUP-{i:02d}'
        emit('purchasing/suppliers',supplier_id=sid,supplier_name=name,email=f'accounts.sup{i}@example.com',currency='USD',statement_frequency='monthly',invoice_frequency='on_receipt',core_policy='No refundable cores modeled')
        for n,(eff,net) in enumerate([('2024-01-01',30),('2026-08-01',21 if i==4 else 30)]):
            emit('purchasing/terms_history',terms_id=f'TERM-{i}-{n}',supplier_id=sid,effective_from=eff,effective_to='2026-07-31' if n==0 else '',net_days=net,late_fee_pct='0.00',contract_note='Synthetic agreed supplier terms')
    parts=[('OIL','Synthetic motor oil','liter',3,390,12),('FILTER','Oil filter','each',1,680,12),('BRAKE','Axle pad kit','each',1,5800,1),('ROTOR','Brake rotor','each',1,4900,1),('BRAKEFLUID','Brake fluid','liter',3,650,6),('TIRE','All-season tire','each',2,8100,1),('COOLANT','Premix coolant','liter',3,310,12),('PUMP','Water pump','each',4,8900,1),('BATTERY','12V battery no core','each',1,10900,1),('AIR','Engine air filter','each',1,1300,6),('CABIN','Cabin air filter','each',1,1550,6),('STRUT','Strut assembly','each',4,12900,1),('BOLT','Suspension hardware kit','each',1,1800,1),('TIMING','Stocked aftermarket timing kit','each',4,24500,1),('SEAL','Seal kit','each',4,3900,1),('SENSOR','Diagnostic sensor','each',4,7200,1),('TIMING-SO','Customer-approved OEM special-order timing kit; not interchangeable with aftermarket kit','each',4,24500,1)]
    for sku,name,u,si,c,pack in parts:
        SKUS[sku]={'cost':c,'supplier':f'SUP-{si:02d}','unit':u,'pack':pack}
        emit('inventory/parts_catalog',sku=sku,description=name,base_unit=u,purchase_unit='case' if pack>1 else 'each',base_units_per_purchase_unit=f'{pack}.000',supplier_id=f'SUP-{si:02d}',special_order=str(sku in ['TIMING','TIMING-SO','STRUT','PUMP']),core_charge_usd='0.00',valuation_method='FIFO_CENTS')
        for n,(eff,mult) in enumerate([('2024-01-01',1),('2025-07-01',1.09),('2026-04-01',1.26)]):
            cost=roundi(c*mult)
            emit('purchasing/purchase_price_history',price_id=f'PRICE-{sku}-{n}',sku=sku,supplier_id=f'SUP-{si:02d}',effective_from=eff,effective_to=['2025-06-30','2026-03-31',''][n],base_unit_price_usd=money(cost),purchase_unit_price_usd=money(cost*pack),base_units_per_purchase_unit=f'{pack}.000',price_change_reason=['opening contract','2025 supplier cost increase','2026 supplier price step'][n])
    for i in range(12):
        cid=f'FLEET-CUST-{i+1:03d}';fid=f'FLEET-{i+1:03d}'
        emit('shop/customers',customer_id=cid,customer_type='fleet',customer_name=f'Demo Fleet {i+1:02d} LLC',email=f'fleet{i+1}@example.com',created_date='2023-01-01',acquisition_source='commercial_outreach')
        emit('shop/fleet_accounts',fleet_account_id=fid,customer_id=cid,contract_start_date='2024-01-01',net_days=30,credit_limit_usd='45000.00',payment_pattern='40pct_day25_60pct_day60' if i%2==0 else '40pct_day35_60pct_day72',labor_discount_pct='5.00',expected_days_after_invoice=60 if i%2==0 else 72)
        for v in range(10):emit('shop/vehicles',vehicle_id=f'VEH-F{i+1:03d}-{v+1:02d}',customer_id=cid,make='Demo Commercial Make',model='Service Van',model_year=2018+v%6,demo_vin=f'DEMO-FLEET-{i+1:03d}-{v+1:02d}',demo_plate=f'DEMO-F-{i+1:03d}-{v+1:02d}',opening_odometer_miles=55000+v*6200)
    first=['Avery','Jordan','Casey','Morgan','Taylor','Riley','Cameron','Alex','Jamie','Parker']
    for i in range(4200):
        cid=f'CUST-{i+1:06d}';ch=R.choices(['repeat','google','meta','referral','organic','direct'],[28,23,9,17,15,8])[0]
        emit('shop/customers',customer_id=cid,customer_type='retail',customer_name=f'{first[i%10]} Demo{i+1:05d}',email=f'customer{i+1:05d}@example.com',created_date='2024-01-01',acquisition_source=ch)
        emit('shop/vehicles',vehicle_id=f'VEH-{i+1:06d}',customer_id=cid,make=['Demo Sedan Make','Demo SUV Make','Demo Pickup Make'][i%3],model=f'DEMO Model {i%8+1}',model_year=2012+i%12,demo_vin=f'DEMO-VEHICLE-{i+1:06d}',demo_plate=f'DEMO-{i+1:06d}',opening_odometer_miles=28000+i%120*1000)

SERVICES=[
 ('OIL','Oil and filter maintenance',0.8,45,{'OIL':5500,'FILTER':1000}),
 ('BRAKE','Axle brake repair',3.0,140,{'BRAKE':1000,'ROTOR':2000,'BRAKEFLUID':500}),
 ('TIRES','Four tire replacement',2.1,110,{'TIRE':4000}),
 ('DIAG','Diagnostic and sensor repair',2.0,110,{'SENSOR':1000}),
 ('COOLING','Cooling system repair',3.8,195,{'PUMP':1000,'COOLANT':8000}),
 ('BATTERY','Battery replacement',0.7,35,{'BATTERY':1000}),
 ('MAINT','Scheduled maintenance',2.3,115,{'OIL':5500,'FILTER':1000,'AIR':1000,'CABIN':1000}),
 ('SUSP','Suspension repair',5.2,270,{'STRUT':2000,'BOLT':1000}),
 ('TIMING','Timing system repair',8.0,450,{'TIMING':1000,'SEAL':1000,'OIL':5500})]

def employees():
    for locnum in range(1,4):
        loc=f'LOC-{locnum:02d}'
        for ti in range(1,7):
            hire=date(2020,1,1) if ti<=5 else [date(2026,2,2),date(2026,5,4),date(2026,7,6)][locnum-1]
            empid=f'EMP-{locnum}-T{ti}'
            new_employee(empid,loc,'technician',hire,29+ti*1.8+locnum,0,f'{loc}-B{ti}')
        for ad in range(1,3):new_employee(f'EMP-{locnum}-A{ad}',loc,'advisor',date(2021,1,1),24+ad,0,'')
        new_employee(f'EMP-{locnum}-M1',loc,'shop_manager',date(2020,1,1),0,78000+locnum*2000,'')
    new_employee('EMP-HQ-01','HQ','general_manager',date(2020,1,1),0,118000,'')
    new_employee('EMP-HQ-02','HQ','finance_operations',date(2020,1,1),0,78000,'')
    for s,name,h,m,p in SERVICES:emit('shop/service_catalog',service_id=s,service_name=name,default_book_hours=f'{h:.2f}',opening_expected_actual_minutes=m,parts_recipe_json=json.dumps({k:qty(v) for k,v in p.items()}),recognition_policy='delivered_vehicle',service_type='maintenance' if s in ['OIL','MAINT'] else 'repair')

def new_employee(eid,loc,role,hire,rate,salary,bay):
    e={'id':eid,'loc':loc,'role':role,'hire':hire,'rate':cents(rate),'salary':cents(salary),'bay':bay}
    EMP[eid]=e
    emit('payroll/employees',employee_id=eid,location_id=loc,employee_name=f'Demo {eid}',role=role,email=f'{eid.lower()}@example.com',hire_date=hire,termination_date='',home_bay_id=bay,compensation_type='salary' if salary else 'hourly_plus_book_bonus' if role=='technician' else 'hourly',currency='USD')
    for n,(eff,mult) in enumerate([(hire,1),(date(2026,1,1),1.045)]):
        if n and hire>=eff:continue
        emit('payroll/compensation_history',compensation_id=f'COMP-{eid}-{n}',employee_id=eid,effective_from=eff,effective_to='2025-12-31' if n==0 and hire<date(2026,1,1) else '',hourly_rate_usd=money(roundi(e['rate']*mult)),annual_salary_usd=money(roundi(e['salary']*mult)),overtime_multiplier='1.50',book_bonus_threshold_hours='70.00' if role=='technician' else '0.00',book_bonus_per_hour_usd='4.00' if role=='technician' else '0.00',employee_withholding_pct='20.00',employer_tax_pct='8.00',employer_benefit_per_paid_hour_usd='2.20',policy_note='Synthetic compensation parameters; bonus on delivered customer book hours in pay period; no flat-rate-only pay')

AVAIL={}; ATTEND={}; SEGMENTS=[]; OCCUP=[]; JOB_CENTS=defaultdict(int); JOB_MINS=defaultdict(int); BOOK=defaultdict(float)
def attendance():
    for d in days(START,CUT):
        for eid,e in EMP.items():
            if d<e['hire'] or d.weekday()>5:continue
            # One selected Saturday monthly, technicians/advisors only, paid as OT.
            sat=d.weekday()==5
            if sat and (not (8<=d.day<=14) or e['role'] not in ['technician','advisor']):continue
            pto=(not sat and e['role']=='technician' and (d.toordinal()+sum(map(ord,eid)))%61==0)
            ot=60 if d.weekday()==3 and e['role'] in ['technician','advisor'] and d.day%2==0 else 0
            if pto:ot=0
            reg=0 if sat else 480
            overtime=240 if sat else ot
            paid=reg+overtime;physical=0 if pto else paid
            aid=uid('ATT')
            row=emit('payroll/attendance',attendance_id=aid,employee_id=eid,location_id=e['loc'],work_date=d,regular_paid_minutes=reg,overtime_paid_minutes=overtime,pto_paid_minutes=480 if pto else 0,approved_paid_minutes=paid,paid_presence_minutes=0 if pto else paid,approval_status='approved',week_start_date=d-timedelta(days=d.weekday()))
            ATTEND[(eid,d)]=(reg,overtime,paid,physical,aid)
            if e['role']=='technician':
                AVAIL[(eid,d)]=physical
                emit('schedule/technician_availability',availability_id=uid('AV'),employee_id=eid,location_id=e['loc'],bay_id=e['bay'],work_date=d,available_minutes=physical,paid_attendance_minutes=paid,unavailable_reason='PTO' if pto else '',shift_start=f'{d}T08:00:00' if physical else '',lunch_start=f'{d}T12:00:00' if physical and not sat else '',lunch_end=f'{d}T13:00:00' if physical and not sat else '',shift_end=f'{d}T{12 if sat else 18 if ot else 17}:00:00' if physical else '',attendance_id=aid)

def rate_for(loc,d,fleet):
    rows=[r for r in T['shop/labor_rate_history'] if r['location_id']==loc and r['effective_from']<=str(d)]
    r=rows[-1];v=cents(r['retail_hourly_rate_usd']);return r['rate_id'],roundi(v*.95) if fleet else v
def price_for(sku,d):
    rows=[r for r in T['purchasing/purchase_price_history'] if r['sku']==sku and r['effective_from']<=str(d)]
    return rows[-1]['price_id'],cents(rows[-1]['base_unit_price_usd'])
def periodkey(d):return (d.year,d.month,1 if d.day<=15 else 2)

def build_work():
    # A bay has one home technician; cursor advances through paid physical intervals.
    customer_map={r['customer_id']:r for r in T['shop/customers']}
    for eid,e in EMP.items():
        if e['role']!='technician':continue
        intervals=[]
        for d in days(max(START,e['hire']),CUT):
            cap=AVAIL.get((eid,d),0)
            if not cap:continue
            intervals.append([datetime.combine(d,datetime.min.time()).replace(hour=8), min(cap,240)])
            if cap>240:intervals.append([datetime.combine(d,datetime.min.time()).replace(hour=13),cap-240])
        ix=0;offset=0;lastday=None;usedtarget=0;daytarget=0
        while ix<len(intervals):
            begin=intervals[ix][0]+timedelta(minutes=offset);d=begin.date()
            if lastday!=d:
                lastday=d;usedtarget=0
                age=(d-e['hire']).days
                ramp=.38 if age<35 else .58 if age<75 else .73 if age<120 else 1
                season={1:.90,2:.87,3:1.0,4:1.02,5:1.08,6:1.10,7:1.06,8:1.04,9:.96,10:1.02,11:1.01,12:.91}[d.month]
                locfactor={'LOC-01':1.00,'LOC-02':.95,'LOC-03':.91}[e['loc']]
                daytarget=roundi(AVAIL[(eid,d)]*R.uniform(.62,.90)*ramp*season*locfactor)
            if usedtarget>=daytarget or intervals[ix][1]-offset<25:
                ix+=1;offset=0;continue
            # Idle between customer jobs is physically explicit.
            offset+=R.randint(6,16)
            if offset>=intervals[ix][1]:ix+=1;offset=0;continue
            begin=intervals[ix][0]+timedelta(minutes=offset);d=begin.date()
            weights=[23,21,11,12,9,9,9,5,1] if d<date(2026,4,1) else [15,23,13,12,10,8,9,8,2]
            svc=R.choices(SERVICES,weights)[0]
            free=R.random() < (.065 if e['loc']=='LOC-03' and d>=date(2026,5,1) else .014)
            originals=[v for v in ROS.values() if v['loc']==e['loc'] and v['delivered'] and v['delivered']<d and not v['warranty'] and (d-v['delivered']).days<=75] if free else []
            original=R.choice(originals) if free and originals else None
            warranty=original is not None
            if warranty:svc=next(s for s in SERVICES if s[0]==original['service'])
            factor=1.0 if d<date(2026,4,1) else 1.17
            if (d-e['hire']).days<90:factor*=1.23
            physical=max(25,roundi(svc[3]*R.uniform(.88,1.13)*factor*(.45 if warranty else 1)))
            # Occasional extensive repair occupies a bay across two days.
            if not warranty and svc[0]=='TIMING':physical+=75
            left=physical;segs=[];startix=ix
            while left and ix<len(intervals):
                st=intervals[ix][0]+timedelta(minutes=offset)
                take=min(left,intervals[ix][1]-offset)
                if take<=0:ix+=1;offset=0;continue
                segs.append((st,st+timedelta(minutes=take),take))
                offset+=take;left-=take
                if offset>=intervals[ix][1]:ix+=1;offset=0
            completion=segs[-1][1].date() if left==0 else None
            # Issue parts only on actual first work date, recognize only actual delivered.
            deliver=biz(completion,R.choices([0,1,2],[88,10,2])[0]) if completion else None
            if deliver and deliver>CUT:deliver=None
            roid=uid('RO');jid=uid('JOB');apid=uid('APPT');estid=uid('EST')
            fleet=(R.random()<.16) if not warranty else bool(original['fleet'])
            fi=R.randrange(12)
            cid=f'FLEET-CUST-{fi+1:03d}' if fleet else f'CUST-{R.randint(1,4200):06d}'
            vid=f'VEH-F{fi+1:03d}-{R.randint(1,10):02d}' if fleet else cid.replace('CUST','VEH')
            fid=f'FLEET-{fi+1:03d}' if fleet else ''
            if warranty:cid,vid,fid=original['customer'],original['vehicle'],original['fleet'];fleet=bool(fid)
            rateid,rate=rate_for(e['loc'],d,fleet)
            bh=0.0 if warranty else svc[2]
            labor=roundi(Decimal(str(bh))*Decimal(rate))
            lines=[]
            def rline(typ,sku,q,unitprice,gross,discount=0,tax=0):
                rr=emit('shop/ro_lines',ro_line_id=uid('ROL'),ro_id=roid,job_id=jid,opened_date=d,line_type=typ,sku=sku,quantity=qty(q),unit='hour' if typ=='labor' else SKUS[sku]['unit'] if sku else 'each',unit_price_usd=money(unitprice),gross_usd=money(gross),discount_usd=money(discount),net_usd=money(gross-discount),tax_usd=money(tax),total_usd=money(gross-discount+tax),book_hours=f'{bh:.2f}' if typ=='labor' else '0.00',labor_rate_id=rateid if typ=='labor' else '',is_customer_charge=str(not warranty))
                lines.append(rr);return rr
            rline('labor','',roundi(bh*1000),rate,labor)
            for sku,q in svc[4].items():
                _,base=price_for(sku,d)
                # Retail increases lag vendor cost inflation: absolute price up, margin down.
                sell=roundi(SKUS[sku]['cost']* (1.91 if d<date(2025,7,1) else 1.98 if d<date(2026,4,1) else 2.12))
                gross=0 if warranty else roundi(q*sell/1000)
                disc=0 if warranty else roundi(gross*.035) if fleet else roundi(gross*.05) if R.random()<.09 else 0
                tax=roundi((gross-disc)*.065)
                rline('parts',sku,q,0 if warranty else sell,gross,disc,tax)
            fee=0 if warranty else min(3900,roundi(labor*.055))
            rline('fee','',1000,fee,fee)
            sublet=not warranty and svc[0]=='SUSP' and R.random()<.42
            if sublet:rline('sublet','',1000,11500,11500)
            net=sum(cents(l['net_usd']) for l in lines);tax=sum(cents(l['tax_usd']) for l in lines);total=net+tax
            change=not warranty and R.random()<.09
            # Approved change order is a separately versioned quote; its lines are a delta.
            change_lines=[l for l in lines if l['line_type']=='fee']+[next(l for l in lines if l['line_type']=='parts')] if change else []
            quoted_base=total-sum(cents(l['total_usd']) for l in change_lines)
            estimates=[(estid,False,[l for l in lines if l not in change_lines],quoted_base)]
            if change:estimates.append((uid('EST'),True,change_lines,total-quoted_base))
            for es,ischange,el,etotal in estimates:
                emit('shop/estimates',estimate_id=es,ro_id=roid,customer_id=cid,location_id=e['loc'],estimate_date=d,estimate_type='change_order_delta' if ischange else 'initial',parent_estimate_id=estid if ischange else '',quoted_net_usd=money(sum(cents(l['net_usd']) for l in el)),quoted_tax_usd=money(sum(cents(l['tax_usd']) for l in el)),quoted_total_usd=money(etotal),status='approved',expires_date=d+timedelta(days=14))
                for l in el:emit('shop/estimate_lines',estimate_line_id=uid('ESTL'),estimate_id=es,ro_line_id=l['ro_line_id'],estimate_date=d,line_type=l['line_type'],quantity=l['quantity'],unit_price_usd=l['unit_price_usd'],gross_usd=l['gross_usd'],discount_usd=l['discount_usd'],net_usd=l['net_usd'],tax_usd=l['tax_usd'],total_usd=l['total_usd'])
                emit('shop/approvals',approval_id=uid('APPROVE'),estimate_id=es,ro_id=roid,decision='approved',decision_date=d,approved_total_usd=money(etotal),approval_method='fleet_authorization' if fleet else 'synthetic_sms')
            drop=begin.replace(hour=7,minute=45)
            emit('schedule/appointments',appointment_id=apid,location_id=e['loc'],customer_id=cid,vehicle_id=vid,ro_id=roid,booked_date=max(START,d-timedelta(days=R.randint(1,9))),scheduled_date=d,scheduled_start=begin,status='completed' if deliver else 'in_progress',actual_dropoff_at=drop,actual_pickup_at=datetime.combine(deliver,datetime.min.time()).replace(hour=17,minute=30) if deliver else '',cancelled_date='',source_channel='fleet' if fleet else customer_map[cid]['acquisition_source'])
            for st,en,mins in segs:
                sid=uid('SEG');SEGMENTS.append((eid,st,en,mins,roid,jid,e['loc']))
                emit('schedule/job_segments',segment_id=sid,job_id=jid,ro_id=roid,employee_id=eid,bay_id=e['bay'],location_id=e['loc'],work_date=st.date(),booked_start_at=st,booked_end_at=en,actual_start_at=st,actual_end_at=en,approved_clock_minutes=mins,approval_status='approved',attendance_id=ATTEND[(eid,st.date())][4])
                JOB_MINS[(eid,st.date(),roid)]+=mins
            occid=uid('OCC')
            emit('schedule/bay_occupancy',occupancy_id=occid,ro_id=roid,bay_id=e['bay'],location_id=e['loc'],actual_occupied_from=segs[0][0],actual_released_at=segs[-1][1] if completion else '',occupied_through_snapshot_at=segs[-1][1] if not completion else '',includes_overnight=str(segs[0][0].date()!=segs[-1][1].date()),release_policy='Moved to off-bay pickup staging after physical completion')
            status='delivered' if deliver else 'awaiting_pickup' if completion else 'in_progress'
            rr=emit('shop/repair_orders',ro_id=roid,location_id=e['loc'],customer_id=cid,vehicle_id=vid,fleet_account_id=fid,appointment_id=apid,initial_estimate_id=estid,opened_date=d,approved_date=d,actual_completion_date=completion,actual_delivery_date=deliver,actual_invoice_date=deliver,expected_delivery_date=completion if completion and deliver else biz(CUT,2),status=status,is_warranty=str(warranty),original_ro_id=original['id'] if warranty else '',approved_net_usd=money(net),approved_tax_usd=money(tax),approved_total_usd=money(total),invoice_id='',odometer_miles=60000+R.randint(0,110000))
            emit('shop/jobs',job_id=jid,ro_id=roid,opened_date=d,service_id=svc[0],employee_id=eid,bay_id=e['bay'],rate_id=rateid,labor_rate_usd=money(rate),book_billed_hours=f'{bh:.2f}',approved_actual_minutes=sum(s[2] for s in segs),remaining_planned_minutes=left,status='completed' if completion else 'in_progress',actual_completion_date=completion)
            for stt,dt in [('opened',d),('approved',d),('work_started',d),('completed',completion),('delivered',deliver),('invoiced',deliver if not warranty else None)]:
                if dt:emit('shop/status_events',status_event_id=uid('STATUS'),ro_id=roid,event_date=dt,status=stt)
            ro={'id':roid,'job':jid,'loc':e['loc'],'employee':eid,'customer':cid,'vehicle':vid,'fleet':fid,'date':d,'completion':completion,'delivered':deliver,'warranty':warranty,'original':original['id'] if warranty else '', 'service':svc[0],'parts':svc[4].copy(),'lines':lines,'net':net,'tax':tax,'total':total,'book':bh,'sublet':sublet,'raw':rr,'parts_cost':0}
            ROS[roid]=ro
            if deliver and not warranty:BOOK[(eid,periodkey(deliver))]+=bh
            if warranty:emit('warranty/comebacks',comeback_id=uid('COME'),corrective_ro_id=roid,original_ro_id=original['id'],reported_date=d,location_id=e['loc'],reason='supplier_part_failure' if R.random()<.4 else 'installation_recheck',customer_charge_usd='0.00',corrective_actual_minutes=sum(s[2] for s in segs),corrective_parts_cost_usd='',supplier_recovery_id='')
            usedtarget+=sum(s[2] for s in segs if s[0].date()==d)
    # Future agreed bookings and rejected estimates carry no actual completion/invoice.
    for loc in ['LOC-01','LOC-02','LOC-03']:
        for k in range(110):
            future=k>=70;d=biz(CUT+timedelta(days=1+k%24)) if future else biz(START+timedelta(days=R.randint(0,720)))
            if not future and d>CUT:d=biz(CUT-timedelta(days=3))
            cid=f'CUST-{R.randint(1,4200):06d}';apid=uid('APPT');es=uid('EST');vehicle=cid.replace('CUST','VEH')
            state='booked' if future else 'cancelled' if k%3 else 'no_show'
            emit('schedule/appointments',appointment_id=apid,location_id=loc,customer_id=cid,vehicle_id=vehicle,ro_id='',booked_date=CUT-timedelta(days=R.randint(0,15)) if future else max(START,d-timedelta(days=4)),scheduled_date=d,scheduled_start=f'{d}T09:00:00',status=state,actual_dropoff_at='',actual_pickup_at='',cancelled_date=max(START,d-timedelta(days=1)) if state=='cancelled' else '',source_channel='google' if k%2 else 'referral')
            emit('shop/estimates',estimate_id=es,ro_id='',customer_id=cid,location_id=loc,estimate_date=CUT if future else max(START,d-timedelta(days=4)),estimate_type='unconverted',parent_estimate_id='',quoted_net_usd='485.00',quoted_tax_usd='13.00',quoted_total_usd='498.00',status='pending' if future else 'declined',expires_date=d+timedelta(days=7))
            emit('shop/estimate_lines',estimate_line_id=uid('ESTL'),estimate_id=es,ro_line_id='',estimate_date=CUT if future else max(START,d-timedelta(days=4)),line_type='labor',quantity='2.000',unit_price_usd='142.50',gross_usd='285.00',discount_usd='0.00',net_usd='285.00',tax_usd='0.00',total_usd='285.00')
            emit('shop/estimate_lines',estimate_line_id=uid('ESTL'),estimate_id=es,ro_line_id='',estimate_date=CUT if future else max(START,d-timedelta(days=4)),line_type='parts',quantity='1.000',unit_price_usd='200.00',gross_usd='200.00',discount_usd='0.00',net_usd='200.00',tax_usd='13.00',total_usd='213.00')
            emit('shop/approvals',approval_id=uid('APPROVE'),estimate_id=es,ro_id='',decision='pending' if future else 'declined',decision_date='' if future else d,approved_total_usd='0.00',approval_method='not_approved')
    actual=defaultdict(int)
    for eid,st,en,mins,ro,jid,loc in SEGMENTS:actual[(eid,st.date())]+=mins
    for (eid,d),avail in sorted(AVAIL.items()):
        e=EMP[eid];work=actual[(eid,d)]
        emit('schedule/daily_capacity',capacity_id=uid('CAP'),work_date=d,location_id=e['loc'],employee_id=eid,bay_id=e['bay'],bay_open_minutes=max(480 if d.weekday()<5 else 240,avail),technician_available_minutes=avail,actual_work_minutes=work,idle_technician_minutes=avail-work,paid_attendance_minutes=ATTEND[(eid,d)][2],new_hire_ramp=str((d-e['hire']).days<120))

def add_pending_work():
    for li in range(1,4):
        loc=f'LOC-{li:02d}';eid=f'EMP-{li}-T6';bay=f'{loc}-B6';d=date(2026,10,28);planned=date(2026,11,16)
        roid=uid('RO');job=uid('JOB');est=uid('EST');ap=uid('APPT');cid=f'CUST-{4100+li:06d}';vid=cid.replace('CUST','VEH');rateid,rate=rate_for(loc,d,False)
        lines=[];book=8.0
        for typ,sku,q,unitprice in [('labor','',8000,rate),('parts','TIMING-SO',1000,roundi(SKUS['TIMING-SO']['cost']*2.12)),('parts','SEAL',1000,roundi(SKUS['SEAL']['cost']*2.12)),('parts','OIL',5500,roundi(SKUS['OIL']['cost']*2.12)),('fee','',1000,3900)]:
            gross=roundi(q*unitprice/1000);tax=roundi(gross*.065) if typ=='parts' else 0
            line=emit('shop/ro_lines',ro_line_id=uid('ROL'),ro_id=roid,job_id=job,opened_date=d,line_type=typ,sku=sku,quantity=qty(q),unit='hour' if typ=='labor' else SKUS[sku]['unit'] if sku else 'each',unit_price_usd=money(unitprice),gross_usd=money(gross),discount_usd='0.00',net_usd=money(gross),tax_usd=money(tax),total_usd=money(gross+tax),book_hours='8.00' if typ=='labor' else '0.00',labor_rate_id=rateid if typ=='labor' else '',is_customer_charge='True');lines.append(line)
        net=sum(cents(l['net_usd']) for l in lines);tax=sum(cents(l['tax_usd']) for l in lines);total=net+tax
        emit('shop/estimates',estimate_id=est,ro_id=roid,customer_id=cid,location_id=loc,estimate_date=d,estimate_type='initial',parent_estimate_id='',quoted_net_usd=money(net),quoted_tax_usd=money(tax),quoted_total_usd=money(total),status='approved',expires_date='2026-11-18')
        for l in lines:emit('shop/estimate_lines',estimate_line_id=uid('ESTL'),estimate_id=est,ro_line_id=l['ro_line_id'],estimate_date=d,line_type=l['line_type'],quantity=l['quantity'],unit_price_usd=l['unit_price_usd'],gross_usd=l['gross_usd'],discount_usd=l['discount_usd'],net_usd=l['net_usd'],tax_usd=l['tax_usd'],total_usd=l['total_usd'])
        emit('shop/approvals',approval_id=uid('APPROVE'),estimate_id=est,ro_id=roid,decision='approved',decision_date=d,approved_total_usd=money(total),approval_method='synthetic_sms')
        rr=emit('shop/repair_orders',ro_id=roid,location_id=loc,customer_id=cid,vehicle_id=vid,fleet_account_id='',appointment_id=ap,initial_estimate_id=est,opened_date=d,approved_date=d,actual_completion_date='',actual_delivery_date='',actual_invoice_date='',expected_delivery_date='2026-11-17',status='awaiting_parts',is_warranty='False',original_ro_id='',approved_net_usd=money(net),approved_tax_usd=money(tax),approved_total_usd=money(total),invoice_id='',odometer_miles=98000)
        emit('shop/jobs',job_id=job,ro_id=roid,opened_date=d,service_id='TIMING',employee_id=eid,bay_id=bay,rate_id=rateid,labor_rate_usd=money(rate),book_billed_hours='8.00',approved_actual_minutes=0,remaining_planned_minutes=480,status='awaiting_parts',actual_completion_date='')
        emit('schedule/appointments',appointment_id=ap,location_id=loc,customer_id=cid,vehicle_id=vid,ro_id=roid,booked_date=d,scheduled_date=planned,scheduled_start=f'{planned}T08:00:00',status='booked',actual_dropoff_at='',actual_pickup_at='',cancelled_date='',source_channel='referral')
        for h1,h2 in [(8,12),(13,17)]:emit('schedule/job_segments',segment_id=uid('SEG'),job_id=job,ro_id=roid,employee_id=eid,bay_id=bay,location_id=loc,work_date=planned,booked_start_at=f'{planned}T{h1:02d}:00:00',booked_end_at=f'{planned}T{h2:02d}:00:00',actual_start_at='',actual_end_at='',approved_clock_minutes=0,approval_status='planned_not_actual',attendance_id='')
        for stt in ['opened','approved','awaiting_parts']:emit('shop/status_events',status_event_id=uid('STATUS'),ro_id=roid,event_date=d,status=stt)
        ROS[roid]={'id':roid,'job':job,'loc':loc,'employee':eid,'customer':cid,'vehicle':vid,'fleet':'','date':d,'completion':None,'delivered':None,'warranty':False,'original':'','service':'TIMING','parts':{'TIMING-SO':1000,'SEAL':1000,'OIL':5500},'lines':lines,'net':net,'tax':tax,'total':total,'book':book,'sublet':False,'raw':rr,'parts_cost':0,'pending_parts':True}
        for sku,q in ROS[roid]['parts'].items():emit('inventory/reservations',reservation_id=uid('RES'),ro_id=roid,location_id=loc,sku=sku,reserved_date=d,reserved_base_quantity=qty(q),issued_base_quantity='0.000',released_base_quantity='0.000',open_reserved_base_quantity=qty(q),actual_issue_date='',status='awaiting_receipt' if sku=='TIMING-SO' else 'reserved_available',physical_stock_effect='No issue/install actual at cutoff; reservation only')
    # A declined additional recommendation is retained, excluded from approved RO amounts.
    for ro in list(ROS.values())[::175]:
        if ro['warranty']:continue
        est=uid('EST');d=ro['date']
        emit('shop/estimates',estimate_id=est,ro_id=ro['id'],customer_id=ro['customer'],location_id=ro['loc'],estimate_date=d,estimate_type='declined_recommendation_delta',parent_estimate_id=ro['raw']['initial_estimate_id'],quoted_net_usd='295.00',quoted_tax_usd='6.18',quoted_total_usd='301.18',status='declined',expires_date=d+timedelta(days=14))
        for typ,q,p,tax in [('labor','1.000','200.00','0.00'),('parts','1.000','95.00','6.18')]:emit('shop/estimate_lines',estimate_line_id=uid('ESTL'),estimate_id=est,ro_line_id='',estimate_date=d,line_type=typ,quantity=q,unit_price_usd=p,gross_usd=p,discount_usd='0.00',net_usd=p,tax_usd=tax,total_usd=money(cents(p)+cents(tax)))
        emit('shop/approvals',approval_id=uid('APPROVE'),estimate_id=est,ro_id=ro['id'],decision='declined',decision_date=d,approved_total_usd='0.00',approval_method='synthetic_customer_decline')

def vehicle_history():
    rng=random.Random(870144);vmap={r['vehicle_id']:r for r in T['shop/vehicles']};cmap={r['customer_id']:r for r in T['shop/customers']}
    apmap={r['ro_id']:r for r in T['schedule/appointments'] if r['ro_id']};byro=defaultdict(list)
    for e,st,en,mi,ro,j,loc in SEGMENTS:byro[ro].append((st,en))
    for ro in ROS.values():
        if ro.get('pending_parts'):continue
        ap=apmap[ro['id']];last=max(e for s,e in byro[ro['id']])
        if ro['delivered']:
            pickup=max(datetime.combine(ro['delivered'],datetime.min.time()).replace(hour=17,minute=30),last+timedelta(minutes=15));ap['actual_pickup_at']=str(pickup.isoformat())
    available=defaultdict(lambda:datetime(2020,1,1));odo={v: int(r['opening_odometer_miles']) for v,r in vmap.items()};seen={}
    ordered=sorted(ROS.values(),key=lambda r:(datetime.fromisoformat(apmap[r['id']]['actual_dropoff_at']) if apmap[r['id']]['actual_dropoff_at'] else datetime(2026,11,16,7,45),r['id']))
    completed=[]
    for ro in ordered:
        ap=apmap[ro['id']];start=datetime.fromisoformat(ap['actual_dropoff_at']) if ap['actual_dropoff_at'] else datetime(2026,11,16,7,45)
        if ro['warranty']:
            orig=ROS[ro['original']]
            if available[orig['vehicle']]>start:
                choices=[v for v in completed if v['loc']==ro['loc'] and v['service']==ro['service'] and not v['warranty'] and v['delivered'] and v['delivered']<ro['date'] and (ro['date']-v['delivered']).days<=75 and available[v['vehicle']]<=start]
                assert choices,('No available warranty original',ro['id'])
                orig=rng.choice(choices);ro['original']=orig['id'];ro['raw']['original_ro_id']=orig['id']
            vid=orig['vehicle'];cid=orig['customer'];fid=orig['fleet']
        elif ro['fleet']:
            fid=ro['fleet'];num=int(fid[-3:]);cid=f'FLEET-CUST-{num:03d}';choices=[f'VEH-F{num:03d}-{k:02d}' for k in range(1,11) if available[f'VEH-F{num:03d}-{k:02d}']<=start]
            if not choices:
                choices=[v for v,r in vmap.items() if r['customer_id'].startswith('FLEET-CUST') and available[v]<=start]
            vid=rng.choice(choices);cid=vmap[vid]['customer_id'];fid='FLEET-'+cid[-3:]
        else:
            choices=None;vid=ro['vehicle'];cid=ro['customer'];fid=''
            if available[vid]>start:
                choices=[v for v,r in vmap.items() if r['customer_id'].startswith('CUST-') and available[v]<=start]
                vid=rng.choice(choices);cid=vmap[vid]['customer_id']
        ro.update(customer=cid,vehicle=vid,fleet=fid);ro['raw'].update(customer_id=cid,vehicle_id=vid,fleet_account_id=fid)
        ap.update(customer_id=cid,vehicle_id=vid,source_channel='fleet' if fid else cmap[cid]['acquisition_source'])
        if not ro.get('pending_parts'):
            elapsed=max(1,(start.date()-seen.get(vid,date(2024,1,1))).days);odo[vid]+=elapsed*(95 if fid else 29)+rng.randint(20,180);seen[vid]=start.date();ro['raw']['odometer_miles']=str(odo[vid])
            available[vid]=datetime.fromisoformat(ap['actual_pickup_at']) if ap['actual_pickup_at'] else datetime(2026,11,1)
        else:ro['raw']['odometer_miles']=''
        completed.append(ro)
    for es in T['shop/estimates']:
        if es['ro_id']:es['customer_id']=ROS[es['ro_id']]['customer']
    # A free comeback may be reassigned to a different original to preserve vehicle
    # availability. Refresh its reference menu rate for that customer's fleet status.
    for job in T['shop/jobs']:
        ro=ROS[job['ro_id']]
        if ro['warranty']:
            rateid,rate=rate_for(ro['loc'],ro['date'],bool(ro['fleet']))
            job.update(rate_id=rateid,labor_rate_usd=money(rate))
            for line in ro['lines']:
                if line['line_type']=='labor':line.update(labor_rate_id=rateid,unit_price_usd=money(rate))
    line_map={r['ro_line_id']:r for r in T['shop/ro_lines']}
    for line in T['shop/estimate_lines']:
        if line['ro_line_id']:line['unit_price_usd']=line_map[line['ro_line_id']]['unit_price_usd']
    for cb in T['warranty/comebacks']:cb['original_ro_id']=ROS[cb['corrective_ro_id']]['original']

def bay_calendar():
    worked=defaultdict(int);occupied=defaultdict(int)
    for eid,st,en,mins,ro,jid,loc in SEGMENTS:worked[(EMP[eid]['bay'],st.date())]+=mins
    for occ in T['schedule/bay_occupancy']:
        begin=datetime.fromisoformat(occ['actual_occupied_from']);end=datetime.fromisoformat(occ['actual_released_at']) if occ['actual_released_at'] else datetime.combine(CUT,datetime.max.time())
        for d in days(begin.date(),min(CUT,end.date())):
            windows=shop_windows(d)
            for st,en in windows:occupied[(occ['bay_id'],d)]+=max(0,roundi((min(end,en)-max(begin,st)).total_seconds()/60))
    for b in T['shop/bays']:
        for d in days(START,CUT):
            windows=shop_windows(d);minutes=sum(roundi((en-st).total_seconds()/60) for st,en in windows)
            emit('schedule/bay_calendar',bay_calendar_id=f'BAYDAY-{b["bay_id"]}-{d}',bay_id=b['bay_id'],location_id=b['location_id'],work_date=d,bay_open_minutes=minutes,actual_productive_minutes=worked[(b['bay_id'],d)],occupied_open_minutes=occupied[(b['bay_id'],d)],idle_open_minutes=minutes-occupied[(b['bay_id'],d)],calendar_policy='Weekdays 08-12 and 13-17; scheduled Thu OT17-18; selected Sat08-12; no federal holiday calendar')

def shop_windows(d):
    if d.weekday()==6 or (d.weekday()==5 and not 8<=d.day<=14):return []
    start=datetime.combine(d,datetime.min.time()).replace(hour=8)
    if d.weekday()==5:return [(start,start.replace(hour=12))]
    return [(start,start.replace(hour=12)),(start.replace(hour=13),start.replace(hour=18 if d.weekday()==3 and d.day%2==0 else 17))]

def term_for(supplier,d):
    return [r for r in T['purchasing/terms_history'] if r['supplier_id']==supplier and r['effective_from']<=str(d)][-1]

def bill(d,loc,vendor,amount,acct,typ,ref,po='',due=None,contract='',ro=''):
    bid=uid('BILL');due=due or biz(d+timedelta(days=30))
    rr=emit('accounting/bills',bill_id=bid,vendor_id=vendor,location_id=loc,bill_date=d,service_period=d.strftime('%Y-%m'),due_date=due,bill_type=typ,source_id=ref,po_id=po,ro_id=ro,contract_id=contract,net_usd=money(amount),tax_usd='0.00',total_usd=money(amount),open_amount_usd='',status='')
    emit('accounting/bill_lines',bill_line_id=uid('BILLL'),bill_id=bid,account_code=acct,description=typ,net_usd=money(amount),tax_usd='0.00',total_usd=money(amount),ro_id=ro)
    BILLS[bid]={'id':bid,'date':d,'loc':loc,'vendor':vendor,'amt':amount,'due':due,'credits':0,'paid':0,'po':po,'ref':ref,'type':typ,'row':rr,'ro':ro,'contract':contract}
    post(d,loc,'accounting','vendor_bill',bid,[(acct,amount),('2000',-amount)],f'{typ}; {ref}')
    return bid

def vendor_credit(d,loc,supplier,amount,acct,typ,ref,billid,ro=''):
    cid=uid('VC')
    emit('accounting/vendor_credits',vendor_credit_id=cid,vendor_id=supplier,location_id=loc,credit_date=d,bill_id=billid,source_type=typ,source_id=ref,ro_id=ro,amount_usd=money(amount),offset_account_code=acct)
    post(d,loc,'accounting','vendor_credit',cid,[('2000',amount),(acct,-amount)],typ)
    BILLS[billid]['credits']+=amount
    emit('accounting/ap_allocations',ap_allocation_id=uid('APA'),bill_id=billid,allocation_date=d,allocation_type='vendor_credit',vendor_payment_id='',vendor_credit_id=cid,amount_usd=money(amount))
    return cid

def move(d,loc,sku,q,v,typ,ref,ro='',lot='',counter='',otherloc=''):
    INV[(loc,sku)][0]+=q;INV[(loc,sku)][1]+=v
    assert INV[(loc,sku)][0]>=0 and INV[(loc,sku)][1]>=0,(loc,sku,d,typ)
    return emit('inventory/movements',movement_id=uid('MOV'),event_sequence=COUNTS['MOV'],movement_date=d,location_id=loc,sku=sku,movement_type=typ,quantity_delta=qty(q),base_unit=SKUS[sku]['unit'],carrying_value_delta_usd=money(v),source_id=ref,ro_id=ro,lot_id=lot,paired_movement_id=counter,other_location_id=otherloc)

def take(loc,sku,q,onlylot=''):
    remaining=q;cost=0
    for lot in LOTS[(loc,sku)]:
        if onlylot and lot['id']!=onlylot:continue
        n=min(remaining,lot['q'])
        if n<=0:continue
        val=lot['v'] if n==lot['q'] else roundi(lot['v']*n/lot['q'])
        lot['q']-=n;lot['v']-=val;remaining-=n;cost+=val
        if not remaining:break
    assert remaining==0,(loc,sku,q,onlylot)
    return cost

def acquire(d,loc,sku,q,why='reorder'):
    s=SKUS[sku];pack=s['pack'];packs=max(1,(q+pack*1000-1)//(pack*1000));q=packs*pack*1000
    podate=max(START,d-timedelta(days=14 if sku in ['STRUT','TIMING','PUMP'] else 4))
    priceid,unit=price_for(sku,podate);val=roundi(unit*q/1000)
    po=uid('PO');pl=uid('POL');rec=uid('RECEIPT');term=term_for(s['supplier'],podate)
    eta=d-timedelta(days=3) if d>=date(2026,8,1) and sku in ['STRUT','TIMING','PUMP'] else d
    emit('purchasing/purchase_orders',po_id=po,location_id=loc,supplier_id=s['supplier'],terms_id=term['terms_id'],ordered_date=podate,expected_receipt_date=eta,actual_closed_date=d,status='received',total_ordered_usd=money(val),open_commitment_usd='0.00',delay_reason='special_order_backlog' if eta<d else '',ro_id='',currency='USD')
    emit('purchasing/po_lines',po_line_id=pl,po_id=po,sku=sku,purchase_quantity=f'{packs}.000',purchase_unit='case' if pack>1 else 'each',base_units_per_purchase_unit=f'{pack}.000',ordered_base_quantity=qty(q),received_base_quantity=qty(q),open_base_quantity='0.000',purchase_unit_cost_usd=money(unit*pack),base_unit_cost_usd=money(unit),line_total_usd=money(val),price_id=priceid)
    bid=bill(d,loc,s['supplier'],val,'1200','parts_receipt',rec,po,biz(d+timedelta(days=int(term['net_days']))))
    emit('purchasing/receipts',receipt_id=rec,po_id=po,po_line_id=pl,location_id=loc,sku=sku,receipt_date=d,received_purchase_quantity=f'{packs}.000',received_base_quantity=qty(q),landed_value_usd=money(val),bill_id=bid,lot_id=rec,inspection_status='accepted')
    LOTS[(loc,sku)].append({'id':rec,'q':q,'v':val,'bill':bid})
    move(d,loc,sku,q,val,'receipt',rec,lot=rec)
    return rec,bid

def inventory():
    targets={'OIL':450000,'FILTER':90000,'BRAKE':45000,'ROTOR':100000,'BRAKEFLUID':30000,'TIRE':120000,'COOLANT':160000,'PUMP':22000,'BATTERY':40000,'AIR':40000,'CABIN':40000,'STRUT':35000,'BOLT':25000,'TIMING':8000,'SEAL':10000,'SENSOR':40000,'TIMING-SO':0}
    for loc in ['LOC-01','LOC-02','LOC-03']:
        for sku,s in SKUS.items():
            q=targets[sku];v=roundi(s['cost']*q/1000);oid=f'OPEN-{loc}-{sku}'
            INV[(loc,sku)]=[q,v];LOTS[(loc,sku)]=[{'id':oid,'q':q,'v':v,'bill':''}]
            opening(loc,'1200',v)
            emit('inventory/opening_stock',opening_stock_id=oid,location_id=loc,sku=sku,as_of_date=START-timedelta(days=1),base_quantity=qty(q),carrying_value_usd=money(v),lot_id=oid,unit_cost_usd=money(s['cost']),fully_paid_before_window='True')
    queue=[];qseq=0
    def event(d,p,typ,ref):
        nonlocal qseq
        if d<=CUT: qseq+=1;heapq.heappush(queue,(d,p,qseq,typ,ref))
    for ro in ROS.values():
        if not ro.get('pending_parts'):event(ro['date'],2,'issue',ro['id'])
        if ro['sublet'] and ro['completion']:event(ro['completion'],4,'sublet',ro['id'])
        if ro['delivered']:event(ro['delivered'],8,'deliver',ro['id'])
    for m in MONTHS:
        event(biz(m.replace(day=12)),0,'transfer',None)
        event(biz(m.replace(day=22)),1,'count',None)
    purchasecount=0
    while queue:
        d,p,seq,typ,ref=heapq.heappop(queue)
        if typ=='issue':
            ro=ROS[ref];cost=0
            for sku,q in ro['parts'].items():
                if INV[(ro['loc'],sku)][0] < q + targets[sku]//5:
                    rec,bid=acquire(d,ro['loc'],sku,targets[sku]-INV[(ro['loc'],sku)][0]+q)
                    purchasecount+=1
                    if purchasecount%17==0:event(biz(d+timedelta(days=3)),1,'return',(ro['loc'],sku,rec,bid))
                val=take(ro['loc'],sku,q);move(d,ro['loc'],sku,-q,-val,'issue_to_wip',ro['id'],ro=ro['id'])
                cost+=val
                emit('inventory/reservations',reservation_id=uid('RES'),ro_id=ro['id'],location_id=ro['loc'],sku=sku,reserved_date=max(START,d-timedelta(days=1)),reserved_base_quantity=qty(q),issued_base_quantity=qty(q),released_base_quantity='0.000',open_reserved_base_quantity='0.000',actual_issue_date=d,status='issued',physical_stock_effect='Only linked issue movement changes inventory')
            ro['parts_cost']=cost;WIP[ref]+=cost
            post(d,ro['loc'],'inventory','ro_parts_issue',ref,[('1210',cost),('1200',-cost)],'Parts capitalized in open RO WIP')
        elif typ=='sublet':
            ro=ROS[ref];amount=8200;sub=uid('SUBLET')
            bid=bill(d,ro['loc'],'VEN-ALIGN',amount,'1210','outsourced_alignment',sub,due=biz(d+timedelta(days=21)),ro=ref)
            emit('operating/sublet_services',sublet_id=sub,ro_id=ref,job_id=ro['job'],vendor_id='VEN-ALIGN',location_id=ro['loc'],actual_service_date=d,description='Outsourced wheel alignment',cost_usd=money(amount),customer_sale_usd='115.00',bill_id=bid)
            ro['sublet_cost']=amount;WIP[ref]+=amount
        elif typ=='deliver':
            ro=ROS[ref];pc=ro['parts_cost'];sc=ro.get('sublet_cost',0)
            post(d,ro['loc'],'inventory','delivered_ro_cost',ref,[('5110' if ro['warranty'] else '5100',pc),('5200',sc),('1210',-pc-sc)],'Release delivered WIP; no additional payroll expense')
            WIP[ref]-=pc+sc
        elif typ=='return':
            loc,sku,lot,bid=ref
            lo=next(x for x in LOTS[(loc,sku)] if x['id']==lot)
            q=min(1000,lo['q'])
            if not q:continue
            val=take(loc,sku,q,lot);rid=uid('SUPRET');move(d,loc,sku,-q,-val,'supplier_return',rid,lot=lot)
            vc=vendor_credit(d,loc,SKUS[sku]['supplier'],val,'1200','supplier_return',rid,bid)
            emit('purchasing/supplier_returns',supplier_return_id=rid,supplier_id=SKUS[sku]['supplier'],location_id=loc,sku=sku,original_receipt_id=lot,original_bill_id=bid,return_date=d,returned_base_quantity=qty(q),original_cost_usd=money(val),vendor_credit_id=vc,reason='unopened_excess_return')
        elif typ=='transfer':
            sku='FILTER';fromloc='LOC-01';toloc='LOC-02';q=4000
            if INV[(fromloc,sku)][0]<q:continue
            val=take(fromloc,sku,q);tid=uid('TRF')
            out=move(d,fromloc,sku,-q,-val,'transfer_out',tid,otherloc=toloc)
            LOTS[(toloc,sku)].append({'id':tid,'q':q,'v':val,'bill':''})
            inc=move(d,toloc,sku,q,val,'transfer_in',tid,lot=tid,counter=out['movement_id'],otherloc=fromloc);out['paired_movement_id']=inc['movement_id']
            emit('inventory/transfers',transfer_id=tid,transfer_date=d,from_location_id=fromloc,to_location_id=toloc,sku=sku,base_quantity=qty(q),carrying_value_usd=money(val),out_movement_id=out['movement_id'],in_movement_id=inc['movement_id'])
            post(d,fromloc,'inventory','transfer_out',tid,[('1300',val),('1200',-val)])
            post(d,toloc,'inventory','transfer_in',tid,[('1200',val),('1300',-val)])
        elif typ=='count':
            for loc in ['LOC-01','LOC-02','LOC-03']:
                sku=R.choice(['FILTER','AIR','CABIN','OIL']);q=1000 if sku!='OIL' else 500
                before=INV[(loc,sku)][0]
                if before<q:continue
                val=take(loc,sku,q);cid=uid('COUNT');mv=move(d,loc,sku,-q,-val,'damage_or_shrink',cid)
                emit('inventory/cycle_counts',count_id=cid,location_id=loc,sku=sku,count_date=d,book_quantity_before=qty(before),counted_usable_quantity=qty(before-q),adjustment_quantity=qty(-q),writeoff_value_usd=money(val),reason='damaged_packaging' if sku!='OIL' else 'oil_handling_loss',movement_id=mv['movement_id'])
                post(d,loc,'inventory','inventory_writeoff',cid,[('5130',val),('1200',-val)])
    # Open special-order commitments deliberately remain unreceived and unexpensed.
    for loc in ['LOC-01','LOC-02','LOC-03']:
        pending=next(r for r in ROS.values() if r['loc']==loc and r.get('pending_parts'))
        for k in range(5):
            sku=['STRUT','TIMING-SO','PUMP','TIRE','TIMING'][k];s=SKUS[sku];q=(1 if k==1 else 2 if sku!='TIRE' else 8)*1000;pi,unit=price_for(sku,CUT);v=roundi(unit*q/1000);po=uid('PO');pl=uid('POL');term=term_for(s['supplier'],CUT)
            ro=pending['id'] if k==1 else ''
            emit('purchasing/purchase_orders',po_id=po,location_id=loc,supplier_id=s['supplier'],terms_id=term['terms_id'],ordered_date='2026-10-22',expected_receipt_date='2026-11-06' if k%2 else '2026-11-13',actual_closed_date='',status='open_delayed',total_ordered_usd=money(v),open_commitment_usd=money(v),delay_reason='supplier_special_order_backlog',ro_id=ro,currency='USD')
            emit('purchasing/po_lines',po_line_id=pl,po_id=po,sku=sku,purchase_quantity=qty(q),purchase_unit='each',base_units_per_purchase_unit='1.000',ordered_base_quantity=qty(q),received_base_quantity='0.000',open_base_quantity=qty(q),purchase_unit_cost_usd=money(unit),base_unit_cost_usd=money(unit),line_total_usd=money(v),price_id=pi)
    # End-of-month inventory from physical movements, independently verified later.
    mov=sorted(T['inventory/movements'],key=lambda r:(r['movement_date'],int(r['event_sequence'])))
    running={(r['location_id'],r['sku']):[roundi(Decimal(r['base_quantity'])*1000),cents(r['carrying_value_usd'])] for r in T['inventory/opening_stock']}
    ix=0
    for m in MONTHS:
        end=monthend(m)
        while ix<len(mov) and mov[ix]['movement_date']<=str(end):
            r=mov[ix];a=running[(r['location_id'],r['sku'])];a[0]+=roundi(Decimal(r['quantity_delta'])*1000);a[1]+=cents(r['carrying_value_delta_usd']);ix+=1
        for (loc,sku),(q,v) in sorted(running.items()):emit('inventory/month_end_balances',balance_id=f'INV-{m:%Y%m}-{loc}-{sku}',month=f'{m:%Y-%m}',as_of_date=end,location_id=loc,sku=sku,base_quantity=qty(q),carrying_value_usd=money(v),base_unit=SKUS[sku]['unit'])
        for ro in ROS.values():
            if ro['date']<=end and (not ro['delivered'] or ro['delivered']>end):
                pc=ro['parts_cost'];sc=ro.get('sublet_cost',0) if ro['completion'] and ro['completion']<=end else 0
                emit('inventory/wip_balances',wip_balance_id=f'WIP-{m:%Y%m}-{ro["id"]}',month=f'{m:%Y-%m}',location_id=ro['loc'],ro_id=ro['id'],issued_parts_value_usd=money(pc),outsourced_service_value_usd=money(sc),labor_capitalized_usd='0.00',total_wip_usd=money(pc+sc),recognition_status='not_delivered',reservation_excluded='True')
    # Operational issue/install/release states are a bridge, not duplicate inventory events.
    issued={}
    for mv in T['inventory/movements']:
        if mv['movement_type']=='issue_to_wip':issued[(mv['ro_id'],mv['sku'])]=mv
    for ro in ROS.values():
        for sku,q in ro['parts'].items():
            mv=issued.get((ro['id'],sku))
            emit('inventory/ro_parts_usage',part_usage_id=uid('USAGE'),ro_id=ro['id'],job_id=ro['job'],location_id=ro['loc'],sku=sku,required_base_quantity=qty(q),issued_base_quantity=qty(q if mv else 0),installed_base_quantity=qty(q if mv and ro['completion'] else 0),reserved_not_issued_quantity=qty(q if not mv else 0),actual_issue_date=ro['date'] if mv else '',actual_install_date=ro['completion'] if mv else '',actual_wip_release_date=ro['delivered'],issue_movement_id=mv['movement_id'] if mv else '',issued_carrying_cost_usd=money(-cents(mv['carrying_value_delta_usd'])) if mv else '0.00',accounting_policy='Installed or issued remains WIP until actual vehicle delivery; labor expensed as earned')
    for cb in T['warranty/comebacks']:cb['corrective_parts_cost_usd']=money(ROS[cb['corrective_ro_id']]['parts_cost'])
    for cb in T['warranty/comebacks']:
        ro=ROS[cb['corrective_ro_id']]
        if not ro['delivered'] or cb['reason']!='supplier_part_failure':continue
        recoverydate=biz(ro['delivered']+timedelta(days=14))
        if recoverydate>CUT:continue
        sku=next(iter(ro['parts']));supplier=SKUS[sku]['supplier']
        candidates=[b for b in BILLS.values() if b['vendor']==supplier and b['loc']==ro['loc'] and b['date']<=recoverydate and b['amt']-b['credits']>ro['parts_cost']//2]
        if not candidates:continue
        bid=candidates[-1]['id'];v=roundi(ro['parts_cost']*.55);rec=uid('RECOVERY');vc=vendor_credit(recoverydate,ro['loc'],supplier,v,'5120','warranty_recovery',rec,bid,ro['id'])
        emit('warranty/supplier_recoveries',recovery_id=rec,comeback_id=cb['comeback_id'],corrective_ro_id=ro['id'],original_ro_id=ro['original'],supplier_id=supplier,recovery_date=recoverydate,amount_usd=money(v),vendor_credit_id=vc,inventory_restock='False',policy='Supplier contribution reduces warranty expense; no fictitious customer revenue')
        cb['supplier_recovery_id']=rec

PAYMENTS={}; INVOICES={}; DEPOSITS={}
def customer_payment(d,loc,cid,roid,amount,tender,purpose,invoice='',deposit='',original=''):
    pid=uid('PAY');amount=int(amount)
    rr=emit('billing/payments',payment_id=pid,customer_id=cid,location_id=loc,ro_id=roid,payment_date=d,payment_type='refund' if amount<0 else 'receipt',tender_type=tender,purpose=purpose,amount_usd=money(amount),invoice_id=invoice,deposit_id=deposit,original_payment_id=original,processor_balance_transaction_id='',bank_transaction_id='')
    clear='1010' if tender=='card' else '1020'
    offset='2200' if purpose=='deposit_receipt' else '1100'
    post(d,loc,'billing','customer_payment',pid,[(clear,amount),(offset,-amount)],purpose)
    if invoice:
        emit('billing/payment_allocations',allocation_id=uid('ALLOC'),invoice_id=invoice,allocation_date=d,payment_id=pid,deposit_id='',allocation_type='refund' if amount<0 else 'cash_receipt',amount_usd=money(amount))
        INVOICES[invoice]['allocated']+=amount
    PAYMENTS[pid]={'row':rr,'d':d,'loc':loc,'amt':amount,'tender':tender,'purpose':purpose}
    return pid

def billing():
    for ro in sorted(ROS.values(),key=lambda r:(r['date'],r['id'])):
        d=ro['date'];loc=ro['loc'];dep=0;depid=''
        if not ro['warranty'] and not ro['fleet'] and ro['service'] in ['SUSP','TIMING','COOLING'] and (R.random()<.4 or not ro['delivered']):
            dep=roundi(ro['total']*.30);depid=uid('DEP');dd=max(START,biz(d-timedelta(days=4)))
            pid=customer_payment(dd,loc,ro['customer'],ro['id'],dep,'card','deposit_receipt',deposit=depid)
            row=emit('billing/deposits',deposit_id=depid,ro_id=ro['id'],customer_id=ro['customer'],location_id=loc,received_date=dd,received_amount_usd=money(dep),payment_id=pid,applied_date=ro['delivered'],applied_invoice_id='',applied_amount_usd=money(dep if ro['delivered'] else 0),unapplied_amount_usd=money(0 if ro['delivered'] else dep),policy='Liability until delivered invoice; not revenue at receipt')
            emit('billing/deposit_events',deposit_event_id=uid('DEPE'),deposit_id=depid,event_date=dd,event_type='receipt',liability_delta_usd=money(dep),invoice_id='',payment_id=pid)
            DEPOSITS[depid]={'row':row,'loc':loc,'amt':dep,'date':dd,'ro':ro['id']}
        if not ro['delivered'] or ro['warranty']:
            if ro['warranty']:ro['raw']['actual_invoice_date']=''
            continue
        inv=uid('INV');ivdate=ro['delivered'];fleet=bool(ro['fleet']);due=biz(ivdate+timedelta(days=30)) if fleet else ivdate
        rr=emit('billing/invoices',invoice_id=inv,ro_id=ro['id'],customer_id=ro['customer'],fleet_account_id=ro['fleet'],location_id=loc,invoice_date=ivdate,due_date=due,net_usd=money(ro['net']),tax_usd=money(ro['tax']),total_usd=money(ro['total']),credit_total_usd='0.00',allocated_total_usd='0.00',open_amount_usd='0.00',status='',currency='USD')
        INVOICES[inv]={'id':inv,'date':ivdate,'due':due,'ro':ro,'total':ro['total'],'credits':0,'allocated':0,'row':rr}
        ro['raw']['invoice_id']=inv
        ent=[('1100',ro['total'])]
        for l in ro['lines']:
            emit('billing/invoice_lines',invoice_line_id=uid('INVL'),invoice_id=inv,invoice_date=ivdate,ro_line_id=l['ro_line_id'],ro_id=ro['id'],line_type=l['line_type'],sku=l['sku'],quantity=l['quantity'],unit=l['unit'],unit_price_usd=l['unit_price_usd'],gross_usd=l['gross_usd'],discount_usd=l['discount_usd'],net_usd=l['net_usd'],tax_usd=l['tax_usd'],total_usd=l['total_usd'])
            a={'parts':'4010','labor':'4000','fee':'4020','sublet':'4030'}[l['line_type']]
            ent.append((a,-cents(l['net_usd'])))
        ent.append(('2100',-ro['tax']));post(ivdate,loc,'billing','customer_invoice',inv,ent,'Delivered customer service only')
        if dep:
            post(ivdate,loc,'billing','deposit_application',depid,[('2200',dep),('1100',-dep)])
            emit('billing/payment_allocations',allocation_id=uid('ALLOC'),invoice_id=inv,allocation_date=ivdate,payment_id='',deposit_id=depid,allocation_type='deposit_application',amount_usd=money(dep))
            emit('billing/deposit_events',deposit_event_id=uid('DEPE'),deposit_id=depid,event_date=ivdate,event_type='application',liability_delta_usd=money(-dep),invoice_id=inv,payment_id='')
            DEPOSITS[depid]['row']['applied_invoice_id']=inv;INVOICES[inv]['allocated']+=dep
        if fleet:
            account=next(f for f in T['shop/fleet_accounts'] if f['fleet_account_id']==ro['fleet'])
            a=roundi(ro['total']*.4);last=int(account['expected_days_after_invoice'])+(8 if ivdate>=date(2026,7,1) else 0)
            for lag,amt in [(25 if last<70 else 35,a),(last,ro['total']-a)]:
                pd=biz(ivdate+timedelta(days=lag))
                if pd<=CUT:customer_payment(pd,loc,ro['customer'],ro['id'],amt,'ACH','invoice_collection',inv)
        else:
            tender=R.choices(['card','cash','ACH'],[84,11,5])[0]
            pid=customer_payment(ivdate,loc,ro['customer'],ro['id'],ro['total']-dep,tender,'invoice_collection',inv)
            # Separate service concession, no part physically returned and no COGS reversal.
            if R.random()<.007:
                cd=biz(ivdate+timedelta(days=R.randint(2,12)))
                if cd<=CUT:
                    part=next((l for l in T['billing/invoice_lines'][-len(ro['lines']):] if l['line_type']=='parts'),None)
                    if part:
                        net=roundi(cents(part['net_usd'])*.18);tax=roundi(net*.065);ct=net+tax;cn=uid('CN')
                        emit('billing/credit_notes',credit_note_id=cn,invoice_id=inv,ro_id=ro['id'],location_id=loc,credit_date=cd,reason='service_goodwill_concession',net_usd=money(net),tax_usd=money(tax),total_usd=money(ct),restock='False',refund_payment_id='')
                        emit('billing/credit_lines',credit_line_id=uid('CNL'),credit_note_id=cn,invoice_line_id=part['invoice_line_id'],line_type='parts_concession',net_credit_usd=money(net),tax_credit_usd=money(tax),total_credit_usd=money(ct),inventory_effect='none')
                        post(cd,loc,'billing','customer_credit',cn,[('4090',net),('2100',tax),('1100',-ct)])
                        INVOICES[inv]['credits']+=ct
                        refund=customer_payment(cd,loc,ro['customer'],ro['id'],-ct,tender,'credit_refund',inv,original=pid)
                        T['billing/credit_notes'][-1]['refund_payment_id']=refund
    for inv,v in INVOICES.items():
        op=v['total']-v['credits']-v['allocated'];row=v['row'];row.update(credit_total_usd=money(v['credits']),allocated_total_usd=money(v['allocated']),open_amount_usd=money(op),status='paid' if op==0 else 'partial' if v['allocated'] else 'open')
        assert op>=0,(inv,op)
        if op:emit('billing/open_ar',invoice_id=inv,ro_id=v['ro']['id'],customer_id=v['ro']['customer'],fleet_account_id=v['ro']['fleet'],location_id=v['ro']['loc'],as_of_date=CUT,invoice_date=v['date'],due_date=v['due'],original_total_usd=money(v['total']),credits_usd=money(v['credits']),allocated_usd=money(v['allocated']),open_amount_usd=money(op),days_past_due=max(0,(CUT-v['due']).days),expected_collection_date=biz(max(CUT+timedelta(days=2),v['date']+timedelta(days=80 if v['date']>=date(2026,7,1) else 68))),collection_assumption='Expected cash timing, not future actual payment')
    for dep,v in DEPOSITS.items():
        if cents(v['row']['unapplied_amount_usd']):emit('billing/open_deposits',deposit_id=dep,ro_id=v['ro'],location_id=v['loc'],as_of_date=CUT,liability_usd=v['row']['unapplied_amount_usd'],expected_application_date=max(date.fromisoformat(ROS[v['ro']]['raw']['expected_delivery_date']),biz(CUT,4)))

def settlement():
    # Processor available date and payout bank arrival are distinct; never repeat sales.
    batches=defaultdict(list);cashbatches=defaultdict(list)
    for pid,p in sorted(PAYMENTS.items(),key=lambda x:(x[1]['d'],x[0])):
        d=p['d'];amount=p['amt'];loc=p['loc']
        if p['tender']=='card':
            fee=roundi(amount*.027)+25 if amount>0 else 0
            bt=uid('BT');avail=biz(d,2);payoutdate=biz(avail,1)
            row=emit('processor/balance_transactions',balance_transaction_id=bt,payment_id=pid,location_id=loc,transaction_date=d,available_date=avail,transaction_type='capture' if amount>0 else 'refund',gross_usd=money(amount),fee_usd=money(fee),net_usd=money(amount-fee),payout_id='',currency='USD')
            p['row']['processor_balance_transaction_id']=bt
            if fee:post(d,loc,'processor','processing_fee',bt,[('6500',fee),('1010',-fee)],'Synthetic 2.7% + $0.25 per capture; no extra refund fee')
            # Batch exists only after available funds are actually initiated, not future fact.
            if avail<=CUT:batches[(loc,avail,payoutdate)].append(row)
        else:
            bankdate=biz(d,1)
            if bankdate<=CUT:cashbatches[(loc,bankdate,p['tender'])].append((pid,p))
    for (loc,init,arr),rows in sorted(batches.items()):
        po=uid('PAYOUT');amt=sum(cents(r['net_usd']) for r in rows);bid=''
        if arr<=CUT:
            bid=bank(arr,loc,amt,'processor_payout',po,'Demo Card Processor')
            post(arr,loc,'processor','payout_bank',po,[('1000',amt),('1010',-amt)],'Card settlement; no new revenue')
        emit('processor/payouts',payout_id=po,location_id=loc,initiated_date=init,expected_bank_date=arr,actual_bank_date=arr if arr<=CUT else '',net_amount_usd=money(amt),status='paid' if arr<=CUT else 'in_transit',bank_transaction_id=bid)
        for r in rows:r['payout_id']=po
    for (loc,d,tender),rows in sorted(cashbatches.items()):
        ref=uid('TENDER-BATCH');amt=sum(p['amt'] for pid,p in rows);bid=bank(d,loc,amt,'cash_deposit' if tender=='cash' else 'customer_ACH_batch',ref,'Demo customer receipts')
        post(d,loc,'billing','noncard_bank_batch',ref,[('1000',amt),('1020',-amt)],tender)
        for pid,p in rows:p['row']['bank_transaction_id']=bid

def payroll():
    techclock=defaultdict(int);roclock=defaultdict(lambda:defaultdict(int))
    for (eid,d,ro),mins in JOB_MINS.items():techclock[(eid,periodkey(d))]+=mins;roclock[(eid,periodkey(d))][ro]+=mins
    for m in MONTHS:
        for half in [1,2]:
            begin=m if half==1 else m.replace(day=16);end=m.replace(day=15) if half==1 else monthend(m);fund=biz(end,2)
            for loc in ['LOC-01','LOC-02','LOC-03','HQ']:
                run=uid('PRUN');grossall=netall=taxall=benefitall=withheldall=0;ent=defaultdict(int)
                for eid,e in EMP.items():
                    if e['loc']!=loc or e['hire']>end:continue
                    at=[(d,v) for (ee,d),v in ATTEND.items() if ee==eid and begin<=d<=end]
                    if not at:continue
                    reg=sum(v[0] for d,v in at);ot=sum(v[1] for d,v in at);paid=reg+ot;presence=sum(v[3] for d,v in at)
                    comp=[r for r in T['payroll/compensation_history'] if r['employee_id']==eid and r['effective_from']<=str(end)][-1]
                    hr=cents(comp['hourly_rate_usd']);annual=cents(comp['annual_salary_usd'])
                    regular=roundi(annual/24) if annual else roundi(hr*reg/60)
                    overtime=0 if annual else roundi(hr*ot/60*1.5)
                    book=BOOK[(eid,(m.year,m.month,half))];bonus=roundi(max(0,book-70)*400) if e['role']=='technician' else 0
                    gross=regular+overtime+bonus;withheld=roundi(gross*.2);net=gross-withheld;tax=roundi(gross*.08);benefit=roundi(paid/60*220);empcost=gross+tax+benefit
                    er=emit('payroll/earnings',earning_id=uid('EARN'),payroll_run_id=run,employee_id=eid,location_id=loc,period_start=begin,period_end=end,compensation_id=comp['compensation_id'],regular_paid_minutes=reg,overtime_paid_minutes=ot,paid_minutes=paid,paid_presence_minutes=presence,approved_job_clock_minutes=techclock[(eid,(m.year,m.month,half))],delivered_book_hours=f'{book:.2f}',regular_gross_usd=money(regular),overtime_gross_usd=money(overtime),book_bonus_usd=money(bonus),gross_pay_usd=money(gross),employee_withholding_usd=money(withheld),net_pay_usd=money(net),employer_tax_usd=money(tax),employer_benefits_usd=money(benefit),total_employer_cost_usd=money(empcost))
                    if e['role']=='technician':
                        ent['5000']+=gross;ent['5010']+=tax;ent['5015']+=benefit
                        # Clock minutes / ALL paid minutes allocates only productive share.
                        byro=roclock[(eid,(m.year,m.month,half))];target=roundi(empcost*sum(byro.values())/paid) if paid else 0
                        remain=target
                        for n,(ro,mins) in enumerate(sorted(byro.items())):
                            alloc=remain if n==len(byro)-1 else roundi(empcost*mins/paid);remain-=alloc
                            emit('payroll/job_cost_allocations',labor_allocation_id=uid('LABALLOC'),earning_id=er['earning_id'],payroll_run_id=run,employee_id=eid,ro_id=ro,location_id=loc,allocation_month=f'{m:%Y-%m}',period_end=end,approved_job_clock_minutes=mins,paid_minutes_denominator=paid,allocated_actual_payroll_usd=money(alloc),posting_status='management_memo_only',allocation_basis='Actual RO clock / total approved paid minutes; unallocated cost is idle/PTO/training')
                    elif loc=='HQ':ent['6200']+=gross;ent['6210']+=tax+benefit
                    else:ent['6100']+=gross;ent['6110']+=tax+benefit
                    grossall+=gross;netall+=net;taxall+=tax;benefitall+=benefit;withheldall+=withheld
                total=grossall+taxall+benefitall;ent['2300']-=total
                post(end,loc,'payroll','payroll_earned',run,list(ent.items()),'Earned actual wages and employer burden; job allocation is not another expense')
                bid='';fundid=''
                if fund<=CUT:
                    fundid=uid('FUND');bid=bank(fund,loc,-total,'payroll_funding',fundid,'Demo Payroll Funding Service')
                    post(fund,loc,'payroll','payroll_funding',fundid,[('2300',total),('1000',-total)])
                    emit('payroll/funding',funding_id=fundid,payroll_run_id=run,location_id=loc,actual_funding_date=fund,net_pay_usd=money(netall),employee_withholding_remitted_usd=money(withheldall),employer_tax_remitted_usd=money(taxall),benefits_funded_usd=money(benefitall),total_funded_usd=money(total),bank_transaction_id=bid)
                emit('payroll/runs',payroll_run_id=run,location_id=loc,period_start=begin,period_end=end,earned_date=end,scheduled_funding_date=fund,actual_funding_date=fund if fund<=CUT else '',gross_pay_usd=money(grossall),net_pay_usd=money(netall),employee_withholding_usd=money(withheldall),employer_taxes_usd=money(taxall),employer_benefits_usd=money(benefitall),total_funding_usd=money(total),status='funded' if fund<=CUT else 'earned_unfunded',funding_id=fundid)

def operating():
    defs=[('RENT','Property landlord','6300',680000,1),('UTIL','Utilities provider','6310',110000,18),('INS','Business insurer','6320',92000,5),('SOFT','Shop software','6330',65000,8),('MAINT','Lift and tool maintenance','6340',52000,20),('WASTE','Disposal and cleaning','6350',38000,15)]
    for code,name,acct,amt,day in defs:emit('operating/vendors',vendor_id=f'VEN-{code}',vendor_name=f'Demo {name}',email=f'{code.lower()}@example.com',service_category=acct,net_days=15)
    emit('operating/vendors',vendor_id='VEN-ALIGN',vendor_name='Demo Alignment Outsource',email='alignment@example.com',service_category='outsourced_service',net_days=21)
    emit('operating/vendors',vendor_id='VEN-EQUIP',vendor_name='Demo Workshop Equipment',email='equipment@example.com',service_category='capital_equipment',net_days=30)
    for loc in ['LOC-01','LOC-02','LOC-03']:
        for code,name,acct,amt,day in defs:
            contract=f'CONTRACT-{loc}-{code}';base=amt+(35000 if loc=='LOC-02' and code=='RENT' else 0)
            currentbase=roundi(Decimal(base)*Decimal('1.03')) if code=='RENT' else base
            emit('operating/recurring_contracts',contract_id=contract,vendor_id=f'VEN-{code}',location_id=loc,expense_account_code=acct,effective_from='2024-01-01',effective_to='',as_of_date=CUT,opening_monthly_base_usd=money(base),monthly_base_usd=money(currentbase),first_escalation_date='2026-01-01' if code=='RENT' else '',billing_policy='service_month_end',payment_days_after_bill=15,next_service_month='2026-11',next_expected_due_date='2026-12-15',open_ap_overlap_key=contract,annual_increase_pct='3.00' if code=='RENT' else '0.00')
            for m in MONTHS:
                val=base
                if code=='RENT' and m>=date(2026,1,1):val=roundi(val*1.03)
                if code=='UTIL':val=roundi(base*({1:1.2,2:1.15,6:1.20,7:1.35,8:1.28,12:1.18}.get(m.month,1))*R.uniform(.93,1.07))
                if code=='MAINT' and loc=='LOC-03' and m>=date(2026,5,1):val+=35000
                bill(monthend(m),loc,f'VEN-{code}',val,acct,'recurring_service',f'{contract}-{m:%Y%m}',due=biz(monthend(m)+timedelta(days=15)),contract=contract)
    contract='CONTRACT-HQ-SOFT'
    emit('operating/recurring_contracts',contract_id=contract,vendor_id='VEN-SOFT',location_id='HQ',expense_account_code='6330',effective_from='2024-01-01',effective_to='',as_of_date=CUT,opening_monthly_base_usd='1450.00',monthly_base_usd='1450.00',first_escalation_date='',billing_policy='service_month_end',payment_days_after_bill=15,next_service_month='2026-11',next_expected_due_date='2026-12-15',open_ap_overlap_key=contract,annual_increase_pct='0.00')
    for m in MONTHS:bill(monthend(m),'HQ','VEN-SOFT',145000,'6330','recurring_service',f'{contract}-{m:%Y%m}',due=biz(monthend(m)+timedelta(days=15)),contract=contract)
    assets=[]
    for loc in ['LOC-01','LOC-02','LOC-03']:
        for kind,cost,acc in [('six_lifts',4800000,1066667),('tools',2400000,533333),('diagnostic_equipment',1800000,400000)]:
            aid=f'ASSET-{loc}-{kind}';assets.append((aid,loc,date(2023,1,1),cost,acc,60,True))
            opening(loc,'1500',cost);opening(loc,'1590',-acc)
    for loc,d,cost,kind in [('LOC-01',date(2026,1,12),1400000,'scan_tool'),('LOC-02',date(2026,2,9),2200000,'tire_changer'),('LOC-03',date(2026,5,11),2800000,'diagnostic_station')]:
        aid=f'ASSET-{loc}-{kind}';bid=bill(d,loc,'VEN-EQUIP',cost,'1500','equipment_capex',aid,due=biz(d+timedelta(days=30)))
        assets.append((aid,loc,d,cost,0,60,False))
    for aid,loc,ins,cost,acc,life,isopen in assets:
        emit('operating/assets',asset_id=aid,location_id=loc,description=aid.split('-',3)[-1],in_service_date=ins,original_cost_usd=money(cost),opening_accumulated_depreciation_usd=money(acc),useful_life_months=life,salvage_value_usd='0.00',depreciation_method='straight_line_full_month',opening_asset=str(isopen),disposal_date='',financed_loan_id=f'LOAN-{loc}' if isopen else '')
        for m in MONTHS:
            if monthend(m)<ins:continue
            dep=roundi(cost/life);did=uid('DEPCHG')
            emit('operating/depreciation',depreciation_id=did,asset_id=aid,location_id=loc,month=f'{m:%Y-%m}',depreciation_date=monthend(m),depreciation_usd=money(dep))
            post(monthend(m),loc,'operating','depreciation',did,[('6600',dep),('1590',-dep)])
    for loc in ['LOC-01','LOC-02','LOC-03']:
        loan=f'LOAN-{loc}';balance=6000000;opening(loc,'2500',-balance)
        emit('finance/loans',loan_id=loan,location_id=loc,lender_name='Demo Equipment Finance',origination_date='2023-11-01',opening_principal_usd=money(balance),annual_interest_pct='9.00',monthly_principal_usd='1000.00',maturity_date='2029-10-20',collateral='Opening workshop equipment',currency='USD')
        for n in range(31):
            m=addmonth(START,n);due=biz(m.replace(day=20));principal=min(100000,balance);interest=roundi(balance*.09/12);sched=uid('DEBT');actual=due if due<=CUT else None;bid=''
            if actual:
                bid=bank(due,loc,-principal-interest,'debt_service',sched,'Demo Equipment Finance')
                post(due,loc,'finance','debt_service',sched,[('2500',principal),('6700',interest),('1000',-principal-interest)])
            emit('finance/debt_schedule',debt_schedule_id=sched,loan_id=loan,location_id=loc,due_date=due,opening_scheduled_principal_usd=money(balance),principal_usd=money(principal),interest_usd=money(interest),total_payment_usd=money(principal+interest),closing_scheduled_principal_usd=money(balance-principal),actual_payment_date=actual,bank_transaction_id=bid,status='paid_actual' if actual else 'contractual_future')
            balance-=principal

def marketing():
    for loc in ['LOC-01','LOC-02','LOC-03']:
        for platform in ['google','meta']:
            campaign=f'{platform.upper()}-{loc}'
            emit('marketing/campaigns',campaign_id=campaign,platform=platform,location_id=loc,campaign_name=f'Demo {loc} {platform} repair demand',start_date=START,end_date='',platform_attribution_model='synthetic_7_day_click_1_day_view' if platform=='meta' else 'synthetic_30_day_click',source_scope='Platform claims can overlap and do not equal earned revenue')
            vendor=f'VEN-ADS-{platform}'
            for m in MONTHS:
                total=0
                for d in days(m,monthend(m)):
                    base=14000 if platform=='google' else 6000
                    if d>=date(2026,5,1):base=roundi(base*1.22)
                    spend=roundi(base*R.uniform(.7,1.3)*(1.12 if d.month in [3,4,10,11] else 1))
                    clicks=max(1,roundi(spend/(520 if platform=='google' else 280)));impressions=clicks*R.randint(20,55);conversions=roundi(clicks*R.uniform(.08,.17));value=conversions*R.randint(48000,80000)
                    emit('marketing/daily_performance',performance_id=uid('AD-DAY'),campaign_id=campaign,platform=platform,location_id=loc,performance_date=d,impressions=impressions,clicks=clicks,spend_usd=money(spend),cost_micros=spend*10000,platform_claimed_conversions=conversions,platform_claimed_value_usd=money(value),attribution_note='Overlapping platform claim, not incremental sales or accounting revenue')
                    total+=spend
                adid=uid('AD-BILL');bid=bill(monthend(m),loc,vendor,total,'6400','ad_media',adid,due=biz(monthend(m)+timedelta(days=10)))
                emit('marketing/billing',ad_bill_id=adid,platform=platform,location_id=loc,service_month=f'{m:%Y-%m}',bill_date=monthend(m),amount_usd=money(total),accounting_bill_id=bid,daily_spend_summary='True')
    for platform in ['google','meta']:emit('operating/vendors',vendor_id=f'VEN-ADS-{platform}',vendor_name=f'Demo {platform.title()} Ads billing',email=f'{platform}.billing@example.com',service_category='advertising',net_days=10)
    for ap in T['schedule/appointments']:
        ch=ap['source_channel'];campaign=f'{ch.upper()}-{ap["location_id"]}' if ch in ['google','meta'] else ''
        emit('marketing/leads',lead_id=uid('LEAD'),customer_id=ap['customer_id'],location_id=ap['location_id'],lead_date=ap['booked_date'],source_channel=ch,campaign_id=campaign,appointment_id=ap['appointment_id'],ro_id=ap['ro_id'],is_repeat_customer=str(ch=='repeat'),attribution_policy='One observed booked lead per appointment; acquisition channel is synthetic customer-master proxy; other unconverted leads retained separately',lead_status='appointment_booked',lost_reason='')
    for m in MONTHS:
        for loc in ['LOC-01','LOC-02','LOC-03']:
            for k in range(150):
                ld=biz(m+timedelta(days=R.randrange(calendar.monthrange(m.year,m.month)[1])))
                if ld>monthend(m):ld=monthend(m)
                ch=R.choices(['google','meta','referral','organic','direct'],[48,24,12,10,6])[0]
                emit('marketing/leads',lead_id=uid('LEAD'),customer_id='',location_id=loc,lead_date=ld,source_channel=ch,campaign_id=f'{ch.upper()}-{loc}' if ch in ['google','meta'] else '',appointment_id='',ro_id='',is_repeat_customer='False',attribution_policy='Anonymous observed inquiry; no conversion or customer invoice inferred',lead_status='not_booked',lost_reason=['price_declined','no_suitable_slot','out_of_scope_request','not_reached'][k%4])

def settle_suppliers():
    creditdates=defaultdict(list)
    for r in T['accounting/vendor_credits']:creditdates[r['bill_id']].append(date.fromisoformat(r['credit_date']))
    for bid,b in sorted(BILLS.items(),key=lambda kv:(kv[1]['date'],kv[0])):
        pd=biz(b['due'], 4 if b['type']=='parts_receipt' and b['date']>=date(2026,8,1) else 0)
        if creditdates[bid]:pd=max(pd,biz(max(creditdates[bid]),2))
        remaining=b['amt']-b['credits'];assert remaining>=0
        if pd<=CUT and remaining:
            pay=uid('VPAY');bankid=bank(pd,b['loc'],-remaining,'vendor_payment',pay,b['vendor'])
            emit('accounting/vendor_payments',vendor_payment_id=pay,vendor_id=b['vendor'],location_id=b['loc'],payment_date=pd,amount_usd=money(remaining),bank_transaction_id=bankid,payment_method='ACH')
            emit('accounting/ap_allocations',ap_allocation_id=uid('APA'),bill_id=bid,allocation_date=pd,allocation_type='cash_payment',vendor_payment_id=pay,vendor_credit_id='',amount_usd=money(remaining))
            post(pd,b['loc'],'accounting','vendor_payment',pay,[('2000',remaining),('1000',-remaining)])
            b['paid']=remaining
        op=b['amt']-b['credits']-b['paid'];b['row']['open_amount_usd']=money(op);b['row']['status']='paid' if not op else 'open'
        if op:
            emit('accounting/open_ap',bill_id=bid,vendor_id=b['vendor'],location_id=b['loc'],as_of_date=CUT,bill_date=b['date'],due_date=b['due'],total_usd=money(b['amt']),credit_allocated_usd=money(b['credits']),cash_paid_usd=money(b['paid']),open_amount_usd=money(op),po_id=b['po'],contract_id=b['contract'],expected_payment_date=biz(max(CUT+timedelta(days=2),pd)),payment_timing_note='Scheduled/assumed future timing only')
            if b['po']:emit('purchasing/payment_schedule',schedule_id=uid('SUPSCHED'),supplier_id=b['vendor'],location_id=b['loc'],po_id=b['po'],bill_id=bid,commitment_type='open_AP_received_stock',expected_due_date=biz(max(CUT+timedelta(days=2),pd)),residual_amount_usd=money(op),cash_forecast_overlap_key=bid)
    for po in T['purchasing/purchase_orders']:
        if cents(po['open_commitment_usd']):
            term=next(t for t in T['purchasing/terms_history'] if t['terms_id']==po['terms_id'])
            due=biz(date.fromisoformat(po['expected_receipt_date'])+timedelta(days=int(term['net_days'])))
            emit('purchasing/payment_schedule',schedule_id=uid('SUPSCHED'),supplier_id=po['supplier_id'],location_id=po['location_id'],po_id=po['po_id'],bill_id='',commitment_type='unreceived_PO_not_AP',expected_due_date=due,residual_amount_usd=po['open_commitment_usd'],cash_forecast_overlap_key=po['po_id'])
    # Monthly statement item copies reference existing bills/credits; amounts are informational.
    statements={}
    for b in BILLS.values():
        if not b['vendor'].startswith('SUP-'):continue
        key=(b['vendor'],b['loc'],b['date'].strftime('%Y-%m'))
        if key not in statements:statements[key]=[uid('STMT'),0]
        sid=statements[key][0];statements[key][1]+=b['amt']
        emit('purchasing/statement_items',statement_item_id=uid('STMTI'),statement_id=sid,document_type='bill',bill_id=b['id'],vendor_credit_id='',document_date=b['date'],signed_document_usd=money(b['amt']))
    for r in T['accounting/vendor_credits']:
        key=(r['vendor_id'],r['location_id'],r['credit_date'][:7])
        if key not in statements:statements[key]=[uid('STMT'),0]
        sid=statements[key][0];statements[key][1]-=cents(r['amount_usd'])
        emit('purchasing/statement_items',statement_item_id=uid('STMTI'),statement_id=sid,document_type='credit',bill_id='',vendor_credit_id=r['vendor_credit_id'],document_date=r['credit_date'],signed_document_usd=money(-cents(r['amount_usd'])))
    for (sup,loc,mo),(sid,amt) in sorted(statements.items()):emit('purchasing/supplier_statements',statement_id=sid,supplier_id=sup,location_id=loc,statement_month=mo,statement_date=monthend(date.fromisoformat(mo+'-01')),net_documents_usd=money(amt),is_summary_only='True',posting_status='Do not post; bills/credits already in AP')

def taxes():
    sales=defaultdict(int)
    for d,loc,a,v,row in J:
        if a=='2100':sales[(d.strftime('%Y-%m'),loc)]-=v
    for (mo,loc),amount in sorted(sales.items()):
        end=monthend(date.fromisoformat(mo+'-01'));due=biz(addmonth(end,1).replace(day=20));tid=f'TAX-{mo}-{loc}';bid=''
        if due<=CUT:
            bid=bank(due,loc,-amount,'synthetic_sales_tax_remittance',tid,'Demo tax authority')
            post(due,loc,'finance','sales_tax_remittance',tid,[('2100',amount),('1000',-amount)])
        emit('finance/tax_register',tax_period_id=tid,location_id=loc,tax_month=mo,net_tax_collected_usd=money(amount),synthetic_tax_base='Net parts sales less concessions',assumed_rate_pct='6.50',due_date=due,actual_remittance_date=due if due<=CUT else '',remitted_usd=money(amount if due<=CUT else 0),open_payable_usd=money(0 if due<=CUT else amount),bank_transaction_id=bid,legal_claim='None; synthetic model parameter')

def planning():
    ver='BUDGET-ORIGINAL-20241018'
    emit('planning/budget_versions',budget_version_id=ver,version_name='Original approved 24-month operating budget',approved_date='2024-10-18',approved_by='Demo owner board',period_start=START,period_end=CUT,version_type='original_approved',locked='True')
    for m in MONTHS:
        season={1:.92,2:.89,3:1.03,4:1.04,5:1.07,6:1.08,7:1.06,8:1.03,9:.98,10:1.02,11:1.01,12:.91}[m.month]
        for loc in ['LOC-01','LOC-02','LOC-03','HQ']:
            if loc!='HQ':
                li=int(loc[-1]);tech=5 if m<date(2026,7,1) else 6
                volume=roundi((385 if li==1 else 368 if li==2 else 355)*season*(1.035 if m>=date(2025,11,1) else 1))
                labor=roundi(volume*2.5*(143+li*3)*100);parts=roundi(volume*26900);fee=roundi(labor*.05);sublet=roundi(volume*.025*11500)
                budget={'4000':labor,'4010':parts,'4020':fee,'4030':sublet,'5100':roundi(parts*.51),'5000':roundi(tech*2080/12*3600),'5010':roundi(tech*2080/12*3600*.08),'5015':roundi(tech*2080/12*220),'6100':roundi((2*5500000+8100000)/12),'6110':roundi((2*5500000+8100000)/12*.12),'6300':680000,'6310':110000,'6320':92000,'6330':65000,'6340':52000,'6350':38000,'6400':600000,'6500':roundi((labor+parts+fee+sublet)*.023),'6600':150000,'6700':40000,'5110':40000,'5120':10000,'5130':5000,'5200':roundi(volume*.025*8200),'4090':10000}
                emit('planning/driver_plan',driver_plan_id=f'DRIVER-{m:%Y%m}-{loc}',budget_version_id=ver,month=f'{m:%Y-%m}',location_id=loc,bays=6,technician_fte=f'{tech}.00',advisor_fte='2.00',manager_fte='1.00',planned_ro_count=volume,planned_book_hours=f'{volume*2.5:.2f}',planned_physical_job_hours=f'{volume*2.5/1.3:.2f}',planned_paid_technician_hours=f'{tech*2080/12:.2f}',planned_labor_rate_usd=f'{143+li*3}.00',planned_parts_margin_pct='49.00',planned_efficiency_pct='130.00',approval_date='2024-10-18')
            else:budget={'6200':roundi(19600000/12),'6210':roundi(19600000/12*.12),'6330':145000}
            for account,amount in budget.items():emit('planning/monthly_budget',budget_line_id=uid('BUD'),budget_version_id=ver,month=f'{m:%Y-%m}',location_id=loc,account_code=account,budget_amount_usd=money(amount),sign_convention='Positive revenue or expense magnitude; contra-account also positive magnitude',approved_date='2024-10-18')
    assumptions=[('fleet_collection_tail_days','80','calendar_day','Fleet partial/late payment history; use invoice-level expected dates'),('new_technician_ramp_first_35_days','0.38','available_time_fraction','Observed onboarding policy'),('new_technician_ramp_next_40_days','0.58','available_time_fraction','Observed onboarding policy'),('card_processor_fee_percent','2.70','percent','Synthetic contract parameter'),('card_processor_fee_fixed','0.25','USD_per_capture','Synthetic contract parameter'),('parts_tax_rate','6.50','percent','Synthetic assumption; not statutory'),('supplier_special_order_delay','14','calendar_day','Planning stress assumption beyond agreed ETA'),('warranty_spike_location','LOC-03','identifier','Unresolved root-cause actions; supplier recovery separately'),('payroll_funding_lag','2','business_day','Semi-monthly period end plus two weekdays')]
    for name,value,unit,note in assumptions:emit('planning/forecast_assumptions',assumption_id=f'ASSUME-{name}',as_of_date=CUT,assumption_name=name,value=value,unit=unit,effective_from='2026-11-01',basis=note,version='FORECAST-INPUTS-CUTOFF',is_actual='False')
    def commitment(typ,loc,src,ref,d,amt,overlap,note):emit('planning/commitments',commitment_id=uid('COMMIT'),as_of_date=CUT,commitment_type=typ,location_id=loc,source_table=src,source_id=ref,expected_date=d,expected_amount_usd=amt,overlap_key=overlap,note=note,actual_event_date='')
    for r in T['billing/open_ar']:commitment('customer_collection',r['location_id'],'billing/open_ar',r['invoice_id'],r['expected_collection_date'],r['open_amount_usd'],r['invoice_id'],'Inflow; same AR balance, not additional revenue')
    for r in T['accounting/open_ap']:commitment('open_AP_payment',r['location_id'],'accounting/open_ap',r['bill_id'],r['expected_payment_date'],money(-cents(r['open_amount_usd'])),r['bill_id'],'Outflow; do not add supplier payment schedule again')
    for r in T['purchasing/payment_schedule']:
        if not r['bill_id']:commitment('unreceived_PO_payment',r['location_id'],'purchasing/purchase_orders',r['po_id'],r['expected_due_date'],money(-cents(r['residual_amount_usd'])),r['po_id'],'Not yet AP; no receipt actual')
    for r in T['payroll/runs']:
        if not r['actual_funding_date']:commitment('earned_payroll_funding',r['location_id'],'payroll/runs',r['payroll_run_id'],r['scheduled_funding_date'],money(-cents(r['total_funding_usd'])),r['payroll_run_id'],'Same payroll payable; next cycles require drivers')
    for r in T['finance/debt_schedule']:
        if not r['actual_payment_date']:commitment('contractual_debt_payment',r['location_id'],'finance/debt_schedule',r['debt_schedule_id'],r['due_date'],money(-cents(r['total_payment_usd'])),r['debt_schedule_id'],'Future contractual principal plus interest')
    for r in T['finance/tax_register']:
        if not r['actual_remittance_date']:commitment('tax_payable_remittance',r['location_id'],'finance/tax_register',r['tax_period_id'],r['due_date'],money(-cents(r['open_payable_usd'])),r['tax_period_id'],'Same sales tax payable')
    for r in T['schedule/appointments']:
        if r['scheduled_date']>str(CUT):commitment('agreed_future_appointment',r['location_id'],'schedule/appointments',r['appointment_id'],r['scheduled_date'],'',r['appointment_id'],'Demand driver only; blank amount, not revenue or cash commitment')
    for r in T['operating/recurring_contracts']:commitment('recurring_contract_next_cycle',r['location_id'],'operating/recurring_contracts',r['contract_id'],r['next_expected_due_date'],money(-cents(r['monthly_base_usd'])),f'{r["contract_id"]}-202611','November service cycle; open October bill is separate. Repeat future cycles under contract drivers.')
    for i,(eff,name,evidence) in enumerate([
      ('2025-07-01','Supplier step increases base unit costs 9%; retail part prices only about 4%','purchasing/purchase_price_history; shop/ro_lines'),
      ('2026-01-01','Existing employee wages increase 4.5% and rent increases 3%','payroll/compensation_history; operating/recurring_contracts; accounting/bills'),
      ('2026-02-02','North Creek sixth technician starts with 120-day utilization ramp','payroll/employees; schedule/daily_capacity'),
      ('2026-03-01','Location labor menu rates rise $5/hour','shop/labor_rate_history; billing/invoice_lines'),
      ('2026-04-01','Supplier costs reach 126% of opening; mix shifts toward expensive repairs; physical minutes increase 17%','purchasing/purchase_price_history; shop/jobs; schedule/job_segments; accounting/general_ledger'),
      ('2026-05-01','Oak Junction comeback spike; maintenance and advertising costs rise','warranty/comebacks; warranty/supplier_recoveries; accounting/bills'),
      ('2026-05-04','River West sixth technician joins','payroll/employees; schedule/daily_capacity'),
      ('2026-07-01','Fleet final settlement stretches eight more days, beyond semi-monthly payroll funding','billing/payments; billing/open_ar; payroll/runs'),
      ('2026-07-06','Oak Junction sixth technician joins','payroll/employees; schedule/daily_capacity'),
      ('2026-08-01','Special-order delivery delay, SUP-04 terms tighten to net21, supplier cash timing strains','purchasing/terms_history; purchasing/purchase_orders; purchasing/payment_schedule'),
    ],1):emit('planning/business_events',event_id=f'EVENT-{i:02d}',effective_date=eff,event_name=name,evidence_tables=evidence,synthetic='True')

def finish_accounting():
    # Equity is opening balance only, not a cash plug or in-period rescue.
    for loc in ['LOC-01','LOC-02','LOC-03','HQ']:
        opening(loc,'3000',-sum(v for (ll,a),v in OPEN.items() if ll==loc))
    for (loc,a),v in sorted(OPEN.items()):emit('accounting/opening_trial_balance',opening_id=f'OTB-{loc}-{a}',as_of_date=START-timedelta(days=1),location_id=loc,account_code=a,debit_usd=money(max(v,0)),credit_usd=money(max(-v,0)),signed_balance_usd=money(v))
    aggregate=defaultdict(lambda:[0,0]);balance=OPEN.copy()
    for d,loc,a,v,row in J:aggregate[(d.strftime('%Y-%m'),loc,a)][0 if v>0 else 1]+=abs(v)
    for m in MONTHS:
        mo=f'{m:%Y-%m}'
        for loc in ['LOC-01','LOC-02','LOC-03','HQ']:
            for a in ACCOUNTS:
                deb,cred=aggregate[(mo,loc,a)];before=balance[(loc,a)];balance[(loc,a)]+=deb-cred
                emit('accounting/monthly_trial_balance',trial_balance_id=f'TB-{mo}-{loc}-{a}',month=mo,location_id=loc,account_code=a,opening_signed_balance_usd=money(before),period_debits_usd=money(deb),period_credits_usd=money(cred),closing_signed_balance_usd=money(balance[(loc,a)]),sign_convention='debit_minus_credit; no annual closing in this observation extract')
        # All HQ operating costs are allocated 35/33/32; zero sum in this memo table.
        for a in ACCOUNTS:
            if ACCOUNTS[a][2] not in ['shared_payroll','software']:continue
            amount=sum(v for d,loc,aa,v,row in J if loc=='HQ' and aa==a and d.strftime('%Y-%m')==mo)
            if not amount:continue
            emit('accounting/shared_cost_allocations',shared_allocation_id=uid('SHARE'),month=mo,account_code=a,location_id='HQ',allocated_expense_delta_usd=money(-amount),allocation_basis='HQ reversal',posting_status='management_memo_only')
            left=amount
            for i,(loc,frac) in enumerate([('LOC-01',.35),('LOC-02',.33),('LOC-03',.32)]):
                n=left if i==2 else roundi(amount*frac);left-=n
                emit('accounting/shared_cost_allocations',shared_allocation_id=uid('SHARE'),month=mo,account_code=a,location_id=loc,allocated_expense_delta_usd=money(n),allocation_basis=f'Approved fixed {frac:.0%} share',posting_status='management_memo_only')
    bal=90000000;ix=0;bs=sorted(BANK,key=lambda r:(r['posted_date'],r['bank_transaction_id']))
    for m in MONTHS:
        mo=f'{m:%Y-%m}';before=bal;incoming=outgoing=0;cnt=0
        while ix<len(bs) and bs[ix]['posted_date']<=monthend(m):
            r=bs[ix];amt=r.pop('amount_cents');bal+=amt;cnt+=1
            incoming+=max(amt,0);outgoing+=max(-amt,0)
            emit('bank/statement',**r,statement_sequence=ix+1,amount_usd=money(amt),running_balance_usd=money(bal));ix+=1
        emit('bank/monthly_statements',bank_statement_id=f'BANK-STMT-{mo}',bank_account_id='BANK-OPERATING-DEMO',month=mo,opening_balance_usd=money(before),inflows_usd=money(incoming),outflows_usd=money(outgoing),closing_balance_usd=money(bal),transaction_count=cnt)
    return balance

def owner_distributions():
    # Quarterly discretionary cash sweep with a $450k operating reserve and $1m cap.
    sweep=0
    for m in MONTHS:
        if m.month not in [3,6,9,12]:continue
        d=monthend(m)
        while d.weekday()>4:d-=timedelta(days=1)
        cash=90000000+sum(r['amount_cents'] for r in BANK if r['posted_date']<=d)
        amount=min(100000000,max(0,cash-45000000))
        if not amount:continue
        ref=uid('OWNER');bid=bank(d,'HQ',-amount,'owner_distribution',ref,'Demo owner members')
        post(d,'HQ','finance','owner_distribution',ref,[('3100',amount),('1000',-amount)],'Quarterly discretionary distribution; retains $450k at decision date, capped $1m')
        emit('finance/owner_distributions',distribution_id=ref,distribution_date=d,location_id='HQ',amount_usd=money(amount),bank_transaction_id=bid,minimum_cash_reserve_usd='450000.00',quarterly_cap_usd='1000000.00',policy='Discretionary synthetic quarterly sweep; equity, not expense; no future distribution assumed')

def writecsv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='raise');w.writeheader();w.writerows(rows)
def infer_type(field,rows):
    vals=[r.get(field,'') for r in rows if r.get(field,'')!=''][:50]
    if field.endswith('_id') or field in ['sku','account_code','source_id','overlap_key','value','source_table']:return 'string'
    if field.endswith('_usd') or field.endswith('_pct') or field.endswith('_hours') or 'quantity' in field or field in ['base_units_per_purchase_unit','overtime_multiplier','technician_fte','advisor_fte','manager_fte','planned_efficiency_pct','planned_parts_margin_pct']:return 'decimal'
    if field.endswith('_at') or field in ['scheduled_start','shift_start','shift_end','lunch_start','lunch_end']:return 'datetime_local'
    if vals and all(len(v)>=19 and v[4]=='-' and v[7]=='-' and v[10]=='T' for v in vals):return 'datetime_local'
    if field.endswith('_date') or field in ['effective_from','effective_to','period_start','period_end','date','expected_date']:return 'date'
    if vals and all(v in ['True','False'] for v in vals):return 'boolean'
    if vals and all(v.lstrip('-').isdigit() for v in vals):return 'integer'
    return 'string'

FIELD_DESCRIPTIONS={
 'location_id':'Operating shop or shared cost center; LOC-01/02/03 or HQ.',
 'ro_id':'Repair order identifier; connects operational, parts, billing and accounting events.',
 'job_id':'Service job identifier inside its parent RO.',
 'customer_id':'Fictional customer identifier; contacts use example.com.',
 'vehicle_id':'Synthetic vehicle identifier; demo_vin and demo_plate cannot identify a real vehicle.',
 'employee_id':'Employee master identifier; home technician and payroll employee are the same person.',
 'bay_id':'Physical service bay identifier; occupancy differs from productive job time.',
 'invoice_id':'Delivered customer invoice identifier; blank means no actual invoice.',
 'bill_id':'Supplier/operating AP invoice identifier, not a customer invoice.',
 'po_id':'Purchase order commitment identifier; does not itself post GL.',
 'sku':'Part catalog identifier; quantities always in stated base unit unless purchase_quantity.',
 'quantity':'Line quantity in unit; labor hours may exceed physical clock hours.',
 'quantity_delta':'Signed physical stock change in base units, to 0.001.',
 'carrying_value_delta_usd':'Signed inventory carrying value change; receipts/transfer-in positive, issues/returns/loss negative.',
 'book_billed_hours':'Customer approved flat-rate book hours; no constraint book <= actual applies.',
 'approved_clock_minutes':'Physical productive job minutes approved by supervisor; capacity denominator input.',
 'approved_actual_minutes':'Total approved actual job clock, not billed book hours.',
 'actual_start_at':'Actual uninterrupted work start in shop local time; blank for future event.',
 'actual_end_at':'Actual uninterrupted work end; end is exclusive for overlap checks.',
 'available_minutes':'Physical technician capacity excluding PTO and unpaid lunch, including explicitly paid OT.',
 'paid_minutes_denominator':'All earned paid minutes of this employee/pay period, including idle/PTO; allocation denominator.',
 'allocated_actual_payroll_usd':'Analytical share of gross wages plus employer tax/benefit cost; not a second GL expense.',
 'allocated_expense_delta_usd':'Management-only HQ reallocation; company sum per month/account is zero.',
 'actual_delivery_date':'Actual vehicle release to customer; revenue and delivered WIP recognition trigger.',
 'actual_completion_date':'Physical work completion; pickup can occur later and revenue waits for delivery.',
 'actual_invoice_date':'Actual delivered invoice date, blank for no-charge warranty or undelivered RO.',
 'signed_balance_usd':'Debit minus credit; assets usually positive, liabilities/equity usually negative.',
 'closing_signed_balance_usd':'Cumulative debit-minus-credit closing balance; P&L must use period activity.',
 'amount_usd':'USD decimal amount; see table grain and sign_convention for cash/credit semantics.',
 'debit_usd':'Nonnegative ledger debit in USD cents precision.',
 'credit_usd':'Nonnegative ledger credit in USD cents precision.',
 'gross_usd':'Line price before discount, or signed processor gross capture/refund as table grain specifies.',
 'discount_usd':'Positive reduction of line gross; already included in net_usd.',
 'net_usd':'Customer line/header amount after discount, excluding synthetic sales tax.',
 'tax_usd':'Synthetic 6.5% of net parts, rounded per line; liability, not earned revenue.',
 'total_usd':'Net plus tax; original document amount is preserved after separate credits.',
 'liability_delta_usd':'Customer deposit liability change; receipts positive and applications/refunds negative.',
 'actual_funding_date':'Actual bank-funded payroll date; blank at cutoff for earned unfunded payroll.',
 'actual_payment_date':'Actual debt/payment date; blank for contractual future schedule.',
 'statement_sequence':'Chronological bank row sequence; establishes same-day running balance order.',
 'event_sequence':'Physical stock event order; sort by movement_date, event_sequence.',
 'platform_claimed_value_usd':'Platform attribution claim; may overlap other channels and is not shop earned revenue.',
 'overlap_key':'Cash forecast deduplication key; same source obligation must be used once.',
 'expected_amount_usd':'Signed future cash assumption; negative outflow, positive inflow, blank for noncash demand driver.',
 'open_reserved_base_quantity':'Unissued requested parts; no physical stock/value/GL movement.',
 'total_wip_usd':'Issued parts plus completed outsourced services on undelivered RO; payroll deliberately not capitalized.',
}

def export():
    ROOT.mkdir(parents=True,exist_ok=True)
    sources=ROOT/'sources';manifest=[];schemas={};catalog=[];dictionary=[]
    for t,meta in META.items():
        rows=T[t];fields=meta['fields'];physical=[]
        if not fields:raise ValueError(f'No schema rows {t}')
        partition=meta['partition_column'];buckets=defaultdict(list)
        if partition:
            for r in rows:buckets[r[partition][:7]].append(r)
        else:buckets['']=rows
        for mo,rr in sorted(buckets.items()):
            rel=f'{t}/{mo}.csv' if partition else f'{t}.csv';path=sources/rel;writecsv(path,rr,fields);physical.append(rel)
            manifest.append(dict(relative_path=f'sources/{rel}',logical_table=t,row_count=len(rr),byte_size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        types={f:infer_type(f,rows) for f in fields}
        schemas[t]={**meta,'types':types,'physical_files':physical,'row_count':len(rows),'encoding':'utf-8-sig','delimiter':',','currency':'USD','decimal_precision':'USD 0.01; quantities 0.001; physical integer minutes','null_semantics':'Empty means not applicable/unknown/not yet actual; never coerce to zero indiscriminately.'}
        catalog.append(dict(logical_table=t,system=t.split('/')[0],grain=meta['grain'],primary_key='|'.join(meta['primary_key']),row_count=len(rows),physical_file_count=len(physical),notes=meta['notes']))
        for f in fields:
            typ=types[f];unit='USD' if f.endswith('_usd') else 'percent' if f.endswith('_pct') else 'minute' if f.endswith('_minutes') else 'hour' if f.endswith('_hours') else 'base_unit_0.001' if 'quantity' in f else 'local_shop_time' if typ=='datetime_local' else ''
            sign='nonnegative magnitude'
            if any(x in f for x in ['signed','delta','expected_amount']) or (t=='billing/payments' and f=='amount_usd') or (t=='bank/statement' and f=='amount_usd') or (t=='processor/balance_transactions' and f in ['gross_usd','net_usd']):sign='signed; details in ACCOUNTING_SIGN_GUIDE_RU.md'
            desc=FIELD_DESCRIPTIONS.get(f, f.replace('_',' ').capitalize()+f'; {meta["grain"]}.')
            dictionary.append(dict(logical_table=t,column_name=f,data_type=typ,is_primary_key=str(f in meta['primary_key']),nullable=str(any(not r.get(f,'') for r in rows)),unit=unit,sign_convention=sign if typ in ['decimal','integer'] else '',description=desc))
    targets={}
    for t,s in schemas.items():
        if len(s['primary_key'])==1:targets.setdefault(s['primary_key'][0],(t,s['primary_key'][0]))
    targets.update({'location_id':('shop/locations','location_id'),'ro_id':('shop/repair_orders','ro_id'),'original_ro_id':('shop/repair_orders','ro_id'),'corrective_ro_id':('shop/repair_orders','ro_id'),'bill_id':('accounting/bills','bill_id'),'original_bill_id':('accounting/bills','bill_id'),'invoice_id':('billing/invoices','invoice_id'),'applied_invoice_id':('billing/invoices','invoice_id'),'account_code':('accounting/chart_of_accounts','account_code'),'expense_account_code':('accounting/chart_of_accounts','account_code'),'offset_account_code':('accounting/chart_of_accounts','account_code'),'rate_id':('shop/labor_rate_history','rate_id'),'labor_rate_id':('shop/labor_rate_history','rate_id'),'parent_estimate_id':('shop/estimates','estimate_id'),'initial_estimate_id':('shop/estimates','estimate_id'),'original_payment_id':('billing/payments','payment_id'),'refund_payment_id':('billing/payments','payment_id'),'original_receipt_id':('purchasing/receipts','receipt_id'),'home_bay_id':('shop/bays','bay_id'),'from_location_id':('shop/locations','location_id'),'to_location_id':('shop/locations','location_id'),'paired_movement_id':('inventory/movements','movement_id'),'out_movement_id':('inventory/movements','movement_id'),'in_movement_id':('inventory/movements','movement_id'),'accounting_bill_id':('accounting/bills','bill_id'),'processor_balance_transaction_id':('processor/balance_transactions','balance_transaction_id'),'supplier_recovery_id':('warranty/supplier_recoveries','recovery_id'),'financed_loan_id':('finance/loans','loan_id')})
    targets['issue_movement_id']=('inventory/movements','movement_id')
    for t,s in schemas.items():
        for f in s['fields']:
            if f not in targets:continue
            target,tc=targets[f]
            if target==t and f in s['primary_key']:continue
            # Vendor IDs may be suppliers or operating vendors; explicit polymorphic mapping below.
            if f=='vendor_id':continue
            link(t,f,target,tc)
    metadir=ROOT/'metadata';metadir.mkdir(exist_ok=True)
    (metadir/'table_schemas.json').write_text(json.dumps(schemas,indent=2,ensure_ascii=False),encoding='utf-8')
    writecsv(metadir/'table_catalog.csv',catalog,list(catalog[0]))
    writecsv(metadir/'data_dictionary.csv',dictionary,list(dictionary[0]))
    writecsv(metadir/'relationships.csv',REL,list(REL[0]))
    writecsv(metadir/'file_manifest.csv',manifest,list(manifest[0]))
    systemnotes={
     'shop':'Shopmonkey/Tekmetric-inspired custom extracts: approvals, RO, jobs, menu and history.',
     'schedule':'Appointment and physical capacity event extracts; no native API fidelity claimed.',
     'inventory':'Perpetual FIFO stock, reservations, parts/sublet WIP and counts.',
     'purchasing':'Supplier agreements, prices, PO/receipts/returns and statement summaries.',
     'billing':'Customer invoices, actual receipts, deposits, allocations, credits and AR.',
     'warranty':'Free comeback work and separately recognized supplier recoveries.',
     'processor':'Synthetic card clearing and payout/bank settlement, 2.7% + $0.25 assumed.',
     'payroll':'Earned attendance-based compensation and actual funding; allocations are analytical.',
     'operating':'Assets, straight-line depreciation, recurring contracts and outsourced work.',
     'finance':'Debt contractual schedule and synthetic sales tax remittances.',
     'marketing':'Google/Meta-style spend and separate observed leads; claims may overlap.',
     'accounting':'QuickBooks-inspired custom chart, double-entry ledger, bills, AP and TB.',
     'bank':'One fictional bank account with actual posting sequence and monthly statements.',
     'planning':'Locked original approved budget, future demand/obligations and forecast inputs.'}
    sc=[]
    for system,note in systemnotes.items():
        ss=[r for r in catalog if r['system']==system]
        sc.append(dict(source_system=system,logical_tables=len(ss),row_count=sum(r['row_count'] for r in ss),description=note,extract_type='custom_flat_synthetic_csv',actual_cutoff=str(CUT)))
    writecsv(metadir/'source_catalog.csv',sc,list(sc[0]))
    mapping=[]
    for r in T['purchasing/suppliers']:mapping.append(dict(accounting_vendor_id=r['supplier_id'],master_table='purchasing/suppliers',master_id=r['supplier_id'],vendor_type='parts_supplier'))
    for r in T['operating/vendors']:mapping.append(dict(accounting_vendor_id=r['vendor_id'],master_table='operating/vendors',master_id=r['vendor_id'],vendor_type='operating_vendor'))
    writecsv(metadir/'vendor_master_mapping.csv',mapping,list(mapping[0]))
    vendor_rel=[dict(from_table=t,from_column='vendor_id',to_table='metadata/vendor_master_mapping.csv',to_column='accounting_vendor_id',cardinality='many_to_one',note='Polymorphic supplier or operating vendor; explicit master_table/master_id mapping.') for t,s in schemas.items() if 'vendor_id' in s['fields']]
    writecsv(metadir/'vendor_relationships.csv',vendor_rel,list(vendor_rel[0]))
    return schemas

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT,help='Output dataset directory; keep separate from original for reproduction')
    ROOT=parser.parse_args().output.resolve()
    setup();masters();employees();attendance();build_work();add_pending_work();vehicle_history();bay_calendar()
    print('work generated',len(ROS),'ROs',len(SEGMENTS),'segments',flush=True)
    inventory();print('inventory complete',len(T['inventory/movements']),flush=True)
    billing();settlement();print('billing complete',len(INVOICES),flush=True)
    payroll();print('payroll complete',flush=True)
    operating();marketing();settle_suppliers();taxes();planning();owner_distributions();finish_accounting();export()
    print('EXPORTED',ROOT,'rows',sum(map(len,T.values())),'GL',len(J),flush=True)
