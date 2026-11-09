"""#1856: the generic test drains must delete a tracked Role's `Has Role` rows too.

Frappe's Role has no `on_trash` that calls `remove_roles()`. A drain that force-deletes a
tracked Role therefore strands the grant on every user that outlives the test (Administrator
is the realistic one), and that user's next `save()` raises "Could not find Row #N: Role: ...".

Each test grants a real Role to Administrator, commits (as production code under test does),
runs one of the four real drain call sites, then checks both the rows and the save. Administrator's
grant is removed in `finally` whatever happens. Probe shortcut: the drain methods are called
directly with a hand-built `doc_info` rather than through a full tearDown.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.force_delete import delete_role_and_grants


class _DrainRoleGrantsMixin:
    def _create_committed_role_grant(self):
        """A Role granted to Administrator and COMMITTED, as production code under test does.

        The commit is load-bearing: the factory drain rolls back before it deletes, so an
        uncommitted grant would vanish and the test could not see the defect.
        """
        role = frappe.get_doc(
            {"doctype": "Role", "role_name": f"zzz-1856-{frappe.generate_hash(length=8)}"}
        ).insert()
        frappe.get_doc("User", "Administrator").add_roles(role.name)
        frappe.db.commit()
        return role.name

    def _cleanup_role_grant(self, role_name):
        delete_role_and_grants(role_name)
        frappe.db.commit()

    def test_drain_leaves_no_has_role_rows_and_administrator_still_saves(self):
        role_name = self._create_committed_role_grant()
        try:
            self.assertEqual(frappe.db.count("Has Role", {"parent": "Administrator", "role": role_name}), 1)

            getattr(self, self.drain_method)(role_name)

            self.assertFalse(frappe.db.exists("Role", role_name), "the drain did not delete the Role")
            self.assertEqual(frappe.db.count("Has Role", {"role": role_name}), 0)
            frappe.get_doc("User", "Administrator").save()
        finally:
            self._cleanup_role_grant(role_name)


class TestBaseInstanceDrain(_DrainRoleGrantsMixin, VereningingenTestCase):
    drain_method = "drain_via_base_retry"

    def drain_via_base_retry(self, role_name):
        info = {"doctype": "Role", "name": role_name}
        self._cleanup_document_with_retry(info)
        self.assertEqual(info["cleanup_status"], "success")


class TestBaseClassDrain(_DrainRoleGrantsMixin, VereningingenTestCase):
    drain_method = "drain_via_base_class"

    def drain_via_base_class(self, role_name):
        saved = list(type(self)._track_created_docs)
        type(self)._track_created_docs = [{"doctype": "Role", "name": role_name}]
        try:
            type(self)._cleanup_tracked_docs()
        finally:
            type(self)._track_created_docs = saved


class TestFactoryRemoveDrainedRecord(_DrainRoleGrantsMixin, EnhancedTestCase):
    drain_method = "drain_via_remove_record"

    def drain_via_remove_record(self, role_name):
        self._remove_drained_record("Role", role_name)


class TestFactoryRetryDrain(_DrainRoleGrantsMixin, EnhancedTestCase):
    drain_method = "drain_via_factory_retry"

    def drain_via_factory_retry(self, role_name):
        self._cleanup_document_with_retry({"doctype": "Role", "name": role_name})
