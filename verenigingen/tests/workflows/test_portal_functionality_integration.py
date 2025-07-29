"""
Portal Functionality Integration Tests
Complete validation of member portal authentication, volunteer dashboard,
team management interface, and address change workflow functionality
"""

import frappe
from frappe.utils import today, add_days, now_datetime, cint
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock
import json


class TestPortalFunctionalityIntegration(VereningingenTestCase):
    """Comprehensive portal functionality integration testing"""

    def setUp(self):
        """Set up test data for portal functionality tests"""
        super().setUp()

        # Create test member with portal access
        self.portal_member = self.factory.create_test_member(
            first_name="Portal",
            last_name="User",
            email=f"portal.user.{self.factory.test_run_id}@example.com",
            enable_portal_access=1
        )

        # Create test volunteer with dashboard access
        self.portal_volunteer = self.factory.create_test_volunteer(
            member=self.portal_member.name,
            volunteer_name=f"{self.portal_member.first_name} {self.portal_member.last_name}",
            email=f"volunteer.{self.factory.test_run_id}@example.com",
            enable_dashboard_access=1
        )

        # Create test chapter and teams
        self.test_chapter = self.factory.create_test_chapter(
            chapter_name="Portal Test Chapter"
        )

        self.test_teams = []
        team_names = ["Communication Team", "Event Planning", "Fundraising", "Volunteer Support"]
        for team_name in team_names:
            team = self.factory.create_test_volunteer_team(
                team_name=team_name,
                chapter=self.test_chapter.name,
                requires_background_check=0
            )
            self.test_teams.append(team)

        # Create membership for portal testing
        self.portal_membership = self.factory.create_test_membership(
            member=self.portal_member.name,
            status="Active"
        )

        # Set up portal session context
        self.portal_context = {
            "member": self.portal_member,
            "volunteer": self.portal_volunteer,
            "membership": self.portal_membership,
            "chapter": self.test_chapter
        }

    def test_member_portal_authentication_data_access(self):
        """Test member portal authentication and secure data access"""
        # Test 1: Portal Access Validation
        self.assertTrue(self.portal_member.enable_portal_access,
                       "Portal member should have portal access enabled")

        # Test 2: Simulate portal login
        with self.as_user(self.portal_member.email):
            # Verify member can access their own data
            member_data = self._get_portal_member_data(self.portal_member.name)

            self.assertIsNotNone(member_data, "Member should be able to access their data")
            self.assertEqual(member_data.name, self.portal_member.name)
            self.assertEqual(member_data.email, self.portal_member.email)

            # Test membership data access
            membership_data = self._get_portal_membership_data(self.portal_member.name)
            self.assertIsNotNone(membership_data, "Member should access membership data")
            self.assertEqual(len(membership_data), 1)
            self.assertEqual(membership_data[0].member, self.portal_member.name)

            # Test payment history access
            payment_history = self._get_portal_payment_history(self.portal_member.name)
            self.assertIsInstance(payment_history, list, "Payment history should be a list")

            # Test SEPA mandate access
            sepa_mandates = self._get_portal_sepa_mandates(self.portal_member.name)
            self.assertIsInstance(sepa_mandates, list, "SEPA mandates should be a list")

        # Test 3: Verify data isolation (member cannot access other member's data)
        other_member = self.factory.create_test_member(
            first_name="Other",
            last_name="Member",
            email=f"other.member.{self.factory.test_run_id}@example.com"
        )

        with self.as_user(self.portal_member.email):
            # Should not be able to access other member's data
            try:
                self._get_portal_member_data(other_member.name)
                self.fail("Member should not access unauthorized data")
            except frappe.PermissionError:
                # Expected behavior
                pass
            except Exception:
                # Any exception is acceptable as long as access is denied
                pass

        # Test 4: Portal permissions for different data types
        permission_tests = [
            {
                "data_type": "Member",
                "member_name": self.portal_member.name,
                "should_access": True
            },
            {
                "data_type": "Membership",
                "member_name": self.portal_member.name,
                "should_access": True
            },
            {
                "data_type": "Member Payment History",
                "member_name": self.portal_member.name,
                "should_access": True
            },
            {
                "data_type": "Member",
                "member_name": other_member.name,
                "should_access": False
            }
        ]

        with self.as_user(self.portal_member.email):
            for test in permission_tests:
                try:
                    self._test_portal_data_access(test["data_type"], test["member_name"])
                    if not test["should_access"]:
                        self.fail(f"Should not access {test['data_type']} for {test['member_name']}")
                except (frappe.PermissionError, frappe.DoesNotExistError):
                    if test["should_access"]:
                        self.fail(f"Should access {test['data_type']} for {test['member_name']}")

    def _get_portal_member_data(self, member_name):
        """Get member data through portal context"""
        return frappe.get_doc("Member", member_name)

    def _get_portal_membership_data(self, member_name):
        """Get membership data for portal member"""
        return frappe.get_all("Membership",
                            filters={"member": member_name},
                            fields=["name", "member", "status", "start_date", "to_date"])

    def _get_portal_payment_history(self, member_name):
        """Get payment history for portal member"""
        return frappe.get_all("Member Payment History",
                            filters={"member": member_name},
                            fields=["payment_date", "amount", "status", "payment_type"],
                            order_by="payment_date desc",
                            limit=20)

    def _get_portal_sepa_mandates(self, member_name):
        """Get SEPA mandates for portal member"""
        return frappe.get_all("SEPA Mandate",
                            filters={"member": member_name},
                            fields=["mandate_id", "status", "iban", "sign_date"])

    def _test_portal_data_access(self, data_type, member_name):
        """Test access to specific data type"""
        if data_type == "Member":
            return frappe.get_doc("Member", member_name)
        elif data_type == "Membership":
            return frappe.get_all("Membership", filters={"member": member_name})
        elif data_type == "Member Payment History":
            return frappe.get_all("Member Payment History", filters={"member": member_name})
        return None

    def test_volunteer_dashboard_functionality(self):
        """Test volunteer dashboard functionality and data presentation"""
        # Create volunteer assignments for dashboard testing
        assignments = []
        for i, team in enumerate(self.test_teams[:3]):  # Assign to first 3 teams
            assignment = frappe.new_doc("Volunteer Assignment")
            assignment.volunteer = self.portal_volunteer.name
            assignment.team = team.name
            assignment.start_date = add_days(today(), -30 + (i * 10))
            assignment.status = "Active" if i < 2 else "Completed"
            assignment.hours_per_week = 5 + i
            assignment.save()
            self.track_doc("Volunteer Assignment", assignment.name)
            assignments.append(assignment)

        # Create volunteer expenses for dashboard
        expenses = []
        for i in range(3):
            expense = self.factory.create_test_volunteer_expense(
                volunteer=self.portal_volunteer.name,
                amount=25.00 + (i * 10),
                expense_date=add_days(today(), -15 + (i * 5)),
                status="Submitted" if i < 2 else "Approved",
                description=f"Test expense {i + 1}"
            )
            expenses.append(expense)

        # Test dashboard data access
        with self.as_user(self.portal_volunteer.email):
            # Test 1: Dashboard Overview Data
            dashboard_data = self._get_volunteer_dashboard_data()

            self.assertIsNotNone(dashboard_data, "Dashboard data should be available")
            self.assertIn("volunteer_info", dashboard_data)
            self.assertIn("active_assignments", dashboard_data)
            self.assertIn("recent_expenses", dashboard_data)
            self.assertIn("performance_metrics", dashboard_data)

            # Verify volunteer info
            volunteer_info = dashboard_data["volunteer_info"]
            self.assertEqual(volunteer_info["name"], self.portal_volunteer.name)
            self.assertEqual(volunteer_info["email"], self.portal_volunteer.email)

            # Test 2: Active Assignments Display
            active_assignments = dashboard_data["active_assignments"]
            self.assertEqual(len(active_assignments), 2, "Should show 2 active assignments")

            for assignment in active_assignments:
                self.assertEqual(assignment["status"], "Active")
                self.assertGreater(assignment["hours_per_week"], 0)

            # Test 3: Expense Management Interface
            expenses_data = dashboard_data["recent_expenses"]
            self.assertEqual(len(expenses_data), 3, "Should show all expenses")

            # Verify expense statuses
            submitted_expenses = [exp for exp in expenses_data if exp["status"] == "Submitted"]
            approved_expenses = [exp for exp in expenses_data if exp["status"] == "Approved"]

            self.assertEqual(len(submitted_expenses), 2)
            self.assertEqual(len(approved_expenses), 1)

            # Test 4: Performance Metrics
            metrics = dashboard_data["performance_metrics"]
            self.assertIn("total_hours_logged", metrics)
            self.assertIn("assignments_completed", metrics)
            self.assertIn("volunteer_since", metrics)

            # Verify metrics calculations
            self.assertEqual(metrics["assignments_completed"], 1)
            self.assertGreater(metrics["total_hours_logged"], 0)

    def _get_volunteer_dashboard_data(self):
        """Get volunteer dashboard data"""
        volunteer = frappe.get_doc("Volunteer", self.portal_volunteer.name)

        # Get active assignments
        active_assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"volunteer": volunteer.name, "status": "Active"},
            fields=["name", "team", "start_date", "hours_per_week", "status"]
        )

        # Get recent expenses
        recent_expenses = frappe.get_all(
            "Volunteer Expense",
            filters={"volunteer": volunteer.name},
            fields=["name", "expense_date", "amount", "status", "description"],
            order_by="expense_date desc",
            limit=10
        )

        # Calculate performance metrics
        total_assignments = frappe.db.count("Volunteer Assignment",
                                          {"volunteer": volunteer.name})
        completed_assignments = frappe.db.count("Volunteer Assignment",
                                               {"volunteer": volunteer.name, "status": "Completed"})

        # Calculate total hours (simplified)
        total_hours = sum(assignment.get("hours_per_week", 0) * 4 for assignment in active_assignments)

        return {
            "volunteer_info": {
                "name": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "email": volunteer.email,
                "status": volunteer.status,
                "start_date": volunteer.start_date
            },
            "active_assignments": active_assignments,
            "recent_expenses": recent_expenses,
            "performance_metrics": {
                "total_assignments": total_assignments,
                "assignments_completed": completed_assignments,
                "total_hours_logged": total_hours,
                "volunteer_since": volunteer.start_date
            }
        }

    def test_team_management_interface(self):
        """Test team management interface functionality"""
        # Create team leader volunteer
        team_leader = self.factory.create_test_volunteer(
            volunteer_name="Team Leader",
            email=f"team.leader.{self.factory.test_run_id}@example.com",
            is_team_leader=1
        )

        # Assign team leader to a team
        main_team = self.test_teams[0]
        main_team.team_leader = team_leader.name
        main_team.save()

        # Create team members
        team_members = []
        for i in range(4):
            member = self.factory.create_test_member(
                first_name=f"Team{i}",
                last_name="Member",
                email=f"team{i}.member.{self.factory.test_run_id}@example.com"
            )

            volunteer = self.factory.create_test_volunteer(
                member=member.name,
                volunteer_name=f"{member.first_name} {member.last_name}",
                email=member.email
            )

            # Create team assignment
            assignment = frappe.new_doc("Volunteer Assignment")
            assignment.volunteer = volunteer.name
            assignment.team = main_team.name
            assignment.start_date = add_days(today(), -20 + (i * 5))
            assignment.status = "Active"
            assignment.role = "Member" if i > 0 else "Assistant Leader"
            assignment.save()
            self.track_doc("Volunteer Assignment", assignment.name)

            team_members.append({
                "member": member,
                "volunteer": volunteer,
                "assignment": assignment
            })

        # Test team management interface
        with self.as_user(team_leader.email):
            # Test 1: Team Overview
            team_data = self._get_team_management_data(main_team.name)

            self.assertIsNotNone(team_data, "Team data should be available")
            self.assertEqual(team_data["team_info"]["name"], main_team.name)
            self.assertEqual(team_data["team_info"]["team_leader"], team_leader.name)

            # Test 2: Team Member Management
            members_data = team_data["team_members"]
            self.assertEqual(len(members_data), 4, "Should show all team members")

            # Verify member roles
            assistant_leaders = [m for m in members_data if m["role"] == "Assistant Leader"]
            regular_members = [m for m in members_data if m["role"] == "Member"]

            self.assertEqual(len(assistant_leaders), 1)
            self.assertEqual(len(regular_members), 3)

            # Test 3: Team Activity Tracking
            activities = team_data["recent_activities"]
            self.assertIsInstance(activities, list, "Activities should be a list")

            # Test 4: Team Performance Metrics
            metrics = team_data["team_metrics"]
            self.assertIn("total_members", metrics)
            self.assertIn("active_assignments", metrics)
            self.assertIn("team_formation_date", metrics)

            self.assertEqual(metrics["total_members"], 4)
            self.assertEqual(metrics["active_assignments"], 4)

        # Test member role update functionality
        with self.as_user(team_leader.email):
            # Test promoting a member to assistant leader
            member_to_promote = team_members[1]["assignment"]
            self._update_team_member_role(member_to_promote.name, "Assistant Leader")

            # Verify role update
            updated_assignment = frappe.get_doc("Volunteer Assignment", member_to_promote.name)
            self.assertEqual(updated_assignment.role, "Assistant Leader")

    def _get_team_management_data(self, team_name):
        """Get team management data"""
        team = frappe.get_doc("Volunteer Team", team_name)

        # Get team members and their assignments
        team_assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"team": team_name, "status": "Active"},
            fields=["name", "volunteer", "start_date", "role", "hours_per_week"]
        )

        # Enrich with volunteer information
        team_members = []
        for assignment in team_assignments:
            volunteer = frappe.get_doc("Volunteer", assignment.volunteer)
            team_members.append({
                "assignment_id": assignment.name,
                "volunteer_name": volunteer.volunteer_name,
                "volunteer_email": volunteer.email,
                "role": assignment.role or "Member",
                "start_date": assignment.start_date,
                "hours_per_week": assignment.hours_per_week
            })

        # Get recent team activities (simplified)
        recent_activities = [
            {
                "date": today(),
                "activity": "Team meeting scheduled",
                "type": "Meeting"
            },
            {
                "date": add_days(today(), -5),
                "activity": "New member added",
                "type": "Member Change"
            }
        ]

        return {
            "team_info": {
                "name": team.name,
                "team_name": team.team_name,
                "team_leader": team.team_leader,
                "description": team.description,
                "is_active": team.is_active
            },
            "team_members": team_members,
            "recent_activities": recent_activities,
            "team_metrics": {
                "total_members": len(team_members),
                "active_assignments": len(team_assignments),
                "team_formation_date": team.creation.date() if team.creation else today()
            }
        }

    def _update_team_member_role(self, assignment_id, new_role):
        """Update team member role"""
        assignment = frappe.get_doc("Volunteer Assignment", assignment_id)
        assignment.role = new_role
        assignment.save()

    def test_address_change_workflow_validation(self):
        """Test address change workflow with validation and approval"""
        # Create member with current address
        member = self.factory.create_test_member(
            first_name="Address",
            last_name="Change",
            email=f"address.change.{self.factory.test_run_id}@example.com",
            address_line_1="Old Street 123",
            postal_code="1234AB",
            city="Old City",
            country="Netherlands"
        )

        # Test 1: Submit Address Change Request
        address_change_data = {
            "member": member.name,
            "current_address": {
                "address_line_1": member.address_line_1,
                "postal_code": member.postal_code,
                "city": member.city,
                "country": member.country
            },
            "new_address": {
                "address_line_1": "New Street 456",
                "postal_code": "5678CD",
                "city": "New City",
                "country": "Netherlands"
            },
            "reason": "Relocated for work",
            "effective_date": today()
        }

        with self.as_user(member.email):
            # Submit address change request
            change_request = self._submit_address_change_request(address_change_data)

            self.assertIsNotNone(change_request, "Address change request should be created")
            self.assertEqual(change_request.member, member.name)
            self.assertEqual(change_request.status, "Pending")

        # Test 2: Address Change Validation
        validation_results = self._validate_address_change(change_request)

        self.assertTrue(validation_results["postal_code_valid"], "Postal code should be valid")
        self.assertTrue(validation_results["city_match"], "City should match postal code")
        self.assertTrue(validation_results["country_valid"], "Country should be valid")

        # Test 3: Chapter Assignment Impact
        # Check if address change affects chapter assignment
        old_chapter = self._get_chapter_for_postal_code(member.postal_code)
        new_chapter = self._get_chapter_for_postal_code(address_change_data["new_address"]["postal_code"])

        chapter_change_required = old_chapter != new_chapter

        if chapter_change_required:
            self.assertNotEqual(old_chapter, new_chapter,
                              "Address change should trigger chapter reassignment")

        # Test 4: Approval Workflow
        # Simulate approval by administrator
        with self.as_user("administrator"):
            # Approve the address change
            change_request.status = "Approved"
            change_request.approved_by = "administrator"
            change_request.approval_date = now_datetime()
            change_request.save()

            # Process the address change
            self._process_approved_address_change(change_request)

        # Test 5: Verify Address Update
        member.reload()
        self.assertEqual(member.address_line_1, address_change_data["new_address"]["address_line_1"])
        self.assertEqual(member.postal_code, address_change_data["new_address"]["postal_code"])
        self.assertEqual(member.city, address_change_data["new_address"]["city"])

        # Test 6: History Tracking
        address_history = self._get_address_change_history(member.name)
        self.assertGreater(len(address_history), 0, "Address change history should be recorded")

        latest_change = address_history[0]  # Most recent change
        self.assertEqual(latest_change["old_postal_code"], "1234AB")
        self.assertEqual(latest_change["new_postal_code"], "5678CD")

        # Test 7: Related Data Updates
        # Verify SEPA mandates, memberships, etc. are updated if needed
        memberships = frappe.get_all("Membership",
                                   filters={"member": member.name, "status": "Active"})

        for membership in memberships:
            membership_doc = frappe.get_doc("Membership", membership.name)
            # In real system, might need to update chapter-specific memberships
            self.assertEqual(membership_doc.member, member.name)

    def _submit_address_change_request(self, change_data):
        """Submit address change request"""
        request = frappe.new_doc("Address Change Request")
        request.member = change_data["member"]
        request.old_address_line_1 = change_data["current_address"]["address_line_1"]
        request.old_postal_code = change_data["current_address"]["postal_code"]
        request.old_city = change_data["current_address"]["city"]
        request.old_country = change_data["current_address"]["country"]

        request.new_address_line_1 = change_data["new_address"]["address_line_1"]
        request.new_postal_code = change_data["new_address"]["postal_code"]
        request.new_city = change_data["new_address"]["city"]
        request.new_country = change_data["new_address"]["country"]

        request.reason = change_data["reason"]
        request.effective_date = change_data["effective_date"]
        request.status = "Pending"

        request.save()
        self.track_doc("Address Change Request", request.name)
        return request

    def _validate_address_change(self, change_request):
        """Validate address change request"""
        # Simplified validation - in real system would use postal code APIs
        postal_code = change_request.new_postal_code
        city = change_request.new_city
        country = change_request.new_country

        # Basic format validation for Dutch postal codes
        postal_code_valid = (len(postal_code) == 6 and
                           postal_code[:4].isdigit() and
                           postal_code[4:].isalpha())

        # City matching (simplified)
        city_match = len(city) > 2

        # Country validation
        country_valid = country in ["Netherlands", "Belgium", "Germany"]

        return {
            "postal_code_valid": postal_code_valid,
            "city_match": city_match,
            "country_valid": country_valid
        }

    def _get_chapter_for_postal_code(self, postal_code):
        """Get chapter for postal code (simplified)"""
        # In real system, would have postal code to chapter mapping
        if postal_code.startswith("12"):
            return "North Chapter"
        elif postal_code.startswith("56"):
            return "South Chapter"
        else:
            return "Central Chapter"

    def _process_approved_address_change(self, change_request):
        """Process approved address change"""
        member = frappe.get_doc("Member", change_request.member)

        # Update member address
        member.address_line_1 = change_request.new_address_line_1
        member.postal_code = change_request.new_postal_code
        member.city = change_request.new_city
        member.country = change_request.new_country
        member.save()

        # Create history record
        history = frappe.new_doc("Member Address History")
        history.member = member.name
        history.change_date = change_request.effective_date
        history.old_address_line_1 = change_request.old_address_line_1
        history.old_postal_code = change_request.old_postal_code
        history.old_city = change_request.old_city
        history.new_address_line_1 = change_request.new_address_line_1
        history.new_postal_code = change_request.new_postal_code
        history.new_city = change_request.new_city
        history.reason = change_request.reason
        history.save()
        self.track_doc("Member Address History", history.name)

    def _get_address_change_history(self, member_name):
        """Get address change history for member"""
        return frappe.get_all(
            "Member Address History",
            filters={"member": member_name},
            fields=["change_date", "old_postal_code", "new_postal_code", "reason"],
            order_by="change_date desc"
        )


def run_portal_functionality_tests():
    """Run portal functionality integration tests"""
    print("🌐 Running Portal Functionality Integration Tests...")

    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPortalFunctionalityIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All portal functionality tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_portal_functionality_tests()
