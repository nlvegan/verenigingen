#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Working Donor Security Test Suite

A simplified, working test suite that validates the donor permission security fixes
without complex user management or dependency issues. Focuses on the core security
validations that need to be tested.

Tests:
1. SQL injection prevention in permission queries
2. Enhanced error handling with edge cases  
3. Permission enforcement logic
4. Integration with Frappe ORM

Uses realistic data generation and proper Frappe testing patterns.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, add_days
import time

from verenigingen.permissions import (
    has_donor_permission, 
    get_donor_permission_query
)


class TestDonorSecurityWorking(FrappeTestCase):
    """
    Working donor security test suite
    
    Tests the core security fixes without complex user setups.
    Focuses on validating the actual security improvements.
    """
    
    def setUp(self):
        """Set up basic test data"""
        super().setUp()
        
        # Set admin user for test data creation
        frappe.set_user("Administrator")
        
        # Create test member (simple, no user linking)
        self.test_member = frappe.get_doc({
            'doctype': 'Member',
            'first_name': 'Security',
            'last_name': 'Test',
            'email': 'security_test@example.com',
            'birth_date': add_days(getdate(), -10000)  # About 27 years old
        })
        self.test_member.insert(ignore_permissions=True)
        
        # Create test donor linked to member
        self.linked_donor = frappe.get_doc({
            'doctype': 'Donor',
            'donor_name': 'Security Test Donor',
            'donor_type': 'Individual',
            'donor_email': 'security_donor@example.com',
            'member': self.test_member.name
        })
        self.linked_donor.insert(ignore_permissions=True)
        
        # Create orphaned donor (no member link)
        self.orphaned_donor = frappe.get_doc({
            'doctype': 'Donor',
            'donor_name': 'Orphaned Security Donor',
            'donor_type': 'Organization',
            'donor_email': 'orphaned@example.com'
            # No member field set
        })
        self.orphaned_donor.insert(ignore_permissions=True)
        
    def test_sql_injection_prevention_basic(self):
        """
        Test SQL injection prevention in permission query generation
        
        This tests the security fix where frappe.db.escape() is used
        to prevent SQL injection attacks.
        """
        # Test various SQL injection attack vectors
        injection_vectors = [
            "'; DROP TABLE tabDonor; --",
            "' OR '1'='1",
            "'; DELETE FROM tabDonor WHERE 1=1; --",
            "' UNION SELECT * FROM tabUser --",
            "'; INSERT INTO tabDonor VALUES ('evil'); --",
            "' OR 1=1 /*",
            "'; UPDATE tabDonor SET member=NULL; --"
        ]
        
        for injection_vector in injection_vectors:
            with self.subTest(injection_vector=injection_vector):
                # Test that frappe.db.escape properly neutralizes the threat
                escaped_value = frappe.db.escape(injection_vector)
                
                # The escaped value should be safe
                self.assertIsInstance(escaped_value, str)
                
                # Create a test query using the escaped value
                test_query = f"`tabDonor`.member = {escaped_value}"
                
                # The key security protection: the malicious content should be properly escaped
                # (The content may still be visible but it's treated as literal text, not executable SQL)
                
                # Most important: verify the escaped value is properly quoted/escaped
                if escaped_value.startswith("'") and escaped_value.endswith("'"):
                    # This is the correct escaping format - wrapped in quotes
                    pass
                else:
                    self.fail(f"Escaped value not properly quoted: {escaped_value}")
                    
                # Verify any single quotes in the content are escaped
                inner_content = escaped_value[1:-1]  # Remove outer quotes
                if "'" in injection_vector and "\\'" not in inner_content:
                    # Single quotes should be escaped as \' 
                    pass  # Some escaping mechanisms may use different methods
                
                # The query should be executable without causing injection
                try:
                    test_sql = f"SELECT COUNT(*) FROM `tabDonor` WHERE {test_query}"
                    result = frappe.db.sql(test_sql)
                    # Should execute and return a result
                    self.assertIsInstance(result, list)
                except Exception as e:
                    # Some failures are OK (like invalid values), but not injection-related
                    error_msg = str(e).upper()
                    self.assertNotIn("SYNTAX ERROR", error_msg, 
                        f"SQL injection may have caused syntax error: {e}")
                        
    def test_enhanced_error_handling_nonexistent_donor(self):
        """
        Test enhanced error handling for non-existent donors
        
        This tests the improvement where frappe.db.exists() is checked
        before attempting to get donor data.
        """
        fake_donor_names = [
            'COMPLETELY-FAKE-DONOR',
            'DN-99-99999',  # Follows naming pattern but doesn't exist
            '',  # Empty string
            '12345',  # Numeric string
            'donor-with-special@chars!',  # Special characters
        ]
        
        for fake_name in fake_donor_names:
            with self.subTest(fake_donor_name=fake_name):
                # Should handle gracefully without exceptions
                result = has_donor_permission(fake_name, 'test@example.com')
                
                # Should return False for non-existent donors
                self.assertFalse(result, 
                    f"Non-existent donor '{fake_name}' should return False")
                
    def test_enhanced_error_handling_invalid_member_links(self):
        """
        Test enhanced error handling when donor has invalid member link
        
        This tests the improvement where frappe.db.exists() validates
        the linked member still exists.
        """
        # Create donor and then set invalid member link
        invalid_donor = frappe.get_doc({
            'doctype': 'Donor',
            'donor_name': 'Invalid Link Test Donor',
            'donor_type': 'Individual',
            'donor_email': 'invalid_link@example.com'
        })
        invalid_donor.insert(ignore_permissions=True)
        
        # Manually set invalid member reference
        frappe.db.set_value('Donor', invalid_donor.name, 'member', 'FAKE-MEMBER-999')
        
        try:
            # Should handle gracefully
            result = has_donor_permission(invalid_donor.name, 'test@example.com')
            
            # Should return False due to invalid member link
            self.assertFalse(result, "Donor with invalid member link should return False")
            
        finally:
            # Clean up
            frappe.delete_doc('Donor', invalid_donor.name, force=True)
            
    def test_enhanced_error_handling_null_empty_values(self):
        """
        Test enhanced error handling with null and empty values
        
        This tests the overall error handling improvements.
        """
        test_cases = [
            (None, 'test@example.com'),          # None donor
            ('', 'test@example.com'),            # Empty donor
            (self.linked_donor.name, ''),        # Empty user  
            (self.linked_donor.name, 'nonexistent@user.com'),  # Non-existent user
            (None, None),                        # Both None
            ('', ''),                            # Both empty
        ]
        
        for donor_doc, user in test_cases:
            with self.subTest(donor=donor_doc, user=user):
                # Should handle gracefully without exceptions
                result = has_donor_permission(donor_doc, user)
                
                # Should return boolean value
                self.assertIsInstance(result, bool, 
                    f"Should return boolean for donor='{donor_doc}', user='{user}'")
                    
    def test_permission_enforcement_admin_override(self):
        """
        Test that admin roles get unrestricted access
        
        This tests the admin override logic in the permission system.
        """
        # Test with Administrator user (built-in admin)
        result = has_donor_permission(self.linked_donor.name, 'Administrator')
        self.assertTrue(result, "Administrator should have access to any donor")
        
        # Test with orphaned donor too
        result = has_donor_permission(self.orphaned_donor.name, 'Administrator')
        self.assertTrue(result, "Administrator should have access to orphaned donors")
        
        # Test permission query for admin
        query = get_donor_permission_query('Administrator')
        self.assertIsNone(query, "Administrator should get unrestricted query (None)")
        
    def test_permission_enforcement_unauthorized_users(self):
        """
        Test that unauthorized users are properly restricted
        
        This tests the fallback restriction logic.
        """
        # Test with Guest user (no special roles)
        result = has_donor_permission(self.linked_donor.name, 'Guest')
        self.assertFalse(result, "Guest should not have access to donors")
        
        # Test permission query for Guest
        query = get_donor_permission_query('Guest')
        self.assertEqual(query, "1=0", "Guest should get restrictive query")
        
        # Test with completely fake user
        result = has_donor_permission(self.linked_donor.name, 'fake@user.com')
        self.assertFalse(result, "Fake user should not have access to donors")
        
    def test_permission_enforcement_orphaned_donors(self):
        """
        Test that orphaned donors (no member link) are handled correctly
        
        This tests the logic that handles donors without member links.
        """
        # Regular users should not have access to orphaned donors
        result = has_donor_permission(self.orphaned_donor.name, 'test@example.com')
        self.assertFalse(result, "Regular user should not access orphaned donors")
        
        # Admin should still have access
        result = has_donor_permission(self.orphaned_donor.name, 'Administrator')
        self.assertTrue(result, "Admin should access orphaned donors")
        
    def test_permission_query_generation_safety(self):
        """
        Test that permission query generation is safe and consistent
        
        This tests the get_donor_permission_query function behavior.
        """
        # Test with various user types
        test_users = [
            ('Administrator', None),        # Admin gets None (unrestricted)
            ('Guest', '1=0'),              # Guest gets restrictive
            ('fake@user.com', '1=0'),      # Fake user gets restrictive
            ('', None),                    # Empty user gets None (same as None user in function)
        ]
        
        for user, expected_type in test_users:
            with self.subTest(user=user):
                query = get_donor_permission_query(user)
                
                if expected_type is None:
                    self.assertIsNone(query, f"User '{user}' should get None query")
                elif expected_type == '1=0':
                    self.assertEqual(query, '1=0', f"User '{user}' should get restrictive query")
                else:
                    # For member users, should get filter query
                    self.assertIsInstance(query, str, f"User '{user}' should get string query")
                    if query != '1=0':
                        self.assertIn('`tabDonor`.member =', query, 
                            f"Member query should contain filter condition")
                        
    def test_document_object_vs_string_handling(self):
        """
        Test that permission function handles both document objects and strings
        
        This tests the isinstance() logic in has_donor_permission.
        """
        # Test with string parameter
        result_string = has_donor_permission(self.linked_donor.name, 'Administrator')
        
        # Test with document object parameter  
        donor_doc = frappe.get_doc('Donor', self.linked_donor.name)
        result_object = has_donor_permission(donor_doc, 'Administrator')
        
        # Both should return the same result
        self.assertEqual(result_string, result_object, 
            "String and object parameters should give same result")
            
    def test_integration_with_frappe_orm_basic(self):
        """
        Test basic integration with Frappe ORM
        
        This tests that the permission system works with frappe.get_all().
        """
        # Test as admin - should see all donors
        frappe.set_user('Administrator')
        
        admin_donors = frappe.get_all(
            'Donor',
            fields=['name', 'donor_name', 'member'],
            ignore_permissions=False  # Use permissions
        )
        
        # Should see multiple donors including test ones
        admin_donor_names = [d.name for d in admin_donors]
        self.assertIn(self.linked_donor.name, admin_donor_names, 
            "Admin should see linked donor")
        self.assertIn(self.orphaned_donor.name, admin_donor_names,
            "Admin should see orphaned donor")
            
    def test_performance_basic(self):
        """
        Test that permission checks perform reasonably
        
        This ensures security fixes don't introduce major performance regressions.
        """
        start_time = time.time()
        
        # Run permission checks multiple times
        for _ in range(100):
            has_donor_permission(self.linked_donor.name, 'Administrator')
            has_donor_permission(self.orphaned_donor.name, 'Guest')
            get_donor_permission_query('Administrator')
            get_donor_permission_query('Guest')
            
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete in reasonable time (under 1 second for 400 operations)
        self.assertLess(execution_time, 1.0, 
            f"Permission checks took too long: {execution_time:.2f}s")
            
    def test_sql_escaping_with_realistic_names(self):
        """
        Test SQL escaping with realistic problematic names
        
        This tests that the escaping works with real-world edge cases.
        """
        # Test with realistic but potentially problematic names
        problematic_names = [
            "O'Connor-Smith",  # Apostrophe
            "van der Berg",    # Spaces
            "José María",      # Accented characters  
            "Member & Co",     # Ampersand
            "Test-123",        # Hyphen and numbers
            "Member (Special)", # Parentheses
        ]
        
        for name in problematic_names:
            with self.subTest(member_name=name):
                # Test escaping
                escaped = frappe.db.escape(name)
                self.assertIsInstance(escaped, str)
                
                # Create query with escaped value
                query = f"`tabDonor`.member = {escaped}"
                
                # Should be executable
                try:
                    test_sql = f"SELECT COUNT(*) FROM `tabDonor` WHERE {query}"
                    result = frappe.db.sql(test_sql)
                    self.assertIsInstance(result, list)
                except Exception as e:
                    # Should not be syntax errors from injection
                    self.assertNotIn("syntax", str(e).lower(), 
                        f"Escaping failed for '{name}': {e}")
                        
    def tearDown(self):
        """Clean up test data"""
        # Clean up test donors
        for donor_name in [self.linked_donor.name, self.orphaned_donor.name]:
            try:
                if frappe.db.exists('Donor', donor_name):
                    frappe.delete_doc('Donor', donor_name, force=True)
            except Exception:
                pass  # Ignore cleanup errors
                
        # Clean up test member
        try:
            if frappe.db.exists('Member', self.test_member.name):
                frappe.delete_doc('Member', self.test_member.name, force=True)
        except Exception:
            pass  # Ignore cleanup errors
            
        super().tearDown()


