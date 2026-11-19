"""Economic sensitivity test. Corrupt only a temporary COPY; refresh its manifest to bypass hash-only checks."""
import csv,json,hashlib,shutil,subprocess,sys,tempfile
from pathlib import Path
from decimal import Decimal

candidate=Path(__file__).resolve().parents[1]
BASE=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else candidate if (candidate/'metadata/table_schemas.json').exists() else candidate/'outputs'/'juniper_quay_data'
def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
file=BASE/'sources/night_audit/folio_lines/2026-10.csv';original=hashlib.sha256(file.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='mutation_fixture_',dir=Path(__file__).resolve().parent) as temp:
    target=Path(temp)/'juniper_quay_data';shutil.copytree(BASE,target)
    changed=target/file.relative_to(BASE);rr=read(changed);idx=next(i for i,r in enumerate(rr) if r['charge_type']=='room')
    rr[idx]['net_revenue_usd']=f'{Decimal(rr[idx]["net_revenue_usd"])+Decimal(".01"):.2f}';write(changed,rr)
    manifest=read(target/'metadata/file_manifest.csv')
    for m in manifest:
        if m['relative_path']==file.relative_to(BASE).as_posix():m['size_bytes']=str(changed.stat().st_size);m['sha256']=hashlib.sha256(changed.read_bytes()).hexdigest()
    write(target/'metadata/file_manifest.csv',manifest)
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('verify_dataset.py')),str(target)],capture_output=True,text=True,encoding='utf-8')
    report=read(target/'validation/validation_report.csv');failed=[r for r in report if r['status']=='FAIL'];economic=[r for r in failed if r['check_name']!='Saved source SHA256 and byte count'];passed=result.returncode!=0 and bool(economic) and not any(r['check_name']=='Saved source SHA256 and byte count' for r in failed)
    data=dict(test='one-cent saved folio mutation with refreshed manifest',status='PASS' if passed else 'FAIL',corrupted_copy_exit_code=result.returncode,mutation_cents=1,manifest_was_refreshed=True,economic_failures_detected=[r['check_name'] for r in economic],pristine_source_unchanged=hashlib.sha256(file.read_bytes()).hexdigest()==original,dirty_fixture_in_deliverables=False)
    (BASE/'validation/mutation_test_result.json').write_text(json.dumps(data,indent=2),encoding='utf-8');print(json.dumps(data))
    if not passed:print(result.stdout[-4000:]);print(result.stderr[-2000:])
    sys.exit(0 if passed and data['pristine_source_unchanged'] else 1)
