"""Financial event derivation and double-entry posting for the synthetic agency."""
from build_dataset import *

OPEN = {}
BANK_BAL = 0

def payroll():
    # Opening run is an already-earned liability, funded inside the observation window.
    periods=[(date(2024,10,16),date(2024,10,31),'opening_item')]
    for m in MONTHS: periods.extend([(m,date(m.year,m.month,15),'in_period'),(date(m.year,m.month,16),me(m),'in_period')])
    cap=defaultdict(list); logs=defaultdict(list)
    for r in T['timekeeping/daily_capacity']: cap[r['employee_id']].append(r)
    for r in T['timekeeping/timesheets']: logs[r['employee_id']].append(r)
    for a,b,scope in periods:
        run=f'PAY-{iso(b)}'; expected=nextbiz(b+timedelta(days=2)); actual=expected if expected<=CUT else ''
        earnings=[]
        for eid,e in EMP.items():
            if not active(e,a): continue
            c=comp_for(eid,a); gross=cents(c['annual_salary_usd']/24); held=cents(money(gross)*c['withholding_rate']); tax=cents(money(gross)*c['employer_tax_rate']); ben=cents(c['monthly_employer_benefit_usd']/2)
            er=add('gusto/payroll_earnings',payroll_earning_id=f'EARN-{iso(b)}-{eid}',payroll_run_id=run,employee_id=eid,compensation_id=c['compensation_id'],earned_start_date=a,earned_end_date=b,record_scope=scope,gross_pay_usd=money(gross),employee_withholding_usd=money(held),employer_tax_usd=money(tax),employer_benefit_usd=money(ben),net_pay_usd=money(gross-held),total_employer_cost_usd=money(gross+tax+ben),journal_id='')
            earnings.append(er); PAYE[er['payroll_earning_id']]=er
            if scope=='in_period':
                event(b,30,'payroll_earning',er)
                cc=[r for r in cap[eid] if a<=r['work_date']<=b]; totalhours=sum(dec(r['paid_capacity_hours']) for r in cc); basis=defaultdict(D)
                for r in logs[eid]:
                    if a<=r['work_date']<=b: basis[(r['project_id'],'project_delivery' if r['project_id']!='PRJ-INTERNAL' else ('corporate_overhead' if e['cost_class']=='overhead' else 'delivery_bench_and_internal'))]+=r['hours']
                pto=sum(dec(r['paid_time_off_hours']) for r in cc)
                if pto: basis[('PRJ-INTERNAL','paid_leave')]+=pto
                entries=list(basis.items()); amounts=alloc(gross+tax+ben,[v for _,v in entries])
                for ((pid,cat),hrs),amt in zip(entries,amounts):
                    p=PROJECTS[pid]
                    add('gusto/cost_allocations',cost_allocation_id=f'PCOST-{len(T["gusto/cost_allocations"])+1:06d}',payroll_earning_id=er['payroll_earning_id'],payroll_run_id=run,employee_id=eid,project_id=pid,client_id=p['client_id'],contract_id=p['contract_id'],service_month=month(b),allocation_category=cat,basis_hours=hrs,period_paid_hours=totalhours,allocated_employer_cost_usd=money(amt),is_additional_gl_expense=False)
        sums={f:sum(cents(e[f]) for e in earnings) for f in ['gross_pay_usd','employee_withholding_usd','employer_tax_usd','employer_benefit_usd','net_pay_usd','total_employer_cost_usd']}
        pr=add('gusto/payroll_runs',payroll_run_id=run,earned_start_date=a,earned_end_date=b,scheduled_funding_date=expected,actual_funding_date=actual,record_scope=scope,**{f:money(v) for f,v in sums.items()},funding_id=f'FUND-{iso(b)}' if actual else '')
        if actual: event(actual,35,'payroll_funding',pr)
        else: add('planning/payroll_commitments',payroll_commitment_id='PCOM-'+run,payroll_run_id=run,earned_end_date=b,scheduled_funding_date=expected,net_pay_usd=pr['net_pay_usd'],withholding_plus_employer_tax_usd=pr['employee_withholding_usd']+pr['employer_tax_usd'],benefits_usd=pr['employer_benefit_usd'],total_funding_usd=pr['total_employer_cost_usd'],overlap_liability_accounts='2100|2110|2120',as_of_date=CUT)

