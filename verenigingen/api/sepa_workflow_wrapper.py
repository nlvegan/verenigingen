"""
SEPA Workflow Wrapper Functions
High-level functions that implement complete workflows with all safeguards
"""

import hashlib
import json

import frappe
from frappe.utils import getdate, now_datetime

from verenigingen.api.sepa_duplicate_prevention import (
    acquire_processing_lock,
    check_return_file_processed,
    detect_incomplete_reversals,
    detect_orphaned_payments,
    execute_idempotent_operation,
    generate_idempotency_key,
    release_processing_lock,
)
from verenigingen.api.sepa_reconciliation import (
    correlate_return_transactions,
    identify_sepa_transactions,
    process_sepa_return_file,
    process_sepa_transaction_conservative,
)

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.security.audit_logging import log_sensitive_operation
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.csrf_protection import validate_csrf_token
from verenigingen.utils.security.rate_limiting import rate_limit


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
@rate_limit(calls=30, period=60)  # 30 calls per minute
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def execute_complete_reconciliation(workflow_data: dict) -> dict:
    """
    Execute complete SEPA reconciliation workflow with all safeguards

    Args:
        workflow_data: {
            "bank_transaction": "BT-001",
            "sepa_batch": "BATCH-001",
            "processing_mode": "conservative"
        }

    Returns:
        Workflow execution result
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_workflow", "execute_complete_reconciliation", {"workflow_data": str(workflow_data)}
    )

    bank_transaction = workflow_data.get("bank_transaction")
    sepa_batch = workflow_data.get("sepa_batch")
    processing_mode = workflow_data.get("processing_mode", "conservative")

    if not bank_transaction or not sepa_batch:
        return {"success": False, "error": "Bank transaction and SEPA batch are required"}

    # Generate workflow idempotency key
    workflow_key = generate_idempotency_key(bank_transaction, sepa_batch, f"reconcile_{processing_mode}")

    def execute_workflow():
        # Execute based on processing mode
        if processing_mode == "conservative":
            return process_sepa_transaction_conservative(bank_transaction, sepa_batch)
        else:
            return {"success": False, "error": f"Unsupported processing mode: {processing_mode}"}

    # Execute with idempotency protection
    return execute_idempotent_operation(workflow_key, execute_workflow)


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def process_complete_return_file(return_file_content: str, file_name: str = "") -> dict:
    """
    Process complete return file with duplicate prevention

    Args:
        return_file_content: CSV content of return file
        file_name: Optional filename for logging

    Returns:
        Processing result
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_workflow",
        "process_complete_return_file",
        {"file_name": file_name, "content_length": len(return_file_content)},
    )

    # Generate file hash for duplicate detection
    file_hash = hashlib.sha256(return_file_content.encode()).hexdigest()

    try:
        # Check if file already processed
        check_return_file_processed(file_hash)

        # Acquire lock for return file processing
        if not acquire_processing_lock("return_file", file_hash):
            return {"success": False, "error": "Return file is currently being processed by another user"}

        try:
            # Log return file processing
            frappe.get_doc(
                {
                    "doctype": "SEPA Return File Log",
                    "file_hash": file_hash,
                    "file_name": file_name,
                    "processing_date": now_datetime(),
                    "processed_by": frappe.session.user,
                    "status": "Processing",
                }
            ).insert()

            # Process the return file
            result = process_sepa_return_file(return_file_content)

            # Update log status
            log_doc = frappe.get_doc("SEPA Return File Log", {"file_hash": file_hash})
            log_doc.status = "Completed" if result.get("success") else "Failed"
            log_doc.processing_result = json.dumps(result)
            log_doc.save()

            return result

        finally:
            release_processing_lock("return_file", file_hash)

    except frappe.ValidationError as e:
        return {"success": False, "error": str(e)}


