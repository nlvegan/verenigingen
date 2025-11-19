"""
Migration helper for transitioning to event-driven payment history updates

This module provides utilities to ensure smooth transition and backwards compatibility.
"""

import frappe
from frappe import _


def ensure_payment_history_current():
    """
    One-time migration to ensure all member payment histories are current
    after switching to the event-driven system.
    """
    members_with_customers = frappe.get_all(
        "Member", filters={"customer": ["!=", ""]}, fields=["name", "customer"], limit=0  # Get all
    )

    total = len(members_with_customers)
    success_count = 0
    error_count = 0

    frappe.logger("migration").info(f"Starting payment history migration for {total} members")

    for idx, member_data in enumerate(members_with_customers):
        try:
            member = frappe.get_doc("Member", member_data.name)

            # Force reload payment history
            if hasattr(member, "load_payment_history"):
                member.load_payment_history()
                # Note: load_payment_history already saves the document
                success_count += 1
            else:
                frappe.log_error(
                    f"Member {member_data.name} missing load_payment_history method",
                    "Payment History Migration Warning",
                )
                error_count += 1

            # Progress logging
            if (idx + 1) % 100 == 0:
                frappe.logger("migration").info(f"Processed {idx + 1}/{total} members")
                frappe.db.commit()

        except Exception as e:
            error_count += 1
            frappe.log_error(
                f"Failed to update payment history for member {member_data.name}: {str(e)}",
                "Payment History Migration Error",
            )

    frappe.logger("migration").info(
        f"Payment history migration completed. Success: {success_count}, Errors: {error_count}"
    )

    return {"total": total, "success": success_count, "errors": error_count}


@frappe.whitelist()
def test_event_system():
    """Test function to verify the event system is working"""
    try:
        # Create a test invoice submission event
        test_event_data = {
            "invoice": "TEST-INV-001",
            "customer": "TEST-CUSTOMER",
            "posting_date": frappe.utils.today(),
            "grand_total": 100.00,
            "status": "Unpaid",
        }

        # Import here to avoid circular imports
        from verenigingen.events.invoice_events import _emit_invoice_event

        # Emit test event
        _emit_invoice_event("invoice_submitted", test_event_data)

        return {
            "status": "success",
            "message": "Test event emitted successfully. Check background jobs for processing.",
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
