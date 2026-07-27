"""Database errors that must never be logged-and-swallowed.

A handler that catches one of these, writes an Error Log row and carries on is not
degrading gracefully -- it is continuing against state the server has already thrown
away, and the write it performs to record the failure is itself issued on that broken
transaction.

The two members differ in how much they destroy, which is why the name is
"non-resumable" rather than "rolls everything back":

* ``QueryDeadlockError`` (MariaDB 1213) -- the server picks a victim and rolls the
  ENTIRE transaction back, savepoints included. Nothing the caller wrote earlier in
  the request survives, and ``rollback(save_point=...)`` afterwards raises 1305.
* ``QueryTimeoutError`` (MariaDB 1205) -- with ``innodb_rollback_on_timeout=OFF``
  (the default; confirmed on this deployment) only the failed statement is rolled
  back. The transaction is still live, but the unit of work is now half-applied,
  which is not a state any caller here is written to reason about.

So: neither is safe to resume from, and both must propagate to whoever owns the
transaction boundary. Retrying in place is not an option for 1213 -- the savepoints
are gone -- so the only correct response is to abandon the unit of work and let the
caller restart it.

This is deliberately a superset of ``retry_utilities.is_deadlock_error()``, which
answers a different question ("may I retry this statement?") and matches on 1213
only, partly by string.
"""

import frappe

NON_RESUMABLE_DB_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
