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

from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
    prepare_background_import,
    run_csv_validation,
)
from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateRow,
    ProcuriosMandateValidator,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@dataclass
class _Caches:
    """Pre-built lookup tables — populated once before the per-row loop."""

    procurios_id_to_member: Dict[str, str] = field(default_factory=dict)
    existing_mandate_by_id: Dict[str, Dict] = field(default_factory=dict)
    members_with_active_mandate: Set[str] = field(default_factory=set)
    # Procurios IDs that map to more than one Member. They are dropped from
    # `procurios_id_to_member`; any row referencing one is skipped as
    # `ambiguous_member` rather than silently assigned to whichever Member
    # the query returned last.
    ambiguous_procurios_ids: Set[str] = field(default_factory=set)
    # Per-member count of currently-active mandates. Maintained in-loop so the
    # cancellation path can decide whether a member still has *any* active
    # mandate without re-querying the DB.
    member_to_active_count: Dict[str, int] = field(default_factory=dict)


class ProcuriosMandateImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen_payments.doctype.procurios_mandate_import."
        "procurios_mandate_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosMandateValidator:
        # Cache slot is `_validator_instance` (single underscore) to match
        # the BaseCSVImport name-mangling-safe pattern. See base class
        # docstring + TestPropertyCacheHits.
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosMandateValidator()
        return self._validator_instance

    # ---- validate / preview -------------------------------------------

    def _validate_and_preview_csv(self) -> None:
        """Read the CSV, check shape, build a preview, set status."""
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                mark_import_failed(self, "CSV file is empty or could not be read")
                return

            headers = list(csv_data[0].keys())
            missing = self._validator.check_required_columns(headers)
            if missing:
                mark_import_failed(self, "Missing required columns: " + ", ".join(missing))
                return

            mapped, errors, filtered_old = self._validator.validate_and_map(csv_data)

            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))

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
            mark_import_failed(self, str(e))
            raise

    # ---- caches -------------------------------------------------------

    def _build_caches(self, csv_mandate_ids: Optional[Set[str]] = None) -> _Caches:
        """Build all lookup caches with one query each.

        Designed for a few thousand rows: each query is well-indexed and
        loads only the fields needed for the per-row decisions.

        Args:
            csv_mandate_ids: If provided, the existing-mandate cache only
                loads SEPA Mandates whose mandate_id is in the CSV OR whose
                status is Active. This keeps the cache bounded by
                (#csv_rows + #active_mandates) instead of the full historical
                SEPA Mandate count. Callers that don't have the CSV-id set
                available (e.g. tests) can omit it and accept the full scan.
        """
        caches = _Caches()

        # Member.procurios_id is a plain Data field without a unique
        # constraint. If two Members share the same procurios_id, neither
        # can be matched unambiguously — drop the id from the lookup and
        # remember it so we can give a clear skip reason instead of a
        # silent misassignment.
        for m in frappe.get_all(
            "Member",
            filters={"procurios_id": ["!=", ""]},
            fields=["name", "procurios_id"],
        ):
            if not m.procurios_id:
                continue
            if m.procurios_id in caches.ambiguous_procurios_ids:
                continue
            if m.procurios_id in caches.procurios_id_to_member:
                # Second hit: mark ambiguous and drop the earlier entry.
                caches.ambiguous_procurios_ids.add(m.procurios_id)
                caches.procurios_id_to_member.pop(m.procurios_id, None)
                continue
            caches.procurios_id_to_member[m.procurios_id] = m.name

        if csv_mandate_ids:
            # OR(status=Active, mandate_id in csv_ids): bound the scan by
            # what the per-row decisions need, not the full historical
            # mandate count. Frappe's filter dict can't express OR across
            # fields directly, so do two filtered queries and de-dup.
            sepa_rows = frappe.get_all(
                "SEPA Mandate",
                filters={"status": "Active"},
                fields=["name", "mandate_id", "status", "cancelled_date", "member", "used_for_memberships"],
            )
            seen_names = {r.name for r in sepa_rows}
            csv_matches = frappe.get_all(
                "SEPA Mandate",
                filters={"mandate_id": ["in", list(csv_mandate_ids)]},
                fields=["name", "mandate_id", "status", "cancelled_date", "member", "used_for_memberships"],
            )
            for r in csv_matches:
                if r.name not in seen_names:
                    sepa_rows.append(r)
                    seen_names.add(r.name)
        else:
            sepa_rows = frappe.get_all(
                "SEPA Mandate",
                fields=["name", "mandate_id", "status", "cancelled_date", "member", "used_for_memberships"],
            )

        for sm in sepa_rows:
            if sm.mandate_id:
                caches.existing_mandate_by_id[sm.mandate_id] = {
                    "name": sm.name,
                    "status": sm.status,
                    "cancelled_date": sm.cancelled_date,
                    "member": sm.member,
                }
                # Membership mandates only (#605). `_create_mandate` inserts
                # `used_for_memberships = 1`, so that is the mandate whose presence
                # is a conflict with what this import creates. Counting a donation
                # mandate here skipped the member's imported MEMBERSHIP mandate as
                # a conflict and left them with none -- and every collection path
                # has resolved mandates by purpose since #597.
                if sm.status == "Active" and sm.member and sm.used_for_memberships:
                    caches.members_with_active_mandate.add(sm.member)
                    caches.member_to_active_count[sm.member] = (
                        caches.member_to_active_count.get(sm.member, 0) + 1
                    )

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
            if row.debiteur_id in caches.ambiguous_procurios_ids:
                skip_counters["ambiguous_member"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"procurios_id={row.debiteur_id} matches multiple Members; "
                    f"cannot import unambiguously"
                )
                return ("skipped", "")

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
            caches.member_to_active_count[member_name] = caches.member_to_active_count.get(member_name, 0) + 1

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
        # Only decrement the active-count if the existing mandate was active
        # before this update; cancelling an already-cancelled mandate is a
        # no-op for the conflict-detection invariant.
        was_active = existing.get("status") == "Active"

        mandate = frappe.get_doc("SEPA Mandate", existing["name"])
        mandate.cancelled_date = row.cancelled_date
        mandate.status = "Cancelled"
        # Security: see _create_mandate — admin-submitted CSV, bulk background job.
        mandate.flags.ignore_permissions = True
        mandate.save()

        # Cache refresh via the in-memory active-count, so the per-row loop
        # stays free of DB queries on the update path.
        member = existing.get("member")
        if was_active and member:
            remaining = caches.member_to_active_count.get(member, 0) - 1
            if remaining <= 0:
                caches.member_to_active_count.pop(member, None)
                caches.members_with_active_mandate.discard(member)
            else:
                caches.member_to_active_count[member] = remaining

        existing["status"] = mandate.status
        existing["cancelled_date"] = mandate.cancelled_date

        return ("updated", mandate.name)

    # ---- finalize -----------------------------------------------------

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,  # noqa: ARG002  — processor passes; we derive from skip_counters
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
        # mandates_skipped is derived from skip_counters (which the per-row
        # processor increments AND which is pre-seeded with validator-stage
        # row-mapping errors) plus filtered-old-cancelled (validator-stage
        # filter that never reaches the processor). Deriving from
        # skip_counters guarantees consistency with skipped_summary.
        counters = dict(skip_counters or {})
        self.mandates_skipped = sum(counters.values()) + filtered_old_cancelled
        self.import_status = "Completed"

        if error_log:
            self.error_log = format_truncated_error_log(error_log)

        summary_counts = dict(counters)
        summary_counts.setdefault("filtered_old_cancelled", 0)
        summary_counts["filtered_old_cancelled"] += filtered_old_cancelled
        self.skipped_summary = "\n".join(
            f"{k}: {summary_counts.get(k, 0)}"
            for k in (
                "filtered_old_cancelled",
                "no_member",
                "ambiguous_member",
                "duplicate",
                "conflict",
                "error",
            )
        )

        # Security: Background job updating its own import status document; the
        # whole flow is gated by submit permission on Procurios Mandate Import.
        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    return run_csv_validation("Procurios Mandate Import", import_doc_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: validate, build caches, process, finalize."""
    import traceback

    from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor

    doc, test_mode = prepare_background_import("Procurios Mandate Import", import_doc_name, test_mode)
    try:
        csv_data = doc._read_csv_file()
        headers = list(csv_data[0].keys()) if csv_data else []
        missing = doc._validator.check_required_columns(headers)
        if missing:
            mark_import_failed(doc, "Missing required columns: " + ", ".join(missing))
            return

        mapped, validator_errors, filtered_old = doc._validator.validate_and_map(csv_data)
        if not mapped:
            # Two distinct empty-mapped cases:
            #  - All rows filtered out by the 12-month cutoff (no errors). That's
            #    a legitimate Completed outcome — the CSV is fine, the business
            #    rule just had nothing to import. Route through the normal
            #    finalize path so the per-reason summary format stays in one
            #    place (no inline literal that can drift).
            #  - Genuine failures or genuinely empty file. Report as Failed.
            if filtered_old > 0 and not validator_errors:
                empty_skip_counters = {
                    "no_member": 0,
                    "ambiguous_member": 0,
                    "duplicate": 0,
                    "conflict": 0,
                    "error": 0,
                }
                doc._finalize_import_results(
                    created_count=0,
                    updated_count=0,
                    skipped_count=0,
                    error_log=[],
                    skip_counters=empty_skip_counters,
                    filtered_old_cancelled=filtered_old,
                )
                return
            mark_import_failed(
                doc,
                format_truncated_error_log(validator_errors)
                if validator_errors
                else "No valid rows to import",
            )
            return

        if test_mode:
            mapped = mapped[:25]

        # Pass the CSV's mandate_ids so the existing-mandate query stays
        # bounded by (#csv_rows + #active_mandates) instead of scanning
        # every historical SEPA Mandate.
        csv_mandate_ids = {row.mandate_id for row in mapped if row.mandate_id}
        caches = doc._build_caches(csv_mandate_ids=csv_mandate_ids)
        # Validator-stage row-mapping errors (bad dates, missing required fields)
        # are real per-row failures: count them toward `error` so the
        # skipped_summary stays consistent with the row total.
        skip_counters = {
            "no_member": 0,
            "ambiguous_member": 0,
            "duplicate": 0,
            "conflict": 0,
            # Pre-seed `error` with the validator-stage mapping failures so
            # they're counted in skipped_summary and mandates_skipped, not
            # just logged into error_log.
            "error": len(validator_errors),
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
        # Our doctype uses mandates_* progress fields rather than the shared
        # processor's members_* default; override so the live progress fields
        # update during batches (otherwise they stay at 0 until finalize).
        processor.process_import(
            data_rows=mapped,
            process_row_callback=_row_callback,
            finalize_callback=_finalize,
            batch_size=50,
            batch_commit=True,
            progress_field_map={
                "created": "mandates_created",
                "updated": "mandates_updated",
                "skipped": "mandates_skipped",
            },
        )

    except Exception:
        mark_import_failed(doc, traceback.format_exc())
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
