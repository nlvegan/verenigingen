"""#2755: the scheduled and bulk Mollie list walks read through MollieClient's retry.

Each of these walked the raw SDK (`.list()` / `page.get_next()`), so one transient 429
was recorded as a failure instead of retried. Only the SDK HTTP boundary
(`MollieClient._get_mollie_client`) and `time.sleep` are stubbed; MollieClient, its
retry policy and every walk are real. MollieClient's circuit breaker is a deliberate
no-op, so what throttles a walk is the retry's backoff, observed through the stubbed sleep.

Per walk: a single 429 is retried and the walk completes; a persistent failure exhausts
the three attempts, is recorded once by the client (one "Mollie Client" Error Log row, not
one per attempt) and the walk stops or moves on per its existing contract; a healthy walk
makes exactly the expected number of requests and never sleeps.

Run:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_10 \\
        verenigingen.tests.payment.test_mollie_raw_walks_retry_2755
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

_SLEEP = "verenigingen.verenigingen_payments.core.resilience.retry_policy.time.sleep"


def _mollie_429_2755():
    from mollie.api.error import RequestError

    return RequestError("429 Too Many Requests")


def _now_iso_2755():
    return datetime.now(timezone.utc).isoformat()


class _Page:
    """One SDK page: iterable, with has_next()/get_next() and a request-counting get_next()."""

    def __init__(self, sdk, pages, index=0):
        self._sdk, self._walk_pages_2755, self._index = sdk, pages, index

    def __iter__(self):
        return iter(self._walk_pages_2755[self._index])

    def has_next(self):
        return self._index + 1 < len(self._walk_pages_2755)

    def get_next(self):
        self._sdk.calls["get_next"] += 1
        self._sdk.fail_if_scripted("get_next")
        return _Page(self._sdk, self._walk_pages_2755, self._index + 1)


class _Resource:
    """`<resource>.list(**params)`: page 0, or the page after the item named by `from`."""

    def __init__(self, sdk, name, pages):
        self._sdk, self._name, self._walk_pages_2755 = sdk, name, pages

    def list(self, **params):
        self._sdk.calls[f"{self._name}.list"] += 1
        self._sdk.fail_if_scripted(f"{self._name}.list")
        index = 0
        if params.get("from"):
            for i, page in enumerate(self._walk_pages_2755):
                if page and _item_id_2755(page[-1]) == params["from"]:
                    index = i + 1
        return _Page(self._sdk, self._walk_pages_2755, index)


def _item_id_2755(item):
    return item["id"] if isinstance(item, dict) else item.id


class _FakeSdk:
    """The Mollie SDK HTTP boundary. `failures[name]` is raised on that request's first calls."""

    def __init__(self, failures=None, **pages_by_resource):
        self._failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls = {
            "payments.list": 0,
            "refunds.list": 0,
            "chargebacks.list": 0,
            "get_next": 0,
            "customers.get": 0,
            "customer.payments.list": 0,
        }
        for name in ("payments", "refunds", "chargebacks"):
            setattr(self, name, _Resource(self, name, pages_by_resource.get(name, [[]])))
        self._customer_payments = pages_by_resource.get("customer_payments", [])
        self.customers = SimpleNamespace(get=self._customers_get)

    def fail_if_scripted(self, name):
        queue = self._failures.get(name)
        if queue:
            raise queue.pop(0)

    def _customers_get(self, customer_id):
        self.calls["customers.get"] += 1
        self.fail_if_scripted("customers.get")

        def _list(limit=None):
            self.calls["customer.payments.list"] += 1
            self.fail_if_scripted("customer.payments.list")
            return list(self._customer_payments)

        return SimpleNamespace(payments=SimpleNamespace(list=_list))


class _RetryWalkBase(EnhancedTestCase):
    """Real MollieClient over a fake SDK, a stubbed sleep, and Error Log accounting."""

    def run_over_sdk(self, sdk, walk, *expected_error_logs):
        self.expectErrorLog("Mollie Client", *expected_error_logs)
        self.client_rows_before = frappe.db.count("Error Log", {"method": "Mollie Client"})
        with patch.object(MollieClient, "_get_api_key", return_value="test_dummy"), patch.object(
            MollieClient, "_get_mollie_client", return_value=sdk
        ), patch(_SLEEP) as sleep:
            self.sleep = sleep
            return walk()

    def client_error_rows(self):
        return frappe.db.count("Error Log", {"method": "Mollie Client"}) - self.client_rows_before


def _walk_refund_2755(tag, n):
    return {"id": f"re_{tag}_{n}", "paymentId": f"tr_{tag}_{n}", "status": "refunded", "createdAt": _now_iso_2755()}


