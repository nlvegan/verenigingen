# -*- coding: utf-8 -*-
"""
Coverage tests for services/member/approval/application_helpers.py

Targets the pure / lightly-DB-backed helpers not already covered by
test_application_helpers_reapplication.py:
    - map_payment_method / get_missing_payment_modes / validate_payment_method_exists
    - parse_application_data (string, dict, HTML-entity, error branches)
    - determine_chapter_from_application
    - get_amount_impact_message
    - fee info trio (get_membership_type_fee_info + wrappers) + suggest_membership_amounts
    - save/load_draft_application, get_member_field_info, check_application_status
    - create_pending / remove_pending chapter membership lifecycle
"""

import json

import frappe

from verenigingen.services.member.approval import application_helpers as ah
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMapPaymentMethod(VereningingenTestCase):
    """map_payment_method() mapping + validation."""

    def test_form_value_mapped_to_display(self):
        self.assertEqual(ah.map_payment_method("bank_transfer", validate=False), "Bank Transfer")
        self.assertEqual(ah.map_payment_method("sepa_direct_debit", validate=False), "SEPA Direct Debit")
        self.assertEqual(ah.map_payment_method("mollie", validate=False), "Mollie")

    def test_display_value_passthrough(self):
        self.assertEqual(ah.map_payment_method("SEPA Direct Debit", validate=False), "SEPA Direct Debit")

    def test_unknown_defaults_to_bank_transfer(self):
        self.assertEqual(ah.map_payment_method("does_not_exist", validate=False), "Bank Transfer")
        self.assertEqual(ah.map_payment_method("", validate=False), "Bank Transfer")

    def test_validate_existing_mode_returns_value(self):
        """When the mapped Mode of Payment exists, validate=True returns it."""
        ah.ensure_payment_modes_exist()
        self.assertEqual(ah.map_payment_method("bank_transfer", validate=True), "Bank Transfer")

    def test_missing_modes_helper(self):
        """get_missing_payment_modes returns names not present in the DB."""
        ah.ensure_payment_modes_exist()
        # After ensure, none of the three required modes should be missing.
        self.assertEqual(ah.get_missing_payment_modes(), [])

    def test_validate_payment_method_exists(self):
        ah.ensure_payment_modes_exist()
        self.assertTrue(ah.validate_payment_method_exists("Bank Transfer"))
        self.assertFalse(ah.validate_payment_method_exists("Totally Made Up Mode XYZ"))


class TestParseApplicationData(VereningingenTestCase):
    """parse_application_data() branches."""

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            ah.parse_application_data(None)

    def test_dict_passthrough_with_entity_decode(self):
        """A dict input has HTML entities in string values decoded."""
        result = ah.parse_application_data({"last_name": "O&#x27;Brien", "age": 5})
        self.assertEqual(result["last_name"], "O'Brien")
        self.assertEqual(result["age"], 5)

    def test_json_string_parsed(self):
        result = ah.parse_application_data('{"first_name": "Jan", "city": "Utrecht"}')
        self.assertEqual(result["first_name"], "Jan")
        self.assertEqual(result["city"], "Utrecht")

    def test_html_escaped_json_string_decoded(self):
        """An HTML-entity-encoded apostrophe inside the JSON string is unescaped."""
        result = ah.parse_application_data('{"last_name": "O&#x27;Brien"}')
        self.assertEqual(result["last_name"], "O'Brien")

    def test_invalid_json_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ah.parse_application_data("{not valid json")


class TestDetermineChapterFromApplication(VereningingenTestCase):
    """determine_chapter_from_application() selection logic."""

    def test_explicit_selected_chapter_wins(self):
        self.assertEqual(
            ah.determine_chapter_from_application({"selected_chapter": "Some Chapter"}),
            "Some Chapter",
        )

    def test_no_chapter_no_postal_returns_none(self):
        self.assertIsNone(ah.determine_chapter_from_application({"first_name": "x"}))


class TestAmountImpactMessage(VereningingenTestCase):
    """get_amount_impact_message() three branches."""

    def test_above_standard(self):
        msg = ah.get_amount_impact_message(150, 100, 150)
        self.assertIn("50%", msg)
        self.assertIn("additional programs", msg)

    def test_below_standard(self):
        msg = ah.get_amount_impact_message(75, 100, 75)
        self.assertIn("25%", msg)
        self.assertIn("discount", msg)

    def test_exactly_standard(self):
        self.assertEqual(ah.get_amount_impact_message(100, 100, 100), "Standard membership fee.")


