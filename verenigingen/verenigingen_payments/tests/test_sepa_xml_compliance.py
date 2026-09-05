#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA XML Compliance Tests

This test suite validates SEPA XML generation compliance with the pain.008.001.08 standard
and Dutch banking requirements after the Direct Debit Batch refactoring.

Focus Areas:
- XML structure compliance with pain.008.001.08
- Dutch banking specific requirements
- SEPA Core Direct Debit scheme compliance
- Mandate sequence type handling
- Address information formatting
- Financial data accuracy
- XML schema validation

Author: Verenigingen Development Team
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.support.sepa_test_configuration import (
    SEPA_TEST_FIELDS,
    apply_sepa_test_configuration,
    verify_sepa_configuration,
)
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import sepa_xml_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities, SEPAXMLValidator


class TestSEPAXMLCompliance(EnhancedTestCase):
    """Test SEPA XML compliance and Dutch banking standards"""

    @classmethod
    def setUpClass(cls):
        """Set up SEPA configuration for XML testing"""
        super().setUpClass()
        # Single-module runs under-seed (before_tests is unreliable in erpnext-v16),
        # leaving Verenigingen Settings.creation_user unset; seed it so the customer
        # <->donor link and Settings save succeed.
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        cls._setup_sepa_test_configuration()

    @classmethod
    def _setup_sepa_test_configuration(cls):
        """Configure SEPA settings for testing, and return the configured company.

        #466: this used to write ``sepa_creditor_id`` / ``company_iban`` /
        ``company_bic`` / ``enable_strict_sepa_validation`` onto *Verenigingen
        Settings*, where none of those four fields exist -- silent no-ops, every
        run -- and ``company = "Test Vereniging"``, a Company that does not exist,
        whose LinkValidationError took the rest of the helper down inside a
        ``try/except``. The real creditor fields live on *Verenigingen Payments
        Settings*; ``enable_strict_sepa_validation`` has no counterpart on either
        Single (see the shared helper's docstring) and is deliberately not
        guessed at.
        """
        cls.eur_company = apply_sepa_test_configuration()
        return cls.eur_company

    def setUp(self):
        """Set up each test with fresh batch data"""
        super().setUp()
        # Re-assert per test: EnhancedTestCase.setUp re-points Verenigingen
        # Settings.company at the ERPNext "_Test Company" on EVERY test method, so
        # setUpClass's configuration is already undone by the time a body runs
        # (#528). Measured, with the other four callers, under "Callers on
        # EnhancedTestCase must re-apply this PER TEST" in
        # tests/support/sepa_test_configuration.
        self._setup_sepa_test_configuration()
        self.test_batch = None
        # The batch child rows below require a real Sales Invoice link (the
        # `invoice` field is a reqd Link to Sales Invoice). On a fresh CI-mirror
        # site the hardcoded "INV-SEPA-001" names don't exist, so create a real
        # member/customer once and mint real invoices per row. XML assertions
        # read the row's member_name/iban/amount/mandate, NOT the linked invoice.
        self._invoice_member = self.create_test_member(
            first_name="SEPAXML",
            last_name="Compliance",
            email="sepaxml.compliance@example.com",
        )
        # Direct Debit Batch validation (validate_invoice_for_sepa) only accepts
        # EUR invoices, so the invoices must belong to a EUR company.
        #
        # This used to be `frappe.db.get_value("Company", {"default_currency": "EUR"},
        # "name")`, which carries two defects in one line: it borrows a fixture instead of
        # owning one (which company wins depends on what else ran first in the shard, and
        # shard bins re-pack on measured runtime), and `db.get_value` has no `order_by` so
        # it defaults to `creation DESC` -- not "some EUR company" but the NEWEST one.
        # Measured on test_site_2, 2026-08-23: 30 EUR companies; the old expression
        # returned 'TEST EBkh Cleanup Cov Co' (an e_boekhouden fixture) while the owned
        # helper returned 'TEST-Payment-Integration-Company'. One of those 30
        # ('EBH Migration Test Co') has neither `default_receivable_account` nor
        # `default_income_account` -- the chart-less company whose borrow produced 101
        # failures across two shards (#237).
        #
        # `cls.eur_company` is what `apply_sepa_test_configuration()` configured the SEPA
        # creditor identity against, so using it keeps the invoices and the settings under
        # the same company rather than merely the same currency.
        self._eur_company = self.eur_company
        self._ensure_active_fiscal_year(self._eur_company)
        # Batch child rows require reqd Links to Member and Membership; create a
        # membership for the test member so rows can be inserted on a fresh site.
        self._membership = self.create_test_membership(member_name=self._invoice_member.name)

    def test_invoices_are_posted_under_the_owned_company_not_the_newest_eur_one(self):
        """Mint a real invoice with a newer EUR company present and read back its company.

        The earlier version of this pin called a one-line ``_resolve_invoice_company()``
        wrapper inside the decoy window and asserted its return value. That wrapper was
        ``return self.eur_company`` -- an attribute resolved in ``setUpClass``, long before
        the decoy existed -- so the window contained no database work at all and the pin
        could not have failed for the reason it claimed. It pinned a getter, not a
        behaviour. Both the wrapper and that assertion are gone; the invoice path is the
        thing that actually has to be right, so post one and read the persisted row.
        """
        from verenigingen.tests.support.eur_company_decoy import newest_eur_company

        with newest_eur_company() as decoy:
            invoice_name = self._real_invoice_name()
            company = frappe.db.get_value("Sales Invoice", invoice_name, "company")

        self.assertEqual(company, "TEST-Payment-Integration-Company")
        self.assertNotEqual(company, decoy)
        self.assertEqual(
            frappe.db.get_value("Company", company, "default_currency"),
            "EUR",
            "validate_invoice_for_sepa rejects a non-EUR invoice",
        )

    def _ensure_active_fiscal_year(self, company):
        """Ensure an active Fiscal Year covers today and permits `company`.

        Restricted fiscal years (linked to specific companies via the
        Fiscal Year Company child table) block invoice posting for other
        companies. Add the company to any active-but-restricted fiscal year.
        """
        today_date = frappe.utils.getdate(frappe.utils.today())
        for fy in frappe.get_all("Fiscal Year", fields=["name", "year_start_date", "year_end_date"]):
            if not (fy.year_start_date <= today_date <= fy.year_end_date):
                continue
            companies = frappe.get_all("Fiscal Year Company", filters={"parent": fy.name}, pluck="company")
            if not companies:
                return  # Unrestricted active fiscal year already usable
            if company in companies:
                return
            fy_doc = frappe.get_doc("Fiscal Year", fy.name)
            fy_doc.append("companies", {"company": company})
            fy_doc.save(ignore_permissions=True)
            return

    def _real_invoice_name(self, amount=25.00):
        """Create and return the name of a real, submitted EUR Sales Invoice.

        The batch's `invoice` child field is a reqd Link to Sales Invoice and
        the batch validates each as a valid (EUR, outstanding) SEPA invoice.
        """
        # Unconditional: `self._eur_company` is the owned company `setUp` resolved by
        # name, so there is no "no EUR company found" case left to fall through.
        kwargs = {
            "customer": self._invoice_member.name,
            "grand_total": amount,
            "company": self._eur_company,
        }
        invoice = self.create_test_sales_invoice(**kwargs)
        return invoice.name

    def _ensure_mandate(self, mandate_reference, iban, recurring=False):
        """Idempotently ensure an active SEPA Mandate with this reference exists.

        Direct Debit Batch.validate_sequence_types() requires an active SEPA
        Mandate whose mandate_id matches each row's mandate_reference. These are
        not seeded on fresh CI-mirror sites, so create them here. SEPA Mandate
        validates the IBAN checksum, so generate a valid test IBAN rather than
        relying on the batch row's (possibly synthetic) IBAN.

        When ``recurring`` is True, a prior "Collected" usage row is recorded so
        get_mandate_sequence_type() returns RCUR (otherwise first use → FRST,
        which makes a RCUR batch row a critical SEPA compliance violation).

        Each mandate gets its OWN member. A batch has one row per debtor in
        reality, and since #584 a member may hold at most one Active mandate per
        purpose -- so hanging every mandate off ``_invoice_member`` (as this used to)
        is both unrealistic and now rejected. ``validate_sequence_types`` resolves
        the mandate by ``mandate_id`` + ``status`` alone
        (``direct_debit_batch.py:109-111``), with no member cross-check, so the batch
        rows can keep naming ``_invoice_member`` as the debtor.
        """
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        if not frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_reference}):
            # One member per mandate -- see the docstring.
            mandate_member = self.create_test_member(
                first_name="XMLMandate", last_name=frappe.generate_hash(length=6)
            )
            # Date the mandate in the past so a prior usage can legitimately
            # post after sign_date (renewal logic would otherwise force FRST).
            sign_date = frappe.utils.add_days(frappe.utils.today(), -60)
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "mandate_id": mandate_reference,
                    "member": mandate_member.name,
                    "account_holder_name": f"{mandate_member.first_name} {mandate_member.last_name}",
                    # Unique account number per mandate: a fixed test IBAN would
                    # collide on the second mandate for the same member ("already
                    # has an active SEPA mandate ... for memberships").
                    "iban": generate_test_iban(
                        "TEST", account_number=str(abs(hash(mandate_reference)) % (10**10)).zfill(10)
                    ),
                    "status": "Active",
                    "mandate_type": "RCUR",
                    "scheme": "SEPA",
                    "sign_date": sign_date,
                }
            )
            if recurring:
                mandate.append(
                    "usage_history",
                    {
                        "usage_date": frappe.utils.add_days(frappe.utils.today(), -30),
                        "reference_doctype": "Other",
                        "sequence_type": "FRST",
                        "amount": 25.00,
                        "status": "Collected",
                    },
                )
            mandate.insert(ignore_permissions=True)
            self._track_test_document("SEPA Mandate", mandate.name)
        return mandate_reference

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        if self.test_batch:
            try:
                frappe.delete_doc("Direct Debit Batch", self.test_batch.name, force=True)
            except:
                pass

    def test_the_class_setup_writes_a_configuration_that_lands(self):
        """#466: this class's SEPA setup configured nothing, on every run.

        It wrote ``sepa_creditor_id``, ``company_iban``, ``company_bic`` and
        ``enable_strict_sepa_validation`` onto *Verenigingen Settings*, where
        **none of those four fields exist** -- assigning a nonexistent field on a
        Frappe Document is a silent no-op. The only assignment that did anything
        was ``company = "Test Vereniging"``, a Company that does not exist, whose
        LinkValidationError took the helper down and was swallowed.

        Damage-first: every test site already holds the expected creditor id, so a
        read-back with no damage is green against the broken helper.

        Named "writes", not "applies": this test RE-APPLIES the configuration in
        its own body, so it is green whether or not the class's other tests run
        under it -- which for this class they demonstrably did not. The
        per-test-body property is pinned separately, by
        test_an_ordinary_test_body_runs_under_the_sepa_configuration.
        """
        original = {
            fieldname: frappe.db.get_single_value("Verenigingen Payments Settings", fieldname)
            for fieldname in SEPA_TEST_FIELDS["Verenigingen Payments Settings"]
        }

        def restore():
            for fieldname, value in original.items():
                frappe.db.set_single_value("Verenigingen Payments Settings", fieldname, value)
            frappe.db.commit()

        self.addCleanup(restore)

        for fieldname in original:
            frappe.db.set_single_value("Verenigingen Payments Settings", fieldname, None)
        frappe.db.commit()

        # The class's own setup path, not the shared helper directly.
        company = type(self)._setup_sepa_test_configuration()

        verify_sepa_configuration(company)

    def test_an_ordinary_test_body_runs_under_the_sepa_configuration(self):
        """The property the class-setup test above cannot prove: an ordinary body,
        which applies nothing itself, is running under the configuration.

        This is the pin for the setUp re-assertion. EnhancedTestCase.setUp reverts
        Verenigingen Settings.company to "_Test Company" before every test method
        (#528), so with that line removed this test goes red -- no damage step is
        needed, the harness supplies the damage on every run.
        """
        verify_sepa_configuration(self.eur_company)

    def test_pain_008_001_08_xml_structure(self):
        """Test compliance with pain.008.001.08 XML structure"""
        batch_doc = self._create_comprehensive_test_batch()

        # Generate SEPA XML
        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)

        # Parse and validate XML structure
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")
        self._validate_pain_008_structure(xml_content)

    def test_get_xml_content_from_batch_returns_the_generated_xml(self):
        """#529: _get_xml_content_from_batch called sepa_xml_service._create_sepa_xml_structure,
        which exists nowhere on SEPAXMLGenerationService -- the AttributeError was swallowed by
        this method's own `except Exception`, so it silently returned None and every `if
        xml_content:` guard in this module was unconditionally False, regardless of whether
        generation itself succeeded.

        This calls the extractor directly (skipping the outer try/except that the real test
        bodies wrap it in, which would also swallow the AttributeError and hide the bug) after a
        real, successful generation, so a regression to the fictional method name fails here for
        the actual reason, not via a masked exception.
        """
        batch_doc = self._create_comprehensive_test_batch()

        sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        self.assertTrue(batch_doc.sepa_file, "generation must have attached a SEPA file")

        xml_content = self._get_xml_content_from_batch(batch_doc)

        self.assertIsNotNone(
            xml_content, "extractor returned None -- the guarded assertions never ran"
        )
        root = ET.fromstring(xml_content)
        # ET reports the default-namespace-qualified tag here, not the bare local
        # name. `_validate_pain_008_structure` and `test_xml_namespace_compliance`
        # made this same wrong assumption (against a bare "Document"/an absent
        # "xmlns" attribute); both were fixed alongside this test once fixing this
        # extractor made them reachable for the first time.
        self.assertEqual(root.tag, "{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Document")

    def test_sepa_core_direct_debit_compliance(self):
        """Test SEPA Core Direct Debit scheme compliance"""
        batch_doc = self._create_comprehensive_test_batch()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check service level
        service_level = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}SvcLvl/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Cd"
        )
        self.assertIsNotNone(service_level)
        self.assertEqual(service_level.text, "SEPA")

        # Check local instrument
        local_instrument = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}LclInstrm/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Cd"
        )
        self.assertIsNotNone(local_instrument)
        self.assertEqual(local_instrument.text, "CORE")

        # Check sequence type
        sequence_type = root.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}SeqTp")
        self.assertIsNotNone(sequence_type)
        self.assertIn(sequence_type.text, ["FRST", "RCUR", "OOFF", "FNAL"])

    def test_dutch_banking_specific_requirements(self):
        """Test Dutch banking specific SEPA requirements"""
        batch_doc = self._create_comprehensive_test_batch()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check Dutch creditor IBAN format
        creditor_iban = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}CdtrAcct/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Id/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}IBAN"
        )
        self.assertIsNotNone(creditor_iban)
        self.assertTrue(creditor_iban.text.startswith("NL"))
        self.assertTrue(SEPAUtilities.validate_dutch_iban(creditor_iban.text))

        # Check Dutch BIC format
        creditor_bic = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}CdtrAgt/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}FinInstnId/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}BIC"
        )
        self.assertIsNotNone(creditor_bic)
        self.assertEqual(len(creditor_bic.text), 8)  # Dutch BIC format

        # Check creditor scheme identification (Dutch incassant ID). The naive
        # `//Id` XPath below used to match the CdtrSchmeId/Id WRAPPER element
        # (whitespace text, per the schema), not the actual identifier four
        # levels down at Id/PrvtId/Othr/Id -- #490 review, verified against
        # the generated XML.
        creditor_id = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}CdtrSchmeId"
            "/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Id"
            "/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}PrvtId"
            "/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Othr"
            "/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Id"
        )
        self.assertIsNotNone(creditor_id)
        self.assertTrue(creditor_id.text.startswith("NL"))
        self.assertIn("ZZZ", creditor_id.text)

    def test_mandate_sequence_type_accuracy(self):
        """Test mandate sequence type handling accuracy"""
        # Create batch with mixed sequence types
        batch_doc = self._create_test_batch_with_sequence_types()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check that mandate information is present. pain.008.001.08 spells
        # the element "MndtId", not "MdtId" -- #490 review, verified against
        # the generated XML (<MndtRltdInf><MndtId>...).
        mandate_ids = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}MndtId")
        self.assertGreater(len(mandate_ids), 0)

        # Check mandate sign dates
        sign_dates = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}DtOfSgntr")
        self.assertEqual(len(sign_dates), len(mandate_ids))

        # Validate date format (YYYY-MM-DD) and check not hardcoded
        for date_elem in sign_dates:
            self._validate_date_format(date_elem.text)

        # Additional validation to ensure sign dates aren't hardcoded
        self._validate_mandate_sign_dates_not_hardcoded(xml_content)

    @unittest.expectedFailure
    def test_structured_address_information(self):
        """Test structured address information (pain.008.001.08 requirement)

        #490: this is a genuine, unfixed production gap, not a test bug -- traced
        two layers deep. (1) `Direct Debit Batch Invoice` (the child doctype
        `_create_test_batch_with_addresses` inserts rows into) has no
        address/postal_code/city fields at all, so the fixture below builds an
        `addresses` list and never attaches it to the row -- there is nowhere on
        the row to put it. (2) Even if it could: `SEPAXMLAdapter._build_transaction`
        constructs `SEPADebtor(name=..., iban=..., bic=..., country="NL")` and never
        populates `address_line_1`/`postal_code`/`town`, so
        `EnhancedSEPAXMLGenerator._generate_debtor_info`'s `build_postal_address(...)`
        call is always given an all-None address and emits no `<PstlAdr>`. The XML
        generator itself DOES support this (`build_postal_address` writes a
        `PstlAdr` when given data) -- the gap is that nothing upstream ever supplies
        it. Implementing this is a real feature (schema + adapter + a source for the
        address, e.g. the member's `Address`), out of scope for a swallow-removal
        fix; `@unittest.expectedFailure` keeps this failure visible (as an expected
        one) rather than silently green, and will flip to an "unexpected success"
        the day the feature lands, which is the signal to remove this decorator.
        """
        batch_doc = self._create_test_batch_with_addresses()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check for postal address information
        postal_addresses = root.findall(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Dbtr/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}PstlAdr"
        )
        self.assertTrue(postal_addresses, "no postal addresses were generated -- nothing below can be checked")

        for address in postal_addresses:
            # Check country code
            country = address.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Ctry")
            if country is not None:
                self.assertEqual(country.text, "NL")

            # Check postal code format
            postal_code = address.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}PstCd")
            if postal_code is not None:
                self._validate_dutch_postal_code(postal_code.text)

    def test_financial_data_accuracy(self):
        """Test financial data accuracy and calculations"""
        batch_doc = self._create_comprehensive_test_batch()

        # Manually calculate expected totals
        expected_total = sum(float(invoice.amount) for invoice in batch_doc.invoices)
        expected_count = len(batch_doc.invoices)

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check group header totals
        nb_of_txs = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}GrpHdr/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}NbOfTxs"
        )
        self.assertIsNotNone(nb_of_txs)
        self.assertEqual(int(nb_of_txs.text), expected_count)

        ctrl_sum = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}GrpHdr/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}CtrlSum"
        )
        self.assertIsNotNone(ctrl_sum)
        self.assertAlmostEqual(float(ctrl_sum.text), expected_total, places=2)

        # Check individual transaction amounts
        instd_amounts = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}InstdAmt")
        self.assertEqual(len(instd_amounts), expected_count)

        # Verify currency codes
        for amount in instd_amounts:
            self.assertEqual(amount.get("Ccy"), "EUR")
            # Verify amount is positive and reasonable
            amount_value = float(amount.text)
            self.assertGreater(amount_value, 0)
            self.assertLess(amount_value, 1000)  # Reasonable membership fee

    def test_xml_schema_validation(self):
        """Test XML schema validation against pain.008.001.08 XSD"""
        batch_doc = self._create_comprehensive_test_batch()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        # Test with SEPA XML validator
        validation_result = SEPAXMLValidator.validate_sepa_xml_schema(xml_content, batch_doc.name)

        # Should have validation result even if XSD is not available
        self.assertIsInstance(validation_result, dict)
        self.assertIn("valid", validation_result)

    def test_xml_namespace_compliance(self):
        """Test XML namespace compliance with pain.008.001.08"""
        batch_doc = self._create_comprehensive_test_batch()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check namespace declaration. ElementTree consumes a default
        # `xmlns=` declaration into the tag's own namespace and does not
        # retain it in .attrib, so root.get("xmlns") is always None for a
        # default-namespaced document; derive it from the tag instead
        # (#529 review).
        expected_namespace = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
        self.assertTrue(root.tag.startswith("{"), f"unexpected unqualified tag: {root.tag}")
        actual_namespace = root.tag[1 : root.tag.index("}")]
        self.assertEqual(actual_namespace, expected_namespace)

        # Check schema location
        schema_location = root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation")
        if schema_location:
            self.assertIn("pain.008.001.08", schema_location)

    def test_dutch_name_handling_with_tussenvoegsel(self):
        """Test proper handling of Dutch names with tussenvoegsel (van, de, etc.)"""
        batch_doc = self._create_test_batch_with_dutch_names()

        xml_file = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)
        xml_content = self._get_xml_content_from_batch(batch_doc)
        self.assertIsNotNone(xml_content, "extractor returned None -- assertions below never ran")

        root = ET.fromstring(xml_content)

        # Check debtor names
        debtor_names = root.findall(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Dbtr/{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Nm"
        )
        self.assertTrue(debtor_names, "no debtor names were generated -- nothing below can be checked")

        for name_elem in debtor_names:
            name = name_elem.text
            # Should be properly formatted (not just field concatenation)
            self.assertIsNotNone(name)
            self.assertGreater(len(name.strip()), 0)
            # Should not have double spaces or weird formatting
            self.assertNotIn("  ", name)

    def _create_comprehensive_test_batch(self):
        """Create comprehensive test batch with realistic Dutch data"""
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = frappe.utils.today()
        batch_doc.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch_doc.batch_description = "SEPA XML Compliance Test Batch"
        batch_doc.batch_type = "CORE"  # SEPA scheme -> pain.008 LclInstrm/Cd
        batch_doc.sequence_type = "RCUR"  # SEPA sequence -> pain.008 SeqTp
        batch_doc.currency = "EUR"

        # Add realistic Dutch test data. #490: the RABO/INGB IBANs below used to
        # carry bogus check digits (NL20.../NL13...), which fail
        # validate_iban's mod-97 checksum and get silently dropped as
        # "Transaction Build Error"s by the adapter -- so a 3-invoice batch
        # only ever produced 1 transaction in the generated XML, and every
        # test in this module that swallowed its own assertions never noticed.
        # Regenerated with generate_test_iban() so all three pass the checksum.
        test_data = [
            {"name": "Jan de Vries", "iban": "NL91ABNA0417164300", "amount": 25.00, "mandate": "MAND-001"},
            {
                "name": "Maria van der Berg",
                "iban": "NL44RABO0123456789",
                "amount": 50.00,
                "mandate": "MAND-002",
            },
            {"name": "Pieter Jansen", "iban": "NL28INGB0000000001", "amount": 35.00, "mandate": "MAND-003"},
        ]

        for i, data in enumerate(test_data):
            batch_doc.append(
                "invoices",
                {
                    "invoice": self._real_invoice_name(data["amount"]),
                    "customer": f"CUST-{i+1:03d}",
                    "member": self._invoice_member.name,
                    "membership": self._membership.name,
                    "member_name": data["name"],
                    "amount": data["amount"],
                    "currency": "EUR",
                    "iban": data["iban"],
                    "mandate_reference": self._ensure_mandate(data["mandate"], data["iban"]),
                    "status": "Pending",
                },
            )

        batch_doc.insert()
        self.test_batch = batch_doc
        return batch_doc

    def _create_test_batch_with_sequence_types(self):
        """Create test batch with different mandate sequence types"""
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = frappe.utils.today()
        batch_doc.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch_doc.batch_description = "Sequence Type Test Batch"
        batch_doc.batch_type = "CORE"  # SEPA scheme -> pain.008 LclInstrm/Cd
        batch_doc.sequence_type = "RCUR"  # SEPA sequence -> pain.008 SeqTp
        batch_doc.currency = "EUR"

        # Add entries with different sequence types
        sequence_types = ["FRST", "RCUR", "OOFF"]

        for i, seq_type in enumerate(sequence_types):
            batch_doc.append(
                "invoices",
                {
                    "invoice": self._real_invoice_name(25.00),
                    "customer": f"CUST-SEQ-{i+1:03d}",
                    "member": self._invoice_member.name,
                    "membership": self._membership.name,
                    "member_name": f"Test Member {seq_type}",
                    "amount": 25.00,
                    "currency": "EUR",
                    "iban": f"NL{91+i:02d}ABNA041716{4300+i:04d}",
                    "mandate_reference": self._ensure_mandate(
                        f"MAND-{seq_type}-{i+1:03d}",
                        f"NL{91+i:02d}ABNA041716{4300+i:04d}",
                        recurring=(seq_type == "RCUR"),
                    ),
                    "sequence_type": seq_type,
                    "status": "Pending",
                },
            )

        batch_doc.insert()
        self.test_batch = batch_doc
        return batch_doc

    def _create_test_batch_with_addresses(self):
        """Create test batch with structured address information"""
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = frappe.utils.today()
        batch_doc.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch_doc.batch_description = "Address Structure Test Batch"
        batch_doc.batch_type = "CORE"  # SEPA scheme -> pain.008 LclInstrm/Cd
        batch_doc.sequence_type = "RCUR"  # SEPA sequence -> pain.008 SeqTp
        batch_doc.currency = "EUR"

        # Add entries with Dutch addresses
        addresses = [
            {
                "name": "Willem van Oranje",
                "address": "Binnenhof 1",
                "postal_code": "2513 AA",
                "city": "Den Haag",
            },
            {
                "name": "Anne Frank",
                "address": "Prinsengracht 263",
                "postal_code": "1016 GV",
                "city": "Amsterdam",
            },
        ]

        for i, addr in enumerate(addresses):
            batch_doc.append(
                "invoices",
                {
                    "invoice": self._real_invoice_name(30.00),
                    "customer": f"CUST-ADDR-{i+1:03d}",
                    "member": self._invoice_member.name,
                    "membership": self._membership.name,
                    "member_name": addr["name"],
                    "amount": 30.00,
                    "currency": "EUR",
                    "iban": f"NL{91+i:02d}ABNA041716{4300+i:04d}",
                    "mandate_reference": self._ensure_mandate(
                        f"MAND-ADDR-{i+1:03d}", f"NL{91+i:02d}ABNA041716{4300+i:04d}"
                    ),
                    "status": "Pending",
                },
            )

        batch_doc.insert()
        self.test_batch = batch_doc
        return batch_doc

    def _create_test_batch_with_dutch_names(self):
        """Create test batch with Dutch names including tussenvoegsel"""
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = frappe.utils.today()
        batch_doc.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch_doc.batch_description = "Dutch Names Test Batch"
        batch_doc.batch_type = "CORE"  # SEPA scheme -> pain.008 LclInstrm/Cd
        batch_doc.sequence_type = "RCUR"  # SEPA sequence -> pain.008 SeqTp
        batch_doc.currency = "EUR"

        # Dutch names with tussenvoegsel
        dutch_names = [
            "Johannes van der Waals",
            "Wilhelmina de Wit",
            "Hendrik van den Berg",
            "Elisabeth ter Horst",
            "Cornelis van de Velde",
        ]

        for i, name in enumerate(dutch_names):
            batch_doc.append(
                "invoices",
                {
                    "invoice": self._real_invoice_name(40.00),
                    "customer": f"CUST-DUTCH-{i+1:03d}",
                    "member": self._invoice_member.name,
                    "membership": self._membership.name,
                    "member_name": name,
                    "amount": 40.00,
                    "currency": "EUR",
                    "iban": f"NL{91+i:02d}ABNA041716{4300+i:04d}",
                    "mandate_reference": self._ensure_mandate(
                        f"MAND-DUTCH-{i+1:03d}", f"NL{91+i:02d}ABNA041716{4300+i:04d}"
                    ),
                    "status": "Pending",
                },
            )

        batch_doc.insert()
        self.test_batch = batch_doc
        return batch_doc

    def _get_xml_content_from_batch(self, batch_doc) -> Optional[str]:
        """Extract XML content from batch document"""
        try:
            if hasattr(batch_doc, "sepa_file") and batch_doc.sepa_file:
                # In a real implementation, you would read the file content
                # For testing, we'll generate the XML again. #529:
                # `sepa_xml_service._create_sepa_xml_structure` never existed --
                # SEPAXMLGenerationService only exposes `generate_sepa_xml_for_batch`
                # (which writes a File and returns its URL, not the XML text) and
                # `_save_xml_file`. The raw XML string is produced by its adapter,
                # `xml_adapter.generate_xml_for_batch`, which is what
                # `generate_sepa_xml_for_batch` itself calls internally. Settings
                # are not a parameter -- the adapter fetches them itself via
                # `sepa_config_service.get_sepa_settings()`.
                return sepa_xml_service.xml_adapter.generate_xml_for_batch(
                    batch_doc,
                    batch_doc.sepa_message_id or "TEST-MSG-ID",
                    batch_doc.sepa_payment_info_id or "TEST-PMT-ID",
                )
            return None
        except Exception as e:
            get_harness_logger("sepa-xml-compliance").warning("Could not extract XML content: %s", e)
            return None

    def _validate_pain_008_structure(self, xml_content: str):
        """Validate basic pain.008.001.08 structure"""
        root = ET.fromstring(xml_content)

        # Check root element
        # ET reports the default-namespace-qualified tag, not the bare local
        # name -- see the new test above (#529) for the same assumption made
        # correctly.
        self.assertEqual(root.tag, "{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}Document")

        # Check main structure elements
        cstmr_drct_dbt_initn = root.find(
            ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}CstmrDrctDbtInitn"
        )
        self.assertIsNotNone(cstmr_drct_dbt_initn)

        # Check group header
        grp_hdr = root.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}GrpHdr")
        self.assertIsNotNone(grp_hdr)

        # Check payment information
        pmt_inf = root.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}PmtInf")
        self.assertIsNotNone(pmt_inf)

        # Check transaction information exists
        drct_dbt_tx_infs = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}DrctDbtTxInf")
        self.assertGreater(len(drct_dbt_tx_infs), 0)

    def _validate_mandate_sign_dates_not_hardcoded(self, xml_content: str):
        """
        Validate that mandate sign dates are NOT hardcoded to 2023-01-01.

        This is a critical compliance check - the old implementation had a
        hardcoded fallback of 2023-01-01 which is incorrect for SEPA compliance.
        The DtOfSgntr field must contain the actual mandate signing date.
        """
        root = ET.fromstring(xml_content)

        sign_dates = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}DtOfSgntr")

        for sign_date_elem in sign_dates:
            date_value = sign_date_elem.text
            # Validate date format
            self._validate_date_format(date_value)

            # Critical: Check that dates are not the old hardcoded value
            # While 2023-01-01 could theoretically be valid, it was the hardcoded
            # fallback in the old code and should raise a warning in tests
            if date_value == "2023-01-01":
                frappe.logger().warning(
                    f"DtOfSgntr contains suspicious value 2023-01-01 - "
                    f"this was the old hardcoded fallback. Please verify this is the actual mandate sign date."
                )

    def _validate_date_format(self, date_string: str):
        """Validate date format is YYYY-MM-DD"""
        try:
            datetime.strptime(date_string, "%Y-%m-%d")
        except ValueError:
            self.fail(f"Invalid date format: {date_string}")

    def _validate_dutch_postal_code(self, postal_code: str):
        """Validate Dutch postal code format (1234 AB)"""
        import re

        pattern = r"^\d{4}\s?[A-Z]{2}$"
        self.assertTrue(re.match(pattern, postal_code), f"Invalid Dutch postal code: {postal_code}")


