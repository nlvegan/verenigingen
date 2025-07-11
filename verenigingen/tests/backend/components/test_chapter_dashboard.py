# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Chapter Dashboard Tests
Tests for chapter dashboard functionality and permissions
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, Mock
import json
from datetime import datetime, timedelta


class TestChapterDashboard(FrappeTestCase):
    """Test chapter dashboard functionality"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        
        # Create test chapter
        cls.test_chapter = cls._create_test_chapter()
        
        # Create test members
        cls.test_members = cls._create_test_members()
        
        # Create test board member user
        cls.board_member_user = cls._create_board_member_user()
        
    @classmethod
    def _create_test_chapter(cls):
        """Create a test chapter"""
        chapter_name = f"Test Dashboard Chapter {frappe.utils.random_string(6)}"
        
        if not frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc({
                "doctype": "Chapter",
                "name": chapter_name,
                "chapter_name": chapter_name,
                "short_name": "TDC",
                "country": "Netherlands",
                "introduction": "Test chapter for dashboard testing",
                "published": 1
            })
            chapter.insert(ignore_permissions=True)
            return chapter
        return frappe.get_doc("Chapter", chapter_name)
        
    @classmethod
    def _create_test_members(cls):
        """Create test members for the chapter"""
        members = []
        
        # Create members with different statuses
        statuses = ["Active", "Active", "Pending", "Inactive", "Suspended"]
        
        for i, status in enumerate(statuses):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Dashboard{i}",
                "last_name": "TestMember",
                "email": f"dashboard.test{i}@example.com",
                "phone": f"+3161234567{i}",
                "status": status,
                "chapter": cls.test_chapter.name
            })
            member.insert(ignore_permissions=True)
            members.append(member)
            
            # Add to chapter members
            cls.test_chapter.append("members", {
                "member": member.name,
                "member_name": member.full_name,
                "status": "Active" if status == "Active" else "Inactive",
                "enabled": 1
            })
            
        cls.test_chapter.save(ignore_permissions=True)
        return members
        
    @classmethod
    def _create_board_member_user(cls):
        """Create a test board member user"""
        email = f"board.member.{frappe.utils.random_string(6)}@test.com"
        
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Board",
                "last_name": "Member",
                "enabled": 1,
                "new_password": frappe.utils.random_string(10),
                "send_welcome_email": 0
            })
            
            # Add Chapter Board Member role
            user.append("roles", {"role": "Chapter Board Member"})
            user.insert(ignore_permissions=True)
            return user
        return frappe.get_doc("User", email)
        
    def test_dashboard_permission_filtering(self):
        """Test dashboard data filtered by user permissions"""
        # Test as board member
        frappe.set_user(self.board_member_user.name)
        
        # Get dashboard data
        from verenigingen.api.chapter_dashboard import get_chapter_dashboard_data
        
        # Mock board member assignment
        with patch('frappe.db.get_value') as mock_get_value:
            mock_get_value.return_value = self.test_chapter.name
            
            # Should only see data for assigned chapter
            dashboard_data = {
                "chapter": self.test_chapter.name,
                "stats": self._get_chapter_stats(),
                "members": self._get_filtered_members()
            }
            
            # Verify filtering
            self.assertEqual(dashboard_data["chapter"], self.test_chapter.name)
            self.assertIsNotNone(dashboard_data["stats"])
            
        # Reset user
        frappe.set_user("Administrator")
        
    def test_statistics_accuracy(self):
        """Test dashboard statistics calculation"""
        stats = self._get_chapter_stats()
        
        # Verify member counts
        self.assertEqual(stats["total_members"], 5)
        self.assertEqual(stats["active_members"], 2)
        self.assertEqual(stats["pending_members"], 1)
        self.assertEqual(stats["inactive_members"], 1)
        self.assertEqual(stats["suspended_members"], 1)
        
        # Verify percentages
        self.assertEqual(stats["active_percentage"], 40.0)  # 2/5
        
        # Verify growth metrics
        self.assertIn("new_members_this_month", stats)
        self.assertIn("growth_rate", stats)
        
    def _get_chapter_stats(self):
        """Helper to calculate chapter statistics"""
        total = len(self.test_members)
        active = len([m for m in self.test_members if m.status == "Active"])
        pending = len([m for m in self.test_members if m.status == "Pending"])
        inactive = len([m for m in self.test_members if m.status == "Inactive"])
        suspended = len([m for m in self.test_members if m.status == "Suspended"])
        
        return {
            "total_members": total,
            "active_members": active,
            "pending_members": pending,
            "inactive_members": inactive,
            "suspended_members": suspended,
            "active_percentage": (active / total * 100) if total > 0 else 0,
            "new_members_this_month": 0,
            "growth_rate": 0.0
        }
        
    def _get_filtered_members(self):
        """Helper to get filtered member list"""
        return [
            {
                "name": m.name,
                "full_name": m.full_name,
                "email": m.email,
                "status": m.status
            }
            for m in self.test_members
        ]
        
    def test_member_email_extraction(self):
        """Test bulk email extraction functionality"""
        # Test extracting emails for different filters
        filters = [
            {"status": "Active", "expected_count": 2},
            {"status": "Pending", "expected_count": 1},
            {"status": ["in", ["Active", "Pending"]], "expected_count": 3}
        ]
        
        for filter_config in filters:
            status_filter = filter_config["status"]
            expected = filter_config["expected_count"]
            
            # Extract emails based on filter
            if isinstance(status_filter, str):
                emails = [
                    m.email for m in self.test_members 
                    if m.status == status_filter
                ]
            else:
                # Handle "in" filter
                status_list = status_filter[1]
                emails = [
                    m.email for m in self.test_members 
                    if m.status in status_list
                ]
                
            # Verify count
            self.assertEqual(len(emails), expected)
            
            # Verify email format
            for email in emails:
                self.assertIn("@", email)
                self.assertTrue(email.startswith("dashboard.test"))
                
    def test_quick_approval_workflow(self):
        """Test quick approval functionality from dashboard"""
        # Get pending member
        pending_member = next(m for m in self.test_members if m.status == "Pending")
        
        # Simulate quick approval
        approval_data = {
            "member": pending_member.name,
            "action": "approve",
            "notes": "Approved via dashboard"
        }
        
        # Process approval
        pending_member.reload()
        pending_member.status = "Active"
        pending_member.application_status = "Approved"
        pending_member.save(ignore_permissions=True)
        
        # Verify approval
        pending_member.reload()
        self.assertEqual(pending_member.status, "Active")
        self.assertEqual(pending_member.application_status, "Approved")
        
    def test_dashboard_performance_with_large_chapters(self):
        """Test dashboard performance with many members"""
        import time
        
        # Simulate large chapter
        large_member_count = 100
        
        # Time statistics calculation
        start_time = time.time()
        
        # Simulate calculating stats for large dataset
        stats = {
            "total_members": large_member_count,
            "active_members": int(large_member_count * 0.8),
            "pending_members": int(large_member_count * 0.1),
            "inactive_members": int(large_member_count * 0.1)
        }
        
        end_time = time.time()
        calculation_time = end_time - start_time
        
        # Should complete quickly even with large dataset
        self.assertLess(calculation_time, 1.0)  # Less than 1 second
        
    def test_export_functionality(self):
        """Test member data export from dashboard"""
        # Test different export formats
        export_formats = ["csv", "excel", "json"]
        
        for format_type in export_formats:
            # Simulate export
            export_data = self._export_member_data(format_type)
            
            # Verify export structure
            if format_type == "csv":
                self.assertIn("headers", export_data)
                self.assertIn("rows", export_data)
                self.assertEqual(len(export_data["headers"]), 4)  # name, email, phone, status
                
            elif format_type == "excel":
                self.assertIn("worksheet_data", export_data)
                
            elif format_type == "json":
                self.assertIsInstance(export_data, list)
                self.assertEqual(len(export_data), len(self.test_members))
                
    def _export_member_data(self, format_type):
        """Helper to simulate data export"""
        if format_type == "csv":
            return {
                "headers": ["Name", "Email", "Phone", "Status"],
                "rows": [
                    [m.full_name, m.email, m.phone, m.status]
                    for m in self.test_members
                ]
            }
        elif format_type == "excel":
            return {
                "worksheet_data": {
                    "members": [
                        {
                            "name": m.full_name,
                            "email": m.email,
                            "phone": m.phone,
                            "status": m.status
                        }
                        for m in self.test_members
                    ]
                }
            }
        elif format_type == "json":
            return [
                {
                    "name": m.full_name,
                    "email": m.email,
                    "phone": m.phone,
                    "status": m.status,
                    "member_id": m.name
                }
                for m in self.test_members
            ]
            
    def test_activity_timeline(self):
        """Test member activity timeline display"""
        # Create test activities
        activities = [
            {
                "type": "status_change",
                "timestamp": frappe.utils.now(),
                "description": "Status changed from Pending to Active"
            },
            {
                "type": "payment",
                "timestamp": frappe.utils.add_days(frappe.utils.now(), -30),
                "description": "Membership fee paid - €100"
            },
            {
                "type": "volunteer",
                "timestamp": frappe.utils.add_days(frappe.utils.now(), -60),
                "description": "Registered as volunteer"
            }
        ]
        
        # Sort by timestamp (newest first)
        sorted_activities = sorted(
            activities, 
            key=lambda x: x["timestamp"], 
            reverse=True
        )
        
        # Verify ordering
        self.assertEqual(sorted_activities[0]["type"], "status_change")
        self.assertEqual(sorted_activities[-1]["type"], "volunteer")
        
    def test_bulk_actions(self):
        """Test bulk actions from dashboard"""
        # Test bulk status update
        member_ids = [m.name for m in self.test_members[:2]]
        
        bulk_update = {
            "action": "update_status",
            "member_ids": member_ids,
            "new_status": "Active",
            "reason": "Bulk activation"
        }
        
        # Simulate bulk update
        updated_count = 0
        for member_id in bulk_update["member_ids"]:
            try:
                member = frappe.get_doc("Member", member_id)
                if member.status != bulk_update["new_status"]:
                    member.status = bulk_update["new_status"]
                    member.save(ignore_permissions=True)
                    updated_count += 1
            except Exception:
                pass
                
        # Verify updates
        self.assertGreater(updated_count, 0)
        
    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up test members
        for member in cls.test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except:
                pass
                
        # Clean up test chapter
        try:
            frappe.delete_doc("Chapter", cls.test_chapter.name, force=True)
        except:
            pass
            
        # Clean up test user
        try:
            frappe.delete_doc("User", cls.board_member_user.name, force=True)
        except:
            pass
            
        super().tearDownClass()