"""
Bank Utilities

Centralized utilities for Bank DocType operations.
"""

import frappe

from verenigingen.e_boekhouden.utils.security_helper import migration_context


def get_or_create_unknown_bank() -> str:
    """
    Get or create the 'Unknown' Bank record.

    The Bank Account DocType requires a linked Bank record (bank field is required).
    This helper ensures the 'Unknown' bank exists before creating Bank Accounts
    when the actual bank is not known (e.g., from Mollie payments or MT940 imports).

    Uses proper permission context instead of ignore_permissions=True.

    Returns:
        str: Bank name ('Unknown')
    """
    bank_name = "Unknown"
    if not frappe.db.exists("Bank", bank_name):
        try:
            # Use migration context for proper permission handling
            with migration_context("party_creation"):
                bank = frappe.new_doc("Bank")
                bank.bank_name = bank_name
                bank.insert()
                frappe.db.commit()
        except frappe.exceptions.DuplicateEntryError:
            # Race condition - another process created it
            pass
    return bank_name
