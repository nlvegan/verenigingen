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
        fields=["name", "amount", "description"],
        order_by="amount",
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
                "tussenvoegsel": data.get("tussenvoegsel", ""),
                "last_name": data.get("last_name"),
                "email": data.get("email"),
                "contact_number": data.get("phone", ""),
                "birth_date": data.get("birth_date"),
                "pronouns": data.get("pronouns", ""),
                "primary_address": address_name,
                "status": "Pending",  # New members start as pending
                "application_status": "Pending",
                "application_date": now_datetime(),
                "suggested_chapter": suggested_chapter,
                "current_chapter_display": suggested_chapter,  # Tentatively assign
                "notes": data.get("motivation", ""),  # Why they want to join
                # Mark this as an application-created member
                "application_id": f"APP-{now_datetime().strftime('%Y%m%d%H%M%S')}-{data.get('email', '').split('@')[0][:5]}",
                "interested_in_volunteering": data.get("interested_in_volunteering", False),
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

        # Handle volunteer information if provided
        if data.get("interested_in_volunteering"):
            create_volunteer_application_data(member, data)

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
            message=f"""
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
        message=f"""
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

    # Create volunteer record if member expressed interest
    if member.interested_in_volunteering:
        create_volunteer_from_approved_member(member)

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


def create_volunteer_application_data(member, application_data):
    """Store volunteer interest and skills data for later processing"""

    # Create a custom doctype or use a simple approach with member custom fields
    # For now, let's store it in member notes and create a separate volunteer interest record

    volunteer_info = {
        "interested_in_volunteering": True,
        "volunteer_availability": application_data.get("volunteer_availability", ""),
        "volunteer_experience_level": application_data.get("volunteer_experience_level", ""),
        "volunteer_areas": application_data.get("volunteer_areas", []),
        "volunteer_skills": application_data.get("volunteer_skills", []),
        "volunteer_skill_level": application_data.get("volunteer_skill_level", ""),
        "volunteer_availability_time": application_data.get("volunteer_availability_time", ""),
        "volunteer_comments": application_data.get("volunteer_comments", ""),
    }

    # Store volunteer interest data in a custom field or notes
    volunteer_notes = f"""
VOLUNTEER INTEREST APPLICATION DATA:
==================================

Interested in Volunteering: Yes
Availability: {volunteer_info['volunteer_availability']}
Experience Level: {volunteer_info['volunteer_experience_level']}
Overall Skill Level: {volunteer_info['volunteer_skill_level']}

Areas of Interest:
{', '.join(volunteer_info['volunteer_areas']) if volunteer_info['volunteer_areas'] else 'None specified'}

Skills Selected:
"""

    # Process skills data
    skills_by_category = {}
    if volunteer_info["volunteer_skills"]:
        for skill_value in volunteer_info["volunteer_skills"]:
            if "|" in skill_value:
                category, skill_name = skill_value.split("|", 1)
                if category not in skills_by_category:
                    skills_by_category[category] = []
                skills_by_category[category].append(skill_name)

    # Add skills to notes
    if skills_by_category:
        for category, skills in skills_by_category.items():
            volunteer_notes += f"\n{category}: {', '.join(skills)}"
    else:
        volunteer_notes += "\nNone specified"

    # Add availability and comments
    if volunteer_info["volunteer_availability_time"]:
        volunteer_notes += f"\n\nAvailability Details:\n{volunteer_info['volunteer_availability_time']}"

    if volunteer_info["volunteer_comments"]:
        volunteer_notes += f"\n\nAdditional Comments:\n{volunteer_info['volunteer_comments']}"

    # Store in member record
    if member.notes:
        member.notes += f"\n\n{volunteer_notes}"
    else:
        member.notes = volunteer_notes

    # Set the volunteer interest flag
    member.interested_in_volunteering = True
    member.db_set("interested_in_volunteering", True, update_modified=False)

    # Create a separate volunteer application record for review
    try:
        volunteer_application = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member.name,
                "content": f"<h4>Volunteer Interest Application</h4><pre>{volunteer_notes}</pre>",
                "comment_email": member.email,
                "comment_by": member.email,
            }
        )
        volunteer_application.insert(ignore_permissions=True)
    except Exception as e:
        # If comment creation fails, just log it - don't fail the application
        frappe.log_error(f"Could not create volunteer application comment: {str(e)}")

    return volunteer_info


