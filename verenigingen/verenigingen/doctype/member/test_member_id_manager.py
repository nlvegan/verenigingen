"""Integration tests for member_id_manager.py — the CANONICAL member ID generator.

Covers MemberIDManager (atomic counter via tabSingles + FOR UPDATE), the
validate_member_id_change hook, and the four whitelisted admin endpoints used by
the Member Counter page (member_counter.js).

These tests assert real behaviour (monotonic assignment, uniqueness, self-heal,
guard branches) against real Member documents and the live Verenigingen Settings
single. No business logic is mocked.
"""


import frappe
from frappe.utils import cint

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member.member_id_manager import (
    MemberIDManager,
    get_member_id_statistics,
    get_next_member_id_preview,
    migrate_member_id_counter,
    reset_member_id_counter,
    validate_member_id_change,
)

COUNTER_KEY = "member_id_counter"
DOCTYPE = "Verenigingen Settings"
FIELD = "last_member_id"


class TestMemberIDManager(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers
    def _get_singles_counter(self):
        """Read the persisted counter directly from tabSingles."""
        row = frappe.db.sql(
            "SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s",
            (DOCTYPE, FIELD),
            as_dict=True,
        )
        return cint(row[0].value) if row and row[0].value is not None else None

    def _set_singles_counter(self, value):
        """Privileged setup: force the persisted counter to a known value."""
        frappe.db.sql(
            "UPDATE `tabSingles` SET value=%s WHERE doctype=%s AND field=%s",
            (value, DOCTYPE, FIELD),
        )

    def _make_member_with_id(self, member_id):
        """Privileged setup: create a real Member carrying an explicit member_id."""
        member = self.create_test_member()
        member.db_set("member_id", str(member_id), update_modified=False)
        member.reload()
        return member

    # as_user() removed (#496): it shadowed EnhancedTestCase.as_user(user_email),
    # and was equivalent to it (restore-on-exit via a context manager). Deleted
    # rather than renamed since there was nothing local about it to preserve.

    # ------------------------------------------------- get_next_member_id (core)
    def test_get_next_member_id_is_monotonic(self):
        first = MemberIDManager.get_next_member_id()
        second = MemberIDManager.get_next_member_id()
        third = MemberIDManager.get_next_member_id()
        self.assertEqual(second, first + 1)
        self.assertEqual(third, second + 1)

    def test_get_next_member_id_persists_to_singles(self):
        assigned = MemberIDManager.get_next_member_id()
        # The persisted counter is advanced to the value just handed out.
        self.assertEqual(self._get_singles_counter(), assigned)

    def test_get_next_member_id_updates_cache(self):
        assigned = MemberIDManager.get_next_member_id()
        self.assertEqual(cint(frappe.cache().get(COUNTER_KEY)), assigned)

    def test_get_next_member_id_advances_from_stored_value(self):
        self._set_singles_counter(50000)
        assigned = MemberIDManager.get_next_member_id()
        # Self-heal can only push the value UP (max of stored and real data),
        # never below the stored counter.
        self.assertGreaterEqual(assigned, 50001)

    def test_get_next_member_id_self_heals_when_counter_drifts_behind(self):
        """If a member exists above the stored counter, the next id must clear it."""
        high = self._get_singles_counter() or 1000
        high = max(high, MemberIDManager._get_max_numeric_member_id()) + 5000
        member = self._make_member_with_id(high)
        # Force the stored counter to lag behind the real data.
        self._set_singles_counter(high - 100)
        assigned = MemberIDManager.get_next_member_id()
        self.assertEqual(assigned, high + 1)
        self.assertNotEqual(str(assigned), member.member_id)

    # -------------------------------------------------------- internal scanners
    def test_get_max_numeric_member_id_reflects_real_data(self):
        baseline = MemberIDManager._get_max_numeric_member_id()
        target = baseline + 7777
        self._make_member_with_id(target)
        self.assertEqual(MemberIDManager._get_max_numeric_member_id(), target)

    def test_get_max_numeric_member_id_ignores_non_numeric(self):
        baseline = MemberIDManager._get_max_numeric_member_id()
        # The factory assigns TEST-prefixed (non-numeric) ids; they must be
        # excluded by the REGEXP '^[0-9]+$' filter and never inflate the max.
        m = self.create_test_member()
        self.assertFalse(str(m.member_id).isdigit())
        self.assertEqual(MemberIDManager._get_max_numeric_member_id(), baseline)

    def test_initialize_counter_prefers_existing_data_over_settings(self):
        target = MemberIDManager._get_max_numeric_member_id() + 8888
        self._make_member_with_id(target)
        # With real numeric data present, init returns the max id, not the
        # settings start value.
        self.assertEqual(MemberIDManager._initialize_counter(), target)

    # ----------------------------------------------- generated ids are unique
    def test_generated_ids_are_unique_across_calls(self):
        ids = {MemberIDManager.get_next_member_id() for _ in range(10)}
        self.assertEqual(len(ids), 10)

    # --------------------------------------------- validate_member_id_change hook
    def test_validate_allows_new_local_document(self):
        doc = frappe.new_doc("Member")
        doc.member_id = "123456"
        # __islocal short-circuits — no role required, no exception.
        validate_member_id_change(doc)

    def test_validate_skips_counter_system_document(self):
        doc = frappe.new_doc("Member")
        doc.name = "MEMBER-COUNTER-SYSTEM"
        doc.flags.pop("__islocal", None)
        # Should return early even though name-based guard is hit.
        validate_member_id_change(doc)

    def test_validate_noop_when_member_id_unchanged(self):
        member = self.create_test_member()
        member.first_name = member.first_name + "X"
        # member_id not touched -> has_value_changed("member_id") is False ->
        # no role check, no throw.
        validate_member_id_change(member)

    def test_validate_blocks_duplicate_member_id(self):
        existing = self._make_member_with_id(MemberIDManager.get_next_member_id())
        victim = self.create_test_member()
        victim.member_id = existing.member_id  # collide with an in-use id
        # Running as Administrator (System Manager) clears the role gate, so we
        # reach the uniqueness check, which must reject the duplicate.
        with self.assertRaises(frappe.ValidationError):
            validate_member_id_change(victim)

    def test_validate_blocks_change_for_non_system_manager(self):
        member = self._make_member_with_id(MemberIDManager.get_next_member_id())
        member.member_id = str(MemberIDManager.get_next_member_id())
        with self.as_user("Guest"):
            # frappe.throw() raises ValidationError; the message identifies the
            # System-Manager-only guard.
            with self.assertRaises(frappe.ValidationError):
                validate_member_id_change(member)

    # -------------------------------------------- whitelisted: preview endpoint
    def test_preview_does_not_increment_counter(self):
        before = self._get_singles_counter()
        result = get_next_member_id_preview()
        after = self._get_singles_counter()
        self.assertEqual(before, after)
        self.assertIn("next_id", result)
        self.assertIn("current_counter", result)
        self.assertEqual(result["next_id"], result["current_counter"] + 1)

    def test_preview_survives_bytes_cache_value(self):
        """Regression: frappe.cache().get() returns bytes; preview must coerce.

        Before the fix this raised TypeError: can't concat int to bytes whenever
        any member id had been generated (which sets the cache key).
        """
        MemberIDManager.get_next_member_id()  # populates cache with bytes
        self.assertIsInstance(frappe.cache().get(COUNTER_KEY), (bytes, bytearray))
        result = get_next_member_id_preview()  # must not raise
        self.assertIsInstance(result["current_counter"], int)
        self.assertEqual(result["next_id"], result["current_counter"] + 1)

    # ----------------------------------------- whitelisted: statistics endpoint
    def test_statistics_reports_real_counts(self):
        MemberIDManager.get_next_member_id()  # ensure cache has a bytes value
        target = MemberIDManager._get_max_numeric_member_id() + 9999
        self._make_member_with_id(target)
        stats = get_member_id_statistics()
        self.assertGreaterEqual(stats["highest_assigned"], target)
        self.assertGreaterEqual(stats["total_with_numeric_ids"], 1)
        self.assertEqual(stats["next_id"], stats["current_counter"] + 1)
        self.assertIsInstance(stats["gaps"], list)
        self.assertGreaterEqual(stats["gap_count"], 0)

    def test_statistics_survives_bytes_cache_value(self):
        """Regression: statistics must coerce the bytes cache value too."""
        MemberIDManager.get_next_member_id()
        self.assertIsInstance(frappe.cache().get(COUNTER_KEY), (bytes, bytearray))
        stats = get_member_id_statistics()  # must not raise
        self.assertIsInstance(stats["current_counter"], int)

    # ------------------------------------------- whitelisted: reset endpoint
    def test_reset_counter_rejects_non_positive(self):
        with self.assertRaises(frappe.ValidationError):
            reset_member_id_counter(0)
        with self.assertRaises(frappe.ValidationError):
            reset_member_id_counter(-5)

    def test_reset_counter_rejects_below_minimum(self):
        start = cint(frappe.db.get_single_value(DOCTYPE, "member_id_start")) or 1000
        # A positive value below the configured minimum must be rejected by
        # MemberIDManager.reset_counter().
        if start > 1:
            with self.assertRaises(frappe.ValidationError):
                reset_member_id_counter(start - 1)

    def test_reset_counter_sets_cache(self):
        start = cint(frappe.db.get_single_value(DOCTYPE, "member_id_start")) or 1000
        # Choose a value at/above the minimum AND above current data to avoid the
        # conflict warning path having side effects.
        target = max(start, MemberIDManager._get_max_numeric_member_id()) + 100000
        result = reset_member_id_counter(target)
        self.assertTrue(result["success"])
        self.assertEqual(cint(frappe.cache().get(COUNTER_KEY)), target)

    def test_reset_counter_blocks_non_system_manager(self):
        with self.as_user("Guest"):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                reset_member_id_counter(99999)

    # -------------------------------------- whitelisted: migrate endpoint
    def test_migrate_counter_survives_bytes_cache_value(self):
        """Regression: migrate -> sync_counter_with_settings compared int>bytes.

        Before the fix this raised TypeError: '>' not supported between
        instances of 'int' and 'bytes'.
        """
        MemberIDManager.get_next_member_id()  # cache now holds bytes
        result = migrate_member_id_counter()  # must not raise
        self.assertTrue(result["success"])

    def test_sync_counter_raises_to_settings_when_higher(self):
        start = cint(frappe.db.get_single_value(DOCTYPE, "member_id_start")) or 1000
        # Seed the cache with a value BELOW the settings start so sync should
        # raise it up to the start value.
        frappe.cache().set(COUNTER_KEY, start - 50 if start > 50 else 1)
        MemberIDManager.sync_counter_with_settings()
        self.assertGreaterEqual(cint(frappe.cache().get(COUNTER_KEY)), start)


class TestMemberIDStartMovesCounter(EnhancedTestCase):
    """#2261: raising ``member_id_start`` moves the REAL counter (ruling 2026-11-09).

    The change goes through a real ``Verenigingen Settings.save()`` and the ids
    come from the real issuing path (``get_next_member_id`` and a real Member
    insert). Only setup writes (``_preset``) go straight to tabSingles, to put
    the start/counter at a known value without firing the hook.
    """

    def setUp(self):
        super().setUp()
        self._saved_start = frappe.db.get_single_value(DOCTYPE, "member_id_start")
        row = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s", (DOCTYPE, FIELD))
        self._saved_counter = row[0][0] if row else None
        self._saved_cache = frappe.cache().get(COUNTER_KEY)
        self.max_id = MemberIDManager._get_max_numeric_member_id()

    def tearDown(self):
        # Settings.on_update commits (sync_category_options_to_doctypes), so every
        # save in these tests is COMMITTED, and a cleanup run after tearDown would
        # restore nothing durable. Restore here and commit it, then prove it.
        frappe.db.set_single_value(DOCTYPE, "member_id_start", self._saved_start)
        if self._saved_counter is not None:
            frappe.db.sql(
                "UPDATE `tabSingles` SET value=%s WHERE doctype=%s AND field=%s",
                (self._saved_counter, DOCTYPE, FIELD),
            )
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)
        frappe.db.commit()
        if self._saved_cache is None:
            frappe.cache().delete_value(COUNTER_KEY)
        else:
            frappe.cache().set(COUNTER_KEY, cint(self._saved_cache))
        self.assertEqual(frappe.db.get_single_value(DOCTYPE, "member_id_start"), self._saved_start)
        self.assertEqual(self._counter(), cint(self._saved_counter))
        super().tearDown()

    def _preset(self, start, counter):
        frappe.db.set_single_value(DOCTYPE, "member_id_start", start)
        frappe.db.sql(
            "UPDATE `tabSingles` SET value=%s WHERE doctype=%s AND field=%s", (counter, DOCTYPE, FIELD)
        )
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)

    def _counter(self):
        row = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s", (DOCTYPE, FIELD))
        return cint(row[0][0])

    def _save_start(self, value):
        settings = frappe.get_doc(DOCTYPE)
        settings.member_id_start = value
        settings.save()

    def test_raising_start_above_max_moves_counter_so_next_id_clears_it(self):
        old_start = self.max_id + 10
        new_start = self.max_id + 5000
        self._preset(old_start, self.max_id)
        self._save_start(new_start)
        self.assertEqual(self._counter(), new_start)
        # The counter holds the last assigned id, so the first new id is start + 1.
        self.assertEqual(MemberIDManager.get_next_member_id(), new_start + 1)

    def test_raising_start_gives_a_real_member_an_id_above_it(self):
        new_start = self.max_id + 7000
        self._preset(self.max_id + 10, self.max_id)
        self._save_start(new_start)
        member = self.create_test_member()
        # Probe shortcut: the factory pins a non-numeric member_id, so clear it
        # and let the REAL service (ensure_member_id -> get_next_member_id) number it.
        member.db_set("member_id", None, update_modified=False)
        member.reload()
        # The whitelisted wrapper serialises the OperationResult to a dict.
        self.assertTrue(member.ensure_member_id()["success"])
        member.reload()
        self.assertEqual(cint(member.member_id), new_start + 1)

    def test_raising_start_keeps_the_display_cache_consistent(self):
        new_start = self.max_id + 6000
        self._preset(self.max_id + 10, self.max_id)
        frappe.cache().set(COUNTER_KEY, self.max_id)
        self._save_start(new_start)
        self.assertEqual(cint(frappe.cache().get(COUNTER_KEY)), new_start)

    def test_lowering_start_does_not_move_the_counter(self):
        counter = self.max_id + 3000
        self._preset(counter + 500, counter)
        self._save_start(self.max_id + 10)  # a real change, downwards
        self.assertEqual(self._counter(), counter)
        self.assertEqual(MemberIDManager.get_next_member_id(), counter + 1)

    def test_raising_start_below_the_counter_does_not_move_it_down(self):
        counter = self.max_id + 9000
        self._preset(self.max_id + 10, counter)
        self._save_start(counter - 100)  # a real raise, but still below the counter
        self.assertEqual(self._counter(), counter)
        self.assertEqual(MemberIDManager.get_next_member_id(), counter + 1)

    def test_raising_start_below_existing_member_ids_does_not_move_counter(self):
        # The stored counter LAGS the data (self-heal case): the sync must see the
        # member id, not just the stored value, or it would drop the counter.
        member = self.create_test_member()
        top = self.max_id + 20000
        member.db_set("member_id", str(top), update_modified=False)
        self._preset(self.max_id + 10, top - 1000)
        self._save_start(top - 50)  # a real raise, above the stored counter, below the data
        self.assertGreaterEqual(self._counter(), top - 1000)
        self.assertNotEqual(self._counter(), top - 50)
        self.assertEqual(MemberIDManager.get_next_member_id(), top + 1)


