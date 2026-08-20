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
from verenigingen.utils import (
    financial_history_batch_processor as batch_module,
    member_financial_history_manager as history_module,
)
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor
from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

DB_ALIASES = {"db", "database"}

SCOPED_METHODS = (
    "_process_member_payment_batch",
    "_process_member_expense_batch",
    "_rollback_to_savepoint",
    "_release_savepoint",
)


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
        FinancialHistoryBatchProcessor._process_member_payment_batch(
            "Assoc-Member-GONE-1234", {"INV-GONE": {"operation": "add_update", "data": {}}}
        )
        FinancialHistoryBatchProcessor._process_member_expense_batch(
            "Assoc-Member-GONE-1234", {"EXP-GONE": {"operation": "add_update", "data": {}}}
        )

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
                if call.func.attr not in ("commit", "rollback", "begin"):
                    continue
                # Receiver must look like a database handle: `frappe.db.x()` and the
                # aliased `db = frappe.db; db.x()`, which walked past an earlier check.
                value = call.func.value
                is_frappe_db = isinstance(value, ast.Attribute) and value.attr == "db"
                is_alias = isinstance(value, ast.Name) and value.id in DB_ALIASES
                if not (is_frappe_db or is_alias):
                    continue
                # A scoped rollback is the point -- but `save_point=None` is the
                # transaction-wide path (frappe's rollback() branches on `if
                # save_point:`), so a literal None must NOT count as scoped.
                if call.func.attr == "rollback" and any(
                    kw.arg == "save_point"
                    and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                    for kw in call.keywords
                ):
                    continue
                offenders.append(f"{node.name}:{call.lineno} frappe.db.{call.func.attr}()")

        self.assertEqual(
            offenders,
            [],
            "a per-member batch handler must confine itself to its savepoint "
            "(`begin()` counts: START TRANSACTION implicitly commits in MariaDB): "
            f"{offenders}. A transaction-wide rollback discards every other member "
            "processed in the same run and the caller's in-flight work -- and the "
            "dispatch loop swallows the exception, so the run still reports success. "
            "A transaction-wide commit flushes a caller's half-finished transaction; "
            "this queue is drained INLINE from add_invoice_to_payment_history(), so "
            "that is hook context.",
        )

    def test_a_vanished_savepoint_does_not_escalate_to_a_full_rollback(self):
        """Inner code can end the transaction, taking every savepoint with it.

        member_financial_history_manager commits after update_child_table (:286),
        and MariaDB discards all savepoints on commit -- so the scoped rollback
        raises 1305 "SAVEPOINT ... does not exist". CI caught exactly this, with the
        1305 masking the original error.

        The handler must then do NOTHING: escalating to a bare frappe.db.rollback()
        would discard the caller's work (the very bug being fixed) and could not undo
        the committed rows anyway.
        """
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "SavepointGone",
                "last_name": f"Caller{frappe.generate_hash(length=6)}",
                "email": f"spgone-{frappe.generate_hash(length=8)}@example.invalid",
                "birth_date": "1990-01-01",
            }
        ).insert()
        self.track_doc("Member", member.name)

        # a savepoint name that was never created -- what a post-commit rollback sees
        FinancialHistoryBatchProcessor._rollback_to_savepoint(
            f"never_created_{frappe.generate_hash(length=8)}", "Assoc-Member-IRRELEVANT"
        )

        self.assertTrue(
            frappe.db.exists("Member", member.name),
            "a vanished savepoint escalated into a transaction-wide rollback and took "
            "the caller's uncommitted work with it",
        )


