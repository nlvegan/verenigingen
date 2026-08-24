"""The control for ``eur_company_decoy``: prove the decoy actually wins the buggy query.

Every pin in this change asserts "the resolved company is the owned one, even with a newer
EUR company present". If the decoy did not in fact win
``get_value("Company", {"default_currency": "EUR"}, "name")``, all of those pins would pass
vacuously and would keep passing after the fix was reverted. A check without a control
proves nothing, so this file is the control.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.eur_company_decoy import newest_eur_company, scan_by_currency
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestEURCompanyDecoy(EnhancedTestCase):
    def test_the_decoy_wins_the_currency_scan(self):
        """Without this, every pin built on the decoy could pass for the wrong reason."""
        before = scan_by_currency()
        with newest_eur_company() as decoy:
            self.assertEqual(
                scan_by_currency(),
                decoy,
                "the decoy is not the newest EUR company, so it does not discriminate",
            )
        self.assertEqual(scan_by_currency(), before, "the decoy outlived its context manager")

    def test_the_owned_helper_ignores_the_decoy(self):
        """``get_eur_test_company`` resolves by NAME, so a newer EUR company cannot win.

        The build is hoisted OUT of the window on purpose. On a fresh CI site
        ``_company_is_usable`` is False, so this call takes ``_create_eur_test_company``
        -> ``_build_and_verify``, which ends in ``frappe.db.commit()``. Committing inside
        the window persists the decoy's raw INSERT and leaves the ``finally`` DELETE
        uncommitted, which the harness teardown then rolls back -- see the decoy module
        docstring. The window only has to contain the *resolution* being pinned.
        """
        owned = get_eur_test_company()
        with newest_eur_company():
            self.assertEqual(get_eur_test_company(), owned)

    def test_the_decoy_leaves_no_row_behind(self):
        """A commit INSIDE the window is the only shape where leaking is possible.

        An empty ``with`` body cannot leak -- the INSERT is uncommitted, so the harness
        rollback removes it whether or not the context manager does anything. That
        version of this test read as the leak guard and guarded nothing: it passed
        unchanged while ``get_eur_test_company()`` inside the window was resurrecting the
        row on every fresh site. So commit inside the window, then roll back the way
        ``EnhancedTestCase.tearDown`` does, and require the row to be gone anyway.
        """
        with newest_eur_company() as decoy:
            frappe.db.commit()
        frappe.db.rollback()
        self.assertFalse(
            frappe.db.sql("SELECT 1 FROM `tabCompany` WHERE `name` = %s", decoy),
            "decoy row survived a commit inside the window plus a rollback -- the "
            "uncommitted DELETE was undone and the drain will re-commit the row",
        )
