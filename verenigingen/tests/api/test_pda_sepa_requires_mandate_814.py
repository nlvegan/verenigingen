"""#814: Periodic Donation Agreement.validate() refuses SEPA Direct Debit with no mandate.

#781/#776 guard two boundaries (create_periodic_agreement, the web form); the model
itself had no invariant. These tests drive the REAL save path (new_doc + insert/save)
with real Donor and SEPA Mandate rows, which is what a Desk form, import, patch or job
does. Only presence of a mandate is asserted: what makes a mandate "valid" (status,
owner) is an open question on the issue and deliberately not enforced here.
"""

from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
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

    def _plant_legacy_active_sepa_row_814(self):
        """Probe shortcut: db.set_value plants the pre-#814 production state (Active, SEPA, no mandate)."""
        agreement = self._new_pda_for_814()
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        frappe.db.set_value(
            "Periodic Donation Agreement",
            agreement.name,
            {"payment_method": "SEPA Direct Debit", "status": "Active", "workflow_state": "Active"},
        )
        return frappe.get_doc("Periodic Donation Agreement", agreement.name)

    def test_cancel_agreement_works_on_a_legacy_active_mandate_less_sepa_row(self):
        legacy = self._plant_legacy_active_sepa_row_814()
        self.assertTrue(legacy.meta.get_workflow())
        legacy.cancel_agreement(reason="legacy cleanup")
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", legacy.name, "status"), "Cancelled")

    def test_cancel_agreement_without_a_workflow_works_on_a_legacy_active_row(self):
        legacy = self._plant_legacy_active_sepa_row_814()
        with patch.object(type(legacy.meta), "get_workflow", return_value=None):
            legacy.cancel_agreement(reason="legacy cleanup")
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", legacy.name, "status"), "Cancelled")

    def test_workflow_cancel_action_works_on_a_legacy_active_row(self):
        legacy = self._plant_legacy_active_sepa_row_814()
        legacy.cancellation_reason = "legacy cleanup"
        legacy.cancellation_date = today()
        frappe.db.set_value(
            "Periodic Donation Agreement", legacy.name, "cancellation_reason", "legacy cleanup"
        )
        legacy.reload()
        apply_workflow(legacy, "Cancel Agreement")
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", legacy.name, "status"), "Cancelled")

    def test_direct_status_to_cancelled_save_works_on_a_legacy_active_row(self):
        legacy = self._plant_legacy_active_sepa_row_814()
        legacy.status = "Cancelled"
        legacy.save()
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", legacy.name, "status"), "Cancelled")

    def test_a_legacy_active_row_is_still_refused_for_any_other_save(self):
        legacy = self._plant_legacy_active_sepa_row_814()
        legacy.annual_amount = 1300
        with self.assertRaises(frappe.ValidationError):
            legacy.save()
        self.assertEqual(frappe.db.get_value("Periodic Donation Agreement", legacy.name, "status"), "Active")

    def test_payment_method_defaults_to_bank_transfer(self):
        self.assertEqual(frappe.new_doc("Periodic Donation Agreement").payment_method, "Bank Transfer")

    def test_insert_omitting_payment_method_succeeds_without_a_mandate(self):
        agreement = self._new_pda_for_814()
        agreement.payment_method = None
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        self.assertEqual(agreement.payment_method, "Bank Transfer")
