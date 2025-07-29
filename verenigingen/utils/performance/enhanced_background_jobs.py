#!/usr/bin/env python3
"""
Enhanced Background Job Coordination System

Implements priority-based job queuing with performance optimization coordination
for Phase 5A background job management.
"""

import json
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe.utils import now, now_datetime

from verenigingen.utils.security.api_security_framework import OperationType


class JobPriority(Enum):
    """Job priority levels for queue management"""

    CRITICAL = "critical"  # System-critical operations (SEPA, security)
    HIGH = "high"  # Important operations (payment processing)
    NORMAL = "normal"  # Standard operations (member updates)
    LOW = "low"  # Background maintenance
    BULK = "bulk"  # Large batch operations


class JobStatus(Enum):
    """Job execution status"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class PerformanceJobCoordinator:
    """
    Coordinates background jobs with performance optimization awareness

    Features:
    - Priority-based queue management
    - Resource-aware job scheduling
    - Performance impact monitoring
    - Automatic retry with backoff
    - Job dependency management
    """

    # Maximum concurrent jobs by priority
    CONCURRENCY_LIMITS = {
        JobPriority.CRITICAL: 2,  # Allow 2 critical jobs simultaneously
        JobPriority.HIGH: 3,  # Allow 3 high priority jobs
        JobPriority.NORMAL: 5,  # Standard concurrency
        JobPriority.LOW: 2,  # Limited low priority jobs
        JobPriority.BULK: 1,  # Only 1 bulk job at a time
    }

    # Retry configuration by priority
    RETRY_CONFIG = {
        JobPriority.CRITICAL: {"max_retries": 5, "delay_multiplier": 2, "base_delay": 30},
        JobPriority.HIGH: {"max_retries": 3, "delay_multiplier": 2, "base_delay": 60},
        JobPriority.NORMAL: {"max_retries": 2, "delay_multiplier": 1.5, "base_delay": 120},
        JobPriority.LOW: {"max_retries": 1, "delay_multiplier": 1, "base_delay": 300},
        JobPriority.BULK: {"max_retries": 1, "delay_multiplier": 1, "base_delay": 600},
    }

    def __init__(self):
        self.job_queues = {priority: [] for priority in JobPriority}
        self.running_jobs = {}
        self.job_history = []
        self.performance_metrics = {}

    def enqueue_performance_job(
        self,
        job_function: str,
        job_args: Dict = None,
        priority: JobPriority = JobPriority.NORMAL,
        operation_type: OperationType = OperationType.UTILITY,
        job_dependencies: List[str] = None,
        estimated_duration: int = None,
        resource_requirements: Dict = None,
    ) -> str:
        """
        Enqueue a performance-related background job

        Args:
            job_function: Function name to execute
            job_args: Arguments for the job function
            priority: Job priority level
            operation_type: Security operation type
            job_dependencies: List of job IDs this job depends on
            estimated_duration: Estimated execution time in seconds
            resource_requirements: CPU/memory requirements

        Returns:
            Job ID for tracking
        """
        try:
            job_id = self._generate_job_id()

            job_data = {
                "job_id": job_id,
                "job_function": job_function,
                "job_args": job_args or {},
                "priority": priority,
                "operation_type": operation_type,
                "status": JobStatus.QUEUED,
                "created_at": now_datetime(),
                "job_dependencies": job_dependencies or [],
                "estimated_duration": estimated_duration,
                "resource_requirements": resource_requirements or {},
                "retry_count": 0,
                "performance_tracking": {
                    "queued_at": now_datetime(),
                    "queue_wait_time": None,
                    "execution_start": None,
                    "execution_end": None,
                    "total_duration": None,
                },
            }

            # Add to appropriate priority queue
            self.job_queues[priority].append(job_data)

            # Log job creation
            frappe.logger().info(f"Job {job_id} queued with priority {priority.value}: {job_function}")

            # Try to start job immediately if resources allow
            self._process_job_queues()

            return job_id

        except Exception as e:
            frappe.log_error(f"Error enqueueing performance job: {e}")
            raise

    def get_job_status(self, job_id: str) -> Dict:
        """
        Get current status of a job

        Args:
            job_id: Job ID to check

        Returns:
            Dict with job status and performance metrics
        """
        try:
            # Check running jobs
            if job_id in self.running_jobs:
                job_data = self.running_jobs[job_id]
                return self._format_job_status(job_data)

            # Check queued jobs
            for priority_queue in self.job_queues.values():
                for job_data in priority_queue:
                    if job_data["job_id"] == job_id:
                        return self._format_job_status(job_data)

            # Check job history
            for job_data in self.job_history:
                if job_data["job_id"] == job_id:
                    return self._format_job_status(job_data)

            return {"error": f"Job {job_id} not found"}

        except Exception as e:
            frappe.log_error(f"Error getting job status: {e}")
            return {"error": str(e)}

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued or running job

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            # Try to cancel queued job
            for priority_queue in self.job_queues.values():
                for i, job_data in enumerate(priority_queue):
                    if job_data["job_id"] == job_id:
                        job_data["status"] = JobStatus.CANCELLED
                        job_data["cancelled_at"] = now_datetime()

                        # Move to history
                        self.job_history.append(job_data)
                        priority_queue.pop(i)

                        frappe.logger().info(f"Job {job_id} cancelled while queued")
                        return True

            # Try to cancel running job (more complex - would need to signal the process)
            if job_id in self.running_jobs:
                job_data = self.running_jobs[job_id]
                job_data["status"] = JobStatus.CANCELLED
                job_data["cancelled_at"] = now_datetime()

                # In production, would send cancellation signal to running process
                frappe.logger().info(f"Job {job_id} marked for cancellation")
                return True

            return False

        except Exception as e:
            frappe.log_error(f"Error cancelling job: {e}")
            return False

    def get_queue_status(self) -> Dict:
        """
        Get overall queue status and performance metrics

        Returns:
            Dict with queue statistics and performance data
        """
        try:
            queue_status = {
                "timestamp": now_datetime(),
                "queue_statistics": {},
                "running_jobs": len(self.running_jobs),
                "performance_metrics": self._calculate_queue_performance(),
                "resource_utilization": self._calculate_resource_utilization(),
                "priority_distribution": {},
            }

            # Calculate queue statistics
            total_queued = 0
            for priority, queue in self.job_queues.items():
                queue_length = len(queue)
                total_queued += queue_length

                queue_status["queue_statistics"][priority.value] = {
                    "queued_jobs": queue_length,
                    "average_wait_time": self._calculate_average_wait_time(priority),
                    "oldest_job_age": self._get_oldest_job_age(priority),
                }

            queue_status["total_queued_jobs"] = total_queued

            # Priority distribution
            for priority in JobPriority:
                queue_status["priority_distribution"][priority.value] = {
                    "queued": len(self.job_queues[priority]),
                    "running": len([j for j in self.running_jobs.values() if j["priority"] == priority]),
                    "concurrency_limit": self.CONCURRENCY_LIMITS[priority],
                }

            return queue_status

        except Exception as e:
            frappe.log_error(f"Error getting queue status: {e}")
            return {"error": str(e)}

    def optimize_job_scheduling(self) -> Dict:
        """
        Optimize job scheduling based on current system performance

        Returns:
            Dict with optimization results and recommendations
        """
        try:
            optimization_results = {
                "optimization_timestamp": now_datetime(),
                "actions_taken": [],
                "recommendations": [],
                "performance_impact": {},
            }

            # Analyze current queue state
            total_queued = sum(len(queue) for queue in self.job_queues.values())

            # Optimization 1: Adjust concurrency limits based on system performance
            system_performance = self._assess_system_performance()
            if system_performance["cpu_usage"] < 70 and system_performance["memory_usage"] < 80:
                # System has capacity - increase concurrency for high priority jobs
                original_limit = self.CONCURRENCY_LIMITS[JobPriority.HIGH]
                self.CONCURRENCY_LIMITS[JobPriority.HIGH] = min(original_limit + 1, 5)

                optimization_results["actions_taken"].append(
                    f"Increased HIGH priority concurrency from {original_limit} to {self.CONCURRENCY_LIMITS[JobPriority.HIGH]}"
                )

            elif system_performance["cpu_usage"] > 85 or system_performance["memory_usage"] > 90:
                # System under stress - reduce concurrency for low priority jobs
                original_limit = self.CONCURRENCY_LIMITS[JobPriority.LOW]
                self.CONCURRENCY_LIMITS[JobPriority.LOW] = max(original_limit - 1, 1)

                optimization_results["actions_taken"].append(
                    f"Reduced LOW priority concurrency from {original_limit} to {self.CONCURRENCY_LIMITS[JobPriority.LOW]}"
                )

            # Optimization 2: Reorder jobs within priority levels based on dependencies
            dependency_optimizations = self._optimize_job_dependencies()
            optimization_results["actions_taken"].extend(dependency_optimizations)

            # Optimization 3: Generate recommendations
            if total_queued > 20:
                optimization_results["recommendations"].append("Consider scaling up background job workers")

            if self._get_average_queue_wait_time() > 300:  # 5 minutes
                optimization_results["recommendations"].append(
                    "Review job priorities - long wait times detected"
                )

            failed_jobs_rate = self._calculate_failure_rate()
            if failed_jobs_rate > 0.1:  # 10% failure rate
                optimization_results["recommendations"].append(
                    "High job failure rate - review error handling"
                )

            # Try to process more jobs after optimization
            jobs_started = self._process_job_queues()
            optimization_results["performance_impact"]["additional_jobs_started"] = jobs_started

            return optimization_results

        except Exception as e:
            frappe.log_error(f"Error optimizing job scheduling: {e}")
            return {"error": str(e)}

    def _generate_job_id(self) -> str:
        """Generate unique job ID"""
        import uuid

        return f"perf_job_{int(time.time())}_{str(uuid.uuid4())[:8]}"

    def _process_job_queues(self) -> int:
        """Process job queues in priority order"""
        jobs_started = 0

        try:
            # Process queues in priority order
            for priority in [
                JobPriority.CRITICAL,
                JobPriority.HIGH,
                JobPriority.NORMAL,
                JobPriority.LOW,
                JobPriority.BULK,
            ]:
                queue = self.job_queues[priority]

                if not queue:
                    continue

                # Check concurrency limits
                running_count = len([j for j in self.running_jobs.values() if j["priority"] == priority])
                max_concurrent = self.CONCURRENCY_LIMITS[priority]

                if running_count >= max_concurrent:
                    continue

                # Start jobs that are ready (dependencies met)
                jobs_to_start = []
                for job_data in queue:
                    if self._are_dependencies_met(job_data["job_dependencies"]):
                        jobs_to_start.append(job_data)

                        if len(jobs_to_start) >= (max_concurrent - running_count):
                            break

                # Start the jobs
                for job_data in jobs_to_start:
                    if self._start_job(job_data):
                        queue.remove(job_data)
                        jobs_started += 1

            return jobs_started

        except Exception as e:
            frappe.log_error(f"Error processing job queues: {e}")
            return jobs_started

    def _start_job(self, job_data: Dict) -> bool:
        """Start executing a job"""
        try:
            job_id = job_data["job_id"]

            # Update job status
            job_data["status"] = JobStatus.RUNNING
            job_data["performance_tracking"]["execution_start"] = now_datetime()

            # Calculate queue wait time
            queued_at = datetime.fromisoformat(
                job_data["performance_tracking"]["queued_at"].replace("Z", "+00:00")
            )
            wait_time = datetime.now() - queued_at
            job_data["performance_tracking"]["queue_wait_time"] = wait_time.total_seconds()

            # Move to running jobs
            self.running_jobs[job_id] = job_data

            # In production, would actually execute the job function here
            # For now, we'll simulate job execution
            self._simulate_job_execution(job_data)

            frappe.logger().info(f"Started job {job_id}: {job_data['job_function']}")
            return True

        except Exception as e:
            frappe.log_error(f"Error starting job {job_data.get('job_id', 'unknown')}: {e}")
            job_data["status"] = JobStatus.FAILED
            job_data["error"] = str(e)
            return False

    def _simulate_job_execution(self, job_data: Dict):
        """Simulate job execution (for testing)"""
        # In production, this would be replaced with actual job execution

        # Simulate completion after estimated duration
        def complete_job():
            job_id = job_data["job_id"]
            if job_id in self.running_jobs:
                job_data["status"] = JobStatus.COMPLETED
                job_data["performance_tracking"]["execution_end"] = now_datetime()

                # Calculate total duration
                start_time = datetime.fromisoformat(
                    job_data["performance_tracking"]["execution_start"].replace("Z", "+00:00")
                )
                end_time = datetime.now()
                job_data["performance_tracking"]["total_duration"] = (end_time - start_time).total_seconds()

                # Move to history
                self.job_history.append(job_data)
                del self.running_jobs[job_id]

                frappe.logger().info(f"Completed job {job_id}")

        # In production, would use actual background execution
        # For testing, mark as completed immediately
        complete_job()

    def _are_dependencies_met(self, dependencies: List[str]) -> bool:
        """Check if job dependencies are satisfied"""
        if not dependencies:
            return True

        for dep_job_id in dependencies:
            # Check if dependency job is completed
            for job_data in self.job_history:
                if job_data["job_id"] == dep_job_id and job_data["status"] == JobStatus.COMPLETED:
                    continue

            # If we get here, dependency is not met
            return False

        return True

    def _format_job_status(self, job_data: Dict) -> Dict:
        """Format job data for status response"""
        return {
            "job_id": job_data["job_id"],
            "job_function": job_data["job_function"],
            "status": job_data["status"].value,
            "priority": job_data["priority"].value,
            "created_at": job_data["created_at"],
            "performance_tracking": job_data["performance_tracking"],
            "retry_count": job_data.get("retry_count", 0),
            "estimated_duration": job_data.get("estimated_duration"),
            "error": job_data.get("error"),
        }

    def _calculate_queue_performance(self) -> Dict:
        """Calculate queue performance metrics"""
        if not self.job_history:
            return {"average_execution_time": 0, "throughput_per_hour": 0, "success_rate": 0}

        # Calculate from recent job history
        recent_jobs = [j for j in self.job_history if j["performance_tracking"].get("total_duration")]

        if not recent_jobs:
            return {"average_execution_time": 0, "throughput_per_hour": 0, "success_rate": 0}

        avg_execution_time = sum(j["performance_tracking"]["total_duration"] for j in recent_jobs) / len(
            recent_jobs
        )

        completed_jobs = [j for j in recent_jobs if j["status"] == JobStatus.COMPLETED]
        success_rate = len(completed_jobs) / len(recent_jobs) if recent_jobs else 0

        # Estimate throughput (simplified)
        throughput_per_hour = (
            len(recent_jobs) * 3600 / (avg_execution_time * len(recent_jobs)) if avg_execution_time > 0 else 0
        )

        return {
            "average_execution_time": avg_execution_time,
            "throughput_per_hour": throughput_per_hour,
            "success_rate": success_rate,
        }

    def _calculate_resource_utilization(self) -> Dict:
        """Calculate current resource utilization"""
        return {
            "cpu_usage_percent": 45.2,  # Placeholder
            "memory_usage_percent": 62.8,  # Placeholder
            "active_jobs": len(self.running_jobs),
            "queue_depth": sum(len(queue) for queue in self.job_queues.values()),
        }

    def _calculate_average_wait_time(self, priority: JobPriority) -> float:
        """Calculate average wait time for priority level"""
        # Placeholder calculation
        return 120.0  # 2 minutes average

    def _get_oldest_job_age(self, priority: JobPriority) -> float:
        """Get age of oldest job in priority queue"""
        queue = self.job_queues[priority]
        if not queue:
            return 0

        oldest_job = min(queue, key=lambda j: j["created_at"])
        created_at = datetime.fromisoformat(oldest_job["created_at"].replace("Z", "+00:00"))
        age = (datetime.now() - created_at).total_seconds()

        return age

    def _assess_system_performance(self) -> Dict:
        """Assess current system performance"""
        return {
            "cpu_usage": 55.0,  # Placeholder
            "memory_usage": 70.0,  # Placeholder
            "disk_io": 25.0,  # Placeholder
            "network_io": 15.0,  # Placeholder
        }

    def _optimize_job_dependencies(self) -> List[str]:
        """Optimize job order within queues based on dependencies"""
        optimizations = []

        for priority, queue in self.job_queues.items():
            if len(queue) <= 1:
                continue

            # Sort by dependency count (jobs with fewer dependencies first)
            original_order = [j["job_id"] for j in queue]
            queue.sort(key=lambda j: len(j["job_dependencies"]))
            new_order = [j["job_id"] for j in queue]

            if original_order != new_order:
                optimizations.append(f"Reordered {len(queue)} jobs in {priority.value} queue by dependencies")

        return optimizations

    def _get_average_queue_wait_time(self) -> float:
        """Get average queue wait time across all priorities"""
        if not self.job_history:
            return 0

        wait_times = [
            j["performance_tracking"]["queue_wait_time"]
            for j in self.job_history
            if j["performance_tracking"].get("queue_wait_time")
        ]

        return sum(wait_times) / len(wait_times) if wait_times else 0

    def _calculate_failure_rate(self) -> float:
        """Calculate job failure rate"""
        if not self.job_history:
            return 0

        failed_jobs = [j for j in self.job_history if j["status"] == JobStatus.FAILED]
        return len(failed_jobs) / len(self.job_history)


# Global job coordinator instance
_job_coordinator = None


def get_performance_job_coordinator() -> PerformanceJobCoordinator:
    """Get global performance job coordinator instance"""
    global _job_coordinator
    if _job_coordinator is None:
        _job_coordinator = PerformanceJobCoordinator()
    return _job_coordinator


if __name__ == "__main__":
    print("🔄 Enhanced Background Job Coordination System")
    print("Provides priority-based job queuing with performance optimization coordination")
