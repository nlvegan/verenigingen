#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix Integration for Frappe/Verenigingen
Sends metrics and alerts between Zabbix and Frappe
"""

import json
from datetime import datetime, timedelta

import frappe
import requests
from frappe.utils import get_datetime, now_datetime


class ZabbixIntegration:
    """Integrate Zabbix monitoring with Frappe"""

    def __init__(self):
        self.zabbix_url = frappe.conf.get("zabbix_url", "http://zabbix.example.com")
        self.zabbix_user = frappe.conf.get("zabbix_user")
        self.zabbix_password = frappe.conf.get("zabbix_password")
        self.zabbix_token = None

    def authenticate(self):
        """Authenticate with Zabbix API"""
        payload = {
            "jsonrpc": "2.0",
            "method": "user.login",
            "params": {"user": self.zabbix_user, "password": self.zabbix_password},
            "id": 1,
        }

        response = requests.post(
            f"{self.zabbix_url}/api_jsonrpc.php", json=payload, headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            self.zabbix_token = response.json().get("result")
            return True
        return False

    def send_metric_to_zabbix(self, host, key, value):
        """Send metric to Zabbix using sender protocol"""
        # This would typically use zabbix_sender command or API
        data = {
            "request": "sender data",
            "data": [
                {"host": host, "key": key, "value": str(value), "clock": int(datetime.now().timestamp())}
            ],
        }

        # Send to Zabbix server (port 10051)
        # In production, use proper Zabbix sender protocol
        return data

    def create_zabbix_trigger(self, name, expression, severity=2):
        """Create trigger in Zabbix"""
        if not self.zabbix_token:
            self.authenticate()

        payload = {
            "jsonrpc": "2.0",
            "method": "trigger.create",
            "params": {"description": name, "expression": expression, "priority": severity},
            "auth": self.zabbix_token,
            "id": 1,
        }

        response = requests.post(f"{self.zabbix_url}/api_jsonrpc.php", json=payload)

        return response.json()


@frappe.whitelist()
def send_frappe_metrics_to_zabbix():
    """Send Frappe metrics to Zabbix monitoring"""
    zabbix = ZabbixIntegration()

    metrics = {
        # System metrics
        "frappe.members.active": frappe.db.count("Member", {"status": "Active"}),
        "frappe.members.total": frappe.db.count("Member"),
        "frappe.volunteers.active": frappe.db.count("Volunteer", {"is_active": 1}),
        # Financial metrics
        "frappe.donations.today": float(
            frappe.db.sql(
                """
            SELECT COALESCE(SUM(grand_total), 0)
            FROM `tabDonation`
            WHERE DATE(creation) = CURDATE()
        """
            )[0][0]
        ),
        # Invoice generation tracking
        "frappe.invoices.sales_today": get_sales_invoices_today(),
        "frappe.invoices.subscription_today": get_subscription_invoices_today(),
        "frappe.invoices.total_today": get_total_invoices_today(),
        # Subscription processing health
        "frappe.subscriptions.active": frappe.db.count("Subscription", {"status": "Active"}),
        "frappe.subscriptions.processed_today": get_subscriptions_processed_today(),
        "frappe.scheduler.last_subscription_run": get_last_subscription_processing(),
        # Performance metrics
        "frappe.error_logs.count": frappe.db.count(
            "Error Log", {"creation": [">=", get_datetime() - timedelta(hours=1)]}
        ),
        # Queue metrics
        "frappe.queue.pending": get_queue_length(),
        "frappe.queue.stuck_jobs": get_stuck_jobs_count(),
        # Custom business metrics
        "frappe.member.churn_rate": calculate_churn_rate(),
        "frappe.volunteer.engagement": calculate_volunteer_engagement(),
    }

    # Send each metric to Zabbix
    host = frappe.conf.get("zabbix_host_name", "frappe-production")

    for key, value in metrics.items():
        zabbix.send_metric_to_zabbix(host, key, value)

    return {"status": "success", "metrics_sent": len(metrics)}


@frappe.whitelist(allow_guest=True)
def zabbix_webhook_receiver():
    """Receive alerts from Zabbix and create issues in Frappe"""
    try:
        # Get webhook data
        data = frappe.request.get_json()

        # Parse Zabbix alert
        alert = {
            "trigger": data.get("trigger", {}).get("name"),
            "severity": data.get("trigger", {}).get("severity"),
            "host": data.get("host", {}).get("name"),
            "timestamp": data.get("timestamp"),
            "message": data.get("message"),
        }

        # Create issue in Frappe based on severity
        if alert["severity"] in ["High", "Disaster"]:
            create_critical_alert(alert)
        else:
            create_monitoring_log(alert)

        return {"status": "success", "message": "Alert received"}

    except Exception as e:
        frappe.log_error(f"Zabbix webhook error: {e}")
        return {"status": "error", "message": str(e)}


def create_critical_alert(alert):
    """Create critical alert in Frappe"""
    # Create Issue
    issue = frappe.new_doc("Issue")
    issue.subject = f"[Zabbix Alert] {alert['trigger']}"
    issue.description = f"""
