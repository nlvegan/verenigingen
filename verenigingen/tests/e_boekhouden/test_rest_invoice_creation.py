"""
Real integration tests for the sales/purchase INVOICE-CREATION cluster of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Target functions:
    _create_sales_invoice, _create_purchase_invoice, _setup_invoice_common,
    _save_and_submit_invoice, _process_invoice_line_items,
    _process_purchase_invoice_line_items, _enhance_sales_invoice_title,
    _consolidate_mixed_invoice_if_needed, _consolidate_purchase_invoice_and_save,
    create_invoice_line_for_tegenrekening

These feed SYNTHETIC eBoekhouden mutation dicts (no live API) and assert the
REAL Sales/Purchase Invoice documents that come out: customer/supplier,
posting date, grand_total, line items, title, is_return, docstatus.

Party resolution (resolve_customer/resolve_supplier) tries a live API first but
degrades gracefully: if a Customer/Supplier already exists with the matching
``eboekhouden_relation_code`` it is reused, so we pre-create parties keyed on the
relation id used in the mutations. Account/line-item resolution needs
``E-Boekhouden Ledger Mapping`` rows keyed on ledger_id == ledger_code so the
two-hop resolution (ledgerId -> ledger_code -> erpnext_account) lands on a real
account.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_invoice_creation
"""

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _consolidate_mixed_invoice_if_needed,
    _create_purchase_invoice,
    _create_sales_invoice,
    _enhance_sales_invoice_title,
    _setup_invoice_common,
    create_invoice_line_for_tegenrekening,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ABBR = "EBIC"
COMPANY = "TEST-EB-Invoice-Company"
# Ledger ids/codes for the synthetic mutations. We deliberately set
# ledger_id == ledger_code so resolve_ledger_code() and the subsequent
# map_grootboek_to_erpnext_account() lookup (which keys on ledger_id) both work.
INCOME_LEDGER = "8000"
EXPENSE_LEDGER = "4000"
RECEIVABLE_LEDGER = "1300"
PAYABLE_LEDGER = "1600"

CUSTOMER_RELATION = "EBCUST-IT-1"
SUPPLIER_RELATION = "EBSUPP-IT-1"


