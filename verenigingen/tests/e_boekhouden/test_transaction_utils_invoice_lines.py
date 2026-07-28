"""
Coverage for the INVOICE LINE-ITEM half of
``verenigingen/e_boekhouden/utils/transaction_utils.py`` -- the region that
``test_transaction_utils_coverage.py`` declares out of scope ("the full SI/PI
happy paths ... are exercised by the REST migration suites").

They are not. Nothing exercises them, and this module shows why: the line-item
loop cannot execute at all (see ``TestSalesInvoiceLineItems`` below).

REACHABILITY NOTE -- read before acting on the failures here
------------------------------------------------------------
``transaction_utils.py`` has NO production importer. ``create_sales_invoice_impl``,
``create_purchase_invoice_impl`` and ``create_journal_entry_impl`` are called
only from tests; the live eBoekhouden import runs through
``eboekhouden_rest_full_migration`` / ``utils/processors/``. The defects pinned
below are therefore LATENT, not actively corrupting ledgers -- but they are
landmines for anyone who wires this module up, and one of them is the reason the
module has never been observed working.

Also covered: the third (name-pattern) fallback of ``get_mapped_account_impl``,
which the existing suite skips, and its lack of a company guard.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_transaction_utils_invoice_lines
"""

import unittest

import frappe
from frappe.utils import nowdate

from verenigingen.e_boekhouden.utils.transaction_utils import (
    create_sales_invoice_impl,
    get_mapped_account_impl,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

COMPANY = "TEST EBkh TxLines Co"
OTHER_COMPANY = "TEST EBkh TxLines Other Co"
ABBR = "EBTL"
OTHER_ABBR = "EBTO"

SALES_LEDGER = "7500008"


class _MigrationDocStub:
    """Supplies exactly the surface ``create_sales_invoice_impl`` touches.

    Customer creation is delegated to the real ``RelationMigrationService`` via
    a real E-Boekhouden Migration document in the tests that need it; this stub
    only stands in where the account-resolution helpers are the subject.
    """

    def __init__(self, company, mapped=None):
        self.company = company
        self._mapped = mapped or {}

    def get_mapped_account(self, code):
        return self._mapped.get(code)


class _TxLinesBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._company(COMPANY, ABBR)
        cls._company(OTHER_COMPANY, OTHER_ABBR)
        cls.income = cls._account(COMPANY, ABBR, "EBTL Omzet", "Income Account", "Income")
        cls._map_ledger(SALES_LEDGER, cls.income, "EBTL Omzet")
        frappe.db.commit()

    @classmethod
    def _company(cls, name, abbr):
        if frappe.db.exists("Company", name):
            return name
        c = frappe.new_doc("Company")
        c.company_name = name
        c.abbr = abbr
        c.default_currency = "EUR"
        c.country = "Netherlands"
        c.insert()
        return name

    @classmethod
    def _root(cls, company, abbr, root_type):
        existing = frappe.db.get_value(
            "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"{abbr} {root_type} Root"
        r.company = company
        r.root_type = root_type
        r.report_type = "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        r.is_group = 1
        r.insert()
        return r.name

    @classmethod
    def _account(cls, company, abbr, account_name, account_type, root_type, account_number=None):
        full = f"{account_number + ' - ' if account_number else ''}{account_name} - {abbr}"
        if frappe.db.exists("Account", full):
            return full
        a = frappe.new_doc("Account")
        a.account_name = account_name
        a.company = company
        a.account_type = account_type
        a.root_type = root_type
        a.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        a.is_group = 0
        if account_number:
            a.account_number = account_number
        a.parent_account = cls._root(company, abbr, root_type)
        a.insert()
        return a.name

    @classmethod
    def _map_ledger(cls, ledger_id, account, label):
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "name")
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", account)
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "ledger_code", str(ledger_id))
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = str(ledger_id)
        m.ledger_code = str(ledger_id)
        m.ledger_name = label
        m.erpnext_account = account
        m.insert()


