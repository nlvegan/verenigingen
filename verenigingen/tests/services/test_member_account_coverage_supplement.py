# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Supplemental real-DB coverage for ``verenigingen/services/member/`` targeting the
branches the prior account/approval sweeps left uncovered:

user_role_profile_calculator.py
    - ``_ensure_employee_for_profile`` (Employee stub creation when a board/staff
      profile that carries the Employee role is synced onto a user)
    - ``get_user_role_profiles`` reading a populated v16 ``role_profiles`` child table
    - ``invalidate_profile_config_cache`` selective + by-type + global eviction
    - ``auto_sync_on_role_change`` fire-and-forget wrapper (success + non-member)

base_role_profile_manager.py
    - ``validate_role_profile_dependencies`` missing-Role branch
    - ``validate_entity_configuration`` role-specific valid / missing-role / missing-profile
    - ``get_entities_using_role_profile`` role-specific assignment branch
    - ``safe_hook_execution`` success + error-isolation

application_helpers.py
    - ``get_form_data`` real assembly of the application form payload
    - ``_get_membership_type_currency`` company-default-currency branch
    - ``activate_pending_chapter_membership`` no-pending-record → create_active fallback
    - ``create_active_chapter_membership`` update-existing-Pending-to-Active branch

No business-logic mocking. Real Members, Volunteers, Chapters, Teams, Role
Profiles, Membership Types and Mode of Payment records are created via the
factory / ``frappe.get_doc().insert()``. Tests run as Administrator.

