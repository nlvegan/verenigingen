#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Advanced Zabbix 7.0 Integration for Frappe
Leverages new Zabbix 7.0 features like anomaly detection and improved preprocessing
"""

import json
import requests
import frappe
from frappe.utils import now_datetime, get_datetime
from datetime import datetime, timedelta
import hashlib
import hmac


class ZabbixV7Integration:
    """Enhanced integration for Zabbix 7.0"""
    
    def __init__(self):
        self.zabbix_url = frappe.conf.get("zabbix_url", "http://zabbix.example.com")
        self.zabbix_token = frappe.conf.get("zabbix_api_token")  # Zabbix 7.0 uses tokens
        self.webhook_secret = frappe.conf.get("zabbix_webhook_secret", "")
        
    def send_to_zabbix_v7(self, metrics):
        """Send metrics using Zabbix 7.0 HTTP agent format"""
        # Zabbix 7.0 supports bulk metric sending
        data = {
            "request": "agent data",
            "session": frappe.local.site,
            "data": []
        }
        
        host = frappe.conf.get("zabbix_host_name", "frappe-production")
        clock = int(datetime.now().timestamp())
        
        for key, value in metrics.items():
            data["data"].append({
                "host": host,
                "key": key,
                "value": str(value),
                "clock": clock,
                "ns": 0
            })
            
        # Send to Zabbix server HTTP endpoint
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.zabbix_token}"
        }
        
        try:
            response = requests.post(
                f"{self.zabbix_url}/api/v2/metrics",
                json=data,
                headers=headers,
                timeout=10
            )
            return response.json()
        except Exception as e:
            frappe.log_error(f"Zabbix 7.0 send error: {e}")
            return None


@frappe.whitelist(allow_guest=True)
def get_metrics_with_metadata():
    """Enhanced metrics endpoint with Zabbix 7.0 metadata support"""
    # Validate request signature if configured
    if frappe.conf.get("zabbix_webhook_secret"):
        if not validate_zabbix_signature():
            frappe.throw("Invalid signature", frappe.AuthenticationError)
    
    metrics = {
        "timestamp": now_datetime().isoformat(),
        "host": frappe.conf.get("zabbix_host_name", "frappe-production"),
        "metrics": {},
        "metadata": {},  # Zabbix 7.0 metadata
        "tags": {}  # Zabbix 7.0 tags
    }
    
    # Business metrics with metadata
    metrics["metrics"]["active_members"] = {
        "value": frappe.db.count("Member", {"status": "Active"}),
        "unit": "members",
        "description": "Currently active members"
    }
    
    metrics["metrics"]["daily_donations"] = {
        "value": get_daily_donations(),
        "unit": "EUR",
        "description": "Total donations today"
    }
    
    metrics["metrics"]["volunteer_engagement"] = {
        "value": calculate_volunteer_engagement_score(),
        "unit": "%",
        "description": "Volunteer engagement score"
    }
    
    # Performance metrics for anomaly detection
    perf_data = get_performance_metrics()
    metrics["metrics"]["response_time_p50"] = {
        "value": perf_data.get("p50", 0),
        "unit": "ms",
        "description": "50th percentile response time"
    }
    
    metrics["metrics"]["response_time_p95"] = {
        "value": perf_data.get("p95", 0),
        "unit": "ms",
        "description": "95th percentile response time"
    }
    
    metrics["metrics"]["response_time_p99"] = {
        "value": perf_data.get("p99", 0),
        "unit": "ms",
        "description": "99th percentile response time"
    }
    
    # Error categorization for Zabbix 7.0
    error_breakdown = get_error_breakdown()
    for error_type, count in error_breakdown.items():
        metrics["metrics"][f"errors_{error_type}"] = {
            "value": count,
            "unit": "errors",
            "description": f"{error_type} errors in last hour"
        }
    
    # Metadata for Zabbix 7.0
    metrics["metadata"] = {
        "app_version": frappe.get_attr("verenigingen.__version__"),
        "frappe_version": frappe.__version__,
        "site": frappe.local.site,
        "environment": frappe.conf.get("environment", "production")
    }
    
    # Tags for better organization in Zabbix 7.0
    metrics["tags"] = {
        "app": "verenigingen",
        "type": "business",
        "region": frappe.conf.get("region", "eu-west"),
        "tier": frappe.conf.get("tier", "production")
    }
    
    # Flatten for backward compatibility
    flat_metrics = {
        "timestamp": metrics["timestamp"],
        "metrics": {}
    }
    
    for key, data in metrics["metrics"].items():
        if isinstance(data, dict):
            flat_metrics["metrics"][key] = data["value"]
        else:
            flat_metrics["metrics"][key] = data
            
    frappe.response["content_type"] = "application/json"
    return flat_metrics


@frappe.whitelist(allow_guest=True)
def zabbix_v7_webhook():
    """Enhanced webhook receiver for Zabbix 7.0 with signature validation"""
    try:
        # Validate webhook signature
        if not validate_zabbix_signature():
            frappe.response["http_status_code"] = 401
            return {"status": "error", "message": "Invalid signature"}
            
        data = frappe.request.get_json()
        
        # Zabbix 7.0 webhook format
        alert = {
            "event_id": data.get("event_id"),
            "trigger_id": data.get("trigger_id"),
            "trigger_name": data.get("trigger", {}).get("name"),
            "severity": data.get("trigger", {}).get("severity"),
            "host": data.get("host", {}).get("name"),
            "timestamp": data.get("timestamp"),
            "value": data.get("value"),
            "operational_data": data.get("operational_data", {}),
            "tags": data.get("tags", []),
            "event_tags": data.get("event_tags", [])
        }
        
        # Process based on tags (Zabbix 7.0 feature)
        if any(tag.get("tag") == "auto_remediate" for tag in alert["event_tags"]):
            handle_auto_remediation(alert)
        elif alert["severity"] in ["High", "Disaster"]:
            create_urgent_issue(alert)
        else:
            log_alert(alert)
            
        # Send acknowledgment to Zabbix 7.0
        acknowledge_zabbix_event(alert["event_id"])
        
        return {"status": "success", "event_id": alert["event_id"]}
        
    except Exception as e:
        frappe.log_error(f"Zabbix 7.0 webhook error: {e}")
        frappe.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}


def validate_zabbix_signature():
    """Validate Zabbix webhook signature for security"""
    secret = frappe.conf.get("zabbix_webhook_secret")
    if not secret:
        return True  # No secret configured, skip validation
        
    signature = frappe.request.headers.get("X-Zabbix-Signature")
    if not signature:
        return False
        
    # Calculate expected signature
    body = frappe.request.get_data()
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected)


def get_performance_metrics():
    """Get detailed performance metrics for Zabbix 7.0 anomaly detection"""
    # Get response times from last hour
    response_times = frappe.db.sql("""
        SELECT response_time
        FROM `tabRequest Log`
        WHERE creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
        ORDER BY response_time
    """, as_dict=True)
    
    if not response_times:
        return {"p50": 0, "p95": 0, "p99": 0}
        
    times = [r.response_time for r in response_times]
    times.sort()
    
    def percentile(data, p):
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data)-1)]
        
    return {
        "p50": percentile(times, 50),
        "p95": percentile(times, 95),
        "p99": percentile(times, 99)
    }


def get_error_breakdown():
    """Categorize errors for better monitoring in Zabbix 7.0"""
    breakdown = {}
    
    errors = frappe.db.sql("""
        SELECT error, COUNT(*) as count
        FROM `tabError Log`
        WHERE creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
        GROUP BY error
    """, as_dict=True)
    
    for error in errors:
        # Categorize errors
        error_text = error.error.lower()
        if "permission" in error_text:
            category = "permission"
        elif "validation" in error_text:
            category = "validation"
        elif "timeout" in error_text:
            category = "timeout"
        elif "connection" in error_text:
            category = "connection"
        else:
            category = "other"
            
        breakdown[category] = breakdown.get(category, 0) + error.count
        
    return breakdown


def handle_auto_remediation(alert):
    """Auto-remediate issues based on Zabbix 7.0 tags"""
    remediation_map = {
        "high_queue_size": clear_stuck_queue,
        "low_memory": cleanup_temp_files,
        "high_error_rate": restart_background_workers,
        "stale_locks": clear_stale_locks
    }
    
    for tag in alert["event_tags"]:
        if tag.get("tag") == "remediation" and tag.get("value") in remediation_map:
            try:
                remediation_map[tag["value"]]()
                frappe.log_error(
                    title=f"Auto-remediation: {tag['value']}",
                    message=f"Successfully executed for alert: {alert['trigger_name']}"
                )
            except Exception as e:
                frappe.log_error(
                    title=f"Auto-remediation failed: {tag['value']}",
                    message=str(e)
                )


def acknowledge_zabbix_event(event_id):
    """Acknowledge event in Zabbix 7.0"""
    try:
        zabbix = ZabbixV7Integration()
        
        payload = {
            "jsonrpc": "2.0",
            "method": "event.acknowledge",
            "params": {
                "eventids": event_id,
                "action": 6,  # Acknowledge and close
                "message": f"Processed by Frappe at {now_datetime()}"
            },
            "auth": zabbix.zabbix_token,
            "id": 1
        }
        
        requests.post(
            f"{zabbix.zabbix_url}/api_jsonrpc.php",
            json=payload,
            timeout=10
        )
    except Exception as e:
        frappe.log_error(f"Failed to acknowledge Zabbix event: {e}")


def calculate_volunteer_engagement_score():
    """Calculate engagement score with trend analysis"""
    # Current month engagement
    current = frappe.db.sql("""
        SELECT COUNT(DISTINCT v.name) as engaged
        FROM `tabVolunteer` v
        JOIN `tabVolunteer Assignment` va ON va.volunteer = v.name
        WHERE v.is_active = 1
        AND va.modified >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """)[0][0]
    
    total = frappe.db.count("Volunteer", {"is_active": 1})
    
    if total == 0:
        return 0
        
    score = (current / total) * 100
    
    # Add trend component for Zabbix 7.0 anomaly detection
    last_month = frappe.db.sql("""
        SELECT COUNT(DISTINCT v.name) as engaged
        FROM `tabVolunteer` v
        JOIN `tabVolunteer Assignment` va ON va.volunteer = v.name
        WHERE v.is_active = 1
        AND va.modified >= DATE_SUB(NOW(), INTERVAL 60 DAY)
        AND va.modified < DATE_SUB(NOW(), INTERVAL 30 DAY)
    """)[0][0]
    
    if last_month > 0:
        trend = ((current - last_month) / last_month) * 10  # ±10% weight
        score = min(100, max(0, score + trend))
        
    return round(score, 2)


# Auto-remediation functions
def clear_stuck_queue():
    """Clear stuck background jobs"""
    frappe.db.sql("""
        DELETE FROM `tabRQ Job`
        WHERE status = 'started'
        AND modified < DATE_SUB(NOW(), INTERVAL 1 HOUR)
    """)
    frappe.db.commit()


def cleanup_temp_files():
    """Clean up temporary files to free memory"""
    import os
    import shutil
    
    temp_dirs = [
        "/tmp/frappe-*",
        frappe.get_site_path("private/backups/"),
        frappe.get_site_path("public/files/.trash/")
    ]
    
    for temp_dir in temp_dirs:
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception:
            pass


def restart_background_workers():
    """Restart background workers"""
    # This would typically be done via supervisor
    frappe.enqueue(
        "frappe.utils.background_jobs.restart_workers",
        queue="short",
        timeout=300
    )


def clear_stale_locks():
    """Clear stale document locks"""
    frappe.db.sql("""
        DELETE FROM `tabDocument Lock`
        WHERE timestamp < DATE_SUB(NOW(), INTERVAL 1 HOUR)
    """)
    frappe.db.commit()


# Scheduled job for Zabbix 7.0
def send_enhanced_metrics_to_zabbix():
    """Send enhanced metrics using Zabbix 7.0 features"""
    zabbix = ZabbixV7Integration()
    
    # Collect comprehensive metrics
    metrics = {
        # Business metrics
        "frappe.members.active": frappe.db.count("Member", {"status": "Active"}),
        "frappe.members.new_today": frappe.db.count("Member", {
            "creation": [">=", datetime.now().date()]
        }),
        
        # Performance percentiles for anomaly detection
        **{f"frappe.response.p{p}": v for p, v in get_performance_metrics().items()},
        
        # Error breakdown
        **{f"frappe.errors.{cat}": count for cat, count in get_error_breakdown().items()},
        
        # Calculated metrics
        "frappe.volunteer.engagement_score": calculate_volunteer_engagement_score(),
        
        # Business health indicators
        "frappe.donation.conversion_rate": calculate_donation_conversion_rate(),
        "frappe.member.retention_rate": calculate_retention_rate()
    }
    
    # Send to Zabbix 7.0
    result = zabbix.send_to_zabbix_v7(metrics)
    
    if result and result.get("failed") == 0:
        frappe.log_error(
            title="Zabbix metrics sent",
            message=f"Sent {len(metrics)} metrics successfully"
        )


def calculate_donation_conversion_rate():
    """Calculate donation conversion rate"""
    # Implementation specific to your business logic
    return 0.0


def calculate_retention_rate():
    """Calculate member retention rate"""
    # Implementation specific to your business logic
    return 0.0