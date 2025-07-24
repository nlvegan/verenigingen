"""
Notification utilities for membership applications
"""
import frappe
from frappe.utils import add_days, getdate, today


def format_email_subject(template, **kwargs):
    """
    Helper function to consistently format email subjects with variable substitution

    Args:
        template (str): Subject template with placeholder variables
        **kwargs: Variables to substitute

    Returns:
        str: Formatted subject line
    """
    try:
        # Use f-string style formatting for better error handling
        return template.format(**kwargs)
    except KeyError as e:
        frappe.log_error(f"Missing template variable: {str(e)}", "Email Subject Formatting")
        # Return template with missing variables highlighted
        return template + f" [MISSING: {str(e)}]"
    except Exception as e:
        frappe.log_error(f"Email subject formatting error: {str(e)}", "Email Subject Formatting")
        return template


def send_application_confirmation_email(member, application_id):
    """Send confirmation email with application ID"""
    try:
        message = f"""
        <h3>Thank you for your membership application!</h3>

        <p>Dear {member.first_name},</p>

        <p>We have received your membership application and will review it shortly.</p>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Application Details:</h4>
            <ul>
                <li><strong>Application ID:</strong> {application_id}</li>
                <li><strong>Name:</strong> {member.full_name}</li>
                <li><strong>Status:</strong> Pending Review</li>
                <li><strong>Applied On:</strong> {frappe.utils.format_datetime(member.application_date)}</li>
            </ul>
        </div>

        <p>You can check your application status at any time using your application ID.</p>

        <p>We will contact you within 2-3 business days with the next steps.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email],
            subject=f"Membership Application Received - ID: {application_id}",
            message=message,
            now=True,
            reference_doctype="Member",
            reference_name=member.name,
        )
    except Exception as e:
        frappe.log_error(f"Error sending confirmation email: {str(e)}", "Email Error")


def notify_reviewers_of_new_application(member, application_id):
    """Notify reviewers with application ID"""
    reviewers = get_application_reviewers(member)

    if reviewers:
        message = f"""
        <h3>New Membership Application: {application_id}</h3>

        <p>A new membership application has been submitted:</p>

        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Application ID:</strong></td>
                <td style="padding: 8px; border: 1px solid #dee2e6;">{application_id}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Name:</strong></td>
                <td style="padding: 8px; border: 1px solid #dee2e6;">{member.full_name}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Email:</strong></td>
                <td style="padding: 8px; border: 1px solid #dee2e6;">{member.email}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Chapter:</strong></td>
                <td style="padding: 8px; border: 1px solid #dee2e6;">{get_member_primary_chapter(member.name) or 'Not assigned'}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Applied On:</strong></td>
                <td style="padding: 8px; border: 1px solid #dee2e6;">{frappe.utils.format_datetime(member.application_date)}</td>
            </tr>
        </table>

        <p><a href="{frappe.utils.get_url()}/app/member/{member.name}"
             style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
            Review Application
        </a></p>
        """

        frappe.sendmail(
            recipients=reviewers,
            subject=f"New Application: {application_id} - {member.full_name}",
            message=message,
            now=True,
        )


def send_approval_email(member, invoice):
    """Send email when application is approved with payment instructions"""
    try:
        payment_url = frappe.utils.get_url() + f"/payment?invoice={invoice.name}"

        message = f"""
        <h3>Your membership application has been approved!</h3>

        <p>Dear {member.first_name},</p>

        <p>Congratulations! Your membership application has been approved.</p>

        <div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Next Steps:</h4>
            <ol>
                <li>Complete your membership payment</li>
                <li>Receive your membership confirmation</li>
                <li>Access member benefits and resources</li>
            </ol>
        </div>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Payment Details:</h4>
            <ul>
                <li><strong>Amount:</strong> {frappe.utils.fmt_money(invoice.grand_total, currency=invoice.currency)}</li>
                <li><strong>Invoice:</strong> {invoice.name}</li>
                <li><strong>Due Date:</strong> {frappe.format_date(invoice.due_date)}</li>
            </ul>
        </div>

        <p><a href="{payment_url}"
             style="background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
            Complete Payment
        </a></p>

        <p>If you have any questions, please don't hesitate to contact us.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email],
            subject="Membership Approved - Payment Required",
            message=message,
            now=True,
            reference_doctype="Member",
            reference_name=member.name,
        )
    except Exception as e:
        frappe.log_error(f"Error sending approval email: {str(e)}", "Email Error")


