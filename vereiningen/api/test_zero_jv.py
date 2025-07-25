"""
Test if ERPNext allows zero-amount Journal Entries
"""

import frappe
from frappe.utils import today


@frappe.whitelist()
def test_zero_amount_journal_entry():
    """Test creating a zero-amount Journal Entry to see if ERPNext allows it"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Create a simple zero-amount JV
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = today()
        je.voucher_type = "Journal Entry"
        je.user_remark = "Test zero-amount JV"

        # Add two zero-amount entries that balance out
        je.append(
            "accounts",
            {
                "account": "80001 - Contributie Leden plus Abonnementen - NVV",  # Income account
                "debit": 0,
                "credit": 0,
                "user_remark": "Test zero debit",
            },
        )

        je.append(
            "accounts",
            {
                "account": "10440 - Triodos - 19.83.96.716 - Algemeen - NVV",  # Bank account
                "debit": 0,
                "credit": 0,
                "user_remark": "Test zero credit",
            },
        )

        # Try to save it
        je.save()
        je.submit()

        return {
            "success": True,
            "journal_entry": je.name,
            "total_debit": je.total_debit,
            "total_credit": je.total_credit,
            "result": "ERPNext allows zero-amount Journal Entries",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "result": "ERPNext validation prevents zero-amount Journal Entries",
        }


@frappe.whitelist()
def test_minimal_amount_journal_entry():
    """Test creating a Journal Entry with minimal amounts (0.01)"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        cost_center = settings.default_cost_center

        # Create a minimal amount JV
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = today()
        je.voucher_type = "Journal Entry"
        je.user_remark = "Test minimal amount JV"

        # Add minimal amount entries that balance out
        je.append(
            "accounts",
            {
                "account": "80001 - Contributie Leden plus Abonnementen - NVV",
                "debit": 0.01,
                "credit": 0,
                "cost_center": cost_center,
                "user_remark": "Test minimal debit",
            },
        )

        je.append(
            "accounts",
            {
                "account": "10440 - Triodos - 19.83.96.716 - Algemeen - NVV",
                "debit": 0,
                "credit": 0.01,
                "cost_center": cost_center,
                "user_remark": "Test minimal credit",
            },
        )

        # Try to save it
        je.save()
        je.submit()

        return {
            "success": True,
            "journal_entry": je.name,
            "total_debit": je.total_debit,
            "total_credit": je.total_credit,
            "result": "ERPNext allows minimal amount (0.01) Journal Entries",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "result": "ERPNext validation prevents minimal amount Journal Entries",
        }


@frappe.whitelist()
def check_existing_zero_jvs():
    """Check if there are any existing zero-amount Journal Entries in the system"""
    try:
        # Find Journal Entries with zero total amounts
        zero_jvs = frappe.get_all(
            "Journal Entry",
            filters={"total_debit": 0, "total_credit": 0, "docstatus": ["!=", 2]},  # Not cancelled
            fields=["name", "posting_date", "user_remark", "docstatus"],
            limit=10,
        )

        return {
            "success": True,
            "zero_amount_jvs_found": len(zero_jvs),
            "examples": zero_jvs,
            "conclusion": f"Found {len(zero_jvs)} existing zero-amount Journal Entries in the system",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
