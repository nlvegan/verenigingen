"""
SEPA Direct Debit processor - Bridge Module

This module re-exports the SEPABatchProcessor (as SEPAProcessor) from the
services layer for backward compatibility. All existing imports continue
to work unchanged.

The actual implementation is in:
    verenigingen.verenigingen_payments.services.sepa_batch_processor

API functions are kept here as they need @frappe.whitelist() decorators.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.services.sepa_batch_processor import (
    SEPABatchProcessor,
    get_sepa_batch_processor,
)
from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager
from verenigingen.verenigingen_payments.utils.sepa_error_handler import get_sepa_error_handler

# Backward compatibility alias - existing code uses SEPAProcessor
SEPAProcessor = SEPABatchProcessor

# Re-export for convenience
__all__ = [
    "SEPAProcessor",
    "SEPABatchProcessor",
    "get_sepa_batch_processor",
    "create_monthly_dues_collection_batch",
    "process_sepa_returns",
    "verify_invoice_coverage_status",
    "get_sepa_batch_preview",
    "get_upcoming_dues_collections",
    "validate_sepa_configuration",
]


# =============================================================================
# API Functions (kept here for @frappe.whitelist() registration)
# =============================================================================


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_monthly_dues_collection_batch():
    """
    Scheduled job to create monthly SEPA collection batch
    Uses centralized configuration for timing and settings
    """
    from frappe.utils import getdate, today

    from verenigingen.utils.db_advisory_lock import get_lock, release_lock

    if not get_lock("sched_monthly_dues_collection_batch", timeout=0):
        frappe.logger().info("create_monthly_dues_collection_batch already running, skipping")
        return None

    try:
        return _create_monthly_dues_collection_batch_impl()
    finally:
        release_lock("sched_monthly_dues_collection_batch")


def _create_monthly_dues_collection_batch_impl():
    from frappe.utils import getdate, today

    # Use centralized configuration manager
    config_manager = get_sepa_config_manager()
    timing_config = config_manager.get_batch_timing_config()

    current_date = getdate(today())

    # Check if auto creation is enabled
    if not timing_config["auto_creation_enabled"]:
        frappe.logger().info("Auto batch creation is disabled in configuration")
        return None

    # Check if today is a batch creation day
    if not timing_config["is_creation_day"]:
        creation_days = ", ".join([str(day) for day in timing_config["creation_days"]])
        frappe.logger().info(
            f"Skipping SEPA batch creation - today is {current_date.day}, runs on: {creation_days}"
        )
        return None

    # Use configured processing date
    processing_date = timing_config["next_processing_date"]

    # Create batch with error handling
    error_handler = get_sepa_error_handler()

    def create_batch_operation():
        processor = get_sepa_batch_processor()
        return processor.create_dues_collection_batch(collection_date=processing_date)

    result = error_handler.execute_with_retry(create_batch_operation)

    if result["success"]:
        batch = result["result"]
        if batch:
            frappe.logger().info(
                f"Created monthly SEPA batch {batch.name} on {current_date} "
                f"for processing on {processing_date} (Dutch payroll timing)"
            )

            # Auto-submit if configured
            if timing_config["auto_submit_enabled"]:
                try:
                    batch.submit()
                    batch.generate_sepa_xml()
                    frappe.logger().info(f"Auto-submitted and generated SEPA file for batch: {batch.name}")
                except Exception as e:
                    frappe.log_error(
                        f"Failed to auto-submit batch {batch.name}: {str(e)}", "SEPA Auto-Submit Error"
                    )

            return batch.name
        else:
            frappe.logger().info("No invoices found for SEPA batch creation")
            return None
    else:
        # The same silent-monthly-loss shape as the daily optimizer (#627 §3), and the
        # analysis in #621 did not cover it. `execute_with_retry` has already exhausted
        # its retries by here, so this is the run's terminal state: nothing was
        # collected, and the next automatic attempt is the next configured creation day
        # -- by default the 1st of next month.
        #
        # An Error Log alone is a record nobody is looking at on the day it matters, so
        # the notification goes out too. `send_system_error_notification` swallows its
        # own send failures, so this cannot make the failure worse.
        #
        # Keyword form: `log_error(title, message)`. The positional call this replaced
        # put the message in `Error Log.method` (Data, truncated at 140 chars) and left
        # the title as the whole body.
        from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
            send_system_error_notification,
        )

        detail = (
            f"Monthly SEPA dues collection batch for {processing_date} could not be "
            f"created after {result.get('retries_attempted', 0)} retries: "
            f"{result['error']}. NO membership dues were collected in this run; the "
            f"next automatic attempt is the next configured batch creation day, so "
            f"this needs a manual batch run rather than a wait."
        )
        frappe.log_error(title="Monthly SEPA Batch Creation Error", message=detail)
        send_system_error_notification(detail)
        return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_sepa_returns(batch_name: str, return_file):
    """Process SEPA return file for a batch"""
    processor = get_sepa_batch_processor()
    failed_count = processor.process_batch_returns(batch_name, return_file)

    frappe.msgprint(_("Processed {0} failed payments from SEPA return file").format(failed_count))

    return failed_count


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def verify_invoice_coverage_status(collection_date=None):
    """API to check invoice coverage for a specific date"""
    processor = get_sepa_batch_processor()
    if not collection_date:
        collection_date = today()

    result = processor.verify_invoice_coverage(collection_date)
    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_sepa_batch_preview(collection_date=None):
    """Preview what SEPA batch would be created without actually creating it"""
    processor = get_sepa_batch_processor()
    if not collection_date:
        collection_date = today()

    invoices = processor.get_existing_unpaid_sepa_invoices(collection_date)

    return {
        "success": True,
        "collection_date": collection_date,
        "unpaid_invoices_found": len(invoices),
        "total_amount": sum(flt(inv["amount"]) for inv in invoices),
        "sample_invoices": invoices[:5],  # Show first 5 as preview
        "members_affected": len(set(inv["member"] for inv in invoices)),
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_upcoming_dues_collections(days_ahead=30):
    """Get upcoming dues collections for review"""
    # Get schedules that will be collected in the next X days
    future_date = add_days(today(), days_ahead)

    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "payment_terms_template": "SEPA Direct Debit",
            "next_invoice_date": ["between", [today(), future_date]],
        },
        fields=[
            "name",
            "member",
            "minimum_amount",
            "suggested_amount",
            "uses_custom_amount",
            "billing_frequency",
            "next_invoice_date",
            "contribution_mode",
            "last_invoice_coverage_start",
            "last_invoice_coverage_end",
        ],
        order_by="next_invoice_date",
    )

    # Group by collection date
    collections_by_date = {}
    for schedule in schedules:
        date_key = str(schedule.next_invoice_date)
        if date_key not in collections_by_date:
            collections_by_date[date_key] = {
                "date": schedule.next_invoice_date,
                "schedules": [],
                "total_amount": 0,
                "count": 0,
            }

        collections_by_date[date_key]["schedules"].append(schedule)
        # Use suggested_amount if available, otherwise minimum_amount
        amount = schedule.suggested_amount if schedule.suggested_amount else schedule.minimum_amount
        collections_by_date[date_key]["total_amount"] += flt(amount)
        collections_by_date[date_key]["count"] += 1

    return list(collections_by_date.values())


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_sepa_configuration():
    """Validate SEPA configuration is complete"""
    payments_settings = get_payments_settings()

    required_fields = {
        "company_iban": "Company IBAN",
        "creditor_id": "Creditor ID (Incassant ID)",
        "company_account_holder": "Company Account Holder Name",
    }

    missing = []
    for field, label in required_fields.items():
        if not getattr(payments_settings, field, None):
            missing.append(label)

    if missing:
        return {"valid": False, "message": _("Missing SEPA configuration: {0}").format(", ".join(missing))}

    # Validate IBAN format
    try:
        from verenigingen.utils.validation.iban_validator import validate_iban

        iban_validation = validate_iban(payments_settings.company_iban)
    except ImportError:
        # Fallback if IBAN validator is not available
        iban_validation = {"valid": True, "bic": None}

    if not iban_validation["valid"]:
        return {"valid": False, "message": _("Invalid company IBAN: {0}").format(iban_validation["error"])}

    return {
        "valid": True,
        "message": _("SEPA configuration is valid"),
        "config": {
            "iban": payments_settings.company_iban,
            "bic": payments_settings.company_bic or iban_validation.get("bic"),
            "creditor_id": payments_settings.creditor_id,
            "account_holder": payments_settings.company_account_holder,
        },
    }
