"""Real-integration tests for the *Mollie Balance Report* script report
(``verenigingen/verenigingen/report/mollie_balance_report/``).

This report was at 0% coverage. It surfaces Mollie balance data via the
``FinancialDashboard``. The happy path requires a live Mollie Organization
Access Token and is therefore out of scope here (no token in the test env).

What IS reachable -- and what these tests cover -- are the guard / early-return
branches in ``get_data``:
  * Mollie Backend API not enabled -> returns [] with a msgprint.
  * Backend API enabled but no Organization Access Token configured -> returns [].
  * the column structure of ``get_columns``.

Tests run as Administrator (who passes the ``Mollie Settings`` read-permission
check), and restore the original ``enable_backend_api`` flag afterwards.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.mollie_balance_report import mollie_balance_report as report
from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
    MollieConfigurationService,
)


class TestMollieBalanceReport(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._orig_enabled = frappe.db.get_single_value("Mollie Settings", "enable_backend_api")

    def tearDown(self):
        self._set_backend_api(self._orig_enabled or 0)
        super().tearDown()

    def _set_backend_api(self, value):
        frappe.db.set_single_value("Mollie Settings", "enable_backend_api", value)
        MollieConfigurationService.clear_cache()

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        self.assertEqual(len(columns), 6)
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(fieldnames[0], "currency")
        self.assertIn("available", fieldnames)
        self.assertIn("total", fieldnames)
        self.assertEqual(columns[-1]["fieldname"], "last_updated")

    # ------------------------------------------------------- not-enabled branch

    def test_backend_api_disabled_returns_empty(self):
        self._set_backend_api(0)
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 6)
        self.assertEqual(data, [], "no rows when the Mollie backend API is disabled")

    def test_get_data_disabled_returns_empty_list(self):
        self._set_backend_api(0)
        with self.assertNoErrorLog():
            data = report.get_data()
        self.assertEqual(data, [])

    # --------------------------------------------------- no-token branch

    def test_backend_api_enabled_without_token_returns_empty(self):
        # Enabling the backend API but leaving the Organization Access Token unset
        # reaches the "token not configured" guard, which returns [] without
        # touching the live Mollie API. (If a token happens to be configured in
        # this environment the call would proceed to the dashboard; we assert the
        # report still degrades gracefully to a list either way.)
        self._set_backend_api(1)
        settings = frappe.get_single("Mollie Settings")
        token = settings.get_password("organization_access_token", raise_exception=False)

        data = report.get_data()
        self.assertIsInstance(data, list)
        if not token:
            self.assertEqual(data, [], "no token configured -> empty result")

    def test_execute_returns_columns_and_list_data(self):
        # execute() must always return a (columns, data) pair with list data,
        # regardless of the backend state.
        self._set_backend_api(0)
        with self.assertNoErrorLog():
            result = report.execute(None)
        self.assertEqual(len(result), 2)
        columns, data = result
        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)
