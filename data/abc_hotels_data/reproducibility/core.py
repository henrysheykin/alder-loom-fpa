"""Deterministic hospitality economic spine. All internal USD values are integer cents."""
from __future__ import annotations
import csv, json, hashlib, calendar, random, os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('JQ_OUTPUT_DIR',str(ROOT.parent/'juniper_quay_rebuilt' if (ROOT/'metadata/table_schemas.json').exists() else ROOT/'outputs'/'juniper_quay_data')))
START=date(2024,11,1); CUT=date(2026,10,31); FUT=date(2027,1,30)
PROPS=['RAL','WIL','DUR']; CENTRES=PROPS+['CORP']
COUNTS={'RAL':60,'WIL':52,'DUR':44}
def iso(d): return d.isoformat() if isinstance(d,date) else str(d)
def cents(x): return int((Decimal(str(x))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def mul(v, rate): return int((Decimal(v)*Decimal(str(rate))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def usd(v): return f'{v/100:.2f}'
def split_cents(total, weights):
    sign=1 if total>=0 else -1; total=abs(total); den=sum(weights)
    parts=[total*w//den for w in weights]
    remainders=sorted(range(len(weights)),key=lambda i:(-(total*weights[i]%den),i))
    for i in remainders[:total-sum(parts)]: parts[i]+=1
    return [p*sign for p in parts]
def nights(a,b,cut=CUT):
    while a<b and a<=cut:
        yield a; a+=timedelta(days=1)
def days(a=START,b=CUT):
    while a<=b: yield a; a+=timedelta(days=1)
def month_end(d): return date(d.year,d.month,calendar.monthrange(d.year,d.month)[1])
def next_month(d): return (d.replace(day=28)+timedelta(days=4)).replace(day=1)
def months(a=START,b=CUT):
    d=a.replace(day=1)
    while d<=b: yield d; d=next_month(d)
def business(d):
    while d.weekday()>4: d+=timedelta(days=1)
    return d
def plus_business(d,n):
    for _ in range(n):
        d+=timedelta(days=1); d=business(d)
    return d
def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='raise');w.writeheader();w.writerows(rows)

PARTITIONS={
 'availability/room_dates':'service_date','pms/actual_stay_nights':'service_date',
 'night_audit/folio_lines':'service_date','quickbooks/general_ledger':'accounting_date',
 'operations/housekeeping_tasks':'service_date','gusto/time_entries':'work_date',
 'planning/on_books_nights':'service_date'
}

class Dataset:
    def __init__(self):
        self.tables=defaultdict(list);self.schemas={};self.seq=defaultdict(int)
        self.rng=random.Random(20261119);self.bank_events=[];self.meta={}
        self.res=[];self.room_dates={};self.charges=defaultdict(list)
    def ident(self,prefix):
        self.seq[prefix]+=1; return f'{prefix}-{self.seq[prefix]:08d}'
    def add(self,table,key,grain,**row):
        if table not in self.schemas:
            self.schemas[table]={'grain':grain,'primary_key':key.split(','),'fields':list(row),'notes':''}
        if set(row)!=set(self.schemas[table]['fields']):
            raise ValueError((table,'inconsistent columns',set(row)^set(self.schemas[table]['fields'])))
        self.tables[table].append(row);return row
    def post(self,day,system,table,src,entries,memo=''):
        if sum(v for p,a,v in entries): raise ValueError(f'unbalanced {src}: {entries}')
        d=iso(day)
        if not START.isoformat()<=d<=CUT.isoformat(): raise ValueError(f'GL cutoff {d}')
        jid=self.ident('JRN')
        for prop,acc,val in entries:
            if val==0: continue
            self.add('quickbooks/general_ledger','line_id','One journal/account/property line; debit and credit unsigned USD',
                line_id=self.ident('GLL'),journal_id=jid,accounting_date=d,property_id=prop,account_code=acc,
                debit_usd=max(val,0),credit_usd=max(-val,0),source_system=system,source_table=table,source_id=src,memo=memo)
        return jid
    def cash(self,day,prop,amount,kind,source_id,offset,system='treasury',table='cash_events',memo=''):
        d=iso(day)
        if d>CUT.isoformat(): return ''
        if d<START.isoformat(): raise ValueError('bank before actual window')
        bid=self.ident('BNK')
        self.bank_events.append(dict(bank_transaction_id=bid,posted_date=d,property_id=prop,
            signed_amount_usd=amount,transaction_type=kind,source_system=system,source_id=source_id,memo=memo))
        self.post(d,system,table,source_id,[(prop,'1000',amount),(prop,offset,-amount)],memo)
        return bid
    def export(self):
        manifests=[]
        for table,s in self.schemas.items():
            rows=self.tables[table];groups=defaultdict(list);part=PARTITIONS.get(table)
            if part:
                for r in rows: groups[str(r[part])[:7]].append(r)
                if not groups: groups['empty']=[]
            else: groups['']=rows
            files=[]
            for group,rr in sorted(groups.items()):
                rel=f'sources/{table}/{group}.csv' if part else f'sources/{table}.csv'
                path=OUT/rel
                formatted=[]
                for r in rr:
                    formatted.append({k:usd(v) if k.endswith('_usd') and isinstance(v,int) else iso(v) if isinstance(v,date) else str(v).lower() if isinstance(v,bool) else v for k,v in r.items()})
                write_csv(path,s['fields'],formatted)
                files.append(rel)
                manifests.append(dict(relative_path=rel,logical_table=table,row_count=len(rr),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            s['physical_files']=files;s['row_count']=len(rows)
        self.meta['manifest']=manifests
        write_csv(OUT/'metadata/file_manifest.csv',list(manifests[0]),manifests)
        (OUT/'metadata').mkdir(exist_ok=True)
        (OUT/'metadata/table_schemas.json').write_text(json.dumps(self.schemas,ensure_ascii=False,indent=2),encoding='utf-8')
        return manifests

ACCOUNTS=[
 ('1000','Operating bank','asset','cash'),('1010','Gateway clearing','asset','processor'),('1020','Cash in transit','asset','transit'),
 ('1100','Corporate invoiced AR','asset','corporate_ar'),('1110','Guest folio AR','asset','guest_ar'),('1120','OTA merchant AR','asset','ota_ar'),('1130','Unbilled corporate earned AR','asset','unbilled_ar'),
 ('1500','Buildings and improvements','asset','assets'),('1510','Furniture fitout equipment','asset','assets'),('1590','Accumulated depreciation','contra_asset','assets'),
 ('2000','Vendor accounts payable','liability','ap'),('2010','OTA commission payable','liability','ota'),('2100','Hotel lodging tax payable','liability','tax'),('2110','OTA tax clearing payable','liability','ota_tax'),
 ('2200','Guest advance lodging deposits','liability','deposits'),('2210','Refundable security deposits','liability','security'),('2220','Corporate advance deposits','liability','corporate_deposits'),
 ('2300','Net wages payable','liability','payroll'),('2310','Payroll taxes and deductions payable','liability','payroll'),('2400','Term debt principal','liability','debt'),
 ('3000','Opening members equity','equity','equity'),('3100','Member distributions','equity','equity'),
 ('4000','Gross consumed room revenue','revenue','rooms'),('4010','Room discounts','contra_revenue','rooms'),('4020','Room service credits','contra_revenue','rooms'),
 ('4100','Parking revenue','revenue','ancillary'),('4110','Breakfast revenue','revenue','ancillary'),('4120','Cleaning and late checkout revenue','revenue','ancillary'),('4200','Cancellation fees','revenue','fees'),('4210','No show fees','revenue','fees'),
 ('5000','OTA distribution commissions','expense','distribution'),('5010','Payment processing fees','expense','processing'),('5100','Housekeeping employee gross pay','expense','housekeeping'),('5110','Other property gross pay','expense','labor'),('5120','Corporate gross pay','expense','corporate'),
 ('5130','Employer payroll taxes','expense','labor'),('5140','Employee benefits','expense','labor'),('5150','Agency housekeeping labor','expense','housekeeping'),
 ('5200','Laundry and linen service','expense','housekeeping'),('5210','Cleaning and guest consumables','expense','housekeeping'),('5220','Breakfast food cost','expense','ancillary'),
 ('5300','Routine maintenance','expense','maintenance'),('5310','Utilities','expense','utilities'),('5320','Property rent','expense','rent'),('5330','Insurance and owned property charges','expense','property'),('5340','Contracted services','expense','services'),
 ('5400','Own advertising','expense','marketing'),('5500','Corporate software and advisory','expense','corporate'),('5600','Depreciation','expense','depreciation'),('5700','Debt interest','expense','interest')]

def build_masters(ds):
    for c,n,t,g in ACCOUNTS:
        ds.add('quickbooks/chart_of_accounts','account_code','One GL account',account_code=c,account_name=n,account_type=t,report_group=g,normal_sign='debit' if t in ['asset','expense','contra_revenue'] or c=='3100' else 'credit',currency='USD')
    ds.add('pms/legal_entities','entity_id','One principal operating legal entity',entity_id='JQH-LLC',legal_name='Juniper Quay Hospitality LLC',brand_name='Juniper Quay',country_code='US',state_code='NC',tax_model='synthetic pass-through LLC',principal_operator=True,contact_email='finance@juniperquay.example.com')
    info={'RAL':('Juniper Quay Raleigh Station','Raleigh','owned','select_service_hotel',15400),
          'WIL':('Juniper Quay Cape Landing','Wilmington','leased','leisure_select_service_hotel',16900),
          'DUR':('Juniper Quay Durham Residences','Durham','leased','aparthotel',11300)}
    ds.rooms={};ds.types={};ds.properties={}
    for p,(name,city,tenure,cat,base) in info.items():
        ds.properties[p]=ds.add('pms/properties','property_id','One physical property; CORP is not a property',property_id=p,entity_id='JQH-LLC',property_name=name,city=city,state_code='NC',country_code='US',time_zone='America/New_York',property_category=cat,tenure=tenure,physical_keys=COUNTS[p],opened_date='2021-04-01',active_from='2024-11-01',active_through='2027-12-31',currency='USD')
        mix=[('KNG',32,1.0,2),('DQQ',20,1.1,4),('STE',8,1.32,4)] if p=='RAL' else [('KNG',24,1,2),('DQQ',20,1.12,4),('STE',8,1.34,4)] if p=='WIL' else [('STD',28,1,2),('ONE',12,1.25,3),('TWO',4,1.60,5)]
        i=0
        for typ,num,mult,cap in mix:
            tid=f'{p}-{typ}';ds.types[tid]=(base,mult)
            ds.add('pms/room_types','room_type_id','One property-specific room category',room_type_id=tid,property_id=p,type_name={'KNG':'Standard King','DQQ':'Double Queen','STE':'King Suite','STD':'Studio kitchenette','ONE':'One-bedroom apartment','TWO':'Two-bedroom apartment'}[typ],keys=num,max_guests=cap,has_kitchen=p=='DUR',rate_multiplier=mult)
            for j in range(num):
                i+=1;rid=f'{p}-{100+i:03d}';r=dict(room_id=rid,property_id=p,room_type_id=tid,room_number=str(100+i),floor_number=1+(i-1)//20,active_from='2021-04-01',active_through='',accessible=(i%17==0))
                ds.rooms[rid]=ds.add('pms/rooms','room_id','One room/apartment physical key',**r)
        for code,factor,daysmin in [('BAR',1.0,1),('ADVANCE',.93,1),('CORP',.86,7 if p=='DUR' else 1),('EXTENDED',.77,14),('COMP',0,1)]:
            for version,eff,end,inc in [('V1','2024-10-01','2026-02-28',1),('V2','2026-03-01','2027-12-31',1.08)]:
                ds.add('pms/rate_plans','rate_plan_version_id','One effective-dated property rate-plan version',rate_plan_version_id=f'{p}-{code}-{version}',property_id=p,rate_plan_code=code,effective_from=eff,effective_through=end,minimum_nights=daysmin,base_rate_usd=mul(base,factor*inc),base_multiplier=factor,refundable=code!='ADVANCE',tax_policy_id=f'TAX-{p}',pricing_note='nightly dynamic category and weekday factors; quoted amounts are not earned revenue')
        ds.add('night_audit/tax_policies','tax_policy_id','One synthetic hotel tax parameter; not a statutory rate',tax_policy_id=f'TAX-{p}',property_id=p,effective_from='2024-11-01',effective_through='2027-12-31',lodging_tax_rate=.1125 if p!='WIL' else .125,ancillary_tax_rate=0.0,long_stay_exemption_applied=False,merchant_ota_remits_lodging_tax=True,assumption_note='case assumption only; applies also to long stays; cancellation/no-show fees non-taxable in model')
    ds.add('quickbooks/cost_centres','cost_centre_id','One property or shared corporate accounting centre',cost_centre_id='CORP',property_id='',centre_name='Shared corporate',capacity_keys=0)
    for p in PROPS: ds.add('quickbooks/cost_centres','cost_centre_id','One property or shared corporate accounting centre',cost_centre_id=p,property_id=p,centre_name=ds.properties[p]['property_name'],capacity_keys=COUNTS[p])
    for channel,model,comm in [('DIRECT','hotel_collect',0),('BOOKING','agency',.15),('EXPEDIA','merchant',.18),('CORPORATE','invoice',0),('INTERNAL','internal',0)]:
        ds.add('channel_manager/channels','channel_id','One synthetic distribution contract',channel_id=channel,channel_name={'DIRECT':'Own website and front desk','BOOKING':'Booking.com-style agency','EXPEDIA':'Expedia-style merchant','CORPORATE':'Corporate sales','INTERNAL':'Complimentary and house use'}[channel],collection_model=model,commission_rate=comm,effective_from='2024-10-01',effective_through='2027-12-31',fee_assumption='case parameter; no claim of current vendor pricing')
        if channel in ['BOOKING','EXPEDIA']:
            for p in PROPS:
                ds.add('channel_manager/listings','listing_id','One OTA/property listing mapping',listing_id=f'{channel}-{p}',channel_id=channel,property_id=p,external_listing_id=f'SYN-{channel}-{p}',pms_property_id=p)
    for i,name in enumerate(['Piedmont Project Relocation LLC','Cedar Research Partners LLC','Bluewater Training Services LLC','Triangle Siteworks LLC','Harbor Clinical Mobility LLC','Oakline Conference Services LLC'],1):
        cid=f'CO-{i:03d}';ds.add('corporate_billing/companies','company_id','One synthetic corporate client',company_id=cid,company_name=name,billing_email=f'accounts{i}@example.com',country_code='US',credit_limit_usd=18000000 if i==1 else 6000000)
        for p in PROPS:
            ds.add('corporate_billing/contracts','contract_id','One effective corporate/property agreement',contract_id=f'CT-{cid}-{p}',company_id=cid,property_id=p,effective_from='2024-10-01',effective_through='2027-12-31',payment_terms_days=30 if i!=1 else 45,invoice_frequency='calendar_month',advance_percent=.20 if i in [1,3] else 0.0,minimum_nights=14 if p=='DUR' else 1,rate_discount=.23 if p=='DUR' else .14,security_deposit_usd=25000 if p=='DUR' else 0)
