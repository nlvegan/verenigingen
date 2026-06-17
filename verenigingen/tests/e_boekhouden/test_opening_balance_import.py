"""
Integration tests for the OPENING BALANCE cluster of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Covers the parts NOT already exercised by:
  - test_migration_pure_helpers.py        (_calculate_opening_balance_debit_credit)
  - test_rest_migration_helpers.py        (_classify_opening_balance_account,
                                           _add_opening_balance_balancing_entry — unit level)

This file adds REAL integration coverage for:
  - _build_opening_balance_je(...)              (full JE construction)
  - _import_opening_balances_from_data(...)     (dry_run, persist, dedup, empty)
  - _import_opening_balances(...)               (force re-import, already-imported,
                                                 full API-fetch path via a stubbed
                                                 EBoekhoudenAPI boundary only)
  - _get_or_create_temporary_diff_account(...)
  - _get_or_create_stock_temporary_account(...)

Tests assert CONCRETE outcomes: per-account debit/credit by root type,
total_debit == total_credit, balancing entries, party assignment on
receivable/payable lines, dry-run non-persistence, and force re-import.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_opening_balance_import
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _build_opening_balance_je,
    _get_or_create_stock_temporary_account,
    _get_or_create_temporary_diff_account,
    _import_opening_balances,
    _import_opening_balances_from_data,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

COMPANY_NAME = "TEST-EB-Opening-Company"
ABBR = "TEBOC"


class _OpeningBalanceBase(EnhancedTestCase):
    """Shared company / accounts / ledger-mapping fixture for the OB cluster."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._ensure_company()
        cls.cost_center = cls._ensure_leaf_cost_center()
        cls.accounts = cls._ensure_accounts()
        cls._ensure_ledger_mappings()
        cls._ensure_fiscal_year_covers_company()

    # ---- company -----------------------------------------------------------
    @classmethod
    def _ensure_company(cls):
        if frappe.db.exists("Company", COMPANY_NAME):
            return COMPANY_NAME
        doc = frappe.new_doc("Company")
        doc.company_name = COMPANY_NAME
        doc.abbr = ABBR
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return COMPANY_NAME

    @classmethod
    def _ensure_fiscal_year_covers_company(cls):
        # erpnext's get_fiscal_year() raises FiscalYearError when a Fiscal Year
        # covering the posting date has a non-empty `companies` child table that
        # excludes our company. Other test sessions restrict the current-year FYs
        # to their own companies, locking ours out. Clear those restrictions on
        # every FY covering today() so submitted Opening-Entry JEs validate.
        for fy in frappe.db.sql(
            """SELECT name FROM `tabFiscal Year`
               WHERE %s BETWEEN year_start_date AND year_end_date
               AND disabled = 0""",
            (today(),),
            pluck=True,
        ):
            if frappe.db.exists("Fiscal Year Company", {"parent": fy}):
                frappe.db.delete("Fiscal Year Company", {"parent": fy})
        frappe.db.commit()

    @classmethod
    def _ensure_leaf_cost_center(cls):
        cc = frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name")
        return cc

    # ---- accounts ----------------------------------------------------------
    @classmethod
    def _ensure_account(cls, acct_name, account_type, root_type):
        full = f"{acct_name} - {ABBR}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account",
            {"company": cls.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = cls.company
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _ensure_accounts(cls):
        return {
            "asset": cls._ensure_account("EB OB Asset", "", "Asset"),
            "bank": cls._ensure_account("EB OB Bank", "Bank", "Asset"),
            "receivable": cls._ensure_account("EB OB Receivable", "Receivable", "Asset"),
            "liability": cls._ensure_account("EB OB Liability", "", "Liability"),
            "payable": cls._ensure_account("EB OB Payable", "Payable", "Liability"),
            "equity": cls._ensure_account("EB OB Equity", "", "Equity"),
            "income": cls._ensure_account("EB OB Income", "", "Income"),
            "expense": cls._ensure_account("EB OB Expense", "", "Expense"),
            "stock": cls._ensure_account("EB OB Stock", "Stock", "Asset"),
        }

    # ---- ledger mappings (ledger_id == ledger_code) ------------------------
    # Map a stable ledger id per account kind so the builder resolves to our
    # ERPNext accounts without ever touching the eBoekhouden API.
    LEDGERS = {
        "asset": 9001,
        "bank": 9002,
        "receivable": 9003,
        "liability": 9004,
        "payable": 9005,
        "equity": 9006,
        "income": 9007,
        "expense": 9008,
        "stock": 9009,
    }

    @classmethod
    def _ensure_ledger_mappings(cls):
        for kind, ledger_id in cls.LEDGERS.items():
            if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}):
                continue
            doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
            doc.ledger_id = ledger_id
            doc.ledger_code = str(ledger_id)
            doc.ledger_name = f"OB Ledger {kind}"
            doc.erpnext_account = cls.accounts[kind]
            doc.insert(ignore_permissions=True)

    # ---- helpers -----------------------------------------------------------
    def _mut(self, kind, amount, amount_field="amount", mid=None, date=None):
        """Build one opening-balance mutation dict for the given account kind."""
        m = {
            "id": mid if mid is not None else self.LEDGERS[kind],
            "ledgerId": self.LEDGERS[kind],
            amount_field: amount,
            "description": f"OB {kind}",
        }
        if date:
            m["date"] = date
        return m

    def _delete_existing_ob(self):
        """Remove any prior OPENING_BALANCE JE so dedup branches are clean.

        ``eboekhouden_mutation_nr`` carries a GLOBAL unique index, so a single
        "OPENING_BALANCE" JE for ANY company blocks creating one for ours
        (IntegrityError 1062). A per-company filter therefore leaves siblings'
        committed OB JEs in place and makes the suite fail on re-run. Purge by the
        marker alone so every persist path starts from a genuinely clean slate.
        """
        existing = frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": "OPENING_BALANCE"},
            pluck="name",
        )
        for name in existing:
            # Cancelling a submitted OB JE can trip an on_cancel hook in the test
            # env; force-delete works regardless of docstatus, so swallow a failed
            # cancel and delete anyway (test-only cleanup, not a business op). If
            # the cancel raises mid-transaction we must roll back before deleting,
            # else the delete runs inside a poisoned transaction.
            try:
                je = frappe.get_doc("Journal Entry", name)
                if je.docstatus == 1:
                    je.cancel()
            except Exception:
                frappe.db.rollback()
            frappe.delete_doc("Journal Entry", name, force=True, ignore_permissions=True)
        frappe.db.commit()


