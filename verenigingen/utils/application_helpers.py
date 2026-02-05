"""
Helper utilities for membership application processing
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import now_datetime, today

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
    """Generate unique application ID with robust collision handling"""
    import datetime
    import os
    import random

    date_str = frappe.utils.nowdate().replace("-", "")
    max_attempts = 20  # Reduce attempts but improve strategy

    for attempt in range(max_attempts):
        # Use different strategies for better distribution
        if attempt == 0:
            # First attempt: use timestamp + microseconds for high uniqueness
            now = datetime.datetime.now()
            timestamp_part = int(now.timestamp() * 1000) % 10000  # millisecond precision
            app_id = f"APP-{date_str}-{timestamp_part:04d}"
        elif attempt < 5:
            # Early attempts: use timestamp with random offset
            timestamp_part = int(time.time() % 10000) + random.randint(-500, 500)
            timestamp_part = abs(timestamp_part) % 10000  # Keep in range
            app_id = f"APP-{date_str}-{timestamp_part:04d}"
        else:
            # Later attempts: pure random with wider range
            random_part = random.randint(1000, 9999)
            app_id = f"APP-{date_str}-{random_part}"

        # Simple existence check (database constraint will handle race conditions)
        if not frappe.db.exists("Member", {"application_id": app_id}):
            return app_id

    # Final fallback: use process ID + microseconds for maximum uniqueness
    final_part = f"{os.getpid() % 100:02d}{datetime.datetime.now().microsecond % 100:02d}"
    return f"APP-{date_str}-{final_part}"


def parse_application_data(data_input):
    """Parse and validate incoming application data"""
    if data_input is None:
        raise ValueError("No data provided")

    if isinstance(data_input, str):
        try:
            # Log the first part of the JSON for debugging
            preview = data_input[:200] if len(data_input) > 200 else data_input
            frappe.logger("verenigingen.application").debug(
                f"Parsing JSON data (length: {len(data_input)}): {preview}..."
            )

            # Decode HTML entities (handles cases where JSON gets HTML encoded)
            import html

            decoded_data = html.unescape(data_input)
            frappe.logger("verenigingen.application").debug(f"After HTML decoding: {decoded_data[:100]}...")

            # Debug: Check complete data structure
            if decoded_data:
                frappe.logger("verenigingen.application").debug(
                    f"Complete decoded data length: {len(decoded_data)}"
                )
                frappe.logger("verenigingen.application").debug(
                    f"Decoded data starts with: {decoded_data[:100]}"
                )
                frappe.logger("verenigingen.application").debug(
                    f"Decoded data ends with: {decoded_data[-100:]}"
                )

                first_char = decoded_data[0]
                first_char_code = ord(first_char)
                frappe.logger("verenigingen.application").debug(
                    f"First character: '{first_char}' (ASCII: {first_char_code})"
                )

                # Check if this looks like truncated JSON
                if decoded_data.count("{") != decoded_data.count("}"):
                    frappe.logger("verenigingen.application").error(
                        f"Unbalanced braces! Opening: {decoded_data.count('{')} Closing: {decoded_data.count('}')}"
                    )

                # Strip whitespace and try again if needed
                stripped_data = decoded_data.strip()
                if stripped_data != decoded_data:
                    frappe.logger("verenigingen.application").debug(
                        "Found whitespace, using stripped version"
                    )
                    decoded_data = stripped_data

            data = json.loads(decoded_data)
        except json.JSONDecodeError as e:
            # Enhanced error message with more context
            error_msg = f"Invalid JSON format: {str(e)}"
            # Use decoded data for error reporting if available
            error_data = locals().get("decoded_data", data_input)
            if len(error_data) > 0:
                # Show the problematic area around the error
                start = max(0, e.pos - 20) if hasattr(e, "pos") else 0
                end = min(len(error_data), start + 40)
                problematic_section = error_data[start:end]
                error_msg += f" | Problematic section: '{problematic_section}'"

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


def create_member_from_application(data, application_id, address=None):
    """Create member record from application data"""
    # Import here to avoid circular imports
    from verenigingen.utils.secure_operations import get_system_user_for_operation
    from verenigingen.utils.validation.application_validators import validate_name

    # Sanitize names before creating member record
    first_name = data.get("first_name", "")
    middle_name = data.get("middle_name", "")
    tussenvoegsel = data.get("tussenvoegsel", "")
    last_name = data.get("last_name", "")

    # Validate and sanitize names
    if first_name:
        validation_result = validate_name(first_name, "First Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            first_name = validation_result["sanitized"]

    if middle_name:
        validation_result = validate_name(middle_name, "Middle Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            middle_name = validation_result["sanitized"]

    if tussenvoegsel:
        validation_result = validate_name(tussenvoegsel, "Tussenvoegsel")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            tussenvoegsel = validation_result["sanitized"]

    if last_name:
        validation_result = validate_name(last_name, "Last Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            last_name = validation_result["sanitized"]

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

    # Handle custom membership amount using new fee override fields
    if data.get("custom_contribution_fee") or data.get("uses_custom_amount"):
        try:
            # Debug logging
            frappe.logger().info(
                f"Processing custom amount for application. custom_contribution_fee: {data.get('custom_contribution_fee')}, uses_custom_amount: {data.get('uses_custom_amount')}"
            )

            # Safely convert custom_contribution_fee to float
            custom_contribution_fee = 0
            if data.get("custom_contribution_fee"):
                try:
                    custom_contribution_fee = float(data.get("custom_contribution_fee"))
                    frappe.logger().info(f"Converted custom_contribution_fee to: {custom_contribution_fee}")
                except (ValueError, TypeError) as e:
                    frappe.logger().error(
                        f"Error converting custom_contribution_fee '{data.get('custom_contribution_fee')}' to float: {str(e)}"
                    )
                    custom_contribution_fee = 0

            # Set fee override fields if custom amount is specified
            if custom_contribution_fee > 0:
                member.dues_rate = custom_contribution_fee
                member.fee_override_reason = f"Custom amount selected during application: {data.get('custom_amount_reason', 'Member-specified contribution level')}"
                member.fee_override_date = today()
                # Also store in the application-specific field
                member.application_custom_fee = custom_contribution_fee

                # Use a safe fallback for fee_override_by - ensure the user exists
                override_user = None

                # Try current session user first
                if frappe.session.user and frappe.session.user != "Guest":
                    if frappe.db.exists("User", frappe.session.user):
                        override_user = frappe.session.user

                # Fallback to Administrator if it exists
                if not override_user and frappe.db.exists("User", "Administrator"):
                    override_user = "Administrator"

                # Final fallback - find any valid user
                if not override_user:
                    first_user = frappe.db.get_value("User", {"enabled": 1}, "name")
                    if first_user:
                        override_user = first_user

                # Only set fee_override_by if we found a valid user
                # Keep the custom amount data regardless - it's valid even without approver info
                if override_user:
                    member.fee_override_by = override_user
                else:
                    # Log warning but keep the custom amount data - don't discard it
                    frappe.log_error(
                        "No valid user found for fee_override_by field - custom amount preserved without approver",
                        "Fee Override User Warning",
                    )
                    # Note: We intentionally do NOT reset dues_rate, fee_override_reason, fee_override_date
                    # The custom amount is valid even if we can't record who approved it

            # Legacy JSON storage in notes removed - data now stored in proper fields
        except Exception as e:
            # Log the error for debugging but don't fail the submission
            frappe.log_error(f"Error storing custom amount data: {str(e)}", "Custom Amount Storage Error")

    # Add chapter information to notes for approver visibility
    try:
        selected_chapter = data.get("selected_chapter")
        if selected_chapter:
            existing_notes = member.notes or ""
            if existing_notes:
                existing_notes += "\n\n"

            # Get chapter display name if possible
            try:
                # chapter_doc = frappe.get_doc("Chapter", selected_chapter)
                # chapter_display = f"{chapter_doc.chapter_name} ({selected_chapter})"
                chapter_doc = frappe.get_doc("Chapter", selected_chapter)
                chapter_display = f"{chapter_doc.region} ({selected_chapter})"
            except Exception:
                chapter_display = selected_chapter

            member.notes = existing_notes + f"Selected Chapter: {chapter_display}"
    except Exception as e:
        # Log the error for debugging but don't fail the submission
        frappe.log_error(f"Error storing chapter information: {str(e)}", "Chapter Info Storage Error")

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
    from verenigingen.utils.validation.application_validators import validate_name

    # Get existing member
    member = frappe.get_doc("Member", member_name)

    # Sanitize names before updating
    first_name = data.get("first_name", "")
    middle_name = data.get("middle_name", "")
    tussenvoegsel = data.get("tussenvoegsel", "")
    last_name = data.get("last_name", "")

    # Validate and sanitize names
    if first_name:
        validation_result = validate_name(first_name, "First Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            first_name = validation_result["sanitized"]

    if middle_name:
        validation_result = validate_name(middle_name, "Middle Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            middle_name = validation_result["sanitized"]

    if tussenvoegsel:
        validation_result = validate_name(tussenvoegsel, "Tussenvoegsel")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            tussenvoegsel = validation_result["sanitized"]

    if last_name:
        validation_result = validate_name(last_name, "Last Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            last_name = validation_result["sanitized"]

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
    selected_chapter = data.get("selected_chapter")
    if selected_chapter:
        try:
            chapter_doc = frappe.get_doc("Chapter", selected_chapter)
            chapter_display = f"{chapter_doc.region} ({selected_chapter})"
            existing_notes = member.notes or ""
            if existing_notes:
                existing_notes += "\n\n"
            member.notes = existing_notes + f"Selected Chapter (Reapplication): {chapter_display}\n"
        except Exception as e:
            frappe.log_error(f"Error storing chapter information: {str(e)}", "Chapter Info Storage Error")

    # Add reapplication timestamp note
    reapp_note = f"Reapplication submitted: {now_datetime()}"
    if member.notes:
        member.notes += f"\n{reapp_note}"
    else:
        member.notes = reapp_note

    # Suppress customer creation messages during reapplication processing
    member._suppress_customer_messages = True

    # Handle custom membership amount
    if data.get("custom_contribution_fee") or data.get("uses_custom_amount"):
        try:
            custom_contribution_fee = 0
            if data.get("custom_contribution_fee"):
                try:
                    custom_contribution_fee = float(data.get("custom_contribution_fee"))
                except (ValueError, TypeError) as e:
                    frappe.logger().error(f"Error converting custom_contribution_fee: {str(e)}")
                    custom_contribution_fee = 0

            if custom_contribution_fee > 0:
                member.dues_rate = custom_contribution_fee
                member.fee_override_reason = f"Custom amount from reapplication: {data.get('custom_amount_reason', 'Member-specified contribution level')}"
                member.fee_override_date = today()
                member.application_custom_fee = custom_contribution_fee

                # Set override user
                override_user = None
                if frappe.session.user and frappe.session.user != "Guest":
                    if frappe.db.exists("User", frappe.session.user):
                        override_user = frappe.session.user
                if not override_user and frappe.db.exists("User", "Administrator"):
                    override_user = "Administrator"
                if override_user:
                    member.fee_override_by = override_user

        except Exception as e:
            frappe.log_error(f"Error updating custom amount data: {str(e)}", "Custom Amount Update Error")

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


def get_membership_fee_info(membership_type):
    """Get membership fee information"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Get standard amount and billing frequency from template
        standard_amount = 0
        billing_frequency = "Annual"  # Default
        if membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                standard_amount = template.dues_rate or template.suggested_amount or 0
                # Get billing frequency from template (source of truth)
                billing_frequency = template.billing_frequency or "Annual"
            except Exception:
                pass

        # Fallback to minimum_amount if no template amount available
        if not standard_amount:
            standard_amount = membership_type_doc.minimum_amount

        return {
            "success": True,
            "membership_type": membership_type,
            "standard_amount": standard_amount,
            "currency": _get_membership_type_currency(membership_type_doc),
            "description": membership_type_doc.description,
            "billing_frequency": billing_frequency,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error retrieving membership fee information"}


def get_membership_type_details(membership_type):
    """Get detailed membership type information"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Get base amount and billing frequency from template
        base_amount = 0
        billing_frequency = "Annual"  # Default
        if membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                base_amount = template.dues_rate or template.suggested_amount or 0
                # Get billing frequency from template (source of truth)
                billing_frequency = template.billing_frequency or "Annual"
            except Exception:
                pass

        # Fallback to minimum_amount if no template amount available
        if not base_amount:
            base_amount = membership_type_doc.minimum_amount

        base_amount = float(base_amount)

        # Calculate suggested amounts (if custom amounts allowed)
        suggested_amounts = []

        # Standard amount
        suggested_amounts.append(
            {"amount": base_amount, "label": "Standard", "description": "Standard membership fee"}
        )

        # Supporter amounts
        for multiplier, label in [(1.5, "Supporter"), (2.0, "Patron"), (3.0, "Benefactor")]:
            suggested_amounts.append(
                {
                    "amount": base_amount * multiplier,
                    "label": label,
                    "description": f"Support our mission with {int((multiplier - 1) * 100)}% extra",
                }
            )

        return {
            "success": True,
            "name": membership_type_doc.name,
            "membership_type_name": membership_type_doc.membership_type_name,
            "description": membership_type_doc.description,
            "amount": base_amount,  # Use template-based amount, not minimum_amount
            "currency": _get_membership_type_currency(membership_type_doc),
            "billing_frequency": billing_frequency,
            "allow_custom_amount": True,  # Enable custom amounts for all membership types
            # minimum_amount usage here is correct - it's for validation bounds
            "minimum_amount": membership_type_doc.minimum_amount * 0.5,  # 50% of constraint floor
            "maximum_amount": base_amount * 5,  # 5x standard amount
            "custom_amount_note": "You can adjust your contribution amount. Minimum is 50% of standard fee.",
            "suggested_amounts": suggested_amounts,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error retrieving membership type details"}


# Legacy get_member_custom_amount_data function removed - use contribution system instead


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
    """Suggest membership amounts based on type"""
    try:
        membership_type = frappe.get_doc("Membership Type", membership_type_name)
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
        # Validate suggested amount - allow zero if minimum_amount is also zero (free membership)
        if template.suggested_amount is None:
            frappe.throw(f"Dues Schedule Template '{template.name}' must have a suggested_amount configured")

        if template.suggested_amount < 0:
            frappe.throw(
                f"Dues Schedule Template '{template.name}' cannot have negative suggested_amount: {template.suggested_amount}"
            )

        # Allow zero amounts only if the membership type minimum is also zero (free membership)
        if template.suggested_amount == 0:
            membership_type_minimum = getattr(membership_type, "minimum_amount", None)
            if membership_type_minimum is None or membership_type_minimum > 0:
                frappe.throw(
                    f"Dues Schedule Template '{template.name}' has zero suggested_amount but Membership Type '{membership_type.name}' minimum_amount is {membership_type_minimum}. For free memberships, both must be zero."
                )
        base_amount = float(template.suggested_amount)
        currency = _get_membership_type_currency(membership_type)

        suggestions = [
            {
                "amount": base_amount,
                "label": _("Standard"),
                "description": _("Standard membership fee"),
                "percentage": 100,
                "is_default": True,
            },
            {
                "amount": base_amount * 1.25,
                "label": _("Supporter"),
                "description": _("Support our mission with 25% extra"),
                "percentage": 125,
            },
            {
                "amount": base_amount * 1.5,
                "label": _("Advocate"),
                "description": _("Help us grow with 50% extra"),
                "percentage": 150,
            },
            {
                "amount": base_amount * 2,
                "label": _("Champion"),
                "description": _("Be a champion with 100% extra"),
                "percentage": 200,
            },
        ]

        # Format amounts
        for suggestion in suggestions:
            suggestion["formatted_amount"] = frappe.utils.fmt_money(suggestion["amount"], currency=currency)
            suggestion["impact_message"] = get_amount_impact_message(
                suggestion["amount"], base_amount, suggestion["percentage"]
            )

        return {"success": True, "base_amount": base_amount, "currency": currency, "suggestions": suggestions}

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