def contractors_and_vendors():
    supplier_data=[('RENT','Harbor Works Property LLC','rent',15),('SAAS','Lighthouse Workflow Software LLC','software',15),('PRO','Mesa Accounting Advisory LLC','professional_services',30),('TRAVEL','Field Route Travel Services LLC','travel',15),('TRAIN','Studio Learning Services LLC','training',15),('INS','Aspen Business Insurance LLC','insurance',15)]
    for code,name,typ,terms in supplier_data: add('quickbooks/vendors',vendor_id='VND-'+code,vendor_name=name,vendor_type=typ,email=code.lower()+'.billing@example.com',payment_terms_days=terms)
    names=['Dylan Ridge','Sasha Pine','Micah Clay','Ellis Cove','Arden Marsh','Remy Brook']; roles=['motion_designer','brand_designer','measurement_engineer','video_producer','copywriter','paid_search_specialist']; costs=[68,85,92,95,74,78]
    for i,(name,role,rate) in enumerate(zip(names,roles,costs),1):
        cf=f'FREE-{i:03d}'; vid=f'VND-FREE-{i:03d}'
        add('quickbooks/vendors',vendor_id=vid,vendor_name=name+' Studio LLC',vendor_type='freelancer',email=f'freelancer{i}@example.com',payment_terms_days=30)
        add('freelancers/contractors',contractor_id=cf,vendor_id=vid,contractor_name=name,email=f'freelancer{i}@example.com',role=role,status_asof='active',payment_terms_days=30)
        change=date(2026,8,1) if i==4 else date(2026,1,1) if i==2 else None
        for j,(a,b,r,reason) in enumerate([(date(2024,1,1),(change-timedelta(days=1)) if change else date(2027,12,31),rate,'original negotiated cost rate')]+([(change,date(2027,12,31),122 if i==4 else 92,'Video production specialist rate increase' if i==4 else 'Annual contractor repricing')] if change else []),1):
            add('freelancers/rate_history',contractor_rate_id=f'FRATE-{i:03d}-{j}',contractor_id=cf,effective_start_date=a,effective_end_date=b,hourly_cost_rate_usd=usd(r),approved_date=a-timedelta(days=21),reason=reason)
    for m in MONTHS:
        for i in range(1,7):
            cf=f'FREE-{i:03d}'; candidates=project_weights(m,'creative' if i in [1,2,4,5] else 'analytics',True)
            picks=[x[0] for x in RNG.choices(candidates,weights=[w for _,w in candidates],k=2)]
            if i==4 and m>=date(2026,4,1): picks[0]=PROJECTS[RET_MAP[('CLI-007',month(m))][1]]
            if i==2 and date(2026,4,1)<=m<=date(2026,9,1): picks[0]=PROJECTS[RET_MAP[('CLI-003',month(m))][1]]
            rate=next(r for r in T['freelancers/rate_history'] if r['contractor_id']==cf and r['effective_start_date']<=m<=r['effective_end_date'])
            approved=[]
            for j,p in enumerate(picks,1):
                hours=dec(28 if i==4 and j==1 and m>=date(2026,4,1) else 16+((i+m.month+j)%8)*2)
                wo=f'WO-{cf}-{month(m)}-{j}'; wid='WORK-'+wo; cost=usd(hours*rate['hourly_cost_rate_usd'])
                add('freelancers/work_orders',work_order_id=wo,contractor_id=cf,contract_id=p['contract_id'],project_id=p['project_id'],client_id=p['client_id'],service_month=month(m),approved_date=m-timedelta(days=2),budget_hours=hours,budget_cost_usd=cost,status_asof='accepted')
                er=add('freelancers/approved_work',approved_work_id=wid,work_order_id=wo,contractor_id=cf,contractor_rate_id=rate['contractor_rate_id'],project_id=p['project_id'],contract_id=p['contract_id'],client_id=p['client_id'],service_month=month(m),service_start_date=m,service_end_date=me(m),approved_date=me(m),approved_hours=hours,hourly_cost_rate_usd=rate['hourly_cost_rate_usd'],earned_cost_usd=cost,deliverable='Accepted monthly specialist production/measurement work',contractor_invoice_id='',journal_id='')
                approved.append(er); event(me(m),40,'contractor_earned',er)
            invdate=shift(m,1)+timedelta(days=2); due=invdate+timedelta(days=30)
            if invdate<=CUT:
                cinv=f'FINV-{cf}-{month(m)}'; bill='BILL-'+cinv
                add('freelancers/invoices',contractor_invoice_id=cinv,contractor_id=cf,invoice_date=invdate,due_date=due,service_month=month(m),invoice_total_usd=sum((a['earned_cost_usd'] for a in approved),D(0)),accounting_bill_id=bill,status_asof='received')
                for j,w in enumerate(approved,1):
                    w['contractor_invoice_id']=cinv
                    add('freelancers/invoice_lines',contractor_invoice_line_id=f'{cinv}-L{j}',contractor_invoice_id=cinv,approved_work_id=w['approved_work_id'],work_order_id=w['work_order_id'],line_amount_usd=w['earned_cost_usd'],accounting_bill_line_id=f'{bill}-L{j}')
                make_bill(bill,f'VND-FREE-{i:03d}',invdate,due,month(m),[(w['earned_cost_usd'],'2200','Previously accrued accepted freelance services',w['approved_work_id'],f'{cinv}-L{j}',w['project_id'],w['contract_id'],w['client_id']) for j,w in enumerate(approved,1)],cinv)
            else:
                for w in approved: add('planning/contractor_accruals',contractor_accrual_id='ACCR-'+w['approved_work_id'],approved_work_id=w['approved_work_id'],contractor_id=cf,project_id=w['project_id'],contract_id=w['contract_id'],earned_cost_usd=w['earned_cost_usd'],expected_invoice_date=invdate,expected_due_date=due,overlap_liability_account='2200',as_of_date=CUT)

def make_bill(bid,vid,billdate,due,mon,lines,cinv='',scope='in_period'):
    total=sum((x[0] for x in lines),D(0))
    r=add('quickbooks/vendor_bills',bill_id=bid,vendor_id=vid,contractor_invoice_id=cinv,bill_date=billdate,due_date=due,service_month=mon,bill_total_usd=total,record_scope=scope,bill_status_asof='',open_balance_usd='',journal_id='')
    for j,(amount,acct,desc,work,sline,pid,con,cid) in enumerate(lines,1): add('quickbooks/vendor_bill_lines',bill_line_id=f'{bid}-L{j}',bill_id=bid,account_id=acct,description=desc,line_amount_usd=amount,approved_work_id=work,source_line_id=sline,project_id=pid,contract_id=con,client_id=cid)
    if scope=='in_period': event(billdate,15,'vendor_bill',r)
    # Received bills are normally settled just after due, with a few deliberate partials.
    pay=nextbiz(due+timedelta(days=2 if vid.startswith('VND-FREE') else 0))
    if bid in ['BILL-FINV-FREE-004-2026-08','BILL-SAAS-2026-09']:
        parts=alloc(cents(total),[.5,.5]); plans=[(pay,parts[0]),(nextbiz(pay+timedelta(days=35)),parts[1])]
    else: plans=[(pay,cents(total))]
    for j,(pdate,amt) in enumerate(plans,1): event(pdate,25,'vendor_payment',dict(bill=r,amount=amt,payment_id=f'VPAY-{bid}-{j}'))
    return r

def operating_costs():
    for m in MONTHS:
        hc=sum(1 for e in EMP.values() if active(e,me(m)))
        costs=[('RENT','6100',6800 if m<date(2026,1,1) else 7250),('SAAS','6110',(7200+hc*95)*(1 if m<date(2026,1,1) else 1.12)),('PRO','6130',2250),('TRAVEL','6140',450+hc*32+(1800 if m.month in [3,6,9,11] else 0)),('TRAIN','6150',hc*48)]
        for code,acct,amount in costs:
            terms=30 if code=='PRO' else 15
            make_bill(f'BILL-{code}-{month(m)}','VND-'+code,me(m),me(m)+timedelta(days=terms),month(m),[(usd(amount),acct,f'{month(m)} agency {code.lower()} service','','','','','')])
        # Insurance is prepaid annually, then expensed over coverage months.
        source='OPEN-INS-2024' if m<date(2025,7,1) else 'BILL-INS-2025' if m<date(2026,7,1) else 'BILL-INS-2026'
        amt=500 if m<date(2025,7,1) else 550 if m<date(2026,7,1) else 600
        ar=add('finance/prepaid_amortization',amortization_id='AMORT-'+month(m),service_month=month(m),asset_account_id='1200',expense_account_id='6120',amount_usd=usd(amt),source_bill_id=source,journal_id='')
        event(me(m),45,'insurance_amortization',ar)
        event(me(m),46,'depreciation',dict(amount=200000,mon=month(m)))
        if m.month==7:
            amount=6600 if m.year==2025 else 7200
            make_bill(f'BILL-INS-{m.year}','VND-INS',m,m+timedelta(days=14),month(m),[(usd(amount),'1200','Annual business insurance prepaid policy','','','','','')])
    make_bill('OPEN-AP-FREE-001','VND-FREE-001',date(2024,10,20),date(2024,11,10),'2024-10',[(usd(11000),'2200','Pre-period freelance cost already expensed','','','','','')],scope='opening_item')
    make_bill('OPEN-AP-SAAS','VND-SAAS',date(2024,10,31),date(2024,11,15),'2024-10',[(usd(7000),'6110','Pre-period SaaS cost already expensed','','','','','')],scope='opening_item')

