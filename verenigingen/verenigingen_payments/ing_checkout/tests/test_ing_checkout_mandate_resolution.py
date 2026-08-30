# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""ING Checkout mandate resolution against a REAL Member document (#623).

`MandateService._get_member_sepa_mandate` read `member.sepa_mandate`. `Member` has
no such field -- it has the `sepa_mandates` child table of `Member SEPA Mandate
Link` -- and reading an attribute a Frappe Document does not have raises
`AttributeError`. Measured on test_site_1 against a real Member:

    AttributeError: 'Member' object has no attribute 'sepa_mandate'.
                    Did you mean: 'sepa_mandates'?

with `unambiguous_active_mandate` as the control returning the same member's
mandate from the same database state. The read is on line 82's path, BEFORE the
`try:` that wraps the Pay.nl call, so the whitelisted endpoint
`ing_checkout.api.mandate.create_mandate_for_member` raised out of the request
rather than returning its `{"success": False}` contract.

The existing suites did not catch it because every one of them mocks `Member` with
a `MagicMock`, on which `member.sepa_mandate` is a truthy auto-attribute. So these
tests use a real Member and a real SEPA Mandate and mock only the Pay.nl HTTP
boundary -- that is the whole point of the module.

Three outcomes are asserted separately because collapsing two of them is the
mistake this repo has already paid for: a REFUSAL (more than one Active mandate,
none chosen) reported as "no mandate found" sends the caller on to create what is
missing, which is how #585 billed a member a third period.
"""

from unittest.mock import MagicMock

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

IBAN_A = "NL91ABNA0417164300"
IBAN_B = "NL39RABO0300065264"

REFUSAL_TITLE = "ING Checkout: ambiguous SEPA mandate for member"


class TestINGCheckoutMandateResolution(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="INGMandate", last_name="Resolution")
        self.service = MandateService()
        # Pay.nl is the only thing mocked here. Asserting it was NOT called is how the
        # refusal/absent branches are pinned as "returned before any collection".
        self.client = MagicMock()
        self.client.create_mandate.return_value = {"code": "IO-1234-5678-9012"}
        self.service._client = self.client
        self.service._settings = frappe._dict(
            service_id="SL-1234-5678", terms_and_conditions_url="https://example.invalid/terms"
        )

    def _membership_mandate(self, iban, status="Active", **purposes):
        """Insert a SEPA Mandate; force `Active` through the column, not through save.

        `SEPAMandate.validate_single_active_mandate_per_purpose` blocks a second
        Active mandate on the same purpose, so the ambiguous fixture has to be built
        with `frappe.db.set_value`. That is not a trick to make the test pass: it is
        the route that keeps the ambiguous state reachable in production, and
        therefore the reason the resolver refuses instead of trusting the guard.
        """
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"INGRES-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": today(),
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "status": "Draft" if status == "Active" else status,
                "is_active": 0,
                "used_for_memberships": purposes.get("used_for_memberships", 1),
                "used_for_donations": purposes.get("used_for_donations", 0),
                "used_for_other": purposes.get("used_for_other", 0),
            }
        )
        doc.insert()
        if status == "Active":
            frappe.db.set_value(
                "SEPA Mandate", doc.name, {"status": "Active", "is_active": 1}, update_modified=False
            )
            doc.reload()
        return doc

    # -- one mandate -------------------------------------------------------

    def test_one_active_mandate_is_resolved_from_a_real_member(self):
        """#623: this raised `AttributeError` before the fix, for every member."""
        mandate = self._membership_mandate(IBAN_A)

        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertEqual(result["mandate_id"], "IO-1234-5678-9012")
        payload = self.client.create_mandate.call_args[0][0]
        # Pin the mandate that was actually collected against, not merely that one was.
        self.assertEqual(payload["reference"], mandate.name)
        self.assertEqual(payload["customer"]["bankAccount"]["iban"], mandate.iban)

    # -- no mandate --------------------------------------------------------

    def test_no_active_mandate_reports_no_mandate_and_calls_no_gateway(self):
        self._membership_mandate(IBAN_A, status="Cancelled")

        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertFalse(result["success"])
        self.assertIn("no active sepa mandate", result["error"].lower())
        self.client.create_mandate.assert_not_called()

    def test_a_member_with_no_mandate_row_at_all_is_the_same_answer(self):
        """No row and a Cancelled row are one branch, but only one of them was run.

        `unambiguous_active_mandate` returns `MandateChoice(None, 0)` for both, so this
        is the cheap half of the pair rather than a new case -- kept because #623 was
        precisely a branch nobody had ever executed.
        """
        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertFalse(result["success"])
        self.assertIn("no active sepa mandate", result["error"].lower())
        self.client.create_mandate.assert_not_called()

    # -- refusal -----------------------------------------------------------

    def test_two_active_mandates_are_refused_not_reported_as_missing(self):
        """The refusal must be its own answer, distinguishable from "none found".

        Asserting only `success is False` would pass for a resolver that reported
        the ambiguous case as "no mandate" -- which is the #585 mistake -- so this
        pins that the two error strings differ, and that neither IBAN was collected.
        """
        self.expectErrorLog(REFUSAL_TITLE)
        first = self._membership_mandate(IBAN_A)
        second = self._membership_mandate(IBAN_B)

        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertFalse(result["success"])
        self.client.create_mandate.assert_not_called()
        self.assertNotIn(
            "no active sepa mandate",
            result["error"].lower(),
            f"a refusal between {first.mandate_id} and {second.mandate_id} was reported as 'not found'",
        )
        self.assertIn("more than one", result["error"].lower())

    def test_the_refusal_reaches_an_operator_under_its_own_title(self):
        """A refusal nobody can see is the same as a silent wrong answer.

        `Error Log` has no `title` column: `frappe.log_error(title=...)` lands in
        `method`. Filtering on `method` pins that the title reached that column.
        """
        self.expectErrorLog(REFUSAL_TITLE)
        self._membership_mandate(IBAN_A)
        self._membership_mandate(IBAN_B)
        before = frappe.db.count("Error Log", {"method": REFUSAL_TITLE})

        self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertEqual(
            frappe.db.count("Error Log", {"method": REFUSAL_TITLE}),
            before + 1,
            "the ING Checkout refusal did not reach the Error Log under its own title",
        )

    # -- purpose scoping ---------------------------------------------------

    def test_a_donations_only_mandate_is_not_collected_for_membership_dues(self):
        """Pins `purpose="used_for_memberships"`.

        Without it the resolver is purpose-blind (#597) and a member holding a
        donations-only mandate would have their membership dues taken from it. This
        test is the reason the argument cannot be dropped or set to None.
        """
        self._membership_mandate(IBAN_A, used_for_memberships=0, used_for_donations=1)

        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertFalse(result["success"])
        self.assertIn("no active sepa mandate", result["error"].lower())
        self.client.create_mandate.assert_not_called()

    def test_a_mandate_without_an_iban_is_not_usable(self):
        """The error string promises "with IBAN"; an Active mandate can still lack one."""
        mandate = self._membership_mandate(IBAN_A)
        frappe.db.set_value("SEPA Mandate", mandate.name, "iban", None, update_modified=False)

        result = self.service.create_mandate_for_member(self.member.name, amount=12.50)

        self.assertFalse(result["success"])
        self.assertIn("no active sepa mandate", result["error"].lower())
        self.client.create_mandate.assert_not_called()
