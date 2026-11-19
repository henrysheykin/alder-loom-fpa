# Упрощённая бухгалтерская и управленческая policy

Это заданная policy синтетического кейса. Не утверждается, что проведён аудит, подготовлена GAAP/IFRS-compliant отчётность или рассчитаны реальные налоговые обязательства. Общая логика отделяет выполнение услуги, требование оплаты и денежный расчёт; официальные conceptual sources перечислены в RESEARCH_NOTES_RU.md.

## Fee revenue

Retainer — monthly stand-ready/management service с условным равномерным оказанием внутри месяца; для месячного reporting признаётся одной записью в последний день service month. Monthly approval служит evidence завершения месяца. Flat retainer не зависит от actual hours/spend. Для percentage-of-spend SOW fee = max(monthly minimum, applicable contractual share × фактический mapped Meta+Google monthly spend). Variable fee окончательно определяется на month-end; признаётся тогда, invoiced next month5. Никакой media budget не включается в transaction price агентских услуг.

Fixed SOW специально состоит из трёх самостоятельных distinct deliverables. Revenue признаётся point-in-time на actual_approved_date данного deliverable в размере agreed fee. Модель не применяет cost-to-cost/percentage-of-completion и не выдаёт timesheet progress за acceptance. Milestones могут быть приняты позднее planned date. Будущие actual approvals пустые.

Hourly analytics/experiments: только approved staff hours × effective role rate, суммированные по контракту/service month; daily rates берутся из rate_cards, округление каждого time entry до цента. Submitted October time не признаётся и не выставляется. Employee salary rate, client bill rate, utilization и realized effective rate — разные показатели.

Fee concessions — отдельные post-service credit notes на даты выдачи. Они уменьшают AR и net recognized fees через contra-revenue 4090; original invoice и gross service fee не переписываются. По этим двум credits ещё не было полной оплаты исходного invoice, поэтому cash refund/unapplied credit не требуется.

## Invoice, contract asset и liability

У каждого service_id собственная позиция. Advance invoice создаёт AR и deferred fee liability даже до получения cash. Earned unbilled service создаёт asset 1150. Поэтому deferred balance может включать unpaid advance invoice: это billed-but-unearned, а не автоматически «все деньги уже собраны». Для CLI-002 ноябрь–январь advance действительно оплачен до cutoff.

| Событие | Debit | Credit |
|---|---|---|
| Invoice до выполнения service | 1100 AR | 2300 deferred fees |
| Invoice ранее заработанной части | 1100 AR | 1150 unbilled earned fees |
| Earning из уже выставленного advance | 2300 deferred fees | 4000/4010/4020/4030 fee revenue |
| Earning ещё не выставленной платы | 1150 unbilled fees | fee revenue |
| Fee concession | 4090 contra revenue | 1100 AR |
| Client receipt | 1000 bank | 1100 AR |

При частичном invoice сначала погашается существующий unbilled asset конкретного service_id, остаток идёт в deferred. При earning сначала используется deferred того же service_id, остаток — unbilled. Обязательства разных service_id не неттируются друг с другом. После concession остаются gross service-position flows; net bridge использует invoices minus credits и revenue minus concessions.

Monthly identity: **net earned fees = invoices − credits − increase in deferred + increase in unbilled**. AR: opening + invoices − credits − receipts = closing. Receipt application — ссылка между cash и invoice, не вторая операция cash. В наборе каждый ACH receipt применяется к одному invoice; некоторые invoices имеют два receipts.

## Client media и attribution

Все accounts принадлежат clients; payer_client_id = client_id, funding_responsibility = CLIENT_DIRECT, agency_pays_platform = False. Агентство не приобретает и не перепродаёт рекламный инвентарь, не собирает client funds и не несёт media funding liability. Client media не присутствует в agency P&L, bank или AP. Отдельного principal-versus-agent расчёта для pass-through не требуется: pass-through transactions отсутствуют. Reporting fee агентства отражает только оказанные услуги.

Monthly platform billing — аналитическая консолидация daily spend, не точный invoice/payment export Meta или Google. Оплата client bank не наблюдается: CLIENT_DIRECT_SETTLEMENT_NOT_OBSERVED. Google micros — альтернативная единица той же суммы. Platform conversions/value могут пересекаться; deduplicated client revenue fact отсутствует.

## Payroll и margin allocation

