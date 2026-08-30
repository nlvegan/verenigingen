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
from verenigingen.utils.validation_utilities import AgeValidator


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

        # Validate age against Verenigingen Settings.minimum_volunteer_age.
        #
        # This used to be a hardcoded `if age < 16`, so raising the association's
        # minimum changed the desk path and left the public form -- the one entry
        # point reachable without a login -- still accepting 16-year-olds (#659).
        # AgeValidator is the same gate volunteer.py and
        # bulk_volunteer_creation_service.py go through, so all three now answer
        # alike for the same applicant on the same day.
        #
        # Normalise the submitted date first. getdate() throws frappe.ValidationError
        # on an unparseable string, and that must not be mistaken for the
        # configuration error caught below -- both are frappe.ValidationError.
        try:
            birth_date = getdate(data.get("birth_date"))
        except frappe.ValidationError:
            birth_date = None
        if not birth_date:
            return OperationResult.fail(
                _("Please provide a valid birth date"), error_code="INVALID_BIRTH_DATE"
            )

        try:
            age_result = AgeValidator.validate_age(birth_date, context="volunteer", throw_on_error=False)
        except frappe.ValidationError:
            # _get_configurable_min_age throws when minimum_volunteer_age is
            # missing or <= 0; there is deliberately no hardcoded fallback. On a
            # guest endpoint an age gate must fail CLOSED -- one that silently
            # opens on a config error is worse than one that is temporarily shut.
            # The settings field name stays out of the response.
            frappe.log_error(
                "Verenigingen Settings.minimum_volunteer_age is not configured; the public "
                "volunteer application is refusing all submissions until it is set.",
                "Volunteer Application Age Config Error",
            )
            return OperationResult.fail(
                _("Volunteer applications are temporarily unavailable. Please contact us."),
                error_code="AGE_REQUIREMENT_NOT_CONFIGURED",
            )

        if not age_result.is_valid:
            return OperationResult.fail(
                age_result.message or _("You do not meet the minimum age to volunteer"),
                error_code="AGE_REQUIREMENT_NOT_MET",
            )

        # Check for existing volunteer with same email
        existing_volunteer = frappe.db.get_value(
            "Volunteer", {"email": data.get("email")}, ["name", "status"], as_dict=True
        )

        # An Inactive/Retired volunteer is allowed to re-apply: those are
        # terminal states, not pending/active profiles. Because Volunteer.email
        # is unique we must REUSE (reactivate) their existing record rather than
        # insert a duplicate (which would raise an IntegrityError).
        is_reactivation = False
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
            else:
                # Inactive / Retired -> reactivate the existing record in place.
                is_reactivation = True

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

        # Create (or reactivate) the volunteer record using a secure user context
        # (same pattern as the membership application).
        from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

        system_user = get_system_user_for_operation("volunteer_application_submission")

        if is_reactivation:
            volunteer_name = _reactivate_volunteer(existing_volunteer.name, data, member_link, system_user)
        else:
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

            volunteer_name = volunteer.name

        # If they also want membership, create member application
        membership_result = None
        if data.get("become_member") and not member_link:
            membership_result = _create_membership_application(data, volunteer_name)

        frappe.db.commit()

        # Log volunteer application for analytics
        action = "reactivated" if is_reactivation else "submitted"
        frappe.logger().info(f"Volunteer application {action}: {volunteer_name} - {data.get('email')}")

        # The volunteer record is always the primary outcome; the optional
        # membership sign-up is secondary. `member_name` reports the member
        # CREATED by this become_member request (None when linking to an existing
        # member or when no membership was requested). Surface a membership
        # failure to the applicant rather than silently reporting success.
        member_name = None
        membership_error = None
        if membership_result is not None:
            if membership_result["success"]:
                member_name = membership_result["member_name"]
            else:
                membership_error = membership_result["error"]

        result_data = {
            "application_id": volunteer_name,
            "volunteer_name": volunteer_name,
            "member_name": member_name,
        }

        if membership_error:
            result_data["membership_application_error"] = membership_error
            return OperationResult.ok(
                result_data,
                message=_(
                    "Your volunteer application was received, but your membership sign-up could "
                    "not be completed: {0}"
                ).format(membership_error),
            )

        success_message = (
            _("Welcome back! Your volunteer application has been received")
            if is_reactivation
            else _("Volunteer application submitted successfully")
        )
        return OperationResult.ok(result_data, message=success_message)

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


