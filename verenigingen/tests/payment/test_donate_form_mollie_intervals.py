"""
Every subscription interval the public donation form can emit must be one Mollie accepts.

Target: verenigingen/templates/pages/donate.html (the "Recurring" frequency buttons
and the subscription_interval hidden input).

Why a test at all: the value those buttons write ends up in Mollie payment metadata and
then in the subscription Mollie creates. The chain is
    donate.html
      -> templates/pages/donate.submit_donation
      -> PublicDonationService.process_mollie_payment  (services/donation/)
      -> CompletePaymentService.create_recurring_donation_payment
      -> payment metadata -> Mollie
so an interval Mollie refuses would fail at the far end, where CompletePaymentService
now rejects it up front instead. Guarding the near end as well is cheap and catches the
mistake where it is introduced -- someone adding a frequency button.

This test does NOT prove the value survives the chain; test_donate_page_mollie.py
::test_the_donors_chosen_frequency_reaches_the_payment_service does that, and was
written because it did not survive it.

The accepted grammar was measured against the live Mollie test API rather than read off
the docs (a customer with a real directdebit mandate, one subscription create per
candidate, every created subscription cancelled afterwards):

    1 day / 7 days / 14 days / 1 week / 2 weeks  -> 201 accepted
    1 month / 3 months / 6 months / 12 months    -> 201 accepted
    1 year / 2 years                             -> 422 "The interval unit is invalid"
    banana / 0 months  (controls)                -> 422

So Mollie counts in days, weeks and months only; an annual subscription has to be
spelled "12 months". A first probe without a mandate proved nothing -- the "no suitable
mandates found" check fires before interval validation, so every candidate including
nonsense returned the same 422.
"""

import re
import unittest
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    is_valid_mollie_interval,
)

# Deliberately the production predicate rather than a second copy of the grammar:
# a private regex here could drift from the one the gateway enforces and leave both
# suites green while the template and the API disagreed.

DONATE_HTML = (
    Path(frappe.get_app_path("verenigingen")) / "templates" / "pages" / "donate.html"
)


def _intervals_offered_by_the_donate_form():
    """Every interval literal the form can put into subscription_interval.

    Three independent sources, because the button carries the value twice (the
    onclick argument and the data-interval attribute) and the hidden input holds
    the default used when the donor never touches a frequency button.
    """
    html = DONATE_HTML.read_text(encoding="utf-8")

    onclick = set(re.findall(r"selectFrequencyOption\('([^']+)'", html))
    data_attr = set(re.findall(r'data-interval="([^"]+)"', html))
    default = set(
        re.findall(
            r'<input[^>]*id="subscription_interval"[^>]*value="([^"]+)"',
            html,
        )
    )
    return onclick, data_attr, default


class TestDonateFormMollieIntervals(FrappeTestCase):
    def test_the_form_offers_the_frequencies_this_test_thinks_it_does(self):
        """Premise check: the extraction must actually find something.

        Without this, a template rewrite that changes the markup shape turns every
        assertion below into a vacuous pass over an empty set.
        """
        onclick, data_attr, default = _intervals_offered_by_the_donate_form()

        self.assertEqual(
            len(onclick),
            4,
            f"expected 4 frequency buttons in donate.html, found {sorted(onclick)}. "
            f"If you added or removed one deliberately, update this count -- it is here "
            f"so a markup change cannot silently empty the set the next test checks.",
        )
        self.assertEqual(onclick, data_attr, "onclick argument and data-interval disagree")
        self.assertEqual(len(default), 1, "expected exactly one subscription_interval hidden input")

    def test_every_offered_interval_is_one_mollie_accepts(self):
        onclick, data_attr, default = _intervals_offered_by_the_donate_form()

        for interval in sorted(onclick | data_attr | default):
            with self.subTest(interval=interval):
                self.assertTrue(
                    is_valid_mollie_interval(interval),
                    f"donate.html offers {interval!r}, which Mollie rejects with 422 "
                    f'"The interval unit is invalid". Annual must be spelled '
                    f"'12 months'.",
                )

    def test_an_annual_option_is_still_offered(self):
        """The fix must not silently drop Annually from the form."""
        onclick, _, _ = _intervals_offered_by_the_donate_form()

        self.assertIn("12 months", onclick)


if __name__ == "__main__":
    unittest.main()
