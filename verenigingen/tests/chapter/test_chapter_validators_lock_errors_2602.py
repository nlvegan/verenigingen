"""#2602: the Chapter save validators must not swallow a 1213/1205.

After a 1213 MariaDB has already rolled the whole transaction back. A validator that falls back
to a default (``except Exception: pass``) lets ``Chapter.save()`` return normally on a transaction
the server discarded; the caller's next savepoint operation then raises 1305.

The lock error is injected, not provoked (a real deadlock needs a second connection racing the same
rows), by raising the exact class Frappe raises for 1213/1205 at the Singles / Chapter Role read.
Every test runs the real ``Chapter.save``. Because other code on the save path reads the same Single,
each test also asserts the error surfaced FROM the validator under test: a raise from a neighbour
would otherwise make the test pass without the fix.
"""

import traceback
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SETTINGS = "Verenigingen Settings"
REAL_GET_SINGLE = frappe.get_single
REAL_GET_ALL = frappe.get_all
LOCK_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)


def _raising_get_single(error):
    def get_single(doctype, *args, **kwargs):
        if doctype == SETTINGS:
            raise error("lock")
        return REAL_GET_SINGLE(doctype, *args, **kwargs)

    return get_single


def _raising_get_all(error):
    def get_all(doctype, *args, **kwargs):
        if doctype == "Chapter Role":
            raise error("lock")
        return REAL_GET_ALL(doctype, *args, **kwargs)

    return get_all


def _saved_frames(chapter, error):
    """Names of the frames the lock error travelled through, or None if save() did not raise it.

    assertRaises strips ``__traceback__``, so the raise is caught by hand. The chapter is reloaded
    first: a save that failed once leaves the in-memory doc modified-stamped for the next attempt.
    """
    chapter.reload()
    try:
        chapter.save()
    except error as exc:
        return {f.name for f in traceback.extract_tb(exc.__traceback__)}
    return None


class TestChapterValidatorsLockErrors2602(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"LockErr Chapter {frappe.generate_hash(length=6)}"
        )
        self.create_test_board_member(self.chapter.name)
        self.chapter.reload()


    def _assert_save_raises_from(self, target, factory, helper_name):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch(target, side_effect=factory(error)):
                    frames = _saved_frames(self.chapter, error)
                self.assertIsNotNone(frames, f"save() did not raise {error.__name__}")
                self.assertIn(helper_name, frames)

    def test_region_lookup_lock_error_aborts_the_save(self):
        self._assert_save_raises_from("frappe.get_single", _raising_get_single, "_get_valid_regions")

    def test_board_setting_lock_error_aborts_the_save(self):
        # _get_setting exists on both the board and the postal validator; either aborts the save.
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch("frappe.get_single", side_effect=_raising_get_single(error)):
                    frames = _saved_frames(self.chapter, error)
                self.assertIsNotNone(frames, f"save() did not raise {error.__name__}")
                self.assertTrue({"_get_setting", "_get_valid_regions"} & frames)

    def test_board_setting_lock_error_aborts_even_with_region_read_skipped(self):
        """Isolates BoardMemberValidator._get_setting from the earlier region read."""
        from verenigingen.verenigingen.doctype.chapter.validators.chapter_info_validator import (
            ChapterInfoValidator,
        )

        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch.object(ChapterInfoValidator, "_get_valid_regions", return_value=None), patch(
                    "frappe.get_single", side_effect=_raising_get_single(error)
                ):
                    frames = _saved_frames(self.chapter, error)
                self.assertIsNotNone(frames, f"save() did not raise {error.__name__}")
                self.assertIn("_get_setting", frames)

    def test_unique_roles_lock_error_aborts_the_save(self):
        self._assert_save_raises_from("frappe.get_all", _raising_get_all, "_get_unique_roles")

    def test_postal_setting_lock_error_is_not_swallowed(self):
        from verenigingen.verenigingen.doctype.chapter.validators.postal_code_validator import (
            PostalCodeValidator,
        )

        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch("frappe.get_single", side_effect=_raising_get_single(error)):
                    with self.assertRaises(error):
                        PostalCodeValidator(self.chapter).validate_postal_codes("1000-1999")

    def test_event_emission_lock_error_aborts_the_save(self):
        """Chapter.on_update's ``_emit_chapter_change_events`` logged and carried on."""
        target = (
            "verenigingen.services.chapter.chapter_event_service."
            "ChapterEventService.detect_and_emit_settings_changes"
        )
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                self.chapter.reload()
                with patch(target, side_effect=error("lock")):
                    with self.assertRaises(error):
                        self.chapter.save()

    # ------------------------------------------------------------ controls: the fallbacks still apply

    def test_ordinary_settings_error_still_falls_back_and_the_save_succeeds(self):
        with patch("frappe.get_single", side_effect=_raising_get_single(RuntimeError)):
            self.chapter.save()  # every validator falls back to its default

    def test_ordinary_error_reading_unique_roles_still_falls_back(self):
        self.expectErrorLog("Error fetching unique roles")
        from verenigingen.verenigingen.doctype.chapter.validators.board_member_validator import (
            BoardMemberValidator,
        )

        validator = BoardMemberValidator(self.chapter)
        target = "frappe.get_all"
        with self.assertErrorLog("Error fetching unique roles"):
            with patch(target, side_effect=_raising_get_all(RuntimeError)):
                self.assertEqual(validator._get_unique_roles(), set())

    def test_ordinary_error_in_event_emission_is_still_logged_not_raised(self):
        self.expectErrorLog("Chapter Event Emission Error")
        target = (
            "verenigingen.services.chapter.chapter_event_service."
            "ChapterEventService.detect_and_emit_settings_changes"
        )
        with self.assertErrorLog("Chapter Event Emission Error"):
            with patch(target, side_effect=RuntimeError("boom")):
                self.chapter.save()
