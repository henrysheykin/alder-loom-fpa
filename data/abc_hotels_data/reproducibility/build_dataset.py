"""Regenerate every source; docs/verification are separate passes. Python 3.11+, stdlib only."""
from core import *
from stays import build_reservations,build_folios_and_collections,clean_private_fields
from operations_finance import *
from planning import build_budget,build_cutoff_subledgers_forecast
import time

def main():
    ds=Dataset();steps=[build_masters,build_reservations,build_folios_and_collections,build_operations_payroll,build_operating_bills_marketing,build_assets_debt,pay_bills_taxes_opening,build_trial_balance_allocations,build_budget,build_cutoff_subledgers_forecast]
    for step in steps:
        start=time.monotonic();step(ds);print(step.__name__,f'{time.monotonic()-start:.1f}s',sum(len(x) for x in ds.tables.values()),flush=True)
    trace={'direct_prepaid_reservation_id':ds.trace_direct['reservation_id'],'ota_cross_cutoff_reservation_id':ds.trace_ota['reservation_id']}
    clean_private_fields(ds)
    from metadata_docs import build_metadata
    build_metadata(ds)
    manifest=ds.export()
    (OUT/'metadata/trace_selection.json').write_text(json.dumps(trace,indent=2),encoding='utf-8')
    summary=dict(tables=len(ds.tables),csv_files=len(manifest),source_rows=sum(len(x) for x in ds.tables.values()),source_bytes=sum(x['size_bytes'] for x in manifest),reservations=len(ds.res),consumed_nights=len(ds.tables['pms/actual_stay_nights']),journals=ds.seq['JRN'],gl_lines=len(ds.tables['quickbooks/general_ledger']),employees=len(ds.tables['gusto/employees']),closing_bank_usd=usd(sum(ds.closing[(p,'1000')] for p in CENTRES)))
    (OUT/'metadata/build_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
