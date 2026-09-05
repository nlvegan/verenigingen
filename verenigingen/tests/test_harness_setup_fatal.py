"""Harness setup that fails must say so, not log and continue.

The failure mode these guard against is not a crash. It is a setup step that
did not happen, whose consequence arrives much later as a storm of failures in
unrelated tests -- the #291 shape. `disable_workflow_action_emails()` is the
clearest case: if it does not take, Frappe renders a PDF synchronously inside
every Member insert and can raise `OSError: ... HostNotFoundError` in every test
that touches a Member, none of which names this cause (#314).

Two kinds of assertion here, because neither kind alone is enough:

* Behavioural -- the patch is actually on, an import failure propagates instead
  of being logged, and the postcondition fires when the assignment does not take.
* A source guard -- re-wrapping any of these call sites in a `try`/`except`
  restores the old behaviour without changing any observable result on a healthy
  box, so no behavioural test can catch it.
"""

import ast
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import frappe  # noqa: F401  (import side effects the harness modules rely on)

from verenigingen.tests.setup import (
    disable_workflow_action_emails,
    workflow_action_emails_disabled,
)
from verenigingen.tests.utils.paths import APP_ROOT
from verenigingen.tests.utils.source_probes import called_names

_WORKFLOW_ACTION_PKG = "frappe.workflow.doctype.workflow_action"

# Call sites that must not be wrapped in a swallow, and the file each lives in.
# Keyed by the called function's name because that is what survives a refactor
# of the surrounding code; the line number does not.
UNGUARDED_CALLS = {
    "verenigingen/tests/utils/__init__.py": {"disable_workflow_action_emails"},
    "verenigingen/tests/fixtures/enhanced_test_factory.py": {
        "disable_workflow_action_emails",
        # A fixture file that does not load is master data that does not exist.
        # Both the per-file call and the loop around it must stay unguarded: the
        # loop swallow alone made the inner one dead code (#309).
        "_load_fixture_file",
        # A `None` return means the installer's own best-effort handler
        # swallowed a real failure; `_require_settings_installer_succeeded`
        # must keep checking that return value unguarded, or a re-wrapped
        # try/except here would silently restore the #309 swallow (#309).
        "create_default_verenigingen_settings",
        # The self-heal that keeps the check above from being a spurious
        # failure on a fresh/isolated-module site (it seeds the two reqd
        # fields -- creation_user, company -- the installer's own dead
        # branch never sets). Deleting the call passes every other test in
        # this module unnoticed; only this guard catches that (#309).
        "_seed_verenigingen_test_system_user",
        # NB: `ensure_root_department` is deliberately NOT listed, for the same
        # reason `ensure_netherlands_territory` is not. Both sit inside
        # `_ensure_master_data`'s handler, which re-raises as a RuntimeError
        # rather than swallowing. This guard flags any handler-bearing `try`, so
        # listing them would report a re-raise as if it were a swallow.
    },
    "verenigingen/tests/setup/__init__.py": {
        "_seed_default_team_roles",
        "set_defaults_for_tests",
        "enable_all_roles_and_domains",
        # Every seeder below is existence-checked and idempotent, so raising
        # cannot cause a spurious failure -- and each one's own comment already
        # names what breaks when it does not take: payment modes (~119 tests),
        # creation_user (~91, plus ~71 cascading MandatoryError), the leaf
        # Customer Group (~72), MijnRood dummy credentials (~33). Those counts
        # are the argument for failing here rather than logging (#309).
        "ensure_erpnext_base_masters",
        # The root Territory. Swallowing it puts #516 back: the very next line
        # links a child to a parent that does not exist, and the LinkValidationError
        # lands in `setUpClass` of whichever module the shard packer put first.
        "ensure_root_territory",
        "_seed_verenigingen_test_system_user",
        "ensure_payment_modes_exist",
        "_seed_default_leaf_customer_group",
        "_seed_mijnrood_sync_settings_dummy_credentials",
        "make_test_records",
        "ensure_fiscal_year_exists",
    },
    "verenigingen/tests/utils/base.py": {
        # `VereningingenTestCase.setUpClass` -> `ensure_netherlands_territory()`,
        # which is where #516 raised and which now also seeds the root. This is
        # the ONLY thing binding that half of the fix -- ~289 files are on this
        # base and none of them notices its absence: deleting this call left both
        # `test_harness_territory_root` (6/6) and this module (13/13) green, so
        # the whole `VereningingenTestCase` side could be reverted unobserved.
        # Measured by mutation, which is why the postcondition below now demands
        # each named call be FOUND rather than only checking the file exists.
        "ensure_netherlands_territory",
        # Same call site, same reasoning, for the Item Group / Customer Group /
        # Supplier Group roots (#562).
        "ensure_root_item_group",
        "ensure_root_customer_group",
        "ensure_root_supplier_group",
    },
}


