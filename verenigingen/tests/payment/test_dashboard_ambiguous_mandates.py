"""#2289: the dashboard API and the member-form indicator must not show the newest of
several Active membership mandates as "the" mandate.

A member holding two Active SEPA mandates for the SAME purpose is a legacy/race state
(pre-#584 rows are not rewritten). Collection refuses to debit either
(`mandate_candidates.unambiguous_active_mandate`), and since #607 the dashboard page says
"needs attention, contact the office". These endpoints used to take `[0]` of a
`creation desc` list, so they told the same member "mandate active" with the newest
mandate's IBAN and expiry.

The second Active mandate is forced past `validate_single_active_mandate` with
`frappe.db.set_value` (same bypass as `test_payment_retry`), which is how the state is
actually reached on an upgraded install. Each test pairs with a single-mandate control
that goes through the same endpoint, so "refuses" cannot be satisfied by "always refuses".
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.api.payment_dashboard import get_dashboard_data, get_payment_method
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member.member_utils import check_sepa_mandate_status

OLD_IBAN = "NL91ABNA0417164300"
NEW_IBAN = "NL39RABO0300065264"
REFUSAL_TITLE = "Dashboard payment method: ambiguous mandate"


class DashboardMandateFixture(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Ambig", last_name="Mandate", status="Active")

    def _dues_mandate_active(self, iban, expiry_date):
        return self.create_test_sepa_mandate(
            member=self.member.name,
            iban=iban,
            status="Active",
            expiry_date=expiry_date,
            used_for_memberships=1,
            used_for_donations=0,
        )

    def _make_two_active(self, old_expiry=None, new_expiry=None):
        """An OLDER and a NEWER Active membership mandate, the newer one forced Active."""
        old = self._dues_mandate_active(OLD_IBAN, old_expiry)
        new = self.create_test_sepa_mandate(
            member=self.member.name,
            iban=NEW_IBAN,
            status="Draft",
            expiry_date=new_expiry,
            used_for_memberships=1,
            used_for_donations=0,
        )
        frappe.db.set_value("SEPA Mandate", new.name, "status", "Active", update_modified=False)
        self.assertEqual(
            frappe.db.count(
                "SEPA Mandate",
                {"member": self.member.name, "status": "Active", "used_for_memberships": 1},
            ),
            2,
            "fixture must really hold two Active membership mandates",
        )
        return old, new

    @staticmethod
    def _endpoint_data(result):
        data = result if isinstance(result, dict) else result.to_dict()
        return data.get("data", data)


class TestPaymentMethodWithSeveralActiveMandates(DashboardMandateFixture):
    def test_two_active_mandates_are_not_shown_as_the_newest_one(self):
        self._make_two_active()
        self.expectErrorLog(REFUSAL_TITLE)

        payload = self._endpoint_data(get_payment_method(self.member.name))

        self.assertFalse(payload["has_active_mandate"])
        self.assertTrue(payload["mandate_ambiguous"])
        self.assertNotIn("mandate", payload, "no IBAN may be shown as 'the' mandate")

    def test_a_single_active_mandate_is_still_shown(self):
        mandate = self._dues_mandate_active(OLD_IBAN, None)

        payload = self._endpoint_data(get_payment_method(self.member.name))

        self.assertTrue(payload["has_active_mandate"])
        self.assertFalse(payload["mandate_ambiguous"])
        self.assertEqual(payload["mandate"]["mandate_id"], mandate.mandate_id)

    def test_no_mandate_is_not_reported_as_ambiguous(self):
        payload = self._endpoint_data(get_payment_method(self.member.name))

        self.assertFalse(payload["has_active_mandate"])
        self.assertFalse(payload["mandate_ambiguous"])


class TestDashboardExpiryWithSeveralActiveMandates(DashboardMandateFixture):
    def test_the_newest_mandates_expiry_is_not_the_warning(self):
        # Only the NEWEST row expires soon: pick-newest warns, refusal does not.
        self._make_two_active(old_expiry=add_days(today(), 200), new_expiry=add_days(today(), 10))
        self.expectErrorLog("Dashboard data: ambiguous mandate")

        payload = self._endpoint_data(get_dashboard_data(self.member.name))

        self.assertFalse(payload["mandate_expiring_soon"])
        self.assertTrue(payload["mandate_ambiguous"])

    def test_a_single_mandate_expiring_soon_still_warns(self):
        self._dues_mandate_active(OLD_IBAN, add_days(today(), 10))

        payload = self._endpoint_data(get_dashboard_data(self.member.name))

        self.assertTrue(payload["mandate_expiring_soon"])
        self.assertFalse(payload["mandate_ambiguous"])


class TestMemberFormIndicatorWithSeveralActiveMandates(DashboardMandateFixture):
    def test_two_active_mandates_are_not_reported_as_an_active_mandate(self):
        self._make_two_active(old_expiry=add_days(today(), 200), new_expiry=add_days(today(), 5))
        self.expectErrorLog("Member form mandate status: ambiguous mandate")

        result = check_sepa_mandate_status(self.member.name)

        self.assertFalse(result["has_active_mandate"])
        self.assertFalse(result["expiring_soon"])
        self.assertTrue(result["mandate_ambiguous"])

    def test_a_single_active_mandate_is_still_reported(self):
        self._dues_mandate_active(OLD_IBAN, add_days(today(), 5))

        result = check_sepa_mandate_status(self.member.name)

        self.assertTrue(result["has_active_mandate"])
        self.assertTrue(result["expiring_soon"])
        self.assertFalse(result["mandate_ambiguous"])
