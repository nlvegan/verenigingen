"""Guards on FinancialHistoryBatchProcessor's transaction scope.

The processor drains a PROCESS-GLOBAL queue, inline from
``add_invoice_to_payment_history()`` and every 5 minutes from the scheduler
(``hooks/scheduler.py``). Its per-member handlers used to end in a bare
``frappe.db.commit()`` and, on failure, a bare ``frappe.db.rollback()``.

Both are transaction-WIDE. The docstrings promise per-member atomicity; a bare
rollback delivers the opposite -- it discards every other member already
processed in the same run, plus whatever the caller had in flight, and the
caller's ``except`` then swallows the exception and continues. In production
that is silent data loss reported as a successful job; in CI it surfaced as
"Member ... not found" from an unrelated ``reload()`` four frames away.

Two guards, because one alone is not enough:

* the behavioural test covers the scenario CI hit (a stale entry naming a
  deleted member), which now takes the early-skip path; and
* the source guard covers the savepoint invariant itself, which the behavioural
  test can no longer reach precisely BECAUSE of that early skip -- so without it
  a reintroduced ``frappe.db.rollback()`` would go unnoticed.
"""

import ast
import inspect

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils import financial_history_batch_processor as batch_module
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor

SCOPED_METHODS = ("_process_member_payment_batch", "_process_member_expense_batch")


class TestFinancialBatchTransactionScope(VereningingenTestCase):
    def test_stale_entry_for_deleted_member_leaves_caller_work_intact(self):
        """A queued entry naming a member that no longer exists must not unwind
        the caller's own uncommitted work.

        This is the CI failure reproduced end to end: before the fix the flush
        issued a transaction-wide rollback and this member vanished.
        """
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "BatchScope",
                "last_name": f"Caller{frappe.generate_hash(length=6)}",
                "email": f"batchscope-{frappe.generate_hash(length=8)}@example.invalid",
                "birth_date": "1990-01-01",
            }
        ).insert()
        self.track_doc("Member", member.name)
        self.assertTrue(frappe.db.exists("Member", member.name))

        FinancialHistoryBatchProcessor.reset_queues()
        FinancialHistoryBatchProcessor._payment_queue["Assoc-Member-DOES-NOT-EXIST-9999"][
            "ACC-SINV-DOES-NOT-EXIST-0001"
        ] = {"operation": "add_update", "timestamp": frappe.utils.now(), "data": {}}

        FinancialHistoryBatchProcessor.force_process_all()

        self.assertTrue(
            frappe.db.exists("Member", member.name),
            "flushing a stale queue entry destroyed the caller's uncommitted member -- "
            "the rollback escaped its member and took the whole transaction",
        )

    def test_missing_member_is_skipped_rather_than_raised(self):
        """A member deleted between queueing and the flush is an expected race for a
        queue drained minutes later, so it must not raise (the caller logs an Error
        Log per raised batch, which is noise for a routine race)."""
        FinancialHistoryBatchProcessor.reset_queues()
        FinancialHistoryBatchProcessor._payment_queue["Assoc-Member-GONE-1234"]["INV-GONE"] = {
            "operation": "add_update",
            "timestamp": frappe.utils.now(),
            "data": {},
        }
        FinancialHistoryBatchProcessor._expense_queue["Assoc-Member-GONE-1234"]["EXP-GONE"] = {
            "operation": "add_update",
            "timestamp": frappe.utils.now(),
            "data": {},
        }

        FinancialHistoryBatchProcessor._process_member_payment_batch(
            "Assoc-Member-GONE-1234", {"INV-GONE": {"operation": "add_update", "data": {}}}
        )
        FinancialHistoryBatchProcessor._process_member_expense_batch(
            "Assoc-Member-GONE-1234", {"EXP-GONE": {"operation": "add_update", "data": {}}}
        )

        FinancialHistoryBatchProcessor.reset_queues()

    def test_per_member_handlers_never_end_the_whole_transaction(self):
        """Neither handler may call transaction-wide commit/rollback.

        Read from source rather than exercised, deliberately: the behavioural test
        above now short-circuits on the missing-member skip, so it would stay green
        if someone restored the bare rollback. This assertion is what actually pins
        the savepoint invariant.
        """
        tree = ast.parse(inspect.getsource(batch_module))
        offenders = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in SCOPED_METHODS:
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                if call.func.attr not in ("commit", "rollback"):
                    continue
                # frappe.db.<attr>(...)
                value = call.func.value
                if not (isinstance(value, ast.Attribute) and value.attr == "db"):
                    continue
                if call.func.attr == "rollback" and any(kw.arg == "save_point" for kw in call.keywords):
                    continue  # scoped rollback is the point
                offenders.append(f"{node.name}:{call.lineno} frappe.db.{call.func.attr}()")

        self.assertEqual(
            offenders,
            [],
            "per-member batch handlers must confine themselves to a savepoint: "
            f"{offenders}. A bare frappe.db.rollback() discards every other member "
            "processed in the same run and the caller's in-flight work; a bare "
            "frappe.db.commit() flushes a caller's half-finished transaction.",
        )
