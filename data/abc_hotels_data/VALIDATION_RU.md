# Независимая проверка сохранённых CSV

Проверка запускается отдельным process/script `reproducibility/verify_dataset.py`; он не импортирует generator modules и не читает его внутренние objects. Reads schema/manifest и source CSV заново; денежная арифметика Decimal/integer cents. Reference monthly controls также заново рассчитываются из raw sources.

Последний полный прогон: **189 check groups**, **27,426,571 evaluated conditions**, **0 failed conditions**. Точное покрытие и examples при ошибке — `validation/validation_report.csv`. Группы объединяют множество row-level assertions, не независимые аудиторские заключения.

Проверяются PK/FK/types/BOM/SHA/counts; actual cutoff;156×730 physical capacity; actual room overlap; closures из intervals; sold/comp/house-use; effective plans; folio/quote/discount/tax/credits; each journal balance; monthly TB; daily bank-to-GL; gateway capture/refund chronology/cumulative limits/fees/batches/transit; merchant/agency gross commission/tax/bank; invoice mapping/partial applications/aging; guest/security/corporate liabilities; vendor PO/receipts/AP/individual bill GL; approved housekeeping/time/agency/linen/bill; weekly overtime/gross-to-net/funding; fixed assets/depreciation/debt/tax; own advertising; original budget dates/drivers; allocation zero-sum; recurring due dates; all known cash categories; OTB monthly corporate timing; two cutoff traces.

Money tolerance0 cents, quantity tolerance0 nights/minutes. Ratios identities проверяются с Decimal tolerance0.00000001 до display rounding. USD6-decimal ADR/RevPAR и8-decimal occupancy в controls — display values. Объединённые KPI пересчитываются из raw numerator/denominator.

`validation/monthly_control_totals.csv` содержит96 строк (24×COMPANY/RAL/WIL/DUR), revenue splits, capacity, occupancy/ADR/RevPAR, commission/net ADR, HK cost, payroll, EBITDA before/after shared, original budget/BVA, cash movement и cutoff/month-end subledger balances. COMPANY не нужно ещё раз суммировать с properties.

Mutation sensitivity test хранит заведомо повреждённую копию только в scratch work/, меняет1 cent в folio, обновляет её source manifest и повторно запускает verifier. Успех теста означает обнаружение экономической ошибки даже после обновления SHA, а не прохождение испорченных данных. Результат — `validation/mutation_test_result.json`; повреждённая копия не входит в deliverables.

Границы: это автоматизированная внутренняя проверка synthetic case. Она не устанавливает полноту реального PMS, правомерность налоговых ставок или compliance гостиничного accounting standard. Независимый reviewer отдельно проверил principal economics, cutoff/settlements, refunds и forecast timing; его исправленные findings и финальный disposition см. `validation/REVIEW_RU.md`.
