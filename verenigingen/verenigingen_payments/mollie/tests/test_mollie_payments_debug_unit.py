"""
Unit coverage for the Mollie Payments Debug admin page — no Mollie key, no network.
Runs in CI.

verenigingen/templates/pages/mollie_payments_debug.py is the admin/debug console for
Mollie. Beyond thin MollieDebugService delegators it carries real input-handling
logic that this module exercises with the SERVICE BOUNDARY ONLY mocked (or not mocked
at all for the pure paths):

- has_mollie_debug_access / has_customer_deletion_access : the role gates
- get_context                                            : permission throw + assembly
- list_subscriptions                                     : limit clamping + active_only
                                                           string->bool coercion + the
                                                           required-customer guard
- batch_process_dues_payments                            : JSON / HTML-entity parsing,
                                                           type + payment-id validation,
                                                           MAX_BATCH_SIZE enforcement,
                                                           per-user rate-limit cooldown
- process_discovered_payments                            : JSON parsing, id validation,
                                                           batch-size cap, dry_run
                                                           coercion + rate limiting
- bulk_process_member_payments                           : large-batch background-job
                                                           split (queue path) vs the
                                                           synchronous small-batch path

MollieDebugService / BulkPaymentChecker are the wrappers over the Mollie HTTP SDK
(the external boundary), so patching them is permitted; all of the endpoint's own
parsing/validation/branching runs for real. Hence the *_unit.py name. The rate-limit
cache key is cleared in setUp so cooldowns from a prior test never leak.
"""

import html
import json
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_payments_debug as mpd
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_SERVICE = "verenigingen.templates.pages.mollie_payments_debug.MollieDebugService"
# bulk_process_member_payments now delegates to bulk_payment_admin_service, which
# builds its own MollieDebugService via a fresh function-level import from the
# source module rather than the page's symbol - so those two tests patch here
# instead of via _SERVICE (which still covers every other endpoint on this page).
_BULK_SERVICE = "verenigingen.services.mollie_debug_service.MollieDebugService"
_CHECKER = "verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.BulkPaymentChecker"
# Two real-looking Mollie payment IDs (tr_ + 10 alphanumerics) that pass the validator.
_PID_A = "tr_WDqYK6vllg"
_PID_B = "tr_AbCdEfGhIj"


