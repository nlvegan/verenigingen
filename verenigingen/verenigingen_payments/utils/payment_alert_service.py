# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Shared Payment Alert Service

Provides centralized alerting for payment-related issues across all payment integrations
(ING Checkout, Mollie, Ponto, etc.).

Usage:
    from verenigingen.utils.payment_alert_service import PaymentAlertService

    alert_service = PaymentAlertService()
    alert_service.send_overpayment_alert(
        source="ING Checkout",
        transaction_id="TXN-001",
        reference_name="SINV-001",
        amount_paid=150.00,
        amount_due=100.00,
    )
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt


class PaymentAlertService:
    """
    Centralized service for sending payment-related alerts.

    Supports:
    - Overpayment detection alerts
    - Payment Entry creation failure alerts
    - Payment reconciliation issues
    """

    def __init__(self):
        """Initialize the payment alert service."""
        self._recipients_cache = None

    @property
    def alert_recipients(self) -> list:
        """Get alert recipients from hook configuration (cached)."""
        if self._recipients_cache is None:
            self._recipients_cache = frappe.get_hooks("accounts_managers_email") or []
        return self._recipients_cache

    def send_overpayment_alert(
        self,
        source: str,
        transaction_id: str,
        reference_name: str,
        amount_paid: float,
        amount_due: float,
        transaction_doctype: Optional[str] = None,
        transaction_name: Optional[str] = None,
    ) -> bool:
        """
        Send alert for overpayment detection.

        Args:
            source: Payment integration name (e.g., "ING Checkout", "Mollie")
            transaction_id: External transaction/payment ID
            reference_name: Reference document name (e.g., Sales Invoice)
            amount_paid: Amount actually paid
            amount_due: Amount that was due (outstanding)
            transaction_doctype: Optional DocType for adding comments
            transaction_name: Optional document name for adding comments

        Returns:
            True if alert was sent successfully, False otherwise
        """
        overpayment = flt(amount_paid) - flt(amount_due)

        # Log for review
        frappe.log_error(
            title=f"{source}: Overpayment detected - {transaction_id}",
            message=(
                f"Source: {source}\n"
                f"Transaction ID: {transaction_id}\n"
                f"Reference: {reference_name}\n"
                f"Amount Paid: {amount_paid:.2f}\n"
                f"Amount Due: {amount_due:.2f}\n"
                f"Overpayment: {overpayment:.2f}\n\n"
                "Action Required: Review for refund or credit note."
            ),
        )

        # Add comment to transaction document if provided
        if transaction_doctype and transaction_name:
            self._add_overpayment_comment(
                transaction_doctype,
                transaction_name,
                amount_paid,
                amount_due,
                overpayment,
            )

        # Send alert email
        return self._send_email_alert(
            subject=f"{source} Overpayment: {transaction_id} - {overpayment:.2f}",
            message=self._format_overpayment_email(
                source=source,
                transaction_id=transaction_id,
                reference_name=reference_name,
                amount_paid=amount_paid,
                amount_due=amount_due,
                overpayment=overpayment,
            ),
            alert_type="overpayment",
            context_id=transaction_id,
        )

    def send_payment_entry_failure_alert(
        self,
        source: str,
        transaction_id: str,
        reference_name: Optional[str],
        amount: float,
        error_message: str,
    ) -> bool:
        """
        Send alert when Payment Entry creation fails.

        Args:
            source: Payment integration name (e.g., "ING Checkout", "Mollie")
            transaction_id: External transaction/payment ID
            reference_name: Reference document name (optional)
            amount: Transaction amount
            error_message: The error that occurred

        Returns:
            True if alert was sent successfully, False otherwise
        """
        return self._send_email_alert(
            subject=f"URGENT: {source} Payment Entry Failed - {transaction_id}",
            message=self._format_failure_email(
                source=source,
                transaction_id=transaction_id,
                reference_name=reference_name,
                amount=amount,
                error_message=error_message,
            ),
            alert_type="payment_entry_failure",
            context_id=transaction_id,
        )

    def send_reconciliation_alert(
        self,
        source: str,
        transaction_id: str,
        issue_type: str,
        details: str,
    ) -> bool:
        """
        Send alert for payment reconciliation issues.

        Args:
            source: Payment integration name
            transaction_id: External transaction/payment ID
            issue_type: Type of reconciliation issue
            details: Detailed description of the issue

        Returns:
            True if alert was sent successfully, False otherwise
        """
        return self._send_email_alert(
            subject=f"{source} Reconciliation Issue: {issue_type} - {transaction_id}",
            message=(
                f"<p>A payment reconciliation issue has been detected.</p>"
                f"<p><strong>Source:</strong> {source}</p>"
                f"<p><strong>Transaction ID:</strong> {transaction_id}</p>"
                f"<p><strong>Issue Type:</strong> {issue_type}</p>"
                f"<p><strong>Details:</strong></p>"
                f"<pre>{details}</pre>"
                f"<p>Please review and resolve this issue.</p>"
            ),
            alert_type="reconciliation",
            context_id=transaction_id,
        )

    def _add_overpayment_comment(
        self,
        doctype: str,
        docname: str,
        amount_paid: float,
        amount_due: float,
        overpayment: float,
    ) -> None:
        """Add comment to transaction document about overpayment."""
        try:
            doc = frappe.get_doc(doctype, docname)
            doc.add_comment(
                "Comment",
                f"Overpayment of {overpayment:.2f} detected.\n"
                f"Customer paid {amount_paid:.2f} but only {amount_due:.2f} was due.\n"
                f"Allocated {amount_due:.2f} to invoice. Review for refund.",
            )
        except Exception as e:
            frappe.logger().warning(f"Failed to add overpayment comment to {doctype} {docname}: {e}")

    def _send_email_alert(
        self,
        subject: str,
        message: str,
        alert_type: str,
        context_id: str,
    ) -> bool:
        """
        Send email alert to configured recipients.

        Returns:
            True if sent successfully, False otherwise
        """
        from verenigingen.services.communication.email_service import get_email_service

        try:
            recipients = self.alert_recipients
            if not recipients:
                frappe.log_error(
                    title="No Alert Recipients Configured",
                    message=(
                        f"Cannot send {alert_type} alert for {context_id}: "
                        "accounts_managers_email hook not configured."
                    ),
                )
                return False

            # Map alert_type to notification_key
            notification_key_map = {
                "overpayment": "payment_alert_overpayment",
                "payment_entry_failure": "payment_alert_failure",
                "reconciliation": "payment_alert_reconciliation",
            }
            notification_key = notification_key_map.get(alert_type, "payment_alert_failure")

            email_service = get_email_service()
            result = email_service.send_simple_email(
                recipients=recipients,
                subject=subject,
                message=message,
                notification_key=notification_key,
            )
            return result.success
        except Exception as e:
            frappe.logger().warning(f"Failed to send {alert_type} alert email: {e}")
            return False

    def _format_overpayment_email(
        self,
        source: str,
        transaction_id: str,
        reference_name: str,
        amount_paid: float,
        amount_due: float,
        overpayment: float,
    ) -> str:
        """Format HTML email for overpayment alert."""
        return (
            f"<p>An overpayment has been detected.</p>"
            f"<p><strong>Payment Source:</strong> {source}</p>"
            f"<p><strong>Transaction ID:</strong> {transaction_id}</p>"
            f"<p><strong>Reference:</strong> {reference_name}</p>"
            f"<p><strong>Amount Paid:</strong> {amount_paid:.2f}</p>"
            f"<p><strong>Amount Due:</strong> {amount_due:.2f}</p>"
            f"<p><strong>Overpayment:</strong> {overpayment:.2f}</p>"
            f"<p>Please review and process a refund or credit note as appropriate.</p>"
        )

    def _format_failure_email(
        self,
        source: str,
        transaction_id: str,
        reference_name: Optional[str],
        amount: float,
        error_message: str,
    ) -> str:
        """Format HTML email for payment entry failure alert."""
        return (
            f"<p><strong>Payment Entry creation failed.</strong></p>"
            f"<p><strong>Payment Source:</strong> {source}</p>"
            f"<p><strong>Transaction ID:</strong> {transaction_id}</p>"
            f"<p><strong>Reference:</strong> {reference_name or 'N/A'}</p>"
            f"<p><strong>Amount:</strong> {flt(amount):.2f}</p>"
            f"<p><strong>Error:</strong></p>"
            f"<pre>{error_message}</pre>"
            f"<p>Manual intervention is required to create the Payment Entry.</p>"
        )


def get_payment_alert_service() -> PaymentAlertService:
    """Factory function to get PaymentAlertService instance."""
    return PaymentAlertService()
