"""#2600: an existing Expense Claim's ``employee`` can be changed only by staff or by an approver
who may already see the STORED claim.

Frappe judges write permission on the in-memory, already-modified doc, so a claimant who may write
their own claims could re-point someone else's Draft at themselves. The guard sits in the Expense
Claim validate hook and compares against ``get_doc_before_save()``, so it is keyed on neither the
write path (save, ``set_value``, ``client.save``, bulk update) nor on ``custom_chapter`` being set.

Attackers are real users with the Volunteer profile's roles; nothing runs as Administrator.
Probe shortcuts, stated: none beyond the #2528 fixtures it reuses (Chapter Member rows are inserted
directly there).
"""

from unittest.mock import patch

import frappe
from frappe.desk.doctype.bulk_update.bulk_update import submit_cancel_or_update_docs

from verenigingen.tests.security.test_member_files_chapter_claim_2528 import MemberClaimBase

PERMISSION = (frappe.PermissionError, frappe.ValidationError)


class TestExpenseClaimEmployeeTakeover(MemberClaimBase):
    def setUp(self):
        super().setUp()
        self.peer, self.peer_emp, _member, _vol = self._person("peer2600")
        self.chapterless = self.act_as(self.user, lambda: frappe.get_doc(self.claim_data()).insert())
        self.join(self.member.name, self.chapter)
        self.attributed = self.file_as(self.user, self.chapter)
        self.staff = self._staffexp_user("Verenigingen Staff", "stf2600", extra_roles=("Verenigingen Administrator",))
        self.staff_emp = self._staffexp_employee(self.staff)

    def _employee_of(self, claim):
        return frappe.db.get_value("Expense Claim", claim.name, "employee")

    def _refused(self, claim, fn):
        with self.assertRaises(PERMISSION):
            fn()
        self.assertEqual(self._employee_of(claim), self.employee.name)

    def test_a_peer_cannot_take_over_a_chapterless_claim_with_set_value(self):
        self._refused(
            self.chapterless,
            lambda: self.act_as(
                self.peer,
                lambda: frappe.client.set_value("Expense Claim", self.chapterless.name, "employee", self.peer_emp.name),
            ),
        )

    def test_a_peer_cannot_take_over_with_save_or_client_save(self):
        def doc_save():
            doc = frappe.get_doc("Expense Claim", self.chapterless.name)
            doc.employee = self.peer_emp.name
            doc.save()

        self._refused(self.chapterless, lambda: self.act_as(self.peer, doc_save))
        data = frappe.get_doc("Expense Claim", self.chapterless.name).as_dict()
        data["employee"] = self.peer_emp.name
        self._refused(self.chapterless, lambda: self.act_as(self.peer, lambda: frappe.client.save(data)))

    def test_a_peer_cannot_clear_the_chapter_and_take_over_in_one_save(self):
        def takeover():
            doc = frappe.get_doc("Expense Claim", self.attributed.name)
            doc.custom_chapter = None
            doc.employee = self.peer_emp.name
            doc.save()

        self._refused(self.attributed, lambda: self.act_as(self.peer, takeover))
        self.assertEqual(frappe.db.get_value("Expense Claim", self.attributed.name, "custom_chapter"), self.chapter.name)

    def test_a_peer_cannot_take_over_through_bulk_update(self):
        """``_bulk_action`` commits on success and ROLLS BACK everything on failure, which would
        erase this test's uncommitted fixtures, so ``commit``/``rollback`` are stubbed (stated
        probe shortcut). The signal is the ``failed`` list it returns plus the stored employee."""
        for claim in (self.chapterless, self.attributed):
            with self.subTest(claim=claim.name):
                data = {"employee": self.peer_emp.name, "custom_chapter": None}
                with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
                    failed = self.act_as(
                        self.peer, lambda: submit_cancel_or_update_docs("Expense Claim", [claim.name], "update", data)
                    )
                self.assertEqual(failed, [claim.name])
                self.assertEqual(self._employee_of(claim), self.employee.name)

    def test_the_claimant_cannot_hand_their_own_claim_to_a_peer(self):
        self._refused(
            self.chapterless,
            lambda: self.act_as(
                self.user,
                lambda: frappe.client.set_value("Expense Claim", self.chapterless.name, "employee", self.peer_emp.name),
            ),
        )

    def test_the_refusal_matches_a_peer_editing_a_claim_they_cannot_write(self):
        """No new existence oracle: re-pointing and editing a stranger's claim refuse alike."""

        def refusal(values):
            before = len(frappe.local.message_log)
            with self.assertRaises(frappe.PermissionError) as raised:
                self.act_as(
                    self.peer,
                    lambda: frappe.client.set_value("Expense Claim", self.chapterless.name, values),
                )
            del frappe.local.message_log[before:]
            return type(raised.exception), str(raised.exception)

        takeover = refusal({"employee": self.peer_emp.name})
        plain_edit = refusal({"remark": "not mine"})
        self.assertEqual(takeover, plain_edit)

    def test_control_the_claimant_still_edits_ordinary_fields_of_their_own_draft(self):
        def edit():
            doc = frappe.get_doc("Expense Claim", self.chapterless.name)
            doc.remark = "mine"
            doc.save()

        self.act_as(self.user, edit)
        self.assertEqual(frappe.db.get_value("Expense Claim", self.chapterless.name, "remark"), "mine")

    # Plain Staff alone cannot write another employee's claim at all (Frappe's own check, #1606), so the
    # staff control carries Verenigingen Administrator: a role in both ADMIN_ROLES and full claim access.
    def test_control_staff_can_still_reassign(self):
        for claim in (self.chapterless, self.attributed):
            with self.subTest(claim=claim.name):
                self.act_as(
                    self.staff,
                    lambda: frappe.client.set_value("Expense Claim", claim.name, "employee", self.peer_emp.name),
                )
                self.assertEqual(self._employee_of(claim), self.peer_emp.name)

    def test_control_an_approver_who_sees_the_stored_claim_can_reassign(self):
        # the chapter's financial seat holder holds Expense Approver and sees the attributed claim
        self.act_as(
            self.fin_user,
            lambda: frappe.client.set_value("Expense Claim", self.attributed.name, "employee", self.peer_emp.name),
        )
        self.assertEqual(self._employee_of(self.attributed), self.peer_emp.name)

    def test_an_approver_who_cannot_see_the_stored_claim_cannot_take_it_over(self):
        # Expense Approver role alone is not enough: the stored claim must be theirs to see
        other_user, other_emp, _m, _v = self._person("apr2600", extra_roles=("Expense Approver",))
        self._refused(
            self.chapterless,
            lambda: self.act_as(
                other_user,
                lambda: frappe.client.set_value("Expense Claim", self.chapterless.name, "employee", other_emp.name),
            ),
        )
