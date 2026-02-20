"""
Helper utilities for membership application processing
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.utils.dutch_name_utils import format_dutch_full_name, is_dutch_installation


def safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


# Import moved inside function to avoid circular imports


def get_creation_user():
    """
    DEPRECATED: Import from secure_operations instead

    For new code use:
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    This function now properly references Verenigingen Settings creation_user
    to maintain consistency with the secure operations framework.
    """
    # Use the same logic as secure_operations for consistency
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    return get_system_user_for_operation("legacy_get_creation_user_call")


def save_with_system_context(doc, context_description="system operation"):
    """
    DEPRECATED: Use secure_user_context context manager for new code

    Legacy compatibility function for existing code.
    For new code, use:

    from verenigingen.utils.secure_operations import secure_user_context

    with secure_user_context(get_creation_user(), context_description) as ctx:
        doc.save()
        ctx.log_operation(doc.doctype, doc.name)
    """
    from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

    with secure_user_context(
        get_system_user_for_operation("save_with_system_context"), context_description
    ) as ctx:
        doc.save()
        ctx.log_operation(doc.doctype, doc.name)


def validate_payment_method_exists(mode_of_payment: str) -> bool:
    """
    Check if a Mode of Payment exists in the database.

    Args:
        mode_of_payment: The name of the Mode of Payment to check

    Returns:
        True if exists, False otherwise
    """
    return bool(frappe.db.exists("Mode of Payment", mode_of_payment))


def get_missing_payment_modes() -> list:
    """
    Check which required payment modes are missing from the database.

    Returns:
        List of missing payment mode names
    """
    required_modes = ["Bank Transfer", "SEPA Direct Debit", "Mollie"]
    missing = []
    for mode in required_modes:
        if not frappe.db.exists("Mode of Payment", mode):
            missing.append(mode)
    return missing


def ensure_payment_modes_exist():
    """
    Ensure required payment modes exist. Creates them if missing.

    This is a recovery function that can be called to fix missing payment modes
    without requiring a full reinstall.
    """
    payment_modes = [
        {"mode_of_payment": "Bank Transfer", "type": "Bank"},
        {"mode_of_payment": "SEPA Direct Debit", "type": "Bank"},
        {"mode_of_payment": "Mollie", "type": "General"},
        {"mode_of_payment": "Cash", "type": "Cash"},
    ]

    created = []
    for pm_data in payment_modes:
        name = pm_data["mode_of_payment"]
        if not frappe.db.exists("Mode of Payment", name):
            try:
                # Security: System setup helper - creates standard payment modes for app operation
                doc = frappe.get_doc({"doctype": "Mode of Payment", **pm_data})
                doc.insert(ignore_permissions=True)
                created.append(name)
            except Exception as e:
                frappe.log_error(
                    f"Failed to create Mode of Payment '{name}': {str(e)}", "Payment Mode Creation Error"
                )

    if created:
        frappe.db.commit()

    return created


def map_payment_method(payment_method, validate: bool = True):
    """
    Map form payment method values to Member doctype values.

    Args:
        payment_method: The payment method value from the form (e.g., 'bank_transfer')
        validate: If True, validates that the mapped Mode of Payment exists

    Returns:
        The mapped Mode of Payment name (e.g., 'Bank Transfer')

    Raises:
        frappe.ValidationError: If validate=True and the Mode of Payment doesn't exist
    """
    payment_method_map = {
        "bank_transfer": "Bank Transfer",
        "sepa_direct_debit": "SEPA Direct Debit",
        "credit_card": "Credit Card",
        "cash": "Cash",
        "other": "Other",
        "mollie": "Mollie",
        # Also handle case where we receive the display values directly
        "Bank Transfer": "Bank Transfer",
        "SEPA Direct Debit": "SEPA Direct Debit",
        "Credit Card": "Credit Card",
        "Cash": "Cash",
        "Other": "Other",
        "Mollie": "Mollie",
    }
    # Default to Bank Transfer if no match found
    mapped_value = payment_method_map.get(payment_method, "Bank Transfer")

    if validate and not validate_payment_method_exists(mapped_value):
        # Check what modes are missing and provide helpful error message
        missing_modes = get_missing_payment_modes()

        # Machine-friendly error code for automated deployments
        error_code = "PAYMENT_MODE_NOT_CONFIGURED"
        error_data = {
            "error_code": error_code,
            "missing_payment_mode": mapped_value,
            "all_missing_modes": missing_modes,
            "recovery_command": (
                "bench --site <site> execute "
                '"verenigingen.utils.application_helpers.ensure_payment_modes_exist"'
            ),
        }

        # User-friendly error message
        error_msg = _("Payment method '{0}' is not configured in this system. ").format(mapped_value)

        if missing_modes:
            error_msg += _(
                "Missing payment modes: {0}. "
                "Please run 'bench --site <site> execute "
                '"verenigingen.utils.application_helpers.ensure_payment_modes_exist"\' '
                "or contact your system administrator."
            ).format(", ".join(missing_modes))
        else:
            error_msg += _(
                "Please create '{0}' in Setup > Mode of Payment, " "or contact your system administrator."
            ).format(mapped_value)

        # Log structured error for monitoring/alerting systems
        frappe.log_error(
            f"[{error_code}] {error_msg}\nError data: {error_data}", "Payment Mode Configuration Error"
        )

        # Throw with both human-readable message and machine-readable error code
        frappe.throw(
            error_msg,
            title=_("Payment Method Not Found"),
            exc=frappe.ValidationError,
        )
        # Note: The error_code can be found in the error log for automated detection

    return mapped_value


def generate_application_id():
    """Generate unique application ID — delegates to canonical implementation."""
    from verenigingen.services.member.core.member_id_service import (
        generate_application_id as _canonical,
    )

    return _canonical()


def parse_application_data(data_input):
    """Parse and validate incoming application data"""
    if data_input is None:
        raise ValueError("No data provided")

    if isinstance(data_input, str):
        try:
            # Decode HTML entities (handles cases where JSON gets HTML encoded)
            import html

            decoded_data = html.unescape(data_input).strip()

            # Structural validation only (no PII in logs)
            if decoded_data and decoded_data.count("{") != decoded_data.count("}"):
                frappe.logger("verenigingen.application").error(
                    f"Unbalanced braces in application data (length={len(decoded_data)}): "
                    f"opening={decoded_data.count('{')}, closing={decoded_data.count('}')}"
                )

            data = json.loads(decoded_data)
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON format: {str(e)}"
            error_data = locals().get("decoded_data", data_input)
            if len(error_data) > 0:
                start = max(0, e.pos - 20) if hasattr(e, "pos") else 0
                end = min(len(error_data), start + 40)
                problematic_section = error_data[start:end]
                error_msg += f" | Near position {e.pos}"

            frappe.logger("verenigingen.application").error(f"JSON parsing failed: {error_msg}")
            raise ValueError(error_msg)
    else:
        data = data_input

    return data


def get_form_data():
    """Get data needed for application form"""
    try:
        # Get enhanced membership types with contribution options in one bulk operation
        membership_types = []
        try:
            from verenigingen.templates.pages.membership_application import (
                get_membership_types_with_contributions,
            )

            membership_types = get_membership_types_with_contributions()
        except Exception as e:
            # Fallback to basic membership types if enhanced version fails
            frappe.log_error(f"Error getting enhanced membership types, falling back to basic: {str(e)}")
            try:
                membership_types = frappe.get_all(
                    "Membership Type",
                    filters={"is_active": 1},
                    fields=[
                        "name",
                        "membership_type_name",
                        "description",
                        "minimum_amount",
                        "dues_schedule_template",
                    ],
                    order_by="minimum_amount",
                )
                # Enrich with billing_frequency from linked template
                for mt in membership_types:
                    mt["billing_frequency"] = "Annual"  # Default
                    if mt.get("dues_schedule_template"):
                        template_frequency = frappe.db.get_value(
                            "Membership Dues Schedule",
                            mt["dues_schedule_template"],
                            "billing_frequency",
                        )
                        if template_frequency:
                            mt["billing_frequency"] = template_frequency
            except Exception as fallback_e:
                frappe.log_error(f"Error getting basic membership types: {str(fallback_e)}")
                membership_types = []

        # Get countries - use a fallback list
        countries = [
            {"name": "Netherlands"},
            {"name": "Germany"},
            {"name": "Belgium"},
            {"name": "France"},
            {"name": "United Kingdom"},
            {"name": "Other"},
        ]

        # Try to get from database, fallback to hardcoded
        try:
            db_countries = frappe.get_all("Country", fields=["name"], order_by="name")
            if db_countries:
                countries = db_countries
        except Exception as e:
            frappe.log_error(f"Error getting countries: {str(e)}")
            pass  # Use fallback countries

        # Get chapters - always load for application form
        chapters = []
        try:
            chapters = frappe.get_all(
                "Chapter", filters={"published": 1}, fields=["name", "region"], order_by="name"
            )
        except Exception as e:
            frappe.log_error(f"Error getting chapters: {str(e)}")
            pass  # Chapter loading failed

        # Get volunteer areas - with error handling
        volunteer_areas = []
        try:
            volunteer_areas = frappe.get_all(
                "Volunteer Interest Category", fields=["name", "description"], order_by="name"
            )
        except Exception as e:
            frappe.log_error(f"Error getting volunteer areas: {str(e)}")
            pass  # Table might not exist

        return {
            "success": True,
            "membership_types": membership_types,
            "chapters": chapters,
            "volunteer_areas": volunteer_areas,
            "countries": countries,
        }

    except Exception as e:
        frappe.log_error(f"Error in get_form_data: {str(e)}")
        return {"success": False, "error": str(e), "message": "Error loading form data"}


def determine_chapter_from_application(data):
    """Determine suggested chapter from application data"""
    suggested_chapter = None

    if data.get("selected_chapter"):
        suggested_chapter = data.get("selected_chapter")
    elif data.get("postal_code"):
        # Use existing chapter suggestion logic
        try:
            # Import only when needed to avoid circular imports
            from verenigingen.verenigingen.doctype.chapter.chapter import suggest_chapter_for_member

            suggestion_result = suggest_chapter_for_member(
                None, data.get("postal_code"), data.get("state"), data.get("city")
            )
            # The function now returns a list directly, not a dict with matches_by_postal
            if suggestion_result and isinstance(suggestion_result, list) and len(suggestion_result) > 0:
                suggested_chapter = suggestion_result[0]["name"]
            elif isinstance(suggestion_result, dict) and suggestion_result.get("matches_by_postal"):
                # Fallback for old format
                suggested_chapter = suggestion_result["matches_by_postal"][0]["name"]
        except ImportError as e:
            frappe.log_error(f"Could not import chapter module: {str(e)}", "Chapter Import Error")
        except Exception as e:
            frappe.log_error(f"Error suggesting chapter: {str(e)}", "Chapter Suggestion Error")

    return suggested_chapter


def create_address_from_application(data):
    """Create address record from application data"""
    if not (data.get("address_line1") and data.get("city")):
        return None

    # Import here to avoid circular imports
    from verenigingen.utils.validation.application_validators import validate_name

    # Sanitize names for address title
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")

    if first_name:
        validation_result = validate_name(first_name, "First Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            first_name = validation_result["sanitized"]

    if last_name:
        validation_result = validate_name(last_name, "Last Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            last_name = validation_result["sanitized"]

    # Use secure operations framework for address creation during application processing
    from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

    system_user = get_system_user_for_operation("address_creation_during_member_application")
    with secure_user_context(
        system_user, f"Address creation for member application {data.get('email', 'unknown')}"
    ):
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"{first_name} {last_name}",
                "address_type": "Personal",
                "address_line1": data.get("address_line1"),
                "address_line2": data.get("address_line2", ""),
                "city": data.get("city"),
                "state": data.get("state", ""),
                "country": data.get("country"),
                "pincode": data.get("postal_code"),
                "email_id": data.get("email"),
                "phone": data.get("phone", ""),
                "is_primary_address": 1,
            }
        )
        # Insert with proper permissions using secure operations framework
        address.insert()
        return address


def _sanitize_application_names(data):
    """
    Validate and sanitize name fields from application data.

    Returns tuple: (first_name, middle_name, tussenvoegsel, last_name)
    """
    from verenigingen.utils.validation.application_validators import validate_name

    names = {}
    for field, label in [
        ("first_name", "First Name"),
        ("middle_name", "Middle Name"),
        ("tussenvoegsel", "Tussenvoegsel"),
        ("last_name", "Last Name"),
    ]:
        value = data.get(field, "")
        if value:
            validation_result = validate_name(value, label)
            if validation_result.get("valid") and validation_result.get("sanitized"):
                value = validation_result["sanitized"]
        names[field] = value

    return names["first_name"], names["middle_name"], names["tussenvoegsel"], names["last_name"]


def _apply_custom_contribution_fee(member, data, context_label="application"):
    """
    Apply custom contribution fee override fields to a member.

    Args:
        member: Member document (modified in place)
        data: Application data dict with custom_contribution_fee, uses_custom_amount, custom_amount_reason
        context_label: Used in fee_override_reason (e.g. "application" or "reapplication")
    """
    if not (data.get("custom_contribution_fee") or data.get("uses_custom_amount")):
        return

    try:
        custom_contribution_fee = 0
        if data.get("custom_contribution_fee"):
            try:
                custom_contribution_fee = float(data.get("custom_contribution_fee"))
            except (ValueError, TypeError) as e:
                frappe.log_error(
                    f"Error converting custom_contribution_fee '{data.get('custom_contribution_fee')}' to float: {str(e)}",
                    "Custom Amount Conversion Error",
                )
                custom_contribution_fee = 0

        if custom_contribution_fee > 0:
            member.dues_rate = custom_contribution_fee
            member.fee_override_reason = (
                f"Custom amount selected during {context_label}: "
                f"{data.get('custom_amount_reason', 'Member-specified contribution level')}"
            )
            member.fee_override_date = today()
            member.application_custom_fee = custom_contribution_fee

            # Resolve fee_override_by user with safe fallback
            override_user = None
            if frappe.session.user and frappe.session.user != "Guest":
                if frappe.db.exists("User", frappe.session.user):
                    override_user = frappe.session.user
            if not override_user and frappe.db.exists("User", "Administrator"):
                override_user = "Administrator"
            if not override_user:
                first_user = frappe.db.get_value("User", {"enabled": 1}, "name")
                if first_user:
                    override_user = first_user

            if override_user:
                member.fee_override_by = override_user
            else:
                frappe.log_error(
                    "No valid user found for fee_override_by field - custom amount preserved without approver",
                    "Fee Override User Warning",
                )

    except Exception as e:
        frappe.log_error(
            f"Error storing custom amount data: {str(e)}",
            "Custom Amount Storage Error",
        )


def _append_chapter_notes(member, selected_chapter, label="Selected Chapter"):
    """
    Append chapter display info to member notes.

    Args:
        member: Member document (modified in place)
        selected_chapter: Chapter name/ID from application data
        label: Prefix label (e.g. "Selected Chapter" or "Selected Chapter (Reapplication)")
    """
    if not selected_chapter:
        return

    try:
        try:
            chapter_doc = frappe.get_doc("Chapter", selected_chapter)
            chapter_display = f"{chapter_doc.region} ({selected_chapter})"
        except Exception:
            chapter_display = selected_chapter

        from verenigingen.utils import append_to_text_field

        append_to_text_field(member, "notes", f"{label}: {chapter_display}")
    except Exception as e:
        frappe.log_error(
            f"Error storing chapter information: {str(e)}",
            "Chapter Info Storage Error",
        )


def create_member_from_application(data, application_id, address=None):
    """Create member record from application data"""
    # Import here to avoid circular imports
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    # Sanitize names before creating member record
    first_name, middle_name, tussenvoegsel, last_name = _sanitize_application_names(data)

    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": first_name,
            "middle_name": middle_name,
            "tussenvoegsel": tussenvoegsel,
            "last_name": last_name,
            "email": data.get("email"),
            "contact_number": data.get("contact_number", ""),
            "birth_date": data.get("birth_date"),
            "pronouns": data.get("pronouns", ""),
            "primary_address": address.name if address else None,
            "status": "Pending",
            # Application tracking fields
            "application_id": application_id,
            "application_status": "Pending",
            "application_date": now_datetime(),
            "selected_membership_type": data.get("selected_membership_type"),
            "application_dues_schedule": data.get("selected_dues_schedule"),
            "interested_in_volunteering": data.get("interested_in_volunteering", 0),
            "newsletter_opt_in": data.get("newsletter_opt_in", 1),
            # Convert opt-out preference to opt-in field (inverted logic)
            "accepts_optional_communications": 0 if data.get("opt_out_optional_emails") else 1,
            "application_source": data.get("application_source", "Website"),
            "notes": data.get("additional_notes", ""),
            "payment_method": map_payment_method(data.get("payment_method", "")),
            "current_chapter_display": data.get("selected_chapter", ""),
            # Bank details for bank transfer/direct debit
            "iban": data.get("iban", ""),
            "bic": data.get("bic", ""),
            "bank_account_name": data.get("bank_account_name", ""),
            # IMPORTANT: Set owner to the configured system user
            # This prevents the applicant from becoming the owner of the member record
            "owner": get_system_user_for_operation("member_record_owner_assignment"),
        }
    )

    # Store volunteer skills data as a temporary attribute for volunteer record creation
    volunteer_skills = data.get("volunteer_skills", [])
    if volunteer_skills:
        member.volunteer_skills = volunteer_skills

    # Handle custom membership amount using fee override fields
    _apply_custom_contribution_fee(member, data, context_label="application")

    # Add chapter information to notes for approver visibility
    _append_chapter_notes(member, data.get("selected_chapter"), label="Selected Chapter")

    # Suppress customer creation messages during application submission
    member._suppress_customer_messages = True

    # Use secure operations framework for member creation during application processing
    from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

    system_user = get_system_user_for_operation("member_creation_during_application")
    with secure_user_context(system_user, f"Member creation for application {application_id}"):
        # Handle potential application_id collision with retry logic
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Insert with proper permissions using secure operations framework
                member.insert()
                return member
            except Exception as e:
                # Check if this is an IntegrityError related to application_id
                error_str = str(e)
                if "Duplicate entry" in error_str and "application_id" in error_str:
                    if attempt < max_attempts - 1:  # Not the last attempt
                        # Generate new application_id and retry
                        new_app_id = generate_application_id()
                        member.application_id = new_app_id
                        frappe.log_error(
                            f"Application ID collision detected, retrying with new ID: {new_app_id} (attempt {attempt + 1})",
                            "Application ID Collision Retry",
                        )
                        continue
                    else:
                        # Last attempt failed, log and re-raise
                        frappe.log_error(
                            f"Failed to create member after {max_attempts} attempts due to application_id collision: {error_str}",
                            "Application ID Collision Fatal",
                        )
                        raise
                else:
                    # Not an application_id collision, re-raise immediately
                    raise


def update_member_from_reapplication(member_name, data, application_id, address=None):
    """
    Update existing member record from reapplication data.

    Used for:
    - Rejected applications reapplying
    - Pending applications being updated
    - Voluntary terminations rejoining
    """
    from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

    # Get existing member
    member = frappe.get_doc("Member", member_name)

    # Sanitize names before updating
    first_name, middle_name, tussenvoegsel, last_name = _sanitize_application_names(data)

    # Update member fields with new application data
    member.first_name = first_name
    member.middle_name = middle_name
    member.tussenvoegsel = tussenvoegsel
    member.last_name = last_name
    member.contact_number = data.get("contact_number", "")
    member.birth_date = data.get("birth_date")
    member.pronouns = data.get("pronouns", "")

    # Update address if provided
    if address:
        member.primary_address = address.name

    # Reset to pending status for reapplication
    member.status = "Pending"
    member.application_status = "Pending"
    member.application_date = now_datetime()
    member.application_id = application_id

    # Update application-specific fields
    member.selected_membership_type = data.get("selected_membership_type")
    member.interested_in_volunteering = data.get("interested_in_volunteering", 0)
    member.newsletter_opt_in = data.get("newsletter_opt_in", 1)
    # Convert opt-out preference to opt-in field (inverted logic)
    member.accepts_optional_communications = 0 if data.get("opt_out_optional_emails") else 1
    member.application_source = data.get("application_source", "Website")
    member.payment_method = map_payment_method(data.get("payment_method", ""))
    member.current_chapter_display = data.get("selected_chapter", "")

    # Update bank details
    member.iban = data.get("iban", "")
    member.bic = data.get("bic", "")
    member.bank_account_name = data.get("bank_account_name", "")

    # Transfer volunteer skills (consistency with new applications)
    volunteer_skills = data.get("volunteer_skills", [])
    if volunteer_skills:
        member.volunteer_skills = volunteer_skills

    # Add chapter information to notes for approver visibility
    _append_chapter_notes(member, data.get("selected_chapter"), label="Selected Chapter (Reapplication)")

    # Add reapplication timestamp note
    from verenigingen.utils import append_to_text_field

    reapp_note = f"Reapplication submitted: {now_datetime()}"
    append_to_text_field(member, "notes", reapp_note, separator="\n")

    # Suppress customer creation messages during reapplication processing
    member._suppress_customer_messages = True

    # Handle custom membership amount
    _apply_custom_contribution_fee(member, data, context_label="reapplication")

    # Save with proper permissions
    system_user = get_system_user_for_operation("member_reapplication_update")
    with secure_user_context(system_user, f"Update member {member_name} from reapplication {application_id}"):
        member.save()

    return member


def create_volunteer_record(member):
    """Create volunteer record if member is interested - relinks existing volunteer if found.

    Uses the centralized volunteer creation service from volunteer.py for new volunteers.
    Handles reapplication case (existing volunteer) separately.
    """
    if not member.interested_in_volunteering:
        return None

    try:
        from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

        # Check if a volunteer linked to this member already exists (handles reapplication case)
        existing_volunteer = frappe.db.get_value("Volunteer", {"member": member.name}, "name")

        if existing_volunteer:
            # Relink existing volunteer to new member record
            frappe.logger().info(
                f"Found existing volunteer {existing_volunteer} linked to member {member.name}, updating"
            )
            volunteer = frappe.get_doc("Volunteer", existing_volunteer)
            volunteer.member = member.name
            volunteer.volunteer_name = member.full_name or f"{member.first_name} {member.last_name}".strip()
            # Reset to New status for reapplication
            volunteer.status = "New"

            system_user = get_system_user_for_operation("volunteer_creation_during_application")
            with secure_user_context(system_user, f"Volunteer relink for member {member.name}"):
                volunteer.save()

                # Also update member's volunteer_record field if it exists
                if hasattr(member, "volunteer_record"):
                    member.volunteer_record = volunteer.name
                    member.save()

            frappe.logger().info(
                f"Successfully relinked volunteer {existing_volunteer} to member {member.name}"
            )
            return volunteer

        # No existing volunteer - use the centralized volunteer creation service
        from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member

        # Get volunteer skills from member if available
        volunteer_skills = getattr(member, "volunteer_skills", None)

        system_user = get_system_user_for_operation("volunteer_creation_during_application")
        with secure_user_context(system_user, f"Volunteer creation for member {member.name}"):
            result = create_volunteer_from_member(
                member_name=member.name,
                status="New",
                interested_skills=volunteer_skills,
                create_user_account=False,
            )

            if result and result.get("success"):
                volunteer_name = result.get("volunteer_name")
                volunteer = frappe.get_doc("Volunteer", volunteer_name)

                # Update member's volunteer_record field if it exists
                if hasattr(member, "volunteer_record"):
                    member.volunteer_record = volunteer_name
                    member.save()

                frappe.logger().info(
                    f"Successfully created volunteer {volunteer_name} for member {member.name}"
                )
                return volunteer
            else:
                error_msg = result.get("error", "Unknown error") if result else "No result returned"
                frappe.logger().error(f"Failed to create volunteer for member {member.name}: {error_msg}")
                return None

    except Exception as e:
        safe_log_error(f"Error creating volunteer record: {str(e)}")
        return None


def get_membership_type_fee_info(membership_type):
    """Canonical source of truth for membership type fee information.

    Loads the membership type and its dues schedule template, resolves the
    base amount, currency, and billing frequency, and computes suggested
    contribution tiers. All fee query endpoints delegate to this function.

    Args:
        membership_type: Name of the Membership Type document.

    Returns:
        dict with keys:
            success (bool), membership_type (str), membership_type_name (str),
            description (str), amount (float), currency (str),
            billing_frequency (str), minimum_amount (float),
            maximum_amount (float), suggested_amounts (list[dict]),
            allow_custom_amount (bool), has_template (bool),
            raw_suggested_amount (float|None), template_name (str|None)
    """
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Resolve amount from dues schedule template
        amount = 0
        billing_frequency = "Annual"
        raw_suggested_amount = None  # Preserved for strict validation in suggest_membership_amounts
        template_name = None

        template = load_template_for_membership_type(membership_type_doc, required=False)
        has_template = template is not None

        if template:
            amount = template.dues_rate or template.suggested_amount or 0
            billing_frequency = template.billing_frequency or "Annual"
            raw_suggested_amount = template.suggested_amount
            template_name = template.name

        # Fallback to minimum_amount if template has no amount
        if not amount:
            amount = membership_type_doc.minimum_amount or 0

        amount = float(amount)
        currency = _get_membership_type_currency(membership_type_doc)

        # Compute suggested contribution tiers
        suggested_amounts = []
        if amount > 0:
            for multiplier, label, description in [
                (1.0, _("Standard"), _("Standard membership fee")),
                (1.25, _("Supporter"), _("Support our mission with 25% extra")),
                (1.5, _("Advocate"), _("Help us grow with 50% extra")),
                (2.0, _("Champion"), _("Be a champion with 100% extra")),
            ]:
                tier_amount = amount * multiplier
                suggested_amounts.append(
                    {
                        "amount": tier_amount,
                        "label": label,
                        "description": description,
                        "percentage": int(multiplier * 100),
                        "is_default": multiplier == 1.0,
                        "formatted_amount": frappe.utils.fmt_money(tier_amount, currency=currency),
                    }
                )

        return {
            "success": True,
            "membership_type": membership_type_doc.name,
            "membership_type_name": getattr(
                membership_type_doc, "membership_type_name", membership_type_doc.name
            ),
            "description": membership_type_doc.description,
            "amount": amount,
            "currency": currency,
            "billing_frequency": billing_frequency,
            "minimum_amount": float(membership_type_doc.minimum_amount or 0),
            "maximum_amount": amount * 5 if amount > 0 else 0,
            "suggested_amounts": suggested_amounts,
            "allow_custom_amount": True,
            "has_template": has_template,
            "raw_suggested_amount": raw_suggested_amount,
            "template_name": template_name,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Error retrieving membership type fee information",
        }


def get_membership_fee_info(membership_type):
    """Get membership fee information.

    Thin wrapper around get_membership_type_fee_info() that returns only
    the fields needed by the fee info endpoint.
    """
    info = get_membership_type_fee_info(membership_type)
    if not info.get("success"):
        return info
    return {
        "success": True,
        "membership_type": info["membership_type"],
        "standard_amount": info["amount"],
        "currency": info["currency"],
        "description": info["description"],
        "billing_frequency": info["billing_frequency"],
    }


def get_membership_type_details(membership_type):
    """Get detailed membership type information.

    Thin wrapper around get_membership_type_fee_info() that adds the
    legacy suggested_amounts format with Supporter/Patron/Benefactor tiers
    and min/max bounds.
    """
    info = get_membership_type_fee_info(membership_type)
    if not info.get("success"):
        return info

    amount = info["amount"]

    # Legacy tier format: Standard/Supporter/Patron/Benefactor at 1x/1.5x/2x/3x
    legacy_tiers = []
    if amount > 0:
        for multiplier, label, desc in [
            (1.0, "Standard", "Standard membership fee"),
            (1.5, "Supporter", f"Support our mission with {int((1.5 - 1) * 100)}% extra"),
            (2.0, "Patron", f"Support our mission with {int((2.0 - 1) * 100)}% extra"),
            (3.0, "Benefactor", f"Support our mission with {int((3.0 - 1) * 100)}% extra"),
        ]:
            legacy_tiers.append(
                {
                    "amount": amount * multiplier,
                    "label": label,
                    "description": desc,
                }
            )

    return {
        "success": True,
        "name": info["membership_type"],
        "membership_type_name": info["membership_type_name"],
        "description": info["description"],
        "amount": amount,
        "currency": info["currency"],
        "billing_frequency": info["billing_frequency"],
        "allow_custom_amount": True,
        "minimum_amount": info["minimum_amount"] * 0.5,  # 50% of constraint floor
        "maximum_amount": info["maximum_amount"],
        "custom_amount_note": "You can adjust your contribution amount. Minimum is 50% of standard fee.",
        "suggested_amounts": legacy_tiers,
    }


def get_amount_impact_message(selected_amount, standard_amount, percentage):
    """Get message about amount impact"""
    if percentage > 100:
        extra_percentage = percentage - 100
        return f"Your {extra_percentage}% contribution helps fund additional programs and services."
    elif percentage < 100:
        reduction_percentage = 100 - percentage
        return f"Reduced rate ({reduction_percentage}% discount) - thank you for joining us!"
    else:
        return "Standard membership fee."


def suggest_membership_amounts(membership_type_name):
    """Suggest membership amounts based on type.

    Uses get_membership_type_fee_info() for base data, then adds strict
    validation and formatted suggestion tiers.

    Note: This function intentionally uses suggested_amount (not dues_rate)
    as its base amount, matching the original behavior where tiers are based
    on the suggested contribution amount, not the billing rate.
    """
    try:
        info = get_membership_type_fee_info(membership_type_name)
        if not info.get("success"):
            return info

        if not info.get("has_template"):
            frappe.throw(f"Membership Type '{membership_type_name}' must have a dues schedule template")

        # Strict validation on raw suggested_amount (preserved from original)
        raw_suggested_amount = info.get("raw_suggested_amount")
        template_name = info.get("template_name", membership_type_name)

        if raw_suggested_amount is None:
            frappe.throw(f"Dues Schedule Template '{template_name}' must have a suggested_amount configured")

        if raw_suggested_amount < 0:
            frappe.throw(
                f"Dues Schedule Template '{template_name}' cannot have negative "
                f"suggested_amount: {raw_suggested_amount}"
            )

        # Allow zero amounts only if the membership type minimum is also zero
        if raw_suggested_amount == 0:
            membership_type_minimum = getattr(
                frappe.get_doc("Membership Type", membership_type_name), "minimum_amount", None
            )
            if membership_type_minimum is None or membership_type_minimum > 0:
                frappe.throw(
                    f"Dues Schedule Template '{template_name}' has zero suggested_amount but "
                    f"Membership Type '{membership_type_name}' minimum_amount is "
                    f"{membership_type_minimum}. For free memberships, both must be zero."
                )

        # Use suggested_amount as base (not dues_rate) for tier calculation
        base_amount = float(raw_suggested_amount)
        currency = info["currency"]

        # Compute tiers from suggested_amount (not from canonical tiers which use dues_rate)
        suggestions = []
        if base_amount > 0:
            for multiplier, label, desc in [
                (1.0, _("Standard"), _("Standard membership fee")),
                (1.25, _("Supporter"), _("Support our mission with 25% extra")),
                (1.5, _("Advocate"), _("Help us grow with 50% extra")),
                (2.0, _("Champion"), _("Be a champion with 100% extra")),
            ]:
                tier_amount = base_amount * multiplier
                percentage = int(multiplier * 100)
                suggestions.append(
                    {
                        "amount": tier_amount,
                        "label": label,
                        "description": desc,
                        "percentage": percentage,
                        "is_default": multiplier == 1.0,
                        "formatted_amount": frappe.utils.fmt_money(tier_amount, currency=currency),
                        "impact_message": get_amount_impact_message(tier_amount, base_amount, percentage),
                    }
                )

        return {
            "success": True,
            "base_amount": base_amount,
            "currency": currency,
            "suggestions": suggestions,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "suggestions": []}


def _get_membership_type_currency(membership_type_doc):
    """Get currency from membership type with explicit validation"""
    # Check if membership type has explicit currency configuration
    if hasattr(membership_type_doc, "currency") and membership_type_doc.currency:
        return membership_type_doc.currency

    # Get company default currency
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and settings.company:
            company_currency = frappe.db.get_value("Company", settings.company, "default_currency")
            if company_currency:
                return company_currency
    except Exception:
        pass

    # Final fallback with explicit documentation
    frappe.log_error(
        f"No currency configured for membership type '{membership_type_doc.name}' and no company default found, using 'EUR' fallback",
        "Membership Type Currency Configuration",
    )
    return "EUR"


def save_draft_application(data):
    """Save application as draft"""
    try:
        draft_id = f"DRAFT-{int(time.time())}"

        # Store in cache for 24 hours
        frappe.cache().set_value(
            f"application_draft:{draft_id}", json.dumps(data), expires_in_sec=86400  # 24 hours
        )

        return {"success": True, "draft_id": draft_id, "message": _("Draft saved successfully")}

    except Exception as e:
        return {"success": False, "error": str(e), "message": _("Error saving draft")}


def load_draft_application(draft_id):
    """Load application draft"""
    try:
        draft_data = frappe.cache().get_value(f"application_draft:{draft_id}")

        if not draft_data:
            return {"success": False, "message": _("Draft not found or expired")}

        return {"success": True, "data": json.loads(draft_data), "message": _("Draft loaded successfully")}

    except Exception as e:
        return {"success": False, "error": str(e), "message": _("Error loading draft")}


def get_member_field_info():
    """Get information about member fields for form generation"""
    try:
        member_meta = frappe.get_meta("Member")
        field_info = {}

        for field in member_meta.fields:
            if field.fieldname in ["first_name", "last_name", "email", "birth_date", "contact_number"]:
                field_info[field.fieldname] = {
                    "label": field.label,
                    "fieldtype": field.fieldtype,
                    "reqd": field.reqd,
                    "description": field.description,
                }

        return {"success": True, "fields": field_info}

    except Exception as e:
        return {"success": False, "error": str(e), "fields": {}}


def check_application_status(application_id):
    """Check the status of an application by ID"""
    try:
        member = frappe.get_value(
            "Member",
            {"application_id": application_id},
            ["name", "application_status", "application_date", "full_name", "email"],
            as_dict=True,
        )

        if not member:
            return {"success": False, "message": _("Application not found")}

        return {
            "success": True,
            "application_id": application_id,
            "status": member.application_status,
            "applicant_name": member.full_name,
            "application_date": member.application_date,
            "member_id": member.name,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": _("Error checking application status")}


def create_pending_chapter_membership(member, chapter_name):
    """Create pending Chapter Member record during application submission"""
    if not member or not chapter_name:
        return None

    try:
        # Check if chapter exists and is valid
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.log_error(f"Chapter {chapter_name} does not exist", "Chapter Not Found")
            return None

        # Check if Chapter Member record already exists for this member and chapter
        existing = frappe.db.exists("Chapter Member", {"member": member.name, "parent": chapter_name})
        if existing:
            frappe.log_error(
                f"Chapter Member record already exists for {member.name} in {chapter_name}",
                "Chapter Membership Error",
            )
            return existing

        # Get the chapter document to add member to the child table
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Clean up orphaned chapter member records before adding new one
        members_to_remove = []
        for i, cm in enumerate(chapter_doc.members):
            if cm.member and not frappe.db.exists("Member", cm.member):
                members_to_remove.append(i)

        # Remove orphaned records in reverse order to maintain indices
        for i in reversed(members_to_remove):
            chapter_doc.remove(chapter_doc.members[i])

        # Add member to the chapter members child table with Pending status
        chapter_member = chapter_doc.append(
            "members",
            {"member": member.name, "chapter_join_date": today(), "enabled": 1, "status": "Pending"},
        )

        # Save the chapter document with secure operations for members field management
        from verenigingen.utils.secure_operations import secure_document_operation

        result = secure_document_operation(
            operation="save",
            doc=chapter_doc,
            justification="pending member addition to chapter",
            required_permissions=["Chapter:write"],
            allow_system_user=True,  # Allow for automated member assignment
        )

        if not result.success:
            frappe.throw(_("Failed to save chapter membership: {0}").format("; ".join(result.errors)))

        # Note: Membership history is automatically tracked by Chapter.validate() hook
        # via member_manager.handle_member_additions() - no need for explicit call here

        frappe.logger().info(f"Created pending Chapter Member record for {member.name} in {chapter_name}")
        return chapter_member

    except Exception as e:
        # Use shorter error message to avoid title length issues
        try:
            frappe.log_error(
                f"Chapter membership creation failed: {str(e)[:150]}",
                "Chapter Setup Error",
            )
        except Exception:
            # Fallback logging if error log creation fails
            frappe.logger().error(f"Chapter membership creation failed for {member.name}")
        return None


def activate_pending_chapter_membership(member, chapter_name):
    """Activate pending Chapter Member record during application approval"""
    if not member or not chapter_name:
        return None

    try:
        # Check if chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.log_error(f"Chapter {chapter_name} does not exist", "Chapter Membership Activation")
            return None

        # Get the chapter document
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Find the pending Chapter Member record
        pending_member = None
        for cm in chapter_doc.members:
            if cm.member == member.name and cm.status == "Pending":
                pending_member = cm
                break

        if not pending_member:
            # No pending record found, create a new active one
            frappe.logger().info(
                f"No pending Chapter Member found for {member.name} in {chapter_name}, creating new active record"
            )
            return create_active_chapter_membership(member, chapter_name)

        # Activate the pending record
        pending_member.status = "Active"
        pending_member.chapter_join_date = today()  # Update join date to approval date

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        chapter_result = secure_document_operation(
            operation="save",
            doc=chapter_doc,
            justification=f"Activate chapter member {member.name} in chapter {chapter_name}",
            required_permissions=["Chapter:write"],
        )

        if not chapter_result.success:
            frappe.logger().error(f"Failed to activate chapter member: {'; '.join(chapter_result.errors)}")
            frappe.throw(_("Failed to activate chapter member: {0}").format("; ".join(chapter_result.errors)))

        # Update membership history to reflect activation
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        history_updated = ChapterMembershipHistoryManager.update_membership_status(
            member_id=member.name,
            chapter_name=chapter_name,
            assignment_type="Member",
            new_status="Active",
            reason=f"Membership application approved for {chapter_name} chapter",
        )

        if history_updated:
            frappe.logger().info(
                f"Activated Chapter Member record and updated history for {member.name} in {chapter_name}"
            )
        else:
            frappe.logger().warning(
                f"Activated Chapter Member record for {member.name} in {chapter_name} "
                f"but failed to update membership history - pending entry may still exist"
            )

        return pending_member

    except Exception as e:
        frappe.log_error(
            f"Error activating chapter membership for {member.name} in {chapter_name}: {str(e)}",
            "Chapter Activation Error",
        )
        return None


def create_active_chapter_membership(member, chapter_name):
    """Create active Chapter Member record directly (fallback for when no pending record exists)"""
    if not member or not chapter_name:
        return None

    try:
        # Check if chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.log_error(f"Chapter {chapter_name} does not exist", "Chapter Not Found")
            return None

        # Check if Chapter Member record already exists
        existing = frappe.db.exists("Chapter Member", {"member": member.name, "parent": chapter_name})
        if existing:
            # Update existing record to Active if it's not already
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            for cm in chapter_doc.members:
                if cm.member == member.name:
                    if cm.status != "Active":
                        cm.status = "Active"
                        cm.chapter_join_date = today()
                        from verenigingen.utils.secure_operations import secure_document_operation

                        update_result = secure_document_operation(
                            operation="save",
                            doc=chapter_doc,
                            justification=f"Update existing chapter member {member.name} to Active in {chapter_name}",
                            required_permissions=["Chapter:write"],
                        )

                        if not update_result.success:
                            frappe.logger().error(
                                f"Failed to update chapter member status: {'; '.join(update_result.errors)}"
                            )
                            frappe.throw(
                                _("Failed to update chapter member status: {0}").format(
                                    "; ".join(update_result.errors)
                                )
                            )
                        frappe.logger().info(
                            f"Updated existing Chapter Member record to Active for {member.name} in {chapter_name}"
                        )
                    return cm

        # Create new active record
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        chapter_member = chapter_doc.append(
            "members", {"member": member.name, "chapter_join_date": today(), "enabled": 1, "status": "Active"}
        )

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        add_member_result = secure_document_operation(
            operation="save",
            doc=chapter_doc,
            justification=f"Add new chapter member {member.name} to {chapter_name}",
            required_permissions=["Chapter:write"],
        )

        if not add_member_result.success:
            frappe.logger().error(f"Failed to add chapter member: {'; '.join(add_member_result.errors)}")
            frappe.throw(_("Failed to add chapter member: {0}").format("; ".join(add_member_result.errors)))

        # Update membership history tracking for active membership
        # Check if a Pending entry exists and update it, otherwise add new Active entry
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        # Try to update existing Pending history first
        history_updated = ChapterMembershipHistoryManager.update_membership_status(
            member_id=member.name,
            chapter_name=chapter_name,
            assignment_type="Member",
            new_status="Active",
            reason=f"Direct activation for {chapter_name} chapter",
        )

        # Only add new history if no existing Pending entry was updated
        if not history_updated:
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member.name,
                chapter_name=chapter_name,
                assignment_type="Member",
                start_date=today(),
                status="Active",
                reason=f"Direct activation for {chapter_name} chapter (no pending entry found)",
            )

        frappe.logger().info(f"Created active Chapter Member record for {member.name} in {chapter_name}")
        return chapter_member

    except Exception as e:
        frappe.log_error(
            f"Error creating active chapter membership for {member.name} in {chapter_name}: {str(e)}",
            "Chapter Creation Error",
        )
        return None


def remove_pending_chapter_membership(member, chapter_name=None):
    """Remove pending Chapter Member record when application is rejected"""
    if not member:
        return False

    try:
        # If no specific chapter provided, look at member's suggested chapter or current chapter display
        if not chapter_name:
            if hasattr(member, "suggested_chapter") and member.suggested_chapter:
                chapter_name = member.suggested_chapter
            elif hasattr(member, "current_chapter_display") and member.current_chapter_display:
                chapter_name = member.current_chapter_display
            else:
                # No chapter to remove from
                return True

        # Check if chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.logger().warning(
                f"Chapter {chapter_name} does not exist, cannot remove pending membership"
            )
            return False

        # Get the chapter document
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Find and remove the pending Chapter Member record
        members_to_remove = []
        for i, cm in enumerate(chapter_doc.members):
            if cm.member == member.name and cm.status == "Pending":
                members_to_remove.append(i)

        # Remove in reverse order to maintain correct indices
        for i in reversed(members_to_remove):
            chapter_doc.remove(chapter_doc.members[i])

        if members_to_remove:
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            remove_result = secure_document_operation(
                operation="save",
                doc=chapter_doc,
                justification=f"Remove pending chapter member {member.name} from {chapter_name}",
                required_permissions=["Chapter:write"],
            )

            if not remove_result.success:
                frappe.logger().error(
                    f"Failed to remove pending chapter member: {'; '.join(remove_result.errors)}"
                )
                frappe.throw(
                    _("Failed to remove pending chapter member: {0}").format("; ".join(remove_result.errors))
                )

            # Update history entry to Terminated
            try:
                from verenigingen.utils.chapter_membership_history_manager import (
                    ChapterMembershipHistoryManager,
                )

                ChapterMembershipHistoryManager.terminate_chapter_membership(
                    member_id=member.name,
                    chapter_name=chapter_name,
                    assignment_type="Member",
                    end_date=today(),
                    reason="Membership application rejected",
                )
            except Exception as e:
                frappe.logger().warning(
                    f"Failed to update chapter membership history for {member.name} in {chapter_name}: {e}"
                )

            frappe.logger().info(
                f"Removed {len(members_to_remove)} pending Chapter Member record(s) for {member.name} from {chapter_name}"
            )
            return True
        else:
            frappe.logger().info(
                f"No pending Chapter Member record found for {member.name} in {chapter_name}"
            )
            return True

    except Exception as e:
        frappe.log_error(
            f"Error removing pending chapter membership for {member.name} from {chapter_name}: {str(e)}",
            "Chapter Removal Error",
        )
        return False


def remove_all_pending_chapter_memberships(member):
    """Find and remove ALL pending chapter memberships for a member.

    Queries the Chapter Member child table directly to find all chapters where
    this member has a Pending record, then removes each one (including history update).

    Args:
        member: Member document

    Returns:
        list: Chapter names where pending memberships were removed
    """
    if not member:
        return []

    pending_chapters = frappe.db.sql(
        """SELECT DISTINCT parent as chapter
           FROM `tabChapter Member`
           WHERE member = %s AND status = 'Pending'""",
        (member.name,),
        as_dict=True,
    )

    removed = []
    for record in pending_chapters:
        if remove_pending_chapter_membership(member, record.chapter):
            removed.append(record.chapter)

    return removed
