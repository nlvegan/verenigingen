"""
Integration coverage for the DATA-PROCESSING / BULK surface of
``verenigingen/services/mollie_debug_service.py`` (class ``MollieDebugService``).

The plain debug/read methods (debug_customer, debug_payment, list_*, the
dry-run/live happy path of sync_membership_end_dates_from_mollie) are already
covered by
``verenigingen/verenigingen_payments/mollie/tests/test_mollie_debug_service.py``.
This module targets the heavier bulk/aggregation orchestration that historically
hides counting/status bugs:

  - ``retrieve_customer_payments_for_processing`` - limit sanitisation,
    per-payment iteration, processed/unprocessed counting, the "customer not
    found in this mode" early-return, and the ``processable`` decision logic.
  - ``batch_process_dues_payments`` - per-payment processed/skipped/error
    bucketing driven through the REAL DuesPaymentProcessor + BulkPaymentChecker.
  - ``sync_membership_end_dates_from_mollie`` - the deeper branches of
    ``_sync_single_member_end_date`` / ``_fetch_mollie_cancellation_date``
    (410-Gone skip, attached Sales Invoices, Membership.cancellation_date
    write) against REAL Member / Sales Invoice / Membership records.
  - ``bulk_retrieve_all_member_payments`` - global-endpoint pagination, the
    dedup / date / member / status filters, early-termination on consecutive
    old payments, and per-member aggregation, all via the REAL
    MemberPaymentMatcher + idempotency checker.
  - ``bulk_process_member_payments`` + ``_process_single_bulk_payment`` /
    ``_resolve_payment_mode`` / ``_route_to_orchestrator`` /
    ``_submit_processed_documents`` - mode routing, counter aggregation, the
    auto-batch-splitting recursion, and the docstatus=1 submit branch against a
    REAL draft Bank Transaction.
  - ``process_payment_batch_background`` - the worker-side job handler delegates
    to bulk_process_member_payments and attaches batch metadata (and degrades
    gracefully on failure).

Test philosophy (this repo runs an aggressive test-quality-enforcer):
ONLY true externals are faked - the Mollie HTTP SDK boundary (proven seam:
patch ``MollieSettings.get_mollie_client`` + ``MollieClient._get_api_key``) and
the heavyweight MolliePaymentOrchestrator (the accounting engine that creates
GL-posting Bank Transactions / Payment Entries; it is the external-of-this-unit
collaborator for the bulk_process path). The service's own routing, counting,
filtering, pagination and submission logic runs for real, and so do the
MemberPaymentMatcher, PaymentClassifier, DuesPaymentProcessor, BulkPaymentChecker
and the BankTransactionCreator idempotency check - all against REAL Member /
Donor / Sales Invoice / Membership / Bank Transaction DocTypes.
"""

import time
from datetime import date, datetime
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company

# ---------------------------------------------------------------------------
# Patch seam (proven; identical to test_mollie_debug_service.py).
# ---------------------------------------------------------------------------
_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"
_GET_ORCHESTRATOR = (
    "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator.get_payment_orchestrator"
)


# ---------------------------------------------------------------------------
# Fake Mollie SDK.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API; it cannot run in tests. The fake mimics only the small slice of
# the SDK surface the bulk methods touch (customers.get -> .payments.list /
# .subscriptions.list, top-level payments.list with `from`/`limit` pagination)
# and returns Mollie-shaped objects.
# ---------------------------------------------------------------------------


class _Sub:
    def __init__(self, sub_id="sub_FAKE0001", status="active", canceled_at=None):
        self.id = sub_id
        self.status = status
        self.canceled_at = canceled_at


class _Payment:
    """Mollie-shaped payment object."""

    def __init__(
        self,
        payment_id="tr_FAKE0001",
        status="paid",
        amount=None,
        customer_id="cst_FAKE0001",
        description="Membership dues",
        created_at="2099-01-01T00:00:00+00:00",
        subscription_id=None,
    ):
        self.id = payment_id
        self.status = status
        self.amount = amount if amount is not None else {"value": "25.00", "currency": "EUR"}
        self.description = description
        self.method = "directdebit"
        self.created_at = created_at
        self.paid_at = created_at
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.details = None


