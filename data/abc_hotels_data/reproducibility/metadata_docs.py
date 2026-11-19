from core import *

SOURCE_INFO={
 'pms':('PMS / Mews-style','Principal room reservations, masters, actual stay nights; custom synthetic flat extracts.'),
 'availability':('Room availability and closures','Physical room/date ledger; additive capacity; OOO/OOS separate.'),
 'night_audit':('Night audit / folios','Signed actual service charges and tax liabilities. Not checkout-date recognition.'),
 'channel_manager':('Channel manager / OTA','Booking-style agency, Expedia-style merchant, gross-to-net settlements and commissions.'),
 'payments':('Direct gateway / deposits','Captures/refunds, liability applications, gateway clearing/transit, refundable security.'),
 'corporate_billing':('Corporate/group billing','Companies/contracts, block allotments, earned invoices, partial receipts, advances.'),
 'operations':('Housekeeping / maintenance','Approved labor, laundry, consumables, agency and maintenance source detail.'),
 'procurement':('Procurement / vendors','POs, acceptance receipts and commitments; operating supplies expensed on receipt.'),
 'gusto':('Gusto-style staff/payroll','Effective rates, schedules, approved actual minutes, weekly overtime, earned/funded payroll.'),
 'fixed_assets_finance':('Assets / treasury','Opening asset pools, capex, depreciation, debt, hotel tax remittances, member distributions.'),
 'marketing':('Own Meta/Google / booking CRM','Daily ad cost, billing, overlapping platform-attributed booking values, direct funnel.'),
 'quickbooks':('QuickBooks-style accounting','COA, opening TB, GL, vendor AP, monthly TB. Authoritative financial actuals.'),
 'bank':('Operating bank statement','One consolidated USD account, actual posted cash and month-end balances.'),
 'planning':('Approved budget / cutoff planning','Original pre-period budget; OTB future nights and explicit cash forecasting inputs. No future actuals.')}

