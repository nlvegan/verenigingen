"""
#2976: ``ensure_bank_record`` / ``create_bank_account`` (the #2126 creators) must let a
deadlock, a lock-wait timeout and a duplicate key escape as THEMSELVES. Wrapping them in
``BankAccountCreationError`` hides them from ``is_deadlock_error`` and from every caller that
retries on the type, exactly the shape #2923 fixed for ``create_party_bank_account``.

An ordinary failure must still become ``BankAccountCreationError`` (control).

Usage:
    bench --site test_site_11 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_bank_helper_nonresumable_2976
"""

import contextlib
from unittest import mock

import frappe

from verenigingen.tests.e_boekhouden.test_coa_bank_account_contract_2126 import _CoaBankBase
from verenigingen.tests.support import non_resumable_errors
from verenigingen.utils import bank_account_creation
from verenigingen.utils.bank_account_creation import (
    BankAccountCreationError,
    create_bank_account,
    ensure_bank_record,
)
from verenigingen.utils.retry_utilities import is_deadlock_error


@contextlib.contextmanager
def _driver_raises_on_insert_into(table, driver_error):
    """Raise ``driver_error`` from the DB cursor itself on ``INSERT INTO `tab<table>```, so
    frappe's own converter decides the exception type (1213 -> QueryDeadlockError)."""
    cursor_class = type(frappe.db._cursor)
    real_execute = cursor_class.execute

    def execute(self, query, *args, **kwargs):
        if f"INSERT INTO `tab{table}`" in str(query):
            raise driver_error
        return real_execute(self, query, *args, **kwargs)

    with mock.patch.object(cursor_class, "execute", execute):
        yield


class TestBankHelperLetsDbErrorsEscape2976(_CoaBankBase):
    def _new_bank_name(self):
        return f"Bank 2976 {frappe.generate_hash(length=8)}"

    def _create_account(self):
        gl, _ = self._gl_account("Escape 2976")
        bank = ensure_bank_record("Triodos Bank")
        return dict(
            gl_account=gl.name,
            bank=bank,
            account_name=f"Escape 2976 {frappe.generate_hash(length=6)}",
            company=self.company,
            currency="EUR",
        )

    def test_a_driver_1213_on_the_bank_insert_stays_a_deadlock(self):
        driver_error = frappe.db.OperationalError(1213, "Deadlock found when trying to get lock")
        with _driver_raises_on_insert_into("Bank", driver_error):
            with self.assertRaises(frappe.QueryDeadlockError) as caught:
                ensure_bank_record(self._new_bank_name())
        self.assertTrue(is_deadlock_error(caught.exception))

    def test_a_driver_1213_on_the_bank_account_insert_stays_a_deadlock(self):
        kwargs = self._create_account()
        driver_error = frappe.db.OperationalError(1213, "Deadlock found when trying to get lock")
        with _driver_raises_on_insert_into("Bank Account", driver_error):
            with self.assertRaises(frappe.QueryDeadlockError) as caught:
                create_bank_account(**kwargs)
        self.assertTrue(is_deadlock_error(caught.exception))

    def test_a_lock_wait_timeout_keeps_its_type_on_both_creators(self):
        kwargs = self._create_account()
        for table, call in (
            ("Bank", lambda: ensure_bank_record(self._new_bank_name())),
            ("Bank Account", lambda: create_bank_account(**kwargs)),
        ):
            with self.subTest(table=table):
                driver_error = frappe.db.OperationalError(1205, "Lock wait timeout exceeded")
                with _driver_raises_on_insert_into(table, driver_error):
                    with self.assertRaises(frappe.QueryTimeoutError):
                        call()

    def test_a_duplicate_entry_keeps_its_type_on_both_creators(self):
        """Injected at ``secure_document_operation`` (which itself turns a plain duplicate
        into ``success=False``); this pins the helper's own handler, not the writer's."""
        kwargs = self._create_account()
        for call in (lambda: ensure_bank_record(self._new_bank_name()), lambda: create_bank_account(**kwargs)):
            with mock.patch.object(
                bank_account_creation,
                "secure_document_operation",
                side_effect=frappe.DuplicateEntryError("Bank", "x", Exception("dup")),
            ):
                with self.assertRaises(frappe.DuplicateEntryError):
                    call()

    def test_the_injected_nonresumable_class_propagates_from_the_helper(self):
        for error in (non_resumable_errors.deadlock(), non_resumable_errors.lock_wait_timeout()):
            with mock.patch.object(bank_account_creation, "secure_document_operation", side_effect=error):
                with self.assertRaises(type(error)):
                    ensure_bank_record(self._new_bank_name())

    def test_control_an_ordinary_failure_is_still_a_bank_account_creation_error(self):
        self.expectErrorLog("Bank")
        with mock.patch.object(
            bank_account_creation, "secure_document_operation", side_effect=ValueError("boom")
        ):
            with self.assertRaises(BankAccountCreationError) as caught:
                ensure_bank_record(self._new_bank_name())
        self.assertIn("boom", caught.exception.message)

    def test_the_wrapped_error_chains_its_cause(self):
        self.expectErrorLog("Bank")
        with mock.patch.object(
            bank_account_creation, "secure_document_operation", side_effect=ValueError("boom")
        ):
            with self.assertRaises(BankAccountCreationError) as caught:
                ensure_bank_record(self._new_bank_name())
        self.assertIsInstance(caught.exception.__cause__, ValueError)
