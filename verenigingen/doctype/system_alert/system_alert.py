#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Alert DocType

This module provides comprehensive system alerting functionality for the Verenigingen
association management system. It handles the creation, management, and lifecycle
tracking of system alerts for operational monitoring and incident management.

Key Features:
- Automated alert lifecycle management with status tracking
- Severity-based alert categorization and prioritization
- User acknowledgment and resolution tracking with timestamps
- Comprehensive alert querying and dashboard integration
- API endpoints for frontend alert management interfaces

Business Context:
System alerts are critical for maintaining operational awareness in the association
management system. They provide real-time notification capabilities for:
- System performance issues and resource constraints
- SEPA payment processing failures and compliance exceptions
- Member data integrity issues and validation failures
- Integration failures with external systems (eBoekhouden, banking)
- Security incidents and audit compliance violations

Architecture:
This DocType integrates with:
- System monitoring and performance tracking components
- SEPA processing systems for payment-related alerts
- Member management for data integrity alerts
- API integration systems for external service monitoring
- Dashboard and notification systems for user interfaces

Data Model:
- Alert identification with timestamp and categorization
- Severity levels (INFO, WARNING, ERROR, CRITICAL) for prioritization
- Status lifecycle (Active, Acknowledged, Resolved) with user attribution
- Message content with structured details for context
- Audit trail with acknowledgment and resolution tracking

Operational Workflow:
1. Alert Creation: System components create alerts for significant events
2. Active Monitoring: Dashboard displays active alerts by severity
3. Acknowledgment: Operations team acknowledges awareness of issues
4. Resolution: Team resolves underlying issues and closes alerts
5. Audit Trail: Complete history maintained for operational review

Integration Points:
- Performance monitoring systems for resource alerts
- SEPA processing for payment-related notifications
- Member data validation for integrity alerts
- External API monitoring for service availability
- Security systems for compliance and audit alerts

Author: Development Team
Date: 2025-07-25
Version: 1.0
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SystemAlert(Document):
    """
    System alert management with comprehensive lifecycle tracking and operational workflow.

    This DocType provides centralized alert management for system monitoring, operational
    awareness, and incident response within the Verenigingen association management system.

    Key Responsibilities:
    - Manage alert lifecycle from creation to resolution
    - Track user acknowledgment and resolution activities
    - Provide severity-based categorization and prioritization
    - Support dashboard integration and operational reporting
    - Maintain complete audit trail for operational review

    Business Process Integration:
    - Integrates with system monitoring for automated alert creation
    - Supports operational dashboards for real-time awareness
    - Provides API endpoints for frontend alert management
    - Coordinates with notification systems for user alerts
    - Supports incident response and resolution workflows

    Alert Lifecycle:
    1. Active: Alert created by system or user, requires attention
    2. Acknowledged: Operations team aware of issue, investigating
    3. Resolved: Underlying issue resolved, alert closed

    Usage Example:
        ```python
        # Create system alert
        alert = SystemAlert.create_alert(
            alert_type="Performance",
            severity="WARNING",
            message="High database query volume detected",
            details={"query_count": 1500, "threshold": 1000}
        )

        # Acknowledge alert
        alert.acknowledge_alert(user="operations@example.com")

        # Resolve alert
        alert.resolve_alert(user="operations@example.com")
        ```

    Security Model:
    - Role-based access control for alert management
    - Audit trail for all status changes and user actions
    - API endpoints with permission validation
    - Secure handling of sensitive alert details

    Performance Considerations:
    - Indexed on status and timestamp for efficient querying
    - Optimized alert summary calculations for dashboards
    - Efficient bulk operations for alert management
    - Minimal overhead for high-volume alert creation
    """

    def validate(self):
        """Validate alert before saving"""
        if not self.timestamp:
            self.timestamp = now()

        # Auto-set acknowledgment timestamp when status changes
        if self.has_value_changed("status"):
            if self.status == "Acknowledged" and not self.acknowledged_at:
                self.acknowledged_at = now()
                if not self.acknowledged_by:
                    self.acknowledged_by = frappe.session.user

            elif self.status == "Resolved" and not self.resolved_at:
                self.resolved_at = now()
                if not self.resolved_by:
                    self.resolved_by = frappe.session.user

    @staticmethod
    def create_alert(alert_type, severity, message, details=None):
        """Create a new system alert"""
        try:
            alert = frappe.new_doc("System Alert")
            alert.update(
                {
                    "alert_type": alert_type,
                    "severity": severity,
                    "message": message,
                    "details": details or {},
                    "status": "Active",
                    "timestamp": now(),
                }
            )
            alert.insert()
            return alert
        except Exception as e:
            frappe.log_error(f"Failed to create system alert: {str(e)}")
            return None

    @staticmethod
    def get_active_alerts():
        """Get all active alerts"""
        return frappe.get_all(
            "System Alert",
            filters={"status": "Active"},
            fields=["name", "alert_type", "severity", "message", "timestamp"],
            order_by="timestamp DESC",
        )

    @staticmethod
    def get_recent_alerts(hours=24):
        """Get recent alerts within specified hours"""
        from frappe.utils import add_to_date

        return frappe.get_all(
            "System Alert",
            filters={"timestamp": (">=", add_to_date(now(), hours=-hours))},
            fields=["name", "alert_type", "severity", "message", "status", "timestamp"],
            order_by="timestamp DESC",
        )

    def acknowledge_alert(self, user=None):
        """Acknowledge the alert"""
        self.status = "Acknowledged"
        self.acknowledged_by = user or frappe.session.user
        self.acknowledged_at = now()
        self.save()

    def resolve_alert(self, user=None):
        """Resolve the alert"""
        self.status = "Resolved"
        self.resolved_by = user or frappe.session.user
        self.resolved_at = now()
        self.save()


@frappe.whitelist()
def acknowledge_alert(alert_name):
    """API endpoint to acknowledge an alert"""
    try:
        alert = frappe.get_doc("System Alert", alert_name)
        alert.acknowledge_alert()
        return {"status": "success", "message": "Alert acknowledged"}
    except Exception as e:
        frappe.log_error(f"Failed to acknowledge alert {alert_name}: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def resolve_alert(alert_name):
    """API endpoint to resolve an alert"""
    try:
        alert = frappe.get_doc("System Alert", alert_name)
        alert.resolve_alert()
        return {"status": "success", "message": "Alert resolved"}
    except Exception as e:
        frappe.log_error(f"Failed to resolve alert {alert_name}: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_alert_summary():
    """Get alert summary for dashboard"""
    try:
        summary = {
            "active": frappe.db.count("System Alert", {"status": "Active"}),
            "acknowledged": frappe.db.count("System Alert", {"status": "Acknowledged"}),
            "resolved_today": frappe.db.count(
                "System Alert", {"status": "Resolved", "resolved_at": (">=", frappe.utils.today())}
            ),
            "critical_active": frappe.db.count("System Alert", {"status": "Active", "severity": "CRITICAL"}),
        }
        return summary
    except Exception as e:
        frappe.log_error(f"Failed to get alert summary: {str(e)}")
        return {"active": 0, "acknowledged": 0, "resolved_today": 0, "critical_active": 0}
