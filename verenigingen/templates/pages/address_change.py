import re

import frappe
from frappe import _
from frappe.utils import validate_email_address


def get_context(context):
    """Get context for address change portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Get member record by email OR user field

    # First try by email
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member_name:
        # Then try by user field
        member_name = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

    if not member_name:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    # Get member document (may need ignore_permissions for portal users)
    try:
        context.member = frappe.get_doc("Member", member_name)
    except frappe.PermissionError:
        context.member = frappe.get_doc("Member", member_name, ignore_permissions=True)

    # Get current address if exists
    current_address = None
    if context.member.primary_address:
        try:
            current_address = frappe.get_doc("Address", context.member.primary_address)
        except frappe.PermissionError:
            # If permission denied, use database access
            try:
                current_address = frappe.get_doc(
                    "Address", context.member.primary_address, ignore_permissions=True
                )
            except frappe.DoesNotExistError:
                # Address was deleted, clear the reference
                frappe.db.set_value("Member", member_name, "primary_address", None)
                frappe.db.commit()
        except frappe.DoesNotExistError:
            # Address was deleted, clear the reference
            frappe.db.set_value("Member", member_name, "primary_address", None)
            frappe.db.commit()

    context.current_address = current_address

    # Ensure all address fields have default values for template
    if current_address:
        context.address_data = {
            "address_line1": current_address.address_line1 or "",
            "address_line2": current_address.address_line2 or "",
            "city": current_address.city or "",
            "state": current_address.state or "",
            "country": current_address.country or "",
            "pincode": current_address.pincode or "",
            "phone": current_address.phone or "",
            "email_id": current_address.email_id or "",
        }
    else:
        # No current address - provide empty defaults
        context.address_data = {
            "address_line1": "",
            "address_line2": "",
            "city": "",
            "state": "",
            "country": "Netherlands",  # Default to Netherlands for Dutch organization
            "pincode": "",
            "phone": "",
            "email_id": "",
        }

    # Get country list for dropdown
    context.countries = frappe.get_all("Country", fields=["name"], order_by="name")

    # Portal navigation
    context.show_sidebar = True
    context.portal_links = [
        {"title": _("Dashboard"), "route": "/member_portal"},
        {"title": _("Update Address"), "route": "/address_change"},
        {"title": _("Adjust Fee"), "route": "/membership_fee_adjustment"},
        {"title": _("Personal Details"), "route": "/personal_details"},
    ]

    context.page_title = _("Update Address")
    context.parent_template = "templates/web.html"

    return context


@frappe.whitelist()
def update_member_address(address_data):
    """Update member's address with the provided data"""

    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member record
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member_name:
        member_name = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

    if not member_name:
        frappe.throw(_("No member record found"), frappe.DoesNotExistError)

    # Parse address data
    if isinstance(address_data, str):
        import json

        address_data = json.loads(address_data)

    # Validate required fields
    required_fields = ["address_line1", "city", "country"]
    for field in required_fields:
        if not address_data.get(field, "").strip():
            frappe.throw(_("Field {0} is required").format(_(field.replace("_", " ").title())))

    # Validate postal code if provided (basic validation)
    pincode = address_data.get("pincode", "").strip()
    if pincode and not re.match(r"^[0-9A-Za-z\s-]{3,10}$", pincode):
        frappe.throw(_("Please enter a valid postal code"))

    # Validate email if provided
    email = address_data.get("email_id", "").strip()
    if email:
        try:
            validate_email_address(email)
        except frappe.ValidationError:
            frappe.throw(_("Please enter a valid email address"))

    # Validate phone if provided (basic validation)
    phone = address_data.get("phone", "").strip()
    if phone and not re.match(r"^[\+]?[0-9\s\-\(\)]{6,20}$", phone):
        frappe.throw(_("Please enter a valid phone number"))

    # Get member document (may need ignore_permissions for portal users)
    try:
        member_doc = frappe.get_doc("Member", member_name)
    except frappe.PermissionError:
        member_doc = frappe.get_doc("Member", member_name, ignore_permissions=True)

    try:
        # Check if member has existing address
        if member_doc.primary_address:
            # Update existing address
            try:
                address_doc = frappe.get_doc("Address", member_doc.primary_address)
            except frappe.PermissionError:
                # If permission denied, use database access
                address_doc = frappe.get_doc("Address", member_doc.primary_address, ignore_permissions=True)
            # old_address = {
            #     "address_line1": address_doc.address_line1,
            #     "address_line2": address_doc.address_line2 or "",
            #     "city": address_doc.city,
            #     "state": address_doc.state or "",
            #     "country": address_doc.country,
            #     "pincode": address_doc.pincode or "",
            #     "phone": address_doc.phone or "",
            #     "email_id": address_doc.email_id or "",
            # }  # Unused
        else:
            # No existing address
            address_doc = None

        # Create or update address
        if address_doc:
            # Update existing address
            address_doc.update(
                {
                    "address_line1": address_data.get("address_line1", "").strip(),
                    "address_line2": address_data.get("address_line2", "").strip(),
                    "city": address_data.get("city", "").strip(),
                    "state": address_data.get("state", "").strip(),
                    "country": address_data.get("country", "").strip(),
                    "pincode": pincode,
                    "phone": phone,
                    "email_id": email,
                }
            )
            address_doc.save(ignore_permissions=True)
            action = "updated"
        else:
            # Create new address
            address_doc = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": member_doc.full_name,
                    "address_type": "Personal",
                    "address_line1": address_data.get("address_line1", "").strip(),
                    "address_line2": address_data.get("address_line2", "").strip(),
                    "city": address_data.get("city", "").strip(),
                    "state": address_data.get("state", "").strip(),
                    "country": address_data.get("country", "").strip(),
                    "pincode": pincode,
                    "phone": phone,
                    "email_id": email,
                    "is_primary_address": 1,
                    "links": [{"link_doctype": "Member", "link_name": member_name}],
                }
            )
            address_doc.insert(ignore_permissions=True)

            # Link to member using database update to bypass permissions
            frappe.db.set_value("Member", member_name, "primary_address", address_doc.name)
            frappe.db.commit()
            action = "created"

        # Log the change
        frappe.logger().info(f"Address {action} for member {member_name}: {address_doc.name}")

        # Prepare response with formatted address using Dutch conventions
        from verenigingen.utils.address_formatter import format_address_for_country

        new_address_display = format_address_for_country(address_doc)

        return {
            "success": True,
            "message": _("Address {0} successfully").format(_(action)),
            "address_name": address_doc.name,
            "address_display": new_address_display,
            "action": action,
        }

    except Exception as e:
        frappe.log_error(f"Error updating address for member {member_name}: {str(e)}")
        frappe.throw(_("An error occurred while updating your address. Please try again."))


