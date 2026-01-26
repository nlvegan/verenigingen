"""
Payment Transaction Processor for eBoekhouden Integration

This module wraps the existing payment entry creation function from the main migration file,
providing a clean interface for modular processing.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
    convert_gl_account_to_bank_account_or_raise,
)
from verenigingen.e_boekhouden.utils.consolidated.invoice_line_utils import (
    create_invoice_line_for_tegenrekening,
)
from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
    get_erpnext_account_from_ledger_id,
    get_ledger_code_from_id,
)
from verenigingen.e_boekhouden.utils.data_integrity import (
    insert_with_duplicate_handling,
    mask_pii_in_mutation,
    safe_log_mutation_error,
)

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
                # Log with PII masked for privacy compliance
                safe_log_mutation_error(
                    title=f"Unexpected Negative Row Amount - Mutation {mutation_id}",
                    mutation=mutation,
                    additional_context=f"Type {mutation_type} mutation {mutation_id} has negative row amount: {row_amount}\n"
                    f"Expected: positive (unsigned) amounts\n"
                    f"Raw amount: {raw_amount}\n"
                    f"This may indicate E-Boekhouden API behavior change.",
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
                        "⚠️ Excluding Type 3 negative amount without invoice ref (generic refund) - forwarding to JournalProcessor"
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

            # Type 3/4 (Customer/Supplier Payments) use the consolidated payment handler
            # This decouples PaymentProcessor from the monolith migration file
            from verenigingen.e_boekhouden.utils.consolidated.payment_entry_creation import (
                create_payment_entry,
            )

            return create_payment_entry(adjusted_mutation, self.company, self.cost_center, self.debug_info)

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
        Process Type 5/6 money transfers by creating Journal Entry with Bank Transaction.

        Type 5/6 are direct bank transfers without invoices, so we create Journal Entries
        with proper row accounts (income/expense) and Bank Transactions for reconciliation.

        Args:
            mutation: Type 5 (Money Received) or Type 6 (Money Paid) mutation

        Returns:
            Journal Entry document if successful, None otherwise
        """
        mutation_id = mutation.get("id")
        mutation_type = mutation.get("type", 0)
        description = mutation.get("description", "")
        posting_date = mutation.get("date")

        # Calculate amount from rows if main amount is zero
        amount = frappe.utils.flt(mutation.get("amount", 0), 2)
        rows = mutation.get("rows", [])

        if amount == 0 and rows:
            # Keep sign to detect reversed transactions (negative amount = opposite direction)
            row_amounts = [frappe.utils.flt(row.get("amount", 0), 2) for row in rows]
            amount = sum(row_amounts)
            self.debug_info.append(f"Main amount was 0, calculated {amount} from {len(rows)} rows")

        self.debug_info.append(
            f"Processing money transfer: ID={mutation_id}, Type={mutation_type}, Amount={amount}, Rows={len(rows)}"
        )

        # Get bank account from main ledger - use consolidated ledger utils with auto-create
        ledger_id = mutation.get("ledgerId")
        bank_account = get_erpnext_account_from_ledger_id(
            ledger_id, self.company, self.debug_info, auto_create=True
        )

        if not bank_account:
            # Get ledger code for better error message
            ledger_code = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "ledger_code"
            )
            raise frappe.ValidationError(
                f"No ERPNext account mapped for E-Boekhouden ledger {ledger_id} (code: {ledger_code}). "
                f"Please link the ledger mapping to an ERPNext account before importing."
            )

        self.debug_info.append(f"Using GL account from mapping: {bank_account}")

        # Keep GL Account for Journal Entry creation (accounting documents need GL accounts)
        gl_account = bank_account

        # Convert GL Account to Bank Account name for Bank Transaction creation
        # Uses consolidated utility for consistency across all processors
        # Use _or_raise variant since Bank Transaction creation requires a valid Bank Account
        bank_account_name = convert_gl_account_to_bank_account_or_raise(
            bank_account, self.company, self.debug_info
        )

        # Process all rows to get target accounts with amounts
        # For multi-line mutations, we need to create one JE line per row
        row_entries = []
        total_row_amount = 0

        # All utilities now imported at module level from consolidated utils

        if rows:
            for idx, row in enumerate(rows):
                row_amount = abs(frappe.utils.flt(row.get("amount", 0), 2))

                # Skip zero or near-zero amount rows (< 1 cent)
                if row_amount < 0.01:
                    self.debug_info.append(f"Skipping row {idx + 1} with zero/near-zero amount: {row_amount}")
                    continue

                total_row_amount += row_amount
                row_ledger_id = row.get("ledgerId")

                # Validate ledgerId exists
                if not row_ledger_id:
                    error_msg = f"Row {idx + 1} missing ledgerId (amount: {row_amount})"
                    self.debug_info.append(f"❌ {error_msg}")
                    safe_log_mutation_error(
                        title=f"Missing Row Ledger ID - Mutation {mutation_id}",
                        mutation=mutation,
                        additional_context=f"{error_msg}\nRow data (PII masked): {frappe.as_json(mask_pii_in_mutation(row))}",
                    )
                    raise Exception(error_msg)

                # Map ledger to account
                target_account = get_erpnext_account_from_ledger_id(
                    row_ledger_id, self.company, self.debug_info, auto_create=True
                )

                if not target_account:
                    # Create appropriate account if mapping failed
                    ledger_code = get_ledger_code_from_id(row_ledger_id, self.debug_info)

                    if mutation_type == 5:  # Money Received - need income account
                        line_dict = create_invoice_line_for_tegenrekening(
                            tegenrekening_code=ledger_code,
                            amount=row_amount,
                            description=description,
                            transaction_type="sales",
                        )
                        target_account = line_dict.get("income_account")
                    else:  # Money Paid - need expense account
                        line_dict = create_invoice_line_for_tegenrekening(
                            tegenrekening_code=ledger_code,
                            amount=row_amount,
                            description=description,
                            transaction_type="purchase",
                        )
                        target_account = line_dict.get("expense_account")

                if target_account:
                    row_entries.append(
                        {
                            "account": target_account,
                            "amount": row_amount,
                            "ledger_id": row_ledger_id,
                            "row_index": idx,
                        }
                    )
                    self.debug_info.append(
                        f"Row {idx + 1}/{len(rows)}: Ledger {row_ledger_id} → {target_account}, Amount: {row_amount}"
                    )
                else:
                    error_msg = f"Failed to map row {idx + 1} ledger {row_ledger_id} to account"
                    self.debug_info.append(f"❌ {error_msg}")
                    safe_log_mutation_error(
                        title=f"Row Account Mapping Failed - Mutation {mutation_id}",
                        mutation=mutation,
                        additional_context=f"{error_msg}\nRow data (PII masked): {frappe.as_json(mask_pii_in_mutation(row))}",
                    )
                    raise Exception(error_msg)

        # Validate that row amounts match total mutation amount using shared validation utility
        # Dutch tax authorities (Belastingdienst) require exact amounts in bookkeeping
        is_valid, error_msg, amount_diff = self.validate_row_amounts(mutation, rows, amount)

        if not is_valid:
            # Fail fast - amount mismatches indicate data quality issues
            # Dutch accounting standards require exact amounts for audit compliance
            raise Exception(error_msg)

        if not row_entries:
            # Log detailed failure breakdown showing why each row failed
            error_details = [f"Mutation {mutation_id} has {len(rows)} row(s) but none were valid:"]
            for idx, row in enumerate(rows):
                row_amt = abs(frappe.utils.flt(row.get("amount", 0), 2))
                row_ledger = row.get("ledgerId", "MISSING")
                if row_amt < 0.01:
                    error_details.append(f"  Row {idx + 1}: SKIPPED (zero/near-zero amount: {row_amt})")
                elif not row.get("ledgerId"):
                    error_details.append(f"  Row {idx + 1}: FAILED (missing ledgerId, amount: {row_amt})")
                else:
                    error_details.append(
                        f"  Row {idx + 1}: FAILED (ledgerId: {row_ledger}, amount: {row_amt})"
                    )

            error_msg = "\n".join(error_details)
            self.debug_info.append(f"❌ {error_msg}")
            safe_log_mutation_error(
                title=f"No Valid Rows - Mutation {mutation_id}",
                mutation=mutation,
                additional_context=error_msg,
            )
            raise Exception(f"No valid row entries found for mutation {mutation_id}")

        # Extract party information from description for Bank Transaction
        party_info = None
        try:
            from ..party_extractor import EBoekhoudenPartyExtractor

            party_extractor = EBoekhoudenPartyExtractor(self.company)
            party_info = party_extractor.extract_party_from_mutation(mutation)

            if party_info:
                # Check if this is a bank internal transaction
                if party_info.get("is_bank_internal"):
                    self.debug_info.append(
                        f"🏦 Bank internal transaction detected: {party_info.get('cleaned_description')} "
                        f"(no party needed - interest/fees/charges)"
                    )
                else:
                    self.debug_info.append(
                        f"Extracted party: {party_info.get('party_name')} ({party_info.get('party_type')}) "
                        f"via {party_info.get('extraction_method')}"
                    )
            else:
                self.debug_info.append("No party information extracted from mutation")
        except Exception as e:
            # Party extraction failure is critical - we need to know the party
            error_msg = f"Failed to extract party information from mutation {mutation_id}: {str(e)}"
            self.debug_info.append(f"❌ {error_msg}")
            safe_log_mutation_error(
                title=f"Party Extraction Error - Mutation {mutation_id}",
                mutation=mutation,
                error=e,
                additional_context=error_msg,
            )
            raise  # Re-raise to fail fast

        # Create Journal Entry with Bank Transaction
        try:
            je = frappe.new_doc("Journal Entry")
            je.company = self.company
            je.posting_date = posting_date
            je.voucher_type = "Journal Entry"
            je.eboekhouden_mutation_nr = str(mutation_id)
            je.user_remark = description
            je.cheque_no = f"EB-{mutation_id}"
            je.cheque_date = posting_date

            # Determine actual direction: mutation_type gives intent, but amount sign can reverse it
            # Type 5 (Money Received) with positive amount = incoming, with negative = outgoing
            # Type 6 (Money Paid) with positive amount = outgoing, with negative = incoming
            is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

            if is_incoming:
                # Bank account debited (money comes in) - use total of all rows
                bank_entry = {
                    "account": gl_account,
                    "debit_in_account_currency": total_row_amount,
                    "credit_in_account_currency": 0,
                    "cost_center": self.cost_center,
                    "user_remark": f"Money received - {description}",
                }

                # Try to assign party to bank account entry if appropriate
                if party_info:
                    party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, gl_account)
                    if party_assignment:
                        bank_entry["party_type"] = party_assignment[0]
                        bank_entry["party"] = party_assignment[1]
                        self.debug_info.append(
                            f"Assigned {party_assignment[0]} '{party_assignment[1]}' to bank account entry"
                        )

                je.append("accounts", bank_entry)

                # Create one income line per row
                for row_entry in row_entries:
                    income_entry = {
                        "account": row_entry["account"],
                        "debit_in_account_currency": 0,
                        "credit_in_account_currency": row_entry["amount"],
                        "cost_center": self.cost_center,
                        "user_remark": f"Income - {description} (Row {row_entry['row_index'] + 1})",
                    }

                    # Try to assign party to income account entry if appropriate
                    if party_info:
                        party_assignment = party_extractor.resolve_party_for_journal_entry(
                            party_info, row_entry["account"]
                        )
                        if party_assignment:
                            income_entry["party_type"] = party_assignment[0]
                            income_entry["party"] = party_assignment[1]
                            self.debug_info.append(
                                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to income row {row_entry['row_index'] + 1}"
                            )

                    je.append("accounts", income_entry)

                self.debug_info.append(
                    f"Money Received: Bank {gl_account} debited {total_row_amount}, "
                    f"{len(row_entries)} income line(s) credited"
                )
            else:  # Money going out
                # Bank account credited (money goes out) - use total of all rows
                bank_entry = {
                    "account": gl_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": total_row_amount,
                    "cost_center": self.cost_center,
                    "user_remark": f"Money paid - {description}",
                }

                # Try to assign party to bank account entry if appropriate
                if party_info:
                    party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, gl_account)
                    if party_assignment:
                        bank_entry["party_type"] = party_assignment[0]
                        bank_entry["party"] = party_assignment[1]
                        self.debug_info.append(
                            f"Assigned {party_assignment[0]} '{party_assignment[1]}' to bank account entry"
                        )

                je.append("accounts", bank_entry)

                # Create one expense line per row
                for row_entry in row_entries:
                    expense_entry = {
                        "account": row_entry["account"],
                        "debit_in_account_currency": row_entry["amount"],
                        "credit_in_account_currency": 0,
                        "cost_center": self.cost_center,
                        "user_remark": f"Expense - {description} (Row {row_entry['row_index'] + 1})",
                    }

                    # Try to assign party to expense account entry if appropriate
                    if party_info:
                        party_assignment = party_extractor.resolve_party_for_journal_entry(
                            party_info, row_entry["account"]
                        )
                        if party_assignment:
                            expense_entry["party_type"] = party_assignment[0]
                            expense_entry["party"] = party_assignment[1]
                            self.debug_info.append(
                                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to expense row {row_entry['row_index'] + 1}"
                            )

                    je.append("accounts", expense_entry)

                self.debug_info.append(
                    f"Money Paid: Bank {gl_account} credited {total_row_amount}, "
                    f"{len(row_entries)} expense line(s) debited"
                )

            # Insert Journal Entry with race condition handling
            je, was_duplicate = insert_with_duplicate_handling(je)

            if was_duplicate:
                self.debug_info.append(
                    f"✅ Found existing Journal Entry: {je.name} (duplicate race condition handled)"
                )
                return je

            # Create Bank Transaction with party information (only for new JE)
            bank_transaction_name = self._create_bank_transaction_for_journal_entry(
                mutation, je, gl_account, bank_account_name, party_info
            )

            if bank_transaction_name:
                self.debug_info.append(f"✅ Created Bank Transaction: {bank_transaction_name}")
            else:
                self.debug_info.append("⚠️ Bank Transaction creation failed/skipped")

            # Submit Journal Entry
            je.submit()

            self.debug_info.append(f"✅ Created and submitted Journal Entry: {je.name}")
            return je

        except Exception as e:
            error_msg = f"Failed to create Journal Entry: {str(e)}"
            self.debug_info.append(f"❌ {error_msg}")
            safe_log_mutation_error(
                title=f"Money Transfer Journal Entry Error - Mutation {mutation_id}",
                mutation=mutation,
                error=e,
                additional_context=error_msg,
            )
            raise

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
            # Gateway amount adjustment errors are not critical - log and continue with original
            self.debug_info.append(f"⚠️ Gateway payment {mutation_id}: Error adjusting amount: {str(e)}")
            self.debug_info.append("⚠️ Continuing with original mutation amount")

        # If adjustment failed or not applicable, return original
        return mutation

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
                "Bank Transaction Payments",
                {"parent": bank_transaction_name, "payment_entry": payment_entry_name},
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

            self.debug_info.append(
                f"Linked Bank Transaction {bank_transaction_name} to Payment Entry {payment_entry_name}"
            )

        except Exception as e:
            error_msg = f"Failed to link Bank Transaction to Payment Entry: {str(e)}"
            self.debug_info.append(f"ERROR: {error_msg}")
            frappe.log_error(
                f"Bank Transaction linking failed: {error_msg}",
                "E-Boekhouden Bank Transaction Linking",
            )
            raise

    def _create_bank_transaction_for_journal_entry(
        self,
        mutation: Dict[str, Any],
        journal_entry: frappe._dict,
        gl_account: str,
        bank_account_name: str,
        party_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create Bank Transaction for Journal Entry and link it via payment_entries table.

        Args:
            mutation: E-Boekhouden mutation data
            journal_entry: Created Journal Entry document (draft state)
            gl_account: GL Account used in Journal Entry to find the amount
            bank_account_name: Bank Account DocType name for Bank Transaction creation
            party_info: Optional party information extracted from mutation

        Returns:
            Bank Transaction name if created, None on failure
        """
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        try:
            mutation_id = mutation.get("id")
            mutation_type = mutation.get("type", 0)

            # Get amount from Journal Entry first (needed for both new and existing BT)
            amount = 0
            for account_entry in journal_entry.accounts:
                if account_entry.account == gl_account:
                    # Bank account debit = money in (positive), credit = money out (negative)
                    amount = (
                        account_entry.debit_in_account_currency - account_entry.credit_in_account_currency
                    )
                    break

            # Validate non-zero amount
            if not amount or abs(amount) < 0.01:
                self.debug_info.append(f"Skipping Bank Transaction for zero/near-zero amount: {amount}")
                return None

            # Check if Bank Transaction already exists (idempotency)
            existing_bt = frappe.db.get_value(
                "Bank Transaction",
                {"reference_number": f"EB-{mutation_id}"},
                ["name", "status", "party_type", "party"],
                as_dict=True,
            )

            if existing_bt:
                bt_name = existing_bt.get("name")
                self.debug_info.append(
                    f"Bank Transaction {bt_name} already exists "
                    f"(Status: {existing_bt.get('status')}, "
                    f"Party: {existing_bt.get('party_type')} - {existing_bt.get('party') or 'None'})"
                )

                # Handle party update based on overwrite_existing setting
                if self.overwrite_existing:
                    # Overwrite mode: Delete existing BT and recreate with new party info
                    # This ensures clean slate when re-importing
                    if party_info:
                        self.debug_info.append(
                            f"Overwrite mode: Deleting existing Bank Transaction {bt_name} to recreate with updated party"
                        )
                        try:
                            bt_doc = frappe.get_doc("Bank Transaction", bt_name)
                            if bt_doc.docstatus == 1:
                                bt_doc.cancel()
                            frappe.delete_doc("Bank Transaction", bt_name, force=True)
                            existing_bt = None  # Mark as deleted so new BT will be created below
                        except Exception as e:
                            self.debug_info.append(f"Error deleting Bank Transaction {bt_name}: {str(e)}")
                else:
                    # Update mode: Only update party if BT has no party or has generic party
                    existing_party = existing_bt.get("party")
                    is_generic_party = existing_party and "Bank Transfer" in existing_party

                    if party_info and (not existing_party or is_generic_party):
                        self._update_bank_transaction_party(bt_name, party_info)

                # Link to Journal Entry if BT still exists and not already reconciled
                if existing_bt:  # Check if BT wasn't deleted above
                    if existing_bt.get("status") != "Reconciled":
                        self._link_bank_transaction_to_journal_entry(bt_name, journal_entry.name, abs(amount))
                    else:
                        self.debug_info.append(f"Bank Transaction {bt_name} already reconciled")

                    return bt_name
                # If BT was deleted (overwrite mode), fall through to create new one below

            creator = get_bank_transaction_creator()

            # Use bank description
            bt_description = mutation.get("description", "")
            bt_reference = f"EB-{mutation_id}"

            # Extract party information if available
            party_type = None
            party_name = None

            if party_info:
                # Handle bank internal transactions - use bank as party
                if party_info.get("is_bank_internal"):
                    # Extract bank name from the bank account
                    bank_name = self._extract_bank_name_from_account(bank_account_name)
                    if bank_name:
                        party_type = "Supplier"
                        party_name = bank_name
                        self.debug_info.append(
                            f"🏦 Bank internal transaction: Using bank '{bank_name}' as Supplier"
                        )
                    else:
                        self.debug_info.append(
                            "🏦 Bank internal transaction: Could not extract bank name, creating without party"
                        )
                else:
                    self.debug_info.append(f"Party info available: {party_info}")

                    # First try relation_id (most reliable)
                    relation_id = party_info.get("relation_id")
                    if relation_id:
                        try:
                            # Check if we have a mapping from relation_id to Customer/Supplier
                            expected_party_type = party_info.get("party_type")

                            # Look up by E-Boekhouden relation ID
                            party_name = frappe.db.get_value(
                                expected_party_type, {"eboekhouden_relation_id": str(relation_id)}, "name"
                            )

                            if party_name:
                                party_type = expected_party_type
                                self.debug_info.append(
                                    f"Resolved party via relation_id {relation_id} to {party_type}: {party_name}"
                                )
                        except Exception as e:
                            # Relation ID lookup error - log and continue to try name matching
                            self.debug_info.append(f"⚠️ Relation ID lookup error: {str(e)}")
                            self.debug_info.append("⚠️ Trying party name matching instead")

                    # If relation_id didn't work, try party name (with optional auto-create)
                    if not party_name:
                        extracted_name = party_info.get("party_name")
                        if extracted_name:
                            try:
                                expected_party_type = party_info.get("party_type")

                                # Check if auto-create is enabled
                                settings = frappe.get_single("E-Boekhouden Settings")
                                auto_create = settings.get("auto_create_parties_from_bank_transactions", 0)

                                if auto_create:
                                    # Use BankTransactionParser's find_or_create_party method
                                    from verenigingen.e_boekhouden.utils.bank_transaction_parser import (
                                        BankTransactionParser,
                                    )

                                    parser = BankTransactionParser()

                                    # Extract IBAN from description for IBAN-based matching
                                    iban = None
                                    if party_info.get("extraction_method") == "description_pattern":
                                        parsed_desc = parser.parse_description(bt_description)
                                        iban = parsed_desc.get("iban")

                                    party_name, created_new = parser.find_or_create_party(
                                        extracted_name, expected_party_type, iban
                                    )

                                    if created_new:
                                        self.debug_info.append(
                                            f"✅ Created new {expected_party_type}: '{party_name}' from bank transaction"
                                        )
                                    else:
                                        self.debug_info.append(
                                            f"✅ Matched existing {expected_party_type}: '{party_name}'"
                                        )
                                    party_type = expected_party_type
                                else:
                                    # Auto-create disabled - just try to match existing
                                    field_name = (
                                        "customer_name"
                                        if expected_party_type == "Customer"
                                        else "supplier_name"
                                    )
                                    party_name = frappe.db.get_value(
                                        expected_party_type, {field_name: extracted_name}, "name"
                                    )

                                    if party_name:
                                        party_type = expected_party_type
                                        self.debug_info.append(
                                            f"Resolved party via name '{extracted_name}' to {party_type}: {party_name}"
                                        )
                                    else:
                                        self.debug_info.append(
                                            f"Party '{extracted_name}' not found in {expected_party_type}, "
                                            f"Bank Transaction will be created without party link "
                                            f"(auto-create disabled)"
                                        )
                            except Exception as e:
                                # Party resolution error is critical if auto-create is enabled
                                error_msg = f"Failed to resolve/create party '{extracted_name}': {str(e)}"
                                self.debug_info.append(f"❌ {error_msg}")
                                frappe.log_error(
                                    title=f"Party Resolution Error - Mutation {mutation.get('id')}",
                                    message=f"{error_msg}\n\n{frappe.get_traceback()}",
                                )
                                # If auto-create is enabled, fail fast. If disabled, continue without party.
                                if auto_create:
                                    raise  # Fail fast when auto-create should have worked

            # Create Bank Transaction with party information if available
            transaction_data = {
                "date": journal_entry.posting_date,
                "amount": amount,  # Already has correct sign from debit/credit
                "currency": "EUR",
                "description": bt_description,
                "reference_number": bt_reference,
                "party_type": party_type,
                "party": party_name,
            }

            bank_transaction_name = creator.create_from_dict(
                transaction_data=transaction_data,
                bank_account=bank_account_name,
                company=self.company,
                source_type="E-Boekhouden Import",
            )

            if bank_transaction_name:
                # Get BT status after creation
                bt_status = frappe.db.get_value(
                    "Bank Transaction", bank_transaction_name, ["status", "party_type", "party"], as_dict=True
                )

                self.debug_info.append(
                    f"✅ Created Bank Transaction: {bank_transaction_name} "
                    f"(Status: {bt_status.get('status')}, "
                    f"Party: {bt_status.get('party_type')} - {bt_status.get('party') or 'None'})"
                )

                # Link Bank Transaction to Journal Entry
                self._link_bank_transaction_to_journal_entry(
                    bank_transaction_name, journal_entry.name, abs(amount)
                )

            return bank_transaction_name

        except Exception as e:
            self.debug_info.append(f"ERROR creating Bank Transaction: {str(e)}")
            frappe.log_error(
                f"Failed to create Bank Transaction for Type {mutation_type} mutation {mutation.get('id')}: {str(e)}",
                "E-Boekhouden Journal Entry Bank Transaction Creation",
            )
            return None

    def _extract_bank_name_from_account(self, bank_account: str) -> Optional[str]:
        """
        Extract bank name from ERPNext bank account name.

        Bank accounts typically follow format: "1100 - Triodos - 19.83.96.716 - Algemeen - NVV"
        We want to extract "Triodos" as the bank name.

        Args:
            bank_account: ERPNext bank account name

        Returns:
            Bank name as string or None
        """
        if not bank_account:
            return None

        try:
            # Split by dash and get the second part (bank name)
            parts = bank_account.split(" - ")
            if len(parts) >= 2:
                bank_name = parts[1].strip()

                # Check if this bank exists as a Supplier
                existing_bank = frappe.db.get_value("Supplier", {"supplier_name": bank_name}, "name")
                if existing_bank:
                    return existing_bank

                # Only return bank name if it exists as a Supplier
                # This prevents link validation errors when creating Bank Transactions
                # with non-existent party names like "Kas" (Cash)
                self.debug_info.append(
                    f"Bank '{bank_name}' not found as Supplier - Bank Transaction will be created without party"
                )
                return None

        except Exception as e:
            frappe.logger().warning(f"Could not extract bank name from '{bank_account}': {str(e)}")

        return None

    def _link_bank_transaction_to_journal_entry(
        self, bank_transaction_name: str, journal_entry_name: str, allocated_amount: float
    ):
        """
        Link Bank Transaction to Journal Entry for proper reconciliation.

        Args:
            bank_transaction_name: Bank Transaction name
            journal_entry_name: Journal Entry name (draft state)
            allocated_amount: Amount to allocate (absolute value)
        """
        try:
            # Get Bank Transaction document
            bt = frappe.get_doc("Bank Transaction", bank_transaction_name)

            # Check if already linked
            already_linked = frappe.db.exists(
                "Bank Transaction Payments",
                {"parent": bank_transaction_name, "payment_entry": journal_entry_name},
            )

            if already_linked:
                self.debug_info.append(f"Bank Transaction {bank_transaction_name} already linked to JE")
                return

            # Add to Bank Transaction Payments child table
            bt.append(
                "payment_entries",
                {
                    "payment_document": "Journal Entry",
                    "payment_entry": journal_entry_name,
                    "allocated_amount": allocated_amount,
                },
            )

            # Update Bank Transaction status and amounts
            bt.status = "Reconciled"
            bt.allocated_amount = allocated_amount
            bt.unallocated_amount = 0.0

            # Save the Bank Transaction
            bt.save(ignore_permissions=False)

            self.debug_info.append(
                f"✅ Reconciled Bank Transaction {bank_transaction_name} with Journal Entry {journal_entry_name} "
                f"(Status: Reconciled, Allocated: {allocated_amount:.2f})"
            )

        except Exception as e:
            error_msg = f"Failed to link Bank Transaction to Journal Entry: {str(e)}"
            self.debug_info.append(f"ERROR: {error_msg}")
            frappe.log_error(
                f"Bank Transaction linking to JE failed: {error_msg}",
                "E-Boekhouden Bank Transaction JE Linking",
            )
            raise

    def _update_bank_transaction_party(self, bank_transaction_name: str, party_info: Dict[str, Any]):
        """
        Update Bank Transaction with party information when it exists but doesn't have party data.

        Args:
            bank_transaction_name: Bank Transaction name
            party_info: Party information from mutation extraction
        """
        try:
            extracted_name = party_info.get("party_name")
            if not extracted_name:
                return

            expected_party_type = party_info.get("party_type")

            # Check if auto-create is enabled
            settings = frappe.get_single("E-Boekhouden Settings")
            auto_create = settings.get("auto_create_parties_from_bank_transactions", 0)

            party_name = None
            party_type = None

            if auto_create:
                # Use BankTransactionParser's find_or_create_party method
                from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

                parser = BankTransactionParser()

                # Try to extract IBAN from original description
                bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
                iban = None
                if bt.description:
                    parsed_desc = parser.parse_description(bt.description)
                    iban = parsed_desc.get("iban")

                party_name, created_new = parser.find_or_create_party(
                    extracted_name, expected_party_type, iban
                )

                if created_new:
                    self.debug_info.append(
                        f"✅ Created new {expected_party_type}: '{party_name}' for existing Bank Transaction"
                    )
                else:
                    self.debug_info.append(
                        f"✅ Matched existing {expected_party_type}: '{party_name}' for existing Bank Transaction"
                    )
                party_type = expected_party_type
            else:
                # Auto-create disabled - just try to match existing
                field_name = "customer_name" if expected_party_type == "Customer" else "supplier_name"
                party_name = frappe.db.get_value(expected_party_type, {field_name: extracted_name}, "name")

                if party_name:
                    party_type = expected_party_type
                    self.debug_info.append(
                        f"✅ Matched party '{extracted_name}' to {party_type}: {party_name} for existing Bank Transaction"
                    )

            # Update Bank Transaction if we found/created a party
            if party_name and party_type:
                frappe.db.set_value(
                    "Bank Transaction", bank_transaction_name, {"party_type": party_type, "party": party_name}
                )
                self.debug_info.append(
                    f"Updated Bank Transaction {bank_transaction_name} with party: {party_type} - {party_name}"
                )

        except Exception as e:
            self.debug_info.append(f"ERROR updating Bank Transaction party: {str(e)}")
            frappe.log_error(
                f"Failed to update Bank Transaction party: {str(e)}",
                "E-Boekhouden Bank Transaction Party Update",
            )