class TestFeeInfoTrio(VereningingenTestCase):
    """get_membership_type_fee_info() + thin wrappers + suggest_membership_amounts()."""

    def setUp(self):
        super().setUp()
        # Auto-created template has dues_rate 15.0 → amount resolves > 0.
        self.mt = self.create_test_membership_type(minimum_amount=15.0)

    def test_fee_info_success_shape(self):
        info = ah.get_membership_type_fee_info(self.mt.name)
        self.assertTrue(info["success"])
        self.assertEqual(info["membership_type"], self.mt.name)
        self.assertGreater(info["amount"], 0)
        # Currency resolves from the company default; just require a real code.
        self.assertTrue(info["currency"])
        # Suggested tiers: Standard tier is_default at 100%.
        standard = [t for t in info["suggested_amounts"] if t["is_default"]]
        self.assertEqual(len(standard), 1)
        self.assertEqual(standard[0]["percentage"], 100)
        # maximum is 5x amount.
        self.assertAlmostEqual(info["maximum_amount"], info["amount"] * 5, places=4)

    def test_fee_info_nonexistent_type_failure(self):
        info = ah.get_membership_type_fee_info("No Such Type XYZ")
        self.assertFalse(info["success"])
        self.assertIn("error", info)

    def test_get_membership_fee_info_wrapper(self):
        info = ah.get_membership_fee_info(self.mt.name)
        self.assertTrue(info["success"])
        self.assertIn("standard_amount", info)
        self.assertEqual(info["membership_type"], self.mt.name)

    def test_get_membership_fee_info_propagates_failure(self):
        info = ah.get_membership_fee_info("No Such Type XYZ")
        self.assertFalse(info["success"])

    def test_get_membership_type_details_legacy_tiers(self):
        details = ah.get_membership_type_details(self.mt.name)
        self.assertTrue(details["success"])
        labels = [t["label"] for t in details["suggested_amounts"]]
        self.assertEqual(labels, ["Standard", "Supporter", "Patron", "Benefactor"])
        # minimum is 50% of the constraint floor.
        self.assertAlmostEqual(details["minimum_amount"], 15.0 * 0.5, places=4)

    def test_suggest_membership_amounts_success(self):
        result = ah.suggest_membership_amounts(self.mt.name)
        self.assertTrue(result["success"])
        self.assertGreater(result["base_amount"], 0)
        self.assertEqual(len(result["suggestions"]), 4)
        # Each suggestion carries an impact message.
        self.assertTrue(all("impact_message" in s for s in result["suggestions"]))


class TestMembershipTypeCurrency(VereningingenTestCase):
    """_get_membership_type_currency() resolution."""

    def test_explicit_currency_field_used(self):
        mt = self.create_test_membership_type()
        mt.currency = "USD"  # set transient attribute
        self.assertEqual(ah._get_membership_type_currency(mt), "USD")


class TestDraftApplication(VereningingenTestCase):
    """save_draft_application() / load_draft_application() round-trip via cache."""

    def test_save_and_load_roundtrip(self):
        data = {"first_name": "Draft", "email": "draft@example.com"}
        saved = ah.save_draft_application(data)
        self.assertTrue(saved["success"])
        draft_id = saved["draft_id"]

        loaded = ah.load_draft_application(draft_id)
        self.assertTrue(loaded["success"])
        self.assertEqual(loaded["data"]["first_name"], "Draft")

    def test_load_missing_draft(self):
        loaded = ah.load_draft_application("DRAFT-DOES-NOT-EXIST-0")
        self.assertFalse(loaded["success"])
        self.assertIn("not found", loaded["message"].lower())


class TestMemberFieldInfo(VereningingenTestCase):
    """get_member_field_info() returns metadata for the core fields."""

    def test_returns_known_fields(self):
        result = ah.get_member_field_info()
        self.assertTrue(result["success"])
        for field in ("first_name", "last_name", "email"):
            self.assertIn(field, result["fields"])
            self.assertIn("fieldtype", result["fields"][field])


class TestCheckApplicationStatus(VereningingenTestCase):
    """check_application_status() PII-safe status lookup."""

    def test_unknown_application_id(self):
        result = ah.check_application_status("APP-DOES-NOT-EXIST-9999")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"].lower())

    def test_known_application_id_returns_status_only(self):
        member = self.create_test_member()
        app_id = f"APP-STATUS-{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", member.name, {"application_id": app_id, "application_status": "Pending"}
        )

        result = ah.check_application_status(app_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Pending")
        self.assertEqual(result["application_id"], app_id)
        # PII must NOT leak through the enumerable endpoint.
        self.assertNotIn("email", result)
        self.assertNotIn("full_name", result)
        self.assertNotIn("name", result)


class TestPendingChapterMembershipLifecycle(VereningingenTestCase):
    """create_pending → remove_pending / remove_all_pending lifecycle.

    Guard inputs (no member / no chapter) and the full create+remove path on a
    real Chapter.
    """

    def test_create_pending_no_member_or_chapter_returns_none(self):
        self.assertIsNone(ah.create_pending_chapter_membership(None, "X"))
        member = self.create_test_member()
        self.assertIsNone(ah.create_pending_chapter_membership(member, None))

    def test_create_pending_nonexistent_chapter_returns_none(self):
        member = self.create_test_member()
        self.expectErrorLog("Chapter Not Found")
        self.assertIsNone(
            ah.create_pending_chapter_membership(member, "Nonexistent Chapter XYZ")
        )

    def test_remove_all_pending_no_pending_returns_empty(self):
        """A member with no pending chapter rows yields an empty removal list."""
        member = self.create_test_member()
        self.assertEqual(ah.remove_all_pending_chapter_memberships(member), [])

    def test_remove_pending_none_member_returns_false(self):
        self.assertFalse(ah.remove_pending_chapter_membership(None))

    def test_create_then_remove_pending_on_real_chapter(self):
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            self.skipTest("No Chapter exists in this environment")
        chapter_name = chapters[0]["name"]
        member = self.create_test_member()

        created = ah.create_pending_chapter_membership(member, chapter_name)
        if created is None:
            self.skipTest("Chapter membership creation unavailable in this environment")

        # A pending row should now exist for this member in the chapter.
        self.assertTrue(
            frappe.db.exists(
                "Chapter Member",
                {"parent": chapter_name, "member": member.name, "status": "Pending"},
            )
        )

        # remove_all should find and remove it.
        removed = ah.remove_all_pending_chapter_memberships(member)
        self.assertIn(chapter_name, removed)
        self.assertFalse(
            frappe.db.exists(
                "Chapter Member",
                {"parent": chapter_name, "member": member.name, "status": "Pending"},
            )
        )
