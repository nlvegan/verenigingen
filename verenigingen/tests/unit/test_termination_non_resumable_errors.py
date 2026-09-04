"""A deadlock during a termination abandons the unit of work; it is never recorded and resumed (#470).

``verenigingen/utils/transaction_errors.py`` states the rule: ``QueryDeadlockError`` (1213)
and ``QueryTimeoutError`` (1205) must propagate to whoever owns the transaction boundary,
because a handler that catches one, records it and carries on is continuing against state
the server has already thrown away.

The termination stack broke that rule at every layer. #470 named one handler --
``TerminationExecutor.execute`` -- but the executor is not where a 1213 arrives. Each of the
fourteen operations delegates to a ``*_safe`` helper in ``termination_integration``, and
those catch first (illustrative -- both lines marked below are now fixed, #470 and #476
respectively; kept here because it is still the shape that motivates every test below)::

    try:
        chapter_doc.save()              # the Volunteer/Member lock from #459
    except Exception as e:
        frappe.logger().error(...)      # <- 1213 lands here (re-raises since #470)
    # loop continues, saving further chapters on the discarded transaction
    return positions_ended              # <- caller records an ACTION, not an error
                                         #    (excludes unsaved chapters since #476)

So the executor's handler never fires, and re-raising there alone would have changed
nothing on the path most likely to deadlock. That is the shape #459 kept producing: the
issue names one instance of a class.

**What these tests inject is the exception CLASS, not contention.** No real 1213 is
produced, so nothing here demonstrates that InnoDB picks this transaction as the victim,
and nothing here measures what a half-applied termination looks like on disk. What is
demonstrated is which handler catches the error and which operations run after it. The
controls below are what make that a claim about the error class rather than about
exceptions in general: every non-resumable test has an ordinary-``Exception`` twin
asserting the log-and-continue behaviour is still intact.
"""

import ast
import pathlib
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.support.non_resumable_ast import (
    catches_bare_exception,
    reraises_non_resumable,
)
from verenigingen.tests.support.non_resumable_errors import deadlock as _deadlock
from verenigingen.tests.support.termination_request import create_termination_request
from verenigingen.tests.utils.base import VereningingenTestCase

# What `update_member_status_safe`'s status_mapping gives a Voluntary termination. Asserting
# on the literal rather than importing the mapping is deliberate: a test that derives the
# expected value from the code under test cannot notice the code changing it.
TERMINATED_STATUS = "Quit"

TERMINATION_PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "services" / "termination"

# A handler may legitimately swallow a non-resumable error when it is already running
# *after* the failure -- error recovery and savepoint cleanup, where re-raising would
# replace the original error with a secondary one. Those sites carry this marker.
EXEMPTION_MARKER = "non-resumable-ok:"