class TestDebugAccessAndContext(EnhancedTestCase):
    """Role gates + get_context."""

    def setUp(self):
        super().setUp()
        # A real privileged (non-superuser) account: debug access is granted to
        # Verenigingen Staff. Testing the real role boundary instead of switching
        # to the Administrator superuser.
        self.privileged_user = self.create_test_user(
            f"mpd-priv-{frappe.generate_hash(length=6)}@test.com", roles=["Verenigingen Staff"]
        )

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_has_debug_access_true_for_privileged_role(self):
        with self.set_user(self.privileged_user.name):
            self.assertTrue(mpd.has_mollie_debug_access())

    def test_has_debug_access_false_for_guest(self):
        frappe.set_user("Guest")
        self.assertFalse(mpd.has_mollie_debug_access())

    def test_customer_deletion_access_requires_verenigingen_admin(self):
        # Customer deletion is a dangerous cascade and is gated on the
        # Verenigingen Administrator role specifically — strictly tighter than the
        # debug-page gate. Assert the full boundary: admin granted, a Staff user
        # who CAN open the debug page is still denied deletion, and Guest denied.
        admin_user = self.create_test_user(
            f"mpd-admin-{frappe.generate_hash(length=6)}@test.com", roles=["Verenigingen Administrator"]
        )
        with self.set_user(admin_user.name):
            self.assertTrue(mpd.has_customer_deletion_access())

        # privileged_user (Verenigingen Staff) passes has_mollie_debug_access but
        # must NOT be allowed to delete customers.
        with self.set_user(self.privileged_user.name):
            self.assertTrue(mpd.has_mollie_debug_access())
            self.assertFalse(mpd.has_customer_deletion_access())

        frappe.set_user("Guest")
        self.assertFalse(mpd.has_customer_deletion_access())

    def test_get_context_throws_for_guest(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            mpd.get_context(frappe._dict())

    def test_get_context_populates_for_privileged_role(self):
        with self.set_user(self.privileged_user.name):
            context = frappe._dict()
            mpd.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertTrue(context.show_sidebar)
        self.assertIn("Mollie", context.title)
        self.assertTrue(hasattr(context, "csrf_token"))
        self.assertIn("mollie_configured", context)


class TestListSubscriptions(EnhancedTestCase):
    """limit clamping, active_only coercion, customer-required guard."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_requires_customer_id(self):
        result = mpd.list_subscriptions(customer_id="")
        self.assertIn("error", result)

    def test_clamps_out_of_range_limit_and_coerces_active_only(self):
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.list_subscriptions.return_value = {"subscriptions": []}
            # limit 9999 is out of [1,250] -> clamped to 50; "false" -> False.
            mpd.list_subscriptions(customer_id="cst_x", limit=9999, active_only="false")
            args, kwargs = svc.list_subscriptions.call_args
            self.assertEqual(args[0], "cst_x")
            self.assertEqual(args[1], 50)
            self.assertIs(args[2], False)

    def test_invalid_limit_falls_back_to_default(self):
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.list_subscriptions.return_value = {"subscriptions": []}
            mpd.list_subscriptions(customer_id="cst_x", limit="abc", active_only="1")
            args, _ = svc.list_subscriptions.call_args
            self.assertEqual(args[1], 50)
            self.assertIs(args[2], True)


class TestBatchProcessDuesPayments(EnhancedTestCase):
    """JSON/HTML parsing, validation, batch-size, rate limit."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._clear_rate_limit()

    def tearDown(self):
        self._clear_rate_limit()
        frappe.set_user("Administrator")
        super().tearDown()

    def _clear_rate_limit(self):
        frappe.cache().delete(f"dues_batch_limit:{frappe.session.user}")

    def test_rejects_non_list_payload(self):
        result = mpd.batch_process_dues_payments(payment_ids=json.dumps({"a": 1}))
        self.assertIn("error", result)

    def test_rejects_invalid_payment_id_format(self):
        result = mpd.batch_process_dues_payments(payment_ids=json.dumps(["not-a-valid-id"]))
        self.assertIn("error", result)

    def test_rejects_invalid_json(self):
        result = mpd.batch_process_dues_payments(payment_ids="{not json")
        self.assertIn("error", result)

    def test_enforces_max_batch_size(self):
        too_many = [_PID_A] * 51  # MAX_BATCH_SIZE is 50
        result = mpd.batch_process_dues_payments(payment_ids=json.dumps(too_many))
        self.assertIn("error", result)
        self.assertIn("50", result["error"])

    def test_html_escaped_json_is_unescaped_and_processed(self):
        # Simulate form data where the JSON was HTML-escaped.
        escaped = html.escape(json.dumps([_PID_A, _PID_B]))
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.batch_process_dues_payments.return_value = {"processed": 2}
            result = mpd.batch_process_dues_payments(payment_ids=escaped)
            args, _ = svc.batch_process_dues_payments.call_args
            self.assertEqual(args[0], [_PID_A, _PID_B])
        self.assertEqual(result["processed"], 2)

    def test_rate_limit_blocks_second_call(self):
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.batch_process_dues_payments.return_value = {"processed": 1}
            first = mpd.batch_process_dues_payments(payment_ids=json.dumps([_PID_A]))
            self.assertEqual(first["processed"], 1)
            # Second call within the cooldown window must be refused.
            second = mpd.batch_process_dues_payments(payment_ids=json.dumps([_PID_B]))
        self.assertIn("error", second)
        self.assertIn("wait", second["error"].lower())


class TestProcessDiscoveredPayments(EnhancedTestCase):
    """Validation + dry_run coercion + rate limit for the bulk-checker stage 2."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._clear_rate_limit()

    def tearDown(self):
        self._clear_rate_limit()
        frappe.set_user("Administrator")
        super().tearDown()

    def _clear_rate_limit(self):
        frappe.cache().delete(f"bulk_payment_process_limit:{frappe.session.user}")

    def test_rejects_invalid_json(self):
        result = mpd.process_discovered_payments(payment_ids="{nope")
        self.assertIn("error", result)

    def test_rejects_non_list(self):
        result = mpd.process_discovered_payments(payment_ids=json.dumps("tr_x"))
        self.assertIn("error", result)

    def test_enforces_batch_cap(self):
        too_many = [_PID_A] * 101  # MAX_BATCH_SIZE is 100 here
        result = mpd.process_discovered_payments(payment_ids=json.dumps(too_many))
        self.assertIn("error", result)
        self.assertIn("100", result["error"])

    def test_dry_run_string_coerced_and_passed_through(self):
        with patch(_CHECKER) as MockChecker:
            checker = MockChecker.return_value
            checker.process_discovered_payments.return_value = {"processed": 0}
            mpd.process_discovered_payments(payment_ids=json.dumps([_PID_A]), dry_run="true")
            _, kwargs = checker.process_discovered_payments.call_args
            self.assertIs(kwargs["dry_run"], True)
            self.assertEqual(kwargs["payment_ids"], [_PID_A])


class TestBulkProcessMemberPayments(EnhancedTestCase):
    """Synchronous small-batch path vs the background-job split for large batches."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_small_batch_runs_synchronously(self):
        with patch(_BULK_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.bulk_process_member_payments.return_value = {"processed": 2}
            result = mpd.bulk_process_member_payments(payment_ids=json.dumps([_PID_A, _PID_B]), docstatus=0)
            self.assertTrue(svc.bulk_process_member_payments.called)
        self.assertEqual(result["processed"], 2)

    def test_large_batch_queues_background_jobs(self):
        # 101 payments > MAX_BATCH_SIZE (100) -> split into background jobs.
        ids = [_PID_A] * 101
        with patch(
            "verenigingen.templates.pages.mollie_payments_debug.frappe.enqueue",
            return_value="job-xyz",
        ) as mock_enqueue:
            result = mpd.bulk_process_member_payments(payment_ids=json.dumps(ids), docstatus=1)
        self.assertTrue(result["queued"])
        self.assertEqual(result["total_payments"], 101)
        self.assertEqual(result["num_batches"], 2)
        self.assertEqual(mock_enqueue.call_count, 2)

    def test_invalid_docstatus_falls_back_to_draft(self):
        with patch(_BULK_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.bulk_process_member_payments.return_value = {"processed": 1}
            mpd.bulk_process_member_payments(payment_ids=json.dumps([_PID_A]), docstatus=5)
            args, _ = svc.bulk_process_member_payments.call_args
            # 3rd positional arg is docstatus; invalid 5 -> coerced to 0.
            self.assertEqual(args[1], 0)
