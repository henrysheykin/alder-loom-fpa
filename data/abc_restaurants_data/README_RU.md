# Cedar & Skillet — ресторанные данные для AI FP&A

Полностью синтетическая американская сеть из трёх casual dining ресторанов и общей управляющей компании. Данные готовы для самостоятельного построения отчётности, BVA, rolling forecast и 13-week cash forecast в Claude. Сами дашборды и рассчитанный прогноз не входят в пакет.

Факт: **2024-11-01 — 2026-10-31**, 24 полных месяца. Snapshot: **2026-10-31**. Валюта USD. Локальная зона America/New_York. 92 логические таблицы, 736 исходных CSV, 4,402,229 строк. HQ — центр общих расходов, а не четвёртый ресторан.

Все компании, контрагенты, сотрудники и операции вымышлены. Контакты используют example.com. Реальных аккаунтов Toast, DoorDash, Uber Eats, Gusto, QuickBooks, Meta, Google или 7shifts здесь нет. Их бренды обозначают тип моделируемого источника. Схемы собственные: точное совпадение с native export или версией API не заявляется.

## Начало работы

1. Прочитайте COMPANY_PROFILE_RU.md и ACCOUNTING_AND_CONVENTIONS_RU.md.
2. Изучите metadata/source_catalog.csv, table_catalog.csv, data_dictionary.csv, relationships.csv и table_schemas.json. В схеме перечислены все физические monthly partitions.
3. Загрузите только CSV из sources/. Объедините месячные части одной таблицы через UNION ALL. IDs читайте как строки, money — Decimal или integer cents. Колонки английские, CSV UTF-8 BOM, разделитель запятая, десятичная точка. Даты ISO; пустое поле — отсутствие значения, не ноль и не будущий факт.
4. Запустите независимый verifier. Он повторно прочитает CSV, восстановит связи/арифметику и сравнит ваши сохранённые controls.
5. Передайте готовый CLAUDE_HANDOFF_RU.md в Claude вместе с каталогом или нужными ZIP источников.

```powershell
python tools/verify_dataset.py . --scratch ./work/verification
```

Нужен только Python 3.11+ со стандартной библиотекой, без pip-пакетов. Запуск из корня распакованного пакета. Временная SQLite-база требует ориентировочно 2–3 GB свободного места; основной набор около 0.60 GB. В зависимости от компьютера проверка займёт несколько минут. Код возврата 0 означает PASS; 1 — найдены ошибки. Verifier пишет validation_report.csv и validation_summary.json, но не меняет sources/. Не используйте `--write-controls` при обычной проверке: этот флаг явно пересоздаёт эталон из текущих файлов.

## Что находится в папках

| Папка | Содержание |
|---|---|
| sources/toast_pos | Меню/цены, чеки/строки/модификаторы, comps/voids/refunds/tenders, daily closes, marketplace mapping |
| sources/card_processor | Карточные события, fees и payout batches |
| sources/doordash; sources/ubereats | Зеркальные POS-заказы, финансовые события и settlements по отдельным платформам |
| sources/procurement | Поставщики/прайсы, PO, графики доставок, приёмки, invoices и shortage/damage credits |
| sources/kitchen_inventory | Ингредиенты/конверсии/рецептуры/yield, движения и стоимость, waste/staff meals/transfers/counts |
| sources/timekeeping; sources/gusto_payroll | План смен, фактические минуты/OT/ставки, tips, earnings/withholding/taxes/funding |
| sources/quickbooks | Chart of accounts, opening/period TB, двойная запись, bills/credits/payments/applications |
| sources/bank; sources/cash_operations | Выписки банка, кассовые остатки, tip payouts, petty cash и deposit bags |
| sources/meta_ads; sources/google_ads | Дневные метрики и billing с привязкой к accounting bill |
| sources/management_planning; sources/treasury | Original approved budget, recurring cycles, source-linked commitments, debt/assets/tax |
| metadata | Каталоги, полный словарь, связи, research, assumptions, примеры и SHA-256 manifest |
| validation | Результаты проверок и 96 monthly controls: 24 месяца × company + три ресторана |
| tools | Самодостаточный независимый file-based verifier |

Большие 28 логических таблиц разделены по месяцам. Источники находятся единожды в sources/. JSON traces — копии примеров, controls — эталоны, отдельные source ZIP — альтернативный способ загрузки. Не добавляйте их повторно к фактам.

## Важные правила

- Продажа и налог/чаевые — разные сущности. POS sales уже содержат marketplace orders. Складывать POS и DoorDash/Uber Eats sales нельзя.
- Add-ons уже включены в check_lines.modifier_gross_usd и header gross. Присоединение modifiers без агрегации размножает чек.
- Полностью comped чек с нулевой суммой закрывается без успешного tender/capture и card fee. Comped блюдо приготовлено и потребляет ингредиенты. VOID до кухни не создаёт продажу/оплату/потребление. Refund не возвращает приготовленную еду на склад.
- Карточный payout, marketplace settlement и cash deposit не являются повторной продажей. Наличные tips выплачены в день сбора; карточные оплачиваются один раз через payroll.
- Supplier invoice и accounting bill — одно начисление в двух источниках. PO — обязательство, receipt — запас, recipe issue/waste — расход; это разные события.
- Ad daily spend и monthly bill описывают один расход. Атрибуция Meta и Google может пересекаться.
- TB sign — debit minus credit; выручка и liabilities в TB обычно отрицательные. P&L за месяц берите из оборотов, а не накопленного closing balance.
- Открытый bill, его installment и BILLED recurring obligation могут описывать одни деньги. Будущие циклы добавляйте только после устранения overlap.

На срезе действительно открыты AP USD138921.66, net payroll payable USD141126.75, payroll taxes USD46771.62, sales tax USD46362.43; есть 18 unreceived POs и pending settlements. Для funding 2 ноября и других согласованных будущих сроков сохранены schedules, а будущих actual bank/receipt/GL событий нет. cash_commitments — индекс исходных обязательств, а не готовый 13-недельный forecast.

## Проверка и пределы модели

validation/validation_summary.json содержит итог текущего прогона, validation_report.csv — группы проверок, evaluated и failures. Сверки money требуют **0 cents difference**. Qty хранится с шагом 0.000001 base unit; контроль на сохранённой точности требует нулевой разницы. yield округляет raw-per-portion один раз, затем умножает на количество servings; стоимость WAC округляется на каждом issue до цента.

metadata/file_manifest.csv покрывает неизменяемый payload, включая каждый source CSV, docs, schema, verifier и controls. Он исключает себя и перегенерируемые validation_report.csv / validation_summary.json / mutation_test_report.csv / report_manifest.csv. Три отчёта хешируются отдельно в validation/report_manifest.csv; сам manifest не хеширует себя. Контрольные суммы ZIP находятся рядом с архивами в outputs/ARCHIVE_MANIFEST.csv; такая структура исключает самоссылку хешей.

Модельные tax/payroll rates, комиссии, цены и банковский календарь — допущения, а не юридические/тарифные сведения. Полного платного NRA Abstract мы не заявляем: использованы проверенные публичные комментарии NRA. Источники и границы применения приведены в RESEARCH_AND_ASSUMPTIONS_RU.md и metadata/research_sources.csv.