FIELD_NOTES={
 'service_date':'Local date when one night/service is consumed; future only in planning tables.',
 'posting_date':'Actual source posting date; services in this case are posted on service date.',
 'accounting_date':'GL journal recognition date within actual window.',
 'snapshot_date':'As-of date of extracted balances/status; not an event date.',
 'physical_nights':'Physical room keys multiplied by one date; integer room-nights.',
 'available_nights':'Internal denominator: physical minus OOO and OOS, including vacant/occupied/comp/house-use.',
 'sold_nights':'Actually consumed paid room-nights; excludes cancellation/no-show/comp/house use.',
 'occupied_nights':'Sold plus complimentary plus house-use consumed room-nights.',
 'out_of_order_nights':'Room-night removed by maintenance OOO closure; internal availability excludes it.',
 'out_of_service_nights':'Room-night removed by OOS preventive closure; internal availability excludes it.',
 'gross_amount_usd':'Before discount signed charge or signed gateway capture/refund; table grain determines meaning.',
 'discount_amount_usd':'Positive room reduction; net revenue = gross minus discount.',
 'net_revenue_usd':'Signed earned revenue excluding tax; credits negative. Additive across service lines.',
 'total_charge_usd':'Signed net revenue plus lodging tax; credit negative.',
 'tax_usd':'Signed synthetic tax liability component, excluded from revenue.',
 'debit_usd':'Unsigned debit (or bank outflow if bank table); use table grain and sign guide.',
 'credit_usd':'Unsigned credit (or bank inflow if bank table); use table grain and sign guide.',
 'signed_balance_usd':'Debit minus credit; assets generally positive, liabilities generally negative.',
 'budget_usd':'Positive revenue or expense; contra-revenue negative; do not use as debit-minus-credit.',
 'allocated_expense_usd':'Signed analytical expense transfer: positive receiver, negative corporate donor, sum zero.',
 'source_cost_usd':'Repeated original shared expense reference on allocation rows; NOT additive.',
 'consolidated_increment_usd':'Always zero; analytical allocation creates no new consolidated expense.',
 'source_reference':'Supporting operational contract/reference; can be a non-key descriptive composite.',
 'source_id':'Identifier/composite in source_table; polymorphic references, not universally a single-column FK.',
 'source_table':'Source-specific logical table, independent from GL or copy/index context.',
 'commission_usd':'Signed accrued/adjusted OTA distribution expense; negative credit reverses prior accrual.',
 'commission_withheld_usd':'Merchant commission liability cleared against gross AR at settlement release.',
 'ota_remitted_tax_usd':'Synthetic contractual OTA tax remittance clearing; not hotel bank cash or legal rule.',
 'net_payout_usd':'Gross settled amount less withheld commission/tax/fees according to table. Not revenue.',
 'actual_bank_date':'Actual posted bank arrival; blank if pending/transit as of cutoff.',
 'actual_payment_date':'Actual cash date; blank if still scheduled/open, never zero.',
 'actual_release_date':'Actual merchant settlement release; blank if expected at cutoff.',
 'original_folio_line_id':'Credit-to-original charge lineage; original charge is not overwritten.',
 'collection_model':'hotel_collect, agency, merchant, invoice or internal; controls settlement accounting.',
 'planned_nights':'Scheduled checkout minus checkin dates; not actual consumed nights.',
 'actual_consumed_nights':'Count of actual consumed room-nights through cutoff, excluding checkout.',
 'approved_work_minutes':'Approved completed room service time; case productivity assumptions, not a standard.',
 'approved_housekeeping_minutes':'Subset of approved employee actual work minutes assigned to cleaning tasks.',
 'regular_minutes':'Hourly regular work minutes before 40-hour Monday-week threshold; salary work records informational.',
 'overtime_minutes':'Hourly minutes beyond 2,400 per Monday week; premium 1.5 is a synthetic case parameter.',
 'cost_micros':'Millionths of USD. Divide by 1,000,000; spend_usd is the same cost.',
 'attributed_booking_value_usd':'Platform-attributed quoted booking value; overlaps across platforms, not earned revenue.',
 'incremental_guest_collect_usd':'Future booked charge remaining after existing advances; exclude historical AR and merchant receipts.',
 'overlap_key':'Deduplication key for forecast inputs; recurring service month must be substituted for literal service_month.',
 'aging_bucket':'Open corporate AR aging from invoice due date at cutoff.',
 'opening_signed_usd':'Opening monthly debit-minus-credit carrying balance; P&L accounts cumulative across years.',
 'closing_signed_usd':'Opening signed plus period debits less period credits.',
 'property_id':'Property cost centre RAL/WIL/DUR; CORP permitted in accounting/payroll/planning, no rooms.',
 'room_id':'Stable physical room/unit text identifier; never numeric-coerce.',
 'rate_plan_version_id':'Property-specific effective-dated rate plan used for this service date.',
 'expected_cash_date':'Expected timing input as known at cutoff; not an actual bank event.',
 'is_actual_cash':'False for all forecast index rows; the historical source event may be already earned.',
 'is_actual':'False for schedules/assumptions; does not mean missing or zero.',
 'gross_pay_usd':'Employee earned gross, includes employee withholdings; employer costs separate.',
 'employee_withholding_usd':'Synthetic employee deductions/withholding; part of gross, not additional employer expense.',
 'employer_benefit_usd':'Company benefit cost funded in payroll clearing component, not statutory tax.',
 'total_employer_cost_usd':'Gross pay plus employer tax plus employer benefit; not gross plus net.',
 'open_ar_usd':'Invoice total less all cash/prepayment applications at cutoff; nonnegative.',
 'open_ap_usd':'Vendor bill total less applied actual payments at cutoff; nonnegative.',
 'received_total_usd':'Accepted PO value, same transaction as receipt and bill mapping, not extra expense.',
 'unreceived_commitment_usd':'Approved PO value not yet accepted/billed; excludes recognized open AP.',
 'expected_security_return_date':'Forecast return date for refundable security still held; no future cash fabricated.'}

