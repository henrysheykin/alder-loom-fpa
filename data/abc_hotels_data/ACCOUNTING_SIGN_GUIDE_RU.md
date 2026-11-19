# Учёт и знаки

## Приоритет источников

GL — authoritative monetary actual P&L/BS; folio lines и subledgers объясняют его. Capacity/PMS задают физические drivers. Opening TB отдельно на 2024-10-31; не включайте его в period revenue/cost. Monthly TB использует debit minus credit и не закрывает P&L ежегодно: period activity берите из period_debit/credit или GL.

GL debit_usd/credit_usd unsigned. Для актива normal signed balance положительный; liability/equity/revenue обычно отрицательный. Expense и contra-revenue обычно дебетовые. Нормализованный P&L: revenue = credits−debits по accounts4000–4210 включая contra; expenses = debits−credits по accounts5000–5700. Budget: income и expense положительны, contra-revenue отрицательна; sign не совпадает с GL balance sign.

Bank credit=поступление, debit=списание, signed=credit−debit. Payments capture positive, refund negative; processing fee positive, net=gross−fee. Folio credits negative, discounts positive reduction; net=gross−discount, total=net+tax. Liability в balance sheet для показа положительным = −GL signed balance. Не превращайте неизвестную actual date в дату due.

## Проводки экономических событий

| Событие | Debit | Credit | Примечание |
|---|---|---|---|
| Gateway lodging capture | 1010 net, 5010 fee | 2200 gross | lodging advance до услуги |
| Consumed room night | 1110/1120/1130 total, 4010 discount | 4000 gross, 2100/2110 tax | guest / merchant / corporate AR соответственно |
| Deposit application | 2200 | 1110 | non-cash, только фактически оказанная charge |
| Hotel ancillary | 1110/1130 | 4100–4120 | separate service line; case ancillary tax0 |
| Room credit | 4020 (+tax liability reduction) | соответствующий AR | original line сохраняется, original_folio_line_id задан |
| Guest service refund | 1110 | 1010 | погашает credit AR, не создаёт второй room credit |
| Cancellation refund of unearned advance | 2200 | 1010 | earned fee при наличии отдельной строкой; до capture — void |
| Security capture/refund | 1010/1000 ↔ 2210 | 2210 ↔ 1010/1000 | ни доход, ни расход; processing fee отдельно |
| Gateway payout initiated | 1020 | 1010 | cash transit, без выручки |
| Actual bank payout arrival | 1000 | 1020 | только когда есть bank statement row |
| OTA commission accrue/credit | 5000 | 2010 | earned room/fee basis; service credit reverse отдельно |
| Merchant settlement release | 1020 net, 2010 commission, 2110 tax | 1120 gross | gross revenue уже признана ночью; tax assumption explicit |
| Agency commission payment | 2010 | 1000 | agency guest previously paid hotel gross |
| Corporate invoice at month end | 1100 | 1130 | AR reclassification, без новой revenue |
| Corporate advance / application | 1000 / 2220 | 2220 / 1100 | cash и non-cash отдельными событиями |
| Corporate partial receipt | 1000 | 1100 | application invoice-specific, не ещё одна продажа |
| Vendor operating bill | expense | 2000 | operational cost detail не прибавлять повторно |
| Capitalized equipment/refurbishment | 1510 | 2000 | invoice acceptance; не maintenance expense |
| Vendor payment | 2000 | 1000 | principal cash payment; AP decreases |
| Earned payroll | wages, 5130 employer tax, 5140 benefit | 2300 net pay, 2310 withholding/employer/benefit clearing | gross включает employee withholding |
| Payroll funding | 2300/2310 | 1000 | отдельно от earned period; benefits bundled in payroll funding |
| Depreciation | 5600 | 1590 | straight line; новый asset с месяца после ввода |
| Debt payment | 2400 principal, 5700 interest | 1000 | principal не P&L |
| Members distribution | 3100 | 1000 | equity, не expense |

Room discounts4010 и room credits4020 уменьшают room revenue; cancellation4200/no-show4210 отдельно, не room ADR numerator. Hotel-collected lodging tax2100 перечисляется по model schedule. Merchant OTA tax2110 погашается release, без hotel bank movement; это contractual synthetic assumption, не налоговая норма. Существующее guest/corporate advance не является future fresh cash.

Invoices, receipts, work logs, payroll details, platform bills и GL могут описывать одну операцию в разных systems/grains. Стройте либо финансовый факт из GL с детализацией source_id, либо субфакты с мостами; никогда UNION ALL всех USD columns.

## Shared costs и property cash

CORP payroll/software признаются один раз в GL. `shared_cost_allocations` — аналитический zero-sum bridge: negative expense у CORP, positive у RAL/WIL/DUR. Не repost bridge в GL и не добавляйте source_cost_usd на каждой строке: он repeated reference. EBITDA_after_allocation = EBITDA_before_allocation − allocated_expense. На company level сумма allocations0.

Один bank account; property_id — аналитическая attribution платежа. CORP может иметь отрицательный attributed running cash после distributions и shared costs, пока консолидированный bank положителен. Это не реальный overdraft отдельного property account. Opening equity распределён по cost centres для balance checks, без intercompany management fees.

## Политики упрощения

Operating supplies/linen services immaterial; expenses при monthly accepted receipt/consumption, без stock ledger. Capitalize equipment/refurbishment с выгодами >12 месяцев и стоимостью проекта ≥USD2,500; routine repair остаётся expense. Строительные работы WO могут содержать approved specialist scope; это supporting approved amount, не весь asset invoice. WIL64k включает specialist work и furnishings; approved WO totals не являются дополнительным capex/expense.

Straight-line salvage0: building390 months; opening equipment/fitout120; new refurbishments84; RAL equipment60. Opening accumulated depreciation принята как carrying historical balance. Corporate income tax, ASC842 leases, FX, chargebacks, credit losses allowance, loyalty points и restaurant inventory не моделируются. Нельзя выдавать параметры кейса за statutory accounting certification.
