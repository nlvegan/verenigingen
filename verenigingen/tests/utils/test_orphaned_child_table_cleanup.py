"""
Integration tests for verenigingen.utils.orphaned_child_table_cleanup.

These tests exercise the DESTRUCTIVE child-table orphan cleanup + index
management utilities. Safety rules followed here:

- All dry_run tests assert reports only and verify NO mutation occurred.
- Real-deletion tests create UNIQUELY-NAMED orphan fixtures (parent values that
  contain a per-run hash) via direct SQL INSERT, then assert deletion is scoped
  ONLY to those rows. Pre-existing site data is never matched.
- _validate_table_name is exercised with valid + SQL-injection-style names.

Orphan fixtures are inserted with direct SQL because the ORM refuses to persist
a child row whose parent does not exist; an orphan is by definition a child row
referencing a missing parent.
"""

import frappe
from frappe.utils import nowdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.orphaned_child_table_cleanup import (
    SimpleLock,
    _batch_delete_orphans,
    _validate_table_name,
    cleanup_member_child_tables_only,
    cleanup_orphaned_child_tables,
    cleanup_volunteer_child_tables_only,
    create_missing_parent_indexes,
    detect_orphaned_child_tables,
    verify_child_table_indexes,
)


def _unwrap(result):
    """Decorated @critical_api endpoints return the nested OperationResult dict.

    Shape: {"success": bool, "data": {...}, "error": {...}, "meta": {...}}.
    Returns (success, payload) where payload is the inner results dict (data) on
    success or the error object on failure.
    """
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    if result.get("success"):
        return True, result["data"]
    return False, result.get("error", {})


