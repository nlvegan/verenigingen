"""
Mollie Settlements API Client
Client for managing settlement operations and reconciliation
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.models.settlement import Settlement, SettlementCapture, SettlementLine
from ..core.mollie_base_client import MollieBaseClient


class SettlementsClient(MollieBaseClient):
    """
    Client for Mollie Settlements API

    Provides:
    - Settlement retrieval and listing
    - Payment captures in settlements
    - Refunds and chargebacks tracking
    - Settlement reconciliation
    - Financial reporting
    """

    def get_settlement(self, settlement_id: str) -> Settlement:
        """
        Get a specific settlement

        Args:
            settlement_id: Settlement identifier

        Returns:
            Settlement object
        """
        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.SETTLEMENT_PROCESSED, AuditSeverity.INFO, f"Retrieving settlement: {settlement_id}"
        # )

        response = self.get(f"settlements/{settlement_id}")
        return Settlement(response)

    def list_settlements(
        self,
        reference: Optional[str] = None,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
    ) -> List[Settlement]:
        """
        List settlements with optional filters

        Args:
            reference: Filter by bank reference
            from_date: Start date filter (applied in memory, not API)
            until_date: End date filter (applied in memory, not API)
            limit: Maximum number of results

        Returns:
            List of Settlement objects
        """
        params = {"limit": limit}

        # NOTE: Mollie settlements API doesn't support date filtering
        # We get all settlements and filter in memory
        if reference:
            params["reference"] = reference

        # Don't add date parameters as they cause 400 Bad Request
        # if from_date:
        #     params["from"] = from_date.strftime("%Y-%m-%d")
        # if until_date:
        #     params["until"] = until_date.strftime("%Y-%m-%d")

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED, AuditSeverity.INFO, "Listing settlements", details=params
        )

        response = self.get("settlements", params=params, paginated=True)
        settlements = [Settlement(item) for item in response]

        # Apply optimized date filtering in memory if requested
        if from_date or until_date:
            filtered_settlements = []

            # Use optimized date comparison with model's parsed datetime objects
            for settlement in settlements:
                settlement_date = None

                # Use the model's parsed datetime objects (already converted to naive)
                if hasattr(settlement, "settled_at_datetime") and settlement.settled_at_datetime:
                    settlement_date = settlement.settled_at_datetime
                elif hasattr(settlement, "created_at_datetime") and settlement.created_at_datetime:
                    settlement_date = settlement.created_at_datetime

                # Apply date filter using date-only comparison for better performance
                if settlement_date:
                    settlement_date_only = (
                        settlement_date.date() if hasattr(settlement_date, "date") else settlement_date
                    )
                    from_date_only = (
                        from_date.date() if from_date and hasattr(from_date, "date") else from_date
                    )
                    until_date_only = (
                        until_date.date() if until_date and hasattr(until_date, "date") else until_date
                    )

                    if from_date_only and settlement_date_only < from_date_only:
                        continue
                    if until_date_only and settlement_date_only > until_date_only:
                        continue

                filtered_settlements.append(settlement)

            # Log performance information
            frappe.logger().info(
                f"Filtered {len(settlements)} settlements to {len(filtered_settlements)} based on date range"
            )
            return filtered_settlements

        return settlements

    def get_next_settlement(self) -> Optional[Settlement]:
        """
        Get the next scheduled settlement

        Returns:
            Settlement object or None if no pending settlement
        """
        response = self.get("settlements/next")

        if response:
            self.audit_trail.log_event(
                AuditEventType.SETTLEMENT_PROCESSED,
                AuditSeverity.INFO,
                "Retrieved next settlement",
                details={"settlement_id": response.get("id")},
            )
            return Settlement(response)

        return None

    def get_open_settlement(self) -> Optional[Settlement]:
        """
        Get the currently open settlement

        Returns:
            Settlement object or None if no open settlement
        """
        response = self.get("settlements/open")

        if response:
            self.audit_trail.log_event(
                AuditEventType.SETTLEMENT_PROCESSED,
                AuditSeverity.INFO,
                "Retrieved open settlement",
                details={"settlement_id": response.get("id")},
            )
            return Settlement(response)

        return None

    def list_settlement_payments(self, settlement_id: str, limit: int = 250) -> List[Dict]:
        """
        List all payments in a settlement

        Args:
            settlement_id: Settlement identifier
            limit: Maximum number of results

        Returns:
            List of payment dictionaries
        """
        params = {"limit": limit}

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            AuditSeverity.INFO,
            f"Listing payments for settlement: {settlement_id}",
        )

        response = self.get(f"settlements/{settlement_id}/payments", params=params, paginated=True)

        return response

    def list_settlement_refunds(self, settlement_id: str, limit: int = 250) -> List[Dict]:
        """
        List all refunds in a settlement

        Args:
            settlement_id: Settlement identifier
            limit: Maximum number of results

        Returns:
            List of refund dictionaries
        """
        params = {"limit": limit}

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            AuditSeverity.INFO,
            f"Listing refunds for settlement: {settlement_id}",
        )

        response = self.get(f"settlements/{settlement_id}/refunds", params=params, paginated=True)

        return response

    def list_settlement_chargebacks(self, settlement_id: str, limit: int = 250) -> List[Dict]:
        """
        List all chargebacks in a settlement

        Args:
            settlement_id: Settlement identifier
            limit: Maximum number of results

        Returns:
            List of chargeback dictionaries
        """
        params = {"limit": limit}

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            AuditSeverity.INFO,
            f"Listing chargebacks for settlement: {settlement_id}",
        )

        response = self.get(f"settlements/{settlement_id}/chargebacks", params=params, paginated=True)

        return response

    def list_settlement_captures(self, settlement_id: str, limit: int = 250) -> List[SettlementCapture]:
        """
        List all captures in a settlement

        Args:
            settlement_id: Settlement identifier
            limit: Maximum number of results

        Returns:
            List of SettlementCapture objects
        """
        params = {"limit": limit}

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            AuditSeverity.INFO,
            f"Listing captures for settlement: {settlement_id}",
        )

        response = self.get(f"settlements/{settlement_id}/captures", params=params, paginated=True)

        return [SettlementCapture(item) for item in response]

    def reconcile_settlement(self, settlement_id: str) -> Dict:
        """
        Reconcile a settlement with all its components

        Args:
            settlement_id: Settlement to reconcile

        Returns:
            Dict with reconciliation results
        """
        # Get settlement details
        settlement = self.get_settlement(settlement_id)

        # Get all components
        payments = self.list_settlement_payments(settlement_id)
        refunds = self.list_settlement_refunds(settlement_id)
        chargebacks = self.list_settlement_chargebacks(settlement_id)
        captures = self.list_settlement_captures(settlement_id)

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
            "settlement_id": settlement_id,
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
            "reconciled_at": datetime.now().isoformat(),
        }

        # Log reconciliation
        severity = AuditSeverity.INFO if reconciliation["reconciled"] else AuditSeverity.WARNING
        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            severity,
            f"Settlement reconciliation {'successful' if reconciliation['reconciled'] else 'failed'}: {settlement_id}",
            details=reconciliation,
        )

        # Alert if discrepancy
        if not reconciliation["reconciled"]:
            frappe.publish_realtime(
                "settlement_discrepancy",
                {
                    "message": _(f"Settlement {settlement_id} has discrepancy: €{abs(discrepancy):.2f}"),
                    "settlement_id": settlement_id,
                    "discrepancy": float(discrepancy),
                },
                user=frappe.session.user,
            )

        return reconciliation

    def get_settlement_summary(self, from_date: datetime, until_date: datetime) -> Dict:
        """
        Get summary of settlements for a period

        Args:
            from_date: Period start
            until_date: Period end

        Returns:
            Dict with settlement summary
        """
        settlements = self.list_settlements(from_date=from_date, until_date=until_date)

        summary = {
            "period": {"from": from_date.isoformat(), "until": until_date.isoformat()},
            "total_settlements": len(settlements),
            "by_status": {"open": 0, "pending": 0, "paidout": 0, "failed": 0},
            "total_amount": Decimal("0"),
            "total_revenue": Decimal("0"),
            "total_costs": Decimal("0"),
            "settlements": [],
        }

        for settlement in settlements:
            # Count by status
            if settlement.status:
                status_key = settlement.status.lower()
                if status_key in summary["by_status"]:
                    summary["by_status"][status_key] += 1

            # Sum amounts
            if settlement.amount and hasattr(settlement.amount, "decimal_value"):
                summary["total_amount"] += settlement.amount.decimal_value

            summary["total_revenue"] += settlement.get_total_revenue()
            summary["total_costs"] += settlement.get_total_costs()

            # Add settlement info
            summary["settlements"].append(
                {
                    "id": settlement.id,
                    "reference": settlement.reference,
                    "status": settlement.status,
                    "amount": float(settlement.amount.decimal_value) if settlement.amount else 0,
                    "created_at": settlement.created_at,
                    "settled_at": settlement.settled_at,
                }
            )

        # Convert Decimals to float for JSON serialization
        summary["total_amount"] = float(summary["total_amount"])
        summary["total_revenue"] = float(summary["total_revenue"])
        summary["total_costs"] = float(summary["total_costs"])
        summary["net_amount"] = summary["total_revenue"] - summary["total_costs"]

        return summary

    def track_settlement_status(self, settlement_id: str) -> Dict:
        """
        Track and monitor settlement status

        Args:
            settlement_id: Settlement to track

        Returns:
            Dict with status information
        """
        settlement = self.get_settlement(settlement_id)

        status_info = {
            "settlement_id": settlement_id,
            "current_status": settlement.status,
            "is_settled": settlement.is_settled(),
            "is_failed": settlement.is_failed(),
            "created_at": settlement.created_at,
            "settled_at": settlement.settled_at,
            "reference": settlement.reference,
            "amount": float(settlement.amount.decimal_value) if settlement.amount else 0,
            "tracked_at": datetime.now().isoformat(),
        }

        # Check for issues
        if settlement.is_failed():
            status_info["alert"] = "Settlement failed"
            status_info["alert_severity"] = "high"

            # Send alert
            frappe.publish_realtime(
                "settlement_failed",
                {
                    "message": _(f"Settlement {settlement_id} has failed"),
                    "settlement_id": settlement_id,
                    "reference": settlement.reference,
                },
                user=frappe.session.user,
            )

        elif settlement.status == "pending":
            # Calculate days pending
            if settlement.created_at:
                created = datetime.fromisoformat(settlement.created_at.replace("Z", "+00:00"))
                days_pending = (datetime.now() - created).days

                status_info["days_pending"] = days_pending

                if days_pending > 5:
                    status_info["alert"] = f"Settlement pending for {days_pending} days"
                    status_info["alert_severity"] = "medium"

        return status_info

    def export_settlement_report(self, settlement_id: str) -> Dict:
        """
        Export detailed settlement report

        Args:
            settlement_id: Settlement to export

        Returns:
            Dict with complete settlement data
        """
        # Reconcile first to get all data
        reconciliation = self.reconcile_settlement(settlement_id)

        # Get settlement details
        settlement = self.get_settlement(settlement_id)

        report = {
            "settlement": {
                "id": settlement.id,
                "reference": settlement.reference,
                "status": settlement.status,
                "created_at": settlement.created_at,
                "settled_at": settlement.settled_at,
                "amount": reconciliation["actual_amount"],
                "currency": settlement.amount.currency if settlement.amount else "EUR",
            },
            "reconciliation": reconciliation,
            "periods": {},
            "generated_at": datetime.now().isoformat(),
        }

        # Add period details
        if settlement.periods:
            for period_key, period in settlement.periods.items():
                if hasattr(period, "calculate_net_amount"):
                    report["periods"][period_key] = {
                        "net_amount": float(period.calculate_net_amount()),
                        "revenue_count": len(period.revenue) if period.revenue else 0,
                        "costs_count": len(period.costs) if period.costs else 0,
                        "invoice_id": period.invoice_id,
                    }

        # Log report generation
        self.audit_trail.log_event(
            AuditEventType.REPORT_GENERATED,
            AuditSeverity.INFO,
            f"Settlement report exported: {settlement_id}",
            details={"settlement_id": settlement_id},
        )

        return report
