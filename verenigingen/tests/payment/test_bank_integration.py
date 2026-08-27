"""
Real-integration tests for verenigingen_payments/utils/bank_integration.py

The statement-parsing surface (CAMT.053 XML + MT940 text -> transaction dicts)
is pure logic and is exercised here with real sample payloads (no mocking).
`create_bank_transaction` is exercised against a real Bank Account / Company so
it creates a real Bank Transaction row. `BankAPIClient.fetch_statements` is
mostly outbound HTTP; its pure date-validation and unconfigured-settings
branches are tested directly, and the PSD2 response→statements mapping is tested
via the extracted `_handle_statement_response` helper (no DB/HTTP mocking — a
plain dict + a lightweight fake response).

Target file is LIVE via the deprecation shim
verenigingen/utils/bank_integration.py (re-exports *).
"""

import os
import tempfile
import unittest

import frappe

from verenigingen.tests.support.error_log_assertions import assert_error_log
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.bank_integration import (
    BankAPIClient,
    BankStatementImporter,
    create_bank_transaction,
    import_bank_statement,
)

# --------------------------------------------------------------------------- #
# Sample payloads (real-shaped CAMT.053 / MT940 fragments)
# --------------------------------------------------------------------------- #

CAMT053_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


def _camt053(entries_xml: str, iban: str = "NL91ABNA0417164300") -> str:
    """Build a minimal CAMT.053 document around the supplied <Ntry> fragments."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{CAMT053_NS}">
  <BkToCstmrStmt>
    <Stmt>
      <Acct>
        <Id><IBAN>{iban}</IBAN></Id>
      </Acct>
      {entries_xml}
    </Stmt>
  </BkToCstmrStmt>
</Document>"""


CREDIT_ENTRY = """
<Ntry>
  <Amt Ccy="EUR">25.00</Amt>
  <CdtDbtInd>CRDT</CdtDbtInd>
  <BookgDt><Dt>2025-03-15</Dt></BookgDt>
  <NtryDtls>
    <TxDtls>
      <Refs><EndToEndId>MEMB-2025-001</EndToEndId></Refs>
      <RltdPties>
        <Dbtr><Nm>Jan de Vries</Nm></Dbtr>
        <DbtrAcct><Id><IBAN>NL02RABO0123456789</IBAN></Id></DbtrAcct>
      </RltdPties>
      <RmtInf><Ustrd>Membership fee 2025</Ustrd></RmtInf>
    </TxDtls>
  </NtryDtls>
</Ntry>
"""

DEBIT_ENTRY = """
<Ntry>
  <Amt Ccy="EUR">99.00</Amt>
  <CdtDbtInd>DBIT</CdtDbtInd>
  <BookgDt><Dt>2025-03-16</Dt></BookgDt>
</Ntry>
"""


MT940_SAMPLE = """:20:STATEMENT001
:25:NL91ABNA0417164300 EUR
:28C:1/1
:60F:C250315EUR1000,00
:61:2503150315C25,00NTRFMEMB-2025-001//REF
:86:/NAME/Jan de Vries/IBAN/NL02RABO0123456789/ Membership fee 2025
:61:2503160316D50,00NTRFOUTGOING//REF2
:86:/NAME/Webhoster BV/ Hosting invoice
:62F:C250316EUR975,00
"""


# --------------------------------------------------------------------------- #
# CAMT.053 parsing
# --------------------------------------------------------------------------- #


