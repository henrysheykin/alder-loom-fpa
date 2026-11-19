# Сквозные traces — copies из исходных CSV

JSON examples — сохранённые копии строк, не дополнительные facts. Все identifiers существуют в sources/. Для compactness показаны выбранные reservation components; payout/settlement headers и их GL относятся к целому property batch с другими reservations. Не пытайтесь приравнять одну reservation к целой weekly batch.

## Direct prepaid: RSV-00020333

RAL room101, booking2026-10-20, scheduled stay2026-10-29–2026-11-03, checkout exclusive. Один lodging capture2026-10-22; три breakfast charges по USD24 погашены из того же deposit, отдельного ancillary capture в этом trace нет. К cutoff потреблены3 ночи, ещё2 — OTB; actual checkout пустая. Фактический payment gross USD 823.02; processor fee USD 22.88 отдельным expense.

1. pms/reservations даёт quote на5 ночей; это не весь actual October revenue.
2. payments/transactions: net to1010, fee5010, gross to2200.
3. Три actual stay nights и соответствующие folio lines дают earned room/ancillary net **USD 513.40**, tax **USD 49.66**. Для будущих двух ночей folio/GL нет.
4. Deposit applications2200→1110 погашают earned charges, не создают cash/revenue повторно.
5. На cutoff lodging advance liability этой reservation **USD 259.96** частично покрывает будущие room+tax charges **USD 331.96**. После использования депозита на breakfast остаётся **USD 72.00** incremental collection; это видно в booked_payment_terms. Уже удержанный deposit не является ещё одним future cash receipt.
6. Lodging capture balance transaction принадлежит Friday payout2026-10-30; expected bank2026-11-02, actual bank date blank на cutoff. Full batch payout не равен сумме одной reservation. Исторического November bank credit нет.

## OTA merchant across cutoff: RSV-00020334

WIL room101, scheduled/actual consumed stay2026-10-25–2026-10-29:4 ночи. Гостя собирает EXPEDIA-style merchant, hotel gateway capture для room charges отсутствует.

1. Earned folio revenue **USD 692.88**, tax **USD 86.60**, gross OTA AR **USD 779.48**.
2. Separate distribution commissions **USD 124.72**, expense5000/payable2010; gross room revenue остаётся в4000/contra.
3. Selected settlement components: gross−OTA tax−commission = **USD 568.16** net remittance для этой reservation. Full settlement header содержит также другие reservations.
4. Release2026-10-31: clear1120 gross,2010 commission,2110 OTA tax; net to1020 cash-in-transit. Expected bank2026-11-02, actual bank date blank.
5. В hypothetical November forecast arrival переносит1020→1000; такой future actual cash не добавлен в source bank или GL. Net remittance не является новой room sale.
