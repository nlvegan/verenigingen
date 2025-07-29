"""
Check error log entries to find the specific log titles
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_batch_debug_logs():
    """Check for REST Enhanced Batch Debug entries in Error Log"""
    try:
        # Get error logs that contain the old title
        logs = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%REST Enhanced Batch Debug%"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=20,
        )

        results = []
        for log in logs:
            # Extract first few lines to understand content
            error_lines = log.error.split("\n")[:10]
            preview = "\n".join(error_lines)

            results.append(
                {
                    "log_name": log.name,
                    "creation": log.creation,
                    "error_preview": preview,
                    "contains_mutations": "mutation" in log.error.lower(),
                    "contains_batch": "batch" in log.error.lower(),
                }
            )

        return {"success": True, "count": len(logs), "logs": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_mutation_type_logs():
    """Look for logs that contain mutation type processing"""
    try:
        # Get recent error logs that might contain mutation lists
        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">", "2024-01-01"], "error": ["like", "%mutation%"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=50,
        )

        mutation_type_logs = []
        for log in logs:
            # Look for patterns that suggest this is a mutation type processing log
            if any(
                pattern in log.error.lower()
                for pattern in [
                    "processing mutation type",
                    "mutations of type",
                    "mutation_type",
                    "batch import",
                    "enhanced batch",
                ]
            ):
                # Extract key info
                error_lines = log.error.split("\n")
                first_10_lines = "\n".join(error_lines[:10])

                mutation_type_logs.append(
                    {
                        "log_name": log.name,
                        "creation": log.creation,
                        "preview": first_10_lines,
                        "line_count": len(error_lines),
                        "size_kb": len(log.error) / 1024,
                    }
                )

        return {
            "success": True,
            "total_logs": len(logs),
            "mutation_type_logs": len(mutation_type_logs),
            "logs": mutation_type_logs[:10],  # Show first 10
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
