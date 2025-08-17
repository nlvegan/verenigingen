"""
Subscription Management Integration
Bridges Mollie subscriptions with backend financial operations
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from ..clients.balances_client import BalancesClient
from ..clients.settlements_client import SettlementsClient
from ..core.compliance.audit_trail import AuditEventType, AuditSeverity, AuditTrail


class SubscriptionStatus:
    """Subscription status constants"""

    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class SubscriptionManager:
    """
    Manages subscription lifecycle with backend integration

    Provides:
    - Subscription financial tracking
    - Payment reconciliation
    - Revenue recognition
    - Churn analysis
    - Subscription metrics
    - Automated billing coordination
    """

    def __init__(self, settings_name: str):
        """Initialize subscription manager"""
        self.settings_name = settings_name
        self.audit_trail = AuditTrail()

        # Initialize API clients
        self.balances_client = BalancesClient(settings_name)
        self.settlements_client = SettlementsClient(settings_name)

        # Get Mollie settings
        self.settings = frappe.get_doc("Mollie Settings", settings_name)

    def sync_subscription_payments(self, member_name: str) -> Dict:
        """
        Sync subscription payments with backend systems

        Args:
            member_name: Member to sync

        Returns:
            Dict with sync results
        """
        sync_result = {
            "member": member_name,
            "subscription_id": None,
            "payments_synced": 0,
            "revenue_recognized": Decimal("0"),
            "status": "success",
            "issues": [],
        }

        try:
            # Get member and subscription details
            member = frappe.get_doc("Member", member_name)

            if not member.mollie_subscription_id:
                sync_result["status"] = "skipped"
                sync_result["issues"].append("No active subscription")
                return sync_result

            sync_result["subscription_id"] = member.mollie_subscription_id

            # Get recent payments for this subscription
            payments = self._get_subscription_payments(member.mollie_subscription_id)

            for payment in payments:
                # Reconcile each payment with settlements
                reconciliation = self._reconcile_subscription_payment(payment)

                if reconciliation["reconciled"]:
                    sync_result["payments_synced"] += 1
                    sync_result["revenue_recognized"] += reconciliation["amount"]
                else:
                    sync_result["issues"].append(
                        f"Payment {payment['id']} not reconciled: {reconciliation.get('reason')}"
                    )

            # Update member subscription metrics
            self._update_subscription_metrics(member, sync_result)

            # Log sync
            self.audit_trail.log_event(
                AuditEventType.PAYMENT_PROCESSED,
                AuditSeverity.INFO,
                f"Subscription payments synced for {member_name}",
                details=sync_result,
            )

        except Exception as e:
            sync_result["status"] = "failed"
            sync_result["error"] = str(e)

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED,
                AuditSeverity.ERROR,
                f"Subscription sync failed for {member_name}: {str(e)}",
            )

        # Convert decimal to float for JSON
        sync_result["revenue_recognized"] = float(sync_result["revenue_recognized"])

        return sync_result

    def _get_subscription_payments(self, subscription_id: str) -> List[Dict]:
        """Get payments for a subscription"""
        # This would fetch from Mollie API
        # For now, we'll get from Payment Entry records
        payments = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": ["like", f"%{subscription_id}%"], "docstatus": 1},
            fields=["name", "paid_amount", "posting_date", "reference_no"],
            order_by="posting_date desc",
            limit=10,
        )

        return [
            {
                "id": p["name"],
                "amount": p["paid_amount"],
                "date": p["posting_date"],
                "subscription_id": subscription_id,
            }
            for p in payments
        ]

    def _reconcile_subscription_payment(self, payment: Dict) -> Dict:
        """Reconcile subscription payment with settlements"""
        reconciliation = {
            "payment_id": payment["id"],
            "amount": Decimal(str(payment["amount"])),
            "reconciled": False,
            "settlement_id": None,
            "reason": None,
        }

        try:
            # Find settlement containing this payment
            # Look for settlements around the payment date
            search_start = payment["date"] - timedelta(days=2)
            search_end = payment["date"] + timedelta(days=7)

            settlements = self.settlements_client.list_settlements(
                from_date=search_start, until_date=search_end
            )

            for settlement in settlements:
                # Check if payment is in this settlement
                settlement_payments = self.settlements_client.list_settlement_payments(settlement.id)

                for sp in settlement_payments:
                    if sp.get("metadata", {}).get("payment_entry_id") == payment["id"]:
                        reconciliation["reconciled"] = True
                        reconciliation["settlement_id"] = settlement.id
                        break

                if reconciliation["reconciled"]:
                    break

            if not reconciliation["reconciled"]:
                reconciliation["reason"] = "Payment not found in settlements"

        except Exception as e:
            reconciliation["reason"] = f"Reconciliation error: {str(e)}"

        return reconciliation

    def _update_subscription_metrics(self, member, sync_result: Dict):
        """Update subscription metrics for member"""
        try:
            # Update custom fields on member
            member.db_set("subscription_last_sync", now_datetime())
            member.db_set(
                "subscription_revenue_total",
                (member.subscription_revenue_total or 0) + sync_result["revenue_recognized"],
            )
            member.db_set(
                "subscription_payment_count",
                (member.subscription_payment_count or 0) + sync_result["payments_synced"],
            )

            if sync_result["issues"]:
                member.db_set("subscription_sync_issues", json.dumps(sync_result["issues"]))

        except Exception as e:
            frappe.log_error(f"Failed to update subscription metrics: {str(e)}", "Subscription Manager")

    def analyze_subscription_revenue(self, period_days: int = 30) -> Dict:
        """
        Analyze subscription revenue patterns

        Args:
            period_days: Analysis period in days

        Returns:
            Dict with revenue analysis
        """
        analysis = {
            "period": {
                "days": period_days,
                "start": add_days(now_datetime(), -period_days),
                "end": now_datetime(),
            },
            "metrics": {
                "total_revenue": Decimal("0"),
                "recurring_revenue": Decimal("0"),
                "average_subscription_value": Decimal("0"),
                "growth_rate": 0,
            },
            "by_frequency": {},
            "by_status": {},
            "churn": {"rate": 0, "count": 0, "revenue_impact": Decimal("0")},
        }

        try:
            # Get all active subscriptions
            active_members = frappe.get_all(
                "Member",
                filters={"subscription_status": "active", "mollie_subscription_id": ["is", "set"]},
                fields=["name", "mollie_subscription_id", "subscription_amount", "billing_frequency"],
            )

            # Calculate recurring revenue
            for member in active_members:
                monthly_value = self._calculate_monthly_value(
                    member.get("subscription_amount", 0), member.get("billing_frequency", "monthly")
                )
                analysis["metrics"]["recurring_revenue"] += monthly_value

                # Group by frequency
                frequency = member.get("billing_frequency", "monthly")
                if frequency not in analysis["by_frequency"]:
                    analysis["by_frequency"][frequency] = {"count": 0, "revenue": Decimal("0")}
                analysis["by_frequency"][frequency]["count"] += 1
                analysis["by_frequency"][frequency]["revenue"] += monthly_value

            # Get actual revenue from settlements
            settlements = self.settlements_client.list_settlements(
                from_date=analysis["period"]["start"], until_date=analysis["period"]["end"]
            )

            for settlement in settlements:
                # Extract subscription revenue from settlement
                revenue = self._extract_subscription_revenue(settlement)
                analysis["metrics"]["total_revenue"] += revenue

            # Calculate average subscription value
            if active_members:
                analysis["metrics"]["average_subscription_value"] = analysis["metrics"][
                    "recurring_revenue"
                ] / len(active_members)

            # Analyze churn
            churned = frappe.get_all(
                "Member",
                filters={
                    "subscription_status": "cancelled",
                    "subscription_cancelled_date": [">=", analysis["period"]["start"]],
                },
                fields=["name", "subscription_amount", "billing_frequency"],
            )

            analysis["churn"]["count"] = len(churned)

            for member in churned:
                monthly_value = self._calculate_monthly_value(
                    member.get("subscription_amount", 0), member.get("billing_frequency", "monthly")
                )
                analysis["churn"]["revenue_impact"] += monthly_value

            # Calculate churn rate
            total_at_start = len(active_members) + len(churned)
            if total_at_start > 0:
                analysis["churn"]["rate"] = (len(churned) / total_at_start) * 100

            # Calculate growth rate (compare to previous period)
            prev_period_revenue = self._get_previous_period_revenue(period_days)
            if prev_period_revenue > 0:
                growth = (
                    (analysis["metrics"]["total_revenue"] - prev_period_revenue) / prev_period_revenue
                ) * 100
                analysis["metrics"]["growth_rate"] = float(growth)

            # Convert decimals to float
            analysis["metrics"]["total_revenue"] = float(analysis["metrics"]["total_revenue"])
            analysis["metrics"]["recurring_revenue"] = float(analysis["metrics"]["recurring_revenue"])
            analysis["metrics"]["average_subscription_value"] = float(
                analysis["metrics"]["average_subscription_value"]
            )
            analysis["churn"]["revenue_impact"] = float(analysis["churn"]["revenue_impact"])

            for frequency in analysis["by_frequency"]:
                analysis["by_frequency"][frequency]["revenue"] = float(
                    analysis["by_frequency"][frequency]["revenue"]
                )

        except Exception as e:
            analysis["error"] = str(e)

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED,
                AuditSeverity.ERROR,
                f"Subscription revenue analysis failed: {str(e)}",
            )

        return analysis

    def _calculate_monthly_value(self, amount: float, frequency: str) -> Decimal:
        """Calculate monthly value from subscription amount and frequency"""
        amount = Decimal(str(amount))

        if frequency == "monthly":
            return amount
        elif frequency == "quarterly":
            return amount / 3
        elif frequency == "yearly":
            return amount / 12
        elif frequency == "weekly":
            return amount * 4.33  # Average weeks per month
        else:
            return amount  # Default to monthly

    def _extract_subscription_revenue(self, settlement) -> Decimal:
        """Extract subscription revenue from settlement"""
        revenue = Decimal("0")

        # Get settlement payments
        try:
            payments = self.settlements_client.list_settlement_payments(settlement.id)

            for payment in payments:
                # Check if payment is subscription-related
                if payment.get("metadata", {}).get("type") == "subscription":
                    amount = payment.get("settlementAmount", {}).get("value", "0")
                    revenue += Decimal(amount)

        except Exception:
            pass

        return revenue

    def _get_previous_period_revenue(self, period_days: int) -> Decimal:
        """Get revenue from previous period for comparison"""
        prev_start = add_days(now_datetime(), -(period_days * 2))
        prev_end = add_days(now_datetime(), -period_days)

        revenue = Decimal("0")

        try:
            settlements = self.settlements_client.list_settlements(from_date=prev_start, until_date=prev_end)

            for settlement in settlements:
                revenue += self._extract_subscription_revenue(settlement)

        except Exception:
            pass

        return revenue

    def forecast_subscription_revenue(self, months: int = 3) -> Dict:
        """
        Forecast subscription revenue

        Args:
            months: Number of months to forecast

        Returns:
            Dict with revenue forecast
        """
        forecast = {
            "period_months": months,
            "projections": [],
            "assumptions": {"churn_rate": 0, "growth_rate": 0, "average_subscription_value": 0},
            "total_projected": Decimal("0"),
        }

        try:
            # Get current metrics
            current_analysis = self.analyze_subscription_revenue(30)

            # Set assumptions
            forecast["assumptions"]["churn_rate"] = current_analysis["churn"]["rate"]
            forecast["assumptions"]["growth_rate"] = current_analysis["metrics"]["growth_rate"]
            forecast["assumptions"]["average_subscription_value"] = current_analysis["metrics"][
                "average_subscription_value"
            ]

            # Get active subscription count
            active_count = frappe.db.count(
                "Member", filters={"subscription_status": "active", "mollie_subscription_id": ["is", "set"]}
            )

            # Project each month
            for month in range(1, months + 1):
                # Apply growth and churn
                projected_count = active_count * (1 + forecast["assumptions"]["growth_rate"] / 100) ** month
                projected_count *= (1 - forecast["assumptions"]["churn_rate"] / 100) ** month

                # Calculate revenue
                monthly_revenue = Decimal(str(projected_count)) * Decimal(
                    str(forecast["assumptions"]["average_subscription_value"])
                )

                projection = {
                    "month": month,
                    "projected_subscribers": int(projected_count),
                    "projected_revenue": float(monthly_revenue),
                }

                forecast["projections"].append(projection)
                forecast["total_projected"] += monthly_revenue

            forecast["total_projected"] = float(forecast["total_projected"])

        except Exception as e:
            forecast["error"] = str(e)

        return forecast

    def identify_at_risk_subscriptions(self) -> List[Dict]:
        """
        Identify subscriptions at risk of churning

        Returns:
            List of at-risk subscriptions
        """
        at_risk = []

        try:
            # Get active subscriptions
            members = frappe.get_all(
                "Member",
                filters={"subscription_status": "active", "mollie_subscription_id": ["is", "set"]},
                fields=[
                    "name",
                    "full_name",
                    "mollie_subscription_id",
                    "last_payment_date",
                    "payment_failure_count",
                ],
            )

            for member in members:
                risk_score = 0
                risk_factors = []

                # Check payment failures
                if member.get("payment_failure_count", 0) > 2:
                    risk_score += 40
                    risk_factors.append("Multiple payment failures")

                # Check last payment date
                if member.get("last_payment_date"):
                    days_since_payment = (datetime.now().date() - member["last_payment_date"]).days

                    if days_since_payment > 45:
                        risk_score += 30
                        risk_factors.append(f"No payment for {days_since_payment} days")

                # Check engagement (simplified - would check actual activity)
                last_login = frappe.db.get_value(
                    "User", {"name": frappe.db.get_value("Member", member["name"], "user")}, "last_login"
                )

                if last_login:
                    days_since_login = (datetime.now() - get_datetime(last_login)).days
                    if days_since_login > 60:
                        risk_score += 20
                        risk_factors.append(f"No login for {days_since_login} days")

                # Add to at-risk list if score is high
                if risk_score >= 50:
                    at_risk.append(
                        {
                            "member": member["name"],
                            "name": member["full_name"],
                            "subscription_id": member["mollie_subscription_id"],
                            "risk_score": risk_score,
                            "risk_factors": risk_factors,
                        }
                    )

            # Sort by risk score
            at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

        except Exception as e:
            frappe.log_error(f"Failed to identify at-risk subscriptions: {str(e)}", "Subscription Manager")

        return at_risk

    def create_retention_campaign(self, at_risk_members: List[str]) -> Dict:
        """
        Create retention campaign for at-risk members

        Args:
            at_risk_members: List of member names

        Returns:
            Dict with campaign details
        """
        campaign = {
            "campaign_id": frappe.generate_hash(length=8),
            "created_at": now_datetime(),
            "target_members": at_risk_members,
            "actions": [],
            "status": "created",
        }

        try:
            for member_name in at_risk_members:
                member = frappe.get_doc("Member", member_name)

                # Determine retention actions
                actions = []

                # Offer discount
                actions.append({"type": "discount_offer", "discount_percent": 20, "valid_months": 3})

                # Send retention email
                actions.append(
                    {
                        "type": "retention_email",
                        "template": "subscription_retention",
                        "send_date": now_datetime(),
                    }
                )

                # Create task for personal outreach
                if member.get("risk_score", 0) > 70:
                    actions.append(
                        {
                            "type": "personal_outreach",
                            "assigned_to": "Customer Success Team",
                            "priority": "high",
                        }
                    )

                campaign["actions"].extend(actions)

                # Log campaign creation
                self.audit_trail.log_event(
                    AuditEventType.CONFIGURATION_CHANGED,
                    AuditSeverity.INFO,
                    f"Retention campaign created for {member_name}",
                    details={"campaign_id": campaign["campaign_id"], "actions": actions},
                )

            campaign["status"] = "active"

        except Exception as e:
            campaign["status"] = "failed"
            campaign["error"] = str(e)

        return campaign


# Scheduled tasks
@frappe.whitelist()
def sync_all_subscription_payments():
    """Sync payments for all active subscriptions"""
    settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)

    if not settings:
        return {"status": "skipped", "reason": "No active settings"}

    manager = SubscriptionManager(settings[0]["name"])

    # Get all active subscription members
    members = frappe.get_all(
        "Member",
        filters={"subscription_status": "active", "mollie_subscription_id": ["is", "set"]},
        pluck="name",
    )

    results = {"total_members": len(members), "synced": 0, "failed": 0, "revenue_recognized": Decimal("0")}

    for member_name in members:
        sync_result = manager.sync_subscription_payments(member_name)

        if sync_result["status"] == "success":
            results["synced"] += 1
            results["revenue_recognized"] += Decimal(str(sync_result["revenue_recognized"]))
        else:
            results["failed"] += 1

    results["revenue_recognized"] = float(results["revenue_recognized"])

    return results


@frappe.whitelist()
def analyze_subscription_health():
    """Analyze overall subscription health"""
    settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)

    if not settings:
        return {"status": "error", "message": "No active settings"}

    manager = SubscriptionManager(settings[0]["name"])

    # Get revenue analysis
    revenue = manager.analyze_subscription_revenue(30)

    # Get forecast
    forecast = manager.forecast_subscription_revenue(3)

    # Identify at-risk subscriptions
    at_risk = manager.identify_at_risk_subscriptions()

    return {
        "revenue_analysis": revenue,
        "forecast": forecast,
        "at_risk_count": len(at_risk),
        "at_risk_members": at_risk[:10],  # Top 10 at risk
    }
