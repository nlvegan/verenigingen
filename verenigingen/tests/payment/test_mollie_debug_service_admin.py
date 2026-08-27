"""
Tests for the ADMIN / WRITE / VALIDATION surface of ``MollieDebugService``.

``MollieDebugService.__init__`` wires three collaborators:
    * ``self.mollie_client = MollieClient()`` - the Mollie SDK wrapper
    * ``self.audit_trail = get_audit_trail()`` - the compliance audit log
    * ``self.config`` (lazy) - the Mollie configuration service

The Mollie SDK is an external HTTP boundary that cannot be reached in tests.
These tests replace the three collaborators at the *module import seam*
(``verenigingen.services.mollie_debug_service``) so the REAL service object is
built but never touches live Mollie. Everything else - the validation guards,
the confirmation gates, the audit-trail wiring and the success/error response
shaping - runs for real and is asserted on.

Mock justification: only the Mollie SDK boundary (and, for explicitly
delegating methods, the production ``SubscriptionService``) is faked. No
business logic is mocked. The fakes record the calls made against them so the
service's behaviour - not its internals - can be asserted.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.core.compliance.audit_trail import AuditEventType

# A mod-97 valid Dutch test IBAN (see iban_validator.generate_test_iban("TEST")).
VALID_TEST_IBAN = "NL13TEST0123456789"
VALID_TEST_BIC = "TESTNL2A"

_MODULE = "verenigingen.services.mollie_debug_service"


# ---------------------------------------------------------------------------
# Fakes for the Mollie SDK boundary
# ---------------------------------------------------------------------------


class _Obj:
    """Minimal attribute bag standing in for a Mollie SDK resource object."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeSubscriptions:
    def __init__(self, recorder, sub):
        self._recorder = recorder
        self._sub = sub

    def get(self, subscription_id):
        return self._sub

    def update(self, subscription_id, data):
        self._recorder["subscription_updates"].append((subscription_id, data))
        # Echo updated fields back onto the subscription object.
        for k, v in data.items():
            setattr(self._sub, k, v)
        return self._sub

    def list(self):
        return self._recorder["customer_subscriptions"]

    def delete(self, subscription_id):
        self._recorder["subscriptions_deleted"].append(subscription_id)
        return _Obj(id=subscription_id, status="canceled")


class _FakeMandates:
    def __init__(self, recorder, created_mandate, delete_raises=None):
        self._recorder = recorder
        self._created = created_mandate
        self._delete_raises = delete_raises

    def create(self, data=None, idempotency_key="", **params):
        self._recorder["mandates_created"].append(data)
        return self._created

    def get(self, mandate_id):
        return self._created

    def list(self):
        return self._recorder["customer_mandates"]

    def delete(self, mandate_id):
        self._recorder["mandates_deleted"].append(mandate_id)
        if self._delete_raises:
            raise self._delete_raises
        return _Obj(id=mandate_id)


class _FakeCustomerObj:
    def __init__(self, recorder, customer_id, **kwargs):
        self.id = customer_id
        self.name = kwargs.get("name", "Test Customer")
        self.email = kwargs.get("email", "cust@example.com")
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.mode = "test"
        sub = kwargs.get("subscription") or _Obj(
            id="sub_FAKE",
            status="active",
            webhookUrl="https://old.example.com/wh",
            mandateId="mdt_OLD",
        )
        self.subscriptions = _FakeSubscriptions(recorder, sub)
        self.mandates = _FakeMandates(
            recorder,
            kwargs.get("created_mandate"),
            delete_raises=kwargs.get("mandate_delete_raises"),
        )


class _FakeCustomers:
    def __init__(self, recorder, customer_obj, get_raises=None, delete_raises=None):
        self._recorder = recorder
        self._customer_obj = customer_obj
        self._get_raises = get_raises
        self._delete_raises = delete_raises

    def get(self, customer_id):
        self._recorder["customers_fetched"].append(customer_id)
        if self._get_raises:
            raise self._get_raises
        return self._customer_obj

    def delete(self, customer_id):
        self._recorder["customers_deleted"].append(customer_id)
        if self._delete_raises:
            raise self._delete_raises
        return _Obj(id=customer_id)


class _FakePayments:
    def __init__(self, recorder, payment):
        self._recorder = recorder
        self._payment = payment

    def get(self, payment_id):
        if isinstance(self._payment, Exception):
            raise self._payment
        return self._payment


