"""
Tests for the READ/DEBUG surface of ``MollieDebugService``.

These cover the read-only debugging operations (``debug_*``, ``list_*``,
``search_customers_by_name``, ``test_webhook_processing``) plus the static
helpers (``_sanitize_limit``, ``_sanitize_error_message``,
``_resolve_subscription_start_date``, ``_resolve_payment_mode``).

The Mollie SDK is the external HTTP boundary; it cannot be exercised in
tests. We construct the REAL ``MollieDebugService`` and fake only the three
collaborators wired up in ``__init__`` (the Mollie client, the audit trail,
and the configuration service) at the module import seam. Everything below
that boundary — the result-dict assembly, amount parsing, attribute
fallbacks, and the real Member/Donor database lookups in ``debug_customer`` —
runs for real.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

DEBUG_MODULE = "verenigingen.services.mollie_debug_service"


# ---------------------------------------------------------------------------
# Fake Mollie SDK objects
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API and cannot be reached in tests. These fakes mimic only the small
# slice of the SDK surface the read/debug methods touch and let us drive both
# the success path and the ``except Exception -> result["error"]`` path.
# ---------------------------------------------------------------------------


class _FakeCollection(list):
    """A list that also exposes .list()/.get() like a Mollie SDK collection."""

    def __init__(self, items=None, get_map=None, raises=None):
        super().__init__(items or [])
        self._get_map = get_map or {}
        self._raises = raises

    def list(self, *args, **kwargs):
        if self._raises:
            raise self._raises
        return list(self)

    def get(self, obj_id, *args, **kwargs):
        if self._raises:
            raise self._raises
        if obj_id in self._get_map:
            return self._get_map[obj_id]
        raise Exception(f"Object {obj_id} not found")

    def update(self, obj_id, data, *args, **kwargs):
        return self._get_map.get(obj_id)

    def delete(self, obj_id, *args, **kwargs):
        return self._get_map.get(obj_id)


class _FakeCustomer(SimpleNamespace):
    """A Mollie customer object with nested subscription/mandate/payment collections."""

    def __init__(self, **kwargs):
        kwargs.setdefault("subscriptions", _FakeCollection())
        kwargs.setdefault("mandates", _FakeCollection())
        kwargs.setdefault("payments", _FakeCollection())
        super().__init__(**kwargs)


def _make_fake_sdk_client(customers=None, payments=None, refunds=None, chargebacks=None):
    """Build a fake top-level SDK client exposing .customers/.payments/etc."""
    client = MagicMock(name="sdk_client")
    client.customers = customers if customers is not None else _FakeCollection()
    client.payments = payments if payments is not None else _FakeCollection()
    client.refunds = refunds if refunds is not None else _FakeCollection()
    client.chargebacks = chargebacks if chargebacks is not None else _FakeCollection()
    return client


class MollieDebugReadTestBase(VereningingenTestCase):
    """Constructs a real MollieDebugService with the three __init__ deps faked."""

    def _build_service(self, sdk_client=None, test_mode=True):
        """Build the real service with faked Mollie client / audit / config.

        Returns (service, fake_mollie_client). Patches are stopped on cleanup.
        """
        client_patch = patch(f"{DEBUG_MODULE}.MollieClient")
        audit_patch = patch(f"{DEBUG_MODULE}.get_audit_trail")
        config_patch = patch(f"{DEBUG_MODULE}.get_mollie_config")

        MockMollieClient = client_patch.start()
        mock_get_audit = audit_patch.start()
        mock_get_config = config_patch.start()
        self.addCleanup(client_patch.stop)
        self.addCleanup(audit_patch.stop)
        self.addCleanup(config_patch.stop)

        fake_client = MockMollieClient.return_value
        fake_client.is_test_mode.return_value = test_mode
        fake_client.sdk_client = sdk_client if sdk_client is not None else _make_fake_sdk_client()

        mock_get_audit.return_value = MagicMock(name="audit_trail")

        fake_config = MagicMock(name="config")
        fake_config.is_test_mode.return_value = test_mode
        mock_get_config.return_value = fake_config

        from verenigingen.services.mollie_debug_service import MollieDebugService

        service = MollieDebugService()
        return service, fake_client


# ===========================================================================
# Static / helper methods (no external boundary needed)
# ===========================================================================


class TestSanitizeLimit(unittest.TestCase):
    def setUp(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.fn = MollieDebugService._sanitize_limit

    def test_valid_in_range(self):
        self.assertEqual(self.fn(50), 50)

    def test_min_boundary(self):
        self.assertEqual(self.fn(1), 1)

    def test_max_boundary(self):
        self.assertEqual(self.fn(250), 250)

    def test_zero_falls_back_to_default(self):
        self.assertEqual(self.fn(0), 20)

    def test_above_max_falls_back_to_default(self):
        self.assertEqual(self.fn(251), 20)

    def test_negative_falls_back_to_default(self):
        self.assertEqual(self.fn(-5), 20)

    def test_string_numeric_coerced(self):
        self.assertEqual(self.fn("42"), 42)

    def test_non_numeric_string_falls_back(self):
        self.assertEqual(self.fn("abc"), 20)

    def test_none_falls_back(self):
        self.assertEqual(self.fn(None), 20)

    def test_custom_max_and_default(self):
        # search_customers_by_name uses max_val=100
        self.assertEqual(self.fn(200, max_val=100, default=20), 20)
        self.assertEqual(self.fn(80, max_val=100), 80)


class TestResolvePaymentMode(unittest.TestCase):
    def setUp(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.fn = MollieDebugService._resolve_payment_mode

    def test_missing_payment_id_returns_none_none(self):
        mode, invoice = self.fn({}, "tr_X")
        self.assertIsNone(mode)
        self.assertIsNone(invoice)

    def test_dict_with_mode_and_dict_invoice(self):
        modes = {"tr_X": {"mode": "bt_only", "matching_invoice": {"invoice_name": "SI-001"}}}
        mode, invoice = self.fn(modes, "tr_X")
        self.assertEqual(mode, "bt_only")
        self.assertEqual(invoice, "SI-001")

    def test_dict_with_scalar_invoice(self):
        modes = {"tr_X": {"mode": "bt_pe_reconcile", "matching_invoice": "SI-002"}}
        mode, invoice = self.fn(modes, "tr_X")
        self.assertEqual(mode, "bt_pe_reconcile")
        self.assertEqual(invoice, "SI-002")

    def test_non_dict_entry_ignored(self):
        mode, invoice = self.fn({"tr_X": "not-a-dict"}, "tr_X")
        self.assertIsNone(mode)
        self.assertIsNone(invoice)


class TestSanitizeErrorMessage(MollieDebugReadTestBase):
    def test_sanitizes_and_truncates(self):
        service, _ = self._build_service()
        out = service._sanitize_error_message("Something broke")
        self.assertIsInstance(out, str)
        self.assertTrue(len(out) > 0)

    def test_redacts_api_key_keyword(self):
        service, _ = self._build_service()
        raw = "Connection failed with api_key=test_abcdef1234567890 in request"
        out = service._sanitize_error_message(raw)
        # The raw secret must not survive sanitization verbatim.
        self.assertNotIn("test_abcdef1234567890", out)


class TestResolveSubscriptionStartDate(MollieDebugReadTestBase):
    def test_explicit_date_returned_verbatim(self):
        service, _ = self._build_service()
        self.assertEqual(service._resolve_subscription_start_date("2026-01-15", "1 month"), "2026-01-15")

    def test_monthly_without_date_returns_none(self):
        service, _ = self._build_service()
        # Only quarterly/yearly auto-calculate; "1 month" should yield None.
        self.assertIsNone(service._resolve_subscription_start_date(None, "1 month"))

    def test_quarterly_auto_calculates_from_settings(self):
        service, _ = self._build_service()
        fake_settings = MagicMock()
        fake_settings.get_next_payment_date_for_scheduled_months.return_value = "2026-03-01"
        fake_settings.quarterly_yearly_payment_months = "3,6,9,12"
        with patch.object(frappe, "get_single", return_value=fake_settings):
            out = service._resolve_subscription_start_date(None, "3 months")
        self.assertEqual(out, "2026-03-01")
        fake_settings.get_next_payment_date_for_scheduled_months.assert_called_once_with(min_months_ahead=2)

    def test_quarterly_no_calculated_date_returns_none(self):
        service, _ = self._build_service()
        fake_settings = MagicMock()
        fake_settings.get_next_payment_date_for_scheduled_months.return_value = None
        with patch.object(frappe, "get_single", return_value=fake_settings):
            out = service._resolve_subscription_start_date(None, "12 months")
        self.assertIsNone(out)


# ===========================================================================
# Required-param guards (each must raise ValueError)
# ===========================================================================


class TestRequiredParamGuards(MollieDebugReadTestBase):
    def setUp(self):
        super().setUp()
        self.service, _ = self._build_service()

    def test_debug_customer_requires_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_customer("")

    def test_debug_subscription_requires_subscription_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_subscription("", customer_id="cst_1")

    def test_debug_subscription_requires_customer_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_subscription("sub_1", customer_id=None)

    def test_debug_mandate_requires_mandate_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_mandate("", customer_id="cst_1")

    def test_debug_mandate_requires_customer_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_mandate("mdt_1", customer_id=None)

    def test_debug_payment_requires_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_payment("")

    def test_debug_refund_requires_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_refund("")

    def test_debug_webhook_delivery_requires_id(self):
        with self.assertRaises(ValueError):
            self.service.debug_webhook_delivery("")

    def test_test_webhook_processing_requires_id(self):
        with self.assertRaises(ValueError):
            self.service.test_webhook_processing("")


# ===========================================================================
# debug_customer
# ===========================================================================


class TestDebugCustomer(MollieDebugReadTestBase):
    def _make_member_with_mollie(self, customer_id, **kwargs):
        """Factory helper: create a tracked Member linked to a Mollie customer."""
        return self.factory.create_test_member(
            mollie_customer_id=customer_id,
            mollie_subscription_id="sub_TEST",
            subscription_status="active",
            payment_method="Mollie",
            **kwargs,
        )

    def test_success_with_subscriptions_and_mandates(self):
        customer_id = "cst_DEBUGOK"
        sub = SimpleNamespace(
            id="sub_1",
            status="active",
            amount={"value": "10.00", "currency": "EUR"},
            interval="1 month",
            description="Monthly dues",
            created_at="2026-01-01",
            next_payment_date="2026-02-01",
            canceled_at=None,
            mandateId="mdt_1",
        )
        mandate = SimpleNamespace(
            id="mdt_1",
            status="valid",
            method="directdebit",
            created_at="2026-01-01",
            mandate_reference="REF-1",
            signature_date="2025-12-31",
        )
        customer_obj = _FakeCustomer(
            id=customer_id,
            name="Jane Tester",
            email="jane@example.com",
            created_at="2026-01-01",
            mode="test",
            subscriptions=_FakeCollection([sub]),
            mandates=_FakeCollection([mandate]),
        )
        sdk = _make_fake_sdk_client(customers=_FakeCollection(get_map={customer_id: customer_obj}))
        service, fake_client = self._build_service(sdk_client=sdk)
        # MollieClient.get_customer returns a customer object too.
        fake_client.get_customer.return_value = SimpleNamespace(
            id=customer_id,
            name="Jane Tester",
            email="jane@example.com",
            created_at="2026-01-01",
            mode="test",
        )

        result = service.debug_customer(customer_id)

        self.assertTrue(result["customer_found"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["customer_data"]["id"], customer_id)
        self.assertEqual(len(result["subscriptions"]), 1)
        # Amount parsed from dict form -> "value currency".
        self.assertEqual(result["subscriptions"][0]["amount"], "10.00 EUR")
        self.assertEqual(result["subscriptions"][0]["mandate_id"], "mdt_1")
        self.assertEqual(len(result["mandates"]), 1)
        self.assertEqual(result["mandates"][0]["status"], "valid")
        self.assertTrue(result["test_mode"])

    def test_scalar_amount_parsing(self):
        customer_id = "cst_SCALAR"
        sub = SimpleNamespace(
            id="sub_s",
            status="active",
            amount="EUR 5.00",  # scalar, not dict
            interval="1 month",
            description="d",
            created_at="2026-01-01",
            next_payment_date=None,
            canceled_at=None,
            mandateId=None,
        )
        customer_obj = _FakeCustomer(
            id=customer_id,
            name="N",
            email="e@e.com",
            created_at="2026-01-01",
            mode="test",
            subscriptions=_FakeCollection([sub]),
        )
        sdk = _make_fake_sdk_client(customers=_FakeCollection(get_map={customer_id: customer_obj}))
        service, fake_client = self._build_service(sdk_client=sdk)
        fake_client.get_customer.return_value = SimpleNamespace(
            id=customer_id, name="N", email="e@e.com", created_at="2026-01-01", mode="test"
        )

        result = service.debug_customer(customer_id)
        self.assertEqual(result["subscriptions"][0]["amount"], "EUR 5.00")

    def test_api_error_populates_error_but_still_reads_db(self):
        customer_id = "cst_APIFAIL"
        # The Member must still be discovered even when the Mollie API call fails.
        member = self._make_member_with_mollie(customer_id)
        service, fake_client = self._build_service()
        fake_client.get_customer.side_effect = Exception("Mollie 500")

        result = service.debug_customer(customer_id)

        self.assertFalse(result["customer_found"])
        self.assertEqual(result["error"], "Mollie 500")
        member_names = [m["name"] for m in result["database_records"]["members"]]
        self.assertIn(member.name, member_names)

    def test_database_records_member_fields_present(self):
        """Member queries subscription_status + payment_method; verify they resolve."""
        customer_id = "cst_DBFIELDS"
        member = self._make_member_with_mollie(customer_id)
        service, fake_client = self._build_service()
        fake_client.get_customer.side_effect = Exception("skip API")

        result = service.debug_customer(customer_id)
        members = result["database_records"]["members"]
        self.assertEqual(len(members), 1)
        row = members[0]
        # Fields exist on the Member doctype and round-trip from the DB.
        self.assertEqual(row["subscription_status"], "active")
        self.assertEqual(row["payment_method"], "Mollie")
        self.assertEqual(row["mollie_subscription_id"], "sub_TEST")

    def test_donor_records_discovered(self):
        customer_id = "cst_DONOR"
        donor = self.create_test_donor_with_sync(mollie_customer_id=customer_id)
        service, fake_client = self._build_service()
        fake_client.get_customer.side_effect = Exception("skip API")

        result = service.debug_customer(customer_id)
        donor_names = [d["name"] for d in result["database_records"]["donors"]]
        self.assertIn(donor.name, donor_names)


# ===========================================================================
# debug_subscription
# ===========================================================================


class TestDebugSubscription(MollieDebugReadTestBase):
    def _build_with_subscription(self, sub, customer_id="cst_1"):
        customer_obj = _FakeCustomer(subscriptions=_FakeCollection(get_map={sub.id: sub}))
        sdk = _make_fake_sdk_client(customers=_FakeCollection(get_map={customer_id: customer_obj}))
        return self._build_service(sdk_client=sdk)

    def test_success_snake_case_attrs(self):
        sub = SimpleNamespace(
            id="sub_A",
            customer_id="cst_1",
            status="active",
            amount={"value": "12.50", "currency": "EUR"},
            interval="1 month",
            times=12,
            description="desc",
            created_at="2026-01-01",
            start_date="2026-01-15",
            next_payment_date="2026-02-15",
            canceled_at=None,
            mandate_id="mdt_snake",
            webhook_url="https://hook.example/wh",
            metadata={"k": "v"},
        )
        service, _ = self._build_with_subscription(sub)
        result = service.debug_subscription("sub_A", customer_id="cst_1")

        self.assertTrue(result["subscription_found"])
        self.assertIsNone(result["error"])
        data = result["subscription_data"]
        self.assertEqual(data["amount"], "12.50 EUR")
        self.assertEqual(data["times"], 12)
        self.assertEqual(data["mandate_id"], "mdt_snake")
        self.assertEqual(data["webhook_url"], "https://hook.example/wh")
        self.assertEqual(data["start_date"], "2026-01-15")

    def test_camelcase_fallback_for_mandate_and_webhook(self):
        # No snake_case attrs at all -> getattr falls back to camelCase.
        sub = SimpleNamespace(
            id="sub_B",
            customer_id="cst_1",
            status="active",
            amount=None,
            interval="1 month",
            times=None,
            description="d",
            created_at="2026-01-01",
            startDate="2026-03-01",
            canceled_at=None,
            mandateId="mdt_camel",
            webhookUrl="https://camel.example/wh",
        )
        service, _ = self._build_with_subscription(sub)
        result = service.debug_subscription("sub_B", customer_id="cst_1")
        data = result["subscription_data"]
        self.assertEqual(data["mandate_id"], "mdt_camel")
        self.assertEqual(data["webhook_url"], "https://camel.example/wh")
        self.assertEqual(data["start_date"], "2026-03-01")
        # amount None -> "Unknown"
        self.assertEqual(data["amount"], "Unknown")
        # metadata default {} when attribute absent
        self.assertEqual(data["metadata"], {})

    def test_times_property_raising_is_guarded(self):
        """Mollie SDK can raise on .times for unlimited subs; guard yields None."""

        class _RaisingTimesSub:
            id = "sub_C"
            customer_id = "cst_1"
            status = "active"
            amount = None
            interval = "1 month"
            description = "d"
            created_at = "2026-01-01"
            canceled_at = None

            @property
            def times(self):
                raise ValueError("times is None for unlimited subscription")

        service, _ = self._build_with_subscription(_RaisingTimesSub())
        result = service.debug_subscription("sub_C", customer_id="cst_1")
        self.assertTrue(result["subscription_found"])
        self.assertIsNone(result["subscription_data"]["times"])

    def test_api_error_path(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(raises=Exception("no such customer")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_subscription("sub_X", customer_id="cst_missing")
        self.assertFalse(result["subscription_found"])
        self.assertEqual(result["error"], "no such customer")


# ===========================================================================
# debug_mandate
# ===========================================================================


class TestDebugMandate(MollieDebugReadTestBase):
    def test_success(self):
        mandate = SimpleNamespace(
            id="mdt_1",
            status="valid",
            method="directdebit",
            created_at="2026-01-01",
            mandate_reference="REF",
            signature_date="2025-12-31",
            consumer_name="Jane",
            consumer_account="NL00BANK0123456789",
        )
        customer_obj = _FakeCustomer(mandates=_FakeCollection(get_map={mandate.id: mandate}))
        sdk = _make_fake_sdk_client(customers=_FakeCollection(get_map={"cst_1": customer_obj}))
        service, _ = self._build_service(sdk_client=sdk)

        result = service.debug_mandate("mdt_1", customer_id="cst_1")
        self.assertTrue(result["mandate_found"])
        self.assertEqual(result["mandate_data"]["consumer_name"], "Jane")
        self.assertEqual(result["mandate_data"]["signature_date"], "2025-12-31")

    def test_api_error_path(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(raises=Exception("mandate boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_mandate("mdt_1", customer_id="cst_1")
        self.assertFalse(result["mandate_found"])
        self.assertEqual(result["error"], "mandate boom")


# ===========================================================================
# debug_payment
# ===========================================================================


class TestDebugPayment(MollieDebugReadTestBase):
    def _payment(self, **overrides):
        defaults = dict(
            id="tr_1",
            status="paid",
            amount={"value": "20.00", "currency": "EUR"},
            description="Payment",
            method="ideal",
            created_at="2026-01-01",
            paid_at="2026-01-02",
            customer_id="cst_1",
            subscription_id="sub_1",
            mandate_id="mdt_1",
            sequence_type="recurring",
        )
        defaults.update(overrides)
        p = SimpleNamespace(**defaults)
        p.refunds = _FakeCollection()
        p.chargebacks = _FakeCollection()
        return p

    def test_success_with_refunds_and_chargebacks(self):
        refund = SimpleNamespace(
            id="re_1",
            status="refunded",
            amount={"value": "5.00", "currency": "EUR"},
            description="partial",
            created_at="2026-01-03",
            settled_at="2026-01-04",
        )
        chargeback = SimpleNamespace(
            id="chb_1",
            amount={"value": "20.00", "currency": "EUR"},
            created_at="2026-01-05",
            reason="fraud",
            reversed_at=None,
        )
        payment = self._payment()
        payment.refunds = _FakeCollection([refund])
        payment.chargebacks = _FakeCollection([chargeback])
        sdk = _make_fake_sdk_client(payments=_FakeCollection(get_map={"tr_1": payment}))
        service, _ = self._build_service(sdk_client=sdk)

        result = service.debug_payment("tr_1")
        self.assertTrue(result["payment_found"])
        self.assertEqual(result["payment_data"]["amount"], "20.00 EUR")
        self.assertEqual(result["payment_data"]["status"], "paid")
        self.assertEqual(len(result["refunds"]), 1)
        self.assertEqual(result["refunds"][0]["amount"], "5.00 EUR")
        self.assertEqual(len(result["chargebacks"]), 1)
        self.assertEqual(result["chargebacks"][0]["reason"], "fraud")

    def test_refunds_listing_failure_yields_empty_list(self):
        payment = self._payment()
        payment.refunds = _FakeCollection(raises=Exception("no refunds endpoint"))
        sdk = _make_fake_sdk_client(payments=_FakeCollection(get_map={"tr_1": payment}))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_payment("tr_1")
        self.assertTrue(result["payment_found"])
        self.assertEqual(result["refunds"], [])

    def test_payment_not_found_error(self):
        sdk = _make_fake_sdk_client(payments=_FakeCollection(raises=Exception("payment gone")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_payment("tr_missing")
        self.assertFalse(result["payment_found"])
        self.assertEqual(result["error"], "payment gone")


# ===========================================================================
# debug_refund
# ===========================================================================


class TestDebugRefund(MollieDebugReadTestBase):
    def _refund(self):
        return SimpleNamespace(
            id="re_1",
            payment_id="tr_1",
            status="refunded",
            amount={"value": "5.00", "currency": "EUR"},
            description="d",
            created_at="2026-01-01",
            settled_at="2026-01-02",
            metadata={},
            settlement_id="stl_1",
        )

    def test_via_payment(self):
        refund = self._refund()
        payment = SimpleNamespace(refunds=_FakeCollection(get_map={"re_1": refund}))
        sdk = _make_fake_sdk_client(payments=_FakeCollection(get_map={"tr_1": payment}))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_refund("re_1", payment_id="tr_1")
        self.assertTrue(result["refund_found"])
        self.assertEqual(result["refund_data"]["amount"], "5.00 EUR")
        self.assertEqual(result["refund_data"]["settlement_id"], "stl_1")

    def test_direct_lookup(self):
        refund = self._refund()
        sdk = _make_fake_sdk_client(refunds=_FakeCollection(get_map={"re_1": refund}))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_refund("re_1")
        self.assertTrue(result["refund_found"])
        self.assertEqual(result["refund_data"]["id"], "re_1")

    def test_error_path(self):
        sdk = _make_fake_sdk_client(refunds=_FakeCollection(raises=Exception("refund boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_refund("re_x")
        self.assertFalse(result["refund_found"])
        self.assertEqual(result["error"], "refund boom")


# ===========================================================================
# debug_webhook_delivery
# ===========================================================================


class TestDebugWebhookDelivery(MollieDebugReadTestBase):
    def test_builds_status_timeline(self):
        payment = SimpleNamespace(
            id="tr_1",
            webhook_url="https://hook.example/wh",
            status="paid",
            created_at="2026-01-01",
            authorized_at="2026-01-01T01:00",
            paid_at="2026-01-02",
            canceled_at=None,
            expired_at=None,
            failed_at=None,
        )
        sdk = _make_fake_sdk_client(payments=_FakeCollection(get_map={"tr_1": payment}))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_webhook_delivery("tr_1")
        info = result["webhook_info"]
        self.assertEqual(info["webhook_url"], "https://hook.example/wh")
        statuses = [c["status"] for c in info["status_changes"]]
        self.assertEqual(statuses, ["created", "authorized", "paid"])
        self.assertIn("note", info)

    def test_error_path(self):
        sdk = _make_fake_sdk_client(payments=_FakeCollection(raises=Exception("wh boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.debug_webhook_delivery("tr_1")
        self.assertEqual(result["error"], "wh boom")


# ===========================================================================
# list_customers / list_payments / list_chargebacks / list_subscriptions
# ===========================================================================


class TestListCustomers(MollieDebugReadTestBase):
    def test_success(self):
        c1 = SimpleNamespace(id="cst_1", name="A", email="a@a.com", created_at="2026-01-01", mode="test")
        c2 = SimpleNamespace(id="cst_2", name="B", email="b@b.com", created_at="2026-01-02", mode="test")
        sdk = _make_fake_sdk_client(customers=_FakeCollection([c1, c2]))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_customers(limit=50)
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["customers"]), 2)
        self.assertEqual(result["customers"][0]["id"], "cst_1")

    def test_bad_limit_sanitized_to_default(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection([]))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_customers(limit=99999)
        self.assertEqual(result["limit"], 20)

    def test_error_path(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(raises=Exception("list boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_customers()
        self.assertEqual(result["error"], "list boom")


class TestListPayments(MollieDebugReadTestBase):
    def _payment(self, pid, status="paid"):
        return SimpleNamespace(
            id=pid,
            status=status,
            amount={"value": "10.00", "currency": "EUR"},
            description="d",
            method="ideal",
            created_at="2026-01-01",
            customer_id="cst_1",
            subscription_id=None,
            sequence_type="oneoff",
        )

    def test_global_list(self):
        sdk = _make_fake_sdk_client(payments=_FakeCollection([self._payment("tr_1"), self._payment("tr_2")]))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_payments()
        self.assertEqual(len(result["payments"]), 2)
        self.assertIsNone(result["error"])

    def test_per_customer_with_status_filter(self):
        paid = self._payment("tr_paid", status="paid")
        failed = self._payment("tr_failed", status="failed")
        customer_obj = _FakeCustomer(payments=_FakeCollection([paid, failed]))
        sdk = _make_fake_sdk_client(customers=_FakeCollection(get_map={"cst_1": customer_obj}))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_payments(customer_id="cst_1", status_filter="paid")
        ids = [p["id"] for p in result["payments"]]
        self.assertEqual(ids, ["tr_paid"])

    def test_error_path(self):
        sdk = _make_fake_sdk_client(payments=_FakeCollection(raises=Exception("pay list boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_payments()
        self.assertEqual(result["error"], "pay list boom")


class TestListChargebacks(MollieDebugReadTestBase):
    def test_direct_listing(self):
        chb = SimpleNamespace(
            id="chb_1",
            payment_id="tr_1",
            amount={"value": "20.00", "currency": "EUR"},
            created_at="2026-01-01",
            reason="fraud",
            reversed_at=None,
            settlement_id="stl_1",
        )
        sdk = _make_fake_sdk_client(chargebacks=_FakeCollection([chb]))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_chargebacks()
        self.assertEqual(len(result["chargebacks"]), 1)
        self.assertEqual(result["chargebacks"][0]["reason"], "fraud")

    def test_direct_listing_unavailable_sets_message(self):
        sdk = _make_fake_sdk_client(chargebacks=_FakeCollection(raises=Exception("not available")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_chargebacks()
        self.assertIn("Direct chargeback listing not available", result["error"])

    def test_via_customer_payments(self):
        chb = SimpleNamespace(
            id="chb_2",
            amount={"value": "30.00", "currency": "EUR"},
            created_at="2026-01-02",
            reason="dispute",
            reversed_at=None,
            settlement_id=None,
        )
        payment = SimpleNamespace(id="tr_9", chargebacks=_FakeCollection([chb]))
        sdk = _make_fake_sdk_client(payments=_FakeCollection([payment]))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.list_chargebacks(customer_id="cst_1")
        self.assertEqual(len(result["chargebacks"]), 1)
        self.assertEqual(result["chargebacks"][0]["payment_id"], "tr_9")


class TestListSubscriptions(MollieDebugReadTestBase):
    def test_delegates_to_subscription_service(self):
        service, fake_client = self._build_service()
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.subscription_service.SubscriptionService"
        ) as MockSubSvc:
            MockSubSvc.return_value.list_subscriptions.return_value = {
                "subscriptions": [{"id": "sub_1"}],
                "total_found": 1,
                "customer_id": "cst_1",
                "error": None,
            }
            result = service.list_subscriptions("cst_1", limit=10, active_only=False)

        self.assertEqual(result["total_found"], 1)
        MockSubSvc.assert_called_once_with(fake_client)
        MockSubSvc.return_value.list_subscriptions.assert_called_once_with(
            "cst_1", limit=10, active_only=False
        )


# ===========================================================================
# search_customers_by_name
# ===========================================================================


class TestSearchCustomersByName(MollieDebugReadTestBase):
    def _customers(self):
        return [
            SimpleNamespace(
                id="cst_1",
                name="Jane Doe",
                email="jane@example.com",
                created_at="2026-01-01",
                locale="nl_NL",
                mode="test",
            ),
            SimpleNamespace(
                id="cst_2",
                name="John Smith",
                email="john@elsewhere.com",
                created_at="2026-01-02",
                locale="nl_NL",
                mode="test",
            ),
            SimpleNamespace(
                id="cst_3",
                name=None,
                email="jane.alt@example.com",
                created_at="2026-01-03",
                locale="nl_NL",
                mode="test",
            ),
        ]

    def test_short_term_rejected(self):
        service, _ = self._build_service()
        result = service.search_customers_by_name("a")
        self.assertIn("at least 2 characters", result["error"])
        self.assertEqual(result["customers"], [])

    def test_name_match(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(self._customers()))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.search_customers_by_name("jane")
        ids = {c["id"] for c in result["customers"]}
        # Matches cst_1 (name) and cst_3 (email contains jane)
        self.assertEqual(ids, {"cst_1", "cst_3"})
        self.assertEqual(result["total_found"], 2)

    def test_email_only_match(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(self._customers()))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.search_customers_by_name("elsewhere")
        ids = {c["id"] for c in result["customers"]}
        self.assertEqual(ids, {"cst_2"})

    def test_limit_sanitized_to_100_max(self):
        service, _ = self._build_service()
        result = service.search_customers_by_name("xx", limit=500)
        # max_val=100, default=20 -> out-of-range falls back to default 20
        self.assertEqual(result["limit"], 20)

    def test_error_path(self):
        sdk = _make_fake_sdk_client(customers=_FakeCollection(raises=Exception("search boom")))
        service, _ = self._build_service(sdk_client=sdk)
        result = service.search_customers_by_name("jane")
        self.assertEqual(result["error"], "search boom")


# ===========================================================================
# test_webhook_processing
# ===========================================================================


class TestTestWebhookProcessing(MollieDebugReadTestBase):
    def test_success(self):
        service, _ = self._build_service()
        fake_router = MagicMock()
        fake_router.fetch_payment.return_value = SimpleNamespace(id="tr_1")
        fake_router.classify_payment.return_value = {
            "payment_type": "dues",
            "confidence": "high",
            "matched_by": "subscription_id",
        }
        with (
            patch(
                "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
                return_value=fake_router,
            ),
            patch(
                "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook",
                return_value={"status": "ok"},
            ),
        ):
            result = service.test_webhook_processing("tr_1")

        self.assertTrue(result["webhook_called"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_type"], "dues")
        self.assertEqual(result["webhook_status"], "ok")

    def test_error_path(self):
        service, _ = self._build_service()
        fake_router = MagicMock()
        fake_router.fetch_payment.side_effect = Exception("router boom")
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
            return_value=fake_router,
        ):
            result = service.test_webhook_processing("tr_1")

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["webhook_called"])
        self.assertIn("router boom", result["error"])


if __name__ == "__main__":
    unittest.main()
