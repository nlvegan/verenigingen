"""
Regression tests for #3012 and #3011 (Mollie bulk importer).

#3012: ``_save_import_record`` wrote ``import_status = "Completed With Errors"``
(or "... Warnings"), which ``MT940 Import.import_status`` did not offer, so the
insert failed and exactly the runs that had errors left no history record.

#3011: a row whose Bank Transaction creation returned None (creator failed
without raising) was neither imported nor counted as an error, so the run
reported ``completed``. The None is produced for real here by importing for a
company that has no Bank Account (the creator's "no bank account" branch).
"""

from datetime import datetime, timezone

import frappe

from verenigingen.tests.payment.test_bulk_transaction_importer_sweep import (
    _BulkImporterSweepBase,
    _payment,
    _StubPaymentsClient,
    _StubSettlementsClient,
)

_FROM = datetime(2024, 3, 1, tzinfo=timezone.utc)
_TO = datetime(2024, 3, 31, tzinfo=timezone.utc)


class TestBulkImporterStatusAndNoneRows(_BulkImporterSweepBase):
    def _no_bank_company(self):
        return f"No Such Company {self.uid}"

    def _history_status(self, import_id):
        return frappe.db.get_value(
            "MT940 Import", {"import_summary": ["like", f"%{import_id}%"]}, "import_status"
        )

    # ---- #3012 -------------------------------------------------------
    def _save_with_status(self, status):
        import_id = f"st3012_{status}_{self.uid}"
        self.imp.import_id = import_id
        self.imp._save_import_record(
            {
                "import_id": import_id,
                "strategy": "hybrid",
                "company": self.company,
                "bank_account": self.bank_account,
                "status": status,
                "date_range": {"from": _FROM.isoformat(), "to": _TO.isoformat()},
                "transactions": {
                    "settlements_imported": 0,
                    "payments_imported": 1,
                    "duplicates_skipped": 0,
                    "errors": 1,
                    "total_imported": 1,
                },
            }
        )
        return self._history_status(import_id)

    def test_completed_with_errors_record_is_saved_truthfully(self):
        self.assertEqual(self._save_with_status("completed_with_errors"), "Completed With Errors")

    def test_completed_with_warnings_record_is_saved_truthfully(self):
        self.assertEqual(self._save_with_status("completed_with_warnings"), "Completed With Warnings")

    def test_control_completed_record_is_still_saved_as_completed(self):
        self.assertEqual(self._save_with_status("completed"), "Completed")

    # ---- #3011 -------------------------------------------------------
    def test_payment_whose_creation_returns_none_is_an_error(self):
        # The no-Bank-Account company also fails the history-record insert (unknown Company link).
        self.expectErrorLog("Bulk Import Record")
        pid = f"tr_none_{self.uid}"
        self.imp.payments_client = _StubPaymentsClient([_payment(pid)])
        self.imp.settlements_client = _StubSettlementsClient([])
        results = self.imp.import_transactions(
            _FROM, _TO, "payments", self._no_bank_company(), None
        )
        self.assertEqual(results["transactions"]["payments_imported"], 0)
        self.assertEqual(results["status"], "completed_with_errors")
        self.assertTrue(any(pid in e for e in results["errors"]), results["errors"])

    def test_settlement_whose_creation_returns_none_is_an_error(self):
        # The no-Bank-Account company also fails the history-record insert (unknown Company link).
        self.expectErrorLog("Bulk Import Record")
        sid = f"stl_none_{self.uid}"
        settlement = {
            "id": sid,
            "amount": {"value": "5.00", "currency": "EUR"},
            "settledAt": "2024-03-20T00:00:00.000Z",
        }
        self.imp.payments_client = _StubPaymentsClient([])
        self.imp.settlements_client = _StubSettlementsClient([settlement])
        results = self.imp.import_transactions(
            _FROM, _TO, "settlements", self._no_bank_company(), None
        )
        self.assertEqual(results["transactions"]["settlements_imported"], 0)
        self.assertEqual(results["status"], "completed_with_errors")
        self.assertTrue(any(sid in e for e in results["errors"]), results["errors"])

    def test_control_payment_that_imports_is_not_an_error(self):
        pid = f"tr_ok_{self.uid}"
        self.imp.payments_client = _StubPaymentsClient([_payment(pid)])
        self.imp.settlements_client = _StubSettlementsClient([])
        results = self.imp.import_transactions(_FROM, _TO, "payments", self.company, self.bank_account)
        self.assertEqual(results["transactions"]["payments_imported"], 1)
        self.assertEqual(results["errors"], [])
        self.assertEqual(results["status"], "completed")

    def test_control_legitimate_settlement_skip_is_not_an_error(self):
        """A settlement without settledAt is a legitimate skip, not a failure."""
        self.imp.payments_client = _StubPaymentsClient([])
        self.imp.settlements_client = _StubSettlementsClient([{"id": f"stl_nodate_{self.uid}"}])
        results = self.imp.import_transactions(
            _FROM, _TO, "settlements", self.company, self.bank_account
        )
        self.assertEqual(results["errors"], [])
        self.assertEqual(results["status"], "completed")

    def test_run_with_a_failed_row_leaves_a_history_record(self):
        """End to end (#3012): a real run with one bad row still writes its record."""
        self.expectErrorLog("Payment Data Validation")
        bad = _payment(f"tr_hist_{self.uid}")
        bad["createdAt"] = "not-a-real-timestamp"
        self.imp.payments_client = _StubPaymentsClient([bad])
        self.imp.settlements_client = _StubSettlementsClient([])
        results = self.imp.import_transactions(_FROM, _TO, "payments", self.company, self.bank_account)
        self.assertEqual(results["status"], "completed_with_errors")
        self.assertEqual(self._history_status(results["import_id"]), "Completed With Errors")
