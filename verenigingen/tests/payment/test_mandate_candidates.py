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
from verenigingen.verenigingen_payments.utils.mandate_candidates import (
    cancel_active_mandates,
    carry_forward_purposes,
    unambiguous_active_mandate,
)

REFUSAL_TITLE = "Test: ambiguous mandate"


class TestUnambiguousActiveMandate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="MandateCand", last_name="Test")

    def _mandate_with_purposes(self, iban, status="Active"):
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
        mandate = self._mandate_with_purposes("NL91ABNA0417164300")

        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertTrue(choice)
        self.assertFalse(choice.is_ambiguous)
        self.assertEqual(choice.mandate.name, mandate.name)
        self.assertEqual(choice.candidates, 1)

    def test_no_active_mandate_is_not_a_refusal(self):
        """Nothing found and refusing to choose must not look the same to a caller."""
        self._mandate_with_purposes("NL91ABNA0417164300", status="Cancelled")

        choice = unambiguous_active_mandate(self.member.name, REFUSAL_TITLE)

        self.assertFalse(choice)
        self.assertIsNone(choice.mandate)
        self.assertFalse(choice.is_ambiguous, "an empty result was reported as a refusal")
        self.assertEqual(choice.candidates, 0)

    def test_two_active_mandates_are_refused_not_ordered(self):
        self.expectErrorLog(REFUSAL_TITLE)
        first = self._mandate_with_purposes("NL91ABNA0417164300")
        second = self._mandate_with_purposes("NL39RABO0300065264")

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
        first = self._mandate_with_purposes("NL91ABNA0417164300")
        second = self._mandate_with_purposes("NL39RABO0300065264")
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


class TestCancelActiveMandates(EnhancedTestCase):
    """The supersede half of the one-Active-mandate invariant (#584).

    Four flows activate a mandate, and every one of them now has to cancel first.
    The property that is easy to get wrong is not the cancelling -- it is that the
    replacement must not silently NARROW what the member is collected for.
    `used_for_memberships` / `used_for_donations` / `used_for_other` are three
    independent checkboxes, so replacing a memberships mandate with a donations-only
    one would otherwise end that member's membership collections with no error.
    """

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="CancelMand", last_name="Test")

    def _active_mandate_for(self, iban, **flags):
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"CANC-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": today(),
                "status": "Draft",
                "is_active": 0,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                **flags,
            }
        )
        doc.insert()
        frappe.db.set_value(
            "SEPA Mandate", doc.name, {"status": "Active", "is_active": 1}, update_modified=False
        )
        doc.reload()
        return doc

    def test_it_cancels_the_active_mandate_and_reports_it(self):
        mandate = self._active_mandate_for("NL91ABNA0417164300")

        result = cancel_active_mandates(self.member.name, "test reason")

        self.assertEqual(result["names"], [mandate.name])
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Cancelled")
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "is_active"), 0)
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", mandate.name, "cancellation_reason"), "test reason"
        )

    def test_it_leaves_non_active_mandates_alone(self):
        """Draft siblings are how a replacement is staged -- cancelling them would
        break the very flow the guard is meant to permit."""
        draft = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"CANC-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Draft",
                "is_active": 0,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        draft.insert()

        result = cancel_active_mandates(self.member.name, "test reason")

        self.assertEqual(result["names"], [])
        self.assertEqual(frappe.db.get_value("SEPA Mandate", draft.name, "status"), "Draft")

    def test_the_purposes_of_what_it_cancelled_are_returned(self):
        self._active_mandate_for("NL91ABNA0417164300", used_for_memberships=1, used_for_donations=0)

        result = cancel_active_mandates(self.member.name, "test reason")

        self.assertEqual(result["purposes"]["used_for_memberships"], 1)
        self.assertEqual(result["purposes"]["used_for_donations"], 0)
        self.assertEqual(result["purposes"]["used_for_other"], 0)

    def test_a_donations_replacement_does_not_drop_memberships(self):
        """The silent-narrowing failure, end to end."""
        self._active_mandate_for("NL91ABNA0417164300", used_for_memberships=1, used_for_donations=0)

        superseded = cancel_active_mandates(self.member.name, "test reason")

        replacement = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"CANC-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "used_for_memberships": 0,   # a donations-only replacement
                "used_for_donations": 1,
            }
        )
        carry_forward_purposes(replacement, superseded["purposes"])
        replacement.insert()

        self.assertEqual(
            replacement.used_for_memberships,
            1,
            "the replacement dropped memberships -- this member would stop being collected",
        )
        self.assertEqual(replacement.used_for_donations, 1)

    def test_suspended_is_available_and_does_not_stamp_a_cancellation(self):
        """`create_and_link_mandate` supersedes recoverably; converging the flows
        must not quietly turn that into a terminal state (`enforce_terminal_status`
        treats Cancelled as irreversible, Suspended as not)."""
        mandate = self._active_mandate_for("NL91ABNA0417164300")

        cancel_active_mandates(self.member.name, "test reason", new_status="Suspended")

        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Suspended")
        self.assertFalse(frappe.db.get_value("SEPA Mandate", mandate.name, "cancelled_date"))

    def test_it_clears_the_way_for_the_guard(self):
        """The point of the helper: after it runs, activating a replacement works."""
        self._active_mandate_for("NL91ABNA0417164300")
        cancel_active_mandates(self.member.name, "test reason")

        replacement = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"CANC-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        replacement.insert()   # would raise if the old mandate were still Active

        self.assertEqual(replacement.status, "Active")
