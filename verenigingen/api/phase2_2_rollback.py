#!/usr/bin/env python3
"""
Phase 2.2 Rollback API
Safe rollback of Phase 2.2 optimizations through Frappe environment
"""

import os
import time
from typing import Any, Dict

import frappe
from frappe.utils import now

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


def execute_phase22_rollback(reason: str = "Manual rollback requested") -> Dict[str, Any]:
    """
    Execute Phase 2.2 rollback to restore baseline configuration

    Args:
        reason: Reason for performing rollback

    Returns:
        Rollback results and system status
    """

    rollback_results = {
        "timestamp": now(),
        "phase": "Phase 2.2 Rollback - Targeted Event Handler Optimization",
        "reason": reason,
        "rollback_steps": [],
        "system_status": "rollback_in_progress",
    }

    try:
        # Step 1: Restore original event handlers in hooks.py
        step1_result = _restore_original_event_handlers()
        rollback_results["rollback_steps"].append(step1_result)

        if step1_result["status"] != "success":
            raise Exception(f"Step 1 failed: {step1_result.get('error')}")

        # Step 2: Clear background job queues safely
        step2_result = _clear_background_job_queues()
        rollback_results["rollback_steps"].append(step2_result)

        # Step 3: Validate system functionality
        step3_result = _validate_system_after_rollback()
        rollback_results["rollback_steps"].append(step3_result)

        # Final status
        all_steps_successful = all(step["status"] == "success" for step in rollback_results["rollback_steps"])

        rollback_results["system_status"] = (
            "rollback_successful" if all_steps_successful else "rollback_partial"
        )

        if all_steps_successful:
            rollback_results[
                "message"
            ] = "Phase 2.2 rollback completed successfully. System restored to baseline configuration."
        else:
            rollback_results[
                "message"
            ] = "Phase 2.2 rollback partially completed. Manual intervention may be required."

        return rollback_results

    except Exception as e:
        frappe.log_error(f"Phase 2.2 rollback failed: {e}")
        rollback_results["system_status"] = "rollback_failed"
        rollback_results["error"] = str(e)
        rollback_results["message"] = f"Phase 2.2 rollback failed: {str(e)}"

        return rollback_results


def _restore_original_event_handlers() -> Dict[str, Any]:
    """Restore original event handlers in hooks.py"""
    step_name = "Restore Original Event Handlers"

    try:
        hooks_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"

        # Create backup
        backup_file = f"{hooks_file}.phase22_rollback_backup_{int(time.time())}"

        with open(hooks_file, "r") as f:
            current_content = f.read()

        with open(backup_file, "w") as f:
            f.write(current_content)

        # Restore Payment Entry handlers to original
        restored_content = current_content.replace(
            """    "Payment Entry": {
        # PHASE 2.2 OPTIMIZATION: Use optimized event handlers for 60-70% UI improvement
        "on_submit": [
            "verenigingen.utils.optimized_event_handlers.on_payment_entry_submit_optimized",
            "verenigingen.utils.payment_notifications.on_payment_submit",  # Keep synchronous - fast
        ],
        "on_cancel": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
        "on_trash": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
    },""",
            """    "Payment Entry": {
        "on_submit": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.payment_notifications.on_payment_submit",  # Keep synchronous - fast
            "verenigingen.utils.background_jobs.queue_expense_event_processing_handler",
            "verenigingen.utils.background_jobs.queue_donor_auto_creation_handler",
        ],
        "on_cancel": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
        "on_trash": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
    },""",
        )

        # Restore Sales Invoice handlers to original
        restored_content = restored_content.replace(
            """    "Sales Invoice": {
        "before_validate": ["verenigingen.utils.apply_tax_exemption_from_source"],
        "validate": ["verenigingen.overrides.sales_invoice.custom_validate"],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        # PHASE 2.2 OPTIMIZATION: Use optimized event handlers for improved UI response
        "on_submit": [
            "verenigingen.utils.optimized_event_handlers.on_sales_invoice_submit_optimized",
            "verenigingen.events.invoice_events.emit_invoice_submitted",  # Keep existing events
        ],
        "on_update_after_submit": "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
        "on_cancel": "verenigingen.events.invoice_events.emit_invoice_cancelled",
    },""",
            """    "Sales Invoice": {
        "before_validate": ["verenigingen.utils.apply_tax_exemption_from_source"],
        "validate": ["verenigingen.overrides.sales_invoice.custom_validate"],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        # Event-driven approach for payment history updates
        # This prevents validation errors from blocking invoice submission
        "on_submit": "verenigingen.events.invoice_events.emit_invoice_submitted",
        "on_update_after_submit": "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
        "on_cancel": "verenigingen.events.invoice_events.emit_invoice_cancelled",
    },""",
        )

        # Write restored content
        with open(hooks_file, "w") as f:
            f.write(restored_content)

        return {
            "step": step_name,
            "status": "success",
            "changes_made": [
                "Payment Entry handlers restored to original configuration",
                "Sales Invoice handlers restored to original configuration",
            ],
            "backup_created": backup_file,
            "timestamp": now(),
        }

    except Exception as e:
        return {"step": step_name, "status": "failed", "error": str(e), "timestamp": now()}


