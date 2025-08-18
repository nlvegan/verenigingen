"""
Mollie Invoices API Client
Client for managing Mollie invoices and billing
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.models.invoice import Invoice, InvoiceStatus
from ..core.mollie_base_client import MollieBaseClient


class InvoicesClient(MollieBaseClient):
    """
    Client for Mollie Invoices API

    Provides:
    - Invoice retrieval and listing
    - Invoice status tracking
    - VAT calculations
    - Billing reconciliation
    """

    def get_invoice(self, invoice_id: str) -> Invoice:
        """
        Get a specific invoice

        Args:
            invoice_id: Invoice identifier

        Returns:
            Invoice object
        """
        self.audit_trail.log_event(
            AuditEventType.REPORT_GENERATED, AuditSeverity.INFO, f"Retrieving invoice: {invoice_id}"
        )

        response = self.get(f"invoices/{invoice_id}")
        return Invoice(response)

    def list_invoices(
        self,
        reference: Optional[str] = None,
        year: Optional[int] = None,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
    ) -> List[Invoice]:
        """
        List invoices with optional filters

        Args:
            reference: Filter by invoice reference
            year: Filter by year
            from_date: Start date filter
            until_date: End date filter
            limit: Maximum number of results

        Returns:
            List of Invoice objects
        """
        params = {"limit": limit}

        if reference:
            params["reference"] = reference

        if year:
            params["year"] = year

        if from_date:
            params["from"] = from_date.strftime("%Y-%m-%d")

        if until_date:
            params["until"] = until_date.strftime("%Y-%m-%d")

        self.audit_trail.log_event(
            AuditEventType.REPORT_GENERATED, AuditSeverity.INFO, "Listing invoices", details=params
        )

        response = self.get("invoices", params=params, paginated=True)
        return [Invoice(item) for item in response]

    def get_overdue_invoices(self) -> List[Invoice]:
        """
        Get all overdue invoices

        Returns:
            List of overdue Invoice objects
        """
        all_invoices = self.list_invoices()
        overdue = [inv for inv in all_invoices if inv.is_overdue()]

        if overdue:
            self.audit_trail.log_event(
                AuditEventType.REPORT_GENERATED,
                AuditSeverity.WARNING,
                f"Found {len(overdue)} overdue invoices",
                details={"overdue_count": len(overdue)},
            )

        return overdue

    def calculate_vat_summary(self, from_date: datetime, until_date: datetime) -> Dict:
        """
        Calculate VAT summary for a period

        Args:
            from_date: Period start
            until_date: Period end

        Returns:
            Dict with VAT calculations
        """
        invoices = self.list_invoices(from_date=from_date, until_date=until_date)

        summary = {
            "period": {"from": from_date.isoformat(), "until": until_date.isoformat()},
            "total_invoices": len(invoices),
            "total_net": Decimal("0"),
            "total_vat": Decimal("0"),
            "total_gross": Decimal("0"),
            "by_rate": {},
            "by_status": {"open": 0, "paid": 0, "overdue": 0},
        }

        for invoice in invoices:
            # Count by status
            if invoice.is_paid():
                summary["by_status"]["paid"] += 1
            elif invoice.is_overdue():
                summary["by_status"]["overdue"] += 1
            else:
                summary["by_status"]["open"] += 1

            # Sum amounts
            if invoice.net_amount and hasattr(invoice.net_amount, "decimal_value"):
                summary["total_net"] += invoice.net_amount.decimal_value

            if invoice.vat_amount and hasattr(invoice.vat_amount, "decimal_value"):
                summary["total_vat"] += invoice.vat_amount.decimal_value

            if invoice.gross_amount and hasattr(invoice.gross_amount, "decimal_value"):
                summary["total_gross"] += invoice.gross_amount.decimal_value

            # Group by VAT rate
            vat_rate = invoice.get_vat_rate()
            rate_key = f"{vat_rate:.1f}%"

            if rate_key not in summary["by_rate"]:
                summary["by_rate"][rate_key] = {
                    "count": 0,
                    "net": Decimal("0"),
                    "vat": Decimal("0"),
                    "gross": Decimal("0"),
                }

            summary["by_rate"][rate_key]["count"] += 1

            if invoice.net_amount:
                summary["by_rate"][rate_key]["net"] += invoice.net_amount.decimal_value
            if invoice.vat_amount:
                summary["by_rate"][rate_key]["vat"] += invoice.vat_amount.decimal_value
            if invoice.gross_amount:
                summary["by_rate"][rate_key]["gross"] += invoice.gross_amount.decimal_value

        # Convert Decimals to float for JSON
        summary["total_net"] = float(summary["total_net"])
        summary["total_vat"] = float(summary["total_vat"])
        summary["total_gross"] = float(summary["total_gross"])

        for rate_key in summary["by_rate"]:
            summary["by_rate"][rate_key]["net"] = float(summary["by_rate"][rate_key]["net"])
            summary["by_rate"][rate_key]["vat"] = float(summary["by_rate"][rate_key]["vat"])
            summary["by_rate"][rate_key]["gross"] = float(summary["by_rate"][rate_key]["gross"])

        return summary

    def reconcile_invoice_with_settlements(self, invoice_id: str) -> Dict:
        """
        Reconcile invoice with related settlements

        Args:
            invoice_id: Invoice to reconcile

        Returns:
            Dict with reconciliation results
        """
        invoice = self.get_invoice(invoice_id)

        reconciliation = {
            "invoice_id": invoice_id,
            "reference": invoice.reference,
            "status": invoice.status,
            "gross_amount": float(invoice.gross_amount.decimal_value) if invoice.gross_amount else 0,
            "settlements": [],
            "total_settled": Decimal("0"),
            "discrepancy": Decimal("0"),
            "reconciled": False,
        }

        # Get related settlements
        if invoice.settlements:
            for settlement_id in invoice.settlements:
                reconciliation["settlements"].append(settlement_id)

        # Would need to fetch settlement details to calculate totals
        # This is a simplified version

        reconciliation["reconciled"] = invoice.is_paid()
        reconciliation["total_settled"] = float(reconciliation["total_settled"])
        reconciliation["discrepancy"] = float(reconciliation["discrepancy"])

        return reconciliation

    def track_payment_status(self, invoice_id: str) -> Dict:
        """
        Track invoice payment status

        Args:
            invoice_id: Invoice to track

        Returns:
            Dict with payment status
        """
        invoice = self.get_invoice(invoice_id)

        status = {
            "invoice_id": invoice_id,
            "reference": invoice.reference,
            "status": invoice.status,
            "is_paid": invoice.is_paid(),
            "is_overdue": invoice.is_overdue(),
            "issued_at": invoice.issued_at,
            "due_at": invoice.due_at,
            "paid_at": invoice.paid_at,
            "amount": {
                "net": float(invoice.net_amount.decimal_value) if invoice.net_amount else 0,
                "vat": float(invoice.vat_amount.decimal_value) if invoice.vat_amount else 0,
                "gross": float(invoice.gross_amount.decimal_value) if invoice.gross_amount else 0,
            },
        }

        # Calculate days overdue if applicable
        if invoice.is_overdue() and invoice.due_at:
            due_date = datetime.fromisoformat(invoice.due_at.replace("Z", "+00:00"))
            days_overdue = (datetime.now() - due_date).days
            status["days_overdue"] = days_overdue

            # Send alert for overdue invoices
            self.audit_trail.log_event(
                AuditEventType.REPORT_GENERATED,
                AuditSeverity.WARNING,
                f"Invoice {invoice_id} is {days_overdue} days overdue",
                details=status,
            )

            frappe.publish_realtime(
                "invoice_overdue",
                {
                    "message": _(f"Invoice {invoice.reference} is {days_overdue} days overdue"),
                    "invoice_id": invoice_id,
                    "days_overdue": days_overdue,
                    "amount": status["amount"]["gross"],
                },
                user=frappe.session.user,
            )

        return status

    def export_invoices_for_accounting(self, from_date: datetime, until_date: datetime) -> List[Dict]:
        """
        Export invoices in format suitable for accounting systems

        Args:
            from_date: Export period start
            until_date: Export period end

        Returns:
            List of invoice data for accounting
        """
        invoices = self.list_invoices(from_date=from_date, until_date=until_date)

        export_data = []

        for invoice in invoices:
            # Format for accounting system
            invoice_data = {
                "invoice_number": invoice.reference,
                "invoice_date": invoice.issued_at,
                "due_date": invoice.due_at,
                "paid_date": invoice.paid_at,
                "status": invoice.status,
                "vat_number": invoice.vat_number,
                "net_amount": float(invoice.net_amount.decimal_value) if invoice.net_amount else 0,
                "vat_amount": float(invoice.vat_amount.decimal_value) if invoice.vat_amount else 0,
                "gross_amount": float(invoice.gross_amount.decimal_value) if invoice.gross_amount else 0,
                "vat_rate": invoice.get_vat_rate(),
                "currency": invoice.gross_amount.currency if invoice.gross_amount else "EUR",
                "lines": [],
            }

            # Add line items
            if invoice.lines:
                for line in invoice.lines:
                    invoice_data["lines"].append(
                        {
                            "description": line.description,
                            "period": line.period,
                            "quantity": line.count,
                            "unit_price": float(line.amount.decimal_value) if line.amount else 0,
                            "vat_rate": line.vat_percentage,
                            "total": float(line.calculate_total()),
                        }
                    )

            export_data.append(invoice_data)

        # Log export
        self.audit_trail.log_event(
            AuditEventType.DATA_EXPORT,
            AuditSeverity.INFO,
            f"Exported {len(export_data)} invoices for accounting",
            details={
                "period_from": from_date.isoformat(),
                "period_until": until_date.isoformat(),
                "invoice_count": len(export_data),
            },
        )

        return export_data
