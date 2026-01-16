"""
Add batch_rate_limit_calls to all CRITICAL/HIGH security operations.

This patch ensures that CRITICAL and HIGH security operations have explicit
batch rate limits configured. This is required after the security fix that
enforces rate limiting for CRITICAL/HIGH operations in background context
(instead of bypassing rate limiting entirely).

Without explicit batch_rate_limit_calls, these operations would inherit
their interactive rate limits when running in background jobs or scheduled
tasks, which could break legitimate batch processing.

Default batch limits:
- CRITICAL operations: 100,000 calls per hour
- HIGH operations: 50,000 calls per hour

These are intentionally high to not interfere with batch processing while
still providing a safety net against runaway processes.
"""

import frappe


def execute():
    """Add batch_rate_limit_calls to CRITICAL/HIGH operations without them."""

    # Skip if Critical Operation Rule doctype doesn't exist
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    # Define default batch limits by security level
    batch_limits = {
        "critical": 100000,  # 100k calls per hour for critical ops
        "high": 50000,  # 50k calls per hour for high security ops
    }

    # Find CRITICAL/HIGH operations without batch_rate_limit_calls
    operations = frappe.get_all(
        "Critical Operation Rule",
        filters={
            "enabled": 1,
            "security_level": ["in", ["critical", "high"]],
        },
        fields=["name", "operation_name", "security_level", "batch_rate_limit_calls"],
    )

    updated_count = 0

    for op in operations:
        # Skip if batch_rate_limit_calls is already set to a non-zero value
        if op.batch_rate_limit_calls and op.batch_rate_limit_calls > 0:
            continue

        # Get the appropriate batch limit for this security level
        batch_limit = batch_limits.get(op.security_level, 50000)

        # Update the COR record
        frappe.db.set_value(
            "Critical Operation Rule",
            op.name,
            {
                "batch_rate_limit_calls": batch_limit,
                "batch_rate_limit_period_seconds": 3600,  # 1 hour
                "apply_batch_limits_to": "Both",  # Apply to both background jobs and scheduled tasks
            },
            update_modified=False,
        )
        updated_count += 1

    if updated_count > 0:
        frappe.db.commit()
        frappe.logger("patches").info(
            f"Added batch_rate_limit_calls to {updated_count} CRITICAL/HIGH operations"
        )
    else:
        frappe.logger("patches").info(
            "All CRITICAL/HIGH operations already have batch_rate_limit_calls configured"
        )
