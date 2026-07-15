# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Procurios membership import controller.

Imports membership contracts from a Procurios CSV export. Matches
Debiteur Id -> Member.procurios_id. Active rows create a live Membership
+ dues schedule via MembershipImportService; cancelled/expired rows are
created as historical records. Idempotent on Membership.procurios_membership_id.

Design: docs/superpowers/specs/2026-07-15-procurios-membership-mandate-import-design.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import frappe

from verenigingen.services.csv_import.membership_import_service import (
    get_membership_import_service,
)
from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
    prepare_background_import,
    run_csv_validation,
)
from verenigingen.utils.csv.procurios_membership_validator import (
    ProcuriosMembershipRow,
    ProcuriosMembershipValidator,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.security.api_security_framework import OperationType, critical_api

# dues-schedule template settings fields (checked on validate)
DUES_TEMPLATE_SETTINGS = [
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
]

# Per-reason skip counters, in the order they appear in skipped_summary.
_SKIP_REASONS = ("no_member", "ambiguous_member", "duplicate", "already_active", "error")


@dataclass
class _Caches:
    """Pre-built lookup tables — populated once before the per-row loop."""

    # procurios_id -> Member.name (ambiguous ids dropped, see _build_caches).
    procurios_id_to_member: Dict[str, str] = field(default_factory=dict)
    # procurios_ids that map to more than one Member; rows referencing one are
    # skipped as `ambiguous_member` rather than silently misassigned.
    ambiguous_procurios_ids: Set[str] = field(default_factory=set)
    # Set of Membership.procurios_membership_id already imported (idempotency).
    existing_membership_ids: Set[str] = field(default_factory=set)
    # Members that currently hold a submitted, Active Membership.
    members_with_active_membership: Set[str] = field(default_factory=set)
    # procurios_type -> Membership Type name (completed mapping).
    type_mapping: Dict[str, str] = field(default_factory=dict)


class ProcuriosMembershipImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen.doctype.procurios_membership_import."
        "procurios_membership_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosMembershipValidator:
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosMembershipValidator()
        return self._validator_instance

    # ---- validate / preview ----

    def _validate_and_preview_csv(self) -> None:
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

            self._sync_type_mapping(self._validator.extract_membership_types(csv_data))

            mapped, errors = self._validator.validate_and_map(csv_data)
            row_error_log = format_truncated_error_log(errors) if errors else ""

            preview = [
                {
                    "debiteur_id": r.debiteur_id,
                    "debiteur_naam": r.debiteur_naam,
                    "type": r.procurios_type,
                    "status": r.status,
                    "start_date": r.start_date,
                    "dues_rate": r.dues_rate,
                }
                for r in mapped[:5]
            ]
            self.db_set("preview_data", json.dumps(preview, indent=2, default=str))
            self.db_set("total_rows", len(csv_data))
            self.db_set("descriptive_name", f"Procurios membership import - {len(csv_data)} rows")

            missing_templates = self._missing_dues_templates()
            dues_warning_log = (
                "WARNING: Verenigingen Settings missing dues-schedule templates: "
                + ", ".join(missing_templates)
                + " — active memberships with these payment periods will fail."
                if missing_templates
                else ""
            )

            combined_error_log = "\n\n".join(filter(None, [row_error_log, dues_warning_log]))
            if combined_error_log:
                self.db_set("error_log", combined_error_log)

            self.db_set("import_status", "Ready for Import" if mapped else "Failed")
            if not mapped and not errors:
                self.db_set("error_log", "No valid rows found in CSV")
            frappe.db.commit()
        except Exception as e:
            mark_import_failed(self, str(e))
            raise

    def _sync_type_mapping(self, procurios_types: List[str]) -> None:
        """Upsert distinct Procurios Type values into membership_type_mapping,
        preserving any membership_type already chosen."""
        existing = {r.procurios_type: r.membership_type for r in (self.membership_type_mapping or [])}
        self.set("membership_type_mapping", [])
        for ptype in procurios_types:
            self.append(
                "membership_type_mapping",
                {"procurios_type": ptype, "membership_type": existing.get(ptype)},
            )
        # Security: Called from `_validate_and_preview_csv`, which only runs on
        # a doc already gated by the DocType's own create/write permissions
        # (System Manager / Verenigingen Administrator). The bypass here just
        # avoids re-checking write permission on every validate-stage save of
        # the doc's own child table (validate stage; doc not submitted yet).
        self.save(ignore_permissions=True)

    def _get_type_mapping(self) -> Dict[str, str]:
        return {
            r.procurios_type: r.membership_type
            for r in (self.membership_type_mapping or [])
            if r.procurios_type and r.membership_type
        }

    def _incomplete_mapping_types(self) -> List[str]:
        return [
            r.procurios_type
            for r in (self.membership_type_mapping or [])
            if r.procurios_type and not r.membership_type
        ]

    def _missing_dues_templates(self) -> List[str]:
        settings = frappe.get_single("Verenigingen Settings")
        return [f for f in DUES_TEMPLATE_SETTINGS if not settings.get(f)]

    # ---- caches ----

    def _build_caches(self) -> _Caches:
        """Build all lookup caches with one query each."""
        caches = _Caches()

        # Member.procurios_id is a plain Data field without a unique
        # constraint. If two Members share the same procurios_id, neither can
        # be matched unambiguously — drop the id and remember it so the row
        # gets a clear skip reason instead of a silent misassignment.
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
                caches.ambiguous_procurios_ids.add(m.procurios_id)
                caches.procurios_id_to_member.pop(m.procurios_id, None)
                continue
            caches.procurios_id_to_member[m.procurios_id] = m.name

        caches.existing_membership_ids = set(
            frappe.get_all(
                "Membership",
                filters={"procurios_membership_id": ["!=", ""]},
                pluck="procurios_membership_id",
            )
        )
        caches.members_with_active_membership = set(
            frappe.get_all(
                "Membership",
                filters={"status": "Active", "docstatus": 1},
                pluck="member",
            )
        )
        caches.type_mapping = self._get_type_mapping()
        return caches

    # ---- per-row processor ----

    def _process_single_member(
        self,
        row: ProcuriosMembershipRow,
        error_log: List[str],
        caches: _Caches,
        skip_counters: Dict[str, int],
    ) -> Tuple[str, str]:
        """Process one mapped row. Returns (status, membership_name).

        Status is "created" or "skipped". On skip, the relevant counter in
        `skip_counters` is incremented. Per-row exceptions are caught, logged,
        and counted under "error" — they never propagate.
        """
        try:
            # 1. Ambiguous member
            if row.debiteur_id in caches.ambiguous_procurios_ids:
                skip_counters["ambiguous_member"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"procurios_id={row.debiteur_id} matches multiple Members; "
                    f"cannot import unambiguously"
                )
                return ("skipped", "")

            # 2. No matching member
            member_name = caches.procurios_id_to_member.get(row.debiteur_id)
            if not member_name:
                skip_counters["no_member"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"no Member with procurios_id={row.debiteur_id}"
                )
                return ("skipped", "")

            # 3. Duplicate (idempotency on procurios_membership_id)
            if row.procurios_membership_id in caches.existing_membership_ids:
                skip_counters["duplicate"] += 1
                return ("skipped", "")

            # 4. Already-active conflict (active rows only)
            if row.status == "Active" and member_name in caches.members_with_active_membership:
                skip_counters["already_active"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"member {member_name} already has an active membership"
                )
                return ("skipped", "")

            # 5. Create
            if row.status == "Active":
                return self._create_active_membership(row, member_name, caches)
            return self._create_historical_membership(row, member_name, caches)

        except Exception as e:
            skip_counters["error"] += 1
            sanitized = sanitize_error_for_audit(str(e))
            error_log.append(f"Row {row.row_number} ({row.debiteur_naam}): {sanitized}")
            return ("skipped", "")

    def _create_active_membership(
        self,
        row: ProcuriosMembershipRow,
        member_name: str,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Create a live Membership + dues schedule via MembershipImportService."""
        member_doc = frappe.get_doc("Member", member_name)
        row_data = {
            "member_id": row.debiteur_id,
            "membership_type": caches.type_mapping[row.procurios_type],
            "payment_period": row.payment_period,
            "member_since": row.start_date,
            "dues_rate": row.dues_rate,
        }
        membership_name = get_membership_import_service().create_membership_from_csv(member_doc, row_data)
        if not membership_name:
            # Service swallows creation failures (logged to Error Log) and
            # returns None. Surface it as a per-row error rather than a silent
            # created/skipped miscount.
            raise frappe.ValidationError(f"membership creation returned no result for member {member_name}")

        # Invariant: Step 4 (already_active skip) prevents reaching this for a
        # member who already holds an active Membership, so create_membership_from_csv's
        # advisory-lock double-check should not return a *pre-existing* membership
        # here. Guard defensively anyway: if it returned one already tagged with a
        # different procurios_membership_id, don't overwrite the tag or miscount it
        # as created — surface it as a per-row error instead.
        existing_tag = frappe.db.get_value("Membership", membership_name, "procurios_membership_id")
        if existing_tag and existing_tag != row.procurios_membership_id:
            raise frappe.ValidationError(
                f"membership {membership_name} already tagged with procurios_membership_id "
                f"'{existing_tag}'; refusing to retag as '{row.procurios_membership_id}'"
            )

        # Idempotency marker so re-imports skip this membership.
        frappe.db.set_value(
            "Membership",
            membership_name,
            "procurios_membership_id",
            row.procurios_membership_id,
            update_modified=False,
        )

        caches.existing_membership_ids.add(row.procurios_membership_id)
        caches.members_with_active_membership.add(member_name)
        return ("created", membership_name)

    def _create_historical_membership(
        self,
        row: ProcuriosMembershipRow,
        member_name: str,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Create a submitted historical Membership directly (no dues schedule).

        Elevate to Administrator for the insert/submit so
        `Membership.validate_dates`'s minimum-1-year rule (which only *throws*
        for non-System-Manager users) degrades to a warning.

        The final status is derived by `Membership.set_status` from the dates we
        provide — never set directly — so it must be steered per row type:

        - Cancelled: carry the historic `cancellation_date`; `set_status` checks
          it first (past → "Cancelled").
        - Expired: carry NO `cancellation_date`. `set_renewal_date` computes a
          past `renewal_date` from the historic `start_date` + type period, and
          `set_status` (reached only after the cancellation branch) → "Expired".

        `_is_csv_import` is deliberately NOT set on this historical path: that
        flag pushes `renewal_date` to today+period (future) to keep *active*
        imports Active, which would wrongly suppress the Expired status here.
        """
        membership_data = {
            "doctype": "Membership",
            "member": member_name,
            "membership_type": caches.type_mapping[row.procurios_type],
            "start_date": row.start_date,
            "procurios_membership_id": row.procurios_membership_id,
        }
        if row.status == "Cancelled":
            membership_data["cancellation_date"] = row.cancellation_date
            membership_data["cancellation_reason"] = "Imported from Procurios (historical)"

        original_user = frappe.session.user
        original_suppress = frappe.flags.get("suppress_grace_period_message")
        try:
            frappe.set_user("Administrator")
            frappe.flags.suppress_grace_period_message = True
            membership = frappe.get_doc(membership_data)
            # Security: Background bulk import driven by an admin-submitted,
            # validated CSV. The import DocType is gated to System Manager /
            # Verenigingen Administrator; per-row historical Membership inserts
            # run elevated to avoid re-checking the admin role for every row.
            membership.flags.ignore_permissions = True
            membership.flags.skip_dues_schedule_creation = True  # no billing for historical
            membership.insert()
            membership.submit()  # set_status -> Cancelled (cancellation_date) / Expired (past renewal_date)
        finally:
            frappe.set_user(original_user)
            # Reset the flag we set above so it does not leak True onto the rest
            # of the batch (other rows / callers rely on the default behaviour).
            frappe.flags.suppress_grace_period_message = original_suppress

        caches.existing_membership_ids.add(row.procurios_membership_id)
        return ("created", membership.name)

    # ---- finalize ----

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,  # noqa: ARG002 — processor passes; memberships have no update path
        skipped_count: int,  # noqa: ARG002 — derived from skip_counters for consistency
        error_log: List[str],
        _created_records=None,
        _updated_records=None,
        _skipped_records=None,
        skip_counters: Optional[Dict[str, int]] = None,
    ) -> None:
        """Write final counters + bounded error log + per-reason summary."""
        self.reload()
        counters = dict(skip_counters or {})
        self.memberships_created = created_count
        self.memberships_skipped = sum(counters.values())
        self.import_status = "Completed"

        if error_log:
            self.error_log = format_truncated_error_log(error_log)

        self.skipped_summary = "\n".join(f"{k}: {counters.get(k, 0)}" for k in _SKIP_REASONS)

        # Security: Background job updating its own import status document; the
        # whole flow is gated by submit permission on Procurios Membership Import.
        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    return run_csv_validation("Procurios Membership Import", import_doc_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: validate, build caches, process, finalize."""
    import traceback

    from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor

    doc, test_mode = prepare_background_import("Procurios Membership Import", import_doc_name, test_mode)
    try:
        csv_data = doc._read_csv_file()
        headers = list(csv_data[0].keys()) if csv_data else []
        missing = doc._validator.check_required_columns(headers)
        if missing:
            mark_import_failed(doc, "Missing required columns: " + ", ".join(missing))
            return

        # Enforce a complete membership-type mapping WITHOUT re-saving the child
        # table. On a submitted doc (the real UI flow submits before enqueuing
        # this job) membership_type_mapping is NOT allow_on_submit, so rebuilding
        # and saving it here would trip validate_update_after_submit and fail the
        # whole import. The mapping was already populated and persisted at VALIDATE
        # time (docstatus=0, in _validate_and_preview_csv). So instead of a
        # post-submit write, compare the CSV's distinct Types against the persisted,
        # fully-mapped rows and fail if any CSV Type has no membership_type.
        csv_types = doc._validator.extract_membership_types(csv_data)
        type_mapping = doc._get_type_mapping()  # {procurios_type: membership_type} for MAPPED rows only
        unmapped = [t for t in csv_types if t not in type_mapping]
        if unmapped:
            mark_import_failed(
                doc,
                "Complete the membership-type mapping before importing: " + ", ".join(unmapped),
            )
            return

        mapped, validator_errors = doc._validator.validate_and_map(csv_data)
        if not mapped:
            mark_import_failed(
                doc,
                (
                    format_truncated_error_log(validator_errors)
                    if validator_errors
                    else "No valid rows to import"
                ),
            )
            return

        if test_mode:
            mapped = mapped[:25]

        caches = doc._build_caches()
        # Validator-stage row-mapping errors (bad dates, missing required
        # fields) are real per-row failures: pre-seed `error` so they count
        # toward memberships_skipped and skipped_summary, not just error_log.
        skip_counters = {k: 0 for k in _SKIP_REASONS}
        skip_counters["error"] = len(validator_errors)
        seeded_errors = list(validator_errors)

        def _row_callback(mapped_row, error_log_list):
            return doc._process_single_member(mapped_row, error_log_list, caches, skip_counters)

        def _finalize(created, updated, skipped, error_log, *records):
            combined = seeded_errors + list(error_log)
            doc._finalize_import_results(
                created,
                updated,
                skipped,
                combined,
                *records,
                skip_counters=skip_counters,
            )

        processor = CSVImportBackgroundProcessor(import_doc_name, "Procurios Membership Import")
        processor.load_import_doc()
        processor.process_import(
            data_rows=mapped,
            process_row_callback=_row_callback,
            finalize_callback=_finalize,
            batch_size=50,
            batch_commit=True,
            progress_field_map={
                "created": "memberships_created",
                "skipped": "memberships_skipped",
            },
        )

    except Exception:
        mark_import_failed(doc, traceback.format_exc())
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
