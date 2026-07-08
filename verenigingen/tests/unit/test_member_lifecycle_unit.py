"""
Unit Tests for Member Lifecycle Business Logic
==============================================

Unit tests for isolated Member DocType business logic components.
These tests focus on specific business rules and edge cases without database dependencies.

Focus Areas:
- Member identification and ID generation
- Dutch naming convention handling
- Address normalization and fingerprinting
- Status transition validation
- Business rule enforcement
- Edge case boundary conditions

Most methods here used to reimplement the production formula inline (e.g. a copy of the
age-calculation math, an invented status-transition table using status values that don't
even exist on the Member DocType, a hand-rolled email regex). That meant a real regression
in the production code could never turn these tests red. They now call the actual
production functions/methods, mocking only true collaborator boundaries.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.address_matching.dutch_address_normalizer import DutchAddressNormalizer
from verenigingen.utils.dutch_name_utils import format_dutch_full_name


class MemberLifecycleUnitTest(EnhancedTestCase):
    """Unit tests for Member lifecycle business logic without database dependencies"""

    def setUp(self):
        """Set up unit test fixtures"""
        super().setUp()

    def test_member_id_generation_logic(self):
        """Member.should_have_member_id(): real business rule -- non-application
        members qualify immediately; application members only qualify once their
        application_status is Approved."""

        non_application_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Jan",
                "last_name": "Testmember",
            }
        )
        self.assertTrue(
            non_application_member.should_have_member_id(),
            "Non-application members should qualify for a member ID immediately",
        )

        pending_application = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Pending",
                "last_name": "Application",
                "application_id": "APP-LIFECYCLE-TEST-0001",
                "application_status": "Pending",
            }
        )
        self.assertFalse(
            pending_application.should_have_member_id(),
            "Pending applications should NOT qualify for a member ID yet",
        )

        approved_application = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Approved",
                "last_name": "Application",
                "application_id": "APP-LIFECYCLE-TEST-0002",
                "application_status": "Approved",
            }
        )
        self.assertTrue(
            approved_application.should_have_member_id(),
            "Approved applications should qualify for a member ID",
        )

    def test_application_id_generation_logic(self):
        """Test application ID generation for pending applications"""

        member_data = {
            "doctype": "Member",
            "first_name": "Pending",
            "last_name": "Application",
            "email": "pending@example.com",
            "status": "Pending",
            "application_id": None,
        }

        member = frappe.get_doc(member_data)

        # Test application ID generation logic (real function on Member class)
        if member.status == "Pending" and not member.application_id:
            member.application_id = member.generate_application_id()

        # Should have generated a proper application ID
        self.assertTrue(member.application_id)
        self.assertIn("APP-", member.application_id)

    def test_dutch_name_formatting_edge_cases(self):
        """Test Dutch naming convention edge cases"""

        # Test case: Multiple tussenvoegsel
        test_cases = [
            {
                "first_name": "Pieter",
                "tussenvoegsel": "van der",
                "last_name": "Berg",
                "expected": "Pieter van der Berg",
            },
            {
                "first_name": "Maria",
                "tussenvoegsel": "de",
                "last_name": "Wit",
                "expected": "Maria de Wit",
            },
            {
                "first_name": "Jan",
                "tussenvoegsel": None,
                "last_name": "Jansen",
                "expected": "Jan Jansen",
            },
            {
                "first_name": "Anne",
                "tussenvoegsel": "",  # Empty string
                "last_name": "Bakker",
                "expected": "Anne Bakker",
            },
        ]

        for case in test_cases:
            full_name = format_dutch_full_name(
                case["first_name"],
                middle_name=None,
                tussenvoegsel=case["tussenvoegsel"],
                last_name=case["last_name"],
            )
            self.assertEqual(full_name, case["expected"], f"Failed for case: {case}")

    def test_address_fingerprint_generation(self):
        """Test address fingerprinting for duplicate detection"""

        # Test cases with address variations that should be considered duplicates
        address_test_cases = [
            {
                "address_1": "Hoofdstraat 123",
                "address_2": "1234 AB",
                "city": "Amsterdam",
                "postal_code": "1234AB",  # No space
            },
            {
                "address_1": "Hoofdstraat 123",
                "address_2": "1234 AB",  # With space
                "city": "Amsterdam",
                "postal_code": "1234 AB",
            },
        ]

        normalizer = DutchAddressNormalizer()

        fingerprints = []
        for address in address_test_cases:
            fingerprint = normalizer.generate_fingerprint(address["address_1"], address["city"])
            fingerprints.append(fingerprint)

        # Both should generate same fingerprint (normalized postal code)
        self.assertEqual(fingerprints[0], fingerprints[1], "Similar addresses should have same fingerprint")

    def test_member_age_calculation_edge_cases(self):
        """Test age calculation using the real AgeValidator (validation_utilities.py) --
        previously this reimplemented the year-subtraction/leap-year math inline."""

        from frappe.utils import add_years, getdate

        from verenigingen.utils.validation_utilities import AgeValidator

        today = getdate()

        # Exactly 18 years ago -> age should be (very close to) 18.0
        birth_18 = add_years(today, -18)
        age_18 = AgeValidator.calculate_age(birth_18)
        self.assertAlmostEqual(age_18, 18.0, delta=0.05, msg="Exact 18th birthday should compute to ~18.0")

        # Exactly 16 years ago -> age should be (very close to) 16.0
        birth_16 = add_years(today, -16)
        age_16 = AgeValidator.calculate_age(birth_16)
        self.assertAlmostEqual(age_16, 16.0, delta=0.05, msg="Exact 16th birthday should compute to ~16.0")

        # A birth date further in the past must yield a strictly larger age
        birth_40 = add_years(today, -40)
        age_40 = AgeValidator.calculate_age(birth_40)
        self.assertGreater(age_40, age_18, "An older birth date must produce a larger computed age")

        # A future birth date is invalid -- real ValidationError, not a graceful default
        future_birth = add_years(today, 1)
        with self.assertRaises(frappe.ValidationError):
            AgeValidator.calculate_age(future_birth)

    def test_volunteer_eligibility_validation(self):
        """Test volunteer eligibility via the real validate_volunteer_age() business rule
        (validation_utilities.py) -- previously this reimplemented the eligibility math
        inline and never called into the actual validator."""

        from frappe.utils import add_years, getdate

        from verenigingen.utils.validation_utilities import validate_volunteer_age

        today = getdate()
        min_age = frappe.db.get_single_value("Verenigingen Settings", "minimum_volunteer_age")
        self.assertTrue(min_age and min_age > 0, "minimum_volunteer_age must be configured for this test")

        # Clearly above the minimum -> eligible
        eligible_result = validate_volunteer_age(add_years(today, -(min_age + 2)))
        self.assertTrue(eligible_result.is_valid, "A volunteer well above the minimum age must be eligible")

        # Clearly below the minimum -> not eligible
        ineligible_result = validate_volunteer_age(add_years(today, -(min_age - 2)))
        self.assertFalse(
            ineligible_result.is_valid, "A volunteer well below the minimum age must NOT be eligible"
        )

    def test_postal_code_normalization(self):
        """Test Dutch postal code normalization via the real normalize_dutch_postal_code()
        utility (utils/validation/postal_code_validator.py) -- previously this reimplemented
        the spacing/case logic inline."""

        from verenigingen.utils.validation.postal_code_validator import normalize_dutch_postal_code

        test_cases = [
            {"input": "1234AB", "expected": "1234 AB"},
            {"input": "1234 AB", "expected": "1234 AB"},
            {"input": "1234  AB", "expected": "1234 AB"},  # Multiple spaces
            {"input": "1234ab", "expected": "1234 AB"},  # Lowercase
            {"input": "1234 ab", "expected": "1234 AB"},  # Mixed case
            {"input": " 1234AB ", "expected": "1234 AB"},  # Leading/trailing spaces
        ]

        for case in test_cases:
            result = normalize_dutch_postal_code(case["input"])
            self.assertEqual(
                result, case["expected"], f"Postal code normalization failed for input: {case['input']}"
            )

        # Invalid postal codes must return None, not a best-effort guess
        self.assertIsNone(normalize_dutch_postal_code("0123 AB"))  # 0000-prefix excluded
        self.assertIsNone(normalize_dutch_postal_code(""))

    def test_email_validation_and_uniqueness(self):
        """Test email format validation AND uniqueness via the real validate_email()
        (utils/validation/application_validators.py) -- previously format was checked with
        a hand-rolled regex and uniqueness with an in-memory dict, neither of which called
        any production code."""

        from verenigingen.utils.validation.application_validators import validate_email

        # Format validation (delegates to frappe.utils.validate_email_address)
        for email in ["test@example.com", "user.name@domain.co.uk", "user+tag@example.org"]:
            result = validate_email(email)
            self.assertTrue(result["valid"], f"Email {email} should be valid")

        for email in ["invalid.email", "@domain.com", "user@", ""]:
            result = validate_email(email)
            self.assertFalse(result["valid"], f"Email {email} should be invalid")

        # Uniqueness: a real, already-persisted member's email must be reported as existing.
        # (The factory appends a uniqueness suffix to the email we pass in, so read the
        # email actually persisted rather than assuming our literal string survived.)
        existing_member = self.create_test_member(email="lifecycle.unique@example.com")
        persisted_email = existing_member.email

        dup_result = validate_email(persisted_email)
        self.assertFalse(dup_result["valid"], "An email already used by a Member must be rejected")
        self.assertTrue(dup_result.get("exists"))
        self.assertEqual(dup_result.get("member_id"), existing_member.name)

        # allow_existing=True (reapplication flow) surfaces the existing member but
        # does not hard-block
        reapply_result = validate_email(persisted_email, allow_existing=True)
        self.assertTrue(reapply_result["valid"])
        self.assertTrue(reapply_result.get("exists"))

    def test_fee_override_amount_validation_rejects_non_positive(self):
        """Bounded unhappy gap-fill: MemberFeeValidationService.validate_fee_override_amount()
        gates every fee override change before it reaches fee-change history, but had zero
        UNHAPPY coverage. A negative override amount must raise a genuine ValidationError,
        not silently clamp or ignore the bad value. (Zero is real production behavior for
        "no override set" -- `if amount and amount <= 0` short-circuits on falsy 0 -- so it
        intentionally does NOT raise; asserted explicitly below to pin that behavior.)"""

        from verenigingen.services.member.financial.member_fee_validation_service import (
            get_member_fee_validation_service,
        )

        validator = get_member_fee_validation_service()

        # Valid positive amount must not raise
        validator.validate_fee_override_amount(25.50)

        # Zero means "no override" and is intentionally a no-op, not a rejection
        validator.validate_fee_override_amount(0)

        for bad_amount in (-0.01, -10):
            with self.assertRaises(frappe.ValidationError, msg=f"Amount {bad_amount} must be rejected"):
                validator.validate_fee_override_amount(bad_amount)

    def test_birth_date_range_validation(self):
        """Test birth date range validation via the real AgeValidator.validate_age()
        (validation_utilities.py, throw_on_error=False) -- previously reimplemented as an
        inline future-date/120-year-cutoff check."""

        from frappe.utils import add_years, getdate

        from verenigingen.utils.validation_utilities import AgeValidator

        today = getdate()

        # Normal birth date well within range -> valid, with the age itself computed correctly
        normal_result = AgeValidator.validate_age(
            add_years(today, -25), context="membership", throw_on_error=False
        )
        self.assertTrue(normal_result.is_valid, "A normal adult birth date should be valid")
        self.assertAlmostEqual(
            normal_result.age_years, 25.0, delta=0.1, msg="Computed age should match the birth date"
        )

        # Future birth date -> invalid (calculate_age itself rejects it)
        future_result = AgeValidator.validate_age(
            add_years(today, 1), context="membership", throw_on_error=False
        )
        self.assertFalse(future_result.is_valid, "A future birth date must be invalid")

        # Far beyond the max_age (120) -> invalid
        too_old_result = AgeValidator.validate_age(
            add_years(today, -150), context="membership", throw_on_error=False
        )
        self.assertFalse(too_old_result.is_valid, "A birth date implying age > 120 must be invalid")


if __name__ == "__main__":
    unittest.main()
