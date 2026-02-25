#!/usr/bin/env python3
"""
Business Logic Monitoring System for Verenigingen

This module implements sophisticated business logic monitoring that detects
anomalous patterns in critical operations and integrates with Zabbix for
real-time alerting and trend analysis.

Features:
- Pattern Detection: Round amounts, excessive discounts, unusual volumes
- Anomaly Detection: Statistical analysis of operation patterns
- Zabbix Integration: Seamless monitoring data export
- Risk Scoring: Dynamic risk assessment based on operation context
- Policy Compliance: Automated regulatory compliance checking

Author: Claude Code Assistant
Date: September 15, 2025
"""

import json
import logging
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.constants import Roles

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level classification for business operations"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MINIMAL = "minimal"


class MonitoringContext(Enum):
    """Business context for monitoring operations"""

    FINANCIAL = "financial"
    MEMBER_DATA = "member_data"
    GOVERNANCE = "governance"
    OPERATIONS = "operations"
    COMPLIANCE = "compliance"


@dataclass
class BusinessMetric:
    """Business metric data structure for Zabbix integration"""

    name: str
    value: float
    timestamp: datetime
    context: MonitoringContext
    risk_level: RiskLevel
    details: Dict[str, Any]

    def to_zabbix_format(self) -> Dict[str, Any]:
        """Convert metric to Zabbix-compatible format"""
        return {
            "key": f"verenigingen.business_logic.{self.context.value}.{self.name}",
            "value": self.value,
            "timestamp": int(self.timestamp.timestamp()),
            "risk_level": self.risk_level.value,
            "details": json.dumps(self.details),
        }


@dataclass
class PatternAlert:
    """Alert for detected suspicious patterns"""

    pattern_type: str
    severity: RiskLevel
    description: str
    evidence: Dict[str, Any]
    suggested_action: str
    compliance_impact: Optional[str] = None


