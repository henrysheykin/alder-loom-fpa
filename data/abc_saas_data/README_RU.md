# RelayNest — исходные данные SaaS для AI FP&A

Полностью вымышленная американская компания, синтетические контакты и операции. Кейс предназначен для демонстрации автоматизации reporting, Budget vs Actual, rolling forecast и 13-week cash forecast. Это связанные плоские source extracts, моделирующие несколько систем; они не получены из реальных аккаунтов и не заявляются как точный native export конкретной версии API. На будущих интерфейсах показывайте «Demo company / Synthetic data».

## Быстрый старт

1. Распакуйте полный ZIP с сохранением каталогов.
2. Передайте Claude файл CLAUDE_HANDOFF_RU.md и доступ к распакованной папке. В Claude Code откройте эту папку как рабочий каталог.
3. Прочитайте COMPANY_PROFILE_RU.md, ACCOUNTING_POLICIES_RU.md и METRICS_DEFINITIONS_RU.md.
4. Изучите metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, relationships.csv и table_schemas.json. Читайте большие CSV программно.
5. Сравните собственные расчёты с validation/monthly_control_totals.csv. Контроли и примеры не являются дополнительными исходными фактами.

Если удобнее переносить источники по частям, используйте архив справки/метаданных и отдельные ZIP. Для сквозной сверки нужен весь комплект источников. Верхний DOWNLOAD_INDEX_RU.md рядом с архивами содержит ссылки и размеры.

## Фиксированный период

- Факт: **2024-11-01 — 2026-10-31**, 24 полных месяца. Snapshot as of **2026-10-31**.
- Валюта USD; даты ISO; все IDs читаются текстом.
- Исторические строки с record_scope=opening_support сохраняют документальные основания начальных остатков и историю контрактов. Их нельзя включать в новые продажи/расходы 24-месячного периода.
- Future service coverage уже выставленных годовых счетов, scheduled cancellations, due dates, известные договоры и планы разрешены. Будущих actual payments и earned postings в GL нет.
- Наличие future_unearned в revenue schedule означает оставшееся обязательство. Actual_posting_date у таких строк пуст.

## Объём

**16 источников, 78 логических таблиц, 147 исходных CSV, 2 732 768 строк.** Словарь содержит 673 описаний колонок. История GL и две большие таблицы дневной product activity разделены на 24 месячных partition каждая; остальные таблицы представлены одним CSV.

| Каталог sources/ | Таблиц | CSV | Строк |
|---|---:|---:|---:|
| stripe_billing | 14 | 14 | 91 204 |
| stripe_payments | 5 | 5 | 37 115 |
| contracts | 2 | 2 | 22 923 |
| revenue_accounting | 2 | 2 | 30 303 |
| product_analytics | 6 | 52 | 2 316 743 |
| hubspot | 5 | 5 | 2 610 |
| aws | 4 | 4 | 75 982 |
| gusto | 6 | 6 | 2 404 |
| quickbooks | 14 | 37 | 143 189 |
| bank | 3 | 3 | 429 |
| meta_ads | 3 | 3 | 2 217 |
| google_ads | 3 | 3 | 2 217 |
| marketing | 2 | 2 | 4 660 |
| procurement | 2 | 2 | 18 |
| planning | 6 | 6 | 752 |
| finance | 1 | 1 | 2 |

## Компания и контроль среза

RelayNest Workflow, Inc., Denver, Colorado: платформа согласования задач, workflow и автоматизаций для небольших B2B-команд. Три seat-based плана, monthly/annual billing, 14-дневные free trials. Usage-based add-ons не используются.

- 1004 платных договоров, допущенных в MRR по описанной grace policy; 25 действующих сотрудников.
- Closing MRR: USD 464754.50; ARR: USD 5577054.00.
- Октябрьская recognized revenue: USD 465135.38; net billings: USD 628776.91; bookings: USD 638736.91.
- Actual bank cash: USD 4555836.68; processor balance: USD 20692.16; payouts in transit: USD 47970.68.
- AR: USD 17547.60; AP: USD 92628.40; deferred revenue: USD 1663520.30; earned unfunded payroll: USD 157643.87.

Эти суммы имеют разный экономический смысл. Annual upfront cash не является выручкой одного месяца. Подписанный будущий контракт входит в bookings по принятой политике, но ещё не входит в active MRR.

## Форматы

CSV: запятая, UTF-8 BOM, decimal USD с точкой и двумя знаками. Для Python используйте encoding='utf-8-sig', Decimal или integer cents. Пустое поле означает неприменимость/отсутствие уже состоявшегося события, а не ноль. Boolean записан как True/False.

Все *_end_exclusive и effective_to исключают конечную дату; start включается. Интервалы означают календарные дни с границами в 00:00 UTC; это собственная нормализованная конвенция кейса. Семантика отдельных native API полей не подменяется нашими именами.

## Проверка и воспроизводимость

Сохранённые CSV перечитаны отдельным валидатором: **322 групп, 25 921 383 проверенных условий, 0 ошибок**. Файл validation/validation_report.csv содержит результаты групп; validation/summary.json — точные объёмы; validation/monthly_control_totals.csv — 24 месячных сверки.

Команда после распаковки:

    python scripts/validate_dataset.py --root .

Нужен Python 3.10+ и только стандартная библиотека. Валидатор не импортирует генератор и его функции округления. Повторный запуск обновляет только validation files.

Исходный генератор, денежное ядро и тесты находятся в scripts/reproduction/. По умолчанию генератор требует явный целевой каталог, чтобы пересборка не затёрла распакованный кейс; команда описана в scripts/REPRODUCTION_RU.md.

metadata/file_manifest.csv содержит row counts, bytes и SHA-256 каждого source CSV. package_inventory.csv содержит SHA-256 остальных включённых файлов и источников, кроме самого inventory.

## Примеры связей

metadata/examples/annual_invoice_to_cash.json — annual invoice → credit → refund → recognition/deferred → processor → payout → bank → GL.

metadata/examples/lifecycle_mrr_trace.json — цены и интервалы одного subscription с изменениями и reactivation.

metadata/examples/cloud_payroll_trace.json — cloud shared/tenant и support COGS/OPEX allocation.

Все примеры — **иллюстративные копии записей, не дополнительные факты**. Пакет не содержит готовых dashboards, сайта или презентации.
