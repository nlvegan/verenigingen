"""
Integration tests for a cluster of member-portal web-page controllers in
verenigingen/templates/pages/.

These exercise each page's get_context() (and the whitelisted helpers the
templates call) against REAL data built by the Enhanced Test Factory, covering
the happy path plus the guard / error / permission branches.

Pages covered:
  - my_addresses.py
  - application_status.py
  - my_teams.py
  - apply_for_membership.py
  - membership_application.py
  - personal_details.py
  - my_dues_schedule.py
  - address_change.py
  - membership_adjustment.py
  - member_portal.py
"""

import frappe
from frappe.utils import now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class PortalPageTestBase(EnhancedTestCase):
    """Shared helpers: a member with a linked, role-bearing User account."""

    def setUp(self):
        super().setUp()
        # Several portal endpoints under test are gated to the DEVELOPMENT
        # environment by the API security framework, which reads
        # frappe.conf.developer_mode. A sibling test in the same shard can leave
        # developer_mode toggled off (it's a shared, non-transactional flag), so
        # the gate then raises "Function not available in production environment".
        # Force it on for these tests (save/restore the raw key — frappe.conf is a
        # frappe._dict, so patch.object does not work on it).
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def _make_member_with_user(self, first_name="Portal", last_name="User"):
        """Create a Member linked to a real User (member resolved from session)."""
        member = self.create_test_member(
            first_name=first_name,
            last_name=last_name,
            email=f"portal-{now_datetime().strftime('%H%M%S%f')}@example.com",
            birth_date="1990-01-01",
        )
        # Factory appends a uniqueness suffix; read back the persisted email.
        member.reload()
        email = member.email
        user = self._ensure_member_user(email, first_name, last_name)
        member.db_set("user", email)
        frappe.db.commit()
        return member, user

    def _ensure_member_user(self, email, first_name="Portal", last_name="User"):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", email)
        return email


class TestPageMyAddresses(PortalPageTestBase):
    """verenigingen.templates.pages.my_addresses"""

    def test_no_member_record_returns_graceful_context(self):
        from verenigingen.templates.pages import my_addresses

        # A logged-in user with NO member record.
        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)

        with self.as_user(email):
            ctx = frappe._dict()
            my_addresses.get_context(ctx)

        self.assertTrue(ctx.no_member_record)
        self.assertEqual(ctx.title, "My Addresses")
        # Early return: no member/address keys set.
        self.assertNotIn("current_address", ctx)

    def test_member_without_address(self):
        from verenigingen.templates.pages import my_addresses

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            my_addresses.get_context(ctx)

        self.assertEqual(ctx.member.name, member.name)
        self.assertIsNone(ctx.current_address)
        self.assertIsNone(ctx.address_display)
        self.assertEqual(ctx.page_title, "My Addresses")

    def test_member_with_address_formats_display(self):
        from verenigingen.templates.pages import my_addresses

        member, user = self._make_member_with_user()
        address = self.factory.create_address(
            address_line1="Teststraat 1",
            city="Amsterdam",
            pincode="1011 AB",
            link_doctype="Member",
            link_name=member.name,
        )
        member.db_set("primary_address", address.name)

        with self.as_user(user):
            ctx = frappe._dict()
            my_addresses.get_context(ctx)

        self.assertEqual(ctx.current_address.name, address.name)
        self.assertIsNotNone(ctx.address_display)


class TestPageApplicationStatus(PortalPageTestBase):
    """verenigingen.templates.pages.application_status"""

    def test_logged_in_member_resolved_from_session(self):
        from verenigingen.templates.pages import application_status

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            application_status.get_context(ctx)

        self.assertIsNotNone(ctx.member)
        self.assertEqual(ctx.member.name, member.name)
        self.assertEqual(ctx.title, "Application Status")
        self.assertIsInstance(ctx.member_chapters, list)

    def test_member_id_from_form_dict(self):
        from verenigingen.templates.pages import application_status

        member, user = self._make_member_with_user()
        original = frappe.form_dict
        try:
            frappe.form_dict = frappe._dict({"id": member.name})
            with self.as_user(user):
                ctx = frappe._dict()
                application_status.get_context(ctx)
        finally:
            frappe.form_dict = original

        self.assertEqual(ctx.member.name, member.name)

    def test_no_member_yields_empty_context(self):
        from verenigingen.templates.pages import application_status

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            application_status.get_context(ctx)

        self.assertIsNone(ctx.member)
        self.assertEqual(ctx.member_chapters, [])


