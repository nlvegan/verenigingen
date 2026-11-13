"""#1655: a hand-made Employee must not pin its linked user to itself through a User Permission.

Real flow: the Employee is inserted through the document API exactly as the desk form does
(``user_id`` set, ``create_user_permission`` left out so the DocType default of 1 applies), and
the harm is measured at the doc-level read of ANOTHER employee's Expense Claim by a Treasurer
(HR Manager) user.

Probe shortcut, stated: the claimant's Employee is built with ``create_user_permission=0`` (as the
app's own paths do) so only the Employee under test carries the default.
"""

import time

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.security.test_staff_expense_approval_1606 import _roles_shipped_for_profile
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestEmployeeUserPermissionDefault1655(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.company = get_eur_test_company()
        self.expense_account = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
        )
        self.payable_account = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Payable", "is_group": 0}, "name"
        )
        self.assertTrue(self.expense_account and self.payable_account, "fixture company lacks accounts")
        self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
        self.expense_type = self._make_claim_type_1655()
        self.treasurer = self.create_test_user(
            email=f"x1655-treas-{self.token}@test.com",
            roles=_roles_shipped_for_profile("Verenigingen Treasurer"),
        )
        self.claimant = self.create_test_user(
            email=f"x1655-claim-{self.token}@test.com", roles=["Verenigingen Volunteer"]
        )
        self.claimant_emp = self._employee_1655(self.claimant, create_user_permission=0)
        self.claim = self._claim_1655(self.claimant_emp)

    # ---------------------------------------------------------------- fixtures
    def _make_claim_type_1655(self):
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": f"T1655 {self.token}",
                "accounts": [{"company": self.company, "default_account": self.expense_account}],
            }
        ).insert()
        self._track_test_document("Expense Claim Type", doc.name, priority=1)
        return doc.name

    def _employee_1655(self, user, **extra):
        """Inserted like the desk form: only the fields the form asks for, user_id linked."""
        data = {
            "doctype": "Employee",
            "first_name": f"E{frappe.generate_hash(length=5)}",
            "gender": "Other",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
            "status": "Active",
            "company": self.company,
            "user_id": user.name,
        }
        data.update(extra)
        emp = frappe.get_doc(data).insert()
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _claim_1655(self, employee):
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": self.company,
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": self.payable_account,
                "cost_center": self.cost_center,
                "approval_status": "Draft",
                "expenses": [
                    {
                        "expense_type": self.expense_type,
                        "amount": 12.5,
                        "sanctioned_amount": 12.5,
                        "expense_date": today(),
                        "default_account": self.expense_account,
                        "cost_center": self.cost_center,
                    }
                ],
            }
        ).insert()
        self._track_test_document("Expense Claim", doc.name, priority=6)
        return doc

    def _user_permissions(self, user):
        return frappe.get_all(
            "User Permission", filters={"user": user.name}, fields=["allow", "for_value"], limit_page_length=0
        )

    def _treasurer_can_read_claim(self):
        return frappe.has_permission("Expense Claim", "read", doc=self.claim.name, user=self.treasurer.name)

    def _insert_as(self, actor_user, target_user, **extra):
        original = frappe.session.user
        frappe.set_user(actor_user)
        try:
            return self._employee_1655(target_user, **extra)
        finally:
            frappe.set_user(original)

    # ------------------------------------------------------------------- tests
    def test_control_the_treasurer_reads_the_claim_without_a_user_permission(self):
        self.assertEqual(self._user_permissions(self.treasurer), [])
        self.assertTrue(self._treasurer_can_read_claim())

    def test_hand_insert_with_the_default_creates_no_user_permission(self):
        emp = self._employee_1655(self.treasurer)
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 0)
        self.assertEqual(self._user_permissions(self.treasurer), [])

    def test_treasurer_with_a_hand_made_employee_still_reads_another_employees_claim(self):
        self._employee_1655(self.treasurer)
        self.assertTrue(self._treasurer_can_read_claim())

    def test_an_explicit_create_user_permission_on_insert_is_forced_to_zero(self):
        emp = self._employee_1655(self.treasurer, create_user_permission=1)
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 0)
        self.assertEqual(self._user_permissions(self.treasurer), [])

    def test_the_hook_does_not_depend_on_who_inserts(self):
        """Administrator and an HR Manager acting user both get 0 (kills an 'only for role X' hook)."""
        hr_actor = self.create_test_user(email=f"x1655-hr-{self.token}@test.com", roles=["HR Manager"])
        for actor in ("Administrator", hr_actor.name):
            target = self.create_test_user(
                email=f"x1655-t-{frappe.generate_hash(length=5)}-{self.token}@test.com",
                roles=["Verenigingen Volunteer"],
            )
            emp = self._insert_as(actor, target)
            self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 0, actor)
            self.assertEqual(self._user_permissions(target), [], actor)

    def test_an_employee_inserted_without_a_user_id_also_gets_zero(self):
        """Every new Employee, not only those with a linked user (ruling: EVERY new Employee)."""
        no_user = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"N{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": self.company,
            }
        ).insert()
        self._track_test_document("Employee", no_user.name, priority=2)
        self.assertEqual(frappe.db.get_value("Employee", no_user.name, "create_user_permission"), 0)

    def test_control_staff_can_still_add_a_user_permission_deliberately(self):
        self._employee_1655(self.treasurer)
        frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": self.treasurer.name,
                "allow": "Employee",
                "for_value": self.claimant_emp.name,
                "apply_to_all_doctypes": 1,
            }
        ).insert()
        self.assertEqual(
            [(p.allow, p.for_value) for p in self._user_permissions(self.treasurer)],
            [("Employee", self.claimant_emp.name)],
        )

    def test_control_ticking_the_box_on_update_still_creates_the_permission(self):
        """Insert only: a later deliberate tick is honoured, not reset."""
        emp = self._employee_1655(self.treasurer)
        emp.reload()
        emp.create_user_permission = 1
        emp.save()
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 1)
        self.assertIn(("Employee", emp.name), [(p.allow, p.for_value) for p in self._user_permissions(self.treasurer)])
        self.assertFalse(self._treasurer_can_read_claim(), "control: the permission really hides the claim")
