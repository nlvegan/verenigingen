# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Migration: Clear deprecated dues schedule retry queue from cache

Background:
-----------
The old dues schedule retry system used an unbounded Redis cache key
"dues_schedule_retry_queue" which caused memory leaks in production.

This has been replaced with proper background job retry using frappe.enqueue()
via the new DuesScheduleCreationService in services/billing/.

This migration clears the obsolete cache key to free memory and prevent confusion.

Related Files:
- verenigingen/services/billing/dues_schedule_creation_service.py (new)
- verenigingen/verenigingen/doctype/membership/membership.py (refactored)
- verenigingen/utils/dues_schedule_auto_creator.py (deprecated functions)
"""

import frappe


def execute():
    """Clear the deprecated dues_schedule_retry_queue cache key"""
    try:
        # Check if the key exists
        retry_queue = frappe.cache().get("dues_schedule_retry_queue")

        if retry_queue:
            queue_size = len(retry_queue) if isinstance(retry_queue, dict) else 0
            frappe.logger().info(f"[MIGRATION] Clearing deprecated retry queue with {queue_size} entries")

            # Clear the cache key
            frappe.cache().delete_value("dues_schedule_retry_queue")

            frappe.logger().info(
                "[MIGRATION] Successfully cleared deprecated dues_schedule_retry_queue cache key"
            )

            # Log any pending retries that were in the queue
            if queue_size > 0:
                frappe.logger().warning(
                    f"[MIGRATION] Cleared {queue_size} pending retry entries. "
                    f"These will be handled by the new DuesScheduleCreationService "
                    f"if dues schedules are still missing."
                )
        else:
            frappe.logger().info("[MIGRATION] No deprecated retry queue found in cache - already clean")

    except Exception as e:
        frappe.logger().error(f"[MIGRATION] Error clearing deprecated retry queue: {str(e)}")
        # Don't fail the migration - this is a cleanup operation
        pass
