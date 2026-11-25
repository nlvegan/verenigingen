"""#3221: the e-Boekhouden security_helper contexts must hand back the CALLER's flags.

Same harm as #2577. ``migration_context``, ``cleanup_context``, ``migration_transaction``,
``atomic_migration_operation`` and the ``skip_validation`` path of ``validate_and_insert`` /
``validate_and_save`` raised ``frappe.flags`` and wrote False/None on exit. They nest (an
atomic operation inside a migration_context shares ``migration_initiated_by``), so the inner
exit wiped the outer scope's audit flags.

Every case runs with the flag set beforehand (value must come back) and absent beforehand
(must be absent again). Real flow: no mocks; the contexts are entered for real as the
current (Administrator) user. migration_transaction / atomic_migration_operation commit on
success, but write nothing here.
"""

from types import SimpleNamespace

import frappe

from verenigingen.e_boekhouden.utils.security_helper import (
    atomic_migration_operation,
    cleanup_context,
    migration_context,
    migration_transaction,
    validate_and_insert,
    validate_and_save,
)
from verenigingen.tests.utils.test_flags_restored_2577 import _ABSENT, FlagRestoreCase

SENTINEL = "caller-3221"


class TestSecurityHelperFlagsRestored(FlagRestoreCase):
    def _assert_caller_values_survive(self, names, call):
        """Flags hold a caller value (not just True) before; the same value must be back after."""
        self._arm(names, SENTINEL)
        call()
        for name in names:
            self.assertEqual(
                frappe.flags.get(name), SENTINEL, f"{name} lost the caller's value (#3221)"
            )

    def _both(self, names, call):
        self.assert_restored(names, call)
        self._assert_caller_values_survive(names, call)

    def test_migration_context(self):
        names = ["in_migration", "migration_operation", "migration_initiated_by"]

        def call():
            with migration_context("general"):
                self.assertTrue(frappe.flags.in_migration)

        self._both(names, call)

    def test_migration_context_restores_on_exception(self):
        def call():
            try:
                with migration_context("general"):
                    raise ValueError("boom")
            except ValueError:
                pass

        self._both(["in_migration", "migration_operation", "migration_initiated_by"], call)

    def test_cleanup_context(self):
        def call():
            with cleanup_context():
                self.assertTrue(frappe.flags.in_cleanup)

        self._both(["in_cleanup", "cleanup_initiated_by"], call)

    def test_migration_transaction(self):
        def call():
            with migration_transaction("general"):
                self.assertTrue(frappe.flags.in_migration_transaction)

        self._both(
            ["in_migration_transaction", "migration_transaction_type", "migration_initiated_by"], call
        )

    def test_atomic_migration_operation(self):
        def call():
            with atomic_migration_operation("general"):
                self.assertTrue(frappe.flags.in_atomic_migration)

        self._both(["in_atomic_migration", "atomic_operation_type", "atomic_initiated_by"], call)

    def test_nested_inner_exit_keeps_outer_audit_flags(self):
        """The real nesting: an atomic operation inside a migration_context."""
        self._arm(["migration_initiated_by"], _ABSENT)
        with migration_context("general"):
            outer = frappe.flags.migration_initiated_by
            self.assertTrue(outer)
            with migration_transaction("general"):
                pass
            self.assertEqual(
                frappe.flags.migration_initiated_by,
                outer,
                "the inner context's exit cleared the outer migration_initiated_by (#3221)",
            )
            self.assertTrue(frappe.flags.in_migration)

    def test_skip_validation_flag_insert_and_save(self):
        doc = SimpleNamespace(
            doctype="Account", name="X-3221", insert=lambda: None, save=lambda: None
        )
        for fn in (validate_and_insert, validate_and_save):
            self._both(["skip_non_critical_validations"], lambda fn=fn: fn(doc, skip_validation=True))