class _InvoiceClusterBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, ledger mappings, cost center, parties."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_parties()
        cls._ensure_fiscal_year()
        frappe.db.commit()

    # ---- bootstrap helpers (classmethods so they persist across the class) ----

    @classmethod
    def _ensure_company(cls):
        if frappe.db.exists("Company", COMPANY):
            cls.company = COMPANY
            return
        c = frappe.new_doc("Company")
        c.company_name = COMPANY
        c.abbr = ABBR
        c.default_currency = "EUR"
        c.country = "Netherlands"
        c.insert(ignore_permissions=True)
        cls.company = COMPANY

    @classmethod
    def _make_root(cls, root_type):
        existing = frappe.db.get_value(
            "Account",
            {"company": COMPANY, "root_type": root_type, "is_group": 1},
            "name",
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"EB {root_type} Root"
        r.company = COMPANY
        r.root_type = root_type
        r.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        r.is_group = 1
        r.insert(ignore_permissions=True)
        return r.name

    @classmethod
    def _make_account(cls, account_name, account_type, root_type):
        expected = f"{account_name} - {ABBR}"
        if frappe.db.exists("Account", expected):
            return expected
        a = frappe.new_doc("Account")
        a.account_name = account_name
        a.company = COMPANY
        a.account_type = account_type
        a.root_type = root_type
        a.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        a.is_group = 0
        a.parent_account = cls._make_root(root_type)
        a.insert(ignore_permissions=True)
        return a.name

    @classmethod
    def _ensure_accounts(cls):
        cls.receivable = cls._make_account("EB Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EB Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EB Sales Income", "Income Account", "Income")
        cls.expense = cls._make_account("EB Expenses", "Expense Account", "Expense")

        company = frappe.get_doc("Company", COMPANY)
        changed = False
        if not company.default_receivable_account:
            company.default_receivable_account = cls.receivable
            changed = True
        if not company.default_payable_account:
            company.default_payable_account = cls.payable
            changed = True
        if changed:
            company.save(ignore_permissions=True)

    @classmethod
    def _ensure_cost_center(cls):
        cls.cost_center = frappe.db.get_value(
            "Cost Center", {"company": COMPANY, "is_group": 0}, "name"
        )
        if cls.cost_center:
            return
        # Create a root + leaf cost center
        root_cc = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1}, "name")
        if not root_cc:
            rc = frappe.new_doc("Cost Center")
            rc.cost_center_name = COMPANY
            rc.company = COMPANY
            rc.is_group = 1
            rc.insert(ignore_permissions=True)
            root_cc = rc.name
        leaf = frappe.new_doc("Cost Center")
        leaf.cost_center_name = "Main"
        leaf.company = COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root_cc
        leaf.insert(ignore_permissions=True)
        cls.cost_center = leaf.name

    @classmethod
    def _make_ledger_map(cls, ledger_id, account, name):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}):
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = str(ledger_id)
        m.ledger_name = name
        m.erpnext_account = account
        m.insert(ignore_permissions=True)

    @classmethod
    def _ensure_ledger_mappings(cls):
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EB Sales Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EB Expenses")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EB Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EB Creditors")

    @classmethod
    def _ensure_parties(cls):
        if not frappe.db.exists("Customer", {"eboekhouden_relation_code": CUSTOMER_RELATION}):
            cust = frappe.new_doc("Customer")
            cust.customer_name = "EB Test Customer IT"
            cust.customer_type = "Individual"
            cust.default_currency = "EUR"
            cust.eboekhouden_relation_code = CUSTOMER_RELATION
            cust.insert(ignore_permissions=True)
        cls.customer = frappe.db.get_value(
            "Customer", {"eboekhouden_relation_code": CUSTOMER_RELATION}, "name"
        )

        if not frappe.db.exists("Supplier", {"eboekhouden_relation_code": SUPPLIER_RELATION}):
            supp = frappe.new_doc("Supplier")
            supp.supplier_name = "EB Test Supplier IT"
            supp.supplier_type = "Individual"
            supp.default_currency = "EUR"
            supp.eboekhouden_relation_code = SUPPLIER_RELATION
            supp.insert(ignore_permissions=True)
        cls.supplier = frappe.db.get_value(
            "Supplier", {"eboekhouden_relation_code": SUPPLIER_RELATION}, "name"
        )

    @classmethod
    def _ensure_fiscal_year(cls):
        """Ensure a Fiscal Year covering today() lists our test company.

        erpnext's global test setup restricts the current FY to _Test Company,
        so a date-stamped invoice against our company otherwise fails with
        'Date <today> is not in any active Fiscal Year'.
        """
        year = getdate().year
        # Find any non-test FY that covers the current year, else our own.
        fy_name = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()]},
            "name",
            order_by="creation desc",
        )
        if not fy_name:
            fy_name = f"EB-FY-{year}"
            if not frappe.db.exists("Fiscal Year", fy_name):
                fy = frappe.new_doc("Fiscal Year")
                fy.year = fy_name
                fy.year_start_date = f"{year}-01-01"
                fy.year_end_date = f"{year}-12-31"
                fy.insert(ignore_permissions=True)
        fy = frappe.get_doc("Fiscal Year", fy_name)
        if not any(c.company == COMPANY for c in fy.companies):
            fy.append("companies", {"company": COMPANY})
            fy.save(ignore_permissions=True)

    # ---- per-test helpers ----

    def _sales_mutation(self, **overrides):
        m = {
            "id": 900001,
            "type": 1,
            "date": nowdate(),
            "amount": 100.00,
            "relationId": CUSTOMER_RELATION,
            "invoiceNumber": "F-2024-001",
            "description": "Membership fee 2024",
            # Top-level ledgerId drives _resolve_receivable_account -> debit_to
            "ledgerId": RECEIVABLE_LEDGER,
            # No vatCode: BTW_CODE_MAP points tax codes at hard-coded account
            # names that live on a different company in the test DB, so adding
            # tax lines would trip ERPNext's cross-company-account guard. The
            # VAT-resolution path is exercised by invoice_helpers' own tests.
            "Regels": [
                {
                    "ledgerId": INCOME_LEDGER,
                    "amount": 100.00,
                    "quantity": 1,
                    "description": "Annual membership",
                }
            ],
        }
        m.update(overrides)
        return m

    def _purchase_mutation(self, **overrides):
        m = {
            "id": 900101,
            "type": 2,
            "date": nowdate(),
            "amount": 50.00,
            "relationId": SUPPLIER_RELATION,
            "invoiceNumber": "PINV-77",
            "description": "Office supplies",
            # Top-level ledgerId drives _resolve_payable_account -> credit_to
            "ledgerId": PAYABLE_LEDGER,
            "Regels": [
                {
                    "ledgerId": EXPENSE_LEDGER,
                    "amount": 50.00,
                    "quantity": 1,
                    "description": "Paper",
                }
            ],
        }
        m.update(overrides)
        return m


