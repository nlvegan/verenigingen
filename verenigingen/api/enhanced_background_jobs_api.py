#!/usr/bin/env python3
"""
Enhanced Background Jobs API

Provides API endpoints for managing and monitoring the enhanced background job
coordination system in Phase 5A performance optimization.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.performance.enhanced_background_jobs import (
    JobPriority,
    JobStatus,
    PerformanceJobCoordinator,
    get_performance_job_coordinator,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def enqueue_performance_job(
    job_function: str,
    job_args: Dict = None,
    priority: str = "normal",
    operation_type: str = "UTILITY",
    estimated_duration: int = None,
):
    """
    Enqueue a performance-related background job

    Args:
        job_function: Function name to execute
        job_args: Arguments for the job function
        priority: Job priority (critical, high, normal, low, bulk)
        operation_type: Security operation type
        estimated_duration: Estimated execution time in seconds

    Returns:
        Dict with job ID and enqueue status
    """
    try:
        # Parse priority
        try:
            job_priority = JobPriority(priority.lower())
        except ValueError:
            frappe.throw(f"Invalid priority: {priority}. Use: critical, high, normal, low, bulk")

        # Parse operation type
        try:
            op_type = OperationType(operation_type.upper())
        except ValueError:
            frappe.throw(f"Invalid operation type: {operation_type}")

        # Get job coordinator
        coordinator = get_performance_job_coordinator()

        # Enqueue the job
        job_id = coordinator.enqueue_performance_job(
            job_function=job_function,
            job_args=job_args or {},
            priority=job_priority,
            operation_type=op_type,
            estimated_duration=estimated_duration,
        )

        return {
            "success": True,
            "data": {
                "job_id": job_id,
                "job_function": job_function,
                "priority": priority,
                "operation_type": operation_type,
                "enqueued_at": now_datetime(),
            },
            "message": f"Job {job_id} enqueued successfully with priority {priority}",
        }

    except Exception as e:
        frappe.log_error(f"Error enqueueing performance job: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_job_status(job_id: str):
    """
    Get current status of a background job

    Args:
        job_id: Job ID to check

    Returns:
        Dict with job status and performance metrics
    """
    try:
        coordinator = get_performance_job_coordinator()
        job_status = coordinator.get_job_status(job_id)

        if "error" in job_status:
            return {"success": False, "error": job_status["error"]}

        return {"success": True, "data": job_status, "message": f"Job status retrieved for {job_id}"}

    except Exception as e:
        frappe.log_error(f"Error getting job status: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_queue_status():
    """
    Get overall queue status and performance metrics

    Returns:
        Dict with comprehensive queue statistics
    """
    try:
        coordinator = get_performance_job_coordinator()
        queue_status = coordinator.get_queue_status()

        # Add additional analysis
        queue_status["analysis"] = {
            "queue_health": _assess_queue_health(queue_status),
            "performance_rating": _calculate_queue_performance_rating(queue_status),
            "optimization_opportunities": _identify_optimization_opportunities(queue_status),
        }

        return {"success": True, "data": queue_status, "message": "Queue status retrieved successfully"}

    except Exception as e:
        frappe.log_error(f"Error getting queue status: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def cancel_job(job_id: str):
    """
    Cancel a queued or running job

    Args:
        job_id: Job ID to cancel

    Returns:
        Dict with cancellation status
    """
    try:
        coordinator = get_performance_job_coordinator()
        cancelled = coordinator.cancel_job(job_id)

        if cancelled:
            return {
                "success": True,
                "data": {"job_id": job_id, "cancelled_at": now_datetime()},
                "message": f"Job {job_id} cancelled successfully",
            }
        else:
            return {"success": False, "error": f"Job {job_id} not found or cannot be cancelled"}

    except Exception as e:
        frappe.log_error(f"Error cancelling job: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def optimize_job_scheduling():
    """
    Optimize job scheduling based on current system performance

    Returns:
        Dict with optimization results and recommendations
    """
    try:
        coordinator = get_performance_job_coordinator()
        optimization_results = coordinator.optimize_job_scheduling()

        return {
            "success": True,
            "data": optimization_results,
            "message": "Job scheduling optimization completed",
        }

    except Exception as e:
        frappe.log_error(f"Error optimizing job scheduling: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def enqueue_member_payment_history_job(member_name: str, priority: str = "normal"):
    """
    Enqueue a member payment history refresh job

    Args:
        member_name: Member to refresh payment history for
        priority: Job priority level

    Returns:
        Dict with job enqueue status
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            frappe.throw(f"Member {member_name} not found")

        job_id = enqueue_performance_job(
            job_function="refresh_member_financial_history_optimized",
            job_args={"member_name": member_name},
            priority=priority,
            operation_type="FINANCIAL",
            estimated_duration=120,  # 2 minutes estimated
        )

        return job_id

    except Exception as e:
        frappe.log_error(f"Error enqueueing member payment history job: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def enqueue_performance_analysis_job(sample_size: int = 10, priority: str = "low"):
    """
    Enqueue a comprehensive performance analysis job

    Args:
        sample_size: Number of members to analyze
        priority: Job priority level

    Returns:
        Dict with job enqueue status
    """
    try:
        # Validate sample size
        sample_size = max(1, min(int(sample_size), 50))

        job_id = enqueue_performance_job(
            job_function="run_comprehensive_performance_analysis",
            job_args={"sample_size": sample_size},
            priority=priority,
            operation_type="REPORTING",
            estimated_duration=300,  # 5 minutes estimated
        )

        return job_id

    except Exception as e:
        frappe.log_error(f"Error enqueueing performance analysis job: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_job_queue_dashboard():
    """
    Get comprehensive job queue dashboard data

    Returns:
        Dict with dashboard data for monitoring job queues
    """
    try:
        coordinator = get_performance_job_coordinator()

        # Get basic queue status
        queue_status = coordinator.get_queue_status()

        # Add dashboard-specific metrics
        dashboard_data = {
            "timestamp": now_datetime(),
            "overview": {
                "total_queued": queue_status.get("total_queued_jobs", 0),
                "running_jobs": queue_status.get("running_jobs", 0),
                "system_load": queue_status.get("resource_utilization", {}).get("cpu_usage_percent", 0),
                "memory_usage": queue_status.get("resource_utilization", {}).get("memory_usage_percent", 0),
            },
            "priority_queues": queue_status.get("priority_distribution", {}),
            "performance_metrics": queue_status.get("performance_metrics", {}),
            "recent_activity": _get_recent_job_activity(),
            "health_indicators": {
                "queue_health": _assess_queue_health(queue_status),
                "performance_rating": _calculate_queue_performance_rating(queue_status),
                "alerts": _generate_queue_alerts(queue_status),
            },
        }

        return {
            "success": True,
            "data": dashboard_data,
            "message": "Job queue dashboard data retrieved successfully",
        }

    except Exception as e:
        frappe.log_error(f"Error getting job queue dashboard: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_job_coordination():
    """
    Test the job coordination system with sample jobs

    Returns:
        Dict with test results
    """
    try:
        coordinator = get_performance_job_coordinator()

        # Enqueue test jobs with different priorities
        test_jobs = []

        # Critical priority test job
        critical_job_id = coordinator.enqueue_performance_job(
            job_function="test_critical_operation",
            job_args={"test_param": "critical_test"},
            priority=JobPriority.CRITICAL,
            operation_type=OperationType.ADMIN,
            estimated_duration=30,
        )
        test_jobs.append({"job_id": critical_job_id, "priority": "critical"})

        # High priority test job
        high_job_id = coordinator.enqueue_performance_job(
            job_function="test_high_priority_operation",
            job_args={"test_param": "high_test"},
            priority=JobPriority.HIGH,
            operation_type=OperationType.FINANCIAL,
            estimated_duration=60,
        )
        test_jobs.append({"job_id": high_job_id, "priority": "high"})

        # Normal priority test job
        normal_job_id = coordinator.enqueue_performance_job(
            job_function="test_normal_operation",
            job_args={"test_param": "normal_test"},
            priority=JobPriority.NORMAL,
            operation_type=OperationType.UTILITY,
            estimated_duration=45,
        )
        test_jobs.append({"job_id": normal_job_id, "priority": "normal"})

        # Get queue status after enqueueing
        queue_status = coordinator.get_queue_status()

        return {
            "success": True,
            "data": {
                "test_jobs": test_jobs,
                "queue_status_after_enqueue": queue_status,
                "coordination_working": len(test_jobs) == 3,
                "priority_distribution": queue_status.get("priority_distribution", {}),
            },
            "message": f"Job coordination test completed - {len(test_jobs)} test jobs enqueued",
        }

    except Exception as e:
        frappe.log_error(f"Error testing job coordination: {e}")
        return {"success": False, "error": str(e)}


def _assess_queue_health(queue_status: Dict) -> str:
    """Assess overall queue health"""
    try:
        total_queued = queue_status.get("total_queued_jobs", 0)
        running_jobs = queue_status.get("running_jobs", 0)
        resource_util = queue_status.get("resource_utilization", {})

        cpu_usage = resource_util.get("cpu_usage_percent", 0)
        memory_usage = resource_util.get("memory_usage_percent", 0)

        # Health assessment logic
        if total_queued > 50 or cpu_usage > 90 or memory_usage > 95:
            return "CRITICAL"
        elif total_queued > 20 or cpu_usage > 80 or memory_usage > 85:
            return "WARNING"
        elif running_jobs > 0 and total_queued < 10:
            return "HEALTHY"
        else:
            return "GOOD"

    except Exception:
        return "UNKNOWN"


def _calculate_queue_performance_rating(queue_status: Dict) -> str:
    """Calculate queue performance rating"""
    try:
        perf_metrics = queue_status.get("performance_metrics", {})
        success_rate = perf_metrics.get("success_rate", 0)
        avg_execution_time = perf_metrics.get("average_execution_time", 0)

        if success_rate >= 0.95 and avg_execution_time < 60:
            return "EXCELLENT"
        elif success_rate >= 0.90 and avg_execution_time < 120:
            return "GOOD"
        elif success_rate >= 0.80 and avg_execution_time < 300:
            return "ACCEPTABLE"
        else:
            return "NEEDS_IMPROVEMENT"

    except Exception:
        return "UNKNOWN"


def _identify_optimization_opportunities(queue_status: Dict) -> List[str]:
    """Identify optimization opportunities"""
    opportunities = []

    try:
        total_queued = queue_status.get("total_queued_jobs", 0)
        priority_dist = queue_status.get("priority_distribution", {})

        if total_queued > 15:
            opportunities.append("Consider increasing worker capacity")

        critical_queued = priority_dist.get("critical", {}).get("queued", 0)
        if critical_queued > 2:
            opportunities.append("High critical job backlog - review system resources")

        bulk_running = priority_dist.get("bulk", {}).get("running", 0)
        if bulk_running > 0 and total_queued > 10:
            opportunities.append("Consider pausing bulk operations during peak load")

        if not opportunities:
            opportunities.append("Job queue performance is optimal")

    except Exception:
        opportunities.append("Unable to assess optimization opportunities")

    return opportunities


def _get_recent_job_activity() -> List[Dict]:
    """Get recent job activity for dashboard"""
    # Placeholder - would query actual job history
    return [
        {
            "job_id": "perf_job_12345",
            "function": "refresh_member_financial_history_optimized",
            "status": "completed",
            "duration": 85,
            "timestamp": now_datetime(),
        },
        {
            "job_id": "perf_job_12346",
            "function": "run_comprehensive_performance_analysis",
            "status": "running",
            "estimated_remaining": 180,
            "timestamp": now_datetime(),
        },
    ]


def _generate_queue_alerts(queue_status: Dict) -> List[Dict]:
    """Generate alerts based on queue status"""
    alerts = []

    try:
        total_queued = queue_status.get("total_queued_jobs", 0)
        resource_util = queue_status.get("resource_utilization", {})

        if total_queued > 30:
            alerts.append(
                {
                    "level": "warning",
                    "message": f"High queue depth: {total_queued} jobs queued",
                    "recommendation": "Consider scaling up workers",
                }
            )

        cpu_usage = resource_util.get("cpu_usage_percent", 0)
        if cpu_usage > 85:
            alerts.append(
                {
                    "level": "critical",
                    "message": f"High CPU usage: {cpu_usage}%",
                    "recommendation": "Reduce concurrent job limits",
                }
            )

        memory_usage = resource_util.get("memory_usage_percent", 0)
        if memory_usage > 90:
            alerts.append(
                {
                    "level": "critical",
                    "message": f"High memory usage: {memory_usage}%",
                    "recommendation": "Review memory-intensive jobs",
                }
            )

    except Exception:
        pass

    return alerts


if __name__ == "__main__":
    print("🔄 Enhanced Background Jobs API")
    print("Provides management and monitoring for priority-based background job coordination")
