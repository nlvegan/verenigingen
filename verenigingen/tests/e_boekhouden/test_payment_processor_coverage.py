"""
Coverage sweep for ``e_boekhouden/utils/processors/payment_processor.py``.

Targets the PURE / cheap-DB decision surface of :class:`PaymentProcessor` that
governs whether a mutation becomes a Payment Entry, a skipped gateway
adjustment, or a forwarded-to-JournalProcessor refund:

* ``can_process``                  -- type gating (3/4/5/6), refund detection
* ``get_payment_type``             -- Receive/Pay mapping
* ``_is_payment_gateway_adjustment`` -- Mollie/gateway skip detection
* ``_adjust_payment_gateway_amount`` -- amount math against the invoice total
* ``_extract_bank_name_from_account`` -- bank-name parse + Supplier guard

These are real integration tests: a real EUR company resolves the cost centre,
the gateway-detection paths read/write the real ``E-Boekhouden Settings`` Single
(restored in tearDown) and a real ``E-Boekhouden Ledger Mapping`` + ``Purchase
Invoice`` row, and ``_extract_bank_name_from_account`` exercises a real
``Supplier`` lookup.

OUT OF SCOPE (documented, not tested here):
* ``process`` / ``_process_money_transfer`` -- create & submit real Journal
  Entries + Bank Transactions through the party extractor / ledger auto-create
  pipeline; covered by the integration suites
  (test_rest_journal_entry_creation, test_payment_entry_handler).
* ``_create_bank_transaction_for_journal_entry`` / ``_link_*`` /
  ``_update_bank_transaction_party`` -- require a persisted JE + Bank Account +
  bank_transaction_creator service; integration-level, not unit-testable here.

Run with::

    bench --site veg11.veganisme.org run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_processor_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestPaymentProcessorDecisions(EnhancedTestCase):
    """can_process / get_payment_type branch coverage (no gateway config)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _processor(self):
        return PaymentProcessor(self.company)

    # ---- can_process: type gating ----

    def test_can_process_rejects_non_payment_types(self):
        """Only types 3/4/5/6 are payment mutations; everything else is rejected."""
        p = self._processor()
        for t in (0, 1, 2, 7, 99):
            self.assertFalse(
                p.can_process({"id": 1, "type": t}),
                msg=f"type {t} must NOT be claimed by PaymentProcessor",
            )

    def test_can_process_accepts_type5_and_type6(self):
        """Type 5 (Money Received) and Type 6 (Money Paid) always go to PaymentProcessor."""
        p = self._processor()
        self.assertTrue(p.can_process({"id": 10, "type": 5}))
        self.assertTrue(p.can_process({"id": 11, "type": 6}))

    # ---- can_process: Type 3 (customer payment) refund logic ----

    def test_can_process_type3_positive_accepted(self):
        """Normal positive customer payment is claimed."""
        self.assertTrue(self._processor().can_process({"id": 20, "type": 3, "amount": 100.0}))

    def test_can_process_type3_negative_without_invoice_forwarded(self):
        """Negative Type 3 WITHOUT an invoice ref is a generic refund -> JournalProcessor.

        This is the key exclusion branch: ``return False`` so the mutation falls
        through to JournalProcessor instead of becoming a Payment Entry.
        """
        mutation = {"id": 21, "type": 3, "amount": -100.0}
        self.assertFalse(self._processor().can_process(mutation))

    def test_can_process_type3_negative_with_invoice_kept(self):
        """Negative Type 3 WITH an invoice ref is a credit-note payment -> kept as PE."""
        mutation = {"id": 22, "type": 3, "amount": -100.0, "invoiceNumber": "CN-2025-1"}
        self.assertTrue(self._processor().can_process(mutation))

    def test_can_process_type3_zero_amount_accepted(self):
        """Zero raw amount is not negative -> not excluded."""
        self.assertTrue(self._processor().can_process({"id": 23, "type": 3, "amount": 0}))

    # ---- can_process: Type 4 (supplier payment) accepts both directions ----

    def test_can_process_type4_positive_payment_accepted(self):
        """Positive Type 4 (normal payment OUT) is claimed."""
        self.assertTrue(self._processor().can_process({"id": 30, "type": 4, "amount": 100.0}))

    def test_can_process_type4_negative_refund_accepted(self):
        """Negative Type 4 (refund FROM supplier) is still claimed -- handler reverses direction."""
        self.assertTrue(self._processor().can_process({"id": 31, "type": 4, "amount": -100.0}))

    def test_can_process_type4_with_rows_accepted(self):
        """Type 4 with positive rows but zero main amount is a normal payment."""
        mutation = {"id": 32, "type": 4, "amount": 0, "rows": [{"amount": 50.0}]}
        self.assertTrue(self._processor().can_process(mutation))

    def test_can_process_type4_negative_row_amount_logs_warning(self):
        """A negative row amount violates the unsigned assumption and is logged.

        The mutation is still claimed (Type 4 accepts everything); the branch we
        exercise is the warning + ``safe_log_mutation_error`` call. We assert the
        debug trail records the violation.
        """
        p = self._processor()
        mutation = {"id": 33, "type": 4, "amount": 80.0, "rows": [{"amount": -80.0}]}
        # safe_log_mutation_error writes an Error Log; that is the intended
        # behaviour here, so tell the automatic tearDown guard to ignore it.
        self.expectErrorLog("Unexpected Negative Row Amount")
        result = p.can_process(mutation)
        self.assertTrue(result)
        self.assertTrue(
            any("NEGATIVE row amount" in m for m in p.get_debug_info()),
            msg="negative row amount must be flagged in debug info",
        )

    # ---- get_payment_type ----

    def test_get_payment_type_type3_is_receive(self):
        self.assertEqual(self._processor().get_payment_type({"type": 3}), "Receive")

    def test_get_payment_type_type4_is_pay(self):
        self.assertEqual(self._processor().get_payment_type({"type": 4}), "Pay")

    def test_get_payment_type_default_is_pay(self):
        """Any non-3 type (incl. missing) maps to Pay."""
        self.assertEqual(self._processor().get_payment_type({}), "Pay")
        self.assertEqual(self._processor().get_payment_type({"type": 5}), "Pay")


