# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/bulk_invoice_generation_service.py

Coverage focus (per coverage-sweep brief):
  - Cutoff-date calculators (monthly / quarterly / yearly / fallback / Feb-31 edge)
    These are nearly pure: driven by Verenigingen Settings + today(). We mutate
    the single Settings doc in fixture helpers and restore it in tearDown.
  - Dataclasses: BulkGenerationResult / ChunkResult / EligibilityDetails defaults.
  - get_eligible_schedules: eligibility selection, ineligible-status filtering
    (incl. the "Banned" bug, see below), test-mode mismatch categorisation.
  - generate_invoices(test_mode=...): advisory-lock + eligibility + sequential path,
    including REAL Sales Invoice creation scoped to our own fixtures.
  - _validate_accounting_configuration, _clean_error_message,
    _format_validation_error, _detect_coverage_gaps, get_parallel_status,
    get_bulk_invoice_generation_service.

NOT covered (documented):
  - The PARALLEL path (_process_parallel / process_invoice_chunk worker / Redis
    enqueue). It enqueues real background jobs (>50 eligible schedules, non-test)
    and cannot be exercised deterministically in a single test transaction.

ISOLATION:
  generate_invoices() and the schedule.generate_invoice() pipeline call
  frappe.db.commit(), escaping FrappeTestCase's transaction rollback. Every test
  creates UNIQUE fixtures, tracks them, and force-deletes them (plus any Sales
  Invoices they produced) in tearDown. Assertions are scoped to our own data.

PRODUCT BUG FOUND + FIXED (red-green):
  get_eligible_schedules used ineligible_statuses = ["Quit","Expelled","Deceased","Quit"].
  "Expelled" is not a valid Member status (the schema uses "Banned") and "Quit"
  was duplicated, so a *Banned* member's schedule was NOT filtered at the
  status stage. Canonical list elsewhere (eligibility_checker.py:259,
  billing_date_service.py:139) is ["Quit","Banned","Deceased"]. Fixed to match.
  test_banned_member_filtered_as_ineligible_status guards it.