class FakeSDK:
    """Stand-in for ``mollie.api.client.Client`` (the raw SDK)."""

    def __init__(self, recorder, customer_obj=None, payment=None, **cust_kwargs):
        self.api_key = "test_fake_key"
        self.customers = _FakeCustomers(recorder, customer_obj, **cust_kwargs)
        self.payments = _FakePayments(recorder, payment)


class FakeMollieClient:
    """Stand-in for the ``MollieClient`` wrapper used at the module seam.

    Exposes ``sdk_client`` (the raw SDK used by direct-SDK methods) plus the
    handful of wrapper methods the create-* paths call.
    """

    def __init__(self, recorder, sdk, *, test_mode=True, create_sub=None, create_payment=None):
        self.recorder = recorder
        self.sdk_client = sdk
        self._test_mode = test_mode
        self._create_sub = create_sub
        self._create_payment = create_payment

    def is_test_mode(self):
        return self._test_mode

    def get_webhook_url(self):
        return "https://example.com/mollie_payment_webhook"

    def create_subscription(self, customer_id, subscription_data):
        self.recorder["wrapper_subscriptions_created"].append((customer_id, subscription_data))
        if isinstance(self._create_sub, Exception):
            raise self._create_sub
        return self._create_sub

    def create_payment(self, payment_data):
        self.recorder["wrapper_payments_created"].append(payment_data)
        if isinstance(self._create_payment, Exception):
            raise self._create_payment
        return self._create_payment


class FakeAuditTrail:
    """Records ``log_event`` calls so the write paths can be asserted."""

    def __init__(self):
        self.events = []

    def log_event(self, event_type, severity, message, **kwargs):
        self.events.append(
            {
                "event_type": event_type,
                "severity": severity,
                "message": message,
                "details": kwargs.get("details", {}),
                "entity_type": kwargs.get("entity_type"),
                "entity_id": kwargs.get("entity_id"),
            }
        )


class FakeConfig:
    def __init__(self, test_mode=True):
        self._test_mode = test_mode

    def is_test_mode(self):
        return self._test_mode


def _new_recorder():
    return {
        "customers_fetched": [],
        "customers_deleted": [],
        "subscriptions_deleted": [],
        "subscription_updates": [],
        "mandates_created": [],
        "mandates_deleted": [],
        "customer_subscriptions": [],
        "customer_mandates": [],
        "wrapper_subscriptions_created": [],
        "wrapper_payments_created": [],
    }