class TestStaleSettingsSaveKeepsCounter(TestMemberIDStartMovesCounter):
    """#2316: a Settings doc loaded BEFORE ids were issued must not roll the counter back.

    ``last_member_id`` is a read-only field of the Settings Single, and a Single save
    rewrites every field from the in-memory doc. The ids are issued through the real
    ``get_next_member_id``; the stale doc is a real ``frappe.get_doc`` loaded earlier.
    Setup/teardown inherit the committed restore from the parent class (Settings.on_update
    commits mid-save). Subclassing re-runs the parent's tests too, which is intended.
    """

    def _stale_doc_then_issue(self, issued=3):
        counter = self.max_id + 400
        self._preset(self.max_id + 10, counter)
        stale = frappe.get_doc(DOCTYPE)  # the "form loaded in a browser tab"
        self.assertEqual(cint(stale.last_member_id), counter)
        last = [MemberIDManager.get_next_member_id() for _ in range(issued)][-1]
        self.assertEqual(last, counter + issued)
        return stale, last

    def test_stale_save_does_not_roll_the_counter_back(self):
        stale, last = self._stale_doc_then_issue()
        stale.save()
        self.assertEqual(self._counter(), last)
        self.assertEqual(MemberIDManager.get_next_member_id(), last + 1)

    def test_stale_save_raising_start_moves_counter_to_start_not_back(self):
        stale, last = self._stale_doc_then_issue()
        stale.member_id_start = last + 5000  # raise above the counter
        stale.save()
        self.assertEqual(self._counter(), last + 5000)
        self.assertEqual(MemberIDManager.get_next_member_id(), last + 5001)

    def test_stale_save_lowering_start_keeps_the_issued_counter(self):
        stale, last = self._stale_doc_then_issue()
        stale.member_id_start = 1  # lowering does nothing
        stale.save()
        self.assertEqual(self._counter(), last)
        self.assertEqual(MemberIDManager.get_next_member_id(), last + 1)
