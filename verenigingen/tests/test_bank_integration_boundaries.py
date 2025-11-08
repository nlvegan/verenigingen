"""
Integration Boundary Tests for Bank Import/Export Systems

Tests the integration boundaries between Verenigingen and Dutch banking systems,
including SEPA file processing, bank statement imports, and payment reconciliation.

These tests focus on realistic data exchange scenarios with proper error handling
and boundary condition validation.
"""

import json
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, mock_open

import frappe
import requests_mock

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAFileExportIntegration(EnhancedTestCase):
    """Test SEPA direct debit file generation and export"""

    def setUp(self):
        super().setUp()
        self.test_company = self.create_test_company()
        self.test_member = self.create_test_member(
            first_name="Jan",
            last_name="de Wit",
            email="jan.dewit@example.nl",
            iban="NL91 ABNA 0417 1643 00"
        )

        # Create SEPA mandate for the member
        self.sepa_mandate = self.create_test_sepa_mandate(
            member_name=self.test_member.name,
            iban="NL91 ABNA 0417 1643 00",
            status="active"
        )

    def test_sepa_direct_debit_file_generation(self):
        """
        Test Priority 1: SEPA direct debit file generation for Dutch banking

        Tests the complete workflow from outstanding invoices to SEPA XML file.
        """
        # Create outstanding invoices for batch processing
        invoice1 = self.create_test_sales_invoice(
            customer=self.test_member.name,
            grand_total=25.00,
            status="Submitted"
        )

        invoice2 = self.create_test_sales_invoice(
            customer=self.test_member.name,
            grand_total=15.00,
            status="Submitted"
        )

        # Test SEPA batch creation
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import DirectDebitBatch

        batch = frappe.new_doc("Direct Debit Batch")
        batch.update({
            "company": self.test_company,
            "collection_date": frappe.utils.add_days(frappe.utils.today(), 5),
            "scheme": "CORE",
            "sequence_type": "RCUR"  # Recurring payment
        })
        batch.insert()

        # Add invoices to batch
        batch.append("items", {
            "member": self.test_member.name,
            "sales_invoice": invoice1.name,
            "amount": 25.00,
            "sepa_mandate": self.sepa_mandate.name
        })

        batch.append("items", {
            "member": self.test_member.name,
            "sales_invoice": invoice2.name,
            "amount": 15.00,
            "sepa_mandate": self.sepa_mandate.name
        })

        batch.save()
        batch.submit()

        # Test SEPA XML generation
        sepa_xml = batch.generate_sepa_xml()

        # Verify SEPA XML structure
        self.assertIsNotNone(sepa_xml)
        self.assertIn("pain.008.001.02", sepa_xml)  # SEPA Direct Debit schema
        self.assertIn("NL91ABNA0417164300", sepa_xml)  # IBAN without spaces
        self.assertIn("40.00", sepa_xml)  # Total amount
        self.assertIn("EUR", sepa_xml)  # Currency

        # Verify batch status and file attachment
        batch.reload()
        self.assertEqual(batch.status, "Submitted")
        self.assertTrue(batch.sepa_file)

    def test_sepa_file_validation_and_error_handling(self):
        """Test SEPA file validation for banking compliance"""

        # Test with invalid IBAN
        invalid_member = self.create_test_member(
            first_name="Invalid",
            last_name="IBAN",
            email="invalid@example.nl",
            iban="XX00 INVALID IBAN"
        )

        invoice = self.create_test_sales_invoice(
            customer=invalid_member.name,
            grand_total=25.00
        )

        batch = frappe.new_doc("Direct Debit Batch")
        batch.update({
            "company": self.test_company,
            "collection_date": frappe.utils.add_days(frappe.utils.today(), 5)
        })
        batch.insert()

        # Test validation catches invalid IBAN
        with self.assertRaises(frappe.ValidationError):
            batch.append("items", {
                "member": invalid_member.name,
                "sales_invoice": invoice.name,
                "amount": 25.00,
                "sepa_mandate": "INVALID"
            })
            batch.save()

    def test_sepa_mandate_validation_workflow(self):
        """Test SEPA mandate validation for regulatory compliance"""

        # Test expired mandate
        expired_mandate = self.create_test_sepa_mandate(
            member_name=self.test_member.name,
            iban="NL91 ABNA 0417 1643 00",
            status="expired",
            end_date=frappe.utils.add_days(frappe.utils.today(), -30)
        )

        invoice = self.create_test_sales_invoice(
            customer=self.test_member.name,
            grand_total=25.00
        )

        # Test mandate validation in batch processing
        batch = frappe.new_doc("Direct Debit Batch")
        batch.update({
            "company": self.test_company,
            "collection_date": frappe.utils.add_days(frappe.utils.today(), 5)
        })
        batch.insert()

        # Should reject expired mandates
        with self.assertRaises(frappe.ValidationError):
            batch.append("items", {
                "member": self.test_member.name,
                "sales_invoice": invoice.name,
                "amount": 25.00,
                "sepa_mandate": expired_mandate.name
            })
            batch.save()


