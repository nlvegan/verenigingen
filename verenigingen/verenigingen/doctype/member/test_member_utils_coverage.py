"""
Real-DB coverage for the Member *doctype-level* utils
(``verenigingen/verenigingen/doctype/member/member_utils.py``).

NOTE: this is the doctype module ``...doctype.member.member_utils`` — distinct
from ``verenigingen.utils.member_utils`` (covered by
``tests/member/test_member_utils_coverage.py``). This file exercises the
whitelisted helper endpoints defined here:

- settings/config helpers: get_member_settings, get_iban_bank_codes,
  is_chapter_management_enabled, get_member_form_settings
- SEPA helpers: check_sepa_mandate_status, check_mandate_iban_mismatch,
  need_new_mandate, validate_mandate_reference, generate_mandate_reference,
  check_and_handle_sepa_mandate, create_sepa_mandate_from_bank_details
- donation/termination lookups: get_linked_donations, get_member_termination_status
- chapter/postal helpers: find_chapter_by_postal_code, debug_postal_code_matching
- derive_bic_from_iban

Real Member/SEPA Mandate/Chapter/Donor records via the factory; run as
Administrator. No business logic is mocked.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import member_utils as mu


class TestMemberUtilsDoctypeCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="MUDoctype",
            last_name="Cov",
            email=f"mudoctype.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------ settings/config

    def test_get_member_settings_returns_defaults_shape(self):
        settings = mu.get_member_settings()
        self.assertIn("mandate_expiry_warning_days", settings)
        self.assertIn("default_mandate_type", settings)

    def test_get_iban_bank_codes_known_countries(self):
        codes = mu.get_iban_bank_codes()
        self.assertIn("NL", codes)
        self.assertEqual(codes["NL"], (4, 4))

    def test_is_chapter_management_enabled_returns_bool(self):
        self.assertIsInstance(mu.is_chapter_management_enabled(), bool)

    def test_get_member_form_settings_shape(self):
        settings = mu.get_member_form_settings()
        self.assertIn("show_chapter_field", settings)
        self.assertIn("chapter_field_label", settings)

    # ------------------------------------------------------------ SEPA: no-mandate paths

    def test_check_sepa_mandate_status_no_mandate(self):
        result = mu.check_sepa_mandate_status(self.member.name)
        self.assertFalse(result["has_active_mandate"])
        self.assertFalse(result["expiring_soon"])

    def test_check_mandate_iban_mismatch_missing_params(self):
        result = mu.check_mandate_iban_mismatch(self.member.name, "")
        self.assertFalse(result["show_popup"])
        self.assertIn("error", result)

    def test_check_mandate_iban_mismatch_first_time_setup(self):
        # No existing mandates -> first-time-setup popup.
        result = mu.check_mandate_iban_mismatch(self.member.name, "NL13TEST0123456789")
        self.assertTrue(result["show_popup"])
        self.assertEqual(result["scenario"], "first_time_setup")

    def test_need_new_mandate_true_when_no_match(self):
        result = mu.need_new_mandate(self.member.name, "NL13TEST0123456789")
        self.assertTrue(result["need_new"])

    def test_validate_mandate_reference_available_for_unused(self):
        result = mu.validate_mandate_reference(f"M-UNUSED-{frappe.generate_hash(length=8)}")
        self.assertTrue(result["available"])
        self.assertFalse(result["exists"])

    def test_generate_mandate_reference_shape(self):
        result = mu.generate_mandate_reference(self.member.name)
        self.assertIn("mandate_reference", result)
        self.assertTrue(result["mandate_reference"].startswith("M-"))

    def test_check_and_handle_sepa_mandate_create_new_when_none(self):
        result = mu.check_and_handle_sepa_mandate(self.member.name, "NL13TEST0123456789")
        self.assertEqual(result["action"], "create_new")

    # ------------------------------------------------------------ SEPA create + reuse

    def test_create_sepa_mandate_from_bank_details_creates_and_links(self):
        iban = "NL13 TEST 0123 4567 89"
        name = mu.create_sepa_mandate_from_bank_details(
            member=self.member.name,
            iban=iban,
            account_holder_name="MUDoctype Cov",
        )
        self.assertTrue(frappe.db.exists("SEPA Mandate", name))
        self.track_doc("SEPA Mandate", name)

        # Now an active mandate exists; status check reflects it.
        status = mu.check_sepa_mandate_status(self.member.name)
        self.assertTrue(status["has_active_mandate"])

        # need_new_mandate must now be False for the same (normalized) IBAN.
        self.assertFalse(mu.need_new_mandate(self.member.name, "NL13TEST0123456789")["need_new"])

        # check_and_handle for the same IBAN -> reuse existing / none-needed (not create_new).
        result = mu.check_and_handle_sepa_mandate(self.member.name, "NL13TEST0123456789")
        self.assertIn(result["action"], ("use_existing", "none_needed"))

    def test_create_sepa_mandate_requires_member_and_iban(self):
        with self.assertRaises(frappe.ValidationError):
            mu.create_sepa_mandate_from_bank_details(member="", iban="")

    def test_check_mandate_iban_mismatch_detects_mismatch(self):
        # Create a mandate with one IBAN, then check against a different IBAN.
        existing = mu.create_sepa_mandate_from_bank_details(
            member=self.member.name, iban="NL13 TEST 0123 4567 89"
        )
        self.track_doc("SEPA Mandate", existing)
        result = mu.check_mandate_iban_mismatch(self.member.name, "NL02ABNA0123456789")
        self.assertTrue(result["show_popup"])
        self.assertEqual(result["reason"], "iban_mismatch")

    # ------------------------------------------------------------ donations / termination

    def test_get_linked_donations_none(self):
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])

    def test_get_linked_donations_by_email(self):
        donor = self.create_test_donor(donor_email=self.member.email)
        result = mu.get_linked_donations(self.member.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["donor"], donor.name)

    def test_get_linked_donations_empty_member(self):
        result = mu.get_linked_donations("")
        self.assertFalse(result["success"])

    def test_get_member_termination_status_none(self):
        result = mu.get_member_termination_status(self.member.name)
        self.assertEqual(result["pending_requests"], [])
        self.assertFalse(result["is_terminated"])

    # ------------------------------------------------------------ chapter / postal

    def test_find_chapter_by_postal_code_no_code(self):
        result = mu.find_chapter_by_postal_code("")
        self.assertFalse(result["success"])

    def test_find_chapter_by_postal_code_matches(self):
        chapter = self.create_test_chapter(
            chapter_name=f"MUPostal {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        result = mu.find_chapter_by_postal_code("1234")
        self.assertTrue(result["success"])
        names = {c["name"] for c in result["matching_chapters"]}
        self.assertIn(chapter.name, names)

    def test_debug_postal_code_matching_no_code(self):
        result = mu.debug_postal_code_matching("")
        self.assertIn("error", result)

    def test_debug_postal_code_matching_returns_buckets(self):
        self.create_test_chapter(
            chapter_name=f"MUDebug {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        result = mu.debug_postal_code_matching("1234")
        self.assertEqual(result["postal_code"], "1234")
        self.assertIn("matching_chapters", result)
        self.assertIn("non_matching_chapters", result)
        self.assertGreaterEqual(result["total_chapters"], 1)

    # ------------------------------------------------------------ derive_bic

    def test_derive_bic_from_iban(self):
        # Dutch IBAN with bank code ABNA derives the ABN AMRO BIC. Assert the
        # exact value (a wrong BIC or an echoed IBAN must fail, not just non-None).
        result = mu.derive_bic_from_iban("NL02ABNA0123456789")
        self.assertEqual(result, "ABNANL2A")
