# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for services/member/approval/application_helpers.py.

This is the membership-application utils-bag. Tests drive REAL Member /
Membership Type / Chapter / Dues Schedule docs through the helper functions
to verify:
- payment-method mapping + validation (missing Mode of Payment throws)
- application data parsing (JSON string, HTML-entity decode, error path)
- member creation from application data (sanitized names, owner override,
  custom-fee override, application tracking fields)
- reapplication update of an existing member
- canonical fee-info resolution + its thin wrappers
- suggested-amount tiers + strict validation
- chapter membership lifecycle: pending -> active -> removed
- volunteer record creation on approval
- draft save/load round trip
- application-status lookup (PII-safe response)
"""

import frappe

from verenigingen.services.member.approval import application_helpers as helpers
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _make_membership_type(factory, amount=24.0):
    """Helper: create a Membership Type with a template at a known amount."""
    return factory.create_test_membership_type(membership_type_name="HelpersType", amount=amount)


class TestPaymentMethodMapping(EnhancedTestCase):
    """map_payment_method / payment-mode helpers."""

    def setUp(self):
        super().setUp()
        # Ensure standard modes exist so validate=True passes for known methods
        helpers.ensure_payment_modes_exist()

    def test_maps_form_value_to_mode_of_payment(self):
        """A form value like 'bank_transfer' maps to 'Bank Transfer'."""
        self.assertEqual(helpers.map_payment_method("bank_transfer"), "Bank Transfer")
        self.assertEqual(helpers.map_payment_method("sepa_direct_debit"), "SEPA Direct Debit")
        self.assertEqual(helpers.map_payment_method("mollie"), "Mollie")

    def test_unknown_value_defaults_to_bank_transfer(self):
        """Unknown form values fall back to Bank Transfer."""
        self.assertEqual(helpers.map_payment_method("totally_unknown"), "Bank Transfer")

    def test_display_value_passes_through(self):
        """Already-mapped display values map to themselves."""
        self.assertEqual(helpers.map_payment_method("Bank Transfer"), "Bank Transfer")

    def test_validate_false_skips_existence_check(self):
        """validate=False returns mapped value without DB check."""
        # 'credit_card' maps to 'Credit Card' which is not a seeded mode;
        # validate=False must not throw.
        self.assertEqual(helpers.map_payment_method("credit_card", validate=False), "Credit Card")

    def test_missing_mode_throws_validation_error(self):
        """A mapped Mode of Payment that does not exist raises ValidationError."""
        target = "Credit Card"
        # Remove the mode if present so the validation path triggers.
        if frappe.db.exists("Mode of Payment", target):
            frappe.delete_doc("Mode of Payment", target, force=True, ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError) as ctx:
            helpers.map_payment_method("credit_card", validate=True)
        self.assertIn("Credit Card", str(ctx.exception))

    def test_validate_payment_method_exists(self):
        """validate_payment_method_exists reflects DB existence."""
        self.assertTrue(helpers.validate_payment_method_exists("Bank Transfer"))
        self.assertFalse(helpers.validate_payment_method_exists("NoSuchMode-XYZ"))

    def test_ensure_payment_modes_exist_creates_missing(self):
        """ensure_payment_modes_exist creates a removed standard mode."""
        if frappe.db.exists("Mode of Payment", "Mollie"):
            frappe.delete_doc("Mode of Payment", "Mollie", force=True, ignore_permissions=True)
        created = helpers.ensure_payment_modes_exist()
        self.assertIn("Mollie", created)
        self.assertTrue(frappe.db.exists("Mode of Payment", "Mollie"))


class TestParseApplicationData(EnhancedTestCase):
    """parse_application_data."""

    def test_parses_json_string(self):
        result = helpers.parse_application_data('{"email": "a@b.com", "first_name": "Jan"}')
        self.assertEqual(result["email"], "a@b.com")
        self.assertEqual(result["first_name"], "Jan")

    def test_decodes_html_entities_in_string(self):
        """An HTML-escaped apostrophe is decoded back to a real character."""
        result = helpers.parse_application_data('{"last_name": "O&#x27;Brien"}')
        self.assertEqual(result["last_name"], "O'Brien")

    def test_decodes_html_entities_in_dict_values(self):
        """Dict input has its string values HTML-unescaped."""
        result = helpers.parse_application_data({"last_name": "O&#x27;Brien", "age": 5})
        self.assertEqual(result["last_name"], "O'Brien")
        self.assertEqual(result["age"], 5)

    def test_none_input_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            helpers.parse_application_data(None)
        self.assertIn("No data provided", str(ctx.exception))

    def test_invalid_json_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            helpers.parse_application_data("{not valid json")
        self.assertIn("Invalid JSON", str(ctx.exception))


class TestGetMembershipTypeFeeInfo(EnhancedTestCase):
    """get_membership_type_fee_info (canonical) and its wrappers."""

    def setUp(self):
        super().setUp()
        self.mt = _make_membership_type(self.factory, amount=20.0)

    def test_returns_fee_info_with_tiers(self):
        info = helpers.get_membership_type_fee_info(self.mt.name)
        self.assertTrue(info["success"])
        self.assertEqual(info["membership_type"], self.mt.name)
        self.assertTrue(info["has_template"])
        self.assertGreater(info["amount"], 0)
        # Four suggested tiers at 1x/1.25x/1.5x/2x
        self.assertEqual(len(info["suggested_amounts"]), 4)
        self.assertTrue(info["suggested_amounts"][0]["is_default"])
        self.assertEqual(info["suggested_amounts"][0]["percentage"], 100)
        self.assertEqual(info["suggested_amounts"][3]["percentage"], 200)
        # Champion tier is 2x the base amount
        self.assertAlmostEqual(info["suggested_amounts"][3]["amount"], info["amount"] * 2.0, places=2)

    def test_nonexistent_type_returns_failure(self):
        info = helpers.get_membership_type_fee_info("Nonexistent-Type-999999")
        self.assertFalse(info["success"])
        self.assertIn("error", info)

    def test_get_membership_fee_info_wrapper(self):
        """get_membership_fee_info returns the slim subset."""
        info = helpers.get_membership_fee_info(self.mt.name)
        self.assertTrue(info["success"])
        self.assertEqual(info["membership_type"], self.mt.name)
        self.assertIn("standard_amount", info)
        self.assertIn("billing_frequency", info)
        # Wrapper does NOT leak the full tier list
        self.assertNotIn("suggested_amounts", info)

    def test_get_membership_fee_info_propagates_failure(self):
        info = helpers.get_membership_fee_info("Nonexistent-Type-999999")
        self.assertFalse(info["success"])

    def test_get_membership_type_details_legacy_tiers(self):
        """get_membership_type_details adds the legacy 1x/1.5x/2x/3x tiers."""
        info = helpers.get_membership_type_details(self.mt.name)
        self.assertTrue(info["success"])
        labels = [t["label"] for t in info["suggested_amounts"]]
        self.assertEqual(labels, ["Standard", "Supporter", "Patron", "Benefactor"])
        # details min = 50% of the canonical fee-info minimum_amount (constraint floor)
        canonical = helpers.get_membership_type_fee_info(self.mt.name)
        self.assertAlmostEqual(info["minimum_amount"], canonical["minimum_amount"] * 0.5, places=2)
        # Benefactor tier is 3x the base amount
        self.assertAlmostEqual(info["suggested_amounts"][3]["amount"], info["amount"] * 3.0, places=2)


class TestSuggestMembershipAmounts(EnhancedTestCase):
    """suggest_membership_amounts + get_amount_impact_message."""

    def setUp(self):
        super().setUp()
        self.mt = _make_membership_type(self.factory, amount=30.0)

    def test_suggestions_use_suggested_amount_base(self):
        result = helpers.suggest_membership_amounts(self.mt.name)
        self.assertTrue(result["success"])
        self.assertGreater(result["base_amount"], 0)
        self.assertEqual(len(result["suggestions"]), 4)
        # Each suggestion carries an impact message
        for s in result["suggestions"]:
            self.assertIn("impact_message", s)
            self.assertIn("formatted_amount", s)

    def test_nonexistent_type_returns_failure(self):
        result = helpers.suggest_membership_amounts("Nonexistent-Type-999999")
        self.assertFalse(result["success"])
        # When the underlying fee-info lookup fails, its failure dict is returned
        # verbatim (no 'suggestions' key); the error is surfaced instead.
        self.assertIn("error", result)

    def test_amount_impact_message_above_standard(self):
        msg = helpers.get_amount_impact_message(50, 25, 200)
        self.assertIn("100%", msg)

    def test_amount_impact_message_below_standard(self):
        msg = helpers.get_amount_impact_message(10, 25, 40)
        self.assertIn("Reduced rate", msg)
        self.assertIn("60%", msg)

    def test_amount_impact_message_standard(self):
        msg = helpers.get_amount_impact_message(25, 25, 100)
        self.assertEqual(msg, "Standard membership fee.")


class TestCreateMemberFromApplication(EnhancedTestCase):
    """create_member_from_application — the core member-creation helper."""

    def setUp(self):
        super().setUp()
        self.mt = _make_membership_type(self.factory, amount=15.0)
        helpers.ensure_payment_modes_exist()

    def _build_application(self, **overrides):
        app_id = helpers.generate_application_id()
        data = {
            "first_name": "Jan",
            "last_name": f"Applicant{frappe.generate_hash()[:8]}",
            "email": f"applicant.{frappe.generate_hash()[:8]}@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-01-01",
            "selected_membership_type": self.mt.name,
            "payment_method": "bank_transfer",
            "interested_in_volunteering": 0,
        }
        data.update(overrides)
        return data, app_id

    def test_creates_member_with_application_fields(self):
        data, app_id = self._build_application()
        member = helpers.create_member_from_application(data, app_id)
        self.track_doc("Member", member.name)

        self.assertEqual(member.application_id, app_id)
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.selected_membership_type, self.mt.name)
        self.assertEqual(member.payment_method, "Bank Transfer")
        # Owner is the system user, NOT the applicant's email
        self.assertNotEqual(member.owner, data["email"])
        self.assertEqual(member.first_name, "Jan")

    def test_custom_contribution_fee_applied(self):
        """custom_contribution_fee populates dues_rate + override fields."""
        data, app_id = self._build_application(
            custom_contribution_fee="42.50",
            uses_custom_amount=1,
            custom_amount_reason="I want to support more",
        )
        member = helpers.create_member_from_application(data, app_id)
        self.track_doc("Member", member.name)

        self.assertEqual(float(member.dues_rate), 42.50)
        self.assertEqual(float(member.application_custom_fee), 42.50)
        self.assertIn("support more", member.fee_override_reason)
        self.assertTrue(member.fee_override_date)
        self.assertTrue(member.fee_override_by)

    def test_opt_out_inverts_to_accepts_optional(self):
        """opt_out_optional_emails=True sets accepts_optional_communications=0."""
        data, app_id = self._build_application(opt_out_optional_emails=True)
        member = helpers.create_member_from_application(data, app_id)
        self.track_doc("Member", member.name)
        self.assertEqual(member.accepts_optional_communications, 0)

    def test_bank_details_persisted(self):
        iban = self.factory.create_test_iban()
        data, app_id = self._build_application(iban=iban, bic="INGBNL2A", bank_account_name="Jan Applicant")
        member = helpers.create_member_from_application(data, app_id)
        self.track_doc("Member", member.name)
        # IBAN is normalized (spaces) by the Member controller; compare digits.
        self.assertEqual(member.iban.replace(" ", ""), iban.replace(" ", ""))
        self.assertEqual(member.bank_account_name, "Jan Applicant")


class TestReapplicationUpdate(EnhancedTestCase):
    """update_member_from_reapplication."""

    def setUp(self):
        super().setUp()
        self.mt = _make_membership_type(self.factory, amount=15.0)
        helpers.ensure_payment_modes_exist()
        self.member = self.create_test_member(first_name="Old", last_name="Name", email="reapply@example.com")

    def test_updates_existing_member_to_pending(self):
        new_app_id = helpers.generate_application_id()
        data = {
            "first_name": "New",
            "last_name": "Surname",
            "email": self.member.email,
            "selected_membership_type": self.mt.name,
            "payment_method": "bank_transfer",
            "birth_date": "1985-05-05",
        }
        updated = helpers.update_member_from_reapplication(self.member.name, data, new_app_id)

        self.assertEqual(updated.first_name, "New")
        self.assertEqual(updated.last_name, "Surname")
        self.assertEqual(updated.application_status, "Pending")
        self.assertEqual(updated.status, "Pending")
        self.assertEqual(updated.application_id, new_app_id)
        self.assertIn("Reapplication submitted", updated.notes or "")


class TestChapterMembershipLifecycle(EnhancedTestCase):
    """create_pending / activate / remove chapter membership helpers."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(region="Noord-Holland", published=1)
        self.member = self.create_test_member(first_name="Chap", last_name="Member", email="chap@example.com")

    def _pending_status(self):
        rows = frappe.get_all(
            "Chapter Member",
            filters={"member": self.member.name, "parent": self.chapter.name},
            fields=["status"],
        )
        return rows[0].status if rows else None

    def test_create_pending_then_activate(self):
        """Pending chapter membership is created then promoted to Active."""
        row = helpers.create_pending_chapter_membership(self.member, self.chapter.name)
        self.assertIsNotNone(row)
        self.assertEqual(self._pending_status(), "Pending")

        helpers.activate_pending_chapter_membership(self.member, self.chapter.name)
        self.assertEqual(self._pending_status(), "Active")

    def test_activate_with_no_pending_creates_active(self):
        """Activating with no pending record falls back to creating an active one."""
        helpers.activate_pending_chapter_membership(self.member, self.chapter.name)
        self.assertEqual(self._pending_status(), "Active")

    def test_remove_pending_membership(self):
        """Rejection path removes the pending chapter membership."""
        helpers.create_pending_chapter_membership(self.member, self.chapter.name)
        self.assertEqual(self._pending_status(), "Pending")

        result = helpers.remove_pending_chapter_membership(self.member, self.chapter.name)
        self.assertTrue(result)
        self.assertIsNone(self._pending_status())

    def test_remove_all_pending(self):
        """remove_all_pending_chapter_memberships returns removed chapter names."""
        helpers.create_pending_chapter_membership(self.member, self.chapter.name)
        removed = helpers.remove_all_pending_chapter_memberships(self.member)
        self.assertIn(self.chapter.name, removed)
        self.assertIsNone(self._pending_status())

    def test_create_pending_nonexistent_chapter_returns_none(self):
        result = helpers.create_pending_chapter_membership(self.member, "No-Such-Chapter-XYZ")
        self.assertIsNone(result)

    def test_create_pending_with_no_args_returns_none(self):
        self.assertIsNone(helpers.create_pending_chapter_membership(None, None))


