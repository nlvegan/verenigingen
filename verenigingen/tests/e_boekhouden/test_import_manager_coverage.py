"""
Coverage tests for
verenigingen/e_boekhouden/utils/import_manager.py

The clean/update import paths drive the live eBoekhouden REST iterator and the
destructive ``nuke_all_financial_data`` utility, so they are out of scope for a
unit suite. What we CAN test for real:

    * EBoekhoudenImportManager.__init__   - resolves company from
      E-Boekhouden Settings.default_company (regression for the AttributeError
      bug where it read the non-existent ``company`` field).
    * get_import_status                   - real DB counts + last-import SQL.
    * _get_existing_imports               - real DB query over imported docs.
    * _needs_update                       - pure comparison of a doc vs a
      mutation-detail dict.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_import_manager_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.import_manager import EBoekhoudenImportManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    name = "EBkh ImpMgr Co"
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = "EIMC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class _ImpMgrBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def setUp(self):
        super().setUp()
        # The manager reads E-Boekhouden Settings.default_company. Pin it so
        # instantiation is deterministic regardless of site config.
        self._orig_default_company = frappe.db.get_single_value(
            "E-Boekhouden Settings", "default_company"
        )
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", self.company)

    def tearDown(self):
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "default_company", self._orig_default_company
        )
        super().tearDown()


class TestImportManagerInit(_ImpMgrBase):
    def test_init_resolves_company_from_default_company(self):
        # REGRESSION GUARD: previously read self.settings.company (no such field)
        # and raised AttributeError, making the whole manager uninstantiable.
        with self.assertNoErrorLog():
            manager = EBoekhoudenImportManager()
        self.assertEqual(manager.company, self.company)


class TestGetImportStatus(_ImpMgrBase):
    def test_status_shape_and_counts(self):
        manager = EBoekhoudenImportManager()
        with self.assertNoErrorLog():
            status = manager.get_import_status()
        self.assertIn("total_imported", status)
        self.assertIn("by_type", status)
        # All four labelled doctypes appear in the breakdown
        for label in ("Sales Invoices", "Purchase Invoices", "Payments", "Journal Entries"):
            self.assertIn(label, status["by_type"])
        # total_imported is the sum of the per-type counts
        self.assertEqual(status["total_imported"], sum(status["by_type"].values()))

    def test_date_range_defaults(self):
        manager = EBoekhoudenImportManager()
        status = manager.get_import_status()
        self.assertEqual(status["date_range"]["from"], "All time")
        self.assertEqual(status["date_range"]["to"], "Current")

        status2 = manager.get_import_status(from_date="2025-01-01", to_date="2025-12-31")
        self.assertEqual(status2["date_range"]["from"], "2025-01-01")
        self.assertEqual(status2["date_range"]["to"], "2025-12-31")


class TestGetExistingImports(_ImpMgrBase):
    def _make_imported_journal_entry(self, mutation_nr):
        """A minimal submitted-less JE tagged with an eBoekhouden mutation nr.

        We keep it a draft (no submit) so we avoid Fiscal Year / Cost Center
        requirements; _get_existing_imports filters only on the mutation field
        and posting_date, not on docstatus.
        """
        cash = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Cash", "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Asset", "is_group": 0}, "name"
        )
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = "2025-06-15"
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = mutation_nr
        je.append("accounts", {"account": cash, "debit_in_account_currency": 10})
        je.append("accounts", {"account": cash, "credit_in_account_currency": 10})
        je.insert(ignore_permissions=True)
        return je.name

    def test_existing_imports_includes_tagged_journal_entry(self):
        je_name = self._make_imported_journal_entry("99887766")
        manager = EBoekhoudenImportManager()
        existing = manager._get_existing_imports()
        names = {d["name"] for d in existing}
        self.assertIn(je_name, names)
        # The mutation id is coerced to int
        entry = next(d for d in existing if d["name"] == je_name)
        self.assertEqual(entry["mutation_id"], 99887766)
        self.assertEqual(entry["doctype"], "Journal Entry")

    def test_date_filter_excludes_out_of_range(self):
        je_name = self._make_imported_journal_entry("55443322")
        manager = EBoekhoudenImportManager()
        # JE posting_date is 2025-06-15; a window after it must exclude it.
        existing = manager._get_existing_imports(from_date="2025-07-01")
        names = {d["name"] for d in existing}
        self.assertNotIn(je_name, names)


class TestNeedsUpdate(_ImpMgrBase):
    def _make_je(self, mutation_nr, remark="orig remark"):
        cash = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Asset", "is_group": 0}, "name"
        )
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = "2025-06-15"
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = mutation_nr
        je.user_remark = remark
        je.append("accounts", {"account": cash, "debit_in_account_currency": 10})
        je.append("accounts", {"account": cash, "credit_in_account_currency": 10})
        je.insert(ignore_permissions=True)
        return je.name

    def test_empty_mutation_detail_returns_false(self):
        je_name = self._make_je("31313131")
        manager = EBoekhoudenImportManager()
        doc_info = {"doctype": "Journal Entry", "name": je_name}
        # No keys in mutation detail => no checks accumulated => no update needed.
        self.assertFalse(manager._needs_update(doc_info, {}))

    def test_je_lacks_amount_and_remarks_fields_so_those_signals_are_ignored(self):
        # Journal Entry has neither 'grand_total' nor 'remarks' (it uses
        # 'user_remark'), so the amount/description branches are hasattr-guarded
        # OFF for JE: even mismatching values must NOT trigger an update. This
        # pins the hasattr guard behavior (a regression that dropped the guards
        # would raise AttributeError or return True here).
        je_name = self._make_je("32323232", remark="hello")
        manager = EBoekhoudenImportManager()
        doc_info = {"doctype": "Journal Entry", "name": je_name}
        with self.assertNoErrorLog():
            self.assertFalse(
                manager._needs_update(
                    doc_info,
                    {"amount": 999999, "description": "TOTALLY DIFFERENT"},
                )
            )

    def test_je_has_no_items_so_regels_count_signal_is_ignored(self):
        # JE exposes 'accounts', not 'items', so the Regels-vs-items length check
        # is skipped and a differing Regels count does not request an update.
        je_name = self._make_je("33333333")
        manager = EBoekhoudenImportManager()
        doc_info = {"doctype": "Journal Entry", "name": je_name}
        self.assertFalse(
            manager._needs_update(doc_info, {"Regels": [{"a": 1}, {"b": 2}, {"c": 3}]})
        )


if __name__ == "__main__":
    unittest.main()
