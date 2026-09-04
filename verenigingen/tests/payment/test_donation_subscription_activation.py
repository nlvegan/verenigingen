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
from urllib.parse import urlparse

import frappe
from mollie.api.error import BadRequestError

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

    It also 400s a reused key whose PAYLOAD differs, which is the other way the
    real API is less forgiving than a naive cache. Without that, the
    mid-ladder-payload-change hazard the production comments argue in prose was
    tested by nothing.
    """

    def __init__(
        self,
        recorder,
        seen_keys,
        *,
        fail_after_create=None,
        live=None,
        create_status="active",
        list_raises=None,
    ):
        self._recorder = recorder
        self._seen_keys = seen_keys
        self._fail_after_create = fail_after_create
        # Every subscription that exists at Mollie, keyed by id -- what
        # subscriptions.list() returns. Survives key expiry, as the real thing does.
        self._live = live if live is not None else {}
        # Mollie's list endpoint returns terminal subscriptions alongside live
        # ones (measured read-only: all five on cst_9yahc9xjkb are `canceled`),
        # so the fake must be able to hold one. A fake that only ever produces
        # `active` cannot express the state where adopting is the WRONG answer.
        self._create_status = create_status
        # Without this, _find_subscription_for_payment's except branch is dead in
        # the whole suite and its Error Log category is pinned by nothing.
        self._list_raises = list_raises

    def list(self):
        if self._list_raises:
            raise self._list_raises
        return list(self._live.values())

    def create(self, data=None, idempotency_key="", **kwargs):
        payload = data if data is not None else kwargs
        if idempotency_key and idempotency_key in self._seen_keys:
            existing, cached_payload = self._seen_keys[idempotency_key]
            if cached_payload != payload:
                # Mollie replays a key only for the request it first saw; a reused
                # key whose parameters differ is answered 400 (documented, and
                # cited by _get_or_create_subscription's own comments -- NOT
                # re-measured here, the probe needs a live account). The `detail`
                # wording is illustrative: production classifies on the 400 status
                # via the exception class, never on this text.
                raise BadRequestError(
                    {
                        "status": 400,
                        "title": "Bad Request",
                        "detail": "Idempotency key already used with different request parameters",
                    },
                    idempotency_key=idempotency_key,
                )
            return self._live[existing]

        subscription_id = f"sub_FAKE{len(self._recorder) + 1:04d}"
        self._recorder.append({"id": subscription_id, "data": payload, "key": idempotency_key})
        created = SimpleNamespace(
            id=subscription_id,
            status=self._create_status,
            metadata=(payload or {}).get("metadata") or {},
        )
        self._live[subscription_id] = created
        if idempotency_key:
            # The payload is stored alongside the id: a key replay is only a
            # replay when the request is the same one.
            self._seen_keys[idempotency_key] = (subscription_id, payload)

        if self._fail_after_create:
            # Mollie committed the subscription; the response never arrived.
            raise self._fail_after_create
        return created


class _FakeCustomer:
    def __init__(
        self,
        customer_id,
        recorder,
        seen_keys,
        fail_after_create=None,
        live=None,
        create_status="active",
        list_raises=None,
    ):
        self.id = customer_id
        self.subscriptions = _FakeSubscriptionsResource(
            recorder,
            seen_keys,
            fail_after_create=fail_after_create,
            live=live,
            create_status=create_status,
            list_raises=list_raises,
        )


class _FakeCustomersResource:
    def __init__(
        self,
        recorder,
        seen_keys,
        fail_after_create=None,
        live=None,
        create_status="active",
        list_raises=None,
    ):
        self._recorder = recorder
        # Shared across every _FakeCustomer this resource hands out, so an
        # Idempotency-Key survives the customers.get() that each webhook
        # delivery performs -- exactly as it does at Mollie.
        self._seen_keys = seen_keys
        self._fail_after_create = fail_after_create
        self._live = live if live is not None else {}
        self._create_status = create_status
        self._list_raises = list_raises

    def get(self, customer_id):
        return _FakeCustomer(
            customer_id,
            self._recorder,
            self._seen_keys,
            self._fail_after_create,
            self._live,
            self._create_status,
            self._list_raises,
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

    # --------------------------------------- a failed status update is not a 200

    def _fail_the_status_save_only(self):
        """Patch that fails the `donation.save()` inside `_update_donation_status`.

        `save` is the collaborator; the code under test is the production body of
        `_update_donation_status` and its caller's handling of the outcome. The
        wrapper swaps `save` on the very donation instance production is about to
        use and then calls the real method, so the try/except under test runs
        unmodified. Nothing else in the delivery is touched -- the Bank
        Transaction, the Journal Entry and the two other history tables stay
        real, which is what makes the assertions below discriminate on *this*
        step rather than on "everything broke".
        """
        svc_cls = type(self.service)
        real = svc_cls._update_donation_status

        def wrapper(svc_self, donation, payment_data):
            def boom(*args, **kwargs):
                raise RuntimeError("injected: Donation.save failed")

            donation.save = boom  # type: ignore[method-assign]
            return real(svc_self, donation, payment_data)

        return patch.object(svc_cls, "_update_donation_status", wrapper)

    def test_a_failed_status_update_is_not_reported_as_success(self):
        """REGRESSION (#464): the webhook must not answer 200 when the donation
        was left unpaid.

        `_update_donation_status` caught its own exception and returned None, and
        the caller discarded even that. So a failing `donation.save()` produced
        `{"status": "success"}` -> HTTP 200 -> Mollie never re-delivers, while the
        donation stays `paid = 0` and `status = One-time` and the Mollie
        subscription goes on charging the donor every month. `paid` and `status`
        are what every report and every reconciliation read.

        Asking for a re-delivery is safe for the same reason it is in #449: the
        money-side steps are each idempotent on the payment id, measured as one
        Journal Entry, one Bank Transaction and a GL debit of the charge amount
        rather than twice it.
        """
        # The injected save failure is logged by production code on purpose; mark it
        # expected so the harness's Error Log guard does not read it as a defect.
        self.expectErrorLog("Mollie Integration Error")
        with self._fail_the_status_save_only():
            result = self._run_webhook()

        self.assertEqual(
            result["status"],
            "error",
            "A failed donation status update must surface as an error so the API "
            f"layer returns non-2xx and Mollie re-delivers; got {result}",
        )
        failures = result.get("history_failures", [])
        self.assertTrue(
            any(f.startswith("donation status") for f in failures),
            f"the failing step must be named in history_failures; got {failures}",
        )
        # The cause must travel with it -- a bare label sends whoever reads the
        # webhook log back to the server log to find out what broke.
        self.assertTrue(
            any("injected: Donation.save failed" in f for f in failures),
            f"the failure reason must reach the response; got {failures}",
        )

        # The failure has to be REAL, not merely reported: assert the database
        # state the donor is left in. Without this the test would pass against a
        # fix that flags an error it did not actually suffer.
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "paid"),
            0,
            "the injected failure must genuinely leave the donation unpaid",
        )

        # The money must still be booked -- that is what makes asking for a
        # re-delivery the right answer rather than a dangerous one.
        self.assertTrue(
            result.get("journal_entry"),
            f"the Journal Entry should still exist for the retry to be safe; got {result}",
        )

    def test_the_happy_path_still_marks_the_donation_paid(self):
        """Control for the test above.

        Without it, "the webhook returns error" would be equally consistent with
        "the new check is wrong and fails on every delivery". Asserts the same two
        fields from the other side.
        """
        result = self._run_webhook()

        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        self.assertNotIn("history_failures", result)
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "paid"),
            1,
            "an undisturbed delivery must leave the donation paid",
        )

    def test_a_redelivery_after_a_status_failure_does_not_double_book(self):
        """The safety claim for THIS failure mode, measured rather than borrowed.

        Its sibling below measures the same thing for a failed history write, but
        the two paths are not interchangeable. When the status save is what failed,
        `Donation.on_update` never fires on the first delivery and DOES fire on the
        second -- and that hook is one of `donor_history`'s three writers. So this
        path has a duplicate-row mechanism the history-failure test cannot cover,
        and it has to be counted here rather than argued from the other test.
        """
        self.expectErrorLog("Mollie Integration Error")
        with self._fail_the_status_save_only():
            first = self._run_webhook()
        self.assertEqual(first["status"], "error", f"setup for this test did not fail: {first}")

        second = self._run_webhook()

        journal_entries = frappe.get_all(
            "Journal Entry", filters={"cheque_no": self.payment_id, "docstatus": ["!=", 2]}, pluck="name"
        )
        bank_transactions = frappe.get_all(
            "Bank Transaction", filters={"reference_number": self.payment_id}, pluck="name"
        )
        self.assertEqual(len(journal_entries), 1, f"the re-delivery double-booked: {journal_entries}")
        self.assertEqual(
            len(bank_transactions), 1, f"the re-delivery duplicated the Bank Transaction: {bank_transactions}"
        )

        # Row count is not evidence of what posted (#382) -- assert on the ledger.
        gl_debit = frappe.db.sql(
            """SELECT COALESCE(SUM(debit), 0) FROM `tabGL Entry`
               WHERE voucher_type = 'Journal Entry' AND voucher_no = %s AND is_cancelled = 0""",
            journal_entries[0],
        )[0][0]
        self.assertEqual(
            float(gl_debit),
            float(self.amount),
            f"the ledger must carry the charge once, not twice; got {gl_debit}",
        )

        # The mechanism unique to this path: the hook that did not fire the first
        # time fires the second, so donor_history is where a duplicate would land.
        history = frappe.get_all(
            "Donation History",
            filters={"parent": self.donor, "parenttype": "Donor", "parentfield": "donor_history"},
            fields=["name", "donation_reference"],
        )
        # Bind the row to THIS donation, so an unrelated fixture row cannot satisfy
        # the count and an absent row cannot pass as "no duplicate".
        mine = [r for r in history if r.donation_reference == self.donation_name]
        self.assertEqual(
            len(mine), 1, f"donor_history must carry this donation exactly once; got {history}"
        )

        # And the retry is CORRECTIVE: it repairs the state the failure left behind.
        self.assertEqual(second["status"], "success", f"the re-delivery should complete: {second}")
        self.assertEqual(
            frappe.db.get_value("Donation", self.donation_name, "paid"),
            1,
            "the re-delivery must leave the donation paid -- that is what makes the retry worth asking for",
        )

    # ------------------------------------------ a failed history write is not a 200

    def _fail_donor_history_only(self):
        """Patch that fails the donor_history write and leaves every other one real.

        The manager is a collaborator here, not the code under test: what is under
        test is the WEBHOOK's handling of a False return. Failing only the Donor
        path keeps the donation and member writes real, so the assertion below
        discriminates on which table failed rather than on "everything broke".
        """
        from verenigingen.utils.member_financial_history_manager import (
            MemberFinancialHistoryManager,
        )

        real = MemberFinancialHistoryManager.add_or_update_entry

        def failing(manager_self, *args, **kwargs):
            if manager_self.doc.doctype == "Donor":
                return False
            return real(manager_self, *args, **kwargs)

        return patch.object(MemberFinancialHistoryManager, "add_or_update_entry", failing)

    def test_a_failed_donor_history_write_is_not_reported_as_success(self):
        """REGRESSION (#449): the webhook must not answer 200 when the history
        write failed.

        `add_or_update_entry` returns False -- it does not raise -- for a builder
        that returns None or raises, a TimestampMismatchError surviving five
        attempts, an `update_child_table` failing three retries, and anything its
        outer `except Exception` catches. `_update_donor_record` computed that flag
        and then returned True unconditionally, and the caller discarded even that,
        so every one of those became `{"status": "success"}` -> HTTP 200 -> Mollie
        never re-delivers -> the donation is missing from `donor_history`
        permanently. Per #425 nothing repairs it afterwards.
        """
        with self._fail_donor_history_only():
            result = self._run_webhook()

        self.assertEqual(
            result["status"],
            "error",
            "A failed donor_history write must surface as an error so the API layer "
            f"returns non-2xx and Mollie re-delivers; got {result}",
        )
        self.assertIn("donor_history", result.get("history_failures", []))

        # The money must still have been booked -- that is what makes asking for a
        # re-delivery the right answer rather than a dangerous one.
        self.assertTrue(
            result.get("journal_entry"),
            f"the Journal Entry should still exist for the retry to be safe; got {result}",
        )

    def test_the_happy_path_still_succeeds_and_writes_donor_history(self):
        """Control for the test above: without the injected failure the same run
        answers success, and the WEBHOOK's own write is what lands.

        Without a control, "the webhook returns error" would be equally consistent
        with "the new check is wrong and fails always".

        Asserting the row merely EXISTS would prove nothing, and the first version of
        this test made exactly that mistake. `donor_history` has three writers, and
        the webhook's is the last of them:

        1. `Donation.after_insert` -> `donation_history_manager.on_donation_insert`
        2. `Donation.on_update`    -> `...on_donation_update`, which fires from the
           `donation.save()` inside `_update_donation_status` -- i.e. immediately
           BEFORE `_update_donor_record` runs
        3. `_update_donor_record` itself, the code under test

        So the row is already present and already populated by the time the webhook
        writes. Stubbing the webhook's write to a no-op leaves the assertion green.

        The one field that separates them is `donation_date`. The hook copies
        `Donation.donation_date`; the webhook writes Mollie's `paid_at`. The fixture
        set both to 2025-04-10, which is why nothing discriminated. Repointing the
        donation's own date makes the assertion bind writer 3 alone.
        """
        mollie_paid_date = "2025-04-10"  # what the fake payment reports as paidAt
        donation_own_date = "2024-01-02"  # deliberately different
        frappe.db.set_value("Donation", self.donation_name, "donation_date", donation_own_date)
        frappe.db.commit()

        result = self._run_webhook()
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        # The success payload never sets this key; comparing it to [] cannot fail.
        self.assertNotIn("history_failures", result)

        donor_id = frappe.db.get_value("Donation", self.donation_name, "donor")
        row = frappe.get_all(
            "Donation History",
            filters={
                "parent": donor_id,
                "parenttype": "Donor",
                "donation_reference": self.donation_name,
            },
            fields=["donation_date"],
        )
        self.assertEqual(len(row), 1, "exactly one donor_history row for this donation")
        self.assertEqual(
            str(row[0]["donation_date"]),
            mollie_paid_date,
            "donor_history must carry Mollie's paid_at, which only _update_donor_record "
            f"writes -- {donation_own_date} would mean the doc-event hook's value survived "
            "and the webhook's own write did nothing",
        )

    def test_a_redelivery_after_a_history_failure_does_not_double_book(self):
        """The safety claim behind returning non-2xx, measured rather than argued.

        `is_fully_processed()` is permanently false for donations (#344), so every
        re-delivery lands back on the new-payment path -- the code says so itself.
        Asking Mollie to retry is therefore only safe if the money-side steps are
        individually idempotent. They claim to be, on the payment id:
        `bank_transaction_creator._find_matching_bank_transaction` (the create-time
        gate since #383/#823) matches `Bank Transaction.reference_number`, and the
        donation Journal Entry creator matches `Journal Entry.cheque_no` (that
        doctype has no `reference_no`).

        So: fail the history write, then re-deliver cleanly, and count the rows.
        """
        with self._fail_donor_history_only():
            first = self._run_webhook()
        self.assertEqual(first["status"], "error", f"setup for this test did not fail: {first}")

        second = self._run_webhook()

        journal_entries = frappe.get_all(
            "Journal Entry", filters={"cheque_no": self.payment_id, "docstatus": ["!=", 2]}, pluck="name"
        )
        bank_transactions = frappe.get_all(
            "Bank Transaction", filters={"reference_number": self.payment_id}, pluck="name"
        )

        self.assertEqual(len(journal_entries), 1, f"the re-delivery double-booked: {journal_entries}")
        # Row count alone is not proof of what posted -- this repo already knows
        # docstatus is not evidence a JE posted (#382). Assert on the ledger.
        gl_debit = frappe.db.sql(
            """SELECT COALESCE(SUM(debit), 0) FROM `tabGL Entry`
               WHERE voucher_type = 'Journal Entry' AND voucher_no = %s AND is_cancelled = 0""",
            journal_entries[0],
        )[0][0]
        self.assertEqual(
            float(gl_debit),
            float(self.amount),
            f"the ledger must carry the charge once, not twice; got {gl_debit}",
        )
        self.assertEqual(
            len(bank_transactions), 1, f"the re-delivery duplicated the Bank Transaction: {bank_transactions}"
        )
        self.assertEqual(
            second["status"],
            "success",
            f"the re-delivery should complete what was missing; got {second}",
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

    def test_a_reused_idempotency_key_with_a_changed_payload_is_not_retried(self):
        """The design requirement that reached no task (design.md:173).

        Mollie 400s a reused Idempotency-Key whose parameters differ. That is
        exactly what a deploy landing mid-ladder produces: attempt 1 sent the
        old payload, attempt 5 sends one carrying webhookUrl, under the same
        deterministic key ``donsub-<payment id>``. The 400 used to fall into the
        broad except and return an error dict with NO reason, and an
        unrecognised reason is treated as retryable -- so Mollie would run the
        remaining attempts of its 10-attempt / 26-hour ladder against a refusal
        that is identical every time.

        The setup below is the one case the durable guard cannot cover: Mollie
        holds the key from the earlier attempt, and the subscription it created
        carries no ``metadata.payment_id`` fingerprint, so
        _find_subscription_for_payment cannot adopt it and the create is reached.

        Control lives one test up the file: test_transient_activation_failure_
        asks_mollie_to_retry drives a ConnectionError through the same code and
        gets permanent=False, so "everything is permanent now" would be caught.
        """
        self.expectErrorLog(
            "Mollie Direct Subscription Creation",
            "Mollie Donation Subscription Activation",
        )

        # An earlier attempt in this same ladder, before the deploy: the key is
        # in Mollie's cache against a payload that had no webhookUrl, and the
        # subscription it produced carries no payment_id fingerprint.
        stale = SimpleNamespace(id="sub_PREDEPLOY", status="active", metadata={})
        self.live_subscriptions["sub_PREDEPLOY"] = stale
        self.seen_idempotency_keys[f"donsub-{self.payment_id}"] = (
            "sub_PREDEPLOY",
            {"interval": "3 months", "description": "an older payload"},
        )

        result = self._run_webhook(interval="3 months")

        self.assertEqual(
            self.created_subscriptions, [], "the 400 means Mollie created nothing on this attempt"
        )
        activation = result.get("subscription_activation", {})
        self.assertEqual(
            activation.get("reason"),
            "idempotency_key_conflict",
            f"the 400 must be named, or it cannot be classified: {result}",
        )
        self.assertIs(
            activation.get("permanent"),
            True,
            "a 400 is refused identically on every redelivery; retrying it burns the ladder",
        )
        self.assertEqual(
            result["status"],
            "success",
            f"the payment is recorded and Mollie must NOT be asked to re-deliver; got {result}",
        )
        # Same reasoning as the invalid-interval test: the donor stays findable.
        self.assertEqual(frappe.db.get_value("Donation", self.donation_name, "status"), "Recurring")
        self.assertFalse(frappe.db.get_value("Donation", self.donation_name, "mollie_subscription_id"))


class TestSubscriptionCarriesAReachableWebhook(EnhancedTestCase):
    """Without a webhookUrl Mollie charges the donor and tells nobody. Issue #345.

    Measured: every subscription in the Mollie test account created by
    ``_activate_direct_subscription_after_first_payment`` carries
    ``webhookUrl: None``.

    The URL must be ``get_webhook_url()`` -- the guest-reachable payment webhook
    (``mollie/api/webhooks.py::mollie_payment_webhook``) -- and explicitly not
    ``get_subscription_webhook_url()``: that endpoint is the member-dues machine,
    unreachable for a donation on three independent counts (#343).
    """

    # ------------------------------------------------------------------ setup
    def _setup_donor(self):
        """EnhancedTestCase's factory has no donor helper; build one inline."""
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Hook Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"hook.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_recurring_donation(self):
        """A Donation configured the way the donation-agreement helper reads it."""
        donation = frappe.new_doc("Donation")
        donation.donor = self._setup_donor()
        donation.donation_date = frappe.utils.nowdate()
        donation.amount = 50
        donation.mode_of_payment = "Mollie"
        donation.status = "Recurring"
        donation.recurring_frequency = "Monthly"
        donation.mollie_customer_id = "cst_FAKECUSTOMER"
        # payment_id is UNIQUE -- never a literal.
        donation.payment_id = f"tr_{frappe.generate_hash(length=12)}"
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation.name

    def _setup_gateway(self, recorder, seen_keys, live, create_status="active", list_raises=None):
        return SimpleNamespace(
            client=SimpleNamespace(
                customers=_FakeCustomersResource(recorder, seen_keys, None, live, create_status, list_raises)
            )
        )

    def _create_direct_subscription(self, recorder, seen_keys, live):
        """Run _activate_direct_subscription_after_first_payment against the fakes."""
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        payment = _FakePayment(
            f"tr_{frappe.generate_hash(length=12)}",
            "50.00",
            f"Assoc-Dnt-{frappe.generate_hash(length=6)}",
            sequence_type="first",
            subscription_setup=True,
        )
        return pg._activate_direct_subscription_after_first_payment(
            self._setup_gateway(recorder, seen_keys, live), payment
        )

    # ------------------------------------------------------------------ tests
    def test_direct_subscription_payload_carries_the_payment_webhook(self):
        recorder, seen_keys, live = [], {}, {}
        result = self._create_direct_subscription(recorder, seen_keys, live)

        self.assertEqual(result["status"], "success", result.get("message"))
        self.assertEqual(len(recorder), 1)
        self.assertEqual(
            recorder[0]["data"].get("webhookUrl"),
            frappe.get_single("Mollie Settings").get_webhook_url(),
            "Mollie has nowhere to announce this subscription's charges",
        )

    def test_the_webhook_the_payload_carries_is_guest_reachable(self):
        """The property that actually matters: Mollie can POST to it at all.

        This replaces an assertNotEqual against get_subscription_webhook_url(),
        which was logically implied by the sibling test above in every state and
        so had no red state of its own.

        Mollie authenticates nothing -- it just POSTs ``id=tr_...`` -- so a
        webhookUrl on an endpoint that is not ``allow_guest`` answers 403 and the
        charge is announced to nobody. Measured on test_site_1:
        ``mollie_payment_webhook`` IS in ``frappe.guest_methods``;
        ``mollie_subscription_webhook`` (the member-dues endpoint, #343) is NOT.

        Red under the Step 7 mutation, and red if anyone ever repoints
        get_webhook_url() at a non-guest endpoint.
        """
        recorder, seen_keys, live = [], {}, {}
        self._create_direct_subscription(recorder, seen_keys, live)

        self.assertEqual(len(recorder), 1)
        url = recorder[0]["data"].get("webhookUrl")
        self.assertIsNotNone(url, "Mollie has nowhere to announce this subscription's charges")

        dotted = urlparse(url).path.split("/api/method/", 1)[1]
        # frappe.get_attr(dotted) is evaluated BEFORE frappe.guest_methods is
        # read, and resolving it imports the module, which runs the
        # @frappe.whitelist(allow_guest=True) decorator that registers the
        # function. So this cannot pass or fail on import ordering. Do not
        # "simplify" it by hoisting the lookup out of the assertIn call.
        self.assertIn(
            frappe.get_attr(dotted),
            frappe.guest_methods,
            f"{dotted} is not allow_guest; Mollie's unauthenticated POST would get a 403 "
            "and the charge would never be announced",
        )

    def test_donation_agreement_subscription_payload_carries_it_too(self):
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donation_name = self._setup_recurring_donation()
        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            f"tr_{frappe.generate_hash(length=12)}",
            "50.00",
            donation_name,
            sequence_type="first",
            subscription_setup=True,
        )

        result = pg._activate_donation_subscription_after_first_payment(
            self._setup_gateway(recorder, seen_keys, live), payment
        )

        self.assertEqual(result["status"], "success", result.get("message"))
        self.assertEqual(len(recorder), 1)
        self.assertEqual(
            recorder[0]["data"].get("webhookUrl"),
            frappe.get_single("Mollie Settings").get_webhook_url(),
        )
        # The direct site has this assertion; this one did not. A uuid4 (the SDK
        # default) or any per-call value would let a retry duplicate while the
        # suite stayed green.
        self.assertEqual(
            recorder[0]["key"],
            f"donagr-{payment.id}",
            "The Idempotency-Key must be derived from the payment id",
        )

    def test_donation_agreement_helper_adopts_an_existing_subscription(self):
        """The durable guard across idempotency-key expiry.

        Mollie caches keys for one hour against a retry ladder that runs
        twenty-six, so attempts 8-10 arrive unprotected. Clearing seen_keys while
        `live` survives is exactly that: a fake whose key cache never expires
        would report the durable guard as working when it is not.
        """
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donation_name = self._setup_recurring_donation()
        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            f"tr_{frappe.generate_hash(length=12)}",
            "50.00",
            donation_name,
            sequence_type="first",
            subscription_setup=True,
        )

        def _deliver():
            return pg._activate_donation_subscription_after_first_payment(
                self._setup_gateway(recorder, seen_keys, live), payment
            )

        first = _deliver()
        self.assertEqual(first["status"], "success", first.get("message"))
        self.assertEqual(len(recorder), 1, "the first delivery must create exactly one")

        seen_keys.clear()  # the key cache expires; the subscription does not
        self.assertTrue(live, "the subscription must still exist at Mollie")

        second = _deliver()
        self.assertEqual(second["status"], "success", second.get("message"))
        self.assertEqual(first["subscription_id"], second["subscription_id"])
        self.assertEqual(len(recorder), 1, "a late retry created a second subscription")

    def _deliver_against_a_seeded_subscription(self, seeded_status):
        """One delivery against a subscription Mollie ALREADY holds for this payment.

        ``seeded_status`` is the status of that pre-existing subscription and is
        the ONLY difference between the two tests below -- what makes them a
        discriminating pair rather than two assertions. Anything the helper
        creates is created ``active``, so a message about creating a live
        subscription stays true of the fake.
        """
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donation_name = self._setup_recurring_donation()
        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            f"tr_{frappe.generate_hash(length=12)}",
            "50.00",
            donation_name,
            sequence_type="first",
            subscription_setup=True,
        )

        seeded_id = f"sub_SEEDED{frappe.generate_hash(length=6)}"
        live[seeded_id] = SimpleNamespace(
            id=seeded_id,
            status=seeded_status,
            metadata={"payment_id": payment.id},
        )

        result = pg._activate_donation_subscription_after_first_payment(
            self._setup_gateway(recorder, seen_keys, live), payment
        )
        self.assertEqual(result["status"], "success", result.get("message"))
        return result, recorder, donation_name, seeded_id

    def test_a_seeded_active_subscription_is_adopted(self):
        """CONTROL for the canceled case below: a LIVE subscription IS adopted."""
        result, recorder, donation_name, seeded_id = self._deliver_against_a_seeded_subscription("active")

        self.assertEqual(recorder, [], "an adoptable subscription existed; nothing should be created")
        self.assertEqual(result["subscription_id"], seeded_id)
        self.assertEqual(
            frappe.db.get_value("Donation", donation_name, "mollie_subscription_id"),
            seeded_id,
            "the adopted subscription must be the one recorded on the donation",
        )

    def test_a_canceled_subscription_is_not_adopted(self):
        """Adopting a canceled subscription records the donation as subscribed to
        something Mollie will never charge.

        Mollie's list endpoint returns canceled subscriptions alongside live ones
        (measured read-only: all five on cst_9yahc9xjkb are `canceled`), and it
        rejects a server-side `status` filter, so an unfiltered guard will match
        one. It would then write that id to Donation.mollie_subscription_id and
        return status "success" -- silently, with no retry left to repair it.
        That is precisely the failure this branch exists to eliminate, so the
        guard must decline and create a live subscription instead.
        """
        result, recorder, donation_name, seeded_id = self._deliver_against_a_seeded_subscription("canceled")

        self.assertEqual(len(recorder), 1, "the guard must create a live subscription, not adopt a dead one")
        created_id = recorder[0]["id"]
        self.assertNotEqual(result["subscription_id"], seeded_id, "the canceled subscription was adopted")
        self.assertEqual(result["subscription_id"], created_id)

        # The stated harm, asserted directly rather than by proxy: the donation
        # must not be left pointing at a subscription Mollie will never charge.
        self.assertEqual(
            frappe.db.get_value("Donation", donation_name, "mollie_subscription_id"),
            created_id,
            "the donation is recorded as subscribed to a canceled subscription; "
            "Mollie will never charge it and nothing will ever notice",
        )

    def test_a_listing_failure_is_logged_under_the_calling_helpers_category(self):
        """_find_subscription_for_payment used to hardcode the DIRECT category.

        A listing failure on the donation-agreement path was therefore filed
        under "Mollie Direct Subscription Creation" -- invisible to anyone
        grepping Error Log by the category the rest of that helper uses. Nothing
        pinned that, because the fake's list() could not fail: the except branch
        was dead in the whole suite under either category.

        The documented behaviour is also asserted here: a listing failure must
        NOT stop a first-time donor subscribing, so the create still happens.
        """
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        self.expectErrorLog("Mollie Donation Subscription Creation")

        donation_name = self._setup_recurring_donation()
        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            f"tr_{frappe.generate_hash(length=12)}",
            "50.00",
            donation_name,
            sequence_type="first",
            subscription_setup=True,
        )

        started = frappe.utils.now()
        result = pg._activate_donation_subscription_after_first_payment(
            self._setup_gateway(
                recorder, seen_keys, live, list_raises=ConnectionError("Mollie API unavailable while listing")
            ),
            payment,
        )

        self.assertEqual(result["status"], "success", result.get("message"))
        self.assertEqual(len(recorder), 1, "a listing failure must not stop a first-time donor subscribing")

        # frappe.log_error(message, title) puts the category in whichever field
        # its title/message swap-detection picks, so match across both rather
        # than pinning one.
        rows = frappe.get_all("Error Log", filters={"creation": [">=", started]}, fields=["method", "error"])
        blob = " ".join(f"{r.method} {r.error}" for r in rows if payment.id in f"{r.method} {r.error}")
        self.assertIn(
            "Mollie Donation Subscription Creation",
            blob,
            "the listing failure was not filed under the donation-agreement category",
        )
        # The discriminating half: this is what the old hardcoded category did.
        self.assertNotIn(
            "Mollie Direct Subscription Creation",
            blob,
            "the donation-agreement path filed its listing failure under the DIRECT category",
        )
