# Явные допущения и упрощения

Компания, customers, employees, vendors, product prices и все операции синтетические. Реальные названия систем описывают стиль моделируемого источника. Кейс нельзя представлять как реального клиента.

1. Один US SaaS entity, одна валюта USD, один bank account и процессор; нет FX, chargebacks, debt, interest, dividends или использования кредитной карты компании.
2. Три seat plans, минимальные seats 3/5/10, 14 дней trial, один recurring item/subscription. Нет setup fees и usage-based billing. Все feature actions входят в фиксированную подписку.
3. Annual price = десять monthly list prices; additional recurring discount 10% у заданной части клиентов. Effective price histories и grandfathered policies заданы в COMPANY_PROFILE_RU.md.
4. Конвенция календарных дней [start,end); дневной подход проще реального second-level billing. Все даты — модельные UTC day boundaries, не предполагают локальный налоговый event timestamp.
5. Все sales tax amounts = 0 по MODEL_ZERO_SALES_TAX. Это учебное упрощение, не утверждение о налогообложении SaaS в штатах. Corporate income-tax provision в модели равен нулю; tax returns, NOL schedules и income-tax payables не моделируются. Поле net_income в controls — модельный результат при этой нулевой provision.
6. Payroll withholding 22%, employer tax 8.2% — условные flat rates. Нет legal bracket/state payroll, retirement deductions, bonuses, commissions или overtime. Health benefits $650 за сотрудника в месяц отдельно в vendor bills; месяц ухода оплачивается полностью. Semi-monthly salary prorated по employed calendar days.
7. Processor fee = 2.9% capture + $0.30, original fee при refund не возвращается, дополнительной refund fee нет. Эти цифры и settlement times не заявляются текущим тарифом реального провайдера.
8. Weekly Friday payouts, available after two weekdays; bank receipt after two weekdays. Weekdays Monday–Friday без федерального holiday calendar. Календарные даты событий отдельных внутренних posting допустимы.
9. Ретрай после начального failure на день 3; terminal failure attempts на дни 0/7/14, service/grace 21 день. Согласованный net35 two-installment отдельно хранится как collection_terms. Будущие actual attempts/payments отсутствуют.
10. Midterm change: net proration оплачивается сразу или credit возвращается/уменьшает AR. Отрицательная экономическая сумма — credit note, не отрицательная finalized invoice.
11. При dunning unused service зеркально сторнирует исходные будущие allocations до цента. Goodwill 18 июля — immediate one-off credit по состоянию именно на дату инцидента.
12. Production cloud 70% tenant attribution по monthly workflow_runs+1, 30% shared. Development 100% shared. Это управленческая модель, не точный алгоритм native AWS CUR. Resource usage units и ставки вымышлены.
13. Support compensation/benefits 80% COGS / 20% CS OPEX; engineering 100% R&D OPEX, без capitalized development. Все allocation layers сохраняют исходный expense total.
14. Original 24-month budget approved 2024-10-20, immutable. Future requisitions — plans, не hires. Known obligations register — копии и ближайшие новые cycles, не дополнительные posted bills.
15. First-party tracking сохраняет известные links лишь у части leads. Platform attribution windows заданы как 7d click/1d view и 30d click; Meta/Google claims могут пересекаться и не дают уникальных customers или accounting revenue. Platform monthly claims связаны с observed trial pool, а не произвольными большими conversion counts.
16. Opening source support неполон как исторический бизнес за все годы: он сохраняет документы для opening balances и контрактов. Prior operating burn и opening equipment/accumulated depreciation суммированы явно в opening TB. Детальный фактический P&L начинается 2024-11-01.
17. Insurance annual January, security software annual June, service recognition по дням. Vendor bills на monthly expenses датированы концом периода, без отдельного invoice-lag accrual layer. Payroll accrual/payable и vendor prepayments моделируются отдельно.
18. Fixed assets straight-line, residual zero; old group 48 months, new laptops 36 months. Нет asset sales/disposals.
19. Sales cycle/stage histories, product adoption, campaigns и churn задаются согласованной историей с deterministic seed 20261031. Это быстрорастущий кейс, без обещания совпадения с медианными SaaS benchmarks.
20. Намеренно испорченные источники в поставку не включены. Validation controls, example copies, catalogs и ZIP copies не загружать в raw facts повторно.