class _MollieDebugServiceHarness:
    """Builds a REAL MollieDebugService with all three collaborators faked."""

    def __init__(
        self,
        *,
        customer_obj=None,
        payment=None,
        test_mode=True,
        create_sub=None,
        create_payment=None,
        cust_get_raises=None,
        cust_delete_raises=None,
        mandate_delete_raises=None,
        created_mandate=None,
        subscription=None,
        customer_subscriptions=None,
        customer_id="cst_FAKE",
    ):
        self.recorder = _new_recorder()
        if customer_subscriptions is not None:
            self.recorder["customer_subscriptions"] = customer_subscriptions
        if customer_obj is None:
            customer_obj = _FakeCustomerObj(
                self.recorder,
                customer_id,
                created_mandate=created_mandate,
                mandate_delete_raises=mandate_delete_raises,
                subscription=subscription,
            )
        sdk = FakeSDK(
            self.recorder,
            customer_obj=customer_obj,
            payment=payment,
            get_raises=cust_get_raises,
            delete_raises=cust_delete_raises,
        )
        self.audit = FakeAuditTrail()
        self.client = FakeMollieClient(
            self.recorder, sdk, test_mode=test_mode, create_sub=create_sub, create_payment=create_payment
        )
        self._patches = [
            patch(f"{_MODULE}.MollieClient", return_value=self.client),
            patch(f"{_MODULE}.get_audit_trail", return_value=self.audit),
            patch(f"{_MODULE}.get_mollie_config", return_value=FakeConfig(test_mode)),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.service = MollieDebugService()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class TestMollieDebugServiceValidation(EnhancedTestCase):
    """Validation guards on the admin/write surface (no SDK call expected)."""

    # --- _validate_mandate_params -----------------------------------------

    def _validate_mandate(self, **overrides):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        params = {
            "customer_id": "cst_X",
            "consumer_name": "Jane Doe",
            "consumer_account": VALID_TEST_IBAN,
            "consumer_bic": None,
            "signature_date": None,
            "mandate_reference": None,
        }
        params.update(overrides)
        return MollieDebugService._validate_mandate_params(**params)

    def test_validate_mandate_requires_customer_id(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(customer_id="")
        self.assertIn("Customer ID", str(ctx.exception))

    def test_validate_mandate_requires_consumer_name(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(consumer_name="")
        self.assertIn("Consumer name", str(ctx.exception))

    def test_validate_mandate_requires_iban(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(consumer_account="")
        self.assertIn("IBAN", str(ctx.exception))

    def test_validate_mandate_rejects_overlong_consumer_name(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(consumer_name="A" * 71)
        self.assertIn("70 characters", str(ctx.exception))

    def test_validate_mandate_rejects_overlong_reference(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(mandate_reference="R" * 36)
        self.assertIn("35 characters", str(ctx.exception))

    def test_validate_mandate_rejects_invalid_iban(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(consumer_account="NL00BANK0000000000")
        self.assertIn("Invalid IBAN", str(ctx.exception))

    def test_validate_mandate_rejects_invalid_bic(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(consumer_bic="XX")
        self.assertIn("Invalid BIC", str(ctx.exception))

    def test_validate_mandate_accepts_valid_bic(self):
        # Should not raise and should return the (None) signature date unchanged.
        result = self._validate_mandate(consumer_bic=VALID_TEST_BIC)
        self.assertIsNone(result)

    def test_validate_mandate_rejects_future_signature_date(self):
        future = frappe.utils.add_days(frappe.utils.today(), 5)
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(signature_date=future)
        self.assertIn("future", str(ctx.exception))

    def test_validate_mandate_normalizes_past_signature_date(self):
        past = frappe.utils.add_days(frappe.utils.today(), -5)
        result = self._validate_mandate(signature_date=past)
        self.assertEqual(result, str(frappe.utils.getdate(past)))

    def test_validate_mandate_rejects_unparseable_signature_date(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_mandate(signature_date="not-a-date")
        self.assertIn("Invalid signature date", str(ctx.exception))

    # --- _validate_subscription_params ------------------------------------

    def _validate_subscription(self, **overrides):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        params = {
            "customer_id": "cst_X",
            "amount": 15.0,
            "interval_count": 1,
            "interval_unit": "months",
            "times": None,
        }
        params.update(overrides)
        return MollieDebugService._validate_subscription_params(**params)

    def test_validate_subscription_requires_customer_id(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(customer_id="")
        self.assertIn("Customer ID", str(ctx.exception))

    def test_validate_subscription_rejects_non_numeric_amount(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(amount="abc")
        self.assertIn("Invalid amount", str(ctx.exception))

    def test_validate_subscription_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(amount=0)
        self.assertIn("positive", str(ctx.exception))

    def test_validate_subscription_rejects_amount_over_cap(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(amount=1500)
        self.assertIn("1,000", str(ctx.exception))

    def test_validate_subscription_rejects_non_numeric_interval_count(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(interval_count="x")
        self.assertIn("interval count", str(ctx.exception))

    def test_validate_subscription_rejects_bad_interval_unit(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(interval_unit="days")
        self.assertIn("weeks", str(ctx.exception))

    def test_validate_subscription_rejects_month_count_out_of_range(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(interval_unit="months", interval_count=13)
        self.assertIn("1 and 12", str(ctx.exception))

    def test_validate_subscription_rejects_week_count_out_of_range(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(interval_unit="weeks", interval_count=53)
        self.assertIn("1 and 52", str(ctx.exception))

    def test_validate_subscription_rejects_times_below_one(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(times=0)
        self.assertIn("at least 1", str(ctx.exception))

    def test_validate_subscription_rejects_times_over_cap(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate_subscription(times=1000)
        self.assertIn("999", str(ctx.exception))

    def test_validate_subscription_singular_interval_string(self):
        amount, count, interval = self._validate_subscription(interval_count=1, interval_unit="months")
        self.assertEqual(amount, 15.0)
        self.assertEqual(count, 1)
        # 1 month (singular), not "1 months".
        self.assertEqual(interval, "1 month")

    def test_validate_subscription_plural_interval_string(self):
        _, _, interval = self._validate_subscription(interval_count=3, interval_unit="months")
        self.assertEqual(interval, "3 months")


class TestMollieDebugServiceWriteGuards(EnhancedTestCase):
    """Guard branches on the write methods that short-circuit before any SDK call."""

    def test_update_webhook_requires_ids(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.update_subscription_webhook("", "sub_1", "https://x/wh")
            self.assertIn("required", str(ctx.exception))
            # No SDK customer fetch happened.
            self.assertEqual(h.recorder["customers_fetched"], [])

    def test_update_webhook_requires_url(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.update_subscription_webhook("cst_1", "sub_1", "")
            self.assertIn("Webhook URL is required", str(ctx.exception))

    def test_update_webhook_requires_https(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.update_subscription_webhook("cst_1", "sub_1", "http://insecure/wh")
            self.assertIn("HTTPS", str(ctx.exception))
            self.assertEqual(h.recorder["customers_fetched"], [])

    def test_revoke_mandate_requires_ids(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_revoke_mandate("", "mdt_1")
            self.assertIn("required", str(ctx.exception))

    def test_revoke_mandate_requires_reason(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_revoke_mandate("cst_1", "mdt_1", reason="")
            self.assertIn("reason", str(ctx.exception))

    def test_delete_customer_requires_id(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_delete_customer("")
            self.assertIn("Customer ID", str(ctx.exception))

    def test_delete_customer_requires_reason(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_delete_customer("cst_1", reason="")
            self.assertIn("reason", str(ctx.exception))

    def test_delete_customer_requires_exact_confirmation(self):
        with _MollieDebugServiceHarness() as h:
            # Wrong confirmation text must be rejected before any SDK call.
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_delete_customer("cst_1", confirmation_text="delete customer")
            self.assertIn("DELETE CUSTOMER", str(ctx.exception))
            self.assertEqual(h.recorder["customers_deleted"], [])

    def test_delete_customer_rejects_missing_confirmation(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError):
                h.service.admin_delete_customer("cst_1")
            self.assertEqual(h.recorder["customers_deleted"], [])

    def test_cancel_payment_requires_id(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_cancel_payment("")
            self.assertIn("Payment ID", str(ctx.exception))

    def test_cancel_payment_requires_reason(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.admin_cancel_payment("tr_1", reason="")
            self.assertIn("reason", str(ctx.exception))

    def test_create_subscription_requires_customer_id(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_subscription("", 15.0, "1 month", "desc")
            self.assertIn("Customer ID", str(ctx.exception))

    def test_create_subscription_rejects_bad_interval(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_subscription("cst_1", 15.0, "5 months", "desc")
            self.assertIn("Invalid interval", str(ctx.exception))

    def test_create_subscription_rejects_amount_over_cap(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_subscription("cst_1", 1500.0, "1 month", "desc")
            self.assertIn("1,000", str(ctx.exception))

    def test_create_test_payment_rejects_amount_over_cap(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_test_payment(1500.0, "valid description")
            self.assertIn("1,000", str(ctx.exception))

    def test_create_test_payment_rejects_short_description(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_test_payment(15.0, "ab")
            self.assertIn("3 characters", str(ctx.exception))

    def test_create_test_payment_rejects_past_due_date(self):
        with _MollieDebugServiceHarness() as h:
            yesterday = frappe.utils.add_days(frappe.utils.today(), -1)
            with self.assertRaises(ValueError) as ctx:
                h.service.create_test_payment(15.0, "valid description", due_date=yesterday)
            self.assertIn("tomorrow", str(ctx.exception))

    def test_create_test_payment_rejects_far_future_due_date(self):
        with _MollieDebugServiceHarness() as h:
            far = frappe.utils.add_days(frappe.utils.today(), 200)
            with self.assertRaises(ValueError) as ctx:
                h.service.create_test_payment(15.0, "valid description", due_date=far)
            self.assertIn("100 days", str(ctx.exception))

    def test_create_test_payment_rejects_bad_due_date_format(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError) as ctx:
                h.service.create_test_payment(15.0, "valid description", due_date="2026/01/01")
            self.assertIn("Invalid due date format", str(ctx.exception))


class TestMollieDebugServiceUpdateWebhook(EnhancedTestCase):
    def test_update_webhook_success_logs_audit(self):
        sub = _Obj(id="sub_1", webhookUrl="https://old/wh")
        with _MollieDebugServiceHarness(subscription=sub) as h:
            with self.set_user("Administrator"):
                result = h.service.update_subscription_webhook(
                    "cst_1", "sub_1", "https://new.example.com/wh", reason="rotation"
                )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["old_webhook_url"], "https://old/wh")
            self.assertEqual(result["new_webhook_url"], "https://new.example.com/wh")
            # The SDK actually received the PATCH.
            self.assertEqual(
                h.recorder["subscription_updates"],
                [("sub_1", {"webhookUrl": "https://new.example.com/wh"})],
            )
            # Audit trail recorded a configuration change for the subscription.
            self.assertEqual(len(h.audit.events), 1)
            ev = h.audit.events[0]
            self.assertEqual(ev["event_type"], AuditEventType.CONFIGURATION_CHANGED)
            self.assertEqual(ev["entity_type"], "Mollie Subscription")
            self.assertEqual(ev["entity_id"], "sub_1")
            self.assertEqual(ev["details"]["new_webhook_url"], "https://new.example.com/wh")

    def test_update_webhook_failure_reraises_and_no_audit(self):
        with _MollieDebugServiceHarness(cust_get_raises=RuntimeError("boom")) as h:
            with self.assertRaises(RuntimeError):
                h.service.update_subscription_webhook("cst_1", "sub_1", "https://new/wh")
            self.assertEqual(h.audit.events, [])


class TestMollieDebugServiceRevokeMandate(EnhancedTestCase):
    def test_revoke_mandate_cancels_active_subscriptions_and_logs(self):
        subs = [
            _Obj(id="sub_active", status="active"),
            _Obj(id="sub_pending", status="pending"),
            _Obj(id="sub_canceled", status="canceled"),
        ]
        with _MollieDebugServiceHarness(customer_subscriptions=subs) as h:
            with self.set_user("Administrator"):
                result = h.service.admin_revoke_mandate("cst_1", "mdt_1", reason="fraud")
            self.assertEqual(result["status"], "success")
            # Only active + pending subscriptions cancelled (canceled one skipped).
            self.assertEqual(sorted(h.recorder["subscriptions_deleted"]), ["sub_active", "sub_pending"])
            self.assertEqual(h.recorder["mandates_deleted"], ["mdt_1"])
            self.assertEqual(result["cancelled_subscriptions"], ["sub_active", "sub_pending"])
            # Audit event recorded for the mandate revocation.
            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.CONFIGURATION_CHANGED)
            self.assertEqual(ev["entity_type"], "Mollie Mandate")
            self.assertEqual(ev["entity_id"], "mdt_1")
            self.assertEqual(ev["details"]["subscriptions_cancelled_count"], 2)

    def test_revoke_already_revoked_mandate_returns_warning(self):
        with _MollieDebugServiceHarness(
            customer_subscriptions=[],
            mandate_delete_raises=RuntimeError("Mandate is no longer available"),
        ) as h:
            with self.set_user("Administrator"):
                result = h.service.admin_revoke_mandate("cst_1", "mdt_gone", reason="cleanup")
            self.assertEqual(result["status"], "warning")
            self.assertIn("already revoked", result["message"].lower())
            # No audit success event since revocation failed.
            self.assertEqual(h.audit.events, [])

    def test_revoke_mandate_unexpected_error_reraises(self):
        with _MollieDebugServiceHarness(
            customer_subscriptions=[],
            mandate_delete_raises=RuntimeError("internal server error"),
        ) as h:
            with self.assertRaises(RuntimeError):
                h.service.admin_revoke_mandate("cst_1", "mdt_1", reason="cleanup")


class TestMollieDebugServiceCreateMandate(EnhancedTestCase):
    def test_create_mandate_success_logs_masked_iban(self):
        mandate = _Obj(
            id="mdt_NEW",
            status="valid",
            method="directdebit",
            signature_date="2026-01-01",
            mandate_reference="REF1",
            created_at="2026-01-01T00:00:00+00:00",
            details={"consumerName": "Jane Doe", "consumerAccount": VALID_TEST_IBAN, "consumerBic": None},
        )
        with _MollieDebugServiceHarness(created_mandate=mandate) as h:
            with self.set_user("Administrator"):
                result = h.service.create_mandate(
                    "cst_1", "Jane Doe", VALID_TEST_IBAN, consumer_bic=VALID_TEST_BIC
                )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["mandate"]["id"], "mdt_NEW")
            # SDK received a directdebit mandate create with cleaned (upper, no-space) IBAN.
            created = h.recorder["mandates_created"][0]
            self.assertEqual(created["method"], "directdebit")
            self.assertEqual(created["consumerAccount"], VALID_TEST_IBAN)
            self.assertEqual(created["consumerBic"], VALID_TEST_BIC)
            # Audit event masks the IBAN (country code + last 4 preserved, middle masked).
            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.PAYMENT_CREATED)
            self.assertEqual(ev["entity_type"], "Mollie Mandate")
            masked = ev["details"]["iban_masked"]
            self.assertTrue(masked.startswith("NL"))
            self.assertTrue(masked.endswith(VALID_TEST_IBAN[-4:]))
            self.assertIn("*", masked)
            self.assertNotIn(VALID_TEST_IBAN[2:-4], masked)

    def test_create_mandate_invalid_iban_raises_before_sdk(self):
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError):
                h.service.create_mandate("cst_1", "Jane", "NL00BANK0000000000")
            self.assertEqual(h.recorder["mandates_created"], [])

    def test_create_mandate_sdk_failure_returns_error_response(self):
        with _MollieDebugServiceHarness(cust_get_raises=RuntimeError("API down with secret key sk_live_x")) as h:
            with self.set_user("Administrator"):
                result = h.service.create_mandate("cst_1", "Jane Doe", VALID_TEST_IBAN)
            self.assertEqual(result["status"], "error")
            # Error message sanitised - must not leak the API key fragment.
            self.assertNotIn("sk_live_x", result["message"])
            self.assertEqual(h.audit.events, [])


class TestMollieDebugServiceDeleteCustomer(EnhancedTestCase):
    def test_delete_customer_success_cascades_and_logs_critical(self):
        recorder_subs = [_Obj(id="sub_1", status="active")]
        with _MollieDebugServiceHarness(customer_subscriptions=recorder_subs) as h:
            with self.set_user("Administrator"):
                result = h.service.admin_delete_customer(
                    "cst_1", reason="GDPR erasure", confirmation_text="DELETE CUSTOMER"
                )
            self.assertEqual(result["status"], "success")
            self.assertEqual(h.recorder["customers_deleted"], ["cst_1"])
            # Audit logged at CRITICAL severity for a data deletion.
            from verenigingen.verenigingen_payments.core.compliance.audit_trail import AuditSeverity

            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.DATA_DELETION)
            self.assertEqual(ev["severity"], AuditSeverity.CRITICAL)
            self.assertEqual(ev["entity_type"], "Mollie Customer")
            self.assertEqual(ev["entity_id"], "cst_1")

    def test_delete_nonexistent_customer_returns_warning(self):
        with _MollieDebugServiceHarness(cust_get_raises=RuntimeError("Customer not found")) as h:
            with self.set_user("Administrator"):
                result = h.service.admin_delete_customer(
                    "cst_gone", reason="cleanup", confirmation_text="DELETE CUSTOMER"
                )
            self.assertEqual(result["status"], "warning")
            self.assertEqual(h.recorder["customers_deleted"], [])
            self.assertEqual(h.audit.events, [])

    def test_delete_customer_unexpected_error_reraises(self):
        with _MollieDebugServiceHarness(cust_get_raises=RuntimeError("network exploded")) as h:
            with self.assertRaises(RuntimeError):
                h.service.admin_delete_customer(
                    "cst_1", reason="x", confirmation_text="DELETE CUSTOMER"
                )


class TestMollieDebugServiceCancelPayment(EnhancedTestCase):
    def test_cancel_payment_success_logs_audit(self):
        payment = _Obj(id="tr_1", status="open", isCancelable=True)

        class _Resp:
            status_code = 204

        with _MollieDebugServiceHarness(payment=payment) as h:
            with patch("requests.delete", return_value=_Resp()) as del_mock:
                with self.set_user("Administrator"):
                    result = h.service.admin_cancel_payment("tr_1", reason="duplicate")
            self.assertEqual(result["status"], "success")
            del_mock.assert_called_once()
            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.PAYMENT_UPDATED)
            self.assertEqual(ev["entity_type"], "Mollie Payment")
            self.assertEqual(ev["entity_id"], "tr_1")

    def test_cancel_payment_wrong_status_returns_warning(self):
        payment = _Obj(id="tr_1", status="paid", isCancelable=False)
        with _MollieDebugServiceHarness(payment=payment) as h:
            result = h.service.admin_cancel_payment("tr_1", reason="x")
            self.assertEqual(result["status"], "warning")
            self.assertEqual(result["current_status"], "paid")
            self.assertEqual(h.audit.events, [])

    def test_cancel_payment_not_cancelable_returns_warning(self):
        payment = _Obj(id="tr_1", status="open", isCancelable=False)
        with _MollieDebugServiceHarness(payment=payment) as h:
            result = h.service.admin_cancel_payment("tr_1", reason="x")
            self.assertEqual(result["status"], "warning")
            self.assertFalse(result["is_cancelable"])
            self.assertEqual(h.audit.events, [])

    def test_cancel_payment_422_returns_warning(self):
        payment = _Obj(id="tr_1", status="open", isCancelable=True)

        class _Resp:
            status_code = 422

            def json(self):
                return {"detail": "Payment cannot be cancelled in current state"}

        with _MollieDebugServiceHarness(payment=payment) as h:
            with patch("requests.delete", return_value=_Resp()):
                result = h.service.admin_cancel_payment("tr_1", reason="x")
            self.assertEqual(result["status"], "warning")
            self.assertIn("mollie_error", result)
            self.assertEqual(h.audit.events, [])

    def test_cancel_payment_not_found_returns_warning(self):
        with _MollieDebugServiceHarness(payment=RuntimeError("Payment does not exist")) as h:
            result = h.service.admin_cancel_payment("tr_gone", reason="x")
            self.assertEqual(result["status"], "warning")
            self.assertEqual(h.audit.events, [])

    def test_cancel_payment_unexpected_error_reraises(self):
        with _MollieDebugServiceHarness(payment=RuntimeError("kaboom internal")) as h:
            with self.assertRaises(RuntimeError):
                h.service.admin_cancel_payment("tr_1", reason="x")


class TestMollieDebugServiceCreateSubscription(EnhancedTestCase):
    def test_create_subscription_success_logs_audit(self):
        created = _Obj(
            id="sub_NEW",
            status="active",
            amount={"value": "15.00", "currency": "EUR"},
            interval="1 month",
            description="Monthly dues",
        )
        with _MollieDebugServiceHarness(create_sub=created) as h:
            with self.set_user("Administrator"):
                result = h.service.create_subscription("cst_1", 15.0, "1 month", "Monthly dues")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["subscription_id"], "sub_NEW")
            # Routed through the MollieClient wrapper (not the raw SDK).
            self.assertEqual(len(h.recorder["wrapper_subscriptions_created"]), 1)
            cust, data = h.recorder["wrapper_subscriptions_created"][0]
            self.assertEqual(cust, "cst_1")
            self.assertEqual(data["interval"], "1 month")
            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.PAYMENT_CREATED)
            self.assertEqual(ev["entity_id"], "sub_NEW")

    def test_create_subscription_failure_returns_sanitized_error(self):
        with _MollieDebugServiceHarness(create_sub=RuntimeError("boom token sk_test_secret")) as h:
            with self.set_user("Administrator"):
                result = h.service.create_subscription("cst_1", 15.0, "1 month", "desc")
            self.assertEqual(result["status"], "error")
            self.assertNotIn("sk_test_secret", result["message"])
            self.assertEqual(h.audit.events, [])

    def test_create_scheduled_subscription_success(self):
        created = _Obj(
            id="sub_SCHED",
            status="active",
            amount={"value": "30.00", "currency": "EUR"},
            interval="1 month",
            description="Scheduled",
        )
        with _MollieDebugServiceHarness(create_sub=created) as h:
            with self.set_user("Administrator"):
                result = h.service.create_scheduled_subscription(
                    "cst_1", 30.0, 1, "months", "Scheduled"
                )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["subscription_id"], "sub_SCHED")
            cust, data = h.recorder["wrapper_subscriptions_created"][0]
            self.assertEqual(data["interval"], "1 month")

    def test_create_scheduled_subscription_failure(self):
        with _MollieDebugServiceHarness(create_sub=RuntimeError("scheduled boom")) as h:
            with self.set_user("Administrator"):
                result = h.service.create_scheduled_subscription("cst_1", 30.0, 1, "months", "Scheduled")
            self.assertEqual(result["status"], "error")
            self.assertEqual(h.audit.events, [])

    def test_create_scheduled_subscription_validates_params(self):
        # Validation happens before the try block - bad interval unit raises.
        with _MollieDebugServiceHarness() as h:
            with self.assertRaises(ValueError):
                h.service.create_scheduled_subscription("cst_1", 30.0, 1, "days", "Scheduled")


class TestMollieDebugServiceCreateTestPayment(EnhancedTestCase):
    def test_create_test_payment_success_logs_audit(self):
        payment = _Obj(
            id="tr_NEW",
            status="open",
            amount={"value": "15.00", "currency": "EUR"},
            description="Test payment",
            checkout_url="https://pay.example.com/tr_NEW",
        )
        with _MollieDebugServiceHarness(create_payment=payment) as h:
            with self.set_user("Administrator"):
                result = h.service.create_test_payment(15.0, "Test payment", customer_id="cst_1")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["payment_id"], "tr_NEW")
            self.assertEqual(result["checkout_url"], "https://pay.example.com/tr_NEW")
            # Wrapper create_payment received the customer link.
            data = h.recorder["wrapper_payments_created"][0]
            self.assertEqual(data["customerId"], "cst_1")
            ev = h.audit.events[-1]
            self.assertEqual(ev["event_type"], AuditEventType.PAYMENT_CREATED)
            self.assertEqual(ev["entity_id"], "tr_NEW")

    def test_create_test_payment_with_due_date(self):
        payment = _Obj(
            id="tr_DUE",
            status="open",
            amount={"value": "15.00", "currency": "EUR"},
            description="Bank transfer",
            checkout_url="https://pay/x",
        )
        due = frappe.utils.add_days(frappe.utils.today(), 10)
        with _MollieDebugServiceHarness(create_payment=payment) as h:
            with self.set_user("Administrator"):
                result = h.service.create_test_payment(15.0, "Bank transfer", due_date=due)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["due_date"], due)
            data = h.recorder["wrapper_payments_created"][0]
            self.assertEqual(data["dueDate"], due)

    def test_create_test_payment_failure_returns_sanitized_error(self):
        with _MollieDebugServiceHarness(create_payment=RuntimeError("fail sk_live_leak")) as h:
            with self.set_user("Administrator"):
                result = h.service.create_test_payment(15.0, "Test payment")
            self.assertEqual(result["status"], "error")
            self.assertNotIn("sk_live_leak", result["message"])
            self.assertEqual(h.audit.events, [])


class TestMollieDebugServiceDelegation(EnhancedTestCase):
    """admin_cancel_subscription + update_subscription_mandate delegate to the
    production SubscriptionService. Patch it at its source module and assert
    the delegation arguments (the method imports it inside the body)."""

    _SUB_SVC = "verenigingen.verenigingen_payments.mollie.services.subscription_service.SubscriptionService"

    def test_admin_cancel_subscription_delegates(self):
        with _MollieDebugServiceHarness() as h:
            with patch(self._SUB_SVC) as svc_cls:
                svc_cls.return_value.admin_cancel_subscription.return_value = {"status": "success"}
                result = h.service.admin_cancel_subscription("cst_1", "sub_1", reason="ops")
            # Built with the service's MollieClient and called with the right args.
            svc_cls.assert_called_once_with(h.service.mollie_client)
            svc_cls.return_value.admin_cancel_subscription.assert_called_once_with(
                "cst_1", "sub_1", reason="ops"
            )
            self.assertEqual(result, {"status": "success"})

    def test_update_subscription_mandate_delegates(self):
        with _MollieDebugServiceHarness() as h:
            with patch(self._SUB_SVC) as svc_cls:
                svc_cls.return_value.update_subscription_mandate.return_value = {"status": "success"}
                result = h.service.update_subscription_mandate(
                    "cst_1", "sub_1", "mdt_NEW", reason="bank change"
                )
            svc_cls.assert_called_once_with(h.service.mollie_client)
            svc_cls.return_value.update_subscription_mandate.assert_called_once_with(
                "cst_1", "sub_1", "mdt_NEW", reason="bank change"
            )
            self.assertEqual(result, {"status": "success"})
