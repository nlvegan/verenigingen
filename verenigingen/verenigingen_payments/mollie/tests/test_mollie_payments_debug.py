"""
Integration coverage for the Mollie Payments Debug admin page —
the branches the sibling ``test_mollie_payments_debug_unit.py`` does NOT reach.

verenigingen/templates/pages/mollie_payments_debug.py is the admin/debug console.
The ``_unit.py`` file already owns the pure delegators it has so far covered:
  - has_mollie_debug_access / has_customer_deletion_access role gates
  - get_context
  - list_subscriptions (limit clamp + active_only coercion + required-customer)
  - batch_process_dues_payments (JSON/HTML parsing, validation, batch cap, rate limit)
  - process_discovered_payments (JSON/non-list/cap/dry_run coercion — but NOT its
    rate-limit cooldown, asserted here)
  - bulk_process_member_payments (small-batch sync vs large-batch background split)

This file (integration, no ``_unit`` suffix) covers the REMAINING uncovered ~58%:
  - the six balance-transaction endpoints (get_balance_info,
    process_recent_balance_transactions, process_balance_date_range,
    process_balance_historical_data, check_balance_transaction_status,
    search_balance_transactions) plus fetch_recent_for_search /
    get_balance_processing_statistics — input coercion (int/bool/date-range),
    correct delegation args, and the delegate-raises / invalid-int error branches
  - process_discovered_payments rate-limit cooldown branch (dry-run window)
  - check_all_customers_for_new_payments (BulkPaymentChecker delegation, param
    coercion, and its own bulk_payment_discovery_limit rate limit)
  - process_payment_batch_job module-level worker delegation

Boundary patched: the lazily-imported delegate functions in
``balance_transaction_processing`` and the ``BulkPaymentChecker`` /
``MollieDebugService`` wrappers — the page's OWN coercion / date math / role
gating / rate-limiting runs for real. None of these are duplicated from
``_unit.py`` (confirmed by reading it). Rate-limit cache keys are cleared in
setUp/tearDown so cooldowns never leak between tests.
"""

import json
from datetime import datetime
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_payments_debug as mpd
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Module path where the balance-endpoint delegates are imported from. Each page
# endpoint does `from <this module> import <fn>` lazily inside its body, so the
# binding is resolved at call time and patching here intercepts it.
_BAL = "verenigingen.verenigingen_payments.api.balance_transaction_processing"
_CHECKER = "verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.BulkPaymentChecker"
# process_payment_batch_job is now a back-compat shim delegating to
# bulk_payment_admin_service.process_payment_batch_job, which builds its own
# MollieDebugService via a fresh function-level import from the source module
# rather than this page's symbol - so patch it there, not via the page.
_SERVICE = "verenigingen.services.mollie_debug_service.MollieDebugService"

_PID_A = "tr_WDqYK6vllg"
_PID_B = "tr_AbCdEfGhIj"


