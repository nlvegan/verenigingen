"""
Personal Details Management Page
Allows members to view and update their personal information including pronouns
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, today


def get_context(context):
    """Get context for personal details page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Personal Details")

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    context.member = frappe.get_doc("Member", member)

    # Check for success messages from form submission
    success_messages = frappe.session.get("personal_details_success")
    if success_messages:
        context.success_messages = success_messages
        # Clear messages after displaying
        del frappe.session["personal_details_success"]

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for personal details page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_personal_details():
    """Handle personal details form submission"""

    # Get member
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member_name:
        frappe.throw(_("No member record found"), frappe.DoesNotExistError)

    member = frappe.get_doc("Member", member_name)

    # Get form data
    form_data = frappe.local.form_dict

    # Validate required fields
    first_name = form_data.get("first_name", "").strip()
    last_name = form_data.get("last_name", "").strip()

    if not first_name:
        frappe.throw(_("First name is required"))

    if not last_name:
        frappe.throw(_("Last name is required"))

    # Validate name format
    if not validate_name_format(first_name):
        frappe.throw(_("First name contains invalid characters"))

    if not validate_name_format(last_name):
        frappe.throw(_("Last name contains invalid characters"))

    # Validate middle name if provided
    middle_name = form_data.get("middle_name", "").strip()
    if middle_name and not validate_name_format(middle_name, allow_prefixes=True):
        frappe.throw(_("Middle name contains invalid characters"))

    # Validate contact number if provided
    contact_number = form_data.get("contact_number", "").strip()
    if contact_number and not validate_phone_number(contact_number):
        frappe.throw(_("Please enter a valid phone number"))

    # Validate birth date if provided
    birth_date = form_data.get("birth_date", "").strip()
    if birth_date:
        try:
            from frappe.utils import getdate

            birth_date_obj = getdate(birth_date)
            if birth_date_obj >= getdate(today()):
                frappe.throw(_("Birth date cannot be in the future"))
        except Exception:
            frappe.throw(_("Please enter a valid birth date"))

    # Handle pronouns
    pronouns = form_data.get("pronouns", "").strip()
    custom_pronouns = form_data.get("custom_pronouns", "").strip()

    if pronouns == "custom":
        if not custom_pronouns:
            frappe.throw(_("Please specify your preferred pronouns"))
        final_pronouns = custom_pronouns
    else:
        final_pronouns = pronouns

    # Validate pronouns
    if final_pronouns and not validate_pronouns(final_pronouns):
        frappe.throw(_("Pronouns contain invalid characters"))

    # Check what has changed
    changes = track_changes(
        member,
        {
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "birth_date": birth_date,
            "contact_number": contact_number,
            "pronouns": final_pronouns,
            "allow_directory_listing": cint(form_data.get("allow_directory_listing", 0)),
            "allow_photo_usage": cint(form_data.get("allow_photo_usage", 0)),
        },
    )

    # Handle image upload/removal
    image_changes = handle_image_update(member, form_data)
    if image_changes:
        changes.update(image_changes)

    if not changes:
        frappe.msgprint(_("No changes detected"))
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/personal_details"
        return

    # Apply changes
    try:
        apply_personal_details_changes(member, changes)

        # Prepare success message
        success_message = prepare_success_message(changes)

        # Store success message in session
        frappe.session["personal_details_success"] = success_message

        # Redirect back to form with success message
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/personal_details"

    except Exception as e:
        frappe.log_error(f"Personal details update failed: {str(e)}")
        frappe.throw(_("Failed to update personal details. Please try again or contact support."))


def validate_name_format(name, allow_prefixes=False):
    """Validate name format - letters, spaces, hyphens, apostrophes"""
    if allow_prefixes:
        # Allow prefixes like van, de, von, etc.
        pattern = r"^[a-zA-ZÀ-ÿ\s\-'\.]+$"
    else:
        pattern = r"^[a-zA-ZÀ-ÿ\s\-']+$"

    return bool(re.match(pattern, name))


def validate_phone_number(phone):
    """Validate phone number format"""
    # Remove spaces and common separators
    # clean_phone = re.sub(r"[\s\-\(\)]", "", phone)  # Unused

    # Basic validation - starts with + or digits, contains only digits and +
    pattern = r"^(\+|00)?[\d\s\-\(\)\.]{7,15}$"
    return bool(re.match(pattern, phone))


def validate_pronouns(pronouns):
    """Validate pronouns format"""
    # Allow letters, slashes, spaces, common punctuation
    pattern = r"^[a-zA-Z\s\/\-,\.]+$"
    return bool(re.match(pattern, pronouns))


