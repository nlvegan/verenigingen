# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Shared helpers for tests that need a throwaway, per-test Company with a
controlled (often zero) Cost Center count.

``_create_isolated_company`` / ``_delete_all_cost_centers`` were independently
written three times (``test_cost_center_fix.py``'s
``_IsolatedCompanyTestBase``, and two #1441 test classes covering the
chapter/e-Boekhouden Cost Center creators) before
``scripts/validation/duplicate_helper_validator.py`` flagged the growth.
Import these instead of writing another copy.
"""

import hashlib

import frappe


def create_isolated_test_company(test_case, name_prefix: str, abbr_prefix: str) -> str:
    """Insert a throwaway EUR/Netherlands Company scoped to one test method.

    Named deterministically from the test class + method name (never a shared
    counter), so two test METHODS -- in the same class or different classes --
    can never generate the same company/abbr pair, regardless of execution
    order.
    """
    tag = hashlib.md5(f"{type(test_case).__name__}.{test_case._testMethodName}".encode()).hexdigest()[:6]
    name = f"{name_prefix} {tag}"
    doc = frappe.new_doc("Company")
    doc.company_name = name
    doc.abbr = f"{abbr_prefix}{tag}"
    doc.default_currency = "EUR"
    doc.country = "Netherlands"
    doc.insert(ignore_permissions=True)
    return name


def delete_all_cost_centers(company: str) -> None:
    """Delete every Cost Center belonging to `company`.

    Leaves before groups: a group with a live child cannot be deleted first.
    For throwaway, per-test companies only -- never call this on a company
    other tests in the shard might still depend on.
    """
    for cc in frappe.get_all(
        "Cost Center", filters={"company": company}, fields=["name"], order_by="is_group asc"
    ):
        frappe.delete_doc("Cost Center", cc.name, force=True, ignore_permissions=True)


def create_group_cost_center(company: str, cost_center_name: str, parent: str) -> str:
    """Insert a real, non-root group Cost Center under `parent` for `company`
    -- a fixture row for tests asserting an existing group Cost Center must
    be preferred over any zero-Cost-Center fallback."""
    doc = frappe.new_doc("Cost Center")
    doc.cost_center_name = cost_center_name
    doc.company = company
    doc.is_group = 1
    doc.parent_cost_center = parent
    doc.insert(ignore_permissions=True)
    return doc.name
