# Определения метрик для будущего приложения

## MRR и ARR

MRR = active paid recurring normalized monthly contract value после recurring discounts. Для каждого subscription возьмите effective status и effective item на дату, цену за interval, quantity и recurring_discount_bps. Net full interval value округляется HALF_UP до цента; для annual делится на 12 и ещё раз округляется HALF_UP до цента на уровне subscription. Closing MRR = сумма этих account-level значений. ARR = 12 × этот MRR.

Включены active и past_due в пределах 21-дневного grace period от первого неудачного renewal attempt. По границе окончания grace договор переводится в unpaid и исключается из MRR. Free trial, canceled, unpaid и not_started исключаются. Scheduled cancel_at_period_end сохраняет MRR до effective cancellation date. Реактивация становится MRR только с фактического возобновления paid-tier service.

Слова paid activation означают начало платного тарифного обслуживания и договорного recurring obligation; это не обещание, что первый capture уже успешен. Нужный финансовый статус cash берётся из charges. Просрочка в допустимом grace не превращает контракт в trial.

Из MRR исключены taxes, one-off goodwill credits/refunds, old annual cash, признание прошлых предоплат и uncontracted pipeline. Annual discount уже находится в annual price. Annual-to-monthly/monthly-to-annual переход может менять MRR без изменения seats.

Источники: subscription_history + subscription_item_history + prices. Текущий subscriptions snapshot недостаточен для прошлых дат. Никакой готовой случайной MRR table в sources нет.

Bridge за месяц:

    opening MRR + new + expansion - contraction - churn + reactivation = closing MRR

Классифицируйте каждое effective изменение из истории: 0→positive впервые = new, после прежнего paid срока = reactivation; positive→0 = churn; изменение positive→positive = expansion/contraction. Повышение цены и скидка за annual cadence относятся к той же коммерческой expansion/contraction. В одном месяце у клиента может быть несколько движений.

## Bookings, billings, revenue и cash

| Метрика | Определение кейса | Источник |
|---|---|---|
| Bookings | Signed value newly committed noncancelable service terms + amendments − termination concessions; без goodwill/tax | contracts/contract_events |
| Gross billings | Original finalized invoice total на issue date | stripe_billing/invoices |
| Net billings | Gross billings минус issued credit-note face по дате кредита | invoices + credit_notes |
| Recognized revenue | Оказанный service, включая signed credits, по earned posting date | GL revenue accounts и actual_earned schedule |
| Captured customer cash | Successful charges минус successful refunds по actual cash event dates | stripe_payments |
| Bank cash | Реальные posted bank transactions; payout receipt отличается от capture | bank/statement |
| Contracted ARR at signature | Annualized signed initial contract value в CRM | CRM signed contract map |

Monthly contracts коммитят очередной месяц, поэтому booking repeats на каждом renewal; annual коммитит год. При assisted first contract signature раньше service start может быть booking до invoice/MRR. Signed future contract 26 октября — показательный пример. Pipeline probability не создаёт bookings или contracted ARR.

## Cohorts и retention

Paid acquisition cohort = календарный месяц первого effective paid-tier обслуживания по subscription history. Opening cohorts остаются с настоящими pre-window месяцами; не объединяйте их с new customers ноября 2024. Never-paid trials не входят в paid cohort; reactivation сохраняет исходный cohort.

Для monthly control NRR фиксируется набор клиентов с positive MRR на начало месяца. Numerator = closing MRR только тех же customer IDs; denominator = их opening MRR. Reactivation того же opening-cohort customer внутри месяца входит в endpoint NRR, новые клиенты исключены.

GRR в controls использует консервативную явно заданную внутримесячную конвенцию: по каждому opening-cohort customer берётся минимальный MRR среди opening и всех effective states месяца, затем сумма делится на opening MRR. Expansion и reactivation ничего не восстанавливают в этом GRR. Это не обещание совпадения с endpoint-only GRR другого продукта.

Для cohort matrix на 12 месяцев также фиксируйте cohort IDs и initial observation date. Не смешивайте monthly control GRR с иной формулой без смены метки.

Logo churn (endpoint) = число opening paid customers с closing MRR=0 / число opening paid customers. Churn-event count храните отдельно: churn и reactivation в том же месяце могут дать событие при отсутствии endpoint logo loss.

ARPA = closing MRR / closing eligible paid logos. Seat ARPU = closing MRR / purchased seats. Product active-user rate = distinct active users / assigned users либо / purchased seats с явным названием denominator. Trial users исключите из paid denominator.

## CAC, LTV, margin и runway

Fully loaded acquisition CAC за период = фактический S&M cost, включая compensation/benefits/ads/tools, делённый на впервые activated paid accounts, без reactivation. Это blended acquisition-cost proxy: нет точного разделения acquisition versus expansion labor. Для payback используйте cohort gross profit, учитывая sales lag. При нуле new accounts возвращайте N/A.

Paid-media CAC — только spend соответствующего канала, делённый на наблюдаемые matched new paid accounts с выбранной first-touch attribution. Unmatched/privacy gaps сохраняются; это не полный точный CAC всей базы. Meta/Google platform claims не складываются. Их агрегаты смоделированы как 45% и 68% наблюдаемых trial starts месяца; возможен overlap, а individual matching заявлен лишь там, где он действительно сохранён.

Gross margin = (recognized revenue − COGS) / recognized revenue, по accounts 5xxx. Инфраструктура, support и processing fees включены согласно ACCOUNTING_POLICIES_RU.md. Tenant allocation не добавляется второй раз к cloud cost.

LTV не является готовым фактом. Для простой демонстрации можно принять steady-state ARPA × gross margin / monthly logo churn, используя 12-месячное сглаживание churn и максимум 60 месяцев lifetime. Это оценочное допущение; при нулевом/отрицательном churn denominator — N/A. Cohort discounted gross-profit LTV предпочтительнее при изменении annual mix и retention.

Runway = unrestricted actual bank cash / положительный среднемесячный operating cash burn за последние 3 месяца. Equity funding исключается из operating burn. При положительном operating cash flow показывайте «нет текущего burn», не отрицательные месяцы runway. Processor balance и in-transit payouts показывайте отдельно от actual bank cash и включайте в forecast на ожидаемую дату.

## 13-week cash forecast

As of 2026-10-31; рекомендуемое окно 2026-11-01 — 2027-01-30, 13 последовательных 7-дневных недель. Forecast — новый план с собственными assumptions/version, не продолжение actual CSV.

Используйте opening actual bank cash, ожидаемые processor settlements, due/remaining AR, будущие renewals из current contract periods, signed future start, open AP, unfunded payroll, current salary history, recurring vendor contracts, benefits, ad/cloud assumptions и запланированные hiring requisitions по выбранному сценарию.

Не добавляйте cash за уже оплаченные будущие annual service periods. Исключайте scheduled cancellation до следующего renewal. Unpaid/writeoff accounts не предполагают автоматического collection. Open AP/known_obligations/recurring agreement deduplicate по source bill и cycle key. Будущие invoices/captures/hires остаются forecast rows с явной вероятностью/версией.