def create_volunteer_from_approved_member(member):
    """Create a volunteer record from an approved member with volunteer interest"""

    try:
        # Check if volunteer already exists
        existing_volunteer = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        if existing_volunteer:
            frappe.logger().info(f"Volunteer record already exists for member {member.name}")
            return existing_volunteer

        # Parse volunteer data from member notes or comments
        volunteer_data = parse_volunteer_data_from_notes(member.notes)

        # If not in notes, check comments
        if not volunteer_data:
            comments = frappe.get_all(
                "Comment",
                filters={
                    "reference_doctype": "Member",
                    "reference_name": member.name,
                    "content": ["like", "%VOLUNTEER INTEREST APPLICATION DATA:%"],
                },
                fields=["content"],
                order_by="creation desc",
                limit=1,
            )
            if comments:
                # Extract text content from HTML
                import re

                content = comments[0].content
                # Remove HTML tags
                text_content = re.sub("<.*?>", "", content)
                volunteer_data = parse_volunteer_data_from_notes(text_content)

        # Create volunteer record
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "member": member.name,
                "volunteer_name": member.full_name,
                "email": member.email,
                "phone": member.contact_number or "",  # Handle missing phone
                "status": "Active",
                "start_date": frappe.utils.today(),
                "notes": f"Created from membership application. Original application date: {frappe.utils.format_datetime(member.application_date)}",
            }
        )

        volunteer.insert(ignore_permissions=True)

        # Add skills if parsed from application
        if volunteer_data and volunteer_data.get("skills_by_category"):
            add_skills_to_volunteer(volunteer, volunteer_data)

        # Add interests/areas if specified
        if volunteer_data and volunteer_data.get("volunteer_areas"):
            add_interest_areas_to_volunteer(volunteer, volunteer_data["volunteer_areas"])

        # Log success
        frappe.logger().info(f"Created volunteer record {volunteer.name} for approved member {member.name}")

        # Add comment to member record
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member.name,
                "content": f"Volunteer record created: <a href='/app/volunteer/{volunteer.name}'>{volunteer.name}</a>",
                "comment_by": frappe.session.user,
            }
        ).insert(ignore_permissions=True)

        return volunteer.name

    except Exception as e:
        frappe.log_error(f"Error creating volunteer from member {member.name}: {str(e)}")
        return None


def parse_volunteer_data_from_notes(notes):
    """Parse volunteer application data from member notes"""
    if not notes or "VOLUNTEER INTEREST APPLICATION DATA:" not in notes:
        return None

    try:
        # Extract volunteer section from notes
        volunteer_section = notes.split("VOLUNTEER INTEREST APPLICATION DATA:")[1]

        data = {
            "skills_by_category": {},
            "volunteer_areas": [],
            "availability": "",
            "experience_level": "",
            "skill_level": "",
        }

        lines = volunteer_section.split("\n")
        current_section = None

        for line in lines:
            line = line.strip()
            if not line or line == "==================================":
                continue

            if line.startswith("Availability:"):
                data["availability"] = line.replace("Availability:", "").strip()
            elif line.startswith("Experience Level:"):
                data["experience_level"] = line.replace("Experience Level:", "").strip()
            elif line.startswith("Overall Skill Level:"):
                data["skill_level"] = line.replace("Overall Skill Level:", "").strip()
            elif line.startswith("Areas of Interest:"):
                current_section = "areas"
            elif line.startswith("Skills Selected:"):
                current_section = "skills"
            elif current_section == "areas" and ":" not in line:
                if line != "None specified":
                    data["volunteer_areas"].extend([area.strip() for area in line.split(",")])
            elif current_section == "skills" and ":" in line and line != "None specified":
                # Stop processing skills when we hit other sections
                if line.startswith("Availability Details:") or line.startswith("Additional Comments:"):
                    current_section = None
                    continue

                category, skills = line.split(":", 1)
                category = category.strip()
                skills_text = skills.strip()

                # Only process if there are actual skills (not empty)
                if skills_text:
                    skills_list = [skill.strip() for skill in skills_text.split(",")]
                    data["skills_by_category"][category] = skills_list

        return data

    except Exception as e:
        frappe.log_error(f"Error parsing volunteer data from notes: {str(e)}")
        return None


def add_skills_to_volunteer(volunteer, volunteer_data):
    """Add skills to volunteer record from application data"""

    try:
        skills_by_category = volunteer_data.get("skills_by_category", {})
        skill_level = volunteer_data.get("skill_level", "3")

        for category, skills in skills_by_category.items():
            for skill_name in skills:
                skill_row = volunteer.append("skills_and_qualifications", {})
                skill_row.skill_category = category
                skill_row.volunteer_skill = skill_name
                skill_row.proficiency_level = f"{skill_level} - {get_proficiency_label(skill_level)}"
                skill_row.experience_years = 0  # Unknown from application
                skill_row.certifications = ""

        volunteer.save(ignore_permissions=True)
        skills_count = len([s for skills in skills_by_category.values() for s in skills])
        frappe.logger().info(f"Added {skills_count} skills to volunteer {volunteer.name}")

    except Exception as e:
        frappe.log_error(f"Error adding skills to volunteer {volunteer.name}: {str(e)}")


def add_interest_areas_to_volunteer(volunteer, areas):
    """Add interest areas to volunteer record"""

    try:
        # This would require the volunteer interest areas system to be set up
        # For now, just add to notes
        current_notes = volunteer.notes or ""
        areas_text = f"\nInterest Areas from Application: {', '.join(areas)}"
        volunteer.db_set("notes", current_notes + areas_text, update_modified=False)

        frappe.logger().info(f"Added interest areas to volunteer {volunteer.name}: {', '.join(areas)}")

    except Exception as e:
        frappe.log_error(f"Error adding interest areas to volunteer {volunteer.name}: {str(e)}")


def get_proficiency_label(level):
    """Get proficiency label from level number"""
    labels = {"1": "Beginner", "2": "Basic", "3": "Intermediate", "4": "Advanced", "5": "Expert"}
    return labels.get(str(level), "Intermediate")


# Debug function removed after successful testing