class TestReversalRediscoveryWalk(_RetryWalkBase):
    """`reversal_rediscovery_sweep._iter_pages`, the scheduled (daily) walk."""

    def _refund_pages_2755(self):
        tag = frappe.generate_hash(length=8)
        return tag, [[_walk_refund_2755(tag, 1), _walk_refund_2755(tag, 2)], [_walk_refund_2755(tag, 3)]]

    def _walk(self, sdk):
        from verenigingen.verenigingen_payments.mollie.services import reversal_rediscovery_sweep as sweep

        return self.run_over_sdk(sdk, lambda: [r["id"] for r in sweep._iter_pages(MollieClient(), "refunds")])

    def test_a_429_on_the_first_page_and_on_the_next_page_is_retried_and_the_walk_completes(self):
        tag, pages = self._refund_pages_2755()
        sdk = _FakeSdk(
            refunds=pages, failures={"refunds.list": [_mollie_429_2755()], "get_next": [_mollie_429_2755()]}
        )
        ids = self._walk(sdk)

        self.assertEqual(ids, [f"re_{tag}_{n}" for n in (1, 2, 3)])
        self.assertEqual(sdk.calls["refunds.list"], 2)
        self.assertEqual(sdk.calls["get_next"], 2)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(self.client_error_rows(), 0, "a recovered 429 is not an error")

    def test_a_persistent_failure_is_recorded_once_and_the_scheduled_sweep_books_nothing(self):
        from verenigingen.verenigingen_payments.mollie.services.reversal_rediscovery_sweep import (
            sweep_missed_reversals,
        )

        _, pages = self._refund_pages_2755()
        sdk = _FakeSdk(refunds=pages, failures={"refunds.list": [_mollie_429_2755() for _ in range(3)]})
        summary = self.run_over_sdk(
            sdk, sweep_missed_reversals, "Mollie reversal rediscovery sweep: problem(s)"
        )

        self.assertEqual(sdk.calls["refunds.list"], 3, "the retry policy's three attempts, no more")
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(self.client_error_rows(), 1, "one row for the exhausted read, not one per attempt")
        self.assertEqual(len(summary["errors"]), 1, summary)
        self.assertIn("could not list reversals at Mollie", summary["errors"][0]["error"])
        self.assertIn("429", summary["errors"][0]["error"])
        self.assertEqual(summary["reversals_booked"], 0)

    def test_a_persistent_next_page_failure_stops_the_walk_with_one_error(self):
        _, pages = self._refund_pages_2755()
        sdk = _FakeSdk(refunds=pages, failures={"get_next": [_mollie_429_2755() for _ in range(3)]})
        with self.assertRaises(MolliePaymentError):
            self._walk(sdk)

        self.assertEqual(sdk.calls["get_next"], 3)
        self.assertEqual(self.client_error_rows(), 1)

    def test_a_healthy_walk_makes_one_request_per_page_and_never_sleeps(self):
        tag, pages = self._refund_pages_2755()
        sdk = _FakeSdk(refunds=pages)
        ids = self._walk(sdk)

        self.assertEqual(ids, [f"re_{tag}_{n}" for n in (1, 2, 3)])
        self.assertEqual((sdk.calls["refunds.list"], sdk.calls["get_next"]), (1, 1))
        self.sleep.assert_not_called()


def _walk_payment_2755(tag, n):
    stamp = _now_iso_2755()
    return SimpleNamespace(
        id=f"tr_{tag}_{n}",
        created_at=stamp,
        paid_at=stamp,
        status="paid",
        amount={"currency": "EUR", "value": "10.00"},
    )


class _PaymentsWalkBase(_RetryWalkBase):
    def _walk_pages_2755(self):
        tag = frappe.generate_hash(length=8)
        return tag, [[_walk_payment_2755(tag, 1), _walk_payment_2755(tag, 2)], [_walk_payment_2755(tag, 3)]]