# ===========================================================================
# Balance-transaction endpoints — coercion + delegation + error branches.
# ===========================================================================
class TestBalanceTransactionEndpoints(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    # --- get_balance_info -------------------------------------------------
    def test_get_balance_info_delegates(self):
        with patch(f"{_BAL}.get_primary_balance_info", return_value={"balance": "100.00"}) as m:
            result = mpd.get_balance_info()
        self.assertTrue(m.called)
        self.assertEqual(result["balance"], "100.00")

    def test_get_balance_info_delegate_failure_captured(self):
        with patch(f"{_BAL}.get_primary_balance_info", side_effect=RuntimeError("boom")):
            result = mpd.get_balance_info()
        self.assertIn("error", result)
        self.assertIn("boom", result["error"])

    # --- process_recent_balance_transactions ------------------------------
    def test_recent_computes_date_range_and_coerces_ints(self):
        # days=7 -> from_date is exactly 7 days before until_date; limit "300" -> 300.
        captured = {}

        def _fake(from_date, until_date, limit):
            captured["from_date"] = from_date
            captured["until_date"] = until_date
            captured["limit"] = limit
            return {"processed": 0}

        with patch(f"{_BAL}.process_balance_transactions", side_effect=_fake):
            mpd.process_recent_balance_transactions(days="7", limit="300")

        self.assertEqual(captured["limit"], 300)
        self.assertIsInstance(captured["limit"], int)
        d_from = datetime.strptime(captured["from_date"], "%Y-%m-%d")
        d_until = datetime.strptime(captured["until_date"], "%Y-%m-%d")
        self.assertEqual((d_until - d_from).days, 7)

    def test_recent_invalid_days_raises_value_error_captured(self):
        # int("abc") raises inside the try -> error dict.
        result = mpd.process_recent_balance_transactions(days="abc")
        self.assertIn("error", result)

    # --- process_balance_date_range ---------------------------------------
    def test_date_range_passes_dates_through_and_coerces_limit(self):
        captured = {}

        def _fake(from_date, until_date, limit):
            captured.update(from_date=from_date, until_date=until_date, limit=limit)
            return {"ok": True}

        with patch(f"{_BAL}.process_balance_transactions", side_effect=_fake):
            mpd.process_balance_date_range(from_date="2025-01-01", until_date="2025-02-01", limit="50")

        self.assertEqual(captured["from_date"], "2025-01-01")
        self.assertEqual(captured["until_date"], "2025-02-01")
        self.assertEqual(captured["limit"], 50)

    # --- process_balance_historical_data ----------------------------------
    def test_historical_coerces_months_and_batch_size(self):
        captured = {}

        def _fake(months_back, batch_size):
            captured.update(months_back=months_back, batch_size=batch_size)
            return {"batches": 1}

        with patch(f"{_BAL}.process_historical_data", side_effect=_fake):
            mpd.process_balance_historical_data(months_back="6", batch_size="125")

        self.assertEqual(captured["months_back"], 6)
        self.assertEqual(captured["batch_size"], 125)
        self.assertIsInstance(captured["months_back"], int)

    # --- check_balance_transaction_status ---------------------------------
    def test_check_status_coerces_include_flag_string_true(self):
        captured = {}

        def _fake(transaction_id, include_mollie_data):
            captured.update(transaction_id=transaction_id, include_mollie_data=include_mollie_data)
            return {"processed": True}

        with patch(f"{_BAL}.check_transaction_status", side_effect=_fake):
            mpd.check_balance_transaction_status(transaction_id="baltr_X", include_mollie_data="yes")

        self.assertEqual(captured["transaction_id"], "baltr_X")
        self.assertIs(captured["include_mollie_data"], True)

    def test_check_status_coerces_include_flag_string_false(self):
        captured = {}

        def _fake(transaction_id, include_mollie_data):
            captured["include_mollie_data"] = include_mollie_data
            return {}

        with patch(f"{_BAL}.check_transaction_status", side_effect=_fake):
            mpd.check_balance_transaction_status(transaction_id="baltr_Y", include_mollie_data="no")

        self.assertIs(captured["include_mollie_data"], False)

    # --- search_balance_transactions --------------------------------------
    def test_search_coerces_limit_and_forwards_term(self):
        captured = {}

        def _fake(search_term, limit):
            captured.update(search_term=search_term, limit=limit)
            return {"results": []}

        with patch(f"{_BAL}.search_transactions_by_description", side_effect=_fake):
            mpd.search_balance_transactions(search_term="dues 2025", limit="25")

        self.assertEqual(captured["search_term"], "dues 2025")
        self.assertEqual(captured["limit"], 25)

    # --- fetch_recent_for_search ------------------------------------------
    def test_fetch_recent_for_search_coerces_limit(self):
        captured = {}

        def _fake(limit):
            captured["limit"] = limit
            return {"transactions": []}

        with patch(f"{_BAL}.fetch_recent_transactions_for_search", side_effect=_fake):
            mpd.fetch_recent_for_search(limit="80")

        self.assertEqual(captured["limit"], 80)

    # --- get_balance_processing_statistics --------------------------------
    def test_statistics_coerces_days(self):
        captured = {}

        def _fake(days):
            captured["days"] = days
            return {"count": 5}

        with patch(f"{_BAL}.get_processing_statistics", side_effect=_fake):
            mpd.get_balance_processing_statistics(days="14")

        self.assertEqual(captured["days"], 14)


# ===========================================================================
# process_discovered_payments — the rate-limit cooldown branch (not asserted
# in _unit.py, which only clears the key and never triggers the cooldown).
# ===========================================================================
class TestProcessDiscoveredPaymentsRateLimit(EnhancedTestCase):
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

    def test_second_dry_run_within_cooldown_is_blocked(self):
        with patch(_CHECKER) as MockChecker:
            checker = MockChecker.return_value
            checker.process_discovered_payments.return_value = {"processed": 0}
            first = mpd.process_discovered_payments(payment_ids=json.dumps([_PID_A]), dry_run="true")
            self.assertEqual(first["processed"], 0)
            # Second call inside the 30s dry-run cooldown must be refused before
            # ever reaching the checker.
            second = mpd.process_discovered_payments(payment_ids=json.dumps([_PID_B]), dry_run="true")
            # Checker was only invoked once (the blocked call never delegated).
            self.assertEqual(checker.process_discovered_payments.call_count, 1)
        self.assertIn("error", second)
        self.assertIn("wait", second["error"].lower())


# ===========================================================================
# check_all_customers_for_new_payments — discovery stage 1.
# Delegation, param coercion, and its OWN rate limit (different cache key).
# ===========================================================================
class TestCheckAllCustomersForNewPayments(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._clear_rate_limit()

    def tearDown(self):
        self._clear_rate_limit()
        frappe.set_user("Administrator")
        super().tearDown()

    def _clear_rate_limit(self):
        frappe.cache().delete(f"bulk_payment_discovery_limit:{frappe.session.user}")

    def test_coerces_params_and_delegates_to_checker(self):
        with patch(_CHECKER) as MockChecker:
            checker = MockChecker.return_value
            checker.check_all_customers_for_new_payments.return_value = {
                "members_checked": 3,
                "total_members": 3,
            }
            # days_back out of [1,365] -> 7; all_history "true" -> True;
            # limit_per_customer out of [1,250] -> 250.
            result = mpd.check_all_customers_for_new_payments(
                days_back="9999", all_history="true", limit_per_customer="9999"
            )
            _, kwargs = checker.check_all_customers_for_new_payments.call_args

        self.assertEqual(kwargs["days_back"], 7)
        self.assertIs(kwargs["all_history"], True)
        self.assertEqual(kwargs["limit_per_customer"], 250)
        self.assertEqual(kwargs["max_members"], 10000)
        self.assertEqual(result["members_checked"], 3)

    def test_valid_days_back_passed_through(self):
        with patch(_CHECKER) as MockChecker:
            checker = MockChecker.return_value
            checker.check_all_customers_for_new_payments.return_value = {}
            mpd.check_all_customers_for_new_payments(days_back="14", all_history="false")
            _, kwargs = checker.check_all_customers_for_new_payments.call_args
        self.assertEqual(kwargs["days_back"], 14)
        self.assertIs(kwargs["all_history"], False)

    def test_rate_limit_blocks_second_discovery(self):
        with patch(_CHECKER) as MockChecker:
            checker = MockChecker.return_value
            checker.check_all_customers_for_new_payments.return_value = {"members_checked": 0}
            mpd.check_all_customers_for_new_payments(days_back=7)
            second = mpd.check_all_customers_for_new_payments(days_back=7)
            # Only the first call reached the checker.
            self.assertEqual(checker.check_all_customers_for_new_payments.call_count, 1)
        self.assertIn("error", second)
        self.assertIn("wait", second["error"].lower())


# ===========================================================================
# process_payment_batch_job — module-level background worker.
# ===========================================================================
class TestProcessPaymentBatchJob(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_delegates_to_service_with_tracking_id_as_job_id(self):
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.process_payment_batch_background.return_value = {"batch_num": 2, "processed": 1}
            result = mpd.process_payment_batch_job(
                batch_num=2,
                payment_ids=[_PID_A],
                docstatus=1,
                payment_modes={_PID_A: {"mode": "bt_only"}},
                tracking_id="abc12345",
            )
            _, kwargs = svc.process_payment_batch_background.call_args

        self.assertEqual(kwargs["batch_num"], 2)
        self.assertEqual(kwargs["payment_ids"], [_PID_A])
        self.assertEqual(kwargs["docstatus"], 1)
        self.assertEqual(kwargs["payment_modes"], {_PID_A: {"mode": "bt_only"}})
        # tracking_id is forwarded as job_id (frappe.enqueue reserves job_id).
        self.assertEqual(kwargs["job_id"], "abc12345")
        self.assertEqual(result["processed"], 1)
