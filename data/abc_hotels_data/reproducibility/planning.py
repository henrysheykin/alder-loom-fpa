from core import *

def build_budget(ds):
    approval='2024-10-15';version='BUDGET-ORIGINAL-2024-10-15'
    ds.add('planning/budget_versions','budget_version_id','One frozen pre-period approved 24-month budget version',budget_version_id=version,approved_date=approval,approved_by='Synthetic members budget committee',first_month='2024-11',last_month='2026-10',status='original_approved',actuals_used=False)
    hkcounts={'RAL':6,'WIL':5,'DUR':3};othercounts={'RAL':6,'WIL':6,'DUR':4}
    for d in months():
        mo=d.strftime('%Y-%m');nd=calendar.monthrange(d.year,d.month)[1]
        for p in CENTRES:
            amount={acc:0 for acc,n,t,g in ACCOUNTS if t in ['revenue','contra_revenue','expense']}
            if p!='CORP':
                cap=COUNTS[p]*nd;season=__import__('math').sin((d.month-3)*__import__('math').pi/6)
                oc=.68+(.04*season) if p=='RAL' else .65+.14*season if p=='WIL' else .77
                sold=round(cap*oc);adr=14900 if p=='RAL' else 16600 if p=='WIL' else 11200
                adr=mul(adr,1+.05*season if p=='WIL' else 1)
                if d>=date(2025,11,1):adr=mul(adr,1.035)
                net=adr*sold;discount=mul(net,.065);gross=net+discount
                amount['4000']=gross;amount['4010']=-discount;amount['4020']=-mul(net,.002)
                amount['4100']=sold*(420 if p=='RAL' else 320 if p=='WIL' else 0)
                amount['4110']=sold*(740 if p!='DUR' else 0)
                amount['4120']=sold*(90 if p!='DUR' else 185)
                amount['4200']=mul(net,.004);amount['4210']=mul(net,.003)
                amount['5000']=mul(net,.27*.15+.20*.18);amount['5010']=mul(net,.68*.0275)+sold*7
                amount['5100']=mul(1900,Decimal(hkcounts[p])*Decimal('7')*Decimal(nd)*Decimal(5)/7)
                # hourly other + salaried managers; budget driver rates intentionally frozen before actual wage changes.
                amount['5110']=mul(2150,Decimal(othercounts[p]-1)*8*Decimal(nd)*5/7)+516667
                amount['5130']=mul(amount['5100']+amount['5110'],.083)
                amount['5140']=(hkcounts[p]+othercounts[p])*35000;amount['5150']=0
                amount['5200']=sold*(420 if p!='DUR' else 170);amount['5210']=sold*(235 if p!='DUR' else 120)
                amount['5220']=mul(amount['4110'],.39);amount['5300']=280000 if p=='RAL' else 310000 if p=='WIL' else 220000
                amount['5310']=mul(640000 if p=='RAL' else 720000 if p=='WIL' else 610000,1.18 if d.month in [6,7,8] else 1)
                amount['5320']=0 if p=='RAL' else 2600000 if p=='WIL' else 2400000
                amount['5330']=1650000 if p=='RAL' else 580000 if p=='WIL' else 480000;amount['5340']=920000 if p!='DUR' else 620000
                amount['5400']=mul((3700+5800)*nd,1.15 if p=='WIL' else .8 if p=='DUR' else 1)
                amount['5600']=2250000 if p=='RAL' else 1208333 if p=='WIL' else 1125000
                amount['5700']=1743750 if p=='RAL' else 0
                ds.add('planning/approved_room_plan','budget_version_id,property_id,service_month','One original monthly property room-night/rate/mix plan; no recast actuals',budget_version_id=version,approved_date=approval,property_id=p,service_month=mo,physical_nights=cap,planned_closed_nights=0,available_nights=cap,planned_sold_nights=sold,planned_adr_usd=adr,planned_net_room_revenue_usd=net,direct_mix=.38,agency_mix=.27,merchant_mix=.20,corporate_mix=.15,planned_complimentary_nights=round(cap*.003))
                for role,count,hourly,annual in [('housekeeper',hkcounts[p],1900,0),('property_other',othercounts[p]-1,2150,0),('property_manager',1,0,6200000)]:
                    ds.add('planning/approved_staff_plan','budget_version_id,property_id,service_month,role','One original monthly role/property headcount and cost driver',budget_version_id=version,property_id=p,service_month=mo,role=role,planned_headcount=count,hourly_rate_usd=hourly,annual_salary_usd=annual,planned_hours_per_week=35 if role=='housekeeper' else 40,approved_date=approval)
            else:
                amount['5120']=2291667;amount['5130']=mul(amount['5120'],.083);amount['5140']=105000;amount['5500']=1050000
                ds.add('planning/approved_staff_plan','budget_version_id,property_id,service_month,role','One original monthly role/property headcount and cost driver',budget_version_id=version,property_id=p,service_month=mo,role='corporate_blended_average',planned_headcount=3,hourly_rate_usd=0,annual_salary_usd=9166667,planned_hours_per_week=40,approved_date=approval)
            for acc,val in amount.items():
                ds.add('planning/approved_budget','budget_version_id,property_id,service_month,account_code','One frozen original budget P&L account/property/month; income and expense positive; contra revenue negative',budget_version_id=version,approved_date=approval,property_id=p,service_month=mo,account_code=acc,budget_usd=val,currency='USD',sign_convention='positive income or expense; contra-revenue negative')