class TestCreateVolunteerRecord(EnhancedTestCase):
    """create_volunteer_record."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Volun", last_name="Teer", email="vol@example.com")

    def test_not_interested_returns_none(self):
        self.member.interested_in_volunteering = 0
        self.assertIsNone(helpers.create_volunteer_record(self.member))

    def test_interested_creates_volunteer(self):
        self.member.interested_in_volunteering = 1
        self.member.save()
        volunteer = helpers.create_volunteer_record(self.member)
        self.assertIsNotNone(volunteer)
        self.track_doc("Volunteer", volunteer.name)
        self.assertEqual(volunteer.member, self.member.name)
        self.assertEqual(volunteer.status, "New")


class TestDraftAndStatus(EnhancedTestCase):
    """save_draft_application / load_draft_application / check_application_status."""

    def test_draft_round_trip(self):
        data = {"first_name": "Draft", "email": "draft@example.com"}
        saved = helpers.save_draft_application(data)
        self.assertTrue(saved["success"])
        draft_id = saved["draft_id"]

        loaded = helpers.load_draft_application(draft_id)
        self.assertTrue(loaded["success"])
        self.assertEqual(loaded["data"]["first_name"], "Draft")

    def test_load_missing_draft(self):
        loaded = helpers.load_draft_application("DRAFT-does-not-exist")
        self.assertFalse(loaded["success"])

    def test_check_status_returns_pii_safe_subset(self):
        mt = _make_membership_type(self.factory, amount=15.0)
        helpers.ensure_payment_modes_exist()
        app_id = helpers.generate_application_id()
        data = {
            "first_name": "Status",
            "last_name": f"Check{frappe.generate_hash()[:8]}",
            "email": f"status.{frappe.generate_hash()[:8]}@example.com",
            "selected_membership_type": mt.name,
            "payment_method": "bank_transfer",
            "birth_date": "1990-01-01",
        }
        member = helpers.create_member_from_application(data, app_id)
        self.track_doc("Member", member.name)

        result = helpers.check_application_status(app_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Pending")
        self.assertEqual(result["application_id"], app_id)
        # PII-safe: no name/email/member docname leaked
        self.assertNotIn("email", result)
        self.assertNotIn("full_name", result)
        self.assertNotIn("member", result)

    def test_check_status_not_found(self):
        result = helpers.check_application_status("APP-99999999-9999")
        self.assertFalse(result["success"])
