import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import SEPAError, handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor

# Import comprehensive security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    critical_api,
    high_security_api,
)
from verenigingen.verenigingen_payments.utils.mandate_candidates import (
    log_ambiguous_mandate_refusal,
    unambiguous_active_mandate,
)
from verenigingen.verenigingen_payments.utils.sepa_input_validation import SEPAInputValidator


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def load_unpaid_invoices(date_range="overdue", membership_type: str | None = None, limit=100):
    """Load unpaid invoices for batch processing"""

    # Input validation. Guard with `is not None` so an explicit limit=0 (invalid)
    # is rejected rather than slipping through the falsy short-circuit.
    if limit is not None and (
        not isinstance(limit, int) or limit <= 0 or limit > SEPAInputValidator.MAX_BATCH_SIZE
    ):
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

    # Add membership type filter if specified.
    #
    # Invoices link to their billing schedule via `membership_dues_schedule_display`
    # (Sales Invoice has no `membership` field - filtering on it raised
    # DataError: "Field not permitted in query: membership", so this filter never
    # worked). The Membership Dues Schedule carries `membership_type`, so resolve
    # the type to its schedules and constrain the invoice query on that link.
    # A type with no matching schedules returns nothing, rather than silently
    # falling through and loading every unpaid invoice into the batch selector.
    if membership_type:
        schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"membership_type": membership_type}, pluck="name"
        )
        if not schedules:
            return []
        filters["membership_dues_schedule_display"] = ["in", schedules]

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
            "membership_dues_schedule_display as membership",
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
                -- Purpose filter, not a refinement: a member may legitimately hold an
                -- Active membership mandate AND an Active donation mandate, so
                -- `status = 'Active'` alone is ambiguous by construction and this join
                -- returned two rows for one membership (#597). These columns become the
                -- Direct Debit Batch row that the SEPA XML is generated from.
                LEFT JOIN `tabSEPA Mandate` sm
                    ON sm.member = mem.name
                    AND sm.status = 'Active'
                    AND sm.used_for_memberships = 1
                WHERE mds.name IN %(memberships)s
                ORDER BY mds.name, sm.creation DESC
            """,
                {"memberships": membership_ids},
                as_dict=True,
            )

            # Build lookup dictionary for O(1) access.
            #
            # The join is purpose-filtered (above), so under
            # `validate_single_active_mandate_per_purpose` there is at most ONE row
            # per membership and this loop is a no-op. It used to be a silent
            # tiebreak -- "keep the first (most recent)" across ALL Active mandates,
            # which handed a dues batch the IBAN of a newer donation-only mandate
            # (#597).
            #
            # A SECOND row for one membership now means two Active mandates sharing a
            # purpose, which `save()` refuses but `frappe.db.set_value` on `status`
            # still reaches. That is genuinely ambiguous, so the mandate fields are
            # blanked and the candidates logged rather than one being picked: an
            # operator sees an invoice with no IBAN and a reason, instead of a debit
            # against a guess. Mirrors `unambiguous_active_mandate` (#584).
            member_data_lookup = {}
            ambiguous = {}
            for row in member_mandate_data:
                existing = member_data_lookup.get(row.membership)
                if existing is None:
                    member_data_lookup[row.membership] = row
                    continue
                ambiguous.setdefault(row.membership, [existing]).append(row)

            for membership, candidates in ambiguous.items():
                chosen = member_data_lookup[membership]
                # LOG BEFORE BLANKING. `candidates[0]` IS `chosen` -- the same dict
                # object -- so blanking first destroyed half the evidence the log
                # exists to carry, and the Error Log read
                # "Candidates: None (None), MAND-NEW (NL02...)". The whole point of
                # refusing instead of guessing is that an operator can see WHICH
                # mandates collided.
                log_ambiguous_mandate_refusal(
                    chosen.member,
                    candidates,
                    "used_for_memberships",
                    "Ambiguous SEPA mandate in batch invoice list",
                )
                chosen.iban = None
                chosen.bic = None
                chosen.mandate_id = None
                chosen.sign_date = None

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
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_invoice_mandate_info(invoice: str):
    """Get mandate information for an invoice.

    The invoice/member half is one query; the mandate is resolved separately so an
    ambiguous pick can be REFUSED rather than ordered by recency (#584).
    """

    # Single query to get invoice, membership dues schedule, member, and mandate data
    result = frappe.db.sql(
        """
        SELECT
            si.name as invoice,
            si.membership_dues_schedule_display as membership,
            mem.name as member,
            mem.full_name as member_name
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMembership Dues Schedule` mds ON si.membership_dues_schedule_display = mds.name
        LEFT JOIN `tabMember` mem ON mds.member = mem.name
        WHERE si.name = %(invoice)s
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

    # Resolve the mandate separately, and REFUSE rather than order: the invoice was
    # given by name, so the old `ORDER BY sm.creation DESC LIMIT 1` was picking among
    # Active mandates, not among invoices, and its result is written straight into the
    # Direct Debit Batch row the SEPA XML is generated from (#584).
    choice = unambiguous_active_mandate(data.member, "SEPA Batch UI: ambiguous mandate (invoice row)")

    if choice.is_ambiguous:
        return {
            "valid": False,
            "error": _(
                "Member {0} has {1} active SEPA mandates; refusing to guess which IBAN "
                "to debit. Cancel all but one."
            ).format(data.member_name or data.member, choice.candidates),
        }

    if choice and choice.mandate.iban and choice.mandate.mandate_id:
        return {
            "iban": choice.mandate.iban,
            "bic": choice.mandate.bic,
            "mandate_reference": choice.mandate.mandate_id,
            "mandate_date": str(choice.mandate.sign_date) if choice.mandate.sign_date else "",
            "valid": True,
        }

    return {"valid": False, "error": _("No active SEPA mandate found")}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def validate_invoice_mandate(invoice: str, member: str):
    """Validate mandate for a specific invoice - optimized single query"""

    try:
        if not frappe.db.exists("Member", member):
            return {"valid": False, "error": _("Member not found")}

        # Same defect as `get_invoice_mandate_info` and, until #584, the same file:
        # the member is given BY NAME, so `ORDER BY sm.creation DESC LIMIT 1` was
        # picking among that member's Active mandates by recency. This one matters
        # more -- `direct_debit_batch.js:578` calls it in a loop over every invoice
        # in the batch and writes iban/bic/mandate_reference/mandate_date into each
        # child row, which is what the SEPA XML is generated from.
        choice = unambiguous_active_mandate(member, "SEPA Batch UI: ambiguous mandate (batch validation)")

        if choice.is_ambiguous:
            return {
                "valid": False,
                "error": _(
                    "Member {0} has {1} active SEPA mandates; refusing to guess which "
                    "IBAN to debit. Cancel all but one."
                ).format(member, choice.candidates),
            }

        if not choice:
            return {"valid": False, "error": _("No active SEPA mandate")}

        data = choice.mandate

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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def get_batch_analytics(batch_name: str):
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
@high_security_api(operation_type=OperationType.FINANCIAL)
def preview_sepa_xml(batch_name: str):
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
            "creditor_iban": frappe.db.get_single_value("Verenigingen Payments Settings", "company_iban"),
            "creditor_id": frappe.db.get_single_value("Verenigingen Payments Settings", "creditor_id"),
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


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
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
                [
                    "name",
                    "status",
                    "outstanding_amount",
                    "docstatus",
                    "member",
                    "membership_dues_schedule_display",
                    "currency",
                ],
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

            # SEPA Direct Debit is EUR-only. Reject non-EUR invoices rather than silently
            # batching them under the hardcoded EUR batch currency, which would otherwise
            # mis-state the collected amount.
            if invoice_doc.currency and invoice_doc.currency != "EUR":
                invoice_validation_errors.append(
                    f"Invoice {invoice['invoice']} is not in EUR (currency: {invoice_doc.currency}); "
                    "SEPA Direct Debit only supports EUR"
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

            # Resolve the membership from the AUTHORITATIVE link: the invoice's dues
            # schedule (membership_dues_schedule_display -> Membership Dues Schedule)
            # points to the exact Membership this invoice bills. Only fall back to an
            # arbitrary member lookup if that link is absent, and in the fallback prefer
            # an Active membership so we never mark an expired/wrong membership as paid.
            member_name = invoice_doc.member
            membership_name = None
            mds = invoice_doc.membership_dues_schedule_display
            if mds:
                membership_name = frappe.db.get_value("Membership Dues Schedule", mds, "membership")

            if not membership_name and member_name:
                # Fallback: dues-schedule link absent. Prefer an Active membership.
                membership_name = frappe.db.get_value(
                    "Membership", {"member": member_name, "status": "Active", "docstatus": 1}, "name"
                ) or frappe.db.get_value("Membership", {"member": member_name, "docstatus": 1}, "name")
                if membership_name:
                    frappe.logger().warning(
                        f"SEPA batch: invoice {invoice['invoice']} has no dues-schedule link; "
                        f"fell back to membership {membership_name} for member {member_name}"
                    )

            if not member_name or not membership_name:
                invoice_validation_errors.append(
                    f"Could not resolve member/membership for invoice {invoice['invoice']}"
                )
                continue

            enriched = dict(invoice)
            enriched["member"] = member_name
            enriched["membership"] = membership_name
            validated_invoices.append(enriched)

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
        # Reqd field is `batch_description` (not `description`); `currency` is also reqd.
        batch_doc.batch_description = cleaned_params.get(
            "description", f"SEPA Batch {cleaned_params['batch_date']}"
        )
        batch_doc.currency = "EUR"
        batch_doc.status = "Draft"

        # Add invoices to batch
        total_amount = 0
        for invoice in validated_invoices:
            batch_invoice = batch_doc.append("invoices", {})
            batch_invoice.invoice = invoice["invoice"]
            batch_invoice.amount = invoice["amount"]
            batch_invoice.currency = invoice.get("currency", "EUR")
            batch_invoice.member = invoice["member"]
            batch_invoice.membership = invoice["membership"]
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def validate_batch_invoices(invoice_list: str | list):
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def get_sepa_validation_constraints():
    """
    Get SEPA validation constraints for frontend validation

    Returns:
        Dictionary of validation rules and constraints
    """
    from verenigingen.verenigingen_payments.utils.sepa_input_validation import get_sepa_validation_rules

    return get_sepa_validation_rules()
