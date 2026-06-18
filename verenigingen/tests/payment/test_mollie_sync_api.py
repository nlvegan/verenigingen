"""Tests for the Mollie Sync API endpoints (mollie/api/sync.py).

These cover the orchestration logic in sync.py: the five whitelisted
endpoints (sync_payment_status, sync_subscription_status,
sync_customer_payments, sync_member_subscriptions, bulk_sync_recent_payments)
and the four internal helpers (_update_local_subscription_records,
_update_member_subscription_status, _handle_subscription_status_change,
_notify_subscription_status_change).

The Mollie service/client classes (PaymentService, SubscriptionService,
MollieClient) are EXTERNAL HTTP boundaries; they are patched with
deterministic fakes. sync.py's own orchestration -- including the
_update_* helpers and the audit-log SQL -- runs for real against the DB.

The whitelisted endpoints are decorated with @standard_api which adds
rate-limiting / request-size validation that is irrelevant to sync.py's
logic and flaky in-process. We therefore call the *raw* underlying
functions (via __wrapped__) while still running inside
`with self.set_user("Administrator")` so that the in-body
`frappe.only_for(...)` role gate is genuinely exercised.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import sync as sync_module
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError

SYNC_PATH = "verenigingen.verenigingen_payments.mollie.api.sync"


def _raw(fn):
    """Unwrap a @frappe.whitelist + @standard_api decorated function."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


sync_payment_status = _raw(sync_module.sync_payment_status)
sync_subscription_status = _raw(sync_module.sync_subscription_status)
sync_customer_payments = _raw(sync_module.sync_customer_payments)
sync_member_subscriptions = _raw(sync_module.sync_member_subscriptions)
bulk_sync_recent_payments = _raw(sync_module.bulk_sync_recent_payments)

# Direct references to internal helpers (not decorated).
_update_local_subscription_records = sync_module._update_local_subscription_records
_update_member_subscription_status = sync_module._update_member_subscription_status
_handle_subscription_status_change = sync_module._handle_subscription_status_change
_notify_subscription_status_change = sync_module._notify_subscription_status_change


class _FakePaymentService:
    """Deterministic stand-in for PaymentService."""

    def __init__(self, status=None, completion_result=None, raise_on_status=False):
        self._status = status or {"status": "paid", "is_paid": True}
        self._completion_result = completion_result
        self._raise_on_status = raise_on_status
        self.completion_calls = []

    def get_payment_status(self, payment_id):
        if self._raise_on_status:
            raise RuntimeError("mollie boom")
        return self._status

    def process_payment_completion(self, payment_id):
        self.completion_calls.append(payment_id)
        return self._completion_result if self._completion_result is not None else {"ok": True}


class _FakeSubscriptionService:
    """Deterministic stand-in for SubscriptionService."""

    def __init__(self, status=None, member_subscriptions=None):
        self._status = status or {
            "id": "sub_test",
            "customer_id": "cst_test",
            "status": "active",
            "next_payment_date": "2026-07-01",
        }
        self._member_subscriptions = member_subscriptions or []

    def get_subscription_status(self, customer_id, subscription_id):
        return self._status

    def list_member_subscriptions(self, member_id):
        return self._member_subscriptions


def _make_payment_obj(pid, status, value="10.00", currency="EUR"):
    """Build a SimpleNamespace mimicking a Mollie SDK payment object."""
    return SimpleNamespace(
        id=pid,
        amount={"value": value, "currency": currency},
        status=status,
        paid_at="2026-06-01T00:00:00+00:00",
        method="creditcard",
        description=f"Payment {pid}",
    )


class _ExplodingPayment:
    """A 'payment' whose attribute access raises, to hit the per-payment
    error branch in sync_customer_payments."""

    @property
    def id(self):
        return "tr_explode"

    @property
    def amount(self):
        raise ValueError("bad amount")


class _FakeClient:
    def __init__(self, payments):
        self._payments = payments

    def list_customer_payments(self, customer_id, limit=50):
        return self._payments


