"""Independent saved-file verifier. Python 3.11+ standard library only.

Does not import generator modules and never reads their state. CSV decimals are
converted to integer cents / millionths before loading an isolated SQLite DB.
Default operation compares persisted monthly controls; --write-controls creates
or deliberately refreshes them. Does not modify any file under sources/.
"""
import argparse
import calendar
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

START='2024-11-01';END='2026-10-31';OPENING='2024-10-31'


def scaled(value,scale):
    d=Decimal(value)*scale
    if not d.is_finite() or d!=d.to_integral_value():
        raise ValueError(f'Unsupported precision: {value}')
    return int(d)


def parse_money(value):return scaled(value,100)
def parse_qty(value):return scaled(value,1000000)


def rounded(n,d):
    if n is None or d is None or d<=0:return None
    return (1 if n>=0 else -1)*((abs(n)*2+d)//(d*2))


def money(value):
    value=int(value or 0)
    return ('-' if value<0 else '')+f'{abs(value)//100}.{abs(value)%100:02d}'


def qty(value):
    value=int(value or 0)
    return ('-' if value<0 else '')+f'{abs(value)//1000000}.{abs(value)%1000000:06d}'


def enable_mutation_rollback(db):
    db.commit()
    mode=db.execute('PRAGMA journal_mode=MEMORY').fetchone()[0]
    if mode.lower()!='memory':raise RuntimeError('Rollback journal required for mutation isolation')


class Verifier:
    def __init__(self,root,scratch):
        self.root=root.resolve();scratch.mkdir(parents=True,exist_ok=True)
        self.dbpath=scratch/'cedar_skillet_verification.sqlite'
        if self.dbpath.exists():self.dbpath.unlink()
        self.db=sqlite3.connect(self.dbpath)
        self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA synchronous=OFF');self.db.execute('PRAGMA temp_store=FILE');self.db.execute('PRAGMA cache_size=-180000')
        self.db.create_function('R',2,rounded,deterministic=True)
        self.db.create_function('MINS',2,lambda a,b:int((datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds()//60),deterministic=True)
        self.schemas=json.loads((root/'metadata'/'table_schemas.json').read_text(encoding='utf-8'))
        self.relationships=json.loads((root/'metadata'/'relationships.json').read_text(encoding='utf-8'))
        self.report=[];self.counts={};self.file_counts={};self.input_errors=[];self.rules=[]

    def record(self,name,evaluated,failures=0,maxdiff=0,examples='',unit='count'):
        self.report.append(dict(check_name=name,status='PASS' if not failures else 'FAIL',evaluated=evaluated,failures=failures,unit=unit,max_absolute_difference_cents=maxdiff if unit=='cents' else 0,max_absolute_difference_base_units=qty(maxdiff) if unit=='quantity' else '0.000000',examples=examples))
        if failures:print(f'FAIL {name}: {failures:,} / {evaluated:,}; {examples[:400]}',flush=True)

    def count(self,table):return self.counts[table]

    def check(self,name,sql,evaluated,unit='cents'):
        self.rules.append((name,sql))
        if isinstance(evaluated,str):evaluated=self.db.execute(evaluated).fetchone()[0]
        failures=0;maxdiff=0;examples=[]
        try:
            for row in self.db.execute(sql):
                failures+=1
                diff=row[-1]
                if isinstance(diff,(int,float)):maxdiff=max(maxdiff,abs(int(diff)))
                if len(examples)<4:examples.append(' | '.join(str(x) for x in row))
        except sqlite3.Error as e:
            raise RuntimeError(f'{name}: {e}\n{sql}') from e
        self.record(name,evaluated,failures,maxdiff,'; '.join(examples),unit)

    def run(self,sql):self.db.executescript(sql)

    def load(self):
        actual_files=set()
        for t,s in self.schemas.items():
            if not re.fullmatch('[a-z][a-z0-9_]*',t):raise ValueError(t)
            cols=s['fields'];types=s['types']
            integer={f for f in cols if types.get(f,'').startswith('decimal') or types.get(f)=='integer'}
            definition=','.join('"'+f+'" '+('INTEGER' if f in integer else 'TEXT') for f in cols)
            self.db.execute(f'CREATE TABLE "{t}" ({definition})')
            insert=f'INSERT INTO "{t}" VALUES('+','.join('?' for _ in cols)+')'
            n=0
            for rel in s['physical_files']:
                path=self.root/rel;actual_files.add(rel)
                if path.read_bytes()[:3]!=b'\xef\xbb\xbf':self.input_errors.append((rel,'Missing UTF-8 BOM'))
                with path.open(encoding='utf-8-sig',newline='') as h:
                    reader=csv.DictReader(h)
                    if reader.fieldnames!=cols:raise ValueError(f'CSV schema mismatch {rel}')
                    batch=[];fn=0
                    for row in reader:
                        parsed=[]
                        for f in cols:
                            v=row[f];ty=types.get(f,'text')
                            try:
                                if v=='':v=None
                                elif ty=='decimal(18,2)':v=parse_money(v)
                                elif ty.startswith('decimal'):v=parse_qty(v)
                                elif ty=='integer':v=int(v)
                                elif ty=='date':date.fromisoformat(v)
                                elif ty=='local_datetime':datetime.fromisoformat(v)
                            except (ValueError,ArithmeticError) as ex:
                                if len(self.input_errors)<30:self.input_errors.append((rel,f,str(ex)))
                                v=None
                            parsed.append(v)
                        batch.append(parsed);fn+=1;n+=1
                        if len(batch)>=5000:self.db.executemany(insert,batch);batch=[]
                    if batch:self.db.executemany(insert,batch)
                    self.file_counts[rel]=fn
            self.counts[t]=n
            pk=s['primary_key']
            self.db.execute(f'CREATE INDEX "ix_pk_{t}" ON "{t}" ('+','.join('"'+x+'"' for x in pk)+')')
            if 'journal_date' in cols:self.db.execute(f'CREATE INDEX "ix_date_{t}" ON "{t}"(journal_date,restaurant_id)' if 'restaurant_id' in cols else f'CREATE INDEX "ix_date_{t}" ON "{t}"(journal_date)')
            if t in ['checks','check_lines','inventory_movements','general_ledger']:print(f'Loaded {t}: {n:,}',flush=True)
        self.db.commit()
        present={p.relative_to(self.root).as_posix() for p in (self.root/'sources').rglob('*.csv')}
        self.record('Physical CSV coverage and no undeclared source files',len(present|actual_files),len(present^actual_files),examples=str(sorted(present^actual_files)[:5]))
        self.record('CSV BOM, numeric precision and ISO format',sum(self.counts.values()),len(self.input_errors),examples=str(self.input_errors[:5]))
        for t,s in self.schemas.items():
            pk=s['primary_key'];group=','.join(pk);null=' OR '.join(f'{f} IS NULL' for f in pk)
            self.check('Primary key populated and unique: '+t,f'SELECT {group}, count(*) FROM {t} GROUP BY {group} HAVING count(*)<>1 OR {null}',self.count(t),'count')
            self.record('Declared row count: '+t,self.count(t),int(self.count(t)!=s['row_count']))
        for f in self.relationships:
            t,field,p,pf=f['child_table'],f['child_field'],f['parent_table'],f['parent_field']
            cond=f'c.{field} IS NOT NULL AND p.{pf} IS NULL'
            if not f['optional']:cond=f'(c.{field} IS NULL OR p.{pf} IS NULL)'
            self.check(f'Foreign key {t}.{field} -> {p}.{pf}',f'SELECT c.rowid,1 FROM {t} c LEFT JOIN {p} p ON c.{field}=p.{pf} WHERE {cond}',self.count(t),'count')
        # Index frequently queried child keys after all rows have been loaded.
        for t,fields in [('check_lines','check_id'),('check_modifiers','check_line_id'),('payments','check_id'),('refunds','check_id'),('general_ledger','source_table,source_id'),('general_ledger','account_id,restaurant_id,journal_date'),('vendor_bill_lines','bill_id'),('bill_payment_applications','bill_id'),('inventory_movements','restaurant_id,ingredient_id,movement_sequence'),('timesheets','payroll_run_id,employee_id'),('tip_allocations','payroll_run_id,employee_id')]:
            ix='ix_child_'+t+'_'+fields.replace(',','_')
            self.db.execute(f'CREATE INDEX {ix} ON {t}({fields})')
        self.db.commit()

    def cutoff(self):
        actual={
        'checks':['business_date','opened_at','closed_at'],'check_lines':['business_date'],'check_modifiers':['business_date'],'payments':['business_date'],'refunds':['refund_date'],'discounts':['business_date'],'comps':['business_date'],'voids':['business_date'],'day_closings':['business_date'],
        'processor_transactions':['transaction_date'],'processor_payouts':['created_date','initiated_date','bank_arrival_date'],'doordash_orders':['order_date'],'ubereats_orders':['order_date'],'doordash_transactions':['transaction_date'],'ubereats_transactions':['transaction_date'],'doordash_settlements':['statement_date','initiated_date','bank_arrival_date'],'ubereats_settlements':['statement_date','initiated_date','bank_arrival_date'],
        'cash_drawer_closings':['business_date'],'cash_deposits':['dispatch_date','bank_arrival_date'],'petty_cash_receipts':['transaction_date'],'bank_transactions':['transaction_date'],'journals':['journal_date'],'general_ledger':['journal_date'],
        'scheduled_shifts':['business_date'],'timesheets':['business_date','clock_in_at','clock_out_at'],'tip_allocations':['business_date','cash_tip_paid_date'],'payroll_runs':['period_start','period_end','approval_date','funding_date','actual_pay_date'],'payroll_funding':['actual_funding_date'],
        'purchase_orders':['order_date'],'delivery_schedule':['actual_delivery_date'],'receipts':['receipt_date'],'supplier_invoices':['invoice_date'],'supplier_credit_notes':['credit_date'],'inventory_movements':['movement_date'],'theoretical_usage':['business_date'],'waste_events':['business_date'],'staff_meals':['business_date'],'inventory_transfers':['transfer_date'],'physical_stock_counts':['count_date'],'inventory_daily_balances':['business_date'],
        'vendor_bills':['bill_date'],'vendor_credits':['credit_date'],'vendor_payments':['payment_date'],'bill_credit_applications':['application_date'],'bill_payment_applications':['application_date'],'bill_payment_schedule':['actual_payment_date'],'debt_schedule':['actual_payment_date'],'sales_tax_obligations':['actual_payment_date'],'owner_distributions':['distribution_date'],
        'meta_ads_daily':['activity_date'],'google_ads_daily':['activity_date'],'meta_ads_billing':['invoice_date'],'google_ads_billing':['invoice_date']}
        for t,fields in actual.items():
            cond=' OR '.join(f"({f} IS NOT NULL AND (substr({f},1,10)<'{START}' OR substr({f},1,10)>'{END}'))" for f in fields)
            self.check('Actual-date window: '+t,f'SELECT rowid,1 FROM {t} WHERE {cond}',self.count(t),'count')
        self.check('Budget approved before start and exactly within 24 months',f"SELECT budget_line_id,1 FROM approved_budget WHERE approved_date>='{START}' OR service_month<'{START}' OR service_month>'2026-10-01'",self.count('approved_budget'),'count')
        self.check('Exactly 730 daily closings per physical restaurant',"SELECT restaurant_id,count(*)-730 FROM day_closings GROUP BY restaurant_id HAVING count(*)<>730 OR min(business_date)<>'2024-11-01' OR max(business_date)<>'2026-10-31'",3,'count')
        self.check('Exactly 24 monthly statements',"SELECT 'BANK',count(*)-24 FROM bank_monthly_statements HAVING count(*)<>24",24,'count')

    def sales(self):
        n=self.count
        self.run('''
        CREATE TABLE line_totals AS SELECT check_id,sum(menu_gross_usd+modifier_gross_usd) ordered,sum(gross_sales_usd) gross,sum(discount_usd) discount,sum(comp_usd) comp,sum(net_sales_usd) net,sum(sales_tax_usd) tax FROM check_lines GROUP BY check_id;
        CREATE INDEX ix_line_totals ON line_totals(check_id);
        CREATE TABLE mod_totals AS SELECT check_line_id,sum(gross_usd) gross FROM check_modifiers GROUP BY check_line_id;
        CREATE INDEX ix_mod_totals ON mod_totals(check_line_id);
        CREATE TABLE tender_totals AS SELECT check_id,sum(amount_usd) amount,sum(CASE WHEN tender_type='CARD' THEN tip_usd ELSE 0 END) cardtip,sum(CASE WHEN tender_type='CASH' THEN tip_usd ELSE 0 END) cashtip FROM payments GROUP BY check_id;
        CREATE INDEX ix_tender_totals ON tender_totals(check_id);
        ''')
        self.check('POS menu quantity times unit price','SELECT check_line_id,menu_gross_usd-quantity*unit_price_usd FROM check_lines WHERE menu_gross_usd<>quantity*unit_price_usd',n('check_lines'))
        self.check('Modifier quantity times unit price','SELECT check_modifier_id,gross_usd-quantity*unit_price_usd FROM check_modifiers WHERE gross_usd<>quantity*unit_price_usd',n('check_modifiers'))
        self.check('Modifiers roll once into line gross','SELECT l.check_line_id,l.modifier_gross_usd-coalesce(m.gross,0) FROM check_lines l LEFT JOIN mod_totals m USING(check_line_id) WHERE l.modifier_gross_usd<>coalesce(m.gross,0)',n('check_lines'))
        self.check('POS served/void gross and net arithmetic',"SELECT check_line_id,net_sales_usd-(gross_sales_usd-discount_usd-comp_usd) FROM check_lines WHERE net_sales_usd<>gross_sales_usd-discount_usd-comp_usd OR gross_sales_usd<>CASE WHEN line_status='VOID' THEN 0 ELSE menu_gross_usd+modifier_gross_usd END OR discount_usd+comp_usd>gross_sales_usd",n('check_lines'))
        self.check('POS tax rounds per line at model rate','SELECT check_line_id,sales_tax_usd-R(net_sales_usd*750,10000) FROM check_lines WHERE sales_tax_usd<>R(net_sales_usd*750,10000)',n('check_lines'))
        self.check('POS menu price interval and channel',"SELECT l.check_line_id,l.unit_price_usd-p.unit_price_usd FROM check_lines l JOIN checks h USING(check_id) JOIN menu_price_versions p USING(price_version_id) WHERE l.unit_price_usd<>p.unit_price_usd OR l.menu_item_id<>p.menu_item_id OR l.business_date<p.effective_from OR l.business_date>coalesce(p.effective_to,'9999-12-31') OR p.price_channel<>CASE WHEN h.channel IN ('DOORDASH','UBEREATS') THEN 'DELIVERY' ELSE 'DIRECT' END",n('check_lines'))
        for header,detail in [('ordered_gross_usd','ordered'),('gross_sales_usd','gross'),('discount_usd','discount'),('comp_usd','comp'),('net_sales_usd','net'),('sales_tax_usd','tax')]:
            self.check('POS header/line '+header,f'SELECT c.check_id,c.{header}-coalesce(l.{detail},0) FROM checks c LEFT JOIN line_totals l USING(check_id) WHERE c.{header}<>coalesce(l.{detail},0)',n('checks'))
        self.check('Original check total includes sales tax and tips','SELECT check_id,total_due_usd-net_sales_usd-sales_tax_usd-card_tips_usd-cash_tips_usd FROM checks WHERE total_due_usd<>net_sales_usd+sales_tax_usd+card_tips_usd+cash_tips_usd',n('checks'))
        self.check('POS tender amount splits sales/tax and tip','SELECT payment_id,amount_usd-sales_and_tax_usd-tip_usd FROM payments WHERE amount_usd<>sales_and_tax_usd+tip_usd',n('payments'))
        self.check('Successful POS tenders have positive amount','SELECT payment_id,amount_usd FROM payments WHERE amount_usd<=0',n('payments'))
        self.check('Successful card captures have positive amount',"SELECT processor_transaction_id,gross_amount_usd FROM processor_transactions WHERE transaction_type='CAPTURE' AND gross_amount_usd<=0",n('processor_transactions'))
        self.check('Pre-order void checks have no unmatched external marketplace identity',"SELECT check_id,1 FROM checks WHERE status='VOID' AND platform_order_id IS NOT NULL",n('checks'),'count')
        self.check('Dine-in intervals never exceed physical seating capacity',"WITH events AS (SELECT check_id,restaurant_id,business_date,opened_at event_at,guests delta,1 arrival FROM checks WHERE status='CLOSED' AND channel='DINE_IN' UNION ALL SELECT check_id,restaurant_id,business_date,closed_at,-guests,0 FROM checks WHERE status='CLOSED' AND channel='DINE_IN'), occupancy AS (SELECT e.*,sum(delta) OVER(PARTITION BY restaurant_id,business_date ORDER BY event_at,delta,check_id ROWS UNBOUNDED PRECEDING) occupied FROM events e) SELECT o.check_id||'@'||o.event_at,o.occupied-r.seats FROM occupancy o JOIN restaurants r USING(restaurant_id) WHERE o.arrival=1 AND o.occupied>r.seats",n('checks'),'count')
        self.check('POS check total paid exactly once across tenders','SELECT c.check_id,c.total_due_usd-coalesce(t.amount,0) FROM checks c LEFT JOIN tender_totals t USING(check_id) WHERE c.total_due_usd<>coalesce(t.amount,0)',n('checks'))
        self.check('POS header tips equal card/cash tender tips','SELECT c.check_id,c.card_tips_usd-coalesce(t.cardtip,0) FROM checks c LEFT JOIN tender_totals t USING(check_id) WHERE c.card_tips_usd<>coalesce(t.cardtip,0) OR c.cash_tips_usd<>coalesce(t.cashtip,0)',n('checks'))
        self.check('Voids have no payment or preparation',"SELECT c.check_id,1 FROM checks c LEFT JOIN payments p USING(check_id) WHERE c.status='VOID' AND (p.payment_id IS NOT NULL OR c.total_due_usd<>0 OR EXISTS(SELECT 1 FROM check_lines l WHERE l.check_id=c.check_id AND l.line_status<>'VOID'))",n('checks'),'count')
        self.check('Void audit equals quoted line value',"SELECT v.void_id,v.quoted_amount_usd-l.menu_gross_usd-l.modifier_gross_usd FROM voids v JOIN check_lines l USING(check_line_id) WHERE l.line_status<>'VOID' OR v.kitchen_prepared<>'NO' OR v.quoted_amount_usd<>l.menu_gross_usd+l.modifier_gross_usd",n('voids'))
        for table,amount in [('discounts','discount_usd'),('comps','comp_usd')]:
            self.check('Line '+table+' matches approval register',f'SELECT l.check_line_id,l.{amount}-coalesce(a.amount,0) FROM check_lines l LEFT JOIN (SELECT check_line_id,sum(amount_usd) amount FROM {table} GROUP BY check_line_id) a USING(check_line_id) WHERE l.{amount}<>coalesce(a.amount,0)',n('check_lines'))
        self.check('Refund total and original line allocation',"SELECT r.refund_id,r.total_refund_usd-r.net_sales_refund_usd-r.tax_refund_usd-r.tip_refund_usd FROM refunds r JOIN check_lines l USING(check_line_id) JOIN payments p USING(payment_id) WHERE r.total_refund_usd<>r.net_sales_refund_usd+r.tax_refund_usd+r.tip_refund_usd OR r.net_sales_refund_usd<>R(l.net_sales_usd*r.refund_qty,l.quantity*1000000) OR r.check_id<>l.check_id OR r.check_id<>p.check_id OR r.tender_type<>p.tender_type OR r.refund_date<r.original_business_date OR r.refund_qty>l.quantity*1000000 OR r.inventory_restock<>'NO'",n('refunds'))
        self.check('Cumulative refunds do not exceed paid amount','SELECT p.payment_id,sum(r.total_refund_usd)-p.amount_usd FROM payments p JOIN refunds r USING(payment_id) GROUP BY p.payment_id HAVING sum(r.total_refund_usd)>p.amount_usd',n('payments'))
        self.check('Card capture/refund matches POS event',"SELECT t.processor_transaction_id,t.gross_amount_usd-CASE WHEN t.transaction_type='CAPTURE' THEN p.amount_usd ELSE -r.total_refund_usd END FROM processor_transactions t LEFT JOIN payments p USING(payment_id) LEFT JOIN refunds r USING(refund_id) WHERE (t.transaction_type='CAPTURE' AND (t.gross_amount_usd<>p.amount_usd OR p.tender_type<>'CARD' OR t.transaction_date<>p.business_date OR t.processor_transaction_id<>p.processor_capture_id)) OR (t.transaction_type='REFUND' AND (t.gross_amount_usd<>-r.total_refund_usd OR r.tender_type<>'CARD' OR t.transaction_date<>r.refund_date))",n('processor_transactions'))
        self.check('Exactly one processor capture for each card tender',"SELECT p.payment_id,count(t.processor_transaction_id)-1 FROM payments p LEFT JOIN processor_transactions t ON t.payment_id=p.payment_id AND t.transaction_type='CAPTURE' WHERE p.tender_type='CARD' GROUP BY p.payment_id HAVING count(t.processor_transaction_id)<>1",'SELECT count(*) FROM payments WHERE tender_type=\'CARD\'','count')
        self.check('Processor fee and net arithmetic',"SELECT processor_transaction_id,net_amount_usd-gross_amount_usd+fee_usd FROM processor_transactions WHERE net_amount_usd<>gross_amount_usd-fee_usd OR fee_usd<>CASE WHEN transaction_type='CAPTURE' THEN R(gross_amount_usd*265,10000)+10 ELSE 0 END",n('processor_transactions'))
        self.run('CREATE TABLE processor_totals AS SELECT payout_id,sum(CASE WHEN transaction_type=\'CAPTURE\' THEN gross_amount_usd ELSE 0 END) capture,-sum(CASE WHEN transaction_type=\'REFUND\' THEN gross_amount_usd ELSE 0 END) refund,sum(fee_usd) fees,sum(net_amount_usd) net FROM processor_transactions GROUP BY payout_id;CREATE INDEX ix_proc_totals ON processor_totals(payout_id);')
        self.check('Processor batches reconcile captures refunds fees','SELECT p.payout_id,p.payout_usd-t.net FROM processor_payouts p JOIN processor_totals t USING(payout_id) WHERE p.payout_usd<>t.net OR p.capture_usd<>t.capture OR p.refund_usd<>t.refund OR p.fees_usd<>t.fees',n('processor_payouts'))
        self.check('Processor payout actual bank arrival','SELECT p.payout_id,p.payout_usd-b.amount_usd FROM processor_payouts p JOIN bank_transactions b USING(bank_transaction_id) WHERE p.payout_usd<>b.amount_usd OR p.bank_arrival_date<>b.transaction_date OR b.source_id<>p.payout_id',n('processor_payouts'))
        self.check('Processor pending batches have no future actual bank values',"SELECT payout_id,1 FROM processor_payouts WHERE (expected_bank_date>'2026-10-31' AND (bank_arrival_date IS NOT NULL OR bank_transaction_id IS NOT NULL OR status='PAID')) OR (expected_bank_date<='2026-10-31' AND (bank_arrival_date IS NULL OR bank_transaction_id IS NULL))",n('processor_payouts'),'count')
        for p in ['doordash','ubereats']:self.marketplace(p)
        self.check('Closed marketplace checks map exactly once',"SELECT c.check_id,count(m.mapping_id)-1 FROM checks c LEFT JOIN marketplace_pos_map m USING(check_id) WHERE c.status='CLOSED' AND c.channel IN ('DOORDASH','UBEREATS') GROUP BY c.check_id HAVING count(m.mapping_id)<>1",'SELECT count(*) FROM marketplace_pos_map','count')
        self.check('Marketplace mapping key unique across both platforms','SELECT platform,platform_order_id,count(*)-1 FROM marketplace_pos_map GROUP BY platform,platform_order_id HAVING count(*)<>1',n('marketplace_pos_map'),'count')
        self.daily_and_cash()

    def marketplace(self,p):
        n=self.count
        self.check(p+' POS order identity and totals',f"SELECT o.platform_order_id,o.merchant_net_sales_usd-c.net_sales_usd FROM {p}_orders o JOIN checks c USING(check_id) JOIN marketplace_pos_map m USING(check_id) WHERE c.status<>'CLOSED' OR c.channel<>'{p.upper()}' OR m.platform<>'{p.upper()}' OR o.platform_order_id<>c.platform_order_id OR m.platform_order_id<>o.platform_order_id OR o.restaurant_id<>c.restaurant_id OR o.order_date<>c.business_date OR o.merchant_gross_usd<>c.gross_sales_usd OR o.merchant_discount_usd<>c.discount_usd OR o.merchant_comp_usd<>c.comp_usd OR o.merchant_net_sales_usd<>c.net_sales_usd OR o.sales_tax_usd<>c.sales_tax_usd",n(p+'_orders'))
        self.check(p+' tax retained by platform and promotion reimbursement',f'SELECT platform_order_id,merchant_net_sales_usd-customer_food_paid_usd-platform_reimbursement_usd FROM {p}_orders WHERE marketplace_tax_withheld_usd<>sales_tax_usd OR merchant_tip_usd<>0 OR platform_customer_promo_usd<>platform_reimbursement_usd OR merchant_net_sales_usd<>customer_food_paid_usd+platform_reimbursement_usd',n(p+'_orders'))
        self.check(p+' commission and net receivable',f'SELECT platform_order_id,merchant_net_receivable_usd-(merchant_net_sales_usd-commission_usd-merchant_promotion_fee_usd-service_adjustment_usd) FROM {p}_orders WHERE commission_usd<>R(merchant_net_sales_usd*commission_rate,1000000) OR merchant_net_receivable_usd<>merchant_net_sales_usd-commission_usd-merchant_promotion_fee_usd-service_adjustment_usd',n(p+'_orders'))
        self.check(p+' capture and refund event source arithmetic',f"SELECT t.platform_transaction_id,t.net_receivable_usd-t.merchant_sales_usd+t.commission_usd+t.promotion_fee_usd+t.service_adjustment_usd FROM {p}_transactions t JOIN {p}_orders o USING(platform_order_id) LEFT JOIN refunds r USING(refund_id) WHERE t.net_receivable_usd<>t.merchant_sales_usd-t.commission_usd-t.promotion_fee_usd-t.service_adjustment_usd OR (t.transaction_type='CAPTURE' AND (t.merchant_sales_usd<>o.merchant_net_sales_usd OR t.commission_usd<>o.commission_usd OR t.promotion_fee_usd<>o.merchant_promotion_fee_usd OR t.service_adjustment_usd<>o.service_adjustment_usd)) OR (t.transaction_type='REFUND' AND (t.merchant_sales_usd<>-r.net_sales_refund_usd OR t.transaction_date<>r.refund_date OR t.commission_usd<>0 OR t.promotion_fee_usd<>0 OR t.service_adjustment_usd<>0))",n(p+'_transactions'))
        self.run(f"CREATE TABLE {p}_totals AS SELECT settlement_id,sum(CASE WHEN transaction_type='CAPTURE' THEN merchant_sales_usd ELSE 0 END) sales,-sum(CASE WHEN transaction_type='REFUND' THEN merchant_sales_usd ELSE 0 END) refunds,sum(commission_usd) commission,sum(promotion_fee_usd) promo,sum(service_adjustment_usd) adjust,sum(net_receivable_usd) net FROM {p}_transactions GROUP BY settlement_id;CREATE INDEX ix_{p}_totals ON {p}_totals(settlement_id);")
        self.check(p+' settlement component totals',f'SELECT s.settlement_id,s.payout_usd-t.net FROM {p}_settlements s JOIN {p}_totals t USING(settlement_id) WHERE s.merchant_sales_usd<>t.sales OR s.refunds_usd<>t.refunds OR s.commissions_usd<>t.commission OR s.promotion_fees_usd<>t.promo OR s.service_adjustments_usd<>t.adjust OR s.payout_usd<>t.net',n(p+'_settlements'))
        self.check(p+' settlement bank amount/date',f'SELECT s.settlement_id,s.payout_usd-b.amount_usd FROM {p}_settlements s JOIN bank_transactions b USING(bank_transaction_id) WHERE s.payout_usd<>b.amount_usd OR s.bank_arrival_date<>b.transaction_date OR b.source_id<>s.settlement_id',n(p+'_settlements'))
        self.check(p+' pending settlement actual-date separation',f"SELECT settlement_id,1 FROM {p}_settlements WHERE (expected_bank_date>'{END}' AND (bank_arrival_date IS NOT NULL OR bank_transaction_id IS NOT NULL)) OR (expected_bank_date<='{END}' AND (bank_arrival_date IS NULL OR bank_transaction_id IS NULL))",n(p+'_settlements'),'count')

    def daily_and_cash(self):
        self.run('''CREATE TABLE daily_pos AS SELECT restaurant_id,business_date,sum(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) closed,sum(CASE WHEN status='VOID' THEN 1 ELSE 0 END) voided,sum(CASE WHEN status='CLOSED' THEN guests ELSE 0 END) guests,sum(gross_sales_usd) gross,sum(discount_usd) discount,sum(comp_usd) comp,sum(net_sales_usd) net,sum(CASE WHEN channel IN ('DINE_IN','TAKEAWAY') THEN sales_tax_usd ELSE 0 END) directtax,sum(CASE WHEN channel IN ('DOORDASH','UBEREATS') THEN sales_tax_usd ELSE 0 END) markettax,sum(card_tips_usd) cardtip,sum(cash_tips_usd) cashtip FROM checks GROUP BY restaurant_id,business_date;
        CREATE INDEX ix_daily_pos ON daily_pos(restaurant_id,business_date);
        CREATE TABLE daily_tenders AS SELECT restaurant_id,business_date,sum(CASE WHEN tender_type='CASH' THEN amount_usd ELSE 0 END) cash,sum(CASE WHEN tender_type='CARD' THEN amount_usd ELSE 0 END) card,sum(CASE WHEN tender_type='DOORDASH' THEN amount_usd ELSE 0 END) doordash,sum(CASE WHEN tender_type='UBEREATS' THEN amount_usd ELSE 0 END) ubereats FROM payments GROUP BY restaurant_id,business_date;
        CREATE INDEX ix_daily_tenders ON daily_tenders(restaurant_id,business_date);
        ''')
        for field,raw in [('gross_sales_usd','gross'),('discount_usd','discount'),('comp_usd','comp'),('net_sales_usd','net'),('direct_sales_tax_usd','directtax'),('marketplace_sales_tax_usd','markettax'),('card_tips_usd','cardtip'),('cash_tips_usd','cashtip'),('closed_check_count','closed'),('void_check_count','voided'),('guest_count','guests')]:
            self.check('Daily POS close '+field,f'SELECT c.close_id,c.{field}-p.{raw} FROM day_closings c JOIN daily_pos p USING(restaurant_id,business_date) WHERE c.{field}<>p.{raw}',self.count('day_closings'),'count' if field.endswith('_count') else 'cents')
        for tender in ['cash','card','doordash','ubereats']:
            self.check('Daily tender close '+tender,f'SELECT c.close_id,c.{tender}_tenders_usd-p.{tender} FROM day_closings c JOIN daily_tenders p USING(restaurant_id,business_date) WHERE c.{tender}_tenders_usd<>p.{tender}',self.count('day_closings'))
        self.check('Cash drawer source POS amounts','SELECT d.drawer_close_id,d.cash_tenders_usd-c.cash_tenders_usd FROM cash_drawer_closings d JOIN day_closings c USING(close_id) WHERE d.cash_tenders_usd<>c.cash_tenders_usd OR d.cash_refunds_usd<>c.cash_refunds_usd OR d.cash_tips_paid_usd<>c.cash_tips_usd',self.count('cash_drawer_closings'))
        self.check('Drawer expected count and shortage/overage','SELECT drawer_close_id,counted_before_deposit_usd-expected_before_count_usd-over_short_usd FROM cash_drawer_closings WHERE expected_before_count_usd<>opening_float_usd+cash_tenders_usd-cash_refunds_usd-cash_tips_paid_usd-petty_cash_out_usd OR counted_before_deposit_usd<>expected_before_count_usd+over_short_usd OR closing_float_usd<>40000 OR counted_before_deposit_usd-deposit_bag_usd<>closing_float_usd',self.count('cash_drawer_closings'))
        self.check('Petty cash receipts reconcile drawer outflow','SELECT d.drawer_close_id,d.petty_cash_out_usd-coalesce(p.amount,0) FROM cash_drawer_closings d LEFT JOIN (SELECT restaurant_id,transaction_date business_date,sum(amount_usd) amount FROM petty_cash_receipts GROUP BY restaurant_id,transaction_date) p USING(restaurant_id,business_date) WHERE d.petty_cash_out_usd<>coalesce(p.amount,0)',self.count('cash_drawer_closings'))
        self.check('Deposit bag equals counted drawer extraction','SELECT c.deposit_id,c.deposit_bag_usd-d.deposit_bag_usd FROM cash_deposits c JOIN cash_drawer_closings d USING(deposit_id) WHERE c.deposit_bag_usd<>d.deposit_bag_usd OR c.dispatch_date<>d.business_date',self.count('cash_deposits'))
        self.check('Cash bag actual bank arrival','SELECT d.deposit_id,d.deposit_bag_usd-b.amount_usd FROM cash_deposits d JOIN bank_transactions b USING(bank_transaction_id) WHERE d.deposit_bag_usd<>b.amount_usd OR d.bank_arrival_date<>b.transaction_date OR b.source_id<>d.deposit_id',self.count('cash_deposits'))
        self.check('Pending cash bags have no future actual arrival',f"SELECT deposit_id,1 FROM cash_deposits WHERE (expected_bank_date>'{END}' AND (bank_arrival_date IS NOT NULL OR bank_transaction_id IS NOT NULL)) OR (expected_bank_date<='{END}' AND (bank_arrival_date IS NULL OR bank_transaction_id IS NULL))",self.count('cash_deposits'),'count')

    def procurement_inventory(self):
        n=self.count
        self.check('Recipe edible yield to raw base quantity','SELECT recipe_component_id,raw_per_portion_qty-R(edible_per_portion_qty*1000000,yield_factor) FROM recipe_components WHERE raw_per_portion_qty<>R(edible_per_portion_qty*1000000,yield_factor) OR yield_factor<=0',n('recipe_components'),'quantity')
        self.check('Supplier price unit conversion','SELECT p.supplier_price_id,p.base_unit_price_usd-R(p.pack_price_usd*10000000000,p.base_units_per_pack_qty) FROM supplier_price_versions p JOIN ingredients i USING(ingredient_id) WHERE p.base_units_per_pack_qty<>i.base_units_per_pack_qty OR p.base_unit_price_usd<>R(p.pack_price_usd*10000000000,p.base_units_per_pack_qty)',n('supplier_price_versions'),'quantity')
        self.check('PO ordered pack/base/value and price interval','SELECT l.purchase_order_line_id,l.ordered_base_qty-R(l.ordered_pack_qty*i.base_units_per_pack_qty,1000000) FROM purchase_order_lines l JOIN ingredients i USING(ingredient_id) JOIN purchase_orders p USING(purchase_order_id) JOIN supplier_price_versions s USING(supplier_price_id) WHERE l.ordered_base_qty<>R(l.ordered_pack_qty*i.base_units_per_pack_qty,1000000) OR l.ordered_value_usd<>R(l.ordered_pack_qty*l.pack_price_usd,1000000) OR l.pack_price_usd<>s.pack_price_usd OR p.order_date<s.effective_from OR p.order_date>coalesce(s.effective_to,\'9999-12-31\')',n('purchase_order_lines'),'quantity')
        self.check('PO line accepted short and outstanding quantity','SELECT purchase_order_line_id,ordered_base_qty-accepted_base_qty-credited_short_base_qty-outstanding_base_qty FROM purchase_order_lines WHERE ordered_base_qty<>accepted_base_qty+credited_short_base_qty+outstanding_base_qty OR outstanding_base_qty<0',n('purchase_order_lines'),'quantity')
        self.check('Receipt pack quantity integrity','SELECT receipt_line_id,shipped_pack_qty-delivered_pack_qty-short_pack_qty FROM receipt_lines WHERE shipped_pack_qty<>delivered_pack_qty+short_pack_qty OR delivered_pack_qty<>accepted_pack_qty+rejected_pack_qty OR accepted_pack_qty<0 OR rejected_pack_qty<0 OR short_pack_qty<0',n('receipt_lines'),'quantity')
        self.check('Receipt base quantity and billed accepted credited value','SELECT r.receipt_line_id,r.accepted_value_usd-R(r.accepted_pack_qty*p.pack_price_usd,1000000) FROM receipt_lines r JOIN purchase_order_lines p USING(purchase_order_line_id) JOIN ingredients i USING(ingredient_id) WHERE r.accepted_base_qty<>R(r.accepted_pack_qty*i.base_units_per_pack_qty,1000000) OR r.billed_value_usd<>R(r.shipped_pack_qty*p.pack_price_usd,1000000) OR r.accepted_value_usd<>R(r.accepted_pack_qty*p.pack_price_usd,1000000) OR r.billed_value_usd-r.shortage_credit_usd<>r.accepted_value_usd',n('receipt_lines'))
        self.check('Receipt inventory movement quantity/cost','SELECT r.receipt_line_id,r.accepted_value_usd-m.value_delta_usd FROM receipt_lines r JOIN inventory_movements m USING(inventory_movement_id) WHERE r.accepted_base_qty<>m.quantity_delta_qty OR r.accepted_value_usd<>m.value_delta_usd OR m.movement_type<>\'RECEIPT\' OR m.reference_id<>r.receipt_line_id',n('receipt_lines'))
        self.run('''CREATE TABLE received_po AS SELECT purchase_order_line_id,sum(accepted_base_qty) accepted,sum(shortage_credit_usd) credit FROM receipt_lines GROUP BY purchase_order_line_id;CREATE INDEX ix_received_po ON received_po(purchase_order_line_id);
        CREATE TABLE credited_po AS SELECT r.purchase_order_line_id,sum(c.credited_base_qty) qty FROM supplier_credit_lines c JOIN receipt_lines r USING(receipt_line_id) GROUP BY r.purchase_order_line_id;CREATE INDEX ix_credited_po ON credited_po(purchase_order_line_id);''')
        self.check('PO accepted quantity rebuilt from saved receipts','SELECT p.purchase_order_line_id,p.accepted_base_qty-coalesce(r.accepted,0) FROM purchase_order_lines p LEFT JOIN received_po r USING(purchase_order_line_id) WHERE p.accepted_base_qty<>coalesce(r.accepted,0)',n('purchase_order_lines'),'quantity')
        self.check('PO short quantity rebuilt from actual supplier credits','SELECT p.purchase_order_line_id,p.credited_short_base_qty-coalesce(r.qty,0) FROM purchase_order_lines p LEFT JOIN credited_po r USING(purchase_order_line_id) WHERE p.credited_short_base_qty<>coalesce(r.qty,0)',n('purchase_order_lines'),'quantity')
        self.check('PO header value and status reconcile lines',"SELECT p.purchase_order_id,p.ordered_value_usd-l.ordered FROM purchase_orders p JOIN (SELECT purchase_order_id,sum(ordered_value_usd) ordered,sum(outstanding_base_qty) outstanding FROM purchase_order_lines GROUP BY purchase_order_id) l USING(purchase_order_id) WHERE p.ordered_value_usd<>l.ordered OR (p.status='OPEN')<>(l.outstanding>0)",n('purchase_orders'))
        self.check('Delivery schedule actual receipt identity','SELECT d.delivery_schedule_id,1 FROM delivery_schedule d LEFT JOIN receipts r USING(receipt_id) WHERE (d.actual_delivery_date IS NOT NULL AND (r.receipt_id IS NULL OR d.actual_delivery_date<>r.receipt_date OR d.purchase_order_id<>r.purchase_order_id)) OR (d.actual_delivery_date IS NULL AND d.receipt_id IS NOT NULL)',n('delivery_schedule'),'count')
        self.check('Supplier invoice line pack arithmetic','SELECT l.supplier_invoice_line_id,l.billed_amount_usd-R(l.billed_pack_qty*l.pack_price_usd,1000000) FROM supplier_invoice_lines l JOIN receipt_lines r USING(receipt_line_id) WHERE l.billed_amount_usd<>R(l.billed_pack_qty*l.pack_price_usd,1000000) OR l.billed_amount_usd<>r.billed_value_usd OR l.billed_pack_qty<>r.shipped_pack_qty',n('supplier_invoice_lines'))
        self.check('Supplier invoice gross net credit and receipt value','SELECT s.supplier_invoice_id,s.net_payable_usd-r.accepted_value_usd FROM supplier_invoices s JOIN receipts r ON s.receipt_id=r.receipt_id JOIN (SELECT supplier_invoice_id,sum(billed_amount_usd) amount FROM supplier_invoice_lines GROUP BY supplier_invoice_id) l USING(supplier_invoice_id) WHERE s.gross_amount_usd<>l.amount OR s.net_payable_usd<>s.gross_amount_usd-s.credit_amount_usd OR s.net_payable_usd<>r.accepted_value_usd',n('supplier_invoices'))
        self.check('Supplier invoice to accounting bill one-to-one','SELECT s.supplier_invoice_id,s.gross_amount_usd-b.gross_amount_usd FROM supplier_invoices s JOIN vendor_bills b ON s.accounting_bill_id=b.bill_id WHERE s.gross_amount_usd<>b.gross_amount_usd OR s.credit_amount_usd<>b.credit_applied_usd OR s.supplier_invoice_id<>b.source_document_id OR s.invoice_date<>b.bill_date OR s.restaurant_id<>b.restaurant_id',n('supplier_invoices'))
        self.check('Supplier credit lines and shortage match','SELECT c.supplier_credit_line_id,c.amount_usd-r.shortage_credit_usd FROM supplier_credit_lines c JOIN receipt_lines r USING(receipt_line_id) JOIN ingredients i USING(ingredient_id) WHERE c.amount_usd<>r.shortage_credit_usd OR c.credited_base_qty<>R(c.credited_pack_qty*i.base_units_per_pack_qty,1000000) OR c.credited_pack_qty<>r.short_pack_qty+r.rejected_pack_qty',n('supplier_credit_lines'))
        self.check('Supplier credit header sum matches accounting credit','SELECT c.supplier_credit_note_id,c.amount_usd-v.amount_usd FROM supplier_credit_notes c JOIN vendor_credits v ON c.supplier_credit_note_id=v.vendor_credit_id JOIN (SELECT supplier_credit_note_id,sum(amount_usd) amount FROM supplier_credit_lines GROUP BY supplier_credit_note_id) l USING(supplier_credit_note_id) WHERE c.amount_usd<>v.amount_usd OR c.amount_usd<>l.amount',n('supplier_credit_notes'))
        # Servings reconstructed from individual saved POS lines and selected modifiers.
        self.run('''CREATE TABLE servings_raw AS
        SELECT h.restaurant_id,l.business_date,'REC-'||l.menu_item_id recipe_id,l.quantity servings FROM check_lines l JOIN checks h USING(check_id) WHERE l.line_status='SERVED'
        UNION ALL SELECT h.restaurant_id,m.business_date,'REC-'||m.modifier_id,m.quantity FROM check_modifiers m JOIN checks h USING(check_id) WHERE m.modifier_status='SERVED'
        UNION ALL SELECT restaurant_id,business_date,'REC-PACKAGING',1 FROM checks WHERE status='CLOSED' AND channel<>'DINE_IN'
        UNION ALL SELECT restaurant_id,business_date,recipe_id,meal_count FROM staff_meals;
        CREATE TABLE servings AS SELECT restaurant_id,business_date,recipe_id,sum(servings) servings FROM servings_raw GROUP BY restaurant_id,business_date,recipe_id;
        CREATE INDEX ix_servings ON servings(restaurant_id,business_date,recipe_id);
        CREATE INDEX ix_usage_components ON theoretical_usage(restaurant_id,business_date,recipe_component_id);
        ''')
        self.check('Every served recipe/component has exactly one usage row','SELECT s.restaurant_id||s.business_date||r.recipe_component_id,count(u.usage_id)-1 FROM servings s JOIN recipe_components r USING(recipe_id) LEFT JOIN theoretical_usage u ON u.restaurant_id=s.restaurant_id AND u.business_date=s.business_date AND u.recipe_component_id=r.recipe_component_id GROUP BY s.restaurant_id,s.business_date,r.recipe_component_id HAVING count(u.usage_id)<>1','SELECT count(*) FROM servings s JOIN recipe_components r USING(recipe_id)','count')
        self.check('Theoretical ingredient quantity rebuilt from POS and BOM','SELECT u.usage_id,u.theoretical_use_qty-s.servings*r.raw_per_portion_qty FROM theoretical_usage u JOIN recipe_components r USING(recipe_component_id) LEFT JOIN servings s ON u.restaurant_id=s.restaurant_id AND u.business_date=s.business_date AND u.recipe_id=s.recipe_id WHERE s.servings IS NULL OR u.served_count<>s.servings OR u.raw_per_portion_qty<>r.raw_per_portion_qty OR u.theoretical_use_qty<>s.servings*r.raw_per_portion_qty OR u.ingredient_id<>r.ingredient_id',n('theoretical_usage'),'quantity')
        self.check('Theoretical usage quantity and cost link to actual issue','SELECT u.usage_id,u.usage_cost_usd+m.value_delta_usd FROM theoretical_usage u JOIN inventory_movements m USING(inventory_movement_id) WHERE u.theoretical_use_qty<>-m.quantity_delta_qty OR u.usage_cost_usd<>-m.value_delta_usd OR m.reference_id<>u.usage_id OR u.restaurant_id<>m.restaurant_id OR u.ingredient_id<>m.ingredient_id',n('theoretical_usage'))
        self.check('Staff meal count matches worked hourly shifts plus managers','SELECT s.staff_meal_id,s.meal_count-t.cnt-2 FROM staff_meals s JOIN (SELECT restaurant_id,business_date,count(*) cnt FROM timesheets GROUP BY restaurant_id,business_date) t USING(restaurant_id,business_date) WHERE s.meal_count<>t.cnt+2',n('staff_meals'),'count')
        self.check('Waste quantity/cost links to movement',"SELECT w.waste_event_id,w.waste_cost_usd+m.value_delta_usd FROM waste_events w JOIN inventory_movements m USING(inventory_movement_id) WHERE w.waste_qty<>-m.quantity_delta_qty OR w.waste_cost_usd<>-m.value_delta_usd OR m.movement_type<>'WASTE' OR m.reference_id<>w.waste_event_id",n('waste_events'))
        self.check('Paired transfers preserve quantity and carrying value',"SELECT t.transfer_id,o.value_delta_usd+i.value_delta_usd FROM inventory_transfers t JOIN inventory_movements o ON t.out_movement_id=o.inventory_movement_id JOIN inventory_movements i ON t.in_movement_id=i.inventory_movement_id WHERE o.quantity_delta_qty<>-t.transfer_qty OR i.quantity_delta_qty<>t.transfer_qty OR o.value_delta_usd<>-t.carrying_cost_usd OR i.value_delta_usd<>t.carrying_cost_usd OR o.restaurant_id<>t.from_restaurant_id OR i.restaurant_id<>t.to_restaurant_id OR o.ingredient_id<>i.ingredient_id OR o.movement_type<>'TRANSFER_OUT' OR i.movement_type<>'TRANSFER_IN'",n('inventory_transfers'))
        self.check('Physical stock count arithmetic and movement','SELECT s.stock_count_id,s.counted_qty-s.expected_qty-s.adjustment_qty FROM physical_stock_counts s LEFT JOIN inventory_movements m USING(inventory_movement_id) WHERE s.counted_qty<>s.expected_qty+s.adjustment_qty OR (s.adjustment_qty<>0 AND (m.inventory_movement_id IS NULL OR s.adjustment_qty<>m.quantity_delta_qty OR s.adjustment_value_usd<>m.value_delta_usd)) OR (s.adjustment_qty=0 AND (m.inventory_movement_id IS NOT NULL OR s.adjustment_value_usd<>0))',n('physical_stock_counts'),'quantity')
        self.run('''CREATE TABLE movement_previous AS SELECT m.*,coalesce(lag(balance_after_qty) OVER(PARTITION BY restaurant_id,ingredient_id ORDER BY movement_sequence),o.on_hand_qty) prevqty,coalesce(lag(value_after_usd) OVER(PARTITION BY restaurant_id,ingredient_id ORDER BY movement_sequence),o.inventory_value_usd) prevvalue FROM inventory_movements m JOIN opening_inventory o USING(restaurant_id,ingredient_id);
        CREATE TABLE movement_daily AS SELECT restaurant_id,ingredient_id,movement_date business_date,sum(quantity_delta_qty) q,sum(value_delta_usd) v FROM inventory_movements GROUP BY restaurant_id,ingredient_id,movement_date;
        CREATE INDEX ix_movement_daily ON movement_daily(restaurant_id,ingredient_id,business_date);
        CREATE TABLE daily_previous AS SELECT b.*,coalesce(lag(closing_qty) OVER(PARTITION BY restaurant_id,ingredient_id ORDER BY business_date),o.on_hand_qty) prevqty,coalesce(lag(closing_value_usd) OVER(PARTITION BY restaurant_id,ingredient_id ORDER BY business_date),o.inventory_value_usd) prevvalue FROM inventory_daily_balances b JOIN opening_inventory o USING(restaurant_id,ingredient_id);
        ''')
        self.check('Every inventory movement quantity roll-forward','SELECT inventory_movement_id,balance_after_qty-prevqty-quantity_delta_qty FROM movement_previous WHERE balance_after_qty<>prevqty+quantity_delta_qty',n('inventory_movements'),'quantity')
        self.check('Every inventory movement value roll-forward','SELECT inventory_movement_id,value_after_usd-prevvalue-value_delta_usd FROM movement_previous WHERE value_after_usd<>prevvalue+value_delta_usd',n('inventory_movements'))
        self.check('Perpetual weighted-average issue cost to cent',"SELECT inventory_movement_id,-value_delta_usd-R(prevvalue*(-quantity_delta_qty),prevqty) FROM movement_previous WHERE quantity_delta_qty<0 AND -value_delta_usd<>R(prevvalue*(-quantity_delta_qty),prevqty)",n('inventory_movements'))
        self.check('Stock count gains use existing carrying value',"SELECT inventory_movement_id,value_delta_usd-R(prevvalue*quantity_delta_qty,prevqty) FROM movement_previous WHERE movement_type='COUNT_ADJUSTMENT' AND quantity_delta_qty>0 AND value_delta_usd<>R(prevvalue*quantity_delta_qty,prevqty)",n('physical_stock_counts'))
        self.check('No negative stock quantity or inventory carrying value','SELECT inventory_movement_id,min(balance_after_qty,value_after_usd) FROM inventory_movements WHERE balance_after_qty<0 OR value_after_usd<0 OR (balance_after_qty=0 AND value_after_usd<>0)',n('inventory_movements'),'quantity')
        self.check('Daily ingredient closing quantity roll-forward','SELECT b.inventory_balance_id,b.closing_qty-b.prevqty-coalesce(m.q,0) FROM daily_previous b LEFT JOIN movement_daily m USING(restaurant_id,ingredient_id,business_date) WHERE b.closing_qty<>b.prevqty+coalesce(m.q,0)',n('inventory_daily_balances'),'quantity')
        self.check('Daily ingredient closing value roll-forward','SELECT b.inventory_balance_id,b.closing_value_usd-b.prevvalue-coalesce(m.v,0) FROM daily_previous b LEFT JOIN movement_daily m USING(restaurant_id,ingredient_id,business_date) WHERE b.closing_value_usd<>b.prevvalue+coalesce(m.v,0)',n('inventory_daily_balances'))

    def ap_checks(self):
        n=self.count
        self.run('''CREATE TABLE bill_line_totals AS SELECT bill_id,sum(amount_usd) amount FROM vendor_bill_lines GROUP BY bill_id;CREATE INDEX ix_bill_line_totals ON bill_line_totals(bill_id);
        CREATE TABLE bill_cash_totals AS SELECT bill_id,sum(amount_usd) amount FROM bill_payment_applications GROUP BY bill_id;CREATE INDEX ix_bill_cash_totals ON bill_cash_totals(bill_id);
        CREATE TABLE bill_credit_totals AS SELECT bill_id,sum(amount_usd) amount FROM bill_credit_applications GROUP BY bill_id;CREATE INDEX ix_bill_credit_totals ON bill_credit_totals(bill_id);''')
        self.check('AP bill total equals its account lines','SELECT b.bill_id,b.gross_amount_usd-l.amount FROM vendor_bills b JOIN bill_line_totals l USING(bill_id) WHERE b.gross_amount_usd<>l.amount',n('vendor_bills'))
        self.check('AP credits cash applications and remaining balance','SELECT b.bill_id,b.open_balance_usd-b.gross_amount_usd+coalesce(c.amount,0)+coalesce(p.amount,0) FROM vendor_bills b LEFT JOIN bill_credit_totals c USING(bill_id) LEFT JOIN bill_cash_totals p USING(bill_id) WHERE b.credit_applied_usd<>coalesce(c.amount,0) OR b.cash_paid_usd<>coalesce(p.amount,0) OR b.open_balance_usd<>b.gross_amount_usd-coalesce(c.amount,0)-coalesce(p.amount,0) OR b.open_balance_usd<0',n('vendor_bills'))
        self.check('Vendor payment sums its bill applications','SELECT p.vendor_payment_id,p.amount_usd-coalesce(a.amount,0) FROM vendor_payments p LEFT JOIN (SELECT vendor_payment_id,sum(amount_usd) amount FROM bill_payment_applications GROUP BY vendor_payment_id) a USING(vendor_payment_id) WHERE p.amount_usd<>coalesce(a.amount,0)',n('vendor_payments'))
        self.check('Vendor bank debit identity and sign','SELECT p.vendor_payment_id,p.amount_usd+b.amount_usd FROM vendor_payments p JOIN bank_transactions b USING(bank_transaction_id) WHERE p.amount_usd<>-b.amount_usd OR p.payment_date<>b.transaction_date OR b.source_id<>p.vendor_payment_id',n('vendor_payments'))
        self.check('Bill payment application vendor/date identity','SELECT a.bill_application_id,1 FROM bill_payment_applications a JOIN vendor_payments p USING(vendor_payment_id) JOIN vendor_bills b USING(bill_id) WHERE b.vendor_id<>p.vendor_id OR b.restaurant_id<>p.restaurant_id OR a.application_date<>p.payment_date OR a.application_date<b.bill_date',n('bill_payment_applications'),'count')
        self.check('Credit application noncash amount and date','SELECT a.credit_application_id,a.amount_usd-c.amount_usd FROM bill_credit_applications a JOIN vendor_credits c USING(vendor_credit_id) WHERE a.amount_usd<>c.amount_usd OR a.bill_id<>c.bill_id OR a.application_date<>c.credit_date',n('bill_credit_applications'))
        self.check('AP installments sum to net bill and open schedules equal open AP',"SELECT b.bill_id,b.open_balance_usd-coalesce(s.openamount,0) FROM vendor_bills b LEFT JOIN (SELECT bill_id,sum(amount_usd) total,sum(CASE WHEN status='OPEN' THEN amount_usd ELSE 0 END) openamount FROM bill_payment_schedule GROUP BY bill_id) s USING(bill_id) WHERE b.gross_amount_usd-b.credit_applied_usd<>s.total OR b.open_balance_usd<>coalesce(s.openamount,0)",n('vendor_bills'))
        self.check('AP scheduled/actual paid date separation',f"SELECT bill_schedule_id,1 FROM bill_payment_schedule WHERE (agreed_payment_date>'{END}' AND (actual_payment_date IS NOT NULL OR vendor_payment_id IS NOT NULL OR status<>'OPEN')) OR (agreed_payment_date<='{END}' AND (actual_payment_date IS NULL OR vendor_payment_id IS NULL OR status<>'PAID'))",n('bill_payment_schedule'),'count')

    def labor(self):
        n=self.count
        self.check('Pay rate intervals do not overlap per employee',"SELECT a.pay_rate_id||b.pay_rate_id,1 FROM pay_rates a JOIN pay_rates b ON a.employee_id=b.employee_id AND a.pay_rate_id<b.pay_rate_id WHERE a.effective_from<=coalesce(b.effective_to,'9999-12-31') AND b.effective_from<=coalesce(a.effective_to,'9999-12-31')",n('pay_rates'),'count')
        self.check('Every active snapshot employee has exactly one current rate',f"SELECT e.employee_id,count(r.pay_rate_id)-1 FROM employees e LEFT JOIN pay_rates r ON e.employee_id=r.employee_id AND r.effective_from<='{END}' AND coalesce(r.effective_to,'9999-12-31')>='{END}' WHERE e.hire_date<='{END}' AND (e.termination_date IS NULL OR e.termination_date>='{END}') GROUP BY e.employee_id HAVING count(r.pay_rate_id)<>1",n('employees'),'count')
        self.check('Actual shift minutes from clock timestamps and breaks','SELECT timesheet_id,paid_minutes-MINS(clock_in_at,clock_out_at)+unpaid_break_minutes FROM timesheets WHERE paid_minutes<>MINS(clock_in_at,clock_out_at)-unpaid_break_minutes OR paid_minutes<>regular_minutes+overtime_minutes OR paid_minutes<=0',n('timesheets'),'count')
        self.check('Planned shift minutes from schedule timestamps','SELECT shift_id,scheduled_paid_minutes-MINS(scheduled_start_at,scheduled_end_at)+scheduled_break_minutes FROM scheduled_shifts WHERE scheduled_paid_minutes<>MINS(scheduled_start_at,scheduled_end_at)-scheduled_break_minutes',n('scheduled_shifts'),'count')
        self.check('Timesheet employee role location and active effective rate','SELECT t.timesheet_id,1 FROM timesheets t JOIN employees e USING(employee_id) JOIN pay_rates r USING(pay_rate_id) JOIN scheduled_shifts s USING(shift_id) WHERE t.employee_id<>r.employee_id OR t.employee_id<>s.employee_id OR t.restaurant_id<>e.home_restaurant_id OR t.role_id<>e.role_id OR t.business_date<e.hire_date OR (e.termination_date IS NOT NULL AND t.business_date>e.termination_date) OR t.business_date<r.effective_from OR t.business_date>coalesce(r.effective_to,\'9999-12-31\')',n('timesheets'),'count')
        self.check('Hourly regular/overtime pay at effective rates','SELECT t.timesheet_id,t.wage_expense_usd-t.regular_pay_usd-t.overtime_pay_usd FROM timesheets t JOIN pay_rates r USING(pay_rate_id) WHERE t.regular_pay_usd<>R(t.regular_minutes*r.hourly_rate_usd,60) OR t.overtime_pay_usd<>R(t.overtime_minutes*r.hourly_rate_usd*3,120) OR t.wage_expense_usd<>t.regular_pay_usd+t.overtime_pay_usd',n('timesheets'))
        self.check('Hour decimals consistently derive from paid minutes','SELECT timesheet_id,paid_hours-R(paid_minutes*1000000,60) FROM timesheets WHERE paid_hours<>R(paid_minutes*1000000,60) OR regular_hours<>R(regular_minutes*1000000,60) OR overtime_hours<>R(overtime_minutes*1000000,60)',n('timesheets'),'quantity')
        self.run('''CREATE TABLE workweek AS SELECT t.*,coalesce(sum(t.paid_minutes) OVER(PARTITION BY t.employee_id,t.workweek_start_date ORDER BY t.business_date,t.timesheet_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)+coalesce(o.paid_minutes_before_window,0) minutes_before FROM timesheets t LEFT JOIN opening_workweek_balances o ON t.employee_id=o.employee_id AND t.workweek_start_date=o.workweek_start_date;
        CREATE TABLE time_by_payroll AS SELECT payroll_run_id,employee_id,sum(regular_minutes) regular_minutes,sum(overtime_minutes) overtime_minutes,sum(regular_pay_usd) regular,sum(overtime_pay_usd) overtime FROM timesheets GROUP BY payroll_run_id,employee_id;
        CREATE INDEX ix_time_by_payroll ON time_by_payroll(payroll_run_id,employee_id);
        CREATE TABLE tips_by_payroll AS SELECT payroll_run_id,employee_id,sum(card_tips_usd) cardtip,sum(cash_tips_usd) cashtip FROM tip_allocations GROUP BY payroll_run_id,employee_id;
        CREATE INDEX ix_tips_by_payroll ON tips_by_payroll(payroll_run_id,employee_id);
        ''')
        self.check('Weekly overtime includes opening and cross-period carry','SELECT timesheet_id,overtime_minutes-max(0,paid_minutes-max(0,2400-minutes_before)) FROM workweek WHERE overtime_minutes<>max(0,paid_minutes-max(0,2400-minutes_before))',n('timesheets'),'count')
        self.check('Payroll run contains earned shift date','SELECT t.timesheet_id,1 FROM timesheets t JOIN payroll_runs p USING(payroll_run_id) WHERE t.business_date<p.period_start OR t.business_date>p.period_end',n('timesheets'),'count')
        self.check('Tip allocations only to worked eligible employees','SELECT a.tip_allocation_id,1 FROM tip_allocations a JOIN timesheets t USING(timesheet_id) JOIN roles r ON t.role_id=r.role_id WHERE r.tip_eligible<>\'YES\' OR a.employee_id<>t.employee_id OR a.business_date<>t.business_date OR a.cash_tip_paid_date<>a.business_date',n('tip_allocations'),'count')
        self.check('Daily employee tip allocation equals POS collected staff tips','SELECT c.close_id,c.card_tips_usd-coalesce(t.cardtip,0) FROM day_closings c LEFT JOIN (SELECT restaurant_id,business_date,sum(card_tips_usd) cardtip,sum(cash_tips_usd) cashtip FROM tip_allocations GROUP BY restaurant_id,business_date) t USING(restaurant_id,business_date) WHERE c.card_tips_usd<>coalesce(t.cardtip,0) OR c.cash_tips_usd<>coalesce(t.cashtip,0)',n('day_closings'))
        self.check('Payroll hourly earnings and tips reconcile independent sources','SELECT p.payroll_register_id,p.regular_wages_usd-coalesce(t.regular,0) FROM payroll_register p LEFT JOIN time_by_payroll t USING(payroll_run_id,employee_id) LEFT JOIN tips_by_payroll a USING(payroll_run_id,employee_id) WHERE p.regular_minutes<>coalesce(t.regular_minutes,0) OR p.overtime_minutes<>coalesce(t.overtime_minutes,0) OR p.regular_wages_usd<>coalesce(t.regular,0) OR p.overtime_wages_usd<>coalesce(t.overtime,0) OR p.card_tips_usd<>coalesce(a.cardtip,0) OR p.cash_tips_reported_usd<>coalesce(a.cashtip,0)',n('payroll_register'))
        self.check('Payroll salary pro rata at agreed effective annual rate',"SELECT p.payroll_register_id,p.salary_wages_usd-R(r.annual_salary_usd*CAST(julianday(min(x.period_end,coalesce(e.termination_date,x.period_end)))-julianday(max(x.period_start,e.hire_date))+1 AS INTEGER),24*CAST(julianday(x.period_end)-julianday(x.period_start)+1 AS INTEGER)) FROM payroll_register p JOIN payroll_runs x USING(payroll_run_id) JOIN employees e USING(employee_id) JOIN pay_rates r ON r.employee_id=p.employee_id AND max(x.period_start,e.hire_date) BETWEEN r.effective_from AND coalesce(r.effective_to,'9999-12-31') WHERE p.pay_type='SALARY' AND p.salary_wages_usd<>R(r.annual_salary_usd*CAST(julianday(min(x.period_end,coalesce(e.termination_date,x.period_end)))-julianday(max(x.period_start,e.hire_date))+1 AS INTEGER),24*CAST(julianday(x.period_end)-julianday(x.period_start)+1 AS INTEGER))",'SELECT count(*) FROM payroll_register WHERE pay_type=\'SALARY\'')
        self.check('Payroll wage taxable gross and net pay arithmetic','SELECT payroll_register_id,net_pay_usd-wage_expense_usd-card_tips_usd+employee_withholding_usd FROM payroll_register WHERE wage_expense_usd<>regular_wages_usd+overtime_wages_usd+salary_wages_usd OR taxable_gross_usd<>wage_expense_usd+card_tips_usd+cash_tips_reported_usd OR net_pay_usd<>wage_expense_usd+card_tips_usd-employee_withholding_usd OR net_pay_usd<0',n('payroll_register'))
        self.check('Payroll employee withholding and employer model tax rates','SELECT p.payroll_register_id,p.employer_taxes_usd-R(p.taxable_gross_usd*r.employer_tax_rate,1000000) FROM payroll_register p JOIN payroll_runs x USING(payroll_run_id) JOIN employees e USING(employee_id) JOIN pay_rates r ON r.employee_id=p.employee_id AND max(x.period_start,e.hire_date) BETWEEN r.effective_from AND coalesce(r.effective_to,\'9999-12-31\') WHERE p.employee_withholding_usd<>R(p.taxable_gross_usd*r.employee_withholding_rate,1000000) OR p.employer_taxes_usd<>R(p.taxable_gross_usd*r.employer_tax_rate,1000000)',n('payroll_register'))
        for field in ['wage_expense_usd','card_tips_usd','cash_tips_reported_usd','taxable_gross_usd','employee_withholding_usd','employer_taxes_usd','net_pay_usd']:
            self.check('Company payroll aggregate '+field,f'SELECT r.payroll_run_id,r.{field}-p.amount FROM payroll_runs r JOIN (SELECT payroll_run_id,sum({field}) amount FROM payroll_register GROUP BY payroll_run_id) p USING(payroll_run_id) WHERE r.{field}<>p.amount',n('payroll_runs'))
        self.check('Payroll funding excludes already paid cash tips','SELECT p.payroll_run_id,p.total_funding_usd-p.net_pay_usd-p.employee_withholding_usd-p.employer_taxes_usd FROM payroll_runs p WHERE p.total_funding_usd<>p.net_pay_usd+p.employee_withholding_usd+p.employer_taxes_usd',n('payroll_runs'))
        self.check('Payroll funding component exactly matches run',"SELECT f.payroll_funding_id,f.amount_usd-CASE WHEN f.funding_component='NET_PAY' THEN p.net_pay_usd ELSE p.employee_withholding_usd+p.employer_taxes_usd END FROM payroll_funding f JOIN payroll_runs p USING(payroll_run_id) WHERE f.amount_usd<>CASE WHEN f.funding_component='NET_PAY' THEN p.net_pay_usd ELSE p.employee_withholding_usd+p.employer_taxes_usd END",n('payroll_funding'))
        self.check('Payroll actual funding bank debit identity','SELECT f.payroll_funding_id,f.amount_usd+b.amount_usd FROM payroll_funding f JOIN bank_transactions b USING(bank_transaction_id) WHERE f.amount_usd<>-b.amount_usd OR f.actual_funding_date<>b.transaction_date OR b.source_id<>f.payroll_funding_id',n('payroll_funding'))
        self.check('Payroll pending approval contains no future actual bank values',f"SELECT payroll_funding_id,1 FROM payroll_funding WHERE (scheduled_funding_date>'{END}' AND (actual_funding_date IS NOT NULL OR bank_transaction_id IS NOT NULL OR status<>'PENDING')) OR (scheduled_funding_date<='{END}' AND (actual_funding_date IS NULL OR bank_transaction_id IS NULL))",n('payroll_funding'),'count')

    def accounting(self):
        n=self.count
        self.check('GL lines have exactly one positive debit or credit','SELECT gl_line_id,debit_usd-credit_usd FROM general_ledger WHERE debit_usd<0 OR credit_usd<0 OR (debit_usd=0 AND credit_usd=0) OR (debit_usd>0 AND credit_usd>0)',n('general_ledger'))
        self.check('Every journal balances to cent','SELECT journal_id,sum(debit_usd-credit_usd) FROM general_ledger GROUP BY journal_id HAVING sum(debit_usd-credit_usd)<>0',n('journals'))
        self.check('Every journal header has at least two ledger lines','SELECT j.journal_id,count(g.gl_line_id)-2 FROM journals j LEFT JOIN general_ledger g USING(journal_id) GROUP BY j.journal_id HAVING count(g.gl_line_id)<2',n('journals'),'count')
        self.check('GL source and date match journal header','SELECT g.gl_line_id,1 FROM general_ledger g JOIN journals j USING(journal_id) WHERE g.journal_date<>j.journal_date OR g.source_id<>j.source_id OR g.source_table<>j.source_table OR g.source_system<>j.source_system',n('general_ledger'),'count')
        # Polymorphic references are checked against actual source primary keys.
        sourcepairs=self.db.execute('SELECT DISTINCT source_table FROM journals').fetchall()
        for (table,) in sourcepairs:
            if table not in self.schemas:raise ValueError('Unknown journal source '+table)
            pk=self.schemas[table]['primary_key'][0]
            self.check('Journal source document exists: '+table,f"SELECT j.journal_id,1 FROM journals j LEFT JOIN {table} s ON j.source_id=s.{pk} WHERE j.source_table='{table}' AND s.{pk} IS NULL",f"SELECT count(*) FROM journals WHERE source_table='{table}'",'count')
        self.run('''CREATE TABLE gl_month AS SELECT substr(journal_date,1,7)||'-01' service_month,restaurant_id,account_id,sum(debit_usd) debit,sum(credit_usd) credit,sum(debit_usd-credit_usd) signed FROM general_ledger GROUP BY substr(journal_date,1,7),restaurant_id,account_id;
        CREATE INDEX ix_gl_month ON gl_month(service_month,restaurant_id,account_id);
        CREATE TABLE gl_day AS SELECT journal_date business_date,restaurant_id,account_id,sum(debit_usd-credit_usd) signed FROM general_ledger GROUP BY journal_date,restaurant_id,account_id;
        CREATE INDEX ix_gl_day ON gl_day(business_date,restaurant_id,account_id);
        ''')
        self.check('Opening trial balance balances company-wide','SELECT as_of_date,sum(balance_usd) FROM opening_trial_balance GROUP BY as_of_date HAVING sum(balance_usd)<>0',n('opening_trial_balance'))
        self.check('Opening trial balance sign','SELECT opening_balance_id,balance_usd-debit_usd+credit_usd FROM opening_trial_balance WHERE balance_usd<>debit_usd-credit_usd',n('opening_trial_balance'))
        self.check('Monthly trial balance debit/credit turnovers from GL','SELECT b.trial_balance_id,b.debit_usd-coalesce(g.debit,0) FROM monthly_trial_balance b LEFT JOIN gl_month g USING(service_month,restaurant_id,account_id) WHERE b.debit_usd<>coalesce(g.debit,0) OR b.credit_usd<>coalesce(g.credit,0)',n('monthly_trial_balance'))
        self.run('''CREATE TABLE tb_previous AS SELECT b.*,coalesce(lag(closing_balance_usd) OVER(PARTITION BY restaurant_id,account_id ORDER BY service_month),o.balance_usd,0) previous FROM monthly_trial_balance b LEFT JOIN opening_trial_balance o USING(restaurant_id,account_id);''')
        self.check('Monthly trial balance opening and closing continuity','SELECT trial_balance_id,closing_balance_usd-opening_balance_usd-debit_usd+credit_usd FROM tb_previous WHERE opening_balance_usd<>previous OR closing_balance_usd<>opening_balance_usd+debit_usd-credit_usd',n('monthly_trial_balance'))
        self.check('Monthly company trial balance balances','SELECT service_month,sum(closing_balance_usd) FROM monthly_trial_balance GROUP BY service_month HAVING sum(closing_balance_usd)<>0',24)
        self.check('Bank running balances from opening statement',"SELECT bank_transaction_id,running_balance_usd-(48000000+sum(amount_usd) OVER(ORDER BY transaction_date,bank_transaction_id ROWS UNBOUNDED PRECEDING)) FROM bank_transactions",n('bank_transactions')) if False else None
        self.run('''CREATE TABLE bank_running AS SELECT b.*,48000000+sum(amount_usd) OVER(ORDER BY transaction_date,bank_transaction_id ROWS UNBOUNDED PRECEDING) expected FROM bank_transactions b;
        CREATE TABLE bank_month AS SELECT substr(transaction_date,1,7)||'-01' service_month,sum(CASE WHEN amount_usd>0 THEN amount_usd ELSE 0 END) inflows,-sum(CASE WHEN amount_usd<0 THEN amount_usd ELSE 0 END) outflows,sum(amount_usd) net,count(*) cnt FROM bank_transactions GROUP BY substr(transaction_date,1,7);
        CREATE TABLE bank_month_running AS SELECT b.*,48000000+sum(net) OVER(ORDER BY service_month) closing FROM bank_month b;
        ''')
        self.check('Bank running balances from actual statement rows','SELECT bank_transaction_id,running_balance_usd-expected FROM bank_running WHERE running_balance_usd<>expected',n('bank_transactions'))
        self.check('Monthly statement totals and balance roll-forward','SELECT s.statement_id,s.closing_balance_usd-b.closing FROM bank_monthly_statements s JOIN bank_month_running b USING(service_month) WHERE s.inflows_usd<>b.inflows OR s.outflows_usd<>b.outflows OR s.transaction_count<>b.cnt OR s.closing_balance_usd<>b.closing OR s.opening_balance_usd<>b.closing-b.net',24)
        self.check('Bank ledger reconciles to statements monthly',"SELECT b.trial_balance_id,b.closing_balance_usd-s.closing_balance_usd FROM monthly_trial_balance b JOIN bank_monthly_statements s USING(service_month) WHERE b.restaurant_id='HQ' AND b.account_id='1000' AND b.closing_balance_usd<>s.closing_balance_usd",24)
        self.check('No bank overdrafts in chosen case','SELECT bank_transaction_id,running_balance_usd FROM bank_transactions WHERE running_balance_usd<0',n('bank_transactions'))
        self.check('Each bank transaction has exact cash ledger impact',"SELECT b.bank_transaction_id,b.amount_usd-coalesce(g.signed,0) FROM bank_transactions b LEFT JOIN (SELECT source_id,sum(debit_usd-credit_usd) signed FROM general_ledger WHERE source_table='bank_transactions' AND account_id='1000' GROUP BY source_id) g ON g.source_id=b.bank_transaction_id WHERE b.amount_usd<>coalesce(g.signed,0)",n('bank_transactions'))
        self.check('Inventory opening GL values equal paid ingredient balances',"SELECT o.restaurant_id||o.account_id,o.balance_usd-i.value FROM opening_trial_balance o JOIN (SELECT restaurant_id,inventory_account_id account_id,sum(inventory_value_usd) value FROM opening_inventory JOIN ingredients USING(ingredient_id) GROUP BY restaurant_id,inventory_account_id) i USING(restaurant_id,account_id) WHERE o.balance_usd<>i.value",9)
        self.check('Monthly GL inventory reconciles ingredient closing carrying value',"SELECT b.trial_balance_id,b.closing_balance_usd-i.value FROM monthly_trial_balance b JOIN (SELECT substr(business_date,1,7)||'-01' service_month,restaurant_id,inventory_account_id account_id,sum(closing_value_usd) value FROM inventory_daily_balances JOIN ingredients USING(ingredient_id) WHERE business_date=date(business_date,'start of month','+1 month','-1 day') GROUP BY substr(business_date,1,7),restaurant_id,inventory_account_id) i USING(service_month,restaurant_id,account_id) WHERE b.closing_balance_usd<>i.value",216)
        self.check('Inventory GL movements equal operational quantity/value ledger',"SELECT g.service_month||g.restaurant_id||g.account_id,g.signed-coalesce(m.value,0) FROM gl_month g LEFT JOIN (SELECT substr(movement_date,1,7)||'-01' service_month,restaurant_id,inventory_account_id account_id,sum(value_delta_usd) value FROM inventory_movements JOIN ingredients USING(ingredient_id) GROUP BY substr(movement_date,1,7),restaurant_id,inventory_account_id) m USING(service_month,restaurant_id,account_id) WHERE g.account_id IN ('1100','1110','1120') AND g.signed<>coalesce(m.value,0)",216)
        self.account_subledgers()

    def account_subledgers(self):
        # Recompute cumulative source subledgers independently for every month/site.
        self.check('Daily GL POS gross food/beverage/modifier revenue',"SELECT s.restaurant_id||s.business_date||s.account_id,s.value+coalesce(g.signed,0) FROM (SELECT h.restaurant_id,l.business_date,CASE WHEN i.category='Food' THEN '4000' ELSE '4010' END account_id,sum(CASE WHEN l.line_status='SERVED' THEN l.menu_gross_usd ELSE 0 END) value FROM check_lines l JOIN checks h USING(check_id) JOIN menu_items i USING(menu_item_id) GROUP BY h.restaurant_id,l.business_date,i.category UNION ALL SELECT h.restaurant_id,l.business_date,'4020',sum(CASE WHEN l.line_status='SERVED' THEN l.modifier_gross_usd ELSE 0 END) FROM check_lines l JOIN checks h USING(check_id) GROUP BY h.restaurant_id,l.business_date) s LEFT JOIN gl_day g USING(restaurant_id,business_date,account_id) WHERE s.value<>-coalesce(g.signed,0)",6570)
        for account,field in [('4090','discount_usd'),('4091','comp_usd'),('4092','refunds_net_usd')]:
            self.check('Daily GL contra revenue '+account,f"SELECT c.close_id,c.{field}-coalesce(g.signed,0) FROM day_closings c LEFT JOIN gl_day g ON g.business_date=c.business_date AND g.restaurant_id=c.restaurant_id AND g.account_id='{account}' WHERE c.{field}<>coalesce(g.signed,0)",self.count('day_closings'))
        self.check('Monthly AP liability from bills credits and actual cash applications',"SELECT t.trial_balance_id,t.closing_balance_usd+coalesce((SELECT sum(b.gross_amount_usd) FROM vendor_bills b WHERE b.restaurant_id=t.restaurant_id AND b.bill_date<=date(t.service_month,'+1 month','-1 day')),0)-coalesce((SELECT sum(c.amount_usd) FROM vendor_credits c WHERE c.restaurant_id=t.restaurant_id AND c.credit_date<=date(t.service_month,'+1 month','-1 day')),0)-coalesce((SELECT sum(p.amount_usd) FROM vendor_payments p WHERE p.restaurant_id=t.restaurant_id AND p.payment_date<=date(t.service_month,'+1 month','-1 day')),0) FROM monthly_trial_balance t WHERE t.account_id='2000' AND t.closing_balance_usd<>-coalesce((SELECT sum(b.gross_amount_usd) FROM vendor_bills b WHERE b.restaurant_id=t.restaurant_id AND b.bill_date<=date(t.service_month,'+1 month','-1 day')),0)+coalesce((SELECT sum(c.amount_usd) FROM vendor_credits c WHERE c.restaurant_id=t.restaurant_id AND c.credit_date<=date(t.service_month,'+1 month','-1 day')),0)+coalesce((SELECT sum(p.amount_usd) FROM vendor_payments p WHERE p.restaurant_id=t.restaurant_id AND p.payment_date<=date(t.service_month,'+1 month','-1 day')),0)",96)
        self.check('Monthly drawer GL balance equals fixed counted cash float',"SELECT trial_balance_id,closing_balance_usd-40000 FROM monthly_trial_balance WHERE account_id='1010' AND restaurant_id<>'HQ' AND closing_balance_usd<>40000",72)
        # Source deltas, accumulated month by month in Python integer dictionaries.
        source=defaultdict(Counter)
        def add(d,r,a,value):source[(d[:7]+'-01',r)][a]+=int(value)
        for r,d,g,f,n in self.db.execute('SELECT restaurant_id,transaction_date,gross_amount_usd,fee_usd,net_amount_usd FROM processor_transactions'):add(d,r,'1030',n);add(d,r,'6160',f)
        for r,d,amount in self.db.execute('SELECT restaurant_id,bank_arrival_date,payout_usd FROM processor_payouts WHERE bank_arrival_date IS NOT NULL'):add(d,r,'1030',-amount)
        for platform,account in [('doordash','1040'),('ubereats','1050')]:
            for r,d,net,commission,promo,adjust in self.db.execute(f'SELECT restaurant_id,transaction_date,net_receivable_usd,commission_usd,promotion_fee_usd,service_adjustment_usd FROM {platform}_transactions'):
                add(d,r,account,net);add(d,r,'6170',commission);add(d,r,'6180',promo);add(d,r,'6210',adjust)
            for r,d,amount in self.db.execute(f'SELECT restaurant_id,bank_arrival_date,payout_usd FROM {platform}_settlements WHERE bank_arrival_date IS NOT NULL'):add(d,r,account,-amount)
        for r,d,amount,arrival in self.db.execute('SELECT restaurant_id,dispatch_date,deposit_bag_usd,bank_arrival_date FROM cash_deposits'):
            add(d,r,'1020',amount)
            if arrival:add(arrival,r,'1020',-amount)
        for r,d,tax,refund,cardtip,cashtip in self.db.execute('SELECT restaurant_id,business_date,direct_sales_tax_usd,refunds_tax_usd,card_tips_usd,cash_tips_usd FROM day_closings'):
            add(d,r,'2030',-tax+refund);add(d,r,'2020',-cardtip)
        for r,d,amount in self.db.execute('SELECT restaurant_id,actual_payment_date,net_tax_payable_usd FROM sales_tax_obligations WHERE actual_payment_date IS NOT NULL'):add(d,r,'2030',amount)
        for r,d,hourly,salary,er,net,ee,ct in self.db.execute('SELECT p.restaurant_id,x.period_end,p.regular_wages_usd+p.overtime_wages_usd,p.salary_wages_usd,p.employer_taxes_usd,p.net_pay_usd,p.employee_withholding_usd,p.card_tips_usd FROM payroll_register p JOIN payroll_runs x USING(payroll_run_id)'):
            for a,v in [('6000',hourly),('6010',salary),('6020',er),('2010',-net),('2011',-ee-er),('2020',ct)]:add(d,r,a,v)
        for r,d,net,tax in self.db.execute('SELECT p.restaurant_id,x.funding_date,p.net_pay_usd,p.employee_withholding_usd+p.employer_taxes_usd FROM payroll_register p JOIN payroll_runs x USING(payroll_run_id) WHERE x.funding_date IS NOT NULL'):
            add(d,r,'2010',net);add(d,r,'2011',tax)
        for r,d,amount in self.db.execute('SELECT restaurant_id,business_date,waste_cost_usd FROM waste_events'):add(d,r,'5030',amount)
        for r,d,amount in self.db.execute('SELECT restaurant_id,count_date,adjustment_value_usd FROM physical_stock_counts'):add(d,r,'5050',-amount)
        for r,d,amount,typ,account in self.db.execute('SELECT u.restaurant_id,u.business_date,u.usage_cost_usd,u.usage_type,i.cogs_account_id FROM theoretical_usage u JOIN ingredients i USING(ingredient_id)'):add(d,r,'5040' if typ=='STAFF_MEAL' else account,amount)
        accounts=['1030','1040','1050','1020','2030','2020','2010','2011']
        expense_accounts=['6160','6170','6180','6210','6000','6010','6020','5000','5010','5020','5030','5040','5050']
        months=sorted({x[0] for x in source});rids=['R01','R02','R03','HQ'];cumulative=defaultdict(int)
        actualtb={(m,r,a):b for m,r,a,b in self.db.execute('SELECT service_month,restaurant_id,account_id,closing_balance_usd FROM monthly_trial_balance')}
        actualgl={(m,r,a):b for m,r,a,b in self.db.execute('SELECT service_month,restaurant_id,account_id,signed FROM gl_month')}
        for a in accounts+expense_accounts:
            failures=[];maxdiff=0
            for m in months:
                for r in rids:
                    v=source[(m,r)][a]
                    if a in accounts:
                        cumulative[(r,a)]+=v;expected=cumulative[(r,a)];actual=actualtb[(m,r,a)]
                    else:expected=v;actual=actualgl.get((m,r,a),0)
                    if expected!=actual:failures.append(f'{m}/{r}: {actual-expected}');maxdiff=max(maxdiff,abs(actual-expected))
            self.record('Independent monthly source-to-GL reconciliation: '+a,len(months)*len(rids),len(failures),maxdiff,'; '.join(failures[:4]),'cents')
        self.check('Cash tip liability fully paid from daily drawers',"SELECT trial_balance_id,closing_balance_usd FROM monthly_trial_balance WHERE account_id='2021' AND closing_balance_usd<>0",96)

    def other_finance(self):
        n=self.count
        self.check('Accounting bill recognition matches account distributions',"SELECT l.bill_id||l.account_id,l.amount-coalesce(g.amount,0) FROM (SELECT bill_id,account_id,sum(amount_usd) amount FROM vendor_bill_lines GROUP BY bill_id,account_id) l LEFT JOIN (SELECT source_id bill_id,account_id,sum(debit_usd-credit_usd) amount FROM general_ledger WHERE source_table='vendor_bills' AND account_id<>'2000' GROUP BY source_id,account_id) g USING(bill_id,account_id) WHERE l.amount<>coalesce(g.amount,0)",n('vendor_bill_lines'))
        self.check('Recurring billed obligations mirror exactly one accounting expense','SELECT o.obligation_id,o.amount_usd-b.gross_amount_usd FROM recurring_obligations o JOIN vendor_bills b ON o.existing_bill_id=b.bill_id WHERE o.amount_usd<>b.gross_amount_usd OR o.service_month<>b.service_month OR o.restaurant_id<>b.restaurant_id',n('recurring_obligations'))
        self.check('Future recurring cycles are not actual bills',f"SELECT obligation_id,1 FROM recurring_obligations WHERE (service_month>'{END}' AND (existing_bill_id IS NOT NULL OR status<>'NOT_BILLED')) OR (service_month<='{END}' AND existing_bill_id IS NULL)",n('recurring_obligations'),'count')
        for platform,account in [('meta_ads','6190'),('google_ads','6191')]:
            self.check(platform+' daily spend equals billed media','SELECT b.billing_id,b.amount_usd-a.amount FROM '+platform+'_billing b JOIN (SELECT billing_id,sum(spend_usd) amount FROM '+platform+'_daily GROUP BY billing_id) a USING(billing_id) JOIN vendor_bills v ON b.accounting_bill_id=v.bill_id WHERE b.amount_usd<>a.amount OR b.amount_usd<>v.gross_amount_usd OR b.service_month<>v.service_month',n(platform+'_billing'))
            self.check(platform+' expense recognized exactly once monthly',f"SELECT a.service_month||a.restaurant_id,a.amount-coalesce(g.signed,0) FROM (SELECT substr(activity_date,1,7)||'-01' service_month,restaurant_id,sum(spend_usd) amount FROM {platform}_daily GROUP BY substr(activity_date,1,7),restaurant_id) a LEFT JOIN gl_month g ON a.service_month=g.service_month AND a.restaurant_id=g.restaurant_id AND g.account_id='{account}' WHERE a.amount<>coalesce(g.signed,0)",72)
        self.check('Debt installment principal interest total and decline','SELECT debt_schedule_id,closing_principal_usd-opening_principal_usd+principal_usd FROM debt_schedule WHERE closing_principal_usd<>opening_principal_usd-principal_usd OR interest_usd<>R(opening_principal_usd*900,120000) OR total_payment_usd<>principal_usd+interest_usd',n('debt_schedule'))
        self.run('CREATE TABLE debt_previous AS SELECT d.*,lag(closing_principal_usd) OVER(ORDER BY payment_due_date) previous FROM debt_schedule d;')
        self.check('Debt schedule principal continuity','SELECT debt_schedule_id,opening_principal_usd-previous FROM debt_previous WHERE previous IS NOT NULL AND opening_principal_usd<>previous',n('debt_schedule'))
        self.check('Debt actual bank service matches scheduled payment','SELECT d.debt_schedule_id,d.total_payment_usd+b.amount_usd FROM debt_schedule d JOIN bank_transactions b USING(bank_transaction_id) WHERE d.total_payment_usd<>-b.amount_usd OR d.actual_payment_date<>b.transaction_date',n('debt_schedule'))
        self.check('Future debt rows contain no invented payment',f"SELECT debt_schedule_id,1 FROM debt_schedule WHERE (payment_due_date>'{END}' AND (actual_payment_date IS NOT NULL OR bank_transaction_id IS NOT NULL OR schedule_status<>'CONTRACTUAL_FUTURE')) OR (payment_due_date<='{END}' AND actual_payment_date IS NULL)",n('debt_schedule'),'count')
        self.check('Debt closing GL principal equals paid principal schedule',"SELECT b.trial_balance_id,b.closing_balance_usd+42000000-coalesce((SELECT sum(d.principal_usd) FROM debt_schedule d WHERE d.actual_payment_date<=date(b.service_month,'+1 month','-1 day')),0) FROM monthly_trial_balance b WHERE b.account_id='2040' AND b.restaurant_id='HQ' AND b.closing_balance_usd<>-42000000+coalesce((SELECT sum(d.principal_usd) FROM debt_schedule d WHERE d.actual_payment_date<=date(b.service_month,'+1 month','-1 day')),0)",24)
        self.check('Monthly interest expense equals contractual actual payments',"SELECT g.service_month,g.signed-coalesce(d.amount,0) FROM gl_month g LEFT JOIN (SELECT substr(actual_payment_date,1,7)||'-01' service_month,sum(interest_usd) amount FROM debt_schedule WHERE actual_payment_date IS NOT NULL GROUP BY substr(actual_payment_date,1,7)) d USING(service_month) WHERE g.account_id='6400' AND g.signed<>coalesce(d.amount,0)",24)
        self.check('Owner distributions reconcile bank and equity debit','SELECT o.distribution_id,o.amount_usd+b.amount_usd FROM owner_distributions o JOIN bank_transactions b USING(bank_transaction_id) JOIN (SELECT source_id,sum(debit_usd-credit_usd) amount FROM general_ledger WHERE account_id=\'3100\' GROUP BY source_id) g ON g.source_id=o.bank_transaction_id WHERE o.amount_usd<>-b.amount_usd OR o.amount_usd<>g.amount',n('owner_distributions'))
        self.check('Depreciation amount and asset net book value','SELECT d.depreciation_id,d.net_book_value_usd-a.original_cost_usd+d.accumulated_depreciation_usd FROM depreciation_schedule d JOIN equipment_assets a USING(asset_id) WHERE d.depreciation_usd<>R(a.original_cost_usd,CAST(a.useful_life_months AS INTEGER)) OR d.net_book_value_usd<>a.original_cost_usd-d.accumulated_depreciation_usd OR d.service_month<a.depreciation_start_date OR d.service_month>\'2026-10-01\'',n('depreciation_schedule'))
        self.check('Acquired equipment cost matches capitalized bill','SELECT a.asset_id,a.original_cost_usd-b.gross_amount_usd FROM equipment_assets a JOIN vendor_bills b ON a.accounting_bill_id=b.bill_id WHERE a.original_cost_usd<>b.gross_amount_usd OR a.acquisition_date<>b.bill_date OR b.bill_type<>\'EQUIPMENT\'',n('equipment_assets'))
        self.check('Opening assets depreciation history matches opening carrying value',"SELECT asset_id,opening_accumulated_depreciation_usd-R(original_cost_usd,CAST(useful_life_months AS INTEGER))*((2024-CAST(substr(depreciation_start_date,1,4) AS INTEGER))*12+11-CAST(substr(depreciation_start_date,6,2) AS INTEGER)) FROM equipment_assets WHERE accounting_bill_id IS NULL AND (acquisition_date>depreciation_start_date OR opening_accumulated_depreciation_usd<>R(original_cost_usd,CAST(useful_life_months AS INTEGER))*((2024-CAST(substr(depreciation_start_date,1,4) AS INTEGER))*12+11-CAST(substr(depreciation_start_date,6,2) AS INTEGER)))",n('equipment_assets'))
        self.check('Depreciation GL equals saved asset schedule',"SELECT d.service_month||d.restaurant_id,d.amount-coalesce(g.signed,0) FROM (SELECT service_month,restaurant_id,sum(depreciation_usd) amount FROM depreciation_schedule GROUP BY service_month,restaurant_id) d LEFT JOIN gl_month g ON d.service_month=g.service_month AND d.restaurant_id=g.restaurant_id AND g.account_id='6300' WHERE d.amount<>coalesce(g.signed,0)",72)
        self.check('Direct sales tax monthly collectible amount','SELECT t.tax_obligation_id,t.net_tax_payable_usd-d.amount FROM sales_tax_obligations t JOIN (SELECT restaurant_id,substr(business_date,1,7)||\'-01\' service_month,sum(direct_sales_tax_usd-refunds_tax_usd) amount FROM day_closings GROUP BY restaurant_id,substr(business_date,1,7)) d USING(restaurant_id,service_month) WHERE t.net_tax_payable_usd<>d.amount OR t.net_tax_payable_usd<>t.direct_tax_collected_usd-t.direct_tax_refunded_usd',n('sales_tax_obligations'))
        self.check('Tax actual remittance bank identity','SELECT t.tax_obligation_id,t.net_tax_payable_usd+b.amount_usd FROM sales_tax_obligations t JOIN bank_transactions b USING(bank_transaction_id) WHERE t.net_tax_payable_usd<>-b.amount_usd OR t.actual_payment_date<>b.transaction_date',n('sales_tax_obligations'))
        self.check('Budget has 24 full months and four reporting entities','SELECT restaurant_id,count(DISTINCT service_month)-24 FROM approved_budget GROUP BY restaurant_id HAVING count(DISTINCT service_month)<>24',4,'count')
        self.check('Budget immutable approval/version relationship','SELECT b.budget_line_id,1 FROM approved_budget b JOIN budget_versions v USING(budget_version_id) WHERE b.approved_date<>v.approved_date OR v.status<>\'APPROVED_ORIGINAL\' OR b.service_month<v.first_service_month OR b.service_month>v.last_service_month',n('approved_budget'),'count')
        self.check('Budget sign follows account classification',"SELECT b.budget_line_id,b.budget_amount_usd FROM approved_budget b JOIN chart_of_accounts a USING(account_id) WHERE (a.account_type='Revenue' AND b.budget_amount_usd>0) OR (a.account_type IN ('Expense','ContraRevenue') AND b.budget_amount_usd<0)",n('approved_budget'))
        for t,s in self.schemas.items():
            for field in s['fields']:
                if 'email' in field:self.check('Synthetic contact domain: '+t+'.'+field,f"SELECT rowid,1 FROM {t} WHERE {field} IS NOT NULL AND lower({field}) NOT LIKE '%@example.com'",n(t),'count')
        self.commitment_checks()

    def commitment_checks(self):
        self.check('Commitment dates after snapshot with positive explicit direction',f"SELECT commitment_id,1 FROM cash_commitments WHERE expected_cash_date<='{END}' OR as_of_date<>'{END}' OR amount_usd<=0 OR direction NOT IN ('INFLOW','OUTFLOW')",self.count('cash_commitments'),'count')
        self.check('Commitment overlap keys unique','SELECT overlap_key,count(*)-1 FROM cash_commitments GROUP BY overlap_key HAVING count(*)<>1',self.count('cash_commitments'),'count')
        tables=self.db.execute('SELECT DISTINCT source_table FROM cash_commitments').fetchall()
        for (t,) in tables:
            pk=self.schemas[t]['primary_key'][0]
            self.check('Commitment references existing source '+t,f"SELECT c.commitment_id,1 FROM cash_commitments c LEFT JOIN {t} s ON c.source_id=s.{pk} WHERE c.source_table='{t}' AND s.{pk} IS NULL",f"SELECT count(*) FROM cash_commitments WHERE source_table='{t}'",'count')
        for t,pk,field,datefield,predicate in [('bill_payment_schedule','bill_schedule_id','amount_usd','agreed_payment_date','s.actual_payment_date IS NULL'),('payroll_funding','payroll_funding_id','amount_usd','scheduled_funding_date','s.actual_funding_date IS NULL'),('sales_tax_obligations','tax_obligation_id','net_tax_payable_usd','due_date','s.actual_payment_date IS NULL'),('debt_schedule','debt_schedule_id','total_payment_usd','payment_due_date','s.actual_payment_date IS NULL'),('recurring_obligations','obligation_id','amount_usd','due_date','s.existing_bill_id IS NULL'),('processor_payouts','payout_id','payout_usd','expected_bank_date','s.bank_arrival_date IS NULL'),('doordash_settlements','settlement_id','payout_usd','expected_bank_date','s.bank_arrival_date IS NULL'),('ubereats_settlements','settlement_id','payout_usd','expected_bank_date','s.bank_arrival_date IS NULL'),('cash_deposits','deposit_id','deposit_bag_usd','expected_bank_date','s.bank_arrival_date IS NULL')]:
            self.check('Open source commitment amount/date coverage '+t,f"SELECT s.{pk},s.{field}-coalesce(c.amount_usd,0) FROM {t} s LEFT JOIN cash_commitments c ON c.source_table='{t}' AND c.source_id=s.{pk} WHERE {predicate} AND (c.commitment_id IS NULL OR c.amount_usd<>s.{field} OR c.expected_cash_date<>s.{datefield})",f'SELECT count(*) FROM {t} s WHERE {predicate}')
        self.check('Open PO quantities remain distinct from already billed receipts',"SELECT c.commitment_id,c.amount_usd-R(l.outstanding_base_qty*l.pack_price_usd,R(l.ordered_base_qty*1000000,l.ordered_pack_qty)) FROM cash_commitments c JOIN purchase_order_lines l ON c.source_id=l.purchase_order_line_id WHERE c.source_table='purchase_order_lines' AND (l.outstanding_base_qty<=0 OR c.amount_usd<>R(l.outstanding_base_qty*l.pack_price_usd,R(l.ordered_base_qty*1000000,l.ordered_pack_qty)))",'SELECT count(*) FROM cash_commitments WHERE source_table=\'purchase_order_lines\'')
        self.check('Cutoff has real open AP payroll tax and unreceived PO commitments',"SELECT required,1 FROM (SELECT 'OPEN_AP' required UNION ALL SELECT 'APPROVED_PAYROLL' UNION ALL SELECT 'ACCRUED_SALES_TAX' UNION ALL SELECT 'UNRECEIVED_PO' UNION ALL SELECT 'PENDING_SETTLEMENT' UNION ALL SELECT 'CONTRACTUAL_DEBT' UNION ALL SELECT 'FUTURE_CONTRACT_CYCLE') r WHERE NOT EXISTS(SELECT 1 FROM cash_commitments c WHERE c.commitment_type=r.required)",7,'count')

    def manifest(self):
        file=self.root/'metadata'/'file_manifest.csv'
        if not file.exists():
            self.record('Payload SHA256 manifest',1,1,examples='metadata/file_manifest.csv missing');return
        errors=[];n=0;sourcefound=set()
        with file.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                n+=1;rel=r['relative_path'];p=self.root/rel
                if rel.startswith('sources/'):sourcefound.add(rel)
                if not p.is_file():errors.append(rel+' missing');continue
                h=hashlib.sha256()
                with p.open('rb') as b:
                    for chunk in iter(lambda:b.read(4*1024*1024),b''):h.update(chunk)
                if h.hexdigest()!=r['sha256'] or p.stat().st_size!=int(r['size_bytes']):errors.append(rel+' hash/size mismatch')
        self.record('Payload SHA256 manifest',n,len(errors),examples='; '.join(errors[:4]))
        declared={f for s in self.schemas.values() for f in s['physical_files']}
        self.record('Manifest covers every declared source CSV',len(declared),len(declared^sourcefound),examples=str(sorted(declared^sourcefound)[:4]))

    def controls(self,write=False):
        # Values always derive from CSV-loaded source facts, never from control file.
        gl=defaultdict(Counter);tb=defaultdict(Counter);bud=defaultdict(Counter)
        for m,r,a,v in self.db.execute('SELECT service_month,restaurant_id,account_id,signed FROM gl_month'):gl[(m,r)][a]+=v;gl[(m,'COMPANY')][a]+=v
        for m,r,a,v in self.db.execute('SELECT service_month,restaurant_id,account_id,closing_balance_usd FROM monthly_trial_balance'):tb[(m,r)][a]+=v;tb[(m,'COMPANY')][a]+=v
        for m,r,a,v in self.db.execute('SELECT service_month,restaurant_id,account_id,budget_amount_usd FROM approved_budget'):bud[(m,r)][a]+=v;bud[(m,'COMPANY')][a]+=v
        ops=defaultdict(Counter)
        def add(m,r,k,v):ops[(m,r)][k]+=v;ops[(m,'COMPANY')][k]+=v
        for r,d,closed,voided,guests,gross,disc,comp,net,ref,ct,cs in self.db.execute('SELECT restaurant_id,business_date,closed_check_count,void_check_count,guest_count,gross_sales_usd,discount_usd,comp_usd,net_sales_usd,refunds_net_usd,card_tips_usd,cash_tips_usd FROM day_closings'):
            for k,v in [('closed_check_count',closed),('void_check_count',voided),('guest_count',guests),('gross_sales_usd',gross),('discount_usd',disc),('comp_usd',comp),('refunds_usd',ref),('card_tips_collected_usd',ct),('cash_tips_collected_usd',cs)]:add(d[:7]+'-01',r,k,v)
        for r,d,paid,ot in self.db.execute('SELECT restaurant_id,business_date,paid_minutes,overtime_minutes FROM timesheets'):add(d[:7]+'-01',r,'paid_minutes',paid);add(d[:7]+'-01',r,'overtime_minutes',ot)
        for r,d,amount in self.db.execute('SELECT restaurant_id,receipt_date,accepted_value_usd FROM receipts'):add(d[:7]+'-01',r,'received_inventory_usd',amount)
        for r,d,amount in self.db.execute('SELECT restaurant_id,payment_date,amount_usd FROM vendor_payments'):add(d[:7]+'-01',r,'vendor_cash_paid_usd',amount)
        for r,d,amount in self.db.execute('SELECT restaurant_id,transaction_date,amount_usd FROM bank_transactions'):add(d[:7]+'-01',r,'bank_inflows_usd' if amount>0 else 'bank_outflows_usd',abs(amount))
        account_metrics={'food_theoretical_cost_usd':'5000','beverage_theoretical_cost_usd':'5010','packaging_cost_usd':'5020','waste_cost_usd':'5030','staff_meals_cost_usd':'5040','count_variance_cost_usd':'5050','hourly_wages_usd':'6000','salary_wages_usd':'6010','employer_payroll_taxes_usd':'6020','benefits_usd':'6030','rent_usd':'6100','utilities_usd':'6110','card_fees_usd':'6160','marketplace_commissions_usd':'6170','marketplace_promotion_fees_usd':'6180','meta_ad_spend_usd':'6190','google_ad_spend_usd':'6191','depreciation_usd':'6300','interest_usd':'6400'}
        balances={'drawer_cash_usd':('1010',1),'cash_in_transit_usd':('1020',1),'processor_clearing_usd':('1030',1),'doordash_clearing_usd':('1040',1),'ubereats_clearing_usd':('1050',1),'ap_balance_usd':('2000',-1),'payroll_net_payable_usd':('2010',-1),'payroll_tax_payable_usd':('2011',-1),'card_tip_liability_usd':('2020',-1),'sales_tax_payable_usd':('2030',-1),'debt_principal_usd':('2040',-1)}
        result=[]
        for m in sorted({x[0] for x in gl}):
            for rid in ['COMPANY','R01','R02','R03']:
                g=gl[(m,rid)];t=tb[(m,rid)];b=bud[(m,rid)]
                row=dict(service_month=m,entity_type='COMPANY' if rid=='COMPANY' else 'RESTAURANT',entity_id=rid)
                for k in ['closed_check_count','void_check_count','guest_count','paid_minutes','overtime_minutes']:row[k]=ops[(m,rid)][k]
                for k in ['gross_sales_usd','discount_usd','comp_usd','refunds_usd','card_tips_collected_usd','cash_tips_collected_usd','received_inventory_usd','vendor_cash_paid_usd','bank_inflows_usd','bank_outflows_usd']:row[k]=money(ops[(m,rid)][k])
                row['net_revenue_usd']=money(-sum(v for a,v in g.items() if a.startswith('4')))
                for k,a in account_metrics.items():row[k]=money(g[a])
                row['total_ingredient_cost_usd']=money(sum(v for a,v in g.items() if a.startswith('5')))
                row['total_labor_cost_usd']=money(sum(g[a] for a in ['6000','6010','6020','6030']))
                row['pretax_income_usd']=money(-sum(v for a,v in g.items() if a[0] in '456'))
                row['budget_net_revenue_usd']=money(-sum(v for a,v in b.items() if a.startswith('4')))
                row['budget_pretax_income_usd']=money(-sum(b.values()))
                for k,(a,sgn) in balances.items():row[k]=money(t[a]*sgn)
                row['inventory_value_usd']=money(sum(t[a] for a in ['1100','1110','1120']))
                row['central_bank_balance_usd']=money(t['1000']) if rid=='COMPANY' else ''
                result.append(row)
        out=self.root/'validation';out.mkdir(exist_ok=True);path=out/'monthly_control_totals.csv'
        if write:
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(result[0]),lineterminator='\n');w.writeheader();w.writerows(result)
        errors=[]
        if path.exists():
            with path.open(encoding='utf-8-sig',newline='') as f:saved=list(csv.DictReader(f))
            if len(saved)!=len(result):errors.append('Control row count differs')
            for actual,expected in zip(saved,result):
                for k,v in expected.items():
                    if actual.get(k)!=str(v):errors.append(f'{expected["service_month"]}/{expected["entity_id"]}/{k}: {actual.get(k)} vs {v}')
        else:errors.append('Control file missing; initialize deliberately with --write-controls')
        self.record('Monthly company/site controls independently recomputed',len(result)*len(result[0]),len(errors),examples='; '.join(errors[:4]))
        return result

    def save(self):
        out=self.root/'validation';out.mkdir(exist_ok=True)
        with (out/'validation_report.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(self.report[0]),lineterminator='\n');w.writeheader();w.writerows(self.report)
        summary=dict(actual_start=START,actual_end=END,snapshot_date=END,source_tables=len(self.schemas),source_files=len(self.file_counts),source_rows=sum(self.counts.values()),check_groups=len(self.report),evaluated_conditions=sum(x['evaluated'] for x in self.report),failed_groups=sum(x['status']=='FAIL' for x in self.report),failures=sum(x['failures'] for x in self.report),money_tolerance_usd='0.00',quantity_tolerance_base_units='0.000000',quantity_storage_resolution='0.000001',verifier='Independent Python stdlib / saved CSV / integer SQLite',control_rows=96)
        (out/'validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary),flush=True)
        return summary

    def mutation_tests(self):
        """Exercise the actual registered rules, using rollback-only scratch DB mutations."""
        enable_mutation_rollback(self.db)
        definitions=[
        ('IMPOSSIBLE_DINING_CAPACITY','Dine-in intervals never exceed physical seating capacity',["UPDATE checks SET guests=1000 WHERE rowid=(SELECT min(rowid) FROM checks WHERE status='CLOSED' AND channel='DINE_IN')"]),
        ('DUPLICATE_PRIMARY_KEY','Primary key populated and unique: checks',["INSERT INTO checks SELECT * FROM checks LIMIT 1"]),
        ('ORPHAN_POS_LINE','Foreign key check_lines.check_id -> checks.check_id',["UPDATE check_lines SET check_id='NONEXISTENT-CHECK' WHERE rowid=(SELECT min(rowid) FROM check_lines)"]),
        ('CHECK_TOTAL_PLUS_CENT','Original check total includes sales tax and tips',["UPDATE checks SET total_due_usd=total_due_usd+1 WHERE rowid=(SELECT min(rowid) FROM checks)"]),
        ('MARKETPLACE_SALES_PLUS_CENT','doordash POS order identity and totals',["UPDATE doordash_orders SET merchant_net_sales_usd=merchant_net_sales_usd+1 WHERE rowid=(SELECT min(rowid) FROM doordash_orders)"]),
        ('PROCESSOR_FEE_PLUS_CENT','Processor fee and net arithmetic',["UPDATE processor_transactions SET fee_usd=fee_usd+1 WHERE rowid=(SELECT min(rowid) FROM processor_transactions)"]),
        ('DRAWER_COUNT_PLUS_CENT','Drawer expected count and shortage/overage',["UPDATE cash_drawer_closings SET counted_before_deposit_usd=counted_before_deposit_usd+1 WHERE rowid=(SELECT min(rowid) FROM cash_drawer_closings)"]),
        ('AP_BALANCE_PLUS_CENT','AP credits cash applications and remaining balance',["UPDATE vendor_bills SET open_balance_usd=open_balance_usd+1 WHERE rowid=(SELECT min(rowid) FROM vendor_bills)"]),
        ('NEGATIVE_INGREDIENT_STOCK','No negative stock quantity or inventory carrying value',["UPDATE inventory_movements SET balance_after_qty=-1 WHERE rowid=(SELECT min(rowid) FROM inventory_movements)"]),
        ('WAC_ISSUE_COST_PLUS_CENT','Perpetual weighted-average issue cost to cent',["UPDATE inventory_movements SET value_delta_usd=value_delta_usd+1 WHERE inventory_movement_id=(SELECT inventory_movement_id FROM inventory_movements WHERE quantity_delta_qty<0 LIMIT 1)","UPDATE movement_previous SET value_delta_usd=value_delta_usd+1 WHERE inventory_movement_id=(SELECT inventory_movement_id FROM inventory_movements WHERE quantity_delta_qty<0 LIMIT 1)"]),
        ('RECIPE_RAW_QTY_PLUS_MICROUNIT','Recipe edible yield to raw base quantity',["UPDATE recipe_components SET raw_per_portion_qty=raw_per_portion_qty+1 WHERE rowid=(SELECT min(rowid) FROM recipe_components)"]),
        ('TRANSFER_VALUE_LEAK','Paired transfers preserve quantity and carrying value',["UPDATE inventory_movements SET value_delta_usd=value_delta_usd-1 WHERE inventory_movement_id=(SELECT out_movement_id FROM inventory_transfers LIMIT 1)"]),
        ('CLOCK_PAID_MINUTES_PLUS_ONE','Actual shift minutes from clock timestamps and breaks',["UPDATE timesheets SET paid_minutes=paid_minutes+1 WHERE rowid=(SELECT min(rowid) FROM timesheets)"]),
        ('PAYROLL_NET_PLUS_CENT','Payroll wage taxable gross and net pay arithmetic',["UPDATE payroll_register SET net_pay_usd=net_pay_usd+1 WHERE rowid=(SELECT min(rowid) FROM payroll_register)"]),
        ('PAYROLL_SALARY_PLUS_CENT','Payroll salary pro rata at agreed effective annual rate',["UPDATE payroll_register SET salary_wages_usd=salary_wages_usd+1 WHERE rowid=(SELECT min(rowid) FROM payroll_register WHERE pay_type='SALARY')"]),
        ('PAYROLL_CASH_TIP_DOUBLE_PAY','Payroll wage taxable gross and net pay arithmetic',["UPDATE payroll_register SET net_pay_usd=net_pay_usd+cash_tips_reported_usd WHERE rowid=(SELECT min(rowid) FROM payroll_register WHERE cash_tips_reported_usd>0)"]),
        ('GL_UNBALANCED_ONE_CENT','Every journal balances to cent',["UPDATE general_ledger SET credit_usd=credit_usd+1 WHERE rowid=(SELECT min(rowid) FROM general_ledger)"]),
        ('BANK_AMOUNT_PLUS_CENT','Each bank transaction has exact cash ledger impact',["UPDATE bank_transactions SET amount_usd=amount_usd+1 WHERE rowid=(SELECT min(rowid) FROM bank_transactions)"]),
        ('FUTURE_BANK_ACTUAL','Actual-date window: bank_transactions',["UPDATE bank_transactions SET transaction_date='2026-11-02' WHERE rowid=(SELECT min(rowid) FROM bank_transactions)"]),
        ('AD_SPEND_PLUS_CENT','meta_ads daily spend equals billed media',["UPDATE meta_ads_daily SET spend_usd=spend_usd+1 WHERE rowid=(SELECT min(rowid) FROM meta_ads_daily)"]),
        ('TAX_OBLIGATION_PLUS_CENT','Direct sales tax monthly collectible amount',["UPDATE sales_tax_obligations SET net_tax_payable_usd=net_tax_payable_usd+1 WHERE rowid=(SELECT min(rowid) FROM sales_tax_obligations)"]),
        ('DUPLICATE_CASH_COMMITMENT','Commitment overlap keys unique',["INSERT INTO cash_commitments SELECT * FROM cash_commitments LIMIT 1"]),
        ]
        rules=dict(self.rules);result=[];failures=0
        for case,name,updates in definitions:
            sql=rules[name]
            before=self.db.execute('SELECT count(*) FROM ('+sql+')').fetchone()[0]
            self.db.execute('SAVEPOINT mutation')
            for update in updates:self.db.execute(update)
            after=self.db.execute('SELECT count(*) FROM ('+sql+')').fetchone()[0]
            self.db.execute('ROLLBACK TO mutation');self.db.execute('RELEASE mutation')
            restored=self.db.execute('SELECT count(*) FROM ('+sql+')').fetchone()[0]
            passed=before==0 and after>0 and restored==0
            if not passed:failures+=1
            result.append(dict(mutation_id=case,detecting_check=name,baseline_violations=before,mutated_violations=after,after_rollback_violations=restored,status='PASS' if passed else 'FAIL',scope='ROLLBACK_ONLY_SCRATCH_SQLITE_NO_SOURCE_CSV_CHANGED'))
        out=self.root/'validation';out.mkdir(exist_ok=True)
        with (out/'mutation_test_report.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(result[0]),lineterminator='\n');w.writeheader();w.writerows(result)
        self.record('Verifier sensitivity to controlled scratch mutations',len(result),failures,examples='All mutations rolled back; saved source CSV unchanged.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path,nargs='?',default=Path(__file__).resolve().parents[1])
    parser.add_argument('--scratch',type=Path,default=Path.cwd()/'work'/'verification')
    parser.add_argument('--write-controls',action='store_true',help='Explicitly initialize/refresh expected controls from saved sources')
    parser.add_argument('--reuse-loaded-db',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    v=Verifier(args.dataset,args.scratch)
    print('Loading saved CSV source extracts into independent SQLite',flush=True)
    v.load();v.cutoff();v.sales();v.procurement_inventory();v.ap_checks();v.labor();v.accounting();v.other_finance();v.controls(args.write_controls);v.mutation_tests();v.manifest()
    summary=v.save();v.db.close()
    return 1 if summary['failures'] else 0


if __name__=='__main__':sys.exit(main())
