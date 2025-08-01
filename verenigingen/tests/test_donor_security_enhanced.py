#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Donor Security Test Suite

Addresses QA feedback by implementing comprehensive real user permission testing.
This suite closes the gap in testing with actual Frappe users and Vereiningen Member roles.

Key Enhancements:
1. Real User Role Testing - Tests with actual User records and proper role assignments
2. Complete Permission Chain Validation - User → Member → Donor access chain
3. Production-Like Scenarios - Realistic concurrent access patterns
4. Enhanced API Security Testing - Whitelisted functions and session isolation
5. Session Context Testing - Real Frappe user context switching

Architecture:
- Uses EnhancedTestCase for realistic data generation without mocking
- Creates actual User accounts with proper Verenigingen Member roles
- Tests complete User→Member→Donor permission chain
- Validates real role assignment and permission inheritance
- Tests with actual linked member-donor relationships
"""

import time
import threading
import frappe
from frappe.utils import getdate, add_days, now_datetime
from frappe.tests.utils import FrappeTestCase

from verenigingen.permissions import (
    has_donor_permission, 
    get_donor_permission_query
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorSecurityEnhanced(EnhancedTestCase):
    """
    Enhanced donor security test suite with real user permission testing
    
    Addresses the critical gap identified by QA: "No Real User Permission Testing"
    """
    
    def setUp(self):
        """Set up real user accounts with proper role assignments"""
        super().setUp()
        
        # Set admin user for initial setup
        frappe.set_user("Administrator")
        
        # Create test users with actual User records
        self.test_users = {}
        self.test_members = {}
        self.test_donors = {}
        
        # Create real User account with Verenigingen Member role
        self.create_real_test_user("member1@unittest.test", "Verenigingen Member")
        self.create_real_test_user("member2@unittest.test", "Verenigingen Member") 
        self.create_real_test_user("nonmember@unittest.test", "Guest")
        self.create_real_test_user("admin@unittest.test", "Verenigingen Administrator")
        
        # Create Member records linked to users
        self.create_linked_member_and_donor("member1@unittest.test")
        self.create_linked_member_and_donor("member2@unittest.test")
        
        # Create orphaned donor (no member link)
        self.create_orphaned_donor()
        
    def create_real_test_user(self, email: str, role_name: str):
        """Create actual User record with proper role assignment"""
        # Check if user already exists
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            # Create new user
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": f"Test",
                "last_name": f"User {email.split('@')[0]}",
                "send_welcome_email": 0,
                "enabled": 1
            })
            user.insert(ignore_permissions=True)
        
        # Ensure user has the specified role
        if not any(role.role == role_name for role in user.roles):
            user.append("roles", {"role": role_name})
            user.save(ignore_permissions=True)
        
        self.test_users[email] = user
        
    def create_linked_member_and_donor(self, user_email: str):
        """Create Member and Donor records linked to user"""
        # Create Member record linked to user
        member = self.create_test_member(
            email=user_email,
            user=user_email,  # Link to actual user account
            first_name="Test",
            last_name=f"Member {user_email.split('@')[0]}"
        )
        self.test_members[user_email] = member
        
        # Create Donor record linked to member
        donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": f"Test Donor for {member.first_name} {member.last_name}",
            "donor_type": "Individual",
            "donor_email": user_email,
            "member": member.name  # Link to member record
        })
        donor.insert(ignore_permissions=True)
        self.test_donors[user_email] = donor
        
    def create_orphaned_donor(self):
        """Create donor with no member link"""
        orphaned_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Orphaned Test Donor",
            "donor_type": "Organization",
            "donor_email": "orphaned@unittest.test"
            # No member field set - this is the orphaned donor
        })
        orphaned_donor.insert(ignore_permissions=True)
        self.orphaned_donor = orphaned_donor
        
    def test_real_user_permission_chain_validation(self):
        """
        TEST 1: Real User → Member → Donor Permission Chain
        
        This is the critical missing test identified by QA.
        Tests the complete permission chain with actual User records.
        """
        member1_email = "member1@unittest.test"
        member2_email = "member2@unittest.test"
        
        # Test 1a: User can access their own linked donor
        with self.subTest("Own donor access"):
            member1_donor = self.test_donors[member1_email]
            result = has_donor_permission(member1_donor.name, member1_email)
            self.assertTrue(result, "Member should have access to their own linked donor")
            
        # Test 1b: User cannot access other users' donors
        with self.subTest("Other user donor restriction"):
            member1_donor = self.test_donors[member1_email]  
            result = has_donor_permission(member1_donor.name, member2_email)
            self.assertFalse(result, "Member should not have access to other members' donors")
            
        # Test 1c: Non-member user has no access
        with self.subTest("Non-member restriction"):
            member1_donor = self.test_donors[member1_email]
            result = has_donor_permission(member1_donor.name, "nonmember@unittest.test")
            self.assertFalse(result, "Non-member users should have no donor access")
            
        # Test 1d: Admin user has access to all donors
        with self.subTest("Admin override access"):
            member1_donor = self.test_donors[member1_email]
            result = has_donor_permission(member1_donor.name, "admin@unittest.test")
            self.assertTrue(result, "Admin users should have access to all donors")
            
    def test_real_user_context_switching(self):
        """
        TEST 2: Real User Context Switching with frappe.set_user()
        
        Tests that user context switching works correctly with real users
        and that permission queries are properly filtered.
        """
        member1_email = "member1@unittest.test"
        member2_email = "member2@unittest.test"
        
        # Test with member1 context
        with self.subTest("Member1 context"):
            frappe.set_user(member1_email)
            
            # Should see own donor in filtered results
            query = get_donor_permission_query(member1_email)
            self.assertIsInstance(query, str, "Member should get filtered query")
            self.assertIn("`tabDonor`.member =", query, "Query should filter by member")
            
            # Get all donors with permissions - should only see own
            accessible_donors = frappe.get_all(
                "Donor",
                fields=["name", "donor_name", "member"],
                ignore_permissions=False  # Use actual permissions
            )
            
            # Should only see own donor
            donor_names = [d.name for d in accessible_donors]
            self.assertIn(self.test_donors[member1_email].name, donor_names,
                         "Should see own donor in results")
            self.assertNotIn(self.test_donors[member2_email].name, donor_names,
                           "Should not see other users' donors")
            
        # Test with member2 context  
        with self.subTest("Member2 context"):
            frappe.set_user(member2_email)
            
            accessible_donors = frappe.get_all(
                "Donor", 
                fields=["name", "donor_name", "member"],
                ignore_permissions=False
            )
            
            donor_names = [d.name for d in accessible_donors]
            self.assertIn(self.test_donors[member2_email].name, donor_names,
                         "Should see own donor in results")
            self.assertNotIn(self.test_donors[member1_email].name, donor_names,
                           "Should not see other users' donors")
            
        # Test with admin context
        with self.subTest("Admin context"):
            frappe.set_user("admin@unittest.test")
            
            query = get_donor_permission_query("admin@unittest.test")
            self.assertIsNone(query, "Admin should get unrestricted query")
            
            accessible_donors = frappe.get_all(
                "Donor",
                fields=["name", "donor_name", "member"], 
                ignore_permissions=False
            )
            
            # Should see all donors
            donor_names = [d.name for d in accessible_donors]
            self.assertIn(self.test_donors[member1_email].name, donor_names,
                         "Admin should see all donors")
            self.assertIn(self.test_donors[member2_email].name, donor_names,
                         "Admin should see all donors")
            self.assertIn(self.orphaned_donor.name, donor_names,
                         "Admin should see orphaned donors")
            
    def test_role_assignment_persistence(self):
        """
        TEST 3: Role Assignment and Permission Inheritance
        
        Tests that role assignments persist and permissions are inherited correctly
        """
        member1_email = "member1@unittest.test"
        
        # Verify role assignment persists
        with self.subTest("Role persistence"):
            user = frappe.get_doc("User", member1_email)
            user_roles = [role.role for role in user.roles]
            self.assertIn("Verenigingen Member", user_roles, 
                         "User should have Verenigingen Member role")
            
        # Verify role-based permission inheritance
        with self.subTest("Role-based permissions"):
            frappe.set_user(member1_email)
            
            # Check user's roles via frappe.get_roles()
            session_roles = frappe.get_roles(member1_email)
            self.assertIn("Verenigingen Member", session_roles,
                         "User should have Verenigingen Member role in session")
            
        # Test permission changes when role is removed
        with self.subTest("Role removal effects"):
            frappe.set_user("Administrator")
            
            # Remove Verenigingen Member role temporarily
            user = frappe.get_doc("User", member1_email)
            user.roles = [role for role in user.roles if role.role != "Verenigingen Member"]
            user.save(ignore_permissions=True)
            
            # Test permission should be denied now
            member1_donor = self.test_donors[member1_email]
            result = has_donor_permission(member1_donor.name, member1_email)
            self.assertFalse(result, "Permission should be denied without proper role")
            
            # Restore role
            user.append("roles", {"role": "Verenigingen Member"})
            user.save(ignore_permissions=True)
            
            # Permission should be restored
            result = has_donor_permission(member1_donor.name, member1_email)
            self.assertTrue(result, "Permission should be restored with role")
            
    def test_production_concurrent_access_scenarios(self):
        """
        TEST 4: Production-Like Concurrent Access Testing
        
        Tests realistic scenarios with multiple users accessing different records simultaneously
        """
        results = {}
        errors = []
        
        def test_user_access(user_email, donor_name, expected_result, thread_id):
            """Test function to run in thread"""
            try:
                # Simulate some processing time
                time.sleep(0.1)
                
                result = has_donor_permission(donor_name, user_email)
                results[thread_id] = {
                    "user": user_email,
                    "donor": donor_name, 
                    "result": result,
                    "expected": expected_result,
                    "success": result == expected_result
                }
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")
                
        # Create multiple threads testing different scenarios
        threads = []
        
        # Scenario 1: Multiple users accessing their own donors
        threads.append(threading.Thread(
            target=test_user_access,
            args=("member1@unittest.test", self.test_donors["member1@unittest.test"].name, True, "t1")
        ))
        threads.append(threading.Thread(
            target=test_user_access, 
            args=("member2@unittest.test", self.test_donors["member2@unittest.test"].name, True, "t2")
        ))
        
        # Scenario 2: Users trying to access others' donors (should fail)
        threads.append(threading.Thread(
            target=test_user_access,
            args=("member1@unittest.test", self.test_donors["member2@unittest.test"].name, False, "t3")
        ))
        threads.append(threading.Thread(
            target=test_user_access,
            args=("member2@unittest.test", self.test_donors["member1@unittest.test"].name, False, "t4")
        ))
        
        # Scenario 3: Admin accessing all donors (should succeed)
        threads.append(threading.Thread(
            target=test_user_access,
            args=("admin@unittest.test", self.test_donors["member1@unittest.test"].name, True, "t5")
        ))
        threads.append(threading.Thread(
            target=test_user_access,
            args=("admin@unittest.test", self.orphaned_donor.name, True, "t6")
        ))
        
        # Start all threads
        for thread in threads:
            thread.start()
            
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5.0)  # 5 second timeout
            
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent access errors: {errors}")
        self.assertEqual(len(results), 6, "All threads should complete")
        
        for thread_id, result in results.items():
            with self.subTest(thread=thread_id):
                self.assertEqual(result["result"], result["expected"],
                               f"Thread {thread_id}: User {result['user']} access to donor {result['donor']}")
                               
    def test_user_member_linking_validation(self):
        """
        TEST 5: User-Member Linking Edge Cases
        
        Tests edge cases in user-member linking that could cause security issues
        """
        
        # Test 5a: Member with invalid user link
        with self.subTest("Invalid user link"):
            # Create member with non-existent user
            invalid_member = self.create_test_member(
                email="invalid@unittest.test",
                user="nonexistent@unittest.test",  # User doesn't exist
                first_name="Invalid",
                last_name="User Link"
            )
            
            # Create donor linked to this member
            invalid_donor = frappe.get_doc({
                "doctype": "Donor",
                "donor_name": "Invalid User Link Donor",
                "donor_type": "Individual",
                "donor_email": "invalid@unittest.test",
                "member": invalid_member.name
            })
            invalid_donor.insert(ignore_permissions=True)
            
            # Permission check should fail gracefully
            result = has_donor_permission(invalid_donor.name, "nonexistent@unittest.test")
            self.assertFalse(result, "Should deny access for non-existent user")
            
        # Test 5b: User with no member record  
        with self.subTest("User without member record"):
            # Create user without corresponding member
            orphan_user = frappe.get_doc({
                "doctype": "User",
                "email": "orphanuser@unittest.test",
                "first_name": "Orphan",
                "last_name": "User",
                "send_welcome_email": 0,
                "enabled": 1
            })
            orphan_user.insert(ignore_permissions=True)
            orphan_user.append("roles", {"role": "Verenigingen Member"})
            orphan_user.save(ignore_permissions=True)
            
            # Should not have access to any donors
            member1_donor = self.test_donors["member1@unittest.test"]
            result = has_donor_permission(member1_donor.name, "orphanuser@unittest.test")
            self.assertFalse(result, "User without member record should have no access")
            
        # Test 5c: Multiple members linked to same user (edge case)
        with self.subTest("Multiple members per user"):
            # This could happen in data corruption scenarios
            duplicate_member = self.create_test_member(
                email="member1@unittest.test",  # Same email/user as existing
                user="member1@unittest.test",
                first_name="Duplicate",
                last_name="Member"
            )
            
            # Create donor for duplicate member
            duplicate_donor = frappe.get_doc({
                "doctype": "Donor", 
                "donor_name": "Duplicate Member Donor",
                "donor_type": "Individual",
                "donor_email": "member1@unittest.test",
                "member": duplicate_member.name
            })
            duplicate_donor.insert(ignore_permissions=True)
            
            # User should have access to both donors (both linked to their member records)
            result = has_donor_permission(duplicate_donor.name, "member1@unittest.test")
            self.assertTrue(result, "User should access donors linked to any of their member records")
            
    def test_session_security_and_isolation(self):
        """
        TEST 6: Session Security and Isolation
        
        Tests that user sessions are properly isolated and cannot access each other's data
        """
        
        # Test 6a: Session context isolation
        with self.subTest("Session isolation"):
            # Set user context
            frappe.set_user("member1@unittest.test")
            
            # Verify current user
            self.assertEqual(frappe.session.user, "member1@unittest.test")
            
            # Test permission in this context
            member1_donor = self.test_donors["member1@unittest.test"]
            result = has_donor_permission(member1_donor.name, frappe.session.user)
            self.assertTrue(result, "Should have access to own donor in session context")
            
            # Switch user context
            frappe.set_user("member2@unittest.test")
            self.assertEqual(frappe.session.user, "member2@unittest.test") 
            
            # Test that previous user's permissions don't leak
            result = has_donor_permission(member1_donor.name, frappe.session.user)
            self.assertFalse(result, "Should not have access to other user's donor after context switch")
            
        # Test 6b: Permission caching doesn't cause leaks
        with self.subTest("Permission cache isolation"):
            # Test multiple rapid context switches
            for i in range(5):
                frappe.set_user("member1@unittest.test")
                result1 = has_donor_permission(self.test_donors["member1@unittest.test"].name, 
                                              frappe.session.user)
                self.assertTrue(result1, f"Iteration {i}: Member1 should access own donor")
                
                frappe.set_user("member2@unittest.test")
                result2 = has_donor_permission(self.test_donors["member1@unittest.test"].name,
                                              frappe.session.user)
                self.assertFalse(result2, f"Iteration {i}: Member2 should not access member1's donor")
                
    def test_api_security_whitelisted_functions(self):
        """
        TEST 7: API Security for Whitelisted Functions
        
        Tests that whitelisted functions properly respect user permissions
        """
        # Note: This would test actual API endpoints if they exist
        # For now, we test the underlying permission functions that APIs would use
        
        # Test 7a: Permission function security
        with self.subTest("Permission function consistency"):
            member1_email = "member1@unittest.test"
            member1_donor = self.test_donors[member1_email]
            
            # Test direct function call
            direct_result = has_donor_permission(member1_donor.name, member1_email)
            
            # Test with document object instead of string
            donor_doc = frappe.get_doc("Donor", member1_donor.name)
            object_result = has_donor_permission(donor_doc, member1_email)
            
            self.assertEqual(direct_result, object_result,
                           "Permission function should work consistently with strings and objects")
            
        # Test 7b: Permission query security
        with self.subTest("Permission query injection prevention"):
            # Test with potentially malicious user input
            malicious_users = [
                "'; DROP TABLE tabDonor; --",
                "' OR '1'='1",
                "admin@test.com'; DELETE FROM tabUser; --"
            ]
            
            for malicious_user in malicious_users:
                query = get_donor_permission_query(malicious_user)
                self.assertEqual(query, "1=0", 
                               f"Malicious user input should get restrictive query: {malicious_user}")
                               
    def test_permission_edge_cases_and_error_handling(self):
        """
        TEST 8: Permission Edge Cases and Error Handling
        
        Tests that the permission system handles edge cases gracefully
        """
        
        # Test 8a: Deleted member records
        with self.subTest("Deleted member handling"):
            # Create member and donor
            temp_member = self.create_test_member(
                email="temp@unittest.test",
                first_name="Temporary",
                last_name="Member"
            )
            
            temp_donor = frappe.get_doc({
                "doctype": "Donor",
                "donor_name": "Temporary Donor",
                "donor_type": "Individual", 
                "donor_email": "temp@unittest.test",
                "member": temp_member.name
            })
            temp_donor.insert(ignore_permissions=True)
            
            # Delete member
            frappe.delete_doc("Member", temp_member.name, force=True)
            
            # Permission check should handle gracefully
            result = has_donor_permission(temp_donor.name, "temp@unittest.test")
            self.assertFalse(result, "Should deny access when linked member is deleted")
            
        # Test 8b: Disabled user accounts
        with self.subTest("Disabled user handling"):
            # Disable user account
            user = frappe.get_doc("User", "member1@unittest.test")
            user.enabled = 0
            user.save(ignore_permissions=True)
            
            try:
                member1_donor = self.test_donors["member1@unittest.test"]
                result = has_donor_permission(member1_donor.name, "member1@unittest.test")
                # Behavior may vary - could be False or raise exception
                # The important thing is it doesn't grant access
                if result is not False:
                    self.fail("Disabled user should not have donor access")
                    
            finally:
                # Re-enable user
                user.enabled = 1
                user.save(ignore_permissions=True)
                
        # Test 8c: Performance with large datasets
        with self.subTest("Performance with multiple donors"):
            # Create multiple donors for same member
            member1_email = "member1@unittest.test"
            member1 = self.test_members[member1_email]
            
            additional_donors = []
            for i in range(10):
                donor = frappe.get_doc({
                    "doctype": "Donor",
                    "donor_name": f"Performance Test Donor {i}",
                    "donor_type": "Individual",
                    "donor_email": f"perf{i}@unittest.test",
                    "member": member1.name
                })
                donor.insert(ignore_permissions=True)
                additional_donors.append(donor)
                
            # Test performance of permission queries
            start_time = time.time()
            
            frappe.set_user(member1_email)
            accessible_donors = frappe.get_all(
                "Donor",
                fields=["name", "donor_name", "member"],
                ignore_permissions=False
            )
            
            end_time = time.time()
            query_time = end_time - start_time
            
            # Should complete reasonably quickly (under 1 second)
            self.assertLess(query_time, 1.0, 
                          f"Permission query took too long: {query_time:.2f}s")
            
            # Should return all linked donors
            donor_names = [d.name for d in accessible_donors]
            self.assertGreaterEqual(len(donor_names), 11,  # Original + 10 additional
                                  "Should return all linked donors")
                                  
    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")
        
        # Clean up test donors
        for donor in self.test_donors.values():
            try:
                if frappe.db.exists("Donor", donor.name):
                    frappe.delete_doc("Donor", donor.name, force=True)
            except Exception:
                pass
                
        # Clean up orphaned donor
        try:
            if hasattr(self, 'orphaned_donor') and frappe.db.exists("Donor", self.orphaned_donor.name):
                frappe.delete_doc("Donor", self.orphaned_donor.name, force=True)
        except Exception:
            pass
            
        # Clean up test members  
        for member in self.test_members.values():
            try:
                if frappe.db.exists("Member", member.name):
                    frappe.delete_doc("Member", member.name, force=True)
            except Exception:
                pass
                
        # Clean up test users (but keep built-in ones)
        for email, user in self.test_users.items():
            if email not in ["Administrator", "Guest"]:
                try:
                    if frappe.db.exists("User", email):
                        frappe.delete_doc("User", email, force=True)
                except Exception:
                    pass
                    
        super().tearDown()


class TestDonorSecurityRealWorldScenarios(EnhancedTestCase):
    """
    Real-world security scenario testing
    
    Tests complex scenarios that mirror production usage patterns
    """
    
    def setUp(self):
        """Set up complex real-world scenario data"""
        super().setUp()
        frappe.set_user("Administrator")
        
        # Create a more complex user hierarchy
        self.setup_organization_scenario()
        
    def setup_organization_scenario(self):
        """Create realistic organizational structure"""
        # Create chapter admin user
        self.create_user_with_roles("chapter.admin@unittest.test", 
                                   ["Verenigingen Administrator", "Verenigingen Member"])
        
        # Create board member user
        self.create_user_with_roles("board.member@unittest.test",
                                   ["Verenigingen Member"])
        
        # Create regular members
        self.create_user_with_roles("regular1@unittest.test", ["Verenigingen Member"]) 
        self.create_user_with_roles("regular2@unittest.test", ["Verenigingen Member"])
        
        # Create corresponding member records and donors
        self.users_data = {}
        for email in ["chapter.admin@unittest.test", "board.member@unittest.test", 
                     "regular1@unittest.test", "regular2@unittest.test"]:
            member = self.create_test_member(
                email=email,
                user=email,
                first_name="Test",
                last_name=email.split('@')[0].replace('.', ' ').title()
            )
            
            donor = frappe.get_doc({
                "doctype": "Donor", 
                "donor_name": f"Donor for {member.first_name} {member.last_name}",
                "donor_type": "Individual",
                "donor_email": email,
                "member": member.name
            })
            donor.insert(ignore_permissions=True)
            
            self.users_data[email] = {"member": member, "donor": donor}
            
    def create_user_with_roles(self, email: str, roles: list):
        """Create user with multiple roles"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": email.split('@')[0].split('.')[0].title(),
                "last_name": email.split('@')[0].split('.')[1].title() if '.' in email.split('@')[0] else "User",
                "send_welcome_email": 0,
                "enabled": 1
            })
            user.insert(ignore_permissions=True)
            
        # Add all specified roles
        for role_name in roles:
            if not any(role.role == role_name for role in user.roles):
                user.append("roles", {"role": role_name})
        user.save(ignore_permissions=True)
        
    def test_organizational_hierarchy_permissions(self):
        """
        TEST 9: Organizational Hierarchy Permission Testing
        
        Tests that different organizational roles have appropriate access levels
        """
        
        # Test 9a: Chapter admin should have broad access
        with self.subTest("Chapter admin access"):
            frappe.set_user("chapter.admin@unittest.test")
            
            # Admin should have access to all donors (due to Verenigingen Administrator role)
            accessible_donors = frappe.get_all(
                "Donor",
                fields=["name", "donor_name", "member"],
                ignore_permissions=False
            )
            
            # Should see multiple donors including others' 
            self.assertGreaterEqual(len(accessible_donors), 4,
                                  "Chapter admin should see multiple donors")
                                  
        # Test 9b: Regular member should only see own
        with self.subTest("Regular member restricted access"):
            frappe.set_user("regular1@unittest.test")
            
            accessible_donors = frappe.get_all(
                "Donor",
                fields=["name", "donor_name", "member"], 
                ignore_permissions=False
            )
            
            # Should only see own donor
            self.assertEqual(len(accessible_donors), 1,
                           "Regular member should only see own donor")
            self.assertEqual(accessible_donors[0].name, 
                           self.users_data["regular1@unittest.test"]["donor"].name,
                           "Should see only own donor")
                           
        # Test 9c: Cross-user access prevention
        with self.subTest("Cross-user access prevention"):
            regular1_donor = self.users_data["regular1@unittest.test"]["donor"]
            regular2_email = "regular2@unittest.test"
            
            result = has_donor_permission(regular1_donor.name, regular2_email)
            self.assertFalse(result, "One regular member should not access another's donor")
            
    def test_role_based_security_matrix(self):
        """
        TEST 10: Role-Based Security Matrix Testing
        
        Comprehensive test of all role combinations and their access patterns
        """
        test_scenarios = [
            # (user_email, target_donor_user, expected_access, scenario_name)
            ("chapter.admin@unittest.test", "regular1@unittest.test", True, "Admin access to regular member"),
            ("chapter.admin@unittest.test", "regular2@unittest.test", True, "Admin access to regular member 2"),
            ("board.member@unittest.test", "regular1@unittest.test", False, "Board member access to regular member"),
            ("board.member@unittest.test", "board.member@unittest.test", True, "Board member access to own"),
            ("regular1@unittest.test", "regular2@unittest.test", False, "Regular member cross-access"),
            ("regular1@unittest.test", "regular1@unittest.test", True, "Regular member own access"),
            ("regular2@unittest.test", "chapter.admin@unittest.test", False, "Regular member access to admin"),
        ]
        
        for user_email, target_donor_user, expected_access, scenario_name in test_scenarios:
            with self.subTest(scenario=scenario_name):
                target_donor = self.users_data[target_donor_user]["donor"]
                result = has_donor_permission(target_donor.name, user_email)
                self.assertEqual(result, expected_access,
                               f"{scenario_name}: {user_email} → {target_donor_user}")
                               
    def tearDown(self):
        """Clean up complex test data"""
        frappe.set_user("Administrator")
        
        # Clean up all created data
        for email, data in self.users_data.items():
            try:
                if frappe.db.exists("Donor", data["donor"].name):
                    frappe.delete_doc("Donor", data["donor"].name, force=True)
                if frappe.db.exists("Member", data["member"].name):
                    frappe.delete_doc("Member", data["member"].name, force=True)
                if frappe.db.exists("User", email):
                    frappe.delete_doc("User", email, force=True)
            except Exception:
                pass
                
        super().tearDown()


if __name__ == '__main__':
    # Allow running the test directly
    import unittest
    unittest.main()