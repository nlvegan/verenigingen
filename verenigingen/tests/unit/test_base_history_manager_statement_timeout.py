"""A real MariaDB 1969 (statement timeout) is raised, not swallowed, by BaseHistoryManager (#1352).

``test_base_history_manager_row_lock.py`` already proves the equivalent for a real 1205
(lock-wait timeout) by holding the parent row from a SECOND connection. This module stays
on one connection -- the test's own -- and lowers the SESSION ``max_statement_time``
instead, because the whole point of #1352 is that frappe's own dispatch
(``frappe/database/database.py``) never converts a 1969 into a typed exception the way it
does 1213/1205, so a test that injects ``frappe.QueryTimeoutError`` directly would not
exercise the gap at all; only a real 1969 from the driver does.

Measured on test_site_8 (10.11.14-MariaDB) before writing this test, to confirm what
``_with_doc``'s cleanup has to survive: unlike a 1213 deadlock, a 1969 does NOT roll back
the whole transaction -- ``ROLLBACK TO SAVEPOINT`` after one still succeeds, and a plain
``SELECT 1`` on the same connection immediately afterward still works. So the harness's
own per-test rollback in ``tearDown`` is not at risk here the way it would be after a
real 1213.

The SESSION ``max_statement_time`` ceiling is restored in a ``finally`` inside the test
method itself, not via ``addCleanup``: ``VereningingenTestCase``'s own tearDown (rollback,
drain) runs BEFORE addCleanup callbacks, so leaving the ceiling in place until addCleanup
would expose that teardown to the same leaked-session-variable hazard #1353 is about.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.donation_history_manager import DonationHistoryManager


class TestBaseHistoryManagerStatementTimeout(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.create_test_donor()

    def _with_statement_timeout(self, seconds, callback):
        """Run ``callback()`` with SESSION ``max_statement_time`` set to *seconds*,
        restoring the original value in a ``finally`` before returning/raising."""
        original = frappe.db.sql("SELECT @@session.max_statement_time")[0][0]
        frappe.db.sql(f"SET SESSION max_statement_time = {seconds}")
        try:
            return callback()
        finally:
            frappe.db.sql(f"SET SESSION max_statement_time = {int(original)}")

    def test_a_real_statement_timeout_is_raised_not_swallowed(self):
        """The callback protocol runs ``callback(doc)`` inside ``_with_doc``'s own try, so a
        1969 raised there is exactly the case that must not be folded into an ordinary
        ``HistoryOperationResult(success=False)`` -- the eleven call sites in
        ``chapter/managers/member_manager.py`` this method's own comment names discard
        that result entirely.
        """

        def _slow_callback(doc):
            frappe.db.sql("SELECT SLEEP(1)")
            return True  # never reached

        with self.assertRaises(
            Exception,
            msg="a MariaDB 1969 must propagate, not come back as a failed HistoryOperationResult",
        ) as ctx:
            self._with_statement_timeout(
                0.1,
                lambda: DonationHistoryManager._with_doc(self.donor.name, "test op", _slow_callback),
            )

        self.assertEqual(
            ctx.exception.args[0],
            1969,
            f"expected a real MariaDB 1969, got {ctx.exception.args!r} -- this test proves "
            "nothing about the statement-timeout gap unless the exception it caught IS one",
        )

    def test_control_an_ordinary_callback_exception_is_still_a_failed_result(self):
        """CONTROL. Without this, the test above is equally consistent with `_with_doc` now
        re-raising every exception -- which would be a correctness regression of its own,
        since every existing caller is written against a returned HistoryOperationResult
        for ordinary failures."""
        self.expectErrorLog("History Manager Error")

        def _ordinary_failure(doc):
            raise ValueError("not a statement timeout")

        result = self._with_statement_timeout(
            0.1,
            lambda: DonationHistoryManager._with_doc(self.donor.name, "test op", _ordinary_failure),
        )

        self.assertFalse(result.success)
        self.assertIn("not a statement timeout", result.errors[0])