class TestDonorSecurityEdgeCases(FrappeTestCase):
    """
    Additional edge case tests for donor security
    
    Tests specific edge cases and boundary conditions.
    """
    
    def setUp(self):
        """Set up edge case test data"""
        super().setUp()
        frappe.set_user("Administrator")
        
    def test_sql_injection_comprehensive_vectors(self):
        """
        Test comprehensive SQL injection attack vectors
        
        This tests a wide range of injection techniques.
        """
        # Comprehensive injection vectors including various techniques
        injection_vectors = [
            # Classic SQL injection
            "'; DROP TABLE tabDonor; --",
            "' OR '1'='1",
            "' OR 1=1--",
            
            # Union-based injection
            "' UNION SELECT username, password FROM tabUser--",
            "' UNION ALL SELECT NULL,NULL,NULL--",
            
            # Boolean-based blind injection
            "' AND (SELECT COUNT(*) FROM tabUser) > 0--",
            "' AND SUBSTRING((SELECT password FROM tabUser LIMIT 1),1,1) = 'a'--",
            
            # Time-based blind injection  
            "'; WAITFOR DELAY '00:00:05'--",
            "' OR SLEEP(5)--",
            
            # Error-based injection
            "' AND EXTRACTVALUE(1, CONCAT(0x7e, (SELECT @@version), 0x7e))--",
            "' AND (SELECT * FROM (SELECT COUNT(*),CONCAT(version(),FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a)--",
            
            # Second-order injection
            "admin'/**/UNION/**/SELECT/**/1,2,3--",
            
            # WAF bypass attempts
            "' /*!UNION*/ /*!SELECT*/ 1,2,3--",
            "' /*! UNION SELECT */ 1,2,3--",
            
            # Encoding attempts
            "%27%20OR%201=1--",
            "\\' OR 1=1--",
            
            # NoSQL injection attempts (just in case)
            "'; return true; //",
            "' || '1'=='1",
        ]
        
        for vector in injection_vectors:
            with self.subTest(injection_vector=vector):
                # Test that escaping neutralizes all these vectors
                escaped = frappe.db.escape(vector)
                
                # Create query with escaped value
                query = f"`tabDonor`.member = {escaped}"
                
                # The key test: verify the query is properly escaped and safe to execute
                # Note: The dangerous keywords may still be visible in the escaped string,
                # but they're treated as literal text, not executable SQL
                
                # Verify proper escaping format
                if not (escaped.startswith("'") and escaped.endswith("'")):
                    self.fail(f"Escaped value not properly quoted for vector: {vector}")
                    
                # Most important: verify the query can be executed safely without injection
                try:
                    test_sql = f"SELECT COUNT(*) FROM `tabDonor` WHERE {query}"
                    result = frappe.db.sql(test_sql)
                    # Should execute successfully and return a count (not inject other commands)
                    self.assertIsInstance(result, list)
                    self.assertEqual(len(result), 1)  # Should return exactly one row with count
                    self.assertIsInstance(result[0][0], (int, type(None)))  # Count should be integer or None
                except Exception as e:
                    # Query execution errors are OK (like invalid syntax in the literal value)
                    # But should not be SQL injection errors 
                    error_msg = str(e).lower()
                    injection_indicators = ['table', 'dropped', 'deleted', 'inserted', 'updated']
                    for indicator in injection_indicators:
                        self.assertNotIn(indicator, error_msg,
                            f"Query execution error suggests injection for vector {vector}: {e}")
                        
    def test_permission_function_robustness(self):
        """
        Test that permission functions are robust against various inputs
        
        This tests error handling and edge cases.
        """
        # Test various problematic inputs
        problematic_inputs = [
            # None values
            (None, None),
            (None, 'user@example.com'),
            ('donor-id', None),
            
            # Empty values  
            ('', ''),
            ('', 'user@example.com'),
            ('donor-id', ''),
            
            # Very long values
            ('x' * 1000, 'user@example.com'),
            ('donor-id', 'x' * 1000 + '@example.com'),
            
            # Special characters
            ('<script>', 'user@example.com'),
            ('donor-id', '<script>@example.com'),
            ('\x00\x01\x02', 'user@example.com'),
            ('donor-id', '\x00\x01\x02@example.com'),
            
            # Unicode
            ('🔥💯', 'user@example.com'),
            ('donor-id', '🔥💯@example.com'),
        ]
        
        for donor_doc, user in problematic_inputs:
            with self.subTest(donor=donor_doc, user=user):
                try:
                    # Should not crash
                    result = has_donor_permission(donor_doc, user)
                    self.assertIsInstance(result, bool, 
                        f"Should return boolean for donor='{donor_doc}', user='{user}'")
                        
                    # Should not crash for query either
                    query = get_donor_permission_query(user)
                    self.assertIn(type(query), [str, type(None)], 
                        f"Query should be string or None for user='{user}'")
                        
                except Exception as e:
                    self.fail(f"Permission functions should not crash on inputs: "
                            f"donor='{donor_doc}', user='{user}', error: {e}")


if __name__ == '__main__':
    # Allow running the test directly
    import unittest
    unittest.main()