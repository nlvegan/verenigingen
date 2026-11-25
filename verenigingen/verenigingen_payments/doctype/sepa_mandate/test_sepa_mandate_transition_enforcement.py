"""#3179: an invalid SEPA Mandate status transition is refused in validate."""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.doctype.sepa_mandate.test_sepa_mandate import create_test_member


class TestSEPAMandateTransitionEnforcement(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = create_test_member()

    def _mandate_in_status(self, status):
        """Insert a mandate directly in `status` (a new doc is not a transition)."""
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-3179-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": status,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "used_for_memberships": 1,
            }
        )
        doc.insert()
        self.track_doc("SEPA Mandate", doc.name)
        return doc

    def test_draft_to_suspended_is_refused_and_not_persisted(self):
        mandate = self._mandate_in_status("Draft")
        mandate.status = "Suspended"
        with self.assertRaises(frappe.ValidationError) as ctx:
            mandate.save()
        self.assertIn("Draft", str(ctx.exception))
        self.assertIn("Suspended", str(ctx.exception))
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Draft")

    def test_active_to_suspended_is_allowed(self):
        """Control: a valid transition still saves."""
        mandate = self._mandate_in_status("Active")
        mandate.status = "Suspended"
        mandate.save()
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Suspended")

    def test_cancelled_to_active_is_refused(self):
        """Terminal state: was silently reset by enforce_terminal_status, now a refusal."""
        mandate = self._mandate_in_status("Draft")
        mandate.status = "Cancelled"
        mandate.save()
        mandate.status = "Active"
        with self.assertRaises(frappe.ValidationError):
            mandate.save()
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Cancelled")

    def test_unrelated_save_keeps_status_and_passes(self):
        """Control: same status is not a transition."""
        mandate = self._mandate_in_status("Active")
        mandate.notes = "touched"
        mandate.save()
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Active")

    def test_date_derived_expiry_on_unrelated_save_is_not_refused(self):
        """A status the DATE rules derive is not a caller-requested transition.

        Probe shortcut: the past expiry_date is written with db.set_value to stand
        in for time passing. Starts from Draft because Draft -> Expired is NOT in the
        transition map: that makes the test fail if the check ever runs after the
        date derivation (Active -> Expired is valid and would hide it).
        """
        mandate = self._mandate_in_status("Draft")
        frappe.db.set_value(
            "SEPA Mandate",
            mandate.name,
            {
                "sign_date": frappe.utils.add_days(today(), -30),
                "expiry_date": frappe.utils.add_days(today(), -1),
            },
        )
        mandate.reload()
        mandate.notes = "unrelated edit"
        mandate.save()
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Expired")

    def test_future_sign_date_keeps_draft_not_pending(self):
        """Pending is not a SEPA Mandate status option (ruling 2026-11-24): a future
        sign_date used to force "Pending" through set_status_based_on_dates.

        Service-level on a real persisted mandate: save() refuses a future sign_date
        ("Sign date cannot be in the future"), so the rule is only reachable directly.
        """
        from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
            SEPAMandateLifecycleService,
        )

        mandate = self._mandate_in_status("Draft")
        mandate.sign_date = frappe.utils.add_days(today(), 10)
        self.assertEqual(SEPAMandateLifecycleService().set_status_based_on_dates(mandate), "Draft")
