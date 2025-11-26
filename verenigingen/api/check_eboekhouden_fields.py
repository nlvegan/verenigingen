#!/usr/bin/env python3

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def check_eboekhouden_fields() -> OperationResult[Dict[str, Any]]:
    """Check if E-Boekhouden custom fields exist"""
    try:
        print("Testing E-Boekhouden custom fields...")

        # Check if fields exist
        fields_to_check = [
            ("Journal Entry", "eboekhouden_mutation_nr"),
            ("Journal Entry", "eboekhouden_relation_code"),
            ("Journal Entry", "eboekhouden_invoice_number"),
            ("Journal Entry", "eboekhouden_main_ledger_id"),
            ("Journal Entry", "eboekhouden_mutation_type"),
            ("Sales Invoice", "eboekhouden_mutation_nr"),
            ("Sales Invoice", "eboekhouden_invoice_number"),
            ("Purchase Invoice", "eboekhouden_mutation_nr"),
            ("Purchase Invoice", "eboekhouden_invoice_number"),
            ("Payment Entry", "eboekhouden_mutation_nr"),
            ("Payment Entry", "eboekhouden_mutation_type"),
            ("Customer", "eboekhouden_relation_code"),
            ("Supplier", "eboekhouden_relation_code"),
            ("Account", "eboekhouden_grootboek_nummer"),
        ]

        results = []
        for doctype, fieldname in fields_to_check:
            exists = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})
            results.append((doctype, fieldname, "EXISTS" if exists else "MISSING"))
            status = "✅ EXISTS" if exists else "❌ MISSING"
            print(f"{doctype}.{fieldname}: {status}")

        missing_count = len([r for r in results if r[2] == "MISSING"])
        total_count = len(results)
        existing_count = total_count - missing_count

        print(f"\n📊 Summary: {existing_count}/{total_count} fields exist, {missing_count} missing")

        if missing_count == 0:
            print("✅ All E-Boekhouden custom fields are properly created!")
            return OperationResult.ok({"results": results}, message=_("All E-Boekhouden custom fields exist"))
        else:
            print("⚠️ Some E-Boekhouden custom fields are missing")
            missing_fields = [(dt, fn) for dt, fn, status in results if status == "MISSING"]

            frappe.log_error(
                title=_("E-Boekhouden Fields Missing"),
                message=_("{0} E-Boekhouden custom fields are missing: {1}").format(
                    missing_count, ", ".join([f"{dt}.{fn}" for dt, fn in missing_fields])
                ),
            )

            return OperationResult.fail(
                message=_("{0} E-Boekhouden fields missing").format(missing_count),
                data={"missing_fields": missing_fields, "results": results},
            )

    except Exception as e:
        frappe.log_error(
            title=_("E-Boekhouden Field Check Failed"),
            message=f"{_('Error checking E-Boekhouden custom fields')}: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to check E-Boekhouden custom fields: {0}").format(str(e)), exception=e
        )
