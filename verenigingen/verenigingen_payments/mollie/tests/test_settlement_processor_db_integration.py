"""
Integration tests (Tier-2) for the DB-driven branches of
SettlementBankTransactionProcessor, against REAL Frappe Docs. No mocks.

settlement_bank_transaction_processor.py
    - _validate_configuration       (real MollieConfigurationService + Bank Account / company lookups)
    - _link_payment_entries         (real Payment Entry remark stamping + idempotency)

Both methods read/write the database and contain no Mollie-API calls, so they can
be exercised without credentials by invoking them as unbound methods, sidestepping
the constructor (which builds a SettlementsClient needing Mollie keys). For
_link_payment_entries we attach a tiny fake settlements_client (the Mollie API
boundary) to a __new__-built instance so the real DB stamping logic runs.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.mollie_account_fixtures import (
    ensure_bank_account_record,
    ensure_mollie_gl_accounts,
    provisioned_mollie_settings,
)
from verenigingen.verenigingen_payments.services.settlement_bank_transaction_processor import (
    SettlementBankTransactionProcessor,
)


def _get_test_company():
    return frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")


class _FakeSettlementsClient:
    """Mollie-API boundary stub returning a canned settlement-payments list."""

    def __init__(self, payments):
        self._payments = payments

    def list_settlement_payments(self, settlement_id, **kw):
        return self._payments


class TestValidateConfiguration(EnhancedTestCase):
    """_validate_configuration — real config service + DB lookups.

    These used to accept EITHER outcome (`assertIn(out["status"], ("valid",
    "error"))`) because nothing provisioned Mollie Settings, so the test asserted
    shape and nothing else -- it passed identically on a correctly configured site
    and on one where settlement processing could never run. Each test now
    provisions the configuration it is about.
    """

    def test_a_provisioned_configuration_is_accepted(self):
        """A control: this passes against develop too. It pins that the guard does
        not close on the configuration it exists to permit."""
        with provisioned_mollie_settings():
            out = SettlementBankTransactionProcessor._validate_configuration(None)
        self.assertEqual(out["status"], "valid", f"expected a provisioned config to pass: {out}")
        self.assertTrue(out["bank_account"], "the Bank Account record the fixture creates must resolve")
        self.assertTrue(out["company"])

    def test_an_account_outside_the_booking_company_stops_settlement_processing(self):
        """The #540 protection, end to end rather than at the validator's return dict.

        veg11 books settlements into `Verenigingen Settings.company`
        ('Nederlandse Vereniging voor Veganisme') while its Mollie accounts sit in
        'TEST-Payment-Integration-Company'. Both accounts validate individually, so
        before the coherence guard this returned `status: "valid"` and processing
        proceeded -- posting one side of the settlement into a leaked test company's
        ledger. `process_settlement_deposit` returns immediately on
        `status == "error"`, so this is what actually prevents it.
        """
        accounts = ensure_mollie_gl_accounts()
        foreign = frappe.db.get_value(
            "Account",
            {"company": ["!=", accounts["company"]], "account_type": "Bank", "is_group": 0},
            "name",
        )
        self.assertTrue(foreign, "precondition: the site needs a leaf Bank account elsewhere")
        # The foreign account needs a Bank Account record, or the method refuses for
        # an UNRELATED reason ("no Bank Account found linked to GL account") and the
        # test would pass against develop while proving nothing. Measured: that is
        # exactly what an earlier version of this test did.
        ensure_bank_account_record(frappe.db.get_value("Account", foreign, "company"), foreign)

        with provisioned_mollie_settings(mollie_bank_account=foreign):
            out = SettlementBankTransactionProcessor._validate_configuration(None)
        self.assertEqual(out["status"], "error", "a foreign-company account must stop processing")
        self.assertIn(
            "booked into",
            out["error"].lower(),
            f"the refusal must be ABOUT the company mismatch: {out['error']}",
        )

    def test_one_account_as_both_clearing_and_bank_is_still_accepted(self):
        """clearing == bank must NOT stop processing.

        `_book_settlement_payout` supports one account (nothing to drain) and
        `test_one_account_configured_as_both_sides_needs_no_payout_leg` asserts the
        accounting. An earlier version of this guard rejected it, which made this
        pipeline refuse a configuration the other one books correctly -- and produced
        the per-run Error Log row that code deliberately avoids.
        """
        accounts = ensure_mollie_gl_accounts()
        shared = accounts["clearing_account"]
        # The shared account needs a Bank Account record, or this refuses for the
        # SEPARATE pre-existing reason ("No Bank Account found linked to GL Account")
        # and the test would be about linkage rather than about the guard. veg11's
        # shared account has one.
        ensure_bank_account_record(accounts["company"], shared)

        with provisioned_mollie_settings(mollie_bank_account=shared):
            out = SettlementBankTransactionProcessor._validate_configuration(None)
        self.assertEqual(
            out["status"], "valid", f"one account as both sides is supported: {out.get('error')}"
        )

    def test_a_missing_clearing_account_stops_settlement_processing(self):
        """The pre-existing per-account validation still bites, and says which
        account. Without this the test above is equally consistent with "the guard
        fires" and "any override at all produces an error"."""
        with provisioned_mollie_settings(mollie_clearing_account=""):
            out = SettlementBankTransactionProcessor._validate_configuration(None)
        self.assertEqual(out["status"], "error")
        self.assertIn("clearing", out["error"].lower())


