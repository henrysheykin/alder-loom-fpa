# Проверенные концепции и синтетические допущения

Проверка первичных источников выполнена2026-11-19. Внешние источники помогают выбрать корректные system concepts и экономический контекст; ни одна операция набора не скопирована у реального бизнеса.

- [Mews reservations](https://docs.mews.com/connector-api/operations/reservations) и [revenue management](https://docs.mews.com/connector-api/use-cases/revenue-management) поддерживают разделение reservation/service items/resource blocks. Здесь реализованы собственные flat CSV с общими IDs; соответствие конкретному native Export не заявлено.
- [Booking.com reconciliation](https://developers.booking.com/connectivity/docs/reconciliation-api/understanding-the-reconciliation-api) описывает payout components, commissions/taxes и reservation mapping. Это основание для отдельного settlement grain. API page обозначена как closed beta; набор не требует доступа к API.
- [Expedia invoices and booking receipts](https://developers.expediagroup.com/rapid/lodging/manage-booking/booking-receipts?locale=en_US) различает Property Collect и Expedia Collect: кто получает оплату гостя и выдаёт документы. Здесь channel contracts и timing синтетические; они не заявляются как универсальная схема налогообложения или точная текущая настройка Expedia.
- [Stripe payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation) различает payout batch и его transactions. Поэтому payment, processor balance, initiated payout и actual bank arrival не смешаны.
- [Gusto payroll fundamentals](https://docs.gusto.com/embedded-payroll/v2026-02-01/docs/payroll-fundamentals) различает earned gross, deductions/net и employer costs. Case payroll по собственным blended assumptions, без имитации statutory tax engine.
- [CoStar/STR glossary](https://www.costar.com/en-gb/gbr/products/str-benchmark/resources/glossary) проверен для room-night KPI concepts. Выбор исключать обе OOO/OOS категории является внутренним управленческим выбором; сравнение с официальной market series потребует другого policy mapping.
- [CoStar full-year2025 release, 20 January2026](https://www.costar.com/products/str-benchmark/resources/press-releases/us-hotels-report-first-full-year-occupancy-revpar): национальные occupancy62.3%, ADR USD160.54, RevPAR USD100.02. Это проверенный ориентир порядка величины, не comp set для трёх NC объектов. Более низкая blended rate апарт-отеля и собственный closure denominator ограничивают прямое сравнение; эти числа не подставлены в actuals или forecast. Research-only rows отдельно в metadata/industry_context_benchmarks.csv.
- [AHLA State of the Industry2026](https://www.ahla.com/sites/default/files/State-of-the-Industry_2026_One-Pager.pdf) даёт национальный контекст cost/workforce pressure. Это не региональная оценка для конкретного NC property и не подтверждение выбранных маржинальностей. Case ADR/occupancy/cleaning productivity — согласованные синтетические assumptions, не прогноз рынка.

## Явные параметры

| Параметр | Значение кейса | Граница |
|---|---|---|
| Hotel lodging tax | RAL/DUR11.25%, WIL12.5% | не statutory rates; long stays также облагаются, exemption не применяется |
| Ancillary / cancellation/no-show tax | 0% | модельное упрощение, не правовой вывод |
| Merchant OTA tax | OTA collects/remits lodging tax;2110 clearing погашается release | contractual synthetic assumption для EXPEDIA-style channel |
| Agency commission |15% earned room/fee net of credits | не реальная текущая Booking.com price quote |
| Merchant commission |18% earned room/fee net of credits | не реальный Expedia contract |
| Gateway fee |2.75%+USD0.25 per capture; refund fee0, original fee не возвращается | собственный параметр; не Stripe current tariff |
| Capture lag | prepaid nominally booking+2 calendar days, earliest window start; arrival collect for other guests | cancellation before capture voids authorization, only earned fee captured |
| Processor availability/payout |+2 business days, next Friday release, bank+1 business day | weeks exclude weekends only; no holiday calendar |
| Merchant earned release | same-week Saturday+7 days, bank+1 business day | отдельная selected trace release Oct31; clear source dates authoritative |
| Corporate payments | monthly invoicing; terms30/45;65% and35% tranches18 days apart | CO-00152-day delay from Aug2026; CO-0038-day delay |
| Security | DUR USD250, return3 business days after checkout | refundable liability, separate from final cleaning fee |
| Employee withholding |18% hourly,23% salary | blended assumed deduction; no W-4/state tax calculation |
| Employer tax |8.3% gross | synthetic; employer benefitUSD175 per employee/halfmonth with gross pay |
| Overtime | hourly >40h Monday-week,1.5× | case policy; no statutory compliance representation |
| Benefits funding | included in payroll2310 funding | not additional vendor-benefit bill/tax remittance |
| Operational productivity | hotel34/16 min departure/stayover; aparthotel48/32 departure/weekly | not certified cleaning norms |
| Laundry |USD3.90/set, USD4.35 from May2026 | synthetic vendor quote, not market benchmark |
| Supplies |USD1.45 hotel stayover,2.60 weekly,3.90 departure; +12% from June | immaterial expensed consumption, no artificial stock ledger |
| Shared allocation | physical keys60:52:44, largest-remainder cents | analytical zero-sum bridge; source_cost repeated reference |
| Budget approval |2024-10-15 for all24 months | original case planning baseline; never recast using generated actuals |
| Asset/rent policy | capitalize project≥USD2,500 and useful>12mo; monthly SL; rent expensed | no ASC842/USALI certification |

Никаких owner trust funds/property management rents, restaurant sales, franchise fee, sales tax nexus certification, FX, chargebacks и refundable-security deductions за damages не добавлено. Missing actual date отличается от actual monetary zero. Scientific/industry inputs не подменяют внутреннюю финансовую сверку: основной критерий — linked event consistency до цента и room-night.
