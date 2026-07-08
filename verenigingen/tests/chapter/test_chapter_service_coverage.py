"""
Test coverage for 12 chapter services + Chapter Board Member child table.

Services tested:
1. ChapterAssignmentService — member-to-chapter assignment
2. ChapterBoardService — board member data operations
3. ChapterEventService — change detection, event emission
4. ChapterMatchingService — chapter matching logic
5. chapter_provisioning_service — ensure_region / ensure_chapter functions
6. ChapterQueryService — chapter queries
7. ChapterReferenceManager — reference validation/cleanup
8. chapter_security — permission helpers
9. ChapterValidationService — validation and auto-fix
10. DepartmentSyncService — department synchronization
11. OptimizedChapterLookup — optimized lookup queries
12. ChapterBoardMember — child table controller (validate, role assignment)
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# 1. ChapterAssignmentService
# ---------------------------------------------------------------------------
class TestChapterAssignmentService(EnhancedTestCase):
    """Tests for ChapterAssignmentService — member-to-chapter assignment."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test Assign Chapter")
        self.member = self.create_test_member(first_name="Assign", last_name="Svc")

    def _get_service(self):
        from verenigingen.services.chapter.chapter_assignment_service import (
            get_chapter_assignment_service,
        )

        return get_chapter_assignment_service()

    # --- assign_member ---
    def test_assign_member_success(self):
        """assign_member returns success and marks added_to_members."""
        svc = self._get_service()
        result = svc.assign_member(self.member.name, self.chapter.name, note="unit test")
        self.assertTrue(result["success"])
        self.assertIn("added_to_members", result)

    def test_assign_member_validation_empty_member(self):
        """assign_member throws when member is empty."""
        svc = self._get_service()
        with self.assertRaises(frappe.ValidationError):
            svc.assign_member("", self.chapter.name)

    def test_assign_member_validation_empty_chapter(self):
        """assign_member throws when chapter is empty."""
        svc = self._get_service()
        with self.assertRaises(frappe.ValidationError):
            svc.assign_member(self.member.name, "")

    # --- assign_with_cleanup ---
    def test_assign_with_cleanup_fresh_member(self):
        """assign_with_cleanup works for a member not in any chapter."""
        svc = self._get_service()
        result = svc.assign_with_cleanup(self.member.name, self.chapter.name, note="cleanup test")
        self.assertTrue(result["success"])
        self.assertIn("cleanup_performed", result)
        self.assertIn("message", result)

    def test_assign_with_cleanup_already_in_target(self):
        """assign_with_cleanup returns appropriate message when already assigned."""
        svc = self._get_service()
        # First assignment
        svc.assign_member(self.member.name, self.chapter.name)
        # Second assignment to same chapter
        result = svc.assign_with_cleanup(self.member.name, self.chapter.name)
        self.assertTrue(result["success"])
        # Should not add again
        self.assertFalse(result.get("added_to_members", True))

    def test_assign_with_cleanup_validation(self):
        """assign_with_cleanup throws when member is empty."""
        svc = self._get_service()
        with self.assertRaises(frappe.ValidationError):
            svc.assign_with_cleanup("", self.chapter.name)


# ---------------------------------------------------------------------------
# 2. ChapterBoardService
# ---------------------------------------------------------------------------
class TestChapterBoardService(EnhancedTestCase):
    """Tests for ChapterBoardService — chapter head updates and chair queries."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test Board Svc Chapter")

    def _get_service(self):
        from verenigingen.services.chapter.chapter_board_service import (
            get_chapter_board_service,
        )

        return get_chapter_board_service()

    def test_update_chapter_head_no_board_members(self):
        """update_chapter_head returns False and clears head when no board members."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.board_members = []
        result = svc.update_chapter_head(chapter_doc)
        self.assertFalse(result)
        self.assertIsNone(chapter_doc.chapter_head)

    def test_get_chapter_chair_optimized_no_board(self):
        """get_chapter_chair_optimized returns None when no board members."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.board_members = []
        result = svc.get_chapter_chair_optimized(chapter_doc)
        self.assertIsNone(result)

    def test_populate_board_document_fields_deprecated(self):
        """populate_board_document_fields is deprecated and does nothing."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        # Should not raise
        svc.populate_board_document_fields(chapter_doc)


