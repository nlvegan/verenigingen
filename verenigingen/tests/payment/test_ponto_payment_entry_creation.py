# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Real-DB tests for `create_ponto_payment_entry` (ponto/services/payment_entry_service.py).

This is the function that turns an executed Ponto payment link into money on the
ledger, and it had no coverage at all - the existing test_ponto_webhook_handler.py
suite covers event extraction and routing, stopping short of document creation.

Everything here runs against real documents: a real Member/Customer, a real
submitted Sales Invoice, a real Ponto clearing GL Account and a real Ponto Payment
Link. Nothing in the payment-entry path is mocked.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.services.payment_entry_service import (
    create_ponto_payment_entry,
)


def _ensure_ponto_clearing_account(company):
    """A real Bank GL Account matching the handler's `%Ponto%` lookup.

    Lives at module scope (a recognised fixture location) so the permission-bypass
    insert is allowed. The handler prefers
    `Verenigingen Payments Settings.ponto_bank_account_parent` and falls back to this
    name match, which is the branch exercised here.
    """
    existing = frappe.db.get_value(
        "Account", {"company": company, "account_name": "Ponto Clearing", "is_group": 0}, "name"
    )
    if existing:
        return existing

    parent = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
    ) or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
    account = frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": "Ponto Clearing",
            "company": company,
            "parent_account": parent,
            "account_type": "Bank",
            "is_group": 0,
            "account_currency": frappe.db.get_value("Company", company, "default_currency"),
        }
    ).insert(ignore_permissions=True)
    frappe.db.commit()
    return account.name