# ===========================================================================
# _build_opening_balance_je
# ===========================================================================
class TestBuildOpeningBalanceJE(_OpeningBalanceBase):
    def _line_for(self, je, account):
        for row in je.accounts:
            if row.account == account:
                return row
        return None

    def test_asset_positive_goes_to_debit(self):
        muts = [self._mut("asset", 1000.0, date=today())]
        result = _build_opening_balance_je(muts, self.company, self.cost_center, [])
        je = result["je"]
        line = self._line_for(je, self.accounts["asset"])
        self.assertIsNotNone(line)
        self.assertEqual(line.debit_in_account_currency, 1000.0)
        self.assertEqual(line.credit_in_account_currency, 0)

    def test_liability_positive_goes_to_credit(self):
        muts = [self._mut("liability", 2000.0, date=today())]
        result = _build_opening_balance_je(muts, self.company, self.cost_center, [])
        je = result["je"]
        line = self._line_for(je, self.accounts["liability"])
        self.assertEqual(line.credit_in_account_currency, 2000.0)
        self.assertEqual(line.debit_in_account_currency, 0)

    def test_equity_positive_goes_to_credit(self):
        muts = [self._mut("equity", 500.0, date=today())]
        result = _build_opening_balance_je(muts, self.company, self.cost_center, [])
        line = self._line_for(result["je"], self.accounts["equity"])
        self.assertEqual(line.credit_in_account_currency, 500.0)
        self.assertEqual(line.debit_in_account_currency, 0)

    def test_negative_asset_goes_to_credit(self):
        # Asset with negative raw amount -> credit side (contra-asset)
        muts = [self._mut("asset", -300.0, date=today())]
        line = self._line_for(
            _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"],
            self.accounts["asset"],
        )
        self.assertEqual(line.credit_in_account_currency, 300.0)
        self.assertEqual(line.debit_in_account_currency, 0)

    def test_negative_liability_goes_to_debit(self):
        muts = [self._mut("liability", -250.0, date=today())]
        line = self._line_for(
            _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"],
            self.accounts["liability"],
        )
        self.assertEqual(line.debit_in_account_currency, 250.0)
        self.assertEqual(line.credit_in_account_currency, 0)

    def test_receivable_line_carries_customer_party(self):
        muts = [self._mut("receivable", 800.0, date=today())]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"]
        line = self._line_for(je, self.accounts["receivable"])
        self.assertEqual(line.party_type, "Customer")
        self.assertTrue(line.party)
        # Receivable is an Asset root -> debit side
        self.assertEqual(line.debit_in_account_currency, 800.0)

    def test_payable_line_carries_supplier_party(self):
        muts = [self._mut("payable", 600.0, date=today())]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"]
        line = self._line_for(je, self.accounts["payable"])
        self.assertEqual(line.party_type, "Supplier")
        self.assertTrue(line.party)
        # Payable is a Liability root -> credit side
        self.assertEqual(line.credit_in_account_currency, 600.0)

    def test_pnl_and_stock_accounts_skipped(self):
        muts = [
            self._mut("income", 100.0, date=today()),
            self._mut("expense", 100.0, date=today()),
            self._mut("stock", 100.0, date=today()),
            self._mut("asset", 100.0, date=today()),
        ]
        result = _build_opening_balance_je(muts, self.company, self.cost_center, [], track_skip_reasons=True)
        je = result["je"]
        present = {row.account for row in je.accounts}
        self.assertIn(self.accounts["asset"], present)
        self.assertNotIn(self.accounts["income"], present)
        self.assertNotIn(self.accounts["expense"], present)
        self.assertNotIn(self.accounts["stock"], present)
        # skip reasons tracked
        self.assertEqual(len(result["skipped_accounts"]["pnl"]), 2)
        self.assertEqual(len(result["skipped_accounts"]["stock"]), 1)

    def test_zero_amount_line_skipped(self):
        muts = [self._mut("asset", 0.0, date=today())]
        result = _build_opening_balance_je(muts, self.company, self.cost_center, [])
        # No real lines -> early-return shape with success/message
        self.assertIn("success", result)
        self.assertIsNone(result["journal_entry"])

    def test_duplicate_account_only_processed_once(self):
        muts = [
            self._mut("asset", 1000.0, mid=1, date=today()),
            self._mut("asset", 5000.0, mid=2, date=today()),  # same ledger -> same account
        ]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"]
        asset_lines = [r for r in je.accounts if r.account == self.accounts["asset"]]
        self.assertEqual(len(asset_lines), 1)
        # First-seen amount wins (1000), not 5000
        self.assertEqual(asset_lines[0].debit_in_account_currency, 1000.0)

    def test_unbalanced_set_gets_balancing_entry_and_totals_match(self):
        # Asset 1000 debit, Liability 200 credit -> imbalance 800 -> balancing credit
        muts = [
            self._mut("asset", 1000.0, mid=1, date=today()),
            self._mut("liability", 200.0, mid=2, date=today()),
        ]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"]
        temp = _get_or_create_temporary_diff_account(self.company, [])
        bal_line = next((r for r in je.accounts if r.account == temp), None)
        self.assertIsNotNone(bal_line, "expected a balancing entry on the temp-diff account")
        # debit_excess (1000 - 200 = 800) -> balancing entry is a credit
        self.assertEqual(bal_line.credit_in_account_currency, 800.0)
        total_debit = sum(r.debit_in_account_currency for r in je.accounts)
        total_credit = sum(r.credit_in_account_currency for r in je.accounts)
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    def test_already_balanced_set_gets_no_balancing_entry(self):
        # Asset 1000 debit, Liability 1000 credit -> balanced, no temp-diff line
        muts = [
            self._mut("asset", 1000.0, mid=1, date=today()),
            self._mut("liability", 1000.0, mid=2, date=today()),
        ]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [])["je"]
        temp = _get_or_create_temporary_diff_account(self.company, [])
        self.assertIsNone(next((r for r in je.accounts if r.account == temp), None))
        self.assertEqual(len(je.accounts), 2)

    def test_no_date_uses_fallback(self):
        debug = []
        muts = [self._mut("asset", 1000.0)]  # no date key
        je = _build_opening_balance_je(muts, self.company, self.cost_center, debug)["je"]
        self.assertEqual(str(je.posting_date), "2018-01-01")
        self.assertTrue(any("fallback date" in d for d in debug))

    def test_je_metadata_set(self):
        je = _build_opening_balance_je(
            [self._mut("asset", 1000.0, date=today())], self.company, self.cost_center, []
        )["je"]
        self.assertEqual(je.voucher_type, "Opening Entry")
        self.assertEqual(je.company, self.company)
        self.assertEqual(je.eboekhouden_mutation_nr, "OPENING_BALANCE")

    def test_amount_field_override_uses_balance_key(self):
        # _import_opening_balances_from_data path uses amount_field="balance"
        muts = [self._mut("asset", 1234.0, amount_field="balance", date=today())]
        je = _build_opening_balance_je(muts, self.company, self.cost_center, [], amount_field="balance")["je"]
        line = next(r for r in je.accounts if r.account == self.accounts["asset"])
        self.assertEqual(line.debit_in_account_currency, 1234.0)


