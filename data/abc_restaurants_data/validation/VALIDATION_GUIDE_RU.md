# Проверка пакета

Итог прогона: validation_summary.json. Детализация каждой группы: validation_report.csv. PASS означает отсутствие отклонения на объявленной точности; failures должны равняться нулю. evaluated_conditions — сумма проверяемых условий разных групп, а не число независимых транзакций. PK/FK и date checks включены в это число.

Деньги сверяются до цента без допусков. Ингредиентные quantity сохраняются с шагом 0.000001 base unit; сравнение требует 0.000000 difference. Base-unit quantities, purchase packs и menu servings различаются в data_dictionary.csv.

Покрытие: все объявленные CSV/BOM/колонки/строки и SHA-256; PK/FK; actual cutoff; POS line/header/modifier/discount/comp/void/refund/tender; физическая посадка по guest intervals и seats; зеркальные marketplace orders, tax retention, fees/promo/adjustments и settlements; capture/fees/payout/bank; cash drawer/tips/petty cash/deposits; PO/поставки/приёмки/credits/invoice/AP/cash applications; recipe/yield quantities, perpetual WAC/value/quantity movements, spoilage/staff meals/transfers/counts/daily balances; shifts/clocks/week carry/OT/effective rates, tips allocation, salary/withholding/employer taxes/net/funding; ad spend vs billing/expense; journal balance/source provenance, bank/TB/inventory/clearing/payroll/tax/AP reconciliation; original budget и будущие cash commitments без actual операций.

monthly_control_totals.csv: 96 строк, 24 месяца × COMPANY/R01/R02/R03. Company включает HQ. Site bank balance пустой, поскольку счёт централизован. Сравнивайте month/account/source totals из собственной загрузки, не стройте дашборд непосредственно из controls.

mutation_test_report.csv: 22 намеренных дефекта временной SQLite-базы проверяют чувствительность опубликованных правил. До искажения должно быть 0 violations, после — больше 0, после rollback снова 0. Среди случаев: невозможная посадка, duplicate PK, orphan FK, ошибочная копейка/минуты/recipe micro-unit, утечка transfer value, повторная выплата cash tips, future bank actual, неверный ad spend/tax и повтор cash commitment. Перед тестами включается MEMORY rollback journal; source CSV не меняются.

Обычный повторный запуск из корня: `python tools/verify_dataset.py . --scratch ./work/verification`. Требуется Python 3.11+; зависимостей нет. Он пересоздаёт scratch SQLite и отчёты, читает только сохранённые источники/schema/controls/manifest. Не запускайте параллельно с записью CSV. `--write-controls` используется только при явном изменении самого синтетического набора, а не для сокрытия найденных расхождений.

Основной metadata/file_manifest.csv покрывает static payload и controls, исключая себя и три перегенерируемых отчёта. validation/report_manifest.csv фиксирует SHA этих трёх поставляемых отчётов. После пользовательского повторного запуска report_manifest относится к исходной поставке; повторный verifier не переиздаёт архивы. Данные демонстрационные, проверки являются acceptance controls кейса, не внешним аудитом реального предприятия.
