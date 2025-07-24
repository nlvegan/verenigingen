#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitoring Setup Script
Configures monitoring for the Verenigingen application
"""

import os
import sys
import json
import frappe
from pathlib import Path


class MonitoringSetup:
    """Configure monitoring for Verenigingen"""
    
    def __init__(self, site_name):
        self.site_name = site_name
        self.site_path = f"/home/frappe/frappe-bench/sites/{site_name}"
        self.config_path = f"{self.site_path}/site_config.json"
        
    def setup_sentry(self, dsn=None):
        """Configure Sentry integration"""
        print("🔍 Setting up Sentry integration...")
        
        if not dsn:
            print("⚠️  No Sentry DSN provided. Skipping Sentry setup.")
            print("   To enable Sentry, provide your DSN:")
            print("   python setup_monitoring.py --sentry-dsn YOUR_DSN_HERE")
            return
            
        config_updates = {
            "sentry_dsn": dsn,
            "enable_sentry_db_monitoring": 1,
            "sentry_tracing_sample_rate": 0.1,
            "sentry_profiling_sample_rate": 0.1,
            "sentry_environment": "production"
        }
        
        self._update_site_config(config_updates)
        print("✅ Sentry integration configured!")
        
    def setup_frappe_monitor(self):
        """Enable Frappe's built-in monitoring"""
        print("📊 Enabling Frappe Monitor...")
        
        config_updates = {
            "monitor": 1,
            "logging": 2,
            "verbose": 1
        }
        
        self._update_site_config(config_updates)
        print("✅ Frappe Monitor enabled!")
        
    def create_default_alerts(self):
        """Create default analytics alert rules"""
        print("🚨 Creating default alert rules...")
        
        frappe.init(site=self.site_name)
        frappe.connect()
        
        try:
            alerts = [
                {
                    "alert_name": "High Error Rate",
                    "metric_type": "Error Rate",
                    "condition": ">",
                    "threshold_value": 5.0,
                    "check_frequency": "Hourly",
                    "action": "Send Email",
                    "description": "Alert when error rate exceeds 5%"
                },
                {
                    "alert_name": "Low Active Members",
                    "metric_type": "Active Members",
                    "condition": "<",
                    "threshold_value": 100,
                    "check_frequency": "Daily",
                    "action": "Send Email",
                    "description": "Alert when active members drop below 100"
                },
                {
                    "alert_name": "High Member Churn",
                    "metric_type": "Member Churn Rate",
                    "condition": ">",
                    "threshold_value": 10.0,
                    "check_frequency": "Weekly",
                    "action": "Send Email",
                    "description": "Alert when member churn exceeds 10%"
                },
                {
                    "alert_name": "Donation Target Miss",
                    "metric_type": "Donation Revenue",
                    "condition": "<",
                    "threshold_value": 5000,
                    "check_frequency": "Monthly",
                    "action": "Send Email",
                    "description": "Alert when monthly donations below target"
                },
                {
                    "alert_name": "Slow API Response",
                    "metric_type": "API Response Time",
                    "condition": ">",
                    "threshold_value": 2000,  # milliseconds
                    "check_frequency": "Hourly",
                    "action": "Send Email",
                    "description": "Alert when API response time exceeds 2 seconds"
                }
            ]
            
            for alert_config in alerts:
                # Check if alert already exists
                if not frappe.db.exists("Analytics Alert Rule", 
                                      {"alert_name": alert_config["alert_name"]}):
                    alert = frappe.new_doc("Analytics Alert Rule")
                    alert.update(alert_config)
                    alert.is_active = 1
                    alert.insert(ignore_permissions=True)
                    print(f"  ✓ Created alert: {alert_config['alert_name']}")
                else:
                    print(f"  - Alert already exists: {alert_config['alert_name']}")
                    
            frappe.db.commit()
            print("✅ Default alerts created!")
            
        finally:
            frappe.destroy()
            
    def create_monitoring_dashboard(self):
        """Create monitoring dashboard page"""
        print("📈 Creating monitoring dashboard...")
        
        dashboard_py = """import frappe
from frappe import _
from verenigingen.utils.performance_dashboard import PerformanceDashboard

def get_context(context):
    if not frappe.has_permission("System Manager"):
        raise frappe.PermissionError
        
    dashboard = PerformanceDashboard()
    
    try:
        metrics = dashboard.get_metrics()
        slow_queries = dashboard.get_slow_queries()
        errors = dashboard.get_error_analysis()
        suggestions = dashboard.get_optimization_suggestions()
    except Exception as e:
        frappe.log_error(f"Error loading dashboard: {e}")
        metrics = {}
        slow_queries = []
        errors = {}
        suggestions = []
    
    context.update({
        "title": _("Performance Dashboard"),
        "metrics": metrics,
        "slow_queries": slow_queries,
        "errors": errors,
        "suggestions": suggestions,
        "no_cache": 1
    })
    
    return context
"""
        
        dashboard_html = """{% extends "templates/web.html" %}

{% block title %}{{ title }}{% endblock %}

{% block page_content %}
<div class="container mt-4">
    <h1>{{ title }}</h1>
    
    <!-- Key Metrics -->
    <div class="row mt-4">
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Response Time</h5>
                    <p class="card-text h3">{{ metrics.avg_response_time|round(2) }}ms</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Error Rate</h5>
                    <p class="card-text h3">{{ metrics.error_rate|round(2) }}%</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Active Users</h5>
                    <p class="card-text h3">{{ metrics.active_users }}</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">System Health</h5>
                    <p class="card-text h3">{{ metrics.health_score|round(0) }}%</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Slow Queries -->
    <div class="mt-5">
        <h3>Slow Queries</h3>
        {% if slow_queries %}
        <table class="table table-striped">
            <thead>
                <tr>
                    <th>Query</th>
                    <th>Duration</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody>
                {% for query in slow_queries[:10] %}
                <tr>
                    <td><code>{{ query.query[:100] }}...</code></td>
                    <td>{{ query.duration|round(2) }}ms</td>
                    <td>{{ query.count }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p class="text-muted">No slow queries detected.</p>
        {% endif %}
    </div>
    
    <!-- Recent Errors -->
    <div class="mt-5">
        <h3>Recent Errors</h3>
        {% if errors.recent_errors %}
        <table class="table table-striped">
            <thead>
                <tr>
                    <th>Error</th>
                    <th>Count</th>
                    <th>Last Seen</th>
                </tr>
            </thead>
            <tbody>
                {% for error in errors.recent_errors[:10] %}
                <tr>
                    <td>{{ error.method }}: {{ error.error[:50] }}...</td>
                    <td>{{ error.count }}</td>
                    <td>{{ frappe.utils.pretty_datetime(error.last_seen) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p class="text-muted">No recent errors.</p>
        {% endif %}
    </div>
    
    <!-- Optimization Suggestions -->
    <div class="mt-5">
        <h3>Optimization Suggestions</h3>
        {% if suggestions %}
        <ul class="list-group">
            {% for suggestion in suggestions %}
            <li class="list-group-item">
                <strong>{{ suggestion.title }}</strong><br>
                {{ suggestion.description }}
                {% if suggestion.priority == "high" %}
                <span class="badge bg-danger">High Priority</span>
                {% elif suggestion.priority == "medium" %}
                <span class="badge bg-warning">Medium Priority</span>
                {% else %}
                <span class="badge bg-info">Low Priority</span>
                {% endif %}
            </li>
            {% endfor %}
        </ul>
        {% else %}
        <p class="text-muted">No optimization suggestions at this time.</p>
        {% endif %}
    </div>
</div>
{% endblock %}
"""
        
        # Create www directory if it doesn't exist
        www_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/www"
        Path(www_path).mkdir(parents=True, exist_ok=True)
        
        # Write dashboard files
        with open(f"{www_path}/performance_dashboard.py", "w") as f:
            f.write(dashboard_py)
            
        with open(f"{www_path}/performance_dashboard.html", "w") as f:
            f.write(dashboard_html)
            
        print("✅ Monitoring dashboard created at /performance_dashboard")
        
    def setup_log_rotation(self):
        """Configure log rotation"""
        print("🔄 Setting up log rotation...")
        
        logrotate_config = """
/home/frappe/frappe-bench/sites/*/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 frappe frappe
    sharedscripts
    postrotate
        supervisorctl restart all
    endscript
}
"""
        
        # Note: This would need sudo access to write to /etc/logrotate.d/
        print("   Log rotation configuration:")
        print(logrotate_config)
        print("   ⚠️  Please add this to /etc/logrotate.d/frappe with sudo")
        
    def create_health_check_endpoint(self):
        """Create health check endpoint"""
        print("🏥 Creating health check endpoint...")
        
        health_check_py = """import frappe
from frappe import _
import json

def get_context(context):
    # Allow guest access for monitoring tools
    context.no_cache = 1
    return context

@frappe.whitelist(allow_guest=True)
def health():
    \"\"\"Health check endpoint for monitoring\"\"\"
    try:
        # Basic checks
        checks = {
            "database": check_database(),
            "redis": check_redis(),
            "scheduler": check_scheduler(),
            "background_jobs": check_background_jobs()
        }
        
        # Overall status
        all_healthy = all(check["status"] == "healthy" for check in checks.values())
        
        response = {
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": checks,
            "timestamp": frappe.utils.now_datetime()  # More explicit datetime
        }
        
        frappe.response["content_type"] = "application/json"
        return response
        
    except Exception as e:
        frappe.response["content_type"] = "application/json"
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": frappe.utils.now_datetime()  # More explicit datetime
        }

def check_database():
    \"\"\"Check database connectivity\"\"\"
    try:
        frappe.db.sql("SELECT 1")
        return {"status": "healthy", "message": "Database is responsive"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}

def check_redis():
    \"\"\"Check Redis connectivity\"\"\"
    try:
        frappe.cache().ping()
        return {"status": "healthy", "message": "Redis is responsive"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}

def check_scheduler():
    \"\"\"Check if scheduler is running\"\"\"
    try:
        last_run = frappe.get_last_doc("Scheduled Job Log")
        if last_run:
            time_diff = frappe.utils.time_diff_in_seconds(
                frappe.utils.now(), 
                last_run.modified
            )
            if time_diff < 300:  # 5 minutes
                return {"status": "healthy", "message": "Scheduler is running"}
        return {"status": "unhealthy", "message": "Scheduler may be stopped"}
    except Exception:
        return {"status": "unknown", "message": "Could not check scheduler"}

def check_background_jobs():
    \"\"\"Check background job queue\"\"\"
    try:
        from frappe.utils.background_jobs import get_queue_length
        queue_length = get_queue_length()
        if queue_length < 1000:
            return {"status": "healthy", "message": f"Queue length: {queue_length}"}
        else:
            return {"status": "unhealthy", "message": f"Queue backed up: {queue_length}"}
    except Exception:
        return {"status": "unknown", "message": "Could not check job queue"}
"""
        
        # Write health check endpoint
        www_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/www"
        with open(f"{www_path}/health.py", "w") as f:
            f.write(health_check_py)
            
        print("✅ Health check endpoint created at /health")
        
    def _update_site_config(self, updates):
        """Update site configuration file"""
        # Load existing config
        config = {}
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                
        # Update config
        config.update(updates)
        
        # Write back
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)
            
    def display_summary(self):
        """Display setup summary"""
        print("\n" + "="*50)
        print("📊 MONITORING SETUP COMPLETE")
        print("="*50)
        print("\nAvailable endpoints:")
        print("  - Performance Dashboard: https://your-site/performance_dashboard")
        print("  - Health Check: https://your-site/health")
        print("\nNext steps:")
        print("  1. Restart bench: bench restart")
        print("  2. Configure email for alerts")
        print("  3. Set up Sentry DSN if not done")
        print("  4. Configure log rotation with sudo")
        print("\nMonitoring commands:")
        print(f"  - View logs: bench --site {self.site_name} show-logs")
        print("  - Check health: curl https://your-site/health")
        print(f"  - View errors: bench --site {self.site_name} console")
        print("    >>> frappe.get_all('Error Log', limit=10)")
        
    def run_full_setup(self, sentry_dsn=None):
        """Run complete monitoring setup"""
        print("🚀 Starting monitoring setup for Verenigingen...\n")
        
        self.setup_frappe_monitor()
        self.setup_sentry(sentry_dsn)
        self.create_default_alerts()
        self.create_monitoring_dashboard()
        self.create_health_check_endpoint()
        self.setup_log_rotation()
        self.display_summary()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Setup monitoring for Verenigingen")
    parser.add_argument("--site", 
                       default="dev.veganisme.net",
                       help="Site name (default: dev.veganisme.net)")
    parser.add_argument("--sentry-dsn",
                       help="Sentry DSN for error tracking")
    
    args = parser.parse_args()
    
    setup = MonitoringSetup(args.site)
    setup.run_full_setup(args.sentry_dsn)


if __name__ == "__main__":
    main()
