"""
Mollie Chargebacks API Client
Client for managing payment disputes and chargebacks
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.models.chargeback import Chargeback, ChargebackReason
from ..core.mollie_base_client import MollieBaseClient


class ChargebacksClient(MollieBaseClient):
    """
    Client for Mollie Chargebacks API

    Provides:
    - Chargeback retrieval and listing
    - Dispute management
    - Financial impact analysis
    - Chargeback prevention insights
    """

    def get_chargeback(self, payment_id: str, chargeback_id: str) -> Chargeback:
        """
        Get a specific chargeback

        Args:
            payment_id: Payment identifier
            chargeback_id: Chargeback identifier

        Returns:
            Chargeback object
        """
        self.audit_trail.log_event(
            AuditEventType.CHARGEBACK_RECEIVED,
            AuditSeverity.WARNING,
            f"Retrieving chargeback: {chargeback_id} for payment: {payment_id}",
        )

        response = self.get(f"payments/{payment_id}/chargebacks/{chargeback_id}")
        return Chargeback(response)

    def list_payment_chargebacks(self, payment_id: str) -> List[Chargeback]:
        """
        List all chargebacks for a payment

        Args:
            payment_id: Payment identifier

        Returns:
            List of Chargeback objects
        """
        self.audit_trail.log_event(
            AuditEventType.CHARGEBACK_RECEIVED,
            AuditSeverity.INFO,
            f"Listing chargebacks for payment: {payment_id}",
        )

        response = self.get(f"payments/{payment_id}/chargebacks", paginated=True)
        return [Chargeback(item) for item in response]

    def list_all_chargebacks(
        self, from_date: Optional[datetime] = None, until_date: Optional[datetime] = None, limit: int = 250
    ) -> List[Chargeback]:
        """
        List all chargebacks across all payments

        Args:
            from_date: Start date filter (applied in memory, not API)
            until_date: End date filter (applied in memory, not API)
            limit: Maximum number of results

        Returns:
            List of Chargeback objects
        """
        params = {"limit": limit}

        # NOTE: Mollie chargebacks API doesn't support date filtering
        # We get all chargebacks and filter in memory

        # Don't add date parameters as they cause 400 Bad Request
        # if from_date:
        #     params["from"] = from_date.strftime("%Y-%m-%d")
        # if until_date:
        #     params["until"] = until_date.strftime("%Y-%m-%d")

        self.audit_trail.log_event(
            AuditEventType.CHARGEBACK_RECEIVED, AuditSeverity.INFO, "Listing all chargebacks", details=params
        )

        response = self.get("chargebacks", params=params, paginated=True)
        chargebacks = [Chargeback(item) for item in response]

        # Apply date filtering in memory if requested
        if from_date or until_date:
            filtered_chargebacks = []
            for chargeback in chargebacks:
                # Try to get chargeback date from createdAt
                chargeback_date = None

                if hasattr(chargeback, "created_at") and chargeback.created_at:
                    if isinstance(chargeback.created_at, str):
                        try:
                            chargeback_date = datetime.fromisoformat(
                                chargeback.created_at.replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(chargeback.created_at, datetime):
                        chargeback_date = chargeback.created_at

                # Apply date filter
                if chargeback_date:
                    if from_date and chargeback_date < from_date:
                        continue
                    if until_date and chargeback_date > until_date:
                        continue

                filtered_chargebacks.append(chargeback)

            return filtered_chargebacks

        return chargebacks

    def analyze_chargeback_trends(self, period_days: int = 90) -> Dict:
        """
        Analyze chargeback trends and patterns

        Args:
            period_days: Number of days to analyze

        Returns:
            Dict with trend analysis
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        chargebacks = self.list_all_chargebacks(from_date=start_date, until_date=end_date)

        analysis = {
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": period_days},
            "total_chargebacks": len(chargebacks),
            "total_amount": Decimal("0"),
            "total_impact": Decimal("0"),
            "by_reason": {},
            "by_status": {"reversed": 0, "active": 0},
            "by_month": {},
            "average_per_day": 0,
            "high_risk_indicators": [],
        }

        for chargeback in chargebacks:
            # Sum amounts
            if chargeback.amount and hasattr(chargeback.amount, "decimal_value"):
                analysis["total_amount"] += chargeback.amount.decimal_value

            analysis["total_impact"] += chargeback.get_financial_impact()

            # Count by status
            if chargeback.is_reversed():
                analysis["by_status"]["reversed"] += 1
            else:
                analysis["by_status"]["active"] += 1

            # Group by reason
            reason_code = chargeback.get_reason_code() or "unknown"
            if reason_code not in analysis["by_reason"]:
                analysis["by_reason"][reason_code] = {
                    "count": 0,
                    "amount": Decimal("0"),
                    "description": chargeback.get_reason_description(),
                }

            analysis["by_reason"][reason_code]["count"] += 1
            if chargeback.amount:
                analysis["by_reason"][reason_code]["amount"] += chargeback.amount.decimal_value

            # Group by month
            if chargeback.created_at:
                month_key = chargeback.created_at[:7]  # YYYY-MM
                if month_key not in analysis["by_month"]:
                    analysis["by_month"][month_key] = {"count": 0, "amount": Decimal("0")}

                analysis["by_month"][month_key]["count"] += 1
                if chargeback.amount:
                    analysis["by_month"][month_key]["amount"] += chargeback.amount.decimal_value

        # Calculate averages
        analysis["average_per_day"] = len(chargebacks) / period_days if period_days > 0 else 0

        # Identify high-risk patterns
        if analysis["total_chargebacks"] > period_days * 0.1:  # More than 0.1 per day
            analysis["high_risk_indicators"].append("High chargeback frequency")

        if ChargebackReason.FRAUDULENT.value in analysis["by_reason"]:
            fraud_count = analysis["by_reason"][ChargebackReason.FRAUDULENT.value]["count"]
            if fraud_count > len(chargebacks) * 0.3:  # More than 30% fraud
                analysis["high_risk_indicators"].append("High fraud rate")

        # Convert Decimals to float for JSON
        analysis["total_amount"] = float(analysis["total_amount"])
        analysis["total_impact"] = float(analysis["total_impact"])

        for reason in analysis["by_reason"]:
            analysis["by_reason"][reason]["amount"] = float(analysis["by_reason"][reason]["amount"])

        for month in analysis["by_month"]:
            analysis["by_month"][month]["amount"] = float(analysis["by_month"][month]["amount"])

        # Log if high risk
        if analysis["high_risk_indicators"]:
            self.audit_trail.log_event(
                AuditEventType.CHARGEBACK_RECEIVED,
                AuditSeverity.WARNING,
                "High chargeback risk detected",
                details=analysis,
            )

            frappe.publish_realtime(
                "chargeback_alert",
                {
                    "message": _("High chargeback risk detected"),
                    "indicators": analysis["high_risk_indicators"],
                    "total_chargebacks": analysis["total_chargebacks"],
                    "total_impact": analysis["total_impact"],
                },
                user=frappe.session.user,
            )

        return analysis

    def calculate_financial_impact(self, from_date: datetime, until_date: datetime) -> Dict:
        """
        Calculate total financial impact of chargebacks

        Args:
            from_date: Period start
            until_date: Period end

        Returns:
            Dict with financial impact details
        """
        chargebacks = self.list_all_chargebacks(from_date=from_date, until_date=until_date)

        impact = {
            "period": {"from": from_date.isoformat(), "until": until_date.isoformat()},
            "chargeback_count": len(chargebacks),
            "direct_loss": Decimal("0"),
            "fees_and_penalties": Decimal("0"),
            "total_impact": Decimal("0"),
            "reversed_amount": Decimal("0"),
            "net_loss": Decimal("0"),
            "chargebacks": [],
        }

        for chargeback in chargebacks:
            cb_impact = chargeback.get_financial_impact()

            # Track individual chargeback
            cb_data = {
                "id": chargeback.id,
                "payment_id": chargeback.payment_id,
                "amount": float(chargeback.amount.decimal_value) if chargeback.amount else 0,
                "impact": float(cb_impact),
                "reversed": chargeback.is_reversed(),
                "reason": chargeback.get_reason_code(),
            }

            impact["chargebacks"].append(cb_data)

            # Calculate totals
            if chargeback.amount and hasattr(chargeback.amount, "decimal_value"):
                impact["direct_loss"] += chargeback.amount.decimal_value

                if chargeback.is_reversed():
                    impact["reversed_amount"] += chargeback.amount.decimal_value

            if chargeback.settlement_amount and hasattr(chargeback.settlement_amount, "decimal_value"):
                # Settlement amount usually includes fees
                fees = abs(chargeback.settlement_amount.decimal_value) - (
                    chargeback.amount.decimal_value if chargeback.amount else Decimal("0")
                )
                impact["fees_and_penalties"] += fees

            impact["total_impact"] += cb_impact

        # Calculate net loss
        impact["net_loss"] = impact["total_impact"] - impact["reversed_amount"]

        # Convert to float for JSON
        impact["direct_loss"] = float(impact["direct_loss"])
        impact["fees_and_penalties"] = float(impact["fees_and_penalties"])
        impact["total_impact"] = float(impact["total_impact"])
        impact["reversed_amount"] = float(impact["reversed_amount"])
        impact["net_loss"] = float(impact["net_loss"])

        # Log financial impact
        self.audit_trail.log_event(
            AuditEventType.REPORT_GENERATED,
            AuditSeverity.INFO,
            f"Chargeback financial impact calculated: €{impact['net_loss']:.2f}",
            details=impact,
        )

        return impact

    def get_chargeback_prevention_insights(self) -> Dict:
        """
        Get insights for chargeback prevention

        Returns:
            Dict with prevention recommendations
        """
        # Analyze recent chargebacks
        analysis = self.analyze_chargeback_trends(period_days=30)

        insights = {
            "risk_level": "low",
            "recommendations": [],
            "top_reasons": [],
            "metrics": {
                "current_rate": analysis["average_per_day"],
                "total_last_30_days": analysis["total_chargebacks"],
                "financial_impact": analysis["total_impact"],
            },
        }

        # Determine risk level
        if analysis["average_per_day"] > 0.5:
            insights["risk_level"] = "high"
        elif analysis["average_per_day"] > 0.2:
            insights["risk_level"] = "medium"

        # Get top reasons
        sorted_reasons = sorted(analysis["by_reason"].items(), key=lambda x: x[1]["count"], reverse=True)

        for reason, data in sorted_reasons[:3]:
            insights["top_reasons"].append(
                {
                    "reason": reason,
                    "count": data["count"],
                    "percentage": (data["count"] / analysis["total_chargebacks"] * 100)
                    if analysis["total_chargebacks"] > 0
                    else 0,
                }
            )

        # Generate recommendations based on patterns
        if ChargebackReason.FRAUDULENT.value in [r["reason"] for r in insights["top_reasons"]]:
            insights["recommendations"].append(
                {
                    "priority": "high",
                    "action": "Implement additional fraud detection",
                    "reason": "High rate of fraud-related chargebacks",
                }
            )

        if ChargebackReason.UNRECOGNIZED.value in [r["reason"] for r in insights["top_reasons"]]:
            insights["recommendations"].append(
                {
                    "priority": "medium",
                    "action": "Improve transaction descriptors",
                    "reason": "Customers not recognizing charges",
                }
            )

        if analysis["total_chargebacks"] > 10:
            insights["recommendations"].append(
                {
                    "priority": "medium",
                    "action": "Review customer communication",
                    "reason": "Overall chargeback volume is elevated",
                }
            )

        return insights

    def handle_new_chargeback(self, payment_id: str, chargeback_id: str) -> Dict:
        """
        Handle a new chargeback notification

        Args:
            payment_id: Payment identifier
            chargeback_id: Chargeback identifier

        Returns:
            Dict with handling results
        """
        # Get chargeback details
        chargeback = self.get_chargeback(payment_id, chargeback_id)

        handling_result = {
            "chargeback_id": chargeback_id,
            "payment_id": payment_id,
            "amount": float(chargeback.amount.decimal_value) if chargeback.amount else 0,
            "reason": chargeback.get_reason_code(),
            "reason_description": chargeback.get_reason_description(),
            "created_at": chargeback.created_at,
            "actions_taken": [],
        }

        # Log the chargeback
        self.audit_trail.log_event(
            AuditEventType.CHARGEBACK_RECEIVED,
            AuditSeverity.WARNING,
            f"New chargeback received: {chargeback_id}",
            details=handling_result,
        )
        handling_result["actions_taken"].append("Logged in audit trail")

        # Send notification
        frappe.publish_realtime(
            "new_chargeback",
            {
                "message": _(f"New chargeback received for payment {payment_id}"),
                "chargeback_id": chargeback_id,
                "amount": handling_result["amount"],
                "reason": handling_result["reason_description"],
            },
            user=frappe.session.user,
        )
        handling_result["actions_taken"].append("Notification sent")

        # Would trigger additional workflows here
        # - Update payment status
        # - Notify accounting
        # - Create dispute case

        return handling_result
