"""
Payment processing utilities for membership applications
"""

import random
import string

import frappe
from frappe import _
from frappe.utils import add_days, cint, today

from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


def create_membership_invoice_with_amount(member, membership, amount):
    """Create invoice with specific amount (custom or standard)"""
    try:
        from verenigingen.utils import DutchTaxExemptionHandler
    except ImportError:
        DutchTaxExemptionHandler = None

    # Legacy subscription utilities have been replaced by dues schedule system

    settings = frappe.get_single("Verenigingen Settings")

    # Create or get customer
    if not member.customer:
        customer = create_customer_for_member(member)
        member.db_set("customer", customer.name)

    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    # Legacy subscription period calculation replaced by dues schedule system

    # Calculate coverage period for the first billing cycle
    # billing_period is optional on membership type - default to Annual if not set
    billing_period = getattr(membership_type, "billing_period", None) or "Annual"
    period_start = today()
    period_end = coverage_end_for_billing_period(
        billing_period,
        period_start,
        getattr(membership_type, "billing_period_in_months", None),
    )

    # Determine invoice description with coverage period
    description = f"Membership Fee - {membership_type.membership_type_name}"
    if hasattr(membership, "uses_custom_amount") and membership.uses_custom_amount:
        # Get suggested amount from template for comparison
        template = load_template_for_membership_type(membership_type)
        suggested_amount = template.suggested_amount or 0

        if amount > suggested_amount:
            description += " (Supporter Contribution)"
        elif amount < suggested_amount:
            description += " (Reduced Rate)"

    # Add coverage period to description
    if billing_period == "Daily":
        description += f" - {billing_period} fee for {period_start}"
    else:
        description += f" - {billing_period} period: {period_start} to {period_end}"

    # Create invoice with dues schedule system
    invoice_data = {
        "doctype": "Sales Invoice",
        "company": settings.company,  # Use company from Verenigingen Settings
        "customer": member.customer,
        "member": member.name,
        # Flag as a membership invoice, consistent with the other membership
        # invoice creation paths (services/billing/invoice_generator.py and the
        # Mollie dues processor). Without this, invoices created during
        # application approval are invisible to strict is_membership_invoice=1
        # queries used by reconciliation (invoice_matcher) and reporting
        # (background_jobs), even though they set the `member` link.
        "is_membership_invoice": 1,
        # Link the invoice to the Membership record (Link(Membership) custom
        # field on Sales Invoice). Consistent with the dues generator
        # (services/billing/invoice_generator.py), and required for the
        # membership -> invoices lookup (membership.get_membership_invoices).
        "membership": membership.name,
        "posting_date": today(),
        "due_date": add_days(today(), 14),
        "custom_coverage_start_date": period_start,  # Set coverage period start
        "custom_coverage_end_date": period_end,  # Set coverage period end
        "items": [
            {
                "item_code": get_membership_item(membership_type),
                "qty": 1,
                "rate": amount,
                "description": description,
            }
        ],
        "remarks": f"Membership application invoice for {member.full_name}\nFirst billing period: {period_start} to {period_end}",
    }

    # The dues schedule system handles billing periods automatically

    invoice = frappe.get_doc(invoice_data)

    # Apply tax exemption if configured
    if settings.tax_exempt_for_contributions and DutchTaxExemptionHandler:
        try:
            handler = DutchTaxExemptionHandler()
            handler.apply_exemption_to_invoice(invoice, "EXEMPT_MEMBERSHIP")
        except Exception as e:
            frappe.log_error(
                message=f"Error applying tax exemption: {str(e)}",
                title="Tax Exemption Error",
            )

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    result = secure_document_operation(
        operation="insert",
        doc=invoice,
        justification=f"Create membership invoice for member {member.name} amount €{amount} - financial processing for membership application",
        required_permissions=["Sales Invoice:create"],
    )

    if not result.success:
        frappe.log_error(
            message=f"Failed to create membership invoice: {'; '.join(result.errors)}",
            title="Membership Invoice Security",
        )
        frappe.throw(_("Failed to create membership invoice. Please contact support."))

    # Get the created invoice document using the doc_name from SecureOperationResult
    invoice = frappe.get_doc("Sales Invoice", result.doc_name)

    # Submit through the SAME secure-operation escalation used for the insert.
    # The approver (e.g. Verenigingen Administrator) is not expected to hold
    # Sales Invoice permissions — that is precisely why the insert escalates to
    # the system user. Calling invoice.submit() directly here would run under the
    # approver's session and raise PermissionError whenever they lack
    # "Sales Invoice:submit" (which the app ships to no role), silently dropping
    # the invoice. Escalate the submit the same way the insert is escalated.
    submit_result = secure_document_operation(
        operation="submit",
        doc=invoice,
        justification=f"Submit membership invoice {invoice.name} for member {member.name} - financial processing for membership application",
        required_permissions=["Sales Invoice:submit"],
    )

    if not submit_result.success:
        frappe.log_error(
            message=f"Failed to submit membership invoice {invoice.name}: {'; '.join(submit_result.errors)}",
            title="Membership Invoice Security",
        )
        frappe.throw(_("Failed to submit membership invoice. Please contact support."))

    invoice.reload()

    return invoice


