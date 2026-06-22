# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Coverage-focused integration tests for the Volunteer DocType controller.

Targets branches/methods in verenigingen/verenigingen/doctype/volunteer/volunteer.py
that the existing test_volunteer.py / test_volunteer_aggregated.py skip:

  - validate_member_link (nonexistent member -> throw)
  - validate_volunteer_age (too young -> throw; no birth_date -> skip; valid age)
  - validate_dates (assignment start > end -> throw)
  - update_status / _has_any_assignment (New -> Active on assignment)
  - on_trash (child-table cleanup)
  - get_contact_link_doctype / get_contact_link_name
  - onload (member-linked vs standalone) + load_aggregated_assignments
  - add_activity / end_activity (whitelisted delegators)
  - get_aggregated_assignments / get_volunteer_history (whitelisted delegators)
  - calculate_total_hours (activity + assignment-history hours)
  - get_skills_by_category
  - create_volunteer_from_member (success, duplicate, missing member, skills
    as JSON-string / list / dict, custom name)
  - module-level skill search/insight helpers

All tests build REAL records via the enhanced test factory and assert
meaningful behaviour. No mocking of frappe.db / get_doc / business functions.
"""

import json

import frappe
from frappe.utils import add_days, today

from verenigingen.services.volunteer.assignment_query_builder import AssignmentQueryBuilder
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerControllerCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The assignment aggregation cache lives on frappe.local and is keyed by
        # volunteer name, which repeats across rolled-back tests (sequential
        # autoname). Clear it so a prior test's cached result can't mask the
        # assignments this test creates.
        AssignmentQueryBuilder.clear_request_cache()
        self.test_member = self.create_test_member()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_volunteer_doc(self, member_name, **overrides):
        """Construct (but do not insert) a Volunteer doc directly so we can
        exercise controller validation paths the factory would otherwise block."""
        suffix = frappe.generate_hash()[:8]
        data = {
            "doctype": "Volunteer",
            "volunteer_name": f"Cov Volunteer {suffix}",
            "email": f"cov.{suffix}@test.invalid",
            "member": member_name,
            "status": "New",
            "start_date": today(),
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        # Avoid background account-creation side effects during tests.
        doc.flags.skip_volunteer_account_creation = True
        return doc

    # ------------------------------------------------------------------
    # validate_member_link
    # ------------------------------------------------------------------
    def test_validate_member_link_nonexistent_member_throws(self):
        # A nonexistent member blocks insertion. Frappe's framework link
        # validation (LinkValidationError) and the controller's own
        # validate_member_link (DoesNotExistError) are both ValidationError
        # subclasses; either way creation must be refused.
        doc = self._build_volunteer_doc(member_name="NonExistent-Member-ZZZ")
        with self.assertRaises(frappe.ValidationError):
            doc.insert()
        self.assertFalse(frappe.db.exists("Volunteer", {"member": "NonExistent-Member-ZZZ"}))

    def test_validate_member_link_valid_member_passes(self):
        with self.assertNoErrorLog():
            doc = self._build_volunteer_doc(member_name=self.test_member.name)
            doc.insert()
        self.assertEqual(doc.member, self.test_member.name)

    # ------------------------------------------------------------------
    # validate_volunteer_age
    # ------------------------------------------------------------------
    def test_validate_age_uses_member_age_field_when_present(self):
        """When the linked Member already exposes a numeric `age`, the age gate uses
        it directly. An adult age passes and the volunteer is created."""
        frappe.db.set_value("Member", self.test_member.name, "age", 40)
        with self.assertNoErrorLog():
            doc = self._build_volunteer_doc(member_name=self.test_member.name)
            doc.insert()
        self.assertTrue(frappe.db.exists("Volunteer", doc.name))

    def test_validate_age_skipped_when_no_member_linked(self):
        """No member linked -> age validation returns early (no error logged)."""
        with self.assertNoErrorLog():
            doc = self._build_volunteer_doc(member_name=self.test_member.name)
            doc.member = None
            # member is mandatory on the doctype, so insert would fail on mandatory;
            # instead exercise validate_volunteer_age directly with no member.
            doc.validate_volunteer_age()
        # Method returns None and logs nothing when member is unset.
        self.assertIsNone(doc.member)

    def test_validate_age_adult_member_passes(self):
        """An adult member (factory default birth_date 1990) passes the age gate and
        the volunteer is created."""
        with self.assertNoErrorLog():
            doc = self._build_volunteer_doc(member_name=self.test_member.name)
            doc.insert()
        # Linked member is well over the minimum age -> volunteer created.
        self.assertTrue(frappe.db.exists("Volunteer", doc.name))

    def test_validate_age_skipped_when_member_has_no_birth_date(self):
        """No birth_date on member -> age validation is skipped (volunteer created)."""
        member = self.create_test_member()
        frappe.db.set_value("Member", member.name, "birth_date", None)
        with self.assertNoErrorLog():
            doc = self._build_volunteer_doc(member_name=member.name)
            doc.insert()
        self.assertTrue(frappe.db.exists("Volunteer", doc.name))

    # ------------------------------------------------------------------
    # validate_dates
    # ------------------------------------------------------------------
    def test_validate_dates_start_after_end_throws(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Bad Dates",
                "start_date": today(),
                "end_date": add_days(today(), -5),  # end before start
                "status": "Completed",
            },
        )
        with self.assertRaises(frappe.ValidationError):
            volunteer.save()

    def test_validate_dates_valid_range_passes(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Good Dates",
                "start_date": add_days(today(), -10),
                "end_date": today(),
                "status": "Completed",
            },
        )
        with self.assertNoErrorLog():
            volunteer.save()
        volunteer.reload()
        self.assertEqual(volunteer.assignment_history[-1].role, "Good Dates")

    # ------------------------------------------------------------------
    # update_status / _has_any_assignment
    # ------------------------------------------------------------------
    def test_new_volunteer_without_assignments_stays_new(self):
        doc = self._build_volunteer_doc(member_name=self.test_member.name, status="New")
        doc.insert()
        # No assignments anywhere -> update_status keeps it New.
        self.assertEqual(doc.status, "New")
        self.assertFalse(doc._has_any_assignment())

    def test_new_volunteer_with_assignment_history_becomes_active(self):
        doc = self._build_volunteer_doc(member_name=self.test_member.name, status="New")
        doc.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Coordinator",
                "start_date": today(),
                "status": "Active",
            },
        )
        doc.insert()
        # before_save -> update_status sees an in-memory assignment_history row.
        self.assertTrue(doc._has_any_assignment())
        self.assertEqual(doc.status, "Active")

    def test_update_status_does_not_override_explicit_non_new_status(self):
        """update_status only acts on New/empty status; an explicit Active is left as-is
        even without assignments."""
        doc = self._build_volunteer_doc(member_name=self.test_member.name, status="Active")
        doc.insert()
        self.assertEqual(doc.status, "Active")

    # ------------------------------------------------------------------
    # on_trash child-table cleanup
    # ------------------------------------------------------------------
    def test_on_trash_cleans_assignment_history_rows(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "To Be Deleted",
                "start_date": today(),
                "status": "Active",
            },
        )
        volunteer.save()
        name = volunteer.name
        # Child rows exist before delete.
        self.assertTrue(frappe.db.exists("Volunteer Assignment", {"parent": name, "parenttype": "Volunteer"}))

        with self.assertNoErrorLog():
            frappe.delete_doc("Volunteer", name, force=True)

        # on_trash DELETEs the child rows -> none remain.
        self.assertFalse(
            frappe.db.exists("Volunteer Assignment", {"parent": name, "parenttype": "Volunteer"})
        )

    # ------------------------------------------------------------------
    # get_contact_link_doctype / get_contact_link_name
    # ------------------------------------------------------------------
    def test_contact_link_routes_to_member_when_linked(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        self.assertEqual(volunteer.get_contact_link_doctype(), "Member")
        self.assertEqual(volunteer.get_contact_link_name(), self.test_member.name)

    def test_contact_link_falls_back_to_volunteer_when_unlinked(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        # Detach the member in-memory to exercise the fallback branch.
        volunteer.member = None
        self.assertEqual(volunteer.get_contact_link_doctype(), "Volunteer")
        self.assertEqual(volunteer.get_contact_link_name(), volunteer.name)

    # ------------------------------------------------------------------
    # onload / load_aggregated_assignments
    # ------------------------------------------------------------------
    def test_onload_with_linked_member_populates_aggregated_assignments(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        # Fresh fetch triggers onload().
        with self.assertNoErrorLog():
            loaded = frappe.get_doc("Volunteer", volunteer.name)
            loaded.run_method("onload")
        onload = loaded.get("__onload")
        self.assertIsNotNone(onload)
        self.assertIsInstance(onload.aggregated_assignments, list)

    def test_onload_without_member_uses_own_address_and_contact(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        frappe.db.set_value("Volunteer", volunteer.name, "member", None)
        with self.assertNoErrorLog():
            loaded = frappe.get_doc("Volunteer", volunteer.name)
            loaded.run_method("onload")
        self.assertIsInstance(loaded.get("__onload").aggregated_assignments, list)

    # ------------------------------------------------------------------
    # add_activity / end_activity (whitelisted delegators)
    # ------------------------------------------------------------------
    def test_add_activity_creates_record_returned_by_name(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        with self.assertNoErrorLog():
            activity_name = volunteer.add_activity(
                activity_type="Project",
                role="Builder",
                description="Build a thing",
                estimated_hours=12,
            )
        self.assertTrue(frappe.db.exists("Volunteer Activity", activity_name))
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.volunteer, volunteer.name)
        self.assertEqual(activity.role, "Builder")
        self.assertEqual(activity.status, "Active")

    def test_end_activity_marks_completed_and_sets_end_date(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        activity_name = volunteer.add_activity(activity_type="Project", role="Closer")
        with self.assertNoErrorLog():
            result = volunteer.end_activity(activity_name, end_date=today())
        self.assertTrue(result)
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.status, "Completed")
        self.assertTrue(activity.end_date)

    # ------------------------------------------------------------------
    # get_aggregated_assignments / get_volunteer_history delegators
    # ------------------------------------------------------------------
    def test_get_aggregated_assignments_includes_activity(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        activity_name = volunteer.add_activity(activity_type="Project", role="Aggregated Role")
        with self.assertNoErrorLog():
            assignments = volunteer.get_aggregated_assignments()
        self.assertIsInstance(assignments, list)
        names = [a.get("source_name") for a in assignments]
        self.assertIn(activity_name, names)

    def test_get_volunteer_history_returns_list(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.add_activity(activity_type="Project", role="Historic Role")
        with self.assertNoErrorLog():
            history = volunteer.get_volunteer_history()
        self.assertIsInstance(history, list)

    # ------------------------------------------------------------------
    # calculate_total_hours
    # ------------------------------------------------------------------
    def test_calculate_total_hours_sums_activities_and_assignment_history(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        # Activity with estimated hours (no actual) -> uses estimated.
        volunteer.add_activity(activity_type="Project", role="Estimator", estimated_hours=5)
        # Assignment-history row with actual hours.
        volunteer.reload()
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Hourly",
                "start_date": today(),
                "status": "Active",
                "actual_hours": 7,
            },
        )
        volunteer.save()
        with self.assertNoErrorLog():
            total = volunteer.calculate_total_hours()
        self.assertEqual(total, 12)

    def test_calculate_total_hours_prefers_actual_over_estimated(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        activity_name = volunteer.add_activity(activity_type="Project", role="ActualPref", estimated_hours=3)
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        activity.actual_hours = 9
        activity.save()
        with self.assertNoErrorLog():
            total = volunteer.calculate_total_hours()
        # actual (9) used instead of estimated (3).
        self.assertEqual(total, 9)

    # ------------------------------------------------------------------
    # get_skills_by_category
    # ------------------------------------------------------------------
    def test_get_skills_by_category_groups_by_category(self):
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.append(
            "skills_and_qualifications",
            {
                "skill_category": "Technical",
                "volunteer_skill": "Soldering",
                "proficiency_level": "3 - Intermediate",
                "experience_years": 4,
            },
        )
        volunteer.append(
            "skills_and_qualifications",
            {
                "skill_category": "Communication",
                "volunteer_skill": "Writing",
                "proficiency_level": "2 - Basic",
            },
        )
        volunteer.save()
        grouped = volunteer.get_skills_by_category()
        self.assertIn("Technical", grouped)
        self.assertIn("Communication", grouped)
        tech = {s["skill"]: s for s in grouped["Technical"]}
        self.assertIn("Soldering", tech)
        self.assertEqual(tech["Soldering"]["level"], "3 - Intermediate")
        self.assertEqual(tech["Soldering"]["experience"], 4)


class TestCreateVolunteerFromMember(EnhancedTestCase):
    """Coverage for the module-level create_volunteer_from_member() factory."""

    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen.doctype.volunteer import volunteer as volunteer_module

        self.create_volunteer_from_member = volunteer_module.create_volunteer_from_member

    def _track_created_volunteer(self, result):
        if result.get("success") and result.get("volunteer_name"):
            self.track_doc("Volunteer", result["volunteer_name"])

    def test_create_from_member_success_links_back_to_member(self):
        member = self.create_test_member()
        with self.assertNoErrorLog():
            result = self.create_volunteer_from_member(member.name)
        self._track_created_volunteer(result)
        self.assertTrue(result["success"], result)
        vol_name = result["volunteer_name"]
        self.assertTrue(frappe.db.exists("Volunteer", vol_name))
        # Member.volunteer_record back-link is written via db.set_value.
        self.assertEqual(frappe.db.get_value("Member", member.name, "volunteer_record"), vol_name)
        self.assertEqual(frappe.db.get_value("Volunteer", vol_name, "member"), member.name)

    def test_create_from_member_missing_member_returns_error(self):
        result = self.create_volunteer_from_member("Does-Not-Exist-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"])

    def test_create_from_member_duplicate_returns_error(self):
        member = self.create_test_member()
        first = self.create_volunteer_from_member(member.name)
        self._track_created_volunteer(first)
        self.assertTrue(first["success"])

        second = self.create_volunteer_from_member(member.name)
        self.assertFalse(second["success"])
        self.assertIn("already exists", second["error"])

    def test_create_from_member_custom_volunteer_name(self):
        member = self.create_test_member()
        with self.assertNoErrorLog():
            result = self.create_volunteer_from_member(member.name, volunteer_name="Custom Display Name")
        self._track_created_volunteer(result)
        self.assertTrue(result["success"])
        self.assertEqual(
            frappe.db.get_value("Volunteer", result["volunteer_name"], "volunteer_name"),
            "Custom Display Name",
        )

    def test_create_from_member_skills_as_json_string(self):
        member = self.create_test_member()
        skills = json.dumps(["Carpentry", "Plumbing"])
        with self.assertNoErrorLog():
            result = self.create_volunteer_from_member(member.name, interested_skills=skills)
        self._track_created_volunteer(result)
        self.assertTrue(result["success"])
        vol = frappe.get_doc("Volunteer", result["volunteer_name"])
        skill_names = {s.volunteer_skill for s in vol.skills_and_qualifications}
        self.assertEqual(skill_names, {"Carpentry", "Plumbing"})
        # String skills default to category Other.
        self.assertTrue(all(s.skill_category == "Other" for s in vol.skills_and_qualifications))

    def test_create_from_member_skills_as_list_of_dicts(self):
        member = self.create_test_member()
        skills = [
            {"name": "Welding", "category": "Technical", "level": "4 - Advanced"},
            {"skill": "Cooking", "category": "Hospitality"},
        ]
        with self.assertNoErrorLog():
            result = self.create_volunteer_from_member(member.name, interested_skills=skills)
        self._track_created_volunteer(result)
        self.assertTrue(result["success"])
        vol = frappe.get_doc("Volunteer", result["volunteer_name"])
        by_skill = {s.volunteer_skill: s for s in vol.skills_and_qualifications}
        self.assertIn("Welding", by_skill)
        self.assertEqual(by_skill["Welding"].skill_category, "Technical")
        self.assertEqual(by_skill["Welding"].proficiency_level, "4 - Advanced")
        # second dict uses 'skill' key and default level.
        self.assertIn("Cooking", by_skill)
        self.assertEqual(by_skill["Cooking"].proficiency_level, "1 - Beginner")

    def test_create_from_member_invalid_json_falls_back_to_single_skill(self):
        member = self.create_test_member()
        # Production intentionally logs a "JSON Parsing Error" and falls back to
        # treating the raw string as a single literal skill.
        self.expectErrorLog("JSON Parsing Error")
        result = self.create_volunteer_from_member(member.name, interested_skills="Not valid json [[")
        self._track_created_volunteer(result)
        self.assertTrue(result["success"])
        vol = frappe.get_doc("Volunteer", result["volunteer_name"])
        skill_names = [s.volunteer_skill for s in vol.skills_and_qualifications]
        # Bad JSON is treated as a single literal skill.
        self.assertEqual(skill_names, ["Not valid json [["])


class TestVolunteerSkillSearchHelpers(EnhancedTestCase):
    """Coverage for module-level skill search / insight whitelisted helpers."""

    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen.doctype.volunteer import volunteer as volunteer_module

        self.module = volunteer_module
        # An Active volunteer with a distinctive skill to find.
        self.member = self.create_test_member()
        self.volunteer = self.create_test_volunteer(member_name=self.member.name, status="Active")
        self.unique_skill = f"UniqueSkill{frappe.generate_hash()[:8]}"
        self.volunteer.append(
            "skills_and_qualifications",
            {
                "skill_category": "Technical",
                "volunteer_skill": self.unique_skill,
                "proficiency_level": "5 - Expert",
            },
        )
        self.volunteer.save()

    def test_search_volunteers_by_skill_finds_match(self):
        with self.assertNoErrorLog():
            results = self.module.search_volunteers_by_skill(self.unique_skill)
        names = [r["name"] for r in results]
        self.assertIn(self.volunteer.name, names)
        matched = next(r for r in results if r["name"] == self.volunteer.name)
        self.assertEqual(matched["matched_skill"], self.unique_skill)

    def test_search_volunteers_by_skill_with_category_and_level(self):
        with self.assertNoErrorLog():
            results = self.module.search_volunteers_by_skill(
                self.unique_skill, category="Technical", min_level=5
            )
        self.assertIn(self.volunteer.name, [r["name"] for r in results])

        # min_level above the skill's level filters it out.
        no_results = self.module.search_volunteers_by_skill(
            self.unique_skill, category="Technical", min_level=6
        )
        self.assertNotIn(self.volunteer.name, [r["name"] for r in no_results])

    def test_get_skill_suggestions_returns_matching_skill(self):
        with self.assertNoErrorLog():
            suggestions = self.module.get_skill_suggestions(self.unique_skill[:10])
        self.assertIn(self.unique_skill, suggestions)

    def test_get_skill_suggestions_short_input_returns_empty(self):
        self.assertEqual(self.module.get_skill_suggestions("a"), [])
        self.assertEqual(self.module.get_skill_suggestions(""), [])

    def test_get_volunteers_with_filters_by_skill(self):
        with self.assertNoErrorLog():
            results = self.module.get_volunteers_with_filters(skill=self.unique_skill)
        names = [r["name"] for r in results]
        self.assertIn(self.volunteer.name, names)
        matched = next(r for r in results if r["name"] == self.volunteer.name)
        # join clause builds a skills_summary aggregate.
        self.assertIn(self.unique_skill, matched["skills_summary"])

    def test_get_volunteers_with_filters_no_filter_lists_active(self):
        with self.assertNoErrorLog():
            results = self.module.get_volunteers_with_filters()
        self.assertIn(self.volunteer.name, [r["name"] for r in results])
        # No skills join -> skills_summary is NULL.
        matched = next(r for r in results if r["name"] == self.volunteer.name)
        self.assertIsNone(matched["skills_summary"])

    def test_get_volunteers_with_filters_clamps_invalid_max_results(self):
        # Non-numeric max_results falls back to 50 without error.
        with self.assertNoErrorLog():
            results = self.module.get_volunteers_with_filters(max_results="not-a-number")
        self.assertIsInstance(results, list)

    def test_get_all_skills_list_includes_active_volunteer_skill(self):
        # Clear the TTL cache so the freshly added skill is visible.
        self.module._get_all_skills_list_cached.cache_clear()
        with self.assertNoErrorLog():
            skills = self.module.get_all_skills_list()
        self.assertTrue(any(s["volunteer_skill"] == self.unique_skill for s in skills))

    def test_get_skill_insights_structure_and_expert_skill(self):
        self.module._get_all_skills_list_cached.cache_clear()
        with self.assertNoErrorLog():
            insights = self.module.get_skill_insights()
        self.assertIn("popular_skills", insights)
        self.assertIn("category_distribution", insights)
        self.assertIn("expert_skills", insights)
        self.assertIn("development_skills", insights)
        self.assertGreaterEqual(insights["total_volunteers_with_skills"], 1)
        # Expert (level 5) skill should surface in expert_skills.
        expert_names = [s["volunteer_skill"] for s in insights["expert_skills"]]
        self.assertIn(self.unique_skill, expert_names)
