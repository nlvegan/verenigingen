"""
Sales Invoice hooks to automatically populate member field and chapter
"""

import frappe

from verenigingen.utils.chapter_utils import get_member_primary_chapter


def set_member_from_customer(doc, method):
    """
    Automatically set member field on Sales Invoice from Customer
    Called on before_save and before_validate
    """
    if doc.customer and not doc.get("member"):
        # Fetch member from customer
        member = frappe.db.get_value("Customer", doc.customer, "member")
        if member:
            doc.member = member


def populate_member_chapter(doc, method=None):
    """
    Auto-populate custom_member_chapter field on Sales Invoice.

    Called before_validate to capture member's chapter at time of invoice creation.
    This ensures accurate dues split reporting even if member changes chapters later.

    Args:
        doc: Sales Invoice document
        method: Event method name (not used)
    """
    # Only populate if not already set
    if hasattr(doc, "custom_member_chapter") and doc.custom_member_chapter:
        return

    # Check if customer is provided
    if not doc.customer:
        return

    # Validate custom_member_chapter field exists (defensive check)
    if not hasattr(doc, "custom_member_chapter"):
        frappe.logger().warning(
            "custom_member_chapter field not found on Sales Invoice - "
            "ensure custom field is installed via fixtures"
        )
        return

    try:
        # Check if this customer is linked to a Member
        member_name = frappe.db.get_value("Member", {"customer": doc.customer}, "name")

        if not member_name:
            # Not a member invoice, skip silently
            return

        # Get member's primary chapter
        try:
            chapter_name = get_member_primary_chapter(member_name)

            if chapter_name:
                # Validate chapter exists before setting
                if frappe.db.exists("Chapter", chapter_name):
                    doc.custom_member_chapter = chapter_name
                    frappe.logger().debug(
                        f"Auto-populated chapter '{chapter_name}' for Sales Invoice to member {member_name}"
                    )
                else:
                    frappe.logger().warning(
                        f"Chapter '{chapter_name}' returned for member {member_name} but does not exist in database"
                    )
            else:
                # Member has no active chapter - this is valid, just log for tracking
                frappe.logger().debug(
                    f"Member {member_name} has no active chapter membership - Sales Invoice will not be included in chapter dues split"
                )

        except frappe.DoesNotExistError as e:
            # Specific handling for missing DocType records
            frappe.logger().error(
                f"Database record not found while looking up chapter for member {member_name}: {str(e)}"
            )
        except frappe.ValidationError as e:
            # Validation errors during chapter lookup
            frappe.logger().error(
                f"Validation error during chapter lookup for member {member_name}: {str(e)}"
            )

    except frappe.DoesNotExistError:
        # Member DocType or Customer record doesn't exist
        frappe.logger().warning(f"Customer '{doc.customer}' does not exist or Member DocType not available")
    except Exception as e:
        # Catch-all for unexpected errors - don't fail invoice creation
        frappe.logger().error(
            f"Unexpected error populating member chapter for Sales Invoice {getattr(doc, 'name', 'new')}, "
            f"Customer {doc.customer}: {str(e)}",
            exc_info=True,  # Include full traceback for debugging
        )