@high_security_api(operation_type=OperationType.AUDIT)
@frappe.whitelist()
@rate_limit(calls=5, period=300)  # 5 calls per 5 minutes
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def run_comprehensive_sepa_audit() -> dict:
    """
    Run comprehensive audit of SEPA reconciliation system

    Returns:
        Audit results with recommendations
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_workflow", "run_comprehensive_sepa_audit", {"requested_by": frappe.session.user}
    )

    audit_results = {"timestamp": now_datetime(), "audit_sections": []}

    # 1. Check for orphaned payments
    orphaned_payments = detect_orphaned_payments()
    audit_results["audit_sections"].append(
        {
            "section": "Orphaned Payments",
            "status": "warning" if orphaned_payments else "ok",
            "count": len(orphaned_payments),
            "items": orphaned_payments[:10],  # Limit for display
            "recommendation": "Review and fix orphaned payment entries"
            if orphaned_payments
            else "No action needed",
        }
    )

    # 2. Check for incomplete reversals
    incomplete_reversals = detect_incomplete_reversals()
    audit_results["audit_sections"].append(
        {
            "section": "Incomplete Reversals",
            "status": "error" if incomplete_reversals else "ok",
            "count": len(incomplete_reversals),
            "items": incomplete_reversals[:10],
            "recommendation": "Complete failed payment reversals"
            if incomplete_reversals
            else "No action needed",
        }
    )

    # 3. Check for unprocessed SEPA transactions
    unprocessed_transactions = identify_sepa_transactions()
    audit_results["audit_sections"].append(
        {
            "section": "Unprocessed SEPA Transactions",
            "status": "info" if unprocessed_transactions.get("potential_matches") else "ok",
            "count": len(unprocessed_transactions.get("potential_matches", [])),
            "items": unprocessed_transactions.get("potential_matches", [])[:5],
            "recommendation": "Process identified SEPA transactions"
            if unprocessed_transactions.get("potential_matches")
            else "All transactions processed",
        }
    )

    # 4. Check for unmatched return transactions
    unmatched_returns = correlate_return_transactions()
    audit_results["audit_sections"].append(
        {
            "section": "Unmatched Return Transactions",
            "status": "warning" if unmatched_returns.get("unmatched_returns") else "ok",
            "count": len(unmatched_returns.get("unmatched_returns", [])),
            "items": unmatched_returns.get("unmatched_returns", [])[:5],
            "recommendation": "Investigate unmatched return transactions"
            if unmatched_returns.get("unmatched_returns")
            else "All returns matched",
        }
    )

    # 5. Overall health score
    total_issues = sum(len(section.get("items", [])) for section in audit_results["audit_sections"])
    error_sections = sum(1 for section in audit_results["audit_sections"] if section["status"] == "error")
    warning_sections = sum(1 for section in audit_results["audit_sections"] if section["status"] == "warning")

    if error_sections > 0:
        health_status = "critical"
        health_score = 0
    elif warning_sections > 2:
        health_status = "poor"
        health_score = 30
    elif warning_sections > 0:
        health_status = "fair"
        health_score = 70
    else:
        health_status = "excellent"
        health_score = 100

    audit_results["overall_health"] = {
        "status": health_status,
        "score": health_score,
        "total_issues": total_issues,
        "error_sections": error_sections,
        "warning_sections": warning_sections,
    }

    return audit_results


@high_security_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def generate_duplicate_prevention_report() -> dict:
    """
    Generate report on duplicate prevention effectiveness

    Returns:
        Report on prevented duplicates and system protection status
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_workflow", "generate_duplicate_prevention_report", {"requested_by": frappe.session.user}
    )

    report = {
        "generated_at": now_datetime(),
        "protection_status": {},
        "statistics": {},
        "recommendations": [],
    }

    # Check duplicate payment prevention
    duplicate_attempts = frappe.get_all(
        "Error Log",
        filters={"error": ["like", "%already fully paid%"], "creation": [">=", getdate()]},
        fields=["name", "creation", "error"],
    )

    report["protection_status"]["payment_duplicates_prevented"] = {
        "count": len(duplicate_attempts),
        "status": "active",
        "last_prevention": duplicate_attempts[0]["creation"] if duplicate_attempts else None,
    }

    # Check batch reprocessing prevention
    batch_reprocess_attempts = frappe.get_all(
        "Error Log",
        filters={"error": ["like", "%already been processed%"], "creation": [">=", getdate()]},
        fields=["name", "creation"],
    )

    report["protection_status"]["batch_reprocessing_prevented"] = {
        "count": len(batch_reprocess_attempts),
        "status": "active",
        "last_prevention": batch_reprocess_attempts[0]["creation"] if batch_reprocess_attempts else None,
    }

    # Statistics on SEPA processing
    total_payments_today = frappe.db.count(
        "Payment Entry", filters={"custom_sepa_batch": ["!=", ""], "posting_date": getdate()}
    )

    total_batches_processed = frappe.db.count(
        "SEPA Direct Debit Batch",
        filters={
            "custom_reconciliation_status": ["in", ["Fully Reconciled", "Partially Reconciled"]],
            "modified": [">=", getdate()],
        },
    )

    report["statistics"] = {
        "payments_created_today": total_payments_today,
        "batches_processed_today": total_batches_processed,
        "duplicate_prevention_active": True,
        "processing_locks_enabled": True,
    }

    # Generate recommendations
    if len(duplicate_attempts) > 5:
        report["recommendations"].append(
            {
                "priority": "medium",
                "type": "user_training",
                "message": f"High number of duplicate payment attempts ({len(duplicate_attempts)}) detected. Consider user training on SEPA processing workflows.",
            }
        )

    if total_batches_processed == 0:
        report["recommendations"].append(
            {
                "priority": "low",
                "type": "monitoring",
                "message": "No SEPA batches processed today. Verify if this is expected or if there are processing issues.",
            }
        )

    return report
