"""
Integration coverage for the Mollie core HTTP-client wrapper.

Targets:
  - verenigingen/verenigingen_payments/mollie/core/client.py (MollieClient)
  - verenigingen/verenigingen_payments/mollie/exceptions/__init__.py (raised here)

Test philosophy (this repo runs an aggressive test-quality-enforcer):
  - ONLY the Mollie SDK boundary is faked. MollieClient is a thin wrapper over
    the third-party Mollie SDK (an external HTTP client for a payment API that
    cannot run in tests). The fake records the calls made against it and returns
    realistic Mollie-shaped objects. The wrapper's OWN logic — building the
    customer->resource call chains, pagination walking in list_mandates, error
    wrapping into MolliePaymentError, the debug_* aggregation — runs for real.
  - The proven seam (copied from test_mollie_debug_service.py): patch
    MollieSettings.get_mollie_client (so sdk_client is the fake) and
    MollieClient._get_api_key (so __init__ needs no real credentials).
  - get_payment / create_payment / create_refund are wrapped with @with_retry
    (real time.sleep between attempts). On the error paths we patch the retry
    policy's time.sleep so the wrapped methods don't actually block for seconds.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MollieIntegrationError,
    MolliePaymentError,
    MollieSecurityError,
    MollieValidationError,
    MollieWebhookError,
)

_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"
# The @with_retry decorator sleeps between attempts via the retry_policy module's
# time.sleep. Patch THAT so error-path tests (which exhaust the retries) are fast.
_RETRY_SLEEP = "verenigingen.verenigingen_payments.core.resilience.retry_policy.time.sleep"


# ---------------------------------------------------------------------------
# Fake Mollie SDK.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API; it cannot run in tests. This fake mimics only the slice of the
# SDK surface MollieClient touches and records calls for assertion.
# ---------------------------------------------------------------------------


class _Boom(Exception):
    """A generic SDK-side failure used to drive the error-wrapping branches."""


class _Obj:
    """A simple attribute carrier for a Mollie resource object."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _PaginationPage(list):
    """A list page that walks to the next via get_next() (Mollie SDK shape)."""

    def __init__(self, items, next_page=None):
        super().__init__(items)
        self._next_page = next_page

    def get_next(self):
        return self._next_page


class _ResourceCollection:
    """A generic create/get/list/update/delete collection (payments, mandates...)."""

    def __init__(self, recorder, name, *, list_result=None, get_result=None):
        self._rec = recorder
        self._name = name
        self._list_result = list_result
        self._get_result = get_result

    def get(self, resource_id):
        self._rec.append((self._name, "get", resource_id))
        if isinstance(self._get_result, Exception):
            raise self._get_result
        return self._get_result if self._get_result is not None else _Obj(id=resource_id)

    def create(self, data=None):
        self._rec.append((self._name, "create", data))
        return _Obj(id=f"{self._name}_new", data=data)

    def update(self, resource_id, data):
        self._rec.append((self._name, "update", (resource_id, data)))
        return _Obj(id=resource_id, data=data)

    def delete(self, resource_id):
        self._rec.append((self._name, "delete", resource_id))
        return _Obj(id=resource_id, status="canceled")

    def list(self, limit=None):
        self._rec.append((self._name, "list", limit))
        if isinstance(self._list_result, Exception):
            raise self._list_result
        return self._list_result if self._list_result is not None else []


class _Customer:
    def __init__(self, customer_id, recorder, *, mandates_page=None, subs=None, payments=None):
        self.id = customer_id
        self.name = "Test Customer"
        self.email = "customer@example.com"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.mode = "test"
        self._rec = recorder
        self.subscriptions = _ResourceCollection(recorder, "subscriptions", list_result=subs or [])
        self.mandates = _MandateCollection(recorder, mandates_page)
        self.payments = _ResourceCollection(recorder, "payments", list_result=payments or [])


