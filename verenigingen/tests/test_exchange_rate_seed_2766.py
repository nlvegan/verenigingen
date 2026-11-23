"""#2766: stored exchange rates keep tests off erpnext's live-fetch path.

`erpnext.setup.utils.get_exchange_rate` consults stored Currency Exchange rows first.
Without one it reaches the external provider, which it refuses ("Only system users can
fetch exchange rates from an external provider") unless `is_system_user()` is true.
Merge-queue shards hit that for an INR price list on a EUR company, in three unrelated
PRs. These tests simulate the CI condition (the check forced False, the provider's
cache key empty) instead of waiting for it.
"""

import io
from contextlib import redirect_stderr
from datetime import timedelta
from unittest import mock

import frappe
from erpnext.setup.utils import get_exchange_rate
from frappe.utils import add_days, getdate

from verenigingen.tests.fixtures import enhanced_test_factory as factory
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

PAIRS = (("INR", "EUR"), ("EUR", "INR"), ("USD", "EUR"), ("EUR", "USD"))


def _live_fetch_refused():
    """Make the stored-row miss behave as it does for a non-System session user."""
    for day in (getdate(), getdate() + timedelta(days=1)):
        for from_currency, to_currency in PAIRS:
            frappe.cache().delete_value(f"currency_exchange_rate_{day}:{from_currency}:{to_currency}")
    return mock.patch("erpnext.setup.utils.is_system_user", return_value=False)


class TestExchangeRateSeed2766(EnhancedTestCase):
    def _delete_seeded_rows(self):
        for from_currency, to_currency in PAIRS:
            for name in frappe.get_all(
                "Currency Exchange",
                filters={"from_currency": from_currency, "to_currency": to_currency},
                pluck="name",
            ):
                frappe.delete_doc("Currency Exchange", name, force=True, ignore_permissions=True)

    def _seed_from_scratch(self):
        """Drop whatever the site already holds (before_tests commits the seed, so the
        rows usually pre-exist), then build them with the helper under test."""
        self._delete_seeded_rows()
        factory.ensure_test_exchange_rates()

    def _set_allow_stale(self, value):
        original = frappe.db.get_single_value("Accounts Settings", "allow_stale")
        frappe.db.set_single_value("Accounts Settings", "allow_stale", value)
        frappe.db.set_single_value("Accounts Settings", "stale_days", 1)
        self.addCleanup(frappe.clear_document_cache, "Accounts Settings", "Accounts Settings")
        self.addCleanup(frappe.db.set_single_value, "Accounts Settings", "allow_stale", original)
        frappe.clear_document_cache("Accounts Settings", "Accounts Settings")

    def test_every_seeded_pair_resolves_without_a_live_fetch(self):
        today = getdate()
        self._seed_from_scratch()
        with _live_fetch_refused():
            for from_currency, to_currency in PAIRS:
                for args in (None, "for_buying", "for_selling"):
                    for posting in (today, add_days(today, -400), add_days(today, 1)):
                        rate = get_exchange_rate(from_currency, to_currency, posting, args)
                        self.assertGreater(rate, 0, (from_currency, to_currency, args, posting))

    def test_with_stale_rates_disallowed_the_dated_row_still_hits(self):
        """allow_stale off: only a row inside `stale_days` of the posting date counts."""
        self._set_allow_stale(0)
        self._seed_from_scratch()
        with _live_fetch_refused():
            for from_currency, to_currency in PAIRS:
                self.assertGreater(get_exchange_rate(from_currency, to_currency, getdate()), 0)

    def test_control_without_the_rows_the_live_fetch_is_refused(self):
        """The simulation is real: with the rows gone the same call raises."""
        self._delete_seeded_rows()
        with _live_fetch_refused():
            with self.assertRaises(frappe.PermissionError) as ctx:
                get_exchange_rate("INR", "EUR", getdate())
        self.assertIn("Only system users", str(ctx.exception))

    def test_a_run_crossing_midnight_reseeds_for_the_new_day(self):
        """allow_stale off, and the date has moved on: yesterday's row is stale."""
        self._set_allow_stale(0)
        self._delete_seeded_rows()
        tomorrow = getdate() + timedelta(days=1)
        with mock.patch.object(factory, "getdate", return_value=tomorrow):
            factory.ensure_test_exchange_rates()
        with _live_fetch_refused():
            self.assertGreater(get_exchange_rate("INR", "EUR", tomorrow), 0)

    def test_seeding_is_idempotent(self):
        before = frappe.db.count("Currency Exchange")
        factory.ensure_test_exchange_rates()
        factory.ensure_test_exchange_rates()
        self.assertEqual(before, frappe.db.count("Currency Exchange"))

    def test_the_drain_does_not_claim_the_seeded_rows(self):
        self._delete_seeded_rows()
        captured_before = len(self._captured_inserts)
        factory.ensure_test_exchange_rates()
        self.assertGreater(frappe.db.count("Currency Exchange", {"from_currency": "INR"}), 0)
        claimed = [k for k in self._captured_inserts[captured_before:] if k[0] == "Currency Exchange"]
        self.assertEqual([], claimed, "the captured-insert drain would delete the shared rates")

    def test_the_seed_helper_is_declared_shared(self):
        self.assertTrue(hasattr(factory.ensure_test_exchange_rates, "__wrapped__"))


class TestSessionUserTripwire2766(EnhancedTestCase):
    """The tripwire output is captured, never emitted into the run's own log."""

    def _fire(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            fired = factory.log_session_user_tripwire_2766("probe.test_id")
        return fired, buffer.getvalue()

    def test_silent_for_a_normal_administrator(self):
        fired, output = self._fire()
        self.assertFalse(fired)
        self.assertNotIn("TRIPWIRE-2766", output)

    def test_fires_once_with_diagnostics_when_administrator_is_not_a_system_user(self):
        with mock.patch("erpnext.setup.utils.is_system_user", return_value=False):
            fired, output = self._fire()
        self.assertTrue(fired)
        self.assertEqual(1, output.count("TRIPWIRE-2766"), output)
        self.assertIn("probe.test_id", output)
        self.assertIn("cached_user_type='System User'", output)
        self.assertIn("db_user_type='System User'", output)
        self.assertIn("erpnext_is_system_user_is_frappe_permissions=False", output)

    def test_silent_for_another_user_even_when_not_a_system_user(self):
        frappe.set_user("Guest")
        self.addCleanup(frappe.set_user, "Administrator")
        with mock.patch("erpnext.setup.utils.is_system_user", return_value=False):
            fired, output = self._fire()
        self.assertFalse(fired)
        self.assertNotIn("TRIPWIRE-2766", output)
