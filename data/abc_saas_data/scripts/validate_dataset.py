"""Independent saved-file validator. Does NOT import or execute the economic generator.

Usage: python validate_dataset.py --root PATH
Python >=3.10, standard library only. All money is Decimal -> exact integer cents.
"""
import argparse, csv, json, hashlib, sys, calendar, re
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict, Counter
from functools import lru_cache

START=date(2024,11,1); CUTOFF=date(2026,10,31); END=date(2026,11,1)
REPORT=defaultdict(lambda:dict(evaluated=0,failures=0,max_absolute_difference_cents=0,examples=[]))
ROOT=None;SCHEMA={}
def ck(name,ok,label='',difference=0):
    r=REPORT[name];r['evaluated']+=1
    if not ok:
        r['failures']+=1
        if len(r['examples'])<4:r['examples'].append(str(label)[:200])
    r['max_absolute_difference_cents']=max(r['max_absolute_difference_cents'],abs(int(difference)))
def eq(name,actual,expected,label=''):
    ck(name,actual==expected,label,actual-expected)
def m(value):
    x=Decimal(value)*100
    if x!=x.to_integral_value():raise ValueError('Fractional source cent: '+value)
    return int(x)
def rnd(n,d):
    return int((Decimal(n)/Decimal(d)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
def ds(s):return date.fromisoformat(s)
def fmt(c):return f'{Decimal(c)/100:.2f}'
def monthnext(d):return date(d.year+(d.month==12),1 if d.month==12 else d.month+1,1)
def monthend(d):return monthnext(d)-timedelta(days=1)
def files(table):return [ROOT/p for p in SCHEMA[table]['physical_files']]
def rows(table):
    for path in files(table):
        with path.open(encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)
@lru_cache(None)
def data(table):return list(rows(table))
def keyed(table,key):return {r[key]:r for r in data(table)}
def sum_by(table,key,field,condition=lambda x:True):
    out=defaultdict(int)
    for r in rows(table):
        if condition(r):out[r[key]]+=m(r[field])
    return out
def write_csv(path,content,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(content[0]));w.writeheader();w.writerows(content)

def structural():
    manifest_path=ROOT/'metadata/file_manifest.csv'
    ck('Manifest is present',manifest_path.exists())
    manifests={}
    if manifest_path.exists():
        with manifest_path.open(encoding='utf-8-sig',newline='') as f:manifests={r['relative_path']:r for r in csv.DictReader(f)}
    rowcounts={}
    for table,s in SCHEMA.items():
        seen=set();count=0
        for path in files(table):
            exists=path.is_file();ck('Every declared physical source file exists',exists,str(path))
            if not exists:continue
            raw=path.read_bytes()
            ck('CSV UTF8 BOM encoding',raw.startswith(b'\xef\xbb\xbf'),path.name)
            relative=path.relative_to(ROOT).as_posix()
            if manifests:
                ck('Every source file is in manifest',relative in manifests,relative)
                if relative in manifests:
                    ck('Source SHA256 matches saved manifest',hashlib.sha256(raw).hexdigest()==manifests[relative]['sha256'],relative)
                    eq('Source byte size matches manifest',len(raw),int(manifests[relative]['byte_size']),relative)
            local=0
            with path.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f)
                ck('CSV header matches schema exactly',reader.fieldnames==s['fields'],relative)
                for r in reader:
                    local+=1;count+=1
                    key=tuple(r.get(k,'') for k in s['primary_key'].split('|'))
                    ck('Primary keys populated and globally unique',all(key) and key not in seen,table+':'+str(key))
                    seen.add(key)
                    ck('CSV rows have declared column count',None not in r and all(v is not None for v in r.values()),table+':'+str(key))
                    if s.get('types'):
                        valid=True
                        for col,typ in s['types'].items():
                            value=r[col]
                            if value=='':continue
                            if typ=='decimal_usd':valid=valid and bool(re.fullmatch(r'-?\d+\.\d{2}',value))
                            elif typ=='integer':valid=valid and bool(re.fullmatch(r'\d+',value))
                            elif typ=='boolean':valid=valid and value in ('True','False')
                            elif typ=='iso_date':
                                try: valid=valid and len(value)==10 and ds(value).isoformat()==value
                                except ValueError:valid=False
                            elif typ=='iso_month':valid=valid and bool(re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',value))
                        ck('Saved field types match data dictionary',valid,table+':'+str(key))
                    if 'currency' in r:ck('All source currency is USD',r['currency']=='USD',table)
                    if s['partition_column']:
                        ck('Monthly partitions contain matching dates',r[s['partition_column']][:7]==path.stem,table+':'+str(key))
                    if r.get('record_scope'):
                        ck('Record scope uses documented values',r['record_scope'] in ('observation_period','opening_support'),table)
            if manifests and relative in manifests:eq('Source row counts match manifest',local,int(manifests[relative]['row_count']),relative)
        rowcounts[table]=count
    actual={p.relative_to(ROOT).as_posix() for p in (ROOT/'sources').rglob('*.csv')}
    declared={p for s in SCHEMA.values() for p in s['physical_files']}
    ck('No undeclared or missing source partitions',actual==declared,str(actual^declared))
    # Metadata foreign keys are evaluated from disk, blanks allowed only as documented.
    relpath=ROOT/'metadata/relationships.csv'
    ck('Relationship catalog is present',relpath.exists())
    if relpath.exists():
        with relpath.open(encoding='utf-8-sig',newline='') as f:relations=list(csv.DictReader(f))
        for rel in relations:
            targets={r[rel['to_column']] for r in rows(rel['to_table'])}
            field,value=(rel['condition'].split('=',1) if rel.get('condition') else ('',''))
            for r in rows(rel['from_table']):
                if field and r.get(field)!=value:continue
                v=r[rel['from_column']]
                ck('Foreign key '+rel['from_table']+'.'+rel['from_column'],(not v and rel['nullable']=='True') or v in targets,str(v))
    return rowcounts

def subscription_checks():
    prices=keyed('stripe_billing/prices','price_id')
    history=defaultdict(list)
    for r in data('stripe_billing/subscription_history'):history[r['subscription_id']].append(r)
    items={r['subscription_version_id']:r for r in data('stripe_billing/subscription_item_history')}
    versions={r['subscription_version_id']:r for rr in history.values() for r in rr}
    customers=keyed('stripe_billing/customers','billing_customer_id')
    def value(v):
        item=items[v['subscription_version_id']]
        if v['status'] not in ('active','past_due'):return 0
        p=prices[item['price_id']]
        contract=rnd(m(p['unit_amount'])*int(item['quantity'])*(10000-int(item['recurring_discount_bps'])),10000)
        return rnd(contract,int(p['normalization_months']))
    snapshots={}
    for sid,vs in history.items():
        vs.sort(key=lambda r:r['effective_from'])
        first_paid=False
        for i,v in enumerate(vs):
            ck('Observed subscription states do not occur after cutoff',ds(v['effective_from'])<=CUTOFF,sid)
            expected_end=vs[i+1]['effective_from'] if i+1<len(vs) else ''
            ck('Subscription history has contiguous nonoverlapping intervals',v['effective_to']==expected_end,sid)
            if v['effective_to']:ck('Subscription effective interval is positive',v['effective_to']>v['effective_from'],sid)
            item=items[v['subscription_version_id']]
            ck('Item history dates match subscription version',item['effective_from']==v['effective_from'] and item['effective_to']==v['effective_to'],sid)
            eq('Purchased seat quantities match versioned subscription items',int(item['quantity']),int(v['quantity']),sid)
            ck('Item plan and recurrence match catalog',prices[item['price_id']]['plan_name']==v['plan_name'] and prices[item['price_id']]['recurring_interval']==v['billing_interval'],sid)
            eq('Contract recurring discount matches item history',int(item['recurring_discount_bps']),int(v['recurring_discount_bps']),sid)
            ck('Recurring discount is valid',0<=int(item['recurring_discount_bps'])<10000,sid)
            if v['status']=='past_due':
                ck('Past due state has explicit grace boundary',bool(v['grace_end_date']),sid)
                end=ds(v['effective_to']) if v['effective_to'] else END
                ck('No paid MRR survives beyond dunning grace',end<=ds(v['grace_end_date']),sid)
            if v['status'] in ('active','past_due'):
                ck('Paid service period contains version start',ds(v['period_start'])<=ds(v['effective_from'])<ds(v['period_end_exclusive']),sid)
            if v['status']=='not_started':ck('Known future contract has no started service',ds(v['period_start'])>CUTOFF,sid)
        snapshots[sid]=vs[-1]
    for s in data('stripe_billing/subscriptions'):
        v=snapshots[s['subscription_id']]
        ck('Current snapshots reconcile to last historical version',s['current_version_id']==v['subscription_version_id'] and s['status']==v['status'],s['subscription_id'])
    for e in data('stripe_billing/subscription_events'):
        ck('Lifecycle event date matches referenced effective state',e['event_date']==versions[e['subscription_version_id']]['effective_from'],e['event_id'])
        ck('Lifecycle events are observed by cutoff',ds(e['event_date'])<=CUTOFF,e['event_id'])
    for t in data('stripe_billing/trials'):
        ck('Trials are free and before paid activation',not t['paid_activation_date'] or t['paid_activation_date']>=t['scheduled_trial_end'],t['trial_id'])
        if t['actual_trial_end']:ck('No future actual trial end',ds(t['actual_trial_end'])<=CUTOFF,t['trial_id'])
    for p in prices.values():
        if p['recurring_interval']=='year':
            monthly=prices[p['price_id'].replace('_year_','_month_')]
            eq('Annual catalog discount equals two free months',m(p['unit_amount']),10*m(monthly['unit_amount']),p['price_id'])
    con=keyed('contracts/contracts','contract_id')
    eventvalues=sum_by('contracts/contract_events','contract_id','committed_value_change')
    inv_by_contract=defaultdict(list)
    for i in data('stripe_billing/invoices'):inv_by_contract[i['contract_id']].append(i)
    for c in con.values():
        eq('Contract commitment rollforward',eventvalues[c['contract_id']],m(c['current_committed_amount']),c['contract_id'])
        ck('Contracts signed no later than cutoff',ds(c['signed_date'])<=CUTOFF,c['contract_id'])
        p=prices[c['price_id']]
        calc=rnd(m(p['unit_amount'])*int(c['quantity_at_signature'])*(10000-int(c['recurring_discount_bps'])),10000)
        eq('Original signed contract quantity price discount arithmetic',m(c['original_committed_amount']),calc,c['contract_id'])
        if c['known_future_start']=='True':
            ck('Future signed contract has no actual invoice or paid MRR',not inv_by_contract[c['contract_id']] and ds(c['service_start'])>CUTOFF,c['contract_id'])
        # Catalog sales window applies to first sale. Renewals and reactivations may retain legacy pricing.
        if c['term_type']=='initial' and c['known_future_start']=='False':
            ck('Initial contract uses price effective at activation',ds(p['effective_from'])<=ds(c['service_start']) and (not p['effective_to'] or ds(c['service_start'])<ds(p['effective_to'])),c['contract_id'])
    # Independent MRR snapshots and bridges are derived solely from histories, not invoice cash or generator summaries.
    monthly={}
    for mi in range(24):
        y=2024+(10+mi)//12;mo=(10+mi)%12+1;a=date(y,mo,1);b=monthnext(a);month=a.strftime('%Y-%m')
        opening=closing=0;mov=Counter();paid=annual=seats=0;startcohort={};endcohort={};minimum={}
        for sid,vs in history.items():
            previous=0;ever=False;old_at_start=0;closing_value=0
            for v in vs:
                amount=value(v);vd=ds(v['effective_from'])
                if vd<a:old_at_start=amount
                if vd<b:closing_value=amount
                if a<=vd<b:
                    delta=amount-previous
                    if previous==0 and amount>0:mov['reactivation' if ever else 'new']+=amount
                    elif amount==0 and previous>0:mov['churn']+=previous
                    elif delta>0:mov['expansion']+=delta
                    elif delta<0:mov['contraction']-=delta
                if amount>0:ever=True
                previous=amount
            opening+=old_at_start;closing+=closing_value
            if old_at_start:
                startcohort[sid]=old_at_start
                endcohort[sid]=closing_value
                minimum[sid]=min([old_at_start]+[value(v) for v in vs if a<=ds(v['effective_from'])<b])
            if closing_value:
                paid+=1
                last=[v for v in vs if ds(v['effective_from'])<b][-1]
                annual+=last['billing_interval']=='year';seats+=int(last['quantity'])
        eq('Monthly historical MRR bridge reconciles',opening+mov['new']+mov['expansion']-mov['contraction']-mov['churn']+mov['reactivation'],closing,month)
        if mi:eq('MRR month opening equals prior month closing',opening,monthly[prevmonth]['closing_mrr'],month)
        monthly[month]=dict(opening_mrr=opening,new_mrr=mov['new'],expansion_mrr=mov['expansion'],contraction_mrr=mov['contraction'],
            churn_mrr=mov['churn'],reactivation_mrr=mov['reactivation'],closing_mrr=closing,closing_arr=closing*12,
            paid_accounts=paid,annual_paid_accounts=annual,monthly_paid_accounts=paid-annual,purchased_seats=seats,
            cohort_nrr=Decimal(sum(endcohort.values()))/opening if opening else Decimal(0),
            cohort_grr=Decimal(sum(minimum.values()))/opening if opening else Decimal(0))
        prevmonth=month
    return history,versions,items,value,monthly

def billing_checks(versions,items):
    invoices=keyed('stripe_billing/invoices','invoice_id');lines=data('stripe_billing/invoice_lines')
    totals=defaultdict(lambda:Counter())
    prices=keyed('stripe_billing/prices','price_id')
    def full_version(vid):
        v=versions[vid];item=items[vid];p=prices[item['price_id']]
        return rnd(m(p['unit_amount'])*int(item['quantity'])*(10000-int(item['recurring_discount_bps'])),10000)
    for l in lines:
        k=l['invoice_id'];totals[k]['gross']+=m(l['gross_amount']);totals[k]['discount']+=m(l['discount_amount']);totals[k]['net']+=m(l['net_amount']);totals[k]['tax']+=m(l['tax_amount'])
        eq('Invoice line net equals gross minus discounts',m(l['net_amount']),m(l['gross_amount'])-m(l['discount_amount']),l['invoice_line_id'])
        ck('Invoice service coverage has positive end-exclusive duration',l['service_end_exclusive']>l['service_start'],l['invoice_line_id'])
        if l['line_type']=='subscription':
            gross=m(l['unit_amount'])*int(l['quantity'])
            eq('Subscription invoice quantity times catalog unit amount',m(l['gross_amount']),gross,l['invoice_line_id'])
            net=rnd(gross*(10000-int(l['recurring_discount_bps'])),10000)
            eq('Subscription recurring discount arithmetic',m(l['net_amount']),net,l['invoice_line_id'])
            v=versions[l['new_version_id']]
            eq('Issued purchased seats reconcile to actual invoice lines',int(l['quantity']),int(v['quantity']),l['invoice_line_id'])
        else:
            eq('Proration base traces to old and new commercial histories',m(l['proration_base_difference']),full_version(l['new_version_id'])-full_version(l['old_version_id']),l['invoice_line_id'])
            expected=rnd(m(l['proration_base_difference'])*(ds(l['service_end_exclusive'])-ds(l['service_start'])).days,
                         (ds(l['full_period_end_exclusive'])-ds(l['full_period_start'])).days)
            eq('Positive proration sign and day arithmetic',m(l['net_amount']),expected,l['invoice_line_id'])
    paid=sum_by('stripe_payments/charges','invoice_id','amount')
    arcredits=sum_by('stripe_billing/credit_notes','invoice_id','ar_credit_amount')
    writeoffs=sum_by('stripe_billing/writeoffs','invoice_id','amount')
    for i in invoices.values():
        k=i['invoice_id'];t=totals[k]
        eq('Invoice header subtotal matches lines',m(i['subtotal']),t['gross'],k)
        eq('Invoice header recurring discounts match lines',m(i['recurring_discount_amount']),t['discount'],k)
        eq('Invoice total net plus taxes',m(i['total']),t['net']+t['tax'],k)
        eq('Synthetic zero sales tax assumption enforced',m(i['tax_amount']),0,k)
        eq('Invoice paid amount matches actual successful captures',m(i['amount_paid']),paid[k],k)
        eq('Invoice AR credits match credit notes',m(i['ar_credit_applied']),arcredits[k],k)
        eq('Invoice writeoffs match bad debt register',m(i['written_off']),writeoffs[k],k)
        eq('Invoice AR balance arithmetic',m(i['amount_remaining']),m(i['total'])-paid[k]-arcredits[k]-writeoffs[k],k)
        ck('Invoice unpaid balance is nonnegative',m(i['amount_remaining'])>=0,k)
        ck('Invoice issuance actual cutoff',ds(i['issue_date'])<=CUTOFF,k)
    charge_by_id=keyed('stripe_payments/charges','charge_id')
    refunds_by_charge=sum_by('stripe_payments/refunds','charge_id','amount')
    for ch in charge_by_id.values():
        ck('Refunds never exceed captured charge',refunds_by_charge[ch['charge_id']]<=m(ch['amount']),ch['charge_id'])
        ck('Captured charge is after invoice and before cutoff',invoices[ch['invoice_id']]['issue_date']<=ch['charge_date']<=CUTOFF.isoformat(),ch['charge_id'])
    success=Counter((r['invoice_id'],r['charge_date'],r['amount']) for r in charge_by_id.values())
    attempts=Counter()
    for a in data('stripe_billing/payment_attempts'):
        eq('Failed attempts create zero captured cash',m(a['captured_amount']),m(a['attempted_amount']) if a['status']=='succeeded' else 0,a['attempt_id'])
        ck('No future actual payment attempts',ds(a['attempt_date'])<=CUTOFF,a['attempt_id'])
        if a['status']=='succeeded':attempts[(a['invoice_id'],a['attempt_date'],a['captured_amount'])]+=1
    ck('Every successful attempt maps once to a charge',success==attempts,str(success-attempts))
    creditlines=defaultdict(int)
    for l in data('stripe_billing/credit_note_lines'):
        creditlines[l['credit_note_id']]-=m(l['net_amount'])
        ck('Credit note line is a negative economic adjustment',m(l['net_amount'])<0,l['credit_note_line_id'])
        if l['line_type'] in ('contraction','unused_after_dunning'):
            if l['line_type']=='unused_after_dunning':
                full=-m(l['proration_base_difference'])
                expected=-(full-rnd(full*(ds(l['service_start'])-ds(l['full_period_start'])).days,
                    (ds(l['full_period_end_exclusive'])-ds(l['full_period_start'])).days))
            else:
                eq('Contraction base traces to old and new commercial histories',m(l['proration_base_difference']),full_version(l['new_version_id'])-full_version(l['old_version_id']),l['credit_note_line_id'])
                expected=rnd(m(l['proration_base_difference'])*(ds(l['service_end_exclusive'])-ds(l['service_start'])).days,
                             (ds(l['full_period_end_exclusive'])-ds(l['full_period_start'])).days)
            eq('Negative proration sign and exact day arithmetic',m(l['net_amount']),expected,l['credit_note_line_id'])
    commercial_credit=defaultdict(int)
    for l in data('stripe_billing/credit_note_lines'):
        if l['line_type']!='goodwill_incident':commercial_credit[l['contract_id']]+=m(l['net_amount'])
    billed_contract=sum_by('stripe_billing/invoices','contract_id','total')
    for c in data('contracts/contracts'):
        if c['known_future_start']=='False':
            eq('Contract commitment equals billed service plus commercial credits',m(c['current_committed_amount']),billed_contract[c['contract_id']]+commercial_credit[c['contract_id']],c['contract_id'])
    refundcredits=sum_by('stripe_payments/refunds','credit_note_id','amount')
    notes=keyed('stripe_billing/credit_notes','credit_note_id')
    for n in notes.values():
        k=n['credit_note_id']
        eq('Credit note face amount equals negative line sum',m(n['credit_amount']),creditlines[k],k)
        eq('Credit splits into AR reduction and refund',m(n['credit_amount']),m(n['ar_credit_amount'])+m(n['refund_credit_amount']),k)
        eq('Refund credit settles in actual cash refunds',m(n['refund_credit_amount']),refundcredits[k],k)
        ck('Credit note observed cutoff',ds(n['issue_date'])<=CUTOFF,k)
    for r in data('stripe_payments/refunds'):
        ck('Refund timeline follows paid charge and credit',charge_by_id[r['charge_id']]['charge_date']<=r['refund_date'] and notes[r['credit_note_id']]['issue_date']<=r['refund_date']<=CUTOFF.isoformat(),r['refund_id'])
    copies=data('quickbooks/client_invoices')
    eq('Accounting invoice mirrors are one per Stripe invoice',len(copies),len(invoices))
    for r in copies:eq('Accounting invoice mirror has same amount',m(r['total']),m(invoices[r['stripe_invoice_id']]['total']),r['accounting_invoice_id'])
    receipts=keyed('quickbooks/customer_receipts','charge_id')
    eq('Accounting receipts are one per charge',len(receipts),len(charge_by_id))
    for ch in charge_by_id.values():eq('Accounting receipt cash matches captured charge',m(receipts[ch['charge_id']]['amount']),m(ch['amount']),ch['charge_id'])
    for r in data('quickbooks/client_credit_notes'):eq('Accounting credit mirrors have same face amount',m(r['amount']),m(notes[r['stripe_credit_note_id']]['credit_amount']),r['accounting_credit_note_id'])

def recognition_checks():
    invoice_lines=keyed('stripe_billing/invoice_lines','invoice_line_id')
    credit_lines=keyed('stripe_billing/credit_note_lines','credit_note_line_id')
    grouped=defaultdict(list)
    for r in data('revenue_accounting/revenue_schedule'):
        grouped[(r['source_document_type'],r['source_line_id'])].append(r)
    ck('Every performance obligation has a complete revenue schedule',
       set(grouped)=={('invoice_line',x) for x in invoice_lines}|{('credit_note_line',x) for x in credit_lines})
    actual_months=defaultdict(int);future=defaultdict(int)
    for (typ,k),schedule in grouped.items():
        line=invoice_lines[k] if typ=='invoice_line' else credit_lines[k]
        a,b=ds(line['service_start']),ds(line['service_end_exclusive'])
        amt=m(line['net_amount'])
        schedule.sort(key=lambda r:r['service_start'])
        eq('Revenue schedule conserves signed invoice or credit cents',sum(m(r['amount']) for r in schedule),amt,k)
        prior=a;allocated=0
        for r in schedule:
            ra,rb=ds(r['service_start']),ds(r['service_end_exclusive'])
            ck('Recognition schedule covers continuous exact service period',ra==prior and ra<rb<=b,k)
            if line.get('recognition_method')=='reverse_original_unearned':
                basis=invoice_lines[line['allocation_basis_invoice_line_id']]
                ba,bb,bamt=ds(basis['service_start']),ds(basis['service_end_exclusive']),m(basis['net_amount'])
                expected=-(rnd(bamt*(rb-ba).days,(bb-ba).days)-rnd(bamt*(ra-ba).days,(bb-ba).days))
                eq('Dunning credits mirror original unearned day allocations',m(r['amount']),expected,r['recognition_id'])
            else:
                current=rnd(amt*(rb-a).days,(b-a).days)
                eq('Recognition uses independent cumulative daily allocation',m(r['amount']),current-allocated,r['recognition_id'])
                allocated=current
            prior=rb
            status='opening_earned' if rb<=START else ('actual_earned' if rb<=END else 'future_unearned')
            ck('Earned versus future unearned classification',r['schedule_status']==status,r['recognition_id'])
            ck('Recognition month matches earned service month',r['recognition_month']==ra.strftime('%Y-%m'),r['recognition_id'])
            if status=='future_unearned':
                ck('Future earned schedule has no actual posting date',r['actual_posting_date']=='',r['recognition_id'])
                future[(typ,k,r['invoice_id'])]+=m(r['amount'])
            else:
                ck('Actual recognition date is earned and within cutoff',r['actual_posting_date']==(rb-timedelta(days=1)).isoformat() and ds(r['actual_posting_date'])<=CUTOFF,r['recognition_id'])
                if status=='actual_earned':actual_months[r['recognition_month']]+=m(r['amount'])
        ck('Recognition final exclusive end matches obligation',prior==b,k)
    snapshot={(r['source_document_type'],r['source_line_id'],r['invoice_id']):m(r['remaining_unearned_amount']) for r in data('revenue_accounting/contract_liability_snapshot')}
    ck('Contract liability snapshot matches remaining source-line schedules',dict(future)==snapshot)
    return actual_months

def temporal_checks():
    """Regression checks for economic event ordering, beyond a balanced GL."""
    history=defaultdict(list)
    for r in data('stripe_billing/subscription_history'):history[r['subscription_id']].append(r)
    prices=keyed('stripe_billing/prices','price_id')
    notes=keyed('stripe_billing/credit_notes','credit_note_id')
    invoices=keyed('stripe_billing/invoices','invoice_id')
    for l in data('stripe_billing/credit_note_lines'):
        if l['line_type']!='goodwill_incident':continue
        note=notes[l['credit_note_id']];d=note['issue_date']
        vs=[v for v in history[l['subscription_id']] if v['effective_from']<=d and (not v['effective_to'] or d<v['effective_to'])]
        ck('Goodwill uses commercial state actually effective at incident date',len(vs)==1,l['credit_note_id'])
        if vs:
            v=vs[0]
            p=prices['price_'+v['plan_name'].lower()+'_month_'+v['catalog_version']]
            monthly=rnd(m(p['unit_amount'])*int(v['quantity'])*(10000-int(v['recurring_discount_bps'])),10000)
            expected=min(max(100,rnd(monthly*15,100)),m(invoices[l['invoice_id']]['total'])//4)
            eq('Goodwill credit has no future seat or plan lookahead',-m(l['net_amount']),expected,l['credit_note_id'])
            ck('Goodwill plan is the incident-date plan',l['plan_name']==v['plan_name'],l['credit_note_id'])
    firstevent={r['organization_id']:r['event_date'] for r in data('product_analytics/onboarding_events') if r['event_name']=='first_workflow_run'}
    firstusage={}
    for r in rows('product_analytics/organization_daily_activity'):
        if int(r['workflow_runs'])>0:
            org=r['organization_id'];firstusage[org]=min(firstusage.get(org,r['activity_date']),r['activity_date'])
    for org,d in firstusage.items():
        ck('Workflow usage never precedes product first-run activation',org in firstevent and firstevent[org]<=d,org+':'+d)
    for org,d in firstevent.items():
        if START.isoformat()<=d<=CUTOFF.isoformat():
            ck('Observed first-run activation matches first actual workflow day',firstusage.get(org)==d,org+':'+d)
    trialmonths=Counter(r['trial_start'][:7] for r in data('stripe_billing/trials'))
    for source in ['meta_ads','google_ads']:
        claims=Counter()
        for r in data(source+'/daily_campaign_metrics'):claims[r['activity_date'][:7]]+=int(r['platform_attributed_trials'])
        for month,value in claims.items():
            ck('Each ad platform trial claim count fits observed company trial pool',value<=trialmonths[month],source+':'+month+':'+str(value))
    canceled={n['invoice_id']:n['issue_date'][:7] for n in notes.values() if n['reason']=='unused_after_dunning'}
    netafter=Counter()
    for r in data('revenue_accounting/revenue_schedule'):
        iid=r['invoice_id']
        if iid in canceled and r['recognition_month']>canceled[iid]:
            netafter[(iid,r['recognition_month'])]+=m(r['amount'])
    for k,value in netafter.items():eq('Dunning termination reverses all later unearned service exactly',value,0,str(k))

def operating_checks(history,versions):
    employees=keyed('gusto/employees','employee_id')
    salary=defaultdict(list)
    for s in data('gusto/salary_history'):salary[s['employee_id']].append(s)
    for ss in salary.values():
        ss.sort(key=lambda r:r['effective_from'])
        for i,s in enumerate(ss):
            ck('Salary effective intervals are contiguous',s['effective_to']==(ss[i+1]['effective_from'] if i+1<len(ss) else ''),s['salary_history_id'])
    allocation=sum_by('gusto/payroll_allocations','payroll_line_id','allocated_employer_cost')
    register=keyed('gusto/payroll_register','payroll_line_id');payruns=keyed('gusto/payroll_runs','payroll_run_id')
    run=defaultdict(lambda:Counter())
    for r in register.values():
        k=r['payroll_line_id'];e=employees[r['employee_id']]
        eq('Payroll gross less withholding equals net',m(r['gross_pay'])-m(r['employee_withholding']),m(r['net_pay']),k)
        eq('Employer cost adds only employer tax to gross',m(r['employer_cost']),m(r['gross_pay'])+m(r['employer_tax']),k)
        eq('Synthetic withholding model is explicit',m(r['employee_withholding']),rnd(m(r['gross_pay'])*22,100),k)
        eq('Synthetic employer tax model is explicit',m(r['employer_tax']),rnd(m(r['gross_pay'])*82,1000),k)
        eq('Payroll account allocations do not create additional expense',allocation[k],m(r['employer_cost']),k)
        ck('Payroll employee department agrees with master',r['department']==e['department'],k)
        start=max(ds(r['period_start']),ds(e['hire_date']))
        stop=min(ds(r['period_end_exclusive']),ds(e['termination_date'])+timedelta(days=1)) if e['termination_date'] else ds(r['period_end_exclusive'])
        eq('Actual payroll uses employed earned days',int(r['active_earned_days']),(stop-start).days,k)
        sal=[s for s in salary[e['employee_id']] if s['effective_from']<=start.isoformat() and (not s['effective_to'] or s['effective_to']>start.isoformat())]
        ck('Each payroll line has one effective salary',len(sal)==1,k)
        if sal:
            monthly=rnd(m(sal[0]['annual_salary']),12)
            expected=rnd(monthly*(stop-start).days,calendar.monthrange(start.year,start.month)[1])
            eq('Salary history independently reproduces gross earned pay',m(r['gross_pay']),expected,k)
        ck('Payroll earned before cutoff',ds(r['earned_posting_date'])<=CUTOFF,k)
        for f in ['gross_pay','employee_withholding','net_pay','employer_tax','employer_cost']:run[r['payroll_run_id']][f]+=m(r[f])
    for p in payruns.values():
        for f in ['gross_pay','employee_withholding','net_pay','employer_tax']:eq('Payroll run totals reconcile to employee lines',m(p[f]),run[p['payroll_run_id']][f],p['payroll_run_id']+f)
        eq('Payroll funding includes net and both tax components',m(p['funding_amount']),m(p['net_pay'])+m(p['employee_withholding'])+m(p['employer_tax']),p['payroll_run_id'])
    funded=sum_by('gusto/payroll_funding','payroll_run_id','amount')
    for p in payruns.values():eq('Only occurred payroll funding is recorded',funded[p['payroll_run_id']],m(p['funding_amount']) if p['actual_funding_date'] else 0,p['payroll_run_id'])
    for r in data('gusto/payroll_funding'):
        ck('Actual payroll funding cutoff and timing',payruns[r['payroll_run_id']]['earned_posting_date']<r['funding_date']<=CUTOFF.isoformat(),r['payroll_funding_id'])
    support=[]
    for a in data('gusto/payroll_allocations'):
        dep=register[a['payroll_line_id']]['department']
        ck('Support COGS versus OPEX classification policy',(a['account_code'] in ('5010','6200')) if dep=='Customer Success/Support' else a['account_code'] in {'Engineering/R&D':'6000','Sales & Marketing':'6100','G&A':'6300'}[dep],a['payroll_allocation_id'])
        if dep=='Customer Success/Support' and a['account_code']=='5010':
            eq('Support payroll COGS allocation is 80 percent',m(a['allocated_employer_cost']),rnd(m(register[a['payroll_line_id']]['employer_cost'])*80,100),a['payroll_allocation_id'])
    bills=keyed('quickbooks/vendor_bills','vendor_bill_id')
    lines=sum_by('quickbooks/vendor_bill_lines','vendor_bill_id','amount')
    payments=sum_by('quickbooks/vendor_payments','vendor_bill_id','amount')
    for b in bills.values():
        k=b['vendor_bill_id']
        eq('AP bill lines reconcile to header',lines[k],m(b['total']),k)
        eq('Vendor payments match bill paid amount',payments[k],m(b['amount_paid']),k)
        eq('AP unpaid rollforward',m(b['total'])-payments[k],m(b['amount_remaining']),k)
        ck('No future AP bill issuance',ds(b['issue_date'])<=CUTOFF,k)
    for p in data('quickbooks/vendor_payments'):
        ck('Vendor actual payments occur after bill and by cutoff',bills[p['vendor_bill_id']]['issue_date']<=p['payment_date']<=CUTOFF.isoformat(),p['vendor_payment_id'])
    prepaid=defaultdict(int)
    for s in data('quickbooks/vendor_service_schedule'):
        prepaid[s['vendor_bill_id']]+=m(s['amount'])
        actual=bool(s['actual_posting_date'])
        ck('Future prepaid allocations are not posted actual costs',actual==(s['schedule_status']!='future_unearned'),s['vendor_schedule_id'])
        if actual:ck('No future actual prepaid expense',ds(s['actual_posting_date'])<=CUTOFF,s['vendor_schedule_id'])
    for b in bills.values():
        if b['recognition_type']=='prepaid':eq('Prepaid service schedule conserves invoice value',prepaid[b['vendor_bill_id']],m(b['total']),b['vendor_bill_id'])
    resource_daily=sum_by('aws/daily_resource_cost','cloud_invoice_id','cost')
    resources=keyed('aws/resources','resource_id')
    resource_total=defaultdict(int)
    for r in data('aws/daily_resource_cost'):
        resource_total[(r['cloud_invoice_id'],r['resource_id'])]+=m(r['cost'])
        ck('Cloud usage actual cutoff',START<=ds(r['usage_date'])<=CUTOFF,r['resource_day_id'])
    allocated=defaultdict(int);shared=defaultdict(int)
    monthly_workflows=defaultdict(lambda:defaultdict(int))
    # Build product activity and independently reconcile user daily detail month by month.
    users=keyed('product_analytics/users','user_id')
    seats=defaultdict(list)
    assigned_count=Counter()
    for s in data('product_analytics/seat_assignments_history'):
        seats[s['user_id']].append((s['assigned_from'],s['assigned_to_exclusive']))
        assigned_count[s['subscription_version_id']]+=1
    for vid,v in versions.items():
        maximum=int(v['quantity']) if v['status'] in ('active','past_due','trialing') else 0
        ck('Assigned seats do not exceed billable entitlement',assigned_count[vid]<=maximum,vid)
    orgs=keyed('product_analytics/organizations','organization_id')
    customer_map=keyed('stripe_billing/customers','billing_customer_id')
    for o in orgs.values():
        ck('Organization billing customer mapping is bidirectionally exact',customer_map[o['billing_customer_id']]['organization_id']==o['organization_id'],o['organization_id'])
    orgfiles=files('product_analytics/organization_daily_activity');userfiles=files('product_analytics/user_daily_activity')
    for op,up in zip(orgfiles,userfiles):
        agg=defaultdict(lambda:[0,0,0,0,0])
        with up.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                d=r['activity_date'];uid=r['user_id'];org=r['organization_id']
                ck('Daily user identity and tenant mapping',uid in users and users[uid]['organization_id']==org,r['user_day_id'])
                ck('Daily active user has an assigned seat on activity date',any(a<=d and (not b or d<b) for a,b in seats.get(uid,[])),r['user_day_id'])
                v=agg[(d,org)]
                for i,field in enumerate(['logins','workflow_runs','automation_actions','export_actions']):v[i]+=int(r[field])
                v[4]+=1
        found=set()
        with op.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                d=r['activity_date'];org=r['organization_id'];found.add((d,org));v=agg[(d,org)]
                for i,field in enumerate(['logins','workflow_runs','automation_actions','export_actions','active_users']):
                    eq('Organization daily activity reconciles to actual user activity',int(r[field]),v[i],r['organization_day_id']+field)
                ck('Active users <= assigned users <= purchased seats for paid service',
                   int(r['active_users'])<=int(r['assigned_users']) and (r['service_status']=='trialing' or int(r['assigned_users'])<=int(r['purchased_billable_seats'])),r['organization_day_id'])
                vs=history[r['subscription_id']]
                vv=[x for x in vs if x['effective_from']<=d and (not x['effective_to'] or d<x['effective_to'])]
                ck('Daily product service is active on historical date',len(vv)==1 and vv[0]['status'] in ('active','past_due','trialing'),r['organization_day_id'])
                if vv:
                    eq('Product purchased seats reproduce subscription history',int(r['purchased_billable_seats']),0 if vv[0]['status']=='trialing' else int(vv[0]['quantity']),r['organization_day_id'])
                    eq('Daily assigned user count reproduces seat assignments',int(r['assigned_users']),assigned_count[vv[0]['subscription_version_id']],r['organization_day_id'])
                monthly_workflows[d[:7]][org]+=int(r['workflow_runs'])
        ck('Every user-day has its organization-day parent',set(agg)<=found,op.name)
    for r in data('aws/monthly_cost_allocations'):
        k=(r['cloud_invoice_id'],r['resource_id']);allocated[k]+=m(r['allocated_cost'])
        if r['allocation_bucket']=='shared':shared[k]+=m(r['allocated_cost'])
        else:
            eq('Tenant cloud allocation weights trace to measured workflows',int(r['workflow_weight']),monthly_workflows[r['billing_month']][r['organization_id']]+1,r['cloud_allocation_id'])
    for k,amount in resource_total.items():
        eq('Cloud tenant plus shared allocations conserve real modeled cost',allocated[k],amount,str(k))
        resource=resources[k[1]]
        eq('Cloud shared portion policy is explicit',shared[k],rnd(amount*30,100) if resource['environment']=='production' else amount,str(k))
    for i in data('aws/monthly_invoices'):
        eq('Cloud monthly bill equals daily source cost',m(i['amount']),resource_daily[i['cloud_invoice_id']],i['cloud_invoice_id'])
        eq('Cloud AP representation is the same cost',m(bills[i['vendor_bill_id']]['total']),m(i['amount']),i['cloud_invoice_id'])
    for source in ['meta_ads','google_ads']:
        monthspend=defaultdict(int)
        for r in data(source+'/daily_campaign_metrics'):
            monthspend[r['activity_date'][:7]]+=m(r['spend'])
            eq('Advertising micros versus USD conversion',int(r['cost_micros']),m(r['spend'])*10000,r['campaign_day_id'])
            ck('Ad daily spend actual cutoff',START<=ds(r['activity_date'])<=CUTOFF,r['campaign_day_id'])
        for i in data(source+'/monthly_billing'):
            eq('Advertising monthly bill equals daily spend',m(i['amount']),monthspend[i['billing_month']],i['ad_invoice_id'])
            eq('Advertising AP representation is same expense',m(bills[i['vendor_bill_id']]['total']),m(i['amount']),i['ad_invoice_id'])
    contracts=keyed('contracts/contracts','contract_id')
    mappings=keyed('hubspot/won_contract_mapping','deal_id')
    deals=keyed('hubspot/deals','deal_id')
    for d in deals.values():
        if d['stage']=='closed_won':
            ck('Won CRM deals map to signed contracts',d['deal_id'] in mappings and d['contract_id'] in contracts,d['deal_id'])
            if d['contract_id'] in contracts:ck('Won contract signature equals actual CRM close',contracts[d['contract_id']]['signed_date']==d['actual_close_date'],d['deal_id'])
        else:
            ck('Pipeline never supplies contracted subscription ARR',d['contract_id']=='' and d['subscription_id']=='' and m(d['contracted_arr_at_signature'])==0,d['deal_id'])
        ck('No future actual CRM close',not d['actual_close_date'] or ds(d['actual_close_date'])<=CUTOFF,d['deal_id'])
    for s in data('hubspot/deal_stage_history'):ck('No future observed CRM stage',ds(s['entered_date'])<=CUTOFF,s['stage_event_id'])
    for b in data('planning/original_monthly_budget'):ck('Original budget approved before every budget month',ds(b['approved_date'])<ds(b['budget_month']+'-01'),b['budget_line_id'])
    for h in data('planning/hiring_requisitions'):ck('Future hiring plans are not actual employees',h['actual_employee_id']=='' and h['status']=='open_not_hired' and ds(h['expected_start_date'])>CUTOFF,h['requisition_id'])
    obs=data('planning/known_obligations');keys=[x['deduplication_key'] for x in obs]
    ck('Known obligations deduplication keys are unique',len(keys)==len(set(keys)))
    openbills={k:b for k,b in bills.items() if m(b['amount_remaining'])}
    ap_obs={x['source_id']:x for x in obs if x['obligation_type']=='open_ap'}
    ck('Known obligations include all open AP once',set(openbills)==set(ap_obs))
    for k,b in openbills.items():eq('Known AP obligation is a copy of payable balance',m(ap_obs[k]['amount']),m(b['amount_remaining']),k)

def ledger_checks(actual_revenue):
    chart=keyed('quickbooks/chart_of_accounts','account_code')
    opening={r['account_code']:m(r['signed_balance']) for r in data('quickbooks/opening_trial_balance')}
    eq('Opening trial balance is balanced',sum(opening.values()),0)
    gl=list(rows('quickbooks/general_ledger'));journals=defaultdict(int);observed=defaultdict(int)
    monthly=defaultdict(lambda:defaultdict(lambda:[0,0]))
    for g in gl:
        k=g['account_code'];dr,cr=m(g['debit']),m(g['credit'])
        ck('GL accounts exist and debit-credit signs are valid',k in chart and dr>=0 and cr>=0 and (dr==0 or cr==0),g['gl_line_id'])
        ck('GL actual posting date within 24-month window',START<=ds(g['posting_date'])<=CUTOFF,g['gl_line_id'])
        journals[g['journal_id']]+=dr-cr
        observed[(g['source_event'],g['source_id'],k)]+=dr-cr
        monthly[g['posting_date'][:7]][k][0]+=dr;monthly[g['posting_date'][:7]][k][1]+=cr
    for k,value in journals.items():eq('Every journal balances to the cent',value,0,k)
    # Build every expected actual accounting distribution from saved independent operational sources.
    expected=defaultdict(int)
    def post(d,event,source,entries):
        if START.isoformat()<=d<=CUTOFF.isoformat():
            for code,value in entries:expected[(event,source,code)]+=value
    for i in data('stripe_billing/invoices'):post(i['issue_date'],'invoice_finalized',i['invoice_id'],[('1100',m(i['total'])),('2200',-m(i['total']))])
    for c in data('stripe_payments/charges'):
        amt=m(c['amount']);fee=rnd(amt*29,1000)+30
        post(c['charge_date'],'customer_payment',c['charge_id'],[('1010',amt),('1100',-amt)])
        post(c['charge_date'],'processor_fee',c['charge_id'],[('5030',fee),('1010',-fee)])
    for c in data('stripe_billing/credit_notes'):
        post(c['issue_date'],'credit_note_issued',c['credit_note_id'],[('2200',m(c['credit_amount'])),('1100',-m(c['ar_credit_amount'])),('2300',-m(c['refund_credit_amount']))])
    for r in data('stripe_payments/refunds'):post(r['refund_date'],'customer_refund',r['refund_id'],[('2300',m(r['amount'])),('1010',-m(r['amount']))])
    for w in data('stripe_billing/writeoffs'):post(w['writeoff_date'],'ar_writeoff',w['writeoff_id'],[('6350',m(w['amount'])),('1100',-m(w['amount']))])
    revenue_account={'Starter':'4000','Team':'4010','Scale':'4020'}
    for r in data('revenue_accounting/revenue_schedule'):
        if r['actual_posting_date']:
            post(r['actual_posting_date'],'revenue_recognition',r['recognition_id'],[('2200',m(r['amount'])),(revenue_account[r['plan_name']],-m(r['amount']))])
    for p in data('stripe_payments/payouts'):
        post(p['initiated_date'],'payout_initiated',p['payout_id'],[('1020',m(p['amount'])),('1010',-m(p['amount']))])
        if p['actual_bank_receipt_date']:post(p['actual_bank_receipt_date'],'payout_bank_received',p['payout_id'],[('1000',m(p['amount'])),('1020',-m(p['amount']))])
    payroll=keyed('gusto/payroll_register','payroll_line_id')
    allocations=defaultdict(list)
    for p in data('gusto/payroll_allocations'):allocations[p['payroll_line_id']].append((p['account_code'],m(p['allocated_employer_cost'])))
    for p in payroll.values():post(p['earned_posting_date'],'payroll_accrual',p['payroll_line_id'],allocations[p['payroll_line_id']]+[('2100',-m(p['employer_cost']))])
    for p in data('gusto/payroll_funding'):post(p['funding_date'],'payroll_funding',p['payroll_funding_id'],[('2100',m(p['amount'])),('1000',-m(p['amount']))])
    billlines=defaultdict(list)
    for b in data('quickbooks/vendor_bill_lines'):billlines[b['vendor_bill_id']].append((b['account_code'],m(b['amount'])))
    for b in data('quickbooks/vendor_bills'):post(b['issue_date'],'vendor_bill',b['vendor_bill_id'],billlines[b['vendor_bill_id']]+[('2000',-m(b['total']))])
    for p in data('quickbooks/vendor_payments'):post(p['payment_date'],'vendor_payment',p['vendor_payment_id'],[('2000',m(p['amount'])),('1000',-m(p['amount']))])
    for p in data('quickbooks/vendor_service_schedule'):
        if p['actual_posting_date']:post(p['actual_posting_date'],'prepaid_amortization',p['vendor_schedule_id'],[(p['account_code'],m(p['amount'])),('1300',-m(p['amount']))])
    for d in data('quickbooks/depreciation_schedule'):post(d['posting_date'],'depreciation',d['depreciation_id'],[('6340',m(d['amount'])),('1590',-m(d['amount']))])
    for e in data('finance/equity_funding'):post(e['funding_date'],'equity_funding',e['equity_event_id'],[('1000',m(e['amount'])),('3000',-m(e['amount']))])
    for k in expected.keys()|observed.keys():eq('Every GL distribution matches one independent source event',observed[k],expected[k],str(k))
    tb=keyed('quickbooks/monthly_trial_balance','trial_balance_id')
    balances=dict(opening);monthclose={}
    for month,activity in sorted(monthly.items()):
        for code in chart:
            dr,cr=activity[code];close=balances[code]+dr-cr;r=tb[month+'_'+code]
            eq('Trial balance opening amount from independent rollforward',m(r['opening_signed_balance']),balances[code],month+code)
            eq('Trial balance monthly debits from GL',m(r['period_debits']),dr,month+code)
            eq('Trial balance monthly credits from GL',m(r['period_credits']),cr,month+code)
            eq('Trial balance ending balance from GL',m(r['closing_signed_balance']),close,month+code)
            balances[code]=close
        eq('Monthly trial balance closes to zero',sum(balances.values()),0,month)
        rev=sum(cr-dr for code,(dr,cr) in activity.items() if chart[code]['account_type']=='revenue')
        eq('Monthly recognized revenue reconciles schedules and GL',rev,actual_revenue[month],month)
        monthclose[month]=dict(balances)
    # Opening and closing subledgers are independently reconstructed using cutoff dates.
    def subledger(at):
        ar=sum(m(i['total']) for i in data('stripe_billing/invoices') if i['issue_date']<=at)
        ar-=sum(m(c['amount']) for c in data('stripe_payments/charges') if c['charge_date']<=at)
        ar-=sum(m(c['ar_credit_amount']) for c in data('stripe_billing/credit_notes') if c['issue_date']<=at)
        ar-=sum(m(w['amount']) for w in data('stripe_billing/writeoffs') if w['writeoff_date']<=at)
        ap=sum(m(b['total']) for b in data('quickbooks/vendor_bills') if b['issue_date']<=at)-sum(m(p['amount']) for p in data('quickbooks/vendor_payments') if p['payment_date']<=at)
        payrollbal=sum(m(p['funding_amount']) for p in data('gusto/payroll_runs') if p['earned_posting_date']<=at)-sum(m(p['amount']) for p in data('gusto/payroll_funding') if p['funding_date']<=at)
        deferred=sum(m(i['total']) for i in data('stripe_billing/invoices') if i['issue_date']<=at)-sum(m(c['credit_amount']) for c in data('stripe_billing/credit_notes') if c['issue_date']<=at)
        deferred-=sum(m(r['amount']) for r in data('revenue_accounting/revenue_schedule') if r['actual_posting_date'] and r['actual_posting_date']<=at)
        processor=sum(m(b['net']) for b in data('stripe_payments/balance_transactions') if b['transaction_date']<=at)-sum(m(p['amount']) for p in data('stripe_payments/payouts') if p['initiated_date']<=at)
        transit=sum(m(p['amount']) for p in data('stripe_payments/payouts') if p['initiated_date']<=at and (not p['actual_bank_receipt_date'] or p['actual_bank_receipt_date']>at))
        return {'1100':ar,'2000':-ap,'2100':-payrollbal,'2200':-deferred,'1010':processor,'1020':transit}
    for at,bal in [('2024-10-31',opening)]+[(monthend(ds(mm+'-01')).isoformat(),bb) for mm,bb in monthclose.items()]:
        for code,value in subledger(at).items():eq('Opening and monthly AR AP payroll deferred processor subledger reconcile',bal[code],value,at+':'+code)
    eq('Closing prepaid assets reconcile remaining vendor service',balances['1300'],sum(m(s['amount']) for s in data('quickbooks/vendor_service_schedule') if s['schedule_status']=='future_unearned'))
    eq('Closing equipment cost equals asset register',balances['1500'],sum(m(a['original_cost']) for a in data('quickbooks/fixed_assets')))
    eq('Closing accumulated depreciation equals asset schedules',-balances['1590'],sum(m(a['opening_accumulated_depreciation']) for a in data('quickbooks/fixed_assets'))+sum(m(d['amount']) for d in data('quickbooks/depreciation_schedule')))
    eq('Refund payable settles to zero',balances['2300'],0)
    # Payout / source-balance arithmetic, availability, bank cash and source payment mapping.
    payouts=keyed('stripe_payments/payouts','payout_id');payout_total=defaultdict(int)
    charges=keyed('stripe_payments/charges','charge_id');refunds=keyed('stripe_payments/refunds','refund_id')
    for t in data('stripe_payments/balance_transactions'):
        amount,fee,net=m(t['amount']),m(t['fee']),m(t['net'])
        eq('Processor balance transaction net equals gross less fee',amount-fee,net,t['balance_transaction_id'])
        if t['transaction_type']=='charge':
            eq('Charge balance transaction references captured amount',amount,m(charges[t['source_id']]['amount']),t['balance_transaction_id'])
            eq('Processor synthetic fee calculation',fee,rnd(amount*29,1000)+30,t['balance_transaction_id'])
        else:eq('Refund balance transaction uses negative cash sign',amount,-m(refunds[t['source_id']]['amount']),t['balance_transaction_id'])
        if t['payout_id']:
            p=payouts[t['payout_id']];payout_total[t['payout_id']]+=net
            ck('Payout does not precede processor availability',t['available_on']<=p['initiated_date'],t['balance_transaction_id'])
    bank=keyed('bank/statement','bank_transaction_id')
    for p in payouts.values():
        eq('Payout batch reconciles assigned transaction net',m(p['amount']),payout_total[p['payout_id']],p['payout_id'])
        if p['bank_transaction_id'] and p['actual_bank_receipt_date']>=START.isoformat():
            b=bank[p['bank_transaction_id']]
            eq('Processor payout equals actual bank receipt',m(p['amount']),m(b['amount']),p['payout_id'])
            ck('Payout receipt date matches bank statement',b['posting_date']==p['actual_bank_receipt_date'],p['payout_id'])
        if p['status']=='in_transit':ck('In-transit payouts have no future actual bank receipts',not p['actual_bank_receipt_date'] and not p['bank_transaction_id'],p['payout_id'])
    running=m(data('bank/opening_balance')[0]['opening_balance'])
    eq('Bank opening balance equals GL opening cash',running,opening['1000'])
    bymonth=defaultdict(lambda:Counter())
    for b in sorted(bank.values(),key=lambda r:(r['posting_date'],r['bank_transaction_id'])):
        ck('No future actual bank movements',START<=ds(b['posting_date'])<=CUTOFF,b['bank_transaction_id'])
        amount=m(b['amount']);running+=amount
        eq('Bank running balance recalculated from statement',running,m(b['running_balance']),b['bank_transaction_id'])
        bymonth[b['posting_date'][:7]]['in']+=max(0,amount);bymonth[b['posting_date'][:7]]['out']+=max(0,-amount)
    eq('Closing actual bank cash equals GL',running,balances['1000'])
    for source,datecol,amountcol,idcol in [
      ('quickbooks/vendor_payments','payment_date','amount','vendor_payment_id'),
      ('gusto/payroll_funding','funding_date','amount','payroll_funding_id'),
      ('finance/equity_funding','funding_date','amount','equity_event_id')]:
        for p in data(source):
            if p[datecol]>=START.isoformat():
                b=bank[p['bank_transaction_id']];sign=1 if source.startswith('finance') else -1
                eq('Actual vendor payroll financing payments match bank',m(b['amount']),sign*m(p[amountcol]),p[idcol])
                ck('Actual payment source id matches bank',b['source_id']==p[idcol] and b['posting_date']==p[datecol],p[idcol])
    for b in data('bank/monthly_balances'):
        month=b['month'];eq('Monthly bank cash equals monthly GL cash',m(b['closing_balance']),monthclose[month]['1000'],month)
        eq('Monthly bank statement cash in',m(b['cash_in']),bymonth[month]['in'],month)
        eq('Monthly bank statement cash out',m(b['cash_out']),bymonth[month]['out'],month)
        eq('Monthly bank statement rollforward',m(b['opening_balance'])+m(b['cash_in'])-m(b['cash_out']),m(b['closing_balance']),month)
    return monthly,monthclose,bymonth

def controls(mrr,monthly,balances,bankmonths):
    out=[];chart=keyed('quickbooks/chart_of_accounts','account_code')
    def amount_in(table,datefield,amountfield,month):return sum(m(r[amountfield]) for r in data(table) if r[datefield][:7]==month)
    bankreceipts=defaultdict(int)
    for p in data('stripe_payments/payouts'):
        if p['actual_bank_receipt_date']:bankreceipts[p['actual_bank_receipt_date'][:7]]+=m(p['amount'])
    for month,stats in sorted(mrr.items()):
        act=monthly[month];balance=balances[month]
        rev=sum(cr-dr for code,(dr,cr) in act.items() if chart[code]['account_type']=='revenue')
        cogs=sum(dr-cr for code,(dr,cr) in act.items() if code.startswith('5'))
        opex=sum(dr-cr for code,(dr,cr) in act.items() if code.startswith('6'))
        budget_rev=sum(m(r['budget_amount']) for r in data('planning/original_monthly_budget') if r['budget_month']==month and r['metric']=='recognized_revenue')
        budget_exp=sum(m(r['budget_amount']) for r in data('planning/original_monthly_budget') if r['budget_month']==month and r['metric']!='recognized_revenue')
        dateend=monthend(ds(month+'-01')).isoformat()
        hc=sum(e['hire_date']<=dateend and (not e['termination_date'] or e['termination_date']>dateend) for e in data('gusto/employees'))
        row=dict(month=month,**{k:(f'{v:.8f}' if k in ('cohort_nrr','cohort_grr') else (str(v) if k in ('paid_accounts','annual_paid_accounts','monthly_paid_accounts','purchased_seats') else fmt(v))) for k,v in stats.items()},
            gross_billings=fmt(amount_in('stripe_billing/invoices','issue_date','total',month)),
            credit_notes=fmt(amount_in('stripe_billing/credit_notes','issue_date','credit_amount',month)),
            net_billings=fmt(amount_in('stripe_billing/invoices','issue_date','total',month)-amount_in('stripe_billing/credit_notes','issue_date','credit_amount',month)),
            bookings=fmt(amount_in('contracts/contract_events','event_date','committed_value_change',month)),
            recognized_revenue=fmt(rev),captured_customer_cash=fmt(amount_in('stripe_payments/charges','charge_date','amount',month)),
            customer_refunds=fmt(amount_in('stripe_payments/refunds','refund_date','amount',month)),
            processor_fees=fmt(act['5030'][0]-act['5030'][1]),
            initiated_payouts=fmt(amount_in('stripe_payments/payouts','initiated_date','amount',month)),
            actual_payout_bank_receipts=fmt(bankreceipts[month]),bank_cash_in=fmt(bankmonths[month]['in']),
            bank_cash_out=fmt(bankmonths[month]['out']),closing_bank_cash=fmt(balance['1000']),
            closing_processor_balance=fmt(balance['1010']),closing_payouts_in_transit=fmt(balance['1020']),
            closing_ar=fmt(balance['1100']),closing_ap=fmt(-balance['2000']),closing_deferred_revenue=fmt(-balance['2200']),
            closing_payroll_payable=fmt(-balance['2100']),closing_prepaid_services=fmt(balance['1300']),
            cloud_expense=fmt(sum(act[k][0]-act[k][1] for k in ['5000','6010'])),
            advertising_expense=fmt(sum(act[k][0]-act[k][1] for k in ['6110','6120'])),
            gross_payroll=fmt(amount_in('gusto/payroll_register','earned_posting_date','gross_pay',month)),
            cogs=fmt(cogs),gross_profit=fmt(rev-cogs),opex=fmt(opex),net_income=fmt(rev-cogs-opex),
            closing_headcount=hc,original_budget_revenue=fmt(budget_rev),original_budget_expense=fmt(budget_exp))
        out.append(row)
    write_csv(ROOT/'validation/monthly_control_totals.csv',out)
    return out

def main():
    global ROOT,SCHEMA
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=ap.parse_args();ROOT=args.root.resolve()
    SCHEMA=json.loads((ROOT/'metadata/table_schemas.json').read_text(encoding='utf-8'))
    counts=structural()
    history,versions,items,value,mrr=subscription_checks()
    billing_checks(versions,items);revenue=recognition_checks();temporal_checks()
    operating_checks(history,versions)
    monthly,balances,banks=ledger_checks(revenue)
    control=controls(mrr,monthly,balances,banks)
    report=[]
    for name,r in REPORT.items():
        report.append(dict(check_name=name,status='FAIL' if r['failures'] else 'PASS',evaluated=r['evaluated'],
            failures=r['failures'],max_absolute_difference_cents=r['max_absolute_difference_cents'],examples=' | '.join(r['examples'])))
    write_csv(ROOT/'validation/validation_report.csv',report)
    summary=dict(validation_method='Independent Python process rereads saved files; no imports of generator or its monetary kernel',
        cutoff=CUTOFF.isoformat(),check_groups=len(report),evaluated_conditions=sum(r['evaluated'] for r in report),
        failures=sum(r['failures'] for r in report),source_logical_tables=len(counts),source_rows=sum(counts.values()),
        source_csv_files=sum(len(s['physical_files']) for s in SCHEMA.values()),monthly_controls=len(control),
        table_row_counts=counts)
    (ROOT/'validation/summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='table_row_counts'},indent=2))
    for r in report:
        if r['failures']:print('FAIL',r['check_name'],r['failures'],r['examples'])
    if summary['failures']:sys.exit(1)
if __name__=='__main__':main()
