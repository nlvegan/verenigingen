import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import SEPAError, handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.sepa_input_validation import SEPAInputValidator


@handle_api_error
@frappe.whitelist()
def load_unpaid_invoices(date_range="overdue", membership_type=None, limit=100):
    """Load unpaid invoices for batch processing"""

    # Input validation
    if limit and (not isinstance(limit, int) or limit <= 0 or limit > SEPAInputValidator.MAX_BATCH_SIZE):
        raise SEPAError(_(f"Invalid limit. Must be between 1 and {SEPAInputValidator.MAX_BATCH_SIZE}"))

    valid_date_ranges = ["overdue", "due_this_week", "due_this_month", "all"]
    if date_range not in valid_date_ranges:
        raise SEPAError(_(f'Invalid date_range. Valid options: {", ".join(valid_date_ranges)}'))

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
        # Get memberships of this type
        memberships = frappe.get_all("Membership", filters={"membership_type": membership_type}, pluck="name")
        if memberships:
            filters["membership"] = ["in", memberships]

    # Get invoices
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


@frappe.whitelist()
def get_invoice_mandate_info(invoice):
    """Get mandate information for an invoice - optimized single query"""

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


@frappe.whitelist()
def validate_invoice_mandate(invoice, member):
    """Validate mandate for a specific invoice - optimized single query"""

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
@frappe.whitelist()
def get_batch_analytics(batch_name):
    """Get detailed analytics for a batch"""

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


@frappe.whitelist()
def preview_sepa_xml(batch_name):
    """Preview SEPA XML content before generation"""

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

    # Add transaction preview (first 5)
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
@frappe.whitelist()
def create_sepa_batch_validated(**params):
    """
    Create SEPA batch with comprehensive input validation

    Args:
        **params: Batch creation parameters including:
            - batch_date: Collection date (ISO format)
            - batch_type: SEPA batch type (CORE, B2B, COR1)
            - invoice_list: List of invoice dictionaries
            - description: Optional batch description

    Returns:
        Dictionary with batch creation result
    """
    # Comprehensive input validation
    validation_result = SEPAInputValidator.validate_batch_creation_params(**params)

    if not validation_result["valid"]:
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

        return {
            "success": True,
            "batch_name": batch_doc.name,
            "total_amount": total_amount,
            "invoice_count": len(validated_invoices),
            "warnings": validation_result.get("warnings", []),
            "message": f"SEPA batch created successfully with {len(validated_invoices)} invoices",
        }

    except Exception as e:
        frappe.log_error(f"SEPA batch creation error: {str(e)}", "SEPA Batch Creation")
        return {
            "success": False,
            "errors": [f"Batch creation failed: {str(e)}"],
            "message": "System error during batch creation",
        }


@handle_api_error
@frappe.whitelist()
def validate_batch_invoices(invoice_list):
    """
    Validate a list of invoices for SEPA batch processing

    Args:
        invoice_list: List of invoice dictionaries or JSON string

    Returns:
        Validation result with detailed feedback
    """
    import json

    # Handle JSON string input
    if isinstance(invoice_list, str):
        try:
            invoice_list = json.loads(invoice_list)
        except json.JSONDecodeError as e:
            return {"valid": False, "errors": [f"Invalid JSON format: {str(e)}"], "validated_invoices": []}

    # Use the comprehensive validator
    return SEPAInputValidator.validate_invoice_list(invoice_list)


@handle_api_error
@frappe.whitelist()
def get_sepa_validation_constraints():
    """
    Get SEPA validation constraints for frontend validation

    Returns:
        Dictionary of validation rules and constraints
    """
    from verenigingen.utils.sepa_input_validation import get_sepa_validation_rules

    return get_sepa_validation_rules()