class TestBuildPostalAddressParity(unittest.TestCase):
    """XML-output parity: build_postal_address must produce byte-identical results
    to the inlined creditor/debtor address blocks it replaced.

    We compare element tag names, order, and text for the same sample address data
    to prove the refactored generator emits the same XML structure.
    """

    def _inline_address(self, parent, address_line_1, address_line_2, postal_code, town, country="NL"):
        """Reproduce the original inlined creditor/debtor address block verbatim."""
        if any([address_line_1, address_line_2, postal_code, town]):
            pstl_adr = ET.SubElement(parent, "PstlAdr")
            ET.SubElement(pstl_adr, "Ctry").text = country
            if address_line_1:
                ET.SubElement(pstl_adr, "AdrLine").text = address_line_1
            if address_line_2:
                ET.SubElement(pstl_adr, "AdrLine").text = address_line_2
            if postal_code:
                ET.SubElement(pstl_adr, "PstCd").text = postal_code
            if town:
                ET.SubElement(pstl_adr, "TwnNm").text = town

    def _helper_address(self, parent, address_line_1, address_line_2, postal_code, town, country="NL"):
        """Call the shared helper with the same data."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        build_postal_address(
            parent,
            {
                "country": country,
                "address_line_1": address_line_1,
                "address_line_2": address_line_2,
                "postal_code": postal_code,
                "town": town,
            },
        )

    def _tostring(self, parent):
        return ET.tostring(parent, encoding="unicode")

    def _make_roots(self):
        return ET.Element("Cdtr"), ET.Element("Cdtr")

    def _assert_parity(self, address_line_1, address_line_2, postal_code, town, country="NL"):
        inline_root, helper_root = self._make_roots()
        self._inline_address(inline_root, address_line_1, address_line_2, postal_code, town, country)
        self._helper_address(helper_root, address_line_1, address_line_2, postal_code, town, country)
        self.assertEqual(
            self._tostring(inline_root),
            self._tostring(helper_root),
            f"XML mismatch for address: {address_line_1!r}, {address_line_2!r}, {postal_code!r}, {town!r}",
        )

    def test_full_address_parity(self):
        self._assert_parity("Teststraat 1", "Appartement 2", "1234 AB", "Amsterdam")

    def test_address_line_1_only(self):
        self._assert_parity("Teststraat 1", None, None, None)

    def test_postal_code_and_town_only(self):
        self._assert_parity(None, None, "1234 AB", "Amsterdam")

    def test_town_only(self):
        self._assert_parity(None, None, None, "Rotterdam")

    def test_no_address_fields_emits_nothing(self):
        """When no optional address fields are set, no PstlAdr element is emitted."""
        inline_root, helper_root = self._make_roots()
        self._inline_address(inline_root, None, None, None, None)
        self._helper_address(helper_root, None, None, None, None)
        self.assertEqual(self._tostring(inline_root), self._tostring(helper_root))
        # Confirm both produce an element with NO PstlAdr child
        self.assertIsNone(inline_root.find("PstlAdr"))
        self.assertIsNone(helper_root.find("PstlAdr"))

    def test_country_code_is_first_child_of_pstladr(self):
        """Ctry must be the first sub-element of PstlAdr, matching the original order."""
        helper_root = ET.Element("Cdtr")
        self._helper_address(helper_root, "Straat 1", None, "1234 AB", "Utrecht")
        pstl_adr = helper_root.find("PstlAdr")
        self.assertIsNotNone(pstl_adr)
        children = list(pstl_adr)
        self.assertEqual(children[0].tag, "Ctry")
        self.assertEqual(children[0].text, "NL")

    def test_address_line_2_only(self):
        self._assert_parity(None, "Suite 3", None, None)

    def test_be_country_code(self):
        self._assert_parity("Rue de la Loi 1", None, "1000", "Brussels", country="BE")


if __name__ == "__main__":
    unittest.main()