# ---------------------------------------------------------------------------
# get_mapped_account_impl: the fallbacks the existing suite does not reach.
# ---------------------------------------------------------------------------
class TestGetMappedAccountFallbacks(_TxLinesBase):
    def test_name_pattern_fallback_resolves_prefixed_account(self):
        """Third fallback: no ledger mapping, no eboekhouden_grootboek_nummer and
        no account_number -- resolve by the ``<code> - % - <abbr>`` name shape
        that a Chart-of-Accounts import produces.

        The account below carries the code only inside its NAME (account_number
        is unset), so fallbacks 1 and 2 must both miss.
        """
        account = self._account(COMPANY, ABBR, "9101 - EBTL Naampatroon", "Income Account", "Income")
        stub = _MigrationDocStub(COMPANY)

        self.assertEqual(get_mapped_account_impl(stub, "9101"), account)

    def test_unknown_code_returns_none_rather_than_guessing(self):
        """A code that matches nothing must resolve to None so the caller can
        route the line to suspense -- never to an arbitrary account."""
        stub = _MigrationDocStub(COMPANY)
        self.assertIsNone(get_mapped_account_impl(stub, "EBTL-NO-SUCH-CODE-9999"))

    def test_name_pattern_fallback_is_scoped_to_the_migration_company(self):
        """Fallbacks 2 and 3 filter on ``migration_doc.company``: an identically
        coded account belonging to ANOTHER company must not be returned.

        Booking a sibling company's account onto an invoice is rejected by
        ERPNext at save time in the best case and silently mis-posts in the
        worst, so this isolation is load-bearing.
        """
        other = self._account(
            OTHER_COMPANY, OTHER_ABBR, "9102 - EBTL Andere Firma", "Income Account", "Income"
        )
        self.assertTrue(frappe.db.exists("Account", other))

        stub = _MigrationDocStub(COMPANY)
        self.assertIsNone(
            get_mapped_account_impl(stub, "9102"),
            "an account owned by another company must not be resolved",
        )

    @unittest.expectedFailure
    def test_ledger_mapping_hit_is_also_scoped_to_the_migration_company(self):
        """PRODUCTION DEFECT (transaction_utils.py:463-468).

        The FIRST lookup queries "E-Boekhouden Ledger Mapping" by ledger_code
        with NO company filter and returns its ``erpnext_account`` verbatim. The
        mapping doctype has no company column, so on a bench importing more than
        one company the mapping resolves to whichever company's account was
        linked first -- and ``get_mapped_account_impl`` hands that foreign
        account back regardless of ``migration_doc.company``.

        Fallbacks 2 and 3 (asserted above) DO filter on company; only the
        mapping-table hit does not, so the behaviour is inconsistent within a
        single function.

        Marked expectedFailure: it will report an UNEXPECTED SUCCESS once a
        company guard is added to the mapping branch.
        """
        # SALES_LEDGER is mapped to an account owned by COMPANY.
        stub = _MigrationDocStub(OTHER_COMPANY)
        self.assertIsNone(
            get_mapped_account_impl(stub, SALES_LEDGER),
            "a mapping pointing at another company's account must not be returned",
        )


# ---------------------------------------------------------------------------
# create_sales_invoice_impl: the line-item loop.
# ---------------------------------------------------------------------------
class TestSalesInvoiceLineItems(_TxLinesBase):
    def _migration(self):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = f"EBTL {frappe.generate_hash()[:8]}"
        doc.company = COMPANY
        doc.migration_status = "Draft"
        doc.insert()
        return doc

    @staticmethod
    def _invoice_data(**overrides):
        data = {
            "Datum": nowdate(),
            "Factuurnummer": f"EBTL-{frappe.generate_hash()[:6]}",
            "Relatie": {"ID": "EBTL-REL-1", "Bedrijf": "EBTL Klant BV", "Contactpersoon": ""},
            "Regels": [
                {
                    "Omschrijving": "EBTL dienst",
                    "Aantal": 2,
                    "PrijsExclBTW": 50.00,
                    "TegenrekeningCode": SALES_LEDGER,
                }
            ],
        }
        data.update(overrides)
        return data

    @unittest.expectedFailure
    def test_invoice_with_line_items_is_created(self):
        """PRODUCTION DEFECT (transaction_utils.py:282 and :401) -- WRONG ARITY.

        Both invoice builders call::

            account_code = _get_ledger_code_from_id(raw_tegenrekening, debug_info)

        but the callee's signature is
        ``_get_ledger_code_from_id(ledger_id, company, debug_info)``
        (eboekhouden_rest_full_migration.py:1835). The debug list is bound to
        ``company`` and the required ``debug_info`` is missing, so the very first
        line item raises::

            TypeError: _get_ledger_code_from_id() missing 1 required positional
                       argument: 'debug_info'

        The function's blanket ``except Exception`` converts that into
        ``{"success": False, "error": "<TypeError text>"}``, so an operator sees
        a Python type error where an accounting error should be. NO invoice with
        line items can ever be produced by these functions -- everything after
        the loop (rate/qty math, income-account assignment, the BTW tax row, the
        save/submit) is unreachable.

        Every other in-repo call site passes three arguments
        (eboekhouden_rest_full_migration.py:2489 and :2762), so the two here are
        the outliers.

        Marked expectedFailure: it will report an UNEXPECTED SUCCESS once the
        call sites are corrected.
        """
        migration = self._migration()
        result = create_sales_invoice_impl(migration, self._invoice_data())

        self.assertTrue(result["success"], result.get("error"))
        si = frappe.get_doc("Sales Invoice", result["sales_invoice"])
        self.assertEqual(len(si.items), 1)
        self.assertAlmostEqual(float(si.items[0].qty), 2.0, places=2)
        self.assertAlmostEqual(float(si.items[0].rate), 50.0, places=2)
        self.assertAlmostEqual(float(si.net_total), 100.0, places=2)
        self.assertEqual(si.items[0].income_account, self.income)

    def test_unmapped_tegenrekening_fails_without_persisting_a_partial_invoice(self):
        """A line whose TegenrekeningCode has no ledger mapping must abort the
        whole invoice -- structurally, with nothing written.

        Booking a line to a guessed account would corrupt the ledger, and a
        half-built Sales Invoice would be worse still. The document is only saved
        after the loop completes, so this invariant holds both today and after
        the arity defect above is fixed.
        """
        migration = self._migration()
        data = self._invoice_data(
            Regels=[
                {
                    "Omschrijving": "EBTL onbekende tegenrekening",
                    "Aantal": 1,
                    "PrijsExclBTW": 10.00,
                    "TegenrekeningCode": "7599999",  # deliberately unmapped
                }
            ]
        )
        invoice_number = data["Factuurnummer"]

        result = create_sales_invoice_impl(migration, data)

        self.assertFalse(result["success"])
        self.assertIsInstance(result["error"], str)
        self.assertEqual(
            frappe.get_all("Sales Invoice", filters={"eboekhouden_invoice_number": invoice_number}),
            [],
            "a line-item failure must not persist a partial Sales Invoice",
        )


