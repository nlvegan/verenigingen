"""
Tests for the eBoekhouden payment-processing engine helpers.

Covers the decision/parsing/validation surface of:
- ``e_boekhouden/utils/payment_processing/payment_entry_handler.py``
  (PaymentEntryHandler): invoice-number parsing, row reference extraction,
  payment-type/refund determination, remarks generation, direction validation.
- ``e_boekhouden/utils/processors/payment_processor.py`` (PaymentProcessor):
  ``can_process`` routing for payment mutation types incl. refund/credit-note
  edge cases, gateway-adjustment no-ops, bank-name extraction.

These are real integration tests against a EUR company. They exercise the pure
and DB-backed decision logic that does NOT require a live eBoekhouden HTTP
connection (no actual Payment Entry is submitted, which would need fully
configured ledgers/invoices/bank accounts).

Run with:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_entry_handler
"""

import frappe

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
    PaymentEntryHandler,
)
from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    """Return a EUR company name, creating a dedicated test company if needed."""
    existing = frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
    if existing:
        return existing

    company = frappe.new_doc("Company")
    company.company_name = "EBKH EUR Test Co"
    company.abbr = "EETC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class TestPaymentEntryHandlerHelpers(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _handler(self):
        return PaymentEntryHandler(self.company)

    # ---- _parse_invoice_numbers ----

    def test_parse_invoice_numbers_none(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(None), [])

    def test_parse_invoice_numbers_empty_string(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(""), [])

    def test_parse_invoice_numbers_csv_trims_and_drops_blanks(self):
        self.assertEqual(self._handler()._parse_invoice_numbers("A, B ,C,"), ["A", "B", "C"])

    def test_parse_invoice_numbers_coerces_int(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(123), ["123"])

    # ---- _is_valid_invoice_reference ----

    def test_valid_invoice_reference_good(self):
        self.assertTrue(self._handler()._is_valid_invoice_reference("INV-001"))

    def test_valid_invoice_reference_with_allowed_chars(self):
        self.assertTrue(self._handler()._is_valid_invoice_reference("2025/01_A.1"))

    def test_valid_invoice_reference_too_short(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("A"))

    def test_valid_invoice_reference_bad_chars(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("bad space!"))

    def test_valid_invoice_reference_too_long(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("X" * 51))

    # ---- _extract_invoice_references_from_rows ----

    def test_extract_refs_from_rows_rest(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "REF1"}, {"factuurNummer": "REF2"}]}
        )
        self.assertIn("REF1", refs)
        self.assertIn("REF2", refs)

    def test_extract_refs_from_regels_soap(self):
        refs = self._handler()._extract_invoice_references_from_rows({"Regels": [{"FactuurNummer": "REG1"}]})
        self.assertEqual(refs, ["REG1"])

    def test_extract_refs_dedupes(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "DUP"}, {"factuurNummer": "DUP"}]}
        )
        self.assertEqual(refs.count("DUP"), 1)

    def test_extract_refs_ignores_invalid(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "has space"}]}
        )
        self.assertEqual(refs, [])

    def test_extract_refs_empty(self):
        self.assertEqual(self._handler()._extract_invoice_references_from_rows({}), [])

    def test_extract_refs_handles_non_dict_rows(self):
        # Defensive: non-dict entries are skipped without error
        refs = self._handler()._extract_invoice_references_from_rows({"rows": ["not-a-dict"]})
        self.assertEqual(refs, [])

    # ---- _determine_payment_type ----

    def test_determine_type3_positive_receive(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 1, "type": 3}, 100.0, 3)
        self.assertEqual((pt, party, refund), ("Receive", "Customer", False))

    def test_determine_type3_negative_is_refund(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 2, "type": 3}, -100.0, 3)
        self.assertEqual((pt, party, refund), ("Pay", "Customer", True))

    def test_determine_type4_positive_pay(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 3, "type": 4}, 100.0, 4)
        self.assertEqual((pt, party, refund), ("Pay", "Supplier", False))

    def test_determine_type4_negative_is_refund(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 4, "type": 4}, -100.0, 4)
        self.assertEqual((pt, party, refund), ("Receive", "Supplier", True))

    def test_determine_type4_gateway_adjustment_keeps_pay(self):
        pt, party, refund = self._handler()._determine_payment_type(
            {"id": 5, "type": 4, "_original_amount": 200}, -150.0, 4
        )
        # Gateway adjustments are not treated as refunds
        self.assertEqual((pt, party, refund), ("Pay", "Supplier", False))

    # ---- _validate_payment_direction ----

    def test_validate_direction_correct_passes(self):
        # A correct direction returns None and emits no Error Log row.
        # frappe.log_error commits independently of the test txn, so the
        # Error Log count delta is a reliable "no error raised" guard.
        before = frappe.db.count("Error Log")
        self.assertIsNone(self._handler()._validate_payment_direction(3, 100.0, "Receive", "Customer"))
        self.assertIsNone(self._handler()._validate_payment_direction(4, 100.0, "Pay", "Supplier"))
        self.assertEqual(frappe.db.count("Error Log"), before)

    def test_validate_direction_wrong_type_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._validate_payment_direction(3, 100.0, "Pay", "Customer")

    def test_validate_direction_wrong_party_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._validate_payment_direction(3, 100.0, "Receive", "Supplier")

    def test_validate_direction_non_payment_type_noop(self):
        # Type 7 is not validated -> returns None without raising and logs nothing.
        before = frappe.db.count("Error Log")
        self.assertIsNone(self._handler()._validate_payment_direction(7, 100.0, "Pay", "Supplier"))
        self.assertEqual(frappe.db.count("Error Log"), before)

    # ---- _generate_remarks ----

    def test_generate_remarks_contains_key_fields(self):
        remarks = self._handler()._generate_remarks(
            {
                "id": 42,
                "type": 3,
                "invoiceNumber": "INV-1",
                "description": "Membership",
                "rows": [{}, {}],
                "ledgerId": 1100,
                "relationId": 5001,
            },
            "Bank - X",
            "Customer A",
        )
        self.assertIn("Mutation 42", remarks)
        self.assertIn("Customer Payment", remarks)
        self.assertIn("INV-1", remarks)
        self.assertIn("Row count: 2", remarks)
        self.assertIn("1100", remarks)

    def test_generate_remarks_supplier_label(self):
        remarks = self._handler()._generate_remarks({"id": 7, "type": 4, "ledgerId": 1}, "Bank", "Supplier B")
        self.assertIn("Supplier Payment", remarks)

    # ---- _get_or_create_party ----

    def test_get_or_create_party_no_relation_id(self):
        self.assertIsNone(self._handler()._get_or_create_party(None, "Customer", "desc"))

    # ---- _determine_bank_account error path ----

    def test_determine_bank_account_no_ledger_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._determine_bank_account(None, "Receive")

    # ---- debug log ----

    def test_debug_log_accumulates(self):
        h = self._handler()
        h._log("a message")
        self.assertTrue(any("a message" in line for line in h.get_debug_log()))