class TestPaymentProcessorGatewayUnconfigured(EnhancedTestCase):
    """Gateway-detection short-circuits when E-Boekhouden Settings has no gateway."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        # Ensure gateway config is empty for these tests (restore in tearDown).
        self._saved_account = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account"
        )
        self._saved_prefix = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix"
        )
        frappe.db.set_single_value("E-Boekhouden Settings", "payment_gateway_virtual_account", "")
        frappe.db.set_single_value("E-Boekhouden Settings", "payment_gateway_invoice_prefix", "")

    def tearDown(self):
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self._saved_account
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix", self._saved_prefix
        )
        super().tearDown()

    def _processor(self):
        return PaymentProcessor(self.company)

    def test_is_adjustment_false_for_non_type4(self):
        """Gateway logic only applies to Type 4; other types return False immediately."""
        p = self._processor()
        for t in (3, 5, 6):
            self.assertFalse(p._is_payment_gateway_adjustment({"id": 1, "type": t}))

    def test_is_adjustment_false_when_unconfigured(self):
        """Type 4 with no gateway config returns False and logs the config notice once."""
        p = self._processor()
        mutation = {"id": 2, "type": 4, "ledgerId": "123", "invoiceNumber": "MOLLIE-1"}
        self.assertFalse(p._is_payment_gateway_adjustment(mutation))
        self.assertTrue(
            any("gateway configuration not set" in m for m in p.get_debug_info()),
            msg="missing-config notice must be logged",
        )

    def test_is_adjustment_config_notice_logged_once(self):
        """The config warning is logged once per processor instance, not per call."""
        p = self._processor()
        mutation = {"id": 3, "type": 4, "ledgerId": "123", "invoiceNumber": "MOLLIE-1"}
        p._is_payment_gateway_adjustment(mutation)
        p._is_payment_gateway_adjustment(mutation)
        notices = [m for m in p.get_debug_info() if "gateway configuration not set" in m]
        self.assertEqual(len(notices), 1)

    def test_adjust_amount_returns_original_for_non_type4(self):
        """Non-Type-4 mutations are returned unchanged (identity)."""
        p = self._processor()
        mutation = {"id": 4, "type": 3, "amount": 100.0}
        self.assertIs(p._adjust_payment_gateway_amount(mutation), mutation)

    def test_adjust_amount_returns_original_when_unconfigured(self):
        """Type 4 with no gateway config is returned unchanged."""
        p = self._processor()
        mutation = {"id": 5, "type": 4, "amount": 100.0, "ledgerId": "123", "invoiceNumber": "MOLLIE-1"}
        result = p._adjust_payment_gateway_amount(mutation)
        self.assertIs(result, mutation)
        self.assertEqual(result["amount"], 100.0)


class TestPaymentProcessorGatewayConfigured(EnhancedTestCase):
    """Gateway-configured detection + amount adjustment against a real invoice.

    Seeds a real ``E-Boekhouden Ledger Mapping`` linking the gateway virtual
    account to a known ledger id, points the ``E-Boekhouden Settings`` Single at
    that account + a ``MOLLIE-`` invoice prefix, and creates a real draft
    Purchase Invoice carrying the matching ``eboekhouden_invoice_number``.
    """

    GATEWAY_LEDGER_ID = "999000999"
    GATEWAY_PREFIX = "MOLLIE-"
    INVOICE_NUM = "MOLLIE-COVERAGE-1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self._saved_account = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account"
        )
        self._saved_prefix = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix"
        )

        # A real GL account to act as the gateway virtual account.
        self.gateway_account = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 0}, "name"
        )
        self.assertIsNotNone(self.gateway_account, "EUR company must have at least one ledger account")

        self._make_ledger_mapping()
        self.purchase_invoice = self._make_draft_purchase_invoice(rate=42.50)

        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self.gateway_account
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix", self.GATEWAY_PREFIX
        )

    def tearDown(self):
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self._saved_account
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix", self._saved_prefix
        )
        super().tearDown()

    def _make_ledger_mapping(self):
        existing = frappe.db.exists(
            "E-Boekhouden Ledger Mapping", {"ledger_id": self.GATEWAY_LEDGER_ID}
        )
        if existing:
            frappe.delete_doc("E-Boekhouden Ledger Mapping", existing, force=True)
        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        mapping.ledger_id = self.GATEWAY_LEDGER_ID
        mapping.ledger_code = "GW999"
        mapping.ledger_name = "Gateway Virtual"
        mapping.erpnext_account = self.gateway_account
        mapping.insert(ignore_permissions=True)

    def _make_draft_purchase_invoice(self, rate):
        supplier_name = "EBKH Gateway Coverage Supplier"
        if not frappe.db.exists("Supplier", supplier_name):
            sup = frappe.new_doc("Supplier")
            sup.supplier_name = supplier_name
            sup.supplier_group = frappe.db.get_value(
                "Supplier Group", {"is_group": 0}, "name", order_by="name"
            )
            sup.insert(ignore_permissions=True)
            supplier_name = sup.name

        item_code = frappe.db.get_value("Item", {"is_purchase_item": 1}, "name")
        self.assertIsNotNone(item_code, "A purchase item must exist for the draft Purchase Invoice")

        pi = frappe.new_doc("Purchase Invoice")
        pi.supplier = supplier_name
        pi.company = self.company
        # Pin the document currency to the EUR test company's currency. Without
        # this the PI inherits the ambient system default (INR on CI test sites),
        # which mismatches the EUR party account and fails validation -- an
        # order-dependent failure that doesn't surface on a EUR-default site.
        pi.currency = "EUR"
        pi.posting_date = "2025-01-15"
        pi.disable_rounded_total = 1
        pi.append("items", {"item_code": item_code, "qty": 1, "rate": rate})
        pi.eboekhouden_invoice_number = self.INVOICE_NUM
        # Draft only -- the detection/adjustment code reads name + grand_total,
        # neither of which needs a submitted/posted invoice.
        pi.save()
        pi.reload()
        return pi

    def _processor(self):
        return PaymentProcessor(self.company)

    def _gateway_mutation(self, amount):
        return {
            "id": 700,
            "type": 4,
            "amount": amount,
            "ledgerId": self.GATEWAY_LEDGER_ID,
            "invoiceNumber": self.INVOICE_NUM,
        }

    # ---- _is_payment_gateway_adjustment configured branches ----

    def test_is_adjustment_false_when_invoice_outstanding(self):
        """A draft (unpaid, full outstanding) invoice means process-with-adjustment, not skip."""
        p = self._processor()
        self.assertFalse(p._is_payment_gateway_adjustment(self._gateway_mutation(-42.50)))

    def test_is_adjustment_false_when_invoice_missing(self):
        """No matching Purchase Invoice -> process normally (return False)."""
        p = self._processor()
        mutation = self._gateway_mutation(-42.50)
        mutation["invoiceNumber"] = "MOLLIE-DOES-NOT-EXIST"
        self.assertFalse(p._is_payment_gateway_adjustment(mutation))

    def test_is_adjustment_false_for_wrong_ledger(self):
        """Mutation on a different ledger than the gateway ledger is not gateway traffic."""
        p = self._processor()
        mutation = self._gateway_mutation(-42.50)
        mutation["ledgerId"] = "111111"
        self.assertFalse(p._is_payment_gateway_adjustment(mutation))

    def test_is_adjustment_false_for_wrong_prefix(self):
        """Invoice number without the gateway prefix is not gateway traffic."""
        p = self._processor()
        mutation = self._gateway_mutation(-42.50)
        mutation["invoiceNumber"] = "REGULAR-2025-1"
        self.assertFalse(p._is_payment_gateway_adjustment(mutation))

    def test_is_adjustment_true_when_invoice_already_paid(self):
        """When the matching invoice is fully paid (outstanding == 0), the mutation is skipped.

        We set the draft PI's outstanding_amount to 0 directly (the detection
        code reads outstanding_amount via get_all, not the document object).
        """
        frappe.db.set_value("Purchase Invoice", self.purchase_invoice.name, "outstanding_amount", 0)
        p = self._processor()
        self.assertTrue(p._is_payment_gateway_adjustment(self._gateway_mutation(-42.50)))

    # ---- _adjust_payment_gateway_amount math ----

    def test_adjust_amount_matches_invoice_total(self):
        """Gateway payment amount is rewritten to ``-abs(invoice.grand_total)``.

        The raw mutation amount (-50.00, e.g. gross-of-fees) is replaced by the
        invoice's net grand_total so the Payment Entry reconciles exactly.
        """
        p = self._processor()
        expected_total = self.purchase_invoice.grand_total
        self.assertGreater(expected_total, 0)

        adjusted = p._adjust_payment_gateway_amount(self._gateway_mutation(-50.00))

        # New object (deepcopy), not the original.
        self.assertEqual(adjusted["amount"], -abs(expected_total))
        self.assertEqual(adjusted["_original_amount"], 50.00)
        self.assertIn("Gateway fee reconciliation", adjusted["_adjustment_reason"])
        self.assertIn(self.purchase_invoice.name, adjusted["_adjustment_reason"])

    def test_adjust_amount_rewrites_first_row(self):
        """When the mutation has rows, the first row amount is also set to the invoice total."""
        p = self._processor()
        mutation = self._gateway_mutation(0)
        mutation["rows"] = [{"amount": 50.00, "ledgerId": self.GATEWAY_LEDGER_ID}]
        expected_total = self.purchase_invoice.grand_total

        adjusted = p._adjust_payment_gateway_amount(mutation)

        self.assertEqual(adjusted["amount"], -abs(expected_total))
        self.assertEqual(adjusted["rows"][0]["amount"], -abs(expected_total))
        # Original mutation must be untouched (deepcopy semantics).
        self.assertEqual(mutation["rows"][0]["amount"], 50.00)

    def test_adjust_amount_returns_original_when_invoice_missing(self):
        """No matching invoice -> original mutation returned unchanged (no adjustment keys)."""
        p = self._processor()
        mutation = self._gateway_mutation(-50.00)
        mutation["invoiceNumber"] = "MOLLIE-NOPE"
        result = p._adjust_payment_gateway_amount(mutation)
        self.assertIs(result, mutation)
        self.assertNotIn("_original_amount", result)


class TestExtractBankName(EnhancedTestCase):
    """_extract_bank_name_from_account: parse the bank name and guard on Supplier existence."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _processor(self):
        return PaymentProcessor(self.company)

    def test_none_returns_none(self):
        self.assertIsNone(self._processor()._extract_bank_name_from_account(None))

    def test_empty_returns_none(self):
        self.assertIsNone(self._processor()._extract_bank_name_from_account(""))

    def test_no_dash_separator_returns_none(self):
        """Account name without the ' - ' separator cannot be parsed -> None."""
        self.assertIsNone(self._processor()._extract_bank_name_from_account("PlainAccountName"))

    def test_parsed_bank_not_a_supplier_returns_none(self):
        """A parsed bank name that is NOT a Supplier returns None (avoids link errors).

        Uses a deliberately unique name so it cannot collide with a real Supplier.
        """
        account = "1100 - ZZZUnlikelyBankXYZ-9931 - Algemeen - NVV"
        p = self._processor()
        self.assertIsNone(p._extract_bank_name_from_account(account))
        self.assertTrue(
            any("not found as Supplier" in m for m in p.get_debug_info()),
            msg="missing-supplier branch must be logged",
        )

    def _make_supplier(self, bank_name):
        if frappe.db.exists("Supplier", bank_name):
            return bank_name
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = bank_name
        sup.supplier_group = frappe.db.get_value(
            "Supplier Group", {"is_group": 0}, "name", order_by="name"
        )
        sup.insert(ignore_permissions=True)
        return sup.name

    def test_parsed_bank_existing_supplier_returned(self):
        """When the parsed bank name exists as a Supplier, that Supplier name is returned."""
        bank_name = self._make_supplier("EBKH Coverage Bank Supplier")

        account = f"1100 - {bank_name} - 19.83.96.716 - Algemeen - NVV"
        result = self._processor()._extract_bank_name_from_account(account)
        self.assertEqual(result, bank_name)
