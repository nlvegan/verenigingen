"""A non-resumable DB error stays recognisable at the termination reporting boundaries (#475).

#470 fixed *whether* a termination abandons its unit of work on a 1205/1213: forty-four
handlers under ``services/termination/`` now re-raise. This module is about *how* that
failure is then reported. Five frames above the fix converted the error back into something
a caller cannot distinguish from an ordinary failure, which puts the guarantee back where it
started one frame higher up.

The five, and what each did before this change::

    TerminationExecutionService.execute      frappe.throw()  -> ValidationError, class lost
    MijnRoodTerminationSyncService           except Exception -> {"success": False}
    api/termination_api                      except Exception -> {"success": False}, HTTP 200
    utils/safe_child_table_update            except Exception -> HistoryOperationResult(False)
    api/suspension_api (two frames)          except Exception -> per-member dict, loop continues

``QueryDeadlockError`` and ``QueryTimeoutError`` derive directly from ``Exception`` and are
**not** subclasses of ``ValidationError`` (measured, not read) -- which is why boundary 1's
``frappe.throw`` genuinely destroys the class rather than merely renaming it, and why the
guards below can sit above the existing ``frappe.ValidationError`` handlers without changing
which of those ever fires.

**Boundaries 1 and 2 are coupled, and the order matters.** Fixing MijnRood alone is a no-op:
the execution service masks the class one frame below it, so an
``except NON_RESUMABLE_DB_ERRORS`` clause there could never match. That is why they land
together, and why ``test_the_class_survives_the_service_so_mijnrood_can_see_it`` asserts the
composition rather than each half separately.

**What these tests inject is the exception CLASS, not contention** -- the same caveat as the
#470 module. No real 1213 is produced, so nothing here shows InnoDB picking this transaction
as the victim. What is demonstrated is which frame catches, what it hands its caller, and
what runs afterwards. Every non-resumable test has an ordinary-``Exception`` twin, because
without one each assertion is equally consistent with "this frame now propagates everything",
which is a different and wrong change: the structured failure dicts are load-bearing for
ordinary errors and every control below pins one.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.support.termination_request import create_termination_request
from verenigingen.tests.utils.base import VereningingenTestCase


def _deadlock():
    return frappe.QueryDeadlockError("Deadlock found when trying to get lock; try restarting transaction")


def _timeout():
    return frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")


class TestTerminationExecutionServiceReportsTheClass(VereningingenTestCase):
    """Boundary 1. ``_handle_error`` ends in ``frappe.throw``, which raises ValidationError."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        self.request = create_termination_request(self, self.member.name, "reporting boundary (#475)")
        self.request.db_set("status", "Approved")
        frappe.db.commit()
        self.addCleanup(frappe.db.commit)

    def _service_over(self, error):
        """Patch the operation list's execution, leaving execute()'s own handler real."""
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        return TerminationExecutionService(), patch.object(
            TerminationExecutionService, "execute_system_updates", side_effect=error
        )

    def test_a_deadlock_leaves_the_service_as_itself(self):
        service, exploding = self._service_over(_deadlock())
        with exploding:
            with self.assertRaises(frappe.QueryDeadlockError):
                service.execute(self.request)

    def test_a_lock_wait_timeout_leaves_the_service_as_itself(self):
        """1205 is the other member of the class, and the one #475 notes is reachable today."""
        service, exploding = self._service_over(_timeout())
        with exploding:
            with self.assertRaises(frappe.QueryTimeoutError):
                service.execute(self.request)

    def test_an_ordinary_failure_still_leaves_the_service_as_a_validation_error(self):
        """CONTROL. Admins get one uniform, translated ValidationError for ordinary failures
        and that must survive -- without this the tests above are equally consistent with
        "the service stopped calling _handle_error at all"."""
        service, exploding = self._service_over(Exception("ordinary failure"))
        with exploding:
            with self.assertRaises(frappe.ValidationError):
                service.execute(self.request)

    def test_the_status_is_still_reverted_for_retry_after_a_deadlock(self):
        """The recovery ``_handle_error`` exists to do must not be lost by re-raising earlier.

        Reverting to Approved is what enables the operator's retry; a guard that returned
        before the recovery would trade one defect for another.

        The failure has to land *after* ``status = "Executed"`` is saved, or there is nothing
        to revert and the assertion would pass on a service that never recovered at all. So
        the audit entry that follows the save is what explodes -- and only the success one:
        ``_handle_error`` writes its own "Execution Failed" entry through the same method, and
        exploding on that too would break the recovery rather than test it.
        """
        from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (  # noqa: E501
            MembershipTerminationRequest,
        )

        real_add_audit_entry = MembershipTerminationRequest.add_audit_entry

        def explode_on_the_success_entry(doc, action, *args, **kwargs):
            if action == "Termination Executed":
                raise _deadlock()
            return real_add_audit_entry(doc, action, *args, **kwargs)

        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        service = TerminationExecutionService()
        succeeding_updates = patch.object(
            TerminationExecutionService,
            "execute_system_updates",
            return_value={"actions_taken": [], "errors": []},
        )
        with succeeding_updates, patch.object(
            MembershipTerminationRequest, "add_audit_entry", explode_on_the_success_entry
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                service.execute(self.request)

        self.assertEqual(
            frappe.db.get_value("Membership Termination Request", self.request.name, "status"),
            "Approved",
            "the status revert that enables retry was lost when the guard re-raised",
        )


class TestMijnRoodSyncReportsTheClass(VereningingenTestCase):
    """Boundary 2, and the one #475 calls the most important.

    ``dispatcher.apply_event`` was deliberately given an ``except NON_RESUMABLE_DB_ERRORS``
    clause that rolls back, records and re-raises, with a comment saying every such clause
    below it re-raises so this frame must too. That clause could never fire for the
    termination path, because this service converted the exception into a return value one
    frame below it -- and the dispatcher then took its **success-path** branch:
    ``event.save()`` followed by ``frappe.db.commit()``, making the half-applied termination
    durable. Not the generic ``except`` branch, which at least rolls back.
    """

    def setUp(self):
        super().setUp()
        self.service = self._sync_service()

    @staticmethod
    def _sync_service():
        from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
            MijnRoodTerminationSyncService,
        )

        return MijnRoodTerminationSyncService()

    def _handle_over(self, error):
        """Drive ``_check_and_handle_termination`` to the execute() call and explode there."""
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        member = self.create_test_member()
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "event_type": "Changed",
                "status": "Approved",
                "mijnrood_table": "admin_member",
                "mijnrood_row_id": 1,
                "linked_member": member.name,
            }
        )
        event.insert()
        self.track_doc("MijnRood Sync Event", event.name)

        changed = [{"field": "current_membership_status_id", "old": self._active_id(), "new": self._terminated_id()}]
        return (
            event,
            changed,
            patch.object(TerminationExecutionService, "execute", side_effect=error),
        )

    @staticmethod
    def _active_id():
        from verenigingen.mijnrood_sync.field_mapping import get_active_status_ids

        return sorted(get_active_status_ids())[0]

    @staticmethod
    def _terminated_id():
        from verenigingen.mijnrood_sync.field_mapping import get_terminated_status_ids

        return sorted(get_terminated_status_ids())[0]

    def test_a_deadlock_propagates_so_the_dispatchers_clause_can_fire(self):
        event, changed, exploding = self._handle_over(_deadlock())
        with exploding:
            with self.assertRaises(frappe.QueryDeadlockError):
                self.service._check_and_handle_termination(event, {}, {"id": 1}, changed)

    def test_the_class_survives_the_service_so_mijnrood_can_see_it(self):
        """The composition, through BOTH real frames -- the point of landing them together.

        The two tests above patch ``TerminationExecutionService.execute`` itself, so they
        pin this frame's handler while saying nothing about whether a real 1213 ever
        arrives here as itself. It does not, unless boundary 1 is also fixed: the service's
        ``_handle_error`` ends in ``frappe.throw``. So this drives the genuine service --
        exploding inside ``execute_system_updates``, below its handler -- and asserts the
        class is still a deadlock two frames later. Revert either fix alone and this reddens.
        """
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        event, changed, _unused = self._handle_over(_deadlock())
        with patch.object(
            TerminationExecutionService, "execute_system_updates", side_effect=_deadlock()
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                self.service._check_and_handle_termination(event, {}, {"id": 1}, changed)

    def test_an_ordinary_execution_failure_is_still_reported_as_a_result_dict(self):
        """CONTROL. A failed execution that is not a DB error must still leave the created
        request recorded and let the dispatcher mark the event -- that is the whole reason
        this handler exists."""
        event, changed, exploding = self._handle_over(Exception("ordinary failure"))
        with exploding:
            result = self.service._check_and_handle_termination(event, {}, {"id": 1}, changed)

        self.assertIsNotNone(result, "the ordinary failure stopped being reported at all")
        self.assertFalse(result["success"])
        self.assertIn("execution failed", result["message"])


class TestTerminationApiReportsTheClass(VereningingenTestCase):
    """Boundary 3. ``@critical_api`` logs and re-raises (measured), so a raise here really
    does reach Frappe rather than being converted by the decorator stack."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        frappe.db.commit()
        self.addCleanup(frappe.db.commit)

    @staticmethod
    def _exploding_status_update(error):
        return patch(
            "verenigingen.utils.termination_integration.update_member_status_safe",
            side_effect=error,
        )

    def _terminate(self):
        from verenigingen.api.termination_api import execute_safe_termination

        return execute_safe_termination(self.member.name, "Voluntary", today())

    def test_a_deadlock_is_not_answered_with_a_200(self):
        with self._exploding_status_update(_deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._terminate()

    def test_an_ordinary_failure_is_still_answered_with_a_structured_result(self):
        """CONTROL. The structured failure dict is this endpoint's contract for ordinary
        errors and is what the desk UI renders."""
        with self._exploding_status_update(Exception("ordinary failure")):
            result = self._terminate()

        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestSafeChildTableUpdateReportsTheClass(VereningingenTestCase):
    """Boundary 4. ``BaseHistoryManager._with_doc`` was given an
    ``except NON_RESUMABLE_DB_ERRORS: raise`` by #460 precisely so callers would see these --
    but the swallow sits *outside* that guard, in the helper ``_with_doc`` delegates the
    write to, so it never fired for that call.
    """

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()

    def _update_over(self, error):
        from verenigingen.utils.history_manager_utils import safe_child_table_update

        doc = frappe.get_doc("Member", self.member.name)
        return doc, safe_child_table_update, patch.object(
            type(doc), "update_child_table", side_effect=error
        )

    def test_a_deadlock_writing_the_child_table_propagates(self):
        doc, update, exploding = self._update_over(_deadlock())
        with exploding:
            with self.assertRaises(frappe.QueryDeadlockError):
                update(doc, "payment_history", "deadlock (#475)", "Member:write")

    def test_an_ordinary_write_failure_is_still_a_failed_result(self):
        """CONTROL. Returning ``HistoryOperationResult(success=False)`` for ordinary errors is
        what every history caller is written against."""
        doc, update, exploding = self._update_over(Exception("ordinary failure"))
        with exploding:
            result = update(doc, "payment_history", "control", "Member:write")

        self.assertFalse(result.success)


class TestBulkSuspensionStopsOnTheClass(VereningingenTestCase):
    """Boundary 5, and the #470 shape one frame up: a serial loop that keeps suspending the
    remaining members on a transaction the server has already discarded.

    Three frames catch here, not the one #475 names -- ``process_member_suspension``,
    ``bulk_suspend_members``, and the shared ``@handle_api_error`` decorator. The first two
    are fixed here; the decorator is app-wide (68 endpoints) and is tracked separately, which
    is why these tests assert on **which members were attempted** rather than on the returned
    envelope. The loop stopping is the behaviour that was asked for; what the decorator then
    renders is a different question.
    """

    def setUp(self):
        super().setUp()
        self.members = [self.create_test_member() for _ in range(3)]
        frappe.db.commit()
        self.addCleanup(frappe.db.commit)

    def _run_with_second_member_failing(self, error):
        """Return the member names the loop actually attempted."""
        from verenigingen.api import suspension_api

        attempted = []

        def spy(member_name, **_kwargs):
            attempted.append(member_name)
            if member_name == self.members[1].name:
                raise error
            return {"success": True, "actions_taken": []}

        names = [m.name for m in self.members]
        with patch(
            "verenigingen.utils.termination_integration.suspend_member_safe", side_effect=spy
        ):
            try:
                suspension_api.bulk_suspend_members(names, "reporting boundary (#475)")
            except frappe.QueryDeadlockError:
                pass
        return attempted

    def test_a_deadlock_stops_the_bulk_loop(self):
        attempted = self._run_with_second_member_failing(_deadlock())

        self.assertEqual(
            attempted,
            [self.members[0].name, self.members[1].name],
            "the loop kept suspending members after a non-resumable error",
        )

    def test_the_bulk_frame_rolls_back_before_it_logs(self):
        """Binds the OUTER frame, which the loop-stopping test above does not reach.

        Mutation found this gap: reverting the outer guard alone left ``attempted``
        unchanged -- the inner guard already stopped the loop -- so that test passes on it
        and the guard would have been held by nothing.

        What the outer frame actually owns is the rollback: without it the
        ``frappe.log_error`` below it is issued on the discarded transaction, and Frappe
        commits the partial suspensions at request end.

        ``@handle_api_error`` still converts the re-raise into an OperationResult one frame
        further up, so the exception is not observable from the public name; the rollback is.
        """
        from verenigingen.api import suspension_api

        rollbacks = []
        real_rollback = frappe.db.rollback

        def spy_rollback(*args, **kwargs):
            rollbacks.append(args)
            return real_rollback(*args, **kwargs)

        def explode(member_name, **_kwargs):
            raise _deadlock()

        names = [m.name for m in self.members]
        with patch(
            "verenigingen.utils.termination_integration.suspend_member_safe", side_effect=explode
        ):
            with patch.object(frappe.db, "rollback", spy_rollback):
                suspension_api.bulk_suspend_members(names, "reporting boundary (#475)")

        self.assertTrue(
            rollbacks,
            "the bulk frame logged and returned without ending the discarded transaction",
        )

    def test_an_ordinary_failure_still_lets_the_bulk_loop_finish(self):
        """CONTROL. One member failing for an ordinary reason must not abort the other 49 --
        that per-member isolation is the point of the endpoint."""
        attempted = self._run_with_second_member_failing(Exception("ordinary failure"))

        self.assertEqual(
            attempted,
            [m.name for m in self.members],
            "per-member isolation was lost for an ordinary exception",
        )