class TestPaymentProcessorRouting(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _processor(self):
        return PaymentProcessor(self.company)

    # ---- can_process ----

    def test_cannot_process_non_payment_type(self):
        self.assertFalse(self._processor().can_process({"id": 1, "type": 2}))

    def test_can_process_type5_money_received(self):
        self.assertTrue(self._processor().can_process({"id": 2, "type": 5}))

    def test_can_process_type6_money_paid(self):
        self.assertTrue(self._processor().can_process({"id": 3, "type": 6}))

    def test_can_process_type3_positive(self):
        self.assertTrue(self._processor().can_process({"id": 4, "type": 3, "amount": 100}))

    def test_type3_negative_without_invoice_forwarded(self):
        # Generic refund -> forwarded to JournalProcessor (False)
        self.assertFalse(self._processor().can_process({"id": 5, "type": 3, "amount": -50}))

    def test_type3_negative_with_invoice_claimed(self):
        # Credit note payment -> Payment Entry (True)
        self.assertTrue(
            self._processor().can_process({"id": 6, "type": 3, "amount": -50, "invoiceNumber": "X"})
        )

    def test_can_process_type4_positive(self):
        self.assertTrue(self._processor().can_process({"id": 7, "type": 4, "amount": 100}))

    def test_can_process_type4_negative_refund(self):
        self.assertTrue(self._processor().can_process({"id": 8, "type": 4, "amount": -100}))

    def test_negative_row_amount_warning_logged(self):
        p = self._processor()
        p.can_process({"id": 9, "type": 3, "amount": 100, "rows": [{"amount": -5}]})
        self.assertTrue(any("NEGATIVE row amount" in m for m in p.get_debug_info()))

    # ---- get_payment_type ----

    def test_get_payment_type_receive(self):
        self.assertEqual(self._processor().get_payment_type({"type": 3}), "Receive")

    def test_get_payment_type_pay(self):
        self.assertEqual(self._processor().get_payment_type({"type": 4}), "Pay")

    # ---- gateway adjustment (no-op when not type 4 / unconfigured) ----

    def test_gateway_adjustment_false_for_non_type4(self):
        self.assertFalse(self._processor()._is_payment_gateway_adjustment({"id": 1, "type": 3}))

    def test_gateway_adjustment_false_when_unconfigured(self):
        # Settings have no gateway account/prefix on the test site -> not an adjustment.
        # Pin the specific no-op branch (config-not-set) by asserting the exact
        # debug line the product emits at payment_processor.py ~L566-574.
        p = self._processor()
        self.assertFalse(
            p._is_payment_gateway_adjustment({"id": 1, "type": 4, "ledgerId": 1, "invoiceNumber": "X"})
        )
        self.assertTrue(
            any(
                "Payment gateway configuration not set - gateway adjustment logic disabled" in m
                for m in p.get_debug_info()
            )
        )

    def test_adjust_gateway_amount_noop_non_type4(self):
        mutation = {"id": 2, "type": 3, "amount": 50}
        self.assertEqual(self._processor()._adjust_payment_gateway_amount(mutation), mutation)

    def test_adjust_gateway_amount_noop_when_unconfigured(self):
        # The amount-adjust path returns the mutation unchanged when gateway
        # config is absent. _adjust_payment_gateway_amount itself logs nothing
        # (comment: "already logged by _is_payment_gateway_adjustment"), so pin
        # the unconfigured branch by first triggering the detector on the same
        # processor instance and asserting its config-not-set debug line fired.
        p = self._processor()
        mutation = {"id": 3, "type": 4, "amount": 50, "ledgerId": 1, "invoiceNumber": "X"}
        # Detector establishes (and logs) that config is not set.
        self.assertFalse(p._is_payment_gateway_adjustment(mutation))
        self.assertTrue(
            any(
                "Payment gateway configuration not set - gateway adjustment logic disabled" in m
                for m in p.get_debug_info()
            )
        )
        # Therefore the amount adjustment is a true no-op for the unconfigured branch.
        self.assertEqual(p._adjust_payment_gateway_amount(mutation), mutation)

    # ---- _extract_bank_name_from_account ----

    def test_extract_bank_name_empty(self):
        self.assertIsNone(self._processor()._extract_bank_name_from_account(""))

    def test_extract_bank_name_unknown_supplier(self):
        # Bank name not present as a Supplier -> None (avoids link validation errors)
        self.assertIsNone(
            self._processor()._extract_bank_name_from_account("1100 - NonexistentBankXYZ - 123 - NVV")
        )


# ---------------------------------------------------------------------------
# Integration fixtures for driving the REAL Payment Entry create path.
#
# These module-level helpers perform the privileged inserts (parties, GL
# accounts, ledger mappings, invoices) outside the test body so the
# test-quality-enforcer's ban on inline ignore_permissions/set_user is honored.
# ---------------------------------------------------------------------------


def _non_group(doctype):
    """First non-group master of a doctype (Customer Group / Territory / etc.)."""
    return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def _ensure_current_fiscal_year():
    """Ensure a Fiscal Year covers today's date AND applies to every company.

    erpnext's global test setup (``set_defaults_for_tests``) links the current
    calendar-year Fiscal Year to ``_Test Company`` via the FY ``companies`` child
    table, which RESTRICTS that FY to only that company. ``get_fiscal_years``
    then returns [] for any other company (e.g. the EUR test company), so a
    Payment Entry submit fails "Date <today> is not in any active Fiscal Year".

    The canonical session helper clears this once, but its session flag can be
    set by an earlier test class whose setUp ran *before* erpnext re-applied the
    restriction. So we clear the restriction unconditionally here: drop every
    ``Fiscal Year Company`` row on every Fiscal Year that covers today(), commit
    so it survives per-test rollback, then bust the per-company FY cache.
    """
    from frappe.utils import getdate, today

    from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

    ensure_test_fiscal_year_for_all_companies()

    d = getdate(today())
    covering = frappe.db.sql(
        """
        SELECT name FROM `tabFiscal Year`
        WHERE %s BETWEEN year_start_date AND year_end_date AND disabled = 0
        """,
        (d,),
        pluck=True,
    )
    for fy_name in covering:
        if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
            frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()  # fixture must outlive per-test rollback
    # get_fiscal_years() memoizes per company; drop it so the now-unrestricted
    # current FY is picked up during submit().
    frappe.cache().delete_value("fiscal_years")


def _setup_cash_account(company):
    """Return a non-group Cash/Bank GL account for the company.

    The EUR test company ships a 'Cash' account; we reuse it as the bank-side
    GL account for Payment Entries (paid_to for receipts, paid_from for
    payments). No Bank Account DocType is needed because the integration tests
    drive _create_payment_entry / _allocate_and_insert_payment / submit
    directly (the Bank Transaction synthesis happens only in the full
    process_payment_mutation path, which also reaches the live API party
    resolver).
    """
    acct = frappe.db.get_value(
        "Account", {"company": company, "account_type": ["in", ["Cash", "Bank"]], "is_group": 0}, "name"
    )
    return acct


def _persist_cash_ledger_mapping(ledger_id, account):
    """Link an E-Boekhouden ledger id to a Cash/Bank GL account.

    With erpnext_account pre-set, get_ledger_mapping() resolves entirely from
    the DB and never touches the live eBoekhouden API.
    """
    if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}):
        return
    doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
    doc.ledger_id = str(ledger_id)
    doc.ledger_code = f"PAYTEST{ledger_id}"
    doc.ledger_name = f"Pay Test Ledger {ledger_id}"
    doc.erpnext_account = account
    doc.insert(ignore_permissions=True)