def invoicing():
    groups=defaultdict(list)
    for sid,s in SERVICES.items():
        co=CONTRACTS[s['contract_id']]; typ=s['service_type']; m=date.fromisoformat(s['service_month']+'-01')
        prepaid=False; opening_ar=False
        if typ=='retainer':
            _,_,t=RET_MAP[(s['client_id'],s['service_month'])]
            if s['client_id']=='CLI-002':
                offset=(m.year-co['service_start_date'].year)*12+m.month-co['service_start_date'].month
                q=offset//3; qstart=shift(co['service_start_date'],q*3); idate=shift(qstart,-1).replace(day=25); gid=f'INV-{co["contract_id"]}-Q{q+1}'
                if qstart==date(2026,11,1): idate=date(2026,10,15) # Signed renewal/prepaid Nov-Jan, paid before cutoff.
                prepaid=(co['service_start_date']==START and q==0)
            elif t['spend_fee_rate']:
                idate=shift(m,1)+timedelta(days=4); gid=f'INV-{co["contract_id"]}-{month(m)}'
            else:
                idate=m; gid=f'INV-{co["contract_id"]}-{month(m)}'
                if m==START and s['client_id'] in ['CLI-004','CLI-008','CLI-009']: idate=date(2024,10,25); opening_ar=True
            amount=s['approved_fee_usd'] if s['approved_fee_usd']!='' else s['agreed_minimum_fee_usd']
            known=t['known_asof_date'] if not t['spend_fee_rate'] or not s['actual_approved_date'] else s['actual_approved_date']
            basis='minimum_variable_upside_unknown' if not s['actual_approved_date'] and t['spend_fee_rate'] else 'earned_fee' if t['spend_fee_rate'] else 'signed_fixed_fee'
        elif typ=='fixed_milestone':
            # First modeled launch deposit is issued at window start, after its October SOW signing.
            seq=int(sid[-1]); idate=max(START,co['signed_date']) if seq==1 else (s['actual_approved_date'] or s['planned_approval_date'])+timedelta(days=10)
            gid=f'INV-{co["contract_id"]}-M{seq}'; amount=s['agreed_minimum_fee_usd']; known=co['signed_date']; basis='signed_milestone_fee'
        else:
            idate=shift(m,1)+timedelta(days=4); gid=f'INV-{co["contract_id"]}-{month(m)}'; amount=s['approved_fee_usd']; known=s['actual_approved_date']; basis='approved_hours_earned_fee'
        sched=add('contracts/billing_schedule',schedule_line_id='SCH-'+sid,planned_invoice_group_id=gid,contract_id=s['contract_id'],client_id=s['client_id'],service_id=sid,scheduled_invoice_date=idate,scheduled_due_date=idate+timedelta(days=co['payment_terms_days']),scheduled_amount_usd=amount,amount_basis=basis,known_date=known,actual_invoice_line_id='',status_asof='opening_prepaid' if prepaid else 'billed' if idate<=CUT else 'scheduled',as_of_date=CUT)
        if prepaid or opening_ar:
            add('delivery/opening_service_balances',opening_service_balance_id='OSB-'+sid,service_id=sid,contract_id=s['contract_id'],client_id=s['client_id'],balance_date=START-timedelta(days=1),deferred_revenue_usd=amount,unbilled_revenue_usd=usd(0),explanation='Paid quarterly retainer before window; pre-period cash is in opening bank' if prepaid else 'Prebilled November service, unpaid at opening; matching opening AR')
        if not prepaid: groups[gid].append((sched,s,opening_ar))
        if idate>CUT:
            add('planning/signed_future_commitments',commitment_id='COM-'+sid,schedule_line_id=sched['schedule_line_id'],contract_id=s['contract_id'],client_id=s['client_id'],service_id=sid,scheduled_invoice_date=idate,scheduled_due_date=sched['scheduled_due_date'],scheduled_amount_usd=amount,amount_basis=basis,overlap_key=sched['schedule_line_id'],as_of_date=CUT)
    add('delivery/opening_service_balances',opening_service_balance_id='OSB-SVC-OPEN-H-001',service_id='SVC-OPEN-H-001',contract_id='CON-H-001',client_id='CLI-001',balance_date=START-timedelta(days=1),deferred_revenue_usd=usd(0),unbilled_revenue_usd=usd(6000),explanation='Approved October analytics earned before window; invoiced on November 5')
    for gid,lines in groups.items():
        sch=lines[0][0]; idate=sch['scheduled_invoice_date']
        if idate>CUT: continue
        inv=add('quickbooks/client_invoices',invoice_id=gid,client_id=sch['client_id'],contract_id=sch['contract_id'],invoice_date=idate,due_date=sch['scheduled_due_date'],invoice_total_usd=sum((x[0]['scheduled_amount_usd'] for x in lines),D(0)),record_scope='opening_item' if lines[0][2] else 'in_period',invoice_status_asof='',open_balance_usd='',journal_id='')
        for j,(schedule,s,op) in enumerate(lines,1):
            line=add('quickbooks/client_invoice_lines',invoice_line_id=f'{gid}-L{j}',invoice_id=gid,contract_id=s['contract_id'],client_id=s['client_id'],service_id=s['service_id'],schedule_line_id=schedule['schedule_line_id'],description=s['service_type']+' '+s['service_month'],line_amount_usd=schedule['scheduled_amount_usd'],invoiced_to_deferred_usd=usd(0),invoiced_from_unbilled_usd=usd(0))
            schedule['actual_invoice_line_id']=line['invoice_line_id']
        if inv['record_scope']=='in_period': event(idate,10,'client_invoice',inv)
    # Fee credits are post-service concessions and reduce AR plus net recognized fees.
    credit_targets=[('CLI-003','2026-06',date(2026,7,12),2500,'Delivery credit for excessive revision cycles'),('CLI-004','2026-08',date(2026,9,15),1000,'Commercial concession during collection dispute')]
    for i,(cid,mon,dt,amount,reason) in enumerate(credit_targets,1):
        line=next(l for l in T['quickbooks/client_invoice_lines'] if l['client_id']==cid and SERVICES[l['service_id']]['service_type']=='retainer' and SERVICES[l['service_id']]['service_month']==mon)
        r=add('quickbooks/credit_notes',credit_note_id=f'CN-{i:03d}',client_id=cid,invoice_id=line['invoice_id'],invoice_line_id=line['invoice_line_id'],contract_id=line['contract_id'],service_id=line['service_id'],credit_date=dt,amount_usd=usd(amount),reason=reason,recognition_id=f'REV-CN-{i:03d}',journal_id='')
        event(dt,12,'credit_note',r)
    credits=defaultdict(int)
    for c in T['quickbooks/credit_notes']: credits[c['invoice_id']]+=cents(c['amount_usd'])
    for inv in T['quickbooks/client_invoices']:
        cid=inv['client_id']; total=cents(inv['invoice_total_usd'])-credits[inv['invoice_id']]; idate=inv['invoice_date']; due=inv['due_date']
        if cid=='CLI-002': planned=[(nextbiz(idate+timedelta(days=7)),total)]
        elif cid=='CLI-004' and idate>=date(2026,4,1):
            amts=alloc(total,[.35,.65]); planned=[(nextbiz(idate+timedelta(days=48)),amts[0]),(nextbiz(idate+timedelta(days=105)),amts[1])]
        elif inv['invoice_id'].startswith('INV-CON-R-003') and month(idate)=='2026-06': planned=[(date(2026,7,20),total)]
        elif cid in ['CLI-010','CLI-018']:
            amts=alloc(total,[.6,.4]); p=nextbiz(due+timedelta(days=RNG.randint(1,5))); planned=[(p,amts[0]),(nextbiz(p+timedelta(days=14)),amts[1])]
        else: planned=[(nextbiz(due+timedelta(days=RNG.randint(0,9))),total)]
        for j,(dt,amt) in enumerate(planned,1): event(dt,20,'client_receipt',dict(invoice=inv,amount=amt,receipt_id=f'RCPT-{inv["invoice_id"]}-{j}'))
    for sid,s in SERVICES.items():
        if s['actual_approved_date'] and s['record_scope']=='in_period': event(s['actual_approved_date'],50,'revenue',s)

