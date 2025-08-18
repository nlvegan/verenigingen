import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.utils.security.api_security_framework import OperationType, standard_api
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
)
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient


class PaymentReconciliationManager:
    """Manages automatic reconciliation of all payment types (SEPA, Mollie) with bank transactions"""

    def __init__(self):
        self.settings = frappe.get_single("Verenigingen Settings")
        self.mollie_settings = frappe.get_single("Mollie Settings")
        self.match_threshold = 0.85  # 85% similarity required for auto-match
        self._validate_bank_transaction_fields()
        self._validate_mollie_accounts()
        self._processed_mollie_payments = set()  # Track processed payment IDs

    def _validate_mollie_accounts(self):
        """Validate that Mollie accounts are properly configured"""
        # Only validate if Mollie fields exist (for backward compatibility)
        if not hasattr(self.mollie_settings, "mollie_bank_account"):
            # Fields don't exist yet - skip validation
            return

        if not self.mollie_settings.mollie_bank_account:
            frappe.log_error(
                "Mollie Bank Account not configured in Mollie Settings", "Mollie Account Configuration"
            )
            return

        if not self.mollie_settings.mollie_clearing_account:
            frappe.log_error(
                "Mollie Clearing Account not configured in Mollie Settings", "Mollie Account Configuration"
            )
            return

        # Validate accounts exist
        if not frappe.db.exists("Account", self.mollie_settings.mollie_bank_account):
            frappe.log_error(
                f"Mollie Bank Account {self.mollie_settings.mollie_bank_account} does not exist",
                "Mollie Account Configuration",
            )

        if not frappe.db.exists("Account", self.mollie_settings.mollie_clearing_account):
            frappe.log_error(
                f"Mollie Clearing Account {self.mollie_settings.mollie_clearing_account} does not exist",
                "Mollie Account Configuration",
            )

    def _validate_bank_transaction_fields(self):
        """Validate that required Bank Transaction fields exist"""
        try:
            meta = frappe.get_meta("Bank Transaction")
            existing_fields = {f.fieldname: f.fieldtype for f in meta.fields}

            required_fields = {
                "deposit": "Currency",
                "withdrawal": "Currency",
                "reference_number": "Data",
                "description": "Text Editor",
                "date": "Date",
                "bank_account": "Link",
                "status": "Select",
            }

            missing_fields = []
            for field_name, expected_type in required_fields.items():
                if field_name not in existing_fields:
                    missing_fields.append(field_name)

            if missing_fields:
                frappe.log_error(
                    f"Missing Bank Transaction fields: {missing_fields}",
                    "SEPA Reconciliation Field Validation",
                )
                frappe.throw(
                    _(
                        "Required Bank Transaction fields not found: {0}. Please check ERPNext version compatibility."
                    ).format(", ".join(missing_fields))
                )

        except Exception as e:
            frappe.log_error(f"Error validating Bank Transaction fields: {str(e)}")
            frappe.throw(_("Unable to validate Bank Transaction fields. Please check system configuration."))

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    @require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
    def reconcile_bank_transactions(self, bank_account=None, from_date=None, to_date=None):
        """Reconcile imported bank transactions with SEPA batches"""

        # Get unreconciled bank transactions
        filters = {"status": "Pending", "reference_type": ["is", "not set"]}

        if bank_account:
            filters["bank_account"] = bank_account

        if from_date:
            filters["date"] = [">=", from_date]

        if to_date:
            filters["date"] = ["<=", to_date]

        transactions = frappe.get_all(
            "Bank Transaction",
            filters=filters,
            fields=[
                "name",
                "date",
                "deposit",  # Standard ERPNext field for credit amounts
                "withdrawal",  # Standard ERPNext field for debit amounts
                "description",
                "bank_account",
                "reference_number",
            ],
        )

        matched_count = 0
        for transaction in transactions:
            if self.match_transaction(transaction):
                matched_count += 1

        return {
            "total_transactions": len(transactions),
            "matched": matched_count,
            "unmatched": len(transactions) - matched_count,
        }

    def match_transaction(self, transaction):
        """Try to match a bank transaction with SEPA payments"""

        # Try different matching strategies
        matches = []

        # Strategy 1: Match by SEPA batch reference
        if transaction.get("reference_number"):
            batch_match = self.match_by_batch_reference(transaction)
            if batch_match:
                matches.append(batch_match)

        # Strategy 2: Match by amount and reference
        amount_match = self.match_by_amount_and_reference(transaction)
        if amount_match:
            matches.append(amount_match)

        # Strategy 2.5: Match Mollie settlements
        mollie_match = self.match_mollie_settlement(transaction)
        if mollie_match:
            matches.append(mollie_match)

        # Strategy 3: Match by description patterns
        desc_match = self.match_by_description(transaction)
        if desc_match:
            matches.append(desc_match)

        # Select best match
        if matches:
            best_match = max(matches, key=lambda x: x["confidence"])
            if best_match["confidence"] >= self.match_threshold:
                return self.create_reconciliation(transaction, best_match)

        return False

    def match_by_batch_reference(self, transaction):
        """Match transaction by SEPA batch reference"""

        # Look for batch reference in transaction description
        batch_pattern = r"BATCH-([A-Z0-9-]+)"
        match = re.search(batch_pattern, transaction.get("description", ""))

        if match:
            batch_ref = match.group(1)

            # Find matching batch
            batch = frappe.db.exists("Direct Debit Batch", {"name": ["like", f"%{batch_ref}%"]})

            if batch:
                batch_doc = frappe.get_doc("Direct Debit Batch", batch)

                # Verify amount matches
                if flt(transaction["deposit"]) == flt(batch_doc.total_amount):
                    return {
                        "type": "batch",
                        "reference": batch,
                        "confidence": 1.0,
                        "match_reason": "Exact batch reference match",
                    }

        return None

    def match_by_amount_and_reference(self, transaction):
        """Match transaction by amount and reference number"""

        amount = self._safe_decimal(transaction.get("deposit", 0))
        reference = transaction.get("reference_number", "").strip()

        if not amount or not reference:
            return None

        # Find invoices with matching amount and reference using safe SQL
        try:
            matching_invoices = frappe.db.sql(
                """
                SELECT
                    ddi.parent as batch,
                    ddi.invoice,
                    ddi.amount,
                    ddi.member_name,
                    si.customer
                FROM `tabDirect Debit Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                LEFT JOIN `tabSales Invoice` si ON si.name = ddi.invoice
                WHERE
                    ddi.amount = %(amount)s
                    AND (ddi.invoice = %(reference)s OR ddb.name LIKE %(batch_ref)s)
                    AND ddb.status IN ('Submitted', 'Processed')
                    AND ddb.batch_date BETWEEN DATE_SUB(%(date)s, INTERVAL 7 DAY) AND DATE_ADD(%(date)s, INTERVAL 7 DAY)
                ORDER BY ddb.batch_date DESC
                LIMIT 10
            """,
                {
                    "amount": amount,
                    "reference": reference,
                    "batch_ref": f"%{reference}%",
                    "date": transaction["date"],
                },
                as_dict=True,
            )
        except frappe.db.DatabaseError as e:
            frappe.log_error(f"Database error in amount/reference matching: {str(e)}")
            return None

        if matching_invoices:
            # If single match, high confidence
            if len(matching_invoices) == 1:
                return {
                    "type": "invoice",
                    "reference": matching_invoices[0]["invoice"],
                    "batch": matching_invoices[0]["batch"],
                    "confidence": 0.95,
                    "match_reason": f'Amount and reference match for {matching_invoices[0]["member_name"]}',
                }
            else:
                # Multiple matches, need more context
                return {
                    "type": "multiple",
                    "matches": matching_invoices,
                    "confidence": 0.7,
                    "match_reason": f"Multiple invoices match amount {amount} and reference {reference}",
                }

        return None

    def match_by_description(self, transaction):
        """Match transaction by description patterns"""

        description = transaction.get("description", "").upper()

        # Common patterns in SEPA descriptions
        patterns = [
            (r"INVOICE\s+([A-Z0-9-]+)", "invoice"),
            (r"MEMBERSHIP\s+([A-Z0-9-]+)", "membership"),
            (r"MEMBER\s+ID\s*:?\s*([A-Z0-9-]+)", "member"),
            (r"MANDATE\s*:?\s*([A-Z0-9-]+)", "mandate"),
        ]

        for pattern, match_type in patterns:
            match = re.search(pattern, description)
            if match:
                reference = match.group(1)

                if match_type == "invoice":
                    if frappe.db.exists("Sales Invoice", reference):
                        return {
                            "type": "invoice",
                            "reference": reference,
                            "confidence": 0.9,
                            "match_reason": "Invoice number found in description",
                        }

                elif match_type == "membership":
                    if frappe.db.exists("Membership", reference):
                        # Get related invoice
                        invoice = frappe.db.get_value(
                            "Sales Invoice",
                            {"membership": reference, "status": ["in", ["Unpaid", "Overdue"]]},
                            "name",
                        )
                        if invoice:
                            return {
                                "type": "invoice",
                                "reference": invoice,
                                "confidence": 0.85,
                                "match_reason": f"Membership {reference} found in description",
                            }

                elif match_type == "member":
                    # Find unpaid invoices for member
                    member_invoices = self.get_member_unpaid_invoices(reference, transaction["deposit"])
                    if member_invoices:
                        return {
                            "type": "member",
                            "reference": member_invoices[0],
                            "confidence": 0.8,
                            "match_reason": f"Member ID {reference} found in description",
                        }

        # Fuzzy matching on member names
        return self.fuzzy_match_member_name(description, transaction["deposit"])

    def match_mollie_settlement(self, transaction):
        """Match bank transaction with Mollie settlements"""

        # Only check transactions on the configured Mollie bank account
        if (
            not hasattr(self.mollie_settings, "mollie_bank_account")
            or not self.mollie_settings.mollie_bank_account
        ):
            return None

        if transaction.get("bank_account") != self.mollie_settings.mollie_bank_account:
            return None

        amount = self._safe_decimal(transaction.get("deposit", 0))
        if not amount:
            return None

        description = transaction.get("description", "").lower()

        # Look for Mollie indicators in description
        mollie_keywords = ["mollie", "settlement", "payout"]
        if not any(keyword in description for keyword in mollie_keywords):
            return None

        try:
            # Initialize Mollie clients to fetch settlement data
            settlements_client = SettlementsClient()

            # Get settlements around the transaction date
            from frappe.utils import add_days

            date_from = add_days(transaction["date"], -3)
            date_to = add_days(transaction["date"], 3)

            settlements = settlements_client.get_settlements_by_date_range(date_from, date_to)

            # Look for exact amount match with proper decimal precision
            for settlement in settlements:
                settlement_amount = self._safe_decimal(settlement.get("amount", {}).get("value", 0))
                amount_decimal = self._safe_decimal(amount)

                is_valid, match_type, difference = self._validate_transaction_amount(
                    amount_decimal, settlement_amount, tolerance_percent=0.1  # 0.1% tolerance
                )

                if is_valid:
                    confidence = 0.98 if match_type == "exact_match" else 0.92
                    return {
                        "type": "mollie_settlement",
                        "reference": settlement.get("id"),
                        "confidence": confidence,
                        "match_reason": f"Mollie settlement {settlement.get('id')} {match_type} (diff: €{difference})",
                        "settlement_data": settlement,
                    }

        except Exception as e:
            frappe.log_error(f"Error matching Mollie settlement: {str(e)}", "Mollie Settlement Matching")

        return None

    def fuzzy_match_member_name(self, description, amount):
        """Try to match based on member name in description"""

        # Get members with unpaid invoices of matching amount using safe SQL
        try:
            members_with_invoices = frappe.db.sql(
                """
                SELECT DISTINCT
                    m.name as member_id,
                    m.full_name,
                    si.name as invoice,
                    si.customer
                FROM `tabMember` m
                JOIN `tabMembership` ms ON ms.member = m.name
                JOIN `tabSales Invoice` si ON si.membership = ms.name
                WHERE
                    si.outstanding_amount = %(amount)s
                    AND si.status IN ('Unpaid', 'Overdue')
                ORDER BY si.due_date DESC
                LIMIT 50
            """,
                {"amount": amount},
                as_dict=True,
            )
        except frappe.db.DatabaseError as e:
            frappe.log_error(f"Database error in fuzzy matching: {str(e)}")
            return None

        best_match = None
        best_score = 0

        for member in members_with_invoices:
            # Calculate similarity between member name and description
            score = SequenceMatcher(None, member["full_name"].upper(), description).ratio()

            if score > best_score and score > 0.6:  # At least 60% match
                best_score = score
                best_match = member

        if best_match:
            return {
                "type": "invoice",
                "reference": best_match["invoice"],
                "confidence": best_score * 0.9,  # Reduce confidence for fuzzy matches
                "match_reason": f'Name match: {best_match["full_name"]} (score: {best_score:.2f})',
            }

        return None

    def get_member_unpaid_invoices(self, member_id, amount):
        """Get unpaid invoices for a member with matching amount"""

        try:
            return frappe.db.sql_list(
                """
                SELECT si.name
                FROM `tabSales Invoice` si
                JOIN `tabMembership` ms ON si.membership = ms.name
                WHERE
                    ms.member = %(member_id)s
                    AND si.outstanding_amount = %(amount)s
                    AND si.status IN ('Unpaid', 'Overdue')
                ORDER BY si.due_date DESC
                LIMIT 5
            """,
                {"member_id": member_id, "amount": amount},
            )
        except frappe.db.DatabaseError as e:
            frappe.log_error(f"Database error getting unpaid invoices: {str(e)}")
            return []

    def create_reconciliation(self, transaction, match):
        """Create reconciliation entry for matched transaction"""

        try:
            # Validate permissions before proceeding
            if not frappe.has_permission("Bank Transaction", "write"):
                frappe.throw(_("Insufficient permissions to update bank transactions"))

            if not frappe.has_permission("Payment Entry", "create"):
                frappe.throw(_("Insufficient permissions to create payment entries"))

            bank_trans = frappe.get_doc("Bank Transaction", transaction["name"])

            if match["type"] in ["invoice", "batch"]:
                # Create payment entry with proper validation
                try:
                    payment_entry = self.create_payment_entry_from_transaction(
                        bank_trans, match["reference"], match.get("batch")
                    )

                    # Update bank transaction
                    bank_trans.status = "Reconciled"
                    bank_trans.reference_type = "Payment Entry"
                    bank_trans.reference_name = payment_entry.name
                    bank_trans.add_comment(
                        "Comment",
                        f'Auto-reconciled: {match["match_reason"]} (Confidence: {match["confidence"]:.0%})',
                    )
                    bank_trans.save()

                    return True

                except frappe.ValidationError as ve:
                    frappe.log_error(
                        f"Mollie settlement validation error: {str(ve)}", "Mollie Settlement Validation"
                    )
                    self._mark_transaction_unreconciled(
                        transaction, f"Mollie settlement validation failed: {str(ve)}"
                    )
                    return False
                except Exception as pe:
                    frappe.log_error(
                        f"Mollie settlement processing error: {str(pe)}", "Mollie Settlement Error"
                    )
                    self._mark_transaction_unreconciled(
                        transaction, f"Mollie settlement processing failed: {str(pe)}"
                    )
                    return False

            elif match["type"] == "mollie_settlement":
                # Process Mollie settlement
                try:
                    settlement_result = self.process_mollie_settlement(
                        bank_trans, match["reference"], match["settlement_data"]
                    )

                    # Update bank transaction with settlement processing details
                    bank_trans.custom_processing_status = "Mollie Settlement Processed"

                    # Add settlement summary to transaction comments
                    summary = (
                        f"Processed {settlement_result['processed_count']}/{settlement_result['total_payments']} "
                        f"payments. Fees: €{settlement_result['mollie_fees']}"
                    )
                    bank_trans.add_comment("Comment", f"Mollie settlement processed: {summary}")

                    # Update bank transaction
                    bank_trans.status = "Reconciled"
                    bank_trans.reference_type = "Mollie Settlement"
                    bank_trans.reference_name = match["reference"]
                    bank_trans.add_comment(
                        "Comment",
                        f'Auto-reconciled: {match["match_reason"]} (Confidence: {match["confidence"]:.0%})',
                    )
                    bank_trans.save()

                    return True

                except frappe.ValidationError as ve:
                    frappe.log_error(f"Validation error in reconciliation: {str(ve)}")
                    return False
                except Exception as pe:
                    frappe.log_error(f"Payment creation error: {str(pe)}")
                    return False

            elif match["type"] == "multiple":
                # Flag for manual review but don't mark as failed
                bank_trans.status = "Pending"
                bank_trans.add_comment(
                    "Comment",
                    f'Multiple matches found: {len(match["matches"])} invoices with amount {transaction["deposit"]} - Manual review required',
                )
                bank_trans.save()
                return False

        except Exception as e:
            frappe.log_error(f"Reconciliation error: {str(e)}", "Payment Reconciliation")
            self._mark_transaction_unreconciled(transaction, f"Reconciliation failed: {str(e)}")
            return False

    def _mark_transaction_unreconciled(self, transaction, reason):
        """Mark transaction as unreconciled with reason for failure"""
        try:
            bank_trans = frappe.get_doc("Bank Transaction", transaction["name"])
            bank_trans.status = "Unmatched"
            bank_trans.add_comment("Comment", f"Reconciliation failed: {reason}")
            bank_trans.save()
            frappe.logger().info(f"Transaction {transaction['name']} marked as unreconciled: {reason}")
        except Exception as e:
            frappe.log_error(
                f"Error marking transaction {transaction['name']} as unreconciled: {str(e)}",
                "Transaction Status Update",
            )

    def _batch_fetch_invoice_data(self, invoice_refs):
        """Batch fetch invoice data to prevent N+1 queries"""
        if not invoice_refs:
            return {}

        try:
            # Filter out None values
            valid_refs = [ref for ref in invoice_refs if ref]

            if not valid_refs:
                return {}

            # Batch fetch all invoice data
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"name": ["in", valid_refs]},
                fields=["name", "grand_total", "outstanding_amount", "customer", "status"],
            )

            # Return as dictionary for quick lookup
            return {inv.name: inv for inv in invoices}

        except Exception as e:
            frappe.log_error(f"Error batch fetching invoice data: {str(e)}", "Invoice Batch Fetch")
            return {}

    def create_payment_entry_from_transaction(self, bank_trans, invoice_name, batch_name=None):
        """Create payment entry from bank transaction"""

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Create payment entry
        payment_entry = get_payment_entry(
            dt="Sales Invoice", dn=invoice.name, party_amount=bank_trans.deposit
        )

        # Set payment details
        payment_entry.posting_date = bank_trans.date
        payment_entry.reference_no = bank_trans.reference_number or batch_name
        payment_entry.reference_date = bank_trans.date
        payment_entry.mode_of_payment = "SEPA Direct Debit"

        # Link to bank transaction
        payment_entry.bank_transaction = bank_trans.name

        # Validate and save with proper permissions
        try:
            payment_entry.insert()

            # Only submit if user has submit permissions
            if frappe.has_permission("Payment Entry", "submit"):
                payment_entry.submit()
            else:
                frappe.log_error(
                    f"User {frappe.session.user} cannot submit payment entry {payment_entry.name}",
                    "SEPA Reconciliation Permission",
                )
                # Return draft payment entry for manual review

        except frappe.ValidationError as e:
            frappe.log_error(f"Payment entry validation failed: {str(e)}")
            frappe.throw(_("Failed to create payment entry: {0}").format(str(e)))
        except Exception as e:
            frappe.log_error(f"Unexpected error creating payment entry: {str(e)}")
            frappe.throw(_("Unexpected error in payment creation. Please check logs."))

        # Update membership payment status with proper validation
        if invoice.membership:
            try:
                if frappe.has_permission("Membership", "write"):
                    membership = frappe.get_doc("Membership", invoice.membership)
                    membership.payment_status = "Paid"
                    membership.payment_date = bank_trans.date
                    # Only ignore validation if absolutely necessary and user has proper permissions
                    if frappe.has_permission("Membership", "submit"):
                        membership.flags.ignore_validate_update_after_submit = True
                        membership.save()
                    else:
                        frappe.log_error(
                            f"Cannot update membership {invoice.membership} - insufficient permissions",
                            "SEPA Reconciliation Permission",
                        )
                else:
                    frappe.log_error(
                        f"Cannot update membership {invoice.membership} - no write permission",
                        "SEPA Reconciliation Permission",
                    )
            except Exception as e:
                frappe.log_error(f"Error updating membership status: {str(e)}")
                # Don't fail the entire reconciliation for membership update errors

        return payment_entry

    def process_mollie_settlement(self, bank_trans, settlement_id, settlement_data):
        """Process a Mollie settlement by reconciling individual payments"""

        try:
            # Get payments for this settlement from Mollie API
            settlements_client = SettlementsClient()
            payments = settlements_client.get_payments_for_settlement(settlement_id)

            processed_payments = []
            total_reconciled = Decimal("0")

            # Pre-fetch all invoice references to prevent N+1 queries
            invoice_refs = []
            for payment in payments:
                invoice_ref = self._extract_invoice_reference(payment)
                if invoice_ref:
                    invoice_refs.append(invoice_ref)

            # Batch fetch invoice data
            self._current_invoice_batch = self._batch_fetch_invoice_data(invoice_refs)

            for payment in payments:
                mollie_payment_id = payment.get("id")

                if not mollie_payment_id:
                    processed_payments.append(
                        {
                            "mollie_payment_id": "unknown",
                            "status": "error",
                            "error": "Missing Mollie payment ID",
                        }
                    )
                    continue

                # Check for duplicates
                if self._is_mollie_payment_processed(mollie_payment_id):
                    processed_payments.append(
                        {
                            "mollie_payment_id": mollie_payment_id,
                            "status": "duplicate",
                            "note": "Payment already processed",
                        }
                    )
                    continue

                try:
                    # Extract invoice reference from payment metadata or description
                    invoice_ref = self._extract_invoice_reference(payment)
                    payment_amount = self._safe_decimal(payment.get("amount", {}).get("value", 0))

                    if invoice_ref:
                        # Use batched invoice data if available, otherwise fetch individually
                        if (
                            hasattr(self, "_current_invoice_batch")
                            and invoice_ref in self._current_invoice_batch
                        ):
                            invoice_data = self._current_invoice_batch[invoice_ref]
                            invoice_amount = self._safe_decimal(invoice_data.grand_total)
                        elif frappe.db.exists("Sales Invoice", invoice_ref):
                            invoice_amount = self._safe_decimal(
                                frappe.db.get_value("Sales Invoice", invoice_ref, "grand_total")
                            )
                        else:
                            processed_payments.append(
                                {
                                    "mollie_payment_id": mollie_payment_id,
                                    "invoice": invoice_ref,
                                    "amount": str(payment_amount),
                                    "status": "invoice_not_found",
                                    "error": f"Invoice {invoice_ref} not found",
                                }
                            )
                            continue

                        is_valid, match_type, difference = self._validate_transaction_amount(
                            payment_amount, invoice_amount, tolerance_percent=1.0
                        )

                        if not is_valid:
                            processed_payments.append(
                                {
                                    "mollie_payment_id": mollie_payment_id,
                                    "invoice": invoice_ref,
                                    "amount": str(payment_amount),
                                    "status": "amount_mismatch",
                                    "error": f"Payment amount €{payment_amount} doesn't match invoice €{invoice_amount} (diff: €{difference})",
                                }
                            )
                            continue

                        # Create payment entry for this specific Mollie payment
                        payment_entry = self._create_mollie_payment_entry(
                            bank_trans, invoice_ref, payment, settlement_data
                        )

                        # Mark as processed
                        self._mark_mollie_payment_processed(mollie_payment_id)

                        processed_payments.append(
                            {
                                "mollie_payment_id": mollie_payment_id,
                                "invoice": invoice_ref,
                                "amount": str(payment_amount),
                                "payment_entry": payment_entry.name,
                                "status": "success",
                                "match_type": match_type,
                            }
                        )

                        total_reconciled += payment_amount

                    else:
                        processed_payments.append(
                            {
                                "mollie_payment_id": mollie_payment_id,
                                "invoice": None,
                                "amount": str(payment_amount),
                                "status": "no_invoice_match",
                                "note": f"Could not match payment to invoice. Searched for: {invoice_ref or 'no reference found'}",
                            }
                        )

                except frappe.ValidationError as ve:
                    processed_payments.append(
                        {
                            "mollie_payment_id": mollie_payment_id,
                            "status": "validation_error",
                            "error": str(ve),
                        }
                    )
                    frappe.log_error(
                        f"Validation error processing Mollie payment {mollie_payment_id}: {str(ve)}",
                        "Mollie Payment Validation",
                    )

                except Exception as e:
                    processed_payments.append(
                        {"mollie_payment_id": mollie_payment_id, "status": "error", "error": str(e)}
                    )
                    frappe.log_error(
                        f"Unexpected error processing Mollie payment {mollie_payment_id}: {str(e)}",
                        "Mollie Payment Processing",
                    )

            # Handle Mollie fees by creating clearing account entries
            settlement_amount = self._safe_decimal(settlement_data.get("amount", {}).get("value", 0))
            mollie_fees = total_reconciled - settlement_amount

            if abs(mollie_fees) > Decimal("0.01"):  # If there are fees
                self._create_mollie_fee_entry(bank_trans, mollie_fees, settlement_data)

            return {
                "type": "mollie_settlement",
                "settlement_id": settlement_id,
                "total_payments": len(payments),
                "processed_count": len([p for p in processed_payments if p["status"] == "success"]),
                "failed_count": len([p for p in processed_payments if p["status"] == "error"]),
                "unmatched_count": len([p for p in processed_payments if p["status"] == "no_invoice_match"]),
                "total_reconciled": str(total_reconciled),
                "mollie_fees": str(mollie_fees),
                "details": processed_payments,
            }

        except Exception as e:
            frappe.log_error(f"Error processing Mollie settlement {settlement_id}: {str(e)}")
            raise

    def _extract_invoice_reference(self, payment):
        """Extract invoice reference from Mollie payment"""

        # Check metadata first
        metadata = payment.get("metadata", {})
        if metadata.get("invoice_id"):
            return metadata["invoice_id"]

        # Check description for invoice patterns
        description = payment.get("description", "")
        import re

        # Look for invoice patterns like "SI-2024-001" or "Invoice: SI-2024-001"
        patterns = [
            r"\b(SI-\d{4}-\d{3,4})\b",
            r"\b(ACC-INV-\d{4}-\d{3,4})\b",
            r"Invoice:?\s*([A-Z0-9-]+)",
            r"\b([A-Z]{2,3}-\d{4}-\d{3,4})\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _create_mollie_payment_entry(self, bank_trans, invoice_name, mollie_payment, settlement_data):
        """Create payment entry for a Mollie payment"""

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        payment_amount = self._safe_decimal(mollie_payment.get("amount", {}).get("value", 0))

        # Create payment entry via clearing account
        payment_entry = get_payment_entry(dt="Sales Invoice", dn=invoice.name, party_amount=payment_amount)

        # Set payment details
        payment_entry.posting_date = bank_trans.date
        payment_entry.reference_no = mollie_payment.get("id")
        payment_entry.reference_date = bank_trans.date
        payment_entry.mode_of_payment = "Mollie"

        # Use clearing account instead of direct bank account
        if (
            hasattr(self.mollie_settings, "mollie_clearing_account")
            and self.mollie_settings.mollie_clearing_account
        ):
            payment_entry.paid_from = self.mollie_settings.mollie_clearing_account

        # Add custom fields for tracking
        payment_entry.custom_mollie_payment_id = mollie_payment.get("id")
        payment_entry.custom_mollie_settlement_id = settlement_data.get("id")
        payment_entry.custom_bank_transaction = bank_trans.name

        # Validate and save
        payment_entry.insert()
        if frappe.has_permission("Payment Entry", "submit"):
            payment_entry.submit()

        return payment_entry

    def _create_mollie_fee_entry(self, bank_trans, fee_amount, settlement_data):
        """Create journal entry for Mollie fees"""

        fee_amount_decimal = self._safe_decimal(fee_amount)
        if abs(fee_amount_decimal) < Decimal("0.01"):
            return None

        from frappe import get_doc

        # Check if Mollie accounts are configured
        if (
            not hasattr(self.mollie_settings, "mollie_clearing_account")
            or not self.mollie_settings.mollie_clearing_account
        ):
            frappe.log_error(
                "Cannot create Mollie fee entry - clearing account not configured", "Mollie Fee Processing"
            )
            return None

        # Create journal entry for fees
        accounts = [
            {
                "account": self.mollie_settings.mollie_clearing_account,
                "debit_in_account_currency": float(abs(fee_amount_decimal)) if fee_amount_decimal > 0 else 0,
                "credit_in_account_currency": float(abs(fee_amount_decimal)) if fee_amount_decimal < 0 else 0,
            },
            {
                "account": self._get_payment_processing_fees_account(),
                "debit_in_account_currency": float(abs(fee_amount_decimal)) if fee_amount_decimal < 0 else 0,
                "credit_in_account_currency": float(abs(fee_amount_decimal)) if fee_amount_decimal > 0 else 0,
            },
        ]

        journal_entry = get_doc(
            {
                "doctype": "Journal Entry",
                "posting_date": bank_trans.date,
                "voucher_type": "Journal Entry",
                "user_remark": f"Mollie settlement fees - Settlement {settlement_data.get('id')}",
                "accounts": accounts,
            }
        )

        journal_entry.insert()
        if frappe.has_permission("Journal Entry", "submit"):
            journal_entry.submit()

        return journal_entry

    def _get_payment_processing_fees_account(self):
        """Get configured payment processing fees account"""

        # Check if configured in Mollie Settings
        if (
            hasattr(self.mollie_settings, "payment_processing_fees_account")
            and self.mollie_settings.payment_processing_fees_account
        ):
            return self.mollie_settings.payment_processing_fees_account

        # Try to find a suitable account by name patterns
        fee_account_patterns = [
            "Payment Processing Fees",
            "Transaction Fees",
            "Banking Fees",
            "Financial Service Charges",
        ]

        for pattern in fee_account_patterns:
            account = frappe.db.get_value("Account", {"account_name": ["like", f"%{pattern}%"]}, "name")
            if account:
                return account

        # Fallback: create or find expense account
        expense_accounts = frappe.get_all(
            "Account",
            filters={"account_type": "Expense", "is_group": 0},
            fields=["name", "account_name"],
            limit=1,
        )

        if expense_accounts:
            frappe.log_error(
                f"Using fallback expense account {expense_accounts[0]['name']} for Mollie fees. "
                "Please configure payment_processing_fees_account in Mollie Settings.",
                "Mollie Fee Account Fallback",
            )
            return expense_accounts[0]["name"]

        frappe.throw(
            _(
                "No suitable account found for payment processing fees. Please configure payment_processing_fees_account in Mollie Settings."
            )
        )

    def _safe_decimal(self, value, description="amount"):
        """Safely convert value to Decimal with proper error handling"""
        if value is None:
            return Decimal("0")

        try:
            if isinstance(value, (int, float)):
                return Decimal(str(value))
            elif isinstance(value, str):
                # Handle string amounts that might have currency symbols
                cleaned = re.sub(r"[^\d\.-]", "", value)
                return Decimal(cleaned) if cleaned else Decimal("0")
            elif isinstance(value, Decimal):
                return value
            else:
                frappe.log_error(f"Unexpected {description} type: {type(value)}, value: {value}")
                return Decimal("0")
        except (InvalidOperation, ValueError) as e:
            frappe.log_error(f"Error converting {description} '{value}' to Decimal: {str(e)}")
            return Decimal("0")

    def _is_mollie_payment_processed(self, mollie_payment_id):
        """Check if Mollie payment has already been processed"""
        if mollie_payment_id in self._processed_mollie_payments:
            return True

        # Check database for existing payment entries with this Mollie payment ID
        existing = frappe.db.exists(
            "Payment Entry", {"custom_mollie_payment_id": mollie_payment_id, "docstatus": 1}
        )

        if existing:
            self._processed_mollie_payments.add(mollie_payment_id)
            return True

        return False

    def _mark_mollie_payment_processed(self, mollie_payment_id):
        """Mark Mollie payment as processed"""
        self._processed_mollie_payments.add(mollie_payment_id)

    def _validate_transaction_amount(self, transaction_amount, expected_amount, tolerance_percent=1.0):
        """Validate transaction amounts with proper decimal precision"""
        try:
            trans_decimal = self._safe_decimal(transaction_amount, "transaction amount")
            expected_decimal = self._safe_decimal(expected_amount, "expected amount")

            if trans_decimal == expected_decimal:
                return True, "exact_match", Decimal("0")

            difference = abs(trans_decimal - expected_decimal)
            tolerance = expected_decimal * Decimal(str(tolerance_percent / 100))

            if difference <= tolerance:
                return True, "within_tolerance", difference
            else:
                return False, "outside_tolerance", difference

        except Exception as e:
            frappe.log_error(f"Error validating transaction amounts: {str(e)}")
            return False, "validation_error", Decimal("0")


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
@require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_VALIDATE)
def process_sepa_return_file(file_content, file_type="pain.002"):
    """Process SEPA return/status file from bank"""

    PaymentReconciliationManager()

    if file_type == "pain.002":
        # Parse pain.002 status report
        return_data = parse_pain002_file(file_content)
    else:
        # Parse other formats (MT940, CAMT, etc.)
        frappe.throw(_("File type {0} not yet supported").format(file_type))

    processed_count = 0

    for return_item in return_data:
        if return_item["status"] == "Rejected":
            # Handle rejection
            handle_payment_rejection(
                return_item["end_to_end_id"], return_item["reason_code"], return_item["reason_text"]
            )
            processed_count += 1

        elif return_item["status"] == "Accepted":
            # Mark as successfully processed
            mark_payment_successful(return_item["end_to_end_id"])
            processed_count += 1

    return {"processed": processed_count, "total": len(return_data)}


