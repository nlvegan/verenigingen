"""
Portal customization utilities for member-focused portal configuration
"""

import frappe


@frappe.whitelist()
def setup_member_portal_menu():
    """Configure portal menu for association members - disable ERP items, add member items"""
    try:
        portal_settings = frappe.get_single("Portal Settings")

        # Items to disable (ERP/business-focused)
        erp_items_to_disable = [
            "Request for Quotations",
            "Supplier Quotation",
            "Purchase Orders",
            "Purchase Invoices",
            "Invoices",
            "Timesheets",
            "Material Request",
            "Quotations",
            "Orders",
            "Shipments",
        ]

        # Disable ERP items
        disabled_count = 0
        for item in portal_settings.menu:
            if item.title in erp_items_to_disable:
                item.enabled = 0
                disabled_count += 1

        # Items to ensure are enabled (association-relevant)
        association_items = {
            "Issues & Support": {"role": "Customer", "enabled": 1},
            "Addresses": {"role": "", "enabled": 1},
            "Projects": {"role": "Customer", "enabled": 1},
            "Newsletter": {"role": "", "enabled": 1},
        }

        # Enable association items
        enabled_count = 0
        for item in portal_settings.menu:
            if item.title in association_items:
                item.enabled = 1
                if association_items[item.title].get("role"):
                    item.role = association_items[item.title]["role"]
                enabled_count += 1

        # Add custom member/volunteer items if not present
        custom_items = [
            {
                "title": "Member Portal",
                "route": "/member_portal",
                "reference_doctype": "",
                "role": "Verenigingen Member",
                "enabled": 1,
            },
            {
                "title": "My Memberships",
                "route": "/memberships",
                "reference_doctype": "Membership",
                "role": "Verenigingen Member",
                "enabled": 1,
            },
            {
                "title": "Volunteer Portal",
                "route": "/volunteer_portal",
                "reference_doctype": "",
                "role": "Verenigingen Volunteer",
                "enabled": 1,
            },
            {
                "title": "My Expenses",
                "route": "/my_expenses",
                "reference_doctype": "Volunteer Expense",
                "role": "Verenigingen Volunteer",
                "enabled": 1,
            },
            {
                "title": "My Addresses",
                "route": "/my_addresses",
                "reference_doctype": "Address",
                "role": "",
                "enabled": 1,
            },
        ]

        # Check which custom items already exist
        existing_titles = [item.title for item in portal_settings.menu]
        added_count = 0

        for custom_item in custom_items:
            if custom_item["title"] not in existing_titles:
                portal_settings.append("menu", custom_item)
                added_count += 1

        # Save changes
        portal_settings.save(ignore_permissions=True)
        frappe.db.commit()

        # Clear cache
        frappe.clear_cache()

        return {
            "success": True,
            "message": "Portal menu updated: {disabled_count} ERP items disabled, {enabled_count} association items verified, {added_count} custom items added",
            "disabled_count": disabled_count,
            "enabled_count": enabled_count,
            "added_count": added_count,
        }

    except Exception as e:
        frappe.log_error(f"Error setting up member portal menu: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def reset_portal_menu_to_member_only():
    """Reset portal menu to only show member/volunteer relevant items"""
    try:
        portal_settings = frappe.get_single("Portal Settings")

        # Define which items should be kept for members
        member_relevant_items = [
            "Member Portal",
            "My Memberships",
            "Volunteer Portal",
            "My Expenses",
            "My Addresses",
            "Issues & Support",
            "Addresses",
            "Projects",
            "Newsletter",
        ]

        # Disable all items first
        for item in portal_settings.menu:
            item.enabled = 0

        # Enable only member-relevant items
        enabled_count = 0
        for item in portal_settings.menu:
            if item.title in member_relevant_items:
                item.enabled = 1
                enabled_count += 1

        # Add missing items
        existing_titles = [item.title for item in portal_settings.menu]

        new_items = [
            {
                "title": "Member Portal",
                "route": "/member_portal",
                "reference_doctype": "",
                "role": "Verenigingen Member",
                "enabled": 1,
            },
            {
                "title": "Volunteer Portal",
                "route": "/volunteer_portal",
                "reference_doctype": "",
                "role": "Verenigingen Volunteer",
                "enabled": 1,
            },
        ]

        added_count = 0
        for item in new_items:
            if item["title"] not in existing_titles:
                portal_settings.append("menu", item)
                added_count += 1

        # Save
        portal_settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache()

        return {
            "success": True,
            "message": "Portal menu reset to member-only view: {enabled_count} items enabled, {added_count} items added",
            "enabled_count": enabled_count,
            "added_count": added_count,
        }

    except Exception as e:
        frappe.log_error(f"Error resetting portal menu: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_clean_member_portal_menu():
    """Get a clean list of portal menu items relevant for members"""
    try:
        portal_settings = frappe.get_single("Portal Settings")
        user_roles = frappe.get_roles(frappe.session.user)

        # Filter for enabled items that are relevant to members
        clean_menu = []

        for item in portal_settings.menu:
            if not item.enabled:
                continue

            # Check role-based access
            if item.role and item.role not in user_roles:
                continue

            # Add to clean menu
            clean_menu.append(
                {
                    "title": item.title,
                    "route": item.route,
                    "reference_doctype": item.reference_doctype,
                    "role": item.role,
                }
            )

        return {"success": True, "menu_items": clean_menu, "user_roles": user_roles}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_current_portal_usage():
    """Analyze which portal menu items are actually being used"""
    try:
        # Get all enabled portal menu items
        portal_settings = frappe.get_single("Portal Settings")

        analysis = []

        for item in portal_settings.menu:
            if not item.enabled:
                continue

            item_analysis = {
                "title": item.title,
                "route": item.route,
                "role": item.role,
                "reference_doctype": item.reference_doctype,
                "is_erp_focused": False,
                "is_member_relevant": False,
                "recommendation": "",
            }

            # Categorize items
            erp_items = [
                "Request for Quotations",
                "Supplier Quotation",
                "Purchase Orders",
                "Purchase Invoices",
                "Invoices",
                "Timesheets",
                "Material Request",
                "Quotations",
                "Orders",
                "Shipments",
            ]

            member_items = [
                "Member Portal",
                "My Memberships",
                "Volunteer Portal",
                "My Expenses",
                "My Addresses",
                "Issues & Support",
                "Addresses",
                "Projects",
                "Newsletter",
            ]

            if item.title in erp_items:
                item_analysis["is_erp_focused"] = True
                item_analysis["recommendation"] = "Disable - Not relevant for association members"
            elif item.title in member_items:
                item_analysis["is_member_relevant"] = True
                item_analysis["recommendation"] = "Keep - Useful for members/volunteers"
            else:
                item_analysis["recommendation"] = "Review - Check if needed for members"

            analysis.append(item_analysis)

        return {"success": True, "total_items": len(analysis), "analysis": analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_member_info(user_email):
    """Get member information for the given user email"""
    try:
        member = frappe.get_all(
            "Member",
            filters={"email": user_email},
            fields=[
                "name",
                "member_id",
                "first_name",
                "last_name",
                "full_name",
                "member_since",
                "email",
            ],
            limit=1,
        )
        if member:
            return member[0]
    except Exception:
        pass
    return None


def get_member_context(context):
    """Add member-specific context to portal pages"""
    if frappe.session.user != "Guest":
        context.member = get_member_info(frappe.session.user) or {}
    else:
        context.member = {}

    return context


def add_brand_body_classes(context):
    """Add body classes for brand-specific styling on portal pages

    This function adds CSS classes to the body element to enable proper
    scoping of brand colors and styles on portal pages.
    """
    # Get existing body_class or initialize as empty string
    body_class = context.get("body_class", "")

    # Add base portal class
    portal_classes = ["portal-page"]

    # Check if this is a verenigingen portal page
    path = context.get("path", "")
    pathname = context.get("pathname", "")

    # Add verenigingen-specific class if applicable
    verenigingen_paths = [
        "member_portal",
        "member_dashboard",
        "volunteer_portal",
        "my_addresses",
        "personal_details",
        "payment_dashboard",
        "chapter_dashboard",
        "my_teams",
        "team_members",
        "bank_details",
        "apply_for_membership",
        "donate",
        "contact_request",
        "chapter_join",
        "me",
    ]

    # Check if current path matches any verenigingen portal paths
    for vpath in verenigingen_paths:
        if vpath in path or vpath in pathname:
            portal_classes.append("verenigingen-portal")
            break

    # Check if user is a member
    if frappe.session.user != "Guest":
        # Check if user has member role
        roles = frappe.get_roles(frappe.session.user)
        if "Verenigingen Member" in roles:
            portal_classes.append("member-portal")
        if "Verenigingen Volunteer" in roles:
            portal_classes.append("volunteer-portal")

    # Get active brand settings to add brand-specific class
    try:
        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_active_brand_settings

        brand_settings = get_active_brand_settings()
        if brand_settings and brand_settings.get("settings_name"):
            # Convert brand name to CSS-friendly class
            brand_class = "brand-" + frappe.scrub(brand_settings["settings_name"])
            portal_classes.append(brand_class)
    except Exception:
        # If brand settings fail, continue without brand class
        pass

    # Combine existing and new classes
    if body_class:
        all_classes = body_class + " " + " ".join(portal_classes)
    else:
        all_classes = " ".join(portal_classes)

    # Set the body_class in context
    context["body_class"] = all_classes

    # Also add a data attribute for more specific targeting
    context["data_portal_page"] = "true"

    return context
