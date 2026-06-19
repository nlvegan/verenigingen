"""
Real-integration unit tests for
verenigingen/verenigingen_payments/utils/sepa_xml_enhanced_generator.py

This file complements the existing happy-path coverage in
``verenigingen/tests/sepa/test_sepa_week3_features.py`` (which already covers a
single successful ``generate_sepa_xml`` call plus one over-long-message-id
failure) by exercising the UNcovered branches:

  * every individual validation-failure path (creditor IBAN/BIC/id, debtor,
    mandate, transaction amount/currency/remittance, sequence-type mismatch,
    bad characters, empty payment-infos, empty transactions),
  * the validation-WARNING paths (past collection date, future mandate
    signature, >99 payment-info blocks) which do not raise,
  * the optional XML-emission branches (postal address, amendment indicator
    with original creditor scheme id + original debtor agent, purpose code,
    BIC derived from IBAN, debtor with no derivable BIC),
  * the module-level factory / helper functions
    (``create_sepa_transaction_from_invoice``, ``_resolve_batch_sequence_type``,
    ``_resolve_batch_local_instrument``),
  * the whitelisted API surface ``generate_enhanced_sepa_xml`` (driven through a
    REAL ``Direct Debit Batch`` built via SEPATestDataFactory) and
    ``validate_sepa_xml_compliance``.

The generator is essentially pure XML construction over dataclasses, so most
assertions parse the produced XML with ElementTree and assert real structure
(tags / text / attributes). No business logic is mocked.
"""

import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.utils.error_handling import SEPAError
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import (
    EnhancedSEPAXMLGenerator,
    SEPACreditor,
    SEPADebtor,
    SEPALocalInstrument,
    SEPAMandate,
    SEPAPaymentInfo,
    SEPASequenceType,
    SEPATransaction,
    _resolve_batch_local_instrument,
    _resolve_batch_sequence_type,
    create_sepa_transaction_from_invoice,
    generate_enhanced_sepa_xml,
    validate_sepa_xml_compliance,
)

