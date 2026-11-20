"""
Party-linked Bank Account creation (#2923).

Three writers (MT940 import, Mollie dues, Mollie donation) each hand-built the same
"IBAN -> party" Bank Account. They now share
``bank_account_creation.create_party_bank_account``. These tests pin what each caller
does today (create / raise / swallow) so the refactor cannot change it.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.mollie.services.payment_processors import DonationPaymentProcessor
from verenigingen.verenigingen_payments.utils import mt940_import as M


class TestPartyBankAccountCreation2923(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._made = []

    def tearDown(self):
        for dt, name in reversed(self._made):
            if frappe.db.exists(dt, name):
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
        super().tearDown()

    def _customer(self):
        cust = frappe.new_doc("Customer")
        cust.customer_name = f"PBA2923-{frappe.generate_hash()[:8]}"
        cust.customer_type = "Individual"
        cust.insert()
        self._made.append(("Customer", cust.name))
        return cust.name

    def _iban(self):
        # A checksum-valid NL IBAN (Bank Account validates it), unique per call.
        bban = "ABNA" + str(int(frappe.generate_hash(length=8), 16)).zfill(10)[-10:]
        digits = "".join(str(int(c, 36)) for c in bban + "NL00")
        return f"NL{98 - int(digits) % 97:02d}{bban}"

    def _linked(self, iban):
        row = frappe.db.get_value(
            "Bank Account", {"iban": iban}, ["name", "party_type", "party", "is_default"], as_dict=True
        )
        if row:
            self._made.append(("Bank Account", row.name))
        return row

    def _missing_party(self):
        self.expectErrorLog("Could not find Party")
        return f"NoSuchCustomer-{frappe.generate_hash()[:8]}"

    def test_mt940_link_creates_account_for_party(self):
        customer, iban = self._customer(), self._iban()
        M._ensure_bank_account_link(iban, customer, "Customer")
        row = self._linked(iban)
        self.assertIsNotNone(row)
        self.assertEqual((row.party_type, row.party, row.is_default), ("Customer", customer, 0))

    def test_mt940_link_raises_when_insert_fails(self):
        with self.assertRaises(frappe.ValidationError):
            M._ensure_bank_account_link(self._iban(), self._missing_party(), "Customer")

    def test_dues_processor_creates_account_for_customer(self):
        customer, iban = self._customer(), self._iban()
        DuesPaymentProcessor.__new__(DuesPaymentProcessor)._ensure_customer_bank_account(
            customer, iban, "Holder"
        )
        row = self._linked(iban)
        self.assertIsNotNone(row)
        self.assertEqual((row.party_type, row.party, row.is_default), ("Customer", customer, 0))

    def test_dues_processor_raises_when_insert_fails(self):
        with self.assertRaises(frappe.ValidationError):
            DuesPaymentProcessor.__new__(DuesPaymentProcessor)._ensure_customer_bank_account(
                self._missing_party(), self._iban(), "Holder"
            )

    def test_donation_processor_creates_account_for_customer(self):
        customer, iban = self._customer(), self._iban()
        proc = DonationPaymentProcessor.__new__(DonationPaymentProcessor)
        proc.logger = frappe.logger()
        proc._ensure_customer_bank_account(customer, iban)
        row = self._linked(iban)
        self.assertIsNotNone(row)
        self.assertEqual((row.party_type, row.party, row.is_default), ("Customer", customer, 0))

    def test_donation_processor_swallows_when_insert_fails(self):
        iban = self._iban()
        proc = DonationPaymentProcessor.__new__(DonationPaymentProcessor)
        proc.logger = frappe.logger()
        proc._ensure_customer_bank_account(self._missing_party(), iban)  # must not raise
        self.assertIsNone(self._linked(iban))

    def test_shared_creator_creates_and_raises_typed_error(self):
        from verenigingen.utils.bank_account_creation import (
            BankAccountCreationError,
            create_party_bank_account,
        )

        customer, iban = self._customer(), self._iban()
        name = create_party_bank_account("Customer", customer, iban, source="test 2923")
        self._made.append(("Bank Account", name))
        row = frappe.db.get_value("Bank Account", name, ["party", "iban", "is_company_account"], as_dict=True)
        self.assertEqual((row.party, row.iban, row.is_company_account), (customer, iban, 0))
        with self.assertRaises(BankAccountCreationError):
            create_party_bank_account("Customer", self._missing_party(), self._iban(), source="test 2923")
