"""``singleton_backup`` must put a Single's CHILD TABLES back too (#2091).

``SingletonBackup`` skipped every ``Table`` field, so a test that replaced
``Verenigingen Email Configuration.notification_types`` inside ``singleton_backup(...)`` left the
replacement in place, and ``restore()`` ends in ``frappe.db.commit()``, which made it permanent for
every later module in the CI shard. Measured on test_site_2: running
``test_unregistered_notification_description`` then ``test_approval_without_invoice`` in one process
left ONE ``notification_types`` row on the site and failed 31 of 33 tests with "has no enabled
'member_application_approved' row". Redis was not involved: ``frappe.get_single`` reads the database.

These tests add no ``frappe.db.commit()`` of their own (the order-dependence baseline may not grow).
``restore()`` commits by itself, which is the exact "commit while stripped" path of the leak, so the
tests need none. The cleanup writes the snapshot back uncommitted; if a regression made ``restore()``
commit a stripped table, the class rollback would not undo it, and the red run says so loudly.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup, singleton_backup

DT = "Verenigingen Email Configuration"
CHILD = "Email Notification Type"
FILTERS = {"parent": DT, "parenttype": DT, "parentfield": "notification_types"}


def _rows():
    return frappe.get_all(CHILD, filters=FILTERS, fields=["*"], order_by="idx asc", limit_page_length=0)


class TestSingletonBackupRestoresChildTables(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._snapshot = _rows()
        self.assertGreater(len(self._snapshot), 2, "precondition: the site has seeded notification rows")
        self.addCleanup(self._put_site_back)

    def _put_site_back(self):
        frappe.db.delete(CHILD, FILTERS)
        frappe.db.delete(CHILD, {"name": ("in", [r.name for r in self._snapshot])})
        for row in self._snapshot:
            frappe.get_doc({**row, "doctype": CHILD}).db_insert()

    def _strip_and_disable(self):
        config = frappe.get_single(DT)
        keep = config.notification_types[0].notification_key
        config.set("notification_types", [])
        config.append("notification_types", {"notification_key": keep, "label": "kept", "enabled": 0})
        config.append("notification_types", {"notification_key": "probe_2091_key", "label": "probe", "enabled": 1})
        config.save()
        return keep

    def test_replaced_rows_come_back_although_restore_commits(self):
        with singleton_backup(DT):
            keep = self._strip_and_disable()
            self.assertEqual(len(_rows()), 2, "control: the strip really reached the database")
        self.assertEqual(_rows(), self._snapshot)
        self.assertNotIn("probe_2091_key", [r.notification_key for r in _rows()])
        first = frappe.get_single(DT).notification_types[0]
        self.assertEqual((first.notification_key, first.enabled), (keep, self._snapshot[0].enabled))

    def test_restore_also_removes_rows_added_to_an_empty_table(self):
        # The OUTER backup, taken before the delete, is what puts the site back: this test's own
        # `restore()` commits an EMPTY table, which the uncommitted cleanup could not undo (#2158 S1).
        with singleton_backup(DT):
            frappe.db.delete(CHILD, FILTERS)
            backup = SingletonBackup(DT)
            backup.backup()
            config = frappe.get_single(DT)
            config.append(
                "notification_types", {"notification_key": "probe_2091_key", "label": "probe", "enabled": 1}
            )
            config.save()
            backup.restore()
            self.assertEqual(_rows(), [], "an empty table must be restored as empty")

    def test_a_row_moved_to_another_parentfield_does_not_half_restore_the_table(self):
        """N1: the captured row's NAME is taken by a row the parentfield filter does not match, so a
        filter-only delete leaves it and the re-insert raises IntegrityError mid-restore."""
        moved = self._snapshot[0].name
        backup = SingletonBackup(DT)
        backup.backup()
        frappe.db.set_value(CHILD, moved, "parentfield", "moved_2091", update_modified=False)
        backup.restore()
        self.assertEqual(_rows(), self._snapshot)
        self.assertEqual(frappe.db.count(CHILD, {"parentfield": "moved_2091"}), 0)

    def test_restored_rows_survive_an_enhanced_test_case_teardown(self):
        """`EnhancedTestCase` deletes every row inserted during a test at teardown. The restore inserts
        rows, so without ``suspend_insert_capture`` the drain claims them and the table ends EMPTY
        (the victim module, ``test_approval_without_invoice``, uses ``singleton_backup`` in a test body)."""

        class _Case(EnhancedTestCase):
            def test_body(inner):
                with singleton_backup(DT):
                    self._strip_and_disable()

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_Case).run(result)
        self.assertEqual(result.errors + result.failures, [], "the nested class must run clean")
        self.assertEqual(_rows(), self._snapshot)


SETTINGS = "Verenigingen Settings"
SETTINGS_TABLES = {
    "board_document_categories": "Board Document Category",
    "application_payment_methods": "Application Payment Method",
    "volunteer_skill_categories": "Volunteer Skill Category",
}


def _settings_rows(fieldname):
    return frappe.get_all(
        SETTINGS_TABLES[fieldname],
        filters={"parent": SETTINGS, "parenttype": SETTINGS, "parentfield": fieldname},
        fields=["*"],
        order_by="idx asc",
        limit_page_length=0,
    )


class TestSingletonBackupSingleWithSeveralTables(FrappeTestCase):
    """`Verenigingen Settings` has three tables. A restore keyed on one doctype, or one that deletes by
    `parent` alone (so each table's delete wipes the previous table's re-inserted rows), passes the
    one-table tests above and fails here (#2158 S2)."""

    def setUp(self):
        super().setUp()
        self._snapshot = {f: _settings_rows(f) for f in SETTINGS_TABLES}
        self.assertGreater(
            len(self._snapshot["board_document_categories"]), 1, "precondition: the first table has rows"
        )
        self.addCleanup(self._put_site_back)

    def _put_site_back(self):
        for fieldname, child in SETTINGS_TABLES.items():
            frappe.db.delete(child, {"parent": SETTINGS, "parentfield": fieldname})
            for row in self._snapshot[fieldname]:
                frappe.get_doc({**row, "doctype": child}).db_insert()

    def _change_two_tables(self):
        """Raw writes (no controller hook): shrink table one, add a row to table two."""
        first = self._snapshot["board_document_categories"]
        frappe.db.delete("Board Document Category", {"name": ("in", [r.name for r in first[1:]])})
        frappe.get_doc(
            {
                "doctype": "Application Payment Method",
                "name": frappe.generate_hash(length=10),
                "parent": SETTINGS,
                "parenttype": SETTINGS,
                "parentfield": "application_payment_methods",
                "idx": 1,
            }
        ).db_insert()

    def test_changes_to_two_tables_both_come_back_whole(self):
        with singleton_backup(SETTINGS):
            self._change_two_tables()
            self.assertEqual(len(_settings_rows("board_document_categories")), 1, "control: table one changed")
            self.assertEqual(len(_settings_rows("application_payment_methods")), 1, "control: table two changed")
        for fieldname in SETTINGS_TABLES:
            self.assertEqual(_settings_rows(fieldname), self._snapshot[fieldname], fieldname)

    def test_the_cached_document_reflects_the_restored_rows(self):
        """Pins the outcome, not the `clear_document_cache` call: `restore()` commits afterwards, and
        `clear_document_cache` registers the same redis delete as an after-commit hook, so removing the
        explicit call does not change this result (measured: that mutant stays green)."""
        names = [r.name for r in self._snapshot["board_document_categories"]]
        with singleton_backup(SETTINGS):
            self._change_two_tables()
            cached = frappe.get_cached_doc(SETTINGS)
            self.assertEqual(len(cached.board_document_categories), 1, "control: the cache holds the change")
        restored = frappe.get_cached_doc(SETTINGS)
        self.assertEqual([r.name for r in restored.board_document_categories], names)
        self.assertEqual(len(restored.application_payment_methods), 0)


NAVBAR = "Navbar Settings"
NAVBAR_FIELDS = ("settings_dropdown", "help_dropdown")


def _navbar_rows(fieldname):
    return frappe.get_all(
        "Navbar Item",
        filters={"parent": NAVBAR, "parenttype": NAVBAR, "parentfield": fieldname},
        fields=["*"],
        order_by="idx asc",
        limit_page_length=0,
    )


class TestSingletonBackupTwoTablesOfOneChildDoctype(FrappeTestCase):
    """`Navbar Settings` has two tables of the SAME child doctype (`Navbar Item`). A restore that deletes
    by `parent` alone, dropping `parentfield`, wipes the first table's re-inserted rows when it handles
    the second; on `Verenigingen Settings` (three DISTINCT child doctypes) that mutant is invisible, so
    this is the class that pins the parentfield filter (#2158 S2)."""

    def setUp(self):
        super().setUp()
        # The site's own rows cannot be relied on: a fresh install (CI) has an EMPTY
        # settings_dropdown. So this class backs up whatever is there, seeds two rows in each
        # table itself, and the outer backup's restore (which commits) puts the site back as found.
        outer = SingletonBackup(NAVBAR)
        outer.backup()
        self.addCleanup(outer.restore)
        for fieldname in NAVBAR_FIELDS:
            for i in range(2):
                frappe.get_doc(
                    {
                        "doctype": "Navbar Item",
                        "name": frappe.generate_hash(length=10),
                        "parent": NAVBAR,
                        "parenttype": NAVBAR,
                        "parentfield": fieldname,
                        "idx": 1000 + i,
                        "item_label": f"T2091 {fieldname} {i}",
                        "item_type": "Route",
                        "route": "/app",
                    }
                ).db_insert()
        self._snapshot = {f: _navbar_rows(f) for f in NAVBAR_FIELDS}
        for fieldname in NAVBAR_FIELDS:
            self.assertGreaterEqual(len(self._snapshot[fieldname]), 2, f"precondition: {fieldname} has rows")

    def test_both_tables_of_a_shared_child_doctype_come_back_whole(self):
        with singleton_backup(NAVBAR):
            for fieldname in NAVBAR_FIELDS:
                first = self._snapshot[fieldname][0]
                frappe.db.delete("Navbar Item", {"name": first.name})
                frappe.db.set_value("Navbar Item", self._snapshot[fieldname][-1].name, "item_label", "changed_2091")
        for fieldname in NAVBAR_FIELDS:
            self.assertEqual(_navbar_rows(fieldname), self._snapshot[fieldname], fieldname)


class TestSingletonBackupCapturesPasswordsEvenIfAChildCaptureFails(FrappeTestCase):
    """N2: the child capture runs after the password capture and cannot prevent it."""

    def test_password_backup_survives_a_failing_child_capture(self):
        from frappe.utils.password import set_encrypted_password

        # Written uncommitted; this class' rollback removes it. `backup()` is never followed by `restore()`.
        set_encrypted_password("Ponto Settings", "Ponto Settings", "probe-2091", fieldname="sandbox_client_secret")

        class _BrokenChildCapture(SingletonBackup):
            @staticmethod
            def _child_rows(doctype_name, fieldname, child_doctype):
                raise RuntimeError("child capture failed")

        backup = _BrokenChildCapture("Ponto Settings")
        backup.backup()
        self.assertEqual(
            backup._password_backups["Ponto Settings"].get("sandbox_client_secret"), "probe-2091"
        )
        self.assertIn("Ponto Settings", backup._backups, "the scalar backup must be kept too")
