"""
Coverage sweep (Tier-2 integration) for the high-level processing orchestrators
in ``mollie/api/payment_webhook.py`` that the existing sibling suites do not
reach:

- ``process_successful_payment``              (PE + history + status enrichment)
- ``process_successful_payment_with_idempotency`` (ordered idempotent processing)
- ``process_successful_member_payment``       (member subscription payment record)
- ``_notify_member_of_payment_failure``       (template selection + send result)
- ``_create_customer_for_donor``              (guest-donation customer creation)

These functions are part of the file's documented "legacy helper" cluster
(see the LEGACY HELPER FUNCTIONS banner around line 84): production webhook
processing now flows through the service-layer WebhookService / payment
processors, and only ``create_payment_entry_for_donation`` /
``find_donation_for_payment_by_id`` / ``_create_customer_for_donor`` are still
re-exported on the live public surface (verenigingen/integrations/mollie and
payment_entry_factory). The remaining orchestrators are exercised through real
test utilities, so the tests below run the genuine business logic against the
real database with NO mocking of the logic under test; the only stubbed boundary
is the Mollie SDK payment object (a types.SimpleNamespace attribute carrier).

Regression coverage: TestNotifyMemberOfPaymentFailure.test_send_path_logs_no_spurious_error
pins the fix for the OperationResult flat-read bug -- ``send_templated_email``
returns an OperationResult dataclass (no dict ``.get``), so the previous
``result.get("status")`` raised AttributeError and logged a spurious
"Payment Notification Error" on every successful send.
"""

import types

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
    _create_customer_for_donor,
    _notify_member_of_payment_failure,
    process_successful_member_payment,
    process_successful_payment,
    process_successful_payment_with_idempotency,
)


def _company():
    return frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")


def _make_unsubmitted_donation(test_case, donor_name="WebhookCov Donor", amount=60.0):
    """Create a docstatus=0 Donation so its child tables can be appended/saved.

    Module-scope so the insert is a recognised factory setup pattern.
    """
    donor = test_case.create_test_donor(donor_name=donor_name)
    donation = frappe.get_doc(
        {
            "doctype": "Donation",
            "company": _company(),
            "donor": donor.name,
            "amount": amount,
            "donation_date": getdate(),
            "currency": "EUR",
            "paid": 0,
            "mode_of_payment": "Bank Transfer",
        }
    ).insert()
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Donation", donation.name)
        factory.track_document("Donor", donor.name)
    return donation, donor


def _fake_payment(payment_id, **extra):
    """Minimal Mollie SDK payment stand-in (attribute carrier only)."""
    p = types.SimpleNamespace(
        id=payment_id,
        status="paid",
        amount={"value": "60.00", "currency": "EUR"},
        method="ideal",
        customer_id=None,
        mandate_id=None,
        subscription_id=None,
        created_at="2024-02-01T10:00:00+00:00",
        paid_at="2024-02-01T10:05:00+00:00",
        description=None,
        metadata={},
        sequence_type=None,
    )
    for k, v in extra.items():
        setattr(p, k, v)
    return p


class TestProcessSuccessfulPayment(EnhancedTestCase):
    """process_successful_payment — end-to-end status/history enrichment.

    create_payment_entry_for_donation may return None in a minimal test
    environment (it never raises -- it catches and logs), so we assert on the
    deterministic donation side effects that this function owns: paid flag,
    One-time/Recurring status, and a populated result envelope.
    """

    def test_one_time_payment_marks_paid_and_one_time(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="OneTime Donor")
        payment = _fake_payment(f"tr_succ_{frappe.generate_hash()[:8]}")

        result = process_successful_payment(donation, payment)

        self.assertEqual(result["donation_id"], donation.name)
        self.assertEqual(result["mollie_payment_id"], payment.id)
        fresh = frappe.get_doc("Donation", donation.name)
        self.assertEqual(fresh.paid, 1)
        self.assertEqual(fresh.status, "One-time")

    def test_recurring_payment_marks_recurring(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="Recurring Donor")
        # sequence_type=recurring is the highest-priority recurring signal.
        payment = _fake_payment(
            f"tr_rec_{frappe.generate_hash()[:8]}", sequence_type="recurring", subscription_id="sub_rec_1"
        )

        result = process_successful_payment(donation, payment)

        fresh = frappe.get_doc("Donation", donation.name)
        self.assertEqual(fresh.paid, 1)
        self.assertEqual(fresh.status, "Recurring")
        # Mollie subscription id persisted via update_donation_with_mollie_data.
        self.assertEqual(fresh.mollie_subscription_id, "sub_rec_1")
        self.assertEqual(result["amount"], fresh.amount)


