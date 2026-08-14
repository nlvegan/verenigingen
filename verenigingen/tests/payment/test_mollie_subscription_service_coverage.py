"""
Coverage for the SubscriptionService methods not exercised by the existing
consolidation / amendment-sync suites:

* get_subscription_status (full field mapping incl. is_active/is_canceled)
* process_subscription_payment (membership / donation / unknown / not-paid /
  no-customer routing)
* list_member_subscriptions (no customer, with subscription, error swallow)
* list_subscriptions (limit clamping, active_only filter, customer-not-found
  error, generic error sanitisation)
* admin_cancel_subscription (validation, already-cancelled tolerance, hard error)
* update_subscription_mandate (validation, PATCH success, error re-raise)
* _find_subscription_for_payment (metadata + customer-metadata fallbacks, throw)

Plus MollieSubscriptionSyncService helpers:
* _get_subscription_parameters (all amendment types)
* _verify_subscription_amount (match, retry-success, mismatch)

The Mollie SDK / MollieClient is the external boundary, replaced by fakes; no
live Mollie credentials are needed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError
from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
    BILLING_INTERVAL_TO_MOLLIE_FORMAT,
    MollieSubscriptionSyncService,
)
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService

# ---------------------------------------------------------------------------
# Fakes for the MollieClient boundary.
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API. These fakes mimic only the slice of MollieClient the service
# calls; everything below the client is exercised for real.
# ---------------------------------------------------------------------------


def _sub(
    sub_id="sub_1",
    customer_id="cst_1",
    status="active",
    value="25.00",
    currency="EUR",
    interval="1 month",
    next_payment_date="2026-07-01",
    description="Dues",
    metadata=None,
    webhook_url="https://x/hook",
    mandate_id="mdt_1",
):
    return SimpleNamespace(
        id=sub_id,
        customer_id=customer_id,
        status=status,
        amount={"value": value, "currency": currency},
        interval=interval,
        next_payment_date=next_payment_date,
        description=description,
        metadata=metadata or {},
        webhook_url=webhook_url,
        mandate_id=mandate_id,
    )


class _FakeMollieClient:
    """Controllable stand-in for MollieClient (subscription-level methods)."""

    def __init__(
        self,
        subscription=None,
        payment=None,
        customer=None,
        test_mode=False,
        sdk_client=None,
        cancel_raises=None,
    ):
        self._subscription = subscription
        self._payment = payment
        self._customer = customer
        self._test_mode = test_mode
        self.sdk_client = sdk_client
        self._cancel_raises = cancel_raises
        self.cancelled = []

    def get_subscription(self, customer_id, subscription_id):
        return self._subscription

    def get_payment(self, payment_id):
        return self._payment

    def get_customer(self, customer_id):
        return self._customer

    def is_test_mode(self):
        return self._test_mode

    def cancel_subscription(self, customer_id, subscription_id):
        if self._cancel_raises:
            raise self._cancel_raises
        self.cancelled.append((customer_id, subscription_id))
        return _sub(sub_id=subscription_id, status="canceled")


class TestGetSubscriptionStatus(EnhancedTestCase):
    def test_active_subscription_maps_all_fields(self):
        client = _FakeMollieClient(subscription=_sub(status="active"))
        service = SubscriptionService(client=client)

        status = service.get_subscription_status("cst_1", "sub_1")

        self.assertEqual(status["status"], "active")
        self.assertTrue(status["is_active"])
        self.assertFalse(status["is_canceled"])
        self.assertEqual(status["amount"], 25.0)
        self.assertEqual(status["currency"], "EUR")
        self.assertEqual(status["mandate_id"], "mdt_1")

    def test_canceled_subscription_flags(self):
        client = _FakeMollieClient(subscription=_sub(status="suspended"))
        service = SubscriptionService(client=client)

        status = service.get_subscription_status("cst_1", "sub_1")

        self.assertFalse(status["is_active"])
        self.assertTrue(status["is_canceled"])


class TestProcessSubscriptionPayment(EnhancedTestCase):
    def _payment(self, status="paid", customer_id="cst_1", metadata=None, pid="tr_1"):
        return SimpleNamespace(
            id=pid,
            status=status,
            customer_id=customer_id,
            amount={"value": "25.00", "currency": "EUR"},
            metadata=metadata or {},
        )

    def test_not_paid_raises(self):
        client = _FakeMollieClient(payment=self._payment(status="open"))
        service = SubscriptionService(client=client)
        with self.assertRaises(MollieIntegrationError):
            service.process_subscription_payment("tr_1")

    def test_no_customer_raises(self):
        client = _FakeMollieClient(payment=self._payment(customer_id=None))
        service = SubscriptionService(client=client)
        with self.assertRaises(MollieIntegrationError):
            service.process_subscription_payment("tr_1")

    def test_membership_payment_routes_to_membership_processor(self):
        payment = self._payment(metadata={"subscription_type": "membership_dues", "subscription_id": "sub_1"})
        client = _FakeMollieClient(payment=payment)
        service = SubscriptionService(client=client)

        result = service.process_subscription_payment("tr_1")

        self.assertEqual(result["type"], "membership_subscription")
        self.assertEqual(result["amount"], 25.0)
        self.assertTrue(result["processed"])

    def test_donation_payment_routes_to_donation_processor(self):
        payment = self._payment(metadata={"subscription_type": "recurring_donation"})
        client = _FakeMollieClient(payment=payment)
        service = SubscriptionService(client=client)

        result = service.process_subscription_payment("tr_1")

        self.assertEqual(result["type"], "donation_subscription")

    def test_unknown_subscription_type_raises(self):
        payment = self._payment(metadata={"subscription_type": "lottery"})
        client = _FakeMollieClient(payment=payment)
        service = SubscriptionService(client=client)
        with self.assertRaises(MollieIntegrationError):
            service.process_subscription_payment("tr_1")

    def test_falls_back_to_customer_metadata_membership(self):
        payment = self._payment(metadata={})  # no subscription_type
        customer = SimpleNamespace(metadata={"member_id": "MEM-1"})
        client = _FakeMollieClient(payment=payment, customer=customer)
        service = SubscriptionService(client=client)

        result = service.process_subscription_payment("tr_1")

        self.assertEqual(result["type"], "membership_subscription")

    def test_falls_back_to_customer_metadata_donation(self):
        payment = self._payment(metadata={})
        customer = SimpleNamespace(metadata={"donor_id": "DON-1"})
        client = _FakeMollieClient(payment=payment, customer=customer)
        service = SubscriptionService(client=client)

        result = service.process_subscription_payment("tr_1")

        self.assertEqual(result["type"], "donation_subscription")

    def test_undeterminable_subscription_type_raises(self):
        payment = self._payment(metadata={})
        customer = SimpleNamespace(metadata={})
        client = _FakeMollieClient(payment=payment, customer=customer)
        service = SubscriptionService(client=client)
        with self.assertRaises(MollieIntegrationError):
            service.process_subscription_payment("tr_1")


class TestListMemberSubscriptions(EnhancedTestCase):
    def _make_member(self, customer_id=None, subscription_id=None):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="List",
            last_name=f"Sub{token}",
            email=f"list-{token}@example.com",
            birth_date="1990-01-01",
        )
        values = {}
        if customer_id:
            values["mollie_customer_id"] = customer_id
        if subscription_id:
            values["mollie_subscription_id"] = subscription_id
        if values:
            frappe.db.set_value("Member", member.name, values, update_modified=False)
        member.reload()
        return member

    def test_no_customer_returns_empty(self):
        member = self._make_member()
        service = SubscriptionService(client=_FakeMollieClient())
        self.assertEqual(service.list_member_subscriptions(member.name), [])

    def test_with_subscription_returns_info(self):
        member = self._make_member(customer_id="cst_M", subscription_id="sub_M")
        client = _FakeMollieClient(subscription=_sub(sub_id="sub_M"))
        service = SubscriptionService(client=client)

        subs = service.list_member_subscriptions(member.name)

        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["id"], "sub_M")
        self.assertEqual(subs[0]["type"], "membership_dues")

    def test_subscription_fetch_error_is_swallowed(self):
        member = self._make_member(customer_id="cst_M", subscription_id="sub_M")

        class _Raising(_FakeMollieClient):
            def get_subscription(self, customer_id, subscription_id):
                raise RuntimeError("mollie down")

        service = SubscriptionService(client=_Raising())
        # Error is logged, empty list returned.
        self.assertEqual(service.list_member_subscriptions(member.name), [])


class _FakeSubscriptionsList:
    def __init__(self, subs):
        self._subs = subs

    def list(self, limit=50):
        return self._subs


class _FakeCustomerObj:
    def __init__(self, subs):
        self.subscriptions = _FakeSubscriptionsList(subs)


class _FakeCustomers:
    def __init__(self, subs, error=None):
        self._subs = subs
        self._error = error

    def get(self, customer_id):
        if self._error:
            raise self._error
        return _FakeCustomerObj(self._subs)


class _FakeSDK:
    def __init__(self, subs=None, error=None):
        self.customers = _FakeCustomers(subs or [], error)


class TestListSubscriptions(EnhancedTestCase):
    def _sdk_sub(self, sub_id, status="active", value="25.00"):
        return SimpleNamespace(
            id=sub_id,
            status=status,
            amount={"value": value, "currency": "EUR"},
            interval="1 month",
            description="Dues",
            created_at="2026-01-01",
            next_payment_date="2026-07-01",
            canceled_at=None,
            _links={},
        )

    def test_empty_customer_id_raises(self):
        service = SubscriptionService(client=_FakeMollieClient())
        with self.assertRaises(ValueError):
            service.list_subscriptions("")

    def test_active_only_filters_inactive(self):
        sdk = _FakeSDK(subs=[self._sdk_sub("sub_a"), self._sdk_sub("sub_b", status="canceled")])
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)

        result = service.list_subscriptions("cst_1", active_only=True)

        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["subscriptions"][0]["id"], "sub_a")

    def test_active_only_false_includes_all(self):
        sdk = _FakeSDK(subs=[self._sdk_sub("sub_a"), self._sdk_sub("sub_b", status="canceled")])
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)

        result = service.list_subscriptions("cst_1", active_only=False)

        self.assertEqual(result["total_found"], 2)
        self.assertEqual(result["subscriptions"][0]["amount_value"], 25.0)

    def test_invalid_limit_clamped_to_default(self):
        sdk = _FakeSDK(subs=[])
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)

        result = service.list_subscriptions("cst_1", limit=99999, active_only=False)
        self.assertEqual(result["limit"], 50)

        result2 = service.list_subscriptions("cst_1", limit="garbage", active_only=False)
        self.assertEqual(result2["limit"], 50)

    def test_customer_not_found_error_is_contextual(self):
        sdk = _FakeSDK(error=RuntimeError("No customer exists with token cst_1"))
        client = _FakeMollieClient(sdk_client=sdk, test_mode=True)
        service = SubscriptionService(client=client)

        result = service.list_subscriptions("cst_1")

        self.assertIsNotNone(result["error"])
        self.assertIn("test mode", result["error"])

    def test_generic_error_is_sanitised(self):
        sdk = _FakeSDK(error=RuntimeError("connection reset"))
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)

        result = service.list_subscriptions("cst_1")
        self.assertIsNotNone(result["error"])


class TestAdminCancelSubscription(EnhancedTestCase):
    def test_validation_errors(self):
        service = SubscriptionService(client=_FakeMollieClient())
        with self.assertRaises(ValueError):
            service.admin_cancel_subscription("", "sub_1")
        with self.assertRaises(ValueError):
            service.admin_cancel_subscription("cst_1", "")
        with self.assertRaises(ValueError):
            service.admin_cancel_subscription("cst_1", "sub_1", reason="")

    def test_successful_cancel_returns_success_and_records(self):
        client = _FakeMollieClient()
        service = SubscriptionService(client=client)

        result = service.admin_cancel_subscription("cst_1", "sub_1", reason="cleanup")

        self.assertEqual(result["status"], "success")
        self.assertEqual(client.cancelled, [("cst_1", "sub_1")])

    def test_already_cancelled_returns_warning(self):
        client = _FakeMollieClient(cancel_raises=RuntimeError("Subscription not found"))
        service = SubscriptionService(client=client)

        result = service.admin_cancel_subscription("cst_1", "sub_gone", reason="cleanup")

        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["subscription_id"], "sub_gone")

    def test_hard_error_reraises(self):
        client = _FakeMollieClient(cancel_raises=RuntimeError("internal server error"))
        service = SubscriptionService(client=client)
        with self.assertRaises(RuntimeError):
            service.admin_cancel_subscription("cst_1", "sub_1", reason="cleanup")


class _FakeSubscriptionsForUpdate:
    def __init__(self, recorder, old_mandate="mdt_OLD"):
        self._recorder = recorder
        self._old_mandate = old_mandate

    def get(self, subscription_id):
        return SimpleNamespace(mandateId=self._old_mandate)

    def update(self, subscription_id, payload):
        self._recorder.append((subscription_id, payload))


class _FakeCustomerForUpdate:
    def __init__(self, recorder, old_mandate="mdt_OLD", update_raises=None):
        self._update_raises = update_raises
        self.subscriptions = _FakeSubscriptionsForUpdate(recorder, old_mandate)
        if update_raises:
            def _raise(subscription_id, payload):
                raise update_raises
            self.subscriptions.update = _raise


class _FakeSDKForUpdate:
    def __init__(self, recorder, old_mandate="mdt_OLD", update_raises=None):
        self._recorder = recorder
        self._old_mandate = old_mandate
        self._update_raises = update_raises

    @property
    def customers(self):
        return SimpleNamespace(
            get=lambda cid: _FakeCustomerForUpdate(self._recorder, self._old_mandate, self._update_raises)
        )


class TestUpdateSubscriptionMandate(EnhancedTestCase):
    def test_validation_errors(self):
        service = SubscriptionService(client=_FakeMollieClient())
        with self.assertRaises(ValueError):
            service.update_subscription_mandate("", "sub_1", "mdt_new")
        with self.assertRaises(ValueError):
            service.update_subscription_mandate("cst_1", "sub_1", "")

    def test_successful_patch_records_new_mandate(self):
        recorder = []
        sdk = _FakeSDKForUpdate(recorder)
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)

        result = service.update_subscription_mandate("cst_1", "sub_1", "mdt_NEW")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_mandate_id"], "mdt_NEW")
        self.assertEqual(recorder, [("sub_1", {"mandateId": "mdt_NEW"})])

    def test_patch_error_reraises(self):
        sdk = _FakeSDKForUpdate([], update_raises=RuntimeError("patch failed"))
        client = _FakeMollieClient(sdk_client=sdk)
        service = SubscriptionService(client=client)
        with self.assertRaises(RuntimeError):
            service.update_subscription_mandate("cst_1", "sub_1", "mdt_NEW")


class TestFindSubscriptionForPayment(EnhancedTestCase):
    def test_metadata_subscription_type(self):
        service = SubscriptionService(client=_FakeMollieClient())
        payment = SimpleNamespace(
            id="tr_1", metadata={"subscription_type": "membership_dues", "subscription_id": "sub_X"}
        )
        info = service._find_subscription_for_payment("cst_1", payment)
        self.assertEqual(info["type"], "membership_dues")
        self.assertEqual(info["id"], "sub_X")

    def test_customer_metadata_member(self):
        customer = SimpleNamespace(metadata={"member_id": "MEM-1"})
        client = _FakeMollieClient(customer=customer)
        service = SubscriptionService(client=client)
        payment = SimpleNamespace(id="tr_1", metadata={})
        info = service._find_subscription_for_payment("cst_1", payment)
        self.assertEqual(info["type"], "membership_dues")

    def test_undeterminable_raises(self):
        customer = SimpleNamespace(metadata={})
        client = _FakeMollieClient(customer=customer)
        service = SubscriptionService(client=client)
        payment = SimpleNamespace(id="tr_1", metadata={})
        with self.assertRaises(MollieIntegrationError):
            service._find_subscription_for_payment("cst_1", payment)


# ---------------------------------------------------------------------------
# MollieSubscriptionSyncService helper coverage
# ---------------------------------------------------------------------------

class TestGetSubscriptionParameters(EnhancedTestCase):
    """_get_subscription_parameters across amendment types."""

    def _service(self):
        return MollieSubscriptionSyncService(client=_FakeMollieClient())

    def _membership(self):
        """A membership whose member genuinely has NO findable dues schedule.

        Membership.on_submit creates an Active schedule, so these fallback tests
        only ever passed because _get_membership_dues_schedule filtered on
        docstatus=1 and could never match anything. Cancel the auto-created row so
        the no-schedule path is exercised for a real reason.
        """
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Param",
            last_name=f"Sync{token}",
            email=f"param-{token}@example.com",
            birth_date="1990-01-01",
        )
        membership = self.create_test_membership(member_name=member.name)
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": ["in", ["Active", "Scheduled"]]},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")
        return membership, member

    def test_fee_change_keeps_interval_default_when_no_schedule(self):
        service = self._service()
        membership, member = self._membership()
        amendment = frappe._dict(amendment_type="Fee Change", requested_amount=42.0)

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(amount, 42.0)
        self.assertEqual(interval, "1 month")

    def test_membership_type_change_no_template_defaults_monthly(self):
        service = self._service()
        membership, member = self._membership()
        amendment = frappe._dict(
            amendment_type="Membership Type Change",
            requested_amount=30.0,
            requested_membership_type=None,
        )

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(amount, 30.0)
        self.assertEqual(interval, "1 month")

    def test_billing_interval_change_maps_interval(self):
        service = self._service()
        membership, member = self._membership()
        amendment = frappe._dict(
            amendment_type="Billing Interval Change",
            new_billing_interval="Quarterly",
        )

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(interval, "3 months")
        # No dues schedule -> amount 0.
        self.assertEqual(amount, 0)

    def test_unknown_amendment_type_falls_back(self):
        service = self._service()
        membership, member = self._membership()
        amendment = frappe._dict(amendment_type="Something Else")

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(interval, "1 month")
        self.assertEqual(amount, 0)


class TestSubscriptionParametersWithDuesSchedule(EnhancedTestCase):
    """The WITH-a-dues-schedule path of _get_subscription_parameters.

    The class above only ever exercises members that have NO dues schedule, so
    both of these defects were invisible to it:

    * _get_membership_dues_schedule filtered on docstatus=1, but Membership Dues
      Schedule is not submittable (is_submittable is None) and all 1660 live rows
      are docstatus=0 -- so the lookup returned None for every member, always.
      Consequence: a Billing Interval Change built a EUR 0 subscription, and a Fee
      Change ignored the member's real billing frequency.
    * BILLING_INTERVAL_TO_MOLLIE_FORMAT was keyed on "Annually"/"Semi-Annually",
      but the Select vocabulary is "Annual"/"Semi-Annual", and Weekly/Daily were
      absent entirely -- so 5 of the 7 options silently fell back to "1 month".
      Live data is 1087 Annual / 563 Quarterly / 10 Monthly, so this fires as soon
      as the lookup above starts returning real rows.
    """

    def _service(self):
        return MollieSubscriptionSyncService(client=_FakeMollieClient())

    def _member_with_schedule(self, frequency, dues_rate=25.0):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Sched",
            last_name=f"Param{token}",
            email=f"sched-{token}@example.com",
            birth_date="1990-01-01",
        )
        membership = self.create_test_membership(member_name=member.name)
        # Membership.on_submit already created an Active schedule, and production
        # allows only one per member -- so the factory REUSES that row and ignores the
        # frequency/rate asked for here. Set them on the returned doc instead.
        schedule = self.create_test_dues_schedule(
            member=member.name, amount=dues_rate, frequency=frequency
        )
        schedule.billing_frequency = frequency
        schedule.dues_rate = dues_rate
        schedule.save()
        return membership, member, schedule

    def test_lookup_finds_the_unsubmitted_schedule(self):
        service = self._service()
        membership, member, schedule = self._member_with_schedule("Quarterly", dues_rate=120.0)

        # Guard the premise: the row really is docstatus=0.
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule.name, "docstatus"), 0)

        found = service._get_membership_dues_schedule(member.name)

        self.assertIsNotNone(found, "a docstatus=0 dues schedule must be found")
        self.assertEqual(found.name, schedule.name)

    def test_fee_change_uses_the_members_real_interval(self):
        service = self._service()
        membership, member, schedule = self._member_with_schedule("Quarterly", dues_rate=120.0)
        amendment = frappe._dict(amendment_type="Fee Change", requested_amount=42.0)

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(amount, 42.0)
        self.assertEqual(interval, "3 months", "a Quarterly member must not be billed monthly")

    def test_billing_interval_change_uses_the_schedule_amount(self):
        service = self._service()
        membership, member, schedule = self._member_with_schedule("Monthly", dues_rate=155.5)
        amendment = frappe._dict(
            amendment_type="Billing Interval Change", new_billing_interval="Quarterly"
        )

        amount, interval = service._get_subscription_parameters(amendment, membership)

        self.assertEqual(interval, "3 months")
        self.assertEqual(amount, 155.5, "must bill the real dues rate, not EUR 0")

    def test_every_concrete_billing_frequency_maps(self):
        """Table-driven over the REAL Select vocabulary, read from the doctype.

        Reading the options from meta rather than hardcoding them means adding a
        new billing frequency without a Mollie mapping fails here instead of
        silently billing that member monthly.
        """
        expected = {
            "Monthly": "1 month",
            "Quarterly": "3 months",
            "Semi-Annual": "6 months",
            "Annual": "12 months",
            "Weekly": "1 week",
            "Daily": "1 day",
        }
        options = [
            o
            for o in frappe.get_meta("Membership Dues Schedule")
            .get_field("billing_frequency")
            .options.split("\n")
            if o.strip()
        ]
        # "Custom" carries its own number/unit fields and has no single mapping.
        concrete = [o for o in options if o != "Custom"]
        self.assertEqual(
            sorted(concrete),
            sorted(expected),
            "the Select vocabulary changed -- update the Mollie interval mapping too",
        )

        for frequency in concrete:
            with self.subTest(frequency=frequency):
                self.assertEqual(
                    BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(frequency),
                    expected[frequency],
                    f"{frequency} has no correct Mollie interval mapping",
                )

    def test_every_amendment_billing_interval_maps(self):
        """The OTHER caller's vocabulary, which is not the same one.

        _get_subscription_parameters feeds the same map from
        Contribution Amendment Request.new_billing_interval, whose Select uses the
        older "-ly" spellings (Monthly/Quarterly/Annually). Nothing guarded that,
        so a fix aimed at the dues-schedule vocabulary could silently break this
        caller instead.
        """
        expected = {"Monthly": "1 month", "Quarterly": "3 months", "Annually": "12 months"}
        options = [
            o
            for o in frappe.get_meta("Contribution Amendment Request")
            .get_field("new_billing_interval")
            .options.split("\n")
            if o.strip()
        ]
        self.assertEqual(
            sorted(options),
            sorted(expected),
            "the amendment Select vocabulary changed -- update the Mollie interval mapping too",
        )

        for interval in options:
            with self.subTest(interval=interval):
                self.assertEqual(
                    BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(interval),
                    expected[interval],
                    f"{interval} has no correct Mollie interval mapping",
                )

    def test_gateway_passes_through_every_interval_a_dues_schedule_can_emit(self):
        """MollieGateway.create_subscription must not downgrade its own inputs.

        That method re-maps the interval through a passthrough allow-list and
        silently rewrites anything missing to "1 month" -- an annual subscription
        quietly billed monthly. This drives the real gateway for every billing
        frequency the Select allows, capturing the payload handed to the payment
        service, and asserts the interval survives unchanged.

        Behavioural on purpose: an earlier version of this test read the allow-list
        out of the function's source with a regex, which both asserted a property
        that does not exist and would have rotted the moment the literal moved.

        (BILLING_INTERVAL_TO_MOLLIE_FORMAT is deliberately NOT checked here: it
        feeds MollieClient directly and never reaches this gateway method.)
        """
        from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
            convert_frequency_to_mollie_interval,
        )

        member = self._member_for_gateway()
        for frequency in self._concrete_billing_frequencies():
            emitted = convert_frequency_to_mollie_interval(frequency)
            with self.subTest(frequency=frequency, emitted=emitted):
                sent = self._interval_reaching_mollie(member, emitted)
                self.assertEqual(
                    sent,
                    emitted,
                    f"{frequency} -> {emitted!r} but the gateway sent {sent!r}",
                )

    def test_whitelisted_endpoint_accepts_every_interval_a_dues_schedule_can_emit(self):
        """create_member_subscription must not reject what the gateway handles.

        The endpoint validates its `interval` parameter against its own tuple and
        returns an "Unsupported subscription interval" error otherwise. That tuple
        omitted "12 months" -- what an Annual schedule produces -- so an annual
        subscription was refused before it ever reached Mollie.
        """
        from unittest.mock import patch as _patch

        from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
            convert_frequency_to_mollie_interval,
        )
        from verenigingen.verenigingen_payments.utils import payment_gateways

        member = self._member_for_gateway()
        for frequency in self._concrete_billing_frequencies():
            emitted = convert_frequency_to_mollie_interval(frequency)
            with self.subTest(frequency=frequency, emitted=emitted):
                # Stub the gateway: the interval check runs before it is reached,
                # so this isolates the validation without touching Mollie.
                fake = SimpleNamespace(
                    create_subscription=lambda m, d: {"status": "success", "subscription_id": "sub_x"}
                )
                with _patch.object(
                    payment_gateways.PaymentGatewayFactory, "get_gateway", return_value=fake
                ):
                    result = payment_gateways.create_member_subscription(
                        member.name, 25.0, interval=emitted
                    )
                self.assertNotIn(
                    "Unsupported subscription interval",
                    str(result.get("message", "")),
                    f"{frequency} -> {emitted!r} is rejected by the endpoint",
                )

    # --- helpers for the two tests above -------------------------------------

    def test_non_repricing_amendment_types_never_reach_mollie(self):
        """Suspension / Reactivation / Plan Change must not re-price a subscription.

        They fall through _get_subscription_parameters' else branch, which has no
        pricing rules and returns the member's full dues rate. That was harmless
        only while the dues-schedule lookup was broken and always yielded EUR 0
        (which Mollie rejects); with the lookup working, a Suspension would
        re-create the subscription at full price. Asserted against the live Select
        so a new amendment type has to be classified deliberately.
        """
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            REPRICING_AMENDMENT_TYPES,
        )

        options = [
            o
            for o in frappe.get_meta("Contribution Amendment Request")
            .get_field("amendment_type")
            .options.split("\n")
            if o.strip()
        ]
        self.assertTrue(REPRICING_AMENDMENT_TYPES.issubset(options), "stale repricing type name")

        service = MollieSubscriptionSyncService(client=_FakeMollieClient())
        for amendment_type in [o for o in options if o not in REPRICING_AMENDMENT_TYPES]:
            with self.subTest(amendment_type=amendment_type):
                result = service.sync_subscription_for_amendment(
                    frappe._dict(name="AMEND-X", amendment_type=amendment_type)
                )
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(result["reason"], "amendment_type_not_repricing")

    def _concrete_billing_frequencies(self):
        """Every billing_frequency the live Select allows, except Custom.

        Custom carries its own number/unit fields and has no single interval.
        """
        return [
            o
            for o in frappe.get_meta("Membership Dues Schedule")
            .get_field("billing_frequency")
            .options.split("\n")
            if o.strip() and o != "Custom"
        ]

    def _member_for_gateway(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Gw",
            last_name=f"Interval{token}",
            email=f"gw-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_GWTEST", update_modified=False
        )
        member.reload()
        return member

    def _interval_reaching_mollie(self, member, interval):
        """Run the real create_subscription body and return the interval it sent.

        The gateway is built with __new__ and given a stub `settings` rather than
        constructed normally: MollieGateway.__init__ loads Mollie Settings and
        throws "Mollie test secret key not configured" wherever no key exists --
        which is every CI runner. The method under test is create_subscription,
        not the constructor, so this keeps the test running everywhere instead of
        silently skipping exactly where it matters.
        """
        from unittest.mock import patch as _patch

        from verenigingen.verenigingen_payments.utils import payment_gateways

        captured = {}

        def _capture(self_, customer_data, subscription_data):
            captured.update(subscription_data)
            return {
                "customer_id": "cst_GWTEST",
                "subscription_id": "sub_GWTEST",
                "subscription_status": "active",
                "next_payment_date": None,
            }

        gateway = payment_gateways.MollieGateway.__new__(payment_gateways.MollieGateway)
        gateway.settings = SimpleNamespace(
            enable_subscriptions=1,
            get_subscription_webhook_url=lambda: "https://example.org/hook",
        )
        with _patch.object(
            payment_gateways.CompletePaymentService, "create_customer_subscription", _capture
        ):
            gateway.create_subscription(member, {"amount": 25.0, "interval": interval})
        self.assertIn("interval", captured, "gateway never called the payment service")
        return captured["interval"]


class TestVerifySubscriptionAmount(EnhancedTestCase):
    def _member(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Verify",
            last_name=f"Amt{token}",
            email=f"verify-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", "cst_V", update_modified=False)
        member.reload()
        return member

    def test_amount_matches(self):
        member = self._member()
        membership = self.create_test_membership(member_name=member.name)
        client = _FakeMollieClient(subscription=_sub(value="25.00"))
        service = MollieSubscriptionSyncService(client=client)

        result = service._verify_subscription_amount(member, membership, "sub_1", 25.0)

        self.assertTrue(result["verified"])
        self.assertEqual(result["mollie_amount"], 25.0)

    def _cancel_auto_schedules(self, member_name):
        """Membership.on_submit creates an Active schedule; cancel it.

        Without this, "no dues schedule" is not true and the retry branch below
        runs for real -- this test used to pass only because the lookup was broken
        and returned None for everyone.
        """
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def test_amount_mismatch_no_schedule_fails(self):
        member = self._member()
        membership = self.create_test_membership(member_name=member.name)
        self._cancel_auto_schedules(member.name)
        client = _FakeMollieClient(subscription=_sub(value="25.00"))
        service = MollieSubscriptionSyncService(client=client)

        # Expected differs from Mollie's 25.00 and there is genuinely no dues
        # schedule to rescue it on retry.
        result = service._verify_subscription_amount(member, membership, "sub_1", 99.0)

        self.assertFalse(result["verified"])
        self.assertIn("mismatch", result["message"].lower())

    def test_amount_mismatch_is_rescued_when_the_schedule_agrees_with_mollie(self):
        """The retry-succeeds branch, which this change brought to life.

        _verify_subscription_amount re-reads the dues schedule on a mismatch and
        flips to verified when the schedule agrees with Mollie. That branch was
        unreachable while the lookup always returned None, so nothing covered it --
        yet it is the branch that suppresses the admin mismatch escalation.
        """
        member = self._member()
        membership = self.create_test_membership(member_name=member.name)
        self._cancel_auto_schedules(member.name)
        schedule = self.create_test_dues_schedule(member=member.name, amount=120.0, frequency="Monthly")
        # The factory reuses the auto-created row, so set the rate explicitly.
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Active")
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "dues_rate", 25.0)

        client = _FakeMollieClient(subscription=_sub(value="25.00"))
        service = MollieSubscriptionSyncService(client=client)

        # Caller's expectation (99.0) is stale; the schedule says 25.00, which is
        # what Mollie holds -> the retry must rescue it.
        result = service._verify_subscription_amount(member, membership, "sub_1", 99.0)

        self.assertTrue(result["verified"], f"retry should have rescued this: {result}")
        self.assertEqual(result["mollie_amount"], 25.0)
