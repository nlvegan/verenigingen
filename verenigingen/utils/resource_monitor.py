#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resource Monitor for Verenigingen
Monitors system resources and performance metrics
"""

import json

import frappe
from frappe.utils import add_to_date, now


class ResourceMonitor:
    """Monitor system resources and performance"""

    def __init__(self):
        self.thresholds = {
            "memory_percent": 85,
            "cpu_percent": 80,
            "disk_percent": 90,
            "active_connections": 100,
            "queue_length": 50,
            "error_rate_threshold": 10,
        }

    def collect_system_metrics(self):
        """Collect comprehensive system metrics"""
        try:
            # Try to import psutil for system metrics
            try:
                import psutil

                system_available = True
            except ImportError:
                system_available = False

            metrics = {
                "timestamp": now(),
                "database": self.get_database_metrics(),
                "application": self.get_application_metrics(),
                "business": self.get_business_metrics(),
            }

            if system_available:
                metrics["system"] = self.get_system_resource_metrics()
            else:
                metrics["system"] = {"error": "psutil not available"}

            return metrics

        except Exception as e:
            frappe.log_error(f"Error collecting system metrics: {str(e)}")
            return {"error": str(e), "timestamp": now()}

    def get_system_resource_metrics(self):
        """Get system resource usage (requires psutil)"""
        try:
            import psutil

            return {
                "cpu_percent": round(psutil.cpu_percent(interval=1), 2),
                "memory_percent": round(psutil.virtual_memory().percent, 2),
                "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                "disk_usage_percent": round(psutil.disk_usage("/").percent, 2),
                "disk_free_gb": round(psutil.disk_usage("/").free / (1024**3), 2),
                "load_average": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
                "boot_time": psutil.boot_time(),
            }
        except ImportError:
            return {"error": "psutil not installed"}
        except Exception as e:
            return {"error": str(e)}

    def get_database_metrics(self):
        """Get database performance metrics"""
        try:
            return {
                "total_tables": self.get_table_count(),
                "error_logs_count": frappe.db.count("Error Log"),
                "recent_errors": frappe.db.count(
                    "Error Log", {"creation": (">=", add_to_date(now(), hours=-1))}
                ),
                "database_size_mb": self.get_database_size(),
                "active_connections": self.get_active_connections(),
                "slow_queries": self.get_slow_query_indicators(),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_application_metrics(self):
        """Get Frappe application metrics"""
        try:
            return {
                "active_users": frappe.db.count("User", {"enabled": 1}),
                "logged_in_users": self.get_logged_in_users(),
                "background_jobs": self.get_background_job_metrics(),
                "cache_status": "OK",  # Simplified
                "session_count": self.get_session_count(),
                "scheduler_status": self.get_scheduler_status(),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_business_metrics(self):
        """Get business process metrics"""
        try:
            return {
                "daily_transactions": self.get_daily_transaction_count(),
                "payment_success_rate": self.get_payment_success_rate(),
                "member_activity": self.get_member_activity_metrics(),
                "sepa_health": self.get_sepa_health_metrics(),
                "application_pipeline": self.get_application_metrics_business(),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_table_count(self):
        """Get total database table count"""
        try:
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM information_schema.tables
                WHERE table_schema = %s
            """,
                [frappe.conf.db_name],
                as_dict=True,
            )
            return result[0]["count"] if result else 0
        except:
            return 0

    def get_database_size(self):
        """Get database size in MB"""
        try:
            result = frappe.db.sql(
                """
                SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb
                FROM information_schema.tables
                WHERE table_schema = %s
            """,
                [frappe.conf.db_name],
                as_dict=True,
            )
            return result[0]["size_mb"] if result else 0
        except:
            return 0

    def get_active_connections(self):
        """Get active database connection count"""
        try:
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM information_schema.processlist
                WHERE db = %s
            """,
                [frappe.conf.db_name],
                as_dict=True,
            )
            return result[0]["count"] if result else 0
        except:
            return 0

    def get_slow_query_indicators(self):
        """Get indicators of slow queries"""
        try:
            # Count errors that might indicate slow queries
            timeout_errors = frappe.db.count(
                "Error Log",
                {"error": ("like", "%timeout%"), "creation": (">=", add_to_date(now(), hours=-1))},
            )

            lock_errors = frappe.db.count(
                "Error Log", {"error": ("like", "%lock%"), "creation": (">=", add_to_date(now(), hours=-1))}
            )

            return {
                "timeout_errors": timeout_errors,
                "lock_errors": lock_errors,
                "total_performance_issues": timeout_errors + lock_errors,
            }
        except:
            return {"timeout_errors": 0, "lock_errors": 0, "total_performance_issues": 0}

    def get_logged_in_users(self):
        """Get count of recently active users"""
        try:
            return frappe.db.count("User", {"last_login": (">=", add_to_date(now(), days=-1)), "enabled": 1})
        except:
            return 0

    def get_background_job_metrics(self):
        """Get background job queue metrics"""
        try:
            return {
                "queued": frappe.db.count("RQ Job", {"status": "queued"}),
                "failed": frappe.db.count("RQ Job", {"status": "failed"}),
                "finished_today": frappe.db.count(
                    "RQ Job", {"status": "finished", "creation": (">=", frappe.utils.today())}
                ),
            }
        except:
            return {"queued": 0, "failed": 0, "finished_today": 0}

    def get_session_count(self):
        """Get active session count"""
        try:
            return frappe.db.count("Sessions", {"lastupdate": (">=", add_to_date(now(), hours=-1))})
        except:
            return 0

    def get_scheduler_status(self):
        """Get scheduler status"""
        try:
            # Check if scheduler is enabled
            scheduler_enabled = frappe.utils.cint(frappe.conf.get("disable_scheduler")) == 0

            # Check recent scheduled job execution
            recent_jobs = frappe.db.count(
                "Scheduled Job Log", {"creation": (">=", add_to_date(now(), hours=-1))}
            )

            return {
                "enabled": scheduler_enabled,
                "recent_executions": recent_jobs,
                "status": "healthy" if scheduler_enabled and recent_jobs > 0 else "warning",
            }
        except:
            return {"enabled": False, "recent_executions": 0, "status": "unknown"}

    def get_daily_transaction_count(self):
        """Get daily transaction count"""
        try:
            return {
                "payments": frappe.db.count(
                    "Payment Entry", {"creation": (">=", frappe.utils.today()), "docstatus": 1}
                ),
                "invoices": frappe.db.count(
                    "Sales Invoice", {"creation": (">=", frappe.utils.today()), "docstatus": 1}
                ),
                "journal_entries": frappe.db.count(
                    "Journal Entry", {"creation": (">=", frappe.utils.today()), "docstatus": 1}
                ),
            }
        except:
            return {"payments": 0, "invoices": 0, "journal_entries": 0}

    def get_payment_success_rate(self):
        """Get payment success rate"""
        try:
            total_today = frappe.db.count("Payment Entry", {"creation": (">=", frappe.utils.today())})

            if total_today == 0:
                return {"rate": 100.0, "total": 0, "successful": 0, "failed": 0}

            successful = frappe.db.count(
                "Payment Entry", {"creation": (">=", frappe.utils.today()), "docstatus": 1}
            )

            failed = frappe.db.count(
                "Payment Entry", {"creation": (">=", frappe.utils.today()), "docstatus": 2}
            )

            rate = round((successful / total_today) * 100, 2)

            return {"rate": rate, "total": total_today, "successful": successful, "failed": failed}
        except:
            return {"rate": 100.0, "total": 0, "successful": 0, "failed": 0}

    def get_member_activity_metrics(self):
        """Get member activity metrics"""
        try:
            return {
                "new_today": frappe.db.count("Member", {"creation": (">=", frappe.utils.today())}),
                "new_this_week": frappe.db.count(
                    "Member", {"creation": (">=", add_to_date(frappe.utils.today(), days=-7))}
                ),
                "active_total": frappe.db.count("Member", {"status": "Active"}),
                "terminated_today": frappe.db.count(
                    "Member", {"status": "Terminated", "modified": (">=", frappe.utils.today())}
                ),
            }
        except:
            return {"new_today": 0, "new_this_week": 0, "active_total": 0, "terminated_today": 0}

    def get_sepa_health_metrics(self):
        """Get SEPA system health metrics"""
        try:
            return {
                "active_mandates": frappe.db.count("SEPA Mandate", {"status": "Active"}),
                "failed_mandates_today": frappe.db.count(
                    "SEPA Mandate", {"status": "Failed", "creation": (">=", frappe.utils.today())}
                ),
                "recent_batches": frappe.db.count(
                    "Direct Debit Batch", {"creation": (">=", add_to_date(now(), days=-7))}
                ),
                "pending_payments": frappe.db.count(
                    "Payment Entry", {"docstatus": 0, "payment_type": "Receive"}
                ),
            }
        except:
            return {
                "active_mandates": 0,
                "failed_mandates_today": 0,
                "recent_batches": 0,
                "pending_payments": 0,
            }

    def get_application_metrics_business(self):
        """Get membership application pipeline metrics"""
        try:
            return {
                "pending_review": frappe.db.count(
                    "Membership Application", {"workflow_state": "Pending Review"}
                ),
                "approved_today": frappe.db.count(
                    "Membership Application",
                    {"workflow_state": "Approved", "modified": (">=", frappe.utils.today())},
                ),
                "rejected_today": frappe.db.count(
                    "Membership Application",
                    {"workflow_state": "Rejected", "modified": (">=", frappe.utils.today())},
                ),
                "stalled_applications": frappe.db.count(
                    "Membership Application",
                    {"workflow_state": "Pending Review", "creation": ("<=", add_to_date(now(), days=-7))},
                ),
            }
        except:
            return {"pending_review": 0, "approved_today": 0, "rejected_today": 0, "stalled_applications": 0}

    def check_resource_thresholds(self):
        """Check if any resource thresholds are exceeded"""
        try:
            metrics = self.collect_system_metrics()
            alerts = []

            # Check system resources if available
            if "system" in metrics and "error" not in metrics["system"]:
                system = metrics["system"]

                if system.get("cpu_percent", 0) > self.thresholds["cpu_percent"]:
                    alerts.append(
                        {
                            "type": "HIGH_CPU",
                            "severity": "HIGH",
                            "message": f"CPU usage: {system['cpu_percent']}%",
                            "details": system,
                        }
                    )

                if system.get("memory_percent", 0) > self.thresholds["memory_percent"]:
                    alerts.append(
                        {
                            "type": "HIGH_MEMORY",
                            "severity": "HIGH",
                            "message": f"Memory usage: {system['memory_percent']}%",
                            "details": system,
                        }
                    )

                if system.get("disk_usage_percent", 0) > self.thresholds["disk_percent"]:
                    alerts.append(
                        {
                            "type": "HIGH_DISK",
                            "severity": "CRITICAL",
                            "message": f"Disk usage: {system['disk_usage_percent']}%",
                            "details": system,
                        }
                    )

            # Check database metrics
            if "database" in metrics and "error" not in metrics["database"]:
                db = metrics["database"]

                if db.get("active_connections", 0) > self.thresholds["active_connections"]:
                    alerts.append(
                        {
                            "type": "HIGH_DB_CONNECTIONS",
                            "severity": "MEDIUM",
                            "message": f"High database connections: {db['active_connections']}",
                            "details": db,
                        }
                    )

                if db.get("recent_errors", 0) > self.thresholds["error_rate_threshold"]:
                    alerts.append(
                        {
                            "type": "HIGH_ERROR_RATE",
                            "severity": "HIGH",
                            "message": f"High error rate: {db['recent_errors']} errors in last hour",
                            "details": db,
                        }
                    )

            # Check application metrics
            if "application" in metrics and "error" not in metrics["application"]:
                app = metrics["application"]

                if isinstance(app.get("background_jobs"), dict):
                    queued = app["background_jobs"].get("queued", 0)
                    if queued > self.thresholds["queue_length"]:
                        alerts.append(
                            {
                                "type": "HIGH_JOB_QUEUE",
                                "severity": "MEDIUM",
                                "message": f"High background job queue: {queued} jobs",
                                "details": app["background_jobs"],
                            }
                        )

                # Check scheduler health
                scheduler = app.get("scheduler_status", {})
                if scheduler.get("status") == "warning":
                    alerts.append(
                        {
                            "type": "SCHEDULER_ISSUES",
                            "severity": "MEDIUM",
                            "message": "Scheduler may not be running properly",
                            "details": scheduler,
                        }
                    )

            return alerts

        except Exception as e:
            frappe.log_error(f"Error checking resource thresholds: {str(e)}")
            return []

    def generate_performance_report(self):
        """Generate a comprehensive performance report"""
        try:
            metrics = self.collect_system_metrics()
            alerts = self.check_resource_thresholds()

            report = {
                "timestamp": now(),
                "summary": {
                    "overall_health": "healthy"
                    if len(alerts) == 0
                    else "warning"
                    if len([a for a in alerts if a["severity"] in ["HIGH", "CRITICAL"]]) == 0
                    else "critical",
                    "active_alerts": len(alerts),
                    "critical_alerts": len([a for a in alerts if a["severity"] == "CRITICAL"]),
                    "high_alerts": len([a for a in alerts if a["severity"] == "HIGH"]),
                },
                "metrics": metrics,
                "alerts": alerts,
                "recommendations": self.generate_recommendations(metrics, alerts),
            }

            return report

        except Exception as e:
            frappe.log_error(f"Error generating performance report: {str(e)}")
            return {"error": str(e), "timestamp": now()}

    def generate_recommendations(self, metrics, alerts):
        """Generate recommendations based on metrics and alerts"""
        recommendations = []

        try:
            # System resource recommendations
            if any(alert["type"] == "HIGH_MEMORY" for alert in alerts):
                recommendations.append(
                    {
                        "category": "system",
                        "priority": "high",
                        "title": "High Memory Usage",
                        "description": "Consider restarting services or investigating memory leaks",
                        "action": "Monitor memory usage patterns and consider scaling",
                    }
                )

            if any(alert["type"] == "HIGH_CPU" for alert in alerts):
                recommendations.append(
                    {
                        "category": "system",
                        "priority": "high",
                        "title": "High CPU Usage",
                        "description": "Check for runaway processes or high load operations",
                        "action": "Review recent operations and consider load balancing",
                    }
                )

            # Database recommendations
            if any(alert["type"] == "HIGH_DB_CONNECTIONS" for alert in alerts):
                recommendations.append(
                    {
                        "category": "database",
                        "priority": "medium",
                        "title": "High Database Connections",
                        "description": "Monitor connection pooling and query efficiency",
                        "action": "Review database connection settings and optimize queries",
                    }
                )

            # Application recommendations
            if any(alert["type"] == "HIGH_JOB_QUEUE" for alert in alerts):
                recommendations.append(
                    {
                        "category": "application",
                        "priority": "medium",
                        "title": "High Background Job Queue",
                        "description": "Background jobs are accumulating",
                        "action": "Check job processing and consider scaling workers",
                    }
                )

            # Business process recommendations
            business = metrics.get("business", {})
            if isinstance(business, dict) and "application_pipeline" in business:
                pipeline = business["application_pipeline"]
                if pipeline.get("stalled_applications", 0) > 5:
                    recommendations.append(
                        {
                            "category": "business",
                            "priority": "medium",
                            "title": "Stalled Membership Applications",
                            "description": f"{pipeline['stalled_applications']} applications pending review for over 7 days",
                            "action": "Review and process pending membership applications",
                        }
                    )

        except Exception as e:
            frappe.log_error(f"Error generating recommendations: {str(e)}")

        return recommendations


@frappe.whitelist()
def get_system_health():
    """Get overall system health status"""
    try:
        monitor = ResourceMonitor()
        metrics = monitor.collect_system_metrics()
        alerts = monitor.check_resource_thresholds()

        return {
            "status": "healthy"
            if len(alerts) == 0
            else "warning"
            if len([a for a in alerts if a["severity"] in ["HIGH", "CRITICAL"]]) == 0
            else "critical",
            "metrics": metrics,
            "alerts": alerts,
            "timestamp": now(),
        }
    except Exception as e:
        frappe.log_error(f"Error getting system health: {str(e)}")
        return {"status": "error", "error": str(e), "timestamp": now()}


@frappe.whitelist()
def get_performance_report():
    """Get comprehensive performance report"""
    try:
        monitor = ResourceMonitor()
        return monitor.generate_performance_report()
    except Exception as e:
        frappe.log_error(f"Error getting performance report: {str(e)}")
        return {"error": str(e), "timestamp": now()}
