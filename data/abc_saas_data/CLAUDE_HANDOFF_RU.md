# Готовое задание для передачи в Claude

Скопируйте текст ниже в Claude Code либо среду Claude с доступом к распакованной папке. Большие файлы читайте программно; не вставляйте миллионы строк в чат.

---

Я строю демонстрацию AI FP&A для **вымышленной** американской B2B SaaS RelayNest Workflow, Inc. Все исходные данные уже подготовлены и связаны; создавать новые случайные факты не нужно. Это source package для reporting, forecasting, Budget vs Actual и 13-week cash forecast. На пользовательских интерфейсах показывай Demo company / Synthetic data; не представляй это внедрением у настоящего клиента.

Факт 2024-11-01 — 2026-10-31, исторический snapshot as of 2026-10-31. Валюта USD. Текущая календарная дата не меняет cutoff. Есть opening_support, известные future service periods, expected due/arrival dates и планы; будущих actual payments и earned revenue нет.

Сначала прочитай README_RU.md, COMPANY_PROFILE_RU.md, ACCOUNTING_POLICIES_RU.md, METRICS_DEFINITIONS_RU.md и ASSUMPTIONS_RU.md. Затем metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, relationships.csv и table_schemas.json. Источники находятся только в sources/. Примеры metadata/examples/* — иллюстративные копии существующих записей, не новые факты. Validation controls — ожидаемые результаты сверки, не источник метрик для дашборда.

CSV с UTF-8 BOM, comma delimiter, ISO dates, IDs как text, деньги Decimal/целые cents. Все *_end_exclusive/effective_to исключают конечный день. Объедини 24 monthly partitions каждой большой логической таблицы. Не загружай второй раз те же CSV из отдельных ZIP.

Первый этап:

1. Построй карту источников и grain, выполни PK/FK/type/date checks.
2. Восстанови historical subscription states/items/prices и MRR на каждую месячную границу.
3. Независимо построй MRR bridge, cohorts, платные accounts, purchased seats и product active users.
4. Отдельно вычисли bookings, gross/net billings, recognized revenue, captures/refunds, processor balance, payouts in transit и actual bank cash.
5. Построй ledger-based P&L, balance sheet schedules, AR/AP/deferred/payroll/prepaid/fixed-asset rollforwards. Opening TB отдельно; period P&L по activity.
6. Сверь 24 месяца с validation/monthly_control_totals.csv, не подменяя собственный расчёт контрольной таблицей. Выполни scripts/validate_dataset.py при доступном Python.

Обязательные правила:

- MRR берётся из status/item history, не из current snapshot, invoices, payments или recognized revenue. Active/past_due eligible только в 21-day grace; canceled/unpaid/trial/not_started исключены. Scheduled cancellation сохраняет MRR до effective end.
- Annual net recurring amount / 12 с per-subscription HALF_UP cent rounding. ARR=12×такой MRR. One-off goodwill/taxes/old annual revenue не входят в MRR.
- New/expansion/contraction/churn/reactivation учитываются по всем effective переходам, включая несколько в одном месяце. Acquisition cohort — первое paid-tier обслуживание, не reactivation.
- Bookings — подписанное новое noncancelable commitment и amendments. Open pipeline не bookings. Подписанный 26 октября future-start контракт имеет bookings, но пока ноль actual MRR/invoice/revenue/cash.
- Annual upfront billing/capture создаёт deferred, а earned revenue распределяется по service days. Future_unearned schedule не actual posting. При dunning credit зеркально отменяет оставшиеся исходные allocations; не добавляй лишние центы после отключения.
- Credit-note face positive, credit lines negative. Refund — cash settlement кредитного обязательства; AR уменьшается только ar_credit_amount. Failed attempts дают ноль cash. Partial payments и due dates читай из collection_terms.
- Stripe invoice и accounting mirror — одна продажа/AR. Receipt/charge/payout/bank — стадии одних денег. Source bill/allocations/AP/GL — один expense.
- Production cloud, support allocations и fees входят в COGS по описанной политике; payroll allocation не новый расход. Customer success часть 20% — OPEX, engineering — R&D OPEX.
- Monthly salary earned и payroll funding относятся к разным датам. На срезе вторая половина октября accrued, actual funding ещё не произошёл.
- Daily ads, monthly billing и GL отражают одну собственную рекламу. Platform claims могут пересекаться; неполные first-party links нельзя дорисовывать как точные matches.
- Equity funding не revenue/MRR/bookings. Opening support не новый actual P&L периода. Доходные/расходные TB balances накопительные, месяцы считай по activity.
- Approved budget immutable и утверждён до начала факта. Future hiring requisitions не actual employees.

После сверок реализуй на выбранном стеке Business Overview, MRR/ARR Bridge & Retention, Revenue vs Billing vs Cash, Budget vs Actual, Department Spend, Rolling Forecast, 13-week Cash Forecast и Data Quality/Reconciliation. Это следующий этап работы: в исходном пакете dashboards ещё нет.

13-week forecast as of 2026-10-31: окно 2026-11-01 — 2027-01-30. Создай отдельную forecast version и assumptions. Используй bank cash, expected processor receipts, AR/renewals с учётом scheduled cancels, signed future start, AP, unfunded payroll, salaries, recurring vendors, cloud/ads drivers и hiring scenario. Устраняй overlap AP/obligations/contract cycles. Не прогнозируй повторный cash за уже оплаченные будущие annual service.

Комментарии AI должны ссылаться на рассчитанные факты и объяснимые источники: price migration/grandfathering, annual mix, July–August churn/incident, August cloud step-up, salary/hiring changes. Если выбранное определение retention/CAC/LTV отличается от документации, назови его явно и сохрани исходное как отдельную метрику.

Начни с краткой карты данных и проверенных сверок, затем переходи к реализации.

---
