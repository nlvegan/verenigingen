"""
Tests for verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py

PaymentMixin is mixed into the Member controller. These tests target the
independently-testable, branch-heavy validation / helper methods that are not
already covered elsewhere:

- set_payment_reference()      : payment_reference defaulting
- validate_bank_details()      : SEPA Direct Debit IBAN / account-holder guards
- validate_iban_format()       : empty-input short circuit + real IBAN formatting
- get_member_chapters()        : Chapter Member lookup (and error fallback)
- _is_chapter_management_enabled()

All tests use REAL Member / Chapter documents; no business logic is mocked.
"""

import ast
import inspect
import threading
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor


class TestPaymentMixin(EnhancedTestCase):
    # ------------------------------------------------------------------
    # set_payment_reference
    # ------------------------------------------------------------------
    def test_set_payment_reference_defaults_to_name(self):
        """When no payment_reference is set it defaults to the member's name."""
        member = self.create_test_member(first_name="PayRef", last_name="Default")
        member.payment_reference = None
        member.set_payment_reference()
        self.assertEqual(member.payment_reference, member.name)

    def test_set_payment_reference_preserves_existing(self):
        """An existing payment_reference is left untouched."""
        member = self.create_test_member(first_name="PayRef", last_name="Keep")
        member.payment_reference = "CUSTOM-REF-1"
        member.set_payment_reference()
        self.assertEqual(member.payment_reference, "CUSTOM-REF-1")

    # ------------------------------------------------------------------
    # validate_iban_format
    # ------------------------------------------------------------------
    def test_validate_iban_format_empty_returns_none(self):
        """An empty IBAN short-circuits to None before any service call."""
        member = self.create_test_member(first_name="Iban", last_name="Empty")
        self.assertIsNone(member.validate_iban_format(""))
        self.assertIsNone(member.validate_iban_format(None))

    def test_validate_iban_format_formats_valid_iban(self):
        """A valid IBAN is returned normalised (spaced/grouped) by the service."""
        member = self.create_test_member(first_name="Iban", last_name="Valid")
        formatted = member.validate_iban_format("NL13TEST0123456789")
        self.assertIsInstance(formatted, str)
        # Formatting strips/regroups but preserves the alphanumerics.
        self.assertEqual(formatted.replace(" ", ""), "NL13TEST0123456789")

    def test_validate_iban_format_rejects_invalid(self):
        """A structurally invalid IBAN raises a ValidationError."""
        member = self.create_test_member(first_name="Iban", last_name="Bad")
        with self.assertRaises(frappe.ValidationError):
            member.validate_iban_format("NOT-AN-IBAN")

    # ------------------------------------------------------------------
    # validate_bank_details - SEPA Direct Debit guards
    # ------------------------------------------------------------------
    def test_validate_bank_details_sepa_requires_iban(self):
        """SEPA Direct Debit with no IBAN raises a clear ValidationError."""
        member = self.create_test_member(first_name="Bank", last_name="NoIban")
        member.payment_method = "SEPA Direct Debit"
        member.iban = None
        member.bank_account_name = "Holder"
        with self.assertRaises(frappe.ValidationError) as ctx:
            member.validate_bank_details()
        # Pin the specific message so the IBAN vs holder branches can't be swapped.
        self.assertIn("IBAN is required", str(ctx.exception))

    def test_validate_bank_details_sepa_requires_account_holder(self):
        """SEPA Direct Debit with IBAN but no account holder name raises."""
        member = self.create_test_member(first_name="Bank", last_name="NoHolder")
        member.payment_method = "SEPA Direct Debit"
        member.iban = "NL13TEST0123456789"
        member.bank_account_name = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            member.validate_bank_details()
        self.assertIn("Account Holder Name is required", str(ctx.exception))

    def test_validate_bank_details_non_sepa_no_throw(self):
        """A non-SEPA member with no bank details validates cleanly (no throw)."""
        member = self.create_test_member(first_name="Bank", last_name="Transfer")
        member.payment_method = "Bank Transfer"
        member.iban = None
        # Should not raise.
        member.validate_bank_details()

    # ------------------------------------------------------------------
    # get_member_chapters / _is_chapter_management_enabled
    # ------------------------------------------------------------------
    def test_get_member_chapters_empty_for_unaffiliated(self):
        """A member in no chapter returns an empty list of chapters."""
        member = self.create_test_member(first_name="NoChap", last_name="Member")
        self.assertEqual(member.get_member_chapters(), [])

    def test_get_member_chapters_lists_enabled_membership(self):
        """get_member_chapters returns the parent chapter of enabled Chapter Member rows."""
        member = self.create_test_member(first_name="HasChap", last_name="Member")
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member.name, "enabled": 1, "chapter_join_date": frappe.utils.today()},
        )
        chapter.save()

        chapters = member.get_member_chapters()
        self.assertIn(chapter.name, chapters)

    def test_is_chapter_management_enabled_reflects_setting(self):
        """Pins the method to the real Verenigingen Settings flag, not just 'a bool'."""
        member = self.create_test_member(first_name="ChapMgmt", last_name="Flag")
        expected = frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        self.assertEqual(member._is_chapter_management_enabled(), expected)