def _persist_customer(name):
    if frappe.db.exists("Customer", name):
        return name
    doc = frappe.new_doc("Customer")
    doc.customer_name = name
    doc.customer_group = _non_group("Customer Group")
    doc.territory = _non_group("Territory")
    doc.insert(ignore_permissions=True)
    return doc.name


def _persist_supplier(name):
    if frappe.db.exists("Supplier", name):
        return name
    doc = frappe.new_doc("Supplier")
    doc.supplier_name = name
    doc.supplier_group = _non_group("Supplier Group")
    doc.insert(ignore_permissions=True)
    return doc.name


def _persist_sales_item(company):
    """A non-stock sellable Item with an income account on the EUR company."""
    item_code = "EBKH PE Test Item"
    if frappe.db.exists("Item", item_code):
        return item_code
    doc = frappe.new_doc("Item")
    doc.item_code = item_code
    doc.item_name = item_code
    doc.item_group = _non_group("Item Group") or "All Item Groups"
    doc.stock_uom = "Nos"
    doc.is_stock_item = 0
    doc.insert(ignore_permissions=True)
    return item_code


def _persist_submitted_sales_invoice(company, customer, debit_to, eb_invoice_number, rate):
    """Insert and submit a Sales Invoice carrying an eboekhouden_invoice_number.

    Returns the SI name. The invoice posts against ``debit_to`` (the company's
    default receivable) so the payment's invoice-first account resolution lands
    on the same receivable account.
    """
    income = frappe.db.get_value(
        "Account", {"company": company, "is_group": 0, "root_type": "Income"}, "name"
    )
    item_code = _persist_sales_item(company)
    si = frappe.new_doc("Sales Invoice")
    si.company = company
    si.customer = customer
    si.posting_date = frappe.utils.today()
    si.due_date = frappe.utils.today()
    si.debit_to = debit_to
    si.eboekhouden_invoice_number = eb_invoice_number
    si.append("items", {"item_code": item_code, "qty": 1, "rate": rate, "income_account": income})
    si.set_missing_values()
    si.insert(ignore_permissions=True)
    si.submit()
    return si.name


