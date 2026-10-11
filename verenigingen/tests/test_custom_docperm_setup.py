"""Custom DocPerm handling on install/migrate (#1621, #1622).

When a DocType has ANY Custom DocPerm row, Frappe ignores its stock DocPerm rows
(``frappe/model/meta.py::set_custom_permissions``). ``frappe.permissions.add_permission``
copies the stock rows first; a raw insert (what fixture import does) does not.

Probe shortcuts, stated up front: the "JSON changed" step edits the DocPerm table with
``db.set_value`` as the stand-in for "a new release's JSON was synced by migrate". The
frozen state itself is created through the REAL path (``add_permission``).
"""

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

PERM_FIELDS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report",
               "export", "import", "share", "print", "email", "select")
LEGACY_FIXTURE = "custom_docperm.json"


def _effective(doctype):
    frappe.clear_cache(doctype=doctype)
    return frappe.get_meta(doctype).permissions


def _roles(doctype):
    return {p.role for p in _effective(doctype)}


def _run_permission_sync():
    """What the app does on install/migrate for permissions.

    Before the fix there is no such function and the app's fixture file is the only
    mechanism; importing that file is exactly what `migrate` did for it.
    """
    path = frappe.get_app_path("verenigingen", "fixtures", LEGACY_FIXTURE)
    if os.path.exists(path):
        # What fixture import does with these rows: a plain insert, no copy_perms. Done by
        # hand because data_import.import_doc commits, which the per-test rollback cannot undo.
        with open(path) as f:
            for row in json.load(f):
                frappe.get_doc(row).insert(ignore_if_duplicate=True)
    try:
        from verenigingen.setup.custom_docperm_setup import apply_custom_permissions
    except ImportError:
        return
    apply_custom_permissions()


TEST_ROLE = "Test Public Creator 1621"


