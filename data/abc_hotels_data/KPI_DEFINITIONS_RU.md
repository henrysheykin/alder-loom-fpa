# KPI definitions: additive drivers first

| Показатель | Определение кейса | Источники / ограничения |
|---|---|---|
| Physical room-nights | keys × dates | room master + availability room/date; одна строка на key/date |
| Available nights | physical − OOO − OOS | оба статуса исключены для внутреннего denominator; comp/house-use остаются в available |
| Sold nights | actual consumed paid stays | pms actual_stay_nights stay_status=sold; не booking/block/no-show |
| Occupied nights | sold + complimentary + house_use | actual occupied; checkout exclusive |
| Sold occupancy | SUM(sold)/SUM(available) | основной occupancy, без сложения/усреднения monthly ratios |
| Occupied occupancy | SUM(occupied)/SUM(available) | включает complimentary и house-use; это не sold occupancy |
| Net room revenue | gross room4000 − discounts4010 − service credits4020 | folio type room+room_credit; tax/ancillary/fees исключены |
| ADR | net room revenue / sold nights | sold, а не occupied; service credits уменьшают numerator без удаления sold night |
| RevPAR | net room revenue / available nights | ADR × sold occupancy при тех же scope/date/denominator |
| Ancillary revenue | parking4100 + breakfast4110 + cleaning/late4120 | услуги по consumed service date, separate from room |
| Total revenue | net room + ancillary + cancellation/no-show fees | tax и security исключены |
| Distribution cost | all accrued OTA commissions5000, including fee-related | own Meta/Google5400 и processing5010 отдельно |
| Net ADR after OTA commission | (net room − только room/room_credit-related OTA commission)/sold | commissions on cancellation/no-show fees исключены из этого numerator; direct commission0 |
| Channel economics | net earned room по channel − related commission, optionally processing/own ads separately | merchant net payout не surrogate revenue; атрибуцию платформ не складывать |
| Corporate AR | earned invoices − cash/prepayment applications | due-date aging на cutoff; не будущие monthly invoices |
| Cancellation rate | cancelled reservations / all room reservations of scheduled-arrival cohort | reservations count, не nights; multi-room booking counts several components; на выбранный as-of |
| No-show rate | no_show reservations / scheduled-arrival cohort | no occupied night; earned fee separately |
| Housekeeping defined cost | 5100 employee gross +5150 agency +5200 laundry +5210 consumables | employer tax/benefit не включены; показывать выбранное определение |
| HK cost per occupied night | defined HK cost / occupied nights | extended stays имеют weekly service; сопоставлять с format mix |
| HK cost per serviced room | тот же defined cost / approved cleaning tasks | включает зарплату и непродуктивное оплачиваемое время; несколько задач в одном key/day возможны как разные services |
| Property contribution / EBITDA before shared | earned total revenue − property opex excluding5600/5700 | включает property rent, utilities, distribution, own ads; CORP costs excluded from individual properties |
| EBITDA after shared allocation | before − analytical allocated shared expense | company consolidated EBITDA одинаков до/после allocation |
| Net income | earned revenue − all expenses incl depreciation/interest | principal и distributions excluded |
| BVA revenue | actual revenue − original budget revenue | positive favorable for revenue |
| BVA expense | actual expense − budget expense | positive unfavorable; показывать sign явно |
| BVA EBITDA | actual EBITDA − original budget EBITDA | positive favorable |

В controls доступны 96 monthly rows: COMPANY включает CORP; три physical properties показываются отдельно. Чтобы company contribution совпал с суммой properties, примените zero-sum allocations и учтите CORP residual0. Не суммируйте COMPANY вместе с properties. Чтобы объединить месяцы или объекты, складывайте cents/nights, затем делите. ADR и RevPAR в control file имеют6 decimal places для display; occupancy8. Никакого ограничения «ADR×sold≈revenue» из-за gross-versus-net путаницы нет: numerator определён точно; rounding display tolerance отдельно.

В monthly controls property EBITDA BVA сравнивает EBITDA до shared allocation с исходным property budget без CORP. COMPANY budget и actual уже включают CORP. Для BVA после shared allocation сначала распределите также budget CORP cost по тому же driver, чтобы scopes совпадали. Account3100 drawings имеет normal debit sign, несмотря на equity classification.

Cancellation/no-show costs могут влиять на total distribution expense, но их earned fees не входят в room revenue. Credit по прошлой ночи в этом кейсе отражён на service recovery date внутри того же stay; original night mapping сохраняется. Long stays: earned nights попадают в каждый сервисный месяц, invoice month-end не меняет revenue recognition.

OOO/OOS policy намеренно является внутренней управленческой политикой; её нельзя автоматически назвать denominator стандартного STR benchmark. Данные поддерживают пересчёт альтернативного denominator из physical/closure flags, если явно сменить KPI definition.