class TestBankStatementImportIntegration(EnhancedTestCase):
    """Test bank statement import and payment reconciliation"""

    def setUp(self):
        super().setUp()
        self.test_company = self.create_test_company()
        self.test_member = self.create_test_member(
            first_name="Marie",
            last_name="van der Berg",
            email="marie.vandenberg@example.nl"
        )

        # Create outstanding invoice for reconciliation
        self.outstanding_invoice = self.create_test_sales_invoice(
            customer=self.test_member.name,
            grand_total=50.00,
            status="Submitted"
        )

    def test_camt053_bank_statement_import(self):
        """
        Test Priority 1: CAMT.053 bank statement processing

        Tests import of Dutch bank statement format and automatic reconciliation.
        """
        # Mock CAMT.053 XML content
        camt_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <BkToCstmrStmt>
                <Stmt>
                    <Id>20240315-001</Id>
                    <ElctrncSeqNb>001</ElctrncSeqNb>
                    <CreDtTm>2024-03-15T09:00:00</CreDtTm>
                    <Acct>
                        <Id>
                            <IBAN>NL91ABNA0417164300</IBAN>
                        </Id>
                    </Acct>
                    <Bal>
                        <Tp>
                            <CdOrPrtry>
                                <Cd>CLBD</Cd>
                            </CdOrPrtry>
                        </Tp>
                        <Amt Ccy="EUR">1250.00</Amt>
                        <CdtDbtInd>CRDT</CdtDbtInd>
                        <Dt>
                            <Dt>2024-03-15</Dt>
                        </Dt>
                    </Bal>
                    <Ntry>
                        <Amt Ccy="EUR">50.00</Amt>
                        <CdtDbtInd>CRDT</CdtDbtInd>
                        <Sts>BOOK</Sts>
                        <BookgDt>
                            <Dt>2024-03-15</Dt>
                        </BookgDt>
                        <NtryDtls>
                            <TxDtls>
                                <Refs>
                                    <EndToEndId>{}</EndToEndId>
                                </Refs>
                                <RltdPties>
                                    <Dbtr>
                                        <Nm>Marie van der Berg</Nm>
                                    </Dbtr>
                                    <DbtrAcct>
                                        <Id>
                                            <IBAN>NL02RABO0123456789</IBAN>
                                        </Id>
                                    </DbtrAcct>
                                </RltdPties>
                                <RmtInf>
                                    <Ustrd>Membership dues {}</Ustrd>
                                </RmtInf>
                            </TxDtls>
                        </NtryDtls>
                    </Ntry>
                </Stmt>
            </BkToCstmrStmt>
        </Document>""".format(self.outstanding_invoice.name, self.outstanding_invoice.name)

        # Test bank statement import
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(camt_xml)
            f.flush()

            # Import bank statement
            from verenigingen.utils.bank_integration import import_bank_statement

            result = import_bank_statement(f.name, "CAMT.053")

            # Verify import results
            self.assertTrue(result["success"])
            self.assertEqual(result["transactions_imported"], 1)
            self.assertEqual(result["amount_total"], 50.00)

            # Verify payment entry created and invoice reconciled
            payment_entries = frappe.get_all("Payment Entry",
                filters={"reference_no": self.outstanding_invoice.name})
            self.assertEqual(len(payment_entries), 1)

            # Check invoice status updated
            self.outstanding_invoice.reload()
            self.assertEqual(self.outstanding_invoice.status, "Paid")

    def test_mt940_bank_statement_processing(self):
        """Test MT940 format bank statement import (legacy format)"""

        # Mock MT940 format content
        mt940_content = """:20:STARTUMSE
