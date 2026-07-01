"""
Branch / error-path coverage for the Mollie bulk transaction importer.

Complements ``test_bulk_transaction_importer.py`` (pure helpers) and
``test_bulk_transaction_importer_sweep.py`` (happy-path creation/orchestration)
by exercising the previously-uncovered defensive and error branches:

    - import_transactions: completed_with_errors status when a strategy method
      surfaces errors.
    - _import_payment_data: naive-datetime -> UTC conversion, per-payment
      ValueError handling, and outer network / validation / generic handlers.
    - _import_settlement_data: outer API-failure handler.
    - _create_bank_transaction_from_settlement / _from_payment: default
      company+bank-account resolution, "no bank account -> None", and the
      bad-amount exception path.
    - _process_settlement_for_import / _process_payment_for_import: create-returns
      -None (skipped) and malformed-date exception branches.
    - _validate_duplicate_transaction: settlement-id and amount/date/reference
      duplicate criteria against real Bank Transactions.
    - _find_member_by_payment_details: multiple fuzzy name matches (no auto-assign).
    - _save_import_record: fallback bank account, non-existent bank account,
      and malformed-results exception handler.
    - estimate_import_size: API-failure handler.
    - run_bulk_import whitelisted endpoint: full success path (stubbed Mollie
      boundary) and bad-date error path.

Only the Mollie API client boundary is stubbed (hand-written stub clients /
raising stubs standing in for the live HTTP/SDK layer). Every importer method
under test runs for real against real Bank Transaction / Member / SEPA Mandate /
MT940 Import documents.
"""

from datetime import datetime, timezone

import frappe

from verenigingen.tests.payment.test_bulk_transaction_importer_sweep import (
    _BulkImporterSweepBase,
    _payment,
    _StubPaymentsClient,
    _StubSettlementsClient,
)
from verenigingen.verenigingen_payments.clients import bulk_transaction_importer as bti_module
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
    BulkTransactionImporter,
    run_bulk_import,
)


class _RaisingSettlementsClient:
    """Stand-in for the settlements HTTP client whose call fails (network/API)."""

    def __init__(self, exc):
        self._exc = exc

    def get_settlements_by_date_range(self, from_str, to_str):
        raise self._exc


class _RaisingPaymentsClient:
    """Stand-in for the payments HTTP client whose list call fails."""

    def __init__(self, exc):
        self._exc = exc

    def list_payments(self, from_date=None, to_date=None):
        raise self._exc


class TestImportTransactionsErrorStatus(_BulkImporterSweepBase):
    """import_transactions surfaces strategy errors as completed_with_errors."""

    def test_payment_value_error_yields_completed_with_errors(self):
        """A payment with a malformed createdAt raises ValueError inside the
        per-payment loop; the importer records it as an error and the overall
        status becomes completed_with_errors (not 'completed')."""
        self.expectErrorLog("Payment Data Validation")
        bad_payment = _payment(f"tr_baddate_{self.uid}", value="10.00")
        bad_payment["createdAt"] = "not-a-real-timestamp"
        self.imp.payments_client = _StubPaymentsClient([bad_payment])
        self.imp.settlements_client = _StubSettlementsClient([])

        results = self.imp.import_transactions(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            "payments",
            self.company,
            self.bank_account,
        )
        self.assertEqual(results["status"], "completed_with_errors")
        self.assertEqual(results["transactions"]["payments_imported"], 0)
        self.assertGreaterEqual(results["transactions"]["errors"], 1)
        self.assertTrue(any("validation error" in e.lower() for e in results["errors"]))


class TestImportPaymentDataBranches(_BulkImporterSweepBase):
    """_import_payment_data naive-datetime conversion and outer handlers."""

    def test_naive_datetimes_converted_to_utc(self):
        """Called directly with naive datetimes, _import_payment_data converts
        them to UTC before querying (the tz-None branches)."""
        self.imp.payments_client = _StubPaymentsClient([])
        naive_from = datetime(2024, 3, 1)  # no tzinfo
        naive_to = datetime(2024, 3, 31)  # no tzinfo
        results = self.imp._import_payment_data(naive_from, naive_to, self.company, self.bank_account)
        self.assertEqual(results["imported"], 0)
        self.assertEqual(results["errors"], [])

    def test_network_error_recorded(self):
        self.expectErrorLog("Bulk Payment Network Error")
        self.imp.payments_client = _RaisingPaymentsClient(ConnectionError("boom"))
        results = self.imp._import_payment_data(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            self.company,
            self.bank_account,
        )
        self.assertTrue(any("Network error" in e for e in results["errors"]))

    def test_validation_error_recorded(self):
        self.expectErrorLog("Bulk Payment Validation")
        self.imp.payments_client = _RaisingPaymentsClient(frappe.ValidationError("nope"))
        results = self.imp._import_payment_data(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            self.company,
            self.bank_account,
        )
        self.assertTrue(any("Validation error" in e for e in results["errors"]))

    def test_generic_error_recorded(self):
        self.expectErrorLog("Bulk Transaction Import")
        self.imp.payments_client = _RaisingPaymentsClient(RuntimeError("kaboom"))
        results = self.imp._import_payment_data(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            self.company,
            self.bank_account,
        )
        self.assertTrue(any("Payment data import failed" in e for e in results["errors"]))


