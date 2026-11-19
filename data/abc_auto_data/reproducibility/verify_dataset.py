"""Independent audit of Cedar Bend synthetic CSV extracts (Python standard library).

The generator is never imported or executed. All results are recomputed from the
persisted CSV files and metadata. Amounts are integer cents parsed with Decimal;
quantities are integer thousandths; intervals use integer minutes, end exclusive.
Run: python work/verify_dataset.py [--root PATH]
Exit status is 0 only when every check passes; reports are always written.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

START, CUTOFF = "2024-11-01", "2026-10-31"
MONTHS = [f"{2024 + (10+i)//12:04d}-{(10+i)%12+1:02d}" for i in range(24)]
ENDS = {m: f"{m}-{calendar.monthrange(int(m[:4]), int(m[5:]))[1]:02d}" for m in MONTHS}
CENT = Decimal("0.01")


def rounded(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def c(value):
    if value == "" or value is None:
        raise ValueError("A required monetary value is blank")
    return rounded(Decimal(value) * 100)


def q(value):
    return rounded(Decimal(value) * 1000)


def usd(value):
    return f"{Decimal(value)/100:.2f}"


def mins(start, end):
    duration = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    if duration % 60:
        raise ValueError("Physical interval is not an integer number of minutes")
    return int(duration // 60)


def halfkey(employee, day):
    return employee, day[:7], 1 if int(day[8:10]) <= 15 else 2


def readcsv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def writecsv(path, rows):
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Checks:
    def __init__(self):
        self.items = {}

    def test(self, name, condition, example="", difference=0):
        result = self.items.setdefault(name, {"check_name": name, "status": "PASS", "evaluated": 0,
            "failures": 0, "max_difference_cents": 0, "examples": []})
        result["evaluated"] += 1
        result["max_difference_cents"] = max(result["max_difference_cents"], abs(int(difference)))
        if not condition:
            result["status"] = "FAIL"
            result["failures"] += 1
            if len(result["examples"]) < 6:
                result["examples"].append(str(example))

    def equal(self, name, observed, expected, example=""):
        nonmonetary = name in {
            "file_byte_size","manifest_row_count","schema_row_count","source_catalog_row_totals","capacity_actual_clock","capacity_available_minutes",
            "capacity_work_plus_idle","attendance_paid_regular_plus_ot","attendance_presence_plus_pto",
            "availability_interval_minutes","availability_equals_paid_presence","availability_paid_minutes",
            "job_clock_sums_actual_segments","segment_duration_equals_clock","ro_line_approved_exactly_once",
            "inventory_monthend_quantity_milli","parts_issued_equal_ro_physical_quantity","reservation_quantity_rollforward",
            "transfer_quantity_zero_company","count_quantity_arithmetic","count_adjustment_matches_movement",
            "po_pack_conversion_milli","po_ordered_received_open_quantity","po_receipt_quantity",
            "receipt_exactly_one_stock_movement","receipt_stock_quantity_milli","supplier_return_stock_quantity_milli",
            "supplier_document_in_statement_once","delivered_ro_line_invoiced_once","warranty_corrective_clock",
            "payroll_minutes_from_approved_attendance","payroll_clock_from_actual_segments","job_allocations_cover_clock_once",
            "job_allocation_actual_ro_minutes","job_allocation_paid_denominator","approved_attendance_in_payroll_once",
            "card_payments_have_exactly_one_processor_record","bank_sequence_contiguous","bank_monthly_transaction_count",
            "ad_cost_micros_to_usd","budget_grain_unique","future_obligation_in_commitments_once",
            "bay_calendar_open_minutes_policy","bay_calendar_productive_actual","bay_calendar_occupied_open_minutes",
            "bay_calendar_idle_plus_occupied","bay_calendar_all_physical_bays_all_dates",
            "parts_usage_issued_matches_movement_quantity","parts_usage_installed_only_after_completion",
        }
        self.test(name, observed == expected,
                  f"{example}: observed={observed}; expected={expected}", 0 if nonmonetary else observed-expected)

    def rows(self):
        return [{**value, "examples": " | ".join(value["examples"])}
                for _, value in sorted(self.items.items())]


class Audit:
    def __init__(self, root):
        self.root, self.checks = root, Checks()
        self.tables, self.schemas, self.indexes = {}, {}, {}
        self.gl_event = defaultdict(lambda: defaultdict(int))
        self.gl_meta = defaultdict(set)
        self.expected_events = set()
        self.activity, self.closing = defaultdict(int), defaultdict(int)
        self.opening = defaultdict(int)
        self.controls = defaultdict(dict)

    def rows(self, table):
        return self.tables[table]

    def idx(self, table, field=None):
        field = field or self.schemas[table]["primary_key"][0]
        key = table, field
        if key not in self.indexes:
            self.indexes[key] = {r[field]: r for r in self.rows(table)}
        return self.indexes[key]

    def group(self, table, field):
        result = defaultdict(list)
        for row in self.rows(table):
            result[row[field]].append(row)
        return result

    def expect(self, name, source_type, source_id, day, loc, entries):
        key = source_type, source_id, loc
        self.expected_events.add(key)
        expected = defaultdict(int)
        for account, amount in entries:
            expected[account] += amount
        observed = self.gl_event.get(key, {})
        for account in set(expected) | set(observed):
            self.checks.equal(name, observed.get(account, 0), expected.get(account, 0),
                              f"{source_type}/{source_id}/{loc}/{account}")
        self.checks.test(name+"_dates", self.gl_meta.get(key) == {day}, f"{key}: {self.gl_meta.get(key)} vs {day}")

    def load(self):
        check = self.checks
        self.input_hashes = {name: hashlib.sha256((self.root/"metadata"/name).read_bytes()).hexdigest()
                             for name in ["table_schemas.json","file_manifest.csv","relationships.csv","vendor_master_mapping.csv","vendor_relationships.csv"]
                             if (self.root/"metadata"/name).exists()}
        self.schemas = json.loads((self.root/"metadata/table_schemas.json").read_text(encoding="utf-8"))
        _, manifest = readcsv(self.root/"metadata/file_manifest.csv")
        manifest = {r["relative_path"]: r for r in manifest}
        schema_files = set()
        for table, schema in self.schemas.items():
            records = []
            for relative in schema["physical_files"]:
                filename = "sources/"+relative
                schema_files.add(filename)
                path = self.root/filename
                raw = path.read_bytes()
                item = manifest.get(filename)
                check.test("manifest_file_registered", item is not None, filename)
                if item:
                    check.test("file_sha256", hashlib.sha256(raw).hexdigest() == item["sha256"], filename)
                    check.equal("file_byte_size", len(raw), int(item["byte_size"]), filename)
                    check.test("file_logical_table", item["logical_table"] == table, filename)
                check.test("csv_utf8_bom", raw.startswith(b"\xef\xbb\xbf"), filename)
                header, rows = readcsv(path)
                check.test("schema_header_exact", header == schema["fields"], filename)
                if item:
                    check.equal("manifest_row_count", len(rows), int(item["row_count"]), filename)
                if schema["partition_column"]:
                    for r in rows:
                        check.test("partition_month", r[schema["partition_column"]][:7] == path.stem, filename)
                records.extend(rows)
            check.equal("schema_row_count", len(records), schema["row_count"], table)
            seen = set()
            money_fields = [f for f in schema["fields"] if f.endswith("_usd")]
            quantity_fields = [f for f in schema["fields"] if "quantity" in f or f == "base_units_per_purchase_unit"]
            minute_fields = [f for f in schema["fields"] if f.endswith("_minutes") or f == "paid_minutes_denominator"]
            for r in records:
                pk = tuple(r[f] for f in schema["primary_key"])
                check.test("primary_keys_nonblank_unique", all(pk) and pk not in seen, f"{table}/{pk}")
                seen.add(pk)
                check.test("csv_row_shape", None not in r and None not in r.values(), f"{table}/{pk}")
                for f in money_fields:
                    if r[f] != "":
                        check.test("usd_exact_cent_format", bool(re.fullmatch(r"-?\d+\.\d{2}", r[f])), f"{table}/{pk}/{f}={r[f]}")
                for f in quantity_fields:
                    if r[f] != "":
                        check.test("quantity_milli_format", bool(re.fullmatch(r"-?\d+\.\d{3}", r[f])), f"{table}/{pk}/{f}={r[f]}")
                for f in minute_fields:
                    if r[f] != "":
                        check.test("physical_minutes_integer", bool(re.fullmatch(r"\d+", r[f])), f"{table}/{pk}/{f}")
                if "currency" in r:
                    check.test("all_monetary_currency_usd",r["currency"]=="USD",f"{table}/{pk}")
            self.tables[table] = records
        check.test("manifest_schema_file_set", set(manifest) == schema_files,
                   str(set(manifest) ^ schema_files))
        physical_files = {p.relative_to(self.root).as_posix() for p in (self.root/"sources").rglob("*.csv")}
        check.test("manifest_covers_all_source_csv", physical_files == schema_files, str(physical_files ^ schema_files))
        _, relationships = readcsv(self.root/"metadata/relationships.csv")
        for relation in relationships:
            table, column = relation["from_table"], relation["from_column"]
            target, target_column = relation["to_table"], relation["to_column"]
            allowed = set(self.idx(target, target_column))
            for r in self.rows(table):
                if r[column]:
                    check.test("declared_foreign_keys", r[column] in allowed, f"{table}.{column}={r[column]} -> {target}")
        vendors = set(self.idx("purchasing/suppliers")) | set(self.idx("operating/vendors"))
        _,vendor_mapping = readcsv(self.root/"metadata/vendor_master_mapping.csv")
        mapped = set()
        for r in vendor_mapping:
            ident = r["accounting_vendor_id"]
            check.test("vendor_master_mapping_id_unique",ident not in mapped,ident)
            mapped.add(ident)
            check.test("vendor_master_mapping_target_exists",r["master_table"] in self.tables and r["master_id"] in self.idx(r["master_table"]),ident)
            check.test("vendor_master_mapping_identity_type",ident==r["master_id"] and (r["vendor_type"],r["master_table"]) in {("parts_supplier","purchasing/suppliers"),("operating_vendor","operating/vendors")},ident)
        check.test("vendor_master_mapping_covers_all_vendor_masters",mapped==vendors,str(mapped^vendors))
        if (self.root/"metadata/vendor_relationships.csv").exists():
            _,vendor_relations = readcsv(self.root/"metadata/vendor_relationships.csv")
            declared_vendor_columns = set()
            for relation in vendor_relations:
                table,column = relation["from_table"],relation["from_column"]
                declared_vendor_columns.add((table,column))
                check.test("vendor_relationship_mapping_target",relation["to_table"]=="metadata/vendor_master_mapping.csv" and relation["to_column"]=="accounting_vendor_id",table)
                for r in self.rows(table):
                    check.test("vendor_relationship_foreign_keys_to_mapping",not r[column] or r[column] in mapped,f"{table}/{r[column]}")
            expected_columns = {(table,"vendor_id") for table,schema in self.schemas.items() if "vendor_id" in schema["fields"]}
            check.test("vendor_relationships_cover_vendor_columns",declared_vendor_columns==expected_columns,str(declared_vendor_columns^expected_columns))
        for table in self.tables:
            if "vendor_id" in self.schemas[table]["fields"]:
                for r in self.rows(table):
                    check.test("polymorphic_vendor_foreign_keys", not r["vendor_id"] or r["vendor_id"] in vendors, f"{table}/{r['vendor_id']}")
        for table in self.tables:
            check.test("all_logical_tables_nonempty", bool(self.tables[table]), table)
        for path in (self.root/"metadata").glob("*.csv"):
            check.test("metadata_csv_utf8_bom",path.read_bytes().startswith(b"\xef\xbb\xbf"),path.name)
        if (self.root/"metadata/source_catalog.csv").exists():
            _,catalog = readcsv(self.root/"metadata/source_catalog.csv")
            for r in catalog:
                check.test("source_catalog_custom_synthetic_not_native_api",r["extract_type"]=="custom_flat_synthetic_csv" and r["actual_cutoff"]==CUTOFF,r["source_system"])
                check.equal("source_catalog_row_totals",int(r["row_count"]),sum(len(rows) for table,rows in self.tables.items() if table.split("/")[0]==r["source_system"]),r["source_system"])
        print(f"Read {len(self.schemas)} logical tables, {sum(map(len, self.tables.values())):,} CSV rows", flush=True)

    def dates(self):
        # Explicit actual history fields. Contract/master/effective, due, expected,
        # scheduled, forecast, opening and approved-budget dates have other roles.
        actual_fields = {
            "shop/repair_orders": ["opened_date", "approved_date", "actual_completion_date", "actual_delivery_date", "actual_invoice_date"],
            "shop/jobs": ["opened_date", "actual_completion_date"], "shop/status_events": ["event_date"],
            "shop/estimates": ["estimate_date"], "shop/approvals": ["decision_date"],
            "schedule/appointments": ["booked_date", "actual_dropoff_at", "actual_pickup_at", "cancelled_date"],
            "schedule/technician_availability": ["work_date"], "schedule/job_segments": ["actual_start_at", "actual_end_at"],
            "schedule/bay_occupancy": ["actual_occupied_from", "actual_released_at", "occupied_through_snapshot_at"],
            "inventory/movements": ["movement_date"], "inventory/reservations": ["actual_issue_date"],
            "purchasing/purchase_orders": ["ordered_date", "actual_closed_date"], "purchasing/receipts": ["receipt_date"],
            "purchasing/supplier_returns": ["return_date"], "billing/invoices": ["invoice_date"],
            "billing/payments": ["payment_date"], "billing/payment_allocations": ["allocation_date"],
            "billing/deposits": ["received_date", "applied_date"], "billing/deposit_events": ["event_date"],
            "billing/credit_notes": ["credit_date"], "warranty/comebacks": ["reported_date"],
            "warranty/supplier_recoveries": ["recovery_date"], "processor/balance_transactions": ["transaction_date"],
            "processor/payouts": ["initiated_date", "actual_bank_date"], "payroll/attendance": ["work_date"],
            "payroll/runs": ["earned_date", "actual_funding_date"], "payroll/funding": ["actual_funding_date"],
            "operating/depreciation": ["depreciation_date"], "operating/sublet_services": ["actual_service_date"],
            "finance/debt_schedule": ["actual_payment_date"], "finance/tax_register": ["actual_remittance_date"],
            "finance/owner_distributions": ["distribution_date"],
            "marketing/daily_performance": ["performance_date"], "marketing/billing": ["bill_date"],
            "marketing/leads": ["lead_date"],
            "accounting/general_ledger": ["journal_date"], "accounting/bills": ["bill_date"],
            "accounting/vendor_credits": ["credit_date"], "accounting/ap_allocations": ["allocation_date"],
            "accounting/vendor_payments": ["payment_date"], "bank/statement": ["posted_date"],
        }
        for table, fields in actual_fields.items():
            for row in self.rows(table):
                for field in fields:
                    value = row[field]
                    if value:
                        self.checks.test("actual_dates_inside_history", START <= value[:10] <= CUTOFF, f"{table}/{field}={value}")
                        try:
                            datetime.fromisoformat(value)
                            valid = True
                        except ValueError:
                            valid = False
                        self.checks.test("actual_dates_parse", valid, f"{table}/{field}={value}")
        self.date_policy = {"actual_fields": actual_fields,
            "exceptions": "Master/employment/in-service/origination dates may predate history. Opening balances are 2024-10-31. Effective history dates may span cutoff. Due/expected/scheduled/contractual dates and forecast drivers may extend beyond cutoff; they are not actual events. Budget approval predates history."}

    def ledger(self):
        ch = self.checks
        journals, journal_headers = defaultdict(int), defaultdict(set)
        self.debits, self.credits = defaultdict(int), defaultdict(int)
        for r in self.rows("accounting/general_ledger"):
            debit, credit = c(r["debit_usd"]), c(r["credit_usd"])
            value = debit-credit
            ch.test("gl_positive_single_sided_lines", debit >= 0 and credit >= 0 and (debit == 0) != (credit == 0), r["journal_line_id"])
            journals[r["journal_id"]] += value
            event = r["source_type"], r["source_id"], r["location_id"]
            self.gl_event[event][r["account_code"]] += value
            self.gl_meta[event].add(r["journal_date"])
            journal_headers[r["journal_id"]].add((r["journal_date"],)+event)
            key = r["journal_date"][:7], r["location_id"], r["account_code"]
            self.activity[key] += value
            self.debits[key] += debit
            self.credits[key] += credit
            ch.test("no_gl_owner_equity_cash_plug", r["account_code"] != "3000", r["journal_line_id"])
        for journal, total in journals.items():
            ch.equal("journals_balance_exactly", total, 0, journal)
            ch.test("journal_header_consistent", len(journal_headers[journal]) == 1, journal)
        open_by_location = defaultdict(int)
        for r in self.rows("accounting/opening_trial_balance"):
            value = c(r["debit_usd"])-c(r["credit_usd"])
            ch.equal("opening_tb_line_arithmetic", c(r["signed_balance_usd"]), value, r["opening_id"])
            ch.test("opening_tb_date", r["as_of_date"] == "2024-10-31", r["opening_id"])
            self.opening[(r["location_id"],r["account_code"])] += value
            open_by_location[r["location_id"]] += value
        for loc, amount in open_by_location.items():
            ch.equal("opening_tb_balanced_by_location", amount, 0, loc)
        self.locations = sorted(self.idx("shop/locations"))
        balance = self.opening.copy()
        tb = {(r["month"],r["location_id"],r["account_code"]): r for r in self.rows("accounting/monthly_trial_balance")}
        for month in MONTHS:
            for loc in self.locations:
                for account in self.idx("accounting/chart_of_accounts"):
                    key = month, loc, account
                    row = tb.get(key)
                    ch.test("monthly_tb_complete", row is not None, key)
                    before = balance.get((loc,account), 0)
                    balance[(loc,account)] = before+self.activity[key]
                    self.closing[key] = balance[(loc,account)]
                    if row:
                        ch.equal("monthly_tb_opening", c(row["opening_signed_balance_usd"]), before, key)
                        ch.equal("monthly_tb_debits", c(row["period_debits_usd"]), self.debits[key], key)
                        ch.equal("monthly_tb_credits", c(row["period_credits_usd"]), self.credits[key], key)
                        ch.equal("monthly_tb_closing", c(row["closing_signed_balance_usd"]), balance[(loc,account)], key)
                ch.equal("monthly_tb_balanced_by_location", sum(v for (ll,_),v in balance.items() if ll==loc), 0, f"{month}/{loc}")
        print("Ledger and opening/monthly trial balances recomputed", flush=True)

    def shop(self):
        ch = self.checks
        ro = self.idx("shop/repair_orders")
        rates = self.idx("shop/labor_rate_history")
        jobs_by_ro = self.group("shop/jobs", "ro_id")
        lines_by_ro = self.group("shop/ro_lines", "ro_id")
        estimates = self.idx("shop/estimates")
        elines = self.group("shop/estimate_lines", "estimate_id")
        approvals = self.group("shop/approvals", "estimate_id")
        est_by_ro = self.group("shop/estimates", "ro_id")
        quote_counts = Counter()
        for table in ["shop/ro_lines", "shop/estimate_lines", "billing/invoice_lines"]:
            for r in self.rows(table):
                ident = r[self.schemas[table]["primary_key"][0]]
                gross = rounded(Decimal(r["quantity"])*c(r["unit_price_usd"]))
                ch.equal("document_line_quantity_times_price", c(r["gross_usd"]), gross, f"{table}/{ident}")
                ch.equal("document_line_net", c(r["net_usd"]), c(r["gross_usd"])-c(r["discount_usd"]), f"{table}/{ident}")
                ch.equal("document_line_total", c(r["total_usd"]), c(r["net_usd"])+c(r["tax_usd"]), f"{table}/{ident}")
                tax = rounded(Decimal(c(r["net_usd"]))*Decimal("0.065")) if r["line_type"]=="parts" else 0
                ch.equal("parts_tax_per_line_rounding", c(r["tax_usd"]), tax, f"{table}/{ident}")
        for r in self.rows("shop/estimate_lines"):
            if r["ro_line_id"]:
                quote_counts[r["ro_line_id"]] += 1
                origin = self.idx("shop/ro_lines")[r["ro_line_id"]]
                for field in ["quantity", "unit_price_usd", "gross_usd", "discount_usd", "net_usd", "tax_usd", "total_usd"]:
                    ch.test("approved_quote_equals_ro_line", r[field] == origin[field], f"{r['estimate_line_id']}/{field}")
        for r in self.rows("shop/estimates"):
            for field, header in [("net_usd","quoted_net_usd"),("tax_usd","quoted_tax_usd"),("total_usd","quoted_total_usd")]:
                ch.equal("estimate_header_sums_lines", c(r[header]), sum(c(a[field]) for a in elines[r["estimate_id"]]), r["estimate_id"])
            decisions = approvals[r["estimate_id"]]
            ch.test("estimate_has_one_decision", len(decisions)==1, r["estimate_id"])
            for a in decisions:
                approved = a["decision"] == "approved"
                ch.test("estimate_decision_matches_status", a["decision"]==r["status"], a["approval_id"])
                ch.equal("approval_amount", c(a["approved_total_usd"]), c(r["quoted_total_usd"]) if approved else 0, a["approval_id"])
                ch.test("approval_date_order", not approved or r["estimate_date"] <= a["decision_date"] <= ro[r["ro_id"]]["opened_date"], a["approval_id"])
            if r["estimate_type"] == "change_order_delta":
                parent = estimates[r["parent_estimate_id"]]
                ch.test("change_order_parent_same_ro", parent["ro_id"]==r["ro_id"] and parent["estimate_type"]=="initial", r["estimate_id"])
        events_by_ro = self.group("shop/status_events","ro_id")
        for rid, r in ro.items():
            for field, header in [("net_usd","approved_net_usd"),("tax_usd","approved_tax_usd"),("total_usd","approved_total_usd")]:
                ch.equal("ro_header_sums_lines", c(r[header]), sum(c(a[field]) for a in lines_by_ro[rid]), rid)
            ch.equal("ro_approved_versions_sum", sum(c(e["quoted_total_usd"]) for e in est_by_ro[rid] if e["status"]=="approved"), c(r["approved_total_usd"]), rid)
            for line in lines_by_ro[rid]:
                ch.equal("ro_line_approved_exactly_once", quote_counts[line["ro_line_id"]], 1, line["ro_line_id"])
                if line["line_type"] == "labor":
                    rate = rates[line["labor_rate_id"]]
                    ch.test("labor_rate_effective_version", rate["location_id"]==r["location_id"] and rate["effective_from"]<=r["opened_date"] and (not rate["effective_to"] or r["opened_date"]<=rate["effective_to"]), rid)
                    expected_rate = c(rate["retail_hourly_rate_usd"])
                    if r["fleet_account_id"]:
                        fleet = self.idx("shop/fleet_accounts")[r["fleet_account_id"]]
                        expected_rate = rounded(Decimal(expected_rate)*(1-Decimal(fleet["labor_discount_pct"])/100))
                    ch.equal("labor_effective_contract_price", c(line["unit_price_usd"]), expected_rate, rid)
            completed, delivered = r["actual_completion_date"], r["actual_delivery_date"]
            ch.test("ro_chronology", r["approved_date"] <= r["opened_date"] and (not completed or r["opened_date"] <= completed) and (not delivered or bool(completed) and completed<=delivered), rid)
            warranty = r["is_warranty"] == "True"
            has_invoice = bool(delivered) and not warranty
            ch.test("delivery_recognition_invoice_presence", bool(r["invoice_id"]) == has_invoice and bool(r["actual_invoice_date"])==has_invoice, rid)
            ch.test("delivery_invoice_dates_equal", not has_invoice or r["actual_invoice_date"] == delivered, rid)
            if warranty:
                ch.equal("free_warranty_no_customer_revenue", c(r["approved_total_usd"]), 0, rid)
                ch.test("warranty_original_completed_before_return", r["original_ro_id"] in ro and bool(ro[r["original_ro_id"]]["actual_delivery_date"]) and ro[r["original_ro_id"]]["actual_delivery_date"] < r["opened_date"], rid)
            expected_status = {("opened",r["opened_date"]),("approved",r["approved_date"])}
            if r["status"]=="awaiting_parts": expected_status.add(("awaiting_parts",r["opened_date"]))
            else: expected_status.add(("work_started",r["opened_date"]))
            if completed: expected_status.add(("completed",completed))
            if delivered: expected_status.add(("delivered",delivered))
            if has_invoice: expected_status.add(("invoiced",delivered))
            actual_status = [(e["status"],e["event_date"]) for e in events_by_ro[rid]]
            ch.test("ro_status_event_completeness", set(actual_status)==expected_status and len(actual_status)==len(expected_status), rid)
            ch.test("ro_vehicle_customer", self.idx("shop/vehicles")[r["vehicle_id"]]["customer_id"]==r["customer_id"], rid)
        self.ro_lines = lines_by_ro
        self.jobs_by_ro = jobs_by_ro

    def scheduling(self):
        ch = self.checks
        availability = {(r["employee_id"],r["work_date"]):r for r in self.rows("schedule/technician_availability")}
        attend = self.idx("payroll/attendance")
        employees = self.idx("payroll/employees")
        daily, job_minutes, ro_minutes = defaultdict(int), defaultdict(int), defaultdict(int)
        by_employee, by_bay = defaultdict(list), defaultdict(list)
        self.period_clock, self.period_ro_clock = defaultdict(int), defaultdict(int)
        for r in self.rows("schedule/job_segments"):
            start, end = r["actual_start_at"], r["actual_end_at"]
            if not start or not end:
                ch.test("future_segments_have_no_actual_clock", not start and not end and int(r["approved_clock_minutes"])==0, r["segment_id"])
                continue
            duration = mins(start,end)
            ch.equal("segment_duration_equals_clock", int(r["approved_clock_minutes"]), duration, r["segment_id"])
            ch.test("segment_positive_same_day", duration>0 and start[:10]==end[:10]==r["work_date"], r["segment_id"])
            av = availability.get((r["employee_id"], r["work_date"]))
            ch.test("segment_has_paid_availability", av is not None, r["segment_id"])
            if av:
                ch.test("segment_within_shift", bool(av["shift_start"]) and av["shift_start"]<=start<end<=av["shift_end"], r["segment_id"])
                ch.test("segment_excludes_unpaid_lunch", not av["lunch_start"] or end<=av["lunch_start"] or start>=av["lunch_end"], r["segment_id"])
                ch.test("segment_availability_identity", r["attendance_id"]==av["attendance_id"] and r["bay_id"]==av["bay_id"] and r["location_id"]==av["location_id"], r["segment_id"])
            a = attend[r["attendance_id"]]
            ch.test("segment_attendance_identity", a["employee_id"]==r["employee_id"] and a["work_date"]==r["work_date"] and a["approval_status"]=="approved", r["segment_id"])
            daily[(r["employee_id"],r["work_date"])] += duration
            job_minutes[r["job_id"]] += duration
            ro_minutes[r["ro_id"]] += duration
            key = halfkey(r["employee_id"],r["work_date"])
            self.period_clock[key] += duration
            self.period_ro_clock[key+(r["ro_id"],)] += duration
            by_employee[r["employee_id"]].append((start,end,r["segment_id"]))
            by_bay[r["bay_id"]].append((start,end,r["segment_id"]))
        for name, groups in [("technician_actual_segments_no_overlap",by_employee),("bay_actual_segments_no_overlap",by_bay)]:
            for ident, intervals in groups.items():
                previous_end = ""
                for start,end,sid in sorted(intervals):
                    ch.test(name, start>=previous_end, f"{ident}/{sid}/{start} previous_end={previous_end}")
                    previous_end = max(previous_end,end)
        for key, av in availability.items():
            physical = 0
            if av["shift_start"] and av["shift_end"]:
                physical = mins(av["shift_start"],av["shift_end"])
                if av["lunch_start"]: physical-=mins(av["lunch_start"],av["lunch_end"])
            ch.equal("availability_interval_minutes", int(av["available_minutes"]), physical, str(key))
            ch.test("clock_not_more_than_physical_availability", 0<=daily[key]<=physical, f"{key}: clock={daily[key]}, available={physical}")
            a = attend[av["attendance_id"]]
            ch.equal("availability_equals_paid_presence", int(av["available_minutes"]), int(a["paid_presence_minutes"]), str(key))
            ch.equal("availability_paid_minutes", int(av["paid_attendance_minutes"]), int(a["approved_paid_minutes"]), str(key))
            ch.test("technician_employed_on_work_date", employees[key[0]]["hire_date"]<=key[1] and (not employees[key[0]]["termination_date"] or key[1]<=employees[key[0]]["termination_date"]), str(key))
        for r in self.rows("schedule/daily_capacity"):
            key = r["employee_id"],r["work_date"]
            ch.equal("capacity_actual_clock", int(r["actual_work_minutes"]), daily[key], str(key))
            ch.equal("capacity_available_minutes", int(r["technician_available_minutes"]), int(availability[key]["available_minutes"]), str(key))
            ch.equal("capacity_work_plus_idle", int(r["actual_work_minutes"])+int(r["idle_technician_minutes"]), int(r["technician_available_minutes"]), str(key))
            ch.test("capacity_nonnegative_idle_and_bay", int(r["idle_technician_minutes"])>=0 and int(r["bay_open_minutes"])>=int(r["actual_work_minutes"]), str(key))
        for r in self.rows("shop/jobs"):
            ch.equal("job_clock_sums_actual_segments", int(r["approved_actual_minutes"]), job_minutes[r["job_id"]], r["job_id"])
            # Flat-rate book hours intentionally have no <= physical-time rule.
        occupancy_by_bay = defaultdict(list)
        occupancy_by_ro = self.group("schedule/bay_occupancy","ro_id")
        for r in self.rows("schedule/bay_occupancy"):
            end = r["actual_released_at"] or r["occupied_through_snapshot_at"]
            ch.test("bay_occupancy_positive", bool(end) and r["actual_occupied_from"]<end, r["occupancy_id"])
            occupancy_by_bay[r["bay_id"]].append((r["actual_occupied_from"],end,r["occupancy_id"]))
        for bay, intervals in occupancy_by_bay.items():
            previous = ""
            for start,end,oid in sorted(intervals):
                ch.test("continuous_bay_occupancy_no_overlap", start>=previous, f"{bay}/{oid}")
                previous = max(previous,end)
        for r in self.rows("schedule/job_segments"):
            if r["actual_start_at"]:
                ch.test("segment_inside_ro_bay_occupancy", any(o["bay_id"]==r["bay_id"] and o["actual_occupied_from"]<=r["actual_start_at"] and (o["actual_released_at"] or o["occupied_through_snapshot_at"])>=r["actual_end_at"] for o in occupancy_by_ro[r["ro_id"]]), r["segment_id"])
        self.daily_clock, self.ro_clock = daily, ro_minutes

    def vehicles_bays_and_parts_bridge(self):
        ch = self.checks
        ros, vehicles = self.idx("shop/repair_orders"),self.idx("shop/vehicles")
        segments = self.group("schedule/job_segments","ro_id")
        visits = defaultdict(list)
        for r in self.rows("schedule/appointments"):
            if not r["ro_id"]: continue
            ro = ros[r["ro_id"]]
            ch.test("appointment_ro_vehicle_customer_location",r["vehicle_id"]==ro["vehicle_id"] and r["customer_id"]==ro["customer_id"] and r["location_id"]==ro["location_id"],r["appointment_id"])
            actual = [s for s in segments[r["ro_id"]] if s["actual_start_at"]]
            if actual:
                ch.test("dropoff_before_actual_work",bool(r["actual_dropoff_at"]) and r["actual_dropoff_at"]<=min(s["actual_start_at"] for s in actual),r["appointment_id"])
                if r["actual_pickup_at"]:
                    ch.test("pickup_after_last_actual_work",r["actual_pickup_at"]>=max(s["actual_end_at"] for s in actual),r["appointment_id"])
            if r["actual_dropoff_at"]:
                visits[r["vehicle_id"]].append((r["actual_dropoff_at"],r["actual_pickup_at"] or "2026-11-01T00:00:00",ro))
            else:
                ch.test("not_dropped_off_has_no_actual_odometer",ro["odometer_miles"]=="",ro["ro_id"])
        for vid,rows in visits.items():
            previous_end, previous_odo = "",int(vehicles[vid]["opening_odometer_miles"])
            for start,end,ro in sorted(rows,key=lambda x:x[0]):
                ch.test("vehicle_actual_stays_do_not_overlap",start>=previous_end,f"{vid}/{ro['ro_id']}: start={start}, previous_end={previous_end}")
                ch.test("vehicle_odometer_monotonic",bool(ro["odometer_miles"]) and int(ro["odometer_miles"])>=previous_odo,f"{vid}/{ro['ro_id']}")
                previous_end = max(previous_end,end)
                if ro["odometer_miles"]: previous_odo = int(ro["odometer_miles"])
        if "schedule/bay_calendar" in self.tables:
            productive = defaultdict(int)
            for r in self.rows("schedule/job_segments"):
                if r["actual_start_at"]: productive[(r["bay_id"],r["work_date"])]+=int(r["approved_clock_minutes"])
            occupancy = self.group("schedule/bay_occupancy","bay_id")
            calendar_keys = set()
            for r in self.rows("schedule/bay_calendar"):
                day = date.fromisoformat(r["work_date"])
                key = r["bay_id"],r["work_date"]
                ch.test("bay_calendar_grain_unique",key not in calendar_keys,str(key))
                calendar_keys.add(key)
                windows = []
                if day.weekday()<5:
                    windows=[(f"{day}T08:00:00",f"{day}T12:00:00"),(f"{day}T13:00:00",f"{day}T{'18' if day.weekday()==3 and day.day%2==0 else '17'}:00:00")]
                elif day.weekday()==5 and 8<=day.day<=14:
                    windows=[(f"{day}T08:00:00",f"{day}T12:00:00")]
                expected = sum(mins(st,en) for st,en in windows)
                occupied = 0
                for o in occupancy[r["bay_id"]]:
                    begin,end = o["actual_occupied_from"],o["actual_released_at"] or "2026-11-01T00:00:00"
                    if begin[:10]>r["work_date"] or end[:10]<r["work_date"]: continue
                    for st,en in windows:
                        lo,hi = max(begin,st),min(end,en)
                        if lo<hi: occupied+=mins(lo,hi)
                ch.equal("bay_calendar_open_minutes_policy",int(r["bay_open_minutes"]),expected,str(key))
                ch.equal("bay_calendar_productive_actual",int(r["actual_productive_minutes"]),productive[key],str(key))
                ch.equal("bay_calendar_occupied_open_minutes",int(r["occupied_open_minutes"]),occupied,str(key))
                ch.equal("bay_calendar_idle_plus_occupied",int(r["idle_open_minutes"])+occupied,expected,str(key))
                ch.test("bay_calendar_productive_occupied_capacity",0<=productive[key]<=occupied<=expected,str(key))
            day_count = (date.fromisoformat(CUTOFF)-date.fromisoformat(START)).days+1
            ch.equal("bay_calendar_all_physical_bays_all_dates",len(calendar_keys),len(self.rows("shop/bays"))*day_count,"physical bays calendar")
            for bay in self.idx("shop/bays"):
                day = date.fromisoformat(START)
                while str(day)<=CUTOFF:
                    ch.test("bay_calendar_individual_dates_complete",(bay,str(day)) in calendar_keys,f"{bay}/{day}")
                    day+=timedelta(days=1)
        if "inventory/ro_parts_usage" in self.tables:
            keys = set()
            movements = self.idx("inventory/movements")
            for r in self.rows("inventory/ro_parts_usage"):
                ro = ros[r["ro_id"]]
                key = r["ro_id"],r["sku"]
                ch.test("parts_usage_ro_sku_unique",key not in keys,str(key))
                keys.add(key)
                required,issued,installed,pending = [q(r[f]) for f in ["required_base_quantity","issued_base_quantity","installed_base_quantity","reserved_not_issued_quantity"]]
                ch.test("parts_usage_physical_rollforward",required==issued+pending and 0<=installed<=issued,str(key))
                ch.equal("parts_usage_issued_matches_movement_quantity",issued,self.issue_by_sku[key],str(key))
                if r["issue_movement_id"]:
                    mv = movements[r["issue_movement_id"]]
                    ch.equal("parts_usage_cost_matches_issue",c(r["issued_carrying_cost_usd"]),-c(mv["carrying_value_delta_usd"]),str(key))
                    ch.test("parts_usage_dates_movement_install_release",r["actual_issue_date"]==mv["movement_date"] and r["actual_install_date"]==ro["actual_completion_date"] and r["actual_wip_release_date"]==ro["actual_delivery_date"],str(key))
                    ch.equal("parts_usage_installed_only_after_completion",installed,issued if ro["actual_completion_date"] else 0,str(key))
                else:
                    ch.test("parts_usage_pending_no_actual_cost",not r["actual_issue_date"] and not r["actual_install_date"] and not r["actual_wip_release_date"] and c(r["issued_carrying_cost_usd"])==0 and issued==installed==0,str(key))
            expected = {(r["ro_id"],r["sku"]) for r in self.rows("shop/ro_lines") if r["line_type"]=="parts"}
            ch.test("parts_usage_covers_every_approved_ro_sku",keys==expected,str(keys^expected)[:500])

    def inventory(self):
        ch = self.checks
        ros = self.idx("shop/repair_orders")
        stock = defaultdict(lambda: [0,0])
        lots = defaultdict(list)
        for r in self.rows("inventory/opening_stock"):
            key = r["location_id"],r["sku"]
            stock[key][0] += q(r["base_quantity"])
            stock[key][1] += c(r["carrying_value_usd"])
            lots[key].append([r["lot_id"],q(r["base_quantity"]),c(r["carrying_value_usd"])])
            ch.equal("opening_stock_cost_arithmetic", c(r["carrying_value_usd"]), rounded(Decimal(r["base_quantity"])*c(r["unit_cost_usd"])), r["opening_stock_id"])
        for loc in self.locations:
            ch.equal("opening_inventory_to_gl1200", sum(v[1] for (ll,_),v in stock.items() if ll==loc), self.opening.get((loc,"1200"),0), loc)
        movements = sorted(self.rows("inventory/movements"), key=lambda r: (r["movement_date"],int(r["event_sequence"])))
        ch.test("inventory_event_sequence_unique", len({r["event_sequence"] for r in movements})==len(movements), "movement event_sequence")
        month_stock = {(r["month"],r["location_id"],r["sku"]): r for r in self.rows("inventory/month_end_balances")}
        self.issue_cost, self.issue_by_sku = defaultdict(int), defaultdict(int)
        self.issue_events = defaultdict(list)
        movement_by_source = defaultdict(list)
        ix = 0
        for month in MONTHS:
            while ix<len(movements) and movements[ix]["movement_date"]<=ENDS[month]:
                r = movements[ix]
                key = r["location_id"],r["sku"]
                quantity, value = q(r["quantity_delta"]), c(r["carrying_value_delta_usd"])
                movement_by_source[r["source_id"]].append(r)
                stock[key][0] += quantity
                stock[key][1] += value
                ch.test("inventory_nonnegative_after_every_movement", stock[key][0]>=0 and stock[key][1]>=0, f"{r['movement_id']}: {stock[key]}")
                ch.test("inventory_quantity_value_direction", quantity*value>=0 and (quantity!=0 or value==0), r["movement_id"])
                if quantity>0:
                    lots[key].append([r["lot_id"],quantity,value])
                elif quantity<0:
                    remaining, cost = -quantity,0
                    for lot in lots[key]:
                        if r["movement_type"]=="supplier_return" and lot[0]!=r["lot_id"]:
                            continue
                        take = min(remaining,lot[1])
                        if take<=0: continue
                        carrying = lot[2] if take==lot[1] else rounded(Decimal(lot[2])*take/lot[1])
                        lot[1]-=take
                        lot[2]-=carrying
                        remaining-=take
                        cost+=carrying
                        if remaining==0: break
                    ch.test("fifo_lots_sufficient", remaining==0, r["movement_id"])
                    ch.equal("fifo_issue_return_transfer_writeoff_valuation", -value, cost, r["movement_id"])
                if r["movement_type"]=="issue_to_wip":
                    self.issue_cost[r["ro_id"]] -= value
                    self.issue_by_sku[(r["ro_id"],r["sku"])] -= quantity
                    self.issue_events[r["ro_id"]].append(r)
                ix+=1
            for (loc,sku), (quantity,value) in stock.items():
                row = month_stock.get((month,loc,sku))
                ch.test("inventory_monthend_rows_complete", row is not None, f"{month}/{loc}/{sku}")
                if row:
                    ch.equal("inventory_monthend_quantity_milli", q(row["base_quantity"]), quantity, f"{month}/{loc}/{sku}")
                    ch.equal("inventory_monthend_value", c(row["carrying_value_usd"]), value, f"{month}/{loc}/{sku}")
            for loc in self.locations:
                balance = sum(v[1] for (ll,_),v in stock.items() if ll==loc)
                ch.equal("inventory_monthend_source_to_gl1200", balance, self.closing[(month,loc,"1200")], f"{month}/{loc}")
                self.controls[(month,loc)]["inventory_source_usd"] = balance
        sublets = self.group("operating/sublet_services","ro_id")
        self.sublet_cost = {rid:sum(c(s["cost_usd"]) for s in rows) for rid,rows in sublets.items()}
        wip_rows = {(r["month"],r["ro_id"]):r for r in self.rows("inventory/wip_balances")}
        expected_wip_keys = set()
        for rid, ro in ros.items():
            for part in self.ro_lines[rid]:
                if part["line_type"]=="parts":
                    expected_quantity = 0 if ro["status"]=="awaiting_parts" else q(part["quantity"])
                    ch.equal("parts_issued_equal_ro_physical_quantity", self.issue_by_sku[(rid,part["sku"])], expected_quantity, f"{rid}/{part['sku']}")
            issue = self.issue_events[rid]
            ch.test("parts_issues_follow_actual_work_status", bool(issue)==(ro["status"]!="awaiting_parts"), rid)
            if issue:
                day = min(r["movement_date"] for r in issue)
                cost = self.issue_cost[rid]
                self.expect("parts_issue_source_to_gl", "ro_parts_issue", rid, day, ro["location_id"], [("1210",cost),("1200",-cost)])
            if ro["actual_delivery_date"]:
                pc, sc = self.issue_cost[rid], self.sublet_cost.get(rid,0)
                self.expect("delivered_cogs_source_to_gl", "delivered_ro_cost", rid, ro["actual_delivery_date"], ro["location_id"], [("5110" if ro["is_warranty"]=="True" else "5100",pc),("5200",sc),("1210",-pc-sc)])
            for month in MONTHS:
                end = ENDS[month]
                if ro["opened_date"]<=end and (not ro["actual_delivery_date"] or ro["actual_delivery_date"]>end):
                    key = month,rid
                    expected_wip_keys.add(key)
                    pc = sum(-c(i["carrying_value_delta_usd"]) for i in issue if i["movement_date"]<=end)
                    sc = sum(c(s["cost_usd"]) for s in sublets[rid] if s["actual_service_date"]<=end)
                    row = wip_rows.get(key)
                    ch.test("wip_open_ro_row_complete", row is not None, key)
                    if row:
                        ch.equal("wip_parts_cost", c(row["issued_parts_value_usd"]), pc, str(key))
                        ch.equal("wip_sublet_cost", c(row["outsourced_service_value_usd"]), sc, str(key))
                        ch.equal("wip_no_capitalized_labor", c(row["labor_capitalized_usd"]), 0, str(key))
                        ch.equal("wip_total_parts_plus_sublet", c(row["total_wip_usd"]), pc+sc, str(key))
        ch.test("wip_only_undelivered_ro_rows", set(wip_rows)==expected_wip_keys, str(set(wip_rows)^expected_wip_keys)[:500])
        wip_monthly = defaultdict(int)
        for r in self.rows("inventory/wip_balances"):
            wip_monthly[(r["month"],r["location_id"])] += c(r["total_wip_usd"])
        for month in MONTHS:
            for loc in self.locations:
                source = wip_monthly[(month,loc)]
                ch.equal("wip_monthend_source_to_gl1210", source, self.closing[(month,loc,"1210")], f"{month}/{loc}")
                self.controls[(month,loc)]["wip_source_usd"] = source
        for r in self.rows("inventory/reservations"):
            reserved, issued, released, residual = map(q,[r["reserved_base_quantity"],r["issued_base_quantity"],r["released_base_quantity"],r["open_reserved_base_quantity"]])
            ch.test("reservation_quantity_rollforward", reserved==issued+released+residual and min(issued,released,residual)>=0, r["reservation_id"])
            ch.test("open_reservation_no_actual_issue", residual==0 or not r["actual_issue_date"], r["reservation_id"])
        moves = self.idx("inventory/movements")
        for r in self.rows("inventory/transfers"):
            out, inc = moves[r["out_movement_id"]], moves[r["in_movement_id"]]
            ch.equal("transfer_quantity_zero_company", q(out["quantity_delta"])+q(inc["quantity_delta"]), 0, r["transfer_id"])
            ch.equal("transfer_value_zero_company", c(out["carrying_value_delta_usd"])+c(inc["carrying_value_delta_usd"]), 0, r["transfer_id"])
            ch.test("transfer_pair_identity", out["paired_movement_id"]==inc["movement_id"] and inc["paired_movement_id"]==out["movement_id"] and out["location_id"]==r["from_location_id"] and inc["location_id"]==r["to_location_id"], r["transfer_id"])
            value = c(r["carrying_value_usd"])
            self.expect("transfer_source_to_gl", "transfer_out", r["transfer_id"], r["transfer_date"], r["from_location_id"], [("1300",value),("1200",-value)])
            self.expect("transfer_source_to_gl", "transfer_in", r["transfer_id"], r["transfer_date"], r["to_location_id"], [("1200",value),("1300",-value)])
        for month in MONTHS:
            ch.equal("intershop_gl1300_company_zero", sum(self.closing[(month,l,"1300")] for l in self.locations),0,month)
        for r in self.rows("inventory/cycle_counts"):
            mv = moves[r["movement_id"]]
            ch.equal("count_quantity_arithmetic", q(r["counted_usable_quantity"])-q(r["book_quantity_before"]), q(r["adjustment_quantity"]), r["count_id"])
            ch.equal("count_adjustment_matches_movement", q(mv["quantity_delta"]), q(r["adjustment_quantity"]), r["count_id"])
            ch.equal("count_writeoff_matches_movement", -c(mv["carrying_value_delta_usd"]), c(r["writeoff_value_usd"]), r["count_id"])
            value = c(r["writeoff_value_usd"])
            self.expect("count_source_to_gl", "inventory_writeoff", r["count_id"], r["count_date"], r["location_id"], [("5130",value),("1200",-value)])
        self.movements_by_source = movement_by_source
        self.cutoff_inventory_quantities = {key: value[0] for key,value in stock.items()}
        print("FIFO inventory, WIP, physical transfers and delivered COGS recomputed", flush=True)

    def purchasing(self):
        ch = self.checks
        pos, prices, terms = self.idx("purchasing/purchase_orders"), self.idx("purchasing/purchase_price_history"), self.idx("purchasing/terms_history")
        receipts = self.group("purchasing/receipts","po_line_id")
        po_lines = self.group("purchasing/po_lines","po_id")
        bills = self.idx("accounting/bills")
        credits = self.idx("accounting/vendor_credits")
        for r in self.rows("purchasing/po_lines"):
            po, price = pos[r["po_id"]], prices[r["price_id"]]
            ch.equal("po_pack_conversion_milli", q(r["ordered_base_quantity"]), rounded(Decimal(r["purchase_quantity"])*Decimal(r["base_units_per_purchase_unit"])*1000), r["po_line_id"])
            ch.equal("po_unit_conversion_cost", c(r["purchase_unit_cost_usd"]), rounded(Decimal(r["base_units_per_purchase_unit"])*c(r["base_unit_cost_usd"])), r["po_line_id"])
            ch.equal("po_line_price_quantity", c(r["line_total_usd"]), rounded(Decimal(r["ordered_base_quantity"])*c(r["base_unit_cost_usd"])), r["po_line_id"])
            ch.equal("po_ordered_received_open_quantity", q(r["ordered_base_quantity"]), q(r["received_base_quantity"])+q(r["open_base_quantity"]), r["po_line_id"])
            ch.equal("po_receipt_quantity", q(r["received_base_quantity"]), sum(q(a["received_base_quantity"]) for a in receipts[r["po_line_id"]]), r["po_line_id"])
            ch.test("po_effective_price_version", price["sku"]==r["sku"] and price["supplier_id"]==po["supplier_id"] and price["effective_from"]<=po["ordered_date"] and (not price["effective_to"] or po["ordered_date"]<=price["effective_to"]), r["po_line_id"])
            ch.equal("po_contract_base_price", c(r["base_unit_cost_usd"]), c(price["base_unit_price_usd"]), r["po_line_id"])
        for pid, r in pos.items():
            t = terms[r["terms_id"]]
            ch.test("po_effective_terms_version", t["supplier_id"]==r["supplier_id"] and t["effective_from"]<=r["ordered_date"] and (not t["effective_to"] or r["ordered_date"]<=t["effective_to"]), pid)
            ch.equal("po_header_sum_lines", c(r["total_ordered_usd"]), sum(c(a["line_total_usd"]) for a in po_lines[pid]), pid)
            residual = sum(rounded(Decimal(a["open_base_quantity"])*c(a["base_unit_cost_usd"])) for a in po_lines[pid])
            ch.equal("po_open_commitment", c(r["open_commitment_usd"]), residual, pid)
            if residual:
                ch.test("unreceived_po_no_actual_bill", not r["actual_closed_date"] and not any(b["po_id"]==pid for b in bills.values()), pid)
        for r in self.rows("purchasing/receipts"):
            mv = self.movements_by_source[r["receipt_id"]]
            ch.equal("receipt_exactly_one_stock_movement", len(mv),1,r["receipt_id"])
            ch.equal("receipt_stock_value", sum(c(m["carrying_value_delta_usd"]) for m in mv), c(r["landed_value_usd"]),r["receipt_id"])
            ch.equal("receipt_stock_quantity_milli", sum(q(m["quantity_delta"]) for m in mv),q(r["received_base_quantity"]),r["receipt_id"])
            b = bills[r["bill_id"]]
            ch.test("receipt_bill_identity_dates", b["source_id"]==r["receipt_id"] and b["bill_date"]==r["receipt_date"] and b["po_id"]==r["po_id"] and b["location_id"]==r["location_id"],r["receipt_id"])
            ch.equal("receipt_bill_value", c(b["total_usd"]),c(r["landed_value_usd"]),r["receipt_id"])
        for r in self.rows("purchasing/supplier_returns"):
            credit = credits[r["vendor_credit_id"]]
            original = self.idx("purchasing/receipts")[r["original_receipt_id"]]
            ch.test("supplier_return_original_lot_and_bill", original["bill_id"]==r["original_bill_id"] and original["receipt_date"]<=r["return_date"] and original["sku"]==r["sku"],r["supplier_return_id"])
            ch.equal("supplier_return_credit_original_cost",c(credit["amount_usd"]),c(r["original_cost_usd"]),r["supplier_return_id"])
            mv = self.movements_by_source[r["supplier_return_id"]]
            ch.equal("supplier_return_stock_value", -sum(c(m["carrying_value_delta_usd"]) for m in mv), c(r["original_cost_usd"]),r["supplier_return_id"])
            ch.equal("supplier_return_stock_quantity_milli",-sum(q(m["quantity_delta"]) for m in mv),q(r["returned_base_quantity"]),r["supplier_return_id"])
        statement_items = self.group("purchasing/statement_items","statement_id")
        references = Counter()
        for r in self.rows("purchasing/statement_items"):
            if r["document_type"]=="bill":
                b = bills[r["bill_id"]]
                amount, day, ref = c(b["total_usd"]),b["bill_date"],r["bill_id"]
            else:
                b = credits[r["vendor_credit_id"]]
                amount, day, ref = -c(b["amount_usd"]),b["credit_date"],r["vendor_credit_id"]
            references[ref]+=1
            ch.equal("statement_item_matches_existing_document",c(r["signed_document_usd"]),amount,r["statement_item_id"])
            ch.test("statement_item_document_date",r["document_date"]==day,r["statement_item_id"])
        for r in self.rows("purchasing/supplier_statements"):
            ch.equal("supplier_statement_sum_documents",c(r["net_documents_usd"]),sum(c(a["signed_document_usd"]) for a in statement_items[r["statement_id"]]),r["statement_id"])
            ch.test("supplier_statement_summary_only",r["is_summary_only"]=="True",r["statement_id"])
            ch.test("supplier_statement_no_gl_doublepost",not any(k[1]==r["statement_id"] for k in self.gl_event),r["statement_id"])
        for ident,count in references.items():
            ch.equal("supplier_document_in_statement_once",count,1,ident)
        for r in self.rows("purchasing/payment_schedule"):
            if r["bill_id"]:
                expected = c(bills[r["bill_id"]]["open_amount_usd"])
                ch.test("supplier_schedule_received_is_ap",r["commitment_type"]=="open_AP_received_stock",r["schedule_id"])
            else:
                expected = c(pos[r["po_id"]]["open_commitment_usd"])
                ch.test("supplier_schedule_unreceived_is_not_ap",r["commitment_type"]=="unreceived_PO_not_AP",r["schedule_id"])
            ch.equal("supplier_schedule_residual",c(r["residual_amount_usd"]),expected,r["schedule_id"])

    def billing(self):
        ch = self.checks
        ros = self.idx("shop/repair_orders")
        invoices = self.idx("billing/invoices")
        invoice_lines = self.group("billing/invoice_lines","invoice_id")
        credits = self.group("billing/credit_notes","invoice_id")
        allocations = self.group("billing/payment_allocations","invoice_id")
        invoice_ro_lines = Counter(r["ro_line_id"] for r in self.rows("billing/invoice_lines"))
        open_ar = self.idx("billing/open_ar")
        source_fields = ["line_type","sku","quantity","unit","unit_price_usd","gross_usd","discount_usd","net_usd","tax_usd","total_usd"]
        ar_monthly, sales_monthly = defaultdict(int), defaultdict(int)
        self.tax_collected = defaultdict(int)
        for r in self.rows("billing/invoice_lines"):
            origin = self.idx("shop/ro_lines")[r["ro_line_id"]]
            ch.test("invoice_line_preserves_original_ro", all(r[f]==origin[f] for f in source_fields),r["invoice_line_id"])
        for inv, r in invoices.items():
            ro = ros[r["ro_id"]]
            ch.test("invoice_only_delivered_customer_ro",ro["is_warranty"]=="False" and r["invoice_date"]==ro["actual_delivery_date"] and ro["invoice_id"]==inv,r["invoice_id"])
            ch.test("invoice_customer_location_identity", r["customer_id"]==ro["customer_id"] and r["location_id"]==ro["location_id"],inv)
            for field in ["net_usd","tax_usd","total_usd"]:
                ch.equal("invoice_header_sums_lines",c(r[field]),sum(c(a[field]) for a in invoice_lines[inv]),f"{inv}/{field}")
            for line in self.ro_lines[r["ro_id"]]:
                ch.equal("delivered_ro_line_invoiced_once",invoice_ro_lines[line["ro_line_id"]],1,line["ro_line_id"])
            total_credit = sum(c(a["total_usd"]) for a in credits[inv])
            total_alloc = sum(c(a["amount_usd"]) for a in allocations[inv])
            residual = c(r["total_usd"])-total_credit-total_alloc
            ch.equal("invoice_credit_header",c(r["credit_total_usd"]),total_credit,inv)
            ch.equal("invoice_allocation_header",c(r["allocated_total_usd"]),total_alloc,inv)
            ch.equal("invoice_open_amount",c(r["open_amount_usd"]),residual,inv)
            ch.test("invoice_ar_nonnegative",residual>=0,inv)
            ch.test("open_ar_register_presence",(inv in open_ar)==(residual!=0),inv)
            if inv in open_ar:
                ch.equal("open_ar_register_amount",c(open_ar[inv]["open_amount_usd"]),residual,inv)
                ch.test("open_ar_age",int(open_ar[inv]["days_past_due"])==max(0,(date.fromisoformat(CUTOFF)-date.fromisoformat(r["due_date"])).days),inv)
            entries = [("1100",c(r["total_usd"])),("2100",-c(r["tax_usd"]))]
            account_by_type = {"labor":"4000","parts":"4010","fee":"4020","sublet":"4030"}
            for line in invoice_lines[inv]:
                entries.append((account_by_type[line["line_type"]],-c(line["net_usd"])))
            self.expect("customer_invoice_source_to_gl", "customer_invoice",inv,r["invoice_date"],r["location_id"],entries)
            for month in MONTHS:
                if r["invoice_date"]<=ENDS[month]:
                    balance = c(r["total_usd"])-sum(c(a["total_usd"]) for a in credits[inv] if a["credit_date"]<=ENDS[month])-sum(c(a["amount_usd"]) for a in allocations[inv] if a["allocation_date"]<=ENDS[month])
                    ch.test("ar_nonnegative_each_monthend",balance>=0,f"{month}/{inv}")
                    ar_monthly[(month,r["location_id"])] += balance
            key = r["invoice_date"][:7],r["location_id"]
            sales_monthly[key] += c(r["net_usd"])
            self.tax_collected[key] += c(r["tax_usd"])
        credit_lines = self.group("billing/credit_lines","credit_note_id")
        for r in self.rows("billing/credit_notes"):
            lines = credit_lines[r["credit_note_id"]]
            for field, linefield in [("net_usd","net_credit_usd"),("tax_usd","tax_credit_usd"),("total_usd","total_credit_usd")]:
                ch.equal("credit_note_header_sums_lines",c(r[field]),sum(c(a[linefield]) for a in lines),r["credit_note_id"])
            ch.equal("credit_note_net_plus_tax",c(r["total_usd"]),c(r["net_usd"])+c(r["tax_usd"]),r["credit_note_id"])
            ch.equal("credit_note_tax_reversal",c(r["tax_usd"]),rounded(Decimal(c(r["net_usd"]))*Decimal("0.065")),r["credit_note_id"])
            ch.test("credit_date_after_invoice",r["credit_date"]>=invoices[r["invoice_id"]]["invoice_date"],r["credit_note_id"])
            self.expect("customer_credit_source_to_gl","customer_credit",r["credit_note_id"],r["credit_date"],r["location_id"],[("4090",c(r["net_usd"])),("2100",c(r["tax_usd"])),("1100",-c(r["total_usd"]))])
            key = r["credit_date"][:7],r["location_id"]
            sales_monthly[key] -= c(r["net_usd"])
            self.tax_collected[key] -= c(r["tax_usd"])
            for line in lines:
                original = self.idx("billing/invoice_lines")[line["invoice_line_id"]]
                ch.test("credit_original_invoice_link",original["invoice_id"]==r["invoice_id"] and 0<=c(line["net_credit_usd"])<=c(original["net_usd"]),line["credit_line_id"])
                ch.test("concession_no_inventory_restock",line["inventory_effect"]=="none" and r["restock"]=="False",line["credit_line_id"])
        payment_alloc = self.group("billing/payment_allocations","payment_id")
        for r in self.rows("billing/payments"):
            amount = c(r["amount_usd"])
            clear = "1010" if r["tender_type"]=="card" else "1020"
            offset = "2200" if r["purpose"]=="deposit_receipt" else "1100"
            self.expect("customer_payment_source_to_gl","customer_payment",r["payment_id"],r["payment_date"],r["location_id"],[(clear,amount),(offset,-amount)])
            ch.test("payment_sign_type",(amount<0)==(r["payment_type"]=="refund"),r["payment_id"])
            if r["invoice_id"]:
                ch.equal("payment_allocation_complete",sum(c(a["amount_usd"]) for a in payment_alloc[r["payment_id"]]),amount,r["payment_id"])
                ch.test("payment_not_before_invoice",r["payment_date"]>=invoices[r["invoice_id"]]["invoice_date"],r["payment_id"])
            if amount<0:
                original = self.idx("billing/payments")[r["original_payment_id"]]
                ch.test("refund_original_payment_link",original["amount_usd"] and c(original["amount_usd"])>0 and original["payment_date"]<=r["payment_date"] and original["invoice_id"]==r["invoice_id"],r["payment_id"])
        deposits = self.idx("billing/deposits")
        dep_events = self.group("billing/deposit_events","deposit_id")
        open_dep = self.idx("billing/open_deposits")
        dep_monthly = defaultdict(int)
        for did,r in deposits.items():
            balance = sum(c(e["liability_delta_usd"]) for e in dep_events[did])
            ch.equal("deposit_header_rollforward",c(r["received_amount_usd"])-c(r["applied_amount_usd"]),c(r["unapplied_amount_usd"]),did)
            ch.equal("deposit_event_ending_liability",balance,c(r["unapplied_amount_usd"]),did)
            ch.test("open_deposits_register_presence",(did in open_dep)==(balance>0),did)
            if did in open_dep:
                ch.equal("open_deposit_register_amount",c(open_dep[did]["liability_usd"]),balance,did)
            if r["applied_invoice_id"]:
                inv = invoices[r["applied_invoice_id"]]
                ch.test("deposit_application_only_at_delivery",r["applied_date"]==inv["invoice_date"] and r["ro_id"]==inv["ro_id"],did)
                amount = c(r["applied_amount_usd"])
                self.expect("deposit_application_source_to_gl","deposit_application",did,r["applied_date"],r["location_id"],[("2200",amount),("1100",-amount)])
            for month in MONTHS:
                balance = sum(c(e["liability_delta_usd"]) for e in dep_events[did] if e["event_date"]<=ENDS[month])
                ch.test("deposit_liability_nonnegative_monthend",balance>=0,f"{month}/{did}")
                dep_monthly[(month,r["location_id"])] += balance
        for month in MONTHS:
            for loc in self.locations:
                key = month,loc
                ch.equal("ar_monthend_source_to_gl1100",ar_monthly[key],self.closing[(month,loc,"1100")],str(key))
                ch.equal("deposits_monthend_source_to_gl2200",dep_monthly[key],-self.closing[(month,loc,"2200")],str(key))
                ledger_sales = -sum(self.activity[(month,loc,a)] for a in ["4000","4010","4020","4030","4090"])
                ch.equal("earned_net_sales_invoice_credit_to_gl",sales_monthly[key],ledger_sales,str(key))
                self.controls[key].update(ar_source_usd=ar_monthly[key],deposits_source_usd=dep_monthly[key],earned_net_sales_usd=sales_monthly[key])
        for r in self.rows("warranty/comebacks"):
            corrective, original = ros[r["corrective_ro_id"]],ros[r["original_ro_id"]]
            ch.test("warranty_comeback_links",corrective["is_warranty"]=="True" and corrective["original_ro_id"]==original["ro_id"] and corrective["customer_id"]==original["customer_id"] and corrective["vehicle_id"]==original["vehicle_id"],r["comeback_id"])
            ch.equal("warranty_corrective_parts_cost",c(r["corrective_parts_cost_usd"]),self.issue_cost[r["corrective_ro_id"]],r["comeback_id"])
            ch.equal("warranty_corrective_clock",int(r["corrective_actual_minutes"]),self.ro_clock[r["corrective_ro_id"]],r["comeback_id"])
            ch.equal("warranty_customer_charge_zero",c(r["customer_charge_usd"]),0,r["comeback_id"])
        for r in self.rows("warranty/supplier_recoveries"):
            vc = self.idx("accounting/vendor_credits")[r["vendor_credit_id"]]
            corrective = ros[r["corrective_ro_id"]]
            ch.test("warranty_recovery_after_delivery",bool(corrective["actual_delivery_date"]) and corrective["actual_delivery_date"]<=r["recovery_date"],r["recovery_id"])
            ch.test("warranty_recovery_vendor_credit_expense_offset",vc["source_type"]=="warranty_recovery" and vc["source_id"]==r["recovery_id"] and vc["offset_account_code"]=="5120" and vc["ro_id"]==r["corrective_ro_id"] and r["inventory_restock"]=="False",r["recovery_id"])
            ch.equal("warranty_recovery_credit_value",c(vc["amount_usd"]),c(r["amount_usd"]),r["recovery_id"])

    def ap(self):
        ch = self.checks
        bills = self.idx("accounting/bills")
        lines = self.group("accounting/bill_lines","bill_id")
        allocations = self.group("accounting/ap_allocations","bill_id")
        open_ap = self.idx("accounting/open_ap")
        ap_monthly = defaultdict(int)
        for bid,r in bills.items():
            entries = [("2000",-c(r["total_usd"]))]
            for line in lines[bid]:
                ch.equal("vendor_bill_line_net_plus_tax",c(line["net_usd"])+c(line["tax_usd"]),c(line["total_usd"]),line["bill_line_id"])
                entries.append((line["account_code"],c(line["total_usd"])))
            for field in ["net_usd","tax_usd","total_usd"]:
                ch.equal("vendor_bill_header_sums_lines",c(r[field]),sum(c(l[field]) for l in lines[bid]),f"{bid}/{field}")
            self.expect("vendor_bill_source_to_gl","vendor_bill",bid,r["bill_date"],r["location_id"],entries)
            residual = c(r["total_usd"])-sum(c(a["amount_usd"]) for a in allocations[bid])
            ch.equal("vendor_bill_open_header",c(r["open_amount_usd"]),residual,bid)
            ch.test("open_ap_register_presence",(bid in open_ap)==(residual>0),bid)
            if bid in open_ap:
                ch.equal("open_ap_register_amount",c(open_ap[bid]["open_amount_usd"]),residual,bid)
            for month in MONTHS:
                if r["bill_date"]<=ENDS[month]:
                    amount = c(r["total_usd"])-sum(c(a["amount_usd"]) for a in allocations[bid] if a["allocation_date"]<=ENDS[month])
                    ch.test("ap_nonnegative_each_bill_monthend",amount>=0,f"{month}/{bid}")
                    ap_monthly[(month,r["location_id"])] += amount
        credit_allocs, cash_allocs = defaultdict(int),defaultdict(int)
        for r in self.rows("accounting/ap_allocations"):
            bill = bills[r["bill_id"]]
            ch.test("ap_allocation_after_bill",r["allocation_date"]>=bill["bill_date"],r["ap_allocation_id"])
            if r["allocation_type"]=="vendor_credit":
                credit = self.idx("accounting/vendor_credits")[r["vendor_credit_id"]]
                ch.test("ap_credit_allocation_identity_date",credit["bill_id"]==r["bill_id"] and credit["credit_date"]==r["allocation_date"] and not r["vendor_payment_id"],r["ap_allocation_id"])
                credit_allocs[r["vendor_credit_id"]] += c(r["amount_usd"])
            else:
                payment = self.idx("accounting/vendor_payments")[r["vendor_payment_id"]]
                ch.test("ap_cash_allocation_identity_date",payment["payment_date"]==r["allocation_date"] and payment["vendor_id"]==bill["vendor_id"] and not r["vendor_credit_id"],r["ap_allocation_id"])
                cash_allocs[r["vendor_payment_id"]] += c(r["amount_usd"])
        for r in self.rows("accounting/vendor_credits"):
            amount = c(r["amount_usd"])
            ch.equal("vendor_credit_fully_allocated_once",credit_allocs[r["vendor_credit_id"]],amount,r["vendor_credit_id"])
            self.expect("vendor_credit_source_to_gl","vendor_credit",r["vendor_credit_id"],r["credit_date"],r["location_id"],[("2000",amount),(r["offset_account_code"],-amount)])
        for r in self.rows("accounting/vendor_payments"):
            amount = c(r["amount_usd"])
            ch.equal("vendor_payment_fully_allocated",cash_allocs[r["vendor_payment_id"]],amount,r["vendor_payment_id"])
            self.expect("vendor_payment_source_to_gl","vendor_payment",r["vendor_payment_id"],r["payment_date"],r["location_id"],[("2000",amount),("1000",-amount)])
            bank = self.idx("bank/statement")[r["bank_transaction_id"]]
            ch.equal("vendor_payment_to_bank",-c(bank["amount_usd"]),amount,r["vendor_payment_id"])
        for month in MONTHS:
            for loc in self.locations:
                source = ap_monthly[(month,loc)]
                ch.equal("ap_monthend_source_to_gl2000",source,-self.closing[(month,loc,"2000")],f"{month}/{loc}")
                self.controls[(month,loc)]["ap_source_usd"] = source

    def payroll(self):
        ch = self.checks
        employees, comps = self.idx("payroll/employees"),self.idx("payroll/compensation_history")
        attendance = defaultdict(list)
        attendance_keys = set()
        for r in self.rows("payroll/attendance"):
            daykey = r["employee_id"],r["work_date"]
            ch.test("attendance_employee_date_unique",daykey not in attendance_keys,str(daykey))
            attendance_keys.add(daykey)
            ch.equal("attendance_paid_regular_plus_ot",int(r["approved_paid_minutes"]),int(r["regular_paid_minutes"])+int(r["overtime_paid_minutes"]),r["attendance_id"])
            ch.equal("attendance_presence_plus_pto",int(r["approved_paid_minutes"]),int(r["paid_presence_minutes"])+int(r["pto_paid_minutes"]),r["attendance_id"])
            ch.test("attendance_employment_dates",employees[r["employee_id"]]["hire_date"]<=r["work_date"],r["attendance_id"])
            attendance[halfkey(r["employee_id"],r["work_date"])].append(r)
        delivered_book = defaultdict(Decimal)
        ros = self.idx("shop/repair_orders")
        for job in self.rows("shop/jobs"):
            ro = ros[job["ro_id"]]
            if ro["actual_delivery_date"] and ro["is_warranty"]=="False":
                delivered_book[halfkey(job["employee_id"],ro["actual_delivery_date"])] += Decimal(job["book_billed_hours"])
        run_earnings = self.group("payroll/earnings","payroll_run_id")
        allocation_by_earning = self.group("payroll/job_cost_allocations","earning_id")
        earned_keys = Counter()
        for r in self.rows("payroll/earnings"):
            key = halfkey(r["employee_id"],r["period_end"])
            earned_keys[key] += 1
            a = attendance[key]
            comp = comps[r["compensation_id"]]
            ch.test("payroll_effective_compensation",comp["employee_id"]==r["employee_id"] and comp["effective_from"]<=r["period_end"] and (not comp["effective_to"] or r["period_end"]<=comp["effective_to"]),r["earning_id"])
            for field, att_field in [("regular_paid_minutes","regular_paid_minutes"),("overtime_paid_minutes","overtime_paid_minutes"),("paid_minutes","approved_paid_minutes"),("paid_presence_minutes","paid_presence_minutes")]:
                ch.equal("payroll_minutes_from_approved_attendance",int(r[field]),sum(int(x[att_field]) for x in a),f"{r['earning_id']}/{field}")
            ch.equal("payroll_clock_from_actual_segments",int(r["approved_job_clock_minutes"]),self.period_clock[key],r["earning_id"])
            ch.test("payroll_clock_le_paid_presence",int(r["approved_job_clock_minutes"])<=int(r["paid_presence_minutes"]),r["earning_id"])
            ch.test("payroll_delivered_book_from_ro",Decimal(r["delivered_book_hours"])==delivered_book[key],f"{r['earning_id']}: {r['delivered_book_hours']} vs {delivered_book[key]}")
            annual, hourly = c(comp["annual_salary_usd"]),c(comp["hourly_rate_usd"])
            regular = rounded(Decimal(annual)/24) if annual else rounded(Decimal(hourly)*int(r["regular_paid_minutes"])/60)
            overtime = 0 if annual else rounded(Decimal(hourly)*int(r["overtime_paid_minutes"])/60*Decimal(comp["overtime_multiplier"]))
            bonus = rounded(max(Decimal(0),delivered_book[key]-Decimal(comp["book_bonus_threshold_hours"]))*c(comp["book_bonus_per_hour_usd"]))
            gross = regular+overtime+bonus
            withholding = rounded(Decimal(gross)*Decimal(comp["employee_withholding_pct"])/100)
            tax = rounded(Decimal(gross)*Decimal(comp["employer_tax_pct"])/100)
            benefit = rounded(Decimal(int(r["paid_minutes"]))/60*c(comp["employer_benefit_per_paid_hour_usd"]))
            expected = {"regular_gross_usd":regular,"overtime_gross_usd":overtime,"book_bonus_usd":bonus,"gross_pay_usd":gross,"employee_withholding_usd":withholding,"net_pay_usd":gross-withholding,"employer_tax_usd":tax,"employer_benefits_usd":benefit,"total_employer_cost_usd":gross+tax+benefit}
            for field,amount in expected.items():
                ch.equal("payroll_gross_to_net_and_employer_cost",c(r[field]),amount,f"{r['earning_id']}/{field}")
            allocations = allocation_by_earning[r["earning_id"]]
            allocated = sum(c(a["allocated_actual_payroll_usd"]) for a in allocations)
            total_clock = sum(int(a["approved_job_clock_minutes"]) for a in allocations)
            if employees[r["employee_id"]]["role"]=="technician":
                target = rounded(Decimal(expected["total_employer_cost_usd"])*self.period_clock[key]/int(r["paid_minutes"])) if int(r["paid_minutes"]) else 0
                ch.equal("job_allocations_rounded_aggregate_productive_share",allocated,target,r["earning_id"])
                ch.equal("job_allocations_cover_clock_once",total_clock,self.period_clock[key],r["earning_id"])
            ch.test("job_allocations_not_more_than_earned_payroll",0<=allocated<=expected["total_employer_cost_usd"],r["earning_id"])
            for a in allocations:
                ch.test("job_allocations_management_only",a["posting_status"]=="management_memo_only",a["labor_allocation_id"])
                ch.equal("job_allocation_actual_ro_minutes",int(a["approved_job_clock_minutes"]),self.period_ro_clock[key+(a["ro_id"],)],a["labor_allocation_id"])
                ch.equal("job_allocation_paid_denominator",int(a["paid_minutes_denominator"]),int(r["paid_minutes"]),a["labor_allocation_id"])
        for key in attendance:
            ch.equal("approved_attendance_in_payroll_once",earned_keys[key],1,str(key))
        funding_by_run = self.group("payroll/funding","payroll_run_id")
        accrued = defaultdict(int)
        funded = defaultdict(int)
        for r in self.rows("payroll/runs"):
            earnings = run_earnings[r["payroll_run_id"]]
            field_map = {"gross_pay_usd":"gross_pay_usd","net_pay_usd":"net_pay_usd","employee_withholding_usd":"employee_withholding_usd","employer_taxes_usd":"employer_tax_usd","employer_benefits_usd":"employer_benefits_usd","total_funding_usd":"total_employer_cost_usd"}
            for field, ef in field_map.items():
                ch.equal("payroll_run_sum_employee_earnings",c(r[field]),sum(c(e[ef]) for e in earnings),f"{r['payroll_run_id']}/{field}")
            entries = defaultdict(int)
            for e in earnings:
                emp = employees[e["employee_id"]]
                gross,tax,benefit = c(e["gross_pay_usd"]),c(e["employer_tax_usd"]),c(e["employer_benefits_usd"])
                if emp["role"]=="technician":
                    entries["5000"]+=gross
                    entries["5010"]+=tax
                    entries["5015"]+=benefit
                elif r["location_id"]=="HQ":
                    entries["6200"]+=gross
                    entries["6210"]+=tax+benefit
                else:
                    entries["6100"]+=gross
                    entries["6110"]+=tax+benefit
            entries["2300"]-=c(r["total_funding_usd"])
            self.expect("payroll_earned_source_to_gl","payroll_earned",r["payroll_run_id"],r["earned_date"],r["location_id"],list(entries.items()))
            ch.test("payroll_funding_actual_presence",bool(r["actual_funding_date"])==(r["status"]=="funded") and len(funding_by_run[r["payroll_run_id"]])==int(bool(r["actual_funding_date"])),r["payroll_run_id"])
            accrued[(r["earned_date"][:7],r["location_id"])] += c(r["total_funding_usd"])
        for r in self.rows("payroll/funding"):
            amount = c(r["total_funded_usd"])
            ch.equal("payroll_funding_net_withholding_tax_benefit",amount,sum(c(r[f]) for f in ["net_pay_usd","employee_withholding_remitted_usd","employer_tax_remitted_usd","benefits_funded_usd"]),r["funding_id"])
            self.expect("payroll_funding_source_to_gl","payroll_funding",r["funding_id"],r["actual_funding_date"],r["location_id"],[("2300",amount),("1000",-amount)])
            bank = self.idx("bank/statement")[r["bank_transaction_id"]]
            ch.equal("payroll_funding_to_bank",-c(bank["amount_usd"]),amount,r["funding_id"])
            ch.test("payroll_funding_bank_date",bank["posted_date"]==r["actual_funding_date"],r["funding_id"])
            funded[(r["actual_funding_date"][:7],r["location_id"])] += amount
        outstanding = defaultdict(int)
        for month in MONTHS:
            for loc in self.locations:
                key = month,loc
                outstanding[loc]+=accrued[key]-funded[key]
                ch.equal("payroll_monthend_source_to_gl2300",outstanding[loc],-self.closing[(month,loc,"2300")],str(key))
                self.controls[key].update(payroll_earned_usd=accrued[key],payroll_funded_usd=funded[key],payroll_payable_source_usd=outstanding[loc])
        print("Payroll earned attendance, gross-to-net, actual funding and memo allocations recomputed",flush=True)

    def processor_and_bank(self):
        ch = self.checks
        payments, bank = self.idx("billing/payments"),self.idx("bank/statement")
        transactions_by_payment = self.group("processor/balance_transactions","payment_id")
        tx_by_payout = self.group("processor/balance_transactions","payout_id")
        for pid,p in payments.items():
            ch.equal("card_payments_have_exactly_one_processor_record",len(transactions_by_payment[pid]),int(p["tender_type"]=="card"),pid)
        for r in self.rows("processor/balance_transactions"):
            p = payments[r["payment_id"]]
            gross,fee,net = c(r["gross_usd"]),c(r["fee_usd"]),c(r["net_usd"])
            ch.equal("processor_gross_equals_payment",gross,c(p["amount_usd"]),r["balance_transaction_id"])
            ch.equal("processor_fee_contract_rounding",fee,rounded(Decimal(gross)*Decimal("0.027"))+25 if gross>0 else 0,r["balance_transaction_id"])
            ch.equal("processor_net_gross_less_fee",net,gross-fee,r["balance_transaction_id"])
            ch.test("processor_available_after_capture",r["transaction_date"]<=r["available_date"],r["balance_transaction_id"])
            if fee:
                self.expect("processor_fee_source_to_gl","processing_fee",r["balance_transaction_id"],r["transaction_date"],r["location_id"],[("6500",fee),("1010",-fee)])
        payouts = self.idx("processor/payouts")
        for pid,r in payouts.items():
            amount = c(r["net_amount_usd"])
            ch.equal("payout_sum_processor_nets",amount,sum(c(t["net_usd"]) for t in tx_by_payout[pid]),pid)
            ch.test("payout_after_funds_available",all(t["available_date"]<=r["initiated_date"] for t in tx_by_payout[pid]),pid)
            settled = bool(r["actual_bank_date"])
            ch.test("payout_actual_vs_in_transit",settled==(r["status"]=="paid") and bool(r["bank_transaction_id"])==settled,pid)
            if settled:
                b = bank[r["bank_transaction_id"]]
                ch.equal("processor_payout_to_bank",c(b["amount_usd"]),amount,pid)
                ch.test("processor_payout_bank_identity_date",b["source_id"]==pid and b["posted_date"]==r["actual_bank_date"],pid)
                self.expect("processor_payout_source_to_gl","payout_bank",pid,r["actual_bank_date"],r["location_id"],[("1000",amount),("1010",-amount)])
        noncard_batches = defaultdict(list)
        for p in payments.values():
            if p["tender_type"]!="card" and p["bank_transaction_id"]:
                noncard_batches[p["bank_transaction_id"]].append(p)
        for bid, rows in noncard_batches.items():
            b = bank[bid]
            amount = sum(c(p["amount_usd"]) for p in rows)
            ch.equal("noncard_customer_batch_to_bank",c(b["amount_usd"]),amount,bid)
            ch.test("noncard_bank_no_early_settlement",all(p["payment_date"]<=b["posted_date"] for p in rows),bid)
            self.expect("noncard_bank_source_to_gl","noncard_bank_batch",b["source_id"],b["posted_date"],b["location_id"],[("1000",amount),("1020",-amount)])
        tx = self.rows("processor/balance_transactions")
        self.clearing_components = []
        for month in MONTHS:
            end = ENDS[month]
            for loc in self.locations:
                net = sum(c(t["net_usd"]) for t in tx if t["location_id"]==loc and t["transaction_date"]<=end)
                settled = sum(c(p["net_amount_usd"]) for p in payouts.values() if p["location_id"]==loc and p["actual_bank_date"] and p["actual_bank_date"]<=end)
                residual = net-settled
                transit = sum(c(t["net_usd"]) for t in tx if t["location_id"]==loc and t["transaction_date"]<=end and (not t["payout_id"] or not payouts[t["payout_id"]]["actual_bank_date"] or payouts[t["payout_id"]]["actual_bank_date"]>end))
                ch.equal("processor_clearing_equals_unsettled_including_transit",residual,transit,f"{month}/{loc}")
                ch.equal("processor_monthend_source_to_gl1010",residual,self.closing[(month,loc,"1010")],f"{month}/{loc}")
                pending = sum(c(p["amount_usd"]) for p in payments.values() if p["location_id"]==loc and p["tender_type"]!="card" and p["payment_date"]<=end and (not p["bank_transaction_id"] or bank[p["bank_transaction_id"]]["posted_date"]>end))
                ch.equal("noncard_monthend_source_to_gl1020",pending,self.closing[(month,loc,"1020")],f"{month}/{loc}")
                self.controls[(month,loc)].update(processor_clearing_source_usd=residual,noncard_clearing_source_usd=pending)
        account = self.rows("bank/accounts")[0]
        opening = c(account["opening_balance_usd"])
        ch.equal("bank_opening_to_company_gl1000",opening,sum(self.opening.get((l,"1000"),0) for l in self.locations),"opening")
        statement = sorted(bank.values(),key=lambda r:int(r["statement_sequence"]))
        running,previous_day = opening,""
        bank_month = defaultdict(lambda:[0,0,0])
        bank_loc = defaultdict(int)
        for ix,r in enumerate(statement,1):
            ch.equal("bank_sequence_contiguous",int(r["statement_sequence"]),ix,r["bank_transaction_id"])
            ch.test("bank_sequence_chronological",r["posted_date"]>=previous_day,r["bank_transaction_id"])
            previous_day = r["posted_date"]
            amount = c(r["amount_usd"])
            running+=amount
            ch.equal("bank_running_balance",c(r["running_balance_usd"]),running,r["bank_transaction_id"])
            month = r["posted_date"][:7]
            bank_month[month][0]+=max(amount,0)
            bank_month[month][1]+=max(-amount,0)
            bank_month[month][2]+=1
            bank_loc[(month,r["location_id"])] += amount
        monthly = self.idx("bank/monthly_statements","month")
        balance,byloc = opening,{l:self.opening.get((l,"1000"),0) for l in self.locations}
        for month in MONTHS:
            r = monthly[month]
            incoming,outgoing,count = bank_month[month]
            ch.equal("bank_monthly_opening",c(r["opening_balance_usd"]),balance,month)
            ch.equal("bank_monthly_inflows",c(r["inflows_usd"]),incoming,month)
            ch.equal("bank_monthly_outflows",c(r["outflows_usd"]),outgoing,month)
            ch.equal("bank_monthly_transaction_count",int(r["transaction_count"]),count,month)
            balance += incoming-outgoing
            ch.equal("bank_monthly_closing",c(r["closing_balance_usd"]),balance,month)
            for loc in self.locations:
                byloc[loc] += bank_loc[(month,loc)]
                ch.equal("bank_monthend_source_to_gl1000",byloc[loc],self.closing[(month,loc,"1000")],f"{month}/{loc}")
                self.controls[(month,loc)]["bank_source_usd"] = byloc[loc]
        print("Processor gross/fees/net, payout transit, bank running and monthly cash reconciled",flush=True)

    def fixed_assets_tax_and_debt(self):
        ch = self.checks
        assets = self.idx("operating/assets")
        depreciation = self.group("operating/depreciation","asset_id")
        assets_month, accdep_month = defaultdict(int),defaultdict(int)
        for aid,r in assets.items():
            charge = rounded(Decimal(c(r["original_cost_usd"])-c(r["salvage_value_usd"]))/int(r["useful_life_months"]))
            actual_months = {d["month"] for d in depreciation[aid]}
            expected_months = {m for m in MONTHS if ENDS[m]>=r["in_service_date"] and (not r["disposal_date"] or m<=r["disposal_date"][:7])}
            ch.test("asset_monthly_depreciation_coverage",actual_months==expected_months,aid)
            for d in depreciation[aid]:
                ch.equal("depreciation_straight_line_rounding",c(d["depreciation_usd"]),charge,d["depreciation_id"])
                ch.test("depreciation_monthend_date",d["depreciation_date"]==ENDS[d["month"]],d["depreciation_id"])
                self.expect("depreciation_source_to_gl","depreciation",d["depreciation_id"],d["depreciation_date"],d["location_id"],[("6600",charge),("1590",-charge)])
            for month in MONTHS:
                if r["in_service_date"]<=ENDS[month]:
                    assets_month[(month,r["location_id"])] += c(r["original_cost_usd"])
                    accumulated = c(r["opening_accumulated_depreciation_usd"])+sum(c(d["depreciation_usd"]) for d in depreciation[aid] if d["month"]<=month)
                    ch.test("asset_accumulated_depreciation_not_excess",accumulated<=c(r["original_cost_usd"])-c(r["salvage_value_usd"]),f"{month}/{aid}")
                    accdep_month[(month,r["location_id"])] += accumulated
        loans = self.idx("finance/loans")
        schedules = self.group("finance/debt_schedule","loan_id")
        loan_month = defaultdict(int)
        for lid,loan in loans.items():
            previous = c(loan["opening_principal_usd"])
            for r in sorted(schedules[lid],key=lambda x:x["due_date"]):
                principal,interest = c(r["principal_usd"]),c(r["interest_usd"])
                ch.equal("debt_opening_rollforward",c(r["opening_scheduled_principal_usd"]),previous,r["debt_schedule_id"])
                ch.equal("debt_principal_closing",c(r["closing_scheduled_principal_usd"]),previous-principal,r["debt_schedule_id"])
                ch.equal("debt_interest_contract",interest,rounded(Decimal(previous)*Decimal(loan["annual_interest_pct"])/100/12),r["debt_schedule_id"])
                ch.equal("debt_payment_principal_plus_interest",c(r["total_payment_usd"]),principal+interest,r["debt_schedule_id"])
                previous-=principal
                if r["actual_payment_date"]:
                    self.expect("debt_actual_source_to_gl","debt_service",r["debt_schedule_id"],r["actual_payment_date"],r["location_id"],[("2500",principal),("6700",interest),("1000",-principal-interest)])
                    b = self.idx("bank/statement")[r["bank_transaction_id"]]
                    ch.equal("debt_actual_to_bank",-c(b["amount_usd"]),principal+interest,r["debt_schedule_id"])
                else:
                    ch.test("future_debt_blank_actual_no_bank",r["due_date"]>CUTOFF and not r["bank_transaction_id"] and r["status"]=="contractual_future",r["debt_schedule_id"])
            for month in MONTHS:
                loan_month[(month,loan["location_id"])] += c(loan["opening_principal_usd"])-sum(c(r["principal_usd"]) for r in schedules[lid] if r["actual_payment_date"] and r["actual_payment_date"]<=ENDS[month])
        tax = self.rows("finance/tax_register")
        tax_month = defaultdict(int)
        for r in tax:
            key = r["tax_month"],r["location_id"]
            ch.equal("tax_register_invoice_less_credit",c(r["net_tax_collected_usd"]),self.tax_collected[key],r["tax_period_id"])
            ch.equal("tax_register_payable_rollforward",c(r["net_tax_collected_usd"])-c(r["remitted_usd"]),c(r["open_payable_usd"]),r["tax_period_id"])
            if r["actual_remittance_date"]:
                amount = c(r["remitted_usd"])
                self.expect("tax_remittance_source_to_gl","sales_tax_remittance",r["tax_period_id"],r["actual_remittance_date"],r["location_id"],[("2100",amount),("1000",-amount)])
                b = self.idx("bank/statement")[r["bank_transaction_id"]]
                ch.equal("tax_remittance_to_bank",-c(b["amount_usd"]),amount,r["tax_period_id"])
            else:
                ch.test("unremitted_tax_no_bank",not r["bank_transaction_id"] and c(r["remitted_usd"])==0,r["tax_period_id"])
            for month in MONTHS:
                if r["tax_month"]<=month:
                    tax_month[(month,r["location_id"])] += c(r["net_tax_collected_usd"])-(c(r["remitted_usd"]) if r["actual_remittance_date"] and r["actual_remittance_date"]<=ENDS[month] else 0)
        for month in MONTHS:
            for loc in self.locations:
                key = month,loc
                ch.equal("fixed_assets_monthend_source_to_gl1500",assets_month[key],self.closing[(month,loc,"1500")],str(key))
                ch.equal("accumulated_depreciation_source_to_gl1590",accdep_month[key],-self.closing[(month,loc,"1590")],str(key))
                ch.equal("debt_monthend_source_to_gl2500",loan_month[key],-self.closing[(month,loc,"2500")],str(key))
                ch.equal("tax_monthend_source_to_gl2100",tax_month[key],-self.closing[(month,loc,"2100")],str(key))
                self.controls[key].update(fixed_asset_cost_source_usd=assets_month[key],accumulated_depreciation_source_usd=accdep_month[key],debt_principal_source_usd=loan_month[key],sales_tax_payable_source_usd=tax_month[key])
        if "finance/owner_distributions" in self.tables:
            bank_by_day = defaultdict(int)
            for r in self.rows("bank/statement"):
                bank_by_day[r["posted_date"]]+=c(r["amount_usd"])
            opening_cash = sum(c(r["opening_balance_usd"]) for r in self.rows("bank/accounts"))
            for r in self.rows("finance/owner_distributions"):
                amount = c(r["amount_usd"])
                self.expect("owner_distribution_source_to_gl","owner_distribution",r["distribution_id"],r["distribution_date"],r["location_id"],[("3100",amount),("1000",-amount)])
                b = self.idx("bank/statement")[r["bank_transaction_id"]]
                ch.equal("owner_distribution_to_bank",-c(b["amount_usd"]),amount,r["distribution_id"])
                ch.test("owner_distribution_cap",0<amount<=c(r["quarterly_cap_usd"]),r["distribution_id"])
                closing = opening_cash+sum(v for day,v in bank_by_day.items() if day<=r["distribution_date"])
                ch.test("owner_distribution_respects_cash_reserve",closing>=c(r["minimum_cash_reserve_usd"]),f"{r['distribution_id']}: closing={closing}")

    def marketing_shared_and_planning(self):
        ch = self.checks
        daily_spend = defaultdict(int)
        for r in self.rows("marketing/daily_performance"):
            ch.equal("ad_cost_micros_to_usd",int(r["cost_micros"]),c(r["spend_usd"])*10000,r["performance_id"])
            daily_spend[(r["platform"],r["location_id"],r["performance_date"][:7])] += c(r["spend_usd"])
        for r in self.rows("marketing/billing"):
            expected = daily_spend[(r["platform"],r["location_id"],r["service_month"])]
            ch.equal("ad_bill_sum_daily_spend",c(r["amount_usd"]),expected,r["ad_bill_id"])
            ch.equal("ad_bill_to_accounting_bill",c(self.idx("accounting/bills")[r["accounting_bill_id"]]["total_usd"]),expected,r["ad_bill_id"])
        shares = defaultdict(int)
        hq_share = defaultdict(int)
        memo_ids = set()
        for r in self.rows("accounting/shared_cost_allocations"):
            key = r["month"],r["account_code"]
            shares[key] += c(r["allocated_expense_delta_usd"])
            if r["location_id"]=="HQ": hq_share[key] += c(r["allocated_expense_delta_usd"])
            ch.test("shared_allocations_management_only",r["posting_status"]=="management_memo_only",r["shared_allocation_id"])
            memo_ids.add(r["shared_allocation_id"])
        memo_ids.update(r["labor_allocation_id"] for r in self.rows("payroll/job_cost_allocations"))
        for key,total in shares.items():
            ch.equal("shared_cost_allocation_company_zero",total,0,str(key))
            ch.equal("shared_hq_reversal_equals_actual_expense",hq_share[key],-self.activity[(key[0],"HQ",key[1])],str(key))
        for key in self.gl_event:
            ch.test("management_allocations_not_posted_again",key[1] not in memo_ids,str(key))
        versions = self.idx("planning/budget_versions")
        for r in versions.values():
            ch.test("original_budget_approved_before_window",r["approved_date"]<START and r["version_type"]=="original_approved" and r["locked"]=="True" and r["period_start"]==START and r["period_end"]==CUTOFF,r["budget_version_id"])
        budget_keys = Counter()
        for r in self.rows("planning/monthly_budget"):
            key = r["budget_version_id"],r["month"],r["location_id"],r["account_code"]
            budget_keys[key]+=1
            ch.test("budget_lines_original_version_date",r["approved_date"]==versions[r["budget_version_id"]]["approved_date"] and r["approved_date"]<START and r["month"] in MONTHS,r["budget_line_id"])
        for key,count in budget_keys.items(): ch.equal("budget_grain_unique",count,1,str(key))
        for month in MONTHS:
            for loc in self.locations:
                ch.test("approved_budget_all_months_locations",any(k[1]==month and k[2]==loc for k in budget_keys),f"{month}/{loc}")
        commitments_by_source = defaultdict(list)
        overlaps = set()
        for r in self.rows("planning/commitments"):
            ch.test("commitments_future_not_actual",r["as_of_date"]==CUTOFF and r["expected_date"]>CUTOFF and r["actual_event_date"]=="",r["commitment_id"])
            ch.test("commitment_overlap_keys_unique",r["overlap_key"] not in overlaps,r["commitment_id"])
            overlaps.add(r["overlap_key"])
            target = self.idx(r["source_table"])
            ch.test("commitment_source_exists",r["source_id"] in target,r["commitment_id"])
            commitments_by_source[(r["source_table"],r["source_id"])].append(r)
            if r["commitment_type"]=="agreed_future_appointment":
                ch.test("future_appointment_blank_amount",r["expected_amount_usd"]=="",r["commitment_id"])
        for r in self.rows("planning/forecast_assumptions"):
            ch.test("forecast_assumptions_not_actual",r["is_actual"]=="False" and r["as_of_date"]==CUTOFF and r["effective_from"]>CUTOFF,r["assumption_id"])
        def committed(table,ident,expected,kind):
            rows = commitments_by_source[(table,ident)]
            ch.equal("future_obligation_in_commitments_once",len(rows),1,f"{table}/{ident}")
            if rows:
                ch.test("commitment_type_matches_source",rows[0]["commitment_type"]==kind,ident)
                if expected is not None: ch.equal("commitment_amount_matches_source",c(rows[0]["expected_amount_usd"]),expected,ident)
        for r in self.rows("billing/open_ar"): committed("billing/open_ar",r["invoice_id"],c(r["open_amount_usd"]),"customer_collection")
        for r in self.rows("accounting/open_ap"): committed("accounting/open_ap",r["bill_id"],-c(r["open_amount_usd"]),"open_AP_payment")
        for r in self.rows("purchasing/purchase_orders"):
            if c(r["open_commitment_usd"]): committed("purchasing/purchase_orders",r["po_id"],-c(r["open_commitment_usd"]),"unreceived_PO_payment")
        for r in self.rows("payroll/runs"):
            if not r["actual_funding_date"]: committed("payroll/runs",r["payroll_run_id"],-c(r["total_funding_usd"]),"earned_payroll_funding")
        for r in self.rows("finance/debt_schedule"):
            if not r["actual_payment_date"]: committed("finance/debt_schedule",r["debt_schedule_id"],-c(r["total_payment_usd"]),"contractual_debt_payment")
        for r in self.rows("finance/tax_register"):
            if not r["actual_remittance_date"]: committed("finance/tax_register",r["tax_period_id"],-c(r["open_payable_usd"]),"tax_payable_remittance")
        for r in self.rows("schedule/appointments"):
            if r["scheduled_date"]>CUTOFF:
                ch.test("future_booking_actual_fields_blank",not r["actual_dropoff_at"] and not r["actual_pickup_at"],r["appointment_id"])
                committed("schedule/appointments",r["appointment_id"],None,"agreed_future_appointment")
        for r in self.rows("planning/business_events"):
            ch.test("business_event_evidence_tables_exist",all(t.strip() in self.tables and bool(self.tables[t.strip()]) for t in r["evidence_tables"].split(";")),r["event_id"])
        expected_event_dates = {"2025-07-01","2026-01-01","2026-02-02","2026-03-01","2026-04-01","2026-05-01","2026-05-04","2026-07-01","2026-07-06","2026-08-01"}
        ch.test("all_scenario_business_events_present",{r["effective_date"] for r in self.rows("planning/business_events")}==expected_event_dates,"scenario timeline")
        price = self.rows("purchasing/purchase_price_history")
        for sku in self.idx("inventory/parts_catalog"):
            versions = sorted([r for r in price if r["sku"]==sku],key=lambda r:r["effective_from"])
            ch.test("supplier_inflation_event_versions",len(versions)==3 and versions[1]["effective_from"]=="2025-07-01" and versions[2]["effective_from"]=="2026-04-01" and c(versions[0]["base_unit_price_usd"])<c(versions[1]["base_unit_price_usd"])<c(versions[2]["base_unit_price_usd"]),sku)
        for loc,hire in [("LOC-01","2026-02-02"),("LOC-02","2026-05-04"),("LOC-03","2026-07-06")]:
            ch.test("new_hire_scenario_events",any(r["role"]=="technician" and r["location_id"]==loc and r["hire_date"]==hire for r in self.rows("payroll/employees")),loc)
        for table in ["shop/labor_rate_history","payroll/compensation_history","purchasing/terms_history"]:
            fields = {"shop/labor_rate_history":"location_id","payroll/compensation_history":"employee_id","purchasing/terms_history":"supplier_id"}
            groups = self.group(table,fields[table])
            for ident,rows in groups.items():
                previous_end = ""
                for r in sorted(rows,key=lambda r:r["effective_from"]):
                    ch.test("effective_history_versions_do_not_overlap",not previous_end or r["effective_from"]>previous_end,f"{table}/{ident}/{r['effective_from']}")
                    previous_end = r["effective_to"] or "9999-12-31"

    def scenario_evidence(self):
        ch = self.checks
        early,late = set(MONTHS[:12]),set(MONTHS[12:])
        cohorts = {"first_12": {"parts_sales":0,"parts_cogs":0,"book_milli":0,"clock_minutes":0},
                   "last_12": {"parts_sales":0,"parts_cogs":0,"book_milli":0,"clock_minutes":0}}
        ros = self.idx("shop/repair_orders")
        for job in self.rows("shop/jobs"):
            ro = ros[job["ro_id"]]
            if ro["is_warranty"]=="True" or not ro["actual_delivery_date"]: continue
            label = "first_12" if ro["actual_delivery_date"][:7] in early else "last_12"
            cohort = cohorts[label]
            cohort["book_milli"] += q(job["book_billed_hours"])
            cohort["clock_minutes"] += int(job["approved_actual_minutes"])
            cohort["parts_cogs"] += self.issue_cost[ro["ro_id"]]
            cohort["parts_sales"] += sum(c(r["net_usd"]) for r in self.ro_lines[ro["ro_id"]] if r["line_type"]=="parts")
        first,last = cohorts["first_12"],cohorts["last_12"]
        ch.test("scenario_parts_revenue_up_last12_vs_first12",last["parts_sales"]>first["parts_sales"],str(cohorts))
        ch.test("scenario_delivered_parts_gross_margin_declines",last["parts_cogs"]*first["parts_sales"]>first["parts_cogs"]*last["parts_sales"],str(cohorts))
        ch.test("scenario_customer_ro_technician_efficiency_declines",last["book_milli"]*first["clock_minutes"]<first["book_milli"]*last["clock_minutes"],str(cohorts))
        availability = self.rows("schedule/technician_availability")
        employees = self.idx("payroll/employees")
        hire_evidence = []
        for eid,emp in employees.items():
            if emp["role"]!="technician" or emp["hire_date"]<START: continue
            hire = date.fromisoformat(emp["hire_date"])
            end = str(hire+timedelta(days=34))
            loc = emp["location_id"]
            own_available=own_clock=peer_available=peer_clock=0
            for a in availability:
                if a["location_id"]!=loc or not emp["hire_date"]<=a["work_date"]<=end: continue
                key = a["employee_id"],a["work_date"]
                if a["employee_id"]==eid:
                    own_available+=int(a["available_minutes"])
                    own_clock+=self.daily_clock[key]
                elif employees[a["employee_id"]]["hire_date"]<START:
                    peer_available+=int(a["available_minutes"])
                    peer_clock+=self.daily_clock[key]
            item = {"employee_id":eid,"location_id":loc,"hire_date":emp["hire_date"],"window_end":end,"new_hire_clock_minutes":own_clock,"new_hire_available_minutes":own_available,"tenured_peer_clock_minutes":peer_clock,"tenured_peer_available_minutes":peer_available}
            hire_evidence.append(item)
            ch.test("scenario_new_hire_first35day_utilization_below_tenured",own_available>0 and peer_available>0 and own_clock*peer_available<peer_clock*own_available,str(item))
        before_total=after_total=before_warranty=after_warranty=0
        for ro in ros.values():
            if ro["location_id"]!="LOC-03" or ro["status"]=="awaiting_parts": continue
            if ro["opened_date"]<"2026-05-01":
                before_total+=1
                before_warranty+=int(ro["is_warranty"]=="True")
            else:
                after_total+=1
                after_warranty+=int(ro["is_warranty"]=="True")
        comeback = {"location_id":"LOC-03","before_202605_ro_count":before_total,"before_202605_warranty_count":before_warranty,"from_202605_ro_count":after_total,"from_202605_warranty_count":after_warranty}
        ch.test("scenario_loc03_comeback_rate_spikes_from_may2026",before_total>0 and after_total>0 and after_warranty*before_total>before_warranty*after_total,str(comeback))
        sup04 = [r for r in self.rows("purchasing/terms_history") if r["supplier_id"]=="SUP-04" and r["effective_from"]=="2026-08-01"]
        ch.test("scenario_supplier04_terms_tighten_net21",len(sup04)==1 and int(sup04[0]["net_days"])==21,"SUP-04 Aug2026")
        self.scenario_results = {"delivered_customer_ro_cohorts":cohorts,"new_hire_ramp":hire_evidence,"loc03_comeback_rate":comeback,
            "ratio_method":"Integer cross-products; no float/tolerance comparisons. Efficiency uses book hours and actual clock from the identical delivered non-warranty RO cohort. Parts margin uses customer parts revenue and its delivered historical FIFO costs."}

    def contract_forecast_inputs(self):
        """Reconcile cutoff contract rates and the next service cycle independently.

        Rent has one completed January 2026 escalation at this cutoff. Utilities
        and maintenance have variable actual bills, so their base contract rate
        is deliberately not equated with the latest actual bill amount.
        """
        ch = self.checks
        bills_by_contract = self.group("accounting/bills","contract_id")
        bill_lines = self.group("accounting/bill_lines","bill_id")
        commitments_by_contract = defaultdict(list)
        for r in self.rows("planning/commitments"):
            if r["commitment_type"]=="recurring_contract_next_cycle":
                commitments_by_contract[r["source_id"]].append(r)
        contracts = self.idx("operating/recurring_contracts")
        open_ap_by_contract = self.group("accounting/open_ap","contract_id")
        cutoff_day = date.fromisoformat(CUTOFF)
        next_service_month = f"{cutoff_day.year+(cutoff_day.month==12):04d}-{cutoff_day.month%12+1:02d}"
        fixed_accounts = {"6300","6320","6330","6350"}
        for cid,r in contracts.items():
            account = r["expense_account_code"]
            ch.test("contract_snapshot_asof_actual_cutoff",r["as_of_date"]==CUTOFF,cid)
            opening,current = c(r["opening_monthly_base_usd"]),c(r["monthly_base_usd"])
            if account=="6300":
                ch.test("rent_first_escalation_date_and_rate",r["first_escalation_date"]=="2026-01-01" and Decimal(r["annual_increase_pct"])==Decimal("3.00"),cid)
                ch.equal("rent_current_base_includes_completed_three_percent_escalation",current,rounded(Decimal(opening)*Decimal("1.03")),cid)
            else:
                ch.equal("nonrent_current_contract_base_preserves_opening_base",current,opening,cid)
            if account in fixed_accounts:
                bills = [b for b in bills_by_contract[cid] if b["bill_type"]=="recurring_service" and b["bill_date"]<=CUTOFF]
                ch.test("fixed_contract_has_cutoff_bill",bool(bills),cid)
                if bills:
                    latest_date = max(b["bill_date"] for b in bills)
                    latest = [b for b in bills if b["bill_date"]==latest_date]
                    ch.test("fixed_contract_latest_bill_is_cutoff_month_once",latest_date==CUTOFF and len(latest)==1,cid)
                    ch.equal("fixed_contract_current_base_equals_latest_recurring_bill",current,sum(c(b["total_usd"]) for b in latest),cid)
                    for bill in latest:
                        ch.test("fixed_contract_latest_bill_location_and_account",bill["location_id"]==r["location_id"] and all(line["account_code"]==account for line in bill_lines[bill["bill_id"]]),bill["bill_id"])
            future = commitments_by_contract[cid]
            ch.test("each_recurring_contract_next_cycle_commitment_once",len(future)==1,cid)
            ch.test("contract_next_service_cycle_is_november2026",r["next_service_month"]==next_service_month,cid)
            for obligation in future:
                ch.equal("recurring_commitment_uses_current_contract_base",c(obligation["expected_amount_usd"]),-current,obligation["commitment_id"])
                ch.test("recurring_commitment_source_contract_identity",obligation["source_table"]=="operating/recurring_contracts" and obligation["source_id"]==cid and obligation["location_id"]==r["location_id"] and obligation["as_of_date"]==r["as_of_date"],obligation["commitment_id"])
                ch.test("recurring_commitment_expected_date_matches_contract",obligation["expected_date"]==r["next_expected_due_date"] and obligation["expected_date"]>CUTOFF,obligation["commitment_id"])
                expected_overlap = cid+"-"+next_service_month.replace("-","")
                ch.test("recurring_commitment_november_overlap_key",obligation["overlap_key"]==expected_overlap,obligation["commitment_id"])
                october_bill_ids = {b["bill_id"] for b in open_ap_by_contract[cid] if b["bill_date"][:7]==CUTOFF[:7]}
                ch.test("recurring_november_commitment_separate_from_october_open_ap",obligation["source_id"] not in october_bill_ids and obligation["overlap_key"] not in october_bill_ids,obligation["commitment_id"])
        ch.test("recurring_commitments_only_reference_existing_contracts",set(commitments_by_contract)<=set(contracts),str(set(commitments_by_contract)-set(contracts)))

    def special_order_availability(self):
        """Prove pending parts are unavailable approved SKUs with ordered supply.

        On-hand stock is independently rolled from opening stock and physical
        movements. A different interchangeable-looking SKU is never counted as
        availability for the customer-approved special-order SKU.
        """
        ch = self.checks
        catalog = self.idx("inventory/parts_catalog")
        ros = self.idx("shop/repair_orders")
        po_lines = self.group("purchasing/po_lines","po_id")
        pos_by_ro = self.group("purchasing/purchase_orders","ro_id")
        segments = self.group("schedule/job_segments","ro_id")
        awaiting = [r for r in self.rows("inventory/reservations") if r["status"]=="awaiting_receipt"]
        ch.test("scenario_three_awaiting_receipt_special_order_reservations",len(awaiting)==3,f"observed={len(awaiting)}; expected=3")
        for r in awaiting:
            ident = r["reservation_id"]
            reserved = q(r["reserved_base_quantity"])
            unissued = q(r["open_reserved_base_quantity"])
            ch.test("awaiting_receipt_positive_fully_unissued_reservation",reserved==unissued>0 and q(r["issued_base_quantity"])==0 and q(r["released_base_quantity"])==0 and not r["actual_issue_date"],ident)
            ch.test("awaiting_receipt_sku_is_special_order",catalog[r["sku"]]["special_order"]=="True",ident)
            key = r["location_id"],r["sku"]
            ch.test("awaiting_receipt_cutoff_stock_key_exists",key in self.cutoff_inventory_quantities,ident)
            on_hand = self.cutoff_inventory_quantities.get(key,0)
            ch.test("awaiting_receipt_cutoff_stock_insufficient_for_reserved_sku",0<=on_hand<unissued,f"{ident}/{r['sku']}: on_hand_milli={on_hand}; unissued_milli={unissued}")
            matching = []
            for po in pos_by_ro[r["ro_id"]]:
                if po["location_id"]!=r["location_id"] or po["actual_closed_date"] or c(po["open_commitment_usd"])<=0: continue
                if any(line["sku"]==r["sku"] and q(line["open_base_quantity"])>=unissued for line in po_lines[po["po_id"]]):
                    matching.append(po)
            ch.test("awaiting_receipt_matching_open_po_same_ro_sku_quantity",bool(matching),ident)
            planned = [segment for segment in segments[r["ro_id"]] if segment["booked_start_at"] and not segment["actual_start_at"] and not segment["actual_end_at"]]
            ch.test("awaiting_receipt_has_booked_future_job",bool(planned) and min(segment["booked_start_at"][:10] for segment in planned)>CUTOFF,ident)
            if planned:
                booked_start = min(segment["booked_start_at"][:10] for segment in planned)
                ro = ros[r["ro_id"]]
                ch.test("awaiting_receipt_po_eta_before_booked_job_before_expected_delivery",any(po["expected_receipt_date"]<=booked_start<=ro["expected_delivery_date"] for po in matching),f"{ident}: booked_start={booked_start}; expected_delivery={ro['expected_delivery_date']}")

    def event_coverage(self):
        for key in self.gl_event:
            self.checks.test("every_gl_event_traced_to_source",key in self.expected_events,str(key))
        # GL cash is exactly mirrored by bank, with source references linked.
        bank_sources = {(r["source_id"],r["location_id"],r["posted_date"]):c(r["amount_usd"]) for r in self.rows("bank/statement")}
        self.checks.test("bank_source_location_date_unique",len(bank_sources)==len(self.rows("bank/statement")),"source identity for bank to GL matching")
        ledger_cash = defaultdict(int)
        for r in self.rows("accounting/general_ledger"):
            if r["account_code"]=="1000": ledger_cash[(r["source_id"],r["location_id"],r["journal_date"])] += c(r["debit_usd"])-c(r["credit_usd"])
        for key in set(bank_sources)|set(ledger_cash):
            self.checks.equal("every_bank_cash_event_to_gl_source",bank_sources.get(key,0),ledger_cash.get(key,0),str(key))

    def write(self):
        directory = self.root/"validation"
        directory.mkdir(exist_ok=True)
        for name,digest in self.input_hashes.items():
            self.checks.test("metadata_unchanged_during_validation",hashlib.sha256((self.root/"metadata"/name).read_bytes()).hexdigest()==digest,name)
        report = self.checks.rows()
        writecsv(directory/"validation_report.csv",report)
        accounts = {"bank_source_usd":"1000","processor_clearing_source_usd":"1010","noncard_clearing_source_usd":"1020","ar_source_usd":"1100","inventory_source_usd":"1200","wip_source_usd":"1210","fixed_asset_cost_source_usd":"1500","accumulated_depreciation_source_usd":"1590","ap_source_usd":"2000","sales_tax_payable_source_usd":"2100","deposits_source_usd":"2200","payroll_payable_source_usd":"2300","debt_principal_source_usd":"2500"}
        negative_accounts = {"1590","2000","2100","2200","2300","2500"}
        controls = []
        for month in MONTHS:
            for loc in self.locations:
                source = self.controls[(month,loc)]
                row = {"month":month,"location_id":loc,"earned_net_sales_usd":usd(source.get("earned_net_sales_usd",0)),"payroll_earned_usd":usd(source.get("payroll_earned_usd",0)),"payroll_funded_usd":usd(source.get("payroll_funded_usd",0))}
                for field,account in accounts.items():
                    row[field] = usd(source.get(field,0))
                    row["gl"+account+"_balance_usd"] = usd((-1 if account in negative_accounts else 1)*self.closing[(month,loc,account)])
                    row["gl"+account+"_difference_usd"] = usd(source.get(field,0)-(-1 if account in negative_accounts else 1)*self.closing[(month,loc,account)])
                row["gl_period_debits_usd"] = usd(sum(self.debits[(month,loc,a)] for a in self.idx("accounting/chart_of_accounts")))
                row["gl_period_credits_usd"] = usd(sum(self.credits[(month,loc,a)] for a in self.idx("accounting/chart_of_accounts")))
                row["net_income_usd"] = usd(-sum(self.activity[(month,loc,a)] for a,r in self.idx("accounting/chart_of_accounts").items() if r["account_type"] in {"revenue","contra_revenue","expense","contra_expense"}))
                controls.append(row)
        writecsv(directory/"location_monthly_control_totals.csv",controls)
        company = []
        for month in MONTHS:
            rows = [r for r in controls if r["month"]==month]
            row = {"month":month}
            for field in controls[0]:
                if field not in {"month","location_id"}: row[field]=usd(sum(c(r[field]) for r in rows))
            company.append(row)
        writecsv(directory/"monthly_control_totals.csv",company)
        failed = [r for r in report if r["status"]=="FAIL"]
        summary = {"status":"PASS" if not failed else "FAIL","independence":"Standalone Python standard library; rereads physical CSV files plus manifest and schema; does not import or execute generator.","input_metadata_sha256":self.input_hashes,"verifier_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"history_start":START,"actual_cutoff":CUTOFF,"logical_tables":len(self.tables),"source_csv_rows":sum(map(len,self.tables.values())),"checks":len(report),"evaluated_assertions":sum(r["evaluated"] for r in report),"failed_checks":len(failed),"failed_assertions":sum(r["failures"] for r in failed),"company_control_months":len(company),"location_control_rows":len(controls),"monetary_policy":"Decimal to integer cents; exact reconciliation. HALF_UP only for explicitly rounded line tax, line price, FIFO partial lot, payroll, depreciation and contractual interest. Book hours may exceed physical clock hours. Management allocations are not GL postings.","date_policy":self.date_policy,"scenario_evidence":self.scenario_results,"failures":failed}
        (directory/"validation_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        print(json.dumps({k:summary[k] for k in ["status","checks","evaluated_assertions","failed_checks","failed_assertions","company_control_months","location_control_rows"]}),flush=True)
        for failure in failed:
            print(f"FAIL {failure['check_name']} ({failure['failures']}): {failure['examples']}",flush=True)
        return 1 if failed else 0

    def run(self):
        self.load()
        for phase in [self.dates,self.ledger,self.shop,self.scheduling,self.inventory,self.vehicles_bays_and_parts_bridge,self.purchasing,self.billing,self.ap,self.payroll,self.processor_and_bank,self.fixed_assets_tax_and_debt,self.marketing_shared_and_planning,self.contract_forecast_inputs,self.special_order_availability,self.scenario_evidence,self.event_coverage]:
            phase()
            failures = [(k,v["failures"],v["examples"][:2]) for k,v in self.checks.items.items() if v["status"]=="FAIL"]
            if failures: print(f"After {phase.__name__}: {json.dumps(failures)}",flush=True)
        return self.write()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    script = Path(__file__).resolve()
    workspace_default = script.parents[1]/"outputs/cedar_bend_auto_data"
    default_root = next((p for p in [script.parent,script.parent.parent,workspace_default]
                         if (p/"metadata/table_schemas.json").exists()),workspace_default)
    parser.add_argument("--root",type=Path,default=default_root)
    arguments = parser.parse_args()
    audit = Audit(arguments.root.resolve())
    try:
        result = audit.run()
    except (OSError,ValueError,KeyError,csv.Error) as error:
        audit.checks.test("audit_execution_error",False,f"{type(error).__name__}: {error}")
        directory = audit.root/"validation"
        directory.mkdir(parents=True,exist_ok=True)
        writecsv(directory/"validation_report.csv",audit.checks.rows())
        (directory/"validation_summary.json").write_text(json.dumps({"status":"FAIL","error":f"{type(error).__name__}: {error}","checks":audit.checks.rows()},indent=2),encoding="utf-8")
        print(f"AUDIT FAILED: {type(error).__name__}: {error}",file=sys.stderr,flush=True)
        result = 1
    sys.exit(result)




