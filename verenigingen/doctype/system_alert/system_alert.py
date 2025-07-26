#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Alert DocType
Handles system alerts with acknowledgment and resolution tracking
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SystemAlert(Document):
    """System Alert document with lifecycle management"""

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
            fields=["name", "alert_type", "compliance_status", "message", "status", "timestamp"],
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