class TestLinkPaymentEntries(EnhancedTestCase):
    """_link_payment_entries — real Payment Entry remark stamping."""

    def _make_submitted_payment_entry(self, reference_no):
        """Create a minimal submitted Payment Entry referencing a Mollie payment.

        Module-scope-ish factory pattern (inside setUp/helper, not a test_ method)
        so the ignore_permissions insert is a recognised setup pattern.
        """
        company = _get_test_company()
        # Find a receivable + a cash/bank account on the company for a valid PE.
        paid_to = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
        )
        paid_from = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
        )
        if not (paid_to and paid_from):
            return None

        customer = self.create_test_member(first_name="Settle", last_name=frappe.generate_hash()[:6])
        customer_name = frappe.db.get_value("Member", customer.name, "customer")
        if not customer_name:
            return None

        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": company,
                "posting_date": frappe.utils.today(),
                "party_type": "Customer",
                "party": customer_name,
                "paid_from": paid_from,
                "paid_to": paid_to,
                "paid_amount": 25.0,
                "received_amount": 25.0,
                "reference_no": reference_no,
                "reference_date": frappe.utils.today(),
            }
        )
        pe.insert(ignore_permissions=True)
        pe.submit()
        factory = getattr(self, "factory", None)
        if factory is not None and hasattr(factory, "track_document"):
            factory.track_document("Payment Entry", pe.name)
        return pe.name

    def _processor(self, payments):
        proc = object.__new__(SettlementBankTransactionProcessor)
        proc.settlements_client = _FakeSettlementsClient(payments)
        return proc

    def test_no_matching_payment_entries_links_zero(self):
        token = frappe.generate_hash()[:10]
        payments = [{"id": f"tr_nomatch_{token}"}]
        proc = self._processor(payments)
        linked = proc._link_payment_entries("ACC-BT-FAKE", f"stl_{token}", {})
        self.assertEqual(linked, 0)

    def test_matching_pe_gets_remark_and_is_idempotent(self):
        token = frappe.generate_hash()[:10]
        payment_id = f"tr_match_{token}"
        pe_name = self._make_submitted_payment_entry(payment_id)
        if not pe_name:
            self.skipTest("Could not build a submitted Payment Entry on this site")

        settlement_id = f"stl_{token}"
        bt_name = f"ACC-BT-{token}"
        payments = [{"id": payment_id}]
        proc = self._processor(payments)

        linked = proc._link_payment_entries(bt_name, settlement_id, {})
        self.assertEqual(linked, 1)

        remark = frappe.db.get_value("Payment Entry", pe_name, "remarks") or ""
        self.assertIn(settlement_id, remark)
        self.assertIn(bt_name, remark)

        # Second run must be idempotent: note already present -> 0 newly linked
        linked_again = proc._link_payment_entries(bt_name, settlement_id, {})
        self.assertEqual(linked_again, 0)
