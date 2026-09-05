"""
Coverage tests for the small / previously-untested portal page controllers under
verenigingen.templates.pages.

These controllers are mostly thin: redirect pages, permission-gated context
builders, and a couple of @whitelist helpers. They had 0% (or near-0%) coverage
before this file. Each test calls the real get_context()/helper with a real
frappe._dict() context and asserts on the populated data, exercising both the
permission-allowed (Administrator) and permission-denied branches where relevant.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSimplePortalControllers(EnhancedTestCase):
    """Smoke + branch coverage for the thin portal controllers."""

    # ------------------------------------------------------------------ #
    # Redirect controllers
    # ------------------------------------------------------------------ #
    # templates/pages/addresses.py was deleted: Frappe's router only registers routes for
    # html/xml/js/css/md files (website/router.py::get_pages_from_path), so a .py-only page
    # never had a route - get_pages() has no "addresses" entry. It also used the RPC-style
    # frappe.local.response["type"], which does not redirect a page render at all (contrast
    # the sibling test below, which correctly expects frappe.Redirect). /addresses itself
    # still resolves: it is served by ERPNext's Web Form, not by that module.

    def test_financial_dashboard_redirects_to_payment_dashboard(self):
        from verenigingen.templates.pages import financial_dashboard

        context = frappe._dict()
        with self.assertNoErrorLog():
            with self.assertRaises(frappe.Redirect):
                financial_dashboard.get_context(context)
        self.assertEqual(frappe.local.flags.redirect_location, "/payment_dashboard")

    # ------------------------------------------------------------------ #
    # application_success - reads id / payment_url from form_dict
    # ------------------------------------------------------------------ #
    def test_application_success_context(self):
        from verenigingen.templates.pages import application_success

        frappe.local.form_dict.id = "MEMBER-0001"
        frappe.local.form_dict.payment_url = "https://pay.example.invalid/abc"
        try:
            context = frappe._dict()
            with self.assertNoErrorLog():
                application_success.get_context(context)
            self.assertEqual(context.member_id, "MEMBER-0001")
            self.assertEqual(context.payment_url, "https://pay.example.invalid/abc")
            self.assertEqual(context.no_cache, 1)
            self.assertFalse(context.show_sidebar)
            self.assertTrue(context.title)
        finally:
            frappe.local.form_dict.pop("id", None)
            frappe.local.form_dict.pop("payment_url", None)

    def test_application_success_context_no_params(self):
        from verenigingen.templates.pages import application_success

        context = frappe._dict()
        with self.assertNoErrorLog():
            application_success.get_context(context)
        self.assertIsNone(context.member_id)
        self.assertIsNone(context.payment_url)

    # ------------------------------------------------------------------ #
    # brand_css_disabled - emits minimal CSS, sets response headers
    # ------------------------------------------------------------------ #
    def test_brand_css_disabled_context(self):
        from verenigingen.templates.pages import brand_css_disabled

        context = frappe._dict()
        with self.assertNoErrorLog():
            brand_css_disabled.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertIn("--brand-primary", context.css_content)
        self.assertEqual(frappe.response.content_type, "text/css; charset=utf-8")
        self.assertIn("no-cache", frappe.response.headers["Cache-Control"])

    # ------------------------------------------------------------------ #
    # Permission-gated tool pages: allowed as Administrator
    # ------------------------------------------------------------------ #
    def test_auto_create_dues_schedules_admin_allowed(self):
        from verenigingen.templates.pages import auto_create_dues_schedules

        context = frappe._dict()
        with self.assertNoErrorLog():
            auto_create_dues_schedules.get_context(context)
        self.assertTrue(context.title)
        self.assertEqual(context.no_cache, 1)
        self.assertTrue(any(p.get("route") == "/tools" for p in context.parents))

    def test_auto_create_dues_schedules_guest_denied(self):
        from verenigingen.templates.pages import auto_create_dues_schedules

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                auto_create_dues_schedules.get_context(frappe._dict())

    def test_schedule_maintenance_admin_allowed(self):
        from verenigingen.templates.pages import schedule_maintenance

        context = frappe._dict()
        with self.assertNoErrorLog():
            schedule_maintenance.get_context(context)
        self.assertTrue(context.title)
        self.assertTrue(context.page_title)
        # Administrator can write+delete dues schedules
        self.assertTrue(context.can_cleanup)

    def test_schedule_maintenance_guest_denied(self):
        from verenigingen.templates.pages import schedule_maintenance

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                schedule_maintenance.get_context(frappe._dict())

    # generate_test_data was removed (#430): its core buttons posted to
    # verenigingen.api.generate_test_members.*, a module that never existed, so --
    # like /membership_application before it -- a passing get_context() test here
    # read as coverage for a page that could not do its job.
    #
    # eboekhouden_item_mapping was NOT removed, despite an earlier pass in this
    # same PR wrongly deleting it: its two calls were pointed at
    # verenigingen.api.eboekhouden_item_mapping_tool, but the module actually lives
    # at verenigingen.e_boekhouden.api.eboekhouden_item_mapping_tool -- the same
    # kind of stale-path bug the DD batch optimizer repoint two commits earlier
    # fixed correctly. Repointed instead; its tests stay below.

    # ------------------------------------------------------------------ #
    # eBoekhouden tool pages (permission-gated, build dropdown context)
    # ------------------------------------------------------------------ #
    def test_eboekhouden_item_mapping_admin_allowed(self):
        from verenigingen.templates.pages import eboekhouden_item_mapping

        context = frappe._dict()
        with self.assertNoErrorLog():
            eboekhouden_item_mapping.get_context(context)
        self.assertEqual(context.title, "E-Boekhouden Item Mapping Tool")
        # NOTE: "items" shadows dict.items, so read via subscript not attribute.
        self.assertIsInstance(context["items"], list)

    def test_eboekhouden_item_mapping_guest_denied(self):
        from verenigingen.templates.pages import eboekhouden_item_mapping

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                eboekhouden_item_mapping.get_context(frappe._dict())

    def test_eboekhouden_mapping_review_admin_allowed(self):
        from verenigingen.templates.pages import eboekhouden_mapping_review

        context = frappe._dict()
        with self.assertNoErrorLog():
            eboekhouden_mapping_review.get_context(context)
        self.assertEqual(context.title, "E-Boekhouden Account Review")
        # account_types is a hard-coded list matching ERPNext valid types
        self.assertIn("Bank", context.account_types)
        self.assertIn("Receivable", context.account_types)

    def test_eboekhouden_mapping_review_guest_denied(self):
        from verenigingen.templates.pages import eboekhouden_mapping_review

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                eboekhouden_mapping_review.get_context(frappe._dict())

    # ------------------------------------------------------------------ #
    # mt940_import - needs company configured in Verenigingen Settings
    # ------------------------------------------------------------------ #
    def test_mt940_import_admin_allowed(self):
        from verenigingen.templates.pages import mt940_import

        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if not company:
            self.skipTest("Verenigingen Settings.company not configured on this site")
        context = frappe._dict()
        with self.assertNoErrorLog():
            mt940_import.get_context(context)
        self.assertEqual(context.company, company)
        self.assertIsInstance(context.bank_accounts, list)
        self.assertTrue(context.title)

    def test_mt940_import_guest_denied(self):
        from verenigingen.templates.pages import mt940_import

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                mt940_import.get_context(frappe._dict())


class TestMyAddressesPage(EnhancedTestCase):
    """my_addresses.get_context for a member with/without a primary address."""

    def setUp(self):
        super().setUp()
        self.user_email = f"myaddr-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "MyAddr",
                    "last_name": "Member",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="MyAddr", last_name="Member", email=email, birth_date="1985-05-05"
        )
        member.db_set("user", email)
        return member

    def test_get_context_member_no_address(self):
        from verenigingen.templates.pages import my_addresses

        with self.as_user(self.user_email):
            context = frappe._dict()
            with self.assertNoErrorLog():
                my_addresses.get_context(context)
            # setup_portal_context resolves the member; no primary address yet
            self.assertEqual(context.current_address, None)
            self.assertEqual(context.address_display, None)
            self.assertEqual(context.page_title, "My Addresses")

    def test_get_context_member_with_address(self):
        from verenigingen.templates.pages import my_addresses

        address = self._make_address_for_member(self.member)
        with self.as_user(self.user_email):
            context = frappe._dict()
            with self.assertNoErrorLog():
                my_addresses.get_context(context)
            self.assertIsNotNone(context.current_address)
            self.assertEqual(context.current_address.name, address.name)
            self.assertIsNotNone(context.address_display)

    def _make_address_for_member(self, member):
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"{member.name}-home",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "pincode": "1011AB",
                "country": "Netherlands",
            }
        )
        address.insert(ignore_permissions=True)
        member.db_set("primary_address", address.name)
        member.reload()
        return address


class TestApplyForMembershipHelpers(EnhancedTestCase):
    """get_context + the pure helper functions of apply_for_membership."""

    def test_get_context_guest(self):
        from verenigingen.templates.pages import apply_for_membership

        with self.as_user("Guest"):
            context = frappe._dict()
            with self.assertNoErrorLog():
                apply_for_membership.get_context(context)
            self.assertFalse(context.already_member)
            self.assertTrue(context.title)
            self.assertIsInstance(context.payment_methods, list)
            self.assertGreaterEqual(context.total_steps, 5)
            self.assertIsInstance(context.available_countries, list)

    def test_get_payment_methods_defaults(self):
        from verenigingen.templates.pages import apply_for_membership

        settings = frappe.get_single("Verenigingen Settings")
        methods = apply_for_membership.get_payment_methods(settings)
        self.assertIsInstance(methods, list)
        self.assertTrue(methods)
        for m in methods:
            self.assertIn("value", m)
            self.assertIn("label", m)
            self.assertIn("order", m)

    def test_get_skill_categories_returns_list(self):
        from verenigingen.templates.pages import apply_for_membership

        settings = frappe.get_single("Verenigingen Settings")
        categories = apply_for_membership.get_skill_categories(settings)
        self.assertIsInstance(categories, list)
