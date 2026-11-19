# Сквозные записи из сохранённых CSV

Все JSON в этой папке — **копии для объяснения**, не дополнительные факты. Канонические строки находятся в sources/.

- Retail: RO `RO-00020234`, invoice `INV-00024635` от 2026-09-02, USD 493.83. Parts + labor -> actual segments -> FIFO issue/WIP -> delivered invoice/COGS -> card capture/fee -> batch payout -> bank. В JSON включены все constituents соответствующего payout: сумма банковского batch может превышать вклад одного RO.
- Fleet: RO `RO-00003273`, invoice `INV-00021476` от 2026-06-01, USD 471.76. Две оплаты: 40% и 60%; final collection позже net30 и нескольких циклов payroll. Due date не равна actual payment date. ACH batch в банке включает другие поступления.
- Supplier: PO `PO-00000017`, bill `BILL-00000024`. Приёмка увеличивает inventory и AP; возврат уменьшает stock по стоимости исходного lot и создаёт vendor credit; cash payment погашает остаток AP. Statement лишь повторяет существующие bill/credit, COGS возникает отдельно при выдаче автомобиля.

В trace нет второй проводки job labor cost allocation: это управленческая детализация уже начисленной зарплаты. Для полного payroll->bank funding сопоставляйте earning_id/payroll_run_id с источником payroll и GL.