Zabbix has detected a critical issue:

**Trigger:** {alert['trigger']}
**Host:** {alert['host']}
**Severity:** {alert['severity']}
**Time:** {alert['timestamp']}

**Message:**
{alert['message']}

Please investigate immediately.
"""
    issue.priority = "High"
    issue.issue_type = "System Alert"
    issue.insert(ignore_permissions=True)

    # Send email notification
    frappe.sendmail(
        recipients=frappe.conf.get("alert_recipients", ["admin@example.com"]),
        subject=issue.subject,
        message=issue.description,
        priority=1,
    )

    # Create Analytics Alert Log
    if frappe.db.exists("DocType", "Analytics Alert Log"):
        alert_log = frappe.new_doc("Analytics Alert Log")
        alert_log.alert_name = alert["trigger"]
        alert_log.alert_type = "External - Zabbix"
        alert_log.severity = alert["severity"]
        alert_log.details = json.dumps(alert)
        alert_log.insert(ignore_permissions=True)


def create_monitoring_log(alert):
    """Log non-critical alerts"""
    frappe.log_error(title=f"Zabbix Alert: {alert['trigger']}", message=json.dumps(alert, indent=2))


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_metrics_for_zabbix():
    """API endpoint for Zabbix to pull metrics"""
    # This endpoint can be called by Zabbix HTTP agent

    try:
        # Check if API key authentication is provided (only when in request context)
        auth_header = None
        try:
            auth_header = frappe.get_request_header("Authorization")
        except RuntimeError:
            # No request context (e.g., called via bench execute), skip auth check
            pass

        if auth_header and auth_header.startswith("token "):
            # Validate API token if provided
            try:
                api_key, api_secret = auth_header.replace("token ", "").split(":")
                user = frappe.db.get_value("User", {"api_key": api_key}, ["name", "enabled"])
                if not user or not user[1]:  # Check if user exists and is enabled
                    return {"error": "Invalid API credentials", "status": "unauthorized"}
            except Exception as e:
                return {"error": f"Invalid API credentials format: {str(e)}", "status": "unauthorized"}
        # If no auth header or no request context, proceed anyway

        metrics = {
            "timestamp": now_datetime().isoformat(),
            "metrics": {
                "active_members": frappe.db.count("Member", {"status": "Active"}),
                "pending_expenses": frappe.db.count("Volunteer Expense", {"status": "Pending"}),
                "daily_donations": get_daily_donations(),
                "system_health": get_system_health_score(),
                "error_rate": get_error_rate(),
                "response_time": get_average_response_time(),
                "job_queue_size": get_queue_length(),
                "db_connections": get_db_connections(),
                # New subscription and invoice tracking metrics
                "active_subscriptions": frappe.db.count("Subscription", {"status": "Active", "docstatus": 1}),
                "sales_invoices_today": get_sales_invoices_today(),
                "subscription_invoices_today": get_subscription_invoices_today(),
                "total_invoices_today": get_total_invoices_today(),
                "subscriptions_processed_today": get_subscriptions_processed_today(),
                "last_subscription_run": get_last_subscription_processing(),
                "stuck_jobs": get_stuck_jobs_count(),
            },
        }

        frappe.response["content_type"] = "application/json"
        return metrics

    except Exception as e:
        frappe.log_error(f"Zabbix metrics error: {str(e)}")
        return {"error": "Internal server error", "message": str(e), "timestamp": now_datetime().isoformat()}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def health_check():
    """Health check endpoint for Zabbix that evaluates actual system health"""
    try:
        health_score = get_system_health_score()
        status = "healthy" if health_score >= 70 else "unhealthy"

        # Get details about what's affecting health
        details = get_health_details()

        return {
            "status": status,
            "score": health_score,
            "details": details,
            "timestamp": now_datetime().isoformat(),
        }
    except Exception as e:
        frappe.log_error(f"Health check error: {str(e)}")
        return {"status": "unhealthy", "score": 0, "error": str(e), "timestamp": now_datetime().isoformat()}


def get_queue_length():
    """Get background job queue length"""
    try:
        from frappe.utils.background_jobs import get_queue_length

        return get_queue_length()
    except:
        return 0


def calculate_churn_rate():
    """Calculate member churn rate"""
    # Last 30 days churn
    churned = frappe.db.count(
        "Member", {"status": "Terminated", "modified": [">=", get_datetime() - timedelta(days=30)]}
    )

    total = frappe.db.count("Member", {"status": "Active"})

    if total > 0:
        return round((churned / total) * 100, 2)
    return 0


def calculate_volunteer_engagement():
    """Calculate volunteer engagement score"""
    try:
        # Check if volunteer tables exist
        if not frappe.db.exists("DocType", "Volunteer"):
            return 0

        total_volunteers = frappe.db.count("Volunteer", {"is_active": 1})
        if total_volunteers == 0:
            return 0

        # Try to get volunteer engagement from assignments
        if frappe.db.exists("DocType", "Volunteer Assignment"):
            active_volunteers = frappe.db.sql(
                """
                SELECT COUNT(DISTINCT v.name)
                FROM `tabVolunteer` v
                JOIN `tabVolunteer Assignment` va ON va.volunteer = v.name
                WHERE v.is_active = 1
                AND va.modified >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
            )[0][0]
        else:
            # Fallback: just count recently modified volunteers
            active_volunteers = frappe.db.count(
                "Volunteer", {"is_active": 1, "modified": [">=", get_datetime() - timedelta(days=30)]}
            )

        return round((active_volunteers / total_volunteers) * 100, 2)
    except Exception as e:
        frappe.logger().error(f"Error calculating volunteer engagement: {str(e)}")
        return 0


