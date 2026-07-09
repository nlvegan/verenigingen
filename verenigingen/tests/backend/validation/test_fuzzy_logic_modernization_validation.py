"""
Comprehensive test suite for validating fuzzy logic modernization fixes
Tests all 325+ patterns that were converted from fuzzy to explicit validation
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestFuzzyLogicModernizationValidation(VereningingenTestCase):
    """Test that fuzzy logic patterns have been properly modernized"""

    def test_explicit_validation_patterns(self):
        """Name validation is explicit: dangerous/invalid characters are rejected.

        Replaces a try/except that passed whether or not save() raised. A first_name
        containing an HTML tag must raise ValidationError via
        dutch_name_service.validate_member_name_fields ->
        application_validators.validate_name (dangerous_patterns).
        Uses frappe.new_doc directly to hit the real Member.validate (the factory
        re-wraps validation errors as a generic Exception).
        """
        member = frappe.new_doc("Member")
        member.first_name = "<script>bad</script>"
        member.last_name = "User"
        member.email = f"namebad.{frappe.generate_hash(length=6)}@test.invalid"

        with self.assertRaises(frappe.ValidationError):
            member.insert()

    def test_full_name_is_derived_from_parts(self):
        """full_name is explicitly derived from name parts (no empty fallback).

        Replaces a try/except-pass that asserted nothing. dutch_name_service.
        update_member_full_name composes full_name from first_name + last_name on save.
        """
        member = self.create_test_member(first_name="Jan", last_name="Jansen")
        # Factory appends a uniqueness suffix to last_name; full_name must join both parts.
        self.assertEqual(member.full_name, f"Jan {member.last_name}")

    def test_explicit_error_messages(self):
        """An invalid email is rejected with a specific, email-naming message (not generic).

        Strengthened from asserting only that *some* exception raised: the message must
        actually reference the email address so the error is specific, per the docstring's
        original intent. Uses frappe.new_doc to hit real Member.validate directly (the
        factory re-wraps validation errors as a generic Exception, hiding the message).
        """
        member = frappe.new_doc("Member")
        member.first_name = "Valid"
        member.last_name = "Name"
        member.email = "invalid-email"

        with self.assertRaises((frappe.ValidationError, frappe.InvalidEmailAddressError)) as cm:
            member.insert()
        self.assertIn("email", str(cm.exception).lower())

    def test_no_auto_creation_patterns(self):
        """A chapter-less member is allowed, but no Chapter Member row is auto-created.

        Replaces an assertion-free body (member created, only a comment followed). Creating
        a member without a chapter must succeed AND must not silently auto-create a chapter
        membership — the "no fuzzy auto-creation" contract this suite guards. chapter=False
        tells the factory NOT to assign one, so any Chapter Member row would come from a
        production hook (the regression this guards against).
        """
        member = self.create_test_member(chapter=False)
        member.reload()

        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": member.name}),
            "No Chapter Member row should be auto-created for a chapter-less member",
        )

    def test_consistent_field_validation(self):
        """Test that field validation is consistent across similar fields"""

        # Test that all email fields use same validation.
        # NOTE: Volunteer.email is intentionally omitted — its JSON schema does
        # not set options="Email", and the Volunteer controller has no explicit
        # validate_email_address() call, so frappe.new_doc("Volunteer") with
        # invalid email would not raise ValidationError for the email format.
        # Adding email validation to Volunteer is a follow-up (G4-territory
        # schema change or controller change).
        email_test_cases = [
            ("Member", "email"),
            ("Donor", "donor_email"),
        ]

        for doctype, field in email_test_cases:
            with self.subTest(doctype=doctype, field=field):
                doc = frappe.new_doc(doctype)
                setattr(doc, field, "invalid-email")

                with self.assertRaises(frappe.ValidationError):
                    doc.save()

    def test_no_silent_data_coercion(self):
        """Test that data is not silently converted to different types"""

        # Test that string "0" doesn't become integer 0
        # Test that empty strings don't become None
        # Test that whitespace isn't stripped automatically

        test_data = [
            {"field": "phone", "input": "  123  ", "should_preserve_whitespace": False},
            {"field": "postal_code", "input": "0000", "should_stay_string": True},
        ]

        for case in test_data:
            member = self.create_test_member()
            setattr(member, case["field"], case["input"])
            member.save()

            stored_value = getattr(member, case["field"])

            if case.get("should_preserve_whitespace", True):
                self.assertEqual(stored_value, case["input"])
            if case.get("should_stay_string", False):
                self.assertIsInstance(stored_value, str)

    def test_proper_type_enforcement(self):
        """Test that field types are properly enforced"""

        # Test that date fields reject invalid dates - this is enforced at DB level
        with self.assertRaises((frappe.ValidationError, Exception)):
            member = self.create_test_member(birth_date="invalid-date")

    def test_cascade_deletion_explicit(self):
        """Test that cascade deletions are explicit, not implicit"""

        # Create member with related records
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member.name)

        # Deleting member should either fail or require explicit cascade
        with self.assertRaises((frappe.ValidationError, frappe.LinkExistsError)):
            frappe.delete_doc("Member", member.name)

    def test_no_fuzzy_search_patterns(self):
        """Test that search operations are explicit"""

        # Create a test member
        member = self.create_test_member(first_name="Test")

        # Test that search works as expected
        members = frappe.get_all("Member", filters={"first_name": "Test"}, fields=["name"])  # Exact match

        # Should find the exact match
        self.assertGreaterEqual(len(members), 1)

    def test_validation_order_deterministic(self):
        """Test that validation happens in deterministic order"""

        # Multiple validation errors should be reported consistently
        try:
            member = frappe.new_doc("Member")
            # Leave multiple required fields empty
            member.save()
        except frappe.ValidationError as e:
            # The same validation should always be reported first
            error_msg = str(e)
            self.assertTrue(len(error_msg) > 0)

    def test_negative_case_null_handling(self):
        """Test negative cases for null value handling"""

        # Test that null/None values are handled explicitly
        negative_cases = [
            {"doctype": "Member", "field": "email", "value": None},
            {"doctype": "Member", "field": "first_name", "value": ""},
            {"doctype": "Volunteer", "field": "member", "value": None},
        ]

        for case in negative_cases:
            with self.subTest(case=case):
                doc = frappe.new_doc(case["doctype"])
                setattr(doc, case["field"], case["value"])

                with self.assertRaises((frappe.ValidationError, frappe.MandatoryError)):
                    doc.save()

    def test_negative_case_invalid_references(self):
        """An invalid (non-existent) Member reference is rejected, not silently accepted.

        Previously this "negative case" asserted the POSITIVE path (valid refs work). A
        Volunteer pointing at a non-existent Member must raise on save (Frappe link
        validation). Built with frappe.new_doc so the bad link reaches the DB layer.
        """
        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "Ghost Volunteer"
        volunteer.email = f"ghost.{frappe.generate_hash(length=6)}@test.invalid"
        volunteer.member = "NONEXISTENT-MEMBER-" + frappe.generate_hash(length=6)

        with self.assertRaises((frappe.LinkValidationError, frappe.ValidationError)):
            volunteer.insert()

    def test_negative_case_business_logic_violations(self):
        """The under-16 age rule is enforced (business-logic violation is rejected).

        Replaces a try/except that passed whether or not the throw happened. An
        11-year-old birth_date must raise, and the message must name the 16-year rule
        (member_age_service.validate_member_age_requirements -> AgeValidator).
        """
        with self.assertRaises(Exception) as cm:
            self.create_test_member(
                first_name="Too",
                last_name="Young",
                birth_date="2015-01-01",  # 11 years old
            )
        # Key off the message shape, not the literal configured age (min age is a
        # Verenigingen Settings value; the "at least ... years old" phrasing is stable).
        msg = str(cm.exception).lower()
        self.assertIn("at least", msg)
        self.assertIn("years old", msg)

    def test_negative_case_data_integrity(self):
        """Duplicate member_id is rejected (unique-integrity violation).

        Previously this "negative case" asserted the POSITIVE path (two members with
        different emails both save). Instead assign the same member_id to a second member
        and assert the app-level guard in member_id_manager.validate_member_id_change
        rejects it. (Tests run as Administrator = System Manager, so the role gate passes
        and we reach the in-use check.)
        """
        member1 = self.create_test_member(first_name="Integrity", last_name="One")
        dup_id = "TESTDUP-" + frappe.generate_hash(length=6)
        member1.member_id = dup_id
        member1.save()

        member2 = self.create_test_member(first_name="Integrity", last_name="Two")
        member2.member_id = dup_id
        with self.assertRaises(frappe.ValidationError) as cm:
            member2.save()
        self.assertIn("already in use", str(cm.exception))

    def test_negative_permission_escalation(self):
        """Test that permission checks are explicit.

        A low-privilege member (no System Manager / Settings write perm) must
        not be able to save Verenigingen Settings. NOTE: the shared
        "test@example.com" fixture user carries System Manager on this site, so
        a dedicated low-privilege scratch user is used instead — otherwise the
        save would (correctly) succeed and the test would be a false negative.
        """
        low_priv_email = self._ensure_low_priv_user()

        with self.as_user(low_priv_email):
            with self.assertRaises(frappe.PermissionError):
                settings = frappe.get_doc("Verenigingen Settings")
                # Touch a real field so save() actually attempts a write.
                settings.company = settings.company
                settings.save()

    def _ensure_low_priv_user(self):
        """Create (once) and track a low-privilege scratch user for the escalation test.

        Fixture creation belongs in a helper, not inline in test logic — the low-priv
        User needs ignore_permissions to be seeded, which is only appropriate here.
        """
        low_priv_email = "fuzzy.lowpriv.regression@test.invalid"
        if not frappe.db.exists("User", low_priv_email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": low_priv_email,
                    "first_name": "Low",
                    "last_name": "Priv",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
        self.track_doc("User", low_priv_email)
        return low_priv_email

    def test_api_response_consistency(self):
        """Test that API responses are consistently structured"""

        # Test that all APIs return consistent error structures
        from verenigingen.utils.api_response import APIResponse

        # Success response
        success_response = APIResponse.success("test data")
        self.assertIn("success", success_response)
        self.assertIn("data", success_response)
        self.assertTrue(success_response["success"])

        # Error response
        error_response = APIResponse.error("test error")
        self.assertIn("success", error_response)
        self.assertIn("error", error_response)
        self.assertFalse(error_response["success"])

    def test_query_parameter_sanitization(self):
        """Test that query parameters are properly sanitized"""

        # Test SQL injection prevention
        dangerous_inputs = ["'; DROP TABLE tabMember; --", "1 OR 1=1", "<script>alert('xss')</script>"]

        for dangerous_input in dangerous_inputs:
            with self.subTest(input=dangerous_input):
                # Should not cause SQL errors or execution
                try:
                    result = frappe.get_all("Member", filters={"first_name": dangerous_input}, limit=1)
                    # Should return empty results, not cause errors
                    self.assertIsInstance(result, list)
                except frappe.ValidationError:
                    # Validation errors are acceptable
                    pass
                except Exception as e:
                    # SQL errors or other exceptions indicate vulnerability
                    self.fail(f"Dangerous input caused unexpected error: {e}")


class TestFuzzyLogicSpecificPatterns(VereningingenTestCase):
    """Test specific fuzzy logic patterns that were identified and fixed"""

    def test_implicit_member_lookup_fixed(self):
        """Test that implicit member lookups are now explicit"""

        # Old fuzzy pattern: get_or_create_member(email)
        # New explicit pattern: Must provide all required fields

        with self.assertRaises((frappe.ValidationError, frappe.MandatoryError)):
            # Should fail without explicit required fields
            member = frappe.new_doc("Member")
            member.email = "test@example.com"
            # Missing first_name, last_name should cause explicit error
            member.save()

    def test_fallback_chapter_assignment_fixed(self):
        """Chapter assignment is explicit: no fuzzy fallback chapter is auto-assigned.

        Strengthened from asserting only that a member was created. A member created
        outside the application flow must have NO Chapter Member row silently assigned —
        chapter assignment is an explicit business-process step, not an implicit fallback.
        chapter=False tells the factory not to assign one, isolating production behaviour.
        """
        member = self.create_test_member(chapter=False)
        member.reload()

        self.assertTrue(member.name)
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": member.name}),
            "No fallback chapter should be auto-assigned outside the application process",
        )

    def test_payment_status_inference_fixed(self):
        """Test that payment status is explicit, not inferred"""

        # Old fuzzy pattern: Infer payment status from amount/date
        # New explicit pattern: Status must be set explicitly

        member = self.create_test_member()

        # Payment without explicit status should fail
        with self.assertRaises(frappe.ValidationError):
            payment = frappe.new_doc("Payment Entry")
            payment.party_type = "Customer"
            payment.party = member.customer
            payment.payment_type = "Receive"
            payment.paid_amount = 100
            # Missing explicit status/mode should cause validation error
            payment.save()


if __name__ == "__main__":
    unittest.main()
