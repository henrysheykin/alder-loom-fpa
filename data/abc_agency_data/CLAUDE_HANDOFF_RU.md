# Готовое задание для Claude

Скопируйте текст ниже в Claude Code/среду Claude с доступом к распакованному каталогу. Если используете веб-интерфейс с ограничениями загрузки, передавайте source ZIP по очереди и общие metadata; не создавайте дубликаты фактов.

---

Я строю демонстрацию AI-автоматизации FP&A для полностью вымышленного американского рекламного агентства Signal Harbor Performance LLC. Данные подготовлены; не генерируй новые случайные actual facts. На интерфейсах и demo screenshots показывай «Demo company / Synthetic data».

Факт 2024-11-01 — 2026-10-31, 24 полных месяца; snapshot строго 2026-10-31. Валюта USD. Договорные будущие service/due dates и commitment schedules допустимы, будущих actual payments/revenue/approvals нет. 18→22 сотрудников, 6 фрилансеров, retainers, fixed distinct-deliverable projects и approved-hour analytics. Все client media budgets оплачиваются клиентами напрямую.

Начни с README_RU.md, COMPANY_PROFILE_RU.md, ACCOUNTING_POLICY_RU.md и ASSUMPTIONS_RU.md. Затем metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, table_schemas.json, relationships.csv, join_guide.csv, kpi_definitions.csv и relationship_map.mmd. Примеры metadata/example_*_trace.json — иллюстративные копии записей, не дополнительные факты.

Читай CSV программно, UTF-8 BOM, текстовые IDs и account codes, Decimal/целые центы. Не печатай большие таблицы в чат. Источник фактов только sources/. Объедини monthly partitions в одну логическую таблицу: GL, daily media, timesheets, daily capacity, bank transactions. Metadata, validation, исходные ZIP и illustrative copies не являются новыми операциями. Сначала загрузи все таблицы, затем проверь циклические FK associations.

Построй нормализованную модель:

1. CRM companies/leads/deals, наблюдаемую stage history и open pipeline snapshots. Open pipeline не должен включать signed won contracts. Quote, lifetime contract value и hourly ceiling не являются actual revenue.
2. Contract/SOW versions, renewals, change orders, monthly terms и billing schedule; agreed deliverables и effective hourly rate cards.
3. Daily capacity, approved time, leave и frozen allocations. Раздели delivery-team utilization и firmwide utilization. Retainer/fixed billable time включено в цену, без автоматического hourly overage invoice.
4. Payroll earned periods отдельно от bank funding; project cost allocations — view уже понесённого расхода. Freelance accepted work отдельно от invoice/AP и payment.
5. Client-owned platform spend/attribution отдельно от agency fee revenue. Сопоставь campaign→ad_account→client→effective contract. Client media отсутствует в agency GL и bank. Meta/Google conversion values могут пересекаться; общей deduplicated client sales fact нет.
6. Service obligations/approvals и recognition_events отдельно от client invoices/credits и cash applications. Deferred billed-but-unearned и earned-unbilled активы сверять по service_id/contract_id.
7. Ledger monthly P&L, opening balance и monthly TB, AR/AP schedules, bank reconciliation. Signed GL balance = debit−credit. Monthly P&L считать по activity; closing balances PL накоплены с начала окна, annual closing entries отсутствуют.
8. Immutable original annual budgets, department/headcount/capacity plans и cutoff-known future commitments.

Сверки обязательны до визуализации: PK/FK, time capacity/approval, effective rates, employee cost→project+internal+leave, accepted freelancer cost→accrual→AP→payment, percentage fees versus client media, service revenue/invoice/deferred/unbilled bridge, partial cash/credits/AR, AP, balanced journals/GL/TB, bank cash и отсутствие future actuals. Запусти `python tools/validate_dataset.py .` и независимо сопоставь собственные 24 monthly aggregates с validation/monthly_control_totals.csv. Не подставляй готовые control totals вместо расчёта raw sources.

Критические anti-double-counting правила:

- Agency fee revenue, client media, contract value, invoice и cash — разные метрики; не суммируй их.
- Client media и platform attributed conversion value не являются ни revenue, ни expense/cash агентства.
- Invoice создаёт AR и deferred либо погашает unbilled asset; earning происходит по service approval. Receipt уменьшает AR без повторной выручки.
- Credit notes уменьшают AR и net fees отдельно; original invoice/service не переписаны.
- Gusto allocations не добавляются к salary GL. Весь employer cost распределяется до цента. Project contributions и consolidated gross profit отличаются на delivery bench/internal/paid leave; operations payroll идёт ниже gross profit.
- Freelancer approved_work уже создаёт expense5010/accrual2200. QB invoice только 2200→AP2000, payment AP→bank; не дебетуй expense повторно.
- Opening-item invoices/AP/payroll и initial unbilled/deferred — supporting opening balances, не текущий доход/расход. November funding opening payroll не является новым November expense.
- Debt principal и owner distributions — financing, только interest является expense.

После проверенной модели создай reporting, Budget vs Actual, client/project contribution, gross margin/utilization, effective billable rate, scope overrun, revenue per employee, DSO/overdue AR, renewals/churn и contracted versus pipeline forecasting. Выбор стека и интерфейса за тобой; эта задача передаёт исходные данные, готовых dashboards в пакете нет.

Для 13-week cash forecast от 2026-11-01 используй opening bank cash на cutoff, existing AR и collection expectations, actual open AP, unfunded October payroll, accepted-uninvoiced contractors, current salary rates/capacity plan, recurring next cycles, signed billing schedule и debt service. Выбери и покажи week convention, сохрани полное покрытие первых/последних дней горизонта. Future variables/unsold work/pipeline — scenarios с вероятностями и явными assumptions; не actuals и не гарантированные fees.

Устраняй overlap: signed_future_commitments — копия future billing_schedule по schedule_line_id; existing AR invoice не добавляй снова как future invoice; payroll_commitments уже покрывает 2100/2110/2120, contractor_accruals покрывает 2200, open AP bills покрывают2000. Из recurring obligation добавляй новые service cycles, не current_open_bill_id второй раз. CLI-002 November–January fee уже invoiced and collected in October; future earning не создаёт будущего cash поступления. Unbilled approved October work ещё можно выставить по расписанию, но revenue за октябрь второй раз не признаётся. Не повторяй discretionary owner distributions как обязательный outflow.

AI-комментарий должен ссылаться на рассчитанные метрики и конкретные client/contract/source IDs. Заданные stories: CLI-001 media grows with flat fee; CLI-003 scope creep + October reprice + July credit; CLI-004 delayed partial collections; CLI-005 churn и August–September utilization decline; FREE-004 video rate increase; CLI-002 paid future quarterly service.

Начни с краткой карты данных, найденных границ факта и результата сверок. Затем реализуй выбранное приложение. Вопросы о рутинных параметрах решай по документации/assumptions; не выдумывай реальные клиентские данные или проведённый audit.

---
