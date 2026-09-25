# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Reset MariaDB session variables between test CLASSES (#1353).

Why this exists
----------------
A CI shard runs every test module in ONE process, on ONE DB connection. Nothing
about that connection is reset between test files or classes -- only the
transaction is (`frappe.db.rollback()`, the harness's one automatic cleanup).
Session-scoped state set via ``SET SESSION ...`` is untouched by a rollback, so
it survives for the rest of the process once something sets it and never puts
it back.

#1350 / PR #1351 was exactly this: ``frappe.desk.notifications.get_open_count``
calls ``frappe.db.set_execution_timeout(1)`` (``SET SESSION max_statement_time =
1``) and never restores it. That leaked a 1-second statement ceiling into every
later test sharing the connection, and 81 modules later a deliberate 2-second
``innodb_lock_wait_timeout`` probe was killed by the inherited ceiling instead of
by the lock it was testing -- deterministic, but only in a shard layout that put
the two tests together. PR #1351 fixed that ONE call site with a local
``addCleanup``. This module is the harness-level backstop: the next leak (of the
same variable, or a different one -- production or third-party code neither test
file controls) does not need its own bug report to be caught.

``SET ... = DEFAULT``, not a snapshotted value
------------------------------------------------
An earlier revision of this module snapshotted the tracked variables' VALUES
once, at the first harness class to run, and restored every later class to
that cached snapshot. That is broken by construction: the app also has ~421
plain ``FrappeTestCase``-only classes and other non-harness ``unittest.TestCase``
classes that register no guard. If one of those runs BEFORE the first harness
class in a shard and leaks a tracked variable, the snapshot captures the
ALREADY-LEAKED value as though it were the correct baseline -- and every later
harness class then actively **re-applies** that leaked value at teardown,
defending the leak instead of undoing it. Measured independently during review
(test_site_11): a non-harness class set ``lock_wait_timeout = 97531`` first;
the next two ``EnhancedTestCase`` classes both still saw 97531 after the first
one's own cleanup ran.

``SET SESSION <var> = DEFAULT`` sidesteps the whole class of bug: MariaDB
resets the SESSION value to the current GLOBAL value, looked up fresh by the
server at restore time -- there is nothing here for an earlier leak to poison.
Verified this app and frappe core never deliberately set any of the tracked
variables to something other than the global value at connect time (no
``init_command``, no post-connect ``SET SESSION`` in
``frappe/database/mariadb/mysqlclient.py``'s ``get_connection_settings()`` /
``connect()``, and a repo-wide grep of ``verenigingen/`` and ``scripts/`` found
none either) -- so "the global value" and "what a fresh connection starts with"
are the same thing here, measured equal for all 7 tracked variables on a fresh
connection on this bench (test_site_2).

Which variables
----------------
Deliberately a fixed, narrow list, not "every session variable"
(``SHOW SESSION VARIABLES`` returns several hundred rows and most are never
touched by test or application code -- guarding an unbounded list would mean
resetting things nothing ever changes, at real per-class query cost, for no
benefit): the one #1350 actually hit, plus the ones #1353 names as "not
established" but plausible for the same failure shape.

A tracked name absent on this MariaDB version (e.g. ``transaction_isolation``
is MySQL 8's name; MariaDB 10.11 here only has ``tx_isolation``) cannot simply
be included in the ``SET ... = DEFAULT`` list regardless -- unlike a read
(``SHOW ... WHERE Variable_name IN (...)``, which just returns fewer rows), a
``SET`` naming an unknown variable raises ``Unknown system variable`` and,
measured, aborts the ENTIRE statement without applying any of the other
(valid) assignments in it. So which names are valid on this server is checked
once per process (``SHOW SESSION VARIABLES``, name existence only -- no value
is cached), and the restore only ever names variables confirmed to exist.

Cost
----
One name-existence query, once per PROCESS (module-level cache -- which
variable names exist on this MariaDB server does not change during a run).
TWO reset statements per test CLASS (~2972 harness classes app-wide as of
#1353): one issued immediately in ``setUpClass`` (so this class itself starts
clean, regardless of what ran before it -- see "start AND end" below), and one
via ``addClassCleanup`` (so it also runs if the rest of ``setUpClass`` raises
after registering it -- same reasoning as ``own_settings_company``,
``tests/support/verenigingen_settings.py``). Each reset is unconditional --
always issued, never diffed against the current value first -- because a
second query to check for drift would cost as much as the reset itself.

Deliberately per-CLASS, not per-test
--------------------------------------
Matches the granularity #1353 asks for and the cost/benefit above: ~2972 cheap
resets beats one query per test method. A test that legitimately needs a
session variable for the duration of its OWN body (the
``innodb_lock_wait_timeout`` probes in
``tests/unit/test_base_history_manager_row_lock.py``) already restores it
itself with its own ``addCleanup`` before its own class ends -- this guard is a
backstop for the next unrestored leak, not a replacement for that.

Reset at BOTH start and end of a class, not just one
------------------------------------------------------
A single end-of-class ``addClassCleanup`` leaves a gap: the FIRST harness
class after a leak (whether the leak came from a harness class's own test
body, or from one of the ~421 non-harness classes that register no guard at
all) still runs its own tests with the leaked value in place -- only the class
AFTER it would come back clean. That first class is exactly the #1350 victim
position: the leak is observed by whichever class runs next, and in a shard
that can be a harness class following a plain ``FrappeTestCase``. So
``guard_session_variables`` resets immediately, synchronously, as well as
registering the cleanup -- every harness class then starts clean regardless of
what ran before it, not just the one after the one that noticed.
"""

import frappe

#: MariaDB/MySQL session variables this guard resets to their GLOBAL value
#: (via ``SET SESSION <var> = DEFAULT``) after each test class. See the module
#: docstring for why this list and not "every session variable".
TRACKED_SESSION_VARIABLES = (
    "max_statement_time",
    "innodb_lock_wait_timeout",
    "lock_wait_timeout",
    "transaction_isolation",
    "tx_isolation",
    "sql_mode",
    "time_zone",
)

#: Populated once per process by `_supported_variables()`: which of
#: TRACKED_SESSION_VARIABLES actually exist as system variables on this
#: MariaDB server. Module-level, not a frappe.flags attribute, deliberately:
#: it must survive the per-class `_restore_thread_locals` cleanup
#: FrappeTestCase itself registers, which restores a deep copy of
#: `frappe.local.flags` at each class's teardown. Unlike the value snapshot
#: this replaced, caching NAME EXISTENCE cannot be poisoned by an earlier
#: leak -- which names exist is a property of the server version, not of
#: anything a test set.
_supported_variables_cache = None


def guard_session_variables(test_class) -> None:
    """Reset the tracked session variables to their GLOBAL (server-default)
    value NOW, and register a class-level cleanup that resets them again.

    Call this from ``setUpClass``, after ``super().setUpClass()``. No-ops on
    any backend other than MariaDB (``frappe.db.db_type != "mariadb"``):
    ``SHOW SESSION VARIABLES`` / ``SET SESSION name = DEFAULT`` are
    MariaDB/MySQL syntax, and every test site in this bench is MariaDB, so
    this is cheap insurance rather than a real code path.

    Both the immediate reset and the ``addClassCleanup`` are needed, not just
    one:

    * Without the IMMEDIATE reset, the first harness class after a leak
      (harness or non-harness -- this app has ~421 ``FrappeTestCase``-only /
      plain ``unittest.TestCase`` classes that register no guard at all)
      still starts its own tests with the leaked value in place; only the
      class AFTER it would come back clean. That first class is exactly the
      #1350 victim position -- the leak is observed by whichever class runs
      next, and in a shard that can be a harness class following a
      non-harness one.
    * Without the ``addClassCleanup``, a leak from one of THIS class's own
      test methods sits there until the next harness class's immediate reset
      runs -- which may never happen if the next class in the shard is a
      non-harness one.

    Because this runs synchronously inside ``setUpClass`` -- specifically
    inside THIS module's ``super().setUpClass()`` chain, before a subclass's
    own additional ``setUpClass`` code executes -- a subclass that sets one of
    the tracked variables deliberately, AFTER its own ``super().setUpClass()``
    call, is unaffected: that write happens strictly after this reset, not
    before it. Verified with a real subclass, not assumed (see
    ``TestStartOfClassResetDoesNotClobberADeliberateSubclassSetting`` in
    ``test_session_variable_guard.py``).
    """
    if getattr(frappe.db, "db_type", None) != "mariadb":
        return
    supported = _supported_variables()
    if not supported:
        return
    _reset_to_global_default(supported)
    test_class.addClassCleanup(_reset_to_global_default, supported)


def _supported_variables() -> tuple:
    """Which of TRACKED_SESSION_VARIABLES exist as system variables on this
    server, checked once per process. See module docstring for why a `SET
    ... = DEFAULT` naming an unknown variable is not merely a no-op for that
    one name -- it aborts the whole statement."""
    global _supported_variables_cache
    if _supported_variables_cache is None:
        rows = frappe.db.sql(
            "SHOW SESSION VARIABLES WHERE Variable_name IN %(names)s",
            {"names": TRACKED_SESSION_VARIABLES},
            as_dict=True,
        )
        _supported_variables_cache = tuple(sorted(row["Variable_name"].lower() for row in rows))
    return _supported_variables_cache


def _reset_to_global_default(names: tuple) -> None:
    """`SET SESSION` every named variable to `DEFAULT` (MariaDB's own current
    GLOBAL value for it, looked up fresh -- never a value this module cached)."""
    if not names:
        return
    assignments = ", ".join(f"{name} = DEFAULT" for name in names)
    frappe.db.sql(f"SET SESSION {assignments}")
