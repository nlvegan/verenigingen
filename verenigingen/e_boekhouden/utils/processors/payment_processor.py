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
        mutation_id = mutation.get("id")

        self.debug_info.append(
            f"PaymentProcessor.can_process() called for mutation {mutation_id}, type={mutation_type}"
        )

        # Type 3 = Customer Payment, Type 4 = Supplier Payment
        # Type 5 = Money Received, Type 6 = Money Paid
        if mutation_type not in [3, 4, 5, 6]:
            self.debug_info.append(
                f"PaymentProcessor: Type {mutation_type} not in [3,4,5,6] - cannot process"
            )
            return False

        # Payment gateway adjustments should be explicitly claimed by this processor
        # so they can be skipped (returning True here, None from process())
        # This prevents them from falling through to JournalProcessor
        is_adjustment = self._is_payment_gateway_adjustment(mutation)
        self.debug_info.append(f"Gateway adjustment check for mutation {mutation.get('id')}: {is_adjustment}")

        if is_adjustment:
            self.debug_info.append(
                f"⚠️ CLAIMING payment gateway adjustment mutation {mutation.get('id')} to skip it "
                f"(internal accounting, not actual bank transaction)"
            )
            # Return True to claim this mutation, but process() will return None to skip it
            return True

        # For Type 3/4: Handle refunds in opposite direction
        # Type 3 (Customer Payment) normally positive - if negative = refund to customer
        # Type 4 (Supplier Payment) normally negative - if positive = refund from supplier
        #
        # CRITICAL: E-Boekhouden stores row amounts as UNSIGNED (always positive)
        # The mutation type determines the payment direction, NOT the row amount sign
        # Only use raw_amount (main mutation amount) for refund detection
        if mutation_type in [3, 4]:
            raw_amount = mutation.get("amount", 0) or 0
            has_rows = bool(mutation.get("rows"))
            row_amount = mutation["rows"][0].get("amount", 0) if has_rows else 0
            has_invoice_ref = bool(mutation.get("invoiceNumber"))

            # Validate row amount sign assumption - row amounts should typically be positive
            # Negative row amounts may indicate unexpected E-Boekhouden API behavior changes
            if has_rows and row_amount < 0:
                self.debug_info.append(
                    f"⚠️ WARNING: Type {mutation_type} mutation {mutation_id} has NEGATIVE row amount "
                    f"({row_amount}), which violates the unsigned assumption. This may affect refund detection."
                )
                frappe.log_error(
                    title=f"Unexpected Negative Row Amount - Mutation {mutation_id}",
                    message=f"Type {mutation_type} mutation {mutation_id} has negative row amount: {row_amount}\n"
                    f"Expected: positive (unsigned) amounts\n"
                    f"Raw amount: {raw_amount}\n"
                    f"This may indicate E-Boekhouden API behavior change.\n"
                    f"Full mutation: {frappe.as_json(mutation, indent=2)}",
                )

            # Type 3: Exclude negative amounts WITHOUT invoice ref (generic refunds → Journal Entry)
            # But keep negative WITH invoice ref (credit note payments → Payment Entry for reconciliation)
            if mutation_type == 3:
                is_negative = raw_amount < 0  # Only check raw_amount, row amounts are unsigned
                self.debug_info.append(
                    f"Type 3 refund check for mutation {mutation_id}: "
                    f"raw_amount={raw_amount}, row_amount={row_amount}, is_negative={is_negative}, "
                    f"has_invoice_ref={has_invoice_ref}"
                )
                if is_negative and not has_invoice_ref:
                    self.debug_info.append(
                        f"⚠️ Excluding Type 3 negative amount without invoice ref (generic refund) - forwarding to JournalProcessor"
                    )
                    return False

            # Type 4: Accept all Type 4 (both normal payments and refunds)
            # For Type 4 (Supplier Payment) in E-Boekhouden:
            # - raw_amount > 0 (positive) = NORMAL payment OUT to supplier → payment_type="Pay"
            # - raw_amount = 0 with positive row_amount = NORMAL payment → payment_type="Pay"
            # - raw_amount < 0 (negative) = REFUND/CREDIT from supplier, money IN → payment_type="Receive"
            #
            # NOTE: E-Boekhouden stores Type 4 payments with POSITIVE amounts (money leaving bank account)
            # PaymentEntryHandler will reverse the payment_type for negative amounts
            elif mutation_type == 4:
                is_refund = raw_amount < 0  # Negative = refund FROM supplier (money IN)
                self.debug_info.append(
                    f"Type 4 check for mutation {mutation_id}: "
                    f"raw_amount={raw_amount}, row_amount={row_amount}, is_refund={is_refund}"
                )
                # Accept both normal payments and refunds - let PaymentEntryHandler handle direction
                # No exclusion needed

        # Type 5/6 always go to Payment Entry (money transfers, bank fees, etc.)
        return True

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process the mutation and create payment entry"""
        mutation_type = mutation.get("type", 0)

        # Check if this is an adjustment that should be skipped
        # (can_process already detected this, but we check again to be explicit)
        if self._is_payment_gateway_adjustment(mutation):
            self.debug_info.append(
                f"✅ Skipping payment gateway adjustment mutation {mutation.get('id')} "
                f"(already detected in can_process)"
            )
            return None

        # Type 5/6 (Money Received/Paid) - extract party from bank transaction description
        # and create proper Payment Entry instead of Journal Entry
        if mutation_type in [5, 6]:
            return self._process_money_transfer(mutation)
        else:
            # Check if this is a gateway payment that needs amount adjustment
            adjusted_mutation = self._adjust_payment_gateway_amount(mutation)

            # Type 3/4 (Customer/Supplier Payments) use the enhanced payment handler
            from ..eboekhouden_rest_full_migration import _create_payment_entry

            return _create_payment_entry(adjusted_mutation, self.company, self.cost_center, self.debug_info)

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
                pe.paid_from = frappe.db.get_value("Company", self.company, "default_receivable_account")
                pe.paid_to = bank_account

            else:  # Type 6 - Money Paid
                pe.payment_type = "Pay"
                pe.mode_of_payment = "Bank Transfer"
                pe.party_type = party_type
                pe.party = party

                # For Pay: paid_from = bank account, paid_to = payable account
                pe.paid_from = bank_account
                pe.paid_to = frappe.db.get_value("Company", self.company, "default_payable_account")

            # Set amounts
            pe.paid_amount = abs(amount)
            pe.received_amount = abs(amount)
            pe.source_exchange_rate = 1.0
            pe.target_exchange_rate = 1.0

            # Set remarks
            pe.remarks = description

            # Save and submit
            pe.insert(ignore_permissions=False)

            # Create Bank Transaction before submitting (same pattern as Type 3/4)
            bank_transaction_name = self._create_bank_transaction_for_money_transfer(
                mutation, pe, bank_account
            )

            if bank_transaction_name:
                # Link Bank Transaction to Payment Entry
                self._link_bank_transaction_to_payment(bank_transaction_name, pe.name)
                self.debug_info.append(f"✅ Created and linked Bank Transaction: {bank_transaction_name}")
            else:
                self.debug_info.append(f"⚠️ Bank Transaction creation failed/skipped")

            # Submit Payment Entry (commits both PE and BT atomically)
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

    def _is_payment_gateway_adjustment(self, mutation: Dict[str, Any]) -> bool:
        """
        Detect if this is a payment gateway internal accounting entry that should be skipped.

        Payment gateways like Mollie create multiple internal mutations for fee calculations.
        Strategy: Process ONLY the first payment (adjust to invoice total), skip all subsequent ones.

        Args:
            mutation: The eBoekhouden mutation data

        Returns:
            True if this payment should be skipped (subsequent payment for already-paid invoice)
        """
        mutation_id = mutation.get("id")
        mutation_type = mutation.get("type")

        # Only applies to Type 4 (Supplier Payment)
        if mutation_type != 4:
            return False

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        gateway_account = settings.get("payment_gateway_virtual_account")
        gateway_prefix = settings.get("payment_gateway_invoice_prefix")

        # If not configured, don't apply gateway logic
        if not gateway_account or not gateway_prefix:
            # Log configuration warning once per processor instance to avoid spam
            if not hasattr(self, "_gateway_config_warning_logged"):
                self._gateway_config_warning_logged = True
                self.debug_info.append(
                    "ℹ️ Payment gateway configuration not set - gateway adjustment logic disabled. "
                    "Configure 'payment_gateway_virtual_account' and 'payment_gateway_invoice_prefix' "
                    "in E-Boekhouden Settings to enable Mollie payment adjustments."
                )
            return False

        # Look up the E-Boekhouden ledger ID from the ERPNext account mapping
        gateway_ledger = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"erpnext_account": gateway_account}, "ledger_id"
        )

        if not gateway_ledger:
            return False

        # Check if mutation is on the gateway virtual ledger
        mutation_ledger = str(mutation.get("ledgerId", ""))
        if mutation_ledger != str(gateway_ledger):
            return False

        # Check if invoice has gateway prefix
        invoice_num = mutation.get("invoiceNumber", "")
        if not invoice_num or not invoice_num.startswith(gateway_prefix):
            return False

        # This is a gateway payment - check if invoice already has payment
        self.debug_info.append(f"Gateway check for {mutation_id}: Payment for Mollie invoice {invoice_num}")

        # Look up Purchase Invoice
        invoices = frappe.get_all(
            "Purchase Invoice",
            filters={"eboekhouden_invoice_number": invoice_num},
            fields=["name", "grand_total", "outstanding_amount"],
            limit=1,
        )

        if not invoices:
            self.debug_info.append(
                f"Gateway check for {mutation_id}: Invoice {invoice_num} not found - will process normally"
            )
            return False

        invoice = invoices[0]
        outstanding = frappe.utils.flt(invoice.get("outstanding_amount", 0), 2)

        if outstanding == 0:
            self.debug_info.append(
                f"✅ Gateway check for {mutation_id}: Invoice {invoice['name']} already paid - SKIPPING"
            )
            return True
        else:
            self.debug_info.append(
                f"Gateway check for {mutation_id}: Invoice {invoice['name']} unpaid (€{outstanding}) - will process with adjusted amount"
            )
            return False

    def _adjust_payment_gateway_amount(self, mutation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adjust payment amount for gateway payments to match invoice total exactly.

        For payment gateway invoices (e.g., Mollie), adjust the payment amount to match
        the invoice total, ensuring perfect reconciliation. The invoice total already
        represents the net after all gateway adjustments.

        Args:
            mutation: The payment mutation data

        Returns:
            Adjusted mutation with amount set to invoice total, or original if not applicable
        """
        mutation_id = mutation.get("id")

        # Only applies to Type 4 (Supplier Payment)
        if mutation.get("type") != 4:
            return mutation

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        gateway_account = settings.get("payment_gateway_virtual_account")
        gateway_prefix = settings.get("payment_gateway_invoice_prefix")

        # If not configured, return original
        if not gateway_account or not gateway_prefix:
            # Configuration already logged by _is_payment_gateway_adjustment
            return mutation

        # Look up the E-Boekhouden ledger ID from the ERPNext account mapping
        gateway_ledger = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"erpnext_account": gateway_account}, "ledger_id"
        )

        if not gateway_ledger:
            return mutation

        # Check if this is on gateway ledger
        mutation_ledger = str(mutation.get("ledgerId", ""))
        if mutation_ledger != str(gateway_ledger):
            return mutation

        # Check if invoice has gateway prefix
        invoice_num = mutation.get("invoiceNumber", "")
        if not invoice_num or not invoice_num.startswith(gateway_prefix):
            return mutation

        # This is a gateway payment - find the invoice and adjust to its amount
        try:
            # Look up Purchase Invoice by eboekhouden_invoice_number or name
            invoice = None

            # First try by eboekhouden_invoice_number (the invoice number field, not mutation ID)
            invoices = frappe.get_all(
                "Purchase Invoice",
                filters={"eboekhouden_invoice_number": invoice_num},
                fields=["name", "grand_total"],
                limit=1,
            )

            if invoices:
                invoice = invoices[0]
            else:
                # Try by name
                if frappe.db.exists("Purchase Invoice", invoice_num):
                    invoice = frappe.db.get_value(
                        "Purchase Invoice", invoice_num, ["name", "grand_total"], as_dict=True
                    )

            if invoice:
                # Get original amount for logging
                raw_amount = mutation.get("amount", 0) or 0
                rows = mutation.get("rows", [])
                if raw_amount == 0 and rows:
                    row_amounts = [abs(row.get("amount", 0) or 0) for row in rows]
                    original_amount = sum(row_amounts)
                else:
                    original_amount = abs(raw_amount)

                # Create a DEEP copy to avoid mutating original mutation data
                import copy

                adjusted = copy.deepcopy(mutation)
                invoice_total = invoice["grand_total"]

                # Adjust the amount to match invoice total
                adjusted["amount"] = -abs(invoice_total)  # Negative for Type 4 (supplier payment)

                # Also adjust rows if present
                if adjusted.get("rows"):
                    if adjusted["rows"]:
                        adjusted["rows"][0]["amount"] = -abs(invoice_total)

                # Store original amount for audit trail
                adjusted["_original_amount"] = original_amount
                adjusted["_adjustment_reason"] = f"Gateway fee reconciliation for invoice {invoice['name']}"

                self.debug_info.append(
                    f"💰 Gateway payment {mutation_id}: Adjusted amount from €{original_amount} to €{invoice_total}"
                )
                self.debug_info.append(
                    f"   Matching invoice {invoice['name']} total for perfect reconciliation"
                )
                self.debug_info.append(
                    f"   Bank Transaction will use adjusted amount €{invoice_total} for proper reconciliation"
                )

                return adjusted
            else:
                self.debug_info.append(
                    f"⚠️ Gateway payment {mutation_id}: Could not find invoice {invoice_num} for adjustment"
                )

        except Exception as e:
            self.debug_info.append(f"❌ Gateway payment {mutation_id}: Error adjusting amount: {str(e)}")

        # If adjustment failed, return original
        return mutation

    def _create_bank_transaction_for_money_transfer(
        self, mutation: Dict[str, Any], payment_entry: frappe._dict, bank_account: str
    ) -> Optional[str]:
        """
        Create Bank Transaction for Type 5/6 money transfer mutations.

        Args:
            mutation: E-Boekhouden mutation data
            payment_entry: Created Payment Entry document (draft state)
            bank_account: Bank account used in Payment Entry

        Returns:
            Bank Transaction name if created, None on failure
        """
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        try:
            mutation_id = mutation.get("id")

            # Check if Bank Transaction already exists (idempotency)
            existing_bt = frappe.db.get_value(
                "Bank Transaction", {"reference_number": f"EB-{mutation_id}"}, "name"
            )

            if existing_bt:
                self.debug_info.append(f"Bank Transaction {existing_bt} already exists, skipping")
                return existing_bt

            creator = get_bank_transaction_creator()

            # Get amount from Payment Entry
            amount = payment_entry.paid_amount or payment_entry.received_amount

            # Validate non-zero amount
            if not amount or amount < 0.01:
                self.debug_info.append(f"Skipping Bank Transaction for zero/near-zero amount: {amount}")
                return None

            # Determine sign from payment type
            bank_transaction_amount = amount if payment_entry.payment_type == "Receive" else -amount

            # Use bank description
            bt_description = mutation.get("description", "")
            bt_reference = f"EB-{mutation_id}"

            # Create Bank Transaction
            transaction_data = {
                "date": payment_entry.posting_date,
                "amount": bank_transaction_amount,
                "currency": "EUR",
                "description": bt_description,
                "reference_number": bt_reference,
                "party_type": payment_entry.party_type if payment_entry.party else None,
                "party": payment_entry.party if payment_entry.party else None,
            }

            bank_transaction_name = creator.create_from_dict(
                transaction_data=transaction_data,
                bank_account=bank_account,
                company=self.company,
                source_type="E-Boekhouden Import",
            )

            return bank_transaction_name

        except Exception as e:
            self.debug_info.append(f"ERROR creating Bank Transaction: {str(e)}")
            frappe.log_error(
                f"Failed to create Bank Transaction for Type 5/6 mutation {mutation.get('id')}: {str(e)}",
                "E-Boekhouden Type 5/6 Bank Transaction Creation",
            )
            return None

    def _link_bank_transaction_to_payment(self, bank_transaction_name: str, payment_entry_name: str):
        """
        Link Bank Transaction to Payment Entry for proper reconciliation.

        Args:
            bank_transaction_name: Bank Transaction name
            payment_entry_name: Payment Entry name (draft state)
        """
        try:
            # Get documents
            bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
            pe = frappe.get_doc("Payment Entry", payment_entry_name)

            # Check if already linked
            already_linked = frappe.db.exists(
                "Bank Transaction Payments", {"parent": bank_transaction_name, "payment_entry": payment_entry_name}
            )

            if already_linked:
                self.debug_info.append(f"Bank Transaction {bank_transaction_name} already linked")
                return

            # Add to Bank Transaction Payments child table
            bt.append(
                "payment_entries",
                {
                    "payment_document": "Payment Entry",
                    "payment_entry": payment_entry_name,
                    "allocated_amount": pe.paid_amount or pe.received_amount,
                },
            )

            # Update Bank Transaction status and amounts
            bt.status = "Reconciled"
            bt.allocated_amount = pe.paid_amount or pe.received_amount
            bt.unallocated_amount = 0.0

            # Save the Bank Transaction
            bt.save(ignore_permissions=False)

            self.debug_info.append(f"Linked Bank Transaction {bank_transaction_name} to Payment Entry {payment_entry_name}")

        except Exception as e:
            error_msg = f"Failed to link Bank Transaction to Payment Entry: {str(e)}"
            self.debug_info.append(f"ERROR: {error_msg}")
            frappe.log_error(
                f"Bank Transaction linking failed: {error_msg}",
                "E-Boekhouden Bank Transaction Linking",
            )
            raise
