"""
Integration tests for verenigingen.utils.member_portal_utils.

This module is LIVE: it powers 8 portal-page controllers (my_dues_schedule,
membership_adjustment, address_change, personal_details, ...). The tests below
exercise it the way the real portal does — as a logged-in Member-linked user
and as a system/admin user — hitting the real DB and the real branches rather
than mocking business logic.

Covered functions:
- get_member_portal_stats (real aggregate counts)
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
    setup_portal_context,
)


class TestMemberPortalUtils(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers
    def _make_portal_member(self, roles=None):
        """Create a User (with given roles) + a Member linked to that User.

        Returns (member_doc, user_email). The Member.user link is what
        get_current_user_member_name / get_user_appropriate_home_page resolve on.
        """
        if roles is None:
            roles = ["Verenigingen Member"]
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
        return self.factory.create_user_with_roles(roles=roles)

    # ------------------------------------------------ get_member_portal_stats
    def test_member_portal_stats_shape_and_values(self):
        # Baseline, then add a user holding the real member role
        # ("Verenigingen Member") + a linked Member record. The stats SQL filters
        # on that role; if it still filtered on the phantom "Member" role (which
        # does not exist on prod) the count would not move.
        before = get_member_portal_stats()
        self.assertNotIn("error", before)
        self._make_portal_member(roles=["Verenigingen Member"])
        stats = get_member_portal_stats()
        self.assertNotIn("error", stats)
        for key in ("total_member_users", "members_with_linked_records"):
            self.assertIn(key, stats)
        # The home_settings-based adoption metric was removed: routing is handled
        # by auth_hooks + member_portal_redirect.js, not a per-user field.
        self.assertNotIn("members_with_portal_home", stats)
        self.assertNotIn("portal_adoption_rate", stats)
        # The new Verenigingen Member user must be counted (role filter regression).
        self.assertEqual(stats["total_member_users"], before["total_member_users"] + 1)
        self.assertEqual(stats["members_with_linked_records"], before["members_with_linked_records"] + 1)

    # ------------------------------------------ get_user_appropriate_home_page
    def test_home_page_guest(self):
        with self.set_user("Guest"):
            self.assertEqual(get_user_appropriate_home_page(), "/web")

    def test_home_page_member_linked(self):
        _, email = self._make_portal_member(roles=["Verenigingen Member"])
        with self.set_user(email):
            self.assertEqual(get_user_appropriate_home_page(), "/member_portal")

    def test_home_page_member_role_without_record(self):
        # A user with the "Verenigingen Member" role but NO linked Member record
        # must still resolve to the portal via the role branch. This is the
        # phantom-role regression: the check used the non-existent "Member" role.
        user = self._make_user(roles=["Verenigingen Member"])
        with self.set_user(user.email):
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
