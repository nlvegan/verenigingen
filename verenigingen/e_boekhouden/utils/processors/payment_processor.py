"""
Payment Transaction Processor for eBoekhouden Integration

This module wraps the existing payment entry creation function from the main migration file,
providing a clean interface for modular processing.
"""

from typing import Any, Dict, Optional

import frappe

from .base_processor import BaseTransactionProcessor


class PaymentProcessor(BaseTransactionProcessor):
    """Processor for creating Payment Entries from mutations"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is a payment mutation"""
        mutation_type = mutation.get("type", 0)

        # Type 3 = Customer Payment, Type 4 = Supplier Payment
        # Type 5 = Money Received, Type 6 = Money Paid
        if mutation_type not in [3, 4, 5, 6]:
            return False

        # For Type 3/4: Exclude credit note refunds (handled by JournalProcessor instead)
        # Credit note refunds have negative amounts + invoice references
        if mutation_type in [3, 4]:
            raw_amount = mutation.get("amount", 0) or 0
            has_rows = bool(mutation.get("rows"))
            row_amount = mutation["rows"][0].get("amount", 0) if has_rows else 0
            is_negative = (raw_amount < 0) or (row_amount < 0)
            has_invoice_ref = bool(mutation.get("invoiceNumber"))

            # If it's a credit note refund, let JournalProcessor handle it
            if is_negative and has_invoice_ref:
                return False

        # Type 5/6 always go to Payment Entry (money transfers, bank fees, etc.)
        return True

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process the mutation and create payment entry"""
        mutation_type = mutation.get("type", 0)

        # Type 5/6 (Money Received/Paid) - extract party from bank transaction description
        # and create proper Payment Entry instead of Journal Entry
        if mutation_type in [5, 6]:
            return self._process_money_transfer(mutation)
        else:
            # Type 3/4 (Customer/Supplier Payments) use the enhanced payment handler
            from ..eboekhouden_rest_full_migration import _create_payment_entry

            return _create_payment_entry(mutation, self.company, self.cost_center, self.debug_info)

    def get_payment_type(self, mutation: Dict[str, Any]) -> str:
        """Determine payment type from mutation"""
        mutation_type = mutation.get("type", 0)

        # Type 3 = Money received (Receive)
        # Type 4 = Money paid (Pay)
        return "Receive" if mutation_type == 3 else "Pay"

    def is_enhanced_processing_enabled(self) -> bool:
        """Enhanced payment processing is always enabled for data quality"""
        return True

    def _process_money_transfer(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """
        Process Type 5/6 money transfers with party extraction from bank transaction description.

        Extracts party information from the bank transaction description and creates
        a proper Payment Entry with party reference instead of a Journal Entry.

        Args:
            mutation: Type 5 (Money Received) or Type 6 (Money Paid) mutation

        Returns:
            Payment Entry document if successful, None otherwise
        """
        from ..bank_transaction_parser import get_party_for_transaction

        mutation_id = mutation.get("id")
        mutation_type = mutation.get("type", 0)
        description = mutation.get("description", "")
        posting_date = mutation.get("date")

        # Calculate amount from rows if main amount is zero
        amount = frappe.utils.flt(mutation.get("amount", 0), 2)
        rows = mutation.get("rows", [])

        if amount == 0 and rows:
            row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in rows]
            amount = sum(row_amounts)
            self.debug_info.append(f"Main amount was 0, calculated {amount} from {len(rows)} rows")

        self.debug_info.append(
            f"Processing money transfer: ID={mutation_id}, Type={mutation_type}, Amount={amount}"
        )

        # Extract party from description
        try:
            party, party_type = get_party_for_transaction(description, mutation_type)
            self.debug_info.append(f"Extracted party: {party} ({party_type}) from description")
        except Exception as e:
            self.debug_info.append(f"Failed to extract party: {str(e)}, falling back to legacy")
            # Fall back to legacy Journal Entry approach
            from ..eboekhouden_rest_full_migration import _create_money_transfer_payment_entry

            return _create_money_transfer_payment_entry(
                mutation, self.company, self.cost_center, self.debug_info
            )

        # Get bank account from main ledger
        ledger_id = mutation.get("ledgerId")
        bank_account = None

        if ledger_id:
            bank_account = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "erpnext_account"
            )

        if not bank_account:
            self.debug_info.append(f"Could not find bank account for ledger {ledger_id}")
            # Fall back to legacy approach
            from ..eboekhouden_rest_full_migration import _create_money_transfer_payment_entry

            return _create_money_transfer_payment_entry(
                mutation, self.company, self.cost_center, self.debug_info
            )

        self.debug_info.append(f"Using bank account: {bank_account}")

        # Create Payment Entry
        try:
            pe = frappe.new_doc("Payment Entry")
            pe.company = self.company
            pe.posting_date = posting_date
            pe.eboekhouden_mutation_nr = str(mutation_id)
            pe.reference_no = f"EB-{mutation_id}"
            pe.reference_date = posting_date

            # Set payment type and accounts based on mutation type
            if mutation_type == 5:  # Money Received
                pe.payment_type = "Receive"
                pe.mode_of_payment = "Bank Transfer"
                pe.party_type = party_type
                pe.party = party

                # For Receive: paid_from = receivable account, paid_to = bank account
                pe.paid_from = frappe.get_value("Company", self.company, "default_receivable_account")
                pe.paid_to = bank_account

            else:  # Type 6 - Money Paid
                pe.payment_type = "Pay"
                pe.mode_of_payment = "Bank Transfer"
                pe.party_type = party_type
                pe.party = party

                # For Pay: paid_from = bank account, paid_to = payable account
                pe.paid_from = bank_account
                pe.paid_to = frappe.get_value("Company", self.company, "default_payable_account")

            # Set amounts
            pe.paid_amount = abs(amount)
            pe.received_amount = abs(amount)
            pe.source_exchange_rate = 1.0
            pe.target_exchange_rate = 1.0

            # Set remarks
            pe.remarks = description

            # Save and submit
            pe.insert(ignore_permissions=False)
            pe.submit()

            self.debug_info.append(f"✅ Created Payment Entry: {pe.name}")
            return pe

        except Exception as e:
            error_msg = f"Failed to create Payment Entry: {str(e)}"
            self.debug_info.append(f"❌ {error_msg}")
            frappe.log_error(
                title=f"Money Transfer Payment Entry Error - Mutation {mutation_id}",
                message=f"{error_msg}\n\nMutation:\n{frappe.as_json(mutation)}",
            )

            # Fall back to legacy Journal Entry approach
            self.debug_info.append("Falling back to legacy Journal Entry approach")
            from ..eboekhouden_rest_full_migration import _create_money_transfer_payment_entry

            return _create_money_transfer_payment_entry(
                mutation, self.company, self.cost_center, self.debug_info
            )
