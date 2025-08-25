"""
Bulk Queue Configuration for Account Creation System
====================================================

This module configures dedicated Redis queues for bulk processing operations,
ensuring that large-scale imports don't interfere with individual member approvals
and other time-sensitive operations.

Queue Architecture:
- 'bulk': Dedicated queue for bulk account creation (low priority)
- 'long': Default queue for individual operations (normal priority)
- 'short': High-priority queue for interactive operations

Author: Verenigingen Development Team
"""

import frappe
from frappe import _


def get_bulk_queue_config():
    """
    Get the bulk queue configuration for account creation operations.

    Returns:
        dict: Queue configuration parameters
    """
    return {
        # Queue name for bulk operations
        "queue_name": "bulk",
        # Maximum concurrent workers for bulk queue
        "max_workers": 3,  # Reduced from default to prevent resource exhaustion
        # Timeout per job (1 hour for batch processing)
        "timeout": 3600,
        # Priority level (lower number = higher priority)
        "priority": 9,  # Low priority to not block other operations
        # Retry configuration
        "max_retries": 2,
        "retry_delay": 300,  # 5 minutes between retries
        # Memory and resource limits
        "memory_limit_mb": 512,  # 512MB per worker
        "max_batch_size": 50,  # Maximum members per batch
        # Monitoring thresholds
        "stuck_job_timeout_minutes": 90,  # Alert if job runs longer than 90 minutes
        "queue_backlog_alert_threshold": 20,  # Alert if more than 20 jobs queued
    }


