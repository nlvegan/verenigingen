"""
#1098: ``rollback_role_rename`` must only reverse the renames ``ROLE_MAPPINGS`` describes.

The function is bench-execute-only (not whitelisted, pinned by
test_scripts_bare_whitelist_write_endpoints), so this is defence in depth: a caller-supplied
``role_mappings`` used to be an arbitrary Role-rename primitive. It must now refuse any
``{new_name: old_name}`` pair that is not the reverse of a ROLE_MAPPINGS entry, and refuse the
whole call before renaming anything.

ROLE_MAPPINGS is patched to a real old/new pair of disposable Role rows (the shipped constant maps
every role to itself, so it has no rename to exercise). Real Role rows, real ``rename_doc``.

Run on test_site_11:
    bench --site test_site_11 run-tests --app verenigingen \
        --module verenigingen.tests.security.test_rollback_role_rename_mappings_1098
"""

import importlib
from unittest import mock

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

MODULE = "scripts.maintenance.rename_roles_with_prefix"
OLD = "Zz1098 Role Old"
NEW = "Zz1098 Role New"
BYSTANDER = "Zz1098 Role Bystander"
SPARE = "Zz1098 Role Spare"


class TestRollbackRoleRenameMappings1098(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.module = importlib.import_module(MODULE)
        self._wipe_1098_roles()
        for name in (NEW, BYSTANDER):
            frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)
        patcher = mock.patch.dict(self.module.ROLE_MAPPINGS, {OLD: NEW}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._wipe_1098_roles)

    def _wipe_1098_roles(self):
        for name in (OLD, NEW, BYSTANDER, SPARE):
            if frappe.db.exists("Role", name):
                frappe.delete_doc("Role", name, force=True, ignore_permissions=True)

    def _assert_rollback_refused_1098(self, mappings):
        with self.assertRaises(frappe.ValidationError):
            self.module.rollback_role_rename(mappings)

    def test_control_the_real_reverse_mapping_still_rolls_back(self):
        result = self.module.rollback_role_rename({NEW: OLD})
        self.assertTrue(frappe.db.exists("Role", OLD))
        self.assertFalse(frappe.db.exists("Role", NEW))
        self.assertEqual(result["errors"], [])

    def test_control_default_mapping_still_rolls_back(self):
        self.module.rollback_role_rename()
        self.assertTrue(frappe.db.exists("Role", OLD))
        self.assertFalse(frappe.db.exists("Role", NEW))

    def test_a_role_outside_role_mappings_is_not_renamed(self):
        self._assert_rollback_refused_1098({BYSTANDER: SPARE})
        self.assertTrue(frappe.db.exists("Role", BYSTANDER))
        self.assertFalse(frappe.db.exists("Role", SPARE))

    def test_a_known_role_cannot_be_renamed_to_an_arbitrary_name(self):
        # right key, wrong value: catches a keys-only validation
        self._assert_rollback_refused_1098({NEW: SPARE})
        self.assertTrue(frappe.db.exists("Role", NEW))
        self.assertFalse(frappe.db.exists("Role", SPARE))

    def test_one_bad_entry_refuses_the_whole_call_before_any_rename(self):
        self._assert_rollback_refused_1098({NEW: OLD, BYSTANDER: SPARE})
        self.assertTrue(frappe.db.exists("Role", NEW))
        self.assertFalse(frappe.db.exists("Role", OLD))
        self.assertTrue(frappe.db.exists("Role", BYSTANDER))
