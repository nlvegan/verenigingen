#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alert Manager for Verenigingen
Handles automated alerting system for critical errors and compliance issues
"""

import json

import frappe
from frappe.utils import add_to_date, now


class AlertManager:
    """Central alert management system"""

    def __init__(self):
        self.alert_thresholds = {
            "error_rate_hourly": 10,
            "error_rate_daily": 50,
            "slow_query_threshold": 2000,  # milliseconds
            "failed_sepa_threshold": 5,
            "member_churn_daily": 10,
        }

    def check_error_rate_alert(self):
        """Check for high error rates"""
        hourly_errors = frappe.db.count("Error Log", {"creation": (">=", add_to_date(now(), hours=-1))})

        if hourly_errors > self.alert_thresholds["error_rate_hourly"]:
            self.send_alert(
                alert_type="HIGH_ERROR_RATE",
                severity="CRITICAL",
                message=f"High error rate detected: {hourly_errors} errors in the last hour",
                details={
                    "error_count": hourly_errors,
                    "threshold": self.alert_thresholds["error_rate_hourly"],
                },
            )

    def check_sepa_compliance_alert(self):
        """Check for SEPA compliance issues"""
        try:
            failed_sepa = frappe.db.count(
                "SEPA Audit Log",
                {"compliance_status": "Failed", "timestamp": (">=", add_to_date(now(), hours=-1))},
            )

            if failed_sepa > self.alert_thresholds["failed_sepa_threshold"]:
                self.send_alert(
                    alert_type="SEPA_COMPLIANCE",
                    severity="HIGH",
                    message=f"SEPA compliance issues detected: {failed_sepa} failed processes",
                    details={"failed_count": failed_sepa},
                )
        except Exception as e:
            # SEPA Audit Log DocType may not exist yet
            frappe.log_error(f"Could not check SEPA compliance: {str(e)}")

    def send_alert(self, alert_type, severity, message, details=None):
        """Send alert via email and log"""
        try:
            # Use System Alert DocType for better tracking
            from verenigingen.doctype.system_alert.system_alert import SystemAlert

            alert_doc = SystemAlert.create_alert(
                alert_type=alert_type, severity=severity, message=message, details=details or {}
            )

            if not alert_doc:
                # Fallback to Error Log
                frappe.log_error(f"Alert: {alert_type} - {message}", json.dumps(details or {}, indent=2))

            # Send email notification
            recipients = frappe.get_system_settings("alert_recipients") or frappe.conf.get(
                "alert_recipients", ["admin@dev.veganisme.net"]
            )

            frappe.sendmail(
                recipients=recipients,
                subject=f"[{severity}] {alert_type}: {message}",
                message=self.format_alert_email(alert_type, severity, message, details),
                delayed=False,
            )

            return alert_doc

        except Exception as e:
            frappe.log_error(f"Failed to send alert: {str(e)}")
            return None

    def format_alert_email(self, alert_type, severity, message, details):
        """Format alert email"""
        return f"""
        <h3>System Alert: {alert_type}</h3>
        <p><strong>Severity:</strong> {severity}</p>
        <p><strong>Message:</strong> {message}</p>
        <p><strong>Timestamp:</strong> {now()}</p>
        <p><strong>Details:</strong> {json.dumps(details, indent=2) if details else 'None'}</p>
        <p><a href="/monitoring_dashboard">View Monitoring Dashboard</a></p>
        """

    def generate_daily_report(self):
        """Generate daily monitoring report"""
        try:
            # Collect daily metrics
            daily_stats = {
                "errors_24h": frappe.db.count("Error Log", {"creation": (">=", add_to_date(now(), days=-1))}),
                "members_created": frappe.db.count(
                    "Member", {"creation": (">=", add_to_date(now(), days=-1))}
                ),
                "invoices_generated": frappe.db.count(
                    "Sales Invoice", {"creation": (">=", add_to_date(now(), days=-1)), "docstatus": 1}
                ),
            }

            # Send daily report
            recipients = frappe.conf.get("alert_recipients", ["admin@dev.veganisme.net"])
            frappe.sendmail(
                recipients=recipients,
                subject="Daily Monitoring Report",
                message=self.format_daily_report(daily_stats),
                delayed=False,
            )

        except Exception as e:
            frappe.log_error(f"Failed to generate daily report: {str(e)}")

    def format_daily_report(self, stats):
        """Format daily report email"""
        return f"""
        <h3>Daily Monitoring Report</h3>
        <p><strong>Date:</strong> {frappe.utils.today()}</p>

        <h4>System Health</h4>
        <ul>
            <li>Errors (24h): {stats.get('errors_24h', 0)}</li>
            <li>New Members: {stats.get('members_created', 0)}</li>
            <li>Invoices Generated: {stats.get('invoices_generated', 0)}</li>
        </ul>

        <p><a href="/monitoring_dashboard">View Full Dashboard</a></p>
        """

    def check_performance_alerts(self):
        """Check for performance-related alerts"""
        try:
            # Check for slow queries or high resource usage
            slow_queries = frappe.db.count(
                "Error Log",
                {"error": ("like", "%timeout%"), "creation": (">=", add_to_date(now(), hours=-1))},
            )

            if slow_queries > 5:
                self.send_alert(
                    alert_type="PERFORMANCE_DEGRADATION",
                    severity="MEDIUM",
                    message=f"Detected {slow_queries} potential slow queries in the last hour",
                    details={"slow_query_count": slow_queries},
                )

            # Check background job queue
            try:
                queued_jobs = frappe.db.count("RQ Job", {"status": "queued"})
                if queued_jobs > 20:
                    self.send_alert(
                        alert_type="HIGH_JOB_QUEUE",
                        severity="MEDIUM",
                        message=f"High background job queue: {queued_jobs} jobs pending",
                        details={"queued_jobs": queued_jobs},
                    )
            except:
                # RQ Job table may not exist
                pass

        except Exception as e:
            frappe.log_error(f"Error checking performance alerts: {str(e)}")

    def check_business_process_alerts(self):
        """Check for business process-related alerts"""
        try:
            # Check for high member churn
            member_changes = frappe.db.count(
                "Member",
                {
                    "status": ("in", ["Terminated", "Expelled"]),
                    "modified": (">=", add_to_date(now(), days=-1)),
                },
            )

            if member_changes > self.alert_thresholds["member_churn_daily"]:
                self.send_alert(
                    alert_type="HIGH_MEMBER_CHURN",
                    severity="MEDIUM",
                    message=f"High member churn detected: {member_changes} members terminated/expelled today",
                    details={"member_changes": member_changes},
                )

            # Check for stuck dues schedules
            stuck_schedules = frappe.db.count(
                "Membership Dues Schedule",
                {
                    "status": "Active",
                    "next_invoice_date": ("<=", add_to_date(now(), days=-7)),
                    "auto_generate": 1,
                },
            )

            if stuck_schedules > 5:
                self.send_alert(
                    alert_type="STUCK_DUES_SCHEDULES",
                    severity="MEDIUM",
                    message=f"Found {stuck_schedules} dues schedules that appear stuck",
                    details={"stuck_schedules": stuck_schedules},
                )

        except Exception as e:
            frappe.log_error(f"Error checking business process alerts: {str(e)}")

    def check_data_quality_alerts(self):
        """Check for data quality issues"""
        try:
            # Check for members without customer records
            members_without_customers = frappe.db.count(
                "Member", {"customer": ("is", "not set"), "status": ("!=", "Terminated")}
            )

            if members_without_customers > 10:
                self.send_alert(
                    alert_type="DATA_QUALITY_ISSUE",
                    severity="LOW",
                    message=f"Found {members_without_customers} active members without customer records",
                    details={"members_without_customers": members_without_customers},
                )

            # Check for orphaned payment entries
            orphaned_payments = frappe.db.count(
                "Payment Entry", {"reference_no": ("is", "not set"), "docstatus": 1}
            )

            if orphaned_payments > 5:
                self.send_alert(
                    alert_type="ORPHANED_PAYMENTS",
                    severity="MEDIUM",
                    message=f"Found {orphaned_payments} payment entries without proper references",
                    details={"orphaned_payments": orphaned_payments},
                )

        except Exception as e:
            frappe.log_error(f"Error checking data quality alerts: {str(e)}")

    def get_alert_statistics(self):
        """Get statistics for monitoring dashboard"""
        try:
            return {
                "total_alerts_24h": frappe.db.count(
                    "System Alert", {"creation": (">=", add_to_date(now(), days=-1))}
                ),
                "critical_alerts_24h": frappe.db.count(
                    "System Alert",
                    {"creation": (">=", add_to_date(now(), days=-1)), "severity": "CRITICAL"},
                ),
                "error_rate_1h": frappe.db.count(
                    "Error Log", {"creation": (">=", add_to_date(now(), hours=-1))}
                ),
                "performance_alerts_24h": frappe.db.count(
                    "System Alert",
                    {
                        "creation": (">=", add_to_date(now(), days=-1)),
                        "alert_type": ("like", "%PERFORMANCE%"),
                    },
                ),
            }
        except Exception as e:
            frappe.log_error(f"Error getting alert statistics: {str(e)}")
            return {}


@frappe.whitelist()
def check_critical_errors():
    """Send immediate alerts for critical errors"""
    try:
        critical_errors = frappe.db.count(
            "Error Log", {"creation": (">=", add_to_date(now(), hours=-1)), "error": ("like", "%Critical%")}
        )
        if critical_errors > 0:
            alert_manager = AlertManager()
            alert_manager.send_alert(
                alert_type="CRITICAL_ERRORS",
                severity="CRITICAL",
                message=f"Found {critical_errors} critical errors in the last hour",
                details={"critical_error_count": critical_errors},
            )
    except Exception as e:
        frappe.log_error(f"Failed to check critical errors: {str(e)}")


@frappe.whitelist()
def run_hourly_checks():
    """Run hourly alert checks"""
    try:
        alert_manager = AlertManager()
        alert_manager.check_error_rate_alert()
        alert_manager.check_sepa_compliance_alert()
        alert_manager.check_performance_alerts()
        alert_manager.check_business_process_alerts()

        frappe.logger().info("Hourly alert checks completed")
    except Exception as e:
        frappe.log_error(f"Hourly alert check failed: {str(e)}")


@frappe.whitelist()
def run_daily_checks():
    """Run daily alert checks and reports"""
    try:
        alert_manager = AlertManager()
        alert_manager.generate_daily_report()
        alert_manager.check_data_quality_alerts()

        frappe.logger().info("Daily alert checks completed")
    except Exception as e:
        frappe.log_error(f"Daily alert check failed: {str(e)}")


@frappe.whitelist()
def test_alert_system():
    """Test the alert system with a sample alert"""
    try:
        alert_manager = AlertManager()
        alert_manager.send_alert(
            alert_type="TEST_ALERT",
            severity="LOW",
            message="Test alert to verify email notifications are working",
            details={"test": True, "timestamp": now()},
        )
        return {"status": "success", "message": "Test alert sent successfully"}
    except Exception as e:
        frappe.log_error(f"Test alert failed: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_alert_statistics():
    """Get alert statistics for dashboard"""
    try:
        alert_manager = AlertManager()
        return alert_manager.get_alert_statistics()
    except Exception as e:
        frappe.log_error(f"Failed to get alert statistics: {str(e)}")
        return {}
