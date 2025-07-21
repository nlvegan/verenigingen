#!/usr/bin/env python3
"""
Test the fixed employee creation
Run with: bench --site dev.veganisme.net execute verenigingen.test_employee_fix.test_employee_creation
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestEmployeeFix(VereningingenTestCase):
    """Test employee creation with the fixed code using proper test framework"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        frappe.set_user("Administrator")
        
        # Ensure Volunteer designation exists
        self.ensure_volunteer_designation()
    
    def ensure_volunteer_designation(self):
        """Ensure Volunteer designation exists for testing"""
        designation_name = "Volunteer"
        
        if not frappe.db.exists("Designation", designation_name):
            designation_doc = frappe.new_doc("Designation")
            designation_doc.designation_name = designation_name
            designation_doc.save()
            self.track_doc("Designation", designation_doc.name)
    
    def test_employee_creation_with_volunteer(self):
        """Test employee creation for volunteer without existing employee_id"""
        
        # Create test member and volunteer using factory methods
        test_member = self.create_test_member(
            first_name="Employee",
            last_name="TestCase",
            email=f"employee.testcase.{frappe.utils.random_string(5)}@example.com"
        )
        
        test_volunteer = self.create_test_volunteer(
            member=test_member.name,
            volunteer_name="Employee Test Volunteer"
        )
        
        # Ensure volunteer doesn't have employee_id initially
        test_volunteer.employee_id = None
        test_volunteer.save()
        
        print(f"Testing employee creation for volunteer: {test_volunteer.volunteer_name}")
        
        # Test employee creation
        employee_id = test_volunteer.create_minimal_employee()
        
        self.assertIsNotNone(employee_id, "Employee creation should return employee ID")
        self.assertTrue(employee_id, "Employee ID should be truthy")
        
        print(f"✅ Successfully created employee: {employee_id}")
        
        # Verify volunteer was updated with employee_id
        test_volunteer.reload()
        self.assertEqual(test_volunteer.employee_id, employee_id, "Volunteer should be linked to employee")
        
        # Track employee for automatic cleanup
        self.track_doc("Employee", employee_id)
        
    def test_employee_creation_with_existing_employee_id(self):
        """Test that employee creation handles volunteers with existing employee_id"""
        
        # Create test member and volunteer
        test_member = self.create_test_member(
            first_name="ExistingEmployee",
            last_name="TestCase",
            email=f"existing.employee.{frappe.utils.random_string(5)}@example.com"
        )
        
        test_volunteer = self.create_test_volunteer(
            member=test_member.name,
            volunteer_name="Existing Employee Test Volunteer"
        )
        
        # First, create an employee
        first_employee_id = test_volunteer.create_minimal_employee()
        self.assertIsNotNone(first_employee_id, "First employee creation should succeed")
        self.track_doc("Employee", first_employee_id)
        
        # Now test creating another employee - should handle gracefully
        second_employee_id = test_volunteer.create_minimal_employee()
        
        # Should either return the existing employee_id or handle the duplicate gracefully
        if second_employee_id:
            # If a new employee was created, track it
            if second_employee_id != first_employee_id:
                self.track_doc("Employee", second_employee_id)
        
        print(f"✅ Handled existing employee case: first={first_employee_id}, second={second_employee_id}")
        
    def test_designation_creation(self):
        """Test Volunteer designation creation"""
        designation_name = "TestVolunteerDesignation"  # Use unique name for testing
        
        # Verify designation doesn't exist initially
        self.assertFalse(
            frappe.db.exists("Designation", designation_name),
            "Test designation should not exist initially"
        )
        
        # Create designation
        designation_doc = frappe.new_doc("Designation")
        designation_doc.designation_name = designation_name
        designation_doc.save()
        
        self.track_doc("Designation", designation_doc.name)
        
        # Verify designation was created
        self.assertTrue(
            frappe.db.exists("Designation", designation_name),
            "Designation should exist after creation"
        )
        
        print(f"✅ Successfully created designation: {designation_name}")
        
    def test_employee_designation_assignment(self):
        """Test that created employees get proper designation"""
        
        # Create test data
        test_member = self.create_test_member(
            first_name="Designation",
            last_name="TestCase",
            email=f"designation.testcase.{frappe.utils.random_string(5)}@example.com"
        )
        
        test_volunteer = self.create_test_volunteer(
            member=test_member.name,
            volunteer_name="Designation Test Volunteer"
        )
        
        # Create employee
        employee_id = test_volunteer.create_minimal_employee()
        self.assertIsNotNone(employee_id, "Employee creation should succeed")
        self.track_doc("Employee", employee_id)
        
        # Verify employee has correct designation
        employee_doc = frappe.get_doc("Employee", employee_id)
        self.assertEqual(
            employee_doc.designation, "Volunteer",
            "Employee should have Volunteer designation"
        )
        
        print(f"✅ Employee {employee_id} has correct designation: {employee_doc.designation}")


@frappe.whitelist()
def test_employee_creation():
    """Legacy whitelist function for backwards compatibility"""
    try:
        # Find a volunteer without employee_id or create one for testing
        volunteer = frappe.db.get_value(
            "Volunteer", {"employee_id": ["is", "not set"]}, ["name", "volunteer_name"], as_dict=True
        )

        if not volunteer:
            return {"success": False, "message": "No volunteers without employee_id found for testing"}

        print(f"Testing employee creation for volunteer: {volunteer.volunteer_name}")

        # Get volunteer document
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

        # Test employee creation
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id:
            return {
                "success": True,
                "message": f"Successfully created employee: {employee_id}",
                "volunteer": volunteer.name,
                "employee_id": employee_id}
        else:
            return {"success": False, "message": "Employee creation returned None"}

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
def test_designation_creation():
    """Legacy whitelist function for backwards compatibility"""
    try:
        designation_name = "Volunteer"

        if frappe.db.exists("Designation", designation_name):
            return {"success": True, "message": f"Designation {designation_name} already exists"}

        # Create designation
        designation_doc = frappe.new_doc("Designation")
        designation_doc.designation_name = designation_name
        designation_doc.save()

        return {"success": True, "message": f"Successfully created designation: {designation_name}"}

    except Exception as e:
        return {"success": False, "message": f"Error creating designation: {str(e)}"}


def run_employee_fix_tests():
    """Run employee fix tests"""
    import unittest
    
    print("👨‍💼 Running Employee Fix Tests...")
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEmployeeFix)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All employee fix tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for failure in result.failures:
            print(f"FAIL: {failure[0]}")
            print(f"  {failure[1]}")
        for error in result.errors:
            print(f"ERROR: {error[0]}")
            print(f"  {error[1]}")
        return False


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Run new test framework
    run_employee_fix_tests()
    
    # Also run legacy tests for backwards compatibility
    print("\n=== Legacy Test Results ===")
    print("=== Testing Designation Creation ===")
    result = test_designation_creation()
    print(f"Result: {result}")

    print("\n=== Testing Employee Creation ===")
    result = test_employee_creation()
    print(f"Result: {result}")

    frappe.destroy()
