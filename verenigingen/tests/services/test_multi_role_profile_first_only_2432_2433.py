# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""#2432 / #2433: code that read only the FIRST role profile (``User.role_profile_name``).

On Frappe v16 a user's profiles live in the ``role_profiles`` child table and
``role_profile_name`` mirrors only the first row. The stacked shape is produced by the
app's own sync: ``sync_user_role_profile`` keeps a profile it did not grant (a manual one)
and APPENDS what it derives, so a user holding a manual profile who is an active volunteer
ends up with [manual, Volunteer]. (Measured on test_site_4: the sync REPLACES a held
"Verenigingen Member" with Volunteer rather than stacking, so Member is not a stacking
first profile.)

Probe shortcut (stated, per the brief): desk-setting columns are zeroed with
``db.set_value`` to stand in for "settings were never enabled"; the profile stacking
itself goes through the real sync.
"""

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_MEMBER,
    PROFILE_VOLUNTEER,
    bulk_recalculate_role_profiles,
    sync_user_role_profile,
    validate_role_profile_data_integrity,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.user_desk_settings import (
    DESK_ENABLED_PROFILES,
    DESK_PROPERTIES,
    ensure_desk_settings_for_role_profile,
)


class TestFirstRoleProfileOnly(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        calc.invalidate_profile_config_cache()
        self.addCleanup(calc.invalidate_profile_config_cache)

    # ------------------------------------------------------------------ helpers

    def _make_member_user_2433(self):
        email = f"frp2433.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(
            first_name="FirstOnly",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status="Active",
        )
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name, member.name

    def _set_profiles(self, user, profiles):
        doc = frappe.get_doc("User", user)
        doc.set("role_profiles", [{"role_profile": p} for p in profiles])
        doc.save()
        frappe.clear_cache(user=user)

    def _stacked_member_volunteer_user(self):
        """[manual, Volunteer]: manual held first, Volunteer appended by the real sync."""
        manual = self._make_manual_profile()
        user, member = self._make_member_user_2433()
        self._set_profiles(user, [manual])
        self.create_test_volunteer(member=member, status="Active")
        sync_user_role_profile(user, dry_run=False)
        rows = frappe.get_all(
            "User Role Profile", filters={"parent": user, "parenttype": "User"},
            pluck="role_profile", order_by="idx asc",
        )
        self.assertEqual(rows, [manual, PROFILE_VOLUNTEER], "fixture: real sync must stack")
        self.assertEqual(frappe.db.get_value("User", user, "role_profile_name"), manual)
        return user, member

    def _disable_desk(self, user):
        for prop in DESK_PROPERTIES:
            frappe.db.set_value("User", user, prop, 0, update_modified=False)

    def _desk_state(self, user):
        return [frappe.db.get_value("User", user, p) for p in DESK_PROPERTIES]

    # ------------------------------------------------------------------ #2432

    def test_fixture_first_profile_is_not_desk_enabled_but_second_is(self):
        """Guards the premise: the first profile does NOT mask the bug."""
        self.assertNotIn(self._make_manual_profile(), DESK_ENABLED_PROFILES)
        self.assertIn(PROFILE_VOLUNTEER, DESK_ENABLED_PROFILES)

    def test_desk_settings_enabled_when_desk_profile_is_second_on_update(self):
        manual = self._make_manual_profile()
        user, member = self._make_member_user_2433()
        self._set_profiles(user, [manual])
        self._disable_desk(user)
        self.create_test_volunteer(member=member, status="Active")
        # Real flow: the sync appends Volunteer and saves the User (on_update hook).
        sync_user_role_profile(user, dry_run=False)
        self.assertEqual(frappe.db.get_value("User", user, "role_profile_name"), manual)
        self.assertEqual(self._desk_state(user), [1] * len(DESK_PROPERTIES))

    def test_desk_settings_enabled_when_desk_profile_is_second_on_insert(self):
        manual = self._make_manual_profile()
        email = f"frp2433.ins.{frappe.generate_hash(length=8)}@test.invalid"
        doc = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Ins",
                "send_welcome_email": 0,
                # The User defaults are 1, which would make this test vacuous.
                **{prop: 0 for prop in DESK_PROPERTIES},
                "role_profiles": [{"role_profile": manual}, {"role_profile": PROFILE_VOLUNTEER}],
            }
        ).insert()
        self.track_doc("User", doc.name)
        self.assertEqual(frappe.db.get_value("User", email, "role_profile_name"), manual)
        self.assertEqual(self._desk_state(email), [1] * len(DESK_PROPERTIES))

    def test_desk_settings_untouched_when_no_profile_is_desk_enabled(self):
        """Control: a Member-only user keeps disabled desk settings (a real, disabled row)."""
        user, _member = self._make_member_user_2433()
        self._set_profiles(user, [PROFILE_MEMBER])
        self.assertNotIn(PROFILE_MEMBER, DESK_ENABLED_PROFILES)
        self._disable_desk(user)
        doc = frappe.get_doc("User", user)
        doc.first_name = "Renamed"
        doc.save()
        self.assertEqual(self._desk_state(user), [0] * len(DESK_PROPERTIES))

    def test_unrelated_save_does_not_re_enable_deliberately_disabled_settings(self):
        """Control: the hook still acts only when the profile set changes."""
        user, _member = self._stacked_member_volunteer_user()
        self._disable_desk(user)
        doc = frappe.get_doc("User", user)
        doc.first_name = "Renamed"
        doc.save()
        self.assertEqual(self._desk_state(user), [0] * len(DESK_PROPERTIES))

    def test_hook_acts_for_stacked_user_when_there_is_no_before_doc(self):
        """Direct call with no before-doc (the insert shape) acts for a stacked user."""
        user, _member = self._stacked_member_volunteer_user()
        self._disable_desk(user)
        doc = frappe.get_doc("User", user)
        ensure_desk_settings_for_role_profile(doc, "on_update")  # no before-doc: counts as changed
        self.assertEqual(self._desk_state(user), [1] * len(DESK_PROPERTIES))

    # ------------------------------------------------------------------ #2433

    def test_bulk_default_filter_includes_user_whose_qualifying_profile_is_second(self):
        """[manual, Member]: first profile outside the default four, Member second.

        Volunteer record is Inactive while the user holds Volunteer-less [manual, Member]
        and an ACTIVE volunteer exists, so a real change (add Volunteer) is pending.
        """
        manual = self._make_manual_profile()
        user, member = self._make_member_user_2433()
        self._set_profiles(user, [manual, PROFILE_MEMBER])
        self.assertEqual(frappe.db.get_value("User", user, "role_profile_name"), manual)
        self.create_test_volunteer(member=member, status="Active")

        result = bulk_recalculate_role_profiles(dry_run=True)

        self.assertIn(user, [c["user"] for c in result["changes"]], result["errors_list"])

    def test_bulk_default_filter_still_excludes_user_with_no_default_profile(self):
        """Control: only [manual] held, same pending change; must NOT be swept in."""
        manual = self._make_manual_profile()
        user, member = self._make_member_user_2433()
        self._set_profiles(user, [manual])
        self.create_test_volunteer(member=member, status="Active")
        # Prove the user WOULD change if swept in (a real row for the wrong behaviour).
        explicit = bulk_recalculate_role_profiles(filters={"name": user}, dry_run=True)
        self.assertEqual(explicit["changed"], 1, explicit)

        result = bulk_recalculate_role_profiles(dry_run=True)

        self.assertNotIn(user, [c["user"] for c in result["changes"]])

    def test_validation_sample_reports_no_false_mismatch_for_stacked_profiles(self):
        """[Member, Volunteer] with an active volunteer: the headline Volunteer IS held.

        Probe shortcut: the stack is written directly (the real sync replaces Member
        with Volunteer, see module docstring), the shape an admin-assigned stack has.
        """
        stacked, member = self._make_member_user_2433()
        self._set_profiles(stacked, [PROFILE_MEMBER, PROFILE_VOLUNTEER])
        self.create_test_volunteer(member=member, status="Active")
        # Control: genuinely drifted user (holds Member only, derives Volunteer).
        drifted, member2 = self._make_member_user_2433()
        self._set_profiles(drifted, [PROFILE_MEMBER])
        self.create_test_volunteer(member=member2, status="Active")

        issues = validate_role_profile_data_integrity()["issues"]["profile_mismatches"]
        reported = {i["user"] for i in issues}

        self.assertIn(drifted, reported, "control: a real mismatch must still be reported")
        self.assertNotIn(stacked, reported, "stacked [Member, Volunteer] is not a mismatch")

    def test_validation_sample_covers_user_whose_qualifying_profile_is_second(self):
        """[manual, Member] with an active volunteer is a real mismatch, and was never sampled."""
        manual = self._make_manual_profile()
        user, member = self._make_member_user_2433()
        self._set_profiles(user, [manual, PROFILE_MEMBER])
        self.create_test_volunteer(member=member, status="Active")

        issues = validate_role_profile_data_integrity()["issues"]["profile_mismatches"]

        self.assertIn(user, {i["user"] for i in issues})

    def _make_manual_profile(self):
        name = f"FRP2433 manual {frappe.generate_hash(length=6)}"
        rp = frappe.get_doc(
            {"doctype": "Role Profile", "role_profile": name, "roles": [{"role": "Verenigingen Member"}]}
        )
        rp.insert()
        self.track_doc("Role Profile", rp.name)
        return rp.name