class TestImportSettlementDataBranches(_BulkImporterSweepBase):
    """_import_settlement_data outer API-failure handler."""

    def test_settlement_api_failure_recorded(self):
        self.expectErrorLog("Bulk Transaction Import")
        self.imp.settlements_client = _RaisingSettlementsClient(RuntimeError("api down"))
        results = self.imp._import_settlement_data(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            self.company,
            self.bank_account,
        )
        self.assertEqual(results["imported"], 0)
        self.assertTrue(any("Settlement data import failed" in e for e in results["errors"]))


class TestCreateBankTransactionResolutionBranches(_BulkImporterSweepBase):
    """Default company/bank-account resolution + missing-bank-account guard."""

    def test_payment_resolves_default_company_and_bank(self):
        """With company/bank_account omitted, the importer resolves a default
        Company and a Bank Account belonging to that company (the resolution
        branch). The resolved bank account must be consistent with the company."""
        # Pin the resolved default Company to our seeded EUR test company so the
        # resolution branch lands on a company that actually has a Bank Account.
        # (Otherwise it resolves the site's Global Defaults company, which has no
        # bank account under CI — the source of the env-fragile failure.)
        frappe.defaults.set_user_default("Company", self.company)
        self.imp.import_id = f"res_{self.uid}"
        bt = self.imp._create_bank_transaction_from_payment(
            _payment(f"tr_resolve_{self.uid}", value="12.00"),
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            company=None,
            bank_account=None,
        )
        self.assertIsNotNone(bt)
        self.assertTrue(bt.company)
        self.assertTrue(bt.bank_account)
        # The resolved bank account must belong to the resolved company.
        self.assertEqual(
            frappe.db.get_value("Bank Account", bt.bank_account, "company"), bt.company
        )

    def test_settlement_resolves_default_company_and_bank(self):
        """Settlement creation also resolves a default Company + Bank Account when
        both are omitted (the settlement-side resolution branch)."""
        # Pin the resolved default Company to our seeded EUR test company (see
        # test_payment_resolves_default_company_and_bank for the rationale).
        frappe.defaults.set_user_default("Company", self.company)
        self.imp.import_id = f"sres_{self.uid}"
        bt = self.imp._create_bank_transaction_from_settlement(
            {
                "id": f"stl_resolve_{self.uid}",
                "reference": "res-ref",
                "amount": {"value": "300.00", "currency": "EUR"},
            },
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            company=None,
            bank_account=None,
        )
        self.assertIsNotNone(bt)
        self.assertEqual(
            frappe.db.get_value("Bank Account", bt.bank_account, "company"), bt.company
        )

    def test_payment_no_bank_account_returns_none(self):
        """A company with no Bank Account yields no transaction (None)."""
        bt = self.imp._create_bank_transaction_from_payment(
            _payment(f"tr_nobank_{self.uid}", value="5.00"),
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            company=f"No Such Company {self.uid}",
            bank_account=None,
        )
        self.assertIsNone(bt)

    def test_settlement_no_bank_account_returns_none(self):
        bt = self.imp._create_bank_transaction_from_settlement(
            {"id": f"stl_nobank_{self.uid}", "amount": {"value": "5.00", "currency": "EUR"}},
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            company=f"No Such Company {self.uid}",
            bank_account=None,
        )
        self.assertIsNone(bt)

    def test_payment_bad_amount_returns_none(self):
        """A non-numeric Mollie amount raises in the creation path and is caught,
        returning None rather than propagating."""
        self.expectErrorLog("Bulk Payment Import")
        bad = _payment(f"tr_badamt_{self.uid}")
        bad["amount"] = {"value": "not-a-number", "currency": "EUR"}
        bt = self.imp._create_bank_transaction_from_payment(
            bad, datetime(2024, 3, 15, tzinfo=timezone.utc), self.company, self.bank_account
        )
        self.assertIsNone(bt)

    def test_settlement_bad_amount_returns_none(self):
        self.expectErrorLog("Bulk Settlement Import")
        bt = self.imp._create_bank_transaction_from_settlement(
            {"id": f"stl_badamt_{self.uid}", "amount": {"value": "xyz", "currency": "EUR"}},
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            self.company,
            self.bank_account,
        )
        self.assertIsNone(bt)


