"""
#3131: ``EBoekhoudenImportManager._get_existing_imports`` must honour BOTH date bounds.

It assigned ``filters["posting_date"]`` twice, so a ``to_date`` silently replaced the
``from_date`` bound and the range read "everything up to to_date".

The Payment Entries come from the importer itself (``_create_payment_entry``), on three
distinct posting dates, so a row BEFORE ``from_date`` exists for the wrong behaviour to find.

Run with:
    bench --site test_site_9 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_import_manager_existing_imports_date_range_3131
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _create_payment_entry
from verenigingen.e_boekhouden.utils.import_manager import EBoekhoudenImportManager
from verenigingen.tests.e_boekhouden.test_rest_migration_payments import (
    BANK_LEDGER,
    INCOME_LEDGER,
    _PaymentTestBase,
)


class TestExistingImportsDateRange3131(_PaymentTestBase):
    def setUp(self):
        super().setUp()
        self._orig_default_company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", self.company)
        self.early = add_days(today(), -6)
        self.middle = add_days(today(), -3)
        self.late = today()
        self.mutation_by_date = {d: self._import_payment_on(d) for d in (self.early, self.middle, self.late)}

    def tearDown(self):
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", self._orig_default_company)
        super().tearDown()

    def _import_payment_on(self, posting_date):
        mutation = {
            "id": self._uid(),
            "type": 3,
            "date": posting_date,
            "amount": 50.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "",
            "description": f"existing-imports 3131 {posting_date}",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 50.0, "description": "row"}],
        }
        _create_payment_entry(mutation, self.company, self.cost_center, [])
        return mutation["id"]

    def _ours_in_range(self, from_date=None, to_date=None):
        """Posting dates of OUR imported rows that the range returns (other imports on the site are ignored)."""
        ours = {mutation_id: d for d, mutation_id in self.mutation_by_date.items()}
        found = EBoekhoudenImportManager()._get_existing_imports(from_date, to_date)
        return sorted(
            getdate(ours[row["mutation_id"]]) for row in found if row["mutation_id"] in ours
        )

    def test_both_bounds_return_only_the_rows_inside_the_range(self):
        self.assertEqual(
            self._ours_in_range(add_days(today(), -4), add_days(today(), -1)),
            [getdate(self.middle)],
        )

    def test_row_before_from_date_is_excluded_when_to_date_is_also_given(self):
        found = self._ours_in_range(add_days(today(), -4), today())
        self.assertNotIn(getdate(self.early), found)
        self.assertEqual(found, [getdate(self.middle), getdate(self.late)])

    def test_from_date_equal_to_a_posting_date_includes_that_row(self):
        # Pins the inclusive lower bound: a `>`-style or from_date+1 mutant drops the middle row.
        self.assertEqual(
            self._ours_in_range(self.middle, self.late),
            [getdate(self.middle), getdate(self.late)],
        )

    def test_from_date_alone_has_no_upper_bound(self):
        self.assertEqual(
            self._ours_in_range(add_days(today(), -4)), [getdate(self.middle), getdate(self.late)]
        )

    def test_to_date_alone_has_no_lower_bound(self):
        self.assertEqual(
            self._ours_in_range(to_date=add_days(today(), -4)), [getdate(self.early)]
        )

    def test_no_dates_returns_every_row(self):
        self.assertEqual(
            self._ours_in_range(),
            sorted(getdate(d) for d in (self.early, self.middle, self.late)),
        )
