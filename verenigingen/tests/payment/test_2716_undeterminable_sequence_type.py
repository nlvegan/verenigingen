"""
#2716: when a SEPA mandate's sequence type (FRST/RCUR) cannot be determined, the batch
builders used to ship the guess in the batch (pain.008 ``SeqTp``) and in the persisted
SEPA Mandate Usage row. Maintainer ruling (2026-11-18): leave THAT invoice out of the
batch, record a visible error on the batch for staff (``batch_log``), ship the rest.

Failure is injected at the real lookup (the SEPA Mandate Usage query, for ONE victim
mandate only), below ``get_mandate_sequence_type``. The victim's real type is RCUR
(prior Collected usage) while the fallback guess is FRST, and the other member's real
type is FRST, so a leftover guess or a swapped row cannot pass.
"""

from unittest.mock import patch

import frappe
from frappe.model.qb_query import DatabaseQuery
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.api import dd_batch_optimizer
from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
    create_mandate_usage_record,
)
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor
from verenigingen.verenigingen_payments.utils import payment_retry as retry

_s2716_real_execute = DatabaseQuery.execute


def _s2716_fail_usage_lookup_for(mandate_name):
    """Fail the usage lookup of ONE mandate inside DatabaseQuery.execute (below
    frappe.get_all and below every handler under test); everything else runs for real."""

    def _s2716_execute(query, *args, **kwargs):
        filters = kwargs.get("filters")
        if (
            query.doctype == "SEPA Mandate Usage"
            and isinstance(filters, dict)
            and filters.get("parent") == mandate_name
        ):
            raise RuntimeError("transient usage lookup failure (#2716)")
        return _s2716_real_execute(query, *args, **kwargs)

    return patch.object(DatabaseQuery, "execute", _s2716_execute)


