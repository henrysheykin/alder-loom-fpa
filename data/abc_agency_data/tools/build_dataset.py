"""Deterministic fictional agency event model. Standard library only; see PLAN.md."""
from __future__ import annotations
import calendar, csv, hashlib, json, math, random, shutil
from collections import defaultdict, Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / 'outputs' / 'signal_harbor_data'
START, CUT = date(2024,11,1), date(2026,10,31)
RNG = random.Random(803117)
D = Decimal

def dec(x): return D(str(x))
def usd(x): return dec(x).quantize(D('.01'), rounding=ROUND_HALF_UP)
def cents(x): return int((dec(x)*100).quantize(D('1'), rounding=ROUND_HALF_UP))
def money(c): return usd(D(c)/100)
def iso(x): return x.isoformat() if isinstance(x,date) else x
def month(x): return iso(x)[:7]
def ms(x): return date(x.year,x.month,1)
def shift(x,n):
    k=x.year*12+x.month-1+n
    return date(k//12,k%12+1,min(x.day,calendar.monthrange(k//12,k%12+1)[1]))
def me(x): return date(x.year,x.month,calendar.monthrange(x.year,x.month)[1])
def weekdays(a,b):
    return [a+timedelta(days=i) for i in range((b-a).days+1) if (a+timedelta(days=i)).weekday()<5]
def nextbiz(x):
    while x.weekday()>4: x+=timedelta(days=1)
    return x
def alloc(total,weights):
    """Largest-remainder integer allocation; stable tie break preserves every cent/unit."""
    if not weights: return []
    s=sum(dec(w) for w in weights)
    if s==0: return [total]+[0]*(len(weights)-1)
    raw=[dec(total)*dec(w)/s for w in weights]; out=[int(v) for v in raw]
    for i in sorted(range(len(raw)),key=lambda i:(-(raw[i]-out[i]),i))[:total-sum(out)]: out[i]+=1
    return out

MONTHS=[shift(START,i) for i in range(24)]
T, SC, FK = {}, {}, []

def table(key,fields,grain,pk,notes='',partition=''):
    T[key]=[]; SC[key]={'fields':fields.split('|'),'grain':grain,'primary_key':pk.split('|'),
                        'notes':notes,'partition_column':partition}
def add(key,**r):
    unknown=set(r)-set(SC[key]['fields'])
    if unknown: raise ValueError((key,unknown))
    row={k:r.get(k,'') for k in SC[key]['fields']}; T[key].append(row); return row
def fk(a,col,b,target,nullable=False,note=''):
    FK.append(dict(from_table=a,from_column=col,to_table=b,to_column=target,
                   cardinality='many_to_one',nullable=nullable,note=note))
def reg(key,spec,grain,pk,notes='',partition=''): table(key,spec,grain,pk,notes,partition)

def init_tables():
    reg('hubspot/companies','client_id|company_name|industry|state_code|email|created_date|lifecycle_stage|currency|is_synthetic','One fictional client/prospect company as of cutoff','client_id')
    reg('hubspot/pipeline_stages','stage_id|stage_name|stage_order|probability|is_closed','One sales pipeline stage','stage_id')
    reg('hubspot/leads','lead_id|client_id|created_date|lead_source|owner_employee_id|qualification_status','One prospect qualification record','lead_id')
    reg('hubspot/deals','deal_id|client_id|lead_id|deal_name|deal_type|created_date|expected_close_date|actual_close_date|stage_id|probability|quoted_value_usd|value_basis|contract_id|owner_employee_id|lost_reason|as_of_date','One deal current state at cutoff','deal_id','Won deal amount is a quote/bookings measure, never earned revenue.')
    reg('hubspot/deal_stage_history','stage_event_id|deal_id|changed_date|from_stage_id|to_stage_id|probability|expected_close_date|quoted_value_usd','One observed sales-stage or expected-close revision; same-stage events revise forecast properties','stage_event_id')
    reg('hubspot/deal_monthly_snapshots','snapshot_id|snapshot_date|deal_id|client_id|stage_id|probability|expected_close_date|quoted_value_usd|weighted_pipeline_usd|include_in_pipeline|contract_id','One deal known at a historical month-end','snapshot_id','Closed-won/lost rows carry zero weighted open pipeline.')
    reg('contracts/contracts','contract_id|client_id|deal_id|parent_contract_id|contract_type|sow_name|signed_date|service_start_date|original_end_date|current_end_date|original_contract_value_usd|current_committed_minimum_usd|contract_ceiling_usd|contract_value_basis|payment_terms_days|billing_cadence|status_asof|currency','One signed SOW/renewal; amendments separate','contract_id')
    reg('contracts/contract_versions','contract_version_id|contract_id|version_number|approved_date|effective_start_date|effective_end_date|fee_model|monthly_minimum_fee_usd|spend_fee_rate|scope_hours_month|scope_cost_budget_month_usd|reason|change_order_id','One dated commercial version, append-only','contract_version_id')
    reg('contracts/monthly_terms','term_id|contract_id|contract_version_id|client_id|service_month|fee_model|monthly_minimum_fee_usd|spend_fee_rate|scope_hours_budget|scope_cost_budget_usd|known_asof_date','One signed retainer service month including known future months','term_id')
    reg('contracts/change_orders','change_order_id|contract_id|signed_date|effective_date|change_type|fee_change_usd|scope_hours_change|reason|supersedes_version_id','One signed amendment/termination','change_order_id')
    reg('contracts/rate_cards','rate_card_id|role|effective_start_date|effective_end_date|approved_date|hourly_rate_usd','One hourly bill rate per role/effective interval','rate_card_id')
    reg('contracts/milestones','milestone_id|contract_id|project_id|sequence|deliverable|planned_approval_date|actual_approved_date|approval_status|agreed_fee_usd|original_hours_budget|original_cost_budget_usd|service_id','One explicitly priced fixed-project milestone','milestone_id')
    reg('contracts/fee_calculations','calculation_id|term_id|contract_id|client_id|service_month|media_spend_usd|spend_fee_rate|percentage_fee_usd|minimum_fee_usd|earned_fee_usd|service_id','One observed monthly retainer fee calculation','calculation_id','Media spend is a fee driver, not agency revenue.')
    reg('contracts/billing_schedule','schedule_line_id|planned_invoice_group_id|contract_id|client_id|service_id|scheduled_invoice_date|scheduled_due_date|scheduled_amount_usd|amount_basis|known_date|actual_invoice_line_id|status_asof|as_of_date','One planned billing allocation to a service obligation','schedule_line_id','Historical billed rows and future known billings share the same schedule; do not add actual and schedule amounts.')
    reg('timekeeping/projects','project_id|client_id|contract_id|project_name|project_type|start_date|end_date|is_billable|original_hours_budget|original_cost_budget_usd|budget_basis','One internal or contract delivery project','project_id')
    reg('timekeeping/tasks','task_id|task_name|is_billable|scope_class','One reusable timekeeping task','task_id')
    reg('timekeeping/work_calendar','calendar_date|is_weekday|company_holiday|standard_paid_hours','One calendar date in historical window','calendar_date')
    reg('timekeeping/daily_capacity','capacity_id|employee_id|work_date|paid_capacity_hours|paid_time_off_hours|available_work_hours','One active employee weekday, including paid leave','capacity_id',partition='work_date')
    reg('timekeeping/time_off','time_off_id|employee_id|off_date|hours|leave_type|approval_date|approval_status','One approved paid-leave event','time_off_id')
    reg('timekeeping/staff_allocations','allocation_plan_id|employee_id|project_id|contract_id|service_month|planned_hours|approved_date|plan_version_id','One frozen employee/project monthly allocation','allocation_plan_id')
    reg('timekeeping/timesheets','time_entry_id|employee_id|role|project_id|task_id|client_id|contract_id|work_date|hours|billable|approval_status|approved_date|billing_treatment|rate_card_id|billable_rate_usd|is_scope_rework','One actual employee/task time entry','time_entry_id','Retainer and fixed-fee billable time does not generate extra hourly invoices.',partition='work_date')
    reg('gusto/employees','employee_id|employee_name|email|role|department|cost_class|hire_date|termination_date|employment_type|standard_week_hours','One fictional employee across entire roster history','employee_id')
    reg('gusto/compensation_rates','compensation_id|employee_id|effective_start_date|effective_end_date|annual_salary_usd|withholding_rate|employer_tax_rate|monthly_employer_benefit_usd|approved_date','One effective salary interval; all tax parameters are synthetic','compensation_id')
    reg('gusto/payroll_runs','payroll_run_id|earned_start_date|earned_end_date|scheduled_funding_date|actual_funding_date|record_scope|gross_pay_usd|employee_withholding_usd|employer_tax_usd|employer_benefit_usd|net_pay_usd|total_employer_cost_usd|funding_id','One semimonthly payroll, with one opening run','payroll_run_id')
    reg('gusto/payroll_earnings','payroll_earning_id|payroll_run_id|employee_id|compensation_id|earned_start_date|earned_end_date|record_scope|gross_pay_usd|employee_withholding_usd|employer_tax_usd|employer_benefit_usd|net_pay_usd|total_employer_cost_usd|journal_id','One employee/payroll-period earning','payroll_earning_id')
    reg('gusto/payroll_funding','funding_id|payroll_run_id|funding_date|net_pay_usd|employee_withholding_usd|employer_tax_usd|employer_benefit_usd|bank_debit_usd|bank_transaction_id|journal_id','One actual payroll-provider bank funding','funding_id','Provider remits tax/benefits from this debit; do not add another tax cash payment.')
    reg('gusto/cost_allocations','cost_allocation_id|payroll_earning_id|payroll_run_id|employee_id|project_id|client_id|contract_id|service_month|allocation_category|basis_hours|period_paid_hours|allocated_employer_cost_usd|is_additional_gl_expense','One employee/payroll-period/project-or-overhead cost allocation','cost_allocation_id','Secondary view of already-posted payroll, not an additional expense.')
    reg('freelancers/contractors','contractor_id|vendor_id|contractor_name|email|role|status_asof|payment_terms_days','One freelance supplier','contractor_id')
    reg('freelancers/rate_history','contractor_rate_id|contractor_id|effective_start_date|effective_end_date|hourly_cost_rate_usd|approved_date|reason','One effective freelance cost-rate interval','contractor_rate_id')
    reg('freelancers/work_orders','work_order_id|contractor_id|contract_id|project_id|client_id|service_month|approved_date|budget_hours|budget_cost_usd|status_asof','One monthly approved freelance work authorization','work_order_id')
    reg('freelancers/approved_work','approved_work_id|work_order_id|contractor_id|contractor_rate_id|project_id|contract_id|client_id|service_month|service_start_date|service_end_date|approved_date|approved_hours|hourly_cost_rate_usd|earned_cost_usd|deliverable|contractor_invoice_id|journal_id','One accepted freelance work item/earned cost','approved_work_id','Expense arises here once; subsequent QB bill clears accrued contractor cost.')
    reg('freelancers/invoices','contractor_invoice_id|contractor_id|invoice_date|due_date|service_month|invoice_total_usd|accounting_bill_id|status_asof','One received freelancer invoice','contractor_invoice_id')
    reg('freelancers/invoice_lines','contractor_invoice_line_id|contractor_invoice_id|approved_work_id|work_order_id|line_amount_usd|accounting_bill_line_id','One invoiced accepted-work reference','contractor_invoice_line_id')
    for platform in ['meta_ads','google_ads']:
        reg(platform+'/ad_accounts','ad_account_id|client_id|account_name|account_owner|payer_client_id|funding_responsibility|agency_pays_platform|currency|timezone','One client-owned advertising account','ad_account_id')
        reg(platform+'/campaigns','campaign_id|ad_account_id|client_id|campaign_name|objective|start_date|end_date|attribution_model|attribution_window|conversion_unit','One client campaign','campaign_id')
        reg(platform+'/campaign_contract_map','mapping_id|campaign_id|ad_account_id|client_id|contract_id|effective_start_date|effective_end_date','One campaign/management-SOW effective interval','mapping_id')
        extra='|cost_micros' if platform=='google_ads' else ''
        reg(platform+'/daily_metrics','metric_id|metric_date|campaign_id|ad_account_id|client_id|contract_id|payer_client_id|funding_responsibility|spend_usd'+extra+'|impressions|clicks|attributed_conversions|attributed_conversion_value_usd|currency','One campaign/day/platform observation','metric_id','Platform attribution can overlap across platforms; values are not agency sales.',partition='metric_date')
        reg(platform+'/monthly_billing','platform_statement_id|ad_account_id|client_id|service_month|statement_date|media_spend_usd|payer_client_id|funding_responsibility|agency_cash_amount_usd|client_payment_status','One analytical monthly client platform-spend statement','platform_statement_id','Monthly consolidation is a synthetic simplification; client bank settlement is not observed.')
    reg('delivery/service_obligations','service_id|contract_id|client_id|project_id|service_type|service_month|service_start_date|service_end_date|planned_approval_date|actual_approved_date|agreed_minimum_fee_usd|approved_fee_usd|approved_hours|rate_card_basis|recognition_status|record_scope','One priced monthly service or approved milestone; includes signed future obligations','service_id')
    reg('delivery/recognition_events','recognition_id|service_id|contract_id|client_id|project_id|recognition_date|service_month|recognition_type|revenue_account_id|recognized_fee_usd|earned_from_deferred_usd|earned_to_unbilled_usd|credit_note_id|journal_id','One actual earning or fee-concession event','recognition_id')
    reg('delivery/opening_service_balances','opening_service_balance_id|service_id|contract_id|client_id|balance_date|deferred_revenue_usd|unbilled_revenue_usd|explanation','One opening performance-obligation asset/liability','opening_service_balance_id')
    reg('delivery/monthly_contract_balances','contract_balance_id|contract_id|service_month|opening_deferred_usd|invoiced_to_deferred_usd|earned_from_deferred_usd|closing_deferred_usd|opening_unbilled_usd|earned_to_unbilled_usd|invoiced_from_unbilled_usd|closing_unbilled_usd','One contract/month service balance roll-forward','contract_balance_id')
    reg('quickbooks/chart_of_accounts','account_id|account_name|account_type|financial_statement|normal_balance|cash_flow_class','One modeled GL account','account_id')
    reg('quickbooks/opening_trial_balance','account_id|balance_date|debit_usd|credit_usd|signed_balance_usd|explanation','One opening account balance; excluded from period activity','account_id')
    reg('quickbooks/client_invoices','invoice_id|client_id|contract_id|invoice_date|due_date|invoice_total_usd|record_scope|invoice_status_asof|open_balance_usd|journal_id','One client fee invoice, including opening receivables','invoice_id')
    reg('quickbooks/client_invoice_lines','invoice_line_id|invoice_id|contract_id|client_id|service_id|schedule_line_id|description|line_amount_usd|invoiced_to_deferred_usd|invoiced_from_unbilled_usd','One fee invoice allocation to a service','invoice_line_id')
    reg('quickbooks/credit_notes','credit_note_id|client_id|invoice_id|invoice_line_id|contract_id|service_id|credit_date|amount_usd|reason|recognition_id|journal_id','One post-service commercial fee concession','credit_note_id')
    reg('quickbooks/client_receipts','receipt_id|client_id|receipt_date|receipt_amount_usd|payment_method|bank_transaction_id|journal_id','One actual client ACH receipt','receipt_id')
    reg('quickbooks/receipt_applications','receipt_application_id|receipt_id|invoice_id|applied_date|applied_amount_usd','One client receipt application to an invoice','receipt_application_id')
    reg('quickbooks/vendors','vendor_id|vendor_name|vendor_type|email|payment_terms_days','One fictional vendor or named-system modeled supplier','vendor_id')
    reg('quickbooks/vendor_bills','bill_id|vendor_id|contractor_invoice_id|bill_date|due_date|service_month|bill_total_usd|record_scope|bill_status_asof|open_balance_usd|journal_id','One received AP bill','bill_id')
    reg('quickbooks/vendor_bill_lines','bill_line_id|bill_id|account_id|description|line_amount_usd|approved_work_id|source_line_id|project_id|contract_id|client_id','One AP line; freelance lines debit accrued liability','bill_line_id')
    reg('quickbooks/vendor_payments','vendor_payment_id|vendor_id|payment_date|payment_amount_usd|bank_transaction_id|journal_id','One actual vendor payment','vendor_payment_id')
    reg('quickbooks/vendor_payment_applications','vendor_application_id|vendor_payment_id|bill_id|applied_date|applied_amount_usd','One AP payment allocation','vendor_application_id')
    reg('quickbooks/ar_open_items','ar_item_id|invoice_id|client_id|contract_id|invoice_date|due_date|original_amount_usd|credit_applied_usd|cash_applied_usd|open_amount_usd|days_past_due|aging_bucket|as_of_date','One unpaid client invoice at cutoff','ar_item_id')
    reg('quickbooks/ap_open_items','ap_item_id|bill_id|vendor_id|bill_date|due_date|original_amount_usd|cash_applied_usd|open_amount_usd|days_past_due|aging_bucket|as_of_date','One unpaid vendor bill at cutoff','ap_item_id')
    reg('quickbooks/journals','journal_id|journal_date|source_system|source_type|source_id|memo|total_debit_usd|total_credit_usd','One in-period balanced journal','journal_id')
    reg('quickbooks/general_ledger','gl_line_id|journal_id|journal_date|account_id|debit_usd|credit_usd|source_system|source_type|source_id|client_id|contract_id|project_id|employee_id|service_month','One journal/account/dimension debit or credit','gl_line_id','Opening TB is separate. No year-end closing journals in this 24-month extract.',partition='journal_date')
    reg('quickbooks/monthly_trial_balance','tb_id|service_month|account_id|opening_signed_balance_usd|period_debits_usd|period_credits_usd|closing_signed_balance_usd','One account/month; signs debit minus credit','tb_id')
    reg('bank/accounts','bank_account_id|bank_name|account_name|currency|opening_balance_date|opening_balance_usd','One fictional agency operating bank account','bank_account_id')
    reg('bank/transactions','bank_transaction_id|bank_account_id|transaction_date|sequence|transaction_type|counterparty|reference_type|reference_id|money_in_usd|money_out_usd|signed_amount_usd|running_balance_usd|journal_id','One actual agency bank statement movement','bank_transaction_id',partition='transaction_date')
    reg('bank/monthly_statements','statement_id|bank_account_id|service_month|opening_balance_usd|total_money_in_usd|total_money_out_usd|closing_balance_usd|transaction_count','One monthly bank statement','statement_id')
    reg('planning/budget_versions','budget_version_id|budget_name|approved_date|period_start_date|period_end_date|is_original_approved|status|assumptions','One immutable original annual management budget','budget_version_id')
    reg('planning/monthly_budget','budget_line_id|budget_version_id|service_month|department|revenue_stream|account_id|client_id|project_id|budget_amount_usd|budget_hours|driver_note','One original monthly budget line; revenue and expense amounts positive','budget_line_id')
    reg('planning/headcount_capacity_plan','capacity_plan_id|plan_version_id|approved_date|service_month|department|planned_headcount|planned_paid_hours|planned_available_hours|target_billable_utilization|planned_salary_cost_usd|plan_status','One department/month frozen resource plan','capacity_plan_id')
    reg('planning/signed_future_commitments','commitment_id|schedule_line_id|contract_id|client_id|service_id|scheduled_invoice_date|scheduled_due_date|scheduled_amount_usd|amount_basis|overlap_key|as_of_date','One already-signed future billing item at cutoff','commitment_id','Convenience copy of future billing schedule, not another fact.')
    reg('planning/collection_expectations','collection_expectation_id|invoice_id|client_id|open_amount_usd|expected_receipt_date|collection_risk|basis|as_of_date','One management collection assumption for existing AR','collection_expectation_id','Expected date is not an actual receipt.')
    reg('planning/recurring_obligations','obligation_id|vendor_id|description|account_id|cadence|contract_start_date|contract_end_date|current_cycle_fee_usd|next_service_start_date|next_expected_bill_date|payment_terms_days|current_open_bill_id|overlap_rule|as_of_date','One active operating vendor obligation at cutoff','obligation_id')
    reg('planning/payroll_commitments','payroll_commitment_id|payroll_run_id|earned_end_date|scheduled_funding_date|net_pay_usd|withholding_plus_employer_tax_usd|benefits_usd|total_funding_usd|overlap_liability_accounts|as_of_date','One earned but unfunded payroll run at cutoff','payroll_commitment_id')
    reg('planning/contractor_accruals','contractor_accrual_id|approved_work_id|contractor_id|project_id|contract_id|earned_cost_usd|expected_invoice_date|expected_due_date|overlap_liability_account|as_of_date','One accepted but not yet invoiced freelance work item','contractor_accrual_id')
    reg('finance/debt_register','debt_id|lender_name|agreement_date|maturity_date|original_principal_usd|opening_principal_usd|annual_interest_rate|monthly_principal_usd|principal_asof_usd|is_synthetic_rate|as_of_date','One term loan; rate is an invented contract parameter','debt_id')
    reg('finance/debt_service','debt_service_id|debt_id|payment_date|principal_usd|interest_usd|total_payment_usd|closing_principal_usd|bank_transaction_id|journal_id','One actual loan repayment','debt_service_id')
    reg('finance/debt_schedule','debt_schedule_id|debt_id|scheduled_payment_date|scheduled_principal_usd|scheduled_interest_usd|scheduled_total_usd|known_asof_date|status','One future contractual debt payment, not an actual','debt_schedule_id')
    reg('finance/owner_distributions','distribution_id|distribution_date|amount_usd|bank_transaction_id|journal_id|policy','One actual owner distribution; financing only','distribution_id')
    reg('finance/prepaid_amortization','amortization_id|service_month|asset_account_id|expense_account_id|amount_usd|source_bill_id|journal_id','One monthly release of paid insurance asset','amortization_id')

CLIENTS={}; CONTRACTS={}; PROJECTS={}; SERVICES={}; TERMS={}; RET_MAP={}; EMP={}; COMP={}; AD_SPEND=defaultdict(int); EVENTS=[]; PAYE={}

def event(when,priority,kind,data):
    if START<=when<=CUT: EVENTS.append((when,priority,len(EVENTS),kind,data))

def company_and_staff():
    names=['Cedar Peak Outdoor','Willow Bend Dental Group','Morrow Home Goods','Canyon Trail Fitness','Beacon Ridge Solar','Copperline Learning','Maple & Moss Skincare','Prairie Home Services','Northstar Pet Supply','Harborlight B2B Software','Blue Mesa Travel','Aster Kitchenware','Summit Grove Wellness','Fieldstone Auto Care','Juniper Kids Apparel','Redwood Local Clinics','Fairhaven Coffee Roasters','Vela Safety Equipment','Pinecrest Garden Supply','Lumen Office Systems','Tidepool Home Textiles','Atlas Trail Nutrition','Prospect Birch Home','Prospect Oak Dental','Prospect Vista Equipment','Prospect Ember Wellness','Prospect Wren Software','Prospect Cove Travel']
    industries=['Outdoor retail','Dental services','Home goods','Fitness','Residential solar','Online learning','Beauty','Home services','Pet retail','B2B SaaS','Travel','Kitchen retail','Wellness','Automotive services','Apparel','Clinics','Food & beverage','Safety equipment','Garden retail','Office services','Home textiles','Nutrition']
    for i,name in enumerate(names,1):
        start=START if i<=14 else {15:date(2025,1,1),16:date(2025,3,1),17:date(2025,6,1),18:date(2025,9,1),19:date(2025,11,1),20:date(2026,2,1),21:date(2026,5,1),22:date(2026,8,1)}.get(i)
        end={5:date(2026,7,31),12:date(2026,3,31)}.get(i,date(2027,12,31))
        cid=f'CLI-{i:03d}'; CLIENTS[cid]={'i':i,'start':start,'end':end,'base':{1:12000,2:12000,3:13000,4:14000,6:10500,8:15000,9:13000}.get(i,9500+(i%6)*1250)}
        add('hubspot/companies',client_id=cid,company_name=name+' LLC',industry=industries[(i-1)%22],state_code=['CO','TX','IL','NC','WA','AZ'][i%6],email=f'finance.client{i:03d}@example.com',created_date=date(2024,7,1)+timedelta(days=(i*7)%105),lifecycle_stage='customer' if start else 'prospect',currency='USD',is_synthetic=True)
    staff=[('Avery Lane','Managing Partner','operations','overhead',150000),('Morgan Vale','Finance and Operations Lead','operations','overhead',96000),('Jordan Ellis','Business Development Lead','operations','overhead',102000),('Riley Brooks','Paid Media Lead','paid_media','delivery',108000),('Casey Rowan','Paid Media Strategist','paid_media','delivery',84000),('Quinn Parker','Paid Media Strategist','paid_media','delivery',80000),('Taylor Reed','Paid Media Specialist','paid_media','delivery',69000),('Alex Morgan','Paid Media Specialist','paid_media','delivery',66000),('Jamie Blake','Client Services Lead','client_services','delivery',98000),('Cameron Gray','Account Manager','client_services','delivery',76000),('Dakota Hayes','Account Manager','client_services','delivery',73000),('Reese Miller','Creative Lead','creative','delivery',102000),('Skyler Quinn','Designer','creative','delivery',73000),('Peyton Lee','Video Editor','creative','delivery',75000),('Finley Hart','Copywriter','creative','delivery',70000),('Robin Sage','Analytics Lead','analytics','delivery',112000),('Charlie West','Analytics Specialist','analytics','delivery',85000),('Emerson Fox','Analytics Specialist','analytics','delivery',81000),('River Cole','Paid Media Specialist','paid_media','delivery',71000),('Hayden Moss','Designer','creative','delivery',76000),('Blair Stone','Account Manager','client_services','delivery',80000),('Drew Lake','Analytics Specialist','analytics','delivery',88000),('Shawn Wren','Video Editor','creative','delivery',79000),('Kendall Finch','Paid Media Strategist','paid_media','delivery',88000)]
    hires={19:date(2025,3,1),20:date(2025,6,1),21:date(2025,10,1),22:date(2026,1,1),23:date(2026,4,1),24:date(2026,7,1)}
    departures={8:date(2025,12,31),15:date(2026,6,30)}
    for i,(name,role,dept,cl,sal) in enumerate(staff,1):
        eid=f'EMP-{i:03d}'; hire=hires.get(i,date(2023,1,1)+timedelta(days=i*17)); end=departures.get(i)
        EMP[eid]=add('gusto/employees',employee_id=eid,employee_name=name,email=f'{name.lower().replace(" ",".")}@example.com',role=role,department=dept,cost_class=cl,hire_date=hire,termination_date=end or '',employment_type='salaried_full_time',standard_week_hours=40)
        starts=[max(hire,date(2024,1,1))]+[date(y,1,1) for y in [2025,2026] if date(y,1,1)>hire and (not end or date(y,1,1)<=end)]
        for j,eff in enumerate(starts):
            # New hires keep offer salary until the next calendar-year review.
            n=sum(1 for y in [2025,2026] if hire<date(y,1,1)<=eff)
            annual=usd(dec(sal)*(D('1.04')**n))
            cid=f'COMP-{i:03d}-{j+1}'
            row=add('gusto/compensation_rates',compensation_id=cid,employee_id=eid,effective_start_date=eff,effective_end_date=(starts[j+1]-timedelta(days=1)) if j+1<len(starts) else (end or date(2026,12,31)),annual_salary_usd=annual,withholding_rate=D('.22')+D(i%4)/100,employer_tax_rate=D('.08'),monthly_employer_benefit_usd=usd(350),approved_date=eff-timedelta(days=20))
            COMP[cid]=row
    roles=sorted(set(e['role'] for e in EMP.values()))
    for i,role in enumerate(roles,1):
        base=225 if 'Lead' in role or 'Partner' in role else (200 if 'Specialist' in role or 'Strategist' in role else 185)
        for yr,start,end,mult in [(1,date(2024,1,1),date(2025,12,31),D(1)),(2,date(2026,1,1),date(2027,12,31),D('1.05'))]:
            add('contracts/rate_cards',rate_card_id=f'RATE-{i:02d}-{yr}',role=role,effective_start_date=start,effective_end_date=end,approved_date=start-timedelta(days=30),hourly_rate_usd=usd(base*mult))

def service(sid,co,pid,typ,sm,a,b,planned,approved,fee,hours='',scope='in_period',minimum=None):
    if a>CUT: scope='signed_future'
    minimum=(0 if typ=='hourly' else fee) if minimum is None else minimum
    r=add('delivery/service_obligations',service_id=sid,contract_id=co['contract_id'],client_id=co['client_id'],project_id=pid,service_type=typ,service_month=sm,service_start_date=a,service_end_date=b,planned_approval_date=planned,actual_approved_date=approved or '',agreed_minimum_fee_usd=usd(minimum),approved_fee_usd=usd(fee) if approved else '',approved_hours=hours,rate_card_basis='effective_role_rate' if typ=='hourly' else 'not_applicable',recognition_status='approved' if approved else 'signed_future' if scope=='signed_future' else 'pending_acceptance',record_scope=scope)
    SERVICES[sid]=r; return r

def project(co,pid,name,typ,hours,basis):
    r=add('timekeeping/projects',project_id=pid,client_id=co['client_id'],contract_id=co['contract_id'],project_name=name,project_type=typ,start_date=co['service_start_date'],end_date=co['current_end_date'],is_billable=True,original_hours_budget=dec(hours),original_cost_budget_usd=usd(dec(hours)*68),budget_basis=basis)
    PROJECTS[pid]=r; return r

def build_contracts():
    for cid,c in CLIENTS.items():
        if not c['start']: continue
        st=c['start']; prev=''; sequence=0
        while st<=date(2026,12,1) and st<=c['end']:
            signed=st-timedelta(days=20)
            if signed>CUT: break
            sequence+=1; end=shift(st,12)-timedelta(days=1); actualend=min(end,c['end'])
            con=f'CON-R-{cid[-3:]}-{sequence}'; pid=f'PRJ-R-{cid[-3:]}-{sequence}'
            base=c['base']
            if sequence>1 and c['i'] not in [1,3,6]: base=round(base*(1.045**(sequence-1)))
            if c['i']==1 and st>CUT: base=14000
            if c['i']==3 and st>=date(2026,11,1): base=15500
            variable=c['i'] in [6,10,18]
            model='percent_of_spend_with_minimum' if variable else 'flat_retainer'
            scope=82+(c['i']%5)*7
            if c['i']==3 and st>=date(2026,11,1): scope+=22
            quoted=base*12
            co=add('contracts/contracts',contract_id=con,client_id=cid,deal_id='DEAL-'+con,parent_contract_id=prev,contract_type='retainer',sow_name=f'Paid media, creative and analytics annual SOW {sequence}',signed_date=signed,service_start_date=st,original_end_date=end,current_end_date=actualend,original_contract_value_usd=usd(quoted),current_committed_minimum_usd=0,contract_ceiling_usd='',contract_value_basis='fixed_minimum_excludes_variable_spend_upside',payment_terms_days=30 if c['i']==4 else 15,billing_cadence='monthly_arrears' if variable else ('quarterly_advance' if c['i']==2 else 'monthly_service_start'),status_asof='signed_future' if st>CUT else 'terminated' if actualend<end else ('completed' if actualend<CUT else 'active'),currency='USD')
            CONTRACTS[con]=co; project(co,pid,f'{cid} integrated monthly retainer','retainer',scope*12,'original annual SOW hours; monthly budgets in monthly_terms')
            changes=[]
            if c['i']==3 and st<=date(2026,10,1)<=end: changes.append((date(2026,10,1),15500,D(0),scope+22,date(2026,9,20),'repricing_scope_reset','Extra creative variants accepted after prolonged unpaid scope creep'))
            if c['i']==6 and st<=date(2026,7,1)<=end: changes.append((date(2026,7,1),base,D('.07'),scope,date(2026,6,18),'variable_fee_repricing','Management percentage rises from 6% to 7%; minimum unchanged'))
            versions=[(st,base,(D('.07') if c['i']==6 and st>=date(2026,7,1) else D('.06')) if variable else D(0),scope,signed,'initial_sow','')]
            for ix,(eff,fee,rate,hrs,ap,typ,reason) in enumerate(changes,1):
                ch=f'CO-{con}-{ix}'
                add('contracts/change_orders',change_order_id=ch,contract_id=con,signed_date=ap,effective_date=eff,change_type=typ,fee_change_usd=usd((fee-base)*max(0,(end.year-eff.year)*12+end.month-eff.month+1)),scope_hours_change=hrs-scope,reason=reason,supersedes_version_id=f'VER-{con}-1')
                versions.append((eff,fee,rate,hrs,ap,typ,ch))
            for ix,(eff,fee,rate,hrs,ap,reason,ch) in enumerate(versions,1):
                vend=(versions[ix][0]-timedelta(days=1)) if ix<len(versions) else actualend
                add('contracts/contract_versions',contract_version_id=f'VER-{con}-{ix}',contract_id=con,version_number=ix,approved_date=ap,effective_start_date=eff,effective_end_date=vend,fee_model=model,monthly_minimum_fee_usd=usd(fee),spend_fee_rate=rate,scope_hours_month=hrs,scope_cost_budget_month_usd=usd(hrs*68),reason=reason,change_order_id=ch)
            m=st; committed=0
            while m<=actualend:
                vs=[v for v in T['contracts/contract_versions'] if v['contract_id']==con and v['effective_start_date']<=m<=v['effective_end_date']][-1]
                tid=f'TERM-{con}-{month(m)}'
                t=add('contracts/monthly_terms',term_id=tid,contract_id=con,contract_version_id=vs['contract_version_id'],client_id=cid,service_month=month(m),fee_model=model,monthly_minimum_fee_usd=vs['monthly_minimum_fee_usd'],spend_fee_rate=vs['spend_fee_rate'],scope_hours_budget=vs['scope_hours_month'],scope_cost_budget_usd=vs['scope_cost_budget_month_usd'],known_asof_date=vs['approved_date'])
                TERMS[tid]=t; RET_MAP[(cid,month(m))]=(co,pid,t); committed+=cents(vs['monthly_minimum_fee_usd']); m=shift(m,1)
            co['current_committed_minimum_usd']=money(committed)
            if actualend<end:
                endfee=base*max(0,(end.year-actualend.year)*12+end.month-actualend.month)
                add('contracts/change_orders',change_order_id=f'CO-{con}-TERM',contract_id=con,signed_date=date(2026,6,15) if c['i']==5 else date(2026,3,10),effective_date=actualend+timedelta(days=1),change_type='termination_release',fee_change_usd=usd(-endfee),scope_hours_change=0,reason='Client moved media buying in-house' if c['i']==5 else 'Client closed a product line; no renewal',supersedes_version_id=f'VER-{con}-1')
            prev=con; st=shift(st,12)
    # Explicitly priced fixed projects; approvals occur only when the deliverable is accepted.
    for k in range(26):
        st=shift(START,k); signed=st-timedelta(days=16)
        if signed>CUT: continue
        active=[cid for cid,c in CLIENTS.items() if c['start'] and c['start']<=st<=c['end']]
        cid=active[(k*3+2)%len(active)]; con=f'CON-F-{k+1:03d}'; pid=f'PRJ-F-{k+1:03d}'; end=me(shift(st,2)); fee=32000+(k%6)*5500; hrs=dec(fee)/160
        co=add('contracts/contracts',contract_id=con,client_id=cid,deal_id='DEAL-'+con,parent_contract_id='',contract_type='fixed_project',sow_name=['Creative launch system','Measurement rebuild','Landing-page creative package'][k%3],signed_date=signed,service_start_date=st,original_end_date=end,current_end_date=end,original_contract_value_usd=usd(fee),current_committed_minimum_usd=usd(fee),contract_ceiling_usd=usd(fee),contract_value_basis='fixed_distinct_deliverables',payment_terms_days=30,billing_cadence='milestone_advance_then_acceptance_arrears',status_asof='signed_future' if st>CUT else 'active' if end>=CUT else 'completed',currency='USD')
        CONTRACTS[con]=co; project(co,pid,co['sow_name'], 'fixed_project',hrs,'original total project budget; no automatic overtime fee')
        for j,part in enumerate([D('.25'),D('.35'),D('.40')],1):
            pm=shift(st,j-1); planned=date(pm.year,pm.month,[20,25,28][j-1]); accepted=planned+timedelta(days=18 if k==8 and j==2 else (4 if k%7==3 and j==3 else 0)); actual=accepted if accepted<=CUT else None
            sid=f'SVC-{con}-M{j}'; amt=usd(dec(fee)*part)
            service(sid,co,pid,'fixed_milestone',month(pm),pm,me(pm),planned,actual,amt)
            add('contracts/milestones',milestone_id=f'MS-{con}-{j}',contract_id=con,project_id=pid,sequence=j,deliverable=['Approved creative strategy and briefs','Accepted production assets and tracking implementation','Signed launch QA and final handoff'][j-1],planned_approval_date=planned,actual_approved_date=actual or '',approval_status='approved' if actual else 'planned',agreed_fee_usd=amt,original_hours_budget=(hrs*part).quantize(D('.01')),original_cost_budget_usd=usd(hrs*part*68),service_id=sid)
    for n in [1,3,4,6,8,10,15,20]:
        cid=f'CLI-{n:03d}'; st=max(date(2024,10,1),CLIENTS[cid]['start'] if n>14 else date(2024,10,1)); con=f'CON-H-{n:03d}'; pid=f'PRJ-H-{n:03d}'
        co=add('contracts/contracts',contract_id=con,client_id=cid,deal_id='DEAL-'+con,parent_contract_id='',contract_type='hourly',sow_name='Approved-hours analytics and experiments',signed_date=st-timedelta(days=12),service_start_date=st,original_end_date=date(2027,10,31),current_end_date=date(2027,10,31),original_contract_value_usd=usd(36000),current_committed_minimum_usd=usd(0),contract_ceiling_usd=usd(120000),contract_value_basis='estimate_not_guarantee_T_and_M_ceiling_separate',payment_terms_days=30,billing_cadence='approved_hours_monthly_arrears',status_asof='active',currency='USD')
        CONTRACTS[con]=co; project(co,pid,'Hourly analytics and experiments','hourly',180,'estimated 12-month hours, not committed recurring fees')
    for tid,name,billable,scope in [('TSK-STRATEGY','Strategy and account management',True,'in_scope'),('TSK-OPTIMIZE','Campaign optimization',True,'in_scope'),('TSK-CREATIVE','Creative production',True,'in_scope'),('TSK-ANALYTICS','Analytics and measurement',True,'in_scope'),('TSK-REWORK','Unpriced extra creative revisions',True,'scope_creep'),('TSK-ADMIN','Administration and internal meetings',False,'non_billable'),('TSK-TRAIN','Training and business development',False,'non_billable')]:
        add('timekeeping/tasks',task_id=tid,task_name=name,is_billable=billable,scope_class=scope)
    add('timekeeping/projects',project_id='PRJ-INTERNAL',client_id='',contract_id='',project_name='Internal, bench and business development',project_type='internal',start_date=START,end_date=CUT,is_billable=False,original_hours_budget='',original_cost_budget_usd='',budget_basis='not_applicable')
    PROJECTS['PRJ-INTERNAL']=T['timekeeping/projects'][-1]

def media():
    campaigns={}
    for platform,code in [('meta_ads','META'),('google_ads','GOOG')]:
        campaigns[platform]={}
        for cid,c in CLIENTS.items():
            if not c['start']: continue
            aid=f'{code}-ACCT-{cid[-3:]}'
            add(platform+'/ad_accounts',ad_account_id=aid,client_id=cid,account_name=f'{cid} client-owned {code}',account_owner='client',payer_client_id=cid,funding_responsibility='CLIENT_DIRECT',agency_pays_platform=False,currency='USD',timezone='America/Chicago')
            for j in [1,2]:
                camp=f'{code}-CMP-{cid[-3:]}-{j}'; campaigns[platform][(cid,j)]=camp
                add(platform+'/campaigns',campaign_id=camp,ad_account_id=aid,client_id=cid,campaign_name=('Prospecting' if j==1 else 'Retargeting') if code=='META' else ('Nonbrand search' if j==1 else 'Brand and shopping'),objective='sales_or_qualified_leads',start_date=c['start'],end_date=c['end'],attribution_model='platform_reported_7d_click_1d_view' if code=='META' else 'platform_reported_data_driven',attribution_window='7_day_click_1_day_view' if code=='META' else '30_day_click',conversion_unit='platform_attributed_conversion')
                for co in CONTRACTS.values():
                    if co['client_id']==cid and co['contract_type']=='retainer': add(platform+'/campaign_contract_map',mapping_id=f'MAP-{camp}-{co["contract_id"]}',campaign_id=camp,ad_account_id=aid,client_id=cid,contract_id=co['contract_id'],effective_start_date=co['service_start_date'],effective_end_date=co['current_end_date'])
    for mi,m in enumerate(MONTHS):
        for cid,c in CLIENTS.items():
            if (cid,month(m)) not in RET_MAP: continue
            co,pid,t=RET_MAP[(cid,month(m))]
            seasonal={11:1.28,12:1.18,1:.89,2:.92,6:.96,7:.94}.get(m.month,1.0)
            base=60000+(c['i']%7)*9500
            if c['i']==1: base=65000+mi*5300 # Story: flat agency fee while media budget grows.
            else: base*=1+mi*.022
            total=cents(base*seasonal*(1+RNG.uniform(-.035,.035)))
            platforms=alloc(total,[.56 if c['i']%2 else .44,.44 if c['i']%2 else .56])
            for (platform,code),ptotal in zip([('meta_ads','META'),('google_ads','GOOG')],platforms):
                aid=f'{code}-ACCT-{cid[-3:]}'; days=[m+timedelta(days=d) for d in range(calendar.monthrange(m.year,m.month)[1])]
                perday=alloc(ptotal,[(.9 if d.weekday()>4 else 1.05)*RNG.uniform(.8,1.2) for d in days])
                for d,dtot in zip(days,perday):
                    for j,sp in zip([1,2],alloc(dtot,[.78,.22])):
                        camp=campaigns[platform][(cid,j)]; click_cost=1.2+(c['i']%5)*.38+(.25 if code=='GOOG' else 0)+mi*.006
                        clicks=max(1,round(float(money(sp))/click_cost*RNG.uniform(.9,1.1))); impressions=max(clicks,round(clicks/(.018 if code=='META' else .041)))
                        conv=usd(dec(clicks)*dec(.027+(c['i']%4)*.006)*dec(RNG.uniform(.85,1.15))); value=usd(conv*dec(75+(c['i']%8)*35))
                        r=dict(metric_id=f'{code}-MET-{iso(d)}-{cid[-3:]}-{j}',metric_date=d,campaign_id=camp,ad_account_id=aid,client_id=cid,contract_id=co['contract_id'],payer_client_id=cid,funding_responsibility='CLIENT_DIRECT',spend_usd=money(sp),impressions=impressions,clicks=clicks,attributed_conversions=conv,attributed_conversion_value_usd=value,currency='USD')
                        if code=='GOOG': r['cost_micros']=sp*10000
                        add(platform+'/daily_metrics',**r)
                add(platform+'/monthly_billing',platform_statement_id=f'{code}-STMT-{cid[-3:]}-{month(m)}',ad_account_id=aid,client_id=cid,service_month=month(m),statement_date=me(m),media_spend_usd=money(ptotal),payer_client_id=cid,funding_responsibility='CLIENT_DIRECT',agency_cash_amount_usd=usd(0),client_payment_status='CLIENT_DIRECT_SETTLEMENT_NOT_OBSERVED')
            AD_SPEND[(cid,month(m))]=total
            earned=max(cents(t['monthly_minimum_fee_usd']),cents(money(total)*t['spend_fee_rate'])) if t['spend_fee_rate'] else cents(t['monthly_minimum_fee_usd'])
            sid=f'SVC-{co["contract_id"]}-{month(m)}'; s=service(sid,co,pid,'retainer',month(m),m,me(m),me(m),me(m),money(earned),minimum=t['monthly_minimum_fee_usd'])
            add('contracts/fee_calculations',calculation_id=f'FEE-{co["contract_id"]}-{month(m)}',term_id=t['term_id'],contract_id=co['contract_id'],client_id=cid,service_month=month(m),media_spend_usd=money(total),spend_fee_rate=t['spend_fee_rate'],percentage_fee_usd=usd(money(total)*t['spend_fee_rate']),minimum_fee_usd=t['monthly_minimum_fee_usd'],earned_fee_usd=money(earned),service_id=sid)
    for (cid,mon),(co,pid,t) in RET_MAP.items():
        m=date.fromisoformat(mon+'-01')
        if m>CUT: service(f'SVC-{co["contract_id"]}-{mon}',co,pid,'retainer',mon,m,me(m),me(m),None,t['monthly_minimum_fee_usd'])

def active(e,d): return e['hire_date']<=d and (not e['termination_date'] or e['termination_date']>=d)
def comp_for(eid,d): return next(c for c in COMP.values() if c['employee_id']==eid and c['effective_start_date']<=d<=c['effective_end_date'])
def rate_for(role,d): return next(r for r in T['contracts/rate_cards'] if r['role']==role and r['effective_start_date']<=d<=r['effective_end_date'])
def project_weights(m,dept,actual=False):
    out=[]
    for p in PROJECTS.values():
        if p['project_type']=='internal' or p['start_date']>me(m) or p['end_date']<m: continue
        cid=p['client_id']; typ=p['project_type']; con=p['contract_id']
        if typ=='retainer':
            t=RET_MAP.get((cid,month(m)))
            if not t or t[0]['contract_id']!=con: continue
            weight=float(t[2]['scope_hours_budget'])
            if actual and cid=='CLI-003' and date(2026,4,1)<=m<=date(2026,9,1): weight*=2.55
            mult={'paid_media':1.2,'client_services':1.0,'creative':.7,'analytics':.7}.get(dept,.2)
        elif typ=='fixed_project': weight=float(p['original_hours_budget'])/3; mult={'paid_media':.3,'client_services':.45,'creative':1.45,'analytics':1.2}.get(dept,.2)
        else: weight=11; mult=2.7 if dept=='analytics' else (.25 if dept=='paid_media' else .08)
        out.append((p,weight*mult))
    return out

def timesheets_and_capacity():
    holidays={date(2024,11,28),date(2024,11,29),date(2024,12,25),date(2025,1,1),date(2025,5,26),date(2025,7,4),date(2025,9,1),date(2025,11,27),date(2025,11,28),date(2025,12,25),date(2026,1,1),date(2026,5,25),date(2026,7,3),date(2026,9,7)}
    for i in range((CUT-START).days+1):
        d=START+timedelta(days=i); add('timekeeping/work_calendar',calendar_date=d,is_weekday=d.weekday()<5,company_holiday=d in holidays,standard_paid_hours=8 if d.weekday()<5 else 0)
    for mi,m in enumerate(MONTHS):
        for eid,e in EMP.items():
            days=[d for d in weekdays(m,me(m)) if active(e,d)]
            if not days: continue
            # Stable client pods make the staff plan explain actual delivery assignments.
            pod=int(eid[-3:])%3
            planned=[x for x in project_weights(m,e['department']) if int(x[0]['client_id'][-3:])%3==pod]
            actualw=[x for x in project_weights(m,e['department'],True) if int(x[0]['client_id'][-3:])%3==pod]
            pct=.78 if e['cost_class']=='delivery' else 0
            if m.month in [11,12]: pct+=.04 if pct else 0
            if m in [date(2026,8,1),date(2026,9,1)]: pct-=.15 if pct else 0
            if m==date(2026,10,1): pct-=.055 if pct else 0
            # Frozen plan is deliberately not changed for later scope creep/utilization outcomes.
            if planned and e['cost_class']=='delivery':
                picks=planned; ph=alloc(round(len(days)*8*.76*4),[w for _,w in picks])
                for (p,_),h in zip(picks,ph):
                    add('timekeeping/staff_allocations',allocation_plan_id=f'AP-{eid}-{month(m)}-{p["project_id"]}',employee_id=eid,project_id=p['project_id'],contract_id=p['contract_id'],service_month=month(m),planned_hours=dec(h)/4,approved_date=m-timedelta(days=1),plan_version_id='RES-'+month(m))
            for d in days:
                off=8 if d in holidays else (RNG.choice([4,8]) if RNG.random()<.039 else 0)
                add('timekeeping/daily_capacity',capacity_id=f'CAP-{eid}-{iso(d)}',employee_id=eid,work_date=d,paid_capacity_hours=8,paid_time_off_hours=off,available_work_hours=8-off)
                if off: add('timekeeping/time_off',time_off_id=f'PTO-{eid}-{iso(d)}',employee_id=eid,off_date=d,hours=off,leave_type='company_holiday' if d in holidays else 'paid_leave',approval_date=d if d in holidays else d-timedelta(days=7),approval_status='approved')
                available=8-off
                if not available: continue
                units=available*4; billunits=min(units,max(0,round(units*(pct+RNG.uniform(-.11,.11))))) if pct else 0
                if billunits:
                    selected=RNG.choices(actualw,weights=[w for _,w in actualw],k=2)
                    combined=defaultdict(int)
                    for (p,_),hu in zip(selected,alloc(billunits,[.6,.4])): combined[p['project_id']]+=hu
                    for pid,hu in combined.items():
                        p=PROJECTS[pid]; typ=p['project_type']; rework=typ=='retainer' and p['client_id']=='CLI-003' and date(2026,4,1)<=m<=date(2026,9,1) and RNG.random()<.55
                        task='TSK-REWORK' if rework else {'paid_media':'TSK-OPTIMIZE','client_services':'TSK-STRATEGY','creative':'TSK-CREATIVE','analytics':'TSK-ANALYTICS'}[e['department']]
                        rate=rate_for(e['role'],d) if typ=='hourly' else None
                        # A few October hourly entries remain submitted and cannot earn fees yet.
                        approved=not (typ=='hourly' and d>=date(2026,10,29) and int(eid[-3:])%3==0)
                        add('timekeeping/timesheets',time_entry_id=f'TIME-{len(T["timekeeping/timesheets"])+1:07d}',employee_id=eid,role=e['role'],project_id=pid,task_id=task,client_id=p['client_id'],contract_id=p['contract_id'],work_date=d,hours=dec(hu)/4,billable=True,approval_status='approved' if approved else 'submitted',approved_date=min(me(m),d+timedelta(days=2)) if approved else '',billing_treatment='approved_hours_times_rate' if typ=='hourly' else 'included_in_retainer' if typ=='retainer' else 'included_in_fixed_fee',rate_card_id=rate['rate_card_id'] if rate else '',billable_rate_usd=rate['hourly_rate_usd'] if rate else '',is_scope_rework=rework)
                if units-billunits:
                    add('timekeeping/timesheets',time_entry_id=f'TIME-{len(T["timekeeping/timesheets"])+1:07d}',employee_id=eid,role=e['role'],project_id='PRJ-INTERNAL',task_id='TSK-ADMIN' if RNG.random()<.75 else 'TSK-TRAIN',client_id='',contract_id='',work_date=d,hours=dec(units-billunits)/4,billable=False,approval_status='approved',approved_date=min(me(m),d+timedelta(days=1)),billing_treatment='not_billable',rate_card_id='',billable_rate_usd='',is_scope_rework=False)
    # Keep two known submitted October entries, awaiting client-approved hourly billing.
    pending=sorted([t for t in T['timekeeping/timesheets'] if t['billing_treatment']=='approved_hours_times_rate' and month(t['work_date'])=='2026-10'],key=lambda t:(t['work_date'],t['time_entry_id']))[-2:]
    for t in pending: t['approval_status']='submitted'; t['approved_date']=''
    hourly=defaultdict(lambda:[D(0),0])
    for t in T['timekeeping/timesheets']:
        if t['billing_treatment']=='approved_hours_times_rate' and t['approval_status']=='approved':
            a=hourly[(t['contract_id'],month(t['work_date']))]; a[0]+=t['hours']; a[1]+=cents(t['hours']*t['billable_rate_usd'])
    for (con,mon),(hours,fee) in hourly.items():
        co=CONTRACTS[con]; m=date.fromisoformat(mon+'-01'); sid=f'SVC-{con}-{mon}'; service(sid,co,'PRJ-H-'+co['client_id'][-3:],'hourly',mon,m,me(m),me(m),me(m),money(fee),hours)
    co=CONTRACTS['CON-H-001']; service('SVC-OPEN-H-001',co,'PRJ-H-001','hourly','2024-10',date(2024,10,1),date(2024,10,31),date(2024,10,31),date(2024,10,31),6000,30,'opening_item')

if __name__=='__main__':
    raise SystemExit('Run work/run_build.py after all build modules have been written.')