class _MandateCollection(_ResourceCollection):
    def __init__(self, recorder, page):
        super().__init__(recorder, "mandates")
        self._page = page

    def list(self, limit=None):
        self._rec.append(("mandates", "list", limit))
        return self._page if self._page is not None else _PaginationPage([])

    def get(self, mandate_id):
        self._rec.append(("mandates", "get", mandate_id))
        return _Obj(id=mandate_id, status="valid", method="directdebit", created_at="2025-01-01T00:00:00+00:00")


class _Payment:
    def __init__(self, payment_id, recorder, *, refunds=None, chargebacks=None):
        self.id = payment_id
        self._rec = recorder
        self.refunds = _ResourceCollection(
            recorder, "refunds", list_result=refunds if refunds is not None else []
        )
        self.chargebacks = _ResourceCollection(
            recorder, "chargebacks", list_result=chargebacks if chargebacks is not None else []
        )


class FakeSDK:
    def __init__(self, *, customer=None, payment=None, payments_get_raises=None):
        self.calls = []
        self._customer = customer
        self._payment = payment
        self._payments_get_raises = payments_get_raises
        self.payments = _PaymentsCollection(self)
        self.customers = _CustomersCollection(self)


class _PaymentsCollection:
    def __init__(self, sdk):
        self._sdk = sdk

    def get(self, payment_id):
        self._sdk.calls.append(("payments", "get", payment_id))
        if self._sdk._payments_get_raises is not None:
            raise self._sdk._payments_get_raises
        return self._sdk._payment if self._sdk._payment is not None else _Obj(id=payment_id)

    def create(self, data):
        self._sdk.calls.append(("payments", "create", data))
        return _Obj(id="tr_created", data=data)


class _CustomersCollection:
    def __init__(self, sdk):
        self._sdk = sdk

    def get(self, customer_id):
        self._sdk.calls.append(("customers", "get", customer_id))
        if self._sdk._customer is not None:
            return self._sdk._customer
        return _Customer(customer_id, self._sdk.calls)

    def create(self, data):
        self._sdk.calls.append(("customers", "create", data))
        return _Obj(id="cst_created", data=data)


class _MollieConfigStub:
    def __init__(self, test_mode):
        self._test_mode = test_mode

    def is_test_mode(self):
        return self._test_mode


# ---------------------------------------------------------------------------


class _ClientTestBase(unittest.TestCase):
    """Builds a MollieClient wired to a FakeSDK via the proven patch seam."""

    def _make_client(self, fake_sdk):
        with patch(_GET_API_KEY, return_value="test_dummy"):
            client = MollieClient()
        # sdk_client lazily calls get_mollie_client(); wire it to the fake.
        client._mollie_client = fake_sdk
        return client


