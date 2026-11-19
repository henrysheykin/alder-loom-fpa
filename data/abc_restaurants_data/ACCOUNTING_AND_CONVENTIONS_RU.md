# Правила учёта, знаки и точность

## Даты и слой источников

Actual window 2024-11-01 — 2026-10-31, snapshot 2026-10-31. Scheduled shifts — планы уже прошедших смен; employee/asset/contract master может хранить исторические даты до открытия окна. Opening balances на 2024-10-31 — состояние, а не повторные actual операции. Future expected deliveries, due dates, debt/contract cycles, payroll scheduled dates допускаются; actual receipt/bank/GL/pay даты после среза отсутствуют.

Business date — местный операционный день America/New_York. Все service checks в модели закрываются до полуночи, поэтому timezone переходы DST не изменяют business date. Clock timestamps также локальные, без offset; все смены дневные, без переходов DST ночью. Пиковая одновременная посадка проверяется интервальным sweep opened_at/closed_at с учётом guests и seats. LUNCH распределён по 11:00–14:30, DINNER по 17:00–20:45, LATE по 21:00–21:45; это окна открытия чеков, не время ухода гостей. Модельный банковский календарь: Monday–Friday без федеральных holidays. Поэтому scheduled funding на праздник не является обещанием реального банковского SLA.

Все CSV — UTF-8 BOM, comma delimiter, dot decimal, ISO даты; пустое поле = null. Для current menu prices, supplier prices и employee pay rates пустой effective_to означает действующие до замены условия. При прогнозе можно перенести last-known-as-of terms как явное сценарное допущение; это не обещание неизменных цен/ставок и не expiry на 31 октября. IDs строковые, включая account_id. Импортируйте monthly files одной таблицы единожды; реестр физических файлов находится в table_schemas.json. Деньги при вычислениях переводите в integer cents/Decimal. Base_unit_price хранит 6 decimals USD/unit, прочие денежные поля — 2. Qty — 6 decimals base unit; количество menu servings целое. LB, ML, FL_OZ и EA нельзя складывать в общий physical quantity.

## POS, comps, voids, refunds

check_lines.menu_gross = quantity × unit_price. modifier_gross = сумма check_modifiers.gross. Для SERVED: gross_sales = menu_gross + modifier_gross; для VOID gross_sales = 0, хотя quoted values сохранены. net_sales = gross_sales - discount - comp. Tax округляется на каждой строке как net × 7.5%; check header суммирует округлённые строки. Gross food/beverage и modifier sales отражаются отдельно на 4000/4010/4020, discounts/comps — на 4090/4091.

comp — приготовленная и выданная позиция, поэтому recipe usage сохраняется. VOID отменён до приготовления: нет stock issue, оплаты, sales/tax. В модели нет void-after-prep: такие потери выражаются waste/service recovery. VOID header может хранить ordered_gross, но не recognized gross.

Сумма tenders = net sales + customer tax + staff tips. Небольшая часть direct checks имеет split cash/card tender, поэтому check:payment = 1:N. refunds — отдельные события на refund_date, с исходной line/payment ссылкой; original headers/lines не уменьшаются. Refund debit 4092, direct tax debit 2030, credit tender clearing/drawer. Tip refunds отсутствуют. Refund quantity для блюда не означает возврат ингредиентов: prepared food never restocked. Для margin по service date и финансового P&L по refund date выберите осознанную политику, не переписывайте факт.

## Marketplace и processor

Каждый CLOSED DoorDash/Uber Eats order уже есть в POS; marketplace_pos_map соединяет external platform_order_id и check_id. Считайте merchant sales один раз из POS; platform orders добавляют commission/promo/adjustment и settlement timing. Присоединяйте aggregated platform events или сохраняйте их отдельно; order 1:N financial transactions, order 1:1 capture и 0:N refund events.

Delivery POS menu prices на 10% выше direct; courier tip, customer delivery/service fee и courier labor не принадлежат ресторану и не моделируются как merchant revenue/expense. merchant_discount — ресторанная POS скидка, уже уменьшающая выручку. platform_customer_promo = platform_reimbursement; consumer food paid + reimbursement = merchant net, дополнительной выручки от reimbursement нет. merchant_promotion_fee — отдельная плата платформе, debit 6180. Service adjustment — отдельный небольшой merchant charge, debit 6210; customer refunds находятся в refunds, не повторяются adjustment.

