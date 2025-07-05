"""
Helper utilities for membership application processing
"""
import json
import time

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.dutch_name_utils import format_dutch_full_name, is_dutch_installation

# Import moved inside function to avoid circular imports


def map_payment_method(payment_method):
    """Map form payment method values to Member doctype values"""
    payment_method_map = {
        "bank_transfer": "Bank Transfer",
        "sepa_direct_debit": "SEPA Direct Debit",
        "credit_card": "Credit Card",
        "cash": "Cash",
        "other": "Other",
        # Also handle case where we receive the display values directly
        "Bank Transfer": "Bank Transfer",
        "SEPA Direct Debit": "SEPA Direct Debit",
        "Credit Card": "Credit Card",
        "Cash": "Cash",
        "Other": "Other",
    }
    # Default to Bank Transfer if no match found
    return payment_method_map.get(payment_method, "Bank Transfer")


def generate_application_id():
    """Generate unique application ID"""
    return f"APP-{frappe.utils.nowdate().replace('-', '')}-{int(time.time() % 10000):04d}"


def parse_application_data(data_input):
    """Parse and validate incoming application data"""
    if data_input is None:
        raise ValueError("No data provided")

    if isinstance(data_input, str):
        try:
            data = json.loads(data_input)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {str(e)}")
    else:
        data = data_input

    return data


def get_form_data():
    """Get data needed for application form"""
    try:
        # Get active membership types
        membership_types = []
        try:
            membership_types = frappe.get_all(
                "Membership Type",
                filters={"is_active": 1},
                fields=[
                    "name",
                    "membership_type_name",
                    "description",
                    "amount",
                    "currency",
                    "subscription_period",
                ],
                order_by="amount",
            )
        except Exception as e:
            frappe.log_error(f"Error getting membership types: {str(e)}")

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
    from verenigingen.utils.application_validators import validate_name

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
    address.flags.ignore_permissions = True
    address.insert(ignore_permissions=True)
    return address


def create_member_from_application(data, application_id, address=None):
    """Create member record from application data"""
    # Import here to avoid circular imports
    from verenigingen.utils.application_validators import validate_name

    # Sanitize names before creating member record
    first_name = data.get("first_name", "")
    middle_name = data.get("middle_name", "")
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

    if last_name:
        validation_result = validate_name(last_name, "Last Name")
        if validation_result.get("valid") and validation_result.get("sanitized"):
            last_name = validation_result["sanitized"]

    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": first_name,
            "middle_name": middle_name,
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
            "interested_in_volunteering": data.get("interested_in_volunteering", 0),
            "newsletter_opt_in": data.get("newsletter_opt_in", 1),
            "application_source": data.get("application_source", "Website"),
            "notes": data.get("additional_notes", ""),
            "payment_method": map_payment_method(data.get("payment_method", "")),
            "current_chapter_display": data.get("selected_chapter", ""),
            # Bank details for bank transfer/direct debit
            "iban": data.get("iban", ""),
            "bic": data.get("bic", ""),
            "bank_account_name": data.get("bank_account_name", ""),
        }
    )

    # Store volunteer skills data as a temporary attribute for volunteer record creation
    volunteer_skills = data.get("volunteer_skills", [])
    if volunteer_skills:
        member.volunteer_skills = volunteer_skills

    # Handle custom membership amount using new fee override fields
    if data.get("membership_amount") or data.get("uses_custom_amount"):
        try:
            # Debug logging
            frappe.logger().info(
                f"Processing custom amount for application. membership_amount: {data.get('membership_amount')}, uses_custom_amount: {data.get('uses_custom_amount')}"
            )

            # Safely convert membership_amount to float
            membership_amount = 0
            if data.get("membership_amount"):
                try:
                    membership_amount = float(data.get("membership_amount"))
                    frappe.logger().info(f"Converted membership_amount to: {membership_amount}")
                except (ValueError, TypeError) as e:
                    frappe.logger().error(
                        f"Error converting membership_amount '{data.get('membership_amount')}' to float: {str(e)}"
                    )
                    membership_amount = 0

            # Set fee override fields if custom amount is specified
            if membership_amount > 0:
                member.membership_fee_override = membership_amount
                member.fee_override_reason = f"Custom amount selected during application: {data.get('custom_amount_reason', 'Member-specified contribution level')}"
                member.fee_override_date = today()

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

                # Only set the field if we found a valid user
                if override_user:
                    member.fee_override_by = override_user
                else:
                    # Log warning but don't fail - just skip the fee override fields
                    frappe.log_error(
                        "No valid user found for fee_override_by field", "Fee Override User Error"
                    )
                    member.membership_fee_override = None
                    member.fee_override_reason = None
                    member.fee_override_date = None

            # Store legacy data in notes for audit purposes
            custom_amount_data = {
                "membership_amount": membership_amount,
                "uses_custom_amount": bool(data.get("uses_custom_amount", False)),
            }

            # Only store if there's actually custom amount data
            if membership_amount > 0 or custom_amount_data["uses_custom_amount"]:
                existing_notes = member.notes or ""
                if existing_notes:
                    existing_notes += "\n\n"

                member.notes = existing_notes + f"Custom Amount Data: {json.dumps(custom_amount_data)}"
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
                chapter_doc = frappe.get_doc("Chapter", selected_chapter)
                chapter_display = f"{chapter_doc.chapter_name} ({selected_chapter})"
            except Exception:
                chapter_display = selected_chapter

            member.notes = existing_notes + f"Selected Chapter: {chapter_display}"
    except Exception as e:
        # Log the error for debugging but don't fail the submission
        frappe.log_error(f"Error storing chapter information: {str(e)}", "Chapter Info Storage Error")

    # Suppress customer creation messages during application submission
    member._suppress_customer_messages = True
    member.flags.ignore_permissions = True
    member.insert(ignore_permissions=True)
    return member


