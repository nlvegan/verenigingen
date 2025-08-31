"""
Phase 5.2B Volunteer Operations Mock Elimination: Real Database Validation Testing

This test eliminates inappropriate business logic mocks from volunteer operations
workflows. Replaces mocked volunteer management with real database operations
to discover hidden production issues.

ELIMINATED INAPPROPRIATE MOCKS:
- @patch('verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record') - Real volunteer lookup
- @patch.object(volunteer, 'create_minimal_employee') - Real employee creation business logic
- @patch('verenigingen.utils.termination_integration.suspend_team_memberships_safe') - Real team membership management
- Mock return values for volunteer business validation - Real business rule validation

RETAINED APPROPRIATE PATTERNS:
- External service mocks (email, ERPNext API calls if needed) - if any
- Test data cleanup and setup procedures

This conversion demonstrates Phase 5.2B mock elimination principles:
1. Keep only external service mocks (email, external APIs)
2. Eliminate all internal volunteer business logic mocks
3. Use real database operations for volunteer record management
4. Test actual volunteer-to-employee creation business rules
5. Discover production issues that mocked tests missed
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerOperationsPhase5_2BMockElimination(EnhancedTestCase):
    """
    Real business logic tests for volunteer operations without inappropriate mocks
    
    Phase 5.2B: Tests actual volunteer record management and business rules
    """
    
    def setUp(self):
        """Set up test data with real database operations"""
        super().setUp()
        
        # Create test members using real Enhanced Test Factory
        self.member1 = self.create_test_member(
            first_name="Phase5_2B",
            last_name="Volunteer1",
            birth_date="1985-03-15"  # Over 16, can be volunteer
        )
        
        self.member2 = self.create_test_member(
            first_name="Phase5_2B", 
            last_name="Volunteer2",
            birth_date="1990-07-22"  # Over 16, can be volunteer
        )
        
        # Create test volunteer team using real database operations
        # 🔧 PHASE 5.2B PRODUCTION ISSUE DISCOVERED: Field name mismatch
        # Enhanced Test Factory used 'team_description' but Team DocType field is 'description'
        self.test_team = self.create_test_team(
            team_name="Phase 5.2B Test Team",
            description="Testing volunteer operations without mocks"  # Fixed field name
        )

    def test_volunteer_record_lookup_real_database(self):
        """Test volunteer record lookup with real database operations (NO MOCKS)"""
        
        # PHASE 5.2B: NO MOCKING - Use real volunteer creation and lookup
        # This will test actual volunteer business logic and may discover production issues
        
        # Create real volunteer record
        volunteer1 = self.create_test_volunteer(self.member1.name, 
            volunteer_skills=["Communication", "Event Management"]
        )
        
        # Test real volunteer lookup - this may discover production issues
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record
        
        # Set user context to test real lookup logic
        frappe.set_user(self.member1.email)
        
        try:
            # This should use real database lookup without mocks
            result = get_user_volunteer_record()
            
            # PHASE 5.2B VALIDATION: Verify real volunteer lookup occurred
            self.assertIsNotNone(result, "Real volunteer lookup should return volunteer record")
            self.assertEqual(result.name, volunteer1.name, "Should return correct volunteer record")
            self.assertEqual(result.member, self.member1.name, "Should link to correct member")
            
        except Exception as e:
            # If real lookup fails, we've discovered a production issue!
            self.fail(f"Real volunteer lookup failed - production issue discovered: {e}")
        
        finally:
            frappe.set_user("Administrator")

    def test_volunteer_employee_creation_real_business_logic(self):
        """Test volunteer employee creation with real business logic (NO MOCKS)"""
        
        # PHASE 5.2B: NO MOCKING - Test real employee creation business rules
        
        volunteer2 = self.create_test_volunteer(self.member2.name,
            volunteer_skills=["Finance", "Administration"]
        )
        
        # Verify volunteer has no employee initially
        self.assertIsNone(volunteer2.employee_id, "Volunteer should start without employee record")
        
        # Test real employee creation business logic
        try:
            # This should trigger real employee creation workflow
            employee_id = volunteer2.create_minimal_employee()
            
            # PHASE 5.2B VALIDATION: Verify real employee creation occurred
            self.assertIsNotNone(employee_id, "Real employee creation should return employee ID")
            
            # Reload volunteer to check employee link was created
            volunteer2.reload()
            self.assertEqual(volunteer2.employee_id, employee_id, "Volunteer should be linked to created employee")
            
            # Verify employee record actually exists in database
            employee_exists = frappe.db.exists("Employee", employee_id)
            self.assertTrue(employee_exists, "Employee record should exist in database")
            
            # Verify employee record has correct data
            employee_doc = frappe.get_doc("Employee", employee_id)
            self.assertEqual(employee_doc.employee_name, volunteer2.volunteer_name)
            self.assertEqual(employee_doc.personal_email, self.member2.email)
            
        except Exception as e:
            # If real employee creation fails, we've discovered a production issue!
            self.fail(f"Real employee creation failed - production issue discovered: {e}")

    def test_team_membership_management_real_operations(self):
        """Test team membership management with real database operations (NO MOCKS)"""
        
        # PHASE 5.2B: NO MOCKING - Use real team membership management
        
        # Create volunteers and add to team with real operations
        volunteer1 = self.create_test_volunteer(self.member1.name)
        volunteer2 = self.create_test_volunteer(self.member2.name)
        
        # Add volunteers to team with real team membership operations
        team_member1 = self.create_test_team_member(
            self.test_team.name, 
            volunteer1.name,
            team_role_name="Team Member"
        )
        
        team_member2 = self.create_test_team_member(
            self.test_team.name,
            volunteer2.name, 
            team_role_name="Team Leader"
        )
        
        # Verify team memberships were created with real database operations
        team_members = frappe.get_all("Volunteer Team Member", 
            filters={"parent": self.test_team.name}, 
            fields=["volunteer", "team_role", "enabled"]
        )
        
        self.assertEqual(len(team_members), 2, "Should have 2 real team members")
        
        volunteer_names = [tm["volunteer"] for tm in team_members]
        self.assertIn(volunteer1.name, volunteer_names, "First volunteer should be in team")
        self.assertIn(volunteer2.name, volunteer_names, "Second volunteer should be in team")
        
        # Test real team membership suspension (instead of mocking suspend_team_memberships_safe)
        try:
            from verenigingen.utils.termination_integration import suspend_team_memberships_safe
            
            # This should use real database operations to suspend team memberships
            result = suspend_team_memberships_safe(volunteer1.name)
            
            # PHASE 5.2B VALIDATION: Verify real team suspension occurred
            if result:  # If suspension was successful
                # Check that team membership was actually disabled in database
                suspended_member = frappe.get_doc("Volunteer Team Member", {
                    "parent": self.test_team.name,
                    "volunteer": volunteer1.name
                })
                
                # This assertion may FAIL and reveal production issues!
                # If suspend_team_memberships_safe has bugs, we'll discover them
                self.assertFalse(suspended_member.enabled, 
                               "Real team suspension should disable membership")
                
                # Verify other team member remains active
                active_member = frappe.get_doc("Volunteer Team Member", {
                    "parent": self.test_team.name,
                    "volunteer": volunteer2.name
                })
                self.assertTrue(active_member.enabled, 
                              "Other team members should remain active")
            
        except Exception as e:
            # If real team suspension fails, we've discovered a production issue!
            self.fail(f"Real team membership suspension failed - production issue discovered: {e}")

    def test_volunteer_expense_business_validation_real_rules(self):
        """Test volunteer expense business validation with real business rules (NO MOCKS)"""
        
        # PHASE 5.2B: NO MOCKING - Test real expense validation business logic
        
        volunteer1 = self.create_test_volunteer(self.member1.name)
        
        # Test real expense business validation without mocking
        expense_data = {
            "expense_date": today(),
            "expense_type": "Travel",
            "amount": 125.50,
            "description": "Phase 5.2B Test Expense", 
            "receipt_required": True
        }
        
        try:
            # This should use real business validation rules
            from verenigingen.templates.pages.volunteer.expenses import validate_expense_data
            
            # Test real validation logic - may discover production issues
            validation_result = validate_expense_data(expense_data, volunteer1.name)
            
            # PHASE 5.2B VALIDATION: Verify real validation occurred
            self.assertTrue(validation_result.get("valid", False), 
                           "Real expense validation should pass for valid data")
            
            # Test invalid expense data to verify real validation logic
            invalid_expense_data = {
                "expense_date": add_days(today(), 1),  # Future date should fail
                "expense_type": "Invalid Type",
                "amount": -50,  # Negative amount should fail
                "description": "",  # Empty description should fail
            }
            
            invalid_result = validate_expense_data(invalid_expense_data, volunteer1.name)
            
            # This assertion may FAIL and reveal production validation issues!
            self.assertFalse(invalid_result.get("valid", True),
                            "Real expense validation should reject invalid data")
            
            # Verify specific validation errors are returned
            errors = invalid_result.get("errors", [])
            self.assertGreater(len(errors), 0, 
                             "Real validation should return specific error messages")
            
        except Exception as e:
            # If validation function doesn't exist or fails, we've discovered a production issue!
            self.fail(f"Real expense validation failed - production issue discovered: {e}")

    def test_volunteer_organization_access_real_permissions(self):
        """Test volunteer organization access with real permission validation (NO MOCKS)"""
        
        # PHASE 5.2B: Test real volunteer permission logic without session mocking
        
        volunteer1 = self.create_test_volunteer(self.member1.name)
        
        # Add volunteer to team to give them real permissions
        team_member = self.create_test_team_member(
            self.test_team.name,
            volunteer1.name, 
            team_role_name="Team Member"
        )
        
        # Test real organization access validation
        try:
            from verenigingen.templates.pages.volunteer.expenses import validate_volunteer_organization_access
            
            # Set user context to test real permission checking
            frappe.set_user(self.member1.email)
            
            # This should use real permission validation without mocks
            access_result = validate_volunteer_organization_access(
                volunteer1.name, 
                "Team",
                self.test_team.name
            )
            
            # PHASE 5.2B VALIDATION: Verify real permission checking occurred  
            self.assertTrue(access_result.get("has_access", False),
                           "Volunteer with team membership should have access")
            
            # Test access to organization they're not part of
            unauthorized_access = validate_volunteer_organization_access(
                volunteer1.name,
                "Team", 
                "Non-Existent Team"
            )
            
            # This assertion may reveal production permission issues
            self.assertFalse(unauthorized_access.get("has_access", True),
                            "Real permission validation should deny unauthorized access")
            
        except Exception as e:
            # If permission validation fails, it reveals real production permission issues
            self.fail(f"Real volunteer permission validation failed: {str(e)}")
            
        finally:
            frappe.set_user("Administrator")

    def test_volunteer_skill_management_real_database(self):
        """Test volunteer skill management with real database operations (NO MOCKS)"""
        
        # PHASE 5.2B: Test real volunteer skill assignment and validation
        
        # Create volunteer with skills using real operations
        initial_skills = ["Communication", "Event Management", "Finance"]
        volunteer1 = self.create_test_volunteer(self.member1.name, 
            volunteer_skills=initial_skills
        )
        
        # Verify skills were stored in real database
        volunteer_skills = frappe.get_all("Volunteer Skill", 
            filters={"parent": volunteer1.name},
            fields=["skill_name", "proficiency_level"]
        )
        
        self.assertEqual(len(volunteer_skills), len(initial_skills),
                        "All skills should be stored in database")
        
        stored_skill_names = [skill["skill_name"] for skill in volunteer_skills]
        for skill in initial_skills:
            self.assertIn(skill, stored_skill_names, f"Skill '{skill}' should be stored")
        
        # Test skill modification with real database operations
        try:
            # Add new skill using real business logic
            volunteer1.append("volunteer_skills", {
                "skill_name": "Leadership",
                "proficiency_level": "Intermediate"
            })
            volunteer1.save()
            
            # Verify skill was added to real database
            updated_skills = frappe.get_all("Volunteer Skill",
                filters={"parent": volunteer1.name},
                fields=["skill_name"]
            )
            
            self.assertEqual(len(updated_skills), len(initial_skills) + 1,
                            "New skill should be added to database")
            
            updated_skill_names = [skill["skill_name"] for skill in updated_skills]
            self.assertIn("Leadership", updated_skill_names, "New skill should be present")
            
        except Exception as e:
            # If skill management fails, we've discovered a production issue!
            self.fail(f"Real volunteer skill management failed - production issue discovered: {e}")

    def tearDown(self):
        """Clean up test data"""
        # Let Enhanced Test Factory handle cleanup
        super().tearDown()


print("Phase 5.2B Volunteer Operations Mock Elimination Test Created")
print("=" * 62)
print("This test eliminates inappropriate business logic mocks from volunteer")
print("operations workflows and will discover production issues that mocked")
print("tests missed.")
print("")
print("Key eliminations:")
print("- get_user_volunteer_record() mocking → Real volunteer database lookup")
print("- create_minimal_employee() mocking → Real employee creation business logic")
print("- suspend_team_memberships_safe() mocking → Real team membership management")
print("- Volunteer expense validation mocking → Real business rule validation")
print("- Permission checking mocking → Real volunteer permission validation")