from core import *
from collections import Counter

VENDORS=[('VEN-LAUNDRY','Cape & Pine Linen Services LLC','laundry',15),('VEN-SUPPLY','Piedmont Guest Supply LLC','supplies',30),('VEN-AGENCY','Triangle Flex Hospitality LLC','agency',14),('VEN-MAINT','Clearwater Building Care LLC','maintenance',30),('VEN-UTIL','Regional Utility Services LLC','utilities',20),('VEN-RENT','Juniper Sites Landlord LLC','rent',1),('VEN-INS','Quay Risk Services LLC','insurance',20),('VEN-SERVICE','NightWatch Hospitality Services LLC','contract_services',30),('VEN-SOFTWARE','Cloud Ledger Support LLC','software_advisory',30),('VEN-CAPEX','Oakline Hospitality Fixtures LLC','capex',30),('VEN-FOOD','Coastal Breakfast Supply LLC','food',15),('VEN-META','Meta-style synthetic media billing','advertising',10),('VEN-GOOGLE','Google-style synthetic media billing','advertising',10)]

def add_bill(ds,p,v,day,items,kind,source_ref='',purchase=False,due=None):
    """Items: (account, cents, quantity, unit_cents, source_table, source_id)."""
    vendor=next(x for x in VENDORS if x[0]==v);bid=ds.ident('BIL');poid=ds.ident('PO') if purchase else '';receipt=ds.ident('RCP') if purchase else ''
    total=sum(i[1] for i in items);due=due or day+timedelta(days=vendor[3])
    if purchase:
        ds.add('procurement/purchase_orders','purchase_order_id','One approved vendor order; commitments differ from bills and cash',purchase_order_id=poid,property_id=p,vendor_id=v,approved_date=iso(max(START,day-timedelta(days=12))),expected_receipt_date=iso(day),ordered_total_usd=total,received_total_usd=total,unreceived_commitment_usd=0,status='received',contract_id='')
        ds.add('procurement/receipts','receipt_id','One actual accepted goods/service receipt; not a second expense',receipt_id=receipt,purchase_order_id=poid,property_id=p,vendor_id=v,received_date=iso(day),accepted_value_usd=total,bill_id=bid)
    row=ds.add('quickbooks/bills','bill_id','One vendor bill recognized once in GL; amount_paid applications below',bill_id=bid,vendor_id=v,property_id=p,invoice_date=iso(day),service_month=iso(day)[:7],due_date=iso(due),purchase_order_id=poid,receipt_id=receipt,source_reference=source_ref,bill_type=kind,total_usd=total,paid_usd=0,open_ap_usd=total,currency='USD',expected_payment_date=iso(business(due)))
    entries=[(p,'2000',-total)]
    for account,amount,quantity,unit,st,sid in items:
        lid=ds.ident('BLL');pol=ds.ident('POL') if poid else ''
        ds.add('quickbooks/bill_lines','bill_line_id','One vendor bill account/source detail; operational detail is supporting, not additive',bill_line_id=lid,bill_id=bid,property_id=p,account_code=account,description=kind,quantity=quantity,unit_cost_usd=unit,line_amount_usd=amount,source_table=st,source_id=sid,purchase_order_line_id=pol)
        entries.append((p,account,amount))
        if poid:
            ds.add('procurement/purchase_order_lines','purchase_order_line_id','One ordered item/service line',purchase_order_line_id=pol,purchase_order_id=poid,description=kind,quantity=quantity,unit_cost_usd=unit,ordered_value_usd=amount,received_value_usd=amount,open_value_usd=0,account_code=account)
            ds.add('procurement/receipt_lines','receipt_line_id','One accepted PO line; matches recognized vendor bill line',receipt_line_id=ds.ident('RCL'),receipt_id=receipt,purchase_order_line_id=pol,bill_line_id=lid,quantity=quantity,accepted_value_usd=amount)
    ds.post(day,'quickbooks','bills',bid,entries,kind)
    return row

