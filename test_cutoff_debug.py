#!/usr/bin/env python3
"""Debug script to test calculate_cutoff_date_for_period"""

import sys

sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

from datetime import date

import frappe
from frappe.utils import getdate, today

# Initialize Frappe
frappe.init(site="dev.veganisme.net")
frappe.connect()

# Import after init
from verenigingen.services.billing.coverage_calculator import CoverageCalculator

print("=" * 60)
print("Testing calculate_cutoff_date_for_period()")
print("=" * 60)

# Get settings
settings = frappe.get_single("Verenigingen Settings")
print(f"\nSettings:")
print(f"  billing_cutoff_frequency: {getattr(settings, 'billing_cutoff_frequency', 'NOT SET')}")
print(f"  book_year_start_month: {getattr(settings, 'book_year_start_month', 'NOT SET')}")
print(f"  book_year_end_month: {getattr(settings, 'book_year_end_month', 'NOT SET')}")
print(f"  book_year_end_day: {getattr(settings, 'book_year_end_day', 'NOT SET')}")

# Get today's date
today_date = getdate(today())
print(f"\nToday's date: {today_date}")
print(f"  Type: {type(today_date)}")

# Call the method
try:
    result = CoverageCalculator.calculate_cutoff_date_for_period()
    print(f"\nResult: {result}")
    print(f"  Type: {type(result)}")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback

    traceback.print_exc()

frappe.destroy()
