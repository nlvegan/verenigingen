# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import frappe
from frappe.utils import now_datetime, add_days, add_months, getdate
from verenigingen.tests.test_utils import BaseTestCase
import unittest


class TestMembershipAnalyticsPermissions(BaseTestCase):
    """Test access permissions for membership analytics features"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Create test users with different roles
        cls.admin_user = cls._create_analytics_test_user("admin@test.com", [
            "Verenigingen Administrator",
            "System Manager"
        ])
        
        cls.manager_user = cls._create_analytics_test_user("manager@test.com", [
            "Verenigingen Staff"
        ])
        
        cls.board_member_user = cls._create_analytics_test_user("board@test.com", [
            "Verenigingen National Board Member"
        ])
        
        cls.regular_member_user = cls._create_analytics_test_user("member@test.com", [
            "Verenigingen Member"
        ])
        
        cls.no_role_user = cls._create_analytics_test_user("norole@test.com", [])
        
    @classmethod
    def _create_analytics_test_user(cls, email, roles):
        """Create a test user with specified roles.

        Renamed from `create_test_user` (#496): that name shadows
        `EnhancedTestCase.create_test_user(email, roles=None, **kwargs)`, which
        `as_role()` calls internally as `self.create_test_user(email,
        roles=roles)`. This override is a classmethod with no `**kwargs`, used
        only from setUpClass -- latent because this class never calls
        `self.as_role()` today.
        """
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0].title(),
                "enabled": 1,
                "new_password": "testpass123",
                # Suppress welcome email: Frappe v16's send_welcome_mail_to_user
                # raises AttributeError ('bool' has no attribute 'message') when the
                # mailer returns a bool in the no-email test context.
                "send_welcome_email": 0,
                "roles": []
            })
            user.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        # Clear existing roles
        user.roles = []
        
        # Add specified roles
        for role in roles:
            user.append("roles", {"role": role})

        user.save()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        frappe.db.commit()

        # Post the audit #2 Rule-5 cap, HIGH/CRITICAL access needs an assigned role
        # PROFILE; assign the profile matching each role so admin/staff/board users
        # clear the analytics endpoints' gate (Member/no-role stay denied).
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(email, roles)

        return email
    
    def setUp(self):
        super().setUp()
        # Reset to administrator for setup
        # BaseTestCase handles permissions through custom framework
        
        # Create test data
        self.create_test_membership_data()
        self.create_test_analytics_data()
    
    def create_test_membership_data(self):
        """Create test members and memberships"""
        # Per-test unique token so the auto-created Customer (named after the member's
        # full_name) never collides with a Customer left behind by a previous/crashed run.
        token = frappe.generate_hash(length=6)
        # Create a few test members
        for i in range(5):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Test{i}{token}",
                "last_name": "Analytics",
                "email": f"analytics{i}{token}@test.com",
                "status": "Active",
                "member_since": add_months(getdate(), -i)
            })
            member.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
    
    def create_test_analytics_data(self):
        """Create test analytics data"""
        # Create a test goal
        self.test_goal = frappe.get_doc({
            "doctype": "Membership Goal",
            "goal_name": "Test Growth Goal",
            "goal_type": "Member Count Growth",
            "goal_year": now_datetime().year,
            "target_value": 100,
            "start_date": frappe.utils.get_year_start(frappe.utils.today()),
            "end_date": frappe.utils.get_year_ending(frappe.utils.today()),
            "status": "Active"
        })
        self.test_goal.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        # Create a test alert rule
        self.test_alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Alert Rule",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 1000,
            "check_frequency": "Daily",
            "send_email": 0,
            "send_system_notification": 1
        })
        self.test_alert_rule.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        # Create a test snapshot
        self.test_snapshot = frappe.get_doc({
            "doctype": "Membership Analytics Snapshot",
            "snapshot_date": getdate(),
            "snapshot_type": "Daily",
            "period": "Test Period",
            "total_members": 100,
            "active_members": 95,
            "new_members": 10,
            "lost_members": 2
        })
        self.test_snapshot.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        frappe.db.commit()
    
    def test_analytics_page_access(self):
        """Test access to membership analytics page"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_dashboard_data
        
        # Test administrator access
        frappe.set_user(self.admin_user)
        try:
            data = get_dashboard_data()
            self.assertIsNotNone(data)
            self.assertIn("summary", data)
        except frappe.PermissionError:
            self.fail("Administrator should have access to analytics page")

        # Test manager access
        frappe.set_user(self.manager_user)
        try:
            data = get_dashboard_data()
            self.assertIsNotNone(data)
        except frappe.PermissionError:
            self.fail("Manager should have access to analytics page")

        # Test board member access
        frappe.set_user(self.board_member_user)
        try:
            data = get_dashboard_data()
            self.assertIsNotNone(data)
        except frappe.PermissionError:
            self.fail("Board member should have access to analytics page")

        # Test regular member - should NOT have access
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            data = get_dashboard_data()

        # Test user with no roles - should NOT have access
        frappe.set_user(self.no_role_user)
        with self.assertRaises(frappe.PermissionError):
            data = get_dashboard_data()

        frappe.set_user("Administrator")
    
    def test_goal_permissions(self):
        """Test permissions for Membership Goal doctype"""
        # Administrator - full access
        frappe.set_user(self.admin_user)

        # Should be able to read
        goal = frappe.get_doc("Membership Goal", self.test_goal.name)
        self.assertEqual(goal.goal_name, "Test Growth Goal")
        
        # Should be able to create
        new_goal = frappe.get_doc({
            "doctype": "Membership Goal",
            "goal_name": "Admin Test Goal",
            "goal_type": "Revenue Growth",
            "goal_year": now_datetime().year,
            "target_value": 50000,
            "start_date": frappe.utils.get_year_start(frappe.utils.today()),
            "end_date": frappe.utils.get_year_ending(frappe.utils.today())
        })
        new_goal.insert()
        # Membership Goal autoname is GOAL-{goal_year}-{####}, so look it up by goal_name.
        self.assertTrue(frappe.db.exists("Membership Goal", {"goal_name": "Admin Test Goal"}))

        # Should be able to update
        goal.target_value = 150
        goal.save()

        # Should be able to delete
        new_goal.delete()

        # Manager (Verenigingen Staff) - read only per Membership Goal permissions
        frappe.set_user(self.manager_user)

        # Should be able to read
        goal = frappe.get_doc("Membership Goal", self.test_goal.name)
        self.assertIsNotNone(goal)

        # Should NOT be able to create (Staff has read-only on Membership Goal)
        with self.assertRaises(frappe.PermissionError):
            manager_goal = frappe.get_doc({
                "doctype": "Membership Goal",
                "goal_name": "Manager Test Goal",
                "goal_type": "Retention Rate",
                "goal_year": now_datetime().year,
                "target_value": 90,
                "start_date": frappe.utils.get_year_start(frappe.utils.today()),
                "end_date": frappe.utils.get_year_ending(frappe.utils.today())
            })
            manager_goal.insert()

        # Board Member - read only
        frappe.set_user(self.board_member_user)

        # Should be able to read
        goal = frappe.get_doc("Membership Goal", self.test_goal.name)
        self.assertIsNotNone(goal)

        # Should NOT be able to create
        with self.assertRaises(frappe.PermissionError):
            board_goal = frappe.get_doc({
                "doctype": "Membership Goal",
                "goal_name": "Board Test Goal",
                "goal_type": "Member Count Growth",
                "goal_year": now_datetime().year,
                "target_value": 200,
                "start_date": frappe.utils.get_year_start(frappe.utils.today()),
                "end_date": frappe.utils.get_year_ending(frappe.utils.today())
            })
            board_goal.insert()
        
        # Should NOT be able to update
        with self.assertRaises(frappe.PermissionError):
            goal.target_value = 200
            goal.save()
        
        # Regular Member - no access. frappe.get_doc() does not enforce read
        # permission, so assert via the explicit read permission check.
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Membership Goal", self.test_goal.name).check_permission("read")

        frappe.set_user("Administrator")

    def test_alert_rule_permissions(self):
        """Test permissions for Analytics Alert Rule doctype"""
        # Administrator - full access
        frappe.set_user(self.admin_user)

        # Should be able to read
        alert = frappe.get_doc("Analytics Alert Rule", self.test_alert_rule.name)
        self.assertEqual(alert.rule_name, "Test Alert Rule")
        
        # Should be able to create
        new_alert = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Admin Alert Test",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Churn Rate",
            "condition": "Greater Than",
            "threshold_value": 10,
            "check_frequency": "Daily"
        })
        new_alert.insert()
        
        # Should be able to update
        new_alert.threshold_value = 15
        new_alert.save()
        
        # Should be able to delete
        new_alert.delete()
        
        # Board Member - read only
        frappe.set_user(self.board_member_user)

        # Should be able to read
        alert = frappe.get_doc("Analytics Alert Rule", self.test_alert_rule.name)
        self.assertIsNotNone(alert)

        # Should NOT be able to create
        with self.assertRaises(frappe.PermissionError):
            board_alert = frappe.get_doc({
                "doctype": "Analytics Alert Rule",
                "rule_name": "Board Alert Test",
                "is_active": 1,
                "alert_type": "Threshold",
                "metric": "Revenue",
                "condition": "Less Than",
                "threshold_value": 50000,
                "check_frequency": "Weekly"
            })
            board_alert.insert()
        
        # Manager - no access to alert rules. frappe.get_doc() does not enforce
        # read permission, so assert via the explicit read permission check.
        frappe.set_user(self.manager_user)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                "Analytics Alert Rule", self.test_alert_rule.name
            ).check_permission("read")

        # Regular Member - no access
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                "Analytics Alert Rule", self.test_alert_rule.name
            ).check_permission("read")

        frappe.set_user("Administrator")

    def test_snapshot_permissions(self):
        """Test permissions for Membership Analytics Snapshot doctype"""
        # Administrator - full access
        frappe.set_user(self.admin_user)

        # Should be able to read
        snapshot = frappe.get_doc("Membership Analytics Snapshot", self.test_snapshot.name)
        self.assertEqual(snapshot.total_members, 100)

        # Should be able to create via API
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import create_snapshot
        # "Manual" is not a snapshot_type option. Use a different date from the
        # setUp fixture's, since create_snapshot() rejects a duplicate (date, type).
        new_snapshot_name = create_snapshot("Daily", add_days(getdate(), -1))
        self.assertTrue(frappe.db.exists("Membership Analytics Snapshot", new_snapshot_name))

        # Manager - read only
        frappe.set_user(self.manager_user)

        # Should be able to read
        snapshot = frappe.get_doc("Membership Analytics Snapshot", self.test_snapshot.name)
        self.assertIsNotNone(snapshot)

        # Should NOT be able to write
        with self.assertRaises(frappe.PermissionError):
            snapshot.total_members = 150
            snapshot.save()

        # Board Member - read only
        frappe.set_user(self.board_member_user)

        # Should be able to read
        snapshot = frappe.get_doc("Membership Analytics Snapshot", self.test_snapshot.name)
        self.assertIsNotNone(snapshot)

        # Regular Member - no access
        frappe.set_user(self.regular_member_user)

        # Should NOT be able to read. frappe.get_doc() does not enforce read
        # permission, so assert via the explicit read permission check.
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                "Membership Analytics Snapshot", self.test_snapshot.name
            ).check_permission("read")

        frappe.set_user("Administrator")

    def test_predictive_analytics_access(self):
        """Test access to predictive analytics functions"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import get_predictive_analytics
        
        # Administrator - should have access
        frappe.set_user(self.admin_user)
        try:
            data = get_predictive_analytics(months_ahead=6)
            self.assertIsNotNone(data)
            self.assertIn("member_growth_forecast", data)
        except frappe.PermissionError:
            self.fail("Administrator should have access to predictive analytics")

        # Manager - should have access
        frappe.set_user(self.manager_user)
        try:
            data = get_predictive_analytics(months_ahead=6)
            self.assertIsNotNone(data)
        except frappe.PermissionError:
            self.fail("Manager should have access to predictive analytics")

        # Board Member - should have access
        frappe.set_user(self.board_member_user)
        try:
            data = get_predictive_analytics(months_ahead=6)
            self.assertIsNotNone(data)
        except frappe.PermissionError:
            self.fail("Board member should have access to predictive analytics")

        # Regular Member - should NOT have access
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            data = get_predictive_analytics(months_ahead=6)

        frappe.set_user("Administrator")
    
    def test_export_permissions(self):
        """Test export functionality permissions"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import export_dashboard_data
        
        # Administrator - should be able to export
        frappe.set_user(self.admin_user)
        try:
            # Test Excel export
            data = export_dashboard_data(format="excel")
            # Since this modifies frappe.response, we just check it doesn't raise an error
        except frappe.PermissionError:
            self.fail("Administrator should be able to export data")

        # Manager - should be able to export
        frappe.set_user(self.manager_user)
        try:
            data = export_dashboard_data(format="csv")
        except frappe.PermissionError:
            self.fail("Manager should be able to export data")

        # Board Member - should be able to export
        frappe.set_user(self.board_member_user)
        try:
            data = export_dashboard_data(format="csv")
        except frappe.PermissionError:
            self.fail("Board member should be able to export data")

        # Regular Member - should NOT be able to export
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            data = export_dashboard_data(format="excel")

        frappe.set_user("Administrator")
    
    def test_alert_log_permissions(self):
        """Test permissions for Analytics Alert Log"""
        # Create a test log entry
        # BaseTestCase handles permissions through custom framework
        test_log = frappe.get_doc({
            "doctype": "Analytics Alert Log",
            "alert_rule": self.test_alert_rule.name,
            "triggered_at": now_datetime(),
            "metric_value": 150,
            "threshold_value": 100,
            "condition": "Greater Than"
        })
        test_log.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately

        # Administrator - full access
        frappe.set_user(self.admin_user)
        log = frappe.get_doc("Analytics Alert Log", test_log.name)
        self.assertEqual(log.metric_value, 150)

        # Board Member - read only
        frappe.set_user(self.board_member_user)
        log = frappe.get_doc("Analytics Alert Log", test_log.name)
        self.assertIsNotNone(log)

        # Manager - no access to alert logs. frappe.get_doc() does not enforce
        # read permission, so assert via the explicit read permission check.
        frappe.set_user(self.manager_user)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Analytics Alert Log", test_log.name).check_permission("read")

        # Regular Member - no access
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Analytics Alert Log", test_log.name).check_permission("read")

        frappe.set_user("Administrator")
    
    def test_goal_creation_api(self):
        """Test goal creation through API with permissions"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import create_goal
        
        goal_data = {
            "goal_name": "API Test Goal",
            "goal_type": "Member Count Growth",
            "goal_year": now_datetime().year,
            "target_value": 200,
            "start_date": frappe.utils.get_year_start(frappe.utils.today()),
            "end_date": frappe.utils.get_year_ending(frappe.utils.today()),
            "description": "Test goal created via API"
        }
        
        # Administrator - should succeed
        frappe.set_user(self.admin_user)
        goal_name = create_goal(goal_data)
        self.assertTrue(frappe.db.exists("Membership Goal", {"goal_name": "API Test Goal"}))
        frappe.delete_doc("Membership Goal", goal_name)

        # Manager (Verenigingen Staff) - should fail (read-only on Membership Goal)
        frappe.set_user(self.manager_user)
        goal_data["goal_name"] = "Manager API Goal"
        with self.assertRaises(frappe.PermissionError):
            create_goal(goal_data)

        # Board Member - should fail
        frappe.set_user(self.board_member_user)
        goal_data["goal_name"] = "Board API Goal"
        with self.assertRaises(frappe.PermissionError):
            create_goal(goal_data)

        # Regular Member - should fail
        frappe.set_user(self.regular_member_user)
        goal_data["goal_name"] = "Member API Goal"
        with self.assertRaises(frappe.PermissionError):
            create_goal(goal_data)

        frappe.set_user("Administrator")
    
    def tearDown(self):
        """Clean up test data"""
        # Restore Administrator in case a test left a restricted user active
        # (e.g. on early failure) before running cleanup.
        frappe.set_user("Administrator")

        # Delete test data in reverse order of dependencies
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Log`")
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Rule`")
        frappe.db.sql("DELETE FROM `tabMembership Analytics Snapshot`")
        frappe.db.sql("DELETE FROM `tabMembership Goal`")
        
        # Delete test members (first_name is uniquified per run, so the auto-created Customer
        # cannot collide across runs; the raw DELETE leaves those Customers behind harmlessly).
        frappe.db.sql("DELETE FROM `tabMember` WHERE last_name = 'Analytics'")

        frappe.db.commit()

        super().tearDown()


class TestMembershipAnalyticsDataSecurity(BaseTestCase):
    """Test data security and isolation in analytics"""
    
    def setUp(self):
        super().setUp()
        # BaseTestCase handles permissions through custom framework
        
        # Create test chapters
        self.chapter_a = self.create_test_chapter("Chapter A")
        self.chapter_b = self.create_test_chapter("Chapter B")
        
        # Create chapter managers
        self.manager_a = self.create_chapter_manager("manager_a@test.com", self.chapter_a)
        self.manager_b = self.create_chapter_manager("manager_b@test.com", self.chapter_b)
        
        # Create members in different chapters
        self.create_chapter_members(self.chapter_a, 10)
        self.create_chapter_members(self.chapter_b, 15)
    
    def create_test_chapter(self, name):
        """Create a test chapter, returns chapter name"""
        if frappe.db.exists("Chapter", name):
            return name
        chapter = super().create_test_chapter(chapter_name=name)
        return chapter.name
    
    def create_chapter_manager(self, email, chapter):
        """Create a chapter manager user"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0].title(),
                "enabled": 1,
                "new_password": "testpass123"
            })
            user.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        # Add Verenigingen Staff role
        user.roles = []
        user.append("roles", {"role": "Verenigingen Staff"})
        user.save()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately

        # Post the Rule-5 cap, the analytics endpoints (@high_security_api) require an
        # assigned role PROFILE, not a bare Staff role. Grant the matching profile.
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(email, "Verenigingen Staff")

        # Link user to chapter via Member if one exists for this user
        # Note: Chapter Member requires a Member reference, not User
        member_name = frappe.db.get_value("Member", {"user": email}, "name")
        if member_name:
            chapter_doc = frappe.get_doc("Chapter", chapter)
            # Check if member already exists in chapter
            member_exists = any(cm.member == member_name for cm in chapter_doc.members)
            if not member_exists:
                chapter_doc.append("members", {
                    "member": member_name,
                    "chapter_join_date": frappe.utils.today(),
                    "enabled": 1,
                    "status": "Active"
                })
                chapter_doc.save()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
        
        return email
    
    def create_chapter_members(self, chapter, count):
        """Create test members in a chapter"""
        # Per-call unique token so the auto-created Customer (named after the member's
        # full_name) never collides with a Customer left behind by a previous/crashed run.
        token = frappe.generate_hash(length=6)
        chapter_doc = frappe.get_doc("Chapter", chapter)
        for i in range(count):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Test{chapter}{token}",
                "last_name": f"Member{i}",
                "email": f"{chapter.lower().replace(' ', '')}member{i}{token}@test.com",
                "status": "Active",
                "current_chapter": chapter,
                "member_since": frappe.utils.add_months(frappe.utils.getdate(), -i)
            })
            member.insert()  # VereningingenTestCase (via BaseTestCase) handles permissions appropriately
            # The chapter segmentation analytics joins via the Chapter Member child
            # table (status='Active'), not Member.current_chapter, so add an Active
            # Chapter Member row for each member.
            chapter_doc.append("members", {
                "member": member.name,
                "chapter_join_date": frappe.utils.today(),
                "enabled": 1,
                "status": "Active",
            })
        chapter_doc.save()
    
    def test_chapter_data_isolation(self):
        """Test that chapter managers can only see their chapter's data"""
        # Note: This would require implementing chapter-based filtering in the analytics
        # For now, we test that the data structure supports filtering
        
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_dashboard_data
        
        # Test with chapter filter
        frappe.set_user(self.manager_a)
        data = get_dashboard_data(filters={"chapter": self.chapter_a})
        
        # Verify data structure supports filtering
        self.assertIsNotNone(data)
        self.assertIn("summary", data)
        
        # Test segmentation includes chapter data
        if "segmentation" in data and "by_chapter" in data["segmentation"]:
            chapter_data = data["segmentation"]["by_chapter"]
            # Should include chapter information
            self.assertTrue(any(c.get("name") == self.chapter_a for c in chapter_data))
    
    def test_sensitive_data_masking(self):
        """Test that sensitive member data is properly masked in analytics"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import analyze_churn_risk
        
        # BaseTestCase handles permissions through custom framework
        churn_data = analyze_churn_risk()
        
        # High risk members should not expose sensitive details
        if churn_data.get("high_risk_members"):
            for member in churn_data["high_risk_members"]:
                # Should have member name but not full personal details
                self.assertIn("member_name", member)
                self.assertNotIn("email", member)  # Email should not be exposed
                self.assertNotIn("phone", member)  # Phone should not be exposed
                self.assertNotIn("address", member)  # Address should not be exposed
    
    def tearDown(self):
        """Clean up test data"""
        # Restore Administrator in case a test left a restricted user active.
        frappe.set_user("Administrator")

        # Delete test members (names are uniquified per run, so the auto-created Customer
        # cannot collide across runs; the raw DELETE leaves those Customers behind harmlessly).
        frappe.db.sql("DELETE FROM `tabMember` WHERE first_name LIKE 'Test%'")

        # Delete chapter members + chapters. Chapter is prompt-named (the `name` IS the
        # chapter name; there is no `chapter_name` column) and create_test_chapter may
        # uniquify the name, so use the actual created chapter names. Chapter Member is a
        # child table keyed by `parent` (the Chapter); the old `member_email` column is gone.
        chapter_names = [
            getattr(c, "name", c)
            for c in (getattr(self, "chapter_a", None), getattr(self, "chapter_b", None))
            if c is not None
        ]
        if chapter_names:
            frappe.db.sql(
                "DELETE FROM `tabChapter Member` WHERE parent IN %(names)s",
                {"names": tuple(chapter_names)},
            )
            frappe.db.sql(
                "DELETE FROM `tabChapter` WHERE name IN %(names)s",
                {"names": tuple(chapter_names)},
            )
        
        frappe.db.commit()
        
        super().tearDown()


if __name__ == "__main__":
    unittest.main()