def _reactivate_volunteer(volunteer_name, data, member_link, system_user):
    """Reactivate a dormant (Inactive/Retired) volunteer in place.

    Volunteer.email is unique, so a returning volunteer must reuse their
    existing record rather than insert a duplicate. The application-derived
    fields are refreshed from the new submission and the volunteer is put back
    at the START of the onboarding pipeline (status "New"): a guest
    re-application must never self-activate to "Active". Earned profile fields
    (experience_level, preferred_work_style) are intentionally preserved.

    Returns the existing volunteer's name.
    """
    from verenigingen.utils.secure_operations import secure_user_context

    with secure_user_context(
        system_user, f"Reactivate dormant volunteer {volunteer_name} from public application form"
    ):
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        volunteer.volunteer_name = f"{data.get('first_name')} {data.get('last_name')}"
        volunteer.status = "New"  # Re-enter onboarding; guest input must not self-activate
        volunteer.start_date = today()
        volunteer.note = _build_volunteer_notes(data)
        volunteer.commitment_level = _map_time_commitment(data.get("time_commitment"))
        if member_link:
            volunteer.member = member_link

        # Refresh interests from the new application rather than appending to
        # stale rows, so a re-application cannot accumulate duplicate interests.
        volunteer.interests = []
        volunteer.save()

        # Re-add the interest areas selected on this application.
        _add_interest_areas(volunteer_name, data)

    return volunteer_name


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
            # Check if interest area category exists, create if not.
            # The category's name field is `category_name` (its autoname source),
            # not `interest_category`.
            if not frappe.db.exists("Volunteer Interest Category", interest_name):
                category = frappe.get_doc(
                    {"doctype": "Volunteer Interest Category", "category_name": interest_name}
                )
                category.insert()

            # Add interest area to volunteer. The child link field is `interest_area`
            # (a Link to Volunteer Interest Category), not `interest_category`.
            volunteer_doc.append("interests", {"interest_area": interest_name})

    # Save volunteer with all interest areas added
    if len(volunteer_doc.interests) > 0:
        volunteer_doc.save()


def _create_membership_application(data, volunteer_name):
    """Create a membership application for a volunteer who also wants to join.

    Returns a dict ``{"success": bool, "member_name": str|None, "error": str|None}``.
    The membership outcome is SURFACED to the caller, not swallowed: if the
    membership sign-up fails, the volunteer record is still created, but the
    applicant is told their membership needs attention (see the caller).
    """
    try:
        from verenigingen.api.membership_application import submit_application

        # Pass the real address fields through. The volunteer form collects a
        # full address; do NOT substitute placeholder defaults (a junk postal
        # code like "0000AA" fails Dutch validation), so a genuinely missing
        # address surfaces as an honest validation error instead of silently
        # discarding the membership request.
        application_data = {
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "email": data.get("email"),
            "birth_date": data.get("birth_date"),
            "contact_number": data.get("contact_number", ""),
            "interested_in_volunteering": 1,
            "application_source": "Volunteer Application Form (also requested membership)",
            "address_line1": data.get("address_line1"),
            "city": data.get("city"),
            "postal_code": data.get("postal_code"),
            "country": data.get("country", "Netherlands"),
        }

        # submit_application is a decorated endpoint, so it returns a serialized
        # dict ({"success", "data", "error"}), not an OperationResult.
        result = submit_application(**application_data)
        if not isinstance(result, dict) and hasattr(result, "to_dict"):
            result = result.to_dict()

        if result.get("success"):
            # The membership endpoint returns the new member under data.member_record
            member_name = (result.get("data") or {}).get("member_record")

            if member_name:
                from verenigingen.utils.secure_operations import (
                    get_system_user_for_operation,
                    secure_user_context,
                )

                system_user = get_system_user_for_operation("volunteer_application_submission")

                with secure_user_context(
                    system_user, f"Link volunteer {volunteer_name} to member {member_name}"
                ):
                    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
                    volunteer_doc.member = member_name
                    volunteer_doc.save()

                frappe.logger().info(
                    f"Created membership application {member_name} linked to volunteer {volunteer_name}"
                )
            return {"success": True, "member_name": member_name, "error": None}

        # Surface the real failure reason instead of swallowing it.
        error_message = (result.get("error") or {}).get("message") or _(
            "Membership application could not be created"
        )
        frappe.logger().error(
            f"Membership application failed for volunteer {volunteer_name}: {error_message}"
        )
        return {"success": False, "member_name": None, "error": error_message}

    except Exception as e:
        frappe.logger().error(f"Error creating membership for volunteer {volunteer_name}: {str(e)}")
        return {"success": False, "member_name": None, "error": str(e)}


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
