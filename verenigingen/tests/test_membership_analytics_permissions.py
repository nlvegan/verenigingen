# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import frappe
import unittest
from frappe.utils import now_datetime, add_months, getdate
from verenigingen.tests.test_utils import BaseTestCase


class TestMembershipAnalyticsPermissions(BaseTestCase):
    """Test access permissions for membership analytics features"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Create test users with different roles
        cls.admin_user = cls.create_test_user("admin@test.com", [
            "Verenigingen Administrator",
            "System Manager"
        ])
        
        cls.manager_user = cls.create_test_user("manager@test.com", [
            "Verenigingen Manager"
        ])
        
        cls.board_member_user = cls.create_test_user("board@test.com", [
            "National Board Member"
        ])
        
        cls.regular_member_user = cls.create_test_user("member@test.com", [
            "Verenigingen Member"
        ])
        
        cls.no_role_user = cls.create_test_user("norole@test.com", [])
        
    @classmethod
    def create_test_user(cls, email, roles):
        """Create a test user with specified roles"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0].title(),
                "enabled": 1,
                "new_password": "testpass123",
                "roles": []
            })
            user.insert(ignore_permissions=True)
        
        # Clear existing roles
        user.roles = []
        
        # Add specified roles
        for role in roles:
            user.append("roles", {"role": role})
        
        user.save(ignore_permissions=True)
        frappe.db.commit()
        
        return email
    
    def setUp(self):
        super().setUp()
        # Reset to administrator for setup
        frappe.set_user("Administrator")
        
        # Create test data
        self.create_test_membership_data()
        self.create_test_analytics_data()
    
    def create_test_membership_data(self):
        """Create test members and memberships"""
        # Create a few test members
        for i in range(5):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Test{i}",
                "last_name": "Analytics",
                "email": f"analytics{i}@test.com",
                "status": "Active",
                "member_since": add_months(getdate(), -i)
            })
            member.insert(ignore_permissions=True)
    
    def create_test_analytics_data(self):
        """Create test analytics data"""
        # Create a test goal
        self.test_goal = frappe.get_doc({
            "doctype": "Membership Goal",
            "goal_name": "Test Growth Goal",
            "goal_type": "Member Count Growth",
            "goal_year": now_datetime().year,
            "target_value": 100,
            "start_date": frappe.utils.year_start(),
            "end_date": frappe.utils.year_end(),
            "status": "Active"
        })
        self.test_goal.insert(ignore_permissions=True)
        
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
        self.test_alert_rule.insert(ignore_permissions=True)
        
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
        self.test_snapshot.insert(ignore_permissions=True)
        
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
            "start_date": frappe.utils.year_start(),
            "end_date": frappe.utils.year_end()
        })
        new_goal.insert()
        self.assertTrue(frappe.db.exists("Membership Goal", "Admin Test Goal"))
        
        # Should be able to update
        goal.target_value = 150
        goal.save()
        
        # Should be able to delete
        new_goal.delete()
        
        # Manager - read and write, no delete
        frappe.set_user(self.manager_user)
        
        # Should be able to read
        goal = frappe.get_doc("Membership Goal", self.test_goal.name)
        self.assertIsNotNone(goal)
        
        # Should be able to create
        manager_goal = frappe.get_doc({
            "doctype": "Membership Goal",
            "goal_name": "Manager Test Goal",
            "goal_type": "Retention Rate",
            "goal_year": now_datetime().year,
            "target_value": 90,
            "start_date": frappe.utils.year_start(),
            "end_date": frappe.utils.year_end()
        })
        manager_goal.insert()
        
        # Should be able to update
        manager_goal.target_value = 95
        manager_goal.save()
        
        # Should NOT be able to delete
        with self.assertRaises(frappe.PermissionError):
            manager_goal.delete()
        
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
                "start_date": frappe.utils.year_start(),
                "end_date": frappe.utils.year_end()
            })
            board_goal.insert()
        
        # Should NOT be able to update
        with self.assertRaises(frappe.PermissionError):
            goal.target_value = 200
            goal.save()
        
        # Regular Member - no access
        frappe.set_user(self.regular_member_user)
        
        # Should NOT be able to read
        with self.assertRaises(frappe.PermissionError):
            goal = frappe.get_doc("Membership Goal", self.test_goal.name)
    
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
        
        # Manager - no access to alert rules
        frappe.set_user(self.manager_user)
        
        # Should NOT be able to read
        with self.assertRaises(frappe.PermissionError):
            alert = frappe.get_doc("Analytics Alert Rule", self.test_alert_rule.name)
        
        # Regular Member - no access
        frappe.set_user(self.regular_member_user)
        
        # Should NOT be able to read
        with self.assertRaises(frappe.PermissionError):
            alert = frappe.get_doc("Analytics Alert Rule", self.test_alert_rule.name)
    
    def test_snapshot_permissions(self):
        """Test permissions for Membership Analytics Snapshot doctype"""
        # Administrator - full access
        frappe.set_user(self.admin_user)
        
        # Should be able to read
        snapshot = frappe.get_doc("Membership Analytics Snapshot", self.test_snapshot.name)
        self.assertEqual(snapshot.total_members, 100)
        
        # Should be able to create via API
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import create_snapshot
        new_snapshot_name = create_snapshot("Manual")
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
        
        # Should NOT be able to read
        with self.assertRaises(frappe.PermissionError):
            snapshot = frappe.get_doc("Membership Analytics Snapshot", self.test_snapshot.name)
    
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
    
    def test_alert_log_permissions(self):
        """Test permissions for Analytics Alert Log"""
        # Create a test log entry
        frappe.set_user("Administrator")
        test_log = frappe.get_doc({
            "doctype": "Analytics Alert Log",
            "alert_rule": self.test_alert_rule.name,
            "triggered_at": now_datetime(),
            "metric_value": 150,
            "threshold_value": 100,
            "condition": "Greater Than"
        })
        test_log.insert(ignore_permissions=True)
        
        # Administrator - full access
        frappe.set_user(self.admin_user)
        log = frappe.get_doc("Analytics Alert Log", test_log.name)
        self.assertEqual(log.metric_value, 150)
        
        # Board Member - read only
        frappe.set_user(self.board_member_user)
        log = frappe.get_doc("Analytics Alert Log", test_log.name)
        self.assertIsNotNone(log)
        
        # Manager - no access to alert logs
        frappe.set_user(self.manager_user)
        with self.assertRaises(frappe.PermissionError):
            log = frappe.get_doc("Analytics Alert Log", test_log.name)
        
        # Regular Member - no access
        frappe.set_user(self.regular_member_user)
        with self.assertRaises(frappe.PermissionError):
            log = frappe.get_doc("Analytics Alert Log", test_log.name)
    
    def test_goal_creation_api(self):
        """Test goal creation through API with permissions"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import create_goal
        
        goal_data = {
            "goal_name": "API Test Goal",
            "goal_type": "Member Count Growth",
            "goal_year": now_datetime().year,
            "target_value": 200,
            "start_date": frappe.utils.year_start(),
            "end_date": frappe.utils.year_end(),
            "description": "Test goal created via API"
        }
        
        # Administrator - should succeed
        frappe.set_user(self.admin_user)
        goal_name = create_goal(goal_data)
        self.assertTrue(frappe.db.exists("Membership Goal", {"goal_name": "API Test Goal"}))
        frappe.delete_doc("Membership Goal", goal_name)
        
        # Manager - should succeed
        frappe.set_user(self.manager_user)
        goal_data["goal_name"] = "Manager API Goal"
        goal_name = create_goal(goal_data)
        self.assertTrue(frappe.db.exists("Membership Goal", {"goal_name": "Manager API Goal"}))
        
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
    
    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")
        
        # Delete test data in reverse order of dependencies
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Log`")
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Rule`")
        frappe.db.sql("DELETE FROM `tabMembership Analytics Snapshot`")
        frappe.db.sql("DELETE FROM `tabMembership Goal`")
        
        # Delete test members
        frappe.db.sql("DELETE FROM `tabMember` WHERE last_name = 'Analytics'")
        
        frappe.db.commit()
        
        super().tearDown()


class TestMembershipAnalyticsDataSecurity(BaseTestCase):
    """Test data security and isolation in analytics"""
    
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        
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
        """Create a test chapter"""
        if not frappe.db.exists("Chapter", name):
            chapter = frappe.get_doc({
                "doctype": "Chapter",
                "chapter_name": name,
                "is_active": 1
            })
            chapter.insert(ignore_permissions=True)
            return chapter.name
        return name
    
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
            user.insert(ignore_permissions=True)
        
        # Add Verenigingen Manager role
        user.roles = []
        user.append("roles", {"role": "Verenigingen Manager"})
        user.save(ignore_permissions=True)
        
        # Link to chapter
        if not frappe.db.exists("Chapter Member", {"chapter": chapter, "member_email": email}):
            chapter_member = frappe.get_doc({
                "doctype": "Chapter Member",
                "chapter": chapter,
                "member_email": email,
                "role": "Manager",
                "is_active": 1
            })
            chapter_member.insert(ignore_permissions=True)
        
        return email
    
    def create_chapter_members(self, chapter, count):
        """Create test members in a chapter"""
        for i in range(count):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Test{chapter}",
                "last_name": f"Member{i}",
                "email": f"{chapter.lower().replace(' ', '')}member{i}@test.com",
                "status": "Active",
                "current_chapter": chapter,
                "member_since": frappe.utils.add_months(frappe.utils.getdate(), -i)
            })
            member.insert(ignore_permissions=True)
    
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
        
        frappe.set_user("Administrator")
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
        frappe.set_user("Administrator")
        
        # Delete test members
        frappe.db.sql("DELETE FROM `tabMember` WHERE first_name LIKE 'Test%'")
        
        # Delete chapter members
        frappe.db.sql("DELETE FROM `tabChapter Member` WHERE member_email LIKE '%@test.com'")
        
        # Delete test chapters
        frappe.db.sql("DELETE FROM `tabChapter` WHERE chapter_name IN ('Chapter A', 'Chapter B')")
        
        frappe.db.commit()
        
        super().tearDown()


if __name__ == "__main__":
    unittest.main()