"""``@handle_api_error`` must not turn a non-resumable DB error into a return value (#481).

#470 made forty-four handlers under ``services/termination/`` re-raise a 1205/1213, and #475
fixed the five frames above them that converted the class back into an ordinary failure. This
is the sixth boundary, and it is not on the termination path at all: the shared
``@handle_api_error`` decorator ends in ``except Exception``, so it applies to every endpoint
wearing it -- **50 whitelisted endpoints** on develop @ ``b0cd9ac6`` (AST census; the 68 in
the issue counted ``scripts/optimization/*`` generators, a validator that greps for the
decorator, a template and tests).

Two things went wrong at once, and only one of them is about the class:

1. **No rollback.** With the exception converted to a return value nothing propagates, so the
   request ends on its *success* path and Frappe commits whatever the endpoint already wrote.
   Six of the 50 write in-frame, ``membership_application.submit_application`` (the public
   form) with a ``frappe.db.commit()`` of its own.
2. **The class is lost.** ``QueryDeadlockError`` and ``QueryTimeoutError`` derive from
   ``Exception`` and are **not** ``ValidationError`` subclasses (measured), so they fall past
   the two typed branches into the catch-all and come back as
   ``OperationResult(success=False, http_status=500)`` -- delivered, separately, as HTTP 200.

**Why a guard here is not a no-op, unlike #475 boundary 2.** Every frame that can sit above
this decorator was checked before writing these tests: the ``api_security_framework`` wrapper
that backs ``critical_api``/``high_security_api``/``standard_api``/``public_api`` logs its
audit event and **re-raises** (``api_security_framework.py:1044``);
``_flatten_operation_result`` transforms the returned value only; ``performance_monitor``,
``require_roles`` and ``validate_with_schema`` do not catch the wrapped call. So the class
really does reach the caller, and ``test_the_class_survives_the_security_wrapper_too`` drives
that composition rather than trusting the reading.

**What these tests inject is the exception CLASS, not contention** -- the same caveat as the
#470 and #475 modules. No real 1213 is produced here.

Every non-resumable test has an ordinary-exception twin. Without one each assertion is
equally consistent with "the decorator now propagates everything", which is a different and
wrong change: the structured failure dict is the decorator's entire purpose for ordinary
errors, and 44 endpoints' callers read it.
"""

import frappe

from verenigingen.tests.support.non_resumable_errors import deadlock as _deadlock
from verenigingen.tests.support.non_resumable_errors import lock_wait_timeout as _timeout
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import handle_api_error


def _endpoint_raising(error):
    """A minimal endpoint wearing only the decorator under test."""

    @handle_api_error
    def endpoint():
        raise error

    return endpoint


class TestHandleApiErrorKeepsTheClass(VereningingenTestCase):
    """The class must survive the decorator instead of becoming an OperationResult."""

    def setUp(self):
        super().setUp()
        # The guard logs through the decorator's own log_error, preserving the function /
        # args / traceback context the request-boundary log would not carry.
        self.expectErrorLog("QueryDeadlockError", "QueryTimeoutError", "endpoint")

    def test_a_deadlock_leaves_the_decorator_as_itself(self):
        with self.assertRaises(frappe.QueryDeadlockError):
            _endpoint_raising(_deadlock())()

    def test_a_lock_wait_timeout_leaves_the_decorator_as_itself(self):
        """1205 is the other member of the class, and the half-applied one."""
        with self.assertRaises(frappe.QueryTimeoutError):
            _endpoint_raising(_timeout())()

    def test_an_ordinary_exception_still_returns_the_structured_failure(self):
        """CONTROL. The catch-all is load-bearing for every other error and 50 endpoints'
        callers read ``success``/``error_code`` out of it. Without this control the two tests
        above are equally consistent with the decorator having stopped catching anything."""
        result = _endpoint_raising(RuntimeError("ordinary failure"))()

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SYSTEM_ERROR")
        self.assertEqual(result.http_status, 500)

    def test_a_validation_error_still_returns_its_own_structured_failure(self):
        """CONTROL for the guard's POSITION. ``QueryDeadlockError`` is not a
        ``ValidationError``, so a guard placed above that branch cannot steal from it -- this
        pins that, because a guard written as ``except Exception`` would pass every test above
        and break this one."""
        result = _endpoint_raising(frappe.ValidationError("not valid"))()

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "VALIDATION_ERROR")
        self.assertEqual(result.http_status, 400)


class TestHandleApiErrorAbandonsTheHalfAppliedWork(VereningingenTestCase):
    """The durability half, which is the one an operator actually feels.

    Asserted on a real persisted row rather than on a call to ``frappe.db.rollback``: the
    defect is that the work *survives*, and a mock of the rollback would be satisfied by a
    guard that called it on the wrong connection or after the commit.
    """

    def setUp(self):
        super().setUp()
        self.expectErrorLog("QueryDeadlockError", "endpoint")

    def test_a_row_written_before_the_deadlock_does_not_survive_the_decorator(self):
        marker = f"481-half-applied-{frappe.generate_hash(length=8)}"

        @handle_api_error
        def endpoint():
            frappe.get_doc({"doctype": "ToDo", "description": marker}).insert(ignore_permissions=True)
            # Visible to this connection immediately; only a rollback removes it.
            assert frappe.db.exists("ToDo", {"description": marker})
            raise _deadlock()

        with self.assertRaises(frappe.QueryDeadlockError):
            endpoint()

        self.assertFalse(
            frappe.db.exists("ToDo", {"description": marker}),
            "the endpoint's half-applied write survived the guard, so Frappe would commit it "
            "at request end",
        )

    def test_an_ordinary_exception_does_not_discard_the_transaction(self):
        """CONTROL. Rolling back on every error would silently undo work for the 44 endpoints
        that return a structured failure and keep going -- a much larger change than #481 asks
        for, and one that no assertion above would notice."""
        marker = f"481-ordinary-{frappe.generate_hash(length=8)}"

        @handle_api_error
        def endpoint():
            frappe.get_doc({"doctype": "ToDo", "description": marker}).insert(ignore_permissions=True)
            raise RuntimeError("ordinary failure")

        result = endpoint()

        self.assertFalse(result.success)
        self.assertTrue(
            frappe.db.exists("ToDo", {"description": marker}),
            "an ordinary error must leave the transaction alone",
        )
        frappe.db.rollback()


class TestTheClassSurvivesTheWholeDecoratorStack(VereningingenTestCase):
    """Composition, not frames. #475 boundaries 1 and 2 were each individually 'fixed' by a
    guard that the other frame then masked; a test per frame would not have caught it. The
    50 endpoints all sit inside the security framework wrapper, so that is the stack to drive.
    """

    def setUp(self):
        super().setUp()
        self.expectErrorLog("QueryDeadlockError", "endpoint")

    def test_the_class_survives_the_security_wrapper_too(self):
        from verenigingen.utils.security.api_security_framework import OperationType, critical_api

        @critical_api(operation_type=OperationType.FINANCIAL)
        @handle_api_error
        def endpoint():
            raise _deadlock()

        with self.assertRaises(frappe.QueryDeadlockError):
            endpoint()
