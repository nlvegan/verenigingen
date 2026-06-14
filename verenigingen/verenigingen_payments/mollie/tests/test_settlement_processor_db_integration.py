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
    """_validate_configuration — real config service + DB lookups."""

    def test_returns_status_dict(self):
        # On a site without Mollie clearing/bank GL accounts this returns the
        # error branch; on a fully configured site it returns 'valid' with a
        # bank_account + company. Either way the method must not raise and must
        # produce a well-formed status dict — exercising the real config path.
        out = SettlementBankTransactionProcessor._validate_configuration(None)
        self.assertIn("status", out)
        self.assertIn(out["status"], ("valid", "error"))
        if out["status"] == "valid":
            self.assertTrue(out["bank_account"])
            self.assertTrue(out["company"])
        else:
            self.assertTrue(out["error"])


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
