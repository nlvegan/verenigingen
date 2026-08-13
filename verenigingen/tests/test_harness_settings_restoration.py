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


class TestVereningingenTestCaseOwnsTheSettingsCompany(unittest.TestCase):
    """`VereningingenTestCase` must pin the company, not inherit it.

    Its tests read `Verenigingen Settings.company` through production code
    (`sepa_config_manager`, `invoice_generator`, `chapter_finance_service`...)
    but the base class never set it, so they passed only when an
    `EnhancedTestCase` test had run earlier in the same shard and leaked the
    value (#312, #308).

    All test sites already carry that leaked value, so these tests set a
    sentinel first -- otherwise the pin is a no-op and the assertions pass
    against a base class that does nothing.
    """

    def setUp(self):
        self.original = _settings()
        self.addCleanup(self._restore)

    def _restore(self):
        frappe.db.set_value("Verenigingen Settings", None, "company", self.original[0], update_modified=False)
        frappe.db.set_value(
            "Verenigingen Payments Settings",
            None,
            "dues_income_account",
            self.original[1],
            update_modified=False,
        )
        frappe.db.commit()

    def _run_case(self, body):
        from verenigingen.tests.utils.base import VereningingenTestCase

        class _Case(VereningingenTestCase):
            def test_body(inner):
                body()

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_Case).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])

    def _pin_sentinel(self):
        """Point BOTH singles at a company the harness does not own.

        Setting only `company` is not adversarial enough: every test site's
        `dues_income_account` already belongs to the harness company, so a
        helper that pins half the pair looks correct. Measured — that exact
        mutation survived until this method also moved the account.
        """
        sentinel = _a_company_the_harness_will_not_pick()
        frappe.db.set_value("Verenigingen Settings", None, "company", sentinel, update_modified=False)
        foreign_account = frappe.db.get_value(
            "Account", {"company": sentinel, "root_type": "Income", "is_group": 0}, "name"
        )
        if foreign_account:
            frappe.db.set_value(
                "Verenigingen Payments Settings",
                None,
                "dues_income_account",
                foreign_account,
                update_modified=False,
            )
        frappe.db.commit()
        return sentinel

    def test_company_is_pinned_during_the_test(self):
        self._pin_sentinel()
        seen = []

        self._run_case(lambda: seen.append(frappe.db.get_value("Verenigingen Settings", None, "company")))

        self.assertEqual(len(seen), 1)
        self.assertIn(
            seen[0],
            HARNESS_OWNED_COMPANIES,
            "VereningingenTestCase did not pin the settings company; its tests are still "
            "reading whatever ran before them",
        )

    def test_the_previous_value_is_put_back(self):
        sentinel = self._pin_sentinel()

        self._run_case(lambda: None)

        self.assertEqual(
            frappe.db.get_value("Verenigingen Settings", None, "company"),
            sentinel,
            "the pin was not restored, so the harness now leaks the value it was written to stop leaking",
        )

    def test_a_mutation_by_the_test_body_is_also_restored(self):
        """The case the early-return version of this helper got wrong.

        When the site value already equals the harness company there is nothing
        to write -- but a cleanup must still be registered, or a test that
        changes the single itself leaves it changed.
        """
        harness_company = _harness_company_or_skip()
        frappe.db.set_value(
            "Verenigingen Settings", None, "company", harness_company, update_modified=False
        )
        frappe.db.commit()
        other = _a_company_the_harness_will_not_pick()

        def mutate():
            frappe.db.set_value("Verenigingen Settings", None, "company", other, update_modified=False)
            frappe.db.commit()

        self._run_case(mutate)

        self.assertEqual(
            frappe.db.get_value("Verenigingen Settings", None, "company"),
            harness_company,
            "a test body's mutation of the single outlived the class that made it",
        )

    def test_the_income_account_belongs_to_the_pinned_company(self):
        """Pinning half the pair reproduces the error this module quotes.

        `invoice_generator._get_income_account` returns `dues_income_account`
        if the Account merely exists -- it never checks whose company it is.
        """
        self._pin_sentinel()
        seen = {}

        def observe():
            company = frappe.db.get_value("Verenigingen Settings", None, "company")
            account = frappe.db.get_value(
                "Verenigingen Payments Settings", None, "dues_income_account"
            )
            seen["company"] = company
            seen["account_company"] = frappe.db.get_value("Account", account, "company") if account else None

        self._run_case(observe)

        if seen["account_company"] is None:
            self.skipTest("no income account resolvable for the harness company on this site")
        self.assertEqual(
            seen["account_company"],
            seen["company"],
            "dues_income_account belongs to a different company than the pinned one",
        )


def _harness_company_or_skip():
    from verenigingen.tests.support.verenigingen_settings import _harness_company

    company = _harness_company()
    if not company:
        raise unittest.SkipTest("no harness-owned Company on this site")
    return company


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

        self.assertEqual(
            _settings(),
            (sentinel, self.original_income_account),
            "Verenigingen Settings was left pointing at the harness test company. "
            "_ensure_verenigingen_settings() commits BOTH singles, so only the tearDown "
            "restore can undo them -- see #312.",
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

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_ObservingCase).run(result)
        self.assertEqual(result.errors, [])

        self.assertEqual(len(seen), 1)
        self.assertIn(
            seen[0],
            HARNESS_OWNED_COMPANIES,
            "setUp did not repoint Verenigingen Settings at a harness-owned company; "
            f"got {seen[0]!r}, so the restoration test above would pass vacuously",
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
                from frappe.email import sendmail_to_system_managers
                from frappe.email.doctype.email_queue.email_queue import EmailQueue

                frappe.sendmail(recipients=["nobody@example.invalid"], subject="probe", message="x")
                # The patch on this was DELETED, on the argument that it is a
                # one-line wrapper around frappe.sendmail and therefore already
                # covered. That argument is only worth making if it is checked.
                sendmail_to_system_managers("probe-via-wrapper", "x")
                observed["captured"] = list(inner.captured_emails)
                observed["queue_send_patched"] = isinstance(EmailQueue.send, MagicMock)

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_CapturingCase).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])

        self.assertEqual(len(observed["captured"]), 2, "not every send pathway was captured")
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
