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
    def test_addresses_redirects_to_my_addresses(self):
        from verenigingen.templates.pages import addresses

        context = frappe._dict()
        with self.assertNoErrorLog():
            addresses.get_context(context)
        self.assertEqual(frappe.local.response.get("type"), "redirect")
        self.assertEqual(frappe.local.response.get("location"), "/my_addresses")

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

    def test_generate_test_data_admin_allowed(self):
        from verenigingen.templates.pages import generate_test_data

        context = frappe._dict()
        with self.assertNoErrorLog():
            generate_test_data.get_context(context)
        self.assertEqual(context.title, "Generate Test Data")
        self.assertTrue(context.description)

    def test_generate_test_data_guest_denied(self):
        from verenigingen.templates.pages import generate_test_data

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                generate_test_data.get_context(frappe._dict())

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


class TestWorkflowDemoPage(EnhancedTestCase):
    """workflow_demo.get_context + the two @whitelist workflow helpers."""

    def setUp(self):
        super().setUp()
        # execute_workflow_action is @standard_api(MEMBER_DATA) -> HIGH security,
        # gated to the DEVELOPMENT environment via frappe.conf.developer_mode; a
        # sibling shard test can leave the (shared, non-transactional) flag off,
        # making the endpoint raise a production-environment PermissionError.
        # Force it on, restore in tearDown.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        self.member = self.create_test_member(
            first_name="Workflow", last_name="Demo", birth_date="1990-01-01"
        )

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def test_get_context_as_admin(self):
        from verenigingen.templates.pages import workflow_demo

        context = frappe._dict()
        with self.assertNoErrorLog():
            workflow_demo.get_context(context)
        self.assertTrue(context.title)
        # workflow_exists is a bool either way; sample_members + stats present
        self.assertIn("workflow_exists", context)
        self.assertIsInstance(context.sample_members, list)
        if context.workflow_exists:
            self.assertIsInstance(context.workflow_states, list)
            self.assertIsInstance(context.workflow_transitions, list)
            self.assertIsInstance(context.workflow_stats, dict)

    def test_get_context_guest_denied(self):
        from verenigingen.templates.pages import workflow_demo

        with self.as_user("Guest"):
            with self.assertRaises(frappe.ValidationError):
                workflow_demo.get_context(frappe._dict())

    def test_get_workflow_actions_returns_dict(self):
        from verenigingen.templates.pages import workflow_demo

        with self.assertNoErrorLog():
            result = workflow_demo.get_workflow_actions(self.member.name)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        if result.get("success"):
            self.assertEqual(result["current_state"], self.member.application_status)
            self.assertIsInstance(result["available_actions"], list)

    def test_get_workflow_actions_unknown_member(self):
        from verenigingen.templates.pages import workflow_demo

        # get_doc on a missing member raises inside the try → caught → success False
        with self.assertNoErrorLog():
            result = workflow_demo.get_workflow_actions("NON-EXISTENT-MEMBER-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_execute_workflow_action_updates_status(self):
        from verenigingen.templates.pages import workflow_demo

        old_status = self.member.application_status
        new_status = "Under Review" if old_status != "Under Review" else "Approved"
        with self.assertNoErrorLog():
            result = workflow_demo.execute_workflow_action(
                self.member.name, action="Review", next_state=new_status
            )
        # The controller writes application_status = next_state then saves; the
        # save may trigger downstream member hooks that advance the status
        # further, so we only assert on the controller's own reported transition
        # and that the member status actually changed away from the old value.
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["old_state"], old_status)
        self.assertEqual(result["new_state"], new_status)
        self.member.reload()
        self.assertNotEqual(self.member.application_status, old_status)


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
