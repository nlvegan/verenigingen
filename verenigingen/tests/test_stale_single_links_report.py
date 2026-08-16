"""
The bootstrap report that names a site's stale Single links.

WHY THIS EXISTS
---------------
A Single's values live in `tabSingles` and survive every rollback, and the test
harness configures Singles with `frappe.db.set_value(...)`, which skips the
document validation chain. So a dangling Link value persists indefinitely and is
never validated -- until some unrelated code path does a real `.save()`, at which
point Frappe validates every link field at once and throws naming all of them.

`test_site_5` failed 19/19 in setUp that way, identically on develop, and it was
read as a code failure. `report_stale_single_links()` exists to make the site
name its own problem at bootstrap instead.

WHAT IS ASSERTED
----------------
That the detector distinguishes a dangling link from a healthy one. Both halves
matter: a detector that flags everything is as useless as one that flags nothing,
and the second half is the control -- without it, `find_stale_single_links`
could simply return every link field and still pass.
"""

import frappe

from verenigingen.tests.setup import find_stale_single_links, report_stale_single_links
from verenigingen.tests.utils.base import VereningingenTestCase

SETTINGS = "Verenigingen Settings"
FIELD = "donations_gl_account"


class TestStaleSingleLinksReport(VereningingenTestCase):
    """The detector must separate a dangling link from a valid one."""

    def setUp(self):
        super().setUp()
        # tabSingles is not transactional -- it survives the harness rollback, so
        # the original value must be restored explicitly. addCleanup rather than
        # tearDown: cleanups run after the base teardown drain, which has been
        # observed to discard restores made in tearDown.
        original = frappe.db.get_single_value(SETTINGS, FIELD)
        self.addCleanup(self._restore, original)

    @staticmethod
    def _restore(original):
        frappe.db.set_value(SETTINGS, None, FIELD, original, update_modified=False)
        frappe.db.commit()

    def _set(self, value):
        frappe.db.set_value(SETTINGS, None, FIELD, value, update_modified=False)
        frappe.db.commit()

    def _findings_for_field(self):
        return [p for p in find_stale_single_links() if p["doctype"] == SETTINGS and p["fieldname"] == FIELD]

    def test_a_dangling_link_is_reported(self):
        """A value naming a non-existent Account is found, with its target named."""
        missing = "NO SUCH ACCOUNT - ZZZ"
        self.assertFalse(
            frappe.db.exists("Account", missing),
            "fixture is broken: the 'missing' account actually exists",
        )
        self._set(missing)

        findings = self._findings_for_field()
        self.assertEqual(len(findings), 1, msg=f"expected exactly one finding, got {findings}")
        self.assertEqual(findings[0]["value"], missing)
        self.assertEqual(findings[0]["target_doctype"], "Account")

    def test_a_valid_link_is_not_reported(self):
        """CONTROL. Without this, a detector that flags every link field passes."""
        real_account = frappe.db.get_value("Account", {"is_group": 0}, "name")
        self.assertIsNotNone(real_account, "fixture is broken: no Account exists on this site")
        self._set(real_account)

        self.assertEqual(
            self._findings_for_field(),
            [],
            "a link pointing at an existing Account was reported as stale",
        )

    def test_an_empty_link_is_not_reported(self):
        """An unset field is not a dangling link; the healthy sites leave these empty."""
        self._set("")
        self.assertEqual(self._findings_for_field(), [])

    def test_the_report_names_the_field_and_does_not_raise(self):
        """It must print and return, never throw.

        Raising would fail the whole suite at bootstrap. Two of five local test
        sites already carry a dangling link in an app Single, and CI's state is
        unmeasured, so a throwing guard is not safe. This pins the non-raising
        contract so it is not "tightened" into a raise without that evidence.
        """
        missing = "NO SUCH ACCOUNT - ZZZ"
        self._set(missing)

        problems = report_stale_single_links()  # must not raise

        self.assertTrue(
            any(p["doctype"] == SETTINGS and p["value"] == missing for p in problems),
            msg=f"the report did not name the stale field: {problems}",
        )
