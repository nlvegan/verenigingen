"""Tests for #609: a whole-second `creation`/`modified` timestamp makes a
document unable to save or submit itself.

`frappe.utils.now()` always returns a string carrying six fractional digits
('...48.000000'). MariaDB round-trips the SAME instant back as a `datetime`
whose `str()` DROPS the trailing '.000000' ('...48'). Two framework
comparisons (`check_if_latest`, `validate_set_only_once` -- both in
`frappe/model/document.py`) stringify both sides before comparing, so a
whole-second `creation`/`modified` disagrees with itself on the very next
save/submit of the same in-memory object:

    TimestampMismatchError: ... has been modified after you have opened it
    CannotChangeConstantError: Value cannot be changed for Created On

Production hits this ~1-in-10^6 per document (measured on CI, see #609); a
whole-second `freeze_time()` hits it 100% of the time -- see the four
`test_mollie_settings.py` freezes and the two others named in #609, all of
which insert/save inside a `@freeze_time("... 00:00:00")` (zero microseconds)
window without an intervening `reload()`.

This module tests mitigation #1 (the production `doc_events["*"]["on_change"]`
normaliser). Mitigation #2 (the test-harness `db_insert` normalisation) is
covered separately in `verenigingen/tests/fixtures/test_timestamp_normalization_harness_609.py`
-- kept apart because it exercises the harness's own monkey-patch, not
production hook wiring.

**on_change, not after_insert, not on_update.** The wildcard normaliser went
through two registrations before this one:

1. `after_insert` (first shipped). A live CI recurrence on an unrelated PR
   (#729) proved that insufficient: a test called `.submit()` twice on the
   same in-memory Sales Invoice, and the whole-second `now()` landed on the
   FIRST `submit()` (a `set_user_and_timestamp()` call, same as insert, just
   not one) -- `after_insert` never fires for that, so the string was never
   trimmed, and the SECOND `submit()`'s `check_if_latest()` raised exactly
   the #609 defect.
2. `on_update` (the fix for #1's gap). Fires for both `insert()`
   (`_action == "save"`) and every later `save()`/`submit()`
   (`frappe/model/document.py:run_post_save_methods`) -- but a skeptical
   review caught that `run_post_save_methods()` only calls `on_update` for
   `_action in ("save", "submit")`. A `save()` on an already-*submitted*
   document (`_action == "update_after_submit"`), a `cancel()`, and
   `db_set()` (which stamps `modified` via the identical `now()` call,
   `document.py:1533`) all skip it entirely.

`on_change` is unconditional in `run_post_save_methods()` (fires for every
`_action`) AND is what `db_set()` itself calls (`document.py:1566`), so it
is the only event that covers every path capable of producing the
whole-second value. Reproduced directly before each switch (force a
whole-second `now()` on a `save()` call after a normal `insert()` --
`TimestampMismatchError` with `after_insert` only, `RESULT: second save OK`
with `on_update`/`on_change`). `TestWildcardHookEndToEndOnSubsequentSave`
below is the regression test for the #729 shape specifically.
"""

import unittest

import frappe
from freezegun import freeze_time

from verenigingen.hooks.doc_events import doc_events
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.timestamp_normalization import (
    ZERO_MICROSECONDS_SUFFIX,
    normalize_whole_second_timestamps,
    strip_whole_second_suffix,
)


