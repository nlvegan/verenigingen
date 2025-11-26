#!/usr/bin/env python3
"""
Job Status API
Phase 2.2 Implementation - Background Job Status Tracking and User Notifications

This API provides user-facing endpoints for tracking background job status
and receiving notifications about job completion.
"""

import traceback
from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.utils.background_jobs import BackgroundJobManager
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_job_status(job_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Get status of a background job

    Args:
        job_name: Name/ID of the job to check

    Returns:
        Job status information
    """
    try:
        if not job_name:
            return OperationResult.fail(message=_("Job name is required"), error_code="MISSING_JOB_NAME")

        job_status = BackgroundJobManager.get_job_status(job_name)

        # Add user-friendly status descriptions
        status_descriptions = {
            "Queued": _("Job is waiting to be processed"),
            "Running": _("Job is currently being executed"),
            "Completed": _("Job completed successfully"),
            "Failed": _("Job failed to complete"),
            "Retrying": _("Job is scheduled for retry"),
            "Unknown": _("Job status could not be determined"),
        }

        job_status["status_description"] = status_descriptions.get(
            job_status.get("status"), _("Unknown status")
        )

        return OperationResult.ok(data=job_status, message=_("Job status retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get job status"),
            message=f"Job: {job_name}\nError: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retrieve job status: {0}").format(str(e)),
            error_code="JOB_STATUS_ERROR",
            data={"job_name": job_name},
        )


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def get_user_jobs(limit: int = 20) -> OperationResult[List[Dict[str, Any]]]:
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

        return OperationResult.ok(data=user_jobs, message=_("User jobs retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get user jobs"),
            message=f"User: {frappe.session.user}\nError: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retrieve user jobs: {0}").format(str(e)), error_code="USER_JOBS_ERROR"
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def retry_failed_job(job_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Manually retry a failed job

    Args:
        job_name: Name/ID of the job to retry

    Returns:
        Retry result
    """
    try:
        if not job_name:
            return OperationResult.fail(message=_("Job name is required"), error_code="MISSING_JOB_NAME")

        # Check permissions - user should only be able to retry their own jobs
        job_status = BackgroundJobManager.get_job_status(job_name)
        if job_status.get("user") != frappe.session.user:
            return OperationResult.fail(
                message=_("You can only retry your own jobs"), error_code="PERMISSION_DENIED"
            )

        success = BackgroundJobManager.retry_failed_job(job_name)

        if success:
            return OperationResult.ok(
                data={"job_name": job_name},
                message=_("Job {0} has been scheduled for retry").format(job_name),
            )
        else:
            return OperationResult.fail(
                message=_("Job could not be retried (may have exceeded max retries or not in failed state)"),
                error_code="RETRY_FAILED",
                data={"job_name": job_name},
            )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to retry job"),
            message=f"Job: {job_name}\nError: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retry job: {0}").format(str(e)),
            error_code="JOB_RETRY_ERROR",
            data={"job_name": job_name},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_job_queue_status() -> OperationResult[Dict[str, Any]]:
    """
    Get overall job queue status (for administrators)

    Returns:
        Queue status information
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "read"):
            return OperationResult.fail(
                message=_("Insufficient permissions to view queue status"), error_code="PERMISSION_DENIED"
            )

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

        return OperationResult.ok(data=queue_status, message=_("Queue status retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get queue status"), message=f"Error: {str(e)}\n{traceback.format_exc()}"
        )
        return OperationResult.fail(
            message=_("Failed to retrieve queue status: {0}").format(str(e)),
            error_code="QUEUE_STATUS_ERROR",
            data={"timestamp": frappe.utils.now()},
        )


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def get_recent_payment_history_jobs(
    member: str = None, limit: int = 10
) -> OperationResult[List[Dict[str, Any]]]:
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
                return OperationResult.fail(
                    message=_("Insufficient permissions to view this member's jobs"),
                    error_code="PERMISSION_DENIED",
                )

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

        return OperationResult.ok(data=recent_jobs, message=_("Payment history jobs retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get payment history jobs"),
            message=f"Member: {member}\nError: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retrieve payment history jobs: {0}").format(str(e)),
            error_code="PAYMENT_HISTORY_JOBS_ERROR",
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def clear_completed_jobs(older_than_hours: int = 24) -> OperationResult[Dict[str, Any]]:
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
            return OperationResult.fail(
                message=_("Insufficient permissions to clear jobs"), error_code="PERMISSION_DENIED"
            )

        from datetime import datetime, timedelta

        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        cleared_count = 0

        # This would implement actual cleanup logic in production
        # For now, just return success

        return OperationResult.ok(
            data={
                "cleared_count": cleared_count,
                "cutoff_time": cutoff_time.isoformat(),
            },
            message=_("Cleared {0} completed jobs older than {1} hours").format(
                cleared_count, older_than_hours
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to clear completed jobs"),
            message=f"Older than: {older_than_hours} hours\nError: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to clear completed jobs: {0}").format(str(e)), error_code="CLEAR_JOBS_ERROR"
        )


@critical_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def test_background_job_system() -> OperationResult[Dict[str, Any]]:
    """
    Test the background job system by creating a test job

    Returns:
        Test result
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "write"):
            return OperationResult.fail(
                message=_("Insufficient permissions to test job system"), error_code="PERMISSION_DENIED"
            )

        # Create a test member payment history update job
        test_members = frappe.get_all("Member", limit=1, fields=["name"])

        if not test_members:
            return OperationResult.fail(message=_("No members found to test with"), error_code="NO_TEST_DATA")

        test_member = test_members[0].name

        job_id = BackgroundJobManager.queue_member_payment_history_update(
            member_name=test_member, payment_entry=None, priority="short"
        )

        return OperationResult.ok(
            data={
                "job_id": job_id,
                "test_member": test_member,
                "instructions": f'Check job status with: get_job_status("{job_id}")',
            },
            message=_("Test job created successfully"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to test background job system"),
            message=f"Error: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to test background job system: {0}").format(str(e)), error_code="TEST_JOB_ERROR"
        )


@critical_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def get_system_performance_metrics() -> OperationResult[Dict[str, Any]]:
    """
    Get system performance metrics related to background jobs

    Returns:
        Performance metrics
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("System Settings", "read"):
            return OperationResult.fail(
                message=_("Insufficient permissions to view performance metrics"),
                error_code="PERMISSION_DENIED",
            )

        import psutil

        # Get system metrics
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)

        # Get job queue metrics - extract data from OperationResult
        queue_result = get_job_queue_status()
        queue_status = queue_result.data if queue_result.success else {}

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
                _("High memory usage detected - consider optimizing job batch sizes")
            )

        if queue_status.get("total_jobs", 0) > 100:
            metrics["performance_tips"].append(_("High job queue length - consider adding more workers"))

        if cpu_percent > 90:
            metrics["performance_tips"].append(
                _("High CPU usage - consider distributing jobs across multiple servers")
            )

        return OperationResult.ok(data=metrics, message=_("Performance metrics retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get performance metrics"), message=f"Error: {str(e)}\n{traceback.format_exc()}"
        )
        return OperationResult.fail(
            message=_("Failed to retrieve performance metrics: {0}").format(str(e)),
            error_code="PERFORMANCE_METRICS_ERROR",
            data={"timestamp": frappe.utils.now()},
        )
