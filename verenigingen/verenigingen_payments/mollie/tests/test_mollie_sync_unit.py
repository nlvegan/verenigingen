"""
Integration coverage (Tier-2) for the Mollie sync endpoints — api/sync.py.

LIVENESS NOTE: api/sync.py is NOT imported by api/__init__.py (the
``from . import sync`` line is commented out and it is not referenced by any JS,
workspace, scheduler hook, or other Python module). Frappe can still resolve its
@whitelist endpoints by full dotted path at HTTP call time, so it is not provably
dead, but it has zero in-app wiring — see the agent report's dead-code flag. These
tests exercise the parts that do not require a live Mollie connection: the local
DB-update helpers, the input/guard branches, and the role-gate enforcement. The
Mollie SDK boundary (PaymentService / SubscriptionService / MollieClient) is
swapped for test doubles ONLY at the external boundary — the sync module's own
logic is never mocked.

Targets (verenigingen/verenigingen_payments/mollie/api/sync.py):
  - _update_local_subscription_records   (member lookup + field update + error path)
  - _update_member_subscription_status   (status change + save + error path)
  - _handle_subscription_status_change    (cancel/suspend + reactivation branches)
  - sync_member_subscriptions             (no-customer-id skip; missing-id throw)
  - sync_payment_status                   (missing payment_id throw; happy path via double)
  - bulk_sync_recent_payments             (>168h cap + security event; happy path)
  - role-gate enforcement (frappe.only_for) for an unauthorised user
"""

import types
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import sync
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError

_PAYMENT_SERVICE = "verenigingen.verenigingen_payments.mollie.api.sync.PaymentService"
_SUBSCRIPTION_SERVICE = "verenigingen.verenigingen_payments.mollie.api.sync.SubscriptionService"


class _FakePaymentService:
    """Boundary double standing in for the Mollie-backed PaymentService."""

    def __init__(self, status, processing=None):
        self._status = status
        self._processing = processing or {"processed": True}
        self.completed_calls = []

    def get_payment_status(self, payment_id):
        return dict(self._status, payment_id=payment_id)

    def process_payment_completion(self, payment_id):
        self.completed_calls.append(payment_id)
        return self._processing


class TestUpdateLocalSubscriptionRecords(EnhancedTestCase):
    """_update_local_subscription_records — real Member field updates."""

    def _member_with_subscription(self, token):
        member = self.create_test_member(
            first_name="Sync", last_name=f"Local{token}", email=f"sync.local.{token}@example.com"
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": f"cst_{token}", "mollie_subscription_id": f"sub_{token}"},
        )
        return member

    def test_updates_matching_member(self):
        token = frappe.generate_hash()[:10]
        member = self._member_with_subscription(token)

        status = {
            "id": f"sub_{token}",
            "customer_id": f"cst_{token}",
            "status": "active",
            "next_payment_date": "2026-01-15",
        }
        result = sync._update_local_subscription_records(status)

        self.assertEqual(result["updated_records"], 1)
        self.assertEqual(result["errors"], [])
        member.reload()
        self.assertEqual(member.subscription_status, "active")
        self.assertEqual(str(member.next_payment_date), "2026-01-15")

    def test_no_matching_member_updates_nothing(self):
        token = frappe.generate_hash()[:10]
        status = {
            "id": f"sub_missing_{token}",
            "customer_id": f"cst_missing_{token}",
            "status": "active",
        }
        result = sync._update_local_subscription_records(status)
        self.assertEqual(result["updated_records"], 0)
        self.assertEqual(result["errors"], [])

    def test_general_error_captured(self):
        # Missing required keys (no "id"/"customer_id") trips the outer except
        result = sync._update_local_subscription_records({})
        self.assertEqual(result["updated_records"], 0)
        self.assertTrue(result["errors"], "a KeyError should be captured into errors")


class TestUpdateMemberSubscriptionStatus(EnhancedTestCase):
    """_update_member_subscription_status — status transition + persistence."""

    def test_status_change_persists(self):
        token = frappe.generate_hash()[:10]
        member = self.create_test_member(
            first_name="Sync", last_name=f"Member{token}", email=f"sync.m.{token}@example.com"
        )
        frappe.db.set_value("Member", member.name, "subscription_status", "active")
        member.reload()

        status = {"id": f"sub_{token}", "status": "canceled", "next_payment_date": None}
        result = sync._update_member_subscription_status(member, status)

        self.assertTrue(result["updated"])
        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["previous_status"], "active")
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")

    def test_malformed_status_returns_error_dict(self):
        token = frappe.generate_hash()[:10]
        member = self.create_test_member(
            first_name="Sync", last_name=f"Bad{token}", email=f"sync.bad.{token}@example.com"
        )
        # Missing the required "status" key -> KeyError inside the helper ->
        # it must swallow it into {"updated": False, "error": ...} (never raise).
        result = sync._update_member_subscription_status(member, {"id": f"sub_{token}"})
        self.assertFalse(result["updated"])
        self.assertIn("error", result)