:25:NL91ABNA0417164300EUR
:28C:00001/001
:60F:C240315EUR1200,00
:61:2403150315DR50,00NMSCNONREF//MEMBERSHIP
:86:/TRTP/SEPA INCASSO ALGEMEEN DOORLOPEND
/CSID/NL02ZZZ123456780001
/NAME/Marie van der Berg
/MARF/{}/REMI/USTD//Membership dues {}
:62F:C240315EUR1250,00
-""".format(self.outstanding_invoice.name, self.outstanding_invoice.name)

        # Test MT940 import
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sta', delete=False) as f:
            f.write(mt940_content)
            f.flush()

            from verenigingen.utils.bank_integration import import_bank_statement

            result = import_bank_statement(f.name, "MT940")

            # Verify MT940 processing
            self.assertTrue(result["success"])
            self.assertGreaterEqual(result["transactions_imported"], 1)

    def test_payment_reconciliation_with_member_matching(self):
        """Test automatic member identification and payment matching"""

        # Create payment entry manually to test matching logic
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.update({
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": self.test_member.name,
            "paid_amount": 50.00,
            "received_amount": 50.00,
            "reference_no": self.outstanding_invoice.name,
            "reference_date": frappe.utils.today(),
            "company": self.test_company
        })

        # Add reference to outstanding invoice
        payment_entry.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": self.outstanding_invoice.name,
            "allocated_amount": 50.00
        })

        payment_entry.insert()
        payment_entry.submit()

        # Verify reconciliation
        self.outstanding_invoice.reload()
        self.assertEqual(self.outstanding_invoice.outstanding_amount, 0.0)
        self.assertEqual(self.outstanding_invoice.status, "Paid")

        # Verify member payment history updated
        payment_history = frappe.get_all("Member Payment History",
            filters={"member": self.test_member.name, "sales_invoice": self.outstanding_invoice.name})
        self.assertEqual(len(payment_history), 1)


class TestDutchBankingComplianceIntegration(EnhancedTestCase):
    """Test Dutch banking regulation compliance and error handling"""

    def setUp(self):
        super().setUp()
        self.test_company = self.create_test_company()

    def test_iban_validation_for_dutch_accounts(self):
        """Test comprehensive IBAN validation for Dutch banking"""

        valid_ibans = [
            "NL91 ABNA 0417 1643 00",
            "NL02RABO0123456789",
            "NL86INGB0002445588"
        ]

        invalid_ibans = [
            "NL91 ABNA 0417 1643 99",  # Invalid check digits
            "DE89 3704 0044 0532 0130 00",  # German IBAN
            "INVALID IBAN FORMAT",
            ""
        ]

        from verenigingen.tests.fixtures.dutch_validation_helpers import validate_dutch_iban

        # Test valid IBANs
        for iban in valid_ibans:
            with self.subTest(iban=iban):
                result = validate_dutch_iban(iban)
                self.assertTrue(result["is_valid"], f"IBAN should be valid: {iban}")

        # Test invalid IBANs
        for iban in invalid_ibans:
            with self.subTest(iban=iban):
                result = validate_dutch_iban(iban)
                self.assertFalse(result["is_valid"], f"IBAN should be invalid: {iban}")

    def test_sepa_mandate_regulatory_compliance(self):
        """Test SEPA mandate compliance with Dutch regulations"""

        member = self.create_test_member(
            first_name="Compliance",
            last_name="Test",
            email="compliance@example.nl"
        )

        # Test mandate creation with all required fields
        mandate = self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL91 ABNA 0417 1643 00",
            mandate_type="RCUR",  # Recurring
            status="active",
            sign_date=frappe.utils.today()
        )

        # Verify mandate compliance
        self.assertIsNotNone(mandate.mandate_id)
        self.assertEqual(mandate.status, "active")
        self.assertIsNotNone(mandate.sign_date)
        self.assertTrue(mandate.is_active)

        # Test mandate lifecycle - suspension
        mandate.status = "suspended"
        mandate.is_active = 0
        mandate.save()

        # Test mandate reactivation
        mandate.status = "active"
        mandate.is_active = 1
        mandate.save()

        # Verify status synchronization
        mandate.reload()
        self.assertEqual(mandate.status, "active")
        self.assertTrue(mandate.is_active)

    def test_bank_holiday_collection_date_validation(self):
        """Test validation of collection dates against Dutch bank holidays"""

        # Mock Dutch bank holidays
        bank_holidays = [
            "2024-12-25",  # Christmas
            "2024-12-26",  # Boxing Day
            "2024-01-01",  # New Year
        ]

        from verenigingen.utils.dutch_bank_calendar import is_dutch_banking_day

        # Test bank holiday detection
        for holiday in bank_holidays:
            with self.subTest(date=holiday):
                result = is_dutch_banking_day(holiday)
                self.assertFalse(result, f"Should not be a banking day: {holiday}")

        # Test normal business day
        business_day = "2024-03-15"  # Friday
        result = is_dutch_banking_day(business_day)
        self.assertTrue(result, f"Should be a banking day: {business_day}")

        # Test weekend
        weekend_day = "2024-03-16"  # Saturday
        result = is_dutch_banking_day(weekend_day)
        self.assertFalse(result, f"Should not be a banking day: {weekend_day}")


class TestBankIntegrationErrorHandling(EnhancedTestCase):
    """Test error handling and recovery in bank integration scenarios"""

    def setUp(self):
        super().setUp()
        self.test_company = self.create_test_company()

    def test_corrupted_bank_file_handling(self):
        """Test handling of corrupted or invalid bank statement files"""

        # Test various corrupted file scenarios
        corrupted_files = [
            "<?xml version='1.0'?><invalid>broken xml",  # Malformed XML
            "not xml at all",  # Non-XML content
            "",  # Empty file
            "<?xml version='1.0'?><Document>wrong schema</Document>"  # Wrong schema
        ]

        from verenigingen.utils.bank_integration import import_bank_statement

        for content in corrupted_files:
            with self.subTest(content=content[:20] + "..."):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
                    f.write(content)
                    f.flush()

                    result = import_bank_statement(f.name, "CAMT.053")

                    # Should handle gracefully without crashing
                    self.assertFalse(result["success"])
                    self.assertIn("error", result)
                    self.assertEqual(result["transactions_imported"], 0)

    def test_duplicate_payment_detection(self):
        """Test detection and handling of duplicate payment imports"""

        member = self.create_test_member(
            first_name="Duplicate",
            last_name="Test",
            email="duplicate@example.nl"
        )

        invoice = self.create_test_sales_invoice(
            customer=member.name,
            grand_total=75.00
        )

        # Create first payment entry
        payment1 = frappe.new_doc("Payment Entry")
        payment1.update({
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": member.name,
            "paid_amount": 75.00,
            "received_amount": 75.00,
            "reference_no": f"BANK_IMPORT_{invoice.name}",
            "reference_date": frappe.utils.today(),
            "company": self.test_company
        })
        payment1.insert()
        payment1.submit()

        # Attempt to create duplicate payment
        payment2 = frappe.new_doc("Payment Entry")
        payment2.update({
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": member.name,
            "paid_amount": 75.00,
            "received_amount": 75.00,
            "reference_no": f"BANK_IMPORT_{invoice.name}",  # Same reference
            "reference_date": frappe.utils.today(),
            "company": self.test_company
        })

        # Should detect duplicate and prevent creation
        with self.assertRaises(frappe.ValidationError):
            payment2.insert()

    def test_bank_api_timeout_and_retry_logic(self):
        """Test handling of bank API timeouts and connection issues"""

        with requests_mock.Mocker() as m:
            # Mock timeout scenarios
            m.get("https://api.bank.nl/statements",
                  exc=requests_mock.exceptions.ConnectTimeout)

            from verenigingen.utils.bank_integration import BankAPIClient

            client = BankAPIClient()

            # Test timeout handling
            result = client.fetch_statements("2024-03-15")

            # Should handle timeout gracefully
            self.assertFalse(result["success"])
            self.assertIn("timeout", result["error"].lower())

            # Test retry with successful response
            m.get("https://api.bank.nl/statements",
                  json={"statements": [], "status": "success"})

            retry_result = client.fetch_statements("2024-03-15")
            self.assertTrue(retry_result["success"])


class TestBankReconciliationReporting(EnhancedTestCase):
    """Test bank reconciliation reporting and audit trails"""

    def setUp(self):
        super().setUp()
        self.test_company = self.create_test_company()

    def test_reconciliation_report_generation(self):
        """Test generation of bank reconciliation reports for audit purposes"""

        # Create sample data for reconciliation report
        member = self.create_test_member(
            first_name="Report",
            last_name="Test",
            email="report@example.nl"
        )

        invoice = self.create_test_sales_invoice(
            customer=member.name,
            grand_total=100.00
        )

        # Create payment entry
        payment = frappe.new_doc("Payment Entry")
        payment.update({
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": member.name,
            "paid_amount": 100.00,
            "received_amount": 100.00,
            "reference_no": f"BANK_IMPORT_{invoice.name}",
            "reference_date": frappe.utils.today(),
            "company": self.test_company
        })
        payment.insert()
        payment.submit()

        # Generate reconciliation report
        from verenigingen.reports.bank_reconciliation_report.bank_reconciliation_report import execute

        filters = {
            "company": self.test_company,
            "from_date": frappe.utils.add_days(frappe.utils.today(), -30),
            "to_date": frappe.utils.today()
        }

        columns, data = execute(filters)

        # Verify report structure
        self.assertIsNotNone(columns)
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)

        # Verify payment appears in report
        payment_found = any(row for row in data if invoice.name in str(row))
        self.assertTrue(payment_found, "Payment should appear in reconciliation report")

    def test_unreconciled_transactions_identification(self):
        """Test identification of unreconciled bank transactions"""

        # Create unmatched bank import entry
        bank_transaction = frappe.new_doc("Bank Transaction")
        bank_transaction.update({
            "date": frappe.utils.today(),
            "description": "Unmatched payment from unknown source",
            "deposit": 150.00,
            "currency": "EUR",
            "bank_account": f"Bank Account - {self.test_company}",
            "company": self.test_company,
            "status": "Unreconciled"
        })
        bank_transaction.insert()

        # Test unreconciled transaction reporting
        from verenigingen.utils.bank_reconciliation import get_unreconciled_transactions

        unreconciled = get_unreconciled_transactions(self.test_company)

        # Verify unreconciled transaction detected
        self.assertGreater(len(unreconciled), 0)

        # Find our test transaction
        test_transaction = next((t for t in unreconciled
                               if t.get("amount") == 150.00), None)
        self.assertIsNotNone(test_transaction)
        self.assertEqual(test_transaction["status"], "Unreconciled")


if __name__ == "__main__":
    import unittest
    unittest.main()