class _WritesAreDropped:
    """Stands in for the workflow_action module and ignores attribute writes.

    Used to prove the postcondition check does real work: with this in place the
    assignment inside `disable_workflow_action_emails()` silently does nothing,
    which is exactly the situation "it did not raise" cannot distinguish from
    success.
    """

    send_workflow_action_email = staticmethod(lambda *a, **k: None)

    def __setattr__(self, name, value):
        pass


class _FakePackage:
    def __init__(self, workflow_action):
        self.workflow_action = workflow_action


class WorkflowActionEmailPatchTest(unittest.TestCase):
    """The patch must be on, and must be verified rather than assumed."""

    def tearDown(self):
        # Whatever a test did to sys.modules, leave the real patch in place: the
        # rest of the suite depends on it, and a test that quietly turns it off
        # would slow every later Member insert to a PDF render.
        sys.modules.pop("_never", None)
        disable_workflow_action_emails()

    def test_the_patch_is_on_during_a_test_run(self):
        """The real postcondition, against the real module."""
        self.assertTrue(
            workflow_action_emails_disabled(),
            "workflow-action emails are not disabled; every Member insert renders a PDF",
        )

    def test_calling_it_again_is_idempotent(self):
        disable_workflow_action_emails()
        disable_workflow_action_emails()
        self.assertTrue(workflow_action_emails_disabled())

    def test_an_import_failure_propagates_instead_of_being_logged(self):
        """A `None` in sys.modules makes the import raise. It must not be caught."""
        original = sys.modules.get(_WORKFLOW_ACTION_PKG)
        sys.modules[_WORKFLOW_ACTION_PKG] = None
        try:
            with self.assertRaises(ImportError):
                disable_workflow_action_emails()
        finally:
            if original is None:
                sys.modules.pop(_WORKFLOW_ACTION_PKG, None)
            else:
                sys.modules[_WORKFLOW_ACTION_PKG] = original

    def test_an_assignment_that_does_not_take_is_caught(self):
        """"It did not raise" is not evidence the side effect happened."""
        original = sys.modules.get(_WORKFLOW_ACTION_PKG)
        sys.modules[_WORKFLOW_ACTION_PKG] = _FakePackage(_WritesAreDropped())
        try:
            with self.assertRaises(RuntimeError) as caught:
                disable_workflow_action_emails()
            self.assertIn("send_workflow_action_email", str(caught.exception))
        finally:
            if original is None:
                sys.modules.pop(_WORKFLOW_ACTION_PKG, None)
            else:
                sys.modules[_WORKFLOW_ACTION_PKG] = original


