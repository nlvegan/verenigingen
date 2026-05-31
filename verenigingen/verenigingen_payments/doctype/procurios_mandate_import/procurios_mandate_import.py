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
from typing import Dict, List

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateValidator,
)
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.error_handling import sanitize_error_for_audit


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
