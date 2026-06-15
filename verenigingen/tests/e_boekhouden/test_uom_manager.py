"""
Integration tests for verenigingen/e_boekhouden/utils/uom_manager.py

UOMManager creates UOM / UOM Conversion Factor master data from Dutch unit
strings. Tests run against the real DB (no HTTP). UOMManager.__init__ calls
ensure_base_uoms_exist(), so constructing one is itself a creation path.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_uom_manager
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.uom_manager import (
    UOMManager,
    map_unit_of_measure,
    setup_dutch_uoms,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestUOMManagerStatic(unittest.TestCase):
    """get_uom_for_category is a pure staticmethod."""

    def test_known_groups(self):
        self.assertEqual(UOMManager.get_uom_for_category("Services"), "Hour")
        self.assertEqual(UOMManager.get_uom_for_category("Products"), "Unit")
        self.assertEqual(UOMManager.get_uom_for_category("Consumable"), "Unit")

    def test_unknown_group_defaults_unit(self):
        self.assertEqual(UOMManager.get_uom_for_category("Nonexistent Group"), "Unit")


class TestUOMManagerMapping(EnhancedTestCase):
    """map_uom against the real DB - creates UOMs as needed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = UOMManager()

    def test_direct_dutch_mappings(self):
        self.assertEqual(self.manager.map_uom("uur"), "Hour")
        self.assertEqual(self.manager.map_uom("stuks"), "Nos")
        self.assertEqual(self.manager.map_uom("kg"), "Kg")
        self.assertEqual(self.manager.map_uom("maand"), "Month")

    def test_case_insensitive_and_trimmed(self):
        self.assertEqual(self.manager.map_uom("  UUR  "), "Hour")
        self.assertEqual(self.manager.map_uom("Liter"), "Litre")

    def test_empty_defaults_to_nos(self):
        self.assertEqual(self.manager.map_uom(""), "Nos")
        self.assertEqual(self.manager.map_uom(None), "Nos")

    def test_mapped_uom_exists_in_db(self):
        result = self.manager.map_uom("jaar")
        self.assertEqual(result, "Year")
        self.assertTrue(frappe.db.exists("UOM", "Year"))

    def test_already_valid_erpnext_uom_passthrough(self):
        # "Nos" is a standard ERPNext UOM and is not in the Dutch map keys
        self.assertTrue(frappe.db.exists("UOM", "Nos"))
        self.assertEqual(self.manager.map_uom("Nos"), "Nos")

    def test_unmapped_creates_custom_uom(self):
        custom = "EBkhCustomUomXyz"
        frappe.db.delete("UOM", {"uom_name": custom})
        result = self.manager.map_uom(custom)
        self.assertEqual(result, custom)
        self.assertTrue(frappe.db.exists("UOM", custom))

    def test_module_level_map_function(self):
        self.assertEqual(map_unit_of_measure("week"), "Week")


class TestUOMManagerSetup(EnhancedTestCase):
    """Base UOM + conversion setup creates master data without error."""

    def test_ensure_base_uoms_exist(self):
        manager = UOMManager()
        manager.ensure_base_uoms_exist()
        # A representative sample of base UOMs should exist
        for uom in ["Hour", "Day", "Kg", "Litre", "Meter", "Subscription"]:
            self.assertTrue(frappe.db.exists("UOM", uom), f"UOM {uom} missing")

    def test_setup_conversions_creates_no_conversion_factors(self):
        # Regression: setup_conversions() used to define an inverted, redundant
        # conversion table (e.g. "1 Gram = 1000 Kg" -- backwards vs ERPNext's
        # "1 Kg = 1000 Gram") whose inserts silently failed on the missing
        # mandatory `category`. It is now an intentional no-op and must not
        # fabricate any UOM Conversion Factor rows.
        before = frappe.db.count("UOM Conversion Factor")
        UOMManager().setup_conversions()
        self.assertEqual(frappe.db.count("UOM Conversion Factor"), before)
        # The specific inverted Gram->Kg row must never exist (ERPNext ships Kg->Gram).
        self.assertIsNone(
            frappe.db.exists("UOM Conversion Factor", {"from_uom": "Gram", "to_uom": "Kg"})
        )

    def test_setup_dutch_uoms_seeds_base_uoms_without_conversions(self):
        # setup_dutch_uoms must actually seed base UOMs (not just return a
        # hardcoded "success"), while fabricating no inverted conversion factors.
        before = frappe.db.count("UOM Conversion Factor")
        result = setup_dutch_uoms()
        self.assertEqual(result["status"], "success")
        for uom in ["Hour", "Kg", "Litre"]:
            self.assertTrue(frappe.db.exists("UOM", uom), f"UOM {uom} missing")
        self.assertEqual(frappe.db.count("UOM Conversion Factor"), before)


if __name__ == "__main__":
    unittest.main()
