"""
Real-integration tests for SEPAMandateService.

Creates REAL Member + SEPA Mandate records via the test factory and exercises
the batch lookup, in-process caching, batch validation, and cache invalidation
paths against the real database. No business-logic mocking.

Complements the SEPA sequence-type tests in tests/sepa/ which focus on
sequence determination rather than the lookup/validation/caching surface here.
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import (
    SEPAMandateService,
    get_sepa_mandate_service,
    invalidate_mandate_cache_for_member,
    invalidate_mandate_sequence_cache,
)


class TestSEPAMandateService(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.service = SEPAMandateService()
        self.mandate = self.create_test_sepa_mandate(scenario="normal")
        self.member_name = self.mandate.member

    # ------------------------------------------------------------------
    # get_active_mandate_batch / get_active_mandate
    # ------------------------------------------------------------------
    def test_empty_input_returns_empty(self):
        self.assertEqual(self.service.get_active_mandate_batch([]), {})

    def test_batch_returns_active_mandate(self):
        result = self.service.get_active_mandate_batch([self.member_name])
        self.assertIn(self.member_name, result)
        mandate = result[self.member_name]
        self.assertIsNotNone(mandate)
        self.assertEqual(mandate["member"], self.member_name)
        self.assertEqual(mandate["status"], "Active")
        self.assertEqual(mandate["name"], self.mandate.name)

    def test_single_lookup_delegates_to_batch(self):
        mandate = self.service.get_active_mandate(self.member_name)
        self.assertIsNotNone(mandate)
        self.assertEqual(mandate["name"], self.mandate.name)

    def test_member_without_mandate_returns_none_and_caches(self):
        other = self.create_test_member(
            first_name="No",
            last_name="Mandate",
            email=f"nomandate.{frappe.generate_hash(length=6)}@example.com",
        )
        result = self.service.get_active_mandate_batch([other.name])
        self.assertIsNone(result[other.name])
        # Cached even though None
        self.assertIn(other.name, self.service._mandate_cache)
        self.assertIsNone(self.service._mandate_cache[other.name])

    def test_batch_uses_cache_on_second_call(self):
        # Prime cache
        self.service.get_active_mandate_batch([self.member_name])
        self.assertIn(self.member_name, self.service._mandate_cache)
        # Poison the DB-bypassing cache to a sentinel and confirm cache is used
        sentinel = {"name": "CACHED-SENTINEL", "member": self.member_name, "status": "Active"}
        self.service._mandate_cache[self.member_name] = sentinel
        result = self.service.get_active_mandate_batch([self.member_name])
        self.assertEqual(result[self.member_name]["name"], "CACHED-SENTINEL")

    def test_batch_mixed_cached_and_uncached(self):
        member2 = self.create_test_sepa_mandate(scenario="normal").member
        # Prime only first member
        self.service.get_active_mandate_batch([self.member_name])
        result = self.service.get_active_mandate_batch([self.member_name, member2])
        self.assertEqual(result[self.member_name]["member"], self.member_name)
        self.assertEqual(result[member2]["member"], member2)

    def test_suspended_mandate_not_returned_as_active(self):
        suspended = self.create_test_sepa_mandate(scenario="suspended")
        result = self.service.get_active_mandate_batch([suspended.member])
        self.assertIsNone(result[suspended.member])

    # ------------------------------------------------------------------
    # validate_mandate_status_batch
    # ------------------------------------------------------------------
    def test_validate_status_empty(self):
        self.assertEqual(self.service.validate_mandate_status_batch([]), {})

    @unittest.expectedFailure
    def test_validate_mandate_status_batch_PRODUCTION_BUG(self):
        """
        PRODUCTION BUG (characterized):
        SEPAMandateService.validate_mandate_status_batch() SELECTs columns
        `valid_from`, `valid_until`, `date_signed` from `tabSEPA Mandate`, but
        those columns do NOT exist on the SEPA Mandate doctype (verified against
        the schema: only `sign_date` and `expiry_date` exist). Any non-empty
        call therefore raises a 1054 "Unknown column" OperationalError.

        See: verenigingen_payments/utils/sepa_mandate_service.py:224-241

        This test asserts the *intended* behaviour (a valid Active mandate passes
        validation). It is marked expectedFailure because the query crashes.
        FIX (money-relevant, left for maintainer review): map valid_until ->
        expiry_date and drop the non-existent valid_from/date_signed checks, OR
        add the columns. Not auto-fixed because it changes validity semantics.
        """
        results = self.service.validate_mandate_status_batch([self.mandate.name])
        self.assertIn(self.mandate.name, results)
        self.assertTrue(results[self.mandate.name]["valid"])

    def test_validate_mandate_status_batch_raises_on_missing_columns(self):
        """Companion to the expectedFailure: pins the CURRENT crash behaviour so
        a future fix flips this test (it will stop raising).

        Narrowed to the DB OperationalError (1054 Unknown column) rather than a
        bare Exception so this can't pass on an unrelated failure. Built as a
        tuple across whichever MySQL driver is installed (this site uses MySQLdb).
        """
        db_errors = []
        for mod, attr in (("MySQLdb", "OperationalError"), ("pymysql.err", "OperationalError")):
            try:
                db_errors.append(getattr(__import__(mod, fromlist=[attr]), attr))
            except ImportError:
                pass

        with self.assertRaises(tuple(db_errors)):
            self.service.validate_mandate_status_batch([self.mandate.name])

    # ------------------------------------------------------------------
    # get_sepa_invoices_with_mandates (real query, returns list)
    # ------------------------------------------------------------------
    def test_get_sepa_invoices_with_mandates_returns_list(self):
        # No SEPA-eligible invoices for our throwaway member, but the optimized
        # query must execute without error and return a list.
        result = self.service.get_sepa_invoices_with_mandates(frappe.utils.today())
        self.assertIsInstance(result, list)

    def test_get_sepa_invoices_custom_lookback(self):
        result = self.service.get_sepa_invoices_with_mandates(frappe.utils.today(), lookback_days=120)
        self.assertIsInstance(result, list)

    # ------------------------------------------------------------------
    # Cache invalidation + stats
    # ------------------------------------------------------------------
    def test_invalidate_member_cache_clears_entry(self):
        self.service.get_active_mandate_batch([self.member_name])
        self.assertIn(self.member_name, self.service._mandate_cache)
        self.service.invalidate_member_cache(self.member_name)
        self.assertNotIn(self.member_name, self.service._mandate_cache)

    def test_invalidate_member_cache_empty_noop(self):
        # Should not raise
        self.service.invalidate_member_cache("")
        self.service.invalidate_member_cache(None)

    def test_invalidate_mandate_cache_clears_sequence_entries(self):
        self.service._sequence_cache[f"{self.mandate.name}:INV-001"] = "RCUR"
        self.service._sequence_cache["OTHER:INV-002"] = "FRST"
        self.service.invalidate_mandate_cache(self.mandate.name)
        self.assertNotIn(f"{self.mandate.name}:INV-001", self.service._sequence_cache)
        self.assertIn("OTHER:INV-002", self.service._sequence_cache)

    def test_clear_cache_empties_all(self):
        self.service._mandate_cache["x"] = {"name": "y"}
        self.service._sequence_cache["a:b"] = "RCUR"
        self.service.clear_cache()
        self.assertEqual(len(self.service._mandate_cache), 0)
        self.assertEqual(len(self.service._sequence_cache), 0)

    def test_get_cache_stats(self):
        self.service._mandate_cache["m1"] = None
        self.service._mandate_cache["m2"] = {"name": "x"}
        self.service._sequence_cache["a:b"] = "RCUR"
        stats = self.service.get_cache_stats()
        self.assertEqual(stats["mandate_cache_size"], 2)
        self.assertEqual(stats["sequence_cache_size"], 1)
        self.assertEqual(stats["total_cached_items"], 3)

    # ------------------------------------------------------------------
    # Module-level helpers + global singleton
    # ------------------------------------------------------------------
    def test_global_service_singleton(self):
        a = get_sepa_mandate_service()
        b = get_sepa_mandate_service()
        self.assertIs(a, b)

    def test_invalidate_helpers_do_not_raise(self):
        # These wrap the global service and must swallow any failure.
        invalidate_mandate_cache_for_member(self.member_name)
        invalidate_mandate_sequence_cache(self.mandate.name)