class TestPaymentEntryHandlerCreateIntegration(EnhancedTestCase):
    """Integration tests that drive the REAL Payment Entry create path and
    assert the created document's financial content (payment_type, party,
    paid_from/paid_to accounts, amounts, and invoice reference rows).

    These call _create_payment_entry / _allocate_and_insert_payment /
    _submit_with_floating_point_fix directly with real DB fixtures. The full
    process_payment_mutation() wrapper is intentionally NOT used because its
    party resolution (_get_or_create_party) calls the live eBoekhouden HTTP API
    -- the only external boundary. Everything money-moving (account selection,
    amount calc, allocation, GL-posting submit) is exercised for real.
    """

    CASH_LEDGER_ID = 770090

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        _ensure_current_fiscal_year()
        cls.cash_account = _setup_cash_account(cls.company)
        assert cls.cash_account, f"No Cash/Bank account for {cls.company}"
        cls.receivable = frappe.db.get_value("Company", cls.company, "default_receivable_account")
        cls.payable = frappe.db.get_value("Company", cls.company, "default_payable_account")
        _persist_cash_ledger_mapping(cls.CASH_LEDGER_ID, cls.cash_account)
        cls.customer = _persist_customer("EBKH PE Test Customer")
        cls.supplier = _persist_supplier("EBKH PE Test Supplier")

    def _handler(self):
        return PaymentEntryHandler(self.company)

    _id_counter = 0

    def _unique_id(self):
        # Mutation ids must be unique to avoid the early "already exists" return
        # and the eboekhouden_mutation_nr unique constraint across reruns.
        import random

        TestPaymentEntryHandlerCreateIntegration._id_counter += 1
        return (
            (int(frappe.utils.now_datetime().timestamp()) % 2000000) * 1000
            + random.randint(0, 999)
            + TestPaymentEntryHandlerCreateIntegration._id_counter
        )

    # ---- (a) customer receipt (type 3), no invoice ----

    def test_customer_receipt_type3_financial_content(self):
        h = self._handler()
        h._current_invoice_numbers = []
        mut = {
            "id": self._unique_id(),
            "type": 3,
            "date": frappe.utils.today(),
            "amount": 75.0,
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-C1",
            "invoiceNumber": "",
            "description": "integration customer receipt",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Receive",
            party_type="Customer",
            party=self.customer,
            bank_account=self.cash_account,
        )
        h._allocate_and_insert_payment(pe, [], mut, "Customer")
        h._submit_with_floating_point_fix(pe, None)

        # Reload from DB to assert persisted financial content.
        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Receive")
        self.assertEqual(saved.party_type, "Customer")
        self.assertEqual(saved.party, self.customer)
        # Receive: money lands in our Cash account, sourced from the receivable.
        self.assertEqual(saved.paid_to, self.cash_account)
        self.assertEqual(saved.paid_from, self.receivable)
        self.assertEqual(saved.paid_amount, 75.0)
        self.assertEqual(saved.received_amount, 75.0)
        # No invoice referenced -> fully unallocated.
        self.assertEqual(saved.unallocated_amount, 75.0)
        self.assertEqual(len(saved.references), 0)
        self.assertEqual(saved.eboekhouden_mutation_nr, str(mut["id"]))

    # ---- (b) supplier payment (type 4), no invoice ----

    def test_supplier_payment_type4_financial_content(self):
        h = self._handler()
        h._current_invoice_numbers = []
        mut = {
            "id": self._unique_id(),
            "type": 4,
            "date": frappe.utils.today(),
            "amount": 40.0,
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-S1",
            "invoiceNumber": "",
            "description": "integration supplier payment",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Pay",
            party_type="Supplier",
            party=self.supplier,
            bank_account=self.cash_account,
        )
        h._allocate_and_insert_payment(pe, [], mut, "Supplier")
        h._submit_with_floating_point_fix(pe, None)

        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Pay")
        self.assertEqual(saved.party_type, "Supplier")
        self.assertEqual(saved.party, self.supplier)
        # Pay: money leaves our Cash account, into the payable.
        self.assertEqual(saved.paid_from, self.cash_account)
        self.assertEqual(saved.paid_to, self.payable)
        self.assertEqual(saved.paid_amount, 40.0)
        self.assertEqual(saved.received_amount, 40.0)
        self.assertEqual(saved.unallocated_amount, 40.0)
        self.assertEqual(len(saved.references), 0)

    # ---- (c) customer receipt allocated against an existing Sales Invoice ----

    def test_customer_receipt_allocated_to_sales_invoice(self):
        eb_invoice_number = f"EB-PE-INT-{self._unique_id()}"
        si_name = _persist_submitted_sales_invoice(
            self.company, self.customer, self.receivable, eb_invoice_number, rate=50.0
        )

        h = self._handler()
        invoice_numbers = h._parse_invoice_numbers(eb_invoice_number)
        # Mirror process(): the handler stashes header invoice numbers for
        # invoice-first account resolution.
        h._current_invoice_numbers = invoice_numbers
        mut = {
            "id": self._unique_id(),
            "type": 3,
            "date": frappe.utils.today(),
            "amount": 50.0,
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-C2",
            "invoiceNumber": eb_invoice_number,
            "description": "integration receipt vs invoice",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Receive",
            party_type="Customer",
            party=self.customer,
            bank_account=self.cash_account,
        )
        h._allocate_and_insert_payment(pe, invoice_numbers, mut, "Customer")
        h._submit_with_floating_point_fix(pe, None)

        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Receive")
        self.assertEqual(saved.paid_to, self.cash_account)
        # Invoice-first resolution: paid_from is the invoice's receivable account.
        self.assertEqual(saved.paid_from, self.receivable)
        self.assertEqual(saved.paid_amount, 50.0)

        # The payment must carry exactly one reference row to the Sales Invoice
        # for the full amount, leaving nothing unallocated.
        self.assertEqual(len(saved.references), 1)
        ref = saved.references[0]
        self.assertEqual(ref.reference_doctype, "Sales Invoice")
        self.assertEqual(ref.reference_name, si_name)
        self.assertEqual(ref.allocated_amount, 50.0)
        self.assertEqual(saved.unallocated_amount, 0.0)

        # And the invoice it paid is now settled.
        self.assertEqual(frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount"), 0.0)
