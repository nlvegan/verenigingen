"""
Stock Transaction Processor for eBoekhouden Integration

This module handles stock-related mutations (Type 7 Memorial Bookings and Type 10 Stock Mutations)
that involve stock accounts. Since ERPNext requires stock accounts to be updated via Stock Entry
or Stock Reconciliation (not Journal Entry), this processor creates appropriate stock documents.

E-Boekhouden Pattern:
    Type 7 Memorial Bookings with stock accounts typically represent:
    - Stock valuation adjustments
    - Inventory corrections
    - Purchase-to-stock transfers

    These are handled via Stock Reconciliation which adjusts the stock balance
    and creates the appropriate accounting entries.

ERPNext Constraint:
    Stock accounts (account_type='Stock') can only be updated through:
    - Stock Entry (for movements with items)
    - Stock Reconciliation (for balance adjustments)

    Attempting to update via Journal Entry will raise a validation error.
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, getdate

from .base_processor import BaseTransactionProcessor


class StockProcessor(BaseTransactionProcessor):
    """Processor for creating Stock Reconciliation from stock-related mutations"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """
        Check if this mutation involves stock accounts.

        Stock mutations are identified by:
        1. Type 7 (Memorial Booking) or Type 10 (Stock Mutation)
        2. At least one account in the transaction is a Stock account

        Args:
            mutation: Mutation data from E-Boekhouden

        Returns:
            bool: True if this is a stock-related mutation
        """
        mutation_type = mutation.get("type", 0)

        # Check if it's a stock mutation type
        if mutation_type not in [7, 10]:
            return False

        # Check if any accounts involved are stock accounts
        has_stock_account = False

        # Check main ledger account
        ledger_id = mutation.get("ledgerId")
        if ledger_id:
            account = self._get_account_for_ledger(ledger_id)
            if account and self._is_stock_account(account):
                has_stock_account = True

        # Check row accounts
        rows = mutation.get("rows", [])
        for row in rows:
            row_ledger_id = row.get("ledgerId")
            if row_ledger_id:
                account = self._get_account_for_ledger(row_ledger_id)
                if account and self._is_stock_account(account):
                    has_stock_account = True
                    break

        return has_stock_account

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """
        Process the stock mutation and create Stock Reconciliation.

        Args:
            mutation: Mutation data from E-Boekhouden

        Returns:
            Stock Reconciliation document if successful, None otherwise
        """
        mutation_id = mutation.get("id") or mutation.get("mutationNumber", "Unknown")
        mutation_date = mutation.get("date", frappe.utils.today())
        description = mutation.get("description", "")

        self.debug_info.append(f"Processing stock mutation {mutation_id}: {description}")

        # Extract stock account information
        stock_account = None
        counterparty_account = None
        amount = 0

        # Get main account
        main_ledger_id = mutation.get("ledgerId")
        main_account = self._get_account_for_ledger(main_ledger_id) if main_ledger_id else None

        # Get row accounts
        rows = mutation.get("rows", [])

        if not rows:
            self.debug_info.append(f"⚠️ Stock mutation {mutation_id} has no rows, skipping")
            return None

        for row in rows:
            row_ledger_id = row.get("ledgerId")
            row_account = self._get_account_for_ledger(row_ledger_id) if row_ledger_id else None
            row_amount = flt(row.get("amount", 0))

            # Determine which is stock and which is counterparty
            if main_account and self._is_stock_account(main_account):
                stock_account = main_account
                counterparty_account = row_account
                # Main account gets the balancing amount
                amount = -row_amount  # Opposite sign
            elif row_account and self._is_stock_account(row_account):
                stock_account = row_account
                counterparty_account = main_account
                amount = row_amount

        if not stock_account:
            self.debug_info.append(f"⚠️ No stock account found in mutation {mutation_id}")
            return None

        if abs(amount) < 0.01:
            self.debug_info.append(f"⚠️ Stock mutation {mutation_id} has zero amount, skipping")
            return None

        self.debug_info.append(
            f"Stock adjustment: {stock_account} = €{amount:.2f}, "
            f"Counterparty: {counterparty_account or 'None'}"
        )

        # Create Stock Reconciliation
        try:
            stock_reco = self._create_stock_reconciliation(
                mutation_id=mutation_id,
                mutation_date=mutation_date,
                description=description,
                stock_account=stock_account,
                amount=amount,
            )

            if stock_reco:
                self.debug_info.append(f"✅ Created Stock Reconciliation: {stock_reco.name}")
                return stock_reco
            else:
                self.debug_info.append(f"⚠️ Failed to create Stock Reconciliation for mutation {mutation_id}")
                return None

        except Exception as e:
            self.debug_info.append(f"❌ Error creating Stock Reconciliation: {str(e)}")
            frappe.log_error(
                title=f"Stock Processor Error - Mutation {mutation_id}",
                message=f"Error: {str(e)}\n\nMutation data:\n{frappe.as_json(mutation)}",
            )
            return None

    def _create_stock_reconciliation(
        self, mutation_id: str, mutation_date: str, description: str, stock_account: str, amount: float
    ) -> Optional[frappe.model.document.Document]:
        """
        Create Stock Reconciliation for stock account adjustment.

        Args:
            mutation_id: E-Boekhouden mutation ID
            mutation_date: Transaction date
            description: Transaction description
            stock_account: Stock account name
            amount: Stock value adjustment amount

        Returns:
            Stock Reconciliation document if successful
        """
        # Get or create warehouse
        warehouse = self._get_or_create_warehouse()
        if not warehouse:
            self.debug_info.append("❌ Could not get/create warehouse for stock reconciliation")
            return None

        # Get or create stock item for this account
        item_code = self._get_or_create_stock_item(stock_account)
        if not item_code:
            self.debug_info.append(f"❌ Could not get/create stock item for {stock_account}")
            return None

        # Create Stock Reconciliation
        stock_reco = frappe.new_doc("Stock Reconciliation")
        stock_reco.company = self.company
        stock_reco.posting_date = getdate(mutation_date)
        stock_reco.posting_time = "12:00:00"
        stock_reco.purpose = "Stock Reconciliation"
        stock_reco.expense_account = stock_account

        # Store E-Boekhouden reference
        stock_reco.eboekhouden_mutation_nr = str(mutation_id)
        stock_reco.user_remark = f"E-Boekhouden mutation {mutation_id}: {description}"

        # Calculate quantity (assume €1.00 per unit for simplicity)
        qty = abs(amount)
        rate = 1.00

        stock_reco.append(
            "items",
            {
                "item_code": item_code,
                "warehouse": warehouse,
                "qty": qty,
                "valuation_rate": rate,
                "amount": abs(amount),
            },
        )

        # Save and submit
        stock_reco.flags.ignore_permissions = False  # Use proper permissions
        stock_reco.save()
        stock_reco.submit()

        self.debug_info.append(f"Created Stock Reconciliation: Qty={qty}, Rate={rate}, Amount={amount}")

        return stock_reco

    def _get_or_create_warehouse(self) -> Optional[str]:
        """Get or create a default warehouse for the company"""
        # Try to get existing non-group warehouse
        warehouse = frappe.db.get_value(
            "Warehouse", {"company": self.company, "is_group": 0}, "name", order_by="creation"
        )

        if warehouse:
            return warehouse

        # Create default warehouse
        try:
            warehouse_doc = frappe.new_doc("Warehouse")
            warehouse_doc.warehouse_name = "Main Warehouse"
            warehouse_doc.company = self.company
            warehouse_doc.save()
            self.debug_info.append(f"Created default warehouse: {warehouse_doc.name}")
            return warehouse_doc.name
        except Exception as e:
            self.debug_info.append(f"Error creating warehouse: {str(e)}")
            return None

    def _get_or_create_stock_item(self, stock_account: str) -> Optional[str]:
        """
        Get or create a stock item for the given stock account.

        Args:
            stock_account: Stock account name

        Returns:
            Item code or None if failed
        """
        try:
            # Extract account name for item naming
            account_parts = stock_account.split(" - ")
            if len(account_parts) > 1:
                account_name = account_parts[1]  # e.g., "Voorraden" from "30000 - Voorraden - NVV"
            else:
                account_name = stock_account.replace(" ", "_")

            # Create item code based on account
            item_code = f"STOCK_{account_name.upper().replace(' ', '_')}"

            # Check if item already exists
            if frappe.db.exists("Item", item_code):
                return item_code

            # Get default item group
            item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            if not item_group:
                item_group = "All Item Groups"  # Fallback

            # Create new stock item
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = f"Stock Item for {account_name}"
            item.item_group = item_group
            item.stock_uom = "Nos"
            item.is_stock_item = 1
            item.include_item_in_manufacturing = 0
            item.valuation_method = "FIFO"

            item.save()
            self.debug_info.append(f"Created stock item: {item_code} for account {stock_account}")
            return item_code

        except Exception as e:
            self.debug_info.append(f"Error creating stock item for {stock_account}: {str(e)}")
            return None

    def _get_account_for_ledger(self, ledger_id: int) -> Optional[str]:
        """Look up ERPNext account for an E-Boekhouden ledger ID"""
        try:
            account = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "erpnext_account"
            )
            return account
        except Exception:
            return None

    def _is_stock_account(self, account: str) -> bool:
        """Check if the given account is a stock account"""
        try:
            account_type = frappe.db.get_value("Account", account, "account_type")
            return account_type == "Stock"
        except Exception:
            return False
