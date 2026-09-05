"""Recurring donation charge recovery sweep — unit tests (#872, part B of #345).

Mollie's webhook retry ladder gives up after 26 hours; before this sweep
existed, a charge no delivery ever reached stayed unbooked forever. These
tests stub the two boundaries the sweep crosses -- the Mollie SDK (a fake
subscription whose `.payments.list()` returns fixed payloads) and
DonationProcessor (the same class PaymentTypeRouter's DONATION branch now
uses, tested on its own in test_donation_processor_unit.py) -- so this module
only has to prove the sweep's own logic: which subscriptions it selects, and
what it does with each payment it finds.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge_sweep import (
    sweep_recurring_donation_charges,
)

_MODULE = "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge_sweep"


def _payment(payment_id, status="paid"):
    return SimpleNamespace(id=payment_id, status=status)


class _FakePage:
    """One Mollie payments page: iterable, with real has_next()/get_next().

    Mollie's List Subscription Payments endpoint paginates and returns
    newest-first; PaginationList (mollie-api-python 4.0.0) only iterates its
    OWN embedded page and exposes has_next()/get_next() for the rest. A fake
    that flattened every page into one list -- as this file's first version
    did -- would exercise a code path production never takes and hide a
    single-page-only bug (the defect this class exists to catch).
    """

    def __init__(self, payments, remaining_pages):
        self._payments = list(payments)
        self._remaining_pages = list(remaining_pages)

    def __iter__(self):
        return iter(self._payments)

    def has_next(self):
        return len(self._remaining_pages) > 0

    def get_next(self):
        if not self._remaining_pages:
            return None
        nxt, *rest = self._remaining_pages
        return _FakePage(nxt, rest)


class _FakeSubscription:
    def __init__(self, pages):
        """``pages``: a list of payment-lists, one per Mollie page.

        A plain flat list of payments is also accepted and treated as a
        single page, for tests that do not care about pagination -- detected
        by the first element not itself being a list (a payment fake is a
        SimpleNamespace, never a list).
        """
        if pages and not isinstance(pages[0], list):
            pages = [pages]
        self._pages = [list(p) for p in pages] if pages else [[]]

    @property
    def payments(self):
        first, *rest = self._pages
        return SimpleNamespace(list=lambda limit=None: _FakePage(first, rest))


class _FakeMollieClient:
    """Stand-in for MollieClient: maps subscription_id -> payments."""

    def __init__(self, subscriptions=None):
        self._subscriptions = subscriptions or {}

    def get_subscription(self, customer_id, subscription_id):
        return _FakeSubscription(self._subscriptions.get(subscription_id, []))


class _SweepTestBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("iDEAL")
        self.company = frappe.get_list("Company", limit=1)[0].name

    def _create_donation(self, **kwargs):
        donor = self.create_test_donor(donor_email=f"sweep.{frappe.generate_hash(length=8)}@example.org")
        defaults = dict(
            donor=donor.name,
            company=self.company,
            amount=10,
            donation_date=frappe.utils.today(),
            mode_of_payment="iDEAL",
            status="Recurring",
            paid=1,
        )
        defaults.update(kwargs)
        donation = frappe.get_doc({"doctype": "Donation", **defaults})
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation

    def _origin(self, tag, **kwargs):
        defaults = dict(
            mollie_subscription_id=f"sub_{tag}",
            mollie_customer_id=f"cst_{tag}",
            payment_id=f"tr_first_{tag}",
        )
        defaults.update(kwargs)
        return self._create_donation(**defaults)


class TestActiveSubscriptionSelection(_SweepTestBase):
    """Which Donation rows the sweep treats as active donation subscriptions."""

    def test_origin_with_subscription_is_swept(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)

        client = _FakeMollieClient(subscriptions={f"sub_{tag}": [_payment(f"tr_first_{tag}")]})
        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(f"{_MODULE}.DonationProcessor"):
            summary = sweep_recurring_donation_charges()

        self.assertGreaterEqual(summary["subscriptions_checked"], 1)

    def test_charge_donation_is_not_swept_as_its_own_subscription(self):
        # A charge Donation carries the same mollie_subscription_id as its
        # origin (recurring_donation_charge.py's _charge_values) -- without
        # excluding recurring_origin_donation rows, every already-booked
        # charge would be treated as another subscription to sweep.
        tag = frappe.generate_hash(length=8)
        origin = self._origin(tag)
        self._origin(tag, payment_id=f"tr_charge_{tag}", recurring_origin_donation=origin.name)

        seen_subscription_ids = []

        def _get_subscription(customer_id, subscription_id):
            seen_subscription_ids.append(subscription_id)
            return _FakeSubscription([])

        client = SimpleNamespace(get_subscription=_get_subscription)
        with patch(f"{_MODULE}.MollieClient", return_value=client):
            sweep_recurring_donation_charges()

        self.assertEqual(seen_subscription_ids.count(f"sub_{tag}"), 1)

    def test_one_time_donation_is_not_swept(self):
        tag = frappe.generate_hash(length=8)
        self._create_donation(status="One-time", payment_id=f"tr_onetime_{tag}")

        def _boom(*a, **k):
            raise AssertionError("should not be called for a One-time donation")

        client = SimpleNamespace(get_subscription=_boom)
        with patch(f"{_MODULE}.MollieClient", return_value=client):
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["subscriptions_checked"], 0)


class TestSweepOnePayment(_SweepTestBase):
    """Per-payment behaviour once a subscription's payments are listed."""

    def test_unpaid_charge_is_skipped_and_counted(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        client = _FakeMollieClient(
            subscriptions={f"sub_{tag}": [_payment(f"tr_pending_{tag}", status="pending")]}
        )

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["charges_not_paid"], 1)
        self.assertEqual(summary["charges_booked"], 0)
        mocked_processor.return_value.process_donation_payment.assert_not_called()

    def test_already_booked_charge_is_skipped_without_reprocessing(self):
        # origin.payment_id IS the first payment's id, so listing it back
        # from Mollie must not re-trigger booking.
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        client = _FakeMollieClient(subscriptions={f"sub_{tag}": [_payment(f"tr_first_{tag}")]})

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["charges_already_booked"], 1)
        self.assertEqual(summary["charges_booked"], 0)
        mocked_processor.return_value.process_donation_payment.assert_not_called()

    def test_unbooked_paid_charge_is_booked(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        client = _FakeMollieClient(
            subscriptions={f"sub_{tag}": [_payment(f"tr_first_{tag}"), _payment(f"tr_second_{tag}")]}
        )

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            mocked_processor.return_value.process_donation_payment.return_value = {"status": "success"}
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["charges_booked"], 1)
        self.assertEqual(summary["charges_already_booked"], 1)
        mocked_processor.return_value.process_donation_payment.assert_called_once()
        called_payment_id = mocked_processor.return_value.process_donation_payment.call_args[0][0]
        self.assertEqual(called_payment_id, f"tr_second_{tag}")

    def test_booking_failure_is_recorded_not_raised(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        client = _FakeMollieClient(subscriptions={f"sub_{tag}": [_payment(f"tr_second_{tag}")]})

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            mocked_processor.return_value.process_donation_payment.return_value = {
                "status": "error",
                "message": "No donation found",
            }
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["charges_booked"], 0)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(summary["errors"][0]["payment_id"], f"tr_second_{tag}")

    def test_one_subscription_failing_does_not_stop_the_sweep(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        tag2 = frappe.generate_hash(length=8)
        self._origin(
            tag2,
            mollie_subscription_id=f"sub_broken_{tag2}",
            mollie_customer_id=f"cst_broken_{tag2}",
            payment_id=f"tr_first_{tag2}",
        )

        good_client = _FakeMollieClient(subscriptions={f"sub_{tag}": [_payment(f"tr_second_{tag}")]})

        def _get_subscription(customer_id, subscription_id):
            if subscription_id == f"sub_broken_{tag2}":
                raise RuntimeError("Mollie unreachable")
            return good_client.get_subscription(customer_id, subscription_id)

        combined_client = SimpleNamespace(get_subscription=_get_subscription)
        with patch(f"{_MODULE}.MollieClient", return_value=combined_client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            mocked_processor.return_value.process_donation_payment.return_value = {"status": "success"}
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["subscriptions_checked"], 2)
        self.assertEqual(summary["charges_booked"], 1)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(summary["errors"][0]["subscription_id"], f"sub_broken_{tag2}")


class TestPagination(_SweepTestBase):
    """A subscription with more payments than one Mollie page.

    Mollie's List Subscription Payments endpoint returns newest-first and
    paginates; a single page is a SLIDING WINDOW over recent charges, not a
    growing scan -- a charge that ages past the first page while unbooked
    would never be revisited by a later run unless every `next` link is
    followed. These tests build a subscription whose payments span more than
    one page and prove the sweep actually walks past the first one.
    """

    def test_an_unbooked_charge_on_the_second_page_is_still_booked(self):
        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        # Page 1 carries only the already-booked first payment; the unbooked
        # charge sits on page 2. Reading only page 1 would find nothing to
        # book and this test would see charges_booked == 0.
        client = _FakeMollieClient(
            subscriptions={
                f"sub_{tag}": [
                    [_payment(f"tr_first_{tag}")],
                    [_payment(f"tr_page2_{tag}")],
                ]
            }
        )

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            mocked_processor.return_value.process_donation_payment.return_value = {"status": "success"}
            summary = sweep_recurring_donation_charges()

        self.assertEqual(summary["charges_already_booked"], 1)
        self.assertEqual(summary["charges_booked"], 1)
        mocked_processor.return_value.process_donation_payment.assert_called_once()
        called_payment_id = mocked_processor.return_value.process_donation_payment.call_args[0][0]
        self.assertEqual(called_payment_id, f"tr_page2_{tag}")

    def test_pagination_is_bounded_so_one_subscription_cannot_run_unbounded(self):
        from verenigingen.verenigingen_payments.mollie.services import (
            recurring_donation_charge_sweep as sweep_module,
        )

        tag = frappe.generate_hash(length=8)
        self._origin(tag)
        # One distinct unbooked charge per page, well past the bound -- if
        # get_next() were followed forever, every page would be seen and
        # booked (or attempted); the bound must cut this off at exactly
        # _MAX_PAGES_PER_SUBSCRIPTION pages read (this subscription's first
        # page carries the origin's own payment, plus one page per index).
        total_pages = sweep_module._MAX_PAGES_PER_SUBSCRIPTION + 5
        pages = [[_payment(f"tr_first_{tag}")]] + [
            [_payment(f"tr_p{i}_{tag}")] for i in range(total_pages - 1)
        ]
        client = _FakeMollieClient(subscriptions={f"sub_{tag}": pages})

        with patch(f"{_MODULE}.MollieClient", return_value=client), patch(
            f"{_MODULE}.DonationProcessor"
        ) as mocked_processor:
            mocked_processor.return_value.process_donation_payment.return_value = {"status": "success"}
            summary = sweep_recurring_donation_charges()

        total_seen = (
            summary["charges_booked"] + summary["charges_already_booked"] + summary["charges_not_paid"]
        )
        self.assertEqual(total_seen, sweep_module._MAX_PAGES_PER_SUBSCRIPTION)