def opening_and_chart():
    specs=[('1000','Operating bank','asset','BS','debit','cash'),('1100','Accounts receivable','asset','BS','debit','working_capital'),('1150','Unbilled earned fees','asset','BS','debit','working_capital'),('1200','Prepaid insurance','asset','BS','debit','working_capital'),('1500','Equipment at cost','asset','BS','debit','investing'),('1590','Accumulated depreciation','contra_asset','BS','credit','non_cash'),('2000','Accounts payable','liability','BS','credit','working_capital'),('2100','Payroll net payable','liability','BS','credit','working_capital'),('2110','Payroll withholding and employer tax payable','liability','BS','credit','working_capital'),('2120','Payroll benefits payable','liability','BS','credit','working_capital'),('2200','Accrued contractor services','liability','BS','credit','working_capital'),('2300','Deferred fee revenue','liability','BS','credit','working_capital'),('2500','Term loan','liability','BS','credit','financing'),('3000','Members equity and opening retained earnings','equity','BS','credit','financing'),('3100','Owner distributions','equity','BS','debit','financing'),('4000','Flat retainer fee revenue','revenue','PL','credit','operating'),('4010','Spend-based management fee revenue','revenue','PL','credit','operating'),('4020','Approved fixed-project fee revenue','revenue','PL','credit','operating'),('4030','Approved hourly service revenue','revenue','PL','credit','operating'),('4090','Fee concessions','contra_revenue','PL','debit','operating'),('5000','Delivery salaries','cost_of_services','PL','debit','operating'),('5001','Delivery employer payroll taxes','cost_of_services','PL','debit','operating'),('5002','Delivery employer benefits','cost_of_services','PL','debit','operating'),('5010','Accepted freelance delivery services','cost_of_services','PL','debit','operating'),('6000','Operations salaries','operating_expense','PL','debit','operating'),('6001','Operations employer payroll taxes','operating_expense','PL','debit','operating'),('6002','Operations employer benefits','operating_expense','PL','debit','operating'),('6100','Office rent','operating_expense','PL','debit','operating'),('6110','Agency SaaS','operating_expense','PL','debit','operating'),('6120','Business insurance','operating_expense','PL','debit','operating'),('6130','Accounting and professional fees','operating_expense','PL','debit','operating'),('6140','Travel and client meetings','operating_expense','PL','debit','operating'),('6150','Training','operating_expense','PL','debit','operating'),('6300','Depreciation','operating_expense','PL','debit','non_cash'),('6400','Debt interest','interest_expense','PL','debit','operating')]
    for aid,name,typ,fs,normal,cf in specs: add('quickbooks/chart_of_accounts',account_id=aid,account_name=name,account_type=typ,financial_statement=fs,normal_balance=normal,cash_flow_class=cf)
    openingpay=[p for p in T['gusto/payroll_runs'] if p['record_scope']=='opening_item'][0]
    balances={'1000':cents(380000),'1100':sum(cents(r['invoice_total_usd']) for r in T['quickbooks/client_invoices'] if r['record_scope']=='opening_item'),'1150':cents(6000),'1200':cents(4000),'1500':cents(120000),'1590':-cents(40000),'2000':-cents(18000),'2100':-cents(openingpay['net_pay_usd']),'2110':-cents(openingpay['employee_withholding_usd']+openingpay['employer_tax_usd']),'2120':-cents(openingpay['employer_benefit_usd']),'2300':-sum(cents(r['deferred_revenue_usd']) for r in T['delivery/opening_service_balances']),'2500':-cents(120000)}
    balances['3000']=-sum(balances.values()); OPEN.update({r['account_id']:balances.get(r['account_id'],0) for r in T['quickbooks/chart_of_accounts']})
    for aid,b in OPEN.items(): add('quickbooks/opening_trial_balance',account_id=aid,balance_date=START-timedelta(days=1),debit_usd=money(max(b,0)),credit_usd=money(max(-b,0)),signed_balance_usd=money(b),explanation='Opening balance only; already reflected in pre-period activity')
    add('bank/accounts',bank_account_id='BANK-OPERATING-1042',bank_name='Fictional Harbor Federal Bank',account_name='Signal Harbor operating USD',currency='USD',opening_balance_date=START-timedelta(days=1),opening_balance_usd=usd(380000))

def loan_and_distributions():
    principal=cents(120000)
    for m in MONTHS:
        interest=cents(money(principal)*D('.09')/12); p=cents(2500); principal-=p
        row=add('finance/debt_service',debt_service_id='DEBT-PAY-'+month(m),debt_id='DEBT-001',payment_date=date(m.year,m.month,25),principal_usd=money(p),interest_usd=money(interest),total_payment_usd=money(p+interest),closing_principal_usd=money(principal),bank_transaction_id='',journal_id='')
        event(row['payment_date'],32,'debt',row)
        if m.month in [1,4,7,10]: event(me(m),99,'distribution',dict(date=me(m)))
    add('finance/debt_register',debt_id='DEBT-001',lender_name='Fictional Harbor Federal Bank',agreement_date=date(2023,11,1),maturity_date=date(2028,10,25),original_principal_usd=usd(150000),opening_principal_usd=usd(120000),annual_interest_rate=D('.09'),monthly_principal_usd=usd(2500),principal_asof_usd=money(principal),is_synthetic_rate=True,as_of_date=CUT)
    m=date(2026,11,1)
    while principal>0:
        interest=cents(money(principal)*D('.09')/12); p=min(cents(2500),principal); principal-=p
        add('finance/debt_schedule',debt_schedule_id='DSCH-'+month(m),debt_id='DEBT-001',scheduled_payment_date=date(m.year,m.month,25),scheduled_principal_usd=money(p),scheduled_interest_usd=money(interest),scheduled_total_usd=money(p+interest),known_asof_date=CUT,status='contractual_future_not_actual'); m=shift(m,1)

