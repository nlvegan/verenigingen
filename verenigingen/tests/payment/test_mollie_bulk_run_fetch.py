"""Tests for the Mollie fetch layer of the bulk run service.

_list_mollie_payments wraps the Mollie SDK's paginated ``payments.list``
API. These tests replace the SDK client with a fake so we can verify:
- date-range filtering on paid_at
- pagination walking via ``from`` cursor
- early-termination after N consecutive pre-range payments
- member-match lookup integration
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc


def _mk_payment(pid, created_at, paid_at=None, currency="EUR", value="10.00"):
    return SimpleNamespace(
        id=pid,
        created_at=created_at,
        paid_at=paid_at,
        status="paid",
        amount={"currency": currency, "value": value},
    )


class _FakePage:
    """Mimics the Mollie SDK's paginated list result."""

    def __init__(self, batch, next_batch=None):
        self._batch = batch
        self._next = next_batch

    def __iter__(self):
        return iter(self._batch)

    def has_next(self):
        return self._next is not None


class TestMollieFetchLayer(EnhancedTestCase):
    """Verify date filtering, pagination, and early termination in
    _list_mollie_payments."""

    def _install_fake_client(self, pages):
        """Patch MollieClient.sdk_client.payments.list to return the given pages in order."""
        call_state = {"index": 0}

        def fake_list(**kwargs):
            idx = call_state["index"]
            call_state["index"] += 1
            return pages[idx] if idx < len(pages) else _FakePage(batch=[])

        fake_client = MagicMock()
        fake_client.payments.list.side_effect = fake_list

        mollie_client_mock = MagicMock()
        mollie_client_mock.sdk_client = fake_client

        matcher_mock = MagicMock()
        matcher_mock.find_member_for_payment.return_value = None  # all orphan by default

        return patch.multiple(
            "verenigingen.verenigingen_payments.services.mollie_bulk_run_service",
            # patched inside the function's imported namespace — we patch the SDK via imports
        ), mollie_client_mock, matcher_mock, fake_client

    # --- Basic filtering ---------------------------------------------------

    def test_filters_by_paid_at_within_range(self):
        payments = [
            _mk_payment("tr_in1", "2021-02-01T10:00:00Z", paid_at="2021-02-01T10:00:00Z"),
            _mk_payment("tr_in2", "2021-02-15T10:00:00Z", paid_at="2021-02-15T10:00:00Z"),
            _mk_payment("tr_after", "2021-04-01T10:00:00Z", paid_at="2021-04-01T10:00:00Z"),
        ]
        pages = [_FakePage(batch=payments)]

        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"
        ) as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm:
            fake_client = MagicMock()
            fake_client.payments.list.side_effect = lambda **kw: pages[0]
            mc.return_value.sdk_client = fake_client
            mm.return_value.find_member_for_payment.return_value = None

            out = svc._list_mollie_payments("2021-01-01", "2021-03-31")

        ids = [p["id"] for p in out]
        self.assertIn("tr_in1", ids)
        self.assertIn("tr_in2", ids)
        self.assertNotIn("tr_after", ids)

    def test_paid_at_falls_back_to_created_at_when_missing(self):
        p = _mk_payment("tr_nopaid", "2021-02-01T10:00:00Z", paid_at=None)
        pages = [_FakePage(batch=[p])]

        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"
        ) as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm:
            fake_client = MagicMock()
            fake_client.payments.list.side_effect = lambda **kw: pages[0]
            mc.return_value.sdk_client = fake_client
            mm.return_value.find_member_for_payment.return_value = None

            out = svc._list_mollie_payments("2021-01-01", "2021-03-31")

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "tr_nopaid")

    # --- Pagination --------------------------------------------------------

    def test_walks_paginated_pages_via_from_cursor(self):
        page1_batch = [
            _mk_payment(f"tr_p1_{i}", "2021-02-01T10:00:00Z", paid_at="2021-02-01T10:00:00Z")
            for i in range(3)
        ]
        page2_batch = [
            _mk_payment(f"tr_p2_{i}", "2021-02-02T10:00:00Z", paid_at="2021-02-02T10:00:00Z")
            for i in range(2)
        ]
        page1 = _FakePage(batch=page1_batch, next_batch=page2_batch)
        page2 = _FakePage(batch=page2_batch)

        call_count = {"n": 0}

        def fake_list(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                self.assertNotIn("from", kwargs, "First call should not pass 'from' cursor")
                return page1
            self.assertEqual(kwargs.get("from"), "tr_p1_2")
            return page2

        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"
        ) as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm:
            fake_client = MagicMock()
            fake_client.payments.list.side_effect = fake_list
            mc.return_value.sdk_client = fake_client
            mm.return_value.find_member_for_payment.return_value = None

            out = svc._list_mollie_payments("2021-01-01", "2021-03-31")

        self.assertEqual(len(out), 5)
        self.assertEqual(call_count["n"], 2)

    # --- Early termination -------------------------------------------------

    def test_early_terminates_after_100_consecutive_older_payments(self):
        """Mollie returns newest-first; once we've seen 100 pre-range payments
        in a row we give up rather than walking years of history."""
        older_batch = [
            _mk_payment(f"tr_old_{i}", "2020-06-01T10:00:00Z", paid_at="2020-06-01T10:00:00Z")
            for i in range(120)  # more than the 100-threshold
        ]
        page = _FakePage(batch=older_batch)

        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"
        ) as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm:
            fake_client = MagicMock()
            fake_client.payments.list.side_effect = lambda **kw: page
            mc.return_value.sdk_client = fake_client
            mm.return_value.find_member_for_payment.return_value = None

            out = svc._list_mollie_payments("2021-01-01", "2021-03-31")

        self.assertEqual(out, [], "All 120 are pre-range, none should be returned")

    # --- Member matching integration --------------------------------------

    def test_matched_member_propagates_to_result(self):
        p1 = _mk_payment("tr_matched", "2021-02-01T10:00:00Z", paid_at="2021-02-01T10:00:00Z")
        p2 = _mk_payment("tr_orphan", "2021-02-02T10:00:00Z", paid_at="2021-02-02T10:00:00Z")
        page = _FakePage(batch=[p1, p2])

        def fake_match(payment):
            if payment.id == "tr_matched":
                return {"name": "Assoc-Member-TEST-001"}
            return None

        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"
        ) as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm:
            fake_client = MagicMock()
            fake_client.payments.list.side_effect = lambda **kw: page
            mc.return_value.sdk_client = fake_client
            mm.return_value.find_member_for_payment.side_effect = fake_match

            out = svc._list_mollie_payments("2021-01-01", "2021-03-31")

        by_id = {p["id"]: p for p in out}
        self.assertEqual(by_id["tr_matched"]["member"], "Assoc-Member-TEST-001")
        self.assertIsNone(by_id["tr_orphan"]["member"])

    # --- parse_datetime ---------------------------------------------------

    def test_parse_datetime_handles_various_inputs(self):
        self.assertIsNone(svc._parse_datetime(None))
        self.assertIsNone(svc._parse_datetime(""))

        # ISO with Z suffix → parsed
        result = svc._parse_datetime("2021-02-01T10:00:00Z")
        self.assertIsNotNone(result)

        # Garbage → None (graceful)
        self.assertIsNone(svc._parse_datetime("not-a-datetime"))

    def test_parse_datetime_strips_tzinfo_for_mariadb(self):
        """Regression: Mollie returns '+00:00' tz suffix; MariaDB DATETIME rejects it."""
        # Z suffix form
        dt_z = svc._parse_datetime("2022-11-02T17:55:20Z")
        self.assertIsNotNone(dt_z)
        self.assertIsNone(dt_z.tzinfo, "tzinfo must be stripped for DATETIME storage")

        # Explicit +00:00 form (as seen in the production error)
        dt_plus = svc._parse_datetime("2022-11-02T17:55:20+00:00")
        self.assertIsNotNone(dt_plus)
        self.assertIsNone(dt_plus.tzinfo)

        # Non-UTC offset converts to UTC before stripping
        dt_offset = svc._parse_datetime("2022-11-02T19:55:20+02:00")
        self.assertIsNotNone(dt_offset)
        self.assertIsNone(dt_offset.tzinfo)
        # 19:55 +02:00 == 17:55 UTC
        self.assertEqual(dt_offset.hour, 17)
        self.assertEqual(dt_offset.minute, 55)
