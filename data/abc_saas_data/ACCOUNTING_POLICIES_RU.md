# Бухгалтерские правила и защита от двойного счёта

## Даты, знаки, исходные остатки

Фактические проводки ограничены 2024-11-01 — 2026-10-31. Услуга относится к [service_start, service_end_exclusive). Изменение с даты D действует с начала D. В эффективной истории effective_to также исключается. Будущая due date — срок обязательства, не actual payment.

GL debit и credit неотрицательны; signed trial balance = debit minus credit. Для положительной revenue используйте credit minus debit. Для expense — debit minus credit. Bank amount положителен для поступления, отрицателен для списания. Credit-note face и refund face показаны положительными; credit_note_lines.net_amount отрицателен. Balance refund amount/net отрицательны.

Opening trial balance хранится отдельно на 2024-11-01. Исторический P&L закрыт в opening retained earnings. Внутри 24-месячного extract годовых closing journals нет: P&L balances накапливаются. Месячный P&L строится по period activity, не по cumulative closing balance. Общий opening prior burn USD1m и opening asset cost/accumulated depreciation являются явно суммированными pre-window carryforward, не новыми расходами периода.

## Invoice → recognition → cash

1. Finalized subscription/proration invoice: Dr AR 1100 / Cr Deferred revenue 2200.
2. Оказание услуги: Dr Deferred 2200 / Cr subscription revenue 4000/4010/4020.
3. Successful capture: Dr Processor 1010 / Cr AR 1100.
4. Processor fee: Dr COGS processing 5030 / Cr Processor 1010.
5. Initiated payout: Dr Payouts in transit 1020 / Cr Processor 1010.
6. Actual bank receipt: Dr Bank 1000 / Cr Payouts in transit 1020.

Признание не зависит от даты payout и не ускоряется при annual upfront capture. Service invoice lines распределяются по фактическим календарным дням. Для обычного графика каждая месячная сумма = rounded cumulative amount at month boundary minus previous rounded cumulative amount. HALF_UP в integer cents, включая симметричные отрицательные суммы. Последняя сумма сохраняет полный signed transaction price до цента.

Revenue schedule содержит opening_earned, actual_earned и future_unearned. Последнее — оставшийся график уже выставленного service obligation, а не будущая actual выручка. Actual_posting_date там пуст; таких posting IDs нет в actual GL. Подписанный, но ещё не выставленный будущий контракт вообще не создаёт revenue schedule или deferred balance.

Revenue по plan stream относится к plan на документированной invoice/credit line. При midterm plan upgrade первоначальная line продолжает начисляться на исходный stream, net incremental proration — на новый stream. Поэтому сумма по текущему plan snapshot не является тем же разрезом, что GL revenue by invoiced stream.

## Proration, credits, refunds и dunning

Изменение seats/plan в середине срока не сбрасывает anchor. Full-period new net recurring amount минус old net amount умножается на remaining days / full period days. Дополнительная recurring discount уже включена в обе стороны. Net positive adjustment выставлен отдельной proration invoice; net negative adjustment — credit note. Это консолидированная экономическая line кейса, без заявления о точном native Stripe JSON.

Credit note: Dr Deferred / Cr AR в части неоплаченного остатка и Cr Refund payable 2300 в части оплаченного кредита. Возврат: Dr Refund payable / Cr Processor. Refunded credits не открывают AR повторно. Одноразовый goodwill credit признаётся сразу через отрицательную revenue; MRR и bookings по принятой политике не меняет.

Goodwill 18 июля = 15% monthly list-equivalent contract value по seats/plan/recurring discount именно на дату инцидента, минимум $1, максимум 25% исходного счета. Annual discount здесь не применяется: база явно monthly list equivalent. Это вымышленная сервисная политика.

