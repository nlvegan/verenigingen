"""
Tests for BulkPaymentChecker (Mollie bulk payment discovery + processing).

The Mollie SDK is the external boundary; it is replaced here by fakes so tests
never touch the live Mollie API. Everything below the SDK is exercised for real,
including the typed-payment conversion, date/duplicate filtering, idempotency
batch checks, orphan classification, circuit-breaker logic, and audit logging.

The checker is built with ``object.__new__`` and then has its two collaborators
(``mollie_client`` and ``dues_processor``) replaced with controllable fakes -
``BulkPaymentChecker.__init__`` would otherwise build a real MollieClient and
DuesPaymentProcessor that need site-specific Mollie/account configuration.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import (
    BulkPaymentChecker,
    BulkPaymentCheckerConfig,
)

# ---------------------------------------------------------------------------
# Fakes for the SDK boundary and the two checker collaborators.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API and cannot run in tests. DuesPaymentProcessor / BankTransaction
# creation reach ERPNext docs that aren't relevant to the discovery logic under
# test, so they are stubbed at the object boundary while the bulk checker's own
# filtering / aggregation / circuit-breaker logic runs unmodified.
# ---------------------------------------------------------------------------


def _sdk_payment(
    pid,
    status="paid",
    value="25.00",
    currency="EUR",
    created=None,
    paid=None,
    description="Membership dues",
    customer_id="cst_1",
    subscription_id=None,
):
    """A dict in the shape MolliePayment.from_mollie_api consumes."""
    if created is None or paid is None:
        _recent = (now_datetime() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        created = created or _recent
        paid = paid or _recent
    return {
        "id": pid,
        "amount": {"value": value, "currency": currency},
        "description": description,
        "status": status,
        "customerId": customer_id,
        "subscriptionId": subscription_id,
        "createdAt": created,
        "paidAt": paid,
        "metadata": {},
        "method": "directdebit",
    }


class _FakePaymentsList:
    """Stand-in for customer.payments.list() -> list of SDK payment dicts."""

    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=250):
        return self._payments


class _FakeCustomerObj:
    def __init__(self, payments):
        self.payments = _FakePaymentsList(payments)


class _FakeCustomers:
    def __init__(self, payments_by_customer, raise_for=None):
        self._payments_by_customer = payments_by_customer
        self._raise_for = raise_for or {}

    def get(self, customer_id):
        if customer_id in self._raise_for:
            raise self._raise_for[customer_id]
        return _FakeCustomerObj(self._payments_by_customer.get(customer_id, []))


class _FakeSDKClient:
    def __init__(self, payments_by_customer=None, raise_for=None):
        self.customers = _FakeCustomers(payments_by_customer or {}, raise_for)


class _FakeMollieClient:
    def __init__(self, sdk):
        self.sdk_client = sdk


class _FakeDuesProcessor:
    """Controllable identify_payment_type / find_member_for_payment."""

    def __init__(self, payment_type="dues", member_for_payment=None):
        self._payment_type = payment_type
        self._member = member_for_payment

    def identify_payment_type(self, payment):
        return self._payment_type

    def find_member_for_payment(self, payment):
        return self._member


class _NotProcessedCreator:
    """BankTransactionCreator stub: nothing is already processed."""

    def check_already_processed(self, reference_number, check_payment_entry=False):
        return {"already_processed": False, "payment_entry": None, "bank_transaction": None}


def _build_checker(sdk, payment_type="dues", member_for_payment=None):
    checker = object.__new__(BulkPaymentChecker)
    checker.mollie_client = _FakeMollieClient(sdk)
    checker.dues_processor = _FakeDuesProcessor(payment_type, member_for_payment)
    return checker


def _patch_bt_creator():
    """Route get_bank_transaction_creator() to a not-processed stub."""
    return patch(
        "verenigingen.verenigingen_payments.services.bank_transaction_creator.get_bank_transaction_creator",
        return_value=_NotProcessedCreator(),
    )


class TestBulkPaymentCheckerFilters(EnhancedTestCase):
    """Static filter / classification helpers (no Mollie I/O)."""

    def test_filter_payment_by_date_excludes_old_payment(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        old = SimpleNamespace(
            id="tr_old",
            paid_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(BulkPaymentChecker._filter_payment_by_date(old, from_date))

    def test_filter_payment_by_date_keeps_recent_payment(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        recent = SimpleNamespace(
            id="tr_new",
            paid_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(recent, from_date))

    def test_filter_payment_by_date_none_from_date_keeps_all(self):
        p = SimpleNamespace(id="tr_x", paid_at=None, created_at=None)
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(p, None))

    def test_filter_payment_by_date_no_date_excludes(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        p = SimpleNamespace(id="tr_nodate", paid_at=None, created_at=None)
        self.assertTrue(BulkPaymentChecker._filter_payment_by_date(p, from_date))

    def test_filter_payment_by_date_naive_datetime_is_treated_as_utc(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        naive_recent = SimpleNamespace(
            id="tr_naive",
            paid_at=datetime(2026, 6, 10),  # no tzinfo
            created_at=datetime(2026, 6, 10),
        )
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(naive_recent, from_date))

    def test_build_payment_info_processable_dues(self):
        payment = SimpleNamespace(
            id="tr_1",
            status="paid",
            description="dues",
            created_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            paid_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            subscription_id=None,
        )
        idempotency = {"already_processed": False, "payment_entry": None, "bank_transaction": None}
        info = BulkPaymentChecker._build_payment_info(
            payment, "dues", idempotency, "25.00", "EUR", None, None
        )
        self.assertTrue(info["processable"])
        self.assertEqual(info["processing_mode"], "bt_only")
        self.assertEqual(info["amount_display"], "EUR 25.00")

    def test_build_payment_info_with_matching_invoice_sets_reconcile_mode(self):
        payment = SimpleNamespace(
            id="tr_2",
            status="paid",
            description="dues",
            created_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            paid_at=None,
            subscription_id="sub_1",
        )
        idempotency = {"already_processed": False, "payment_entry": None, "bank_transaction": None}
        info = BulkPaymentChecker._build_payment_info(
            payment, "dues", idempotency, "25.00", "EUR", None, {"invoice_name": "ACC-INV-1"}
        )
        self.assertEqual(info["processing_mode"], "bt_pe_reconcile")
        self.assertEqual(info["paid_at"], None)

    def test_build_payment_info_currency_warning_not_processable(self):
        payment = SimpleNamespace(
            id="tr_3",
            status="paid",
            description="dues",
            created_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            paid_at=None,
            subscription_id=None,
        )
        idempotency = {"already_processed": False, "payment_entry": None, "bank_transaction": None}
        info = BulkPaymentChecker._build_payment_info(
            payment, "dues", idempotency, "25.00", "USD", "Non-EUR currency: USD.", None
        )
        self.assertFalse(info["processable"])

    def test_build_payment_info_already_processed_not_processable(self):
        payment = SimpleNamespace(
            id="tr_4",
            status="paid",
            description="dues",
            created_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            paid_at=None,
            subscription_id=None,
        )
        idempotency = {"already_processed": True, "payment_entry": "PE-1", "bank_transaction": "BT-1"}
        info = BulkPaymentChecker._build_payment_info(
            payment, "dues", idempotency, "25.00", "EUR", None, None
        )
        self.assertFalse(info["processable"])
        self.assertEqual(info["payment_entry"], "PE-1")
        self.assertIsNone(info["processing_mode"])

    def test_classify_orphaned_payment_with_customer_is_processable(self):
        payment = SimpleNamespace(
            status="paid",
            customer_id="cst_orphan",
            subscription_id=None,
            description="anon dues",
            paid_at="2026-06-10",
            created_at="2026-06-10",
        )
        info, processable = BulkPaymentChecker._classify_orphaned_payment(
            payment, "tr_orphan", "dues", "EUR", "10.00"
        )
        self.assertTrue(processable)
        self.assertEqual(info["processing_mode"], "bt_only_orphaned")
        self.assertEqual(info["customer_id"], "cst_orphan")

    def test_classify_orphaned_payment_anonymous(self):
        payment = SimpleNamespace(
            status="paid",
            customer_id=None,
            subscription_id=None,
            description="anon",
            paid_at="2026-06-10",
            created_at="2026-06-10",
        )
        info, processable = BulkPaymentChecker._classify_orphaned_payment(
            payment, "tr_anon", "unknown", "EUR", "10.00"
        )
        self.assertTrue(processable)
        self.assertEqual(info["processing_mode"], "bt_only_anonymous")

    def test_classify_orphaned_payment_non_eur_not_processable(self):
        payment = SimpleNamespace(
            status="paid",
            customer_id="cst_1",
            subscription_id=None,
            description="x",
            paid_at="2026-06-10",
            created_at="2026-06-10",
        )
        info, processable = BulkPaymentChecker._classify_orphaned_payment(
            payment, "tr_usd", "dues", "USD", "10.00"
        )
        self.assertFalse(processable)
        self.assertIsNone(info["processing_mode"])

    def test_extract_payment_ids_from_transactions_filters_by_date(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        to_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
        in_range = SimpleNamespace(
            id="tr_in",
            context={"paymentId": "tr_in"},
            created_at="2026-06-15T12:00:00+00:00",
            type="payment",
            amount={"value": "10.00"},
        )
        out_of_range = SimpleNamespace(
            id="tr_out",
            context={"paymentId": "tr_out"},
            created_at="2026-05-15T12:00:00+00:00",
            type="payment",
            amount={"value": "10.00"},
        )
        ids, tx_list = BulkPaymentChecker._extract_payment_ids_from_transactions(
            [in_range, out_of_range], from_date, to_date
        )
        self.assertEqual(ids, {"tr_in"})
        self.assertEqual(len(tx_list), 1)
        self.assertEqual(tx_list[0]["payment_id"], "tr_in")

    def test_extract_payment_ids_uses_tx_id_when_no_context_payment_id(self):
        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        to_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
        tx = SimpleNamespace(
            id="tr_fromid",
            context={},
            created_at="2026-06-15T12:00:00+00:00",
            type="payment",
            amount={"value": "10.00"},
        )
        ids, _ = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, {"tr_fromid"})


class TestBatchAlreadyProcessed(EnhancedTestCase):
    """_batch_check_already_processed is a real DB query against PE/BT tables."""

    def test_empty_list_returns_empty(self):
        self.assertEqual(BulkPaymentChecker._batch_check_already_processed([]), [])

    def test_unprocessed_ids_pass_through(self):
        # Random ids that cannot exist as references -> all unprocessed.
        ids = [f"tr_{frappe.generate_hash(length=12)}" for _ in range(3)]
        result = BulkPaymentChecker._batch_check_already_processed(ids)
        self.assertEqual(sorted(result), sorted(ids))


class TestCheckPaymentsForCustomer(EnhancedTestCase):
    """check_payments_for_customer end-to-end against a fake SDK + creator."""

    def test_returns_processable_dues_payment(self):
        sdk = _FakeSDKClient(payments_by_customer={"cst_1": [_sdk_payment("tr_a", value="25.00")]})
        checker = _build_checker(sdk)

        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_1", "MEM-1")

        self.assertIsNone(result["error"])
        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["new_payments"], 1)
        self.assertEqual(len(result["payments"]), 1)
        self.assertTrue(result["payments"][0]["processable"])

    def test_filters_duplicate_payment_ids(self):
        dup = _sdk_payment("tr_dup")
        sdk = _FakeSDKClient(payments_by_customer={"cst_1": [dup, dict(dup)]})
        checker = _build_checker(sdk)

        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_1", "MEM-1")

        self.assertEqual(result["total_found"], 2)
        self.assertEqual(result["filtered_by_duplicate"], 1)
        self.assertEqual(len(result["payments"]), 1)

    def test_filters_payment_outside_date_window(self):
        old = _sdk_payment("tr_old", created="2026-01-01T10:00:00+00:00", paid="2026-01-01T10:00:00+00:00")
        sdk = _FakeSDKClient(payments_by_customer={"cst_1": [old]})
        checker = _build_checker(sdk)

        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_1", "MEM-1", from_date=from_date)

        self.assertEqual(result["filtered_by_date"], 1)
        self.assertEqual(len(result["payments"]), 0)

    def test_non_eur_payment_gets_currency_warning(self):
        usd = _sdk_payment("tr_usd", currency="USD")
        sdk = _FakeSDKClient(payments_by_customer={"cst_1": [usd]})
        checker = _build_checker(sdk)

        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_1", "MEM-1")

        info = result["payments"][0]
        self.assertIsNotNone(info["currency_warning"])
        self.assertFalse(info["processable"])

    def test_sdk_error_recorded_on_result(self):
        sdk = _FakeSDKClient(raise_for={"cst_err": RuntimeError("boom")})
        checker = _build_checker(sdk)

        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_err", "MEM-1")

        self.assertIsNotNone(result["error"])
        self.assertIn("boom", result["error"])

    def test_donation_payment_is_not_processable_as_dues(self):
        sdk = _FakeSDKClient(payments_by_customer={"cst_1": [_sdk_payment("tr_don")]})
        checker = _build_checker(sdk, payment_type="donation")

        with _patch_bt_creator():
            result = checker.check_payments_for_customer("cst_1", "MEM-1")

        self.assertEqual(result["new_payments"], 0)
        self.assertFalse(result["payments"][0]["processable"])


class TestGetMembersWithMollieCustomers(EnhancedTestCase):
    """get_members_with_mollie_customers paginates against a real Member table."""

    def _make_member_with_customer(self, customer_id):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Bulk",
            last_name=f"Cust{token}",
            email=f"bulk-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", customer_id, update_modified=False)
        return member

    def test_lists_only_members_with_customer_ids(self):
        cid = f"cst_{frappe.generate_hash(length=8)}"
        member = self._make_member_with_customer(cid)
        checker = object.__new__(BulkPaymentChecker)

        data = checker.get_members_with_mollie_customers(limit=500)

        names = {m["name"] for m in data["members"]}
        self.assertIn(member.name, names)
        self.assertGreaterEqual(data["total_count"], 1)

    def test_pagination_has_more_flag(self):
        for _ in range(3):
            self._make_member_with_customer(f"cst_{frappe.generate_hash(length=8)}")
        checker = object.__new__(BulkPaymentChecker)

        data = checker.get_members_with_mollie_customers(limit=1)

        self.assertEqual(data["count"], 1)
        self.assertTrue(data["has_more"])


class TestCheckAllCustomersDiscovery(EnhancedTestCase):
    """_check_via_customers orchestration, circuit breaker, audit logging."""

    def test_rejects_excessive_days_back(self):
        checker = _build_checker(_FakeSDKClient())
        result = checker.check_all_customers_for_new_payments(
            days_back=BulkPaymentCheckerConfig.MAX_DAYS_BACK + 1
        )
        # frappe.throw is caught by the outer try -> recorded as result["error"].
        self.assertIn("error", result)
        self.assertTrue(result["error"])

    def test_invalid_retrieval_mode_throws(self):
        checker = _build_checker(_FakeSDKClient())
        with self.assertRaises(frappe.ValidationError):
            checker.check_all_customers_for_new_payments(retrieval_mode="nonsense")

    def test_discovery_aggregates_across_members(self):
        # Two members with one processable dues payment each.
        c1 = f"cst_{frappe.generate_hash(length=8)}"
        c2 = f"cst_{frappe.generate_hash(length=8)}"
        for first, cid in (("DiscA", c1), ("DiscB", c2)):
            token = frappe.generate_hash(length=8)
            m = self.create_test_member(
                first_name=first,
                last_name=f"X{token}",
                email=f"disc-{token}@example.com",
                birth_date="1990-01-01",
            )
            frappe.db.set_value("Member", m.name, "mollie_customer_id", cid, update_modified=False)

        sdk = _FakeSDKClient(
            payments_by_customer={
                c1: [_sdk_payment("tr_c1")],
                c2: [_sdk_payment("tr_c2")],
            }
        )
        checker = _build_checker(sdk)

        # Avoid the real 600ms rate-limit sleep between members.
        with (
            _patch_bt_creator(),
            patch("verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.time.sleep"),
        ):
            result = checker.check_all_customers_for_new_payments(days_back=30, max_members=500)

        self.assertGreaterEqual(result["members_checked"], 2)
        self.assertGreaterEqual(result["total_new_payments"], 2)
        self.assertEqual(result["retrieval_mode"], "customer")
        self.assertTrue(result["summary"])

    def test_circuit_breaker_trips_on_repeated_errors(self):
        # All-failing customers trip the circuit breaker early and stop the run
        # well before every member is checked. With a small member set the 10%
        # error-budget breaker fires first; either breaker satisfies the
        # contract (the run aborts rather than hammering a dead API).
        raise_for = {}
        n_members = BulkPaymentCheckerConfig.MAX_CONSECUTIVE_ERRORS + 5
        for _ in range(n_members):
            cid = f"cst_{frappe.generate_hash(length=8)}"
            raise_for[cid] = RuntimeError("api down")
            token = frappe.generate_hash(length=8)
            m = self.create_test_member(
                first_name="CB",
                last_name=f"X{token}",
                email=f"cb-{token}@example.com",
                birth_date="1990-01-01",
            )
            frappe.db.set_value("Member", m.name, "mollie_customer_id", cid, update_modified=False)

        sdk = _FakeSDKClient(raise_for=raise_for)
        checker = _build_checker(sdk)

        with (
            _patch_bt_creator(),
            patch("verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.time.sleep"),
        ):
            result = checker.check_all_customers_for_new_payments(days_back=30, max_members=500)

        self.assertTrue(result["circuit_breaker_triggered"])
        self.assertIn("STOPPED", result["summary"])
        # The breaker stopped the run before checking every member.
        self.assertLess(result["members_checked"], result["total_members"])

    def test_consecutive_error_breaker_when_budget_is_generous(self):
        # With >= 50 members the 10% budget is >= 5, so consecutive failures
        # reach MAX_CONSECUTIVE_ERRORS before the budget threshold is crossed.
        # We patch check_payments_for_customer to fail the first N then succeed,
        # isolating the consecutive-error breaker.
        n_members = 60
        for _ in range(n_members):
            cid = f"cst_{frappe.generate_hash(length=8)}"
            token = frappe.generate_hash(length=8)
            m = self.create_test_member(
                first_name="CBgen",
                last_name=f"X{token}",
                email=f"cbgen-{token}@example.com",
                birth_date="1990-01-01",
            )
            frappe.db.set_value("Member", m.name, "mollie_customer_id", cid, update_modified=False)

        checker = _build_checker(_FakeSDKClient())

        def _always_error(customer_id, member_name, from_date=None, limit=250):
            return {
                "customer_id": customer_id,
                "member": member_name,
                "payments": [],
                "total_found": 0,
                "new_payments": 0,
                "error": "api down",
                "filtered_by_date": 0,
                "filtered_by_duplicate": 0,
            }

        checker.check_payments_for_customer = _always_error

        with patch("verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.time.sleep"):
            result = checker.check_all_customers_for_new_payments(days_back=30, max_members=500)

        self.assertTrue(result["circuit_breaker_triggered"])
        # Consecutive breaker fires at exactly MAX_CONSECUTIVE_ERRORS because
        # the budget (>=6) has not been exceeded yet.
        self.assertEqual(result["errors"], BulkPaymentCheckerConfig.MAX_CONSECUTIVE_ERRORS)


class TestProcessDiscoveredPayments(EnhancedTestCase):
    """Stage 2 processing (dry-run + real path via stubbed dues processor)."""

    def test_empty_payment_ids_raises(self):
        checker = _build_checker(_FakeSDKClient())
        with self.assertRaises(ValueError):
            checker.process_discovered_payments([])

    def test_dry_run_does_not_process(self):
        sdk = _FakeSDKClient()
        # dry_run path calls sdk_client.payments.get(payment_id)
        sdk.payments = SimpleNamespace(
            get=lambda pid: SimpleNamespace(id=pid, status="paid", amount={"value": "25.00"})
        )
        checker = _build_checker(sdk)
        checker.mollie_client.sdk_client.payments = sdk.payments

        result = checker.process_discovered_payments(["tr_dry"], dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["results"][0]["status"], "dry_run")

    def test_real_processing_counts_success(self):
        checker = _build_checker(_FakeSDKClient())

        # Stub the dues processor's process_dues_payment to return success.
        checker.dues_processor.process_dues_payment = lambda pid: {"status": "success", "payment_id": pid}

        result = checker.process_discovered_payments(["tr_x"], dry_run=False)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["errors"], 0)

    def test_real_processing_counts_error(self):
        checker = _build_checker(_FakeSDKClient())

        def _boom(pid):
            raise RuntimeError("processing failed")

        checker.dues_processor.process_dues_payment = _boom

        result = checker.process_discovered_payments(["tr_err"], dry_run=False)

        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")
