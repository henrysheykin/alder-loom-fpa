# Допущения и границы кейса

Это вымышленный demo business с заданной экономической историей. Отраслевые источники использованы для проверки понятий и масштаба ролей; цены, ставки, налоговые параметры и календарные правила набора выбраны автором модели. Они не являются тарифами HubSpot/Gusto/Meta/Google/QuickBooks или реальными законодательными ставками.

Полный машинный перечень: metadata/assumptions.csv (A01–A30). В ACCOUNTING_POLICY_RU.md подробно описаны earning, invoicing, cash, opening balances, payroll allocation и contractor accrual.

Ключевые упрощения: одна валюта и один банк; только direct-funded client media; salaried full-time staff без overtime; условные payroll tax/withholding/benefit rules; отсутствие sales tax/corporate income tax модели; один агрегированный provider cash debit; monthly media billing consolidation; selected company holidays; fixed equipment base; нет FX, bad-debt writeoffs, client cash refunds, disputes/chargebacks, credit cards и pass-through media.

Fee model не означает, что revenue должна равняться invoices или cash. Lifetime signed value не является отчетной revenue. Annual T&M quote и spending ceiling не гарантируют future fees. Будущая variable spend fee ограничена известным minimum в commitment schedule; upside требует forecast media assumptions.

Original budget не использует поздние scope creep, churn, collection delays или contractor rate increases задним числом. Budgets хранятся рядом с фактами как отдельные frozen management records, а не как результат подгонки actuals. Data-quality упражнения не подмешаны в sources/: mutation fixtures создаются временно вне основного набора и удаляются после проверки.

Для demo screenshots используйте заметную пометку «Demo company / Synthetic data». Пакет не содержит реальных персональных данных и не является доказательством внедрения у реального клиента.