v16 note: role-profile assignment lands in the User ``role_profiles`` child
table, not the deprecated ``role_profile_name`` Link.
"""

import frappe

from verenigingen.services.member.account import (
    base_role_profile_manager as brpm,
    user_role_profile_calculator as calc,
)
from verenigingen.services.member.approval import application_helpers as ah
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG, _team_manager


class TestUserRoleProfileCalculatorSupplement(EnhancedTestCase):
    """Cover the calculator branches missed by test_user_role_profile_calculator."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.h = frappe.generate_hash(length=6)
        calc.invalidate_profile_config_cache()
        self.addCleanup(calc.invalidate_profile_config_cache)

    # ------------------------------------------------------------------ helpers

    def _make_member_user(self, status="Active", first_name="Roleprof", with_dob=True):
        email = f"urpcs.{frappe.generate_hash(length=8)}@test.invalid"
        kwargs = {
            "first_name": first_name,
            "last_name": f"M{frappe.generate_hash(length=5)}",
            "email": email,
            "status": status,
        }
        if with_dob:
            kwargs["birth_date"] = "1985-05-05"
        member = self.create_test_member(**kwargs)
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name, member.name

    def _make_volunteer(self, member, status="Active"):
        return self.create_test_volunteer(member=member, status=status).name

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert()
            self.track_doc("Chapter Role", role_name)

    def _add_board_position(self, chapter_name, volunteer, role="Bestuurslid"):
        self._ensure_chapter_role(role)
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()

    # ----------------------------------------------- _ensure_employee_for_profile

    def test_sync_board_profile_creates_employee_stub(self):
        """Syncing a profile carrying the Employee role auto-creates an Employee.

        ``Verenigingen Volunteer`` includes the Employee role; an Active volunteer
        resolves to that profile. ``sync_user_role_profile`` must create the
        Employee stub before saving the User so ERPNext's validate_employee_role
        hook does not strip the Employee/ESS roles.
        """
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        self.assertFalse(frappe.db.exists("Employee", {"user_id": user}))

        with self.assertNoErrorLog():
            result = calc.sync_user_role_profile(user, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["new_profile"], calc.PROFILE_VOLUNTEER)
        emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
        self.assertTrue(emp, "Employee stub should have been created for the Employee-bearing profile")
        # Member had a real birth_date, so the Employee must carry it through rather
        # than the 1990 placeholder.
        self.assertEqual(str(frappe.db.get_value("Employee", emp, "date_of_birth")), "1985-05-05")

    def test_ensure_employee_uses_placeholder_dob_when_member_has_none(self):
        """When the Member has no birth_date the stub falls back to the 1990 placeholder."""
        user, member = self._make_member_user(with_dob=False)
        # The factory seeds a default birth_date; clear it so the placeholder
        # fallback branch in _ensure_employee_for_profile actually runs.
        frappe.db.set_value("Member", member, "birth_date", None)
        self._make_volunteer(member, status="Active")

        with self.assertNoErrorLog():
            calc.sync_user_role_profile(user, dry_run=False)

        emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
        self.assertTrue(emp)
        self.assertEqual(str(frappe.db.get_value("Employee", emp, "date_of_birth")), calc._STUB_EMPLOYEE_DOB)

    def test_ensure_employee_noop_for_member_only_profile(self):
        """A plain member resolves to ``Verenigingen Member`` (no Employee role) → no stub."""
        user, member = self._make_member_user()  # no volunteer

        with self.assertNoErrorLog():
            result = calc.sync_user_role_profile(user, dry_run=False)

        self.assertEqual(result["new_profile"], calc.PROFILE_MEMBER)
        self.assertFalse(frappe.db.exists("Employee", {"user_id": user}))

    def test_ensure_employee_idempotent_when_employee_exists(self):
        """Re-running sync when an Employee already exists must not duplicate it."""
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        with self.assertNoErrorLog():
            calc.sync_user_role_profile(user, dry_run=False)
            calc._ensure_employee_for_profile(user, calc.PROFILE_VOLUNTEER)
        self.assertEqual(frappe.db.count("Employee", {"user_id": user}), 1, "No duplicate Employee on re-run")

    def test_ensure_employee_unknown_profile_returns_silently(self):
        """A profile name that does not exist is a no-op (DoesNotExistError swallowed)."""
        user, _ = self._make_member_user()
        with self.assertNoErrorLog():
            calc._ensure_employee_for_profile(user, "Ghost Profile ZZZ")
        self.assertFalse(frappe.db.exists("Employee", {"user_id": user}))

    # --------------------------------------------------- get_user_role_profiles

    def test_get_user_role_profiles_reads_populated_store(self):
        """After a sync the version-agnostic reader returns the assigned profile."""
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        with self.assertNoErrorLog():
            calc.sync_user_role_profile(user, dry_run=False)
        profiles = calc.get_user_role_profiles(user)
        self.assertIn(calc.PROFILE_VOLUNTEER, profiles)

    def test_get_user_role_profiles_empty_for_unprofiled_user(self):
        email = f"urpcs.noprof.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        # Brand new user with no role profile assigned.
        self.assertEqual(calc.get_user_role_profiles(user.name), [])

    # ---------------------------------------------- invalidate_profile_config_cache

    def test_invalidate_cache_specific_entity(self):
        calc._profile_config_cache["chapter_profile:ABC"] = ({}, frappe.utils.now_datetime())
        calc._profile_config_cache["team_profile:XYZ"] = ({}, frappe.utils.now_datetime())
        calc.invalidate_profile_config_cache(entity_type="chapter", entity_name="ABC")
        self.assertNotIn("chapter_profile:ABC", calc._profile_config_cache)
        self.assertIn("team_profile:XYZ", calc._profile_config_cache)

    def test_invalidate_cache_by_type(self):
        calc._profile_config_cache["chapter_profile:A"] = ({}, frappe.utils.now_datetime())
        calc._profile_config_cache["chapter_profile:B"] = ({}, frappe.utils.now_datetime())
        calc._profile_config_cache["team_profile:T"] = ({}, frappe.utils.now_datetime())
        calc.invalidate_profile_config_cache(entity_type="chapter")
        self.assertNotIn("chapter_profile:A", calc._profile_config_cache)
        self.assertNotIn("chapter_profile:B", calc._profile_config_cache)
        self.assertIn("team_profile:T", calc._profile_config_cache)

    def test_invalidate_cache_global(self):
        calc._profile_config_cache["chapter_profile:A"] = ({}, frappe.utils.now_datetime())
        calc._profile_config_cache["team_profile:T"] = ({}, frappe.utils.now_datetime())
        calc.invalidate_profile_config_cache()
        self.assertEqual(calc._profile_config_cache, {})

    # ----------------------------------------------------- auto_sync_on_role_change

    def test_auto_sync_on_role_change_success(self):
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        with self.assertNoErrorLog():
            result = calc.auto_sync_on_role_change(user)
        self.assertTrue(result["success"])
        self.assertEqual(result["new_profile"], calc.PROFILE_VOLUNTEER)

    def test_auto_sync_on_role_change_non_member_does_not_raise(self):
        """Fire-and-forget: a non-member user yields an unsuccessful result, no raise."""
        email = f"urpcs.autosync.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        # sync returns success=False ("not a member"); auto_sync logs a warning only.
        result = calc.auto_sync_on_role_change(user.name)
        self.assertFalse(result["success"])


