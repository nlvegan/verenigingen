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
    can_adjust, message = can_member_adjust_fee(context.member, settings)
    context.can_adjust_fee = can_adjust
    context.adjustment_message = message

    # Get adjustment history for the member
    date_365_days_ago = frappe.utils.add_days(today(), -365)
    adjustments_past_year = frappe.db.count(
        "Contribution Amendment Request",
        filters={
            "member": member,
            "amendment_type": "Fee Change",
            "creation": [">=", date_365_days_ago],
            "requested_by_member": 1,
        },
    )
    context.adjustments_past_year = adjustments_past_year
    context.adjustments_remaining = max(0, 2 - adjustments_past_year)

    # Get pending fee adjustment requests
    pending_fee_requests = frappe.get_all(
        "Contribution Amendment Request",
        filters={
            "member": member,
            "amendment_type": "Fee Change",
            "status": ["in", ["Draft", "Pending Approval"]],
            "requested_by_member": 1,
        },
        fields=["name", "status", "requested_amount", "reason", "creation", "amendment_type"],
        order_by="creation desc",
    )

    # Get pending membership type change requests
    pending_type_requests = frappe.get_all(
        "Contribution Amendment Request",
        filters={
            "member": member,
            "amendment_type": "Membership Type Change",
            "status": ["in", ["Draft", "Pending Approval"]],
            "requested_by_member": 1,
        },
        fields=["name", "status", "requested_membership_type", "reason", "creation", "amendment_type"],
        order_by="creation desc",
    )

    # Combine all pending requests
    pending_requests = pending_fee_requests + pending_type_requests
    pending_requests.sort(key=lambda x: x["creation"], reverse=True)
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
        # PRIORITY 1: Check for active dues schedule (new approach)
        active_dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active"},
            ["name", "amount", "contribution_mode", "billing_frequency"],
            as_dict=True,
        )

        if active_dues_schedule:
            return {
                "amount": active_dues_schedule.amount,
                "source": "dues_schedule",
                "reason": f"Active dues schedule ({active_dues_schedule.contribution_mode})",
                "schedule_name": active_dues_schedule.name,
            }

        # PRIORITY 2: Check membership record for custom amount (Updated to use dues schedule system)
        # This priority slot is reserved for future membership-level customizations

        # PRIORITY 3: Fall back to member's override fields (legacy support)
        if hasattr(member, "dues_rate") and member.dues_rate:
            return {
                "amount": member.dues_rate,
                "source": "member_override",
                "reason": "Legacy fee override (consider migrating to dues schedule)",
            }

        # PRIORITY 4: Fall back to member's get_current_membership_fee method
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

    # Check how many adjustments in the past 365 days (not just this calendar year)
    date_365_days_ago = frappe.utils.add_days(today(), -365)
    adjustments_past_year = frappe.db.count(
        "Contribution Amendment Request",
        filters={
            "member": member.name,
            "amendment_type": "Fee Change",
            "creation": [">=", date_365_days_ago],
            "requested_by_member": 1,
        },
    )

    # Allow 2 adjustments in 365 days by default
    max_adjustments = 2
    if adjustments_past_year >= max_adjustments:
        return False, _("You have reached the maximum number of fee adjustments (2) in the past 365 days")

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

    # Check if this is an increase or decrease
    if new_amount > current_amount:
        # For increases, check if it exceeds the maximum multiplier
        if new_amount > maximum_fee:
            needs_approval = True
    else:
        # For decreases, always require approval (as per original settings)
        needs_approval = settings.get("require_approval_for_decreases", True)

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
        # Apply the fee change using new dues schedule approach
        dues_schedule_name = create_new_dues_schedule(member_doc, new_amount, reason)

        # Update amendment status
        amendment.status = "Applied"
        amendment.applied_date = today()
        amendment.dues_schedule = dues_schedule_name  # Link to new schedule
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


