"""
Unit coverage for SubscriptionService.list_subscriptions and the api/mollie_payment
shaping helpers, exercised with an injected fake Mollie client.

These verify the relocation (the production subscription-management methods now live
on SubscriptionService, not MollieDebugService) and that amounts flow as structured
values rather than a formatted string that callers re-parse. The Mollie SDK boundary
is the only thing faked — SubscriptionService is built to accept an injected client
for exactly this purpose — so the service's own logic runs for real.
"""

from verenigingen.api import mollie_payment as mp
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService


class _FakeSub:
    """A minimal stand-in for a Mollie SDK subscription object."""

    def __init__(self, sub_id, status, value, currency="EUR", interval="1 month", description="Dues"):
        self.id = sub_id
        self.status = status
        self.amount = {"currency": currency, "value": value}
        self.interval = interval
        self.description = description
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.next_payment_date = "2026-07-01"
        self.canceled_at = None
        self._links = {}


class _FakeSubscriptions:
    def __init__(self, subs):
        self._subs = subs

    def list(self, limit=50):
        return list(self._subs)


class _FakeCustomer:
    def __init__(self, subs):
        self.subscriptions = _FakeSubscriptions(subs)


class _FakeCustomers:
    def __init__(self, subs):
        self._subs = subs

    def get(self, customer_id):
        return _FakeCustomer(self._subs)


class _FakeSdkClient:
    def __init__(self, subs):
        self.customers = _FakeCustomers(subs)


class _FakeMollieClient:
    """Fake of the production MollieClient — only the surface list_subscriptions uses."""

    def __init__(self, subs):
        self.sdk_client = _FakeSdkClient(subs)

    def is_test_mode(self):
        return True


class TestSubscriptionServiceList(EnhancedTestCase):
    """SubscriptionService.list_subscriptions returns structured amounts and filters status."""

    def _service(self, subs):
        return SubscriptionService(client=_FakeMollieClient(subs))

    def test_list_returns_structured_amount_and_display_string(self):
        """Each subscription carries a numeric amount_value + currency (no string
        round-trip) alongside the human-readable amount string for display."""
        result = self._service([_FakeSub("sub_1", "active", "25.00")]).list_subscriptions(
            "cst_aaaaaaaaaa", active_only=False
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["total_found"], 1)
        sub = result["subscriptions"][0]
        self.assertEqual(sub["amount_value"], 25.0)  # structured float
        self.assertEqual(sub["currency"], "EUR")
        self.assertEqual(sub["amount"], "EUR 25.00")  # display string preserved for debug page
        self.assertEqual(sub["status"], "active")

    def test_active_only_filters_canceled(self):
        """active_only=True drops non-active subscriptions; active_only=False keeps all."""
        subs = [_FakeSub("sub_1", "active", "10.00"), _FakeSub("sub_2", "canceled", "10.00")]

        active = self._service(subs).list_subscriptions("cst_aaaaaaaaaa", active_only=True)
        self.assertEqual(active["total_found"], 1)
        self.assertEqual(active["subscriptions"][0]["id"], "sub_1")

        every = self._service(subs).list_subscriptions("cst_aaaaaaaaaa", active_only=False)
        self.assertEqual(every["total_found"], 2)

    def test_missing_customer_id_raises(self):
        with self.assertRaises(ValueError):
            self._service([]).list_subscriptions("")

    def test_shape_subscription_reads_structured_amount(self):
        """The api helper consumes amount_value/currency directly — no string parsing —
        and derives is_active/is_canceled from status."""
        sub = {
            "id": "sub_1",
            "status": "active",
            "amount_value": 25.0,
            "currency": "EUR",
            "interval": "1 month",
            "next_payment_date": "2026-07-01",
            "description": "Dues",
            "amount": "EUR 25.00",
        }
        info = {
            "customer_id": "cst_aaaaaaaaaa",
            "source": "member",
            "local_status": "active",
            "local_cancelled_date": None,
        }

        shaped = mp._shape_subscription(sub, info, mandate_valid=True, mandate_status="valid")

        self.assertEqual(shaped["subscription"]["amount"], 25.0)
        self.assertEqual(shaped["subscription"]["currency"], "EUR")
        self.assertTrue(shaped["subscription"]["is_active"])
        self.assertFalse(shaped["subscription"]["is_canceled"])
        self.assertTrue(shaped["mandate_valid"])

    def test_customer_only_entry_omits_mandate_status_when_unchecked(self):
        """On a list error (mandate validity not checked) the entry has no
        mandate_status key; when checked (even None) the key is present."""
        info = {"customer_id": "cst_aaaaaaaaaa", "source": "member"}

        unchecked = mp._customer_only_entry(info, error="boom")
        self.assertNotIn("mandate_status", unchecked)
        self.assertEqual(unchecked["error"], "boom")
        self.assertFalse(unchecked["mandate_valid"])

        checked = mp._customer_only_entry(info, mandate_valid=False, mandate_status=None, note="no subs")
        self.assertIn("mandate_status", checked)
        self.assertIsNone(checked["mandate_status"])
        self.assertEqual(checked["note"], "no subs")
