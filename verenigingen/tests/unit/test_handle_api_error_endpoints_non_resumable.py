"""#481/#504 gave ``@handle_api_error`` a guard: a MariaDB 1205/1213 re-raises instead
of becoming a return value, because a caller cannot retry what it cannot distinguish
and the alternative is Frappe committing half-applied work at request end.

That guard can only fire if the class actually reaches the decorator. #505 is that it
did not, for endpoints whose OWN body wraps everything in a broad ``except Exception``
that returns rather than re-raises -- the class is caught one frame BELOW the
decorator and converted into an ``OperationResult``/dict before ``@handle_api_error``
ever sees it. #505's own AST census (taken against an earlier develop commit) named 11
such endpoints.

**Re-running that census against the current tree finds 16, not 11.** The extra five
are code the app grew after #505 was filed: ``quick_approve_member``,
``suggest_chapters_for_postal_code``, ``sync_team_with_volunteers``,
``bulk_apply_team_role_profiles``, and ``create_sepa_batch_validated`` -- the last of
these a WRITER (``batch_doc.insert()`` sits immediately above its swallow), and one
#481's own "writers" table had already named without #505 picking it up. This is the
same lesson as #458/#462 and the CLAUDE.md rule it produced: a finding is a class, not
the instance list attached to the issue that reported it -- grep the pattern again
before trusting the count.

``TestHandleApiErrorEndpointsPropagateNonResumableErrors`` demonstrates the swallow
empirically (not from reading) on three representative shapes, each with an ordinary-
exception CONTROL proving the endpoint still returns its normal structured failure for
everything else:

* ``get_members_without_chapter`` -- the simplest shape, a single top-level try.
* ``submit_application`` -- reproduces the exact injection #505's own issue text used
  (``parse_application_data``), and is the endpoint with a real in-frame
  ``frappe.db.commit()``.
* ``execute_bulk_payment_action`` -- the class one frame below the decorator AND
  inside a per-item loop: the loop's own ``except Exception`` swallows first, so
  fixing only the function-level catch (as a naive read of #505 might suggest) would
  still leave this one broken.

``TestEveryHandleApiErrorEndpointReRaisesNonResumableErrors`` is the ratchet: an AST
walk of every ``@frappe.whitelist()`` + ``@handle_api_error`` function app-wide (not
one package -- #481 itself asked whether the #470 ratchet, scoped to
``services/termination/``, should widen to cover this decorator; this is that widened
ratchet), asserting every catch-all in the function's OWN body (nested loops included,
nested closures excluded) is preceded by a clause that re-raises
``NON_RESUMABLE_DB_ERRORS`` -- or that the catch-all's own body already re-raises
unconditionally regardless of class, which needs no separate guard. That second
refinement matters: without it the ratchet would demand a redundant guard above
``submit_application``'s member-creation ``except Exception as e: log(...); raise``,
which already propagates everything, non-resumable errors included. #470/#561's
shared ratchet (``non_resumable_ast.py``) does not have this refinement because
nothing in ``services/termination/`` needed it; reused here rather than duplicated.

**What this file does NOT claim.** No real 1213 is produced anywhere in it -- as with
every other module in this class (#470, #475, #481's own
``test_handle_api_error_non_resumable``), what is injected is the exception CLASS, not
contention. ``sepa_race_condition_manager.retry_failed_operation`` carries the same
shape and is deliberately excluded from both the fix and this ratchet: it is not
whitelisted (an internal retry helper, outside the 50-endpoint universe #481 and #505
both define) and its swallow is a purposeful retry-then-wrap-in-SEPAError, not a
silent continue.
"""

import ast
import pathlib
from unittest.mock import patch

import frappe

from verenigingen.tests.support.non_resumable_ast import (
    catches_bare_exception,
    reraises_non_resumable,
    reraises_unconditionally,
)
from verenigingen.tests.support.non_resumable_errors import deadlock as _deadlock
from verenigingen.tests.support.non_resumable_errors import lock_wait_timeout as _timeout
from verenigingen.tests.utils.base import VereningingenTestCase

