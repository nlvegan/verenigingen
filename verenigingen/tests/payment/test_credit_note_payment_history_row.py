"""A credit note is trackable in a member's payment history (#653).

Found while proving #649. Three separate wrongs, measured on `test_site_3` before any
of this was written:

1. `validate_entry` rejects a credit note's negative `amount`
   (`payment_history_builder.py`), so `build_payment_history_entry` returns None for
   EVERY credit note -- a return Sales Invoice has `grand_total < 0` by construction.
2. The caller answers that rejection with a hard-coded minimal entry stamped
   `payment_status = "Draft"` (`payment_history_service.py`), never reading
   `invoice.docstatus`. So a SUBMITTED credit note sat in the history labelled Draft,
   with `due_date`, `membership`, the reference and the coverage dates all dropped.
3. `determine_payment_status` short-circuits on `outstanding_amount <= 0` before it
   looks at the status, so BOTH of ERPNext's credit-note statuses collapse to "Paid":

   | document | ERPNext status | was reported as |
   |---|---|---|
   | the credit note itself | `Return` | `Paid` |
   | an invoice fully credited | `Credit Note Issued` | `Paid` |

   The second one matters most: a membership invoice that was WAIVED read exactly like
   one the member had paid. For an association that is the distinction the history
   exists to record. It is also the row #649 had just taught the app to refresh -- so
   that fix made a wrong figure fresh rather than making it right.

An against-self credit note (`update_outstanding_for_self = 1`) makes the
short-circuit's shape plain: its own `outstanding_amount` is NEGATIVE thirty euro --
money owed TO the member -- and `<= 0` reported it as Paid.

`payment_status` gains one Select option, `Credited`, used for both rows. `Refunded`
was rejected deliberately: a credit note is often a waiver or a correction, and
`Refunded` asserts money went back to the member when none may have moved.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.support.invoice_payments import build_eur_membership_invoice
from verenigingen.tests.support.payment_history_fixtures import MemberPaymentHistoryFixture
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.utils import determine_payment_status
from verenigingen.utils.payment_history_builder import PaymentHistoryEntryBuilder


class _CreditedInvoiceFixture(MemberPaymentHistoryFixture):
    """An unpaid EUR invoice, and a way to credit it either way round."""

    MEMBER_FIRST_NAME = "CreditedHistory"
    INVOICE_AMOUNT = 42.0

    def setUp(self):
        super().setUp()
        self.invoice = build_eur_membership_invoice(self, self.member.customer, rate=self.INVOICE_AMOUNT)

    def partial_credit_note(self, amount):
        """A credit note for LESS than the invoice, booked against the original.

        `make_return_doc` maps the whole invoice, so the returned line is re-rated to
        `amount`: a partial credit is a smaller negative, not a different document.
        """
        from erpnext.controllers.sales_and_purchase_return import make_return_doc

        note = make_return_doc("Sales Invoice", self.invoice.name)
        note.posting_date = today()
        note.set_posting_time = 1
        note.update_outstanding_for_self = 0
        for row in note.items:
            row.qty = -1
            row.rate = amount
        note.insert()
        self.track_test_record("Sales Invoice", note.name)
        note.submit()
        note.reload()
        return note

    def credit_note(self, update_outstanding_for_self=0):
        """A full credit note against `self.invoice`.

        `update_outstanding_for_self` is passed explicitly because the DocType field
        DEFAULTS TO 1 -- a note built the obvious way books against itself and the
        original never moves (#649).
        """
        from erpnext.controllers.sales_and_purchase_return import make_return_doc

        note = make_return_doc("Sales Invoice", self.invoice.name)
        note.posting_date = today()
        note.set_posting_time = 1
        note.update_outstanding_for_self = update_outstanding_for_self
        note.insert()
        self.track_test_record("Sales Invoice", note.name)
        note.submit()
        note.reload()
        return note


class TestACreditNoteReachesTheMembersHistory(_CreditedInvoiceFixture):
    def test_the_credit_notes_own_row_is_written_and_is_not_labelled_draft(self):
        """The defect as reported: a submitted credit note read as a Draft.

        Pinned to "Credited" rather than `assertNotEqual(..., "Draft")` -- the loose
        form passes for "Paid", which is what this row said the moment the Draft
        fallback stopped firing, and "Paid" on a -42.00 row is the next wrong answer.
        """
        note = self.credit_note()
        self.drain()

        row = self.history_row(note.name)
        self.assertEqual(flt(row.amount), -self.INVOICE_AMOUNT)
        self.assertEqual(row.payment_status, "Credited")

    def test_the_credit_notes_row_is_fully_built_not_the_minimal_fallback(self):
        """The fallback dropped every field the real builder computes.

        `due_date` is the discriminator: the minimal entry carried `invoice`,
        `posting_date`, `amount`, `outstanding_amount` and `payment_status` only, so a
        row with a due date cannot have come from it.
        """
        note = self.credit_note()
        self.drain()

        row = self.history_row(note.name)
        self.assertTrue(row.due_date, "the row came from the minimal rejection fallback")
        self.assertEqual(row.invoice_doctype, "Sales Invoice")

    def test_a_non_membership_credit_note_is_classified_too(self):
        """The `else` branch, proven untested by a surviving mutation.

        Every other integration test here uses `is_membership_invoice = 1`, and the
        `validate_entry` tests pass `transaction_type="Credit Note"` as a LITERAL, so
        nothing exercised the producer's non-membership path. Mutating `else "Credit
        Note"` to `else "Regular Invoice"` stayed green across 63 tests in 5 suites --
        while making a credit note against a member's donation or merchandise invoice
        fail the new sign rule and degrade to the minimal fallback, i.e. exactly the
        defect this whole change exists to fix.
        """
        invoice = build_eur_membership_invoice(self, self.member.customer, rate=25.0)
        frappe.db.set_value("Sales Invoice", invoice.name, "is_membership_invoice", 0, update_modified=False)

        from erpnext.controllers.sales_and_purchase_return import make_return_doc

        note = make_return_doc("Sales Invoice", invoice.name)
        note.posting_date = today()
        note.set_posting_time = 1
        note.update_outstanding_for_self = 0
        note.insert()
        self.track_test_record("Sales Invoice", note.name)
        note.submit()

        self.drain()

        row = self.history_row(note.name)
        self.assertEqual(row.transaction_type, "Credit Note")
        self.assertEqual(row.payment_status, "Credited")
        self.assertEqual(flt(row.amount), -25.0)

    def test_the_credit_note_is_distinguishable_from_an_invoice(self):
        """Trackable means more than present: a reader must be able to tell which
        rows reduced what the member owed."""
        note = self.credit_note()
        self.drain()

        self.assertEqual(self.history_row(note.name).transaction_type, "Membership Credit Note")
        self.assertEqual(self.history_row(self.invoice.name).transaction_type, "Membership Invoice")

    def test_writing_the_credit_notes_row_logs_no_validation_error(self):
        """The regression guard for the rejection itself.

        `assertNoErrorLog` rather than leaving it to the automatic tearDown check: that
        check is gated on `VERENIGINGEN_FAIL_ON_ERROR_LOG` and only WARNED here -- this
        test passed against the unfixed tree while printing the very error it forbids.
        The explicit form always fails.
        """
        self.credit_note()

        with self.assertNoErrorLog():
            self.drain()


class TestAWaivedInvoiceDoesNotReadAsPaid(_CreditedInvoiceFixture):
    def test_a_fully_credited_invoice_is_credited_not_paid(self):
        """The row #649 taught the app to refresh -- refreshed to the wrong label.

        ERPNext sets the original's status to "Credit Note Issued"; the history said
        "Paid", so a waived membership invoice was indistinguishable from a paid one.
        """
        self.drain()
        self.assertEqual(self.history_row(self.invoice.name).payment_status, "Unpaid")

        self.credit_note()
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", self.invoice.name, "status"),
            "Credit Note Issued",
            "premise: ERPNext must mark the original credited",
        )
        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(flt(row.outstanding_amount), 0.0)
        self.assertEqual(row.payment_status, "Credited")

    def test_a_credit_note_owing_the_member_money_is_not_paid(self):
        """`update_outstanding_for_self = 1` leaves the NOTE carrying the outstanding.

        Its `outstanding_amount` is -42.00 -- owed to the member -- and the
        `outstanding_amount <= 0` short-circuit called that Paid.
        """
        note = self.credit_note(update_outstanding_for_self=1)
        self.assertEqual(
            flt(note.outstanding_amount), -self.INVOICE_AMOUNT, "premise: the note owes the member"
        )
        self.drain()

        self.assertEqual(self.history_row(note.name).payment_status, "Credited")


class TestDeterminePaymentStatusHandlesCreditNotes(MemberPaymentHistoryFixture):
    """Unit-level, so each branch is pinned independently of the ledger that produces it."""

    MEMBER_FIRST_NAME = "CreditedStatus"

    @staticmethod
    def _status_shim(status, outstanding, grand_total=42.0, docstatus=1):
        return frappe._dict(
            docstatus=docstatus, status=status, outstanding_amount=outstanding, grand_total=grand_total
        )

    def test_a_return_is_credited(self):
        self.assertEqual(determine_payment_status(self._status_shim("Return", 0.0, -42.0), 0.0), "Credited")

    def test_a_credit_note_issued_invoice_is_credited(self):
        self.assertEqual(determine_payment_status(self._status_shim("Credit Note Issued", 0.0), 0.0), "Credited")

    def test_a_draft_return_is_still_draft(self):
        """docstatus wins: an unsubmitted credit note has not credited anything yet."""
        self.assertEqual(
            determine_payment_status(self._status_shim("Return", 0.0, -42.0, docstatus=0), 0.0), "Draft"
        )

    def test_an_ordinary_paid_invoice_is_unaffected(self):
        self.assertEqual(determine_payment_status(self._status_shim("Paid", 0.0), 42.0), "Paid")

    def test_an_ordinary_zero_outstanding_invoice_is_still_paid(self):
        """The short-circuit this change reaches past must survive for everything else."""
        self.assertEqual(determine_payment_status(self._status_shim("Unpaid", 0.0), 42.0), "Paid")


class TestValidateEntryStillRejectsNegativesThatAreNotCreditNotes(MemberPaymentHistoryFixture):
    """The control for the validation relaxation.

    Allowing a credit note's negative amount must not become "negatives are fine": a
    negative on an ordinary invoice row is still a bug worth refusing.
    """

    MEMBER_FIRST_NAME = "CreditedValidate"

    @staticmethod
    def _entry(**overrides):
        entry = {
            "invoice": "ACC-SINV-TEST",
            "posting_date": today(),
            "amount": 42.0,
            "outstanding_amount": 42.0,
            "payment_status": "Unpaid",
            "transaction_type": "Regular Invoice",
        }
        entry.update(overrides)
        return entry

    def test_a_negative_amount_on_an_ordinary_invoice_is_still_rejected(self):
        ok, errors = PaymentHistoryEntryBuilder.validate_entry(self._entry(amount=-42.0))
        self.assertFalse(ok)
        self.assertIn("amount cannot be negative", errors)

    def test_a_negative_outstanding_on_an_ordinary_invoice_is_still_rejected(self):
        ok, errors = PaymentHistoryEntryBuilder.validate_entry(self._entry(outstanding_amount=-42.0))
        self.assertFalse(ok)
        self.assertIn("outstanding_amount cannot be negative", errors)

    def test_a_credit_note_may_carry_both_negative(self):
        ok, errors = PaymentHistoryEntryBuilder.validate_entry(
            self._entry(
                amount=-42.0,
                outstanding_amount=-42.0,
                payment_status="Credited",
                transaction_type="Credit Note",
            )
        )
        self.assertTrue(ok, f"a credit note must validate; got {errors}")

    def test_a_credit_note_with_a_positive_amount_is_rejected(self):
        """The relaxation is not a blanket exemption -- a credit note whose amount is
        positive is as wrong as an invoice whose amount is negative."""
        ok, errors = PaymentHistoryEntryBuilder.validate_entry(
            self._entry(amount=42.0, payment_status="Credited", transaction_type="Credit Note")
        )
        self.assertFalse(ok)
        self.assertIn("a credit note's amount must not be positive", errors)


class TestTheRejectionFallbackDoesNotInventAStatus(_CreditedInvoiceFixture):
    """The last-resort row must not claim a docstatus it never read.

    Separate from everything above because it survives the rest of this fix: once
    `validate_entry` accepts credit notes the fallback is no longer REACHED by one, so
    nothing else here can tell whether it still lies. A mutation proved that -- putting
    the literal `"Draft"` back left all 15 tests green.

    The fallback still matters. Any future rejection -- a new validation rule, a
    transient failure in the coverage lookup -- silently rewrote a SUBMITTED invoice's
    row as a draft, indistinguishable from one that really is a draft.
    """

    MEMBER_FIRST_NAME = "CreditedFallback"

    def test_a_submitted_invoice_that_fails_to_build_is_not_reported_as_draft(self):
        """Drives the real service with only the builder stubbed out.

        The stub is the seam where a rejection happens, not the logic under test: what
        is asserted is what the SERVICE does with a rejection.
        """
        from verenigingen.services.member.payment.payment_history_service import (
            get_payment_history_service,
        )

        invoice = frappe.get_doc("Sales Invoice", self.invoice.name)
        self.assertEqual(invoice.docstatus, 1, "premise: the invoice is submitted")

        with patch(
            "verenigingen.utils.payment_history_builder.build_payment_history_entry", return_value=None
        ):
            entry = get_payment_history_service().build_payment_history_entry(
                invoice, member_doc=frappe.get_doc("Member", self.member.name)
            )

        self.assertEqual(
            entry["payment_status"],
            "Unpaid",
            "the fallback stamped a status it never read off the document",
        )
        self.assertEqual(flt(entry["amount"]), self.INVOICE_AMOUNT)

    def test_the_fallback_reports_a_credited_invoice_as_credited(self):
        """The same seam, on the document this issue is about."""
        from verenigingen.services.member.payment.payment_history_service import (
            get_payment_history_service,
        )

        self.credit_note()
        invoice = frappe.get_doc("Sales Invoice", self.invoice.name)

        with patch(
            "verenigingen.utils.payment_history_builder.build_payment_history_entry", return_value=None
        ):
            entry = get_payment_history_service().build_payment_history_entry(
                invoice, member_doc=frappe.get_doc("Member", self.member.name)
            )

        self.assertEqual(entry["payment_status"], "Credited")


class TestTheSchemaAllowsEveryStatusTheCodeWrites(MemberPaymentHistoryFixture):
    """The only gate on the DocType half of this change.

    Measured: reverting the Select option and reloading the DocType left every other
    test here GREEN. There are TWO independent reasons for that and the measurement
    cannot tell them apart, so both are stated rather than the convenient one:
    `update_child_table` (`frappe/model/document.py:654`) ends in `db_update()` and
    never calls `_validate()`, AND `_validate_selects` returns immediately under
    `frappe.flags.in_import`, which `EnhancedTestCase.setUp` sets. Either way no
    behavioural test in this harness can catch a missing option.

    It matters more than "the desk renders it blank". In PRODUCTION `in_import` is
    False, and `member_history_update_service.py:261` refreshes history with a real
    `member_doc.save()` -- which DOES run `_validate_selects` on the child rows. A
    missing option there throws, is swallowed by that method's own handler, and turns
    the entire history refresh into a silent failure.

    So this asserts the CONSISTENCY of the two halves rather than either alone: every
    status the builder is willing to emit must be a status the schema allows. It fails
    in both directions -- adding a status in code without the option, or removing the
    option while code still writes it.
    """

    MEMBER_FIRST_NAME = "CreditedSchema"

    def test_every_status_the_builder_emits_is_a_valid_select_option(self):
        field = frappe.get_meta("Member Payment History").get_field("payment_status")
        self.assertEqual(field.fieldtype, "Select", "premise: the gate only means anything on a Select")
        options = set(field.options.split("\n"))

        self.assertIn("Credited", options, "the DocType lost the option this fix writes")

        missing = PaymentHistoryEntryBuilder.VALID_PAYMENT_STATUSES - options
        self.assertEqual(
            missing,
            set(),
            f"the builder emits statuses the DocType does not allow: {sorted(missing)}",
        )

    def test_every_status_the_deriver_can_return_is_one_the_validator_allows(self):
        """The link the bug actually ran through, which the check above does NOT gate.

        `VALID_PAYMENT_STATUSES` is the VALIDATOR's allow-list, not a producer. The
        producer is `determine_payment_status`. Teach it a new status without adding it
        to the allow-list and `validate_entry` rejects the entry, the caller substitutes
        the minimal fallback, and the row silently degrades -- #653 again, from the
        other end.

        The returns are enumerated from the function's own source rather than by calling
        it, so the test cannot miss a branch whose inputs it failed to imagine.
        """
        import ast
        import inspect

        import verenigingen.utils as utils_module

        tree = ast.parse(inspect.getsource(utils_module.determine_payment_status))
        returned = {
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
        }

        self.assertIn("Credited", returned, "premise: the deriver must actually be able to return it")
        self.assertGreater(len(returned), 3, "premise: the source walk found suspiciously few branches")

        unlisted = returned - PaymentHistoryEntryBuilder.VALID_PAYMENT_STATUSES
        self.assertEqual(
            unlisted,
            set(),
            f"determine_payment_status can return statuses validate_entry rejects: {sorted(unlisted)}",
        )


class TestTheMemberPortalAgreesWithTheDeskGrid(_CreditedInvoiceFixture):
    """The same decision, made the other way, one layer out (#653).

    `PaymentStatus.PAID_STATUSES` contains "Credit Note Issued" because it means
    SETTLED, and the member-facing dashboard mapped everything in that set to "Paid".
    So fixing only `determine_payment_status` would have left the desk grid saying
    "Credited" and the member's own portal saying "Paid" for the same invoice -- the
    exact conflation this change exists to remove, surviving in the place the MEMBER
    looks.

    The set itself is deliberately left alone: its other consumer,
    `dues_schedule_manager`, asks "should we still chase this?" and must keep answering
    NO for a credited invoice. A waived member must not become collectable again. Two
    questions, one constant; the portal branches before consulting it.
    """

    MEMBER_FIRST_NAME = "CreditedPortal"

    def _portal_rows(self):
        """The rows the member's own dashboard renders, keyed by invoice.

        The endpoint returns a SERIALIZED OperationResult -- a plain dict with the rows
        under "data" -- not the object. Reading `.data` off it silently yields the dict's
        KEYS instead, which is a shape that makes an assertion pass or fail for reasons
        having nothing to do with the status, so `success` is asserted here.
        """
        from verenigingen.api.payment_dashboard import get_payment_history

        result = get_payment_history(member=self.member.name)
        self.assertTrue(result.get("success"), f"the portal endpoint failed: {result}")
        rows = result.get("data") or []
        return {r["id"]: r for r in rows if r.get("type") == "invoice"}

    def test_a_waived_invoice_is_not_shown_to_the_member_as_paid(self):
        self.credit_note()
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", self.invoice.name, "status"),
            "Credit Note Issued",
            "premise: ERPNext must mark the original credited",
        )

        row = self._portal_rows().get(self.invoice.name)
        self.assertIsNotNone(row, "the invoice must appear in the member's own payment history")
        self.assertEqual(row["status"], "Credited")

    def test_an_ordinary_unpaid_invoice_is_unaffected(self):
        """The control: the branch must not swallow everything on its way past."""
        row = self._portal_rows().get(self.invoice.name)
        self.assertIsNotNone(row)
        self.assertNotEqual(row["status"], "Credited")


class TestAPartlyCreditedPartlyPaidInvoiceIsDistinguishable(_CreditedInvoiceFixture):
    """"Credited" must not swallow an invoice the member actually paid most of.

    ERPNext sets "Credit Note Issued" for ANY credit note against the invoice once
    outstanding reaches 0 -- it is not "fully credited". So a EUR 42 membership invoice
    with a EUR 10 goodwill credit, whose remaining EUR 32 the member then PAYS, lands on
    the same status as one that was waived outright. Reporting both as "Credited" hides
    a real payment exactly as reporting both as "Paid" hid a real waiver.

    Order matters and is asserted as a premise: credit FIRST, then pay. Paying first and
    crediting the remainder leaves the invoice on "Paid", a different branch entirely.
    """

    MEMBER_FIRST_NAME = "PartCredited"
    CREDIT_AMOUNT = 10.0

    def _pay(self, amount):
        from verenigingen.tests.support.invoice_payments import receive_against_invoice

        _, payment = receive_against_invoice(self, self.invoice.name, amount)
        self.track_test_record("Payment Entry", payment.name)
        return payment

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # receive_against_invoice READS Company.default_bank_account.
        get_eur_bank_account(get_eur_test_company())

    def test_the_member_paid_most_of_it_and_the_row_says_so(self):
        note = self.partial_credit_note(self.CREDIT_AMOUNT)
        self.assertEqual(flt(note.grand_total), -self.CREDIT_AMOUNT, "premise: a PARTIAL credit")
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")),
            self.INVOICE_AMOUNT - self.CREDIT_AMOUNT,
            "premise: the credit reduced but did not clear the invoice",
        )

        self._pay(self.INVOICE_AMOUNT - self.CREDIT_AMOUNT)
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", self.invoice.name, "status"),
            "Credit Note Issued",
            "premise: ERPNext uses the same status it uses for a fully waived invoice",
        )

        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(row.payment_status, "Partially Credited")
        self.assertEqual(flt(row.paid_amount), self.INVOICE_AMOUNT - self.CREDIT_AMOUNT)
        self.assertEqual(flt(row.outstanding_amount), 0.0)

    def test_a_waived_invoice_is_still_plain_credited(self):
        """The control: the new branch must not swallow the waiver case it sits beside."""
        self.credit_note()
        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(row.payment_status, "Credited")
        self.assertEqual(flt(row.paid_amount), 0.0)

    def test_the_member_portal_makes_the_same_distinction(self):
        """Desk and portal disagreeing is what the last round of this fix was about."""
        from verenigingen.api.payment_dashboard import get_payment_history

        self.partial_credit_note(self.CREDIT_AMOUNT)
        self._pay(self.INVOICE_AMOUNT - self.CREDIT_AMOUNT)

        result = get_payment_history(member=self.member.name)
        self.assertTrue(result.get("success"), f"the portal endpoint failed: {result}")
        rows = {r["id"]: r for r in (result.get("data") or []) if r.get("type") == "invoice"}

        self.assertEqual(rows[self.invoice.name]["status"], "Partially Credited")


class TestDeterminePaymentStatusSplitsCreditedOnPayment(MemberPaymentHistoryFixture):
    """Unit-level, so each branch is pinned independently of the ledger."""

    MEMBER_FIRST_NAME = "PartCreditedUnit"

    @staticmethod
    def _credited_shim(status="Credit Note Issued", outstanding=0.0, grand_total=42.0):
        return frappe._dict(
            docstatus=1, status=status, outstanding_amount=outstanding, grand_total=grand_total
        )

    def test_credited_with_a_payment_is_partially_credited(self):
        self.assertEqual(determine_payment_status(self._credited_shim(), 32.0), "Partially Credited")

    def test_credited_with_no_payment_is_credited(self):
        self.assertEqual(determine_payment_status(self._credited_shim(), 0.0), "Credited")

    def test_the_credit_note_itself_is_never_partially_credited(self):
        """A "Return" IS the credit; it is not a thing that was partly credited."""
        self.assertEqual(
            determine_payment_status(self._credited_shim(status="Return", grand_total=-42.0), 32.0),
            "Credited",
        )
