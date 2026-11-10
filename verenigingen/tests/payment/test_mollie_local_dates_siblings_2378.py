"""#2378: Mollie timestamps become the SITE-LOCAL day, never the UTC day (siblings of #2162/#2192).

Every instant below is 23:30 UTC on 3 March 2026: the UTC day is the 3rd, the day in
Europe/Amsterdam (and in the Kolkata test sites) is the 4th. The zone is pinned, so a
site-zone change cannot hide a regression, and each test names both days.

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_local_dates_siblings_2378
"""

import types
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.system_timezone import system_timezone
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.core.mollie_base_client import MollieBaseClient
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import update_donation_payment_history
from verenigingen.verenigingen_payments.mollie.services.payment_processors import DonationPaymentProcessor
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PaymentEntryFactory,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    MollieLogger,
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    customer_for_member,
)
from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

ZONE = "Europe/Amsterdam"
LATE_EVENING_UTC = "2026-03-03T23:30:00+00:00"
UTC_DAY = date(2026, 3, 3)
LOCAL_DAY = date(2026, 3, 4)


class TestExtractorDates(EnhancedTestCase):
    """payment_data_extractor.py: the helper behind most booking dates."""

    def setUp(self):
        super().setUp()
        self.extractor = get_payment_data_extractor()

    def test_extract_payment_date_string_is_the_local_day(self):
        with system_timezone(ZONE):
            got = self.extractor.extract_payment_date({"paid_at": LATE_EVENING_UTC})
        self.assertEqual(got, LOCAL_DAY, f"UTC day {UTC_DAY} must not be returned")

    def test_extract_payment_date_aware_datetime_is_the_local_day(self):
        moment = datetime(2026, 3, 3, 23, 30, tzinfo=timezone.utc)
        with system_timezone(ZONE):
            got = self.extractor.extract_payment_date({"paid_at": moment})
        self.assertEqual(got, LOCAL_DAY)

    def test_extract_payment_date_date_only_string_is_not_shifted(self):
        with system_timezone("Pacific/Honolulu"):
            got = self.extractor.extract_payment_date({"paid_at": "2026-03-04"})
        self.assertEqual(got, LOCAL_DAY)

    def test_extract_date_string_is_the_local_day(self):
        """``extract_date`` (bank transactions, dues, settlements) used getdate(): the UTC day."""
        obj = types.SimpleNamespace(paid_at=LATE_EVENING_UTC)
        with system_timezone(ZONE):
            got = self.extractor.extract_date(obj)
        self.assertEqual(got, LOCAL_DAY)

    def test_extract_date_date_only_string_is_not_shifted(self):
        obj = types.SimpleNamespace(paid_at="2026-03-04")
        with system_timezone("Pacific/Honolulu"):
            self.assertEqual(self.extractor.extract_date(obj), LOCAL_DAY)


class TestPaymentEntryReferenceDate(EnhancedTestCase):
    def test_reference_date_is_the_local_day(self):
        with system_timezone(ZONE):
            got = PaymentEntryFactory()._get_reference_date({"paid_at": LATE_EVENING_UTC})
        self.assertEqual(got, LOCAL_DAY)


class TestDonationBankTransactionDate(EnhancedTestCase):
    def test_bank_transaction_date_is_the_local_day(self):
        member = self.create_test_member(first_name="Late", last_name="Evening", email="late.2378@example.com")
        customer = customer_for_member(member)
        donor = self.create_test_donor(donor_email="late.donor.2378@example.com")
        frappe.db.set_value("Donor", donor.name, "customer", customer)
        donation = self.create_test_donation(donor=donor.name, amount=15.0, paid=0)
        processor = DonationPaymentProcessor()
        seen = {}

        def record(**kwargs):
            seen.update(kwargs)
            return "BT-RECORDED"

        # Only the collaborator that WRITES the Bank Transaction is replaced: the date
        # under test is computed by the processor before it is handed over.
        with patch.object(
            processor.bank_tx_creator,
            "get_mollie_bank_account_config",
            return_value={"bank_account": "x", "company": "y"},
        ), patch.object(processor.bank_tx_creator, "create", side_effect=record):
            with system_timezone(ZONE):
                result = processor._create_bank_transaction_for_donation(
                    donation,
                    {"payment_id": "tr_2378", "amount": "15.00", "paid_at": LATE_EVENING_UTC},
                )
        self.assertEqual(result, "BT-RECORDED")
        self.assertEqual(seen["date"], LOCAL_DAY)


