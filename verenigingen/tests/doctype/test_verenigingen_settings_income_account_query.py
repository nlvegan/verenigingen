"""#831: the Income Account picker must key on root_type, not account_type.

ERPNext's standard chart leaves ``account_type`` EMPTY on income leaves (they carry
``root_type = "Income"``), so a filter on ``account_type = 'Income Account'`` returns an
empty dropdown on a standard chart. The leaves below are created exactly that way:
under the company's Income root, with no account_type.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import suspend_insert_capture
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings import (
    get_income_account_query,
)

_MARK = "Test831"


class TestIncomeAccountQueryStandardChart(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with suspend_insert_capture():
            cls.company = get_eur_test_company()

    def _root(self, root_type):
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": root_type, "is_group": 1, "parent_account": ["is", "not set"]},
            "name",
            order_by="name asc",
        )

    def _leaf(self, label, parent, is_group=0):
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"{_MARK} {label}",
                "company": self.company,
                "parent_account": parent,
                "is_group": is_group,
            }
        )
        doc.insert()
        self.track_doc("Account", doc.name)
        return doc

    def _query(self, txt=_MARK):
        rows = get_income_account_query("Account", txt, "name", 0, 50, {"company": self.company})
        return [r[0] for r in rows]

    def test_untyped_income_leaf_is_offered_and_non_income_is_not(self):
        income_leaf = self._leaf("Income Leaf", self._root("Income"))
        income_group = self._leaf("Income Group", self._root("Income"), is_group=1)
        expense_leaf = self._leaf("Expense Leaf", self._root("Expense"))

        # Precondition: this is the standard-chart shape, not a hand-typed account.
        self.assertFalse(income_leaf.account_type)
        self.assertEqual(income_leaf.root_type, "Income")

        offered = self._query()
        self.assertIn(income_leaf.name, offered)
        # Controls, each with a real row for the wrong behaviour to find.
        self.assertNotIn(income_group.name, offered, "group accounts are not selectable")
        self.assertNotIn(expense_leaf.name, offered, "a non-income leaf must not be offered")

    def test_scoped_to_the_requested_company(self):
        income_leaf = self._leaf("Income Leaf", self._root("Income"))
        other_name = frappe.db.get_value(
            "Account",
            {"company": ["!=", self.company], "root_type": "Income", "is_group": 0},
            "account_name",
        )
        self.assertTrue(other_name, "control needs an income leaf in another company")
        # Searching by the OTHER company's account name must not surface it here.
        other = frappe.db.get_value(
            "Account", {"account_name": other_name, "company": ["!=", self.company]}, "name"
        )
        self.assertNotIn(other, self._query(txt=other_name))
        self.assertIn(income_leaf.name, self._query())
