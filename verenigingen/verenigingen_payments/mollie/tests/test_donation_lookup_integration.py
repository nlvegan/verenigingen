"""
Tier-2 real-DB integration tests for the live DonationLookup handler.

Covers:
  verenigingen/verenigingen_payments/mollie/services/handlers/donation_lookup.py
    DonationLookup.find_by_payment_id
    DonationLookup.find_for_subscription_payment
    DonationLookup.find_for_payment           (primary + customer/timestamp fallback)
    DonationLookup.check_processing_status     (per-component idempotency)
    + the standalone backward-compat wrappers

DonationLookup is on the live webhook path (donation discovery / routing in
webhook_wrapper_service_unified). These tests exercise the real Frappe DB: real
Donation documents are created via the shared factory, and Mollie payment objects
are stood in with SimpleNamespace stubs (the SDK boundary). No Frappe DB or
permission internals are mocked.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.handlers.donation_lookup import (
    DonationLookup,
    check_payment_processing_status,
    find_donation_for_payment,
    find_donation_for_payment_by_id,
    find_donation_for_subscription_payment,
)


def _payment(**kwargs):
    """A minimal Mollie payment SDK stub. metadata defaults to an empty dict."""
    kwargs.setdefault("metadata", {})
    return SimpleNamespace(**kwargs)


class TestFindByPaymentId(EnhancedTestCase):
    """find_by_payment_id — primary lookup by Donation.payment_id."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()
        self.payment_id = f"tr_find_{frappe.generate_hash(length=8)}"
        self.donation = self.create_test_donation(amount=25.0, payment_id=self.payment_id)

    def test_found_returns_donation_doc(self):
        with self.assertNoErrorLog():
            found = self.lookup.find_by_payment_id(self.payment_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, self.donation.name)

    def test_not_found_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(self.lookup.find_by_payment_id("tr_does_not_exist_xyz"))

    def test_with_lock_still_returns_doc(self):
        # The FOR UPDATE branch must return the same document.
        with self.assertNoErrorLog():
            found = self.lookup.find_by_payment_id(self.payment_id, with_lock=True)
        self.assertEqual(found.name, self.donation.name)

    def test_standalone_wrapper_matches_method(self):
        with self.assertNoErrorLog():
            found = find_donation_for_payment_by_id(self.payment_id)
        self.assertEqual(found.name, self.donation.name)


