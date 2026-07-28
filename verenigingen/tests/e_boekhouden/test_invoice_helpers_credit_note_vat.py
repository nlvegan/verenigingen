"""
Money-math coverage for the LIVE credit-note / correction-line VAT path in
``verenigingen/e_boekhouden/utils/invoice_helpers.py``.

These tests drive the exact sequence production uses for every eBoekhouden
sales/purchase invoice (``eboekhouden_rest_full_migration._process_invoice_line_items``):

    regels -> _convert_regels_for_credit_note (credit notes only)
           -> process_line_items   (builds invoice.items)
           -> add_tax_lines        (builds invoice.taxes)

Nothing is mocked. ``BTW_CODE_MAP`` is repointed at a real Tax account on this
module's own company -- that is DATA CONFIGURATION (the map is a static lookup
table of Dutch VAT codes to account names hardcoded for the NVV production
company), not business logic.

The invariant under test is the one that decides whether the general ledger
balances: **the sign of the VAT booked on an invoice must match the sign of that
invoice's net amount.** A credit note whose net is -100 must carry -21 of VAT,
never +21; otherwise the customer/supplier balance is wrong by twice the VAT and
the VAT return is overstated.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_invoice_helpers_credit_note_vat
"""

import unittest

import frappe
from frappe.utils import flt

from verenigingen.e_boekhouden.utils import invoice_helpers as ih
from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _convert_regels_for_credit_note,
)
from verenigingen.e_boekhouden.utils.invoice_helpers import add_tax_lines, process_line_items
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

COMPANY = "TEST EBkh CreditVAT Co"
ABBR = "EBCV"

# Globally unique ledger code (the mapping doctype has no company column).
SALES_LEDGER = "7400008"
BTW_CODE = "EBCV_HOOG_VERK_21"


class _InvoiceStub:
    """Stands in for the Sales/Purchase Invoice document while its child tables
    are being built.

    ``process_line_items`` and ``add_tax_lines`` only ever read ``company`` /
    ``doctype`` / ``is_return`` / ``cost_center`` and append plain dicts to
    ``items`` / ``taxes``; using a real Document here would force a premature
    save (and therefore ERPNext's own recalculation) before the helpers under
    test have finished. The dicts appended are exactly what production hands to
    ERPNext, so the arithmetic asserted below is the arithmetic that reaches the
    ledger.
    """

    def __init__(self, company, doctype="Sales Invoice", is_return=False, cost_center=None):
        self.company = company
        self.doctype = doctype
        self.is_return = is_return
        self.cost_center = cost_center
        self.items = []
        self.taxes = []

    def append(self, table, row):
        getattr(self, table).append(row)
        return row

    # -- derived totals, computed the way ERPNext computes them --
    @property
    def net_total(self):
        return flt(sum(flt(i["qty"]) * flt(i["rate"]) for i in self.items), 2)

    @property
    def total_taxes(self):
        return flt(sum(flt(t["tax_amount"]) for t in self.taxes), 2)


