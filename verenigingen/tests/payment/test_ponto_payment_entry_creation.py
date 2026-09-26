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

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.services.payment_entry_service import (
    create_ponto_payment_entry,
)


@contextmanager
def _no_ponto_bank_account_configured(company, ponto_account):
    """Blank all three resolution paths `create_ponto_payment_entry` tries (settings
    parent group, `%Ponto%` account name match, company default bank account), so
    the misconfiguration guard (#1362) is genuinely reachable rather than silently
    falling through to a real account. Nothing here is committed; everything is
    restored on exit, mirroring test_sepa_reconciliation.py's
    test_create_manual_payment_entry_no_default_bank_account_throws.
    """
    from verenigingen.utils import settings_utils

    original_default_bank_account = frappe.db.get_value("Company", company, "default_bank_account")
    original_account_name = frappe.db.get_value("Account", ponto_account, "account_name")
    frappe.db.set_value("Company", company, "default_bank_account", None)
    # Must not itself contain "Ponto" (case-insensitively), or the `%Ponto%` LIKE
    # match this is trying to defeat still finds the row via account_name.
    frappe.db.set_value("Account", ponto_account, "account_name", "Renamed Elsewhere Clearing")
    frappe.clear_document_cache("Company", company)
    try:
        with patch.object(settings_utils, "get_payments_settings") as mock_settings:
            mock_settings.return_value.ponto_bank_account_parent = None
            yield
    finally:
        frappe.db.set_value("Company", company, "default_bank_account", original_default_bank_account)
        frappe.db.set_value("Account", ponto_account, "account_name", original_account_name)
        frappe.clear_document_cache("Company", company)


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


