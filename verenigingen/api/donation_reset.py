"""
Reset donation for webhook testing
"""
import frappe


@frappe.whitelist(allow_guest=True)
def reset_donation_for_testing(donation_name):
    """Reset donation payment status for testing webhook"""

    try:
        donation = frappe.get_doc("Donation", donation_name)

        # Reset payment status
        donation.db_set("paid", 0)
        donation.db_set("status", "Promised")

        # Clear payment history if any
        if donation.payments:
            donation.payments = []
            donation.save()

        # Delete any Payment Entries
        payment_refs = frappe.get_all(
            "Payment Entry Reference", filters={"reference_name": donation.name}, fields=["parent"]
        )

        for ref in payment_refs:
            pe = frappe.get_doc("Payment Entry", ref.parent)
            pe.cancel()
            pe.delete()

        frappe.db.commit()

        return {
            "status": "success",
            "message": f"Reset donation {donation_name} for testing",
            "donation": {"name": donation.name, "paid": donation.paid, "status": donation.status},
        }

    except Exception as e:
        frappe.db.rollback()
        return {"status": "error", "message": str(e)}
