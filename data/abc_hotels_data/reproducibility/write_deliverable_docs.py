"""Documentation/examples assembled from SAVED outputs, not generator's in-memory events."""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict,Counter
import json,csv
from core import OUT,write_csv

def rows(table):
    result=[]
    for path in schemas[table]['physical_files']:
        with (OUT/path).open(encoding='utf-8-sig',newline='') as f:result.extend(csv.DictReader(f))
    return result
def read(path):
    with (OUT/path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def put(path,content):
    p=OUT/path;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(content.strip()+'\n',encoding='utf-8')
def money(s):return Decimal(s or '0')
def dollars(s):return f'USD {money(s):,.2f}'
def sumcol(rr,col):return sum((money(r[col]) for r in rr),Decimal(0))
def jsonfile(path,obj):put(path,json.dumps(obj,ensure_ascii=False,indent=2))

schemas=json.loads((OUT/'metadata/table_schemas.json').read_text());summary=json.loads((OUT/'metadata/build_summary.json').read_text());validation=json.loads((OUT/'validation/validation_summary.json').read_text());controls=read('validation/monthly_control_totals.csv');company=[r for r in controls if r['scope_id']=='COMPANY'];last=company[-1];source_catalog=read('metadata/source_catalog.csv')
y1=[r for r in company if r['service_month']<='2025-10'];y2=[r for r in company if r['service_month']>='2025-11']
source_table='\n'.join(f'| {r["source_system"]} | {r["logical_tables"]} | {int(r["row_count"]):,} | {r["description_en"]} |' for r in source_catalog)
profile_rows=[]
for p in ['RAL','WIL','DUR']:
    rr=[r for r in controls if r['scope_id']==p];sold=sum(int(r['sold_nights']) for r in rr);av=sum(int(r['available_nights']) for r in rr);room=sumcol(rr,'net_room_revenue_usd')
    profile_rows.append(f'| {p} | {sold:,} | {Decimal(sold)/av:.2%} | {dollars(room/sold)} | {dollars(sumcol(rr,"total_revenue_usd"))} | {dollars(sumcol(rr,"ebitda_before_shared_allocation_usd"))} |')

put('README_RU.md',f'''
# Juniper Quay — отели и апарт-отель: исходные данные для AI FP&A

Полностью вымышленная американская компания. Все операции, сотрудники, гости, компании, контракты и номера документов synthetic; контакты используют example.com. Это демонстрационные данные для услуг AI-автоматизации reporting, Budget vs Actual, forecasting и cash flow. Они не являются данными или результатом внедрения у реального клиента.

## Быстрый старт

1. Распакуйте полный ZIP с сохранением каталогов. Рабочая папка — `juniper_quay_data/`.
2. Передайте Claude `CLAUDE_HANDOFF_RU.md` и доступ к этой папке. Не вставляйте все строки CSV в текст чата.
3. Прочитайте `COMPANY_PROFILE_RU.md`, `ACCOUNTING_SIGN_GUIDE_RU.md`, `KPI_DEFINITIONS_RU.md`, затем `metadata/source_catalog.csv`, `table_catalog.csv`, `data_dictionary.csv`, `table_schemas.json`, `relationships.csv`.
4. Объедините все partitions каждой логической таблицы. Физические файлы перечислены в schemas и manifest.
5. Сверьте собственные расчёты с `validation/monthly_control_totals.csv`: 24 месяца × компания и три физических объекта = 96 строк.
6. Для повторной независимой проверки: `python reproducibility/verify_dataset.py .` из рабочей папки. Python 3.11+, внешних библиотек нет. Проверка заново читает все сохранённые CSV и пересоздаёт validation reports/controls.

## Масштаб

- Juniper Quay Hospitality LLC; один principal оператор, три property cost centres, shared centre CORP.
- Raleigh Station (RAL): 60 номеров; Cape Landing, Wilmington (WIL): 52 номера; Durham Residences (DUR): 44 апартамента. Всего **156 ключей**. Все объекты работают весь период.
- Actual history: **2024-11-01 — 2026-10-31**, 24 полных месяца, 730 ночей. Snapshot: **2026-10-31**, конец местного дня America/New_York. Валюта USD.
- **{summary['tables']} логических таблиц**, **{summary['csv_files']} исходных CSV**, **{summary['source_rows']:,} исходных строк**. В GL **{summary['gl_lines']:,} строк**, **{summary['journals']:,} сбалансированных journals**.
- **{summary['reservations']:,} room reservations**, **{summary['consumed_nights']:,} actual occupied room-nights**, 33 сотрудника.
- Выручка первых 12 месяцев: **{dollars(sumcol(y1,'total_revenue_usd'))}**, последних 12: **{dollars(sumcol(y2,'total_revenue_usd'))}**. Выручка включает earned ancillary и fees, исключает tax.
- Bank на cutoff: **{dollars(last['closing_bank_usd'])}**. Это один общий счёт. Балансы cash по property являются внутренней аналитикой движений одного счёта, а не отдельными банковскими счетами.

## Источники

| Папка sources/ | Таблиц | Строк | Назначение |
|---|---:|---:|---|
{source_table}

Все source extracts — кастомные плоские synthetic CSV. Обозначения Mews-style, Booking.com-style, Expedia-style, Gusto-style и QuickBooks-style описывают моделируемые концепции, не точную схему native API или штатного Export. Проверенные концепции и границы допущений: `RESEARCH_AND_ASSUMPTIONS_RU.md` и `metadata/research_sources.csv`.

## Форматы и точность

CSV: comma delimiter, UTF-8 BOM, English columns; dates YYYY-MM-DD, months YYYY-MM. IDs и account codes — текст. Деньги — decimal USD с двумя знаками; читайте через Decimal или integer cents. Денежные и количественные сверки точные: **0 cents**, **0 room-nights** допустимой разницы. Ratios в controls округлены до 6/8 знаков; пересчитывайте их из сумм числителей и знаменателей.

Пустая actual дата = событие ещё не наступило/неприменимо; это не ноль. Пустой company_id означает обычного гостя. Во всех исходных CSV boolean записан true/false. Metadata CSV могут использовать True/False. Таблицы unordered, кроме `bank/statement`, где порядок задаёт sequence.

Крупные facts разделены по месяцам: `availability/room_dates`, `pms/actual_stay_nights`, `night_audit/folio_lines`, `operations/housekeeping_tasks`, `gusto/time_entries`, `quickbooks/general_ledger`; будущие OTB nights — по service month. Путь вида `sources/quickbooks/general_ledger.csv` отсутствует: читайте `sources/quickbooks/general_ledger/*.csv`.

## Что не складывать повторно

- PMS booking/quote не равен earned revenue; OTB после cutoff не является actual. Checkout exclusive.
- Folio service lines, corporate invoice lines и GL описывают одни услуги. Corporate invoice reclassifies unbilled AR в invoiced AR, без новой выручки.
- Capture до услуги — advance liability. Deposit application — non-cash погашение AR. Refundable security — отдельное liability.
- OTA merchant gross revenue и distribution expense признаны отдельно. Net settlement, gateway payout и bank arrival не создают продажи.
- Housekeeping/laundry/agency logs — supporting detail тех же payroll/bills. Не прибавляйте их второй раз к расходам GL.
- Own daily ad spend и platform billing — один расход; Meta/Google attribution пересекается и не равна company revenue. OTA commission — отдельный expense.
- Shared allocation bridge суммируется в ноль. CORP расход уже есть в консолидированном GL.
- `planning/known_cash_inputs` и `planning/cutoff_balance_inputs` — явно отмеченные copies/indexes исходных остатков. Применяйте либо индекс, либо исходные документы, с deduplication; не оба.
- Examples, validation controls, archives и manifests не являются дополнительными source facts.

## Cash forecasting inputs

Горизонт — 2026-11-01 — 2027-01-30, 13 недель. Даны open corporate AR и partial applications, vendor AP, payroll funding, tax/agency payables, gateway clearing/transit, merchant AR/transit, held security, future known booked nights, existing advances, monthly corporate collection terms, recurring contracts, debt schedules, unreceived capex commitments и версия incremental demand assumptions. Будущих actual service charges, recognized revenue или bank payments нет.

Готовый рассчитанный forecast не подставлен в данные. Подробный порядок устранения overlap: `CASH_FORECAST_INPUTS_RU.md`.

## Проверка и воспроизводимость

Текущий independent verifier: **{validation['check_groups']} групп**, **{validation['evaluated_conditions']:,} проверенных условий**, **{validation['failed_conditions']} ошибок**. См. `validation/validation_report.csv`, `validation/validation_summary.json`, `VALIDATION_RU.md` и mutation-test result. Контрольные totals вычислены из сохранённых source CSV, без импорта генератора.

`metadata/file_manifest.csv` содержит counts/bytes/SHA-256 каждого source CSV. `metadata/package_manifest.csv` покрывает остальные файлы пакета, кроме самого manifest и integrity report с их self-reference. Архивные SHA-256 находятся в download index рядом с ZIP.

В `reproducibility/` лежат генератор, независимый verifier, тесты и инструкции. Генератор детерминирован по seed 20261119; он создаёт согласованные события, затем раздельные source extracts. Репликация источников не требует облачных аккаунтов.
''')

put('COMPANY_PROFILE_RU.md',f'''
# Juniper Quay Hospitality LLC — профиль синтетической компании

Компания и бренд вымышлены. Юридическая структура: одна North Carolina LLC, principal по всем договорам размещения. Она сама эксплуатирует объекты, нанимает персонал, выставляет corporate invoices и несёт distribution/operating costs. Raleigh real estate принадлежит LLC; Wilmington и Durham арендованы, FF&E принадлежит оператору. Чужих owner funds, property-management fees, trusts или консолидации отдельных дочерних обществ нет.

## Портфель

| ID | Город, NC | Формат | Ключей | Room/category mix | Экономика |
|---|---|---|---:|---|---|
| RAL | Raleigh | Independent select-service hotel, owned | 60 | 32 Standard King, 20 Double Queen, 8 King Suite | weekday business demand, limited leisure weekends; parking и paid breakfast |
| WIL | Wilmington | Independent coastal leisure hotel, leased | 52 | 24 Standard King, 20 Double Queen, 8 King Suite | лето и пятница/суббота сильнее; сезонная стоимость труда; parking/breakfast |
| DUR | Durham | Aparthotel, leased | 44 | 28 studios, 12 one-bedroom, 4 two-bedroom | kitchenette, corporate relocation/project stays 14–55 ночей; weekly cleaning и departure cleaning |

Это рабочие категории кейса, без присвоения официальной звёздности или гостиничной сертификации. Все объекты действуют с 2021 года; master/opening dates могут предшествовать наблюдаемому окну. Предыдущий период не реконструируется; opening TB фиксирует финансовую границу. В opening нет AR/AP/deposits/payroll outstanding; бронирования до окна с capture внутри окна остаются допустимыми.

## Продажи и услуги

Short stays преимущественно 1–6 ночей; отдельные long-stay bookings в DUR 14–55. Один room reservation относится к одному физическому номеру, multi-room booking объединяет такие компоненты. Company account и guest ID разделены. Есть group allotments; сам block не создаёт занятую или проданную ночь.

Rate plans BAR, ADVANCE, CORP, EXTENDED и COMP имеют effective versions. Модельная база Standard King/Studio: RAL USD154, WIL USD169, DUR USD113; room-type multipliers 1.00–1.60. Dynamic season/weekday factors и contract/advance discounts меняют фактический ADR. С марта 2026 базовые nightly rates повышены на 8%. EXTENDED multiplier 0.77, CORP 0.86, ADVANCE 0.93. Это параметры вымышленного бизнеса.

Own website/front desk и Booking-style agency собирают деньги гостя через gateway. Expedia-style merchant собирает у гостя самостоятельно, гостиница признаёт gross earned charge и OTA AR. Corporate invoices выходят на конец каждого месяца за реально оказанные ночи. Два corporate клиента вносят 20% advance; части corporate invoices оплачиваются 65% и 35% раздельно. У CO-001 terms45, у остальных terms30; задержки и фактические даты видны в sources.

Номерные парковка/завтраки включены не во все заезды. Parking RAL USD18/WIL USD14 на выбранные ночи; breakfast USD24 на выбранный room-night; DUR departure cleaning USD65; отдельный late checkout USD35. Merchant room package в этом кейсе не имеет дополнительных hotel-collected ancillary. Security USD250 у DUR — refundable cash liability, не earned cleaning charge.

## Персонал и затраты

33 сотрудника: RAL12, WIL11, DUR7, CORP3. Housekeepers 6/5/3; прочие property roles front desk, maintenance и manager. Ночное наблюдение и часть services закупаются по договору; roster не является обещанием сертифицированного staffing standard. Shared regional manager, finance и revenue/marketing остаются CORP до аналитической allocation по 60:52:44 ключам.

Approved cleaning assumptions: hotel departure34 min, stayover16; DUR departure48 min, weekly32. Laundry sets и unit cost есть в logs. Housekeeper approved shift capacity420 min; нехватка закрывается agency workers, approved worker count и costs. Это pricing/productivity assumptions, не проверенные нормы отрасли. С июня 2026 hourly rates +7.5%, salary +4%; с 15 июня до 31 августа трое WIL housekeepers имеют unpaid absence, agency покрывает выполненные работы. Для hourly overtime >40h Monday-week оплачивается 1.5× по условию кейса.

## События для BVA и commentary

- В 2025 direct share повышается; с лета 2026 возрастает доля OTA и cost per booking.
- В феврале–марте 2026 восемь WIL rooms закрыты на refurbishment; actual capacity уменьшается по room/date, бюджет сохраняет исходную ёмкость.
- В июле 2026 четыре RAL rooms выведены из доступности из-за HVAC; expense maintenance отделён от capitalized refurbishment.
- ADR с марта выше, leisure/business occupancy с мая слабее. Rate growth не гарантирует более высокий contribution.
- Летом растут agency/overtime и собственный advertising spend. Utilities +24% к модельной базе с июня; maintenance base +35%; laundry unit cost повышен с мая.
- С августа CO-001 оплачивает invoices с задержкой52 дня к contractual due; CO-003 delay8 дней. Partial receipts дополнительно распределены на две даты с разницей18 дней.
- Есть cancellations, no-shows, room service credits, refunds и выплаты с банковским поступлением после cutoff.

## Финансовая база и наблюдаемый результат

Opening bank USD650,000. Owned building USD5.2m; opening equipment/fitout USD3.9m; opening accumulated depreciation USD1.69m. Opening term principal USD3.1m, contractual annual interest6.75%, USD7,000 monthly principal; balloon остаток на maturity2033 предусмотрен структурой, полный maturity schedule за пределами горизонта не развёрнут. WIL rent USD26,000/month, DUR USD24,000/month, с января2026 +3%. Rent отражён как operating expense; ASC842 right-of-use accounting не моделируется.

Opening members equity — балансирующий исторический paid-in/retained members capital, не доход периода. Нет отдельного corporate income tax для pass-through LLC. Capex: RAL laundry equipment USD18,500 в мае2025, WIL refurbishment USD64,000 в марте2026, DUR kitchenette equipment USD32,000 в октябре2026. Ещё USD110,000 approved/unreceived DUR PO с платежами30/70% в ноябре/декабре.

| Property | Sold nights, 24mo | Sold occupancy | ADR | Earned revenue | EBITDA до CORP allocation |
|---|---:|---:|---:|---:|---:|
{chr(10).join(profile_rows)}

Компания за 24 месяца: revenue **{dollars(sumcol(company,'total_revenue_usd'))}**, EBITDA **{dollars(sumcol(company,'ebitda_before_shared_allocation_usd'))}**; эти значения вычислены из сохранённых folio/GL. EBITDA — определение кейса, не обещание USALI/GAAP hotel reporting certification.

На cutoff: corporate AR {dollars(last['closing_corporate_ar_usd'])}; vendor AP {dollars(last['closing_vendor_ap_usd'])}; guest lodging deposits {dollars(last['closing_guest_deposits_usd'])}; corporate advances {dollars(last['closing_corporate_deposits_usd'])}; security {dollars(last['closing_security_deposits_usd'])}; processor clearing {dollars(last['closing_gateway_clearing_usd'])}; cash transit {dollars(last['closing_cash_transit_usd'])}. Held liabilities не прибавляются к cash.
''')

put('ACCOUNTING_SIGN_GUIDE_RU.md','''
# Учёт и знаки

## Приоритет источников

GL — authoritative monetary actual P&L/BS; folio lines и subledgers объясняют его. Capacity/PMS задают физические drivers. Opening TB отдельно на 2024-10-31; не включайте его в period revenue/cost. Monthly TB использует debit minus credit и не закрывает P&L ежегодно: period activity берите из period_debit/credit или GL.

GL debit_usd/credit_usd unsigned. Для актива normal signed balance положительный; liability/equity/revenue обычно отрицательный. Expense и contra-revenue обычно дебетовые. Нормализованный P&L: revenue = credits−debits по accounts4000–4210 включая contra; expenses = debits−credits по accounts5000–5700. Budget: income и expense положительны, contra-revenue отрицательна; sign не совпадает с GL balance sign.

Bank credit=поступление, debit=списание, signed=credit−debit. Payments capture positive, refund negative; processing fee positive, net=gross−fee. Folio credits negative, discounts positive reduction; net=gross−discount, total=net+tax. Liability в balance sheet для показа положительным = −GL signed balance. Не превращайте неизвестную actual date в дату due.

## Проводки экономических событий

| Событие | Debit | Credit | Примечание |
|---|---|---|---|
| Gateway lodging capture | 1010 net, 5010 fee | 2200 gross | lodging advance до услуги |
| Consumed room night | 1110/1120/1130 total, 4010 discount | 4000 gross, 2100/2110 tax | guest / merchant / corporate AR соответственно |
| Deposit application | 2200 | 1110 | non-cash, только фактически оказанная charge |
| Hotel ancillary | 1110/1130 | 4100–4120 | separate service line; case ancillary tax0 |
| Room credit | 4020 (+tax liability reduction) | соответствующий AR | original line сохраняется, original_folio_line_id задан |
| Guest service refund | 1110 | 1010 | погашает credit AR, не создаёт второй room credit |
| Cancellation refund of unearned advance | 2200 | 1010 | earned fee при наличии отдельной строкой; до capture — void |
| Security capture/refund | 1010/1000 ↔ 2210 | 2210 ↔ 1010/1000 | ни доход, ни расход; processing fee отдельно |
| Gateway payout initiated | 1020 | 1010 | cash transit, без выручки |
| Actual bank payout arrival | 1000 | 1020 | только когда есть bank statement row |
| OTA commission accrue/credit | 5000 | 2010 | earned room/fee basis; service credit reverse отдельно |
| Merchant settlement release | 1020 net, 2010 commission, 2110 tax | 1120 gross | gross revenue уже признана ночью; tax assumption explicit |
| Agency commission payment | 2010 | 1000 | agency guest previously paid hotel gross |
| Corporate invoice at month end | 1100 | 1130 | AR reclassification, без новой revenue |
| Corporate advance / application | 1000 / 2220 | 2220 / 1100 | cash и non-cash отдельными событиями |
| Corporate partial receipt | 1000 | 1100 | application invoice-specific, не ещё одна продажа |
| Vendor operating bill | expense | 2000 | operational cost detail не прибавлять повторно |
| Capitalized equipment/refurbishment | 1510 | 2000 | invoice acceptance; не maintenance expense |
| Vendor payment | 2000 | 1000 | principal cash payment; AP decreases |
| Earned payroll | wages, 5130 employer tax, 5140 benefit | 2300 net pay, 2310 withholding/employer/benefit clearing | gross включает employee withholding |
| Payroll funding | 2300/2310 | 1000 | отдельно от earned period; benefits bundled in payroll funding |
| Depreciation | 5600 | 1590 | straight line; новый asset с месяца после ввода |
| Debt payment | 2400 principal, 5700 interest | 1000 | principal не P&L |
| Members distribution | 3100 | 1000 | equity, не expense |

Room discounts4010 и room credits4020 уменьшают room revenue; cancellation4200/no-show4210 отдельно, не room ADR numerator. Hotel-collected lodging tax2100 перечисляется по model schedule. Merchant OTA tax2110 погашается release, без hotel bank movement; это contractual synthetic assumption, не налоговая норма. Существующее guest/corporate advance не является future fresh cash.

Invoices, receipts, work logs, payroll details, platform bills и GL могут описывать одну операцию в разных systems/grains. Стройте либо финансовый факт из GL с детализацией source_id, либо субфакты с мостами; никогда UNION ALL всех USD columns.

## Shared costs и property cash

CORP payroll/software признаются один раз в GL. `shared_cost_allocations` — аналитический zero-sum bridge: negative expense у CORP, positive у RAL/WIL/DUR. Не repost bridge в GL и не добавляйте source_cost_usd на каждой строке: он repeated reference. EBITDA_after_allocation = EBITDA_before_allocation − allocated_expense. На company level сумма allocations0.

Один bank account; property_id — аналитическая attribution платежа. CORP может иметь отрицательный attributed running cash после distributions и shared costs, пока консолидированный bank положителен. Это не реальный overdraft отдельного property account. Opening equity распределён по cost centres для balance checks, без intercompany management fees.

## Политики упрощения

Operating supplies/linen services immaterial; expenses при monthly accepted receipt/consumption, без stock ledger. Capitalize equipment/refurbishment с выгодами >12 месяцев и стоимостью проекта ≥USD2,500; routine repair остаётся expense. Строительные работы WO могут содержать approved specialist scope; это supporting approved amount, не весь asset invoice. WIL64k включает specialist work и furnishings; approved WO totals не являются дополнительным capex/expense.

Straight-line salvage0: building390 months; opening equipment/fitout120; new refurbishments84; RAL equipment60. Opening accumulated depreciation принята как carrying historical balance. Corporate income tax, ASC842 leases, FX, chargebacks, credit losses allowance, loyalty points и restaurant inventory не моделируются. Нельзя выдавать параметры кейса за statutory accounting certification.
''')

put('KPI_DEFINITIONS_RU.md','''
# KPI definitions: additive drivers first

| Показатель | Определение кейса | Источники / ограничения |
|---|---|---|
| Physical room-nights | keys × dates | room master + availability room/date; одна строка на key/date |
| Available nights | physical − OOO − OOS | оба статуса исключены для внутреннего denominator; comp/house-use остаются в available |
| Sold nights | actual consumed paid stays | pms actual_stay_nights stay_status=sold; не booking/block/no-show |
| Occupied nights | sold + complimentary + house_use | actual occupied; checkout exclusive |
| Sold occupancy | SUM(sold)/SUM(available) | основной occupancy, без сложения/усреднения monthly ratios |
| Occupied occupancy | SUM(occupied)/SUM(available) | включает complimentary и house-use; это не sold occupancy |
| Net room revenue | gross room4000 − discounts4010 − service credits4020 | folio type room+room_credit; tax/ancillary/fees исключены |
| ADR | net room revenue / sold nights | sold, а не occupied; service credits уменьшают numerator без удаления sold night |
| RevPAR | net room revenue / available nights | ADR × sold occupancy при тех же scope/date/denominator |
| Ancillary revenue | parking4100 + breakfast4110 + cleaning/late4120 | услуги по consumed service date, separate from room |
| Total revenue | net room + ancillary + cancellation/no-show fees | tax и security исключены |
| Distribution cost | all accrued OTA commissions5000, including fee-related | own Meta/Google5400 и processing5010 отдельно |
| Net ADR after OTA commission | (net room − только room/room_credit-related OTA commission)/sold | commissions on cancellation/no-show fees исключены из этого numerator; direct commission0 |
| Channel economics | net earned room по channel − related commission, optionally processing/own ads separately | merchant net payout не surrogate revenue; атрибуцию платформ не складывать |
| Corporate AR | earned invoices − cash/prepayment applications | due-date aging на cutoff; не будущие monthly invoices |
| Cancellation rate | cancelled reservations / all room reservations of scheduled-arrival cohort | reservations count, не nights; multi-room booking counts several components; на выбранный as-of |
| No-show rate | no_show reservations / scheduled-arrival cohort | no occupied night; earned fee separately |
| Housekeeping defined cost | 5100 employee gross +5150 agency +5200 laundry +5210 consumables | employer tax/benefit не включены; показывать выбранное определение |
| HK cost per occupied night | defined HK cost / occupied nights | extended stays имеют weekly service; сопоставлять с format mix |
| HK cost per serviced room | тот же defined cost / approved cleaning tasks | включает зарплату и непродуктивное оплачиваемое время; несколько задач в одном key/day возможны как разные services |
| Property contribution / EBITDA before shared | earned total revenue − property opex excluding5600/5700 | включает property rent, utilities, distribution, own ads; CORP costs excluded from individual properties |
| EBITDA after shared allocation | before − analytical allocated shared expense | company consolidated EBITDA одинаков до/после allocation |
| Net income | earned revenue − all expenses incl depreciation/interest | principal и distributions excluded |
| BVA revenue | actual revenue − original budget revenue | positive favorable for revenue |
| BVA expense | actual expense − budget expense | positive unfavorable; показывать sign явно |
| BVA EBITDA | actual EBITDA − original budget EBITDA | positive favorable |

В controls доступны 96 monthly rows: COMPANY включает CORP; три physical properties показываются отдельно. Чтобы company contribution совпал с суммой properties, примените zero-sum allocations и учтите CORP residual0. Не суммируйте COMPANY вместе с properties. Чтобы объединить месяцы или объекты, складывайте cents/nights, затем делите. ADR и RevPAR в control file имеют6 decimal places для display; occupancy8. Никакого ограничения «ADR×sold≈revenue» из-за gross-versus-net путаницы нет: numerator определён точно; rounding display tolerance отдельно.

В monthly controls property EBITDA BVA сравнивает EBITDA до shared allocation с исходным property budget без CORP. COMPANY budget и actual уже включают CORP. Для BVA после shared allocation сначала распределите также budget CORP cost по тому же driver, чтобы scopes совпадали. Account3100 drawings имеет normal debit sign, несмотря на equity classification.

Cancellation/no-show costs могут влиять на total distribution expense, но их earned fees не входят в room revenue. Credit по прошлой ночи в этом кейсе отражён на service recovery date внутри того же stay; original night mapping сохраняется. Long stays: earned nights попадают в каждый сервисный месяц, invoice month-end не меняет revenue recognition.

OOO/OOS policy намеренно является внутренней управленческой политикой; её нельзя автоматически назвать denominator стандартного STR benchmark. Данные поддерживают пересчёт альтернативного denominator из physical/closure flags, если явно сменить KPI definition.
''')

put('CASH_FORECAST_INPUTS_RU.md','''
# Исходные данные для 13-week cash forecast

As-of 2026-10-31; первая неделя2026-11-01–11-07, последняя2027-01-24–01-30. Это input package, не готовый forecast. Blank actual dates не разрешают считать будущий cash фактом.

## Порядок построения

1. Opening liquidity — bank1000, отдельно gateway1010 и transit1020. Поступления clearing/transit прогнозируйте один раз; не прибавляйте эти активы к bank и одновременно ещё раз как opening cash.
2. Возьмите earned/open obligations. `planning/known_cash_inputs` — convenience COPY/index: open invoices/AP, earned-unfunded payroll, tax, agency commission, earned merchant remittances, gateway transit/unreleased balance, security returns, debt и unreceived capex. Полный перечень проверяется с source subledgers. Используйте индекс ИЛИ первичные таблицы, без повторения.
3. Historical open corporate invoices уже включают actual nights до cutoff. Фактические receipts/applications уже уменьшили open_ar. expected_collection_date — оставшаяся сумма к expected final tranche, conservative timing для частично открытого остатка. При уточнении разбейте остаток по источнику application/observed client delay, не создавайте повторный full invoice collection.
4. Merchant earned/unsettled gross AR1120 включает налог/комиссию. В known_cash_inputs уже дан net payout после обоих удержаний. Не добавляйте отдельно тот же gross OTA AR плюс net settlement. Tax2110/merchant commission, включённые в этот netting, не требуют ещё одного hotel bank payment.
5. Для будущих услуг возьмите `on_books_nights` и `booked_payment_terms`. Услуги будущие, известные reservations созданы не позже cutoff. Monthly corporate rows разбиты по reservation/service_month; existing_advance_cover распределён по ближайшим месяцам и не повторяется. `incremental_guest_collect_usd` уже исключает held advances; 65% собирайте на expected_first_collect_date, remainder на expected_collect_date. Delay52 для CO-001, delay8 для CO-003; first_tranche_share65%. Direct/agency remaining lodging collect при заезде; existing prepaid amount не является fresh receipt.
6. Merchant future OTB: разбивайте по service nights, начисляйте gross room revenue, distribution18% и synthetic tax, прогнозируйте weekly net release. В этой модели service date переносится на Saturday той же недели +7 дней; actual bank +1 business day. У future terms merchant collect dates blank: они определяются nightly settlement rule, не monthly corporate invoice rule.
7. New business — только incremental nights `max(0,target_total_sold_occupancy×available−known_OTB_sold_nights)`, с ограничением remaining capacity. Не прибавляйте target occupancy поверх OTB. Mix/ADR/variable cost/collection assumptions по property/week находятся отдельно; можно сделать сценарии с version IDs. OTB free/house-use capacity уже тоже занята и требует physical capacity контроля.
8. Salaried/hourly будущие payroll periods генерируйте из active employees, effective rates, calendars и hours assumptions. Earned October H2 funding в начале ноября уже является known obligation; не включайте его второй раз в new November payroll. Payroll2310 включает employee withholding, employer tax и funded benefits, их не дублировать как отдельный tax outflow.
9. Recurring contracts начинаются с next_service_month2026-11. October AP относится к предыдущему cycle и уже есть в open AP. Match `property|account|service_month`; existing_october_bill_id поможет проверить границу. Rent due month start, insurance end+20, services/software end+30. На due weekend применяйте business-day timing при построении bank cash forecast. Utilities/maintenance future base — assumptions, не ещё один fixed contract bill.
10. Approved unreceived capex PO USD110k — installments30/70%. Он не имеет actual receipt/bill/AP на cutoff. Если позже появится bill, замените соответствующий commitment, не складывайте оба. Уже capitalized October equipment относится к AP и исключено из unreceived commitments.
11. Security deposits2210 — refundable outflow по expected return; не room revenue, не lodging prepayment coverage. Future new DUR guests могут внести новые security amounts, для этого нужен отдельный scenario driver; не netting с room revenue.
12. Debt schedule разделяет principal/interest; known scheduled service уже дан. Member distributions после cutoff не заданы как неизбежные obligations: решение собственников должно быть отдельным scenario, исторический policy не гарантирует future cash.

## Неопределённость и горизонты

Known due dates могут находиться за пределами13 недель; сохраняйте их в inputs, но не помещайте в wrong week. Corporate long-stay service months могут дать collection уже в2027. Future employee/calendar rows включают даты за концом horizon, когда это необходимо для начисленного позднего периода. При признании нового future revenue сначала сдвиньте service dates, затем cash lag; исторические GL/bank не дописываются.

Business days в кейсе — Monday–Friday, без федеральных праздников. Если в пользовательском forecast нужен US federal banking calendar, внесите его как новый явно версионированный assumption и покажите timing variance. Параметры налогов/OTA/gateway/payroll не являются реальными юридическими ставками или текущими тарифами провайдеров.
''')

research=[
 ('SRC-MEWS-RES','Mews','Reservations — Connector API','https://docs.mews.com/connector-api/operations/reservations','Reservation state/resource assignment and service-order concepts','Separate reservation, room assignment and consumed nights','No native field/schema fidelity claimed'),
 ('SRC-MEWS-REV','Mews','Revenue management use case','https://docs.mews.com/connector-api/use-cases/revenue-management','Reservations, order items and resource blocks are distinct','OOO/OOS blocks and nightly folio items linked by IDs','Internal availability denominator explicitly chosen'),
 ('SRC-BOOKING','Booking.com','Understanding the Reconciliation API','https://developers.booking.com/connectivity/docs/reconciliation-api/understanding-the-reconciliation-api','Reservation-level payout reports break out commission and taxes','Gross-to-net merchant settlement and component mappings','API page described closed beta; not a claim of API access or exact OTA contract'),
 ('SRC-EXPEDIA','Expedia Group','Invoices and booking receipts','https://developers.expediagroup.com/rapid/lodging/manage-booking/booking-receipts?locale=en_US','Property collects guest payments versus Expedia collects; receipt and invoice responsibilities differ','Distinct agency/hotel collect and merchant collection accounting','Synthetic commission/tax/weekly-bank remittance policy; no exact native export or universal tax rule'),
 ('SRC-STRIPE','Stripe','Payout reconciliation report','https://docs.stripe.com/reports/payout-reconciliation','Payout reconciles batch transactions; bank deposit differs from charge','Captures/fees/balance transactions/payout/transit/bank separate','Synthetic fee2.75%+0.25 and calendar are not Stripe pricing promises'),
 ('SRC-GUSTO','Gusto','Payroll fundamentals','https://docs.gusto.com/embedded-payroll/v2026-02-01/docs/payroll-fundamentals','Gross pay, employee deductions, net and employer costs differ','Earned payroll gross-to-net with separate funding','No statutory withholding computation or native export claimed'),
 ('SRC-COSTAR','CoStar / STR','Glossary','https://www.costar.com/en-gb/gbr/products/str-benchmark/resources/glossary','ADR/occupancy/RevPAR use consistent room revenue and room-night drivers','Ratios recomputed from additive drivers','Internal OOO/OOS/comp policy is not certified STR reporting'),
 ('SRC-US2025','CoStar','US full-year 2025 hotel performance, released 2026-01-20','https://www.costar.com/products/str-benchmark/resources/press-releases/us-hotels-report-first-full-year-occupancy-revpar','National 2025 occupancy62.3%, ADR160.54, RevPAR100.02','Broad order-of-magnitude context for small mixed hotel/extended-stay portfolio','Not a direct comp set; different denominator/format/geography; not 2026 actual or local rate quote'),
 ('SRC-AHLA','AHLA','2026 State of the Industry one-pager','https://www.ahla.com/sites/default/files/State-of-the-Industry_2026_One-Pager.pdf','National context: operating cost and workforce pressure','Fictional rate growth/soft occupancy/cost pressure storyline','National trends do not verify property-specific wages, utility rates or margins')]
rr=[dict(source_id=a,organization=b,title=c,url=d,verified_date='2026-11-19',verified_concept=e,case_application=f,scope_limit=g) for a,b,c,d,e,f,g in research]
write_csv(OUT/'metadata/research_sources.csv',list(rr[0]),rr)
bench=[dict(benchmark_id='US-2025-'+metric,source_id='SRC-US2025',geography='United States all hotels',period='2025',metric=metric,value=value,unit=unit,report_date='2026-01-20',retrieved_date='2026-11-19',usage='external context only, not synthetic company actuals') for metric,value,unit in [('occupancy','0.623','ratio'),('adr','160.54','USD per sold room-night'),('revpar','100.02','USD per available room-night')]]
write_csv(OUT/'metadata/industry_context_benchmarks.csv',list(bench[0]),bench)
put('RESEARCH_AND_ASSUMPTIONS_RU.md','''
# Проверенные концепции и синтетические допущения

Проверка первичных источников выполнена2026-11-19. Внешние источники помогают выбрать корректные system concepts и экономический контекст; ни одна операция набора не скопирована у реального бизнеса.

- [Mews reservations](https://docs.mews.com/connector-api/operations/reservations) и [revenue management](https://docs.mews.com/connector-api/use-cases/revenue-management) поддерживают разделение reservation/service items/resource blocks. Здесь реализованы собственные flat CSV с общими IDs; соответствие конкретному native Export не заявлено.
- [Booking.com reconciliation](https://developers.booking.com/connectivity/docs/reconciliation-api/understanding-the-reconciliation-api) описывает payout components, commissions/taxes и reservation mapping. Это основание для отдельного settlement grain. API page обозначена как closed beta; набор не требует доступа к API.
- [Expedia invoices and booking receipts](https://developers.expediagroup.com/rapid/lodging/manage-booking/booking-receipts?locale=en_US) различает Property Collect и Expedia Collect: кто получает оплату гостя и выдаёт документы. Здесь channel contracts и timing синтетические; они не заявляются как универсальная схема налогообложения или точная текущая настройка Expedia.
- [Stripe payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation) различает payout batch и его transactions. Поэтому payment, processor balance, initiated payout и actual bank arrival не смешаны.
- [Gusto payroll fundamentals](https://docs.gusto.com/embedded-payroll/v2026-02-01/docs/payroll-fundamentals) различает earned gross, deductions/net и employer costs. Case payroll по собственным blended assumptions, без имитации statutory tax engine.
- [CoStar/STR glossary](https://www.costar.com/en-gb/gbr/products/str-benchmark/resources/glossary) проверен для room-night KPI concepts. Выбор исключать обе OOO/OOS категории является внутренним управленческим выбором; сравнение с официальной market series потребует другого policy mapping.
- [CoStar full-year2025 release, 20 January2026](https://www.costar.com/products/str-benchmark/resources/press-releases/us-hotels-report-first-full-year-occupancy-revpar): национальные occupancy62.3%, ADR USD160.54, RevPAR USD100.02. Это проверенный ориентир порядка величины, не comp set для трёх NC объектов. Более низкая blended rate апарт-отеля и собственный closure denominator ограничивают прямое сравнение; эти числа не подставлены в actuals или forecast. Research-only rows отдельно в metadata/industry_context_benchmarks.csv.
- [AHLA State of the Industry2026](https://www.ahla.com/sites/default/files/State-of-the-Industry_2026_One-Pager.pdf) даёт национальный контекст cost/workforce pressure. Это не региональная оценка для конкретного NC property и не подтверждение выбранных маржинальностей. Case ADR/occupancy/cleaning productivity — согласованные синтетические assumptions, не прогноз рынка.

## Явные параметры

| Параметр | Значение кейса | Граница |
|---|---|---|
| Hotel lodging tax | RAL/DUR11.25%, WIL12.5% | не statutory rates; long stays также облагаются, exemption не применяется |
| Ancillary / cancellation/no-show tax | 0% | модельное упрощение, не правовой вывод |
| Merchant OTA tax | OTA collects/remits lodging tax;2110 clearing погашается release | contractual synthetic assumption для EXPEDIA-style channel |
| Agency commission |15% earned room/fee net of credits | не реальная текущая Booking.com price quote |
| Merchant commission |18% earned room/fee net of credits | не реальный Expedia contract |
| Gateway fee |2.75%+USD0.25 per capture; refund fee0, original fee не возвращается | собственный параметр; не Stripe current tariff |
| Capture lag | prepaid nominally booking+2 calendar days, earliest window start; arrival collect for other guests | cancellation before capture voids authorization, only earned fee captured |
| Processor availability/payout |+2 business days, next Friday release, bank+1 business day | weeks exclude weekends only; no holiday calendar |
| Merchant earned release | same-week Saturday+7 days, bank+1 business day | отдельная selected trace release Oct31; clear source dates authoritative |
| Corporate payments | monthly invoicing; terms30/45;65% and35% tranches18 days apart | CO-00152-day delay from Aug2026; CO-0038-day delay |
| Security | DUR USD250, return3 business days after checkout | refundable liability, separate from final cleaning fee |
| Employee withholding |18% hourly,23% salary | blended assumed deduction; no W-4/state tax calculation |
| Employer tax |8.3% gross | synthetic; employer benefitUSD175 per employee/halfmonth with gross pay |
| Overtime | hourly >40h Monday-week,1.5× | case policy; no statutory compliance representation |
| Benefits funding | included in payroll2310 funding | not additional vendor-benefit bill/tax remittance |
| Operational productivity | hotel34/16 min departure/stayover; aparthotel48/32 departure/weekly | not certified cleaning norms |
| Laundry |USD3.90/set, USD4.35 from May2026 | synthetic vendor quote, not market benchmark |
| Supplies |USD1.45 hotel stayover,2.60 weekly,3.90 departure; +12% from June | immaterial expensed consumption, no artificial stock ledger |
| Shared allocation | physical keys60:52:44, largest-remainder cents | analytical zero-sum bridge; source_cost repeated reference |
| Budget approval |2024-10-15 for all24 months | original case planning baseline; never recast using generated actuals |
| Asset/rent policy | capitalize project≥USD2,500 and useful>12mo; monthly SL; rent expensed | no ASC842/USALI certification |

Никаких owner trust funds/property management rents, restaurant sales, franchise fee, sales tax nexus certification, FX, chargebacks и refundable-security deductions за damages не добавлено. Missing actual date отличается от actual monetary zero. Scientific/industry inputs не подменяют внутреннюю финансовую сверку: основной критерий — linked event consistency до цента и room-night.
''')

put('metadata/RELATIONSHIPS_RU.md','''
# Карта связей и grains

Машиночитаемая карта — `relationships.csv`, ключи/типы/partitions — `table_schemas.json`. Blank FK разрешён только при неприменимости или ещё не наступившем событии. В metadata condition channel_id=BOOKING/EXPEDIA задаёт разные targets одного settlement_id.

```mermaid
flowchart LR
  B[Booking] --> R[Room reservation]
  R --> A[Room assignment]
  A --> N[Actual consumed room-night]
  C[Room master + closures] --> V[Room/date capacity]
  N --> V
  N --> F[Earned folio line]
  F --> I[Corporate monthly invoice line]
  I --> AR[Invoice AR + receipt application]
  R --> P[Guest capture / advance liability]
  P --> APPL[Deposit application]
  APPL --> F
  P --> BT[Processor balance transaction]
  BT --> PO[Payout initiated]
  PO --> T[Cash transit]
  F --> OTA[Gross OTA AR + commission]
  OTA --> S[Merchant settlement components]
  S --> T
  T --> BANK[Actual bank arrival]
  N --> HK[Cleaning work / linen]
  HK --> W[Employee approved time + agency]
  W --> PY[Earned payroll / vendor bill]
  PY --> GL[GL double entry]
  F --> GL
  AR --> GL
  BANK --> GL
```

Никогда join двух фактов many-to-many только по reservation_id для sum money: несколько nights × несколько captures × несколько invoice lines умножат строки. Сначала агрегируйте каждый факт по целевому grain, либо соединяйте line-specific payment application/folio_line_id. Аналогично rooms/date ↔ tasks может иметь несколько tasks, нужны count DISTINCT task_id и preaggregation.

Group booking и group allotment различаются: bookings→booking_rooms→reservation; corporate group_blocks→group_pickups→reservation. Occupancy берётся из actual nights, а не количества blocks. Channel reservation export — mapping той же reservation, не дополнительная продажа.

Corporate invoice_line_id→folio_line_id — exact earned service mapping; GL invoices source только перекидывает1130→1100. Merchant settlement_line_id→folio_line_id→commission: folio net+tax−commission−OTA tax=net remittance. Agency commission settlement_id указывает на agency_invoice_id, merchant — на settlement_id.

Bill lines могут ссылаться на operational property/month composite в source_id: это описательная aggregation reference, не универсальный одноколоночный FK. По purchase_order_line_id и bill_line_id есть строгие receipt mappings. General ledger source_id — polymorphic key, source_system/source_table обязательны для join. Для allocation_id source_cost повторяется по recipients и donor; не суммируется.
''')

put('CLAUDE_HANDOFF_RU.md','''
# Готовое задание для Claude

Скопируйте текст ниже в Claude Code с рабочей папкой juniper_quay_data. Все исходники уже существуют; новые случайные facts не требуются.

---

Я строю демонстрацию AI FP&A для вымышленной Juniper Quay Hospitality LLC. Мне нужны reporting, Budget vs Actual, channel/unit economics, rolling forecast и13-week cash forecast. Программу и интерактивные dashboards строю в этом проекте отдельно от подготовки данных.

Сначала прочитай README_RU.md, COMPANY_PROFILE_RU.md, ACCOUNTING_SIGN_GUIDE_RU.md, KPI_DEFINITIONS_RU.md, CASH_FORECAST_INPUTS_RU.md, RESEARCH_AND_ASSUMPTIONS_RU.md. Затем metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, table_schemas.json, relationships.csv и RELATIONSHIPS_RU.md. Посмотри examples/TRACE_GUIDE_RU.md и два JSON trace; это copies, не дополнительные facts.

Основной период2024-11-01–2026-10-31, cutoff2026-10-31, USD, local service dates America/New_York. Principal operator, три property RAL60/WIL52/DUR44 keys, corporate shared centreCORP. Room revenue принадлежит LLC. Management for external owners отсутствует. Во всех будущих UI/скриншотах обозначай Demo company / Synthetic data. Не представляй кейс как результат внедрения у реального клиента или гостиничную accounting certification.

Читай CSV программно с UTF-8 BOM, comma delimiter, IDs как string, USD как Decimal/integer cents. Все physical parts таблицы берутся из schemas. GL лежит в sources/quickbooks/general_ledger/*.csv. Не печатай миллионы строк в чат. Нельзя загружать examples, validation controls, metadata, source ZIPs или planning copy/index как дополнительные факты тех же операций.

Сначала нормализуй данные, проверь PK/FK и grain, пересчитай сверки и сопоставь свои24 monthly results по компании и трём properties с validation/monthly_control_totals.csv. COMPANY уже включает CORP и properties — не суммируй этот row с property rows. Controls — reference expected results, не значения для dashboard вместо raw sources. Independent verifier reproducibility/verify_dataset.py повторно читает source CSV; его можно запустить из корня пакета: python reproducibility/verify_dataset.py .

Построй модель с отдельными facts:

1. Reservation snapshot + status/amendment history, multi-room mapping; separately actual consumed nights и room/date availability/closure.
2. Folio service charges/credits с room, ancillary, fee и tax components; checkout-exclusive consumption.
3. Direct gateway capture/refund, deposit applications, security, processor balances, initiated payouts, transit и actual bank arrivals.
4. OTA agency versus merchant economics: commission accrual/credit, agency invoice/payment, merchant gross-to-net settlement и bank.
5. Corporate contracts/blocks, earned monthly invoices, line mapping, advances, partial receipt applications и due-date aging.
6. Housekeeping approved tasks, employee actual time/weekly overtime, agency shifts, linen/laundry/supplies и одноразовый payroll/bill cost.
7. Vendor PO/receipt/bill/payment/open AP; capex versus routine repair, assets/depreciation/debt principal/interest.
8. GL P&L/BS/monthly TB, bank and subledger reconciliation; zero-sum analytical shared allocations.
9. Own marketing cost и direct funnel; platform attribution separately.
10. Frozen original budget и drivers; distinct forecast versions и explicit assumptions.

Критические правила:

- Future confirmed/on-books reservations после cutoff — bookings, не actual occupied nights и не earned revenue. Group block также не occupied/sold.
- Room/date capacity = physical−OOO−OOS для внутреннего availability. Sold occupancy=sold/available; ADR=net room after discounts/credits divided sold; RevPAR=net room/available. Comp/house-use не sold. Ratios пересчитывай из totals.
- Stay crossing month-end/cutoff признаётся night-by-night, а не целиком в booking/checkout month. Corporate invoice не создаёт revenue повторно.
- Lodging prepayment2200/2220 — deferred until consumed; refundable security2210 отдельно. Capture, payout и bank deposit не три продажи.
- Agency guest pays hotel gross, гостиница должна commission2010. Merchant gross earned room to1120, commission5000/2010, synthetic OTA tax2110; settlement clears gross to net. Не считать net bank payout всей выручкой.
- Credits/refunds отдельными событиями с original/parent IDs; не переписывай исходные charge amounts задним числом и не списывай один credit дважды.
- Employee withholding уже в gross; employer tax/benefit additional. Payroll earned и funded dates различаются; OctoberH2 payable — известный future cash out, без fabricated bank payment.
- Operations logs и vendor/payroll GL описывают один expense. Daily ad spend и monthly billing также один expense. OTA commissions separate from own media spend; overlapping Meta/Google booking values не company revenue.
- Assets/debt/distributions не expense целиком: depreciation/interest P&L, principal/distributions financing. Rent case simplification описана.
- CORP shared expense уже в company GL; bridge allocations sum0, source_cost repeated reference. Property contribution до/после shared показывай с названиями.
- GL signed TB = debit−credit; P&L activity, не cumulative revenue account balance. Opening отдельно. Budget income/expense positive, contra-revenue negative.

Для13-week forecast2026-11-01–2027-01-30 используй CASH_FORECAST_INPUTS_RU.md. Opening bank отдельно от clearing/transit; known_cash_inputs — COPY index, source balances альтернативны, не additive. Устранить overlap: open AP vs recurring prior month, current payroll liability vs future earned payroll, merchant net settlement vs gross AR/tax/commission, held advances vs future OTB collection, billed capex vs unreceived PO commitments. OTB corporate payments идут по service months и65/35 dates; merchant future cash рассчитывается по nightly weekly-release rule. New demand только remaining available capacity после OTB. Forecast assumptions могут меняться, historical actuals остаются историческими. Future due/expected dates не actual events.

После сверок можно реализовать Business Overview, Property/Channel Economics, Occupancy/ADR/RevPAR, Corporate AR, Operations, BVA, Rolling Forecast,13-week Cash и Data Quality. Выбери собственный стек. AI commentary должен показывать конкретные рассчитанные drivers и traceable source IDs, а forecast — версию assumptions и сценарий. Начни с краткой карты нормализованных grains и результатов собственных сверок, затем реализуй систему.

---
''')

# Trace copies from saved source exports. Selected batch headers can contain other reservations.
selection=json.loads((OUT/'metadata/trace_selection.json').read_text());reservations={r['reservation_id']:r for r in rows('pms/reservations')};folios=rows('night_audit/folio_lines');payments=rows('payments/transactions');applications=rows('payments/applications');balance=rows('payments/balance_transactions');payout=rows('payments/payouts');commission=rows('channel_manager/commissions');settlement_lines=rows('channel_manager/settlement_lines');settlements=rows('channel_manager/settlements');bank=rows('bank/statement');balances=rows('payments/reservation_balances')
traces=[]
for name,key in [('direct_prepaid','direct_prepaid_reservation_id'),('ota_cutoff','ota_cross_cutoff_reservation_id')]:
    rid=selection[key];r=reservations[rid];ff=[x for x in folios if x['reservation_id']==rid];tt=[x for x in payments if x['reservation_id']==rid];tids={x['payment_id'] for x in tt};bb=[x for x in balance if x['payment_id'] in tids];pids={x['payout_id'] for x in bb if x['payout_id']};cc=[x for x in commission if x['reservation_id']==rid];ss=[x for x in settlement_lines if x['reservation_id']==rid];sids={x['settlement_id'] for x in ss}
    trace=dict(copy_only=True,not_additional_facts=True,snapshot_date='2026-10-31',reservation_id=rid,scope_note='Selected reservation components only. Payout/settlement headers and their GL are full property batches and include other reservations; selected components alone do not sum to batch total.',source_records={
      'pms/reservations':[r],'pms/actual_stay_nights':[x for x in rows('pms/actual_stay_nights') if x['reservation_id']==rid],
      'planning/on_books_nights':[x for x in rows('planning/on_books_nights') if x['reservation_id']==rid],
      'night_audit/folio_lines':ff,'payments/transactions':tt,'payments/applications':[x for x in applications if x['reservation_id']==rid],
      'payments/balance_transactions':bb,'payments/payouts':[x for x in payout if x['payout_id'] in pids],
      'payments/reservation_balances':[x for x in balances if x['reservation_id']==rid],
      'channel_manager/commissions':cc,'channel_manager/settlement_lines':ss,'channel_manager/settlements':[x for x in settlements if x['settlement_id'] in sids]})
    bids={x['bank_transaction_id'] for x in trace['source_records']['payments/payouts']+trace['source_records']['channel_manager/settlements'] if x['bank_transaction_id']};trace['source_records']['bank/statement']=[x for x in bank if x['bank_transaction_id'] in bids]
    sourceids=set(tids)|pids|sids|{x['folio_line_id'] for x in ff}|{x['commission_id'] for x in cc}|{x['application_id'] for x in trace['source_records']['payments/applications']}
    gl=[]
    for path in schemas['quickbooks/general_ledger']['physical_files']:
        if not path.endswith('/2026-10.csv'):continue
        for g in read(path):
            if g['source_id'] in sourceids:gl.append(g)
    trace['source_records']['quickbooks/general_ledger']=gl
    jsonfile(f'examples/example_{name}_trace.json',trace);traces.append(trace)
dr=traces[0];ot=traces[1];dp=dr['source_records']['payments/transactions'];df=dr['source_records']['night_audit/folio_lines'];db=dr['source_records']['payments/reservation_balances'][0];of=ot['source_records']['night_audit/folio_lines'];oc=ot['source_records']['channel_manager/commissions'];osl=ot['source_records']['channel_manager/settlement_lines'];future_total=sumcol(dr['source_records']['planning/on_books_nights'],'booked_room_usd')+sumcol(dr['source_records']['planning/on_books_nights'],'booked_lodging_tax_usd');future_uncovered=max(Decimal(0),future_total-money(db['guest_advance_deposit_usd']))
put('examples/TRACE_GUIDE_RU.md',f'''
# Сквозные traces — copies из исходных CSV

JSON examples — сохранённые копии строк, не дополнительные facts. Все identifiers существуют в sources/. Для compactness показаны выбранные reservation components; payout/settlement headers и их GL относятся к целому property batch с другими reservations. Не пытайтесь приравнять одну reservation к целой weekly batch.

## Direct prepaid: {dr['reservation_id']}

RAL room101, booking2026-10-20, scheduled stay2026-10-29–2026-11-03, checkout exclusive. Один lodging capture2026-10-22; три breakfast charges по USD24 погашены из того же deposit, отдельного ancillary capture в этом trace нет. К cutoff потреблены3 ночи, ещё2 — OTB; actual checkout пустая. Фактический payment gross {dollars(sumcol(dp,'gross_amount_usd'))}; processor fee {dollars(sumcol(dp,'processing_fee_usd'))} отдельным expense.

1. pms/reservations даёт quote на5 ночей; это не весь actual October revenue.
2. payments/transactions: net to1010, fee5010, gross to2200.
3. Три actual stay nights и соответствующие folio lines дают earned room/ancillary net **{dollars(sumcol(df,'net_revenue_usd'))}**, tax **{dollars(sumcol(df,'tax_usd'))}**. Для будущих двух ночей folio/GL нет.
4. Deposit applications2200→1110 погашают earned charges, не создают cash/revenue повторно.
5. На cutoff lodging advance liability этой reservation **{dollars(db['guest_advance_deposit_usd'])}** частично покрывает будущие room+tax charges **{dollars(future_total)}**. После использования депозита на breakfast остаётся **{dollars(future_uncovered)}** incremental collection; это видно в booked_payment_terms. Уже удержанный deposit не является ещё одним future cash receipt.
6. Lodging capture balance transaction принадлежит Friday payout2026-10-30; expected bank2026-11-02, actual bank date blank на cutoff. Full batch payout не равен сумме одной reservation. Исторического November bank credit нет.

## OTA merchant across cutoff: {ot['reservation_id']}

WIL room101, scheduled/actual consumed stay2026-10-25–2026-10-29:4 ночи. Гостя собирает EXPEDIA-style merchant, hotel gateway capture для room charges отсутствует.

1. Earned folio revenue **{dollars(sumcol(of,'net_revenue_usd'))}**, tax **{dollars(sumcol(of,'tax_usd'))}**, gross OTA AR **{dollars(sumcol(of,'total_charge_usd'))}**.
2. Separate distribution commissions **{dollars(sumcol(oc,'commission_usd'))}**, expense5000/payable2010; gross room revenue остаётся в4000/contra.
3. Selected settlement components: gross−OTA tax−commission = **{dollars(sumcol(osl,'net_usd'))}** net remittance для этой reservation. Full settlement header содержит также другие reservations.
4. Release2026-10-31: clear1120 gross,2010 commission,2110 OTA tax; net to1020 cash-in-transit. Expected bank2026-11-02, actual bank date blank.
5. В hypothetical November forecast arrival переносит1020→1000; такой future actual cash не добавлен в source bank или GL. Net remittance не является новой room sale.
''')

put('VALIDATION_RU.md',f'''
# Независимая проверка сохранённых CSV

Проверка запускается отдельным process/script `reproducibility/verify_dataset.py`; он не импортирует generator modules и не читает его внутренние objects. Reads schema/manifest и source CSV заново; денежная арифметика Decimal/integer cents. Reference monthly controls также заново рассчитываются из raw sources.

Последний полный прогон: **{validation['check_groups']} check groups**, **{validation['evaluated_conditions']:,} evaluated conditions**, **{validation['failed_conditions']} failed conditions**. Точное покрытие и examples при ошибке — `validation/validation_report.csv`. Группы объединяют множество row-level assertions, не независимые аудиторские заключения.

Проверяются PK/FK/types/BOM/SHA/counts; actual cutoff;156×730 physical capacity; actual room overlap; closures из intervals; sold/comp/house-use; effective plans; folio/quote/discount/tax/credits; each journal balance; monthly TB; daily bank-to-GL; gateway capture/refund chronology/cumulative limits/fees/batches/transit; merchant/agency gross commission/tax/bank; invoice mapping/partial applications/aging; guest/security/corporate liabilities; vendor PO/receipts/AP/individual bill GL; approved housekeeping/time/agency/linen/bill; weekly overtime/gross-to-net/funding; fixed assets/depreciation/debt/tax; own advertising; original budget dates/drivers; allocation zero-sum; recurring due dates; all known cash categories; OTB monthly corporate timing; two cutoff traces.

Money tolerance0 cents, quantity tolerance0 nights/minutes. Ratios identities проверяются с Decimal tolerance0.00000001 до display rounding. USD6-decimal ADR/RevPAR и8-decimal occupancy в controls — display values. Объединённые KPI пересчитываются из raw numerator/denominator.

`validation/monthly_control_totals.csv` содержит96 строк (24×COMPANY/RAL/WIL/DUR), revenue splits, capacity, occupancy/ADR/RevPAR, commission/net ADR, HK cost, payroll, EBITDA before/after shared, original budget/BVA, cash movement и cutoff/month-end subledger balances. COMPANY не нужно ещё раз суммировать с properties.

Mutation sensitivity test хранит заведомо повреждённую копию только в scratch work/, меняет1 cent в folio, обновляет её source manifest и повторно запускает verifier. Успех теста означает обнаружение экономической ошибки даже после обновления SHA, а не прохождение испорченных данных. Результат — `validation/mutation_test_result.json`; повреждённая копия не входит в deliverables.

Границы: это автоматизированная внутренняя проверка synthetic case. Она не устанавливает полноту реального PMS, правомерность налоговых ставок или compliance гостиничного accounting standard. Независимый reviewer отдельно проверил principal economics, cutoff/settlements, refunds и forecast timing; его исправленные findings и финальный disposition см. `validation/REVIEW_RU.md`.
''')

put('reproducibility/README_RU.md','''
# Проверка и воспроизводимость

Python3.11+, standard library. Никаких реальных аккаунтов/API/секретов.

Из корня распакованного juniper_quay_data:

```
python reproducibility/verify_dataset.py .
python reproducibility/test_core.py
```

Verifier не импортирует генератор, source data читает с диска; выводит exit0 только при0 failures и пересоздаёт validation report/controls. Во время проверки не меняйте source CSV. Полный прогон может занять несколько минут.

Для новой сборки источников: `python reproducibility/build_dataset.py`. Default destination — соседняя папка juniper_quay_rebuilt. Для собственного destination задайте task-specific environment variable JQ_OUTPUT_DIR; all original sources deterministic seed20261119. Генератор не удаляет неизвестные stale files: для изменённого сценария используйте новую пустую destination. Затем запустите verifier с путём к новой папке. Rebuilding sources alone не создаёт ZIP/docs; write_deliverable_docs.py после verifier использует тот же JQ_OUTPUT_DIR.

test_core.py проверяет half-up cents, allocation conservation, checkout-exclusive cutoff и rejection unbalanced journal. mutation_smoke.py принимает путь dataset, создаёт отдельную scratch копию и проверяет, что сохранённый economic mismatch обнаружен независимо от обновлённого manifest. Он не нужен для обычного импорта данных.

Scripts исходно находились в work/ отдельного чата; никаких файлов других чатов они не меняют. Native API/export schemas не гарантируются.
''')
print(json.dumps({'docs_written':True,'trace_direct':dr['reservation_id'],'trace_ota':ot['reservation_id'],'tables':len(schemas),'validation_failed':validation['failed_conditions']}))
