"""
Integration coverage for the invoice event chain.

Exercises:
  * ``verenigingen/events/invoice_events.py`` — emit_invoice_submitted /
    _cancelled / _updated_after_submit guards, the bulk-generation skip, the
    payment-history member-fan-out enqueue path, and the subscriber registry.
  * ``verenigingen/events/subscribers/payment_history_subscriber.py`` — the
    handlers that queue (and ultimately materialise) member payment-history
    rows from invoice lifecycle events.

Hardening (subscribers swallow-and-log):
  * ``self.assertNoErrorLog()`` around the happy path turns a swallowed
    exception into a real failure (frappe.log_error commits independently of
    the test transaction).
  * Real side effects are asserted: the in-memory FinancialHistoryBatchProcessor
    queue grows, and after ``force_process_all()`` the Member's
    ``payment_history`` child table actually contains the invoice row.

``emit_*`` enqueue via frappe.enqueue (no inline run), so the emitter tests
patch ``frappe.enqueue`` to capture dispatch decisions (the enqueue boundary,
not product logic). The subscriber-effect tests call the handler functions
directly with real records.
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.events import invoice_events as ie
from verenigingen.events.subscribers import payment_history_subscriber as phs
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor


class TestInvoiceEventsCoverage(EnhancedTestCase):
    """Real integration coverage for invoice_events + payment_history_subscriber."""

    def setUp(self):
        super().setUp()
        # The batch processor uses class-level (process-global) queues. Clear
        # them so a prior test's residue does not leak into assertions here.
        FinancialHistoryBatchProcessor._payment_queue.clear()
        FinancialHistoryBatchProcessor._expense_queue.clear()
        # Ensure the bulk-generation flag is not set by a neighbouring test.
        self._saved_bulk = getattr(frappe.flags, "bulk_invoice_generation", None)
        frappe.flags.bulk_invoice_generation = False

    def tearDown(self):
        frappe.flags.bulk_invoice_generation = self._saved_bulk
        FinancialHistoryBatchProcessor._payment_queue.clear()
        FinancialHistoryBatchProcessor._expense_queue.clear()
        super().tearDown()

    # ------------------------------------------------------------------ helpers
    def _make_member_with_customer(self, prefix="inv"):
        """Member + linked Customer (via create_test_sales_invoice's linkage)."""
        member = self.create_test_member(first_name="InvSub", last_name="Member", birth_date="1990-01-01")
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        member.db_set("email", email, update_modified=False)
        member.reload()
        return member

    def _make_submitted_invoice(self, member):
        # Enhanced factory signature: create_test_sales_invoice(customer, **kwargs);
        # passing the Member name resolves (and creates) its linked Customer.
        invoice = self.create_test_sales_invoice(member.name)
        invoice.submit()
        member.reload()  # picks up member.customer set during invoice creation
        return invoice

    @contextmanager
    def _captured_enqueue(self):
        """Capture frappe.enqueue calls without actually queuing a job."""
        calls = []

        def _fake(*args, **kwargs):
            calls.append(kwargs)
            return None

        with patch("frappe.enqueue", side_effect=_fake):
            yield calls

    def _payment_queue_for(self, member_name):
        return FinancialHistoryBatchProcessor._payment_queue.get(member_name, {})

    def _make_empty_payment_history(self, member_name):
        """Clear a Member's payment_history child rows (factory/setup helper)."""
        md = frappe.get_doc("Member", member_name)
        md.payment_history = []
        md.save(ignore_permissions=True)

    def _payment_history_invoices(self, member_name):
        rows = frappe.get_all(
            "Member Payment History",
            filters={"parent": member_name, "parenttype": "Member"},
            fields=["invoice"],
        )
        return {r.invoice for r in rows if r.invoice}

    # ============================================================ emitter guards
    def test_emit_submitted_skips_non_sales_invoice(self):
        doc = frappe._dict(doctype="Purchase Invoice", customer="X", name="PI-1")
        with self._captured_enqueue() as calls:
            ie.emit_invoice_submitted(doc)
        self.assertEqual(calls, [], "non Sales Invoice must not dispatch")

    def test_emit_submitted_skips_invoice_without_customer(self):
        doc = frappe._dict(doctype="Sales Invoice", customer=None, name="SI-noc")
        with self._captured_enqueue() as calls:
            ie.emit_invoice_submitted(doc)
        self.assertEqual(calls, [], "customer-less invoice must not dispatch")

    def test_emit_updated_after_submit_skips_draft(self):
        doc = frappe._dict(doctype="Sales Invoice", customer="X", name="SI-d", docstatus=0)
        with self._captured_enqueue() as calls:
            ie.emit_invoice_updated_after_submit(doc)
        self.assertEqual(calls, [], "draft invoice must not dispatch update event")

    def test_emit_submitted_skips_during_bulk_generation(self):
        member = self._make_member_with_customer("bulk")
        invoice = self._make_submitted_invoice(member)
        frappe.flags.bulk_invoice_generation = True
        try:
            with self._captured_enqueue() as calls:
                ie.emit_invoice_submitted(frappe.get_doc("Sales Invoice", invoice.name))
            self.assertEqual(calls, [], "bulk generation must short-circuit emission")
        finally:
            frappe.flags.bulk_invoice_generation = False

    # ============================================================ emitter dispatch
    def test_emit_submitted_enqueues_member_specific_dedupe_job(self):
        """A real member+invoice routes to a per-member dedupe job (the special
        payment-history path in _emit_invoice_event)."""
        member = self._make_member_with_customer("dispatch")
        invoice = self._make_submitted_invoice(member)

        with self._captured_enqueue() as calls:
            ie.emit_invoice_submitted(frappe.get_doc("Sales Invoice", invoice.name))

        self.assertEqual(len(calls), 1, f"expected one enqueue, got {calls}")
        kw = calls[0]
        self.assertEqual(kw.get("job_name"), f"payment_history_update_{member.name}")
        self.assertTrue(kw.get("dedupe"), "member payment-history job must be dedupe'd")
        self.assertTrue(kw.get("method", "").endswith("payment_history_subscriber.handle_invoice_submitted"))
        self.assertEqual(kw.get("event_data", {}).get("invoice"), invoice.name)

    def test_emit_submitted_customer_with_no_member_enqueues_nothing(self):
        """Characterization: a customer NOT linked to any Member dispatches ZERO
        jobs for the payment-history subscriber.

        In ``_emit_invoice_event`` the payment-history subscriber takes the
        ``if customer:`` branch, resolves ``members=[]`` (no member for this
        customer) and the per-member loop runs zero times. The generic ``else``
        fallback only fires when ``customer`` itself is falsy — which the top-of
        -emitter guard already rejects. Net: an orphan-customer invoice silently
        produces no payment-history update. Documents the dead fallback branch.
        """
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"Orphan Cust {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)

        doc = frappe._dict(
            doctype="Sales Invoice",
            customer=customer.name,
            name=f"SI-orphan-{frappe.generate_hash(length=6)}",
            posting_date=str(frappe.utils.today()),
            due_date=str(frappe.utils.today()),
            grand_total=10,
            outstanding_amount=10,
            status="Unpaid",
            docstatus=1,
        )
        with self._captured_enqueue() as calls:
            ie.emit_invoice_submitted(doc)
        self.assertEqual(calls, [], "orphan-customer invoice should enqueue nothing")

    def test_emit_submitted_swallows_dispatch_failure(self):
        """The emitter must log-and-swallow if dispatch raises (never block submit)."""
        member = self._make_member_with_customer("swallow")
        invoice = self._make_submitted_invoice(member)
        self.expectErrorLog("Invoice Event Emission Error")
        before = frappe.db.count("Error Log")
        with patch.object(ie, "_emit_invoice_event", side_effect=RuntimeError("boom")):
            ie.emit_invoice_submitted(frappe.get_doc("Sales Invoice", invoice.name))  # must not raise
        self.assertGreater(frappe.db.count("Error Log"), before)

    def test_get_event_subscribers_registry_resolvable(self):
        import importlib

        for event in ("invoice_submitted", "invoice_cancelled", "invoice_updated_after_submit"):
            subs = ie._get_event_subscribers(event)
            self.assertTrue(subs, f"no subscribers for {event}")
            for dotted in subs:
                module_path, func = dotted.rsplit(".", 1)
                mod = importlib.import_module(module_path)
                self.assertTrue(callable(getattr(mod, func, None)), f"missing handler {dotted}")

    def test_get_event_subscribers_unknown_event(self):
        self.assertEqual(ie._get_event_subscribers("nope"), [])

    # ===================================== handle_invoice_submitted (subscriber)
    def test_handle_submitted_queues_then_materialises_payment_history(self):
        """End-to-end: handle_invoice_submitted queues the member, and once the
        batch is forced the invoice appears in the Member's payment_history."""
        member = self._make_member_with_customer("queue")
        invoice = self._make_submitted_invoice(member)
        customer = member.customer
        self.assertTrue(customer, "invoice creation should have linked a customer")

        with self.assertNoErrorLog():
            phs.handle_invoice_submitted(
                event_name="invoice_submitted",
                event_data={"customer": customer, "invoice": invoice.name},
            )

        # The handler queues into the in-memory batch processor (queue may have
        # been auto-flushed by the 30s timer; force to make the assertion robust).
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertIn(
            invoice.name,
            self._payment_history_invoices(member.name),
            "submitted invoice must end up in the member's payment history",
        )

    def test_handle_submitted_skips_during_bulk_generation(self):
        member = self._make_member_with_customer("bulkskip")
        invoice = self._make_submitted_invoice(member)
        frappe.flags.bulk_invoice_generation = True
        try:
            with self.assertNoErrorLog():
                phs.handle_invoice_submitted(
                    event_name="invoice_submitted",
                    event_data={"customer": member.customer, "invoice": invoice.name},
                )
            self.assertEqual(self._payment_queue_for(member.name), {}, "bulk mode must not queue")
        finally:
            frappe.flags.bulk_invoice_generation = False

    def test_handle_submitted_no_event_data_noop(self):
        with self.assertNoErrorLog():
            phs.handle_invoice_submitted(event_name="invoice_submitted", event_data=None)

    def test_handle_submitted_missing_customer_or_invoice_noop(self):
        with self.assertNoErrorLog():
            phs.handle_invoice_submitted("e", {"invoice": "SI-x"})  # no customer
            phs.handle_invoice_submitted("e", {"customer": "Cust-x"})  # no invoice

    def test_handle_submitted_nonexistent_invoice_noop(self):
        """Race-condition guard: an invoice that does not exist is skipped (no
        queue entry, no error)."""
        member = self._make_member_with_customer("race")
        self._make_submitted_invoice(member)  # establishes member.customer
        with self.assertNoErrorLog():
            phs.handle_invoice_submitted(
                "e", {"customer": member.customer, "invoice": "SI-DOES-NOT-EXIST-999"}
            )
        self.assertEqual(self._payment_queue_for(member.name), {})

    # ===================================== handle_invoice_cancelled (subscriber)
    def test_handle_cancelled_removes_from_payment_history(self):
        member = self._make_member_with_customer("cancel")
        invoice = self._make_submitted_invoice(member)
        customer = member.customer

        # First put the invoice into payment history.
        phs.handle_invoice_submitted("e", {"customer": customer, "invoice": invoice.name})
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertIn(invoice.name, self._payment_history_invoices(member.name))

        # Now cancel -> queued removal -> forced -> row gone.
        with self.assertNoErrorLog():
            phs.handle_invoice_cancelled("e", {"customer": customer, "invoice": invoice.name})
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertNotIn(
            invoice.name,
            self._payment_history_invoices(member.name),
            "cancelled invoice must be removed from payment history",
        )

    def test_handle_cancelled_skips_during_bulk_generation(self):
        member = self._make_member_with_customer("cbulk")
        invoice = self._make_submitted_invoice(member)
        frappe.flags.bulk_invoice_generation = True
        try:
            with self.assertNoErrorLog():
                phs.handle_invoice_cancelled("e", {"customer": member.customer, "invoice": invoice.name})
            self.assertEqual(self._payment_queue_for(member.name), {})
        finally:
            frappe.flags.bulk_invoice_generation = False

    def test_handle_cancelled_no_event_data_noop(self):
        with self.assertNoErrorLog():
            phs.handle_invoice_cancelled("e", None)

    # ===================================== handle_invoice_updated (subscriber)
    def test_handle_updated_updates_payment_history(self):
        """handle_invoice_updated -> Member.update_invoice_in_payment_history.

        Despite the handler's "atomic update" wording, that method ultimately
        QUEUES into the batch processor (add_invoice_to_payment_history), so
        force the batch to materialise the row.
        """
        member = self._make_member_with_customer("update")
        invoice = self._make_submitted_invoice(member)

        with self.assertNoErrorLog():
            phs.handle_invoice_updated("e", {"customer": member.customer, "invoice": invoice.name})
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertIn(
            invoice.name,
            self._payment_history_invoices(member.name),
            "updated invoice must be present in payment history",
        )

    def test_handle_updated_skips_during_bulk_generation(self):
        """In bulk mode the handler must early-return before updating the Member;
        without the flag the same call populates payment_history.

        submit() already ran the doc-hook that adds the invoice, so clear the
        payment_history rows first to get a clean signal of what THIS call does.
        """
        member = self._make_member_with_customer("ubulk")
        invoice = self._make_submitted_invoice(member)

        # Bulk mode: handler early-returns -> history stays empty.
        self._make_empty_payment_history(member.name)
        # Drop any queue residue from submit() so a later flush can't add the row.
        FinancialHistoryBatchProcessor._payment_queue.clear()
        frappe.flags.bulk_invoice_generation = True
        try:
            with self.assertNoErrorLog():
                phs.handle_invoice_updated("e", {"customer": member.customer, "invoice": invoice.name})
            self.assertNotIn(
                invoice.name,
                self._payment_history_invoices(member.name),
                "bulk mode must not update payment history",
            )
        finally:
            frappe.flags.bulk_invoice_generation = False

        # Same call without the flag DOES populate it (proves the flag was the
        # only thing suppressing the update above). The update queues via the
        # batch processor, so force it to materialise.
        self._make_empty_payment_history(member.name)
        with self.assertNoErrorLog():
            phs.handle_invoice_updated("e", {"customer": member.customer, "invoice": invoice.name})
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertIn(invoice.name, self._payment_history_invoices(member.name))

    def test_handle_updated_no_event_data_noop(self):
        with self.assertNoErrorLog():
            phs.handle_invoice_updated("e", None)

    def test_handle_updated_customer_without_member_noop(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"NoMember Cust {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        with self.assertNoErrorLog():
            phs.handle_invoice_updated("e", {"customer": customer.name, "invoice": "SI-x"})

    # ===================================== legacy alias
    def test_immediate_handler_delegates_to_submitted(self):
        """handle_invoice_submitted_immediate is a thin alias — same effect."""
        member = self._make_member_with_customer("legacy")
        invoice = self._make_submitted_invoice(member)
        with self.assertNoErrorLog():
            phs.handle_invoice_submitted_immediate(
                event_name="invoice_submitted",
                event_data={"customer": member.customer, "invoice": invoice.name},
            )
        FinancialHistoryBatchProcessor.force_process_all()
        self.assertIn(invoice.name, self._payment_history_invoices(member.name))
