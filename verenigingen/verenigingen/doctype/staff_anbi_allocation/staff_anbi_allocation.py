# Copyright (c) 2025, NVV and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class StaffANBIAllocation(Document):
    def validate(self):
        self.validate_percentages()
        self.calculate_amounts()

    def validate_percentages(self):
        """Ensure percentages sum to 100%."""
        total = (self.pct_doelstelling or 0) + (self.pct_werving or 0) + (self.pct_beheer or 0)

        # Allow for small floating point differences
        if abs(total - 100) > 0.01:
            frappe.throw(
                _("Allocation percentages must sum to 100%. Current total: {0}%").format(round(total, 2))
            )

    def calculate_amounts(self):
        """Calculate euro amounts for each ANBI category."""
        cost = self.annual_employer_cost or 0

        self.amount_doelstelling = cost * (self.pct_doelstelling or 0) / 100
        self.amount_werving = cost * (self.pct_werving or 0) / 100
        self.amount_beheer = cost * (self.pct_beheer or 0) / 100


def get_anbi_personnel_totals(fiscal_year):
    """Get total personnel costs per ANBI category for a fiscal year.

    Args:
        fiscal_year: Fiscal Year name (e.g., "2024")

    Returns:
        dict with totals per category and grand total
    """
    allocations = frappe.get_all(
        "Staff ANBI Allocation",
        filters={"fiscal_year": fiscal_year},
        fields=[
            "employee_name",
            "annual_employer_cost",
            "amount_doelstelling",
            "amount_werving",
            "amount_beheer",
        ],
    )

    totals = {
        "doelstelling": 0,
        "werving": 0,
        "beheer": 0,
        "total_personnel": 0,
        "employee_count": len(allocations),
        "details": allocations,
    }

    for alloc in allocations:
        totals["doelstelling"] += alloc.amount_doelstelling or 0
        totals["werving"] += alloc.amount_werving or 0
        totals["beheer"] += alloc.amount_beheer or 0
        totals["total_personnel"] += alloc.annual_employer_cost or 0

    return totals