def _make_second_ponto_account(company, suffix="Backup", disabled=0):
    """A SECOND real Bank GL Account also matching the `%Ponto%` name lookup.

    Created per-test (not at class scope like `_ensure_ponto_clearing_account`), so
    the harness's captured-insert drain cleans it up at teardown without any special
    handling. Created strictly after `cls.ponto_account` (class setup runs first), so
    it is the row `creation DESC` would pick under the pre-#1434 code - the ambiguity
    test below must catch a "pick newest" regression, not merely a "pick some row".

    `disabled=1` builds the exact scenario the issue itself describes ("an old
    clearing account plus a new one created during a re-configuration"): a
    DISABLED account matching `%Ponto%` must not count as an ambiguity candidate,
    since ERPNext refuses to post accounting entries against a disabled Account at
    all (`general_ledger.validate_disabled_accounts`) - it was never a real
    posting target, so it must not force a refusal that blocks the one real,
    enabled candidate.
    """
    parent = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
    ) or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
    account = frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": f"Ponto Clearing {suffix}",
            "company": company,
            "parent_account": parent,
            "account_type": "Bank",
            "is_group": 0,
            "disabled": disabled,
            "account_currency": frappe.db.get_value("Company", company, "default_currency"),
        }
    ).insert(ignore_permissions=True)
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

    def test_no_bank_account_configured_raises(self):
        """A misconfigured Ponto bank account must RAISE, not silently return None
        (#1362, the #1288/#1323 class). Unlike the already-established legitimate
        no-ops (no invoice, already paid, draft invoice, Guest refusal), there is
        no configuration under which "nowhere to post the money" is an expected
        outcome once the bank has confirmed execution - the caller's transaction
        boundary needs to see this so it can roll the status write back instead of
        committing "Executed" with no Payment Entry and no signal anything failed.
        """
        member = self._member_with_customer(first_name="PontoNoBank")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        self.expectErrorLog("Ponto Payment Entry creation failed")
        with _no_ponto_bank_account_configured(self.company, self.ponto_account):
            with self.assertRaises(frappe.ValidationError):
                create_ponto_payment_entry(link, invoice.name)

        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "a refused misconfiguration must leave no Payment Entry behind",
        )

    def test_process_payment_received_propagates_misconfiguration(self):
        """`process_payment_received()` (the DocType's own entry point, reached
        from both `refresh_status()` and the webhook-inline call in
        `update_status_from_webhook()`) has no try/except around the call - this
        pins that the raise actually reaches whichever caller invoked it rather
        than the old `if not pe_name: return` silently absorbing it again.
        """
        member = self._member_with_customer(first_name="PontoLinkNoBank")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()

        self.expectErrorLog("Ponto Payment Entry creation failed")
        with _no_ponto_bank_account_configured(self.company, self.ponto_account):
            with self.assertRaises(frappe.ValidationError):
                link.process_payment_received()

        self.assertFalse(link.payment_entry, "no partial link may survive a raised misconfiguration")

    def test_async_job_raises_instead_of_silently_succeeding(self):
        """The async `process_executed_payment_job` path (`_process_executed_payment`)
        must not swallow a genuine misconfiguration either (#1362). By the time it
        runs, the link's status is ALREADY committed "Executed" by the original
        webhook request (enqueue_after_commit) - no savepoint here can roll that
        back - but a silent `return result` was the only place left where the
        money could get permanently stuck with no Payment Entry and nothing but an
        unread Error Log to show for it.
        """
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _process_executed_payment,
        )

        member = self._member_with_customer(first_name="PontoAsyncNoBank")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()

        self.expectErrorLog("Ponto Payment Entry creation failed", "Ponto payment processing failed")
        with _no_ponto_bank_account_configured(self.company, self.ponto_account):
            with self.assertRaises(frappe.ValidationError):
                _process_executed_payment(link)

        self.assertFalse(
            frappe.db.get_value("Ponto Payment Link", link.name, "payment_entry"),
            "no partial payment_entry link may survive a raised misconfiguration",
        )

    def test_webhook_misconfiguration_rolls_back_status_not_stuck_executed(self):
        """A misconfigured Ponto bank account must not leave the link "Executed"
        with no Payment Entry and no way to retry (#1362, the #1288/#1323 class).

        `_update_payment_link_status()` already wraps
        `update_status_from_webhook()` in a per-link savepoint (pre-existing, not
        added by this fix); this proves that boundary actually catches the now-
        RAISED misconfiguration and rolls the status write back with it, rather
        than the previous swallow leaving "Executed" committed with nothing to
        show it never actually recorded the payment.
        """
        from verenigingen.verenigingen_payments.ponto.api import webhook_handlers as wh

        member = self._member_with_customer(first_name="PontoWHNoBank")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()
        # No frappe.db.commit() here: wh._update_payment_link_status() below runs
        # in-process on the SAME connection, so the uncommitted status write is
        # already visible to its frappe.get_all()/get_doc() re-read (same-
        # transaction MVCC) without one.
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Authorized")

        self.expectErrorLog("Ponto Payment Entry creation failed", "Payment link webhook status update failed")
        with _no_ponto_bank_account_configured(self.company, self.ponto_account):
            result = wh._update_payment_link_status(request_id=link.ponto_request_id, new_status="executed")

        self.assertEqual(result.get("failed_links"), [link.name], result)
        link.reload()
        self.assertEqual(
            link.status,
            "Authorized",
            "a misconfiguration must roll back the status write, not leave it stuck "
            "at Executed with no Payment Entry",
        )
        self.assertFalse(link.payment_entry)

    def test_guest_permission_refusal_is_still_a_silent_no_op(self):
        """The one exception NOT re-raised by #1362's fix: Guest is refused by
        `frappe.PermissionError`, which stays a legitimate no-op (unchanged
        contract, see test_guest_cannot_create_the_entry) rather than becoming a
        raised misconfiguration - the async job is what actually creates the
        entry for this path, running as the configured webhook user.
        """
        member = self._member_with_customer(first_name="PontoGuestStillNoop")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user("Guest")
        pe_name = create_ponto_payment_entry(link, invoice.name)

        self.assertIsNone(pe_name, "Guest must still be refused silently, not raise")

    def _make_ponto_restricted_user(self):
        """A fresh, non-Guest User carrying a Role with ZERO doctype permissions.

        Named uniquely (not `_make_user_with_roles`/`_make_deskless_role_without_
        perms`, which test_payment_entry_creation_service.py, test_bank_
        transaction_reconciliation.py and test_authorization_coverage.py already
        each carry their own near-identical copy of) so this single-use helper
        does not grow that existing duplicate_helper_validator clone family.
        `_make_` is one of the enforcer's allowed permission-bypass contexts.
        """
        role = frappe.new_doc("Role")
        role.role_name = f"PontoNoPerm {frappe.generate_hash(length=8)}"
        role.desk_access = 1
        role.insert(ignore_permissions=True)
        self.track_doc("Role", role.name)

        user = frappe.new_doc("User")
        user.email = f"ponto-restricted-{frappe.generate_hash(length=10)}@example.com"
        user.first_name = "Ponto Restricted"
        user.send_welcome_email = 0
        user.enabled = 1
        user.append("roles", {"role": role.name})
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user.name

    def test_non_guest_permission_denied_raises_instead_of_silent_no_op(self):
        """A non-Guest user lacking Payment Entry permission is a genuine
        misconfiguration, not Guest's expected refusal (#1362 review finding 2).

        Before this fix, `except frappe.PermissionError: return None` was NOT
        scoped to Guest, so a misconfigured service account - in particular the
        configured webhook user the async process_executed_payment_job runs
        as - would silently return None forever: Executed, no PE, zero Error Log
        rows, and only a warning-level log dropped at the production log level
        (see CLAUDE.md's "Known traps"). Uses a REAL non-Guest user with zero
        Payment Entry permissions, not a mock of the permission check itself.
        """
        member = self._member_with_customer(first_name="PontoRestrictedUser")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)

        restricted_user = self._make_ponto_restricted_user()

        self.expectErrorLog("Ponto Payment Entry creation failed")
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user(restricted_user)
        with self.assertRaises(frappe.PermissionError):
            create_ponto_payment_entry(link, invoice.name)

        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "a refused misconfiguration must leave no Payment Entry behind",
        )

    def test_refresh_status_rolls_back_even_when_the_caller_swallows(self):
        """refresh_status()'s real production callers
        (`templates.pages.ponto_api_debug.refresh_payment_link_status` and
        `ponto.api.betaalverzoek_callback.payment_link_callback`, the customer-
        facing redirect) both wrap the call in a bare `try/except Exception` that
        logs and does NOT re-raise, so Frappe's request-level rollback never
        fires for either of them (#1362 review finding 1). refresh_status() must
        therefore protect itself with its own savepoint rather than depending on
        a caller to propagate the failure.

        Reproduced by calling refresh_status() inside that EXACT swallow shape
        and proving the status does not end up "Executed" with no Payment Entry
        regardless.
        """
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        LINK_CLIENT = (
            "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client."
            "get_betaalverzoek_client"
        )

        member = self._member_with_customer(first_name="PontoRefreshCallerSwallow")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Authorized")
        link.reload()

        fake_client = MagicMock()
        fake_client.get_payment_request.return_value = SimpleNamespace(
            status="executed", debtor_name=None, debtor_iban=None, debtor_bank=None
        )

        self.expectErrorLog(
            "Ponto Payment Entry creation failed", "Ponto payment link status refresh failed"
        )
        with _no_ponto_bank_account_configured(self.company, self.ponto_account):
            with patch(LINK_CLIENT, return_value=fake_client):
                # The EXACT shape both real callers use: log, do NOT re-raise.
                try:
                    link.refresh_status()
                except Exception:
                    pass

        link.reload()
        self.assertNotEqual(
            link.status,
            "Executed",
            "the caller swallowing the exception must not leave the link stuck "
            "Executed with no Payment Entry",
        )
        self.assertFalse(link.payment_entry)

    def _make_third_account_for_default_bank(self):
        """A THIRD real, non-Ponto-named Account, set as `Company.default_bank_account`
        for the ambiguity tests below. Its purpose is to make fallback #3 (the company
        default) reachable and DISTINGUISHABLE from the correct behaviour: if the fix
        ever silently fell through to it instead of refusing, these tests would see a
        successful Payment Entry posted to THIS account rather than the raise they
        assert on - proving the fallthrough is not just "no account configured".
        """
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Bank", "is_group": 1}, "name"
        )
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"Default Bank {frappe.generate_hash(length=6)}",
                "company": self.company,
                "parent_account": parent,
                "account_type": "Bank",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", self.company, "default_currency"),
            }
        ).insert(ignore_permissions=True)
        return account.name

    @contextmanager
    def _company_default_bank_account_set_to_a_third_account(self):
        """Sets `Company.default_bank_account` to a real, non-Ponto account for the
        duration of the block, restoring the original value on exit. Mirrors
        `_no_ponto_bank_account_configured`'s restore shape (no commit needed - same
        connection, same transaction).
        """
        original = frappe.db.get_value("Company", self.company, "default_bank_account")
        third_account = self._make_third_account_for_default_bank()
        frappe.db.set_value("Company", self.company, "default_bank_account", third_account)
        frappe.clear_document_cache("Company", self.company)
        try:
            yield third_account
        finally:
            frappe.db.set_value("Company", self.company, "default_bank_account", original)
            frappe.clear_document_cache("Company", self.company)

    def test_multiple_ponto_accounts_refuses_instead_of_picking_one(self):
        """More than one non-group `%Ponto%` account must REFUSE, not silently pick
        one (#1434). `frappe.db.get_value` with no `order_by` defaults to
        `creation DESC`, so the pre-fix code silently picked whichever account was
        created most recently, with no signal an operator could see.

        `_make_second_ponto_account` is created strictly after `cls.ponto_account`, so it
        is the row `creation DESC` would have picked - this test would stay green
        under a "pick oldest"/`order_by` mutant too, since it asserts a raise
        regardless of which account gets chosen, but it specifically defeats
        "pick newest" because that mutant returns a value (no raise) here.

        Company.default_bank_account is also set to a real THIRD account for the
        duration of the test: the fix must not fall through to it either - that
        would just be another arbitrary pick, and the priority order (setting,
        then a single unambiguous match, then the company default) is preserved
        only when ambiguity itself raises before the company-default branch runs.
        """
        member = self._member_with_customer(first_name="PontoAmbiguous")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        second_account = _make_second_ponto_account(self.company)

        with self._company_default_bank_account_set_to_a_third_account() as third_account:
            self.expectErrorLog("Ponto Payment Entry creation failed")
            with self.assertRaises(frappe.ValidationError) as ctx:
                create_ponto_payment_entry(link, invoice.name)

        message = str(ctx.exception)
        self.assertIn(self.ponto_account, message, "the refusal must name every candidate account")
        self.assertIn(second_account, message, "the refusal must name every candidate account")
        self.assertIn(
            "ponto_bank_account_parent",
            message,
            "the refusal must point at the setting that resolves the ambiguity",
        )
        self.assertFalse(
            frappe.db.exists(
                "Payment Entry", {"reference_no": link.ponto_request_id, "paid_to": third_account}
            ),
            "ambiguity must not silently fall through to the company default account",
        )
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": link.ponto_request_id}),
            "an ambiguous match must leave no Payment Entry behind",
        )

    def test_disabled_ponto_account_is_not_an_ambiguity_candidate(self):
        """A DISABLED `%Ponto%` account must not count towards the ambiguity check
        (#1434 review finding): the issue's own scenario is "an old clearing
        account plus a new one created during a re-configuration" - the old one
        gets disabled, not deleted. ERPNext refuses to post accounting entries
        against a disabled Account at all
        (`general_ledger.validate_disabled_accounts`, confirmed empirically on
        this bench: submitting a Journal Entry referencing a disabled Account
        raises "Cannot create accounting entries against disabled accounts"), so
        a disabled match was never a real posting target and must not force a
        refusal that blocks the one real, enabled candidate.

        The disabled account is created strictly AFTER `cls.ponto_account`, so
        `creation DESC` would prefer IT over the enabled one if the filter were
        missing - this defeats a mutant that merely reorders rather than
        excluding disabled rows.
        """
        member = self._member_with_customer(first_name="PontoDisabledSibling")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        disabled_account = _make_second_ponto_account(self.company, suffix="Old Disabled", disabled=1)
        self.assertEqual(
            frappe.db.get_value("Account", disabled_account, "disabled"),
            1,
            "premise: the sibling account must actually be disabled",
        )

        pe_name = create_ponto_payment_entry(link, invoice.name)

        self.assertIsNotNone(
            pe_name, "a disabled sibling must not force a refusal when one enabled account exists"
        )
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(
            pe.paid_to, self.ponto_account, "the entry must post to the enabled account, not the disabled one"
        )

    def test_ambiguity_rolls_back_status_not_stuck_executed(self):
        """Same contract as `test_webhook_misconfiguration_rolls_back_status_not_stuck_executed`,
        for the ambiguity refusal: the raise must propagate through
        `_update_payment_link_status()`'s per-link savepoint so the status write
        rolls back, rather than committing "Executed" with no Payment Entry and no
        signal anything failed (#1434, the #1362 pattern applied to ambiguity).
        """
        from verenigingen.verenigingen_payments.ponto.api import webhook_handlers as wh

        member = self._member_with_customer(first_name="PontoAmbiguousWH")
        invoice = self._submitted_invoice(member.customer)
        link = self._payment_link(member)
        link.sales_invoice = invoice.name
        link.save()
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Authorized")
        _make_second_ponto_account(self.company)

        self.expectErrorLog("Ponto Payment Entry creation failed", "Payment link webhook status update failed")
        result = wh._update_payment_link_status(request_id=link.ponto_request_id, new_status="executed")

        self.assertEqual(result.get("failed_links"), [link.name], result)
        link.reload()
        self.assertEqual(
            link.status,
            "Authorized",
            "an ambiguous account match must roll back the status write, not leave it "
            "stuck at Executed with no Payment Entry",
        )
        self.assertFalse(link.payment_entry)