APP_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestHandleApiErrorEndpointsPropagateNonResumableErrors(VereningingenTestCase):
    """Behavioural half: does the class actually reach the caller for real endpoints."""

    def setUp(self):
        super().setUp()
        # @handle_api_error's own guard (#504) logs the error once the class reaches
        # it -- expected, not a regression. The ordinary-exception CONTROLS also log
        # (that is the behaviour they pin), just through each endpoint's own
        # pre-existing except Exception clause instead.
        self.expectErrorLog(
            "QueryDeadlockError",
            "QueryTimeoutError",
            "get_members_without_chapter",
            "submit_application",
            "execute_bulk_payment_action",
            "RuntimeError",
            "ordinary failure",
            "Members Without Chapter Error",
            "Application Submission Error",
        )

    # -- shape 1: a single top-level try ----------------------------------------

    def test_get_members_without_chapter_propagates_a_deadlock(self):
        from verenigingen.api import member_management

        with patch.object(
            member_management, "can_view_members_without_chapter", side_effect=_deadlock()
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                member_management.get_members_without_chapter()

    def test_get_members_without_chapter_still_returns_a_structured_failure_for_ordinary_errors(self):
        """CONTROL. Without this, the test above is equally consistent with the endpoint
        now propagating everything, which would break every caller reading
        ``result["success"]``. The wrapping security decorator (``high_security_api``)
        already serializes the OperationResult to a dict via ``to_dict()`` before it
        reaches this caller, so the result here is a plain dict, not the object."""
        from verenigingen.api import member_management

        with patch.object(
            member_management,
            "can_view_members_without_chapter",
            side_effect=RuntimeError("ordinary failure"),
        ):
            result = member_management.get_members_without_chapter()

        self.assertFalse(result["success"])

    # -- shape 2: the exact injection #505's own issue text used -----------------

    def test_submit_application_propagates_a_lock_wait_timeout(self):
        """Reproduces #505's own empirical proof: a 1205 injected into
        ``parse_application_data`` used to return identically to an ordinary error
        (``success=False``) instead of propagating. ``submit_application`` also has a
        real ``frappe.db.commit()`` mid-function (#481's durability half), making it
        the endpoint where a swallowed class does the most damage."""
        from verenigingen.api import membership_application

        with patch.object(
            membership_application, "parse_application_data", side_effect=_timeout()
        ):
            with self.assertRaises(frappe.QueryTimeoutError):
                membership_application.submit_application(data={})

    def test_submit_application_still_returns_a_structured_failure_for_ordinary_errors(self):
        """CONTROL."""
        from verenigingen.api import membership_application

        with patch.object(
            membership_application,
            "parse_application_data",
            side_effect=RuntimeError("ordinary failure"),
        ):
            result = membership_application.submit_application(data={})

        self.assertFalse(result["success"])

    # -- shape 3: the class one frame below the decorator AND inside a loop -----

    def test_execute_bulk_payment_action_propagates_a_deadlock_from_inside_the_loop(self):
        """The loop's own ``except Exception`` (payment_processing.py) is the FIRST
        thing that sees the exception -- fixing only the function-level catch would
        leave this one swallowing exactly as before. This is the discriminating test
        for that nested-guard requirement."""
        from verenigingen.api import payment_processing

        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data",
            return_value=[{"member_name": "NON-EXISTENT-MEMBER-FOR-505"}],
        ):
            with patch.object(
                payment_processing, "send_payment_reminder_email", side_effect=_deadlock()
            ):
                with self.assertRaises(frappe.QueryDeadlockError):
                    payment_processing.execute_bulk_payment_action(
                        action="Send Payment Reminders", apply_to="All Visible Records"
                    )

    def test_execute_bulk_payment_action_still_continues_past_an_ordinary_per_item_failure(self):
        """CONTROL. Partial progress on an ordinary per-member failure is deliberate
        (a bad member should not block the rest of the batch) and must survive."""
        from verenigingen.api import payment_processing

        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data",
            return_value=[{"member_name": "NON-EXISTENT-MEMBER-FOR-505"}],
        ):
            with patch.object(
                payment_processing,
                "send_payment_reminder_email",
                side_effect=RuntimeError("ordinary failure"),
            ):
                result = payment_processing.execute_bulk_payment_action(
                    action="Send Payment Reminders", apply_to="All Visible Records"
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)