def track_changes(member, new_data):
    """Track what fields have changed"""
    changes = {}

    for field, new_value in new_data.items():
        current_value = getattr(member, field, None)

        # Handle empty strings vs None
        if current_value is None:
            current_value = ""
        if new_value is None:
            new_value = ""

        # Convert to string for comparison
        current_str = str(current_value).strip()
        new_str = str(new_value).strip()

        if current_str != new_str:
            changes[field] = {"old": current_value, "new": new_value}

    return changes


def handle_image_update(member, form_data):
    """Handle profile image upload or removal"""
    changes = {}

    # Check if image should be removed
    remove_image = form_data.get("remove_image")
    if remove_image and member.image:
        changes["image"] = {"old": member.image, "new": None, "action": "remove"}
        return changes

    # Check for new image upload
    if hasattr(frappe.local, "uploaded_file") and frappe.local.uploaded_file:
        uploaded_file = frappe.local.uploaded_file[0]

        # Validate file
        if not uploaded_file.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
            frappe.throw(_("Please upload a valid image file (JPG, PNG, GIF)"))

        if uploaded_file.file_size > 5 * 1024 * 1024:  # 5MB
            frappe.throw(_("Image file size must be less than 5MB"))

        # Save the file
        try:
            file_doc = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": uploaded_file.filename,
                    "attached_to_doctype": "Member",
                    "attached_to_name": member.name,
                    "content": uploaded_file.content,
                    "decode": False,
                }
            )
            file_doc.save()

            changes["image"] = {"old": member.image, "new": file_doc.file_url, "action": "upload"}

        except Exception as e:
            frappe.log_error(f"Image upload failed: {str(e)}")
            frappe.throw(_("Failed to upload image. Please try again."))

    return changes


def apply_personal_details_changes(member, changes):
    """Apply the tracked changes to the member document"""

    # Update basic fields
    for field, change in changes.items():
        if field != "image":  # Handle image separately
            setattr(member, field, change["new"])

    # Handle image changes
    if "image" in changes:
        image_change = changes["image"]
        if image_change["action"] == "remove":
            member.image = None
        elif image_change["action"] == "upload":
            member.image = image_change["new"]

    # Update full name if name fields changed
    name_fields = ["first_name", "middle_name", "last_name"]
    if any(field in changes for field in name_fields):
        # Construct full name
        name_parts = []
        if member.first_name:
            name_parts.append(member.first_name)
        if member.middle_name:
            name_parts.append(member.middle_name)
        if member.last_name:
            name_parts.append(member.last_name)

        member.full_name = " ".join(name_parts)

    # Save the member document
    member.save(ignore_permissions=True)

    # Log the changes for audit
    log_personal_details_changes(member.name, changes)


def log_personal_details_changes(member_name, changes):
    """Log personal details changes for audit purposes"""

    change_descriptions = []

    for field, change in changes.items():
        if field == "image":
            if change["action"] == "remove":
                change_descriptions.append("Removed profile image")
            elif change["action"] == "upload":
                change_descriptions.append("Updated profile image")
        else:
            field_label = get_field_label(field)
            change_descriptions.append(f"Changed {field_label}: '{change['old']}' → '{change['new']}'")

    frappe.logger().info(
        f"Personal details updated for member {member_name} by {frappe.session.user}: "
        f"{'; '.join(change_descriptions)}"
    )


def get_field_label(field):
    """Get user-friendly field labels"""
    labels = {
        "first_name": "First Name",
        "middle_name": "Middle Name",
        "last_name": "Last Name",
        "birth_date": "Birth Date",
        "contact_number": "Contact Number",
        "pronouns": "Pronouns",
        "allow_directory_listing": "Directory Listing",
        "allow_photo_usage": "Photo Usage Permission",
    }
    return labels.get(field, field.replace("_", " ").title())


def prepare_success_message(changes):
    """Prepare success message based on changes made"""

    messages = []

    # Count types of changes
    name_changes = sum(1 for field in changes.keys() if field in ["first_name", "middle_name", "last_name"])
    contact_changes = sum(1 for field in changes.keys() if field in ["contact_number"])
    preference_changes = sum(
        1 for field in changes.keys() if field in ["pronouns", "allow_directory_listing", "allow_photo_usage"]
    )
    image_changes = "image" in changes

    if name_changes:
        messages.append(_("Your name information has been updated"))

    if contact_changes:
        messages.append(_("Your contact information has been updated"))

    if preference_changes:
        messages.append(_("Your preferences have been updated"))

    if image_changes:
        if changes["image"]["action"] == "remove":
            messages.append(_("Your profile image has been removed"))
        else:
            messages.append(_("Your profile image has been updated"))

    if "birth_date" in changes:
        messages.append(_("Your birth date has been updated"))

    return messages
