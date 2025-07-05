import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.application_notifications import send_payment_confirmation_email, send_rejection_email


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False

    # Get membership types for the form
    context.membership_types = frappe.get_all(
        "Membership Type",
        filters={"is_active": 1},
        fields=["name", "membership_fee", "description"],
        order_by="membership_fee",
    )

    # Get countries for address
    context.countries = frappe.get_all("Country", fields=["name"])

    # Get calculator settings from Verenigingen Settings
    settings = frappe.get_single("Verenigingen Settings")
    context.enable_income_calculator = getattr(settings, "enable_income_calculator", 0)
    context.income_percentage_rate = getattr(settings, "income_percentage_rate", 0.5)
    context.calculator_description = getattr(
        settings,
        "calculator_description",
        "Our suggested contribution is 0.5% of your monthly net income. This helps ensure fair and equitable contributions based on your financial capacity.",
    )

    return context


@frappe.whitelist(allow_guest=True)
def submit_membership_application(data):
    """Process membership application from portal"""
    import json

    if isinstance(data, str):
        data = json.loads(data)

    # Validate required fields
    required_fields = ["first_name", "last_name", "email", "birth_date"]
    for field in required_fields:
        if not data.get(field):
            frappe.throw(_("Please fill all required fields"))

    # Check if member with this email already exists
    existing = frappe.db.exists("Member", {"email": data.get("email")})
    if existing:
        frappe.throw(_("A member with this email already exists. Please login or contact support."))

    try:
        # Create address first if provided
        address_name = None
        if data.get("address_line1"):
            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": f"{data.get('first_name')} {data.get('last_name')}",
                    "address_type": "Personal",
                    "address_line1": data.get("address_line1"),
                    "address_line2": data.get("address_line2", ""),
                    "city": data.get("city"),
                    "state": data.get("state", ""),
                    "country": data.get("country"),
                    "pincode": data.get("postal_code"),
                    "email_id": data.get("email"),
                    "phone": data.get("phone", ""),
                }
            )
            address.insert(ignore_permissions=True)
            address_name = address.name

        # Suggest chapter based on postal code
        suggested_chapter = None
        if data.get("postal_code"):
            chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name", "postal_codes"])

            for chapter in chapters:
                if chapter.postal_codes:
                    chapter_doc = frappe.get_doc("Chapter", chapter.name)
                    if chapter_doc.matches_postal_code(data.get("postal_code")):
                        suggested_chapter = chapter.name
                        break

        # Create member record
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": data.get("first_name"),
                "middle_name": data.get("middle_name", ""),
                "last_name": data.get("last_name"),
                "email": data.get("email"),
                "phone": data.get("phone", ""),
                "birth_date": data.get("birth_date"),
                "pronouns": data.get("pronouns", ""),
                "primary_address": address_name,
                "status": "Pending",  # New members start as pending
                "application_status": "Pending",
                "application_date": now_datetime(),
                "suggested_chapter": suggested_chapter,
                "current_chapter_display": suggested_chapter,  # Tentatively assign
                "notes": data.get("motivation", ""),  # Why they want to join
            }
        )

        # Handle bank details if provided (for direct debit)
        if data.get("payment_method") == "SEPA Direct Debit" and data.get("iban"):
            member.payment_method = "SEPA Direct Debit"
            member.iban = data.get("iban")
            member.bank_account_name = data.get("bank_account_name", "")

        # Handle income calculator data if provided
        if data.get("monthly_income") and data.get("payment_interval"):
            member.monthly_income = data.get("monthly_income")
            member.preferred_payment_interval = data.get("payment_interval")

        member.insert(ignore_permissions=True)

        # Send notifications
        send_application_notifications(member)

        # Send confirmation email to applicant
        send_application_confirmation(member)

        return {
            "success": True,
            "message": _("Thank you for your application! We will review it and get back to you soon."),
            "member_id": member.name,
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Membership Application Error")
        frappe.throw(_("An error occurred while processing your application. Please try again."))


def send_application_notifications(member):
    """Send notifications to relevant reviewers"""
    recipients = []

    # Notify association managers
    managers = frappe.get_all(
        "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent as user"]
    )
    recipients.extend([m.user for m in managers])

    # If chapter is suggested, notify chapter board members
    if member.suggested_chapter:
        chapter = frappe.get_doc("Chapter", member.suggested_chapter)

        # Get board members with appropriate roles
        for board_member in chapter.board_members:
            if board_member.is_active and board_member.email:
                # Check if role has membership approval permissions
                role = frappe.get_doc("Chapter Role", board_member.chapter_role)
                if role.permissions_level in ["Admin", "Membership"]:
                    recipients.append(board_member.email)

    # Remove duplicates
    recipients = list(set(recipients))

    if recipients:
        frappe.sendmail(
            recipients=recipients,
            subject=f"New Membership Application: {member.full_name}",
            message="""
            <h3>New Membership Application Received</h3>
            <p>A new membership application has been submitted:</p>
            <ul>
                <li><strong>Name:</strong> {member.full_name}</li>
                <li><strong>Email:</strong> {member.email}</li>
                <li><strong>Suggested Chapter:</strong> {member.suggested_chapter or 'None'}</li>
                <li><strong>Application Date:</strong> {frappe.utils.format_datetime(member.application_date)}</li>
            </ul>
            <p><a href="{frappe.utils.get_url()}/app/member/{member.name}">Review Application</a></p>
            """,
            now=True,
        )


def send_application_confirmation(member):
    """Send confirmation email to applicant"""
    frappe.sendmail(
        recipients=[member.email],
        subject="Membership Application Received",
        message="""
        <h3>Thank you for your membership application!</h3>
        <p>Dear {member.first_name},</p>
        <p>We have received your membership application and it is currently under review.</p>
        <p>You will receive an email once your application has been processed.</p>
        <p>If you have any questions, please don't hesitate to contact us.</p>
        <p>Best regards,<br>The Membership Team</p>
        """,
        now=True,
    )


@frappe.whitelist()
def approve_membership_application(member_name, create_invoice=True, membership_type=None):
    """Approve a membership application"""
    member = frappe.get_doc("Member", member_name)

    if member.application_status != "Pending":
        frappe.throw(_("This application has already been processed"))

    # Update member status
    member.application_status = "Approved"
    member.status = "Active"
    member.reviewed_by = frappe.session.user
    member.review_date = now_datetime()
    member.member_since = today()
    member.save()

    # Create membership record if type specified
    if membership_type and create_invoice:
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member_name,
                "membership_type": membership_type,
                "start_date": today(),
                "status": "Pending",  # Will become active after payment
            }
        )
        membership.insert()
        membership.submit()

        # Generate invoice
        invoice = membership.generate_invoice()

        # Send welcome email with invoice
        send_payment_confirmation_email(member, invoice)
    else:
        # Just send welcome email
        send_payment_confirmation_email(member, None)

    return {"success": True}


@frappe.whitelist()
def reject_membership_application(member_name, reason):
    """Reject a membership application"""
    member = frappe.get_doc("Member", member_name)

    if member.application_status != "Pending":
        frappe.throw(_("This application has already been processed"))

    # Update member status
    member.application_status = "Rejected"
    member.status = "Rejected"
    member.reviewed_by = frappe.session.user
    member.review_date = now_datetime()
    member.review_notes = reason
    member.save()

    # Send rejection email
    send_rejection_email(member, reason)

    return {"success": True}
