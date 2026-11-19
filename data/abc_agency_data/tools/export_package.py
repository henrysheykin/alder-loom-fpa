"""Publish raw extracts, schemas, relational metadata and documentation scaffolding."""
from build_dataset import *

DESCRIPTIONS={
 'client_id':'Stable fictional client/company ID; join to hubspot/companies, not a customer email.',
 'contract_id':'Signed SOW ID, join to contracts/contracts; blank only for internal/overhead.',
 'project_id':'Delivery project ID, including PRJ-INTERNAL; join to timekeeping/projects.',
 'service_id':'Performance-obligation ID linking delivery, fee billing and recognition.',
 'service_month':'Service/analysis month in YYYY-MM; recognition event month can differ for late milestones.',
 'employee_id':'Stable employee roster ID; salaried time allocation does not create another expense.',
 'account_id':'Text GL account code; join to chart_of_accounts.',
 'billable':'True for client delivery work; for retainers/fixed projects this does not imply an incremental invoice.',
 'billing_treatment':'Time billing rule: included fees versus approved hours times effective role rate.',
 'payer_client_id':'Client legally funding platform media directly. No agency bank movement is implied.',
 'funding_responsibility':'CLIENT_DIRECT for every ad observation; exclude from agency GL and bank.',
 'account_owner':'Client owns the platform ad account; agency only has management access.',
 'agency_pays_platform':'Always False in this package; no pass-through cash or media expense modeled.',
 'media_spend_usd':'Client platform media cost in USD; a management-fee driver, never agency fee revenue.',
 'spend_usd':'Observed client-funded campaign media spend in USD.',
 'cost_micros':'Google modeled cost in millionths of USD; divide by 1,000,000; also equal spend_usd * 1,000,000.',
 'attributed_conversions':'Platform-attributed conversions; decimal attribution weights permitted; platforms overlap.',
 'attributed_conversion_value_usd':'Client platform-attributed conversion value; neither deduplicated client sales nor agency revenue.',
 'spend_fee_rate':'Contractual decimal share of combined mapped Meta/Google media spend; 0.06 means 6%.',
 'scope_hours_budget':'Approved monthly included-service hours; scope rework is not automatically chargeable.',
 'planned_hours':'Approved monthly staff allocation, distinct from actual approved timesheets.',
 'paid_capacity_hours':'Paid scheduled weekday hours before paid leave; denominator for payroll allocation.',
 'available_work_hours':'Paid capacity less approved paid leave/holiday; upper bound for actual work hours.',
 'basis_hours':'Paid hours assigned to project/internal work/leave within one payroll period.',
 'period_paid_hours':'Total paid scheduled employee hours for this payroll period; repeated denominator, do not sum over allocation rows.',
 'allocated_employer_cost_usd':'Allocated share of gross salary plus employer tax and benefits; secondary view, never post again.',
 'is_additional_gl_expense':'Always False; the allocation is already contained in consolidated payroll GL expense.',
 'gross_pay_usd':'Earned salary before employee withholding. Employee withholding is included, not an extra employer expense.',
 'employee_withholding_usd':'Synthetic employee withholding deducted from gross pay; remitted in payroll funding.',
 'employer_tax_usd':'Additional employer payroll cost using a synthetic 8% assumption, not a statutory tax calculation.',
 'employer_benefit_usd':'Synthetic employer benefit cost paid through modeled payroll-provider funding.',
 'net_pay_usd':'Gross salary minus employee withholding; one part of payroll bank funding.',
 'total_employer_cost_usd':'Gross salary plus employer tax plus employer benefit, including unpaid earned periods.',
 'bank_debit_usd':'Actual combined payroll funding: net pay + employee withholding + employer tax + benefits.',
 'earned_cost_usd':'Accepted freelancer service expense; posted once to 5010/2200 before received AP invoice.',
 'hourly_cost_rate_usd':'Effective negotiated freelancer cost in USD per approved hour; synthetic contract price.',
 'hourly_rate_usd':'Effective client hourly billing rate in USD per approved hour, independent of employee salary.',
 'billable_rate_usd':'Client hourly role rate only for T&M work; blank for included retainer/fixed time.',
 'record_scope':'in_period = historical service/activity window; opening_item = pre-window balance support; signed_future = already signed future service, not an observed actual.',
 'agreed_minimum_fee_usd':'Contractually guaranteed service fee floor, separate from approved_fee_usd. Retainer floor from monthly_terms; hourly T&M minimum is zero; fixed deliverable has agreed price.',
 'approved_fee_usd':'Actual approved gross earned fee; may exceed spend-based contract floor. Blank for future service. Never substitute for guaranteed contract minimum.',
 'status_asof':'Source state at the historical cutoff; values are table-specific. For SOWs, active means in service, signed_future means signed but not started, completed/terminated are separate.',
 'recognized_fee_usd':'Signed actual earned fee: positive fee, negative post-service concession; exclude invoice/cash copies.',
 'earned_from_deferred_usd':'Gross earning applied against previously billed service liability.',
 'earned_to_unbilled_usd':'Gross earning not yet invoiced; increases contract asset 1150.',
 'invoiced_to_deferred_usd':'Invoice amount before earning; increases contract liability 2300.',
 'invoiced_from_unbilled_usd':'Invoice settles previously earned unbilled fee; credits 1150 without new revenue.',
 'original_contract_value_usd':'Signed original fixed minimum or hourly quote according to contract_value_basis; not period revenue.',
 'current_committed_minimum_usd':'Guaranteed fixed contract fee across its full amended term, excluding variable spend upside and hourly ceilings.',
 'contract_ceiling_usd':'Maximum permitted T&M charge or fixed price; blank if no contractual ceiling. Not guaranteed revenue.',
 'weighted_pipeline_usd':'Open deal quoted value times stage probability; zero for won/lost deals.',
 'include_in_pipeline':'True only for open unsigned opportunities at snapshot; signed contracts are excluded.',
 'signed_balance_usd':'Debit minus credit; liability/revenue balances normally negative.',
 'closing_signed_balance_usd':'Accumulated debit-minus-credit month-end account balance; PL balances are not month-only income.',
 'period_debits_usd':'Debit account movement during that month only.',
 'period_credits_usd':'Credit account movement during that month only.',
 'debit_usd':'Nonnegative journal/account debit in USD.',
 'credit_usd':'Nonnegative journal/account credit in USD.',
 'is_original_approved':'True only for the immutable original annual budget, approved before its coverage starts.',
 'budget_amount_usd':'Positive approved revenue or expense budget; classify with account/stream, do not treat all as one sign.',
 'target_billable_utilization':'Planned decimal share of available employee hours for approved client delivery; not invoice utilization.',
 'overlap_key':'Stable billing schedule key to deduplicate signed-future commitment copies.',
 'as_of_date':'Historical snapshot date 2026-10-31. Does not convert future plans into actuals.',
 'known_date':'Date on which this billing allocation/amount was known; variable actual true-up can be known at month-end.',
 'planned_invoice_group_id':'Planned invoice header grouping. Future groups are schedules and have no actual invoice record.',
 'actual_invoice_line_id':'Actual QB fee invoice line link; blank for future scheduled items or opening settled prepaid items.',
 'expected_receipt_date':'Management estimate for collecting open AR after cutoff; never an actual bank receipt.',
 'actual_approved_date':'Actual acceptance date; blank for future unaccepted services.',
 'approval_status':'Observed status at cutoff. Only approved hourly work earns hourly fees.',
 'is_scope_rework':'True for unpriced extra revision work, an explicit scope-creep marker.',
 'client_payment_status':'Client platform settlement is not observed by the agency; not an agency payment source.',
 'current_open_bill_id':'Existing AP bill for the latest service cycle; do not add it twice through recurring-obligation forecasts.',
 'source_bill_id':'Insurance origin bill ID, or OPEN-INS-2024 for the opening asset.',
 'original_hours_budget':'Original agreed project/milestone hours. For retainer monthly scope use monthly_terms.',
 'contract_version_id':'Append-only dated commercial version; approved_date must be on/before its effective service month.',
 'sequence':'Within bank statement chronological ordering, or within a fixed-project milestone sequence, according to table grain.',
}