class _SubCollection:
    def __init__(self, subs):
        self._subs = subs

    def list(self, limit=None):
        return list(self._subs)


class _PaymentCollection:
    def __init__(self, recorder, payments):
        self._recorder = recorder
        self._payments = payments

    def list(self, limit=None):
        self._recorder.customer_payment_list_limits.append(limit)
        return list(self._payments)


class _FakeCustomer:
    def __init__(self, recorder, customer_id, subs, payments):
        self.id = customer_id
        self.name = "Test Customer"
        self.email = "customer@example.com"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.mode = "test"
        self.subscriptions = _SubCollection(subs)
        self.payments = _PaymentCollection(recorder, payments)


class _FakeCustomers:
    def __init__(self, recorder, subs, customer_payments, not_found_ids, gone_ids):
        self._recorder = recorder
        self._subs = subs
        self._customer_payments = customer_payments
        self._not_found_ids = not_found_ids or set()
        self._gone_ids = gone_ids or set()

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        if customer_id in self._gone_ids:
            raise RuntimeError("Mandate is no longer available (410 Gone)")
        if customer_id in self._not_found_ids:
            raise RuntimeError(f"No customer exists with token {customer_id} (404)")
        return _FakeCustomer(self._recorder, customer_id, self._subs, self._customer_payments)


class _FakeGlobalPayments:
    """Top-level ``client.payments.list(**params)`` with `from`/`limit` paging.

    ``pages`` is a list of payment-lists; each ``list()`` call (driven by the
    service's ``from`` cursor) returns the next page so pagination + early
    termination logic runs for real.
    """

    def __init__(self, recorder, pages):
        self._recorder = recorder
        self._pages = pages
        self._call_index = 0

    def list(self, **params):
        self._recorder.global_list_params.append(dict(params))
        if self._call_index < len(self._pages):
            page = self._pages[self._call_index]
        else:
            page = []
        self._call_index += 1
        return list(page)

    def get(self, payment_id):
        for page in self._pages:
            for p in page:
                if p.id == payment_id:
                    return p
        return _Payment(payment_id=payment_id)


class _Recorder:
    def __init__(self):
        self.customers_fetched = []
        self.customer_payment_list_limits = []
        self.global_list_params = []


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(
        self,
        subs=None,
        customer_payments=None,
        global_payment_pages=None,
        customer_not_found_ids=None,
        customer_gone_ids=None,
    ):
        self.recorder = _Recorder()
        subs = subs if subs is not None else [_Sub()]
        customer_payments = customer_payments if customer_payments is not None else [_Payment()]
        global_payment_pages = global_payment_pages if global_payment_pages is not None else [[]]
        self.customers = _FakeCustomers(
            self.recorder, subs, customer_payments, customer_not_found_ids, customer_gone_ids
        )
        self.payments = _FakeGlobalPayments(self.recorder, global_payment_pages)


# ---------------------------------------------------------------------------
# Fake MolliePaymentOrchestrator (the accounting engine boundary for the
# bulk_process_member_payments path).
#
# Mock justified: the real orchestrator fetches the live Mollie payment and
# creates GL-posting Bank Transaction / Payment Entry documents (full ERPNext
# accounting wiring). The service-under-test's responsibility is to ROUTE each
# payment to the correct orchestrator method, AGGREGATE the per-payment
# status counters, and SUBMIT resulting draft documents - none of which is the
# orchestrator's job. So we replace the orchestrator with a recorder that
# returns real PaymentProcessingResult objects; everything the service does with
# those results runs for real.
# ---------------------------------------------------------------------------


def _make_result(payment_id, status="success", bank_transaction=None, payment_entry=None, member=None):
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        PaymentProcessingResult,
    )

    return PaymentProcessingResult(
        payment_id=payment_id,
        status=status,
        bank_transaction=bank_transaction,
        payment_entry=payment_entry,
        member=member,
        sales_invoice=None,
        actions_taken=["fake"],
        reconciled=False,
    )


