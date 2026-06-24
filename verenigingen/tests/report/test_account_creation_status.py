"""
Real-integration tests for the *Account Creation Status* script report
(``verenigingen/verenigingen/report/account_creation_status/``).

The report tracks, per Member, the existence and linkage of the related
records (User / Volunteer / Employee / Customer / Address / Membership /
Dues Schedule) plus the most recent Account Creation Request status and
failure reason. It also returns a summary block and a completion bar chart.

These tests seed real Members (some with Users / Volunteers / Customers /
Account Creation Requests) and exercise:
  * the column structure and the 5-tuple execute contract;
  * the data-row computation (has_* / *_linked flags);
  * each ``status_filter`` branch (Missing User / Missing Volunteer /
    Missing Employee / Failed Requests / Complete);
  * the failure-reason breakdown branch in the summary;
  * the summary and chart shape.

Tests run as Administrator. All data is auto-cleaned.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.account_creation_status import account_creation_status as report


class TestAccountCreationStatusReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member(self, with_customer=False, **kwargs):
        return self.create_test_member(
            chapter=False,
            first_name="Acct",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"acct.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=with_customer,
            **kwargs,
        )

    def _row_for(self, data, member_name):
        return next((r for r in data if r["member_name"] == member_name), None)

    def _make_failed_request(self, member, failure_reason, retry_count=0):
        """Create an Account Creation Request for ``member`` and mark it
        Failed with the given reason (the report keys off the latest request
        per source_record)."""
        acr = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email,
                "full_name": member.full_name,
                "priority": "Normal",
                "role_profile": "Verenigingen Member",
                "business_justification": "Report coverage test",
            }
        )
        acr.insert(ignore_permissions=True)
        self.track_doc("Account Creation Request", acr.name)
        frappe.db.set_value(
            "Account Creation Request",
            acr.name,
            {"status": "Failed", "failure_reason": failure_reason, "retry_count": retry_count},
            update_modified=False,
        )
        return acr

    # ------------------------------------------------------------- columns / execute

    def test_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertIn("member_name", fieldnames)
        self.assertIn("has_user", fieldnames)
        self.assertIn("account_request_status", fieldnames)
        self.assertIn("failure_reason", fieldnames)

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _none, chart, summary = result
        self.assertEqual(_none, None)
        self.assertIsInstance(data, list)
        self.assertIsInstance(summary, list)
        self.assertIsNotNone(chart)

    # ------------------------------------------------------------- data rows

    def test_member_appears_with_flags(self):
        member = self._member()
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row, "member must appear in the status report")
        self.assertEqual(row["full_name"], member.full_name)
        # Fresh member with no user/volunteer/employee.
        self.assertEqual(row["has_volunteer"], 0)

    def test_member_with_customer_has_customer_flags(self):
        member = self._member(with_customer=True)
        member.reload()
        self.assertTrue(member.customer)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["has_customer"], 1)
        self.assertEqual(row["customer_linked"], 1)

    def test_member_with_volunteer_has_volunteer_flag(self):
        member = self._member()
        volunteer = self.create_test_volunteer(member=member.name)
        self.assertEqual(volunteer.member, member.name)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["has_volunteer"], 1)

    # ------------------------------------------------------------- status filters

    def test_status_filter_missing_volunteer(self):
        no_vol = self._member()
        has_vol = self._member()
        self.create_test_volunteer(member=has_vol.name)

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"status_filter": "Missing Volunteer"})
        ids = {r["member_name"] for r in data}
        self.assertIn(no_vol.name, ids)
        self.assertNotIn(has_vol.name, ids)

    def test_status_filter_missing_employee(self):
        member = self._member()
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"status_filter": "Missing Employee"})
        ids = {r["member_name"] for r in data}
        self.assertIn(member.name, ids, "member with no Employee must appear under Missing Employee")

    def test_status_filter_missing_user(self):
        member = self._member()  # no user linked
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"status_filter": "Missing User"})
        ids = {r["member_name"] for r in data}
        self.assertIn(member.name, ids)

    def test_status_filter_failed_requests(self):
        member = self._member()
        self._make_failed_request(member, "Throttled: rate limit exceeded", retry_count=2)

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"status_filter": "Failed Requests"})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row, "member with a Failed request must appear")
        self.assertEqual(row["account_request_status"], "Failed")
        self.assertEqual(row["retry_count"], 2)

    def test_status_filter_complete_excludes_incomplete(self):
        # A bare member (no user/volunteer/employee) must be absent from Complete.
        member = self._member()
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"status_filter": "Complete"})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids)

    # ------------------------------------------------------------- summary

    def test_summary_has_member_totals(self):
        self._member()
        with self.assertNoErrorLog():
            _, _, _, _, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Members (All)", labels)
        self.assertIn("Active Members", labels)
        self.assertGreaterEqual(labels["Total Members (All)"], 1)

    def test_summary_includes_request_status_breakdown(self):
        member = self._member()
        self._make_failed_request(member, "already assigned to Employee X")

        with self.assertNoErrorLog():
            summary = report.get_summary_data()
        labels = {s["label"]: s["value"] for s in summary}
        # The request status breakdown adds a "Requests Failed" row, and the
        # failure-type breakdown adds an "Employee Exists" row.
        self.assertTrue(any("Requests" in label for label in labels))
        self.assertTrue(any("Employee Exists" in label for label in labels))

    # ------------------------------------------------------------- chart

    def test_chart_shape(self):
        with self.assertNoErrorLog():
            chart = report.get_chart_data()
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(
            chart["data"]["labels"],
            ["User Account", "Volunteer Record", "Employee Record", "Complete (All 3)"],
        )
        self.assertEqual(len(chart["data"]["datasets"][0]["values"]), 4)
