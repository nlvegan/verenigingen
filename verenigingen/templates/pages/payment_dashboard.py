import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name


def get_context(context):
    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

    # Check if user has appropriate permissions
    is_member = frappe.db.exists("Has Role", {"parent": frappe.session.user, "role": "Verenigingen Member"})
    is_admin = frappe.db.exists(
        "Has Role",
        {
            "parent": frappe.session.user,
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]],
        },
    )

    if not is_member and not is_admin:
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    # Get member parameter from URL if admin is viewing
    member_param = frappe.form_dict.get("member")

    if is_admin and member_param:
        # Admin viewing specific member's dashboard
        # Validate member parameter is not empty or None
        if not member_param or member_param.strip() == "":
            frappe.throw(_("Invalid member parameter provided"), frappe.ValidationError)

        if frappe.db.exists("Member", member_param):
            context.member = member_param
            context.viewing_as_admin = True
            member_doc = frappe.get_doc("Member", member_param)
            context.member_name = member_doc.full_name
        else:
            frappe.throw(_("Member {0} not found").format(member_param), frappe.DoesNotExistError)
    else:
        # Get member record for logged in user using standardized utility
        member = get_current_user_member_name()

        if not member and is_member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)
        elif not member and is_admin:
            # Admin without member record - show member selection
            context.show_member_selection = True
            context.members = frappe.get_all(
                "Member", fields=["name", "full_name", "email"], order_by="full_name"
            )
        else:
            context.member = member

    context.title = _("Payment Dashboard")
    context.is_admin = is_admin

    # Add brand CSS
    context.brand_css = "/brand_css"

    # Add bank details context data when member is available
    if context.get("member"):
        _add_bank_details_context(context)

    return context


def _add_bank_details_context(context):
    """Add bank details context data from bank_details.py"""
    # Import bank details helpers
    from verenigingen.templates.pages.bank_details import get_active_sepa_mandate, parse_mollie_customer_ids

    # Ensure CSRF token is available
    context.csrf_token = frappe.session.csrf_token

    # Get member document
    member_doc = frappe.get_doc("Member", context.member)
    context.member_doc = member_doc

    # Get current bank details
    current_details = {
        "iban": member_doc.iban,
        "bic": member_doc.bic,
        "bank_account_name": member_doc.bank_account_name,
    }
    context.current_details = current_details

    # Check for active SEPA mandate
    context.current_mandate = get_active_sepa_mandate(context.member)

    # Get Mollie subscription information from both Member and Donor records
    mollie_customers = []

    # Check member record for Mollie customer ID (regardless of payment method)
    # Support comma-separated customer IDs for members with multiple Mollie accounts
    if member_doc.mollie_customer_id:
        customer_ids = parse_mollie_customer_ids(member_doc.mollie_customer_id, max_ids=5)
        for customer_id in customer_ids:
            mollie_customers.append(
                {
                    "customer_id": customer_id,
                    "subscription_id": member_doc.mollie_subscription_id,
                    "status": member_doc.subscription_status,
                    "next_payment_date": member_doc.next_payment_date,
                    "cancelled_date": member_doc.subscription_cancelled_date,
                    "source": "member",
                    "payment_method": member_doc.payment_method,  # Track what it's used for
                }
            )

    # Check donor record for Mollie customer ID
    donor_records = frappe.get_all(
        "Donor",
        filters={"member": context.member, "mollie_customer_id": ["!=", ""]},
        fields=["name", "mollie_customer_id", "donor_name"],
        limit=1,
    )

    if donor_records:
        donor = donor_records[0]
        mollie_customers.append(
            {
                "customer_id": donor.mollie_customer_id,
                "subscription_id": None,  # Donor subscriptions handled differently
                "status": None,
                "next_payment_date": None,
                "cancelled_date": None,
                "source": "donor",
                "donor_name": donor.donor_name,
            }
        )

    # Store all Mollie customers (max 2: member + donor)
    context.mollie_customers = mollie_customers
    # Keep legacy field for backward compatibility
    context.mollie_subscription = mollie_customers[0] if mollie_customers else None

    # Get active dues schedule for displaying current rate
    if member_doc.current_dues_schedule:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", member_doc.current_dues_schedule)
            context.active_dues_schedule = {
                "name": schedule.name,
                "amount": schedule.dues_rate,  # Use dues_rate instead of amount
                "billing_frequency": schedule.billing_frequency,
            }
        except Exception:
            context.active_dues_schedule = None
    else:
        context.active_dues_schedule = None