class TestHistoryManagerLeavesTheTransactionAlone(VereningingenTestCase):
    """#411. The batch processor's savepoints are only worth as much as the code
    they wrap: ``MemberFinancialHistoryManager._save_with_retry`` used to end in a
    transaction-wide ``frappe.db.commit()``, and MariaDB discards every savepoint
    when a transaction commits.

    So the scoped rollback one frame up became a no-op, and #408 had to teach both
    ``_release_savepoint`` and ``_rollback_to_savepoint`` to tolerate a savepoint
    that had silently vanished. That defensiveness stays -- other code can still
    commit -- but the manager itself is now the thing being pinned.
    """

    def _member(self):
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "HistScope",
                "last_name": f"Caller{frappe.generate_hash(length=6)}",
                "email": f"histscope-{frappe.generate_hash(length=8)}@example.invalid",
                "birth_date": "1990-01-01",
            }
        ).insert()
        self.track_doc("Member", member.name)
        return member

    def test_a_callers_savepoint_survives_a_history_write(self):
        """The invariant, stated as the caller experiences it.

        A savepoint is the one thing a commit cannot leave behind: MariaDB drops
        all of them the moment the transaction ends. So RELEASE succeeding is
        proof no commit happened inside -- there is no way to fake it, and no way
        for the assertion to pass vacuously while the commit is still there.
        """
        member = self._member()
        save_point = f"hist_scope_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(save_point)

        manager = get_payment_history_manager(member)
        wrote = manager.add_or_update_entry(
            "ACC-SINV-HISTSCOPE-0001",
            lambda: {
                # Matches entry_id: if Member Payment History.invoice ever gains a
                # link/reqd check, a mismatched row would make update_child_table
                # throw and this test fail for a reason unrelated to commits.
                "invoice": "ACC-SINV-HISTSCOPE-0001",
                "posting_date": frappe.utils.nowdate(),
                "amount": 1.0,
                "outstanding_amount": 0.0,
                "payment_status": "Paid",
                "transaction_type": "Membership Invoice",
            },
            "invoice",
        )
        self.assertTrue(wrote, "the history write itself failed, so this proves nothing about commits")

        try:
            frappe.db.release_savepoint(save_point)
        except Exception as e:
            self.fail(
                f"the caller's savepoint {save_point} did not survive a history write ({e}). "
                "MariaDB discards every savepoint on commit, so this means the manager "
                "ended the caller's transaction -- flushing whatever the caller had in "
                "flight and disarming every scoped rollback above it (#411)."
            )

    def test_the_history_manager_never_ends_the_transaction(self):
        """Source guard, for the same reason #408 needed one.

        ``_save_with_retry`` is reached through several paths, and a behavioural
        test only covers the one it drives. This pins the invariant itself --
        including the two evasions that walked past the first version of the
        batch-processor guard: a ``save_point=None`` rollback (frappe branches on
        ``if save_point:``, so None IS the transaction-wide path) and the aliased
        ``db = frappe.db; db.commit()``.
        """
        tree = ast.parse(inspect.getsource(history_module))
        offenders = []

        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in ("commit", "rollback", "begin"):
                continue
            value = call.func.value
            is_frappe_db = isinstance(value, ast.Attribute) and value.attr == "db"
            is_alias = isinstance(value, ast.Name) and value.id in DB_ALIASES
            if not (is_frappe_db or is_alias):
                continue
            if call.func.attr == "rollback" and any(
                kw.arg == "save_point" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                for kw in call.keywords
            ):
                continue
            offenders.append(f"line {call.lineno}: frappe.db.{call.func.attr}()")

        self.assertEqual(
            offenders,
            [],
            "member_financial_history_manager must not end the caller's transaction: "
            "(`begin()` counts -- it issues START TRANSACTION, which implicitly commits "
            "in MariaDB and discards every savepoint, the ImplicitCommitError class) "
            f"{offenders}. It is reached from ordinary request and hook paths -- the "
            "batch queue is drained INLINE from add_invoice_to_payment_history() -- so "
            "a commit here flushes a caller's half-finished work and destroys every "
            "savepoint above it. Durability is the owning request or job's decision; "
            "if one caller genuinely needs it sooner, it commits for itself (#411).",
        )
