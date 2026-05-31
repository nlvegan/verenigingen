# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Procurios SEPA Mandate Import controller.

Imports SEPA mandates from a Procurios CSV export. Matches Debiteur ID
to existing Member.procurios_id. Per-row business rules: skip
old-cancelled (>12mo), skip-no-member, duplicate (update if cancelled,
otherwise skip), conflict (active rows only, member with another active
mandate is skipped), else create.

Design: docs/plans/2026-05-27-procurios-mandate-import-design.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateRow,
    ProcuriosMandateValidator,
)
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.error_handling import sanitize_error_for_audit


@dataclass
class _Caches:
    """Pre-built lookup tables — populated once before the per-row loop."""

    procurios_id_to_member: Dict[str, str] = field(default_factory=dict)
    existing_mandate_by_id: Dict[str, Dict] = field(default_factory=dict)
    members_with_active_mandate: Set[str] = field(default_factory=set)


class ProcuriosMandateImport(Document):
    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "__parser"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self.__parser = SecureCSVParser(encoding=encoding, delimiter=self.csv_delimiter)
        return self.__parser

    @property
    def _validator(self) -> ProcuriosMandateValidator:
        if not hasattr(self, "__validator"):
            self.__validator = ProcuriosMandateValidator()
        return self.__validator

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    # ---- validate / preview -------------------------------------------

    def _read_csv_file(self) -> List[Dict]:
        return self._parser.read_csv_file(self.csv_file)

    def _validate_and_preview_csv(self) -> None:
        """Read the CSV, check shape, build a preview, set status."""
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return

            headers = list(csv_data[0].keys())
            missing = self._validator.check_required_columns(headers)
            if missing:
                self.db_set("import_status", "Failed")
                self.db_set(
                    "error_log",
                    "Missing required columns: " + ", ".join(missing),
                )
                frappe.db.commit()
                return

            mapped, errors, filtered_old = self._validator.validate_and_map(csv_data)

            if errors:
                self.db_set("error_log", "\n".join(errors[:50]))

            if mapped:
                preview = [
                    {
                        "mandate_id": m.mandate_id,
                        "iban": m.iban,
                        "account_holder_name": m.account_holder_name,
                        "debiteur_id": m.debiteur_id,
                        "debiteur_naam": m.debiteur_naam,
                        "sign_date": m.sign_date,
                        "cancelled_date": m.cancelled_date,
                        "mandate_type": m.mandate_type,
                        "is_cancelled": m.is_cancelled,
                    }
                    for m in mapped[:5]
                ]
                self.db_set("preview_data", json.dumps(preview, indent=2, default=str))

            self.db_set("total_rows", len(csv_data))
            self.db_set(
                "descriptive_name",
                f"Procurios mandate import — {len(csv_data)} rows "
                f"({filtered_old} cancelled outside cutoff)",
            )

            if mapped:
                self.db_set("import_status", "Ready for Import")
            else:
                self.db_set("import_status", "Failed")
                if not errors:
                    self.db_set("error_log", "No valid rows found in CSV")

            frappe.db.commit()

        except Exception as e:
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise

    # ---- caches -------------------------------------------------------

    def _build_caches(self) -> _Caches:
        """Build all three lookup caches with one query each.

        Designed for a few thousand rows: each query is well-indexed and
        loads only the fields needed for the per-row decisions.
        """
        caches = _Caches()

        for m in frappe.get_all(
            "Member",
            filters={"procurios_id": ["!=", ""]},
            fields=["name", "procurios_id"],
        ):
            if m.procurios_id:
                caches.procurios_id_to_member[m.procurios_id] = m.name

        for sm in frappe.get_all(
            "SEPA Mandate",
            fields=["name", "mandate_id", "status", "cancelled_date", "member"],
        ):
            if sm.mandate_id:
                caches.existing_mandate_by_id[sm.mandate_id] = {
                    "name": sm.name,
                    "status": sm.status,
                    "cancelled_date": sm.cancelled_date,
                    "member": sm.member,
                }
                if sm.status == "Active" and sm.member:
                    caches.members_with_active_mandate.add(sm.member)

        return caches

    # ---- per-row processor -------------------------------------------

    def _process_single_row(
        self,
        row: ProcuriosMandateRow,
        error_log: List[str],
        caches: _Caches,
        skip_counters: Dict[str, int],
    ) -> Tuple[str, str]:
        """Process one mapped row. Returns (status, mandate_name).

        Status is one of: "created", "updated", "skipped". On skip, the
        relevant counter in `skip_counters` is incremented. Per-row
        exceptions are caught, logged, and counted under "error" — they
        never propagate.
        """
        try:
            # 1. Member match
            member_name = caches.procurios_id_to_member.get(row.debiteur_id)
            if not member_name:
                skip_counters["no_member"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"no Member with procurios_id={row.debiteur_id}"
                )
                return ("skipped", "")

            # 2. Duplicate check
            existing = caches.existing_mandate_by_id.get(row.mandate_id)
            if existing:
                if row.is_cancelled:
                    # Update path: refresh cancelled_date on the existing mandate.
                    return self._update_cancellation(existing, row, caches)
                skip_counters["duplicate"] += 1
                return ("skipped", "")

            # 3. Conflict check (active rows only)
            if not row.is_cancelled and member_name in caches.members_with_active_mandate:
                skip_counters["conflict"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"member {member_name} already has an active mandate"
                )
                return ("skipped", "")

            # 4. Create
            return self._create_mandate(row, member_name, caches)

        except Exception as e:
            skip_counters["error"] += 1
            sanitized = sanitize_error_for_audit(str(e))
            error_log.append(f"Row {row.row_number} ({row.debiteur_naam}): {sanitized}")
            return ("skipped", "")

    def _create_mandate(
        self,
        row: ProcuriosMandateRow,
        member_name: str,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Insert a new SEPA Mandate and update caches."""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": row.mandate_id,
                "member": member_name,
                "account_holder_name": row.account_holder_name,
                "iban": row.iban,
                "sign_date": row.sign_date,
                "cancelled_date": row.cancelled_date,  # blank for active, set for cancelled
                "status": "Cancelled" if row.is_cancelled else "Active",
                "mandate_type": row.mandate_type,
                "scheme": "SEPA",
                "used_for_memberships": 1,
                "notes": row.notes,
            }
        )
        # Security: Background bulk import driven by an admin-submitted, validated CSV.
        # The import DocType itself is restricted to System Manager / Verenigingen
        # Administrator; per-row mandate inserts run with elevated rights to avoid
        # re-checking the admin role for every one of potentially thousands of rows.
        mandate.flags.ignore_permissions = True
        mandate.insert()

        # Cache updates so subsequent rows see the new state.
        caches.existing_mandate_by_id[row.mandate_id] = {
            "name": mandate.name,
            "status": mandate.status,
            "cancelled_date": mandate.cancelled_date,
            "member": member_name,
        }
        if mandate.status == "Active":
            caches.members_with_active_mandate.add(member_name)

        return ("created", mandate.name)

    def _update_cancellation(
        self,
        existing: Dict,
        row: ProcuriosMandateRow,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Mark an existing mandate as cancelled, refreshing cancelled_date.

        Uses frappe.get_doc + save so the lifecycle service flips status
        to Cancelled. ignore_permissions because the bulk import runs in
        a background job.
        """
        mandate = frappe.get_doc("SEPA Mandate", existing["name"])
        mandate.cancelled_date = row.cancelled_date
        mandate.status = "Cancelled"
        # Security: see _create_mandate — admin-submitted CSV, bulk background job.
        mandate.flags.ignore_permissions = True
        mandate.save()

        # Cache refresh: the member may no longer have an active mandate.
        if existing.get("member") in caches.members_with_active_mandate:
            still_active = frappe.db.exists(
                "SEPA Mandate",
                {"member": existing["member"], "status": "Active"},
            )
            if not still_active:
                caches.members_with_active_mandate.discard(existing["member"])

        existing["status"] = mandate.status
        existing["cancelled_date"] = mandate.cancelled_date

        return ("updated", mandate.name)

    # ---- submission ---------------------------------------------------

    def on_submit(self):
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method=(
                "verenigingen.verenigingen_payments.doctype.procurios_mandate_import."
                "procurios_mandate_import.process_import_background"
            ),
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=bool(self.test_mode),
            now=False,
        )

    # ---- finalize -----------------------------------------------------

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_log: List[str],
        _created_records=None,
        _updated_records=None,
        _skipped_records=None,
        skip_counters: Optional[Dict[str, int]] = None,
        filtered_old_cancelled: int = 0,
    ) -> None:
        """Write final counters + bounded error log + per-reason summary."""
        self.reload()
        self.mandates_created = created_count
        self.mandates_updated = updated_count
        # mandates_skipped includes filtered-old (which never reaches the processor)
        self.mandates_skipped = skipped_count + filtered_old_cancelled
        self.import_status = "Completed"

        if error_log:
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"

        summary_counts = dict(skip_counters or {})
        summary_counts.setdefault("filtered_old_cancelled", 0)
        summary_counts["filtered_old_cancelled"] += filtered_old_cancelled
        self.skipped_summary = "\n".join(
            f"{k}: {summary_counts.get(k, 0)}"
            for k in ("filtered_old_cancelled", "no_member", "duplicate", "conflict", "error")
        )

        # Security: Background job updating its own import status document; the
        # whole flow is gated by submit permission on Procurios Mandate Import.
        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    doc = frappe.get_doc("Procurios Mandate Import", import_doc_name)
    try:
        doc._validate_and_preview_csv()
        doc.reload()
        return {
            "status": "success" if doc.import_status == "Ready for Import" else "error",
            "message": f"Validation complete. Status: {doc.import_status}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": sanitize_error_for_audit(str(e)),
        }


