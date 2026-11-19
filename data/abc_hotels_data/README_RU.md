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
- **95 логических таблиц**, **235 исходных CSV**, **1,399,337 исходных строк**. В GL **567,058 строк**, **209,262 сбалансированных journals**.
- **21,371 room reservations**, **76,313 actual occupied room-nights**, 33 сотрудника.
- Выручка первых 12 месяцев: **USD 6,180,808.43**, последних 12: **USD 6,165,172.31**. Выручка включает earned ancillary и fees, исключает tax.
- Bank на cutoff: **USD 2,756,844.48**. Это один общий счёт. Балансы cash по property являются внутренней аналитикой движений одного счёта, а не отдельными банковскими счетами.

## Источники

| Папка sources/ | Таблиц | Строк | Назначение |
|---|---:|---:|---|
| pms | 13 | 236,603 | Principal room reservations, masters, actual stay nights; custom synthetic flat extracts. |
| availability | 2 | 114,048 | Physical room/date ledger; additive capacity; OOO/OOS separate. |
| night_audit | 3 | 125,459 | Signed actual service charges and tax liabilities. Not checkout-date recognition. |
| channel_manager | 7 | 40,068 | Booking-style agency, Expedia-style merchant, gross-to-net settlements and commissions. |
| payments | 6 | 95,656 | Captures/refunds, liability applications, gateway clearing/transit, refundable security. |
| corporate_billing | 9 | 42,914 | Companies/contracts, block allotments, earned invoices, partial receipts, advances. |
| operations | 7 | 111,587 | Approved labor, laundry, consumables, agency and maintenance source detail. |
| procurement | 5 | 1,095 | POs, acceptance receipts and commitments; operating supplies expensed on receipt. |
| gusto | 7 | 36,529 | Effective rates, schedules, approved actual minutes, weekly overtime, earned/funded payroll. |
| fixed_assets_finance | 6 | 230 | Opening asset pools, capex, depreciation, debt, hotel tax remittances, member distributions. |
| marketing | 4 | 6,720 | Daily ad cost, billing, overlapping platform-attributed booking values, direct funnel. |
| quickbooks | 9 | 574,820 | COA, opening TB, GL, vendor AP, monthly TB. Authoritative financial actuals. |
| bank | 2 | 5,285 | One consolidated USD account, actual posted cash and month-end balances. |
| planning | 15 | 8,323 | Original pre-period budget; OTB future nights and explicit cash forecasting inputs. No future actuals. |

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

Текущий independent verifier: **189 групп**, **27,426,571 проверенных условий**, **0 ошибок**. См. `validation/validation_report.csv`, `validation/validation_summary.json`, `VALIDATION_RU.md` и mutation-test result. Контрольные totals вычислены из сохранённых source CSV, без импорта генератора.

`metadata/file_manifest.csv` содержит counts/bytes/SHA-256 каждого source CSV. `metadata/package_manifest.csv` покрывает остальные файлы пакета, кроме самого manifest и integrity report с их self-reference. Архивные SHA-256 находятся в download index рядом с ZIP.

В `reproducibility/` лежат генератор, независимый verifier, тесты и инструкции. Генератор детерминирован по seed 20261119; он создаёт согласованные события, затем раздельные source extracts. Репликация источников не требует облачных аккаунтов.