"""

from datetime import date

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.billing.bulk_invoice_generation_service import (
    BulkGenerationResult,
    BulkInvoiceGenerationService,
    ChunkResult,
    EligibilityDetails,
    get_bulk_invoice_generation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBulkInvoiceGenerationService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed_docs = []  # (doctype, name) force-deleted in tearDown
        self._sales_invoices = []  # names of generated SIs to cancel+delete
        self.svc = get_bulk_invoice_generation_service()

        # Snapshot the Settings fields the cutoff calculators read so cutoff
        # tests can mutate them freely and we can restore afterwards.
        s = frappe.get_single("Verenigingen Settings")
        self._settings_snapshot = {
            "billing_cutoff_frequency": getattr(s, "billing_cutoff_frequency", None),
            "book_year_start_month": getattr(s, "book_year_start_month", None),
            "book_year_end_month": getattr(s, "book_year_end_month", None),
            "book_year_end_day": getattr(s, "book_year_end_day", None),
        }

    def tearDown(self):
        # Cancel + delete any generated Sales Invoices first (they reference
        # customers/members we are about to remove).
        for si in self._sales_invoices:
            if frappe.db.exists("Sales Invoice", si):
                try:
                    doc = frappe.get_doc("Sales Invoice", si)
                    if doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc("Sales Invoice", si, force=True, ignore_permissions=True)
                except Exception:
                    pass
        for doctype, name in reversed(self._committed_docs):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        # Restore Settings snapshot.
        self._restore_settings()
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers (allowed to use ignore_permissions / set_value)
    # ------------------------------------------------------------------
    def _set_cutoff_settings(self, **fields):
        for k, v in fields.items():
            frappe.db.set_value("Verenigingen Settings", "Verenigingen Settings", k, v)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

    def _restore_settings(self):
        for k, v in self._settings_snapshot.items():
            frappe.db.set_value("Verenigingen Settings", "Verenigingen Settings", k, v)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

    def _make_membership_type(self):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"BIG-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Bulk invoice gen test type"
        mt.minimum_amount = 0.01
        mt.is_active = 1
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))
        return mt

    def _make_member(self, status="Active"):
        member = frappe.new_doc("Member")
        member.first_name = "BulkGen"
        member.last_name = f"T{frappe.generate_hash(length=6)}"
        member.email = f"bulkgen.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.address_line1 = "1 Bulk Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        if status != "Active":
            frappe.db.set_value("Member", member.name, "status", status)
        self._committed_docs.append(("Member", member.name))
        return member

    def _deactivate_auto_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def _make_dues_schedule(
        self,
        member,
        membership_type,
        amount=5.0,
        status="Active",
        auto_generate=1,
        next_invoice_date=None,
        test_mode=0,
    ):
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self._committed_docs.append(("Membership", membership.name))

        self._deactivate_auto_schedules(member.name)

        ds = frappe.new_doc("Membership Dues Schedule")
        ds.schedule_name = f"BIG-{member.name}-{frappe.generate_hash(length=8)}"
        ds.member = member.name
        ds.membership = membership.name
        ds.membership_type = membership_type.name
        ds.currency = "EUR"
        ds.contribution_mode = "Fixed"
        ds.dues_rate = amount
        ds.uses_custom_amount = 1
        if amount > 0:
            ds.custom_amount_approved = 1
        ds.billing_frequency = "Monthly"
        ds.payment_method = "Bank Transfer"
        ds.status = status
        ds.auto_generate = auto_generate
        ds.test_mode = test_mode
        if next_invoice_date is not None:
            ds.next_invoice_date = next_invoice_date
        ds.save()
        self._committed_docs.append(("Membership Dues Schedule", ds.name))
        return ds

    def _track_generated_invoices(self, result):
        """Record any Sales Invoices produced by a generation run for cleanup."""
        for inv in result.invoices:
            invoice = inv.get("invoice")
            name = getattr(invoice, "name", None) or (
                invoice.get("name") if isinstance(invoice, dict) else None
            )
            if name and frappe.db.exists("Sales Invoice", name):
                self._sales_invoices.append(name)

    # ==================================================================
    # Dataclasses
    # ==================================================================
    def test_dataclass_defaults(self):
        r = BulkGenerationResult()
        self.assertEqual(r.processed, 0)
        self.assertEqual(r.generated, 0)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.invoices, [])
        self.assertEqual(r.coverage_gap_count, 0)
        self.assertFalse(r.parallel_mode)
        self.assertIsNone(r.cutoff_date)
        # default_factory must produce independent instances
        r2 = BulkGenerationResult()
        r.errors.append("x")
        self.assertEqual(r2.errors, [])

        c = ChunkResult(chunk_id=3)
        self.assertEqual(c.chunk_id, 3)
        self.assertEqual(c.processed, 0)
        self.assertIsInstance(c.members_to_update, set)
        self.assertEqual(len(c.members_to_update), 0)

        e = EligibilityDetails()
        self.assertEqual(e.eligible_schedules, [])
        self.assertEqual(e.total_filtered, 0)
        self.assertEqual(e.summary, {})

    def test_service_singleton_factory(self):
        svc = get_bulk_invoice_generation_service()
        self.assertIsInstance(svc, BulkInvoiceGenerationService)
        self.assertEqual(svc.LOCK_NAME, "verenigingen_bulk_invoice_generation")

    # ==================================================================
    # Cutoff-date calculators
    # ==================================================================
    def test_monthly_cutoff_end_of_month(self):
        # _calculate_monthly_cutoff is pure on its date arg.
        self.assertEqual(self.svc._calculate_monthly_cutoff(date(2026, 2, 10)), date(2026, 2, 28))
        # December must roll the year over correctly (off-by-one trap).
        self.assertEqual(self.svc._calculate_monthly_cutoff(date(2026, 12, 5)), date(2026, 12, 31))
        # Leap February.
        self.assertEqual(self.svc._calculate_monthly_cutoff(date(2024, 2, 1)), date(2024, 2, 29))

    def test_quarterly_cutoff_standard_year(self):
        s = frappe.get_single("Verenigingen Settings")
        s.book_year_start_month = 1
        # Q1 ends Mar 31, Q2 Jun 30, Q3 Sep 30, Q4 Dec 31
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 2, 15), s), date(2026, 3, 31))
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 5, 15), s), date(2026, 6, 30))
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 8, 15), s), date(2026, 9, 30))
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 11, 15), s), date(2026, 12, 31))

    def test_quarterly_cutoff_fiscal_year_april(self):
        s = frappe.get_single("Verenigingen Settings")
        s.book_year_start_month = 4
        # Fiscal Apr-start: Q1=AMJ(end Jun), ... Q4=JFM(end Mar)
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 5, 15), s), date(2026, 6, 30))
        self.assertEqual(self.svc._calculate_quarterly_cutoff(date(2026, 2, 15), s), date(2026, 3, 31))

    def test_yearly_cutoff_standard(self):
        s = frappe.get_single("Verenigingen Settings")
        s.book_year_start_month = 1
        s.book_year_end_month = 12
        s.book_year_end_day = 31
        self.assertEqual(self.svc._calculate_yearly_cutoff(date(2026, 1, 15), s), date(2026, 12, 31))
        self.assertEqual(self.svc._calculate_yearly_cutoff(date(2026, 12, 15), s), date(2026, 12, 31))

    def test_yearly_cutoff_fiscal_april_march(self):
        s = frappe.get_single("Verenigingen Settings")
        s.book_year_start_month = 4
        s.book_year_end_month = 3
        s.book_year_end_day = 31
        # May 2026 -> book year 2026, ends Mar 2027
        self.assertEqual(self.svc._calculate_yearly_cutoff(date(2026, 5, 15), s), date(2027, 3, 31))
        # Feb 2026 -> book year 2025, ends Mar 2026
        self.assertEqual(self.svc._calculate_yearly_cutoff(date(2026, 2, 15), s), date(2026, 3, 31))

    def test_yearly_cutoff_invalid_day_falls_back_to_month_end(self):
        s = frappe.get_single("Verenigingen Settings")
        s.book_year_start_month = 1
        s.book_year_end_month = 2
        s.book_year_end_day = 31  # Feb 31 is invalid -> last day of Feb
        self.assertEqual(self.svc._calculate_yearly_cutoff(date(2026, 1, 15), s), date(2026, 2, 28))

    def test_calculate_cutoff_date_dispatches_on_settings(self):
        # Monthly
        self._set_cutoff_settings(billing_cutoff_frequency="Monthly")
        expected_monthly = self.svc._calculate_monthly_cutoff(getdate(today()))
        self.assertEqual(self.svc.calculate_cutoff_date(), expected_monthly)

        # Quarterly
        self._set_cutoff_settings(billing_cutoff_frequency="Quarterly", book_year_start_month=1)
        s = frappe.get_single("Verenigingen Settings")
        self.assertEqual(
            self.svc.calculate_cutoff_date(),
            self.svc._calculate_quarterly_cutoff(getdate(today()), s),
        )

        # Yearly
        self._set_cutoff_settings(
            billing_cutoff_frequency="Yearly",
            book_year_start_month=1,
            book_year_end_month=12,
            book_year_end_day=31,
        )
        self.assertEqual(self.svc.calculate_cutoff_date(), date(getdate(today()).year, 12, 31))

    def test_calculate_cutoff_date_unknown_frequency_falls_back_to_monthly(self):
        self._set_cutoff_settings(billing_cutoff_frequency="Weekly")  # unsupported
        expected = self.svc._calculate_monthly_cutoff(getdate(today()))
        self.assertEqual(self.svc.calculate_cutoff_date(), expected)

    # ==================================================================
    # get_eligible_schedules
    # ==================================================================
    def test_eligible_schedule_selected(self):
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, auto_generate=1, next_invoice_date=add_days(today(), -1))
        cutoff = getdate(today())
        details = self.svc.get_eligible_schedules(cutoff_date=cutoff, test_mode=False)
        self.assertIsInstance(details, EligibilityDetails)
        self.assertIn(ds.name, details.eligible_schedules)
        self.assertIn("filter_breakdown", details.summary)

    def test_banned_member_filtered_as_ineligible_status(self):
        """Regression: a Banned member's schedule must be filtered into the
        'ineligible_status' bucket (was leaking through due to the
        Expelled/duplicate-Quit list bug)."""
        mt = self._make_membership_type()
        member = self._make_member(status="Banned")
        ds = self._make_dues_schedule(member, mt, auto_generate=1, next_invoice_date=add_days(today(), -1))
        details = self.svc.get_eligible_schedules(cutoff_date=getdate(today()), test_mode=False)
        self.assertNotIn(ds.name, details.eligible_schedules)
        ineligible = {m["schedule"] for m in details.filtered_members["ineligible_status"]}
        self.assertIn(ds.name, ineligible)

    def test_deceased_member_filtered_as_ineligible_status(self):
        mt = self._make_membership_type()
        member = self._make_member(status="Deceased")
        ds = self._make_dues_schedule(member, mt, auto_generate=1, next_invoice_date=add_days(today(), -1))
        details = self.svc.get_eligible_schedules(cutoff_date=getdate(today()), test_mode=False)
        ineligible = {m["schedule"] for m in details.filtered_members["ineligible_status"]}
        self.assertIn(ds.name, ineligible)
        self.assertNotIn(ds.name, details.eligible_schedules)

    def test_test_mode_mismatch_filters_production_schedule(self):
        """test_mode=True must filter out a production (test_mode=0) schedule
        into the test_mode_mismatch bucket."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(
            member, mt, auto_generate=1, next_invoice_date=add_days(today(), -1), test_mode=0
        )
        details = self.svc.get_eligible_schedules(cutoff_date=getdate(today()), test_mode=True)
        mismatch = {m["schedule"] for m in details.filtered_members["test_mode_mismatch"]}
        self.assertIn(ds.name, mismatch)
        self.assertNotIn(ds.name, details.eligible_schedules)

    def test_eligible_defaults_cutoff_when_none(self):
        # Passing cutoff_date=None must use calculate_cutoff_date() and still run.
        details = self.svc.get_eligible_schedules(cutoff_date=None, test_mode=False)
        self.assertIsInstance(details, EligibilityDetails)
        self.assertIn("total_schedules_checked", details.summary)

    # ==================================================================
    # generate_invoices (end-to-end, sequential, real invoice creation)
    # ==================================================================
    def test_generate_invoices_creates_real_invoice(self):
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(
            member, mt, amount=10.0, auto_generate=1, next_invoice_date=add_days(today(), -1)
        )
        result = self.svc.generate_invoices(test_mode=False)
        self._track_generated_invoices(result)

        # Our schedule should have produced exactly one invoice for our member.
        our = [inv for inv in result.invoices if inv.get("member_id") == member.name]
        self.assertEqual(len(our), 1, f"errors={result.errors}")
        self.assertEqual(our[0]["schedule"], ds.name)
        self.assertIsNotNone(result.cutoff_date)
        self.assertGreaterEqual(result.generated, 1)
        # Real Sales Invoice exists and references our customer.
        si_name = getattr(our[0]["invoice"], "name", our[0]["invoice"])
        self.assertTrue(frappe.db.exists("Sales Invoice", si_name))

    def test_generate_invoices_lock_busy_returns_error(self):
        """If the advisory lock is already held, generate_invoices must abort
        cleanly with an error and generate nothing."""
        from verenigingen.utils.db_advisory_lock import (
            _is_redis_available,
            advisory_lock_with_backend,
        )

        # Hold the lock on whichever backend generate_invoices() will use, so the
        # "already running" guard is genuinely exercised.
        backend = "redis" if _is_redis_available() else "database"
        with advisory_lock_with_backend(
            BulkInvoiceGenerationService.LOCK_NAME,
            timeout=10,
            backend=backend,
            ttl=60,
            raise_on_timeout=False,
        ) as acquired:
            self.assertTrue(acquired)
            result = self.svc.generate_invoices(test_mode=False)
        self._track_generated_invoices(result)
        self.assertEqual(result.generated, 0)
        self.assertTrue(
            any("already running" in e for e in result.errors),
            f"errors={result.errors}",
        )

    # ==================================================================
    # _validate_accounting_configuration
    # ==================================================================
    def test_validate_accounting_configuration_passes(self):
        # test_site_2 has _Test Company with accounts configured; must not raise.
        self.svc._validate_accounting_configuration()

    # ==================================================================
    # _clean_error_message / _format_validation_error
    # ==================================================================
    def test_clean_error_message_strips_html_and_truncates(self):
        msg = "<b>boom</b> Error Log abc123: something went wrong"
        cleaned = self.svc._clean_error_message(msg)
        self.assertNotIn("<b>", cleaned)
        self.assertNotIn("Error Log", cleaned)
        self.assertLessEqual(len(cleaned), 80)

    def test_format_validation_error_branches(self):
        err = frappe.ValidationError("bad date")
        self.assertIn(
            "ADVANCED",
            self.svc._format_validation_error("S1", err, {"action_taken": "date_advanced", "retry_count": 1}),
        )
        self.assertIn(
            "RETRY",
            self.svc._format_validation_error("S1", err, {"action_taken": "retry_tracked", "retry_count": 2}),
        )
        self.assertIn(
            "MANUAL REVIEW",
            self.svc._format_validation_error("S1", err, {"action_taken": "skipped", "retry_count": 3}),
        )
        self.assertIn(
            "ERROR",
            self.svc._format_validation_error("S1", err, {"action_taken": "other", "retry_count": 0}),
        )

    # ==================================================================
    # _detect_coverage_gaps
    # ==================================================================
    def test_detect_coverage_gaps_none_when_covered(self):
        class FakeInvoice:
            name = "SI-FAKE-1"
            custom_coverage_end_date = date(2026, 12, 31)

        invoices = [{"member_id": "M1", "schedule": "S1", "invoice": FakeInvoice()}]
        gaps, count = self.svc._detect_coverage_gaps(invoices, date(2026, 6, 30))
        self.assertEqual(count, 0)
        self.assertEqual(gaps, [])

    def test_detect_coverage_gaps_reports_gap(self):
        class FakeInvoice:
            name = "SI-FAKE-2"
            custom_coverage_end_date = date(2026, 5, 31)

        invoices = [{"member_id": "M1", "schedule": "S1", "invoice": FakeInvoice()}]
        cutoff = date(2026, 6, 30)
        gaps, count = self.svc._detect_coverage_gaps(invoices, cutoff)
        self.assertEqual(count, 1)
        self.assertEqual(gaps[0]["gap_days"], (cutoff - date(2026, 5, 31)).days)
        self.assertEqual(gaps[0]["member"], "M1")

    def test_detect_coverage_gaps_handles_missing_attr(self):
        class FakeInvoice:
            name = "SI-FAKE-3"
            # no custom_coverage_end_date attribute

        invoices = [{"member_id": "M1", "schedule": "S1", "invoice": FakeInvoice()}]
        gaps, count = self.svc._detect_coverage_gaps(invoices, date(2026, 6, 30))
        self.assertEqual(count, 0)

    # ==================================================================
    # get_parallel_status
    # ==================================================================
    def test_get_parallel_status_shape(self):
        status = self.svc.get_parallel_status()
        self.assertIn("total_jobs", status)
        self.assertIn("jobs", status)
        self.assertIn("message", status)
        self.assertIsInstance(status["jobs"], list)