def build_cutoff_subledgers_forecast(ds):
    payby=defaultdict(list);apps=defaultdict(int);security=defaultdict(int);corpdep=defaultdict(int);otaar=defaultdict(int)
    for t in ds.tables['payments/transactions']:payby[t['reservation_id']].append(t)
    for a in ds.tables['payments/applications']:apps[a['reservation_id']]+=a['amount_usd']
    for s in ds.tables['payments/security_movements']:security[s['reservation_id']]+=s['amount_usd']
    for c in ds.tables['corporate_billing/prepayments']:corpdep[c['reservation_id']]+=c['open_amount_usd']
    settlement={s['settlement_id']:s for s in ds.tables['channel_manager/settlements']}
    for c in ds.tables['channel_manager/settlement_lines']:
        if not settlement[c['settlement_id']]['actual_release_date']:otaar[c['reservation_id']]+=c['gross_folio_usd']
    folios={f['reservation_id']:f for f in ds.tables['night_audit/folios']}
    for r in ds.res:
        rid=r['reservation_id'];p=r['property_id'];dep=sum(t['gross_amount_usd'] for t in payby[rid] if t['purpose']=='lodging')-apps[rid];sec=security[rid];cd=corpdep[rid];ota=otaar[rid]
        if dep or sec or cd or ota or folios[rid]['guest_open_ar_usd']:
            ds.add('payments/reservation_balances','reservation_id','One nonzero reservation deposit/security/guest/OTA balance at cutoff; different account types never netted',reservation_id=rid,property_id=p,snapshot_date=iso(CUT),guest_advance_deposit_usd=dep,corporate_advance_deposit_usd=cd,refundable_security_usd=sec,guest_open_ar_usd=folios[rid]['guest_open_ar_usd'],ota_open_ar_usd=ota,expected_security_return_date=iso(plus_business(r['_b'],3)) if sec else '',scheduled_checkout_date=r['scheduled_checkout_date'])
    # Explicit future booking payment terms: quoted future charges are not forecast receipts by themselves.
    for r in ds.res:
        future=[n for n in ds.tables['planning/on_books_nights'] if n['reservation_id']==r['reservation_id']]
        if not future or r['channel_id']=='INTERNAL':continue
        dep=sum(t['gross_amount_usd'] for t in payby[r['reservation_id']] if t['purpose']=='lodging')-apps[r['reservation_id']]+corpdep[r['reservation_id']]
        service_months=defaultdict(list)
        for n in future:service_months[n['service_date'][:7]].append(n)
        for mo,nn in sorted(service_months.items()):
            unearned=sum(n['booked_room_usd']+n['booked_lodging_tax_usd'] for n in nn);cover=min(max(0,dep),unearned);dep-=cover
            collect=iso(max(CUT+timedelta(days=1),r['_a']));first_collect=collect
            if r['company_id']:
                delay=52 if r['company_id']=='CO-001' else 8 if r['company_id']=='CO-003' else 0
                first_collect=iso(business(month_end(date.fromisoformat(mo+'-01'))+timedelta(days=(45 if r['company_id']=='CO-001' else 30)+delay)))
                collect=iso(business(month_end(date.fromisoformat(mo+'-01'))+timedelta(days=(45 if r['company_id']=='CO-001' else 30)+delay+18)))
            if r['collection_model']=='merchant':collect='';first_collect=''
            ds.add('planning/booked_payment_terms','reservation_id,service_month','One OTB reservation/service-month cash timing input; corporate monthly invoice timing; not actual AR',reservation_id=r['reservation_id'],service_month=mo,property_id=r['property_id'],snapshot_date=iso(CUT),collection_model=r['collection_model'],company_id=r['company_id'],scheduled_checkin_date=r['scheduled_checkin_date'],scheduled_checkout_date=r['scheduled_checkout_date'],future_booked_charges_usd=unearned,existing_advance_cover_usd=cover,incremental_guest_collect_usd=max(0,unearned-cover) if r['collection_model'] in ['hotel_collect','agency','invoice'] else 0,expected_first_collect_date=first_collect,first_tranche_share=.65 if r['company_id'] else 1.0,expected_collect_date=collect,assumption='corporate 65% at first date, remainder at final expected_collect_date; CO-001 delay52, CO-003 delay8 days; merchant uses each service night weekly settlement, dates blank here')
    for i in range(13):
        a=CUT+timedelta(days=1+i*7);b=a+timedelta(days=6)
        ds.add('planning/forecast_weeks','week_id','One 7-day cash forecasting bucket; no forecast result is precomputed',week_id=f'FW-{i+1:02d}',week_start_date=iso(a),week_end_date=iso(b),snapshot_date=iso(CUT),is_actual=False)
        for p in PROPS:
            ds.add('planning/incremental_demand_assumptions','week_id,property_id','One versioned incremental new-booking assumption; apply only after subtracting OTB nights',week_id=f'FW-{i+1:02d}',property_id=p,assumption_version='FC-2026-10-31-BASE',target_total_sold_occupancy=.63 if p=='RAL' else .48 if p=='WIL' else .76,target_new_booking_adr_usd=16100 if p=='RAL' else 17200 if p=='WIL' else 11900,direct_mix=.40,agency_mix=.30,merchant_mix=.20,corporate_mix=.10,guest_prepaid_share=.46,corporate_collection_days=45,agency_commission_rate=.15,merchant_commission_rate=.18,gateway_percent_rate=.0275,gateway_fixed_fee_usd=25,lodging_tax_rate=.125 if p=='WIL' else .1125,variable_laundry_cost_per_sold_night_usd=490 if p!='DUR' else 195,variable_consumables_per_sold_night_usd=280 if p!='DUR' else 130,utilities_monthly_base_usd=793600 if p=='RAL' else 892800 if p=='WIL' else 756400,maintenance_monthly_base_usd=378000 if p=='RAL' else 418500 if p=='WIL' else 297000,incremental_nights_rule='max(0,target*available_nights-known_OTB_sold_nights); never add target occupancy to OTB',cash_lag_policy='gateway 2 business days plus weekly payout; agency commission monthly; merchant weekly net; business days exclude weekends only')
    obligations=[]
    def ob(kind,source,sourceid,p,d,amt,direction,overlap,account=''):
        if not amt:return
        obligations.append(dict(input_id=f'CFI-{len(obligations)+1:06d}',snapshot_date=iso(CUT),input_type=kind,source_table=source,source_id=sourceid,property_id=p,expected_cash_date=d,amount_usd=amt,direction=direction,gl_account_code=account,overlap_key=overlap,is_actual_cash=False))
    for i in ds.tables['corporate_billing/invoices']:
        if i['open_ar_usd']:ob('open_corporate_ar','corporate_billing/invoices',i['invoice_id'],i['property_id'],max('2026-11-02',i['expected_collection_date']),i['open_ar_usd'],'in',i['invoice_id'],'1100')
    for b in ds.tables['quickbooks/bills']:
        if b['open_ap_usd']:ob('open_vendor_ap','quickbooks/bills',b['bill_id'],b['property_id'],max('2026-11-02',b['expected_payment_date']),b['open_ap_usd'],'out',b['bill_id'],'2000')
    for f in ds.tables['gusto/funding']:
        if f['open_payable_usd']:ob('earned_unfunded_payroll','gusto/funding',f['funding_id'],f['property_id'],f['due_date'],f['open_payable_usd'],'out',f['funding_id'],f['payable_account_code'])
    for f in ds.tables['fixed_assets_finance/tax_remittances']:
        if f['open_tax_usd']:ob('hotel_lodging_tax','fixed_assets_finance/tax_remittances',f['tax_remittance_id'],f['property_id'],f['scheduled_payment_date'],f['open_tax_usd'],'out',f['tax_remittance_id'],'2100')
    for f in ds.tables['channel_manager/agency_invoices']:
        if f['open_usd']:ob('agency_commission','channel_manager/agency_invoices',f['agency_invoice_id'],f['property_id'],f['due_date'],f['open_usd'],'out',f['agency_invoice_id'],'2010')
    for f in ds.tables['channel_manager/settlements']:
        if not f['actual_bank_date']:ob('earned_ota_net_remittance','channel_manager/settlements',f['settlement_id'],f['property_id'],f['expected_bank_date'],f['net_payout_usd'],'in',f['settlement_id'],'1020' if f['actual_release_date'] else '1120')
    for f in ds.tables['payments/payouts']:
        if not f['actual_bank_date']:ob('gateway_transit','payments/payouts',f['payout_id'],f['property_id'],f['expected_bank_date'],f['net_payout_usd'],'in',f['payout_id'],'1020')
    unsettled=defaultdict(int)
    for t in ds.tables['payments/balance_transactions']:
        if not t['payout_id']:unsettled[t['property_id']]+=t['net_usd']
    for p,amt in unsettled.items():ob('gateway_unreleased_balance','payments/balance_transactions',p,p,'2026-11-09',amt,'in',f'CLEARING-{p}','1010')
    for b in ds.tables['payments/reservation_balances']:
        if b['refundable_security_usd']:ob('security_return','payments/reservation_balances',b['reservation_id'],b['property_id'],max('2026-11-02',b['expected_security_return_date']),b['refundable_security_usd'],'out',f'SEC-{b["reservation_id"]}','2210')
    for b in ds.tables['planning/capex_commitments']:ob('unreceived_capex','planning/capex_commitments',b['commitment_id'],b['property_id'],b['due_date'],b['open_commitment_usd'],'out',b['commitment_id'],'')
    for b in ds.tables['fixed_assets_finance/debt_schedule']:
        if not b['actual_payment_date']:ob('scheduled_debt_service','fixed_assets_finance/debt_schedule',b['debt_payment_id'],b['property_id'],b['due_date'],b['total_usd'],'out',b['debt_payment_id'],'2400')
    for b in obligations:ds.add('planning/known_cash_inputs','input_id','One convenience COPY/index of a known cash input; source tables authoritative; never append as extra facts',**b)
    # Future employee funding schedule is an estimate separate from already-earned October payroll.
    for d in months(CUT+timedelta(days=1),FUT):
        for half in [1,2]:
            end=d.replace(day=15) if half==1 else month_end(d);fund=plus_business(end,2)
            ds.add('planning/future_payroll_calendar','forecast_payroll_id','One future earned period/funding timing assumption; do not overlap earned actual payroll',forecast_payroll_id=f'FPR-{d:%Y-%m}-H{half}',period_start_date=iso(d if half==1 else d.replace(day=16)),period_end_date=iso(end),scheduled_funding_date=iso(fund),basis='active employees/effective compensation plus explicit hours, overtime and absence assumptions',hourly_regular_weekly_hours=35,other_hourly_weekly_hours=40,assumed_overtime_weekly_hours=0,employer_tax_rate=.083,benefit_per_employee_halfmonth_usd=17500,is_actual=False)
    # Balance-sheet snapshot to make cash availability and restricted liabilities explicit.
    for p in CENTRES:
        for acc in ['1000','1010','1020','1100','1110','1120','1130','2000','2010','2100','2110','2200','2210','2220','2300','2310','2400']:
            ds.add('planning/cutoff_balance_inputs','property_id,account_code','One signed GL cutoff balance; a lookup COPY, not a second balance source',snapshot_date=iso(CUT),property_id=p,account_code=acc,signed_balance_usd=ds.closing[(p,acc)],cash_restriction_note='bank unrestricted; security/deposit liabilities are not additional cash' if acc=='1000' else '')