class TestPageMyTeams(PortalPageTestBase):
    """verenigingen.templates.pages.my_teams"""

    def test_member_without_volunteer(self):
        from verenigingen.templates.pages import my_teams

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            my_teams.get_context(ctx)

        self.assertEqual(ctx.title, "My Teams")
        self.assertIsNone(ctx.volunteer)
        self.assertEqual(ctx.teams, [])

    def test_volunteer_with_active_team_membership(self):
        from verenigingen.templates.pages import my_teams

        member, user = self._make_member_with_user()
        volunteer = self.create_test_volunteer(member_name=member.name)
        team = self.create_test_team(team_name="Test Team", status="Active")
        self.create_test_team_member(team.name, volunteer.name)

        with self.as_user(user):
            ctx = frappe._dict()
            my_teams.get_context(ctx)

        self.assertEqual(ctx.volunteer, volunteer.name)
        team_names = [t["info"].name for t in ctx.teams]
        self.assertIn(team.name, team_names)
        # can_view_members defaults True for any team member
        self.assertTrue(ctx.teams[0]["can_view_members"])


class TestPageApplyForMembership(PortalPageTestBase):
    """verenigingen.templates.pages.apply_for_membership

    This module builds the full public application context (brand content,
    step config, payment methods, skill categories, country list).
    """

    def test_guest_context_has_brand_and_steps(self):
        from verenigingen.templates.pages import apply_for_membership

        self.create_test_membership_type(membership_type_name="Standard")
        with self.as_user("Guest"):
            ctx = frappe._dict()
            apply_for_membership.get_context(ctx)

        self.assertFalse(ctx.already_member)
        self.assertTrue(ctx.page_title)
        self.assertIn(ctx.total_steps, (5, 6))
        self.assertIsInstance(ctx.available_countries, list)
        self.assertTrue(ctx.payment_methods)
        self.assertTrue(ctx.skill_categories)
        self.assertIsInstance(ctx.enhanced_membership_types, list)

    def test_existing_member_short_circuits(self):
        from verenigingen.templates.pages import apply_for_membership

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            apply_for_membership.get_context(ctx)

        self.assertTrue(ctx.already_member)
        self.assertEqual(ctx.member_name, member.name)

    def test_default_payment_methods(self):
        from verenigingen.templates.pages.apply_for_membership import get_payment_methods

        settings = frappe.get_single("Verenigingen Settings")
        # Defaults are sorted by display order.
        methods = get_payment_methods(settings)
        self.assertTrue(methods)
        orders = [m["order"] for m in methods]
        self.assertEqual(orders, sorted(orders))

    def test_default_skill_categories(self):
        from verenigingen.templates.pages.apply_for_membership import get_skill_categories

        settings = frappe.get_single("Verenigingen Settings")
        cats = get_skill_categories(settings)
        self.assertTrue(cats)
        names = [c["name"] for c in cats]
        self.assertTrue(any("Technical" in n for n in names))