# Address formatting moved to verenigingen.utils.address_formatter


@frappe.whitelist()
def get_current_address():
    """Get current address for the logged-in member"""

    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.PermissionError)

    # Get member record
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member_name:
        member_name = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

    if not member_name:
        frappe.throw(_("No member record found"), frappe.DoesNotExistError)

    # Get member document (may need ignore_permissions for portal users)
    try:
        member_doc = frappe.get_doc("Member", member_name)
    except frappe.PermissionError:
        member_doc = frappe.get_doc("Member", member_name, ignore_permissions=True)

    if not member_doc.primary_address:
        return {"address": None}

    try:
        try:
            address_doc = frappe.get_doc("Address", member_doc.primary_address)
        except frappe.PermissionError:
            # If permission denied, use database access
            address_doc = frappe.get_doc("Address", member_doc.primary_address, ignore_permissions=True)

        return {
            "address": {
                "name": address_doc.name,
                "address_line1": address_doc.address_line1 or "",
                "address_line2": address_doc.address_line2 or "",
                "city": address_doc.city or "",
                "state": address_doc.state or "",
                "country": address_doc.country or "",
                "pincode": address_doc.pincode or "",
                "phone": address_doc.phone or "",
                "email_id": address_doc.email_id or "",
            }
        }
    except frappe.DoesNotExistError:
        # Address was deleted, clear the reference
        frappe.db.set_value("Member", member_name, "primary_address", None)
        frappe.db.commit()
        return {"address": None}