# ===========================================================================
# _import_opening_balances_from_data  (persist / dry_run / dedup / empty)
# ===========================================================================
class TestImportOpeningBalancesFromData(_OpeningBalanceBase):
    def setUp(self):
        super().setUp()
        self._delete_existing_ob()

    def test_dry_run_does_not_persist(self):
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        result = _import_opening_balances_from_data(muts, self.company, self.cost_center, [], dry_run=True)
        self.assertTrue(result["success"])
        self.assertIsNone(result["journal_entry"])
        # Nothing persisted
        self.assertFalse(
            frappe.db.exists(
                "Journal Entry",
                {"company": self.company, "eboekhouden_mutation_nr": "OPENING_BALANCE"},
            )
        )

    def test_persist_creates_submitted_balanced_je(self):
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        result = _import_opening_balances_from_data(muts, self.company, self.cost_center, [], dry_run=False)
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["journal_entry"])
        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        self.assertEqual(je.docstatus, 1)  # submitted
        self.assertAlmostEqual(je.total_debit, je.total_credit, places=2)
        self.assertEqual(je.voucher_type, "Opening Entry")

    def test_second_import_is_deduped(self):
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        first = _import_opening_balances_from_data(muts, self.company, self.cost_center, [], dry_run=False)
        second = _import_opening_balances_from_data(muts, self.company, self.cost_center, [], dry_run=False)
        self.assertTrue(second["success"])
        self.assertIn("already imported", second["message"])
        self.assertEqual(second["journal_entry"], first["journal_entry"])

    def test_empty_data_returns_no_balances(self):
        result = _import_opening_balances_from_data([], self.company, self.cost_center, [], dry_run=False)
        self.assertTrue(result["success"])
        self.assertIsNone(result["journal_entry"])
        self.assertIn("No opening balances", result["message"])

    def test_unbalanced_data_persists_balanced_via_temp_account(self):
        # Only a single asset line -> must be balanced by temp-diff account to submit
        muts = [self._mut("asset", 750.0, amount_field="balance", mid=1, date=today())]
        result = _import_opening_balances_from_data(muts, self.company, self.cost_center, [], dry_run=False)
        self.assertTrue(result["success"], msg=result)
        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        self.assertAlmostEqual(je.total_debit, je.total_credit, places=2)
        temp = _get_or_create_temporary_diff_account(self.company, [])
        self.assertTrue(any(r.account == temp for r in je.accounts))


