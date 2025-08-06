#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test function for SecureTestDataFactory
"""

import frappe
from verenigingen.tests.fixtures.field_validator import FieldValidator, validate_field


@frappe.whitelist()
def test_field_validator():
    """Test the field validator functionality"""
    try:
        print("Testing FieldValidator...")
        
        validator = FieldValidator()
        
        # Test Member fields
        print("Testing Member fields...")
        validator.validate_field_exists("Member", "first_name")
        print("✅ Member.first_name exists")
        
        validator.validate_field_exists("Member", "email")
        print("✅ Member.email exists")
        
        # Test invalid field
        try:
            validator.validate_field_exists("Member", "nonexistent_field")
            print("❌ Should have failed for nonexistent field")
        except Exception as e:
            print(f"✅ Correctly caught nonexistent field: {e}")
            
        # Test Volunteer fields
        print("Testing Volunteer fields...")
        validator.validate_field_exists("Volunteer", "volunteer_name")
        print("✅ Volunteer.volunteer_name exists")
        
        validator.validate_field_exists("Volunteer", "member")
        print("✅ Volunteer.member exists")
        
        # Test required fields
        required = validator.get_required_fields("Member")
        print(f"✅ Member required fields: {required}")
        
        print("✅ FieldValidator test completed successfully")
        return {"success": True, "message": "FieldValidator test passed"}
        
    except Exception as e:
        print(f"❌ FieldValidator test failed: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_schema_validation():
    """Test schema validation features"""
    try:
        print("Testing schema validation...")
        
        # Test convenience functions
        validate_field("Member", "first_name")
        print("✅ Convenience function validate_field works")
        
        # Test field existence checks for volunteer skills tests
        fields_to_check = [
            ("Member", "first_name"),
            ("Member", "last_name"),
            ("Member", "email"),
            ("Member", "birth_date"),
            ("Member", "status"),
            ("Member", "notes"),
            ("Member", "contact_number"),
            ("Verenigingen Volunteer", "volunteer_name"),
            ("Verenigingen Volunteer", "member"),
            ("Verenigingen Volunteer", "status"),
            ("Verenigingen Volunteer", "email"),
            ("Verenigingen Volunteer", "start_date"),
            ("Volunteer Skill", "skill_category"),
            ("Volunteer Skill", "volunteer_skill"),
            ("Volunteer Skill", "proficiency_level"),
            ("Volunteer Skill", "experience_years")
        ]
        
        for doctype, field in fields_to_check:
            validate_field(doctype, field)
            print(f"✅ {doctype}.{field} validated")
            
        print("✅ Schema validation test completed successfully")
        return {"success": True, "message": "Schema validation test passed"}
        
    except Exception as e:
        print(f"❌ Schema validation test failed: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_secure_factory_basic():
    """Test basic SecureTestDataFactory functionality"""
    try:
        from verenigingen.tests.fixtures.secure_test_data_factory import SecureTestContext
        
        print("Testing SecureTestDataFactory...")
        
        with SecureTestContext(seed=12345) as factory:
            # Test member creation
            member = factory.create_member(first_name="TestUser", last_name="Secure")
            print(f"✅ Created member: {member.name}")
            
            # Test volunteer creation
            volunteer = factory.create_volunteer(member.name, volunteer_name="Test Volunteer")
            print(f"✅ Created volunteer: {volunteer.name}")
            
            # Test application data generation
            app_data = factory.create_application_data(with_volunteer_skills=True)
            print(f"✅ Generated application data for: {app_data['email']}")
            
            # Test deterministic data
            iban1 = factory.create_test_iban()
            iban2 = factory.create_test_iban()
            print(f"✅ Generated test IBANs: {iban1}, {iban2}")
            
            print("✅ SecureTestDataFactory basic test completed successfully")
            
        print("✅ Cleanup completed automatically")
        return {"success": True, "message": "SecureTestDataFactory basic test passed"}
        
    except Exception as e:
        print(f"❌ SecureTestDataFactory test failed: {e}")
        frappe.log_error(frappe.get_traceback(), "SecureTestDataFactory Test Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def run_all_factory_tests():
    """Run all factory tests"""
    results = []
    
    # Test field validator
    result1 = test_field_validator()
    results.append(("FieldValidator", result1))
    
    # Test schema validation
    result2 = test_schema_validation()
    results.append(("SchemaValidation", result2))
    
    # Test secure factory
    result3 = test_secure_factory_basic()
    results.append(("SecureFactory", result3))
    
    # Summary
    successes = sum(1 for _, result in results if result.get("success"))
    total = len(results)
    
    print(f"\n📊 Test Summary: {successes}/{total} tests passed")
    
    for test_name, result in results:
        status = "✅ PASS" if result.get("success") else "❌ FAIL"
        print(f"  {status} {test_name}")
        if not result.get("success"):
            print(f"    Error: {result.get('error', 'Unknown error')}")
            
    return {
        "success": successes == total,
        "total_tests": total,
        "passed": successes,
        "results": results
    }