def create_new_dues_schedule(member, new_amount, reason):
    """Create a new dues schedule for fee adjustment"""
    try:
        # Get current active membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member.name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        if not membership:
            frappe.throw(_("No active membership found for creating dues schedule"))

        # Deactivate existing active dues schedule
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "status": "Active"}, "name"
        )

        if existing_schedule:
            existing_doc = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            existing_doc.status = "Cancelled"
            existing_doc.add_comment(text=f"Cancelled and replaced by new fee adjustment: €{new_amount:.2f}")
            existing_doc.save(ignore_permissions=True)

        # Create new dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership.membership_type
        dues_schedule.contribution_mode = "Custom"
        dues_schedule.amount = new_amount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_approved = 1  # Auto-approve for self-adjustments
        dues_schedule.custom_amount_reason = f"Member self-adjustment: {reason}"

        # Handle zero amounts specially
        if new_amount == 0:
            dues_schedule.custom_amount_reason = f"Free membership: {reason}"
        dues_schedule.billing_frequency = "Monthly"  # Default
        # Payment method will be determined dynamically based on member's payment setup
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 1
        dues_schedule.test_mode = 0
        dues_schedule.effective_date = today()
        # Coverage dates are calculated automatically

        # Add portal adjustment metadata in notes
        dues_schedule.notes = f"Created from member portal by {frappe.session.user} on {today()}"

        dues_schedule.save(ignore_permissions=True)

        # Add comment about the adjustment
        dues_schedule.add_comment(
            text=f"Created from member portal fee adjustment. Amount: €{new_amount:.2f}. Reason: {reason}"
        )

        # Also maintain legacy override fields temporarily for backward compatibility
        member.reload()  # Refresh to avoid timestamp mismatch
        member.dues_rate = new_amount
        member.fee_override_reason = f"Member self-adjustment: {reason}"
        member.fee_override_date = today()
        member.fee_override_by = frappe.session.user
        member.save(ignore_permissions=True)

        return dues_schedule.name

    except Exception as e:
        frappe.log_error(f"Error creating dues schedule: {str(e)}", "Fee Adjustment Error")
        frappe.throw(_("Error creating dues schedule: {0}").format(str(e)))


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
        "Membership",
        {"member": member, "status": "Active", "docstatus": 1},
        ["name", "membership_type"],
        as_dict=True,
    )

    if not membership:
        frappe.throw(_("No active membership found"))

    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    # Calculate fees using new priority system
    standard_fee = membership_type.amount
    minimum_fee = get_minimum_fee(member_doc, membership_type)
    current_fee = get_effective_fee_for_member(member_doc, membership)

    # Get historical fee information
    fee_history = get_member_fee_history(member)

    return {
        "standard_fee": standard_fee,
        "minimum_fee": minimum_fee,
        "current_fee": current_fee.get("amount", standard_fee),
        "current_source": current_fee.get("source", "membership_type"),
        "current_reason": current_fee.get("reason", "Standard membership fee"),
        "membership_type": membership_type.membership_type_name,
        "fee_history": fee_history,
        "active_dues_schedule": current_fee.get("schedule_name"),
    }


def get_member_fee_history(member_name):
    """Get historical fee information for a member"""
    try:
        # Get all dues schedules for the member (active and historical)
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=[
                "name",
                "amount",
                "contribution_mode",
                "status",
                "effective_date",
                "custom_amount_reason",
                "creation",
            ],
            order_by="creation desc",
        )

        # Get amendment requests
        amendment_requests = frappe.get_all(
            "Contribution Amendment Request",
            filters={"member": member_name, "amendment_type": "Fee Change"},
            fields=[
                "name",
                "current_amount",
                "requested_amount",
                "status",
                "requested_date",
                "reason",
                "applied_date",
            ],
            order_by="requested_date desc",
        )

        # Combine and format history
        history = []

        # Add dues schedules
        for schedule in dues_schedules:
            history.append(
                {
                    "date": schedule.effective_date or schedule.creation,
                    "type": "Dues Schedule",
                    "amount": schedule.amount,
                    "status": schedule.status,
                    "reason": schedule.custom_amount_reason or f"{schedule.contribution_mode} contribution",
                    "source": "dues_schedule",
                    "reference": schedule.name,
                }
            )

        # Add amendment requests
        for request in amendment_requests:
            history.append(
                {
                    "date": request.applied_date or request.requested_date,
                    "type": "Amendment Request",
                    "amount": request.requested_amount,
                    "status": request.status,
                    "reason": request.reason,
                    "source": "amendment_request",
                    "reference": request.name,
                    "previous_amount": request.current_amount,
                }
            )

        # Sort by date descending
        history.sort(key=lambda x: x["date"], reverse=True)

        return history[:10]  # Return last 10 entries

    except Exception as e:
        frappe.log_error(f"Error getting fee history for {member_name}: {str(e)}", "Fee History Error")
        return []


