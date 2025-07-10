"""
Migration Error Recovery and Retry System

Provides comprehensive error handling, retry mechanisms, and recovery options
for the eBoekhouden migration process.
"""

import json
import time
import traceback
from datetime import datetime, timedelta
from functools import wraps

import frappe
from frappe.utils import add_days, now_datetime


class MigrationError:
    """Represents a migration error with full context"""

    def __init__(self, error_type, message, record_data=None, context=None):
        self.error_type = error_type
        self.message = message
        self.record_data = record_data or {}
        self.context = context or {}
        self.timestamp = now_datetime()
        self.traceback = traceback.format_exc()

    def to_dict(self):
        return {
            "error_type": self.error_type,
            "message": self.message[:500],  # Truncate for safety
            "record_data": self.record_data,
            "context": self.context,
            "timestamp": str(self.timestamp),
            "traceback": self.traceback,
        }


class RetryStrategy:
    """Configurable retry strategy for migration operations"""

    def __init__(self, max_retries=3, initial_delay=1, backoff_factor=2, max_delay=60):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay

    def get_delay(self, attempt):
        """Calculate delay for retry attempt using exponential backoff"""
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay)


def with_retry(retry_strategy=None, error_handler=None):
    """
    Decorator for adding retry capability to migration functions

    Args:
        retry_strategy: RetryStrategy instance (default: 3 retries with exponential backoff)
        error_handler: Function to handle errors (receives MigrationError instance)
    """
    if retry_strategy is None:
        retry_strategy = RetryStrategy()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, retry_strategy.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = MigrationError(
                        error_type=type(e).__name__,
                        message=str(e),
                        context={
                            "function": func.__name__,
                            "attempt": attempt,
                            "args": str(args)[:200],
                            "kwargs": str(kwargs)[:200],
                        },
                    )

                    if error_handler:
                        error_handler(last_error)

                    if attempt < retry_strategy.max_retries:
                        delay = retry_strategy.get_delay(attempt)
                        frappe.logger().warning(
                            "Retry {attempt}/{retry_strategy.max_retries} for {func.__name__} "
                            f"after {delay}s delay. Error: {str(e)[:200]}"
                        )
                        time.sleep(delay)
                    else:
                        # Final attempt failed
                        raise

            return None

        return wrapper

    return decorator


