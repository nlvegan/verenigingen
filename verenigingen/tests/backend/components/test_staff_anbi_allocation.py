"""
Unit tests for Staff ANBI Allocation DocType

Tests the personnel cost allocation across ANBI reporting categories:
- 61: Besteed aan doelstellingen (Program costs)
- 62: Kosten werving baten (Fundraising costs)
- 63: Beheer en administratie (Administration costs)

Per Dutch ANBI regulations, personnel costs must be allocated across these
categories and must sum to 100%.
"""

import uuid

import frappe
from frappe import ValidationError
from frappe.tests.utils import FrappeTestCase
from verenigingen.verenigingen.doctype.staff_anbi_allocation.staff_anbi_allocation import (
    StaffANBIAllocation,
    get_anbi_personnel_totals,
)


class TestStaffANBIAllocation(FrappeTestCase):
    """Test Staff ANBI Allocation DocType functionality"""

    # Track created docs for cleanup
    created_docs = []

    def setUp(self):
        """Set up test fixtures"""
        frappe.set_user("Administrator")
        # Use a unique test fiscal year to avoid conflicts
        self.test_fiscal_year = self._ensure_fiscal_year("2099")
        self.test_id = str(uuid.uuid4())[:8]

    def tearDown(self):
        """Clean up test data"""
        # Delete all test allocations for our test fiscal year
        for name in frappe.get_all(
            "Staff ANBI Allocation",
            filters={"fiscal_year": "2099"},
            pluck="name"
        ):
            frappe.delete_doc("Staff ANBI Allocation", name, force=True)
        frappe.db.commit()

    def _ensure_fiscal_year(self, year):
        """Ensure a fiscal year exists for testing"""
        fy_name = year
        if not frappe.db.exists("Fiscal Year", fy_name):
            fy = frappe.get_doc({
                "doctype": "Fiscal Year",
                "year": fy_name,
                "year_start_date": f"{year}-01-01",
                "year_end_date": f"{year}-12-31",
            })
            fy.insert(ignore_permissions=True)
            frappe.db.commit()
        return fy_name

    def _create_allocation(self, **kwargs):
        """Helper to create Staff ANBI Allocation for testing"""
        # Generate unique employee name if not provided
        if "employee_name" not in kwargs:
            kwargs["employee_name"] = f"Test Employee {self.test_id}"

        defaults = {
            "fiscal_year": self.test_fiscal_year,
            "annual_employer_cost": 50000,
            "fte": 1.0,
            "pct_doelstelling": 70,
            "pct_werving": 20,
            "pct_beheer": 10,
        }
        defaults.update(kwargs)

        doc = frappe.get_doc({
            "doctype": "Staff ANBI Allocation",
            **defaults
        })
        return doc

    # ==========================================================================
    # Percentage Validation Tests
    # ==========================================================================

    def test_percentages_must_sum_to_100(self):
        """Test that allocation percentages must sum to exactly 100%"""
        doc = self._create_allocation(
            pct_doelstelling=70,
            pct_werving=20,
            pct_beheer=10  # Total = 100%
        )
        # Should not raise
        doc.insert()
        self.assertEqual(
            doc.pct_doelstelling + doc.pct_werving + doc.pct_beheer,
            100
        )

    def test_percentages_under_100_rejected(self):
        """Test that percentages totaling less than 100% are rejected"""
        doc = self._create_allocation(
            pct_doelstelling=60,
            pct_werving=20,
            pct_beheer=10  # Total = 90%
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.insert()

        self.assertIn("100%", str(ctx.exception))
        self.assertIn("90", str(ctx.exception))

    def test_percentages_over_100_rejected(self):
        """Test that percentages totaling more than 100% are rejected"""
        doc = self._create_allocation(
            pct_doelstelling=80,
            pct_werving=20,
            pct_beheer=10  # Total = 110%
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.insert()

        self.assertIn("100%", str(ctx.exception))
        self.assertIn("110", str(ctx.exception))

    def test_floating_point_tolerance(self):
        """Test that small floating point differences are tolerated"""
        doc = self._create_allocation(
            pct_doelstelling=33.33,
            pct_werving=33.33,
            pct_beheer=33.34  # Total = 100.00 (with fp precision)
        )
        # Should not raise - within 0.01 tolerance
        doc.insert()
        self.assertIsNotNone(doc.name)

    def test_zero_percentage_allowed(self):
        """Test that zero percentages are allowed (as long as total is 100%)"""
        doc = self._create_allocation(
            pct_doelstelling=100,
            pct_werving=0,
            pct_beheer=0  # Total = 100%, all to mission
        )
        doc.insert()
        self.assertEqual(doc.pct_werving, 0)
        self.assertEqual(doc.pct_beheer, 0)

    # ==========================================================================
    # Amount Calculation Tests
    # ==========================================================================

    def test_amounts_calculated_correctly(self):
        """Test that euro amounts are calculated from percentages"""
        doc = self._create_allocation(
            annual_employer_cost=50000,
            pct_doelstelling=70,
            pct_werving=20,
            pct_beheer=10
        )
        doc.insert()

        self.assertEqual(doc.amount_doelstelling, 35000)  # 50000 * 0.70
        self.assertEqual(doc.amount_werving, 10000)       # 50000 * 0.20
        self.assertEqual(doc.amount_beheer, 5000)         # 50000 * 0.10

    def test_amounts_sum_equals_total_cost(self):
        """Test that calculated amounts sum to annual employer cost"""
        doc = self._create_allocation(
            annual_employer_cost=75000,
            pct_doelstelling=60,
            pct_werving=25,
            pct_beheer=15
        )
        doc.insert()

        total_amounts = (
            doc.amount_doelstelling +
            doc.amount_werving +
            doc.amount_beheer
        )
        self.assertEqual(total_amounts, 75000)

    def test_zero_cost_produces_zero_amounts(self):
        """Test that zero employer cost produces zero amounts"""
        doc = self._create_allocation(
            annual_employer_cost=0,
            pct_doelstelling=70,
            pct_werving=20,
            pct_beheer=10
        )
        doc.insert()

        self.assertEqual(doc.amount_doelstelling, 0)
        self.assertEqual(doc.amount_werving, 0)
        self.assertEqual(doc.amount_beheer, 0)

    def test_fractional_amounts_handled(self):
        """Test that fractional amounts are calculated correctly"""
        doc = self._create_allocation(
            annual_employer_cost=33333,  # Odd number
            pct_doelstelling=33.33,
            pct_werving=33.33,
            pct_beheer=33.34
        )
        doc.insert()

        # Amounts should be calculated (may have small rounding differences)
        self.assertAlmostEqual(doc.amount_doelstelling, 11109.89, places=0)
        self.assertAlmostEqual(doc.amount_werving, 11109.89, places=0)
        self.assertAlmostEqual(doc.amount_beheer, 11113.22, places=0)

    # ==========================================================================
    # FTE Field Tests
    # ==========================================================================

    def test_fte_default_is_one(self):
        """Test that FTE defaults to 1.0"""
        doc = self._create_allocation()
        # Don't set FTE explicitly
        del doc.fte

        doc.insert()
        # Should default to 1.0 per DocType definition
        self.assertEqual(doc.fte, 1.0)

    def test_part_time_fte_allowed(self):
        """Test that part-time FTE values are allowed"""
        doc = self._create_allocation(fte=0.5)
        doc.insert()
        self.assertEqual(doc.fte, 0.5)

    # ==========================================================================
    # Utility Function Tests
    # ==========================================================================

    def test_get_anbi_personnel_totals_empty(self):
        """Test get_anbi_personnel_totals with no allocations"""
        # Use a fiscal year with no allocations
        result = get_anbi_personnel_totals("9999")

        self.assertEqual(result["doelstelling"], 0)
        self.assertEqual(result["werving"], 0)
        self.assertEqual(result["beheer"], 0)
        self.assertEqual(result["total_personnel"], 0)
        self.assertEqual(result["employee_count"], 0)

    def test_get_anbi_personnel_totals_single_allocation(self):
        """Test get_anbi_personnel_totals with one allocation"""
        doc = self._create_allocation(
            employee_name="Single Employee",
            annual_employer_cost=60000,
            pct_doelstelling=80,
            pct_werving=15,
            pct_beheer=5
        )
        doc.insert()

        result = get_anbi_personnel_totals(self.test_fiscal_year)

        self.assertEqual(result["doelstelling"], 48000)  # 60000 * 0.80
        self.assertEqual(result["werving"], 9000)        # 60000 * 0.15
        self.assertEqual(result["beheer"], 3000)         # 60000 * 0.05
        self.assertEqual(result["total_personnel"], 60000)
        self.assertEqual(result["employee_count"], 1)

    def test_get_anbi_personnel_totals_multiple_allocations(self):
        """Test get_anbi_personnel_totals aggregates multiple employees"""
        # Employee 1: €50,000 - 70/20/10 split
        doc1 = self._create_allocation(
            employee_name="Employee One",
            annual_employer_cost=50000,
            pct_doelstelling=70,
            pct_werving=20,
            pct_beheer=10
        )
        doc1.insert()

        # Employee 2: €40,000 - 60/30/10 split
        doc2 = self._create_allocation(
            employee_name="Employee Two",
            annual_employer_cost=40000,
            pct_doelstelling=60,
            pct_werving=30,
            pct_beheer=10
        )
        doc2.insert()

        result = get_anbi_personnel_totals(self.test_fiscal_year)

        # Expected totals:
        # Doelstelling: 35000 + 24000 = 59000
        # Werving: 10000 + 12000 = 22000
        # Beheer: 5000 + 4000 = 9000
        # Total: 90000
        self.assertEqual(result["doelstelling"], 59000)
        self.assertEqual(result["werving"], 22000)
        self.assertEqual(result["beheer"], 9000)
        self.assertEqual(result["total_personnel"], 90000)
        self.assertEqual(result["employee_count"], 2)

    def test_get_anbi_personnel_totals_returns_details(self):
        """Test that get_anbi_personnel_totals returns allocation details"""
        doc = self._create_allocation(
            employee_name="Detail Test Employee",
            annual_employer_cost=55000
        )
        doc.insert()

        result = get_anbi_personnel_totals(self.test_fiscal_year)

        self.assertIn("details", result)
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["employee_name"], "Detail Test Employee")

    # ==========================================================================
    # Document Naming Tests
    # ==========================================================================

    def test_autoname_format(self):
        """Test that document name follows employee-year format"""
        doc = self._create_allocation(
            employee_name="John Doe",
            fiscal_year=self.test_fiscal_year
        )
        doc.insert()

        self.assertEqual(doc.name, f"John Doe-{self.test_fiscal_year}")

    def test_unique_constraint_per_employee_year(self):
        """Test that same employee cannot have duplicate allocations for same year"""
        doc1 = self._create_allocation(
            employee_name="Unique Test",
            fiscal_year=self.test_fiscal_year
        )
        doc1.insert()

        doc2 = self._create_allocation(
            employee_name="Unique Test",
            fiscal_year=self.test_fiscal_year
        )

        # Should raise duplicate name error
        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert()


class TestStaffANBIAllocationEdgeCases(FrappeTestCase):
    """Edge case tests for Staff ANBI Allocation"""

    def setUp(self):
        frappe.set_user("Administrator")
        self.test_fiscal_year = "2098"  # Different year from main tests
        self.test_id = str(uuid.uuid4())[:8]
        if not frappe.db.exists("Fiscal Year", self.test_fiscal_year):
            fy = frappe.get_doc({
                "doctype": "Fiscal Year",
                "year": self.test_fiscal_year,
                "year_start_date": "2098-01-01",
                "year_end_date": "2098-12-31",
            })
            fy.insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        """Clean up test data"""
        for name in frappe.get_all(
            "Staff ANBI Allocation",
            filters={"fiscal_year": "2098"},
            pluck="name"
        ):
            frappe.delete_doc("Staff ANBI Allocation", name, force=True)
        frappe.db.commit()

    def test_null_percentage_treated_as_zero(self):
        """Test that null/None percentages are treated as 0"""
        doc = frappe.get_doc({
            "doctype": "Staff ANBI Allocation",
            "employee_name": f"Null Test {self.test_id}",
            "fiscal_year": self.test_fiscal_year,
            "annual_employer_cost": 50000,
            "pct_doelstelling": 100,
            "pct_werving": None,  # Explicitly null
            "pct_beheer": None,   # Explicitly null
        })
        # Should treat None as 0, total = 100%
        doc.insert()
        self.assertEqual(doc.amount_werving, 0)
        self.assertEqual(doc.amount_beheer, 0)

    def test_large_employer_cost(self):
        """Test handling of large employer costs"""
        doc = frappe.get_doc({
            "doctype": "Staff ANBI Allocation",
            "employee_name": f"Executive {self.test_id}",
            "fiscal_year": self.test_fiscal_year,
            "annual_employer_cost": 250000,  # €250k
            "pct_doelstelling": 50,
            "pct_werving": 30,
            "pct_beheer": 20,
        })
        doc.insert()

        self.assertEqual(doc.amount_doelstelling, 125000)
        self.assertEqual(doc.amount_werving, 75000)
        self.assertEqual(doc.amount_beheer, 50000)

    def test_special_characters_in_employee_name(self):
        """Test employee names with special characters"""
        special_name = f"José García-López {self.test_id}"
        doc = frappe.get_doc({
            "doctype": "Staff ANBI Allocation",
            "employee_name": special_name,
            "fiscal_year": self.test_fiscal_year,
            "annual_employer_cost": 45000,
            "pct_doelstelling": 70,
            "pct_werving": 20,
            "pct_beheer": 10,
        })
        doc.insert()
        self.assertIn("José García-López", doc.name)


if __name__ == "__main__":
    import unittest
    unittest.main()
