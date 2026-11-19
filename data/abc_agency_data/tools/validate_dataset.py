"""Independent validator. Reads saved CSVs only; never imports generator modules.

Usage: python validate_dataset.py [dataset_folder]
Money is converted to integer cents with Decimal. Exit code 1 means failure.
"""
from __future__ import annotations
import csv, hashlib, json, re, sys
from collections import defaultdict, Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

D=Decimal
START='2024-11-01'; CUT='2026-10-31'; OPEN_DATE='2024-10-31'
def c(x): return int((D(x or '0')*100).quantize(D('1'),rounding=ROUND_HALF_UP))
def q(x): return (D(x)/100).quantize(D('.01'))
def dec(x): return D(x or '0')
def mon(x): return x[:7]
def dt(x): return date.fromisoformat(x)
def csv_read(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def write_csv(p,rows,fields=None):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]),lineterminator='\n'); w.writeheader(); w.writerows(rows)
def sumc(rows,col): return sum(c(r[col]) for r in rows)
def group(rows,key):
    out=defaultdict(list)
    for r in rows: out[r[key]].append(r)
    return out

class Checks:
    def __init__(self): self.data={}
    def test(self,name,ok,detail='',diff=0):
        if name not in self.data: self.data[name]=dict(check_name=name,status='PASS',evaluated=0,failures=0,max_absolute_difference_cents=0,examples=[])
        r=self.data[name]; r['evaluated']+=1; r['max_absolute_difference_cents']=max(r['max_absolute_difference_cents'],abs(int(diff)))
        if not ok:
            r['status']='FAIL'; r['failures']+=1
            if len(r['examples'])<4: r['examples'].append(str(detail)[:350])
    def equal(self,name,a,b,detail=''): self.test(name,a==b,f'{detail}: actual={a} expected={b}',a-b)
    def rows(self): return [{**r,'examples':' | '.join(r['examples'])} for r in self.data.values()]

