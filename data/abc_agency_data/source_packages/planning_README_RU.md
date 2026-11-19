# Источник planning — часть единого demo-пакета

Signal Harbor Performance LLC; полностью синтетические данные, USD. Факт 2024-11-01 — 2026-10-31; cutoff 2026-10-31.

Этот source ZIP содержит 8 CSV/частей, 8 логических таблиц, 1,428 строк только своего источника. Описание: Immutable original budgets, capacity plans and cutoff-known commitments/collection assumptions.

Каждый ZIP имеет одинаковый корень signal_harbor_data/. Общие docs, metadata, validator, controls и illustrative copies одинаковы во всех 12 source ZIP. Источники можно распаковать в один каталог. Для полной FK/финансовой проверки нужны все 12 источников либо полный архив. Schema/catalog описывают всю модель, поэтому остальные таблицы не следует заменять случайными фактами при чтении одного ZIP.

Sources — единственный факт. Metadata examples, monthly controls и repeated common files не создают дополнительных операций. Direct client-funded media никогда не становится agency cash/expense/revenue. Payroll allocations и contractor AP — представления тех же расходов, не второй расход. Подробные правила в README_RU.md и ACCOUNTING_POLICY_RU.md; готовое задание — CLAUDE_HANDOFF_RU.md.
