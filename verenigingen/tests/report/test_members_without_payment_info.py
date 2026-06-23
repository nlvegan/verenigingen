"""
Real-integration tests for the *Members Without Payment Info* script report
(``verenigingen/verenigingen/report/members_without_payment_info/``).

The report lists Active/Pending Members who lack ANY valid payment method
(no complete Mollie subscription, no active SEPA mandate, no complete Bank
Transfer setup). It returns columns, data, summary statistics and a pie chart.

These tests seed real Members, Chapters and SEPA Mandates via the factory and
call ``execute(filters)`` / ``get_data`` directly. No business logic is
mocked; tests run as Administrator.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.members_without_payment_info import (
    members_without_payment_info as report,
)


class TestMembersWithoutPaymentInfoReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member(self, status="Active", chapter=False, **kwargs):
        member = self.create_test_member(
            first_name="Pay",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"pay.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            chapter=chapter,
            **kwargs,
        )
        member.reload()
        return member

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 11)
        self.assertEqual(columns[0]["fieldname"], "member_name")
        self.assertEqual(columns[0]["options"], "Member")
        for fn in ("has_mollie", "has_sepa", "has_bank_transfer", "missing_info"):
            self.assertIn(fn, fieldnames)

    # ----------------------------------------------------- execute / shape

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _, chart, summary = result
        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(None)
        self.assertEqual(len(columns), 11)

    # ----------------------------------------------------- core inclusion

    def test_member_without_any_payment_method_appears(self):
        # Default member: no payment_method, no SEPA, no bank info -> appears.
        member = self._member()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row, "member with no payment info must appear")
        self.assertFalse(row["has_mollie"])
        self.assertFalse(row["has_sepa"])
        self.assertFalse(row["has_bank_transfer"])
        self.assertIn("indicator red", row["missing_info"])

    def test_member_with_active_sepa_mandate_is_excluded(self):
        member = self._member()
        # An active SEPA mandate counts as a valid payment method.
        self.create_test_sepa_mandate(member=member.name, scenario="normal")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids, "member with an active SEPA mandate must be excluded")

    def test_member_with_complete_bank_transfer_is_excluded(self):
        member = self._member(
            payment_method="Bank Transfer",
            iban="NL39RABO0300065264",
            bank_account_name="Pay Member",
        )
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids, "member with complete bank transfer setup must be excluded")

    def test_member_with_incomplete_bank_transfer_appears_with_missing_iban(self):
        # Bank Transfer chosen but IBAN missing -> still appears, IBAN flagged.
        member = self._member(
            payment_method="Bank Transfer",
            bank_account_name="Pay Member",
        )
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertFalse(row["has_bank_transfer"])
        self.assertIn("IBAN", row["missing_info"])

    def test_member_with_mollie_method_but_no_credentials_flags_mollie(self):
        member = self._member(payment_method="Mollie")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertFalse(row["has_mollie"])
        self.assertIn("Mollie", row["missing_info"])

    def test_member_with_complete_mollie_subscription_is_excluded(self):
        member = self._member(
            payment_method="Mollie",
            mollie_customer_id="cst_test123",
            mollie_subscription_id="sub_test123",
            subscription_status="active",
        )
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids, "member with a complete active Mollie subscription is excluded")

    # ------------------------------------------------------- status filter

    def test_pending_member_included(self):
        member = self._member(status="Pending")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertIn(member.name, {r["member_name"] for r in data})

    def test_suspended_member_excluded(self):
        member = self._member(status="Suspended")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertNotIn(
            member.name, {r["member_name"] for r in data}, "only Active/Pending members are considered"
        )

    # ------------------------------------------------------ chapter filter

    def test_chapter_filter_restricts_to_chapter_members(self):
        chapter = self.create_test_chapter()
        in_chapter = self._member(chapter=chapter.name)
        out_chapter = self._member(chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"chapter": chapter.name})
        ids = {r["member_name"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)
        row = next(r for r in data if r["member_name"] == in_chapter.name)
        self.assertEqual(row["chapters"], chapter.name)

    def test_chapter_filter_empty_chapter_returns_empty(self):
        chapter = self.create_test_chapter()
        with self.assertNoErrorLog():
            data = report.get_data({"chapter": chapter.name})
        self.assertEqual(data, [], "a chapter with no members yields no rows")

    def test_member_without_chapter_shows_no_chapter_label(self):
        member = self._member(chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["chapters"], "No Chapter")

    # ----------------------------------------------------- summary / chart

    def test_summary_counts_and_breakdown(self):
        self._member(status="Active")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Members Without Payment Info", labels)
        self.assertGreaterEqual(labels["Total Members Without Payment Info"], 1)
        self.assertEqual(labels["Total Members Without Payment Info"], len(data))
        self.assertIn("Active Members", labels)

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))

    def test_chart_reflects_status_distribution(self):
        self._member(status="Active")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "pie")
        self.assertIn("Active", chart["data"]["labels"])
