"""
Newsletter Demo and Setup Script
Creates sample email groups and demonstrates newsletter functionality
"""

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def setup_email_groups():
    """Create default email groups for the organization"""

    groups_created = []

    # 1. All Active Members group
    if not frappe.db.exists("Email Group", "All Active Members"):
        all_members = frappe.new_doc("Email Group")
        all_members.title = "All Active Members"
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=all_members,
            justification="Create All Active Members email group for newsletter system - communication management",
            required_permissions=["Email Group:create"],
        )

        if result.success:
            groups_created.append("All Active Members")
        else:
            frappe.log_error(f"Failed to create All Active Members email group: {'; '.join(result.errors)}")

    # 2. Newsletter Subscribers (respects opt-out)
    if not frappe.db.exists("Email Group", "Newsletter Subscribers"):
        newsletter_group = frappe.new_doc("Email Group")
        newsletter_group.title = "Newsletter Subscribers"
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=newsletter_group,
            justification="Create Newsletter Subscribers email group for newsletter system - member communications with opt-out compliance",
            required_permissions=["Email Group:create"],
        )

        if result.success:
            groups_created.append("Newsletter Subscribers")
        else:
            frappe.log_error(
                f"Failed to create Newsletter Subscribers email group: {'; '.join(result.errors)}"
            )

    # 3. Chapter-specific groups
    chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name"])
    for chapter in chapters:
        group_name = f"{chapter.name} Members"
        if not frappe.db.exists("Email Group", group_name):
            chapter_group = frappe.new_doc("Email Group")
            chapter_group.title = group_name
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="insert",
                doc=chapter_group,
                justification=f"Create {group_name} email group for chapter-specific communications - geographic member organization",
                required_permissions=["Email Group:create"],
            )

            if result.success:
                groups_created.append(group_name)
            else:
                frappe.log_error(f"Failed to create {group_name} email group: {'; '.join(result.errors)}")

    # 4. Board Members group
    if not frappe.db.exists("Email Group", "Board Members"):
        board_group = frappe.new_doc("Email Group")
        board_group.title = "Board Members"
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=board_group,
            justification="Create Board Members email group for governance communications - board administration",
            required_permissions=["Email Group:create"],
        )

        if result.success:
            groups_created.append("Board Members")
        else:
            frappe.log_error(f"Failed to create Board Members email group: {'; '.join(result.errors)}")

    # 5. Volunteers group
    if not frappe.db.exists("Email Group", "Active Volunteers"):
        volunteer_group = frappe.new_doc("Email Group")
        volunteer_group.title = "Active Volunteers"
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=volunteer_group,
            justification="Create Active Volunteers email group for volunteer communications - volunteer coordination",
            required_permissions=["Email Group:create"],
        )

        if result.success:
            groups_created.append("Active Volunteers")
        else:
            frappe.log_error(f"Failed to create Active Volunteers email group: {'; '.join(result.errors)}")

    frappe.db.commit()

    return {
        "success": True,
        "groups_created": groups_created,
        "message": f"Created {len(groups_created)} email groups",
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def populate_email_groups():
    """Populate email groups with current members"""

    stats = {
        "all_members": 0,
        "newsletter_subscribers": 0,
        "board_members": 0,
        "volunteers": 0,
        "chapter_groups": {},
    }

    # Get all active members
    members = frappe.get_all(
        "Member",
        filters={"status": "Active"},
        fields=["name", "email", "first_name", "last_name", "accepts_optional_communications"],
    )

    for member in members:
        if not member.email:
            continue

        # Add to All Active Members
        add_to_email_group("All Active Members", member.email, member.first_name)
        stats["all_members"] += 1

        # Add to Newsletter Subscribers (only if opted in)
        if member.accepts_optional_communications:
            add_to_email_group("Newsletter Subscribers", member.email, member.first_name)
            stats["newsletter_subscribers"] += 1

        # Find member's chapter(s)
        chapters = frappe.db.sql(
            """
            SELECT DISTINCT parent as chapter
            FROM `tabChapter Member`
            WHERE member = %s AND enabled = 1
        """,
            member.name,
            as_dict=True,
        )

        for chapter_record in chapters:
            group_name = f"{chapter_record.chapter} Members"
            if frappe.db.exists("Email Group", group_name):
                add_to_email_group(group_name, member.email, member.first_name)
                if group_name not in stats["chapter_groups"]:
                    stats["chapter_groups"][group_name] = 0
                stats["chapter_groups"][group_name] += 1

    # Add board members
    board_members = frappe.db.sql(
        """
        SELECT DISTINCT m.email, m.first_name
        FROM `tabChapter Board Member` cbm
        JOIN `tabVolunteer` v ON v.name = cbm.volunteer
        JOIN `tabMember` m ON m.name = v.member
        WHERE cbm.is_active = 1 AND m.email IS NOT NULL
    """,
        as_dict=True,
    )

    for board_member in board_members:
        add_to_email_group("Board Members", board_member.email, board_member.first_name)
        stats["board_members"] += 1

    # Add volunteers
    volunteers = frappe.db.sql(
        """
        SELECT DISTINCT m.email, m.first_name
        FROM `tabVolunteer` v
        JOIN `tabMember` m ON m.name = v.member
        WHERE v.status = 'Active' AND m.email IS NOT NULL
    """,
        as_dict=True,
    )

    for volunteer in volunteers:
        add_to_email_group("Active Volunteers", volunteer.email, volunteer.first_name)
        stats["volunteers"] += 1

    frappe.db.commit()

    return {"success": True, "statistics": stats, "message": "Email groups populated successfully"}


def add_to_email_group(group_name, email, member_name=None):
    """Add an email to an email group if not already present"""

    # Check if already in group
    existing = frappe.db.exists("Email Group Member", {"email_group": group_name, "email": email})

    if not existing:
        member = frappe.new_doc("Email Group Member")
        member.email_group = group_name
        member.email = email
        member.unsubscribed = 0
        # Note: Email Group Member doesn't have a name field - email is the identifier
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=member,
            justification=f"Add {email} to {group_name} email group - member email list management",
            required_permissions=["Email Group Member:create"],
        )

        return result.success
    return False


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_sample_newsletter():
    """Create a sample newsletter template"""

    newsletter_name = "Monthly Member Update"
    if not frappe.db.exists("Newsletter", newsletter_name):
        # Get default email account
        email_account = frappe.get_value("Email Account", {"default_outgoing": 1}, "email_id")
        if not email_account:
            email_account = "info@example.com"

        newsletter = frappe.new_doc("Newsletter")
        newsletter.subject = "Member Newsletter - Monthly Update"
        newsletter.sender_email = email_account
        newsletter.content_type = "Rich Text"

        # Add email group as child table
        newsletter.append("email_group", {"email_group": "Newsletter Subscribers"})

        newsletter.message = """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2>Dear {{ first_name|default('Member') }},</h2>

    <p>Welcome to our monthly newsletter! Here's what's happening in our organization:</p>

    <h3>📅 Upcoming Events</h3>
    <ul>
        <li>Annual General Meeting - January 15, 2025</li>
        <li>Volunteer Appreciation Dinner - February 1, 2025</li>
        <li>Spring Fundraiser - March 20, 2025</li>
    </ul>

    <h3>🎉 Member Highlights</h3>
    <p>This month we'd like to recognize our outstanding volunteers who have contributed over 100 hours of service!</p>

    <h3>📢 Important Announcements</h3>
    <p>Membership renewal season is approaching. Please ensure your contact information is up to date.</p>

    <hr>

    <p style="color: #666; font-size: 12px;">
        You're receiving this because you're subscribed to our newsletter.
        If you wish to opt out of future optional communications, please update your preferences in your member profile.
    </p>

    <p style="color: #666; font-size: 12px;">
        <strong>Note:</strong> Statutory communications such as AGM notices cannot be opted out of as required by law.
    </p>
</div>
        """
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=newsletter,
            justification="Create sample newsletter template for member communications - newsletter system setup",
            required_permissions=["Newsletter:create"],
        )

        if result.success:
            frappe.db.commit()
            return {
                "success": True,
                "newsletter": newsletter.name,
                "message": "Sample newsletter created successfully",
            }
        else:
            return {"success": False, "message": f"Failed to create newsletter: {'; '.join(result.errors)}"}
    else:
        return {"success": False, "message": "Sample newsletter already exists"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def send_test_newsletter(email_group=None):
    """Send a test newsletter to demonstrate the system"""

    if not email_group:
        email_group = "Newsletter Subscribers"

    # Get test recipients (limit to 5 for demo)
    recipients = frappe.get_all(
        "Email Group Member",
        filters={"email_group": email_group, "unsubscribed": 0},
        fields=["email", "name"],  # Use 'name' field instead of non-existent 'email_group_member_name'
        limit=5,
    )

    if not recipients:
        return {"success": False, "message": f"No recipients found in {email_group} group"}

    # Create a test newsletter
    subject = "Test Newsletter - Please Ignore"
    content = """
    <h2>This is a Test Newsletter</h2>
    <p>This email is being sent to test the newsletter functionality.</p>
    <p>If you received this email, it means you are properly subscribed to our newsletter system.</p>
    <p><strong>No action is required.</strong></p>
    """

    # Send to recipients via EmailService for central control
    from verenigingen.services.communication.email_service import get_email_service

    email_service = get_email_service()
    recipient_emails = [r.email for r in recipients]

    result = email_service.send_simple_email(
        recipients=recipient_emails,
        subject=subject,
        message=content,
        reference_doctype="Email Group",
        reference_name=email_group,
        notification_key="newsletter_campaign",
    )

    return {
        "success": result.success,
        "recipients_count": len(recipients),
        "message": f"Test newsletter sent to {len(recipients)} recipients",
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_newsletter_statistics():
    """Get statistics about newsletter subscribers and opt-outs"""

    stats = {}

    # Total active members
    stats["total_active_members"] = frappe.db.count("Member", {"status": "Active"})

    # Members with email
    stats["members_with_email"] = frappe.db.count("Member", {"status": "Active", "email": ["!=", ""]})

    # Members who declined optional communications (only count those with email to match denominator)
    stats["opted_out_members"] = frappe.db.count(
        "Member", {"status": "Active", "email": ["!=", ""], "accepts_optional_communications": 0}
    )

    # Newsletter subscribers (members who accept optional communications)
    stats["newsletter_subscribers"] = stats["members_with_email"] - stats["opted_out_members"]

    # Opt-out percentage
    if stats["members_with_email"] > 0:
        stats["opt_out_percentage"] = round(
            (stats["opted_out_members"] / stats["members_with_email"]) * 100, 2
        )
    else:
        stats["opt_out_percentage"] = 0

    # Email groups
    stats["email_groups"] = frappe.db.count("Email Group")

    # Recent newsletters
    stats["recent_newsletters"] = frappe.get_all(
        "Newsletter", fields=["name", "subject", "modified"], order_by="modified desc", limit=5
    )

    return stats
