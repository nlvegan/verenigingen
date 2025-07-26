"""
Secure SEPA Batch UI API with Comprehensive Security Hardening

This module provides secure API endpoints for SEPA batch operations with:
- CSRF protection
- Rate limiting
- Comprehensive audit logging
- Role-based authorization
- Input validation
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

# Existing imports
from verenigingen.utils.error_handling import SEPAError, handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.audit_logging import AuditEventType, AuditSeverity, audit_log, log_sepa_event
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    require_sepa_create,
    require_sepa_permission,
    require_sepa_process,
    require_sepa_read,
)

# Security imports
from verenigingen.utils.security.csrf_protection import require_csrf_token
from verenigingen.utils.security.rate_limiting import (
    rate_limit_sepa_analytics,
    rate_limit_sepa_batch_creation,
    rate_limit_sepa_loading,
    rate_limit_sepa_validation,
)
from verenigingen.utils.sepa_input_validation import SEPAInputValidator


@handle_api_error
@require_csrf_token
@rate_limit_sepa_loading
@require_sepa_read
@audit_log("sepa_invoice_loading", "info", capture_args=True)
@frappe.whitelist()
def load_unpaid_invoices_secure(date_range="overdue", membership_type=None, limit=100):
    """
    Securely load unpaid invoices for batch processing

    Enhanced with comprehensive security measures:
    - CSRF protection
    - Rate limiting
    - Authorization checks
    - Input validation
    - Audit logging
    """

    # Input validation
    if limit and (not isinstance(limit, int) or limit <= 0 or limit > SEPAInputValidator.MAX_BATCH_SIZE):
        raise SEPAError(_(f"Invalid limit. Must be between 1 and {SEPAInputValidator.MAX_BATCH_SIZE}"))

    valid_date_ranges = ["overdue", "due_this_week", "due_this_month", "all"]
    if date_range not in valid_date_ranges:
        raise SEPAError(_(f'Invalid date_range. Valid options: {", ".join(valid_date_ranges)}'))

    # Log the operation
    log_sepa_event(
        AuditEventType.SEPA_INVOICE_LOADED.value,
        details={"date_range": date_range, "membership_type": membership_type, "limit": limit},
    )

    filters = {"status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1}

    # Add date range filter
    if date_range == "overdue":
        filters["due_date"] = ["<", today()]
    elif date_range == "due_this_week":
        filters["due_date"] = ["between", [today(), add_days(today(), 7)]]
    elif date_range == "due_this_month":
        filters["due_date"] = ["between", [today(), add_days(today(), 30)]]

    # Add membership type filter if specified
    if membership_type:
        # Validate membership type exists
        if not frappe.db.exists("Membership Type", membership_type):
            raise SEPAError(_(f"Invalid membership type: {membership_type}"))

        # Get memberships of this type
        memberships = frappe.get_all("Membership", filters={"membership_type": membership_type}, pluck="name")
        if memberships:
            filters["membership"] = ["in", memberships]

    # Get invoices with optimized query
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name as invoice",
            "customer",
            "outstanding_amount as amount",
            "currency",
            "due_date",
            "custom_membership_dues_schedule as membership",
        ],
        order_by="due_date",
        limit=limit,
    )

    # Optimized: Get member and mandate information in single batch query
    if invoices:
        membership_ids = [inv.membership for inv in invoices if inv.membership]

        if membership_ids:
            # Single query to get all member and mandate data
            member_mandate_data = frappe.db.sql(
                """
                SELECT
                    mds.name as membership,
                    mem.name as member,
                    mem.full_name as member_name,
                    sm.iban,
                    sm.bic,
                    sm.mandate_id,
                    sm.sign_date
                FROM `tabMembership Dues Schedule` mds
                JOIN `tabMember` mem ON mds.member = mem.name
                LEFT JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
                WHERE mds.name IN %(memberships)s
                ORDER BY mds.name, sm.creation DESC
            """,
                {"memberships": membership_ids},
                as_dict=True,
            )

            # Build lookup dictionary for O(1) access
            member_data_lookup = {}
            for row in member_mandate_data:
                # Only keep the first (most recent) mandate per membership
                if row.membership not in member_data_lookup:
                    member_data_lookup[row.membership] = row

            # Apply data to invoices in single loop
            for invoice in invoices:
                if invoice.membership and invoice.membership in member_data_lookup:
                    data = member_data_lookup[invoice.membership]
                    invoice.update(
                        {
                            "member": data.member,
                            "member_name": data.member_name,
                            "iban": data.iban or "",
                            "bic": data.bic or "",
                            "mandate_reference": data.mandate_id or "",
                            "mandate_date": str(data.sign_date) if data.sign_date else "",
                        }
                    )
                else:
                    # No membership or member data found
                    invoice.update(
                        {
                            "member": "",
                            "member_name": "",
                            "iban": "",
                            "bic": "",
                            "mandate_reference": "",
                            "mandate_date": "",
                        }
                    )
        else:
            # No memberships found, set empty values
            for invoice in invoices:
                invoice.update(
                    {
                        "member": "",
                        "member_name": "",
                        "iban": "",
                        "bic": "",
                        "mandate_reference": "",
                        "mandate_date": "",
                    }
                )

    return invoices


@handle_api_error
@require_csrf_token
@rate_limit_sepa_validation
@require_sepa_read
@audit_log("sepa_mandate_info_retrieval", "info")
@frappe.whitelist()
def get_invoice_mandate_info_secure(invoice):
    """
    Securely get mandate information for an invoice

    Enhanced with security measures
    """

    # Validate invoice parameter
    if not invoice:
        raise SEPAError(_("Invoice parameter is required"))

    # Verify invoice exists and user has access
    if not frappe.db.exists("Sales Invoice", invoice):
        raise SEPAError(_("Invoice not found: {0}").format(invoice))

    # Log the operation
    log_sepa_event(
        AuditEventType.SEPA_MANDATE_VALIDATED.value,
        details={"invoice": invoice, "operation": "mandate_info_retrieval"},
    )

    # Single query to get invoice, membership dues schedule, member, and mandate data
    result = frappe.db.sql(
        """
        SELECT
            si.name as invoice,
            si.custom_membership_dues_schedule as membership,
            mem.name as member,
            mem.full_name as member_name,
            sm.iban,
            sm.bic,
            sm.mandate_id,
            sm.sign_date,
            sm.status as mandate_status
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMembership Dues Schedule` mds ON si.custom_membership_dues_schedule = mds.name
        LEFT JOIN `tabMember` mem ON mds.member = mem.name
        LEFT JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
        WHERE si.name = %(invoice)s
        ORDER BY sm.creation DESC
        LIMIT 1
    """,
        {"invoice": invoice},
        as_dict=True,
    )

    if not result:
        return None

    data = result[0]

    if not data.membership:
        return None

    if not data.member:
        return None

    if data.iban and data.mandate_id:
        return {
            "iban": data.iban,
            "bic": data.bic,
            "mandate_reference": data.mandate_id,
            "mandate_date": str(data.sign_date) if data.sign_date else "",
            "valid": True,
        }

    return {"valid": False, "error": _("No active SEPA mandate found")}


@handle_api_error
@require_csrf_token
@rate_limit_sepa_validation
@require_sepa_permission(SEPAOperation.INVOICE_VALIDATE)
@audit_log("sepa_mandate_validation", "info")
@frappe.whitelist()
def validate_invoice_mandate_secure(invoice, member):
    """
    Securely validate mandate for a specific invoice

    Enhanced with comprehensive security and validation
    """

    # Validate parameters
    if not invoice:
        raise SEPAError(_("Invoice parameter is required"))
    if not member:
        raise SEPAError(_("Member parameter is required"))

    # Verify entities exist
    if not frappe.db.exists("Sales Invoice", invoice):
        raise SEPAError(_("Invoice not found: {0}").format(invoice))
    if not frappe.db.exists("Member", member):
        raise SEPAError(_("Member not found: {0}").format(member))

    # Log the operation
    log_sepa_event(
        AuditEventType.SEPA_MANDATE_VALIDATED.value,
        details={"invoice": invoice, "member": member, "operation": "mandate_validation"},
    )

    try:
        # Single query to get member and active mandate data
        result = frappe.db.sql(
            """
            SELECT
                mem.name as member,
                mem.full_name as member_name,
                sm.name as mandate_name,
                sm.iban,
                sm.bic,
                sm.mandate_id,
                sm.sign_date,
                sm.first_collection_date,
                sm.expiry_date,
                sm.status
            FROM `tabMember` mem
            LEFT JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
            WHERE mem.name = %(member)s
            ORDER BY sm.creation DESC
            LIMIT 1
        """,
            {"member": member},
            as_dict=True,
        )

        if not result:
            return {"valid": False, "error": _("Member not found")}

        data = result[0]

        if not data.iban or not data.mandate_id:
            return {"valid": False, "error": _("No active SEPA mandate")}

        # Validate IBAN
        from verenigingen.utils.validation.iban_validator import validate_iban

        iban_validation = validate_iban(data.iban)

        if not iban_validation["valid"]:
            return {"valid": False, "error": iban_validation["message"]}

        # Check mandate expiry
        if data.expiry_date and getdate(data.expiry_date) < getdate(today()):
            return {"valid": False, "error": _("Mandate has expired")}

        return {
            "valid": True,
            "iban": data.iban,
            "bic": data.bic,
            "mandate_reference": data.mandate_id,
            "mandate_date": str(data.sign_date) if data.sign_date else "",
        }

    except Exception as e:
        return {"valid": False, "error": str(e)}


@handle_api_error
@require_csrf_token
@rate_limit_sepa_analytics
@require_sepa_read
@audit_log("sepa_batch_analytics", "info")
@frappe.whitelist()
def get_batch_analytics_secure(batch_name):
    """
    Securely get detailed analytics for a batch

    Enhanced with authorization and audit logging
    """

    # Validate batch parameter
    if not batch_name:
        raise SEPAError(_("Batch name is required"))

    # Verify batch exists and user has access
    if not frappe.db.exists("Direct Debit Batch", batch_name):
        raise SEPAError(_("Batch not found: {0}").format(batch_name))

    # Log the operation
    log_sepa_event(
        AuditEventType.SEPA_BATCH_VALIDATED.value,
        details={"batch_name": batch_name, "operation": "analytics_retrieval"},
    )

    batch = frappe.get_doc("Direct Debit Batch", batch_name)

    analytics = {
        "summary": {
            "total_invoices": len(batch.invoices),
            "total_amount": batch.total_amount,
            "status": batch.status,
        },
        "by_status": {},
        "by_member": {},
        "issues": [],
    }

    # Analyze by status
    status_counts = {}
    status_amounts = {}

    for inv in batch.invoices:
        status = inv.status or "Pending"
        status_counts[status] = status_counts.get(status, 0) + 1
        status_amounts[status] = status_amounts.get(status, 0) + inv.amount

        # Check for issues
        if not inv.iban:
            analytics["issues"].append(
                {"invoice": inv.invoice, "member": inv.member_name, "issue": "Missing IBAN"}
            )
        elif not inv.mandate_reference:
            analytics["issues"].append(
                {"invoice": inv.invoice, "member": inv.member_name, "issue": "Missing mandate reference"}
            )

    analytics["by_status"] = [
        {"status": status, "count": count, "amount": status_amounts.get(status, 0)}
        for status, count in status_counts.items()
    ]

    return analytics


@handle_api_error
@require_csrf_token
@rate_limit_sepa_analytics
@require_sepa_read
@audit_log("sepa_xml_preview", "info")
@frappe.whitelist()
def preview_sepa_xml_secure(batch_name):
    """
    Securely preview SEPA XML content before generation

    Enhanced with security measures and sensitive data protection
    """

    # Validate batch parameter
    if not batch_name:
        raise SEPAError(_("Batch name is required"))

    # Verify batch exists and user has access
    if not frappe.db.exists("Direct Debit Batch", batch_name):
        raise SEPAError(_("Batch not found: {0}").format(batch_name))

    # Log the operation
    log_sepa_event(
        AuditEventType.SEPA_XML_GENERATED.value,
        details={"batch_name": batch_name, "operation": "xml_preview"},
    )

    batch = frappe.get_doc("Direct Debit Batch", batch_name)

    # Generate preview data
    preview = {
        "header": {
            "message_id": f"BATCH-{batch.name}",
            "creation_datetime": frappe.utils.now(),
            "number_of_transactions": len(batch.invoices),
            "control_sum": batch.total_amount,
        },
        "payment_info": {
            "collection_date": str(batch.batch_date),
            "batch_type": batch.batch_type,
            "creditor_name": frappe.db.get_single_value("Verenigingen Settings", "company_name"),
            "creditor_iban": frappe.db.get_single_value("Verenigingen Settings", "company_iban"),
            "creditor_id": frappe.db.get_single_value("Verenigingen Settings", "creditor_id"),
        },
        "transactions": [],
    }

    # Add transaction preview (first 5) with sensitive data protection
    for i, inv in enumerate(batch.invoices[:5]):
        preview["transactions"].append(
            {
                "end_to_end_id": f"E2E-{inv.invoice}",
                "amount": inv.amount,
                "debtor_name": inv.member_name,
                "debtor_iban": inv.iban[:4] + "****" + inv.iban[-4:] if inv.iban else "Missing",
                "mandate_id": inv.mandate_reference or "Missing",
                "description": f"Invoice {inv.invoice}",
            }
        )

    if len(batch.invoices) > 5:
        preview["more_transactions"] = len(batch.invoices) - 5

    return preview


@handle_api_error
@require_csrf_token
@rate_limit_sepa_batch_creation
@require_sepa_create
@audit_log("sepa_batch_creation", "info", capture_args=True)
@frappe.whitelist()
def create_sepa_batch_validated_secure(**params):
    """
    Securely create SEPA batch with comprehensive security measures

    Enhanced with:
    - CSRF protection
    - Rate limiting
    - Authorization checks
    - Comprehensive input validation
    - Audit logging
    - Sensitive data handling
    """

    # Log the batch creation attempt
    log_sepa_event(
        AuditEventType.SEPA_BATCH_CREATED.value,
        details={
            "operation": "batch_creation_attempt",
            "params_count": len(params),
            "has_invoice_list": "invoice_list" in params,
            "invoice_count": len(params.get("invoice_list", []))
            if isinstance(params.get("invoice_list"), list)
            else 0,
        },
        severity=AuditSeverity.INFO,
    )

    # Comprehensive input validation
    validation_result = SEPAInputValidator.validate_batch_creation_params(**params)

    if not validation_result["valid"]:
        log_sepa_event(
            "sepa_batch_creation_validation_failed",
            details={
                "errors": validation_result["errors"],
                "warnings": validation_result.get("warnings", []),
            },
            severity=AuditSeverity.WARNING,
        )
        return {
            "success": False,
            "errors": validation_result["errors"],
            "warnings": validation_result.get("warnings", []),
            "message": "Input validation failed",
        }

    cleaned_params = validation_result["cleaned_params"]

    try:
        # Check for existing batches on the same date
        existing_batches = frappe.get_all(
            "Direct Debit Batch",
            filters={"batch_date": cleaned_params["batch_date"], "docstatus": ["!=", 2]},  # Not cancelled
            fields=["name", "status", "total_amount"],
        )

        if existing_batches:
            log_sepa_event(
                "sepa_batch_creation_duplicate_date",
                details={
                    "batch_date": cleaned_params["batch_date"],
                    "existing_batches": [b.name for b in existing_batches],
                },
                severity=AuditSeverity.WARNING,
            )
            return {
                "success": False,
                "errors": [f"Batch already exists for date {cleaned_params['batch_date']}"],
                "existing_batches": existing_batches,
                "message": "Duplicate batch date detected",
            }

        # Additional business validation
        invoice_validation_errors = []
        validated_invoices = []

        for invoice in cleaned_params["invoice_list"]:
            # Check if invoice exists and is unpaid
            invoice_doc = frappe.db.get_value(
                "Sales Invoice",
                invoice["invoice"],
                ["name", "status", "outstanding_amount", "docstatus"],
                as_dict=True,
            )

            if not invoice_doc:
                invoice_validation_errors.append(f"Invoice not found: {invoice['invoice']}")
                continue

            if invoice_doc.docstatus != 1:
                invoice_validation_errors.append(f"Invoice not submitted: {invoice['invoice']}")
                continue

            if invoice_doc.status not in ["Unpaid", "Overdue"]:
                invoice_validation_errors.append(
                    f"Invoice not unpaid: {invoice['invoice']} (status: {invoice_doc.status})"
                )
                continue

            if float(invoice_doc.outstanding_amount) != float(invoice["amount"]):
                invoice_validation_errors.append(
                    f"Amount mismatch for {invoice['invoice']}: "
                    f"Expected {invoice_doc.outstanding_amount}, got {invoice['amount']}"
                )
                continue

            # Check if invoice is already in another active batch
            existing_batch_invoice = frappe.db.get_value(
                "Direct Debit Batch Invoice",
                {"invoice": invoice["invoice"], "docstatus": ["!=", 2]},
                ["parent"],
                as_dict=True,
            )

            if existing_batch_invoice:
                batch_doc = frappe.get_doc("Direct Debit Batch", existing_batch_invoice.parent)
                if batch_doc.status not in ["Cancelled", "Failed"]:
                    invoice_validation_errors.append(
                        f"Invoice {invoice['invoice']} already in batch {existing_batch_invoice.parent}"
                    )
                    continue

            validated_invoices.append(invoice)

        if invoice_validation_errors:
            log_sepa_event(
                "sepa_batch_creation_invoice_validation_failed",
                details={
                    "validation_errors": invoice_validation_errors,
                    "failed_count": len(invoice_validation_errors),
                    "total_invoices": len(cleaned_params["invoice_list"]),
                },
                severity=AuditSeverity.WARNING,
            )
            return {
                "success": False,
                "errors": invoice_validation_errors,
                "message": f"Invoice validation failed for {len(invoice_validation_errors)} invoices",
            }

        if not validated_invoices:
            return {
                "success": False,
                "errors": ["No valid invoices to process"],
                "message": "No invoices available for batch creation",
            }

        # Create the SEPA batch document
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = cleaned_params["batch_date"]
        batch_doc.batch_type = cleaned_params["batch_type"]
        batch_doc.description = cleaned_params.get(
            "description", f"SEPA Batch {cleaned_params['batch_date']}"
        )
        batch_doc.status = "Draft"

        # Add invoices to batch
        total_amount = 0
        for invoice in validated_invoices:
            batch_invoice = batch_doc.append("invoices", {})
            batch_invoice.invoice = invoice["invoice"]
            batch_invoice.amount = invoice["amount"]
            batch_invoice.currency = invoice.get("currency", "EUR")
            batch_invoice.member_name = invoice["member_name"]
            batch_invoice.iban = invoice["iban"]
            batch_invoice.bic = invoice.get("bic", "")
            batch_invoice.mandate_reference = invoice["mandate_reference"]
            batch_invoice.status = "Pending"

            total_amount += float(invoice["amount"])

        batch_doc.total_amount = total_amount
        batch_doc.insert()

        # Log successful batch creation
        log_sepa_event(
            AuditEventType.SEPA_BATCH_CREATED.value,
            details={
                "batch_name": batch_doc.name,
                "batch_date": cleaned_params["batch_date"],
                "batch_type": cleaned_params["batch_type"],
                "invoice_count": len(validated_invoices),
                "total_amount": total_amount,
                "operation": "batch_creation_success",
            },
            severity=AuditSeverity.INFO,
        )

        return {
            "success": True,
            "batch_name": batch_doc.name,
            "total_amount": total_amount,
            "invoice_count": len(validated_invoices),
            "warnings": validation_result.get("warnings", []),
            "message": f"SEPA batch created successfully with {len(validated_invoices)} invoices",
        }

    except Exception as e:
        # Log batch creation failure
        log_sepa_event(
            "sepa_batch_creation_system_error",
            details={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "operation": "batch_creation_failed",
            },
            severity=AuditSeverity.ERROR,
        )

        frappe.log_error(f"SEPA batch creation error: {str(e)}", "SEPA Batch Creation")
        return {
            "success": False,
            "errors": [f"Batch creation failed: {str(e)}"],
            "message": "System error during batch creation",
        }


@handle_api_error
@require_csrf_token
@rate_limit_sepa_validation
@require_sepa_permission(SEPAOperation.BATCH_VALIDATE)
@audit_log("sepa_batch_invoice_validation", "info")
@frappe.whitelist()
def validate_batch_invoices_secure(invoice_list):
    """
    Securely validate a list of invoices for SEPA batch processing

    Enhanced with comprehensive security measures
    """

    import json

    # Log validation attempt
    log_sepa_event(
        AuditEventType.SEPA_BATCH_VALIDATED.value,
        details={
            "operation": "invoice_list_validation",
            "list_type": type(invoice_list).__name__,
            "list_length": len(invoice_list) if isinstance(invoice_list, list) else "unknown",
        },
    )

    # Handle JSON string input
    if isinstance(invoice_list, str):
        try:
            invoice_list = json.loads(invoice_list)
        except json.JSONDecodeError as e:
            log_sepa_event(
                "sepa_invoice_validation_json_error",
                details={
                    "error": str(e),
                    "input_preview": str(invoice_list)[:100] + "..."
                    if len(str(invoice_list)) > 100
                    else str(invoice_list),
                },
                severity=AuditSeverity.ERROR,
            )
            return {"valid": False, "errors": [f"Invalid JSON format: {str(e)}"], "validated_invoices": []}

    # Use the comprehensive validator
    result = SEPAInputValidator.validate_invoice_list(invoice_list)

    # Log validation result
    log_sepa_event(
        AuditEventType.SEPA_BATCH_VALIDATED.value,
        details={
            "operation": "invoice_list_validation_complete",
            "valid": result["valid"],
            "error_count": len(result.get("errors", [])),
            "warning_count": len(result.get("warnings", [])),
            "validated_count": len(result.get("validated_invoices", [])),
        },
        severity=AuditSeverity.INFO if result["valid"] else AuditSeverity.WARNING,
    )

    return result


# API endpoint to get SEPA validation constraints with security
@handle_api_error
@require_sepa_read
@frappe.whitelist()
def get_sepa_validation_constraints_secure():
    """
    Securely get SEPA validation constraints for frontend validation

    Enhanced with authorization checks
    """
    from verenigingen.utils.sepa_input_validation import get_sepa_validation_rules

    log_sepa_event(
        "sepa_validation_constraints_retrieved", details={"operation": "validation_constraints_request"}
    )

    return get_sepa_validation_rules()


# Health check endpoint for security monitoring
@frappe.whitelist(allow_guest=False)
def sepa_security_health_check():
    """
    Security health check endpoint for monitoring

    Returns status of security systems
    """
    try:
        from verenigingen.utils.security.audit_logging import get_audit_logger
        from verenigingen.utils.security.authorization import get_auth_manager
        from verenigingen.utils.security.csrf_protection import get_csrf_token
        from verenigingen.utils.security.rate_limiting import get_rate_limiter

        # Test each security component
        health_status = {
            "csrf_protection": {"status": "unknown", "details": {}},
            "rate_limiting": {"status": "unknown", "details": {}},
            "authorization": {"status": "unknown", "details": {}},
            "audit_logging": {"status": "unknown", "details": {}},
        }

        # Test CSRF protection
        try:
            csrf_result = get_csrf_token()
            health_status["csrf_protection"] = {
                "status": "healthy" if csrf_result.get("success") else "error",
                "details": {"token_generated": csrf_result.get("success", False)},
            }
        except Exception as e:
            health_status["csrf_protection"] = {"status": "error", "details": {"error": str(e)}}

        # Test rate limiting
        try:
            limiter = get_rate_limiter()
            health_status["rate_limiting"] = {"status": "healthy", "details": {"backend": limiter.backend}}
        except Exception as e:
            health_status["rate_limiting"] = {"status": "error", "details": {"error": str(e)}}

        # Test authorization
        try:
            auth_manager = get_auth_manager()
            permissions = auth_manager.get_user_permissions()
            health_status["authorization"] = {
                "status": "healthy",
                "details": {"permissions_count": len(permissions)},
            }
        except Exception as e:
            health_status["authorization"] = {"status": "error", "details": {"error": str(e)}}

        # Test audit logging
        try:
            audit_logger = get_audit_logger()
            health_status["audit_logging"] = {
                "status": "healthy",
                "details": {"logger_available": audit_logger is not None},
            }
        except Exception as e:
            health_status["audit_logging"] = {"status": "error", "details": {"error": str(e)}}

        # Overall health
        all_healthy = all(status["status"] == "healthy" for status in health_status.values())

        return {
            "success": True,
            "overall_health": "healthy" if all_healthy else "degraded",
            "components": health_status,
            "timestamp": frappe.utils.now(),
        }

    except Exception as e:
        return {"success": False, "overall_health": "error", "error": str(e), "timestamp": frappe.utils.now()}
