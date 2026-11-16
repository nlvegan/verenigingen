"""
#2628: ``SEPAMandateService.get_sequence_types_batch`` cached a guessed sequence
type when determining the real one failed. The service is a process-wide
singleton (``get_sepa_mandate_service``), ``_sequence_cache`` has no TTL and no
production caller invalidates it, so one transient failure pinned a guessed
FRST/RCUR for that mandate:invoice pair until the worker restarted. The cached
value is written onto the Direct Debit Batch row and from there into pain.008
``SeqTp``.

Two failure paths, each given its own test, with a real value that DIFFERS from
the fallback so the recovery assertion can fail:

* the service's own broad ``except`` (fallback RCUR; real value FRST for a
  mandate that was never collected);
* ``get_mandate_sequence_type``'s own swallow, which returns FRST (fallback FRST;
  real value RCUR for a mandate with a Collected usage row) and used to be cached
  as if it were a determination.

Failure is injected at the real lookup (``DatabaseQuery.execute`` for the usage child
table, or the determination function itself); the second call is NOT patched.
"""

from unittest.mock import patch

import frappe
from frappe.model.qb_query import DatabaseQuery
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage import sepa_mandate_usage
from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
    create_mandate_usage_record,
)
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

_real_execute = DatabaseQuery.execute


def _fail_usage_query(exc):
    """Fail the SEPA Mandate Usage query inside DatabaseQuery.execute, below
    frappe.get_all and below the handlers under test; every other query runs for real."""

    def _2628_fail_lookup(query, *args, **kwargs):
        if query.doctype == "SEPA Mandate Usage":
            raise exc
        return _real_execute(query, *args, **kwargs)

    return patch.object(DatabaseQuery, "execute", _2628_fail_lookup)


class Test2628SequenceCacheDoesNotPoison(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.service = SEPAMandateService()
        self.invoice = f"SINV-2628-{frappe.generate_hash(length=6)}"

    def _key(self, mandate):
        return f"{mandate.name}:{self.invoice}"

    def _collected_mandate(self):
        mandate = self.create_test_sepa_mandate(scenario="normal")
        usage_name = create_mandate_usage_record(
            mandate_name=mandate.name,
            reference_doctype="Sales Invoice",
            reference_name=f"PRIOR-{frappe.generate_hash(length=8)}",
            amount=10,
            sequence_type="FRST",
        )
        for row in frappe.get_doc("SEPA Mandate", mandate.name).usage_history:
            if row.name == usage_name:
                row.db_set("status", "Collected", update_modified=False)
                row.db_set("processing_date", today(), update_modified=False)
        return mandate

    def test_premise_real_values_differ_from_both_fallbacks(self):
        """Control: the real answers are FRST (fresh) and RCUR (collected), so a
        recovery assertion cannot pass on a leftover fallback."""
        fresh = self.create_test_sepa_mandate(scenario="normal")
        collected = self._collected_mandate()
        self.assertEqual(
            self.service.get_sequence_types_batch([(fresh.name, self.invoice)])[self._key(fresh)], "FRST"
        )
        self.assertEqual(
            self.service.get_sequence_types_batch([(collected.name, self.invoice)])[self._key(collected)],
            "RCUR",
        )

    def test_service_level_failure_returns_fallback_uncached_then_recovers(self):
        mandate = self.create_test_sepa_mandate(scenario="normal")
        self.expectErrorLog("SEPA Mandate Service - Sequence Type Error")
        pair = [(mandate.name, self.invoice)]

        with patch.object(sepa_mandate_usage, "get_mandate_sequence_type", side_effect=RuntimeError("boom")):
            first = self.service.get_sequence_types_batch(pair)
        self.assertEqual(first[self._key(mandate)], "RCUR")
        self.assertNotIn(self._key(mandate), self.service._sequence_cache)

        second = self.service.get_sequence_types_batch(pair)
        self.assertEqual(second[self._key(mandate)], "FRST")

    def test_determination_swallow_is_not_cached_then_recovers(self):
        mandate = self._collected_mandate()
        self.expectErrorLog("Error determining sequence type")
        pair = [(mandate.name, self.invoice)]

        with _fail_usage_query(RuntimeError("transient usage lookup failure")):
            first = self.service.get_sequence_types_batch(pair)
        self.assertEqual(first[self._key(mandate)], "FRST")
        self.assertNotIn(self._key(mandate), self.service._sequence_cache)

        second = self.service.get_sequence_types_batch(pair)
        self.assertEqual(second[self._key(mandate)], "RCUR")

    def test_successful_determination_is_still_cached(self):
        """Control: the fix must not turn the cache off."""
        mandate = self._collected_mandate()
        pair = [(mandate.name, self.invoice)]
        self.service.get_sequence_types_batch(pair)
        self.assertEqual(self.service._sequence_cache[self._key(mandate)], "RCUR")

    def test_deadlock_in_determination_propagates_instead_of_a_guess(self):
        mandate = self._collected_mandate()

        with _fail_usage_query(frappe.QueryDeadlockError("1213")):
            with self.assertRaises(frappe.QueryDeadlockError):
                self.service.get_sequence_types_batch([(mandate.name, self.invoice)])
        self.assertNotIn(self._key(mandate), self.service._sequence_cache)
