"""
Opening Balance Processor for eBoekhouden Integration

This module handles the import of opening balances from eBoekhouden,
wrapping the existing functionality from the main migration file.
"""

from typing import Any, Dict, List, Optional

import frappe

from .base_processor import BaseTransactionProcessor


class OpeningBalanceProcessor(BaseTransactionProcessor):
    """Processor for importing opening balances"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is an opening balance mutation"""
        mutation_type = mutation.get("type", 0)
        return mutation_type == 0  # Type 0 = Opening balance

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process opening balance mutation"""
        # Opening balances are typically handled as journal entries
        from ..eboekhouden_rest_full_migration import _create_journal_entry

        return _create_journal_entry(mutation, self.company, self.cost_center, self.debug_info)

    def import_all_opening_balances(self, dry_run: bool = False) -> Dict[str, Any]:
        """Import all opening balances for the company"""
        from ..eboekhouden_rest_full_migration import _import_opening_balances

        return _import_opening_balances(self.company, self.cost_center, self.debug_info, dry_run=dry_run)

    def validate_opening_balance(self, mutation: Dict[str, Any]) -> bool:
        """Validate if opening balance data is complete and allowed"""
        # Check required fields
        if not mutation.get("ledgerId"):
            self.add_debug_info("Opening balance missing ledgerId")
            return False

        amount = self.get_amount(mutation)
        if amount == 0:
            self.add_debug_info("Opening balance has zero amount")
            return False

        # Check if account is a stock account (should be skipped)
        account = self.get_opening_balance_account(mutation)
        if account and self.is_stock_account(account):
            self.add_debug_info(f"Skipping stock account {account} - excluded from opening balances")
            return False

        return True

    def is_stock_account(self, account_name: str) -> bool:
        """Check if an account is a stock account"""
        try:
            account_type = frappe.db.get_value("Account", account_name, "account_type")
            return account_type == "Stock"
        except:
            return False

    def get_opening_balance_account(self, mutation: Dict[str, Any]) -> Optional[str]:
        """Get the ERPNext account for the opening balance"""
        ledger_id = mutation.get("ledgerId")
        if not ledger_id:
            return None

        # Look up account mapping
        mapping_result = frappe.db.sql(
            """SELECT erpnext_account
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE ledger_id = %s
            LIMIT 1""",
            ledger_id,
            as_dict=True,
        )

        if mapping_result:
            return mapping_result[0].get("erpnext_account")

        self.add_debug_info(f"No account mapping found for ledger {ledger_id}")
        return None
