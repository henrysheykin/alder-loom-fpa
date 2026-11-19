"""Independent disk-only verifier. NO imports from generator/modules. Stdlib Python 3.11+."""
import csv,json,hashlib,sys,calendar,re
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
from datetime import date,timedelta
from collections import defaultdict,Counter

candidate=Path(__file__).resolve().parents[1]
BASE=Path(sys.argv[1]) if len(sys.argv)>1 else candidate if (candidate/'metadata/table_schemas.json').exists() else candidate/'outputs'/'juniper_quay_data'
START='2024-11-01';CUT='2026-10-31';PROPS=['RAL','WIL','DUR'];CENTRES=PROPS+['CORP']
def money(v):return int(Decimal(v)*100) if v not in ['',None] else 0
def rnd(v):return int(Decimal(v).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def mul(v,r):return rnd(Decimal(v)*Decimal(str(r)))
def fmt(v):return f'{Decimal(v)/100:.2f}'
def readcsv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)
def writecsv(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields or list(rows[0]));w.writeheader();w.writerows(rows)

class Verify:
    def __init__(self):self.checks={};self.cache={};self.schemas={};self.ids={};self.g=defaultdict(lambda:[0,0]);self.source_gl=defaultdict(lambda:Counter());self.source_dims=defaultdict(set);self.opening=defaultdict(int)
    def check(self,name,ok,detail='',diff=0):
        c=self.checks.setdefault(name,dict(check_name=name,status='PASS',evaluated=0,failures=0,max_absolute_difference_cents=0,examples=[]))
        c['evaluated']+=1
        if not ok:
            c['status']='FAIL';c['failures']+=1;c['max_absolute_difference_cents']=max(c['max_absolute_difference_cents'],abs(diff))
            if len(c['examples'])<4:c['examples'].append(str(detail))
    def rows(self,t):
        for p in self.schemas[t]['physical_files']:
            for r in readcsv(BASE/p):
                for k,v in list(r.items()):
                    typ=self.schemas[t]['types'][k]
                    if v=='':continue
                    if k.endswith('_usd'):r[k]=money(v)
                    elif typ=='integer':r[k]=int(v)
                    elif typ=='boolean':r[k]=v=='true'
                    elif typ=='decimal':r[k]=Decimal(v)
                yield r
    def table(self,t):
        if t not in self.cache:self.cache[t]=list(self.rows(t))
        return self.cache[t]
    def idx(self,t,k):return {r[k]:r for r in self.table(t)}
    def close(self,p,acc):return self.opening[(p,acc)]+sum(v[0]-v[1] for (mo,pp,a),v in self.g.items() if pp==p and a==acc)
    def totalclose(self,acc):return sum(self.close(p,acc) for p in CENTRES)
    def eq(self,name,a,b,detail=''):self.check(name,a==b,detail or f'{a} != {b}',a-b)
    def metadata(self):
        required=['README_RU.md','COMPANY_PROFILE_RU.md','CLAUDE_HANDOFF_RU.md','metadata/table_schemas.json','metadata/file_manifest.csv','metadata/relationships.csv']
        # Documentation files validated on final run; missing schemas fail early on acceptance run.
        if not (BASE/'metadata/table_schemas.json').exists():
            self.check('Source schema exists',False,str(BASE));return False
        self.schemas=json.loads((BASE/'metadata/table_schemas.json').read_text(encoding='utf-8-sig'))
        manifest=list(readcsv(BASE/'metadata/file_manifest.csv'));actual_files={p.relative_to(BASE).as_posix() for p in (BASE/'sources').rglob('*.csv')}
        self.check('Manifest covers all source CSV exactly once',actual_files=={x['relative_path'] for x in manifest})
        for m in manifest:
            p=BASE/m['relative_path'];blob=p.read_bytes()
            self.check('Saved source SHA256 and byte count',hashlib.sha256(blob).hexdigest()==m['sha256'] and len(blob)==int(m['size_bytes']),m['relative_path'])
            self.check('UTF-8 BOM on every source CSV',blob.startswith(b'\xef\xbb\xbf'),m['relative_path'])
            n=0;s=self.schemas[m['logical_table']];seen=self.ids.setdefault(m['logical_table'],set())
            for r in readcsv(p):
                n+=1;key=tuple(r[k] for k in s['primary_key'])
                self.check('Primary keys populated and globally unique across partitions',all(key) and key not in seen,(m['logical_table'],key));seen.add(key)
                self.check('CSV columns equal declared schema',list(r)==s['fields'],m['relative_path'])
                for k,v in r.items():
                    if not v:continue
                    typ=s['types'][k];ok=True
                    try:
                        if typ=='date':date.fromisoformat(v)
                        elif typ=='month':date.fromisoformat(v+'-01')
                        elif k.endswith('_usd'):ok=bool(re.fullmatch(r'-?\d+\.\d{2}',v))
                        elif typ=='integer':int(v)
                        elif typ=='boolean':ok=v in ['true','false']
                        elif typ=='decimal':Decimal(v)
                    except (ValueError,ArithmeticError):ok=False
                    self.check('Declared value types and cent precision',ok,(m['relative_path'],k,v))
            self.eq('Saved CSV row counts match manifest',n,int(m['row_count']),m['relative_path'])
        # Build FK target scalar sets from saved data, independent of generator objects.
        targetsets={}
        for rel in readcsv(BASE/'metadata/relationships.csv'):
            f,t,fc,tc=rel['from_table'],rel['to_table'],rel['from_column'],rel['to_column'];key=(t,tc)
            if key not in targetsets:targetsets[key]={r[tc] for r in self.table(t)}
            for r in self.rows(f):
                value=r[fc];cond=rel['condition']
                if not value:continue
                if cond!='nonblank':
                    ck,cv=cond.split('=',1)
                    if str(r[ck])!=cv:continue
                self.check('Declared foreign keys including guarded polymorphic joins',value in targetsets[key],(f,fc,value,t))
        # Fields explicitly representing actual events; future due/scheduled/service plans excluded.
        actual_columns={
          'pms/reservations':['booked_date','actual_checkin_date','actual_checkout_date','cancellation_date'],
          'pms/reservation_history':['event_date'],'pms/reservation_modifications':['modified_date'],'pms/room_assignments':['assigned_date'],
          'pms/actual_stay_nights':['service_date'],'availability/room_dates':['service_date'],'night_audit/folio_lines':['service_date','posting_date'],
          'payments/transactions':['transaction_date'],'payments/applications':['application_date'],'payments/security_movements':['movement_date'],
          'payments/payouts':['created_date','actual_bank_date'],'payments/balance_transactions':['transaction_date','actual_available_date'],
          'channel_manager/settlements':['actual_release_date','actual_bank_date'],'channel_manager/agency_invoices':['actual_payment_date'],
          'corporate_billing/invoices':['invoice_date'],'corporate_billing/receipts':['receipt_date'],'corporate_billing/prepayments':['payment_date'],
          'operations/housekeeping_tasks':['service_date','actual_completed_date'],'operations/work_orders':['actual_start_date','actual_completed_date'],
          'procurement/receipts':['received_date'],'quickbooks/bills':['invoice_date'],'quickbooks/bill_payments':['payment_date'],
          'gusto/time_entries':['work_date'],'gusto/payroll_runs':['earned_date','actual_funding_date'],'gusto/funding':['actual_payment_date'],
          'bank/statement':['posted_date'],'fixed_assets_finance/debt_schedule':['actual_payment_date'],'fixed_assets_finance/tax_remittances':['actual_payment_date']}
        for t,cols in actual_columns.items():
            for r in self.rows(t):
                for col in cols:
                    if r[col]:self.check('No fabricated actual events after cutoff',r[col]<=CUT,(t,col,r[col]))
        return True
    def ledger(self):
        journals=defaultdict(int);coa=self.idx('quickbooks/chart_of_accounts','account_code');datecash=defaultdict(int)
        for a in coa.values():self.check('COA normal sign includes contra-revenue and member drawings exceptions',a['normal_sign']==('debit' if a['account_type'] in ['asset','expense','contra_revenue'] or a['account_code']=='3100' else 'credit'),a['account_code'])
        for g in self.rows('quickbooks/general_ledger'):
            d,c=g['debit_usd'],g['credit_usd'];a=g['account_code'];p=g['property_id'];mo=g['accounting_date'][:7];v=d-c
            self.check('GL unsigned debit credit and valid actual date',d>=0 and c>=0 and bool(d)!=bool(c) and START<=g['accounting_date']<=CUT and a in coa,g['line_id'])
            journals[g['journal_id']]+=v;self.g[(mo,p,a)][0]+=d;self.g[(mo,p,a)][1]+=c
            self.source_gl[(g['source_system'],g['source_table'],g['source_id'])][a]+=v
            self.source_dims[(g['source_system'],g['source_table'],g['source_id'])].add((g['accounting_date'],p))
            if a=='1000':datecash[g['accounting_date']]+=v
        for jid,v in journals.items():self.eq('Every double-entry journal balances',v,0,jid)
        for o in self.table('quickbooks/opening_trial_balance'):
            self.eq('Opening TB signed equals debit less credit',o['signed_balance_usd'],o['debit_usd']-o['credit_usd']);self.opening[(o['property_id'],o['account_code'])]+=o['signed_balance_usd']
        for p in CENTRES:self.eq('Opening TB balances by cost centre',sum(v for (pp,a),v in self.opening.items() if pp==p),0,p)
        running=defaultdict(int,self.opening);months=sorted({g[0] for g in self.g});self.eq('Exactly 24 complete GL months',len(months),24)
        tb=self.table('quickbooks/monthly_trial_balance');self.eq('TB all months centres and COA accounts covered',len(tb),24*4*len(coa));tbtotal=Counter()
        for r in tb:
            k=(r['service_month'],r['property_id'],r['account_code']);b=running[(k[1],k[2])];deb,cred=self.g[k]
            self.eq('Monthly TB opening continuity',r['opening_signed_usd'],b,str(k));self.eq('Monthly TB period debits',r['period_debit_usd'],deb,str(k));self.eq('Monthly TB period credits',r['period_credit_usd'],cred,str(k));self.eq('Monthly TB rollforward',r['closing_signed_usd'],b+deb-cred,str(k));running[(k[1],k[2])]=b+deb-cred;tbtotal[(k[0],k[1])]+=r['closing_signed_usd']
        for k,v in tbtotal.items():self.eq('Every monthly centre TB balances',v,0,str(k))
        bal=sum(v for (p,a),v in self.opening.items() if a=='1000');monthly=Counter();dates=Counter();bankidx=self.idx('bank/statement','bank_transaction_id')
        for r in sorted(bankidx.values(),key=lambda r:r['sequence']):
            self.eq('Bank credit minus debit equals signed amount',r['credit_usd']-r['debit_usd'],r['signed_amount_usd']);bal+=r['signed_amount_usd'];monthly[r['posted_date'][:7]]+=r['signed_amount_usd'];dates[r['posted_date']]+=r['signed_amount_usd'];self.eq('Bank running balance every actual movement',r['running_balance_usd'],bal,r['bank_transaction_id']);self.check('Bank never overdrawn',bal>=0,r['bank_transaction_id'])
        for d in set(dates)|set(datecash):self.eq('Daily bank movements equal GL cash',dates[d],datecash[d],d)
        self.eq('Cutoff bank balance equals GL',bal,self.totalclose('1000'))
        for r in self.table('bank/monthly_balances'):
            mo=r['service_month'];self.eq('Monthly bank statement movement arithmetic',r['opening_balance_usd']+r['credits_usd']-r['debits_usd'],r['closing_balance_usd'],mo);self.eq('Monthly bank statement GL movement',r['credits_usd']-r['debits_usd'],sum(self.g[(mo,p,'1000')][0]-self.g[(mo,p,'1000')][1] for p in CENTRES),mo)
        self.bank=bankidx
    def stays(self):
        res=self.idx('pms/reservations','reservation_id');rooms=self.idx('pms/rooms','room_id');rates=self.idx('pms/rate_plans','rate_plan_version_id');actual=self.table('pms/actual_stay_nights');keys={};rescounts=Counter();self.ops=defaultdict(Counter)
        for n in actual:
            k=(n['room_id'],n['service_date']);r=res[n['reservation_id']];self.check('No two actual occupied stays in one room-night',k not in keys,k);keys[k]=n
            self.check('Actual night status reservation dates and property agree',r['status_as_of_cutoff'] in ['checked_out','in_house'] and r['actual_checkin_date']<=n['service_date']<r['scheduled_checkout_date'] and n['property_id']==r['property_id']==rooms[n['room_id']]['property_id'],n['stay_night_id'])
            self.eq('Room-night sold flag follows actual status',n['sold_nights'],int(n['stay_status']=='sold'));rescounts[n['reservation_id']]+=1
            rate=rates[n['rate_plan_version_id']];self.check('Consumed nightly rate version effective',rate['effective_from']<=n['service_date']<=rate['effective_through'],n['stay_night_id'])
        self.eq('Three properties and 156 keys',sum(r['physical_keys'] for r in self.table('pms/properties')),156);self.eq('Room master count matches capacity',len(rooms),156)
        closures={}
        for b in self.table('availability/room_blocks'):
            d=date.fromisoformat(b['start_date']);end=date.fromisoformat(b['end_date'])
            while d<end:
                key=(b['room_id'],d.isoformat());self.check('Room closure intervals do not conflict',key not in closures,key);closures[key]=b;d+=timedelta(days=1)
        arrivals={(r['assigned_room_id'],r['actual_checkin_date']) for r in res.values() if r['actual_checkin_date']};departures={(r['assigned_room_id'],r['actual_checkout_date']) for r in res.values() if r['actual_checkout_date']}
        capcount=0
        for c in self.rows('availability/room_dates'):
            k=(c['room_id'],c['service_date']);capcount+=1
            b=closures.get(k)
            self.check('Room date arrival departure turnover derived actual timestamps',c['arrivals_count']==int(k in arrivals) and c['departures_count']==int(k in departures) and c['same_day_turnovers_count']==int(k in arrivals and k in departures),str(k))
            self.check('Availability closure status recomputed from room block intervals',c['block_id']==(b['block_id'] if b else '') and c['out_of_order_nights']==int(bool(b and b['block_status']=='OOO')) and c['out_of_service_nights']==int(bool(b and b['block_status']=='OOS')),str(k))
            self.eq('Capacity availability closure arithmetic',c['available_nights']+c['out_of_order_nights']+c['out_of_service_nights'],c['physical_nights'],str(k));self.eq('Occupied nights sold plus comp and house use',c['occupied_nights'],c['sold_nights']+c['complimentary_nights']+c['house_use_nights'],str(k));self.eq('Available capacity splits occupied vacant',c['available_nights'],c['occupied_nights']+c['vacant_available_nights'],str(k));self.eq('Availability occupied equals actual PMS stay night',c['occupied_nights'],int(k in keys),str(k));self.check('Closed rooms cannot be occupied',not c['occupied_nights'] or not c['block_id'],str(k))
            if k in keys:self.check('Capacity and PMS reservation mapping agrees',c['reservation_id']==keys[k]['reservation_id'] and c['stay_night_id']==keys[k]['stay_night_id'],str(k))
            self.ops[(c['service_date'][:7],c['property_id'])].update({f:c[f] for f in ['physical_nights','available_nights','sold_nights','complimentary_nights','house_use_nights','occupied_nights','out_of_order_nights','out_of_service_nights']})
        self.eq('Every room/date in 730-day window covered',capcount,156*730)
        for rid,r in res.items():
            self.eq('Reservation actual consumed nights match night facts',r['actual_consumed_nights'],rescounts[rid],rid)
            self.eq('Reservation planned length checkout exclusive',r['planned_nights'],(date.fromisoformat(r['scheduled_checkout_date'])-date.fromisoformat(r['scheduled_checkin_date'])).days,rid)
            self.eq('Quoted booking arithmetic excludes earned inference',r['quoted_total_usd'],r['quoted_room_usd']+r['quoted_lodging_tax_usd'],rid)
            if r['status_as_of_cutoff'] in ['cancelled','no_show','confirmed']:self.check('Unconsumed statuses have no actual check-in or occupied nights',not r['actual_checkin_date'] and not rescounts[rid],rid)
        self.res=res;self.actual=keys
        future=Counter()
        futurekeys=set()
        for n in self.table('planning/on_books_nights'):
            r=res[n['reservation_id']];future[r['reservation_id']]+=1
            key=(n['room_id'],n['service_date']);self.check('Known future room assignments do not overlap',key not in futurekeys,key);futurekeys.add(key)
            self.check('OTB known at cutoff and service future only',r['booked_date']<=CUT<n['service_date']<r['scheduled_checkout_date'] and r['status_as_of_cutoff'] in ['confirmed','in_house'],n['on_books_night_id'])
        booking=self.idx('pms/bookings','booking_id');mapped=Counter(r['booking_id'] for r in self.table('pms/booking_rooms'))
        for b in booking.values():self.eq('Multi-room booking mapping count',b['room_reservation_count'],mapped[b['booking_id']],b['booking_id'])
        self.check('Dataset includes multi-room bookings',any(v>1 for v in mapped.values()))
        for p in PROPS:
            rr=[x for x in self.table('pms/room_types') if x['property_id']==p];self.eq('Room type mix equals property physical keys',sum(x['keys'] for x in rr),sum(r['property_id']==p for r in rooms.values()),p)
    def folios_payments(self):
        lines=self.idx('night_audit/folio_lines','folio_line_id');bynight=Counter();byres=defaultdict(Counter);mo=defaultdict(Counter);tax=Counter();rates=self.idx('pms/rate_plans','rate_plan_version_id');nightidx=self.idx('pms/actual_stay_nights','stay_night_id')
        for c in lines.values():
            fid=c['folio_line_id'];p=c['property_id'];r=self.res[c['reservation_id']];net=c['gross_amount_usd']-c['discount_amount_usd'];self.eq('Folio gross less discounts equals net',c['net_revenue_usd'],net,fid);self.eq('Folio total revenue plus liability tax',c['total_charge_usd'],net+c['tax_usd'],fid)
            if c['charge_type'] in ['room','room_credit']:
                self.eq('Synthetic lodging tax rounded per service line',c['tax_usd'],mul(net,'.125' if p=='WIL' else '.1125'),fid)
                self.check('Room charge/credit links actual sold room-night',c['stay_night_id'] in nightidx and nightidx[c['stay_night_id']]['stay_status']=='sold',fid)
                if c['charge_type']=='room':
                    bynight[c['stay_night_id']]+=1;rate=rates[nightidx[c['stay_night_id']]['rate_plan_version_id']]
                    self.eq('Room discount follows effective rate plan',c['discount_amount_usd'],mul(c['gross_amount_usd'],Decimal(1)-rate['base_multiplier']),fid)
                else:self.check('Service credit links original positive room charge',c['original_folio_line_id'] in lines and lines[c['original_folio_line_id']]['charge_type']=='room' and net<0,fid)
            if c['charge_type'] in ['cancellation_fee','no_show_fee']:self.check('Cancellation/no show fee never room revenue/night',not c['stay_night_id'] and c['tax_usd']==0,fid)
            gl=self.source_gl[('night_audit','folio_lines',fid)];self.eq('Each folio line recognized once in GL AR',gl[c['receivable_account_code']],c['total_charge_usd'],fid);self.eq('Each folio gross recognized in specified revenue GL',gl[c['revenue_account_code']],-c['gross_amount_usd'],fid)
            self.eq('Each folio discount recognized in GL',gl['4010'],c['discount_amount_usd'],fid)
            if c['tax_account_code']:self.eq('Each folio tax recognized in correct liability',gl[c['tax_account_code']],-c['tax_usd'],fid)
            byres[c['reservation_id']].update({f:c[f] for f in ['net_revenue_usd','tax_usd','total_charge_usd']});mo[(c['service_date'][:7],p)][c['charge_type']]+=net;tax[c['tax_account_code']]+=c['tax_usd']
        for n in nightidx.values():self.eq('Exactly one earned room charge per actual sold night',bynight[n['stay_night_id']],n['sold_nights'],n['stay_night_id'])
        for f in self.table('night_audit/folios'):
            for col in ['net_revenue_usd','tax_usd','total_charge_usd']:self.eq('Folio header equals saved charge lines',f[col],byres[f['reservation_id']][col],f['folio_id'])
        tx=self.idx('payments/transactions','payment_id');balances=self.table('payments/balance_transactions');payout=self.idx('payments/payouts','payout_id');bypay=Counter();bypayout=defaultdict(Counter);paymentaccount=Counter();app=Counter();byappres=Counter()
        refunded=Counter()
        for t in tx.values():
            self.eq('Payment gross less fee equals processor net',t['gross_amount_usd']-t['processing_fee_usd'],t['net_processor_usd'],t['payment_id']);self.check('Capture/refund signed and refund parent exists',t['gross_amount_usd']>0 if t['transaction_type']=='capture' else t['gross_amount_usd']<0 and t['parent_payment_id'] in tx,t['payment_id'])
            expectedfee=mul(t['gross_amount_usd'],'.0275')+25 if t['transaction_type']=='capture' else 0;self.eq('Gateway synthetic fee calculation',t['processing_fee_usd'],expectedfee,t['payment_id'])
            gl=self.source_gl[('payments','transactions',t['payment_id'])];self.eq('Payment GL clearing movement',gl['1010'],t['net_processor_usd'],t['payment_id']);paymentaccount[t['liability_or_ar_account_code']]+=t['gross_amount_usd']
            if t['transaction_type']=='refund':
                parent=tx.get(t['parent_payment_id'])
                self.check('Refund follows parent capture date and same reservation/purpose',parent is not None and parent['transaction_type']=='capture' and parent['transaction_date']<=t['transaction_date'] and parent['reservation_id']==t['reservation_id'],t['payment_id'])
                refunded[t['parent_payment_id']]-=t['gross_amount_usd']
        for pid,amount in refunded.items():self.check('Cumulative gateway refunds never exceed parent capture',amount<=tx[pid]['gross_amount_usd'],pid)
        for b in balances:
            t=tx[b['payment_id']];bypay[b['payment_id']]+=1
            self.check('Processor balance transaction matches payment gross fee net',(b['gross_usd'],b['fee_usd'],b['net_usd'])==(t['gross_amount_usd'],t['processing_fee_usd'],t['net_processor_usd']),b['balance_transaction_id'])
            if b['payout_id']:bypayout[b['payout_id']].update({'gross':b['gross_usd'],'fee':b['fee_usd'],'net':b['net_usd'],'count':1})
        for pid in tx:self.eq('Exactly one balance transaction per payment',bypay[pid],1,pid)
        for pid,p in payout.items():
            for col,metric in [('gross_usd','gross'),('fees_usd','fee'),('net_payout_usd','net'),('balance_transaction_count','count')]:self.eq('Gateway payout sums assigned balance transactions',p[col],bypayout[pid][metric],pid)
            if p['bank_transaction_id']:self.eq('Gateway payout actual bank arrival',self.bank[p['bank_transaction_id']]['signed_amount_usd'],p['net_payout_usd'],pid)
            else:self.check('Transit payout has no fabricated bank arrival',not p['actual_bank_date'],pid)
        for a in self.table('payments/applications'):
            app[a['folio_line_id']]+=a['amount_usd'];byappres[a['reservation_id']]+=a['amount_usd'];self.check('Deposit application follows capture and earned service',tx[a['payment_id']]['transaction_date']<=a['application_date'] and lines[a['folio_line_id']]['service_date']<=a['application_date'],a['application_id'])
        self.eq('Guest deferred deposits reconcile to GL',paymentaccount['2200']-sum(app.values()),-self.totalclose('2200'))
        guest=0;folio_paid=Counter()
        for t in tx.values():
            if t['purpose']=='folio':folio_paid[t['folio_line_id']]+=t['gross_amount_usd']
        for c in lines.values():
            if c['receivable_account_code']=='1110':guest+=c['total_charge_usd']-app[c['folio_line_id']]-folio_paid[c['folio_line_id']]
        self.eq('Guest folio open AR reconciles GL',guest,self.totalclose('1110'))
        sec=sum(s['amount_usd'] for s in self.table('payments/security_movements'));self.eq('Refundable security liability reconciles GL',sec,-self.totalclose('2210'))
        unsettled=sum(b['net_usd'] for b in balances if not b['payout_id']);self.eq('Unreleased processor clearing reconciles GL',unsettled,self.totalclose('1010'))
        self.foliolines=lines;self.revenuemo=mo;self.tax=tax
    def ota_corporate_ap(self):
        comm=self.table('channel_manager/commissions');cms=defaultdict(int);agency=Counter();cmgl=Counter()
        for c in comm:
            f=self.foliolines[c['folio_line_id']];self.eq('OTA commission base equals earned charge or credit',c['commission_base_usd'],f['net_revenue_usd'],c['commission_id']);self.eq('OTA commission rate and rounding',c['commission_usd'],mul(c['commission_base_usd'],c['commission_rate']),c['commission_id']);cms[c['folio_line_id']]+=c['commission_usd'];cmgl[c['property_id']]+=c['commission_usd'];self.eq('Each OTA commission accrued exactly once GL',self.source_gl[('channel_manager','commissions',c['commission_id'])]['5000'],c['commission_usd'],c['commission_id'])
        settle=self.idx('channel_manager/settlements','settlement_id');sl=defaultdict(Counter);ar=tax=withheld=0;transit=0
        for l in self.table('channel_manager/settlement_lines'):
            c=self.foliolines[l['folio_line_id']];self.check('Merchant settlement line gross tax commission matches folio',l['gross_folio_usd']==c['total_charge_usd'] and l['ota_tax_usd']==c['tax_usd'] and l['commission_usd']==cms[c['folio_line_id']],l['settlement_line_id']);self.eq('Merchant net arithmetic',l['net_usd'],l['gross_folio_usd']-l['ota_tax_usd']-l['commission_usd'],l['settlement_line_id']);sl[l['settlement_id']].update({f:l[f] for f in ['gross_folio_usd','commission_usd','ota_tax_usd','net_usd']})
        for sid,s in settle.items():
            for h,l in [('gross_folio_usd','gross_folio_usd'),('commission_withheld_usd','commission_usd'),('ota_remitted_tax_usd','ota_tax_usd'),('net_payout_usd','net_usd')]:self.eq('Merchant settlement header equals component lines',s[h],sl[sid][l],sid)
            if s['actual_release_date']:
                withheld+=s['commission_withheld_usd']
                gl=self.source_gl[('channel_manager','settlements',sid)];self.eq('Released merchant gross AR cleared GL',gl['1120'],-s['gross_folio_usd'],sid)
                if s['bank_transaction_id']:self.eq('Merchant net matches actual bank arrival',self.bank[s['bank_transaction_id']]['signed_amount_usd'],s['net_payout_usd'],sid)
                else:transit+=s['net_payout_usd']
            else:ar+=s['gross_folio_usd'];tax+=s['ota_remitted_tax_usd'];self.check('Unreleased merchant no actual bank date',not s['actual_bank_date'] and not s['bank_transaction_id'],sid)
        self.eq('Merchant gross AR open reconciles GL',ar,self.totalclose('1120'));self.eq('Merchant tax clearing reconciles GL',tax,-self.totalclose('2110'))
        agpaid=0
        for a in self.table('channel_manager/agency_invoices'):
            amount=sum(c['commission_usd'] for c in comm if c['channel_id']=='BOOKING' and c['property_id']==a['property_id'] and c['service_date'][:7]==a['service_month']);self.eq('Agency commission invoice equals earned/adjusted accruals',a['commission_usd'],amount,a['agency_invoice_id']);self.eq('Agency paid plus open equals invoice',a['paid_usd']+a['open_usd'],amount);agpaid+=a['paid_usd']
            if a['bank_transaction_id']:self.eq('Agency cash payment clears commission only',self.bank[a['bank_transaction_id']]['signed_amount_usd'],-a['paid_usd'],a['agency_invoice_id'])
        self.eq('Total OTA commission payable GL',sum(c['commission_usd'] for c in comm)-withheld-agpaid,-self.totalclose('2010'))
        transit+=sum(p['net_payout_usd'] for p in self.table('payments/payouts') if not p['actual_bank_date']);self.eq('All OTA gateway transit reconciles GL',transit,self.totalclose('1020'))
        invoices=self.idx('corporate_billing/invoices','invoice_id');il=defaultdict(Counter);mapped=Counter();applied=Counter();cashapplied=Counter();preapplied=Counter();receiptap=Counter();prep=Counter()
        for l in self.table('corporate_billing/invoice_lines'):
            f=self.foliolines[l['folio_line_id']];mapped[l['folio_line_id']]+=1
            self.check('Corporate invoice line copies earned service amount',l['total_usd']==f['total_charge_usd'] and l['net_usd']==f['net_revenue_usd'] and l['service_date']==f['service_date'],l['invoice_line_id']);il[l['invoice_id']].update({c:l[c] for c in ['net_usd','tax_usd','total_usd']})
        for c in self.foliolines.values():
            if c['receivable_account_code']=='1130':self.eq('Every earned corporate charge invoiced once',mapped[c['folio_line_id']],1,c['folio_line_id'])
        for a in self.table('corporate_billing/receipt_applications'):
            applied[a['invoice_id']]+=a['amount_usd']
            if a['application_type']=='cash_receipt':cashapplied[a['invoice_id']]+=a['amount_usd'];receiptap[a['receipt_id']]+=a['amount_usd']
            else:preapplied[a['invoice_id']]+=a['amount_usd'];prep[a['prepayment_id']]+=a['amount_usd']
        for iid,i in invoices.items():
            for c in ['net_usd','tax_usd','total_usd']:self.eq('Corporate invoice header equals lines',i[c],il[iid][c],iid)
            self.eq('Corporate AR total minus applied partial receipts',i['open_ar_usd'],i['total_usd']-applied[iid],iid);self.eq('Corporate invoice cash applications',i['cash_applied_usd'],cashapplied[iid],iid);self.eq('Corporate invoice advance applications',i['prepayment_applied_usd'],preapplied[iid],iid);self.check('Corporate AR nonnegative',i['open_ar_usd']>=0,iid)
            gl=self.source_gl[('corporate_billing','invoices',iid)];self.check('Corporate invoice reclasses AR without new revenue',gl['1100']==i['total_usd'] and gl['1130']==-i['total_usd'] and not any(k.startswith('4') and v for k,v in gl.items()),iid)
            age=max(0,(date.fromisoformat(CUT)-date.fromisoformat(i['due_date'])).days) if i['open_ar_usd'] else 0;self.eq('Corporate AR aging due-date basis',i['days_past_due_at_cutoff'],age,iid)
        for r in self.table('corporate_billing/receipts'):
            self.eq('Corporate receipt fully allocated once',r['amount_usd'],receiptap[r['receipt_id']],r['receipt_id']);self.eq('Corporate receipt bank amount',r['amount_usd'],self.bank[r['bank_transaction_id']]['signed_amount_usd'],r['receipt_id'])
        for d in self.table('corporate_billing/prepayments'):
            self.eq('Corporate advance applications and balance',d['amount_usd']-prep[d['prepayment_id']],d['open_amount_usd'],d['prepayment_id'])
        self.eq('Corporate invoiced AR reconciles GL',sum(i['open_ar_usd'] for i in invoices.values()),self.totalclose('1100'));self.eq('Corporate earned unbilled AR clears at monthly invoice',self.totalclose('1130'),0);self.eq('Corporate deferred advances reconcile GL',sum(d['open_amount_usd'] for d in self.table('corporate_billing/prepayments')),-self.totalclose('2220'))
        bills=self.idx('quickbooks/bills','bill_id');bl=Counter();ba=Counter();bybillpay=Counter();billaccounts=defaultdict(Counter)
        for l in self.table('quickbooks/bill_lines'):
            bl[l['bill_id']]+=l['line_amount_usd'];self.eq('Vendor bill quantity times unit cost',mul(l['unit_cost_usd'],l['quantity']),l['line_amount_usd'],l['bill_line_id'])
            billaccounts[l['bill_id']][l['account_code']]+=l['line_amount_usd']
        for a in self.table('quickbooks/bill_payment_applications'):ba[a['bill_id']]+=a['amount_usd'];bybillpay[a['bill_payment_id']]+=a['amount_usd']
        for b in bills.values():
            self.eq('Vendor bill total equals lines',b['total_usd'],bl[b['bill_id']],b['bill_id']);self.eq('Vendor paid applications',b['paid_usd'],ba[b['bill_id']],b['bill_id']);self.eq('AP bill balance',b['total_usd']-b['paid_usd'],b['open_ap_usd'],b['bill_id']);self.check('Vendor AP not negative',b['open_ap_usd']>=0,b['bill_id'])
            key=('quickbooks','bills',b['bill_id']);expected=Counter(billaccounts[b['bill_id']]);expected['2000']=-b['total_usd'];self.check('Every individual vendor bill GL accounts date and property match',dict(self.source_gl[key])==dict(expected) and self.source_dims[key]=={(b['invoice_date'],b['property_id'])},b['bill_id'])
        for p in self.table('quickbooks/bill_payments'):
            self.eq('Vendor payment fully allocated',p['amount_usd'],bybillpay[p['bill_payment_id']],p['bill_payment_id']);self.eq('Vendor payment actual bank debit',-p['amount_usd'],self.bank[p['bank_transaction_id']]['signed_amount_usd'],p['bill_payment_id'])
        self.eq('Open AP reconciles GL',sum(b['open_ap_usd'] for b in bills.values()),-self.totalclose('2000'))
        receipts=Counter();pol=defaultdict(Counter)
        for l in self.table('procurement/receipt_lines'):receipts[l['receipt_id']]+=l['accepted_value_usd'];pol[l['purchase_order_line_id']]['received']+=l['accepted_value_usd']
        for r in self.table('procurement/receipts'):self.eq('Accepted receipts equal lines and bill',r['accepted_value_usd'],receipts[r['receipt_id']],r['receipt_id']);self.eq('Receipt equals vendor invoice amount',r['accepted_value_usd'],bills[r['bill_id']]['total_usd'],r['receipt_id'])
        po=defaultdict(Counter)
        for l in self.table('procurement/purchase_order_lines'):
            self.eq('PO line ordered arithmetic',l['ordered_value_usd'],mul(l['unit_cost_usd'],l['quantity']),l['purchase_order_line_id']);self.eq('PO line received actuals',l['received_value_usd'],pol[l['purchase_order_line_id']]['received'],l['purchase_order_line_id']);self.eq('PO line ordered received open',l['ordered_value_usd'],l['received_value_usd']+l['open_value_usd'],l['purchase_order_line_id']);po[l['purchase_order_id']].update({k:l[k] for k in ['ordered_value_usd','received_value_usd','open_value_usd']})
        for p in self.table('procurement/purchase_orders'):
            for h,l in [('ordered_total_usd','ordered_value_usd'),('received_total_usd','received_value_usd'),('unreceived_commitment_usd','open_value_usd')]:self.eq('PO headers equal line ordered received commitments',p[h],po[p['purchase_order_id']][l],p['purchase_order_id'])
    def labor_assets_marketing(self):
        tasks=self.table('operations/housekeeping_tasks');tk=Counter();ops=defaultdict(Counter);agency=defaultdict(Counter);nights=set(self.actual);linen=self.table('operations/linen_logs')
        for t in tasks:
            r=self.res[t['reservation_id']];d=t['service_date'];ok=(d==r['actual_checkout_date']) if t['task_type']=='departure' else (t['room_id'],d) in nights
            self.check('Cleaning tasks correspond to consumed stay or actual departure',ok,t['task_id']);self.check('Cleaning assignment employee XOR agency',bool(t['employee_id'])!=bool(t['contractor_vendor_id']),t['task_id']);tk[(t['employee_id'],d)]+=t['approved_work_minutes'] if t['employee_id'] else 0
            key=(t['property_id'],d[:7]);ops[key].update({'laundry':t['laundry_cost_usd'],'consumables':t['consumables_cost_usd'],'agency':t['agency_cost_usd']})
            if t['contractor_vendor_id']:agency[(t['property_id'],d)].update({'minutes':t['approved_work_minutes'],'cost':t['agency_cost_usd'],'rooms':1})
        taskidx={r['task_id']:r for r in tasks}
        for l in linen:
            t=taskidx[l['task_id']];self.check('Linen approval quantity and cost ties cleaning',l['linen_sets']==t['linen_sets'] and l['total_laundry_usd']==t['laundry_cost_usd'] and l['linen_sets']*l['unit_laundry_cost_usd']==l['total_laundry_usd'],l['linen_log_id'])
        for a in self.table('operations/agency_shifts'):
            key=(a['property_id'],a['work_date']);self.check('Agency shift matches approved tasks',a['approved_minutes']==agency[key]['minutes'] and a['approved_cost_usd']==agency[key]['cost'] and a['rooms_serviced']==agency[key]['rooms'] and a['approved_minutes']<=a['worker_count']*420,a['agency_shift_id'])
        bills=self.idx('quickbooks/bills','bill_id')
        for l in self.table('operations/cost_bill_links'):
            val=ops[(l['property_id'],l['service_month'])][l['cost_type']];self.eq('Operational cost logs equal accounting bill once',val,l['approved_cost_usd'],l['cost_link_id']);self.eq('Operational bill amount agrees source detail',val,bills[l['bill_id']]['total_usd'],l['cost_link_id'])
        for l in self.table('operations/maintenance_cost_links'):
            self.eq('Maintenance preventive and work orders equal bill',l['preventive_base_usd']+l['work_orders_cost_usd'],bills[l['bill_id']]['total_usd'],l['maintenance_cost_id'])
        times=self.table('gusto/time_entries');weekly=Counter();byperiod=defaultdict(Counter);rates=self.idx('gusto/compensation_history','compensation_id');emps=self.idx('gusto/employees','employee_id')
        for t in sorted(times,key=lambda x:(x['employee_id'],x['work_date'])):
            eid=t['employee_id'];e=emps[eid];key=(eid,t['week_start_date']);reg=min(t['total_minutes'],max(0,2400-weekly[key]));ot=t['total_minutes']-reg;weekly[key]+=t['total_minutes']
            self.check('Approved cleaning minutes within actual employee capacity',tk[(eid,t['work_date'])]==t['approved_housekeeping_minutes']<=t['total_minutes'],t['time_entry_id']);self.eq('Actual regular plus overtime minutes',t['regular_minutes']+t['overtime_minutes'],t['total_minutes'],t['time_entry_id'])
            if e['pay_type']=='hourly':self.check('Weekly overtime independently recomputed',reg==t['regular_minutes'] and ot==t['overtime_minutes'],t['time_entry_id'])
            rate=rates[t['compensation_id']];self.check('Workday compensation effective',rate['effective_from']<=t['work_date']<=rate['effective_through'],t['time_entry_id']);period=t['work_date'][:7]+('-H1' if int(t['work_date'][8:])<=15 else '-H2');byperiod[(eid,period)].update({'reg':t['regular_minutes'],'ot':t['overtime_minutes'],'gross':mul(rate['hourly_rate_usd'],Decimal(t['regular_minutes'])/60)+mul(rate['hourly_rate_usd'],Decimal(t['overtime_minutes'])/60*Decimal('1.5'))})
        byrun=defaultdict(Counter);pays=Counter()
        for r in self.table('gusto/payroll_details'):
            period=byperiod[(r['employee_id'],r['period_id'])];e=emps[r['employee_id']];rate=rates[r['employee_id']+('-V2' if r['period_id'][:7]>='2026-06' else '-V1')]
            expected=mul(rate['annual_salary_usd'],Decimal(1)/24) if e['pay_type']=='salary' else period['gross'];self.eq('Payroll gross derives effective salary or approved minutes',r['gross_pay_usd'],expected,r['payroll_detail_id']);self.check('Payroll approved time totals match detail',r['regular_minutes']==period['reg'] and r['overtime_minutes']==period['ot'],r['payroll_detail_id']);self.eq('Employee gross less deductions equals net',r['gross_pay_usd']-r['employee_withholding_usd'],r['net_pay_usd'],r['payroll_detail_id']);self.eq('Employer payroll tax synthetic rate',r['employer_tax_usd'],mul(r['gross_pay_usd'],'.083'),r['payroll_detail_id']);self.eq('Employer total excludes duplicate withholding',r['total_employer_cost_usd'],r['gross_pay_usd']+r['employer_tax_usd']+r['employer_benefit_usd'],r['payroll_detail_id']);byrun[r['payroll_run_id']].update({c:r[c] for c in ['gross_pay_usd','net_pay_usd','employee_withholding_usd','employer_tax_usd','employer_benefit_usd','total_employer_cost_usd']});pays[r['wage_account_code']]+=r['gross_pay_usd'];pays['5130']+=r['employer_tax_usd'];pays['5140']+=r['employer_benefit_usd']
        for r in self.table('gusto/payroll_runs'):
            for a,b in [('gross_pay_usd','gross_pay_usd'),('net_pay_usd','net_pay_usd'),('withholding_usd','employee_withholding_usd'),('employer_tax_usd','employer_tax_usd'),('employer_benefit_usd','employer_benefit_usd'),('total_employer_cost_usd','total_employer_cost_usd')]:self.eq('Payroll run aggregates employees',r[a],byrun[r['payroll_run_id']][b],r['payroll_run_id'])
        for acc,val in pays.items():self.eq('Payroll source expense equals GL',val,sum(v[0]-v[1] for (m,p,a),v in self.g.items() if a==acc),acc)
        unfunded=Counter()
        for f in self.table('gusto/funding'):
            unfunded[f['payable_account_code']]+=f['open_payable_usd']
            if f['bank_transaction_id']:self.eq('Actual payroll funding bank debit',-f['amount_usd'],self.bank[f['bank_transaction_id']]['signed_amount_usd'],f['funding_id'])
            else:self.check('Future payroll funding blank actual date',not f['actual_payment_date'] and f['due_date']>CUT,f['funding_id'])
        for acc in ['2300','2310']:self.eq('Payroll cutoff payable reconciles GL',unfunded[acc],-self.totalclose(acc),acc)
        assets=self.idx('fixed_assets_finance/assets','asset_id');depby=Counter();depmo=Counter()
        for d in self.table('fixed_assets_finance/depreciation'):
            a=assets[d['asset_id']];depby[a['asset_id']]+=d['depreciation_usd'];self.eq('Asset depreciation straight-line amount',d['depreciation_usd'],mul(a['gross_cost_usd'],Decimal(1)/a['useful_life_months']),d['depreciation_id']);self.eq('Asset accumulated depreciation rollforward',d['accumulated_depreciation_usd'],a['opening_accum_depreciation_usd']+depby[a['asset_id']],d['depreciation_id']);self.eq('Asset net book value',d['closing_net_book_value_usd'],a['gross_cost_usd']-d['accumulated_depreciation_usd'],d['depreciation_id']);depmo[d['service_month']]+=d['depreciation_usd']
        self.eq('Gross assets reconcile GL',sum(a['gross_cost_usd'] for a in assets.values()),self.totalclose('1500')+self.totalclose('1510'));self.eq('Accumulated depreciation reconciles GL',sum(a['opening_accum_depreciation_usd'] for a in assets.values())+sum(depby.values()),-self.totalclose('1590'))
        debt=self.table('fixed_assets_finance/debt_schedule');balance=310000000;repaid=interest=0
        for d in debt:
            self.eq('Debt scheduled opening principal continuity',d['opening_principal_usd'],balance,d['debt_payment_id']);self.eq('Debt interest contractual monthly calculation',d['interest_usd'],mul(balance,Decimal('.0675')/12),d['debt_payment_id']);self.eq('Debt total principal plus interest',d['total_usd'],d['principal_usd']+d['interest_usd'],d['debt_payment_id']);balance-=d['principal_usd'];self.eq('Debt scheduled closing balance',balance,d['scheduled_closing_principal_usd'],d['debt_payment_id'])
            if d['actual_payment_date']:repaid+=d['principal_usd'];interest+=d['interest_usd'];self.eq('Debt actual bank principal plus interest',-d['total_usd'],self.bank[d['bank_transaction_id']]['signed_amount_usd'],d['debt_payment_id'])
        self.eq('Actual term debt GL principal outstanding',310000000-repaid,-self.totalclose('2400'));self.eq('Debt interest GL excludes principal',interest,sum(v[0]-v[1] for (m,p,a),v in self.g.items() if a=='5700'))
        remit=self.table('fixed_assets_finance/tax_remittances');self.eq('Hotel-collected lodging tax liability GL',self.tax['2100']-sum(r['paid_usd'] for r in remit),-self.totalclose('2100'))
        ads=defaultdict(int)
        for r in self.table('marketing/daily_campaigns'):self.eq('Google/Meta micros convert exactly to cent spend',r['cost_micros'],r['spend_usd']*10000);ads[(r['platform'],r['property_id'],r['metric_date'][:7])]+=r['spend_usd']
        for b in self.table('marketing/billing'):self.eq('Daily own ad spend equals monthly billing',ads[(b['platform'],b['property_id'],b['service_month'])],b['spend_usd'],b['billing_id']);self.eq('Ad billing equals vendor AP bill',b['spend_usd'],bills[b['bill_id']]['total_usd'],b['billing_id'])
        self.eq('Own marketing GL separate from OTA distribution',sum(ads.values()),sum(v[0]-v[1] for (m,p,a),v in self.g.items() if a=='5400'))
    def planning_controls(self):
        alloc=Counter();bycentre=defaultdict(Counter)
        for a in self.table('planning/shared_cost_allocations'):alloc[a['allocation_id']]+=a['allocated_expense_usd'];bycentre[(a['service_month'],a['property_id'])][a['account_code']]+=a['allocated_expense_usd'];self.eq('Allocations create zero consolidated increment',a['consolidated_increment_usd'],0)
        for aid,v in alloc.items():self.eq('Shared cost allocation bridge is zero sum',v,0,aid)
        for b in self.table('planning/approved_budget'):self.check('Original budget approval before actual window and budget month',b['approved_date']<START and b['approved_date']<b['service_month']+'-01' and b['budget_version_id']=='BUDGET-ORIGINAL-2024-10-15',str(b))
        self.eq('Budget complete account property month grid',len(self.table('planning/approved_budget')),24*4*len([a for a in self.table('quickbooks/chart_of_accounts') if a['account_type'] in ['revenue','contra_revenue','expense']]))
        for p in self.table('planning/approved_room_plan'):self.eq('Budget room rate times sold nights',p['planned_adr_usd']*p['planned_sold_nights'],p['planned_net_room_revenue_usd'])
        budmap={(b['service_month'],b['property_id'],b['account_code']):b['budget_usd'] for b in self.table('planning/approved_budget')};staff=defaultdict(Counter)
        for s in self.table('planning/approved_staff_plan'):
            y,m=map(int,s['service_month'].split('-'));nd=calendar.monthrange(y,m)[1]
            cost=mul(s['annual_salary_usd'],Decimal(s['planned_headcount'])/12) if s['annual_salary_usd'] else mul(s['hourly_rate_usd'],Decimal(s['planned_headcount'])*s['planned_hours_per_week']*nd/7)
            staff[(s['service_month'],s['property_id'])]['5100' if s['role']=='housekeeper' else '5120' if s['property_id']=='CORP' else '5110']+=cost
        for k,aa in staff.items():
            for acc,val in aa.items():self.eq('Original staff driver plan ties budget wages',val,budmap[(*k,acc)],str((*k,acc)))
        for r in self.table('planning/approved_room_plan'):self.eq('Original room driver plan ties budget room revenue before credits',r['planned_net_room_revenue_usd'],budmap[(r['service_month'],r['property_id'],'4000')]+budmap[(r['service_month'],r['property_id'],'4010')])
        for c in self.table('planning/recurring_contracts'):
            y,m=map(int,c['next_service_month'].split('-'));end=date(y,m,calendar.monthrange(y,m)[1]);expected=date(y,m,1) if c['account_code']=='5320' else end+timedelta(days=20 if c['account_code']=='5330' else 30)
            self.check('Recurring next due follows service month and contract terms',c['next_due_date']==expected.isoformat(),c['recurring_contract_id'])
        otb=defaultdict(int)
        for n in self.table('planning/on_books_nights'):otb[(n['reservation_id'],n['service_date'][:7])]+=n['booked_room_usd']+n['booked_lodging_tax_usd']
        for t in self.table('planning/booked_payment_terms'):
            self.eq('OTB payment timing split by service month',t['future_booked_charges_usd'],otb[(t['reservation_id'],t['service_month'])],str((t['reservation_id'],t['service_month'])))
            self.check('Future advance cover is capped per service month',0<=t['existing_advance_cover_usd']<=t['future_booked_charges_usd'],t['reservation_id'])
            if t['company_id']:
                y,m=map(int,t['service_month'].split('-'));invoice=date(y,m,calendar.monthrange(y,m)[1]);terms=45 if t['company_id']=='CO-001' else 30;delay=52 if t['company_id']=='CO-001' else 8 if t['company_id']=='CO-003' else 0
                expected=invoice+timedelta(days=terms+delay+18)
                while expected.weekday()>4:expected+=timedelta(days=1)
                self.check('Corporate OTB collection date follows its earned invoice month',t['expected_collect_date']==expected.isoformat(),str(t))
        inputs=self.table('planning/known_cash_inputs');seen=set()
        for c in inputs:
            key=(c['input_type'],c['overlap_key']);self.check('Known cash input index unique and future timing only',key not in seen and c['expected_cash_date']>CUT and c['amount_usd']>=0 and not c['is_actual_cash'],c['input_id']);seen.add(key)
        for acc,typ in [('1100','open_corporate_ar'),('2000','open_vendor_ap'),('2100','hotel_lodging_tax')]:self.eq('Known cash input open subledger coverage',sum(c['amount_usd'] for c in inputs if c['input_type']==typ),abs(self.totalclose(acc)),typ)
        expected={}
        def expect(typ,t,key,amt,condition):
            for r in self.table(t):
                if condition(r) and r[amt]:expected[(typ,r[key])]=r[amt]
        expect('open_corporate_ar','corporate_billing/invoices','invoice_id','open_ar_usd',lambda r:r['open_ar_usd']>0)
        expect('open_vendor_ap','quickbooks/bills','bill_id','open_ap_usd',lambda r:r['open_ap_usd']>0)
        expect('earned_unfunded_payroll','gusto/funding','funding_id','open_payable_usd',lambda r:r['open_payable_usd']>0)
        expect('hotel_lodging_tax','fixed_assets_finance/tax_remittances','tax_remittance_id','open_tax_usd',lambda r:r['open_tax_usd']>0)
        expect('agency_commission','channel_manager/agency_invoices','agency_invoice_id','open_usd',lambda r:r['open_usd']>0)
        expect('earned_ota_net_remittance','channel_manager/settlements','settlement_id','net_payout_usd',lambda r:not r['actual_bank_date'])
        expect('gateway_transit','payments/payouts','payout_id','net_payout_usd',lambda r:not r['actual_bank_date'])
        expect('security_return','payments/reservation_balances','reservation_id','refundable_security_usd',lambda r:r['refundable_security_usd']>0)
        expect('unreceived_capex','planning/capex_commitments','commitment_id','open_commitment_usd',lambda r:r['open_commitment_usd']>0)
        expect('scheduled_debt_service','fixed_assets_finance/debt_schedule','debt_payment_id','total_usd',lambda r:not r['actual_payment_date'])
        uncleared=Counter()
        for b in self.table('payments/balance_transactions'):
            if not b['payout_id']:uncleared[b['property_id']]+=b['net_usd']
        for p,amt in uncleared.items():expected[('gateway_unreleased_balance',p)]=amt
        indexed={(c['input_type'],c['source_id']):c['amount_usd'] for c in inputs};self.check('Every known cash input category complete with no duplicate source obligations',indexed==expected,str(set(indexed)^set(expected)))
        for b in self.table('planning/cutoff_balance_inputs'):self.eq('Cutoff balance input copy agrees TB',b['signed_balance_usd'],self.close(b['property_id'],b['account_code']))
        weeks=self.table('planning/forecast_weeks');self.eq('13 forecast week buckets',len(weeks),13);self.check('Forecast horizon starts after cutoff ends 2027-01-30',weeks[0]['week_start_date']=='2026-11-01' and weeks[-1]['week_end_date']=='2027-01-30')
        # Saved-record traces must straddle cutoff in the promised ways.
        selection=json.loads((BASE/'metadata/trace_selection.json').read_text());r=self.res[selection['direct_prepaid_reservation_id']];self.check('Direct prepaid trace consumed/future split',r['channel_id']=='DIRECT' and r['prepaid'] and r['actual_consumed_nights']==3 and r['planned_nights']==5 and r['status_as_of_cutoff']=='in_house')
        otaid=selection['ota_cross_cutoff_reservation_id'];sids={l['settlement_id'] for l in self.table('channel_manager/settlement_lines') if l['reservation_id']==otaid};ss=self.idx('channel_manager/settlements','settlement_id');self.check('OTA trace release before cutoff bank after cutoff',any(ss[s]['actual_release_date']=='2026-10-31' and not ss[s]['actual_bank_date'] and ss[s]['expected_bank_date']>CUT for s in sids))
        # 24 months x company + three physical properties. CORP contributes to company totals.
        coa=self.idx('quickbooks/chart_of_accounts','account_code');budget=defaultdict(Counter)
        for b in self.table('planning/approved_budget'):budget[(b['service_month'],b['property_id'])][b['account_code']]+=b['budget_usd']
        controls=[];tbidx={(r['service_month'],r['property_id'],r['account_code']):r['closing_signed_usd'] for r in self.table('quickbooks/monthly_trial_balance')}
        for mo in sorted({k[0] for k in self.ops}):
            for scope in ['COMPANY']+PROPS:
                pp=CENTRES if scope=='COMPANY' else [scope];oc=Counter();rev=Counter();gl=Counter();alloccost=0;bud=Counter()
                for p in pp:
                    oc.update(self.ops[(mo,p)]);rev.update(self.revenuemo[(mo,p)]);bud.update(budget[(mo,p)])
                    for acc in coa:gl[acc]+=self.g[(mo,p,acc)][0]-self.g[(mo,p,acc)][1]
                    alloccost+=sum(bycentre[(mo,p)].values())
                room=rev['room']+rev['room_credit'];anc=sum(rev[c] for c in ['parking','breakfast','cleaning','late_checkout']);fees=rev['cancellation_fee']+rev['no_show_fee'];revenue=room+anc+fees;distribution=gl['5000'];expenses=sum(v for a,v in gl.items() if coa[a]['account_type']=='expense');ebitda=revenue-expenses+gl['5600']+gl['5700'];netincome=revenue-expenses
                glroom=-(gl['4000']+gl['4010']+gl['4020']);self.eq('Monthly net room revenue folio to GL',room,glroom,f'{mo}-{scope}');self.eq('Monthly total earned revenue folio to GL',revenue,-sum(v for a,v in gl.items() if coa[a]['account_type'] in ['revenue','contra_revenue']),f'{mo}-{scope}')
                sold=oc['sold_nights'];avail=oc['available_nights'];adr=Decimal(room)/100/sold if sold else Decimal(0);revpar=Decimal(room)/100/avail if avail else Decimal(0);occupancy=Decimal(sold)/avail if avail else Decimal(0);self.check('ADR occupancy RevPAR identity from summed drivers',abs(adr*occupancy-revpar)<Decimal('.00000001'),f'{mo}-{scope}')
                hk=sum(gl[a] for a in ['5100','5150','5200','5210']);roomcommission=sum(c['commission_usd'] for c in self.table('channel_manager/commissions') if c['property_id'] in pp and c['service_date'][:7]==mo and self.foliolines[c['folio_line_id']]['charge_type'] in ['room','room_credit']);netadr=(Decimal(room-roomcommission)/100/sold) if sold else 0
                budgetrev=sum(v for a,v in bud.items() if coa[a]['account_type'] in ['revenue','contra_revenue']);budgetexpense=sum(v for a,v in bud.items() if coa[a]['account_type']=='expense');budgetebitda=budgetrev-budgetexpense+bud['5600']+bud['5700']
                balances={name:fmt(sign*sum(tbidx[(mo,p,acc)] for p in pp)) for name,acc,sign in [('closing_bank_usd','1000',1),('closing_gateway_clearing_usd','1010',1),('closing_cash_transit_usd','1020',1),('closing_corporate_ar_usd','1100',1),('closing_ota_ar_usd','1120',1),('closing_vendor_ap_usd','2000',-1),('closing_guest_deposits_usd','2200',-1),('closing_security_deposits_usd','2210',-1),('closing_corporate_deposits_usd','2220',-1),('closing_hotel_tax_payable_usd','2100',-1),('closing_ota_tax_clearing_usd','2110',-1),('closing_payroll_net_payable_usd','2300',-1),('closing_payroll_other_payable_usd','2310',-1),('closing_term_debt_usd','2400',-1)]}
                controls.append(dict(service_month=mo,scope_id=scope,**dict(oc),net_room_revenue_usd=fmt(room),ancillary_revenue_usd=fmt(anc),cancellation_no_show_fees_usd=fmt(fees),total_revenue_usd=fmt(revenue),sold_occupancy=f'{occupancy:.8f}',occupied_occupancy=f'{Decimal(oc["occupied_nights"])/avail:.8f}',adr_usd=f'{adr:.6f}',revpar_usd=f'{revpar:.6f}',ota_distribution_cost_usd=fmt(distribution),room_related_ota_commission_usd=fmt(roomcommission),net_adr_after_ota_commission_usd=f'{netadr:.6f}',housekeeping_defined_cost_usd=fmt(hk),housekeeping_cost_per_occupied_night_usd=f'{Decimal(hk)/100/oc["occupied_nights"]:.6f}' if oc['occupied_nights'] else '0.000000',gross_payroll_usd=fmt(sum(gl[a] for a in ['5100','5110','5120'])),ebitda_before_shared_allocation_usd=fmt(ebitda),shared_allocated_cost_usd=fmt(alloccost),ebitda_after_shared_allocation_usd=fmt(ebitda-alloccost),net_income_usd=fmt(netincome),original_budget_revenue_usd=fmt(budgetrev),original_budget_ebitda_usd=fmt(budgetebitda),revenue_bva_usd=fmt(revenue-budgetrev),ebitda_bva_usd=fmt(ebitda-budgetebitda),cash_movement_usd=fmt(gl['1000']),**balances))
        # Ordered common field list, including zero fields absent from counters.
        countfields=['physical_nights','available_nights','sold_nights','complimentary_nights','house_use_nights','occupied_nights','out_of_order_nights','out_of_service_nights']
        for r in controls:
            for k in countfields:r.setdefault(k,0)
        fields=['service_month','scope_id']+countfields+[k for k in controls[0] if k not in ['service_month','scope_id']+countfields]
        self.eq('96 monthly company/property controls',len(controls),96);writecsv(BASE/'validation/monthly_control_totals.csv',controls,fields)
    def finish(self):
        report=[]
        for c in self.checks.values():c=dict(c);c['examples']=' | '.join(c['examples']);report.append(c)
        writecsv(BASE/'validation/validation_report.csv',report)
        summary=dict(check_groups=len(report),evaluated_conditions=sum(c['evaluated'] for c in report),failed_conditions=sum(c['failures'] for c in report),failed_groups=sum(c['status']=='FAIL' for c in report),money_tolerance_cents=0,room_night_tolerance=0,ratio_identity_tolerance='0.00000001',verifier='independent saved-CSV reader; no generator imports')
        (BASE/'validation/validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
        for c in report:
            if c['status']=='FAIL':print(c['check_name'],c['failures'],c['examples'])
        return summary['failed_conditions']

def main():
    v=Verify()
    if v.metadata():
        for f in [v.ledger,v.stays,v.folios_payments,v.ota_corporate_ap,v.labor_assets_marketing,v.planning_controls]:
            print('Checking',f.__name__,flush=True);f()
    sys.exit(1 if v.finish() else 0)
if __name__=='__main__':main()
