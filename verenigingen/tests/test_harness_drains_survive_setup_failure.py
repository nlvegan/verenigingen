"""EnhancedTestCase's cleanup drains must survive setUp() raising (#1467).

`_drain_tracked_documents` and `_drain_captured_inserts` were only ever called
explicitly from `tearDown()`. Standard `unittest.TestCase.run()` semantics:
when `setUp()` itself raises, `tearDown()` is skipped entirely -- so any
document a test's `setUp()` created and tracked/captured before the point
where it raised was never drained by that test's own lifecycle.

That would be an ordinary uncommitted-and-later-rolled-back non-issue, except
several `@shared_fixture` helpers (e.g. `ensure_mollie_reversal_accounts()`)
end with an UNCONDITIONAL `frappe.db.commit()`, by design -- that is what lets
the master data they build survive the *next* test's own per-method rollback.
Called from a later test's `setUp()`, that commit does not distinguish "only
my own pending insert" from "also a previous test's uncommitted leftovers,
whose own tearDown-driven rollback+drain never ran because its setUp raised
first" -- it commits all of it. #1438 measured exactly this leaving one
submitted Donation behind, which then collided with every later run.

The case is driven through two real `EnhancedTestCase` test METHODS on one
class (not two separate classes -- `FrappeTestCase`'s `addClassCleanup(
_rollback_db)` fires once per class, so splitting across classes would roll
back the leak before the second setUp ever ran, silently curing the very bug
under test) run via a manually-built `unittest.TestSuite`, exactly matching
the reproduction procedure the issue itself used.

`step_one` leaks TWO different rows on purpose -- one via `self.create_test_
member(...)` (factory-TRACKED: `self.factory.track_document(...)`, drained by
`_drain_tracked_documents`) and one via a raw `frappe.get_doc(...).insert()`
on a plain "Note" (CAPTURED-only, via the `Document.db_insert` monkeypatch,
drained by `_drain_captured_inserts`). A fix that only wires up one of the two
drains -- a real, plausible partial fix -- would still pass a version of this
test that checked only the Member.
"""

