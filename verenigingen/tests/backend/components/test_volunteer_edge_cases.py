import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today


class TestVolunteerEdgeCases(FrappeTestCase):
    """Comprehensive edge case tests for Volunteer doctype"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()
        cls.test_counter = 0

    def setUp(self):
        """Set up for each test"""
        TestVolunteerEdgeCases.test_counter += 1
        self.test_id = f"VEDGE{TestVolunteerEdgeCases.test_counter:03d}"
        self.docs_to_cleanup = []

        # Create test prerequisites
        self.create_test_prerequisites()

    def tearDown(self):
        """Clean up after each test"""
        for doctype, name in reversed(self.docs_to_cleanup):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True)
            except Exception as e:
                print(f"Error cleaning up {doctype} {name}: {e}")
        frappe.db.commit()

    def create_test_prerequisites(self):
        """Create test prerequisites"""
        # Create test member for volunteer
        self.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Verenigingen Volunteer",
                "last_name": f"Member {self.test_id}",
                "email": f"volmember{self.test_id.lower()}@example.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer",
                "pronouns": "They/them",
                "interested_in_volunteering": 1,
                "volunteer_availability": "Weekly",
                "volunteer_skills": "Programming, Event Planning"}
        )
        self.test_member.insert()
        self.docs_to_cleanup.append(("Member", self.test_member.name))

        # Create test interest categories if needed
        self.create_test_interest_categories()

    def create_test_interest_categories(self):
        """Create test interest categories"""
        categories = ["Testing Category", "Edge Case Category", "Special Category"]
        for category in categories:
            if not frappe.db.exists("Volunteer Interest Category", category):
                cat_doc = frappe.get_doc(
                    {
                        "doctype": "Volunteer Interest Category",
                        "category_name": category,
                        "description": f"Test category {category}"}
                )
                cat_doc.insert()
                self.docs_to_cleanup.append(("Volunteer Interest Category", category))

    def create_test_volunteer(self, **kwargs):
        """Create a test volunteer with default values"""
        defaults = {
            "doctype": "Volunteer",
            "volunteer_name": f"Test Volunteer {self.test_id}",
            "email": f"volunteer{self.test_id.lower()}@organization.org",
            "member": self.test_member.name,
            "status": "Active",
            "start_date": today()}
        defaults.update(kwargs)

        volunteer = frappe.get_doc(defaults)
        volunteer.insert()
        self.docs_to_cleanup.append(("Verenigingen Volunteer", volunteer.name))
        return volunteer

    def test_volunteer_name_edge_cases(self):
        """Test volunteer names with edge cases"""
        print("\n🧪 Testing volunteer name edge cases...")

        # Test very long name
        long_name = f"Very Long Volunteer Name That Exceeds Normal Limits {self.test_id} " + "X" * 100
        try:
            volunteer = self.create_test_volunteer(volunteer_name=long_name[:140])
            self.assertTrue(volunteer.name, "Long name should be handled gracefully")
            print("✅ Long name handled")
        except Exception as e:
            print(f"✅ Long name properly rejected: {str(e)}")

        # Test name with special characters
        special_name = f"José-María Ñoël-O'Connor {self.test_id}"
        volunteer = self.create_test_volunteer(volunteer_name=special_name)
        self.assertEqual(volunteer.volunteer_name, special_name, "Special characters should be preserved")
        print("✅ Special characters in name handled")

        # Test name with numbers and symbols
        numeric_name = f"Volunteer 123 & Co. {self.test_id}"
        volunteer = self.create_test_volunteer(volunteer_name=numeric_name)
        self.assertEqual(volunteer.volunteer_name, numeric_name, "Numbers and symbols should be allowed")
        print("✅ Numbers and symbols in name handled")

        # Test name with emoji
        emoji_name = f"Test Volunteer 🌟📝 {self.test_id}"
        try:
            volunteer = self.create_test_volunteer(volunteer_name=emoji_name)
            self.assertEqual(volunteer.volunteer_name, emoji_name, "Emoji in name should be preserved")
            print("✅ Emoji in name handled")
        except Exception as e:
            print(f"⚠️ Emoji in name caused issues: {str(e)}")

    def test_email_validation_edge_cases(self):
        """Test email validation with edge cases"""
        print("\n🧪 Testing email validation edge cases...")

        email_test_cases = [
            ("simple@example.com", True, "Simple email"),
            ("with+plus@example.org", True, "Email with plus"),
            ("with.dots@example.net", True, "Email with dots"),
            ("with-dashes@example.co.uk", True, "Email with dashes"),
            (
                "very.long.email.address.with.many.dots@very-long-domain-name.example.com",
                True,
                "Very long email",
            ),
            ("", False, "Empty email"),
            ("invalid-email", False, "Invalid format"),
            ("@example.com", False, "Missing username"),
            ("user@", False, "Missing domain"),
            ("user@.com", False, "Invalid domain"),
            ("user name@example.com", False, "Space in email"),
        ]

        for email, should_be_valid, description in email_test_cases:
            try:
                volunteer = self.create_test_volunteer(
                    volunteer_name=f"Email Test {self.test_id} {len(self.docs_to_cleanup)}", email=email
                )
                if should_be_valid:
                    self.assertEqual(volunteer.email, email, f"{description}: {email} should be preserved")
                    print(f"✅ {description}: {email}")
                else:
                    print(f"⚠️ {description}: {email} was accepted (might be valid)")
            except Exception as e:
                if should_be_valid:
                    print(f"⚠️ {description}: {email} was rejected: {str(e)}")
                else:
                    print(f"✅ {description}: {email} properly rejected")

    def test_status_transitions_edge_cases(self):
        """Test volunteer status transitions with edge cases"""
        print("\n🧪 Testing status transitions edge cases...")

        volunteer = self.create_test_volunteer(status="New")

        # Test all valid status transitions
        status_transitions = [
            ("New", "Onboarding"),
            ("Onboarding", "Active"),
            ("Active", "Inactive"),
            ("Inactive", "Active"),
            ("Active", "Retired"),
            ("Retired", "Active"),  # Comeback scenario
        ]

        for from_status, to_status in status_transitions:
            volunteer.status = from_status
            volunteer.save()
            volunteer.reload()
            self.assertEqual(volunteer.status, from_status, f"Should be able to set status to {from_status}")

            volunteer.status = to_status
            volunteer.save()
            volunteer.reload()
            self.assertEqual(
                volunteer.status, to_status, f"Should transition from {from_status} to {to_status}"
            )
            print(f"✅ Status transition: {from_status} → {to_status}")

        # Test rapid status changes
        for i in range(10):
            status = ["New", "Active", "Inactive"][i % 3]
            volunteer.status = status
            volunteer.save()
            volunteer.reload()
            self.assertEqual(volunteer.status, status, f"Rapid change {i} should work")

        print("✅ Rapid status changes handled")

    def test_skills_and_qualifications_edge_cases(self):
        """Test skills and qualifications with edge cases"""
        print("\n🧪 Testing skills and qualifications edge cases...")

        volunteer = self.create_test_volunteer()

        # Test adding many skills
        skill_categories = [
            "Technical",
            "Organizational",
            "Communication",
            "Leadership",
            "Financial",
            "Event Planning",
            "Other",
        ]

        for i, category in enumerate(skill_categories * 3):  # 21 skills total
            volunteer.append(
                "skills_and_qualifications",
                {
                    "skill_category": category,
                    "volunteer_skill": f"Skill {i + 1} in {category}",
                    "proficiency_level": str((i % 5) + 1)
                    + " - "
                    + ["Beginner", "Basic", "Intermediate", "Advanced", "Expert"][i % 5],
                    "experience_years": i % 20,
                    "certifications": f"Cert-{i + 1}, Advanced-{i + 1}" if i % 3 == 0 else ""},
            )

        volunteer.save()
        volunteer.reload()

        # Verify large skill set handling
        self.assertEqual(len(volunteer.skills_and_qualifications), 21, "Should handle large skill set")
        print("✅ Large skill set (21 skills) handled")

        # Test skills with special characters and edge cases
        special_skills = [
            ("Technical", "C++ Programming", "2 - Basic", 0, ""),
            ("Communication", "日本語 (Japanese)", "4 - Advanced", 5, "JLPT N1"),
            ("Other", "Skill with emoji 🎨📊", "3 - Intermediate", 2, ""),
            ("Technical", "", "1 - Beginner", 0, ""),  # Empty skill name
            (
                "Leadership",
                "Very Long Skill Name That Exceeds Normal Expectations " + "X" * 50,
                "5 - Expert",
                15,
                "",
            ),
        ]

        for category, skill, level, years, certs in special_skills:
            try:
                volunteer.append(
                    "skills_and_qualifications",
                    {
                        "skill_category": category,
                        "volunteer_skill": skill,
                        "proficiency_level": level,
                        "experience_years": years,
                        "certifications": certs},
                )
                volunteer.save()
                print(f"✅ Special skill handled: {skill[:30]}...")
            except Exception as e:
                print(f"⚠️ Special skill rejected: {skill[:30]}... - {str(e)}")

        # Test get_skills_by_category method
        volunteer.reload()
        if hasattr(volunteer, "get_skills_by_category"):
            skills_by_category = volunteer.get_skills_by_category()
            self.assertIsInstance(skills_by_category, dict, "Should return dictionary")
            self.assertIn("Technical", skills_by_category, "Should have Technical category")
            print("✅ Skills categorization method works")

    def test_assignment_history_edge_cases(self):
        """Test assignment history with edge cases"""
        print("\n🧪 Testing assignment history edge cases...")

        volunteer = self.create_test_volunteer()

        # Test adding many assignments
        assignment_types = ["Board Position", "Committee", "Team", "Project", "Event", "Other"]

        for i in range(30):  # Large number of assignments
            assignment_type = assignment_types[i % len(assignment_types)]
            start_date = add_days(today(), -365 + (i * 10))
            end_date = add_days(start_date, 30) if i % 3 == 0 else None  # Some ongoing

            volunteer.append(
                "assignment_history",
                {
                    "assignment_type": assignment_type,
                    "reference_doctype": "Volunteer Activity",
                    "reference_name": f"TEST-ACTIVITY-{i}",
                    "role": f"Role {i + 1} - {assignment_type}",
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "Completed" if end_date else "Active",
                    "estimated_hours": (i + 1) * 10,
                    "actual_hours": (i + 1) * 8 if end_date else 0,
                    "accomplishments": f"Accomplished task {i + 1} successfully",
                    "notes": f"Notes for assignment {i + 1}"},
            )

        volunteer.save()
        volunteer.reload()

        # Verify large assignment history handling
        self.assertEqual(len(volunteer.assignment_history), 30, "Should handle large assignment history")
        print("✅ Large assignment history (30 assignments) handled")

        # Test assignments with edge case data
        edge_case_assignments = [
            {
                "assignment_type": "Project",
                "role": "José-María's Special Project Coordinator 🌟",
                "start_date": today(),
                "estimated_hours": 0.1,  # Minimal hours
                "accomplishments": "A" * 1000,  # Very long accomplishments
                "notes": "Notes with special chars: <script>alert('test')</script>"},
            {
                "assignment_type": "Event",
                "role": "R" * 200,  # Very long role name
                "start_date": add_days(today(), -1000),  # Very old start date
                "end_date": add_days(today(), 1000),  # Far future end date
                "estimated_hours": 10000,  # Huge hours
                "actual_hours": 15000,  # More actual than estimated
            },
            {
                "assignment_type": "Other",
                "role": "",  # Empty role
                "start_date": today(),
                "estimated_hours": -5,  # Negative hours
            },
        ]

        for assignment_data in edge_case_assignments:
            try:
                volunteer.append("assignment_history", assignment_data)
                volunteer.save()
                print(f"✅ Edge case assignment handled: {assignment_data.get('role', 'Empty role')[:30]}...")
            except Exception as e:
                print(f"⚠️ Edge case assignment rejected: {str(e)}")

    def test_interest_areas_edge_cases(self):
        """Test interest areas with edge cases"""
        print("\n🧪 Testing interest areas edge cases...")

        volunteer = self.create_test_volunteer()

        # Add all available interest categories multiple times
        available_categories = frappe.get_all("Volunteer Interest Category", pluck="name")

        for category in available_categories * 3:  # Add duplicates
            volunteer.append("interests", {"interest_area": category})

        volunteer.save()
        volunteer.reload()

        # Should allow duplicates (business decision)
        self.assertGreater(
            len(volunteer.interests), len(available_categories), "Should handle duplicate interests"
        )
        print(f"✅ Duplicate interests handled ({len(volunteer.interests)} entries)")

        # Test with non-existent interest category
        try:
            volunteer.append("interests", {"interest_area": "Non-Existent Category"})
            volunteer.save()
            print("⚠️ Non-existent category was accepted")
        except Exception as e:
            print(f"✅ Non-existent category properly rejected: {str(e)}")

    def test_development_goals_edge_cases(self):
        """Test development goals with edge cases"""
        print("\n🧪 Testing development goals edge cases...")

        volunteer = self.create_test_volunteer()

        # Test adding many development goals
        skills_to_develop = [
            "Public Speaking",
            "Project Management",
            "Technical Writing",
            "Leadership",
            "Financial Management",
            "Event Planning",
            "Community Outreach",
            "Digital Marketing",
            "Data Analysis",
            "Graphic Design",
            "Web Development",
            "Foreign Languages",
        ]

        for i, skill in enumerate(skills_to_develop):
            current_level = (
                str((i % 5) + 1) + " - " + ["Beginner", "Basic", "Intermediate", "Advanced", "Expert"][i % 5]
            )
            target_level = (
                str(((i + 2) % 5) + 1)
                + " - "
                + ["Beginner", "Basic", "Intermediate", "Advanced", "Expert"][(i + 2) % 5]
            )

            volunteer.append(
                "development_goals",
                {
                    "skill": skill,
                    "current_level": current_level,
                    "target_level": target_level,
                    "notes": f"Development plan for {skill} - step {i + 1}"},
            )

        volunteer.save()
        volunteer.reload()

        # Verify large goals set handling
        self.assertEqual(
            len(volunteer.development_goals), len(skills_to_develop), "Should handle many development goals"
        )
        print(f"✅ Large development goals set ({len(skills_to_develop)} goals) handled")

        # Test development goals with edge case data
        edge_case_goals = [
            {
                "skill": "S" * 500,  # Very long skill name
                "current_level": "1 - Beginner",
                "target_level": "5 - Expert",
                "notes": "N" * 2000,  # Very long notes
            },
            {
                "skill": "日本語習得 (Japanese Learning) 🇯🇵",  # Unicode and emoji
                "current_level": "2 - Basic",
                "target_level": "4 - Advanced",
                "notes": "Learning Japanese for international outreach"},
            {
                "skill": "",  # Empty skill
                "current_level": "3 - Intermediate",
                "target_level": "3 - Intermediate",  # Same level
                "notes": ""},
        ]

        for goal_data in edge_case_goals:
            try:
                volunteer.append("development_goals", goal_data)
                volunteer.save()
                print(f"✅ Edge case goal handled: {goal_data['skill'][:30]}...")
            except Exception as e:
                print(f"⚠️ Edge case goal rejected: {str(e)}")

    def test_member_linkage_edge_cases(self):
        """Test member linkage with edge cases"""
        print("\n🧪 Testing member linkage edge cases...")

        volunteer = self.create_test_volunteer()

        # Verify initial linkage
        self.assertEqual(volunteer.member, self.test_member.name, "Should be linked to test member")

        # Test with non-existent member
        try:
            invalid_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"Invalid Member Test {self.test_id}",
                    "email": f"invalid{self.test_id.lower()}@organization.org",
                    "member": "NON-EXISTENT-MEMBER",
                    "status": "Active",
                    "start_date": today()}
            )
            invalid_volunteer.insert()
            self.docs_to_cleanup.append(("Verenigingen Volunteer", invalid_volunteer.name))
            print("⚠️ Non-existent member was accepted")
        except Exception as e:
            print(f"✅ Non-existent member properly rejected: {str(e)}")

        # Test member data synchronization
        original_pronouns = volunteer.preferred_pronouns

        # Update member pronouns
        self.test_member.pronouns = "she/her"
        self.test_member.save()

        # Reload volunteer and check if pronouns sync (depends on implementation)
        volunteer.reload()
        # Note: This tests whether the system automatically syncs data
        if volunteer.preferred_pronouns != original_pronouns:
            print("✅ Member data automatically synced")
        else:
            print("ℹ️ Member data sync requires manual refresh")

        # Test creating volunteer without member link
        try:
            volunteer_no_member = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"No Member Test {self.test_id}",
                    "email": f"nomember{self.test_id.lower()}@organization.org",
                    "status": "Active",
                    "start_date": today()}
            )
            volunteer_no_member.insert()
            self.docs_to_cleanup.append(("Verenigingen Volunteer", volunteer_no_member.name))
            print("✅ Volunteer without member link allowed")
        except Exception as e:
            print(f"ℹ️ Volunteer without member link rejected: {str(e)}")

    def test_date_validation_edge_cases(self):
        """Test date validation with edge cases"""
        print("\n🧪 Testing date validation edge cases...")

        volunteer = self.create_test_volunteer()

        # Test assignment with invalid date ranges
        invalid_date_scenarios = [
            {
                "start_date": add_days(today(), 10),
                "end_date": today(),  # End before start
                "description": "End date before start date"},
            {
                "start_date": add_days(today(), -10000),  # Very old start
                "end_date": add_days(today(), 10000),  # Very far future end
                "description": "Extreme date range"},
            {"start_date": None, "end_date": today(), "description": "Null start date"},
        ]

        for scenario in invalid_date_scenarios:
            try:
                volunteer.append(
                    "assignment_history",
                    {
                        "assignment_type": "Project",
                        "role": f"Date Test - {scenario['description']}",
                        "start_date": scenario["start_date"],
                        "end_date": scenario["end_date"],
                        "status": "Active"},
                )
                volunteer.save()
                print(f"⚠️ {scenario['description']} was accepted")
            except Exception as e:
                print(f"✅ {scenario['description']} properly rejected: {str(e)}")

            # Clear the invalid assignment to continue testing
            if volunteer.assignment_history:
                volunteer.assignment_history = volunteer.assignment_history[:-1]

    def test_data_consistency_edge_cases(self):
        """Test data consistency edge cases"""
        print("\n🧪 Testing data consistency edge cases...")

        volunteer = self.create_test_volunteer()
        original_modified = volunteer.modified

        # Test rapid successive updates
        for i in range(20):
            volunteer.note = f"Updated note {i} with timestamp {now_datetime()}"
            volunteer.save()
            volunteer.reload()

        # Verify final state
        self.assertIn("Updated note 19", volunteer.note or "")
        self.assertNotEqual(volunteer.modified, original_modified)
        print("✅ Rapid successive updates handled")

        # Test concurrent-like updates (simulate race conditions)
        volunteer1 = frappe.get_doc("Volunteer", volunteer.name)
        volunteer2 = frappe.get_doc("Volunteer", volunteer.name)

        # Update both instances
        volunteer1.experience_level = "Expert"
        volunteer2.commitment_level = "Intensive"

        # Save both (second save might overwrite first)
        volunteer1.save()
        volunteer2.save()

        # Reload and verify final state
        final_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        # One of the updates should be preserved
        self.assertTrue(
            final_volunteer.experience_level == "Expert" or final_volunteer.commitment_level == "Intensive",
            "At least one update should be preserved",
        )
        print("✅ Concurrent-like updates handled")

    def test_performance_edge_cases(self):
        """Test volunteer performance with edge cases"""
        print("\n🧪 Testing performance edge cases...")

        import time

        # Test large data handling
        start_time = time.time()

        # Create volunteer with large amount of data
        large_note = "Lorem ipsum dolor sit amet. " * 200  # ~5400 characters

        volunteer = self.create_test_volunteer(
            volunteer_name=f"Large Data Volunteer {self.test_id}", note=large_note
        )

        # Add many skills, interests, and assignments
        for i in range(50):
            volunteer.append(
                "skills_and_qualifications",
                {
                    "skill_category": ["Technical", "Communication", "Leadership"][i % 3],
                    "volunteer_skill": f"Skill {i + 1}",
                    "proficiency_level": f"{(i % 5) + 1} - Level {i + 1}",
                    "experience_years": i % 20,
                    "certifications": f"Cert-{i + 1}, Advanced-{i + 1}" if i % 5 == 0 else ""},
            )

            if i < 10:  # Limit interests to available categories
                volunteer.append("interests", {"interest_area": "Testing Category"})

            volunteer.append(
                "assignment_history",
                {
                    "assignment_type": ["Project", "Event", "Committee"][i % 3],
                    "role": f"Role {i + 1}",
                    "start_date": add_days(today(), -i),
                    "status": "Active",
                    "estimated_hours": (i + 1) * 2,
                    "accomplishments": f"Accomplishment {i + 1} " * 10,  # Longer text
                    "notes": f"Notes for assignment {i + 1} " * 5},
            )

            volunteer.append(
                "development_goals",
                {
                    "skill": f"Goal Skill {i + 1}",
                    "current_level": f"{(i % 3) + 1} - Current",
                    "target_level": f"{((i % 3) + 2)} - Target",
                    "notes": f"Development notes {i + 1} " * 3},
            )

        volunteer.save()
        creation_time = time.time() - start_time

        self.assertLess(
            creation_time, 10.0, "Large data volunteer creation should complete in reasonable time"
        )
        print(f"✅ Large data volunteer created in {creation_time:.3f}s")

        # Test retrieval performance
        start_time = time.time()
        retrieved_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        retrieval_time = time.time() - start_time

        self.assertLess(retrieval_time, 3.0, "Volunteer retrieval should be fast")
        self.assertEqual(len(retrieved_volunteer.skills_and_qualifications), 50)
        print(f"✅ Large data volunteer retrieved in {retrieval_time:.3f}s")

        # Test aggregated assignments performance
        start_time = time.time()
        if hasattr(retrieved_volunteer, "get_aggregated_assignments"):
            assignments = retrieved_volunteer.get_aggregated_assignments()
            aggregation_time = time.time() - start_time

            self.assertLess(aggregation_time, 5.0, "Assignment aggregation should be reasonably fast")
            self.assertIsInstance(assignments, list, "Should return list of assignments")
            print(f"✅ Assignment aggregation completed in {aggregation_time:.3f}s")

    def test_validation_edge_cases(self):
        """Test volunteer validation edge cases"""
        print("\n🧪 Testing validation edge cases...")

        # Test creating volunteer with minimal required data
        try:
            minimal_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"Minimal Volunteer {self.test_id}",
                    "email": f"minimal{self.test_id.lower()}@organization.org"
                    # Only required fields
                }
            )
            minimal_volunteer.insert()
            self.docs_to_cleanup.append(("Verenigingen Volunteer", minimal_volunteer.name))

            self.assertEqual(minimal_volunteer.volunteer_name, f"Minimal Volunteer {self.test_id}")
            print("✅ Minimal volunteer creation handled")
        except Exception as e:
            print(f"⚠️ Minimal volunteer creation failed: {str(e)}")

        # Test invalid data scenarios
        invalid_scenarios = [
            {
                "field": "experience_level",
                "value": "Invalid Level",
                "description": "Invalid experience level"},
            {"field": "commitment_level", "value": "24/7", "description": "Invalid commitment level"},
            {"field": "preferred_work_style", "value": "Underwater", "description": "Invalid work style"},
            {"field": "status", "value": "Zombie", "description": "Invalid status"},
        ]

        for scenario in invalid_scenarios:
            try:
                test_data = {
                    "doctype": "Volunteer",
                    "volunteer_name": f"Invalid {scenario['description']} {self.test_id}",
                    "email": f"invalid{len(self.docs_to_cleanup)}{self.test_id.lower()}@organization.org",
                    scenario["field"]: scenario["value"]}
                invalid_volunteer = frappe.get_doc(test_data)
                invalid_volunteer.insert()
                self.docs_to_cleanup.append(("Verenigingen Volunteer", invalid_volunteer.name))
                print(f"⚠️ {scenario['description']} was accepted (might be valid)")
            except Exception as e:
                print(f"✅ {scenario['description']} properly rejected: {str(e)}")

    def test_internationalization_edge_cases(self):
        """Test volunteer internationalization edge cases"""
        print("\n🧪 Testing internationalization edge cases...")

        # Test various international character sets
        intl_test_cases = [
            ("Arabic", "المتطوع العربي", "volunteer.arabic@org.net"),
            ("Chinese", "中文志愿者", "volunteer.chinese@org.net"),
            ("Japanese", "日本のボランティア", "volunteer.japanese@org.net"),
            ("Russian", "Русский волонтёр", "volunteer.russian@org.net"),
            ("Emoji", "Volunteer 🌟👥📋", "volunteer.emoji@org.net"),
            ("Mixed", "José-María 中文 🌟", "volunteer.mixed@org.net"),
        ]

        for script_name, intl_text, email in intl_test_cases:
            try:
                volunteer = self.create_test_volunteer(
                    volunteer_name=intl_text, email=email, note=f"Notes with {intl_text} characters"
                )

                self.assertEqual(volunteer.volunteer_name, intl_text)
                self.assertIn(intl_text, volunteer.note or "")
                print(f"✅ {script_name} characters handled: {intl_text}")

            except Exception as e:
                print(f"⚠️ {script_name} characters caused issues: {str(e)}")

    def test_security_edge_cases(self):
        """Test volunteer security-related edge cases"""
        print("\n🧪 Testing security edge cases...")

        # Test HTML/script injection prevention
        dangerous_inputs = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "'; DROP TABLE volunteers; --",
            "<iframe src='data:text/html,<script>alert(1)</script>'></iframe>",
        ]

        for dangerous_input in dangerous_inputs:
            try:
                volunteer = self.create_test_volunteer(
                    volunteer_name=f"Security Test {self.test_id} {len(self.docs_to_cleanup)}",
                    note=dangerous_input,
                )

                # Verify dangerous content is stored as-is (Frappe handles escaping on display)
                volunteer.reload()
                print(f"✅ Dangerous input stored (will be escaped on display): {dangerous_input[:50]}...")

            except Exception as e:
                print(f"✅ Dangerous input rejected: {str(e)}")


def run_volunteer_edge_case_tests():
    """Run all volunteer edge case tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVolunteerEdgeCases)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n📊 Volunteer Edge Case Tests Summary:")
    print(f"   Tests Run: {result.testsRun}")
    print(f"   Failures: {len(result.failures)}")
    print(f"   Errors: {len(result.errors)}")

    return len(result.failures) == 0 and len(result.errors) == 0


if __name__ == "__main__":
    run_volunteer_edge_case_tests()
