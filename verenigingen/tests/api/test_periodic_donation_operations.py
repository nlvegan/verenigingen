# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Meaningful test suite for verenigingen/api/periodic_donation_operations.py

This module covers the ANBI periodic-donation-agreement API:
  - create_periodic_agreement   (high_security_api, FINANCIAL)
  - link_donation_to_agreement  (critical_api, FINANCIAL)  -- no production callers,
                                 but whitelisted/reachable, so still exercised here.
  - send_renewal_reminders      (critical_api, FINANCIAL)
  - generate_tax_receipts       (critical_api, FINANCIAL)
  - export_agreements           (standard_api, REPORTING)

Each function gets a happy path asserting the real returned data, plus error/edge
cases. The OperationResult contract (.success / .data / .errors / .message) is
asserted explicitly. ANBI-specific business rules (5-year minimum, end-date
calculation, payment-amount split, ANBI vs pledge classification) are asserted on
the actually-persisted agreement records, since the API delegates to the
controller for those calculations.
"""

import json

import frappe
from frappe.utils import add_days, add_years, flt, today

from verenigingen.api.periodic_donation_operations import (
    create_periodic_agreement,
    export_agreements,
    generate_tax_receipts,
    link_donation_to_agreement,
    render_tax_receipt_html,
    send_renewal_reminders,
)
from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.utils.base import VereningingenTestCase


class TestPeriodicDonationOperations(VereningingenTestCase):
    """The @critical_api / @high_security_api / @standard_api decorators
    serialize the returned OperationResult into the *nested* dict schema, so
    callers see a plain dict, not an OperationResult object:

        success: {"success": True,  "data": {...}, "meta": {"message": "..."}}
        failure: {"success": False, "error": {"message": "...", "errors": [...]}}

    The accessor helpers below normalize that contract for the assertions.
    """

    # ------------------------------------------------------------------ #
    # OperationResult-dict accessors
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ok(result):
        return result["success"] is True

    @staticmethod
    def _data(result):
        return result.get("data") or {}

    @staticmethod
    def _errors(result):
        err = result.get("error") or {}
        return err.get("errors") or ([err["message"]] if err.get("message") else [])

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _make_donor(self, **kwargs):
        """Persist a donor via the base-class factory (tracked for cleanup).

        When the donor gives ANBI consent (anbi_consent=1) we also attach a
        valid (eleven-proof) BSN, because the ANBI validation service requires
        Individual donors to carry a tax identifier for ANBI-eligible
        agreements. Without consent we leave BSN unset to exercise the
        non-ANBI / warning paths.
        """
        if kwargs.get("anbi_consent") and "bsn_citizen_service_number" not in kwargs:
            kwargs["bsn_citizen_service_number"] = generate_valid_bsn()
        return self.create_test_donor(**kwargs)

    def _make_paid_donation(self, donor_name, amount=100.0, **kwargs):
        """Persist a paid donation linked to a donor (tracked for cleanup)."""
        kwargs.setdefault("paid", 1)
        return self.create_test_donation(donor=donor_name, amount=amount, **kwargs)

    # ================================================================== #
    # create_periodic_agreement
    # ================================================================== #
    def test_create_agreement_happy_path_returns_real_agreement(self):
        donor = self._make_donor(anbi_consent=1)

        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=1200,
            payment_frequency="Monthly",
            payment_method="Bank Transfer",
            agreement_type="Private Written",
        )

        self.assertTrue(self._ok(result), f"creation failed: {self._errors(result)}")
        agreement_name = self._data(result)["agreement"]
        self.assertTrue(agreement_name)
        self.track_doc("Periodic Donation Agreement", agreement_name)

        agreement = frappe.get_doc("Periodic Donation Agreement", agreement_name)
        # Returned agreement_number must match what was persisted.
        self.assertEqual(self._data(result)["agreement_number"], agreement.agreement_number)
        self.assertTrue(agreement.agreement_number.startswith("PDA-"))

        # Real field values persisted by the API.
        self.assertEqual(agreement.donor, donor.name)
        self.assertEqual(flt(agreement.annual_amount), 1200.0)
        self.assertEqual(agreement.payment_frequency, "Monthly")
        self.assertEqual(agreement.payment_method, "Bank Transfer")
        self.assertEqual(agreement.agreement_type, "Private Written")
        # The API explicitly sets status="Draft".
        self.assertEqual(agreement.status, "Draft")
        # start_date defaulted to today().
        self.assertEqual(str(agreement.start_date), today())

    def test_create_agreement_computes_monthly_payment_amount(self):
        donor = self._make_donor(anbi_consent=1)
        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=1200,
            payment_frequency="Monthly",
            payment_method="Bank Transfer",
        )
        self.assertTrue(self._ok(result), self._errors(result))
        self.track_doc("Periodic Donation Agreement", self._data(result)["agreement"])

        agreement = frappe.get_doc("Periodic Donation Agreement", self._data(result)["agreement"])
        # 1200 / 12 == 100 monthly.
        self.assertEqual(flt(agreement.payment_amount), 100.0)

    def test_create_agreement_computes_quarterly_payment_amount(self):
        donor = self._make_donor(anbi_consent=1)
        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=1200,
            payment_frequency="Quarterly",
            payment_method="Bank Transfer",
        )
        self.assertTrue(self._ok(result), self._errors(result))
        self.track_doc("Periodic Donation Agreement", self._data(result)["agreement"])

        agreement = frappe.get_doc("Periodic Donation Agreement", self._data(result)["agreement"])
        # 1200 / 4 == 300 quarterly.
        self.assertEqual(flt(agreement.payment_amount), 300.0)

    def test_create_agreement_computes_anbi_5year_end_date(self):
        donor = self._make_donor(anbi_consent=1)
        start = today()
        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=1200,
            payment_frequency="Annually",
            payment_method="Bank Transfer",
            start_date=start,
        )
        self.assertTrue(self._ok(result), self._errors(result))
        self.track_doc("Periodic Donation Agreement", self._data(result)["agreement"])

        agreement = frappe.get_doc("Periodic Donation Agreement", self._data(result)["agreement"])
        # Default duration for an ANBI-eligible agreement is the 5-year minimum,
        # so end_date should be start + 5 years.
        self.assertEqual(str(agreement.end_date), str(add_years(start, 5)))
        # An ANBI-eligible 5-year agreement is classified as an ANBI periodic
        # donation agreement (Dutch tax compliance rule).
        self.assertEqual(agreement.anbi_eligible, 1)
        self.assertEqual(agreement.commitment_type, "ANBI Periodic Donation Agreement")

    def test_create_agreement_without_anbi_consent_is_rejected_for_anbi_default(self):
        """An ANBI-eligible agreement (the default) requires donor ANBI consent.

        The API only msgprint-warns about missing consent, but the controller's
        validate()->validate_anbi_eligibility() enforces it as a hard, fail-closed
        rule (consent is mandatory before reporting to the Belastingdienst). So a
        no-consent donor with the default ANBI-eligible agreement is rejected.
        """
        donor = self._make_donor(anbi_consent=0)
        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=600,
            payment_frequency="Monthly",
            payment_method="Bank Transfer",
        )
        self.assertFalse(self._ok(result))
        joined = " ".join(self._errors(result))
        self.assertIn("ANBI consent", joined)
        # Nothing should have been persisted.
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": donor.name}))

    def test_create_agreement_invalid_amount_fails_gracefully(self):
        """Zero annual amount violates validate_annual_amount; API returns failure."""
        donor = self._make_donor(anbi_consent=1)
        result = create_periodic_agreement(
            donor=donor.name,
            annual_amount=0,
            payment_frequency="Monthly",
            payment_method="Bank Transfer",
        )
        self.assertFalse(self._ok(result))
        self.assertTrue(self._errors(result))
        # No agreement should have been persisted for this donor.
        self.assertFalse(
            frappe.db.exists("Periodic Donation Agreement", {"donor": donor.name}),
            "A failed creation must not leave an agreement behind",
        )

    def test_create_agreement_missing_donor_fails_gracefully(self):
        result = create_periodic_agreement(
            donor="Nonexistent-Donor-XYZ",
            annual_amount=1200,
            payment_frequency="Monthly",
            payment_method="Bank Transfer",
        )
        self.assertFalse(self._ok(result))
        self.assertTrue(self._errors(result))

    # ================================================================== #
    # link_donation_to_agreement
    #   NOTE: this whitelisted API has NO production callers (verified via
    #   grep). It is reachable as a whitelisted endpoint, so it is still
    #   tested here.
    # ================================================================== #
    def test_link_donation_happy_path_links_both_sides(self):
        donor = self._make_donor(anbi_consent=1)
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")
        donation = self._make_paid_donation(donor.name, amount=150.0)

        result = link_donation_to_agreement(donation=donation.name, agreement=agreement.name)
        self.assertTrue(self._ok(result), f"link failed: {self._errors(result)}")

        # Donation side: link persisted on the donation record.
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "periodic_donation_agreement"),
            agreement.name,
        )

        # Agreement side: donation appears in the agreement's child table with the
        # correct amount and Paid status (donation.paid == 1).
        agreement.reload()
        linked = [d for d in agreement.donations if d.donation == donation.name]
        self.assertEqual(len(linked), 1, "donation should appear exactly once in agreement table")
        self.assertEqual(flt(linked[0].amount), 150.0)
        self.assertEqual(linked[0].status, "Paid")

    def test_link_donation_donor_mismatch_rejected(self):
        donor_a = self._make_donor(anbi_consent=1)
        donor_b = self._make_donor(anbi_consent=1)
        agreement = self.create_anbi_compliant_agreement(donor=donor_a.name, status="Active")
        # Donation belongs to a DIFFERENT donor.
        donation = self._make_paid_donation(donor_b.name, amount=100.0)

        result = link_donation_to_agreement(donation=donation.name, agreement=agreement.name)
        self.assertFalse(self._ok(result))
        self.assertTrue(self._errors(result))
        # No cross-donor link must be persisted.
        self.assertFalse(frappe.db.get_value("Donation", donation.name, "periodic_donation_agreement"))

    def test_link_donation_already_linked_rejected(self):
        donor = self._make_donor(anbi_consent=1)
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")
        donation = self._make_paid_donation(donor.name, amount=100.0)

        first = link_donation_to_agreement(donation=donation.name, agreement=agreement.name)
        self.assertTrue(self._ok(first), self._errors(first))

        # Re-linking the same donation must be rejected.
        second = link_donation_to_agreement(donation=donation.name, agreement=agreement.name)
        self.assertFalse(self._ok(second))
        self.assertTrue(self._errors(second))

    # ================================================================== #
    # send_renewal_reminders
    #
    # An expiring Active agreement whose donor has a donor_email must be
    # reminded: the per-agreement body sends the email and then records a
    # "Renewal reminder sent" audit comment via
    # ``frappe.get_doc(...).add_comment("Comment", ...)``. So such an agreement
    # bumps ``sent_count`` and gains a reminder comment, while far-future
    # agreements (outside the window) are never touched.
    # ================================================================== #
    def test_send_renewal_reminders_query_selects_only_expiring_active_agreements(self):
        # Expiring soon (end_date within the window) and Active.
        donor_soon = self._make_donor(anbi_consent=1)
        expiring = self.create_anbi_compliant_agreement(donor=donor_soon.name, status="Active")
        near_end = add_days(today(), 30)
        frappe.db.set_value("Periodic Donation Agreement", expiring.name, "end_date", near_end)
        self.assertTrue(frappe.db.get_value("Donor", donor_soon.name, "donor_email"))

        # Far-future end date -> outside a 90-day window.
        donor_far = self._make_donor(anbi_consent=1)
        far = self.create_anbi_compliant_agreement(donor=donor_far.name, status="Active")
        frappe.db.set_value("Periodic Donation Agreement", far.name, "end_date", add_days(today(), 400))

        result = send_renewal_reminders(days_before_expiry=90)
        self.assertTrue(self._ok(result), self._errors(result))

        # The expiring Active agreement is reminded, so sent_count is at least 1.
        self.assertGreaterEqual(
            self._data(result)["sent_count"],
            1,
            "An expiring Active agreement with a donor email should be reminded.",
        )

        # And a "Renewal reminder sent" audit comment is recorded on it.
        expiring_comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Periodic Donation Agreement",
                "reference_name": expiring.name,
            },
            fields=["content"],
        )
        self.assertTrue(
            any("Renewal reminder sent" in (c.content or "") for c in expiring_comments),
            "A reminder comment must be recorded on the expiring agreement.",
        )

        # The far-future agreement must never be touched (outside the window).
        far_comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Periodic Donation Agreement",
                "reference_name": far.name,
            },
            fields=["content"],
        )
        self.assertFalse(
            any("Renewal reminder sent" in (c.content or "") for c in far_comments),
            "far-future agreement must not be reminded within a 90-day window",
        )

    def test_send_renewal_reminders_skips_draft_agreements(self):
        donor = self._make_donor(anbi_consent=1)
        # Draft (not Active) agreement, even though expiring.
        draft = self.create_anbi_compliant_agreement(donor=donor.name, status="Draft")
        frappe.db.set_value("Periodic Donation Agreement", draft.name, "end_date", add_days(today(), 10))

        result = send_renewal_reminders(days_before_expiry=90)
        self.assertTrue(self._ok(result), self._errors(result))

        # A Draft agreement is filtered out by status='Active' in the SQL, so it
        # is never even iterated -- this holds independently of the add_comment bug.
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Periodic Donation Agreement",
                "reference_name": draft.name,
            },
            fields=["content"],
        )
        self.assertFalse(
            any("Renewal reminder sent" in (c.content or "") for c in comments),
            "Draft agreements must be skipped (status filter = 'Active')",
        )

    # ================================================================== #
    # generate_tax_receipts
    #
    # Each Active + anbi_eligible agreement gets a real confirmation receipt:
    # the per-agreement body renders receipt HTML, converts it to a PDF, and
    # attaches it as a private File to the agreement (deterministically named
    # ``ANBI_Tax_Receipt_<agreement_number>.pdf``), then records a
    # "Tax receipt generated" audit comment ONLY after the File is saved, and
    # bumps ``generated_count``. Re-running replaces the existing receipt File
    # (exactly one per agreement).
    # ================================================================== #
    def _receipt_files(self, agreement_name):
        """All File records attached to an agreement whose name looks like a receipt."""
        return frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Periodic Donation Agreement",
                "attached_to_name": agreement_name,
                "file_name": ["like", "ANBI_Tax_Receipt_%"],
            },
            fields=["name", "file_name", "is_private"],
        )

    def test_generate_tax_receipts_attaches_pdf_file_to_agreement(self):
        # Active + ANBI eligible -> should get a real receipt File.
        donor_anbi = self._make_donor(anbi_consent=1)
        anbi = self.create_anbi_compliant_agreement(donor=donor_anbi.name, status="Active")
        self.assertEqual(anbi.anbi_eligible, 1)
        self.assertEqual(anbi.status, "Active")

        result = generate_tax_receipts(filters={})
        self.assertTrue(self._ok(result), self._errors(result))
        self.assertGreaterEqual(
            self._data(result)["generated_count"],
            1,
            "An Active ANBI-eligible agreement should get a tax receipt.",
        )

        # A private receipt File is now attached to the agreement. Frappe's
        # save_file may insert a uniqueness hash before the extension, so the
        # deterministic part is the stem prefix.
        files = self._receipt_files(anbi.name)
        self.assertEqual(len(files), 1, "exactly one receipt File must be attached")
        self.assertTrue(
            files[0].file_name.startswith(f"ANBI_Tax_Receipt_{anbi.agreement_number}"),
            f"unexpected receipt file name: {files[0].file_name}",
        )
        self.assertTrue(files[0].file_name.endswith(".pdf"))
        self.assertEqual(files[0].is_private, 1, "the receipt must be a private File")
        self.track_doc("File", files[0].name)

        # The File holds real, non-empty PDF bytes (a %PDF header).
        content = frappe.get_doc("File", files[0].name).get_content()
        if isinstance(content, str):
            content = content.encode("latin-1", errors="ignore")
        self.assertTrue(content, "receipt File must have content")
        self.assertTrue(content.startswith(b"%PDF"), "receipt File must be a real PDF")

        # And a "Tax receipt generated" audit comment is recorded on the agreement.
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Periodic Donation Agreement",
                "reference_name": anbi.name,
            },
            fields=["content"],
        )
        self.assertTrue(
            any("Tax receipt generated" in (c.content or "") for c in comments),
            "A tax-receipt comment must be recorded on the ANBI agreement.",
        )

    def test_generate_tax_receipts_is_idempotent_replace(self):
        """Re-running must not pile up duplicate receipt Files."""
        donor = self._make_donor(anbi_consent=1)
        anbi = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")

        first = generate_tax_receipts(filters={})
        self.assertTrue(self._ok(first), self._errors(first))
        second = generate_tax_receipts(filters={})
        self.assertTrue(self._ok(second), self._errors(second))

        files = self._receipt_files(anbi.name)
        self.assertEqual(
            len(files),
            1,
            "re-running must replace, not duplicate, the receipt File",
        )
        for f in files:
            self.track_doc("File", f.name)

    def test_generate_tax_receipts_accepts_json_string_filters(self):
        """filters may arrive as a JSON string from the HTTP layer; must parse and succeed."""
        result = generate_tax_receipts(filters=json.dumps({"status": "Active"}))
        self.assertTrue(self._ok(result), self._errors(result))
        self.assertIn("generated_count", self._data(result))

    def test_generate_tax_receipts_skips_non_anbi_pledge_but_not_anbi(self):
        # A non-ANBI 1-year pledge is not eligible ...
        donor_pledge = self._make_donor(anbi_consent=0)
        pledge = self.create_non_anbi_pledge(donor=donor_pledge.name, status="Active")
        self.assertEqual(pledge.anbi_eligible, 0)
        # ... while an Active ANBI agreement in the SAME run is.
        donor_anbi = self._make_donor(anbi_consent=1)
        anbi = self.create_anbi_compliant_agreement(donor=donor_anbi.name, status="Active")

        result = generate_tax_receipts(filters={})
        self.assertTrue(self._ok(result), self._errors(result))

        # The skip is selective: the pledge gets nothing, the ANBI agreement gets
        # a receipt (proves the anbi_eligible filter, not a global no-op).
        self.assertEqual(
            len(self._receipt_files(pledge.name)),
            0,
            "Non-ANBI pledge must not receive a tax receipt (anbi_eligible filter)",
        )
        anbi_files = self._receipt_files(anbi.name)
        self.assertEqual(len(anbi_files), 1, "the ANBI agreement in the same run must get a receipt")
        self.track_doc("File", anbi_files[0].name)

    def test_render_tax_receipt_html_contains_agreement_and_donor(self):
        """The pure renderer must embed the real agreement + donor identity."""
        donor = self._make_donor(anbi_consent=1, donor_name="Renderer Test Donor Unique")
        anbi = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")

        html = render_tax_receipt_html(anbi.name)
        self.assertIn(anbi.agreement_number, html)
        self.assertIn("Renderer Test Donor Unique", html)
        # The deductibility statement is the whole point of the receipt -- assert
        # the actual sentence, not just the substring "ANBI" (which the static
        # template title always contains regardless of data).
        self.assertIn("full tax deductibility", html)

    def test_render_tax_receipt_html_escapes_donor_controlled_input(self):
        """Donor-controlled fields are HTML-escaped in the renderer (render_template
        does NOT autoescape, and the HTML is fed to wkhtmltopdf). Frappe strips
        full tags like <script> at storage, so this asserts on a metacharacter
        that survives storage -- '&' -- proving the renderer's escaping is live."""
        donor = self._make_donor(anbi_consent=1, donor_name="Acme & Co Foundation")
        anbi = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")

        html = render_tax_receipt_html(anbi.name)
        self.assertIn("Acme &amp; Co Foundation", html, "donor name must be HTML-escaped")
        self.assertNotIn("Acme & Co Foundation", html, "a raw, unescaped ampersand must not appear")

    # ================================================================== #
    # export_agreements  /  report get_data
    #
    # The anbi_periodic_agreements report selects with ``WHERE pda.docstatus < 2``.
    # Periodic Donation Agreement is NOT submittable (docstatus always 0), so an
    # Active agreement is returned by ``get_data``. The export, which delegates to
    # that report, therefore contains a data row for each matching agreement
    # (the doctype tracks lifecycle via its ``status`` Select field, not docstatus).
    # ================================================================== #
    def test_report_get_data_returns_active_agreement_row(self):
        from verenigingen.verenigingen.report.anbi_periodic_agreements.anbi_periodic_agreements import (
            get_data,
        )

        donor = self._make_donor(anbi_consent=1, donor_name="Report GetData Donor Unique")
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")

        rows = get_data({})
        self.assertGreaterEqual(len(rows), 1, "report must return rows for Active agreements")
        matching = [r for r in rows if r["agreement_number"] == agreement.agreement_number]
        self.assertEqual(
            len(matching),
            1,
            "the Active agreement must appear exactly once in the report data",
        )
        self.assertEqual(matching[0]["donor"], donor.name)

    def test_export_agreements_produces_csv_with_data_row(self):
        donor = self._make_donor(anbi_consent=1, donor_name="Export Test Donor Unique")
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")

        result = export_agreements(filters={})
        self.assertTrue(self._ok(result), f"export failed: {self._errors(result)}")
        self.assertTrue(self._data(result)["file_name"].endswith(".csv"))
        self.assertTrue(self._data(result)["file_url"])

        # The export creates a real File record with the report content.
        file_doc = frappe.get_all(
            "File",
            filters={"file_url": self._data(result)["file_url"]},
            fields=["name"],
            limit=1,
        )
        self.assertTrue(file_doc, "export must create a File record")
        self.track_doc("File", file_doc[0].name)

        content = frappe.get_doc("File", file_doc[0].name).get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        # Header section is always present.
        self.assertIn("ANBI Periodic Agreements Report", content)
        self.assertIn("Agreement Number", content)  # column header row

        # The Active agreement now appears as a real data row in the CSV.
        self.assertIn(
            agreement.agreement_number,
            content,
            "the Active agreement must be exported as a data row",
        )

    def test_export_agreements_accepts_json_string_filters(self):
        result = export_agreements(filters=json.dumps({}))
        self.assertTrue(self._ok(result), self._errors(result))
        self.assertIn("file_url", self._data(result))
        file_doc = frappe.get_all(
            "File", filters={"file_url": self._data(result)["file_url"]}, fields=["name"], limit=1
        )
        if file_doc:
            self.track_doc("File", file_doc[0].name)
