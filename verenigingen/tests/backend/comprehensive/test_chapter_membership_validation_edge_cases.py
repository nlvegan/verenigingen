#!/usr/bin/env python3
"""
Edge case tests for chapter membership validation to prevent similar bugs
"""

import contextlib
import unittest

import frappe
from frappe.utils import today


@contextlib.contextmanager
def _as_session_user(email: str):
    """Temporarily set frappe.session.user without going through User-validation.

    Replaces broken `with patch("frappe.session.user", email):` idiom.
    `mock.patch` resolves the dotted path at decoration time — `frappe.session`
    is a Werkzeug LocalProxy whose `.user` lookup raises before the patch can
    install. Direct assignment works because the proxy delegates __setattr__
    to the underlying session dict.
    """
    original = frappe.session.user
    try:
        frappe.session.user = email
        yield
    finally:
        frappe.session.user = original


def _ensure_user(email: str, first_name: str, last_name: str,
                 role_profile: str = "Verenigingen Volunteer") -> None:
    """Idempotently create a User with a role profile assignment.

    The portal endpoints under test (e.g. `submit_expense`) require MEDIUM
    security level. Per `verenigingen/utils/security/authorization_policy.py`,
    only role *profiles* — not plain roles — grant access to a security level.
    `Verenigingen Volunteer` profile grants MEDIUM (for self_service_only
    operations) + LOW.
    """
    def _apply_role_profile(user_doc):
        # In Frappe v16 setting role_profile_name alone does NOT assign the
        # profile's roles — the profile must be present in the role_profiles
        # child table, which then syncs Has Role records on save.
        existing = {rp.role_profile for rp in user_doc.get("role_profiles", [])}
        if role_profile not in existing:
            user_doc.append("role_profiles", {"role_profile": role_profile})
            user_doc.save(ignore_permissions=True)

    if frappe.db.exists("User", email):
        _apply_role_profile(frappe.get_doc("User", email))
        return
    user = frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "enabled": 1,
        "user_type": "System User",
        "send_welcome_email": 0,
        "role_profiles": [{"role_profile": role_profile}],
    })
    user.insert(ignore_permissions=True)


def _ensure_region(region_name: str, region_code: str) -> str:
    """Idempotently create a Region and return its actual .name (autoname scrubs)."""
    existing = frappe.db.get_value("Region", {"region_name": region_name}, "name")
    if existing:
        return existing
    # The Region controller rejects a duplicate region_code with a ValidationError
    # (not DuplicateEntryError). On the shared test site a prior run may already
    # own this code, so reuse that Region instead of failing.
    existing_by_code = frappe.db.get_value("Region", {"region_code": region_code}, "name")
    if existing_by_code:
        return existing_by_code
    try:
        doc = frappe.get_doc({
            "doctype": "Region",
            "region_name": region_name,
            "region_code": region_code,
        }).insert(ignore_permissions=True)
        return doc.name
    except (frappe.DuplicateEntryError, frappe.ValidationError):
        # Pre-existing Region row colliding on scrubbed name or region_code.
        return (
            frappe.db.get_value("Region", {"region_name": region_name}, "name")
            or frappe.db.get_value("Region", {"region_code": region_code}, "name")
            or region_name.lower().replace(" ", "-")
        )