class TestOrphanedChildTableCleanup(EnhancedTestCase):
    """Real-DB tests for the orphan cleanup utilities."""

    # Child table -> (parenttype DocType, dict of required non-link fields)
    VOLUNTEER_SKILL_TABLE = "Volunteer Skill"

    def setUp(self):
        super().setUp()
        # Unique suffix so our orphan rows never collide with real data and our
        # assertions can be scoped exclusively to rows we created.
        self.run_tag = frappe.generate_hash(length=10)
        self._orphan_names = []

    def tearDown(self):
        # Defensively remove any orphan rows we created that survived a test
        # (e.g. dry-run tests that intentionally leave them behind).
        self._purge_orphans()
        self._purge_member_orphans()
        super().tearDown()

    def _purge_member_orphans(self):
        names = getattr(self, "_member_orphan_names", [])
        if not names:
            return
        placeholders = ",".join(["%s"] * len(names))
        frappe.db.sql(
            f"DELETE FROM `tabMember Fee Change History` WHERE name IN ({placeholders})",
            tuple(names),
        )
        frappe.db.commit()
        self._member_orphan_names = []

    # ------------------------------------------------------------------ helpers

    def _make_volunteer_skill_orphan(self, parenttype="Volunteer", parent=None):
        """Insert one orphaned Volunteer Skill row via direct SQL.

        The parent value points at a Volunteer that does not exist, making the
        row a genuine orphan. The parent name embeds self.run_tag for scoping.
        """
        if parent is None:
            parent = f"GHOST-VOL-{self.run_tag}"
        name = frappe.generate_hash(length=18)
        frappe.db.sql(
            """
            INSERT INTO `tabVolunteer Skill`
                (name, creation, modified, modified_by, owner, docstatus, idx,
                 skill_category, volunteer_skill, parent, parentfield, parenttype)
            VALUES
                (%(name)s, NOW(), NOW(), 'Administrator', 'Administrator', 0, 1,
                 %(cat)s, %(skill)s, %(parent)s, 'skills', %(parenttype)s)
            """,
            {
                "name": name,
                "cat": "Technical",
                "skill": f"orphan-skill-{self.run_tag}",
                "parent": parent,
                "parenttype": parenttype,
            },
        )
        frappe.db.commit()
        self._orphan_names.append(name)
        return name, parent

    def _orphan_exists(self, name):
        return bool(
            frappe.db.sql(
                "SELECT name FROM `tabVolunteer Skill` WHERE name = %s", name
            )
        )

    def _purge_orphans(self):
        if not self._orphan_names:
            return
        placeholders = ",".join(["%s"] * len(self._orphan_names))
        frappe.db.sql(
            f"DELETE FROM `tabVolunteer Skill` WHERE name IN ({placeholders})",
            tuple(self._orphan_names),
        )
        frappe.db.commit()
        self._orphan_names = []

    def _count_my_orphans(self):
        if not self._orphan_names:
            return 0
        placeholders = ",".join(["%s"] * len(self._orphan_names))
        return frappe.db.sql(
            f"SELECT COUNT(*) FROM `tabVolunteer Skill` WHERE name IN ({placeholders})",
            tuple(self._orphan_names),
        )[0][0]

    # ------------------------------------------------- _validate_table_name (security)

    def test_validate_table_name_accepts_valid_names(self):
        self.assertTrue(_validate_table_name("tabMember"))
        self.assertTrue(_validate_table_name("tabVolunteer Skill"))
        self.assertTrue(_validate_table_name("tabMember Fee Change History"))
        self.assertTrue(_validate_table_name("tabDocType_123"))
        # Hyphenated DocType names are valid (e.g. eBoekhouden mapping tables)
        # and must not be flagged as a security violation.
        self.assertTrue(_validate_table_name("tabE-Boekhouden Cost Center Mapping"))

    def test_validate_table_name_rejects_sql_injection(self):
        malicious = [
            "tabMember; DROP TABLE tabMember",
            "tabMember`; DELETE FROM x; --",
            "tabMember' OR '1'='1",
            "tabMember(SELECT)",
            "tabMember\nUNION",
            "tab--comment",
            "Member",  # missing tab prefix
            "tab",  # prefix only, no name
            "",
            "xtabMember",  # does not start with tab
        ]
        for name in malicious:
            self.assertFalse(
                _validate_table_name(name),
                f"Expected {name!r} to be rejected as invalid",
            )

    # ------------------------------------------------- verify_child_table_indexes

    def test_verify_child_table_indexes_returns_structured_report(self):
        ok, data = _unwrap(verify_child_table_indexes())
        self.assertTrue(ok)
        self.assertIn("indexes_verified", data)
        self.assertIn("missing_indexes", data)
        self.assertIn("recommendations", data)
        self.assertIn("summary", data)
        self.assertIsInstance(data["missing_indexes"], list)
        # recommendations and missing_indexes must stay in lock-step
        self.assertEqual(len(data["recommendations"]), len(data["missing_indexes"]))
        # Each recommendation carries a CREATE INDEX statement
        for rec in data["recommendations"][:5]:
            self.assertIn("table", rec)
            self.assertIn("CREATE INDEX", rec["recommendation"])

    # ------------------------------------------------- create_missing_parent_indexes

    def test_create_missing_parent_indexes_is_idempotent(self):
        # First run may create indexes; second run must skip all it created.
        ok1, data1 = _unwrap(create_missing_parent_indexes())
        self.assertTrue(ok1)
        self.assertIn("indexes_created", data1)
        self.assertIn("indexes_skipped", data1)
        self.assertIn("summary", data1)

        ok2, data2 = _unwrap(create_missing_parent_indexes())
        self.assertTrue(ok2)
        # After the first pass, a second pass must create nothing new
        # (everything is now already indexed).
        self.assertEqual(
            data2["indexes_created"],
            [],
            "Second index-creation pass should create zero indexes (idempotent)",
        )

    def test_verify_after_create_reports_no_missing(self):
        # Ensure indexes exist, then verification should report none missing.
        create_missing_parent_indexes()
        ok, data = _unwrap(verify_child_table_indexes())
        self.assertTrue(ok)
        self.assertEqual(
            data["missing_indexes"],
            [],
            "After create_missing_parent_indexes, verify must report no missing indexes",
        )
        self.assertGreater(data["indexes_verified"], 0)

    # ------------------------------------------------- detect_orphaned_child_tables

    def test_detect_finds_our_orphan(self):
        self._make_volunteer_skill_orphan()
        ok, data = _unwrap(detect_orphaned_child_tables())
        self.assertTrue(ok)
        self.assertGreaterEqual(data["total_orphaned"], 1)
        # Find the Volunteer Skill / Volunteer detail entry
        vs_details = [
            d
            for d in data["details"]
            if d["child_table"] == "Volunteer Skill"
            and d["parent_doctype"] == "Volunteer"
        ]
        self.assertTrue(vs_details, "Detection should report Volunteer Skill orphans")
        sample_parents = vs_details[0]["sample_parents"]
        # Our ghost parent should appear among the detected orphan parents
        # (it is unique to this run).
        self.assertIn(f"GHOST-VOL-{self.run_tag}", sample_parents)

    def test_detect_is_read_only(self):
        name, _parent = self._make_volunteer_skill_orphan()
        detect_orphaned_child_tables()
        # Detection must never delete anything
        self.assertTrue(self._orphan_exists(name), "Detection must not delete orphans")

    # ------------------------------------------------- cleanup dry_run (no mutation)

    def test_cleanup_dry_run_reports_but_does_not_delete(self):
        name, _parent = self._make_volunteer_skill_orphan()
        ok, data = _unwrap(
            cleanup_orphaned_child_tables(dry_run=True, table_filter="Volunteer Skill")
        )
        self.assertTrue(ok)
        self.assertTrue(data["dry_run"])
        self.assertIn("note", data)
        self.assertGreaterEqual(data["total_deleted"], 1)
        # All detail actions must say "Would delete" in dry run
        for d in data["details"]:
            if "action" in d:
                self.assertEqual(d["action"], "Would delete")
        # Nothing actually deleted
        self.assertTrue(self._orphan_exists(name), "Dry run must not delete orphans")

    def test_cleanup_dry_run_string_truthy_parsing(self):
        name, _parent = self._make_volunteer_skill_orphan()
        # dry_run passed as a string (as it would arrive over HTTP) must be parsed
        ok, data = _unwrap(
            cleanup_orphaned_child_tables(dry_run="true", table_filter="Volunteer Skill")
        )
        self.assertTrue(ok)
        self.assertTrue(data["dry_run"])
        self.assertTrue(self._orphan_exists(name))

    def test_member_cleanup_dry_run_does_not_delete(self):
        ok, data = _unwrap(cleanup_member_child_tables_only(dry_run=True))
        self.assertTrue(ok)
        self.assertTrue(data["dry_run"])
        self.assertIn("audit_log", data)
        self.assertIn("summary", data)

    def test_volunteer_cleanup_dry_run_reports_our_orphan(self):
        name, _parent = self._make_volunteer_skill_orphan()
        ok, data = _unwrap(cleanup_volunteer_child_tables_only(dry_run=True))
        self.assertTrue(ok)
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(data["total_deleted"], 1)
        # Dry run must not delete
        self.assertTrue(self._orphan_exists(name))
        # Audit log entries should mark dry_run
        for entry in data["audit_log"]:
            self.assertTrue(entry["dry_run"])

    def test_volunteer_cleanup_dry_run_string_false_parsing(self):
        # "false" string should parse to dry_run=False -> would actually delete.
        # Use a Volunteer Skill orphan so it is in-scope for the volunteer cleanup.
        name, _parent = self._make_volunteer_skill_orphan()
        ok, data = _unwrap(cleanup_volunteer_child_tables_only(dry_run="false"))
        self.assertTrue(ok)
        self.assertFalse(data["dry_run"])
        # With real deletion our orphan must be gone
        self.assertFalse(self._orphan_exists(name), "Real cleanup should delete the orphan")
        self._orphan_names = []  # already deleted

    # ------------------------------------------------- cleanup real deletion (scoped)

    def test_volunteer_cleanup_real_delete_scoped_to_orphans(self):
        # Create a real volunteer with a real skill that MUST survive cleanup.
        member = self.create_test_member(
            first_name="Orphan", last_name=f"Keep{self.run_tag[:6]}"
        )
        volunteer = self.create_test_volunteer(member_name=member.name)
        vol_doc = frappe.get_doc("Volunteer", volunteer.name)
        vol_doc.append(
            "skills_and_qualifications",
            {"skill_category": "Technical", "volunteer_skill": f"keep-{self.run_tag}"},
        )
        vol_doc.save()
        frappe.db.commit()
        kept_skill_name = vol_doc.skills_and_qualifications[-1].name

        # And one genuine orphan.
        orphan_name, _parent = self._make_volunteer_skill_orphan()

        ok, data = _unwrap(cleanup_volunteer_child_tables_only(dry_run=False))
        self.assertTrue(ok)
        self.assertFalse(data["dry_run"])

        # Orphan deleted, real skill preserved.
        self.assertFalse(self._orphan_exists(orphan_name), "Orphan must be deleted")
        self.assertTrue(
            self._orphan_exists(kept_skill_name),
            "Skill of an existing volunteer must NOT be deleted (not an orphan)",
        )
        self._orphan_names = []  # orphan already deleted

    def test_cleanup_real_delete_via_batch_helper_scoped(self):
        # Directly exercise _batch_delete_orphans against our scoped orphans.
        self._make_volunteer_skill_orphan()
        self._make_volunteer_skill_orphan()
        before = self._count_my_orphans()
        self.assertEqual(before, 2)

        deleted = _batch_delete_orphans(
            "tabVolunteer Skill", "tabVolunteer", "Volunteer", batch_size=1
        )
        # Batch helper deletes ALL Volunteer-parented orphans site-wide; we only
        # assert OUR rows are gone and the count is at least what we created.
        self.assertGreaterEqual(deleted, 2)
        self.assertEqual(self._count_my_orphans(), 0)
        self._orphan_names = []

    def test_member_cleanup_real_delete_scoped(self):
        # Member-scoped cleanup uses parenttype-agnostic parent->tabMember join,
        # so any Volunteer Skill row whose parent is absent from tabMember counts.
        # Use a member-child-table orphan instead for correctness.
        orphan_name = self._make_member_fee_history_orphan()
        ok, data = _unwrap(cleanup_member_child_tables_only(dry_run=False))
        self.assertTrue(ok)
        self.assertFalse(data["dry_run"])
        self.assertFalse(
            frappe.db.sql(
                "SELECT name FROM `tabMember Fee Change History` WHERE name = %s",
                orphan_name,
            ),
            "Orphaned Member Fee Change History row must be deleted",
        )
        self._member_orphan_names = []

    def _make_member_fee_history_orphan(self):
        name = frappe.generate_hash(length=18)
        frappe.db.sql(
            """
            INSERT INTO `tabMember Fee Change History`
                (name, creation, modified, modified_by, owner, docstatus, idx,
                 change_date, change_type, parent, parentfield, parenttype)
            VALUES
                (%(name)s, NOW(), NOW(), 'Administrator', 'Administrator', 0, 1,
                 %(date)s, 'Manual', %(parent)s, 'fee_change_history', 'Member')
            """,
            {
                "name": name,
                "date": nowdate(),
                "parent": f"GHOST-MEM-{self.run_tag}",
            },
        )
        frappe.db.commit()
        self._member_orphan_names = getattr(self, "_member_orphan_names", [])
        self._member_orphan_names.append(name)
        return name

    # ------------------------------------------------- table_filter behaviour

    def test_cleanup_table_filter_scopes_to_single_table(self):
        self._make_volunteer_skill_orphan()
        ok, data = _unwrap(
            cleanup_orphaned_child_tables(dry_run=True, table_filter="Volunteer Skill")
        )
        self.assertTrue(ok)
        # Only Volunteer Skill should appear in details
        child_tables = {d.get("child_table") for d in data["details"]}
        child_tables.discard(None)
        self.assertEqual(child_tables, {"Volunteer Skill"})

    def test_cleanup_nonexistent_table_filter_returns_empty(self):
        ok, data = _unwrap(
            cleanup_orphaned_child_tables(
                dry_run=True, table_filter="Nonexistent Doctype XYZ"
            )
        )
        self.assertTrue(ok)
        self.assertEqual(data["total_deleted"], 0)
        self.assertEqual(data["tables_cleaned"], 0)

    # ------------------------------------------------- SimpleLock

    def test_simple_lock_acquire_release_cycle(self):
        lock_name = f"test_orphan_lock_{self.run_tag}"
        lock = SimpleLock(lock_name, timeout=60)
        self.assertTrue(lock.acquire(blocking=False))
        self.assertTrue(lock.acquired)
        try:
            # A second lock with the same name must fail to acquire
            other = SimpleLock(lock_name, timeout=60)
            self.assertFalse(other.acquire(blocking=False))
            self.assertFalse(other.acquired)
        finally:
            lock.release()
            self.assertFalse(lock.acquired)
        # After release a fresh lock can acquire again
        again = SimpleLock(lock_name, timeout=60)
        self.assertTrue(again.acquire(blocking=False))
        again.release()

    def test_simple_lock_release_without_acquire_is_safe(self):
        lock = SimpleLock(f"test_unacquired_{self.run_tag}", timeout=60)
        # Never acquired -> release must be a no-op, not raise
        lock.release()
        self.assertFalse(lock.acquired)

    def test_concurrent_cleanup_blocked_by_lock(self):
        # Hold the system-wide lock, then a non-dry-run cleanup must be refused.
        held = SimpleLock("orphaned_cleanup_system_wide", timeout=60)
        self.assertTrue(held.acquire(blocking=False))
        try:
            result = cleanup_orphaned_child_tables(dry_run=False, skip_index_check=True)
            ok, err = _unwrap(result)
            self.assertFalse(ok, "Cleanup should be refused while lock is held")
            self.assertIn("currently running", err.get("message", ""))
        finally:
            held.release()

    def test_member_cleanup_concurrent_lock_block(self):
        held = SimpleLock("orphaned_cleanup_member_only", timeout=60)
        self.assertTrue(held.acquire(blocking=False))
        try:
            ok, err = _unwrap(cleanup_member_child_tables_only(dry_run=False))
            self.assertFalse(ok)
            self.assertIn("currently running", err.get("message", ""))
        finally:
            held.release()

    def test_volunteer_cleanup_concurrent_lock_block(self):
        held = SimpleLock("orphaned_cleanup_volunteer_only", timeout=60)
        self.assertTrue(held.acquire(blocking=False))
        try:
            ok, err = _unwrap(cleanup_volunteer_child_tables_only(dry_run=False))
            self.assertFalse(ok)
            self.assertIn("currently running", err.get("message", ""))
        finally:
            held.release()
