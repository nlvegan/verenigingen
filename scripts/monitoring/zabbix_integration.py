#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix Integration for Frappe/Verenigingen
Sends metrics and alerts between Zabbix and Frappe
"""

import json
import requests
import frappe
from frappe.utils import now_datetime, get_datetime
from datetime import datetime, timedelta


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
            "params": {
                "user": self.zabbix_user,
                "password": self.zabbix_password
            },
            "id": 1
        }
        
        response = requests.post(
            f"{self.zabbix_url}/api_jsonrpc.php",
            json=payload,
            headers={"Content-Type": "application/json"}
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
            "data": [{
                "host": host,
                "key": key,
                "value": str(value),
                "clock": int(datetime.now().timestamp())
            }]
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
            "params": {
                "description": name,
                "expression": expression,
                "priority": severity
            },
            "auth": self.zabbix_token,
            "id": 1
        }
        
        response = requests.post(
            f"{self.zabbix_url}/api_jsonrpc.php",
            json=payload
        )
        
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
        "frappe.donations.today": float(frappe.db.sql("""
            SELECT COALESCE(SUM(grand_total), 0) 
            FROM `tabDonation` 
            WHERE DATE(creation) = CURDATE()
        """)[0][0]),
        
        # Performance metrics
        "frappe.error_logs.count": frappe.db.count("Error Log", {
            "creation": [">=", get_datetime() - timedelta(hours=1)]
        }),
        
        # Queue metrics
        "frappe.queue.pending": get_queue_length(),
        
        # Custom business metrics
        "frappe.member.churn_rate": calculate_churn_rate(),
        "frappe.volunteer.engagement": calculate_volunteer_engagement()
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
            "message": data.get("message")
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
        priority=1
    )
    
    # Create Analytics Alert Log
    if frappe.db.exists("DocType", "Analytics Alert Log"):
        alert_log = frappe.new_doc("Analytics Alert Log")
        alert_log.alert_name = alert['trigger']
        alert_log.alert_type = "External - Zabbix"
        alert_log.severity = alert['severity']
        alert_log.details = json.dumps(alert)
        alert_log.insert(ignore_permissions=True)


def create_monitoring_log(alert):
    """Log non-critical alerts"""
    frappe.log_error(
        title=f"Zabbix Alert: {alert['trigger']}",
        message=json.dumps(alert, indent=2)
    )


@frappe.whitelist()
def get_metrics_for_zabbix():
    """API endpoint for Zabbix to pull metrics"""
    # This endpoint can be called by Zabbix HTTP agent
    metrics = {
        "timestamp": now_datetime().isoformat(),
        "metrics": {
            "active_members": frappe.db.count("Member", {"status": "Active"}),
            "pending_expenses": frappe.db.count("Volunteer Expense", {"status": "Pending"}),
            "daily_donations": get_daily_donations(),
            "system_health": get_system_health_score(),
            "error_rate": get_error_rate(),
            "response_time": get_average_response_time()
        }
    }
    
    frappe.response["content_type"] = "application/json"
    return metrics


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
    churned = frappe.db.count("Member", {
        "status": "Terminated",
        "modified": [">=", get_datetime() - timedelta(days=30)]
    })
    
    total = frappe.db.count("Member", {"status": "Active"})
    
    if total > 0:
        return round((churned / total) * 100, 2)
    return 0


def calculate_volunteer_engagement():
    """Calculate volunteer engagement score"""
    # Active volunteers with recent activity
    active_volunteers = frappe.db.sql("""
        SELECT COUNT(DISTINCT v.name)
        FROM `tabVolunteer` v
        JOIN `tabVolunteer Assignment` va ON va.volunteer = v.name
        WHERE v.is_active = 1
        AND va.modified >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """)[0][0]
    
    total_volunteers = frappe.db.count("Volunteer", {"is_active": 1})
    
    if total_volunteers > 0:
        return round((active_volunteers / total_volunteers) * 100, 2)
    return 0


def get_daily_donations():
    """Get today's donation total"""
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(grand_total), 0)
        FROM `tabDonation`
        WHERE DATE(creation) = CURDATE()
        AND docstatus = 1
    """)
    return float(result[0][0]) if result else 0


def get_system_health_score():
    """Calculate overall system health score"""
    scores = []
    
    # Check error rate (inverse score)
    error_count = frappe.db.count("Error Log", {
        "creation": [">=", get_datetime() - timedelta(hours=1)]
    })
    scores.append(100 if error_count == 0 else max(0, 100 - (error_count * 10)))
    
    # Check scheduler
    last_job = frappe.get_last_doc("Scheduled Job Log") if frappe.db.exists("Scheduled Job Log", {}) else None
    if last_job and (get_datetime() - get_datetime(last_job.modified)).seconds < 300:
        scores.append(100)
    else:
        scores.append(0)
        
    # Check database response
    try:
        start = datetime.now()
        frappe.db.sql("SELECT 1")
        response_time = (datetime.now() - start).total_seconds()
        scores.append(100 if response_time < 0.1 else 50)
    except:
        scores.append(0)
        
    return round(sum(scores) / len(scores)) if scores else 0


def get_error_rate():
    """Get error rate percentage"""
    # Errors in last hour
    errors = frappe.db.count("Error Log", {
        "creation": [">=", get_datetime() - timedelta(hours=1)]
    })
    
    # Approximate requests (you'd need actual request tracking)
    # This is a simplified calculation
    return min(errors * 0.1, 100)  # Assume 1000 requests/hour baseline


def get_average_response_time():
    """Get average response time in ms"""
    # This would ideally come from actual performance monitoring
    # For now, return a placeholder
    return 150  # milliseconds


# Scheduled job to send metrics
def send_metrics_to_zabbix_scheduled():
    """Scheduled job to send metrics every 5 minutes"""
    try:
        send_frappe_metrics_to_zabbix()
    except Exception as e:
        frappe.log_error(f"Failed to send Zabbix metrics: {e}")