class TestHandleSubscriptionStatusChange(EnhancedTestCase):
    """_handle_subscription_status_change — branch coverage, never raises."""

    def test_cancel_from_active_logs_without_email(self):
        token = frappe.generate_hash()[:10]
        member = self.create_test_member(
            first_name="Sync", last_name=f"Cancel{token}", email=f"sync.c.{token}@example.com"
        )
        member.email = None  # no email -> notification branch skipped
        # Must not raise even though it logs an Error Log for audit
        sync._handle_subscription_status_change(member, "active", "canceled", {"id": f"sub_{token}"})

    def test_reactivation_branch(self):
        token = frappe.generate_hash()[:10]
        member = self.create_test_member(
            first_name="Sync", last_name=f"React{token}", email=f"sync.r.{token}@example.com"
        )
        # canceled -> active hits the reactivation branch (info log, no email)
        sync._handle_subscription_status_change(member, "canceled", "active", {"id": f"sub_{token}"})


class TestSyncMemberSubscriptionsGuards(EnhancedTestCase):
    """sync_member_subscriptions — guard branches (no Mollie call required)."""

    def test_member_without_customer_id_is_skipped(self):
        token = frappe.generate_hash()[:10]
        member = self.create_test_member(
            first_name="Sync", last_name=f"NoCust{token}", email=f"sync.nc.{token}@example.com"
        )
        with self.set_user("Administrator"):
            result = sync.sync_member_subscriptions(member.name)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no Mollie customer ID", result["message"])

    def test_missing_member_id_raises(self):
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync.sync_member_subscriptions("")


class TestSyncPaymentStatus(EnhancedTestCase):
    """sync_payment_status — validation + boundary-double happy path."""

    def test_missing_payment_id_raises(self):
        with self.set_user("Administrator"):
            with self.assertRaises(MollieIntegrationError):
                sync.sync_payment_status("")

    def test_paid_payment_triggers_completion(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_sync_{token}"
        fake = _FakePaymentService(status={"is_paid": True, "status": "paid"})
        with self.set_user("Administrator"):
            with patch(_PAYMENT_SERVICE, return_value=fake):
                result = sync.sync_payment_status(pid)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_id"], pid)
        # is_paid -> completion was processed
        self.assertEqual(fake.completed_calls, [pid])
        self.assertEqual(result["processing_result"], {"processed": True})

    def test_unpaid_payment_skips_completion(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_open_{token}"
        fake = _FakePaymentService(status={"is_paid": False, "status": "open"})
        with self.set_user("Administrator"):
            with patch(_PAYMENT_SERVICE, return_value=fake):
                result = sync.sync_payment_status(pid)
        self.assertEqual(result["status"], "success")
        self.assertEqual(fake.completed_calls, [], "unpaid payment must not be completed")
        self.assertIsNone(result["processing_result"])


class TestBulkSyncRecentPayments(EnhancedTestCase):
    """bulk_sync_recent_payments — hour cap + security event + processing."""

    def test_hours_capped_at_168_and_security_event_logged(self):
        # Regression: the endpoint did `from frappe.utils import add_hours`, but
        # add_hours does not exist in frappe.utils, so EVERY call raised
        # ImportError -> MollieIntegrationError. Fixed to use add_to_date(hours=).
        with self.set_user("Administrator"):
            fake = _FakePaymentService(status={"is_paid": False, "status": "open"})
            with patch(_PAYMENT_SERVICE, return_value=fake):
                with patch(
                    "verenigingen.verenigingen_payments.mollie.api.sync.log_mollie_security_event"
                ) as sec:
                    result = sync.bulk_sync_recent_payments(hours=500)
            # The requested window is clamped to the 168h ceiling
            self.assertEqual(result["timeframe_hours"], 168)
            self.assertEqual(result["status"], "completed")
            # A security event documenting the clamp was emitted
            sec.assert_called_once()
            self.assertEqual(sec.call_args[0][0], "bulk_sync_limit_exceeded")


class TestSyncRoleGate(EnhancedTestCase):
    """The financial sync endpoints reject users without an authorised role."""

    def _persist_plain_user(self, token):
        """Create a roleless User (factory/setup pattern, permission-bypass allowed)."""
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"plain.sync.{token}@example.com",
                "first_name": "Plain",
                "send_welcome_email": 0,
            }
        )
        user.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("User", user.name, force=True, ignore_permissions=True))
        return user

    def test_plain_member_is_denied(self):
        token = frappe.generate_hash()[:8]
        user = self._persist_plain_user(token)
        with self.set_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                sync.sync_payment_status("tr_anything")
