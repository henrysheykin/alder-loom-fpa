from build_dataset import *
import argparse
import build_dataset
from build_finance import run_finance
import export_package

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Rebuild modeled sources deterministically into the chosen folder.')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output:
        build_dataset.ROOT=args.output.resolve(); export_package.ROOT=build_dataset.ROOT
    init_tables()
    company_and_staff(); build_contracts(); media(); timesheets_and_capacity()
    print('Operational events prepared:',sum(len(v) for v in T.values()),flush=True)
    run_finance()
    print('Financial events prepared:',sum(len(v) for v in T.values()),flush=True)
    export_package.write_sources()
    print('Export complete:',export_package.ROOT,flush=True)
