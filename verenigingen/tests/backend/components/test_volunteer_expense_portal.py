import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestVolunteerExpensePortal(FrappeTestCase):
    """
    Comprehensive tests for the volunteer expense portal

    UPDATED: December 2024 - Tests now reflect ERPNext integration
    Legacy Volunteer Expense Dashboard functionality has been phased out
    """

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create test data"""
        # Get or create test company
        if not frappe.db.exists("Company", "Test Company"):
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Company",
                    "abbr": "TC",
                    "default_currency": "EUR",
                    "country": "Netherlands"}
            )
            company.insert()
            cls.company = company.name
        else:
            cls.company = "Test Company"

        # Create test users
        cls.volunteer_user_email = "volunteer@test.com"
        cls.non_volunteer_user_email = "nonvolunteer@test.com"
        cls.board_member_email = "boardmember@test.com"

        cls.create_test_user(cls.volunteer_user_email, "Test Volunteer")
        cls.create_test_user(cls.non_volunteer_user_email, "Non Volunteer")
        cls.create_test_user(cls.board_member_email, "Board Member")

        # Create test chapter
        cls.test_chapter = cls.create_test_chapter()

        # Create test team
        cls.test_team = cls.create_test_team()

        # Create test member and volunteer
        cls.test_member = cls.create_test_member()
        cls.test_volunteer = cls.create_test_volunteer()

        # Create non-volunteer member
        cls.non_volunteer_member = cls.create_non_volunteer_member()

        # Create expense categories
        cls.expense_categories = cls.create_expense_categories()

        # Set up chapter membership
        cls.setup_chapter_membership()

        # Set up team membership
        cls.setup_team_membership()

        # Set up board member
        cls.setup_board_member()

    @classmethod
    def create_test_user(cls, email, full_name):
        """Create test user if not exists"""
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": full_name.split()[0],
                    "last_name": full_name.split()[-1] if len(full_name.split()) > 1 else "",
                    "full_name": full_name,
                    "enabled": 1,
                    "new_password": "test123"}
            )
            user.insert(ignore_permissions=True)

    @classmethod
    def create_test_chapter(cls):
        """Create test chapter"""
        chapter_name = "Test Chapter Portal"
        if not frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": chapter_name,  # Explicitly set name for prompt autoname
                    "chapter_name": chapter_name,
                    "city": "Test City",
                    "country": "Netherlands",
                    "enabled": 1}
            )
            chapter.insert()
            return chapter.name
        return chapter_name

    @classmethod
    def create_test_team(cls):
        """Create test team"""
        team_name = "Test Team Portal"
        if not frappe.db.exists("Team", team_name):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "description": "Test team for portal testing",
                    "chapter": cls.test_chapter,
                    "status": "Active"}
            )
            team.insert()
            return team.name
        return team_name

    @classmethod
    def create_test_member(cls):
        """Create test member"""
        member_id = "TEST-MEMBER-001"
        if not frappe.db.exists("Member", member_id):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": member_id,
                    "first_name": "Test",
                    "last_name": "Volunteer",
                    "full_name": "Test Volunteer",
                    "email": cls.volunteer_user_email,
                    "user": cls.volunteer_user_email,
                    "status": "Active",
                    "interested_in_volunteering": 1}
            )
            member.insert()
            return member.name
        return member_id

    @classmethod
    def create_non_volunteer_member(cls):
        """Create non-volunteer member"""
        member_id = "TEST-MEMBER-002"
        if not frappe.db.exists("Member", member_id):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": member_id,
                    "first_name": "Non",
                    "last_name": "Volunteer",
                    "full_name": "Non Volunteer",
                    "email": cls.non_volunteer_user_email,
                    "user": cls.non_volunteer_user_email,
                    "status": "Active",
                    "interested_in_volunteering": 0}
            )
            member.insert()
            return member.name
        return member_id

    @classmethod
    def create_test_volunteer(cls):
        """Create test volunteer"""
        volunteer_name = "TEST-VOL-001"
        if not frappe.db.exists("Volunteer", volunteer_name):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": volunteer_name,
                    "volunteer_name": "Test Volunteer",
                    "member": cls.test_member,
                    "status": "Active",
                    "email": cls.volunteer_user_email}
            )
            volunteer.insert()
            return volunteer.name
        return volunteer_name

    @classmethod
    def create_expense_categories(cls):
        """Create test expense categories"""
        categories = []
        test_categories = [
            {"name": "Travel", "description": "Travel expenses"},
            {"name": "Materials", "description": "Material costs"},
            {"name": "Food", "description": "Food and beverages"},
        ]

        for cat_data in test_categories:
            if not frappe.db.exists("Expense Category", cat_data["name"]):
                category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": cat_data["name"],
                        "description": cat_data["description"],
                        "disabled": 0}
                )
                category.insert()
                categories.append(category.name)
            else:
                categories.append(cat_data["name"])

        return categories

    @classmethod
    def setup_chapter_membership(cls):
        """Set up chapter membership for test member"""
        chapter_doc = frappe.get_doc("Chapter", cls.test_chapter)

        # Check if member is already in chapter
        member_exists = any(member.member == cls.test_member for member in chapter_doc.members)

        if not member_exists:
            chapter_doc.append(
                "members", {"member": cls.test_member, "chapter_join_date": today(), "enabled": 1}
            )
            chapter_doc.save()

    @classmethod
    def setup_team_membership(cls):
        """Set up team membership for test volunteer"""
        if not frappe.db.exists("Team Member", {"volunteer": cls.test_volunteer, "parent": cls.test_team}):
            team_member = frappe.get_doc(
                {
                    "doctype": "Team Member",
                    "parent": cls.test_team,
                    "parenttype": "Team",
                    "parentfield": "members",
                    "volunteer": cls.test_volunteer,
                    "role_type": "Team Member",
                    "status": "Active",
                    "joined_date": today()}
            )
            team_member.insert()

    @classmethod
    def setup_board_member(cls):
        """Set up board member for approval testing"""
        # Create chapter role if not exists
        role_name = "Test Chair"
        if not frappe.db.exists("Chapter Role", role_name):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Admin",
                    "can_approve_expenses": 1}
            )
            role.insert()

        # Create board member volunteer
        board_volunteer_name = "TEST-VOL-BOARD"
        if not frappe.db.exists("Volunteer", board_volunteer_name):
            # Create board member
            board_member_id = "TEST-MEMBER-BOARD"
            if not frappe.db.exists("Member", board_member_id):
                board_member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "member_id": board_member_id,
                        "first_name": "Board",
                        "last_name": "Member",
                        "full_name": "Board Member",
                        "email": cls.board_member_email,
                        "user": cls.board_member_email,
                        "status": "Active"}
                )
                board_member.insert()

            board_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": board_volunteer_name,
                    "volunteer_name": "Board Member",
                    "member": board_member_id,
                    "status": "Active",
                    "email": cls.board_member_email}
            )
            board_volunteer.insert()

        # Create board position
        if not frappe.db.exists(
            "Chapter Board Member", {"volunteer": board_volunteer_name, "parent": cls.test_chapter}
        ):
            board_position = frappe.get_doc(
                {
                    "doctype": "Chapter Board Member",
                    "parent": cls.test_chapter,
                    "parenttype": "Chapter",
                    "parentfield": "board_members",
                    "volunteer": board_volunteer_name,
                    "chapter_role": role_name,
                    "start_date": today(),
                    "is_active": 1}
            )
            board_position.insert()

    def setUp(self):
        """Set up for each test"""
        # Set current user to volunteer
        frappe.set_user(self.volunteer_user_email)

    def tearDown(self):
        """Clean up after each test"""
        frappe.set_user("Administrator")
        # Clean up any test expenses
        expenses = frappe.get_all("Volunteer Expense", filters={"volunteer": self.test_volunteer})
        for expense in expenses:
            try:
                frappe.delete_doc("Volunteer Expense", expense.name, force=1)
            except Exception:
                pass

    # PORTAL ACCESS TESTS

    def test_volunteer_dashboard_access_valid_volunteer(self):
        """Test dashboard access for valid volunteer"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        context = {}
        get_context(context)

        self.assertIsNotNone(context.get("volunteer"))
        self.assertEqual(context["volunteer"]["name"], self.test_volunteer)
        self.assertIsNotNone(context.get("volunteer_profile"))
        self.assertIsNotNone(context.get("organizations"))

    def test_volunteer_dashboard_access_non_volunteer(self):
        """Test dashboard access for non-volunteer user"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user(self.non_volunteer_user_email)

        context = {}
        get_context(context)

        self.assertIsNotNone(context.get("error_message"))
        self.assertIn("No volunteer record found", context["error_message"])

    def test_volunteer_dashboard_access_guest_user(self):
        """Test dashboard access for guest user"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user("Guest")

        with self.assertRaises(frappe.PermissionError):
            context = {}
            get_context(context)

    def test_expense_portal_access_valid_volunteer(self):
        """Test expense portal access for valid volunteer"""
        from verenigingen.templates.pages.volunteer.expenses import get_context

        context = {}
        get_context(context)

        self.assertIsNotNone(context.get("volunteer"))
        self.assertIsNotNone(context.get("organizations"))
        self.assertIsNotNone(context.get("expense_categories"))
        self.assertIsNotNone(context.get("recent_expenses"))
        self.assertIsNotNone(context.get("expense_stats"))

    def test_expense_portal_access_guest_user(self):
        """Test expense portal access for guest user"""
        from verenigingen.templates.pages.volunteer.expenses import get_context

        frappe.set_user("Guest")

        with self.assertRaises(frappe.PermissionError):
            context = {}
            get_context(context)

    # ORGANIZATION ACCESS TESTS

    def test_get_volunteer_organizations_with_chapter_and_team(self):
        """Test getting organizations for volunteer with both chapter and team"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

        organizations = get_volunteer_organizations(self.test_volunteer)

        self.assertIsInstance(organizations, dict)
        self.assertIn("chapters", organizations)
        self.assertIn("teams", organizations)
        self.assertTrue(len(organizations["chapters"]) > 0)
        self.assertTrue(len(organizations["teams"]) > 0)

    def test_get_organization_options_chapter(self):
        """Test getting chapter options for volunteer"""
        from verenigingen.templates.pages.volunteer.expenses import get_organization_options

        options = get_organization_options("Chapter", self.test_volunteer)

        self.assertIsInstance(options, list)
        self.assertTrue(len(options) > 0)
        self.assertIn("value", options[0])
        self.assertIn("label", options[0])

    def test_get_organization_options_team(self):
        """Test getting team options for volunteer"""
        from verenigingen.templates.pages.volunteer.expenses import get_organization_options

        options = get_organization_options("Team", self.test_volunteer)

        self.assertIsInstance(options, list)
        self.assertTrue(len(options) > 0)
        self.assertIn("value", options[0])
        self.assertIn("label", options[0])

    def test_get_organization_options_invalid_type(self):
        """Test getting organization options with invalid type"""
        from verenigingen.templates.pages.volunteer.expenses import get_organization_options

        options = get_organization_options("InvalidType", self.test_volunteer)

        self.assertEqual(options, [])

    # EXPENSE SUBMISSION TESTS

    def test_submit_expense_valid_chapter(self):
        """Test submitting valid expense for chapter"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test travel expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter,
            "category": self.expense_categories[0],
            "notes": "Test expense submission"}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])
        self.assertIn("expense_name", result)

        # Verify expense was created
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.volunteer, self.test_volunteer)
        self.assertEqual(expense.description, "Test travel expense")
        self.assertEqual(expense.amount, 50.00)
        self.assertEqual(expense.organization_type, "Chapter")
        self.assertEqual(expense.chapter, self.test_chapter)
        self.assertEqual(expense.status, "Submitted")

    def test_submit_expense_valid_team(self):
        """Test submitting valid expense for team"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test material expense",
            "amount": 25.50,
            "expense_date": today(),
            "organization_type": "Team",
            "team": self.test_team,
            "category": self.expense_categories[1]}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify expense was created
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.organization_type, "Team")
        self.assertEqual(expense.team, self.test_team)

    def test_submit_expense_missing_required_fields(self):
        """Test submitting expense with missing required fields"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            # Missing amount, expense_date, organization_type
        }

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])
        self.assertIn("required", result["message"])

    def test_submit_expense_invalid_organization_selection(self):
        """Test submitting expense with invalid organization selection"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            # Missing chapter selection
        }

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])
        self.assertIn("select a chapter", result["message"])

    def test_submit_expense_zero_amount(self):
        """Test submitting expense with zero amount"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            "amount": 0.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])

    def test_submit_expense_negative_amount(self):
        """Test submitting expense with negative amount"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            "amount": -50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])

    def test_submit_expense_future_date(self):
        """Test submitting expense with future date"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": add_days(today(), 1),  # Future date
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])

    def test_submit_expense_unauthorized_chapter(self):
        """Test submitting expense for unauthorized chapter"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create another chapter
        other_chapter = "Other Test Chapter"
        if not frappe.db.exists("Chapter", other_chapter):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "chapter_name": other_chapter,
                    "city": "Other City",
                    "country": "Netherlands",
                    "enabled": 1}
            )
            chapter.insert()

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": other_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])

    # EXPENSE STATISTICS TESTS

    def test_get_expense_statistics_no_expenses(self):
        """Test getting expense statistics with no expenses"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics

        stats = get_expense_statistics(self.test_volunteer)

        self.assertEqual(stats["total_submitted"], 0)
        self.assertEqual(stats["total_approved"], 0)
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["approved_count"], 0)
        self.assertEqual(stats["total_count"], 0)

    def test_get_expense_statistics_with_expenses(self):
        """Test getting expense statistics with existing expenses"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics

        # Create test expenses
        expenses = []

        # Submitted expense
        expense1 = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer,
                "description": "Test expense 1",
                "amount": 100.00,
                "currency": "EUR",
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter,
                "status": "Submitted"}
        )
        expense1.insert()
        expense1.submit()
        expenses.append(expense1.name)

        # Approved expense
        expense2 = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer,
                "description": "Test expense 2",
                "amount": 50.00,
                "currency": "EUR",
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter,
                "status": "Approved"}
        )
        expense2.insert()
        expense2.submit()
        expenses.append(expense2.name)

        try:
            stats = get_expense_statistics(self.test_volunteer)

            self.assertEqual(stats["total_submitted"], 150.00)
            self.assertEqual(stats["total_approved"], 50.00)
            self.assertEqual(stats["pending_count"], 1)
            self.assertEqual(stats["approved_count"], 1)
            self.assertEqual(stats["total_count"], 2)
            self.assertEqual(stats["pending_amount"], 100.00)

        finally:
            # Clean up
            for expense_name in expenses:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # EXPENSE DETAILS TESTS

    def test_get_expense_details_valid_expense(self):
        """Test getting details for valid expense"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_details

        # Create test expense
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer,
                "description": "Test expense for details",
                "amount": 75.00,
                "currency": "EUR",
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter,
                "category": self.expense_categories[0]}
        )
        expense.insert()
        expense.submit()

        try:
            details = get_expense_details(expense.name)

            self.assertEqual(details["volunteer"], self.test_volunteer)
            self.assertEqual(details["description"], "Test expense for details")
            self.assertEqual(details["amount"], 75.00)
            self.assertIn("organization_name", details)
            self.assertIn("attachment_count", details)

        finally:
            frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_get_expense_details_unauthorized_expense(self):
        """Test getting details for expense belonging to another volunteer"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_details

        # Create another volunteer
        other_volunteer = "TEST-VOL-OTHER"
        if not frappe.db.exists("Volunteer", other_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": other_volunteer,
                    "volunteer_name": "Other Volunteer",
                    "status": "Active"}
            )
            volunteer.insert()

        # Create expense for other volunteer
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": other_volunteer,
                "description": "Other volunteer expense",
                "amount": 25.00,
                "currency": "EUR",
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter}
        )
        expense.insert()
        expense.submit()

        try:
            with self.assertRaises(frappe.PermissionError):
                get_expense_details(expense.name)

        finally:
            frappe.delete_doc("Volunteer Expense", expense.name, force=1)
            frappe.delete_doc("Volunteer", other_volunteer, force=1)

    # APPROVAL THRESHOLD TESTS

    def test_get_approval_thresholds(self):
        """Test getting approval thresholds"""
        from verenigingen.templates.pages.volunteer.expenses import get_approval_thresholds

        thresholds = get_approval_thresholds()

        self.assertIn("basic_limit", thresholds)
        self.assertIn("financial_limit", thresholds)
        self.assertIn("admin_limit", thresholds)
        self.assertEqual(thresholds["basic_limit"], 100.0)
        self.assertEqual(thresholds["financial_limit"], 500.0)

    # EDGE CASE TESTS

    def test_volunteer_with_no_organizations(self):
        """Test volunteer with no chapter or team memberships"""
        # Create isolated volunteer
        isolated_volunteer = "TEST-VOL-ISOLATED"
        isolated_email = "isolated@test.com"

        # Create user
        if not frappe.db.exists("User", isolated_email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": isolated_email,
                    "first_name": "Isolated",
                    "last_name": "Volunteer",
                    "full_name": "Isolated Volunteer",
                    "enabled": 1}
            )
            user.insert(ignore_permissions=True)

        # Create volunteer without member link
        if not frappe.db.exists("Volunteer", isolated_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": isolated_volunteer,
                    "volunteer_name": "Isolated Volunteer",
                    "email": isolated_email,
                    "status": "Active"}
            )
            volunteer.insert()

        try:
            frappe.set_user(isolated_email)

            from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

            organizations = get_volunteer_organizations(isolated_volunteer)

            self.assertEqual(len(organizations["chapters"]), 0)
            self.assertEqual(len(organizations["teams"]), 0)

        finally:
            frappe.set_user(self.volunteer_user_email)
            frappe.delete_doc("Volunteer", isolated_volunteer, force=1)
            frappe.delete_doc("User", isolated_email, force=1)

    def test_expense_submission_without_volunteer_record(self):
        """Test expense submission when user has no volunteer record"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.non_volunteer_user_email)

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])
        self.assertIn("No volunteer record found", result["message"])

    def test_large_expense_amount(self):
        """Test submitting expense with very large amount"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Large expense",
            "amount": 999999.99,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify expense was created with correct amount
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.amount, 999999.99)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_very_long_description(self):
        """Test submitting expense with very long description"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        long_description = "A" * 1000  # 1000 character description

        expense_data = {
            "description": long_description,
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify expense was created with full description
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.description, long_description)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_special_characters_in_description(self):
        """Test submitting expense with special characters in description"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        special_description = "Test expense with special chars: @#$%^&*()_+-=[]{}|;':\",./<>?"

        expense_data = {
            "description": special_description,
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify expense was created with special characters
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.description, special_description)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_concurrent_submissions(self):
        """Test multiple concurrent expense submissions"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expenses = []

        try:
            # Submit multiple expenses quickly
            for i in range(5):
                expense_data = {
                    "description": f"Concurrent expense {i + 1}",
                    "amount": 10.00 * (i + 1),
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter}

                result = submit_expense(expense_data)

                self.assertTrue(result["success"])
                expenses.append(result["expense_name"])

            # Verify all expenses were created
            self.assertEqual(len(expenses), 5)

            for expense_name in expenses:
                expense = frappe.get_doc("Volunteer Expense", expense_name)
                self.assertEqual(expense.volunteer, self.test_volunteer)
                self.assertEqual(expense.status, "Submitted")

        finally:
            # Clean up
            for expense_name in expenses:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    def test_expense_categories_disabled(self):
        """Test behavior when expense categories are disabled"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_categories

        # Disable all categories
        for category_name in self.expense_categories:
            category = frappe.get_doc("Expense Category", category_name)
            category.disabled = 1
            category.save()

        try:
            categories = get_expense_categories()
            self.assertEqual(len(categories), 0)

        finally:
            # Re-enable categories
            for category_name in self.expense_categories:
                category = frappe.get_doc("Expense Category", category_name)
                category.disabled = 0
                category.save()

    def test_expense_with_unicode_characters(self):
        """Test submitting expense with unicode characters"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        unicode_description = "Test expense with unicode: 你好 🌟 café naïve résumé"

        expense_data = {
            "description": unicode_description,
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify expense was created with unicode characters
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.description, unicode_description)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)


if __name__ == "__main__":
    unittest.main()
