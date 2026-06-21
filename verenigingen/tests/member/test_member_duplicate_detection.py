"""
Comprehensive tests for Member Duplicate Detection Service

Tests cover:
- Email exact matching
- IBAN exact matching with normalization
- Fuzzy name + birthdate matching
- Dutch tussenvoegsel handling
- Address matching
- Security validation (SQL injection, XSS, permissions)
- Edge cases and error handling
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.member.validation.member_duplicate_detection_service import (
    find_potential_duplicates,
    check_email_duplicate,
    check_iban_duplicate,
    fuzzy_match_name_birthdate,
    check_address_duplicate,
    check_duplicate_for_approval,
    _calculate_name_similarity,
)


def clear_rate_limits():
    """Helper to clear all rate limiting caches for tests"""
    frappe.flags.in_test = True
    cache = frappe.cache()
    if cache:
        try:
            # Reset the specific COR rate limit for create_customer_for_member
            cache.set("cor_rate_limit:create_customer_for_member:Administrator", 0)
            cache.set("cor_rate_limit:create_customer_for_member:" + frappe.session.user, 0)
        except Exception as e:
            print(f"Warning: Failed to clear rate limits: {e}")


def set_shared_email(member_name, email):
    """Force a Member's email directly, bypassing the factory's email uniquifier.

    EnhancedTestDataFactory.create_member appends a per-member unique suffix to
    the local part of an email UNLESS its last 5 chars already contain a digit
    (a deterministic-but-content-dependent heuristic). When two members are
    created with the same uuid-hex email and that hex happens to end in 5 letters,
    BOTH get mangled with DIFFERENT suffixes, so they no longer share an email
    and duplicate detection finds nothing -- an intermittent (~0.76%/uuid) flake.

    Duplicate-detection tests deliberately need members to SHARE an email, so we
    set it explicitly after creation (db.set_value also skips re-validation), making
    the shared-email setup deterministic regardless of the random hex.
    """
    frappe.db.set_value("Member", member_name, "email", email)


class TestEmailDuplicateDetection(EnhancedTestCase):
    """Test email-based duplicate detection"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_exact_email_match_returns_100_confidence(self):
        """Exact email match should return 1.0 confidence"""
        # Use unique email for this test to avoid cross-test contamination
        import uuid
        unique_email = f"jan.devries.{uuid.uuid4().hex[:8]}@example.com"

        # Create two members with same email
        member1 = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            email=unique_email,
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Johannes",
            last_name="Vries",
            email=unique_email,  # Same email
            birth_date="1985-05-15"
        )

        # Force the shared email post-creation so the factory's uniquifier cannot
        # split member1/member2 onto different emails (see set_shared_email).
        set_shared_email(member1.name, unique_email)
        set_shared_email(member2.name, unique_email)

        # Check for duplicates (excluding member1)
        matches = check_email_duplicate(unique_email, exclude_member=member1.name)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence, 1.0)
        self.assertEqual(matches[0].member_name, member2.name)
        self.assertEqual(matches[0].match_type, "email_exact")

    def test_email_match_case_insensitive(self):
        """Email matching should be case-insensitive"""
        import uuid
        unique_email = f"test.user.{uuid.uuid4().hex[:8]}@example.com"
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            email=unique_email.upper(),  # Store in uppercase
            birth_date="1990-01-01"
        )

        # Force the uppercase email post-creation (the factory uniquifier would
        # otherwise mangle the local part for some uuids) so the case-insensitivity
        # assertion is deterministic.
        set_shared_email(member.name, unique_email.upper())

        # Search with lowercase
        matches = check_email_duplicate(unique_email.lower())

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].member_name, member.name)

    def test_no_email_returns_empty_list(self):
        """Passing None or empty email should return empty list"""
        matches1 = check_email_duplicate(None)
        matches2 = check_email_duplicate("")

        self.assertEqual(len(matches1), 0)
        self.assertEqual(len(matches2), 0)


