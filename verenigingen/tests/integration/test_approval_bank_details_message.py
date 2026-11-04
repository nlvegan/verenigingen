"""#2023: an approval refused for invalid bank details tells the approver what is wrong (the IBAN, or the
account holder), not only "Bank details validation failed". Driven through submit_application -> confirm ->
approve_application; no field is set directly."""

import frappe

from verenigingen.tests.integration.test_application_record_approval import (
    IBAN,
    SUBMISSION,
    ApprovalCase,
)

BAD_IBAN = "NL00XXXX0000000000"


class TestApprovalBankDetailsMessage(ApprovalCase):
    def _refusal(self, name, user=None):
        """The message of the refusal; the application is still Pending Review and nothing was created."""
        with self.assertRaises(frappe.ValidationError) as caught:
            self._approve_as(name, user=user)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertFalse(frappe.db.get_value(SUBMISSION, name, "member"))
        member = frappe.db.get_value("Member", {"email": self.email})
        self.assertIsNone(member)
        self.assertEqual(frappe.get_all("Membership", {"member": member or ""}), [])
        self.assertEqual(frappe.get_all("Member IBAN History", {"parent": member or ""}), [])
        return str(caught.exception)

    def test_invalid_iban_names_the_iban(self):
        name = self._stage_and_confirm(iban=BAD_IBAN, bank_account_name="X Holder")
        message = self._refusal(name)
        self.assertIn("Bank details validation failed", message)
        self.assertIn("IBAN", message)
        self.assertNotIn("holder", message.lower())

    def test_invalid_iban_names_the_iban_for_a_board_member(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        name = self._stage_and_confirm(iban=BAD_IBAN, bank_account_name="X Holder")
        self.assertIn("IBAN", self._refusal(name, user=board.user))

    def test_invalid_holder_names_the_holder_not_the_iban(self):
        name = self._stage_and_confirm(iban=IBAN, bank_account_name="H")
        message = self._refusal(name)
        self.assertIn("Account holder name is too short", message)
        self.assertNotIn("Invalid IBAN", message)

    def test_blank_holder_with_a_valid_iban_still_approves(self):
        name = self._stage_and_confirm(iban=IBAN)
        result = self._approve_as(name)
        self.assertTrue(result["success"], result)
        member = frappe.get_doc("Member", result["member"])
        self.assertEqual([r.bank_account_name for r in member.iban_history], [member.full_name])

    def test_no_iban_with_bank_transfer_still_approves(self):
        name = self._stage_and_confirm(payment_method="Bank Transfer")
        result = self._approve_as(name)
        self.assertTrue(result["success"], result)
