"""
Gap-fill coverage for two LIVE payments utils modules:
    - verenigingen_payments/utils/mt940_import.py
    - verenigingen_payments/utils/bank_transaction_reconciliation.py

Targets helpers/branches NOT already covered by:
    - test_mt940_import_coverage.py / test_mt940_parsing.py /
      test_mt940_import_integration.py
    - test_bank_transaction_reconciliation.py /
      test_bank_reconciliation_matching.py /
      test_sepa_bank_reconciliation_coverage.py

All real-DB, no business-logic mocks. Real Bank Account / Customer documents and
the real WoLpH/mt940 library (small fixture statements) drive every path.

Covered here:
  mt940_import:
    - _ensure_bank_account_link: creates a Bank Account link, and is idempotent
      when one already exists (both the iban and bank_account_no skip branches)
    - get_mt940_import_status: returns the recent-transactions report structure
    - convert_mt940_to_csv: real statement -> decodable base64 CSV with a data row
  bank_transaction_reconciliation:
    - PaymentReconciliationManager() constructs (runs _validate_bank_transaction_fields
      against the real Bank Transaction meta without throwing)
    - get_reconciliation_summary: empty-window zero-division-safe rate branch
"""

import base64
import csv
import io

import frappe

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import mt940_import as M

# A syntactically valid IBAN not belonging to any seeded party.
_LINK_IBAN = "NL02ABNA0123456789"


class TestEnsureBankAccountLink(EnhancedTestCase):
    """_ensure_bank_account_link creates/idempotently-skips a Bank Account."""

    def _make_customer(self, name_hint):
        cust = frappe.new_doc("Customer")
        cust.customer_name = f"{name_hint}-{frappe.generate_hash()[:6]}"
        cust.customer_type = "Individual"
        cust.insert(ignore_permissions=True)
        self.track_doc("Customer", cust.name)
        return cust.name

    def track_doc(self, doctype, name):
        # EnhancedTestCase rolls back, but Bank Account creation in the helper
        # uses migration_context which may commit; track for explicit cleanup.
        if not hasattr(self, "_extra_docs"):
            self._extra_docs = []
        self._extra_docs.append((doctype, name))

    def tearDown(self):
        for doctype, name in reversed(getattr(self, "_extra_docs", [])):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        super().tearDown()

    def test_creates_link_when_absent(self):
        customer = self._make_customer("LinkCust")
        iban = _LINK_IBAN
        # Pre-clean any stray Bank Account on this IBAN from a prior aborted run.
        for ba in frappe.get_all("Bank Account", filters={"iban": iban}, pluck="name"):
            frappe.delete_doc("Bank Account", ba, force=True, ignore_permissions=True)

        with self.assertNoErrorLog():
            M._ensure_bank_account_link(iban, customer, "Customer")

        created = frappe.db.get_value(
            "Bank Account", {"iban": iban}, ["name", "party", "party_type"], as_dict=True
        )
        self.assertIsNotNone(created)
        self.assertEqual(created.party, customer)
        self.assertEqual(created.party_type, "Customer")
        self.track_doc("Bank Account", created.name)

    def test_idempotent_when_link_exists(self):
        customer = self._make_customer("IdemCust")
        iban = "NL44RABO0123456789"
        for ba in frappe.get_all("Bank Account", filters={"iban": iban}, pluck="name"):
            frappe.delete_doc("Bank Account", ba, force=True, ignore_permissions=True)

        M._ensure_bank_account_link(iban, customer, "Customer")
        first = frappe.db.get_value("Bank Account", {"iban": iban}, "name")
        self.assertIsNotNone(first)
        self.track_doc("Bank Account", first)

        # Second call must hit the existing-link skip branch (no second account).
        with self.assertNoErrorLog():
            M._ensure_bank_account_link(iban, customer, "Customer")
        all_for_iban = frappe.get_all("Bank Account", filters={"iban": iban}, pluck="name")
        self.assertEqual(len(all_for_iban), 1)

    def test_noop_on_empty_inputs(self):
        # Early return: empty iban or party does nothing and never raises.
        with self.assertNoErrorLog():
            M._ensure_bank_account_link("", "whatever", "Customer")
            M._ensure_bank_account_link(_LINK_IBAN, "", "Customer")