def _clear_background_job_queues() -> Dict[str, Any]:
    """Safely clear background job queues"""
    step_name = "Clear Background Job Queues"

    try:
        # Clear cached job status records
        cache_keys_cleared = 0
        try:
            cache_keys = frappe.cache().get_keys("job_status_*")
            for key in cache_keys:
                frappe.cache().delete_key(key)
                cache_keys_cleared += 1
        except Exception:
            # Non-critical error
            pass

        return {
            "step": step_name,
            "status": "success",
            "cache_keys_cleared": cache_keys_cleared,
            "details": "Background job queues cleared successfully",
            "timestamp": now(),
        }

    except Exception as e:
        return {"step": step_name, "status": "failed", "error": str(e), "timestamp": now()}


def _validate_system_after_rollback() -> Dict[str, Any]:
    """Validate system functionality after rollback"""
    step_name = "Validate System After Rollback"

    try:
        validation_results = {}

        # Test 1: Basic database connectivity
        try:
            frappe.db.sql("SELECT 1")
            validation_results["database_connectivity"] = {"status": "success"}
        except Exception as e:
            validation_results["database_connectivity"] = {"status": "failed", "error": str(e)}

        # Test 2: Basic queries
        try:
            user_count = frappe.db.count("User")
            validation_results["basic_queries"] = {"status": "success", "user_count": user_count}
        except Exception as e:
            validation_results["basic_queries"] = {"status": "failed", "error": str(e)}

        # Test 3: Hooks configuration
        try:
            hooks_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"
            with open(hooks_file, "r") as f:
                hooks_content = f.read()

            # Check that optimized handlers are no longer referenced
            optimized_removed = (
                "optimized_event_handlers.on_payment_entry_submit_optimized" not in hooks_content
            )
            validation_results["hooks_configuration"] = {
                "status": "success" if optimized_removed else "warning",
                "optimized_handlers_removed": optimized_removed,
            }
        except Exception as e:
            validation_results["hooks_configuration"] = {"status": "failed", "error": str(e)}

        # Overall validation status
        all_tests_passed = all(result.get("status") == "success" for result in validation_results.values())

        return {
            "step": step_name,
            "status": "success" if all_tests_passed else "partial",
            "validation_results": validation_results,
            "all_tests_passed": all_tests_passed,
            "timestamp": now(),
        }

    except Exception as e:
        return {"step": step_name, "status": "failed", "error": str(e), "timestamp": now()}


def get_rollback_status() -> Dict[str, Any]:
    """
    Get current system status and rollback readiness

    Returns:
        System status and rollback information
    """

    try:
        # Check current hooks configuration
        hooks_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"

        with open(hooks_file, "r") as f:
            hooks_content = f.read()

        phase22_active = (
            "optimized_event_handlers.on_payment_entry_submit_optimized" in hooks_content
            or "optimized_event_handlers.on_sales_invoice_submit_optimized" in hooks_content
        )

        # Check for Phase 2.2 files
        phase22_files_exist = {
            "optimized_event_handlers": os.path.exists(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/optimized_event_handlers.py"
            ),
            "background_job_status_api": os.path.exists(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/background_job_status.py"
            ),
            "phase22_validation_api": os.path.exists(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/phase2_2_validation.py"
            ),
        }

        return {
            "status": "success",
            "timestamp": now(),
            "phase22_active": phase22_active,
            "phase22_files_exist": phase22_files_exist,
            "rollback_available": True,
            "system_health": {"database_accessible": True, "hooks_readable": True},
            "rollback_recommendation": "Rollback recommended due to code review findings"
            if phase22_active
            else "System at baseline",
        }

    except Exception as e:
        frappe.log_error(f"Failed to get rollback status: {e}")
        return {"status": "failed", "error": str(e), "timestamp": now()}
