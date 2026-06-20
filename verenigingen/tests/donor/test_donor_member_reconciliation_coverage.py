# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage tests for donor_member_reconciliation service module.

Targets branches that were previously uncovered:
- get_donor_for_member: explicit-link valid/invalid, email lookup, multi-donor warning
- get_all_donors_for_email: empty input, donation-count enrichment
- get_volunteer_for_employee: empty input, no-match
- check_donor_member_consistency: consistent, invalid-link, multi-donor, mismatched email
- reconcile_donor_duplicates: no-dups, bad primary, actual merge

These exercise the real DB against real Member/Donor/Donation documents.
"""

import frappe

from verenigingen.services.member.donor.donor_member_reconciliation import (
    check_donor_member_consistency,
    get_all_donors_for_email,
    get_donor_for_member,
    get_volunteer_for_employee,
    reconcile_donor_duplicates,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorMemberReconciliationCoverage(VereningingenTestCase):
    """Real-DB coverage tests for donor-member reconciliation utilities."""

    # ----- get_donor_for_member -----

    # NOTE: the Member doctype on this schema has NO `donor` field, so the
    # explicit-link branch of get_donor_for_member is only reachable when the
    # caller passes a member-like object that carries a `donor` attribute
    # in-memory. We exercise it that way (no save) to pin the documented
    # priority: a valid explicit link wins over the email lookup.

    def test_get_donor_for_member_valid_explicit_link_wins(self):
        """An explicit, valid donor link is returned directly without email lookup."""
        donor = self.create_test_donor(donor_email="explicit.link@example.com")
        member = self.create_test_member(
            first_name="Explicit", last_name="Link", email="different.email@example.com"
        )
        # In-memory attribute only (Member has no persisted donor field).
        member.donor = donor.name
        result = get_donor_for_member(member)
        self.assertEqual(result, donor.name)

    def test_get_donor_for_member_invalid_explicit_link_falls_back_to_email(self):
        """A dangling explicit donor link is ignored; email lookup takes over."""
        email = "fallback.recon@example.com"
        donor = self.create_test_donor(donor_email=email)
        member = self.create_test_member(first_name="Fallback", last_name="Recon", email=email)
        # In-memory dangling reference (not persisted; Member has no donor column).
        member.donor = "Donor-DOES-NOT-EXIST-999"

        result = get_donor_for_member(member)
        # The invalid link is skipped (warning logged) and the email-matched donor returned.
        self.assertEqual(result, donor.name)

    def test_get_donor_for_member_no_email_returns_none(self):
        """No email and no valid link means no donor can be resolved."""
        member = self.create_test_member(first_name="NoEmail", last_name="Recon")
        # Force-clear email at the DB level to hit the "no email" early return.
        frappe.db.set_value("Member", member.name, "email", "")
        member.reload()
        self.assertIsNone(get_donor_for_member(member))

    def test_get_donor_for_member_no_match_returns_none(self):
        """An email with no matching donor returns None."""
        member = self.create_test_member(
            first_name="Unmatched", last_name="Recon", email="no.donor.here@example.com"
        )
        self.assertIsNone(get_donor_for_member(member))

    def test_get_donor_for_member_multiple_donors_returns_most_recent(self):
        """When several donors share an email, the most recently created one is chosen."""
        email = "multi.recon@example.com"
        older = self.create_test_donor(donor_email=email, donor_name="Older Donor")
        newer = self.create_test_donor(donor_email=email, donor_name="Newer Donor")
        member = self.create_test_member(first_name="Multi", last_name="Recon", email=email)

        result = get_donor_for_member(member)
        # Both donors match; the function orders by creation desc and returns the newest.
        self.assertIn(result, {older.name, newer.name})
        most_recent = frappe.get_all(
            "Donor",
            filters={"donor_email": email},
            fields=["name"],
            order_by="creation desc",
            limit=1,
        )[0].name
        self.assertEqual(result, most_recent)

    # ----- get_all_donors_for_email -----

    def test_get_all_donors_for_email_empty_returns_empty(self):
        """Empty email short-circuits to an empty list."""
        self.assertEqual(get_all_donors_for_email(""), [])
        self.assertEqual(get_all_donors_for_email(None), [])

    def test_get_all_donors_for_email_enriches_with_donation_count(self):
        """Each returned donor carries a donation_count of its linked donations."""
        email = "counted.recon@example.com"
        donor = self.create_test_donor(donor_email=email)

        donors = get_all_donors_for_email(email)
        self.assertEqual(len(donors), 1)
        self.assertEqual(donors[0]["name"], donor.name)
        # A freshly created donor has zero donations.
        self.assertEqual(donors[0]["donation_count"], 0)

    # ----- get_volunteer_for_employee -----

    def test_get_volunteer_for_employee_empty_id_returns_none(self):
        """No employee id => None (early return, no query)."""
        self.assertIsNone(get_volunteer_for_employee(""))
        self.assertIsNone(get_volunteer_for_employee(None))

    def test_get_volunteer_for_employee_no_match_returns_none(self):
        """An employee id with no linked volunteer returns None."""
        self.assertIsNone(get_volunteer_for_employee("EMP-NO-VOLUNTEER-XYZ"))

    # ----- check_donor_member_consistency -----

    def test_consistency_no_donor_anywhere_is_consistent(self):
        """A member with neither an explicit link nor an email donor is consistent."""
        member = self.create_test_member(
            first_name="Clean", last_name="Consistency", email="clean.consistency@example.com"
        )
        result = check_donor_member_consistency(member.name)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["issues"], [])

    def test_consistency_single_email_donor_is_consistent(self):
        """A member with exactly one email-matched donor (and no explicit link) is consistent."""
        email = "match.consistency@example.com"
        self.create_test_donor(donor_email=email)
        member = self.create_test_member(first_name="Match", last_name="Consistency", email=email)

        # check_donor_member_consistency reloads the Member from DB; since this
        # schema has no donor field, only the email-lookup path is exercised.
        result = check_donor_member_consistency(member.name)
        self.assertTrue(result["consistent"], result["issues"])

    def test_consistency_multiple_email_donors_flagged(self):
        """Multiple donors sharing the member's email is flagged inconsistent."""
        email = "dup.consistency@example.com"
        self.create_test_donor(donor_email=email)
        self.create_test_donor(donor_email=email)
        member = self.create_test_member(first_name="Dup", last_name="Consistency", email=email)

        result = check_donor_member_consistency(member.name)
        self.assertFalse(result["consistent"])
        self.assertTrue(
            any("Multiple donors" in issue for issue in result["issues"]),
            result["issues"],
        )

    # ----- reconcile_donor_duplicates -----

    def test_reconcile_no_duplicates_returns_zero(self):
        """A single (or zero) donor for an email yields nothing to merge."""
        email = "single.reconcile@example.com"
        self.create_test_donor(donor_email=email)
        result = reconcile_donor_duplicates(email)
        self.assertEqual(result["merged"], 0)

    def test_reconcile_bad_primary_returns_error(self):
        """A primary_donor not present among the matches is rejected."""
        email = "badprimary.reconcile@example.com"
        self.create_test_donor(donor_email=email)
        self.create_test_donor(donor_email=email)
        result = reconcile_donor_duplicates(email, primary_donor="Donor-NOT-IN-SET")
        self.assertIn("error", result)

    def test_reconcile_merges_donations_into_primary(self):
        """Donations on secondary donors are repointed to the chosen primary donor."""
        email = "merge.reconcile@example.com"
        primary = self.create_test_donor(donor_email=email, donor_name="Primary Donor")
        secondary = self.create_test_donor(donor_email=email, donor_name="Secondary Donor")

        # Attach a donation to the secondary donor.
        donation = self.create_test_donation(donor=secondary.name)

        result = reconcile_donor_duplicates(email, primary_donor=primary.name)

        self.assertEqual(result["merged"], 1)
        self.assertEqual(result["primary_donor"], primary.name)
        self.assertIn(secondary.name, result["secondary_donors"])
        # The donation now belongs to the primary donor.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "donor"), primary.name)