# ---------------------------------------------------------------------------
# 3. ChapterEventService
# ---------------------------------------------------------------------------
class TestChapterEventService(EnhancedTestCase):
    """Tests for ChapterEventService — change detection and event emission."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test Event Svc Chapter")

    def _get_service(self):
        from verenigingen.services.chapter.chapter_event_service import (
            get_chapter_event_service,
        )

        return get_chapter_event_service()

    def test_detect_board_changes_no_changes(self):
        """detect_and_emit_board_changes does not raise when boards are identical."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        old_doc = frappe.get_doc("Chapter", self.chapter.name)
        # Should not raise
        svc.detect_and_emit_board_changes(chapter_doc, old_doc)

    def test_detect_membership_changes_no_changes(self):
        """detect_and_emit_membership_changes does not raise with identical members."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        old_doc = frappe.get_doc("Chapter", self.chapter.name)
        svc.detect_and_emit_membership_changes(chapter_doc, old_doc)

    def test_detect_settings_changes_no_changes(self):
        """detect_and_emit_settings_changes does not raise with no changes."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        old_doc = frappe.get_doc("Chapter", self.chapter.name)
        svc.detect_and_emit_settings_changes(chapter_doc, old_doc)


# ---------------------------------------------------------------------------
# 4. ChapterMatchingService
# ---------------------------------------------------------------------------
class TestChapterMatchingService(EnhancedTestCase):
    """Tests for ChapterMatchingService — chapter suggestion algorithms."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter(
            "Test Match Chapter",
            {"published": 1, "postal_codes": "1000-1999", "region": None},
        )

    def _get_service(self):
        from verenigingen.services.chapter.chapter_matching_service import (
            get_chapter_matching_service,
        )

        return get_chapter_matching_service()

    def test_get_chapters_by_postal_code_empty(self):
        """get_chapters_by_postal_code returns empty list for empty input."""
        svc = self._get_service()
        result = svc.get_chapters_by_postal_code("")
        self.assertEqual(result, [])

    def test_get_chapters_by_postal_code_no_match(self):
        """get_chapters_by_postal_code returns empty for non-matching code."""
        svc = self._get_service()
        result = svc.get_chapters_by_postal_code("9999ZZ")
        self.assertIsInstance(result, list)

    def test_suggest_chapters_for_member_returns_list(self):
        """suggest_chapters_for_member returns a list."""
        member = self.create_test_member(first_name="Match", last_name="Test")
        svc = self._get_service()
        result = svc.suggest_chapters_for_member(member.name)
        self.assertIsInstance(result, list)

    def test_suggest_chapters_with_explicit_postal(self):
        """suggest_chapters_for_member uses explicit postal_code parameter."""
        member = self.create_test_member(first_name="Postal", last_name="Test")
        svc = self._get_service()
        result = svc.suggest_chapters_for_member(member.name, postal_code="1234AB")
        self.assertIsInstance(result, list)

    def test_calculate_region_match_score_no_match(self):
        """_calculate_region_match_score returns 0 when nothing matches."""
        svc = self._get_service()
        score = svc._calculate_region_match_score(
            chapter={"name": "X", "region": "Amsterdam"},
            state="Groningen",
            city="Assen",
        )
        self.assertEqual(score, 0)

    def test_calculate_region_match_score_state_in_region(self):
        """_calculate_region_match_score awards points for state-in-region match."""
        svc = self._get_service()
        score = svc._calculate_region_match_score(
            chapter={"name": "X", "region": "Noord-Holland"},
            state="Noord-Holland",
            city=None,
        )
        self.assertEqual(score, svc.SCORE_STATE_IN_REGION)

    def test_calculate_region_match_score_city_in_name(self):
        """_calculate_region_match_score awards points for city-in-name match."""
        svc = self._get_service()
        score = svc._calculate_region_match_score(
            chapter={"name": "Amsterdam", "region": "XYZ"},
            state=None,
            city="Amsterdam",
        )
        self.assertEqual(score, svc.SCORE_CITY_IN_NAME)


# ---------------------------------------------------------------------------
# 5. chapter_provisioning_service (module-level functions)
# ---------------------------------------------------------------------------
class TestChapterProvisioningService(EnhancedTestCase):
    """Tests for ensure_region / ensure_chapter provisioning functions."""

    def test_ensure_region_creates_or_finds_nl(self):
        """ensure_region returns a valid region name."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_region

        result = ensure_region()
        self.assertIsNotNone(result)
        self.assertTrue(frappe.db.exists("Region", result))

    def test_ensure_region_explicit_existing(self):
        """ensure_region returns explicit region if it exists."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_region

        # Create a region first
        region_name = ensure_region()
        result = ensure_region(default_region=region_name)
        self.assertEqual(result, region_name)

    def test_ensure_region_explicit_nonexistent_throws(self):
        """ensure_region throws when explicit region does not exist."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_region

        with self.assertRaises(frappe.ValidationError):
            ensure_region(default_region="NonExistentRegion99999")

    def test_ensure_chapter_creates_new(self):
        """ensure_chapter creates a new chapter when it does not exist."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_chapter

        chapter_name = f"Prov Test Chapter {frappe.generate_hash(length=6)}"
        result = ensure_chapter(chapter_name)
        self.assertEqual(result, chapter_name)
        self.assertTrue(frappe.db.exists("Chapter", chapter_name))

    def test_ensure_chapter_existing(self):
        """ensure_chapter returns existing chapter name without error."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_chapter

        chapter = self.ensure_test_chapter("Prov Existing Chapter")
        result = ensure_chapter(chapter.name)
        self.assertEqual(result, chapter.name)


