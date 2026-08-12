"""`EnhancedTestCase` must put `Verenigingen Settings` back the way it found it.

`_ensure_verenigingen_settings()` repoints `Verenigingen Settings.company` and
`Verenigingen Payments Settings.dues_income_account` at the harness's test
company **and commits**, which is why a restore step exists at all — the
per-method `frappe.db.rollback()` in `tearDown` cannot undo a committed write.

The restore was unreachable for as long as it has existed: `tearDown` called it
on `self.factory`, but it is defined on `EnhancedTestCase`. That raised
`AttributeError` into a handler that logged through a `frappe.logger()` sitting
at level ERROR, so nothing was written anywhere and the two singles simply
stayed pointed at the test company for the rest of the process and on the site
afterwards (#312, found via #311).

These tests drive a real `EnhancedTestCase` through `unittest` rather than
calling the restore directly, because the defect was in *how tearDown reached
it*, not in the method. A test that called `case._restore_verenigingen_settings()`
would have passed against the broken code.

The sentinel has to be a company the harness will not itself select. On
`test_site_2` the site default already **is** `_Test Company`, so a sentinel
picked carelessly makes the whole assertion a no-op that passes either way —
which is exactly what the first draft of this file did.
"""

import unittest
from unittest.mock import MagicMock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import (
    HARNESS_OWNED_COMPANIES,
    EnhancedTestCase,
)

SNAPSHOT_ATTR = "_original_verenigingen_settings"


def _run_one_harness_test():
    """Run a minimal real `EnhancedTestCase`; setUp/tearDown are the subject.

    The case class is defined here rather than at module level so the test
    loader does not collect it as a test of its own.
    """

    class _TrivialCase(EnhancedTestCase):
        def test_nothing(self):
            pass

    suite = unittest.TestLoader().loadTestsFromTestCase(_TrivialCase)
    result = unittest.TestResult()
    suite.run(result)
    return result


def _settings():
    return (
        frappe.db.get_value("Verenigingen Settings", None, "company"),
        frappe.db.get_value("Verenigingen Payments Settings", None, "dues_income_account"),
    )


def _a_company_the_harness_will_not_pick():
    """Any Company outside `HARNESS_OWNED_COMPANIES` and the pinned test company.

    `_get_test_company()` returns `frappe.local.test_company_name` if pinned,
    else the first existing name in `HARNESS_OWNED_COMPANIES`. Excluding both is
    what makes a restore distinguishable from a no-op.
    """
    excluded = set(HARNESS_OWNED_COMPANIES)
    pinned = getattr(frappe.local, "test_company_name", None)
    if pinned:
        excluded.add(pinned)

    for name in frappe.get_all("Company", pluck="name"):
        if name not in excluded:
            return name

    raise unittest.SkipTest("needs a Company the harness does not own to tell a restore from a no-op")


class TestHarnessRestoresVerenigingenSettings(unittest.TestCase):
    def setUp(self):
        self.original_company, self.original_income_account = _settings()
        self.addCleanup(self._restore_site_state)
        # The snapshot is taken once and keyed on frappe.local, which outlives a
        # single test method. Clear it so this test controls the precondition
        # rather than inheriting whatever ran before it in the same process.
        self._forget_snapshot()

    def _forget_snapshot(self):
        if hasattr(frappe.local, SNAPSHOT_ATTR):
            delattr(frappe.local, SNAPSHOT_ATTR)

    def _restore_site_state(self):
        frappe.db.set_value(
            "Verenigingen Settings", None, "company", self.original_company, update_modified=False
        )
        frappe.db.set_value(
            "Verenigingen Payments Settings",
            None,
            "dues_income_account",
            self.original_income_account,
            update_modified=False,
        )
        frappe.db.commit()
        self._forget_snapshot()

    def test_settings_survive_a_harness_test(self):
        """The committed repointing is undone by the time tearDown returns."""
        sentinel = _a_company_the_harness_will_not_pick()
        frappe.db.set_value("Verenigingen Settings", None, "company", sentinel, update_modified=False)
        frappe.db.commit()

        result = _run_one_harness_test()
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])

        company_after, _ = _settings()
        self.assertEqual(
            company_after,
            sentinel,
            "Verenigingen Settings.company was left pointing at the harness test company. "
            "_ensure_verenigingen_settings() commits, so only the tearDown restore can "
            "undo it -- see #312.",
        )

    def test_the_sentinel_is_actually_overwritten_during_the_test(self):
        """Guards the guard: prove the setup step really does mutate the single.

        Without this, a harness that stopped calling `_ensure_verenigingen_settings`
        would leave the sentinel in place and make the test above pass for the
        wrong reason.
        """
        sentinel = _a_company_the_harness_will_not_pick()
        frappe.db.set_value("Verenigingen Settings", None, "company", sentinel, update_modified=False)
        frappe.db.commit()

        seen = []

        class _ObservingCase(EnhancedTestCase):
            def test_observe(self):
                seen.append(frappe.db.get_value("Verenigingen Settings", None, "company"))

        suite = unittest.TestLoader().loadTestsFromTestCase(_ObservingCase)
        suite.run(unittest.TestResult())

        self.assertEqual(len(seen), 1)
        self.assertNotEqual(
            seen[0], sentinel, "setUp did not repoint Verenigingen Settings; nothing to restore"
        )

    def test_email_capture_is_actually_installed(self):
        """Three of five email patches targeted modules that no longer exist.

        They failed to start on every test and the failure was logged through a
        discarded logger, so `captured_emails == []` meant "nothing was
        watching", not "no mail was sent" (#312). Starting a patch is now fatal,
        which makes a dead target impossible to miss; this pins the two live
        pathways so a retarget that silently stops capturing is caught too.
        """
        observed = {}

        class _CapturingCase(EnhancedTestCase):
            def test_capture(inner):
                from frappe.email.doctype.email_queue.email_queue import EmailQueue

                frappe.sendmail(recipients=["nobody@example.invalid"], subject="probe", message="x")
                observed["captured"] = list(inner.captured_emails)
                observed["queue_send_patched"] = isinstance(EmailQueue.send, MagicMock)

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_CapturingCase).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])

        self.assertEqual(len(observed["captured"]), 1, "frappe.sendmail was not captured")
        self.assertEqual(observed["captured"][0]["subject"], "probe")
        self.assertTrue(observed["queue_send_patched"], "EmailQueue.send was left unpatched")

    def test_snapshot_is_cleared_so_the_next_test_re_snapshots(self):
        """A stale snapshot would restore a value two tests old.

        `_ensure_verenigingen_settings` only snapshots `if not hasattr(...)`, so
        leaving the attribute behind means every later restore writes back the
        first value ever seen.
        """
        _run_one_harness_test()

        self.assertFalse(
            hasattr(frappe.local, SNAPSHOT_ATTR),
            f"frappe.local.{SNAPSHOT_ATTR} outlived the test that took it",
        )
