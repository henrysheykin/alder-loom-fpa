"""Enrich saved-source metadata, materialize explanatory record copies, package deliverables.
All trace copies are pulled from persisted CSV files, never new synthetic facts.
"""
from pathlib import Path
import csv,json,hashlib,shutil,zipfile
from collections import defaultdict
from decimal import Decimal
BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'outputs'/'cedar_bend_auto_data'
def readcsv(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def read(t):
    for f in SCHEMAS[t]['physical_files']:
        with (ROOT/'sources'/f).open(encoding='utf-8-sig',newline='') as h:yield from csv.DictReader(h)
def enrich():
    dd=readcsv(ROOT/'metadata/data_dictionary.csv');rs=readcsv(ROOT/'metadata/relationships.csv');refs=defaultdict(list)
    for r in rs:refs[(r['from_table'],r['from_column'])].append(f'{r["to_table"]}.{r["to_column"]}')
    desc={
    'monthly_base_usd':'Current recurring contractual monthly base as of cutoff, already including effective rent escalation. Variable utility/maintenance extras require separate forecast assumptions.',
    'opening_monthly_base_usd':'Initial recurring monthly base before the first specified escalation; do not use in place of current monthly_base_usd for future commitments.',
    'first_escalation_date':'First contractual escalation date; rent first rises 3% on 2026-01-01, already included in current monthly base; next annual cycle is 2027-01-01.',
    'opened_date':'Date the RO was opened/approved for work; can predate a future appointment and is not a revenue trigger.',
    'approved_date':'Actual customer authorization date; approved scope only, no earned revenue.',
    'rate_id':'Versioned menu labor price effective on RO authorization date; do not join to latest price.',
    'price_id':'Versioned supplier price agreed on PO order date.',
    'terms_id':'Supplier credit-term version effective on PO order date.',
    'effective_from':'Inclusive effective start of this contract or rate version; may predate the actual window.',
    'effective_to':'Inclusive effective end; empty means current/open-ended at cutoff.',
    'regular_paid_minutes':'Approved regular paid minutes INCLUDING the PTO subset; do not add PTO a second time.',
    'pto_paid_minutes':'Paid leave minutes already included in regular_paid_minutes; never physical production capacity.',
    'overtime_paid_minutes':'Separately approved paid OT minutes, compensated at the synthetic 1.5 multiplier for hourly staff.',
    'approved_paid_minutes':'Regular plus overtime paid minutes; regular already includes paid leave.',
    'paid_presence_minutes':'Paid on-site minutes excluding PTO; no unpaid lunch.',
    'paid_minutes':'All compensated regular plus overtime minutes for employee/run, including PTO.',
    'approved_job_clock_minutes':'Approved physical work time attributed to jobs; distinct from attendance and billable book hours.',
    'delivered_book_hours':'Customer book hours from ROs actually delivered within the payroll period; bonus driver, not capacity.',
    'book_bonus_usd':'Max(0, delivered book hours - 70) times synthetic USD4/hour per semi-monthly technician run.',
    'regular_gross_usd':'Hourly rate times regular minutes/60, or annual salary/24, rounded to cents.',
    'overtime_gross_usd':'Hourly OT rate times OT minutes/60, rounded to cents; salary staff have zero OT premium.',
    'gross_pay_usd':'Regular gross plus OT gross plus book bonus before employee withholding.',
    'employee_withholding_usd':'Synthetic 20% of gross; included within gross, not a second employer expense.',
    'net_pay_usd':'Gross less employee withholding.',
    'employer_tax_usd':'Synthetic 8% of gross additional employer cost; not a statutory payroll computation.',
    'employer_taxes_usd':'Run sum of synthetic employer payroll taxes.',
    'employer_benefits_usd':'Synthetic USD2.20 times all paid hours, rounded per employee/run.',
    'total_employer_cost_usd':'Employee gross plus employer tax plus employer benefits; allocated productive share is analytical only.',
    'total_funding_usd':'Gross plus employer tax plus employer benefits; includes net pay and withholding remittance once.',
    'expected_collection_date':'Cash forecast estimate for the residual invoice amount; not actual collection.',
    'expected_payment_date':'Cash forecast estimate of residual vendor balance; not a bank movement.',
    'expected_application_date':'Expected deposit liability release at delivered invoice; no earlier than RO expected delivery.',
    'expected_receipt_date':'Agreed supplier ETA; can be earlier than actual receipt for delayed past PO, or future for open PO.',
    'remaining_planned_minutes':'Future unfinished physical work estimate; not actual attendance or capacity already used.',
    'actual_install_date':'Completed synthetic installation date; empty means not yet installed. Issued uninstalled parts remain WIP.',
    'actual_wip_release_date':'Actual delivered RO date, when issued parts/sublet cost leaves WIP for expense.',
    'issue_movement_id':'Canonical stock issue reference; bridge row must not be posted as a second issue.',
    'issued_carrying_cost_usd':'FIFO cost copied from linked issue movement; not a new expense.',
    'required_base_quantity':'Recipe part need in canonical SKU units; open requirement does not imply issued or installed.',
    'installed_base_quantity':'Units actually installed on physically completed job; zero for awaiting parts/incomplete work.',
    'reserved_not_issued_quantity':'Required units still unissued; no stock/value movement.',
    'issued_base_quantity':'Part units physically issued into WIP; installed and delivered are separate milestones.',
    'bay_open_minutes':'Physical shop-open bay minutes in bay_calendar; daily_capacity includes staffed rows only.',
    'occupied_open_minutes':'Intersection of continuous RO bay occupation with shop-open windows; includes waiting and overnight effects during open hours.',
    'actual_productive_minutes':'Sum of approved physical job intervals for this bay/date, excludes waiting.',
    'idle_open_minutes':'Physical bay-open minutes minus occupied-open minutes, including unstaffed empty bays.',
    'idle_technician_minutes':'Available physical technician minutes less approved actual job time; not negative.',
    'new_hire_ramp':'True in the first 120 days of new technician employment; reduced demand loading is an explicit scenario.',
    'actual_occupied_from':'First actual job segment timestamp; start of continuous bay occupancy, no future booking inferred.',
    'actual_released_at':'Actual last work end when vehicle moves to off-bay pickup staging; empty for unfinished work.',
    'occupied_through_snapshot_at':'Last observed work timestamp for incomplete RO; open bay occupation continues to cutoff for utilization.',
    'demo_vin':'DEMO-prefixed invented identifier; intentionally not a valid real vehicle VIN.',
    'demo_plate':'DEMO-prefixed invented identifier, not an actual registration plate.',
    'odometer_miles':'Observed synthetic odometer at actual visit, monotonically increasing per vehicle; empty for future job before drop-off.',
    'open_amount_usd':'Unpaid/unapplied residual at cutoff after separate credits and allocations; balance, not period revenue or expense.',
    'residual_amount_usd':'Cutoff future cash amount for this supplier obligation; deduplicate bill or PO overlap key.',
    'open_commitment_usd':'Unreceived PO value at cutoff; no AP or inventory until actual receipt.',
    'open_base_quantity':'Ordered base units less received base units, not yet inventory.',
    'received_base_quantity':'Actual accepted receipt quantity in SKU canonical units.',
    'purchase_quantity':'Count of purchase packs/cases/each; multiply by base_units_per_purchase_unit to get canonical units.',
    'purchase_unit_cost_usd':'USD per purchase pack; canonical base cost times stated conversion.',
    'base_unit_cost_usd':'USD per canonical SKU unit, not per case.',
    'landed_value_usd':'Accepted actual stock carrying value, equal to linked parts vendor bill. No additional freight charge in this case.',
    'original_cost_usd':'Original asset acquisition cost or supplier-return original FIFO lot cost, according to table grain.',
    'gross_usd':'Original extended line selling amount before discount; processor table uses signed captured/refunded principal.',
    'net_usd':'After-discount line or invoice amount excluding sales tax; processor net is in its separate net_usd field after fees.',
    'fee_usd':'Positive synthetic processor charge withheld from clearing; no separate refund fee.',
    'payout_id':'Automatic settlement batch identifier; blank if funds not yet available/initiated by cutoff.',
    'available_date':'Processor funds-availability date (capture plus two modeled business days); can be future as contractual availability, not an actual payout.',
    'actual_bank_date':'Actual payout receipt in bank; blank for in-transit payout at cutoff.',
    'initiated_date':'Actual batch initiation from available funds; no initiated batch after cutoff.',
    'balance_transaction_id':'Canonical capture/refund balance movement including its fee, not a second sale.',
    'cost_micros':'Advertising cost in millionths of USD; spend_usd times 1,000,000.',
    'platform_claimed_conversions':'Synthetic platform-attributed conversion claim; can overlap other platforms and observed leads.',
    'is_summary_only':'True means informational document view, excluded from new financial posting.',
    'cash_forecast_overlap_key':'Bill ID for received stock/AP or PO ID for unreceived commitment; use residual obligation once.',
    'budget_amount_usd':'Locked original approved positive magnitude for this account/month/location; apply account reporting sign.',
    'actual_event_date':'Blank in planning commitments; expected future timing is not an actual historical event.',
    }
    for row in dd:
        f=row['column_name'];t=row['logical_table'];row['grain']=SCHEMAS[t]['grain'];row['foreign_key_targets']='|'.join(refs[(t,f)])
        if f in desc:row['description']=desc[f]
        if f.endswith('_id') or f in ['sku','account_code']:row['data_type']='string'
        if f=='quantity':row['unit']='row.unit'
        if f in ['purchase_quantity','received_purchase_quantity']:row['unit']='purchase_pack'
        if f=='cost_micros':row['unit']='USD_1e-6'
        if f in ['odometer_miles','opening_odometer_miles']:row['unit']='mile'
        if f.endswith('_rate_usd') or f in ['labor_rate_usd','hourly_rate_usd']:row['unit']='USD_per_hour'
        if f in ['unit_price_usd','base_unit_price_usd','base_unit_cost_usd','unit_cost_usd']:row['unit']='USD_per_row_or_base_unit'
        if f in ['purchase_unit_price_usd','purchase_unit_cost_usd']:row['unit']='USD_per_purchase_pack'
        if t in ['billing/payments','bank/statement'] and f=='amount_usd':row['sign_convention']='positive receipt, negative cash outflow/refund'
        if t=='accounting/vendor_payments' and f=='amount_usd':row['sign_convention']='positive payment magnitude; bank counterpart negative'
        if t=='finance/owner_distributions' and f=='amount_usd':row['sign_convention']='positive distribution magnitude; equity debit/bank credit'
    writecsv(ROOT/'metadata/data_dictionary.csv',dd)
    # Explicit vendor mapping is polymorphic, not an invalid FK to only one master.
    links=[dict(from_table=t,from_column='vendor_id',to_table='metadata/vendor_master_mapping.csv',to_column='accounting_vendor_id',cardinality='many_to_one',note='Polymorphic supplier or operating vendor; explicit master_table/master_id mapping.') for t,s in SCHEMAS.items() if 'vendor_id' in s['fields']]
    writecsv(ROOT/'metadata/vendor_relationships.csv',links)
    for t,s in SCHEMAS.items():
        s['columns']={r['column_name']:{k:r[k] for k in ['data_type','unit','nullable','sign_convention','description','foreign_key_targets']} for r in dd if r['logical_table']==t}
    (ROOT/'metadata/table_schemas.json').write_text(json.dumps(SCHEMAS,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(BASE/'work/industry_research.json',ROOT/'metadata/industry_sources.json')
    (ROOT/'metadata/relationship_map.mmd').write_text('''flowchart LR
    CRM[Marketing leads] --> S[Appointments / quotes / approvals]
    S --> RO[Repair orders / jobs / lines]
    RO --> C[Physical segments / bay occupancy]
    P[Supplier contracts / PO] --> R[Receipts / vendor bills]
    R --> I[FIFO inventory]
    I --> W[Issued parts + sublet WIP]
    RO --> W
    W --> D[Actual vehicle delivery]
    D --> V[Customer invoices / COGS]
    V --> AR[AR / payments / deposits]
    AR --> PR[Card clearing / payouts]
    PR --> B[Bank]
    PAY[Attendance / earned payroll] --> G[Double-entry ledger / TB]
    V --> G
    R --> G
    B --> G
    BUD[Locked original budget] --> BV[Budget versus actual]
    G --> BV
    O[Open obligations / agreed bookings] --> CF[13-week cash forecast inputs]
    AR --> CF
    P --> CF
''',encoding='utf-8')

def traces():
    cache={}
    def rows(t):
        if t not in cache:cache[t]=list(read(t))
        return cache[t]
    invoices=rows('billing/invoices');payments=rows('billing/payments');payouts={r['payout_id']:r for r in rows('processor/payouts')};bt={r['balance_transaction_id']:r for r in rows('processor/balance_transactions')}
    retail=None
    for inv in invoices:
        if not ('2026-09-01'<=inv['invoice_date']<='2026-09-25') or inv['fleet_account_id']:continue
        pp=[p for p in payments if p['invoice_id']==inv['invoice_id'] and p['tender_type']=='card' and p['payment_type']=='receipt']
        if not pp:continue
        b=bt.get(pp[0]['processor_balance_transaction_id'],{});po=payouts.get(b.get('payout_id',''),{})
        if po.get('actual_bank_date'):retail=inv;break
    fleet=next(inv for inv in invoices if inv['fleet_account_id'] and '2026-06-01'<=inv['invoice_date']<='2026-07-15' and len([p for p in payments if p['invoice_id']==inv['invoice_id']])==2)
    def trace(inv,name):
        ro=inv['ro_id'];rid=inv['invoice_id'];parts={}
        filters={
         'shop/repair_orders':lambda r:r['ro_id']==ro,'shop/jobs':lambda r:r['ro_id']==ro,'shop/ro_lines':lambda r:r['ro_id']==ro,
         'shop/estimates':lambda r:r['ro_id']==ro,'shop/approvals':lambda r:r['ro_id']==ro,
         'schedule/appointments':lambda r:r['ro_id']==ro,'schedule/job_segments':lambda r:r['ro_id']==ro,'schedule/bay_occupancy':lambda r:r['ro_id']==ro,
         'inventory/movements':lambda r:r['ro_id']==ro,'inventory/ro_parts_usage':lambda r:r['ro_id']==ro,
         'billing/invoices':lambda r:r['invoice_id']==rid,'billing/invoice_lines':lambda r:r['invoice_id']==rid,
         'billing/payments':lambda r:r['ro_id']==ro,'billing/payment_allocations':lambda r:r['invoice_id']==rid,
         'billing/deposits':lambda r:r['ro_id']==ro,'billing/credit_notes':lambda r:r['ro_id']==ro,
         'payroll/job_cost_allocations':lambda r:r['ro_id']==ro,
        }
        for t,fn in filters.items():parts[t]=[r for r in rows(t) if fn(r)]
        estimates={r['estimate_id'] for r in parts['shop/estimates']};parts['shop/estimate_lines']=[r for r in rows('shop/estimate_lines') if r['estimate_id'] in estimates]
        payids={r['payment_id'] for r in parts['billing/payments']};depids={r['deposit_id'] for r in parts['billing/deposits']}
        parts['billing/deposit_events']=[r for r in rows('billing/deposit_events') if r['deposit_id'] in depids]
        parts['processor/balance_transactions']=[r for r in rows('processor/balance_transactions') if r['payment_id'] in payids]
        poids={r['payout_id'] for r in parts['processor/balance_transactions'] if r['payout_id']};parts['processor/payouts']=[payouts[x] for x in poids]
        # Whole batch constituents explain why the bank deposit can exceed this single RO.
        parts['processor/whole_payout_batch_components']=[r for r in rows('processor/balance_transactions') if r['payout_id'] in poids]
        bankids={r['bank_transaction_id'] for r in parts['processor/payouts']}|{r['bank_transaction_id'] for r in parts['billing/payments'] if r['bank_transaction_id']}
        parts['bank/statement']=[r for r in rows('bank/statement') if r['bank_transaction_id'] in bankids]
        parts['billing/whole_noncard_bank_batch_components']=[r for r in payments if r['bank_transaction_id'] and r['bank_transaction_id'] in bankids]
        refs={ro,rid}|payids|depids|poids|{r['balance_transaction_id'] for r in parts['processor/balance_transactions']}
        parts['accounting/general_ledger']=[r for r in read('accounting/general_ledger') if r['source_id'] in refs or (r['account_code']=='1000' and any(b['source_id']==r['source_id'] for b in parts['bank/statement']))]
        return {'notice':'EXPLANATORY RECORD COPIES ONLY — already present in sources; do not load as additional facts.','trace_name':name,'root_ro_id':ro,'root_invoice_id':rid,'tables':parts}
    ex=ROOT/'examples';ex.mkdir(exist_ok=True)
    for inv,name in [(retail,'retail_ro_trace'),(fleet,'fleet_ro_trace')]:
        (ex/f'{name}.json').write_text(json.dumps(trace(inv,name),ensure_ascii=False,indent=2),encoding='utf-8')
    ret=next(r for r in rows('purchasing/supplier_returns') if r['return_date']<'2026-09-01');bid=ret['original_bill_id'];rid=ret['original_receipt_id'];vc=ret['vendor_credit_id'];receipt=next(r for r in rows('purchasing/receipts') if r['receipt_id']==rid);po=receipt['po_id']
    alloc=[r for r in rows('accounting/ap_allocations') if r['bill_id']==bid];pids={r['vendor_payment_id'] for r in alloc if r['vendor_payment_id']};vp=[r for r in rows('accounting/vendor_payments') if r['vendor_payment_id'] in pids];banks={r['bank_transaction_id'] for r in vp}
    parts={
     'purchasing/purchase_orders':[r for r in rows('purchasing/purchase_orders') if r['po_id']==po],
     'purchasing/po_lines':[r for r in rows('purchasing/po_lines') if r['po_id']==po],
     'purchasing/receipts':[receipt],'purchasing/supplier_returns':[ret],
     'inventory/movements':[r for r in rows('inventory/movements') if r['source_id'] in [rid,ret['supplier_return_id']]],
     'accounting/bills':[r for r in rows('accounting/bills') if r['bill_id']==bid],
     'accounting/bill_lines':[r for r in rows('accounting/bill_lines') if r['bill_id']==bid],
     'accounting/vendor_credits':[r for r in rows('accounting/vendor_credits') if r['vendor_credit_id']==vc],
     'accounting/ap_allocations':alloc,'accounting/vendor_payments':vp,'bank/statement':[r for r in rows('bank/statement') if r['bank_transaction_id'] in banks],
     'purchasing/statement_items':[r for r in rows('purchasing/statement_items') if r['bill_id']==bid or r['vendor_credit_id']==vc],
     'accounting/general_ledger':[r for r in read('accounting/general_ledger') if r['source_id'] in {bid,vc}|pids],
    }
    sids={r['statement_id'] for r in parts['purchasing/statement_items']};parts['purchasing/supplier_statements']=[r for r in rows('purchasing/supplier_statements') if r['statement_id'] in sids]
    (ex/'supplier_purchase_return_trace.json').write_text(json.dumps({'notice':'EXPLANATORY RECORD COPIES ONLY — do not add to source facts.','root_po_id':po,'root_bill_id':bid,'tables':parts},ensure_ascii=False,indent=2),encoding='utf-8')
    (ex/'EXAMPLES_RU.md').write_text(f'''# Сквозные записи из сохранённых CSV

Все JSON в этой папке — **копии для объяснения**, не дополнительные факты. Канонические строки находятся в sources/.

- Retail: RO `{retail['ro_id']}`, invoice `{retail['invoice_id']}` от {retail['invoice_date']}, USD {retail['total_usd']}. Parts + labor -> actual segments -> FIFO issue/WIP -> delivered invoice/COGS -> card capture/fee -> batch payout -> bank. В JSON включены все constituents соответствующего payout: сумма банковского batch может превышать вклад одного RO.
- Fleet: RO `{fleet['ro_id']}`, invoice `{fleet['invoice_id']}` от {fleet['invoice_date']}, USD {fleet['total_usd']}. Две оплаты: 40% и 60%; final collection позже net30 и нескольких циклов payroll. Due date не равна actual payment date. ACH batch в банке включает другие поступления.
- Supplier: PO `{po}`, bill `{bid}`. Приёмка увеличивает inventory и AP; возврат уменьшает stock по стоимости исходного lot и создаёт vendor credit; cash payment погашает остаток AP. Statement лишь повторяет существующие bill/credit, COGS возникает отдельно при выдаче автомобиля.

В trace нет второй проводки job labor cost allocation: это управленческая детализация уже начисленной зарплаты. Для полного payroll->bank funding сопоставляйте earning_id/payroll_run_id с источником payroll и GL.
''',encoding='utf-8')
    return {'retail_ro_id':retail['ro_id'],'fleet_ro_id':fleet['ro_id'],'supplier_po_id':po}

def reproduce():
    dest=ROOT/'reproducibility';dest.mkdir(exist_ok=True)
    for name in ['build_dataset.py','verify_dataset.py','prepare_delivery.py','add_margin_controls.py']:
        if (BASE/'work'/name).exists():shutil.copy2(BASE/'work'/name,dest/name)
    (dest/'README_RU.md').write_text('''# Воспроизведение и независимая проверка

Python 3.11+; только стандартная библиотека, установка зависимостей не нужна. Генерация проверена в Python 3.13.9.

Проверить распакованные источники из любого каталога:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/verify_dataset.py" --root "PATH/cedar_bend_auto_data"
```

Сгенерировать отдельную копию, не перезаписывая поставку:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/build_dataset.py" --output "PATH/work/rebuilt_cedar_bend_auto_data"
python "PATH/cedar_bend_auto_data/reproducibility/verify_dataset.py" --root "PATH/work/rebuilt_cedar_bend_auto_data"
```

`build_dataset.py` создаёт economic events, source CSV и исходные metadata. `verify_dataset.py` НЕ импортирует генератор и повторно читает сохранённые файлы. Его checks/controls не используются для создания фактов. `prepare_delivery.py` — служебный скрипт авторской рабочей папки для каталогов, traces и ZIP; его пути предполагают исходную структуру work/ и outputs/, он не нужен для проверки.

Для повторной проверки моста RO margin → GL:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/add_margin_controls.py" --root "PATH/cedar_bend_auto_data"
```

Этот скрипт также читает только сохранённые CSV и останавливается при расхождении на один цент.

Идентификаторы детерминированы, fixed PRNG seeds; одинаковый Python и код дают одинаковые source bytes. Изменение assumptions — новый synthetic scenario; не выдавайте пересчитанные данные за полученный факт. Полный ZIP содержит проверенный снимок CSV, документацию, независимый verifier и исходный генератор.
''',encoding='utf-8')

if __name__=='__main__':
    SCHEMAS=json.loads((ROOT/'metadata/table_schemas.json').read_text(encoding='utf-8'))
    enrich();print('metadata enriched',flush=True);print(traces(),flush=True);reproduce()