class SetupCallsAreNotSwallowedTest(unittest.TestCase):
    """No behavioural test can see a swallow that never fires. This can."""

    def test_named_setup_calls_are_not_inside_a_try_except(self):
        offenders = []
        for rel_path, names in UNGUARDED_CALLS.items():
            path = APP_ROOT / rel_path
            self.assertTrue(path.exists(), f"{rel_path} moved; update this test")
            for name, lineno in _calls_guarded_by_except(path, names):
                offenders.append(f"{rel_path}:{lineno} {name}()")

        self.assertEqual(
            [],
            offenders,
            "These setup calls are wrapped in an except handler again. A failure "
            "there is not survivable in a useful way -- it resurfaces as unrelated "
            "failures elsewhere. See #309/#314.",
        )

    def test_every_named_setup_call_is_still_there_to_guard(self):
        """A DELETED call passes the swallow guard above, which is worse.

        `path.exists()` and "no offenders" are both satisfied by a file that no
        longer calls the thing at all -- and a call that does not happen is the
        failure mode this whole module is about (#309/#314). Measured: deleting
        `ensure_netherlands_territory()` from `tests/utils/base.py` left
        `test_harness_territory_root` 6/6 and this module 13/13 green (#516).
        """
        missing = []
        for rel_path, names in UNGUARDED_CALLS.items():
            path = APP_ROOT / rel_path
            called = called_names(ast.parse(path.read_text(), filename=str(path)))
            for name in sorted(names - called):
                missing.append(f"{rel_path}: {name}()")

        self.assertEqual(
            [],
            missing,
            "These setup calls are named as must-not-be-swallowed but are no longer "
            "called in that file. Either the setup step was dropped -- which is the "
            "#309 failure mode, not a refactor -- or this table needs updating.",
        )


class _TrackingStub:
    """The only collaborator `_load_fixture_file` needs, and nothing else.

    `_load_fixture_file` is a method of `EnhancedTestCase`, whose real `setUp`
    builds the whole harness. Standing in for `self` here keeps these tests about
    the loader's own error handling -- the code under test is the real method.
    """

    def __init__(self):
        self.tracked = []

    class _Factory:
        def __init__(self, outer):
            self.outer = outer

        def track_document(self, doctype, name, priority=1):
            self.outer.tracked.append((doctype, name))

    @property
    def factory(self):
        return self._Factory(self)

    def __getattr__(self, name):
        """Borrow every other method from the real class, bound to this stub.

        Without this the stub lacks `_validate_fixture_before_load` and
        `_is_acceptable_fixture_validation_error`, and the loader dies on
        `AttributeError` -- which `assertRaises(Exception)` accepts as a pass.
        The tests below would then be green while proving nothing.
        """
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        return getattr(EnhancedTestCase, name).__get__(self, type(self))


def _load(records_or_text, suffix=".json"):
    """Run the real `_load_fixture_file` over a temporary fixture file."""
    from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
        if isinstance(records_or_text, str):
            handle.write(records_or_text)
        else:
            json.dump(records_or_text, handle)
        path = handle.name

    try:
        return EnhancedTestCase._load_fixture_file(_TrackingStub(), path, Path(path).name)
    finally:
        os.unlink(path)