def get_daily_donations():
    """Get today's donation total"""
    try:
        # Try to get from Donation doctype if it exists
        if frappe.db.exists("DocType", "Donation"):
            result = frappe.db.sql(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM `tabDonation`
                WHERE DATE(creation) = CURDATE()
                AND docstatus = 1
            """
            )
            return float(result[0][0]) if result else 0
        else:
            # Fallback to Sales Invoice for donations
            result = frappe.db.sql(
                """
                SELECT COALESCE(SUM(grand_total), 0)
                FROM `tabSales Invoice`
                WHERE DATE(creation) = CURDATE()
                AND docstatus = 1
                AND customer_group = 'Donor'
            """
            )
            return float(result[0][0]) if result else 0
    except Exception as e:
        frappe.logger().error(f"Error getting daily donations: {str(e)}")
        return 0


def get_system_health_score():
    """Calculate overall system health score"""
    scores = []

    try:
        # Check error rate (inverse score)
        error_count = frappe.db.count("Error Log", {"creation": [">=", get_datetime() - timedelta(hours=1)]})
        scores.append(100 if error_count == 0 else max(0, 100 - (error_count * 10)))
    except:
        scores.append(50)  # Default score if Error Log check fails

    try:
        # Check scheduler - simplified
        if frappe.db.exists("DocType", "Scheduled Job Log"):
            recent_jobs = frappe.db.count(
                "Scheduled Job Log", {"modified": [">=", get_datetime() - timedelta(minutes=30)]}
            )
            scores.append(100 if recent_jobs > 0 else 0)
        else:
            scores.append(75)  # Assume OK if no job logs
    except:
        scores.append(50)

    # Check database response
    try:
        start = datetime.now()
        frappe.db.sql("SELECT 1")
        response_time = (datetime.now() - start).total_seconds()
        scores.append(100 if response_time < 0.1 else 50)
    except:
        scores.append(0)

    return round(sum(scores) / len(scores)) if scores else 50


def get_error_rate():
    """Get error rate percentage"""
    # Errors in last hour
    errors = frappe.db.count("Error Log", {"creation": [">=", get_datetime() - timedelta(hours=1)]})

    # Approximate requests (you'd need actual request tracking)
    # This is a simplified calculation
    return min(errors * 0.1, 100)  # Assume 1000 requests/hour baseline


def get_average_response_time():
    """Get average response time in ms"""
    # This would ideally come from actual performance monitoring
    # For now, return a placeholder
    return 150  # milliseconds


def get_db_connections():
    """Get current database connection count"""
    try:
        result = frappe.db.sql("SHOW STATUS WHERE Variable_name = 'Threads_connected'")
        if result:
            return int(result[0][1])
        return 0
    except Exception:
        return 0


def get_health_details():
    """Get detailed health information for debugging"""
    details = {}

    try:
        # Error rate details
        error_count = frappe.db.count("Error Log", {"creation": [">", get_datetime() - timedelta(hours=1)]})
        details["errors_last_hour"] = error_count
        details["error_score"] = 100 if error_count == 0 else max(0, 100 - (error_count * 10))
    except Exception as e:
        details["error_check_failed"] = str(e)
        details["error_score"] = 50

    try:
        # Scheduler health
        if frappe.db.exists("DocType", "Scheduled Job Log"):
            recent_jobs = frappe.db.count(
                "Scheduled Job Log", {"modified": [">", get_datetime() - timedelta(minutes=30)]}
            )
            details["recent_scheduled_jobs"] = recent_jobs
            details["scheduler_score"] = 100 if recent_jobs > 0 else 0
        else:
            details["scheduler_status"] = "No job logs available"
            details["scheduler_score"] = 75
    except Exception as e:
        details["scheduler_check_failed"] = str(e)
        details["scheduler_score"] = 50

    try:
        # Database response time
        start = datetime.now()
        frappe.db.sql("SELECT 1")
        response_time = (datetime.now() - start).total_seconds()
        details["db_response_time_seconds"] = response_time
        details["db_score"] = 100 if response_time < 0.1 else 50
    except Exception as e:
        details["db_check_failed"] = str(e)
        details["db_score"] = 0

    # Calculate overall score
    scores = [details.get("error_score", 50), details.get("scheduler_score", 50), details.get("db_score", 50)]
    details["overall_score"] = round(sum(scores) / len(scores)) if scores else 50
    details["threshold"] = 70

    return details


# Scheduled job to send metrics
def get_sales_invoices_today():
    """Get count of Sales Invoices created today"""
    try:
        count = frappe.db.count(
            "Sales Invoice",
            {"creation": [">=", get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)]},
        )
        return count
    except Exception as e:
        frappe.logger().error(f"Error getting sales invoices today: {str(e)}")
        return 0


def get_subscription_invoices_today():
    """Get count of subscription-related Sales Invoices created today"""
    try:
        count = frappe.db.count(
            "Sales Invoice",
            {
                "creation": [">=", get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)],
                "subscription": ["!=", ""],
            },
        )
        return count
    except Exception as e:
        frappe.logger().error(f"Error getting subscription invoices today: {str(e)}")
        return 0


def get_total_invoices_today():
    """Get total count of all invoices (Sales + Purchase) created today"""
    try:
        today_start = get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)

        sales_count = frappe.db.count("Sales Invoice", {"creation": [">=", today_start]})
        purchase_count = frappe.db.count("Purchase Invoice", {"creation": [">=", today_start]})

        return sales_count + purchase_count
    except Exception as e:
        frappe.logger().error(f"Error getting total invoices today: {str(e)}")
        return 0


def get_subscriptions_processed_today():
    """Get count of Process Subscription documents created today"""
    try:
        if not frappe.db.exists("DocType", "Process Subscription"):
            return 0

        count = frappe.db.count(
            "Process Subscription",
            {"creation": [">=", get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)]},
        )
        return count
    except Exception as e:
        frappe.logger().error(f"Error getting subscriptions processed today: {str(e)}")
        return 0


def get_last_subscription_processing():
    """Get hours since last subscription processing (0 = processed today)"""
    try:
        if not frappe.db.exists("DocType", "Process Subscription"):
            return 999  # No subscription processing available

        last_process = frappe.db.get_value(
            "Process Subscription", filters={}, fieldname="creation", order_by="creation desc"
        )

        if not last_process:
            return 999  # Never processed

        hours_ago = (now_datetime() - get_datetime(last_process)).total_seconds() / 3600
        return round(hours_ago, 1)

    except Exception as e:
        frappe.logger().error(f"Error getting last subscription processing: {str(e)}")
        return 999


def get_stuck_jobs_count():
    """Get count of potentially stuck scheduler jobs"""
    try:
        if not frappe.db.exists("DocType", "Scheduled Job Type"):
            return 0

        # Jobs that haven't run in over 25 hours but should run daily
        stuck_jobs = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabScheduled Job Type`
            WHERE stopped = 0
            AND frequency IN ('Daily', 'Daily Long')
            AND (last_execution IS NULL OR last_execution < DATE_SUB(NOW(), INTERVAL 25 HOUR))
        """
        )[0][0]

        return int(stuck_jobs)

    except Exception as e:
        frappe.logger().error(f"Error getting stuck jobs count: {str(e)}")
        return 0


def send_metrics_to_zabbix_scheduled():
    """Scheduled job to send metrics every 5 minutes"""
    try:
        send_frappe_metrics_to_zabbix()
    except Exception as e:
        frappe.log_error(f"Failed to send Zabbix metrics: {e}")
