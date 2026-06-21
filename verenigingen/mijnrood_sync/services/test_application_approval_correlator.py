# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for ApplicationApprovalCorrelator.

The correlator collapses an admin_membership_application 'Deleted' event +
an admin_member 'New' event (same sync run) into one synthesized 'Approved'
event, marking the raw pair Ignored.

These tests create REAL MijnRood Sync Events in the test_site_4 DB and run
the full correlate() pipeline, plus drive the confidence-check / summary
helpers directly with row dicts. Nothing is stubbed — this is pure
correlation business logic over real rows.
"""

import json

import frappe

from verenigingen.mijnrood_sync.services.application_approval_correlator import (
    ApplicationApprovalCorrelator,
    get_correlator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCorrelatorHelpers(EnhancedTestCase):
    """Direct unit coverage of the pure helpers (_field, summary, confidence)."""

    def setUp(self):
        super().setUp()
        self.c = ApplicationApprovalCorrelator()

    # ---- _field -----------------------------------------------------------

    def test_field_extracts_and_strips(self):
        raw = json.dumps({"email": "  A@B.com ", "mollie_customer_id": "cst_1"})
        self.assertEqual(self.c._field(raw, "email"), "A@B.com")
        self.assertEqual(self.c._field(raw, "mollie_customer_id"), "cst_1")

    def test_field_none_and_empty_and_missing(self):
        self.assertIsNone(self.c._field(None, "x"))
        self.assertIsNone(self.c._field(json.dumps({"x": ""}), "x"))
        self.assertIsNone(self.c._field(json.dumps({"x": None}), "x"))
        self.assertIsNone(self.c._field(json.dumps({"y": "z"}), "x"))

    def test_field_invalid_json_returns_none(self):
        self.assertIsNone(self.c._field("not-json{", "x"))

    def test_field_coerces_non_string(self):
        self.assertEqual(self.c._field(json.dumps({"id": 42}), "id"), "42")

    # ---- _build_summary ---------------------------------------------------

    def test_build_summary_full_name_and_ids(self):
        old = {"id": 11, "first_name": "Jan"}
        new = {"id": 99, "first_name": "Jan", "last_name": "de Vries"}
        summary = self.c._build_summary(old, new)
        self.assertIn("Jan de Vries", summary)
        self.assertIn("11", summary)
        self.assertIn("99", summary)

    def test_build_summary_unknown_when_no_name(self):
        summary = self.c._build_summary({}, {})
        self.assertIn("unknown", summary)

    # ---- _passes_confidence_check ----------------------------------------

    def _evt(self, **fields):
        """Build a fake event dict with old_data/new_data JSON blobs."""
        return fields

    def test_confidence_blocks_lastname_mismatch(self):
        d = {"name": "D1", "old_data": json.dumps({"last_name": "Smith"})}
        c = {"name": "C1", "new_data": json.dumps({"last_name": "Jones"})}
        self.assertFalse(self.c._passes_confidence_check(d, c))

    def test_confidence_passes_lastname_match(self):
        d = {"name": "D1", "old_data": json.dumps({"last_name": "Smith"})}
        c = {"name": "C1", "new_data": json.dumps({"last_name": "smith"})}  # case-insensitive
        self.assertTrue(self.c._passes_confidence_check(d, c))

    def test_confidence_vetoed_by_mollie_mismatch(self):
        d = {"name": "D1", "old_data": json.dumps({"last_name": "X", "mollie_customer_id": "a"})}
        c = {"name": "C1", "new_data": json.dumps({"last_name": "X", "mollie_customer_id": "b"})}
        self.assertFalse(self.c._passes_confidence_check(d, c))

    def test_confidence_vetoed_by_dob_mismatch(self):
        d = {"name": "D1", "old_data": json.dumps({"last_name": "X", "date_of_birth": "1990-01-01"})}
        c = {"name": "C1", "new_data": json.dumps({"last_name": "X", "date_of_birth": "1991-02-02"})}
        self.assertFalse(self.c._passes_confidence_check(d, c))

    def test_confidence_allows_missing_secondary_signals(self):
        """Matching last names with no mollie/dob on either side still passes."""
        d = {"name": "D1", "old_data": json.dumps({"last_name": "X"})}
        c = {"name": "C1", "new_data": json.dumps({"last_name": "X"})}
        self.assertTrue(self.c._passes_confidence_check(d, c))


class TestCorrelateFullPipeline(EnhancedTestCase):
    """End-to-end correlate() over real MijnRood Sync Events."""

    def _make_event(self, sync_run_id, event_type, table, row_id, data_field, data):
        evt = frappe.new_doc("MijnRood Sync Event")
        evt.event_type = event_type
        evt.mijnrood_table = table
        evt.mijnrood_row_id = row_id
        evt.status = "Pending"
        evt.sync_run_id = sync_run_id
        setattr(evt, data_field, json.dumps(data))
        evt.insert(ignore_permissions=True)
        return evt

    def _deletion(self, run, row_id, data):
        return self._make_event(run, "Deleted", "admin_membership_application", row_id, "old_data", data)

    def _creation(self, run, row_id, data):
        return self._make_event(run, "New", "admin_member", row_id, "new_data", data)

    def _new_run(self):
        return f"test-run-{frappe.generate_hash()[:10]}"

    def test_no_candidates_returns_zero(self):
        run = self._new_run()
        result = get_correlator().correlate(run)
        self.assertEqual(result, 0)

    def test_mollie_match_collapses_pair(self):
        run = self._new_run()
        d = self._deletion(run, 1, {"id": 1, "mollie_customer_id": "cst_match", "last_name": "Doe"})
        c = self._creation(run, 2, {"id": 2, "mollie_customer_id": "cst_match", "last_name": "Doe"})

        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 1)

        # Raw pair marked Ignored with cross-reference note
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", d.name, "status"), "Ignored")
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", c.name, "status"), "Ignored")
        note = frappe.db.get_value("MijnRood Sync Event", d.name, "review_notes")
        self.assertIn("Superseded by", note)

        # Synthesized Approved event exists for this run
        approved = frappe.get_all(
            "MijnRood Sync Event",
            filters={"sync_run_id": run, "event_type": "Approved"},
            fields=["name", "mijnrood_row_id", "change_tags"],
        )
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].mijnrood_row_id, 2)  # creation row id
        self.assertEqual(approved[0].change_tags, "Approved")

    def test_email_match_collapses_when_lastname_agrees(self):
        run = self._new_run()
        d = self._deletion(run, 1, {"id": 1, "email": "Same@x.com", "last_name": "Vega"})
        c = self._creation(run, 2, {"id": 2, "email": "same@x.com", "last_name": "vega"})

        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 1)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", d.name, "status"), "Ignored")
        approved = frappe.get_all(
            "MijnRood Sync Event", filters={"sync_run_id": run, "event_type": "Approved"}, fields=["name"]
        )
        self.assertEqual(len(approved), 1)

    def test_email_match_blocked_by_lastname_mismatch(self):
        run = self._new_run()
        d = self._deletion(run, 1, {"id": 1, "email": "same@x.com", "last_name": "Smith"})
        c = self._creation(run, 2, {"id": 2, "email": "same@x.com", "last_name": "Jones"})

        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 0)
        # Both stay Pending
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", d.name, "status"), "Pending")
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", c.name, "status"), "Pending")

    def test_ambiguous_mollie_match_left_alone(self):
        """Two creations sharing one Mollie id -> ambiguous, no collapse."""
        run = self._new_run()
        d = self._deletion(run, 1, {"id": 1, "mollie_customer_id": "dup", "last_name": "X"})
        c1 = self._creation(run, 2, {"id": 2, "mollie_customer_id": "dup", "last_name": "X"})
        c2 = self._creation(run, 3, {"id": 3, "mollie_customer_id": "dup", "last_name": "X"})

        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 0)
        for e in (d, c1, c2):
            self.assertEqual(frappe.db.get_value("MijnRood Sync Event", e.name, "status"), "Pending")

    def test_unmatched_deletion_left_alone(self):
        """A deletion with no creation counterpart (a rejection) stays Pending."""
        run = self._new_run()
        d = self._deletion(run, 1, {"id": 1, "email": "lonely@x.com", "last_name": "Nobody"})
        # An unrelated creation
        c = self._creation(run, 2, {"id": 2, "email": "other@x.com", "last_name": "Else"})

        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 0)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", d.name, "status"), "Pending")
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", c.name, "status"), "Pending")

    def test_mollie_preferred_over_email_and_one_creation_consumed(self):
        """Mollie pass consumes the creation; the email pass can't re-pair it."""
        run = self._new_run()
        # deletion + creation share Mollie id AND email
        d = self._deletion(
            run, 1, {"id": 1, "mollie_customer_id": "cstZ", "email": "z@x.com", "last_name": "Z"}
        )
        c = self._creation(
            run, 2, {"id": 2, "mollie_customer_id": "cstZ", "email": "z@x.com", "last_name": "Z"}
        )
        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 1)
        approved = frappe.get_all(
            "MijnRood Sync Event",
            filters={"sync_run_id": run, "event_type": "Approved"},
            fields=["name"],
        )
        # Exactly one Approved event (not double-paired)
        self.assertEqual(len(approved), 1)

    def test_email_pass_vetoed_by_mollie_mismatch(self):
        """Same email + same last name, but conflicting Mollie ids -> veto."""
        run = self._new_run()
        d = self._deletion(
            run, 1, {"id": 1, "email": "v@x.com", "last_name": "Veto", "mollie_customer_id": "a"}
        )
        c = self._creation(
            run, 2, {"id": 2, "email": "v@x.com", "last_name": "Veto", "mollie_customer_id": "b"}
        )
        collapsed = ApplicationApprovalCorrelator().correlate(run)
        self.assertEqual(collapsed, 0)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", d.name, "status"), "Pending")
