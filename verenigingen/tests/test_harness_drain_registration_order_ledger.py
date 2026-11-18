"""The drain registration ORDER in EnhancedTestCase.setUp is pinned by a ledger-bearing voucher (#1522).

`EnhancedTestCase.setUp` registers three cleanups, `_drain_captured_inserts`,
`_drain_tracked_documents`, `_uninstall_insert_capture`, in that order so LIFO runs
`_uninstall_insert_capture` FIRST. `test_harness_drains_survive_setup_failure` cannot
pin that: Member and Note are not submittable, so neither goes through
`_remove_drained_record`'s cancel-then-delete branch, and reversing the registrations
leaves it green (#1522, measured by the review of #1467's fix).

This module drives the setUp-failure path with a SUBMITTED Journal Entry, which
posts GL Entry rows and, on the drain's cancel, writes reversal rows.
"""

import io
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.support.test_accounts import make_submitted_journal_entry


def _ledger_rows_for_voucher(voucher_no):
    return {
        ledger: frappe.db.count(ledger, {"voucher_type": "Journal Entry", "voucher_no": voucher_no})
        for ledger in ("GL Entry", "Payment Ledger Entry")
    }


class _LedgerLeakAcrossSetupFailure(EnhancedTestCase):
    """step_one's setUp posts a Journal Entry AFTER capture is installed, commits it, then raises.

    No `test_*` methods, for the reason given in test_harness_drains_survive_setup_failure.
    """

    leaked_voucher = None
    gl_rows_before_cleanup = None
    capture_active_during_drain = None
    instance = None

    def _drain_captured_inserts(self):
        self._note_capture_state("captured")
        super()._drain_captured_inserts()

    def _drain_tracked_documents(self):
        self._note_capture_state("tracked")
        super()._drain_tracked_documents()

    def _note_capture_state(self, which):
        """Record whether the Document.db_insert monkeypatch is still installed as `which` drain starts.

        `addCleanup(self._drain_...)` in the base setUp binds these overrides (attribute lookup
        happens at registration), so they sit in the real cleanup stack at the real position.
        """
        state = type(self).capture_active_during_drain
        if state is None:
            state = type(self).capture_active_during_drain = {}
        state[which] = getattr(self, "_orig_db_insert", None) is not None

    def setUp(self):
        type(self).capture_active_during_drain = {}
        super().setUp()
        type(self).instance = self
        company = get_eur_test_company()
        abbr = frappe.db.get_value("Company", company, "abbr")
        entry = self._create_committed_posted_entry(company, f"Cash - {abbr}")
        type(self).leaked_voucher = entry.name
        type(self).gl_rows_before_cleanup = _ledger_rows_for_voucher(entry.name)["GL Entry"]
        raise RuntimeError("simulated setUp failure after posting a voucher (#1522)")

    def _create_committed_posted_entry(self, company, cash_account):
        """Post a balanced JE between two seeded non-party accounts and commit it.

        Committed so the drains' own opening rollback cannot erase it: only the cancel-then-delete
        path can remove it. `_create`-prefixed so scan_order_dependence records the commit as
        COMMIT_EXEMPT, the convention test_harness_drains_survive_setup_failure uses.
        """
        other = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 0, "root_type": "Asset", "account_type": ["in", ["", "Bank"]]},
            "name",
            order_by="name asc",
        )
        if not other or other == cash_account:
            other = frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 0, "root_type": "Asset", "name": ["!=", cash_account]},
                "name",
                order_by="name asc",
            )
        entry = make_submitted_journal_entry(company, cash_account, other, 10)
        frappe.db.commit()
        return entry

    def step_one_posts_a_voucher_then_setup_fails(self):
        self.fail("setUp should have raised before this test body ever runs")


class DrainRegistrationOrderLedgerTest(unittest.TestCase):
    def test_a_posted_voucher_leaves_no_ledger_rows_when_setup_fails(self):
        suite = unittest.TestSuite()
        suite.addTest(_LedgerLeakAcrossSetupFailure("step_one_posts_a_voucher_then_setup_fails"))

        result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)

        self.assertEqual(1, len(result.errors), f"expected only the injected setUp failure: {result.errors}")
        voucher = _LedgerLeakAcrossSetupFailure.leaked_voucher
        self.assertIsNotNone(voucher, "the reproduction must post a voucher before setUp raises")
        self.assertGreater(
            _LedgerLeakAcrossSetupFailure.gl_rows_before_cleanup,
            0,
            "control: the voucher must have posted GL rows, or the assertion below proves nothing",
        )
        self.assertFalse(frappe.db.exists("Journal Entry", voucher), f"Journal Entry {voucher} survived")
        self.assertEqual(
            {"GL Entry": 0, "Payment Ledger Entry": 0},
            _ledger_rows_for_voucher(voucher),
            "ledger rows stranded for the drained voucher (#1522)",
        )

    def test_capture_is_uninstalled_before_either_drain_runs(self):
        """Pins the registration order itself (#1522).

        The stranding the order guards against is NOT observable as leftover ledger rows:
        `_remove_drained_record` purges by voucher_no after the delete, so the reversal rows are
        swept whichever order the cleanups run in (measured: the test above stays green with the
        three registrations reversed). What the wrong order does leave is the capture hook live
        while the drains cancel the voucher, which is the mechanism #1522 describes. That is what is
        asserted, from the cleanup stack as it really ran. (Measured: the reversal rows are not
        observable afterwards in `_captured_inserts` either, so no list-based assertion is made.)
        """
        suite = unittest.TestSuite()
        suite.addTest(_LedgerLeakAcrossSetupFailure("step_one_posts_a_voucher_then_setup_fails"))
        unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)

        self.assertEqual(
            {"captured": False, "tracked": False},
            _LedgerLeakAcrossSetupFailure.capture_active_during_drain,
            "a drain started while Document.db_insert was still patched: _uninstall_insert_capture "
            "must be the FIRST cleanup to run (registered LAST)",
        )
