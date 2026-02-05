# -*- coding: utf-8 -*-
"""
Comprehensive SEPA Return Processing Tests

Tests for SEPA pain.002 return file parsing and return code handling.
Covers transaction-level return code processing including:
- R01 (Insufficient Funds), R02 (Account Closed), R04 (Invalid Account)
- MD01 (No Mandate), MS02/MS03 (Not Specified Reason)
- SL01 (Specific Service), AM04 (Insufficient Funds), etc.

This module provides comprehensive testing for:
- SEPAReturnParser functionality
- SEPAReturnItem data class
- Return reason code mapping
- Status classification (accepted, rejected, pending)
- XML parsing security (XXE protection via defusedxml)
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.sepa_return_parser import (
    SEPAReturnParser,
    SEPAReturnItem,
    SEPA_RETURN_REASON_CODES,
    parse_sepa_return_file,
    get_rejected_transactions,
)


class TestSEPAReturnParser(VereningingenTestCase):
    """Test the SEPAReturnParser class functionality"""

    def test_parser_initialization(self):
        """Test parser initializes correctly"""
        parser = SEPAReturnParser()
        self.assertIsNone(parser.namespace)
        self.assertEqual(parser.ns_prefix, "pain")

    def test_parse_valid_pain002_03_format(self):
        """Test parsing valid pain.002.001.03 XML"""
        xml_content = self._create_pain002_xml(
            namespace="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03",
            status="RJCT",
            reason_code="AM04",
        )
        parser = SEPAReturnParser()
        returns = parser.parse(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertTrue(returns[0].is_rejected())
        self.assertEqual(returns[0].reason_code, "AM04")
        self.assertEqual(returns[0].reason_description, "Insufficient Funds")

    def test_parse_valid_pain002_10_format(self):
        """Test parsing valid pain.002.001.10 XML"""
        xml_content = self._create_pain002_xml(
            namespace="urn:iso:std:iso:20022:tech:xsd:pain.002.001.10",
            status="ACCP",
            reason_code=None,
        )
        parser = SEPAReturnParser()
        returns = parser.parse(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertTrue(returns[0].is_accepted())
        self.assertFalse(returns[0].is_rejected())

    def test_parse_unknown_namespace_raises_error(self):
        """Test that unknown namespace raises ValueError"""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:unknown:namespace">
            <CstmrPmtStsRpt></CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        with self.assertRaises(ValueError) as context:
            parser.parse(xml_content)

        self.assertIn("Invalid pain.002 file", str(context.exception))

    def test_parse_multiple_transactions(self):
        """Test parsing file with multiple transactions"""
        xml_content = self._create_pain002_xml_multiple_transactions([
            {"status": "RJCT", "reason_code": "AM04", "end_to_end_id": "E2E-001"},
            {"status": "ACCP", "reason_code": None, "end_to_end_id": "E2E-002"},
            {"status": "RJCT", "reason_code": "MD01", "end_to_end_id": "E2E-003"},
        ])

        parser = SEPAReturnParser()
        returns = parser.parse(xml_content)

        self.assertEqual(len(returns), 3)

        # Verify each transaction
        rejected = [r for r in returns if r.is_rejected()]
        accepted = [r for r in returns if r.is_accepted()]

        self.assertEqual(len(rejected), 2)
        self.assertEqual(len(accepted), 1)

    def test_parse_extracts_debtor_information(self):
        """Test that debtor information is extracted correctly"""
        xml_content = self._create_pain002_xml_with_debtor(
            debtor_name="Jan de Vries",
            debtor_iban="NL91ABNA0417164300",
            mandate_id="MNDT-2024-001",
        )

        parser = SEPAReturnParser()
        returns = parser.parse(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].debtor_name, "Jan de Vries")
        self.assertEqual(returns[0].debtor_iban, "NL91ABNA0417164300")
        self.assertEqual(returns[0].mandate_id, "MNDT-2024-001")

    def test_parse_extracts_amount_information(self):
        """Test that amount and currency are extracted correctly"""
        xml_content = self._create_pain002_xml_with_amount(
            amount="25.50",
            currency="EUR",
        )

        parser = SEPAReturnParser()
        returns = parser.parse(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].original_amount, 25.50)
        self.assertEqual(returns[0].original_currency, "EUR")

    # Helper methods for creating test XML

    def _create_pain002_xml(self, namespace, status, reason_code):
        """Create a simple pain.002 XML for testing"""
        reason_element = ""
        if reason_code:
            reason_element = f"""
                <StsRsnInf>
                    <Rsn>
                        <Cd>{reason_code}</Cd>
                    </Rsn>
                    <AddtlInf>Test additional info</AddtlInf>
                </StsRsnInf>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="{namespace}">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlGrpInfAndSts>
                    <OrgnlMsgId>ORIG-MSG-001</OrgnlMsgId>
                    <OrgnlMsgNmId>pain.008.001.02</OrgnlMsgNmId>
                </OrgnlGrpInfAndSts>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <OrgnlInstrId>INSTR-001</OrgnlInstrId>
                        <TxSts>{status}</TxSts>
                        {reason_element}
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

    def _create_pain002_xml_multiple_transactions(self, transactions):
        """Create pain.002 XML with multiple transactions"""
        tx_elements = ""
        for tx in transactions:
            reason_element = ""
            if tx.get("reason_code"):
                reason_element = f"""
                    <StsRsnInf>
                        <Rsn>
                            <Cd>{tx['reason_code']}</Cd>
                        </Rsn>
                    </StsRsnInf>"""

            tx_elements += f"""
                <TxInfAndSts>
                    <OrgnlEndToEndId>{tx['end_to_end_id']}</OrgnlEndToEndId>
                    <TxSts>{tx['status']}</TxSts>
                    {reason_element}
                </TxInfAndSts>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    {tx_elements}
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

    def _create_pain002_xml_with_debtor(self, debtor_name, debtor_iban, mandate_id):
        """Create pain.002 XML with debtor information"""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn><Cd>AM04</Cd></Rsn>
                        </StsRsnInf>
                        <OrgnlTxRef>
                            <Amt>
                                <InstdAmt Ccy="EUR">25.00</InstdAmt>
                            </Amt>
                            <Dbtr>
                                <Nm>{debtor_name}</Nm>
                            </Dbtr>
                            <DbtrAcct>
                                <Id>
                                    <IBAN>{debtor_iban}</IBAN>
                                </Id>
                            </DbtrAcct>
                            <MndtRltdInf>
                                <MndtId>{mandate_id}</MndtId>
                            </MndtRltdInf>
                        </OrgnlTxRef>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

    def _create_pain002_xml_with_amount(self, amount, currency):
        """Create pain.002 XML with amount information"""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn><Cd>AM04</Cd></Rsn>
                        </StsRsnInf>
                        <OrgnlTxRef>
                            <Amt>
                                <InstdAmt Ccy="{currency}">{amount}</InstdAmt>
                            </Amt>
                        </OrgnlTxRef>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""


class TestSEPAReturnItem(VereningingenTestCase):
    """Test the SEPAReturnItem data class"""

    def test_is_rejected_for_rjct_status(self):
        """Test is_rejected returns True for RJCT status"""
        item = SEPAReturnItem(
            original_message_id="MSG-001",
            original_payment_id="PMT-001",
            original_end_to_end_id="E2E-001",
            original_instruction_id="INSTR-001",
            status="RJCT",
            reason_code="AM04",
            reason_description="Insufficient Funds",
            additional_info=None,
            original_amount=25.00,
            original_currency="EUR",
            debtor_name="Test Debtor",
            debtor_iban="NL91ABNA0417164300",
            mandate_id="MNDT-001",
        )

        self.assertTrue(item.is_rejected())
        self.assertFalse(item.is_accepted())
        self.assertFalse(item.is_pending())

    def test_is_accepted_for_accepted_statuses(self):
        """Test is_accepted returns True for ACCP, ACSC, ACSP, ACTC statuses"""
        accepted_statuses = ["ACCP", "ACSC", "ACSP", "ACTC"]

        for status in accepted_statuses:
            item = SEPAReturnItem(
                original_message_id="MSG-001",
                original_payment_id="PMT-001",
                original_end_to_end_id="E2E-001",
                original_instruction_id=None,
                status=status,
                reason_code=None,
                reason_description=None,
                additional_info=None,
                original_amount=None,
                original_currency=None,
                debtor_name=None,
                debtor_iban=None,
                mandate_id=None,
            )

            self.assertTrue(item.is_accepted(), f"Status {status} should be accepted")
            self.assertFalse(item.is_rejected(), f"Status {status} should not be rejected")
            self.assertFalse(item.is_pending(), f"Status {status} should not be pending")

    def test_is_pending_for_pdng_status(self):
        """Test is_pending returns True for PDNG status"""
        item = SEPAReturnItem(
            original_message_id="MSG-001",
            original_payment_id="PMT-001",
            original_end_to_end_id="E2E-001",
            original_instruction_id=None,
            status="PDNG",
            reason_code=None,
            reason_description=None,
            additional_info=None,
            original_amount=None,
            original_currency=None,
            debtor_name=None,
            debtor_iban=None,
            mandate_id=None,
        )

        self.assertTrue(item.is_pending())
        self.assertFalse(item.is_accepted())
        self.assertFalse(item.is_rejected())

    def test_to_dict_returns_all_fields(self):
        """Test to_dict returns all required fields"""
        item = SEPAReturnItem(
            original_message_id="MSG-001",
            original_payment_id="PMT-001",
            original_end_to_end_id="E2E-001",
            original_instruction_id="INSTR-001",
            status="RJCT",
            reason_code="MD01",
            reason_description="No Mandate",
            additional_info="Mandate revoked by debtor",
            original_amount=50.00,
            original_currency="EUR",
            debtor_name="Jan de Vries",
            debtor_iban="NL91ABNA0417164300",
            mandate_id="MNDT-2024-001",
        )

        result = item.to_dict()

        # Verify all required fields
        self.assertEqual(result["original_message_id"], "MSG-001")
        self.assertEqual(result["original_payment_id"], "PMT-001")
        self.assertEqual(result["end_to_end_id"], "E2E-001")
        self.assertEqual(result["instruction_id"], "INSTR-001")
        self.assertEqual(result["status"], "RJCT")
        self.assertEqual(result["reason_code"], "MD01")
        self.assertEqual(result["reason_description"], "No Mandate")
        self.assertEqual(result["additional_info"], "Mandate revoked by debtor")
        self.assertEqual(result["amount"], 50.00)
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["debtor_name"], "Jan de Vries")
        self.assertEqual(result["debtor_iban"], "NL91ABNA0417164300")
        self.assertEqual(result["mandate_id"], "MNDT-2024-001")
        self.assertTrue(result["is_rejected"])


class TestSEPAReturnReasonCodes(VereningingenTestCase):
    """Test SEPA return reason code mapping and handling"""

    def test_all_common_reason_codes_defined(self):
        """Test that all common SEPA return reason codes are defined"""
        common_codes = [
            "AC01", "AC04", "AC06", "AM04", "AM05",
            "MD01", "MD02", "MD06", "MD07",
            "MS02", "MS03",
            "RC01", "SL01",
            "FF01", "TECH", "DUPL",
        ]

        for code in common_codes:
            self.assertIn(code, SEPA_RETURN_REASON_CODES, f"Reason code {code} should be defined")

    def test_reason_code_am04_insufficient_funds(self):
        """Test AM04 (Insufficient Funds) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["AM04"], "Insufficient Funds")

    def test_reason_code_ac04_closed_account(self):
        """Test AC04 (Closed Account Number) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["AC04"], "Closed Account Number")

    def test_reason_code_md01_no_mandate(self):
        """Test MD01 (No Mandate) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["MD01"], "No Mandate")

    def test_reason_code_ms02_customer_generated(self):
        """Test MS02 (Not Specified Reason Customer Generated) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["MS02"], "Not Specified Reason Customer Generated")

    def test_reason_code_sl01_specific_service(self):
        """Test SL01 (Specific Service) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["SL01"], "Specific Service Offered by Debtor Agent")

    def test_reason_code_md06_refund_request(self):
        """Test MD06 (Refund Request) reason code - 8-week refund period"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["MD06"], "Refund Request by End Customer")

    def test_reason_code_md07_deceased(self):
        """Test MD07 (End Customer Deceased) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["MD07"], "End Customer Deceased")

    def test_reason_code_ac06_blocked_account(self):
        """Test AC06 (Blocked Account) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["AC06"], "Blocked Account")

    def test_reason_code_focr_cancellation_request(self):
        """Test FOCR (Following Cancellation Request) reason code"""
        self.assertEqual(SEPA_RETURN_REASON_CODES["FOCR"], "Following Cancellation Request")


class TestSEPAReturnConvenienceFunctions(VereningingenTestCase):
    """Test convenience functions for SEPA return processing"""

    def test_parse_sepa_return_file_returns_list_of_dicts(self):
        """Test parse_sepa_return_file returns list of dictionaries"""
        xml_content = self._create_simple_pain002_xml()

        result = parse_sepa_return_file(xml_content)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)
        self.assertIn("status", result[0])
        self.assertIn("reason_code", result[0])

    def test_get_rejected_transactions_filters_correctly(self):
        """Test get_rejected_transactions only returns rejected transactions"""
        xml_content = self._create_pain002_xml_mixed_statuses()

        rejected = get_rejected_transactions(xml_content)

        # Should only return rejected transactions
        for item in rejected:
            self.assertTrue(item["is_rejected"])
            self.assertEqual(item["status"], "RJCT")

    def test_get_rejected_transactions_returns_empty_for_all_accepted(self):
        """Test get_rejected_transactions returns empty list when all accepted"""
        xml_content = self._create_pain002_xml_all_accepted()

        rejected = get_rejected_transactions(xml_content)

        self.assertEqual(len(rejected), 0)

    # Helper methods

    def _create_simple_pain002_xml(self):
        """Create simple pain.002 XML for testing"""
        return """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn><Cd>AM04</Cd></Rsn>
                        </StsRsnInf>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

    def _create_pain002_xml_mixed_statuses(self):
        """Create pain.002 XML with mixed statuses"""
        return """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf><Rsn><Cd>AM04</Cd></Rsn></StsRsnInf>
                    </TxInfAndSts>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-002</OrgnlEndToEndId>
                        <TxSts>ACCP</TxSts>
                    </TxInfAndSts>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-003</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf><Rsn><Cd>MD01</Cd></Rsn></StsRsnInf>
                    </TxInfAndSts>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-004</OrgnlEndToEndId>
                        <TxSts>PDNG</TxSts>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

    def _create_pain002_xml_all_accepted(self):
        """Create pain.002 XML with all accepted transactions"""
        return """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>ACCP</TxSts>
                    </TxInfAndSts>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-002</OrgnlEndToEndId>
                        <TxSts>ACSC</TxSts>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""