При terminal failure service сохраняется 21 день от первой неудачной попытки. Затем статус unpaid исключается из MRR; unused service кредитуется в AR, earned uncollectible balance списывается Dr Bad debt 6350 / Cr AR. Для unused_after_dunning credit schedule зеркально сторнирует исходные оставшиеся дневные allocations; allocation_basis_invoice_line_id сохраняет исходную line. Поэтому после месяца отключения net service revenue по этому invoice ровно ноль, включая будущие месяцы, без остаточных ±1 cent. Failed attempts создают ноль successful cash.

Sales-assisted net35_two_installments — отдельные согласованные сроки, две фактические частичные оплаты. Неоплаченный второй installment до net35 due date не считается автоматически нарушением grace policy. Future planned installments не экспортируются как actual payments.

## COGS и OPEX

- Production cloud 5000 — COGS. Development cloud 6010 — Engineering/R&D OPEX.
- Customer Success/Support compensation: 80% support COGS 5010, 20% CS OPEX 6200. Те же доли применены к отдельно выставленным benefits. Support tooling 5020 — COGS.
- Engineering salaries и tools — R&D OPEX; капитализации разработки нет.
- Sales & Marketing и G&A compensation — OPEX. Gross включает employee withholding; employer tax — дополнительный расход.
- Payroll allocation rows делят gross + employer tax и не добавляют расход. Health benefits — отдельные vendor bills, поэтому второй раз к payroll employer cost их не добавляйте.
- Processing fees — COGS. Собственная реклама — Sales & Marketing OPEX.
- Tenant cloud allocation — управленческое распределение одного bill. Production 70% распределяется по monthly workflow_runs+1, 30% остаётся shared; development 100% shared. Всегда есть явный shared bucket, а суммы до цента равны daily cost, source invoice и AP.

## AP, prepayments, assets, funding

Monthly vendor/cloud/ad bills признаются в конце сервисного месяца; bank payment — отдельное погашение AP. Insurance и security suite оплачиваются за год: Dr Prepaid services 1300 / Cr AP; monthly service schedule списывает Dr Expense / Cr Prepaid. Future schedule не является future actual expense.

Equipment: Dr fixed assets 1500 / Cr AP. Straight-line depreciation учитывается отдельно; opening group — $72k cost, $18k opening accumulated depreciation, 48 месяцев useful life с ноября 2023; новые laptops — $2.4k, 36 месяцев.

Payroll начисляется за календарные половины месяца с prorating по employed days и effective annual salary / 12. Funding — на второй следующий weekday после period end, без федерального holiday calendar. По второй половине октября actual funding ещё нет, хотя expense и payable уже начислены.

Equity contributions: Dr Bank / Cr Paid-in equity 3000. Funding не revenue, MRR, bookings или operating sales cash. Долга нет.

## Не складывать повторные представления

| Представления одной операции | Использование |
|---|---|
| Stripe invoice и QuickBooks client invoice | Одна продажа/AR, accounting row — mirror |
| Invoice, contract booking event, MRR и recognition schedule | Разные меры коммерческого обязательства и оказания услуги |
| Charge, receipt, processor balance, payout и bank deposit | Связанные стадии одних денег |
| Credit note, accounting credit note и refund | Скидка/уменьшение обязательства и её денежное погашение |
| Daily cloud + source bill + tenant allocations + AP + GL | Один расход в деталях и учёте |
| Payroll register + payroll allocations + payroll GL + funding | Один earned cost и последующее погашение |
| Daily advertising + monthly ad invoice + AP + GL | Один маркетинговый расход |
| Open AP + known_obligations copy + recurring agreement | Уберите overlap по bill/cycle, учитывайте только новые cycles |
| Old annual cash + future earned schedule | Нового будущего cash по уже оплаченному сроку нет |
| Opening support + opening TB | Support объясняет opening; TB не является period P&L |

Вычисления финансового факта основывайте на GL и сверяйте с соответствующими операционными subledgers. Источники нужны для объяснения и доказательства, а не для суммирования всех amount columns.