def journal(dt,system,kind,sid,memo,lines,dims=None):
    dims=dims or {}; jid=f'JRN-{len(T["quickbooks/journals"])+1:06d}'; deb=sum(x[1] for x in lines); cred=sum(x[2] for x in lines)
    if deb!=cred: raise ValueError(('Unbalanced',kind,sid,deb,cred))
    add('quickbooks/journals',journal_id=jid,journal_date=dt,source_system=system,source_type=kind,source_id=sid,memo=memo,total_debit_usd=money(deb),total_credit_usd=money(cred))
    for acct,dr,cr in lines:
        if not dr and not cr: continue
        add('quickbooks/general_ledger',gl_line_id=f'GL-{len(T["quickbooks/general_ledger"])+1:07d}',journal_id=jid,journal_date=dt,account_id=acct,debit_usd=money(dr),credit_usd=money(cr),source_system=system,source_type=kind,source_id=sid,client_id=dims.get('client_id',''),contract_id=dims.get('contract_id',''),project_id=dims.get('project_id',''),employee_id=dims.get('employee_id',''),service_month=dims.get('service_month',month(dt)))
    return jid

def bank(dt,amount,kind,name,ref,jid):
    global BANK_BAL
    BANK_BAL+=amount; bid=f'BTX-{len(T["bank/transactions"])+1:06d}'
    add('bank/transactions',bank_transaction_id=bid,bank_account_id='BANK-OPERATING-1042',transaction_date=dt,sequence=len(T['bank/transactions'])+1,transaction_type=kind,counterparty=name,reference_type=kind,reference_id=ref,money_in_usd=money(max(amount,0)),money_out_usd=money(max(-amount,0)),signed_amount_usd=money(amount),running_balance_usd=money(BANK_BAL),journal_id=jid)
    return bid

def post_events():
    global BANK_BAL
    BANK_BAL=OPEN['1000']; pos=defaultdict(lambda:{'def':0,'unb':0}); invlines=defaultdict(list); billlines=defaultdict(list)
    for r in T['delivery/opening_service_balances']: pos[r['service_id']]={'def':cents(r['deferred_revenue_usd']),'unb':cents(r['unbilled_revenue_usd'])}
    for r in T['quickbooks/client_invoice_lines']: invlines[r['invoice_id']].append(r)
    for r in T['quickbooks/vendor_bill_lines']: billlines[r['bill_id']].append(r)
    for dt,priority,seq,kind,r in sorted(EVENTS,key=lambda e:e[:3]):
        if kind=='client_invoice':
            lines=[('1100',cents(r['invoice_total_usd']),0)]
            for l in invlines[r['invoice_id']]:
                p=pos[l['service_id']]; amt=cents(l['line_amount_usd']); unb=min(amt,p['unb']); deff=amt-unb; p['unb']-=unb; p['def']+=deff
                l['invoiced_from_unbilled_usd']=money(unb); l['invoiced_to_deferred_usd']=money(deff)
                lines.extend([('1150',0,unb),('2300',0,deff)])
            r['journal_id']=journal(dt,'quickbooks',kind,r['invoice_id'],'Fee billing, not direct revenue',lines,r)
        elif kind=='revenue':
            p=pos[r['service_id']]; amt=cents(r['approved_fee_usd']); deff=min(amt,p['def']); unb=amt-deff; p['def']-=deff; p['unb']+=unb
            acct='4020' if r['service_type']=='fixed_milestone' else '4030' if r['service_type']=='hourly' else '4010' if RET_MAP[(r['client_id'],r['service_month'])][2]['spend_fee_rate'] else '4000'
            rid='REV-'+r['service_id']; jid=journal(dt,'delivery',kind,rid,'Approved earned agency fee',[('2300',deff,0),('1150',unb,0),(acct,0,amt)],r)
            add('delivery/recognition_events',recognition_id=rid,service_id=r['service_id'],contract_id=r['contract_id'],client_id=r['client_id'],project_id=r['project_id'],recognition_date=dt,service_month=r['service_month'],recognition_type=r['service_type'],revenue_account_id=acct,recognized_fee_usd=money(amt),earned_from_deferred_usd=money(deff),earned_to_unbilled_usd=money(unb),credit_note_id='',journal_id=jid)
        elif kind=='credit_note':
            amt=cents(r['amount_usd']); s=SERVICES[r['service_id']]; jid=journal(dt,'quickbooks',kind,r['credit_note_id'],r['reason'],[('4090',amt,0),('1100',0,amt)],r); r['journal_id']=jid
            add('delivery/recognition_events',recognition_id=r['recognition_id'],service_id=r['service_id'],contract_id=r['contract_id'],client_id=r['client_id'],project_id=s['project_id'],recognition_date=dt,service_month=month(dt),recognition_type='fee_concession',revenue_account_id='4090',recognized_fee_usd=money(-amt),earned_from_deferred_usd=usd(0),earned_to_unbilled_usd=usd(0),credit_note_id=r['credit_note_id'],journal_id=jid)
        elif kind=='client_receipt':
            inv=r['invoice']; amt=r['amount']; rid=r['receipt_id']; jid=journal(dt,'quickbooks',kind,rid,'Client ACH applied to fee invoice',[('1000',amt,0),('1100',0,amt)],inv); bid=bank(dt,amt,'client_receipt',inv['client_id'],rid,jid)
            add('quickbooks/client_receipts',receipt_id=rid,client_id=inv['client_id'],receipt_date=dt,receipt_amount_usd=money(amt),payment_method='ACH',bank_transaction_id=bid,journal_id=jid)
            add('quickbooks/receipt_applications',receipt_application_id='APP-'+rid,receipt_id=rid,invoice_id=inv['invoice_id'],applied_date=dt,applied_amount_usd=money(amt))
        elif kind=='vendor_bill':
            amt=cents(r['bill_total_usd']); lines=[('2000',0,amt)]+[(l['account_id'],cents(l['line_amount_usd']),0) for l in billlines[r['bill_id']]]
            r['journal_id']=journal(dt,'quickbooks',kind,r['bill_id'],'Received supplier bill; freelance cost clears accrual',lines,{'service_month':r['service_month']})
        elif kind=='vendor_payment':
            bill=r['bill']; amt=r['amount']; pid=r['payment_id']; jid=journal(dt,'quickbooks',kind,pid,'Vendor ACH against bill',[('2000',amt,0),('1000',0,amt)]); bid=bank(dt,-amt,'vendor_payment',bill['vendor_id'],pid,jid)
            add('quickbooks/vendor_payments',vendor_payment_id=pid,vendor_id=bill['vendor_id'],payment_date=dt,payment_amount_usd=money(amt),bank_transaction_id=bid,journal_id=jid)
            add('quickbooks/vendor_payment_applications',vendor_application_id='VAPP-'+pid,vendor_payment_id=pid,bill_id=bill['bill_id'],applied_date=dt,applied_amount_usd=money(amt))
        elif kind=='payroll_earning':
            e=EMP[r['employee_id']]; pref='50' if e['cost_class']=='delivery' else '60'; g,h,t,b,n=[cents(r[f]) for f in ['gross_pay_usd','employee_withholding_usd','employer_tax_usd','employer_benefit_usd','net_pay_usd']]
            r['journal_id']=journal(dt,'gusto',kind,r['payroll_earning_id'],'Earned salary, withholding included in gross',[(pref+'00',g,0),(pref+'01',t,0),(pref+'02',b,0),('2100',0,n),('2110',0,h+t),('2120',0,b)],{'employee_id':r['employee_id']})
        elif kind=='payroll_funding':
            n,h,t,b,total=[cents(r[f]) for f in ['net_pay_usd','employee_withholding_usd','employer_tax_usd','employer_benefit_usd','total_employer_cost_usd']]; fid=r['funding_id']; jid=journal(dt,'gusto',kind,fid,'Payroll provider cash funding including tax and benefits',[('2100',n,0),('2110',h+t,0),('2120',b,0),('1000',0,total)]); bid=bank(dt,-total,'payroll_funding','Modeled payroll provider',fid,jid)
            add('gusto/payroll_funding',funding_id=fid,payroll_run_id=r['payroll_run_id'],funding_date=dt,net_pay_usd=money(n),employee_withholding_usd=money(h),employer_tax_usd=money(t),employer_benefit_usd=money(b),bank_debit_usd=money(total),bank_transaction_id=bid,journal_id=jid)
        elif kind=='contractor_earned':
            amt=cents(r['earned_cost_usd']); r['journal_id']=journal(dt,'freelancers',kind,r['approved_work_id'],'Accepted freelance delivery cost, accrued before invoice',[('5010',amt,0),('2200',0,amt)],r)
        elif kind=='insurance_amortization':
            amt=cents(r['amount_usd']); r['journal_id']=journal(dt,'finance',kind,r['amortization_id'],'Release prepaid insurance coverage',[('6120',amt,0),('1200',0,amt)])
        elif kind=='depreciation': journal(dt,'finance',kind,'DEP-'+r['mon'],'Straight-line equipment depreciation',[('6300',r['amount'],0),('1590',0,r['amount'])])
        elif kind=='debt':
            p,i=[cents(r[f]) for f in ['principal_usd','interest_usd']]; jid=journal(dt,'finance',kind,r['debt_service_id'],'Contractual principal and interest',[('2500',p,0),('6400',i,0),('1000',0,p+i)]); r['journal_id']=jid; r['bank_transaction_id']=bank(dt,-p-i,'debt_service','Fictional Harbor Federal Bank',r['debt_service_id'],jid)
        elif kind=='distribution':
            amt=max(0,min(cents(200000),BANK_BAL-cents(420000)))
            if amt:
                did='DIST-'+month(dt); jid=journal(dt,'finance',kind,did,'Quarterly owner distribution under cash reserve rule',[('3100',amt,0),('1000',0,amt)]); bid=bank(dt,-amt,'owner_distribution','Members',did,jid)
                add('finance/owner_distributions',distribution_id=did,distribution_date=dt,amount_usd=money(amt),bank_transaction_id=bid,journal_id=jid,policy='up_to_200000_quarterly_preserve_420000_cash_at_distribution_time')
        else: raise ValueError(kind)
    balance_schedules()

