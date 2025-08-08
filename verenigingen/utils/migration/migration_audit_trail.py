"""
Migration audit trail system for eBoekhouden migration

Provides comprehensive logging, tracking, and reporting of all
migration operations for compliance and debugging purposes.
"""

import json
import os
from collections import defaultdict
from datetime import datetime

import frappe
from frappe.utils import cstr, now_datetime


class MigrationAuditTrail:
    """Comprehensive audit trail for migration operations"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.audit_entries = []
        self.operation_stack = []
        self.statistics = defaultdict(lambda: defaultdict(int))
        self.error_summary = defaultdict(list)
        self.performance_metrics = []
        self.audit_file_path = None
        self._initialize_audit_file()

    def _initialize_audit_file(self):
        """Initialize audit trail file"""
        timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
        self.audit_file_path = frappe.get_site_path(
            "private", "files", "migration_audit_trails", f"audit_{self.migration_doc.name}_{timestamp}.json"
        )

        os.makedirs(os.path.dirname(self.audit_file_path), exist_ok=True)

        # Initialize with header
        self._write_audit_header()

    def _write_audit_header(self):
        """Write audit trail header"""
        header = {
            "migration_id": self.migration_doc.name,
            "company": self.migration_doc.company,
            "from_date": str(self.migration_doc.get("date_from", "")),
            "to_date": str(self.migration_doc.get("date_to", "")),
            "started_at": str(now_datetime()),
            "user": frappe.session.user,
            "settings": {
                "dry_run": self.migration_doc.get("dry_run", False),
                "skip_existing": self.migration_doc.get("skip_existing", True),
                "batch_size": self.migration_doc.get("batch_size", 100),
            },
        }

        with open(self.audit_file_path, "w") as f:
            json.dump({"header": header, "entries": []}, f, indent=2)

    def start_operation(self, operation_type, details=None):
        """
        Start a new operation and track it

        Args:
            operation_type: Type of operation (e.g., "import_accounts", "create_invoice")
            details: Additional operation details

        Returns:
            Operation ID for tracking
        """
        operation_id = (
            "{operation_type}_{len(self.operation_stack)}_{now_datetime().strftime('%Y%m%d_%H%M%S%f')}"
        )

        operation = {
            "id": operation_id,
            "type": operation_type,
            "details": details or {},
            "started_at": now_datetime(),
            "parent_operation": self.operation_stack[-1]["id"] if self.operation_stack else None,
        }

        self.operation_stack.append(operation)

        self.log_event(
            "operation_started",
            {"operation_id": operation_id, "operation_type": operation_type, "details": details},
        )

        return operation_id

    def end_operation(self, operation_id, status="success", result=None, error=None):
        """
        End an operation and record results

        Args:
            operation_id: Operation ID to end
            status: "success", "failed", or "partial"
            result: Operation result details
            error: Error details if failed
        """
        # Find and remove operation from stack
        operation = None
        for i, op in enumerate(self.operation_stack):
            if op["id"] == operation_id:
                operation = self.operation_stack.pop(i)
                break

        if not operation:
            self.log_event(
                "error", {"message": "Operation {operation_id} not found in stack", "type": "audit_error"}
            )
            return

        # Calculate duration
        duration = (now_datetime() - operation["started_at"]).total_seconds()

        # Update statistics
        self.statistics[operation["type"]][status] += 1
        self.statistics[operation["type"]]["total_duration"] += duration

        # Record performance metrics
        self.performance_metrics.append(
            {
                "operation_type": operation["type"],
                "duration": duration,
                "status": status,
                "timestamp": now_datetime(),
            }
        )

        # Log operation completion
        self.log_event(
            "operation_completed",
            {
                "operation_id": operation_id,
                "operation_type": operation["type"],
                "status": status,
                "duration": duration,
                "result": result,
                "error": error,
            },
        )

        # Track errors
        if error:
            self.error_summary[operation["type"]].append(
                {"operation_id": operation_id, "error": error, "timestamp": now_datetime()}
            )

    def log_event(self, event_type, data, severity="info"):
        """
        Log an audit event

        Args:
            event_type: Type of event
            data: Event data
            severity: "info", "warning", "error", "critical"
        """
        entry = {
            "timestamp": str(now_datetime()),
            "event_type": event_type,
            "severity": severity,
            "data": data,
            "operation_context": [op["id"] for op in self.operation_stack],
        }

        self.audit_entries.append(entry)

        # Write to file periodically
        if len(self.audit_entries) % 50 == 0:
            self._flush_to_file()

    def log_record_creation(self, doctype, name, data=None):
        """Log creation of a record"""
        self.log_event(
            "record_created",
            {
                "doctype": doctype,
                "name": name,
                "data_preview": self._get_data_preview(data) if data else None,
            },
        )

        self.statistics["records_created"][doctype] += 1

    def log_record_update(self, doctype, name, changes):
        """Log update of a record"""
        self.log_event("record_updated", {"doctype": doctype, "name": name, "changes": changes})

        self.statistics["records_updated"][doctype] += 1

    def log_record_skipped(self, doctype, identifier, reason):
        """Log skipping of a record"""
        self.log_event(
            "record_skipped",
            {"doctype": doctype, "identifier": identifier, "reason": reason},
            severity="warning",
        )

        self.statistics["records_skipped"][doctype] += 1
        self.statistics["skip_reasons"][reason] += 1

    def log_validation_error(self, doctype, data, errors):
        """Log validation errors"""
        self.log_event(
            "validation_error",
            {"doctype": doctype, "data_preview": self._get_data_preview(data), "errors": errors},
            severity="error",
        )

        self.statistics["validation_errors"][doctype] += 1

    def log_api_call(self, api_method, params, response_summary):
        """Log external API calls"""
        self.log_event(
            "api_call",
            {
                "method": api_method,
                "params": self._sanitize_api_params(params),
                "response_summary": response_summary,
            },
        )

        self.statistics["api_calls"][api_method] += 1

    def log_duplicate_detected(self, doctype, record, matches):
        """Log duplicate detection"""
        self.log_event(
            "duplicate_detected",
            {
                "doctype": doctype,
                "record": self._get_data_preview(record),
                "matches": matches,
                "match_count": len(matches),
            },
            severity="warning",
        )

        self.statistics["duplicates_detected"][doctype] += 1

    def log_batch_processing(self, batch_info):
        """Log batch processing information"""
        self.log_event(
            "batch_processed",
            {
                "batch_number": batch_info.get("batch_number"),
                "batch_size": batch_info.get("batch_size"),
                "records_processed": batch_info.get("records_processed"),
                "errors": batch_info.get("errors", 0),
                "duration": batch_info.get("duration"),
            },
        )

    def log_rollback(self, checkpoint_id, rollback_result):
        """Log rollback operation"""
        self.log_event(
            "rollback_performed",
            {
                "checkpoint_id": checkpoint_id,
                "success": rollback_result.get("success"),
                "actions_performed": len(rollback_result.get("actions", [])),
                "rollback_summary": rollback_result,
            },
            severity="critical",
        )

    def log_data_transformation(self, original, transformed, transformation_type):
        """Log data transformations"""
        self.log_event(
            "data_transformed",
            {
                "transformation_type": transformation_type,
                "original_preview": self._get_data_preview(original),
                "transformed_preview": self._get_data_preview(transformed),
            },
        )

    def add_compliance_note(self, note_type, details):
        """Add compliance-related notes"""
        self.log_event(
            "compliance_note",
            {"note_type": note_type, "details": details, "timestamp": str(now_datetime())},
            severity="info",
        )

    def _get_data_preview(self, data):
        """Get a safe preview of data for logging"""
        if not data:
            return None

        preview = {}
        preview_fields = [
            "name",
            "customer",
            "supplier",
            "party",
            "posting_date",
            "grand_total",
            "paid_amount",
            "account_name",
            "account_number",
            "customer_name",
            "supplier_name",
            "reference_no",
        ]

        for field in preview_fields:
            if isinstance(data, dict) and field in data:
                preview[field] = cstr(data[field])[:100]  # Truncate long values

        return preview

    def _sanitize_api_params(self, params):
        """Remove sensitive information from API parameters"""
        if not params:
            return None

        sanitized = params.copy() if isinstance(params, dict) else {}

        # Remove sensitive fields
        sensitive_fields = ["password", "security_code", "api_key", "secret"]
        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "***REDACTED***"

        return sanitized

    def _flush_to_file(self):
        """Write accumulated entries to file"""
        try:
            # Read existing content
            with open(self.audit_file_path, "r") as f:
                audit_data = json.load(f)

            # Append new entries
            audit_data["entries"].extend(self.audit_entries)

            # Update statistics
            audit_data["statistics"] = dict(self.statistics)
            audit_data["error_summary"] = dict(self.error_summary)

            # Write back
            with open(self.audit_file_path, "w") as f:
                json.dump(audit_data, f, indent=2, default=str)

            # Clear processed entries
            self.audit_entries = []

        except Exception as e:
            frappe.log_error(f"Failed to flush audit trail: {str(e)}", "Migration Audit")

    def generate_summary_report(self):
        """Generate a summary report of the migration"""
        # Ensure all entries are flushed
        self._flush_to_file()

        # Calculate aggregate statistics
        total_records = sum(
            sum(counts.values()) for key, counts in self.statistics.items() if key.startswith("records_")
        )

        total_errors = sum(len(errors) for errors in self.error_summary.values())

        # Performance analysis
        avg_operation_times = {}
        for op_type in set(m["operation_type"] for m in self.performance_metrics):
            op_metrics = [m for m in self.performance_metrics if m["operation_type"] == op_type]
            if op_metrics:
                avg_operation_times[op_type] = {
                    "average_duration": sum(m["duration"] for m in op_metrics) / len(op_metrics),
                    "total_operations": len(op_metrics),
                    "success_rate": sum(1 for m in op_metrics if m["status"] == "success")
                    / len(op_metrics)
                    * 100,
                }

        summary = {
            "migration_id": self.migration_doc.name,
            "audit_file": self.audit_file_path,
            "summary_generated_at": str(now_datetime()),
            "overall_statistics": {
                "total_records_processed": total_records,
                "total_errors": total_errors,
                "records_created": dict(self.statistics.get("records_created", {})),
                "records_updated": dict(self.statistics.get("records_updated", {})),
                "records_skipped": dict(self.statistics.get("records_skipped", {})),
                "validation_errors": dict(self.statistics.get("validation_errors", {})),
                "duplicates_detected": dict(self.statistics.get("duplicates_detected", {})),
            },
            "skip_reasons": dict(self.statistics.get("skip_reasons", {})),
            "api_calls": dict(self.statistics.get("api_calls", {})),
            "performance_metrics": avg_operation_times,
            "error_summary": dict(self.error_summary),
            "recommendations": self._generate_recommendations(),
        }

        # Save summary report
        summary_path = frappe.get_site_path(
            "private",
            "files",
            "migration_audit_trails",
            "summary_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
        )

        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        return summary

    def _generate_recommendations(self):
        """Generate recommendations based on audit data"""
        recommendations = []

        # Check error rate
        total_operations = sum(
            self.statistics[op_type]["success"] + self.statistics[op_type]["failed"]
            for op_type in self.statistics
            if "success" in self.statistics[op_type]
        )

        total_failures = sum(
            self.statistics[op_type]["failed"]
            for op_type in self.statistics
            if "failed" in self.statistics[op_type]
        )

        if total_operations > 0:
            failure_rate = (total_failures / total_operations) * 100
            if failure_rate > 5:
                recommendations.append(
                    {
                        "type": "high_failure_rate",
                        "message": "High failure rate detected: {failure_rate:.1f}%",
                        "severity": "high",
                        "action": "Review error logs and consider data cleanup before re-running",
                    }
                )

        # Check for duplicate issues
        total_duplicates = sum(self.statistics.get("duplicates_detected", {}).values())
        if total_duplicates > 10:
            recommendations.append(
                {
                    "type": "duplicate_records",
                    "message": "Found {total_duplicates} duplicate records",
                    "severity": "medium",
                    "action": "Run duplicate cleanup before migration",
                }
            )

        # Check validation errors
        total_validation_errors = sum(self.statistics.get("validation_errors", {}).values())
        if total_validation_errors > 0:
            recommendations.append(
                {
                    "type": "validation_errors",
                    "message": "Encountered {total_validation_errors} validation errors",
                    "severity": "medium",
                    "action": "Review data quality and field mappings",
                }
            )

        # Performance recommendations
        # Calculate average operation times
        avg_operation_times = {}
        for op_type in set(m["operation_type"] for m in self.performance_metrics):
            op_metrics = [m for m in self.performance_metrics if m["operation_type"] == op_type]
            if op_metrics:
                avg_operation_times[op_type] = {
                    "average_duration": sum(m["duration"] for m in op_metrics) / len(op_metrics),
                    "total_operations": len(op_metrics),
                    "success_rate": sum(1 for m in op_metrics if m["status"] == "success")
                    / len(op_metrics)
                    * 100,
                }

        slow_operations = [
            op_type
            for op_type, metrics in avg_operation_times.items()
            if metrics.get("average_duration", 0) > 5.0
        ]

        if slow_operations:
            recommendations.append(
                {
                    "type": "performance",
                    "message": "Slow operations detected: {', '.join(slow_operations)}",
                    "severity": "low",
                    "action": "Consider batch size optimization",
                }
            )

        return recommendations


class AuditedMigrationOperation:
    """Context manager for audited operations"""

    def __init__(self, audit_trail, operation_type, details=None):
        self.audit_trail = audit_trail
        self.operation_type = operation_type
        self.details = details
        self.operation_id = None
        self.result = None
        self.error = None

    def __enter__(self):
        self.operation_id = self.audit_trail.start_operation(self.operation_type, self.details)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            status = "success"
            error = None
        else:
            status = "failed"
            error = str(exc_val)

        self.audit_trail.end_operation(self.operation_id, status=status, result=self.result, error=error)

        # Don't suppress exceptions
        return False

    def set_result(self, result):
        """Set operation result"""
        self.result = result


@frappe.whitelist()
def get_migration_audit_summary(migration_name):
    """Get audit summary for a migration"""
    # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    audit_trail = MigrationAuditTrail(migration_doc)

    return audit_trail.generate_summary_report()


@frappe.whitelist()
def get_migration_audit_details(migration_name, event_type=None, severity=None):
    """Get detailed audit entries with filters"""
    # Find the latest audit file for this migration
    audit_dir = frappe.get_site_path("private", "files", "migration_audit_trails")

    audit_files = []
    if os.path.exists(audit_dir):
        for file in os.listdir(audit_dir):
            if file.startswith("audit_{migration_name}_") and file.endswith(".json"):
                audit_files.append(os.path.join(audit_dir, file))

    if not audit_files:
        return {"error": "No audit trail found for this migration"}

    # Get the latest file
    latest_file = max(audit_files, key=os.path.getmtime)

    with open(latest_file, "r") as f:
        audit_data = json.load(f)

    # Filter entries
    entries = audit_data.get("entries", [])

    if event_type:
        entries = [e for e in entries if e.get("event_type") == event_type]

    if severity:
        entries = [e for e in entries if e.get("severity") == severity]

    return {
        "audit_file": latest_file,
        "total_entries": len(audit_data.get("entries", [])),
        "filtered_entries": len(entries),
        "entries": entries[:1000],  # Limit to prevent large responses
        "statistics": audit_data.get("statistics", {}),
    }