class TestIBANDuplicateDetection(EnhancedTestCase):
    """Test IBAN-based duplicate detection"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_exact_iban_match_returns_95_confidence(self):
        """Exact IBAN match should return 0.95 confidence"""
        # Generate a valid IBAN using the factory
        unique_iban = self.factory.create_test_iban()

        member1 = self.create_test_member(
            first_name="Jan",
            last_name="Jansen",
            iban=unique_iban,
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Piet",
            last_name="Pietersen",
            iban=unique_iban,  # Same IBAN
            birth_date="1985-05-15"
        )

        matches = check_iban_duplicate(unique_iban, exclude_member=member1.name)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence, 0.95)
        self.assertEqual(matches[0].member_name, member2.name)

    def test_iban_normalization_removes_spaces(self):
        """IBAN matching should normalize spaces"""
        # Generate a valid IBAN and add spaces to it
        unique_iban_no_spaces = self.factory.create_test_iban()
        # Add spaces in standard IBAN format (groups of 4)
        parts = [unique_iban_no_spaces[i:i+4] for i in range(0, len(unique_iban_no_spaces), 4)]
        unique_iban_with_spaces = " ".join(parts)

        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            iban=unique_iban_with_spaces,  # With spaces
            birth_date="1990-01-01"
        )

        # Search with different spacing
        matches = check_iban_duplicate(unique_iban_no_spaces)  # No spaces

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].member_name, member.name)

    def test_iban_case_normalization(self):
        """IBAN matching should be case-insensitive"""
        # Generate a valid IBAN in lowercase
        unique_iban = self.factory.create_test_iban().lower()

        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            iban=unique_iban,  # Lowercase
            birth_date="1990-01-01"
        )

        matches = check_iban_duplicate(unique_iban.upper())  # Uppercase

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].member_name, member.name)

    def test_iban_sql_injection_prevention(self):
        """IBAN matching should prevent SQL injection"""
        # Generate a valid IBAN for the legitimate member
        unique_iban = self.factory.create_test_iban()

        # Create legitimate member
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            iban=unique_iban,
            birth_date="1990-01-01"
        )

        # Try SQL injection via IBAN field
        malicious_iban = "NL91%' OR '1'='1"

        # Should not match due to exact comparison
        matches = check_iban_duplicate(malicious_iban)

        # Should return 0 matches (not crash or return all records)
        self.assertEqual(len(matches), 0)


class TestFuzzyNameMatching(EnhancedTestCase):
    """Test fuzzy name + birthdate matching"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_fuzzy_name_match_with_same_birthdate(self):
        """Similar names with same birthdate should match"""
        member1 = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Johannes",  # Similar to Jan
            last_name="de Vries",
            birth_date="1990-01-01"  # Same birthdate
        )

        # The test factory uniquifies last_name (e.g. "de Vries<suffix>"), so query
        # with member2's actual stored surname. The fuzzy match still exercises the
        # first-name similarity (Jan vs Johannes) with an exact surname/birthdate match.
        matches = fuzzy_match_name_birthdate(
            first_name="Jan",
            last_name=member2.last_name,
            tussenvoegsel=None,
            birth_date="1990-01-01",
            exclude_member=member1.name,
            threshold=0.7
        )

        self.assertGreater(len(matches), 0)
        self.assertEqual(matches[0].member_name, member2.name)
        self.assertGreaterEqual(matches[0].confidence, 0.7)

    def test_tussenvoegsel_handling(self):
        """Dutch name particles (tussenvoegsel) should be properly handled"""
        member1 = self.create_test_member(
            first_name="Jan",
            last_name="Vries",
            tussenvoegsel="de",
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Jan",
            last_name="Vries",
            tussenvoegsel="de",
            birth_date="1990-01-01"
        )

        # Calculate similarity
        similarity = _calculate_name_similarity(
            "Jan", "Vries", "de",
            "Jan", "Vries", "de"
        )

        # Should be perfect match
        self.assertEqual(similarity, 1.0)

    def test_different_tussenvoegsel_reduces_similarity(self):
        """Different tussenvoegsel should affect similarity score"""
        similarity1 = _calculate_name_similarity(
            "Jan", "Berg", "van der",
            "Jan", "Berg", "van de"
        )

        similarity2 = _calculate_name_similarity(
            "Jan", "Berg", "van der",
            "Jan", "Berg", "van der"
        )

        # Exact match should have higher similarity
        self.assertGreater(similarity2, similarity1)

    def test_different_birthdate_no_match(self):
        """Different birthdates should not match even with similar names"""
        member1 = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            birth_date="1991-01-01"  # Different year
        )

        matches = fuzzy_match_name_birthdate(
            first_name="Jan",
            last_name="de Vries",
            tussenvoegsel=None,
            birth_date="1990-01-01",
            exclude_member=member1.name,
            threshold=0.7
        )

        # Should not match member2 (different birthdate)
        matching_names = [m.member_name for m in matches]
        self.assertNotIn(member2.name, matching_names)