class TestBaseRoleProfileManagerSupplement(EnhancedTestCase):
    """Cover validator + lookup branches missed by test_base_role_profile_manager."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.team_manager = _team_manager

    def _make_role_profile(self, label, roles=("Verenigingen Volunteer",)):
        name = f"BRPMS {label} {frappe.generate_hash(length=6)}"
        rp = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": name,
                "roles": [{"role": r} for r in roles],
            }
        )
        rp.insert()
        self.track_doc("Role Profile", rp.name)
        return rp.name

    def _make_team(self, **kwargs):
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"BRPMS Team {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                **kwargs,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _ensure_team_role(self, role_name):
        if not frappe.db.exists("Team Role", role_name):
            frappe.get_doc({"doctype": "Team Role", "role_name": role_name, "is_active": 1}).insert()
            self.track_doc("Team Role", role_name)
        return role_name

    # --------------------------------------- validate_role_profile_dependencies

    def test_dependencies_missing_role_flagged(self):
        """A Role Profile referencing a non-existent Role is flagged.

        Insert a valid profile, then point one of its child rows at a Role that
        doesn't exist via a direct child-table write (bypasses the Link
        validation that would normally block this).
        """
        profile = self._make_role_profile("DepRole")
        # Corrupt: add a child row referencing a missing Role at the DB level.
        child = frappe.get_all("Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, limit=1)
        self.assertTrue(child, "Role Profile should have at least one role row")
        frappe.db.set_value("Has Role", child[0].name, "role", "Ghost Role ZZZ")

        result = brpm.validate_role_profile_dependencies(profile, TEAM_CONFIG)
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Ghost Role ZZZ", result["error"])

    # ------------------------------------------- validate_entity_configuration

    def test_entity_config_role_specific_valid(self):
        """A team with a valid role-specific mapping passes validation."""
        profile = self._make_role_profile("EntityRS")
        role = self._ensure_team_role("BRPMS Coordinator")
        team = self._make_team(enable_role_specific_profiles=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": profile})
        team_doc.save()
        self.assertIsNone(brpm.validate_entity_configuration(TEAM_CONFIG, team))

    def test_entity_config_role_specific_missing_profile_flagged(self):
        """A role-specific mapping pointing at a missing profile is flagged."""
        role = self._ensure_team_role("BRPMS Helper")
        valid_profile = self._make_role_profile("EntityRSValid")
        team = self._make_team(enable_role_specific_profiles=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": valid_profile})
        team_doc.save()
        # Corrupt the saved mapping to reference a ghost profile.
        row = frappe.get_all(
            "Team Role Profile Assignment", filters={"parent": team}, fields=["name"], limit=1
        )
        self.assertTrue(row)
        frappe.db.set_value("Team Role Profile Assignment", row[0].name, "role_profile", "Ghost Profile ZZZ")

        result = brpm.validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Ghost Profile ZZZ", result["error"])

    # ----------------------------------------- get_entities_using_role_profile

    def test_entities_using_role_profile_role_specific(self):
        """A profile used only via a role-specific mapping is reported with that usage_type."""
        profile = self._make_role_profile("UsingRS")
        role = self._ensure_team_role("BRPMS Lead")
        team = self._make_team(enable_role_specific_profiles=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": profile})
        team_doc.save()

        result = self.team_manager.get_entities_using_role_profile(profile)
        names = {r["name"] for r in result}
        self.assertIn(team, names)
        usage_types = {r["usage_type"] for r in result if r["name"] == team}
        self.assertTrue(any(u.startswith("role_specific") for u in usage_types))

    def test_entities_using_role_profile_default(self):
        """A profile used as a team default is reported with usage_type 'default'."""
        profile = self._make_role_profile("UsingDefault")
        team = self._make_team(default_role_profile=profile)
        result = self.team_manager.get_entities_using_role_profile(profile)
        names = {r["name"] for r in result}
        self.assertIn(team, names)
        self.assertIn("default", {r["usage_type"] for r in result if r["name"] == team})

    # ------------------------------------------------------- safe_hook_execution

    def test_safe_hook_execution_returns_result(self):
        self.assertEqual(brpm.safe_hook_execution(lambda a, b: a + b, 2, 3), 5)

    def test_safe_hook_execution_swallows_errors(self):
        def boom():
            raise RuntimeError("kaboom")

        # Error-isolated: returns None rather than propagating.
        self.assertIsNone(brpm.safe_hook_execution(boom))

    # --------------------------------------------- _is_system_operation_authorized

    def test_is_system_operation_authorized_as_administrator(self):
        # setUp runs as Administrator → authorized.
        self.assertTrue(brpm._is_system_operation_authorized())


class TestApplicationHelpersSupplement(EnhancedTestCase):
    """Cover application_helpers functions missed by test_application_helpers_coverage."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    # --------------------------------------------------------------- get_form_data

    def test_get_form_data_returns_form_payload(self):
        """get_form_data assembles a dict with membership_types and chapters keys."""
        with self.assertNoErrorLog():
            result = ah.get_form_data()
        self.assertIsInstance(result, dict)
        # The payload always carries membership types and chapters lists.
        self.assertIn("membership_types", result)
        self.assertIn("chapters", result)
        self.assertIsInstance(result["membership_types"], list)

    # ------------------------------------------------ _get_membership_type_currency

    def test_currency_explicit_on_membership_type(self):
        mt = self.create_test_membership_type(amount=50.0)
        mt.currency = "USD"
        self.assertEqual(ah._get_membership_type_currency(mt), "USD")

    def test_currency_falls_back_to_company_default(self):
        """No explicit currency → derived from Verenigingen Settings company default."""
        mt = self.create_test_membership_type(amount=50.0)
        # Ensure no explicit currency so the company-default branch runs.
        if hasattr(mt, "currency"):
            mt.currency = None
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        expected = frappe.db.get_value("Company", company, "default_currency")
        self.assertEqual(ah._get_membership_type_currency(mt), expected)

    # ---------------------------------- activate / create_active chapter membership

    def _make_member(self):
        return self.create_test_member(
            first_name="Chap",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=f"chap.{frappe.generate_hash(length=8)}@test.invalid",
        )

    def test_activate_pending_falls_back_to_create_active(self):
        """No pending record for the member → activate path creates an Active record."""
        member = self._make_member()
        chapter = self.create_test_chapter()

        with self.assertNoErrorLog():
            result = ah.activate_pending_chapter_membership(member, chapter.name)

        self.assertIsNotNone(result)
        cm = frappe.db.get_value("Chapter Member", {"member": member.name, "parent": chapter.name}, "status")
        self.assertEqual(cm, "Active")

    def test_activate_pending_record_transitions_to_active(self):
        """An existing Pending record is flipped to Active by the activate path."""
        member = self._make_member()
        chapter = self.create_test_chapter()
        # Seed a Pending record first.
        ah.create_pending_chapter_membership(member, chapter.name)
        status = frappe.db.get_value(
            "Chapter Member", {"member": member.name, "parent": chapter.name}, "status"
        )
        self.assertEqual(status, "Pending")

        with self.assertNoErrorLog():
            ah.activate_pending_chapter_membership(member, chapter.name)

        status = frappe.db.get_value(
            "Chapter Member", {"member": member.name, "parent": chapter.name}, "status"
        )
        self.assertEqual(status, "Active")

    def test_create_active_updates_existing_pending(self):
        """create_active on a chapter that already has a Pending row flips it to Active."""
        member = self._make_member()
        chapter = self.create_test_chapter()
        ah.create_pending_chapter_membership(member, chapter.name)

        with self.assertNoErrorLog():
            result = ah.create_active_chapter_membership(member, chapter.name)

        self.assertIsNotNone(result)
        status = frappe.db.get_value(
            "Chapter Member", {"member": member.name, "parent": chapter.name}, "status"
        )
        self.assertEqual(status, "Active")
        # No duplicate row created.
        self.assertEqual(
            frappe.db.count("Chapter Member", {"member": member.name, "parent": chapter.name}), 1
        )

    def test_create_active_nonexistent_chapter_returns_none(self):
        member = self._make_member()
        # The function logs a "Chapter Not Found" Error Log then returns None;
        # register it as expected so the automatic tearDown check ignores it.
        self.expectErrorLog("Chapter Not Found")
        self.assertIsNone(ah.create_active_chapter_membership(member, "No Such Chapter ZZZ"))

    def test_activate_pending_none_inputs_return_none(self):
        self.assertIsNone(ah.activate_pending_chapter_membership(None, "x"))
        member = self._make_member()
        self.assertIsNone(ah.activate_pending_chapter_membership(member, None))
