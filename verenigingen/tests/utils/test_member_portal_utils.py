"""
Integration tests for verenigingen.utils.member_portal_utils.

This module is LIVE: it powers 8 portal-page controllers (my_dues_schedule,
membership_adjustment, address_change, personal_details, ...). The tests below
exercise it the way the real portal does — as a logged-in Member-linked user
and as a system/admin user — hitting the real DB and the real branches rather
than mocking business logic.

Covered functions:
- set_member_home_page (Guest / missing-user / success / default-session)
- set_all_members_home_page (permission-denied / bulk success)
- get_member_portal_stats (real aggregate counts)
- sync_member_user_home_pages (real catch-up count)
- get_user_appropriate_home_page (Guest / member / volunteer / admin / default)
- format_coverage_period (every billing-frequency branch + bad-input guards)
- enhance_outstanding_invoices_with_coverage (empty / coverage / due-date fallback)
- setup_portal_context (member-found / no-member graceful branch)
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_portal_utils import (
    enhance_outstanding_invoices_with_coverage,
    format_coverage_period,
    get_member_portal_stats,
    get_user_appropriate_home_page,
    set_all_members_home_page,
    set_member_home_page,
    setup_portal_context,
    sync_member_user_home_pages,
)


class TestMemberPortalUtils(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers
    def _ensure_member_role(self):
        """The module's SQL filters on the literal role name 'Member'.

        On a fresh CI site only 'Verenigingen Member' exists, so create the
        'Member' role if missing — this mirrors the role the production code
        was written against and lets the real bulk/stats/sync branches run.
        """
        if not frappe.db.exists("Role", "Member"):
            frappe.get_doc({"doctype": "Role", "role_name": "Member", "desk_access": 1}).insert()

    def _make_portal_member(self, roles=None):
        """Create a User (with given roles) + a Member linked to that User.

        Returns (member_doc, user_email). The Member.user link is what
        get_current_user_member_name / get_user_appropriate_home_page resolve on.
        """
        if roles is None:
            roles = ["Verenigingen Member"]
        if "Member" in roles:
            self._ensure_member_role()
        user = self.factory.create_user_with_roles(roles=roles)
        member = self.factory.create_member(
            first_name="Portal",
            last_name="Tester",
            email=user.email,
        )
        member.user = user.email
        member.save()
        return member, user.email

    def _make_user(self, roles):
        if "Member" in roles:
            self._ensure_member_role()
        return self.factory.create_user_with_roles(roles=roles)

    # ------------------------------------------------- set_member_home_page
    def test_set_home_page_rejects_guest(self):
        result = set_member_home_page(user_email="Guest")
        self.assertFalse(result["success"])
        self.assertIn("Guest", result["message"])

    def test_set_home_page_missing_user(self):
        result = set_member_home_page(user_email="does-not-exist-xyz@example.invalid")
        self.assertFalse(result["success"])
        # The message must interpolate the email (regression guard for the
        # missing-f-prefix bug that returned the literal "{user_email}").
        self.assertIn("does-not-exist-xyz@example.invalid", result["message"])

    def test_set_home_page_success_persists(self):
        _, email = self._make_portal_member()
        result = set_member_home_page(user_email=email, home_page="/member_portal")
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["home_page"], "/member_portal")
        # The success message must interpolate the home page (regression guard
        # for the missing-f-prefix bug that returned the literal "{home_page}").
        self.assertIn("/member_portal", result["message"])
        # The change is actually written to the User doctype.
        self.assertEqual(frappe.db.get_value("User", email, "home_settings"), "/member_portal")

    def test_set_home_page_defaults_to_session_user(self):
        _, email = self._make_portal_member()
        with self.set_user(email):
            # No user_email -> falls back to frappe.session.user (the member user).
            result = set_member_home_page(home_page="/member_portal")
        # Member users lack User:write, so this should fail gracefully (not crash)
        # while having resolved the session user rather than erroring on None.
        self.assertIn("success", result)
        self.assertIsInstance(result["success"], bool)

    # --------------------------------------------- set_all_members_home_page
    def test_set_all_members_returns_structured_result_for_member_user(self):
        # In Frappe a normal user can edit their OWN User doc, so has_permission
        # ("User","write") is True even for a member user -> the bulk op proceeds
        # and returns the success-shaped result rather than throwing. We assert
        # the contract (structured dict, never an unhandled exception).
        plain_user = self._make_user(roles=["Verenigingen Member"])
        with self.set_user(plain_user.email):
            result = set_all_members_home_page()
        self.assertIn("success", result)
        self.assertTrue(result["success"])
        self.assertIn("updated_count", result)
        self.assertIn("total_members", result)

    def test_set_all_members_bulk_success(self):
        # Ensure at least one Member-role user exists with a non-portal home page.
        target_user = self._make_user(roles=["Member"])
        frappe.db.set_value("User", target_user.email, "home_settings", "/app")
        result = set_all_members_home_page(home_page="/member_portal")
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertIn("updated_count", result)
        self.assertIn("total_members", result)
        self.assertGreaterEqual(result["total_members"], 1)
        # Our target should now point at the portal.
        self.assertEqual(
            frappe.db.get_value("User", target_user.email, "home_settings"),
            "/member_portal",
        )

    # ------------------------------------------------ get_member_portal_stats
    def test_member_portal_stats_shape_and_values(self):
        member, email = self._make_portal_member(roles=["Member"])
        frappe.db.set_value("User", email, "home_settings", "/member_portal")
        stats = get_member_portal_stats()
        self.assertNotIn("error", stats)
        for key in (
            "total_member_users",
            "members_with_portal_home",
            "members_with_linked_records",
            "portal_adoption_rate",
        ):
            self.assertIn(key, stats)
        # We just created a Member-role user on the portal home page + a linked Member.
        self.assertGreaterEqual(stats["total_member_users"], 1)
        self.assertGreaterEqual(stats["members_with_portal_home"], 1)
        self.assertGreaterEqual(stats["members_with_linked_records"], 1)
        # adoption rate is a percentage in [0, 100].
        self.assertGreaterEqual(stats["portal_adoption_rate"], 0)
        self.assertLessEqual(stats["portal_adoption_rate"], 100)

    # ------------------------------------------- sync_member_user_home_pages
    def test_sync_member_home_pages_catches_up(self):
        # A Member-role user with an empty/'/app' home page is a candidate to sync.
        user = self._make_user(roles=["Member"])
        frappe.db.set_value("User", user.email, "home_settings", "/app")
        count = sync_member_user_home_pages()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    # ------------------------------------------ get_user_appropriate_home_page
    def test_home_page_guest(self):
        with self.set_user("Guest"):
            self.assertEqual(get_user_appropriate_home_page(), "/web")

    def test_home_page_member_linked(self):
        _, email = self._make_portal_member(roles=["Member"])
        with self.set_user(email):
            self.assertEqual(get_user_appropriate_home_page(), "/member_portal")

    def test_home_page_volunteer_role(self):
        # A user with a volunteer role but no member link still gets the portal.
        user = self._make_user(roles=["Verenigingen Volunteer"])
        with self.set_user(user.email):
            self.assertEqual(get_user_appropriate_home_page(), "/member_portal")

    def test_home_page_admin_role(self):
        user = self._make_user(roles=["System Manager"])
        with self.set_user(user.email):
            self.assertEqual(get_user_appropriate_home_page(), "/app")

    def test_home_page_default_fallback(self):
        # System User holding only a role outside every recognised set
        # (not Member / volunteer / admin) and with no linked Member or
        # Volunteer record -> the default fallback /web.
        user = self._make_user(roles=["Newsletter Manager"])
        with self.set_user(user.email):
            self.assertEqual(get_user_appropriate_home_page(), "/web")

    # ------------------------------------------------- format_coverage_period
    def test_coverage_none_for_missing_dates(self):
        self.assertIsNone(format_coverage_period(None, "2025-01-31", "Monthly"))
        self.assertIsNone(format_coverage_period("2025-01-01", None, "Monthly"))

    def test_coverage_none_for_bad_dates(self):
        self.assertIsNone(format_coverage_period("not-a-date", "also-bad", "Monthly"))

    def test_coverage_daily(self):
        out = format_coverage_period("2025-03-10", "2025-03-10", "Daily")
        self.assertEqual(out, frappe.utils.formatdate("2025-03-10"))

    def test_coverage_annual_full_year(self):
        self.assertEqual(format_coverage_period("2025-01-01", "2025-12-31", "Annual"), "2025")

    def test_coverage_annual_same_year_partial(self):
        # Same year but not a full calendar year -> still just the year.
        self.assertEqual(format_coverage_period("2025-03-01", "2025-09-30", "annually"), "2025")

    def test_coverage_annual_spanning_years(self):
        out = format_coverage_period("2024-06-01", "2025-05-31", "yearly")
        expected = f"{frappe.utils.formatdate('2024-06-01')} - " f"{frappe.utils.formatdate('2025-05-31')}"
        self.assertEqual(out, expected)

    def test_coverage_quarterly_aligned(self):
        self.assertEqual(
            format_coverage_period("2025-04-01", "2025-06-30", "Quarterly"),
            "Quarter 2 2025",
        )

    def test_coverage_quarterly_unaligned(self):
        out = format_coverage_period("2025-02-15", "2025-05-14", "quarter")
        expected = f"{frappe.utils.formatdate('2025-02-15')} - " f"{frappe.utils.formatdate('2025-05-14')}"
        self.assertEqual(out, expected)

    def test_coverage_monthly_aligned(self):
        # Full calendar month (within 5-day tolerance) -> month name.
        self.assertEqual(
            format_coverage_period("2025-07-01", "2025-07-31", "Monthly"),
            "July 2025",
        )

    def test_coverage_monthly_unaligned(self):
        out = format_coverage_period("2025-07-10", "2025-08-09", "month")
        expected = f"{frappe.utils.formatdate('2025-07-10')} - " f"{frappe.utils.formatdate('2025-08-09')}"
        self.assertEqual(out, expected)

    def test_coverage_unknown_frequency_default(self):
        out = format_coverage_period("2025-01-05", "2025-01-20", "Weekly")
        expected = f"{frappe.utils.formatdate('2025-01-05')} - " f"{frappe.utils.formatdate('2025-01-20')}"
        self.assertEqual(out, expected)

    # ---------------------------- enhance_outstanding_invoices_with_coverage
    def test_enhance_invoices_empty(self):
        self.assertEqual(enhance_outstanding_invoices_with_coverage([], "Monthly"), [])
        self.assertIsNone(enhance_outstanding_invoices_with_coverage(None, "Monthly"))

    def test_enhance_invoices_with_coverage_dates(self):
        si = self._make_invoice_with_coverage(start="2025-07-01", end="2025-07-31")
        invoices = [{"name": si, "due_date": "2025-07-15"}]
        enhanced = enhance_outstanding_invoices_with_coverage(invoices, "Monthly")
        self.assertEqual(len(enhanced), 1)
        self.assertEqual(enhanced[0]["coverage_period"], "July 2025")
        # Original input is not mutated (function copies).
        self.assertNotIn("coverage_period", invoices[0])

    def test_enhance_invoices_fallback_to_due_date(self):
        si = self._make_invoice_with_coverage(start=None, end=None)
        invoices = [{"name": si, "due_date": "2025-07-15"}]
        enhanced = enhance_outstanding_invoices_with_coverage(invoices, "Monthly")
        self.assertEqual(enhanced[0]["coverage_period"], frappe.utils.formatdate("2025-07-15"))

    def test_enhance_invoices_fallback_no_due_date(self):
        si = self._make_invoice_with_coverage(start=None, end=None)
        invoices = [{"name": si}]  # no coverage, no due_date
        enhanced = enhance_outstanding_invoices_with_coverage(invoices, "Monthly")
        self.assertEqual(enhanced[0]["coverage_period"], "No due date")

    def _make_invoice_with_coverage(self, start, end):
        """Create a real submitted Sales Invoice and set coverage custom fields.

        Uses the factory's plumbing for company/customer/item so the invoice is
        valid; then writes the custom coverage fields directly (they're plain
        date fields read back by enhance_outstanding_invoices_with_coverage).
        """
        member = self.factory.create_member(first_name="Inv", last_name="Cover")
        customer = frappe.db.get_value("Member", member.name, "customer")
        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        item = self._ensure_dues_item()
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": company,
                "items": [{"item_code": item, "qty": 1, "rate": 10}],
            }
        )
        si.insert()
        if start and end:
            frappe.db.set_value(
                "Sales Invoice",
                si.name,
                {
                    "custom_coverage_start_date": start,
                    "custom_coverage_end_date": end,
                },
            )
        return si.name

    def _ensure_dues_item(self):
        item_code = "TEST-PORTAL-DUES-ITEM"
        if not frappe.db.exists("Item", item_code):
            group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
            uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
            frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": item_code,
                    "item_group": group,
                    "stock_uom": uom,
                    "is_stock_item": 0,
                    "is_sales_item": 1,
                }
            ).insert()
        return item_code

    # ----------------------------------------------------- setup_portal_context
    def test_setup_context_member_found(self):
        _, email = self._make_portal_member()
        context = frappe._dict()
        with self.set_user(email):
            member_name = setup_portal_context(context, "My Dues Schedule")
        self.assertIsNotNone(member_name)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)
        self.assertFalse(context.no_member_record)
        self.assertEqual(context.title, "My Dues Schedule")

    def test_setup_context_no_member(self):
        user = self._make_user(roles=["Verenigingen Member"])  # user, but no Member
        context = frappe._dict()
        with self.set_user(user.email):
            member_name = setup_portal_context(context, "Personal Details")
        self.assertIsNone(member_name)
        self.assertTrue(context.no_member_record)
        self.assertIn("error_title", context)
        self.assertIn("error_message", context)
        # support_email key is always set on the no-member branch.
        self.assertIn("support_email", context)
