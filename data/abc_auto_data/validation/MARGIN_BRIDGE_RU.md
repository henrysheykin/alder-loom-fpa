# RO margin и P&L: временной мост

Два CSV содержат 24 company и 96 location/HQ строк, вычисленных заново из сохранённых sources. Они являются control outputs, не источниками новых фактов.

RO cohort margin = net invoices выданных клиентских RO − FIFO parts COGS этих RO − outsourced cost − фактический payroll, распределённый на все их сегменты, включая другие earned periods.

Чтобы перейти к GL contribution периода, вычтите текущие concessions, непродуктивную/неразнесённую оплату, warranty labor allocation и `labor_earned_vs_delivery_cohort_timing`; вычтите warranty parts и stock writeoffs, прибавьте supplier recovery. Timing может быть отрицательным: это перенос между периодом выполнения и периодом выдачи.

Consolidated direct contribution = net earned revenue − debit-net 5000/5010/5015/5100/5110/5120/5130/5200. Следующий уровень location contribution вычитает локальные overhead GL. Shared cost allocation — отдельная нулевая по компании управленческая таблица, к consolidated expense второй раз не добавляется.

Зарплата полностью признаётся по earned payroll. RO allocation и этот bridge не создают проводок. WIP содержит issued parts и completed sublet, без капитализации labor. Все расхождения должны равняться 0.00 USD; скрипт `add_margin_controls.py` останавливается при любом ненулевом расхождении.
