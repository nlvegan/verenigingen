"""
Real (no-mock) tests for the SEPA pain.002 return-file parser.

These feed genuine pain.002.001.03 / pain.002.001.10 XML documents (modelled on
ISO 20022 / SEPA Direct Debit return files) through the real SEPAReturnParser and
assert each field/branch/status/reason-code is extracted correctly. Parsing is
pure logic over XML (defusedxml under the hood); no business logic is mocked.

A FrappeTestCase base is used only because the module calls frappe.log_error on
its error paths - parsing itself needs no DB.

Covers verenigingen/verenigingen_payments/utils/sepa_return_parser.py:
    - SEPAReturnItem (is_rejected/is_pending/is_accepted/to_dict)
    - SEPAReturnParser.parse + namespace detection
    - _parse_transaction_status (status, reason code/desc, addtl info,
      amount/currency, debtor name/iban, mandate id)
    - SEPA_RETURN_REASON_CODES mapping
    - parse_sepa_return_file
    - get_rejected_transactions
"""

import unittest

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.sepa_return_parser import (
    SEPA_RETURN_REASON_CODES,
    SEPAReturnItem,
    SEPAReturnParser,
    get_rejected_transactions,
    parse_sepa_return_file,
)

PAIN002_03 = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"
PAIN002_10 = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.10"


def _reason_block(reason_code, additional_info=None):
    if not reason_code:
        return ""
    addtl = f"<AddtlInf>{additional_info}</AddtlInf>" if additional_info else ""
    return f"""
        <StsRsnInf>
            <Rsn><Cd>{reason_code}</Cd></Rsn>
            {addtl}
        </StsRsnInf>"""


def _tx_block(
    status,
    end_to_end_id="E2E-001",
    reason_code=None,
    additional_info=None,
    instr_id=None,
    amount=None,
    currency="EUR",
    debtor_name=None,
    debtor_iban=None,
    mandate_id=None,
):
    instr = f"<OrgnlInstrId>{instr_id}</OrgnlInstrId>" if instr_id else ""

    orig_tx_ref = ""
    if amount is not None or debtor_name or debtor_iban or mandate_id:
        amt = f'<Amt><InstdAmt Ccy="{currency}">{amount}</InstdAmt></Amt>' if amount is not None else ""
        dbtr = f"<Dbtr><Nm>{debtor_name}</Nm></Dbtr>" if debtor_name else ""
        dbtr_acct = (
            f"<DbtrAcct><Id><IBAN>{debtor_iban}</IBAN></Id></DbtrAcct>" if debtor_iban else ""
        )
        mndt = f"<MndtRltdInf><MndtId>{mandate_id}</MndtId></MndtRltdInf>" if mandate_id else ""
        orig_tx_ref = f"<OrgnlTxRef>{amt}{dbtr}{dbtr_acct}{mndt}</OrgnlTxRef>"

    return f"""
        <TxInfAndSts>
            <OrgnlEndToEndId>{end_to_end_id}</OrgnlEndToEndId>
            {instr}
            <TxSts>{status}</TxSts>
            {_reason_block(reason_code, additional_info)}
            {orig_tx_ref}
        </TxInfAndSts>"""