Все marketplace sales tax в этом синтетическом кейсе collect/retain/remit платформы. POS/marketplace tax хранится информационно; в GL merchant clearing и 2030 не входит. Возврат такого налога также вне merchant GL. Это выбранная модель кейса, не юридическое заключение для NC и не универсальный native sign convention. Direct tax 7.5% — credit 2030; monthly remittance следующего месяца debit 2030, credit bank.

Card capture включает staff card tips. Вся captured amount debit 1030, fee debit 6160 / credit 1030, bank arrival debit 1000 / credit 1030. Модельный тариф 2.65% + USD0.10/capture; fee rebate на refund отсутствует. DD/UE capture debit 1040/1050 на merchant pretax sales; fees credit этого clearing; refund уменьшает clearing. Payout = merchant sales - pretax refunds - комиссии - promotion fees - service adjustments. Приход на банк гасит clearing. Pending snapshot balances должны оставаться asset, а не пропадать в разнице дат.

## Касса и чаевые

Cash tender debit 1010; direct sales/tax и cash tip liability credit в том же daily sales journal. Cash tip payout debit 2021 / credit 1010 в тот же день, один раз. Card tips credit 2020 до approved payroll. Allocations по paid minutes eligible servers/bartenders/hosts с largest remainder; сумма allocation точна до цента. Пул tips общий по точке/дню, индивидуальный чек не принадлежит одному employee.

Drawer expected = opening float + cash tenders - cash refunds - paid cash tips - petty cash. Counted = expected + over_short. Positive over_short — cash overage, P&L cost на 6220 отрицательный; shortage — положительный cost. Deposit bag = counted - USD400. Dispatch debit 1020 / credit 1010; arrival debit 1000 / credit 1020. Cash deposit не создаёт вторую продажу. Petty cash — реальные отдельные receipted operating expenses, не vendor AP payment и не inventory purchase.

## Закупки и ингредиенты

PO не создаёт expense/GL. Approved pack price фиксируется на order_date. Receipt увеличивает usable inventory только на accepted base quantities. Supplier invoice может содержать shipped packs, которых физически не доставили, либо rejected damage; согласованный credit note в тот же день гасит это расхождение. Invoice accounting: debit inventory на billed gross / credit AP; credit: debit AP / credit inventory на short/damaged amount. Чистый inventory GL равен accepted quantity/cost. Supplier invoices/bills и supplier credits/accounting credits — зеркала, не разные экономические события.

PO 1:N lines и 1:N planned shipments; receipt 1:N receipt_lines. Частичный shipment имеет свой receipt/invoice. Outstanding PO quantity = ordered - accepted - closed-with-credit. Не считайте credited short quantities backorder. Credit applications — noncash; actual vendor payments могут закрывать несколько bills, один bill может иметь несколько applications/installments. Bill gross - credits - cash applications = open AP. Due date и agreed installment dates сохраняются отдельно.

raw recipe quantity = edible portion / yield, округление HALF_UP до 0.000001 base unit один раз. Затем умножение на served menu/add-on count, включая comps; упаковка — на completed off-premise check, staff recipe — на staff meals. Выход rice >1 отражает hydration; no synthetic raw material creation revenue. В этом кейсе нет cooked-food inventory и списания ингредиентов в отдельный незавершённый production stock.

Inventory движется в integer millionths; cost — integer cents. На issue: round_half_up(previous carrying value × issued_qty / previous_qty). Остаток = prior + delta. Same-day sequence — числовой movement_sequence, а не лексикографическая строка. Transfer-out использует WAC отправителя, transfer-in принимает точно ту же стоимость/quantity; company profit не возникает. Waste/staff/count сохраняют отдельные expense accounts. Positive stock count difference debit inventory / credit 5050; negative наоборот. Physical count table показывает before/after; closing daily balance уже включает count.

## Payroll

Планы scheduled_shifts отделены от actual timesheets. Paid minutes = clock-out - clock-in - unpaid break; все breaks по 30 minutes. Weekly threshold 2400 paid minutes Monday–Sunday, overtime 1.5x, перенос недель через months и semi-monthly payroll periods обязателен. Opening_workweek_balances хранит минуты до начала окна для первой неполной недели; эта зарплата уже оплачена до окна и не создаёт opening payable.

Regular/OT pay округляются по каждой фактической shift; payroll register суммирует эти cents. Salary = annual rate / 24, с pro rata active calendar days при неполной employment half-month. Wage expense = hourly + salary, без tips. Taxable gross = wages + allocated card tips + reported cash tips. Employee withholding — 16.0–19.5% модельного taxable gross, employer tax — 8.3%, без wage caps/реальных statutory rules.

