"""
Settlement Bank Transaction Processor
Creates ERPNext Bank Transactions from Mollie Settlements

This processor bridges the gap between Mollie settlements (payouts to your bank)
and ERPNext Bank Transactions, enabling automated reconciliation of settlement
deposits against underlying Payment Entries.

Business Workflow:
1. Mollie pays out €10,000 to your bank account
2. You see the deposit in your bank statement with reference "1234.5678.90"
3. You call this processor with the bank reference
4. It creates a Bank Transaction in ERPNext
5. It links the BT to underlying Payment Entries via remarks
6. You can then use Bank Reconciliation Tool to match and reconcile

Security: Uses critical_api decorator for financial operations
Audit: Full logging of settlement processing activities
"""

from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.services.settlement_cache import get_settlement_cache


class SettlementBankTransactionProcessor:
    """
    Process Mollie settlements into ERPNext Bank Transactions.

    Links settlement deposits to underlying Payment Entries for
    automated bank reconciliation via ERPNext Bank Reconciliation Tool.

    Uses settlement cache to work around Mollie API limitations.
    """

    def __init__(self):
        self.settlements_client = SettlementsClient()
        self.settlement_cache = get_settlement_cache()
        self.dues_processor = DuesPaymentProcessor()

    def process_settlement_deposit(
        self, settlement_id: Optional[str] = None, bank_reference: Optional[str] = None
    ) -> Dict:
        """
        Create Bank Transaction from Mollie settlement.

        This method handles the complete workflow of converting a Mollie settlement
        (payout to your bank) into an ERPNext Bank Transaction with proper linkage
        to underlying Payment Entries.

        Args:
            settlement_id: Mollie settlement ID (e.g., "stl_jDk30akdN")
            bank_reference: Bank reference from statement (e.g., "1234.5678.90")
                           One of settlement_id or bank_reference must be provided.

        Returns:
            dict: {
                "status": "success" | "error" | "already_processed",
                "bank_transaction": str (BT name if created),
                "settlement_id": str,
                "settlement_reference": str (bank reference),
                "amount": float,
                "linked_payment_entries": int (count of linked PEs),
                "reconciliation_details": dict with counts,
                "message": str (if already processed or error),
                "error": str (if error occurred)
            }

        Raises:
            frappe.ValidationError: If configuration is missing or invalid
        """
        result = {"status": "pending", "settlement_id": None, "bank_transaction": None}

        try:
            # Step 1: Lookup settlement by bank reference or ID
            settlement = self._get_settlement(settlement_id, bank_reference)
            if isinstance(settlement, dict) and settlement.get("status") == "error":
                return settlement

            result["settlement_id"] = settlement.id
            result["settlement_reference"] = settlement.reference

            # Step 2: Get detailed reconciliation data (use direct method to avoid re-fetching)
            reconciliation = self._reconcile_settlement_from_object(settlement)

            # Step 3: Validate configuration
            config_validation = self._validate_configuration()
            if config_validation.get("status") == "error":
                return config_validation

            bank_account = config_validation["bank_account"]
            company = config_validation["company"]

            # Step 4: Check for duplicate processing
            existing_check = self._check_existing_bank_transaction(settlement.id)
            if existing_check["exists"]:
                return {
                    "status": "already_processed",
                    "bank_transaction": existing_check["name"],
                    "settlement_id": settlement.id,
                    "settlement_reference": settlement.reference,
                    "message": f"Bank Transaction {existing_check['name']} already exists for this settlement",
                }

            # Step 5: Extract settlement financial data
            settlement_amount = float(settlement.amount.decimal_value) if settlement.amount else 0.0
            currency = settlement.amount.currency if settlement.amount else "EUR"
            settlement_date = getdate(settlement.settled_at) if settlement.settled_at else getdate()

            # Step 6: Create Bank Transaction
            bank_transaction = self._create_bank_transaction(
                bank_account=bank_account,
                company=company,
                settlement_date=settlement_date,
                settlement_amount=settlement_amount,
                currency=currency,
                settlement=settlement,
                reconciliation=reconciliation,
            )

            # Step 7: Link underlying Payment Entries
            payment_entries_linked = self._link_payment_entries(
                bank_transaction.name, settlement.id, reconciliation
            )

            # Step 8: Commit transaction to database
            frappe.db.commit()

            # Step 9: Log success
            frappe.logger().info(
                f"✅ Created Bank Transaction {bank_transaction.name} for settlement {settlement.id} "
                f"(amount: {currency} {settlement_amount}, linked PEs: {payment_entries_linked})"
            )

            return {
                "status": "success",
                "bank_transaction": bank_transaction.name,
                "settlement_id": settlement.id,
                "settlement_reference": settlement.reference,
                "amount": settlement_amount,
                "currency": currency,
                "linked_payment_entries": payment_entries_linked,
                "reconciliation_details": {
                    "payments_count": reconciliation["components"]["payments"]["count"],
                    "payments_total": reconciliation["components"]["payments"]["total"],
                    "refunds_count": reconciliation["components"]["refunds"]["count"],
                    "refunds_total": reconciliation["components"]["refunds"]["total"],
                    "chargebacks_count": reconciliation["components"]["chargebacks"]["count"],
                    "chargebacks_total": reconciliation["components"]["chargebacks"]["total"],
                    "reconciled": reconciliation["reconciled"],
                    "discrepancy": reconciliation["discrepancy"],
                },
            }

        except Exception as e:
            error_msg = str(e)
            frappe.log_error(
                f"Error processing settlement deposit: {error_msg}",
                "Settlement Bank Transaction Processing Error",
            )
            return {
                "status": "error",
                "error": error_msg,
                "settlement_id": result.get("settlement_id"),
            }

    def _get_settlement(self, settlement_id: Optional[str], bank_reference: Optional[str]):
        """
        Retrieve settlement from cache by ID or bank reference.

        Uses settlement cache to work around Mollie API limitation where
        individual settlement retrieval is not supported via the standard API.

        Args:
            settlement_id: Mollie settlement ID
            bank_reference: Bank reference from statement

        Returns:
            Settlement object or error dict
        """
        if not settlement_id and not bank_reference:
            return {
                "status": "error",
                "error": "Must provide either settlement_id or bank_reference",
            }

        # Try to get settlement from cache
        settlement = self.settlement_cache.get_settlement(
            settlement_id=settlement_id, bank_reference=bank_reference
        )

        if not settlement:
            # Not found even after cache refresh
            identifier = settlement_id or bank_reference
            return {
                "status": "error",
                "error": f"Settlement not found: {identifier}. "
                "Note: Only settlements from the last 90 days are available.",
            }

        return settlement

    def _reconcile_settlement_from_object(self, settlement) -> Dict:
        """
        Reconcile a settlement using an existing settlement object.

        This avoids the API limitation where individual settlements cannot be retrieved.

        Args:
            settlement: Settlement object from cache

        Returns:
            Dict with reconciliation results
        """
        # Get all components (these endpoints work fine)
        payments = self.settlements_client.list_settlement_payments(settlement.id)
        refunds = self.settlements_client.list_settlement_refunds(settlement.id)
        chargebacks = self.settlements_client.list_settlement_chargebacks(settlement.id)
        captures = self.settlements_client.list_settlement_captures(settlement.id)

        # Calculate totals
        payment_total = sum(Decimal(p.get("settlementAmount", {}).get("value", "0")) for p in payments)
        refund_total = sum(Decimal(r.get("settlementAmount", {}).get("value", "0")) for r in refunds)
        chargeback_total = sum(Decimal(c.get("settlementAmount", {}).get("value", "0")) for c in chargebacks)
        capture_total = sum(
            c.settlement_amount.decimal_value
            for c in captures
            if c.settlement_amount and hasattr(c.settlement_amount, "decimal_value")
        )

        # Calculate expected vs actual
        calculated_total = payment_total - refund_total - chargeback_total

        actual_amount = Decimal("0")
        if settlement.amount and hasattr(settlement.amount, "decimal_value"):
            actual_amount = settlement.amount.decimal_value

        discrepancy = actual_amount - calculated_total

        reconciliation = {
            "settlement_id": settlement.id,
            "status": settlement.status,
            "reference": settlement.reference,
            "components": {
                "payments": {"count": len(payments), "total": float(payment_total)},
                "refunds": {"count": len(refunds), "total": float(refund_total)},
                "chargebacks": {"count": len(chargebacks), "total": float(chargeback_total)},
                "captures": {"count": len(captures), "total": float(capture_total)},
            },
            "calculated_total": float(calculated_total),
            "actual_amount": float(actual_amount),
            "discrepancy": float(discrepancy),
            "reconciled": abs(discrepancy) < Decimal("0.01"),
            "revenue": float(settlement.get_total_revenue()),
            "costs": float(settlement.get_total_costs()),
            "reconciled_at": frappe.utils.now(),
        }

        # Log discrepancy if exists
        if not reconciliation["reconciled"]:
            frappe.logger().warning(f"⚠️ Settlement {settlement.id} has discrepancy: €{abs(discrepancy):.2f}")

        return reconciliation

    def _validate_configuration(self) -> Dict:
        """
        Validate Mollie and ERPNext configuration for settlement processing.

        Returns:
            dict: Configuration details or error
        """
        # Get Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")
        mollie_bank_account_gl = mollie_settings.mollie_bank_account

        if not mollie_bank_account_gl:
            return {
                "status": "error",
                "error": "Mollie Bank Account not configured in Mollie Settings. "
                "Please configure it to specify where settlement deposits are received.",
            }

        # Get Bank Account linked to GL Account
        bank_account = frappe.db.get_value("Bank Account", {"account": mollie_bank_account_gl}, "name")

        if not bank_account:
            return {
                "status": "error",
                "error": f"No Bank Account found linked to GL Account '{mollie_bank_account_gl}'. "
                f"Please create a Bank Account record and link it to this account.",
            }

        # Get company
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default("company")

        if not company:
            return {"status": "error", "error": "No company configured for settlement processing"}

        return {
            "status": "valid",
            "mollie_bank_account_gl": mollie_bank_account_gl,
            "bank_account": bank_account,
            "company": company,
        }

    def _check_existing_bank_transaction(self, settlement_id: str) -> Dict:
        """
        Check if Bank Transaction already exists for this settlement.

        Args:
            settlement_id: Mollie settlement ID

        Returns:
            dict: {"exists": bool, "name": str or None}
        """
        existing_bt = frappe.db.get_value("Bank Transaction", {"reference_number": settlement_id}, "name")

        return {"exists": bool(existing_bt), "name": existing_bt}

    def _create_bank_transaction(
        self,
        bank_account: str,
        company: str,
        settlement_date,
        settlement_amount: float,
        currency: str,
        settlement,
        reconciliation: Dict,
    ):
        """
        Create and submit Bank Transaction for settlement deposit.

        Args:
            bank_account: ERPNext Bank Account name
            company: Company name
            settlement_date: Date of settlement
            settlement_amount: Amount in settlement currency
            currency: Currency code
            settlement: Mollie settlement object
            reconciliation: Settlement reconciliation details

        Returns:
            Bank Transaction document
        """
        bank_transaction = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": settlement_date,
                "deposit": settlement_amount,
                "withdrawal": 0.0,
                "currency": currency,
                "bank_account": bank_account,
                "company": company,
                "reference_number": settlement.id,  # Mollie settlement ID
                "description": self._build_settlement_description(settlement, reconciliation),
                "status": "Unreconciled",
                "unallocated_amount": settlement_amount,
            }
        )

        bank_transaction.insert()
        bank_transaction.submit()

        return bank_transaction

    def _build_settlement_description(self, settlement, reconciliation: Dict) -> str:
        """
        Build human-readable description for Bank Transaction.

        Args:
            settlement: Mollie settlement object
            reconciliation: Settlement reconciliation details

        Returns:
            str: Description text
        """
        components = reconciliation["components"]
        parts = []

        if components["payments"]["count"] > 0:
            parts.append(f"{components['payments']['count']} payments")
        if components["refunds"]["count"] > 0:
            parts.append(f"{components['refunds']['count']} refunds")
        if components["chargebacks"]["count"] > 0:
            parts.append(f"{components['chargebacks']['count']} chargebacks")

        component_str = ", ".join(parts) if parts else "no transactions"

        # Add discrepancy (Mollie fees) if present
        description = f"Mollie settlement {settlement.reference} ({component_str})"

        discrepancy = reconciliation.get("discrepancy", 0)
        if abs(discrepancy) >= 0.01:
            # Show as negative if settlement is less than gross (normal case - fees deducted)
            fee_amount = abs(discrepancy)
            description += f" | Fees: EUR {fee_amount:.2f}"

        return description

    def _link_payment_entries(
        self, bank_transaction_name: str, settlement_id: str, reconciliation: Dict
    ) -> int:
        """
        Find Payment Entries from this settlement and add settlement metadata.

        We can't auto-reconcile them here because ERPNext Bank Reconciliation Tool
        requires manual matching, but we add metadata to Payment Entry remarks
        to help with the reconciliation process.

        Args:
            bank_transaction_name: Created Bank Transaction name
            settlement_id: Mollie settlement ID
            reconciliation: Settlement reconciliation details

        Returns:
            int: Count of Payment Entries that were linked
        """
        linked_count = 0

        try:
            # Get all payment IDs in this settlement
            settlement_payments = self.settlements_client.list_settlement_payments(settlement_id)

            for payment in settlement_payments:
                payment_id = payment.get("id")

                # Find Payment Entry with this Mollie payment reference
                pe_name = frappe.db.get_value(
                    "Payment Entry", {"reference_no": payment_id, "docstatus": 1}, "name"
                )

                if pe_name:
                    try:
                        # Add remark noting which settlement and Bank Transaction it belongs to
                        pe = frappe.get_doc("Payment Entry", pe_name)

                        existing_remark = pe.remarks or ""
                        settlement_note = f"\n[Mollie Settlement: {settlement_id}, Bank Transaction: {bank_transaction_name}]"

                        # Only add if not already present
                        if settlement_note not in existing_remark:
                            pe.remarks = existing_remark + settlement_note
                            pe.db_update()
                            linked_count += 1

                            frappe.logger().info(
                                f"✅ Linked Payment Entry {pe_name} to settlement {settlement_id}"
                            )
                    except Exception as link_error:
                        frappe.logger().warning(
                            f"⚠️ Could not link Payment Entry {pe_name} to settlement: {link_error}"
                        )
                        # Continue processing other payments even if one fails

        except Exception as e:
            frappe.logger().warning(f"⚠️ Error linking Payment Entries for settlement {settlement_id}: {e}")
            # Don't fail the entire settlement processing just because linking failed

        return linked_count

    def _create_individual_payment_transactions(
        self, settlement_id: str, reconciliation: Dict, company: str
    ) -> Dict:
        """
        Create individual Bank Transactions for each payment in the settlement.

        These are deposited to the Mollie Clearing Account (not the bank account)
        and can be reconciled against Sales Invoices or linked to Customers/Members.

        Uses the existing DuesPaymentProcessor infrastructure for consistent processing.

        Args:
            settlement_id: Mollie settlement ID
            reconciliation: Settlement reconciliation details
            company: Company name

        Returns:
            dict: {
                "created_count": int,
                "skipped_count": int,
                "total_amount": float,
                "transactions": List[str] (names of created BTs)
            }
        """
        result = {
            "created_count": 0,
            "skipped_count": 0,
            "total_amount": 0.0,
            "transactions": [],
        }

        # Get Mollie Clearing Account from settings
        mollie_settings = frappe.get_single("Mollie Settings")
        clearing_account_gl = mollie_settings.mollie_clearing_account

        if not clearing_account_gl:
            frappe.logger().warning(
                "⚠️ Mollie Clearing Account not configured - skipping individual payment transactions"
            )
            return result

        # Get Bank Account for clearing account
        clearing_bank_account = frappe.db.get_value("Bank Account", {"account": clearing_account_gl}, "name")

        if not clearing_bank_account:
            frappe.logger().warning(
                f"⚠️ No Bank Account found for clearing account '{clearing_account_gl}' - skipping individual payments"
            )
            return result

        # Get all payments in settlement (these are dictionaries from API)
        payments = self.settlements_client.list_settlement_payments(settlement_id)

        for payment_dict in payments:
            try:
                payment_id = payment_dict.get("id")

                # Check if already processed (either as Payment Entry or Bank Transaction)
                idempotency_check = self.dues_processor.check_payment_already_processed(payment_id)
                if idempotency_check["already_processed"]:
                    result["skipped_count"] += 1
                    continue

                # Fetch full payment object from Mollie API (needed for existing method)
                payment_obj = self.dues_processor.mollie_client.sdk_client.payments.get(payment_id)

                # Determine if this is a dues payment or donation
                payment_type = self.dues_processor.identify_payment_type(payment_obj)

                if payment_type == "dues":
                    # Try to find member for dues payments
                    member_name = self.dues_processor.find_member_for_payment(payment_obj)

                    if member_name:
                        # Use existing infrastructure for dues payments
                        bt_name = self.dues_processor._create_bank_transaction_for_dues(
                            member_name, payment_obj
                        )
                        if bt_name:
                            result["created_count"] += 1
                            result["total_amount"] += float(payment_dict.get("amount", {}).get("value", 0))
                            result["transactions"].append(bt_name)
                        continue

                # For non-dues payments or dues without member match, create generic Bank Transaction
                bt = self._create_generic_payment_bank_transaction(
                    payment=payment_dict,
                    payment_obj=payment_obj,
                    clearing_bank_account=clearing_bank_account,
                    company=company,
                    settlement_id=settlement_id,
                )

                if bt:
                    result["created_count"] += 1
                    result["total_amount"] += float(payment_dict.get("amount", {}).get("value", 0))
                    result["transactions"].append(bt.name)

            except Exception as e:
                frappe.logger().warning(
                    f"⚠️ Failed to create Bank Transaction for payment {payment_dict.get('id')}: {str(e)}"
                )
                result["skipped_count"] += 1

        frappe.logger().info(
            f"✅ Created {result['created_count']} individual payment Bank Transactions "
            f"(total: EUR {result['total_amount']:.2f}, skipped: {result['skipped_count']})"
        )

        return result

    def _create_generic_payment_bank_transaction(
        self,
        payment: Dict,
        payment_obj,
        clearing_bank_account: str,
        company: str,
        settlement_id: str,
    ):
        """
        Create a generic Bank Transaction for a payment (non-dues or unmatched).

        Args:
            payment: Mollie payment dictionary from API
            payment_obj: Full Mollie payment object (SDK)
            clearing_bank_account: Bank Account for clearing
            company: Company name
            settlement_id: Parent settlement ID

        Returns:
            Bank Transaction document or None
        """
        from frappe.utils import getdate

        # Extract payment data
        payment_id = payment.get("id")
        amount = float(payment.get("amount", {}).get("value", 0))
        currency = payment.get("amount", {}).get("currency", "EUR")
        paid_at = payment.get("paidAt")
        description = payment.get("description", "Mollie payment")
        metadata = payment.get("metadata", {})

        # Build rich description
        bt_description = description

        # Add order ID if present in metadata
        order_id = metadata.get("order_id")
        if order_id:
            bt_description += f" | Order #{order_id}"

        # Add customer email if available
        customer_email = (
            getattr(payment_obj, "billing_address", {}).get("email")
            if hasattr(payment_obj, "billing_address")
            else None
        )
        if customer_email:
            bt_description += f" | {customer_email}"

        # Add settlement reference for traceability
        bt_description += f" | Settlement: {settlement_id}"

        # Create Bank Transaction
        bank_transaction = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": getdate(paid_at) if paid_at else getdate(),
                "deposit": amount,
                "withdrawal": 0.0,
                "currency": currency,
                "bank_account": clearing_bank_account,
                "company": company,
                "reference_number": payment_id,
                "description": bt_description,
                "status": "Unreconciled",
                "unallocated_amount": amount,
            }
        )

        bank_transaction.insert()
        bank_transaction.submit()

        frappe.logger().info(
            f"✅ Created generic Bank Transaction {bank_transaction.name} for {payment_id} (EUR {amount})"
        )

        return bank_transaction

    def _create_fee_journal_entry(self, settlement_id: str, fee_amount: float, company: str, settlement_date):
        """
        Create Journal Entry to account for Mollie fees.

        Args:
            settlement_id: Mollie settlement ID
            fee_amount: Fee amount (positive number)
            company: Company name
            settlement_date: Date of settlement

        Returns:
            Journal Entry document or None
        """
        if fee_amount < 0.01:
            # No significant fees to record
            return None

        # Get accounts from settings
        mollie_settings = frappe.get_single("Mollie Settings")
        clearing_account = mollie_settings.mollie_clearing_account
        fees_account = mollie_settings.payment_processing_fees_account

        if not clearing_account or not fees_account:
            frappe.logger().warning("⚠️ Clearing or Fees account not configured - skipping fee Journal Entry")
            return None

        # Create Journal Entry
        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": company,
                "posting_date": settlement_date,
                "user_remark": f"Mollie processing fees for settlement {settlement_id}",
                "accounts": [
                    {
                        "account": fees_account,
                        "debit_in_account_currency": fee_amount,
                        "credit_in_account_currency": 0.0,
                    },
                    {
                        "account": clearing_account,
                        "debit_in_account_currency": 0.0,
                        "credit_in_account_currency": fee_amount,
                    },
                ],
            }
        )

        je.insert()
        je.submit()

        frappe.logger().info(
            f"✅ Created fee Journal Entry {je.name} for settlement {settlement_id} (EUR {fee_amount:.2f})"
        )

        return je

    def batch_process_recent_settlements(self, days: int = 7) -> Dict:
        """
        Batch process all recent settlements into Bank Transactions.

        Useful for catching up on settlements that weren't processed automatically.

        Args:
            days: Number of days to look back (default: 7)

        Returns:
            dict: Batch processing results
        """
        from datetime import datetime, timedelta

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        settlements = self.settlements_client.list_settlements(from_date=start_date, until_date=end_date)

        result = {
            "total_settlements": len(settlements),
            "processed": 0,
            "already_processed": 0,
            "errors": 0,
            "results": [],
        }

        for settlement in settlements:
            # Only process settled (paid out) settlements
            if settlement.status != "paidout":
                continue

            process_result = self.process_settlement_deposit(settlement_id=settlement.id)

            result["results"].append(process_result)

            if process_result["status"] == "success":
                result["processed"] += 1
            elif process_result["status"] == "already_processed":
                result["already_processed"] += 1
            elif process_result["status"] == "error":
                result["errors"] += 1

        frappe.logger().info(
            f"✅ Batch settlement processing complete: "
            f"{result['processed']} processed, "
            f"{result['already_processed']} already processed, "
            f"{result['errors']} errors"
        )

        return result