Gross salary включает employee withholding. Net = gross − withholding. Employer cost = gross + employer tax + employer benefit. За каждый полумесяц расходы и payroll liabilities признаются на earned_end_date. Net liability 2100, withholding+employer tax 2110, employer benefit 2120. Expense accounts: delivery 5000/5001/5002, operations 6000/6001/6002.

Один modeled provider bank debit погашает все три liability components. Provider funding включает remittance taxes/benefits; дополнительное перечисление тех же налогов не создаётся. В реальном Gusto funding может разбиваться на несколько debits; агрегирование и benefits внутри funding — упрощение кейса.

Daily paid capacity = 8 часов по рабочим будням. Рабочее время + paid leave = paid capacity. Employer cost каждого employee/payroll period распределяется пропорционально проектным, внутренним и paid leave hours; largest-remainder rounding сохраняет сумму до цента. Вся allocation — вторичный view, is_additional_gl_expense=False. Submitted work всё равно потребляет salary cost, хотя hourly revenue ещё нет.

Client/project contribution = net earned fees данного проекта − project-allocated employer cost − accepted freelancer cost проекта. В non-billable overhead остаются delivery bench/internal и paid leave, плюс corporate overhead. Gross profit компании = net fee revenue − все delivery salaries/taxes/benefits, включая bench/leave, − accepted freelance delivery expense. Поэтому сумма project contributions отличается от consolidated gross profit на unallocated-to-client delivery bench/leave. Operations payroll входит ниже gross profit. Cross-project timing может дать месячную project margin без revenue в месяце подготовки; анализируйте и whole-SOW margin.

## Freelancers и AP

Approved work — единственная точка cost recognition: Dr5010, Cr2200 accrued contractors. Invoice следующего месяца: Dr2200, Cr2000 AP. Payment: Dr2000, Cr1000. Contractor invoice lines и QB bill lines — копии одной payable stage, связаны approved_work_id/source_line_id; повторно 5010 не дебетуется. На cutoff октябрьские accepted costs ещё в accrual 2200, а полученные сентябрьские invoices могут быть в AP 2000.

Остальные operating bills признаются на service month-end. Rent/SaaS/professional/travel/training идут в expense и AP. Annual insurance invoice — Dr1200 prepaid, CrAP; monthly amortization Dr6120/Cr1200. AP = opening + received bills − applied vendor payments. PO/work order до acceptance является authorization/commitment, не expense.

## Opening, debt и финансовые знаки

Opening TB 2024-10-31 исключён из GL activity. Supporting opening AR invoices на ноябрьскую услугу соответствуют opening deferred; pre-period settled CLI-002 quarterly advance идёт только в opening_service_balances, без повторного cash факта. Октябрьский unbilled hourly fee USD6,000 выставляется в ноябре без повторного earning. Opening AP USD18,000 уже был expensed до окна; его выплаты уменьшают AP. Opening payroll уже earned, его November funding не создаёт November expense.

Equipment gross USD120,000, opening accumulated depreciation USD40,000, monthly depreciation USD2,000. Нет новых capex/disposals в окне. Loan principal не expense, только contractual interest 6400. Owner distributions 3100 — equity/financing, не operating cost. 13-week forecast не должен автоматически повторять discretionary distributions.

Trial balance знак = debit minus credit. Revenue обычно credit, для положительной fee revenue используйте credit minus debit; contra 4090 уменьшает net revenue. P&L — period activity. Temporary accounts не закрываются в конце года; accumulated balances отражают всё окно. Opening + monthly GL activity = closing TB до цента.

## Forecast overlap

Для cash forecast начните с bank cash 2026-10-31. Существующий AR связан с collection_expectations; ожидаемая дата не actual. Будущие scheduled invoice lines добавляются один раз по schedule_line_id; signed_future_commitments — удобная копия. Известный unbilled October fee можно выставить по schedule, затем прогнозировать сбор — это не повтор October revenue.

Уже invoiced/collected November–January CLI-002 fee не попадает во future invoice schedule и не приносит ещё один cash inflow при earning. Open vendor bills покрываются через ap_open_items; October uninvoiced contractors — через contractor_accruals, не через добавление того же балансового 2200. Payroll_commitments покрывает earned-unfunded 2100/2110/2120; будущие payroll periods моделируются из current roster/rates/capacity assumptions. Current recurring open bill — предыдущий service cycle; next_service_start_date начинает следующий. Annual insurance renewal после 2027-06-30 — продолжение как assumption, не подписанное продление. Debt_schedule содержит future contractual dates, без actual cash.