class TestEveryHandleApiErrorEndpointReRaisesNonResumableErrors(VereningingenTestCase):
    """The ratchet. #481 itself asked whether the #470 ratchet (scoped to
    ``services/termination/``) should widen to cover ``@handle_api_error``; this is
    that ratchet, scoped to every ``@frappe.whitelist()`` endpoint wearing the
    decorator app-wide -- the 50-endpoint universe #481 and #505 both measured.

    Deliberately does NOT walk into nested function definitions (closures), matching
    the census that found the 16 real offenders: a nested helper's own try/except is
    that helper's business, not the endpoint's, and #470's whole-FILE walk would over-
    count here (this walker is per-function, #470's is per-package).
    """

    def _decorator_names(self, node):
        names = []
        for d in node.decorator_list:
            if isinstance(d, ast.Call):
                d = d.func
            if isinstance(d, ast.Name):
                names.append(d.id)
            elif isinstance(d, ast.Attribute):
                names.append(d.attr)
        return names

    def _unguarded_in_function(self, func_node):
        """Catch-all handlers in ``func_node``'s own body (nested defs excluded) not
        preceded by a NON_RESUMABLE_DB_ERRORS re-raise, and not already safe because
        their own body re-raises unconditionally regardless of class."""

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not func_node:
                    continue  # a nested closure's handlers are its own business
                if isinstance(child, ast.Try):
                    for position, handler in enumerate(child.handlers):
                        if not catches_bare_exception(handler):
                            continue
                        if reraises_unconditionally(handler):
                            continue  # already propagates everything on its own
                        guarded = any(
                            reraises_non_resumable(earlier) and earlier.type is not None
                            for earlier in child.handlers[:position]
                        )
                        if not guarded:
                            yield handler.lineno
                yield from walk(child)

        yield from walk(func_node)

    def _whitelisted_handle_api_error_functions(self):
        for path in sorted(APP_ROOT.rglob("*.py")):
            rel = path.relative_to(APP_ROOT)
            if "tests" in rel.parts or rel.name.startswith("test_"):
                continue
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorators = self._decorator_names(node)
                if "handle_api_error" in decorators and "whitelist" in decorators:
                    yield path, node

    def test_every_whitelisted_handle_api_error_endpoint_reraises_non_resumable_errors(self):
        offenders = []
        for path, node in self._whitelisted_handle_api_error_functions():
            for lineno in self._unguarded_in_function(node):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{lineno} ({node.name})")

        self.assertEqual(
            offenders,
            [],
            "these endpoints' own catch-all would swallow a 1205/1213 before "
            "@handle_api_error's guard (#481/#504) ever sees it (#505). Add "
            "`except NON_RESUMABLE_DB_ERRORS: raise` ahead of each:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_ratchet_sees_a_swallow_the_app_no_longer_contains(self):
        """SYNTHETIC CONTROL. Proves the walker actually flags the shape it exists to
        catch, rather than passing on an empty tree the same way a walker that
        silently matched nothing would. Mirrors #470's own synthetic control
        (test_termination_non_resumable_errors.py) for the same reason: a real-file
        sweep passing clean is equally consistent with "correctly clean" and with
        "the walker never matches anything real"."""
        planted = ast.parse(
            "@frappe.whitelist()\n"
            "@handle_api_error\n"
            "def endpoint():\n"
            "    try:\n"
            "        f()\n"
            "    except Exception:\n"
            "        return {'success': False}\n"
        )
        (func_node,) = planted.body
        self.assertTrue(list(self._unguarded_in_function(func_node)))

    def test_the_ratchet_sees_an_unguarded_catch_all_nested_in_a_loop_with_no_outer_try(self):
        """STANDING CONTROL for the recursive-descent step itself, not just the
        predicates it applies once it arrives somewhere.

        ``sync_team_with_volunteers`` and ``bulk_apply_team_role_profiles`` in
        ``team_management.py`` have NO function-level try at all -- their only
        catch-all sits one level down, inside a ``for`` loop. A walker whose
        recursive step is a bare ``walk(child)`` statement instead of
        ``yield from walk(child)`` only constructs the inner generator and
        immediately discards it without iterating, so it never visits a ``Try``
        node that isn't a direct child of the function body. That walker still
        passes ``test_the_ratchet_sees_a_swallow_the_app_no_longer_contains`` above
        (that planted catch-all IS a direct child), so this shape needed its own
        control -- proved by reverting exactly these two guards on the PR branch
        and rerunning the ratchet: it stayed green, reporting zero offenders.

        This reuses ``self._unguarded_in_function`` -- the real production walker,
        not a second implementation of it -- which is the point: a parallel walker
        here would only prove the parallel walker works."""
        planted = ast.parse(
            "@frappe.whitelist()\n"
            "@handle_api_error\n"
            "def endpoint():\n"
            "    for item in get_items():\n"
            "        try:\n"
            "            f(item)\n"
            "        except Exception:\n"
            "            log(item)\n"
        )
        (func_node,) = planted.body
        self.assertTrue(list(self._unguarded_in_function(func_node)))

    def test_the_ratchet_accepts_a_preceding_guard(self):
        """CONTROL for the fix shape: a preceding bare re-raise satisfies the walker."""
        planted = ast.parse(
            "@frappe.whitelist()\n"
            "@handle_api_error\n"
            "def endpoint():\n"
            "    try:\n"
            "        f()\n"
            "    except NON_RESUMABLE_DB_ERRORS:\n"
            "        raise\n"
            "    except Exception:\n"
            "        return {'success': False}\n"
        )
        (func_node,) = planted.body
        self.assertEqual(list(self._unguarded_in_function(func_node)), [])

    def test_the_ratchet_accepts_a_catch_all_that_already_reraises_on_its_own(self):
        """CONTROL for the self-safe refinement described in the module docstring --
        this is the exact shape of submit_application's member-creation handler,
        which must NOT be flagged."""
        planted = ast.parse(
            "@frappe.whitelist()\n"
            "@handle_api_error\n"
            "def endpoint():\n"
            "    try:\n"
            "        f()\n"
            "    except Exception as e:\n"
            "        log(e)\n"
            "        raise\n"
        )
        (func_node,) = planted.body
        self.assertEqual(list(self._unguarded_in_function(func_node)), [])

    def test_the_ratchet_ignores_a_nested_closures_own_handlers(self):
        """CONTROL. A nested helper function's try/except is that helper's own
        business, not the endpoint's -- the census this ratchet mirrors deliberately
        does not descend into nested defs."""
        planted = ast.parse(
            "@frappe.whitelist()\n"
            "@handle_api_error\n"
            "def endpoint():\n"
            "    def helper():\n"
            "        try:\n"
            "            f()\n"
            "        except Exception:\n"
            "            return None\n"
            "    return helper()\n"
        )
        (func_node,) = planted.body
        self.assertEqual(list(self._unguarded_in_function(func_node)), [])

    def test_the_census_finds_the_expected_endpoint_count(self):
        """Pins the universe size against #481's own measurement (50 whitelisted
        ``@handle_api_error`` endpoints) so a future refactor that silently drops or
        duplicates a decorator combination is caught here rather than by a shrinking
        offenders list that looks like progress."""
        endpoints = list(self._whitelisted_handle_api_error_functions())
        self.assertEqual(
            len(endpoints),
            50,
            f"expected 50 whitelisted @handle_api_error endpoints (#481's own count), "
            f"found {len(endpoints)}: "
            + ", ".join(f"{p.relative_to(APP_ROOT)}:{n.name}" for p, n in endpoints),
        )