class _FakeOrchestrator:
    def __init__(self, results_by_id=None, default_status="success"):
        self._results_by_id = results_by_id or {}
        self._default_status = default_status
        self.process_payment_calls = []
        self.process_bt_only_calls = []
        self.process_orphaned_calls = []

    def _result_for(self, payment_id):
        if payment_id in self._results_by_id:
            return self._results_by_id[payment_id]
        return _make_result(payment_id, status=self._default_status)

    def process_payment(self, payment_id=None, invoice_name=None, create_missing_invoice=False):
        self.process_payment_calls.append(
            {"payment_id": payment_id, "invoice_name": invoice_name, "create_missing": create_missing_invoice}
        )
        return self._result_for(payment_id)

    def process_bt_only_payment(self, payment_id=None):
        self.process_bt_only_calls.append(payment_id)
        return self._result_for(payment_id)

    def process_orphaned_payment(self, payment_id=None, allow_anonymous=False):
        self.process_orphaned_calls.append({"payment_id": payment_id, "allow_anonymous": allow_anonymous})
        return self._result_for(payment_id)


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


class _MultiPatch:
    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _patch_sdk(sdk):
    return _MultiPatch(
        patch(_GET_MOLLIE_CLIENT, return_value=sdk),
        patch(_GET_API_KEY, return_value="test_fake"),
    )


def _patch_sdk_and_orchestrator(sdk, orchestrator):
    return _MultiPatch(
        patch(_GET_MOLLIE_CLIENT, return_value=sdk),
        patch(_GET_API_KEY, return_value="test_fake"),
        patch(_GET_ORCHESTRATOR, return_value=orchestrator),
    )


def _make_service():
    from verenigingen.services.mollie_debug_service import MollieDebugService

    return MollieDebugService()


class _BulkServiceTest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _unique_pid(self):
        return f"tr_{frappe.generate_hash(length=20)}"

    def _unique_cid(self):
        return f"cst_{frappe.generate_hash(length=16)}"


# ===========================================================================
# retrieve_customer_payments_for_processing
# ===========================================================================
class TestRetrieveCustomerPaymentsForProcessing(_BulkServiceTest):
    def test_empty_customer_id_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.retrieve_customer_payments_for_processing("")

    def test_invalid_limit_clamped_to_250(self):
        # 99999 is out of [1,250] -> coerced to 250.
        with _patch_sdk(FakeSDKClient(customer_payments=[])):
            service = _make_service()
            result = service.retrieve_customer_payments_for_processing("cst_LIMIT", limit=99999)
        self.assertEqual(result["limit"], 250)

        with _patch_sdk(FakeSDKClient(customer_payments=[])):
            service = _make_service()
            result = service.retrieve_customer_payments_for_processing("cst_LIMIT2", limit="abc")
        self.assertEqual(result["limit"], 250)

    def test_customer_not_found_returns_mode_aware_error(self):
        cid = self._unique_cid()
        sdk = FakeSDKClient(customer_not_found_ids={cid})
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.retrieve_customer_payments_for_processing(cid)
        self.assertIsNotNone(result["error"])
        self.assertIn("not found", result["error"])
        # No payments iterated when customer lookup fails.
        self.assertEqual(result["payments"], [])
        self.assertEqual(result["total_found"], 0)

    def test_paid_dues_payment_is_processable_and_counted_unprocessed(self):
        # A member with this customer id makes the payment classify as "dues"
        # and resolve a member -> processable=True, unprocessed_count incremented.
        cid = self._unique_cid()
        member = self.create_test_member(mollie_customer_id=cid)

        pid = self._unique_pid()
        payment = _Payment(payment_id=pid, status="paid", customer_id=cid)
        sdk = FakeSDKClient(customer_payments=[payment])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.retrieve_customer_payments_for_processing(cid)

        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["unprocessed_count"], 1)
        self.assertEqual(result["processed_count"], 0)
        info = result["payments"][0]
        self.assertEqual(info["id"], pid)
        self.assertEqual(info["payment_type"], "dues")
        self.assertEqual(info["member"], member.name)
        self.assertTrue(info["processable"])
        self.assertFalse(info["already_processed"])

    def test_non_paid_payment_is_not_processable(self):
        cid = self._unique_cid()
        self.create_test_member(mollie_customer_id=cid)

        pid = self._unique_pid()
        payment = _Payment(payment_id=pid, status="open", customer_id=cid)
        sdk = FakeSDKClient(customer_payments=[payment])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.retrieve_customer_payments_for_processing(cid)

        info = result["payments"][0]
        # dues + member resolved, but status != paid -> not processable.
        self.assertEqual(info["payment_type"], "dues")
        self.assertFalse(info["processable"])
        # Not processed -> counted unprocessed.
        self.assertEqual(result["unprocessed_count"], 1)


