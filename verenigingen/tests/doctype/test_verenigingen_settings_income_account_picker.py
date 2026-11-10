"""#831 / #2288: the dues income account pickers offer only the settings company's income leaves.

``chapter_dues_income_account`` and ``national_dues_income_account`` carry ``link_filters`` on the
DocType. The Link control (frappe/public/js/frappe/form/controls/link.js) turns those into the
``filters`` argument of ``frappe.desk.search.search_link``. Only that translation (resolving
``eval:doc.company`` against the form's doc) happens in the browser, so ``_picker_filters`` below
re-implements it in Python for the one ``eval:doc.<field>`` shape the DocType uses; everything after
it (the real search_link query against real Account rows) is the server path.

The accounts are created the way ERPNext's standard chart creates them: under the Income / Expense
root with NO account_type. A filter on ``account_type = 'Income Account'`` would offer none of them.
"""

import json

import frappe
from frappe.desk.search import search_link

from verenigingen.tests.fixtures.enhanced_test_factory import suspend_insert_capture
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.base import VereningingenTestCase

_MARK = "Test831Picker"
_FIELDS = ("chapter_dues_income_account", "national_dues_income_account")


class TestDuesIncomeAccountPickers(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with suspend_insert_capture():
            cls.company = get_eur_test_company()

    def _root_account(self, company, root_type):
        return frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ["is", "not set"]},
            "name",
            order_by="name asc",
        )

    def _make_untyped_standard_chart_account_831(self, label, company, root_type, is_group=0):
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"{_MARK} {label}",
                "company": company,
                "parent_account": self._root_account(company, root_type),
                "is_group": is_group,
            }
        )
        doc.insert()
        self.track_doc("Account", doc.name)
        return doc

    def _other_company(self):
        name = frappe.db.get_value(
            "Account",
            {"company": ["!=", self.company], "root_type": "Income", "is_group": 1},
            "company",
        )
        self.assertTrue(name, "control needs a second company with a chart of accounts")
        return name

    def _picker_filters(self, fieldname):
        """The ``filters`` the Link control would send for ``fieldname`` on the settings form."""
        link_filters = frappe.get_meta("Verenigingen Settings").get_field(fieldname).link_filters
        self.assertTrue(link_filters, f"{fieldname} has no link_filters")
        form_doc = frappe.get_single("Verenigingen Settings")
        form_doc.company = self.company
        filters = {}
        for _doctype, key, operator, value in json.loads(link_filters):
            if isinstance(value, str) and value.startswith("eval:doc."):
                value = form_doc.get(value[len("eval:doc.") :])
            filters[key] = [operator, value]
        return filters

    def _offered(self, fieldname):
        results = search_link("Account", _MARK, filters=self._picker_filters(fieldname), page_length=50)
        return {r["value"] for r in results}

    def test_picker_offers_only_this_companys_income_leaves(self):
        income_leaf = self._make_untyped_standard_chart_account_831("Income Leaf", self.company, "Income")
        income_group = self._make_untyped_standard_chart_account_831(
            "Income Group", self.company, "Income", is_group=1
        )
        expense_leaf = self._make_untyped_standard_chart_account_831("Expense Leaf", self.company, "Expense")
        other_leaf = self._make_untyped_standard_chart_account_831(
            "Other Company Income Leaf", self._other_company(), "Income"
        )

        # Precondition: the standard-chart shape, not a hand-typed account.
        self.assertFalse(income_leaf.account_type)
        self.assertEqual(income_leaf.root_type, "Income")

        for fieldname in _FIELDS:
            with self.subTest(field=fieldname):
                self.assertEqual(self._offered(fieldname), {income_leaf.name})
                # Unfiltered, the search does find every one of them: the controls have rows to find.
                everything = {
                    r["value"] for r in search_link("Account", _MARK, filters={}, page_length=50)
                }
                self.assertTrue(
                    {income_group.name, expense_leaf.name, other_leaf.name} <= everything
                )