class TestBulkRunWalk(_PaymentsWalkBase):
    """`mollie_bulk_run_service._list_mollie_payments`, the Mollie Bulk Run's background walk."""

    def _walk(self, sdk):
        from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc

        def walk():
            with patch(
                "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher."
                "get_member_payment_matcher"
            ) as matcher:
                matcher.return_value.find_member_for_payment.return_value = None
                return [p["id"] for p in svc._list_mollie_payments(add_days(today(), -2), add_days(today(), 2))]

        return self.run_over_sdk(sdk, walk)

    def test_a_429_on_the_first_and_the_second_page_is_retried_and_the_walk_completes(self):
        tag, pages = self._walk_pages_2755()
        # Two lists: the first page's request, then the `from=` request for the next page.
        sdk = _FakeSdk(payments=pages, failures={"payments.list": [_mollie_429_2755()]})
        ids = self._walk(sdk)

        self.assertEqual(ids, [f"tr_{tag}_{n}" for n in (1, 2, 3)])
        self.assertEqual(sdk.calls["payments.list"], 3)  # 429 + page 1 + page 2
        self.assertEqual(self.sleep.call_count, 1)
        self.assertEqual(self.client_error_rows(), 0)

    def test_a_persistent_failure_is_recorded_once_and_the_walk_raises_as_before(self):
        _, pages = self._walk_pages_2755()
        sdk = _FakeSdk(payments=pages, failures={"payments.list": [_mollie_429_2755() for _ in range(3)]})
        with self.assertRaises(MolliePaymentError):
            self._walk(sdk)

        self.assertEqual(sdk.calls["payments.list"], 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(self.client_error_rows(), 1)

    def test_a_healthy_walk_makes_one_request_per_page_and_never_sleeps(self):
        tag, pages = self._walk_pages_2755()
        sdk = _FakeSdk(payments=pages)
        ids = self._walk(sdk)

        self.assertEqual(ids, [f"tr_{tag}_{n}" for n in (1, 2, 3)])
        self.assertEqual(sdk.calls["payments.list"], 2)
        self.sleep.assert_not_called()


class TestBulkPaymentAdminWalk(_PaymentsWalkBase):
    """`bulk_payment_admin_service._retrieve_global_payments_with_orphans` (the bulk retrieval)."""

    def _walk(self, sdk):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as admin

        def walk():
            with patch(
                "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher."
                "get_member_payment_matcher"
            ) as matcher:
                matcher.return_value.find_member_for_payment.return_value = None
                return admin._retrieve_global_payments_with_orphans(2, 10, "all")

        return self.run_over_sdk(sdk, walk, "Mollie Payment Processing")

    def test_a_429_on_the_second_page_is_retried_and_the_walk_completes(self):
        tag, pages = self._walk_pages_2755()
        sdk = _FakeSdk(payments=pages, failures={"payments.list": [_mollie_429_2755()]})
        out = self._walk(sdk)

        self.assertNotIn("error", out)
        self.assertEqual(out["total_payments_found"], 3)
        self.assertEqual(sdk.calls["payments.list"], 3)
        self.assertEqual(self.sleep.call_count, 1)
        self.assertEqual(self.client_error_rows(), 0)

    def test_a_persistent_failure_is_recorded_once_by_the_client_and_ends_the_walk_with_an_error(self):
        _, pages = self._walk_pages_2755()
        sdk = _FakeSdk(payments=pages, failures={"payments.list": [_mollie_429_2755() for _ in range(3)]})
        out = self._walk(sdk)

        self.assertIn("429", out["error"])
        self.assertEqual(out["total_payments_found"], 0)
        self.assertEqual(sdk.calls["payments.list"], 3)
        self.assertEqual(self.client_error_rows(), 1)

    def test_a_healthy_walk_makes_one_request_per_page_and_never_sleeps(self):
        _, pages = self._walk_pages_2755()
        sdk = _FakeSdk(payments=pages)
        out = self._walk(sdk)

        self.assertNotIn("error", out)
        self.assertEqual(out["total_payments_found"], 3)
        self.assertEqual(sdk.calls["payments.list"], 2)
        self.sleep.assert_not_called()


class TestDuesBatchWalk(_PaymentsWalkBase):
    """`DuesPaymentProcessor.batch_process_customer_payments`: the customer's payments read."""

    def _walk(self, sdk):
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        return self.run_over_sdk(
            sdk, lambda: DuesPaymentProcessor().batch_process_customer_payments("cst_2755", limit=5),
            "Mollie Batch Processing Error",
        )

    def test_a_429_on_the_customer_read_is_retried_and_the_batch_completes(self):
        sdk = _FakeSdk(customer_payments=[], failures={"customers.get": [_mollie_429_2755()]})
        out = self._walk(sdk)

        self.assertNotIn("error", out)
        self.assertEqual(out["total_retrieved"], 0)
        self.assertEqual(sdk.calls["customers.get"], 2)
        self.assertEqual(sdk.calls["customer.payments.list"], 1)
        self.assertEqual(self.sleep.call_count, 1)
        self.assertEqual(self.client_error_rows(), 0)

    def test_a_persistent_failure_is_recorded_once_by_the_client_and_the_batch_reports_the_error(self):
        sdk = _FakeSdk(failures={"customer.payments.list": [_mollie_429_2755() for _ in range(3)]})
        out = self._walk(sdk)

        self.assertIn("429", out["error"])
        self.assertEqual(sdk.calls["customer.payments.list"], 3)
        self.assertEqual(self.client_error_rows(), 1)

    def test_a_healthy_read_makes_one_request_per_step_and_never_sleeps(self):
        sdk = _FakeSdk(customer_payments=[])
        out = self._walk(sdk)

        self.assertNotIn("error", out)
        self.assertEqual((sdk.calls["customers.get"], sdk.calls["customer.payments.list"]), (1, 1))
        self.sleep.assert_not_called()


class TestListResourcePageGuards(_RetryWalkBase):
    def test_a_resource_outside_the_allowlist_is_refused_without_a_request(self):
        sdk = _FakeSdk()
        with self.assertRaises(ValueError):
            self.run_over_sdk(sdk, lambda: MollieClient().list_resource_page("customers"))
        self.assertEqual(sum(sdk.calls.values()), 0)

    def test_a_job_timeout_is_not_swallowed_into_a_payment_error(self):
        """#2140's listing re-raises a JobTimeoutException; the client's wrapper must not hide it."""
        from rq.timeouts import JobTimeoutException

        sdk = _FakeSdk(failures={"refunds.list": [JobTimeoutException()]})
        with self.assertRaises(JobTimeoutException):
            self.run_over_sdk(sdk, lambda: MollieClient().list_resource_page("refunds", limit=1))
        self.assertEqual(sdk.calls["refunds.list"], 1, "a timeout is not retried")