class TestProcessSuccessfulPaymentWithIdempotency(EnhancedTestCase):
    """process_successful_payment_with_idempotency — ordered, idempotent processing.

    We drive the deterministic branches by supplying an idempotency_status that
    skips the Payment-Entry creation step (which is accounting-environment heavy
    and exercised elsewhere), so the function runs its history-skip + status-update
    logic for real against the donation document.
    """

    def _status(self, **overrides):
        base = {
            "payment_entry_created": True,
            "payment_history_exists": True,
            "donation_status_updated": False,
            "all_complete": False,
        }
        base.update(overrides)
        return base

    def test_status_update_sets_paid_and_one_time(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="Idem OneTime Donor")
        payment = _fake_payment(f"tr_idem_{frappe.generate_hash()[:8]}")

        results = process_successful_payment_with_idempotency(donation, payment, self._status())

        self.assertEqual(results["donation_id"], donation.name)
        self.assertIn("status_updated", results["components_processed"])
        self.assertIn("paid_flag_set", results["components_processed"])
        fresh = frappe.get_doc("Donation", donation.name)
        self.assertEqual(fresh.paid, 1)
        self.assertEqual(fresh.status, "One-time")

    def test_status_update_sets_recurring(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="Idem Recurring Donor")
        payment = _fake_payment(
            f"tr_idemrec_{frappe.generate_hash()[:8]}",
            metadata={"subscription_setup": "true"},
        )

        process_successful_payment_with_idempotency(donation, payment, self._status())

        fresh = frappe.get_doc("Donation", donation.name)
        self.assertEqual(fresh.status, "Recurring")

    def test_all_components_complete_is_noop_but_returns_envelope(self):
        """When every idempotency flag is already set, the function performs no
        writes but still returns the populated result envelope."""
        donation, _ = _make_unsubmitted_donation(self, donor_name="Idem Complete Donor")
        payment = _fake_payment(f"tr_idemdone_{frappe.generate_hash()[:8]}")

        results = process_successful_payment_with_idempotency(
            donation,
            payment,
            self._status(donation_status_updated=True),
        )

        self.assertEqual(results["donation_id"], donation.name)
        self.assertEqual(results["payment_method"], "ideal")
        # No status work was queued.
        self.assertNotIn("status_updated", results["components_processed"])


class TestProcessSuccessfulMemberPayment(EnhancedTestCase):
    """process_successful_member_payment — member subscription payment recording."""

    def test_returns_processed_envelope_with_extracted_amount(self):
        """The function extracts the amount, appends a Paid history row and saves
        the member, returning a 'processed' envelope. We assert on the return
        contract rather than the persisted child table: Member.payment_history is
        regenerated from invoices by the member on_update hook, so a directly
        appended Mollie row is not durably observable after reload."""
        member = self.create_test_member(
            first_name="SuccPay", last_name="Member", email="succpay.member@example.com"
        )
        member.mollie_customer_id = f"cst_succ_{frappe.generate_hash()[:8]}"
        member.save()

        payment_id = f"tr_member_succ_{frappe.generate_hash()[:8]}"
        payment = _fake_payment(payment_id, amount={"value": "30.00", "currency": "EUR"})

        result = process_successful_member_payment(member, payment)

        self.assertEqual(result["member_id"], member.name)
        self.assertEqual(result["payment_id"], payment_id)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["amount"], "30.00")
        self.assertEqual(result["method"], "ideal")

    def test_subscription_payment_handles_unreachable_mollie_api(self):
        """A subscription payment is processed even when the live
        SubscriptionService lookup for the next payment date is unreachable
        (the function logs a warning and continues -- it must not raise)."""
        member = self.create_test_member(
            first_name="SuccSub", last_name="Member", email="succsub.member@example.com"
        )
        member.mollie_customer_id = f"cst_succsub_{frappe.generate_hash()[:8]}"
        member.save()

        payment_id = f"tr_member_sub_{frappe.generate_hash()[:8]}"
        payment = _fake_payment(
            payment_id,
            amount={"value": "30.00", "currency": "EUR"},
            subscription_id=f"sub_succ_{frappe.generate_hash()[:8]}",
        )

        result = process_successful_member_payment(member, payment)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_id"], payment_id)