class TestFindForSubscriptionPayment(EnhancedTestCase):
    """find_for_subscription_payment — metadata + subscription_id discovery."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()

    def test_no_payment_object_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(self.lookup.find_for_subscription_payment("tr_x", payment=None))

    def test_payment_without_subscription_id_returns_none(self):
        # Not a subscription payment -> early None, no DB hit.
        with self.assertNoErrorLog():
            self.assertIsNone(
                self.lookup.find_for_subscription_payment("tr_x", payment=_payment(subscription_id=None))
            )

    def test_metadata_donation_id_resolves(self):
        donation = self.create_test_donation(amount=30.0)
        payment = _payment(subscription_id="sub_1", metadata={"donation_id": donation.name})
        with self.assertNoErrorLog():
            found = self.lookup.find_for_subscription_payment("tr_meta", payment=payment)
        self.assertEqual(found.name, donation.name)

    def test_metadata_donation_id_missing_record_returns_none(self):
        # donation_id in metadata points to a nonexistent Donation -> DoesNotExist
        # is caught and None returned. The handler reports this via frappe.logger()
        # (file log), not the Error Log doctype, so no Error Log row is written.
        payment = _payment(subscription_id="sub_2", metadata={"donation_id": "DON-NOPE-0001"})
        with self.assertNoErrorLog():
            result = self.lookup.find_for_subscription_payment("tr_meta_missing", payment=payment)
        self.assertIsNone(result)

    def test_fallback_by_subscription_id(self):
        donation = self.create_test_donation(amount=40.0)
        sub_id = f"sub_fb_{frappe.generate_hash(length=6)}"
        frappe.db.set_value("Donation", donation.name, "mollie_subscription_id", sub_id)
        payment = _payment(subscription_id=sub_id, metadata={})
        with self.assertNoErrorLog():
            found = self.lookup.find_for_subscription_payment("tr_fb", payment=payment)
        self.assertEqual(found.name, donation.name)

    def test_subscription_id_no_match_returns_none(self):
        payment = _payment(subscription_id="sub_unmatched_zzz", metadata={})
        with self.assertNoErrorLog():
            self.assertIsNone(self.lookup.find_for_subscription_payment("tr_nomatch", payment=payment))

    def test_standalone_wrapper(self):
        donation = self.create_test_donation(amount=50.0)
        payment = _payment(subscription_id="sub_w", metadata={"donation_id": donation.name})
        with self.assertNoErrorLog():
            found = find_donation_for_subscription_payment("tr_w", payment=payment)
        self.assertEqual(found.name, donation.name)


class TestFindForPayment(EnhancedTestCase):
    """find_for_payment — primary by payment_id, then customer+timestamp fallback."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()

    def test_primary_match_by_payment_id(self):
        pid = f"tr_prim_{frappe.generate_hash(length=8)}"
        donation = self.create_test_donation(amount=60.0, payment_id=pid)
        with self.assertNoErrorLog():
            found = self.lookup.find_for_payment(pid, _payment())
        self.assertEqual(found.name, donation.name)

    def test_no_customer_id_returns_none(self):
        # No primary match and no customer_id on the payment -> None.
        with self.assertNoErrorLog():
            self.assertIsNone(self.lookup.find_for_payment("tr_unknown_pid", _payment(customer_id=None)))

    def test_no_created_at_returns_none(self):
        with self.assertNoErrorLog():
            result = self.lookup.find_for_payment(
                "tr_unknown_pid2", _payment(customer_id="cst_1", created_at=None)
            )
        self.assertIsNone(result)

    def test_malformed_created_at_returns_none(self):
        # An un-parseable created_at string trips the ValueError guard -> None.
        with self.assertNoErrorLog():
            result = self.lookup.find_for_payment(
                "tr_unknown_pid3", _payment(customer_id="cst_1", created_at="not-a-date")
            )
        self.assertIsNone(result)

    def test_customer_timestamp_fallback_matches_unpaid(self):
        # A donation with a matching mollie_customer_id, created "now", paid=0,
        # is discovered via the 30-minute window fallback when no payment_id matches.
        cust = f"cst_fb_{frappe.generate_hash(length=6)}"
        donation = self.create_test_donation(amount=70.0, paid=0)
        frappe.db.set_value("Donation", donation.name, "mollie_customer_id", cust)
        payment = _payment(customer_id=cust, created_at=frappe.utils.now_datetime().isoformat())
        with self.assertNoErrorLog():
            found = self.lookup.find_for_payment("tr_no_primary", payment)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, donation.name)

    def test_standalone_wrapper(self):
        pid = f"tr_wrap_{frappe.generate_hash(length=8)}"
        donation = self.create_test_donation(amount=80.0, payment_id=pid)
        with self.assertNoErrorLog():
            found = find_donation_for_payment(pid, _payment())
        self.assertEqual(found.name, donation.name)