class _CreditVATBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls.income = cls._account("EBCV Omzet", "Income Account", "Income")
        cls.expense = cls._account("EBCV Kosten", "Expense Account", "Expense")
        cls.btw_account = cls._account("EBCV BTW af te dragen", "Tax", "Liability")
        cls._map_ledger(SALES_LEDGER, cls.income, "EBCV Omzet")
        frappe.db.commit()

    @classmethod
    def _ensure_company(cls):
        if not frappe.db.exists("Company", COMPANY):
            c = frappe.new_doc("Company")
            c.company_name = COMPANY
            c.abbr = ABBR
            c.default_currency = "EUR"
            c.country = "Netherlands"
            c.insert()
        cls.company = COMPANY

    @classmethod
    def _root(cls, root_type):
        existing = frappe.db.get_value(
            "Account", {"company": COMPANY, "root_type": root_type, "is_group": 1}, "name"
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"{ABBR} {root_type} Root"
        r.company = COMPANY
        r.root_type = root_type
        r.report_type = "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        r.is_group = 1
        r.insert()
        return r.name

    @classmethod
    def _account(cls, account_name, account_type, root_type):
        full = f"{account_name} - {ABBR}"
        if frappe.db.exists("Account", full):
            return full
        a = frappe.new_doc("Account")
        a.account_name = account_name
        a.company = COMPANY
        a.account_type = account_type
        a.root_type = root_type
        a.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        a.is_group = 0
        a.parent_account = cls._root(root_type)
        a.insert()
        return a.name

    @classmethod
    def _map_ledger(cls, ledger_id, account, label):
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "name")
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", account)
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = str(ledger_id)
        m.ledger_code = str(ledger_id)
        m.ledger_name = label
        m.erpnext_account = account
        m.insert()

    def setUp(self):
        super().setUp()
        # Point a 21% output-VAT code at THIS company's BTW account. The shipped
        # map hardcodes NVV production account names, which do not exist here.
        original = dict(ih.BTW_CODE_MAP)
        ih.BTW_CODE_MAP[BTW_CODE] = {
            "rate": 21,
            "type": "Output VAT",
            "account_name": self.btw_account,
            "account_fallback": None,
            "description": "EBCV BTW 21%",
        }
        self.addCleanup(lambda: (ih.BTW_CODE_MAP.clear(), ih.BTW_CODE_MAP.update(original)))

        # The eBoekhouden item-naming path attempts an API session token while
        # resolving items and logs a connection failure on a network-less test
        # host. It is orthogonal to the arithmetic under test (and pre-existing:
        # the neighbouring e_boekhouden suites hit it too), so it is declared
        # expected rather than left to trip the Error Log guard in tearDown.
        self.expectErrorLog("Error getting session token")

    # ---- helpers ----

    @staticmethod
    def _regel(amount, quantity=1, description="EBCV line"):
        return {
            "ledgerId": SALES_LEDGER,
            "amount": amount,
            "quantity": quantity,
            "vatCode": BTW_CODE,
            "description": description,
        }

    def _build(self, regels, is_return=False, invoice_type="sales"):
        """Run the production sequence and return the populated invoice stub."""
        debug = []
        if is_return:
            regels = _convert_regels_for_credit_note(regels, invoice_type, debug)
        invoice = _InvoiceStub(
            self.company,
            doctype="Sales Invoice" if invoice_type == "sales" else "Purchase Invoice",
            is_return=is_return,
        )
        self.assertTrue(process_line_items(invoice, regels, invoice_type, None, debug))
        totals = add_tax_lines(invoice, regels, invoice_type, debug)
        return invoice, totals, debug


# ---------------------------------------------------------------------------
# Baseline: the normal-invoice arithmetic must stay correct.
# ---------------------------------------------------------------------------
class TestNormalInvoiceVat(_CreditVATBase):
    def test_positive_invoice_books_positive_net_and_positive_vat(self):
        invoice, totals, _ = self._build([self._regel(100.00)])

        self.assertAlmostEqual(invoice.net_total, 100.00, places=2)
        self.assertAlmostEqual(totals["net_amount"], 100.00, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 21.00, places=2)
        self.assertAlmostEqual(invoice.total_taxes, 21.00, places=2)
        self.assertEqual(invoice.taxes[0]["account_head"], self.btw_account)
        # Grand total is net + VAT.
        self.assertAlmostEqual(invoice.net_total + invoice.total_taxes, 121.00, places=2)

    def test_vat_is_aggregated_per_code_across_lines(self):
        """Two lines under the same BTW code produce ONE tax row on the summed
        taxable base -- not one row per line (which would still total correctly
        today but breaks the moment rounding differs per line)."""
        invoice, totals, _ = self._build([self._regel(100.00), self._regel(50.00)])

        self.assertAlmostEqual(invoice.net_total, 150.00, places=2)
        self.assertEqual(len(invoice.taxes), 1, "one tax row per BTW code")
        self.assertAlmostEqual(totals["tax_amount"], 31.50, places=2)

    def test_quantity_multiplies_the_taxable_base(self):
        """The VAT base is qty x rate, not rate. A regression that ignored
        quantity would under-declare VAT on every multi-unit line."""
        invoice, totals, _ = self._build([self._regel(100.00, quantity=3)])

        self.assertAlmostEqual(invoice.net_total, 300.00, places=2)
        self.assertAlmostEqual(totals["net_amount"], 300.00, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 63.00, places=2)


