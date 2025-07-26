"""
SEPA Advanced Alerting System

Week 4 Implementation: Comprehensive alerting system for SEPA operations
with configurable thresholds, multiple notification channels, and automated
escalation procedures.

This system monitors SEPA operations in real-time and triggers alerts
based on configurable business rules and performance thresholds.
"""

import json
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import cint, flt, get_datetime, now_datetime

from verenigingen.utils.error_handling import log_error
from verenigingen.utils.sepa_notification_manager import SEPANotificationManager


class AlertSeverity(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertStatus(Enum):
    """Alert status types"""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


@dataclass
class AlertThreshold:
    """Configuration for alert thresholds"""

    metric_name: str
    operator: str  # >, <, >=, <=, ==, !=
    threshold_value: float
    severity: AlertSeverity
    time_window_minutes: int = 5
    min_occurrences: int = 1
    description: str = ""
    enabled: bool = True


@dataclass
class SEPAAlert:
    """SEPA alert data structure"""

    alert_id: str
    alert_type: str
    severity: AlertSeverity
    title: str
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    source_operation: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_config: Optional[AlertThreshold] = None
    status: AlertStatus = AlertStatus.ACTIVE
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    escalation_level: int = 0
    notification_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert enum values to strings
        data["severity"] = self.severity.value
        data["status"] = self.status.value
        # Convert datetime to ISO format
        data["timestamp"] = self.timestamp.isoformat()
        if self.acknowledged_at:
            data["acknowledged_at"] = self.acknowledged_at.isoformat()
        if self.resolved_at:
            data["resolved_at"] = self.resolved_at.isoformat()
        return data


class SEPAAlertingSystem:
    """
    Advanced alerting system for SEPA operations

    Monitors various metrics and triggers alerts based on configurable
    thresholds. Supports multiple notification channels and escalation.
    """

    def __init__(self):
        self.active_alerts: Dict[str, SEPAAlert] = {}
        self.alert_history = deque(maxlen=1000)  # Keep last 1000 alerts
        self.metric_buffer = defaultdict(deque)  # Buffer for time-window calculations
        self.notification_manager = SEPANotificationManager()

        # Load configuration
        self.thresholds = self._load_alert_thresholds()
        self.notification_config = self._load_notification_config()

        # Alert suppression tracking
        self.suppression_rules = {}
        self.escalation_schedules = {}

    def _load_alert_thresholds(self) -> List[AlertThreshold]:
        """Load alert threshold configurations"""
        default_thresholds = [
            AlertThreshold(
                metric_name="batch_creation_time_ms",
                operator=">",
                threshold_value=30000,  # 30 seconds
                severity=AlertSeverity.WARNING,
                time_window_minutes=5,
                description="Batch creation taking longer than 30 seconds",
            ),
            AlertThreshold(
                metric_name="batch_creation_time_ms",
                operator=">",
                threshold_value=60000,  # 60 seconds
                severity=AlertSeverity.CRITICAL,
                time_window_minutes=5,
                description="Batch creation taking longer than 60 seconds",
            ),
            AlertThreshold(
                metric_name="operation_failure_rate_percent",
                operator=">",
                threshold_value=10.0,  # 10%
                severity=AlertSeverity.WARNING,
                time_window_minutes=15,
                min_occurrences=3,
                description="SEPA operation failure rate exceeds 10%",
            ),
            AlertThreshold(
                metric_name="operation_failure_rate_percent",
                operator=">",
                threshold_value=25.0,  # 25%
                severity=AlertSeverity.CRITICAL,
                time_window_minutes=10,
                min_occurrences=2,
                description="SEPA operation failure rate exceeds 25%",
            ),
            AlertThreshold(
                metric_name="memory_usage_mb",
                operator=">",
                threshold_value=1024.0,  # 1GB
                severity=AlertSeverity.WARNING,
                time_window_minutes=10,
                description="High memory usage detected",
            ),
            AlertThreshold(
                metric_name="memory_usage_mb",
                operator=">",
                threshold_value=2048.0,  # 2GB
                severity=AlertSeverity.CRITICAL,
                time_window_minutes=5,
                description="Critical memory usage detected",
            ),
            AlertThreshold(
                metric_name="mandate_validation_failure_rate",
                operator=">",
                threshold_value=5.0,  # 5%
                severity=AlertSeverity.WARNING,
                time_window_minutes=30,
                description="High mandate validation failure rate",
            ),
            AlertThreshold(
                metric_name="stuck_batches_count",
                operator=">",
                threshold_value=5,
                severity=AlertSeverity.CRITICAL,
                time_window_minutes=60,
                description="Multiple batches stuck in processing",
            ),
            AlertThreshold(
                metric_name="large_batch_amount_eur",
                operator=">",
                threshold_value=50000.0,  # €50,000
                severity=AlertSeverity.INFO,
                time_window_minutes=1,
                description="Large batch amount detected (>€50,000)",
            ),
            AlertThreshold(
                metric_name="daily_batch_count",
                operator="<",
                threshold_value=1,
                severity=AlertSeverity.WARNING,
                time_window_minutes=1440,  # 24 hours
                description="No batches created today",
            ),
        ]

        # Try to load custom thresholds from database or config
        try:
            custom_thresholds = frappe.get_single_value("SEPA Settings", "alert_thresholds")
            if custom_thresholds:
                # Parse JSON configuration
                custom_data = json.loads(custom_thresholds)
                for threshold_data in custom_data:
                    default_thresholds.append(AlertThreshold(**threshold_data))
        except Exception as e:
            frappe.logger().warning(f"Could not load custom alert thresholds: {str(e)}")

        return default_thresholds

    def _load_notification_config(self) -> Dict[str, Any]:
        """Load notification configuration"""
        return {
            "email_enabled": True,
            "sms_enabled": False,
            "webhook_enabled": True,
            "default_recipients": ["admin@vereniging.nl", "finance@vereniging.nl"],
            "escalation_recipients": ["manager@vereniging.nl", "director@vereniging.nl"],
            "escalation_delay_minutes": 30,
            "max_escalation_level": 3,
            "webhook_urls": [
                "https://hooks.slack.com/services/...",  # Slack webhook
                "https://discord.com/api/webhooks/...",  # Discord webhook
            ],
            "rate_limit_minutes": 5,  # Don't send same alert more than once per 5 minutes
        }

    def check_metric(self, metric_name: str, value: float, context: Dict[str, Any] = None) -> List[SEPAAlert]:
        """
        Check a metric value against configured thresholds

        Args:
            metric_name: Name of the metric
            value: Metric value to check
            context: Additional context information

        Returns:
            List of triggered alerts
        """
        context = context or {}
        triggered_alerts = []

        # Add metric value to buffer for time-window calculations
        timestamp = get_datetime()
        self.metric_buffer[metric_name].append({"value": value, "timestamp": timestamp, "context": context})

        # Keep only recent values (based on max time window)
        max_window = max((t.time_window_minutes for t in self.thresholds), default=60)
        cutoff_time = timestamp - timedelta(minutes=max_window)

        while (
            self.metric_buffer[metric_name] and self.metric_buffer[metric_name][0]["timestamp"] < cutoff_time
        ):
            self.metric_buffer[metric_name].popleft()

        # Check each threshold
        for threshold in self.thresholds:
            if threshold.metric_name == metric_name and threshold.enabled:
                alert = self._evaluate_threshold(threshold, value, context)
                if alert:
                    triggered_alerts.append(alert)

        return triggered_alerts

    def _evaluate_threshold(
        self, threshold: AlertThreshold, current_value: float, context: Dict[str, Any]
    ) -> Optional[SEPAAlert]:
        """
        Evaluate a single threshold against current and historical values

        Args:
            threshold: Threshold configuration
            current_value: Current metric value
            context: Additional context

        Returns:
            Alert if threshold is breached, None otherwise
        """
        # Get recent values within time window
        cutoff_time = get_datetime() - timedelta(minutes=threshold.time_window_minutes)
        recent_values = [
            entry for entry in self.metric_buffer[threshold.metric_name] if entry["timestamp"] >= cutoff_time
        ]

        if len(recent_values) < threshold.min_occurrences:
            return None

        # Check if threshold is breached
        breached = False

        if threshold.operator == ">":
            breached = current_value > threshold.threshold_value
        elif threshold.operator == "<":
            breached = current_value < threshold.threshold_value
        elif threshold.operator == ">=":
            breached = current_value >= threshold.threshold_value
        elif threshold.operator == "<=":
            breached = current_value <= threshold.threshold_value
        elif threshold.operator == "==":
            breached = current_value == threshold.threshold_value
        elif threshold.operator == "!=":
            breached = current_value != threshold.threshold_value

        if not breached:
            return None

        # Check if we need multiple occurrences
        if threshold.min_occurrences > 1:
            breach_count = 0
            for entry in recent_values:
                entry_breached = False
                if threshold.operator == ">":
                    entry_breached = entry["value"] > threshold.threshold_value
                elif threshold.operator == "<":
                    entry_breached = entry["value"] < threshold.threshold_value
                # ... (similar for other operators)

                if entry_breached:
                    breach_count += 1

            if breach_count < threshold.min_occurrences:
                return None

        # Generate alert
        alert_id = f"{threshold.metric_name}_{threshold.severity.value}_{int(time.time())}"

        # Check if similar alert already exists (avoid spam)
        similar_alert = self._find_similar_active_alert(threshold.metric_name, threshold.severity)
        if similar_alert:
            # Update existing alert instead of creating new one
            similar_alert.metric_value = current_value
            similar_alert.details.update(context)
            similar_alert.timestamp = get_datetime()
            return None  # Don't create duplicate

        alert = SEPAAlert(
            alert_id=alert_id,
            alert_type=f"threshold_breach_{threshold.metric_name}",
            severity=threshold.severity,
            title=f"SEPA Alert: {threshold.description}",
            message=f"{threshold.metric_name} is {current_value:.2f} "
            f"(threshold: {threshold.operator} {threshold.threshold_value})",
            details={
                "metric_name": threshold.metric_name,
                "metric_value": current_value,
                "threshold_value": threshold.threshold_value,
                "operator": threshold.operator,
                "time_window_minutes": threshold.time_window_minutes,
                "occurrences": len(recent_values),
                **context,
            },
            timestamp=get_datetime(),
            metric_value=current_value,
            threshold_config=threshold,
        )

        # Store active alert
        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)

        # Schedule notification
        self._schedule_notification(alert)

        return alert

    def _find_similar_active_alert(self, metric_name: str, severity: AlertSeverity) -> Optional[SEPAAlert]:
        """Find similar active alert to avoid duplicates"""
        for alert in self.active_alerts.values():
            if (
                alert.status == AlertStatus.ACTIVE
                and alert.details.get("metric_name") == metric_name
                and alert.severity == severity
            ):
                return alert
        return None

    def _schedule_notification(self, alert: SEPAAlert) -> None:
        """Schedule notification for an alert"""
        try:
            # Check rate limiting
            if self._is_rate_limited(alert):
                frappe.logger().info(f"Alert {alert.alert_id} rate limited, skipping notification")
                return

            # Send immediate notification
            self._send_notification(alert)

            # Schedule escalation if configured
            if alert.severity in [AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY]:
                self._schedule_escalation(alert)

        except Exception as e:
            log_error(
                e,
                context={"alert_id": alert.alert_id, "alert_type": alert.alert_type},
                module="sepa_alerting_system",
            )

    def _is_rate_limited(self, alert: SEPAAlert) -> bool:
        """Check if alert is rate limited"""
        rate_limit_minutes = self.notification_config.get("rate_limit_minutes", 5)
        cutoff_time = get_datetime() - timedelta(minutes=rate_limit_minutes)

        # Check recent similar alerts
        for recent_alert in self.alert_history:
            if (
                recent_alert.alert_type == alert.alert_type
                and recent_alert.timestamp >= cutoff_time
                and recent_alert.notification_sent
            ):
                return True

        return False

    def _send_notification(self, alert: SEPAAlert) -> None:
        """Send notification for an alert"""
        try:
            # Prepare notification data
            notification_data = {
                "subject": alert.title,
                "message": self._format_alert_message(alert),
                "alert_data": alert.to_dict(),
                "severity": alert.severity.value,
                "timestamp": alert.timestamp.isoformat(),
            }

            # Email notifications
            if self.notification_config.get("email_enabled", True):
                recipients = self._get_notification_recipients(alert)
                for recipient in recipients:
                    self._send_email_notification(recipient, notification_data)

            # Webhook notifications
            if self.notification_config.get("webhook_enabled", False):
                webhook_urls = self.notification_config.get("webhook_urls", [])
                for url in webhook_urls:
                    self._send_webhook_notification(url, notification_data)

            # SMS notifications (if configured)
            if self.notification_config.get("sms_enabled", False):
                # Implementation depends on SMS provider
                pass

            # Mark as notification sent
            alert.notification_sent = True

            frappe.logger().info(f"Notification sent for alert {alert.alert_id}")

        except Exception as e:
            log_error(e, context={"alert_id": alert.alert_id}, module="sepa_alerting_system")

    def _format_alert_message(self, alert: SEPAAlert) -> str:
        """Format alert message for notifications"""
        message = f"""
SEPA System Alert

Severity: {alert.severity.value.upper()}
Type: {alert.alert_type}
Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

{alert.message}

Details:
"""

        for key, value in alert.details.items():
            if key not in ["metric_name", "metric_value"]:  # Already shown in main message
                message += f"- {key}: {value}\n"

        message += f"""
Alert ID: {alert.alert_id}

This is an automated alert from the SEPA monitoring system.
Please investigate and acknowledge this alert when resolved.
"""

        return message

    def _get_notification_recipients(self, alert: SEPAAlert) -> List[str]:
        """Get notification recipients based on alert severity"""
        recipients = self.notification_config.get("default_recipients", [])

        if alert.severity in [AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY]:
            escalation_recipients = self.notification_config.get("escalation_recipients", [])
            recipients.extend(escalation_recipients)

        return list(set(recipients))  # Remove duplicates

    def _send_email_notification(self, recipient: str, notification_data: Dict[str, Any]) -> None:
        """Send email notification"""
        try:
            # Create email communication
            make(
                recipients=[recipient],
                subject=notification_data["subject"],
                content=notification_data["message"],
                send_email=True,
                communication_type="Email",
                doctype="SEPA Alert",
                name=notification_data["alert_data"]["alert_id"],
            )

        except Exception as e:
            frappe.logger().error(f"Failed to send email to {recipient}: {str(e)}")

    def _send_webhook_notification(self, url: str, notification_data: Dict[str, Any]) -> None:
        """Send webhook notification"""
        try:
            import requests

            payload = {
                "text": f"🚨 {notification_data['subject']}",
                "severity": notification_data["severity"],
                "alert": notification_data["alert_data"],
                "message": notification_data["message"],
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

        except Exception as e:
            frappe.logger().error(f"Failed to send webhook to {url}: {str(e)}")

    def _schedule_escalation(self, alert: SEPAAlert) -> None:
        """Schedule alert escalation"""
        escalation_delay = self.notification_config.get("escalation_delay_minutes", 30)
        max_escalation = self.notification_config.get("max_escalation_level", 3)

        if alert.escalation_level < max_escalation:
            # Schedule escalation (in a real system, this would use a job queue)
            self.escalation_schedules[alert.alert_id] = {
                "alert_id": alert.alert_id,
                "escalate_at": get_datetime() + timedelta(minutes=escalation_delay),
                "escalation_level": alert.escalation_level + 1,
            }

    def process_escalations(self) -> None:
        """Process scheduled escalations (called by scheduler)"""
        current_time = get_datetime()

        escalations_to_process = []
        for alert_id, escalation in self.escalation_schedules.items():
            if escalation["escalate_at"] <= current_time:
                escalations_to_process.append(alert_id)

        for alert_id in escalations_to_process:
            alert = self.active_alerts.get(alert_id)
            if alert and alert.status == AlertStatus.ACTIVE:
                self._escalate_alert(alert)

            # Remove from escalation schedule
            del self.escalation_schedules[alert_id]

    def _escalate_alert(self, alert: SEPAAlert) -> None:
        """Escalate an alert to higher notification level"""
        alert.escalation_level += 1

        escalation_message = f"""
ESCALATED ALERT - Level {alert.escalation_level}

This alert has been escalated because it has not been acknowledged.

Original Alert:
{self._format_alert_message(alert)}

Please take immediate action to resolve this issue.
"""

        # Send escalation notification
        escalation_recipients = self.notification_config.get("escalation_recipients", [])
        for recipient in escalation_recipients:
            try:
                make(
                    recipients=[recipient],
                    subject=f"🚨 ESCALATED: {alert.title}",
                    content=escalation_message,
                    send_email=True,
                    communication_type="Email",
                    doctype="SEPA Alert",
                    name=alert.alert_id,
                )
            except Exception as e:
                frappe.logger().error(f"Failed to send escalation email: {str(e)}")

        # Schedule next escalation if not at max level
        max_escalation = self.notification_config.get("max_escalation_level", 3)
        if alert.escalation_level < max_escalation:
            self._schedule_escalation(alert)

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        """
        Acknowledge an alert

        Args:
            alert_id: Alert ID to acknowledge
            acknowledged_by: User acknowledging the alert

        Returns:
            True if acknowledged successfully
        """
        alert = self.active_alerts.get(alert_id)
        if not alert:
            return False

        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = get_datetime()

        # Remove from escalation schedule
        if alert_id in self.escalation_schedules:
            del self.escalation_schedules[alert_id]

        frappe.logger().info(f"Alert {alert_id} acknowledged by {acknowledged_by}")
        return True

    def resolve_alert(self, alert_id: str, resolved_by: str) -> bool:
        """
        Resolve an alert

        Args:
            alert_id: Alert ID to resolve
            resolved_by: User resolving the alert

        Returns:
            True if resolved successfully
        """
        alert = self.active_alerts.get(alert_id)
        if not alert:
            return False

        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = get_datetime()

        # Remove from active alerts
        del self.active_alerts[alert_id]

        # Remove from escalation schedule
        if alert_id in self.escalation_schedules:
            del self.escalation_schedules[alert_id]

        frappe.logger().info(f"Alert {alert_id} resolved by {resolved_by}")
        return True

    def get_active_alerts(self, severity_filter: AlertSeverity = None) -> List[Dict[str, Any]]:
        """
        Get list of active alerts

        Args:
            severity_filter: Optional severity filter

        Returns:
            List of active alerts
        """
        alerts = []
        for alert in self.active_alerts.values():
            if alert.status == AlertStatus.ACTIVE:
                if severity_filter is None or alert.severity == severity_filter:
                    alerts.append(alert.to_dict())

        # Sort by severity and timestamp
        severity_order = {
            AlertSeverity.EMERGENCY: 0,
            AlertSeverity.CRITICAL: 1,
            AlertSeverity.WARNING: 2,
            AlertSeverity.INFO: 3,
        }

        alerts.sort(key=lambda x: (severity_order[AlertSeverity(x["severity"])], x["timestamp"]))

        return alerts

    def get_alert_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        Get alert statistics for specified period

        Args:
            days: Time period in days

        Returns:
            Alert statistics
        """
        cutoff_time = get_datetime() - timedelta(days=days)
        recent_alerts = [alert for alert in self.alert_history if alert.timestamp >= cutoff_time]

        if not recent_alerts:
            return {"message": "No alerts in the specified period", "time_period_days": days}

        # Calculate statistics
        severity_counts = defaultdict(int)
        type_counts = defaultdict(int)
        status_counts = defaultdict(int)

        for alert in recent_alerts:
            severity_counts[alert.severity.value] += 1
            type_counts[alert.alert_type] += 1
            status_counts[alert.status.value] += 1

        resolved_alerts = [a for a in recent_alerts if a.status == AlertStatus.RESOLVED]
        avg_resolution_time = 0
        if resolved_alerts:
            resolution_times = [
                (a.resolved_at - a.timestamp).total_seconds() / 60 for a in resolved_alerts if a.resolved_at
            ]
            avg_resolution_time = sum(resolution_times) / len(resolution_times) if resolution_times else 0

        return {
            "time_period_days": days,
            "total_alerts": len(recent_alerts),
            "active_alerts": len([a for a in recent_alerts if a.status == AlertStatus.ACTIVE]),
            "severity_distribution": dict(severity_counts),
            "type_distribution": dict(type_counts),
            "status_distribution": dict(status_counts),
            "avg_resolution_time_minutes": avg_resolution_time,
            "escalation_rate": len([a for a in recent_alerts if a.escalation_level > 0])
            / len(recent_alerts)
            * 100,
        }


# Global alerting system instance
_alerting_system = SEPAAlertingSystem()


# API Functions


@frappe.whitelist()
def get_active_alerts(severity: str = None) -> List[Dict[str, Any]]:
    """
    Get active alerts

    Args:
        severity: Optional severity filter

    Returns:
        List of active alerts
    """
    severity_filter = AlertSeverity(severity) if severity else None
    return _alerting_system.get_active_alerts(severity_filter)


@frappe.whitelist()
def acknowledge_alert(alert_id: str) -> Dict[str, Any]:
    """
    Acknowledge an alert

    Args:
        alert_id: Alert ID to acknowledge

    Returns:
        Success confirmation
    """
    success = _alerting_system.acknowledge_alert(alert_id, frappe.session.user)
    return {
        "success": success,
        "message": "Alert acknowledged successfully" if success else "Alert not found",
    }


@frappe.whitelist()
def resolve_alert(alert_id: str) -> Dict[str, Any]:
    """
    Resolve an alert

    Args:
        alert_id: Alert ID to resolve

    Returns:
        Success confirmation
    """
    success = _alerting_system.resolve_alert(alert_id, frappe.session.user)
    return {"success": success, "message": "Alert resolved successfully" if success else "Alert not found"}


@frappe.whitelist()
def get_alert_statistics(days: int = 7) -> Dict[str, Any]:
    """
    Get alert statistics

    Args:
        days: Time period in days

    Returns:
        Alert statistics
    """
    return _alerting_system.get_alert_statistics(int(days))


@frappe.whitelist()
def test_alert_system() -> Dict[str, Any]:
    """
    Test the alert system with sample data

    Returns:
        Test results
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only system managers can test the alert system"))

    try:
        # Test various metrics
        test_alerts = []

        # Test high memory usage
        alerts = _alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"test": True, "source": "test_alert_system"}
        )
        test_alerts.extend(alerts)

        # Test slow batch creation
        alerts = _alerting_system.check_metric(
            "batch_creation_time_ms", 45000.0, {"test": True, "source": "test_alert_system"}  # 45 seconds
        )
        test_alerts.extend(alerts)

        # Test high failure rate
        alerts = _alerting_system.check_metric(
            "operation_failure_rate_percent", 15.0, {"test": True, "source": "test_alert_system"}  # 15%
        )
        test_alerts.extend(alerts)

        return {
            "success": True,
            "alerts_generated": len(test_alerts),
            "alert_details": [alert.to_dict() for alert in test_alerts],
            "message": f"Alert system test completed. Generated {len(test_alerts)} test alerts.",
        }

    except Exception as e:
        log_error(e, context={"operation": "test_alert_system"}, module="sepa_alerting_system")
        return {"success": False, "error": str(e), "message": "Alert system test failed"}


# Helper functions for integration


def get_alerting_system() -> SEPAAlertingSystem:
    """Get the global alerting system instance"""
    return _alerting_system


def trigger_sepa_metric_check(metric_name: str, value: float, context: Dict[str, Any] = None) -> None:
    """
    Trigger metric check (to be called from SEPA operations)

    Args:
        metric_name: Name of the metric
        value: Metric value
        context: Additional context
    """
    try:
        _alerting_system.check_metric(metric_name, value, context)
    except Exception as e:
        # Don't let alerting failures break SEPA operations
        frappe.logger().error(f"Alert metric check failed: {str(e)}")


# Scheduler function for escalation processing
def process_alert_escalations():
    """Process scheduled alert escalations (called by Frappe scheduler)"""
    try:
        _alerting_system.process_escalations()
    except Exception as e:
        log_error(e, context={"operation": "process_alert_escalations"}, module="sepa_alerting_system")