class TestAddressDuplicateDetection(EnhancedTestCase):
    """Test address-based duplicate detection"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_same_address_returns_60_confidence(self):
        """Same address should return 0.6 confidence"""
        import random
        unique_suffix = str(random.randint(1000, 9999))

        # Create address - test user already has System Manager role from setUp()
        address = frappe.get_doc({
            "doctype": "Address",
            # address_type set explicitly: EnhancedTestCase runs with
            # frappe.flags.in_import, which suppresses DocType field defaults.
            "address_type": "Personal",
            "address_title": f"Test Address {unique_suffix}",
            "address_line1": "Teststraat 1",
            "city": "Amsterdam",
            "pincode": "1234 AB",
            "country": "Netherlands"
        }).insert()

        member1 = self.create_test_member(
            first_name="Jan",
            last_name="Jansen",
            primary_address=address.name,
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Piet",
            last_name="Pietersen",
            primary_address=address.name,  # Same address
            birth_date="1985-05-15"
        )

        matches = check_address_duplicate(address.name, exclude_member=member1.name)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence, 0.6)
        self.assertEqual(matches[0].member_name, member2.name)


class TestComprehensiveDuplicateDetection(EnhancedTestCase):
    """Test the complete duplicate detection workflow"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_multiple_match_types_highest_confidence_wins(self):
        """When multiple match types exist, highest confidence should be used"""
        # Use unique identifiers to avoid cross-test contamination
        import uuid
        unique_email = f"jan.{uuid.uuid4().hex[:8]}@example.com"
        unique_iban = self.factory.create_test_iban()

        # Create members with multiple matching criteria
        member1 = self.create_test_member(
            first_name="Jan",
            last_name="Jansen",
            email=unique_email,
            iban=unique_iban,
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Jan",
            last_name="Jansen",
            email=unique_email,  # Email match (1.0)
            iban=unique_iban,  # IBAN match (0.95)
            birth_date="1990-01-01"  # Name+DOB match (0.7-0.9)
        )

        # Force the shared email so the 1.0 email-match criterion is deterministic
        # regardless of the factory's email uniquifier (see set_shared_email).
        set_shared_email(member1.name, unique_email)
        set_shared_email(member2.name, unique_email)

        duplicates = find_potential_duplicates(
            member_name=member1.name,
            email=unique_email,
            iban=unique_iban,
            first_name="Jan",
            last_name="Jansen",
            tussenvoegsel=None,
            birth_date="1990-01-01",
            primary_address=None,
            threshold=0.6
        )

        # Should have exactly one match (deduplicated)
        self.assertEqual(len(duplicates), 1)

        # Should use email confidence (1.0) as highest
        self.assertEqual(duplicates[0]["confidence"], 1.0)

    def test_threshold_filtering(self):
        """Only matches above threshold should be returned"""
        import random
        unique_suffix = str(random.randint(1000, 9999))
        # Use unique birthdate to avoid matching other tests' members
        unique_birthdate = f"1967-{random.randint(1,12):02d}-{random.randint(1,28):02d}"

        member1 = self.create_test_member(
            first_name="ThresholdTest",
            last_name="FilteringOne",
            birth_date=unique_birthdate
        )

        # Create address for low-confidence match - test user already has System Manager role
        address = frappe.get_doc({
            "doctype": "Address",
            # address_type set explicitly: EnhancedTestCase runs with
            # frappe.flags.in_import, which suppresses DocType field defaults.
            "address_type": "Personal",
            "address_title": f"Test Address {unique_suffix}",
            "address_line1": "Teststraat 1",
            "city": "Amsterdam",
            "pincode": "1234 AB",
            "country": "Netherlands"
        }).insert()

        member2 = self.create_test_member(
            first_name="ThresholdTest",
            last_name="FilteringTwo",
            primary_address=address.name,
            birth_date="1985-05-15"  # Different birthdate, won't match on name+DOB
        )

        # Set member1's address
        frappe.db.set_value("Member", member1.name, "primary_address", address.name)

        # Search with high threshold (0.9) - address match (0.6) should be excluded
        duplicates_high = find_potential_duplicates(
            member_name=member1.name,
            email=None,
            iban=None,
            first_name="ThresholdTest",
            last_name="FilteringOne",
            tussenvoegsel=None,
            birth_date=unique_birthdate,
            primary_address=address.name,
            threshold=0.9
        )

        # Search with low threshold (0.5) - address match should be included
        duplicates_low = find_potential_duplicates(
            member_name=member1.name,
            email=None,
            iban=None,
            first_name="ThresholdTest",
            last_name="FilteringOne",
            tussenvoegsel=None,
            birth_date=unique_birthdate,
            primary_address=address.name,
            threshold=0.5
        )

        self.assertEqual(len(duplicates_high), 0)
        self.assertGreater(len(duplicates_low), 0)