class _FakeDoc:
    """Minimal stand-in for a Document -- just enough get()/set()/attribute
    access for the pure-function tests below. Using a real Document would
    drag in a DB round-trip for a test that is only about string
    manipulation. Fields are real attributes (not just dict entries) because
    the handler's log line reads `doc.doctype`/`doc.name` directly, same as
    the real Document class.
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def get(self, fieldname):
        return getattr(self, fieldname, None)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)


class TestStripWholeSecondSuffix(unittest.TestCase):
    """Pure-function tests for the trimming logic, no DB required."""

    def test_trims_trailing_zero_microseconds(self):
        doc = _FakeDoc(creation="2026-08-25 14:03:48.000000", modified="2026-08-25 14:03:48.000000")
        touched = strip_whole_second_suffix(doc)
        self.assertEqual(sorted(touched), ["creation", "modified"])
        self.assertEqual(doc.get("creation"), "2026-08-25 14:03:48")
        self.assertEqual(doc.get("modified"), "2026-08-25 14:03:48")

    def test_leaves_nonzero_microseconds_alone(self):
        """CONTROL: a real (non-whole-second) timestamp must not be touched --
        proves the function is not simply stripping the last 7 characters of
        every value, only the exact '.000000' suffix."""
        doc = _FakeDoc(creation="2026-08-25 14:03:48.123456", modified="2026-08-25 14:03:48.123456")
        touched = strip_whole_second_suffix(doc)
        self.assertEqual(touched, [])
        self.assertEqual(doc.get("creation"), "2026-08-25 14:03:48.123456")
        self.assertEqual(doc.get("modified"), "2026-08-25 14:03:48.123456")

    def test_leaves_non_string_values_alone(self):
        """A reloaded doc already carries a `datetime` object here (not a
        string) -- the function must not choke on, or mis-trim, that shape."""
        import datetime

        dt = datetime.datetime(2026, 8, 25, 14, 3, 48)
        doc = _FakeDoc(creation=dt, modified=dt)
        touched = strip_whole_second_suffix(doc)
        self.assertEqual(touched, [])
        self.assertIs(doc.get("creation"), dt)

    def test_only_checks_the_declared_fields(self):
        """Passing an explicit fieldname list limits which fields are touched."""
        doc = _FakeDoc(creation="2026-08-25 14:03:48.000000", other="2026-08-25 14:03:48.000000")
        touched = strip_whole_second_suffix(doc, fieldnames=("creation",))
        self.assertEqual(touched, ["creation"])
        # "other" is untouched even though it has the same suffix.
        self.assertEqual(doc.get("other"), "2026-08-25 14:03:48.000000")

    def test_suffix_constant_matches_what_now_produces(self):
        """Guards against the constant silently drifting from the actual
        format frappe.utils.now() emits (six-digit microseconds). Calls the
        real now() rather than comparing two literals, so a frappe change to
        the fractional-second width would actually be caught here."""
        fractional_part = frappe.utils.now().split(".")[1]
        self.assertEqual(len(fractional_part), len(ZERO_MICROSECONDS_SUFFIX) - 1)
        self.assertEqual(ZERO_MICROSECONDS_SUFFIX, "." + "0" * len(fractional_part))


class TestNormalizeWholeSecondTimestampsHandler(unittest.TestCase):
    """Direct tests of the doc_events handler function, independent of
    whether it is actually wired up (that wiring is covered separately
    below, and end-to-end by TestWildcardHookEndToEnd)."""

    def test_handler_normalizes_whole_second_doc(self):
        doc = _FakeDoc(doctype="ToDo", name="TEST-609", creation="2026-08-25 14:03:48.000000")
        normalize_whole_second_timestamps(doc)
        self.assertEqual(doc.get("creation"), "2026-08-25 14:03:48")

    def test_handler_is_a_noop_for_a_real_timestamp(self):
        """CONTROL for the handler itself."""
        doc = _FakeDoc(doctype="ToDo", name="TEST-609", creation="2026-08-25 14:03:48.123456")
        normalize_whole_second_timestamps(doc)
        self.assertEqual(doc.get("creation"), "2026-08-25 14:03:48.123456")


class TestWildcardHookIsWired(unittest.TestCase):
    """Regression: the normaliser must stay registered under the doc_events
    wildcard key ("*" -- frappe/model/document.py:1653, merged in
    frappe/__init__.py:945) AND under `on_change` specifically -- NOT
    `after_insert` or `on_update`, both of which have gaps a save/submit/
    cancel/db_set can fall through (see module docstring for the two CI/review
    findings that ruled them out). This is a cheap, direct check of the
    source dict (no DB, no hook-cache interaction) that fails immediately if
    someone later removes the wiring, or narrows it back to after_insert or
    on_update, while leaving the handler function itself intact.
    """

    def test_on_change_handler_registered_on_wildcard(self):
        star = doc_events.get("*", {})
        on_change = star.get("on_change", [])
        if isinstance(on_change, str):
            on_change = [on_change]
        self.assertIn(
            "verenigingen.utils.timestamp_normalization.normalize_whole_second_timestamps",
            on_change,
        )

    def test_not_registered_under_after_insert_or_on_update_alone(self):
        """Neither after_insert nor on_update covers every write that can
        produce a whole-second value (see module docstring) -- registering
        under either INSTEAD of on_change would silently reintroduce a gap.
        on_change already covers insert too, so double-registering under
        either would only be wasted double-firing, never a correctness gain."""
        star = doc_events.get("*", {})
        target = "verenigingen.utils.timestamp_normalization.normalize_whole_second_timestamps"
        for event_name in ("after_insert", "on_update"):
            handlers = star.get(event_name, [])
            if isinstance(handlers, str):
                handlers = [handlers]
            self.assertNotIn(target, handlers, f"unexpectedly registered under {event_name}")


class TestWildcardHookEndToEnd(EnhancedTestCase):
    """End-to-end: with the real doc_events wiring dispatched by Frappe,
    a document inserted with a whole-second timestamp must still be able to
    save immediately afterwards, with no intervening reload().

    This is the issue's own deterministic repro (control vs. trigger),
    run through the real insert()/save() lifecycle rather than mocking
    `now()` directly, so it also proves the wildcard hook is dispatched by
    the framework -- not just present in the source dict.

    `app_hooks` is cached in Redis across processes (frappe.__init__.get_hooks)
    and other bench workers on a dev box can repopulate it from the
    *installed* (unfixed) app tree between our edit and this test running.
    Deleting it here, immediately before use in the same process, is the same
    pattern frappe's own frappe/tests/test_hooks.py uses.

    Mitigation #2 (the harness's own `db_insert` patch, see
    `fixtures/enhanced_test_factory.py::_capturing_db_insert`) ALSO
    normalizes on every insert, and runs first (inside `db_insert`, which
    `on_change` fires after). Left installed, it would fix the string before
    the production hook this class exists to test ever got a chance to run
    -- these tests would then pass byte-identically with the production
    `doc_events["*"]` wiring deleted entirely, silently proving nothing.
    Uninstalled in setUp for exactly that reason: this class must exercise
    ONLY the production hook.
    """

    def setUp(self):
        super().setUp()
        frappe.client_cache.delete_value("app_hooks")
        frappe.local.doc_events_hooks = None
        # See class docstring: without this, mitigation #2 masks mitigation
        # #1 and these tests stop being end-to-end at all. tearDown's own
        # addCleanup(self._uninstall_insert_capture) already runs after this
        # test method returns, so no re-install is needed here -- explicit
        # self._track_test_document() calls below cover cleanup for the docs
        # this class creates, same as any other insert-capture-independent
        # test.
        self._uninstall_insert_capture()

    def _insert_and_save_under_frozen_clock(self, frozen_time):
        with freeze_time(frozen_time):
            doc = frappe.get_doc({"doctype": "ToDo", "description": f"#609 repro {frozen_time}"})
            doc.insert()
        self._track_test_document("ToDo", doc.name)
        return doc

    def test_whole_second_insert_then_save_does_not_raise(self):
        """TRIGGER: microsecond == 0. Without the normaliser this raises
        CannotChangeConstantError (db_set path) or TimestampMismatchError
        (direct-save path) -- see #609."""
        doc = self._insert_and_save_under_frozen_clock("2026-08-25 14:03:48")

        # The normaliser must have already fixed the in-memory string by the
        # time insert() returns -- prove the mechanism, not just the absence
        # of an exception three lines down.
        self.assertFalse(str(doc.creation).endswith(".000000"), f"creation={doc.creation!r}")
        self.assertFalse(str(doc.modified).endswith(".000000"), f"modified={doc.modified!r}")

        # direct-save path (no db_set in between): would hit check_if_latest.
        doc.description = "second save, no db_set"
        doc.save()

        # db_set path (refreshes `modified`, so the failure moves to
        # validate_set_only_once on `creation` instead): would hit
        # CannotChangeConstantError, the CI fingerprint from #609.
        doc.db_set("priority", "High")
        doc.description = "third save, after db_set"
        doc.save()

    def test_nonzero_microsecond_insert_then_save_does_not_raise(self):
        """CONTROL: a real (non-whole-second) timestamp was never broken by
        this defect -- this must pass identically with or without the fix,
        proving the normaliser doesn't corrupt the ordinary case.

        Not asserting the exact wall-clock string: `now()` renders in the
        site timezone, which can differ from the UTC instant freeze_time
        freezes (see #609's own CI-timezone note) -- only the microseconds
        are pinned by this test.
        """
        with freeze_time("2026-08-25 14:03:48.123456"):
            doc = frappe.get_doc({"doctype": "ToDo", "description": "#609 control"})
            doc.insert()
        self._track_test_document("ToDo", doc.name)

        self.assertTrue(str(doc.creation).endswith(".123456"), f"creation={doc.creation!r}")

        doc.db_set("priority", "High")
        doc.description = "second save"
        doc.save()


