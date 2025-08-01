"""
Custom Document Links Setup

This module adds custom document links to core doctypes like Expense Claim
to provide better integration with the Verenigingen association management system.
"""

import frappe


def setup_custom_document_links(bootinfo=None):
    """Setup custom document links for better navigation between related records"""

    try:
        # Add Member Ledger link to Expense Claim
        add_member_ledger_link_to_expense_claim()

    except Exception as e:
        frappe.log_error(f"Error setting up custom document links: {str(e)}", "Document Links Setup")


def add_member_ledger_link_to_expense_claim():
    """Add a link from Expense Claim to Member record via Employee"""

    try:
        # Check if the link already exists
        existing_links = frappe.get_meta("Expense Claim").links or []

        # Check if our custom link already exists
        member_link_exists = any(
            link.get("link_doctype") == "Member" and link.get("link_fieldname") == "employee"
            for link in existing_links
        )

        if not member_link_exists:
            # Add the link
            new_link = {"link_doctype": "Member", "link_fieldname": "employee", "group": "Member Relations"}

            # Add to existing links
            existing_links.append(new_link)

            # Update the meta
            meta = frappe.get_meta("Expense Claim")
            meta.links = existing_links

            frappe.logger().info("Added Member ledger link to Expense Claim doctype")

    except Exception as e:
        frappe.log_error(f"Error adding Member link to Expense Claim: {str(e)}", "Document Links Setup")


def get_member_from_expense_claim(expense_claim):
    """Get member record from expense claim via employee"""

    try:
        if not expense_claim:
            return None

        # Get the expense claim document
        expense_doc = frappe.get_doc("Expense Claim", expense_claim)

        if not expense_doc.employee:
            return None

        # Find member with this employee
        member = frappe.db.get_value("Member", {"employee": expense_doc.employee}, "name")

        return member

    except Exception as e:
        frappe.log_error(f"Error getting member from expense claim {expense_claim}: {str(e)}")
        return None


@frappe.whitelist()
def test_document_links():
    """Test function to verify document links are working"""
    try:
        # Get an expense claim for testing
        expense_claim = frappe.db.get_value("Expense Claim", {"employee": ["!=", ""]}, "name")
        if not expense_claim:
            return {"success": False, "message": "No expense claim with employee found"}

        # Test the member lookup
        member = get_member_from_expense_claim(expense_claim)

        # Get expense claim details
        expense_doc = frappe.get_doc("Expense Claim", expense_claim)

        return {
            "success": True,
            "expense_claim": expense_claim,
            "employee": expense_doc.employee,
            "member_found": member,
            "message": f"Document link test: Expense {expense_claim} -> Employee {expense_doc.employee} -> Member {member or 'None'}",
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}
