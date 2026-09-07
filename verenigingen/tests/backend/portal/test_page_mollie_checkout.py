"""
Ownership regression tests for the Mollie checkout API
(verenigingen.verenigingen_payments.templates.pages.mollie_checkout.make_payment).

make_payment is guest-reachable (@frappe.whitelist(allow_guest=True)) and, before
this fix, resolved ANY caller-supplied (reference_doctype, reference_docname) pair
with zero ownership check, then attempted a real gateway payment and wrote to the
resolved document (#1032).

All tests stub the Mollie gateway boundary (PaymentGatewayFactory.get_gateway) so
that, absent the ownership check, the call would SUCCEED and return a real-looking
payment URL -- this proves a refusal is the ownership check firing, not an
unrelated failure (e.g. missing Mollie credentials on this bench, which the app's
own CLAUDE.md documents as a trap: an unstubbed test takes a different path here
than in CI). See tests/backend/portal/test_page_donate.py's equivalent tests
(#969/PR #1028) for the precedent this mirrors.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_GATEWAY_FACTORY_PATH = (
    "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
)


class TestMollieCheckoutOwnership(EnhancedTestCase):
    """A guest naming someone else's document must be refused, with no gateway call."""

    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user

    def tearDown(self):
        frappe.set_user(self._original_user)
        super().tearDown()

    def _make_checkout_donation(self, *, donor_email):
        donor = self.create_test_donor(donor_email=donor_email)
        doc = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": today(),
                "amount": 20.0,
                "mode_of_payment": "Mollie",
                "status": "One-time",
                "donation_purpose_type": "General",
                "paid": 0,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _stub_gateway(self):
        """A gateway stub that would report a real-looking redirect if reached."""
        gateway = MagicMock()
        gateway.process_payment.return_value = {
            "status": "redirect_required",
            "payment_url": "https://pay.mollie.test/checkout/xyz",
            "payment_id": "tr_stubbed",
        }
        return gateway

    def _call_make_payment(self, *, reference_doctype, reference_docname, payer_email=None):
        import json

        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        data = json.dumps(
            {
                "amount": 20.0,
                "title": "Donation",
                "description": "Donation",
                "payer_name": "Someone",
                "payer_email": payer_email,
                "order_id": "ORD-1",
                "currency": "EUR",
            }
        )
        return make_payment(
            data=data,
            reference_doctype=reference_doctype,
            reference_docname=reference_docname,
            gateway_name="Default",
        )

    def test_refuses_stranger_with_no_payer_email(self):
        """A guest supplying only the (enumerable) donation name is refused."""
        self.expectErrorLog("Mollie Payment Error")
        donation = self._make_checkout_donation(donor_email=f"owner-{frappe.generate_hash()[:8]}@example.com")
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Donation", reference_docname=donation.name
                )

        self.assertEqual(result["status"], "Error")
        gateway.process_payment.assert_not_called()

    def test_refuses_stranger_with_wrong_payer_email(self):
        """A guest supplying an unrelated email is refused, same as no email at all."""
        self.expectErrorLog("Mollie Payment Error")
        donation = self._make_checkout_donation(donor_email=f"owner-{frappe.generate_hash()[:8]}@example.com")
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Donation",
                    reference_docname=donation.name,
                    payer_email="stranger@example.com",
                )

        self.assertEqual(result["status"], "Error")
        gateway.process_payment.assert_not_called()

    def test_allows_guest_with_correct_payer_email(self):
        """The real donor -- identified only by their own email, no session -- may pay."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_checkout_donation(donor_email=donor_email)
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Donation",
                    reference_docname=donation.name,
                    payer_email=donor_email,
                )

        self.assertEqual(result["status"], "Open")
        self.assertEqual(result["paymentUrl"], "https://pay.mollie.test/checkout/xyz")
        gateway.process_payment.assert_called_once()

    def _make_checkout_member(self):
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Arbitrary",
                "last_name": "Target",
                "email": f"target-{frappe.generate_hash()[:8]}@example.com",
            }
        )
        member.insert(ignore_permissions=True)
        self.track_doc("Member", member.name)
        return member

    def test_refuses_disallowed_reference_doctype(self):
        """An arbitrary, non-payment doctype is refused outright -- no allowlist match,
        no gateway call -- regardless of any email supplied."""
        self.expectErrorLog("Mollie Payment Error")
        member = self._make_checkout_member()
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Member",
                    reference_docname=member.name,
                    payer_email=member.email,
                )

        self.assertEqual(result["status"], "Error")
        gateway.process_payment.assert_not_called()

    def _make_member_payment_history_row(self, member):
        row = member.append(
            "payment_history",
            {"transaction_type": "Invoice", "amount": 20.0, "payment_status": "Pending"},
        )
        member.save(ignore_permissions=True)
        return row

    def test_disallowed_doctype_write_never_lands(self):
        """The literal write make_payment attempts (frappe.db.set_value on
        payment_status) is what #1032 warned about. Every top-level doctype
        allowed for checkout lacks a payment_status field, so the write is
        provably inert there -- but "Member Payment History" (a Member's
        payment_history child table) has one, and a bare frappe.get_doc can
        load a child-table row directly by its own name, the same as any
        other document. Confirmed pre-fix this let a guest flip an arbitrary
        member's payment_history row from "Pending" to "Open" with a stubbed
        gateway and zero ownership check; this test proves the allowlist
        refusal happens before the write, for every row's payment_status,
        not just before a redirect is returned."""
        self.expectErrorLog("Mollie Payment Error")
        member = self._make_checkout_member()
        row = self._make_member_payment_history_row(member)
        row_name = row.name
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Member Payment History",
                    reference_docname=row_name,
                    payer_email="attacker@example.com",
                )

        self.assertEqual(result["status"], "Error")
        gateway.process_payment.assert_not_called()
        self.assertEqual(
            frappe.db.get_value("Member Payment History", row_name, "payment_status"), "Pending"
        )

    def test_email_comparison_is_case_and_whitespace_insensitive(self):
        """A legitimate donor should not be refused over formatting differences."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_checkout_donation(donor_email=donor_email)
        gateway = self._stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_make_payment(
                    reference_doctype="Donation",
                    reference_docname=donation.name,
                    payer_email=f"  {donor_email.upper()}  ",
                )

        self.assertEqual(result["status"], "Open")
        gateway.process_payment.assert_called_once()
