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

# MariaDB "SAVEPOINT <name> does not exist".
_SAVEPOINT_DOES_NOT_EXIST = 1305


def _is_missing_savepoint(error):
    """Both shapes: the driver's (1305, 'SAVEPOINT x does not exist') and a wrapped copy
    that kept only the message."""
    args = getattr(error, "args", ())
    if args and args[0] == _SAVEPOINT_DOES_NOT_EXIST:
        return True
    return "does not exist" in str(error)


def rollback_to_savepoint(save_point):
    """``ROLLBACK TO SAVEPOINT`` from inside an ``except``, without replacing the error.

    A raise from inside an ``except`` block replaces the exception being handled, and this
    statement has two ways to raise 1305 for reasons that have nothing to do with the
    failure being handled:

    * **a 1213 deadlock** -- the server rolls the whole transaction back and discards every
      savepoint in it. Measured on test_site_1 with two contending connections: the
      victim's savepoint is gone, a non-victim control's survives, so the loss is the
      deadlock's doing and not "savepoints do not work here";
    * **a nested commit** -- any commit clears the savepoint stack, so a helper that commits
      internally takes its caller's savepoint with it. Not hypothetical: mt940_import hit
      it and hand-wrote this function twice.

    In both cases the 1305 masks the real error, and every guard keyed on the real error's
    TYPE then evaluates False -- which is how #481's guard could be correctly placed on 50
    endpoints and still never fire for the one class it exists to catch (#561).

    Returns True if the rollback happened, False if the savepoint was already gone.
    Anything other than a missing savepoint still propagates: this hides one specific,
    diagnosed condition, not savepoint bugs in general.
    """
    try:
        frappe.db.rollback(save_point=save_point)
        return True
    except Exception as rollback_error:  # non-resumable-ok: cleanup running after the failure
        if not _is_missing_savepoint(rollback_error):
            raise
        return False


def insert_and_submit_atomically(doc):
    """Insert and submit as one unit: a failed submit must leave no draft behind.

    A submit precondition can only answer "may this user submit this DOCTYPE?", which
    is the only question askable before the document exists. It cannot see the
    document-level reasons a submit throws - a frozen account, a closed accounting
    period, a Company User Permission, an ERPNext validation that only runs on submit.
    Those fail BETWEEN insert() and submit(), and insert() has already written the row.

    Frappe offers no protection here: Document._save() calls set_docstatus() ->
    db_update() and only then run_post_save_methods(), and there is no savepoint
    anywhere in Document.save/submit. So a throw inside on_submit leaves docstatus=1
    written with no GL entries, and PaymentEntry.on_submit runs update_payment_requests()
    and update_payment_schedule() BEFORE make_gl_entries(), so those land too. Callers
    that swallow the exception then leave that row behind permanently - and a
    docstatus=1-without-GL row satisfies the very dedup guards meant to trigger a retry.

    The exception is re-raised rather than swallowed: the caller must still record the
    operation as failed. Frappe's own ``savepoint`` context manager is not usable here
    because it swallows what it catches, which would let a caller report success naming
    a document that no longer exists.

    Extracted from BankTransactionReconciliationManager._insert_and_submit, which was
    the only correct implementation in the codebase while every gateway path went
    without one.
    """
    _atomically(doc.insert, doc.submit)


def submit_atomically(doc):
    """Submit inside a savepoint, so a failed submit leaves the DRAFT intact.

    For callers that treat an unsubmitted draft as a legitimate outcome (graceful
    degradation on a missing submit permission). Without this a throw inside on_submit
    leaves docstatus=1 with no GL entries, which is not a draft and not a submitted
    entry - it is a row that satisfies dedup guards while having posted nothing.
    """
    _atomically(doc.submit)


def _atomically(*operations):
    savepoint = f"atomic_{frappe.generate_hash(length=8)}"
    frappe.db.savepoint(savepoint)
    try:
        for operation in operations:
            operation()
    except NON_RESUMABLE_DB_ERRORS:
        # A 1213 has already rolled the entire transaction back, savepoints included,
        # so rolling back to this one would raise 1305 on top of the real error and
        # hide it. There is nothing left to undo.
        raise
    except Exception:
        rollback_to_savepoint(savepoint)
        raise
    else:
        frappe.db.release_savepoint(savepoint)
