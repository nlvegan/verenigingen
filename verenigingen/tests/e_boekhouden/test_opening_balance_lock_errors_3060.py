"""#3060: the e-Boekhouden opening-balance import must not turn a 1213/1205 into ``success: False``.

A 1213 makes the server roll the WHOLE transaction back; a 1205 leaves the unit of work
half-applied. The import frames caught ``except Exception`` and returned a failure dict, so the
caller carried on against state the server had thrown away (#3008 class). Each test injects a
real-shape lock error at the DRIVER (``Cursor.execute``), below every swallowing layer, and
asserts it reaches the caller.

Probe shortcut, stated: the lock error is injected, not provoked, and no server ROLLBACK is
issued -- the question under test is only who sees the error.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    import_opening_balances_only,
)
from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _get_or_create_temporary_diff_account,
    _import_opening_balances,
    _import_opening_balances_from_data,
    get_erpnext_account_from_ledger_id,
)
from verenigingen.e_boekhouden.utils.stock_account_handler import (
    import_opening_balances_with_stock_handling,
)
from verenigingen.tests.e_boekhouden.test_opening_balance_import import _OpeningBalanceBase
from verenigingen.tests.e_boekhouden.test_party_creation_lock_errors_3029 import _lock_error_at_driver_3029

_API = "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI"


class TestOpeningBalanceLockErrors3060(_OpeningBalanceBase):
    def setUp(self):
        super().setUp()
        self._delete_existing_ob()

    def _fetch_api_3060(self, payload):
        api = MagicMock()
        api.make_request.return_value = {
            "success": True,
            "status_code": 200,
            "data": frappe.as_json(payload),
        }
        return api

    def _payload_3060(self, with_stock=False):
        rows = [
            {"id": 1, "ledgerId": self.LEDGERS["asset"], "amount": 1000.0, "date": today()},
            {"id": 2, "ledgerId": self.LEDGERS["liability"], "amount": 1000.0, "date": today()},
        ]
        if with_stock:
            rows.append({"id": 3, "ledgerId": self.LEDGERS["stock"], "amount": 500.0, "date": today()})
        return rows

    def _reaches_caller_3060(self, fragment, startswith, call, before=None):
        """Both non-resumable classes must reach the caller, and the injection must have fired.
        ``before`` runs ahead of the injection (fixture setup that must not see the fault)."""
        for code, error in ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError)):
            with self.subTest(code=code):
                self._delete_existing_ob()
                if before:
                    before()
                inject, hits = _lock_error_at_driver_3029(fragment, startswith, code)
                with inject, self.assertRaises(error):
                    call()
                self.assertTrue(hits, "the injection must have fired")

    def test_api_path_journal_entry_insert_lock_error_reaches_caller(self):
        def call():
            with patch(_API, return_value=self._fetch_api_3060(self._payload_3060())):
                _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)

        self._reaches_caller_3060("`tabJournal Entry`", ("INSERT",), call)

    def test_data_path_journal_entry_insert_lock_error_reaches_caller(self):
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        self._reaches_caller_3060(
            "`tabJournal Entry`",
            ("INSERT",),
            lambda: _import_opening_balances_from_data(muts, self.company, self.cost_center, [], False),
        )

    def test_api_path_stock_item_lock_error_reaches_caller(self):
        """The JE is already written when the stock branch runs; a lock error there must not
        be reduced to a debug_info line."""

        def call():
            payload = self._payload_3060(with_stock=True)
            with patch(_API, return_value=self._fetch_api_3060(payload)):
                _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)

        self._reaches_caller_3060("`tabItem`", ("INSERT",), call)

    def test_api_path_stock_reconciliation_lock_error_reaches_caller(self):
        """The per-account ``continue`` handler around the Stock Reconciliation save."""

        def call():
            payload = self._payload_3060(with_stock=True)
            with patch(_API, return_value=self._fetch_api_3060(payload)):
                _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=False)

        self._reaches_caller_3060("`tabStock Reconciliation`", ("INSERT",), call)

    def test_force_reimport_delete_lock_error_reaches_caller(self):
        def call():
            with patch(_API, return_value=self._fetch_api_3060(self._payload_3060())):
                _import_opening_balances(self.company, self.cost_center, [], dry_run=False, force=True)

        self._reaches_caller_3060(
            "`tabJournal Entry`", ("UPDATE",), call, before=self._seed_existing_ob_je_3060
        )

    def test_account_classification_lock_error_is_not_a_skipped_account(self):
        """A lock error on the Account read must not park the balance in the
        temporary-difference account and report success."""
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        self._reaches_caller_3060(
            "`tabAccount`",
            ("SELECT",),
            lambda: _import_opening_balances_from_data(muts, self.company, self.cost_center, [], False),
        )

    def test_missing_ledger_mapping_fetch_lock_error_reaches_caller(self):
        def call():
            with patch(
                "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
            ) as iterator:
                iterator.return_value._get_session_token.return_value = "t"
                iterator.return_value.base_url = "http://stub.invalid"
                with patch("requests.get") as get:
                    get.return_value.status_code = 200
                    get.return_value.json.return_value = {"code": "99999", "description": "x"}
                    get_erpnext_account_from_ledger_id(987654, self.company, [], auto_create=True)

        self._reaches_caller_3060("`tabAccount`", ("SELECT",), call)

    def test_temporary_difference_account_create_lock_error_reaches_caller(self):
        from verenigingen.tests.e_boekhouden.test_opening_balance_import import (
            TestTemporaryAccounts as _Temp,
        )

        # A company with NO Temporary account, so the create branch (and its handler) runs.
        company = _Temp._ensure_clean_temp_company()
        self._reaches_caller_3060(
            "`tabAccount`",
            ("INSERT",),
            lambda: _get_or_create_temporary_diff_account(company, []),
            before=lambda: _Temp._ensure_clean_temp_company(),
        )

    def test_fiscal_year_lookup_lock_error_reaches_caller(self):
        self.expectErrorLog("Fiscal Year Auto-Creation")
        muts = [
            self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
            self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
        ]
        self._reaches_caller_3060(
            "`tabFiscal Year`",
            ("SELECT",),
            lambda: _import_opening_balances_from_data(muts, self.company, self.cost_center, [], False),
        )

    def test_whitelisted_migration_endpoint_does_not_report_a_lock_error_as_failure(self):
        self._reaches_caller_3060(
            "`tabE-Boekhouden Migration`",
            ("SELECT",),
            lambda: import_opening_balances_only("no-such-migration-3060"),
        )

    def test_whitelisted_stock_handling_endpoint_does_not_report_a_lock_error_as_failure(self):
        def call():
            rows = [
                self._mut("asset", 1000.0, amount_field="balance", mid=1, date=today()),
                self._mut("liability", 1000.0, amount_field="balance", mid=2, date=today()),
            ]
            api = MagicMock()
            api.make_request.return_value = {"success": True, "data": rows}
            with patch(_API, return_value=api):
                import_opening_balances_with_stock_handling(self.company, "skip_stock_accounts")

        self._reaches_caller_3060("`tabJournal Entry`", ("INSERT",), call)

    def _seed_existing_ob_je_3060(self):
        from verenigingen.tests.e_boekhouden.test_opening_balance_import import TestImportOpeningBalances

        return TestImportOpeningBalances._seed_existing_ob_je(self)