def balance_schedules():
    # Secondary views; the independent validator recomputes these from persisted sources.
    activity=defaultdict(lambda:[0,0])
    for g in T['quickbooks/general_ledger']:
        a=activity[(month(g['journal_date']),g['account_id'])]; a[0]+=cents(g['debit_usd']); a[1]+=cents(g['credit_usd'])
    bal=OPEN.copy(); bankopen=OPEN['1000']
    for m in MONTHS:
        for aid in OPEN:
            dr,cr=activity[(month(m),aid)]; begin=bal[aid]; bal[aid]+=dr-cr
            add('quickbooks/monthly_trial_balance',tb_id=f'TB-{month(m)}-{aid}',service_month=month(m),account_id=aid,opening_signed_balance_usd=money(begin),period_debits_usd=money(dr),period_credits_usd=money(cr),closing_signed_balance_usd=money(bal[aid]))
        tx=[t for t in T['bank/transactions'] if month(t['transaction_date'])==month(m)]; inc=sum(cents(t['money_in_usd']) for t in tx); out=sum(cents(t['money_out_usd']) for t in tx); end=bankopen+inc-out
        add('bank/monthly_statements',statement_id='BANKSTMT-'+month(m),bank_account_id='BANK-OPERATING-1042',service_month=month(m),opening_balance_usd=money(bankopen),total_money_in_usd=money(inc),total_money_out_usd=money(out),closing_balance_usd=money(end),transaction_count=len(tx)); bankopen=end
    opening=defaultdict(lambda:[0,0])
    for r in T['delivery/opening_service_balances']:
        x=opening[r['contract_id']]; x[0]+=cents(r['deferred_revenue_usd']); x[1]+=cents(r['unbilled_revenue_usd'])
    byinv={r['invoice_id']:r for r in T['quickbooks/client_invoices']}
    flows=defaultdict(lambda:[0,0,0,0])
    for l in T['quickbooks/client_invoice_lines']:
        inv=byinv[l['invoice_id']]
        if inv['record_scope']=='in_period':
            f=flows[(l['contract_id'],month(inv['invoice_date']))]; f[0]+=cents(l['invoiced_to_deferred_usd']); f[3]+=cents(l['invoiced_from_unbilled_usd'])
    for r in T['delivery/recognition_events']:
        f=flows[(r['contract_id'],month(r['recognition_date']))]; f[1]+=cents(r['earned_from_deferred_usd']); f[2]+=cents(r['earned_to_unbilled_usd'])
    for m in MONTHS:
        for con,co in CONTRACTS.items():
            if co['signed_date']>me(m): continue
            deff,unb=opening[con]; invdef,earndef,earnunb,invunb=flows[(con,month(m))]; ed=deff+invdef-earndef; eu=unb+earnunb-invunb
            add('delivery/monthly_contract_balances',contract_balance_id=f'CBAL-{con}-{month(m)}',contract_id=con,service_month=month(m),opening_deferred_usd=money(deff),invoiced_to_deferred_usd=money(invdef),earned_from_deferred_usd=money(earndef),closing_deferred_usd=money(ed),opening_unbilled_usd=money(unb),earned_to_unbilled_usd=money(earnunb),invoiced_from_unbilled_usd=money(invunb),closing_unbilled_usd=money(eu)); opening[con]=[ed,eu]
    rec=defaultdict(int); cred=defaultdict(int); vp=defaultdict(int)
    for x in T['quickbooks/receipt_applications']: rec[x['invoice_id']]+=cents(x['applied_amount_usd'])
    for x in T['quickbooks/credit_notes']: cred[x['invoice_id']]+=cents(x['amount_usd'])
    for x in T['quickbooks/vendor_payment_applications']: vp[x['bill_id']]+=cents(x['applied_amount_usd'])
    for inv in T['quickbooks/client_invoices']:
        amount=cents(inv['invoice_total_usd'])-rec[inv['invoice_id']]-cred[inv['invoice_id']]; inv['open_balance_usd']=money(amount); inv['invoice_status_asof']='paid' if not amount else 'partially_paid' if rec[inv['invoice_id']] else 'unpaid'
        if amount:
            days=max(0,(CUT-inv['due_date']).days); bucket='current' if not days else '1_30' if days<=30 else '31_60' if days<=60 else '61_90' if days<=90 else '91_plus'
            add('quickbooks/ar_open_items',ar_item_id='AR-'+inv['invoice_id'],invoice_id=inv['invoice_id'],client_id=inv['client_id'],contract_id=inv['contract_id'],invoice_date=inv['invoice_date'],due_date=inv['due_date'],original_amount_usd=inv['invoice_total_usd'],credit_applied_usd=money(cred[inv['invoice_id']]),cash_applied_usd=money(rec[inv['invoice_id']]),open_amount_usd=money(amount),days_past_due=days,aging_bucket=bucket,as_of_date=CUT)
            delay=30 if inv['client_id']=='CLI-004' else 10
            add('planning/collection_expectations',collection_expectation_id='COLL-'+inv['invoice_id'],invoice_id=inv['invoice_id'],client_id=inv['client_id'],open_amount_usd=money(amount),expected_receipt_date=nextbiz(max(CUT+timedelta(days=delay),inv['due_date']+timedelta(days=10))),collection_risk='high' if inv['client_id']=='CLI-004' else 'standard',basis='management_cutoff_assumption_not_actual',as_of_date=CUT)
    for b in T['quickbooks/vendor_bills']:
        amount=cents(b['bill_total_usd'])-vp[b['bill_id']]; b['open_balance_usd']=money(amount); b['bill_status_asof']='paid' if not amount else 'partially_paid' if vp[b['bill_id']] else 'unpaid'
        if amount:
            days=max(0,(CUT-b['due_date']).days); bucket='current' if not days else '1_30' if days<=30 else '31_60' if days<=60 else '61_90' if days<=90 else '91_plus'
            add('quickbooks/ap_open_items',ap_item_id='AP-'+b['bill_id'],bill_id=b['bill_id'],vendor_id=b['vendor_id'],bill_date=b['bill_date'],due_date=b['due_date'],original_amount_usd=b['bill_total_usd'],cash_applied_usd=money(vp[b['bill_id']]),open_amount_usd=money(amount),days_past_due=days,aging_bucket=bucket,as_of_date=CUT)