NS = {"sepa": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"}

# Real, checksum-valid Dutch IBANs (validate_iban / derive_bic_from_iban work).
CREDITOR_IBAN = "NL91ABNA0417164300"  # ABNA -> ABNANL2A
DEBTOR_IBAN = "NL71INGB0012345678"  # INGB -> INGBNL2A
DEBTOR_IBAN_NO_BIC = "NL18RABO0123459876"  # RABO -> RABONL2U (derivable)


def _creditor(**overrides):
    base = dict(
        name="Test Vereniging",
        iban=CREDITOR_IBAN,
        bic="ABNANL2A",
        creditor_id="NL13ZZZ123456780000",
    )
    base.update(overrides)
    return SEPACreditor(**base)


def _debtor(**overrides):
    base = dict(name="Jan de Vries", iban=DEBTOR_IBAN, bic="INGBNL2A")
    base.update(overrides)
    return SEPADebtor(**base)


def _mandate(**overrides):
    base = dict(mandate_id="MAND-001", date_of_signature=date(2024, 1, 15))
    base.update(overrides)
    return SEPAMandate(**base)


def _transaction(**overrides):
    base = dict(
        end_to_end_id="E2E-001",
        amount=Decimal("100.50"),
        currency="EUR",
        debtor=_debtor(),
        mandate=_mandate(),
        remittance_info="Membership fee 2024",
        sequence_type=SEPASequenceType.RCUR,
    )
    base.update(overrides)
    return SEPATransaction(**base)


def _payment_info(transactions=None, **overrides):
    base = dict(
        payment_info_id="PMT-001",
        payment_method="DD",
        batch_booking=True,
        requested_collection_date=date(2024, 12, 31),
        creditor=_creditor(),
        local_instrument=SEPALocalInstrument.CORE,
        sequence_type=SEPASequenceType.RCUR,
        transactions=transactions if transactions is not None else [_transaction()],
    )
    base.update(overrides)
    return SEPAPaymentInfo(**base)


class TestEnhancedSEPAXMLValidationFailures(unittest.TestCase):
    """Each test drives one validation-error branch -> ValidationError wrapped in SEPAError."""

    def setUp(self):
        self.gen = EnhancedSEPAXMLGenerator()

    def _generate(self, payment_infos, message_id="MSG-001", party="Test Vereniging"):
        return self.gen.generate_sepa_xml(
            message_id=message_id,
            creation_datetime=datetime(2024, 1, 1, 10, 0, 0),
            payment_infos=payment_infos,
            initiating_party_name=party,
        )

    def assertValidationErrorContains(self, fragment, payment_infos, **kw):
        with self.assertRaises(SEPAError):
            self._generate(payment_infos, **kw)
        joined = "; ".join(self.gen.validation_errors)
        self.assertIn(fragment, joined, f"Expected '{fragment}' in errors: {joined}")

    def test_empty_payment_infos_required(self):
        self.assertValidationErrorContains("At least one payment info block is required", [])

    def test_empty_message_id(self):
        self.assertValidationErrorContains("Message ID must be 1-", [_payment_info()], message_id="")

    def test_message_id_invalid_characters(self):
        # '@' is outside the SEPA character set.
        self.assertValidationErrorContains(
            "Message ID contains invalid characters", [_payment_info()], message_id="MSG@001"
        )

    def test_initiating_party_invalid_characters(self):
        self.assertValidationErrorContains(
            "Initiating party name contains invalid characters",
            [_payment_info()],
            party="Bad@Name",
        )

    def test_creditor_invalid_iban(self):
        pi = _payment_info()
        pi.creditor.iban = "NL00BANK0000000000"  # bad checksum
        self.assertValidationErrorContains("Invalid creditor IBAN", [pi])

    def test_creditor_invalid_bic(self):
        pi = _payment_info()
        pi.creditor.bic = "SHORT"  # not 8/11 chars
        self.assertValidationErrorContains("Invalid creditor BIC format", [pi])

    def test_creditor_missing_creditor_id(self):
        pi = _payment_info()
        pi.creditor.creditor_id = ""
        self.assertValidationErrorContains("Invalid creditor ID", [pi])

    def test_creditor_address_line_too_long(self):
        pi = _payment_info()
        pi.creditor.address_line_1 = "X" * 200
        self.assertValidationErrorContains("Creditor address line 1 too long", [pi])

    def test_transaction_non_positive_amount(self):
        pi = _payment_info(transactions=[_transaction(amount=Decimal("0"))])
        self.assertValidationErrorContains("Amount must be positive", [pi])

    def test_transaction_amount_exceeds_max(self):
        pi = _payment_info(transactions=[_transaction(amount=Decimal("1000000000.00"))])
        self.assertValidationErrorContains("Amount exceeds maximum allowed", [pi])

    def test_transaction_non_eur_currency(self):
        pi = _payment_info(transactions=[_transaction(currency="USD")])
        self.assertValidationErrorContains("Only EUR currency is supported", [pi])

    def test_transaction_remittance_too_long(self):
        pi = _payment_info(transactions=[_transaction(remittance_info="A" * 200)])
        self.assertValidationErrorContains("Remittance info exceeds", [pi])

    def test_transaction_remittance_invalid_chars(self):
        pi = _payment_info(transactions=[_transaction(remittance_info="Bad@Info")])
        self.assertValidationErrorContains("Remittance info contains invalid characters", [pi])

    def test_debtor_invalid_iban(self):
        bad_debtor = _debtor(iban="NL00BANK0000000000")
        pi = _payment_info(transactions=[_transaction(debtor=bad_debtor)])
        self.assertValidationErrorContains("Invalid debtor IBAN", [pi])

    def test_debtor_invalid_bic_when_provided(self):
        bad_debtor = _debtor(bic="BADBIC")
        pi = _payment_info(transactions=[_transaction(debtor=bad_debtor)])
        self.assertValidationErrorContains("Invalid debtor BIC format", [pi])

    def test_mandate_id_too_long(self):
        m = _mandate(mandate_id="M" * 40)
        pi = _payment_info(transactions=[_transaction(mandate=m)])
        self.assertValidationErrorContains("Mandate ID must be 1-", [pi])

    def test_mandate_amendment_without_original(self):
        m = _mandate(amendment_indicator=True, original_mandate_id=None)
        pi = _payment_info(transactions=[_transaction(mandate=m)])
        self.assertValidationErrorContains("Original mandate ID required for amendments", [pi])

    def test_empty_transactions_required(self):
        pi = _payment_info(transactions=[])
        self.assertValidationErrorContains("At least one transaction is required", [pi])

    def test_sequence_type_mismatch(self):
        # Payment info says RCUR, transaction says FRST -> inconsistency error.
        tx = _transaction(sequence_type=SEPASequenceType.FRST)
        pi = _payment_info(transactions=[tx])  # pi.sequence_type stays RCUR
        self.assertValidationErrorContains("Sequence type mismatch", [pi])

    def test_payment_info_id_too_long(self):
        pi = _payment_info(payment_info_id="P" * 40)
        self.assertValidationErrorContains("Payment Info ID must be 1-", [pi])


class TestEnhancedSEPAXMLWarnings(unittest.TestCase):
    """Warning branches do NOT raise; XML is still produced and warnings recorded."""

    def setUp(self):
        self.gen = EnhancedSEPAXMLGenerator()

    def _generate(self, payment_infos):
        return self.gen.generate_sepa_xml(
            message_id="MSG-WARN",
            creation_datetime=datetime(2024, 1, 1, 10, 0, 0),
            payment_infos=payment_infos,
            initiating_party_name="Test Vereniging",
        )

    def test_past_collection_date_warns_but_succeeds(self):
        pi = _payment_info(requested_collection_date=date(2020, 1, 1))
        xml = self._generate([pi])
        self.assertIn("CstmrDrctDbtInitn", xml)
        warnings = self.gen.get_validation_results()["warnings"]
        self.assertTrue(any("Collection date is in the past" in w for w in warnings))

    def test_future_mandate_signature_warns(self):
        future = date.today() + timedelta(days=365)
        m = _mandate(date_of_signature=future)
        pi = _payment_info(transactions=[_transaction(mandate=m)])
        self._generate([pi])
        warnings = self.gen.get_validation_results()["warnings"]
        self.assertTrue(any("Mandate signature date is in the future" in w for w in warnings))

    def test_many_payment_info_blocks_warns(self):
        # 100 blocks (>99) triggers the "large number" warning but still validates.
        blocks = [_payment_info(payment_info_id=f"PMT-{i:03d}") for i in range(100)]
        self._generate(blocks)
        warnings = self.gen.get_validation_results()["warnings"]
        self.assertTrue(any("Large number of payment info blocks" in w for w in warnings))


class TestEnhancedSEPAXMLEmission(unittest.TestCase):
    """Optional XML-emission branches: address, amendment, purpose, derived BIC."""

    def setUp(self):
        self.gen = EnhancedSEPAXMLGenerator()

    def _generate(self, payment_infos):
        return self.gen.generate_sepa_xml(
            message_id="MSG-EMIT",
            creation_datetime=datetime(2024, 3, 15, 9, 30, 0),
            payment_infos=payment_infos,
            initiating_party_name="Test Vereniging",
        )

    def _root(self, xml):
        return ET.fromstring(xml)

    def test_creditor_and_debtor_address_emitted(self):
        creditor = _creditor(
            address_line_1="Hoofdstraat 1",
            address_line_2="Unit B",
            postal_code="1011AB",
            town="Amsterdam",
        )
        debtor = _debtor(
            address_line_1="Kerkstraat 5",
            postal_code="3500CD",
            town="Utrecht",
        )
        pi = _payment_info(transactions=[_transaction(debtor=debtor)], creditor=creditor)
        root = self._root(self._generate([pi]))

        # Creditor postal address
        cdtr = root.find(".//sepa:Cdtr", NS)
        self.assertIsNotNone(cdtr.find("sepa:PstlAdr", NS))
        adr_lines = [e.text for e in cdtr.findall("sepa:PstlAdr/sepa:AdrLine", NS)]
        self.assertIn("Hoofdstraat 1", adr_lines)
        self.assertIn("Unit B", adr_lines)
        self.assertEqual(cdtr.find("sepa:PstlAdr/sepa:TwnNm", NS).text, "Amsterdam")
        self.assertEqual(cdtr.find("sepa:PstlAdr/sepa:PstCd", NS).text, "1011AB")

        # Debtor postal address
        dbtr = root.find(".//sepa:Dbtr", NS)
        self.assertEqual(dbtr.find("sepa:PstlAdr/sepa:TwnNm", NS).text, "Utrecht")

    def test_amendment_indicator_full_details(self):
        m = _mandate(
            amendment_indicator=True,
            original_mandate_id="OLD-MAND-001",
            original_creditor_id="NL00ZZZ000000000000",
            original_debtor_agent="RABONL2U",
        )
        pi = _payment_info(transactions=[_transaction(mandate=m)])
        root = self._root(self._generate([pi]))

        amdmnt = root.find(".//sepa:MndtRltdInf/sepa:AmdmntInfDtls", NS)
        self.assertIsNotNone(amdmnt)
        self.assertEqual(root.find(".//sepa:MndtRltdInf/sepa:AmdmntInd", NS).text, "true")
        self.assertEqual(amdmnt.find("sepa:OrgnlMndtId", NS).text, "OLD-MAND-001")
        # Original creditor scheme id
        orig_cdtr_id = amdmnt.find("sepa:OrgnlCdtrSchmeId/sepa:Id/sepa:PrvtId/sepa:Othr/sepa:Id", NS)
        self.assertEqual(orig_cdtr_id.text, "NL00ZZZ000000000000")
        # Original debtor agent BIC
        orig_agt = amdmnt.find("sepa:OrgnlDbtrAgt/sepa:FinInstnId/sepa:BIC", NS)
        self.assertEqual(orig_agt.text, "RABONL2U")

    def test_purpose_code_emitted(self):
        tx = _transaction(purpose_code="OTHR")
        pi = _payment_info(transactions=[tx])
        root = self._root(self._generate([pi]))
        purp = root.find(".//sepa:DrctDbtTxInf/sepa:Purp/sepa:Cd", NS)
        self.assertIsNotNone(purp)
        self.assertEqual(purp.text, "OTHR")
        # Also emitted as CdtrRef inside DrctDbtTx
        cdtr_ref = root.find(".//sepa:DrctDbtTx/sepa:CdtrRef/sepa:Tp", NS)
        self.assertEqual(cdtr_ref.text, "OTHR")

    def test_debtor_bic_derived_from_iban_when_missing(self):
        # Debtor has no BIC but a RABO IBAN -> derive_bic_from_iban yields RABONL2U.
        debtor = _debtor(iban=DEBTOR_IBAN_NO_BIC, bic=None)
        pi = _payment_info(transactions=[_transaction(debtor=debtor)])
        root = self._root(self._generate([pi]))
        dbtr_agt = root.find(".//sepa:DbtrAgt/sepa:FinInstnId/sepa:BIC", NS)
        self.assertIsNotNone(dbtr_agt, "DbtrAgt BIC should be derived from IBAN")
        self.assertEqual(dbtr_agt.text, "RABONL2U")

    def test_control_sums_and_counts(self):
        txs = [
            _transaction(end_to_end_id="E2E-A", amount=Decimal("100.00")),
            _transaction(end_to_end_id="E2E-B", amount=Decimal("50.25")),
        ]
        pi = _payment_info(transactions=txs)
        root = self._root(self._generate([pi]))
        # Group header totals
        self.assertEqual(root.find(".//sepa:GrpHdr/sepa:NbOfTxs", NS).text, "2")
        self.assertEqual(root.find(".//sepa:GrpHdr/sepa:CtrlSum", NS).text, "150.25")
        # Payment info totals
        self.assertEqual(root.find(".//sepa:PmtInf/sepa:NbOfTxs", NS).text, "2")
        self.assertEqual(root.find(".//sepa:PmtInf/sepa:CtrlSum", NS).text, "150.25")
        # Sequence type & local instrument
        self.assertEqual(root.find(".//sepa:PmtTpInf/sepa:SeqTp", NS).text, "RCUR")
        self.assertEqual(root.find(".//sepa:PmtTpInf/sepa:LclInstrm/sepa:Cd", NS).text, "CORE")

    def test_batch_booking_false_emitted(self):
        pi = _payment_info(batch_booking=False)
        root = self._root(self._generate([pi]))
        self.assertEqual(root.find(".//sepa:PmtInf/sepa:BtchBookg", NS).text, "false")


class TestBicValidation(unittest.TestCase):
    """Direct coverage of the _validate_bic helper edge cases."""

    def setUp(self):
        self.gen = EnhancedSEPAXMLGenerator()

    def test_empty_bic_invalid(self):
        self.assertFalse(self.gen._validate_bic(""))

    def test_wrong_length_invalid(self):
        self.assertFalse(self.gen._validate_bic("ABCDEFGHI"))  # 9 chars

    def test_eight_char_valid(self):
        self.assertTrue(self.gen._validate_bic("ABNANL2A"))

    def test_eleven_char_valid(self):
        self.assertTrue(self.gen._validate_bic("ABNANL2AXXX"))

    def test_lowercase_normalised_and_valid(self):
        self.assertTrue(self.gen._validate_bic("abnanl2a"))


class TestSEPAFactoryHelpers(unittest.TestCase):
    """Module-level factory / resolution helpers."""

    def test_create_sepa_transaction_from_invoice(self):
        tx = create_sepa_transaction_from_invoice(
            {
                "invoice": "INV-2024-001",
                "amount": "42.50",
                "currency": "EUR",
                "member_name": "Piet Klaassen",
                "iban": DEBTOR_IBAN,
                "bic": "INGBNL2A",
                "mandate_reference": "MAND-XYZ",
                "mandate_date": "2024-02-01",
            },
            SEPASequenceType.FRST,
        )
        self.assertEqual(tx.end_to_end_id, "E2E-INV-2024-001")
        self.assertEqual(tx.amount, Decimal("42.50"))
        self.assertEqual(tx.debtor.name, "Piet Klaassen")
        self.assertEqual(tx.mandate.mandate_id, "MAND-XYZ")
        self.assertEqual(tx.mandate.date_of_signature, date(2024, 2, 1))
        self.assertEqual(tx.sequence_type, SEPASequenceType.FRST)

    def test_create_sepa_transaction_from_invoice_defaults(self):
        # Missing fields fall back to defaults (amount 0, today() mandate date).
        tx = create_sepa_transaction_from_invoice({}, SEPASequenceType.RCUR)
        self.assertEqual(tx.amount, Decimal("0"))
        self.assertEqual(tx.currency, "EUR")
        self.assertEqual(tx.debtor.name, "Unknown")

    def test_resolve_batch_sequence_type_from_sequence_field(self):
        self.assertEqual(_resolve_batch_sequence_type({"sequence_type": "FRST"}), SEPASequenceType.FRST)

    def test_resolve_batch_sequence_type_legacy_batch_type_fallback(self):
        # Pre-split batches stored the sequence in batch_type.
        self.assertEqual(
            _resolve_batch_sequence_type({"sequence_type": None, "batch_type": "FNAL"}),
            SEPASequenceType.FNAL,
        )

    def test_resolve_batch_sequence_type_defaults_rcur(self):
        # batch_type holding a scheme value (CORE) is not a sequence -> default RCUR.
        self.assertEqual(_resolve_batch_sequence_type({"batch_type": "CORE"}), SEPASequenceType.RCUR)

    def test_resolve_batch_local_instrument_from_batch_type(self):
        self.assertEqual(_resolve_batch_local_instrument({"batch_type": "B2B"}), SEPALocalInstrument.B2B)

    def test_resolve_batch_local_instrument_defaults_core(self):
        # A sequence value (RCUR) in batch_type has no scheme meaning -> CORE.
        self.assertEqual(_resolve_batch_local_instrument({"batch_type": "RCUR"}), SEPALocalInstrument.CORE)


class TestValidateSepaXmlCompliance(unittest.TestCase):
    """Coverage of the validate_sepa_xml_compliance whitelisted API."""

    def _make_valid_xml(self):
        gen = EnhancedSEPAXMLGenerator()
        return gen.generate_sepa_xml(
            message_id="MSG-COMP",
            creation_datetime=datetime(2024, 1, 1, 10, 0, 0),
            payment_infos=[_payment_info()],
            initiating_party_name="Test Vereniging",
        )

    def test_valid_xml_scores_full(self):
        result = validate_sepa_xml_compliance(self._make_valid_xml())
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["compliance_score"], 100)
        self.assertEqual(result["errors"], [])

    def test_wrong_namespace_flagged(self):
        bad = (
            '<Document xmlns="urn:wrong:namespace">'
            "<CstmrDrctDbtInitn><GrpHdr/><PmtInf/></CstmrDrctDbtInitn></Document>"
        )
        result = validate_sepa_xml_compliance(bad)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("namespace" in e for e in result["errors"]))
        self.assertLess(result["compliance_score"], 100)

    def test_parse_error_returns_zero(self):
        result = validate_sepa_xml_compliance("<not-valid-xml><<<")
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["compliance_score"], 0)
        self.assertTrue(any("parsing error" in e for e in result["errors"]))