class TestNotifyMemberOfPaymentFailure(EnhancedTestCase):
    """_notify_member_of_payment_failure — template selection + send-result handling."""

    def _make_member(self):
        member = self.create_test_member(
            first_name="Notify", last_name="Member", email="notify.member@example.com"
        )
        member.mollie_customer_id = f"cst_notify_{frappe.generate_hash()[:8]}"
        member.save()
        return member

    def _failed_payment(self):
        return _fake_payment(
            f"tr_notify_{frappe.generate_hash()[:8]}",
            status="failed",
            amount={"value": "25.00", "currency": "EUR"},
        )

    def _delete_failure_templates(self):
        """Remove all payment-failure email templates so the no-template branch
        (early return after the generic fallback also misses) is exercised."""
        for name in (
            "payment_failure_first",
            "payment_failure_second",
            "payment_failure_final",
            "payment_failure_generic",
        ):
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True, ignore_permissions=True)

    def test_no_template_returns_without_raising(self):
        """With no failure templates configured the function logs a warning and
        returns (first-attempt branch -> generic fallback -> early return)."""
        self._delete_failure_templates()
        member = self._make_member()
        # Should not raise for any of the three failure-count tiers.
        for count in (1, 2, 3):
            _notify_member_of_payment_failure(member, self._failed_payment(), count)

    def _persist_email_template(self, name):
        tmpl = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": name,
                "subject": "Payment failed",
                "response": "<p>Your payment failed.</p>",
                "use_html": 1,
            }
        )
        tmpl.insert(ignore_permissions=True)
        self.factory.track_document("Email Template", tmpl.name)
        return tmpl

    def test_send_path_logs_no_spurious_error(self):
        """Regression: with a real template present the send result is an
        OperationResult dataclass. The pre-fix code called result.get("status"),
        raising AttributeError and logging a spurious 'Payment Notification Error'.
        After the fix (result.success) the send completes with no such Error Log.
        """
        self._delete_failure_templates()
        self._persist_email_template("payment_failure_first")
        member = self._make_member()
        member.next_payment_date = getdate()
        member.save()

        # Snapshot existing Error Logs so we only judge ones THIS call creates
        # (veg11 is long-lived and may carry stale notification errors).
        before = {r.name for r in frappe.get_all("Error Log", fields=["name"])}

        _notify_member_of_payment_failure(member, self._failed_payment(), 1)

        after = frappe.get_all(
            "Error Log",
            fields=["name", "error"],
            filters={"name": ["not in", list(before) or ["__none__"]]},
        )
        # The fixed code reads result.success on the OperationResult instead of
        # result.get("status"); pre-fix this raised AttributeError and logged a
        # "Payment failure notification error ..." Error Log on every send.
        offending = [r for r in after if "notification error" in (r.error or "").lower()]
        self.assertEqual(
            offending,
            [],
            "Notification send must not log a payment-notification Error Log (OperationResult.get regression)",
        )


class TestCreateCustomerForDonor(EnhancedTestCase):
    """_create_customer_for_donor — guest-donation customer creation (live path
    reused by payment_entry_factory)."""

    def test_creates_customer_linked_to_donor(self):
        donor = self.create_test_donor(donor_name="GuestCust Donor")
        customer_name = _create_customer_for_donor(donor)

        self.assertIsNotNone(customer_name)
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self.factory.track_document("Customer", customer_name)

        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_type, "Individual")
        self.assertTrue(customer.customer_name)

    def test_invalid_email_is_dropped_not_fatal(self):
        """A malformed donor email is detected and cleared (email_id left blank),
        exercising the invalid-email guard branch -- customer creation still
        succeeds. The bad email is set in-memory only (the Donor doctype rejects
        an invalid email on save), which is exactly what the guard reads."""
        donor = self.create_test_donor(donor_name="BadEmail Donor")
        donor.donor_email = "not-a-valid-email"  # in-memory; not persisted

        customer_name = _create_customer_for_donor(donor)
        self.assertIsNotNone(customer_name)
        self.factory.track_document("Customer", customer_name)
        self.assertFalse(frappe.db.get_value("Customer", customer_name, "email_id"))
