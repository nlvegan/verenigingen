"""
Mollie Order Payment Processor

Handles processing of Mollie payments for shop/WooCommerce orders by:
- Creating Bank Transactions for reconciliation
- Extracting invoice numbers from descriptions
- Attempting auto-reconciliation with Sales Invoices
"""

import re
from decimal import Decimal
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.verenigingen_payments.mollie.core.client import MollieClient


class OrderPaymentProcessor:
    """Process Mollie payments for shop/WooCommerce orders"""

    def __init__(self):
        self.mollie_client = MollieClient()
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.bank_tx_creator = get_bank_transaction_creator()

    def extract_invoice_number(self, description: str) -> Optional[str]:
        """
        Extract invoice number from payment description.

        Uses centralized PaymentPatterns for consistent regex handling.

        Args:
            description: Payment description (e.g., "Bestelling 2025-55986")

        Returns:
            Invoice number if found (e.g., "2025-55986"), None otherwise
        """
        from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentPatterns

        return PaymentPatterns.extract_invoice_number(description)

    def find_sales_invoice_by_number(self, invoice_number: str) -> Optional[str]:
        """
        Find Sales Invoice by invoice number.

        Searches multiple fields in priority order:
        1. ERPNext name field (e.g., ACC-SINV-2025-39559)
        2. E-Boekhouden invoice number (e.g., 2025-55986) - MOST COMMON for WooCommerce orders
        3. Generic custom invoice_number field (if exists)

        Args:
            invoice_number: Invoice number to search for (from payment description)

        Returns:
            Sales Invoice name if found, None otherwise
        """
        # Try exact match against ERPNext name field first
        sinv = frappe.db.get_value(
            "Sales Invoice",
            {"name": invoice_number, "docstatus": 1},  # Only submitted invoices
            "name",
        )

        if sinv:
            frappe.logger().info(f"✅ Found Sales Invoice {sinv} by exact name match")
            return sinv

        # Try matching E-Boekhouden invoice number (WooCommerce uses this)
        if frappe.db.has_column("Sales Invoice", "eboekhouden_invoice_number"):
            sinv = frappe.db.get_value(
                "Sales Invoice",
                {"eboekhouden_invoice_number": invoice_number, "docstatus": 1},
                "name",
            )

            if sinv:
                frappe.logger().info(
                    f"✅ Found Sales Invoice {sinv} by E-Boekhouden invoice number {invoice_number}"
                )
                return sinv

        # Try matching generic custom invoice number field if exists
        if frappe.db.has_column("Sales Invoice", "invoice_number"):
            sinv = frappe.db.get_value(
                "Sales Invoice",
                {"invoice_number": invoice_number, "docstatus": 1},
                "name",
            )

            if sinv:
                frappe.logger().info(f"✅ Found Sales Invoice {sinv} by custom invoice_number field")
                return sinv

        frappe.logger().warning(f"⚠️ No Sales Invoice found for invoice number: {invoice_number}")
        return None

    def create_bank_transaction(self, payment, invoice_number: Optional[str] = None) -> Optional[str]:
        """
        Create Bank Transaction for order payment.

        Args:
            payment: Mollie payment object
            invoice_number: Optional invoice number extracted from description

        Returns:
            Bank Transaction name if created, None on failure
        """
        try:
            # Get Mollie bank account configuration using centralized helper
            config = self.bank_tx_creator.get_mollie_bank_account_config()

            if config.get("error"):
                frappe.logger().error(f"❌ Mollie configuration error: {config['error']}")
                return None

            bank_account = config["bank_account"]
            company = config["company"]

            # Build description with invoice number hint if available
            additional_desc = None
            if invoice_number:
                additional_desc = f"Invoice: {invoice_number}"

            # Use centralized Bank Transaction creator
            bank_tx_name = self.bank_tx_creator.create_from_mollie_payment(
                payment=payment,
                bank_account=bank_account,
                company=company,
                additional_description=additional_desc,
            )

            return bank_tx_name

        except Exception as e:
            frappe.logger().error(f"❌ Failed to create Bank Transaction: {e}")
            frappe.log_error(
                f"Bank Transaction creation failed for {payment.id}: {e}", "Order Payment Processing"
            )
            return None

    def attempt_auto_reconciliation(self, bank_transaction_name: str, invoice_number: str) -> Dict[str, Any]:
        """
        Attempt auto-reconciliation of Bank Transaction with Sales Invoice.

        Args:
            bank_transaction_name: Bank Transaction to reconcile
            invoice_number: Invoice number to match against

        Returns:
            Dict with reconciliation result
        """
        result = {
            "reconciled": False,
            "payment_entry": None,
            "invoice": None,
            "message": None,
        }

        try:
            # Find the Sales Invoice
            sinv_name = self.find_sales_invoice_by_number(invoice_number)
            if not sinv_name:
                result["message"] = f"Sales Invoice not found for number: {invoice_number}"
                return result

            # Get the Sales Invoice
            sinv = frappe.get_doc("Sales Invoice", sinv_name)

            # Check if invoice is already fully paid
            if sinv.outstanding_amount <= 0:
                result["message"] = f"Sales Invoice {sinv_name} is already fully paid"
                result["invoice"] = sinv_name
                return result

            # Get Bank Transaction
            bank_tx = frappe.get_doc("Bank Transaction", bank_transaction_name)

            # Check if amounts match (within tolerance)
            amount_difference = abs(bank_tx.unallocated_amount - sinv.outstanding_amount)
            if amount_difference > 0.01:  # 1 cent tolerance
                result["message"] = (
                    f"Amount mismatch: Bank Transaction €{bank_tx.unallocated_amount} "
                    f"vs Invoice Outstanding €{sinv.outstanding_amount}"
                )
                result["invoice"] = sinv_name
                return result

            # TODO: Implement actual reconciliation via ERPNext's bank reconciliation tool
            # This would typically involve:
            # 1. Creating Payment Entry
            # 2. Linking to Bank Transaction
            # 3. Allocating against Sales Invoice
            # 4. Updating Bank Transaction allocated_amount

            result["message"] = (
                f"Auto-reconciliation not yet implemented. "
                f"Manually reconcile Bank Transaction {bank_transaction_name} "
                f"with Sales Invoice {sinv_name}"
            )
            result["invoice"] = sinv_name

            return result

        except Exception as e:
            frappe.logger().error(f"❌ Auto-reconciliation failed: {e}")
            result["message"] = f"Auto-reconciliation error: {str(e)}"
            return result

    def process_order_payment(self, payment_id: str, payment=None) -> Dict[str, Any]:
        """
        Process a shop/WooCommerce order payment.

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched payment object

        Returns:
            Dict with processing result
        """
        result = {
            "payment_id": payment_id,
            "status": "pending",
            "payment_type": "order",
            "bank_transaction": None,
            "invoice_number": None,
            "sales_invoice": None,
            "reconciliation": None,
            "error": None,
        }

        try:
            # Fetch payment if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            result["payment_status"] = payment.status
            result["amount"] = (
                f"{payment.amount['value']} {payment.amount['currency']}" if payment.amount else "Unknown"
            )
            result["description"] = payment.description

            # Only process paid payments
            if payment.status != "paid":
                result["status"] = "skipped"
                result["message"] = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Extract invoice number from description
            invoice_number = self.extract_invoice_number(payment.description)
            result["invoice_number"] = invoice_number

            if not invoice_number:
                frappe.logger().warning(
                    f"⚠️ Could not extract invoice number from description: {payment.description}"
                )

            # Create Bank Transaction
            bank_tx_name = self.create_bank_transaction(payment, invoice_number)
            if not bank_tx_name:
                result["status"] = "error"
                result["error"] = "Failed to create Bank Transaction"
                return result

            result["bank_transaction"] = bank_tx_name
            result["status"] = "success"

            # Build success message
            if invoice_number:
                result["message"] = (
                    f"Bank Transaction {bank_tx_name} created for order {invoice_number}. "
                    f"Ready for reconciliation with Sales Invoice when available."
                )
            else:
                result["message"] = (
                    f"Bank Transaction {bank_tx_name} created. "
                    f"Manual reconciliation required (no invoice number in description)."
                )

            # Note: Auto-reconciliation is handled separately by reconciliation workflows
            # The Bank Transaction is now available for manual or automated matching

            return result

        except Exception as e:
            frappe.logger().error(f"❌ Order payment processing failed: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            return result
