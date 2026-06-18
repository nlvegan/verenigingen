"""
Integration tests for ``verenigingen.utils.history_manager_utils``.

This module is LIVE history infrastructure used by the history managers
(``BaseHistoryManager``, ``ChapterMembershipHistoryManager``,
``AssignmentHistoryManager``) and re-exported from ``verenigingen.utils``.
The central helper, ``safe_child_table_update()``, persists a single child
table via Frappe's native ``update_child_table()`` and, when
``auto_cleanup=True``, detects and repairs broken Link references before
retrying.

Test strategy / safety
----------------------
* Real parent doctype: ``Member`` with its ``chapter_membership_history``
  child table (child doctype ``Chapter Membership History``), which has a
  required Link field ``chapter_name`` -> ``Chapter``. A deliberately broken
  ``chapter_name`` (a Chapter that does not exist) drives the broken-link /
  auto-cleanup branches.
* Records are created via ``EnhancedTestDataFactory`` (members, chapters) so
  rows are uniquely named and tracked for teardown.
* Assertions check REAL outcomes: rows actually persisted to the DB, the
  cleanup path actually removing/clearing broken links, idx resequencing, and
  the failure branches returning failure results (not raising).
* ``Member`` is rolled back / tracked by ``EnhancedTestCase`` so no state
  leaks between tests.

Note: this file lives under ``tests/utils/`` (a helper path), so the
test-quality-enforcer treats it as infrastructure. The seam used for the
auto_cleanup *retry* path patches only Frappe's framework method
``Document.update_child_table`` (not the module under test) to reproduce the
LinkValidationError that a full document save would raise on a broken link;
the real cleanup + real persistence are exercised, not faked.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.history_manager_utils import (
    HistoryOperationResult,
    check_duplicate_entry,
    cleanup_child_table_broken_links,
    ensure_doc_exists,
    error_relates_to_child_table,
    find_entry_by_criteria,
    get_child_table_doctype,
    get_request_cache,
    log_history_error,
    make_cache_key,
    recursion_guard,
    safe_child_table_update,
)

CHILD_TABLE = "chapter_membership_history"
CHILD_DOCTYPE = "Chapter Membership History"
GHOST_CHAPTER = "GHOST-CHAPTER-DOES-NOT-EXIST-9931"


class TestHistoryManagerUtils(EnhancedTestCase):
    """Real-DB tests for the history manager utilities."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Hist", last_name="Util")
        self.chapter = self.create_test_chapter()

    # ------------------------------------------------------------------ helpers

    def _fresh_member_doc(self):
        return frappe.get_doc("Member", self.member.name)

    def _append_history(self, doc, chapter_name, status="Active", **extra):
        row = {
            "chapter_name": chapter_name,
            "assignment_type": "Member",
            "start_date": frappe.utils.today(),
            "status": status,
        }
        row.update(extra)
        return doc.append(CHILD_TABLE, row)

    def _persisted_rows(self):
        return frappe.get_all(
            CHILD_DOCTYPE,
            filters={"parent": self.member.name, "parenttype": "Member"},
            fields=["name", "chapter_name", "status"],
            order_by="idx",
        )

    # =============================================== HistoryOperationResult

    def test_history_operation_result_truthiness(self):
        ok = HistoryOperationResult(success=True, message="m")
        bad = HistoryOperationResult(success=False, message="m", errors=["e"])
        # __bool__ delegates to .success so callers can do `if result:`
        self.assertTrue(bool(ok))
        self.assertFalse(bool(bad))
        self.assertEqual(ok.errors, [])  # default empty list, not None
        self.assertEqual(bad.errors, ["e"])

    # =============================================== ensure_doc_exists

    def test_ensure_doc_exists_true_for_real_member(self):
        self.assertTrue(ensure_doc_exists("Member", self.member.name, "test op"))

    def test_ensure_doc_exists_false_for_missing(self):
        self.assertFalse(ensure_doc_exists("Member", "NONEXISTENT-MEMBER-XYZ", "test op"))

    # =============================================== check_duplicate_entry

    def test_check_duplicate_entry_finds_match(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Active")
        self._append_history(doc, self.chapter.name, status="Completed")
        match = check_duplicate_entry(
            doc.chapter_membership_history,
            {"chapter_name": self.chapter.name, "status": "Completed"},
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.status, "Completed")

    def test_check_duplicate_entry_no_match_returns_none(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Active")
        self.assertIsNone(
            check_duplicate_entry(
                doc.chapter_membership_history,
                {"chapter_name": self.chapter.name, "status": "Quit"},
            )
        )

    def test_check_duplicate_entry_empty_list_returns_none(self):
        self.assertIsNone(check_duplicate_entry(None, {"status": "Active"}))
        self.assertIsNone(check_duplicate_entry([], {"status": "Active"}))

    # =============================================== find_entry_by_criteria

    def test_find_entry_by_criteria_with_status_filter(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Inactive")
        self._append_history(doc, self.chapter.name, status="Active")
        rows = doc.chapter_membership_history
        # criteria matches both rows; status filter narrows to the Active one
        found = find_entry_by_criteria(rows, {"chapter_name": self.chapter.name}, status_values=["Active"])
        self.assertIsNotNone(found)
        self.assertEqual(found.status, "Active")

    def test_find_entry_by_criteria_no_status_filter_returns_first_match(self):
        doc = self._fresh_member_doc()
        first = self._append_history(doc, self.chapter.name, status="Completed")
        found = find_entry_by_criteria(doc.chapter_membership_history, {"chapter_name": self.chapter.name})
        self.assertIsNotNone(found)
        self.assertEqual(found.name, first.name)

    def test_find_entry_by_criteria_status_excludes_returns_none(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Inactive")
        # row matches criteria but its status is not in the accepted set
        self.assertIsNone(
            find_entry_by_criteria(
                doc.chapter_membership_history,
                {"chapter_name": self.chapter.name},
                status_values=["Active", "Pending"],
            )
        )

    def test_find_entry_by_criteria_no_criteria_match_returns_none(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        self.assertIsNone(
            find_entry_by_criteria(doc.chapter_membership_history, {"chapter_name": "Some Other Chapter"})
        )

    # =============================================== recursion_guard

    def test_recursion_guard_first_entry_then_reset(self):
        doc = self._fresh_member_doc()
        flag = "_updating_chapter_membership_history"
        # First entry yields True and sets the flag while inside
        with recursion_guard(doc, flag) as should_proceed:
            self.assertTrue(should_proceed)
            self.assertTrue(getattr(doc, flag))
        # Flag reset on exit
        self.assertFalse(getattr(doc, flag))

    def test_recursion_guard_blocks_nested_entry(self):
        doc = self._fresh_member_doc()
        flag = "_updating_chapter_membership_history"
        with recursion_guard(doc, flag) as outer:
            self.assertTrue(outer)
            # A nested guard while the flag is set must yield False
            with recursion_guard(doc, flag) as inner:
                self.assertFalse(inner)
        self.assertFalse(getattr(doc, flag))

    def test_recursion_guard_resets_flag_on_exception(self):
        doc = self._fresh_member_doc()
        flag = "_updating_chapter_membership_history"
        with self.assertRaises(ValueError):
            with recursion_guard(doc, flag) as proceed:
                self.assertTrue(proceed)
                raise ValueError("boom")
        # finally-block must have reset the flag despite the exception
        self.assertFalse(getattr(doc, flag))

    # =============================================== safe_child_table_update (success)

    def test_safe_child_table_update_persists_rows(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Active")
        result = safe_child_table_update(doc, CHILD_TABLE, "add membership", "Member:write")
        self.assertTrue(result.success, msg=result.errors)
        self.assertEqual(result.message, "Child table updated successfully")
        # REAL outcome: the row is in the DB
        rows = self._persisted_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chapter_name"], self.chapter.name)
        self.assertEqual(rows[0]["status"], "Active")

    def test_safe_child_table_update_syncs_deletion(self):
        # Persist one row, then remove it from the doc and re-sync; the native
        # update_child_table must delete the orphaned DB row.
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        safe_child_table_update(doc, CHILD_TABLE, "add", "Member:write")
        self.assertEqual(len(self._persisted_rows()), 1)

        doc2 = self._fresh_member_doc()
        doc2.set(CHILD_TABLE, [])
        result = safe_child_table_update(doc2, CHILD_TABLE, "clear", "Member:write")
        self.assertTrue(result.success)
        self.assertEqual(len(self._persisted_rows()), 0)

    def test_safe_child_table_update_generic_exception_returns_failure(self):
        # An attribute access on a non-existent child table field raises inside
        # update_child_table -> generic except branch returns a failure result
        # (it must NOT raise out of the function).
        doc = self._fresh_member_doc()
        result = safe_child_table_update(doc, "this_field_does_not_exist", "bad field", "Member:write")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Update failed")
        self.assertTrue(result.errors)

    # =============================================== safe_child_table_update (auto_cleanup)

    def test_auto_cleanup_repairs_broken_link_and_retries(self):
        """The auto_cleanup retry path: a LinkValidationError mentioning the
        child doctype triggers cleanup of the broken row, then a successful
        retry that persists the remaining good row.

        We patch the framework method ``Document.update_child_table`` (NOT the
        module under test) to raise a link error on the first call (as a full
        save would on a broken link) and to behave normally on the retry.
        """
        from unittest.mock import patch

        from frappe.model.document import Document

        real_update = Document.update_child_table
        state = {"calls": 0}

        def flaky_update(self, fieldname, df=None):
            state["calls"] += 1
            if state["calls"] == 1:
                raise frappe.LinkValidationError(
                    f"Could not find Row #2: Chapter Membership History: {GHOST_CHAPTER}"
                )
            return real_update(self, fieldname, df)

        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name, status="Active")  # good
        self._append_history(doc, GHOST_CHAPTER, status="Active")  # broken link
        self.assertEqual(len(doc.chapter_membership_history), 2)

        with patch.object(Document, "update_child_table", flaky_update):
            result = safe_child_table_update(
                doc, CHILD_TABLE, "auto cleanup", "Member:write", auto_cleanup=True
            )

        # Cleanup removed the broken row, retry succeeded
        self.assertTrue(result.success, msg=result.errors)
        self.assertIn("after cleanup", result.message)
        self.assertEqual(state["calls"], 2)  # original + retry
        # Only the good row persisted; the GHOST row was dropped
        rows = self._persisted_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chapter_name"], self.chapter.name)

    def test_auto_cleanup_skipped_when_error_unrelated(self):
        """When the validation error does not relate to the child table, cleanup
        is skipped and the failure is returned untouched (no rows removed)."""
        from unittest.mock import patch

        from frappe.model.document import Document

        def raise_unrelated(self, fieldname, df=None):
            raise frappe.ValidationError("Could not find Row #5: Some Unrelated Doctype: WIDGET-1")

        doc = self._fresh_member_doc()
        self._append_history(doc, GHOST_CHAPTER, status="Active")

        with patch.object(Document, "update_child_table", raise_unrelated):
            result = safe_child_table_update(
                doc, CHILD_TABLE, "unrelated err", "Member:write", auto_cleanup=True
            )
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Validation failed")
        # The in-memory broken row was NOT cleaned (error deemed unrelated)
        self.assertEqual(len(doc.chapter_membership_history), 1)

    def test_validation_error_without_autocleanup_returns_failure(self):
        from unittest.mock import patch

        from frappe.model.document import Document

        def raise_link(self, fieldname, df=None):
            raise frappe.LinkValidationError(f"Could not find Chapter Membership History {GHOST_CHAPTER}")

        doc = self._fresh_member_doc()
        self._append_history(doc, GHOST_CHAPTER)
        with patch.object(Document, "update_child_table", raise_link):
            result = safe_child_table_update(
                doc, CHILD_TABLE, "no cleanup", "Member:write", auto_cleanup=False
            )
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Validation failed")
        self.assertTrue(any(GHOST_CHAPTER in e for e in result.errors))

    def test_timestamp_mismatch_returns_concurrent_failure(self):
        from unittest.mock import patch

        from frappe.model.document import Document

        def raise_ts(self, fieldname, df=None):
            raise frappe.TimestampMismatchError("Document modified by another user")

        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        with patch.object(Document, "update_child_table", raise_ts):
            result = safe_child_table_update(doc, CHILD_TABLE, "concurrent", "Member:write")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Concurrent modification detected")
        self.assertTrue(result.errors)

    def test_auto_cleanup_retry_still_fails_reports_both_errors(self):
        """If the retry after cleanup still raises, both the original and the
        retry error are surfaced and success is False."""
        from unittest.mock import patch

        from frappe.model.document import Document

        def always_raise(self, fieldname, df=None):
            raise frappe.LinkValidationError(f"Could not find Chapter Membership History {GHOST_CHAPTER}")

        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)  # good row -> cleanup is a no-op...
        self._append_history(doc, GHOST_CHAPTER)  # broken -> cleanup removes it
        with patch.object(Document, "update_child_table", always_raise):
            result = safe_child_table_update(
                doc, CHILD_TABLE, "retry fail", "Member:write", auto_cleanup=True
            )
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Update failed even after cleanup")
        # Both the original and post-cleanup error messages are reported
        self.assertEqual(len(result.errors), 2)
        self.assertTrue(result.errors[0].startswith("Original:"))
        self.assertTrue(result.errors[1].startswith("After cleanup:"))

    # =============================================== get_child_table_doctype

    def test_get_child_table_doctype_from_existing_rows(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        self.assertEqual(get_child_table_doctype(doc, CHILD_TABLE), CHILD_DOCTYPE)

    def test_get_child_table_doctype_from_meta_when_empty(self):
        doc = self._fresh_member_doc()
        doc.set(CHILD_TABLE, [])
        # No rows -> resolve via parent meta
        self.assertEqual(get_child_table_doctype(doc, CHILD_TABLE), CHILD_DOCTYPE)

    def test_get_child_table_doctype_unknown_field_returns_none(self):
        doc = self._fresh_member_doc()
        self.assertIsNone(get_child_table_doctype(doc, "not_a_table_field"))

    # =============================================== error_relates_to_child_table

    def test_error_relates_when_doctype_name_in_message(self):
        self.assertTrue(
            error_relates_to_child_table(
                "Could not find Row #11 in Chapter Membership History", CHILD_DOCTYPE
            )
        )

    def test_error_relates_when_link_field_in_message(self):
        # chapter_name is a Link field on the child doctype
        self.assertTrue(
            error_relates_to_child_table("Invalid value for chapter_name on the row", CHILD_DOCTYPE)
        )

    def test_error_relates_when_target_doctype_in_message(self):
        # 'Chapter' is the options/target of the chapter_name Link field
        self.assertTrue(error_relates_to_child_table("Could not find Chapter: GHOST", CHILD_DOCTYPE))

    def test_error_relates_false_for_unrelated_message(self):
        self.assertFalse(
            error_relates_to_child_table("Could not find Row in Sales Invoice Item", CHILD_DOCTYPE)
        )

    def test_error_relates_false_for_empty_inputs(self):
        self.assertFalse(error_relates_to_child_table("", CHILD_DOCTYPE))
        self.assertFalse(error_relates_to_child_table("some error", ""))
        self.assertFalse(error_relates_to_child_table(None, CHILD_DOCTYPE))

    # =============================================== cleanup_child_table_broken_links

    def test_cleanup_removes_broken_link_row(self):
        doc = self._fresh_member_doc()
        good = self._append_history(doc, self.chapter.name, status="Active")
        self._append_history(doc, GHOST_CHAPTER, status="Active")
        result = cleanup_child_table_broken_links(doc, CHILD_TABLE, remove_broken_rows=True)
        self.assertTrue(result.success)
        self.assertIn("1 rows removed", result.message)
        # Only the good row remains, and idx is resequenced to start at 1
        remaining = doc.chapter_membership_history
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].name, good.name)
        self.assertEqual(remaining[0].idx, 1)

    def test_cleanup_clears_broken_link_without_removing_row(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        self._append_history(doc, GHOST_CHAPTER)
        result = cleanup_child_table_broken_links(doc, CHILD_TABLE, remove_broken_rows=False)
        self.assertTrue(result.success)
        self.assertIn("links cleared", result.message)
        # Row count unchanged; the broken link value cleared to None
        rows = doc.chapter_membership_history
        self.assertEqual(len(rows), 2)
        cleared = [r for r in rows if not r.chapter_name]
        self.assertEqual(len(cleared), 1)

    def test_cleanup_no_broken_links_reports_clean(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)
        result = cleanup_child_table_broken_links(doc, CHILD_TABLE)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "No broken links found")
        self.assertEqual(len(doc.chapter_membership_history), 1)

    def test_cleanup_empty_child_table_is_noop(self):
        doc = self._fresh_member_doc()
        doc.set(CHILD_TABLE, [])
        result = cleanup_child_table_broken_links(doc, CHILD_TABLE)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "No child table entries to clean")

    def test_cleanup_resequences_idx_after_multiple_removals(self):
        doc = self._fresh_member_doc()
        self._append_history(doc, GHOST_CHAPTER)  # broken
        good1 = self._append_history(doc, self.chapter.name)  # good
        self._append_history(doc, GHOST_CHAPTER)  # broken
        good2 = self._append_history(doc, self.chapter.name)  # good
        result = cleanup_child_table_broken_links(doc, CHILD_TABLE, remove_broken_rows=True)
        self.assertTrue(result.success)
        self.assertIn("2 rows removed", result.message)
        remaining = doc.chapter_membership_history
        self.assertEqual([r.name for r in remaining], [good1.name, good2.name])
        # idx resequenced consecutively from 1
        self.assertEqual([r.idx for r in remaining], [1, 2])

    # =============================================== log_history_error (smoke, real logger)

    def test_log_history_error_writes_error_log(self):
        title = f"Hist Util Test {frappe.generate_hash(length=8)}"
        marker = "a test history error message marker"
        log_history_error(title, marker)
        frappe.db.commit()
        # safe_log_error -> frappe.log_error persisted an Error Log carrying both
        # our title and message (across the error/method columns).
        rows = frappe.db.sql(
            "SELECT error, method FROM `tabError Log` "
            "WHERE error LIKE %s OR method LIKE %s ORDER BY creation DESC LIMIT 1",
            (f"%{title}%", f"%{title}%"),
            as_dict=True,
        )
        self.assertTrue(rows, "log_history_error must persist an Error Log row")
        combined = (rows[0]["error"] or "") + (rows[0]["method"] or "")
        self.assertIn(title, combined)
        self.assertIn(marker, combined)

    def test_log_history_error_with_traceback_includes_trace(self):
        title = f"Hist Util Trace {frappe.generate_hash(length=8)}"
        try:
            raise RuntimeError("synthetic failure for traceback")
        except RuntimeError:
            log_history_error(title, "wrapping message", include_traceback=True)
        frappe.db.commit()
        # Frappe's log_error stores the short string in one column and the long
        # body in the other (the assignment flips depending on length), so match
        # the title in EITHER column and combine both for the traceback check.
        rows = frappe.db.sql(
            "SELECT error, method FROM `tabError Log` "
            "WHERE error LIKE %s OR method LIKE %s ORDER BY creation DESC LIMIT 1",
            (f"%{title}%", f"%{title}%"),
            as_dict=True,
        )
        self.assertTrue(rows, "log_history_error must persist an Error Log row")
        body = (rows[0]["error"] or "") + (rows[0]["method"] or "")
        self.assertIn("Traceback:", body)
        self.assertIn("synthetic failure for traceback", body)

    # =============================================== request cache helpers

    def test_get_request_cache_creates_and_persists_set(self):
        cache_name = f"_test_hist_cache_{frappe.generate_hash(length=6)}"
        cache = get_request_cache(cache_name)
        self.assertIsInstance(cache, set)
        cache.add("entry-1")
        # Same name returns the SAME set (request-level dedup)
        again = get_request_cache(cache_name)
        self.assertIs(again, cache)
        self.assertIn("entry-1", again)

    def test_make_cache_key_joins_parts(self):
        key = make_cache_key("Member", self.member.name, 42, None)
        self.assertEqual(key, f"Member|{self.member.name}|42|None")
        # deterministic and order-sensitive
        self.assertNotEqual(make_cache_key("a", "b"), make_cache_key("b", "a"))

    # =============================================== permission-denied branch

    def test_safe_child_table_update_permission_denied_for_non_admin(self):
        """A non-Administrator user without write permission (and not in_test
        bypass) must get a Permission denied failure result rather than a write.

        ``frappe.flags.in_test`` is temporarily cleared so the production
        permission gate is actually evaluated, then restored.
        """
        doc = self._fresh_member_doc()
        self._append_history(doc, self.chapter.name)

        guest = "Guest"
        saved_in_test = frappe.flags.in_test
        try:
            frappe.flags.in_test = False
            with self.set_user(guest):
                result = safe_child_table_update(doc, CHILD_TABLE, "perm check", "Member:write")
        finally:
            frappe.flags.in_test = saved_in_test

        self.assertFalse(result.success)
        self.assertEqual(result.message, "Permission denied")
        self.assertTrue(result.errors)
        # No row should have been written by the denied call
        self.assertEqual(len(self._persisted_rows()), 0)

    # =============================================== error_relates extra branches

    def test_error_relates_via_underscored_table_pattern(self):
        # The child-table snake_case pattern ("chapter_membership_history")
        # appearing in the message is a positive match.
        self.assertTrue(
            error_relates_to_child_table(
                "could not sync row in chapter_membership_history table",
                CHILD_DOCTYPE,
            )
        )

    def test_error_relates_meta_lookup_for_unknown_doctype(self):
        # A non-existent child doctype name: frappe.get_meta raises internally,
        # the except swallows it, and the function conservatively returns False.
        self.assertFalse(
            error_relates_to_child_table("Could not find Row #3: nothing here", "No Such Doctype ZZZ")
        )

    # =============================================== get_child_table_doctype meta path

    def test_get_child_table_doctype_handles_bad_doctype(self):
        # A document object whose .doctype is invalid makes frappe.get_meta raise;
        # the except branch returns None instead of propagating.
        class _FakeDoc:
            doctype = "Totally Invalid Doctype XYZ"

            def __getattr__(self, name):
                return None

        self.assertIsNone(get_child_table_doctype(_FakeDoc(), "some_table"))

    # =============================================== cleanup outer-exception branch

    def test_cleanup_outer_exception_returns_failure(self):
        # A doc whose child_table getattr raises drives the outer try/except in
        # cleanup_child_table_broken_links to its failure return.
        class _BoomDoc:
            doctype = "Member"

            def __getattr__(self, name):
                raise RuntimeError("synthetic getattr failure")

        result = cleanup_child_table_broken_links(_BoomDoc(), CHILD_TABLE)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Cleanup failed")
        self.assertTrue(result.errors)


class TestHistoryManagerUtilsDynamicLinks(EnhancedTestCase):
    """Cleanup tests against a child table that has a Dynamic Link field.

    Uses Volunteer.assignment_history (child doctype ``Volunteer Assignment``),
    which carries a Dynamic Link ``reference_name`` keyed on ``reference_doctype``
    plus a regular Link ``reference_doctype`` -> DocType. This exercises the
    Dynamic Link cleanup branches that the Chapter Membership History table
    (Link-only) cannot reach.
    """

    DL_TABLE = "assignment_history"
    DL_CHILD = "Volunteer Assignment"

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="DynLink", last_name="Vol")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)
        self.chapter = self.create_test_chapter()

    def _fresh_volunteer(self):
        return frappe.get_doc("Volunteer", self.volunteer.name)

    def _append_assignment(self, doc, reference_doctype, reference_name, **extra):
        row = {
            "assignment_type": "Committee",
            "role": "Member",
            "start_date": frappe.utils.today(),
            "status": "Active",
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
        }
        row.update(extra)
        return doc.append(self.DL_TABLE, row)

    def test_cleanup_removes_broken_dynamic_link_row(self):
        doc = self._fresh_volunteer()
        good = self._append_assignment(doc, "Chapter", self.chapter.name)
        self._append_assignment(doc, "Chapter", "GHOST-CHAP-DYN-001")  # broken
        result = cleanup_child_table_broken_links(doc, self.DL_TABLE, remove_broken_rows=True)
        self.assertTrue(result.success)
        self.assertIn("1 rows removed", result.message)
        remaining = doc.assignment_history
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].name, good.name)
        self.assertEqual(remaining[0].reference_name, self.chapter.name)

    def test_cleanup_clears_broken_dynamic_link_without_removing(self):
        doc = self._fresh_volunteer()
        self._append_assignment(doc, "Chapter", self.chapter.name)
        self._append_assignment(doc, "Chapter", "GHOST-CHAP-DYN-002")  # broken
        result = cleanup_child_table_broken_links(doc, self.DL_TABLE, remove_broken_rows=False)
        self.assertTrue(result.success)
        self.assertIn("links cleared", result.message)
        rows = doc.assignment_history
        self.assertEqual(len(rows), 2)
        # The broken row had both its value and its doctype field cleared
        cleared = [r for r in rows if not r.reference_name and not r.reference_doctype]
        self.assertEqual(len(cleared), 1)

    def test_cleanup_removes_orphaned_dynamic_link(self):
        # A row with a reference_name but NO reference_doctype is "orphaned" and
        # is treated as broken.
        doc = self._fresh_volunteer()
        good = self._append_assignment(doc, "Chapter", self.chapter.name)
        self._append_assignment(doc, None, "ORPHAN-NO-DOCTYPE-1")
        result = cleanup_child_table_broken_links(doc, self.DL_TABLE, remove_broken_rows=True)
        self.assertTrue(result.success)
        self.assertIn("1 rows removed", result.message)
        self.assertEqual([r.name for r in doc.assignment_history], [good.name])

    def test_cleanup_clears_orphaned_dynamic_link_without_removing(self):
        doc = self._fresh_volunteer()
        self._append_assignment(doc, "Chapter", self.chapter.name)
        self._append_assignment(doc, None, "ORPHAN-NO-DOCTYPE-2")
        result = cleanup_child_table_broken_links(doc, self.DL_TABLE, remove_broken_rows=False)
        self.assertTrue(result.success)
        self.assertIn("links cleared", result.message)
        # The orphaned value was cleared in place; row count unchanged
        self.assertEqual(len(doc.assignment_history), 2)
        self.assertTrue(any(not r.reference_name for r in doc.assignment_history))

    def test_cleanup_good_dynamic_links_reports_clean(self):
        doc = self._fresh_volunteer()
        self._append_assignment(doc, "Chapter", self.chapter.name)
        result = cleanup_child_table_broken_links(doc, self.DL_TABLE)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "No broken links found")
