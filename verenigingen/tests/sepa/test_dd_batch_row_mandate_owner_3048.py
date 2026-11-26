"""A Direct Debit Batch row's mandate must belong to the row's member (#3048 item 2).

`DirectDebitBatch.validate` only asked that SOME Active mandate carry the row's
`mandate_reference`; the row's `member` was never compared to the mandate's owner, so
any writer of the doctype could put member B's mandate on member A's row. Every row
becomes a transaction in the SEPA XML, so that debits B's account for A's invoice.

Scope: ownership only. No IBAN-equality check is made here (that decides the #615
operator-correction question raised in item 1 of the issue).

Fixtures are real members, mandates and invoices; the batches go through real
`insert()` / `save()` / `submit()`. The one shortcut is `_plant_foreign_mandate`, which
writes the child row with `frappe.db.set_value` to stand in for `update_mandate`'s
child-row `save()` (which does not run the parent's `validate`) so the SUBMIT path can
be reached with a foreign mandate already on a saved draft.
"""

import frappe

from verenigingen.tests.sepa.test_dd_batch_duplicate_invoice_guard import _DuplicateInvoiceBase
from verenigingen.verenigingen_payments.api import dd_batch_api


class TestRowMandateMustBelongToRowMember(_DuplicateInvoiceBase):
    def _row_with_other_members_mandate(self):
        """Member A's invoice row carrying member B's real Active mandate."""
        row = self._member_mandate_row(25.0, "1990-01-01")
        other = self._member_with_membership("1991-02-02")
        other_mandate = self._sepa.create_test_sepa_mandate(member=other.name, status="Active")
        self.assertNotEqual(other_mandate.member, row["member"])
        row["mandate_reference"] = other_mandate.mandate_id
        row["iban"] = other_mandate.iban
        return row, other

    def _assert_refused_without_other_member_data(self, ctx, row, other):
        message = str(ctx.exception)
        self.assertIn("does not belong", message)
        self.assertIn(row["invoice"], message)
        mandate_owner_iban = frappe.db.get_value("SEPA Mandate", {"member": other.name}, "iban")
        for leaked in (other.name, other.full_name, mandate_owner_iban, row["mandate_reference"]):
            self.assertNotIn(leaked, message)

    def test_foreign_mandate_is_refused_on_insert(self):
        row, other = self._row_with_other_members_mandate()
        batch = self._unsaved_batch([row])

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.insert()

        self._assert_refused_without_other_member_data(ctx, row, other)

    def test_foreign_mandate_is_refused_in_automated_processing_too(self):
        """`_automated_processing` downgrades sequence-type criticals to a recorded
        status that nothing reads; ownership must not take that route."""
        row, other = self._row_with_other_members_mandate()
        batch = self._unsaved_batch([row], automated=True)

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.insert()

        self._assert_refused_without_other_member_data(ctx, row, other)

    def test_resaving_a_draft_after_swapping_in_a_foreign_mandate_is_refused(self):
        row, other = self._row_with_other_members_mandate()
        own = self._member_mandate_row(30.0, "1992-03-03")
        batch = self._unsaved_batch([own])
        batch.insert()
        self._track("Direct Debit Batch", batch.name)

        batch.invoices[0].mandate_reference = row["mandate_reference"]
        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.save()

        self.assertIn("does not belong", str(ctx.exception))

    def test_submit_refuses_a_foreign_mandate_planted_on_a_saved_draft(self):
        row, other = self._row_with_other_members_mandate()
        own = self._member_mandate_row(30.0, "1992-03-03")
        batch = self._unsaved_batch([own])
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        self._plant_foreign_mandate(batch, row["mandate_reference"])

        batch = frappe.get_doc("Direct Debit Batch", batch.name)
        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.submit()

        self.assertIn("does not belong", str(ctx.exception))
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", batch.name, "docstatus"), 0)

    def test_update_mandate_resolution_to_a_foreign_mandate_does_not_apply(self):
        """The real operator route: `apply_conflict_resolutions` edits the child row
        through its own save, then saves the parent -- which must refuse."""
        row, other = self._row_with_other_members_mandate()
        own = self._member_mandate_row(30.0, "1992-03-03")
        batch = self._unsaved_batch([own])
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        entry_id = batch.invoices[0].name
        own_reference = own["mandate_reference"]

        # @handle_api_error turns the parent's refusal into a failed result rather
        # than an exception, so assert on both the result and the persisted row.
        result = dd_batch_api.apply_conflict_resolutions(
            batch.name,
            [
                {
                    "action": "update_mandate",
                    "entry_id": entry_id,
                    "new_mandate_reference": row["mandate_reference"],
                }
            ],
        )
        self.assertFalse(result.get("success") and result.get("applied"), result)

        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch Invoice", entry_id, "mandate_reference"),
            own_reference,
        )

    # --- round 2: row.member is itself writable, so it must agree with the invoice ---

    def _own_row_and_mandate(self, birth_date):
        member = self._member_with_membership(birth_date)
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        invoice, row = self._invoice_row(member, mandate, 25.0)
        return member, mandate, invoice, row

    def _schedule_of(self, member_name):
        return frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "is_template": 0, "status": "Active"}, "name"
        )

    def _probe_set_invoice_links(self, invoice, member=None, schedule=None):
        """Probe shortcut: direct writes of the invoice's two member-resolving links.
        Setting both explicitly is the point; the control reads the unset state."""
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"member": member, "membership_dues_schedule_display": schedule},
            update_modified=False,
        )

    def _row_naming_other_member_as_its_own(self, other_member, other_mandate, row):
        """A's invoice, but row.member = B and B's own Active mandate: B passes the
        mandate-owner leg, so only the invoice-member leg can refuse it."""
        forged = dict(row)
        forged["member"] = other_member.name
        forged["member_name"] = other_member.full_name
        forged["mandate_reference"] = other_mandate.mandate_id
        forged["iban"] = other_mandate.iban
        return forged

    def test_row_member_swapped_to_the_mandate_owner_is_refused_via_dues_schedule(self):
        member_a, _m, invoice, row = self._own_row_and_mandate("1990-01-01")
        other = self._member_with_membership("1991-02-02")
        other_mandate = self._sepa.create_test_sepa_mandate(member=other.name, status="Active")
        self._probe_set_invoice_links(invoice, member=None, schedule=self._schedule_of(member_a.name))
        forged = self._row_naming_other_member_as_its_own(other, other_mandate, row)

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._unsaved_batch([forged]).insert()

        self.assertIn("does not belong", str(ctx.exception))
        self.assertNotIn(other.name, str(ctx.exception))

    def test_row_member_swapped_to_the_mandate_owner_is_refused_via_invoice_member(self):
        member_a, _m, invoice, row = self._own_row_and_mandate("1990-01-01")
        other = self._member_with_membership("1991-02-02")
        other_mandate = self._sepa.create_test_sepa_mandate(member=other.name, status="Active")
        self._probe_set_invoice_links(invoice, member=member_a.name, schedule=None)
        forged = self._row_naming_other_member_as_its_own(other, other_mandate, row)

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._unsaved_batch([forged]).insert()

        self.assertIn("does not belong", str(ctx.exception))

    def test_dues_schedule_member_wins_over_a_differing_invoice_member(self):
        """Shared customer: Sales Invoice.member (fetched from the customer) names B
        while the invoice's dues schedule is A's. The schedule is authoritative, so A's
        own row saves and a row naming B (with B's mandate) is refused."""
        member_a, _m, invoice, row = self._own_row_and_mandate("1990-01-01")
        other = self._member_with_membership("1991-02-02")
        other_mandate = self._sepa.create_test_sepa_mandate(member=other.name, status="Active")
        self._probe_set_invoice_links(
            invoice, member=other.name, schedule=self._schedule_of(member_a.name)
        )

        own = self._unsaved_batch([row])
        own.insert()
        self._track("Direct Debit Batch", own.name)

        forged = self._row_naming_other_member_as_its_own(other, other_mandate, row)
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_batch([forged]).insert()

    def test_control_invoice_with_no_resolvable_member_still_saves(self):
        """veg11 has invoices with member NULL and no schedule; refusing them would
        block real batches. Unknown means skip, not refuse."""
        _member, _m, invoice, row = self._own_row_and_mandate("1990-01-01")
        self._probe_set_invoice_links(invoice, member=None, schedule=None)
        self.assertIsNone(frappe.db.get_value("Sales Invoice", invoice.name, "member"))

        batch = self._unsaved_batch([row])
        batch.insert()
        self._track("Direct Debit Batch", batch.name)

        self.assertEqual(len(batch.invoices), 1)

    # --- controls: rows that must keep saving ------------------------------------

    def test_control_members_own_active_mandate_saves(self):
        batch = self._unsaved_batch([self._member_mandate_row(25.0, "1990-01-01")])

        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        batch.reload()
        batch.save()

        self.assertEqual(len(batch.invoices), 1)

    def test_control_generation_flow_output_is_saveable(self):
        """The processor's own row writer (`add_invoice_to_batch_with_sequence`) is what
        generation uses; its rows must still insert."""
        member = self._member_with_membership("1993-04-04")
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        invoice = self.create_test_sales_invoice(
            customer=member.name, company=self.eur_company, grand_total=22.0
        )
        member.reload()
        batch = self._unsaved_batch([], automated=True)
        self.processor.add_invoice_to_batch_with_sequence(
            batch,
            {
                "name": invoice.name,
                "membership": frappe.db.get_value("Membership", {"member": member.name}, "name"),
                "member": member.name,
                "member_name": member.full_name,
                "amount": 22.0,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "mandate_sign_date": mandate.sign_date,
                "mandate_name": mandate.name,
            },
            "FRST",
        )

        batch.insert()
        self._track("Direct Debit Batch", batch.name)

        self.assertEqual(len(batch.invoices), 1)

    def _plant_foreign_mandate(self, batch, mandate_reference):
        """Probe shortcut (see module docstring): a direct write, no validate."""
        frappe.db.set_value(
            "Direct Debit Batch Invoice",
            batch.invoices[0].name,
            "mandate_reference",
            mandate_reference,
            update_modified=False,
        )