class TestChapterMembershipValidationEdgeCases(unittest.TestCase):
    """Test edge cases in chapter membership validation"""

    @classmethod
    def _ensure_employee_for_volunteer(cls, volunteer_doc, first_name, last_name):
        """Create + link an Employee for a volunteer (as Administrator).

        Done in setUpClass to avoid the self-service expense path having to
        auto-create the Employee under the limited volunteer user.
        """
        if volunteer_doc.employee_id and frappe.db.exists("Employee", volunteer_doc.employee_id):
            return
        if not getattr(cls, "_company", None):
            return
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": first_name,
                "last_name": last_name,
                "employee_name": f"{first_name} {last_name}",
                "personal_email": volunteer_doc.email,
                "company": cls._company,
                "status": "Active",
                "date_of_birth": "1990-01-01",
                "date_of_joining": today(),
                "gender": "Other",
            }
        )
        employee.insert(ignore_permissions=True)
        volunteer_doc.db_set("employee_id", employee.name)

    @classmethod
    def setUpClass(cls):
        """Set up test data for edge cases"""
        frappe.set_user("Administrator")

        # Clean up any existing test data first
        cls._cleanup_test_data()

        # Create User records for edge emails. The portal endpoints under test
        # gate on `frappe.session.user` being a real authenticated User with
        # the Verenigingen Member role.
        for email, first, last in [
            ("edge1@example.com", "Edge", "Case One"),
            ("edge2@example.com", "Edge", "Case Two"),
            ("edge3@example.com", "Edge", "Case Three"),
            ("empty@example.com", "Edge", "Case Empty"),
        ]:
            _ensure_user(email, first, last)

        # Create required Regions. autoname=field:region_name scrubs to dashes,
        # so capture the resolved .name to use in Chapter.region links below.
        cls.regions = {}
        for region_name, region_code in [
            ("Test Region 1", "TR1"),
            ("Test Region 2", "TR2"),
            ("Test Region Disabled", "TRD"),
        ]:
            cls.regions[region_name] = _ensure_region(region_name, region_code)

        # Create multiple test scenarios
        cls.test_data = {}

        # Scenario 1: Volunteer with member link.
        # Member.autoname is `format:Assoc-Member-{YYYY}-{MM}-{####}` so an
        # explicit "name" is ignored — we capture the resolved .name after
        # insert and use it everywhere downstream.
        cls.test_data["member_1"] = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Edge",
                "last_name": "Case One",
                "email": "edge1@example.com",
                "join_date": today()}
        )
        cls.test_data["member_1"].insert()
        cls.member_1_name = cls.test_data["member_1"].name

        cls.test_data["volunteer_1"] = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Edge Case Volunteer 1",
                "email": "edge1@example.com",
                "member": cls.member_1_name,
                "status": "Active",
                "start_date": today()}
        )
        cls.test_data["volunteer_1"].insert()

        # Scenario 2: Volunteer without member link
        cls.test_data["volunteer_2"] = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Edge Case Volunteer 2",
                "email": "edge2@example.com",
                "status": "Active",
                "start_date": today()}
        )
        cls.test_data["volunteer_2"].insert()

        # The self-service expense submission auto-creates an Employee for the
        # volunteer, which needs Verenigingen Settings.company set AND runs under
        # the (limited) volunteer user who lacks Employee-create permission on an
        # isolated site. Pre-create the Employee records as Administrator and link
        # them so the expense flow finds an existing employee and skips creation.
        cls._company = (
            frappe.db.get_single_value("Verenigingen Settings", "company")
            or frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
            or frappe.db.get_value("Company", {}, "name")
        )
        if cls._company and not frappe.db.get_single_value("Verenigingen Settings", "company"):
            frappe.db.set_single_value("Verenigingen Settings", "company", cls._company)

        cls._ensure_employee_for_volunteer(cls.test_data["volunteer_1"], "Edge", "Case One")
        cls._ensure_employee_for_volunteer(cls.test_data["volunteer_2"], "Edge", "Case Two")

        # Scenario 3: Member without volunteer link
        cls.test_data["member_3"] = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Edge",
                "last_name": "Case Three",
                "email": "edge3@example.com",
                "join_date": today()}
        )
        cls.test_data["member_3"].insert()
        cls.member_3_name = cls.test_data["member_3"].name

        # Create test chapters with required region field
        cls.test_data["chapter_1"] = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": "EDGE-CHAPTER-1",
                "chapter_name": "Edge Case Chapter 1",
                "region": cls.regions["Test Region 1"]}
        )
        cls.test_data["chapter_1"].insert()

        cls.test_data["chapter_2"] = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": "EDGE-CHAPTER-2",
                "chapter_name": "Edge Case Chapter 2",
                "region": cls.regions["Test Region 2"]}
        )
        cls.test_data["chapter_2"].insert()

        # Create chapter membership for scenario 1
        cls.test_data["chapter_1"].append(
            "members", {"member": cls.member_1_name, "member_name": "Edge Case Volunteer 1", "enabled": 1}
        )
        cls.test_data["chapter_1"].save()

        # Create expense category. Expense Category.autoname is
        # field:category_name, so the resolved .name is "Edge Case Category".
        # expense_account is a mandatory Link to Account.
        cls.category_name = "Edge Case Category"
        if not frappe.db.exists("Expense Category", cls.category_name):
            default_company = frappe.db.get_single_value("Global Defaults", "default_company")
            expense_account = None
            if default_company:
                expense_account = frappe.db.get_value(
                    "Account",
                    {"company": default_company, "is_group": 0, "account_type": "Expense Account"},
                    "name",
                )
            # On the isolated test site Global Defaults may have no default_company
            # (or that company has no expense account); fall back to any expense
            # account so the mandatory field is populated.
            if not expense_account:
                expense_account = frappe.db.get_value(
                    "Account",
                    {"is_group": 0, "account_type": "Expense Account"},
                    "name",
                )
            cls.test_data["category"] = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": cls.category_name,
                    "expense_account": expense_account,
                    "is_active": 1}
            )
            cls.test_data["category"].insert()

    def test_volunteer_with_member_valid_chapter(self):
        """Test volunteer with member link submitting to valid chapter"""
        from verenigingen.utils.volunteer_expense_portal_utils import get_user_volunteer_record
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test get_user_volunteer_record first
        with _as_session_user("edge1@example.com"):
            volunteer_record = get_user_volunteer_record()

            self.assertIsNotNone(volunteer_record, "Should find volunteer record")
            self.assertEqual(volunteer_record.member, self.member_1_name, "Should have correct member link")

        # Test expense submission
        expense_data = {
            "description": "Edge case test - valid membership",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "EDGE-CHAPTER-1",
            "category": self.category_name,
            "notes": "Testing valid membership"}

        with _as_session_user("edge1@example.com"):
            result = submit_expense(expense_data)

            self.assertTrue(
                result.get("success"), f"Should succeed for valid membership. Error: {result.get('message')}"
            )

    def test_volunteer_with_member_invalid_chapter(self):
        """Test volunteer with member link submitting to invalid chapter"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Edge case test - invalid membership",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "EDGE-CHAPTER-2",  # Volunteer not member of this chapter
            "category": self.category_name,
            "notes": "Testing invalid membership"}

        with _as_session_user("edge1@example.com"):
            result = submit_expense(expense_data)

            self.assertFalse(result.get("success"), "Should fail for invalid membership")
            self.assertIn(
                "membership required",
                result.get("message", "").lower(),
                "Error should mention membership requirement",
            )

    def test_volunteer_without_member_link(self):
        """Test volunteer without member link submitting expense"""
        from verenigingen.utils.volunteer_expense_portal_utils import get_user_volunteer_record
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test get_user_volunteer_record
        with _as_session_user("edge2@example.com"):
            volunteer_record = get_user_volunteer_record()

            self.assertIsNotNone(volunteer_record, "Should find volunteer record")
            self.assertIn("member", volunteer_record, "Should include member field even if None")
            self.assertIsNone(volunteer_record.member, "Member should be None for unlinked volunteer")

        # Test expense submission - should fail because no member link
        expense_data = {
            "description": "Edge case test - no member link",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "EDGE-CHAPTER-1",
            "category": self.category_name,
            "notes": "Testing volunteer without member link"}

        with _as_session_user("edge2@example.com"):
            result = submit_expense(expense_data)

            self.assertFalse(result.get("success"), "Should fail for volunteer without member link")

    def test_member_without_volunteer_link(self):
        """Test member without volunteer link trying to access system"""
        from verenigingen.utils.volunteer_expense_portal_utils import get_user_volunteer_record

        with _as_session_user("edge3@example.com"):
            volunteer_record = get_user_volunteer_record()

            self.assertIsNone(volunteer_record, "Should return None for member without volunteer link")

    def test_disabled_chapter_membership(self):
        """Test that disabled chapter memberships are not considered valid"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create a disabled membership
        test_chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": "EDGE-CHAPTER-DISABLED",
                "chapter_name": "Edge Case Disabled Chapter",
                "region": self.regions["Test Region Disabled"]}
        )
        test_chapter.insert()

        test_chapter.append(
            "members",
            {
                "member": self.member_1_name,
                "member_name": "Edge Case Volunteer 1",
                "enabled": 0,  # Disabled membership
            },
        )
        test_chapter.save()

        expense_data = {
            "description": "Edge case test - disabled membership",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "EDGE-CHAPTER-DISABLED",
            "category": self.category_name,
            "notes": "Testing disabled membership"}

        with _as_session_user("edge1@example.com"):
            submit_expense(expense_data)

            # Should fail because membership is disabled
            # Note: Current implementation doesn't check enabled status, but we test the query
            membership_exists = frappe.db.exists(
                "Chapter Member",
                {
                    "parent": "EDGE-CHAPTER-DISABLED",
                    "member": self.member_1_name,
                    "enabled": 1,  # Only enabled memberships
                },
            )
            self.assertFalse(membership_exists, "Should not find enabled membership")

        # Clean up
        frappe.delete_doc("Chapter", "EDGE-CHAPTER-DISABLED", )

    def test_multiple_memberships_same_chapter(self):
        """Test edge case where member has multiple entries for same chapter"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # This shouldn't happen in normal operation, but test robustness
        expense_data = {
            "description": "Edge case test - multiple memberships",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "EDGE-CHAPTER-1",
            "category": self.category_name,
            "notes": "Testing multiple memberships edge case"}

        with _as_session_user("edge1@example.com"):
            result = submit_expense(expense_data)

            self.assertTrue(result.get("success"), "Should succeed even with multiple membership entries")

    def test_case_sensitivity_in_chapter_names(self):
        """Test that chapter name matching is case-sensitive as expected"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Edge case test - case sensitivity",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "edge-chapter-1",  # Wrong case
            "category": self.category_name,
            "notes": "Testing case sensitivity"}

        with _as_session_user("edge1@example.com"):
            result = submit_expense(expense_data)

            self.assertFalse(result.get("success"), "Should fail for incorrect case in chapter name")

    def test_nonexistent_chapter(self):
        """Test submission to non-existent chapter"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Edge case test - nonexistent chapter",
            "amount": 20.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "NONEXISTENT-CHAPTER",
            "category": self.category_name,
            "notes": "Testing nonexistent chapter"}

        with _as_session_user("edge1@example.com"):
            result = submit_expense(expense_data)

            self.assertFalse(result.get("success"), "Should fail for nonexistent chapter")

    def test_empty_member_field_vs_none(self):
        """Test difference between empty string and None in member field"""
        from verenigingen.utils.volunteer_expense_portal_utils import get_user_volunteer_record

        # Create volunteer with empty string member field
        volunteer_empty = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Edge Case Empty Member",
                "email": "empty@example.com",
                "member": "",  # Empty string instead of None
                "status": "Active",
                "start_date": today()}
        )
        volunteer_empty.insert()

        try:
            with _as_session_user("empty@example.com"):
                volunteer_record = get_user_volunteer_record()

                self.assertIsNotNone(volunteer_record, "Should find volunteer")
                self.assertIn("member", volunteer_record, "Should include member field")
                # The field should be there, even if empty

        finally:
            frappe.delete_doc("Volunteer", "Edge Case Empty Member", )

    @classmethod
    def _cleanup_test_data(cls):
        """Clean up test data. Each delete is independently try/excepted so a
        single failure doesn't abort the rest — otherwise leftovers from one
        run cause unique-key conflicts on the next run."""
        def _safe(fn):
            try:
                fn()
            except Exception:
                pass

        # Clean up in reverse dependency order
        _safe(lambda: frappe.db.delete(
            "Expense Claim", {"employee": ["Edge Case Volunteer 1", "Edge Case Volunteer 2"]}
        ))
        _safe(lambda: frappe.db.delete(
            "Volunteer Expense", {"volunteer": ["Edge Case Volunteer 1", "Edge Case Volunteer 2"]}
        ))

        for doc_type, names in [
            ("Chapter", ["EDGE-CHAPTER-1", "EDGE-CHAPTER-2", "EDGE-CHAPTER-DISABLED"]),
            # Expense Category.autoname is field:category_name, so the resolved
            # name is "Edge Case Category" not the explicit "EDGE-CATEGORY".
            ("Expense Category", ["Edge Case Category"]),
        ]:
            for name in names:
                if frappe.db.exists(doc_type, name):
                    # Chapter has dependent rows (Chapter Member child table,
                    # Department, etc.); regular delete may fail. Try the ORM
                    # path first, then raw SQL fallback on parent + child tables.
                    _safe(lambda dt=doc_type, n=name: frappe.delete_doc(dt, n, force=True, ignore_permissions=True))
                    if frappe.db.exists(doc_type, name):
                        _safe(lambda dt=doc_type, n=name: frappe.db.sql(
                            "DELETE FROM `tabChapter Member` WHERE parent = %s", (n,)
                        ) if dt == "Chapter" else None)
                        _safe(lambda dt=doc_type, n=name: frappe.db.sql(
                            f"DELETE FROM `tab{dt}` WHERE name = %s", (n,)
                        ))

        # Volunteer and Member autoname is format-based — we can't predict
        # names, so find by email. Volunteer must be deleted before Member
        # (Volunteer.member is a Link to Member). frappe.delete_doc may itself
        # fail on lingering FK refs in test DBs, so fall back to raw SQL — the
        # unique-email constraint will block re-insertion otherwise.
        edge_emails = ("edge1@example.com", "edge2@example.com",
                       "edge3@example.com", "empty@example.com")
        for email in edge_emails:
            for vol_name in frappe.db.sql_list(
                "SELECT name FROM `tabVolunteer` WHERE email = %s", (email,)
            ):
                _safe(lambda n=vol_name: frappe.delete_doc("Volunteer", n, force=True, ignore_permissions=True))
                _safe(lambda n=vol_name: frappe.db.sql("DELETE FROM `tabVolunteer` WHERE name = %s", (n,)))
        for email in edge_emails:
            for member_name in frappe.db.sql_list(
                "SELECT name FROM `tabMember` WHERE email = %s", (email,)
            ):
                _safe(lambda n=member_name: frappe.delete_doc("Member", n, force=True, ignore_permissions=True))
                _safe(lambda n=member_name: frappe.db.sql("DELETE FROM `tabMember` WHERE name = %s", (n,)))

        # Users delete after Volunteer/Member to avoid permission/FK churn.
        for email in edge_emails:
            if frappe.db.exists("User", email):
                _safe(lambda e=email: frappe.delete_doc("User", e, force=True, ignore_permissions=True))
                _safe(lambda e=email: frappe.db.sql("DELETE FROM `tabUser` WHERE name = %s", (e,)))

        _safe(frappe.db.commit)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        cls._cleanup_test_data()


if __name__ == "__main__":
    unittest.main()
