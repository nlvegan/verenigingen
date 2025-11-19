"""
Simple API endpoint to check donation status for testing
"""

import frappe


@frappe.whitelist(allow_guest=True)
def check_donation_status(donation_name):
    """Check the status of a donation including Payment Entries and payment history"""

    try:
        donation = frappe.get_doc("Donation", donation_name)

        # Get payment entries via Payment Entry Reference child table
        payment_refs = frappe.get_all(
            "Payment Entry Reference", filters={"reference_name": donation.name}, fields=["parent"]
        )

        payment_entries = []
        for ref in payment_refs:
            pe = frappe.get_doc("Payment Entry", ref.parent)
            payment_entries.append(
                {
                    "name": pe.name,
                    "paid_amount": pe.paid_amount,
                    "posting_date": pe.posting_date,
                    "naming_series": pe.naming_series,
                }
            )

        result = {
            "donation": {
                "name": donation.name,
                "status": donation.status,
                "paid": donation.paid,
                "payment_id": donation.payment_id,
                "amount": donation.amount,
            },
            "payment_history": [],
            "payment_entries": payment_entries,
        }

        # Get payment history from child table
        if donation.payments:
            for payment in donation.payments:
                result["payment_history"].append(
                    {
                        "payment_date": str(payment.payment_date),
                        "amount": payment.amount,
                        "payment_status": payment.payment_status,
                        "mollie_payment_id": payment.mollie_payment_id,
                    }
                )

        return {"status": "success", "data": result}

    except frappe.DoesNotExistError:
        return {"status": "error", "message": f"Donation {donation_name} not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
