"""The two non-resumable DB errors, built once for every suite that injects them.

`test_termination_non_resumable_errors` (#470) and `test_termination_reporting_boundaries`
(#475) both drive handlers that must treat a 1205/1213 differently from an ordinary
exception, so both need to raise the real classes.

They had a copy each of `_deadlock()`, which the duplicate ratchet reported. Its baseline is
explicit that recording is the worse exit -- the file is "a to-do list, not a permission
slip" -- so this consolidates instead.

These carry the bare MariaDB message, which is NOT what production raises: Frappe wraps the
driver exception (``raise frappe.QueryDeadlockError(e) from e``,
``frappe/database/database.py:278``), so a real one stringifies as
``"(1213, 'Deadlock found when trying to get lock; try restarting transaction')"`` -- errno
included. Anything matching on ``"1213"`` / ``"1205"`` in the message (as
``services/billing/billing_constants.py`` does) therefore sees a real error and NOT one of
these. Use these to exercise handlers that switch on the CLASS, which is every handler
``NON_RESUMABLE_DB_ERRORS`` guards; do not use them to test a string matcher.
"""

import frappe


def deadlock():
    """MariaDB 1213. The server picks a victim and discards the ENTIRE transaction."""
    return frappe.QueryDeadlockError("Deadlock found when trying to get lock; try restarting transaction")


def lock_wait_timeout():
    """MariaDB 1205. Only the failed statement is rolled back, so the unit of work is
    half-applied -- which is not a state any caller here is written to reason about."""
    return frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")
