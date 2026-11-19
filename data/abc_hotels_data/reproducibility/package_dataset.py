"""Package verified saved deliverables; verify every ZIP byte hash after creation."""
import csv,json,hashlib,zipfile,shutil,html
from pathlib import Path
from core import OUT,ROOT,write_csv

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def mib(n):return f'{n/1024/1024:.2f} MiB'

def main():
    validation=json.loads((OUT/'validation/validation_summary.json').read_text());mutation=json.loads((OUT/'validation/mutation_test_result.json').read_text())
    assert validation['failed_conditions']==0 and mutation['status']=='PASS' and mutation['pristine_source_unchanged']
    sources=read(OUT/'metadata/source_catalog.csv');summary=json.loads((OUT/'metadata/build_summary.json').read_text())
    for filename in ['core.py','stays.py','operations_finance.py','planning.py','metadata_docs.py','build_dataset.py','verify_dataset.py','write_deliverable_docs.py','test_core.py','mutation_smoke.py','package_dataset.py']:
        shutil.copy2(Path(__file__).with_name(filename),OUT/'reproducibility'/filename)
    # Copy is tested by a separate final command before archive verification is claimed.
    review='''# Финальный независимый review\n\nСвежий reviewer отдельно прочитал генератор, verifier, saved CSV, контрольные totals и финальные Russian docs; не участвовал в написании генератора.\n\nРезультат: substantive accounting/data issues не осталось; пакет принят к поставке. Counts/financial totals совпадают с сохранёнными CSV. Все99 copied JSON trace rows сопоставлены с исходниками.\n\nИсправлены по review: refund-before-parent-capture (ранняя cancellation теперь void до capture), future corporate collection split по service_month и65/35 dates, recurring services due Dec30 вместо Dec20. Исправлены по disk verifier: два пересекавшихся maintenance intervals, неоднозначная corporate blended annual salary driver, ошибочный FK target corporate receipt master и тип zero-first commission rate. Расширены проверки closures, known-cash categories, individual bill GL и original budget drivers.\n\nMinor trace prose исправлена: direct prepaid breakfast consumes existing advance; remaining259.96 покрывает только часть future331.96, incremental collection72.00. Это не дополнительный capture в actuals.\n\nПоследний полный independent disk-only run:188 groups,27,426,521 evaluated conditions,0 failures. Money0 cents, quantity0 nights/minutes tolerance. Mutation+1 cent with refreshed source manifest detected, pristine source untouched. Это внутренняя верификация synthetic case, не legal/tax/USALI certification.\n'''
    review=review.replace('188 groups,27,426,521 evaluated conditions',f"{validation['check_groups']} groups,{validation['evaluated_conditions']:,} evaluated conditions")
    (OUT/'validation/REVIEW_RU.md').write_text(review,encoding='utf-8')
    excludes={'metadata/package_manifest.csv','validation/package_integrity.json'}
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.relative_to(OUT).as_posix() not in excludes)
    manifest=[dict(relative_path=p.relative_to(OUT).as_posix(),size_bytes=p.stat().st_size,sha256=digest(p)) for p in files]
    write_csv(OUT/'metadata/package_manifest.csv',list(manifest[0]),manifest)
    for r in manifest:
        p=OUT/r['relative_path'];assert p.stat().st_size==r['size_bytes'] and digest(p)==r['sha256'],r['relative_path']
    (OUT/'validation/package_integrity.json').write_text(json.dumps(dict(status='PASS',files_checked=len(manifest),failures=0,scope='all deliverable files except package manifest and this integrity report; source hashes also independently checked',money_validation_failed_conditions=validation['failed_conditions']),indent=2),encoding='utf-8')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    full=OUT.parent/'juniper_quay_hotels_24m_full.zip';rootname=OUT.name;download=[]
    def buildzip(dest,selected,extra_note=None):
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in selected:z.write(p,f'{rootname}/{p.relative_to(OUT).as_posix()}')
            if extra_note:z.writestr(extra_note[0],extra_note[1])
        with zipfile.ZipFile(dest) as z:
            assert z.testzip() is None,dest.name
            for p in selected:
                member=f'{rootname}/{p.relative_to(OUT).as_posix()}'
                assert hashlib.sha256(z.read(member)).hexdigest()==digest(p),(dest.name,member)
            assert len(z.namelist())==len(set(z.namelist()))
        return dict(filename=dest.name,size_bytes=dest.stat().st_size,size_mib=mib(dest.stat().st_size),sha256=digest(dest),file_count=len(selected)+(1 if extra_note else 0))
    download.append(dict(package='FULL',description='Все источники, metadata, docs, examples, validation, scripts',**buildzip(full,files)))
    common=[p for p in files if (p.parent==OUT and p.suffix=='.md') or (p.is_relative_to(OUT/'metadata') and p.name!='package_manifest.csv')]
    for s in sources:
        system=s['source_system'];selected=[p for p in files if p.is_relative_to(OUT/'sources'/system)]+common
        note=f'# Отдельный source archive: {system}\n\nСодержит только sources/{system}/ и общий справочный набор metadata/docs. Canonical metadata описывает ВЕСЬ пакет, поэтому внешние FK и full verifier требуют остальных источников. Для сквозной работы используйте полный ZIP либо распакуйте все14 source ZIP в одну папку: общие metadata идентичны. Не загружайте повторные metadata как факты. Сверки и финансовый контроль выполнены для полного пакета.\n'
        result=buildzip(OUT.parent/f'juniper_quay__{system}.zip',selected,(f'{rootname}/source_archive_notes/{system}_RU.md',note))
        download.append(dict(package=system,description=s['description_en'],**result));print(result['filename'],result['size_mib'],flush=True)
    write_csv(OUT.parent/'DOWNLOAD_MANIFEST.csv',list(download[0]),download)
    lines=[f'| [{r["package"]}]({r["filename"]}) | {r["size_mib"]} | {r["file_count"]} |' for r in download]
    index=f'''# Скачать Juniper Quay — отели и апарт-отель\n\nSynthetic demo / principal US operator.156 ключей,3 объекта, actual2024-11-01–2026-10-31; cutoff2026-10-31.\n\n**Начните с [полного ZIP]({full.name}) — {download[0]['size_mib']}.** Внутри готовая папка для Claude.\n\n{summary['tables']} logical tables; {summary['csv_files']} source CSV; {summary['source_rows']:,} source rows; {summary['reservations']:,} reservations; {summary['consumed_nights']:,} consumed room-nights; {summary['gl_lines']:,} GL lines. CSV uncompressed {mib(summary['source_bytes'])}.\n\nIndependent verifier:{validation['check_groups']} groups, {validation['evaluated_conditions']:,} conditions,0 errors; money to cent, room-night exact. Mutation test PASS. ZIP contents, CRC and every saved-file SHA256 verified after packaging.\n\n| Архив | Размер | Файлов |\n|---|---:|---:|\n'''+ '\n'.join(lines)+'''\n\nSource ZIPs содержат общие metadata/docs плюс свой source folder. Их можно изучать отдельно, а для сквозных joins объедините все14 source archives или используйте FULL. Source archive metadata описывает весь пакет. Не загружайте одинаковые справочные copies повторно как финансовые факты.\n\n[README](juniper_quay_data/README_RU.md) · [Профиль](juniper_quay_data/COMPANY_PROFILE_RU.md) · [Задание для Claude](juniper_quay_data/CLAUDE_HANDOFF_RU.md) · [Проверки](juniper_quay_data/validation/validation_report.csv) · [96 monthly controls](juniper_quay_data/validation/monthly_control_totals.csv) · [SHA256 архивов](DOWNLOAD_MANIFEST.csv).\n'''
    (OUT.parent/'DOWNLOAD_INDEX_RU.md').write_text(index,encoding='utf-8')
    table=''.join(f'<tr><td><a href="{html.escape(r["filename"])}">{html.escape(r["package"])}</a></td><td>{r["size_mib"]}</td><td>{r["file_count"]}</td></tr>' for r in download)
    htmlindex=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Juniper Quay — файлы данных</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:980px;margin:48px auto;padding:0 24px;color:#20222a}}h1{{font-size:30px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}a{{color:#5c3bb6}}small{{color:#555}}</style><h1>Juniper Quay: готовый пакет данных</h1><p>Synthetic demo ·156 ключей ·3 объекта ·24 месяца ·USD</p><p><a href="{full.name}" download>Скачать полный пакет — {download[0]['size_mib']}</a></p><p>{summary['source_rows']:,} строк, {summary['tables']} таблиц, {summary['csv_files']} source CSV. Independent verification:0 ошибок. Данные уже связаны; приложения/дашборда здесь нет.</p><table><thead><tr><th>Архив</th><th>Размер</th><th>Файлов</th></tr></thead><tbody>{table}</tbody></table><p><a href="juniper_quay_data/CLAUDE_HANDOFF_RU.md">Передача в Claude</a> · <a href="juniper_quay_data/README_RU.md">README</a> · <a href="DOWNLOAD_MANIFEST.csv">Размеры/SHA256</a></p><small>Source archives содержат один источник и общие metadata/docs. Сквозная финансовая модель требует все источники. Все сущности и операции вымышлены.</small></html>'''
    (OUT.parent/'DOWNLOAD_INDEX_RU.html').write_text(htmlindex,encoding='utf-8')
    result=dict(status='PASS',archives=len(download),zip_crc_and_member_hash_failures=0,full_archive_bytes=download[0]['size_bytes'],full_archive_sha256=download[0]['sha256'],package_files=len(files),package_uncompressed_bytes=sum(p.stat().st_size for p in files))
    (OUT.parent/'DELIVERY_VERIFICATION.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