Net pay = wages + card tips - withholding. Funding = net pay + withholding + employer taxes. Cash tips уже выплачены, повторного payroll cash для них нет. Approved accrual: debit wages/employer tax, debit 2020 card tips, credit 2010 net payable и 2011 tax payable. Поэтому month-end 2020 может быть zero, хотя tips внутри approved-but-unfunded net payable ещё не дошли сотрудникам. Их состав виден в payroll_register. Funding гасит 2010/2011 и банк; в модели налоговый агент перечисляет taxes в дату funding, downstream расчёты агента не моделируются. Scheduled pay day и funding day различны.

Payroll expense признаётся на конец earned half-month, что сохраняет правильный monthly expense. Funding следующего рабочего дня, employee pay на третий рабочий день. Это договорённости кейса, не описание гарантированных Gusto сроков. Employer benefits — отдельные operating bills, без employee deductions и второго payroll expense.

## Финансовая отчётность и план

Все GL journals сбалансированы company-wide. Debit/credit колонки неотрицательные; signed activity = debit - credit. Revenue/credit liabilities обычно отрицательны; расходы положительны. Monthly P&L uses period activity; TB closing для P&L accounts накоплен с 2024-11-01, искусственных annual closing entries нет. Net revenue = -(4000+4010+4020+4090+4091+4092 signed activity). Pretax income = -sum(Revenue/ContraRevenue/Expense period activity). Liabilities для business reporting показывайте как -TB balance.

Все деньги банка принадлежат HQ, но statement.restaurant_id показывает originating restaurant для платежа/settlement. Restaurant TB — разрез аналитического cost center одной LLC, не баланс отдельного юридического лица; он не обязан сам балансироваться, поскольку HQ держит банк/долг. Company TB балансируется. Shared salaries/finance/interest на HQ не распределены на точки. Monthly controls показывают company и три ресторана; company включает HQ overhead.

Equipment bill debit 1500 / credit AP; opening assets/accumulated depreciation отдельно. Depreciation actual schedule начинается со следующего месяца для новых активов, monthly debit 6300 / credit 1510. Новый compressor октября не имеет будущего depreciation actual. Loan principal debit 2040 при платеже; contractual interest debit 6400; owner distributions debit 3100 equity, не expense. Lease capitalization и corporate income tax отсутствуют по явно выбранным упрощениям.

Original approved budget — единая замороженная версия с approval 2024-10-15 на все 24 месяца; independent drivers, не копия actual. Accounting sign совпадает с GL. Для BVA revenue display sign переворачивается; положительное actual-minus-budget по expenses — перерасход, по signed revenue — недобор. Forecast versions создайте отдельно.

cash_commitments — только source-linked index. Он не содержит weekly balances, будущих продаж, будущих неутверждённых payroll или рассчитанного burn. Для 13-week forecast начните с company bank cash и явно выбранного определения liquidity; добавьте pending historical settlements, existing AP installments, approved payroll/tax, contractual debt, только будущие NOT_BILLED cycles и outstanding unreceived PO quantities. Не суммируйте index с теми же raw schedules. Utilities/maintenance future cycles обозначены ESTIMATE. Nov–Jan service cycles могут иметь due в феврале — отфильтруйте горизонт до 2027-01-30. Не добавляйте cash bags и их pending bank arrivals дважды. Финальные marketplace settlement IDs оканчиваются 20261101, но известная часть включает только orders/refunds до 31 октября. Это earned component незавершённого weekly cycle: прогнозируемые заказы воскресенья 1 ноября попадут в тот же payout, их долю добавьте один раз к известной части.

## Проверка

Verifier использует только сохранённые schema/CSV/manifest/controls, не импортирует генератор и не доверяет его итоговым объектам. Денежный tolerance — 0 cents. Количество разрешено с шагом 0.000001 base unit, допустимое расхождение на сохранённой точности — 0.000000. Он проверяет PK/FK, native-style арифметику/источники, theoretical recipes, WAC/roll-forwards, tips/payroll, AP, bank/clearing/liabilities, GL/TB и budgets/cutoff. Сводки не являются независимым внешним аудитом: это документированные acceptance checks синтетического набора. Отдельные mutation checks показывают, что ключевые искажения действительно обнаруживаются.
