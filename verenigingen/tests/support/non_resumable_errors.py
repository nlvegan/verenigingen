"""The two non-resumable DB errors, built once for every suite that injects them.

`test_termination_non_resumable_errors` (#470) and `test_termination_reporting_boundaries`
(#475) both drive handlers that must treat a 1205/1213 differently from an ordinary
exception, so both need to raise the real classes.

They had a copy each of `_deadlock()`, which the duplicate ratchet reported. Its baseline is
explicit that recording is the worse exit -- the file is "a to-do list, not a permission
slip" -- so this consolidates instead.

The messages match what MariaDB actually emits, because some handlers downstream still
match on the string rather than the class; a test raising these with a made-up message would
pass while production missed the error.
"""

import frappe


def deadlock():
    """MariaDB 1213. The server picks a victim and discards the ENTIRE transaction."""
    return frappe.QueryDeadlockError("Deadlock found when trying to get lock; try restarting transaction")


def lock_wait_timeout():
    """MariaDB 1205. Only the failed statement is rolled back, so the unit of work is
    half-applied -- which is not a state any caller here is written to reason about."""
    return frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")
