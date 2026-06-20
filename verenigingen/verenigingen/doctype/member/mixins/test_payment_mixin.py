"""
Tests for verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py

PaymentMixin is mixed into the Member controller. These tests target the
independently-testable, branch-heavy validation / helper methods that are not
already covered elsewhere:

- set_payment_reference()      : payment_reference defaulting
- validate_bank_details()      : SEPA Direct Debit IBAN / account-holder guards
- validate_iban_format()       : empty-input short circuit + real IBAN formatting
- get_member_chapters()        : Chapter Member lookup (and error fallback)
- _is_chapter_management_enabled()

All tests use REAL Member / Chapter documents; no business logic is mocked.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentMixin(EnhancedTestCase):
    # ------------------------------------------------------------------
    # set_payment_reference
    # ------------------------------------------------------------------
    def test_set_payment_reference_defaults_to_name(self):
        """When no payment_reference is set it defaults to the member's name."""
        member = self.create_test_member(first_name="PayRef", last_name="Default")
        member.payment_reference = None
        member.set_payment_reference()
        self.assertEqual(member.payment_reference, member.name)

    def test_set_payment_reference_preserves_existing(self):
        """An existing payment_reference is left untouched."""
        member = self.create_test_member(first_name="PayRef", last_name="Keep")
        member.payment_reference = "CUSTOM-REF-1"
        member.set_payment_reference()
        self.assertEqual(member.payment_reference, "CUSTOM-REF-1")

    # ------------------------------------------------------------------
    # validate_iban_format
    # ------------------------------------------------------------------
    def test_validate_iban_format_empty_returns_none(self):
        """An empty IBAN short-circuits to None before any service call."""
        member = self.create_test_member(first_name="Iban", last_name="Empty")
        self.assertIsNone(member.validate_iban_format(""))
        self.assertIsNone(member.validate_iban_format(None))

    def test_validate_iban_format_formats_valid_iban(self):
        """A valid IBAN is returned normalised (spaced/grouped) by the service."""
        member = self.create_test_member(first_name="Iban", last_name="Valid")
        formatted = member.validate_iban_format("NL13TEST0123456789")
        self.assertIsInstance(formatted, str)
        # Formatting strips/regroups but preserves the alphanumerics.
        self.assertEqual(formatted.replace(" ", ""), "NL13TEST0123456789")

    def test_validate_iban_format_rejects_invalid(self):
        """A structurally invalid IBAN raises a ValidationError."""
        member = self.create_test_member(first_name="Iban", last_name="Bad")
        with self.assertRaises(frappe.ValidationError):
            member.validate_iban_format("NOT-AN-IBAN")

    # ------------------------------------------------------------------
    # validate_bank_details - SEPA Direct Debit guards
    # ------------------------------------------------------------------
    def test_validate_bank_details_sepa_requires_iban(self):
        """SEPA Direct Debit with no IBAN raises a clear ValidationError."""
        member = self.create_test_member(first_name="Bank", last_name="NoIban")
        member.payment_method = "SEPA Direct Debit"
        member.iban = None
        member.bank_account_name = "Holder"
        with self.assertRaises(frappe.ValidationError) as ctx:
            member.validate_bank_details()
        # Pin the specific message so the IBAN vs holder branches can't be swapped.
        self.assertIn("IBAN is required", str(ctx.exception))

    def test_validate_bank_details_sepa_requires_account_holder(self):
        """SEPA Direct Debit with IBAN but no account holder name raises."""
        member = self.create_test_member(first_name="Bank", last_name="NoHolder")
        member.payment_method = "SEPA Direct Debit"
        member.iban = "NL13TEST0123456789"
        member.bank_account_name = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            member.validate_bank_details()
        self.assertIn("Account Holder Name is required", str(ctx.exception))

    def test_validate_bank_details_non_sepa_no_throw(self):
        """A non-SEPA member with no bank details validates cleanly (no throw)."""
        member = self.create_test_member(first_name="Bank", last_name="Transfer")
        member.payment_method = "Bank Transfer"
        member.iban = None
        # Should not raise.
        member.validate_bank_details()

    # ------------------------------------------------------------------
    # get_member_chapters / _is_chapter_management_enabled
    # ------------------------------------------------------------------
    def test_get_member_chapters_empty_for_unaffiliated(self):
        """A member in no chapter returns an empty list of chapters."""
        member = self.create_test_member(first_name="NoChap", last_name="Member")
        self.assertEqual(member.get_member_chapters(), [])

    def test_get_member_chapters_lists_enabled_membership(self):
        """get_member_chapters returns the parent chapter of enabled Chapter Member rows."""
        member = self.create_test_member(first_name="HasChap", last_name="Member")
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member.name, "enabled": 1, "chapter_join_date": frappe.utils.today()},
        )
        chapter.save()

        chapters = member.get_member_chapters()
        self.assertIn(chapter.name, chapters)

    def test_is_chapter_management_enabled_reflects_setting(self):
        """Pins the method to the real Verenigingen Settings flag, not just 'a bool'."""
        member = self.create_test_member(first_name="ChapMgmt", last_name="Flag")
        expected = frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        self.assertEqual(member._is_chapter_management_enabled(), expected)
