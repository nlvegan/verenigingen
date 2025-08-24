"""
IBAN History Manager

Utility functions for managing IBAN history for members
"""
import frappe
from frappe import _
from frappe.utils import today


@frappe.whitelist()
def create_initial_iban_history(member_name):
    """
    Create initial IBAN history for a member if they have IBAN details

    This should be called:
    1. During application approval for application members
    2. Manually after creating a direct member with IBAN

    Args:
        member_name: Name of the member document

    Returns:
        dict: Success status and message
    """
    try:
        member = frappe.get_doc("Member", member_name)

        # Check if member has IBAN
        if not hasattr(member, "iban") or not member.iban:
            return {"success": False, "message": "Member has no IBAN to track"}

        # Check if IBAN history already exists
        existing_count = frappe.db.count("Member IBAN History", filters={"parent": member_name})
        if existing_count > 0:
            return {"success": False, "message": "IBAN history already exists for this member"}

        # Use "Other" as the reason for initial setup
        reason = "Other"

        # Create IBAN history record via parent document
        member_doc = frappe.get_doc("Member", member_name)
        member_doc.append("iban_history", {
            "iban": member.iban,
            "bic": getattr(member, "bic", None),
            "bank_account_name": getattr(member, "bank_account_name", None),
            "from_date": today(),
            "is_active": 1,
            "changed_by": frappe.session.user,
            "change_reason": reason,
        })
        member_doc.save(ignore_permissions=True)

        frappe.logger().info(f"Created initial IBAN history for member {member_name}")

        return {
            "success": True,
            "message": "Initial IBAN history created for {member_name}",
            "history_name": history_doc.name,
        }

    except Exception as e:
        frappe.logger().error(f"Error creating IBAN history for {member_name}: {str(e)}")
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
def get_iban_history(member_name):
    """
    Get IBAN history for a member

    Args:
        member_name: Name of the member document

    Returns:
        list: List of IBAN history records
    """
    try:
        history = frappe.get_all(
            "Member IBAN History",
            filters={"parent": member_name},
            fields=[
                "iban",
                "bic",
                "bank_account_name",
                "from_date",
                "to_date",
                "is_active",
                "changed_by",
                "change_reason",
                "notes",
            ],
            order_by="from_date desc",
        )

        return history

    except Exception as e:
        frappe.logger().error(f"Error fetching IBAN history for {member_name}: {str(e)}")
        return []


def track_iban_change(member_doc):
    """
    Track IBAN change for a member (called from payment_mixin)

    Args:
        member_doc: Member document object
    """
    try:
        # Get old IBAN from database
        old_iban = frappe.db.get_value("Member", member_doc.name, "iban")

        if old_iban and old_iban != member_doc.iban:
            # Close the previous IBAN history record
            history_records = frappe.get_all(
                "Member IBAN History", filters={"parent": member_doc.name, "is_active": 1}, fields=["name"]
            )

            for record in history_records:
                frappe.db.set_value("Member IBAN History", record.name, {"is_active": 0, "to_date": today()})

            # Add new IBAN history record via parent document
            member_doc.append("iban_history", {
                "iban": member_doc.iban,
                "bic": getattr(member_doc, "bic", None),
                "bank_account_name": getattr(member_doc, "bank_account_name", None),
                "from_date": today(),
                "is_active": 1,
                "changed_by": frappe.session.user,
                "change_reason": "Bank Change",
            })
            member_doc.save(ignore_permissions=True)

            # Log the change
            frappe.logger().info(
                "IBAN changed for member {member_doc.name} from {old_iban} to {member_doc.iban}"
            )

            # Check if SEPA mandates need to be updated
            if hasattr(member_doc, "payment_method") and member_doc.payment_method == "SEPA Direct Debit":
                frappe.msgprint(
                    _("IBAN has been changed. Please review SEPA mandates as they may need to be updated."),
                    indicator="orange",
                    alert=True,
                )

    except Exception as e:
        frappe.logger().error(f"Error tracking IBAN change for member {member_doc.name}: {str(e)}")