class TestMt940ImportStatus(EnhancedTestCase):
    """get_mt940_import_status returns a structured recent-imports report."""

    def test_status_report_shape(self):
        with self.assertNoErrorLog():
            result = M.get_mt940_import_status()
        self.assertTrue(result["success"])
        self.assertIn("recent_transactions", result)
        self.assertIn("total_recent", result)
        self.assertIsInstance(result["recent_transactions"], list)
        self.assertEqual(result["total_recent"], len(result["recent_transactions"]))


class TestConvertMt940ToCsv(EnhancedTestCase):
    """convert_mt940_to_csv produces decodable base64 CSV with data rows."""

    def test_real_statement_converts_to_csv_with_rows(self):
        b64 = base64.b64encode(S.SEPA_INCOMING_CREDIT.encode("utf-8")).decode("ascii")
        with self.assertNoErrorLog():
            result = M.convert_mt940_to_csv(b64, bank_account="Whatever Bank Account")
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertTrue(result["filename"].endswith(".csv"))

        decoded = base64.b64decode(result["csv_content"]).decode("utf-8")
        rows = list(csv.reader(io.StringIO(decoded)))
        # Header + at least one transaction row.
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "Date")
        # The bank_account argument is written into each row's Bank Account column.
        self.assertEqual(rows[1][5], "Whatever Bank Account")

    def test_invalid_base64_returns_failure(self):
        with self.assertNoErrorLog():
            result = M.convert_mt940_to_csv("!!!not-base64!!!", bank_account="X")
        self.assertFalse(result["success"])


class TestReconciliationManagerConstructionAndSummary(EnhancedTestCase):
    """
    Constructing PaymentReconciliationManager runs _validate_bank_transaction_fields
    and _validate_mollie_accounts against the real schema; get_reconciliation_summary
    exercises the zero-division-safe rate computation.
    """

    def _manager(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            PaymentReconciliationManager,
        )

        # Mollie-account validation logs (does not throw) when unconfigured; that
        # logging is expected here, not a test failure.
        self.expectErrorLog("Mollie Account Configuration", "Mollie")
        return PaymentReconciliationManager()

    def test_manager_constructs_against_real_schema(self):
        mgr = self._manager()
        # Required Bank Transaction fields validated successfully -> threshold set.
        self.assertEqual(mgr.match_threshold, 0.85)

    def test_summary_empty_window_rate_is_zero(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            get_reconciliation_summary,
        )

        # Far-past window with no transactions -> exercises the zero-division-safe
        # rate branch (rate == 0, not a crash).
        result = get_reconciliation_summary(from_date="1900-01-01", to_date="1900-12-31")
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["reconciliation_rate"], 0)
        for key in ("reconciled", "pending", "unmatched"):
            self.assertIn(key, result)

    def _make_bank_txn(self, date):
        # Bank Transaction requires only naming_series; date drives the filter.
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date
        bt.deposit = 10
        bt.insert(ignore_permissions=True)
        self.addCleanup(lambda n=bt.name: frappe.delete_doc("Bank Transaction", n, force=True))
        return bt.name

    def test_summary_from_date_lower_bound_is_applied(self):
        # Regression guard: both date bounds must be honoured. Previously both went
        # under the same "date" filter key, so from_date was silently dropped and
        # the older transaction leaked into the window. Use an isolated 1990 window
        # (no real data) and assert from_date excludes the earlier transaction.
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            get_reconciliation_summary,
        )

        self._make_bank_txn("1990-01-01")  # before window -> must be excluded
        self._make_bank_txn("1990-12-31")  # inside window -> must be counted
        result = get_reconciliation_summary(from_date="1990-06-01", to_date="1991-01-01")
        # Only the in-window transaction; the from_date bound drops the Jan one.
        self.assertEqual(result["total_transactions"], 1)