class TestAPISecurity(EnhancedTestCase):
    """Test API endpoint security features"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_api_requires_valid_member_name(self):
        """API should validate member name input"""
        # Test user already has System Manager role from setUp()

        # Test with invalid member name
        result = check_duplicate_for_approval("NonExistentMember123")

        # check_duplicate_for_approval is decorated with an API security
        # decorator, which serializes the OperationResult into the nested-schema
        # dict (success/error/meta) via to_dict(). Assert on dict keys.
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])
        self.assertEqual(result.get("meta", {}).get("has_duplicates"), False)

    def test_api_success_categorizes_duplicates(self):
        """The success path returns duplicates bucketed by confidence level.

        A shared email is a 1.0 (high-confidence) match, so checking the second
        member must report has_duplicates True with the email match landing in
        the high_confidence bucket and the summary counts agreeing.
        """
        import uuid

        shared_email = f"dup.api.{uuid.uuid4().hex[:8]}@example.com"
        member1 = self.create_test_member(
            first_name="Api", last_name="DupOne", email=shared_email, birth_date="1985-05-05"
        )
        # Second member shares the email (definitive 1.0 match against member1).
        member2 = self.create_test_member(
            first_name="Api", last_name="DupTwo", email=shared_email, birth_date="1985-05-05"
        )

        # Force the shared email post-creation so the factory's uniquifier cannot
        # split the two members apart (see set_shared_email).
        set_shared_email(member1.name, shared_email)
        set_shared_email(member2.name, shared_email)

        result = check_duplicate_for_approval(member1.name)

        # Decorator serializes the OperationResult; the success payload is under data.
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertTrue(data["has_duplicates"])
        self.assertGreaterEqual(data["duplicate_count"], 1)
        # The email match (1.0) is high-confidence.
        self.assertGreaterEqual(data["summary"]["high"], 1)
        # Summary counts are internally consistent with the bucket lengths.
        self.assertEqual(data["summary"]["high"], len(data["high_confidence"]))
        self.assertEqual(data["summary"]["medium"], len(data["medium_confidence"]))
        self.assertEqual(data["summary"]["low"], len(data["low_confidence"]))

    def test_api_permission_check(self):
        """API should check user permissions"""
        # Create the member as the default (System Manager) test user from setUp().
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            birth_date="1990-01-01"
        )

        # As an unauthenticated guest the API must refuse with a permission error
        # (raised by the API security framework). as_user() restores the original
        # session user automatically on exit, so we don't leave Guest context
        # leaking into later tests.
        from verenigingen.utils.error_handling import PermissionError as VPermissionError
        with self.as_user("Guest"):
            with self.assertRaises((frappe.PermissionError, VPermissionError)):
                check_duplicate_for_approval(member.name)

    def test_api_sanitizes_error_messages(self):
        """API should not expose internal error details"""
        # Test user already has System Manager role from setUp()

        # Test with invalid member name
        result = check_duplicate_for_approval("InvalidName123")

        # Decorator serializes OperationResult into the nested-schema dict.
        self.assertFalse(result["success"])
        # Error should be user-friendly, not exposing internals
        error_message = result["error"]["message"] or ""
        self.assertNotIn("Traceback", error_message)
        self.assertNotIn("Exception", error_message)


class TestEdgeCases(EnhancedTestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        super().setUp()
        clear_rate_limits()

    def test_empty_fields_handled_gracefully(self):
        """Empty or None fields should not cause errors"""
        duplicates = find_potential_duplicates(
            member_name="TEST-001",
            email=None,
            iban=None,
            first_name=None,
            last_name=None,
            tussenvoegsel=None,
            birth_date=None,
            primary_address=None,
            threshold=0.6
        )

        # Should return empty list, not error
        self.assertEqual(len(duplicates), 0)

    def test_unicode_names_handled_correctly(self):
        """Unicode characters in names should be handled"""
        member = self.create_test_member(
            first_name="François",
            last_name="Müller",
            birth_date="1990-01-01"
        )

        # Calculate similarity with unicode names
        similarity = _calculate_name_similarity(
            "François", "Müller", None,
            "François", "Müller", None
        )

        # Should match perfectly
        self.assertEqual(similarity, 1.0)

    def test_special_characters_in_names(self):
        """Special characters should not break matching"""
        member = self.create_test_member(
            first_name="Jan-Pieter",
            last_name="O'Brien",
            birth_date="1990-01-01"
        )

        similarity = _calculate_name_similarity(
            "Jan-Pieter", "O'Brien", None,
            "Jan-Pieter", "O'Brien", None
        )

        self.assertEqual(similarity, 1.0)