def planning():
    for year,start,approve,basehc in [('2025',START,date(2024,10,15),18),('2026',date(2025,11,1),date(2025,10,15),20)]:
        ver='BUDGET-FY'+year
        add('planning/budget_versions',budget_version_id=ver,budget_name='Original approved November-October plan FY'+year,approved_date=approve,period_start_date=start,period_end_date=me(shift(start,11)),is_original_approved=True,status='immutable',assumptions='Pre-period planning assumptions; 4% salary reviews, planned growth cohorts, no later actual scope creep or churn incorporated')
        known=[cid for cid,c in CLIENTS.items() if c['start'] and c['start']<=start]
        for i in range(12):
            m=shift(start,i)
            def budget(dept,stream,acct,amt,cid='',hours='',note=''):
                add('planning/monthly_budget',budget_line_id=f'BUD-{len(T["planning/monthly_budget"])+1:05d}',budget_version_id=ver,service_month=month(m),department=dept,revenue_stream=stream,account_id=acct,client_id=cid,project_id='',budget_amount_usd=usd(amt),budget_hours=hours,driver_note=note)
            for cid in known:
                c=CLIENTS[cid]; amt=c['base']*(1.045 if year=='2026' and c['i'] not in [1,3,6] else 1)
                budget('client_services','spend_based_management' if c['i'] in [6,10,18] else 'flat_retainer','4010' if c['i'] in [6,10,18] else '4000',amt,cid,90,'Known client retained throughout plan; no hindsight churn')
            budget('client_services','flat_retainer','4000',(i//3+1)*(10500 if year=='2025' else 12000),note='Unassigned new-business cohort; no fabricated signed contract')
            budget('creative','fixed_project','4020',39000 if year=='2025' else 47000,note='Planned monthly accepted-project fees')
            budget('analytics','hourly','4030',10500 if year=='2025' else 14500,note='Forecast approved hours times assumed blended rate')
            hc=basehc+(1 if i>=4 else 0)+(1 if i>=8 else 0)
            counts={'operations':3,'client_services':3+(1 if year=='2026' else 0),'analytics':3+(1 if year=='2026' else 0),'creative':4+(1 if i>=8 else 0)}; counts['paid_media']=hc-sum(counts.values())
            for dept,n in counts.items():
                salary=n*{'operations':10000,'client_services':7100,'analytics':8000,'creative':6500,'paid_media':6600}[dept]*(1.04 if year=='2026' else 1)
                pref='60' if dept=='operations' else '50'; budget(dept,'',pref+'00',salary,note='Original planned headcount times salary assumption'); budget(dept,'',pref+'01',salary*.08,note='Synthetic employer tax assumption 8%'); budget(dept,'',pref+'02',n*350,note='Employer benefit assumption')
                paid=n*len(weekdays(m,me(m)))*8; avail=dec(paid)*D('.94')
                add('planning/headcount_capacity_plan',capacity_plan_id=f'HCP-{ver}-{month(m)}-{dept}',plan_version_id=ver,approved_date=approve,service_month=month(m),department=dept,planned_headcount=n,planned_paid_hours=paid,planned_available_hours=avail,target_billable_utilization=D(0) if dept=='operations' else D('.78'),planned_salary_cost_usd=usd(salary),plan_status='original_budget')
            for acct,dept,amt in [('5010','creative',20500 if year=='2025' else 23200),('6100','operations',6800 if year=='2025' else 7000),('6110','operations',9000 if year=='2025' else 10000),('6120','operations',500 if year=='2025' else 550),('6130','operations',2250),('6140','operations',1800),('6150','operations',hc*45),('6300','operations',2000),('6400','operations',800 if year=='2025' else 600)]: budget(dept,'',acct,amt,note='Original operating-cost assumption')
    for k in range(3):
        m=shift(date(2026,11,1),k)
        for dept in ['operations','paid_media','client_services','creative','analytics']:
            current=[e for e in EMP.values() if e['department']==dept and active(e,CUT)]; n=len(current); hours=n*len(weekdays(m,me(m)))*8; salary=sum((comp_for(e['employee_id'],CUT)['annual_salary_usd']/12 for e in current),D(0))
            add('planning/headcount_capacity_plan',capacity_plan_id=f'HCP-OUTLOOK-{month(m)}-{dept}',plan_version_id='OUTLOOK-2026-10-20',approved_date=date(2026,10,20),service_month=month(m),department=dept,planned_headcount=n,planned_paid_hours=hours,planned_available_hours=dec(hours)*D('.92'),target_billable_utilization=D(0) if dept=='operations' else D('.77'),planned_salary_cost_usd=usd(salary),plan_status='forward_assumption_not_actual')
    accounts={'RENT':'6100','SAAS':'6110','PRO':'6130','TRAVEL':'6140','TRAIN':'6150','INS':'1200'}
    for code in accounts:
        bills=[b for b in T['quickbooks/vendor_bills'] if b['vendor_id']=='VND-'+code and b['record_scope']=='in_period']; latest=max(bills,key=lambda b:b['bill_date']); insurance=code=='INS'; future=date(2027,7,1) if insurance else date(2026,11,30)
        add('planning/recurring_obligations',obligation_id='OBL-'+code,vendor_id='VND-'+code,description='Active agency '+code.lower()+' agreement',account_id=accounts[code],cadence='annual' if insurance else 'monthly',contract_start_date=date(2026,7,1) if insurance else date(2026,1,1),contract_end_date=date(2027,6,30) if insurance else date(2027,12,31),current_cycle_fee_usd=latest['bill_total_usd'],next_service_start_date=date(2027,7,1) if insurance else date(2026,11,1),next_expected_bill_date=future,payment_terms_days=30 if code=='PRO' else 15,current_open_bill_id=latest['bill_id'] if latest['open_balance_usd'] else '',overlap_rule='Existing open bill is prior service cycle; future cycles start at next_service_start_date. Insurance renewal beyond current term is an assumption.',as_of_date=CUT)

def crm():
    stages=[('qualified','Qualified',1,'.15',False),('discovery','Discovery',2,'.30',False),('proposal','Proposal sent',3,'.55',False),('negotiation','Negotiation',4,'.75',False),('contract_sent','Contract sent',5,'.90',False),('closed_won','Closed won',6,'1',True),('closed_lost','Closed lost',7,'0',True)]
    for sid,name,order,p,closed in stages: add('hubspot/pipeline_stages',stage_id=sid,stage_name=name,stage_order=order,probability=D(p),is_closed=closed)
    for i,cid in enumerate(CLIENTS,1): add('hubspot/leads',lead_id=f'LEAD-{i:03d}',client_id=cid,created_date=date(2024,6,1)+timedelta(days=i*4),lead_source=['referral','inbound_content','partner_intro','outbound'][i%4],owner_employee_id='EMP-003',qualification_status='customer' if CLIENTS[cid]['start'] else 'qualified')
    deals=[]
    for co in CONTRACTS.values():
        typ='renewal' if co['parent_contract_id'] else 'new_sow'; signed=co['signed_date']; create=signed-timedelta(days=45)
        deals.append(dict(deal_id=co['deal_id'],client_id=co['client_id'],lead_id='LEAD-'+co['client_id'][-3:],deal_name=co['sow_name'],deal_type=typ,created_date=create,expected_close_date=signed,actual_close_date=signed,stage_id='closed_won',probability=D(1),quoted_value_usd=co['original_contract_value_usd'],value_basis=co['contract_value_basis'],contract_id=co['contract_id'],owner_employee_id='EMP-003',lost_reason='',as_of_date=CUT))
    for k in range(40):
        cid=f'CLI-{23+k%6:03d}'; create=START+timedelta(days=k*18); create=min(create,CUT-timedelta(days=10)); closed=k<34; won=False; dt=min(create+timedelta(days=47),CUT) if closed else ''
        stage='closed_lost' if closed else ['discovery','proposal','negotiation','contract_sent','proposal','qualified'][k-34]; p=next(D(s[3]) for s in stages if s[0]==stage); quoted=usd(72000+(k%8)*18000)
        deals.append(dict(deal_id=f'DEAL-PIPE-{k+1:03d}',client_id=cid,lead_id='LEAD-'+cid[-3:],deal_name='Prospective growth retainer '+str(k+1),deal_type='new_business_pipeline',created_date=create,expected_close_date=(create+timedelta(days=70)) if closed else date(2026,11,15)+timedelta(days=(k-34)*13),actual_close_date=dt,stage_id=stage,probability=p,quoted_value_usd=quoted,value_basis='estimated_12_month_fee_not_revenue',contract_id='',owner_employee_id='EMP-003',lost_reason='Client postponed or selected another agency' if closed else '',as_of_date=CUT))
    for d in deals:
        add('hubspot/deals',**d); hist=[]; current=''; path=['qualified','discovery','proposal','negotiation','contract_sent']
        final=d['stage_id']; terminal=final in ['closed_won','closed_lost']; count=5 if terminal else path.index(final)+1
        finaldate=d['actual_close_date'] if terminal else min(CUT,d['created_date']+timedelta(days=(count-1)*8))
        for ix,stage in enumerate(path[:count]):
            dt=min(finaldate,d['created_date']+timedelta(days=ix*8)); p=next(D(s[3]) for s in stages if s[0]==stage)
            r=add('hubspot/deal_stage_history',stage_event_id=f'DSH-{len(T["hubspot/deal_stage_history"])+1:05d}',deal_id=d['deal_id'],changed_date=dt,from_stage_id=current,to_stage_id=stage,probability=p,expected_close_date=d['expected_close_date'] if ix>=3 else d['created_date']+timedelta(days=55),quoted_value_usd=d['quoted_value_usd']); hist.append(r); current=stage
        if terminal: hist.append(add('hubspot/deal_stage_history',stage_event_id=f'DSH-{len(T["hubspot/deal_stage_history"])+1:05d}',deal_id=d['deal_id'],changed_date=finaldate,from_stage_id=current,to_stage_id=final,probability=d['probability'],expected_close_date=d['expected_close_date'],quoted_value_usd=d['quoted_value_usd']))
        elif hist[-1]['expected_close_date']!=d['expected_close_date']:
            # Observable forecast-date revision without claiming a pipeline-stage transition.
            hist.append(add('hubspot/deal_stage_history',stage_event_id=f'DSH-{len(T["hubspot/deal_stage_history"])+1:05d}',deal_id=d['deal_id'],changed_date=CUT,from_stage_id=current,to_stage_id=current,probability=d['probability'],expected_close_date=d['expected_close_date'],quoted_value_usd=d['quoted_value_usd']))
        for m in MONTHS:
            valid=[h for h in hist if h['changed_date']<=me(m)]
            if not valid: continue
            h=valid[-1]; include=h['to_stage_id'] not in ['closed_won','closed_lost']
            add('hubspot/deal_monthly_snapshots',snapshot_id=f'DSNAP-{d["deal_id"]}-{month(m)}',snapshot_date=me(m),deal_id=d['deal_id'],client_id=d['client_id'],stage_id=h['to_stage_id'],probability=h['probability'],expected_close_date=h['expected_close_date'],quoted_value_usd=h['quoted_value_usd'],weighted_pipeline_usd=usd(h['quoted_value_usd']*h['probability']) if include else usd(0),include_in_pipeline=include,contract_id=d['contract_id'] if not include and h['to_stage_id']=='closed_won' else '')

def run_finance():
    payroll(); contractors_and_vendors(); operating_costs(); invoicing(); opening_and_chart(); loan_and_distributions(); post_events(); planning(); crm()
