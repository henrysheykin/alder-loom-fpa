# Готовое задание для Claude

Скопируйте текст ниже в Claude Code с рабочей папкой juniper_quay_data. Все исходники уже существуют; новые случайные facts не требуются.

---

Я строю демонстрацию AI FP&A для вымышленной Juniper Quay Hospitality LLC. Мне нужны reporting, Budget vs Actual, channel/unit economics, rolling forecast и13-week cash forecast. Программу и интерактивные dashboards строю в этом проекте отдельно от подготовки данных.

Сначала прочитай README_RU.md, COMPANY_PROFILE_RU.md, ACCOUNTING_SIGN_GUIDE_RU.md, KPI_DEFINITIONS_RU.md, CASH_FORECAST_INPUTS_RU.md, RESEARCH_AND_ASSUMPTIONS_RU.md. Затем metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, table_schemas.json, relationships.csv и RELATIONSHIPS_RU.md. Посмотри examples/TRACE_GUIDE_RU.md и два JSON trace; это copies, не дополнительные facts.

Основной период2024-11-01–2026-10-31, cutoff2026-10-31, USD, local service dates America/New_York. Principal operator, три property RAL60/WIL52/DUR44 keys, corporate shared centreCORP. Room revenue принадлежит LLC. Management for external owners отсутствует. Во всех будущих UI/скриншотах обозначай Demo company / Synthetic data. Не представляй кейс как результат внедрения у реального клиента или гостиничную accounting certification.

Читай CSV программно с UTF-8 BOM, comma delimiter, IDs как string, USD как Decimal/integer cents. Все physical parts таблицы берутся из schemas. GL лежит в sources/quickbooks/general_ledger/*.csv. Не печатай миллионы строк в чат. Нельзя загружать examples, validation controls, metadata, source ZIPs или planning copy/index как дополнительные факты тех же операций.

Сначала нормализуй данные, проверь PK/FK и grain, пересчитай сверки и сопоставь свои24 monthly results по компании и трём properties с validation/monthly_control_totals.csv. COMPANY уже включает CORP и properties — не суммируй этот row с property rows. Controls — reference expected results, не значения для dashboard вместо raw sources. Independent verifier reproducibility/verify_dataset.py повторно читает source CSV; его можно запустить из корня пакета: python reproducibility/verify_dataset.py .

Построй модель с отдельными facts:

1. Reservation snapshot + status/amendment history, multi-room mapping; separately actual consumed nights и room/date availability/closure.
2. Folio service charges/credits с room, ancillary, fee и tax components; checkout-exclusive consumption.
3. Direct gateway capture/refund, deposit applications, security, processor balances, initiated payouts, transit и actual bank arrivals.
4. OTA agency versus merchant economics: commission accrual/credit, agency invoice/payment, merchant gross-to-net settlement и bank.
5. Corporate contracts/blocks, earned monthly invoices, line mapping, advances, partial receipt applications и due-date aging.
6. Housekeeping approved tasks, employee actual time/weekly overtime, agency shifts, linen/laundry/supplies и одноразовый payroll/bill cost.
7. Vendor PO/receipt/bill/payment/open AP; capex versus routine repair, assets/depreciation/debt principal/interest.
8. GL P&L/BS/monthly TB, bank and subledger reconciliation; zero-sum analytical shared allocations.
9. Own marketing cost и direct funnel; platform attribution separately.
10. Frozen original budget и drivers; distinct forecast versions и explicit assumptions.

Критические правила:

- Future confirmed/on-books reservations после cutoff — bookings, не actual occupied nights и не earned revenue. Group block также не occupied/sold.
- Room/date capacity = physical−OOO−OOS для внутреннего availability. Sold occupancy=sold/available; ADR=net room after discounts/credits divided sold; RevPAR=net room/available. Comp/house-use не sold. Ratios пересчитывай из totals.
- Stay crossing month-end/cutoff признаётся night-by-night, а не целиком в booking/checkout month. Corporate invoice не создаёт revenue повторно.
- Lodging prepayment2200/2220 — deferred until consumed; refundable security2210 отдельно. Capture, payout и bank deposit не три продажи.
- Agency guest pays hotel gross, гостиница должна commission2010. Merchant gross earned room to1120, commission5000/2010, synthetic OTA tax2110; settlement clears gross to net. Не считать net bank payout всей выручкой.
- Credits/refunds отдельными событиями с original/parent IDs; не переписывай исходные charge amounts задним числом и не списывай один credit дважды.
- Employee withholding уже в gross; employer tax/benefit additional. Payroll earned и funded dates различаются; OctoberH2 payable — известный future cash out, без fabricated bank payment.
- Operations logs и vendor/payroll GL описывают один expense. Daily ad spend и monthly billing также один expense. OTA commissions separate from own media spend; overlapping Meta/Google booking values не company revenue.
- Assets/debt/distributions не expense целиком: depreciation/interest P&L, principal/distributions financing. Rent case simplification описана.
- CORP shared expense уже в company GL; bridge allocations sum0, source_cost repeated reference. Property contribution до/после shared показывай с названиями.
- GL signed TB = debit−credit; P&L activity, не cumulative revenue account balance. Opening отдельно. Budget income/expense positive, contra-revenue negative.

Для13-week forecast2026-11-01–2027-01-30 используй CASH_FORECAST_INPUTS_RU.md. Opening bank отдельно от clearing/transit; known_cash_inputs — COPY index, source balances альтернативны, не additive. Устранить overlap: open AP vs recurring prior month, current payroll liability vs future earned payroll, merchant net settlement vs gross AR/tax/commission, held advances vs future OTB collection, billed capex vs unreceived PO commitments. OTB corporate payments идут по service months и65/35 dates; merchant future cash рассчитывается по nightly weekly-release rule. New demand только remaining available capacity после OTB. Forecast assumptions могут меняться, historical actuals остаются историческими. Future due/expected dates не actual events.

После сверок можно реализовать Business Overview, Property/Channel Economics, Occupancy/ADR/RevPAR, Corporate AR, Operations, BVA, Rolling Forecast,13-week Cash и Data Quality. Выбери собственный стек. AI commentary должен показывать конкретные рассчитанные drivers и traceable source IDs, а forecast — версию assumptions и сценарий. Начни с краткой карты нормализованных grains и результатов собственных сверок, затем реализуй систему.

---
