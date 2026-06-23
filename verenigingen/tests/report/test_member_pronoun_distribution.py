"""Real-integration tests for the *Member Pronoun Distribution* query report
(``verenigingen/verenigingen/report/member_pronoun_distribution/``).

This is a Query Report whose ``.py`` exposes ``execute(filters)`` returning a
two-column (pronouns / count) distribution over Members whose status is in
('Active', 'Dues Outstanding'). The report was at 0% coverage. These tests
seed real Members with explicit pronoun values (and blank/NULL ones) and assert
the Unknown coalescing and the status filtering, calling ``execute`` directly.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.member_pronoun_distribution import (
    member_pronoun_distribution as report,
)


class TestMemberPronounDistributionReport(VereningingenTestCase):
    def _member(self, pronouns, status="Active"):
        member = self.create_test_member(
            first_name="Pronoun",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"pronoun.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
        )
        frappe.db.set_value("Member", member.name, "pronouns", pronouns, update_modified=False)
        frappe.db.set_value("Member", member.name, "status", status, update_modified=False)
        return member

    def _counts(self, data):
        return {row["pronouns"]: row["count"] for row in data}

    def test_columns_structure(self):
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 2)
        self.assertEqual(columns[0]["fieldname"], "pronouns")
        self.assertEqual(columns[1]["fieldname"], "count")
        self.assertIsInstance(data, list)

    def test_explicit_pronouns_are_grouped(self):
        self._member("zij/haar")
        self._member("zij/haar")
        self._member("hij/hem")

        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        counts = self._counts(data)
        self.assertIn("zij/haar", counts)
        self.assertGreaterEqual(counts["zij/haar"], 2)
        self.assertIn("hij/hem", counts)
        self.assertGreaterEqual(counts["hij/hem"], 1)

    def test_blank_and_null_pronouns_coalesce_to_unknown(self):
        m_blank = self._member("")
        m_null = self._member("die/hen")
        frappe.db.set_value("Member", m_null.name, "pronouns", None, update_modified=False)

        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        counts = self._counts(data)
        self.assertIn("Unknown", counts)
        # Both the empty-string and the NULL member land in Unknown.
        self.assertGreaterEqual(counts["Unknown"], 2)
        self.assertIsNotNone(m_blank)

    def test_active_status_is_included(self):
        # NOTE: the report SQL filters on status IN ('Active', 'Dues Outstanding'),
        # but 'Dues Outstanding' is NOT a valid Member.status option (the field's
        # options are Pending/Active/Rejected/Expired/Suspended/Banned/Deceased/
        # Quit). So the second status is dead -- only Active members are counted.
        # FLAGGED for the caller (phantom status string); not fixed here.
        self._member("xij/hen", status="Active")
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        counts = self._counts(data)
        self.assertIn("xij/hen", counts)
        self.assertGreaterEqual(counts["xij/hen"], 1)

    def test_terminated_status_is_excluded(self):
        member = self._member("nij/nem", status="Quit")
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        counts = self._counts(data)
        self.assertNotIn("nij/nem", counts, "Terminated members must be excluded")
        # Flip active and confirm it now appears.
        frappe.db.set_value("Member", member.name, "status", "Active", update_modified=False)
        _columns, data2 = report.execute({})
        self.assertIn("nij/nem", self._counts(data2))

    def test_ordered_by_count_desc(self):
        for _ in range(3):
            self._member("aa/bb")
        self._member("cc/dd")
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        groups = [r["pronouns"] for r in data]
        if "aa/bb" in groups and "cc/dd" in groups:
            self.assertLessEqual(groups.index("aa/bb"), groups.index("cc/dd"))