def send_rejection_email(member, reason):
    """Send email when application is rejected"""
    try:
        message = f"""
        <h3>Regarding your membership application</h3>

        <p>Dear {member.first_name},</p>

        <p>Thank you for your interest in becoming a member. After careful review,
        we are unable to approve your membership application at this time.</p>

        <div style="background: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Reason:</h4>
            <p>{reason}</p>
        </div>

        <p>If you believe this decision was made in error or if your circumstances have changed,
        you may submit a new application or contact us for clarification.</p>

        <p>Thank you for your understanding.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email],
            subject="Membership Application Update",
            message=message,
            now=True,
            reference_doctype="Member",
            reference_name=member.name,
        )
    except Exception as e:
        frappe.log_error(f"Error sending rejection email: {str(e)}", "Email Error")


def send_payment_confirmation_email(member, invoice):
    """Send confirmation email after successful payment"""
    try:
        message = f"""
        <h3>Welcome! Your membership is now active</h3>

        <p>Dear {member.first_name},</p>

        <p>Thank you for your payment. Your membership is now active!</p>

        <div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Membership Details:</h4>
            <ul>
                <li><strong>Member ID:</strong> {member.name}</li>
                <li><strong>Membership Type:</strong> {member.selected_membership_type}</li>
                <li><strong>Start Date:</strong> {frappe.format_date(today())}</li>
                <li><strong>Chapter:</strong> {get_member_primary_chapter(member.name) or 'To be assigned'}</li>
            </ul>
        </div>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>What's Next:</h4>
            <ul>
                <li>Access the member portal</li>
                <li>Join your local chapter activities</li>
                <li>Connect with other members</li>
                <li>Explore member benefits</li>
            </ul>
        </div>

        <p><a href="{frappe.utils.get_url()}/member-dashboard"
             style="background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
            Access Member Portal
        </a></p>

        <p>Welcome to our community!</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        frappe.sendmail(
            recipients=[member.email],
            subject="Welcome! Your membership is active",
            message=message,
            now=True,
            reference_doctype="Member",
            reference_name=member.name,
        )
    except Exception as e:
        frappe.log_error(f"Error sending payment confirmation email: {str(e)}", "Email Error")


def get_application_reviewers(member):
    """Get list of reviewers for application"""
    reviewers = []

    # 1. Chapter board members (if chapter assigned)
    chapter = (
        getattr(member, "selected_chapter", None)
        or getattr(member, "suggested_chapter", None)
        or get_member_primary_chapter(member.name)
    )
    if chapter:
        try:
            chapter_doc = frappe.get_doc("Chapter", chapter)
            for board_member in chapter_doc.board_members:
                if board_member.is_active and board_member.email:
                    role = frappe.get_doc("Chapter Role", board_member.chapter_role)
                    if role.permissions_level in ["Admin", "Membership"]:
                        reviewers.append(board_member.email)
        except Exception as e:
            frappe.log_error(f"Error getting chapter reviewers: {str(e)}")

    # 2. Verenigingen Administrators
    try:
        managers = frappe.db.sql(
            """
            SELECT u.email
            FROM `tabUser` u
            JOIN `tabHas Role` r ON r.parent = u.name
            WHERE r.role = 'Verenigingen Administrator'
            AND u.enabled = 1
        """,
            as_dict=True,
        )

        reviewers.extend([m.email for m in managers])
    except Exception as e:
        frappe.log_error(f"Error getting association managers: {str(e)}")

    # 3. National board if no chapter
    if not chapter:
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                national_board = frappe.get_doc("Chapter", settings.national_board_chapter)
                for board_member in national_board.board_members:
                    if board_member.is_active and board_member.email:
                        reviewers.append(board_member.email)
        except Exception as e:
            frappe.log_error(f"Error getting national board reviewers: {str(e)}")

    return list(set(reviewers))