@frappe.whitelist()
def get_available_membership_types():
    """Get available membership types for the member to switch to"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found"))

    # Get current membership
    membership = frappe.db.get_value(
        "Membership",
        {"member": member, "status": "Active", "docstatus": 1},
        ["membership_type"],
        as_dict=True,
    )

    if not membership:
        frappe.throw(_("No active membership found"))

    # Get all published membership types
    membership_types = frappe.get_all(
        "Membership Type",
        filters={"is_published": 1},
        fields=["name", "membership_type_name", "amount", "description"],
        order_by="amount",
    )

    return {"membership_types": membership_types, "current_type": membership.membership_type}


@frappe.whitelist()
def submit_membership_type_change_request(new_membership_type, reason=""):
    """Submit a membership type change request from member portal"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found"))

    member_doc = frappe.get_doc("Member", member)

    # Get current membership
    membership = frappe.db.get_value(
        "Membership",
        {"member": member, "status": "Active", "docstatus": 1},
        ["name", "membership_type"],
        as_dict=True,
    )

    if not membership:
        frappe.throw(_("No active membership found"))

    # Validate new membership type
    if not frappe.db.exists("Membership Type", new_membership_type):
        frappe.throw(_("Invalid membership type selected"))

    # Check if it's actually a change
    if membership.membership_type == new_membership_type:
        frappe.throw(_("You are already on this membership type"))

    # Validate reason
    if not reason.strip():
        frappe.throw(_("Please provide a reason for the membership type change"))

    # Check if there's already a pending membership type change request
    pending_request = frappe.db.exists(
        "Contribution Amendment Request",
        {
            "member": member,
            "amendment_type": "Membership Type Change",
            "status": ["in", ["Draft", "Pending Approval"]],
        },
    )

    if pending_request:
        frappe.throw(_("You already have a pending membership type change request"))

    # Get new membership type details
    new_type_doc = frappe.get_doc("Membership Type", new_membership_type)
    old_type_doc = frappe.get_doc("Membership Type", membership.membership_type)

    # Create amendment request
    amendment = frappe.get_doc(
        {
            "doctype": "Contribution Amendment Request",
            "member": member,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": membership.membership_type,
            "requested_membership_type": new_membership_type,
            "current_amount": old_type_doc.amount,
            "requested_amount": new_type_doc.amount,
            "reason": reason,
            "status": "Pending Approval",  # All membership type changes require approval
            "requested_by_member": 1,
            "effective_date": today(),
        }
    )

    try:
        amendment.insert(ignore_permissions=True)

        # Send notification to membership committee
        send_membership_type_change_notification(member_doc, old_type_doc, new_type_doc, reason)

        return {
            "success": True,
            "message": _("Your membership type change request has been submitted for approval"),
            "amendment_id": amendment.name,
        }

    except Exception as e:
        frappe.log_error(
            f"Error creating membership type change request: {str(e)}", "Membership Type Change Error"
        )
        frappe.throw(_("Error creating membership type change request: {0}").format(str(e)))


def send_membership_type_change_notification(member, old_type, new_type, reason):
    """Send notification about membership type change request"""
    try:
        # Get notification recipients (membership committee)
        settings = frappe.get_single("Verenigingen Settings")
        recipients = []

        if hasattr(settings, "membership_committee_email"):
            recipients.append(settings.membership_committee_email)

        # Also notify chapter administrators
        if hasattr(member, "chapter") and member.chapter:
            chapter_doc = frappe.get_doc("Chapter", member.chapter)
            for board_member in chapter_doc.board_members:
                if board_member.is_active and board_member.chapter_role in ["Chapter Head", "Secretary"]:
                    recipients.append(board_member.email)

        if recipients:
            frappe.sendmail(
                recipients=list(set(recipients)),  # Remove duplicates
                subject=f"Membership Type Change Request - {member.full_name}",
                message=f"""
                <h3>Membership Type Change Request</h3>
                <p><strong>Member:</strong> {member.full_name} ({member.name})</p>
                <p><strong>Current Type:</strong> {old_type.membership_type_name} (€{old_type.amount:.2f})</p>
                <p><strong>Requested Type:</strong> {new_type.membership_type_name} (€{new_type.amount:.2f})</p>
                <p><strong>Reason:</strong> {reason}</p>
                <p><strong>Submitted:</strong> {frappe.utils.now_datetime()}</p>
                <br>
                <p>Please review this request in the system.</p>
                """,
                delayed=False,
            )

    except Exception as e:
        frappe.log_error(f"Error sending membership type change notification: {str(e)}", "Notification Error")
