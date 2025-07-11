"""
API endpoints for reviewing and managing membership applications
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today


@frappe.whitelist()
def approve_membership_application(member_name, membership_type=None, chapter=None, notes=None):
    """
    Approve a membership application and create invoice
    Now directly processes payment instead of waiting
    """
    member = frappe.get_doc("Member", member_name)

    # Validate application can be approved
    if member.application_status not in ["Pending"]:
        frappe.throw(_("This application cannot be approved in its current state"))

    # Check permissions
    if not has_approval_permission(member):
        frappe.throw(_("You don't have permission to approve this application"))

    # Use provided membership type or fallback to selected
    if not membership_type:
        membership_type = getattr(member, "selected_membership_type", None)

    # Additional fallback to current membership type if selected is not set
    if not membership_type:
        membership_type = getattr(member, "current_membership_type", None)

    # If still no membership type, try to set a default from available types
    if not membership_type:
        membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
        if membership_types:
            membership_type = membership_types[0].name
            # Set this as the selected type for the member
            try:
                member.selected_membership_type = membership_type
                member.save()
                frappe.logger().info(
                    f"Auto-assigned membership type {membership_type} to member {member.name}"
                )
            except Exception as e:
                frappe.logger().error(f"Could not save membership type to member: {str(e)}")
        else:
            frappe.throw(
                _("No membership types available in the system. Please create a membership type first.")
            )

    if not membership_type:
        frappe.throw(_("Please select a membership type"))

    # Update chapter if provided
    if chapter:
        current_chapter = getattr(member, "current_chapter_display", None) or ""
        if chapter != current_chapter:
            try:
                member.current_chapter_display = chapter
            except AttributeError:
                # Field might not exist in database yet, log but continue
                frappe.logger().warning(
                    f"Could not set current_chapter_display field on member {member.name}"
                )

    # Update member status
    member.application_status = "Approved"  # Application is approved
    member.status = "Active"  # Member is now active (not waiting for payment)
    member.member_since = today()  # Set member since date when approved
    member.reviewed_by = frappe.session.user
    member.review_date = now_datetime()
    if notes:
        member.review_notes = notes
    # Set the selected membership type using setattr to handle potential AttributeError
    try:
        member.selected_membership_type = membership_type
    except AttributeError:
        # Field might not exist in the database yet, log but continue
        frappe.logger().warning(f"Could not set selected_membership_type field on member {member.name}")

    member.save()

    # Create employee record for volunteers whose applications are now approved
    if hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering:
        volunteer_record = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        if volunteer_record:
            try:
                volunteer = frappe.get_doc("Volunteer", volunteer_record)
                volunteer.create_employee_if_needed()
                frappe.logger().info(f"Created employee record for approved volunteer: {volunteer.name}")
            except Exception as e:
                frappe.logger().error(f"Failed to create employee for volunteer {volunteer_record}: {str(e)}")

    # Create initial IBAN history if member has IBAN
    if hasattr(member, "iban") and member.iban:
        try:
            frappe.db.insert(
                {
                    "doctype": "Member IBAN History",
                    "parent": member.name,
                    "parenttype": "Member",
                    "parentfield": "iban_history",
                    "iban": member.iban,
                    "bic": getattr(member, "bic", None),
                    "bank_account_name": getattr(member, "bank_account_name", None),
                    "from_date": today(),
                    "is_active": 1,
                    "changed_by": frappe.session.user,
                    "change_reason": "Other",
                }
            )
            frappe.logger().info(f"Created initial IBAN history for approved member {member.name}")
        except Exception as e:
            frappe.logger().error(f"Error creating IBAN history for {member.name}: {str(e)}")
            # Don't fail the approval process due to IBAN history error

    # Create membership record
    membership = frappe.get_doc(
        {
            "doctype": "Membership",
            "member": member.name,
            "membership_type": membership_type,
            "start_date": today(),
            "status": "Draft",  # Will be activated after payment
            "auto_renew": 1,
        }
    )

    # Handle custom amount if member selected one during application or has fee override
    from verenigingen.utils.application_helpers import get_member_custom_amount_data

    custom_amount_data = get_member_custom_amount_data(member)

    # Check for custom amount from application data
    if custom_amount_data and custom_amount_data.get("uses_custom_amount"):
        membership.uses_custom_amount = 1
        if custom_amount_data.get("membership_amount"):
            membership.custom_amount = custom_amount_data.get("membership_amount")

    # Also check for direct fee override on member
    elif hasattr(member, "membership_fee_override") and member.membership_fee_override:
        membership.uses_custom_amount = 1
        membership.custom_amount = member.membership_fee_override

    membership.insert()

    # Get membership type details
    membership_type_doc = frappe.get_doc("Membership Type", membership_type)

    # Create invoice BEFORE submitting membership to prevent duplicate invoices
    from verenigingen.api.payment_processing import create_application_invoice, get_or_create_customer

    get_or_create_customer(member)
    invoice = create_application_invoice(member, membership)

    # Now submit the membership - the subscription creation will detect the existing invoice
    membership.submit()  # Submit the membership to activate it

    # Activate volunteer record if member is interested in volunteering
    if hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering:
        activate_volunteer_record(member)

    # Create user account for portal access
    user_creation_result = create_user_account_for_member(member)

    # Force refresh user document to sync roles if user was created/linked
    if user_creation_result.get("success") and user_creation_result.get("user"):
        frappe.db.commit()  # Ensure all changes are committed
        try:
            # Force reload user document to ensure role changes are reflected
            user_doc = frappe.get_doc("User", user_creation_result["user"])
            user_doc.reload()
        except Exception as e:
            frappe.log_error(f"Error reloading user after role assignment: {str(e)}")

    # Send approval email with payment link
    send_approval_notification(member, invoice, membership_type_doc)

    # Prepare response message
    message = _("Application approved. Invoice sent to applicant.")
    if user_creation_result.get("success"):
        if user_creation_result.get("action") == "created_new":
            message += _(" User account created for portal access.")
        elif user_creation_result.get("action") == "linked_existing":
            message += _(" Linked to existing user account.")
    else:
        message += _(" Note: Could not create user account - member will need manual account creation.")

    return {
        "success": True,
        "message": message,
        "invoice": invoice.name,
        "amount": membership_type_doc.amount,
        "user_account": user_creation_result,
    }


def create_user_account_for_member(member):
    """Create user account for approved member"""
    try:
        from verenigingen.verenigingen.doctype.member.member import create_member_user_account

        return create_member_user_account(member.name, send_welcome_email=True)
    except Exception as e:
        frappe.log_error(f"Error creating user account for member {member.name}: {str(e)}")
        return {"success": False, "error": str(e)}


def activate_volunteer_record(member):
    """Activate volunteer record when membership application is approved"""
    try:
        # Find existing volunteer record for this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")

        if volunteer_name:
            # Update existing volunteer record
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Active"
            volunteer.save()
            frappe.logger().info(f"Activated volunteer record {volunteer_name} for member {member.name}")
        else:
            # Create volunteer record if it doesn't exist (fallback)
            from verenigingen.utils.application_helpers import create_volunteer_record

            volunteer = create_volunteer_record(member)
            if volunteer:
                volunteer.status = "Active"
                volunteer.save()
                frappe.logger().info(
                    f"Created and activated volunteer record {volunteer.name} for member {member.name}"
                )
    except Exception as e:
        frappe.log_error(f"Error activating volunteer record for member {member.name}: {str(e)}")


@frappe.whitelist()
def reject_membership_application(
    member_name,
    reason,
    email_template=None,
    rejection_category=None,
    internal_notes=None,
    process_refund=False,
):
    """Reject a membership application with enhanced template support"""
    member = frappe.get_doc("Member", member_name)

    # Validate application can be rejected
    if member.application_status not in ["Pending", "Payment Failed", "Payment Cancelled", "Approved"]:
        frappe.throw(_("This application cannot be rejected in its current state"))

    # Check permissions
    if not has_approval_permission(member):
        frappe.throw(_("You don't have permission to reject this application"))

    # Build comprehensive review notes
    review_notes = f"Rejection Category: {rejection_category or 'Not specified'}\n"
    review_notes += f"Reason: {reason}\n"
    if internal_notes:
        review_notes += f"Internal Notes: {internal_notes}\n"
    review_notes += f"Email Template Used: {email_template or 'Default'}"

    # Update member status
    member.application_status = "Rejected"
    member.status = "Rejected"
    member.reviewed_by = frappe.session.user
    member.review_date = now_datetime()
    member.review_notes = review_notes
    member.save()

    # Process refund if payment was made
    refund_processed = False
    if (
        process_refund
        and hasattr(member, "application_invoice")
        and getattr(member, "application_invoice", None)
    ):
        from verenigingen.api.payment_processing import process_application_refund

        refund_result = process_application_refund(member_name, "Application Rejected: " + reason)
        refund_processed = refund_result.get("success", False)

    # Cancel any pending membership
    if frappe.db.exists(
        "Membership", {"member": member.name, "status": ["in", ["Draft", "Pending", "Active"]]}
    ):
        membership = frappe.get_doc("Membership", {"member": member.name})
        if membership.docstatus == 1:
            membership.cancel()
        else:
            frappe.delete_doc("Membership", membership.name)

    # Update CRM Lead status if exists
    if frappe.db.exists("Lead", {"member": member.name}):
        lead = frappe.get_doc("Lead", {"member": member.name})
        lead.status = "Do Not Contact"
        lead.save()

    # Send rejection notification with specified template
    send_rejection_notification(member, reason, email_template, rejection_category)

    return {
        "success": True,
        "message": _("Application rejected. Notification sent to applicant."),
        "refund_processed": refund_processed,
    }


@frappe.whitelist()
def get_user_chapter_access():
    """Get user's chapter access for filtering applications"""
    user = frappe.session.user

    # Admin roles see all chapters
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return {"restrict_to_chapters": False, "chapters": [], "is_admin": True}

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return {
            "restrict_to_chapters": True,
            "chapters": [],
            "is_admin": False,
            "message": "User is not a member",
        }

    # Get chapters where user has board access with membership permissions
    user_chapters = []
    volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["parent", "chapter_role"],
        )

        for position in board_positions:
            # Check if the role has membership permissions
            try:
                role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                if role_doc.permissions_level in ["Admin", "Membership"]:
                    if position.parent not in user_chapters:
                        user_chapters.append(position.parent)
            except Exception:
                continue

    # Check national chapter access
    national_access = False
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_chapter") and settings.national_chapter:
            if settings.national_chapter in user_chapters:
                national_access = True
    except Exception:
        pass

    return {
        "restrict_to_chapters": len(user_chapters) > 0 and not national_access,
        "chapters": user_chapters,
        "is_admin": False,
        "has_national_access": national_access,
    }