# ===========================================================================
# batch_process_dues_payments
# ===========================================================================
class TestBatchProcessDuesPayments(_BulkServiceTest):
    def test_empty_payment_ids_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.batch_process_dues_payments([])

    def test_paid_dues_payment_processed_and_skipped_bucketed(self):
        # Two payments for a real member: one paid (-> processed via DuesPayment
        # processor BT/PE creation path) and one non-paid (-> skipped). We assert
        # the aggregate bucketing, which is the service's responsibility, while
        # the REAL DuesPaymentProcessor runs underneath.
        cid = self._unique_cid()
        member = self.create_test_member(mollie_customer_id=cid)
        if not member.customer:
            customer = self.create_test_customer()
            member.db_set("customer", customer.name)

        paid_pid = self._unique_pid()
        open_pid = self._unique_pid()
        paid = _Payment(payment_id=paid_pid, status="paid", customer_id=cid)
        opened = _Payment(payment_id=open_pid, status="open", customer_id=cid)
        sdk = FakeSDKClient(customer_payments=[paid, opened])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.batch_process_dues_payments([paid_pid, open_pid], customer_id=cid)

        self.assertEqual(result["total_requested"], 2)
        # Each payment produced exactly one result entry.
        self.assertEqual(len(result["results"]), 2)
        # Counters partition all results: processed+skipped+errors == total.
        self.assertEqual(
            result["processed"] + result["skipped"] + result["errors"], result["total_requested"]
        )
        # The non-paid payment must be skipped (DuesPaymentProcessor returns
        # status 'skipped' for status != 'paid').
        open_result = next(r for r in result["results"] if r.get("payment_id") == open_pid)
        self.assertEqual(open_result["status"], "skipped")
        self.assertGreaterEqual(result["skipped"], 1)


