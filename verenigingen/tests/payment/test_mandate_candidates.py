"""Guard tests for `unambiguous_active_mandate` (#584).

The property under test is not "does it find a mandate" but "are its three outcomes
distinguishable": one mandate, none at all, and a REFUSAL. Collapsing the last two is
the mistake this repo has already paid for -- a caller that reads a falsy return as
"nothing here" goes on to create what is missing, which is how #585 billed a member a
third period.

Two Active mandates are no longer reachable through save() since
`SEPAMandate.validate_single_active_mandate`, so the ambiguous fixture is built with
`frappe.db.set_value`, which writes the column without running `validate`. That is not
a trick to make the test work: it is the exact route that keeps the ambiguous state
reachable in production, and therefore the reason this helper refuses rather than
trusting the guard.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.mandate_candidates import unambiguous_active_mandate

REFUSAL_TITLE = "Test: ambiguous mandate"


class TestUnambiguousActiveMandate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="MandateCand", last_name="Test")

    def _make_mandate(self, iban, status="Active"):
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"CAND-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": today(),
                "status": "Draft" if status == "Active" else status,
                "is_active": 0,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        mandate.insert()
        if status == "Active":
            # Bypasses `validate`, which is the point -- see the module docstring.
            frappe.db.set_value(
                "SEPA Mandate", mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
            )
            mandate.reload()
        return mandate

    def test_one_active_mandate_is_returned(self):
        mandate = self._make_mandate("NL91ABNA0417164300")

        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertTrue(choice)
        self.assertFalse(choice.is_ambiguous)
        self.assertEqual(choice.mandate.name, mandate.name)
        self.assertEqual(choice.candidates, 1)

    def test_no_active_mandate_is_not_a_refusal(self):
        """Nothing found and refusing to choose must not look the same to a caller."""
        self._make_mandate("NL91ABNA0417164300", status="Cancelled")

        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertFalse(choice)
        self.assertIsNone(choice.mandate)
        self.assertFalse(choice.is_ambiguous, "an empty result was reported as a refusal")
        self.assertEqual(choice.candidates, 0)

    def test_two_active_mandates_are_refused_not_ordered(self):
        self.expectErrorLog(REFUSAL_TITLE)
        first = self._make_mandate("NL91ABNA0417164300")
        second = self._make_mandate("NL39RABO0300065264")

        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertFalse(choice, "a mandate was chosen from an ambiguous set")
        self.assertTrue(choice.is_ambiguous)
        self.assertEqual(choice.candidates, 2)
        # The specific failure being guarded against is `creation DESC` handing back
        # the newest anyway. Asserting only `is_ambiguous` would pass for a helper
        # that returned the newest AND set the flag, so pin the mandate itself.
        # (Comparing `choice.mandate.name` to either fixture would be tautological
        # once it is None -- this is the assertion that carries the weight.)
        self.assertIsNone(choice.mandate, f"chose between {first.mandate_id} and {second.mandate_id}")

    def test_the_refusal_reaches_an_operator_with_both_candidates_named(self):
        """A refusal nobody can see is the same as a silent wrong answer.

        Error Log has no `title` column: `frappe.log_error(title=...)` lands in
        **`method`**, and the body in `error`. That is exactly why the keyword form
        matters -- called positionally, the long message goes into `method`, a Data
        column truncated at 140 characters, and the list view becomes unreadable.
        Filtering on `method` here pins that the title reached the right column.
        """
        self.expectErrorLog(REFUSAL_TITLE)
        first = self._make_mandate("NL91ABNA0417164300")
        second = self._make_mandate("NL39RABO0300065264")
        before = frappe.db.count("Error Log", {"method": REFUSAL_TITLE})

        unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertEqual(
            frappe.db.count("Error Log", {"method": REFUSAL_TITLE}),
            before + 1,
            "the refusal did not reach the Error Log under its own title",
        )
        logs = frappe.get_all(
            "Error Log",
            filters={"method": REFUSAL_TITLE},
            fields=["error"],
            order_by="creation desc",
            limit=1,
        )
        message = logs[0].error
        self.assertIn(first.mandate_id, message)
        self.assertIn(second.mandate_id, message)
        self.assertIn(self.member.name, message)

    def test_a_member_with_no_mandates_at_all(self):
        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertFalse(choice)
        self.assertFalse(choice.is_ambiguous)
        self.assertEqual(choice.candidates, 0)

    def test_an_empty_member_is_not_a_refusal(self):
        """Guards the `if not member` short-circuit: no member is not ambiguity."""
        choice = unambiguous_active_mandate("", REFUSAL_TITLE)

        self.assertFalse(choice)
        self.assertFalse(choice.is_ambiguous)
        self.assertEqual(choice.candidates, 0)