def has_approval_permission(member):
    """Check if current user can approve/reject applications"""
    user = frappe.session.user

    # System managers always have permission
    if "System Manager" in frappe.get_roles(user):
        return True

    # Association/Membership managers have permission
    if any(role in frappe.get_roles(user) for role in ["Verenigingen Administrator", "Verenigingen Manager"]):
        return True

    # Check if user is a board member of the member's chapter
    chapter = getattr(member, "current_chapter_display", None) or getattr(member, "suggested_chapter", None)
    if chapter:
        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            chapter_doc = frappe.get_doc("Chapter", chapter)
            # Check if user is a board member with appropriate permissions
            for board_member in chapter_doc.board_members:
                if board_member.is_active and board_member.member == user_member:
                    role = frappe.get_doc("Chapter Role", board_member.chapter_role)
                    if role.permissions_level in ["Admin", "Membership"]:
                        return True

    return False


def send_approval_notification(member, invoice, membership_type):
    """Send approval notification with payment link"""
    # Create payment link
    payment_url = frappe.utils.get_url(f"/payment/membership/{member.name}/{invoice.name}")

    # Check if email templates exist, otherwise use simple email
    if frappe.db.exists("Email Template", "membership_application_approved"):
        args = {
            "member": member,
            "invoice": invoice,
            "membership_type": membership_type,
            "payment_url": payment_url,
            "payment_amount": invoice.grand_total,
            "company": frappe.defaults.get_global_default("company"),
            "support_email": frappe.db.get_single_value("Verenigingen Settings", "contact_email")
            or "info@verenigingen.nl",
            "base_url": frappe.utils.get_url(),
        }

        # Use Email Template if available
        if frappe.db.exists("Email Template", "membership_application_approved"):
            email_template_doc = frappe.get_doc("Email Template", "membership_application_approved")
            frappe.sendmail(
                recipients=[member.email],
                subject=email_template_doc.subject or _("Membership Application Approved - Payment Required"),
                message=frappe.render_template(email_template_doc.response, args),
                now=True,
            )
        else:
            # Fallback to simple HTML email
            message = """
            <h2>Membership Application Approved!</h2>

            <p>Dear {member.first_name},</p>

            <p>Congratulations! Your membership application has been approved.</p>

            <p><strong>Application Details:</strong></p>
            <ul>
                <li>Application ID: {getattr(member, 'application_id', member.name)}</li>
                <li>Membership Type: {membership_type.membership_type_name}</li>
                <li>Fee Amount: {frappe.format_value(invoice.grand_total, {'fieldtype': 'Currency'})}</li>
            </ul>

            <p>To complete your membership, please pay the membership fee using the link below:</p>
            <p><a href="{payment_url}" class="btn btn-primary">Pay Membership Fee</a></p>

            <p>Thank you for joining us!</p>
            """

            frappe.sendmail(
                recipients=[member.email],
                subject=_("Membership Application Approved - Payment Required"),
                message=message,
                now=True,
            )
    else:
        # Use simple HTML email instead of template
        message = """
        <h2>Membership Application Approved!</h2>

        <p>Dear {member.first_name},</p>

        <p>Congratulations! Your membership application has been approved.</p>

        <p><strong>Application Details:</strong></p>
        <ul>
            <li>Application ID: {getattr(member, 'application_id', member.name)}</li>
            <li>Membership Type: {membership_type.membership_type_name}</li>
            <li>Fee Amount: {frappe.format_value(invoice.grand_total, {'fieldtype': 'Currency'})}</li>
        </ul>

        <p>To complete your membership, please pay the membership fee using the link below:</p>

        <p><a href="{payment_url}" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Pay Membership Fee</a></p>

        <p>Your membership will be activated immediately after payment confirmation.</p>

        <p>If you have any questions, please don't hesitate to contact us.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email],
            subject=_("Membership Application Approved - Payment Required"),
            message=message,
            now=True,
        )


def send_rejection_notification(member, reason, email_template=None, rejection_category=None):
    """Send rejection notification to applicant using specified template"""
    args = {
        "member": member,
        "reason": reason,
        "rejection_category": rejection_category or "Not specified",
        "company": frappe.defaults.get_global_default("company"),
        "member_name": member.full_name,
        "first_name": member.first_name,
        "application_id": getattr(member, "application_id", member.name),
        "support_email": frappe.db.get_single_value("Verenigingen Settings", "contact_email")
        or "info@verenigingen.nl",
        "base_url": frappe.utils.get_url(),
    }

    # Use specified email template if provided and exists
    template_to_use = email_template
    if template_to_use and frappe.db.exists("Email Template", template_to_use):
        # Get the Email Template document and send using Frappe's email template system
        email_template_doc = frappe.get_doc("Email Template", template_to_use)
        frappe.sendmail(
            recipients=[member.email],
            subject=email_template_doc.subject or _("Membership Application Update"),
            message=frappe.render_template(email_template_doc.response, args),
            now=True,
        )
    elif frappe.db.exists("Email Template", "membership_application_rejected"):
        # Fallback to default rejection template
        email_template_doc = frappe.get_doc("Email Template", "membership_application_rejected")
        frappe.sendmail(
            recipients=[member.email],
            subject=email_template_doc.subject or _("Membership Application Update"),
            message=frappe.render_template(email_template_doc.response, args),
            now=True,
        )
    else:
        # Simple rejection email if no templates exist
        message = f"""
        <p>Dear {member.first_name},</p>

        <p>Thank you for your interest in joining our association.</p>

        <p>After careful review, we regret to inform you that your membership application has not been approved at this time.</p>

        <p><strong>Reason:</strong> {reason}</p>

        <p>If you have any questions or would like to discuss this decision, please don't hesitate to contact us.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email], subject=_("Membership Application Update"), message=message, now=True
        )


