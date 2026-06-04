"""
Mollie Settlements API Client
Client for managing settlement operations and reconciliation
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
    MollieObjectType,
    get_payment_data_extractor,
)

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

    def get_settlement(self, settlement_id: str, use_cache: bool = True, cache_ttl: int = 180) -> Settlement:
        """
        Get a specific settlement

        Args:
            settlement_id: Settlement identifier
            use_cache: Whether to use cache (default: True, 180 second TTL)
            cache_ttl: Cache TTL in seconds (default: 180 = 3 minutes)

        Returns:
            Settlement object
        """
        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.SETTLEMENT_PROCESSED, AuditSeverity.INFO, f"Retrieving settlement: {settlement_id}"
        # )

        if use_cache and self.enable_cache:
            response = self.get_cached(f"settlements/{settlement_id}", cache_ttl=cache_ttl)
        else:
            response = self.get(f"settlements/{settlement_id}")
        return self._parse_response(response, Settlement)

    def list_settlements(
        self,
        reference: Optional[str] = None,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
        use_cache: bool = True,
        cache_ttl: int = 300,
    ) -> List[Settlement]:
        """
        List settlements with optional filters

        Args:
            reference: Filter by bank reference
            from_date: Start date filter (applied in memory, not API)
            until_date: End date filter (applied in memory, not API)
            limit: Maximum number of results
            use_cache: Whether to use cache (default: True, 300 second TTL)
            cache_ttl: Cache TTL in seconds (default: 300 = 5 minutes)

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

        if use_cache and self.enable_cache:
            response = self.get_cached("settlements", params=params, paginated=True, cache_ttl=cache_ttl)
        else:
            response = self.get("settlements", params=params, paginated=True)
        settlements = self._parse_response(response, Settlement)

        # Apply memory-based date filtering
        # Settlement objects prefer settled_at_datetime, fall back to created_at_datetime
        filtered_settlements = []
        for settlement in settlements:
            # Try settled_at_datetime first, then created_at_datetime
            date_value = None
            if hasattr(settlement, "settled_at_datetime") and settlement.settled_at_datetime:
                date_value = settlement.settled_at_datetime
            elif hasattr(settlement, "created_at_datetime") and settlement.created_at_datetime:
                date_value = settlement.created_at_datetime

            # Add date_value as temporary attribute for filtering
            settlement._filter_date = date_value
            filtered_settlements.append(settlement)

        # Use centralized filtering with custom field
        result = self._filter_by_date(
            filtered_settlements, from_date=from_date, until_date=until_date, date_field="_filter_date"
        )

        # Clean up temporary attribute
        for settlement in result:
            if hasattr(settlement, "_filter_date"):
                delattr(settlement, "_filter_date")

        return result

    def get_next_settlement(self) -> Optional[Settlement]:
        """
        Get the next scheduled settlement

        Returns:
            Settlement object or None if no pending settlement
        """
        response = self.get("settlements/next")
        settlement = self._parse_response(response, Settlement, allow_none=True)

        if settlement:
            self.audit_trail.log_event(
                AuditEventType.SETTLEMENT_PROCESSED,
                AuditSeverity.INFO,
                "Retrieved next settlement",
                details={"settlement_id": settlement.id},
            )

        return settlement

    def get_settlements_by_date_range(self, from_date: str, to_date: str) -> List[Dict]:
        """
        Get settlements within a specific date range

        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            List of settlement dictionaries
        """

        def _fetch_and_filter():
            # Get all settlements and filter by date range in memory
            # (Mollie API doesn't support date filtering directly)
            all_settlements = self.get("settlements", paginated=True)

            from frappe.utils import getdate

            from_date_obj = getdate(from_date)
            to_date_obj = getdate(to_date)

            filtered_settlements = []
            for settlement in all_settlements:
                settlement_date_str = settlement.get("settledAt")
                if settlement_date_str:
                    # Parse ISO date format (2024-08-15T10:30:00+00:00)
                    import datetime

                    settlement_date = datetime.datetime.fromisoformat(
                        settlement_date_str.replace("Z", "+00:00")
                    ).date()

                    if from_date_obj <= settlement_date <= to_date_obj:
                        filtered_settlements.append(settlement)

            return filtered_settlements

        # Use centralized error handler with graceful failure
        return self.error_handler.wrap_operation(
            operation_name="get_settlements_by_date_range",
            operation_callable=_fetch_and_filter,
            error_type="settlement_processing",
            context={"from_date": from_date, "to_date": to_date},
            audit_trail=self.audit_trail,
            fallback_value=[],
            suppress_errors=True,
        )

    def get_payments_for_settlement(self, settlement_id: str) -> List[Dict]:
        """
        Get all payments that are part of a specific settlement

        Args:
            settlement_id: Mollie settlement ID

        Returns:
            List of payment dictionaries
        """

        def _fetch_settlement_payments():
            # Get settlement details to find payment IDs
            settlement = self.get(f"settlements/{settlement_id}")

            if not settlement:
                return []

            # Get payments that were settled in this settlement
            # Try direct API endpoint first, fallback to filtering if not supported
            try:
                payments = self.get(f"settlements/{settlement_id}/payments", paginated=True)
                return payments if payments else []
            except Exception:
                # Fallback: get recent payments and filter by settlement ID
                from frappe.utils import add_days, getdate

                recent_date = add_days(getdate(), -30)

                # Use the base client to get payments (settlements client inherits from base)
                all_payments = self.get(
                    "payments", paginated=True, params={"from": recent_date.strftime("%Y-%m-%d")}
                )

                # Filter payments that belong to this settlement
                settlement_payments = []
                for payment in all_payments:
                    if payment.get("settlementId") == settlement_id:
                        settlement_payments.append(payment)

                return settlement_payments

        # Use centralized error handler with graceful failure
        return self.error_handler.wrap_operation(
            operation_name="get_payments_for_settlement",
            operation_callable=_fetch_settlement_payments,
            error_type="settlement_processing",
            context={"settlement_id": settlement_id},
            audit_trail=self.audit_trail,
            fallback_value=[],
            suppress_errors=True,
        )

    def get_open_settlement(self) -> Optional[Settlement]:
        """
        Get the currently open settlement

        Returns:
            Settlement object or None if no open settlement
        """
        response = self.get("settlements/open")
        settlement = self._parse_response(response, Settlement, allow_none=True)

        if settlement:
            self.audit_trail.log_event(
                AuditEventType.SETTLEMENT_PROCESSED,
                AuditSeverity.INFO,
                "Retrieved open settlement",
                details={"settlement_id": settlement.id},
            )

        return settlement

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

        return self._parse_response(response, SettlementCapture)

    def reconcile_settlement(self, settlement_id: str, use_cache: bool = False) -> Dict:
        """
        Reconcile a settlement with all its components

        Args:
            settlement_id: Settlement to reconcile
            use_cache: Whether to use cache (default: False - reconciliation needs accurate data)

        Returns:
            Dict with reconciliation results
        """
        # Get settlement details (bypass cache for accurate reconciliation)
        settlement = self.get_settlement(settlement_id, use_cache=use_cache)

        # Get all components
        payments = self.list_settlement_payments(settlement_id)
        refunds = self.list_settlement_refunds(settlement_id)
        chargebacks = self.list_settlement_chargebacks(settlement_id)
        captures = self.list_settlement_captures(settlement_id)

        # Calculate totals
        payment_total = sum(Decimal(p.get("settlementAmount", {}).get("value", "0")) for p in payments)

        refund_total = sum(Decimal(r.get("settlementAmount", {}).get("value", "0")) for r in refunds)

        chargeback_total = sum(Decimal(c.get("settlementAmount", {}).get("value", "0")) for c in chargebacks)

        # Use centralized extractor for settlement amounts
        extractor = get_payment_data_extractor()
        capture_total = sum(
            Decimal(
                str(extractor.extract_amount(c, source_type=MollieObjectType.SETTLEMENT, allow_zero=True))
            )
            for c in captures
            if hasattr(c, "settlement_amount") and c.settlement_amount
        )

        # Calculate expected vs actual
        calculated_total = payment_total - refund_total - chargeback_total

        # Extract settlement amount using centralized extractor
        actual_amount = Decimal(
            str(
                extractor.extract_amount(settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True)
            )
        )

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

        # Alert if discrepancy and invalidate cache
        if not reconciliation["reconciled"]:
            # Invalidate all related caches to ensure consistency
            self.invalidate_cache(f"settlements/{settlement_id}")  # Specific settlement
            self.invalidate_cache(f"settlements/{settlement_id}/payments")  # Settlement payments
            self.invalidate_cache(f"settlements/{settlement_id}/refunds")  # Settlement refunds
            self.invalidate_cache(f"settlements/{settlement_id}/chargebacks")  # Settlement chargebacks
            self.invalidate_cache(f"settlements/{settlement_id}/captures")  # Settlement captures
            self.invalidate_cache("settlements")  # Settlement list (includes this settlement)

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

        # Create extractor once for all settlements
        extractor = get_payment_data_extractor()

        for settlement in settlements:
            # Count by status
            if settlement.status:
                status_key = settlement.status.lower()
                if status_key in summary["by_status"]:
                    summary["by_status"][status_key] += 1

            # Sum amounts using centralized extractor.
            # Use the Decimal variant: total_amount is seeded as Decimal("0") and
            # extract_amount() returns a float, so plain += raises a TypeError
            # (Decimal + float is unsupported).
            summary["total_amount"] += extractor.extract_amount_as_decimal(
                settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
            )

            summary["total_revenue"] += settlement.get_total_revenue()
            summary["total_costs"] += settlement.get_total_costs()

            # Add settlement info (extract amount for dict)
            summary["settlements"].append(
                {
                    "id": settlement.id,
                    "reference": settlement.reference,
                    "status": settlement.status,
                    "amount": extractor.extract_amount(
                        settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                    ),
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

        # Use centralized extractor for settlement amount
        extractor = get_payment_data_extractor()

        status_info = {
            "settlement_id": settlement_id,
            "current_status": settlement.status,
            "is_settled": settlement.is_settled(),
            "is_failed": settlement.is_failed(),
            "created_at": settlement.created_at,
            "settled_at": settlement.settled_at,
            "reference": settlement.reference,
            "amount": extractor.extract_amount(
                settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
            ),
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
