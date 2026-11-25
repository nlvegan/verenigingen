"""A committed Donor with its synced Customer, shared by the unlink_donor_customer WSGI tests.

Committed because the WSGI child is another DB connection; ``_cleanup_donors`` removes them.
"""

import frappe


class LinkedDonorFixtureMixin:
    """Needs ``self._donors = []`` and ``self.addCleanup(self._cleanup_donors)`` in setUp."""

    donor_name_prefix = "Linked"

    def _cleanup_donors(self):
        frappe.db.rollback()
        for donor, customer in self._donors:
            for doctype, name in (("Donor", donor), ("Customer", customer)):
                if name and frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_linked_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"{self.donor_name_prefix} {frappe.generate_hash(length=6)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"f{frappe.generate_hash(length=6)}@example.com"
        donor.flags.enable_customer_sync_in_test = True  # sync is gated off in tests otherwise
        donor.save()
        donor.reload()
        customer = donor.customer
        self.assertTrue(customer, "Donor.save is expected to create and link a Customer")
        self._donors.append((donor.name, customer))
        frappe.db.set_value("Customer", customer, "donor", donor.name)
        frappe.db.commit()
        return donor.name, customer