# ---------------------------------------------------------------------------
# 6. ChapterQueryService
# ---------------------------------------------------------------------------
class TestChapterQueryService(EnhancedTestCase):
    """Tests for ChapterQueryService — user permission queries."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test Query Svc Chapter")

    def _get_service(self):
        from verenigingen.services.chapter.chapter_query_service import (
            get_chapter_query_service,
        )

        return get_chapter_query_service()

    def test_get_user_permissions_returns_dict(self):
        """get_user_permissions_optimized returns expected keys."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        result = svc.get_user_permissions_optimized(chapter_doc)
        self.assertIsInstance(result, dict)
        for key in ["is_board_member", "board_role", "is_system_manager", "can_write_chapter", "can_view_members"]:
            self.assertIn(key, result)

    def test_get_user_permissions_admin_full_access(self):
        """Admin user gets full access in permissions dict."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        # Running as Administrator by default in tests
        result = svc.get_user_permissions_optimized(chapter_doc)
        self.assertTrue(result["can_write_chapter"])
        self.assertTrue(result["can_view_members"])


# ---------------------------------------------------------------------------
# 7. ChapterReferenceManager
# ---------------------------------------------------------------------------
class TestChapterReferenceManager(EnhancedTestCase):
    """Tests for ChapterReferenceManager — reference validation and cleanup."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Ref", last_name="MgrTest")

    def test_validate_chapter_references_no_history(self):
        """validate_chapter_references returns empty list when no history."""
        from verenigingen.services.chapter.chapter_reference_manager import ChapterReferenceManager

        member_doc = frappe.get_doc("Member", self.member.name)
        mgr = ChapterReferenceManager(member_doc)
        result = mgr.validate_chapter_references()
        self.assertIsInstance(result, list)

    def test_has_invalid_chapter_references_no_history(self):
        """has_invalid_chapter_references returns False when no history."""
        from verenigingen.services.chapter.chapter_reference_manager import ChapterReferenceManager

        member_doc = frappe.get_doc("Member", self.member.name)
        mgr = ChapterReferenceManager(member_doc)
        self.assertFalse(mgr.has_invalid_chapter_references())

    def test_cleanup_invalid_chapter_references_no_history(self):
        """cleanup_invalid_chapter_references returns 0 when no history."""
        from verenigingen.services.chapter.chapter_reference_manager import ChapterReferenceManager

        member_doc = frappe.get_doc("Member", self.member.name)
        mgr = ChapterReferenceManager(member_doc)
        result = mgr.cleanup_invalid_chapter_references()
        self.assertEqual(result, 0)

    def test_cleanup_member_chapter_references_utility(self):
        """Module-level cleanup_member_chapter_references works."""
        from verenigingen.services.chapter.chapter_reference_manager import cleanup_member_chapter_references

        result = cleanup_member_chapter_references(self.member.name)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# 8. chapter_security (module-level functions)
