"""
Real-integration tests for the *Members Without Chapter* script report
(``verenigingen/verenigingen/report/members_without_chapter/``).

The report lists Members who are NOT in any (enabled) Chapter Member record,
enriches each with address info, latest membership status and a suggested
chapter, and returns columns, data, summary statistics and a donut chart.

These tests seed real Members (with/without chapters and addresses) and
Memberships via the factory and call ``execute(filters)`` / ``get_data`` /
the pure summary/chart helpers directly. No business logic is mocked; tests
run as Administrator (so ``get_user_accessible_chapters`` returns None ->
see all).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.members_without_chapter import (
    members_without_chapter as report,
)


class TestMembersWithoutChapterReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member_no_chapter(self, status="Active", **kwargs):
        member = self.create_test_member(
            first_name="NoChap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"nochap.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            chapter=False,
            **kwargs,
        )
        member.reload()
        return member

    def _member_no_chapter_with_address(self, city="Rotterdam", country="Netherlands", pincode="3011 AB"):
        """Create a chapter-less member with a linked primary Address.

        The base factory (CoreTestDataFactory) does not create Member addresses,
        so the country/city columns of this report require an explicit Address.
        """
        member = self._member_no_chapter()
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"{member.full_name} Addr {frappe.generate_hash(length=4)}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": city,
                "pincode": pincode,
                "country": country,
                "links": [{"link_doctype": "Member", "link_name": member.name}],
            }
        )
        address.insert(ignore_permissions=True)
        self.track_doc("Address", address.name)
        frappe.db.set_value("Member", member.name, "primary_address", address.name)
        member.reload()
        return member

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 11)
        self.assertEqual(columns[0]["fieldname"], "member_name")
        self.assertEqual(columns[0]["options"], "Member")
        for fn in ("city", "postal_code", "membership_status", "suggested_chapter", "actions"):
            self.assertIn(fn, fieldnames)

    # ----------------------------------------------------- execute / shape

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _, chart, summary = result
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(None)
        self.assertEqual(len(columns), 11)

    # ----------------------------------------------------- core inclusion

    def test_member_without_chapter_appears(self):
        member = self._member_no_chapter()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row, "a member with no chapter must appear")
        self.assertEqual(row["membership_status"], "No Membership")

    def test_member_with_chapter_is_excluded(self):
        chapter = self.create_test_chapter()
        member = self.create_test_member(
            first_name="HasChap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"haschap.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            chapter=chapter.name,
        )
        member.reload()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertNotIn(
            member.name, {r["member_name"] for r in data}, "members in a chapter must be excluded"
        )

    def test_member_with_active_membership_shows_active_status(self):
        member = self._member_no_chapter()
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, status="Active"
        )
        membership.submit()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Active", row["membership_status"])
        self.assertIsNotNone(row["member_since"])

    # ------------------------------------------------------ status filter

    def test_membership_status_filter_restricts_to_member_status(self):
        active = self._member_no_chapter(status="Active")
        suspended = self._member_no_chapter(status="Suspended")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"membership_status": "Suspended"})
        ids = {r["member_name"] for r in data}
        self.assertIn(suspended.name, ids)
        self.assertNotIn(active.name, ids)

    # --------------------------------------------------------- date filters

    def test_from_date_filter_excludes_older_members(self):
        member = self._member_no_chapter()
        # A from_date in the future excludes the just-created member.
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"from_date": add_days(today(), 1)}
            )
        self.assertNotIn(member.name, {r["member_name"] for r in data})

    def test_to_date_filter_excludes_newer_members(self):
        member = self._member_no_chapter()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"to_date": add_days(today(), -1)}
            )
        self.assertNotIn(member.name, {r["member_name"] for r in data})

    def test_from_and_to_date_between_includes_member(self):
        member = self._member_no_chapter()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"from_date": add_days(today(), -1), "to_date": add_days(today(), 1)}
            )
        self.assertIn(member.name, {r["member_name"] for r in data})

    # ------------------------------------------------------- country filter

    def test_country_filter_excludes_other_countries(self):
        # Member with a Netherlands address; filter on a different country -> excluded.
        member = self._member_no_chapter_with_address(city="Amsterdam", country="Netherlands")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"country": "Germany"})
        self.assertNotIn(member.name, {r["member_name"] for r in data})

    def test_country_filter_includes_matching_country(self):
        member = self._member_no_chapter_with_address(city="Rotterdam", country="Netherlands")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"country": "Netherlands"})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["country"], "Netherlands")
        self.assertEqual(row["city"], "Rotterdam")

    # ----------------------------------------------------- summary / chart

    def test_summary_counts(self):
        self._member_no_chapter()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Members Without Chapter", labels)
        self.assertGreaterEqual(labels["Total Members Without Chapter"], 1)
        self.assertEqual(labels["Total Members Without Chapter"], len(data))
        self.assertIn("% with Suggestions", labels)

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))

    def test_chart_groups_by_membership_status(self):
        self._member_no_chapter()
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "donut")
        self.assertIn("No Membership", chart["data"]["labels"])

    # ------------------------------------------------- pure helper coverage

    def test_validate_doctype_fields_true_for_existing(self):
        self.assertTrue(report.validate_doctype_fields("Member", ["name", "status", "email"]))

    def test_validate_doctype_fields_false_for_missing(self):
        self.assertFalse(report.validate_doctype_fields("Member", ["not_a_real_field_xyz"]))

    def test_get_action_buttons_with_suggestion(self):
        html = report.get_action_buttons("MEMBER-X", "Some Chapter")
        self.assertIn("assign-chapter-btn", html)
        self.assertIn("manual-assign-btn", html)

    def test_get_action_buttons_without_suggestion(self):
        html = report.get_action_buttons("MEMBER-X", "No suggestion available")
        self.assertNotIn("assign-chapter-btn", html)
        self.assertIn("manual-assign-btn", html)

    def test_get_summary_groups_by_country(self):
        rows = [
            {"country": "Netherlands", "membership_status": "Active", "suggested_chapter": "Chap A"},
            {"country": "Netherlands", "membership_status": "No Membership",
             "suggested_chapter": "No suggestion available"},
        ]
        summary = report.get_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        self.assertEqual(labels["Total Members Without Chapter"], 2)
        self.assertEqual(labels["Members with Chapter Suggestions"], 1)
        self.assertIn("Netherlands", str(labels["Most Common Country"]))
