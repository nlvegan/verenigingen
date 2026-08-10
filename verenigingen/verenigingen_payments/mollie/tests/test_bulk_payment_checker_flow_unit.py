"""
Flow-level tests for BulkPaymentChecker — the orchestration methods that the
existing pure-helper suite (test_bulk_payment_checker_unit.py) and DB suite
(test_mollie_payment_db_integration.py) do NOT reach.

Targets (verenigingen/verenigingen_payments/mollie/services/bulk_payment_checker.py):
    - BulkPaymentChecker._fetch_customer_with_rate_limit_retry  (429 retry path)
    - BulkPaymentChecker._check_for_matching_invoice            (gating + delegation)
    - BulkPaymentChecker.check_payments_for_customer            (per-customer discovery)
    - BulkPaymentChecker.process_discovered_payments            (stage-2: dry-run + real)
    - BulkPaymentChecker._log_bulk_operation_audit              (audit trail, both branches)
    - BulkPaymentChecker.find_matching_unpaid_dues_invoice      (deprecated delegator)
    - BulkPaymentChecker.check_invoice_match_for_payment        (deprecated delegator)

Credential-free pattern
------------------------
BulkPaymentChecker.__init__ builds a MollieClient (needs Mollie Settings keys)
and a DuesPaymentProcessor (which builds another MollieClient). Neither is used
by the methods under test except via the ``sdk_client`` seam and the
``dues_processor`` collaborator. We therefore obtain an instance via
``object.__new__()`` (bypassing __init__, so no MollieClient is built) and attach
only the collaborators each method actually reads:
    - a fake ``mollie_client`` exposing ``.sdk_client.customers.get(...)`` /
      ``.sdk_client.payments.get(...)`` — the Mollie SDK boundary, stubbed with
      ``types.SimpleNamespace`` per the project trust model (the resource is
      re-fetched from Mollie; here we hand back a pre-built fake instead).
    - a real ``DuesPaymentProcessor`` (also built via object.__new__ + a real
      PaymentClassifier) so ``identify_payment_type`` / ``find_member_for_payment``
      run the REAL DB-backed classification — never mocked.

The methods read/query real DocTypes (Member, Bank Transaction, Payment Entry,
Sales Invoice). No logic under test is mocked.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import BulkPaymentChecker
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor


# ---------------------------------------------------------------------------
# Mollie SDK boundary fakes (SimpleNamespace-based, no network)
# ---------------------------------------------------------------------------
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _raw_sdk_payment(
    *,
    pid="tr_flow001",
    status="paid",
    value="25.00",
    currency="EUR",
    description="contributie 2025",
    customer_id=None,
    subscription_id=None,
    created_at=None,
    paid_at=None,
):
    """A RAW Mollie-SDK payment dict (the API-response shape).

    ``check_payments_for_customer`` converts each listed payment via
    ``MolliePayment.from_mollie_api(sdk_payment)``, which indexes the dict
    (``data["id"]``, ``data["amount"]`` …) and parses ISO ``createdAt`` /
    ``paidAt`` strings. So the customer-flow tests feed RAW dicts here, not the
    typed object.
    """
    if created_at is None:
        created_at = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
    paid = paid_at if paid_at is not None else created_at
    data = {
        "id": pid,
        "status": status,
        "amount": {"value": value, "currency": currency},
        "description": description,
        "customerId": customer_id,
        "subscriptionId": subscription_id,
        "createdAt": _iso(created_at),
        "paidAt": _iso(paid) if paid is not None else None,
    }
    return data


def _sdk_payment(
    *,
    pid="tr_flow001",
    status="paid",
    value="25.00",
    currency="EUR",
    description="contributie 2025",
    customer_id=None,
    subscription_id=None,
    created_at=None,
    paid_at=None,
):
    """A SimpleNamespace payment stub for methods that read attributes directly.

    Used by ``_check_for_matching_invoice`` and ``process_discovered_payments``
    (dry-run / real), where the production code reads ``payment.amount`` (dict),
    ``.status``, ``.paid_at``/``.created_at`` (datetimes), ``.description`` —
    matching the typed object's attribute surface.
    """
    if created_at is None:
        created_at = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=pid,
        status=status,
        amount={"value": value, "currency": currency},
        description=description,
        customer_id=customer_id,
        subscription_id=subscription_id,
        created_at=created_at,
        paid_at=paid_at if paid_at is not None else created_at,
    )


class _FakeCustomerPayments:
    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=250):
        return self._payments


class _FakeCustomerObj:
    def __init__(self, payments):
        self.payments = _FakeCustomerPayments(payments)


class _FakeCustomers:
    """Stubs sdk_client.customers.get(customer_id)."""

    def __init__(self, payments, *, raise_exc=None, raise_then=None):
        self._payments = payments
        self._raise_exc = raise_exc  # always raise this
        self._raise_then = raise_then  # raise on first call, succeed after
        self.call_count = 0

    def get(self, customer_id):
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._raise_then is not None and self.call_count == 1:
            raise self._raise_then
        return _FakeCustomerObj(self._payments)


class _FakePayments:
    """Stubs sdk_client.payments.get(payment_id) keyed by id."""

    def __init__(self, by_id):
        self._by_id = by_id

    def get(self, payment_id):
        return self._by_id[payment_id]


class _FakeSdkClient:
    def __init__(self, *, customers=None, payments=None):
        self.customers = customers
        self.payments = payments


class _FakeMollieClient:
    def __init__(self, *, customers=None, payments=None):
        self.sdk_client = _FakeSdkClient(customers=customers, payments=payments)


def _real_dues_processor():
    """Real DuesPaymentProcessor with no MollieClient (credential-free).

    identify_payment_type / find_member_for_payment hit only the DB-backed
    classifier + matcher, so a bypassed instance with a real PaymentClassifier
    runs the genuine classification logic.
    """
    proc = object.__new__(DuesPaymentProcessor)
    proc.classifier = PaymentClassifier()
    return proc


def _make_checker(*, customers=None, payments=None):
    checker = object.__new__(BulkPaymentChecker)
    checker.mollie_client = _FakeMollieClient(customers=customers, payments=payments)
    checker.dues_processor = _real_dues_processor()
    return checker


def _reset_matcher_cache():
    import verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher as mpm

    mpm._matcher_instance = None


# ===========================================================================
# _fetch_customer_with_rate_limit_retry
# ===========================================================================
class TestFetchCustomerRateLimitRetry(EnhancedTestCase):
    def test_returns_customer_on_first_success(self):
        customers = _FakeCustomers([_sdk_payment()])
        obj = BulkPaymentChecker._fetch_customer_with_rate_limit_retry(
            _FakeSdkClient(customers=customers), "cst_ok"
        )
        self.assertIsInstance(obj, _FakeCustomerObj)
        self.assertEqual(customers.call_count, 1)

    def test_non_429_error_propagates_without_retry(self):
        boom = RuntimeError("network down")
        customers = _FakeCustomers([], raise_exc=boom)
        with self.assertRaises(RuntimeError):
            BulkPaymentChecker._fetch_customer_with_rate_limit_retry(
                _FakeSdkClient(customers=customers), "cst_err"
            )
        # No retry for non-429 -> exactly one attempt.
        self.assertEqual(customers.call_count, 1)


# ===========================================================================
# _check_for_matching_invoice  (gating logic + delegation)
# ===========================================================================
class TestCheckForMatchingInvoice(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.checker = _make_checker()

    def _idem(self, processed=False):
        return {"already_processed": processed, "payment_entry": None, "bank_transaction": None}

    def test_returns_none_when_already_processed(self):
        # Gate: already-processed payments are not invoice-matched.
        p = _sdk_payment()
        result = self.checker._check_for_matching_invoice(
            p, "Assoc-Member-X", self._idem(processed=True), "dues", None, "25.00"
        )
        self.assertIsNone(result)

    def test_returns_none_when_not_dues(self):
        p = _sdk_payment()
        result = self.checker._check_for_matching_invoice(
            p, "Assoc-Member-X", self._idem(), "donation", None, "25.00"
        )
        self.assertIsNone(result)

    def test_returns_none_with_currency_warning(self):
        p = _sdk_payment(currency="USD")
        result = self.checker._check_for_matching_invoice(
            p, "Assoc-Member-X", self._idem(), "dues", "Non-EUR currency: USD.", "25.00"
        )
        self.assertIsNone(result)

    def test_no_matching_invoice_for_member_without_invoice(self):
        # Passes the gate (paid+dues+not-processed+EUR) and runs the REAL
        # InvoiceMatcher against a member with no unpaid dues invoice -> None.
        member = self.create_test_member(
            first_name="Match",
            last_name=f"None{frappe.generate_hash()[:6]}",
            email=f"match.none.{frappe.generate_hash()[:6]}@example.com",
        )
        p = _sdk_payment(paid_at=datetime(2025, 1, 15, tzinfo=timezone.utc))
        result = self.checker._check_for_matching_invoice(p, member.name, self._idem(), "dues", None, "25.00")
        self.assertIsNone(result)


# ===========================================================================
# check_payments_for_customer  (per-customer discovery flow)
# ===========================================================================
class TestCheckPaymentsForCustomer(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        _reset_matcher_cache()

    def _member_with_cid(self, cid):
        member = self.create_test_member(
            first_name="Disc",
            last_name=f"M{frappe.generate_hash()[:6]}",
            email=f"disc.{frappe.generate_hash()[:6]}@example.com",
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)
        return member

    def test_discovers_processable_dues_payment(self):
        cid = f"cst_disc_{frappe.generate_hash()[:8]}"
        member = self._member_with_cid(cid)
        ref = f"tr_disc_{frappe.generate_hash()[:8]}"
        payment = _raw_sdk_payment(pid=ref, status="paid", description="contributie 2025", customer_id=cid)
        checker = _make_checker(customers=_FakeCustomers([payment]))

        result = checker.check_payments_for_customer(cid, member.name)

        self.assertIsNone(result["error"], msg=result)
        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["new_payments"], 1)
        self.assertEqual(len(result["payments"]), 1)
        info = result["payments"][0]
        self.assertEqual(info["id"], ref)
        self.assertEqual(info["payment_type"], "dues")
        self.assertTrue(info["processable"])

    def test_unpaid_payment_is_not_counted_new(self):
        cid = f"cst_open_{frappe.generate_hash()[:8]}"
        member = self._member_with_cid(cid)
        payment = _raw_sdk_payment(
            pid=f"tr_open_{frappe.generate_hash()[:8]}",
            status="open",
            description="contributie",
            customer_id=cid,
        )
        checker = _make_checker(customers=_FakeCustomers([payment]))
        result = checker.check_payments_for_customer(cid, member.name)
        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["new_payments"], 0)
        self.assertFalse(result["payments"][0]["processable"])

    def test_date_filter_excludes_old_payment(self):
        cid = f"cst_olddate_{frappe.generate_hash()[:8]}"
        member = self._member_with_cid(cid)
        old = _raw_sdk_payment(
            pid=f"tr_old_{frappe.generate_hash()[:8]}",
            description="contributie",
            customer_id=cid,
            paid_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        checker = _make_checker(customers=_FakeCustomers([old]))
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = checker.check_payments_for_customer(cid, member.name, from_date=from_date)
        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["filtered_by_date"], 1)
        self.assertEqual(len(result["payments"]), 0)

    def test_non_eur_currency_warning_blocks_processable(self):
        cid = f"cst_usd_{frappe.generate_hash()[:8]}"
        member = self._member_with_cid(cid)
        payment = _raw_sdk_payment(
            pid=f"tr_usd_{frappe.generate_hash()[:8]}",
            description="contributie",
            customer_id=cid,
            currency="USD",
        )
        checker = _make_checker(customers=_FakeCustomers([payment]))
        result = checker.check_payments_for_customer(cid, member.name)
        info = result["payments"][0]
        self.assertIsNotNone(info["currency_warning"])
        self.assertFalse(info["processable"])

    def test_api_error_is_captured_in_result(self):
        cid = f"cst_apierr_{frappe.generate_hash()[:8]}"
        member = self._member_with_cid(cid)
        checker = _make_checker(customers=_FakeCustomers([], raise_exc=RuntimeError("Mollie API exploded")))
        result = checker.check_payments_for_customer(cid, member.name)
        self.assertIsNotNone(result["error"])
        self.assertIn("exploded", result["error"])
        self.assertEqual(result["payments"], [])


# ===========================================================================
# process_discovered_payments  (stage 2)
# ===========================================================================
class TestProcessDiscoveredPayments(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        _reset_matcher_cache()

    def test_empty_payment_ids_raises(self):
        checker = _make_checker()
        with self.assertRaises(ValueError):
            checker.process_discovered_payments([])

    def test_dry_run_reports_without_creating(self):
        cid = f"cst_dry_{frappe.generate_hash()[:8]}"
        member = self.create_test_member(
            first_name="Dry",
            last_name=f"Run{frappe.generate_hash()[:6]}",
            email=f"dry.{frappe.generate_hash()[:6]}@example.com",
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)
        ref = f"tr_dry_{frappe.generate_hash()[:8]}"
        payment = _sdk_payment(pid=ref, description="contributie", customer_id=cid)
        checker = _make_checker(payments=_FakePayments({ref: payment}))

        result = checker.process_discovered_payments([ref], dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["processed"], 0)
        pr = result["results"][0]
        self.assertEqual(pr["status"], "dry_run")
        self.assertEqual(pr["payment_type"], "dues")
        self.assertEqual(pr["member"], member.name)
        self.assertTrue(pr["would_process"])
        # No Bank Transaction / Payment Entry should have been created.
        self.assertFalse(frappe.db.exists("Bank Transaction", {"reference_number": ref}))
        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": ref}))

    def test_real_processing_skips_non_paid_payment(self):
        # Real stage-2: process_dues_payment runs against a non-paid payment and
        # short-circuits to "skipped" (before any dues-routing / account wiring).
        # This pins the loop + per-payment result-tallying and the status gate.
        # (Full paid-dues routing is covered by the dues suite's
        # test_batch_processes_paid_dues_payment_for_member.)
        ref = f"tr_skip_{frappe.generate_hash()[:8]}"
        payment = _sdk_payment(pid=ref, status="open", description="contributie")
        checker = _make_checker(payments=_FakePayments({ref: payment}))
        # process_dues_payment builds its own collaborators on a real processor;
        # give the dues_processor the SDK seam it uses for the (unused here) fetch.
        checker.dues_processor.mollie_client = checker.mollie_client
        checker.dues_processor.bank_tx_creator = __import__(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator",
            fromlist=["get_bank_transaction_creator"],
        ).get_bank_transaction_creator()

        result = checker.process_discovered_payments([ref], dry_run=False)
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["skipped"], 1)
        pr = result["results"][0]
        self.assertEqual(pr["status"], "skipped")
        self.assertIn("not 'paid'", pr["skipped_reason"])

    def test_processing_error_is_tallied(self):
        # A payment id the SDK fake doesn't know about -> KeyError -> error tally.
        checker = _make_checker(payments=_FakePayments({}))
        result = checker.process_discovered_payments(["tr_missing"], dry_run=False)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")


# ===========================================================================
# _log_bulk_operation_audit  (both severity branches)
# ===========================================================================
class TestLogBulkOperationAudit(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.checker = _make_checker()

    def _find_audit_row(self, operation_type):
        """Return the API Audit Log row this operation persisted (or None).

        log_security_event(event_type="other") stores a row in API Audit Log
        with the real type in details["custom_event_type"] = bulk_payment_<op>.
        It inserts WITHOUT committing, so within this still-open test transaction
        the row is queryable; we match on the details JSON substring.
        """
        rows = frappe.get_all(
            "API Audit Log",
            filters={
                "event_type": "other",
                "details": ["like", f"%bulk_payment_{operation_type}%"],
            },
            fields=["name", "severity", "details"],
            order_by="creation desc",
            limit=1,
        )
        return rows[0] if rows else None

    def test_discovery_audit_persists_info_event(self):
        # Clean discovery (no errors, no circuit breaker) -> INFO severity. Assert
        # a row was actually persisted with the right custom_event_type + severity,
        # not merely that the call did not raise.
        result = {
            "members_checked": 2,
            "total_members": 2,
            "total_payments_found": 3,
            "total_new_payments": 1,
            "errors": 0,
            "circuit_breaker_triggered": False,
        }
        self.checker._log_bulk_operation_audit(result, "discovery", days_back=7, all_history=False)

        row = self._find_audit_row("discovery")
        self.assertIsNotNone(row, "discovery audit row must be persisted")
        self.assertEqual(row["severity"], "info")
        self.assertIn("bulk_payment_discovery", row["details"])
        self.assertIn('"date_range": "7_days"', row["details"])

    def test_processing_audit_with_errors_persists_warning_event(self):
        result = {
            "members_checked": 0,
            "total_members": 0,
            "total_payments_found": 0,
            "total_new_payments": 0,
            "errors": 2,
            "circuit_breaker_triggered": True,
            "processed": 1,
            "skipped": 1,
            "dry_run": False,
        }
        # circuit_breaker_triggered + errors -> WARNING severity branch.
        self.checker._log_bulk_operation_audit(result, "processing")

        row = self._find_audit_row("processing")
        self.assertIsNotNone(row, "processing audit row must be persisted")
        self.assertEqual(row["severity"], "warning")
        self.assertIn("bulk_payment_processing", row["details"])


# ===========================================================================
# Deprecated delegators
# ===========================================================================
class TestDeprecatedDelegators(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.checker = _make_checker()

    def test_find_matching_unpaid_dues_invoice_warns_and_returns_none(self):
        import warnings

        member = self.create_test_member(
            first_name="Dep",
            last_name=f"Inv{frappe.generate_hash()[:6]}",
            email=f"dep.inv.{frappe.generate_hash()[:6]}@example.com",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self.checker.find_matching_unpaid_dues_invoice(
                member.name, 25.0, datetime(2025, 1, 15, tzinfo=timezone.utc)
            )
        # Member has no unpaid dues invoice -> delegate returns not-found -> None.
        self.assertIsNone(result)
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))

    def test_check_invoice_match_for_payment_warns_and_returns_none(self):
        import warnings

        member = self.create_test_member(
            first_name="Dep",
            last_name=f"Pay{frappe.generate_hash()[:6]}",
            email=f"dep.pay.{frappe.generate_hash()[:6]}@example.com",
        )
        sdk_payment = {
            "id": "tr_dep_x",
            "amount": {"value": "25.00", "currency": "EUR"},
            "paidAt": "2025-01-15T12:00:00+00:00",
            "createdAt": "2025-01-15T12:00:00+00:00",
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self.checker.check_invoice_match_for_payment(sdk_payment, member.name)
        self.assertIsNone(result)
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))


if __name__ == "__main__":
    import unittest

    unittest.main()