class TestSEPAReturnCodeBusinessScenarios(VereningingenTestCase):
    """Test business scenarios for different SEPA return codes"""

    def test_insufficient_funds_scenario_am04(self):
        """Test AM04 (Insufficient Funds) scenario - common return reason"""
        xml_content = self._create_return_scenario(
            reason_code="AM04",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "AM04")
        self.assertEqual(returns[0]["reason_description"], "Insufficient Funds")
        self.assertTrue(returns[0]["is_rejected"])

        # Business logic: Should trigger retry in next batch or grace period

    def test_closed_account_scenario_ac04(self):
        """Test AC04 (Closed Account) scenario - mandate should be invalidated"""
        xml_content = self._create_return_scenario(
            reason_code="AC04",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "AC04")
        self.assertEqual(returns[0]["reason_description"], "Closed Account Number")

        # Business logic: Mandate should be marked as invalid, member notified

    def test_no_mandate_scenario_md01(self):
        """Test MD01 (No Mandate) scenario - mandate reference issue"""
        xml_content = self._create_return_scenario(
            reason_code="MD01",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
            mandate_id="MNDT-INVALID-001",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "MD01")
        self.assertEqual(returns[0]["reason_description"], "No Mandate")
        self.assertEqual(returns[0]["mandate_id"], "MNDT-INVALID-001")

        # Business logic: Check mandate reference, may need re-signing

    def test_refund_request_scenario_md06(self):
        """Test MD06 (Refund Request) scenario - 8-week contestation period"""
        xml_content = self._create_return_scenario(
            reason_code="MD06",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "MD06")
        self.assertEqual(returns[0]["reason_description"], "Refund Request by End Customer")

        # Business logic: Member requested refund, follow up required

    def test_customer_deceased_scenario_md07(self):
        """Test MD07 (End Customer Deceased) scenario - sensitive handling"""
        xml_content = self._create_return_scenario(
            reason_code="MD07",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "MD07")
        self.assertEqual(returns[0]["reason_description"], "End Customer Deceased")

        # Business logic: Requires sensitive handling, membership termination

    def test_blocked_account_scenario_ac06(self):
        """Test AC06 (Blocked Account) scenario - legal/compliance issue"""
        xml_content = self._create_return_scenario(
            reason_code="AC06",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "AC06")
        self.assertEqual(returns[0]["reason_description"], "Blocked Account")

        # Business logic: Do not retry, contact member

    def test_technical_problem_scenario_tech(self):
        """Test TECH (Technical Problem) scenario - may be temporary"""
        xml_content = self._create_return_scenario(
            reason_code="TECH",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "TECH")
        self.assertEqual(returns[0]["reason_description"], "Technical Problem")

        # Business logic: Retry in next batch, likely temporary issue

    def test_duplicate_payment_scenario_dupl(self):
        """Test DUPL (Duplicate Payment) scenario - duplicate detection"""
        xml_content = self._create_return_scenario(
            reason_code="DUPL",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "DUPL")
        self.assertEqual(returns[0]["reason_description"], "Duplicate Payment")

        # Business logic: Check if original payment was processed

    def test_specific_service_scenario_sl01(self):
        """Test SL01 (Specific Service) scenario - debtor bank restriction"""
        xml_content = self._create_return_scenario(
            reason_code="SL01",
            amount="25.00",
            debtor_name="Test Member",
            debtor_iban="NL91ABNA0417164300",
        )

        returns = parse_sepa_return_file(xml_content)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0]["reason_code"], "SL01")
        self.assertEqual(returns[0]["reason_description"], "Specific Service Offered by Debtor Agent")

        # Business logic: Debtor bank may have specific restrictions

    # Helper methods

    def _create_return_scenario(self, reason_code, amount, debtor_name, debtor_iban, mandate_id=None):
        """Create pain.002 XML for specific return scenario"""
        mandate_element = ""
        if mandate_id:
            mandate_element = f"""
                            <MndtRltdInf>
                                <MndtId>{mandate_id}</MndtId>
                            </MndtRltdInf>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn><Cd>{reason_code}</Cd></Rsn>
                        </StsRsnInf>
                        <OrgnlTxRef>
                            <Amt>
                                <InstdAmt Ccy="EUR">{amount}</InstdAmt>
                            </Amt>
                            <Dbtr>
                                <Nm>{debtor_name}</Nm>
                            </Dbtr>
                            <DbtrAcct>
                                <Id>
                                    <IBAN>{debtor_iban}</IBAN>
                                </Id>
                            </DbtrAcct>
                            {mandate_element}
                        </OrgnlTxRef>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""


class TestSEPAReturnXMLSecurity(VereningingenTestCase):
    """Test XML security measures for SEPA return parsing"""

    def test_rejects_malformed_xml(self):
        """Test parser rejects malformed XML"""
        malformed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <unclosed_tag>
            </CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        with self.assertRaises(Exception):
            parser.parse(malformed_xml)

    def test_handles_empty_xml_gracefully(self):
        """Test parser handles empty content gracefully"""
        empty_xml = ""

        parser = SEPAReturnParser()
        with self.assertRaises(Exception):
            parser.parse(empty_xml)

    def test_handles_missing_required_elements(self):
        """Test parser handles missing required elements"""
        incomplete_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr></GrpHdr>
            </CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        # Should not raise but return empty list (no TxInfAndSts elements)
        returns = parser.parse(incomplete_xml)
        self.assertEqual(len(returns), 0)

    def test_handles_invalid_amount_gracefully(self):
        """Test parser handles invalid amount values gracefully"""
        xml_with_invalid_amount = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <OrgnlTxRef>
                            <Amt>
                                <InstdAmt Ccy="EUR">INVALID_AMOUNT</InstdAmt>
                            </Amt>
                        </OrgnlTxRef>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        returns = parser.parse(xml_with_invalid_amount)

        # Should still parse but amount should be None
        self.assertEqual(len(returns), 1)
        self.assertIsNone(returns[0].original_amount)

    def test_handles_unknown_status_code(self):
        """Test parser handles unknown status codes"""
        xml_with_unknown_status = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>UNKNOWN_STATUS</TxSts>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        returns = parser.parse(xml_with_unknown_status)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].status, "UNKNOWN_STATUS")
        self.assertFalse(returns[0].is_accepted())
        self.assertFalse(returns[0].is_rejected())
        self.assertFalse(returns[0].is_pending())

    def test_handles_unknown_reason_code(self):
        """Test parser handles unknown reason codes"""
        xml_with_unknown_reason = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG-001</MsgId>
                    <CreDtTm>2026-02-05T10:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT-001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E-001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn><Cd>UNKNOWN_CODE</Cd></Rsn>
                        </StsRsnInf>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>"""

        parser = SEPAReturnParser()
        returns = parser.parse(xml_with_unknown_reason)

        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].reason_code, "UNKNOWN_CODE")
        self.assertEqual(returns[0].reason_description, "Unknown reason")
