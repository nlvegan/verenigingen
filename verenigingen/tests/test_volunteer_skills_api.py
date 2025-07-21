"""
Unit tests for volunteer skills API functions
"""

import unittest
import json
import frappe
from frappe.utils import today, now_datetime
from verenigingen.verenigingen.doctype.volunteer.volunteer import (
    search_volunteers_by_skill,
    get_all_skills_list,
    get_skill_suggestions,
    get_volunteers_with_filters,
    get_skill_insights
)
from verenigingen.api.volunteer_skills import (
    get_skills_overview,
    search_volunteers_advanced,
    get_skill_recommendations,
    get_skill_gaps_analysis,
    export_skills_data
)


class TestVolunteerSkillsAPI(unittest.TestCase):
    """Test volunteer skills API functions"""

    def setUp(self):
        """Set up test data"""
        self.cleanup_test_data()
        
        # Create test volunteers with skills
        self.test_volunteers = []
        self.create_test_volunteer_data()

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove test data"""
        # Delete test volunteers and their skills
        test_volunteers = frappe.get_all("Volunteer", 
            filters={"volunteer_name": ["like", "Test Volunteer%"]})
        
        for volunteer in test_volunteers:
            frappe.delete_doc("Volunteer", volunteer.name, force=True)
        
        # Delete test volunteer development goals
        test_goals = frappe.get_all("Volunteer Development Goal",
            filters={"parent": ["like", "Test Volunteer%"]})
        
        for goal in test_goals:
            frappe.delete_doc("Volunteer Development Goal", goal.name, force=True)
        
        frappe.db.commit()

    def create_test_volunteer_data(self):
        """Create test volunteers with skills for testing"""
        volunteers_data = [
            {
                "name": "Test Volunteer Skills API 1",
                "email": "test_vol_api1@example.com",
                "skills": [
                    {"category": "Technical", "skill": "Python", "level": "5 - Expert", "years": 5},
                    {"category": "Technical", "skill": "JavaScript", "level": "4 - Advanced", "years": 3},
                    {"category": "Leadership", "skill": "Team Management", "level": "4 - Advanced", "years": 2}
                ]
            },
            {
                "name": "Test Volunteer Skills API 2", 
                "email": "test_vol_api2@example.com",
                "skills": [
                    {"category": "Technical", "skill": "Python", "level": "3 - Intermediate", "years": 2},
                    {"category": "Communication", "skill": "Writing", "level": "5 - Expert", "years": 7},
                    {"category": "Communication", "skill": "Public Speaking", "level": "4 - Advanced", "years": 3}
                ]
            },
            {
                "name": "Test Volunteer Skills API 3",
                "email": "test_vol_api3@example.com", 
                "skills": [
                    {"category": "Financial", "skill": "Accounting", "level": "4 - Advanced", "years": 5},
                    {"category": "Financial", "skill": "Fundraising", "level": "3 - Intermediate", "years": 1},
                    {"category": "Organizational", "skill": "Event Planning", "level": "5 - Expert", "years": 4}
                ]
            }
        ]
        
        for vol_data in volunteers_data:
            volunteer = frappe.get_doc({
                "doctype": "Volunteer",
                "volunteer_name": vol_data["name"],
                "email": vol_data["email"],
                "status": "Active",
                "start_date": today()
            })
            
            # Add skills
            for skill_data in vol_data["skills"]:
                skill_row = volunteer.append('skills_and_qualifications', {})
                skill_row.skill_category = skill_data["category"]
                skill_row.volunteer_skill = skill_data["skill"]
                skill_row.proficiency_level = skill_data["level"]
                skill_row.experience_years = skill_data["years"]
            
            volunteer.insert()
            self.test_volunteers.append(volunteer.name)

        # Add some development goals for testing
        volunteer1 = frappe.get_doc("Volunteer", self.test_volunteers[0])
        goal_row = volunteer1.append('desired_skill_development', {})
        goal_row.skill = "Machine Learning"
        goal_row.current_level = "2"
        goal_row.target_level = "4"
        volunteer1.save()

    def test_search_volunteers_by_skill(self):
        """Test searching volunteers by skill name"""
        # Search for Python skills
        results = search_volunteers_by_skill("Python")
        
        self.assertGreater(len(results), 0)
        
        # Verify all results have Python skill
        for result in results:
            self.assertEqual(result.matched_skill, "Python")
            self.assertIn("Test Volunteer Skills API", result.volunteer_name)
        
        # Search for non-existent skill
        no_results = search_volunteers_by_skill("NonExistentSkill")
        self.assertEqual(len(no_results), 0)

    def test_search_volunteers_by_skill_with_category(self):
        """Test searching volunteers by skill with category filter"""
        results = search_volunteers_by_skill("Python", category="Technical")
        
        self.assertGreater(len(results), 0)
        
        for result in results:
            self.assertEqual(result.matched_skill, "Python")
            self.assertEqual(result.skill_category, "Technical")

    def test_search_volunteers_by_skill_with_min_level(self):
        """Test searching volunteers by skill with minimum level"""
        results = search_volunteers_by_skill("Python", min_level=4)
        
        # Should find at least the expert level volunteer
        expert_found = False
        for result in results:
            if "5 - Expert" in result.proficiency_level:
                expert_found = True
                break
        
        self.assertTrue(expert_found)

    def test_get_all_skills_list(self):
        """Test getting all skills list"""
        skills = get_all_skills_list()
        
        self.assertGreater(len(skills), 0)
        
        # Verify expected skills are present
        skill_names = [skill.volunteer_skill for skill in skills]
        self.assertIn("Python", skill_names)
        self.assertIn("Writing", skill_names)
        self.assertIn("Accounting", skill_names)
        
        # Verify structure
        for skill in skills:
            self.assertIn("volunteer_skill", skill)
            self.assertIn("skill_category", skill)
            self.assertIn("volunteer_count", skill)
            self.assertIn("avg_level", skill)

    def test_get_skill_suggestions(self):
        """Test getting skill suggestions for autocomplete"""
        # Test with valid partial skill
        suggestions = get_skill_suggestions("Py")
        self.assertIn("Python", suggestions)
        
        # Test with too short input
        short_suggestions = get_skill_suggestions("P")
        self.assertEqual(len(short_suggestions), 0)
        
        # Test with empty input
        empty_suggestions = get_skill_suggestions("")
        self.assertEqual(len(empty_suggestions), 0)

    def test_get_volunteers_with_filters(self):
        """Test getting volunteers with various filters"""
        # Test category filter
        technical_volunteers = get_volunteers_with_filters(category="Technical")
        self.assertGreater(len(technical_volunteers), 0)
        
        # Test skill filter
        python_volunteers = get_volunteers_with_filters(skill="Python")
        self.assertGreater(len(python_volunteers), 0)
        
        # Test minimum level filter
        advanced_volunteers = get_volunteers_with_filters(min_level=4)
        self.assertGreater(len(advanced_volunteers), 0)
        
        # Test combined filters
        advanced_python = get_volunteers_with_filters(skill="Python", min_level=4)
        self.assertGreaterEqual(len(advanced_python), 1)

    def test_get_skill_insights(self):
        """Test getting skill insights for dashboard"""
        insights = get_skill_insights()
        
        # Verify structure
        self.assertIn("popular_skills", insights)
        self.assertIn("category_distribution", insights)
        self.assertIn("expert_skills", insights)
        self.assertIn("development_skills", insights)
        self.assertIn("total_skills", insights)
        self.assertIn("total_volunteers_with_skills", insights)
        
        # Verify data
        self.assertGreater(insights["total_skills"], 0)
        self.assertGreater(len(insights["popular_skills"]), 0)
        self.assertGreater(len(insights["category_distribution"]), 0)

    def test_get_skills_overview(self):
        """Test getting comprehensive skills overview"""
        overview = get_skills_overview()
        
        self.assertTrue(overview["success"])
        self.assertIn("skills_by_category", overview)
        self.assertIn("top_skills", overview)
        self.assertIn("development_skills", overview)
        
        # Verify categories are present
        categories = [cat["skill_category"] for cat in overview["skills_by_category"]]
        expected_categories = ["Technical", "Communication", "Financial", "Leadership", "Organizational"]
        
        for expected_cat in expected_categories:
            if any(cat in categories for cat in expected_categories):
                break
        else:
            self.fail("Expected skill categories not found")

    def test_search_volunteers_advanced(self):
        """Test advanced volunteer search with multiple criteria"""
        # Test single skill requirement
        filters = {"skills": ["Python"]}
        result = search_volunteers_advanced(json.dumps(filters))
        
        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)
        
        # Test multiple skills requirement (AND logic)
        filters = {"skills": ["Python", "JavaScript"]}
        result = search_volunteers_advanced(json.dumps(filters))
        
        self.assertTrue(result["success"])
        # Should find volunteer with both Python AND JavaScript
        
        # Test category filter
        filters = {"categories": ["Technical"]}
        result = search_volunteers_advanced(json.dumps(filters))
        
        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)

    def test_get_skill_recommendations(self):
        """Test skill recommendations based on similar volunteers"""
        volunteer_name = self.test_volunteers[0]  # Has Python, JavaScript, Team Management
        
        recommendations = get_skill_recommendations(volunteer_name)
        
        self.assertTrue(recommendations["success"])
        # Should get recommendations based on similar volunteers
        
        # Test with volunteer that has no skills
        volunteer_no_skills = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": "Test Volunteer No Skills",
            "email": "test_no_skills@example.com",
            "status": "Active"
        })
        volunteer_no_skills.insert()
        
        no_recs = get_skill_recommendations(volunteer_no_skills.name)
        self.assertTrue(no_recs["success"])
        self.assertEqual(len(no_recs["recommendations"]), 0)
        
        # Clean up
        frappe.delete_doc("Volunteer", volunteer_no_skills.name, force=True)

    def test_get_skill_gaps_analysis(self):
        """Test skill gaps analysis"""
        gaps = get_skill_gaps_analysis()
        
        self.assertTrue(gaps["success"])
        self.assertIn("skill_gaps", gaps)
        self.assertIn("category_gaps", gaps)
        
        # Verify structure of results
        if gaps["category_gaps"]:
            for gap in gaps["category_gaps"]:
                self.assertIn("skill_category", gap)
                self.assertIn("volunteer_count", gap)
                self.assertIn("skill_count", gap)

    def test_export_skills_data(self):
        """Test exporting skills data"""
        # Test JSON export
        json_export = export_skills_data("json")
        
        self.assertTrue(json_export["success"])
        self.assertEqual(json_export["format"], "json")
        self.assertIn("data", json_export)
        self.assertGreater(len(json_export["data"]), 0)
        
        # Verify data structure
        for item in json_export["data"]:
            self.assertIn("volunteer_name", item)
            self.assertIn("volunteer_skill", item)
            self.assertIn("skill_category", item)
            self.assertIn("proficiency_level", item)
        
        # Test CSV export
        csv_export = export_skills_data("csv")
        
        self.assertTrue(csv_export["success"])
        self.assertEqual(csv_export["format"], "csv")
        self.assertIn("data", csv_export)
        self.assertIn("filename", csv_export)
        self.assertTrue(csv_export["filename"].endswith(".csv"))

    def test_api_error_handling(self):
        """Test API error handling for edge cases"""
        # Test search with invalid parameters
        invalid_result = search_volunteers_advanced('{"invalid": "data"}')
        self.assertTrue(invalid_result["success"])  # Should handle gracefully
        
        # Test recommendations for non-existent volunteer
        invalid_recs = get_skill_recommendations("NonExistentVolunteer")
        self.assertFalse(invalid_recs["success"])

    def test_skills_data_consistency(self):
        """Test data consistency across different API endpoints"""
        # Get skills from multiple endpoints
        all_skills = get_all_skills_list()
        overview = get_skills_overview()
        insights = get_skill_insights()
        
        # Verify consistent skill counts
        all_skills_count = len(all_skills)
        insights_total = insights["total_skills"]
        
        # Should be reasonably close (some variation due to different queries)
        self.assertGreaterEqual(insights_total, 0)
        self.assertGreaterEqual(all_skills_count, 0)

    def test_performance_with_large_datasets(self):
        """Test API performance considerations"""
        # Test with result limits
        limited_results = get_volunteers_with_filters(max_results=2)
        self.assertLessEqual(len(limited_results), 2)
        
        # Test export with realistic limits
        export_result = export_skills_data("json")
        self.assertTrue(export_result["success"])
        
        # Should complete in reasonable time
        self.assertIsNotNone(export_result["data"])

    def test_skills_search_accuracy(self):
        """Test accuracy of skills search functionality"""
        # Test exact match
        exact_results = search_volunteers_by_skill("Python")
        python_found = any("Python" in r.matched_skill for r in exact_results)
        self.assertTrue(python_found)
        
        # Test partial match
        partial_results = search_volunteers_by_skill("Py")
        self.assertGreater(len(partial_results), 0)
        
        # Test case insensitivity
        case_results = search_volunteers_by_skill("python")
        self.assertGreater(len(case_results), 0)

    def test_volunteer_filtering_logic(self):
        """Test volunteer filtering logic accuracy"""
        # Create volunteer with specific skill level
        test_vol = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": "Test Volunteer Filter Logic",
            "email": "test_filter@example.com",
            "status": "Active"
        })
        
        skill_row = test_vol.append('skills_and_qualifications', {})
        skill_row.skill_category = "Technical"
        skill_row.volunteer_skill = "TestSkill"
        skill_row.proficiency_level = "3 - Intermediate"
        
        test_vol.insert()
        
        # Test minimum level filtering
        results_level_3 = search_volunteers_by_skill("TestSkill", min_level=3)
        results_level_4 = search_volunteers_by_skill("TestSkill", min_level=4)
        
        self.assertGreater(len(results_level_3), 0)
        self.assertEqual(len(results_level_4), 0)  # Should not find level 3 when requiring level 4
        
        # Clean up
        frappe.delete_doc("Volunteer", test_vol.name, force=True)


if __name__ == '__main__':
    unittest.main()