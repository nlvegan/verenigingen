"""
#1497: a Mollie id shared by several Members (or Donors) must not be attributed to
an arbitrary one of them.

Neither ``mollie_customer_id`` nor ``mollie_subscription_id`` is unique on Member or
Donor, and nothing in the app's writers enforces it. The classifier must refuse:
no member_id/donor_id, a result that is neither dues nor donation (so no caller books
it or creates a party for it), an Error Log row, and no fall-through to the next rule.

Probe shortcut, stated: the shared ids are put on the rows with ``db.set_value`` (as
the sibling test module does). The real writer that can produce the duplicate,
``_update_donor_record``, is driven in ``test_a_real_writer_produces_the_duplicate``.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_classification_ambiguous_party_1497
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    ConfidenceLevel,
    CustomerBasedClassification,
    PaymentClassifier,
    PaymentType,
    SubscriptionBasedClassification,
)
from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter

ERROR_TITLE = "Mollie payment classification: ambiguous party"


def _shared_id_payment(**kwargs):
    kwargs.setdefault("id", "tr_1497")
    kwargs.setdefault("description", "")
    kwargs.setdefault("subscription_id", None)
    kwargs.setdefault("customer_id", None)
    return SimpleNamespace(**kwargs)


class AmbiguousPartyBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The refusal is meant to write this Error Log row; its content is asserted below.
        self.expectErrorLog(ERROR_TITLE)
        h = frappe.generate_hash(length=6)
        self.members = [
            self.create_test_member(
                first_name=f"Amb{i}", last_name="Member", email=f"amb1497.m{i}.{h}@example.com"
            )
            for i in range(2)
        ]
        self.donors = [
            self.create_test_donor(donor_name=f"Amb Donor {i}", donor_email=f"amb1497.d{i}.{h}@example.com")
            for i in range(2)
        ]
        self.shared = f"{frappe.generate_hash(length=10)}"

    def _set(self, doctype, name, field, value):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)

    def _share(self, doctype, field, rows):
        value = f"{'sub' if 'subscription' in field else 'cst'}_{self.shared}"
        for row in rows:
            self._set(doctype, row.name, field, value)
        return value

    def _error_rows(self, needle):
        return frappe.get_all(
            "Error Log",
            filters={"method": ERROR_TITLE, "error": ["like", f"%{needle}%"]},
            pluck="error",
        )

    def assertRefused(self, result, names, matched_by):
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertEqual(result.confidence, ConfidenceLevel.NONE)
        self.assertEqual(result.matched_by, matched_by)
        self.assertIsNone(result.member_id)
        self.assertIsNone(result.donor_id)
        for name in names:
            self.assertTrue(self._error_rows(name), f"no Error Log row names {name}")


class TestSharedIdIsRefused(AmbiguousPartyBase):
    def test_two_members_sharing_a_customer_id(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=cust))
        self.assertRefused(result, [m.name for m in self.members], "customer_id_ambiguous_member")

    def test_two_members_sharing_a_subscription_id(self):
        sub = self._share("Member", "mollie_subscription_id", self.members)
        result = SubscriptionBasedClassification().classify(_shared_id_payment(subscription_id=sub))
        self.assertRefused(result, [m.name for m in self.members], "subscription_id_ambiguous_member")

    def test_two_donors_sharing_a_customer_id(self):
        cust = self._share("Donor", "mollie_customer_id", self.donors)
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=cust))
        self.assertRefused(result, [d.name for d in self.donors], "customer_id_ambiguous_donor")

    def test_two_donors_sharing_a_subscription_id(self):
        sub = self._share("Donor", "mollie_subscription_id", self.donors)
        result = SubscriptionBasedClassification().classify(_shared_id_payment(subscription_id=sub))
        self.assertRefused(result, [d.name for d in self.donors], "subscription_id_ambiguous_donor")

    def test_a_single_member_row_beside_the_duplicates_is_not_picked(self):
        """Pick-first/pick-newest would return one of the pair; a third, unique row must not matter."""
        cust = self._share("Member", "mollie_customer_id", self.members)
        other = self.create_test_member(
            first_name="Amb2", last_name="Member", email=f"amb1497.m2.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", other.name, "mollie_customer_id", f"cst_{frappe.generate_hash(length=10)}")
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=cust))
        self.assertRefused(result, [m.name for m in self.members], "customer_id_ambiguous_member")


class TestNoFallThrough(AmbiguousPartyBase):
    def test_ambiguous_customer_id_is_not_rescued_by_the_description_keyword(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = PaymentClassifier().classify(_shared_id_payment(customer_id=cust, description="Contributie 2026"))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.member_id)

    def test_ambiguous_subscription_id_is_not_rescued_by_a_unique_customer_id(self):
        sub = self._share("Member", "mollie_subscription_id", self.members)
        cust = f"cst_{frappe.generate_hash(length=10)}"
        self._set("Donor", self.donors[0].name, "mollie_customer_id", cust)
        result = PaymentClassifier().classify(_shared_id_payment(subscription_id=sub, customer_id=cust))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.donor_id)

    def test_two_members_do_not_fall_through_to_a_donor_holding_the_same_id(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        self._set("Donor", self.donors[0].name, "mollie_customer_id", cust)
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=cust))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.donor_id)


class TestControls(AmbiguousPartyBase):
    def test_a_unique_member_id_still_resolves_beside_a_duplicated_one(self):
        self._share("Member", "mollie_customer_id", self.members[:1] + self.members[1:])
        unique = f"cst_{frappe.generate_hash(length=10)}"
        third = self.create_test_member(
            first_name="Amb3", last_name="Member", email=f"amb1497.m3.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", third.name, "mollie_customer_id", unique)
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=unique))
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.member_id, third.name)

    def test_a_unique_donor_subscription_still_resolves_beside_a_duplicated_one(self):
        self._share("Donor", "mollie_subscription_id", self.donors[:1] + self.donors[1:])
        unique = f"sub_{frappe.generate_hash(length=10)}"
        third = self.create_test_donor(
            donor_name="Amb Donor 3", donor_email=f"amb1497.d3.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Donor", third.name, "mollie_subscription_id", unique)
        result = SubscriptionBasedClassification().classify(_shared_id_payment(subscription_id=unique))
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, third.name)


class TestBatch(AmbiguousPartyBase):
    def test_batch_refuses_shared_member_and_donor_ids_and_resolves_the_unique_one(self):
        shared_member = self._share("Member", "mollie_customer_id", self.members)
        shared_donor = self._share("Donor", "mollie_subscription_id", self.donors)
        unique = f"cst_{frappe.generate_hash(length=10)}"
        third = self.create_test_member(
            first_name="Amb4", last_name="Member", email=f"amb1497.m4.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", third.name, "mollie_customer_id", unique)
        results = PaymentClassifier().classify_batch(
            [
                _shared_id_payment(id="tr_a", customer_id=shared_member),
                _shared_id_payment(id="tr_b", subscription_id=shared_donor),
                _shared_id_payment(id="tr_c", customer_id=unique),
            ]
        )
        self.assertEqual(results[0].payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(results[0].member_id)
        self.assertEqual(results[1].payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(results[1].donor_id)
        self.assertEqual(results[2].member_id, third.name)


class _SeamRouter:
    """The real classify/route code with the Mollie fetch as the only seam."""

    def __init__(self, payment):
        self._payment = payment
        self.classifier = PaymentClassifier()
        sentinel = _Forbidden()
        self.dues_processor = self.order_processor = self.donation_processor = sentinel

    def fetch_payment(self, payment_id):
        return self._payment

    classify_payment = PaymentTypeRouter.classify_payment
    route_payment = PaymentTypeRouter.route_payment


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"a processor was reached for an ambiguous payment ({name})")


class TestCallersRefuse(AmbiguousPartyBase):
    def test_router_reports_an_error_and_reaches_no_processor(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        payment = _shared_id_payment(customer_id=cust)
        result = _SeamRouter(payment).route_payment(payment.id, payment)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["processor"], "none")
        self.assertEqual(result["payment_type"], PaymentType.AMBIGUOUS)
        # not the generic "no matching member/donor found" of the UNKNOWN branch
        self.assertIn("More than one", result["message"])

    def test_webhook_does_not_fall_through_to_the_donation_path(self):
        from verenigingen.verenigingen_payments.mollie.services import payment_type_router as router_mod
        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        cust = self._share("Member", "mollie_customer_id", self.members)
        payment = _shared_id_payment(customer_id=cust, metadata={})
        orig = router_mod.get_payment_router
        # Mock justified: the Mollie fetch is the only gateway boundary; classification is real.
        router_mod.get_payment_router = lambda: _SeamRouter(payment)
        self.addCleanup(lambda: setattr(router_mod, "get_payment_router", orig))

        service = UnifiedWebhookWrapperService()

        def _reached(*a, **k):
            raise AssertionError("webhook continued past an ambiguous classification")

        service.idempotency_manager.check_payment_processing_state = _reached
        result = service.process_payment_webhook("tr_1497", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("More than one", result["message"])


class TestWriterReachability(AmbiguousPartyBase):
    def test_a_real_writer_produces_the_duplicate(self):
        """The webhook's own writer stamps the payment's customer id on whichever Donor the
        Donation names, with no uniqueness check: two donations by one Mollie customer that
        point at two Donor rows leave both carrying the id, and the classifier then refuses it."""
        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        cust = f"cst_{self.shared}"
        service = UnifiedWebhookWrapperService()
        for donor in self.donors:
            service._update_donor_record(
                SimpleNamespace(donor=donor.name, name="DON-1497", amount=5),
                {"id": "tr_w", "customer_id": cust, "metadata": {}},
            )
        holders = frappe.get_all("Donor", filters={"mollie_customer_id": cust}, pluck="name")
        self.assertCountEqual(holders, [d.name for d in self.donors])
        result = CustomerBasedClassification().classify(_shared_id_payment(customer_id=cust))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
