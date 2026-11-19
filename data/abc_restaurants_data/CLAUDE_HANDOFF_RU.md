# Готовое задание для Claude

Скопируйте текст ниже в Claude Code/другую среду с доступом к распакованным файлам. Если загружаете отдельные ZIP, сохраняйте sources/<system>/ и metadata, tools, validation из documentation ZIP; полный ZIP уже содержит всё один раз.

---

Я строю демонстрацию AI FP&A для Cedar & Skillet Hospitality LLC — полностью синтетической US casual dining сети с тремя ресторанами Raleigh/Durham/Cary и shared HQ. Данные уже созданы, создавать новые случайные факты не нужно. Любые будущие интерфейсы/скриншоты помечай Synthetic data / Demo company, не представляй компанию реальным клиентом.

Факт: 2024-11-01 — 2026-10-31, snapshot 2026-10-31, USD, America/New_York. Здесь 92 logical tables в 15 источниках и monthly partitions больших фактов. Прочитай README_RU.md, COMPANY_PROFILE_RU.md, ACCOUNTING_AND_CONVENTIONS_RU.md, RELATIONSHIP_MAP_RU.md. Затем metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, table_schemas.json, relationships.csv. Посмотри example_check_trace.json и example_purchase_trace.json: это копии реальных строк пакета, не дополнительные факты.

Начни с программного импорта и сверок. Читай CSV как UTF-8 BOM, IDs text, dates ISO, money Decimal/integer cents, qty integer millionths of base_uom. Объединяй parts одной таблицы через UNION ALL. Источники загружай единожды из sources/, не подмешивай examples, controls, ZIP-копии или snapshots к исходным событиям.

Запусти tools/verify_dataset.py из корня пакета с отдельным scratch directory. Ожидается exit code 0, failures=0. Изучи validation_report.csv. Самостоятельно пересчитай monthly metrics и сравни с validation/monthly_control_totals.csv: 24 месяца × COMPANY/R01/R02/R03. Controls — эталон сверки, а не источник будущего дашборда. Company включает HQ overhead, хотя HQ не имеет отдельной строки controls.

Построй нормализованный слой: served POS lines + separate dated refund fact, check/payment relation, marketplace mapping/events/settlements, supplier PO/receipt/invoice/credit/payment applications, ingredient recipe/quantity/cost ledger, planned vs actual labor, earned payroll vs funding, full GL/TB, bank/cash, advertising spend and original approved budget. Сохрани происхождение каждой метрики и source IDs.

Критические правила:

1. POS уже содержит все CLOSED marketplace orders. DD/UE используются для fees, promotions и cash settlement; не складывай их продажи с POS. В map один внешний order соответствует одному POS check.
2. Modifiers уже в parent line gross. Перед соединением нескольких дочерних фактов агрегируй каждую сторону; header totals повторять по каждой line нельзя.
3. Discounts/comps уменьшают revenue. Comped meal consumes recipe. VOID before prep does not consume or pay. Refund dated separately; prepared food не возвращается в inventory.
4. Tax/tips не revenue. Direct tax liability отдельно; marketplace tax полностью platform-retained только по допущению этого кейса. Courier tips/fees вне merchant books.
5. Platform-funded consumer discount reimbursed, не дополнительная выручка. Merchant POS discount уже в net sales; merchant promotion fee — отдельный расход платформы.
6. Card/marketplace payout и cash deposit — balance sheet transfers. Processor net = capture - refund - fees. Marketplace net excludes retained sales tax.
7. Cash tips already paid same day; card tips once via payroll. Wage expense excludes tips, taxable gross includes both types. Net pay = wages + card tips - employee withholding. Employer taxes separate expense; funding is later cash. Card tips in approved run move from 2020 into 2010 net payable.
8. Timesheet minutes, weekly carry/OT and effective rates explain hourly cost. Плановые смены не actual expense. Opening workweek minutes are already paid pre-window; do not create opening payroll AP from them.
9. PO is not COGS. Accepted receipts create ingredient inventory; raw recipes and WAC issues explain COGS. Pack/base conversions ingredient-specific. Cooked output does not create finished-goods stock. Sort movement_sequence numerically.
10. Shortage/damage credits close that PO quantity and reduce invoice/AP; do not treat it as backorder. Supplier invoice/accounting bill — зеркала. Credits noncash. Vendor payment can pay many bills: use application amount, not full bank amount per bill.
11. Daily advertising spend and monthly bills describe one expense. Meta/Google attributed revenue overlaps and is not total company sales.
12. TB signs = debit minus credit; period P&L from monthly activity, not cumulative closing revenue balances. HQ holds common bank/debt/overhead; individual restaurant analytical TB need not balance as a standalone entity.
13. Original budget approved 2024-10-15 remains immutable. Actual, budget and new forecasts need different scenarios/versions. Debt principal and owner draws never operating expenses.
14. Current price/pay-rate effective_to пустой, значит условия продолжаются до замены. Carry-forward last-known terms в forecast оформи как сценарное допущение. Финальные DD/UE batches с ID 20261101 содержат только earned activity до cutoff; ожидаемые Nov 1 Sunday orders попадут в тот же weekly settlement и добавляются к известной части один раз. На срезе есть реальные open AP, approved/unfunded payroll, tax, pending settlements и unreceived POs. Future scheduled dates не actual transactions. Recurring BILLED obligation overlaps its bill; cash_commitments also indexes raw schedules, do not add twice.

После сверок можешь реализовать Business Overview, restaurant/menu/channel economics, Budget vs Actual, labor/productivity/waste, rolling forecast, 13-week cash forecast и reconciliation monitoring в выбранном для моей демонстрации стеке. Архитектуру/инструменты выбери и кратко обоснуй. Для прогноза заранее зафиксируй driver assumptions, версии, сценарии и cutoff; не выдавай утверждённые commitments за весь будущий operating cash flow. Горизонт следующего 13-week forecast: 2026-11-01 — 2027-01-30, при Sunday–Saturday это 13 полных недель; при календарных Monday–Sunday явно покажи неполные первую/последнюю недели.

Ищи объяснимые причины отклонений: menu price versions (June 2025/February 2026), supplier inflation (July 2025/June 2026), higher delivery/promotion share in Cary from May 2026, DD commission step June 2026, Durham cook gap/OT summer 2026, fridge waste/repairs September 14 и compressor capex/AP October. Это hypotheses для проверки из raw facts, не готовый AI narrative.

Сначала покажи компактную карту источников и результаты сверок; затем приступай к реализации. Не изменяй исходные CSV ради удобного результата. Для любого AI комментария сохраняй вычисление, период/restaurant/filter и source evidence. Если обнаружишь расхождение, сообщи конкретные IDs и cents/qty difference.

---