class FixtureLoadFailuresAreNotSwallowedTest(unittest.TestCase):
    """A fixture that does not load is master data that does not exist.

    Ten fixture files feed this loader -- membership_type, item, item_group,
    email_template, custom_field, workflow, workflow_state, team_role, role,
    donation_type -- and every one is referenced elsewhere by hardcoded name. A
    silent skip here is the #291 shape: the consequence lands in whichever
    unrelated test the shard packer happens to run first (#309).
    """

    def test_an_unreadable_fixture_file_raises(self):
        """The file-level handler swallowed `open`/`json.load` for a whole file.

        Asserting the specific decode error, not bare `Exception`: any typo in
        this test would raise *something*, and a test that accepts anything
        cannot tell a working loader from a broken one.
        """
        with self.assertRaises(json.JSONDecodeError):
            _load("{ this is not json")

    def test_a_record_that_cannot_be_inserted_raises(self):
        """A missing mandatory field is neither a duplicate nor a missing link."""
        # Role with no `role_name`: passes the pre-load validator (it has a
        # `name`), then fails `insert()` on mandatory. Deliberately not a Link
        # failure -- those reach `insert()` with `ignore_links` already set.
        with self.assertRaises(RuntimeError) as caught:
            _load([{"doctype": "Role", "name": f"zzz-no-role-name-{frappe.generate_hash(length=8)}"}])
        self.assertIn("did not load", str(caught.exception))

    def test_a_record_that_fails_pre_load_validation_raises(self):
        """`valid: False` skipped the record and logged the reason nowhere useful.

        The same handler also turns an exception *inside* a validator -- a harness
        bug, not a data condition -- into `valid: False`, so a broken validator
        silently stopped loading its doctype. Measured before changing it: all
        four fixture files that exist produce zero invalid records, so this
        cannot fire on healthy data (#309).
        """
        with self.assertRaises(RuntimeError) as caught:
            # `_validate_team_role_fixture` rejects a Team Role with no role_name.
            _load([{"doctype": "Team Role", "name": f"zzz-{frappe.generate_hash(length=6)}"}])
        self.assertIn("did not pass", str(caught.exception))

    def test_a_record_that_already_exists_is_still_skipped(self):
        """The duplicate path is legitimately best-effort. Do not over-correct.

        Fixtures are re-seeded across a session; re-inserting an existing record
        must stay a skip, or making the other paths fatal breaks every re-run.
        """
        role = f"zzz-harness-dupe-{frappe.generate_hash(length=8)}"
        frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
        try:
            _load([{"doctype": "Role", "role_name": role}])
        finally:
            frappe.delete_doc("Role", role, force=True)


