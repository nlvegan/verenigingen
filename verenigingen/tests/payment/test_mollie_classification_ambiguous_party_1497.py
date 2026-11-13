"""
#1497: a Mollie id shared by several Members (or Donors) must not be attributed to
an arbitrary one of them.

Maintainer ruling 2026-11-13 (and #1497 (2): the alert is raised only on a delivery/booking path):
* duplicate MEMBERS: the payment is refused as ambiguous (no member_id, type neither dues nor
  donation), ONE deduplicated Error Log row per payment, and one staff alert on the registered
  key ``mollie_ambiguous_party`` on first sight, ONLY when the caller passes ``alert_staff=True``
  (the webhook); every read-only caller writes the Error Log row and sends no alert;
* duplicate DONORS only: develop's behaviour stays (the donation books via its payment id; the
  classifier only withholds ``donor_id``) with one deduplicated Error Log row.

Neither ``mollie_customer_id`` nor ``mollie_subscription_id`` is unique on Member or Donor, and
nothing in the app's writers enforces it.

Probe shortcut, stated: the shared ids are put on the rows with ``db.set_value`` (as the sibling
test module does). The real writer that can produce the duplicate, ``_update_donor_record``, is
driven in ``test_a_real_writer_produces_the_duplicate``. The donation-chain test books through the
real webhook, donation processor, Journal Entry and Bank Transaction code.

Run with:
    bench --site test_site_8 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_classification_ambiguous_party_1497
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.payment import test_mollie_gap_donation_financial_chain as chain
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    AMBIGUOUS_ALERT_KEY,
    DONOR_LOG_TITLE,
    MEMBER_LOG_TITLE,
    ConfidenceLevel,
    CustomerBasedClassification,
    PaymentClassifier,
    PaymentType,
    SubscriptionBasedClassification,
)
from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter


def _shared_id_payment(**kwargs):
    kwargs.setdefault("id", "tr_1497")
    kwargs.setdefault("description", "")
    kwargs.setdefault("subscription_id", None)
    kwargs.setdefault("customer_id", None)
    return SimpleNamespace(**kwargs)


def _purge(payment_ids):
    """Error Log and Staff Alert Event are MyISAM: they outlive a rollback, so remove them by payment id."""
    for payment_id in payment_ids:
        for event in frappe.get_all("Staff Alert Event", filters={"reference_name": payment_id}, pluck="name"):
            frappe.delete_doc("Staff Alert Event", event, force=True)
        for title in (MEMBER_LOG_TITLE, DONOR_LOG_TITLE):
            frappe.db.delete("Error Log", {"method": title, "error": ["like", f"%Payment {payment_id} %"]})


class AmbiguousPartyBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The refusal is meant to write these Error Log rows; their content is asserted below.
        self.expectErrorLog(MEMBER_LOG_TITLE, DONOR_LOG_TITLE)
        h = frappe.generate_hash(length=6)
        self.payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self.addCleanup(_purge, [self.payment_id])
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

    def payment(self, **kwargs):
        kwargs.setdefault("id", self.payment_id)
        return _shared_id_payment(**kwargs)

    def _set(self, doctype, name, field, value):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)

    def _share(self, doctype, field, rows):
        value = f"{'sub' if 'subscription' in field else 'cst'}_{self.shared}"
        for row in rows:
            self._set(doctype, row.name, field, value)
        return value

    def _error_rows(self, title, payment_id=None):
        return frappe.get_all(
            "Error Log",
            filters={"method": title, "error": ["like", f"%Payment {payment_id or self.payment_id} %"]},
            pluck="error",
        )

    def _alert_events(self, payment_id=None):
        return frappe.get_all(
            "Staff Alert Event",
            filters={"notification_key": AMBIGUOUS_ALERT_KEY, "reference_name": payment_id or self.payment_id},
            fields=["name", "attempts", "requires_action", "recipient_count"],
        )

    def _staff_recipient(self):
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

        ensure_notification_registry_rows()
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"staff1497-{frappe.generate_hash(length=6)}@example.com",
                "first_name": "Staff1497",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        return user.name

    def assertRefusedMembers(self, result, names, matched_by):
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertEqual(result.confidence, ConfidenceLevel.NONE)
        self.assertEqual(result.matched_by, matched_by)
        self.assertIsNone(result.member_id)
        self.assertIsNone(result.donor_id)
        rows = self._error_rows(MEMBER_LOG_TITLE)
        self.assertEqual(len(rows), 1)
        for name in names:
            self.assertIn(name, rows[0])

    def assertDonorsKeepDonationPath(self, result, names, matched_by):
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.matched_by, matched_by)
        self.assertIsNone(result.donor_id, "the classifier must not pick one of the duplicate donors")
        self.assertIsNone(result.member_id)
        rows = self._error_rows(DONOR_LOG_TITLE)
        self.assertEqual(len(rows), 1)
        for name in names:
            self.assertIn(name, rows[0])
        self.assertEqual(self._alert_events(), [], "duplicate donors raise no staff alert")


class TestSharedMemberIdIsRefused(AmbiguousPartyBase):
    def test_two_members_sharing_a_customer_id(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = CustomerBasedClassification().classify(self.payment(customer_id=cust))
        self.assertRefusedMembers(result, [m.name for m in self.members], "customer_id_ambiguous_member")

    def test_two_members_sharing_a_subscription_id(self):
        sub = self._share("Member", "mollie_subscription_id", self.members)
        result = SubscriptionBasedClassification().classify(self.payment(subscription_id=sub))
        self.assertRefusedMembers(result, [m.name for m in self.members], "subscription_id_ambiguous_member")

    def test_a_third_unique_member_does_not_change_the_refusal(self):
        """Pick-first/pick-newest would return one of the pair; a third, unique row must not matter."""
        cust = self._share("Member", "mollie_customer_id", self.members)
        other = self.create_test_member(
            first_name="Amb2", last_name="Member", email=f"amb1497.m2.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", other.name, "mollie_customer_id", f"cst_{frappe.generate_hash(length=10)}")
        result = CustomerBasedClassification().classify(self.payment(customer_id=cust))
        self.assertRefusedMembers(result, [m.name for m in self.members], "customer_id_ambiguous_member")


class TestSharedDonorIdKeepsTheDonationPath(AmbiguousPartyBase):
    def test_two_donors_sharing_a_customer_id(self):
        cust = self._share("Donor", "mollie_customer_id", self.donors)
        result = CustomerBasedClassification().classify(self.payment(customer_id=cust))
        self.assertDonorsKeepDonationPath(result, [d.name for d in self.donors], "customer_id_ambiguous_donor")

    def test_two_donors_sharing_a_subscription_id(self):
        sub = self._share("Donor", "mollie_subscription_id", self.donors)
        result = SubscriptionBasedClassification().classify(self.payment(subscription_id=sub))
        self.assertDonorsKeepDonationPath(
            result, [d.name for d in self.donors], "subscription_id_ambiguous_donor"
        )
        self.assertEqual(result.confidence, ConfidenceLevel.HIGH)


class TestNoFallThrough(AmbiguousPartyBase):
    def test_ambiguous_customer_id_is_not_rescued_by_the_description_keyword(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = PaymentClassifier().classify(self.payment(customer_id=cust, description="Contributie 2026"))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.member_id)

    def test_ambiguous_subscription_id_is_not_rescued_by_a_unique_customer_id(self):
        sub = self._share("Member", "mollie_subscription_id", self.members)
        cust = f"cst_{frappe.generate_hash(length=10)}"
        self._set("Donor", self.donors[0].name, "mollie_customer_id", cust)
        result = PaymentClassifier().classify(self.payment(subscription_id=sub, customer_id=cust))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.donor_id)

    def test_two_members_do_not_fall_through_to_a_donor_holding_the_same_id(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        self._set("Donor", self.donors[0].name, "mollie_customer_id", cust)
        result = CustomerBasedClassification().classify(self.payment(customer_id=cust))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.donor_id)


class TestControls(AmbiguousPartyBase):
    def test_a_unique_member_id_still_resolves_beside_a_duplicated_one(self):
        self._share("Member", "mollie_customer_id", self.members)
        unique = f"cst_{frappe.generate_hash(length=10)}"
        third = self.create_test_member(
            first_name="Amb3", last_name="Member", email=f"amb1497.m3.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", third.name, "mollie_customer_id", unique)
        result = CustomerBasedClassification().classify(self.payment(customer_id=unique))
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.member_id, third.name)
        self.assertEqual(self._error_rows(MEMBER_LOG_TITLE), [])
        self.assertEqual(self._alert_events(), [])

    def test_a_unique_donor_subscription_still_resolves_beside_a_duplicated_one(self):
        self._share("Donor", "mollie_subscription_id", self.donors)
        unique = f"sub_{frappe.generate_hash(length=10)}"
        third = self.create_test_donor(
            donor_name="Amb Donor 3", donor_email=f"amb1497.d3.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Donor", third.name, "mollie_subscription_id", unique)
        result = SubscriptionBasedClassification().classify(self.payment(subscription_id=unique))
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, third.name)
        self.assertEqual(self._error_rows(DONOR_LOG_TITLE), [])


class TestBatch(AmbiguousPartyBase):
    """classify_batch has no production caller. Customer-ONLY payments are used on purpose: with both
    id kinds in one call the pre-fetch's ``or_filters`` returns no rows (a separate defect) and every
    payment falls back to the single path, so the batch lines would never run."""

    def test_batch_refuses_shared_member_id_and_resolves_the_unique_one(self):
        shared = self._share("Member", "mollie_customer_id", self.members)
        unique = f"cst_{frappe.generate_hash(length=10)}"
        third = self.create_test_member(
            first_name="Amb4", last_name="Member", email=f"amb1497.m4.{frappe.generate_hash(length=6)}@example.com"
        )
        self._set("Member", third.name, "mollie_customer_id", unique)
        results = PaymentClassifier().classify_batch(
            [self.payment(customer_id=shared), self.payment(id="tr_c_unique", customer_id=unique)]
        )
        self.assertEqual(results[0].payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(results[0].member_id)
        self.assertEqual(results[0].matched_by, "customer_id_ambiguous_member")
        self.assertEqual(results[1].member_id, third.name)

    def test_batch_withholds_the_donor_id_of_duplicate_donors(self):
        shared = self._share("Donor", "mollie_customer_id", self.donors)
        (result,) = PaymentClassifier().classify_batch([self.payment(customer_id=shared)])
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.matched_by, "customer_id_ambiguous_donor")
        self.assertIsNone(result.donor_id)


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"a processor was reached for an ambiguous payment ({name})")


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


class TestDedupAndAlert(AmbiguousPartyBase):
    def test_two_deliveries_write_one_error_log_row_and_one_alert(self):
        self._staff_recipient()
        cust = self._share("Member", "mollie_customer_id", self.members)
        for _ in range(2):
            result = PaymentClassifier().classify(self.payment(customer_id=cust), alert_staff=True)
            self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)
        events = self._alert_events()
        self.assertEqual(len(events), 1, "expected exactly one staff alert event for the payment")
        self.assertEqual(events[0].attempts, 1)
        self.assertEqual(events[0].requires_action, 1)
        self.assertGreaterEqual(events[0].recipient_count, 1, "the alert reached nobody")

    def test_a_second_payment_gets_its_own_row_and_alert(self):
        self._staff_recipient()
        cust = self._share("Member", "mollie_customer_id", self.members)
        other_id = f"tr_{frappe.generate_hash(length=10)}"
        self.addCleanup(_purge, [other_id])
        PaymentClassifier().classify(self.payment(customer_id=cust), alert_staff=True)
        PaymentClassifier().classify(self.payment(id=other_id, customer_id=cust), alert_staff=True)
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE, other_id)), 1)
        self.assertEqual(len(self._alert_events()), 1)
        self.assertEqual(len(self._alert_events(other_id)), 1)

    def test_two_deliveries_of_duplicate_donors_write_one_error_log_row(self):
        cust = self._share("Donor", "mollie_customer_id", self.donors)
        for _ in range(2):
            PaymentClassifier().classify(self.payment(customer_id=cust))
        self.assertEqual(len(self._error_rows(DONOR_LOG_TITLE)), 1)


class TestCallersRefuse(AmbiguousPartyBase):
    def test_router_reports_an_error_and_reaches_no_processor(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        payment = self.payment(customer_id=cust)
        result = _SeamRouter(payment).route_payment(payment.id, payment)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["processor"], "none")
        self.assertEqual(result["payment_type"], PaymentType.AMBIGUOUS)
        # not the generic "no matching member/donor found" of the UNKNOWN branch
        self.assertIn("More than one", result["message"])

    def _webhook_result(self, payment):
        from verenigingen.verenigingen_payments.mollie.services import payment_type_router as router_mod
        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        orig = router_mod.get_payment_router
        # Mock justified: the Mollie fetch is the only gateway boundary; classification is real.
        router_mod.get_payment_router = lambda: _SeamRouter(payment)
        self.addCleanup(lambda: setattr(router_mod, "get_payment_router", orig))

        service = UnifiedWebhookWrapperService()

        def _reached(*a, **k):
            raise AssertionError("webhook continued past an ambiguous classification")

        manager = service.idempotency_manager  # shared across services: undo the instance override
        manager.check_payment_processing_state = _reached
        self.addCleanup(lambda: manager.__dict__.pop("check_payment_processing_state", None))
        return service.process_payment_webhook(self.payment_id, {})

    def test_webhook_does_not_fall_through_to_the_donation_path(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = self._webhook_result(self.payment(customer_id=cust, metadata={}))
        self.assertEqual(result["status"], "error")
        self.assertIn("More than one", result["message"])

    def test_webhook_alerts_exactly_once_across_two_deliveries(self):
        """The webhook is a delivery path: it asks for the alert, and the redelivery is silent."""
        self._staff_recipient()
        cust = self._share("Member", "mollie_customer_id", self.members)
        for _ in range(2):
            result = self._webhook_result(self.payment(customer_id=cust, metadata={}))
            self.assertEqual(result["status"], "error")
        events = self._alert_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].attempts, 1)
        self.assertGreaterEqual(events[0].recipient_count, 1)
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)

    def test_a_refund_repost_for_an_ambiguous_member_payment_is_refused_too(self):
        """Refusing to attribute is refusing to book its reversal as well: the refund of a payment
        nobody could be charged to is not booked against a guessed Member either (#1497). Mollie
        keeps retrying, and the refund books with the payment once the id is unique."""
        cust = self._share("Member", "mollie_customer_id", self.members)
        payment = self.payment(
            customer_id=cust, metadata={}, amount_refunded={"value": "5.00", "currency": "EUR"}
        )
        result = self._webhook_result(payment)
        self.assertEqual(result["status"], "error")
        self.assertIn("More than one", result["message"])


class TestAlertOnlyOnDeliveryPaths(AmbiguousPartyBase):
    """#1497 (2): read-only classification writes the Error Log row and sends NO alert."""

    def setUp(self):
        super().setUp()
        self._staff_recipient()
        self.cust = self._share("Member", "mollie_customer_id", self.members)
        self.other_id = f"tr_{frappe.generate_hash(length=10)}"
        self.addCleanup(_purge, [self.other_id])

    def _payments(self):
        return [self.payment(customer_id=self.cust), self.payment(id=self.other_id, customer_id=self.cust)]

    def assertQuietButLogged(self):
        for payment_id in (self.payment_id, self.other_id):
            self.assertEqual(self._alert_events(payment_id), [], f"read-only caller alerted for {payment_id}")
            self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE, payment_id)), 1)

    def test_default_is_quiet_for_every_entry_point(self):
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        first, second = self._payments()
        self.assertEqual(PaymentClassifier().classify(first).payment_type, PaymentType.AMBIGUOUS)
        (batched,) = PaymentClassifier().classify_batch([second])
        self.assertEqual(batched.payment_type, PaymentType.AMBIGUOUS)
        self.assertQuietButLogged()
        for payment in (first, second):
            self.assertEqual(
                DuesPaymentProcessor().identify_payment_type(payment), PaymentType.AMBIGUOUS
            )
            self.assertEqual(
                PaymentTypeRouter.classify_payment(_SeamRouter(payment), payment)["payment_type"],
                PaymentType.AMBIGUOUS,
            )
        self.assertQuietButLogged()

    def test_explicit_true_alerts_through_each_entry_point(self):
        """Control: the switch is wired through every layer, so a quiet default is not a dead alert."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        first, second = self._payments()
        DuesPaymentProcessor().identify_payment_type(first, alert_staff=True)
        PaymentTypeRouter.classify_payment(_SeamRouter(second), second, alert_staff=True)
        self.assertEqual(len(self._alert_events(self.payment_id)), 1)
        self.assertEqual(len(self._alert_events(self.other_id)), 1)

    def test_batch_with_true_alerts(self):
        PaymentClassifier().classify_batch([self.payment(customer_id=self.cust)], alert_staff=True)
        self.assertEqual(len(self._alert_events()), 1)

    def test_bulk_payment_checker_over_a_shared_customer_sends_no_alert(self):
        from verenigingen.tests.payment import test_bulk_payment_checker as bulk
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        sdk_payments = [
            bulk._sdk_payment(pid, customer_id=self.cust) for pid in (self.payment_id, self.other_id)
        ]
        checker = bulk._build_checker(bulk._FakeSDKClient({self.cust: sdk_payments}))
        checker.dues_processor = DuesPaymentProcessor()  # real classification
        with bulk._patch_bt_creator():
            result = checker.check_payments_for_customer(self.cust, self.members[0].name)
        self.assertIsNone(result["error"])
        self.assertEqual([p["payment_type"] for p in result["payments"]], [PaymentType.AMBIGUOUS] * 2)
        self.assertQuietButLogged()

    def test_debug_service_over_a_shared_customer_sends_no_alert(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService
        from verenigingen.tests.payment import test_bulk_payment_checker as bulk

        payments = [
            SimpleNamespace(
                id=pid,
                status="paid",
                amount={"value": "25.00", "currency": "EUR"},
                description="",
                customer_id=self.cust,
                subscription_id=None,
                created_at="2026-01-01",
                paid_at="2026-01-01",
                metadata={},
            )
            for pid in (self.payment_id, self.other_id)
        ]

        class _Customers:
            def get(_self, customer_id):
                return SimpleNamespace(
                    name="n", email="e", payments=bulk._FakePaymentsList(payments)
                )

        class _Client:
            sdk_client = SimpleNamespace(customers=_Customers())

            def is_test_mode(_self):
                return True

        service = object.__new__(MollieDebugService)
        service.mollie_client = _Client()
        service.logger = get_harness_logger(__name__)  # __init__ (real Mollie client) is skipped
        with bulk._patch_bt_creator():
            result = service.retrieve_customer_payments_for_processing(self.cust)
        self.assertIsNone(result["error"])
        self.assertEqual([p["payment_type"] for p in result["payments"]], [PaymentType.AMBIGUOUS] * 2)
        self.assertQuietButLogged()


class TestWriterReachability(AmbiguousPartyBase):
    def test_a_real_writer_produces_the_duplicate(self):
        """The webhook's own writer stamps the payment's customer id on whichever Donor the
        Donation names, with no uniqueness check: two donations by one Mollie customer that
        point at two Donor rows leave both carrying the id, and the classifier then withholds it."""
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
        result = CustomerBasedClassification().classify(self.payment(customer_id=cust))
        self.assertIsNone(result.donor_id)


class TestDuplicateDonorsStillBookThroughTheRealDonationChain(chain.TestMollieDonationFinancialChain):
    """The review's opposite harm: two Donors sharing the payment's customer id. Develop booked the
    donation (the donation path resolves it by Donation.payment_id and never reads the classifier's
    donor_id); a refusal here would leave a paid donation unbooked. Real webhook, donation
    processor, Journal Entry and Bank Transaction; only the Mollie SDK is faked."""

    # The parent's own tests already run in their module; do not run them a second time here.
    test_success_chain_creates_je_bank_transaction_and_updates_donation = None
    test_second_identical_webhook_is_idempotent = None
    test_donation_journal_entry_link_is_persisted = None

    def setUp(self):
        super().setUp()
        self.expectErrorLog(MEMBER_LOG_TITLE, DONOR_LOG_TITLE)
        self.addCleanup(_purge, [self.payment_id])
        self.customer_id = f"cst_{frappe.generate_hash(length=10)}"
        second = self._setup_donor()
        for donor in (self.donor, second):
            frappe.db.set_value("Donor", donor, "mollie_customer_id", self.customer_id, update_modified=False)
        self.fake_payment.customer_id = self.customer_id

    def test_donation_books_when_two_donors_share_the_customer_id(self):
        result = self._run_webhook()
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        self.assertEqual(result["donation_id"], self.donation_name)
        self.assertTrue(result.get("journal_entry"), result)
        self.assertTrue(result.get("bank_transaction"), result)
        self.assertEqual(frappe.db.get_value("Donation", self.donation_name, "paid"), 1)
        rows = frappe.get_all(
            "Error Log",
            filters={"method": DONOR_LOG_TITLE, "error": ["like", f"%Payment {self.payment_id} %"]},
        )
        self.assertEqual(len(rows), 1, "one deduplicated Error Log row so staff can merge the donors")
