"""
The other Role Profile selectors behind the #1616 mapping guard (#1618).

Measured on test_site_4 before this change (real flows, no db.set_value stand-ins):

- Membership Type.role_profile: a Verenigingen Staff user (write on the doctype) set
  "Verenigingen Administrator" (grants System Manager). The member-type-change flow
  (update_membership_type_role_profile, what the contribution amendment approval calls)
  then gave a member's user System Manager. Guarded here.
- MijnRood Role Mapping.role_profile: a Verenigingen Administrator without System
  Manager could save any profile; the sync hands it to the Account Creation Request.
  The request's final profile is recalculated by the ACR pipeline's last phase (measured:
  roles ended at Verenigingen Member), which is the only thing that stops it. Guarded
  here so that does not rest on a non-fatal sync step.
- Account Creation Request.role_profile: NOT guarded. validate() demands User "create"
  (System Manager only), and a Staff or Administrator-only session was refused on insert,
  with and without ignore_permissions.

Writers driven as a non-System-Manager session: the install fixture
(create_default_membership_types) and Membership Type's own default. MijnRood's
default teams are covered by test_role_profile_mapping_guard; the default role mapping
carries no role_profile (and populate_default_role_mapping is admin-gated by decorator).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SYSTEM_PROFILE = "Verenigingen Administrator"  # grants System Manager
NATIONAL_PROFILE = "Verenigingen National Board Member"
PLAIN_PROFILE = "Verenigingen Auditor"  # neither system nor national
DEFAULT_PROFILE = "Verenigingen Member"


def _selector_profile_roles(profile):
    return set(frappe.get_all("Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, pluck="role"))


class SelectorGuardCase(EnhancedTestCase):
    def _selector_user(self, roles):
        email = f"selector-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Selector",
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in roles],
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "User", email, force=True)
        return email

    def test_control_fixture_profiles_grant_what_the_tests_assume(self):
        self.assertIn("System Manager", _selector_profile_roles(SYSTEM_PROFILE))
        self.assertNotIn("System Manager", _selector_profile_roles(PLAIN_PROFILE))
        self.assertNotIn("System Manager", _selector_profile_roles(NATIONAL_PROFILE))
        self.assertNotIn("Verenigingen Auditor", _selector_profile_roles(DEFAULT_PROFILE))


class TestMembershipTypeProfile(SelectorGuardCase):
    def _selector_type(self, profile, user=None, **extra):
        name = f"Selector Type {frappe.generate_hash(length=6)}"
        values = {"doctype": "Membership Type", "membership_type_name": name, "is_active": 1, "minimum_amount": 5}
        if profile is not None:
            values["role_profile"] = profile
        doc = frappe.get_doc({**values, **extra})
        if user:
            with self.as_user(user):
                doc.insert()
        else:
            doc.insert()
        self.addCleanup(frappe.delete_doc, "Membership Type", name, force=True)
        return doc

    def test_staff_cannot_create_a_type_that_maps_a_profile_granting_system_manager(self):
        staff = self._selector_user(["Verenigingen Staff"])
        name = f"Selector Type {frappe.generate_hash(length=6)}"

        with self.as_user(staff):
            self.assertNotIn("System Manager", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                frappe.get_doc(
                    {
                        "doctype": "Membership Type",
                        "membership_type_name": name,
                        "is_active": 1,
                        "minimum_amount": 5,
                        "role_profile": SYSTEM_PROFILE,
                    }
                ).insert()

        self.assertFalse(frappe.db.exists("Membership Type", name))

    def test_staff_cannot_repoint_an_existing_type_to_such_a_profile(self):
        staff = self._selector_user(["Verenigingen Staff"])
        mt = self._selector_type(DEFAULT_PROFILE)

        with self.as_user(staff):
            doc = frappe.get_doc("Membership Type", mt.name)
            doc.role_profile = SYSTEM_PROFILE
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                doc.save()

        self.assertEqual(frappe.db.get_value("Membership Type", mt.name, "role_profile"), DEFAULT_PROFILE)

    def test_the_refused_profile_never_reaches_a_members_user(self):
        """Outcome: the member-type-change flow grants a user whatever the type maps."""
        from verenigingen.utils.membership_type_role_profile import update_membership_type_role_profile

        user = self._selector_user([DEFAULT_PROFILE])
        staff = self._selector_user(["Verenigingen Staff"])
        # Control: an administrator's mapping lands, so the flow really grants System Manager.
        mapped = self._selector_type(SYSTEM_PROFILE)
        result = update_membership_type_role_profile(user, "", mapped.name)
        self.assertTrue(result.get("success"), result)
        # Read Has Role directly: frappe.get_roles goes through the per-user role cache.
        self.assertTrue(frappe.db.exists("Has Role", {"parent": user, "role": "System Manager"}))

        victim = self._selector_user([DEFAULT_PROFILE])
        mt = self._selector_type(DEFAULT_PROFILE)
        with self.as_user(staff):
            doc = frappe.get_doc("Membership Type", mt.name)
            doc.role_profile = SYSTEM_PROFILE
            with self.assertRaises(frappe.ValidationError):
                doc.save()
        update_membership_type_role_profile(victim, "", mt.name)

        self.assertNotIn("System Manager", frappe.get_roles(victim))

    def test_staff_may_map_a_profile_within_their_own_roles(self):
        profile = frappe.get_doc(
            {"doctype": "Role Profile", "role_profile": f"Selector Own {frappe.generate_hash(length=6)}", "roles": [{"role": "Auditor"}]}
        ).insert()
        self.addCleanup(frappe.delete_doc, "Role Profile", profile.name, force=True)
        staff = self._selector_user(["Verenigingen Staff", "Auditor"])
        with self.as_user(staff):
            self.assertLessEqual(_selector_profile_roles(profile.name), set(frappe.get_roles()))

        mt = self._selector_type(profile.name, user=staff)

        self.assertEqual(frappe.db.get_value("Membership Type", mt.name, "role_profile"), profile.name)

    def test_the_member_profile_is_always_allowed_and_is_the_default(self):
        """Lockout control: a Staff session without the Verenigingen Member role."""
        staff = self._selector_user(["Verenigingen Staff"])
        with self.as_user(staff):
            self.assertNotIn("Verenigingen Member", frappe.get_roles())

        explicit = self._selector_type(DEFAULT_PROFILE, user=staff)
        defaulted = self._selector_type(None, user=staff)

        self.assertEqual(frappe.db.get_value("Membership Type", explicit.name, "role_profile"), DEFAULT_PROFILE)
        self.assertEqual(frappe.db.get_value("Membership Type", defaulted.name, "role_profile"), DEFAULT_PROFILE)

    def test_existing_mapping_does_not_block_an_unrelated_save(self):
        staff = self._selector_user(["Verenigingen Staff"])
        mt = self._selector_type(SYSTEM_PROFILE)  # set by Administrator

        with self.as_user(staff):
            self.assertNotIn("System Manager", frappe.get_roles())
            doc = frappe.get_doc("Membership Type", mt.name)
            doc.description = "Edited by staff"
            doc.save()

        self.assertEqual(frappe.db.get_value("Membership Type", mt.name, "description"), "Edited by staff")

    def test_national_profile_is_refused_even_for_an_administrator(self):
        with self.assertRaisesRegex(frappe.ValidationError, "national"):
            self._selector_type(NATIONAL_PROFILE)

    def test_system_manager_may_map_any_other_profile(self):
        mt = self._selector_type(SYSTEM_PROFILE)

        self.assertEqual(frappe.db.get_value("Membership Type", mt.name, "role_profile"), SYSTEM_PROFILE)

    def test_install_fixture_creates_the_default_types_under_a_non_system_manager(self):
        from verenigingen.setup import create_default_membership_types

        names = ["Lid", "Huisgenootlid", "Aspirant", "Erelid", "Donateur"]
        existing = [n for n in names if frappe.db.exists("Membership Type", n)]
        for n in existing:
            frappe.delete_doc("Membership Type", n, force=True)
        staff = self._selector_user(["Verenigingen Staff"])

        with self.as_user(staff):
            create_default_membership_types()

        for n in names:
            self.assertEqual(frappe.db.get_value("Membership Type", n, "role_profile"), DEFAULT_PROFILE, n)


class TestMijnRoodRoleMappingProfile(SelectorGuardCase):
    def setUp(self):
        super().setUp()
        settings = frappe.get_doc("MijnRood Sync Settings")
        self._original = [
            {k: row.get(k) for k in ("mijnrood_role", "label", "create_volunteer", "role_profile")}
            for row in settings.role_mapping
        ]
        self.addCleanup(self._restore_selector_mapping)
        settings.set("role_mapping", [])
        settings.save()
        self.vadmin = self._selector_user(["Verenigingen Administrator"])

    def _restore_selector_mapping(self):
        settings = frappe.get_doc("MijnRood Sync Settings")
        settings.set("role_mapping", [])
        for row in self._original:
            settings.append("role_mapping", row)
        settings.save()
        frappe.cache.delete_value("mijnrood_role_mapping")

    def _save_mapping(self, profile, user=None, mijnrood_role="ROLE_DIVISION_CONTACT", role=None):
        def save():
            settings = frappe.get_doc("MijnRood Sync Settings")
            settings.set("role_mapping", [])
            settings.append(
                "role_mapping",
                {
                    "mijnrood_role": mijnrood_role,
                    "label": "Selector probe",
                    "create_volunteer": 1,
                    "role_profile": profile,
                    "verenigingen_role": role,
                },
            )
            settings.save()

        if user:
            with self.as_user(user):
                save()
        else:
            save()

    def test_administrator_without_system_manager_cannot_map_a_system_profile(self):
        with self.as_user(self.vadmin):
            self.assertNotIn("System Manager", frappe.get_roles())
            self.assertTrue(frappe.has_permission("MijnRood Sync Settings", "write"))
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                self._save_mapping(SYSTEM_PROFILE)
        self.assertFalse(frappe.get_doc("MijnRood Sync Settings").role_mapping)

    def test_administrator_cannot_map_a_profile_granting_roles_they_lack(self):
        with self.as_user(self.vadmin):
            self.assertNotIn("Verenigingen Auditor", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "Verenigingen Auditor"):
                self._save_mapping(PLAIN_PROFILE)

    def test_the_refused_profile_never_reaches_the_account_creation_request(self):
        """Outcome: the volunteer sync copies the mapped profile onto the request."""
        from verenigingen.mijnrood_sync.field_mapping import _load_role_mapping

        frappe.cache.delete_value("mijnrood_role_mapping")
        self._save_mapping(SYSTEM_PROFILE)  # control: System Manager's mapping is read back
        frappe.cache.delete_value("mijnrood_role_mapping")
        self.assertEqual(_load_role_mapping()["ROLE_DIVISION_CONTACT"]["role_profile"], SYSTEM_PROFILE)

        self._save_mapping(None)
        with self.as_user(self.vadmin):
            with self.assertRaises(frappe.ValidationError):
                self._save_mapping(SYSTEM_PROFILE)
        frappe.cache.delete_value("mijnrood_role_mapping")
        self.assertIsNone(_load_role_mapping()["ROLE_DIVISION_CONTACT"]["role_profile"])

    def test_existing_mapping_does_not_block_an_unrelated_save(self):
        self._save_mapping(SYSTEM_PROFILE)  # set by Administrator

        with self.as_user(self.vadmin):
            settings = frappe.get_doc("MijnRood Sync Settings")
            settings.poll_interval_minutes = 7
            settings.save()

        self.assertEqual(
            frappe.get_doc("MijnRood Sync Settings").role_mapping[0].role_profile, SYSTEM_PROFILE
        )

    def test_a_row_without_a_profile_is_saved_by_an_administrator(self):
        with self.as_user(self.vadmin):
            self._save_mapping(None)

        self.assertEqual(len(frappe.get_doc("MijnRood Sync Settings").role_mapping), 1)

    def test_moving_a_system_profile_to_another_mijnrood_role_is_a_new_mapping(self):
        """An administrator mapped it on ROLE_ADMIN; moving the row to another MijnRood
        role hands it to a different set of people, so it counts as new."""
        self._save_mapping(SYSTEM_PROFILE, mijnrood_role="ROLE_ADMIN")  # set by Administrator

        with self.as_user(self.vadmin):
            self.assertNotIn("System Manager", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                self._save_mapping(SYSTEM_PROFILE, mijnrood_role="ROLE_DIVISION_CONTACT")

        self.assertEqual(frappe.get_doc("MijnRood Sync Settings").role_mapping[0].mijnrood_role, "ROLE_ADMIN")

    def test_administrator_cannot_map_a_role_they_do_not_hold(self):
        with self.as_user(self.vadmin):
            self.assertNotIn("System Manager", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                self._save_mapping(None, role="System Manager")
        self.assertFalse(frappe.get_doc("MijnRood Sync Settings").role_mapping)

    def test_administrator_may_map_a_role_they_hold(self):
        with self.as_user(self.vadmin):
            self._save_mapping(None, role="Verenigingen Administrator")

        self.assertEqual(
            frappe.get_doc("MijnRood Sync Settings").role_mapping[0].verenigingen_role, "Verenigingen Administrator"
        )

    def test_existing_privileged_role_does_not_block_an_unrelated_save(self):
        self._save_mapping(None, role="System Manager")  # set by Administrator

        with self.as_user(self.vadmin):
            settings = frappe.get_doc("MijnRood Sync Settings")
            settings.poll_interval_minutes = 9
            settings.save()

        self.assertEqual(frappe.get_doc("MijnRood Sync Settings").role_mapping[0].verenigingen_role, "System Manager")

    def test_moving_a_privileged_role_to_another_mijnrood_role_is_a_new_mapping(self):
        self._save_mapping(None, mijnrood_role="ROLE_ADMIN", role="System Manager")

        with self.as_user(self.vadmin):
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                self._save_mapping(None, mijnrood_role="ROLE_DIVISION_CONTACT", role="System Manager")

    def test_the_refused_role_is_never_granted_by_the_volunteer_sync(self):
        """Outcome, through _ensure_volunteer. Member.user is set with db.set_value to
        stand in for the account creation that would have linked it."""
        from verenigingen.mijnrood_sync.field_mapping import _load_role_mapping
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            get_volunteer_sync_service,
        )

        def sync_grants_system_manager():
            member = self.create_test_member()
            self.create_test_volunteer(member.name)
            user = self._selector_user(["Verenigingen Member"])
            frappe.db.set_value("Member", member.name, "user", user)
            frappe.cache.delete_value("mijnrood_role_mapping")
            config = _load_role_mapping()["ROLE_DIVISION_CONTACT"]
            get_volunteer_sync_service()._ensure_volunteer(member.name, config)
            return "System Manager" in frappe.get_roles(user)

        self._save_mapping(None, role="System Manager")  # control: an administrator's mapping lands
        self.assertTrue(sync_grants_system_manager())

        self._save_mapping(None)
        with self.as_user(self.vadmin):
            with self.assertRaises(frappe.ValidationError):
                self._save_mapping(None, role="System Manager")
        frappe.cache.delete_value("mijnrood_role_mapping")
        self.assertFalse(sync_grants_system_manager())
