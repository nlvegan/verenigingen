"""
Balance Monitoring and Alert System
Real-time monitoring of financial balances with intelligent alerting
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from ..clients.balances_client import BalancesClient
from ..clients.settlements_client import SettlementsClient
from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.compliance.audit_trail import ImmutableAuditTrail as AuditTrail


class AlertSeverity(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    """Types of balance alerts"""

    LOW_BALANCE = "low_balance"
    NEGATIVE_BALANCE = "negative_balance"
    HIGH_PENDING = "high_pending"
    UNUSUAL_ACTIVITY = "unusual_activity"
    SETTLEMENT_DELAY = "settlement_delay"
    RAPID_DECREASE = "rapid_decrease"
    THRESHOLD_BREACH = "threshold_breach"


class BalanceMonitor:
    """
    Intelligent balance monitoring system

    Provides:
    - Real-time balance tracking
    - Predictive alerts
    - Anomaly detection
    - Threshold management
    - Automated responses
    - Historical analysis
    """

    def __init__(self):
        """Initialize balance monitor"""
        self.audit_trail = AuditTrail()

        # Initialize API clients
        self.balances_client = BalancesClient()
        self.settlements_client = SettlementsClient()

        # Load monitoring configuration
        self.config = self._load_monitoring_config()

        # Alert history for rate limiting
        self.recent_alerts = []

    def _load_monitoring_config(self) -> Dict:
        """Load monitoring configuration"""
        return {
            "thresholds": {
                "low_balance_eur": 1000,
                "critical_balance_eur": 100,
                "high_pending_ratio": 0.5,  # Pending > 50% of available
                "rapid_decrease_percent": 20,  # 20% decrease in 1 hour
            },
            "check_interval_minutes": 15,
            "alert_cooldown_minutes": 60,
            "predictive_enabled": True,
            "auto_response_enabled": True,
        }

    def run_monitoring_cycle(self) -> Dict:
        """
        Run a complete monitoring cycle

        Returns:
            Dict with monitoring results
        """
        cycle_result = {
            "timestamp": now_datetime(),
            "balances_checked": 0,
            "alerts_generated": [],
            "actions_taken": [],
            "status": "success",
        }

        try:
            # Get all balances
            balances = self.balances_client.list_balances()
            cycle_result["balances_checked"] = len(balances)

            for balance in balances:
                # Run checks for each balance
                alerts = self._check_balance(balance)
                cycle_result["alerts_generated"].extend(alerts)

                # Take automated actions if configured
                if self.config["auto_response_enabled"] and alerts:
                    actions = self._take_automated_actions(balance, alerts)
                    cycle_result["actions_taken"].extend(actions)

            # Check for cross-balance issues
            cross_alerts = self._check_cross_balance_issues(balances)
            cycle_result["alerts_generated"].extend(cross_alerts)

            # Run predictive analysis if enabled
            if self.config["predictive_enabled"]:
                predictions = self._run_predictive_analysis(balances)
                cycle_result["predictions"] = predictions

            # Process and send alerts
            self._process_alerts(cycle_result["alerts_generated"])

            # Log monitoring cycle
            self.audit_trail.log_event(
                AuditEventType.MONITORING_CHECK,
                AuditSeverity.INFO,
                "Balance monitoring cycle completed",
                details=cycle_result,
            )

        except Exception as e:
            cycle_result["status"] = "failed"
            cycle_result["error"] = str(e)

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED, AuditSeverity.ERROR, f"Balance monitoring failed: {str(e)}"
            )

        return cycle_result

    def _check_balance(self, balance) -> List[Dict]:
        """Check individual balance for issues"""
        alerts = []

        # Get balance details
        available = balance.available_amount.decimal_value if balance.available_amount else Decimal("0")
        pending = balance.pending_amount.decimal_value if balance.pending_amount else Decimal("0")
        currency = balance.currency

        # Check for negative balance
        if available < 0:
            alerts.append(
                {
                    "type": AlertType.NEGATIVE_BALANCE.value,
                    "severity": AlertSeverity.EMERGENCY.value,
                    "currency": currency,
                    "message": f"Negative balance detected: {currency} {available}",
                    "value": float(available),
                    "threshold": 0,
                }
            )

        # Check for low balance (EUR only for simplicity)
        elif currency == "EUR" and available < self.config["thresholds"]["critical_balance_eur"]:
            alerts.append(
                {
                    "type": AlertType.LOW_BALANCE.value,
                    "severity": AlertSeverity.CRITICAL.value,
                    "currency": currency,
                    "message": f"Critical low balance: {currency} {available}",
                    "value": float(available),
                    "threshold": self.config["thresholds"]["critical_balance_eur"],
                }
            )

        elif currency == "EUR" and available < self.config["thresholds"]["low_balance_eur"]:
            alerts.append(
                {
                    "type": AlertType.LOW_BALANCE.value,
                    "severity": AlertSeverity.WARNING.value,
                    "currency": currency,
                    "message": f"Low balance warning: {currency} {available}",
                    "value": float(available),
                    "threshold": self.config["thresholds"]["low_balance_eur"],
                }
            )

        # Check high pending ratio
        if available > 0 and pending / available > self.config["thresholds"]["high_pending_ratio"]:
            alerts.append(
                {
                    "type": AlertType.HIGH_PENDING.value,
                    "severity": AlertSeverity.WARNING.value,
                    "currency": currency,
                    "message": f"High pending amount: {currency} {pending} (pending > 50% of available)",
                    "value": float(pending),
                    "ratio": float(pending / available),
                }
            )

        # Check for rapid decrease
        decrease_alert = self._check_rapid_decrease(balance)
        if decrease_alert:
            alerts.append(decrease_alert)

        # Check for settlement delays
        settlement_alert = self._check_settlement_delays(balance)
        if settlement_alert:
            alerts.append(settlement_alert)

        return alerts

    def _check_rapid_decrease(self, balance) -> Optional[Dict]:
        """Check for rapid balance decrease"""
        try:
            # Get balance history (would need to store snapshots)
            # For now, we'll check recent transactions
            transactions = self.balances_client.list_balance_transactions(
                balance.id, from_date=datetime.now() - timedelta(hours=1)
            )

            # Calculate net change
            net_change = sum(
                t.result_amount.decimal_value if t.result_amount else Decimal("0") for t in transactions
            )

            current_balance = (
                balance.available_amount.decimal_value if balance.available_amount else Decimal("0")
            )

            if current_balance > 0 and net_change < 0:
                decrease_percent = abs(net_change / current_balance * 100)

                if decrease_percent > self.config["thresholds"]["rapid_decrease_percent"]:
                    return {
                        "type": AlertType.RAPID_DECREASE.value,
                        "severity": AlertSeverity.WARNING.value,
                        "currency": balance.currency,
                        "message": f"Rapid balance decrease: {decrease_percent:.1f}% in last hour",
                        "decrease_amount": float(abs(net_change)),
                        "decrease_percent": float(decrease_percent),
                    }

        except Exception:
            pass

        return None

    def _check_settlement_delays(self, balance) -> Optional[Dict]:
        """Check for settlement delays"""
        try:
            # Get next settlement
            next_settlement = self.settlements_client.get_next_settlement()

            if next_settlement and next_settlement.created_at:
                # Check if settlement is overdue
                created = datetime.fromisoformat(next_settlement.created_at.replace("Z", "+00:00"))
                days_pending = (datetime.now() - created).days

                if days_pending > 5:
                    return {
                        "type": AlertType.SETTLEMENT_DELAY.value,
                        "severity": AlertSeverity.WARNING.value,
                        "currency": balance.currency,
                        "message": f"Settlement delayed by {days_pending} days",
                        "settlement_id": next_settlement.id,
                        "days_delayed": days_pending,
                    }

        except Exception:
            pass

        return None

    def _check_cross_balance_issues(self, balances) -> List[Dict]:
        """Check for issues across multiple balances"""
        alerts = []

        try:
            # Check total available across all currencies
            total_eur_equivalent = Decimal("0")

            for balance in balances:
                if balance.available_amount:
                    # Convert to EUR (simplified - would use actual rates)
                    if balance.currency == "EUR":
                        total_eur_equivalent += balance.available_amount.decimal_value
                    elif balance.currency == "USD":
                        total_eur_equivalent += balance.available_amount.decimal_value * Decimal("0.85")
                    elif balance.currency == "GBP":
                        total_eur_equivalent += balance.available_amount.decimal_value * Decimal("1.15")

            # Check if total is concerning
            if total_eur_equivalent < 5000:
                alerts.append(
                    {
                        "type": AlertType.LOW_BALANCE.value,
                        "severity": AlertSeverity.WARNING.value,
                        "currency": "ALL",
                        "message": f"Total balance across all currencies is low: €{total_eur_equivalent:.2f} equivalent",
                        "value": float(total_eur_equivalent),
                        "threshold": 5000,
                    }
                )

        except Exception:
            pass

        return alerts

    def _run_predictive_analysis(self, balances) -> Dict:
        """Run predictive analysis on balances"""
        predictions = {"run_at": now_datetime(), "predictions": []}

        try:
            for balance in balances:
                if balance.currency != "EUR":
                    continue

                # Get transaction history
                transactions = self.balances_client.list_balance_transactions(
                    balance.id, from_date=datetime.now() - timedelta(days=7)
                )

                # Calculate average daily change
                daily_changes = {}
                for transaction in transactions:
                    date = transaction.created_at[:10] if transaction.created_at else None
                    if date:
                        if date not in daily_changes:
                            daily_changes[date] = Decimal("0")
                        if transaction.result_amount:
                            daily_changes[date] += transaction.result_amount.decimal_value

                if daily_changes:
                    avg_daily_change = sum(daily_changes.values()) / len(daily_changes)
                    current = (
                        balance.available_amount.decimal_value if balance.available_amount else Decimal("0")
                    )

                    # Predict balance in 3 days
                    predicted_3d = current + (avg_daily_change * 3)

                    # Predict balance in 7 days
                    predicted_7d = current + (avg_daily_change * 7)

                    prediction = {
                        "currency": balance.currency,
                        "current_balance": float(current),
                        "avg_daily_change": float(avg_daily_change),
                        "predicted_3_days": float(predicted_3d),
                        "predicted_7_days": float(predicted_7d),
                    }

                    # Check if prediction shows concerning trend
                    if predicted_3d < self.config["thresholds"]["critical_balance_eur"]:
                        prediction["alert"] = "Balance expected to be critical in 3 days"
                        prediction["alert_severity"] = AlertSeverity.WARNING.value
                    elif predicted_7d < self.config["thresholds"]["low_balance_eur"]:
                        prediction["alert"] = "Balance expected to be low in 7 days"
                        prediction["alert_severity"] = AlertSeverity.INFO.value

                    predictions["predictions"].append(prediction)

        except Exception as e:
            predictions["error"] = str(e)

        return predictions

    def _take_automated_actions(self, balance, alerts: List[Dict]) -> List[Dict]:
        """Take automated actions based on alerts"""
        actions = []

        for alert in alerts:
            # Critical low balance - initiate payout hold
            if (
                alert["type"] == AlertType.LOW_BALANCE.value
                and alert["severity"] == AlertSeverity.CRITICAL.value
            ):
                action = {
                    "type": "payout_hold",
                    "reason": "Critical low balance",
                    "balance_id": balance.id,
                    "executed_at": now_datetime(),
                }

                # Would implement actual payout hold here
                actions.append(action)

                self.audit_trail.log_event(
                    AuditEventType.AUTOMATED_ACTION,
                    AuditSeverity.WARNING,
                    f"Automated payout hold for {balance.currency}",
                    details=action,
                )

            # Negative balance - escalate immediately
            elif alert["type"] == AlertType.NEGATIVE_BALANCE.value:
                action = {
                    "type": "emergency_escalation",
                    "reason": "Negative balance detected",
                    "balance_id": balance.id,
                    "notified": ["Finance Team", "Operations Manager"],
                    "executed_at": now_datetime(),
                }

                # Send emergency notifications
                self._send_emergency_notification(alert, action)
                actions.append(action)

        return actions

    def _send_emergency_notification(self, alert: Dict, action: Dict):
        """Send emergency notification"""
        try:
            # Send email notification
            frappe.sendmail(
                recipients=["finance@company.com"],
                subject=f"EMERGENCY: {alert['message']}",
                message=f"""
                Emergency Alert:

                Type: {alert['type']}
                Severity: {alert['severity']}
                Message: {alert['message']}

                Action Taken: {action['type']}

                Please review immediately.
                """,
            )

            # Send realtime notification
            frappe.publish_realtime(
                "emergency_alert",
                {
                    "message": alert["message"],
                    "type": alert["type"],
                    "severity": alert["severity"],
                    "action": action,
                },
            )

        except Exception:
            pass

    def _process_alerts(self, alerts: List[Dict]):
        """Process and send alerts with rate limiting"""
        for alert in alerts:
            # Check if similar alert was recently sent
            if not self._should_send_alert(alert):
                continue

            # Send alert based on severity
            if alert["severity"] == AlertSeverity.EMERGENCY.value:
                self._send_emergency_alert(alert)
            elif alert["severity"] == AlertSeverity.CRITICAL.value:
                self._send_critical_alert(alert)
            elif alert["severity"] == AlertSeverity.WARNING.value:
                self._send_warning_alert(alert)
            else:
                self._send_info_alert(alert)

            # Track alert
            self.recent_alerts.append({"alert": alert, "sent_at": now_datetime()})

    def _should_send_alert(self, alert: Dict) -> bool:
        """Check if alert should be sent (rate limiting)"""
        cooldown = timedelta(minutes=self.config["alert_cooldown_minutes"])
        cutoff_time = now_datetime() - cooldown

        for recent in self.recent_alerts:
            if recent["sent_at"] < cutoff_time:
                continue

            # Check if similar alert
            if recent["alert"]["type"] == alert["type"] and recent["alert"].get("currency") == alert.get(
                "currency"
            ):
                return False

        return True

    def _send_emergency_alert(self, alert: Dict):
        """Send emergency severity alert"""
        frappe.publish_realtime(
            "balance_emergency", alert, user=frappe.session.user if frappe.session else None
        )

    def _send_critical_alert(self, alert: Dict):
        """Send critical severity alert"""
        frappe.publish_realtime(
            "balance_critical", alert, user=frappe.session.user if frappe.session else None
        )

    def _send_warning_alert(self, alert: Dict):
        """Send warning severity alert"""
        frappe.publish_realtime(
            "balance_warning", alert, user=frappe.session.user if frappe.session else None
        )

    def _send_info_alert(self, alert: Dict):
        """Send info severity alert"""
        frappe.publish_realtime("balance_info", alert, user=frappe.session.user if frappe.session else None)

    def set_custom_threshold(self, balance_id: str, threshold_type: str, value: float) -> Dict:
        """
        Set custom threshold for specific balance

        Args:
            balance_id: Balance identifier
            threshold_type: Type of threshold
            value: Threshold value

        Returns:
            Dict with update result
        """
        result = {
            "balance_id": balance_id,
            "threshold_type": threshold_type,
            "value": value,
            "updated_at": now_datetime(),
        }

        try:
            # Store custom threshold
            doc = frappe.new_doc("Balance Threshold")
            doc.balance_id = balance_id
            doc.threshold_type = threshold_type
            doc.threshold_value = value
            doc.active = True
            doc.insert(ignore_permissions=True)

            result["status"] = "success"

            # Log threshold change
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.INFO,
                f"Custom threshold set for {balance_id}",
                details=result,
            )

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    def get_balance_health_score(self, balance_id: str) -> Dict:
        """
        Calculate health score for a balance

        Args:
            balance_id: Balance identifier

        Returns:
            Dict with health score and factors
        """
        health = {
            "balance_id": balance_id,
            "score": 100,  # Start with perfect score
            "factors": [],
            "status": "healthy",
            "calculated_at": now_datetime(),
        }

        try:
            # Get balance
            balance = self.balances_client.get_balance(balance_id)

            available = balance.available_amount.decimal_value if balance.available_amount else Decimal("0")
            pending = balance.pending_amount.decimal_value if balance.pending_amount else Decimal("0")

            # Factor 1: Balance level
            if available < 0:
                health["score"] -= 50
                health["factors"].append({"factor": "negative_balance", "impact": -50})
            elif balance.currency == "EUR" and available < self.config["thresholds"]["critical_balance_eur"]:
                health["score"] -= 30
                health["factors"].append({"factor": "critical_low_balance", "impact": -30})
            elif balance.currency == "EUR" and available < self.config["thresholds"]["low_balance_eur"]:
                health["score"] -= 15
                health["factors"].append({"factor": "low_balance", "impact": -15})

            # Factor 2: Pending ratio
            if available > 0 and pending / available > 0.5:
                health["score"] -= 20
                health["factors"].append({"factor": "high_pending_ratio", "impact": -20})

            # Factor 3: Recent transactions
            recent_transactions = self.balances_client.list_balance_transactions(
                balance_id, from_date=datetime.now() - timedelta(days=1)
            )

            if len(recent_transactions) > 100:
                health["score"] -= 10
                health["factors"].append({"factor": "high_transaction_volume", "impact": -10})

            # Determine overall status
            if health["score"] >= 80:
                health["status"] = "healthy"
            elif health["score"] >= 60:
                health["status"] = "fair"
            elif health["score"] >= 40:
                health["status"] = "poor"
            else:
                health["status"] = "critical"

        except Exception as e:
            health["error"] = str(e)
            health["status"] = "unknown"

        return health


# Scheduled monitoring task
@frappe.whitelist()
def run_balance_monitoring():
    """Run scheduled balance monitoring"""
    settings = frappe.get_single("Mollie Settings")

    if not settings.enable_backend_api:
        return {"status": "skipped", "reason": "Backend API not enabled"}

    monitor = BalanceMonitor()
    return monitor.run_monitoring_cycle()


# API endpoints
@frappe.whitelist()
def get_balance_health_dashboard():
    """Get balance health dashboard data"""
    settings = frappe.get_single("Mollie Settings")

    if not settings.enable_backend_api:
        return {"status": "error", "message": "Backend API not enabled"}

    monitor = BalanceMonitor()

    # Get all balances
    balances = monitor.balances_client.list_balances()

    dashboard = {"balances": [], "overall_health": "healthy", "active_alerts": [], "predictions": {}}

    for balance in balances:
        # Get health score
        health = monitor.get_balance_health_score(balance.id)

        balance_info = {
            "id": balance.id,
            "currency": balance.currency,
            "available": float(balance.available_amount.decimal_value) if balance.available_amount else 0,
            "pending": float(balance.pending_amount.decimal_value) if balance.pending_amount else 0,
            "health_score": health["score"],
            "health_status": health["status"],
        }

        dashboard["balances"].append(balance_info)

        # Update overall health
        if health["status"] == "critical" and dashboard["overall_health"] != "critical":
            dashboard["overall_health"] = "critical"
        elif health["status"] == "poor" and dashboard["overall_health"] not in ["critical", "poor"]:
            dashboard["overall_health"] = "poor"

    # Run predictive analysis
    dashboard["predictions"] = monitor._run_predictive_analysis(balances)

    return dashboard
