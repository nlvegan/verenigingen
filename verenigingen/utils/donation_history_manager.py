"""
Donation History Manager for tracking donation history on donor records
"""


import frappe


class DonationHistoryManager:
    """Manages donation history tracking for donor records"""

    def __init__(self, donor_name: str):
        self.donor_name = donor_name
        self.donor_doc = None

    def get_donor_doc(self):
        """Get donor document"""
        if not self.donor_doc:
            self.donor_doc = frappe.get_doc("Donor", self.donor_name)
        return self.donor_doc

    def sync_donation_history(self):
        """Sync donation history from actual donation records"""
        try:
            donor = self.get_donor_doc()

            # Get all donations for this donor
            donations = frappe.get_all(
                "Donation",
                filters={"donor": self.donor_name},
                fields=[
                    "name",
                    "donation_date",
                    "amount",
                    "payment_method",
                    "status",
                    "fund_designation",
                    "donation_purpose",
                    "paid",
                    "docstatus",
                ],
                order_by="donation_date desc",
            )

            # Clear existing history
            donor.donor_history = []

            # Add each donation to history
            for donation in donations:
                # Only include submitted donations or valid drafts
                if donation.docstatus == 1 or (donation.docstatus == 0 and donation.amount):
                    donor.append(
                        "donor_history",
                        {
                            "donation_reference": donation.name,
                            "donation_date": donation.date,
                            "donation_amount": donation.amount,
                            "payment_method": donation.payment_method,
                            "donation_status": donation.donation_status,
                            "fund_designation": donation.fund_designation,
                            "donation_purpose": donation.donation_purpose,
                            "paid": donation.paid,
                        },
                    )

            # Save without triggering hooks to avoid recursion
            donor.save(ignore_permissions=True)

            return {
                "success": True,
                "donations_synced": len(donations),
                "message": "Synced {len(donations)} donations to donor history",
            }

        except Exception as e:
            frappe.log_error(f"Error syncing donation history for donor {self.donor_name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def add_donation_entry(self, donation_doc):
        """Add a single donation entry to history"""
        try:
            donor = self.get_donor_doc()

            # Check if entry already exists
            existing_entry = None
            for entry in donor.donor_history:
                if entry.donation_reference == donation_doc.name:
                    existing_entry = entry
                    break

            # Update existing entry or create new one
            if existing_entry:
                existing_entry.donation_date = donation_doc.date
                existing_entry.donation_amount = donation_doc.amount
                existing_entry.payment_method = donation_doc.payment_method
                existing_entry.donation_status = donation_doc.donation_status
                existing_entry.fund_designation = donation_doc.fund_designation
                existing_entry.donation_purpose = donation_doc.donation_purpose
                existing_entry.paid = donation_doc.paid
            else:
                donor.append(
                    "donor_history",
                    {
                        "donation_reference": donation_doc.name,
                        "donation_date": donation_doc.date,
                        "donation_amount": donation_doc.amount,
                        "payment_method": donation_doc.payment_method,
                        "donation_status": donation_doc.donation_status,
                        "fund_designation": donation_doc.fund_designation,
                        "donation_purpose": donation_doc.donation_purpose,
                        "paid": donation_doc.paid,
                    },
                )

            # Sort by date (most recent first)
            donor.donor_history = sorted(donor.donor_history, key=lambda x: x.donation_date, reverse=True)

            donor.save(ignore_permissions=True)

            return {
                "success": True,
                "action": "updated" if existing_entry else "added",
                "donation": donation_doc.name,
            }

        except Exception as e:
            frappe.log_error(f"Error adding donation entry to history: {str(e)}")
            return {"success": False, "error": str(e)}

    def remove_donation_entry(self, donation_name: str):
        """Remove a donation entry from history"""
        try:
            donor = self.get_donor_doc()

            # Find and remove the entry
            for i, entry in enumerate(donor.donor_history):
                if entry.donation_reference == donation_name:
                    donor.donor_history.pop(i)
                    break

            donor.save(ignore_permissions=True)

            return {"success": True, "message": f"Removed donation {donation_name} from history"}

        except Exception as e:
            frappe.log_error(f"Error removing donation entry from history: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_donation_summary(self):
        """Get donation summary statistics"""
        try:
            donor = self.get_donor_doc()

            if not donor.donor_history:
                return {
                    "total_donations": 0,
                    "total_amount": 0,
                    "paid_amount": 0,
                    "unpaid_amount": 0,
                    "last_donation_date": None,
                    "payment_methods": {},
                }

            total_amount = sum(float(entry.donation_amount or 0) for entry in donor.donor_history)
            paid_amount = sum(
                float(entry.donation_amount or 0) for entry in donor.donor_history if entry.paid
            )
            unpaid_amount = total_amount - paid_amount

            # Count payment methods
            payment_methods = {}
            for entry in donor.donor_history:
                method = entry.payment_method or "Unknown"
                payment_methods[method] = payment_methods.get(method, 0) + 1

            # Get last donation date
            last_donation_date = None
            if donor.donor_history:
                last_donation_date = max(
                    entry.donation_date for entry in donor.donor_history if entry.donation_date
                )

            return {
                "total_donations": len(donor.donor_history),
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "unpaid_amount": unpaid_amount,
                "last_donation_date": last_donation_date,
                "payment_methods": payment_methods,
            }

        except Exception as e:
            frappe.log_error(f"Error getting donation summary: {str(e)}")
            return {"error": str(e)}


@frappe.whitelist()
def sync_all_donor_histories():
    """Sync donation history for all donors"""
    try:
        donors = frappe.get_all("Donor", fields=["name"])

        success_count = 0
        error_count = 0

        for donor in donors:
            manager = DonationHistoryManager(donor.name)
            result = manager.sync_donation_history()

            if result["success"]:
                success_count += 1
            else:
                error_count += 1

        return {
            "success": True,
            "donors_processed": len(donors),
            "successful_syncs": success_count,
            "failed_syncs": error_count,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def sync_donor_history(donor_name):
    """Sync donation history for a specific donor"""
    manager = DonationHistoryManager(donor_name)
    return manager.sync_donation_history()


@frappe.whitelist()
def get_donor_summary(donor_name):
    """Get donation summary for a donor"""
    manager = DonationHistoryManager(donor_name)
    return manager.get_donation_summary()


# Document event hooks for automatic history management
def on_donation_insert(doc, method):
    """Called when a new donation is created"""
    if doc.donor:
        manager = DonationHistoryManager(doc.donor)
        manager.add_donation_entry(doc)


def on_donation_update(doc, method):
    """Called when a donation is updated"""
    if doc.donor:
        manager = DonationHistoryManager(doc.donor)
        manager.add_donation_entry(doc)


def on_donation_submit(doc, method):
    """Called when a donation is submitted"""
    if doc.donor:
        manager = DonationHistoryManager(doc.donor)
        manager.add_donation_entry(doc)


def on_donation_cancel(doc, method):
    """Called when a donation is cancelled"""
    if doc.donor:
        manager = DonationHistoryManager(doc.donor)
        manager.add_donation_entry(doc)  # Update status but keep in history


def on_donation_delete(doc, method):
    """Called when a donation is deleted"""
    if doc.donor:
        manager = DonationHistoryManager(doc.donor)
        manager.remove_donation_entry(doc.name)