class TestCreditNoteDetectionPayloadShape(_TxLinesBase):
    """``_detect_credit_note_improved`` decides ``is_return`` for both invoice
    builders (transaction_utils.py:253 / :372). It is asserted here against the
    two payload shapes those builders can receive."""

    @staticmethod
    def _detect(payload):
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            _detect_credit_note_improved,
        )

        return _detect_credit_note_improved(payload, [])

    def test_rest_shape_negative_line_is_detected_as_credit_note(self):
        """Guard on the detector itself: with the field names it reads
        (``amount`` / ``quantity``), a negative line IS a credit note and the
        effective total keeps its sign."""
        is_credit_note, total = self._detect(
            {"Regels": [{"Omschrijving": "creditatie", "quantity": 1, "amount": -50.00}]}
        )
        self.assertTrue(is_credit_note)
        self.assertEqual(total, -50.00)

    def test_rest_shape_positive_line_is_not_a_credit_note(self):
        is_credit_note, total = self._detect(
            {"Regels": [{"Omschrijving": "verkoop", "quantity": 1, "amount": 50.00}]}
        )
        self.assertFalse(is_credit_note)
        self.assertEqual(total, 50.00)

    def test_mixed_lines_are_not_a_credit_note(self):
        """ERPNext's ``is_return`` requires ALL lines to be credits; a mixed
        mutation must stay a normal invoice or the save is rejected."""
        is_credit_note, _ = self._detect(
            {"Regels": [{"quantity": 1, "amount": 80.00}, {"quantity": 1, "amount": -30.00}]}
        )
        self.assertFalse(is_credit_note)

    @unittest.expectedFailure
    def test_soap_shape_negative_line_is_detected_as_credit_note(self):
        """PRODUCTION DEFECT (transaction_utils.py:253 / :372) -- FIELD MISMATCH.

        ``create_sales_invoice_impl`` / ``create_purchase_invoice_impl`` accept a
        SOAP-shaped payload whose line amount is ``PrijsExclBTW``. The detector
        only reads ``amount`` / ``Prijs``, so it sees 0.00 on every line and
        ``is_credit_note`` is ALWAYS False for these builders -- the credit-note
        quantity branch (line 262 / 381) is dead code.

        Consequence once the arity defect is fixed: a EUR 50 credit note arrives
        as ``PrijsExclBTW: -50``, ``is_return`` stays False, line 269 takes
        ``abs()`` of the rate and line 267 keeps the quantity positive -- so the
        credit note is booked as a POSITIVE EUR 50 sales invoice. The sign of the
        mutation is destroyed and the customer is billed instead of refunded.

        Marked expectedFailure: it will report an UNEXPECTED SUCCESS once the
        detector understands the field names its callers actually send.
        """
        is_credit_note, total = self._detect(
            {
                "Regels": [
                    {"Omschrijving": "creditatie", "Aantal": 1, "PrijsExclBTW": -50.00},
                ]
            }
        )
        self.assertTrue(is_credit_note, "a -50 PrijsExclBTW line is a credit note")
        self.assertEqual(total, -50.00)
