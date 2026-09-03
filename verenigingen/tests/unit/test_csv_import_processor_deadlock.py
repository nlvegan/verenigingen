# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""``CSVImportBackgroundProcessor``'s row loop must abandon the import on a
non-resumable DB error rather than counting it as one bad row (#700).

A ``QueryDeadlockError`` (MariaDB 1213) means the server has already thrown the
ENTIRE transaction away, savepoints included; a ``QueryTimeoutError`` (1205)
leaves the transaction half-applied. Neither is a row-level failure the batch
loop can shrug off and keep going from -- ``verenigingen/utils/
transaction_errors.py`` is explicit that both must propagate to whoever owns
the transaction boundary, which for a CSV import is this loop.

Before the fix, ``process_import``'s row loop caught ``Exception`` around
``process_row_callback(...)``, so a re-raised ``NON_RESUMABLE_DB_ERRORS`` (the
shape every per-row importer now uses, since #570/#698) was swallowed here
too: counted as one skipped row, logged, and the loop moved on to the next
row -- against a transaction the server had already discarded.

This module drives the real ``CSVImportBackgroundProcessor.process_import``
against a stub ``Member Import`` doc (the engine is doctype-agnostic; the stub
is only there to give ``load_import_doc``/``_update_status`` something to
read and write). The row callback is a plain test double that raises on
command, which is the right level for testing the ENGINE's transaction
boundary -- the callback's own internals (savepoint, rollback) are covered by
each importer's own row-atomicity tests.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.member.test_member_import import _create_stub_member_import_doc
from verenigingen.tests.support.non_resumable_errors import deadlock, lock_wait_timeout
from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor


class _DeadlockRowLoopBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.import_doc = _create_stub_member_import_doc()
        self.calls = []

    def _run_engine_import(self, rows, callback, batch_size=1):
        processor = CSVImportBackgroundProcessor(self.import_doc.name, "Member Import")
        processor.load_import_doc()
        return processor.process_import(
            data_rows=rows,
            process_row_callback=callback,
            batch_size=batch_size,
            batch_commit=True,
        )

    def _engine_row(self, n):
        return {"row_number": n}


class TestRowLoopAbandonsOnNonResumableError(_DeadlockRowLoopBase):
    def test_a_deadlock_abandons_the_import_instead_of_counting_it_as_one_bad_row(self):
        """The core claim: row 2's deadlock must stop the import before row 3.

        ``batch_size=1`` so row 1 completes and commits in its own batch --
        proving the abandonment does not also erase already-durable work --
        before row 2 raises.
        """

        def callback(row, error_log):
            self.calls.append(row["row_number"])
            if row["row_number"] == 1:
                return ("created", f"REC-{row['row_number']}")
            if row["row_number"] == 2:
                raise deadlock()
            raise AssertionError("row 3 must never be reached")

        rows = [self._engine_row(1), self._engine_row(2), self._engine_row(3)]
        result = self._run_engine_import(rows, callback)

        self.assertEqual(self.calls, [1, 2], "row 3 must not be attempted after the deadlock")
        self.assertFalse(result["success"], result)
        self.import_doc.reload()
        self.assertEqual(self.import_doc.import_status, "Failed")

    def test_a_lock_timeout_also_abandons_the_import(self):
        """1205 gets the same treatment as 1213 -- both are NON_RESUMABLE_DB_ERRORS."""

        def callback(row, error_log):
            self.calls.append(row["row_number"])
            if row["row_number"] == 1:
                raise lock_wait_timeout()
            raise AssertionError("row 2 must never be reached")

        rows = [self._engine_row(1), self._engine_row(2)]
        result = self._run_engine_import(rows, callback)

        self.assertEqual(self.calls, [1])
        self.assertFalse(result["success"], result)
        self.import_doc.reload()
        self.assertEqual(self.import_doc.import_status, "Failed")

    def test_an_ordinary_exception_is_still_counted_and_the_import_continues(self):
        """The control: an everyday row failure must still be swallowed and the
        loop must still reach every row. Without this, a fix that made the loop
        abandon on ANY exception would also pass the two tests above."""

        def callback(row, error_log):
            self.calls.append(row["row_number"])
            if row["row_number"] == 2:
                raise ValueError("one bad row")
            return ("created", f"REC-{row['row_number']}")

        rows = [self._engine_row(1), self._engine_row(2), self._engine_row(3)]
        result = self._run_engine_import(rows, callback)

        self.assertEqual(self.calls, [1, 2, 3], "an ordinary exception must not abandon the batch")
        self.assertTrue(result["success"], result)
        self.assertEqual((result["created"], result["skipped"]), (2, 1), result)
        self.import_doc.reload()
        self.assertEqual(self.import_doc.import_status, "Completed")