@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """Background job: validate, build caches, process, finalize."""
    import traceback

    from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor

    frappe.flags.in_background_job = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios Mandate Import", import_doc_name)
    try:
        csv_data = doc._read_csv_file()
        headers = list(csv_data[0].keys()) if csv_data else []
        missing = doc._validator.check_required_columns(headers)
        if missing:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "Missing required columns: " + ", ".join(missing))
            frappe.db.commit()
            return

        mapped, validator_errors, filtered_old = doc._validator.validate_and_map(csv_data)
        if not mapped:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "No valid rows to import")
            frappe.db.commit()
            return

        if test_mode:
            mapped = mapped[:25]

        caches = doc._build_caches()
        skip_counters = {
            "no_member": 0,
            "duplicate": 0,
            "conflict": 0,
            "error": 0,
        }
        seeded_errors = list(validator_errors)

        def _row_callback(mapped_row, error_log_list):
            return doc._process_single_row(mapped_row, error_log_list, caches, skip_counters)

        def _finalize(created, updated, skipped, error_log, *records):
            # Prepend validator-stage errors (row-mapping errors that happened
            # before the row reached the processor) so both kinds land in the
            # final error_log.
            combined = seeded_errors + list(error_log)
            doc._finalize_import_results(
                created,
                updated,
                skipped,
                combined,
                *records,
                skip_counters=skip_counters,
                filtered_old_cancelled=filtered_old,
            )

        processor = CSVImportBackgroundProcessor(import_doc_name, "Procurios Mandate Import")
        processor.load_import_doc()
        processor.process_import(
            data_rows=mapped,
            process_row_callback=_row_callback,
            finalize_callback=_finalize,
            batch_size=50,
            batch_commit=True,
        )

    except Exception:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