class TestMollieClientHappyPaths(_ClientTestBase):
    def test_get_payment_returns_sdk_object(self):
        sdk = FakeSDK(payment=_Obj(id="tr_abc123", status="paid"))
        client = self._make_client(sdk)
        result = client.get_payment("tr_abc123")
        self.assertEqual(result.id, "tr_abc123")
        self.assertIn(("payments", "get", "tr_abc123"), sdk.calls)

    def test_create_payment_passes_data_through(self):
        sdk = FakeSDK()
        client = self._make_client(sdk)
        result = client.create_payment({"amount": {"value": "10.00", "currency": "EUR"}})
        self.assertEqual(result.id, "tr_created")
        self.assertEqual(sdk.calls[-1][1], "create")

    def test_get_customer(self):
        cust = _Customer("cst_x", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.get_customer("cst_x")
        self.assertEqual(result.id, "cst_x")

    def test_create_customer(self):
        sdk = FakeSDK()
        client = self._make_client(sdk)
        result = client.create_customer({"name": "X", "email": "x@e.org"})
        self.assertEqual(result.id, "cst_created")

    def test_create_subscription_uses_customer_chain(self):
        cust = _Customer("cst_s", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.create_subscription("cst_s", {"amount": {"value": "5.00", "currency": "EUR"}})
        self.assertEqual(result.id, "subscriptions_new")

    def test_get_subscription(self):
        cust = _Customer("cst_s", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.get_subscription("cst_s", "sub_1")
        self.assertEqual(result.id, "sub_1")

    def test_update_subscription(self):
        cust = _Customer("cst_s", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.update_subscription("cst_s", "sub_1", {"amount": {"value": "9.00", "currency": "EUR"}})
        self.assertEqual(result.id, "sub_1")

    def test_cancel_subscription(self):
        cust = _Customer("cst_s", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.cancel_subscription("cst_s", "sub_1")
        self.assertEqual(result.status, "canceled")

    def test_create_mandate(self):
        cust = _Customer("cst_m", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.create_mandate("cst_m", {"method": "directdebit"})
        self.assertEqual(result.id, "mandates_new")

    def test_list_mandates_walks_all_pages(self):
        # Two pages: list_mandates must flatten both, proving the get_next walk.
        page2 = _PaginationPage([_Obj(id="mdt_3"), _Obj(id="mdt_4")], next_page=None)
        page1 = _PaginationPage([_Obj(id="mdt_1"), _Obj(id="mdt_2")], next_page=page2)
        cust = _Customer("cst_m", [], mandates_page=page1)
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.list_mandates("cst_m")
        self.assertEqual([m.id for m in result], ["mdt_1", "mdt_2", "mdt_3", "mdt_4"])

    def test_list_customer_payments(self):
        cust = _Customer("cst_p", [], payments=[_Obj(id="tr_1"), _Obj(id="tr_2")])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.list_customer_payments("cst_p", limit=10)
        self.assertEqual([p.id for p in result], ["tr_1", "tr_2"])

    def test_get_refund(self):
        payment = _Payment("tr_r", [])
        payment.refunds = _ResourceCollection([], "refunds", get_result=_Obj(id="re_1", status="refunded"))
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        result = client.get_refund("tr_r", "re_1")
        self.assertEqual(result.id, "re_1")

    def test_create_refund(self):
        payment = _Payment("tr_r", [])
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        result = client.create_refund("tr_r", {"amount": {"value": "1.00", "currency": "EUR"}})
        self.assertEqual(result.id, "refunds_new")

    def test_get_chargeback(self):
        payment = _Payment("tr_c", [])
        payment.chargebacks = _ResourceCollection([], "chargebacks", get_result=_Obj(id="chb_1"))
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        result = client.get_chargeback("tr_c", "chb_1")
        self.assertEqual(result.id, "chb_1")

    def test_list_payment_refunds(self):
        payment = _Payment("tr_lr", [], refunds=[_Obj(id="re_1")])
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        result = client.list_payment_refunds("tr_lr")
        self.assertEqual([r.id for r in result], ["re_1"])

    def test_list_payment_chargebacks(self):
        payment = _Payment("tr_lc", [], chargebacks=[_Obj(id="chb_1")])
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        result = client.list_payment_chargebacks("tr_lc")
        self.assertEqual([c.id for c in result], ["chb_1"])

    def test_revoke_mandate(self):
        cust = _Customer("cst_rm", [])
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        result = client.revoke_mandate("cst_rm", "mdt_1")
        self.assertEqual(result.status, "canceled")


class TestMollieClientErrorWrapping(_ClientTestBase):
    """Every wrapper must wrap raw SDK failures in MolliePaymentError, never leak them."""

    def test_get_payment_error_wrapped(self):
        sdk = FakeSDK(payments_get_raises=_Boom("network down"))
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.get_payment("tr_bad")
        self.assertEqual(ctx.exception.payment_id, "tr_bad")
        self.assertIsInstance(ctx.exception.original_error, _Boom)

    def test_create_payment_error_wrapped(self):
        sdk = FakeSDK()
        sdk.payments.create = lambda data: (_ for _ in ()).throw(_Boom("rejected"))
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError):
                client.create_payment({"amount": {"value": "1.00", "currency": "EUR"}})

    def test_get_customer_error_wrapped(self):
        cust = _Customer("cst_e", [])
        sdk = FakeSDK(customer=cust)
        sdk.customers.get = lambda cid: (_ for _ in ()).throw(_Boom("no such customer"))
        client = self._make_client(sdk)
        with self.assertRaises(MolliePaymentError):
            client.get_customer("cst_e")

    def test_create_subscription_error_wrapped(self):
        cust = _Customer("cst_e", [])
        cust.subscriptions.create = lambda data: (_ for _ in ()).throw(_Boom("bad sub"))
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        with self.assertRaises(MolliePaymentError):
            client.create_subscription("cst_e", {})

    def test_list_mandates_error_wrapped(self):
        cust = _Customer("cst_e", [])
        cust.mandates.list = lambda limit=None: (_ for _ in ()).throw(_Boom("list failed"))
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        with self.assertRaises(MolliePaymentError):
            client.list_mandates("cst_e")

    def test_create_refund_error_wrapped(self):
        payment = _Payment("tr_e", [])
        payment.refunds.create = lambda data: (_ for _ in ()).throw(_Boom("refund failed"))
        sdk = FakeSDK(payment=payment)
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.create_refund("tr_e", {})
        self.assertEqual(ctx.exception.payment_id, "tr_e")

    def test_revoke_mandate_error_wrapped_carries_context(self):
        # Regression: revoke_mandate raises MolliePaymentError(customer_id=, mandate_id=).
        # The exception base must accept those kwargs (previously raised TypeError,
        # masking the genuine MolliePaymentError).
        cust = _Customer("cst_rm", [])
        cust.mandates.delete = lambda mid: (_ for _ in ()).throw(_Boom("revoke failed"))
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.revoke_mandate("cst_rm", "mdt_1")
        self.assertEqual(ctx.exception.customer_id, "cst_rm")
        self.assertEqual(ctx.exception.mandate_id, "mdt_1")


class TestMollieClientDebugMethods(_ClientTestBase):
    def test_debug_customer_carries_customer_id_context_on_error(self):
        # debug_customer raises MolliePaymentError(customer_id=...). Drive a failure
        # so the customer_id kwarg path is exercised (regression for the exception
        # base accepting customer_id).
        sdk = FakeSDK()
        sdk.customers.get = lambda cid: (_ for _ in ()).throw(_Boom("boom"))
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.debug_customer("cst_dbg")
        self.assertEqual(ctx.exception.customer_id, "cst_dbg")

    def test_debug_subscription_carries_subscription_id_context_on_error(self):
        cust = _Customer("cst_s", [])
        cust.subscriptions.get = lambda sid: (_ for _ in ()).throw(_Boom("boom"))
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.debug_subscription("cst_s", "sub_dbg")
        self.assertEqual(ctx.exception.subscription_id, "sub_dbg")

    def test_debug_mandate_carries_mandate_id_context_on_error(self):
        cust = _Customer("cst_m", [])
        cust.mandates.get = lambda mid: (_ for _ in ()).throw(_Boom("boom"))
        sdk = FakeSDK(customer=cust)
        client = self._make_client(sdk)
        with patch(_RETRY_SLEEP):
            with self.assertRaises(MolliePaymentError) as ctx:
                client.debug_mandate("cst_m", "mdt_dbg")
        self.assertEqual(ctx.exception.mandate_id, "mdt_dbg")


class TestMollieClientModeAndWebhook(_ClientTestBase):
    def test_is_test_mode_from_config(self):
        client = self._make_client(FakeSDK())
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.get_mollie_config",
            return_value=_MollieConfigStub(True),
        ):
            self.assertTrue(client.is_test_mode())

    def test_is_test_mode_falls_back_to_api_key_prefix(self):
        with patch(_GET_API_KEY, return_value="test_xyz"):
            client = MollieClient()
        client._mollie_client = FakeSDK()
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.get_mollie_config",
            side_effect=Exception("config service down"),
        ):
            self.assertTrue(client.is_test_mode())

    def test_is_test_mode_live_key_fallback(self):
        with patch(_GET_API_KEY, return_value="live_xyz"):
            client = MollieClient()
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.get_mollie_config",
            side_effect=Exception("down"),
        ):
            self.assertFalse(client.is_test_mode())

    def test_get_webhook_url_explicit_env(self):
        client = self._make_client(FakeSDK())
        url = client.get_webhook_url("mollie_payment_webhook", env="test")
        self.assertTrue(url.endswith("?env=test"))
        self.assertIn("mollie.api.webhooks.mollie_payment_webhook", url)

    def test_get_webhook_url_auto_detect_live(self):
        client = self._make_client(FakeSDK())
        with patch.object(client, "is_test_mode", return_value=False):
            url = client.get_webhook_url()
        self.assertTrue(url.endswith("?env=live"))


class TestMollieClientConstruction(unittest.TestCase):
    def test_init_uses_provided_api_key_without_settings(self):
        client = MollieClient(api_key="test_explicit")
        self.assertEqual(client.api_key, "test_explicit")

    def test_get_mollie_client_failure_wrapped(self):
        with patch(_GET_API_KEY, return_value="test_dummy"):
            client = MollieClient()
        with patch(
            _GET_MOLLIE_CLIENT,
            side_effect=Exception("settings broken"),
        ):
            with self.assertRaises(MolliePaymentError):
                client._get_mollie_client()


class TestMollieExceptionHierarchy(unittest.TestCase):
    """Cheap, real raise/catch coverage of the exception classes + the
    deprecated mollie_exceptions re-export shim."""

    def test_hierarchy_is_consistent(self):
        self.assertTrue(issubclass(MollieWebhookError, MollieIntegrationError))
        self.assertTrue(issubclass(MolliePaymentError, MollieWebhookError))
        self.assertTrue(issubclass(MollieSecurityError, MollieWebhookError))
        self.assertTrue(issubclass(MollieValidationError, MollieWebhookError))

    def test_payment_error_stores_all_context(self):
        original = ValueError("root cause")
        err = MolliePaymentError(
            "failed",
            payment_id="tr_1",
            customer_id="cst_1",
            subscription_id="sub_1",
            mandate_id="mdt_1",
            original_error=original,
            details={"k": "v"},
        )
        self.assertEqual(str(err), "failed")
        self.assertEqual(err.payment_id, "tr_1")
        self.assertEqual(err.customer_id, "cst_1")
        self.assertEqual(err.subscription_id, "sub_1")
        self.assertEqual(err.mandate_id, "mdt_1")
        self.assertIs(err.original_error, original)
        self.assertEqual(err.details, {"k": "v"})

    def test_catch_by_base(self):
        for exc_cls in (MolliePaymentError, MollieSecurityError, MollieValidationError):
            with self.assertRaises(MollieIntegrationError):
                raise exc_cls("boom")

    def test_deprecated_module_reexports_canonical_classes(self):
        # The deprecated mollie_exceptions shim re-exports the canonical classes.
        # NOTE: the module's __getattr__ deprecation-warning hook is effectively
        # dead for the names in __all__, because `from ..exceptions import (...)`
        # binds them at module top-level so attribute access resolves them
        # directly and never reaches __getattr__. We pin the real behaviour:
        # the re-exported symbols ARE the canonical classes.
        from verenigingen.verenigingen_payments.mollie.core import mollie_exceptions

        self.assertIs(mollie_exceptions.MolliePaymentError, MolliePaymentError)
        self.assertIs(mollie_exceptions.MollieSecurityError, MollieSecurityError)
        self.assertIs(mollie_exceptions.MollieValidationError, MollieValidationError)
        self.assertIn("MolliePaymentError", mollie_exceptions.__all__)

    def test_deprecated_module_unknown_attribute_raises(self):
        from verenigingen.verenigingen_payments.mollie.core import mollie_exceptions

        with self.assertRaises(AttributeError):
            _ = mollie_exceptions.NoSuchExceptionClass


if __name__ == "__main__":
    unittest.main()
