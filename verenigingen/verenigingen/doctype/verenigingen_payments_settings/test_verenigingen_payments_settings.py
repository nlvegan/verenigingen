# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for the Verenigingen Payments Settings controller.

Verenigingen Payments Settings is a Single doctype. To avoid mutating the shared
singleton, these tests build in-memory documents (``frappe.new_doc``) and drive
the real SEPA sub-validator (``_validate_sepa_configuration``) directly. No
business logic is mocked — the IBAN checksum validation runs for real. Covers a
happy path plus the mandatory-when-enabled and invalid-checksum rejection
branches.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# A real, mod-97-valid Dutch IBAN (from the doctype field description).
VALID_IBAN = "NL91ABNA0417164300"


class TestVerenigingenPaymentsSettings(EnhancedTestCase):
    def _new_settings(self, **fields):
        doc = frappe.new_doc("Verenigingen Payments Settings")
        for key, value in fields.items():
            doc.set(key, value)
        return doc

    def test_sepa_valid_config_passes(self):
        """A valid IBAN + creditor id + enabled SEPA validates without throwing."""
        doc = self._new_settings(
            enable_sepa_direct_debit=1,
            company_iban=VALID_IBAN,
            creditor_id="NL60ZZZ12345678002",
        )
        # Must not raise
        doc._validate_sepa_configuration()

    def test_sepa_enabled_requires_company_iban(self):
        """Enabling SEPA without a Company IBAN is rejected."""
        doc = self._new_settings(
            enable_sepa_direct_debit=1,
            company_iban="",
            creditor_id="NL60ZZZ12345678002",
        )
        with self.assertRaises(frappe.ValidationError):
            doc._validate_sepa_configuration()

    def test_sepa_enabled_requires_creditor_id(self):
        """Enabling SEPA with an IBAN but no Creditor ID is rejected."""
        doc = self._new_settings(
            enable_sepa_direct_debit=1,
            company_iban=VALID_IBAN,
            creditor_id="",
        )
        with self.assertRaises(frappe.ValidationError):
            doc._validate_sepa_configuration()

    def test_invalid_company_iban_rejected(self):
        """An IBAN failing mod-97 checksum validation is rejected."""
        doc = self._new_settings(
            enable_sepa_direct_debit=0,
            company_iban="NL00ABNA0417164300",  # wrong check digits
        )
        with self.assertRaises(frappe.ValidationError):
            doc._validate_sepa_configuration()