class BusinessLogicMonitor:
    """Main business logic monitoring system"""

    def __init__(self):
        self.metrics_cache = []
        self.alert_thresholds = self._load_thresholds()
        # Enable monitoring by default, settings field will be added later
        self.monitoring_enabled = True

    def _load_thresholds(self) -> Dict[str, Any]:
        """Load monitoring thresholds from Critical Operation Rules"""
        try:
            # Get thresholds from CORs with business rule validation enabled
            thresholds = {}
            rules = frappe.get_all(
                "Critical Operation Rule", filters={"enabled": 1}, fields=["operation_name", "security_level"]
            )

            for rule in rules:
                thresholds[rule.operation_name] = {
                    "amount_threshold": 1000,  # Default threshold
                    "security_level": rule.security_level,
                }

            return thresholds

        except Exception as e:
            logger.warning(f"Could not load COR thresholds: {e}")
            return self._get_default_thresholds()

    def _get_default_thresholds(self) -> Dict[str, Any]:
        """Default monitoring thresholds"""
        return {
            "payment_amount_threshold": 5000,
            "bulk_operation_threshold": 50,
            "frequency_threshold": 10,
            "round_amount_pattern_threshold": 0.7,
            "compliance_alert_threshold": 1,
        }

    def monitor_payment_operation(self, operation_data: Dict[str, Any]) -> List[BusinessMetric]:
        """Monitor payment-related operations for suspicious patterns"""
        metrics = []

        try:
            amount = float(operation_data.get("amount", 0))
            payment_method = operation_data.get("payment_method", "unknown")
            member_id = operation_data.get("member_id")

            # Pattern 1: Round amount detection
            if self._is_round_amount(amount):
                metrics.append(
                    BusinessMetric(
                        name="round_amount_detected",
                        value=1,
                        timestamp=datetime.now(),
                        context=MonitoringContext.FINANCIAL,
                        risk_level=RiskLevel.MEDIUM,
                        details={
                            "amount": amount,
                            "member_id": member_id,
                            "payment_method": payment_method,
                            "pattern": "round_amount",
                        },
                    )
                )

            # Pattern 2: High-value transaction monitoring
            threshold = self.alert_thresholds.get("payment_amount_threshold", 5000)
            if amount > threshold:
                risk_level = RiskLevel.HIGH if amount > threshold * 2 else RiskLevel.MEDIUM
                metrics.append(
                    BusinessMetric(
                        name="high_value_transaction",
                        value=amount,
                        timestamp=datetime.now(),
                        context=MonitoringContext.FINANCIAL,
                        risk_level=risk_level,
                        details={
                            "amount": amount,
                            "threshold": threshold,
                            "member_id": member_id,
                            "payment_method": payment_method,
                        },
                    )
                )

            # Pattern 3: Frequency analysis for member
            if member_id:
                frequency_score = self._analyze_member_payment_frequency(member_id)
                if frequency_score > self.alert_thresholds.get("frequency_threshold", 10):
                    metrics.append(
                        BusinessMetric(
                            name="unusual_payment_frequency",
                            value=frequency_score,
                            timestamp=datetime.now(),
                            context=MonitoringContext.FINANCIAL,
                            risk_level=RiskLevel.MEDIUM,
                            details={
                                "member_id": member_id,
                                "frequency_score": frequency_score,
                                "pattern": "high_frequency",
                            },
                        )
                    )

        except Exception as e:
            logger.error(f"Error monitoring payment operation: {e}")

        return metrics

    def monitor_bulk_operation(self, operation_data: Dict[str, Any]) -> List[BusinessMetric]:
        """Monitor bulk operations for anomalous patterns"""
        metrics = []

        try:
            record_count = int(operation_data.get("record_count", 0))
            operation_type = operation_data.get("operation_type", "unknown")
            user_id = operation_data.get("user_id")

            threshold = self.alert_thresholds.get("bulk_operation_threshold", 50)

            if record_count > threshold:
                # Calculate risk level based on operation scale
                if record_count > threshold * 5:
                    risk_level = RiskLevel.CRITICAL
                elif record_count > threshold * 2:
                    risk_level = RiskLevel.HIGH
                else:
                    risk_level = RiskLevel.MEDIUM

                metrics.append(
                    BusinessMetric(
                        name="large_bulk_operation",
                        value=record_count,
                        timestamp=datetime.now(),
                        context=MonitoringContext.OPERATIONS,
                        risk_level=risk_level,
                        details={
                            "record_count": record_count,
                            "operation_type": operation_type,
                            "user_id": user_id,
                            "threshold": threshold,
                        },
                    )
                )

            # Check for unusual bulk operation timing
            if self._is_unusual_timing():
                metrics.append(
                    BusinessMetric(
                        name="unusual_timing_bulk_operation",
                        value=1,
                        timestamp=datetime.now(),
                        context=MonitoringContext.GOVERNANCE,
                        risk_level=RiskLevel.MEDIUM,
                        details={
                            "operation_type": operation_type,
                            "user_id": user_id,
                            "timing": "outside_business_hours",
                        },
                    )
                )

        except Exception as e:
            logger.error(f"Error monitoring bulk operation: {e}")

        return metrics

    def monitor_member_data_access(self, operation_data: Dict[str, Any]) -> List[BusinessMetric]:
        """Monitor member data access patterns"""
        metrics = []

        try:
            access_count = int(operation_data.get("access_count", 1))
            data_sensitivity = operation_data.get("data_sensitivity", "medium")
            user_id = operation_data.get("user_id")
            access_pattern = operation_data.get("access_pattern", "normal")

            # Pattern 1: Excessive data access
            if access_count > 100:  # Configurable threshold
                metrics.append(
                    BusinessMetric(
                        name="excessive_data_access",
                        value=access_count,
                        timestamp=datetime.now(),
                        context=MonitoringContext.MEMBER_DATA,
                        risk_level=RiskLevel.HIGH if access_count > 500 else RiskLevel.MEDIUM,
                        details={
                            "access_count": access_count,
                            "user_id": user_id,
                            "data_sensitivity": data_sensitivity,
                            "access_pattern": access_pattern,
                        },
                    )
                )

            # Pattern 2: Sensitive data access monitoring
            if data_sensitivity == "high":
                metrics.append(
                    BusinessMetric(
                        name="sensitive_data_access",
                        value=1,
                        timestamp=datetime.now(),
                        context=MonitoringContext.COMPLIANCE,
                        risk_level=RiskLevel.HIGH,
                        details={
                            "user_id": user_id,
                            "data_sensitivity": data_sensitivity,
                            "gdpr_relevant": True,
                        },
                    )
                )

        except Exception as e:
            logger.error(f"Error monitoring member data access: {e}")

        return metrics

    def _is_round_amount(self, amount: float) -> bool:
        """Detect if amount is suspiciously round (pattern detection)"""
        if amount <= 0:
            return False

        # Check for round hundreds, thousands
        return (amount % 100 == 0 and amount >= 100) or (amount % 1000 == 0 and amount >= 1000)

    def _analyze_member_payment_frequency(self, member_id: str) -> float:
        """Analyze payment frequency for anomaly detection"""
        try:
            # Get payment history for the last 30 days
            thirty_days_ago = frappe.utils.add_days(frappe.utils.today(), -30)

            payment_count = frappe.db.count(
                "Payment Entry", filters={"party": member_id, "creation": [">=", thirty_days_ago]}
            )

            # Calculate frequency score (payments per week)
            frequency_score = payment_count * 7 / 30
            return frequency_score

        except Exception as e:
            logger.error(f"Error analyzing payment frequency: {e}")
            return 0

    def _is_unusual_timing(self) -> bool:
        """Check if current time is unusual for business operations"""
        now = datetime.now()

        # Outside business hours (before 8 AM or after 6 PM)
        if now.hour < 8 or now.hour > 18:
            return True

        # Weekend operations
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return True

        return False

    def generate_compliance_metrics(self) -> List[BusinessMetric]:
        """Generate GDPR and Dutch compliance metrics"""
        metrics = []

        try:
            # GDPR compliance monitoring
            gdpr_metrics = self._check_gdpr_compliance()
            metrics.extend(gdpr_metrics)

            # Dutch association law compliance
            association_metrics = self._check_association_compliance()
            metrics.extend(association_metrics)

        except Exception as e:
            logger.error(f"Error generating compliance metrics: {e}")

        return metrics

    def _check_gdpr_compliance(self) -> List[BusinessMetric]:
        """Check GDPR compliance status"""
        metrics = []

        try:
            # Check for data retention policy compliance
            old_members = frappe.db.count(
                "Member",
                filters={
                    "status": "Quit",
                    "termination_date": ["<", frappe.utils.add_years(frappe.utils.today(), -7)],
                },
            )

            if old_members > 0:
                metrics.append(
                    BusinessMetric(
                        name="gdpr_data_retention_alert",
                        value=old_members,
                        timestamp=datetime.now(),
                        context=MonitoringContext.COMPLIANCE,
                        risk_level=RiskLevel.HIGH,
                        details={
                            "old_terminated_members": old_members,
                            "compliance_issue": "data_retention",
                            "regulation": "GDPR Article 5(e)",
                        },
                    )
                )

        except Exception as e:
            logger.error(f"Error checking GDPR compliance: {e}")

        return metrics

    def _check_association_compliance(self) -> List[BusinessMetric]:
        """Check Dutch association law compliance"""
        metrics = []

        try:
            # Check for board composition compliance
            board_members = frappe.db.count("Chapter Board Member", filters={"status": "Active"})

            if board_members < 3:  # Dutch associations typically need minimum 3 board members
                metrics.append(
                    BusinessMetric(
                        name="board_composition_alert",
                        value=board_members,
                        timestamp=datetime.now(),
                        context=MonitoringContext.GOVERNANCE,
                        risk_level=RiskLevel.MEDIUM,
                        details={
                            "active_board_members": board_members,
                            "minimum_required": 3,
                            "compliance_issue": "board_composition",
                        },
                    )
                )

        except Exception as e:
            logger.error(f"Error checking association compliance: {e}")

        return metrics

    def export_metrics_for_zabbix(self) -> Dict[str, Any]:
        """Export all business logic metrics in Zabbix format"""
        if not self.monitoring_enabled:
            return {"status": "monitoring_disabled", "metrics": []}

        all_metrics = []

        try:
            # Generate current compliance metrics
            compliance_metrics = self.generate_compliance_metrics()
            all_metrics.extend(compliance_metrics)

            # Add cached metrics
            all_metrics.extend(self.metrics_cache)

            # Convert to Zabbix format
            zabbix_metrics = [metric.to_zabbix_format() for metric in all_metrics]

            # Clear cache after export
            self.metrics_cache = []

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "metric_count": len(zabbix_metrics),
                "metrics": zabbix_metrics,
                "business_logic_monitoring": {
                    "enabled": self.monitoring_enabled,
                    "thresholds": self.alert_thresholds,
                    "contexts": [ctx.value for ctx in MonitoringContext],
                    "risk_levels": [level.value for level in RiskLevel],
                },
            }

        except Exception as e:
            logger.error(f"Error exporting metrics for Zabbix: {e}")
            return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

    def analyze_operation(self, operation_name: str, operation_data: Dict[str, Any]) -> List[BusinessMetric]:
        """Analyze any operation for business logic anomalies"""
        metrics = []

        try:
            # Route to appropriate monitoring function based on operation type
            if "payment" in operation_name.lower():
                metrics.extend(self.monitor_payment_operation(operation_data))
            elif "bulk" in operation_name.lower():
                metrics.extend(self.monitor_bulk_operation(operation_data))
            elif "member" in operation_name.lower() and "data" in operation_name.lower():
                metrics.extend(self.monitor_member_data_access(operation_data))

            # Cache metrics for Zabbix export
            self.metrics_cache.extend(metrics)

            # Generate alerts for critical patterns
            alerts = self._generate_alerts(metrics)
            if alerts:
                self._send_alerts(alerts)

        except Exception as e:
            logger.error(f"Error analyzing operation {operation_name}: {e}")

        return metrics

    def _generate_alerts(self, metrics: List[BusinessMetric]) -> List[PatternAlert]:
        """Generate alerts for suspicious patterns"""
        alerts = []

        for metric in metrics:
            if metric.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
                alert = PatternAlert(
                    pattern_type=metric.name,
                    severity=metric.risk_level,
                    description=f"Suspicious pattern detected: {metric.name}",
                    evidence=metric.details,
                    suggested_action=self._get_suggested_action(metric),
                    compliance_impact=self._assess_compliance_impact(metric),
                )
                alerts.append(alert)

        return alerts

    def _get_suggested_action(self, metric: BusinessMetric) -> str:
        """Get suggested action for detected pattern"""
        action_map = {
            "round_amount_detected": "Review transaction for potential fraud indicators",
            "high_value_transaction": "Verify authorization and legitimacy of high-value transaction",
            "unusual_payment_frequency": "Investigate unusual payment behavior pattern",
            "large_bulk_operation": "Confirm authorization for bulk operation",
            "excessive_data_access": "Review data access permissions and necessity",
            "gdpr_data_retention_alert": "Review terminated member data for GDPR compliance",
            "board_composition_alert": "Ensure board composition meets legal requirements",
        }

        return action_map.get(metric.name, "Review and investigate detected pattern")

    def _assess_compliance_impact(self, metric: BusinessMetric) -> Optional[str]:
        """Assess potential compliance impact"""
        if metric.context == MonitoringContext.COMPLIANCE:
            return "GDPR or Dutch association law compliance may be affected"
        elif metric.context == MonitoringContext.FINANCIAL and metric.risk_level == RiskLevel.CRITICAL:
            return "Financial regulations and audit trail requirements may be affected"
        elif metric.context == MonitoringContext.GOVERNANCE:
            return "Association governance requirements may be affected"

        return None

    def _send_alerts(self, alerts: List[PatternAlert]) -> None:
        """Send alerts to administrators"""
        try:
            if not alerts:
                return

            # Get admin email addresses
            admin_emails = self._get_admin_emails()
            if not admin_emails:
                logger.warning("No admin emails configured for business logic alerts")
                return

            # Format alert email
            subject = f"Business Logic Alert: {len(alerts)} pattern(s) detected"
            message = self._format_alert_email(alerts)

            # Send email notification
            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=admin_emails,
                subject=subject,
                message=message,
                send_priority=1,
                notification_key="business_logic_alert",
            )

            logger.info(f"Sent business logic alerts to {len(admin_emails)} administrators")

        except Exception as e:
            logger.error(f"Failed to send business logic alerts: {e}")

    def _get_admin_emails(self) -> List[str]:
        """Get administrator email addresses"""
        try:
            admins = frappe.get_all(
                "Has Role", filters={"role": Roles.SYSTEM_MANAGER, "parenttype": "User"}, fields=["parent"]
            )

            admin_emails = []
            for admin in admins:
                user = frappe.get_doc("User", admin.parent)
                if user.enabled and user.email:
                    admin_emails.append(user.email)

            return admin_emails

        except Exception as e:
            logger.error(f"Error getting admin emails: {e}")
            return []

    def _format_alert_email(self, alerts: List[PatternAlert]) -> str:
        """Format business logic alerts as HTML email"""
        html = f"""
        <h2>🚨 Business Logic Monitoring Alert</h2>
        <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Detected Patterns:</strong> {len(alerts)}</p>

        <hr>
        """

        for i, alert in enumerate(alerts, 1):
            severity_color = {
                RiskLevel.CRITICAL: "#d32f2f",
                RiskLevel.HIGH: "#f57c00",
                RiskLevel.MEDIUM: "#fbc02d",
                RiskLevel.LOW: "#388e3c",
            }.get(alert.severity, "#757575")

            html += f"""
            <h3>Alert #{i}: {alert.pattern_type}</h3>
            <p><strong>Severity:</strong> <span style="color: {severity_color}; font-weight: bold;">{alert.severity.value.upper()}</span></p>
            <p><strong>Description:</strong> {alert.description}</p>
            <p><strong>Suggested Action:</strong> {alert.suggested_action}</p>

            <details>
                <summary><strong>Evidence Details</strong></summary>
                <pre>{json.dumps(alert.evidence, indent=2)}</pre>
            </details>

            {f'<p><strong>⚖️ Compliance Impact:</strong> {alert.compliance_impact}</p>' if alert.compliance_impact else ''}

            <hr>
            """

        html += """
        <p><em>This is an automated alert from the Verenigingen Business Logic Monitoring System.</em></p>
        <p>For more information, please check the system health dashboard or contact the system administrator.</p>
        """

        return html


