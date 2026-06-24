#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coverage tests for verenigingen_payments/services/sepa_xml_adapter.py

The sibling test_sepa_xml_adapter.py covers transaction building, the validation
summary dataclass and the invoice-item / cache sign-date paths (with MagicMock
invoice items). This file fills the remaining gaps with REAL DB state and the
pure mapping helpers (no frappe.db mocks):

- _lookup_mandate_sign_date: REAL SEPA Mandate lookups by mandate_id and by
  member fallback (asserting the real sign_date is returned and cached), plus
  the no-reference and not-found fallbacks (today + used_fallback True).
- _prefetch_mandate_data: bulk-prefetch a REAL active mandate into the cache.
- _get_mandate_sign_date: cache-miss -> DB lookup integration end to end.
- _get_batch_sequence_type: dedicated field, legacy batch_type fallback, default.
- _get_local_instrument: CORE / B2B / COR1 / legacy-sequence default mapping.
- _handle_validation_issues: strict-mode raises on missing mandate dates;
  permissive mode only warns.
- _get_financial_admin_emails: parsing the configured comma list (Settings read).

Mandate lookups run against real SEPA Mandate rows created via the test factory.
"""

from datetime import date

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_xml_adapter import (
    BatchValidationSummary,
    SEPAXMLAdapter,
)
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import (
    SEPALocalInstrument,
    SEPASequenceType,
)


class _InvoiceRow:
    """Attribute-only invoice-item stand-in. The adapter reads only
    mandate_reference / member / mandate_sign_date / iban / etc. off each row."""

    def __init__(self, mandate_reference=None, member=None, mandate_sign_date=None):
        self.mandate_reference = mandate_reference
        self.member = member
        self.mandate_sign_date = mandate_sign_date


class _BatchStub:
    def __init__(self, sequence_type=None, batch_type=None):
        self.sequence_type = sequence_type
        self.batch_type = batch_type


class TestMandateSignDateDBLookup(EnhancedTestCase):
    """Real SEPA Mandate sign-date lookups (no DB mocks)."""

    def setUp(self):
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def tearDown(self):
        self.adapter.clear_cache()
        super().tearDown()

    def _make_active_mandate(self, sign_date):
        member = self.create_test_member(
            first_name="Sepa",
            last_name="Lookup",
            email=f"sepa.lookup.{self.factory.test_run_id}@example.com",
        )
        mandate = self.create_test_sepa_mandate(member_name=member.name, status="Active", sign_date=sign_date)
        return member, mandate

    def test_lookup_by_mandate_id_returns_real_sign_date_and_caches(self):
        sign = date(2024, 3, 11)
        _member, mandate = self._make_active_mandate(sign)

        result_date, used_fallback = self.adapter._lookup_mandate_sign_date(
            mandate_reference=mandate.mandate_id, member=None
        )
        self.assertEqual(result_date, sign)
        self.assertFalse(used_fallback)
        # Cached for subsequent lookups (prevents N+1).
        self.assertIn(mandate.mandate_id, self.adapter._mandate_cache)
        self.assertEqual(self.adapter._mandate_cache[mandate.mandate_id]["sign_date"], sign)

    def test_lookup_by_member_fallback_when_mandate_id_unknown(self):
        """An unknown mandate_id but a known member resolves via the member-based
        fallback query and caches under BOTH the real mandate_id and the supplied
        (wrong) reference."""
        sign = date(2024, 7, 9)
        member, mandate = self._make_active_mandate(sign)

        bogus_ref = "MAND-DOES-NOT-EXIST-XYZ"
        result_date, used_fallback = self.adapter._lookup_mandate_sign_date(
            mandate_reference=bogus_ref, member=member.name
        )
        self.assertEqual(result_date, sign)
        self.assertFalse(used_fallback)
        # Cached under the real mandate_id and under the bogus ref.
        self.assertEqual(self.adapter._mandate_cache[mandate.mandate_id]["sign_date"], sign)
        self.assertEqual(self.adapter._mandate_cache[bogus_ref]["sign_date"], sign)

    def test_lookup_no_reference_falls_back_to_today(self):
        result_date, used_fallback = self.adapter._lookup_mandate_sign_date(
            mandate_reference=None, member=None
        )
        self.assertEqual(result_date, date.today())
        self.assertTrue(used_fallback)

    def test_lookup_not_found_falls_back_to_today(self):
        result_date, used_fallback = self.adapter._lookup_mandate_sign_date(
            mandate_reference="MAND-TOTALLY-MISSING-999", member=None
        )
        self.assertEqual(result_date, date.today())
        self.assertTrue(used_fallback)

    def test_get_mandate_sign_date_db_integration(self):
        """End-to-end: a row with only a mandate_reference (no sign date, empty
        cache) resolves via the real DB lookup."""
        sign = date(2024, 5, 2)
        _member, mandate = self._make_active_mandate(sign)
        row = _InvoiceRow(mandate_reference=mandate.mandate_id, member=None, mandate_sign_date=None)

        result_date, used_fallback = self.adapter._get_mandate_sign_date(row)
        self.assertEqual(result_date, sign)
        self.assertFalse(used_fallback)

    def test_prefetch_populates_cache_from_real_mandate(self):
        sign = date(2024, 9, 30)
        _member, mandate = self._make_active_mandate(sign)
        rows = [_InvoiceRow(mandate_reference=mandate.mandate_id, mandate_sign_date=None)]

        self.adapter._prefetch_mandate_data(rows)

        self.assertIn(mandate.mandate_id, self.adapter._mandate_cache)
        self.assertEqual(self.adapter._mandate_cache[mandate.mandate_id]["sign_date"], sign)

    def test_prefetch_skips_rows_with_inline_sign_date(self):
        """Rows that already carry a sign date are not looked up; with no other
        rows the cache stays empty and no query is needed."""
        rows = [_InvoiceRow(mandate_reference="MAND-INLINE", mandate_sign_date=date(2024, 1, 1))]
        self.adapter._prefetch_mandate_data(rows)
        self.assertNotIn("MAND-INLINE", self.adapter._mandate_cache)


class TestSequenceAndInstrumentMapping(EnhancedTestCase):
    """Pure mapping helpers (no DB)."""

    def setUp(self):
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def test_batch_sequence_type_from_dedicated_field(self):
        self.assertEqual(
            self.adapter._get_batch_sequence_type(_BatchStub(sequence_type="FRST")),
            SEPASequenceType.FRST,
        )
        self.assertEqual(
            self.adapter._get_batch_sequence_type(_BatchStub(sequence_type="FNAL")),
            SEPASequenceType.FNAL,
        )

    def test_batch_sequence_type_legacy_batch_type_fallback(self):
        """A batch with no sequence_type but a legacy sequence value in batch_type
        honours the legacy field."""
        self.assertEqual(
            self.adapter._get_batch_sequence_type(_BatchStub(sequence_type=None, batch_type="OOFF")),
            SEPASequenceType.OOFF,
        )

    def test_batch_sequence_type_defaults_to_rcur(self):
        """Neither field carries a valid sequence -> RCUR. batch_type=CORE is a
        SCHEME value, not a sequence, so it must NOT be treated as a sequence."""
        self.assertEqual(
            self.adapter._get_batch_sequence_type(_BatchStub(sequence_type=None, batch_type="CORE")),
            SEPASequenceType.RCUR,
        )

    def test_local_instrument_mapping(self):
        self.assertEqual(self.adapter._get_local_instrument("CORE"), SEPALocalInstrument.CORE)
        self.assertEqual(self.adapter._get_local_instrument("B2B"), SEPALocalInstrument.B2B)
        self.assertEqual(self.adapter._get_local_instrument("COR1"), SEPALocalInstrument.COR1)

    def test_local_instrument_legacy_sequence_defaults_to_core(self):
        """A legacy batch_type still holding a sequence value (RCUR) has no scheme
        meaning -> default CORE."""
        self.assertEqual(self.adapter._get_local_instrument("RCUR"), SEPALocalInstrument.CORE)
        self.assertEqual(self.adapter._get_local_instrument(None), SEPALocalInstrument.CORE)


class TestHandleValidationIssues(EnhancedTestCase):
    """_handle_validation_issues strict vs permissive behaviour."""

    def setUp(self):
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def test_strict_mode_raises_on_missing_mandate_dates(self):
        """Strict mode must FAIL XML generation when mandate sign dates are missing
        rather than silently using today's date."""
        self.adapter._validation_summary = BatchValidationSummary(
            total_invoices=2, successful_transactions=2, missing_mandate_dates=1
        )
        # _is_strict_mode reads a Settings single value; force strict on via a
        # Settings access (permitted) without touching business logic.
        original = frappe.db.get_single_value("Verenigingen Settings", "sepa_strict_mandate_validation")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "sepa_strict_mandate_validation", 1)
            with self.assertRaises(frappe.exceptions.ValidationError):
                self.adapter._handle_validation_issues("BATCH-STRICT-1")
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "sepa_strict_mandate_validation", original or 0
            )

    def test_permissive_mode_only_warns_on_missing_dates(self):
        """Permissive mode (default) must NOT raise on missing mandate dates - it
        logs a warning and continues."""
        self.adapter._validation_summary = BatchValidationSummary(
            total_invoices=1, successful_transactions=1, missing_mandate_dates=1
        )
        original = frappe.db.get_single_value("Verenigingen Settings", "sepa_strict_mandate_validation")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "sepa_strict_mandate_validation", 0)
            # Should complete without raising (no skipped tx -> no alert email).
            self.adapter._handle_validation_issues("BATCH-PERMISSIVE-1")
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "sepa_strict_mandate_validation", original or 0
            )


class TestFinancialAdminEmails(EnhancedTestCase):
    """_get_financial_admin_emails parses the configured comma list."""

    def setUp(self):
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def test_parses_configured_email_list(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "stuck_schedule_notification_emails")
        try:
            frappe.db.set_single_value(
                "Verenigingen Settings",
                "stuck_schedule_notification_emails",
                " admin1@example.org , admin2@example.org ,",
            )
            emails = self.adapter._get_financial_admin_emails()
            self.assertEqual(emails, ["admin1@example.org", "admin2@example.org"])
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "stuck_schedule_notification_emails", original or ""
            )

    def test_empty_config_returns_empty_list(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "stuck_schedule_notification_emails")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "stuck_schedule_notification_emails", "")
            self.assertEqual(self.adapter._get_financial_admin_emails(), [])
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "stuck_schedule_notification_emails", original or ""
            )
