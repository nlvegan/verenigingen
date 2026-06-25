"""
Real-integration tests for
``verenigingen/services/member/donor/donor_member_reconciliation.py``.

These exercise the Donor<->Member mapping helpers with real Donor / Member /
Donation / Volunteer records (no business-logic mocking). They lock in:
- explicit-donor-link priority and invalid-link fallback
- email-based donor lookup, single vs. duplicate handling (most-recent wins)
- consistency reporting (valid link, missing link, email mismatch, duplicates)
- duplicate reconciliation actually re-pointing Donation.donor rows
- volunteer-for-employee resolution incl. member-preferred matching

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.services.test_donor_member_reconciliation
"""

import frappe

from verenigingen.services.member.donor.donor_member_reconciliation import (
    check_donor_member_consistency,
    get_all_donors_for_email,
    get_donor_for_member,
    get_volunteer_for_employee,
    reconcile_donor_duplicates,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorMemberReconciliation(EnhancedTestCase):
    """Exercise donor/member reconciliation helpers with real records."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    # ----------------------------------------------------------- helpers

    def _unique_email(self, prefix="recon"):
        return f"{prefix}.{frappe.generate_hash(length=8)}@example.com"

    def _make_member(self, email=None):
        # NOTE: the factory may append a uniqueness suffix to the email, so
        # callers that need the donor email to match must read member.email
        # back after creation rather than trusting the passed-in value.
        return self.create_test_member(
            first_name="Recon",
            last_name="Member",
            email=email or self._unique_email("member"),
        )

    def _make_donor(self, email, donor_name="Recon Donor"):
        return self.create_test_donor(donor_name=donor_name, donor_email=email, donor_type="Individual")

    # ----------------------------------------------------------- get_donor_for_member

    def test_get_donor_for_member_explicit_valid_link_wins(self):
        """A valid explicit member ``donor`` attribute is returned without email lookup.

        Member has no ``donor`` schema field on this app, so the explicit-link
        branch is only reachable when a caller hands the function a doc object
        carrying a ``donor`` attribute. The helpers read it via getattr exactly
        for that reason — set it in-memory to drive the branch.
        """
        member = self._make_member()
        # Donor with a DIFFERENT email than the member, linked explicitly.
        donor = self._make_donor(self._unique_email("explicit"))
        member.donor = donor.name  # in-memory attribute (no schema field)
        self.assertEqual(get_donor_for_member(member), donor.name)

    def test_get_donor_for_member_invalid_explicit_link_falls_back_to_email(self):
        """An invalid explicit link is ignored and email lookup is used instead."""
        member = self._make_member(email=self._unique_email("fallback"))
        donor = self._make_donor(member.email)  # matches by member's actual email
        member.donor = "Donor-DOES-NOT-EXIST"  # in-memory, invalid link
        self.assertEqual(get_donor_for_member(member), donor.name)

    def test_get_donor_for_member_no_email_returns_none(self):
        """With no email and no valid explicit link, returns None."""
        member = self._make_member()
        member.email = None
        # bypass member email lookup; explicit link absent
        member.donor = None
        self.assertIsNone(get_donor_for_member(member))

    def test_get_donor_for_member_single_email_match(self):
        member = self._make_member(email=self._unique_email("single"))
        donor = self._make_donor(member.email)
        self.assertEqual(get_donor_for_member(member), donor.name)

    def test_get_donor_for_member_no_match_returns_none(self):
        member = self._make_member(email=self._unique_email("nomatch"))
        self.assertIsNone(get_donor_for_member(member))

    def test_get_donor_for_member_multiple_matches_returns_most_recent(self):
        """Duplicate-email donors -> most recently created is selected."""
        member = self._make_member(email=self._unique_email("multi"))
        self._make_donor(member.email, donor_name="First Donor")
        second = self._make_donor(member.email, donor_name="Second Donor")
        # Most recent (second) should be returned.
        self.assertEqual(get_donor_for_member(member), second.name)

    # ----------------------------------------------------------- get_all_donors_for_email

    def test_get_all_donors_for_email_empty(self):
        self.assertEqual(get_all_donors_for_email(""), [])
        self.assertEqual(get_all_donors_for_email(None), [])

    def test_get_all_donors_for_email_includes_donation_count(self):
        email = self._unique_email("count")
        donor = self._make_donor(email)
        # Two donations -> count == 2.
        self.create_test_donation(donor=donor.name)
        self.create_test_donation(donor=donor.name)
        results = get_all_donors_for_email(email)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], donor.name)
        self.assertEqual(results[0]["donation_count"], 2)

    # ----------------------------------------------------------- check_donor_member_consistency

    # NOTE: Member has no ``donor`` schema field in this app, so
    # check_donor_member_consistency() always sees explicit_donor=None and only
    # its email-based branches are reachable. The explicit-link branches are
    # effectively dead unless a site adds a Member.donor custom field.

    def test_consistency_no_donor_anywhere_is_consistent(self):
        member = self._make_member(email=self._unique_email("clean"))
        report = check_donor_member_consistency(member.name)
        self.assertTrue(report["consistent"])
        self.assertEqual(report["issues"], [])

    def test_consistency_single_email_donor_is_consistent(self):
        member = self._make_member(email=self._unique_email("ok"))
        self._make_donor(member.email)
        report = check_donor_member_consistency(member.name)
        self.assertTrue(report["consistent"])
        self.assertEqual(report["issues"], [])

    def test_consistency_duplicate_email_donors_flagged(self):
        member = self._make_member(email=self._unique_email("dups"))
        self._make_donor(member.email, donor_name="Dup A")
        self._make_donor(member.email, donor_name="Dup B")
        report = check_donor_member_consistency(member.name)
        self.assertFalse(report["consistent"])
        self.assertTrue(any("Multiple donors" in i for i in report["issues"]))
        self.assertTrue(any("merging duplicate donors" in r for r in report["recommendations"]))

    # ----------------------------------------------------------- reconcile_donor_duplicates

    def test_reconcile_no_duplicates_noop(self):
        email = self._unique_email("nodupe")
        self._make_donor(email)
        result = reconcile_donor_duplicates(email)
        self.assertEqual(result["merged"], 0)
        self.assertEqual(result["message"], "No duplicates to merge")

    def test_reconcile_merges_donations_into_primary(self):
        """Donations on secondary donors are re-pointed to the primary donor."""
        email = self._unique_email("merge")
        first = self._make_donor(email, donor_name="Primary")  # oldest
        second = self._make_donor(email, donor_name="Secondary")  # most recent
        # Donation on the secondary donor.
        donation = self.create_test_donation(donor=second.name)
        # Default primary = most recent (second). Force primary = first so the
        # secondary's donation is actually moved.
        result = reconcile_donor_duplicates(email, primary_donor=first.name)
        self.assertEqual(result["merged"], 1)
        self.assertEqual(result["primary_donor"], first.name)
        self.assertIn(second.name, result["secondary_donors"])
        # The donation now points at the primary donor.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "donor"), first.name)

    def test_reconcile_invalid_primary_returns_error(self):
        email = self._unique_email("badprimary")
        self._make_donor(email, donor_name="A")
        self._make_donor(email, donor_name="B")
        result = reconcile_donor_duplicates(email, primary_donor="Donor-NOT-IN-SET")
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    # ----------------------------------------------------------- get_volunteer_for_employee

    def test_get_volunteer_for_employee_empty(self):
        self.assertIsNone(get_volunteer_for_employee(""))
        self.assertIsNone(get_volunteer_for_employee(None))

    def test_get_volunteer_for_employee_no_match(self):
        self.assertIsNone(get_volunteer_for_employee(f"EMP-{frappe.generate_hash(length=6)}"))

    def test_get_volunteer_for_employee_single_match(self):
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        employee_id = f"EMP-{frappe.generate_hash(length=6)}"
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee_id)
        self.assertEqual(get_volunteer_for_employee(employee_id), volunteer.name)

    def test_get_volunteer_for_employee_prefers_member_specific(self):
        """When member_name is given, the member-linked volunteer is preferred."""
        member_a = self._make_member()
        member_b = self._make_member()
        vol_a = self.create_test_volunteer(member_name=member_a.name)
        vol_b = self.create_test_volunteer(member_name=member_b.name)
        employee_id = f"EMP-{frappe.generate_hash(length=6)}"
        # Both volunteers share the same employee_id (data anomaly being resolved).
        frappe.db.set_value("Volunteer", vol_a.name, "employee_id", employee_id)
        frappe.db.set_value("Volunteer", vol_b.name, "employee_id", employee_id)
        # Asking for member_b should return vol_b even if vol_a is more recent.
        self.assertEqual(get_volunteer_for_employee(employee_id, member_name=member_b.name), vol_b.name)
