"""The meta memos in the two member optimizers must not outlive a schema customisation (#1935).

They were process-wide ``functools.lru_cache``s of ``frappe.get_meta`` results with no site in
the key, so a Custom Field added after the first read (or present only on another site served by
the same worker) was invisible. Frappe already caches meta per site and invalidates it on
Customize Form / Custom Field save, so the functions now just ask it.

Drives the real flow (a Custom Field insert), primes the cache BEFORE the insert. The cross-site
half was shown with a two-site probe (frappe.init site A, prime, destroy, init site B); an
in-process test can only exercise the staleness half, which is the same missing-key defect.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.member_performance_optimizer import MemberPerformanceOptimizer
from verenigingen.utils.safe_member_optimizer import SafeMemberOptimizer

PROBE = "zz_meta_probe_1935"


class TestMetaCachesFollowCustomization1935(VereningingenTestCase):
    def _add_probe_field(self, doctype, fieldtype="Link", options="User"):
        # Custom Field DDL commits, so rollback cannot undo it: delete the row and drop the column.
        self.addCleanup(self._remove_probe_field, doctype)
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": doctype,
                "fieldname": PROBE,
                "fieldtype": fieldtype,
                "options": options,
                "label": "Meta probe 1935",
            }
        ).insert()

    @staticmethod
    def _remove_probe_field(doctype):
        name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": PROBE})
        if name:
            frappe.delete_doc("Custom Field", name, force=True)
        if frappe.db.has_column(doctype, PROBE):
            frappe.db.sql_ddl(f"alter table `tab{doctype}` drop column `{PROBE}`")
        frappe.clear_cache(doctype=doctype)

    def test_child_table_meta_sees_a_field_added_after_first_read(self):
        SafeMemberOptimizer.get_child_table_meta_cached("ToDo")
        self._add_probe_field("ToDo")
        self.assertTrue(SafeMemberOptimizer.get_child_table_meta_cached("ToDo").get_field(PROBE))

    def test_link_field_options_see_a_field_added_after_first_read(self):
        SafeMemberOptimizer.get_link_field_options_cached("ToDo")
        self._add_probe_field("ToDo")
        self.assertEqual(SafeMemberOptimizer.get_link_field_options_cached("ToDo").get(PROBE), "User")

    def test_doctype_meta_sees_a_field_added_after_first_read(self):
        MemberPerformanceOptimizer.get_doctype_meta_cached("ToDo")
        self._add_probe_field("ToDo")
        meta = MemberPerformanceOptimizer.get_doctype_meta_cached("ToDo")
        self.assertIn(PROBE, meta["field_map"])

    def test_clear_all_member_caches_still_runs(self):
        MemberPerformanceOptimizer().clear_all_member_caches()
