"""Savepoint bookkeeping for one cleanup attempt, without touching the rest of it.

Extracted because the "the savepoint is gone -- an inner commit dropped it, or a
deadlock rolled the whole transaction back" comment had already been written out by
hand twice -- `tests/utils/base.py` and `tests/fixtures/enhanced_test_factory.py` --
and `tests/utils/factories.py` was about to be the third. This repo's rule is that an
explanation worth writing next to a fix is a search query, and
`duplicate_helper_validator.py` cannot find these: it counts private module-level
functions, so methods are invisible to it (#445).

Only `factories.py` calls this today. Converging the two drains onto it is a
behaviour change for them -- neither distinguishes the deadlock case -- and a one-line
widening in that area took 6 of 12 CI shards red during #486, so it needs shard-scale
proof and a change of its own.
"""

import frappe


def rollback_cleanup_attempt(savepoint, error):
    """Undo the failed attempt that raised `error`, and nothing else.

    `error` is read, not just logged: after MariaDB **1213** the server has already
    rolled the ENTIRE transaction back, savepoints included, so
    `rollback(save_point=...)` raises **1305** on top of it and buries the real error.
    There is nothing left to undo. `transaction_errors.py`'s docstring carries the
    measurement, and `_atomically` keys the same decision off the same exception type.

    **1205 (`QueryTimeoutError`) is deliberately NOT in that branch.** With
    `innodb_rollback_on_timeout=OFF` -- the default, confirmed on this deployment --
    only the failed statement was rolled back, so the savepoint is intact and rolling
    back to it is exactly right.

    Nothing is re-raised, unlike `transaction_errors._atomically`. That module hands a
    non-resumable error to whoever owns the transaction boundary; the caller here is a
    test teardown, where raising is the #483 defect itself -- it skips the caller's
    `super().tearDown()`, and with it the drain, the Error Log capture, the leak report
    and the mock restoration.
    """
    if isinstance(error, frappe.QueryDeadlockError):
        return

    try:
        frappe.db.rollback(save_point=savepoint)
    except Exception:
        # An inner commit dropped the savepoint. Nothing left to undo, and raising
        # here would replace the real cleanup failure with an untriageable
        # "SAVEPOINT ... does not exist".
        pass


def release_cleanup_savepoint(savepoint):
    """Release a savepoint whose attempt succeeded.

    Without this, a cleanup of N documents leaves N savepoints standing in the
    transaction. `_cleanup_document_with_retry` gets away without releasing because it
    commits after every successful delete; the callers here deliberately do not commit
    (#489), so the savepoints would accumulate for the whole teardown.
    """
    try:
        frappe.db.release_savepoint(savepoint)
    except Exception:
        # Same reasoning as above: an inner commit already dropped it.
        pass
