"""
Secure performance testing for member list optimizations

Tests the N+1 query elimination while maintaining security compliance
"""

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSecureMemberListPerformance(EnhancedTestCase):
    """Test performance improvements in member listing without compromising security"""

    def setUp(self):
        super().setUp()
        # Create test data using Enhanced Test Factory (secure, no permission bypasses)
        self.test_members = []
        self.test_chapters = []
        
        # Create chapters first using enhanced factory methods  
        # Get an existing region to avoid link validation errors
        existing_regions = frappe.get_all("Region", limit=1, pluck="name")
        region_name = existing_regions[0] if existing_regions else None
        
        if not region_name:
            # Create a region if none exist
            region = frappe.get_doc({
                "doctype": "Region", 
                "region_name": "TEST-Region-Performance"
            })
            region.insert()
            region_name = region.name
        
        for i in range(3):
            chapter = self.ensure_test_chapter(
                chapter_name=f"TEST-Chapter-{i+1}",
                attributes={"region": region_name}
            )
            self.test_chapters.append(chapter)
        
        # Create members with chapter relationships
        for i in range(10):
            member = self.create_test_member(
                first_name=f"Test",
                last_name=f"Member {i+1}",
                birth_date="1990-01-01"
            )
            self.test_members.append(member)
            
            # Assign to chapter using secure method
            from verenigingen.api.member_management import assign_member_to_chapter
            assign_member_to_chapter(member.name, self.test_chapters[i % 3].name)

    def test_n_plus_1_prevention_query_count(self):
        """Test that member listing uses optimized queries instead of N+1 pattern"""
        
        # Test the optimized API
        with self.assertQueryCount(3):  # Should use exactly 3 queries
            from verenigingen.api.member_management import get_members_with_chapter_info
            
            result = get_members_with_chapter_info(limit=10)
            
            # Validate results
            self.assertTrue(result["success"])
            self.assertEqual(len(result["members"]), 10)
            
            # Verify query optimization metadata
            self.assertEqual(result["query_optimization"]["queries_used"], 3)
            self.assertTrue(result["query_optimization"]["n_plus_1_prevented"])
            
            # Verify data completeness
            for member in result["members"]:
                self.assertIn("name", member)
                self.assertIn("full_name", member)
                self.assertIn("chapters", member)
                
                # Members should have chapter info (many-to-many relationship)
                if member["chapters"]:
                    chapter = member["chapters"][0]
                    self.assertIn("chapter_name", chapter)
                    self.assertIn("region", chapter)

    def test_permission_filtering_maintained(self):
        """Verify that query optimization doesn't bypass security"""
        
        # Create test user with limited permissions
        limited_user = self.create_test_user_with_roles(
            email="limited@test.invalid",
            roles=["Verenigingen Member"]  # Limited role that should be denied
        )
        
        # Test with restricted permissions - should fail
        # EnhancedTestCase handles permissions automatically
        
        try:
            from verenigingen.api.member_management import get_members_with_chapter_info
            
            # This should fail due to insufficient permissions
            from verenigingen.utils.error_handling import PermissionError as VPermissionError
            with self.assertRaises(VPermissionError):
                get_members_with_chapter_info(limit=5)
                
        finally:
            # EnhancedTestCase handles permissions automatically
            pass

    def test_large_batch_security_limits(self):
        """Test that optimization respects security limits for large requests"""
        
        from verenigingen.api.member_management import get_members_with_chapter_info
        
        # Request more than allowed limit
        result = get_members_with_chapter_info(limit=1000)
        
        # Should enforce security limits
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["members"]), 500)  # Enforced max limit

    def test_filter_sanitization(self):
        """Test that input filters are properly sanitized"""
        
        from verenigingen.api.member_management import get_members_with_chapter_info
        
        # Try to pass potentially dangerous filters
        malicious_filters = {
            "status": "Active",  # Allowed
            "docstatus": 2,      # Should be filtered out
            "sql_injection": "'; DROP TABLE tabMember; --"  # Should be ignored
        }
        
        result = get_members_with_chapter_info(filters=malicious_filters, limit=5)
        
        # Should succeed with sanitized filters
        self.assertTrue(result["success"])
        # Should not crash or cause security issues

