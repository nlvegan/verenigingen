"""#814: Periodic Donation Agreement.validate() refuses SEPA Direct Debit with no mandate.

#781/#776 guard two boundaries (create_periodic_agreement, the web form); the model
itself had no invariant. These tests drive the REAL save path (new_doc + insert/save)
with real Donor and SEPA Mandate rows, which is what a Desk form, import, patch or job
does. Only presence of a mandate is asserted: what makes a mandate "valid" (status,
owner) is an open question on the issue and deliberately not enforced here.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPdaSepaRequiresMandate814(VereningingenTestCase):
    def _new_pda_for_814(self, **overrides):
        donor = self.create_test_donor()
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.agreement_duration_years = "3 Years (Pledge - No ANBI benefits)"
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.anbi_eligible = 0
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Draft"
        for key, value in overrides.items():
            setattr(agreement, key, value)
        return agreement

    def test_sepa_without_mandate_is_refused_on_insert(self):
        agreement = self._new_pda_for_814(payment_method="SEPA Direct Debit")
        with self.assertRaises(frappe.ValidationError) as ctx:
            agreement.insert()
        self.assertIn("SEPA", str(ctx.exception))
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": agreement.donor}))

    def test_switching_an_existing_agreement_to_sepa_without_mandate_is_refused_on_save(self):
        agreement = self._new_pda_for_814()
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        agreement.payment_method = "SEPA Direct Debit"
        with self.assertRaises(frappe.ValidationError):
            agreement.save()

    def test_control_non_sepa_agreement_saves_without_mandate(self):
        for method in ("Bank Transfer", "Other"):
            agreement = self._new_pda_for_814(payment_method=method)
            agreement.insert()
            self.track_doc("Periodic Donation Agreement", agreement.name)
            self.assertFalse(agreement.sepa_mandate)

    def test_control_sepa_with_a_real_mandate_saves(self):
        mandate = self.create_test_sepa_mandate()
        agreement = self._new_pda_for_814(payment_method="SEPA Direct Debit", sepa_mandate=mandate.name)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", agreement.name, "sepa_mandate"), mandate.name)

    def test_control_closing_a_legacy_mandate_less_sepa_agreement_is_not_blocked(self):
        """A pre-existing mandate-less SEPA row must still be closable (opposite-harm control).

        Probe shortcut: the legacy row is planted with db.set_value, since the model now
        refuses to create one; that is the state production rows from before #814 are in.
        """
        agreement = self._new_pda_for_814()
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "payment_method", "SEPA Direct Debit")
        legacy = frappe.get_doc("Periodic Donation Agreement", agreement.name)
        legacy.status = "Cancelled"
        legacy.save()
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", agreement.name, "status"), "Cancelled")
