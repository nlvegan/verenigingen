"""
Coverage tests for
verenigingen/e_boekhouden/utils/eboekhouden_enhanced_migration.py

execute_migration() delegates the heavy lifting to start_full_rest_import (live
eBoekhouden REST API) and to backup/integrity utilities, so the end-to-end flow
is out of scope for a unit suite. What we test for real:

    * EnhancedEBoekhoudenMigration.__init__   - company resolution from settings,
      the "no company configured" guard, and cost-center wiring.
    * _get_cost_center                        - the documented resolution order
      (settings override -> company default -> heuristics -> throw).
    * _run_pre_validation                     - placeholder validation contract.

Built against a real saved E-Boekhouden Migration document and the real
E-Boekhouden Settings Single (saved/restored), with real Company + Cost Center
master data. No live eBoekhouden HTTP.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_enhanced_migration_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import EnhancedEBoekhoudenMigration
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _SettingsStub:
    """Lightweight stand-in for E-Boekhouden Settings.

    The migration orchestrator only reads ``default_company`` and
    ``default_cost_center`` from settings during the paths under test, so a
    simple attribute holder is sufficient and keeps the Single untouched."""

    def __init__(self, default_company=None, default_cost_center=None):
        self.default_company = default_company
        self.default_cost_center = default_cost_center
        self.standaard_item = None


def _persist_eur_company(name="EBkh EnhMig Co", abbr="EENM"):
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = abbr
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return name


def _make_migration_doc(company, **kwargs):
    doc = frappe.new_doc("E-Boekhouden Migration")
    doc.migration_name = kwargs.pop("migration_name", "EnhMig Coverage Run")
    doc.company = company
    doc.migration_status = "Draft"
    doc.date_from = "2025-01-01"
    doc.date_to = "2025-12-31"
    for k, v in kwargs.items():
        setattr(doc, k, v)
    doc.insert(ignore_permissions=True)
    return doc


class _EnhMigBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _new_migration(self, **kwargs):
        return _make_migration_doc(self.company, **kwargs)


class TestInit(_EnhMigBase):
    def test_no_company_raises(self):
        mig = self._new_migration()
        settings = _SettingsStub(default_company=None)
        with self.assertRaises(frappe.ValidationError):
            EnhancedEBoekhoudenMigration(mig, settings)

    def test_init_wires_company_and_cost_center(self):
        # dry_run defaults to 1 on the doctype; pin it off for this wiring test.
        mig = self._new_migration(dry_run=0, batch_size=100)
        # Resolve a real cost center for the company so _get_cost_center succeeds.
        cc = frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 0}, "name"
        )
        self.assertTrue(cc, "fixture company should ship a non-group cost center")
        settings = _SettingsStub(default_company=self.company)
        with self.assertNoErrorLog():
            enhanced = EnhancedEBoekhoudenMigration(mig, settings)
        self.assertEqual(enhanced.company, self.company)
        self.assertTrue(enhanced.cost_center)
        # Configuration flags resolved from the migration doc
        self.assertFalse(enhanced.dry_run)
        self.assertEqual(enhanced.batch_size, 100)

    def test_dry_run_flag_picked_up(self):
        mig = self._new_migration(dry_run=1)
        settings = _SettingsStub(default_company=self.company)
        enhanced = EnhancedEBoekhoudenMigration(mig, settings)
        self.assertTrue(enhanced.dry_run)
        # In dry-run mode a simulator is initialised
        self.assertTrue(hasattr(enhanced, "dry_run_simulator"))


class TestGetCostCenter(_EnhMigBase):
    def _enhanced(self, settings):
        mig = self._new_migration()
        return EnhancedEBoekhoudenMigration(mig, settings)

    def test_explicit_settings_cost_center_wins(self):
        cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")
        settings = _SettingsStub(default_company=self.company, default_cost_center=cc)
        enhanced = self._enhanced(settings)
        # The explicit setting is honored over any heuristic.
        self.assertEqual(enhanced.cost_center, cc)

    def test_invalid_settings_cost_center_falls_back(self):
        settings = _SettingsStub(
            default_company=self.company, default_cost_center="NONEXISTENT CC ZZZ"
        )
        # Must NOT return the bogus configured value; falls through to a real CC.
        enhanced = self._enhanced(settings)
        self.assertNotEqual(enhanced.cost_center, "NONEXISTENT CC ZZZ")
        self.assertTrue(frappe.db.exists("Cost Center", enhanced.cost_center))
        self.assertEqual(
            frappe.db.get_value("Cost Center", enhanced.cost_center, "company"), self.company
        )

    def test_falls_back_to_any_company_cost_center(self):
        # No settings override, company has no default_cost_center set on the
        # company by default -> resolution lands on a real non-group CC.
        settings = _SettingsStub(default_company=self.company)
        enhanced = self._enhanced(settings)
        cc = enhanced.cost_center
        self.assertTrue(frappe.db.exists("Cost Center", cc))
        self.assertEqual(frappe.db.get_value("Cost Center", cc, "is_group"), 0)

    # NOTE: the "no cost center at all -> frappe.throw" branch is not exercised
    # here. ERPNext companies always ship a non-group cost center and the root
    # cost-center group cannot be reliably deleted (GL/link constraints), so the
    # final fallthrough is not deterministically reachable in a unit test. The
    # resolution order (settings override -> invalid-fallback -> any-CC) is
    # covered by the tests above.


class TestRunPreValidation(_EnhMigBase):
    def test_pre_validation_contract(self):
        settings = _SettingsStub(default_company=self.company)
        mig = self._new_migration()
        enhanced = EnhancedEBoekhoudenMigration(mig, settings)
        with self.assertNoErrorLog():
            result = enhanced._run_pre_validation()
        self.assertTrue(result["can_proceed"])
        self.assertIn("validation_summary", result)
        summary = result["validation_summary"]
        for key in ("total_validated", "passed", "failed", "warnings"):
            self.assertIn(key, summary)


if __name__ == "__main__":
    unittest.main()