# ---------------------------------------------------------------------------
# Credit notes: the sign invariant.
# ---------------------------------------------------------------------------
class TestCreditNoteVatSign(_CreditVATBase):
    def test_credit_note_line_items_are_negative(self):
        """Sanity anchor for the two tests below: process_line_items DOES get the
        item side right for a credit note (negative qty, positive rate)."""
        invoice, _, _ = self._build([self._regel(-100.00)], is_return=True)

        self.assertEqual(len(invoice.items), 1)
        self.assertLess(flt(invoice.items[0]["qty"]), 0, "credit-note qty must be negative")
        self.assertGreater(flt(invoice.items[0]["rate"]), 0, "ERPNext rates are always positive")
        self.assertAlmostEqual(invoice.net_total, -100.00, places=2)

    @unittest.expectedFailure
    def test_credit_note_vat_has_the_same_sign_as_its_net(self):
        """PRODUCTION BUG (invoice_helpers.py:246 ``line_qty = abs(line_qty)``).

        ``add_tax_lines`` unconditionally takes the absolute value of the line
        quantity, so a credit note -- whose amounts were already flipped positive
        by ``_convert_regels_for_credit_note`` -- yields a POSITIVE taxable base
        and a POSITIVE VAT amount, while ``process_line_items`` correctly built
        NEGATIVE line items.

        Result for a EUR 100 credit note at 21%:
            net_total   = -100.00   (correct)
            total_taxes = + 21.00   (WRONG, must be -21.00)
            grand_total = - 79.00   (WRONG, must be -121.00)

        The customer balance is left EUR 42 short and the VAT return is
        overstated by EUR 21 per credit note.

        Marked expectedFailure so the suite stays green while the bug stands; it
        will report an UNEXPECTED SUCCESS (a failure) the moment the bug is fixed.
        """
        invoice, totals, _ = self._build([self._regel(-100.00)], is_return=True)

        self.assertAlmostEqual(invoice.net_total, -100.00, places=2)
        self.assertLess(
            invoice.total_taxes,
            0,
            f"VAT on a credit note must be negative, got {invoice.total_taxes}",
        )
        self.assertAlmostEqual(invoice.net_total + invoice.total_taxes, -121.00, places=2)
        self.assertAlmostEqual(totals["net_amount"], -100.00, places=2)

    def test_partial_correction_line_reduces_the_taxable_base(self):
        """A negative correction line inside a NORMAL invoice nets against the
        positive lines of the same BTW code before VAT is computed.

        +100 and -40 under one 21% code => base 60.00 => VAT 12.60.
        """
        invoice, totals, _ = self._build([self._regel(100.00), self._regel(-40.00, description="korting")])

        self.assertAlmostEqual(invoice.net_total, 60.00, places=2)
        self.assertAlmostEqual(totals["net_amount"], 60.00, places=2)
        self.assertEqual(len(invoice.taxes), 1)
        self.assertAlmostEqual(totals["tax_amount"], 12.60, places=2)

    @unittest.expectedFailure
    def test_net_negative_btw_group_still_books_its_vat_reversal(self):
        """PRODUCTION BUG (invoice_helpers.py:281 ``data["taxable_amount"] > 0``).

        When the correction lines of a BTW code OUTWEIGH its positive lines, the
        code's taxable base goes negative and the guard drops the tax row
        entirely -- so the invoice books a negative net with ZERO VAT instead of
        the negative VAT that belongs to it.

        For +40 and -100 under one 21% code:
            net_total (booked) = -60.00
            correct VAT        = -12.60
            actual VAT         =   0.00

        The VAT reversal is silently lost: the VAT payable account keeps EUR 12.60
        that was never owed, and the invoice's grand total is EUR 12.60 too high.

        Marked expectedFailure so the suite stays green while the bug stands; it
        will report an UNEXPECTED SUCCESS (a failure) once the bug is fixed.
        """
        invoice, totals, _ = self._build([self._regel(40.00), self._regel(-100.00, description="creditatie")])

        self.assertAlmostEqual(invoice.net_total, -60.00, places=2)
        self.assertAlmostEqual(totals["net_amount"], -60.00, places=2)
        self.assertAlmostEqual(
            totals["tax_amount"],
            -12.60,
            places=2,
            msg=f"a net-negative BTW group must reverse its VAT, got {totals['tax_amount']}",
        )

    def test_exempt_codes_produce_no_vat_but_still_count_in_net(self):
        """GEEN / VRIJ / empty codes are VAT-exempt: no tax row, but the line
        still contributes to the net amount."""
        regels = [dict(self._regel(100.00), vatCode="GEEN"), dict(self._regel(50.00), vatCode="VRIJ")]
        invoice, totals, _ = self._build(regels)

        self.assertEqual(invoice.taxes, [], "exempt codes must not produce a tax row")
        self.assertAlmostEqual(totals["tax_amount"], 0.0, places=2)
        self.assertAlmostEqual(totals["net_amount"], 150.00, places=2)
        self.assertAlmostEqual(invoice.net_total, 150.00, places=2)

    def test_unknown_btw_code_is_skipped_without_inventing_vat(self):
        """An unrecognised BTW code must NOT silently fall back to a default
        rate -- inventing VAT on an import is worse than importing none."""
        regels = [dict(self._regel(100.00), vatCode="EBCV_NOT_A_REAL_CODE")]
        invoice, totals, _ = self._build(regels)

        self.assertEqual(invoice.taxes, [])
        self.assertAlmostEqual(totals["tax_amount"], 0.0, places=2)
        # The line itself is still booked.
        self.assertAlmostEqual(totals["net_amount"], 100.00, places=2)