class TestMollieSyncAPI(EnhancedTestCase):
    """Exercise sync.py orchestration with the Mollie HTTP boundary faked."""

    # ------------------------------------------------------------------
    # Member helpers (creation in helpers, never in test bodies)
    # ------------------------------------------------------------------
    def _make_member_with_mollie(
        self,
        customer_id="cst_test",
        subscription_id="sub_test",
        subscription_status="active",
    ):
        """Create a real Member carrying Mollie subscription fields."""
        member = self.create_test_member(
            first_name="Mollie",
            last_name="Syncer",
            email=f"mollie.sync.{frappe.generate_hash(length=8)}@example.com",
        )
        member.mollie_customer_id = customer_id
        member.mollie_subscription_id = subscription_id
        member.subscription_status = subscription_status
        member.save(ignore_permissions=True)
        return member

    def _make_plain_member(self):
        """Member without any Mollie customer ID."""
        return self.create_test_member(
            first_name="Plain",
            last_name="Member",
            email=f"plain.{frappe.generate_hash(length=8)}@example.com",
        )

    # ------------------------------------------------------------------
    # sync_payment_status
    # ------------------------------------------------------------------
    def test_sync_payment_status_paid_processes_completion(self):
        fake = _FakePaymentService(
            status={"status": "paid", "is_paid": True}, completion_result={"entry": "PE-1"}
        )
        with patch(f"{SYNC_PATH}.PaymentService", return_value=fake):
            with self.set_user("Administrator"):
                result = sync_payment_status("tr_paid")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_id"], "tr_paid")
        self.assertTrue(result["payment_status"]["is_paid"])
        self.assertIsNotNone(result["processing_result"])
        self.assertEqual(result["processing_result"], {"entry": "PE-1"})
        # process_payment_completion must have been invoked for the paid payment
        self.assertEqual(fake.completion_calls, ["tr_paid"])

    def test_sync_payment_status_unpaid_skips_completion(self):
        fake = _FakePaymentService(status={"status": "open", "is_paid": False})
        with patch(f"{SYNC_PATH}.PaymentService", return_value=fake):
            with self.set_user("Administrator"):
                result = sync_payment_status("tr_open")

        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["processing_result"])
        self.assertEqual(fake.completion_calls, [])

    def test_sync_payment_status_missing_id_raises(self):
        # Empty payment_id triggers the inner raise, re-wrapped as MollieIntegrationError.
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync_payment_status("")

    def test_sync_payment_status_service_error_rewrapped(self):
        fake = _FakePaymentService(raise_on_status=True)
        with patch(f"{SYNC_PATH}.PaymentService", return_value=fake):
            with self.set_user("Administrator"):
                with self.assertRaises(MollieIntegrationError):
                    sync_payment_status("tr_x")

    # ------------------------------------------------------------------
    # sync_subscription_status
    # ------------------------------------------------------------------
    def test_sync_subscription_status_success(self):
        fake = _FakeSubscriptionService(
            status={
                "id": "sub_test",
                "customer_id": "cst_test",
                "status": "active",
                "next_payment_date": "2026-08-01",
            }
        )
        with patch(f"{SYNC_PATH}.SubscriptionService", return_value=fake):
            with self.set_user("Administrator"):
                result = sync_subscription_status("cst_test", "sub_test")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["customer_id"], "cst_test")
        self.assertEqual(result["subscription_id"], "sub_test")
        self.assertEqual(result["subscription_status"]["status"], "active")
        # local_updates dict is produced by the real helper
        self.assertIn("updated_records", result["local_updates"])

    def test_sync_subscription_status_missing_ids_raises(self):
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync_subscription_status("", "sub_test")
            with self.assertRaises(MollieIntegrationError):
                sync_subscription_status("cst_test", "")

    def test_sync_subscription_status_updates_matching_member(self):
        member = self._make_member_with_mollie(
            customer_id="cst_match", subscription_id="sub_match", subscription_status="active"
        )
        fake = _FakeSubscriptionService(
            status={
                "id": "sub_match",
                "customer_id": "cst_match",
                "status": "canceled",
                "next_payment_date": None,
            }
        )
        with patch(f"{SYNC_PATH}.SubscriptionService", return_value=fake):
            with self.set_user("Administrator"):
                result = sync_subscription_status("cst_match", "sub_match")

        self.assertEqual(result["local_updates"]["updated_records"], 1)
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")

    # ------------------------------------------------------------------
    # sync_customer_payments
    # ------------------------------------------------------------------
    def test_sync_customer_payments_two_payments(self):
        payments = [
            _make_payment_obj("tr_paid", "paid"),
            _make_payment_obj("tr_open", "open"),
        ]
        fake_client = _FakeClient(payments)
        fake_service = _FakePaymentService(completion_result={"entry": "PE-9"})
        with patch(f"{SYNC_PATH}.MollieClient", return_value=fake_client), patch(
            f"{SYNC_PATH}.PaymentService", return_value=fake_service
        ):
            with self.set_user("Administrator"):
                result = sync_customer_payments("cst_test")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payments_synced"], 2)
        # The paid payment, with no pre-existing audit log, should be processed.
        self.assertEqual(fake_service.completion_calls, ["tr_paid"])
        paid_entry = next(p for p in result["payments"] if p["id"] == "tr_paid")
        self.assertIn("processing_result", paid_entry)
        self.assertEqual(paid_entry["amount"], 10.0)
        self.assertEqual(paid_entry["currency"], "EUR")
        open_entry = next(p for p in result["payments"] if p["id"] == "tr_open")
        self.assertNotIn("processing_result", open_entry)

    def test_sync_customer_payments_per_payment_error_recorded(self):
        # The exploding payment raises on amount access; sync should catch it
        # and record an {"id":.., "error":..} entry rather than aborting.
        payments = [_make_payment_obj("tr_good", "open"), _ExplodingPayment()]
        fake_client = _FakeClient(payments)
        with patch(f"{SYNC_PATH}.MollieClient", return_value=fake_client), patch(
            f"{SYNC_PATH}.PaymentService", return_value=_FakePaymentService()
        ):
            with self.set_user("Administrator"):
                result = sync_customer_payments("cst_test")

        self.assertEqual(result["payments_synced"], 2)
        error_entry = next(p for p in result["payments"] if p["id"] == "tr_explode")
        self.assertIn("error", error_entry)

    def test_sync_customer_payments_missing_id_raises(self):
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync_customer_payments("")

    # ------------------------------------------------------------------
    # sync_member_subscriptions
    # ------------------------------------------------------------------
    def test_sync_member_subscriptions_no_customer_id_skipped(self):
        member = self._make_plain_member()
        with self.set_user("Administrator"):
            result = sync_member_subscriptions(member.name)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["member_id"], member.name)

    def test_sync_member_subscriptions_success(self):
        member = self._make_member_with_mollie(
            customer_id="cst_member", subscription_id="sub_member", subscription_status="active"
        )
        fake = _FakeSubscriptionService(
            status={
                "id": "sub_member",
                "customer_id": "cst_member",
                "status": "suspended",
                "next_payment_date": None,
            },
            member_subscriptions=[{"id": "sub_member"}],
        )
        with patch(f"{SYNC_PATH}.SubscriptionService", return_value=fake):
            with self.set_user("Administrator"):
                result = sync_member_subscriptions(member.name)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscriptions_synced"], 1)
        entry = result["subscriptions"][0]
        self.assertEqual(entry["subscription_id"], "sub_member")
        self.assertTrue(entry["local_updates"]["updated"])
        member.reload()
        self.assertEqual(member.subscription_status, "suspended")

    def test_sync_member_subscriptions_missing_id_raises(self):
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync_member_subscriptions("")

    # ------------------------------------------------------------------
    # bulk_sync_recent_payments
    # ------------------------------------------------------------------
    def test_bulk_sync_clamps_hours(self):
        with patch(f"{SYNC_PATH}.PaymentService", return_value=_FakePaymentService()):
            with self.set_user("Administrator"):
                result = bulk_sync_recent_payments(hours=1000)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["timeframe_hours"], 168)

    def test_bulk_sync_no_logs_zero_counts(self):
        # With no matching audit logs in the recent window, all counters are 0.
        with patch(f"{SYNC_PATH}.PaymentService", return_value=_FakePaymentService()):
            with self.set_user("Administrator"):
                result = bulk_sync_recent_payments(hours=1)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["timeframe_hours"], 1)
        self.assertEqual(result["results"]["synced"], 0)
        self.assertEqual(result["results"]["errors"], 0)
        self.assertEqual(result["results"]["skipped"], 0)

    # ------------------------------------------------------------------
    # _update_local_subscription_records (direct)
    # ------------------------------------------------------------------
    def test_update_local_records_matching_member(self):
        member = self._make_member_with_mollie(
            customer_id="cst_local", subscription_id="sub_local", subscription_status="active"
        )
        status = {
            "id": "sub_local",
            "customer_id": "cst_local",
            "status": "canceled",
            "next_payment_date": "2026-09-01",
        }
        with self.set_user("Administrator"):
            updates = _update_local_subscription_records(status)

        self.assertEqual(updates["updated_records"], 1)
        self.assertEqual(updates["errors"], [])
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")
        self.assertEqual(str(member.next_payment_date), "2026-09-01")

    def test_update_local_records_no_match(self):
        status = {
            "id": "sub_nonexistent",
            "customer_id": "cst_nonexistent",
            "status": "active",
            "next_payment_date": None,
        }
        with self.set_user("Administrator"):
            updates = _update_local_subscription_records(status)

        self.assertEqual(updates["updated_records"], 0)
        self.assertEqual(updates["errors"], [])

    def test_update_local_records_missing_keys_recorded_as_error(self):
        # Missing "customer_id" -> KeyError caught by outer try -> general error.
        with self.set_user("Administrator"):
            updates = _update_local_subscription_records({"id": "sub_only"})

        self.assertEqual(updates["updated_records"], 0)
        self.assertEqual(len(updates["errors"]), 1)

    # ------------------------------------------------------------------
    # _update_member_subscription_status (direct)
    # ------------------------------------------------------------------
    def test_update_member_status_change_active_to_canceled(self):
        member = self._make_member_with_mollie(
            customer_id="cst_chg", subscription_id="sub_chg", subscription_status="active"
        )
        status = {"status": "canceled", "next_payment_date": None}
        with self.set_user("Administrator"):
            result = _update_member_subscription_status(member, status)

        self.assertTrue(result["updated"])
        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["previous_status"], "active")
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")

    def test_update_member_status_no_change(self):
        member = self._make_member_with_mollie(
            customer_id="cst_same", subscription_id="sub_same", subscription_status="active"
        )
        status = {"status": "active", "next_payment_date": "2026-10-01"}
        with self.set_user("Administrator"):
            result = _update_member_subscription_status(member, status)

        self.assertTrue(result["updated"])
        self.assertEqual(result["previous_status"], "active")
        self.assertEqual(result["status"], "active")

    def test_update_member_status_missing_status_key_returns_failure(self):
        member = self._make_member_with_mollie(
            customer_id="cst_fail", subscription_id="sub_fail", subscription_status="active"
        )
        # No "status" key -> KeyError caught -> {"updated": False, "error": ...}
        with self.set_user("Administrator"):
            result = _update_member_subscription_status(member, {})

        self.assertFalse(result["updated"])
        self.assertIn("error", result)

    # ------------------------------------------------------------------
    # _handle_subscription_status_change (direct)
    # ------------------------------------------------------------------
    def test_handle_status_change_cancel_does_not_raise(self):
        member = self._make_member_with_mollie(subscription_status="active")
        # Should log but never raise.
        with self.set_user("Administrator"):
            _handle_subscription_status_change(
                member, "active", "canceled", {"id": "sub_test"}
            )

    def test_handle_status_change_reactivation_does_not_raise(self):
        member = self._make_member_with_mollie(subscription_status="canceled")
        with self.set_user("Administrator"):
            _handle_subscription_status_change(
                member, "canceled", "active", {"id": "sub_test"}
            )

    def test_handle_status_change_swallows_errors(self):
        # Pass an object lacking .name/.email; the helper must swallow the
        # AttributeError internally (status update > notification).
        broken = SimpleNamespace()
        with self.set_user("Administrator"):
            # Must not raise.
            _handle_subscription_status_change(broken, "active", "canceled", {})

    # ------------------------------------------------------------------
    # _notify_subscription_status_change (direct)
    # ------------------------------------------------------------------
    def test_notify_returns_early_for_unmapped_status(self):
        member = self._make_member_with_mollie()
        # new_status not in {canceled, suspended} -> template_name None -> early return.
        with self.set_user("Administrator"):
            # Must not raise and must not attempt to send.
            _notify_subscription_status_change(member, "active", "active", {})

    def test_notify_returns_when_template_missing(self):
        member = self._make_member_with_mollie()
        # "subscription_cancelled" template almost certainly does not exist on
        # the test site -> the existence check returns early without sending.
        if frappe.db.exists("Email Template", "subscription_cancelled"):
            self.skipTest("subscription_cancelled template exists on this site")
        with self.set_user("Administrator"):
            _notify_subscription_status_change(member, "active", "canceled", {"id": "sub_test"})
