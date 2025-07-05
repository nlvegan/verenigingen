# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest

import frappe

from verenigingen.verenigingen.doctype.donation.donation import create_donation_from_bank_transfer


class TestDonation(unittest.TestCase):
    def setUp(self):
        create_donor_type()
        settings = frappe.get_doc("Verenigingen Settings")
        settings.company = "_Test Company"
        settings.donation_company = "_Test Company"
        settings.default_donor_type = "_Test Donor"
        settings.automate_donation_payment_entries = 0
        settings.donation_debit_account = "Debtors - _TC"
        settings.donation_payment_account = "Cash - _TC"
        settings.creation_user = "Administrator"
        settings.flags.ignore_permissions = True
        settings.save()

    def test_payment_entry_for_donations(self):
        donor = create_donor()
        create_mode_of_payment()
        donation = create_donation_from_bank_transfer(
            donor.name, 100, frappe.utils.today(), "TEST-BANK-REF-001"
        )

        self.assertTrue(donation.name)

        # Test payment entry generation
        donation.reload()

        self.assertEqual(donation.paid, 1)
        self.assertTrue(frappe.db.exists("Payment Entry", {"reference_no": donation.name}))


def create_donor_type():
    if not frappe.db.exists("Donor Type", "_Test Donor"):
        frappe.get_doc({"doctype": "Donor Type", "donor_type": "_Test Donor"}).insert()


def create_donor():
    donor = frappe.db.exists("Donor", "donor@test.com")
    if donor:
        return frappe.get_doc("Donor", "donor@test.com")
    else:
        return frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "_Test Donor",
                "donor_type": "_Test Donor",
                "email": "donor@test.com",
            }
        ).insert()


def create_mode_of_payment():
    if not frappe.db.exists("Mode of Payment", "Debit Card"):
        frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": "Debit Card",
                "accounts": [{"company": "_Test Company", "default_account": "Cash - _TC"}],
            }
        ).insert()