class TestProcessForImportErrorBranches(_BulkImporterSweepBase):
    """_process_*_for_import skipped + malformed-date branches."""

    def test_process_settlement_create_fails_marks_skipped(self):
        """When bank-transaction creation returns None (bad amount), the settlement
        is marked skipped with a reason rather than imported."""
        self.expectErrorLog("Bulk Settlement Import")
        self.imp.import_id = f"ps_{self.uid}"
        settlement = {
            "id": f"stl_skip_{self.uid}",
            "amount": {"value": "not-a-number", "currency": "EUR"},
            "settledAt": "2024-03-20T00:00:00.000Z",
        }
        result = self.imp._process_settlement_for_import(settlement, self.company, self.bank_account)
        self.assertEqual(result.get("skipped"), 1)
        self.assertEqual(result.get("reason"), "Failed to create bank transaction")

    def test_process_settlement_malformed_date_records_error(self):
        self.expectErrorLog("Bulk Settlement Processing")
        result = self.imp._process_settlement_for_import(
            {"id": "stl_baddate", "settledAt": "garbage-date"}, self.company, self.bank_account
        )
        self.assertIn("error", result)

    def test_process_payment_malformed_date_records_error(self):
        self.expectErrorLog("Bulk Payment Processing")
        result = self.imp._process_payment_for_import(
            {"id": "tr_baddate", "createdAt": "garbage-date"}, self.company, self.bank_account
        )
        self.assertIn("error", result)
        self.assertFalse(result.get("imported"))


class TestValidateDuplicateCriteria(_BulkImporterSweepBase):
    """_validate_duplicate_transaction settlement-id + amount/date/reference."""

    def _persist_bt(self, **fields):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = fields.get("date", frappe.utils.today())
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.currency = "EUR"
        bt.deposit = fields.get("deposit", 0)
        bt.withdrawal = fields.get("withdrawal", 0)
        bt.reference_number = fields.get("reference_number")
        if fields.get("custom_mollie_settlement_id"):
            bt.custom_mollie_settlement_id = fields["custom_mollie_settlement_id"]
        bt.insert(ignore_permissions=True)
        self.created_records.append(("Bank Transaction", bt.name))
        return bt

    def test_duplicate_by_settlement_id(self):
        stl_id = f"stl_dup_{self.uid}"
        self._persist_bt(custom_mollie_settlement_id=stl_id, deposit=100)
        self.assertTrue(
            self.imp._validate_duplicate_transaction({"custom_mollie_settlement_id": stl_id})
        )

    def test_duplicate_by_amount_date_reference(self):
        """A withdrawal matched on amount + date + reference_number is a duplicate
        even without a Mollie id on the incoming row."""
        ref = f"ref_dup_{self.uid}"
        today = frappe.utils.today()
        self._persist_bt(withdrawal=55.0, reference_number=ref, date=today)
        self.assertTrue(
            self.imp._validate_duplicate_transaction(
                {"withdrawal": 55.0, "date": today, "reference_number": ref}
            )
        )

    def test_non_duplicate_amount_returns_false(self):
        ref = f"ref_nodup_{self.uid}"
        today = frappe.utils.today()
        self.assertFalse(
            self.imp._validate_duplicate_transaction(
                {"withdrawal": 99.0, "date": today, "reference_number": ref}
            )
        )


class TestFindMemberMultipleMatches(_BulkImporterSweepBase):
    """_find_member_by_payment_details does not auto-assign on ambiguous names."""

    def test_multiple_fuzzy_name_matches_returns_none(self):
        shared = f"Ambiguous Donor {self.uid}"
        for i in range(2):
            m = self.create_test_member(
                first_name="Ambiguous",
                last_name=f"Donor{self.uid}{i}",
                email=f"ambiguous.{self.uid}.{i}@example.com",
            )
            frappe.db.set_value("Member", m.name, "full_name", f"{shared} {i}")
        # Two members LIKE '%Ambiguous Donor <uid>%' -> ambiguous -> no auto-assign.
        self.assertIsNone(self.imp._find_member_by_payment_details(consumer_name=shared))


