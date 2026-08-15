"""
Regression test: a recurring donation's first payment must actually create the
Mollie subscription.

Issue #343. Mollie does NOT create a subscription by itself -- a
``sequenceType: "first"`` payment only establishes the mandate, and the merchant
must then call the subscriptions API. The donation flow
(``CompletePaymentService.create_recurring_donation_payment``) deliberately defers
that call to webhook time, stamping the payment with
``metadata.subscription_setup = "true"`` plus the interval and amount.

The webhook Mollie actually calls for that payment is
``mollie.api.webhooks.mollie_payment_webhook`` ->
``unified_payment_api.handle_payment_webhook`` -> this service. Nothing on that
path created the subscription, so recurring donors were charged once and never
subscribed.

Mollie's own test-account records show this used to work: five subscriptions
created 2025-09-12 (``sub_czjsX488aw`` .. ``sub_LL9D84YA8o``) carry the exact
metadata fingerprint of ``_activate_direct_subscription_after_first_payment``
(``created_from: 'direct_subscription'`` + ``payment_id``/``donation_id``/
``original_amount``/``original_interval``). So this is a regression, and the
helper is still good code -- what it lost was a reachable caller.

Harness is modelled on ``test_mollie_gap_donation_financial_chain`` (real
fixtures, real business logic; only the Mollie SDK/HTTP boundary is faked).

Run with:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_donation_subscription_activation
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)

# EUR company: the donation Journal Entry posts single-currency, and ERPNext's
# JE/Bank Transaction validation requires the account currency to match the
# company currency. See the sibling gap test for the full rationale.
COMPANY = "_Test Company 2"


# ---------------------------------------------------------------------------
# Mollie SDK fake (HTTP boundary only)
# ---------------------------------------------------------------------------
class _FakeRefundsResource:
    def list(self):
        return {"_embedded": {"refunds": []}}


class _FakeChargebacksResource:
    def list(self):
        return []


class _FakeSubscriptionsResource:
    """Records every subscriptions.create() call so the test can assert on the
    payload the production code sent to Mollie.

    Honours ``idempotency_key`` the way Mollie does, INCLUDING ITS EXPIRY.
    A repeat of a key still in cache returns the ORIGINAL subscription instead of
    creating another (measured: same key + identical payload -> same id, one
    subscription; different keys -> two). But Mollie states *"Keys older than 1
    hour will be removed from our cache"*, while its webhook retry ladder runs 26
    hours (T+0, 1m, 3m, 7m, 15m, 31m, 1h, 2h, 4h, 26h) -- so attempts 8-10 arrive
    with no key protection at all.

    Tests model the eviction by clearing ``seen_idempotency_keys`` between two
    deliveries, while ``_live`` -- the subscriptions Mollie actually holds --
    survives, exactly as it does in reality. A fake whose key cache never expired
    would be more forgiving than the real API in the one dimension that matters
    -- time -- and would report the durable guard as working when it is not.
    """

    def __init__(self, recorder, seen_keys, *, fail_after_create=None, live=None):
        self._recorder = recorder
        self._seen_keys = seen_keys
        self._fail_after_create = fail_after_create
        # Every subscription that exists at Mollie, keyed by id -- what
        # subscriptions.list() returns. Survives key expiry, as the real thing does.
        self._live = live if live is not None else {}

    def list(self):
        return list(self._live.values())

    def create(self, data=None, idempotency_key="", **kwargs):
        payload = data if data is not None else kwargs
        if idempotency_key and idempotency_key in self._seen_keys:
            existing = self._seen_keys[idempotency_key]
            return self._live[existing]

        subscription_id = f"sub_FAKE{len(self._recorder) + 1:04d}"
        self._recorder.append({"id": subscription_id, "data": payload, "key": idempotency_key})
        created = SimpleNamespace(
            id=subscription_id, status="active", metadata=(payload or {}).get("metadata") or {}
        )
        self._live[subscription_id] = created
        if idempotency_key:
            self._seen_keys[idempotency_key] = subscription_id

        if self._fail_after_create:
            # Mollie committed the subscription; the response never arrived.
            raise self._fail_after_create
        return created


class _FakeCustomer:
    def __init__(self, customer_id, recorder, seen_keys, fail_after_create=None, live=None):
        self.id = customer_id
        self.subscriptions = _FakeSubscriptionsResource(
            recorder, seen_keys, fail_after_create=fail_after_create, live=live
        )


class _FakeCustomersResource:
    def __init__(self, recorder, seen_keys, fail_after_create=None, live=None):
        self._recorder = recorder
        # Shared across every _FakeCustomer this resource hands out, so an
        # Idempotency-Key survives the customers.get() that each webhook
        # delivery performs -- exactly as it does at Mollie.
        self._seen_keys = seen_keys
        self._fail_after_create = fail_after_create
        self._live = live if live is not None else {}

    def get(self, customer_id):
        return _FakeCustomer(
            customer_id, self._recorder, self._seen_keys, self._fail_after_create, self._live
        )


class _FakePayment(dict):
    """Mirrors a real Mollie payment: a dict subclass that ALSO exposes attributes.

    This is load-bearing, not incidental. A real ``mollie.api.objects.Payment``
    subclasses ``dict`` (``Payment.__mro__`` -> ``(Payment, ObjectBase, dict,
    object)``), and ``_fetch_payment_from_mollie`` branches on
    ``isinstance(payment, dict)``. So production takes the **camelCase dict
    branch**. A fake that is a plain object silently exercises the other branch,
    leaving the camelCase key names -- ``sequenceType``/``customerId``/
    ``subscriptionId``, string keys crossing a boundary with no compiler --
    covered by nothing. That is the exact defect shape of #341 and #343.

    Attributes are kept too, because other consumers along the chain
    (PaymentTypeRouter, PaymentDataExtractor, the idempotency manager) read the
    payment by attribute.
    """

    def __init__(
        self,
        payment_id,
        amount_value,
        donation_name,
        *,
        sequence_type,
        subscription_setup,
        interval="3 months",
    ):
        metadata = {"donation": donation_name}
        customer_id = None
        if subscription_setup:
            customer_id = "cst_FAKECUSTOMER"
            metadata.update(
                {
                    "donation_id": donation_name,
                    "reference_doctype": "Donation",
                    "reference_docname": donation_name,
                    "subscription_setup": "true",
                    "subscription_interval": interval,
                    "subscription_amount": amount_value,
                    "customer_id": customer_id,
                }
            )

        super().__init__(
            {
                "id": payment_id,
                "status": "paid",
                "amount": {"value": amount_value, "currency": "EUR"},
                "description": f"Donation {donation_name}",
                "createdAt": "2025-04-10T09:00:00+00:00",
                "paidAt": "2025-04-10T09:00:00+00:00",
                "method": "ideal",
                "metadata": metadata,
                "sequenceType": sequence_type,
                "customerId": customer_id,
                # A first payment is not generated BY a subscription, so Mollie
                # omits subscriptionId on it (measured against the test API).
                "subscriptionId": None,
            }
        )

        self.id = payment_id
        self.status = "paid"
        self.amount = {"value": amount_value, "currency": "EUR"}
        self.description = f"Donation {donation_name}"
        self.created_at = "2025-04-10T09:00:00+00:00"
        self.paid_at = "2025-04-10T09:00:00+00:00"
        self.method = "ideal"
        self.metadata = metadata
        self.sequence_type = sequence_type
        self.customer_id = customer_id
        self.subscription_id = None
        self.refunds = _FakeRefundsResource()
        self.chargebacks = _FakeChargebacksResource()


class _FakeSDKClient:
    def __init__(self, payment, recorder, seen_keys=None, fail_after_create=None, live=None):
        self._payment = payment
        self.payments = SimpleNamespace(get=lambda pid: self._payment)
        self.customers = _FakeCustomersResource(
            recorder,
            seen_keys if seen_keys is not None else {},
            fail_after_create,
            live if live is not None else {},
        )

    def set_api_key(self, _key):
        return None


class TestDonationSubscriptionActivation(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._orig_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        cls._orig_donation_account = frappe.db.get_single_value(
            "Verenigingen Settings", "unrestricted_donation_account"
        )
        cls._orig_ms_clearing = frappe.db.get_single_value("Mollie Settings", "mollie_clearing_account")
        cls._orig_ms_bank = frappe.db.get_single_value("Mollie Settings", "mollie_bank_account")
        # setUp forces test_mode=1; without capturing it here the flag leaks to
        # every co-tenant class in the same CI shard.
        cls._orig_ms_test_mode = frappe.db.get_single_value("Mollie Settings", "test_mode")

    @classmethod
    def tearDownClass(cls):
        frappe.db.set_single_value(
            "Verenigingen Settings", "unrestricted_donation_account", cls._orig_donation_account
        )
        frappe.db.set_single_value("Verenigingen Settings", "company", cls._orig_company)
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", cls._orig_ms_clearing)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", cls._orig_ms_bank)
        frappe.db.set_single_value("Mollie Settings", "test_mode", cls._orig_ms_test_mode)
        frappe.db.commit()
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.service = UnifiedWebhookWrapperService()
        frappe.db.set_single_value("Verenigingen Settings", "company", COMPANY)

        self.clearing_account = self._setup_mollie_clearing_account()
        self.bank_account = self._setup_mollie_bank_account(self.clearing_account)
        self.income_account = self._setup_donation_income_account()
        self._setup_mollie_settings(self.clearing_account)

        self.payment_id = f"tr_{frappe.generate_hash(length=12)}"
        self.amount = 25.00
        self.donor = self._setup_donor()
        self.donation_name = self._setup_donation(self.donor, self.payment_id, self.amount)

        # Every subscriptions.create() the production code makes lands here.
        self.created_subscriptions = []
        # Mollie remembers Idempotency-Keys across requests; so does the fake.
        self.seen_idempotency_keys = {}
        # Subscriptions that exist at Mollie. Unlike the key cache these never
        # expire, which is what the durable guard relies on.
        self.live_subscriptions = {}

    # ------------------------------------------------------------------ setup
    def _setup_mollie_clearing_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing Subact Test"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing Subact Test"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _setup_mollie_bank_account(self, gl_account):
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "Subact Test Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "Mollie Subact Test"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def _setup_donation_income_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income Subact Test"}, "name"
        )
        if not name:
            parent = frappe.get_value(
                "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
            )
            acct = frappe.new_doc("Account")
            acct.account_name = "Donation Income Subact Test"
            acct.company = COMPANY
            acct.parent_account = parent
            acct.account_type = "Income Account"
            acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
            acct.insert(ignore_permissions=True)
            name = acct.name
        frappe.db.set_single_value("Verenigingen Settings", "unrestricted_donation_account", name)
        return name

    def _setup_mollie_settings(self, clearing_account):
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()

    def _setup_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Subact Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"subact.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_donation(self, donor_name, payment_id, amount):
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = "2025-04-10"
        donation.amount = amount
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.company = COMPANY
        donation.payment_id = payment_id
        donation.paid = 0
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation.name

    # --------------------------------------------------------------- patching
    def _run_webhook(self, *, sequence_type="first", subscription_setup=True, interval="3 months", sdk=None):
        fake_payment = _FakePayment(
            self.payment_id,
            f"{self.amount:.2f}",
            self.donation_name,
            sequence_type=sequence_type,
            subscription_setup=subscription_setup,
            interval=interval,
        )
        # Pin the branch this harness actually exercises. A real Mollie Payment
        # is a dict subclass, so production takes the camelCase dict branch of
        # _fetch_payment_from_mollie; if this ever stops being true the tests
        # below would quietly stop covering the code they exist to cover.
        self.assertIsInstance(
            fake_payment, dict, "the fake must be a dict subclass, like a real Mollie Payment"
        )
        fake_sdk = sdk or _FakeSDKClient(
            fake_payment,
            self.created_subscriptions,
            self.seen_idempotency_keys,
            live=self.live_subscriptions,
        )
        fake_sdk._payment = fake_payment
        fake_sdk.payments = SimpleNamespace(get=lambda pid: fake_payment)
        with (
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=fake_sdk,
            ),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_api_key",
                return_value="test_dummy_key_for_tests",
            ),
            patch("mollie.api.client.Client", return_value=fake_sdk),
        ):
            with self.set_user("Administrator"):
                return self.service.process_payment_webhook(self.payment_id, {"id": self.payment_id})

    # ------------------------------------------------------------------ tests
    def test_first_payment_with_subscription_setup_creates_mollie_subscription(self):
        """THE regression: a paid recurring first payment must yield a subscription."""
        result = self._run_webhook(interval="3 months")
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")

        self.assertEqual(
            len(self.created_subscriptions),
            1,
            "A recurring donation's first payment must create exactly one Mollie "
            f"subscription; got {self.created_subscriptions!r}",
        )

        sent = self.created_subscriptions[0]["data"]
        self.assertEqual(
            sent["interval"],
            "3 months",
            "The donor's chosen interval must reach Mollie, not a default",
        )
        self.assertEqual(sent["amount"]["value"], f"{self.amount:.2f}")
        self.assertEqual(sent["amount"]["currency"], "EUR")

        # The subscription id must be persisted back onto the donation, or
        # nothing downstream can ever link a recurring charge to this donor.
        persisted = frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id")
        self.assertEqual(
            persisted,
            self.created_subscriptions[0]["id"],
            "Donation.mollie_subscription_id must be persisted after activation",
        )

        # Pins the ordering: activation runs BEFORE the status update precisely
        # so the donation can be stamped Recurring. Reorder the two and this
        # goes red rather than silently regressing to "One-time" -- which is
        # what a recurring donor's first payment was recorded as before #343.
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "status"),
            "Recurring",
            "A donation with a live subscription must be recorded as Recurring",
        )

    def test_first_payment_without_subscription_setup_creates_no_subscription(self):
        """CONTROL 1: sequenceType is first, but nothing asked for a subscription.

        A membership-dues first payment that falls through classification looks
        exactly like this. Split from the oneoff control below so that neither
        guard alone satisfies the pair -- with a single combined control, either
        guard could be deleted and the test would still pass.
        """
        result = self._run_webhook(sequence_type="first", subscription_setup=False)
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        self.assertEqual(self.created_subscriptions, [], "No subscription_setup means no subscription")
        self.assertFalse(frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"))

    def test_oneoff_payment_with_subscription_metadata_creates_no_subscription(self):
        """CONTROL 2: subscription metadata present, but this is not a first payment.

        Only a first payment establishes a mandate, so only a first payment may
        be turned into a subscription.
        """
        result = self._run_webhook(sequence_type="oneoff", subscription_setup=True)
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        self.assertEqual(self.created_subscriptions, [], "A oneoff payment must not create a subscription")
        self.assertFalse(frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"))

    def test_webhook_retry_does_not_create_a_second_subscription(self):
        """Mollie retries webhooks; a retry must not double-subscribe the donor
        NOR undo the first delivery's work."""
        first = self._run_webhook()
        self.assertEqual(first["status"], "success", f"First call failed: {first}")
        self.assertEqual(len(self.created_subscriptions), 1)
        subscription_id = self.created_subscriptions[0]["id"]

        second = self._run_webhook()
        self.assertIn(second["status"], ("success", "skipped"), f"Second call: {second}")
        self.assertEqual(
            len(self.created_subscriptions),
            1,
            "A webhook retry must not create a duplicate Mollie subscription "
            f"(the donor would be charged twice per period); got {self.created_subscriptions!r}",
        )

        # The retry must not revert what the first delivery established. The
        # skip path has to re-publish the subscription id, or the status update
        # that runs after it sees nothing and stamps the donation back to
        # "One-time" -- leaving a donor with a live subscription recorded as a
        # one-off gift.
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "status"),
            "Recurring",
            "A retry must leave the donation Recurring, not revert it to One-time",
        )
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            subscription_id,
            "A retry must not change the recorded subscription id",
        )

    def test_transient_activation_failure_asks_mollie_to_retry(self):
        """If Mollie errors while creating the subscription, the webhook must NOT
        report success.

        There is no sweep that would find an unsubscribed recurring donor later
        (the existing retry job walks Payment Entries and Members, and a donation
        produces neither), so re-delivery is the only recovery path. Returning
        2xx here is what makes the failure permanent and silent.
        """

        class _ExplodingCustomers:
            def get(self, customer_id):
                raise ConnectionError("Mollie API unavailable")

        sdk = _FakeSDKClient(
            None, self.created_subscriptions, self.seen_idempotency_keys, live=self.live_subscriptions
        )
        sdk.customers = _ExplodingCustomers()

        # The Error Logs below are the point of this test, not a side effect:
        # a failed activation must be loud. Declared so the harness's automatic
        # tearDown check does not treat them as an unexplained swallow.
        self.expectErrorLog(
            "Mollie Direct Subscription Creation",
            "Mollie Donation Subscription Activation",
        )

        result = self._run_webhook(sdk=sdk)

        self.assertEqual(self.created_subscriptions, [], "Nothing should have been created")
        self.assertEqual(
            result["status"],
            "error",
            "A transient activation failure must surface as an error so the API layer "
            f"returns non-2xx and Mollie re-delivers; got {result}",
        )
        self.assertFalse(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            "No subscription id may be recorded when none was created",
        )

    def test_lost_response_then_retry_does_not_create_a_second_subscription(self):
        """The worst case: Mollie CREATES the subscription, then the response is lost.

        Nothing is recorded locally, so the `mollie_subscription_id` guard cannot
        help -- it reads NULL on the retry. Only the deterministic
        Idempotency-Key stops a second subscription, and a second subscription
        means the donor is charged twice every period, forever, with only one of
        the two visible to this system.
        """
        self.expectErrorLog(
            "Mollie Direct Subscription Creation",
            "Mollie Donation Subscription Activation",
        )

        # Delivery 1: the create commits at Mollie, then the connection drops.
        sdk1 = _FakeSDKClient(
            None,
            self.created_subscriptions,
            self.seen_idempotency_keys,
            fail_after_create=ConnectionError("connection reset after create"),
            live=self.live_subscriptions,
        )
        first = self._run_webhook(sdk=sdk1)
        self.assertEqual(len(self.created_subscriptions), 1, "Mollie did create one")
        self.assertFalse(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            "Precondition: nothing was recorded locally, so the DB guard is blind",
        )
        self.assertEqual(first["status"], "error", "A lost response is transient -- Mollie should re-deliver")

        # Delivery 2: Mollie's retry. Must NOT produce a second subscription.
        second = self._run_webhook()
        self.assertEqual(
            len(self.created_subscriptions),
            1,
            "A retry after a lost response must not create a second subscription "
            f"(the donor would be charged twice per period); got {self.created_subscriptions!r}",
        )
        self.assertEqual(second["status"], "success")
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            self.created_subscriptions[0]["id"],
            "The retry must adopt and record the subscription Mollie already had",
        )

    def test_late_retry_after_the_idempotency_key_expires_does_not_duplicate(self):
        """The failure the Idempotency-Key alone CANNOT prevent.

        Mollie caches idempotency keys for one hour ("Keys older than 1 hour will
        be removed from our cache"), but retries a failing webhook for twenty-six
        (T+0, 1m, 3m, 7m, 15m, 31m, 1h, 2h, 4h, 26h). Attempts 8, 9 and 10 arrive
        with the key already evicted -- and they are exactly the attempts a
        prolonged failure reaches.

        Scenario: Mollie commits the subscription, the response is lost, nothing
        is recorded locally, and the retry lands after the key has expired. The
        local `mollie_subscription_id` guard reads NULL because there was never
        anything to write, so only a lookup of what Mollie already holds can stop
        a second subscription -- and a second subscription charges this donor
        every period, forever, with just one of the two visible here.
        """
        self.expectErrorLog(
            "Mollie Direct Subscription Creation",
            "Mollie Donation Subscription Activation",
        )

        sdk1 = _FakeSDKClient(
            None,
            self.created_subscriptions,
            self.seen_idempotency_keys,
            fail_after_create=ConnectionError("connection reset after create"),
            live=self.live_subscriptions,
        )
        first = self._run_webhook(sdk=sdk1)
        self.assertEqual(first["status"], "error")
        self.assertEqual(len(self.created_subscriptions), 1, "Mollie did create one")
        self.assertFalse(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            "Precondition: nothing recorded locally, so the DB guard is blind",
        )

        # T+2h: Mollie has evicted the key. The subscription it created is still
        # there -- key caches expire, subscriptions do not.
        self.seen_idempotency_keys.clear()
        self.assertTrue(self.live_subscriptions, "the subscription must still exist at Mollie")

        second = self._run_webhook()

        self.assertEqual(
            len(self.created_subscriptions),
            1,
            "A retry after the idempotency key expired must not create a second "
            "subscription -- the donor would be charged twice every period. "
            f"got {[s['id'] for s in self.created_subscriptions]}",
        )
        self.assertEqual(second["status"], "success")
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"),
            self.created_subscriptions[0]["id"],
            "The retry must adopt the subscription Mollie already holds",
        )

    def test_the_create_carries_a_key_derived_from_the_payment(self):
        """Pins WHY the test above passes: the key must be deterministic per payment.

        A uuid4 (the SDK default) or any per-call value would let the retry create
        a duplicate while this suite stayed green.
        """
        self._run_webhook()
        self.assertEqual(len(self.created_subscriptions), 1)
        self.assertEqual(
            self.created_subscriptions[0]["key"],
            f"donsub-{self.payment_id}",
            "The Idempotency-Key must be derived from the payment id",
        )

    def test_a_deterministic_refusal_is_not_retried(self):
        """An interval Mollie will never accept must not be re-delivered ~10 times.

        `1 year` is not in Mollie's grammar (measured: 422 'The interval unit is
        invalid'); a retry produces the identical refusal.
        """
        self.expectErrorLog(
            "Mollie Direct Subscription Creation",
            "Mollie Donation Subscription Activation",
        )
        result = self._run_webhook(interval="1 year")

        self.assertEqual(self.created_subscriptions, [], "An invalid interval must not be sent")
        self.assertEqual(
            result["status"],
            "success",
            "A permanently-refused activation must NOT ask Mollie to retry; " f"got {result}",
        )
        self.assertEqual(
            result.get("subscription_activation", {}).get("permanent"),
            True,
            "An invalid interval is a permanent refusal",
        )

        # ...but the donor must still be findable. "Recurring with no subscription
        # id" is the only query that can surface donors owed a subscription;
        # stamping them One-time is the invisibility that made #343 last so long.
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "status"),
            "Recurring",
            "A donor who asked for a recurring donation stays Recurring even when "
            "activation failed, so a follow-up sweep can find them",
        )
        self.assertFalse(frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"))
