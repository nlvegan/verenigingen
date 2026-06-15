"""
Tests for SEPABatchProcessor's batch-building / coverage / eligibility logic.

verenigingen/verenigingen_payments/services/sepa_batch_processor.py is a large
service. This module targets its testable, side-effect-light logic with real
DocTypes rather than mocks:

- coverage-period validation against billing frequency (the rolling-period math
  that decides whether an invoice's coverage window is the right length)
- invoice-description generation (contribution-mode branches + coverage labelling)
- get-or-create of the per-(type,frequency) dues Item
- the two Direct Debit Batch document builders
- active-mandate resolution + member_has_sepa_enabled
- eligible-dues-schedule discovery and existing-invoice lookup
- pain.002 return-file parsing + find_invoice_in_batch matching

The processor's __init__ needs a SEPA company config; we seed the EUR test
company so it constructs cleanly, exactly as the production scheduler path does.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.sepa_batch_processor import (
    SEPABatchProcessor,
    SEPAProcessor,
    get_sepa_batch_processor,
)


class TestSEPABatchProcessorPureLogic(EnhancedTestCase):
    """Methods that need no DocTypes - coverage math, description text, builders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The processor reads a company from the SEPA config at construction.
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.processor = SEPABatchProcessor()

    # --- factory / aliases ---------------------------------------------------

    def test_factory_and_alias_return_processor(self):
        self.assertIsInstance(get_sepa_batch_processor(), SEPABatchProcessor)
        # SEPAProcessor is a backwards-compat alias for the same class.
        self.assertIs(SEPAProcessor, SEPABatchProcessor)

    def test_processor_constructs_with_dependencies(self):
        self.assertIsNotNone(self.processor.config_manager)
        self.assertIsNotNone(self.processor.mandate_service)
        self.assertIsNotNone(self.processor.error_handler)
        self.assertIsNotNone(self.processor.performance_optimizer)

    # --- validate_coverage_period -------------------------------------------

    def _schedule(self, start, end, freq):
        return {
            "name": "TEST-SCHED",
            "last_invoice_coverage_start": start,
            "last_invoice_coverage_end": end,
            "billing_frequency": freq,
        }

    def test_coverage_period_missing_dates(self):
        issue = self.processor.validate_coverage_period(self._schedule(None, None, "Monthly"), today())
        self.assertEqual(issue, "Missing coverage period dates")

    def test_coverage_period_monthly_within_tolerance(self):
        # 30-day window (inclusive) for Monthly (expected ~30, tolerance 3) -> OK.
        start = getdate("2026-01-01")
        end = add_days(start, 29)  # 30 days inclusive
        issue = self.processor.validate_coverage_period(
            self._schedule(start, end, "Monthly"), today()
        )
        self.assertIsNone(issue)

    def test_coverage_period_monthly_out_of_tolerance(self):
        # A 10-day window labelled Monthly is well outside tolerance -> flagged.
        start = getdate("2026-01-01")
        end = add_days(start, 9)
        issue = self.processor.validate_coverage_period(
            self._schedule(start, end, "Monthly"), today()
        )
        self.assertIsNotNone(issue)
        self.assertIn("Monthly", issue)

    def test_coverage_period_weekly_exact(self):
        start = getdate("2026-01-01")
        end = add_days(start, 6)  # 7 days inclusive
        issue = self.processor.validate_coverage_period(
            self._schedule(start, end, "Weekly"), today()
        )
        self.assertIsNone(issue)

    def test_coverage_period_daily_exact(self):
        start = getdate("2026-01-01")
        issue = self.processor.validate_coverage_period(
            self._schedule(start, start, "Daily"), today()
        )
        self.assertIsNone(issue)

    def test_coverage_period_annual_within_tolerance(self):
        start = getdate("2026-01-01")
        end = add_days(start, 364)  # 365 days inclusive
        issue = self.processor.validate_coverage_period(
            self._schedule(start, end, "Annual"), today()
        )
        self.assertIsNone(issue)

    def test_coverage_period_custom_frequency_skipped(self):
        # Unknown billing frequency: validation is intentionally skipped (None).
        start = getdate("2026-01-01")
        issue = self.processor.validate_coverage_period(
            self._schedule(start, add_days(start, 100), "Fortnightly"), today()
        )
        self.assertIsNone(issue)

    def test_validate_coverage_periods_batch_collects_only_issues(self):
        start = getdate("2026-01-01")
        good = self._schedule(start, add_days(start, 29), "Monthly")
        good["name"] = "GOOD"
        bad = self._schedule(start, add_days(start, 9), "Monthly")
        bad["name"] = "BAD"
        issues = self.processor.validate_coverage_periods_batch([good, bad], today())
        self.assertIn("BAD", issues)
        self.assertNotIn("GOOD", issues)

    # --- find_invoice_in_batch ----------------------------------------------

    def test_find_invoice_in_batch_matches_end_to_end_id(self):
        batch = frappe.new_doc("Direct Debit Batch")
        batch.append("invoices", {"invoice": "ACC-SINV-0001", "status": "Pending"})
        batch.append("invoices", {"invoice": "ACC-SINV-0002", "status": "Pending"})
        found = self.processor.find_invoice_in_batch(batch, {"end_to_end_id": "ACC-SINV-0002"})
        self.assertIsNotNone(found)
        self.assertEqual(found.invoice, "ACC-SINV-0002")

    def test_find_invoice_in_batch_returns_none_when_absent(self):
        batch = frappe.new_doc("Direct Debit Batch")
        batch.append("invoices", {"invoice": "ACC-SINV-0001", "status": "Pending"})
        self.assertIsNone(
            self.processor.find_invoice_in_batch(batch, {"end_to_end_id": "MISSING"})
        )

    # --- parse_sepa_return_file (defusedxml stub) ---------------------------

    def test_parse_return_file_missing_file_returns_empty(self):
        # The stub parser logs and returns [] on any parse error (e.g. no file).
        result = self.processor.parse_sepa_return_file("/nonexistent/return.xml")
        self.assertEqual(result, [])

    def test_parse_return_file_valid_xml_returns_empty_list(self):
        # The pain.002 body parsing is a documented stub: a well-formed file still
        # yields [] until the bank-specific format is implemented. Pin that.
        path = frappe.get_site_path("private", "files", "test_pain002_stub.xml")
        with open(path, "w") as f:
            f.write('<?xml version="1.0"?><Document><CstmrPmtStsRpt/></Document>')
        try:
            result = self.processor.parse_sepa_return_file(path)
            self.assertEqual(result, [])
        finally:
            import os

            os.remove(path)