class VerenigingenSettingsInstallationIsNotSwallowedTest(unittest.TestCase):
    """The installer's own seed is best-effort by design; the harness must not be.

    ``create_default_verenigingen_settings()`` (verenigingen/setup/__init__.py)
    catches its own exception, prints a warning, and returns ``None`` --
    defensible in production, where "don't fail installation" is a real
    requirement. The harness call site used to just call it for its side effect
    and move on, so a failure there was invisible until a much later test read
    Verenigingen Settings and hit a confusing, unrelated error (#309).

    The postcondition reads the function's own return value (``None`` on its
    internal swallow), not ``frappe.db.exists("Verenigingen Settings",
    "Verenigingen Settings")``. That check is UNCONDITIONALLY truthy for a
    Single -- frappe's database layer short-circuits to "single always exists"
    whenever doctype == docname, without touching the database -- so it can
    never fire. Measured directly: deleting every row of ``tabSingles`` for
    this doctype and calling ``exists()`` again still returns the name. The
    installer's own identical guard is the same antipattern, and is why its
    create branch never actually runs (a separate defect recurring at ~19
    sites outside tests/; tracked, out of scope here).
    ``_require_settings_installer_succeeded`` works around the gap directly,
    by calling ``_seed_verenigingen_test_system_user()`` itself -- the same
    idempotent seeder ``before_tests`` and ~19 other test modules' own
    ``setUpClass`` already call, see ``tests/setup/__init__.py``.
    """

    def test_a_swallowed_installer_failure_is_fatal(self):
        """A `None` return -- the installer's own documented failure signal -- must raise.

        Mocks the installer function directly (the actual dependency this
        method reads), not the broken existence probe -- so the mock cannot
        hide the very defect being tested.
        """
        from unittest import mock

        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        stub = _TrackingStub()
        with mock.patch("verenigingen.setup.create_default_verenigingen_settings", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                EnhancedTestCase._require_settings_installer_succeeded(stub)
        self.assertIn("Verenigingen Settings", str(caught.exception))

    def test_the_happy_path_does_not_raise_and_calls_the_installer_once(self):
        """A successful seed must not raise, and must actually reach the installer.

        Asserting only "did not raise" is satisfied even by a neutered method
        that does nothing at all -- measured: `lambda self: None` in place of
        the real method still passes a bare no-exception check. Asserting the
        installer was actually called is what a neutered method fails.
        """
        from unittest import mock

        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        stub = _TrackingStub()
        with mock.patch(
            "verenigingen.setup.create_default_verenigingen_settings", return_value=object()
        ) as installer:
            EnhancedTestCase._require_settings_installer_succeeded(stub)
        installer.assert_called_once_with()


class EssentialFixtureListIsHonestTest(unittest.TestCase):
    """The list named ten files; four exist.

    `os.path.exists` skipped the other six without a word, so the list read as a
    promise of master data -- team_role, membership_type, donation_type,
    item_group, item, workflow -- that was never loaded from here at all.
    """

    def test_every_listed_fixture_file_exists(self):
        import os

        import frappe

        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        source = inspect.getsource(EnhancedTestCase._load_essential_fixtures)
        listed = re.findall(r'"([a-z_]+\.json)"', source)
        self.assertTrue(listed, "could not find the fixture list; update this test")

        fixtures_path = os.path.join(frappe.get_app_path("verenigingen"), "fixtures")
        missing = [f for f in listed if not os.path.exists(os.path.join(fixtures_path, f))]
        self.assertEqual(
            [],
            missing,
            "These fixture files are listed as essential but do not exist. Either ship "
            "them or drop them from the list -- leaving them listed claims master data "
            "that nothing loads (#309).",
        )


class RootDepartmentIsOwnedByTestsSetupTest(unittest.TestCase):
    """`All Departments` is the Territory bug verbatim.

    Hardcoded name, `db.exists`-gated, idempotent, untracked, and
    `Chapter.after_insert() -> _sync_department()` depends on it. It lived behind
    a swallow inside the factory, so only the 780 EnhancedTestCase files could
    ever create it; the VereningingenTestCase files never called it (#309).
    """

    def test_tests_setup_owns_the_helper(self):
        from verenigingen.tests import setup

        self.assertTrue(
            hasattr(setup, "ensure_root_department"),
            "the root Department must be owned by verenigingen.tests.setup, "
            "alongside ensure_netherlands_territory, so both harnesses get it",
        )

    def test_a_department_with_a_company_is_not_named_bare(self):
        """The premise the helper rests on: why the root omits `company`.

        `Department.autoname` uses `get_abbreviated_name` whenever `company` is
        set. The old factory code passed one, so its insert produced
        `All Departments - _TC` while its own `db.exists("Department",
        "All Departments")` guard -- and `_sync_department`'s parent lookup --
        looked for the bare name.

        On a site where ERPNext already seeded the root this is invisible: the
        helper returns early and never inserts. So this pins the rule directly.
        If ERPNext ever changes it, the helper's rationale is stale and this
        fails rather than the harness quietly regressing.
        """
        company = frappe.get_all("Company", limit=1)[0].name
        department_name = f"zzz-harness-{frappe.generate_hash(length=6)}"
        doc = frappe.get_doc(
            {
                "doctype": "Department",
                "department_name": department_name,
                "company": company,
                "parent_department": "All Departments",
            }
        ).insert()
        try:
            self.assertNotEqual(
                doc.name,
                department_name,
                "Department.autoname no longer appends the company abbreviation; "
                "ensure_root_department() omits company precisely because it did",
            )
        finally:
            frappe.delete_doc("Department", doc.name, force=True)

    def test_the_root_department_exists_after_it_runs(self):
        from verenigingen.tests.setup import ensure_root_department

        ensure_root_department()
        ensure_root_department()  # idempotent
        self.assertTrue(
            frappe.db.exists("Department", "All Departments"),
            "Chapter.after_insert() -> _sync_department() needs this root",
        )


def _calls_guarded_by_except(path: Path, names: set[str]):
    """Yield (name, lineno) for calls to `names` inside a try that has handlers.

    A bare `try`/`finally` is not a swallow, so only handler-bearing Try nodes
    count. Nested functions defined inside the try are not walked around -- a
    call is reported wherever it textually sits, which is what the guard is about.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not node.handlers:
            continue
        for statement in node.body:
            for inner in ast.walk(statement):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name in names:
                    yield name, inner.lineno


if __name__ == "__main__":
    unittest.main()
