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
from typing import Dict, List

import frappe

from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
)
from verenigingen.utils.csv.procurios_membership_validator import (
    ProcuriosMembershipValidator,
)

# dues-schedule template settings fields (checked on validate)
DUES_TEMPLATE_SETTINGS = [
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
]


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
            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))

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
            if missing_templates:
                self.db_set(
                    "error_log",
                    "WARNING: Verenigingen Settings missing dues-schedule templates: "
                    + ", ".join(missing_templates)
                    + " — active memberships with these payment periods will fail.",
                )

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
