"""
Context for membership fee adjustment page
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today


def get_context(context):
    """Get context for membership fee adjustment page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Adjust Membership Fee")

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        # Try alternative lookup by user field
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    context.member = frappe.get_doc("Member", member)

    # Get active membership
    membership = frappe.db.get_value(
        "Membership",
        {"member": member, "status": "Active", "docstatus": 1},
        ["name", "membership_type", "start_date", "renewal_date"],
        as_dict=True,
    )

    if not membership:
        frappe.throw(_("No active membership found"), frappe.DoesNotExistError)

    context.membership = membership

    # Get membership type details and minimum fee
    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
    context.membership_type = membership_type

    # Calculate minimum fee (could be based on membership type, student status, etc.)
    minimum_fee = get_minimum_fee(context.member, membership_type, membership)
    context.minimum_fee = minimum_fee

    # Get current effective fee with billing frequency consideration
    current_fee = get_effective_fee_for_member(context.member, membership)
    context.current_fee = current_fee

    # Determine billing frequency for display
    billing_frequency = "Monthly"
    if membership:
        if (
            "kwartaal" in membership.membership_type.lower()
            or "quarter" in membership.membership_type.lower()
        ):
            billing_frequency = "Quarterly"
        elif "jaar" in membership.membership_type.lower() or "annual" in membership.membership_type.lower():
            billing_frequency = "Annually"
    context.billing_frequency = billing_frequency

    # Get fee adjustment settings
    settings = get_fee_adjustment_settings()
    context.settings = settings

    # Get member contact email and calculator settings from settings
    verenigingen_settings = frappe.get_single("Verenigingen Settings")
    context.member_contact_email = getattr(
        verenigingen_settings, "member_contact_email", "ledenadministratie@veganisme.org"
    )

    # Get calculator settings for the infobox
    context.enable_income_calculator = getattr(verenigingen_settings, "enable_income_calculator", 0)
    context.income_percentage_rate = getattr(verenigingen_settings, "income_percentage_rate", 0.5)
    context.calculator_description = getattr(
        verenigingen_settings,
        "calculator_description",
        "Our suggested contribution is 0.5% of your monthly net income. This helps ensure fair and equitable contributions based on your financial capacity.",
    )

    # Get maximum fee multiplier setting
    context.maximum_fee_multiplier = getattr(verenigingen_settings, "maximum_fee_multiplier", 10)

    # Check if member can adjust their fee
    context.can_adjust_fee = can_member_adjust_fee(context.member, settings)

    # Get pending fee adjustment requests
    pending_requests = frappe.get_all(
        "Contribution Amendment Request",
        filters={
            "member": member,
            "amendment_type": "Fee Change",
            "status": ["in", ["Draft", "Pending Approval"]],
            "requested_by_member": 1,
        },
        fields=["name", "status", "requested_amount", "reason", "creation"],
        order_by="creation desc",
    )
    context.pending_requests = pending_requests

    # Add member portal links
    context.portal_links = [
        {"title": _("Dashboard"), "route": "/member_dashboard"},
        {"title": _("Profile"), "route": "/member_portal"},
        {"title": _("Personal Details"), "route": "/personal_details"},
        {"title": _("Fee Adjustment"), "route": "/membership_fee_adjustment", "active": True},
    ]

    return context


def get_effective_fee_for_member(member, membership):
    """Get the actual effective fee considering billing frequency and custom amounts"""
    try:
        # First try to get the fee from the membership record if it uses custom amount
        if membership:
            membership_doc = frappe.get_doc("Membership", membership.name)
            if getattr(membership_doc, "uses_custom_amount", False):
                custom_amount = getattr(membership_doc, "custom_amount", 0)
                if custom_amount:
                    return {
                        "amount": custom_amount,
                        "source": "custom_membership_amount",
                        "reason": "Custom amount from membership record",
                    }

        # Fall back to member's get_current_membership_fee method
        return member.get_current_membership_fee()

    except Exception as e:
        frappe.log_error(
            f"Error getting effective fee for member {member.name}: {str(e)}", "Fee Calculation Error"
        )
        return {"amount": 0, "source": "error"}


