# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/coverage_overlap_detector.py

Uses REAL Sales Invoices (via the enhanced factory) with custom coverage dates,
then asserts the standard date-range overlap predicate
    proposed_start <= existing_end AND proposed_end >= existing_start
and the structured results / gap detection.

Each test scopes ALL assertions to its own freshly created customer so pre-existing
site invoices never leak into results.
"""

import frappe
from frappe.utils import getdate

from verenigingen.services.billing.coverage_overlap_detector import (
    check_coverage_overlap,
    find_exact_coverage_invoice,
    find_overlapping_invoices,
    get_member_coverage_gaps,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCoverageOverlapDetector(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        for doctype, name in self._committed:
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # --- fixture helpers (factory usage allowed) ---
    def _customer(self):
        member = self.create_test_member()
        member.create_customer()
        member.reload()
        self._committed.append(("Member", member.name))
        self._committed.append(("Customer", member.customer))
        return member.customer

    def _invoice(self, customer, cov_start, cov_end, *, submit=True, outstanding=None):
        # A draft must be requested at creation time: create_test_sales_invoice submits
        # unless status="Draft" is passed, so by the time this helper inspects the doc
        # its docstatus is already 1 and withholding submit() here does nothing.
        inv = self.create_test_sales_invoice(customer=customer, **({} if submit else {"status": "Draft"}))
        self._committed.append(("Sales Invoice", inv.name))
        frappe.db.set_value(
            "Sales Invoice",
            inv.name,
            {
                "custom_coverage_start_date": getdate(cov_start),
                "custom_coverage_end_date": getdate(cov_end),
            },
        )
        if outstanding is not None:
            frappe.db.set_value("Sales Invoice", inv.name, "outstanding_amount", outstanding)
        frappe.db.commit()
        return inv.name

    # ============ find_overlapping_invoices ============
    def test_no_invoices_returns_empty(self):
        customer = self._customer()
        result = find_overlapping_invoices(customer, "2025-01-01", "2025-01-31")
        self.assertEqual(result, [])

    def test_exact_match_overlaps(self):
        customer = self._customer()
        inv = self._invoice(customer, "2025-01-01", "2025-01-31")
        result = find_overlapping_invoices(customer, "2025-01-01", "2025-01-31")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], inv)

    def test_partial_overlap_at_start(self):
        customer = self._customer()
        inv = self._invoice(customer, "2025-01-15", "2025-02-15")
        # proposed Jan 1..Jan 20 overlaps Jan 15..Feb 15
        result = find_overlapping_invoices(customer, "2025-01-01", "2025-01-20")
        self.assertEqual([r["name"] for r in result], [inv])

    def test_adjacent_period_no_overlap(self):
        customer = self._customer()
        # existing Jan; proposed Feb 1..Feb 28 -> Feb1 > Jan31 -> NO overlap
        self._invoice(customer, "2025-01-01", "2025-01-31")
        result = find_overlapping_invoices(customer, "2025-02-01", "2025-02-28")
        self.assertEqual(result, [])

    def test_touching_boundary_counts_as_overlap(self):
        customer = self._customer()
        # existing ends 2025-01-31; proposed starts 2025-01-31 -> start <= end AND end >= start -> overlap
        inv = self._invoice(customer, "2025-01-01", "2025-01-31")
        result = find_overlapping_invoices(customer, "2025-01-31", "2025-02-28")
        self.assertEqual([r["name"] for r in result], [inv])

    def test_containment_overlap(self):
        customer = self._customer()
        # existing fully contains proposed
        inv = self._invoice(customer, "2025-01-01", "2025-12-31")
        result = find_overlapping_invoices(customer, "2025-06-01", "2025-06-30")
        self.assertEqual([r["name"] for r in result], [inv])

    def test_only_with_outstanding_filter(self):
        customer = self._customer()
        # one paid (outstanding 0), one unpaid
        self._invoice(customer, "2025-01-01", "2025-01-31", outstanding=0)
        unpaid = self._invoice(customer, "2025-01-10", "2025-02-10", outstanding=50)
        result = find_overlapping_invoices(customer, "2025-01-01", "2025-02-28", only_with_outstanding=True)
        self.assertEqual([r["name"] for r in result], [unpaid])

    # ============ check_coverage_overlap ============
    def test_check_no_overlap_can_create(self):
        customer = self._customer()
        result = check_coverage_overlap(customer, "2025-03-01", "2025-03-31")
        self.assertFalse(result.has_overlap)
        self.assertTrue(result.can_create_invoice)
        self.assertIsNone(result.exact_match)
        self.assertEqual(result.reason, "No overlapping invoices found")
        # to_dict round trips the fields
        d = result.to_dict()
        self.assertFalse(d["has_overlap"])
        self.assertTrue(d["can_create_invoice"])

    def test_check_exact_match_sets_exact_and_reason(self):
        customer = self._customer()
        inv = self._invoice(customer, "2025-04-01", "2025-04-30")
        result = check_coverage_overlap(customer, "2025-04-01", "2025-04-30")
        self.assertTrue(result.has_overlap)
        self.assertFalse(result.can_create_invoice)
        self.assertEqual(result.exact_match, inv)
        self.assertIn("Exact duplicate", result.reason)
        self.assertIn(inv, result.reason)

    def test_exact_match_prefers_the_payable_invoice_over_a_draft(self):
        """A draft and a submitted UNPAID invoice share a period -> the payable one wins.

        Callers use exact_match to decide what a payment can be allocated to, and only a
        submitted invoice with outstanding can be. Picking the draft here costs a real
        allocation: the callers stop for manual review and the money lands unallocated
        while a payable invoice was sitting right there.

        Built in BOTH creation orders on purpose. find_overlapping_invoices orders by
        coverage start date alone, which is tied here, so a single ordering would let a
        first-match-wins rule pass by accident on whichever row the engine happened to
        return first. An earlier revision of this test asserted that raw order as a
        "premise"; that pinned a MariaDB index artefact rather than the behaviour.
        """
        for draft_first in (True, False):
            with self.subTest(draft_first=draft_first):
                customer = self._customer()
                if draft_first:
                    draft = self._invoice(customer, "2025-07-01", "2025-07-31", submit=False)
                    payable = self._invoice(customer, "2025-07-01", "2025-07-31", outstanding=50)
                else:
                    payable = self._invoice(customer, "2025-07-01", "2025-07-31", outstanding=50)
                    draft = self._invoice(customer, "2025-07-01", "2025-07-31", submit=False)

                result = check_coverage_overlap(customer, "2025-07-01", "2025-07-31")
                self.assertEqual(result.exact_match, payable)
                self.assertNotEqual(result.exact_match, draft)

    def test_exact_match_prefers_a_draft_over_an_already_paid_invoice(self):
        """A draft and a submitted PAID invoice share a period -> the DRAFT must win.

        This is the case a naive "prefer submitted" rule gets catastrophically wrong.
        Handing back the paid invoice makes every caller skip its docstatus guard
        (docstatus == 1) and then read outstanding_amount == 0 as "already paid, create a
        new invoice for this payment" - producing a THIRD invoice for a period the draft
        already covers. Returning the draft keeps the stop-for-review branch reachable,
        which is the whole point of the draft guards.
        """
        for draft_first in (True, False):
            with self.subTest(draft_first=draft_first):
                customer = self._customer()
                if draft_first:
                    draft = self._invoice(customer, "2025-09-01", "2025-09-30", submit=False)
                    self._invoice(customer, "2025-09-01", "2025-09-30", outstanding=0)
                else:
                    self._invoice(customer, "2025-09-01", "2025-09-30", outstanding=0)
                    draft = self._invoice(customer, "2025-09-01", "2025-09-30", submit=False)

                result = check_coverage_overlap(customer, "2025-09-01", "2025-09-30")
                self.assertEqual(
                    result.exact_match,
                    draft,
                    "a paid invoice must not shadow the draft - it routes callers into "
                    "the create-another-invoice branch",
                )

    def test_check_partial_overlap_no_exact_match(self):
        customer = self._customer()
        inv = self._invoice(customer, "2025-05-15", "2025-06-15")
        result = check_coverage_overlap(customer, "2025-05-01", "2025-05-20")
        self.assertTrue(result.has_overlap)
        self.assertIsNone(result.exact_match)
        self.assertIn("Coverage overlap", result.reason)
        self.assertIn(inv, result.reason)

    # ============ find_exact_coverage_invoice ============
    def test_find_exact_returns_name(self):
        customer = self._customer()
        inv = self._invoice(customer, "2025-07-01", "2025-07-31")
        found = find_exact_coverage_invoice(customer, "2025-07-01", "2025-07-31")
        self.assertEqual(found, inv)

    def test_find_exact_none_when_dates_differ(self):
        customer = self._customer()
        self._invoice(customer, "2025-07-01", "2025-07-31")
        found = find_exact_coverage_invoice(customer, "2025-07-01", "2025-08-31")
        self.assertIsNone(found)

    def test_find_exact_with_outstanding_filter(self):
        customer = self._customer()
        self._invoice(customer, "2025-08-01", "2025-08-31", outstanding=0)
        found = find_exact_coverage_invoice(customer, "2025-08-01", "2025-08-31", only_with_outstanding=True)
        self.assertIsNone(found)  # paid invoice excluded

    # ============ get_member_coverage_gaps ============
    def test_gap_when_no_invoices_is_whole_period(self):
        customer = self._customer()
        gaps = get_member_coverage_gaps(customer, "2025-01-01", "2025-12-31")
        self.assertEqual(gaps, [{"start": getdate("2025-01-01"), "end": getdate("2025-12-31")}])

    def test_gap_before_and_after_single_invoice(self):
        customer = self._customer()
        # coverage only Mar..May; analysis window Jan..Dec
        self._invoice(customer, "2025-03-01", "2025-05-31")
        gaps = get_member_coverage_gaps(customer, "2025-01-01", "2025-12-31")
        # gap before (Jan1..Mar1) and gap after (Jun1..Dec31)
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0], {"start": getdate("2025-01-01"), "end": getdate("2025-03-01")})
        self.assertEqual(gaps[1]["start"], getdate("2025-06-01"))  # day after coverage end
        self.assertEqual(gaps[1]["end"], getdate("2025-12-31"))

    def test_no_gap_when_fully_covered(self):
        customer = self._customer()
        self._invoice(customer, "2025-01-01", "2025-12-31")
        gaps = get_member_coverage_gaps(customer, "2025-02-01", "2025-11-30")
        self.assertEqual(gaps, [])

    def test_gap_between_two_invoices(self):
        customer = self._customer()
        self._invoice(customer, "2025-01-01", "2025-03-31")
        self._invoice(customer, "2025-06-01", "2025-08-31")
        gaps = get_member_coverage_gaps(customer, "2025-01-01", "2025-08-31")
        # single gap Apr1..Jun1 between the two coverage periods
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0], {"start": getdate("2025-04-01"), "end": getdate("2025-06-01")})