# Membership Type.billing_period has its own vocabulary ("Biannual", "Lifetime")
# while the billing pipeline's coverage functions use billing-frequency names
# ("Semi-Annual", ...). The same Biannual -> Semi-Annual translation is applied by
# ContributionAmendmentApprovalService._get_billing_frequency.
_BILLING_PERIOD_TO_FREQUENCY = {
    "Daily": "Daily",
    "Monthly": "Monthly",
    "Quarterly": "Quarterly",
    "Biannual": "Semi-Annual",
    "Annual": "Annual",
    "Custom": "Custom",
}


def coverage_end_for_billing_period(billing_period, period_start, billing_period_in_months=None):
    """Last day, INCLUSIVE, of the first billing period starting at period_start.

    Delegates to billing_period_calculator.calculate_coverage_end so this path
    seeds the coverage sequence that the rest of the billing pipeline continues.
    Every other path ends a period the day BEFORE the next one starts; computing
    it here as add_years(start, 1) produced a 366-day period whose last day was
    already the next period's first day, and CoverageCalculator's sequential
    branch (which rolls each later period off previous_end + 1) then carried that
    one-day drift through every subsequent period (#206).

    Args:
        billing_period: A Membership Type ``billing_period`` value, or empty.
        period_start: First day of the period.
        billing_period_in_months: Period length for a Custom billing_period.

    Returns:
        date: Last day of the period.
    """
    from verenigingen.services.billing.billing_period_calculator import calculate_coverage_end

    # Lifetime, blank and anything unrecognised keep this path's long-standing
    # "default to annual" first period - NOT the Monthly that
    # calculate_coverage_end falls back to for an unknown frequency.
    billing_frequency = _BILLING_PERIOD_TO_FREQUENCY.get(billing_period, "Annual")

    if billing_frequency == "Custom":
        # billing_period_in_months is an unvalidated Int, so 0 and negatives both
        # reach here. calculate_coverage_end turns anything < 1 into a MONTHLY
        # period, which is not what "Custom" asked for - clamp to the 12-month
        # default this path has always used instead.
        months = cint(billing_period_in_months)
        if months < 1:
            months = 12
        return calculate_coverage_end("Custom", period_start, months, "Months")

    return calculate_coverage_end(billing_frequency, period_start)


# The Customer Group resolution helper lives in
# verenigingen.services.customer_group_resolver - shared across the donor,
# donation, Mollie orphan-customer, and eBoekhouden Customer-creation paths.