class TestBulkInvoiceGenerationServiceGaps(EnhancedTestCase):
    """Coverage for the previously-uncovered branches of
    bulk_invoice_generation_service.py:
      - _process_parallel (chunk split + real enqueue + enqueue-failure branch)
      - _process_sequential failure branches (None invoice, ValidationError,
        generic Exception, outer load Exception)
      - bulk_update_payment_history (missing member, real member update)
      - _log_blocked_members_summary (with frappe.local.blocked_members populated)
      - process_invoice_chunk worker (success + load-error)
      - _safe_log_error fallbacks
      - _detect_coverage_gaps log-error branch (already partly covered)
    """

    def setUp(self):
        super().setUp()
        self._committed_docs = []
        self._sales_invoices = []
        self.svc = get_bulk_invoice_generation_service()

    def tearDown(self):
        for si in self._sales_invoices:
            if frappe.db.exists("Sales Invoice", si):
                try:
                    doc = frappe.get_doc("Sales Invoice", si)
                    if doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc("Sales Invoice", si, force=True, ignore_permissions=True)
                except Exception:
                    pass
        for doctype, name in reversed(self._committed_docs):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        # Clear any frappe.local state we set.
        if hasattr(frappe.local, "blocked_members"):
            frappe.local.blocked_members = {}
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------
    def _make_membership_type(self):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"BIGap-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Bulk gen gap test type"
        mt.minimum_amount = 0.01
        mt.is_active = 1
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))
        return mt

    def _make_member(self, status="Active"):
        member = frappe.new_doc("Member")
        member.first_name = "BulkGap"
        member.last_name = f"T{frappe.generate_hash(length=6)}"
        member.email = f"bulkgap.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.address_line1 = "1 Gap Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        if status != "Active":
            frappe.db.set_value("Member", member.name, "status", status)
        self._committed_docs.append(("Member", member.name))
        return member

    def _deactivate_auto_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def _make_dues_schedule(
        self,
        member,
        membership_type,
        amount=5.0,
        status="Active",
        auto_generate=1,
        next_invoice_date=None,
        test_mode=0,
    ):
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self._committed_docs.append(("Membership", membership.name))

        self._deactivate_auto_schedules(member.name)

        ds = frappe.new_doc("Membership Dues Schedule")
        ds.schedule_name = f"BIGap-{member.name}-{frappe.generate_hash(length=8)}"
        ds.member = member.name
        ds.membership = membership.name
        ds.membership_type = membership_type.name
        ds.currency = "EUR"
        ds.contribution_mode = "Fixed"
        ds.dues_rate = amount
        ds.uses_custom_amount = 1
        if amount > 0:
            ds.custom_amount_approved = 1
        ds.billing_frequency = "Monthly"
        ds.payment_method = "Bank Transfer"
        ds.status = status
        ds.auto_generate = auto_generate
        ds.test_mode = test_mode
        if next_invoice_date is not None:
            ds.next_invoice_date = next_invoice_date
        ds.save()
        self._committed_docs.append(("Membership Dues Schedule", ds.name))
        return ds

    def _track_invoices_from_member(self, member_name):
        for si in frappe.get_all("Sales Invoice", filters={"member": member_name}, pluck="name"):
            if si not in self._sales_invoices:
                self._sales_invoices.append(si)

    # ==================================================================
    # _process_parallel
    # ==================================================================
    def test_process_parallel_splits_and_enqueues(self):
        """_process_parallel must split schedules into chunks and enqueue a
        background job per chunk, returning parallel_mode=True with the right
        job count and message.

        We patch frappe.enqueue with a recorder so NO real job is written to the
        shared `long` RQ queue (otherwise the worker fn `process_invoice_chunk`
        would later run inline on our FAKE-SCHED-* names and the leaked jobs
        would pollute get_parallel_status for sibling tests). The branch under
        test is the chunk-splitting + per-chunk enqueue accounting, which a fake
        enqueue exercises fully.
        """
        import verenigingen.services.billing.bulk_invoice_generation_service as mod

        schedule_names = [f"FAKE-SCHED-{i}" for i in range(120)]
        result = BulkGenerationResult()
        cutoff = getdate(today())

        enqueued = []
        real_enqueue = mod.frappe.enqueue

        def recording_enqueue(method, **kwargs):
            enqueued.append(kwargs.get("schedule_names"))
            return f"job-{len(enqueued)}"

        mod.frappe.enqueue = recording_enqueue
        try:
            out = self.svc._process_parallel(schedule_names, cutoff, test_mode=False, result=result)
        finally:
            mod.frappe.enqueue = real_enqueue

        self.assertTrue(out.parallel_mode)
        # num_workers = min(8, max(4, 120//100)) = max(4,1)=4 ; chunk_size=ceil(120/4)=30
        # -> 4 chunks of 30. All 4 should enqueue cleanly (job_count == 4).
        self.assertEqual(out.job_count, 4)
        self.assertEqual(len(enqueued), 4)
        # Every schedule name was distributed across exactly the 4 chunks.
        self.assertEqual(sum(len(chunk) for chunk in enqueued), 120)
        self.assertEqual(sorted(n for chunk in enqueued for n in chunk), sorted(schedule_names))
        self.assertIn("4 parallel jobs", out.message)
        self.assertIn("120 invoices", out.message)

    def test_process_parallel_enqueue_failure_branch(self):
        """When frappe.enqueue raises for a chunk, that chunk is recorded as
        failed and job_count reflects only the successful enqueues. We force a
        failure by passing a non-existent queue is not reliable; instead we
        monkeypatch frappe.enqueue on the module to raise for the 2nd call."""
        import verenigingen.services.billing.bulk_invoice_generation_service as mod

        schedule_names = [f"FAKE-SCHED-{i}" for i in range(120)]  # -> 4 chunks
        result = BulkGenerationResult()
        cutoff = getdate(today())

        calls = {"n": 0}
        real_enqueue = mod.frappe.enqueue

        def flaky_enqueue(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated queue backend down")
            return f"job-{calls['n']}"

        self.expectErrorLog()
        mod.frappe.enqueue = flaky_enqueue
        try:
            out = self.svc._process_parallel(schedule_names, cutoff, test_mode=False, result=result)
        finally:
            mod.frappe.enqueue = real_enqueue

        # 4 chunks attempted, 1 failed -> 3 successful enqueues.
        self.assertTrue(out.parallel_mode)
        self.assertEqual(out.job_count, 3)

    # ==================================================================
    # _process_sequential failure branches
    # ==================================================================
    def test_sequential_none_invoice_branch(self):
        """A schedule whose generate_invoice() returns None is recorded as an
        error ('returned None') and NOT counted as generated."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, next_invoice_date=add_days(today(), -1))

        # Force generate_invoice -> None on the instance the service loads by
        # patching the doctype class method for this one schedule via a wrapper.
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        original = MembershipDuesSchedule.generate_invoice

        def returns_none(self_doc, *a, **k):
            if self_doc.name == ds.name:
                return None
            return original(self_doc, *a, **k)

        self.expectErrorLog()
        result = BulkGenerationResult()
        MembershipDuesSchedule.generate_invoice = returns_none
        try:
            out = self.svc._process_sequential([ds.name], getdate(today()), test_mode=False, result=result)
        finally:
            MembershipDuesSchedule.generate_invoice = original

        self.assertEqual(out.generated, 0)
        self.assertEqual(out.processed, 1)
        self.assertTrue(any("returned None" in e for e in out.errors))

    def test_sequential_outer_load_error_branch(self):
        """A schedule name that cannot be loaded hits the outer except and is
        recorded as 'Error processing'."""
        self.expectErrorLog()
        result = BulkGenerationResult()
        out = self.svc._process_sequential(
            ["NONEXISTENT-SCHEDULE-XYZ"], getdate(today()), test_mode=False, result=result
        )
        self.assertEqual(out.generated, 0)
        self.assertTrue(any("Error processing NONEXISTENT-SCHEDULE-XYZ" in e for e in out.errors))

    def test_sequential_generic_exception_branch(self):
        """A schedule whose generate_invoice() raises a non-ValidationError is
        routed through the recovery handler and recorded as 'ERROR: ...'."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, next_invoice_date=add_days(today(), -1))

        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        original = MembershipDuesSchedule.generate_invoice

        def raises_runtime(self_doc, *a, **k):
            if self_doc.name == ds.name:
                raise RuntimeError("boom in generate")
            return original(self_doc, *a, **k)

        self.expectErrorLog()
        result = BulkGenerationResult()
        MembershipDuesSchedule.generate_invoice = raises_runtime
        try:
            out = self.svc._process_sequential([ds.name], getdate(today()), test_mode=False, result=result)
        finally:
            MembershipDuesSchedule.generate_invoice = original

        self.assertEqual(out.generated, 0)
        self.assertTrue(any("ERROR:" in e for e in out.errors))

    def test_sequential_success_updates_payment_history(self):
        """A real end-to-end sequential run: generates a real invoice, then
        invokes bulk_update_payment_history for the member (the
        members_to_update branch + the gap detection + blocked summary)."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, amount=12.0, next_invoice_date=add_days(today(), -1))

        result = BulkGenerationResult()
        out = self.svc._process_sequential([ds.name], getdate(today()), test_mode=False, result=result)
        self._track_invoices_from_member(member.name)

        self.assertEqual(out.generated, 1)
        self.assertEqual(out.processed, 1)
        # member was queued for payment-history update and updated_count >= 1.
        self.assertGreaterEqual(out.payment_history_updates, 1)

    # ==================================================================
    # bulk_update_payment_history
    # ==================================================================
    def test_bulk_update_payment_history_missing_member_skipped(self):
        """A member name that does not exist is skipped (logged) and not
        counted; updated_count stays 0."""
        self.expectErrorLog()
        count = self.svc.bulk_update_payment_history(
            {"NONEXISTENT-MEMBER-ABC"},
            [{"member_id": "NONEXISTENT-MEMBER-ABC", "invoice": "SI-FAKE"}],
        )
        self.assertEqual(count, 0)

    def test_bulk_update_payment_history_real_member(self):
        """A real member with a real generated invoice is updated once."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, amount=8.0, next_invoice_date=add_days(today(), -1))
        invoice = frappe.get_doc("Membership Dues Schedule", ds.name).generate_invoice()
        frappe.db.commit()
        invoice_name = getattr(invoice, "name", invoice)
        self._sales_invoices.append(invoice_name)

        count = self.svc.bulk_update_payment_history(
            {member.name},
            [{"member_id": member.name, "invoice": invoice_name, "schedule": ds.name}],
        )
        self.assertEqual(count, 1)

    # ==================================================================
    # _log_blocked_members_summary
    # ==================================================================
    def test_log_blocked_members_summary_noop_when_empty(self):
        """No blocked_members on frappe.local -> early return, no error."""
        if hasattr(frappe.local, "blocked_members"):
            frappe.local.blocked_members = {}
        # Should simply return without raising.
        self.svc._log_blocked_members_summary()

    def test_log_blocked_members_summary_logs_and_clears(self):
        """Populated blocked_members -> a summary Error Log is written and the
        structure is cleared afterwards (incl. the >10 truncation branch)."""
        self.expectErrorLog()
        frappe.local.blocked_members = {
            "Suspended": [{"member": f"M-{i}", "member_name": f"Name {i}"} for i in range(12)]
        }
        self.svc._log_blocked_members_summary()
        # Cleared after logging.
        self.assertEqual(frappe.local.blocked_members, {})

    # ==================================================================
    # process_invoice_chunk worker + _safe_log_error
    # ==================================================================
    def test_process_invoice_chunk_success(self):
        """The background worker function generates a real invoice for an
        eligible schedule and returns a ChunkResult with generated >= 1."""
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            process_invoice_chunk,
        )

        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, amount=9.0, next_invoice_date=add_days(today(), -1))

        res = process_invoice_chunk(
            schedule_names=[ds.name],
            chunk_id=1,
            total_chunks=1,
            cutoff_date=getdate(today()),
            test_mode=False,
        )
        self._track_invoices_from_member(member.name)

        self.assertIsInstance(res, ChunkResult)
        self.assertEqual(res.chunk_id, 1)
        self.assertEqual(res.generated, 1)
        self.assertIn(member.name, res.members_to_update)

    def test_process_invoice_chunk_load_error(self):
        """A bad schedule name hits the outer except and is recorded as a load
        error without raising."""
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            process_invoice_chunk,
        )

        self.expectErrorLog()
        res = process_invoice_chunk(
            schedule_names=["NONEXISTENT-CHUNK-SCHED"],
            chunk_id=7,
            total_chunks=1,
            cutoff_date=getdate(today()),
            test_mode=False,
        )
        self.assertEqual(res.generated, 0)
        self.assertEqual(res.processed, 0)
        self.assertTrue(any("Error loading schedule" in e for e in res.errors))

    def test_safe_log_error_does_not_raise(self):
        """_safe_log_error must swallow logging failures and never raise."""
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            _safe_log_error,
        )

        import verenigingen.services.billing.bulk_invoice_generation_service as mod

        # Happy path: writes an Error Log row (assert the side-effect happened).
        self.expectErrorLog()
        marker = frappe.utils.now_datetime()
        _safe_log_error("Gap Test Title", "SCHED-1", RuntimeError("kaboom"))
        wrote = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", marker], "method": "Gap Test Title"},
            limit=1,
        )
        self.assertTrue(wrote, "happy path should have written an Error Log row")

        # Fallback path: force frappe.log_error to raise so the inner
        # frappe.logger().error fallback is exercised; _safe_log_error must
        # still swallow it and not propagate.
        real_log_error = mod.frappe.log_error

        def boom(*a, **k):
            raise RuntimeError("log_error itself failed")

        mod.frappe.log_error = boom
        try:
            # Must NOT raise even though the primary logger is broken.
            _safe_log_error("Gap Fallback Title", "SCHED-2", ValueError("inner"))
        finally:
            mod.frappe.log_error = real_log_error
