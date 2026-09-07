#!/usr/bin/env python3
"""#1084 and its class: functions under ``scripts/`` carrying a BARE
``@frappe.whitelist()`` (no security decorator) that also write to the
database via a raw ``frappe.db.set_value``/``frappe.db.sql``/``frappe.delete_doc``/
``rename_doc``/``doc.save(ignore_permissions=True)`` path. A bare whitelist means
ANY authenticated (non-guest) user can dispatch the call directly via
``frappe.call`` -- these are one-off debug/migration/admin scripts meant to be
run via ``bench execute``, which never consults ``frappe.whitelisted`` at all,
so removing the decorator does not break their real callers.

Class census (AST sweep over scripts/, re-derived independently of #1084's own
count): 123 whitelisted functions under scripts/, 39 carry a bare
``@frappe.whitelist()`` with no other decorator, 11 of those write to the
database via a permission-bypassing path (three more than #1084's own sweep
found, because a textual ``.<method>(`` search misses a bare `rename_doc(...)`
call reached through `from frappe.model.rename_doc import rename_doc`).

This test asserts the fix empirically -- dispatch membership, not decorator
presence per CLAUDE.md's "never reason about reachability from decorator
order" -- for the 11 endpoints ENUMERATED in ``WRITE_ENDPOINTS`` below.

It is a regression guard, NOT a class invariant, and the distinction matters:
``WRITE_ENDPOINTS`` is a fixed list, so re-adding ``@frappe.whitelist()`` to
any of the 11 reddens this test, but a TWELFTH bare-whitelisted writer added
under ``scripts/`` later would leave it green. Verified by planting exactly
that -- a new ``scripts/debug/`` module with a bare ``@frappe.whitelist()``
over ``frappe.db.set_value`` + ``commit`` -- during review: this test still
passed 3/3.

What does cover the twelfth is the scanner-based ratchet
``scripts/validation/security/insecure_api_detector.py``, which exits 1 with
"1 finding(s) are new/blocking" on that same planted file. So the class is
gated; it is gated there, not here. Do not widen this list in the belief that
it is the class-level defense -- extend the scanner's coverage instead.
"""

import importlib
import unittest

import frappe

# (module path, function name) for every bare-@frappe.whitelist() function
# under scripts/ found to write to the database. Grouped by file.
WRITE_ENDPOINTS = [
    # #1084's own instance
    ("scripts.debug.membership_dues_coverage_debugger", "populate_coverage_dates"),
    # Role/permission-system writes -- delete_doc on Has Role / DocPerm
    ("scripts.admin.role_cleanup", "remove_redundant_admin_roles"),
    ("scripts.admin.role_cleanup", "fix_chapter_permission_conflicts"),
    # Dashboard doc mutation (save/delete_doc/insert)
    ("scripts.debug.fix_dashboard_chart_issue", "fix_dashboard_chart_issue"),
    # Accounting voucher delete/cancel
    ("scripts.debug.remove_period_closing_vouchers", "remove_period_closing_vouchers"),
    # Raw DDL (CREATE INDEX) against the live schema
    ("scripts.deployment.validate_production_schema", "create_production_indexes"),
    # Item creation with ignore_permissions=True
    ("scripts.migration.create_missing_item", "create_missing_item"),
    # Accounting voucher creation + submit
    ("scripts.migration.create_period_closing_vouchers", "create_period_closing_vouchers"),
    # Role renames via a bare `rename_doc(...)` import -- missed by a textual
    # `.rename_doc(` sweep since there is no leading dot/attribute access.
    ("scripts.admin.role_renamer", "rename_all_roles"),
    ("scripts.maintenance.rename_roles_with_prefix", "rename_verenigingen_roles"),
    # Worst of the class: renames ANY Role to ANY name using a caller-supplied,
    # wholly unvalidated `role_mappings` argument.
    ("scripts.maintenance.rename_roles_with_prefix", "rollback_role_rename"),
]


class ScriptsBareWhitelistWriteEndpointsNotDispatchableTest(unittest.TestCase):
    """None of the write-touching endpoints above may be reachable via
    frappe.call/@frappe.whitelist dispatch. bench execute (frappe.get_attr +
    a direct call) bypasses frappe.whitelisted entirely, so this does not
    affect any real caller of these one-off admin/debug/migration scripts."""

    def test_no_write_endpoint_is_dispatch_reachable(self):
        still_whitelisted = []
        for module_path, func_name in WRITE_ENDPOINTS:
            module = importlib.import_module(module_path)
            fn = getattr(module, func_name)
            if fn in frappe.whitelisted:
                still_whitelisted.append(f"{module_path}.{func_name}")

        self.assertEqual(
            still_whitelisted,
            [],
            "The following scripts/ write endpoints are still dispatch-reachable "
            "via frappe.call (bare @frappe.whitelist() over a DB-write path, the "
            f"#1084 class): {still_whitelisted}",
        )

    def test_is_whitelisted_refuses_each_endpoint(self):
        """Belt-and-braces: frappe.is_whitelisted() must actively refuse each
        one (PermissionError), not just report absence from the registry."""
        for module_path, func_name in WRITE_ENDPOINTS:
            module = importlib.import_module(module_path)
            fn = getattr(module, func_name)
            with self.subTest(endpoint=f"{module_path}.{func_name}"):
                with self.assertRaises(frappe.PermissionError):
                    frappe.is_whitelisted(fn)

    def test_control_group_still_importable_and_callable_as_plain_python(self):
        """Removing @frappe.whitelist() must not break the bench-execute /
        internal-Python-call path -- these functions must remain ordinary,
        directly-importable module-level callables."""
        for module_path, func_name in WRITE_ENDPOINTS:
            module = importlib.import_module(module_path)
            fn = getattr(module, func_name)
            self.assertTrue(
                callable(fn),
                f"{module_path}.{func_name} must remain a plain callable "
                "(bench execute uses frappe.get_attr + a direct call, which "
                "never consults frappe.whitelisted)",
            )


if __name__ == "__main__":
    unittest.main()
