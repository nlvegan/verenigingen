"""Savepoint bookkeeping for one cleanup attempt, without touching the rest of it.

Extracted because the "the savepoint is gone -- an inner commit dropped it, or a
deadlock rolled the whole transaction back" comment had already been written out by
hand twice -- `tests/utils/base.py` and `tests/fixtures/enhanced_test_factory.py` --
and `tests/utils/factories.py` was about to be the third. This repo's rule is that an
explanation worth writing next to a fix is a search query.

`duplicate_helper_validator.py` would not have caught it, but NOT for the reason first
written here. It has seen methods as well as module-level functions since #445 was
fixed (`275a906a`); its own docstring says so. It misses these two because one copy is
inline code rather than a function at all, and because it keys on the helper's NAME,
which exists in only one file. A ratchet that reads names cannot see a duplicated
explanation.

Only `factories.py` calls this today, and the two copies are still there -- #499 tracks
converging them, and each carries a pointer to this module. Converging them is a
behaviour change (neither distinguishes the deadlock case) in code carrying 1748 test
classes, and a one-line widening in that area took 6 of 12 CI shards red during #486,
so it needs shard-scale proof and a change of its own.
"""

import frappe

from verenigingen.tests.harness_logger import get_harness_logger


def rollback_cleanup_attempt(savepoint, error):
    """Undo the failed attempt that raised `error` -- or nothing, if a 1213 already did.

    Undoes that attempt and nothing else.

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

    WHAT THIS BRANCH DOES NOT COVER, measured: a 1213 raised by `delete_doc`'s own row
    lock probe never arrives here as one. `frappe/model/delete_doc.py:148` takes a
    `FOR UPDATE NOWAIT` and rewrites BOTH 1205 and 1213 into `frappe.QueryTimeoutError`
    with a new message, discarding the original -- so for the most likely 1213 on this
    path the rollback below is attempted, raises 1305, and is swallowed. That is the
    behaviour that was here before, i.e. this fails safe rather than silently changing
    it. The branch covers a 1213 raised deeper in, from `on_trash` or
    `delete_from_table`. `retry_utilities.is_deadlock_error()` answers "is this a 1213,
    however it arrived" by also matching the message, and would not help here either:
    frappe replaces the message too.
    """
    if isinstance(error, frappe.QueryDeadlockError):
        return

    try:
        frappe.db.rollback(save_point=savepoint)
    except Exception as rollback_error:
        # An inner commit dropped the savepoint. Raising here would replace the real
        # cleanup failure with an untriageable "SAVEPOINT ... does not exist" -- but a
        # failed undo means the attempt was NOT undone, while the caller goes on to
        # report only the original error. Logging says so without replacing anything;
        # a swallow that logs nothing is the blind spot in the swallow ratchet, not a
        # thing it permits.
        get_harness_logger("cleanup-savepoint").warning(
            "Could not undo a failed cleanup attempt (%s): %s", savepoint, rollback_error
        )


def release_cleanup_savepoint(savepoint):
    """Release a savepoint whose attempt succeeded.

    Without this, a cleanup of N documents leaves N savepoints standing in the
    transaction. `_cleanup_document_with_retry` gets away without releasing because it
    commits after every successful delete; the callers here deliberately do not commit
    (#489), so the savepoints would accumulate for the whole teardown.

    Correct bookkeeping rather than a fix for anything observable: 5000 unreleased
    savepoints were measured at 0.60s to create and cost nothing measurable on the next
    insert. Do not read this as a performance fix.
    """
    try:
        frappe.db.release_savepoint(savepoint)
    except Exception:
        # Same reasoning as above: an inner commit already dropped it.
        pass
