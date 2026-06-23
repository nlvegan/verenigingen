"""Gap-fill tests for the *MijnRood Member Reconciliation* report
(``verenigingen/verenigingen/report/mijnrood_member_reconciliation/``).

The existing suite (``tests/member/test_mijnrood_member_reconciliation.py``)
covers ``_classify`` and the ``execute`` orchestration (both fetch seams
mocked). This file adds the previously-uncovered presentation helpers and edge
branches:

  * ``_columns`` structure;
  * ``_summary`` -- counts and the Red/Orange/Green indicator logic, both with
    discrepancies and on an all-OK (all-Green) roster;
  * ``_chart`` -- the populated donut and the ``None``-when-empty branch;
  * ``_compose_name`` -- first-only / last-only / both / neither;
  * ``_format_mijnrood_status`` -- known id, unknown id (str fallback), and the
    application (status_id is None) fallback to status_name;
  * ``execute`` -- the deterministic sort ordering of rows.

The live SSH fetch (``_fetch_mijnrood_data``) is out of scope (needs a tunnel);
where ``execute`` is exercised both fetch seams are patched at the report's own
boundary (not at any ``frappe.db`` call), matching the existing suite.
"""

from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.mijnrood_member_reconciliation import (
    mijnrood_member_reconciliation as report,
)


class TestMijnRoodReconciliationGapfill(EnhancedTestCase):
    # ------------------------------------------------------------- columns

    def test_columns_structure(self):
        columns = report._columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(fieldnames[0], "type")
        self.assertIn("mijnrood_id", fieldnames)
        self.assertIn("discrepancy", fieldnames)
        member_col = next(c for c in columns if c["fieldname"] == "member")
        self.assertEqual(member_col["options"], "Member")

    # ------------------------------------------------------------- summary

    def test_summary_counts_and_indicators_with_discrepancies(self):
        rows = [
            {"discrepancy": "OK"},
            {"discrepancy": "Status mismatch"},
            {"discrepancy": "Only in MijnRood"},
            {"discrepancy": "Only in MijnRood"},
            {"discrepancy": "Only in Verenigingen"},
        ]
        summary = report._summary(rows)
        by_label = {s["label"]: s for s in summary}

        self.assertEqual(by_label["Status Mismatch"]["value"], 1)
        self.assertEqual(by_label["Status Mismatch"]["indicator"], "Red")
        self.assertEqual(by_label["Only in MijnRood"]["value"], 2)
        self.assertEqual(by_label["Only in MijnRood"]["indicator"], "Orange")
        self.assertEqual(by_label["Only in Verenigingen"]["value"], 1)
        self.assertEqual(by_label["Only in Verenigingen"]["indicator"], "Orange")

    def test_summary_all_ok_is_all_green(self):
        rows = [{"discrepancy": "OK"}, {"discrepancy": "OK"}]
        summary = report._summary(rows)
        self.assertTrue(all(s["indicator"] == "Green" for s in summary))
        ok_card = next(s for s in summary if s["label"].startswith("OK"))
        self.assertEqual(ok_card["value"], 2)

    def test_summary_empty_rows(self):
        summary = report._summary([])
        # All four cards present, all zero, all Green.
        self.assertEqual(len(summary), 4)
        self.assertTrue(all(s["value"] == 0 for s in summary))
        self.assertTrue(all(s["indicator"] == "Green" for s in summary))

    # ------------------------------------------------------------- chart

    def test_chart_none_when_empty(self):
        self.assertIsNone(report._chart([]))

    def test_chart_buckets_by_discrepancy(self):
        rows = [
            {"discrepancy": "OK"},
            {"discrepancy": "OK"},
            {"discrepancy": "Status mismatch"},
        ]
        chart = report._chart(rows)
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "donut")
        labels = chart["data"]["labels"]
        values = chart["data"]["datasets"][0]["values"]
        bucket = dict(zip(labels, values))
        self.assertEqual(bucket["OK"], 2)
        self.assertEqual(bucket["Status mismatch"], 1)

    # ------------------------------------------------------- _compose_name

    def test_compose_name_variants(self):
        self.assertEqual(report._compose_name("Jan", "de Vries"), "Jan de Vries")
        self.assertEqual(report._compose_name("Jan", None), "Jan")
        self.assertEqual(report._compose_name(None, "de Vries"), "de Vries")
        self.assertEqual(report._compose_name(None, None), "")
        self.assertEqual(report._compose_name("  ", "  "), "")

    # ----------------------------------------------- _format_mijnrood_status

    def test_format_status_known_id(self):
        labels = {1: "lid", 6: "geschorst"}
        self.assertEqual(report._format_mijnrood_status({"status_id": 1}, labels), "lid")

    def test_format_status_unknown_id_falls_back_to_str(self):
        labels = {1: "lid"}
        self.assertEqual(report._format_mijnrood_status({"status_id": 99}, labels), "99")

    def test_format_status_application_uses_status_name(self):
        m = {"status_id": None, "status_name": "application (pending review)"}
        self.assertEqual(
            report._format_mijnrood_status(m, {}), "application (pending review)"
        )

    def test_format_status_application_missing_name_is_empty(self):
        self.assertEqual(report._format_mijnrood_status({"status_id": None}, {}), "")

    # ------------------------------------------------------------- sort order

    def test_execute_sort_ordering(self):
        mr_members = {
            1: _mr(1, status_id=1),  # OK
            2: _mr(2, status_id=6),  # Status mismatch vs Active
            3: _mr(3, status_id=1),  # Only in MijnRood
        }
        our_members = {
            1: _ours(1, status="Active"),
            2: _ours(2, status="Active"),
        }
        with patch.object(
            report, "_fetch_mijnrood_data", return_value=(mr_members, {})
        ), patch.object(report, "_fetch_our_members", return_value=(our_members, {})):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 0})

        discrepancies = [r["discrepancy"] for r in rows]
        # Sort key is (discrepancy != "OK", discrepancy, type, mijnrood_id): OK
        # rows (key False=0) sort FIRST, then the non-OK group alphabetically
        # ("Only in MijnRood" < "Status mismatch").
        self.assertEqual(discrepancies[0], "OK")
        self.assertEqual(
            discrepancies, ["OK", "Only in MijnRood", "Status mismatch"]
        )


def _mr(mid, status_id=1, email="m@example"):
    return {
        "mijnrood_id": mid,
        "first_name": "F",
        "last_name": "L",
        "email": email,
        "status_id": status_id,
        "status_name": f"status-{status_id}",
        "allowed_access": 1 if status_id in (1, 2) else 0,
    }


def _ours(mid, status="Active", email="u@example"):
    return {
        "mijnrood_id": mid,
        "member_name": f"Assoc-Member-{mid}",
        "first_name": "F",
        "last_name": "L",
        "email": email,
        "our_status": status,
    }