class TestGenerateEnhancedSepaXMLIntegration(EnhancedTestCase):
    """
    Integration coverage of generate_enhanced_sepa_xml(batch_name) driving a
    REAL Direct Debit Batch document through the full generator pipeline.

    The generator only reads ``batch.invoices`` rows, so we build a minimal
    batch with a synthetic invoice row directly (no submitted Sales Invoice
    required) to keep the test fast and deterministic.
    """

    def setUp(self):
        super().setUp()
        # The generator builds its creditor from Verenigingen Payments Settings
        # (company IBAN/BIC/creditor_id/account_holder). We do NOT mutate that
        # shared Single; if it is not configured on this site, skip the
        # integration test rather than poison global state.
        settings = frappe.get_single("Verenigingen Payments Settings")
        if not (settings.company_iban and settings.creditor_id and settings.company_account_holder):
            self.skipTest("Verenigingen Payments Settings not configured with a SEPA creditor")
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    def test_generate_enhanced_sepa_xml_real_batch(self):
        # The factory builds a REAL batch with real submitted Sales Invoices and
        # SEPA mandates (the Direct Debit Batch validates the invoice Link), with
        # CORE scheme / FRST sequence (first use of fresh mandates).
        batch = self.sepa.create_test_direct_debit_batch(invoice_count=2)
        first_invoice = batch.invoices[0].invoice
        expected_total = sum(row.amount for row in batch.invoices)

        result = generate_enhanced_sepa_xml(batch.name)

        self.assertTrue(result["success"], f"generation failed: {result.get('error')}")
        self.assertIsNotNone(result["xml_content"])
        self.assertEqual(result["statistics"]["transactions"], 2)
        self.assertAlmostEqual(result["statistics"]["total_amount"], float(expected_total))

        root = ET.fromstring(result["xml_content"])
        # SeqTp comes from the batch sequence_type (FRST), LclInstrm from scheme.
        self.assertEqual(root.find(".//sepa:PmtTpInf/sepa:SeqTp", NS).text, "FRST")
        self.assertEqual(root.find(".//sepa:PmtTpInf/sepa:LclInstrm/sepa:Cd", NS).text, "CORE")
        # End-to-end id derives from invoice name with E2E- prefix.
        e2e_ids = [e.text for e in root.findall(".//sepa:PmtId/sepa:EndToEndId", NS)]
        self.assertIn(f"E2E-{first_invoice}", e2e_ids)
        self.assertEqual(len(e2e_ids), 2)

    def test_generate_enhanced_sepa_xml_missing_batch(self):
        # Nonexistent batch -> caught -> structured failure dict (not a raise).
        result = generate_enhanced_sepa_xml("DDB-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result["success"])
        self.assertIsNone(result["xml_content"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