def dtype(field,rows):
    if field.endswith('_usd'): return 'decimal_usd_2dp'
    if field.endswith('_date') or field in ['calendar_date','work_date','off_date','metric_date','journal_date','invoice_date','bill_date','credit_date','payment_date','funding_date','distribution_date','changed_date','created_date']: return 'date_iso'
    if field=='service_month': return 'month_iso'
    if field.startswith('is_') or field in ['billable','include_in_pipeline','agency_pays_platform','company_holiday']: return 'boolean'
    if field.endswith('_hours') or field in ['hours','scope_hours_month','scope_hours_change','scope_hours_budget','original_hours_budget','budget_hours','planned_hours','approved_hours','target_billable_utilization','probability','spend_fee_rate','annual_interest_rate','withholding_rate','employer_tax_rate','attributed_conversions']: return 'decimal'
    if field in ['impressions','clicks','cost_micros','version_number','sequence','days_past_due','stage_order','transaction_count','planned_headcount','payment_terms_days']: return 'integer'
    return 'text'

def description(field,key):
    if field in DESCRIPTIONS: return DESCRIPTIONS[field]
    if field.endswith('_id'): return 'Stable text identifier/reference for '+field[:-3].replace('_',' ')+'. See relationships.csv and this table grain.'
    if field.endswith('_usd'): return field[:-4].replace('_',' ').capitalize()+' in decimal USD; nonnegative unless explicitly labeled signed/change/recognized.'
    if field.endswith('_date'): return field[:-5].replace('_',' ').capitalize()+' in ISO YYYY-MM-DD; empty if not observed or not applicable.'
    if field.endswith('_hours') or field=='hours': return field.replace('_',' ').capitalize()+' in decimal hours; separate planned/approved/actual meaning follows column name.'
    return field.replace('_',' ').capitalize()+'. '+{'status_asof':'Observed state at the 2026-10-31 cutoff.','currency':'USD throughout the package.','email':'Fictional contact using example.com.','role':'Work role, used for employee rates and approved-hour billing.','department':'Department dimension for costs, resource plans or budget.'}.get(field,'Categorical/text source attribute; interpreted within the stated table grain.')