@frappe.whitelist()
def get_pending_applications(chapter=None, days_overdue=None):
    """Get list of pending membership applications"""
    filters = {"application_status": "Pending", "status": "Pending"}

    # Filter by chapter if specified
    if chapter:
        filters["current_chapter_display"] = chapter

    # Filter by overdue if specified
    if days_overdue:
        cutoff_date = add_days(today(), -days_overdue)
        filters["application_date"] = ["<", cutoff_date]

    # Check user permissions
    user = frappe.session.user
    if not any(
        role in frappe.get_roles(user)
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    ):
        # Regular users can only see applications for their chapter
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            # Get chapters where user is a board member
            board_chapters = frappe.db.sql(
                """
                SELECT DISTINCT c.name
                FROM `tabChapter` c
                JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
                WHERE cbm.member = %s AND cbm.is_active = 1
            """,
                user_member,
                as_dict=True,
            )

            if board_chapters:
                chapter_list = [ch.name for ch in board_chapters]
                if "current_chapter_display" in filters:
                    # Ensure requested chapter is in allowed list
                    if filters["current_chapter_display"] not in chapter_list:
                        return []
                else:
                    filters["current_chapter_display"] = ["in", chapter_list]
            else:
                return []  # No board memberships

    # Get applications
    applications = frappe.get_all(
        "Member",
        filters=filters,
        fields=[
            "name",
            "application_id",
            "full_name",
            "email",
            "contact_number",
            "application_date",
            "current_chapter_display",
            "selected_membership_type",
            "application_source",
            "interested_in_volunteering",
            "age",
        ],
        order_by="application_date desc",
    )

    # Add additional info
    for app in applications:
        app["days_pending"] = (getdate(today()) - getdate(app.application_date)).days

        # Get membership type amount
        if app.selected_membership_type:
            mt = frappe.get_cached_doc("Membership Type", app.selected_membership_type)
            app["membership_amount"] = mt.amount
            app["membership_currency"] = mt.currency

    return applications


