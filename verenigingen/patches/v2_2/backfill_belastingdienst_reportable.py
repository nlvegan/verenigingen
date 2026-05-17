"""Backfill Donation.belastingdienst_reportable for donations under a periodic
donation agreement.

The belastingdienst_reportable checkbox was added in audit T1.2. Donations
created before it default to 0. Donations linked to a Periodic Donation
Agreement are always reportable to the Belastingdienst, so set the flag on the
existing ones — new donations get it auto-set in the Donation controller.
"""

import frappe


def execute():
    if not frappe.db.has_column("Donation", "belastingdienst_reportable"):
        # DocType schema sync hasn't created the column yet — new donations
        # still get the flag auto-set in the controller; skip silently.
        return

    frappe.db.sql(
        """
        UPDATE `tabDonation`
        SET belastingdienst_reportable = 1
        WHERE belastingdienst_reportable = 0
          AND periodic_donation_agreement IS NOT NULL
          AND periodic_donation_agreement != ''
        """
    )
