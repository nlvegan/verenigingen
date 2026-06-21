# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for MollieWebhookService.

The service queries real Member records for active Mollie subscriptions,
aggregates webhook info, and bulk-updates webhook URLs. The only external
boundary is the Mollie SDK, reached exclusively through
``MollieDebugService.debug_subscription`` / ``update_subscription_webhook``.
We replace that single seam with an in-memory fake (no business logic mocked)
and build real Members so the get_all() filter and aggregation run for real.
"""

import frappe

from verenigingen.services.payment.mollie_webhook_service import (
    MollieWebhookService,
    get_mollie_webhook_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class FakeDebugService:
    """In-memory stand-in for MollieDebugService (the Mollie SDK boundary).

    Maps subscription_id -> canned debug_subscription() result and records
    every update_subscription_webhook() call so tests can assert behaviour.
    """

    def __init__(self, sub_results=None, update_results=None, raise_on=None):
        # subscription_id -> result dict for debug_subscription
        self.sub_results = sub_results or {}
        # subscription_id -> result dict for update_subscription_webhook
        self.update_results = update_results or {}
        # set of subscription_ids that should raise on debug_subscription
        self.raise_on = raise_on or set()
        self.update_calls = []

    def debug_subscription(self, subscription_id, customer_id=None):
        if subscription_id in self.raise_on:
            raise RuntimeError(f"boom for {subscription_id}")
        return self.sub_results.get(
            subscription_id,
            {"subscription_found": False, "error": f"no canned result for {subscription_id}"},
        )

    def update_subscription_webhook(self, customer_id, subscription_id, webhook_url, reason=None):
        self.update_calls.append(
            {
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "webhook_url": webhook_url,
                "reason": reason,
            }
        )
        return self.update_results.get(
            subscription_id,
            {"status": "success", "old_webhook_url": "https://old.example.com/hook"},
        )


class TestMollieWebhookServiceDefaultUrl(EnhancedTestCase):
    """get_default_webhook_url() reads the live Mollie Settings Single."""

    def setUp(self):
        super().setUp()
        self.service = MollieWebhookService()

    def test_test_mode_returns_testing_url(self):
        # Non-committed single writes are visible same-transaction and roll back.
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        frappe.db.set_single_value(
            "Mollie Settings", "testing_webhook_url", "https://test.example.com/hook"
        )
        info = self.service.get_default_webhook_url()
        self.assertEqual(info["webhook_url"], "https://test.example.com/hook")
        self.assertTrue(info["test_mode"])
        self.assertEqual(info["mode_label"], "Test")

    def test_live_mode_returns_live_url(self):
        frappe.db.set_single_value("Mollie Settings", "test_mode", 0)
        frappe.db.set_single_value(
            "Mollie Settings", "live_webhook_url", "https://live.example.com/hook"
        )
        info = self.service.get_default_webhook_url()
        self.assertEqual(info["webhook_url"], "https://live.example.com/hook")
        self.assertFalse(info["test_mode"])
        self.assertEqual(info["mode_label"], "Live")


class TestMollieWebhookServiceActiveSubscriptions(EnhancedTestCase):
    """get_active_subscriptions_with_webhooks() over real Member rows."""

    def setUp(self):
        super().setUp()
        self.service = MollieWebhookService()
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        frappe.db.set_single_value(
            "Mollie Settings", "testing_webhook_url", "https://default.example.com/hook"
        )

    def _make_subscribed_member(self, *, cust_id, sub_id, status="Active"):
        # NB: production filters subscription_status == "Active" (capitalized).
        # Match it exactly so the get_all() row match does not lean on the
        # column's case-insensitive collation.
        member = self.create_test_member(
            first_name="Webhook",
            last_name="Sub",
            email=f"webhook.{frappe.generate_hash(length=6)}@example.com",
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "mollie_customer_id": cust_id,
                "mollie_subscription_id": sub_id,
                "subscription_status": status,
            },
            update_modified=False,
        )
        return member

    def test_aggregates_found_subscription(self):
        member = self._make_subscribed_member(cust_id="cst_aaa0000001", sub_id="sub_aaa0000001")
        fake = FakeDebugService(
            sub_results={
                "sub_aaa0000001": {
                    "subscription_found": True,
                    "subscription_data": {
                        "status": "active",
                        "webhook_url": "https://current.example.com/hook",
                        "amount": "25.00 EUR",
                        "interval": "1 month",
                    },
                }
            }
        )
        self.service._debug_service = fake

        result = self.service.get_active_subscriptions_with_webhooks()

        rows = [s for s in result["subscriptions"] if s["member_id"] == member.name]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["subscription_id"], "sub_aaa0000001")
        self.assertEqual(row["current_webhook_url"], "https://current.example.com/hook")
        self.assertEqual(row["amount"], "25.00 EUR")
        self.assertEqual(result["default_webhook_url"], "https://default.example.com/hook")
        self.assertTrue(result["test_mode"])

    def test_records_error_result(self):
        member = self._make_subscribed_member(cust_id="cst_bbb0000001", sub_id="sub_bbb0000001")
        fake = FakeDebugService(
            sub_results={
                "sub_bbb0000001": {"subscription_found": False, "error": "Subscription not found at Mollie"}
            }
        )
        self.service._debug_service = fake

        result = self.service.get_active_subscriptions_with_webhooks()

        errs = [e for e in result["errors"] if e["member_id"] == member.name]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["error"], "Subscription not found at Mollie")

    def test_exception_in_debug_is_captured_as_error(self):
        member = self._make_subscribed_member(cust_id="cst_ccc0000001", sub_id="sub_ccc0000001")
        fake = FakeDebugService(raise_on={"sub_ccc0000001"})
        self.service._debug_service = fake

        result = self.service.get_active_subscriptions_with_webhooks()

        errs = [e for e in result["errors"] if e["member_id"] == member.name]
        self.assertEqual(len(errs), 1)
        self.assertIn("boom", errs[0]["error"])

    def test_progress_callback_invoked(self):
        self._make_subscribed_member(cust_id="cst_ddd0000001", sub_id="sub_ddd0000001")
        fake = FakeDebugService(
            sub_results={
                "sub_ddd0000001": {
                    "subscription_found": True,
                    "subscription_data": {"status": "active", "webhook_url": None},
                }
            }
        )
        self.service._debug_service = fake

        events = []

        def cb(message, progress):
            events.append((message, progress))

        self.service.get_active_subscriptions_with_webhooks(progress_callback=cb)

        # Start (10) and Complete (100) are always reported.
        self.assertTrue(any(p == 10 for _, p in events))
        self.assertTrue(any(p == 100 for _, p in events))


class TestMollieWebhookServiceBulkUpdate(EnhancedTestCase):
    """bulk_update_webhooks() validation and per-subscription accounting."""

    def setUp(self):
        super().setUp()
        self.service = MollieWebhookService()

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            self.service.bulk_update_webhooks([{"customer_id": "c", "subscription_id": "s"}], "")

    def test_rejects_non_https_url(self):
        with self.assertRaises(ValueError):
            self.service.bulk_update_webhooks(
                [{"customer_id": "c", "subscription_id": "s"}], "http://insecure.example.com/hook"
            )

    def test_rejects_empty_subscription_list(self):
        with self.assertRaises(ValueError):
            self.service.bulk_update_webhooks([], "https://new.example.com/hook")

    def test_counts_success_and_error(self):
        fake = FakeDebugService(
            update_results={
                "sub_ok000001": {"status": "success", "old_webhook_url": "https://old1/hook"},
                "sub_bad00001": {"status": "error", "message": "Mollie rejected the update"},
            }
        )
        self.service._debug_service = fake

        result = self.service.bulk_update_webhooks(
            [
                {"customer_id": "cst_1", "subscription_id": "sub_ok000001"},
                {"customer_id": "cst_2", "subscription_id": "sub_bad00001"},
            ],
            "https://new.example.com/hook",
        )

        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["success"], 1)
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["new_webhook_url"], "https://new.example.com/hook")

        by_sub = {r["subscription_id"]: r for r in result["results"]}
        self.assertEqual(by_sub["sub_ok000001"]["status"], "success")
        self.assertEqual(by_sub["sub_ok000001"]["old_webhook_url"], "https://old1/hook")
        self.assertEqual(by_sub["sub_bad00001"]["status"], "error")
        self.assertEqual(by_sub["sub_bad00001"]["error"], "Mollie rejected the update")

        # The new URL and reason were actually passed to the SDK boundary.
        self.assertEqual(len(fake.update_calls), 2)
        self.assertTrue(all(c["webhook_url"] == "https://new.example.com/hook" for c in fake.update_calls))

    def test_exception_during_update_recorded_as_error(self):
        class RaisingDebug(FakeDebugService):
            def update_subscription_webhook(self, **kwargs):
                raise RuntimeError("network down")

        self.service._debug_service = RaisingDebug()

        result = self.service.bulk_update_webhooks(
            [{"customer_id": "cst_x", "subscription_id": "sub_x0000001"}],
            "https://new.example.com/hook",
        )
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertIn("network down", result["results"][0]["error"])


class TestMollieWebhookServiceAccessAndFactory(EnhancedTestCase):
    """has_admin_access() against real roles + factory."""

    def test_factory_returns_instance(self):
        self.assertIsInstance(get_mollie_webhook_service(), MollieWebhookService)

    def test_administrator_has_admin_access(self):
        # The suite runs as Administrator, which is in ALLOWED_ROLES.
        service = MollieWebhookService()
        self.assertTrue(service.has_admin_access())
