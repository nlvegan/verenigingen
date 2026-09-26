"""Regression tests for #1510: the six ad-hoc SEPA operations tables
(`tabSEPA_Notification_Log`, `tabSEPA_Notification_Preferences`,
`tabSEPA_Distributed_Lock`, `tabSEPA_Rollback_Operation`,
`tabSEPA_Compensation_Transaction`, `tabSEPA_Rollback_Audit`) must be created
by ``verenigingen.verenigingen_payments.utils.shared.sepa_ops_tables
.ensure_sepa_ops_tables()``, run from ``after_install``/``after_migrate``
(``verenigingen/hooks/lifecycle.py``) -- NOT by the SEPA managers'
constructors.

Before the fix, each manager's ``__init__`` created its own tables inline,
in whatever transaction the caller held. `CREATE TABLE` is DDL, and DDL
auto-commits in MariaDB, so the first write in that transaction made the
`CREATE TABLE` raise `ImplicitCommitError` -- an exception every one of
those constructors swallowed. On a fresh site (every CI shard, and any
newly installed site before some write-free request happened to construct
the manager first) the table was silently never created, and the first real
read against it failed with "table doesn't exist".

NOT PARALLEL-SAFE: these tests DROP and recreate real tables via
``frappe.db.sql_ddl()``, which auto-commits in MariaDB. No test-transaction
rollback can undo that, so every test here restores the tables
unconditionally in tearDown, and this module must not run concurrently with
anything else on the same site that touches these six tables.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.sepa_notification_manager import (
    get_sepa_notification_history,
)
from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import (
    SEPADistributedLock,
)
from verenigingen.verenigingen_payments.utils.shared.sepa_ops_tables import (
    ensure_sepa_ops_tables,
)

ALL_TABLES = (
    "tabSEPA_Notification_Log",
    "tabSEPA_Notification_Preferences",
    "tabSEPA_Distributed_Lock",
    "tabSEPA_Rollback_Operation",
    "tabSEPA_Compensation_Transaction",
    "tabSEPA_Rollback_Audit",
)

# A handful of columns per table that are distinctive enough to prove the
# real schema landed (not just an empty/wrong table), without repeating the
# full column list already pinned in sepa_ops_tables.py.
EXPECTED_COLUMNS = {
    "tabSEPA_Notification_Log": {
        "name",
        "notification_id",
        "notification_type",
        "priority",
        "delivery_status",
    },
    "tabSEPA_Notification_Preferences": {
        "name",
        "user_email",
        "notification_type",
        "enabled",
    },
    "tabSEPA_Distributed_Lock": {
        "name",
        "lock_id",
        "resource",
        "lock_owner",
        "expires_at",
    },
    "tabSEPA_Rollback_Operation": {
        "name",
        "operation_id",
        "batch_name",
        "reason",
        "status",
    },
    "tabSEPA_Compensation_Transaction": {
        "name",
        "transaction_id",
        "operation_id",
        "action_type",
    },
    "tabSEPA_Rollback_Audit": {
        "name",
        "entry_id",
        "operation_id",
        "action",
    },
}


def _table_exists(table_name: str) -> bool:
    return bool(frappe.db.sql(f"SHOW TABLES LIKE '{table_name}'"))  # noqa: S608


def _columns_of(table_name: str) -> set:
    rows = frappe.db.sql(f"SHOW COLUMNS FROM `{table_name}`", as_dict=True)  # noqa: S608
    return {row["Field"] for row in rows}


def _drop_tables(table_names) -> None:
    # DROP is DDL (IMPLICIT_COMMIT_QUERY_TYPES): use sql_ddl() so it commits
    # any pending work first instead of raising ImplicitCommitError.
    for table_name in table_names:
        frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table_name}`")


class TestEnsureSepaOpsTables(EnhancedTestCase):
    """The install/migrate entry point recreates all six tables from scratch."""

    def tearDown(self):
        # Real, non-transactional DDL -- restore unconditionally regardless
        # of how the test finished.
        ensure_sepa_ops_tables()
        super().tearDown()

    def test_recreates_all_six_tables_with_expected_columns(self):
        _drop_tables(ALL_TABLES)
        for table_name in ALL_TABLES:
            self.assertFalse(_table_exists(table_name), f"{table_name} should be dropped before the test")

        ensure_sepa_ops_tables()

        for table_name, expected in EXPECTED_COLUMNS.items():
            self.assertTrue(
                _table_exists(table_name), f"{table_name} should exist after ensure_sepa_ops_tables()"
            )
            missing = expected - _columns_of(table_name)
            self.assertFalse(missing, f"{table_name} missing expected columns: {missing}")

    def test_is_idempotent_when_tables_already_exist(self):
        # The tables already exist (from after_install/after_migrate on this
        # site). Calling again must be a no-op, not an error.
        ensure_sepa_ops_tables()
        ensure_sepa_ops_tables()
        for table_name in ALL_TABLES:
            self.assertTrue(_table_exists(table_name))


class TestNotificationHistoryReadAfterBootstrap(EnhancedTestCase):
    """A real reader succeeds once the bootstrap entry point (not the
    manager's own constructor) has (re)created the tables it needs -- even
    when the caller already holds a pending write, which is exactly the
    precondition that used to trip ImplicitCommitError inside the manager's
    now-removed constructor DDL.
    """

    def setUp(self):
        super().setUp()
        self.reader = self.create_test_user_with_roles(roles=["Verenigingen Administrator"])

    def tearDown(self):
        frappe.set_user("Administrator")
        # Real, non-transactional DDL -- restore unconditionally.
        ensure_sepa_ops_tables()
        super().tearDown()

    def test_history_read_succeeds_after_bootstrap_recreates_dropped_tables(self):
        # Drop just the two tables this reader touches.
        _drop_tables(["tabSEPA_Notification_Log", "tabSEPA_Notification_Preferences"])
        for table_name in ("tabSEPA_Notification_Log", "tabSEPA_Notification_Preferences"):
            self.assertFalse(_table_exists(table_name), f"{table_name} should be dropped before the test")

        # Recreate via the install/migrate entry point -- NOT via
        # SEPANotificationManager()'s own constructor, which no longer does
        # this (see #1510).
        ensure_sepa_ops_tables()

        # A pending write in the SAME transaction: this is exactly the
        # precondition under which the old constructor DDL raised
        # ImplicitCommitError and silently swallowed it, leaving the table
        # missing. With table creation moved to install/migrate, the reader
        # below performs no DDL at all and is unaffected by this write.
        # transaction_writes is a property of the DB connection, not of
        # frappe.session.user, so inserting as Administrator here (normal
        # permissions, no bypass) still leaves the write pending once we
        # switch to the reader below.
        # Cleanup: EnhancedTestCase's captured-insert drain deletes this at
        # tearDown regardless of commit state (see _drain_captured_inserts),
        # so no manual cleanup is needed here.
        todo = frappe.new_doc("ToDo")
        todo.description = "sepa-table-bootstrap regression probe"
        todo.insert()
        self.assertGreater(frappe.db.transaction_writes, 0, "expected a pending write")

        frappe.set_user(self.reader.email)

        result = get_sepa_notification_history(days_back=7)

        self.assertTrue(result.get("success"), f"history read failed: {result.get('error')}")
        self.assertIn("notifications", result)


class TestDistributedLockConstructionPreservesPendingWrites(EnhancedTestCase):
    """#1510: constructing SEPADistributedLock() must not touch the caller's
    transaction.

    Before the fix, its constructor called ``_ensure_lock_table()``, which
    ran the CREATE TABLE through ``shared.db_helpers.ensure_table_exists()``.
    That helper calls ``frappe.db.rollback()`` on ANY error -- and the same
    ``CREATE TABLE IF NOT EXISTS`` raises ``ImplicitCommitError`` whenever
    the caller already has a pending write, regardless of whether the table
    already exists. So constructing a lock while the caller held a pending
    write silently discarded that write. This is a stronger check than "the
    read succeeds": it directly proves the caller's transaction survives,
    which the ordinary "does the read work" test cannot distinguish from
    "the DDL failed harmlessly because the table was already there".
    """

    def tearDown(self):
        ensure_sepa_ops_tables()
        super().tearDown()

    def test_pending_write_survives_lock_construction(self):
        # Ordinary state: the table already exists, as it would on any site
        # that has run after_install/after_migrate.
        ensure_sepa_ops_tables()

        # Cleanup: EnhancedTestCase's captured-insert drain deletes this at
        # tearDown regardless of commit state (see _drain_captured_inserts),
        # so no manual cleanup is needed here.
        todo = frappe.new_doc("ToDo")
        todo.description = "sepa-distributed-lock regression probe"
        todo.insert()
        self.assertGreater(frappe.db.transaction_writes, 0, "expected a pending write")

        SEPADistributedLock()

        # A rollback triggered by lock construction would silently discard
        # this write; it must still be visible in this session.
        self.assertTrue(
            frappe.db.exists("ToDo", todo.name),
            "constructing SEPADistributedLock discarded a pending write (rollback)",
        )