def get_minimum_fee(member, membership_type, membership=None):
    """Calculate minimum fee for a member considering billing frequency"""
    # Get the base amount from membership type
    base_amount = membership_type.amount

    # For quarterly memberships, we need to consider the quarterly amount
    if membership and (
        "kwartaal" in membership.membership_type.lower() or "quarter" in membership.membership_type.lower()
    ):
        # For quarterly members, use a reasonable quarterly minimum
        base_minimum = flt(base_amount * 0.5)  # 50% of standard quarterly fee
    else:
        base_minimum = flt(base_amount * 0.3)  # 30% of standard fee as absolute minimum

    # Student discount
    if getattr(member, "student_status", False):
        base_minimum = max(base_minimum, flt(membership_type.amount * 0.5))  # Students minimum 50%

    # Income-based minimum (if available)
    if hasattr(member, "annual_income") and member.annual_income:
        if member.annual_income in ["Under €25,000", "€25,000 - €40,000"]:
            base_minimum = max(base_minimum, flt(membership_type.amount * 0.4))  # Low income 40%

    # Ensure minimum is at least €5
    return max(base_minimum, 5.0)


def get_fee_adjustment_settings():
    """Get fee adjustment settings from Verenigingen Settings"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return {
            "enable_member_fee_adjustment": getattr(settings, "enable_member_fee_adjustment", 1),
            "max_adjustments_per_year": getattr(settings, "max_adjustments_per_year", 3),
            "require_approval_for_increases": getattr(settings, "require_approval_for_increases", 0),
            "require_approval_for_decreases": getattr(settings, "require_approval_for_decreases", 1),
            "adjustment_reason_required": getattr(settings, "adjustment_reason_required", 1),
        }
    except Exception:
        # Default settings if Verenigingen Settings doesn't exist or lacks fields
        return {
            "enable_member_fee_adjustment": 1,
            "max_adjustments_per_year": 3,
            "require_approval_for_increases": 0,
            "require_approval_for_decreases": 1,
            "adjustment_reason_required": 1,
        }


def can_member_adjust_fee(member, settings):
    """Check if member can adjust their fee"""
    if not settings.get("enable_member_fee_adjustment"):
        return False, _("Fee adjustment is not enabled")

    # Check how many adjustments this year
    year_start = getdate(today()).replace(month=1, day=1)
    adjustments_this_year = frappe.db.count(
        "Contribution Amendment Request",
        filters={
            "member": member.name,
            "amendment_type": "Fee Change",
            "creation": [">=", year_start],
            "requested_by_member": 1,
        },
    )

    max_adjustments = settings.get("max_adjustments_per_year", 2)
    if adjustments_this_year >= max_adjustments:
        return False, _("You have reached the maximum number of fee adjustments for this year ({0})").format(
            max_adjustments
        )

    return True, ""


@frappe.whitelist()
def submit_fee_adjustment_request(new_amount, reason=""):
    """Submit a fee adjustment request from member portal"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found"))

    member_doc = frappe.get_doc("Member", member)

    # Validate amount
    new_amount = flt(new_amount)
    if new_amount <= 0:
        frappe.throw(_("Amount must be greater than 0"))

    # Get membership and minimum fee
    membership = frappe.db.get_value(
        "Membership", {"member": member, "status": "Active", "docstatus": 1}, ["name", "membership_type"]
    )

    if not membership:
        frappe.throw(_("No active membership found"))

    membership_type = frappe.get_doc("Membership Type", membership[1])
    minimum_fee = get_minimum_fee(member_doc, membership_type)

    # Get maximum fee multiplier from settings
    verenigingen_settings = frappe.get_single("Verenigingen Settings")
    maximum_fee_multiplier = getattr(verenigingen_settings, "maximum_fee_multiplier", 10)
    # Use membership type amount as base (not minimum fee) for calculating maximum
    maximum_fee = membership_type.amount * maximum_fee_multiplier

    if new_amount < minimum_fee:
        frappe.throw(
            _("Amount cannot be less than minimum fee of {0}").format(
                frappe.format_value(minimum_fee, {"fieldtype": "Currency"})
            )
        )

    if new_amount > maximum_fee:
        frappe.throw(
            _(
                "Amount cannot be more than maximum fee of {0} (for higher amounts, please contact us directly)"
            ).format(frappe.format_value(maximum_fee, {"fieldtype": "Currency"}))
        )

    # Check if member can adjust fee
    settings = get_fee_adjustment_settings()
    can_adjust, error_msg = can_member_adjust_fee(member_doc, settings)

    if not can_adjust:
        frappe.throw(error_msg)

    # Get current fee
    current_fee = member_doc.get_current_membership_fee()
    current_amount = current_fee.get("amount", membership_type.amount)

    # Validate amount is different and reasonable
    if abs(new_amount - current_amount) < 0.01:
        frappe.msgprint(
            _("The requested amount ({0}) is the same as your current membership fee.").format(
                frappe.utils.fmt_money(new_amount, currency="EUR")
            ),
            title=_("No Change Needed"),
            indicator="orange",
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/membership_fee_adjustment"
        return

    # Determine if approval is needed
    needs_approval = False
    if new_amount > current_amount and settings.get("require_approval_for_increases"):
        needs_approval = True
    elif new_amount < current_amount and settings.get("require_approval_for_decreases"):
        needs_approval = True

    # Validate reason if required
    if settings.get("adjustment_reason_required") and not reason.strip():
        frappe.throw(_("Please provide a reason for the fee adjustment"))

    # Get current active membership
    current_membership = frappe.db.get_value(
        "Membership", {"member": member, "status": "Active", "docstatus": 1}
    )

    if not current_membership:
        frappe.throw(_("No active membership found. Cannot process fee adjustment."))

    # Create amendment request
    amendment = frappe.get_doc(
        {
            "doctype": "Contribution Amendment Request",
            "member": member,
            "membership": current_membership,
            "amendment_type": "Fee Change",
            "current_amount": current_amount,
            "requested_amount": new_amount,
            "reason": reason,
            "status": "Pending Approval" if needs_approval else "Auto-Approved",
            "requested_by_member": 1,
            "effective_date": today(),
        }
    )

    try:
        amendment.insert(ignore_permissions=True)
    except frappe.ValidationError as e:
        # Handle validation errors more gracefully
        error_msg = str(e)
        if "same as current amount" in error_msg:
            frappe.msgprint(
                _("No changes were made as the requested amount is the same as your current fee."),
                title=_("No Change Needed"),
                indicator="orange",
            )
        else:
            frappe.msgprint(
                _("Unable to process your request: {0}").format(error_msg),
                title=_("Validation Error"),
                indicator="red",
            )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/membership_fee_adjustment"
        return

    # If no approval needed, apply immediately
    if not needs_approval:
        # Apply the fee change
        member_doc.membership_fee_override = new_amount
        member_doc.fee_override_reason = f"Member self-adjustment: {reason}"
        member_doc.fee_override_date = today()
        member_doc.fee_override_by = frappe.session.user
        member_doc.save(ignore_permissions=True)

        # Update amendment status
        amendment.status = "Applied"
        amendment.applied_date = today()
        amendment.save(ignore_permissions=True)

        return {
            "success": True,
            "message": _("Your fee has been updated successfully"),
            "amendment_id": amendment.name,
            "needs_approval": False,
        }
    else:
        return {
            "success": True,
            "message": _("Your fee adjustment request has been submitted for approval"),
            "amendment_id": amendment.name,
            "needs_approval": True,
        }


@frappe.whitelist()
def get_fee_calculation_info():
    """Get fee calculation information for member"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found"))

    member_doc = frappe.get_doc("Member", member)

    # Get membership type
    membership = frappe.db.get_value(
        "Membership", {"member": member, "status": "Active", "docstatus": 1}, "membership_type"
    )

    if not membership:
        frappe.throw(_("No active membership found"))

    membership_type = frappe.get_doc("Membership Type", membership)

    # Calculate fees
    standard_fee = membership_type.amount
    minimum_fee = get_minimum_fee(member_doc, membership_type)
    current_fee = member_doc.get_current_membership_fee()

    return {
        "standard_fee": standard_fee,
        "minimum_fee": minimum_fee,
        "current_fee": current_fee.get("amount", standard_fee),
        "current_source": current_fee.get("source", "membership_type"),
        "membership_type": membership_type.membership_type_name,
    }
