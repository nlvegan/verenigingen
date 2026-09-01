"""Tests for #609's mitigation #2: normalizing a whole-second creation/modified
timestamp inside EnhancedTestCase's existing `Document.db_insert` monkey-patch
(`_install_insert_capture` / `_capturing_db_insert`).

See `verenigingen/tests/test_timestamp_normalization_609.py` for the mechanism
and mitigation #1 (the production doc_events["*"] after_insert hook). This
module is separate because it exercises the test HARNESS's own monkey-patch,
not production hook wiring -- the two normalize the same thing from two
different interception points and must not fight each other (whichever runs
first wins; the second becomes a no-op, see both docstrings).

Six whole-second `freeze_time()` decorators already in this app hit this
100% of the time without either mitigation:
test_mollie_retry_policy_coverage_b3.py:236, test_member_scheduler_coverage.py:66,
and four in verenigingen_payments/doctype/mollie_settings/test_mollie_settings.py.
"""

from freezegun import freeze_time

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestHarnessNormalizesWholeSecondTimestamps(EnhancedTestCase):
    def test_whole_second_insert_then_save_does_not_raise(self):
        """TRIGGER: without the harness normalization this raises
        CannotChangeConstantError (db_set path) / TimestampMismatchError
        (direct-save path) -- the exact CI fingerprint from #609."""
        with freeze_time("2026-08-25 14:03:48"):
            doc = frappe.get_doc({"doctype": "ToDo", "description": "#609 harness repro"})
            doc.insert()
        self._track_test_document("ToDo", doc.name)

        # The normalization must be OBSERVABLE, not silent (the whole point of
        # the harness-fidelity trade-off note) -- prove it actually fired for
        # THIS document, not just that no exception was raised.
        matches = [
            entry for entry in self._normalized_whole_second_timestamps if entry[:2] == ("ToDo", doc.name)
        ]
        self.assertTrue(matches, f"Expected a normalization record for {doc.name}, got none")
        self.assertIn("creation", matches[0][2])

        self.assertFalse(str(doc.creation).endswith(".000000"), f"creation={doc.creation!r}")

        doc.description = "second save, no db_set"
        doc.save()

        doc.db_set("priority", "High")
        doc.description = "third save, after db_set"
        doc.save()

    def test_nonzero_microsecond_insert_is_not_recorded(self):
        """CONTROL: an ordinary (non-whole-second) insert must not appear in
        the normalization log -- proves the harness isn't over-triggering."""
        before_count = len(self._normalized_whole_second_timestamps)
        with freeze_time("2026-08-25 14:03:48.654321"):
            doc = frappe.get_doc({"doctype": "ToDo", "description": "#609 harness control"})
            doc.insert()
        self._track_test_document("ToDo", doc.name)

        self.assertEqual(len(self._normalized_whole_second_timestamps), before_count)
        self.assertTrue(str(doc.creation).endswith(".654321"), f"creation={doc.creation!r}")

        doc.db_set("priority", "High")
        doc.description = "second save"
        doc.save()