def create_volunteer_record(member):
    """Create volunteer record if member is interested"""
    if not member.interested_in_volunteering:
        return None

    try:
        # Create volunteer name using Dutch naming conventions if applicable
        if member.full_name:
            # Use the member's properly formatted full_name (which includes Dutch naming if applicable)
            volunteer_name = member.full_name
        elif is_dutch_installation() and hasattr(member, "tussenvoegsel") and member.tussenvoegsel:
            # For Dutch installations, format name with tussenvoegsel
            volunteer_name = format_dutch_full_name(
                member.first_name,
                None,  # Don't use middle_name when tussenvoegsel is available
                member.tussenvoegsel,
                member.last_name,
            )
        else:
            # Standard name formatting for non-Dutch installations
            volunteer_name = f"{member.first_name} {member.last_name}".strip()

        if not volunteer_name:
            volunteer_name = member.email  # Fallback to email if no name available

        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": volunteer_name,
                "member": member.name,
                "email": member.email,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "status": "New",  # Changed from "Pending" to "New" - valid status for new volunteers
                "available": 1,
                "date_joined": today(),
            }
        )

        # Add volunteer skills if provided
        volunteer_skills = getattr(member, "volunteer_skills", None)
        if volunteer_skills and isinstance(volunteer_skills, (list, str)):
            # Parse skills if it's a JSON string
            if isinstance(volunteer_skills, str):
                try:
                    import json

                    volunteer_skills = json.loads(volunteer_skills)
                except Exception:
                    volunteer_skills = []

            # Add each skill to the volunteer record
            for skill_data in volunteer_skills:
                if isinstance(skill_data, dict) and skill_data.get("skill_name"):
                    # Map the application skill level to doctype proficiency level
                    proficiency_mapping = {
                        "Beginner": "1 - Beginner",
                        "Intermediate": "3 - Intermediate",
                        "Advanced": "4 - Advanced",
                        "Expert": "5 - Expert",
                    }

                    proficiency = proficiency_mapping.get(
                        skill_data.get("skill_level", ""), "3 - Intermediate"
                    )

                    # Try to categorize the skill
                    skill_name = skill_data.get("skill_name", "").lower()
                    skill_category = "Other"  # Default

                    if any(
                        word in skill_name
                        for word in ["programming", "coding", "website", "tech", "it", "computer"]
                    ):
                        skill_category = "Technical"
                    elif any(word in skill_name for word in ["event", "planning", "organize"]):
                        skill_category = "Event Planning"
                    elif any(
                        word in skill_name for word in ["communicate", "writing", "speaking", "presentation"]
                    ):
                        skill_category = "Communication"
                    elif any(word in skill_name for word in ["lead", "manage", "supervise"]):
                        skill_category = "Leadership"
                    elif any(word in skill_name for word in ["accounting", "finance", "budget"]):
                        skill_category = "Financial"
                    elif any(word in skill_name for word in ["admin", "organization", "coordination"]):
                        skill_category = "Organizational"

                    volunteer.append(
                        "skills_and_qualifications",
                        {
                            "volunteer_skill": skill_data.get("skill_name"),
                            "skill_category": skill_category,
                            "proficiency_level": proficiency,
                        },
                    )

        volunteer.insert(ignore_permissions=True)
        return volunteer
    except Exception as e:
        frappe.log_error(f"Error creating volunteer record: {str(e)}")
        return None


