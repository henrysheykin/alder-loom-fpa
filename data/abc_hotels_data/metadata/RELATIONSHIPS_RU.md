# Карта связей и grains

Машиночитаемая карта — `relationships.csv`, ключи/типы/partitions — `table_schemas.json`. Blank FK разрешён только при неприменимости или ещё не наступившем событии. В metadata condition channel_id=BOOKING/EXPEDIA задаёт разные targets одного settlement_id.

```mermaid
flowchart LR
  B[Booking] --> R[Room reservation]
  R --> A[Room assignment]
  A --> N[Actual consumed room-night]
  C[Room master + closures] --> V[Room/date capacity]
  N --> V
  N --> F[Earned folio line]
  F --> I[Corporate monthly invoice line]
  I --> AR[Invoice AR + receipt application]
  R --> P[Guest capture / advance liability]
  P --> APPL[Deposit application]
  APPL --> F
  P --> BT[Processor balance transaction]
  BT --> PO[Payout initiated]
  PO --> T[Cash transit]
  F --> OTA[Gross OTA AR + commission]
  OTA --> S[Merchant settlement components]
  S --> T
  T --> BANK[Actual bank arrival]
  N --> HK[Cleaning work / linen]
  HK --> W[Employee approved time + agency]
  W --> PY[Earned payroll / vendor bill]
  PY --> GL[GL double entry]
  F --> GL
  AR --> GL
  BANK --> GL
```

Никогда join двух фактов many-to-many только по reservation_id для sum money: несколько nights × несколько captures × несколько invoice lines умножат строки. Сначала агрегируйте каждый факт по целевому grain, либо соединяйте line-specific payment application/folio_line_id. Аналогично rooms/date ↔ tasks может иметь несколько tasks, нужны count DISTINCT task_id и preaggregation.

Group booking и group allotment различаются: bookings→booking_rooms→reservation; corporate group_blocks→group_pickups→reservation. Occupancy берётся из actual nights, а не количества blocks. Channel reservation export — mapping той же reservation, не дополнительная продажа.

Corporate invoice_line_id→folio_line_id — exact earned service mapping; GL invoices source только перекидывает1130→1100. Merchant settlement_line_id→folio_line_id→commission: folio net+tax−commission−OTA tax=net remittance. Agency commission settlement_id указывает на agency_invoice_id, merchant — на settlement_id.

Bill lines могут ссылаться на operational property/month composite в source_id: это описательная aggregation reference, не универсальный одноколоночный FK. По purchase_order_line_id и bill_line_id есть строгие receipt mappings. General ledger source_id — polymorphic key, source_system/source_table обязательны для join. Для allocation_id source_cost повторяется по recipients и donor; не суммируется.