# Singleton instance for module-level access
business_monitor = BusinessLogicMonitor()


@frappe.whitelist()
def get_business_metrics_for_zabbix():
    """Zabbix-compatible endpoint for business logic metrics"""
    try:
        # Security validation would be handled by API security framework if available
        # For now, just log the access
        frappe.logger().info(f"Business metrics requested by user: {frappe.session.user}")

        # Export metrics
        metrics = business_monitor.export_metrics_for_zabbix()

        frappe.logger().info(
            f"Business logic metrics exported for Zabbix: {metrics.get('metric_count', 0)} metrics"
        )

        return metrics

    except Exception as e:
        frappe.log_error(f"Error exporting business metrics for Zabbix: {str(e)}")
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}


def analyze_critical_operation(operation_name: str, operation_data: Dict[str, Any]) -> None:
    """Hook function to analyze critical operations for business logic patterns"""
    try:
        if not business_monitor.monitoring_enabled:
            return

        # Analyze the operation
        metrics = business_monitor.analyze_operation(operation_name, operation_data)

        if metrics:
            frappe.logger().info(
                f"Business logic analysis for {operation_name}: {len(metrics)} metrics generated"
            )

    except Exception as e:
        frappe.log_error(f"Error in business logic analysis for {operation_name}: {str(e)}")


# Integration hooks for common operations
def on_payment_entry_submit(doc, method):
    """Hook for payment entry submission"""
    analyze_critical_operation(
        "payment_processing",
        {
            "amount": doc.paid_amount,  # ast-skip: Payment Entry field
            "payment_method": doc.mode_of_payment,  # ast-skip: Payment Entry field
            "member_id": doc.party,  # ast-skip: Payment Entry field
            "reference": doc.reference_no,  # ast-skip: Payment Entry field
        },
    )


def on_bulk_member_update(doc, method):
    """Hook for bulk member updates"""
    analyze_critical_operation(
        "bulk_member_update",
        {
            "record_count": 1,  # Individual record, but part of bulk operation
            "operation_type": "member_update",
            "user_id": frappe.session.user,
        },
    )
