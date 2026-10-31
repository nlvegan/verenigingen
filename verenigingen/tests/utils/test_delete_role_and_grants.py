"""#1665: deleting a test Role must not leave `Has Role` rows behind.

Frappe's Role has no `on_trash` that calls `remove_roles()`, so a bare force-delete leaves
the row on every user that held the role, and the next `User.save()` of that user (the
harness re-saves Administrator in `before_tests`) raises "Could not find Row #N: Role: ...".
"""

import ast
from pathlib import Path

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.force_delete import delete_role_and_grants
from verenigingen.tests.utils.paths import APP_ROOT


def _raw_role_deletes(source):
    """Line numbers of `<x>.delete_doc("Role", ...)` calls in `source`."""
    return [
        n.lineno
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "delete_doc"
        and (
            (n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "Role")
            or any(
                k.arg == "doctype" and isinstance(k.value, ast.Constant) and k.value.value == "Role"
                for k in n.keywords
            )
        )
    ]


class TestDeleteRoleAndGrants(VereningingenTestCase):
    def _role_held_by_a_user(self):
        suffix = frappe.generate_hash(length=8)
        role = frappe.get_doc({"doctype": "Role", "role_name": f"zzz-1665-{suffix}"}).insert()
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"zzz-1665-{suffix}@test.invalid",
                "first_name": "Roleholder",
                "send_welcome_email": 0,
            }
        ).insert()
        self.track_doc("User", user.name)
        user.add_roles(role.name)
        self.assertEqual(frappe.db.count("Has Role", {"role": role.name}), 1, "precondition")
        return role.name, user.name

    def test_the_raw_force_delete_leaves_the_row_and_breaks_the_next_user_save(self):
        """Control: the old teardown shape reproduces the defect, so the tests below can fail."""
        role, user = self._role_held_by_a_user()
        try:
            frappe.delete_doc("Role", role, force=True)
            self.assertEqual(frappe.db.count("Has Role", {"role": role}), 1)
            with self.assertRaises(frappe.LinkValidationError) as caught:
                frappe.get_doc("User", user).save()
            self.assertIn(role, str(caught.exception))
        finally:
            frappe.db.delete("Has Role", {"role": role})

    def test_the_helper_leaves_no_has_role_rows_and_the_user_still_saves(self):
        role, user = self._role_held_by_a_user()
        delete_role_and_grants(role)
        self.assertFalse(frappe.db.exists("Role", role))
        self.assertEqual(frappe.db.count("Has Role", {"role": role}), 0)
        frappe.get_doc("User", user).save()

    def test_the_helper_leaves_other_roles_of_the_same_user_alone(self):
        role, user = self._role_held_by_a_user()
        other = frappe.get_doc(
            {"doctype": "Role", "role_name": f"zzz-1665-other-{frappe.generate_hash(length=8)}"}
        ).insert()
        self.track_doc("Role", other.name)
        frappe.get_doc("User", user).add_roles(other.name)
        delete_role_and_grants(role)
        self.assertEqual(frappe.db.count("Has Role", {"parent": user, "role": other.name}), 1)

    def test_no_test_deletes_a_role_without_going_through_the_helper(self):
        """Shape guard (#1665): no new `delete_doc("Role", ...)` / `delete_doc(doctype="Role", ...)`.

        This is NOT a class guard. A variable doctype, `get_doc("Role", r).delete()`,
        `db.delete("Role")`, an aliased `delete_doc` and raw SQL all evade it. It only stops a new
        copy of the exact form this fix replaced. The generic drains are tracked in #1856.
        """
        self.assertEqual(_raw_role_deletes('frappe.delete_doc("Role", r, force=True)'), [1], "control")
        self.assertEqual(_raw_role_deletes('frappe.delete_doc(doctype="Role", name=r)'), [1], "control")
        offenders = []
        for path in (APP_ROOT / "verenigingen" / "tests").rglob("*.py"):
            # force_delete.py is the helper; this file holds the deliberate raw-delete control.
            if path.name in ("force_delete.py", Path(__file__).name):
                continue
            for line in _raw_role_deletes(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{line}")
        self.assertEqual(offenders, [], "use force_delete.delete_role_and_grants for Role teardown")