def validate(root:Path,write_reports=True):
    ck=Checks(); schemas=json.loads((root/'metadata/table_schemas.json').read_text(encoding='utf-8')); tables={}; physical=[]
    manifest={r['relative_path']:r for r in csv_read(root/'metadata/file_manifest.csv')}
    for key,s in schemas.items():
        rows=[]
        for path in s['physical_files']:
            p=root/path; physical.append(path); raw=p.read_bytes(); ck.test('CSV UTF8 BOM present',raw.startswith(b'\xef\xbb\xbf'),path)
            with p.open(encoding='utf-8-sig',newline='') as f:
                rd=csv.DictReader(f); ck.test('CSV headers match declared schemas',rd.fieldnames==s['fields'],path); rr=list(rd)
            ck.test('Source SHA256 matches manifest',hashlib.sha256(raw).hexdigest()==manifest[path]['sha256'],path)
            ck.equal('Manifest row counts',len(rr),int(manifest[path]['row_count']),path); ck.equal('Manifest byte sizes',len(raw),int(manifest[path]['byte_size']),path)
            if s['partition_column']:
                for r in rr: ck.test('Monthly physical partitions match row dates',mon(r[s['partition_column']])==p.stem,path)
            rows.extend(rr)
        tables[key]=rows; seen=set()
        for r in rows:
            pk=tuple(r[k] for k in s['primary_key']); ck.test('Primary keys populated and unique',all(pk) and pk not in seen,f'{key} {pk}'); seen.add(pk)
            ck.test('CSV row widths match schema',None not in r and all(v is not None for v in r.values()),f'{key} {pk}')
            for col,typ in s['types'].items():
                val=r[col]
                ck.test('Required fields populated',bool(val) or s['nullable'][col],f'{key}.{col} {pk}')
                if val=='': continue
                ok=True
                try:
                    if typ=='decimal_usd_2dp': ok=bool(re.fullmatch(r'-?\d+\.\d{2}',val)) and D(val).is_finite()
                    elif typ=='decimal': ok=D(val).is_finite()
                    elif typ=='integer': ok=bool(re.fullmatch(r'-?\d+',val))
                    elif typ=='date_iso': ok=dt(val).isoformat()==val
                    elif typ=='month_iso': ok=dt(val+'-01').strftime('%Y-%m')==val
                    elif typ=='boolean': ok=val in ['True','False']
                except Exception: ok=False
                ck.test('Declared data types and money precision',ok,f'{key}.{col}={val} {pk}')
                if 'email' in col: ck.test('Fictional contact domain',val.endswith('@example.com'),val)
    ck.test('Manifest covers sources exactly',set(physical)==set(manifest),str(set(manifest)^set(physical)))
    actual_files={p.relative_to(root).as_posix() for p in (root/'sources').rglob('*.csv')}; ck.test('No undeclared source CSV files',actual_files==set(physical),str(actual_files^set(physical)))
    catalogs=csv_read(root/'metadata/table_catalog.csv')
    for r in catalogs: ck.equal('Table catalog row counts',len(tables[r['logical_table']]),int(r['row_count']),r['logical_table'])
    dictionary=csv_read(root/'metadata/data_dictionary.csv'); actual_dict={(r['logical_table'],r['column_name']) for r in dictionary}; expected_dict={(k,f) for k,s in schemas.items() for f in s['fields']}; ck.test('Dictionary covers every source column',actual_dict==expected_dict)
    for f in csv_read(root/'metadata/relationships.csv'):
        target={r[f['to_column']] for r in tables[f['to_table']]}; counts=Counter(r[f['to_column']] for r in tables[f['to_table']]); ck.test('Foreign-key targets unique',all(n==1 for n in counts.values()),f'{f["to_table"]}.{f["to_column"]}')
        for r in tables[f['from_table']]:
            value=r[f['from_column']]; ck.test('Foreign keys resolve',value in target or (not value and f['nullable']=='True'),f'{f["from_table"]}.{f["from_column"]}={value}')
    # Observed facts have no future dates; future due/term/plan dates are intentionally permitted.
    actual_fields={
      'hubspot/deals':['created_date','actual_close_date'], 'hubspot/deal_stage_history':['changed_date'],
      'contracts/contracts':['signed_date'], 'contracts/contract_versions':['approved_date'], 'contracts/change_orders':['signed_date'],
      'contracts/milestones':['actual_approved_date'], 'contracts/rate_cards':['approved_date'],
      'timekeeping/daily_capacity':['work_date'],'timekeeping/timesheets':['work_date','approved_date'],'timekeeping/time_off':['off_date','approval_date'],
      'gusto/employees':['hire_date','termination_date'],'gusto/payroll_runs':['earned_start_date','earned_end_date','actual_funding_date'],
      'gusto/payroll_earnings':['earned_start_date','earned_end_date'],'gusto/payroll_funding':['funding_date'],
      'freelancers/approved_work':['service_start_date','service_end_date','approved_date'],'freelancers/invoices':['invoice_date'],
      'delivery/service_obligations':['actual_approved_date'],'delivery/recognition_events':['recognition_date'],
      'quickbooks/client_invoices':['invoice_date'],'quickbooks/credit_notes':['credit_date'],'quickbooks/client_receipts':['receipt_date'],
      'quickbooks/vendor_bills':['bill_date'],'quickbooks/vendor_payments':['payment_date'],'quickbooks/journals':['journal_date'],
      'quickbooks/general_ledger':['journal_date'],'bank/transactions':['transaction_date'],
      'meta_ads/daily_metrics':['metric_date'],'google_ads/daily_metrics':['metric_date'],
      'finance/debt_service':['payment_date'],'finance/owner_distributions':['distribution_date'],
    }
    for tab,fields in actual_fields.items():
        for r in tables[tab]:
            for f in fields:
                if r[f]: ck.test('No actual facts after historical cutoff',r[f]<=CUT,f'{tab}.{f}={r[f]}')
    inperiod=[('bank/transactions','transaction_date'),('quickbooks/general_ledger','journal_date'),('delivery/recognition_events','recognition_date'),('timekeeping/timesheets','work_date'),('meta_ads/daily_metrics','metric_date'),('google_ads/daily_metrics','metric_date')]
    for tab,col in inperiod:
        for r in tables[tab]: ck.test('In-period actuals stay inside 24-month window',START<=r[col]<=CUT,f'{tab} {r[col]}')
    months=sorted({r['service_month'] for r in tables['bank/monthly_statements']}); ck.test('Exactly 24 consecutive actual months',months==[f'{y}-{m:02d}' for y,m in [(2024,11),(2024,12)]+[(2025,m) for m in range(1,13)]+[(2026,m) for m in range(1,11)]])
    idx={key:{r[schemas[key]['primary_key'][0]]:r for r in rows} for key,rows in tables.items() if len(schemas[key]['primary_key'])==1}
    co=idx['contracts/contracts']; proj=idx['timekeeping/projects']; emp=idx['gusto/employees']; svc=idx['delivery/service_obligations']; inv=idx['quickbooks/client_invoices']; bills=idx['quickbooks/vendor_bills']; stages=idx['hubspot/pipeline_stages']
    gl=tables['quickbooks/general_ledger']; byjournal=group(gl,'journal_id'); opening={r['account_id']:c(r['signed_balance_usd']) for r in tables['quickbooks/opening_trial_balance']}
    ck.equal('Opening trial balance balances',sum(opening.values()),0)
    for r in tables['quickbooks/opening_trial_balance']: ck.equal('Opening TB debit-credit signs',c(r['debit_usd'])-c(r['credit_usd']),c(r['signed_balance_usd']),r['account_id'])
    activity=defaultdict(lambda:[0,0]); jaccounts={}
    for jid,lines in byjournal.items():
        jr=idx['quickbooks/journals'][jid]; dr=sumc(lines,'debit_usd'); cr=sumc(lines,'credit_usd'); ck.equal('Every journal balances to cents',dr,cr,jid); ck.equal('Journal header debit total',dr,c(jr['total_debit_usd']),jid); ck.equal('Journal header credit total',cr,c(jr['total_credit_usd']),jid)
        acc=defaultdict(int)
        for l in lines:
            d,cc=c(l['debit_usd']),c(l['credit_usd']); ck.test('GL sides nonnegative and one-sided',d>=0 and cc>=0 and (bool(d)^bool(cc)),l['gl_line_id']); acc[l['account_id']]+=d-cc
            ck.test('GL journal date and provenance match header',all(l[f]==jr[f] for f in ['journal_date','source_system','source_type','source_id']),l['gl_line_id'])
            a=activity[(mon(l['journal_date']),l['account_id'])]; a[0]+=d; a[1]+=cc
        jaccounts[jid]=acc
    ck.test('All journal headers have GL lines',set(byjournal)==set(idx['quickbooks/journals']))
    tb=idx['quickbooks/monthly_trial_balance']; balances=opening.copy(); close={}
    for m in months:
        for aid in opening:
            r=tb['TB-'+m+'-'+aid]; dr,cr=activity[(m,aid)]; ck.equal('TB opening continuity',c(r['opening_signed_balance_usd']),balances[aid],m+' '+aid); ck.equal('TB monthly debits equal GL',c(r['period_debits_usd']),dr,m+' '+aid); ck.equal('TB monthly credits equal GL',c(r['period_credits_usd']),cr,m+' '+aid); balances[aid]+=dr-cr; ck.equal('TB closing equals GL roll-forward',c(r['closing_signed_balance_usd']),balances[aid],m+' '+aid); close[(m,aid)]=balances[aid]
        ck.equal('Monthly TB balances to cents',sum(balances.values()),0,m)
    # Contract/deal integrity and commercial changes.
    term_by=defaultdict(list)
    for eid,rr in group(tables['gusto/compensation_rates'],'employee_id').items():
        previous_end=''
        for r in sorted(rr,key=lambda x:x['effective_start_date']):
            ck.test('Compensation effective ranges are nonempty and employed',r['effective_start_date']<=r['effective_end_date'] and (not emp[eid]['termination_date'] or r['effective_end_date']<=emp[eid]['termination_date']),r['compensation_id'])
            ck.test('Employee compensation ranges never overlap',not previous_end or r['effective_start_date']>previous_end,r['compensation_id']); previous_end=r['effective_end_date']
    for t in tables['contracts/monthly_terms']:
        cc=co[t['contract_id']]; v=idx['contracts/contract_versions'][t['contract_version_id']]; term_by[t['contract_id']].append(t)
        ck.test('Retainer terms inside signed contract dates',cc['service_start_date'][:7]<=t['service_month']<=cc['current_end_date'][:7],t['term_id'])
        ck.test('Retainer versions approved before effective service',v['approved_date']<=t['service_month']+'-01' and v['effective_start_date'][:7]<=t['service_month']<=v['effective_end_date'][:7],t['term_id'])
        ck.test('Monthly terms match effective version',all(t[a]==v[b] for a,b in [('fee_model','fee_model'),('monthly_minimum_fee_usd','monthly_minimum_fee_usd'),('spend_fee_rate','spend_fee_rate'),('scope_hours_budget','scope_hours_month'),('scope_cost_budget_usd','scope_cost_budget_month_usd')]),t['term_id'])
    for con,cc in co.items():
        deal=idx['hubspot/deals'][cc['deal_id']]; ck.test('Signed contract has exactly matching won deal',deal['contract_id']==con and deal['stage_id']=='closed_won' and deal['client_id']==cc['client_id'] and deal['actual_close_date']==cc['signed_date'],con)
        ck.equal('Won quote equals original SOW value',c(deal['quoted_value_usd']),c(cc['original_contract_value_usd']),con)
        if cc['contract_type']=='retainer': ck.equal('Amended retainer minimum equals signed service months',sumc(term_by[con],'monthly_minimum_fee_usd'),c(cc['current_committed_minimum_usd']),con)
        if cc['contract_type']=='hourly': ck.equal('Hourly ceilings not guaranteed recurring revenue',c(cc['current_committed_minimum_usd']),0,con)
        ck.test('Commercial dates logical',cc['signed_date']<=cc['service_start_date']<=cc['current_end_date']<=cc['original_end_date'],con)
        expected_status='signed_future' if cc['service_start_date']>CUT else 'terminated' if cc['current_end_date']<cc['original_end_date'] else 'completed' if cc['current_end_date']<CUT else 'active'
        ck.test('Contract status respects historical cutoff',cc['status_asof']==expected_status,con+' '+cc['status_asof'])
        if cc['parent_contract_id']:
            parent=co[cc['parent_contract_id']]; ck.test('Renewal retains client and follows previous term',parent['client_id']==cc['client_id'] and cc['service_start_date']>parent['current_end_date'],con)
            if cc['client_id'] in ['CLI-003','CLI-006'] and cc['service_start_date']>='2026-11-01':
                pterms=sorted(term_by.get(parent['contract_id'],[r for r in tables['contracts/monthly_terms'] if r['contract_id']==parent['contract_id']]),key=lambda r:r['service_month']); nterms=sorted(term_by.get(con,[r for r in tables['contracts/monthly_terms'] if r['contract_id']==con]),key=lambda r:r['service_month'])
                ck.test('Renewals preserve agreed October fee and scope changes',all(pterms[-1][f]==nterms[0][f] for f in ['monthly_minimum_fee_usd','spend_fee_rate','scope_hours_budget']),con)
    histories=group(tables['hubspot/deal_stage_history'],'deal_id')
    for did,deal in idx['hubspot/deals'].items():
        hist=histories[did]; ordered=sorted(hist,key=lambda r:(r['changed_date'],r['stage_event_id'])); previous=''
        for h in ordered:
            ck.test('Pipeline history stage continuity',h['from_stage_id']==previous,did+' '+h['stage_event_id']); previous=h['to_stage_id']
            ck.test('Pipeline history probability matches stage',dec(h['probability'])==dec(stages[h['to_stage_id']]['probability']),h['stage_event_id'])
        ck.test('Deal current stage equals latest observed history',ordered[-1]['to_stage_id']==deal['stage_id'],did)
        ck.test('Unsigned open pipeline excludes signed contract',deal['stage_id'] in ['closed_won','closed_lost'] or deal['contract_id']=='',did)
    for r in tables['hubspot/deal_monthly_snapshots']:
        valid=[h for h in histories[r['deal_id']] if h['changed_date']<=r['snapshot_date']]; last=sorted(valid,key=lambda h:(h['changed_date'],h['stage_event_id']))[-1]
        include=r['stage_id'] not in ['closed_won','closed_lost']; ck.test('Historical pipeline snapshot uses only known events',r['stage_id']==last['to_stage_id'] and r['probability']==last['probability'] and r['expected_close_date']==last['expected_close_date'],r['snapshot_id']); ck.test('Won-lost deals excluded from open pipeline',r['include_in_pipeline']==str(include),r['snapshot_id']); expected=c(dec(r['quoted_value_usd'])*dec(r['probability'])) if include else 0; ck.equal('Weighted open pipeline arithmetic',c(r['weighted_pipeline_usd']),expected,r['snapshot_id'])
        if r['snapshot_date']==CUT:
            current=idx['hubspot/deals'][r['deal_id']]; ck.test('Cutoff CRM snapshot agrees with current deal fields',all(r[f]==current[f] for f in ['client_id','stage_id','probability','expected_close_date','quoted_value_usd','contract_id']),r['deal_id'])
    # Client-owned media, mapped by effective SOW, with independent monthly billing reconciliation.
    ad_month=defaultdict(int); ad_all=defaultdict(int)
    for platform in ['meta_ads','google_ads']:
        maps=group(tables[platform+'/campaign_contract_map'],'campaign_id'); peracct=defaultdict(int)
        for a in tables[platform+'/ad_accounts']: ck.test('Direct client-funded ad accounts excluded from agency cash',a['account_owner']=='client' and a['payer_client_id']==a['client_id'] and a['funding_responsibility']=='CLIENT_DIRECT' and a['agency_pays_platform']=='False',a['ad_account_id'])
        for r in tables[platform+'/daily_metrics']:
            camp=idx[platform+'/campaigns'][r['campaign_id']]; account=idx[platform+'/ad_accounts'][r['ad_account_id']]; valid=[x for x in maps[r['campaign_id']] if x['effective_start_date']<=r['metric_date']<=x['effective_end_date']]
            ck.test('Campaign-client-contract effective mapping',len(valid)==1 and valid[0]['contract_id']==r['contract_id'] and camp['client_id']==r['client_id']==account['client_id'] and camp['ad_account_id']==r['ad_account_id'] and co[r['contract_id']]['client_id']==r['client_id'],r['metric_id'])
            ck.test('Daily media payer is client direct',r['payer_client_id']==r['client_id'] and r['funding_responsibility']=='CLIENT_DIRECT',r['metric_id'])
            ck.test('Media metrics plausible bounds',c(r['spend_usd'])>=0 and int(r['impressions'])>=int(r['clicks'])>=0 and dec(r['attributed_conversions'])>=0 and c(r['attributed_conversion_value_usd'])>=0,r['metric_id'])
            if platform=='google_ads': ck.equal('Google micros USD conversion',int(r['cost_micros']),c(r['spend_usd'])*10000,r['metric_id'])
            key=(r['ad_account_id'],mon(r['metric_date'])); peracct[key]+=c(r['spend_usd']); ad_month[(r['client_id'],mon(r['metric_date']))]+=c(r['spend_usd']); ad_all[mon(r['metric_date'])]+=c(r['spend_usd'])
        for r in tables[platform+'/monthly_billing']:
            ck.equal('Daily media equals monthly client platform statement',peracct[(r['ad_account_id'],r['service_month'])],c(r['media_spend_usd']),r['platform_statement_id']); ck.equal('Client media statements have zero agency cash',c(r['agency_cash_amount_usd']),0,r['platform_statement_id']); ck.test('Monthly media payer is client direct',r['payer_client_id']==r['client_id'] and r['funding_responsibility']=='CLIENT_DIRECT',r['platform_statement_id'])
    for r in gl: ck.test('Client media excluded from agency GL',r['source_system'] not in ['meta_ads','google_ads'] and r['account_id'] not in ['MEDIA_SPEND','CLIENT_MEDIA'],r['gl_line_id'])
    for r in tables['bank/transactions']: ck.test('Client media excluded from agency bank',r['reference_type'] in ['client_receipt','vendor_payment','payroll_funding','debt_service','owner_distribution'],r['bank_transaction_id'])
    for r in tables['contracts/fee_calculations']:
        term=idx['contracts/monthly_terms'][r['term_id']]; spend=ad_month[(r['client_id'],r['service_month'])]; percentage=c(q(spend)*dec(term['spend_fee_rate'])); expected=max(c(term['monthly_minimum_fee_usd']),percentage) if dec(term['spend_fee_rate']) else c(term['monthly_minimum_fee_usd'])
        ck.equal('Fee driver equals mapped client media spend',c(r['media_spend_usd']),spend,r['calculation_id']); ck.equal('Contract percent fee arithmetic',c(r['percentage_fee_usd']),percentage,r['calculation_id']); ck.equal('Retainer fee applies contractual minimum',c(r['earned_fee_usd']),expected,r['calculation_id']); ck.equal('Retainer earned service matches fee calculation',c(svc[r['service_id']]['approved_fee_usd']),expected,r['calculation_id'])
    # Capacity, leave and approved hours; retainer work never billed again by the hour.
    dailycap={(r['employee_id'],r['work_date']):r for r in tables['timekeeping/daily_capacity']}; daywork=defaultdict(D); dayoff=defaultdict(D); employee_month_cap=defaultdict(D)
    for r in tables['timekeeping/time_off']:
        dayoff[(r['employee_id'],r['off_date'])]+=dec(r['hours']); ck.test('Paid time off approval chronology',r['approval_status']=='approved' and r['approval_date']<=r['off_date'],r['time_off_id'])
    hourly_fees=defaultdict(int); hourly_hours=defaultdict(D); monthly_hours=defaultdict(lambda:defaultdict(D)); logs_by_emp=group(tables['timekeeping/timesheets'],'employee_id')
    assignments={(r['employee_id'],r['project_id'],r['service_month']) for r in tables['timekeeping/staff_allocations']}
    for r in tables['timekeeping/timesheets']:
        key=(r['employee_id'],r['work_date']); e=emp[r['employee_id']]; p=proj[r['project_id']]; hrs=dec(r['hours']); daywork[key]+=hrs; mm=monthly_hours[mon(r['work_date'])]
        ck.test('Time entry matches staff project and contract',r['role']==e['role'] and r['client_id']==p['client_id'] and r['contract_id']==p['contract_id'] and r['billable']==p['is_billable'],r['time_entry_id'])
        ck.test('Worked hours are positive quarter-hours',hrs>0 and hrs*4==int(hrs*4),r['time_entry_id'])
        ck.test('Timesheets only in employed and project dates',e['hire_date']<=r['work_date'] and (not e['termination_date'] or r['work_date']<=e['termination_date']) and p['start_date']<=r['work_date']<=p['end_date'],r['time_entry_id'])
        if r['approval_status']=='approved': ck.test('Timesheet approval chronology',r['work_date']<=r['approved_date']<=CUT,r['time_entry_id'])
        else: ck.test('Unapproved entries have no approval date',r['approved_date']=='',r['time_entry_id'])
        mm['worked']+=hrs
        if r['billable']=='True': mm['billable_approved' if r['approval_status']=='approved' else 'billable_unapproved']+=hrs
        else: mm['nonbillable']+=hrs
        if r['billable']=='True': ck.test('Actual client time has an approved staff assignment',(r['employee_id'],r['project_id'],mon(r['work_date'])) in assignments,r['time_entry_id'])
        if r['billing_treatment']=='approved_hours_times_rate':
            card=idx['contracts/rate_cards'][r['rate_card_id']]; ck.test('Hourly time uses effective role card',card['role']==r['role'] and card['effective_start_date']<=r['work_date']<=card['effective_end_date'] and card['hourly_rate_usd']==r['billable_rate_usd'],r['time_entry_id'])
            if r['approval_status']=='approved': hourly_fees[(r['contract_id'],mon(r['work_date']))]+=c(hrs*dec(r['billable_rate_usd'])); hourly_hours[(r['contract_id'],mon(r['work_date']))]+=hrs
        elif r['billable']=='True': ck.test('Included retainer fixed time has no hourly bill rate',r['billable_rate_usd']=='' and r['rate_card_id']=='' and r['billing_treatment'] in ['included_in_retainer','included_in_fixed_fee'],r['time_entry_id'])
    for key,r in dailycap.items():
        paid,off,avail=[dec(r[f]) for f in ['paid_capacity_hours','paid_time_off_hours','available_work_hours']]
        ck.test('Employee daily capacity bounds',paid==8 and 0<=off<=paid and paid-off==avail and dt(r['work_date']).weekday()<5,r['capacity_id']); ck.test('Actual work never exceeds available daily capacity',daywork[key]<=avail,r['capacity_id']); ck.test('Actual work plus leave fills paid schedule',daywork[key]+off==paid,r['capacity_id']); ck.test('Leave register equals daily capacity leave',dayoff[key]==off,r['capacity_id']); employee_month_cap[(r['employee_id'],mon(r['work_date']))]+=paid; mm=monthly_hours[mon(r['work_date'])]; mm['paid']+=paid; mm['pto']+=off; mm['available']+=avail
        if emp[r['employee_id']]['cost_class']=='delivery': mm['delivery_available']+=avail
    planned=defaultdict(D)
    for r in tables['timekeeping/staff_allocations']:
        planned[(r['employee_id'],r['service_month'])]+=dec(r['planned_hours']); ck.test('Staff plan approved before service month',r['approved_date']<r['service_month']+'-01',r['allocation_plan_id'])
    for key,h in planned.items(): ck.test('Planned staff allocation stays within paid capacity',h<=employee_month_cap[key],str(key))
    for s in svc.values():
        expected_scope='opening_item' if s['service_end_date']<START else 'signed_future' if s['service_start_date']>CUT else 'in_period'
        ck.test('Service records classify future separately',s['record_scope']==expected_scope,s['service_id']+' '+s['record_scope'])
        if s['service_type']=='hourly': ck.equal('Hourly service has zero guaranteed minimum',c(s['agreed_minimum_fee_usd']),0,s['service_id'])
        elif s['service_type']=='retainer':
            term=next(r for r in tables['contracts/monthly_terms'] if r['contract_id']==s['contract_id'] and r['service_month']==s['service_month']); ck.equal('Service minimum equals signed retainer floor',c(s['agreed_minimum_fee_usd']),c(term['monthly_minimum_fee_usd']),s['service_id'])
        if s['service_type']=='hourly' and s['record_scope']=='in_period':
            key=(s['contract_id'],s['service_month']); ck.equal('Hourly fee equals approved hours times effective rates',c(s['approved_fee_usd']),hourly_fees[key],s['service_id']); ck.test('Hourly approved service hours match timesheets',dec(s['approved_hours'])==hourly_hours[key],s['service_id'])
    for r in tables['contracts/milestones']:
        s=svc[r['service_id']]; ck.equal('Milestone fee equals service obligation',c(r['agreed_fee_usd']),c(s['agreed_minimum_fee_usd']),r['milestone_id']); ck.test('Milestone approval matches delivery source',r['actual_approved_date']==s['actual_approved_date'] and (r['approval_status']=='approved')==bool(s['actual_approved_date']),r['milestone_id'])
    # Payroll actual employer cost and allocation are independently reconstructed.
    earn_by_run=group(tables['gusto/payroll_earnings'],'payroll_run_id'); allocation_by=group(tables['gusto/cost_allocations'],'payroll_earning_id'); payroll_month=defaultdict(int); delivery_payroll=defaultdict(int); overhead_payroll=defaultdict(int); project_salary=defaultdict(int); bench_salary=defaultdict(int)
    for r in tables['gusto/payroll_earnings']:
        comp=idx['gusto/compensation_rates'][r['compensation_id']]; gross=c(r['gross_pay_usd']); held=c(r['employee_withholding_usd']); tax=c(r['employer_tax_usd']); ben=c(r['employer_benefit_usd']); total=c(r['total_employer_cost_usd']); e=emp[r['employee_id']]
        ck.test('Payroll uses effective employee compensation',comp['employee_id']==r['employee_id'] and comp['effective_start_date']<=r['earned_start_date']<=comp['effective_end_date'],r['payroll_earning_id']); ck.equal('Semimonthly salary arithmetic',gross,c(dec(comp['annual_salary_usd'])/24),r['payroll_earning_id']); ck.equal('Payroll employee withholding arithmetic',held,c(q(gross)*dec(comp['withholding_rate'])),r['payroll_earning_id']); ck.equal('Payroll employer tax arithmetic',tax,c(q(gross)*dec(comp['employer_tax_rate'])),r['payroll_earning_id']); ck.equal('Payroll employer benefit arithmetic',ben,c(dec(comp['monthly_employer_benefit_usd'])/2),r['payroll_earning_id']); ck.equal('Payroll net plus withholding equals gross',c(r['net_pay_usd'])+held,gross,r['payroll_earning_id']); ck.equal('Payroll employer cost components',total,gross+tax+ben,r['payroll_earning_id'])
        if r['record_scope']=='in_period':
            mm=mon(r['earned_end_date']); payroll_month[mm]+=total; (delivery_payroll if e['cost_class']=='delivery' else overhead_payroll)[mm]+=total
            lines=allocation_by[r['payroll_earning_id']]; ck.equal('Payroll allocations equal actual employer cost to cent',sumc(lines,'allocated_employer_cost_usd'),total,r['payroll_earning_id'])
            caprows=[x for (eid,d),x in dailycap.items() if eid==r['employee_id'] and r['earned_start_date']<=d<=r['earned_end_date']]; paid=sum((dec(x['paid_capacity_hours']) for x in caprows),D(0)); ck.test('Payroll allocation hours cover paid period',sum((dec(x['basis_hours']) for x in lines),D(0))==paid,r['payroll_earning_id'])
            expected_basis=defaultdict(D)
            for t in logs_by_emp[r['employee_id']]:
                if r['earned_start_date']<=t['work_date']<=r['earned_end_date']:
                    category='project_delivery' if t['project_id']!='PRJ-INTERNAL' else 'corporate_overhead' if e['cost_class']=='overhead' else 'delivery_bench_and_internal'
                    expected_basis[(t['project_id'],category)]+=dec(t['hours'])
            expected_basis[('PRJ-INTERNAL','paid_leave')]+=sum((dec(x['paid_time_off_hours']) for x in caprows),D(0))
            for l in lines:
                ck.test('Allocation denominator is actual paid capacity',dec(l['period_paid_hours'])==paid,l['cost_allocation_id']); expected=D(total)*dec(l['basis_hours'])/paid; ck.test('Payroll allocation is proportional within one cent',abs(D(c(l['allocated_employer_cost_usd']))-expected)<=1,l['cost_allocation_id']); ck.test('Allocations do not post second GL expense',l['is_additional_gl_expense']=='False',l['cost_allocation_id'])
                ck.test('Allocation project basis equals actual time and paid leave',dec(l['basis_hours'])==expected_basis[(l['project_id'],l['allocation_category'])],l['cost_allocation_id'])
                p=proj[l['project_id']]; ck.test('Payroll allocation employee and client dimensions match source',l['employee_id']==r['employee_id'] and l['payroll_run_id']==r['payroll_run_id'] and l['service_month']==mm and l['contract_id']==p['contract_id'] and l['client_id']==p['client_id'],l['cost_allocation_id'])
                if l['project_id']!='PRJ-INTERNAL': project_salary[mm]+=c(l['allocated_employer_cost_usd'])
                elif e['cost_class']=='delivery': bench_salary[mm]+=c(l['allocated_employer_cost_usd'])
            acc=jaccounts[r['journal_id']]; pref='50' if e['cost_class']=='delivery' else '60'; ck.equal('Payroll GL salaries from earned payroll only',acc[pref+'00'],gross,r['payroll_earning_id']); ck.equal('Payroll GL employer tax from earned payroll',acc[pref+'01'],tax,r['payroll_earning_id']); ck.equal('Payroll GL benefits from earned payroll',acc[pref+'02'],ben,r['payroll_earning_id'])
            ck.equal('Payroll GL net liability',-acc['2100'],c(r['net_pay_usd']),r['payroll_earning_id']); ck.equal('Payroll GL withholding-tax liability',-acc['2110'],held+tax,r['payroll_earning_id']); ck.equal('Payroll GL benefit liability',-acc['2120'],ben,r['payroll_earning_id'])
    for run in tables['gusto/payroll_runs']:
        for field in ['gross_pay_usd','employee_withholding_usd','employer_tax_usd','employer_benefit_usd','net_pay_usd','total_employer_cost_usd']: ck.equal('Payroll run totals equal employee detail',c(run[field]),sumc(earn_by_run[run['payroll_run_id']],field),run['payroll_run_id']+' '+field)
        ck.test('Unfunded earned payroll has future schedule only',bool(run['actual_funding_date'])==(run['scheduled_funding_date']<=CUT) and bool(run['funding_id'])==bool(run['actual_funding_date']),run['payroll_run_id'])
    for f in tables['gusto/payroll_funding']:
        run=idx['gusto/payroll_runs'][f['payroll_run_id']]; ck.equal('Payroll funding includes gross tax and benefits once',c(f['bank_debit_usd']),c(f['net_pay_usd'])+c(f['employee_withholding_usd'])+c(f['employer_tax_usd'])+c(f['employer_benefit_usd']),f['funding_id']); ck.equal('Payroll funding equals earned run liability',c(f['bank_debit_usd']),c(run['total_employer_cost_usd']),f['funding_id']); ck.test('Payroll actual funding matches run',f['funding_date']==run['actual_funding_date'],f['funding_id'])
        acc=jaccounts[f['journal_id']]; ck.equal('Funding clears net payroll liability',acc['2100'],c(f['net_pay_usd']),f['funding_id']); ck.equal('Funding clears tax payroll liability',acc['2110'],c(f['employee_withholding_usd'])+c(f['employer_tax_usd']),f['funding_id']); ck.equal('Funding clears benefit liability',acc['2120'],c(f['employer_benefit_usd']),f['funding_id'])
    # Freelancer cost: accept -> expense/accrual -> invoice/AP -> payment, with no duplicate expense.
    freelancer_month=defaultdict(int); earned_work=idx['freelancers/approved_work']; invoiced_work=Counter(); fr_invoice=idx['freelancers/invoices']
    for w in earned_work.values():
        rate=idx['freelancers/rate_history'][w['contractor_rate_id']]; wo=idx['freelancers/work_orders'][w['work_order_id']]; amt=c(w['earned_cost_usd']); freelancer_month[w['service_month']]+=amt
        ck.equal('Freelance approved hours times rate',amt,c(dec(w['approved_hours'])*dec(w['hourly_cost_rate_usd'])),w['approved_work_id']); ck.test('Freelance effective cost-rate match',rate['contractor_id']==w['contractor_id'] and rate['effective_start_date']<=w['service_start_date']<=rate['effective_end_date'] and rate['hourly_cost_rate_usd']==w['hourly_cost_rate_usd'],w['approved_work_id']); ck.test('Freelance work within authorized order',wo['approved_date']<=w['service_start_date'] and dec(w['approved_hours'])<=dec(wo['budget_hours']) and wo['project_id']==w['project_id'] and wo['contract_id']==w['contract_id'],w['approved_work_id']); acc=jaccounts[w['journal_id']]; ck.equal('Freelance earned cost posts expense once',acc['5010'],amt,w['approved_work_id']); ck.equal('Freelance earned cost credits accrual',-acc['2200'],amt,w['approved_work_id'])
    fr_lines=group(tables['freelancers/invoice_lines'],'contractor_invoice_id')
    for l in tables['freelancers/invoice_lines']:
        w=earned_work[l['approved_work_id']]; qb=idx['quickbooks/vendor_bill_lines'][l['accounting_bill_line_id']]; invoiced_work[w['approved_work_id']]+=1; ck.equal('Freelancer invoice line equals accepted cost',c(l['line_amount_usd']),c(w['earned_cost_usd']),l['contractor_invoice_line_id']); ck.test('Freelancer QB bill clears accrual without second expense',qb['account_id']=='2200' and qb['approved_work_id']==w['approved_work_id'] and qb['source_line_id']==l['contractor_invoice_line_id'] and qb['line_amount_usd']==l['line_amount_usd'],l['contractor_invoice_line_id']); ck.test('Freelance invoice follows acceptance',fr_invoice[l['contractor_invoice_id']]['invoice_date']>=w['approved_date'],l['contractor_invoice_line_id'])
    for k,n in invoiced_work.items(): ck.equal('Accepted freelance work invoiced at most once',n,1,k)
    for f in fr_invoice.values():
        b=bills[f['accounting_bill_id']]; ck.equal('Freelance invoice totals',c(f['invoice_total_usd']),sumc(fr_lines[f['contractor_invoice_id']],'line_amount_usd'),f['contractor_invoice_id']); ck.test('Freelance source invoice matches AP header',b['contractor_invoice_id']==f['contractor_invoice_id'] and b['bill_total_usd']==f['invoice_total_usd'] and b['bill_date']==f['invoice_date'] and b['due_date']==f['due_date'],f['contractor_invoice_id'])
    # Source billing/credit/collection and accepted revenue reconcile independently.
    ilines=group(tables['quickbooks/client_invoice_lines'],'invoice_id'); blines=group(tables['quickbooks/vendor_bill_lines'],'bill_id'); apps=group(tables['quickbooks/receipt_applications'],'invoice_id'); vapps=group(tables['quickbooks/vendor_payment_applications'],'bill_id'); credits=group(tables['quickbooks/credit_notes'],'invoice_id'); revenue=group(tables['delivery/recognition_events'],'service_id')
    invoice_month=defaultdict(int); credit_month=defaultdict(int); receipt_month=defaultdict(int); bill_month=defaultdict(int); vp_month=defaultdict(int); earned_month=defaultdict(int); streams=defaultdict(lambda:defaultdict(int))
    for r in inv.values():
        ck.equal('Invoice header equals source lines',c(r['invoice_total_usd']),sumc(ilines[r['invoice_id']],'line_amount_usd'),r['invoice_id'])
        if r['record_scope']=='in_period':
            invoice_month[mon(r['invoice_date'])]+=c(r['invoice_total_usd']); ck.equal('Invoice GL AR debit',jaccounts[r['journal_id']]['1100'],c(r['invoice_total_usd']),r['invoice_id'])
            for l in ilines[r['invoice_id']]: ck.equal('Invoice line splits deferred and unbilled',c(l['invoiced_to_deferred_usd'])+c(l['invoiced_from_unbilled_usd']),c(l['line_amount_usd']),l['invoice_line_id'])
        amount=c(r['invoice_total_usd'])-sumc(apps[r['invoice_id']],'applied_amount_usd')-sumc(credits[r['invoice_id']],'amount_usd'); ck.equal('Invoice residual AR balance',c(r['open_balance_usd']),amount,r['invoice_id']); ck.test('Client invoices never overapplied',amount>=0,r['invoice_id'])
        movements=[(r['invoice_date'],0,c(r['invoice_total_usd']))]+[(x['applied_date'],2,-c(x['applied_amount_usd'])) for x in apps[r['invoice_id']]]+[(x['credit_date'],1,-c(x['amount_usd'])) for x in credits[r['invoice_id']]]; run=0
        for d,_,a in sorted(movements): run+=a; ck.test('Invoice AR nonnegative through dated credit and partial receipts',run>=0,r['invoice_id']+' '+d)
    for cr in tables['quickbooks/credit_notes']:
        s=svc[cr['service_id']]; ck.test('Fee credits follow earned service',s['actual_approved_date'] and s['actual_approved_date']<=cr['credit_date'],cr['credit_note_id']); ck.equal('Credit note GL fee concession',jaccounts[cr['journal_id']]['4090'],c(cr['amount_usd']),cr['credit_note_id']); ck.equal('Credit note GL reduces AR',-jaccounts[cr['journal_id']]['1100'],c(cr['amount_usd']),cr['credit_note_id']); credit_month[mon(cr['credit_date'])]+=c(cr['amount_usd'])
    ra=group(tables['quickbooks/receipt_applications'],'receipt_id')
    for r in tables['quickbooks/client_receipts']:
        ck.equal('Receipt applications equal actual received cash',sumc(ra[r['receipt_id']],'applied_amount_usd'),c(r['receipt_amount_usd']),r['receipt_id']); receipt_month[mon(r['receipt_date'])]+=c(r['receipt_amount_usd'])
        for a in ra[r['receipt_id']]: ck.test('Receipt applications use correct client and date',inv[a['invoice_id']]['client_id']==r['client_id'] and a['applied_date']==r['receipt_date'],a['receipt_application_id'])
    for b in bills.values():
        ck.equal('AP bill header equals lines',c(b['bill_total_usd']),sumc(blines[b['bill_id']],'line_amount_usd'),b['bill_id']); amount=c(b['bill_total_usd'])-sumc(vapps[b['bill_id']],'applied_amount_usd'); ck.equal('AP bill residual balance',c(b['open_balance_usd']),amount,b['bill_id']); ck.test('AP bills not overpaid',amount>=0,b['bill_id'])
        if b['record_scope']=='in_period': bill_month[mon(b['bill_date'])]+=c(b['bill_total_usd']); ck.equal('AP bill GL liability',-jaccounts[b['journal_id']]['2000'],c(b['bill_total_usd']),b['bill_id'])
    va=group(tables['quickbooks/vendor_payment_applications'],'vendor_payment_id')
    for r in tables['quickbooks/vendor_payments']:
        ck.equal('Vendor payment applications equal cash',sumc(va[r['vendor_payment_id']],'applied_amount_usd'),c(r['payment_amount_usd']),r['vendor_payment_id']); vp_month[mon(r['payment_date'])]+=c(r['payment_amount_usd'])
        for a in va[r['vendor_payment_id']]: ck.test('Vendor payment client and date references',bills[a['bill_id']]['vendor_id']==r['vendor_id'] and a['applied_date']==r['payment_date'] and r['payment_date']>=bills[a['bill_id']]['bill_date'],a['vendor_application_id'])
    for r in tables['delivery/recognition_events']:
        amt=c(r['recognized_fee_usd']); s=svc[r['service_id']]; acc=jaccounts[r['journal_id']]; ck.equal('Recognition GL equals signed source earned fee',-acc[r['revenue_account_id']],amt,r['recognition_id']); mm=mon(r['recognition_date']); earned_month[mm]+=amt; streams[mm][r['revenue_account_id']]+=amt
        if r['recognition_type']!='fee_concession':
            ck.test('Revenue recognized only on actual approval',s['actual_approved_date']==r['recognition_date'] and s['record_scope']=='in_period',r['recognition_id']); ck.equal('Revenue recognized fee equals approved service',amt,c(s['approved_fee_usd']),r['recognition_id']); ck.equal('Earned fee split from deferred or unbilled',c(r['earned_from_deferred_usd'])+c(r['earned_to_unbilled_usd']),amt,r['recognition_id'])
    for s in svc.values():
        rr=[r for r in revenue[s['service_id']] if r['recognition_type']!='fee_concession']; expected=1 if s['record_scope']=='in_period' and s['actual_approved_date'] else 0; ck.equal('Every approved service earns exactly once and no future service earns',len(rr),expected,s['service_id'])
    # Independent chronological service positions detect invalid deferred/unbilled splits.
    positions=defaultdict(lambda:[0,0]); service_events=[]
    for r in tables['delivery/opening_service_balances']: positions[r['service_id']][0]+=c(r['deferred_revenue_usd']); positions[r['service_id']][1]+=c(r['unbilled_revenue_usd'])
    for l in tables['quickbooks/client_invoice_lines']:
        h=inv[l['invoice_id']]
        if h['record_scope']=='in_period': service_events.append((h['invoice_date'],0,l['invoice_line_id'],'invoice',l))
    for r in tables['delivery/recognition_events']:
        if r['recognition_type']!='fee_concession': service_events.append((r['recognition_date'],1,r['recognition_id'],'earned',r))
    for d,_,eid,typ,r in sorted(service_events,key=lambda x:x[:3]):
        p=positions[r['service_id']]
        if typ=='invoice':
            amt=c(r['line_amount_usd']); unb=min(amt,p[1]); deff=amt-unb; ck.equal('Chronological invoice clears existing unbilled first',c(r['invoiced_from_unbilled_usd']),unb,eid); ck.equal('Chronological advance invoice increases deferred only',c(r['invoiced_to_deferred_usd']),deff,eid); p[1]-=unb; p[0]+=deff
        else:
            amt=c(r['recognized_fee_usd']); deff=min(amt,p[0]); unb=amt-deff; ck.equal('Chronological earned fee consumes deferred first',c(r['earned_from_deferred_usd']),deff,eid); ck.equal('Chronological uninvoiced earnings increase unbilled',c(r['earned_to_unbilled_usd']),unb,eid); p[0]-=deff; p[1]+=unb
        ck.test('Service deferred and unbilled balances nonnegative',min(p)>=0,eid)
    copen=defaultdict(lambda:[0,0]); cflows=defaultdict(lambda:[0,0,0,0])
    for r in tables['delivery/opening_service_balances']: copen[r['contract_id']][0]+=c(r['deferred_revenue_usd']); copen[r['contract_id']][1]+=c(r['unbilled_revenue_usd'])
    for r in tables['quickbooks/client_invoice_lines']:
        h=inv[r['invoice_id']]
        if h['record_scope']=='in_period': a=cflows[(r['contract_id'],mon(h['invoice_date']))]; a[0]+=c(r['invoiced_to_deferred_usd']); a[3]+=c(r['invoiced_from_unbilled_usd'])
    for r in tables['delivery/recognition_events']: a=cflows[(r['contract_id'],mon(r['recognition_date']))]; a[1]+=c(r['earned_from_deferred_usd']); a[2]+=c(r['earned_to_unbilled_usd'])
    cbal=group(tables['delivery/monthly_contract_balances'],'service_month'); def_month={}; unb_month={}
    for m in months:
        for r in cbal[m]:
            con=r['contract_id']; d,u=copen[con]; i,e,eu,iu=cflows[(con,m)]; vals={'opening_deferred_usd':d,'invoiced_to_deferred_usd':i,'earned_from_deferred_usd':e,'closing_deferred_usd':d+i-e,'opening_unbilled_usd':u,'earned_to_unbilled_usd':eu,'invoiced_from_unbilled_usd':iu,'closing_unbilled_usd':u+eu-iu}
            for f,v in vals.items(): ck.equal('Contract balance roll-forwards from saved events',c(r[f]),v,r['contract_balance_id']+' '+f)
            copen[con]=[d+i-e,u+eu-iu]
        def_month[m]=sumc(cbal[m],'closing_deferred_usd'); unb_month[m]=sumc(cbal[m],'closing_unbilled_usd'); ck.equal('Contract deferred totals equal GL liability',def_month[m],-close[(m,'2300')],m); ck.equal('Contract unbilled totals equal GL asset',unb_month[m],close[(m,'1150')],m)
    # AR/AP/payroll/contractor roll-forwards for every month.
    ar=opening['1100']; ap=-opening['2000']; taxpay=-sum(opening[a] for a in ['2100','2110','2120']); accr=-opening['2200']; prevdef=-opening['2300']; prevunb=opening['1150']; prepaid=opening['1200']; debt=-opening['2500']; priorloan=debt
    fundby=group(tables['gusto/payroll_funding'],'funding_date'); insby=group(tables['finance/prepaid_amortization'],'service_month')
    for m in months:
        ar+=invoice_month[m]-credit_month[m]-receipt_month[m]; ap+=bill_month[m]-vp_month[m]; ck.equal('Monthly AR roll-forward to GL',ar,close[(m,'1100')],m); ck.equal('Monthly AP roll-forward to GL',ap,-close[(m,'2000')],m)
        fund=sum(c(r['bank_debit_usd']) for r in tables['gusto/payroll_funding'] if mon(r['funding_date'])==m); taxpay+=payroll_month[m]-fund; ck.equal('Monthly payroll liability roll-forward',taxpay,-sum(close[(m,a)] for a in ['2100','2110','2120']),m)
        billed=sum(c(l['line_amount_usd']) for l in tables['quickbooks/vendor_bill_lines'] if l['account_id']=='2200' and bills[l['bill_id']]['record_scope']=='in_period' and mon(bills[l['bill_id']]['bill_date'])==m); accr+=freelancer_month[m]-billed; ck.equal('Monthly contractor earned-to-billed accrual',accr,-close[(m,'2200')],m)
        ck.equal('Monthly payroll expense equals earned cost once',sum(activity[(m,a)][0]-activity[(m,a)][1] for a in ['5000','5001','5002','6000','6001','6002']),payroll_month[m],m); ck.equal('Monthly freelancer expense equals accepted cost once',activity[(m,'5010')][0]-activity[(m,'5010')][1],freelancer_month[m],m)
        ck.equal('Monthly revenue billing asset-liability bridge',earned_month[m],invoice_month[m]-credit_month[m]-(def_month[m]-prevdef)+(unb_month[m]-prevunb),m); prevdef,prevunb=def_month[m],unb_month[m]
        additions=sum(c(l['line_amount_usd']) for l in tables['quickbooks/vendor_bill_lines'] if l['account_id']=='1200' and bills[l['bill_id']]['record_scope']=='in_period' and mon(bills[l['bill_id']]['bill_date'])==m); prepaid+=additions-sumc(insby[m],'amount_usd'); ck.equal('Prepaid insurance monthly roll-forward',prepaid,close[(m,'1200')],m)
        for r in tables['finance/debt_service']:
            if mon(r['payment_date'])==m:
                ck.equal('Debt contractual monthly interest',c(r['interest_usd']),c(q(debt)*D('.09')/12),r['debt_service_id']); debt-=c(r['principal_usd']); ck.equal('Debt principal roll-forward',debt,c(r['closing_principal_usd']),r['debt_service_id']); ck.equal('Debt service total cash components',c(r['total_payment_usd']),c(r['principal_usd'])+c(r['interest_usd']),r['debt_service_id'])
        ck.equal('Debt register reconciles monthly GL',debt,-close[(m,'2500')],m)
    ck.equal('Cutoff AR open items equal GL',sumc(tables['quickbooks/ar_open_items'],'open_amount_usd'),ar); ck.equal('Cutoff AP open items equal GL',sumc(tables['quickbooks/ap_open_items'],'open_amount_usd'),ap)
    for r in tables['quickbooks/ar_open_items']:
        ck.equal('AR aging input matches invoice residual',c(r['open_amount_usd']),c(inv[r['invoice_id']]['open_balance_usd']),r['ar_item_id']); days=max(0,(dt(CUT)-dt(r['due_date'])).days); ck.equal('AR days past due arithmetic',int(r['days_past_due']),days,r['ar_item_id']); bucket='current' if not days else '1_30' if days<=30 else '31_60' if days<=60 else '61_90' if days<=90 else '91_plus'; ck.test('AR aging buckets',r['aging_bucket']==bucket,r['ar_item_id'])
    ck.equal('Cutoff accepted-unbilled freelance commitments equal accrual',sumc(tables['planning/contractor_accruals'],'earned_cost_usd'),accr)
    ck.equal('Cutoff earned-unfunded payroll commitments equal liability',sumc(tables['planning/payroll_commitments'],'total_funding_usd'),taxpay)
    for a in tables['planning/contractor_accruals']: ck.test('Contractor accruals are accepted and not already invoiced',earned_work[a['approved_work_id']]['contractor_invoice_id']=='' and a['expected_invoice_date']>CUT,a['contractor_accrual_id'])
    # Full agency bank reconciles to GL and to the payment/receipt sources one-to-one.
    bankrows=tables['bank/transactions']; run=opening['1000']; tx_by_j=group(bankrows,'journal_id'); bankmonths=group(bankrows,'transaction_date'); prevdate=''; seq=0
    expected_cash={}
    for tab,pk,dc,amount,sign in [('quickbooks/client_receipts','receipt_id','receipt_date','receipt_amount_usd',1),('quickbooks/vendor_payments','vendor_payment_id','payment_date','payment_amount_usd',-1),('gusto/payroll_funding','funding_id','funding_date','bank_debit_usd',-1),('finance/debt_service','debt_service_id','payment_date','total_payment_usd',-1),('finance/owner_distributions','distribution_id','distribution_date','amount_usd',-1)]:
        for r in tables[tab]: expected_cash[r['bank_transaction_id']]=(r[pk],r[dc],sign*c(r[amount]),r['journal_id'])
    ck.test('Bank references cover actual cash sources exactly',set(expected_cash)==set(idx['bank/transactions']))
    for r in bankrows:
        amount=c(r['money_in_usd'])-c(r['money_out_usd']); run+=amount; seq+=1; ck.equal('Bank signed amount arithmetic',amount,c(r['signed_amount_usd']),r['bank_transaction_id']); ck.equal('Bank running balances to cent',run,c(r['running_balance_usd']),r['bank_transaction_id']); ck.test('Bank sequence chronological',int(r['sequence'])==seq and r['transaction_date']>=prevdate,r['bank_transaction_id']); prevdate=r['transaction_date']; ck.test('Agency bank never negative',run>=0,r['bank_transaction_id']); ck.equal('Bank cash equals mapped journal cash',jaccounts[r['journal_id']]['1000'],amount,r['bank_transaction_id']); ck.test('Bank row matches original actual cash source',expected_cash.get(r['bank_transaction_id'])==(r['reference_id'],r['transaction_date'],amount,r['journal_id']),r['bank_transaction_id'])
    for jid,acc in jaccounts.items():
        if acc.get('1000'): ck.equal('Every cash GL journal appears once in bank',len(tx_by_j[jid]),1,jid)
    previous=opening['1000']; bank_month_end={}
    for r in tables['bank/monthly_statements']:
        mm=r['service_month']; tx=[t for t in bankrows if mon(t['transaction_date'])==mm]; inc=sumc(tx,'money_in_usd'); out=sumc(tx,'money_out_usd'); ck.equal('Monthly bank opening continuity',c(r['opening_balance_usd']),previous,mm); ck.equal('Monthly bank deposits equal transactions',c(r['total_money_in_usd']),inc,mm); ck.equal('Monthly bank withdrawals equal transactions',c(r['total_money_out_usd']),out,mm); previous+=inc-out; ck.equal('Monthly bank closing equals transactions',c(r['closing_balance_usd']),previous,mm); ck.equal('Monthly bank cash equals GL cash',previous,close[(mm,'1000')],mm); ck.equal('Monthly bank transaction counts',int(r['transaction_count']),len(tx),mm); bank_month_end[mm]=previous
    # Immutable planning cutoff and explicit overlap keys.
    for v in tables['planning/budget_versions']: ck.test('Original budgets approved before covered period',v['is_original_approved']=='True' and v['status']=='immutable' and v['approved_date']<v['period_start_date'],v['budget_version_id'])
    for r in tables['planning/monthly_budget']:
        v=idx['planning/budget_versions'][r['budget_version_id']]; ck.test('Budget rows inside original approved window',v['period_start_date'][:7]<=r['service_month']<=v['period_end_date'][:7] and v['approved_date']<r['service_month']+'-01',r['budget_line_id']); ck.test('Budget amounts nonnegative and separate from actuals',c(r['budget_amount_usd'])>=0,r['budget_line_id'])
    schedules=idx['contracts/billing_schedule']; future=set()
    for s in schedules.values():
        ck.test('Billing schedule known by snapshot',s['known_date']<=CUT,s['schedule_line_id']); ck.test('Scheduled invoice date follows contract signing',s['scheduled_invoice_date']>=co[s['contract_id']]['signed_date'],s['schedule_line_id'])
        if s['scheduled_invoice_date']>CUT:
            future.add(s['schedule_line_id']); ck.test('Future billing has no actual invoice',s['actual_invoice_line_id']=='' and s['status_asof']=='scheduled',s['schedule_line_id'])
        elif s['status_asof']!='opening_prepaid': ck.test('Historical scheduled invoice has exact actual line',bool(s['actual_invoice_line_id']) and idx['quickbooks/client_invoice_lines'][s['actual_invoice_line_id']]['schedule_line_id']==s['schedule_line_id'],s['schedule_line_id'])
    commits=tables['planning/signed_future_commitments']; ck.test('Future commitment snapshot covers future billing schedule exactly',{r['schedule_line_id'] for r in commits}==future)
    for r in commits:
        s=schedules[r['schedule_line_id']]; ck.test('Future commitment is deduplicable schedule copy',r['overlap_key']==r['schedule_line_id'] and all(r[f]==s[f] for f in ['contract_id','client_id','service_id','scheduled_invoice_date','scheduled_due_date','scheduled_amount_usd','amount_basis']),r['commitment_id'])
    for r in tables['planning/collection_expectations']: ck.test('Open AR collection assumption is future and tied to residual',r['expected_receipt_date']>CUT and c(r['open_amount_usd'])==c(inv[r['invoice_id']]['open_balance_usd']),r['collection_expectation_id'])
    for r in tables['planning/headcount_capacity_plan']: ck.test('Capacity plans approved before their months',r['approved_date']<r['service_month']+'-01' and dec(r['planned_available_hours'])<=dec(r['planned_paid_hours']) and 0<=dec(r['target_billable_utilization'])<=1,r['capacity_plan_id'])
    for r in tables['planning/recurring_obligations']:
        ck.test('Recurring future cycles not actual invoices',r['next_service_start_date']>CUT and r['next_expected_bill_date']>CUT,r['obligation_id'])
        if r['current_open_bill_id']: ck.test('Recurring overlap link is existing open AP',c(bills[r['current_open_bill_id']]['open_balance_usd'])>0 and bills[r['current_open_bill_id']]['vendor_id']==r['vendor_id'],r['obligation_id'])
    for r in tables['finance/debt_schedule']: ck.test('Future debt schedule has no actual payment',r['scheduled_payment_date']>CUT and r['status']=='contractual_future_not_actual',r['debt_schedule_id'])
    # Specific business stories are observable, not just prose claims.
    fees1=[r for r in tables['contracts/fee_calculations'] if r['client_id']=='CLI-001']; ck.test('Story flat retainer while media spend grows',len({r['earned_fee_usd'] for r in fees1})==1 and c(fees1[-1]['media_spend_usd'])>c(fees1[0]['media_spend_usd'])*1.8)
    actual3=sum((dec(r['hours']) for r in tables['timekeeping/timesheets'] if r['client_id']=='CLI-003' and r['billing_treatment']=='included_in_retainer' and '2026-04'<=mon(r['work_date'])<='2026-09'),D(0)); budget3=sum((dec(r['scope_hours_budget']) for r in tables['contracts/monthly_terms'] if r['client_id']=='CLI-003' and '2026-04'<=r['service_month']<='2026-09'),D(0)); ck.test('Story scope creep exceeds included hours',actual3>budget3*D('1.35'),f'actual={actual3} included={budget3}')
    ck.test('Story churn stops retainer fees and media',not any(r['client_id']=='CLI-005' and r['service_month']>'2026-07' for r in tables['contracts/fee_calculations']) and any(r['contract_id'].startswith('CON-R-005') and r['change_type']=='termination_release' for r in tables['contracts/change_orders']))
    ck.test('Story delayed collections leave overdue AR',any(r['client_id']=='CLI-004' and int(r['days_past_due'])>=30 for r in tables['quickbooks/ar_open_items']))
    vr=[r for r in tables['freelancers/rate_history'] if r['contractor_id']=='FREE-004']; ck.test('Story contractor video rates increase in August',len(vr)==2 and vr[-1]['effective_start_date']=='2026-08-01' and c(vr[-1]['hourly_cost_rate_usd'])>c(vr[0]['hourly_cost_rate_usd']))
    util=lambda m:monthly_hours[m]['billable_approved']/monthly_hours[m]['available']; ck.test('Story utilization falls after churn',util('2026-08')<util('2026-06')-D('.08'))
    hc=[sum(1 for e in emp.values() if e['hire_date']<=m+'-01' and (not e['termination_date'] or e['termination_date']>=m+'-01')) for m in months]; ck.test('Team remains realistic and ends at 22',hc[0]==18 and hc[-1]==22 and all(15<=n<=25 for n in hc))
    # 24 independent reference totals for the downstream Claude implementation.
    controls=[]; bud=group(tables['planning/monthly_budget'],'service_month'); acct=idx['quickbooks/chart_of_accounts']
    for i,m in enumerate(months):
        exp=lambda accounts:sum(activity[(m,a)][0]-activity[(m,a)][1] for a in accounts)
        cos=exp([a for a,r in acct.items() if r['account_type']=='cost_of_services']); opex=exp([a for a,r in acct.items() if r['account_type']=='operating_expense']); dep=exp(['6300']); interest=exp(['6400']); net=earned_month[m]-cos-opex-interest
        ck.equal('Ledger monthly net fees equals recognition register',-sum(activity[(m,a)][0]-activity[(m,a)][1] for a in ['4000','4010','4020','4030','4090']),earned_month[m],m)
        hh=monthly_hours[m]; paid=hh['paid']; pto=hh['pto']; available=hh['available']; denom=sum(earned_month[x] for x in months[max(0,i-2):i+1]); dso=(D(close[(m,'1100')])/denom*D(30*min(3,i+1))).quantize(D('.01')) if denom else ''
        budgetrev=sum(c(r['budget_amount_usd']) for r in bud[m] if r['revenue_stream']); budgetexpense=sum(c(r['budget_amount_usd']) for r in bud[m] if not r['revenue_stream']); pipe=sum(c(r['weighted_pipeline_usd']) for r in tables['hubspot/deal_monthly_snapshots'] if mon(r['snapshot_date'])==m)
        r=dict(service_month=m,agency_net_fee_revenue_usd=q(earned_month[m]),flat_retainer_revenue_usd=q(streams[m]['4000']),spend_based_fee_revenue_usd=q(streams[m]['4010']),fixed_project_revenue_usd=q(streams[m]['4020']),hourly_revenue_usd=q(streams[m]['4030']),fee_concessions_signed_usd=q(streams[m]['4090']),gross_fee_invoices_usd=q(invoice_month[m]),credit_notes_usd=q(credit_month[m]),client_collected_cash_usd=q(receipt_month[m]),client_media_spend_usd=q(ad_all[m]),employee_employer_cost_usd=q(payroll_month[m]),delivery_payroll_cost_usd=q(delivery_payroll[m]),project_allocated_payroll_usd=q(project_salary[m]),delivery_bench_and_paid_leave_cost_usd=q(bench_salary[m]),overhead_payroll_usd=q(overhead_payroll[m]),freelancer_earned_cost_usd=q(freelancer_month[m]),cost_of_services_usd=q(cos),gross_profit_usd=q(earned_month[m]-cos),operating_expenses_including_depreciation_usd=q(opex),ebitda_usd=q(earned_month[m]-cos-opex+dep),depreciation_usd=q(dep),interest_usd=q(interest),net_profit_usd=q(net),bank_cash_usd=q(close[(m,'1000')]),ar_usd=q(close[(m,'1100')]),ap_usd=q(-close[(m,'2000')]),unbilled_earned_fees_usd=q(close[(m,'1150')]),deferred_fees_usd=q(-close[(m,'2300')]),payroll_liability_usd=q(-sum(close[(m,a)] for a in ['2100','2110','2120'])),contractor_accrual_usd=q(-close[(m,'2200')]),prepaid_insurance_usd=q(close[(m,'1200')]),loan_principal_usd=q(-close[(m,'2500')]),owner_distributions_usd=q(exp(['3100'])),active_headcount=hc[i],paid_capacity_hours=paid,paid_leave_hours=pto,available_work_hours=available,approved_billable_hours=hh['billable_approved'],unapproved_billable_hours=hh['billable_unapproved'],nonbillable_work_hours=hh['nonbillable'],billable_utilization=(hh['billable_approved']/available).quantize(D('.000001')) if available else '',budget_fee_revenue_usd=q(budgetrev),budget_total_expenses_usd=q(budgetexpense),open_weighted_pipeline_usd=q(pipe),dso_3month_30day_convention=dso)
        r['delivery_available_work_hours']=hh['delivery_available']; r['delivery_billable_utilization']=(hh['billable_approved']/hh['delivery_available']).quantize(D('.000001')); r['firmwide_billable_utilization']=r.pop('billable_utilization')
        controls.append(r)
    rows=ck.rows(); failures=sum(r['failures'] for r in rows)
    summary=dict(status='PASS' if not failures else 'FAIL',check_groups=len(rows),evaluated_conditions=sum(r['evaluated'] for r in rows),failures=failures,source_csv_files=len(physical),logical_tables=len(tables),source_rows=sum(len(t) for t in tables.values()),period_start=START,snapshot_date=CUT,money_reconciliation_tolerance_cents=0,method='Independent saved-file read; integer cents; no generator imports',last_month=controls[-1])
    if write_reports:
        val=root/'validation'; write_csv(val/'validation_report.csv',rows); write_csv(val/'monthly_control_totals.csv',controls); (val/'validation_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary,rows,controls

if __name__=='__main__':
    candidate=Path(__file__).resolve().parent.parent
    root=Path(sys.argv[1]) if len(sys.argv)>1 else candidate if (candidate/'metadata/table_schemas.json').exists() else candidate/'outputs/signal_harbor_data'
    summary,checks,_=validate(root)
    print(json.dumps({k:v for k,v in summary.items() if k!='last_month'},indent=2))
    for r in checks:
        if r['failures']: print(r['check_name'],r['failures'],r['examples'])
    raise SystemExit(0 if summary['status']=='PASS' else 1)
