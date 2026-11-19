# Проверенные концепции и границы модели

Публичная документация и первичные исследования проверены 2026-11-19. Исторический срез данных остаётся 2026-10-31. Все цены, ставки, сроки процессинга и unit economics RelayNest вымышлены; сайты ниже не являются источниками «тарифов» этой компании.

Точные ссылки, проверенные концепции и наши модельные решения: metadata/research_references.csv.

- [Stripe proration](https://docs.stripe.com/billing/subscriptions/prorations): кредит за неиспользованное время не означает автоматический возврат денег. В кейсе политика возврата задана явно.
- [Stripe revenue recognition](https://docs.stripe.com/revenue-recognition/methodology/subscriptions-and-invoicing): начисление относится к времени оказания услуги. Дневная модель и округление до цента — наше упрощение.
- [Stripe payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation): batch payout сверяется с процессорными транзакциями и отдельным банковским поступлением.
- [AWS allocation concepts](https://docs.aws.amazon.com/cur/latest/userguide/split-cost-allocation-data.html): распределение общей инфраструктуры допустимо как аналитическая детализация. Наша tenant allocation — собственный управленческий слой, не заявленный native CUR.
- [Gusto payroll fundamentals](https://docs.gusto.com/app-integrations/docs/payroll-fundamentals): начисленный employer cost отличается от net pay и funding. Налоговые проценты в наборе заданы как синтетические.
- [PostHog organizations](https://posthog.com/docs/product-analytics/group-analytics) и [HubSpot deals](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/deals/guide): продуктовые организации/пользователи и CRM opportunities — отдельные сущности.
- [QuickBooks JournalEntry](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/journalentry): проводки имеют дебетовые и кредитовые строки; экспорт кейса использует собственную плоскую схему.
- [SaaS Capital growth research](https://www.saas-capital.com/research/private-saas-company-growth-rate-benchmarks/) и [retention research](https://www.saas-capital.com/wp-content/uploads/2025/09/RB32WS1-2025-B2B-SaaS-Retention-Benchmarks.pdf): контекст диапазонов и определений, без заявления, что быстрорастущий демонстрационный кейс воспроизводит среднюю компанию из исследования.

Внимание к конвенции дат: календарные поля *_end_exclusive в нашем наборе всегда исключают конечный день. Это явно нормализованные поля кейса. Не переносите на них без преобразования семантику отдельных native API объектов, в которых граница может описываться иначе.