def parse_pain002_file(file_content):
    """Parse pain.002 XML file"""
    # Implementation would parse the XML and extract status information
    # This is a placeholder for the actual XML parsing logic


def handle_payment_rejection(end_to_end_id, reason_code, reason_text):
    """Handle rejected SEPA payment"""

    # Extract invoice number from end-to-end ID
    invoice_match = re.search(r"E2E-(.+)", end_to_end_id)
    if not invoice_match:
        return

    invoice_name = invoice_match.group(1)

    # Schedule retry
    from verenigingen.utils.payment_retry import PaymentRetryManager

    retry_manager = PaymentRetryManager()
    retry_manager.schedule_retry(invoice_name, reason_code, reason_text)


def mark_payment_successful(end_to_end_id):
    """Mark payment as successful"""

    # Extract invoice number from end-to-end ID
    invoice_match = re.search(r"E2E-(.+)", end_to_end_id)
    if not invoice_match:
        return

    invoice_name = invoice_match.group(1)

    # Update invoice status
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.status in ["Unpaid", "Overdue"]:
        # Payment will be created when bank transaction is imported
        invoice.add_comment("Comment", "SEPA payment accepted by bank")


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
def get_reconciliation_summary(from_date=None, to_date=None):
    """Get summary of reconciliation status"""

    filters = {}
    if from_date:
        filters["date"] = [">=", from_date]
    if to_date:
        filters["date"] = ["<=", to_date]

    summary = {
        "total_transactions": frappe.db.count("Bank Transaction", filters),
        "reconciled": frappe.db.count("Bank Transaction", {**filters, "status": "Reconciled"}),
        "pending": frappe.db.count("Bank Transaction", {**filters, "status": "Pending"}),
        "unmatched": frappe.db.count("Bank Transaction", {**filters, "status": "Unmatched"}),
    }

    summary["reconciliation_rate"] = (
        (summary["reconciled"] / summary["total_transactions"] * 100)
        if summary["total_transactions"] > 0
        else 0
    )

    return summary


def reconcile_bank_transactions(bank_account=None, from_date=None, to_date=None):
    """Module-level function for scheduled job to reconcile bank transactions"""
    manager = PaymentReconciliationManager()
    return manager.reconcile_bank_transactions(bank_account, from_date, to_date)
