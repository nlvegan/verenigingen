"""#2703: the routes #2600's validate guard skips (it returns early for new docs) are still refused.

Measured on test_site_8 (developer_mode=1; the result does not depend on it): a NEW Expense Claim
filed under another person's Employee, an AMEND of a cancelled claim that swaps ``employee``, and a
Data Import row (insert or update) are all refused before this app's own guard is needed, by TWO
independent layers, each of which alone is enough: (a) Frappe's create/write check, whose controller
hook ``verenigingen.permissions.has_expense_claim_permission`` denies unless the claimant is the
employee's user, staff, or an Expense Approver who sees the claim's chapter; (b) HRMS's
``ExpenseClaim.validate_employee_scope`` ("not allowed to create or modify an Expense Claim for
Employee X"; it skips under ``ignore_permissions``). Mutating away BOTH reddens the new-claim,
amend and import-insert tests (measured); mutating only one leaves them green, so no single-layer
mutant is discriminating. No code change was needed; this module pins the refusals and the
legitimate filings beside them. A peer amending a STRANGER's cancelled claim onto their OWN
employee succeeds and is deliberately not pinned here (#3035).

Attackers are real users with the Volunteer profile's roles; nothing runs as Administrator.
Probe shortcuts, stated: the amended-from claim is made ``docstatus=2`` with ``db.set_value``
(a real cancel needs an approved, submitted claim; the amend path under test starts at the new
document); the Data Import rows go through ``Importer.insert_record``/``update_record`` on a bare
Importer (the importer's own file parsing and commits are not under test, and it calls plain
``insert()``/``save()`` with no ``ignore_permissions``, read in frappe/core/doctype/data_import/importer.py).
"""

import frappe
from frappe.core.doctype.data_import.importer import Importer

from verenigingen.tests.security.test_member_files_chapter_claim_2528 import MemberClaimBase

PERMISSION = (frappe.PermissionError, frappe.ValidationError)


class TestExpenseClaimEmployeeRoutes2703(MemberClaimBase):
    def setUp(self):
        super().setUp()
        self.peer, self.peer_emp, _member, _vol = self._person("peer2703")
        self.staff = self._staffexp_user("Verenigingen Staff", "stf2703", extra_roles=("Verenigingen Administrator",))
        self.staff_emp = self._staffexp_employee(self.staff)
        self.importer = self._bare_importer()

    def _bare_importer(self):
        importer = Importer.__new__(Importer)
        importer.doctype = "Expense Claim"
        importer._uses_tree_aliases = False
        importer.data_import = frappe._dict(doctype="Data Import", name="x2703", submit_after_import=0)
        return importer

    def _claims_for(self, employee):
        return frappe.get_all("Expense Claim", filters={"employee": employee.name}, pluck="name")

    def _insert_as(self, actor, employee, **fields):
        return self.act_as(actor, lambda: frappe.get_doc(self.claim_data(employee=employee, **fields)).insert())

    def _cancelled_claim_of(self, user, employee):
        original = self._insert_as(user, employee)
        # probe shortcut (module docstring): stands in for submit + cancel
        frappe.db.set_value("Expense Claim", original.name, "docstatus", 2)
        return original

    # route 1: a new claim under another person's Employee
    def test_a_peer_cannot_file_a_new_claim_under_another_employee(self):
        for fields in ({}, {"custom_chapter": self.chapter.name}):
            with self.subTest(fields=fields), self.assertRaises(PERMISSION):
                self._insert_as(self.user, self.peer_emp, **fields)
        self.assertEqual(self._claims_for(self.peer_emp), [])

    def test_control_the_member_files_their_own_new_claim(self):
        for fields in ({}, {"custom_chapter": self.chapter.name}):
            with self.subTest(fields=fields):
                if fields:
                    self.join(self.member.name, self.chapter)
                claim = self._insert_as(self.user, self.employee, **fields)
                self.assertEqual(claim.employee, self.employee.name)

    def test_control_staff_files_for_another_employee(self):
        claim = self._insert_as(self.staff, self.peer_emp)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "employee"), self.peer_emp.name)

    def test_control_the_chapters_approver_files_a_chapter_claim_for_a_member(self):
        claim = self._insert_as(self.fin_user, self.peer_emp, custom_chapter=self.chapter.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "employee"), self.peer_emp.name)

    def test_an_expense_approver_without_the_chapter_cannot_file_for_another_employee(self):
        other_user, _other_emp, _m, _v = self._person("apr2703", extra_roles=("Expense Approver",))
        with self.assertRaises(PERMISSION):
            self._insert_as(other_user, self.peer_emp, custom_chapter=self.chapter.name)
        self.assertEqual(self._claims_for(self.peer_emp), [])

    # route 2: amend from a cancelled claim, changing employee
    def test_a_peer_cannot_amend_a_cancelled_claim_onto_another_employee(self):
        original = self._cancelled_claim_of(self.user, self.employee)
        with self.assertRaises(PERMISSION):
            self._insert_as(self.user, self.peer_emp, amended_from=original.name)
        self.assertEqual(self._claims_for(self.peer_emp), [])

    def test_control_the_claimant_amends_their_own_cancelled_claim(self):
        original = self._cancelled_claim_of(self.user, self.employee)
        amended = self._insert_as(self.user, self.employee, amended_from=original.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", amended.name, "amended_from"), original.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", amended.name, "employee"), self.employee.name)

    # route 3: Data Import (plain insert()/save() as the importing user)
    def test_data_import_needs_import_permission_a_member_lacks(self):
        self.assertFalse(self.act_as(self.user, lambda: frappe.has_permission("Expense Claim", "import")))

    def test_data_import_cannot_insert_a_claim_under_another_employee(self):
        row = frappe._dict(self.claim_data(employee=self.peer_emp))
        row.pop("doctype")
        with self.assertRaises(PERMISSION):
            self.act_as(self.user, lambda: self.importer.insert_record(row))
        self.assertEqual(self._claims_for(self.peer_emp), [])

    def test_data_import_cannot_repoint_an_existing_claim(self):
        claim = self._insert_as(self.user, self.employee)
        row = frappe._dict(name=claim.name, employee=self.peer_emp.name)
        with self.assertRaises(PERMISSION):
            self.act_as(self.user, lambda: self.importer.update_record(row))
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "employee"), self.employee.name)

    def test_control_data_import_inserts_and_updates_the_importers_own_claim(self):
        row = frappe._dict(self.claim_data(employee=self.employee))
        row.pop("doctype")
        created = self.act_as(self.user, lambda: self.importer.insert_record(row))
        self.assertEqual(created.employee, self.employee.name)
        updated = self.act_as(
            self.user, lambda: self.importer.update_record(frappe._dict(name=created.name, remark="imported"))
        )
        self.assertEqual(frappe.db.get_value("Expense Claim", updated.name, "remark"), "imported")