def infer_type(field,rows):
    values=[r.get(field) for r in rows[:100] if r.get(field) not in ['',None]]
    if field.endswith('_usd'):return 'decimal(18,2)','USD','0.01'
    if field.endswith('_date') or field in ['active_from','active_through','effective_from','effective_through','escalation_from']:return 'date','YYYY-MM-DD',''
    if field.endswith('_month') or field in ['first_month','last_month']:return 'month','YYYY-MM',''
    if field.endswith('_id') or field.endswith('_code') or field in ['period_id','external_booking_reference','room_number']:return 'string','identifier',''
    if values and isinstance(values[0],bool):return 'boolean','true/false',''
    if any(isinstance(v,(float,Decimal)) for v in values):return 'decimal','ratio' if any(t in field for t in ['rate','share','mix','multiplier','percent','occupancy','discount']) else 'number','0.000001'
    if values and isinstance(values[0],int):return 'integer','minutes' if field.endswith('_minutes') else 'micros USD' if field=='cost_micros' else 'count','1'
    return 'string','text',''

def build_metadata(ds):
    OUT.mkdir(parents=True,exist_ok=True);md=OUT/'metadata';md.mkdir(exist_ok=True)
    catalog=[];dictionary=[]
    for table,s in ds.schemas.items():
        for f in s['fields']:
            typ,unit,precision=infer_type(f,ds.tables[table]);s.setdefault('types',{})[f]=typ
            sign='signed debit-minus-credit' if 'signed' in f else 'signed by transaction/credit; see accounting guide' if f.endswith('_usd') else 'not applicable'
            desc=FIELD_NOTES.get(f)
            if not desc:
                desc=f'{f.replace("_"," ").capitalize()}; '+('text identifier, join using relationships.csv.' if typ=='string' and unit=='identifier' else 'USD amount at this table grain; '+s['grain']+'.' if f.endswith('_usd') else s['grain']+'.')
            dictionary.append(dict(logical_table=table,column_name=f,data_type=typ,unit=unit,precision=precision,is_primary_key=f in s['primary_key'],nullable=any(r.get(f) in ['',None] for r in ds.tables[table]),sign_convention=sign,description_en=desc,blank_semantics='not applicable, unknown, or not yet occurred; never interpret blank as zero'))
        s['notes']='Custom flat synthetic extract; not a verified native API/export schema. '+('All partitions form one logical table.' if table in PARTITIONS else '')
        catalog.append(dict(logical_table=table,source_system=table.split('/')[0],grain=s['grain'],primary_key=','.join(s['primary_key']),row_count=len(ds.tables[table]),partition_date_column=PARTITIONS.get(table,''),is_copy_or_control=table in ['planning/known_cash_inputs','planning/cutoff_balance_inputs'],notes=s['notes']))
    write_csv(md/'table_catalog.csv',list(catalog[0]),catalog);write_csv(md/'data_dictionary.csv',list(dictionary[0]),dictionary)
    source=[]
    for system,(label,description) in SOURCE_INFO.items():
        source.append(dict(source_system=system,system_style=label,description_en=description,logical_tables=sum(t.startswith(system+'/') for t in ds.tables),row_count=sum(len(r) for t,r in ds.tables.items() if t.startswith(system+'/')),native_api_schema_claim=False))
    write_csv(md/'source_catalog.csv',list(source[0]),source)
    # Explicit masters + guarded polymorphic references. All ordinary FKs are machine checked.
    targets={
      'entity_id':('pms/legal_entities','entity_id'),'property_id':('quickbooks/cost_centres','cost_centre_id'),
      'room_id':('pms/rooms','room_id'),'assigned_room_id':('pms/rooms','room_id'),'room_type_id':('pms/room_types','room_type_id'),
      'reservation_id':('pms/reservations','reservation_id'),'booking_id':('pms/bookings','booking_id'),'guest_id':('pms/guests','guest_id'),'booker_guest_id':('pms/guests','guest_id'),
      'company_id':('corporate_billing/companies','company_id'),'contract_id':('corporate_billing/contracts','contract_id'),
      'channel_id':('channel_manager/channels','channel_id'),'listing_id':('channel_manager/listings','listing_id'),
      'stay_night_id':('pms/actual_stay_nights','stay_night_id'),'rate_plan_version_id':('pms/rate_plans','rate_plan_version_id'),
      'tax_policy_id':('night_audit/tax_policies','tax_policy_id'),'folio_line_id':('night_audit/folio_lines','folio_line_id'),'original_folio_line_id':('night_audit/folio_lines','folio_line_id'),
      'folio_id':('night_audit/folios','folio_id'),'payment_id':('payments/transactions','payment_id'),'parent_payment_id':('payments/transactions','payment_id'),'payout_id':('payments/payouts','payout_id'),
      'bank_transaction_id':('bank/statement','bank_transaction_id'),'employee_id':('gusto/employees','employee_id'),'compensation_id':('gusto/compensation_history','compensation_id'),'payroll_run_id':('gusto/payroll_runs','payroll_run_id'),
      'vendor_id':('procurement/vendors','vendor_id'),'contractor_vendor_id':('procurement/vendors','vendor_id'),'work_order_id':('operations/work_orders','work_order_id'),'block_id':('availability/room_blocks','block_id'),'task_id':('operations/housekeeping_tasks','task_id'),
      'bill_id':('quickbooks/bills','bill_id'),'bill_line_id':('quickbooks/bill_lines','bill_line_id'),'source_bill_id':('quickbooks/bills','bill_id'),'existing_bill_id':('quickbooks/bills','bill_id'),'existing_october_bill_id':('quickbooks/bills','bill_id'),
      'purchase_order_id':('procurement/purchase_orders','purchase_order_id'),'purchase_order_line_id':('procurement/purchase_order_lines','purchase_order_line_id'),'bill_payment_id':('quickbooks/bill_payments','bill_payment_id'),
      'group_block_id':('corporate_billing/group_blocks','group_block_id'),'invoice_id':('corporate_billing/invoices','invoice_id'),'prepayment_id':('corporate_billing/prepayments','prepayment_id'),
      'asset_id':('fixed_assets_finance/assets','asset_id'),'facility_id':('fixed_assets_finance/debt_facilities','facility_id'),
      'campaign_id':('marketing/campaigns','campaign_id'),'budget_version_id':('planning/budget_versions','budget_version_id'),'week_id':('planning/forecast_weeks','week_id')}
    rels=[]
    for table,s in ds.schemas.items():
        for f in s['fields']:
            target=targets.get(f);condition='nonblank'
            if f=='receipt_id':target=('corporate_billing/receipts','receipt_id') if table.startswith('corporate_billing/') else ('procurement/receipts','receipt_id')
            if f=='settlement_id':
                if table=='channel_manager/commissions':continue # agency invoice vs merchant settlement, explicit below
                target=('channel_manager/settlements','settlement_id')
            if f.endswith('account_code'):target=('quickbooks/chart_of_accounts','account_code')
            if not target or target[0]==table and target[1]==f:continue
            if f=='contract_id' and table in ['procurement/purchase_orders']:continue
            rels.append(dict(from_table=table,from_column=f,to_table=target[0],to_column=target[1],cardinality='many_to_one',condition=condition,notes='Blank allowed when not applicable/future event; text IDs.'))
    for ch,target,col in [('EXPEDIA','channel_manager/settlements','settlement_id'),('BOOKING','channel_manager/agency_invoices','agency_invoice_id')]:
        rels.append(dict(from_table='channel_manager/commissions',from_column='settlement_id',to_table=target,to_column=col,cardinality='many_to_one',condition=f'channel_id={ch}',notes='Polymorphic commission settlement reference.'))
    write_csv(md/'relationships.csv',list(rels[0]),rels)