# ===========================================================================
# sync_membership_end_dates_from_mollie - deeper _sync_single_member_end_date
# branches (410 skip, Sales Invoice attach, Membership.cancellation_date write)
# ===========================================================================
class TestSyncMembershipEndDatesDeep(_BulkServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    def test_410_gone_customer_is_skipped_without_crashing(self):
        cid = self._unique_cid()
        member = self.create_test_member(status="Quit", mollie_customer_id=cid)
        sdk = FakeSDKClient(customer_gone_ids={cid})

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.sync_membership_end_dates_from_mollie(dry_run=False)

        self.assertGreaterEqual(result["total_checked"], 1)
        # No write for a deleted-in-Mollie customer.
        member.reload()
        self.assertFalse(member.member_end_date)
        mr = next(r for r in result["members"] if r["member"] == member.name)
        self.assertTrue(mr.get("skipped"))
        self.assertIn("410", mr["error"])

    def test_live_run_writes_membership_cancellation_date_and_attaches_invoices(self):
        cancel_dt = datetime(2025, 8, 10, 12, 0, 0)
        cancel_date = date(2025, 8, 10)
        cid = self._unique_cid()
        member = self.create_test_member(status="Banned", mollie_customer_id=cid)

        # A submitted Sales Invoice tied to the member -> must be attached.
        invoice = self._make_submitted_sales_invoice(member)

        # A submitted Membership -> its cancellation_date must be written.
        membership = self._make_submitted_membership(member)

        sub = _Sub(sub_id="sub_CANC", status="canceled", canceled_at=cancel_dt)
        sdk = FakeSDKClient(subs=[sub])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.sync_membership_end_dates_from_mollie(dry_run=False)

        member.reload()
        self.assertEqual(str(member.member_end_date), str(cancel_date))

        mr = next(r for r in result["members"] if r["member"] == member.name)
        self.assertEqual(mr["canceled_at"], str(cancel_date))
        # Sales invoice attached.
        self.assertGreaterEqual(mr["invoice_count"], 1)
        attached = [i["name"] for i in mr["sales_invoices"]]
        self.assertIn(invoice.name, attached)
        # Membership cancellation_date written.
        self.assertEqual(mr["membership"], membership.name)
        membership.reload()
        self.assertEqual(str(membership.cancellation_date), str(cancel_date))

    def test_member_without_membership_records_note(self):
        cancel_dt = datetime(2025, 9, 1, 0, 0, 0)
        cid = self._unique_cid()
        member = self.create_test_member(status="Suspended", mollie_customer_id=cid)
        sub = _Sub(sub_id="sub_NOMEM", status="canceled", canceled_at=cancel_dt)
        sdk = FakeSDKClient(subs=[sub])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.sync_membership_end_dates_from_mollie(dry_run=False)

        member.reload()
        self.assertEqual(str(member.member_end_date), "2025-09-01")
        mr = next(r for r in result["members"] if r["member"] == member.name)
        self.assertIn("membership_note", mr)

    # --- fixtures ---------------------------------------------------------
    def _make_submitted_sales_invoice(self, member):
        customer = member.customer
        if not customer:
            customer = self.create_test_customer().name
            member.db_set("customer", customer)
        # The SEPA factory handles EUR company / cost-center / item wiring and
        # links the Sales Invoice.member custom field that the service queries.
        si = self.sepa.create_test_sales_invoice(
            customer=customer,
            member=member.name,
            company=self._company,
            grand_total=10.0,
            posting_date=today(),
            due_date=today(),
            submit=True,
        )
        self.track_doc("Sales Invoice", si.name)
        return si

    def _make_submitted_membership(self, member):
        membership = self.create_test_membership(member_name=member.name)
        # create_test_membership may return a draft; ensure submitted so the
        # service's docstatus=1 membership query finds it.
        membership.reload()
        if membership.docstatus == 0:
            membership.submit()
        return membership


# ===========================================================================
# bulk_retrieve_all_member_payments - pagination + filters + aggregation
# ===========================================================================
class TestBulkRetrieveAllMemberPayments(_BulkServiceTest):
    def test_no_members_returns_zero_without_api_calls(self):
        # No members with mollie ids created in this test -> matcher returns
        # the (possibly non-empty from sibling data) set, but with an empty
        # payments page nothing matches.
        sdk = FakeSDKClient(global_payment_pages=[[]])
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30)
        self.assertEqual(result["total_payments"], 0)
        self.assertEqual(result["members"], [])
        self.assertIsNone(result["error"])

    def test_recent_paid_payment_matched_and_aggregated_per_member(self):
        cid = self._unique_cid()
        member = self.create_test_member(mollie_customer_id=cid)

        recent = today() + "T00:00:00+00:00"
        pid = self._unique_pid()
        payment = _Payment(payment_id=pid, status="paid", customer_id=cid, created_at=recent)
        sdk = FakeSDKClient(global_payment_pages=[[payment]])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30)

        self.assertEqual(result["total_payments_found"], 1)
        self.assertEqual(result["total_payments"], 1)
        self.assertEqual(result["unprocessed_payments"], 1)
        self.assertEqual(result["api_calls_made"], 1)
        member_block = next(m for m in result["members"] if m["member"] == member.name)
        self.assertEqual(member_block["payment_count"], 1)
        self.assertEqual(member_block["unprocessed_count"], 1)
        self.assertEqual(member_block["customer_id"], cid)
        # No internal bookkeeping key leaks into the result.
        self.assertNotIn("_consecutive_old", result)

    def test_duplicate_payment_id_is_filtered(self):
        cid = self._unique_cid()
        self.create_test_member(mollie_customer_id=cid)

        recent = today() + "T00:00:00+00:00"
        pid = self._unique_pid()
        dup1 = _Payment(payment_id=pid, status="paid", customer_id=cid, created_at=recent)
        dup2 = _Payment(payment_id=pid, status="paid", customer_id=cid, created_at=recent)
        sdk = FakeSDKClient(global_payment_pages=[[dup1, dup2]])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30)

        self.assertEqual(result["total_payments_found"], 2)
        self.assertEqual(result["total_filtered_by_duplicate"], 1)
        # Only one survives.
        self.assertEqual(result["total_payments"], 1)

    def test_payment_without_member_is_filtered_by_member(self):
        # Unknown customer id, generic description -> matcher returns None.
        recent = today() + "T00:00:00+00:00"
        pid = self._unique_pid()
        orphan = _Payment(
            payment_id=pid,
            status="paid",
            customer_id="cst_NOTAMEMBER_XYZ",
            description="random",
            created_at=recent,
        )
        sdk = FakeSDKClient(global_payment_pages=[[orphan]])
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30)
        self.assertEqual(result["total_filtered_by_member"], 1)
        self.assertEqual(result["total_payments"], 0)

    def test_old_payment_outside_window_filtered_by_date(self):
        cid = self._unique_cid()
        self.create_test_member(mollie_customer_id=cid)

        old = add_days(today(), -400) + "T00:00:00+00:00"
        pid = self._unique_pid()
        old_payment = _Payment(payment_id=pid, status="paid", customer_id=cid, created_at=old)
        sdk = FakeSDKClient(global_payment_pages=[[old_payment]])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30)

        self.assertEqual(result["total_filtered_by_date"], 1)
        self.assertEqual(result["total_payments"], 0)

    def test_status_filter_excludes_non_matching_status(self):
        cid = self._unique_cid()
        self.create_test_member(mollie_customer_id=cid)

        recent = today() + "T00:00:00+00:00"
        failed = _Payment(payment_id=self._unique_pid(), status="failed", customer_id=cid, created_at=recent)
        sdk = FakeSDKClient(global_payment_pages=[[failed]])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30, payment_status_filter="paid")
        # Matched a member and within date, but filtered out by status.
        self.assertEqual(result["total_payments"], 0)

    def test_early_termination_on_consecutive_old_payments(self):
        cid = self._unique_cid()
        self.create_test_member(mollie_customer_id=cid)

        old = add_days(today(), -500) + "T00:00:00+00:00"
        # 55 consecutive old payments (> the 50 threshold) -> early termination.
        old_payments = [
            _Payment(payment_id=self._unique_pid(), status="paid", customer_id=cid, created_at=old)
            for _ in range(55)
        ]
        # A second page that must NOT be fetched once we terminate early.
        unreached = [_Payment(payment_id=self._unique_pid(), customer_id=cid, created_at=old)]
        sdk = FakeSDKClient(global_payment_pages=[old_payments, unreached])

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.bulk_retrieve_all_member_payments(days_back=30, max_payments=5000)

        self.assertTrue(result["early_termination"])
        self.assertGreaterEqual(result["total_filtered_by_date"], 50)
        # Only the first page was fetched.
        self.assertEqual(result["api_calls_made"], 1)


