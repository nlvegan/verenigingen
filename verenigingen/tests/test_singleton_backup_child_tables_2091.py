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
        frappe.db.delete(CHILD, FILTERS)
        backup = SingletonBackup(DT)
        backup.backup()
        config = frappe.get_single(DT)
        config.append("notification_types", {"notification_key": "probe_2091_key", "label": "probe", "enabled": 1})
        config.save()
        backup.restore()
        self.assertEqual(_rows(), [], "an empty table must be restored as empty")

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