class TestSaveImportRecordBranches(_BulkImporterSweepBase):
    """_save_import_record fallback / non-existent bank / malformed results."""

    def _results(self, **over):
        base = {
            "import_id": f"sr_{self.uid}",
            "strategy": "hybrid",
            "company": self.company,
            "bank_account": self.bank_account,
            "status": "completed",
            "date_range": {"from": "2024-03-01T00:00:00+00:00", "to": "2024-03-31T00:00:00+00:00"},
            "transactions": {
                "settlements_imported": 0,
                "payments_imported": 1,
                "duplicates_skipped": 0,
                "errors": 0,
                "total_imported": 1,
            },
        }
        base.update(over)
        return base

    def test_fallback_bank_account_used_when_missing(self):
        """With no bank_account in results, _save_import_record falls back to the
        first Bank Account in the system and still persists the record."""
        self.imp.import_id = f"sr_{self.uid}"
        self.imp._save_import_record(self._results(bank_account=None))
        rec = frappe.db.get_value(
            "MT940 Import", {"import_summary": ["like", f"%sr_{self.uid}%"]}, "bank_account"
        )
        self.assertTrue(rec)  # some fallback bank account was assigned

    def test_nonexistent_bank_account_branch(self):
        """A bank_account value that does not exist exercises the existence-check /
        available-accounts diagnostic branch; persistence still does not raise."""
        self.expectErrorLog("Bulk Import Record")
        self.imp.import_id = f"srx_{self.uid}"
        # Should not raise even though the bank account does not exist.
        self.imp._save_import_record(
            self._results(import_id=f"srx_{self.uid}", bank_account=f"NONEXISTENT-{self.uid}")
        )

    def test_malformed_results_handled(self):
        """Results missing the 'status' key raise inside the builder; the method
        swallows it (logs) rather than propagating."""
        self.expectErrorLog("Bulk Import Record")
        self.imp.import_id = f"srbad_{self.uid}"
        broken = self._results()
        broken.pop("status")
        # Must not raise.
        self.imp._save_import_record(broken)


class TestEstimateImportSizeError(_BulkImporterSweepBase):
    """estimate_import_size records an error when the settlements API fails."""

    def test_settlement_api_failure_sets_error(self):
        self.imp.settlements_client = _RaisingSettlementsClient(RuntimeError("api down"))
        est = self.imp.estimate_import_size(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            "settlements",
        )
        self.assertIn("error", est)


class TestRunBulkImportEndpoint(_BulkImporterSweepBase):
    """run_bulk_import whitelisted endpoint: success + bad-date paths."""

    def test_bad_date_returns_failed(self):
        self.expectErrorLog("Bulk Import API")
        result = run_bulk_import("not-a-date", "2024-03-31", "payments", self.company, self.bank_account)
        self.assertEqual(result["status"], "failed")
        self.assertIn("error", result)

    def _stub_module_clients(self, payments, settlements):
        """Replace the three Mollie client classes at the module boundary; returns
        a restore() callable. Only the live HTTP/SDK layer is stubbed."""
        orig = (bti_module.PaymentsClient, bti_module.SettlementsClient, bti_module.BalancesClient)

        class _StubBalances:
            def __init__(self, *a, **k):
                pass

        bti_module.PaymentsClient = lambda *a, **k: _StubPaymentsClient(payments)
        bti_module.SettlementsClient = lambda *a, **k: _StubSettlementsClient(settlements)
        bti_module.BalancesClient = _StubBalances

        def restore():
            bti_module.PaymentsClient, bti_module.SettlementsClient, bti_module.BalancesClient = orig

        return restore

    def test_success_path_with_stubbed_clients(self):
        """The endpoint builds its own importer; stub the Mollie client classes at
        the module boundary so the full endpoint body runs without live HTTP."""
        payments = [_payment(f"tr_ep_{self.uid}", value="18.00")]
        restore = self._stub_module_clients(payments, [])
        try:
            result = run_bulk_import(
                "2024-03-01", "2024-03-31", "payments", self.company, self.bank_account
            )
        finally:
            restore()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["transactions"]["payments_imported"], 1)
        self.assertEqual(result["company"], self.company)
        self.assertTrue(
            frappe.db.exists("Bank Transaction", {"reference_number": f"tr_ep_{self.uid}"})
        )

    def test_estimate_bulk_import_size_success(self):
        """The whitelisted estimate endpoint returns a structured estimate for valid
        dates (its happy path), counting the settlements the stub client returns."""
        from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
            estimate_bulk_import_size,
        )

        restore = self._stub_module_clients([], [{"id": "a"}, {"id": "b"}])
        try:
            est = estimate_bulk_import_size("2024-03-01", "2024-03-31", "settlements")
        finally:
            restore()
        self.assertNotIn("error", est)
        self.assertEqual(est["settlements_count"], 2)
        self.assertEqual(est["estimated_transactions"], 2)
