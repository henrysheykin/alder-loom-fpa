# Signal Harbor Performance — пакет синтетических данных рекламного агентства

Полностью вымышленный американский performance marketing / digital advertising business. Это исходные данные для демонстраций AI reporting, Budget vs Actual, forecasting и 13-week cash forecast. Все компании, люди и операции синтетические; контакты используют example.com. Не представлять кейс как внедрение у реального клиента.

Факт: **2024-11-01 — 2026-10-31**, 24 полных месяца. Snapshot: **2026-10-31**, независимо от текущей даты. Валюта USD. Подготовлено 2026-11-19. Названия HubSpot, Harvest/Clockify, Gusto, Meta, Google и QuickBooks обозначают моделируемые источники. Это согласованные плоские extracts, а не точные native exports конкретной версии API.

## Быстрый старт

1. Распакуйте полный архив в один каталог. Не загружайте одновременно те же CSV из ZIP и из распакованной папки.
2. Прочитайте COMPANY_PROFILE_RU.md, ACCOUNTING_POLICY_RU.md и ASSUMPTIONS_RU.md.
3. Передайте Claude весь каталог и текст из CLAUDE_HANDOFF_RU.md. Все необходимые инструкции находятся в пакете; исходный чат не нужен.
4. Загружайте факты только из sources/. Metadata examples, validation controls, каталоги и архивы являются пояснениями/контролями.
5. Для повторной независимой проверки: `python tools/validate_dataset.py .` из корня распакованного пакета. Нужен Python 3.10+ без сторонних библиотек. Вызов перезапишет только отчёты validation/.

В пакете **80 логических таблиц, 218 исходных CSV и 135,757 строк**. Основные объёмы: 26,049 time entries, 11,980 GL lines, 3,897 сбалансированных journals; 86 контрактов/SOW, 126 CRM deals, 24 сотрудников в кадровой истории, 6 фрилансеров. Активный штат: 18 → 22. Начальных retainer-клиентов 14, в конце 20; всего 22 обслуживаемых retainer-клиента и 6 компаний-проспектов.

| Источник | Логических таблиц | CSV/частей | Строк |
|---|---:|---:|---:|
| hubspot | 6 | 6 | 2,726 |
| contracts | 8 | 8 | 2,168 |
| timekeeping | 7 | 53 | 42,142 |
| gusto | 6 | 6 | 8,366 |
| freelancers | 6 | 6 | 1,004 |
| meta_ads | 5 | 28 | 26,703 |
| google_ads | 5 | 28 | 26,703 |
| delivery | 4 | 4 | 2,707 |
| quickbooks | 17 | 40 | 20,677 |
| bank | 3 | 26 | 1,053 |
| planning | 8 | 8 | 1,428 |
| finance | 5 | 5 | 80 |

Полные определения: metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, relationships.csv, table_schemas.json. Каждый исходный CSV указан в metadata/file_manifest.csv с количеством строк, размером и SHA-256.

## Пять разных сумм

| Понятие | Что означает | Основной источник |
|---|---|---|
| Agency fee revenue | Заработанная плата за фактически оказанные услуги, за вычетом fee concessions | delivery/recognition_events; accounting GL accounts 4000–4090 |
| Client media spend | Расход клиента на рекламу на собственных ad accounts; 100% CLIENT_DIRECT | meta_ads и google_ads daily_metrics |
| Contract value | Минимальная договорная плата за весь срок SOW, либо отдельно обозначенная оценка/ceiling T&M | contracts/contracts; смотреть contract_value_basis |
| Invoices | Выставленные требования оплаты; могут опережать или отставать от оказания услуг | quickbooks/client_invoices + client_invoice_lines |
| Collected cash | Фактически полученные агентством деньги в банке | quickbooks/client_receipts, receipt_applications и bank/transactions |

За 24 месяца net fee revenue = USD 6,969,364.35; client media spend = USD 49,112,237.64. Эти суммы **нельзя складывать**. В октябре 2026 заработано USD 331,746.65, выставлено gross invoices USD 350,238.36, получено client cash USD 357,676.42; клиентами потрачено на platforms USD 2,680,693.85.

## Критические правила загрузки