class TestTerminationAbandonsOnNonResumableError(VereningingenTestCase):
    """The behavioural half: which handler catches, and what runs afterwards."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        self.volunteer = self.create_test_volunteer(member=self.member.name)
        self.chapter = self.create_test_chapter()
        self.role = self.create_test_chapter_role()

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("members", {"member": self.member.name, "enabled": 1})
        chapter.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": self.role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save()
        frappe.db.commit()
        self.addCleanup(frappe.db.commit)

        self.request = create_termination_request(self, self.member.name, "non-resumable swallow (#470)")

    def _exploding_chapter_save(self, error):
        """Patch the Chapter save the termination helpers make.

        ``chapter_doc.save()`` is the call #459 established takes both row locks, which
        makes it the realistic deadlock site.

        It is reached inside the **middle** of ``end_board_positions_safe``'s three nested
        handlers -- the loop that saves the chapters. The innermost handler wraps the
        marking loop, which only does ``frappe.get_doc``, and single-guard mutation showed
        it has no behavioural coverage at all: the ratchet is the only thing holding it.
        Same for ``disable_chapter_memberships_safe``'s savepoint block, where operation 4
        re-raises first. Defence in depth, not tested depth -- said plainly here so the
        mutation table is not read as covering more than it does.
        """
        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        return patch.object(Chapter, "save", side_effect=error)

    # -- layer 1: the innermost helper ------------------------------------------------

    def test_a_deadlock_saving_a_chapter_propagates_out_of_end_board_positions_safe(self):
        """The helper #470 does not mention, and the one that swallows first."""
        from verenigingen.services.termination.termination_integration import end_board_positions_safe

        with self._exploding_chapter_save(_deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                end_board_positions_safe(self.member.name, today(), "deadlock (#470)")

    def test_an_ordinary_failure_saving_a_chapter_is_still_swallowed_by_the_helper(self):
        """CONTROL. Without this, the test above is equally consistent with "the helper now
        propagates everything", which is a different and wrong change."""
        from verenigingen.services.termination.termination_integration import end_board_positions_safe

        with self._exploding_chapter_save(Exception("ordinary failure")):
            # The counter used to be incremented in the marking loop, before the save that
            # failed, so the helper reported a board position ended that was never
            # persisted (#476). It must still swallow the ordinary exception (that is what
            # this control asserts, alongside the deadlock test above), but the count it
            # returns must reflect only chapters that actually saved -- zero, here.
            result = end_board_positions_safe(self.member.name, today(), "control")
            self.assertEqual(result, 0)

    def test_a_successful_save_reports_the_actual_number_of_positions_ended(self):
        """CONTROL for #476. Without this, the failure-returns-0 assertion above is equally
        consistent with a degenerate fix that always returns 0 regardless of outcome -- this
        asserts the success path still reports the real count. It does NOT distinguish the
        shipped per-chapter counting from an all-or-nothing strategy (return the total only
        if every chapter saved) -- see
        test_only_the_chapter_that_actually_saved_contributes_to_the_count for that."""
        from verenigingen.services.termination.termination_integration import end_board_positions_safe

        result = end_board_positions_safe(self.member.name, today(), "success")
        self.assertEqual(result, 1)

    def test_two_active_board_roles_in_one_chapter_both_count(self):
        """Pins the per-chapter accumulation in ``positions_marked_by_chapter``: the same
        volunteer holding two active board roles at one chapter must both be counted, not
        just the last one matched."""
        from verenigingen.services.termination.termination_integration import end_board_positions_safe
        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        second_role = self.create_test_chapter_role()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": second_role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        frappe.db.commit()

        result = end_board_positions_safe(self.member.name, today(), "two roles, one chapter")

        self.assertEqual(result, 2)
        chapter_doc.reload()
        self.assertTrue(all(bm.is_active == 0 for bm in chapter_doc.board_members))

    def test_only_the_chapter_that_actually_saved_contributes_to_the_count(self):
        """DISCRIMINATING for #476. The single-chapter tests above cannot tell the shipped
        per-chapter counting apart from a degenerate all-or-nothing strategy (return 0 if
        ANY chapter fails, else the total) -- for one chapter the two are the same function.
        With two chapters they diverge: this asserts the count is exactly the surviving
        chapter's positions (1), not 0 (all-or-nothing) and not 2 (the pre-#476 bug)."""
        from verenigingen.services.termination.termination_integration import end_board_positions_safe
        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        other_chapter = self.create_test_chapter()
        other_role = self.create_test_chapter_role()
        other_volunteer_membership = frappe.get_doc("Chapter", other_chapter.name)
        other_volunteer_membership.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": other_role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        other_volunteer_membership.save()
        frappe.db.commit()

        failing_chapter_name = self.chapter.name
        real_save = Chapter.save

        def fail_only_the_first_chapter(chapter_doc, *args, **kwargs):
            if chapter_doc.name == failing_chapter_name:
                raise Exception("ordinary failure")
            return real_save(chapter_doc, *args, **kwargs)

        # autospec=True is load-bearing here: without it the patched attribute is a plain
        # MagicMock, which is not a descriptor, so `chapter_doc.save()` never passes `self`
        # and the two chapters cannot be told apart.
        with patch.object(Chapter, "save", autospec=True, side_effect=fail_only_the_first_chapter):
            result = end_board_positions_safe(self.member.name, today(), "mixed")

        self.assertEqual(result, 1)

        failed_chapter_doc = frappe.get_doc("Chapter", failing_chapter_name)
        self.assertEqual(failed_chapter_doc.board_members[0].is_active, 1)
        other_volunteer_membership.reload()
        self.assertEqual(other_volunteer_membership.board_members[0].is_active, 0)

    # -- layer 2: the operation that owns the commit point ----------------------------

    def test_a_deadlock_recalculating_duration_propagates_out_of_the_final_operation(self):
        """``UpdateMemberStatusOperation`` swallows inside itself, so the executor's handler
        cannot see it however it is written."""
        from verenigingen.services.termination.termination_operations import (
            TerminationResults,
            UpdateMemberStatusOperation,
        )
        from verenigingen.verenigingen.doctype.member.member import Member

        operation = UpdateMemberStatusOperation(self.member.name, self.request)
        with patch.object(Member, "calculate_cumulative_membership_duration", side_effect=_deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                operation.execute(TerminationResults())

    def test_an_ordinary_duration_failure_is_still_recorded_by_the_final_operation(self):
        """CONTROL."""
        from verenigingen.services.termination.termination_operations import (
            TerminationResults,
            UpdateMemberStatusOperation,
        )
        from verenigingen.verenigingen.doctype.member.member import Member

        results = TerminationResults()
        operation = UpdateMemberStatusOperation(self.member.name, self.request)
        with patch.object(Member, "calculate_cumulative_membership_duration", side_effect=Exception("x")):
            operation.execute(results)

        self.assertTrue(
            any("duration" in error for error in results.errors),
            f"the ordinary failure should still be recorded, got {results.errors}",
        )

    # -- layer 3: the executor, and what runs after the failure -----------------------

    def _executor_over(self, error):
        """An operation that raises, followed by a spy standing in for the commit point.

        ``TerminationExecutor`` requires the last operation to be an
        ``UpdateMemberStatusOperation``, so the spy subclasses it rather than replacing it.
        """
        from verenigingen.services.termination.termination_operations import (
            TerminationExecutor,
            TerminationOperation,
            UpdateMemberStatusOperation,
        )

        class Exploding(TerminationOperation):
            @property
            def operation_name(self):
                return "Exploding Operation"

            def execute(self, results):
                raise error

        class Spy(UpdateMemberStatusOperation):
            def __init__(self, *args):
                super().__init__(*args)
                self.ran = False

            def execute(self, results):
                self.ran = True

        spy = Spy(self.member.name, self.request)
        executor = TerminationExecutor([Exploding(self.member.name, self.request), spy])
        return executor, spy

    def test_the_executor_abandons_the_remaining_operations_on_a_deadlock(self):
        """Propagating is only half of it. The harm #470 describes is operations N+1..13
        running against a transaction the server discarded, so the spy is the assertion
        that matters."""
        executor, spy = self._executor_over(_deadlock())

        with self.assertRaises(frappe.QueryDeadlockError):
            executor.execute()

        self.assertFalse(spy.ran, "the commit-point operation ran after a non-resumable error")

    def test_the_executor_still_continues_past_an_ordinary_operation_failure(self):
        """CONTROL. Partial execution is deliberate for ordinary errors and must survive."""
        executor, spy = self._executor_over(Exception("ordinary failure"))

        results = executor.execute()

        self.assertTrue(spy.ran, "partial execution was lost for an ordinary exception")
        self.assertTrue(results["errors"], "the ordinary failure was not recorded")

    # -- layer 4: end to end through the real fourteen-operation list -----------------

    def test_a_deadlock_mid_termination_leaves_the_member_status_unchanged(self):
        """The whole point, through the production ``operations = [...]``.

        Before the fix this returned a results dict, the service set the request to
        Executed and reported success, and the member came out Terminated -- describing
        writes the server had discarded.
        """
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        with self._exploding_chapter_save(_deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                TerminationExecutionService().execute_system_updates(self.request)

        self.assertNotEqual(
            frappe.db.get_value("Member", self.member.name, "status"),
            TERMINATED_STATUS,
            "the commit-point operation ran after a deadlock earlier in the list",
        )

    def test_an_ordinary_failure_mid_termination_still_reaches_the_commit_point(self):
        """CONTROL. An admin's termination must still limp past an ordinary chapter failure."""
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        with self._exploding_chapter_save(Exception("ordinary failure")):
            TerminationExecutionService().execute_system_updates(self.request)

        self.assertEqual(
            frappe.db.get_value("Member", self.member.name, "status"),
            TERMINATED_STATUS,
            "partial execution was lost for an ordinary exception",
        )


class TestEverySwallowInTheTerminationPackage(VereningingenTestCase):
    """The ratchet. Forty-four handlers were guarded; this is what stops the forty-fifth.

    Scoped to ``services/termination/`` rather than the app, because that is the package
    this work audited. A wider scope would be a claim about code nobody has read.

    What it does and does not enforce: that every catch-all is preceded by a
    ``NON_RESUMABLE_DB_ERRORS`` clause whose body is a bare ``raise``, or carries the
    exemption marker. It cannot check that an exemption's stated *reason* is true -- that
    stays a human claim, and one of the four was wrong on the first pass.

    **It also cannot see how a guarded handler REPORTS the error.** Measured while fixing
    #475: delete the ``except NON_RESUMABLE_DB_ERRORS`` branch from
    ``TerminationExecutionService.execute`` and this module still passes 10/10, because the
    remaining catch-all's ``non-resumable-ok`` marker stays a true statement -- the handler
    really does end in ``_handle_error``, which really does re-raise. It just re-raises a
    ``ValidationError``. Only the behavioural tests in
    ``test_termination_reporting_boundaries`` hold that boundary. Read this paragraph before
    trusting a green run here as coverage of anything but handler SHAPE.
    """

    # Both predicates moved to tests/support/non_resumable_ast.py when #561's ratchet needed
    # the same two questions. The shared rule is the STRICTER one: it also rejects
    # `raise Wrapper(e)`, which replaces the exception and so defeats every caller keyed on
    # the original class. This test's own rule -- "a guard counts only if its body is a bare
    # raise" -- is preserved: checking the handler TYPE alone is what it did originally, and
    # that accepted `except NON_RESUMABLE_DB_ERRORS: log(); return False`, i.e. the #470
    # defect wearing the right clause.

    def _unguarded(self, source, tree):
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for position, handler in enumerate(node.handlers):
                if not catches_bare_exception(handler):
                    continue
                if EXEMPTION_MARKER in lines[handler.lineno - 1]:
                    continue
                # The guard must come FIRST: Python matches handlers in order, so a
                # NON_RESUMABLE clause below `except Exception` is dead code.
                if any(
                    reraises_non_resumable(earlier) and earlier.type is not None
                    for earlier in node.handlers[:position]
                ):
                    continue
                yield handler.lineno

    def test_every_catch_all_in_the_termination_package_re_raises_non_resumable_errors(self):
        offenders = []
        for path in sorted(TERMINATION_PACKAGE.glob("*.py")):
            source = path.read_text()
            for lineno in self._unguarded(source, ast.parse(source)):
                offenders.append(f"{path.name}:{lineno}")

        self.assertEqual(
            offenders,
            [],
            "these catch-all handlers would record a 1205/1213 and carry on against a "
            "transaction the server has discarded (#470). Add `except NON_RESUMABLE_DB_ERRORS: "
            f"raise` above them, or mark the handler `# {EXEMPTION_MARKER} <reason>` if it "
            "runs after the failure and re-raising would mask the original error:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_ratchet_sees_a_swallow_the_package_no_longer_contains(self):
        """A synthetic control. Once the package is clean the test above passes on an empty
        list, which is also what a walker that silently matched nothing would produce -- and
        the exemption and ordering branches are unreachable from the real files."""
        planted = (
            "try:\n    f()\nexcept Exception:\n    pass\n",
            # A guard placed AFTER the catch-all is dead code, and must not count.
            "try:\n    f()\nexcept Exception:\n    pass\nexcept NON_RESUMABLE_DB_ERRORS:\n    raise\n",
            "try:\n    f()\nexcept (ValueError, Exception):\n    pass\n",
            "try:\n    f()\nexcept:\n    pass\n",
            # `except BaseException` is a catch-all too, and catches these two just as well.
            "try:\n    f()\nexcept BaseException:\n    pass\n",
            # A guard in name only. Both of these were ACCEPTED before the skeptical review
            # on this PR measured them -- the walker read the clause and never the body.
            "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    pass\nexcept Exception:\n    pass\n",
            "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    log()\n    return False\n"
            "except Exception:\n    pass\n",
        )
        for source in planted:
            with self.subTest(source=source):
                self.assertTrue(list(self._unguarded(source, ast.parse(source))))

        accepted = (
            "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    raise\nexcept Exception:\n    pass\n",
            "try:\n    f()\nexcept Exception:  # non-resumable-ok: runs after the failure\n    pass\n",
            "try:\n    f()\nexcept ValueError:\n    pass\n",
        )
        for source in accepted:
            with self.subTest(source=source):
                self.assertFalse(list(self._unguarded(source, ast.parse(source))))