def add_relationships():
    # Unambiguous dimension keys across the package; polymorphic document references are documented separately.
    dims={'client_id':('hubspot/companies','client_id'),'payer_client_id':('hubspot/companies','client_id'),'contract_id':('contracts/contracts','contract_id'),'parent_contract_id':('contracts/contracts','contract_id'),'project_id':('timekeeping/projects','project_id'),'employee_id':('gusto/employees','employee_id'),'owner_employee_id':('gusto/employees','employee_id'),'deal_id':('hubspot/deals','deal_id'),'lead_id':('hubspot/leads','lead_id'),'contract_version_id':('contracts/contract_versions','contract_version_id'),'change_order_id':('contracts/change_orders','change_order_id'),'rate_card_id':('contracts/rate_cards','rate_card_id'),'compensation_id':('gusto/compensation_rates','compensation_id'),'term_id':('contracts/monthly_terms','term_id'),'task_id':('timekeeping/tasks','task_id'),'payroll_run_id':('gusto/payroll_runs','payroll_run_id'),'payroll_earning_id':('gusto/payroll_earnings','payroll_earning_id'),'contractor_id':('freelancers/contractors','contractor_id'),'contractor_rate_id':('freelancers/rate_history','contractor_rate_id'),'work_order_id':('freelancers/work_orders','work_order_id'),'approved_work_id':('freelancers/approved_work','approved_work_id'),'contractor_invoice_id':('freelancers/invoices','contractor_invoice_id'),'contractor_invoice_line_id':('freelancers/invoice_lines','contractor_invoice_line_id'),'vendor_id':('quickbooks/vendors','vendor_id'),'invoice_id':('quickbooks/client_invoices','invoice_id'),'invoice_line_id':('quickbooks/client_invoice_lines','invoice_line_id'),'actual_invoice_line_id':('quickbooks/client_invoice_lines','invoice_line_id'),'credit_note_id':('quickbooks/credit_notes','credit_note_id'),'recognition_id':('delivery/recognition_events','recognition_id'),'receipt_id':('quickbooks/client_receipts','receipt_id'),'bill_id':('quickbooks/vendor_bills','bill_id'),'current_open_bill_id':('quickbooks/vendor_bills','bill_id'),'accounting_bill_id':('quickbooks/vendor_bills','bill_id'),'bill_line_id':('quickbooks/vendor_bill_lines','bill_line_id'),'accounting_bill_line_id':('quickbooks/vendor_bill_lines','bill_line_id'),'vendor_payment_id':('quickbooks/vendor_payments','vendor_payment_id'),'bank_transaction_id':('bank/transactions','bank_transaction_id'),'bank_account_id':('bank/accounts','bank_account_id'),'journal_id':('quickbooks/journals','journal_id'),'service_id':('delivery/service_obligations','service_id'),'schedule_line_id':('contracts/billing_schedule','schedule_line_id'),'account_id':('quickbooks/chart_of_accounts','account_id'),'revenue_account_id':('quickbooks/chart_of_accounts','account_id'),'asset_account_id':('quickbooks/chart_of_accounts','account_id'),'expense_account_id':('quickbooks/chart_of_accounts','account_id'),'budget_version_id':('planning/budget_versions','budget_version_id'),'debt_id':('finance/debt_register','debt_id')}
    for key,sc in SC.items():
        for col in sc['fields']:
            if col in dims:
                target,tc=dims[col]
                if target==key and col==tc: continue
                nullable=any(r[col]=='' for r in T[key])
                fk(key,col,target,tc,nullable)
        if key.startswith(('meta_ads/','google_ads/')):
            platform=key.split('/')[0]
            for col,tab in [('ad_account_id','ad_accounts'),('campaign_id','campaigns')]:
                target=platform+'/'+tab
                if col in sc['fields'] and key!=target: fk(key,col,target,col)
    for key,col in [('hubspot/deals','stage_id'),('hubspot/deal_monthly_snapshots','stage_id'),('hubspot/deal_stage_history','from_stage_id'),('hubspot/deal_stage_history','to_stage_id')]: fk(key,col,'hubspot/pipeline_stages','stage_id',col=='from_stage_id')
    # funding_id is nullable on the unpaid payroll run.
    fk('gusto/payroll_runs','funding_id','gusto/payroll_funding','funding_id',True)