def create_customer_for_member(member):
    """Create customer record for member with proper Contact integration"""
    # Check if customer already exists for this member
    existing_customer = frappe.db.get_value("Customer", {"member": member.name}, "name")
    if existing_customer:
        frappe.logger().info(f"Customer {existing_customer} already exists for Member {member.name}")
        return frappe.get_doc("Customer", existing_customer)

    # Validate permissions
    if not frappe.has_permission("Customer", "create"):
        frappe.throw(_("Insufficient permissions to create Customer"))

    if not frappe.has_permission("Contact", "create"):
        frappe.throw(_("Insufficient permissions to create Contact"))

    # Manual savepoint: Frappe's `savepoint(catch=Exception)` context manager rolls
    # back and *suppresses* the exception, leaving the caller with a rolled-back
    # Customer doc and no error signal. We want to roll back AND re-raise so the
    # caller knows creation failed. The naming convention matches Frappe's own
    # savepoint helper in frappe.database.database.savepoint().
    savepoint_name = "".join(random.sample(string.ascii_lowercase, 10))
    frappe.db.savepoint(savepoint_name)
    try:
        # Create Customer record (without direct email/mobile - these come from Contact via fetch_from)
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": member.full_name,
                "customer_type": "Individual",
                "customer_group": resolve_non_group_customer_group(),
                "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
                "member": member.name,  # Direct link to member record
            }
        )
        insert_customer_with_duplicate_retry(customer)

        # Create Contact record using existing Dutch name utilities
        contact = create_contact_for_customer(customer, member)
        if not contact:
            frappe.throw(_("Failed to create Contact for Customer"))

        # Set primary contact. The email_id/mobile_no fields use fetch_from on
        # customer_primary_contact, but fetch_from only runs during a full
        # document save - not on db_set - so we populate them explicitly here to
        # keep the Customer's denormalised contact fields in sync with the
        # primary Contact.
        primary_email = next((e.email_id for e in contact.email_ids if e.is_primary), None) or (
            contact.email_ids[0].email_id if contact.email_ids else None
        )
        primary_mobile = next((p.phone for p in contact.phone_nos if p.is_primary_mobile_no), None) or (
            contact.phone_nos[0].phone if contact.phone_nos else None
        )
        # Only set fields we actually resolved, so a contact without email/phone
        # doesn't null out a Customer's existing email_id/mobile_no.
        customer_fields = {"customer_primary_contact": contact.name}
        if primary_email:
            customer_fields["email_id"] = primary_email
        if primary_mobile:
            customer_fields["mobile_no"] = primary_mobile
        customer.db_set(customer_fields, update_modified=False)
    except NON_RESUMABLE_DB_ERRORS:
        # A 1213 has already rolled the ENTIRE transaction back, savepoints
        # included, so the rollback below cannot run: it raises 1305 and that
        # 1305 REPLACES the deadlock as the propagating exception. Every caller
        # then asks "is this a deadlock?" of an OperationalError and gets False,
        # so the one error that must never be swallowed is the one that always
        # is. Measured on test_site_1 with two contending connections; the
        # non-victim control kept its savepoint, so this is the deadlock's doing.
        # Same order as utils/transaction_errors.py::_atomically. There is
        # nothing left to undo and nothing safe to resume. See #561 for the
        # other 15 handlers in this shape.
        raise
    except Exception as e:
        frappe.db.rollback(save_point=savepoint_name)
        # frappe.log_error signature is (title, message, ...). A positional
        # call with the long detail string first stores it as `title` (the
        # 140-char `method` field in Error Log) - the framework either
        # self-truncates and loses context or raises CharacterLengthExceeded
        # depending on version. Keyword args sidestep the ordering hazard.
        frappe.log_error(
            message=f"Failed to create Customer for Member {member.name}: {str(e)}",
            title="Customer Creation Error",
        )
        raise

    frappe.db.release_savepoint(savepoint_name)
    frappe.logger().info(
        f"Created Customer {customer.name} with Contact {contact.name} for Member {member.name}"
    )
    return customer


def insert_customer_with_duplicate_retry(customer_doc, max_attempts=3):
    """Insert a Customer, retrying on a duplicate-name primary-key collision.

    With Selling Settings ``cust_master_name = "Customer Name"`` a Customer's
    ``name`` IS its ``customer_name`` (here, the member's full name). ERPNext's
    ``get_customer_name`` de-duplicates by check-then-suffix (``Name - 1``,
    ``Name - 2`` ...), but that check and the subsequent insert are not atomic:
    two members who share a full name -- or a delete-then-recreate, which is what
    co-located tests trigger -- can both derive the same name and one insert
    collides on the PK. Previously that ``DuplicateEntryError`` aborted Customer
    creation for the losing member entirely (its approval / invoice failed).

    Retrying re-runs autoname; the now-present sibling makes ``get_customer_name``
    append the next free suffix, so the retry lands on a unique name. Each attempt
    is isolated by its own savepoint so a failed insert never poisons the caller's
    transaction, and the loop is bounded so a genuine (non-collision) error still
    surfaces. See docs/plans/2026-06-07-customer-naming-fragility-proposal.md.
    """
    for attempt in range(1, max_attempts + 1):
        savepoint = f"cust_insert_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        try:
            customer_doc.insert()
            frappe.db.release_savepoint(savepoint)
            return customer_doc
        except frappe.exceptions.DuplicateEntryError:
            frappe.db.rollback(save_point=savepoint)
            if attempt == max_attempts:
                raise
            # Clear the assigned name + naming flag so the next insert re-derives
            # the ' - N' suffix via autoname instead of reusing the collided name.
            customer_doc.name = None
            customer_doc.flags.name_set = False


def get_membership_item(membership_type):
    """Get membership item for membership type - requires explicit creation"""
    # Note: membership_item field does not exist in current Membership Type DocType
    # Item creation is handled through membership type controller methods

    # Fallback to membership type's own method if available
    if hasattr(membership_type, "get_or_create_membership_item"):
        return membership_type.get_or_create_membership_item()

    # If no explicit configuration, require manual setup
    frappe.throw(
        f"No membership item configured for membership type '{membership_type.membership_type_name}'. "
        "Please create the item manually through the membership type controller. "
        "Auto-creation has been disabled to ensure proper item configuration."
    )


def get_payment_methods():
    """Get available payment methods"""
    try:
        payment_methods = frappe.get_all(
            "Mode of Payment", filters={"enabled": 1}, fields=["name", "mode_of_payment"], order_by="name"
        )

        # Add descriptions for common methods
        method_descriptions = {
            "Bank Transfer": "Direct bank transfer (SEPA)",
            "PayPal": "PayPal payment",
            "iDEAL": "iDEAL (Netherlands)",
            "Cash": "Cash payment (in-person only)",
        }

        for method in payment_methods:
            method["description"] = method_descriptions.get(method["name"], "")

        return {"success": True, "payment_methods": payment_methods}

    except Exception as e:
        frappe.log_error(f"Error getting payment methods: {str(e)}")
        return {"success": False, "error": str(e), "payment_methods": []}


