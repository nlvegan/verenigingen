"""
Coverage-extension tests for the personal-details portal page
(verenigingen.templates.pages.personal_details).

The portal cluster test already covers get_context, a few validators,
track_changes(diff), the happy-path name update, the tampering reject and the
missing-first-name reject. This module fills the REMAINING uncovered surface:

- the PURE validators exhaustively (valid + invalid inputs):
  validate_name_format(+prefixes), validate_phone_number, validate_pronouns
- get_field_label (known + fallback)
- prepare_success_message (each change category)
- track_changes (None/empty-string equivalence, no-diff, multi-field)
- log_personal_details_changes / apply_personal_details_changes via the
  whitelist endpoint hitting pronoun + preference + birth_date branches
- update_personal_details validation throws: invalid name chars, invalid phone,
  invalid future birth date, custom-pronouns-without-value, no-member-record.

Image upload (handle_image_update) is exercised only on the "no upload" path
through track_changes; the actual file-upload branch needs frappe.local.
uploaded_file populated by the request layer and is OUT OF SCOPE for a unit
test (we do not simulate the HTTP file-upload pipeline).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePersonalDetailsValidators(EnhancedTestCase):
    """Pure validator + label/message unit tests (no fixtures needed)."""

    def test_validate_name_format_valid(self):
        from verenigingen.templates.pages.personal_details import validate_name_format

        for name in ["Jan", "Anne-Marie", "O'Brien", "José", "Renée", "van der Berg"]:
            self.assertTrue(validate_name_format(name), name)

    def test_validate_name_format_invalid(self):
        from verenigingen.templates.pages.personal_details import validate_name_format

        for name in ["Jan123", "John@Doe", "x_y", "name!", ""]:
            self.assertFalse(validate_name_format(name), name)

    def test_validate_name_format_prefixes_allow_dot(self):
        from verenigingen.templates.pages.personal_details import validate_name_format

        # A dot is only allowed when allow_prefixes=True (e.g. "St." / "v.").
        self.assertTrue(validate_name_format("v.", allow_prefixes=True))
        self.assertFalse(validate_name_format("v.", allow_prefixes=False))

    def test_validate_phone_number_valid(self):
        from verenigingen.templates.pages.personal_details import validate_phone_number

        for phone in ["+31 6 12345678", "0031612345678", "06-12345678", "(020) 1234567"]:
            self.assertTrue(validate_phone_number(phone), phone)

    def test_validate_phone_number_invalid(self):
        from verenigingen.templates.pages.personal_details import validate_phone_number

        for phone in ["abc", "12", "phone-number-here", ""]:
            self.assertFalse(validate_phone_number(phone), phone)

    def test_validate_pronouns_valid(self):
        from verenigingen.templates.pages.personal_details import validate_pronouns

        for p in ["she/her", "they/them", "he/him", "zij/haar", "she, her"]:
            self.assertTrue(validate_pronouns(p), p)

    def test_validate_pronouns_invalid(self):
        from verenigingen.templates.pages.personal_details import validate_pronouns

        for p in ["she@her", "they+them", "1/2", ""]:
            self.assertFalse(validate_pronouns(p), p)

    def test_get_field_label_known_and_fallback(self):
        from verenigingen.templates.pages.personal_details import get_field_label

        self.assertEqual(get_field_label("first_name"), "First Name")
        self.assertEqual(get_field_label("tussenvoegsel"), "Tussenvoegsel")
        self.assertEqual(get_field_label("allow_photo_usage"), "Photo Usage Permission")
        # Unknown field -> slug-to-title fallback.
        self.assertEqual(get_field_label("some_other_field"), "Some Other Field")

    def test_prepare_success_message_categories(self):
        from verenigingen.templates.pages.personal_details import prepare_success_message

        changes = {
            "first_name": {"old": "A", "new": "B"},
            "contact_number": {"old": "1", "new": "2"},
            "pronouns": {"old": "", "new": "she/her"},
            "birth_date": {"old": "1990-01-01", "new": "1991-01-01"},
            "image": {"old": None, "new": "/files/x.png", "action": "upload"},
        }
        messages = prepare_success_message(changes)
        joined = " ".join(messages)
        self.assertIn("name information", joined)
        self.assertIn("contact information", joined)
        self.assertIn("preferences", joined)
        self.assertIn("birth date", joined)
        self.assertIn("profile image", joined)

    def test_prepare_success_message_image_removed(self):
        from verenigingen.templates.pages.personal_details import prepare_success_message

        changes = {"image": {"old": "/files/x.png", "new": None, "action": "remove"}}
        messages = prepare_success_message(changes)
        self.assertTrue(any("removed" in m for m in messages))

    def test_prepare_success_message_empty(self):
        from verenigingen.templates.pages.personal_details import prepare_success_message

        self.assertEqual(prepare_success_message({}), [])


class TestPagePersonalDetailsBehavior(EnhancedTestCase):
    """Endpoint + track_changes + permission tests with real fixtures."""

    def setUp(self):
        super().setUp()
        # update_personal_details is a @self_service_api (HIGH security) endpoint
        # gated to the DEVELOPMENT environment via frappe.conf.developer_mode; a
        # sibling shard test can leave the (shared, non-transactional) flag off,
        # making the endpoint raise a production-environment PermissionError.
        # Force it on, restore in tearDown.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        self.email = f"pdcov-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Pers",
            last_name="Vandenberg",  # clean alpha; the validator rejects digit suffixes
            email=self.email,
            birth_date="1990-01-01",
        )
        self.email = self.member.email
        self.user = self._ensure_user(self.email)
        self.member.db_set("user", self.user)
        # The factory uniquifies last_name with a digit suffix
        # ("Vandenberg<digits>"); update_personal_details' validate_name_format
        # rejects digits, so force clean alpha names that the "unchanged" happy
        # paths can echo back without tripping validation.
        self.member.db_set("first_name", "Pers")
        self.member.db_set("last_name", "Vandenberg")
        self.member.reload()
        # A portal member editing themselves is already onboarded; align the
        # workflow state so the self-save is a no-op transition (see cluster test).
        self.member.db_set("application_status", "Active")

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def _ensure_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Pers",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _make_user_without_member(self):
        """Create a Verenigingen Member User that has no linked Member record."""
        nomember = f"pdcov-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": nomember,
                "first_name": "NoMember",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        ).insert(ignore_permissions=True)
        return nomember

    # ----- track_changes edge cases ------------------------------------

    def test_track_changes_none_vs_empty_string_is_no_diff(self):
        from verenigingen.templates.pages.personal_details import track_changes

        # middle_name is None on the member; submitting "" should NOT be a change.
        self.member.middle_name = None
        changes = track_changes(self.member, {"middle_name": ""})
        self.assertNotIn("middle_name", changes)

    def test_track_changes_multi_field(self):
        from verenigingen.templates.pages.personal_details import track_changes

        changes = track_changes(
            self.member,
            {"first_name": "Changed", "last_name": self.member.last_name, "pronouns": "she/her"},
        )
        self.assertIn("first_name", changes)
        self.assertIn("pronouns", changes)
        self.assertNotIn("last_name", changes)
        self.assertEqual(changes["first_name"]["new"], "Changed")

    # ----- update_personal_details validation throws -------------------

    def test_update_rejects_invalid_first_name_chars(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict({"first_name": "Jan123", "last_name": "Vandenberg"})
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_rejects_last_name_required(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict({"first_name": "Jan", "last_name": ""})
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_rejects_invalid_phone(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {"first_name": "Jan", "last_name": "Vandenberg", "contact_number": "abc"}
            )
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_rejects_future_birth_date(self):
        from frappe.utils import add_years, today

        from verenigingen.templates.pages.personal_details import update_personal_details

        future = add_years(today(), 1)
        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {"first_name": "Jan", "last_name": "Vandenberg", "birth_date": future}
            )
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_rejects_custom_pronouns_without_value(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {
                    "first_name": "Jan",
                    "last_name": "Vandenberg",
                    "pronouns": "custom",
                    "custom_pronouns": "",
                }
            )
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_no_member_record_throws(self):
        from verenigingen.templates.pages.personal_details import update_personal_details
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        nomember = self._make_user_without_member()

        with self.as_user(nomember):
            frappe.local.form_dict = frappe._dict({"first_name": "Jan", "last_name": "Vandenberg"})
            try:
                # update_personal_details is @self_service_api: the framework's
                # implicit self-service resolver rejects a user with no linked member
                # ("Self-service operations require valid member account") before the
                # body's own DoesNotExistError can fire.
                with self.assertRaises(VPermissionError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    # ----- happy path through apply + log + success-message ------------

    def test_update_applies_pronoun_and_preference_changes(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {
                    "first_name": self.member.first_name,
                    "last_name": self.member.last_name,
                    "pronouns": "they/them",
                    # allow_directory_listing / allow_photo_usage are real Check
                    # fields on Member; the controller tracks and persists them.
                    "allow_directory_listing": "1",
                    "allow_photo_usage": "1",
                }
            )
            try:
                with self.assertNoErrorLog():
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        self.member.reload()
        self.assertEqual(self.member.pronouns, "they/them")
        # The two consent preferences now persist (previously dead/no-op fields).
        self.assertEqual(self.member.allow_directory_listing, 1)
        self.assertEqual(self.member.allow_photo_usage, 1)
        # apply_personal_details_changes stores a success message in the session.
        self.assertTrue(frappe.session.get("personal_details_success"))
        self.assertEqual(frappe.local.response.get("type"), "redirect")

    def test_update_custom_pronouns_uses_custom_value(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {
                    "first_name": self.member.first_name,
                    "last_name": self.member.last_name,
                    "pronouns": "custom",
                    "custom_pronouns": "ze/zir",
                }
            )
            try:
                with self.assertNoErrorLog():
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        self.member.reload()
        self.assertEqual(self.member.pronouns, "ze/zir")

    def test_update_no_changes_sets_redirect(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {"first_name": self.member.first_name, "last_name": self.member.last_name}
            )
            try:
                update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        # No changes -> still a redirect, but no success message stored.
        self.assertEqual(frappe.local.response.get("type"), "redirect")
