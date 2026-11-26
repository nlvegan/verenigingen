"""
#3088: a Mollie Payment Entry's audit remark must survive ERPNext's ``set_remarks``.

``PaymentEntry.validate()`` regenerates ``remarks`` ("Amount EUR .. received from ..") unless
``custom_remarks`` is truthy, so a writer that only assigns ``remarks`` loses its text. Every
dict-built Mollie writer is driven through its real function and the STORED row is read back.
The stored text is compared with what the writer intended, derived from the same inputs.

Run:
    PYTHONPATH=<worktree> bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_payment_entry_audit_remarks_3088
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_reversal_single_booking import (
    _ensure_mollie_named_bank_account,
)
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_mollie_settings_bank_account,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import create_payment_entry_for_donation
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_refund_payment_entry,
    create_unified_payment_entry,
)

ERPNEXT_DEFAULT_MARKER = "Transaction reference no"


class TestMollieAuditRemarksSurviveValidate(_RefundFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.ensure_mode_of_payment("Mollie Refund", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        pin_mollie_settings_bank_account(self, _ensure_mollie_named_bank_account())
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        pin_verenigingen_settings(self, company=COMPANY, donation_receivable_account=self.receivable)
        pin_mollie_clearing_account(self, self.clearing_account)
        self.donor = self._make_donor()
        self.donor_name = frappe.db.get_value("Donor", self.donor, "donor_name")
        self.customer = frappe.get_doc("Donor", self.donor).get_or_create_customer()
        self.payment_id = f"tr_rmk_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id

    def _stored_remarks(self, pe):
        self.assertIsNotNone(pe, "the writer did not book a Payment Entry")
        return frappe.db.get_value("Payment Entry", pe.name, "remarks")

    def test_webhook_donation_entry_keeps_its_remark(self):
        pe = create_payment_entry_for_donation(self.donation, {"payment_id": self.payment_id, "method": "ideal"})
        stored = self._stored_remarks(pe)
        self.assertIn("via Mollie (ideal)", stored)
        self.assertIn(self.donor_name, stored)
        self.assertNotIn(ERPNEXT_DEFAULT_MARKER, stored)

    def test_unified_receive_entry_keeps_its_remark(self):
        pe = create_unified_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            amount=100.0,
            payment_type="Receive",
        )
        stored = self._stored_remarks(pe)
        self.assertEqual(stored, f"Payment for {self.donation.name} via Mollie - {self.donor_name}")

    def test_unified_refund_entry_keeps_its_remark(self):
        refund_id = f"re_rmk_{frappe.generate_hash(length=8)}"
        pe = create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )
        stored = self._stored_remarks(pe)
        self.assertIn(f"Refund for {self.donation.name} via Mollie - {self.donor_name}", stored)
        self.assertIn(f"Refund {refund_id}", stored)
        self.assertNotIn(ERPNEXT_DEFAULT_MARKER, stored)

    def test_shared_factory_entry_keeps_its_remark(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import (
            PaymentContext,
        )
        from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
            PaymentEntryFactory,
        )

        context = PaymentContext("donation", "Donation", self.donation.name)
        data = {"payment_id": self.payment_id, "amount": "100.00", "method": "ideal"}
        factory = PaymentEntryFactory()
        expected = factory._sanitize_remarks(factory._generate_remarks(context, data))
        pe = factory.create_payment_entry(context, data, customer=self.customer)
        stored = self._stored_remarks(pe)
        self.assertIn("via Mollie (ideal)", expected, "fixture problem: no marker to look for")
        self.assertEqual(stored, expected)
