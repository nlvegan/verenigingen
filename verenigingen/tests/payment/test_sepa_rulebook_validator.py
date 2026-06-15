"""
Unit/integration tests for SEPARulebookValidator.

The validator operates almost entirely on parsed XML strings and produces
ValidationIssue lists; it touches no DocTypes. Only validate_creditor_iban /
validate_debtor_iban call the pure frappe utility `validate_iban`. These tests
therefore build synthetic SEPA pain.008 XML and assert on the rule outcomes
directly. They run under FrappeTestCase so the frappe runtime (translations,
loggers) is available for the validator's frappe.logger() and validate_iban
calls -- no business logic is mocked.

Target: verenigingen/verenigingen_payments/utils/sepa_rulebook_validator.py
"""

from datetime import date, datetime, timedelta

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.sepa_rulebook_validator import (
    SEPARulebookValidator,
    ValidationIssue,
    ValidationSeverity,
    get_sepa_rules,
    validate_sepa_xml_rulebook,
)

# Valid Dutch test IBANs (correct MOD-97 checksums, verified via iban_validator)
VALID_CREDITOR_IBAN = "NL44RABO0123456789"
VALID_DEBTOR_IBAN = "NL69INGB0123456789"
INVALID_IBAN = "NL00RABO0123456789"  # bad checksum

NS_08 = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
NS_02 = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"


def _build_xml(
    namespace=NS_08,
    msg_id="MSG-12345",
    cre_dt_tm=None,
    nb_of_txs=None,
    ctrl_sum=None,
    creditor_id="NL98ZZZ12345678901",  # 18 chars: NL + 2 + ZZZ + 11
    creditor_iban=VALID_CREDITOR_IBAN,
    creditor_name="Test Vereniging",
    seq_tp="RCUR",
    local_instr="CORE",
    collection_date=None,
    transactions=None,
):
    """Construct a SEPA pain.008 XML document for testing.

    transactions: list of dicts with keys e2e_id, amount, mandate_id,
    mandate_sign_date, debtor_iban, debtor_name. If None a single default
    transaction is created. nb_of_txs / ctrl_sum default to the actual values.
    """
    if cre_dt_tm is None:
        cre_dt_tm = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    if collection_date is None:
        collection_date = (date.today() + timedelta(days=10)).isoformat()
    if transactions is None:
        transactions = [
            {
                "e2e_id": "E2E-0001",
                "amount": "25.00",
                "mandate_id": "MANDATE-0001",
                "mandate_sign_date": (date.today() - timedelta(days=30)).isoformat(),
                "debtor_iban": VALID_DEBTOR_IBAN,
                "debtor_name": "Jan de Tester",
            }
        ]
    if nb_of_txs is None:
        nb_of_txs = str(len(transactions))
    if ctrl_sum is None:
        ctrl_sum = "{:.2f}".format(sum(float(t["amount"]) for t in transactions))

    txn_xml = ""
    for t in transactions:
        txn_xml += f"""
        <DrctDbtTxInf>
          <PmtId><EndToEndId>{t['e2e_id']}</EndToEndId></PmtId>
          <InstdAmt Ccy="EUR">{t['amount']}</InstdAmt>
          <DrctDbtTx>
            <MndtRltdInf>
              <MndtId>{t['mandate_id']}</MndtId>
              <DtOfSgntr>{t['mandate_sign_date']}</DtOfSgntr>
            </MndtRltdInf>
          </DrctDbtTx>
          <DbtrAcct><Id><IBAN>{t['debtor_iban']}</IBAN></Id></DbtrAcct>
          <Dbtr><Nm>{t['debtor_name']}</Nm></Dbtr>
        </DrctDbtTxInf>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{namespace}">
  <CstmrDrctDbtInitn>
    <GrpHdr>
      <MsgId>{msg_id}</MsgId>
      <CreDtTm>{cre_dt_tm}</CreDtTm>
      <NbOfTxs>{nb_of_txs}</NbOfTxs>
      <CtrlSum>{ctrl_sum}</CtrlSum>
      <InitgPty><Nm>{creditor_name}</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtTpInf>
        <SeqTp>{seq_tp}</SeqTp>
        <LclInstrm><Cd>{local_instr}</Cd></LclInstrm>
      </PmtTpInf>
      <ReqdColltnDt>{collection_date}</ReqdColltnDt>
      <CdtrSchmeId><Id><PrvtId><Othr><Id>{creditor_id}</Id></Othr></PrvtId></Id></CdtrSchmeId>
      <Cdtr><Nm>{creditor_name}</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>{creditor_iban}</IBAN></Id></CdtrAcct>
      {txn_xml}
    </PmtInf>
  </CstmrDrctDbtInitn>
</Document>"""