# ===========================================================================
# _resolve_payment_mode / _route_to_orchestrator - pure routing logic
# ===========================================================================
class TestPaymentModeRouting(_BulkServiceTest):
    def test_resolve_payment_mode_dict_with_invoice_dict(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        modes = {"tr_X": {"mode": "bt_pe_reconcile", "matching_invoice": {"invoice_name": "SINV-1"}}}
        mode, inv = MollieDebugService._resolve_payment_mode(modes, "tr_X")
        self.assertEqual(mode, "bt_pe_reconcile")
        self.assertEqual(inv, "SINV-1")

    def test_resolve_payment_mode_invoice_as_string(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        modes = {"tr_Y": {"mode": "bt_only", "matching_invoice": "SINV-2"}}
        mode, inv = MollieDebugService._resolve_payment_mode(modes, "tr_Y")
        self.assertEqual(mode, "bt_only")
        self.assertEqual(inv, "SINV-2")

    def test_resolve_payment_mode_missing_id_defaults_none(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        mode, inv = MollieDebugService._resolve_payment_mode({}, "tr_absent")
        self.assertIsNone(mode)
        self.assertIsNone(inv)

    def test_route_orphaned_calls_process_orphaned_with_anonymous(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        orch = _FakeOrchestrator()
        MollieDebugService._route_to_orchestrator(orch, "tr_O", "bt_only_orphaned", None)
        self.assertEqual(orch.process_orphaned_calls, [{"payment_id": "tr_O", "allow_anonymous": True}])

    def test_route_bt_only_calls_process_bt_only(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        orch = _FakeOrchestrator()
        MollieDebugService._route_to_orchestrator(orch, "tr_B", "bt_only", None)
        self.assertEqual(orch.process_bt_only_calls, ["tr_B"])

    def test_route_default_calls_process_payment_with_invoice(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        orch = _FakeOrchestrator()
        MollieDebugService._route_to_orchestrator(orch, "tr_D", "bt_pe_reconcile", "SINV-9")
        self.assertEqual(len(orch.process_payment_calls), 1)
        call = orch.process_payment_calls[0]
        self.assertEqual(call["payment_id"], "tr_D")
        self.assertEqual(call["invoice_name"], "SINV-9")
        self.assertFalse(call["create_missing"])


# ===========================================================================
# bulk_process_member_payments + _process_single_bulk_payment +
# _submit_processed_documents (orchestrator faked)
# ===========================================================================
class TestBulkProcessMemberPayments(_BulkServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Resolved once per class rather than once per test body: get_eur_bank_account
        # commits (sepa_test_company.py:361, and conditionally :409), and calling it
        # from a test body instead of setUpClass prematurely commits that test's other
        # in-flight, not-yet-tracked fixtures (the #581 review's TEST-LEAK finding).
        cls._eur_bank_account_name = get_eur_bank_account(get_eur_test_company())

    def test_counters_partition_by_status(self):
        pid_ok = self._unique_pid()
        pid_skip = self._unique_pid()
        pid_err = self._unique_pid()
        results = {
            pid_ok: _make_result(pid_ok, status="success"),
            pid_skip: _make_result(pid_skip, status="skipped"),
            pid_err: _make_result(pid_err, status="error"),
        }
        orch = _FakeOrchestrator(results_by_id=results)
        sdk = FakeSDKClient()

        with _patch_sdk_and_orchestrator(sdk, orch):
            service = _make_service()
            result = service.bulk_process_member_payments([pid_ok, pid_skip, pid_err], docstatus=0)

        self.assertEqual(result["total_requested"], 3)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["batches_processed"], 1)
        self.assertEqual(result["total_batches"], 1)
        self.assertEqual(len(result["results"]), 3)

    def test_already_processed_counts_as_skipped(self):
        pid = self._unique_pid()
        orch = _FakeOrchestrator(results_by_id={pid: _make_result(pid, status="already_processed")})
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            service = _make_service()
            result = service.bulk_process_member_payments([pid], docstatus=0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["processed"], 0)

    def test_payment_mode_routes_to_bt_only(self):
        pid = self._unique_pid()
        orch = _FakeOrchestrator(results_by_id={pid: _make_result(pid, status="success")})
        modes = {pid: {"mode": "bt_only"}}
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            service = _make_service()
            service.bulk_process_member_payments([pid], docstatus=0, payment_modes=modes)
        # Routed through the bt_only orchestrator method (not process_payment).
        self.assertEqual(orch.process_bt_only_calls, [pid])
        self.assertEqual(orch.process_payment_calls, [])

    def test_docstatus_1_submits_real_draft_bank_transaction(self):
        # docstatus=1 + a success result carrying a REAL draft Bank Transaction
        # -> _submit_processed_documents submits it for real.
        bank_account = self._ensure_eur_bank_account()
        bt = self._make_draft_bank_transaction(bank_account)
        self.assertEqual(bt.docstatus, 0)

        pid = self._unique_pid()
        orch = _FakeOrchestrator(
            results_by_id={pid: _make_result(pid, status="success", bank_transaction=bt.name)}
        )
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            service = _make_service()
            result = service.bulk_process_member_payments([pid], docstatus=1)

        self.assertEqual(result["processed"], 1)
        payment_result = result["results"][0]
        self.assertTrue(payment_result.get("bank_transaction_submitted"))
        # The REAL Bank Transaction is now submitted.
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "docstatus"), 1)

    def test_docstatus_0_does_not_submit(self):
        bank_account = self._ensure_eur_bank_account()
        bt = self._make_draft_bank_transaction(bank_account)

        pid = self._unique_pid()
        orch = _FakeOrchestrator(
            results_by_id={pid: _make_result(pid, status="success", bank_transaction=bt.name)}
        )
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            service = _make_service()
            result = service.bulk_process_member_payments([pid], docstatus=0)

        payment_result = result["results"][0]
        self.assertNotIn("bank_transaction_submitted", payment_result)
        # Still a draft.
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "docstatus"), 0)

    def test_auto_batch_splitting_for_large_request(self):
        # 251 ids > SAFE_BATCH_SIZE (250) -> split into 2 batches. Patch
        # time.sleep so the inter-batch delay doesn't slow the test.
        ids = [self._unique_pid() for _ in range(251)]
        orch = _FakeOrchestrator(default_status="success")
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            with patch.object(time, "sleep", return_value=None):
                service = _make_service()
                result = service.bulk_process_member_payments(ids, docstatus=0)

        self.assertEqual(result["total_requested"], 251)
        self.assertEqual(result["total_batches"], 2)
        self.assertEqual(result["batches_processed"], 2)
        self.assertEqual(result["processed"], 251)
        self.assertEqual(len(result["results"]), 251)
        self.assertIn("Completed 2 batches", result["message"])

    # --- fixtures ---------------------------------------------------------
    def _ensure_eur_bank_account(self):
        """The EUR test company's owned Bank Account, resolved once in setUpClass.

        The previous version searched progressively wider filters ending in `{}`
        -- any Bank Account on the site at all, by recency -- which could return a
        non-EUR, cross-company row instead of failing loudly (#583).
        `get_eur_bank_account` owns the account by name rather than borrowing.
        """
        return self._eur_bank_account_name

    def _make_draft_bank_transaction(self, bank_account):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = today()
        bt.description = "Mollie bulk test"
        bt.deposit = 10.0
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = self._unique_pid()
        if bank_account:
            bt.bank_account = bank_account
        bt.insert()
        self.track_doc("Bank Transaction", bt.name)
        return bt


# ===========================================================================
# process_payment_batch_background - worker job handler
# ===========================================================================
class TestProcessPaymentBatchBackground(_BulkServiceTest):
    def test_delegates_and_attaches_batch_metadata(self):
        pid = self._unique_pid()
        orch = _FakeOrchestrator(results_by_id={pid: _make_result(pid, status="success")})
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            service = _make_service()
            result = service.process_payment_batch_background(
                batch_num=3, payment_ids=[pid], docstatus=0, payment_modes={}, job_id="job-abc"
            )
        # Delegated to bulk_process_member_payments (counters present) and
        # decorated with batch metadata.
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["batch_num"], 3)
        self.assertEqual(result["job_id"], "job-abc")

    def test_failure_returns_graceful_error_envelope(self):
        # Make the orchestrator factory raise so the whole batch fails; the
        # handler must return an error envelope counting every id as an error.
        pids = [self._unique_pid(), self._unique_pid()]

        def _boom():
            raise RuntimeError("orchestrator unavailable")

        sdk = FakeSDKClient()
        with _MultiPatch(
            patch(_GET_MOLLIE_CLIENT, return_value=sdk),
            patch(_GET_API_KEY, return_value="test_fake"),
            patch(_GET_ORCHESTRATOR, side_effect=_boom),
        ):
            service = _make_service()
            # bulk_process_member_payments swallows the orchestrator-construction
            # error into result["error"] (it does not re-raise), so the handler's
            # own try/except is exercised by the inner failure path: counters
            # show 0 processed and the error is surfaced.
            result = service.process_payment_batch_background(
                batch_num=1, payment_ids=pids, docstatus=0, payment_modes={}, job_id="job-fail"
            )

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result.get("batch_num"), 1)
        self.assertEqual(result.get("job_id"), "job-fail")
        self.assertIn("error", result)