def calculate_membership_amount_with_discounts(membership_type, data):
    """Calculate membership amount considering any applicable discounts"""
    # Get base amount from template
    template = load_template_for_membership_type(membership_type)

    if getattr(template, "suggested_amount", None) and template.suggested_amount < 0:
        frappe.throw(
            f"Dues Schedule Template '{template.name}' cannot have negative suggested_amount: {template.suggested_amount}"
        )

    # Resolve base amount: suggested_amount → dues_rate → minimum_amount
    base_amount = float(
        template.suggested_amount
        or getattr(template, "dues_rate", None)
        or getattr(membership_type, "minimum_amount", None)
        or 0
    )
    final_amount = base_amount
    discounts_applied = []

    # Note: Discount logic has been moved to the Dues Schedule Template system
    # Custom amounts and adjustments are handled through the dues schedule contribution system
    # Legacy student_discount_percentage and early_bird_discount fields do not exist in current Membership Type DocType

    # Ensure minimum amount
    if final_amount < 1:
        final_amount = 1

    return {
        "base_amount": base_amount,
        "final_amount": final_amount,
        "discounts_applied": discounts_applied,
        "total_discount": base_amount - final_amount,
    }


def validate_payment_amount(invoice, received_amount):
    """Validate that the received payment amount is correct"""
    invoice_amount = float(invoice.grand_total)
    received_amount = float(received_amount)

    # Allow small differences due to rounding
    tolerance = 0.01

    if abs(invoice_amount - received_amount) <= tolerance:
        return {"valid": True, "message": "Payment amount is correct"}
    elif received_amount < invoice_amount - tolerance:
        return {
            "valid": False,
            "message": f"Payment amount ({received_amount}) is less than invoice amount ({invoice_amount})",
        }
    else:
        # NOT a donation. A member paying more than this invoice asks for is usually
        # paying ahead or catching up on arrears, and nothing in a payment amount
        # expresses an intent to give. Calling it a donation would misstate income and
        # remove the member's claim on the money.
        #
        # Scope: this function currently has NO production callers - only tests reference
        # it - so this is a wording and classification fix, not a live behaviour change.
        # The path that actually records an overpayment is
        # PaymentEntryCreationService's `cash_received`, which books the excess as an
        # unallocated credit on the customer; the two are consistent, but they are not
        # wired to each other.
        return {
            "valid": True,
            "message": (
                f"Payment amount ({received_amount}) exceeds invoice amount "
                f"({invoice_amount}) - recording the excess as a credit"
            ),
            "overpayment": received_amount - invoice_amount,
        }


def create_membership_invoice(member, membership, membership_type, amount=None):
    """Create invoice for membership with optional custom amount"""
    if amount is None:
        # Get default amount from template
        template = load_template_for_membership_type(membership_type)
        amount = template.suggested_amount or 0

    return create_membership_invoice_with_amount(member, membership, amount)


def format_currency_for_display(amount, currency="EUR"):
    """Format currency amount for display"""
    return frappe.utils.fmt_money(amount, currency=currency)


def create_contact_for_customer(customer, member):
    """Create Contact record for Customer with proper Dutch name handling"""
    try:
        from verenigingen.utils.dutch_name_utils import get_full_last_name

        contact = frappe.new_doc("Contact")

        # Use Member's Dutch name fields properly
        contact.first_name = member.first_name
        if hasattr(member, "middle_name") and member.middle_name:
            contact.middle_name = member.middle_name

        # Combine tussenvoegsel + last_name using existing utility
        contact.last_name = get_full_last_name(member.last_name, getattr(member, "tussenvoegsel", None))

        # Add email to email_ids child table (this populates the read-only email_id field via ERPNext)
        if member.email:
            contact.append("email_ids", {"email_id": member.email, "is_primary": 1})

        # Add phone to phone_nos child table (this populates the read-only mobile_no field via ERPNext)
        if member.contact_number:
            contact.append("phone_nos", {"phone": member.contact_number, "is_primary_mobile_no": 1})

        # Link to customer
        contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})

        # Insert with proper permissions (no bypass)
        contact.insert()

        frappe.logger().info(
            f"Created Contact {contact.name} for Customer {customer.name} (Member: {member.name})"
        )
        return contact

    except Exception as e:
        frappe.log_error(
            message=f"Error creating Contact for Customer {customer.name} (Member: {member.name}): {str(e)}",
            title="Customer Contact Creation Error",
        )
        return None