def notify_admins_of_new_application(member, invoice=None):
    """Notify system administrators of new applications"""
    try:
        admins = frappe.db.sql(
            """
            SELECT u.email
            FROM `tabUser` u
            JOIN `tabHas Role` r ON r.parent = u.name
            WHERE r.role = 'System Manager'
            AND u.enabled = 1
        """,
            as_dict=True,
        )

        if not admins:
            return

        # payment_info = ""
        if invoice:
            pass
            # payment_info = """
            # <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
            #     <h4>Payment Required:</h4>
            #     <p><strong>Invoice:</strong> {invoice.name}</p>
            #     <p><strong>Amount:</strong> {frappe.utils.fmt_money(invoice.grand_total, currency=invoice.currency)}</p>
            #     <p><strong>Due Date:</strong> {frappe.format_date(invoice.due_date)}</p>
            # </div>
            # """

        message = f"""
        <h3>New Membership Application</h3>

        <p>A new membership application has been submitted:</p>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Application Details:</h4>
            <ul>
                <li><strong>Name:</strong> {member.full_name}</li>
                <li><strong>Email:</strong> {member.email}</li>
                <li><strong>Application ID:</strong> {member.application_id}</li>
                <li><strong>Status:</strong> {member.application_status}</li>
                <li><strong>Applied On:</strong> {frappe.utils.format_datetime(member.application_date)}</li>
            </ul>
        </div>

        {payment_info}

        <p><a href="{frappe.utils.get_url()}/app/member/{member.name}"
             style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
            View Application
        </a></p>
        """

        frappe.sendmail(
            recipients=[admin.email for admin in admins],
            subject=f"New Application: {member.full_name}",
            message=message,
            now=True,
        )
    except Exception as e:
        frappe.log_error(f"Error notifying admins: {str(e)}", "Notification Error")


def check_overdue_applications():
    """Check for applications pending more than 7 days"""
    seven_days_ago = add_days(today(), -7)

    overdue = frappe.get_all(
        "Member",
        filters={"application_status": "Pending", "application_date": ["<", seven_days_ago]},
        fields=["name", "full_name", "application_date", "email", "current_membership_type"],
    )

    if overdue:
        # Notify national board
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                national_board = frappe.get_doc("Chapter", settings.national_board_chapter)
                recipients = [bm.email for bm in national_board.board_members if bm.is_active and bm.email]

                if recipients:
                    # Use Email Template if available
                    # Calculate days overdue for each application
                    overdue_with_days = []
                    for app in overdue:
                        days_overdue = (getdate(today()) - getdate(app.application_date)).days
                        overdue_with_days.append({**app, "days_overdue": days_overdue})

                    args = {
                        "overdue_applications": overdue_with_days,
                        "overdue_count": len(overdue),
                        "reviewer_name": "Membership Team",
                        "company": frappe.defaults.get_global_default("company"),
                        "base_url": frappe.utils.get_url(),
                    }

                    if frappe.db.exists("Email Template", "membership_applications_overdue"):
                        email_template_doc = frappe.get_doc(
                            "Email Template", "membership_applications_overdue"
                        )
                        frappe.sendmail(
                            recipients=recipients,
                            subject=frappe.render_template(email_template_doc.subject, args),
                            message=frappe.render_template(email_template_doc.response, args),
                            now=True,
                        )
                    else:
                        # Fallback to simple message
                        app_list = "\n".join(
                            [
                                f"<li>{app['full_name']} (Applied: {app['application_date']}, {app.get('days_overdue', 0)} days overdue)</li>"
                                for app in overdue_with_days
                            ]
                        )
                        message = f"""
                        <h3>Overdue Membership Applications</h3>
                        <p>The following membership applications have been pending for more than 7 days:</p>
                        <ul>
                        {app_list}
                        </ul>
                        <p>Please review these applications as soon as possible.</p>
                        """
                        frappe.sendmail(
                            recipients=recipients,
                            subject="Overdue Membership Applications",
                            message=message,
                            now=True,
                        )
        except Exception as e:
            frappe.log_error(f"Error notifying about overdue applications: {str(e)}")


def send_simple_notification(data, member_id):
    """Send simple notification about application submission"""
    try:
        message = f"""
        <h3>Application Submitted Successfully</h3>

        <p>Your membership application has been submitted and is being reviewed.</p>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Details:</h4>
            <ul>
                <li><strong>Member ID:</strong> {member_id}</li>
                <li><strong>Name:</strong> {data.get('first_name', '')} {data.get('last_name', '')}</li>
                <li><strong>Submitted:</strong> {frappe.utils.format_datetime(now_datetime())}</li>
            </ul>
        </div>

        <p>You will receive updates about your application status via email.</p>
        """

        frappe.sendmail(
            recipients=[data.get("email")],
            subject="Membership Application Submitted",
            message=message,
            now=True,
        )
    except Exception as e:
        frappe.log_error(f"Error sending simple notification: {str(e)}", "Notification Error")


def get_member_primary_chapter(member_name):
    """Get member's primary chapter (first in Chapter Member list)"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
            limit=1,
        )
        return chapters[0].parent if chapters else None
    except Exception:
        return None
