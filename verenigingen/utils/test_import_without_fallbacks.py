#!/usr/bin/env python3
"""
Test import without fallbacks to expose mapping issues
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def test_import_without_fallbacks():
    """Test import with a small batch to identify mapping issues"""

    result = {
        "test_start": now_datetime(),
        "mutations_tested": 0,
        "successes": 0,
        "failures": [],
        "summary": {},
    }

    # Import the migration module and run a test import
    try:
        from vereiningen.utils.eboekhouden_rest_full_migration import (
            _get_default_company,
            start_full_rest_import,
        )

        # Get company
        # company = _get_default_company()
        # Create a test migration record
        test_migration = frappe.new_doc("E-Boekhouden Migration")
        test_migration.migration_type = "Full Import"
        test_migration.status = "In Progress"
        test_migration.import_method = "REST API"
        test_migration.mutation_limit = 10  # Just test 10 mutations
        test_migration.save()

        # Run import
        import_result = start_full_rest_import(test_migration.name)

        result["import_result"] = import_result
        result["mutations_tested"] = import_result.get("total_fetched", 0)
        result["successes"] = import_result.get("processed", 0)

        # Get the migration record for debug info
        # migration_doc = frappe.get_doc("E-Boekhouden Migration", test_migration.name)
        if migration_doc.debug_log:
            result["debug_log"] = migration_doc.debug_log

    except Exception as e:
        result["overall_error"] = str(e)
        import traceback

        result["traceback"] = traceback.format_exc()

    # Analyze failures by type
    if "import_result" in result and "debug_info" in result["import_result"]:
        debug_info = result["import_result"]["debug_info"]

        # Extract failure patterns
        failure_patterns = {
            "missing_bank_account": [],
            "missing_receivable_account": [],
            "missing_payable_account": [],
            "missing_customer": [],
            "missing_supplier": [],
            "missing_expense_account": [],
            "missing_income_account": [],
            "missing_ledger_mapping": [],
            "other": [],
        }

        for line in debug_info:
            if "ERROR" in line or "Failed" in line:
                result["failures"].append(line)

                # Categorize the failure
                if "bank account" in line.lower():
                    failure_patterns["missing_bank_account"].append(line)
                elif "receivable account" in line.lower():
                    failure_patterns["missing_receivable_account"].append(line)
                elif "payable account" in line.lower():
                    failure_patterns["missing_payable_account"].append(line)
                elif "customer" in line.lower() and "create" in line.lower():
                    failure_patterns["missing_customer"].append(line)
                elif "supplier" in line.lower() and "create" in line.lower():
                    failure_patterns["missing_supplier"].append(line)
                elif "expense account" in line.lower():
                    failure_patterns["missing_expense_account"].append(line)
                elif "income account" in line.lower():
                    failure_patterns["missing_income_account"].append(line)
                elif "ledger" in line.lower() and "mapping" in line.lower():
                    failure_patterns["missing_ledger_mapping"].append(line)
                else:
                    failure_patterns["other"].append(line)

        # Summarize failure patterns
        result["summary"] = {
            category: len(failures) for category, failures in failure_patterns.items() if failures
        }

        result["failure_patterns"] = {
            category: failures[:3]  # First 3 examples of each type
            for category, failures in failure_patterns.items()
            if failures
        }

    result["test_end"] = now_datetime()

    # Add recommendations
    recommendations = []
    if result["summary"]:
        if result["summary"].get("missing_bank_account"):
            recommendations.append("Configure bank account mappings in E-Boekhouden Ledger Mapping")
        if result["summary"].get("missing_receivable_account"):
            recommendations.append("Configure receivable account mappings")
        if result["summary"].get("missing_payable_account"):
            recommendations.append("Configure payable account mappings")
        if result["summary"].get("missing_customer"):
            recommendations.append("Enable customer creation or pre-create customers")
        if result["summary"].get("missing_supplier"):
            recommendations.append("Enable supplier creation or pre-create suppliers")
        if result["summary"].get("missing_expense_account") or result["summary"].get(
            "missing_income_account"
        ):
            recommendations.append("Configure tegenrekening mappings for expense/income accounts")
        if result["summary"].get("missing_ledger_mapping"):
            recommendations.append("Add missing ledger mappings in E-Boekhouden Ledger Mapping")

    result["recommendations"] = recommendations

    return result


@frappe.whitelist()
def check_current_mappings():
    """Check what mappings are currently configured"""

    result = {
        "ledger_mappings": 0,
        "tegenrekening_mappings": 0,
        "sample_ledger_mappings": [],
        "sample_tegenrekening_mappings": [],
        "accounts": {
            "bank_accounts": 0,
            "receivable_accounts": 0,
            "payable_accounts": 0,
            "expense_accounts": 0,
            "income_accounts": 0,
        },
    }

    # Count ledger mappings
    result["ledger_mappings"] = frappe.db.count("E-Boekhouden Ledger Mapping")

    # Get sample ledger mappings
    sample_ledgers = frappe.db.sql(
        """
        SELECT ledger_id, ledger_name, erpnext_account
        FROM `tabE-Boekhouden Ledger Mapping`
        LIMIT 10
    """,
        as_dict=True,
    )
    result["sample_ledger_mappings"] = sample_ledgers

    # Check if tegenrekening mapping table exists
    if frappe.db.table_exists("E-Boekhouden Tegenrekening Mapping"):
        result["tegenrekening_mappings"] = frappe.db.count("E-Boekhouden Tegenrekening Mapping")

        # Get sample tegenrekening mappings
        sample_tegenrekeningen = frappe.db.sql(
            """
            SELECT tegenrekening_code, tegenrekening_name, erpnext_item, erpnext_income_account, erpnext_expense_account
            FROM `tabE-Boekhouden Tegenrekening Mapping`
            LIMIT 10
        """,
            as_dict=True,
        )
        result["sample_tegenrekening_mappings"] = sample_tegenrekeningen
    else:
        result["tegenrekening_mappings"] = "Table does not exist"
        result["sample_tegenrekening_mappings"] = []

    # Count different account types
    company = frappe.db.get_value("E-Boekhouden Settings", None, "default_company")

    result["accounts"]["bank_accounts"] = frappe.db.count(
        "Account", {"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0}
    )

    result["accounts"]["receivable_accounts"] = frappe.db.count(
        "Account", {"company": company, "account_type": "Receivable", "is_group": 0}
    )

    result["accounts"]["payable_accounts"] = frappe.db.count(
        "Account", {"company": company, "account_type": "Payable", "is_group": 0}
    )

    result["accounts"]["expense_accounts"] = frappe.db.count(
        "Account", {"company": company, "root_type": "Expense", "is_group": 0}
    )

    result["accounts"]["income_accounts"] = frappe.db.count(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}
    )

    return result


if __name__ == "__main__":
    print("Test import without fallbacks")