def _make_pain002(tx_blocks, namespace=PAIN002_03, payment_id="PMT-001"):
    body = "".join(tx_blocks)
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
                <OrgnlPmtInfId>{payment_id}</OrgnlPmtInfId>
                {body}
            </OrgnlPmtInfAndSts>
        </CstmrPmtStsRpt>
    </Document>"""


class TestSEPAReturnItem(unittest.TestCase):
    """SEPAReturnItem dataclass status helpers and to_dict."""

    def _item(self, status, reason_code=None):
        return SEPAReturnItem(
            original_message_id="MSG",
            original_payment_id="PMT",
            original_end_to_end_id="E2E",
            original_instruction_id="INSTR",
            status=status,
            reason_code=reason_code,
            reason_description="desc" if reason_code else None,
            additional_info=None,
            original_amount=25.0,
            original_currency="EUR",
            debtor_name="Jan",
            debtor_iban="NL91ABNA0417164300",
            mandate_id="MNDT",
        )

    def test_is_rejected(self):
        self.assertTrue(self._item("RJCT").is_rejected())
        self.assertFalse(self._item("ACCP").is_rejected())

    def test_is_pending(self):
        self.assertTrue(self._item("PDNG").is_pending())
        self.assertFalse(self._item("RJCT").is_pending())

    def test_is_accepted_all_variants(self):
        for status in ("ACCP", "ACSC", "ACSP", "ACTC"):
            self.assertTrue(self._item(status).is_accepted(), status)
        self.assertFalse(self._item("RJCT").is_accepted())
        self.assertFalse(self._item("PDNG").is_accepted())

    def test_to_dict_shape_and_values(self):
        d = self._item("RJCT", reason_code="AM04").to_dict()
        self.assertEqual(d["status"], "RJCT")
        self.assertEqual(d["reason_code"], "AM04")
        self.assertEqual(d["end_to_end_id"], "E2E")
        self.assertEqual(d["amount"], 25.0)
        self.assertEqual(d["currency"], "EUR")
        self.assertEqual(d["debtor_iban"], "NL91ABNA0417164300")
        self.assertTrue(d["is_rejected"])


class TestNamespaceDetection(FrappeTestCase):
    """SEPAReturnParser namespace detection branches."""

    def test_detects_pain002_03(self):
        parser = SEPAReturnParser()
        parser.parse(_make_pain002([_tx_block("ACCP")], namespace=PAIN002_03))
        self.assertEqual(parser.namespace, PAIN002_03)

    def test_detects_pain002_10(self):
        parser = SEPAReturnParser()
        parser.parse(_make_pain002([_tx_block("ACCP")], namespace=PAIN002_10))
        self.assertEqual(parser.namespace, PAIN002_10)

    def test_accepts_unknown_pain002_variant(self):
        # Any namespace containing "pain.002" is accepted (forward-compat branch).
        future_ns = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.99"
        parser = SEPAReturnParser()
        returns = parser.parse(_make_pain002([_tx_block("ACCP")], namespace=future_ns))
        self.assertEqual(parser.namespace, future_ns)
        self.assertEqual(len(returns), 1)

    def test_unknown_namespace_raises_value_error(self):
        xml = _make_pain002([_tx_block("ACCP")], namespace="urn:unknown:namespace")
        parser = SEPAReturnParser()
        with self.assertRaises(ValueError) as ctx:
            parser.parse(xml)
        self.assertIn("Invalid pain.002 file", str(ctx.exception))

    def test_malformed_xml_raises(self):
        parser = SEPAReturnParser()
        with self.assertRaises(Exception):
            parser.parse("<not valid xml")


class TestParseTransactionStatus(FrappeTestCase):
    """Field-by-field extraction from TxInfAndSts elements."""

    def test_rejected_with_reason_code_and_description(self):
        xml = _make_pain002([_tx_block("RJCT", reason_code="AM04")])
        returns = SEPAReturnParser().parse(xml)
        self.assertEqual(len(returns), 1)
        item = returns[0]
        self.assertEqual(item.status, "RJCT")
        self.assertTrue(item.is_rejected())
        self.assertEqual(item.reason_code, "AM04")
        self.assertEqual(item.reason_description, "Insufficient Funds")

    def test_unknown_reason_code_description(self):
        xml = _make_pain002([_tx_block("RJCT", reason_code="ZZ99")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.reason_code, "ZZ99")
        self.assertEqual(item.reason_description, "Unknown reason")

    def test_additional_info_extracted(self):
        xml = _make_pain002(
            [_tx_block("RJCT", reason_code="MD01", additional_info="Mandate cancelled by debtor")]
        )
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.additional_info, "Mandate cancelled by debtor")

    def test_accepted_no_reason(self):
        xml = _make_pain002([_tx_block("ACCP")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertTrue(item.is_accepted())
        self.assertIsNone(item.reason_code)
        self.assertIsNone(item.reason_description)

    def test_pending_status(self):
        xml = _make_pain002([_tx_block("PDNG")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertTrue(item.is_pending())

    def test_missing_status_defaults_to_unkn(self):
        # A TxInfAndSts without a TxSts element should default status to "UNKN".
        tx = """
        <TxInfAndSts>
            <OrgnlEndToEndId>E2E-NO-STATUS</OrgnlEndToEndId>
        </TxInfAndSts>"""
        item = SEPAReturnParser().parse(_make_pain002([tx]))[0]
        self.assertEqual(item.status, "UNKN")

    def test_end_to_end_and_instruction_ids(self):
        xml = _make_pain002([_tx_block("RJCT", end_to_end_id="E2E-XYZ", instr_id="INSTR-7")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.original_end_to_end_id, "E2E-XYZ")
        self.assertEqual(item.original_instruction_id, "INSTR-7")

    def test_payment_id_extracted(self):
        """original_payment_id is read from the parent OrgnlPmtInfAndSts container.

        Regression for a fixed PRODUCT BUG: the parser used to call
        ``_get_text(tx_element, "OrgnlPmtInfId", ns)`` which searched *within* the
        TxInfAndSts element. In ISO 20022 pain.002 the OrgnlPmtInfId is a child of
        the parent OrgnlPmtInfAndSts (a sibling container of TxInfAndSts), so the
        lookup never matched and the payment id was always lost. The fix iterates
        per OrgnlPmtInfAndSts group and propagates its OrgnlPmtInfId to each
        contained transaction."""
        xml = _make_pain002([_tx_block("RJCT")], payment_id="PMT-999")
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.original_payment_id, "PMT-999")

    def test_amount_and_currency(self):
        xml = _make_pain002([_tx_block("RJCT", reason_code="AM04", amount="42.50", currency="EUR")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.original_amount, 42.50)
        self.assertEqual(item.original_currency, "EUR")

    def test_non_eur_currency(self):
        xml = _make_pain002([_tx_block("RJCT", amount="10.00", currency="GBP")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.original_currency, "GBP")

    def test_invalid_amount_text_ignored(self):
        # Non-numeric InstdAmt must be swallowed (amount/currency stay None).
        tx = """
        <TxInfAndSts>
            <OrgnlEndToEndId>E2E-BADAMT</OrgnlEndToEndId>
            <TxSts>RJCT</TxSts>
            <OrgnlTxRef><Amt><InstdAmt Ccy="EUR">not-a-number</InstdAmt></Amt></OrgnlTxRef>
        </TxInfAndSts>"""
        item = SEPAReturnParser().parse(_make_pain002([tx]))[0]
        self.assertIsNone(item.original_amount)
        self.assertIsNone(item.original_currency)

    def test_debtor_name_iban_and_mandate(self):
        xml = _make_pain002(
            [
                _tx_block(
                    "RJCT",
                    reason_code="MD01",
                    debtor_name="Jan de Vries",
                    debtor_iban="NL91ABNA0417164300",
                    mandate_id="MNDT-2024-001",
                )
            ]
        )
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.debtor_name, "Jan de Vries")
        self.assertEqual(item.debtor_iban, "NL91ABNA0417164300")
        self.assertEqual(item.mandate_id, "MNDT-2024-001")

    def test_no_orig_tx_ref_leaves_optional_fields_none(self):
        xml = _make_pain002([_tx_block("ACCP")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertIsNone(item.original_amount)
        self.assertIsNone(item.debtor_name)
        self.assertIsNone(item.debtor_iban)
        self.assertIsNone(item.mandate_id)

    def test_original_message_id_extracted(self):
        # The original message id is read once from the document-level
        # CstmrPmtStsRpt > OrgnlGrpInfAndSts > OrgnlMsgId and propagated to every
        # return item. (_make_pain002 emits OrgnlMsgId == "ORIG-MSG-001".)
        xml = _make_pain002([_tx_block("RJCT")])
        item = SEPAReturnParser().parse(xml)[0]
        self.assertEqual(item.original_message_id, "ORIG-MSG-001")


class TestMultipleTransactions(FrappeTestCase):
    """Multiple TxInfAndSts in one file."""

    def test_three_mixed_statuses(self):
        xml = _make_pain002(
            [
                _tx_block("RJCT", end_to_end_id="E2E-1", reason_code="AM04"),
                _tx_block("ACCP", end_to_end_id="E2E-2"),
                _tx_block("RJCT", end_to_end_id="E2E-3", reason_code="MD01"),
            ]
        )
        returns = SEPAReturnParser().parse(xml)
        self.assertEqual(len(returns), 3)
        self.assertEqual(len([r for r in returns if r.is_rejected()]), 2)
        self.assertEqual(len([r for r in returns if r.is_accepted()]), 1)

    def test_empty_document_no_transactions(self):
        xml = _make_pain002([])
        returns = SEPAReturnParser().parse(xml)
        self.assertEqual(returns, [])


class TestModuleEntryPoints(FrappeTestCase):
    """parse_sepa_return_file / get_rejected_transactions public helpers."""

    def test_parse_sepa_return_file_returns_dicts(self):
        xml = _make_pain002([_tx_block("RJCT", reason_code="AM04", amount="25.00")])
        result = parse_sepa_return_file(xml)
        self.assertIsInstance(result, list)
        self.assertIsInstance(result[0], dict)
        self.assertEqual(result[0]["reason_code"], "AM04")
        self.assertTrue(result[0]["is_rejected"])

    def test_get_rejected_transactions_filters(self):
        xml = _make_pain002(
            [
                _tx_block("RJCT", end_to_end_id="E2E-1", reason_code="AM04"),
                _tx_block("ACCP", end_to_end_id="E2E-2"),
                _tx_block("PDNG", end_to_end_id="E2E-3"),
                _tx_block("RJCT", end_to_end_id="E2E-4", reason_code="MD07"),
            ]
        )
        rejected = get_rejected_transactions(xml)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all(r["is_rejected"] for r in rejected))
        self.assertEqual(
            {r["end_to_end_id"] for r in rejected},
            {"E2E-1", "E2E-4"},
        )


class TestReasonCodeMapping(unittest.TestCase):
    """SEPA_RETURN_REASON_CODES dictionary sanity."""

    def test_known_codes(self):
        self.assertEqual(SEPA_RETURN_REASON_CODES["AM04"], "Insufficient Funds")
        self.assertEqual(SEPA_RETURN_REASON_CODES["MD01"], "No Mandate")
        self.assertEqual(SEPA_RETURN_REASON_CODES["AC04"], "Closed Account Number")
        self.assertEqual(SEPA_RETURN_REASON_CODES["MD07"], "End Customer Deceased")

    def test_all_values_are_strings(self):
        self.assertTrue(all(isinstance(v, str) and v for v in SEPA_RETURN_REASON_CODES.values()))


class TestParityAfterRefactor(FrappeTestCase):
    """Parity tests: verify that the refactored helpers produce identical output
    to the previous inline implementation for representative pain.002 samples.

    These tests exist to prove that delegating Clark-notation ``{uri}`` stripping
    to ``extract_xml_namespace`` in ``_detect_namespace`` does not change any
    observable parsing behavior.
    """

    # -----------------------------------------------------------------
    # Representative full pain.002.001.03 sample with all fields populated
    # -----------------------------------------------------------------
    FULL_PAIN002_XML = _make_pain002(
        [
            _tx_block(
                "RJCT",
                end_to_end_id="INV-2026-001",
                reason_code="AM04",
                additional_info="Insufficient funds in account",
                instr_id="INSTR-001",
                amount="123.45",
                currency="EUR",
                debtor_name="Jan de Vries",
                debtor_iban="NL91ABNA0417164300",
                mandate_id="MNDT-2024-001",
            ),
            _tx_block("ACCP", end_to_end_id="INV-2026-002"),
            _tx_block("PDNG", end_to_end_id="INV-2026-003"),
        ],
        namespace=PAIN002_03,
        payment_id="PMT-PARITY-001",
    )

    def test_parity_namespace_detected_correctly(self):
        """extract_xml_namespace delegation: namespace detection is unchanged."""
        parser = SEPAReturnParser()
        parser.parse(self.FULL_PAIN002_XML)
        self.assertEqual(parser.namespace, PAIN002_03)

    def test_parity_transaction_count(self):
        """Correct number of transactions parsed after refactor."""
        returns = SEPAReturnParser().parse(self.FULL_PAIN002_XML)
        self.assertEqual(len(returns), 3)

    def test_parity_rejected_transaction_fields(self):
        """All fields of the rejected transaction are extracted correctly."""
        returns = SEPAReturnParser().parse(self.FULL_PAIN002_XML)
        rjct = next(r for r in returns if r.is_rejected())
        self.assertEqual(rjct.original_end_to_end_id, "INV-2026-001")
        self.assertEqual(rjct.original_payment_id, "PMT-PARITY-001")
        self.assertEqual(rjct.original_message_id, "ORIG-MSG-001")
        self.assertEqual(rjct.original_instruction_id, "INSTR-001")
        self.assertEqual(rjct.reason_code, "AM04")
        self.assertEqual(rjct.reason_description, "Insufficient Funds")
        self.assertEqual(rjct.additional_info, "Insufficient funds in account")
        self.assertAlmostEqual(rjct.original_amount, 123.45)
        self.assertEqual(rjct.original_currency, "EUR")
        self.assertEqual(rjct.debtor_name, "Jan de Vries")
        self.assertEqual(rjct.debtor_iban, "NL91ABNA0417164300")
        self.assertEqual(rjct.mandate_id, "MNDT-2024-001")

    def test_parity_accepted_and_pending_statuses(self):
        """Non-rejected statuses are preserved after refactor."""
        returns = SEPAReturnParser().parse(self.FULL_PAIN002_XML)
        by_e2e = {r.original_end_to_end_id: r for r in returns}
        self.assertTrue(by_e2e["INV-2026-002"].is_accepted())
        self.assertTrue(by_e2e["INV-2026-003"].is_pending())

    def test_parity_pain002_10_namespace(self):
        """pain.002.001.10 namespace is still detected correctly after refactor."""
        xml_10 = _make_pain002(
            [_tx_block("ACCP", end_to_end_id="INV-10-001", amount="99.99", currency="EUR")],
            namespace=PAIN002_10,
            payment_id="PMT-V10",
        )
        parser = SEPAReturnParser()
        returns = parser.parse(xml_10)
        self.assertEqual(parser.namespace, PAIN002_10)
        self.assertEqual(len(returns), 1)
        self.assertTrue(returns[0].is_accepted())

    def test_parity_forward_compat_namespace(self):
        """Unknown pain.002.x.y namespace still accepted (forward-compat)."""
        future_ns = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.99"
        xml_future = _make_pain002([_tx_block("RJCT", reason_code="MD01")], namespace=future_ns)
        parser = SEPAReturnParser()
        returns = parser.parse(xml_future)
        self.assertEqual(parser.namespace, future_ns)
        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].reason_code, "MD01")

    def test_parity_unknown_namespace_still_raises(self):
        """Non-pain.002 namespace still raises ValueError after refactor."""
        xml = _make_pain002([_tx_block("ACCP")], namespace="urn:other:schema")
        with self.assertRaises(ValueError) as ctx:
            SEPAReturnParser().parse(xml)
        self.assertIn("Invalid pain.002 file", str(ctx.exception))

    def test_parity_get_rejected_transactions_output(self):
        """get_rejected_transactions still returns only rejected items."""
        rejected = get_rejected_transactions(self.FULL_PAIN002_XML)
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0]["is_rejected"])
        self.assertEqual(rejected[0]["reason_code"], "AM04")


if __name__ == "__main__":
    unittest.main()