class TestCheckProcessingStatus(EnhancedTestCase):
    """check_processing_status — per-component idempotency reporting."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()

    def test_status_updated_flag_for_paid_donation(self):
        # A submitted "One-time" donation reports donation_status_updated=True;
        # with no Payment Entry and no payment-history row, all_complete is False.
        donation = self.create_test_donation(amount=90.0, status="One-time")
        with self.assertNoErrorLog():
            status = self.lookup.check_processing_status(donation, "tr_status_1")
        self.assertTrue(status["donation_status_updated"])
        self.assertFalse(status["payment_history_exists"])
        self.assertFalse(status["all_complete"])

    def test_payment_history_matched_by_mollie_payment_id(self):
        donation = self.create_test_donation(amount=95.0, status="One-time")
        pid = "tr_hist_match"
        donation.append(
            "payments",
            {
                "payment_date": frappe.utils.today(),
                "amount": 95.0,
                "mollie_payment_id": pid,
                "payment_status": "Paid",
            },
        )
        donation.flags.ignore_validate_update_after_submit = True
        donation.save()
        with self.assertNoErrorLog():
            status = self.lookup.check_processing_status(donation, pid)
        self.assertTrue(status["payment_history_exists"])

    def test_payment_history_matched_by_payment_reference(self):
        donation = self.create_test_donation(amount=96.0, status="One-time")
        pid = "tr_hist_ref"
        donation.append(
            "payments",
            {
                "payment_date": frappe.utils.today(),
                "amount": 96.0,
                "payment_reference": pid,
                "payment_status": "Paid",
            },
        )
        donation.flags.ignore_validate_update_after_submit = True
        donation.save()
        with self.assertNoErrorLog():
            status = self.lookup.check_processing_status(donation, pid)
        self.assertTrue(status["payment_history_exists"])

    def test_payment_history_no_match(self):
        donation = self.create_test_donation(amount=97.0, status="One-time")
        donation.append(
            "payments",
            {
                "payment_date": frappe.utils.today(),
                "amount": 97.0,
                "mollie_payment_id": "tr_other",
                "payment_status": "Paid",
            },
        )
        donation.flags.ignore_validate_update_after_submit = True
        donation.save()
        with self.assertNoErrorLog():
            status = self.lookup.check_processing_status(donation, "tr_looking_for")
        self.assertFalse(status["payment_history_exists"])

    def test_standalone_wrapper(self):
        donation = self.create_test_donation(amount=98.0, status="One-time")
        with self.assertNoErrorLog():
            status = check_payment_processing_status(donation, "tr_wrap_status")
        self.assertIn("all_complete", status)
        self.assertIn("payment_entry_created", status)


class TestSubscriptionLookupPayloadShapes(EnhancedTestCase):
    """The three shapes a charge actually arrives in, and the origin it must resolve to."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()

    def _setup_donation(self, **kwargs):
        """Build a Donor + Donation inline (mirrors _setup_donor/_setup_donation in
        test_donation_subscription_activation.py). create_test_donation()'s optional-field
        whitelist does not pass through mollie_subscription_id or recurring_origin_donation,
        so those go straight onto the doc instead of through the factory helper.
        """
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Lookup Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"lookup.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)

        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.donation_date = frappe.utils.today()
        donation.amount = kwargs.pop("amount", 42.0)
        donation.mode_of_payment = "Mollie"
        donation.status = kwargs.pop("status", "One-time")
        donation.company = frappe.get_list("Company", limit=1)[0].name
        donation.payment_id = kwargs.pop("payment_id", f"tr_lookup_{frappe.generate_hash(length=10)}")
        donation.paid = kwargs.pop("paid", 0)
        for field, value in kwargs.items():
            setattr(donation, field, value)
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation

    def test_resolves_from_a_plain_snake_case_dict(self):
        origin = self._setup_donation(mollie_subscription_id="sub_shape_a")
        payment = {"id": "tr_a", "subscription_id": "sub_shape_a", "metadata": {"donation_id": origin.name}}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_a", payment=payment).name, origin.name)

    def test_resolves_from_a_camel_case_dict(self):
        # This is the SDK Payment's own shape: a dict subclass with camelCase keys.
        origin = self._setup_donation(mollie_subscription_id="sub_shape_b")
        payment = {"id": "tr_b", "subscriptionId": "sub_shape_b", "metadata": {"donation_id": origin.name}}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_b", payment=payment).name, origin.name)

    def test_metadata_null_falls_back_to_the_subscription_id(self):
        # Measured: sub_5euSBaLzqF has no metadata, so its charges carry
        # metadata: null. The old code raised AttributeError here.
        origin = self._setup_donation(mollie_subscription_id="sub_shape_c")
        payment = {"id": "tr_c", "subscriptionId": "sub_shape_c", "metadata": None}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_c", payment=payment).name, origin.name)

    def test_metadata_naming_an_absent_donation_falls_back_rather_than_giving_up(self):
        origin = self._setup_donation(mollie_subscription_id="sub_shape_d")
        payment = {
            "id": "tr_d",
            "subscriptionId": "sub_shape_d",
            "metadata": {"donation_id": "Assoc-Dnt-does-not-exist"},
        }
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_d", payment=payment).name, origin.name)

    def test_never_returns_a_charge_donation(self):
        # The ordering defect: Donation sorts modified DESC, so without an
        # explicit order and an origin-only filter this returns the newest charge.
        origin = self._setup_donation(mollie_subscription_id="sub_shape_e")
        charge = self._setup_donation(
            mollie_subscription_id="sub_shape_e", recurring_origin_donation=origin.name
        )
        charge.db_set("payment_id", f"tr_earlier_charge_{frappe.generate_hash(length=8)}")
        payment = {"id": "tr_e", "subscriptionId": "sub_shape_e", "metadata": None}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_e", payment=payment).name, origin.name)

    def test_no_subscription_id_is_not_a_subscription_payment(self):
        self.assertIsNone(
            self.lookup.find_for_subscription_payment("tr_f", payment={"id": "tr_f", "metadata": None})
        )