class TestWildcardHookEndToEndOnSubsequentSave(EnhancedTestCase):
    """Regression for the #729 CI recurrence: the whole-second `now()` landed
    on a save() AFTER a normal insert(), not on the insert itself. Mirrors
    `test_erpnext_integration_comprehensive.py::test_financial_report_integration`,
    which calls `.submit()` twice on the same in-memory Sales Invoice (the
    factory's `create_test_sales_invoice` already submits when no `status`
    kwarg is given) -- reproduced here directly with a mocked `now()` rather
    than depending on that test's factory-submits-implicitly shape, so this
    stays sensitive to the mechanism even if that test is later changed.
    """

    def setUp(self):
        super().setUp()
        frappe.client_cache.delete_value("app_hooks")
        frappe.local.doc_events_hooks = None

    def test_whole_second_save_then_second_save_does_not_raise(self):
        """TRIGGER: a normal insert(), then a save() whose own now() call is
        whole-second, then a THIRD save/submit on the same in-memory object
        with no reload() in between. Without on_change coverage (i.e. with
        only after_insert, or only on_update, as this app shipped in turn)
        the third save raises TimestampMismatchError -- verified by
        reproduction before this test was written. This save() goes through
        `db_update`, not `db_insert`, so mitigation #2's harness patch
        cannot mask this one the way it can `TestWildcardHookEndToEnd` above
        -- no need to uninstall it here."""
        from unittest.mock import patch

        import frappe.model.document as fmd

        doc = frappe.get_doc({"doctype": "ToDo", "description": "#729 repro insert"})
        doc.insert()
        self._track_test_document("ToDo", doc.name)
        self.assertFalse(str(doc.creation).endswith(".000000"))

        with patch.object(fmd, "now", lambda: "2026-08-25 14:03:48.000000"):
            doc.description = "first save, whole-second now()"
            doc.save()

        # The normaliser must have fixed the string by the time save() returns,
        # from the on_change hook firing during THIS save -- neither
        # after_insert nor after a plain db_insert-only patch would fire here.
        self.assertFalse(str(doc.modified).endswith(".000000"), f"modified={doc.modified!r}")

        doc.description = "second save, real clock, no reload() in between"
        doc.save()
