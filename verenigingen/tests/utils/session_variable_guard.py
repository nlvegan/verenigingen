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

Snapshot-and-restore, not hardcoded defaults
---------------------------------------------
CI's MariaDB defaults are not guaranteed to match this bench's, so restoring to
a literal like ``max_statement_time = 0`` could be wrong in either direction.
Instead this snapshots the ACTUAL session values once, at harness start
(whatever a fresh connection already carries -- including anything Frappe's own
``connect()`` sets), and puts every later class back to that baseline.

Which variables
----------------
Deliberately a fixed, narrow list, not "every session variable"
(``SHOW SESSION VARIABLES`` returns several hundred rows and most are never
touched by test or application code -- guarding an unbounded list would mean
restoring things nothing ever changes, at real per-class query cost, for no
benefit): the one #1350 actually hit, plus the ones #1353 names as "not
established" but plausible for the same failure shape. A variable name absent
on this MariaDB version (e.g. ``transaction_isolation`` is MySQL 8's name;
MariaDB 10.11 here calls it ``tx_isolation``) simply does not appear in the
snapshot and is silently skipped on restore -- ``SHOW ... WHERE Variable_name
IN (...)`` only returns rows that exist, so tracking both spellings costs
nothing on a server that only has one of them.

Cost
----
One snapshot query, once per PROCESS (module-level cache -- the values a fresh
connection carries do not change between classes on their own, only tests or
called production code change them). One restore statement per test CLASS
(~2972 harness classes app-wide as of #1353) in ``addClassCleanup``, so it also
runs if the rest of ``setUpClass`` raises after registering it -- same reasoning
as ``own_settings_company`` (``tests/support/verenigingen_settings.py``). The
restore is unconditional -- always issued, never diffed against the current
value first -- because a second query to check for drift would cost as much as
the restore itself.

Deliberately per-CLASS, not per-test
--------------------------------------
Matches the granularity #1353 asks for and the cost/benefit above: 2972 cheap
restores beats one query per test method. A test that legitimately needs a
session variable for the duration of its OWN body (the
``innodb_lock_wait_timeout`` probes in
``tests/unit/test_base_history_manager_row_lock.py``) already restores it
itself with its own ``addCleanup`` before its own class ends -- this guard is a
backstop for the next unrestored leak, not a replacement for that.
"""

import re

import frappe

#: MariaDB/MySQL session variables this guard snapshots and restores. See the
#: module docstring for why this list and not "every session variable".
TRACKED_SESSION_VARIABLES = (
    "max_statement_time",
    "innodb_lock_wait_timeout",
    "lock_wait_timeout",
    "transaction_isolation",
    "tx_isolation",
    "sql_mode",
    "time_zone",
)

_NUMERIC_VALUE = re.compile(r"^-?\d+(\.\d+)?$")

#: Populated once per process by `_snapshot_baseline()`. Module-level, not a
#: frappe.flags attribute, deliberately: it must survive the per-class
#: `_restore_thread_locals` cleanup FrappeTestCase itself registers, which
#: restores a deep copy of `frappe.local.flags` at each class's teardown.
_baseline_cache = None


def guard_session_variables(test_class) -> None:
    """Register a class-level restore of the tracked session variables.

    Call this from ``setUpClass``, after ``super().setUpClass()``. No-ops on any
    backend other than MariaDB (``frappe.db.db_type != "mariadb"``): ``SHOW
    SESSION VARIABLES`` / ``SET SESSION name = value`` are MariaDB/MySQL syntax,
    and every test site in this bench is MariaDB, so this is cheap insurance
    rather than a real code path.
    """
    if getattr(frappe.db, "db_type", None) != "mariadb":
        return
    baseline = _snapshot_baseline()
    if not baseline:
        return
    test_class.addClassCleanup(_restore_tracked_session_variables, dict(baseline))


def _snapshot_baseline() -> dict:
    """The tracked variables' current values, captured once per process."""
    global _baseline_cache
    if _baseline_cache is None:
        rows = frappe.db.sql(
            "SHOW SESSION VARIABLES WHERE Variable_name IN %(names)s",
            {"names": TRACKED_SESSION_VARIABLES},
            as_dict=True,
        )
        _baseline_cache = {row["Variable_name"].lower(): row["Value"] for row in rows}
    return _baseline_cache


def _restore_tracked_session_variables(baseline: dict) -> None:
    """``SET SESSION`` every tracked variable back to its snapshotted value.

    Not parameterised with ``%s``: MariaDB rejects a quoted string for a numeric
    session variable (``SET SESSION innodb_lock_wait_timeout = '50'`` raises
    ``Incorrect argument type to variable 'innodb_lock_wait_timeout'`` --
    measured), so a single value-typed placeholder cannot cover both the numeric
    and the string-valued variables tracked here in one statement. The values
    are self-produced (this module's own earlier ``SHOW SESSION VARIABLES``
    call, never user input), so a bare numeric literal is rendered directly and
    anything else goes through ``frappe.db.escape(percent=False)`` -- this
    statement is sent with no separate ``values`` argument, so there is no
    second %-formatting pass to collapse ``escape()``'s default ``%`` ->
    ``%%`` back down; with the default ``percent=True`` a value containing a
    literal ``%`` would come back out of MariaDB doubled.
    """
    if not baseline:
        return
    assignments = ", ".join(f"{name} = {_sql_literal(value)}" for name, value in baseline.items())
    frappe.db.sql(f"SET SESSION {assignments}")


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    if _NUMERIC_VALUE.match(text):
        return text
    return frappe.db.escape(text, percent=False)