class TestSalesInvoiceCreation(_InvoiceClusterBase):
    def test_basic_sales_invoice_created_and_submitted(self):
        debug = []
        si = _create_sales_invoice(
            self._sales_mutation(id=900201), self.company, self.cost_center, debug
        )
        self.assertIsNotNone(si, f"Sales invoice was None. debug={debug}")
        self.assertEqual(si.doctype, "Sales Invoice")
        self.assertEqual(si.docstatus, 1, "Invoice should be submitted")
        self.assertEqual(si.customer, self.customer)
        self.assertEqual(si.company, self.company)
        self.assertEqual(getdate(si.posting_date), getdate(nowdate()))
        self.assertEqual(si.debit_to, self.receivable)
        self.assertFalse(si.is_return)
        # One line item at rate 100
        self.assertEqual(len(si.items), 1)
        self.assertEqual(flt(si.items[0].rate), 100.00)
        self.assertEqual(flt(si.items[0].qty), 1)
        # eBoekhouden tracking fields
        self.assertEqual(si.eboekhouden_mutation_nr, "900201")
        self.assertEqual(si.eboekhouden_invoice_number, "F-2024-001")
        # Title enhancement uses invoice number
        self.assertIn("Factuur F-2024-001", si.title)

    def test_sales_invoice_grand_total_matches_net(self):
        debug = []
        si = _create_sales_invoice(
            self._sales_mutation(id=900202), self.company, self.cost_center, debug
        )
        self.assertIsNotNone(si, f"debug={debug}")
        # Single 100 line, no tax -> net == grand
        self.assertEqual(flt(si.net_total), 100.00)
        self.assertEqual(flt(si.grand_total), 100.00, f"taxes={[t.as_dict() for t in si.taxes]}")

    def test_sales_credit_note_sets_is_return(self):
        debug = []
        mut = self._sales_mutation(id=900203, amount=-100.00)
        mut["Regels"][0]["amount"] = -100.00
        si = _create_sales_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(si, f"debug={debug}")
        self.assertEqual(si.is_return, 1, "Negative amount must flip is_return")
        self.assertEqual(si.docstatus, 1)
        # Credit note: qty negative, rate positive, total negative
        self.assertLess(flt(si.items[0].qty), 0)
        self.assertEqual(flt(si.items[0].rate), 100.00)
        self.assertLess(flt(si.grand_total), 0)

    def test_sales_invoice_without_ledger_id_falls_back_to_company_default(self):
        # No top-level ledgerId: _resolve_receivable_account returns None and
        # ERPNext picks the company's default receivable account.
        debug = []
        mut = self._sales_mutation(id=900205)
        mut.pop("ledgerId")
        si = _create_sales_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(si, f"debug={debug}")
        default_recv = frappe.db.get_value("Company", self.company, "default_receivable_account")
        self.assertEqual(si.debit_to, default_recv)
        self.assertTrue(any("No ledgerID found" in d for d in debug))

    def test_sales_invoice_no_invoice_number_no_title_enhancement(self):
        debug = []
        mut = self._sales_mutation(id=900204)
        mut.pop("invoiceNumber")
        si = _create_sales_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(si, f"debug={debug}")
        self.assertTrue(any("No invoice number available" in d for d in debug))
        # eboekhouden_invoice_number stays empty
        self.assertFalse(si.eboekhouden_invoice_number)

    def test_multi_line_sales_invoice_two_positive_lines(self):
        debug = []
        mut = self._sales_mutation(id=900206)
        mut["amount"] = 175.00
        mut["Regels"] = [
            {"ledgerId": INCOME_LEDGER, "amount": 100.0, "quantity": 1, "description": "Line A"},
            {"ledgerId": INCOME_LEDGER, "amount": 75.0, "quantity": 1, "description": "Line B"},
        ]
        si = _create_sales_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(si, f"debug={debug}")
        self.assertEqual(len(si.items), 2)
        self.assertEqual(flt(si.grand_total), 175.00)
        self.assertFalse(si.is_return)

    def test_full_path_mixed_invoice_consolidated_to_return(self):
        # Mixed positive/negative lines with NEGATIVE net through the full
        # _create_sales_invoice path: _detect_credit_note_improved returns
        # is_return=False (mixed) so individual signs are preserved, then
        # _consolidate_mixed_invoice_if_needed nets them and flips is_return.
        debug = []
        mut = self._sales_mutation(id=900207)
        mut["amount"] = 0  # force line-item analysis path in credit-note detection
        mut["Regels"] = [
            {"ledgerId": INCOME_LEDGER, "amount": 40.0, "quantity": 1, "description": "Charge"},
            {"ledgerId": INCOME_LEDGER, "amount": -70.0, "quantity": 1, "description": "Refund"},
        ]
        si = _create_sales_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(si, f"debug={debug}")
        # Consolidated to a single net-(-30) return line
        self.assertEqual(len(si.items), 1)
        self.assertEqual(si.is_return, 1)
        self.assertEqual(flt(si.grand_total), -30.0)
        self.assertIn("CONSOLIDATED MIXED INVOICE", si.items[0].description)


