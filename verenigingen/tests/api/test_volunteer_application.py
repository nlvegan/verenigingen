"""
Tests for verenigingen/api/volunteer_application.py

Target: submit_volunteer_application(**data) — a GUEST-FACING (allow_guest=True)
intake endpoint that accepts untrusted public input and creates a Volunteer
record (plus, optionally, a membership application).

These tests are written to catch REAL regressions in:
  - required-field validation
  - age gating (>= 16)
  - duplicate-application detection (per status)
  - the guest permission boundary (a guest CAN submit, and guest input cannot
    set protected fields such as `status` or `user`)
  - that the public form actually persists what was submitted
  - that the "also become a member" branch works end-to-end

Whitelisted functions in the target module:
  - submit_volunteer_application  -> allow_guest=True  (the only public entry point)
  All other functions in the module are private helpers (no @frappe.whitelist).
"""

import frappe

from verenigingen.api.volunteer_application import (
    _build_volunteer_notes,
    _map_time_commitment,
    submit_volunteer_application,
)
from verenigingen.tests.support.verenigingen_settings import pinned_setting
from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerApplication(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Each test mints a unique email so the duplicate-detection logic only
        # sees what the individual test deliberately seeds.
        self._uniq = frappe.generate_hash(length=8).lower()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _valid_payload(self, **overrides):
        """Build a minimally-valid application payload (all required fields)."""
        data = {
            "first_name": "Ria",
            "last_name": "Vermeer",
            "email": f"ria.{self._uniq}@example.com",
            "birth_date": "1990-05-01",
            "motivation": "I care about animals and want to help.",
            "time_commitment": "6-10",
        }
        data.update(overrides)
        return data

    def _submit_as_guest(self, payload):
        """Submit the application running as the Guest user (the real prod context).

        The @public_api decorator serializes the OperationResult to its nested
        dict form before returning, so the public contract is a dict shaped as:
          success: bool
          data: {application_id, volunteer_name, member_name}   (on success)
          error: {message, code, ...}                            (on failure)
        These helpers read that dict so the tests exercise the real wire format.
        """
        with self.as_user("Guest"):
            return submit_volunteer_application(**payload)

    @staticmethod
    def _ok(result):
        return result.get("success") is True

    @staticmethod
    def _error_code(result):
        return (result.get("error") or {}).get("code")

    @staticmethod
    def _error_message(result):
        return (result.get("error") or {}).get("message") or ""

    @staticmethod
    def _data(result):
        return result.get("data") or {}

    @staticmethod
    def _message(result):
        # On success the OperationResult message is serialized under meta.
        return (result.get("meta") or {}).get("message") or ""

    def _track_created_volunteer(self, result):
        """Track any Volunteer the endpoint created so tearDown cleans it up."""
        data = self._data(result)
        if self._ok(result) and data.get("volunteer_name"):
            name = data["volunteer_name"]
            if frappe.db.exists("Volunteer", name):
                self.track_doc("Volunteer", name)
                member = frappe.db.get_value("Volunteer", name, "member")
                if member and frappe.db.exists("Member", member):
                    self.track_doc("Member", member)
        return result

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------
    def test_guest_can_submit_and_volunteer_is_created_with_submitted_fields(self):
        payload = self._valid_payload()
        result = self._track_created_volunteer(self._submit_as_guest(payload))

        self.assertTrue(self._ok(result), f"Submission should succeed: {self._error_message(result)}")
        vol_name = self._data(result)["volunteer_name"]
        self.assertTrue(frappe.db.exists("Volunteer", vol_name))

        vol = frappe.get_doc("Volunteer", vol_name)
        # The created doc's fields must match what was submitted.
        self.assertEqual(vol.email, payload["email"])
        self.assertEqual(vol.volunteer_name, "Ria Vermeer")
        # New public applications must start as "New" (NOT Active) — they are
        # not yet vetted/onboarded.
        self.assertEqual(vol.status, "New")
        self.assertEqual(vol.experience_level, "Beginner")
        # time_commitment "6-10" maps to "Regular (Monthly)".
        self.assertEqual(vol.commitment_level, "Regular (Monthly)")
        # The motivation text is persisted into the notes blob.
        self.assertIn(payload["motivation"], vol.note)

    def test_submitting_without_become_member_creates_no_member_link(self):
        payload = self._valid_payload()
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result))
        self.assertIsNone(self._data(result)["member_name"])
        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        self.assertFalse(vol.member, "No member should be linked when become_member is not set")

    def test_interest_area_is_linked_and_category_auto_created(self):
        # _add_interest_areas now uses the correct field names: it creates the
        # Volunteer Interest Category via `category_name` (the autoname source,
        # so the category's `name` equals the interest label) and appends the
        # child row via the real Link field `interest_area`. A guest who ticks an
        # interest box must therefore SUCCEED, get a Volunteer created, and have
        # the interest linked — with the category auto-created when it does not
        # already exist on the site.
        mapped_category = "Event Organization"  # interest_events -> this label
        self.assertFalse(
            frappe.db.exists("Volunteer Interest Category", mapped_category),
            "precondition: interest category must NOT already exist (auto-create path)",
        )
        payload = self._valid_payload(interest_events=1)
        result = self._track_created_volunteer(self._submit_as_guest(payload))

        self.assertTrue(self._ok(result), f"Submission should succeed: {self._error_message(result)}")
        # The category was auto-created (its name is the label, via autoname).
        self.assertTrue(
            frappe.db.exists("Volunteer Interest Category", mapped_category),
            "Selecting an interest must auto-create its category",
        )
        self.track_doc("Volunteer Interest Category", mapped_category)

        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        self.assertEqual(len(vol.interests), 1, "Exactly one interest row should be appended")
        self.assertEqual(
            vol.interests[0].interest_area,
            mapped_category,
            "Child row must link the mapped category via the `interest_area` field",
        )

    def test_interest_area_links_to_preexisting_category(self):
        # When the category already exists, _add_interest_areas must reuse it
        # (no duplicate) and still link the child row via `interest_area`.
        self._persist_interest_category("Event Organization")
        payload = self._valid_payload(interest_events=1)
        result = self._track_created_volunteer(self._submit_as_guest(payload))

        self.assertTrue(self._ok(result), f"Submission should succeed: {self._error_message(result)}")
        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        self.assertEqual(len(vol.interests), 1)
        self.assertEqual(vol.interests[0].interest_area, "Event Organization")
        # The pre-existing category was reused, not duplicated.
        self.assertEqual(
            frappe.db.count("Volunteer Interest Category", {"category_name": "Event Organization"}), 1
        )

    # ------------------------------------------------------------------
    # Validation paths (untrusted input -> proper rejection, not silent success)
    # ------------------------------------------------------------------
    def test_missing_required_field_is_rejected(self):
        payload = self._valid_payload()
        del payload["email"]
        result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "MISSING_REQUIRED_FIELDS")
        self.assertIn("email", self._error_message(result))

    def test_missing_multiple_required_fields_lists_all(self):
        payload = self._valid_payload()
        del payload["birth_date"]
        del payload["motivation"]
        result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "MISSING_REQUIRED_FIELDS")
        self.assertIn("birth_date", self._error_message(result))
        self.assertIn("motivation", self._error_message(result))

    def test_empty_string_required_field_is_treated_as_missing(self):
        # Guest input may POST empty strings; these must NOT pass validation.
        payload = self._valid_payload(first_name="")
        result = self._submit_as_guest(payload)
        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "MISSING_REQUIRED_FIELDS")
        self.assertIn("first_name", self._error_message(result))

    def test_applicant_under_16_is_rejected(self):
        from frappe.utils import add_years, today

        # 15 years old today -> below the 16 minimum.
        too_young = add_years(today(), -15)
        payload = self._valid_payload(birth_date=too_young)
        result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "AGE_REQUIREMENT_NOT_MET")
        # The under-age applicant must NOT have created a Volunteer record.
        self.assert_doc_not_exists("Volunteer", {"email": payload["email"]})

    def test_applicant_exactly_old_enough_is_accepted(self):
        from frappe.utils import add_days, add_years, today

        # 16 years + a day old -> just over the threshold.
        old_enough = add_days(add_years(today(), -16), -1)
        payload = self._valid_payload(birth_date=old_enough)
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))

    # ------------------------------------------------------------------
    # #659 — the configured minimum, not a literal 16
    #
    # This endpoint hardcoded `if age < 16` and never read
    # Verenigingen Settings.minimum_volunteer_age, so raising the association's
    # minimum left the one entry point reachable without a login still
    # accepting 16-year-olds. Both directions are asserted: a raised minimum
    # must start rejecting, and a lowered one must start accepting — a literal
    # 16 cannot satisfy both.
    # ------------------------------------------------------------------
    def test_public_application_rejects_below_a_raised_minimum_volunteer_age(self):
        from frappe.utils import add_years, today

        with pinned_setting("minimum_volunteer_age", 21):
            payload = self._valid_payload(birth_date=add_years(today(), -18))
            result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result), "18 is below a configured minimum of 21")
        self.assertEqual(self._error_code(result), "AGE_REQUIREMENT_NOT_MET")
        self.assertIn("21", self._error_message(result), "The message must quote the CONFIGURED minimum")
        self.assert_doc_not_exists("Volunteer", {"email": payload["email"]})

    def test_public_application_accepts_above_a_lowered_minimum_volunteer_age(self):
        from frappe.utils import add_years, today

        with pinned_setting("minimum_volunteer_age", 14):
            payload = self._valid_payload(birth_date=add_years(today(), -15))
            result = self._track_created_volunteer(self._submit_as_guest(payload))

        self.assertTrue(
            self._ok(result),
            f"15 is above a configured minimum of 14: {self._error_message(result)}",
        )

    def test_public_application_accepts_on_the_exact_nth_birthday(self):
        """#657 + #659 together: the applicant turns exactly `min_age` today.

        21 is not divisible by 4, so substituting the configured value WITHOUT
        the integer-calendar fix would reject this applicant.
        """
        from frappe.utils import add_years, today

        with pinned_setting("minimum_volunteer_age", 21):
            payload = self._valid_payload(birth_date=add_years(today(), -21))
            result = self._track_created_volunteer(self._submit_as_guest(payload))

        self.assertTrue(
            self._ok(result),
            f"An applicant turning 21 today meets a minimum of 21: {self._error_message(result)}",
        )

    def test_unparseable_birth_date_is_reported_as_such_not_as_a_config_error(self):
        """getdate() and _get_configurable_min_age both raise frappe.ValidationError.

        Conflating them would tell a guest who typed a bad date that the service
        is unavailable, and would write a misleading Error Log every time.
        """
        payload = self._valid_payload(birth_date="not-a-date")
        result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "INVALID_BIRTH_DATE")
        self.assert_doc_not_exists("Volunteer", {"email": payload["email"]})

    def test_public_application_refuses_when_the_minimum_is_not_configured(self):
        """_get_configurable_min_age throws rather than falling back to a literal.

        An unauthenticated endpoint must fail CLOSED on a configuration error —
        an age gate that silently opens is worse than one that is temporarily
        shut — and must not leak the settings-field name to the caller.
        """
        with pinned_setting("minimum_volunteer_age", 0):
            payload = self._valid_payload()
            result = self._submit_as_guest(payload)

        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "AGE_REQUIREMENT_NOT_CONFIGURED")
        self.assertNotIn("minimum_volunteer_age", self._error_message(result))
        self.assert_doc_not_exists("Volunteer", {"email": payload["email"]})

    # ------------------------------------------------------------------
    # Duplicate-application detection
    # ------------------------------------------------------------------
    def _persist_interest_category(self, category_name):
        """Idempotently persist a Volunteer Interest Category by its real field."""
        if frappe.db.exists("Volunteer Interest Category", category_name):
            return frappe.get_doc("Volunteer Interest Category", category_name)
        cat = frappe.new_doc("Volunteer Interest Category")
        cat.category_name = category_name
        cat.insert(ignore_permissions=True)
        self.track_doc("Volunteer Interest Category", cat.name)
        return cat

    def _persist_volunteer_interest(self, volunteer_name, interest_area):
        """Append an interest row to an existing Volunteer via its child doctype."""
        row = frappe.new_doc("Volunteer Interest Area")
        row.parent = volunteer_name
        row.parenttype = "Volunteer"
        row.parentfield = "interests"
        row.interest_area = interest_area
        row.insert(ignore_permissions=True)
        return row

    def _make_existing_volunteer(self, email, status):
        """Persist a Volunteer with a given email+status via factory + force set.

        Uses the base-class factory (no ignore_permissions in the test body).
        The factory does not accept an email/status kwarg reliably, so we set
        them with db_set after creation, then reload.
        """
        vol = self.create_test_volunteer()
        frappe.db.set_value("Volunteer", vol.name, {"email": email, "status": status})
        frappe.db.commit()
        return frappe.get_doc("Volunteer", vol.name)

    def test_duplicate_active_volunteer_is_rejected(self):
        email = f"active.{self._uniq}@example.com"
        self._make_existing_volunteer(email, "Active")

        result = self._submit_as_guest(self._valid_payload(email=email))
        self.assertFalse(self._ok(result))
        self.assertEqual(self._error_code(result), "VOLUNTEER_ALREADY_EXISTS")

    def test_duplicate_new_application_is_rejected_with_distinct_code(self):
        email = f"pending.{self._uniq}@example.com"
        self._make_existing_volunteer(email, "New")

        result = self._submit_as_guest(self._valid_payload(email=email))
        self.assertFalse(self._ok(result))
        # A still-pending application gets its own, distinct error code.
        self.assertEqual(self._error_code(result), "APPLICATION_ALREADY_SUBMITTED")

    def test_inactive_volunteer_can_reapply_and_record_is_reactivated(self):
        # RESOLVED logic-vs-schema contradiction: the duplicate-check logic only
        # blocks Active/Onboarding/New volunteers, so an "Inactive" volunteer is
        # allowed to re-apply. Because Volunteer.email is unique, the
        # re-application must REUSE the existing record (reactivate it in place)
        # rather than insert a duplicate. The maintainer's decision was to allow
        # reactivation.
        email = f"inactive.{self._uniq}@example.com"
        existing = self._make_existing_volunteer(email, "Inactive")

        result = self._track_created_volunteer(
            self._submit_as_guest(
                self._valid_payload(
                    email=email,
                    first_name="Riana",
                    last_name="Vermeer",
                    motivation="I am back and want to help again.",
                    time_commitment="11-20",
                )
            )
        )
        self.assertTrue(self._ok(result), f"Reapply should succeed: {self._error_message(result)}")

        # The SAME volunteer record is reused — no duplicate is created.
        self.assertEqual(self._data(result)["volunteer_name"], existing.name)
        self.assertEqual(frappe.db.count("Volunteer", {"email": email}), 1)

        vol = frappe.get_doc("Volunteer", existing.name)
        # Reactivation puts the volunteer back into the onboarding pipeline as
        # "New" (a guest re-application must NOT self-activate to Active).
        self.assertEqual(vol.status, "New")
        # The record is refreshed with the new application's details.
        self.assertEqual(vol.volunteer_name, "Riana Vermeer")
        self.assertEqual(vol.commitment_level, "Weekly")
        self.assertIn("I am back and want to help again.", vol.note)

    def test_retired_volunteer_can_reapply_and_record_is_reactivated(self):
        # "Retired" is the other terminal status that the duplicate-check logic
        # treats as eligible to re-apply; it must reactivate just like Inactive.
        email = f"retired.{self._uniq}@example.com"
        existing = self._make_existing_volunteer(email, "Retired")

        result = self._track_created_volunteer(self._submit_as_guest(self._valid_payload(email=email)))
        self.assertTrue(self._ok(result), f"Reapply should succeed: {self._error_message(result)}")

        self.assertEqual(self._data(result)["volunteer_name"], existing.name)
        self.assertEqual(frappe.db.count("Volunteer", {"email": email}), 1)
        self.assertEqual(frappe.db.get_value("Volunteer", existing.name, "status"), "New")

    def test_reactivation_does_not_duplicate_interest_rows(self):
        # A returning volunteer who had interests on file, and re-selects an
        # interest, must end up with that interest linked exactly once (the
        # stale rows are refreshed from the new application, not appended to).
        email = f"reinterest.{self._uniq}@example.com"
        existing = self._make_existing_volunteer(email, "Inactive")
        self._persist_interest_category("Event Organization")
        # Seed a pre-existing interest row on the dormant record.
        self._persist_volunteer_interest(existing.name, "Event Organization")

        result = self._track_created_volunteer(
            self._submit_as_guest(self._valid_payload(email=email, interest_events=1))
        )
        self.assertTrue(self._ok(result), self._error_message(result))

        vol = frappe.get_doc("Volunteer", existing.name)
        areas = [row.interest_area for row in vol.interests]
        self.assertEqual(areas.count("Event Organization"), 1, "Interest must not be duplicated on reapply")

    # ------------------------------------------------------------------
    # Guest permission boundary / privilege escalation
    # ------------------------------------------------------------------
    def test_guest_cannot_escalate_status_via_input(self):
        # A malicious guest tries to self-activate by passing status=Active.
        payload = self._valid_payload(status="Active")
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))

        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        # The endpoint must hard-code status="New"; guest input must NOT win.
        self.assertEqual(vol.status, "New", "Guest must not be able to self-activate via status input")

    def test_guest_cannot_attach_arbitrary_user_account(self):
        # A malicious guest tries to bind the volunteer to an existing privileged
        # user account by passing `user` and `member` directly.
        payload = self._valid_payload(user="Administrator", member="NON-EXISTENT-MEMBER")
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))

        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        # The endpoint never reads data["user"]/data["member"], so neither the
        # Administrator user nor the bogus member may be attached.
        self.assertFalse(vol.user, "Guest must not be able to bind an arbitrary User account")
        self.assertFalse(vol.member, "Guest must not be able to inject an arbitrary Member link")

    def test_guest_become_member_does_not_link_to_unrelated_member(self):
        # Guest sets become_member=1 but supplies an email that belongs to NO
        # member. The volunteer must not be linked to anyone else's member.
        payload = self._valid_payload(become_member=1)
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))
        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        # If a member was created it must be tied to THIS application's email,
        # never to a pre-existing unrelated member.
        if vol.member:
            member_email = frappe.db.get_value("Member", vol.member, "email")
            self.assertEqual(member_email, payload["email"])

    def test_become_member_links_to_existing_member_with_same_email(self):
        # If a Member already exists with the applicant's email and they opt in
        # to membership, the new volunteer must be linked to that EXISTING member
        # (and no second member is created).
        member = self.create_test_member(
            first_name="Joris",
            last_name="Bakker",
            email=f"joris.{self._uniq}@example.com",
        )
        payload = self._valid_payload(
            first_name="Joris",
            last_name="Bakker",
            email=member.email,
            become_member=1,
        )
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))

        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])
        self.assertEqual(vol.member, member.name, "Volunteer should link to the pre-existing member")
        # No new membership application was created (member_link short-circuits it).
        self.assertIsNone(self._data(result)["member_name"])

    # ------------------------------------------------------------------
    # become_member end-to-end
    # ------------------------------------------------------------------
    def test_become_member_without_address_surfaces_membership_error(self):
        # A new applicant opts in to membership but supplies no address. The
        # volunteer record is still created (the primary outcome), but the
        # membership sign-up legitimately fails address validation. That failure
        # must be SURFACED to the applicant, not silently swallowed.
        payload = self._valid_payload(
            first_name="Wim",
            last_name="DeJong",
            email=f"wim.{self._uniq}@example.com",
            become_member=1,
        )
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        # The volunteer itself is still created and overall success is reported.
        self.assertTrue(self._ok(result), self._error_message(result))

        data = self._data(result)
        vol = frappe.get_doc("Volunteer", data["volunteer_name"])
        if data["member_name"] and frappe.db.exists("Member", data["member_name"]):
            self.track_doc("Member", data["member_name"])

        # No member is created/linked without a valid address ...
        self.assertIsNone(
            data["member_name"],
            "No member should be created when no valid address is provided",
        )
        self.assertFalse(vol.member, "Volunteer is left unlinked to any member")
        # ... but the membership failure is now surfaced rather than swallowed.
        self.assertTrue(
            data.get("membership_application_error"),
            "The membership sign-up failure must be surfaced in the response",
        )
        # The message names a missing-address-style validation problem.
        self.assertRegex(
            self._message(result),
            r"membership sign-up could not be completed",
        )

    def test_become_member_with_valid_address_creates_and_links_member(self):
        # A new applicant opts in to membership AND supplies a valid Dutch
        # address: a Member is created and the volunteer is linked to it, with no
        # surfaced membership error.
        payload = self._valid_payload(
            first_name="Wim",
            last_name="DeJong",
            email=f"wim.{self._uniq}@example.com",
            become_member=1,
            address_line1="Hoofdstraat 1",
            city="Amsterdam",
            postal_code="1011 AB",
            country="Netherlands",
        )
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))

        data = self._data(result)
        self.assertIsNone(data.get("membership_application_error"))
        member_name = data["member_name"]
        self.assertTrue(member_name, "A member should be created for a valid become_member request")
        self.track_doc("Member", member_name)

        # The created member carries the applicant's email and the volunteer is linked.
        self.assertEqual(frappe.db.get_value("Member", member_name, "email"), payload["email"])
        vol = frappe.get_doc("Volunteer", data["volunteer_name"])
        self.assertEqual(vol.member, member_name, "Volunteer should be linked to the new member")

    # ------------------------------------------------------------------
    # notes-building / mapping unit behavior (pure functions)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # #659 — the FORM in front of the endpoint carried the same literal
    # ------------------------------------------------------------------
    def test_the_public_form_renders_the_configured_minimum_not_a_literal(self):
        """apply.html hardcoded 16 in its help text AND in its own birth-date check.

        The client check does not merely warn — it CLEARS the field, so with the
        literal in place, lowering minimum_volunteer_age left the browser blocking
        an applicant the fixed endpoint would have accepted. Rendered rather than
        grepped, so the Jinja plumbing is exercised end to end.
        """
        from frappe.website.serve import get_response_content

        with pinned_setting("minimum_volunteer_age", 21), self.as_user("Guest"):
            html = get_response_content("volunteer/apply")

        # Narrowed to the age lines: asserting against the whole rendered page
        # dumps ~40KB of HTML into the CI log on every failure.
        age_lines = [
            line.strip()
            for line in html.splitlines()
            if "years old to volunteer" in line or "minimumAge" in line
        ]
        rendered = "\n".join(age_lines)
        self.assertIn("You must be at least 21 years old to volunteer", rendered)
        self.assertIn("const minimumAge = 21;", rendered)
        self.assertNotIn("at least 16 years old to volunteer", rendered)

    def test_time_commitment_mapping(self):
        self.assertEqual(_map_time_commitment("1-5"), "Occasional")
        self.assertEqual(_map_time_commitment("6-10"), "Regular (Monthly)")
        self.assertEqual(_map_time_commitment("11-20"), "Weekly")
        self.assertEqual(_map_time_commitment("20+"), "Intensive")
        self.assertEqual(_map_time_commitment("flexible"), "Occasional")
        # Unknown / empty values fall back to "Occasional".
        self.assertEqual(_map_time_commitment("nonsense"), "Occasional")
        self.assertEqual(_map_time_commitment(None), "Occasional")

    def test_build_notes_contains_all_supplied_sections(self):
        data = {
            "motivation": "MOTIVATION_TEXT",
            "previous_experience": "PREV_EXP_TEXT",
            "skills_description": "SKILLS_TEXT",
            "time_commitment": "6-10",
            "availability": "Weekends",
            "referral_source": "A friend",
            "additional_comments": "EXTRA_TEXT",
            "contact_number": "+31612345678",
        }
        notes = _build_volunteer_notes(data)
        self.assertIn("MOTIVATION_TEXT", notes)
        self.assertIn("PREV_EXP_TEXT", notes)
        self.assertIn("SKILLS_TEXT", notes)
        self.assertIn("EXTRA_TEXT", notes)
        self.assertIn("+31612345678", notes)
        self.assertIn("Weekends", notes)

    def test_xss_payload_in_motivation_is_neutralized_on_save(self):
        # The motivation is stored in the `note` Text Editor (HTML) field. A
        # malicious guest submits a <script> tag. Frappe's Text Editor sanitizer
        # must neutralize it on save so the stored value cannot execute when the
        # note is rendered in Desk.
        payload = self._valid_payload(
            motivation="<script>alert('xss')</script>I want to help animals"
        )
        result = self._track_created_volunteer(self._submit_as_guest(payload))
        self.assertTrue(self._ok(result), self._error_message(result))
        vol = frappe.get_doc("Volunteer", self._data(result)["volunteer_name"])

        # The live <script> tag must NOT survive verbatim...
        self.assertNotIn("<script>", vol.note, "Raw <script> must not be stored unescaped")
        # ...but the legitimate text content the applicant typed is preserved.
        self.assertIn("I want to help animals", vol.note)