def get_membership_fee_info(membership_type):
    """Get membership fee information"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        return {
            "success": True,
            "membership_type": membership_type,
            "standard_amount": membership_type_doc.amount,
            "currency": membership_type_doc.currency or "EUR",
            "description": membership_type_doc.description,
            "subscription_period": membership_type_doc.subscription_period,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error retrieving membership fee information"}


def get_membership_type_details(membership_type):
    """Get detailed membership type information"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Calculate suggested amounts (if custom amounts allowed)
        suggested_amounts = []
        base_amount = float(membership_type_doc.amount)

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
            "amount": membership_type_doc.amount,
            "currency": membership_type_doc.currency or "EUR",
            "subscription_period": membership_type_doc.subscription_period,
            "allow_custom_amount": True,  # Enable custom amounts for all membership types
            "minimum_amount": membership_type_doc.amount * 0.5,  # 50% of standard amount
            "maximum_amount": membership_type_doc.amount * 5,  # 5x standard amount
            "custom_amount_note": "You can adjust your contribution amount. Minimum is 50% of standard fee.",
            "suggested_amounts": suggested_amounts,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error retrieving membership type details"}


def get_member_custom_amount_data(member):
    """Extract custom amount data from member notes"""
    try:
        import re

        if not hasattr(member, "notes") or not member.notes:
            return None

        # Look for JSON data in notes - make pattern more specific
        pattern = r"Custom Amount Data: (\{[^}]*\})"
        match = re.search(pattern, member.notes, re.DOTALL)

        if match:
            json_str = match.group(1)
            return json.loads(json_str)

        return None
    except Exception as e:
        # Log error for debugging but don't fail
        frappe.log_error(f"Error parsing custom amount data: {str(e)}", "Custom Amount Parse Error")
        return None


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
        base_amount = float(membership_type.amount)
        currency = membership_type.currency or "EUR"

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
            frappe.log_error(f"Chapter {chapter_name} does not exist", "Chapter Membership Creation")
            return None

        # Check if Chapter Member record already exists for this member and chapter
        existing = frappe.db.exists("Chapter Member", {"member": member.name, "parent": chapter_name})
        if existing:
            frappe.log_error(
                f"Chapter Member record already exists for {member.name} in {chapter_name}",
                "Chapter Membership Creation",
            )
            return existing

        # Get the chapter document to add member to the child table
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Add member to the chapter members child table with Pending status
        chapter_member = chapter_doc.append(
            "members",
            {"member": member.name, "chapter_join_date": today(), "enabled": 1, "status": "Pending"},
        )

        # Save the chapter document
        chapter_doc.save()

        # Add membership history tracking for pending membership
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        ChapterMembershipHistoryManager.add_membership_history(
            member_id=member.name,
            chapter_name=chapter_name,
            assignment_type="Member",
            start_date=today(),
            status="Pending",
            reason=f"Applied for membership in {chapter_name} chapter",
        )

        frappe.logger().info(f"Created pending Chapter Member record for {member.name} in {chapter_name}")
        return chapter_member

    except Exception as e:
        frappe.log_error(
            f"Error creating pending chapter membership for {member.name} in {chapter_name}: {str(e)}",
            "Chapter Membership Creation Error",
        )
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

        # Save the chapter document
        chapter_doc.save()

        # Update membership history to reflect activation
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        ChapterMembershipHistoryManager.update_membership_status(
            member_id=member.name,
            chapter_name=chapter_name,
            assignment_type="Member",
            new_status="Active",
            reason=f"Membership application approved for {chapter_name} chapter",
        )

        frappe.logger().info(f"Activated Chapter Member record for {member.name} in {chapter_name}")
        return pending_member

    except Exception as e:
        frappe.log_error(
            f"Error activating chapter membership for {member.name} in {chapter_name}: {str(e)}",
            "Chapter Membership Activation Error",
        )
        return None


def create_active_chapter_membership(member, chapter_name):
    """Create active Chapter Member record directly (fallback for when no pending record exists)"""
    if not member or not chapter_name:
        return None

    try:
        # Check if chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.log_error(f"Chapter {chapter_name} does not exist", "Chapter Membership Creation")
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
                        chapter_doc.save()
                        frappe.logger().info(
                            f"Updated existing Chapter Member record to Active for {member.name} in {chapter_name}"
                        )
                    return cm

        # Create new active record
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        chapter_member = chapter_doc.append(
            "members", {"member": member.name, "chapter_join_date": today(), "enabled": 1, "status": "Active"}
        )

        chapter_doc.save()

        # Add membership history tracking for active membership
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        ChapterMembershipHistoryManager.add_membership_history(
            member_id=member.name,
            chapter_name=chapter_name,
            assignment_type="Member",
            start_date=today(),
            status="Active",
            reason=f"Direct activation for {chapter_name} chapter",
        )

        frappe.logger().info(f"Created active Chapter Member record for {member.name} in {chapter_name}")
        return chapter_member

    except Exception as e:
        frappe.log_error(
            f"Error creating active chapter membership for {member.name} in {chapter_name}: {str(e)}",
            "Chapter Membership Creation Error",
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
            # Save the chapter document
            chapter_doc.save()
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
            "Chapter Membership Removal Error",
        )
        return False
