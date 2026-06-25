# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Integration tests for member_duplicate_detection_service.

Exercises the matching strategies (email exact, IBAN exact incl. normalization,
fuzzy name+birthdate, address exact), confidence scoring, dedup/merge of match
types, and the check_duplicate_for_approval API (validation + categorization)
against real Member documents.
"""

import unittest

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.validation.member_duplicate_detection_service import (
    _calculate_name_similarity,
    _deduplicate_matches,
    DuplicateMatch,
    check_address_duplicate,
    check_duplicate_for_approval,
    check_email_duplicate,
    check_iban_duplicate,
    find_potential_duplicates,
    fuzzy_match_name_birthdate,
)


class TestDuplicateDetectionStrategies(EnhancedTestCase):
    """Each matching strategy returns the expected confidence + reason."""

    def test_email_exact_match_confidence_one(self):
        member = self.create_test_member(
            first_name="Email",
            last_name="Dup",
            email="email.dup@example.com",
        )
        matches = check_email_duplicate(member.email)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].match_type, "email_exact")
        self.assertEqual(matches[0].confidence, 1.0)
        self.assertEqual(matches[0].member_name, member.name)

    def test_email_match_excludes_self(self):
        member = self.create_test_member(
            first_name="Email",
            last_name="Self",
            email="email.self@example.com",
        )
        matches = check_email_duplicate(member.email, exclude_member=member.name)
        self.assertEqual(matches, [])

    def test_email_empty_returns_empty(self):
        self.assertEqual(check_email_duplicate(""), [])

    def test_iban_exact_match_normalized(self):
        """IBAN stored with spaces still matches a normalized query."""
        iban = "NL39 RABO 0300 0652 64"
        member = self.create_test_member(
            first_name="Iban",
            last_name="Dup",
            email="iban.dup@example.com",
            iban=iban,
        )
        # Query with no spaces / lowercase -> normalization must still match
        matches = check_iban_duplicate("nl39rabo0300065264")
        names = [m.member_name for m in matches]
        self.assertIn(member.name, names)
        match = next(m for m in matches if m.member_name == member.name)
        self.assertEqual(match.match_type, "iban_exact")
        self.assertEqual(match.confidence, 0.95)

    def test_iban_empty_returns_empty(self):
        self.assertEqual(check_iban_duplicate(""), [])

    def test_address_exact_match_confidence(self):
        member = self.create_test_member(
            first_name="Addr",
            last_name="Dup",
            email="addr.dup@example.com",
            address_line1="Keizersgracht 1",
            city="Amsterdam",
            postal_code="1015 CN",
        )
        member.reload()
        self.assertTrue(member.primary_address)
        matches = check_address_duplicate(member.primary_address)
        names = [m.member_name for m in matches]
        self.assertIn(member.name, names)
        match = next(m for m in matches if m.member_name == member.name)
        self.assertEqual(match.match_type, "address_exact")
        self.assertEqual(match.confidence, 0.6)

    def test_fuzzy_name_birthdate_exact_match(self):
        """Identical name + birth date yields high (>=0.85) confidence."""
        bd = "1985-06-15"
        member = self.create_test_member(
            first_name="Johan",
            last_name="Bakker",
            email="johan.bakker@example.com",
            birth_date=bd,
        )
        matches = fuzzy_match_name_birthdate(
            first_name="Johan",
            last_name=member.last_name,
            tussenvoegsel=None,
            birth_date=bd,
            exclude_member=None,
        )
        names = [m.member_name for m in matches]
        self.assertIn(member.name, names)
        match = next(m for m in matches if m.member_name == member.name)
        self.assertEqual(match.match_type, "name_birthdate_fuzzy")
        # identical names -> similarity 1.0 -> confidence 0.9
        self.assertAlmostEqual(match.confidence, 0.9, places=2)

    def test_fuzzy_name_birthdate_requires_birthdate_match(self):
        """Same name but different birth date -> no match (birth date is exact)."""
        member = self.create_test_member(
            first_name="Pieter",
            last_name="Jansen",
            email="pieter.jansen@example.com",
            birth_date="1970-01-01",
        )
        matches = fuzzy_match_name_birthdate(
            first_name="Pieter",
            last_name=member.last_name,
            tussenvoegsel=None,
            birth_date="1990-12-31",
            exclude_member=None,
        )
        self.assertNotIn(member.name, [m.member_name for m in matches])

    def test_fuzzy_name_birthdate_below_threshold_excluded(self):
        """A very different name at the same birth date is below threshold."""
        bd = "1960-03-03"
        member = self.create_test_member(
            first_name="Wilhelmina",
            last_name="Vandenberg",
            email="w.vandenberg@example.com",
            birth_date=bd,
        )
        matches = fuzzy_match_name_birthdate(
            first_name="Bob",
            last_name="Xyz",
            tussenvoegsel=None,
            birth_date=bd,
            exclude_member=None,
            threshold=0.7,
        )
        self.assertNotIn(member.name, [m.member_name for m in matches])


class TestNameSimilarity(EnhancedTestCase):
    """_calculate_name_similarity weighting and tussenvoegsel handling."""

    def test_identical_names_score_one(self):
        score = _calculate_name_similarity("Jan", "de Vries", "", "Jan", "de Vries", "")
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_last_name_weighted_more(self):
        """Same last name + different first scores higher than the reverse."""
        same_last = _calculate_name_similarity("Anna", "Smith", None, "Bob", "Smith", None)
        same_first = _calculate_name_similarity("Anna", "Smith", None, "Anna", "Jones", None)
        self.assertGreater(same_last, same_first)

    def test_tussenvoegsel_included_in_last(self):
        """Tussenvoegsel is folded into the last-name comparison."""
        with_tussen = _calculate_name_similarity("Jan", "Vries", "de", "Jan", "de Vries", None)
        # 'de vries' vs 'de vries' should be a strong match
        self.assertGreater(with_tussen, 0.9)


class TestDeduplicateMatches(EnhancedTestCase):
    """_deduplicate_matches keeps highest confidence and merges types."""

    def test_keeps_highest_confidence_and_merges_type(self):
        m_low = DuplicateMatch("MEM-1", "address_exact", 0.6, {})
        m_high = DuplicateMatch("MEM-1", "email_exact", 1.0, {})
        result = _deduplicate_matches([m_low, m_high])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].confidence, 1.0)
        # merged type shows both
        self.assertIn("email_exact", result[0].match_type)
        self.assertIn("address_exact", result[0].match_type)

    def test_distinct_members_preserved(self):
        m1 = DuplicateMatch("MEM-1", "email_exact", 1.0, {})
        m2 = DuplicateMatch("MEM-2", "iban_exact", 0.95, {})
        result = _deduplicate_matches([m1, m2])
        self.assertEqual({m.member_name for m in result}, {"MEM-1", "MEM-2"})


class TestFindPotentialDuplicates(EnhancedTestCase):
    """find_potential_duplicates aggregation, sorting and threshold filtering."""

    def _persist_shared_contact(self, member, email, iban):
        """Force a member to share an email + IBAN (factory uniquifies these)."""
        frappe.db.set_value("Member", member.name, {"email": email, "iban": iban})

    def test_aggregates_and_sorts_by_confidence(self):
        bd = "1992-07-07"
        shared_email = "find.shared.dup@example.com"
        shared_iban = "NL02ABNA0123456789"
        target = self.create_test_member(
            first_name="Find",
            last_name="Target",
            email="find.target@example.com",
            birth_date=bd,
        )
        other = self.create_test_member(
            first_name="Find",
            last_name=target.last_name,
            email="find.other@example.com",
            birth_date=bd,
        )
        # Make `other` a genuine duplicate of the search criteria.
        self._persist_shared_contact(other, shared_email, shared_iban)

        results = find_potential_duplicates(
            member_name=target.name,
            email=shared_email,
            iban=shared_iban,
            first_name="Find",
            last_name=target.last_name,
            birth_date=bd,
            threshold=0.6,
        )
        # other must be present; email (1.0) dominates iban (0.95) after dedup
        match = next((m for m in results if m["member_name"] == other.name), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["confidence"], 1.0)
        # Email (1.0) is checked first; the lower-confidence IBAN match is
        # discarded by _deduplicate_matches, so the surviving type is email_exact.
        self.assertEqual(match["match_type"], "email_exact")
        # results sorted descending
        confidences = [m["confidence"] for m in results]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_threshold_filters_low_confidence(self):
        member = self.create_test_member(
            first_name="Thresh",
            last_name="Addr",
            email="thresh.addr@example.com",
            address_line1="Threshold Straat 9",
            city="Utrecht",
            postal_code="3500 AA",
        )
        member.reload()
        # address-only match is 0.6; threshold 0.9 must exclude it
        results = find_potential_duplicates(
            member_name="OTHER-MEMBER",
            primary_address=member.primary_address,
            threshold=0.9,
        )
        self.assertEqual(results, [])


class TestCheckDuplicateForApproval(EnhancedTestCase):
    """The whitelisted API endpoint: validation + categorization.

    The @standard_api() decorator serializes the OperationResult to a nested
    dict {"success": bool, "data": {...}, "error": {...}, "meta": {...}}.
    """

    def _persist_email(self, member, email):
        frappe.db.set_value("Member", member.name, "email", email)

    def test_nonexistent_member_returns_fail(self):
        result = check_duplicate_for_approval("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result["success"])
        # Failure path carries an error object, no data
        self.assertIn("error", result)

    def test_categorizes_by_confidence(self):
        """A real email duplicate is reported as high confidence."""
        shared = "approval.dup.shared@example.com"
        m1 = self.create_test_member(
            first_name="Approve",
            last_name="One",
            email="approve.one@example.com",
            birth_date="1980-01-01",
        )
        m2 = self.create_test_member(
            first_name="Approve",
            last_name="Two",
            email="approve.two@example.com",
            birth_date="1980-01-01",
        )
        # Give both the same email so m2 is a genuine duplicate of m1.
        self._persist_email(m1, shared)
        self._persist_email(m2, shared)

        result = check_duplicate_for_approval(m1.name)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["has_duplicates"])
        # m2 shares the email -> high confidence (1.0 >= 0.9)
        high_names = [d["member_name"] for d in data["high_confidence"]]
        self.assertIn(m2.name, high_names)
        self.assertEqual(data["summary"]["high"], len(data["high_confidence"]))

    def test_no_duplicates_reported_clean(self):
        member = self.create_test_member(
            first_name="Unique",
            last_name="Solo",
            email="unique.solo.member@example.com",
        )
        result = check_duplicate_for_approval(member.name)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["has_duplicates"])
        self.assertEqual(data["duplicate_count"], 0)


if __name__ == "__main__":
    unittest.main()