@frappe.whitelist()
def get_pending_reviews_for_member(member_name):
    """Get pending membership application reviews for a specific member"""
    try:
        # Check if there are any pending reviews for this member
        # Since this is for membership applications, we check if the member
        # has a pending application status that needs review
        member = frappe.get_doc("Member", member_name)

        reviews = []

        # If member has pending application status, they need review
        if member.application_status == "Pending":
            reviews.append(
                {
                    "name": member.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "application_status": member.application_status,
                    "application_date": getattr(member, "application_date", None),
                    "review_type": "Membership Application",
                }
            )

        return reviews

    except Exception as e:
        frappe.log_error(f"Error getting pending reviews for member {member_name}: {str(e)}")
        return []


@frappe.whitelist()
def debug_and_fix_member_approval(member_name):
    """Debug and fix member approval issues"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Check field access
        result = {
            "member": member.name,
            "full_name": member.full_name,
            "application_status": member.application_status,
            "has_selected_type": hasattr(member, "selected_membership_type"),
            "selected_membership_type": getattr(member, "selected_membership_type", None),
            "has_current_type": hasattr(member, "current_membership_type"),
            "current_membership_type": getattr(member, "current_membership_type", None),
        }

        # Get available membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "membership_type_name", "amount"]
        )
        result["available_membership_types"] = len(membership_types)
        result["membership_types"] = membership_types[:3]  # Show first 3

        # Try to fix if no membership type is set
        if (
            not result["selected_membership_type"]
            and not result["current_membership_type"]
            and membership_types
        ):
            default_type = membership_types[0].name
            try:
                member.selected_membership_type = default_type
                member.save()
                result["fix_applied"] = True
                result["default_type_set"] = default_type
                result["selected_membership_type"] = default_type
            except AttributeError:
                # Field doesn't exist yet, but we can still use it for approval
                result["fix_applied"] = "field_missing_but_will_work"
                result["default_type_set"] = default_type
                result["note"] = "Field not in database yet, but approval logic will handle this"
        else:
            result["fix_applied"] = False

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
def test_member_approval(member_name):
    """Test member approval without actually approving"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Test the same logic as in approve_membership_application
        membership_type = None

        # Use the same fallback logic
        if not membership_type:
            membership_type = getattr(member, "selected_membership_type", None)

        if not membership_type:
            membership_type = getattr(member, "current_membership_type", None)

        if not membership_type:
            membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
            if membership_types:
                membership_type = membership_types[0].name

        result = {
            "member": member.name,
            "application_status": member.application_status,
            "resolved_membership_type": membership_type,
            "can_approve": bool(membership_type and member.application_status == "Pending"),
            "status": "Ready for approval" if membership_type else "No membership type available",
        }

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
def sync_member_statuses():
    """Sync member application and status fields to ensure consistency"""
    try:
        # Get all members to check for inconsistencies
        members = frappe.get_all("Member", fields=["name", "status", "application_status", "application_id"])

        updated_count = 0

        for member_data in members:
            member = frappe.get_doc("Member", member_data.name)
            is_application_member = bool(getattr(member, "application_id", None))

            updated = False

            if is_application_member:
                # Handle application-created members
                if member.application_status == "Approved" and member.status != "Active":
                    member.status = "Active"
                    updated = True
                elif member.application_status == "Rejected" and member.status != "Rejected":
                    member.status = "Rejected"
                    updated = True
            else:
                # Handle backend-created members (no application process)
                if not member.application_status:
                    member.application_status = "Approved"
                    updated = True

                # Ensure backend-created members are Active by default unless explicitly set
                if not member.status or member.status == "Pending":
                    member.status = "Active"
                    updated = True

            if updated:
                member.save()
                updated_count += 1

        return {
            "success": True,
            "message": f"Synchronized {updated_count} member records",
            "updated_count": updated_count,
        }

    except Exception as e:
        frappe.log_error(f"Error syncing member statuses: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_backend_member_statuses():
    """One-time fix for backend-created members showing as Pending"""
    try:
        # Get all members that have Pending application_status but no application_id
        members = frappe.get_all(
            "Member",
            fields=["name", "application_status", "application_id"],
            filters={"application_status": "Pending"},
        )

        fixed_count = 0

        for member_data in members:
            # If no application_id, this is a backend-created member
            if not member_data.application_id:
                member = frappe.get_doc("Member", member_data.name)
                member.application_status = "Approved"
                member.status = "Active"
                member.save()
                fixed_count += 1

        return {
            "success": True,
            "message": f"Fixed {fixed_count} backend-created members",
            "fixed_count": fixed_count,
        }

    except Exception as e:
        frappe.log_error(f"Error fixing backend member statuses: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_application_stats():
    """Get statistics for membership applications"""
    # Check permissions
    if not any(
        role in frappe.get_roles()
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    ):
        frappe.throw(_("Insufficient permissions"))

    stats = {}

    # Total applications by status
    status_counts = frappe.db.sql(
        """
        SELECT application_status, COUNT(*) as count
        FROM `tabMember`
        WHERE application_status IS NOT NULL
        GROUP BY application_status
    """,
        as_dict=True,
    )

    stats["by_status"] = {s.application_status: s.count for s in status_counts}

    # Applications in last 30 days
    stats["last_30_days"] = frappe.db.count("Member", {"application_date": [">=", add_days(today(), -30)]})

    # Average processing time (for approved applications)
    avg_time = frappe.db.sql(
        """
        SELECT AVG(TIMESTAMPDIFF(DAY, application_date, review_date)) as avg_days
        FROM `tabMember`
        WHERE application_status = 'Approved'
        AND review_date IS NOT NULL
        AND application_date IS NOT NULL
    """,
        as_dict=True,
    )

    stats["avg_processing_days"] = round(avg_time[0].avg_days or 0, 1)

    # Overdue applications (> 14 days)
    stats["overdue_count"] = frappe.db.count(
        "Member", {"application_status": "Pending", "application_date": ["<", add_days(today(), -14)]}
    )

    # Applications by chapter
    chapter_counts = frappe.db.sql(
        """
        SELECT current_chapter_display, COUNT(*) as count
        FROM `tabMember`
        WHERE application_status = 'Pending'
        AND current_chapter_display IS NOT NULL
        GROUP BY current_chapter_display
        ORDER BY count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    stats["by_chapter"] = chapter_counts

    # Volunteer interest rate
    total_apps = frappe.db.count("Member", {"application_status": ["!=", None]})
    volunteer_interested = frappe.db.count(
        "Member", {"application_status": ["!=", None], "interested_in_volunteering": 1}
    )

    stats["volunteer_interest_rate"] = round(
        (volunteer_interested / total_apps * 100) if total_apps > 0 else 0, 1
    )

    return stats


@frappe.whitelist()
def migrate_active_application_status():
    """Migrate members with 'Active' application_status to 'Approved'"""
    try:
        # Check if user has permission
        if not any(role in frappe.get_roles() for role in ["System Manager", "Verenigingen Administrator"]):
            frappe.throw(_("Only System Managers and Verenigingen Administrators can run this migration"))

        # Find all members with 'Active' application_status
        members_to_migrate = frappe.get_all(
            "Member", filters={"application_status": "Active"}, fields=["name", "full_name", "application_id"]
        )

        migrated_count = 0

        for member_data in members_to_migrate:
            try:
                member = frappe.get_doc("Member", member_data.name)
                member.application_status = "Approved"
                member.save(ignore_permissions=True)
                migrated_count += 1
                frappe.logger().info(
                    f"Migrated member {member.name} from Active to Approved application status"
                )

            except Exception as e:
                frappe.log_error(f"Error migrating member {member_data.name}: {str(e)}")
                continue

        return {
            "success": True,
            "message": f"Successfully migrated {migrated_count} members from 'Active' to 'Approved' application status",
            "migrated_count": migrated_count,
            "total_found": len(members_to_migrate),
        }

    except Exception as e:
        frappe.log_error(f"Error in migrate_active_application_status: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_member_iban_data(member_name):
    """Check the current IBAN data for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member.name,
            "full_name": member.full_name,
            "payment_method": getattr(member, "payment_method", "Not set"),
            "iban": getattr(member, "iban", "Not set"),
            "bic": getattr(member, "bic", "Not set"),
            "bank_account_name": getattr(member, "bank_account_name", "Not set"),
            "application_id": getattr(member, "application_id", "Not set"),
            "application_status": getattr(member, "application_status", "Not set"),
        }

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_custom_amount_flow(member_name):
    """Debug the custom amount flow for a specific member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member_name,
            "full_name": member.full_name,
            "has_notes": bool(getattr(member, "notes", None)),
            "notes": getattr(member, "notes", ""),
            "custom_amount_data": None,
            "error": None,
        }

        # Test custom amount extraction
        from verenigingen.utils.application_helpers import get_member_custom_amount_data

        custom_data = get_member_custom_amount_data(member)

        result["custom_amount_data"] = custom_data

        if custom_data:
            result["uses_custom_amount"] = custom_data.get("uses_custom_amount")
            result["membership_amount"] = custom_data.get("membership_amount")

        # Check existing memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=["name", "uses_custom_amount", "custom_amount", "subscription"],
        )

        result["memberships"] = memberships

        # Check subscriptions if any
        for membership in memberships:
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)
                membership["subscription_details"] = {"name": subscription.name, "plans": []}

                for plan in subscription.plans:
                    membership["subscription_details"]["plans"].append(
                        {
                            "plan": plan.plan,
                            "cost": getattr(plan, "cost", getattr(plan, "price", 0)),
                            "qty": plan.qty,
                        }
                    )

        return result

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
def debug_membership_subscription(membership_name):
    """Debug a specific membership and its subscription"""
    try:
        membership = frappe.get_doc("Membership", membership_name)

        result = {
            "membership_name": membership_name,
            "uses_custom_amount": membership.uses_custom_amount,
            "custom_amount": membership.custom_amount,
            "billing_amount": membership.get_billing_amount(),
            "subscription": membership.subscription,
            "subscription_details": None,
        }

        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            result["subscription_details"] = {
                "name": subscription.name,
                "status": subscription.status,
                "plans": [],
            }

            for plan in subscription.plans:
                plan_data = {"plan": plan.plan, "qty": plan.qty, "all_fields": {}}

                # Get all fields from the plan object
                for attr in dir(plan):
                    if not attr.startswith("_") and not callable(getattr(plan, attr)):
                        try:
                            value = getattr(plan, attr)
                            if value is not None:
                                plan_data["all_fields"][attr] = value
                        except Exception:
                            pass

                result["subscription_details"]["plans"].append(plan_data)

        return result

    except Exception as e:
        return {"error": str(e), "membership_name": membership_name}


@frappe.whitelist()
def debug_subscription_plan(plan_name):
    """Debug a subscription plan"""
    try:
        plan = frappe.get_doc("Subscription Plan", plan_name)

        result = {"plan_name": plan_name, "all_fields": {}}

        # Get all fields from the plan object
        for attr in dir(plan):
            if not attr.startswith("_") and not callable(getattr(plan, attr)):
                try:
                    value = getattr(plan, attr)
                    if value is not None and not isinstance(value, dict):
                        result["all_fields"][attr] = value
                except Exception:
                    pass

        return result

    except Exception as e:
        return {"error": str(e), "plan_name": plan_name}


@frappe.whitelist()
def test_fix_custom_amount_subscription(membership_name):
    """Test fix for custom amount subscription issue"""
    try:
        membership = frappe.get_doc("Membership", membership_name)

        result = {
            "membership_name": membership_name,
            "current_billing_amount": membership.get_billing_amount(),
            "uses_custom_amount": membership.uses_custom_amount,
            "custom_amount": membership.custom_amount,
            "subscription": membership.subscription,
            "before_fix": {},
            "after_fix": {},
        }

        # Get current subscription state
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            result["before_fix"] = {"subscription_name": subscription.name, "plans": []}

            for plan in subscription.plans:
                plan_doc = frappe.get_doc("Subscription Plan", plan.plan)
                result["before_fix"]["plans"].append({"plan_name": plan.plan, "plan_cost": plan_doc.cost})

        # Test the fix
        if membership.uses_custom_amount and membership.custom_amount:
            # Get or create the correct subscription plan
            correct_plan = membership.get_subscription_plan_for_amount(membership.custom_amount)
            result["correct_plan_name"] = correct_plan

            # Apply the fix by updating the subscription
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)

                # If subscription is submitted, we need to cancel and recreate it
                if subscription.docstatus == 1:
                    subscription.cancel()
                    result["old_subscription_cancelled"] = True

                    # Create new subscription with correct plan
                    new_subscription = membership.create_subscription_from_membership()
                    result["new_subscription_created"] = new_subscription.name

                    # Update membership to point to new subscription
                    membership.subscription = new_subscription.name
                    membership.save(ignore_permissions=True)
                else:
                    # Update the plan for draft subscription
                    for plan_row in subscription.plans:
                        plan_row.plan = correct_plan

                    subscription.save(ignore_permissions=True)

                # Get updated state
                subscription.reload()
                result["after_fix"] = {"subscription_name": subscription.name, "plans": []}

                for plan in subscription.plans:
                    plan_doc = frappe.get_doc("Subscription Plan", plan.plan)
                    result["after_fix"]["plans"].append({"plan_name": plan.plan, "plan_cost": plan_doc.cost})

                result["fix_applied"] = True

        return result

    except Exception as e:
        return {"error": str(e), "membership_name": membership_name}


@frappe.whitelist()
def check_subscription_invoice(invoice_name):
    """Check subscription invoice details"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        return {
            "invoice_name": invoice_name,
            "status": invoice.status,
            "grand_total": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "docstatus": invoice.docstatus,
            "subscription": invoice.subscription,
            "posting_date": invoice.posting_date,
        }

    except Exception as e:
        return {"error": str(e), "invoice_name": invoice_name}


@frappe.whitelist()
def send_overdue_notifications():
    """Send notifications for overdue applications (> 2 weeks)"""
    # This would be called by a scheduled job

    two_weeks_ago = add_days(today(), -14)

    # Get overdue applications
    overdue = frappe.get_all(
        "Member",
        filters={"application_status": "Pending", "application_date": ["<", two_weeks_ago]},
        fields=["name", "full_name", "application_date", "current_chapter_display"],
    )

    if not overdue:
        return

    # Group by chapter
    by_chapter = {}
    no_chapter = []

    for app in overdue:
        chapter = app.current_chapter_display
        if chapter:
            if chapter not in by_chapter:
                by_chapter[chapter] = []
            by_chapter[chapter].append(app)
        else:
            no_chapter.append(app)

    # Send notifications to chapter boards
    for chapter_name, apps in by_chapter.items():
        notify_chapter_of_overdue_applications(chapter_name, apps)

    # Send notification for applications without chapters to association managers
    if no_chapter:
        notify_managers_of_overdue_applications(no_chapter)

    return {"notified_chapters": len(by_chapter), "no_chapter_apps": len(no_chapter)}


def notify_chapter_of_overdue_applications(chapter_name, applications):
    """Notify chapter board of overdue applications"""
    chapter = frappe.get_doc("Chapter", chapter_name)

    # Get board members with membership permissions
    recipients = []
    for board_member in chapter.board_members:
        if board_member.is_active and board_member.email:
            role = frappe.get_doc("Chapter Role", board_member.chapter_role)
            if role.permissions_level in ["Admin", "Membership"]:
                recipients.append(board_member.email)

    if recipients:
        # Create application list HTML
        # app_list = "\n".join(
        #     [
        #         f"<li>{app.full_name} - Applied {frappe.format_date(app.application_date)} "
        #         f"({(getdate(today()) - getdate(app.application_date)).days} days ago)</li>"
        #         for app in applications
        #     ]
        # )

        frappe.sendmail(
            recipients=recipients,
            subject=f"Action Required: {len(applications)} Overdue Membership Applications",
            message="""
            <h3>Overdue Membership Applications for {chapter_name}</h3>

            <p>The following membership applications have been pending for more than 2 weeks:</p>

            <ul>
            {app_list}
            </ul>

            <p>Please review these applications as soon as possible.</p>

            <p><a href="{frappe.utils.get_url()}/app/member?application_status=Pending&current_chapter_display={chapter_name}">
            View All Pending Applications</a></p>
            """,
            now=True,
        )


def notify_managers_of_overdue_applications(applications):
    """Notify association managers of overdue applications without chapters"""
    # Get all association managers
    managers = frappe.get_all("Has Role", filters={"role": "Verenigingen Administrator"}, pluck="parent")

    if managers:
        recipients = [
            frappe.get_value("User", m, "email") for m in managers if frappe.get_value("User", m, "enabled")
        ]

        if recipients:
            # app_list = "\n".join(
            #     [
            #         f"<li>{app.full_name} - Applied {frappe.format_date(app.application_date)} "
            #         f"({(getdate(today()) - getdate(app.application_date)).days} days ago)</li>"
            #         for app in applications
            #     ]
            # )

            frappe.sendmail(
                recipients=recipients,
                subject=f"Action Required: {len(applications)} Unassigned Overdue Applications",
                message="""
                <h3>Overdue Membership Applications Without Chapter Assignment</h3>

                <p>The following membership applications have been pending for more than 2 weeks
                and have no chapter assignment:</p>

                <ul>
                {app_list}
                </ul>

                <p>Please review and assign these applications to appropriate chapters.</p>

                <p><a href="{frappe.utils.get_url()}/app/member?application_status=Pending&current_chapter_display=">
                View Unassigned Applications</a></p>
                """,
                now=True,
            )


@frappe.whitelist()
def create_default_email_templates():
    """Create default email templates for membership application management"""
    if not frappe.has_permission("Email Template", "create"):
        frappe.throw(_("You don't have permission to create email templates"))

    templates = []

    # 1. General rejection template
    if not frappe.db.exists("Email Template", "membership_application_rejected"):
        rejection_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_rejected",
                "subject": "Membership Application Update - {{ member_name }}",
                "enabled": 1,
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review, we regret to inform you that your membership application has not been approved at this time.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Reason:</strong> {{ reason }}</p>
</div>

<p>If you have any questions or would like to discuss this decision, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        rejection_template.insert()
        templates.append("membership_application_rejected")

    # 2. Incomplete information rejection
    if not frappe.db.exists("Email Template", "membership_rejection_incomplete"):
        incomplete_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_incomplete",
                "subject": "Membership Application - Additional Information Required - {{ member_name }}",
                "enabled": 1,
                "response": """
<h3>Membership Application - Additional Information Required</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have reviewed your membership application, but unfortunately we need additional information to proceed with your application.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Missing Information:</strong> {{ reason }}</p>
</div>

<p>You are welcome to submit a new application with the complete information at any time. We encourage you to reapply once you have the required documentation or details.</p>

<p>If you have any questions about what information is needed, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        incomplete_template.insert()
        templates.append("membership_rejection_incomplete")

    # 3. Ineligible rejection
    if not frappe.db.exists("Email Template", "membership_rejection_ineligible"):
        ineligible_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_ineligible",
                "subject": "Membership Application Update - {{ member_name }}",
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review of your application, we regret to inform you that you do not currently meet the eligibility requirements for membership.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>We encourage you to review our membership requirements and consider reapplying in the future if your circumstances change.</p>

<p>If you have any questions about our membership criteria, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        ineligible_template.insert()
        templates.append("membership_rejection_ineligible")

    # 4. Duplicate application rejection
    if not frappe.db.exists("Email Template", "membership_rejection_duplicate"):
        duplicate_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_duplicate",
                "subject": "Membership Application - Duplicate Detected - {{ member_name }}",
                "response": """
<h3>Membership Application - Duplicate Application</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have detected that you have already submitted a membership application or are already a member of our association.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>If you believe this is an error or if you need assistance with your existing membership, please contact us immediately.</p>

<p>If you have any questions, please don't hesitate to reach out.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        duplicate_template.insert()
        templates.append("membership_rejection_duplicate")

    # Also create approval template if it doesn't exist
    if not frappe.db.exists("Email Template", "membership_application_approved"):
        approval_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_approved",
                "subject": "Membership Application Approved - Payment Required - {{ member_name }}",
                "response": """
<h2>🎉 Membership Application Approved!</h2>

<p>Dear {{ first_name }},</p>

<p>Congratulations! Your membership application has been approved.</p>

<div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <h4>Application Details:</h4>
    <ul>
        <li><strong>Application ID:</strong> {{ application_id }}</li>
        <li><strong>Membership Type:</strong> {{ membership_type.membership_type_name }}</li>
        <li><strong>Fee Amount:</strong> {{ payment_amount }}</li>
    </ul>
</div>

<p>To complete your membership, please pay the membership fee using the link below:</p>

<div style="text-align: center; margin: 20px 0;">
    <a href="{{ payment_url }}" style="background-color: #4CAF50; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
        Pay Membership Fee
    </a>
</div>

<p>Your membership will be activated immediately after payment confirmation.</p>

<p>If you have any questions, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        approval_template.insert()
        templates.append("membership_application_approved")

    frappe.db.commit()

    return {"success": True, "message": f"Created {len(templates)} email templates", "templates": templates}