def write_csv(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n'); w.writeheader()
        for r in rows: w.writerow({k:('True' if v else 'False') if isinstance(v,bool) else iso(v) for k,v in r.items()})

def write_sources():
    ROOT.mkdir(parents=True,exist_ok=True); add_relationships(); manifests=[]; catalogs=[]; dictionary=[]
    for key,rows in T.items():
        sc=SC[key]; sc['types']={c:dtype(c,rows) for c in sc['fields']}; sc['nullable']={c:any(r[c]=='' for r in rows) for c in sc['fields']}
        parts=defaultdict(list)
        if sc['partition_column']:
            for row in rows: parts[month(row[sc['partition_column']])].append(row)
        else: parts['']=rows
        sc['physical_files']=[]
        for part,rr in sorted(parts.items()):
            rel=f'sources/{key}/{part}.csv' if part else f'sources/{key}.csv'; path=ROOT/rel
            write_csv(path,sc['fields'],rr); sc['physical_files'].append(rel)
            manifests.append(dict(relative_path=rel,logical_table=key,row_count=len(rr),byte_size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        catalogs.append(dict(logical_table=key,source_system=key.split('/')[0],grain=sc['grain'],primary_key='|'.join(sc['primary_key']),row_count=len(rows),physical_file_count=len(sc['physical_files']),partition_column=sc['partition_column'],notes=sc['notes']))
        for c in sc['fields']:
            typ=sc['types'][c]; dictionary.append(dict(logical_table=key,column_name=c,data_type=typ,nullable=sc['nullable'][c],is_primary_key=c in sc['primary_key'],grain=sc['grain'],unit='USD' if typ=='decimal_usd_2dp' else 'hours' if 'hours' in c else 'ratio' if 'rate' in c and not c.endswith('_id') else 'count' if typ=='integer' else '',sign_convention='debit_minus_credit' if 'signed_balance' in c else 'signed' if c in ['recognized_fee_usd','fee_change_usd','signed_amount_usd'] else 'nonnegative_when_numeric',definition=description(c,key)))
    meta=ROOT/'metadata'; meta.mkdir(exist_ok=True)
    (meta/'table_schemas.json').write_text(json.dumps(SC,ensure_ascii=False,indent=2,default=iso),encoding='utf-8')
    write_csv(meta/'file_manifest.csv',list(manifests[0]),manifests)
    write_csv(meta/'table_catalog.csv',list(catalogs[0]),catalogs)
    write_csv(meta/'data_dictionary.csv',list(dictionary[0]),dictionary)
    write_csv(meta/'relationships.csv',list(FK[0]),FK)
    source_notes={'hubspot':'Modeled CRM companies, qualification, won/lost/open deals and observed historical pipeline snapshots. Not actual revenue.','contracts':'Signed SOWs, amendments, monthly commercial terms, milestone acceptance terms, hourly cards and billing schedule.','timekeeping':'Employee daily capacity, paid time off, frozen assignments and actual time; not a billing ledger.','gusto':'Modeled salary earnings, provider funding and secondary project/overhead allocation. Synthetic tax/benefit assumptions.','freelancers':'Accepted deliverables and hours, earned costs, received invoices and links to QB AP.','meta_ads':'Client-owned, client-funded Meta-style campaign metrics and monthly analytical statements.','google_ads':'Client-owned, client-funded Google-style campaign metrics; cost_micros retained.','delivery':'Approved earned-fee events, service-level opening assets/liabilities and contract roll-forwards.','quickbooks':'Modeled accounting documents, AR/AP, double-entry journals, GL and monthly trial balance.','bank':'Agency bank actuals only, running balances and 24 statements. No client media cash.','planning':'Immutable original budgets, capacity plans and cutoff-known commitments/collection assumptions.','finance':'Loan agreement, actual repayments, future contractual schedule, owner distributions and insurance amortization.'}
    sourcecat=[]
    for system,note in source_notes.items():
        cats=[x for x in catalogs if x['source_system']==system]
        sourcecat.append(dict(source_system=system,table_count=len(cats),physical_csv_count=sum(c['physical_file_count'] for c in cats),row_count=sum(c['row_count'] for c in cats),description=note,extract_semantics='synthetic_modeled_extract_not_native_API_export',snapshot_date=iso(CUT)))
    write_csv(meta/'source_catalog.csv',list(sourcecat[0]),sourcecat)
    settings=dict(company='Signal Harbor Performance LLC',synthetic=True,currency='USD',actual_start=iso(START),actual_end=iso(CUT),snapshot_date=iso(CUT),random_seed=803117,media_policy='ALL_CLIENT_DIRECT_NO_PASS_THROUGH',source_csv_count=len(manifests),logical_table_count=len(T),source_row_count=sum(len(v) for v in T.values()),schema_version='1.0',opening_balance_date='2024-10-31',csv_encoding='UTF-8 BOM',delimiter=',',money_precision='USD cents, ROUND_HALF_UP',budget_calendar='November-October',generation_script='tools/run_build.py')
    (meta/'dataset_settings.json').write_text(json.dumps(settings,indent=2),encoding='utf-8')