# ===========================================================================
# _import_opening_balances  (force / already-imported / API-fetch boundary)
# ===========================================================================
class TestImportOpeningBalances(_OpeningBalanceBase):
    def setUp(self):
        super().setUp()
        self._delete_existing_ob()

    def _seed_existing_ob_je(self):
        """Create a real submitted OPENING_BALANCE JE to test dedup/force."""
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = today()
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.append(
            "accounts",
            {
                "account": self.accounts["asset"],
                "debit_in_account_currency": 100.0,
                "credit_in_account_currency": 0,
                "cost_center": self.cost_center,
            },
        )
        je.append(
            "accounts",
            {
                "account": self.accounts["liability"],
                "debit_in_account_currency": 0,
                "credit_in_account_currency": 100.0,
                "cost_center": self.cost_center,
            },
        )
        je.save()
        je.submit()
        frappe.db.commit()
        return je.name

    def test_already_imported_returns_existing_without_api(self):
        existing = self._seed_existing_ob_je()
        # No API patch: if it tried to fetch, EBoekhoudenAPI() would fail in tests.
        result = _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)
        self.assertTrue(result["success"])
        self.assertIn("already imported", result["message"])
        self.assertEqual(result["journal_entry"], existing)

    def test_api_fetch_path_dry_run_does_not_persist(self):
        api_payload = [
            {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
            {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
        ]
        fake_api = MagicMock()
        fake_api.make_request.return_value = {
            "success": True,
            "status_code": 200,
            "data": frappe.as_json(api_payload),
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=fake_api,
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=True, force=False)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["journal_entry"], "DRY-RUN-PREVIEW")
        self.assertFalse(
            frappe.db.exists(
                "Journal Entry",
                {"company": self.company, "eboekhouden_mutation_nr": "OPENING_BALANCE"},
            )
        )

    def test_api_failure_returns_error(self):
        fake_api = MagicMock()
        fake_api.make_request.return_value = {
            "success": False,
            "status_code": 500,
            "error": "boom",
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=fake_api,
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)
        self.assertFalse(result["success"])
        self.assertIn("Failed to fetch opening balances", result["error"])

    def _fetch_api(self, payload):
        """A stubbed EBoekhoudenAPI whose make_request returns ``payload`` as the
        type-0 mutation list (JSON-encoded, the real API's wire shape)."""
        fake = MagicMock()
        fake.make_request.return_value = {
            "success": True,
            "status_code": 200,
            "data": frappe.as_json(payload),
        }
        return fake

    def test_api_fetch_path_persists_submitted_balanced_je(self):
        """The DEEP path: a real (non-dry-run, no pre-existing OB) API fetch builds,
        SAVES and SUBMITS a balanced OPENING_BALANCE JE. This is the save+submit
        success branch of _import_opening_balances that the dry-run / already-imported
        / failure tests never reach."""
        payload = [
            {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
            {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
        ]
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=self._fetch_api(payload),
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)
        self.assertTrue(result["success"], msg=result)
        self.assertNotIn(result["journal_entry"], (None, "DRY-RUN-PREVIEW"))
        self.assertEqual(result["accounts_processed"], 2)
        # No stock lines -> no Stock Reconciliations attempted.
        self.assertEqual(result["stock_reconciliations"], [])
        self.assertIn("imported successfully", result["message"])

        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        self.assertEqual(je.docstatus, 1)  # submitted, not just saved
        self.assertEqual(je.voucher_type, "Opening Entry")
        self.assertAlmostEqual(je.total_debit, je.total_credit, places=2)
        # Right sides: asset 1000 -> debit, liability 1000 -> credit (balanced, no
        # temp-diff line needed).
        asset_line = next(r for r in je.accounts if r.account == self.accounts["asset"])
        liab_line = next(r for r in je.accounts if r.account == self.accounts["liability"])
        self.assertEqual(asset_line.debit_in_account_currency, 1000.0)
        self.assertEqual(liab_line.credit_in_account_currency, 1000.0)

    def test_api_fetch_path_stock_line_runs_reconciliation_branch(self):
        """A stock account in the OB data is EXCLUDED from the JE and routed through
        the Stock Reconciliation branch (skipped_accounts['stock'] -> the stock
        handler). The OB JE is still saved+submitted from the non-stock lines; the
        reconciliation is best-effort so the run succeeds regardless of its result."""
        payload = [
            {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
            {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
            {"id": 3, "ledgerId": self.LEDGERS["stock"], "amount": 500.0, "date": today()},
            # A P&L line too -> skipped as pnl, exercising the post-save summary.
            {"id": 4, "ledgerId": self.LEDGERS["income"], "amount": 700.0, "date": today()},
        ]
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=self._fetch_api(payload),
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)
        self.assertTrue(result["success"], msg=result)
        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        self.assertEqual(je.docstatus, 1)
        # Neither the stock nor the P&L account is posted to the OB JE.
        je_accounts = {r.account for r in je.accounts}
        self.assertNotIn(self.accounts["stock"], je_accounts)
        self.assertNotIn(self.accounts["income"], je_accounts)
        # The reconciliation branch was entered: the stock account was tracked and
        # the result carries the reconciliation key.
        self.assertIn("stock_reconciliations", result)
        stock_skipped = {s["account"] for s in result["skipped_accounts"]["stock"]}
        self.assertIn(self.accounts["stock"], stock_skipped)
        pnl_skipped = {s["account"] for s in result["skipped_accounts"]["pnl"]}
        self.assertIn(self.accounts["income"], pnl_skipped)

    def test_api_dict_payload_with_items_key_is_normalized(self):
        """The API may return a dict ``{"items": [...]}`` rather than a bare list;
        the import unwraps the ``items`` key before processing (dry-run keeps it
        light — normalization runs before the dry-run check)."""
        payload = {
            "items": [
                {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
                {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
            ]
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=self._fetch_api(payload),
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=True, force=False)
        # Normalized to 2 mutations -> a non-empty preview (not the "No opening
        # balances found" empty-list shape).
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["journal_entry"], "DRY-RUN-PREVIEW")

    def test_api_dict_payload_without_items_uses_values(self):
        """A dict WITHOUT an ``items`` key falls back to its ``.values()`` as the
        mutation list."""
        payload = {
            "a": {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
            "b": {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=self._fetch_api(payload),
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=True, force=False)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["journal_entry"], "DRY-RUN-PREVIEW")

    def test_api_only_pnl_lines_yields_no_valid_entries(self):
        """When every fetched line is a P&L account (all skipped), the builder
        returns the no-valid-entries early shape and _import_opening_balances
        propagates it: success, journal_entry None, nothing persisted."""
        payload = [
            {"id": 1, "ledgerId": self.LEDGERS["income"], "amount": 1000.0, "date": today()},
            {"id": 2, "ledgerId": self.LEDGERS["expense"], "amount": 1000.0, "date": today()},
        ]
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=self._fetch_api(payload),
        ):
            result = _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)
        self.assertTrue(result["success"], msg=result)
        self.assertIsNone(result["journal_entry"])
        self.assertIn("No valid opening balance entries", result["message"])
        self.assertFalse(
            frappe.db.exists(
                "Journal Entry",
                {"company": self.company, "eboekhouden_mutation_nr": "OPENING_BALANCE"},
            )
        )


# ===========================================================================
# _get_or_create_temporary_diff_account / _get_or_create_stock_temporary_account
# ===========================================================================
class TestTemporaryAccounts(_OpeningBalanceBase):
    def test_temp_diff_account_returns_temporary_typed_account(self):
        # Contract: returns a usable "Temporary" account for the company. The
        # company auto-ships a "Temporary Opening" (Temporary) account, which the
        # function reuses (PRIORITY 1-3) rather than creating a new one.
        name = _get_or_create_temporary_diff_account(self.company, [])
        self.assertTrue(name)
        doc = frappe.get_doc("Account", name)
        self.assertEqual(doc.account_type, "Temporary")
        self.assertEqual(doc.company, self.company)

    def test_temp_diff_account_is_idempotent(self):
        first = _get_or_create_temporary_diff_account(self.company, [])
        second = _get_or_create_temporary_diff_account(self.company, [])
        self.assertEqual(first, second)

    def test_temp_diff_account_created_as_equity_when_none_exist(self):
        # On a company with NO pre-existing Temporary account, the create branch
        # must produce an Equity-rooted Temporary "Temporary Differences" account.
        company = self._ensure_clean_temp_company()
        name = _get_or_create_temporary_diff_account(company, [])
        doc = frappe.get_doc("Account", name)
        self.assertEqual(doc.account_type, "Temporary")
        self.assertEqual(doc.root_type, "Equity")
        self.assertEqual(doc.account_name, "Temporary Differences")

    @classmethod
    def _ensure_clean_temp_company(cls):
        name = "TEST-EB-OB-CleanTemp"
        if frappe.db.exists("Company", name):
            # Remove any Temporary accounts so the create branch is exercised.
            for acc in frappe.get_all(
                "Account",
                filters={"company": name, "account_type": "Temporary", "is_group": 0},
                pluck="name",
            ):
                frappe.db.set_value("Account", acc, "account_type", "")
            frappe.db.commit()
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEOBCT"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        for acc in frappe.get_all(
            "Account",
            filters={"company": name, "account_type": "Temporary", "is_group": 0},
            pluck="name",
        ):
            frappe.db.set_value("Account", acc, "account_type", "")
        frappe.db.commit()
        return name

    def test_stock_temp_account_created_as_asset_temporary(self):
        # Regression guard: this previously crashed with
        # "not enough arguments for format string" (single-% in a LIKE inside a
        # parameterized frappe.db.sql) and silently fell back to the temp-diff
        # account, so the dedicated stock temporary account was NEVER created.
        name = _get_or_create_stock_temporary_account(self.company, [])
        doc = frappe.get_doc("Account", name)
        # ERPNext autonames the account "<account_name> - <abbr>"; assert on the
        # stable account_name field + type/root rather than the abbr-suffixed name.
        self.assertEqual(doc.account_name, "Stock Opening Balance (Temporary)")
        self.assertEqual(doc.account_type, "Temporary")
        self.assertEqual(doc.root_type, "Asset")
        self.assertEqual(doc.company, self.company)

    def test_stock_temp_account_is_idempotent(self):
        # Regression guard for a real bug: the lookup used to construct
        # f"... - {company}" (full name) while ERPNext stores "... - {abbr}", so the
        # existence check never matched and a second call re-created/fell back to a
        # different account. After the fix, both calls return the same real account.
        first = _get_or_create_stock_temporary_account(self.company, [])
        second = _get_or_create_stock_temporary_account(self.company, [])
        self.assertEqual(first, second)
        self.assertEqual(
            frappe.db.get_value("Account", first, "account_name"), "Stock Opening Balance (Temporary)"
        )


FORCE_COMPANY = "TEST-EB-OB-Force-Company"
FORCE_ABBR = "TEBOF"


class TestOpeningBalanceForceReimport(EnhancedTestCase):
    """force=True opening-balance re-import, on a DEDICATED single-use company.

    The shared TEST-EB-Opening-Company accumulates committed OPENING_BALANCE JEs
    across sibling tests, so the force path's existence check would find an
    arbitrary one (not the one we seed) -- which made the earlier shared-company
    version flaky and forced a skip. A dedicated company makes the existence check
    deterministic; a standalone repro confirmed the force-delete works here.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls.asset = cls._ensure_account("FC Asset", "Asset")
        cls.liability = cls._ensure_account("FC Liability", "Liability")
        cls.cost_center = cls._ensure_cost_center()
        cls._ensure_fiscal_year()
        frappe.db.commit()

    @classmethod
    def _ensure_company(cls):
        if frappe.db.exists("Company", FORCE_COMPANY):
            return
        c = frappe.new_doc("Company")
        c.company_name = FORCE_COMPANY
        c.abbr = FORCE_ABBR
        c.default_currency = "EUR"
        c.country = "Netherlands"
        c.insert(ignore_permissions=True)

    @classmethod
    def _ensure_root(cls, root_type):
        existing = frappe.db.get_value(
            "Account", {"company": FORCE_COMPANY, "root_type": root_type, "is_group": 1}, "name"
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"FC {root_type} Root"
        r.company = FORCE_COMPANY
        r.root_type = root_type
        r.report_type = "Balance Sheet"
        r.is_group = 1
        r.insert(ignore_permissions=True)
        return r.name

    @classmethod
    def _ensure_account(cls, account_name, root_type):
        expected = f"{account_name} - {FORCE_ABBR}"
        if frappe.db.exists("Account", expected):
            return expected
        a = frappe.new_doc("Account")
        a.account_name = account_name
        a.company = FORCE_COMPANY
        a.root_type = root_type
        a.report_type = "Balance Sheet"
        a.is_group = 0
        a.parent_account = cls._ensure_root(root_type)
        a.insert(ignore_permissions=True)
        return a.name

    @classmethod
    def _ensure_cost_center(cls):
        cc = frappe.db.get_value("Cost Center", {"company": FORCE_COMPANY, "is_group": 0}, "name")
        if cc:
            return cc
        root = frappe.db.get_value("Cost Center", {"company": FORCE_COMPANY, "is_group": 1}, "name")
        if not root:
            rc = frappe.new_doc("Cost Center")
            rc.cost_center_name = FORCE_COMPANY
            rc.company = FORCE_COMPANY
            rc.is_group = 1
            rc.insert(ignore_permissions=True)
            root = rc.name
        leaf = frappe.new_doc("Cost Center")
        leaf.cost_center_name = "FC Main"
        leaf.company = FORCE_COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root
        leaf.insert(ignore_permissions=True)
        return leaf.name

    @classmethod
    def _ensure_fiscal_year(cls):
        fy = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", today()], "year_end_date": [">=", today()]},
            "name",
            order_by="creation desc",
        )
        if not fy:
            # Fresh site with no current-year Fiscal Year: create one so the seeded
            # Opening-Entry JE (posting_date today()) can validate/submit.
            from frappe.utils import getdate

            year = getdate(today()).year
            fy = f"TEBOF-FY-{year}"
            if not frappe.db.exists("Fiscal Year", fy):
                fyd = frappe.new_doc("Fiscal Year")
                fyd.year = fy
                fyd.year_start_date = f"{year}-01-01"
                fyd.year_end_date = f"{year}-12-31"
                fyd.insert(ignore_permissions=True)
        fyd = frappe.get_doc("Fiscal Year", fy)
        if not any(c.company == FORCE_COMPANY for c in fyd.companies):
            fyd.append("companies", {"company": FORCE_COMPANY})
            fyd.save(ignore_permissions=True)

    def _seed_ob_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = FORCE_COMPANY
        je.posting_date = today()
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.append(
            "accounts",
            {
                "account": self.asset,
                "debit_in_account_currency": 100,
                "credit_in_account_currency": 0,
                "cost_center": self.cost_center,
            },
        )
        je.append(
            "accounts",
            {
                "account": self.liability,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": 100,
                "cost_center": self.cost_center,
            },
        )
        je.save()
        je.submit()
        frappe.db.commit()
        return je.name

    def tearDown(self):
        # test_without_force intentionally KEEPS its seeded OB JE; left committed it
        # would block the next run via the GLOBAL unique index on
        # eboekhouden_mutation_nr. Purge here so the module is repeatable.
        self._purge_ob_jes()
        super().tearDown()

    def _purge_ob_jes(self):
        # Defensive against leftover committed state from a prior run on this site.
        # eboekhouden_mutation_nr is GLOBALLY unique, so purge the marker across ALL
        # companies, not just FORCE_COMPANY (a sibling's leftover blocks us too).
        for name in frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": "OPENING_BALANCE"},
            pluck="name",
        ):
            # Cancelling a sibling's submitted OB JE can trip an on_cancel hook in
            # the test env; swallow a failed cancel (rolling back the poisoned
            # transaction) and force-delete regardless of docstatus.
            try:
                d = frappe.get_doc("Journal Entry", name)
                if d.docstatus == 1:
                    d.cancel()
            except Exception:
                frappe.db.rollback()
            frappe.delete_doc("Journal Entry", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_force_deletes_existing_opening_balance_je(self):
        self._purge_ob_jes()
        seeded = self._seed_ob_je()
        # Sanity: the seeded JE is exactly what the existence check will find.
        self.assertEqual(
            frappe.db.exists(
                "Journal Entry",
                {
                    "company": FORCE_COMPANY,
                    "eboekhouden_mutation_nr": "OPENING_BALANCE",
                    "voucher_type": "Opening Entry",
                },
            ),
            seeded,
        )

        # Empty API payload: we are asserting the force-DELETE of the existing OB
        # JE (the previously-untested branch); the build-new-JE path is covered by
        # the API-fetch tests in the shared-company class above.
        fake_api = MagicMock()
        fake_api.make_request.return_value = {"success": True, "status_code": 200, "data": "[]"}
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            return_value=fake_api,
        ):
            result = _import_opening_balances(FORCE_COMPANY, self.cost_center, [], dry_run=False, force=True)

        self.assertTrue(result["success"], msg=result)
        self.assertFalse(
            frappe.db.exists("Journal Entry", seeded),
            "force=True must cancel + delete the pre-existing OPENING_BALANCE JE",
        )

    def test_without_force_keeps_existing_and_reports_already_imported(self):
        self._purge_ob_jes()
        seeded = self._seed_ob_je()
        result = _import_opening_balances(FORCE_COMPANY, self.cost_center, [], dry_run=False, force=False)
        # Non-force: the existing OB JE is left intact and reported back.
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result.get("journal_entry"), seeded)
        self.assertTrue(frappe.db.exists("Journal Entry", seeded))