def _parse(xml):
    import xml.etree.ElementTree as ET

    return ET.fromstring(xml)


def _rule(rule_id):
    return next(r for r in SEPARulebookValidator()._initialize_sepa_rules() if r.rule_id == rule_id)


class TestRulebookSetup(FrappeTestCase):
    """Rule definitions and helper plumbing."""

    def setUp(self):
        self.validator = SEPARulebookValidator()

    def test_rules_initialized(self):
        self.assertGreater(len(self.validator.rules), 0)
        ids = {r.rule_id for r in self.validator.rules}
        for expected in ["MSG001", "PMT001", "CDT001", "MND001", "TXN001", "CHR001", "NL001"]:
            self.assertIn(expected, ids)

    def test_every_rule_has_validator_or_xpath(self):
        for r in self.validator.rules:
            self.assertTrue(
                r.validator_function or r.xpath, f"Rule {r.rule_id} has neither validator nor xpath"
            )

    def test_validator_functions_exist(self):
        for r in self.validator.rules:
            if r.validator_function:
                self.assertTrue(
                    hasattr(self.validator, r.validator_function),
                    f"Missing validator method {r.validator_function} for {r.rule_id}",
                )

    def test_extract_namespace_08(self):
        root = _parse(_build_xml(namespace=NS_08))
        self.assertEqual(SEPARulebookValidator._extract_namespace(root), NS_08)

    def test_extract_namespace_02(self):
        root = _parse(_build_xml(namespace=NS_02))
        self.assertEqual(SEPARulebookValidator._extract_namespace(root), NS_02)

    def test_extract_namespace_no_namespace_falls_back_to_default(self):
        import xml.etree.ElementTree as ET

        root = ET.fromstring("<Document><GrpHdr/></Document>")
        self.assertEqual(
            SEPARulebookValidator._extract_namespace(root),
            SEPARulebookValidator.DEFAULT_NAMESPACE,
        )


class TestValidateSepaXmlHappyPath(FrappeTestCase):
    def setUp(self):
        self.validator = SEPARulebookValidator()

    def test_valid_xml_is_compliant(self):
        result = self.validator.validate_sepa_xml(_build_xml())
        self.assertTrue(result["is_compliant"], msg=f"issues: {result['issues']}")
        self.assertEqual(result["compliance_score"], 100)
        self.assertEqual(result["total_issues"], 0)
        self.assertIn("fully compliant", result["validation_summary"])

    def test_valid_xml_pain_008_001_02_namespace(self):
        # Namespace must be derived from the document; .02 should resolve too.
        result = self.validator.validate_sepa_xml(_build_xml(namespace=NS_02))
        self.assertTrue(result["is_compliant"], msg=f"issues: {result['issues']}")

    def test_parse_error_returns_critical_issue(self):
        result = self.validator.validate_sepa_xml("<not valid xml")
        self.assertFalse(result["is_compliant"])
        self.assertEqual(result["compliance_score"], 0)
        self.assertEqual(result["issues"][0]["rule_id"], "XML001")
        self.assertEqual(result["issues"][0]["severity"], "critical")

    def test_result_structure_keys(self):
        result = self.validator.validate_sepa_xml(_build_xml())
        for key in [
            "is_compliant",
            "compliance_score",
            "total_issues",
            "issues_by_severity",
            "issues",
            "recommendations",
            "validation_summary",
        ]:
            self.assertIn(key, result)


class TestMessageLevelRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    # MSG001 -- message id
    def test_message_id_valid(self):
        self.assertEqual(self._run("MSG001", _build_xml(msg_id="GOOD-ID-001")), [])

    def test_message_id_too_long(self):
        issues = self._run("MSG001", _build_xml(msg_id="X" * 36))
        self.assertTrue(any("1-35 characters" in i.message for i in issues))

    def test_message_id_invalid_characters(self):
        issues = self._run("MSG001", _build_xml(msg_id="BAD#ID!"))
        self.assertTrue(any("invalid characters" in i.message for i in issues))

    def test_message_id_at_35_chars_is_valid(self):
        self.assertEqual(self._run("MSG001", _build_xml(msg_id="A" * 35)), [])

    # MSG002 -- creation datetime
    def test_creation_datetime_past_ok(self):
        self.assertEqual(self._run("MSG002", _build_xml()), [])

    def test_creation_datetime_future_rejected(self):
        future = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
        issues = self._run("MSG002", _build_xml(cre_dt_tm=future))
        self.assertTrue(any("future" in i.message for i in issues))

    def test_creation_datetime_invalid_format(self):
        issues = self._run("MSG002", _build_xml(cre_dt_tm="not-a-date"))
        self.assertTrue(any("Invalid datetime" in i.message for i in issues))

    # MSG003 -- transaction count
    def test_transaction_count_matches(self):
        self.assertEqual(self._run("MSG003", _build_xml(nb_of_txs="1")), [])

    def test_transaction_count_mismatch(self):
        issues = self._run("MSG003", _build_xml(nb_of_txs="5"))
        self.assertTrue(any("count mismatch" in i.message for i in issues))

    def test_transaction_count_invalid_format(self):
        issues = self._run("MSG003", _build_xml(nb_of_txs="abc"))
        self.assertTrue(any("Invalid transaction count" in i.message for i in issues))

    # MSG004 -- control sum
    def test_control_sum_matches(self):
        self.assertEqual(self._run("MSG004", _build_xml(ctrl_sum="25.00")), [])

    def test_control_sum_mismatch(self):
        issues = self._run("MSG004", _build_xml(ctrl_sum="999.00"))
        self.assertTrue(any("Control sum mismatch" in i.message for i in issues))

    def test_control_sum_within_one_cent_ok(self):
        # 0.01 tolerance: 25.01 vs actual 25.00 -> diff == 0.01 -> not flagged
        self.assertEqual(self._run("MSG004", _build_xml(ctrl_sum="25.01")), [])

    def test_control_sum_invalid_format(self):
        # REGRESSION (was a product bug, now fixed): validate_control_sum now also
        # catches decimal.InvalidOperation, so a malformed (non-numeric) control sum
        # like "NaNeuro" correctly emits an "Invalid control sum" issue instead of
        # silently passing validation.
        issues = self._run("MSG004", _build_xml(ctrl_sum="NaNeuro"))
        self.assertTrue(any("Invalid control sum" in i.message for i in issues))


class TestPaymentInfoRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    # PMT001 -- collection date timing
    def test_collection_date_sufficient_lead_core(self):
        col = (date.today() + timedelta(days=10)).isoformat()
        cre = (datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
        self.assertEqual(self._run("PMT001", _build_xml(collection_date=col, cre_dt_tm=cre)), [])

    def test_collection_date_too_early_core(self):
        cre = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        col = (date.today() + timedelta(days=2)).isoformat()  # < 5 days
        issues = self._run("PMT001", _build_xml(collection_date=col, cre_dt_tm=cre, local_instr="CORE"))
        self.assertTrue(any("too early" in i.message for i in issues))

    def test_collection_date_b2b_one_day_lead_ok(self):
        cre = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        col = (date.today() + timedelta(days=2)).isoformat()
        self.assertEqual(
            self._run("PMT001", _build_xml(collection_date=col, cre_dt_tm=cre, local_instr="B2B")), []
        )

    def test_collection_date_cor1_one_day_lead_ok(self):
        cre = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        col = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(
            self._run("PMT001", _build_xml(collection_date=col, cre_dt_tm=cre, local_instr="COR1")), []
        )

    # PMT003 -- transaction limit (sanity: small batch passes)
    def test_transaction_limit_small_batch_ok(self):
        self.assertEqual(self._run("PMT003", _build_xml()), [])

    # PMT002 -- sequence type consistency (currently a no-op pass-through)
    def test_sequence_type_consistency_passes(self):
        self.assertEqual(self._run("PMT002", _build_xml(seq_tp="RCUR")), [])


class TestCreditorRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    # CDT001 -- creditor identifier
    def test_creditor_id_valid(self):
        self.assertEqual(self._run("CDT001", _build_xml(creditor_id="NL98ZZZ12345678901")), [])

    def test_creditor_id_wrong_country(self):
        issues = self._run("CDT001", _build_xml(creditor_id="DE98ZZZ012345670000"))
        self.assertTrue(any("Dutch creditor ID" in i.message for i in issues))

    def test_creditor_id_wrong_length(self):
        issues = self._run("CDT001", _build_xml(creditor_id="NL98ZZZ12"))
        self.assertTrue(any("Dutch creditor ID" in i.message for i in issues))

    # CDT002 -- creditor IBAN
    def test_creditor_iban_valid(self):
        self.assertEqual(self._run("CDT002", _build_xml(creditor_iban=VALID_CREDITOR_IBAN)), [])

    def test_creditor_iban_invalid(self):
        issues = self._run("CDT002", _build_xml(creditor_iban=INVALID_IBAN))
        self.assertTrue(any("Invalid creditor IBAN" in i.message for i in issues))


class TestMandateRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    def _txn(self, **overrides):
        base = {
            "e2e_id": "E2E-0001",
            "amount": "25.00",
            "mandate_id": "MANDATE-0001",
            "mandate_sign_date": (date.today() - timedelta(days=30)).isoformat(),
            "debtor_iban": VALID_DEBTOR_IBAN,
            "debtor_name": "Jan de Tester",
        }
        base.update(overrides)
        return base

    # --- MND001-MND004: sequence-type mandate-usage validators ---
    #
    # PRODUCT BUG (sepa_rulebook_validator.py:741, 772, 802, 831):
    # All four validators locate their transactions with the XPath
    #     ".//sepa:DrctDbtTxInf[.//sepa:SeqTp='FRST']"
    # ElementTree's limited XPath does NOT support a `.//` descendant axis
    # inside a predicate; root.findall(...) raises SyntaxError("invalid
    # predicate"). That SyntaxError is swallowed by the generic `except
    # Exception` in _validate_rule (line 390) and merely logged, so these four
    # rules NEVER inspect any transaction and NEVER emit an issue -- regardless
    # of XML shape. They are effectively dead. (Compounding: the real
    # sepa_xml_enhanced_generator emits SeqTp at PmtInf/PmtTpInf level, not
    # inside DrctDbtTxInf, so even a valid ElementTree descendant predicate
    # would not match.)
    #
    # The "valid mandate" tests below pass only vacuously (swallowed error ->
    # empty issue list). The "too_long" tests assert the CORRECT behaviour
    # (an over-length mandate id should be flagged) and are xfailed.

    def test_mnd_predicate_raises_syntaxerror(self):
        # Direct evidence of the root cause.
        root = _parse(_build_xml(seq_tp="FRST", transactions=[self._txn()]))
        with self.assertRaises(SyntaxError):
            root.findall(".//sepa:DrctDbtTxInf[.//sepa:SeqTp='FRST']", self.v.namespace)

    # MND001 FRST
    def test_frst_mandate_id_too_long(self):
        # PRODUCT BUG: see MND001-004 note. Should flag an over-length FRST mandate id.
        xml = _build_xml(seq_tp="FRST", transactions=[self._txn(mandate_id="M" * 36)])
        issues = self._run("MND001", xml)
        self.assertTrue(any("FRST mandate ID" in i.message for i in issues))

    # MND002 RCUR
    def test_rcur_mandate_id_too_long(self):
        # PRODUCT BUG: see MND001-004 note.
        xml = _build_xml(seq_tp="RCUR", transactions=[self._txn(mandate_id="M" * 36)])
        issues = self._run("MND002", xml)
        self.assertTrue(any("RCUR mandate ID" in i.message for i in issues))

    # MND003 OOFF
    def test_ooff_mandate_id_too_long(self):
        # PRODUCT BUG: see MND001-004 note.
        xml = _build_xml(seq_tp="OOFF", transactions=[self._txn(mandate_id="M" * 36)])
        issues = self._run("MND003", xml)
        self.assertTrue(any("OOFF mandate ID" in i.message for i in issues))

    # MND004 FNAL
    def test_fnal_mandate_id_too_long(self):
        # PRODUCT BUG: see MND001-004 note.
        xml = _build_xml(seq_tp="FNAL", transactions=[self._txn(mandate_id="M" * 36)])
        issues = self._run("MND004", xml)
        self.assertTrue(any("FNAL mandate ID" in i.message for i in issues))

    # MND005 mandate age
    def test_mandate_age_recent_ok(self):
        xml = _build_xml(transactions=[self._txn(mandate_sign_date=(date.today() - timedelta(days=60)).isoformat())])
        self.assertEqual(self._run("MND005", xml), [])

    def test_mandate_age_too_old(self):
        old = date(date.today().year - 4, date.today().month, 1).isoformat()
        xml = _build_xml(transactions=[self._txn(mandate_sign_date=old)])
        issues = self._run("MND005", xml)
        self.assertTrue(any("months old" in i.message for i in issues))
        self.assertEqual(issues[0].severity, ValidationSeverity.ERROR)

    def test_mandate_age_invalid_date_format(self):
        xml = _build_xml(transactions=[self._txn(mandate_sign_date="31-12-2020")])
        issues = self._run("MND005", xml)
        self.assertTrue(any("Invalid mandate signature date" in i.message for i in issues))

    def test_mandate_age_boundary_36_months_ok(self):
        # Exactly 36 months should NOT be flagged (> 36 triggers).
        today = date.today()
        y, m = today.year, today.month - 36
        while m <= 0:
            m += 12
            y -= 1
        sign = date(y, m, 1).isoformat()
        xml = _build_xml(transactions=[self._txn(mandate_sign_date=sign)])
        self.assertEqual(self._run("MND005", xml), [])


class TestTransactionRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    def _txn(self, **overrides):
        base = {
            "e2e_id": "E2E-0001",
            "amount": "25.00",
            "mandate_id": "MANDATE-0001",
            "mandate_sign_date": (date.today() - timedelta(days=30)).isoformat(),
            "debtor_iban": VALID_DEBTOR_IBAN,
            "debtor_name": "Jan de Tester",
        }
        base.update(overrides)
        return base

    # TXN001 amounts
    def test_amount_valid(self):
        self.assertEqual(self._run("TXN001", _build_xml()), [])

    def test_amount_too_small(self):
        xml = _build_xml(transactions=[self._txn(amount="0.00")], ctrl_sum="0.00")
        issues = self._run("TXN001", xml)
        self.assertTrue(any("too small" in i.message for i in issues))

    def test_amount_too_large(self):
        xml = _build_xml(transactions=[self._txn(amount="1000000000.00")], ctrl_sum="1000000000.00")
        issues = self._run("TXN001", xml)
        self.assertTrue(any("too large" in i.message for i in issues))

    def test_amount_at_minimum_ok(self):
        xml = _build_xml(transactions=[self._txn(amount="0.01")], ctrl_sum="0.01")
        self.assertEqual(self._run("TXN001", xml), [])

    def test_amount_invalid_format(self):
        # REGRESSION (was a product bug, now fixed): validate_transaction_amount now
        # also catches decimal.InvalidOperation, so a non-numeric InstdAmt like "abc"
        # correctly emits an "Invalid amount" issue instead of silently passing.
        # Pass an explicit ctrl_sum so the _build_xml helper does not itself choke
        # on float("abc") before the XML reaches the validator.
        xml = _build_xml(transactions=[self._txn(amount="abc")], ctrl_sum="0.00")
        issues = self._run("TXN001", xml)
        self.assertTrue(any("Invalid amount" in i.message for i in issues))

    # TXN002 end-to-end id uniqueness
    def test_e2e_ids_unique_ok(self):
        txns = [self._txn(e2e_id="A1"), self._txn(e2e_id="A2")]
        xml = _build_xml(transactions=txns, ctrl_sum="50.00")
        self.assertEqual(self._run("TXN002", xml), [])

    def test_e2e_ids_duplicate_flagged(self):
        txns = [self._txn(e2e_id="DUP"), self._txn(e2e_id="DUP")]
        xml = _build_xml(transactions=txns, ctrl_sum="50.00")
        issues = self._run("TXN002", xml)
        self.assertTrue(any("Duplicate end-to-end" in i.message for i in issues))

    # TXN003 debtor iban
    def test_debtor_iban_valid(self):
        self.assertEqual(self._run("TXN003", _build_xml()), [])

    def test_debtor_iban_invalid(self):
        xml = _build_xml(transactions=[self._txn(debtor_iban=INVALID_IBAN)])
        issues = self._run("TXN003", xml)
        self.assertTrue(any("Invalid debtor IBAN" in i.message for i in issues))


class TestCharacterSetRule(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    def test_valid_chars_ok(self):
        self.assertEqual(self._run("CHR001", _build_xml(creditor_name="Test Vereniging BV")), [])

    def test_invalid_chars_flagged(self):
        # '#' and '%' are not in the SEPA character set.
        xml = _build_xml(creditor_name="Bad#Name%")
        issues = self._run("CHR001", xml)
        self.assertTrue(any("non-SEPA characters" in i.message for i in issues))


class TestNetherlandsRules(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()
        self.v.namespace = {"sepa": NS_08}

    def _run(self, rule_id, xml):
        return self.v._validate_rule(_rule(rule_id), _parse(xml), xml)

    def _txn(self, **overrides):
        base = {
            "e2e_id": "E2E-0001",
            "amount": "25.00",
            "mandate_id": "MANDATE-0001",
            "mandate_sign_date": (date.today() - timedelta(days=30)).isoformat(),
            "debtor_iban": VALID_DEBTOR_IBAN,
            "debtor_name": "Jan de Tester",
        }
        base.update(overrides)
        return base

    # NL001 dutch iban bank codes
    def test_known_dutch_bank_code_ok(self):
        # RABO / INGB are in the recognised list.
        self.assertEqual(self._run("NL001", _build_xml()), [])

    def test_unknown_dutch_bank_code_warning(self):
        # MOCK is a valid-checksum IBAN but NOT in NL001's recognised codes.
        mock_iban = "NL82MOCK0123456789"
        xml = _build_xml(creditor_iban=mock_iban, transactions=[self._txn(debtor_iban=mock_iban)], ctrl_sum="25.00")
        issues = self._run("NL001", xml)
        self.assertTrue(any("Unknown Dutch bank code" in i.message for i in issues))
        self.assertTrue(all(i.severity == ValidationSeverity.WARNING for i in issues))

    # NL002 dutch business days
    def test_collection_on_weekend_flagged(self):
        # Find next Saturday from today.
        d = date.today()
        while d.weekday() != 5:
            d += timedelta(days=1)
        xml = _build_xml(collection_date=d.isoformat())
        issues = self._run("NL002", xml)
        self.assertTrue(any("weekend" in i.message for i in issues))

    def test_collection_on_weekday_ok(self):
        # Find next Tuesday (not in the 2025 holiday list path for arbitrary years).
        d = date.today()
        while d.weekday() != 1:
            d += timedelta(days=1)
        xml = _build_xml(collection_date=d.isoformat())
        issues = self._run("NL002", xml)
        self.assertEqual([i for i in issues if "weekend" in i.message], [])

    def test_collection_on_dutch_holiday_2025_flagged(self):
        # 2025-12-25 Christmas (Thursday) -> holiday rule, not weekend.
        xml = _build_xml(collection_date="2025-12-25")
        issues = self._run("NL002", xml)
        self.assertTrue(any("public holiday" in i.message for i in issues))

    def test_country_specific_rule_skipped_for_other_country(self):
        # Running full validation with country=DE should skip NL rules entirely.
        mock_iban = "NL82MOCK0123456789"
        xml = _build_xml(creditor_iban=mock_iban, transactions=[self._txn(debtor_iban=mock_iban)], ctrl_sum="25.00")
        result = self.v.validate_sepa_xml(xml, country="DE")
        self.assertFalse(any(i["rule_id"] in ("NL001", "NL002") for i in result["issues"]))


class TestComplianceMetrics(FrappeTestCase):
    def setUp(self):
        self.v = SEPARulebookValidator()

    def test_score_perfect_when_no_issues(self):
        m = self.v._calculate_compliance_metrics([])
        self.assertEqual(m["score"], 100)
        self.assertEqual(m["by_severity"]["critical"], 0)

    def test_score_penalties(self):
        issues = [
            ValidationIssue(rule_id="A", severity=ValidationSeverity.CRITICAL, message="x"),
            ValidationIssue(rule_id="B", severity=ValidationSeverity.ERROR, message="y"),
            ValidationIssue(rule_id="C", severity=ValidationSeverity.WARNING, message="z"),
            ValidationIssue(rule_id="D", severity=ValidationSeverity.INFO, message="w"),
        ]
        m = self.v._calculate_compliance_metrics(issues)
        # 100 - 25 - 10 - 5 - 1 = 59
        self.assertEqual(m["score"], 59)

    def test_score_floor_at_zero(self):
        issues = [ValidationIssue(rule_id="X", severity=ValidationSeverity.CRITICAL, message="m")] * 10
        m = self.v._calculate_compliance_metrics(issues)
        self.assertEqual(m["score"], 0)

    def test_recommendations_for_critical(self):
        issues = [ValidationIssue(rule_id="MND001", severity=ValidationSeverity.CRITICAL, message="m")]
        recs = self.v._generate_recommendations(issues)
        self.assertTrue(any("critical issues" in r for r in recs))
        self.assertTrue(any("mandate management" in r for r in recs))

    def test_recommendations_txn_and_chr(self):
        issues = [
            ValidationIssue(rule_id="TXN001", severity=ValidationSeverity.CRITICAL, message="m"),
            ValidationIssue(rule_id="CHR001", severity=ValidationSeverity.ERROR, message="m"),
        ]
        recs = self.v._generate_recommendations(issues)
        self.assertTrue(any("transaction data" in r for r in recs))
        self.assertTrue(any("character set" in r for r in recs))

    def test_summary_empty(self):
        self.assertIn("fully compliant", self.v._generate_validation_summary([]))

    def test_summary_with_issues_not_ready(self):
        issues = [
            ValidationIssue(rule_id="A", severity=ValidationSeverity.CRITICAL, message="m"),
            ValidationIssue(rule_id="B", severity=ValidationSeverity.WARNING, message="m"),
        ]
        summary = self.v._generate_validation_summary(issues)
        self.assertIn("not ready for submission", summary)
        self.assertIn("1 critical issue", summary)

    def test_summary_warnings_only_acceptable(self):
        issues = [ValidationIssue(rule_id="A", severity=ValidationSeverity.WARNING, message="m")]
        summary = self.v._generate_validation_summary(issues)
        self.assertIn("improvements recommended", summary)


class TestApiEndpoints(FrappeTestCase):
    """Whitelisted endpoints. Tests run as Administrator so the
    @critical_api / @high_security_api decorators allow access; endpoint-body
    errors propagate with their real type (post the require_sepa_permission fix).
    """

    def test_validate_sepa_xml_rulebook_valid(self):
        result = validate_sepa_xml_rulebook(_build_xml(), country="NL")
        self.assertTrue(result["is_compliant"], msg=f"issues: {result['issues']}")

    def test_validate_sepa_xml_rulebook_parse_error(self):
        result = validate_sepa_xml_rulebook("<broken", country="NL")
        self.assertFalse(result["is_compliant"])

    def test_get_sepa_rules_all(self):
        result = get_sepa_rules()
        self.assertGreater(result["total_rules"], 0)
        self.assertEqual(len(result["rules"]), result["total_rules"])

    def test_get_sepa_rules_filter_by_type(self):
        result = get_sepa_rules(rule_type="country_specific")
        self.assertTrue(all(r["rule_type"] == "country_specific" for r in result["rules"]))
        self.assertGreater(result["total_rules"], 0)

    def test_get_sepa_rules_filter_by_country(self):
        # Country filter keeps generic rules (no countries) + NL-specific ones.
        result_nl = get_sepa_rules(country="NL")
        result_de = get_sepa_rules(country="DE")
        # NL-specific rules (with countries=["NL"]) should be excluded for DE.
        nl_specific_ids = {r["rule_id"] for r in result_nl["rules"]} - {
            r["rule_id"] for r in result_de["rules"]
        }
        self.assertIn("NL001", nl_specific_ids)
