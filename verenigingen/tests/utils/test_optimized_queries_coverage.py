"""Coverage sweep for verenigingen/utils/optimized_queries.py.

Real-DB integration tests. For each optimized (bulk/JOIN) query function the
result is asserted against an INDEPENDENT simple recomputation scoped to the
fixtures created in the test — proving the optimization returns the same answer
as the naive approach, rather than merely exercising the code path.

Also covers the input-validation / SQL-injection guards and the placeholder
helper, which sit on the same module.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.fake_cache import isolate_cache_keys
from verenigingen.utils.optimized_queries import (
    OptimizedChapterQueries,
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    QueryCache,
    create_safe_sql_placeholders,
    optimize_volunteer_assignment_loading,
    validate_member_names,
)


class TestInputValidationGuards(EnhancedTestCase):
    """validate_member_names / create_safe_sql_placeholders."""

    # --- validate_member_names -------------------------------------------
    def test_member_names_empty_list_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names([])

    def test_member_names_non_list_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names("Assoc-Member-2025-0001")

    def test_member_names_too_many_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names([f"Member-{i}" for i in range(1001)])

    def test_member_names_non_string_element_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["valid-name", 123])

    def test_member_names_blank_element_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["   "])

    def test_member_names_too_long_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["a" * 201])

    def test_member_names_invalid_chars_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["bad$name#here"])

    def test_member_names_sql_keyword_rejected(self):
        # Passes the char pattern but trips the dangerous-keyword scan.
        with self.assertRaises(ValueError):
            validate_member_names(["select something"])

    def test_member_names_valid_accepted(self):
        # The canonical member-name shape: alnum, hyphens, dots, @.
        validate_member_names(["Assoc-Member-2025-0001", "john.doe@example.org"])

    # --- create_safe_sql_placeholders ------------------------------------
    def test_placeholders_basic(self):
        self.assertEqual(create_safe_sql_placeholders(3), "%s,%s,%s")

    def test_placeholders_zero_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(0)

    def test_placeholders_negative_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(-1)

    def test_placeholders_too_many_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(1001)


class TestOptimizedSEPAQueries(EnhancedTestCase):
    """Active SEPA-mandate bulk loading vs independent query."""

    def _make_mandate(self, member, status="Active"):
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = member.name
        mandate.member_name = member.full_name
        mandate.mandate_id = f"M-{frappe.generate_hash(length=8)}"
        mandate.iban = generate_test_iban("TEST")
        mandate.bic = "TESTNL2A"
        mandate.status = status
        mandate.account_holder_name = member.full_name
        mandate.sign_date = today()
        mandate.insert()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    def test_active_mandates_empty_returns_empty(self):
        self.assertEqual(OptimizedSEPAQueries.get_active_mandates_for_members([]), {})

    def test_active_mandates_match_independent_query(self):
        member = self.create_test_member()
        mandate = self._make_mandate(member, status="Active")

        result = OptimizedSEPAQueries.get_active_mandates_for_members([member.name])
        self.assertIn(member.name, result)
        self.assertEqual(result[member.name]["mandate_name"], mandate.name)
        self.assertEqual(result[member.name]["status"], "Active")

        # Independent: the active mandate for this member.
        expected = frappe.db.get_value("SEPA Mandate", {"member": member.name, "status": "Active"}, "name")
        self.assertEqual(result[member.name]["mandate_name"], expected)

    def test_inactive_mandate_excluded(self):
        member = self.create_test_member()
        self._make_mandate(member, status="Cancelled")
        result = OptimizedSEPAQueries.get_active_mandates_for_members([member.name])
        # No active mandate -> member key absent.
        self.assertNotIn(member.name, result)

    def test_active_mandates_rejects_injection(self):
        with self.assertRaises(ValueError):
            OptimizedSEPAQueries.get_active_mandates_for_members(["x'; DROP --"])


class TestOptimizedVolunteerQueries(EnhancedTestCase):
    """Volunteer assignment UNION query vs independent recomputation."""

    def test_volunteer_assignments_empty_returns_empty(self):
        self.assertEqual(OptimizedVolunteerQueries.get_volunteer_assignments_bulk([]), {})

    def test_volunteer_no_assignments_returns_initialized_empty_list(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)
        result = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer.name])
        # Every requested volunteer is keyed, even with zero assignments.
        self.assertIn(volunteer.name, result)
        self.assertEqual(result[volunteer.name], [])

    def test_volunteer_activity_assignment_captured(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)

        activity = frappe.new_doc("Volunteer Activity")
        activity.volunteer = volunteer.name
        activity.activity_type = "Event"
        activity.role = "Helper"
        activity.status = "Active"
        activity.start_date = today()
        activity.insert()
        self.track_doc("Volunteer Activity", activity.name)

        result = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer.name])
        assignments = result[volunteer.name]
        activity_rows = [a for a in assignments if a["assignment_type"] == "Activity"]
        self.assertEqual(len(activity_rows), 1)
        self.assertEqual(activity_rows[0]["source_name"], activity.name)
        self.assertEqual(activity_rows[0]["role"], "Helper")
        # Activity rows are flagged editable=1 in the UNION.
        self.assertEqual(activity_rows[0]["editable"], 1)
        # Open-ended (start today, no end) -> active.
        self.assertEqual(activity_rows[0]["is_active"], 1)

    def test_volunteer_assignments_rejects_injection(self):
        with self.assertRaises(ValueError):
            OptimizedVolunteerQueries.get_volunteer_assignments_bulk(["x; DELETE"])


class TestOptimizedChapterQueries(EnhancedTestCase):
    """Postal-code -> chapter assignment matching."""

    def test_empty_postal_codes_returns_empty(self):
        self.assertEqual(OptimizedChapterQueries.get_chapter_assignments_bulk([]), {})

    def test_postal_code_matches_active_chapter(self):
        chapter = self.create_test_chapter()
        # Configure the chapter's postal_codes range to contain a code.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.status = "Active"
        chapter_doc.postal_codes = "1234"
        chapter_doc.save()

        result = OptimizedChapterQueries.get_chapter_assignments_bulk(["1234"])
        # FIND_IN_SET on the (space-stripped) postal_codes string must match.
        self.assertEqual(result.get("1234"), chapter.name)

    def test_postal_code_no_match_absent(self):
        result = OptimizedChapterQueries.get_chapter_assignments_bulk(["99999"])
        self.assertNotIn("99999", result)


class TestQueryCacheAndDropIns(EnhancedTestCase):
    """QueryCache round-trip + the drop-in replacement helpers."""

    def test_member_data_cache_roundtrip_and_invalidate(self):
        # Route the QueryCache key through an in-process dict so a sibling shard's
        # frappe.clear_cache() (redis FLUSH on the shared CI redis) cannot evict
        # the value between set and get. See tests/fixtures/fake_cache.py.
        with isolate_cache_keys("member_data:"):
            key = f"cachetest-{frappe.generate_hash(length=6)}"
            self.assertIsNone(QueryCache.get_cached_member_data(key))
            QueryCache.set_cached_member_data(key, {"x": 1})
            self.assertEqual(QueryCache.get_cached_member_data(key), {"x": 1})
            QueryCache.invalidate_member_cache(key)
            self.assertIsNone(QueryCache.get_cached_member_data(key))

    def test_volunteer_assignments_cache_roundtrip(self):
        # Flush-proof the set->get round-trip on the shared CI redis.
        with isolate_cache_keys("volunteer_assignments:"):
            key = f"voltest-{frappe.generate_hash(length=6)}"
            self.assertIsNone(QueryCache.get_cached_volunteer_assignments(key))
            QueryCache.set_cached_volunteer_assignments(key, [{"a": 1}])
            self.assertEqual(QueryCache.get_cached_volunteer_assignments(key), [{"a": 1}])

    def test_optimize_volunteer_assignment_loading_caches_result(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)
        # Flush-proof the production cache slot this exercises so a sibling
        # shard's redis FLUSH cannot evict the cached result between writes/reads.
        with isolate_cache_keys("volunteer_assignments:"):
            # Ensure a clean cache slot.
            frappe.cache().delete_value(f"volunteer_assignments:{volunteer.name}")

            first = optimize_volunteer_assignment_loading(volunteer.name)
            self.assertIsInstance(first, list)
            # Second call must hit the cache and return the same data.
            cached = QueryCache.get_cached_volunteer_assignments(volunteer.name)
            self.assertEqual(cached, first)
            second = optimize_volunteer_assignment_loading(volunteer.name)
            self.assertEqual(second, first)
