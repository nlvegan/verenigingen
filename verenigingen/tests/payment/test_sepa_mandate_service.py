"""
Real-integration tests for SEPAMandateService.

Creates REAL Member + SEPA Mandate records via the test factory and exercises
the batch lookup, in-process caching, batch validation, and cache invalidation
paths against the real database. No business-logic mocking.

Complements the SEPA sequence-type tests in tests/sepa/ which focus on
sequence determination rather than the lookup/validation/caching surface here.
"""

import frappe

from verenigingen.tests.support.sepa_test_company import ensure_sepa_payment_terms_template
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
        # Cached even though None. Keyed on (member, purpose) since #597 -- one
        # member can hold an Active mandate per purpose, so a member-only key would
        # answer a donations lookup with the memberships result.
        key = self.service.mandate_cache_key(other.name)
        self.assertIn(key, self.service._mandate_cache)
        self.assertIsNone(self.service._mandate_cache[key])

    def test_batch_uses_cache_on_second_call(self):
        # Prime cache
        self.service.get_active_mandate_batch([self.member_name])
        key = self.service.mandate_cache_key(self.member_name)
        self.assertIn(key, self.service._mandate_cache)
        # Poison the DB-bypassing cache to a sentinel and confirm cache is used
        sentinel = {"name": "CACHED-SENTINEL", "member": self.member_name, "status": "Active"}
        self.service._mandate_cache[key] = sentinel
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

    def test_validate_mandate_status_batch_active_is_valid(self):
        """A normal Active mandate passes batch validation.

        Regression guard for the fixed 1054 bug: the query used to SELECT the
        non-existent valid_from/valid_until/date_signed columns and crashed on any
        non-empty call. It now reads the real sign_date/expiry_date columns.
        """
        results = self.service.validate_mandate_status_batch([self.mandate.name])
        self.assertIn(self.mandate.name, results)
        self.assertTrue(results[self.mandate.name]["valid"])
        self.assertEqual(results[self.mandate.name]["issues"], [])

    def test_validate_mandate_status_batch_flags_expired(self):
        """A mandate whose expiry_date is in the past is flagged expired/invalid."""
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "expiry_date", "2020-01-01")
        results = self.service.validate_mandate_status_batch([self.mandate.name])
        result = results[self.mandate.name]
        self.assertFalse(result["valid"])
        self.assertIn("Mandate has expired", result["issues"])

    def test_validate_mandate_status_batch_flags_inactive(self):
        """A non-Active mandate is flagged invalid with a status issue."""
        suspended = self.create_test_sepa_mandate(scenario="suspended")
        results = self.service.validate_mandate_status_batch([suspended.name])
        result = results[suspended.name]
        self.assertFalse(result["valid"])
        self.assertTrue(any("not Active" in i for i in result["issues"]))

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
        key = self.service.mandate_cache_key(self.member_name)
        self.assertIn(key, self.service._mandate_cache)
        self.service.invalidate_member_cache(self.member_name)
        self.assertNotIn(key, self.service._mandate_cache)

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


class TestGetSepaInvoicesWithMandatesCurrencyFilter(VereningingenTestCase):
    """#1440: `get_sepa_invoices_with_mandates` backs the AUTOMATED monthly SEPA
    collection path (no operator reviews the list before submission), and its raw
    SQL had no `si.currency = 'EUR'` filter -- invisible to the get_all/get_list
    AST sweeps behind #567/#578 because it is a `frappe.db.sql` query. Builds a
    genuinely eligible row (submitted Unpaid invoice, SEPA Direct Debit dues
    schedule, Active mandate with `used_for_memberships=1`) the same way the real
    monthly batch does.
    """

    def setUp(self):
        super().setUp()
        self.service = SEPAMandateService()
        # On a fresh site nothing seeds this master (#1505); it is a shared,
        # lazily-built get-or-create wrapped in suspend_insert_capture() by
        # its own definition, so calling it here is safe under the drain.
        ensure_sepa_payment_terms_template()

    def _make_collectible_invoice(self, currency=None, dues_rate=22.0):
        """Submit a Sales Invoice that satisfies every join/filter in
        `get_sepa_invoices_with_mandates` except (optionally) currency.

        Forces `currency` via `db_set` AFTER submit, matching the sibling
        currency-guard tests in `test_dues_invoice_workflow.py` (#1286/#1442):
        `create_test_sales_invoice` resolves its company from the ambient
        default (test_site_1's `_Test Company`, currency INR), not a pinned
        EUR company, so setting `currency` pre-submit would fight ERPNext's
        own multi-currency validation. Setting it *after* submit via `db_set`
        writes the value directly and is what every other guard test does.
        """
        member = self.create_test_member(
            first_name="SepaColl",
            last_name=f"Tester{frappe.generate_hash(length=4)}",
            email=f"sepa.coll.{frappe.generate_hash(length=8).lower()}@example.com",
        )
        membership_type = self.create_test_membership_type(minimum_amount=0)
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        if membership.docstatus == 0:
            membership.flags.skip_dues_schedule_creation = True
            membership.submit()

        # create_test_membership may auto-create a schedule on submit; cancel any
        # pre-existing Active one so ours below is the single Active one the
        # query's `si.membership_dues_schedule_display` join resolves to.
        for existing in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", existing, "status", "Cancelled")

        schedule = self.create_test_dues_schedule(
            member=member.name,
            membership_type=membership_type.name,
            dues_rate=dues_rate,
            billing_frequency="Monthly",
            payment_terms_template="SEPA Direct Debit",
            schedule_name=f"Test-SMS-{frappe.generate_hash(length=10)}",
        )
        # scenario="normal" (the default) sets used_for_memberships=1, which the
        # query's mandate JOIN requires (#597 purpose filter).
        mandate = self.create_test_sepa_mandate(member=member.name)

        member.reload()
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.save()
            self.track_doc("Customer", customer.name)
            member.customer = customer.name
            member.save()

        invoice = self.create_test_sales_invoice(member=member.name)
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        if invoice.docstatus == 0:
            invoice.submit()
        frappe.db.set_value(
            "Sales Invoice", invoice.name, "currency", currency or "EUR", update_modified=False
        )
        invoice.reload()
        return invoice

    def test_includes_eur_invoice_on_a_non_eur_company(self):
        """Positive control: a genuinely EUR invoice must still be collected even
        though its own company is NOT EUR (test_site_1's ambient `_Test Company`
        is INR). Pins the fixture precondition that makes this discriminate a
        correct `si.currency = 'EUR'` fix from a plausible wrong one that instead
        compares against the invoice's COMPANY currency (#1445 review history)."""
        invoice = self._make_collectible_invoice(currency="EUR")
        self.assertNotEqual(
            frappe.db.get_value("Company", invoice.company, "default_currency"),
            "EUR",
            "fixture precondition: the invoice's own company must not be EUR, or "
            "this test cannot tell 'compares invoice.currency' from 'compares "
            "company currency'",
        )
        result = self.service.get_sepa_invoices_with_mandates(frappe.utils.today())
        names = {row["name"] for row in result}
        self.assertIn(invoice.name, names)

    def test_excludes_non_eur_invoice(self):
        """A non-EUR invoice with an otherwise fully eligible mandate/schedule must
        NOT be offered to the automated monthly SEPA collection path (#1440)."""
        invoice = self._make_collectible_invoice(currency="USD")
        result = self.service.get_sepa_invoices_with_mandates(frappe.utils.today())
        names = {row["name"] for row in result}
        self.assertNotIn(invoice.name, names, "a non-EUR invoice must not be SEPA-collectible")