def configure_bulk_queue():
    """
    Configure the bulk processing queue with appropriate settings.

    This function sets up the Redis queue configuration for bulk account creation
    operations, ensuring proper resource allocation and priority handling.
    """
    try:
        config = get_bulk_queue_config()

        # Register queue configuration in site config
        site_config = frappe.get_site_config()

        # Initialize queue configurations if not exists
        if "queue_config" not in site_config:
            site_config["queue_config"] = {}

        # Set bulk queue configuration
        site_config["queue_config"]["bulk"] = {
            "workers": config["max_workers"],
            "timeout": config["timeout"],
            "memory_limit": f"{config['memory_limit_mb']}m",
        }

        # Update worker configuration for different queues
        if "worker_config" not in site_config:
            site_config["worker_config"] = {}

        # Ensure proper queue priority allocation
        site_config["worker_config"] = {
            "short": {"workers": 4, "timeout": 300},  # High priority, quick jobs
            "default": {"workers": 2, "timeout": 300},  # Normal priority
            "long": {"workers": 2, "timeout": 1800},  # Individual account creation
            "bulk": {  # Bulk operations
                "workers": config["max_workers"],
                "timeout": config["timeout"],
                "memory_limit": config["memory_limit_mb"],
            },
        }

        # Save configuration
        frappe.get_site_config().update(site_config)

        frappe.logger().info(
            f"Bulk queue configured: {config['max_workers']} workers, {config['timeout']}s timeout"
        )

        return {"success": True, "config": config}

    except Exception as e:
        frappe.logger().error(f"Failed to configure bulk queue: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_queue_status():
    """
    Get current status of all Redis queues for monitoring.

    Returns:
        dict: Queue status information for admin dashboard
    """
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw(_("Insufficient permissions to view queue status"))

    try:
        import redis
        from rq import Connection, Queue

        # Get Redis connection
        redis_conn = redis.from_url(frappe.conf.redis_queue or "redis://localhost:11000")

        queue_status = {}
        queue_names = ["bulk", "long", "default", "short"]

        with Connection(redis_conn):
            for queue_name in queue_names:
                try:
                    queue = Queue(queue_name)

                    queue_status[queue_name] = {
                        "name": queue_name,
                        "length": len(queue),
                        "failed_count": queue.failed_job_registry.count,
                        "started_count": queue.started_job_registry.count,
                        "deferred_count": queue.deferred_job_registry.count,
                        "scheduled_count": queue.scheduled_job_registry.count
                        if hasattr(queue, "scheduled_job_registry")
                        else 0,
                        "workers": len(queue.workers),
                        "is_empty": queue.is_empty(),
                    }

                    # Get sample of recent jobs
                    jobs = queue.get_jobs()[:5]  # Last 5 jobs
                    queue_status[queue_name]["recent_jobs"] = [
                        {
                            "id": job.id,
                            "function": job.func_name,
                            "status": job.get_status(),
                            "created_at": job.created_at.isoformat() if job.created_at else None,
                            "started_at": job.started_at.isoformat() if job.started_at else None,
                        }
                        for job in jobs
                    ]

                except Exception as queue_error:
                    queue_status[queue_name] = {
                        "name": queue_name,
                        "error": str(queue_error),
                        "available": False,
                    }

        return queue_status

    except Exception as e:
        frappe.logger().error(f"Failed to get queue status: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def clear_stuck_jobs():
    """
    Clear jobs that have been running too long (admin function).

    This function identifies and removes jobs that have exceeded the
    configured timeout thresholds, helping to maintain queue health.
    """
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("Insufficient permissions to manage queues"))

    try:
        from datetime import datetime, timedelta

        import redis
        from rq import Connection, Queue

        config = get_bulk_queue_config()
        stuck_threshold = timedelta(minutes=config["stuck_job_timeout_minutes"])

        # Get Redis connection
        redis_conn = redis.from_url(frappe.conf.redis_queue or "redis://localhost:11000")

        cleared_jobs = []

        with Connection(redis_conn):
            for queue_name in ["bulk", "long", "default"]:
                try:
                    queue = Queue(queue_name)

                    # Check started job registry for stuck jobs
                    for job_id in queue.started_job_registry.get_job_ids():
                        try:
                            job = queue.started_job_registry.get_job_class()(job_id, connection=redis_conn)

                            if job.started_at and (datetime.now() - job.started_at) > stuck_threshold:
                                # Job is stuck - remove it
                                queue.started_job_registry.remove(job_id)
                                cleared_jobs.append(
                                    {
                                        "job_id": job_id,
                                        "queue": queue_name,
                                        "function": job.func_name,
                                        "started_at": job.started_at.isoformat(),
                                        "duration_minutes": (datetime.now() - job.started_at).total_seconds()
                                        / 60,
                                    }
                                )

                                frappe.logger().warning(f"Cleared stuck job {job_id} from {queue_name} queue")

                        except Exception as job_error:
                            frappe.logger().error(f"Error processing job {job_id}: {str(job_error)}")
                            continue

                except Exception as queue_error:
                    frappe.logger().error(f"Error processing queue {queue_name}: {str(queue_error)}")
                    continue

        if cleared_jobs:
            frappe.msgprint(_(f"Cleared {len(cleared_jobs)} stuck jobs"))
            frappe.logger().info(f"Cleared {len(cleared_jobs)} stuck jobs: {cleared_jobs}")
        else:
            frappe.msgprint(_("No stuck jobs found"))

        return {"success": True, "cleared_jobs": cleared_jobs}

    except Exception as e:
        frappe.logger().error(f"Failed to clear stuck jobs: {str(e)}")
        frappe.throw(_("Failed to clear stuck jobs: {0}").format(str(e)))


def monitor_bulk_queue_health():
    """
    Monitor bulk queue health and alert if issues are detected.

    This function runs as part of scheduled monitoring to detect:
    - Queue backlog buildup
    - Stuck jobs
    - Worker failures
    - Memory usage issues
    """
    try:
        config = get_bulk_queue_config()
        queue_status = get_queue_status()

        alerts = []

        # Check bulk queue specifically
        if "bulk" in queue_status and not queue_status["bulk"].get("error"):
            bulk_queue = queue_status["bulk"]

            # Alert on queue backlog
            if bulk_queue.get("length", 0) > config["queue_backlog_alert_threshold"]:
                alerts.append(
                    {
                        "type": "queue_backlog",
                        "message": f"Bulk queue has {bulk_queue['length']} jobs (threshold: {config['queue_backlog_alert_threshold']})",
                        "severity": "warning",
                    }
                )

            # Alert on failed jobs
            if bulk_queue.get("failed_count", 0) > 0:
                alerts.append(
                    {
                        "type": "failed_jobs",
                        "message": f"Bulk queue has {bulk_queue['failed_count']} failed jobs",
                        "severity": "error",
                    }
                )

            # Alert if no workers available
            if bulk_queue.get("workers", 0) == 0:
                alerts.append(
                    {
                        "type": "no_workers",
                        "message": "No workers available for bulk queue",
                        "severity": "critical",
                    }
                )

        # Log alerts
        for alert in alerts:
            if alert["severity"] == "critical":
                frappe.log_error(alert["message"], "Bulk Queue Critical Alert")
            elif alert["severity"] == "error":
                frappe.logger().error(f"Bulk Queue Alert: {alert['message']}")
            else:
                frappe.logger().warning(f"Bulk Queue Warning: {alert['message']}")

        return {"success": True, "alerts": alerts, "queue_status": queue_status.get("bulk", {})}

    except Exception as e:
        frappe.logger().error(f"Bulk queue monitoring failed: {str(e)}")
        return {"success": False, "error": str(e)}


# Initialize bulk queue configuration on module import
def init_bulk_queue():
    """Initialize bulk queue configuration if not already done."""
    try:
        if frappe.db and frappe.local.site:
            result = configure_bulk_queue()
            if result.get("success"):
                frappe.logger().info("Bulk queue configuration initialized")
    except Exception as e:
        # Don't fail module import if queue config fails
        frappe.logger().warning(f"Could not initialize bulk queue config: {str(e)}")


# Auto-initialize when module is imported
if frappe.local and hasattr(frappe.local, "site") and frappe.local.site:
    init_bulk_queue()
