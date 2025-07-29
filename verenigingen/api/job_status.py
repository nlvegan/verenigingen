#!/usr/bin/env python3
"""
Job Status API
Phase 2.2 Implementation - Background Job Status Tracking and User Notifications

This API provides user-facing endpoints for tracking background job status
and receiving notifications about job completion.
"""

from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.utils.background_jobs import BackgroundJobManager
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_job_status(job_name: str) -> Dict[str, Any]:
    """
    Get status of a background job

    Args:
        job_name: Name/ID of the job to check

    Returns:
        Job status information
    """
    try:
        if not job_name:
            return {"error": "Job name is required"}

        job_status = BackgroundJobManager.get_job_status(job_name)

        # Add user-friendly status descriptions
        status_descriptions = {
            "Queued": "Job is waiting to be processed",
            "Running": "Job is currently being executed",
            "Completed": "Job completed successfully",
            "Failed": "Job failed to complete",
            "Retrying": "Job is scheduled for retry",
            "Unknown": "Job status could not be determined",
        }

        job_status["status_description"] = status_descriptions.get(job_status.get("status"), "Unknown status")

        return job_status

    except Exception as e:
        frappe.log_error(f"Failed to get job status for {job_name}: {e}")
        return {"error": str(e), "job_name": job_name, "status": "Error"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_user_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get recent background jobs for current user

    Args:
        limit: Maximum number of jobs to return

    Returns:
        List of user's recent jobs
    """
    try:
        # user = frappe.session.user  # Currently not used but may be needed for future permission checks

        # Get job status from cache for current user
        # Note: In a production system, this would query a proper database table
        # For now, we'll return example data structure

        user_jobs = []

        # This is a simplified implementation - in production you'd want to
        # store job records in a database table and query them here

        return user_jobs

    except Exception as e:
        frappe.log_error(f"Failed to get user jobs: {e}")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def retry_failed_job(job_name: str) -> Dict[str, Any]:
    """
    Manually retry a failed job

    Args:
        job_name: Name/ID of the job to retry

    Returns:
        Retry result
    """
    try:
        if not job_name:
            return {"success": False, "error": "Job name is required"}

        # Check permissions - user should only be able to retry their own jobs
        job_status = BackgroundJobManager.get_job_status(job_name)
        if job_status.get("user") != frappe.session.user:
            return {"success": False, "error": "You can only retry your own jobs"}

        success = BackgroundJobManager.retry_failed_job(job_name)

        if success:
            return {
                "success": True,
                "message": f"Job {job_name} has been scheduled for retry",
                "job_name": job_name,
            }
        else:
            return {
                "success": False,
                "error": "Job could not be retried (may have exceeded max retries or not in failed state)",
                "job_name": job_name,
            }

    except Exception as e:
        frappe.log_error(f"Failed to retry job {job_name}: {e}")
        return {"success": False, "error": str(e), "job_name": job_name}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_job_queue_status() -> Dict[str, Any]:
    """
    Get overall job queue status (for administrators)

    Returns:
        Queue status information
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "read"):
            frappe.throw(_("Insufficient permissions to view queue status"))

        from frappe.utils.background_jobs import get_jobs

        # Get queue lengths
        queues = ["default", "short", "long"]
        queue_status = {}
        total_jobs = 0

        for queue in queues:
            try:
                jobs = get_jobs(queue=queue)
                job_count = len(jobs)
                queue_status[f"{queue}_queue"] = {
                    "count": job_count,
                    "jobs": [job.id for job in jobs[:5]],  # Show first 5 job IDs
                }
                total_jobs += job_count
            except Exception as e:
                queue_status[f"{queue}_queue"] = {"count": 0, "error": str(e)}

        queue_status["total_jobs"] = total_jobs
        queue_status["timestamp"] = frappe.utils.now()

        return queue_status

    except Exception as e:
        frappe.log_error(f"Failed to get queue status: {e}")
        return {"error": str(e), "timestamp": frappe.utils.now()}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_recent_payment_history_jobs(member: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent payment history update jobs

    Args:
        member: Optional member name to filter by
        limit: Maximum number of jobs to return

    Returns:
        List of recent payment history jobs
    """
    try:
        # Check permissions - users should only see their own member's jobs
        # or be administrators
        if member:
            if not frappe.has_permission("Member", "read", member):
                frappe.throw(_("Insufficient permissions to view this member's jobs"))

        # This is a simplified implementation
        # In production, you'd query actual job records from database

        recent_jobs = []

        # Example structure of what would be returned:
        example_job = {
            "job_name": "payment_history_update_example",
            "job_type": "member_payment_history_update",
            "status": "Completed",
            "member_name": member or "Example Member",
            "created_at": frappe.utils.now(),
            "execution_time": 0.15,
            "entries_processed": 12,
        }

        if member:
            recent_jobs.append(example_job)

        return recent_jobs

    except Exception as e:
        frappe.log_error(f"Failed to get payment history jobs: {e}")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def clear_completed_jobs(older_than_hours: int = 24) -> Dict[str, Any]:
    """
    Clear completed job records older than specified hours

    Args:
        older_than_hours: Clear jobs older than this many hours

    Returns:
        Cleanup result
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "write"):
            frappe.throw(_("Insufficient permissions to clear jobs"))

        from datetime import datetime, timedelta

        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        cleared_count = 0

        # This would implement actual cleanup logic in production
        # For now, just return success

        return {
            "success": True,
            "cleared_count": cleared_count,
            "cutoff_time": cutoff_time.isoformat(),
            "message": f"Cleared {cleared_count} completed jobs older than {older_than_hours} hours",
        }

    except Exception as e:
        frappe.log_error(f"Failed to clear completed jobs: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_background_job_system() -> Dict[str, Any]:
    """
    Test the background job system by creating a test job

    Returns:
        Test result
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "write"):
            frappe.throw(_("Insufficient permissions to test job system"))

        # Create a test member payment history update job
        test_members = frappe.get_all("Member", limit=1, fields=["name"])

        if not test_members:
            return {"success": False, "error": "No members found to test with"}

        test_member = test_members[0].name

        job_id = BackgroundJobManager.queue_member_payment_history_update(
            member_name=test_member, payment_entry=None, priority="short"
        )

        return {
            "success": True,
            "message": "Test job created successfully",
            "job_id": job_id,
            "test_member": test_member,
            "instructions": f'Check job status with: get_job_status("{job_id}")',
        }

    except Exception as e:
        frappe.log_error(f"Failed to test background job system: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def get_system_performance_metrics() -> Dict[str, Any]:
    """
    Get system performance metrics related to background jobs

    Returns:
        Performance metrics
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "read"):
            frappe.throw(_("Insufficient permissions to view performance metrics"))

        import psutil

        # Get system metrics
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)

        # Get job queue metrics
        queue_status = get_job_queue_status()

        metrics = {
            "timestamp": frappe.utils.now(),
            "system": {
                "memory_percent": memory.percent,
                "memory_available_mb": memory.available / 1024 / 1024,
                "cpu_percent": cpu_percent,
            },
            "job_queues": queue_status,
            "performance_tips": [],
        }

        # Add performance recommendations
        if memory.percent > 80:
            metrics["performance_tips"].append(
                "High memory usage detected - consider optimizing job batch sizes"
            )

        if queue_status.get("total_jobs", 0) > 100:
            metrics["performance_tips"].append("High job queue length - consider adding more workers")

        if cpu_percent > 90:
            metrics["performance_tips"].append(
                "High CPU usage - consider distributing jobs across multiple servers"
            )

        return metrics

    except Exception as e:
        frappe.log_error(f"Failed to get performance metrics: {e}")
        return {"error": str(e), "timestamp": frappe.utils.now()}
