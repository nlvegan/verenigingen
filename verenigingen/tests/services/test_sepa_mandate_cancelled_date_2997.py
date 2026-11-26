"""#2997: cancelling a SEPA Mandate by a plain status save must record cancelled_date.

The lifecycle service only stamps the date in ``on_update``, after the row is written, so a bare
``status = "Cancelled"; save()`` left ``cancelled_date`` NULL in the DB. The mandate is created
through ``SEPAMandateManager.create_mandate`` and cancelled through the doc's own ``save()``
(the real flow); the date is read back with ``frappe.db.get_value``.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.clock_race import assert_written_today
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestMandateCancelledDateStamp2997(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Cancel",
            last_name="Stamp",
            birth_date="1990-01-01",
            email=f"cancel.stamp.{frappe.generate_hash(length=8)}@example.com",
        )
        mandate_id = f"M-2997-{frappe.generate_hash(length=8)}"
        result = get_sepa_mandate_manager().create_mandate(
            member=self.member.name,
            iban=generate_test_iban("RABO", "0123456789"),
            account_holder_name="Cancel Stamp",
            mandate_id=mandate_id,
        )
        self.assertTrue(result.valid, result.message)
        self.mandate = frappe.get_doc("SEPA Mandate", {"mandate_id": mandate_id})

    def _stored_date(self):
        return frappe.db.get_value("SEPA Mandate", self.mandate.name, "cancelled_date")

    def test_a_bare_status_save_stamps_cancelled_date_in_the_database(self):
        self.assertIsNone(self._stored_date())
        self.mandate.status = "Cancelled"
        self.mandate.save()
        assert_written_today(self, self._stored_date())

    def test_a_caller_set_date_is_kept(self):
        caller_date = add_days(today(), -3)
        self.mandate.status = "Cancelled"
        self.mandate.cancelled_date = caller_date
        self.mandate.save()
        self.assertEqual(str(self._stored_date()), str(caller_date))

    def test_a_non_cancel_save_does_not_stamp_the_date(self):
        # Draft -> Active is allowed by the transition map on develop and on #3267's branch.
        self.mandate.status = "Active"
        self.mandate.save()
        self.assertEqual(self.mandate.status, "Active")
        self.assertIsNone(self._stored_date())

    def test_a_save_that_changes_nothing_does_not_stamp_the_date(self):
        self.mandate.account_holder_name = "Cancel Stamp Renamed"
        self.mandate.save()
        self.assertIsNone(self._stored_date())

    def test_an_already_cancelled_row_is_not_restamped_by_a_later_save(self):
        self.mandate.status = "Cancelled"
        self.mandate.cancelled_date = add_days(today(), -5)
        self.mandate.save()
        self.mandate.reload()
        self.mandate.cancelled_date = None
        self.mandate.save()
        self.assertIsNone(self._stored_date())