- Все CSV: запятая, UTF-8 с BOM (`utf-8-sig`), ISO dates YYYY-MM-DD, month YYYY-MM; decimal USD с точкой и двумя знаками. IDs и account codes — строки. True/False — строковые представления boolean.
- Считайте деньги через Decimal или целые центы. Google cost_micros делить на 1,000,000; это копия spend, а не дополнительный расход.
- Пустое значение — событие ещё не произошло/неприменимо; не превращайте пустой actual_approved_date или actual_funding_date в факт.
- Для partitioned tables объедините все части внутри папки. В general_ledger, daily_metrics, daily_capacity, timesheets и bank/transactions данные разбиты по 24 месяцам. Не ожидайте одноимённый одиночный CSV.
- Связи циклические: сначала загрузите таблицы, затем применяйте relationship map. Generic GL source_id, bank reference_id и страховой OPEN-INS-2024 — контекстные ссылки; их правила в metadata/join_guide.csv.
- Opening TB отдельно, дата 2024-10-31. Opening-item invoices, AP и payroll — supporting subledgers начального баланса; не включайте их в расходы/выручку окна.
- P&L считать по activity журнала или period_debits/period_credits. closing_signed_balance временных счетов накоплен с начала окна; годовых closing entries нет.
- Имена систем — модель интерфейса данных. Один агрегированный payroll debit и monthly media statements являются явными упрощениями.

## От двойного счёта защищают эти связи

1. Признанная плата, invoice и bank receipt — три стадии одной операции. CRM pipeline и signed bookings не создают фактическую выручку.
2. Retainer/fixed time является billable delivery, но не дополнительным hourly invoice. Только approved T&M hours × effective role rate дают почасовую плату. Submitted October time не признаётся.
3. Payroll earnings и GL — один expense. gusto/cost_allocations распределяет его по проектам, bench/internal и paid leave; это не второй расход.
4. Freelance approved_work признаёт expense и accrued liability. Received invoice переносит liability 2200 → AP 2000. Payment погашает AP. Эти три источника не суммируются как три расхода.
5. Media daily metrics и monthly platform statements — детализация одного клиентского media spend. Он отсутствует в agency GL, bank и AP. Pass-through нет.
6. Meta/Google conversions/value могут пересекаться. В пакете нет deduplicated client sales fact, поэтому attribution нельзя выдавать за общую выручку клиента или агентства.
7. Signed_future_commitments — копии будущих строк billing_schedule с overlap_key. Уже выставленный invoice исключается из будущих billings; оплаченный ноябрь–январь retainer не создаёт нового cash inflow при признании revenue.
8. AR/AP/payroll/contractor balances и их детальные commitments описывают одни и те же обязательства. Применяйте overlap keys; баланс и детализацию нельзя складывать.
9. Owner distributions и principal repayments — financing; expense только interest. Employee withholding уже внутри gross pay.

## Cutoff и cash forecasting

На 2026-10-31: cash USD 653,775.09; AR USD 101,940.05; AP USD 56,561.20; earned unbilled fees USD 85,517.65; deferred fees USD 47,312.00; earned-unfunded payroll USD 97,204.42; accrued uninvoiced contractors USD 24,552.00; loan principal USD 60,000.00.

Payroll за 16–31 октября финансируется по графику 2026-11-02; фактического ноябрьского списания нет. Будущие signed invoices, ожидаемые сборы AR, recurring vendor commitments, действующие salary rates и debt schedule доступны отдельно. Начало 13-week forecast — 2026-11-01; можно показывать недели понедельник–воскресенье с первой неполной неделей или явно выбрать последовательные 7-дневные интервалы. Не теряйте 1 ноября и конец горизонта. Forecast не рассчитан заранее.

## Сверки

Независимый validator перечитал сохранённые CSV: **215 групп, 5,169,284 проверенных условий, 0 ошибок**. Финансовые roll-forwards и двойная запись сверяются до цента. validation/monthly_control_totals.csv содержит 24 контрольных строки; это эталон сверки, а не источник для dashboards. validation/validator_mutation_tests.csv показывает обнаружение 8 намеренных искажений на изолированных временных копиях. Основной факт остаётся согласованным.

Это проверка числовой целостности синтетического кейса, не независимый аудит и не заявление о соответствии стандартам отчётности. Ограничения и упрощённая policy — в ACCOUNTING_POLICY_RU.md и ASSUMPTIONS_RU.md. Проверенные официальные источники — RESEARCH_NOTES_RU.md и metadata/research_sources.csv.

Отдельные ZIP по 12 источникам имеют одинаковый корень signal_harbor_data/. Их можно объединять, сохраняя пути. Общие metadata/README/validator идентичны. Для полной межсистемной проверки нужны все источники. Примеры в metadata/example_*_trace.json помечены `illustrative_copies_do_not_load_as_facts`.