class TestDonationPaymentHistoryDate(EnhancedTestCase):
    def _open_donation(self):
        donor = self.create_test_donor(donor_email="hist.donor.2378@example.com")
        company = frappe.db.get_single_value("Verenigingen Settings", "company") or (
            frappe.defaults.get_global_default("company")
        )
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": company,
                "donor": donor.name,
                "amount": 10.0,
                "donation_date": frappe.utils.getdate(),
                "currency": "EUR",
                "paid": 0,
                "mode_of_payment": "Bank Transfer",
            }
        ).insert()
        return donation

    def test_webhook_api_history_row_is_the_local_day(self):
        donation = self._open_donation()
        mollie_data = {"payment_id": "tr_hist_2378", "paid_at": LATE_EVENING_UTC}
        with system_timezone(ZONE):
            self.assertTrue(update_donation_payment_history(donation, mollie_data, "PE-2378"))
        row = [p for p in frappe.get_doc("Donation", donation.name).payments if p.mollie_payment_id == "tr_hist_2378"]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].payment_date, LOCAL_DAY)

    def test_unified_service_history_row_is_the_local_day(self):
        svc = object.__new__(UnifiedWebhookWrapperService)
        svc.logger = MollieLogger("test_2378")
        rows = []
        donation = types.SimpleNamespace(
            name="DON-2378",
            payments=[],
            append=lambda table, row: rows.append(row),
            save=lambda: None,
        )
        with system_timezone(ZONE):
            ok = svc._update_donation_payment_history(
                donation, {"id": "tr_2378", "paid_at": LATE_EVENING_UTC, "amount": {"value": "10.00"}}, "PE-1"
            )
        self.assertTrue(ok)
        self.assertEqual(rows[0]["payment_date"], LOCAL_DAY)


class TestSettlementWindowAndGenericFilter(EnhancedTestCase):
    """The caller's from/to are LOCAL days; a settlement stamped in UTC is compared by its local day."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Same bootstrap as test_mollie_base_client_sweep: a real Mollie Settings single
        if not frappe.db.get_singles_dict("Mollie Settings"):
            make_test_records("Mollie Settings")

    def _settlements_client(self):
        client = SettlementsClient(use_backend_api=False)
        client.audit_trail = MagicMock()
        return client

    def test_settlement_window_uses_the_local_day_of_settled_at(self):
        client = self._settlements_client()
        inside = {"id": "stl_in", "settledAt": LATE_EVENING_UTC}  # UTC 3rd, local 4th
        before = {"id": "stl_before", "settledAt": "2026-03-03T10:00:00+00:00"}  # local 3rd
        after = {"id": "stl_after", "settledAt": "2026-03-04T23:30:00+00:00"}  # UTC 4th, local 5th
        with patch.object(client, "get", return_value=[inside, before, after]):
            with system_timezone(ZONE):
                got = client.get_settlements_by_date_range("2026-03-04", "2026-03-04")
        self.assertEqual([s["id"] for s in got], ["stl_in"])

    def test_filter_by_date_uses_the_local_day_of_string_items(self):
        client = MollieBaseClient(use_backend_api=False)
        items = [
            {"created_at": LATE_EVENING_UTC},  # local 4th: in
            {"created_at": "2026-03-03T10:00:00+00:00"},  # local 3rd: out
            {"created_at": "2026-03-04T23:30:00+00:00"},  # local 5th: out
        ]
        with system_timezone(ZONE):
            got = client._filter_by_date(items, from_date=datetime(2026, 3, 4), until_date=datetime(2026, 3, 4))
        self.assertEqual([i["created_at"] for i in got], [LATE_EVENING_UTC])

    def test_filter_by_date_uses_the_local_day_of_aware_datetimes(self):
        client = MollieBaseClient(use_backend_api=False)
        items = [
            {"created_at": datetime(2026, 3, 3, 23, 30, tzinfo=timezone.utc)},
            {"created_at": datetime(2026, 3, 4, 23, 30, tzinfo=timezone.utc)},
        ]
        with system_timezone(ZONE):
            got = client._filter_by_date(items, from_date=datetime(2026, 3, 4), until_date=datetime(2026, 3, 4))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["created_at"].day, 3)