class TestCamt053Parsing(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.importer = BankStatementImporter()

    def _import_xml(self, xml: str):
        return self.importer._import_camt053(xml)

    def test_supported_formats(self):
        self.assertEqual(self.importer.supported_formats, ["CAMT.053", "MT940"])

    def test_credit_entry_parsed_fields(self):
        """A single CRDT entry is parsed into a transaction dict with all fields."""
        entries = self.importer
        root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(
            _camt053(CREDIT_ENTRY)
        )
        ns = {"camt": CAMT053_NS}
        ntry = root.find(".//camt:Ntry", ns)
        txn = entries._parse_camt_entry(ntry, ns, "NL91ABNA0417164300")
        self.assertIsNotNone(txn)
        self.assertEqual(txn["amount"], 25.0)
        self.assertEqual(txn["date"], "2025-03-15")
        self.assertEqual(txn["debtor_name"], "Jan de Vries")
        self.assertEqual(txn["debtor_iban"], "NL02RABO0123456789")
        self.assertEqual(txn["reference"], "MEMB-2025-001")
        self.assertEqual(txn["description"], "Membership fee 2025")
        self.assertEqual(txn["account_iban"], "NL91ABNA0417164300")

    def test_debit_entry_skipped(self):
        """Only credit entries are processed; a DBIT entry parses to None."""
        root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(
            _camt053(DEBIT_ENTRY)
        )
        ns = {"camt": CAMT053_NS}
        ntry = root.find(".//camt:Ntry", ns)
        self.assertIsNone(self.importer._parse_camt_entry(ntry, ns, "NL91ABNA0417164300"))

    def test_full_import_credit_only(self):
        """End-to-end: 1 credit + 1 debit -> only the credit is counted in totals.

        No matching Sales Invoice exists, so transactions_imported stays 0 while
        amount_total and account_iban reflect the parsed (credit) transaction.
        """
        result = self._import_xml(_camt053(CREDIT_ENTRY + DEBIT_ENTRY))
        self.assertTrue(result["success"])
        self.assertEqual(result["account_iban"], "NL91ABNA0417164300")
        # Debit excluded from the parsed transactions list -> total is the credit only.
        self.assertEqual(result["amount_total"], 25.0)
        # No invoice matched the reference -> nothing imported, warning recorded.
        self.assertEqual(result["transactions_imported"], 0)
        self.assertTrue(any("No matching invoice" in w for w in self.importer.warnings))

    def test_missing_iban_returns_error(self):
        """CAMT without an account IBAN is rejected with a clear error."""
        xml = f"""<?xml version="1.0"?>
<Document xmlns="{CAMT053_NS}"><BkToCstmrStmt><Stmt>{CREDIT_ENTRY}</Stmt></BkToCstmrStmt></Document>"""
        result = self._import_xml(xml)
        self.assertFalse(result["success"])
        self.assertIn("No IBAN", result["error"])
        self.assertEqual(result["transactions_imported"], 0)

    def test_malformed_xml_returns_parse_error(self):
        result = self._import_xml("<Document><not closed")
        self.assertFalse(result["success"])
        self.assertIn("Invalid XML", result["error"])
        self.assertEqual(result["transactions_imported"], 0)

    def test_entry_missing_amount_is_skipped(self):
        """An entry without Amt/CdtDbtInd parses to None (not a crash)."""
        bad_entry = "<Ntry><BookgDt><Dt>2025-01-01</Dt></BookgDt></Ntry>"
        root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(
            _camt053(bad_entry)
        )
        ns = {"camt": CAMT053_NS}
        ntry = root.find(".//camt:Ntry", ns)
        self.assertIsNone(self.importer._parse_camt_entry(ntry, ns, "NL91ABNA0417164300"))

    def test_credit_entry_missing_optional_fields_defaults(self):
        """A bare credit entry (no debtor/refs/remittance) defaults to empty strings."""
        bare = """
<Ntry>
  <Amt Ccy="EUR">10.00</Amt>
  <CdtDbtInd>CRDT</CdtDbtInd>
</Ntry>
"""
        root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(
            _camt053(bare)
        )
        ns = {"camt": CAMT053_NS}
        ntry = root.find(".//camt:Ntry", ns)
        txn = self.importer._parse_camt_entry(ntry, ns, "NL91ABNA0417164300")
        self.assertEqual(txn["amount"], 10.0)
        self.assertEqual(txn["debtor_name"], "")
        self.assertEqual(txn["debtor_iban"], "")
        self.assertEqual(txn["reference"], "")
        self.assertEqual(txn["description"], "")
        # No BookgDt -> defaults to today()
        self.assertEqual(txn["date"], frappe.utils.today())


# --------------------------------------------------------------------------- #
# MT940 parsing
# --------------------------------------------------------------------------- #


class TestMt940Parsing(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.importer = BankStatementImporter()

    def test_full_import_credit_only(self):
        """MT940 with one credit (:61: C) and one debit (:61: D); only the credit
        becomes a transaction. No matching invoice -> 0 imported, correct total."""
        result = self.importer._import_mt940(MT940_SAMPLE)
        self.assertTrue(result["success"])
        # Only the C line (25.00) is captured; the D line is filtered out.
        self.assertEqual(result["amount_total"], 25.0)
        self.assertEqual(result["transactions_imported"], 0)
        self.assertTrue(any("No matching invoice" in w for w in self.importer.warnings))

    def test_credit_transaction_detail_fields(self):
        """The :86: line populates description, debtor name and IBAN on the
        preceding credit transaction."""
        # Re-run and inspect the parsed transactions via a captured list.
        captured = []
        original = self.importer._create_payment_entry

        def _capture(txn):
            captured.append(txn)
            return original(txn)

        self.importer._create_payment_entry = _capture  # capture the parsed dicts
        self.importer._import_mt940(MT940_SAMPLE)

        self.assertEqual(len(captured), 1)
        txn = captured[0]
        self.assertEqual(txn["amount"], 25.0)
        self.assertEqual(txn["date"], "2025-03-15")
        self.assertEqual(txn["account_iban"], "NL91ABNA0417164300")
        self.assertEqual(txn["debtor_name"], "Jan de Vries")
        self.assertEqual(txn["debtor_iban"], "NL02RABO0123456789")
        self.assertIn("Membership fee 2025", txn["description"])

    def test_empty_content(self):
        """Empty MT940 content yields a successful, empty import."""
        result = self.importer._import_mt940("")
        self.assertTrue(result["success"])
        self.assertEqual(result["transactions_imported"], 0)
        self.assertEqual(result["amount_total"], 0)

    def test_account_iban_extracted_from_field_25(self):
        """The :25: field IBAN is propagated onto the transaction."""
        content = (
            ":25:NL91ABNA0417164300 EUR\n"
            ":61:2503150315C12,50NTRFREF//X\n"
            ":86:/NAME/Test Person/ payment\n"
        )
        captured = []
        self.importer._create_payment_entry = lambda t: captured.append(t) or False
        self.importer._import_mt940(content)
        self.assertEqual(captured[0]["account_iban"], "NL91ABNA0417164300")
        self.assertEqual(captured[0]["amount"], 12.5)


# --------------------------------------------------------------------------- #
# import_statement / import_bank_statement dispatch
# --------------------------------------------------------------------------- #


class TestImportStatementDispatch(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.importer = BankStatementImporter()

    def _write_tmp(self, content: str, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_unsupported_format(self):
        result = self.importer.import_statement("/nonexistent", "CSV")
        self.assertFalse(result["success"])
        self.assertIn("Unsupported format", result["error"])
        self.assertEqual(result["transactions_imported"], 0)

    def test_missing_file_handled(self):
        """A missing file path is caught and reported, not raised."""
        result = self.importer.import_statement("/no/such/file.xml", "CAMT.053")
        self.assertFalse(result["success"])
        self.assertIn("Import failed", result["error"])

    def test_camt_file_roundtrip(self):
        path = self._write_tmp(_camt053(CREDIT_ENTRY), ".xml")
        result = self.importer.import_statement(path, "CAMT.053")
        self.assertTrue(result["success"])
        self.assertEqual(result["account_iban"], "NL91ABNA0417164300")
        self.assertEqual(result["amount_total"], 25.0)

    def test_mt940_file_roundtrip(self):
        path = self._write_tmp(MT940_SAMPLE, ".sta")
        result = self.importer.import_statement(path, "MT940")
        self.assertTrue(result["success"])
        self.assertEqual(result["amount_total"], 25.0)

    def test_module_function_delegates(self):
        """import_bank_statement() is a thin wrapper over the importer."""
        path = self._write_tmp(_camt053(CREDIT_ENTRY), ".xml")
        result = import_bank_statement(path, "CAMT.053")
        self.assertTrue(result["success"])
        self.assertEqual(result["amount_total"], 25.0)


# --------------------------------------------------------------------------- #
# create_bank_transaction (real Bank Transaction row)
# --------------------------------------------------------------------------- #


class TestCreateBankTransaction(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name
        self.bank_account = self._make_bank_account()

    def _make_bank_account(self):
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        bank = get_or_create_unknown_bank()
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"BankIntegration Test {frappe.generate_hash(length=6)}"
        ba.bank = bank
        ba.company = self.company
        ba.bank_account_no = f"NL00TEST{frappe.generate_hash(length=8)}"
        ba.insert()
        self.track_doc("Bank Account", ba.name)
        return ba.name

    def test_creates_real_bank_transaction(self):
        ref = f"BI-{frappe.generate_hash(length=8)}"
        name = create_bank_transaction(
            {
                "bank_account": self.bank_account,
                "company": self.company,
                "amount": 75.0,
                "currency": "EUR",
                "description": "Test bank integration deposit",
                "reference_number": ref,
                "date": frappe.utils.today(),
            }
        )
        self.assertTrue(name)
        self.track_doc("Bank Transaction", name)
        bt = frappe.get_doc("Bank Transaction", name)
        self.assertEqual(bt.bank_account, self.bank_account)
        self.assertEqual(bt.company, self.company)
        self.assertEqual(bt.currency, "EUR")
        # Positive amount maps to a deposit.
        self.assertEqual(bt.deposit, 75.0)
        self.assertEqual(bt.reference_number, ref)

    def test_negative_amount_is_withdrawal(self):
        ref = f"BI-{frappe.generate_hash(length=8)}"
        name = create_bank_transaction(
            {
                "bank_account": self.bank_account,
                "company": self.company,
                "amount": -40.0,
                "reference_number": ref,
            }
        )
        self.track_doc("Bank Transaction", name)
        bt = frappe.get_doc("Bank Transaction", name)
        self.assertEqual(bt.withdrawal, 40.0)
        self.assertEqual(bt.deposit, 0.0)

    def test_missing_bank_account_throws(self):
        with self.assertRaises(frappe.ValidationError):
            create_bank_transaction({"company": self.company, "amount": 10.0})

    def test_missing_company_throws(self):
        with self.assertRaises(frappe.ValidationError):
            create_bank_transaction({"bank_account": self.bank_account, "amount": 10.0})

    def test_idempotent_on_reference_number(self):
        """Re-creating with the same reference_number returns the existing row."""
        ref = f"BI-{frappe.generate_hash(length=8)}"
        data = {
            "bank_account": self.bank_account,
            "company": self.company,
            "amount": 33.0,
            "reference_number": ref,
        }
        name1 = create_bank_transaction(dict(data))
        self.track_doc("Bank Transaction", name1)
        name2 = create_bank_transaction(dict(data))
        self.assertEqual(name1, name2)


# --------------------------------------------------------------------------- #
# BankAPIClient.fetch_statements
# --------------------------------------------------------------------------- #


class TestBankAPIClient(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.client = BankAPIClient()

    def test_defaults(self):
        self.assertEqual(self.client.timeout, 30)
        self.assertEqual(self.client.retry_count, 3)

    def test_invalid_date_format(self):
        result = self.client.fetch_statements("15-03-2025")
        self.assertFalse(result["success"])
        self.assertIn("Invalid date format", result["error"])

    def test_not_configured_returns_error(self):
        """With no Bank Integration Settings doctype/config, fetch reports the
        unconfigured state instead of attempting a request.

        Note: the 'Bank Integration Settings' DocType is not installed on this
        site, so frappe.db.exists(...) is falsy and bank_settings is None.
        """
        result = self.client.fetch_statements("2025-03-15")
        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"])

    # ------------------------------------------------------------------
    # BankAPIClient._handle_statement_response — PSD2 response mapping.
    # Tested directly (pure of DB/settings lookup) so no frappe.db.* mocking is
    # needed; bank_settings is a plain dict, response is a lightweight stand-in.
    # ------------------------------------------------------------------
    class _FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def test_response_mapping_success(self):
        """A 200 PSD2 response maps booked transactions into the standardized shape."""
        payload = {
            "transactions": {
                "booked": [
                    {
                        "transactionId": "T1",
                        "transactionAmount": {"amount": "12.34", "currency": "EUR"},
                        "bookingDate": "2025-03-15",
                        "valueDate": "2025-03-16",
                        "remittanceInformationUnstructured": "Donation",
                        "debtorName": "Alice",
                        "debtorAccount": {"iban": "NL02RABO0123456789"},
                    }
                ]
            }
        }
        settings = {"bank_name": "ExampleBank", "account_id": "ACC123"}
        result = self.client._handle_statement_response(
            self._FakeResponse(200, payload), settings, "2025-03-15"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["bank"], "ExampleBank")
        self.assertEqual(result["account"], "ACC123")
        self.assertEqual(result["date"], "2025-03-15")
        self.assertEqual(len(result["statements"]), 1)
        txn = result["statements"][0]
        self.assertEqual(txn["transaction_id"], "T1")
        self.assertEqual(txn["amount"], 12.34)
        self.assertEqual(txn["currency"], "EUR")
        self.assertEqual(txn["reference"], "Donation")
        self.assertEqual(txn["counterparty_name"], "Alice")
        self.assertEqual(txn["counterparty_account"], "NL02RABO0123456789")

    def test_response_mapping_creditor_fallback(self):
        """When debtor fields are absent, the mapping falls back to creditor name/iban."""
        payload = {
            "transactions": {
                "booked": [
                    {
                        "transactionId": "T2",
                        "transactionAmount": {"amount": "5.00"},
                        "creditorName": "Bob",
                        "creditorAccount": {"iban": "NL91ABNA0417164300"},
                    }
                ]
            }
        }
        result = self.client._handle_statement_response(self._FakeResponse(200, payload), {}, "2025-03-15")
        txn = result["statements"][0]
        self.assertEqual(txn["counterparty_name"], "Bob")
        self.assertEqual(txn["counterparty_account"], "NL91ABNA0417164300")
        self.assertEqual(txn["currency"], "EUR")  # default when currency missing
        self.assertEqual(result["bank"], "Unknown")  # default when bank_name missing

    def test_response_mapping_unauthorized(self):
        result = self.client._handle_statement_response(self._FakeResponse(401), {}, "2025-03-15")
        self.assertFalse(result["success"])
        self.assertIn("Unauthorized", result["error"])

    def test_response_mapping_rate_limited(self):
        result = self.client._handle_statement_response(self._FakeResponse(429), {}, "2025-03-15")
        self.assertFalse(result["success"])
        self.assertIn("Rate limit", result["error"])

    def test_response_mapping_other_error_includes_status(self):
        result = self.client._handle_statement_response(
            self._FakeResponse(503, text="maintenance"), {}, "2025-03-15"
        )
        self.assertFalse(result["success"])
        self.assertIn("503", result["error"])
        self.assertIn("maintenance", result["error"])


class TestInvoiceReferenceMatching(VereningingenTestCase):
    """R3: shared SINV-/ACC-SINV-/INV- reference matching is consolidated in
    bank_transaction_reconciliation.resolve_invoice_from_reference and reused by
    BankStatementImporter._find_matching_invoice. These tests confirm both paths
    resolve a real Sales Invoice identically (behavior parity)."""

    def setUp(self):
        super().setUp()
        self.importer = BankStatementImporter()
        self.invoice = self.create_test_sales_invoice()

    def test_shared_resolver_direct_name_match(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            resolve_invoice_from_reference,
        )

        self.assertEqual(resolve_invoice_from_reference(self.invoice.name), self.invoice.name)

    def test_shared_resolver_embedded_reference(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            resolve_invoice_from_reference,
        )

        # The default series is ACC-SINV-...; embed it in a noisy reference string.
        embedded = f"PAYMENT FOR {self.invoice.name} THANK YOU"
        self.assertEqual(resolve_invoice_from_reference(embedded), self.invoice.name)

    def test_shared_resolver_no_match_returns_none(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            resolve_invoice_from_reference,
        )

        self.assertIsNone(resolve_invoice_from_reference("SINV-DOES-NOT-EXIST-ZZZ"))
        self.assertIsNone(resolve_invoice_from_reference(""))

    def test_find_matching_invoice_uses_shared_resolver(self):
        # Parity: _find_matching_invoice returns the same invoice the shared
        # resolver does for a reference that names the invoice.
        matched = self.importer._find_matching_invoice({"reference": self.invoice.name})
        self.assertEqual(matched, self.invoice.name)


class TestInvoiceAmountMatching(VereningingenTestCase):
    """The amount fallback in `_find_matching_invoice` chose arbitrarily -- twice (#567).

    When no invoice reference is present the importer falls back to
    `customer_name LIKE %debtor_name%` and then, per customer, one invoice of the
    right amount by `limit=1`. Two arbitrary picks compound:

      * **Across invoices** -- two open invoices of the same amount for one customer
        is ordinary for recurring dues, and `limit=1` took whichever came first.
      * **Across PARTIES** -- the loop returned on the first customer that happened
        to have a matching invoice. A `LIKE` on a debtor name matches more than one
        real customer (`Jansen` matches `Jansen` and `Jansenius`), so the money could
        be allocated to a DIFFERENT MEMBER entirely.

    `_create_payment_entry` builds a Payment Entry against whatever this returns, so
    this is the same money-moving class as the other three sites. #567 lists three
    unfixed instances; this is a fourth that grepping the class turned up.
    """

    # The base invoice helper's generated line is fixed at this rate; see
    # _submitted_invoice for why it cannot be parameterised.
    AMOUNT = 25.0

    def setUp(self):
        super().setUp()
        self.importer = BankStatementImporter()
        # Only the company is needed -- the base invoice helper resolves its own
        # income account. `_owned_company_and_income_account` is still the right
        # call: it OWNS a company rather than scanning for one.
        self.company, _income_account = self._owned_company_and_income_account()

    def _debtor_customer(self, customer_name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        return customer.name

    def _outstanding_invoice(self, customer):
        """A submitted invoice with AMOUNT still outstanding.

        The base helper only saves, and a DRAFT has outstanding 0 so it would never
        be a candidate here. Its generated line is fixed at 25.0 and cannot be
        overridden by passing `items`: the helper `setattr`s the value, which skips
        Frappe's child-table coercion and dies with
        "'dict' object has no attribute 'is_new'". So AMOUNT is the helper's own
        figure rather than a parameter.
        """
        invoice = self.create_test_sales_invoice(customer=customer, company=self.company)
        invoice.submit()
        invoice.reload()
        self.assertAlmostEqual(float(invoice.outstanding_amount), self.AMOUNT, places=2)
        return invoice

    def test_a_single_amount_match_still_resolves(self):
        """Pins the behaviour the fix must not remove. Passes against develop too."""
        token = f"AmtOne{frappe.generate_hash(length=6)}"
        customer = self._debtor_customer(f"Debtor {token}")
        invoice = self._outstanding_invoice(customer)

        matched = self.importer._find_matching_invoice(
            {"reference": "", "amount": self.AMOUNT, "debtor_name": token}
        )
        self.assertEqual(matched, invoice.name)

    def test_two_invoices_of_the_amount_for_one_customer_is_refused(self):
        """Red against develop: `limit=1` returned one of the two."""
        self.expectErrorLog("Bank Import Invoice Ambiguous")
        token = f"AmtTwo{frappe.generate_hash(length=6)}"
        customer = self._debtor_customer(f"Debtor {token}")
        first = self._outstanding_invoice(customer)
        second = self._outstanding_invoice(customer)
        self.assertNotEqual(first.name, second.name)

        matched = self.importer._find_matching_invoice(
            {"reference": "", "amount": self.AMOUNT, "debtor_name": token}
        )
        self.assertIsNone(
            matched,
            f"two invoices of the same amount narrow nothing; got {matched}",
        )
        assert_error_log(
            self,
            "Bank Import Invoice Ambiguous",
            unique=token,
            must_contain=["Reconcile this transaction manually"],
        )

    def test_two_customers_matching_the_debtor_name_is_refused(self):
        """The arbitrary pick crossed PARTIES, not just invoices.

        Red against develop: the loop returned the first customer's invoice, so a
        payment from one member could be booked against another member's invoice.
        """
        self.expectErrorLog("Bank Import Invoice Ambiguous")
        token = f"AmtParty{frappe.generate_hash(length=6)}"
        one = self._debtor_customer(f"Debtor {token}")
        two = self._debtor_customer(f"Debtor {token} Junior")  # also matches LIKE %token%
        mine = self._outstanding_invoice(one)
        theirs = self._outstanding_invoice(two)

        matched = self.importer._find_matching_invoice(
            {"reference": "", "amount": self.AMOUNT, "debtor_name": token}
        )
        self.assertIsNone(
            matched,
            f"a debtor name matching two customers names no invoice; got {matched} "
            f"(candidates {mine.name} / {theirs.name})",
        )
        # "across 2 customer(s)" is the part that distinguishes the cross-PARTY
        # ambiguity from the single-customer one, and it sits mid-message.
        assert_error_log(
            self,
            "Bank Import Invoice Ambiguous",
            unique=token,
            must_contain=["2 customer(s)", "Reconcile this transaction manually"],
        )


if __name__ == "__main__":
    unittest.main()
