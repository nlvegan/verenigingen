"""
Fix Purchase Invoices with Receivable/Payable account issues
"""

import frappe


@frappe.whitelist()
def check_account_types():
    """Check which accounts are being used incorrectly"""

    try:
        # Check account 14500
        account_14500 = frappe.get_doc("Account", "14500 - Vooruitbetaalde bedragen - NVV")

        # Get all receivable/payable accounts
        problematic_accounts = frappe.db.sql(
            """
            SELECT
                name,
                account_name,
                account_number,
                account_type
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND account_type IN ('Receivable', 'Payable')
            ORDER BY account_number
        """,
            as_dict=True,
        )

        # Check how these accounts are being used in the mapping
        ledger_mappings = frappe.db.sql(
            """
            SELECT
                lm.ledger_id,
                lm.ledger_code,
                lm.ledger_name,
                lm.erpnext_account,
                a.account_type
            FROM `tabE-Boekhouden Ledger Mapping` lm
            JOIN `tabAccount` a ON lm.erpnext_account = a.name
            WHERE a.account_type IN ('Receivable', 'Payable')
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "account_14500": {
                "name": account_14500.name,
                "account_type": account_14500.account_type,
                "is_group": account_14500.is_group,
            },
            "problematic_accounts": problematic_accounts,
            "affected_ledger_mappings": ledger_mappings,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def fix_account_types():
    """Fix account types for prepaid/accrual accounts"""

    try:
        # Accounts that should be Current Asset instead of Receivable
        prepaid_accounts = [
            "14500 - Vooruitbetaalde bedragen - NVV",
            "14200 - Vooruitbetaalde verzekeringen - NVV",
            "14700 - Overlopende Posten 2018 - NVV",
            "10002 - Overlopende posten - NVV",  # Accrued items
        ]

        # Accounts that should be Current Liability instead of Payable
        accrual_accounts = ["18100 - Te betalen sociale lasten - NVV"]

        # These should remain as Receivable (actual amounts to receive from customers)
        # "13500 - Te ontvangen contributies" - Contributions to receive
        # "13510 - Te ontvangen donaties" - Donations to receive
        # "13600 - Te ontvangen rente" - Interest to receive
        # "13900 - Te ontvangen bedragen" - Amounts to receive

        # "19290 - Te betalen bedragen" should remain Payable (actual supplier payables)

        fixed = []

        # Fix prepaid accounts (should be Current Asset, not Receivable)
        for account_name in prepaid_accounts:
            if frappe.db.exists("Account", account_name):
                frappe.db.set_value("Account", account_name, "account_type", "Current Asset")
                fixed.append({"account": account_name, "old_type": "Receivable", "new_type": "Current Asset"})

        # Fix accrual accounts (should be Current Liability, not Payable)
        for account_name in accrual_accounts:
            if frappe.db.exists("Account", account_name):
                frappe.db.set_value("Account", account_name, "account_type", "Current Liability")
                fixed.append(
                    {"account": account_name, "old_type": "Payable", "new_type": "Current Liability"}
                )

        frappe.db.commit()

        return {"success": True, "fixed": fixed, "message": f"Fixed {len(fixed)} account types"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
