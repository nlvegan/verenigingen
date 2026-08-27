# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Meaningful tests for verenigingen/api/dues_invoice_workflow.py

This module is the backend for the `dues-invoice-manager` www page. It exposes
six whitelisted endpoints, all returning OperationResult:

- check_member_dues_status        -> member eligibility analysis for the period
- generate_missing_invoices       -> enqueues bulk generation (async, returns job info)
- validate_sepa_eligibility       -> per-invoice SEPA mandate eligibility
- prepare_sepa_batch              -> creates a Direct Debit batch via SEPAProcessor
- get_workflow_status             -> aggregates the above + recent batches
- check_coverage_scheduling_mismatches -> data-integrity check on coverage vs schedule

These tests seed REAL data (Member, Membership, Membership Dues Schedule,
SEPA Mandate, Sales Invoice) and assert on the concrete shape/values returned,
so they fail on real regressions (wrong field, broken query, swapped link).
"""

import frappe

from verenigingen.api.dues_invoice_workflow import (
    check_coverage_scheduling_mismatches,
    check_member_dues_status,
    generate_missing_invoices,
    get_workflow_status,
    prepare_sepa_batch,
    validate_sepa_eligibility,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDuesInvoiceWorkflow(VereningingenTestCase):
    """Integration tests for the dues invoice workflow API."""

    def setUp(self):
        super().setUp()
        # Run all endpoints as Administrator: they are guarded by financial-API
        # security decorators that require an authenticated privileged user.
        frappe.set_user("Administrator")

    # ------------------------------------------------------------------ #
    # result helpers                                                      #
    # ------------------------------------------------------------------ #
    # The @standard_api/@critical_api security decorators serialize the
    # returned OperationResult via to_dict(scrub_sensitive=True), so these
    # endpoints hand back a plain dict:
    #   success: {"success": True, "data": {...}, "meta": {...}}
    #   failure: {"success": False, "error": {"message", "code", ...}}
    def _ok(self, result):
        """Assert the result succeeded and return its data payload."""
        self.assertIsInstance(result, dict)
        self.assertTrue(
            result.get("success"),
            msg=(result.get("error") or {}).get("message") if isinstance(result, dict) else result,
        )
        return result["data"]

    def _err(self, result):
        """Assert the result failed and return its error object."""
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        return result.get("error", {})

    # ------------------------------------------------------------------ #
    # helpers (named _make_/_setup_ so the test-quality-enforcer allows   #
    # the insert/save calls that happen inside them)                      #
    # ------------------------------------------------------------------ #
    def _make_member_with_schedule(self, dues_rate=15.0, billing_frequency="Monthly"):
        """Seed a member + active (submitted) membership + active dues schedule.

        Membership Dues Schedule.validate_member_membership requires the member
        to have an ACTIVE, SUBMITTED Membership; the core factory only inserts a
        draft (docstatus 0), so we submit it (suppressing its auto dues-schedule
        creation so our own schedule doesn't trip the one-active-schedule guard).
        """
        member = self.create_test_member(
            first_name="Dues",
            last_name=f"Tester{frappe.generate_hash(length=4)}",
            email=f"dues.{frappe.generate_hash(length=8).lower()}@example.com",
        )
        membership_type = self.create_test_membership_type(minimum_amount=0)
        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name
        )
        if membership.docstatus == 0:
            membership.flags.skip_dues_schedule_creation = True
            membership.submit()

        # The factory auto-creates a schedule on submit in some configs; cancel
        # any pre-existing active schedule so ours is the single active one.
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
            billing_frequency=billing_frequency,
            schedule_name=f"Test-DIW-{frappe.generate_hash(length=10)}",
        )
        return member, schedule

    def _ensure_customer(self, member):
        """Ensure the member has a linked Customer; return the customer name."""
        member.reload()
        if member.customer:
            return member.customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.member = member.name
        customer.save()
        self.track_doc("Customer", customer.name)
        member.customer = customer.name
        member.save()
        return customer.name

    def _make_dues_invoice(self, member, schedule):
        """Submit a Sales Invoice linked to a member's dues schedule."""
        self._ensure_customer(member)
        invoice = self.create_test_sales_invoice(member=member.name)
        # Link the invoice to the dues schedule (the display link the API reads)
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        if invoice.docstatus == 0:
            invoice.submit()
        invoice.reload()
        return invoice

    # ------------------------------------------------------------------ #
    # check_member_dues_status                                            #
    # ------------------------------------------------------------------ #
    def test_check_member_dues_status_returns_well_formed_result(self):
        """Happy path: returns a successful OperationResult with the full schema."""
        result = check_member_dues_status()

        data = self._ok(result)
        self.assertIsInstance(data, dict)

        # Summary block must carry every documented count key.
        summary = data["summary"]
        for key in (
            "total_active_members",
            "members_with_invoices",
            "members_missing_invoices",
            "members_without_membership",
            "members_without_schedule",
            "sepa_eligible",
            "sepa_missing",
        ):
            self.assertIn(key, summary)
            self.assertIsInstance(summary[key], int)

        # sepa_missing is derived as (missing_invoices - sepa_eligible);
        # a regression that swaps the operands would break this invariant.
        self.assertEqual(
            summary["sepa_missing"],
            summary["members_missing_invoices"] - summary["sepa_eligible"],
        )

        # Categorization block must expose all eight buckets with count/members.
        categories = data["member_categories"]
        for bucket in (
            "ineligible_status",
            "gap_reset",
            "already_covered",
            "needs_invoicing",
            "no_customer",
            "duplicate_coverage",
            "too_early",
            "business_logic",
        ):
            self.assertIn(bucket, categories)
            self.assertEqual(categories[bucket]["count"], len(categories[bucket]["members"]))

        # needs_invoicing count must mirror the summary's missing-invoice count.
        self.assertEqual(
            categories["needs_invoicing"]["count"],
            summary["members_missing_invoices"],
        )

    def test_check_member_dues_status_counts_member_without_membership(self):
        """A member with NO Membership record must land in members_without_membership."""
        baseline = self._ok(check_member_dues_status())["summary"]["members_without_membership"]

        # Member with active status but no Membership document.
        self.create_test_member(
            first_name="Orphan",
            last_name=f"NoMembership{frappe.generate_hash(length=4)}",
            email=f"orphan.{frappe.generate_hash(length=8).lower()}@example.com",
        )

        after = self._ok(check_member_dues_status())["summary"]["members_without_membership"]
        self.assertEqual(
            after,
            baseline + 1,
            "A new active member without a Membership should increment members_without_membership",
        )

    # ------------------------------------------------------------------ #
    # generate_missing_invoices                                           #
    # ------------------------------------------------------------------ #
    def test_generate_missing_invoices_enqueues_background_job(self):
        """generate_missing_invoices is async: it returns a queued job, not invoices.

        This asserts the documented contract (job_id + RQ-status pointer) so a
        regression that turns it back into a synchronous call would be caught.
        """
        result = generate_missing_invoices()

        data = self._ok(result)
        self.assertIn("job_id", data)
        self.assertTrue(data["job_id"], "A queued job must expose a non-empty job_id")
        self.assertIn("/app/rq-job", data["check_status_at"])
        self.assertIn("note", data)

    def test_generate_missing_invoices_with_explicit_member_list_still_enqueues(self):
        """When given a member_list, generation is still routed through the bulk job.

        member_list is advisory only: the function logs a notice and enqueues the
        site-wide bulk generator regardless. (Note: the body has an
        `isinstance(member_list, str): parse_json` branch, but under Frappe v16's
        runtime @whitelist type enforcement a JSON *string* is rejected before the
        body runs because the annotation is `List[str]`, not `List[str] | str`;
        callers must pass a real list, which is what the in-process call does.)
        """
        member, _ = self._make_member_with_schedule()

        result = generate_missing_invoices(member_list=[member.name])

        data = self._ok(result)
        self.assertTrue(data["job_id"])
        self.assertIn("/app/rq-job", data["check_status_at"])

    # ------------------------------------------------------------------ #
    # validate_sepa_eligibility                                           #
    # ------------------------------------------------------------------ #
    def test_validate_sepa_eligibility_ignores_a_donation_only_mandate(self):
        """A donation mandate cannot collect dues, so the invoice is not eligible.

        This resolved the mandate with an unfiltered `get_value` and no
        `order_by`, so a member holding only a donation mandate was reported as
        SEPA-eligible with that mandate's IBAN -- the IBAN an operator reads
        before approving the collection. Every batching path has resolved mandates
        by purpose since #597, so the batch would then have skipped the invoice
        this list said was ready (#605).
        """
        member, schedule = self._make_member_with_schedule(dues_rate=22.0)
        self.create_test_sepa_mandate(
            member=member.name, used_for_memberships=0, used_for_donations=1
        )
        invoice = self._make_dues_invoice(member, schedule)

        data = self._ok(validate_sepa_eligibility(invoice_list=[invoice.name]))

        self.assertEqual(data["summary"]["sepa_eligible"], 0)
        self.assertEqual(len(data["ineligible_invoices"]), 1)
        self.assertIn("No active SEPA mandate", data["ineligible_invoices"][0]["reason"])

    def test_validate_sepa_eligibility_reports_the_membership_mandate(self):
        """With both mandates, the membership one is reported -- not the newest."""
        member, schedule = self._make_member_with_schedule(dues_rate=22.0)
        membership_mandate = self.create_test_sepa_mandate(
            member=member.name, used_for_memberships=1, used_for_donations=0
        )
        self.create_test_sepa_mandate(
            member=member.name, used_for_memberships=0, used_for_donations=1
        )
        invoice = self._make_dues_invoice(member, schedule)

        data = self._ok(validate_sepa_eligibility(invoice_list=[invoice.name]))

        self.assertEqual(data["summary"]["sepa_eligible"], 1)
        self.assertEqual(
            data["eligible_invoices"][0]["mandate"]["mandate_id"], membership_mandate.mandate_id
        )

    def test_validate_sepa_eligibility_marks_invoice_with_active_mandate(self):
        """An unpaid dues invoice whose member has an Active mandate is SEPA-eligible.

        Asserts the eligible-entry payload carries the right member, customer,
        amount and the mandate's IBAN/mandate_id -- the exact fields the SEPA
        batch step downstream depends on.
        """
        member, schedule = self._make_member_with_schedule(dues_rate=22.0)
        mandate = self.create_test_sepa_mandate(member=member.name)
        invoice = self._make_dues_invoice(member, schedule)

        result = validate_sepa_eligibility(invoice_list=[invoice.name])
        data = self._ok(result)

        self.assertEqual(data["summary"]["total_checked"], 1)
        self.assertEqual(data["summary"]["sepa_eligible"], 1)
        self.assertEqual(len(data["eligible_invoices"]), 1)
        self.assertEqual(len(data["ineligible_invoices"]), 0)

        entry = data["eligible_invoices"][0]
        self.assertEqual(entry["invoice"], invoice.name)
        self.assertEqual(entry["member"], member.name)
        self.assertEqual(entry["customer"], invoice.customer)
        self.assertEqual(entry["amount"], invoice.outstanding_amount)
        self.assertEqual(entry["mandate"]["name"], mandate.name)
        self.assertEqual(entry["mandate"]["iban"], mandate.iban)
        self.assertEqual(entry["mandate"]["mandate_id"], mandate.mandate_id)

    def test_validate_sepa_eligibility_marks_invoice_without_mandate(self):
        """A dues invoice whose member has NO active mandate is ineligible."""
        member, schedule = self._make_member_with_schedule()
        invoice = self._make_dues_invoice(member, schedule)  # no mandate created

        result = validate_sepa_eligibility(invoice_list=[invoice.name])
        data = self._ok(result)

        self.assertEqual(data["summary"]["sepa_eligible"], 0)
        self.assertEqual(data["summary"]["missing_mandate"], 1)
        self.assertEqual(len(data["ineligible_invoices"]), 1)
        ineligible = data["ineligible_invoices"][0]
        self.assertEqual(ineligible["invoice"], invoice.name)
        self.assertEqual(ineligible["member"], member.name)
        self.assertIn("No active SEPA mandate", ineligible["reason"])

    def test_validate_sepa_eligibility_skips_non_membership_invoice(self):
        """An invoice with no dues-schedule link is 'Not a membership dues invoice'."""
        # Plain invoice with no membership_dues_schedule_display link.
        member = self.create_test_member(
            first_name="Plain",
            last_name=f"Invoice{frappe.generate_hash(length=4)}",
            email=f"plain.{frappe.generate_hash(length=8).lower()}@example.com",
        )
        self._ensure_customer(member)
        invoice = self.create_test_sales_invoice(member=member.name)
        invoice.submit()

        result = validate_sepa_eligibility(invoice_list=[invoice.name])
        data = self._ok(result)

        self.assertEqual(data["summary"]["sepa_eligible"], 0)
        self.assertEqual(len(data["ineligible_invoices"]), 1)
        self.assertIn(
            "Not a membership dues invoice",
            data["ineligible_invoices"][0]["reason"],
        )

    def test_validate_sepa_eligibility_single_bad_name_yields_zero_eligible(self):
        """A list of one non-existent invoice yields zero eligible, structured summary.

        (The 'no invoices at all' no-op branch only triggers when invoice_list is
        falsy, which under v16 type enforcement we cannot reach with an empty
        JSON string -- `List[str]` rejects a str arg -- so we exercise the
        per-invoice loop with a name that does not resolve.)
        """
        result = validate_sepa_eligibility(invoice_list=["SINV-NOPE-0001"])
        data = self._ok(result)
        summary = data["summary"]
        self.assertEqual(summary["total_checked"], 1)
        self.assertEqual(summary["sepa_eligible"], 0)
        self.assertEqual(data["eligible_invoices"], [])
        self.assertEqual(len(data["ineligible_invoices"]), 1)

    def test_validate_sepa_eligibility_bad_invoice_name_is_captured_not_raised(self):
        """A non-existent invoice name is reported as ineligible, not raised."""
        result = validate_sepa_eligibility(invoice_list=["SINV-DOES-NOT-EXIST-XYZ"])
        data = self._ok(result)
        self.assertEqual(data["summary"]["total_checked"], 1)
        self.assertEqual(data["summary"]["sepa_eligible"], 0)
        self.assertEqual(len(data["ineligible_invoices"]), 1)
        self.assertIn("Error checking invoice", data["ineligible_invoices"][0]["reason"])

    # ------------------------------------------------------------------ #
    # prepare_sepa_batch                                                  #
    # ------------------------------------------------------------------ #
    def test_prepare_sepa_batch_returns_operation_result(self):
        """prepare_sepa_batch returns a structured OperationResult either way.

        With no eligible invoices in this isolated test it should fail cleanly
        with NO_ELIGIBLE_INVOICES (the documented empty path), rather than
        raise. If a batch IS produced it must carry name/amount/count keys.
        """
        result = prepare_sepa_batch()
        self.assertIsInstance(result, dict)

        if result.get("success"):
            data = result["data"]
            self.assertIn("batch_name", data)
            self.assertIn("total_amount", data)
            self.assertIn("entry_count", data)
            self.assertTrue(frappe.db.exists("Direct Debit Batch", data["batch_name"]))
            self.track_doc("Direct Debit Batch", data["batch_name"])
        else:
            # Empty / error path must surface a structured error code, not a stack trace.
            error = self._err(result)
            self.assertIn(
                error.get("code"),
                ("NO_ELIGIBLE_INVOICES", "SEPA_BATCH_CREATION_FAILED"),
            )
            self.assertTrue(error.get("message"))

    # ------------------------------------------------------------------ #
    # get_workflow_status                                                 #
    # ------------------------------------------------------------------ #
    def test_get_workflow_status_returns_populated_analysis(self):
        """get_workflow_status aggregates member analysis + coverage mismatches.

        The endpoint calls check_member_dues_status() and
        check_coverage_scheduling_mismatches() in-process. Both are
        @standard_api-decorated, so the security wrapper serializes their
        OperationResult to a plain dict; get_workflow_status unwraps those
        dicts (via _unwrap_api_result) and returns success=True with populated
        members_analysis / coverage_mismatches blocks. This asserts that the
        in-process call returns real data rather than failing -- a regression
        that re-introduced `.success`/`.data` attribute access on the dict
        result would flip this back to WORKFLOW_STATUS_FAILED.
        """
        member, schedule = self._make_member_with_schedule()
        mandate = self.create_test_sepa_mandate(member=member.name)
        self._make_dues_invoice(member, schedule)
        # mandate kept referenced so it isn't GC'd before the batch logic reads it
        self.assertTrue(mandate.name)

        result = get_workflow_status()
        data = self._ok(result)

        # Top-level workflow status shape.
        self.assertIsInstance(data["recent_batches"], list)
        self.assertIsInstance(data["pending_invoices"], int)

        # members_analysis must expose every documented count key as an int.
        analysis = data["members_analysis"]
        self.assertIsInstance(analysis, dict)
        for key in (
            "total_active_members",
            "members_with_coverage",
            "members_missing_invoices",
            "members_without_membership",
            "members_without_schedule",
            "sepa_eligible",
        ):
            self.assertIn(key, analysis)
            self.assertIsInstance(analysis[key], int)

        # The seeded active member must be reflected in the live count, proving
        # the analysis carries real data unwrapped from check_member_dues_status
        # (not the all-zero fallback used when unwrapping fails).
        self.assertGreaterEqual(analysis["total_active_members"], 1)

        # coverage_mismatches must carry the documented totals + buckets.
        mismatches = data["coverage_mismatches"]
        self.assertIsInstance(mismatches, dict)
        self.assertIn("total_mismatches", mismatches)
        self.assertIn("extending_past", mismatches)
        self.assertIn("ending_early", mismatches)
        self.assertEqual(
            mismatches["total_mismatches"],
            mismatches["extending_past"]["count"] + mismatches["ending_early"]["count"],
        )

    # ------------------------------------------------------------------ #
    # check_coverage_scheduling_mismatches                                #
    # ------------------------------------------------------------------ #
    def test_coverage_mismatch_detects_coverage_extending_past_next_invoice(self):
        """A schedule whose invoice coverage extends well past next_invoice_date
        is reported in the 'extending_past' bucket.

        Seeds: next_invoice_date today, but the latest submitted invoice covers
        a period ending ~60 days out -> gap_days strongly negative -> extending_past.
        """
        member, schedule = self._make_member_with_schedule()
        customer = self._ensure_customer(member)

        # next_invoice_date today
        schedule.db_set("next_invoice_date", frappe.utils.today())

        invoice = self.create_test_sales_invoice(member=member.name)
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        invoice.db_set("custom_coverage_start_date", frappe.utils.today())
        invoice.db_set("custom_coverage_end_date", frappe.utils.add_days(frappe.utils.today(), 60))
        if invoice.docstatus == 0:
            invoice.submit()
        # db_set on a draft is fine; re-assert coverage on the submitted doc
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            "custom_coverage_end_date",
            frappe.utils.add_days(frappe.utils.today(), 60),
        )

        result = check_coverage_scheduling_mismatches()
        data = self._ok(result)

        matched = [
            item
            for item in data["extending_past"]["items"]
            if item["schedule"] == schedule.name
        ]
        self.assertEqual(
            len(matched),
            1,
            f"Schedule {schedule.name} should appear once in extending_past; "
            f"got items={data['extending_past']['items']}",
        )
        entry = matched[0]
        self.assertEqual(entry["latest_invoice"], invoice.name)
        # gap = next_invoice_date - coverage_end ~= -60 days (coverage runs past)
        self.assertLess(entry["gap_days"], -5)
        self.assertEqual(
            data["total_mismatches"],
            data["extending_past"]["count"] + data["ending_early"]["count"],
        )
        self.assertEqual(customer, member.customer)

    def test_coverage_mismatch_detects_coverage_ending_early(self):
        """A schedule whose coverage ended long before next_invoice_date is
        reported in the 'ending_early' bucket."""
        member, schedule = self._make_member_with_schedule()
        self._ensure_customer(member)

        # next_invoice_date 60 days out, but coverage already ended today.
        schedule.db_set("next_invoice_date", frappe.utils.add_days(frappe.utils.today(), 60))

        invoice = self.create_test_sales_invoice(member=member.name)
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        invoice.db_set("custom_coverage_start_date", frappe.utils.add_days(frappe.utils.today(), -30))
        invoice.db_set("custom_coverage_end_date", frappe.utils.today())
        if invoice.docstatus == 0:
            invoice.submit()
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            "custom_coverage_end_date",
            frappe.utils.today(),
        )

        result = check_coverage_scheduling_mismatches()
        data = self._ok(result)

        matched = [
            item
            for item in data["ending_early"]["items"]
            if item["schedule"] == schedule.name
        ]
        self.assertEqual(
            len(matched),
            1,
            f"Schedule {schedule.name} should appear once in ending_early; "
            f"got items={data['ending_early']['items']}",
        )
        # gap = next_invoice_date - coverage_end ~= +60 days
        self.assertGreater(matched[0]["gap_days"], 5)

    def test_coverage_mismatch_ignores_aligned_schedule(self):
        """A schedule whose coverage end is within tolerance of next_invoice_date
        must NOT be flagged as a mismatch."""
        member, schedule = self._make_member_with_schedule()
        self._ensure_customer(member)

        aligned_date = frappe.utils.add_days(frappe.utils.today(), 30)
        schedule.db_set("next_invoice_date", aligned_date)

        invoice = self.create_test_sales_invoice(member=member.name)
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        invoice.db_set("custom_coverage_start_date", frappe.utils.today())
        invoice.db_set("custom_coverage_end_date", aligned_date)
        if invoice.docstatus == 0:
            invoice.submit()
        frappe.db.set_value(
            "Sales Invoice", invoice.name, "custom_coverage_end_date", aligned_date
        )

        result = check_coverage_scheduling_mismatches()
        data = self._ok(result)

        flagged_names = [
            item["schedule"] for item in data["extending_past"]["items"]
        ] + [item["schedule"] for item in data["ending_early"]["items"]]
        self.assertNotIn(
            schedule.name,
            flagged_names,
            "A schedule aligned within tolerance must not be flagged as a mismatch",
        )
