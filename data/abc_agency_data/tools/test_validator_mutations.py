"""Challenge the independent validator using isolated CSV copies, never the main fact."""
import csv, json, shutil, sys, tempfile
from pathlib import Path
from decimal import Decimal
from validate_dataset import validate, csv_read, write_csv

def main():
    here=Path(__file__).resolve().parent; candidate=here.parent
    root=Path(sys.argv[1]) if len(sys.argv)>1 else candidate if (candidate/'metadata/table_schemas.json').exists() else candidate/'outputs/signal_harbor_data'
    scratch=Path(sys.argv[2]) if len(sys.argv)>2 else here/'mutation_checks'
    scratch.mkdir(parents=True,exist_ok=True)
    cases=[
       ('payroll_cost_one_cent','sources/gusto/cost_allocations.csv','allocated_employer_cost_usd',lambda x:str(Decimal(x)+Decimal('.01')),'Payroll allocations equal actual employer cost to cent'),
       ('client_media_payer','sources/meta_ads/ad_accounts.csv','agency_pays_platform',lambda x:'True','Direct client-funded ad accounts excluded from agency cash'),
       ('future_actual_bank','sources/bank/transactions/2026-10.csv','transaction_date',lambda x:'2026-11-01','No actual facts after historical cutoff'),
       ('late_budget_approval','sources/planning/budget_versions.csv','approved_date',lambda x:'2026-01-01','Original budgets approved before covered period'),
       ('earned_hourly_overstatement','sources/delivery/service_obligations.csv','approved_fee_usd',lambda x:str(Decimal(x)+Decimal('1.00')),'Hourly fee equals approved hours times effective rates'),
       ('unbalanced_journal','sources/quickbooks/general_ledger/2026-10.csv','debit_usd',lambda x:str(Decimal(x)+Decimal('.01')),'Every journal balances to cents'),
       ('contractor_double_expense','sources/quickbooks/vendor_bill_lines.csv','account_id',lambda x:'5010','Freelancer QB bill clears accrual without second expense'),
       ('closed_won_pipeline','sources/hubspot/deal_monthly_snapshots.csv','include_in_pipeline',lambda x:'True','Won-lost deals excluded from open pipeline'),
    ]
    results=[]
    # TemporaryDirectory only removes its own freshly-created directory under explicit scratch.
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=scratch) as tmp:
        fixture=Path(tmp)/'dataset'; shutil.copytree(root/'sources',fixture/'sources'); shutil.copytree(root/'metadata',fixture/'metadata')
        baseline,_,_=validate(fixture,False)
        if baseline['status']!='PASS': raise AssertionError('Mutation baseline is not clean')
        for name,path,col,mutate,target in cases:
            p=fixture/path; original=p.read_bytes(); rows=csv_read(p)
            if name=='earned_hourly_overstatement': selected=next(r for r in rows if r['service_type']=='hourly' and r['record_scope']=='in_period')
            elif name=='contractor_double_expense': selected=next(r for r in rows if r['approved_work_id'] and r['account_id']=='2200')
            elif name=='closed_won_pipeline': selected=next(r for r in rows if r['stage_id']=='closed_won')
            else: selected=rows[0]
            selected[col]=mutate(selected[col]); write_csv(p,rows)
            try:
                summary,checks,_=validate(fixture,False); report=next(r for r in checks if r['check_name']==target)
                caught=report['failures']>0 and summary['status']=='FAIL'; results.append(dict(mutation=name,target_check=target,detected=caught,target_failures=report['failures'],note='Semantic check failed independently of the additional manifest hash mismatch'))
                print(name, 'DETECTED' if caught else 'MISSED',flush=True)
                if not caught: raise AssertionError(name)
            finally: p.write_bytes(original)
    write_csv(root/'validation/validator_mutation_tests.csv',results)
    print('Mutation challenges passed:',len(results))

if __name__=='__main__': main()