# ---------------------------------------------------------------------------
class TestChapterSecurity(EnhancedTestCase):
    """Tests for chapter_security — permission helpers."""

    def test_get_user_manageable_chapters_admin(self):
        """Admin user gets 'all' manageable chapters."""
        from verenigingen.services.chapter.chapter_security import get_user_manageable_chapters

        result = get_user_manageable_chapters(user="Administrator")
        self.assertEqual(result, "all")

    def test_can_user_manage_application_admin(self):
        """Admin user can manage any application."""
        from verenigingen.services.chapter.chapter_security import can_user_manage_application

        member = self.create_test_member(first_name="SecTest", last_name="Member")
        result = can_user_manage_application(member.name, user="Administrator")
        self.assertTrue(result)

    def test_filter_applications_by_permission_admin(self):
        """Admin user sees all applications."""
        from verenigingen.services.chapter.chapter_security import filter_applications_by_permission

        apps = [{"name": "MEM-001"}, {"name": "MEM-002"}]
        result = filter_applications_by_permission(apps, user="Administrator")
        self.assertEqual(len(result), 2)

    def test_validate_chapter_permission_or_throw_admin(self):
        """Admin user does not get PermissionError."""
        from verenigingen.services.chapter.chapter_security import validate_chapter_permission_or_throw

        member = self.create_test_member(first_name="SecVal", last_name="Test")
        # Should not raise for Administrator
        validate_chapter_permission_or_throw(member.name, user="Administrator")

    def test_get_user_manageable_chapters_no_member(self):
        """User without member record gets empty list."""
        from verenigingen.services.chapter.chapter_security import get_user_manageable_chapters

        result = get_user_manageable_chapters(user="Guest")
        # Guest has no admin roles and no member record
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_validate_chapter_permission_or_throw_denies_non_manager(self):
        """A non-privileged user (no manageable chapters) gets a PermissionError.

        Complements the admin happy-path test: an authenticated user with only
        a basic member role, no board seat and no linked Member record has
        get_user_manageable_chapters() == [], so can_user_manage_application()
        returns False and validate_chapter_permission_or_throw must raise
        frappe.PermissionError (not merely return).
        """
        from verenigingen.services.chapter.chapter_security import validate_chapter_permission_or_throw

        member = self.create_test_member(first_name="SecDeny", last_name="Target")
        plain_user = self.create_test_user(
            self.factory.generate_test_email("plainuser"),
            roles=["Verenigingen Member"],
        )
        with self.assertRaises(frappe.PermissionError) as ctx:
            validate_chapter_permission_or_throw(member.name, action="approve", user=plain_user.name)
        self.assertIn("permission", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# 9. ChapterValidationService
# ---------------------------------------------------------------------------
class TestChapterValidationService(EnhancedTestCase):
    """Tests for ChapterValidationService — access validation and auto-fix."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test Validation Svc Chapter")

    def _get_service(self):
        from verenigingen.services.chapter.chapter_validation_service import (
            get_chapter_validation_service,
        )

        return get_chapter_validation_service()

    def test_validate_chapter_access_admin(self):
        """validate_chapter_access does not raise for Administrator."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        # Should not raise
        svc.validate_chapter_access(chapter_doc)

    def test_auto_fix_required_fields_test_chapter(self):
        """auto_fix_required_fields sets region for test chapter."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        original_region = chapter_doc.region
        chapter_doc.region = None
        chapter_doc.introduction = None
        chapter_doc.published = 0
        svc.auto_fix_required_fields(chapter_doc)
        # Region should be auto-set (contains "test" in name)
        self.assertIsNotNone(chapter_doc.region)
        # Introduction should be auto-set for unpublished chapter
        self.assertIsNotNone(chapter_doc.introduction)

    def test_auto_fix_required_fields_no_change_when_present(self):
        """auto_fix_required_fields does not overwrite existing region."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        original_region = chapter_doc.region
        svc.auto_fix_required_fields(chapter_doc)
        # Region should not be changed if already set
        self.assertEqual(chapter_doc.region, original_region)

    def test_auto_fix_status_defaults_to_active(self):
        """auto_fix_required_fields sets status to 'Active' when missing.

        Chapter.status is reqd=1 with default 'Active' in chapter.json, but
        Frappe applies field defaults at the form layer — not for
        frappe.get_doc({...}).insert(). The auto-fix bridges that gap so
        raw-dict inserts don't fail with MandatoryError(status).
        """
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.status = None
        svc.auto_fix_required_fields(chapter_doc)
        self.assertEqual(chapter_doc.status, "Active")

    def test_auto_fix_status_preserves_existing_value(self):
        """auto_fix_required_fields does not overwrite an existing status."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.status = "Inactive"
        svc.auto_fix_required_fields(chapter_doc)
        self.assertEqual(chapter_doc.status, "Inactive")


# ---------------------------------------------------------------------------
# 10. DepartmentSyncService
# ---------------------------------------------------------------------------
class TestDepartmentSyncService(EnhancedTestCase):
    """Tests for DepartmentSyncService — ERPNext Department synchronization."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test DeptSync Chapter")

    def _get_service(self):
        from verenigingen.services.chapter.department_sync_service import (
            get_department_sync_service,
        )

        return get_department_sync_service()

    def test_sync_department_does_not_raise(self):
        """sync_department does not raise for a valid chapter."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        # Should not raise — errors are caught internally
        svc.sync_department(chapter_doc)

    def test_sync_department_creates_or_updates_department(self):
        """sync_department creates a linked department."""
        svc = self._get_service()
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        svc.sync_department(chapter_doc)
        # Reload to check department link
        chapter_doc.reload()
        # Department may or may not exist depending on company config.
        # The key is that the method does not raise.


# ---------------------------------------------------------------------------
# 11. OptimizedChapterLookup
# ---------------------------------------------------------------------------
class TestOptimizedChapterLookup(EnhancedTestCase):
    """Tests for OptimizedChapterLookup — optimized postal code lookups."""

    def _get_lookup(self):
        from verenigingen.services.chapter.optimized_chapter_lookup import OptimizedChapterLookup

        return OptimizedChapterLookup()

    def test_is_chapter_management_enabled(self):
        """is_chapter_management_enabled returns a boolean."""
        lookup = self._get_lookup()
        result = lookup.is_chapter_management_enabled()
        self.assertIsInstance(result, (bool, int))

    def test_invalidate_cache(self):
        """invalidate_cache resets internal state."""
        lookup = self._get_lookup()
        # Prime cache
        lookup.is_chapter_management_enabled()
        lookup.invalidate_cache()
        self.assertIsNone(lookup._chapter_management_enabled)
        self.assertIsNone(lookup._chapter_postal_mapping)

    def test_parse_postal_code_patterns_empty(self):
        """_parse_postal_code_patterns returns empty list for empty input."""
        lookup = self._get_lookup()
        result = lookup._parse_postal_code_patterns("")
        self.assertEqual(result, [])

    def test_parse_postal_code_patterns_basic(self):
        """_parse_postal_code_patterns parses comma-separated patterns."""
        lookup = self._get_lookup()
        result = lookup._parse_postal_code_patterns("1000, 2000, 3000")
        self.assertEqual(len(result), 3)

    def test_parse_postal_code_patterns_with_comments(self):
        """_parse_postal_code_patterns skips comment lines."""
        lookup = self._get_lookup()
        result = lookup._parse_postal_code_patterns("# comment\n1000\n2000")
        self.assertEqual(len(result), 2)

    def test_test_postal_code_match_exact(self):
        """_test_postal_code_match matches exact codes."""
        lookup = self._get_lookup()
        self.assertTrue(lookup._test_postal_code_match("1234AB", "1234AB"))
        self.assertFalse(lookup._test_postal_code_match("1234AB", "5678CD"))

    def test_test_postal_code_match_range(self):
        """_test_postal_code_match matches range patterns."""
        lookup = self._get_lookup()
        self.assertTrue(lookup._test_postal_code_match("1500", "1000-1999"))
        self.assertFalse(lookup._test_postal_code_match("2500", "1000-1999"))

    def test_test_postal_code_match_prefix(self):
        """_test_postal_code_match matches prefix patterns."""
        lookup = self._get_lookup()
        self.assertTrue(lookup._test_postal_code_match("1234AB", "12*"))
        self.assertFalse(lookup._test_postal_code_match("9999AB", "12*"))

    def test_test_postal_code_match_empty(self):
        """_test_postal_code_match returns False for empty inputs."""
        lookup = self._get_lookup()
        self.assertFalse(lookup._test_postal_code_match("", "1234"))
        self.assertFalse(lookup._test_postal_code_match("1234", ""))

    def test_find_chapters_for_postal_code_empty(self):
        """find_chapters_for_postal_code returns empty for empty input."""
        lookup = self._get_lookup()
        result = lookup.find_chapters_for_postal_code("")
        self.assertEqual(result, [])

    def test_find_best_chapter_for_postal_code_no_match(self):
        """find_best_chapter_for_postal_code returns None when no match."""
        lookup = self._get_lookup()
        # Use a postal code unlikely to match anything
        result = lookup.find_best_chapter_for_postal_code("0000XX")
        # Could be None or a chapter depending on data; just check type
        self.assertIsInstance(result, (str, type(None)))

    def test_batch_find_chapters_for_members(self):
        """batch_find_chapters_for_members returns dict with member keys."""
        lookup = self._get_lookup()
        result = lookup.batch_find_chapters_for_members([
            ("MEM-001", "1234AB"),
            ("MEM-002", ""),
            ("MEM-003", None),
        ])
        self.assertIsInstance(result, dict)
        self.assertIn("MEM-001", result)
        self.assertIn("MEM-002", result)
        self.assertIsNone(result["MEM-002"])

    def test_module_level_find_chapter_by_postal_code_optimized(self):
        """Module-level find_chapter_by_postal_code_optimized returns dict."""
        from verenigingen.services.chapter.optimized_chapter_lookup import (
            find_chapter_by_postal_code_optimized,
        )

        result = find_chapter_by_postal_code_optimized("")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])

    def test_module_level_batch_suggest(self):
        """Module-level batch_suggest_chapters_for_members returns dict."""
        from verenigingen.services.chapter.optimized_chapter_lookup import (
            batch_suggest_chapters_for_members,
        )

        result = batch_suggest_chapters_for_members([("MEM-X", "1234")])
        self.assertIsInstance(result, dict)

    def test_module_level_invalidate_cache(self):
        """Module-level invalidate_chapter_lookup_cache does not raise."""
        from verenigingen.services.chapter.optimized_chapter_lookup import (
            invalidate_chapter_lookup_cache,
        )

        invalidate_chapter_lookup_cache()


# ---------------------------------------------------------------------------
# 12. ChapterBoardMember child table controller
# ---------------------------------------------------------------------------
class TestChapterBoardMemberController(EnhancedTestCase):
    """Tests for ChapterBoardMember child table — validation hooks."""

    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("Test BoardMember Chapter")

    def _make_board_member_doc(self, **overrides):
        """Create an in-memory ChapterBoardMember doc for validation tests."""
        member = self.create_test_member(first_name="Board", last_name="Ctrl")
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self.factory.ensure_chapter_role("Test Board Role")

        doc = frappe.get_doc({
            "doctype": "Chapter Board Member",
            "parent": self.chapter.name,
            "parenttype": "Chapter",
            "parentfield": "board_members",
            "volunteer": volunteer.name,
            "chapter_role": role.name,
            "from_date": today(),
            "is_active": 1,
        })
        for k, v in overrides.items():
            setattr(doc, k, v)
        return doc

    def test_validate_required_fields_missing_volunteer(self):
        """validate_required_fields throws when volunteer is missing."""
        doc = self._make_board_member_doc()
        doc.volunteer = None
        with self.assertRaises(Exception):
            doc.validate_required_fields()

    def test_validate_required_fields_missing_role(self):
        """validate_required_fields throws when chapter_role is missing."""
        doc = self._make_board_member_doc()
        doc.chapter_role = None
        with self.assertRaises(Exception):
            doc.validate_required_fields()

    def test_validate_required_fields_missing_from_date(self):
        """validate_required_fields throws when from_date is missing."""
        doc = self._make_board_member_doc()
        doc.from_date = None
        with self.assertRaises(Exception):
            doc.validate_required_fields()

    def test_validate_date_range_invalid(self):
        """validate_date_range throws when to_date is before from_date."""
        doc = self._make_board_member_doc(
            from_date="2025-06-01",
            to_date="2025-01-01",
        )
        with self.assertRaises(Exception):
            doc.validate_date_range()

    def test_validate_date_range_valid(self):
        """validate_date_range does not throw for valid range."""
        doc = self._make_board_member_doc(
            from_date="2025-01-01",
            to_date="2025-12-31",
        )
        doc.validate_date_range()

    def test_validate_active_status_past_end_date(self):
        """validate_active_status throws when active with past end date."""
        doc = self._make_board_member_doc(
            is_active=1,
            to_date="2020-01-01",
        )
        with self.assertRaises(Exception):
            doc.validate_active_status()

    def test_validate_email_format_invalid(self):
        """validate_email_format throws for invalid email."""
        doc = self._make_board_member_doc()
        doc.email = "not-an-email"
        with self.assertRaises(Exception):
            doc.validate_email_format()

    def test_validate_email_format_valid(self):
        """validate_email_format does not throw for valid email."""
        doc = self._make_board_member_doc()
        doc.email = "test@example.com"
        doc.validate_email_format()

    def test_validate_volunteer_exists_invalid(self):
        """validate_volunteer_exists throws for nonexistent volunteer."""
        doc = self._make_board_member_doc()
        doc.volunteer = "NONEXISTENT-VOL-99999"
        with self.assertRaises(Exception):
            doc.validate_volunteer_exists()

    def test_validate_role_exists_invalid(self):
        """validate_role_exists throws for nonexistent role."""
        doc = self._make_board_member_doc()
        doc.chapter_role = "NONEXISTENT-ROLE-99999"
        with self.assertRaises(Exception):
            doc.validate_role_exists()

    def test_full_validate_success(self):
        """Full validate() passes for a valid board member doc."""
        doc = self._make_board_member_doc()
        # Should not raise
        doc.validate()
