"""Tests for the MijnRood Member Reconciliation report.

Focuses on the classification logic (pure function of the two fetched
dicts). The MijnRood fetch itself is mocked to avoid live SSH tunneling.
"""

from unittest.mock import patch

import frappe

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
        self.assertEqual(row["type"], "Member")

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

    # --- Application classification ---------------------------------------

    def test_pending_application_matching_mijnrood_is_ok(self):
        """Pending Member matching an open admin_membership_application row → OK."""
        mr_app = {
            10: {
                "mijnrood_id": 10,
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "status_id": None,
                "status_name": "application (pending review)",
                "allowed_access": 0,
            }
        }
        ours_app = {
            10: {
                "mijnrood_id": 10,
                "member_name": "Assoc-Member-10",
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "our_status": "Pending",
            }
        }
        [row] = report._classify(mr_app, ours_app, kind="Application")
        self.assertEqual(row["discrepancy"], "OK")
        self.assertEqual(row["type"], "Application")
        self.assertEqual(row["mijnrood_status"], "application (pending review)")

    def test_pending_application_only_in_verenigingen(self):
        """Our side has a Pending Member with member_id absent from MijnRood
        applications → reported as Only in Verenigingen, type=Application."""
        ours_app = {
            10: {
                "mijnrood_id": 10,
                "member_name": "Assoc-Member-10",
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "our_status": "Pending",
            }
        }
        [row] = report._classify({}, ours_app, kind="Application")
        self.assertEqual(row["discrepancy"], "Only in Verenigingen")
        self.assertEqual(row["type"], "Application")

    def test_application_only_in_mijnrood(self):
        """MijnRood has an open application with no Pending Member on our side."""
        mr_app = {
            10: {
                "mijnrood_id": 10,
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "status_id": None,
                "status_name": "application (pending review)",
                "allowed_access": 0,
            }
        }
        [row] = report._classify(mr_app, {}, kind="Application")
        self.assertEqual(row["discrepancy"], "Only in MijnRood")
        self.assertEqual(row["type"], "Application")
        self.assertEqual(row["mijnrood_status"], "application (pending review)")

    def test_application_status_mismatch_when_we_already_promoted(self):
        """Our Member is no longer Pending but MijnRood still has an open
        application row → flagged as Status mismatch.

        This catches the case where an application was promoted on our side
        without us deleting the corresponding MijnRood application row.
        """
        mr_app = {
            10: {
                "mijnrood_id": 10,
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "status_id": None,
                "status_name": "application (pending review)",
                "allowed_access": 0,
            }
        }
        ours_promoted = {
            10: {
                "mijnrood_id": 10,
                "member_name": "Assoc-Member-10",
                "first_name": "P",
                "last_name": "Q",
                "email": "p@x",
                "our_status": "Active",
            }
        }
        [row] = report._classify(mr_app, ours_promoted, kind="Application")
        self.assertEqual(row["discrepancy"], "Status mismatch")
        self.assertEqual(row["type"], "Application")

    # --- Bucketing in _fetch_our_members -----------------------------------

    def test_pending_member_is_bucketed_as_application(self):
        """Members with status=Pending must land in the applicants dict, not
        the members dict.

        Uses real Member rows via the test factory (no DB mocks) so we exercise
        the actual frappe.get_all path.
        """
        active = self.create_test_member(
            first_name=f"Active{self.uid}",
            last_name="Reconcile",
            email=f"active.recon.{self.uid}@verenigingen.test",
            birth_date="1990-01-01",
        )
        pending = self.create_test_member(
            first_name=f"Pending{self.uid}",
            last_name="Reconcile",
            email=f"pending.recon.{self.uid}@verenigingen.test",
            birth_date="1990-01-01",
        )

        # Assign deterministic member_ids and put `pending` into status=Pending.
        # self.uid is a string suffix; combine into a numeric id below.
        uid_int = abs(hash(str(self.uid))) % 1_000_000
        active_mid = 9_000_001 + uid_int
        pending_mid = 9_000_002 + uid_int
        frappe.db.set_value("Member", active.name, "member_id", str(active_mid))
        frappe.db.set_value("Member", active.name, "status", "Active")
        frappe.db.set_value("Member", pending.name, "member_id", str(pending_mid))
        frappe.db.set_value("Member", pending.name, "status", "Pending")

        members, applicants = report._fetch_our_members()

        self.assertIn(active_mid, members)
        self.assertNotIn(active_mid, applicants)
        self.assertIn(pending_mid, applicants)
        self.assertNotIn(pending_mid, members)
        self.assertEqual(applicants[pending_mid]["our_status"], "Pending")
        self.assertEqual(members[active_mid]["our_status"], "Active")

    # --- End-to-end via execute() with both fetches mocked ------------------

    def test_execute_summary_counts(self):
        """execute() integrates classify across kinds and produces the summary.

        Both data sources are mocked at the report's own seam so we do not
        touch frappe.get_all (forbidden in integration tests by hook).
        """
        mr_members = {
            1: _mr(1, status_id=1),  # OK
            2: _mr(2, status_id=6),  # status mismatch vs Active below
            3: _mr(3, status_id=1),  # only in mijnrood
        }
        our_members = {
            1: _ours(1, status="Active"),
            2: _ours(2, status="Active"),
            9: _ours(9, status="Active"),  # only in ours
        }

        with patch.object(
            report, "_fetch_mijnrood_data", return_value=(mr_members, {})
        ), patch.object(report, "_fetch_our_members", return_value=(our_members, {})):
            _columns, rows, _msg, _chart, summary = report.execute({"discrepancy_only": 0})

        disc_counts = {r["discrepancy"] for r in rows}
        self.assertIn("OK", disc_counts)
        self.assertIn("Status mismatch", disc_counts)
        self.assertIn("Only in MijnRood", disc_counts)
        self.assertIn("Only in Verenigingen", disc_counts)

        labels = [s["label"] for s in summary]
        self.assertTrue(any("Status Mismatch" in l for l in labels))
        # 1 status mismatch (id=2), 1 only in MijnRood (id=3), 1 only in ours (id=9), 1 OK (id=1)
        mismatch_card = next(s for s in summary if "Mismatch" in s["label"])
        only_mr_card = next(s for s in summary if "Only in MijnRood" in s["label"])
        only_us_card = next(s for s in summary if "Only in Verenigingen" in s["label"])
        self.assertEqual(mismatch_card["value"], 1)
        self.assertEqual(only_mr_card["value"], 1)
        self.assertEqual(only_us_card["value"], 1)

    def test_execute_does_not_flag_pending_application_as_only_in_verenigingen(self):
        """Regression: a pending application matched on both sides must not
        be classified as Only in Verenigingen.

        Originally the report only fetched admin_member, so any Pending Member
        on our side appeared as Only in Verenigingen — even when MijnRood had
        a matching admin_membership_application row.
        """
        mr_apps = {10: _mr_app(10)}
        our_applicants = {10: _ours(10, status="Pending")}

        with patch.object(
            report, "_fetch_mijnrood_data", return_value=({}, mr_apps)
        ), patch.object(report, "_fetch_our_members", return_value=({}, our_applicants)):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 0})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["discrepancy"], "OK")
        self.assertEqual(rows[0]["type"], "Application")

    def test_execute_filters_ok_when_discrepancy_only(self):
        mr_members = {
            1: _mr(1, status_id=1),  # OK
            2: _mr(2, status_id=6),  # mismatch
        }
        our_members = {
            1: _ours(1, status="Active"),
            2: _ours(2, status="Active"),
        }

        with patch.object(
            report, "_fetch_mijnrood_data", return_value=(mr_members, {})
        ), patch.object(report, "_fetch_our_members", return_value=(our_members, {})):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 1})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["discrepancy"], "Status mismatch")

    def test_execute_hides_terminated_by_default(self):
        our_members = {1: _ours(1, status="Quit")}
        with patch.object(
            report, "_fetch_mijnrood_data", return_value=({}, {})
        ), patch.object(report, "_fetch_our_members", return_value=(our_members, {})):
            _c, rows, _m, _ch, _s = report.execute({"discrepancy_only": 0})
        self.assertEqual(rows, [], "Quit member should be hidden without include_terminated")

    def test_execute_includes_terminated_when_flag_set(self):
        our_members = {1: _ours(1, status="Quit")}
        with patch.object(
            report, "_fetch_mijnrood_data", return_value=({}, {})
        ), patch.object(report, "_fetch_our_members", return_value=(our_members, {})):
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


def _mr_app(mid: int, email: str = "m@example") -> dict:
    """Build a stub admin_membership_application row dict (no status_id)."""
    return {
        "mijnrood_id": mid,
        "first_name": "F",
        "last_name": "L",
        "email": email,
        "status_id": None,
        "status_name": "application (pending review)",
        "allowed_access": 0,
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