class Test2716UndeterminableSequenceType(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa_factory = SEPATestDataFactory(seed=2716, use_faker=True)
        scenario = self.sepa_factory.create_sepa_test_scenario(scenario_name="s2716", member_count=2)
        self.victim_mandate, self.ok_mandate = scenario["mandates"]
        self.victim_invoice, self.ok_invoice = scenario["invoices"]
        self.scenario = scenario
        # The victim's REAL type is RCUR (a Collected usage), the guess would be FRST.
        usage_name = create_mandate_usage_record(
            mandate_name=self.victim_mandate.name,
            reference_doctype="Sales Invoice",
            reference_name=f"PRIOR-{frappe.generate_hash(length=8)}",
            amount=10,
            sequence_type="FRST",
        )
        for row in frappe.get_doc("SEPA Mandate", self.victim_mandate.name).usage_history:
            if row.name == usage_name:
                row.db_set("status", "Collected", update_modified=False)
                row.db_set("processing_date", today(), update_modified=False)

    def _s2716_membership(self, invoice):
        by_member = {m.member: m.name for m in self.scenario["memberships"]}
        return by_member[invoice.member]

    def _s2716_new_batch(self):
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "CORE"
        batch.currency = "EUR"
        batch.status = "Draft"
        batch._automated_processing = True
        return batch

    def _s2716_usage_rows(self, invoice):
        return frappe.get_all(
            "SEPA Mandate Usage", filters={"reference_name": invoice.name}, fields=["name", "sequence_type"]
        )

    def _s2716_invoice_data(self, invoice, mandate):
        return {
            "name": invoice.name,
            "membership": self._s2716_membership(invoice),
            "member": mandate.member,
            "member_name": "M",
            "amount": invoice.grand_total,
            "currency": invoice.currency,
            "iban": mandate.iban,
            "mandate_name": mandate.name,
            "mandate_reference": mandate.mandate_id,
        }

    def _s2716_assert_victim_left_out(self, batch):
        rows = {r.invoice: r for r in batch.invoices}
        self.assertNotIn(self.victim_invoice.name, rows, "undeterminable invoice must not ship")
        self.assertIn(self.ok_invoice.name, rows, "the rest of the batch must still ship")
        self.assertEqual(rows[self.ok_invoice.name].sequence_type, "FRST")
        self.assertEqual(self._s2716_usage_rows(self.victim_invoice), [], "no usage row for a guess")
        self.assertIn(self.victim_invoice.name, batch.batch_log or "", "staff must see which invoice")
        self.assertNotIn(self.ok_invoice.name, batch.batch_log or "")

    def test_premise_real_types_differ_from_the_guess(self):
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        self.assertEqual(get_mandate_sequence_type(self.victim_mandate.name, "X")["sequence_type"], "RCUR")
        self.assertEqual(get_mandate_sequence_type(self.ok_mandate.name, "X")["sequence_type"], "FRST")

    def test_monthly_optimized_path_leaves_the_invoice_out(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        batch = self._s2716_new_batch()
        invoices = [{"name": self.victim_invoice.name}, {"name": self.ok_invoice.name}]
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            SEPABatchProcessor().add_invoices_to_batch_optimized(batch, invoices)
        self._s2716_assert_victim_left_out(batch)

    def test_monthly_fallback_path_leaves_the_invoice_out(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        batch = self._s2716_new_batch()
        invoices = [
            self._s2716_invoice_data(self.victim_invoice, self.victim_mandate),
            self._s2716_invoice_data(self.ok_invoice, self.ok_mandate),
        ]
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            SEPABatchProcessor()._add_invoices_to_batch_fallback(batch, invoices)
        self._s2716_assert_victim_left_out(batch)

    def test_add_existing_invoice_to_batch_leaves_the_invoice_out(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        batch = self._s2716_new_batch()
        processor = SEPABatchProcessor()
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            processor.add_existing_invoice_to_batch(
                batch, self._s2716_invoice_data(self.victim_invoice, self.victim_mandate)
            )
            processor.add_existing_invoice_to_batch(
                batch, self._s2716_invoice_data(self.ok_invoice, self.ok_mandate)
            )
        self._s2716_assert_victim_left_out(batch)

    def test_dd_batch_optimizer_leaves_the_invoice_out_and_batch_inserts(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        rows = [
            {
                "invoice": inv.name,
                "membership": self._s2716_membership(inv),
                "member": m.member,
                "member_name": "M",
                "amount": inv.grand_total,
                "currency": inv.currency,
                "iban": m.iban,
                "mandate_reference": m.mandate_id,
            }
            for inv, m in (
                (self.victim_invoice, self.victim_mandate),
                (self.ok_invoice, self.ok_mandate),
            )
        ]
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            batch = dd_batch_optimizer.create_dd_batch_document(rows, today(), 1, {})
        batch.reload()
        self._s2716_assert_victim_left_out(batch)
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(batch.total_amount, self.ok_invoice.grand_total)

    def test_dd_batch_optimizer_row_without_a_mandate_is_not_guessed_either(self):
        """The 'No mandate found, defaulting to FRST' branch is the same guess."""
        self.expectErrorLog("SEPA Batch - Sequence Type Undeterminable")
        row = {
            "invoice": self.victim_invoice.name,
            "membership": self._s2716_membership(self.victim_invoice),
            "member": self.victim_mandate.member,
            "member_name": "M",
            "amount": self.victim_invoice.grand_total,
            "currency": self.victim_invoice.currency,
            "iban": self.victim_mandate.iban,
            "mandate_reference": "NO-SUCH-MANDATE-2716",
        }
        ok = {**row, "invoice": self.ok_invoice.name, "mandate_reference": self.ok_mandate.mandate_id}
        batch = dd_batch_optimizer.create_dd_batch_document([row, ok], today(), 1, {})
        batch.reload()
        self.assertEqual([r.invoice for r in batch.invoices], [self.ok_invoice.name])

    def test_dd_batch_optimizer_all_undeterminable_makes_no_batch(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        row = {
            "invoice": self.victim_invoice.name,
            "membership": self._s2716_membership(self.victim_invoice),
            "member": self.victim_mandate.member,
            "member_name": "M",
            "amount": self.victim_invoice.grand_total,
            "currency": self.victim_invoice.currency,
            "iban": self.victim_mandate.iban,
            "mandate_reference": self.victim_mandate.mandate_id,
        }
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            self.assertIsNone(dd_batch_optimizer.create_dd_batch_document([row], today(), 1, {}))

    def test_manual_batch_row_without_sequence_type_is_refused_not_guessed(self):
        """A row saved with a blank sequence_type used to be auto-assigned the guess."""
        self.expectErrorLog("Error determining sequence type")
        batch = self._s2716_new_batch()
        batch._automated_processing = False
        m = self.victim_mandate
        batch.append(
            "invoices",
            {
                "invoice": self.victim_invoice.name,
                "membership": self._s2716_membership(self.victim_invoice),
                "member": m.member,
                "member_name": "M",
                "amount": self.victim_invoice.grand_total,
                "currency": self.victim_invoice.currency,
                "iban": m.iban,
                "mandate_reference": m.mandate_id,
            },
        )
        with _s2716_fail_usage_lookup_for(m.name):
            with self.assertRaises(frappe.ValidationError) as ctx:
                batch.validate_sequence_types()
        self.assertIn(self.victim_invoice.name, str(ctx.exception))
        self.assertFalse(batch.invoices[0].sequence_type, "must not be filled with a guess")

    def test_payment_retry_does_not_submit_a_guess(self):
        self.expectErrorLog("Error determining sequence type", "SEPA Batch - Sequence Type Undeterminable")
        member = frappe.get_doc("Member", self.victim_mandate.member)
        membership = frappe._dict(name=self._s2716_membership(self.victim_invoice))
        frappe.db.set_value("SEPA Mandate", self.victim_mandate.name, "used_for_memberships", 1)
        rec = frappe.new_doc("SEPA Payment Retry")
        rec.invoice = self.victim_invoice.name
        rec.member = member.name
        rec.original_amount = self.victim_invoice.outstanding_amount
        rec.retry_count = 1
        rec.status = "Scheduled"
        rec.next_retry_date = today()
        rec.membership = membership.name
        rec.insert()
        # The scenario factory parks every invoice in a Draft batch; the retry's
        # open-batch guard would answer before the code under test is reached.
        for parent in set(
            frappe.get_all("Direct Debit Batch Invoice", filters={"invoice": self.victim_invoice.name}, pluck="parent")
        ):
            frappe.delete_doc("Direct Debit Batch", parent, force=1)
        with _s2716_fail_usage_lookup_for(self.victim_mandate.name):
            retry.execute_payment_retry(retry_record=rec.name)
        rec.reload()
        self.assertEqual(rec.status, "Failed")
        self.assertEqual(frappe.db.count("Direct Debit Batch Invoice", {"invoice": self.victim_invoice.name}), 0)
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "SEPA Payment Retry", "reference_name": rec.name},
            pluck="content",
        )
        self.assertTrue(any("sequence type" in c.lower() for c in comments), comments)