import io
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _LeaksAcrossSetupFailure(EnhancedTestCase):
    """step_one's setUp creates a tracked Member AND a captured-only Note, then
    raises. step_two's setUp stands in for a `@shared_fixture` helper's
    unconditional commit.

    Deliberately NO `test_*`-named methods: `unittest`'s default test loader
    (which is what discovers tests for `bench run-tests`) collects methods by
    the `test` name prefix, not by class name -- a leading underscore on the
    CLASS does not stop it. A `test_*` method here would be discovered and run
    directly by the module's own top-level test collection, in addition to the
    controlled run via the manually-built suite below, polluting the very leak
    count this reproduction depends on (confirmed: an earlier revision named
    these `test_one_...`/`test_two_...` and bench ran each of them BOTH ways,
    creating two separate leaked Members per run instead of one).
    """

    leaked_member_name = None
    leaked_note_name = None

    def setUp(self):
        super().setUp()
        if self._testMethodName == "step_one_setup_fails_after_creating_a_document":
            member = self.create_test_member(
                first_name="Leaky",
                last_name="SetupFailure",
                email=f"leaky-setup-{frappe.generate_hash(length=8)}@example.com",
            )
            type(self).leaked_member_name = member.name
            type(self).leaked_note_name = self._create_committed_note()
            raise RuntimeError("simulated setUp failure after fixture creation (#1467)")
        else:
            self._create_shared_fixture_commit()

    def _create_committed_note(self):
        """Build a captured-only Note and commit it immediately.

        A raw `frappe.get_doc(...).insert()` the factory never tracks, so only
        the `Document.db_insert` monkeypatch (`_drain_captured_inserts`) knows
        about it -- distinct from the Member built in `setUp`, which is also
        factory-tracked and would be cleaned up by `_drain_tracked_documents`
        alone.

        Committed IMMEDIATELY here (mimicking production code that commits
        mid-setUp, e.g. a service call), not left pending like the Member.
        Both drains open with their own defensive `frappe.db.rollback()`
        before doing anything else, so if this row were left uncommitted like
        the Member, EITHER drain's rollback alone would silently erase it too
        -- which would make this test unable to tell "the tracked drain ran"
        apart from "the captured-insert drain ran" (confirmed: an earlier
        revision left this uncommitted and a tracked-only-drain mutant still
        passed it by accident, via that rollback, not via any
        captured-insert-specific deletion). Committing here means only the
        CAPTURED-insert drain's own delete logic -- not incidental rollback --
        can remove it (#1467).

        `_create`-prefixed so `scan_order_dependence.py` records this commit
        as the non-blocking COMMIT_EXEMPT kind, not a bare COMMIT: it is a
        real fixture builder (the Note is built and returned here, not
        elsewhere), matching the `_create_*`/`_cleanup_*`/`tearDown` exemption
        convention #820/#827 established for load-bearing test commits.
        """
        note = frappe.get_doc(
            {
                "doctype": "Note",
                "title": f"Leaky setUp note {frappe.generate_hash(length=8)}",
                "content": "created by a setUp() that then raises (#1467)",
            }
        ).insert()
        frappe.db.commit()
        return note.name

    def _create_shared_fixture_commit(self):
        """Stand in for a `@shared_fixture` helper's trailing, unconditional
        `frappe.db.commit()` (e.g. `ensure_mollie_reversal_accounts()`),
        called from a later test's `setUp` so ITS OWN master data survives
        per-test rollback -- fired unconditionally even on the common call
        where nothing new needed building, since these are idempotent
        get-or-creates.

        That commit does not distinguish "only my own pending write" from
        "also a previous test's uncommitted leftovers, whose own
        tearDown-driven drain never ran because its setUp raised first" -- it
        commits all of it (#1467). This helper builds no row of its own; it
        exists only to give the commit an honest, `_create`-prefixed home so
        `scan_order_dependence.py` records it as COMMIT_EXEMPT rather than a
        bare, gated COMMIT -- the same #820/#827 convention
        `_create_committed_note` above uses, applied to the shape where the
        "fixture" being modeled is the unconditional commit itself.
        """
        frappe.db.commit()

    def step_one_setup_fails_after_creating_a_document(self):
        self.fail("setUp should have raised before this test body ever runs")

    def step_two_a_later_setup_commits_whatever_is_pending(self):
        pass


class DrainsSurviveSetupFailureTest(unittest.TestCase):
    def test_a_document_created_in_a_failing_setup_does_not_survive(self):
        suite = unittest.TestSuite()
        suite.addTest(_LeaksAcrossSetupFailure("step_one_setup_fails_after_creating_a_document"))
        suite.addTest(_LeaksAcrossSetupFailure("step_two_a_later_setup_commits_whatever_is_pending"))

        result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)

        self.assertEqual(
            1,
            len(result.errors),
            f"expected exactly test_one's injected setUp failure, got: {result.errors}",
        )

        leaked_member = _LeaksAcrossSetupFailure.leaked_member_name
        leaked_note = _LeaksAcrossSetupFailure.leaked_note_name
        self.assertIsNotNone(
            leaked_member, "the reproduction must actually create a document before setUp raises"
        )
        self.assertIsNotNone(
            leaked_note, "the reproduction must actually create a captured-only row before setUp raises"
        )
        self.assertFalse(
            frappe.db.exists("Member", leaked_member),
            f"Member {leaked_member} (factory-TRACKED) leaked past its own failing setUp(): "
            f"tearDown() -- and the drains it calls -- is skipped when setUp() raises, and "
            f"test_two's unconditional frappe.db.commit() (standing in for a @shared_fixture "
            f"helper) persisted it anyway (#1467)",
        )
        self.assertFalse(
            frappe.db.exists("Note", leaked_note),
            f"Note {leaked_note} (CAPTURED-only, not factory-tracked) leaked past its own "
            f"failing setUp() the same way -- a fix that drains only tracked documents and "
            f"not captured inserts would miss exactly this row (#1467)",
        )