class TestSEPABatchProcessorBuilders(EnhancedTestCase):
    """Batch-document builders and the dues-item helper."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.processor = SEPABatchProcessor()

    def test_create_batch_from_invoices_sets_defaults(self):
        coll = getdate("2026-03-02")
        batch = self.processor.create_batch_from_invoices([], coll)
        self.assertEqual(batch.batch_type, "CORE")
        self.assertEqual(batch.sequence_type, "RCUR")
        self.assertEqual(batch.currency, "EUR")
        self.assertEqual(batch.status, "Draft")
        self.assertEqual(batch.batch_date, coll)
        self.assertIn("March 2026", batch.batch_description)
        self.assertTrue(getattr(batch, "_automated_processing", False))

    def test_create_batch_document_sets_defaults(self):
        coll = getdate("2026-03-02")
        batch = self.processor.create_batch_document([], coll)
        self.assertEqual(batch.batch_type, "CORE")
        self.assertEqual(batch.sequence_type, "RCUR")
        self.assertEqual(batch.currency, "EUR")
        self.assertEqual(batch.status, "Draft")
        self.assertTrue(getattr(batch, "_automated_processing", False))

    def test_get_or_create_dues_item_is_idempotent(self):
        schedule = frappe._dict(
            {"membership_type": "Test Type ZZZ", "billing_frequency": "Monthly"}
        )
        code1 = self.processor.get_or_create_dues_item(schedule)
        self.assertTrue(frappe.db.exists("Item", code1))
        # Code is derived deterministically from type+frequency.
        self.assertEqual(code1, "DUES-TEST-TYPE-ZZZ-MONTHLY")
        # Second call must reuse the same Item, not error on duplicate.
        code2 = self.processor.get_or_create_dues_item(schedule)
        self.assertEqual(code1, code2)


class TestSEPABatchProcessorIntegration(EnhancedTestCase):
    """Methods that touch real Member / SEPA Mandate / Dues Schedule data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.processor = SEPABatchProcessor()
        self.factory = self._sepa_factory()

    def _sepa_factory(self):
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        return SEPATestDataFactory(seed=4242, use_faker=True)

    def _member_with_membership(self, birth_date):
        """A member with an active membership, so the dues-schedule factory can
        derive a membership_type (a Dues Schedule requires the member to have an
        active membership)."""
        member = self.create_test_member(birth_date=birth_date)
        self.create_test_membership(member_name=member.name)
        return member

    def _sepa_schedule(self, member_name, **fields):
        """Create the member's SEPA dues schedule, then force the fields the
        processor reads.

        The factory reuses the schedule that Membership.after_insert already
        auto-created and only re-points payment_terms_template, so billing
        frequency / next_invoice_date / test_mode would otherwise carry the
        membership-type template defaults. Set them explicitly and persist.
        """
        schedule = self.factory.create_test_membership_dues_schedule(
            member=member_name, payment_terms_template="SEPA Direct Debit"
        )
        fields.setdefault("test_mode", 0)
        fields.setdefault("auto_generate", 1)
        fields.setdefault("status", "Active")
        for key, value in fields.items():
            setattr(schedule, key, value)
        schedule.flags.ignore_validate = True
        schedule.save()
        return schedule

    # --- get_active_mandate (direct-link branch) -----------------------------

    def test_get_active_mandate_honours_cached_reference(self):
        """If a schedule ever carries an explicit mandate reference (the optional
        cached `active_mandate`), that mandate is returned directly without a
        member lookup. Membership Dues Schedule has no such column today, so this
        is exercised via a dict that supplies one."""
        member = self._member_with_membership("1990-01-01")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        schedule = frappe._dict({"member": member.name, "active_mandate": mandate.name})
        resolved = self.processor.get_active_mandate(schedule)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, mandate.name)

    def test_get_active_mandate_falls_back_to_member_lookup(self):
        """With no cached reference, the member's most recent active mandate is
        resolved."""
        member = self._member_with_membership("1991-02-02")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        schedule = frappe._dict({"member": member.name, "active_mandate": None})
        resolved = self.processor.get_active_mandate(schedule)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, mandate.name)

    def test_get_active_mandate_resolves_by_member_on_real_schedule(self):
        """A real Membership Dues Schedule has no `active_mandate` field. The
        resolver now reads the field defensively via getattr (absent -> None) and
        falls back to the member lookup, instead of raising AttributeError as it
        did before the fix. Returns the member's active mandate, or None when the
        member has none."""
        member_with = self._member_with_membership("1992-03-03")
        mandate = self.factory.create_test_sepa_mandate(member=member_with.name, status="Active")
        schedule_with = self._sepa_schedule(member_with.name)
        resolved = self.processor.get_active_mandate(schedule_with)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, mandate.name)

        member_without = self._member_with_membership("1992-04-04")
        schedule_without = self._sepa_schedule(member_without.name)
        self.assertIsNone(self.processor.get_active_mandate(schedule_without))

    # --- member_has_sepa_enabled --------------------------------------------

    def test_member_has_sepa_enabled_false_without_sepa_terms(self):
        """Non-SEPA payment terms -> the early guard returns False before any
        mandate lookup. This is the branch that works correctly today."""
        member = self._member_with_membership("1993-04-04")
        schedule = self.factory.create_test_membership_dues_schedule(
            member=member.name, payment_terms_template=None
        )
        schedule.payment_terms_template = None
        schedule.flags.ignore_validate = True
        schedule.save()
        self.assertFalse(self.processor.member_has_sepa_enabled(schedule))

    def test_member_has_sepa_enabled_true_with_active_mandate(self):
        """A SEPA member WITH a valid active mandate is reported as enabled. Before
        the get_active_mandate fix this wrongly returned False (the missing-field
        AttributeError was swallowed by the try/except), silently excluding the
        member from direct-debit batches."""
        member = self._member_with_membership("1994-05-05")
        self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        schedule = self._sepa_schedule(member.name)
        self.assertTrue(self.processor.member_has_sepa_enabled(schedule))

    def test_member_has_sepa_enabled_false_without_mandate(self):
        """SEPA payment terms but no active mandate -> not enabled."""
        member = self._member_with_membership("1996-07-07")
        schedule = self._sepa_schedule(member.name)
        self.assertFalse(self.processor.member_has_sepa_enabled(schedule))

    # --- get_eligible_dues_schedules ----------------------------------------

    def test_get_eligible_dues_schedules_includes_due_sepa_schedule(self):
        member = self._member_with_membership("1995-06-06")
        self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        schedule = self._sepa_schedule(
            member.name, next_invoice_date=today(), invoice_days_before=30
        )
        eligible = self.processor.get_eligible_dues_schedules(today())
        names = [s.name for s in eligible]
        self.assertIn(schedule.name, names)

    def test_get_eligible_dues_schedules_excludes_far_future(self):
        member = self._member_with_membership("1996-07-07")
        self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        # next_invoice_date 120 days out with a 1-day pre-window -> not yet due.
        schedule = self._sepa_schedule(
            member.name, next_invoice_date=add_days(today(), 120), invoice_days_before=1
        )
        eligible = self.processor.get_eligible_dues_schedules(today())
        names = [s.name for s in eligible]
        self.assertNotIn(schedule.name, names)

    # --- generate_invoice_description ---------------------------------------

    def test_generate_invoice_description_includes_coverage_and_frequency(self):
        member = self._member_with_membership("1997-08-08")
        schedule = self._sepa_schedule(
            member.name, billing_frequency="Monthly", contribution_mode="Tier"
        )
        desc = self.processor.generate_invoice_description(
            schedule, getdate("2026-01-01"), getdate("2026-01-31")
        )
        self.assertIn("Membership dues - Monthly", desc)
        self.assertIn("Coverage: 2026-01-01 to 2026-01-31", desc)
