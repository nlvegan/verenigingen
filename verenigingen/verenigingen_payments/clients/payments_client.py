"""
Mollie Payments API Client
Client for managing and monitoring payments
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _

from ..core.mollie_base_client import MollieBaseClient


class PaymentsClient(MollieBaseClient):
    """
    Client for Mollie Payments API

    Provides:
    - Payment retrieval and monitoring
    - Payment filtering by date ranges
    - Payment status analysis
    """

    def list_payments(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        status: Optional[str] = None,
        limit: int = 250,
    ) -> List[Dict]:
        """
        List payments with optional filtering

        Args:
            from_date: Start date for filtering (applied in memory)
            to_date: End date for filtering (applied in memory)
            status: Payment status filter
            limit: Maximum number of payments to return

        Returns:
            List of payment dictionaries
        """

        def _fetch_and_filter_payments():
            params = {"limit": limit}

            # Note: Mollie Payments API doesn't support date filtering via from/to parameters
            # We get all payments and filter in memory
            if status:
                params["status"] = status

            response = self.get("/payments", params=params, paginated=True)
            frappe.logger().info(f"Retrieved {len(response)} payments from API")

            # Apply date filtering in memory if requested
            if from_date or to_date:
                filtered_payments = []

                # Ensure filter dates are timezone-aware for comparison
                from ..utils.timezone_utils import ensure_timezone_aware

                filter_from = ensure_timezone_aware(from_date) if from_date else None
                filter_to = ensure_timezone_aware(to_date) if to_date else None

                for payment in response:
                    payment_date = None

                    # Try to get payment creation date
                    if payment.get("createdAt"):
                        try:
                            payment_date = datetime.fromisoformat(payment["createdAt"].replace("Z", "+00:00"))
                        except (ValueError, TypeError) as e:
                            frappe.logger().warning(f"Failed to parse payment createdAt date: {e}")
                            continue

                    if payment_date:
                        # Apply date filter using timezone-aware comparison
                        if filter_from and payment_date < filter_from:
                            continue
                        if filter_to and payment_date > filter_to:
                            continue

                    filtered_payments.append(payment)

                frappe.logger().info(f"Filtered to {len(filtered_payments)} payments based on date range")
                return filtered_payments

            return response

        # Use centralized error handler with graceful failure
        return self.error_handler.wrap_operation(
            operation_name="list_payments",
            operation_callable=_fetch_and_filter_payments,
            error_type="payment_operation",
            context={
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
                "status": status,
                "limit": limit,
            },
            audit_trail=self.audit_trail,
            fallback_value=[],
            suppress_errors=True,
        )

    def get_payments_for_period(
        self, start_date: datetime, end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get all payments for a specific time period

        Args:
            start_date: Period start date
            end_date: Period end date (defaults to now)

        Returns:
            List of payment dictionaries
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc)

        return self.list_payments(from_date=start_date, to_date=end_date)

    def calculate_revenue_for_period(
        self, start_date: datetime, end_date: Optional[datetime] = None, include_pending: bool = True
    ) -> Decimal:
        """
        Calculate total revenue for a period including unsettled payments

        Args:
            start_date: Period start date
            end_date: Period end date (defaults to now)
            include_pending: Include payments that aren't settled yet

        Returns:
            Total revenue as Decimal
        """
        payments = self.get_payments_for_period(start_date, end_date)
        total_revenue = Decimal("0")

        for payment in payments:
            # Include paid payments and optionally pending ones
            status = payment.get("status", "")
            if status == "paid" or (include_pending and status in ["pending", "authorized"]):
                amount_data = payment.get("amount", {})
                if amount_data and "value" in amount_data:
                    try:
                        payment_amount = Decimal(amount_data["value"])
                        # Only include EUR for now
                        if amount_data.get("currency") == "EUR":
                            total_revenue += payment_amount
                    except (ValueError, TypeError) as e:
                        frappe.logger().warning(f"Failed to parse payment amount: {e}")

        return total_revenue

    def get_payment_status_breakdown(
        self, start_date: datetime, end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Get breakdown of payment statuses for a period

        Args:
            start_date: Period start date
            end_date: Period end date (defaults to now)

        Returns:
            Dictionary with status counts
        """
        payments = self.get_payments_for_period(start_date, end_date)
        status_breakdown = {}

        for payment in payments:
            status = payment.get("status", "unknown")
            status_breakdown[status] = status_breakdown.get(status, 0) + 1

        return status_breakdown