def build_operations_payroll(ds):
    for vid,name,cat,terms in VENDORS:
        ds.add('procurement/vendors','vendor_id','One fictional supplier or synthetic platform billing vendor',vendor_id=vid,vendor_name=name,category=cat,payment_terms_days=terms,email=vid.lower()+'@example.com',currency='USD')
    employees=[];ei=0
    for p in CENTRES:
        roles=[('housekeeper',6 if p=='RAL' else 5 if p=='WIL' else 3,1900 if p!='DUR' else 1850,'hourly'),('front_desk',4 if p!='DUR' else 2,2100,'hourly'),('maintenance',1,2500,'hourly'),('property_manager',1,6200000,'salary')] if p!='CORP' else [('regional_manager',1,10500000,'salary'),('finance_manager',1,8800000,'salary'),('revenue_marketing',1,8200000,'salary')]
        for role,num,rate,paytype in roles:
            for j in range(num):
                ei+=1;eid=f'EMP-{ei:03d}'
                employee=ds.add('gusto/employees','employee_id','One synthetic employee with employment dates',employee_id=eid,display_name=f'Synthetic team member {ei:03d}',email=f'team{ei:03d}@example.com',home_property_id=p,role=role,pay_type=paytype,hire_date='2023-06-01',termination_date='',status_as_of_cutoff='active')
                employee['_index']=ei;employee['_role_index']=j;employee['_base']=rate;employees.append(employee)
                for vers,eff,end,multiplier in [('V1','2024-10-01','2026-05-31',1),('V2','2026-06-01','2027-12-31',1.075 if paytype=='hourly' else 1.04)]:
                    ds.add('gusto/compensation_history','compensation_id','One effective pay rate; hourly vs annual salary in separate columns',compensation_id=f'{eid}-{vers}',employee_id=eid,effective_from=eff,effective_through=end,hourly_rate_usd=mul(rate,multiplier) if paytype=='hourly' else 0,annual_salary_usd=mul(rate,multiplier) if paytype=='salary' else 0,employee_withholding_rate=.18 if paytype=='hourly' else .23,employer_payroll_tax_rate=.083,case_policy='synthetic rates; not statutory payroll calculation')
    # Daily room service tasks derived from actual stay nights and actual departures.
    tasksbyday=defaultdict(list);occ=defaultdict(list);resmap={r['reservation_id']:r for r in ds.res}
    for n in ds.tables['pms/actual_stay_nights']:occ[(n['property_id'],n['service_date'])].append(n)
    costs=defaultdict(lambda:Counter());payroll_entries=[];weekly=defaultdict(int);task_minutes=defaultdict(int)
    time_by_eid_period=defaultdict(list)
    for d in days():
        for p in PROPS:
            # Departures are on checkout calendar date, including arrivals in the same room later that day.
            departure=[r for r in ds.res if r['property_id']==p and r['_kind']=='stay' and r['_b']==d and r['_a']<=CUT]
            toclean=[]
            for r in departure:toclean.append((r,'departure',48 if p=='DUR' else 34,3 if p=='DUR' else 2))
            for n in occ[(p,iso(d))]:
                r=resmap[n['reservation_id']];age=(d-r['_a']).days
                if age<=0:continue
                if p=='DUR':
                    if age%7==0:toclean.append((r,'weekly_stayover',32,2))
                else:toclean.append((r,'stayover',16,1))
            available=[]
            for e in employees:
                if e['home_property_id']!=p or e['role']!='housekeeper':continue
                on=(int((d-START).days)+e['_index'])%7<5
                shortage=p=='WIL' and date(2026,6,15)<=d<=date(2026,8,31) and e['_role_index']<3
                if on and not shortage:available.append([e,420,0])
            agency=0;agency_tasks=0
            for r,typ,minutes,linen in toclean:
                candidates=[slot for slot in available if slot[1]>=minutes]
                slot=max(candidates,key=lambda s:s[1]) if candidates else None
                eid=slot[0]['employee_id'] if slot else ''
                if slot:slot[1]-=minutes;slot[2]+=minutes
                else:agency+=minutes;agency_tasks+=1
                tid=ds.ident('HKT');laundry_unit=390 if d<date(2026,5,1) else 435
                laundry=linen*laundry_unit;consumable=(145 if typ=='stayover' else 260 if typ=='weekly_stayover' else 390);consumable=mul(consumable,1.12 if d>=date(2026,6,1) else 1)
                agency_cost=mul(minutes, (3450 if d>=date(2026,6,1) else 3100)/60) if not slot else 0
                row=ds.add('operations/housekeeping_tasks','task_id','One approved completed cleaning task, linked to actual stay/departure',task_id=tid,property_id=p,room_id=r['assigned_room_id'],reservation_id=r['reservation_id'],service_date=iso(d),task_type=typ,employee_id=eid,contractor_vendor_id='' if slot else 'VEN-AGENCY',planned_minutes=minutes,approved_work_minutes=minutes,actual_completed_date=iso(d),linen_sets=linen,laundry_cost_usd=laundry,consumables_cost_usd=consumable,agency_cost_usd=agency_cost,status='approved_completed',cost_posting_policy='bill/payroll supporting detail; do not add twice')
                tasksbyday[(p,d)].append(row);costs[(p,iso(d)[:7])]['laundry']+=laundry;costs[(p,iso(d)[:7])]['consumables']+=consumable;costs[(p,iso(d)[:7])]['agency']+=agency_cost
                if eid:task_minutes[(eid,d)]+=minutes
                ds.add('operations/linen_logs','linen_log_id','One approved linen/laundry usage log per cleaning task',linen_log_id=ds.ident('LIN'),task_id=tid,property_id=p,service_date=iso(d),linen_sets=linen,unit_laundry_cost_usd=laundry_unit,total_laundry_usd=laundry,vendor_id='VEN-LAUNDRY')
            if agency:
                ds.add('operations/agency_shifts','agency_shift_id','One approved property/day agency support shift',agency_shift_id=ds.ident('AGS'),property_id=p,work_date=iso(d),vendor_id='VEN-AGENCY',approved_minutes=agency,rooms_serviced=agency_tasks,approved_cost_usd=sum(t['agency_cost_usd'] for t in tasksbyday[(p,d)]),worker_count=(agency+419)//420)
        for e in employees:
            p=e['home_property_id'];on=((d-START).days+e['_index'])%7<5
            shortage=p=='WIL' and e['role']=='housekeeper' and date(2026,6,15)<=d<=date(2026,8,31) and e['_role_index']<3
            planned=480 if on else 0
            if not planned and not task_minutes[(e['employee_id'],d)]:continue
            actual=0 if shortage else 420 if e['role']=='housekeeper' else 480
            if not on:actual=task_minutes[(e['employee_id'],d)]
            # A subset of desk/maintenance staff covers summer extended shifts and earns weekly overtime.
            if actual and e['pay_type']=='hourly' and e['role']!='housekeeper' and d.month in [6,7,8] and e['_index']%2==0:actual+=90
            eid=e['employee_id'];week=d-timedelta(days=d.weekday());wk=(eid,week)
            regular=min(actual,max(0,2400-weekly[wk]));overtime=actual-regular;weekly[wk]+=actual
            comp=f'{eid}-'+('V2' if d>=date(2026,6,1) else 'V1')
            ds.add('gusto/work_schedules','schedule_id','One planned employee workday; absence tracked in actual hours',schedule_id=f'SCH-{eid}-{iso(d)}',employee_id=eid,property_id=p,work_date=iso(d),planned_minutes=planned,planned_role=e['role'])
            row=ds.add('gusto/time_entries','time_entry_id','One approved employee workday; overtime assigned over 40 hours in Monday week',time_entry_id=f'TIM-{eid}-{iso(d)}',employee_id=eid,property_id=p,work_date=iso(d),week_start_date=iso(week),regular_minutes=regular if e['pay_type']=='hourly' else actual,overtime_minutes=overtime if e['pay_type']=='hourly' else 0,total_minutes=actual,approved_housekeeping_minutes=task_minutes[(eid,d)],absence_minutes=planned if shortage else 0,compensation_id=comp,approval_status='approved')
            period=f'{d:%Y-%m}-'+('H1' if d.day<=15 else 'H2');time_by_eid_period[(eid,period)].append(row)
    rates={r['compensation_id']:r for r in ds.tables['gusto/compensation_history']}
    for d in months():
        for half in [1,2]:
            end=d.replace(day=15) if half==1 else month_end(d);beg=d if half==1 else d.replace(day=16);period=f'{d:%Y-%m}-H{half}';run=ds.ident('PRN');details=[]
            for e in employees:
                eid=e['employee_id'];rr=time_by_eid_period[(eid,period)]
                regular=sum(x['regular_minutes'] for x in rr);ot=sum(x['overtime_minutes'] for x in rr);gross=0
                if e['pay_type']=='salary':gross=mul(rates[f'{eid}-'+('V2' if end>=date(2026,6,1) else 'V1')]['annual_salary_usd'],Decimal(1)/24)
                else:
                    gross=sum(mul(rates[x['compensation_id']]['hourly_rate_usd'],Decimal(x['regular_minutes'])/60)+mul(rates[x['compensation_id']]['hourly_rate_usd'],Decimal(x['overtime_minutes'])/60*Decimal('1.5')) for x in rr)
                wh=mul(gross,.18 if e['pay_type']=='hourly' else .23);employer=mul(gross,.083);benefit=17500 if gross else 0
                net=gross-wh;cost=gross+employer+benefit;p=e['home_property_id'];acc='5100' if e['role']=='housekeeper' else '5120' if p=='CORP' else '5110'
                pid=ds.ident('PDL')
                row=ds.add('gusto/payroll_details','payroll_detail_id','One employee semi-monthly gross-to-net earned payroll line',payroll_detail_id=pid,payroll_run_id=run,employee_id=eid,property_id=p,period_id=period,regular_minutes=regular,overtime_minutes=ot,gross_pay_usd=gross,employee_withholding_usd=wh,net_pay_usd=net,employer_tax_usd=employer,employer_benefit_usd=benefit,total_employer_cost_usd=cost,wage_account_code=acc)
                details.append(row)
                ds.post(end,'gusto','payroll_details',pid,[(p,acc,gross),(p,'5130',employer),(p,'5140',benefit),(p,'2300',-net),(p,'2310',-(wh+employer+benefit))],'earned payroll')
            fund=plus_business(end,2)
            ds.add('gusto/payroll_runs','payroll_run_id','One earned semi-monthly payroll; funding may be after cutoff',payroll_run_id=run,period_start_date=iso(beg),period_end_date=iso(end),earned_date=iso(end),scheduled_funding_date=iso(fund),actual_funding_date=iso(fund) if fund<=CUT else '',gross_pay_usd=sum(x['gross_pay_usd'] for x in details),net_pay_usd=sum(x['net_pay_usd'] for x in details),withholding_usd=sum(x['employee_withholding_usd'] for x in details),employer_tax_usd=sum(x['employer_tax_usd'] for x in details),employer_benefit_usd=sum(x['employer_benefit_usd'] for x in details),total_employer_cost_usd=sum(x['total_employer_cost_usd'] for x in details),status='funded' if fund<=CUT else 'earned_unfunded')
            for p in CENTRES:
                pp=[x for x in details if x['property_id']==p]
                for typ,acc,amount in [('net_wages','2300',sum(x['net_pay_usd'] for x in pp)),('withholdings_employer_benefits','2310',sum(x['employee_withholding_usd']+x['employer_tax_usd']+x['employer_benefit_usd'] for x in pp))]:
                    fid=ds.ident('PFD');bid=ds.cash(fund,p,-amount,'payroll_funding',fid,acc,'gusto','funding')
                    ds.add('gusto/funding','funding_id','One payroll/property funding component or known unpaid obligation',funding_id=fid,payroll_run_id=run,property_id=p,funding_type=typ,payable_account_code=acc,due_date=iso(fund),actual_payment_date=iso(fund) if bid else '',amount_usd=amount,open_payable_usd=amount if not bid else 0,bank_transaction_id=bid)
    # Service cost invoices, derived from approved operations logs (not additional cost).
    for (p,mo),cost in sorted(costs.items()):
        end=month_end(date.fromisoformat(mo+'-01'))
        for label,v,acc in [('laundry','VEN-LAUNDRY','5200'),('consumables','VEN-SUPPLY','5210'),('agency','VEN-AGENCY','5150')]:
            amount=cost[label]
            if not amount:continue
            bill=add_bill(ds,p,v,end,[(acc,amount,1,amount,'operations/housekeeping_tasks',f'{p}-{mo}')],label,f'OPS-{p}-{mo}-{label}',True)
            ds.add('operations/cost_bill_links','cost_link_id','One property/month operational cost category to accounting bill',cost_link_id=ds.ident('OCB'),property_id=p,service_month=mo,cost_type=label,approved_cost_usd=amount,bill_id=bill['bill_id'],account_code=acc)
    for e in employees:
        for k in [k for k in e if k.startswith('_')]:del e[k]

def build_operating_bills_marketing(ds):
    recurring=[]
    for p in PROPS:
        for kind,v,acc,amount,driver in [('rent','VEN-RENT','5320',0 if p=='RAL' else 2600000 if p=='WIL' else 2400000,'fixed_monthly'),('insurance_property_charges','VEN-INS','5330',1650000 if p=='RAL' else 580000 if p=='WIL' else 480000,'fixed_monthly'),('overnight_security_pms_services','VEN-SERVICE','5340',920000 if p!='DUR' else 620000,'fixed_monthly')]:
            if not amount:continue
            cid=f'RC-{p}-{acc}'
            recurring.append((p,kind,v,acc,amount,cid))
            ds.add('planning/recurring_contracts','recurring_contract_id','One active recurring cost agreement; future cycles exclude existing AP bill',recurring_contract_id=cid,property_id=p,vendor_id=v,account_code=acc,effective_from='2024-10-01',effective_through='2027-12-31',frequency='monthly',base_monthly_usd=amount,next_service_month='2026-11',next_due_date='2026-11-01' if kind=='rent' else '2026-12-20' if acc=='5330' else '2026-12-30',escalation_from='2026-01-01' if kind=='rent' else '',escalation_rate=.03 if kind=='rent' else 0.0,existing_october_bill_id='',forecast_overlap_key=f'{p}|{acc}|service_month')
    recurring.append(('CORP','software_advisory','VEN-SOFTWARE','5500',1050000,'RC-CORP-5500'))
    ds.add('planning/recurring_contracts','recurring_contract_id','One active recurring cost agreement; future cycles exclude existing AP bill',recurring_contract_id='RC-CORP-5500',property_id='CORP',vendor_id='VEN-SOFTWARE',account_code='5500',effective_from='2024-10-01',effective_through='2027-12-31',frequency='monthly',base_monthly_usd=1050000,next_service_month='2026-11',next_due_date='2026-12-30',escalation_from='',escalation_rate=0.0,existing_october_bill_id='',forecast_overlap_key='CORP|5500|service_month')
    for d in months():
        end=month_end(d);mo=d.strftime('%Y-%m')
        for p,kind,v,acc,amount,cid in recurring:
            if acc=='5320' and d>=date(2026,1,1): amount=mul(amount,1.03)
            due=d if acc=='5320' else end+timedelta(days=20 if acc=='5330' else 30)
            bill=add_bill(ds,p,v,d if acc=='5320' else end,[(acc,amount,1,amount,'planning/recurring_contracts',cid)],kind,cid,due=due)
            if mo=='2026-10':
                for r in ds.tables['planning/recurring_contracts']:
                    if r['recurring_contract_id']==cid:r['existing_october_bill_id']=bill['bill_id']
        for p in PROPS:
            seasonal=1.0+(.24 if d.month in [6,7,8] else .1 if d.month in [1,2] else 0)
            utilities=mul(640000 if p=='RAL' else 720000 if p=='WIL' else 610000,seasonal*(1.24 if d>=date(2026,6,1) else 1))
            add_bill(ds,p,'VEN-UTIL',end,[('5310',utilities,1,utilities,'operations/utility_readings',f'{p}-{mo}')],'utilities',f'UTILITY-{p}-{mo}')
            ds.add('operations/utility_readings','property_id,service_month','One synthetic property monthly consumption/billing detail',property_id=p,service_month=mo,kwh=round(utilities/15.5),water_kgal=round(COUNTS[p]*.8,2),billed_cost_usd=utilities,cost_assumption='blended synthetic consumption and fixed charges; not a current tariff')
            work=[w for w in ds.tables['operations/work_orders'] if w['property_id']==p and w['actual_completed_date'][:7]==mo and not w['capitalized']]
            maintenance=mul(280000 if p=='RAL' else 310000 if p=='WIL' else 220000,1.35 if d>=date(2026,6,1) else 1)+sum(w['approved_cost_usd'] for w in work)
            bill=add_bill(ds,p,'VEN-MAINT',end,[('5300',maintenance,1,maintenance,'operations/work_orders',f'{p}-{mo}')],'routine_maintenance',f'MAINT-{p}-{mo}',True)
            ds.add('operations/maintenance_cost_links','maintenance_cost_id','One property/month maintenance invoice supporting work orders and preventive base',maintenance_cost_id=ds.ident('MCL'),property_id=p,service_month=mo,work_orders_cost_usd=sum(w['approved_cost_usd'] for w in work),preventive_base_usd=maintenance-sum(w['approved_cost_usd'] for w in work),total_expense_usd=maintenance,bill_id=bill['bill_id'])
            breakfast=sum(c['net_revenue_usd'] for c in ds.tables['night_audit/folio_lines'] if c['property_id']==p and c['service_date'][:7]==mo and c['charge_type']=='breakfast')
            if breakfast:
                amount=mul(breakfast,.39);add_bill(ds,p,'VEN-FOOD',end,[('5220',amount,1,amount,'night_audit/folio_lines',f'{p}-{mo}-breakfast')],'breakfast_food',purchase=True)
    # Marketing separate from OTA distribution; daily campaign costs map to a single monthly bill.
    for platform,v in [('META','VEN-META'),('GOOGLE','VEN-GOOGLE')]:
        for p in PROPS:
            camp=f'{platform}-{p}-DIRECT'
            ds.add('marketing/campaigns','campaign_id','One property/platform own direct-booking campaign',campaign_id=camp,platform=platform,property_id=p,campaign_name=f'Juniper Quay {p} direct demand',active_from=iso(START),active_through=iso(CUT),objective='direct_bookings')
            for d in days():
                base=3700 if platform=='META' else 5800
                spend=mul(base,(.8 if p=='DUR' else 1.15 if p=='WIL' else 1)*(1.28 if d>=date(2026,6,1) else 1)*(1.18 if d.weekday() in [4,5] else 1))+(d.day%7)*19
                clicks=max(1,spend//(125 if platform=='META' else 185));impressions=clicks*(36 if platform=='META' else 15);conv=round(clicks*.037,3)
                ds.add('marketing/daily_campaigns','campaign_id,metric_date','One campaign/day cost and overlapping platform attribution',campaign_id=camp,property_id=p,platform=platform,metric_date=iso(d),impressions=impressions,clicks=clicks,spend_usd=spend,cost_micros=spend*10000,attributed_bookings=conv,attributed_booking_value_usd=mul(42000,conv),attribution_policy='7-day click/1-day view synthetic; platforms overlap; quoted value not recognized revenue')
    for mo in [d.strftime('%Y-%m') for d in months()]:
        for p in PROPS:
            for platform,v in [('META','VEN-META'),('GOOGLE','VEN-GOOGLE')]:
                rr=[r for r in ds.tables['marketing/daily_campaigns'] if r['property_id']==p and r['platform']==platform and r['metric_date'][:7]==mo];amt=sum(r['spend_usd'] for r in rr);end=month_end(date.fromisoformat(mo+'-01'))
                bill=add_bill(ds,p,v,end,[('5400',amt,1,amt,'marketing/daily_campaigns',f'{platform}-{p}-{mo}')],'own_advertising')
                ds.add('marketing/billing','billing_id','One platform/property/month advertising bill, same expense as daily spend',billing_id=ds.ident('ADB'),platform=platform,property_id=p,service_month=mo,spend_usd=amt,bill_id=bill['bill_id'])
    bookdaily=Counter((r['property_id'],r['booked_date']) for r in ds.res if r['channel_id']=='DIRECT')
    for d in days():
        for p in PROPS:
            booked=bookdaily[(p,iso(d))];sessions=190+booked*24+(d.day%13)*7;searches=round(sessions*.48);starts=max(booked,round(searches*.17))
            ds.add('marketing/direct_funnel','property_id,metric_date','One own booking engine property/day funnel; bookings include later cancellations',property_id=p,metric_date=iso(d),sessions=sessions,availability_searches=searches,checkout_starts=starts,confirmed_reservations=booked,recognized_revenue_usd=0,measurement_note='confirmation date funnel; zero recognized revenue by definition; use folio service dates')

def build_assets_debt(ds):
    opening=[('AST-RAL-BLD','RAL','1500',520000000,52000000,390,'building'),('AST-RAL-FF','RAL','1510',110000000,33000000,120,'equipment'),('AST-WIL-FF','WIL','1510',145000000,43500000,120,'leasehold_fitout'),('AST-DUR-FF','DUR','1510',135000000,40500000,120,'leasehold_fitout')]
    assets=[]
    for aid,p,acc,cost,accum,life,kind in opening:
        assets.append(dict(asset_id=aid,property_id=p,asset_class=kind,cost_account_code=acc,acquisition_date='2021-04-01',in_service_date='2021-04-01',gross_cost_usd=cost,opening_accum_depreciation_usd=accum,useful_life_months=life,residual_value_usd=0,source_bill_id='',is_opening_asset=True))
    # Refurbishment 8 rooms; contractor stages separate cost, delivered asset placed in service after closure.
    for p,d,cost,life,kind in [('WIL',date(2026,3,16),6400000,84,'room_refurbishment'),('RAL',date(2025,5,15),1850000,60,'laundry_equipment'),('DUR',date(2026,10,20),3200000,84,'kitchenette_equipment')]:
        aid=ds.ident('AST');bill=add_bill(ds,p,'VEN-CAPEX',d,[('1510',cost,1,cost,'fixed_assets_finance/assets',aid)],kind,purchase=True)
        assets.append(dict(asset_id=aid,property_id=p,asset_class=kind,cost_account_code='1510',acquisition_date=iso(d),in_service_date=iso(d),gross_cost_usd=cost,opening_accum_depreciation_usd=0,useful_life_months=life,residual_value_usd=0,source_bill_id=bill['bill_id'],is_opening_asset=False))
    for a in assets:
        ds.add('fixed_assets_finance/assets','asset_id','One owned capitalized asset or opening asset pool',**a)
        remaining=a['gross_cost_usd']-a['opening_accum_depreciation_usd'];dep=mul(a['gross_cost_usd'],Decimal(1)/a['useful_life_months']);balance=a['opening_accum_depreciation_usd']
        for d in months():
            # Full monthly depreciation starts month after placed-in-service for new assets.
            if not a['is_opening_asset'] and d.strftime('%Y-%m')<=a['in_service_date'][:7]:continue
            amt=min(remaining,dep);remaining-=amt;balance+=amt;did=ds.ident('DEP')
            ds.add('fixed_assets_finance/depreciation','depreciation_id','One asset/month depreciation with carrying amount',depreciation_id=did,asset_id=a['asset_id'],property_id=a['property_id'],service_month=d.strftime('%Y-%m'),depreciation_usd=amt,accumulated_depreciation_usd=balance,closing_net_book_value_usd=a['gross_cost_usd']-balance)
            ds.post(month_end(d),'fixed_assets_finance','depreciation',did,[(a['property_id'],'5600',amt),(a['property_id'],'1590',-amt)],'monthly straight line depreciation')
    ds.add('fixed_assets_finance/debt_facilities','facility_id','One synthetic debt contract; principal separate from interest',facility_id='TERM-01',property_id='RAL',opening_principal_usd=310000000,annual_interest_rate=.0675,monthly_principal_usd=700000,maturity_date='2033-10-31',security='owned Raleigh real estate',currency='USD')
    principal=310000000
    for d in months(START,FUT):
        interest=mul(principal,.0675/12);repay=min(principal,700000);due=business(d.replace(day=25));did=ds.ident('DBT');actual=due<=CUT
        if actual:
            ds.post(due,'fixed_assets_finance','debt_schedule',did,[('RAL','5700',interest),('RAL','2400',repay),('RAL','1000',-repay-interest)],'contractual principal and interest paid')
            bid=ds.ident('BNK');ds.bank_events.append(dict(bank_transaction_id=bid,posted_date=iso(due),property_id='RAL',signed_amount_usd=-repay-interest,transaction_type='debt_service',source_system='fixed_assets_finance',source_id=did,memo='principal plus interest'))
        else:bid=''
        principal-=repay
        ds.add('fixed_assets_finance/debt_schedule','debt_payment_id','One contractual monthly debt obligation; future schedule is not actual cash',debt_payment_id=did,facility_id='TERM-01',property_id='RAL',due_date=iso(due),actual_payment_date=iso(due) if actual else '',opening_principal_usd=principal+repay,principal_usd=repay,interest_usd=interest,total_usd=repay+interest,scheduled_closing_principal_usd=principal,bank_transaction_id=bid,status='paid' if actual else 'scheduled')
    # Known capex commitment, no future receiving/bill/cash event invented.
    po='PO-FUTURE-REFIT';amount=11000000
    ds.add('procurement/purchase_orders','purchase_order_id','One approved vendor order; commitments differ from bills and cash',purchase_order_id=po,property_id='DUR',vendor_id='VEN-CAPEX',approved_date='2026-10-18',expected_receipt_date='2026-12-07',ordered_total_usd=amount,received_total_usd=0,unreceived_commitment_usd=amount,status='approved_open',contract_id='CAPEX-DUR-27')
    ds.add('procurement/purchase_order_lines','purchase_order_line_id','One ordered item/service line',purchase_order_line_id='POL-FUTURE-REFIT',purchase_order_id=po,description='Additional kitchenette renewal',quantity=11,unit_cost_usd=1000000,ordered_value_usd=amount,received_value_usd=0,open_value_usd=amount,account_code='1510')
    for j,share,due in [(1,.3,'2026-11-09'),(2,.7,'2026-12-21')]:
        ds.add('planning/capex_commitments','commitment_id','One unreceived PO payment installment; exclude once billed/paid',commitment_id=f'CAP-COM-{j}',purchase_order_id=po,property_id='DUR',vendor_id='VEN-CAPEX',due_date=due,expected_receipt_date='2026-12-07',committed_usd=mul(amount,share),paid_usd=0,open_commitment_usd=mul(amount,share),existing_bill_id='',is_actual=False)

def pay_bills_taxes_opening(ds):
    for b in ds.tables['quickbooks/bills']:
        due=date.fromisoformat(b['due_date']);delay=10 if b['bill_type'] in ['utilities','routine_maintenance'] and b['service_month']>='2026-08' else 0
        total=b['total_usd'];first=mul(total,.6) if int(b['bill_id'][-3:])%9==0 else total
        schedules=[(first,business(due+timedelta(days=delay)))]
        if first<total:schedules.append((total-first,business(due+timedelta(days=delay+13))))
        for amt,d in schedules:
            if d>CUT:continue
            pid=ds.ident('VPM');bid=ds.cash(d,b['property_id'],-amt,'vendor_payment',pid,'2000','quickbooks','bill_payments')
            ds.add('quickbooks/bill_payments','bill_payment_id','One actual vendor bank payment',bill_payment_id=pid,vendor_id=b['vendor_id'],property_id=b['property_id'],payment_date=iso(d),amount_usd=amt,bank_transaction_id=bid)
            ds.add('quickbooks/bill_payment_applications','application_id','One actual vendor payment application to AP bill',application_id=ds.ident('BPA'),bill_payment_id=pid,bill_id=b['bill_id'],application_date=iso(d),amount_usd=amt);b['paid_usd']+=amt;b['open_ap_usd']-=amt
        b['expected_payment_date']=iso(next((d for amt,d in schedules if d>CUT),business(due+timedelta(days=delay)))) if b['open_ap_usd'] else ''
    taxes=defaultdict(int)
    for c in ds.tables['night_audit/folio_lines']:
        if c['tax_account_code']=='2100':taxes[(c['property_id'],c['service_date'][:7])]+=c['tax_usd']
    for (p,mo),amt in sorted(taxes.items()):
        d=next_month(date.fromisoformat(mo+'-01')).replace(day=20);tid=ds.ident('TAX');pay=business(d);bid=ds.cash(pay,p,-amt,'lodging_tax_remittance',tid,'2100','fixed_assets_finance','tax_remittances')
        ds.add('fixed_assets_finance/tax_remittances','tax_remittance_id','One hotel-collected lodging tax period and actual/scheduled remittance',tax_remittance_id=tid,property_id=p,tax_account_code='2100',service_month=mo,due_date=iso(d),scheduled_payment_date=iso(pay),actual_payment_date=iso(pay) if bid else '',net_tax_collected_usd=amt,paid_usd=amt if bid else 0,open_tax_usd=0 if bid else amt,bank_transaction_id=bid,case_policy='synthetic remittance dates and rates, not statutory guidance')
    # Opening assets/debt/equity are not period journals.
    opening=defaultdict(int)
    for p,cash in [('RAL',25000000),('WIL',17500000),('DUR',12500000),('CORP',10000000)]:opening[(p,'1000')]=cash
    for a in ds.tables['fixed_assets_finance/assets']:
        if a['is_opening_asset']:
            opening[(a['property_id'],a['cost_account_code'])]+=a['gross_cost_usd'];opening[(a['property_id'],'1590')]-=a['opening_accum_depreciation_usd']
    opening[('RAL','2400')]=-310000000
    for p in CENTRES:opening[(p,'3000')]=-sum(v for (pp,acc),v in opening.items() if pp==p)
    ds.opening=opening
    for (p,acc),v in sorted(opening.items()):
        ds.add('quickbooks/opening_trial_balance','property_id,account_code','One opening account/property signed debit-minus-credit balance; outside period',as_of_date='2024-10-31',property_id=p,account_code=acc,debit_usd=max(v,0),credit_usd=max(-v,0),signed_balance_usd=v)
    # Member distributions after measuring liquidity in chronological order; predeclared limited policy.
    for d in [date(2025,10,15),date(2026,4,15),date(2026,10,15)]:
        cash=65000000+sum(x['signed_amount_usd'] for x in ds.bank_events if x['posted_date']<=iso(d))
        amount=min(25000000,max(0,cash-85000000))
        if amount:
            did=ds.ident('DIST');bid=ds.cash(d,'CORP',-amount,'member_distribution',did,'3100','fixed_assets_finance','member_distributions')
            ds.add('fixed_assets_finance/member_distributions','distribution_id','One equity distribution, not operating expense',distribution_id=did,payment_date=iso(d),property_id='CORP',amount_usd=amount,bank_transaction_id=bid)
    # Stable bank posting sequence supplies a reproducible running balance.
    bal=65000000
    for seq,b in enumerate(sorted(ds.bank_events,key=lambda x:(x['posted_date'],x['bank_transaction_id'])),1):
        bal+=b['signed_amount_usd']
        ds.add('bank/statement','bank_transaction_id','One actually posted bank transaction in one consolidated USD operating account',**b,bank_account_id='BANK-JQ-1042',sequence=seq,credit_usd=max(b['signed_amount_usd'],0),debit_usd=max(-b['signed_amount_usd'],0),running_balance_usd=bal,currency='USD')
    for d in months():
        end=iso(month_end(d));beg=iso(d);prior=65000000+sum(b['signed_amount_usd'] for b in ds.bank_events if b['posted_date']<beg);rr=[b for b in ds.bank_events if beg<=b['posted_date']<=end]
        ds.add('bank/monthly_balances','bank_account_id,service_month','One monthly independent statement opening/flows/closing',bank_account_id='BANK-JQ-1042',service_month=d.strftime('%Y-%m'),opening_balance_usd=prior,credits_usd=sum(max(b['signed_amount_usd'],0) for b in rr),debits_usd=sum(max(-b['signed_amount_usd'],0) for b in rr),closing_balance_usd=prior+sum(b['signed_amount_usd'] for b in rr))

def build_trial_balance_allocations(ds):
    activity=defaultdict(lambda:[0,0])
    for g in ds.tables['quickbooks/general_ledger']:
        v=activity[(g['accounting_date'][:7],g['property_id'],g['account_code'])];v[0]+=g['debit_usd'];v[1]+=g['credit_usd']
    running=defaultdict(int,ds.opening)
    for d in months():
        mo=d.strftime('%Y-%m')
        for p in CENTRES:
            for acc,name,typ,grp in ACCOUNTS:
                beg=running[(p,acc)];deb,cred=activity[(mo,p,acc)];closing=beg+deb-cred;running[(p,acc)]=closing
                ds.add('quickbooks/monthly_trial_balance','service_month,property_id,account_code','One monthly GL account/property rollforward; P&L balances not reset yearly',service_month=mo,property_id=p,account_code=acc,opening_signed_usd=beg,period_debit_usd=deb,period_credit_usd=cred,closing_signed_usd=closing)
        # Allocation bridge never enters the statutory GL or consolidated expense twice.
        for acc,n,t,g in ACCOUNTS:
            amt=activity[(mo,'CORP',acc)][0]-activity[(mo,'CORP',acc)][1]
            if t!='expense' or not amt:continue
            shares=split_cents(amt,[60,52,44]);aid=ds.ident('ALC')
            for p,val in [('CORP',-amt)]+list(zip(PROPS,shares)):
                ds.add('planning/shared_cost_allocations','allocation_id,property_id','One analytical allocation bridge line; group sum zero; no GL reposting',allocation_id=aid,service_month=mo,property_id=p,account_code=acc,driver='physical_keys_60_52_44',driver_units=COUNTS[p] if p in COUNTS else -156,allocated_expense_usd=val,source_cost_usd=amt,consolidated_increment_usd=0)
    ds.closing=running
