"""Non-resumable-class DB errors, built once for every suite that injects them.

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

``connection_lost()`` (#731) is a THIRD non-resumable condition but deliberately NOT a
member of the ``NON_RESUMABLE_DB_ERRORS`` tuple: a lost connection (client-side MySQL
codes 2006/2013) surfaces as a plain ``OperationalError`` on both mysqlclient/MySQLdb and
pymysql -- neither driver wraps it into ``QueryDeadlockError``/``QueryTimeoutError`` the
way it does 1213/1205 -- so it is not isinstance-matchable the way the other two are.
Handlers that also need to recognize it match on the error CODE instead (see
``eboekhouden_rest_full_migration._is_connection_lost``); this factory exists so tests for
those handlers do not each hand-roll the same ``OperationalError(2006, ...)`` (three did,
independently, before this was added here -- exactly the per-suite copy this module exists
to end).
"""

import frappe


def deadlock():
    """MariaDB 1213. The server picks a victim and discards the ENTIRE transaction."""
    return frappe.QueryDeadlockError("Deadlock found when trying to get lock; try restarting transaction")


def lock_wait_timeout():
    """MariaDB 1205. Only the failed statement is rolled back, so the unit of work is
    half-applied -- which is not a state any caller here is written to reason about."""
    return frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")


def connection_lost(code=2006):
    """MySQL client-side CR_SERVER_GONE_ERROR (2006, default) / CR_SERVER_LOST
    (2013, pass ``code=2013``). Verified (#731) against this bench's driver
    (mysqlclient/MySQLdb) and confirmed identical on pymysql: neither wraps this
    into QueryDeadlockError/QueryTimeoutError, so it is NOT a member of
    NON_RESUMABLE_DB_ERRORS -- use this to exercise handlers that match on error
    CODE instead of exception class.

    Built via ``frappe.db.OperationalError`` rather than a hardcoded driver
    import, so it tracks whichever backend ``_is_connection_lost``'s own
    ``isinstance(exc, frappe.db.OperationalError)`` check resolves to
    (``frappe/database/__init__.py``'s ``use_mysqlclient`` setting) instead of
    only ever proving the mysqlclient path.
    """
    message = "MySQL server has gone away" if code == 2006 else "Lost connection to MySQL server during query"
    return frappe.db.OperationalError(code, message)