class TestCreatePontoPaymentEntry(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.ponto_account = _ensure_ponto_clearing_account(cls.company)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    def _member_with_customer(self, first_name="PontoPay"):
        member = self.sepa.create_test_member(first_name=first_name)
        if not member.customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
            member.reload()
        return member

    def _submitted_invoice(self, customer, amount=30.0):
        return self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=amount,
            status="Unpaid",
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
            submit=True,
        )

    def _payment_link(self, member, amount=30.0, description="Contributie 2026"):
        link = frappe.get_doc(
            {
                "doctype": "Ponto Payment Link",
                "payment_type": "One-Time",
                "amount": amount,
                "currency": "EUR",
                "description": description,
                "creditor_name": "Vereniging Test",
                "creditor_iban": "NL91ABNA0417164300",
                "status": "Executed",
                "member": member.name,
                "ponto_request_id": f"ponto_req_{frappe.generate_hash(length=10)}",
            }
        )
        link.insert()
        frappe.db.commit()
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def test_creates_a_submitted_entry_allocated_to_the_invoice(self):
        """The baseline contract: money on the ledger, allocated, in the Ponto account."""
        member = self._member_with_customer()
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        pe_name = create_ponto_payment_entry(link, invoice.name)

        self.assertIsNotNone(pe_name, "an executed Ponto payment must produce a Payment Entry")
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.paid_to, self.ponto_account)
        self.assertEqual(pe.reference_no, link.ponto_request_id)
        self.assertEqual(pe.custom_member, member.name)
        self.assertEqual(
            [r.reference_name for r in pe.references],
            [invoice.name],
            "the payment must be allocated to the invoice it was raised for",
        )

    def test_payment_link_remark_survives_validation(self):
        """The Ponto payment-link reference must reach the saved document.

        Payment Entry.validate() calls set_remarks(), which regenerates the field from
        the amount and party unless custom_remarks is set - so the remark is read back
        from the DB rather than off the in-memory document, which would pass even when
        the text is discarded on save.
        """
        member = self._member_with_customer(first_name="PontoRemark")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member, description="Contributie kwartaal 2")

        pe_name = create_ponto_payment_entry(link, invoice.name)

        remarks = frappe.db.get_value("Payment Entry", pe_name, "remarks") or ""
        self.assertIn(link.name, remarks, "the payment-link reference was discarded by set_remarks()")
        self.assertIn("Contributie kwartaal 2", remarks)

    def test_already_paid_invoice_creates_no_entry(self):
        """A fully-paid invoice short-circuits before any document is written."""
        member = self._member_with_customer(first_name="PontoPaid")
        invoice = self._submitted_invoice(member.customer)
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)
        link = self._payment_link(member)

        self.assertIsNone(create_ponto_payment_entry(link, invoice.name))

    def test_draft_invoice_is_not_treated_as_an_allocation_target(self):
        """A DRAFT invoice must not be handed to the Payment Entry allocator.

        #856 (the class #209/#220 were fixed for): a draft Sales Invoice does not
        carry `outstanding_amount == 0` - `calculate_outstanding_amount` runs on every
        save that is not cancelled, so a fresh draft carries its full `grand_total` as
        outstanding. The old code read only `outstanding_amount <= 0` ("already paid,
        skip") with no `docstatus` check, so a draft fell through as a normal *unpaid*
        invoice and was passed straight to `create_payment_entry_from_invoice`, which
        would raise when ERPNext refuses to submit a Payment Entry referencing an
        unsubmitted document (`payment_entry.py:725-727`, "... must be submitted").

        This pins both the premise and the fix: the draft's outstanding_amount is
        confirmed non-zero (so the old code's branch is genuinely reachable), and the
        call must return None - no Payment Entry, no exception - rather than either
        creating one against a draft or letting the ValidationError propagate.
        """
        member = self._member_with_customer(first_name="PontoDraft")
        invoice = self.sepa.create_test_sales_invoice(
            customer=member.customer,
            grand_total=30.0,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
        )
        self.assertEqual(invoice.docstatus, 0, "premise: the invoice must be a draft")
        self.assertGreater(
            flt(invoice.outstanding_amount),
            0,
            "premise: a draft's outstanding_amount is its grand_total, not 0",
        )
        link = self._payment_link(member)

        with self.assertNoErrorLog():
            pe_name = create_ponto_payment_entry(link, invoice.name)

        self.assertIsNone(pe_name, "a draft invoice must never be used as an allocation target")
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "no Payment Entry may be left behind for a refused draft",
        )

    def test_allocation_is_capped_at_the_outstanding_amount(self):
        """An overpaying link allocates only what the invoice still owes.

        Without the cap ERPNext rejects the reference outright ("cannot be greater than
        outstanding amount"), so this pins the clamp rather than the happy path.

        Ponto deliberately does NOT opt into PaymentEntryCreationService's
        `cash_received`: it posts to a bank account rather than a gateway clearing
        account that must reconcile against a settlement file. The paid_amount and
        unallocated_amount assertions below exist to catch that decision being
        reversed silently - asserting allocated_amount alone cannot tell the capped
        posting apart from a full-cash one, since the reference row is 30.00 either way.
        """
        member = self._member_with_customer(first_name="PontoOver")
        invoice = self._submitted_invoice(member.customer, amount=30.0)
        link = self._payment_link(member, amount=100.0)

        pe_name = create_ponto_payment_entry(link, invoice.name)

        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(float(pe.references[0].allocated_amount), 30.0)
        self.assertEqual(flt(pe.paid_amount, 2), 30.0)
        self.assertEqual(flt(pe.unallocated_amount, 2), 0.0)

    def test_guest_cannot_create_the_entry(self):
        """Guest must be refused - and nothing partial may be left behind.

        `handle_ponto_webhook` is `allow_guest=True` and nothing in that request path
        elevates the session, so an INLINE call here ran as Guest. That is why the
        executed-payment branch is now enqueued with `user=_get_webhook_user()` like its
        sibling handlers, rather than made to work under Guest by escalating privileges
        inside the service.

        Pinning the refusal matters as much as pinning the success: if this ever starts
        passing, either the enqueue was reverted or something re-introduced an
        escalation. The second assertion is the load-bearing one - a half-created,
        unlinked Payment Entry is the state that lets a retried webhook post twice.
        """
        member = self._member_with_customer(first_name="PontoGuest")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        # Registered before switching so the session is handed back even if the call
        # raises; restoring via addCleanup keeps the escalation out of the test body.
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user("Guest")
        pe_name = create_ponto_payment_entry(link, invoice.name)

        self.assertIsNone(pe_name, "Guest must not be able to record a payment")
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "a refused attempt must leave no Payment Entry behind",
        )

    def test_second_run_relinks_instead_of_creating_a_second_entry(self):
        """A retried `executed` webhook must not produce a second Payment Entry.

        The caller's guard is `not doc.payment_entry`, which only latches if the
        save-back succeeded. Writing that field is a separate step after the entry is
        already submitted, so the two can diverge - a refused save, a crash between
        them - and the retry then posts the payment again. This simulates exactly that
        divergence by clearing the link field while leaving the submitted entry in
        place, which is the state the guard alone cannot distinguish from "never ran".
        """
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _process_executed_payment,
        )

        member = self._member_with_customer(first_name="PontoRetry")
        self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        first = _process_executed_payment(link)
        self.assertIsNotNone(first.get("payment_entry"), first)

        # Simulate the save-back having been lost.
        frappe.db.set_value("Ponto Payment Link", link.name, "payment_entry", None)
        frappe.db.commit()
        link.reload()

        second = _process_executed_payment(link)

        self.assertEqual(
            second.get("payment_entry"),
            first["payment_entry"],
            "the retry must relink the existing entry, not create another",
        )
        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": link.ponto_request_id, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")

    def test_process_payment_received_actually_creates_and_links(self):
        """The DocType's own entry point must produce a Payment Entry, not swallow a failure.

        `process_payment_received` built a Payment Entry by hand and set
        paid_from_account_currency / paid_to_account_currency but never paid_from /
        paid_to, so every insert raised MandatoryError and was swallowed by its own
        `except`. It therefore never set `self.payment_entry` - which is what leaves the
        `not doc.payment_entry` guard unlatched and lets a retried webhook post twice.

        It also keyed reference_no on `self.name` while the webhook path keys on
        `ponto_request_id`, so the two creators could not see each other's work.
        """
        member = self._member_with_customer(first_name="PontoDoctype")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()

        link.process_payment_received()

        self.assertTrue(link.payment_entry, "the link must carry the entry it created")
        pe = frappe.get_doc("Payment Entry", link.payment_entry)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(
            [r.reference_name for r in pe.references],
            [invoice.name],
            "the entry must be allocated to the linked invoice",
        )
        self.assertEqual(
            frappe.db.get_value("Ponto Payment Link", link.name, "payment_entry"),
            pe.name,
            "the link must be persisted, or the retry guard never latches",
        )

    def test_no_sales_invoice_creates_nothing(self):
        """The branch the only production link-creator actually hits.

        payment_gateways.py builds donation links with reference_doctype="Donation" and
        no sales_invoice, so this early return - not the happy path - is what runs for
        the real flow today.
        """
        member = self._member_with_customer(first_name="PontoNoInv")
        link = self._payment_link(member)
        self.assertFalse(link.sales_invoice)

        link.process_payment_received()

        self.assertFalse(link.payment_entry)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "no invoice to allocate against must mean no Payment Entry",
        )

    def test_relinks_an_entry_keyed_on_the_legacy_link_name(self):
        """Entries the former creator wrote under `self.name` must not be duplicated.

        The widened candidate_refs lookup exists for exactly this: reduce it back to
        `[ponto_request_id]` and this test is the only thing that notices.
        """
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _process_executed_payment,
        )

        member = self._member_with_customer(first_name="PontoLegacy")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()

        legacy_pe = create_ponto_payment_entry(link, invoice.name)
        self.assertIsNotNone(legacy_pe)
        # Re-key it the way the old hand-rolled creator did, and unlatch the link.
        frappe.db.set_value("Payment Entry", legacy_pe, "reference_no", link.name)
        frappe.db.set_value("Ponto Payment Link", link.name, "payment_entry", None)
        frappe.db.commit()
        link.reload()

        result = _process_executed_payment(link)

        self.assertEqual(result.get("payment_entry"), legacy_pe, "must relink the legacy entry")
        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": ("in", [link.name, link.ponto_request_id]), "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")

    def test_executed_webhook_puts_the_payment_on_the_ledger(self):
        """End-to-end: webhook handler -> enqueue -> job -> money on the ledger.

        Dispatches through the CAPTURED enqueue arguments rather than calling the job
        directly, because the seam this covers is precisely between "what we enqueue"
        and "what the job accepts": a `user=` kwarg that frappe.enqueue does not have
        bound cleanly at the call site and raised TypeError only in the worker.

        WHAT THIS DOES NOT PROVE: Redis delivery, enqueue_after_commit ordering against
        a real commit, or the worker's own identity handling - those need a live worker.
        Per tests/utils/test_background_jobs.py frappe.enqueue still targets the real RQ
        queue under test mode, so invoking the captured call the way execute_job does
        (`retval = method(**kwargs)`) is the honest approximation.
        """
        from verenigingen.verenigingen_payments.ponto.api import webhook_handlers as wh

        member = self._member_with_customer(first_name="PontoE2E")
        invoice = self._submitted_invoice(member.customer)
        # No sales_invoice on the link: that is what leaves the enqueue branch
        # reachable (a pre-linked one is handled inline by process_payment_received).
        # The invoice name in the description makes the match deterministic via the
        # remittance strategy rather than coverage/amount heuristics.
        link = self._payment_link(member, description=f"Contributie {invoice.name}")
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Authorized")
        frappe.db.commit()

        captured = []
        enqueue_params = None

        def _capture(*args, **kwargs):
            captured.append((args[0] if args else kwargs["method"], dict(kwargs)))

        with patch.object(wh.frappe, "enqueue", side_effect=_capture):
            wh._update_payment_link_status(request_id=link.ponto_request_id, new_status="executed")

        self.assertEqual(len(captured), 1, f"expected exactly one queued job, got {captured}")
        dotted, kwargs = captured[0]

        import inspect

        enqueue_params = set(inspect.signature(frappe.enqueue).parameters) - {"kwargs"}
        job_kwargs = {k: v for k, v in kwargs.items() if k not in enqueue_params}
        target = frappe.get_attr(dotted)

        # Run it exactly as execute_job would.
        target(**job_kwargs)

        pe_name = frappe.db.get_value("Ponto Payment Link", link.name, "payment_entry")
        self.assertTrue(pe_name, "the link must be latched, or a retry posts the payment again")
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.paid_to, self.ponto_account)
        self.assertEqual(
            [r.reference_name for r in pe.references],
            [invoice.name],
            "the money must be allocated to the invoice named in the remittance",
        )