class TestCustomDocPermSetup(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Plain FrappeTestCase, deliberately: the Enhanced harness's insert-capture drain
        # resurrects and COMMITS the Role and Custom DocPerm rows these tests insert (measured:
        # one Role and one Custom DocPerm row leaked per run). Nothing here commits, so a
        # rollback per test is a complete cleanup.
        self.addCleanup(self._rollback_and_clear_cache)

    def _rollback_and_clear_cache(self):
        frappe.db.rollback()
        frappe.clear_cache()

    def _drop_custom(self, doctype):
        frappe.db.delete("Custom DocPerm", {"parent": doctype})

    def _raw_custom_row(self, doctype, role, **ptypes):
        frappe.get_doc(
            {"doctype": "Custom DocPerm", "parent": doctype, "parenttype": "DocType",
             "parentfield": "permissions", "role": role, "permlevel": 0, **ptypes}
        ).insert()

    # ---- #1622: core DocTypes -------------------------------------------------

    def test_pristine_doctype_keeps_stock_roles_after_install_steps(self):
        for dt in ("Company", "Account", "Mode of Payment", "Customer"):
            with self.subTest(doctype=dt):
                self._drop_custom(dt)
                stock = set(frappe.get_all("DocPerm", filters={"parent": dt}, pluck="role"))
                self.assertTrue(stock, f"{dt} has no stock DocPerm rows; fixture is meaningless")
                _run_permission_sync()
                effective = _roles(dt)
                self.assertTrue(stock <= effective, f"{dt} lost stock roles {stock - effective}")
                self.assertIn("Verenigingen Webhook User", effective)

    def test_webhook_grant_is_read_only_on_company(self):
        self._drop_custom("Company")
        _run_permission_sync()
        row = [p for p in _effective("Company") if p.role == "Verenigingen Webhook User"]
        self.assertEqual(len(row), 1)
        self.assertEqual(cint(row[0].read), 1)
        self.assertEqual(cint(row[0].write), 0)

    def test_truncated_site_is_repaired(self):
        self._drop_custom("Company")
        # the legacy outcome: fixture rows + the HRMS User Type row, no stock copy
        self._raw_custom_row("Company", "Verenigingen Webhook User", read=1)
        self._raw_custom_row("Company", "Employee Self Service", select=1)
        stock = set(frappe.get_all("DocPerm", filters={"parent": "Company"}, pluck="role"))
        self.assertFalse(stock <= _roles("Company"), "precondition: set is truncated")
        _run_permission_sync()
        self.assertTrue(stock <= _roles("Company"))
        ess = [p for p in _effective("Company") if p.role == "Employee Self Service"]
        self.assertEqual(sum(cint(p.select) for p in ess), 1, "User Type's select row kept")

    def test_admin_curated_set_is_not_repaired(self):
        self._drop_custom("Company")
        # Accounts User is stock; Sales Manager is neither declared nor a user-type role,
        # so this set cannot be the legacy truncation. Stock roles absent from it were
        # deliberately removed.
        self._raw_custom_row("Company", "Accounts User", read=1)
        self._raw_custom_row("Company", "Sales Manager", read=1)
        dropped = set(frappe.get_all("DocPerm", filters={"parent": "Company"}, pluck="role")) - {
            "Accounts User", "Sales Manager"}
        self.assertTrue(dropped)
        _run_permission_sync()
        self.assertFalse(dropped & _roles("Company"), "curated set must not get stock rows back")

    def test_grants_are_idempotent(self):
        self._drop_custom("Company")
        _run_permission_sync()
        first = sorted(frappe.get_all("Custom DocPerm", filters={"parent": "Company"}, pluck="name"))
        _run_permission_sync()
        second = sorted(frappe.get_all("Custom DocPerm", filters={"parent": "Company"}, pluck="name"))
        self.assertEqual(first, second)

    # ---- #1621: own DocTypes --------------------------------------------------

    def _freeze_via_user_type_path(self, doctype):
        from frappe.permissions import add_permission, update_permission_property

        self._drop_custom(doctype)
        add_permission(doctype, "Employee Self Service", 0, "select")
        update_permission_property(doctype, "Employee Self Service", 0, "select", 1, validate=False)

    def _flip_json_write_flags(self, doctype):
        """Stand-in for a release whose JSON changed (probe shortcut, see module doc)."""
        for row in frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["name", "write"]):
            frappe.db.set_value("DocPerm", row.name, "write", 0 if cint(row.write) else 1)
        frappe.clear_cache(doctype=doctype)

    def _assert_effective_matches_json(self, doctype):
        effective = {(p.role, cint(p.permlevel), cint(p.if_owner)): p for p in _effective(doctype)}
        for row in frappe.get_all("DocPerm", filters={"parent": doctype}, fields="*"):
            got = effective[(row.role, cint(row.permlevel), cint(row.if_owner))]
            for f in PERM_FIELDS:
                self.assertEqual(cint(got.get(f)), cint(row.get(f)),
                                 f"{doctype} {row.role} L{row.permlevel} {f}")

    def test_frozen_own_doctype_follows_json_and_keeps_ess(self):
        for dt in ("Chapter", "Team", "Volunteer", "Expense Category"):
            with self.subTest(doctype=dt):
                self._freeze_via_user_type_path(dt)
                self._flip_json_write_flags(dt)
                _run_permission_sync()
                self._assert_effective_matches_json(dt)
                ess = [p for p in _effective(dt) if p.role == "Employee Self Service"]
                self.assertEqual([cint(p.select) for p in ess], [1], "ESS select row must survive")

    def test_reconcile_inserts_json_row_missing_from_custom_set(self):
        self._freeze_via_user_type_path("Team")
        victim = frappe.get_all("DocPerm", filters={"parent": "Team"}, fields=["role", "permlevel"])[0]
        frappe.db.delete("Custom DocPerm", {"parent": "Team", "role": victim.role,
                                            "permlevel": victim.permlevel})
        self.assertFalse(any(p.role == victim.role and cint(p.permlevel) == cint(victim.permlevel)
                             for p in _effective("Team")))
        _run_permission_sync()
        self._assert_effective_matches_json("Team")

    def test_role_not_in_json_survives_reconcile(self):
        # Member is frozen by design by the public document creator setup (add_permission
        # for a role the JSON does not declare). Its grant must outlive the reconcile.
        role = frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert()
        from frappe.permissions import add_permission, update_permission_property

        self._drop_custom("Member")
        add_permission("Member", role.name, 0)
        update_permission_property("Member", role.name, 0, "create", 1, validate=False)
        self._flip_json_write_flags("Member")
        _run_permission_sync()
        self._assert_effective_matches_json("Member")
        mine = [p for p in _effective("Member") if p.role == role.name]
        self.assertEqual([(cint(p.read), cint(p.create)) for p in mine], [(1, 1)])

    def test_own_doctype_without_custom_rows_is_left_alone(self):
        self._drop_custom("Membership Type")
        _run_permission_sync()
        self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": "Membership Type"}), 0)