class MigrationErrorRecovery:
    """Handles error recovery for migration processes"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.error_log = []
        self.failed_records = []
        self.retry_queue = []

    def log_error(self, error, record_data=None):
        """Log an error with full context"""
        migration_error = MigrationError(
            error_type=type(error).__name__ if isinstance(error, Exception) else "Unknown",
            message=str(error),
            record_data=record_data,
            context={
                "migration_name": self.migration_doc.name,
                "migration_type": self.migration_doc.get("migration_type"),
                "timestamp": str(now_datetime()),
            },
        )

        self.error_log.append(migration_error.to_dict())

        # Save to failed records for retry
        if record_data:
            self.failed_records.append(
                {
                    "record": record_data,
                    "error": migration_error.to_dict(),
                    "retry_count": 0,
                    "last_retry": None,
                }
            )

        # Update migration document
        self._update_migration_error_log()

        return migration_error

    def _update_migration_error_log(self):
        """Update migration document with error information"""
        try:
            # Truncate error log to prevent field overflow
            error_summary = self._create_error_summary()

            frappe.db.set_value(
                "E-Boekhouden Migration",
                self.migration_doc.name,
                {
                    "error_log": error_summary[:100000],  # Long Text field limit
                    "failed_record_count": len(self.failed_records),
                },
                update_modified=False,
            )

            # Save detailed errors to file
            self._save_error_details_to_file()

        except Exception as e:
            frappe.logger().error(f"Failed to update migration error log: {str(e)}")

    def _create_error_summary(self):
        """Create a summary of errors for the migration document"""
        summary_lines = [
            f"Total Errors: {len(self.error_log)}",
            "Failed Records: {len(self.failed_records)}",
            "Last Updated: {now_datetime()}",
            "\n" + "=" * 50 + "\n",
        ]

        # Group errors by type
        error_types = {}
        for error in self.error_log:
            error_type = error.get("error_type", "Unknown")
            if error_type not in error_types:
                error_types[error_type] = []
            error_types[error_type].append(error)

        # Add error type summary
        summary_lines.append("Error Summary by Type:")
        for error_type, errors in error_types.items():
            summary_lines.append(f"- {error_type}: {len(errors)} occurrences")
            # Show first few examples
            for i, error in enumerate(errors[:3]):
                summary_lines.append(f"  {i + 1}. {error['message'][:100]}...")

        return "\n".join(summary_lines)

    def _save_error_details_to_file(self):
        """Save detailed error information to a file"""
        try:
            file_path = frappe.get_site_path(
                "private",
                "files",
                "eboekhouden_recovery_logs",
                "recovery_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
            )

            # Ensure directory exists
            import os

            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Save error details
            recovery_data = {
                "migration": self.migration_doc.name,
                "timestamp": str(now_datetime()),
                "error_log": self.error_log,
                "failed_records": self.failed_records,
                "retry_queue": self.retry_queue,
            }

            with open(file_path, "w") as f:
                json.dump(recovery_data, f, indent=2)

            return file_path

        except Exception as e:
            frappe.logger().error(f"Failed to save error details to file: {str(e)}")
            return None

    def add_to_retry_queue(self, record_data, error=None):
        """Add a failed record to the retry queue"""
        retry_record = {
            "record": record_data,
            "error": error.to_dict() if error else None,
            "retry_count": 0,
            "last_retry": None,
            "status": "pending",
        }

        self.retry_queue.append(retry_record)

    def process_retry_queue(self, process_function, retry_strategy=None):
        """Process all records in the retry queue"""
        if retry_strategy is None:
            retry_strategy = RetryStrategy()

        results = {"successful": 0, "failed": 0, "errors": []}

        for retry_record in self.retry_queue:
            if retry_record["status"] != "pending":
                continue

            retry_record["retry_count"] += 1
            retry_record["last_retry"] = str(now_datetime())

            try:
                # Process with retry
                @with_retry(retry_strategy=retry_strategy)
                def process_with_retry():
                    return process_function(retry_record["record"])

                # result = process_with_retry()
                process_with_retry()

                retry_record["status"] = "success"
                results["successful"] += 1

            except Exception as e:
                retry_record["status"] = "failed"
                retry_record["error"] = MigrationError(
                    error_type=type(e).__name__, message=str(e), record_data=retry_record["record"]
                ).to_dict()

                results["failed"] += 1
                results["errors"].append(str(e))

                # Move to failed records if max retries exceeded
                if retry_record["retry_count"] >= retry_strategy.max_retries:
                    self.failed_records.append(retry_record)

        # Update migration document
        self._update_migration_error_log()

        return results

    def create_recovery_report(self):
        """Create a detailed recovery report"""
        report = {
            "migration": self.migration_doc.name,
            "timestamp": str(now_datetime()),
            "summary": {
                "total_errors": len(self.error_log),
                "failed_records": len(self.failed_records),
                "retry_queue_size": len(self.retry_queue),
                "pending_retries": len([r for r in self.retry_queue if r["status"] == "pending"]),
            },
            "error_analysis": self._analyze_errors(),
            "recommendations": self._get_recovery_recommendations(),
        }

        return report

    def _analyze_errors(self):
        """Analyze errors to identify patterns"""
        analysis = {"error_types": {}, "error_patterns": [], "time_distribution": {}}

        # Count error types
        for error in self.error_log:
            error_type = error.get("error_type", "Unknown")
            if error_type not in analysis["error_types"]:
                analysis["error_types"][error_type] = 0
            analysis["error_types"][error_type] += 1

        # Identify common patterns
        common_messages = {}
        for error in self.error_log:
            msg = error.get("message", "")
            # Extract key parts of error message
            if "duplicate" in msg.lower():
                pattern = "Duplicate Entry"
            elif "validation" in msg.lower():
                pattern = "Validation Error"
            elif "connection" in msg.lower() or "timeout" in msg.lower():
                pattern = "Connection/Timeout"
            elif "permission" in msg.lower():
                pattern = "Permission Error"
            else:
                pattern = "Other"

            if pattern not in common_messages:
                common_messages[pattern] = 0
            common_messages[pattern] += 1

        analysis["error_patterns"] = common_messages

        return analysis

    def _get_recovery_recommendations(self):
        """Provide recommendations based on error analysis"""
        recommendations = []

        analysis = self._analyze_errors()

        # Check for connection errors
        if analysis["error_patterns"].get("Connection/Timeout", 0) > 5:
            recommendations.append(
                {
                    "issue": "Multiple connection/timeout errors detected",
                    "action": "Check API connectivity and increase timeout settings",
                    "priority": "high",
                }
            )

        # Check for duplicate entries
        if analysis["error_patterns"].get("Duplicate Entry", 0) > 0:
            recommendations.append(
                {
                    "issue": "Duplicate entries detected",
                    "action": "Review duplicate detection logic or clean existing data",
                    "priority": "medium",
                }
            )

        # Check for validation errors
        if analysis["error_patterns"].get("Validation Error", 0) > 10:
            recommendations.append(
                {
                    "issue": "High number of validation errors",
                    "action": "Review data mapping and validation rules",
                    "priority": "high",
                }
            )

        # Check for permission errors
        if analysis["error_patterns"].get("Permission Error", 0) > 0:
            recommendations.append(
                {
                    "issue": "Permission errors detected",
                    "action": "Check user permissions and API credentials",
                    "priority": "critical",
                }
            )

        return recommendations


@frappe.whitelist()
def retry_failed_migration_records(migration_name):
    """Retry all failed records from a migration"""
    # migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)

    # Load recovery data
    recovery = MigrationErrorRecovery(migration_doc)

    # Load failed records from file if available
    recovery_files = frappe.get_all(
        "File",
        filters={
            "file_name": ["like", "%recovery_{migration_name}%"],
            "attached_to_doctype": "E Boekhouden Migration",
        },
        order_by="creation desc",
        limit=1,
    )

    if recovery_files:
        file_doc = frappe.get_doc("File", recovery_files[0].name)
        with open(file_doc.get_full_path(), "r") as f:
            recovery_data = json.load(f)
            recovery.failed_records = recovery_data.get("failed_records", [])
            recovery.retry_queue = recovery_data.get("failed_records", [])

    # Define process function based on migration type
    from .eboekhouden_soap_migration import process_single_mutation

    def process_record(record):
        return process_single_mutation(
            record, migration_doc.company, migration_doc.cost_center, migration_doc
        )

    # Process retry queue
    results = recovery.process_retry_queue(process_record)

    return results


@frappe.whitelist()
def get_migration_recovery_report(migration_name):
    """Get recovery report for a migration"""
    # migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)
    recovery = MigrationErrorRecovery(migration_doc)

    # Load error data
    # ... (load from files)

    return recovery.create_recovery_report()
