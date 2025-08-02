#!/usr/bin/env python3
"""
Investigate Vraagposten fallback logic
"""

import frappe


@frappe.whitelist()
def investigate_vraagposten_payments():
    """Investigate payments using Vraagposten account"""

    try:
        # Check if Vraagposten account exists
        vraagposten_account = "Vraagposten - NVV"
        account_exists = frappe.db.exists("Account", vraagposten_account)

        result = {
            "vraagposten_account": vraagposten_account,
            "account_exists": account_exists,
            "account_details": None,
            "payments_using_vraagposten": [],
        }

        if account_exists:
            account_details = frappe.db.get_value(
                "Account",
                vraagposten_account,
                ["name", "account_name", "account_type", "root_type", "parent_account"],
                as_dict=True,
            )
            result["account_details"] = account_details

        # Find payments using Vraagposten
        payments = frappe.db.sql(
            """
            SELECT name, party_type, party, paid_from, paid_to, payment_type,
                   eboekhouden_mutation_nr, posting_date, paid_amount, received_amount
            FROM `tabPayment Entry`
            WHERE (paid_from = %s OR paid_to = %s)
            ORDER BY posting_date DESC
            LIMIT 5
        """,
            (vraagposten_account, vraagposten_account),
            as_dict=True,
        )

        result["payments_using_vraagposten"] = payments
        result["payment_count"] = len(payments)

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}
