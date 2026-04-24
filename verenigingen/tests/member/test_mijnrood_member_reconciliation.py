"""Tests for the MijnRood Member Reconciliation report.

Focuses on the classification logic (pure function of the two fetched
dicts). The MijnRood fetch itself is mocked to avoid live SSH tunneling.
"""

from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.mijnrood_member_reconciliation import (
    mijnrood_member_reconciliation as report,
)


class TestMijnRoodMemberReconciliation(EnhancedTestCase):
    """Classification edge cases."""

    # --- Pure classifier tests (no DB) -------------------------------------

    def test_both_active_and_matching_is_ok(self):
        mr = {
            1001: {
                "mijnrood_id": 1001,
                "first_name": "A",
                "last_name": "B",
                "email": "a@x",
                "status_id": 1,  # lid
                "status_name": "lid",
                "allowed_access": 1,
            }
        }
        ours = {
            1001: {
                "mijnrood_id": 1001,
                "member_name": "Assoc-Member-1001",
                "first_name": "A",
                "last_name": "B",
                "email": "a@x",
                "our_status": "Active",
            }
        }
        [row] = report._classify(mr, ours)
        self.assertEqual(row["discrepancy"], "OK")
        self.assertEqual(row["mijnrood_id"], 1001)

    def test_aspirant_and_active_is_ok_both_active_category(self):
        mr = {1: {**_mr(1, status_id=2), "allowed_access": 1}}
        ours = {1: _ours(1, status="Active")}
        [row] = report._classify(mr, ours)
        self.assertEqual(row["discrepancy"], "OK")

    def test_suspended_matches_geschorst(self):
        mr = {1: {**_mr(1, status_id=6), "allowed_access": 0}}
        ours = {1: _ours(1, status="Suspended")}
        [row] = report._classify(mr, ours)
        self.assertEqual(row["discrepancy"], "OK")

    def test_mijnrood_suspended_but_ours_active_is_mismatch(self):
        mr = {1: {**_mr(1, status_id=6), "allowed_access": 0}}
        ours = {1: _ours(1, status="Active")}
        [row] = report._classify(mr, ours)
        self.assertEqual(row["discrepancy"], "Status mismatch")
        self.assertIn("eschorst", row["mijnrood_status"])  # "geschorst" or "Geschorst"

    def test_mijnrood_quit_but_ours_active_is_mismatch(self):
        mr = {1: {**_mr(1, status_id=3), "allowed_access": 0}}
        ours = {1: _ours(1, status="Active")}
        [row] = report._classify(mr, ours)
        self.assertEqual(row["discrepancy"], "Status mismatch")

    def test_only_in_mijnrood(self):
        mr = {1: _mr(1, status_id=1)}
        [row] = report._classify(mr, {})
        self.assertEqual(row["discrepancy"], "Only in MijnRood")
        self.assertIsNone(row["member"])
        self.assertIsNone(row["our_status"])

    def test_only_in_verenigingen(self):
        ours = {1: _ours(1, status="Active")}
        [row] = report._classify({}, ours)
        self.assertEqual(row["discrepancy"], "Only in Verenigingen")
        self.assertEqual(row["member"], "Assoc-Member-1")
        self.assertIsNone(row["mijnrood_status"])

    def test_email_divergence_shown_with_slash(self):
        mr = {1: _mr(1, email="new@x")}
        ours = {1: _ours(1, email="old@x")}
        [row] = report._classify(mr, ours)
        self.assertIn("new@x", row["email"])
        self.assertIn("old@x", row["email"])

    # --- End-to-end via execute() with mocked fetch ------------------------

    def test_execute_summary_counts(self):
        mr = {
            1: _mr(1, status_id=1),  # OK
            2: _mr(2, status_id=6),  # status mismatch vs Active below
            3: _mr(3, status_id=1),  # only in mijnrood
        }
        ours_rows = [
            {"name": "Assoc-Member-1", "member_id": "1", "status": "Active"},
            {"name": "Assoc-Member-2", "member_id": "2", "status": "Active"},
            {"name": "Assoc-Member-9", "member_id": "9", "status": "Active"},  # only in ours
        ]

        with patch.object(report, "_fetch_mijnrood_members", return_value=mr), patch(
            "frappe.get_all", return_value=ours_rows
        ):
            columns, rows, _msg, chart, summary = report.execute({"discrepancy_only": 0})

        disc_counts = {r["discrepancy"] for r in rows}
        self.assertIn("OK", disc_counts)
        self.assertIn("Status mismatch", disc_counts)
        self.assertIn("Only in MijnRood", disc_counts)
        self.assertIn("Only in Verenigingen", disc_counts)

        # Summary cards are ordered: Status mismatch, Only in MijnRood, Only in Verenigingen, OK
        labels = [s["label"] for s in summary]
        values = {s["label"]: s["value"] for s in summary}
        self.assertTrue(any("Status Mismatch" in l for l in labels))
        # 1 status mismatch (id=2), 1 only in MijnRood (id=3), 1 only in ours (id=9), 1 OK (id=1)
        mismatch_card = next(s for s in summary if "Mismatch" in s["label"])
        only_mr_card = next(s for s in summary if "Only in MijnRood" in s["label"])
        only_us_card = next(s for s in summary if "Only in Verenigingen" in s["label"])
        self.assertEqual(mismatch_card["value"], 1)
        self.assertEqual(only_mr_card["value"], 1)
        self.assertEqual(only_us_card["value"], 1)

    def test_execute_filters_ok_when_discrepancy_only(self):
        mr = {
            1: _mr(1, status_id=1),  # OK
            2: _mr(2, status_id=6),  # mismatch
        }
        ours_rows = [
            {"name": "Assoc-Member-1", "member_id": "1", "status": "Active"},
            {"name": "Assoc-Member-2", "member_id": "2", "status": "Active"},
        ]

        with patch.object(report, "_fetch_mijnrood_members", return_value=mr), patch(
            "frappe.get_all", return_value=ours_rows
        ):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 1})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["discrepancy"], "Status mismatch")

    def test_execute_hides_terminated_by_default(self):
        ours_rows = [
            {"name": "Assoc-Member-1", "member_id": "1", "status": "Quit"},
        ]
        with patch.object(report, "_fetch_mijnrood_members", return_value={}), patch(
            "frappe.get_all", return_value=ours_rows
        ):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 0})
        self.assertEqual(rows, [], "Quit member should be hidden without include_terminated")

    def test_execute_includes_terminated_when_flag_set(self):
        ours_rows = [
            {"name": "Assoc-Member-1", "member_id": "1", "status": "Quit"},
        ]
        with patch.object(report, "_fetch_mijnrood_members", return_value={}), patch(
            "frappe.get_all", return_value=ours_rows
        ):
            _c, rows, _m, _ch, _s = report.execute(
                {"discrepancy_only": 0, "include_terminated": 1}
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["our_status"], "Quit")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mr(mid: int, status_id: int = 1, email: str = "m@example") -> dict:
    return {
        "mijnrood_id": mid,
        "first_name": "F",
        "last_name": "L",
        "email": email,
        "status_id": status_id,
        "status_name": f"status-{status_id}",
        "allowed_access": 1 if status_id in (1, 2) else 0,
    }


def _ours(mid: int, status: str = "Active", email: str = "u@example") -> dict:
    return {
        "mijnrood_id": mid,
        "member_name": f"Assoc-Member-{mid}",
        "first_name": "F",
        "last_name": "L",
        "email": email,
        "our_status": status,
    }
