# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Ownership regression tests for the guest-reachable universal payment API
(verenigingen.verenigingen_payments.hooks.api.initiate_payment) (#1048).

Before this fix, initiate_payment was @frappe.whitelist(allow_guest=True) and
forwarded EVERY caller-supplied argument straight into
PaymentHook.initiate_payment with zero ownership check and no
reference_doctype allowlist: an anonymous caller could resolve an arbitrary
(reference_doctype, reference_name) pair, name an arbitrary `amount`, request
a recurring mandate, and supply banking details (payer_iban/account_holder)
that would reach a real gateway call.

All tests stub the gateway boundary (PaymentGatewayFactory.get_gateway) so
that, absent the fix, a refused call would otherwise SUCCEED and return a
real-looking payment URL -- this proves a refusal is the new check firing,
not an unrelated failure (e.g. missing gateway credentials on this bench,
which this app's own CLAUDE.md flags as a trap: an unstubbed test takes a
different path here than in CI). Mirrors
tests/backend/portal/test_page_mollie_checkout.py (#1032/PR #1047), the
sibling fix for the analogous mollie_checkout.make_payment endpoint.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.gateway_stub import stub_redirect_gateway as _stub_gateway

_GATEWAY_FACTORY_PATH = (
    "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
)


class TestInitiatePaymentOwnership(EnhancedTestCase):
    """A guest naming someone else's document must be refused, with no
    gateway call and no state change."""

    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user
        # SEPA/other methods depend on site configuration; Mollie is stubbed
        # below regardless, but get_available_methods() (called internally by
        # PaymentHook.initiate_payment) must report the method as available,
        # so force Mollie "available" via the config helper rather than
        # depending on this bench's live Mollie Settings.
        self._mollie_config_patch = patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_mollie_config",
            return_value={"available": True, "subscriptions_enabled": True, "test_mode": True},
        )
        self._mollie_config_patch.start()

    def tearDown(self):
        self._mollie_config_patch.stop()
        frappe.set_user(self._original_user)
        super().tearDown()

    def _make_test_donation_for_ownership_check(self, *, donor_email, amount=20.0):
        donor = self.create_test_donor(donor_email=donor_email)
        doc = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": today(),
                "amount": amount,
                "mode_of_payment": "Mollie",
                "status": "One-time",
                "donation_purpose_type": "General",
                "paid": 0,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _make_disallowed_doctype_target(self):
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

    def _call_initiate_payment(
        self,
        *,
        reference_doctype,
        reference_name,
        payer_email="",
        payer_name="Someone",
        amount=20.0,
        recurring=False,
        interval=None,
    ):
        from verenigingen.verenigingen_payments.hooks.api import initiate_payment

        return initiate_payment(
            method="mollie",
            amount=amount,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            payer_email=payer_email,
            payer_name=payer_name,
            recurring=recurring,
            interval=interval,
        )

    def test_refuses_stranger_with_no_payer_email(self):
        """A guest supplying only the (enumerable) donation name is refused."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        donation = self._make_test_donation_for_ownership_check(
            donor_email=f"owner-{frappe.generate_hash()[:8]}@example.com"
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation", reference_name=donation.name
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_refuses_stranger_with_wrong_payer_email(self):
        """A guest supplying an unrelated email is refused, same as no email at all."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        donation = self._make_test_donation_for_ownership_check(
            donor_email=f"owner-{frappe.generate_hash()[:8]}@example.com"
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation",
                    reference_name=donation.name,
                    payer_email="stranger@example.com",
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_allows_guest_with_correct_payer_email(self):
        """The real donor -- identified only by their own email, no session -- may pay."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_test_donation_for_ownership_check(donor_email=donor_email)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation",
                    reference_name=donation.name,
                    payer_email=donor_email,
                )

        self.assertTrue(result["success"])
        gateway.process_payment.assert_called_once()

    def test_email_comparison_is_case_and_whitespace_insensitive(self):
        """A legitimate donor should not be refused over formatting differences."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_test_donation_for_ownership_check(donor_email=donor_email)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation",
                    reference_name=donation.name,
                    payer_email=f"  {donor_email.upper()}  ",
                )

        self.assertTrue(result["success"])
        gateway.process_payment.assert_called_once()

    def test_refuses_disallowed_reference_doctype(self):
        """An arbitrary, non-payment doctype is refused outright -- no allowlist
        match, no gateway call -- regardless of any email supplied.

        Self-review note (mutation testing): removing ONLY the allowlist
        check does not redden this specific case, because
        _resolve_reference_owner_email independently returns "" for any
        doctype outside the three it knows -- so the ownership check alone
        would still refuse a "Member" reference. That is intentional
        defense in depth, not a gap this test needs to pin down
        separately: the allowlist's own, narrower job -- never calling
        frappe.get_doc on a caller-named arbitrary doctype at all -- was
        verified directly by reading the source (the check runs before any
        frappe.get_doc call), not re-encoded here as a mock, since patching
        frappe.get_doc is exactly the pattern
        scripts/validation/test_quality_enforcer.py blocks.
        """
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        member = self._make_disallowed_doctype_target()
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Member",
                    reference_name=member.name,
                    payer_email=member.email,
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_caller_supplied_amount_is_ignored(self):
        """The amount actually forwarded to the gateway must be the resolved
        document's own amount, never the caller's `amount` argument -- an
        unauthenticated caller must not be able to name an arbitrary sum for
        a real gateway call (#1048)."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_test_donation_for_ownership_check(donor_email=donor_email, amount=20.0)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation",
                    reference_name=donation.name,
                    payer_email=donor_email,
                    amount=999999.0,
                )

        self.assertTrue(result["success"])
        gateway.process_payment.assert_called_once()
        forwarded_form_data = gateway.process_payment.call_args[0][1]
        self.assertEqual(float(forwarded_form_data["amount"]), 20.0)

    def test_recurring_is_forced_off(self):
        """No known legitimate caller uses this guest endpoint for a recurring
        setup (public donation form and payment-plan installments both call
        PaymentHook.initiate_payment directly, under their own session/
        ownership checks). recurring=True from this endpoint must not reach
        the gateway as a recurring request."""
        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_test_donation_for_ownership_check(donor_email=donor_email)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Donation",
                    reference_name=donation.name,
                    payer_email=donor_email,
                    recurring=True,
                    interval="1 month",
                )

        self.assertTrue(result["success"])
        gateway.process_payment.assert_called_once()
        forwarded_form_data = gateway.process_payment.call_args[0][1]
        self.assertFalse(forwarded_form_data["recurring"])

    def _make_payment_plan_payment(self, *, member_email):
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Plan",
                "last_name": "Owner",
                "email": member_email,
            }
        )
        member.insert(ignore_permissions=True)
        self.track_doc("Member", member.name)

        plan = frappe.get_doc(
            {
                "doctype": "Payment Plan",
                "member": member.name,
                "plan_type": "Equal Installments",
                "total_amount": 42.0,
                "number_of_installments": 1,
                "frequency": "Monthly",
                "start_date": today(),
                "status": "Active",
                "payment_method": "Bank Transfer",
            }
        )
        plan.insert(ignore_permissions=True)
        self.track_doc("Payment Plan", plan.name)

        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": plan.name,
                "installment_number": 1,
                "amount": 42.0,
                "currency": "EUR",
                "member": member.name,
                "gateway": "Mollie",
                "status": "Pending",
            }
        )
        intent.insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent, member

    def test_payment_plan_payment_ownership(self):
        """The Payment Plan Payment resolver (via its `member` link) must
        match the same email-ownership rule as Donation."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        member_email = f"planowner-{frappe.generate_hash()[:8]}@example.com"
        intent, _member = self._make_payment_plan_payment(member_email=member_email)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                wrong = self._call_initiate_payment(
                    reference_doctype="Payment Plan Payment",
                    reference_name=intent.name,
                    payer_email="stranger@example.com",
                )
            self.assertFalse(wrong["success"])
            gateway.process_payment.assert_not_called()

            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                right = self._call_initiate_payment(
                    reference_doctype="Payment Plan Payment",
                    reference_name=intent.name,
                    payer_email=member_email,
                )
            self.assertTrue(right["success"])
            gateway.process_payment.assert_called_once()
            forwarded_form_data = gateway.process_payment.call_args[0][1]
            self.assertEqual(float(forwarded_form_data["amount"]), 42.0)

    def test_no_state_change_on_refusal(self):
        """A refused guest call must leave the reference document untouched --
        no partial write lands before the refusal."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        intent, _member = self._make_payment_plan_payment(
            member_email=f"planowner-{frappe.generate_hash()[:8]}@example.com"
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Payment Plan Payment",
                    reference_name=intent.name,
                    payer_email="attacker@example.com",
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()
        self.assertEqual(
            frappe.db.get_value("Payment Plan Payment", intent.name, "status"), "Pending"
        )

    def _make_sales_invoice(self, *, contact_email, grand_total=100.0, outstanding_amount=None, status=None):
        """A Sales Invoice against a fresh Member/Customer, with contact_email
        set directly (the field _resolve_reference_owner_email reads) and
        outstanding_amount forced to a specific value via db_set -- see
        create_test_sales_invoice's own docstring: this MUST happen after
        submit(), since submit() posts GL entries that recompute
        outstanding_amount and would otherwise silently discard an
        earlier override (#609).
        """
        member = self.create_test_member(
            first_name="Invoice", last_name=f"Owner{frappe.generate_hash()[:6]}"
        )
        kwargs = {"grand_total": grand_total}
        if outstanding_amount is not None:
            kwargs["outstanding_amount"] = outstanding_amount
        if status is not None:
            kwargs["status"] = status
        invoice = self.create_test_sales_invoice(customer=member.name, **kwargs)
        invoice.db_set("contact_email", contact_email)
        invoice.reload()
        return invoice

    def test_settled_sales_invoice_amount_resolves_to_zero_and_refuses(self):
        """#1066: a SUBMITTED, fully-settled invoice (outstanding_amount == 0)
        must resolve to amount 0 and be refused -- not recharge the full
        original grand_total. Fails with the pre-fix fallback
        (`outstanding if outstanding > 0 else grand_total`), which returns
        grand_total here."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        contact_email = f"invoice-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice = self._make_sales_invoice(
            contact_email=contact_email, grand_total=100.0, outstanding_amount=0.0
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Sales Invoice",
                    reference_name=invoice.name,
                    payer_email=contact_email,
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_overcredited_sales_invoice_amount_resolves_to_zero_and_refuses(self):
        """#1066: a negative outstanding_amount (over-credited/credit-noted)
        must also resolve to 0, not the (positive) grand_total."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        contact_email = f"invoice-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice = self._make_sales_invoice(
            contact_email=contact_email, grand_total=100.0, outstanding_amount=-20.0
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Sales Invoice",
                    reference_name=invoice.name,
                    payer_email=contact_email,
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_draft_sales_invoice_is_refused(self):
        """#209/#856's class: a DRAFT invoice's outstanding_amount mirrors
        grand_total (never 0), so it cannot be told apart from a genuine
        unpaid submitted invoice by outstanding_amount alone. A draft is not
        a finalized financial document -- require docstatus == 1 before
        trusting the balance at all, not as evidence a payment posted
        (#382), only that the invoice itself is real."""
        self.expectErrorLog("Initiate Payment Ownership Check Failed")
        contact_email = f"invoice-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice = self._make_sales_invoice(
            contact_email=contact_email, grand_total=100.0, status="Draft"
        )
        self.assertEqual(invoice.docstatus, 0)
        self.assertEqual(float(invoice.outstanding_amount), 100.0)
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Sales Invoice",
                    reference_name=invoice.name,
                    payer_email=contact_email,
                )

        self.assertFalse(result["success"])
        gateway.process_payment.assert_not_called()

    def test_partly_paid_sales_invoice_charges_the_outstanding_balance(self):
        """The legitimate case the fix must not regress: a submitted invoice
        genuinely partly paid must still resolve to its real outstanding
        balance (not grand_total, not 0) and succeed."""
        contact_email = f"invoice-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice = self._make_sales_invoice(
            contact_email=contact_email, grand_total=100.0, outstanding_amount=30.0
        )
        gateway = _stub_gateway()

        with self.as_user("Guest"):
            with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                result = self._call_initiate_payment(
                    reference_doctype="Sales Invoice",
                    reference_name=invoice.name,
                    payer_email=contact_email,
                )

        self.assertTrue(result["success"], result)
        gateway.process_payment.assert_called_once()
        forwarded_form_data = gateway.process_payment.call_args[0][1]
        self.assertEqual(float(forwarded_form_data["amount"]), 30.0)