def _row_is_locked_from_another_connection(doctype: str, name: str, timeout: int = 3) -> bool:
    """Return True if `doctype`/`name` cannot be locked from a second connection.

    Same idiom as tests/payment/test_history_manager_row_lock.py -- written
    locally rather than imported cross-file, since that module is a different
    issue's territory and could change independently of this one. Opens its
    own connection via frappe.db.create_connection() (the site's own driver
    and credentials; hand-rolling a raw pymysql/MySQLdb connection here works
    only by accident of which driver happens to be installed) and tries the
    same SELECT ... FOR UPDATE. Error 1205 (lock wait timeout) means somebody
    else holds it; an immediate result (or "no such row") means nobody does.
    """
    conn = frappe.db.create_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", (timeout,))
        try:
            cursor.execute(f"SELECT name FROM `tab{doctype}` WHERE name = %s FOR UPDATE", (name,))
            cursor.fetchall()
            return False
        except Exception as e:
            if e.args and e.args[0] == 1205:
                return True
            raise
    finally:
        conn.rollback()
        conn.close()


class TestGetInvoiceWithRetryDoesNotEndTheTransaction(EnhancedTestCase):
    """#421 (#411's sibling).

    ``_get_invoice_with_retry`` used to call ``frappe.db.commit()`` between
    retry attempts to get a fresh read view onto an invoice that another
    session had inserted. That commit ended the CALLER's whole transaction --
    flushing whatever it had not yet committed and discarding every savepoint
    MariaDB holds, exactly the shape #411 fixed in
    ``member_financial_history_manager.py``.

    A first attempt at this fix replaced the commit with
    ``frappe.get_doc(..., for_update=True)`` (a locking read), reasoning that
    InnoDB serves a locking read from the latest committed data, bypassing
    the transaction's snapshot. That IS true for visibility -- but a
    skeptical review measured, live, that ``FOR UPDATE`` on a not-yet-existing
    primary key takes a gap lock that (a) blocks the very INSERT the retry is
    waiting for and (b) deadlocks (1213) against
    ``MemberFinancialHistoryManager.add_or_update_entry``'s reverse lock
    order (Member first, then this method). A 1213 rolls back the whole
    transaction -- worse than the commit this issue exists to remove.

    The shipped fix takes no lock and ends nothing: a miss re-queues the same
    update for the batch processor's own later, genuinely-fresh-transaction
    drain (financial_history_batch_processor.py's 30s inline trigger or its
    "*/5 * * * *" safety-net cron), instead of trying to see the invoice here
    at all.
    """

    def _member_with_customer(self):
        member = self.create_test_member(
            first_name="Retry421", last_name=f"Case{frappe.generate_hash(length=6)}"
        )
        if not member.customer:
            member.create_customer()
            member.reload()
        return member

    def tearDown(self):
        # The reentrancy guard flag is request/thread-local (frappe.flags),
        # but leaving it set True would make the NEXT test's first miss
        # silently skip re-queuing too.
        frappe.flags._payment_mixin_invoice_retry_requeuing = False
        FinancialHistoryBatchProcessor.reset_queues()
        super().tearDown()

    # ------------------------------------------------------------------
    # A genuinely nonexistent invoice: no commit, no lock, re-queued once.
    # ------------------------------------------------------------------
    def test_missing_invoice_does_not_commit_and_requeues(self):
        """A savepoint is the one thing a commit cannot leave behind -- MariaDB
        drops all of them the instant a transaction ends. So RELEASE
        succeeding after the miss is proof no commit happened; there is no
        way to fake that while a commit is still there. This is the same
        invariant #411's own fix pinned for
        ``member_financial_history_manager.py``, applied to its sibling.
        """
        member = self._member_with_customer()

        # Keep the requeue from immediately re-draining inline (same
        # technique as test_the_inline_drain_does_not_commit in
        # test_payment_history_race_condition.py) so the queue assertion
        # below is deterministic regardless of what earlier tests in this
        # process did to _last_processed.
        FinancialHistoryBatchProcessor._last_processed["payments"] = frappe.utils.now()

        save_point = f"retry421_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(save_point)

        result = member._get_invoice_with_retry("ACC-SINV-421-NEVER-EXISTS")

        self.assertIsNone(result, "a nonexistent invoice must resolve to None")

        try:
            frappe.db.release_savepoint(save_point)
        except Exception as e:
            self.fail(
                f"the caller's savepoint {save_point} did not survive the miss ({e}) -- "
                "something inside _get_invoice_with_retry ended the transaction"
            )

        status = FinancialHistoryBatchProcessor.get_queue_status()
        self.assertGreaterEqual(
            status["payment_queue_size"],
            1,
            "the miss must re-queue the update for a later, fresh-transaction drain "
            "rather than dropping it silently",
        )

    # ------------------------------------------------------------------
    # The actual race: an invoice committed by a SEPARATE connection while our
    # transaction's snapshot already predates it. Proves the fix does NOT try
    # (and is not able) to see it here, and -- the property the locking-read
    # attempt got wrong -- takes no lock while failing to.
    # ------------------------------------------------------------------
    def test_defers_to_batch_queue_without_locking_when_invoice_committed_elsewhere(self):
        member = self._member_with_customer()

        # The Member/Customer only exist in THIS transaction until committed
        # -- the worker thread below opens a genuinely separate connection
        # and cannot see uncommitted rows at all. Commit to publish them (same
        # pattern as test_history_manager_row_lock.py's _committed() helper),
        # then one throwaway read to fix the NEW transaction's REPEATABLE READ
        # snapshot *before* the worker creates the invoice -- otherwise this
        # transaction's first read would be the control-check below, which
        # would happen only after the invoice already exists and would pass
        # vacuously "clean".
        frappe.db.commit()
        frappe.db.get_value("Member", member.name, "name")

        FinancialHistoryBatchProcessor._last_processed["payments"] = frappe.utils.now()

        # No frappe.db.commit() anywhere below in this (main) thread: the
        # snapshot above must stay fixed for the rest of the test.
        save_point = f"retry421_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(save_point)

        holder = {}
        site = frappe.local.site

        def _create_and_commit_on_another_connection():
            # A genuinely separate connection/transaction, per the pattern in
            # transaction_boundary_test_framework.py -- frappe.local is
            # thread-local, so this thread gets its own DB connection.
            frappe.init(site=site)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                invoice = self.create_test_sales_invoice(customer=member.customer, grand_total=42.0)
                frappe.db.commit()
                holder["invoice_name"] = invoice.name
            except Exception as e:  # noqa: BLE001 - surface it, don't lose it
                holder["error"] = repr(e)
            finally:
                frappe.destroy()

        t = threading.Thread(target=_create_and_commit_on_another_connection)
        t.start()
        t.join(60)
        self.assertFalse(t.is_alive(), "the worker thread hung")

        invoice_name = holder.get("invoice_name")
        self.assertTrue(invoice_name, f"the other connection failed: {holder.get('error')}")
        self.track_doc("Sales Invoice", invoice_name)

        # Control: a PLAIN read on OUR (older) transaction must NOT see the
        # row the other connection just committed -- this is what makes it a
        # real race. If this assertion fails, the rest of the test proves
        # nothing.
        with self.assertRaises(frappe.DoesNotExistError):
            frappe.get_doc("Sales Invoice", invoice_name)

        result = member._get_invoice_with_retry(invoice_name)

        self.assertIsNone(
            result,
            "must not try to see the invoice in THIS transaction -- that is the "
            "part the rejected for_update=True attempt got wrong",
        )

        # The property the rejected for_update=True design got wrong: no lock
        # left outstanding on the invoice row. If this fails, a concurrent
        # writer to this exact invoice (e.g. its own submit/cancel) would
        # block on us for the rest of our transaction.
        self.assertFalse(
            _row_is_locked_from_another_connection("Sales Invoice", invoice_name),
            "the miss must not leave any lock on the invoice row",
        )

        try:
            frappe.db.release_savepoint(save_point)
        except Exception as e:
            self.fail(f"the caller's savepoint did not survive the miss ({e})")

        status = FinancialHistoryBatchProcessor.get_queue_status()
        self.assertGreaterEqual(
            status["payment_queue_size"],
            1,
            "the miss must re-queue the update so a later, fresh-transaction drain "
            "(which WILL see the now-committed invoice) can finish the job",
        )

    # ------------------------------------------------------------------
    # Recursion safety: re-queuing from inside an already-requeued drain must
    # not recurse. This is what made the rejected for_update=True approach's
    # sibling risk real: queue_payment_update() can itself trigger an
    # immediate drain (FinancialHistoryBatchProcessor._maybe_process_batches()),
    # and if that drain reaches THIS method again for the same still-missing
    # invoice, requeuing a second time would recurse without end.
    # ------------------------------------------------------------------
    def test_reentrant_call_does_not_requeue_again(self):
        member = self._member_with_customer()

        frappe.flags._payment_mixin_invoice_retry_requeuing = True
        try:
            with patch(
                "verenigingen.utils.financial_history_batch_processor.queue_payment_update"
            ) as mock_queue:
                result = member._get_invoice_with_retry("ACC-SINV-421-NEVER-EXISTS-REENTRANT")
        finally:
            frappe.flags._payment_mixin_invoice_retry_requeuing = False

        self.assertIsNone(result)
        mock_queue.assert_not_called()

    # ------------------------------------------------------------------
    # Source guard, so a reintroduced frappe.db.commit() or FOR UPDATE fails
    # even if no behavioural test happens to exercise the exact race above.
    # ------------------------------------------------------------------
    def test_source_has_no_transaction_ending_call(self):
        """No ``frappe.db.commit()`` / ``rollback()`` / ``begin()`` anywhere in
        ``_get_invoice_with_retry``. Mirrors the AST guard #422 added for
        ``financial_history_batch_processor.py`` (test_financial_batch_transaction_scope.py) --
        written independently here rather than imported cross-file, since that
        module is a different issue's territory.
        """
        from verenigingen.verenigingen.doctype.member.mixins import payment_mixin as mod

        tree = ast.parse(inspect.getsource(mod))
        target = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_get_invoice_with_retry"
        )

        offenders = []
        for call in ast.walk(target):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in ("commit", "rollback", "begin"):
                continue
            value = call.func.value
            is_frappe_db = isinstance(value, ast.Attribute) and value.attr == "db"
            if is_frappe_db:
                offenders.append(f"{call.lineno}: frappe.db.{call.func.attr}()")

        self.assertEqual(
            offenders,
            [],
            f"_get_invoice_with_retry must never end the caller's transaction: {offenders}",
        )

    def test_source_does_not_take_a_locking_read(self):
        """AST guard against `for_update=True` creeping back in -- the exact
        mechanism a skeptical review measured to deadlock and gap-lock.
        """
        from verenigingen.verenigingen.doctype.member.mixins import payment_mixin as mod

        tree = ast.parse(inspect.getsource(mod))
        target = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_get_invoice_with_retry"
        )

        offenders = [
            kw.lineno
            for call in ast.walk(target)
            if isinstance(call, ast.Call)
            for kw in call.keywords
            if kw.arg == "for_update" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
        ]

        self.assertEqual(
            offenders,
            [],
            f"_get_invoice_with_retry must not take a locking read (measured to gap-lock "
            f"and deadlock): lines {offenders}",
        )