class TestPurchaseInvoiceCreation(_InvoiceClusterBase):
    def test_basic_purchase_invoice_created_and_submitted(self):
        debug = []
        pi = _create_purchase_invoice(
            self._purchase_mutation(id=900301), self.company, self.cost_center, debug
        )
        self.assertIsNotNone(pi, f"Purchase invoice was None. debug={debug}")
        self.assertEqual(pi.doctype, "Purchase Invoice")
        self.assertEqual(pi.docstatus, 1)
        self.assertEqual(pi.supplier, self.supplier)
        self.assertEqual(pi.credit_to, self.payable)
        self.assertEqual(pi.bill_no, "PINV-77")
        self.assertEqual(len(pi.items), 1)
        self.assertEqual(flt(pi.items[0].rate), 50.00)
        self.assertEqual(pi.eboekhouden_mutation_nr, "900301")

    def test_purchase_invoice_grand_total_matches_net(self):
        debug = []
        pi = _create_purchase_invoice(
            self._purchase_mutation(id=900302), self.company, self.cost_center, debug
        )
        self.assertIsNotNone(pi, f"debug={debug}")
        self.assertEqual(flt(pi.net_total), 50.00)
        self.assertEqual(flt(pi.grand_total), 50.00, f"taxes={[t.as_dict() for t in pi.taxes]}")

    def test_purchase_credit_note_sets_is_return(self):
        debug = []
        mut = self._purchase_mutation(id=900303, amount=-50.00)
        mut["Regels"][0]["amount"] = -50.00
        pi = _create_purchase_invoice(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(pi, f"debug={debug}")
        self.assertEqual(pi.is_return, 1)
        self.assertEqual(pi.docstatus, 1)
        self.assertLess(flt(pi.items[0].qty), 0)
        self.assertEqual(flt(pi.items[0].rate), 50.00)


class TestSetupInvoiceCommon(_InvoiceClusterBase):
    def test_common_fields_populated_for_normal_invoice(self):
        debug = []
        si = frappe.new_doc("Sales Invoice")
        result = _setup_invoice_common(si, self._sales_mutation(id=900401), self.company, debug)
        self.assertIsNotNone(result)
        is_credit_note, effective = result
        self.assertFalse(is_credit_note)
        self.assertEqual(effective, 100.00)
        self.assertEqual(si.company, self.company)
        self.assertEqual(si.currency, "EUR")
        self.assertEqual(flt(si.conversion_rate), 1.0)
        self.assertEqual(getdate(si.posting_date), getdate(nowdate()))
        self.assertEqual(si.eboekhouden_mutation_nr, "900401")
        self.assertEqual(si.remarks, "Membership fee 2024")
        # default 30-day payment terms -> due date 30 days out
        from frappe.utils import add_days

        self.assertEqual(getdate(si.due_date), getdate(add_days(nowdate(), 30)))

    def test_common_detects_credit_note_from_negative_amount(self):
        debug = []
        pi = frappe.new_doc("Purchase Invoice")
        mut = self._purchase_mutation(id=900402, amount=-99.0)
        result = _setup_invoice_common(pi, mut, self.company, debug)
        self.assertIsNotNone(result)
        is_credit_note, effective = result
        self.assertTrue(is_credit_note)
        self.assertEqual(effective, -99.0)
        self.assertEqual(pi.is_return, 1)


class TestEnhanceSalesInvoiceTitle(_InvoiceClusterBase):
    def test_title_uses_customer_and_sanitised_invoice_number(self):
        debug = []
        si = frappe.new_doc("Sales Invoice")
        si.customer_name = "Jane Member"
        _enhance_sales_invoice_title(si, "2024/07/15", "desc", debug)
        # slashes become dashes
        self.assertEqual(si.title, "Jane Member - Factuur 2024-07-15")

    def test_title_skipped_without_invoice_number(self):
        debug = []
        si = frappe.new_doc("Sales Invoice")
        si.customer_name = "Jane Member"
        _enhance_sales_invoice_title(si, None, "desc", debug)
        self.assertFalse(si.title)
        self.assertTrue(any("No invoice number" in d for d in debug))


class TestConsolidateMixedInvoice(_InvoiceClusterBase):
    def _mixed_sales_invoice(self):
        si = frappe.new_doc("Sales Invoice")
        si.company = self.company
        si.customer = self.customer
        si.debit_to = self.receivable
        si.currency = "EUR"
        si.conversion_rate = 1.0
        si.posting_date = nowdate()
        si.append(
            "items",
            {"item_name": "Pos", "description": "Pos", "qty": 1, "rate": 50.0, "uom": "Unit", "cost_center": self.cost_center},
        )
        si.append(
            "items",
            {"item_name": "Neg", "description": "Neg", "qty": -1, "rate": 80.0, "uom": "Unit", "cost_center": self.cost_center},
        )
        return si

    def test_mixed_negative_total_consolidated_to_single_return_line(self):
        debug = []
        si = self._mixed_sales_invoice()
        # net = 50 - 80 = -30
        _consolidate_mixed_invoice_if_needed(si, self.cost_center, self.company, debug)
        self.assertEqual(len(si.items), 1)
        self.assertEqual(si.is_return, 1)
        self.assertEqual(flt(si.items[0].qty), -1)
        self.assertEqual(flt(si.items[0].rate), 30.0)
        self.assertIn("CONSOLIDATED MIXED INVOICE", si.items[0].description)

    def test_positive_total_left_untouched(self):
        debug = []
        si = self._mixed_sales_invoice()
        # make it net positive: 50 + 80
        si.items[1].qty = 1
        before = len(si.items)
        _consolidate_mixed_invoice_if_needed(si, self.cost_center, self.company, debug)
        self.assertEqual(len(si.items), before)
        self.assertFalse(si.is_return)


class TestCreateInvoiceLineForTegenrekening(_InvoiceClusterBase):
    """create_invoice_line_for_tegenrekening is a DEPRECATED delegator to
    SmartTegenrekeningMapper, which is hard-coupled to a hard-coded default
    company ("Ned Ver Vegan") and resolves accounts within THAT company. We
    therefore assert its deterministic contract: a missing code throws, and a
    code with no resolvable account/item in the mapper's company throws with the
    documented mapping-required message (it must NEVER silently fabricate a
    fallback account)."""

    def test_missing_code_raises(self):
        with self.assertRaises(frappe.ValidationError):
            create_invoice_line_for_tegenrekening(
                tegenrekening_code=None,
                amount=10.0,
                description="x",
                transaction_type="purchase",
            )

    def test_unmappable_code_raises_not_silent_fallback(self):
        # A code that exists in no company / no ledger mapping must raise rather
        # than quietly returning a line pointed at a fabricated account.
        with self.assertRaises(frappe.ValidationError):
            create_invoice_line_for_tegenrekening(
                tegenrekening_code="ZZZ-NO-SUCH-CODE-999999",
                amount=10.0,
                description="x",
                transaction_type="purchase",
            )

    def test_returns_well_formed_line_when_account_resolvable(self):
        # If the mapper's default company has the income ledger we created here
        # (i.e. the default company IS our test company on this site), assert the
        # line shape. Otherwise skip — the function's account resolution is bound
        # to a company we don't control.
        from verenigingen.e_boekhouden.utils.smart_tegenrekening_mapper import (
            SmartTegenrekeningMapper,
        )

        mapper = SmartTegenrekeningMapper()
        if not frappe.db.exists("Company", mapper.company):
            self.skipTest(f"Mapper default company {mapper.company} not present on this site")
        try:
            line = create_invoice_line_for_tegenrekening(
                tegenrekening_code=INCOME_LEDGER,
                amount=42.0,
                description="Donation",
                transaction_type="sales",
            )
        except frappe.ValidationError:
            self.skipTest(
                f"Ledger {INCOME_LEDGER} not resolvable in mapper company {mapper.company}"
            )
        self.assertIsInstance(line, dict)
        self.assertEqual(flt(line["qty"]), 1)
        self.assertEqual(flt(line["rate"]), 42.0)
        self.assertEqual(line["description"], "Donation")
