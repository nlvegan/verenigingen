"""Real-integration tests for the *ANBI Periodic Agreements* script report
(``verenigingen/verenigingen/report/anbi_periodic_agreements/``).

The report was at ~65% coverage; the existing API-level test
(``tests/api/test_periodic_donation_operations.py``) never calls the report's
``execute``. These tests seed real Periodic Donation Agreements and exercise the
previously-uncovered branches of the report:

  * the ANBI-disabled early return;
  * row computations -- days_remaining, expected_total, completion_percentage,
    the "(Expiring Soon)" / "Expired" status decorations, duration parsing;
  * every ``get_conditions`` filter branch (status / donor / anbi_eligible
    Yes & No / expiring_in_days / payment_frequency / min_annual_amount).

Tests force ``enable_anbi_functionality`` on (and restore it afterwards) so the
data branches are reachable irrespective of the site default.
"""

import frappe
from frappe.utils import add_days, add_years, today

from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.anbi_periodic_agreements import (
    anbi_periodic_agreements as report,
)


class TestAnbiPeriodicAgreementsReport(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._orig_anbi = frappe.db.get_single_value(
            "Verenigingen Settings", "enable_anbi_functionality"
        )
        frappe.db.set_single_value("Verenigingen Settings", "enable_anbi_functionality", 1)

    def tearDown(self):
        frappe.db.set_single_value(
            "Verenigingen Settings", "enable_anbi_functionality", self._orig_anbi
        )
        super().tearDown()

    # ------------------------------------------------------------- helpers

    def _make_consenting_donor(self):
        """A donor that has given ANBI consent and carries a valid BSN -- required
        by the controller before an ANBI-eligible agreement can be created."""
        return self.create_test_donor(
            anbi_consent=1,
            anbi_consent_date=today(),
            bsn_citizen_service_number=generate_valid_bsn(),
        )

    def _make_agreement(self, **kwargs):
        """Persist an agreement and force the report-read fields directly in the
        DB (the controller recomputes end_date/total_donated on save)."""
        overrides = {}
        for field in ("status", "end_date", "total_donated", "next_expected_donation", "annual_amount"):
            if field in kwargs:
                overrides[field] = kwargs.pop(field)

        # ANBI-eligible agreements (the factory default) require a consenting donor.
        if kwargs.get("anbi_eligible", 1) and "donor" not in kwargs:
            kwargs["donor"] = self._make_consenting_donor().name

        agreement = self.create_test_periodic_donation_agreement(**kwargs)
        for field, value in overrides.items():
            frappe.db.set_value("Periodic Donation Agreement", agreement.name, field, value)
        agreement.reload()
        return agreement

    def _row_for(self, data, agreement):
        return next((r for r in data if r["agreement_number"] == agreement.agreement_number), None)

    # ------------------------------------------------------- anbi-disabled

    def test_anbi_disabled_returns_empty(self):
        frappe.db.set_single_value("Verenigingen Settings", "enable_anbi_functionality", 0)
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(columns, [])
        self.assertEqual(data, [])

    # ------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertIn("agreement_number", fieldnames)
        self.assertIn("days_remaining", fieldnames)
        self.assertIn("completion_percentage", fieldnames)
        self.assertIn("expected_total", fieldnames)

    # ------------------------------------------------------- row computations

    def test_active_agreement_appears_with_computed_fields(self):
        agreement = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -200),
            end_date=add_years(today(), 5),
            annual_amount=1200,
            total_donated=600,
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        row = self._row_for(data, agreement)
        self.assertIsNotNone(row, "active agreement must appear")
        self.assertGreater(row["days_remaining"], 0)
        self.assertGreater(row["expected_total"], 0)
        self.assertGreater(row["completion_percentage"], 0)

    def test_expiring_soon_decoration(self):
        agreement = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -1000),
            end_date=add_days(today(), 30),  # within 90 days -> Expiring Soon
            annual_amount=1200,
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        row = self._row_for(data, agreement)
        self.assertIsNotNone(row)
        self.assertIn("Expiring Soon", row["status"])
        self.assertGreater(row["days_remaining"], 0)

    def test_expired_decoration_when_end_date_passed(self):
        agreement = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -2000),
            end_date=add_days(today(), -5),  # past -> days_remaining clamps to 0 -> Expired
            annual_amount=1200,
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        row = self._row_for(data, agreement)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "Expired")
        self.assertEqual(row["days_remaining"], 0)

    def test_non_active_status_zeroes_days_and_next_expected(self):
        agreement = self._make_agreement(
            status="Cancelled",
            start_date=add_days(today(), -100),
            end_date=add_years(today(), 4),
            annual_amount=1200,
            next_expected_donation=add_days(today(), 30),
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        row = self._row_for(data, agreement)
        self.assertIsNotNone(row)
        self.assertEqual(row["days_remaining"], 0)
        self.assertIsNone(row["next_expected_donation"])

    def test_completion_percentage_full(self):
        agreement = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -365),
            end_date=add_days(today(), 1),  # ~1 year window
            annual_amount=1000,
            total_donated=1000,
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        row = self._row_for(data, agreement)
        self.assertIsNotNone(row)
        # ~1 year window at 1000/yr -> expected ~1000, donated 1000 -> ~100%.
        self.assertGreater(row["completion_percentage"], 80)

    # ------------------------------------------------------- filter branches

    def test_filter_by_status(self):
        active = self._make_agreement(status="Active", annual_amount=1200)
        cancelled = self._make_agreement(status="Cancelled", annual_amount=1200)
        with self.assertNoErrorLog():
            _columns, data = report.execute({"status": "Active"})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(active.agreement_number, numbers)
        self.assertNotIn(cancelled.agreement_number, numbers)

    def test_filter_by_donor(self):
        donor = self._make_consenting_donor()
        mine = self._make_agreement(donor=donor.name, status="Active", annual_amount=1200)
        other = self._make_agreement(status="Active", annual_amount=1200)
        with self.assertNoErrorLog():
            _columns, data = report.execute({"donor": donor.name})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(mine.agreement_number, numbers)
        self.assertNotIn(other.agreement_number, numbers)

    def test_filter_anbi_eligible_yes(self):
        eligible = self._make_agreement(
            status="Active", anbi_eligible=1, annual_amount=1200,
            agreement_duration_years="5 Years (ANBI Minimum)",
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({"anbi_eligible": "Yes"})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(eligible.agreement_number, numbers)
        self.assertTrue(all(r["anbi_eligible"] for r in data))

    def test_filter_anbi_eligible_no(self):
        not_eligible = self._make_agreement(
            status="Active", anbi_eligible=0, annual_amount=1200,
            agreement_duration_years="1 Year (Pledge - No ANBI benefits)",
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({"anbi_eligible": "No"})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(not_eligible.agreement_number, numbers)
        self.assertTrue(all(not r["anbi_eligible"] for r in data))

    def test_filter_by_payment_frequency(self):
        monthly = self._make_agreement(
            status="Active", payment_frequency="Monthly", annual_amount=1200
        )
        quarterly = self._make_agreement(
            status="Active", payment_frequency="Quarterly", annual_amount=1200
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({"payment_frequency": "Monthly"})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(monthly.agreement_number, numbers)
        self.assertNotIn(quarterly.agreement_number, numbers)

    def test_filter_by_min_annual_amount(self):
        big = self._make_agreement(status="Active", annual_amount=5000)
        small = self._make_agreement(status="Active", annual_amount=100)
        with self.assertNoErrorLog():
            _columns, data = report.execute({"min_annual_amount": 1000})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(big.agreement_number, numbers)
        self.assertNotIn(small.agreement_number, numbers)

    def test_filter_expiring_in_days(self):
        soon = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -1000),
            end_date=add_days(today(), 20),
            annual_amount=1200,
        )
        far = self._make_agreement(
            status="Active",
            start_date=add_days(today(), -100),
            end_date=add_years(today(), 4),
            annual_amount=1200,
        )
        with self.assertNoErrorLog():
            _columns, data = report.execute({"expiring_in_days": 60})
        numbers = {r["agreement_number"] for r in data}
        self.assertIn(soon.agreement_number, numbers)
        self.assertNotIn(far.agreement_number, numbers)