class TestPageMembershipApplication(PortalPageTestBase):
    """verenigingen.templates.pages.membership_application

    The "enhanced" application page: a leaner context that exposes
    membership_types with contribution options, plus several whitelisted
    helpers used by the page JS.
    """

    def test_guest_gets_membership_types(self):
        from verenigingen.templates.pages import membership_application

        self.create_test_membership_type(membership_type_name="Standard")
        with self.as_user("Guest"):
            ctx = frappe._dict()
            membership_application.get_context(ctx)

        self.assertFalse(ctx.already_member)
        self.assertIsInstance(ctx.membership_types, list)
        self.assertIn("company_name", ctx.settings)

    def test_existing_member_short_circuits(self):
        from verenigingen.templates.pages import membership_application

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            membership_application.get_context(ctx)

        self.assertTrue(ctx.already_member)
        self.assertEqual(ctx.member_name, member.name)

    def test_get_membership_type_details_happy_and_missing(self):
        from verenigingen.templates.pages.membership_application import get_membership_type_details

        mt = self.create_test_membership_type(membership_type_name="Detail")
        ok = get_membership_type_details(mt.name)
        self.assertTrue(ok.get("success"))
        self.assertEqual(ok["membership_type"]["name"], mt.name)

        self.assertIn("error", get_membership_type_details(""))
        self.assertIn("error", get_membership_type_details("Does Not Exist XYZ"))

    def test_get_dues_schedules_validation(self):
        from verenigingen.templates.pages.membership_application import (
            get_dues_schedules_for_membership_type,
        )

        # Missing input
        self.assertFalse(get_dues_schedules_for_membership_type("").get("success"))
        # Over-long input
        self.assertFalse(get_dues_schedules_for_membership_type("x" * 200).get("success"))
        # Nonexistent
        self.assertFalse(get_dues_schedules_for_membership_type("Nope XYZ").get("success"))


