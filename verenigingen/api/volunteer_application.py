"""
Volunteer Application API
Handles submissions from the volunteer application form
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, public_api


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def submit_volunteer_application(**data) -> OperationResult[Dict[str, Any]]:
    """
    Handle volunteer application submission.

    This creates a Volunteer record directly (with optional Member record if they want membership).

    Args:
        **data: Form data from volunteer application

    Returns:
        OperationResult[Dict[str, Any]]: Success status and volunteer details
    """
    try:
        # Validate required fields
        required_fields = ["first_name", "last_name", "email", "birth_date", "motivation"]
        missing_fields = [field for field in required_fields if not data.get(field)]

        if missing_fields:
            return OperationResult.fail(
                _("Missing required fields: {0}").format(", ".join(missing_fields)),
                error_code="MISSING_REQUIRED_FIELDS",
            )

        # Validate age (must be at least 16)
        birth_date = getdate(data.get("birth_date"))
        age = (getdate(today()) - birth_date).days / 365.25

        if age < 16:
            return OperationResult.fail(
                _("You must be at least 16 years old to volunteer"), error_code="AGE_REQUIREMENT_NOT_MET"
            )

        # Check for existing volunteer with same email
        existing_volunteer = frappe.db.get_value(
            "Volunteer", {"email": data.get("email")}, ["name", "status"], as_dict=True
        )

        if existing_volunteer:
            if existing_volunteer.status in ["Active", "Onboarding"]:
                return OperationResult.fail(
                    _("You already have an active volunteer profile. Please log in to access your account."),
                    error_code="VOLUNTEER_ALREADY_EXISTS",
                )
            elif existing_volunteer.status == "New":
                return OperationResult.fail(
                    _("We already have your volunteer application. We'll contact you soon!"),
                    error_code="APPLICATION_ALREADY_SUBMITTED",
                )

        # Check if they're already a member (link volunteer to existing member)
        member_link = None
        if data.get("become_member") or frappe.session.user != "Guest":
            # Check for existing member by email or current user
            filters = {"email": data.get("email")}
            if frappe.session.user != "Guest":
                filters = {"user": frappe.session.user}

            existing_member = frappe.db.get_value("Member", filters, "name")
            if existing_member:
                member_link = existing_member

        # Create volunteer record using secure user context (same pattern as membership application)
        from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

        system_user = get_system_user_for_operation("volunteer_application_submission")

        with secure_user_context(system_user, "Create volunteer record from public application form"):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"{data.get('first_name')} {data.get('last_name')}",
                    "email": data.get("email"),
                    "member": member_link,  # Link to member if exists
                    "status": "New",  # Start as "New" - will be activated during onboarding
                    "start_date": today(),
                    "note": _build_volunteer_notes(data),
                    # Map commitment level from time_commitment
                    "commitment_level": _map_time_commitment(data.get("time_commitment")),
                    "experience_level": "Beginner",  # Default for new volunteers
                    "preferred_work_style": "Hybrid",  # Default
                }
            )

            volunteer.insert()

            # Add interest areas if selected
            _add_interest_areas(volunteer.name, data)

        # If they also want membership, create member application
        member_name = None
        if data.get("become_member") and not member_link:
            member_name = _create_membership_application(data, volunteer.name)

        frappe.db.commit()

        # Log volunteer application for analytics
        frappe.logger().info(f"Volunteer application submitted: {volunteer.name} - {data.get('email')}")

        return OperationResult.ok(
            {
                "application_id": volunteer.name,
                "volunteer_name": volunteer.name,
                "member_name": member_name,
            },
            message=_("Volunteer application submitted successfully"),
        )

    except Exception as e:
        frappe.db.rollback()
        error_msg = _("An error occurred while processing your application")
        frappe.log_error(
            f"Volunteer application submission error: {str(e)}\n{traceback.format_exc()}",
            "Volunteer Application Error",
        )
        return OperationResult.fail(
            error_msg, error_code="APPLICATION_SUBMISSION_ERROR", technical_details=str(e)
        )


def _map_time_commitment(time_commitment_str):
    """Map time commitment string to Volunteer commitment level."""
    if not time_commitment_str:
        return "Occasional"

    mapping = {
        "1-5": "Occasional",
        "6-10": "Regular (Monthly)",
        "11-20": "Weekly",
        "20+": "Intensive",
        "flexible": "Occasional",
    }

    return mapping.get(time_commitment_str, "Occasional")


def _add_interest_areas(volunteer_name, data):
    """Add interest areas to volunteer record (called within secure_user_context)."""
    interest_mapping = {
        "interest_events": "Event Organization",
        "interest_communications": "Communications & Marketing",
        "interest_fundraising": "Fundraising",
        "interest_admin": "Administrative Support",
        "interest_outreach": "Community Outreach",
        "interest_tech": "Technical & IT",
    }

    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

    for field, interest_name in interest_mapping.items():
        if data.get(field):
            # Check if interest area category exists, create if not
            if not frappe.db.exists("Volunteer Interest Category", interest_name):
                category = frappe.get_doc(
                    {"doctype": "Volunteer Interest Category", "interest_category": interest_name}
                )
                category.insert()

            # Add interest area to volunteer
            volunteer_doc.append("interests", {"interest_category": interest_name})

    # Save volunteer with all interest areas added
    if len(volunteer_doc.interests) > 0:
        volunteer_doc.save()


def _create_membership_application(data, volunteer_name):
    """Create membership application if volunteer also wants to become a member."""
    try:
        from verenigingen.api.membership_application import submit_application

        # Build minimal required application data for membership
        application_data = {
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "email": data.get("email"),
            "birth_date": data.get("birth_date"),
            "contact_number": data.get("contact_number", ""),
            "interested_in_volunteering": 1,
            "application_source": "Volunteer Application Form (also requested membership)",
            # Add minimal required address fields
            "address_line1": data.get("address_line1", "To be provided"),
            "city": data.get("city", "To be provided"),
            "postal_code": data.get("postal_code", "0000AA"),
            "country": data.get("country", "Netherlands"),
        }

        result = submit_application(**application_data)

        if result.get("success"):
            # Link the volunteer to the new member
            member_name = result.get("member_name")

            from verenigingen.utils.secure_operations import (
                get_system_user_for_operation,
                secure_user_context,
            )

            system_user = get_system_user_for_operation("volunteer_application_submission")

            with secure_user_context(system_user, f"Link volunteer {volunteer_name} to member {member_name}"):
                volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
                volunteer_doc.member = member_name
                volunteer_doc.save()

            frappe.logger().info(
                f"Created membership application {member_name} linked to volunteer {volunteer_name}"
            )
            return member_name

    except Exception as e:
        # Just log the error, don't fail the volunteer application
        frappe.logger().error(f"Error creating membership for volunteer {volunteer_name}: {str(e)}")
    return None


def _build_volunteer_notes(data):
    """
    Build formatted notes from volunteer application data.

    Args:
        data: Application form data

    Returns:
        str: Formatted notes for volunteer record
    """
    notes = []

    # Header
    notes.append("=== VOLUNTEER APPLICATION ===")
    notes.append(f"Submitted: {now_datetime()}")
    notes.append(f"Contact: {data.get('contact_number', 'Not provided')}")
    notes.append("")

    # Motivation
    if data.get("motivation"):
        notes.append("WHY VOLUNTEER:")
        notes.append(data.get("motivation"))
        notes.append("")

    # Interests
    if data.get("interests"):
        notes.append("INTERESTS & PASSIONS:")
        notes.append(data.get("interests"))
        notes.append("")

    # Previous experience
    if data.get("previous_experience"):
        notes.append("PREVIOUS VOLUNTEER EXPERIENCE:")
        notes.append(data.get("previous_experience"))
        notes.append("")

    # Skills
    if data.get("skills_description"):
        notes.append("SKILLS & TALENTS:")
        notes.append(data.get("skills_description"))
        notes.append("")

    # Time commitment and availability
    if data.get("time_commitment"):
        notes.append(f"TIME COMMITMENT: {data.get('time_commitment')} hours per month")

    if data.get("availability"):
        notes.append(f"AVAILABILITY: {data.get('availability')}")
        notes.append("")

    # Referral source
    if data.get("referral_source"):
        notes.append(f"HOW THEY HEARD ABOUT US: {data.get('referral_source')}")
        notes.append("")

    # Additional comments
    if data.get("additional_comments"):
        notes.append("ADDITIONAL COMMENTS:")
        notes.append(data.get("additional_comments"))
        notes.append("")

    # Membership interest
    if data.get("become_member"):
        notes.append("ℹ️ Also interested in becoming a member")

    return "\n".join(notes)