class TestPagePersonalDetails(PortalPageTestBase):
    """verenigingen.templates.pages.personal_details"""

    def test_no_member_record(self):
        from verenigingen.templates.pages import personal_details

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            personal_details.get_context(ctx)
        self.assertTrue(ctx.no_member_record)

    def test_context_with_member_no_address(self):
        from verenigingen.templates.pages import personal_details

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            personal_details.get_context(ctx)

        self.assertEqual(ctx.member.name, member.name)
        self.assertIsNone(ctx.current_address)
        # No address -> Netherlands default and JSON serializable.
        self.assertEqual(ctx.address_data["country"], "Netherlands")
        self.assertIn("Netherlands", ctx.address_data_json)
        self.assertEqual(ctx.active_tab, "personal")

    def test_active_tab_from_form_dict(self):
        from verenigingen.templates.pages import personal_details

        member, user = self._make_member_with_user()
        original = frappe.form_dict
        try:
            frappe.form_dict = frappe._dict({"tab": "contact"})
            with self.as_user(user):
                ctx = frappe._dict()
                personal_details.get_context(ctx)
        finally:
            frappe.form_dict = original
        self.assertEqual(ctx.active_tab, "contact")

    def test_invalid_tab_falls_back_to_personal(self):
        from verenigingen.templates.pages import personal_details

        member, user = self._make_member_with_user()
        original = frappe.form_dict
        try:
            frappe.form_dict = frappe._dict({"tab": "bogus"})
            with self.as_user(user):
                ctx = frappe._dict()
                personal_details.get_context(ctx)
        finally:
            frappe.form_dict = original
        self.assertEqual(ctx.active_tab, "personal")

    def test_validators(self):
        from verenigingen.templates.pages.personal_details import (
            validate_name_format,
            validate_phone_number,
            validate_pronouns,
        )

        self.assertTrue(validate_name_format("Jan"))
        self.assertFalse(validate_name_format("Jan123"))
        self.assertTrue(validate_name_format("van der", allow_prefixes=True))
        self.assertTrue(validate_phone_number("+31 6 12345678"))
        self.assertFalse(validate_phone_number("abc"))
        self.assertTrue(validate_pronouns("she/her"))
        self.assertFalse(validate_pronouns("she@her"))

    def test_track_changes_detects_diff(self):
        from verenigingen.templates.pages.personal_details import track_changes

        member, _user = self._make_member_with_user(first_name="Old")
        changes = track_changes(member, {"first_name": "New", "last_name": member.last_name})
        self.assertIn("first_name", changes)
        self.assertNotIn("last_name", changes)

    def test_update_personal_details_changes_name(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        member, user = self._make_member_with_user(first_name="Before")
        # A real portal member editing their details is already onboarded. The
        # factory leaves application_status in the workflow's initial "Pending"
        # state while status is "Active"; saving the doc would otherwise have a
        # Member hook reconcile that to "Approved", which the member-user is not
        # allowed to transition (Membership Application Workflow). Align it to the
        # terminal "Active" state first so the self-edit is a no-op transition.
        member.db_set("application_status", "Active")
        with self.as_user(user):
            # last_name must be clean alpha (the factory appends a digit
            # suffix to the seeded last name, which the validator rejects).
            frappe.local.form_dict = frappe._dict({"first_name": "After", "last_name": "Vandenberg"})
            try:
                update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        member.reload()
        self.assertEqual(member.first_name, "After")
        self.assertEqual(member.last_name, "Vandenberg")
        # Redirect response set.
        self.assertEqual(frappe.local.response.get("type"), "redirect")

    def test_update_personal_details_rejects_tampering(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        member, user = self._make_member_with_user()
        with self.as_user(user):
            frappe.local.form_dict = frappe._dict(
                {
                    "member": "Some-Other-Member",
                    "first_name": "X",
                    "last_name": "Y",
                }
            )
            try:
                with self.assertRaises(frappe.PermissionError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_update_personal_details_requires_first_name(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        member, user = self._make_member_with_user()
        with self.as_user(user):
            frappe.local.form_dict = frappe._dict({"first_name": "", "last_name": "Y"})
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()


class TestPageMyDuesSchedule(PortalPageTestBase):
    """verenigingen.templates.pages.my_dues_schedule"""

    def test_no_member_record(self):
        from verenigingen.templates.pages import my_dues_schedule

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            my_dues_schedule.get_context(ctx)
        self.assertTrue(ctx.no_member_record)

    def test_context_for_member_without_schedule(self):
        from verenigingen.templates.pages import my_dues_schedule

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            my_dues_schedule.get_context(ctx)

        self.assertEqual(ctx.member, member.name)
        self.assertIsNone(ctx.current_schedule)
        # No schedule -> payment method left unset/None.
        self.assertIsNone(ctx.payment_method)
        # Coverage falls back to zero with no schedule.
        self.assertEqual(ctx.coverage_percentage, 0)
        self.assertEqual(ctx.total_months, 12)
        self.assertTrue(ctx.calendar_month)

    def test_calendar_data(self):
        from verenigingen.templates.pages.my_dues_schedule import get_calendar_data

        data = get_calendar_data()
        self.assertIn(data["month_num"], range(1, 13))
        self.assertTrue(data["month_name"])

    def test_coverage_info_no_schedule(self):
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        member, _user = self._make_member_with_user()
        info = get_coverage_info(member.name, None)
        self.assertEqual(info["percentage"], 0)
        self.assertEqual(info["total_months"], 12)

    def test_export_schedule_sets_download_response(self):
        from verenigingen.templates.pages.my_dues_schedule import export_schedule

        member, user = self._make_member_with_user()
        with self.as_user(user):
            try:
                export_schedule()
                self.assertEqual(frappe.response.get("type"), "download")
                self.assertTrue(frappe.response.get("filename", "").endswith(".csv"))
                self.assertIn("Date", frappe.response.get("filecontent", ""))
            finally:
                for key in ("type", "filename", "filecontent"):
                    frappe.response.pop(key, None)

    def test_get_payment_details_not_found_raises(self):
        from verenigingen.templates.pages.my_dues_schedule import get_payment_details

        member, user = self._make_member_with_user()
        with self.as_user(user):
            with self.assertRaises(frappe.DoesNotExistError):
                get_payment_details("1900-01-01")


class TestPageAddressChange(PortalPageTestBase):
    """verenigingen.templates.pages.address_change"""

    def test_no_member_record(self):
        from verenigingen.templates.pages import address_change

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            address_change.get_context(ctx)
        self.assertTrue(ctx.no_member_record)

    def test_context_with_member(self):
        from verenigingen.templates.pages import address_change

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            address_change.get_context(ctx)

        self.assertEqual(ctx.member.name, member.name)
        self.assertEqual(ctx.address_data["country"], "Netherlands")
        self.assertTrue(ctx.countries)
        self.assertTrue(ctx.portal_links)
        self.assertEqual(ctx.page_title, "Update Address")

    def test_get_current_address_none(self):
        from verenigingen.templates.pages.address_change import get_current_address

        member, user = self._make_member_with_user()
        with self.as_user(user):
            result = get_current_address()
        self.assertIsNone(result["address"])

    def test_update_member_address_creates_then_reads(self):
        from verenigingen.templates.pages.address_change import (
            get_current_address,
            update_member_address,
        )

        member, user = self._make_member_with_user()
        payload = {
            "address_line1": "Nieuwstraat 5",
            "city": "Utrecht",
            "country": "Netherlands",
            "pincode": "3511 AA",
        }
        with self.as_user(user):
            result = update_member_address(payload)
            self.assertTrue(result["success"])
            self.assertEqual(result["action"], "created")

            current = get_current_address()
            self.assertIsNotNone(current["address"])
            self.assertEqual(current["address"]["city"], "Utrecht")

        member.reload()
        self.assertEqual(member.primary_address, result["address_name"])

    def test_update_member_address_missing_required(self):
        from verenigingen.templates.pages.address_change import update_member_address

        member, user = self._make_member_with_user()
        with self.as_user(user):
            with self.assertRaises(frappe.ValidationError):
                update_member_address({"city": "Utrecht", "country": "Netherlands"})

    def test_update_member_address_invalid_email(self):
        from verenigingen.templates.pages.address_change import update_member_address

        member, user = self._make_member_with_user()
        with self.as_user(user):
            with self.assertRaises(frappe.ValidationError):
                update_member_address(
                    {
                        "address_line1": "Straat 1",
                        "city": "Utrecht",
                        "country": "Netherlands",
                        "email_id": "not-an-email",
                    }
                )


class TestPageMemberPortal(PortalPageTestBase):
    """verenigingen.templates.pages.member_portal"""

    def test_no_member_record(self):
        from verenigingen.templates.pages import member_portal

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            member_portal.get_context(ctx)
        self.assertTrue(ctx.no_member_record)
        self.assertTrue(ctx.error_title)

    def test_full_context_for_member(self):
        from verenigingen.templates.pages import member_portal

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            member_portal.get_context(ctx)

        self.assertFalse(ctx.no_member_record)
        self.assertEqual(ctx.member.name, member.name)
        self.assertIsNone(ctx.volunteer)
        self.assertEqual(ctx.volunteer_hours, 0)
        self.assertIsInstance(ctx.recent_activity, list)
        self.assertIsInstance(ctx.quick_actions, list)
        self.assertTrue(ctx.quick_actions)  # always has Payment Dashboard etc.
        self.assertIsInstance(ctx.chapters_info, list)
        self.assertIn("is_board_member", ctx)

    def test_volunteer_member_gets_teams_and_dashboard_action(self):
        from verenigingen.templates.pages import member_portal

        member, user = self._make_member_with_user()
        volunteer = self.create_test_volunteer(member_name=member.name)

        with self.as_user(user):
            ctx = frappe._dict()
            member_portal.get_context(ctx)

        self.assertIsNotNone(ctx.volunteer)
        self.assertEqual(ctx.volunteer.name, volunteer.name)
        titles = [a["title"] for a in ctx.quick_actions]
        self.assertIn("Volunteer Dashboard", titles)

    def test_quick_actions_always_present(self):
        from verenigingen.templates.pages.member_portal import get_quick_actions

        member, _user = self._make_member_with_user()
        member_doc = frappe.get_doc("Member", member.name)
        actions = get_quick_actions(member_doc, None, None)
        titles = [a["title"] for a in actions]
        self.assertIn("Payment Dashboard", titles)
        self.assertIn("Contact Support", titles)


class TestPageMembershipAdjustment(PortalPageTestBase):
    """verenigingen.templates.pages.membership_adjustment"""

    def _member_with_active_membership(self):
        member, user = self._make_member_with_user()
        mt = self.create_test_membership_type(membership_type_name="Adj", minimum_amount=10.0)
        membership = self.create_test_membership(member_name=member.name, membership_type_name=mt.name)
        # Ensure submitted/active so get_context finds it.
        membership.reload()
        if membership.docstatus == 0:
            membership.submit()
        if membership.status != "Active":
            membership.db_set("status", "Active")
        frappe.db.commit()
        return member, user, mt, membership

    def test_no_member_record(self):
        from verenigingen.templates.pages import membership_adjustment

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            ctx = frappe._dict()
            membership_adjustment.get_context(ctx)
        self.assertTrue(ctx.no_member_record)

    def test_no_active_membership_raises(self):
        from verenigingen.templates.pages import membership_adjustment

        member, user = self._make_member_with_user()
        with self.as_user(user):
            ctx = frappe._dict()
            with self.assertRaises(frappe.DoesNotExistError):
                membership_adjustment.get_context(ctx)

    def test_context_with_active_membership(self):
        from verenigingen.templates.pages import membership_adjustment

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            ctx = frappe._dict()
            membership_adjustment.get_context(ctx)

        self.assertEqual(ctx.member.name, member.name)
        self.assertEqual(ctx.membership.name, membership.name)
        self.assertGreater(ctx.standard_fee, 0)
        self.assertGreaterEqual(ctx.minimum_fee, 5.0)
        self.assertIn("enable_member_fee_adjustment", ctx.settings)
        self.assertIsInstance(ctx.pending_requests, list)
        self.assertIn("can_adjust_fee", ctx)

    def test_fee_adjustment_settings_defaults(self):
        from verenigingen.templates.pages.membership_adjustment import get_fee_adjustment_settings

        settings = get_fee_adjustment_settings()
        self.assertIn("max_adjustments_per_year", settings)
        self.assertIn("enable_member_fee_adjustment", settings)

    def test_can_member_adjust_fee_disabled(self):
        from verenigingen.templates.pages.membership_adjustment import can_member_adjust_fee

        member, _user = self._make_member_with_user()
        member_doc = frappe.get_doc("Member", member.name)
        ok, msg = can_member_adjust_fee(member_doc, {"enable_member_fee_adjustment": 0})
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_get_minimum_fee_respects_floor(self):
        from verenigingen.templates.pages.membership_adjustment import get_minimum_fee

        member, _user = self._make_member_with_user()
        mt = self.create_test_membership_type(membership_type_name="Floor", minimum_amount=2.0)
        member_doc = frappe.get_doc("Member", member.name)
        mt_doc = frappe.get_doc("Membership Type", mt.name)
        # Absolute €5 floor enforced regardless of low membership minimum.
        self.assertGreaterEqual(get_minimum_fee(member_doc, mt_doc), 5.0)

    def test_submit_fee_adjustment_no_member(self):
        from verenigingen.templates.pages.membership_adjustment import submit_fee_adjustment_request

        email = f"nomember-{now_datetime().strftime('%H%M%S%f')}@example.com"
        self._ensure_member_user(email)
        with self.as_user(email):
            with self.assertRaises(frappe.ValidationError):
                submit_fee_adjustment_request(20.0, reason="test")

    def test_submit_fee_adjustment_below_minimum(self):
        from verenigingen.templates.pages.membership_adjustment import submit_fee_adjustment_request

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            with self.assertRaises(frappe.ValidationError):
                submit_fee_adjustment_request(0.5, reason="too low")

    def test_get_available_membership_types(self):
        from verenigingen.templates.pages.membership_adjustment import get_available_membership_types

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            result = get_available_membership_types()
        self.assertEqual(result["current_type"], mt.name)
        self.assertTrue(result["membership_types"])

    def test_submit_membership_type_change_same_type_rejected(self):
        from verenigingen.templates.pages.membership_adjustment import (
            submit_membership_type_change_request,
        )

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            with self.assertRaises(frappe.ValidationError):
                submit_membership_type_change_request(mt.name, reason="same")

    def test_submit_membership_type_change_invalid_type(self):
        from verenigingen.templates.pages.membership_adjustment import (
            submit_membership_type_change_request,
        )

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            with self.assertRaises(frappe.ValidationError):
                submit_membership_type_change_request("Bogus Type XYZ", reason="x")

    def test_get_fee_calculation_info(self):
        from verenigingen.templates.pages.membership_adjustment import get_fee_calculation_info

        member, user, mt, membership = self._member_with_active_membership()
        with self.as_user(user):
            info = get_fee_calculation_info()
        self.assertIn("standard_fee", info)
        self.assertIn("minimum_fee", info)
        self.assertIn("membership_type", info)
        self.assertIsInstance(info["fee_history"], list)
