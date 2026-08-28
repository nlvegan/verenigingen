"""
A Mollie reversal must book exactly ONCE, whichever route delivers it.

Two independent code paths book a donation refund, and neither can see the
other's work:

  * the payment-webhook sweep -- ``_process_pending_refunds`` -> Bank Transaction
    + **Journal Entry**, keyed ``{payment_id}_refund_{refund_id}``
  * the refund webhook -- ``handle_refund_webhook`` -> ``create_refund_payment_entry``
    -> **Payment Entry**, keyed with the *same* string

``create_unified_payment_entry`` checks only ``Payment Entry`` for that key, so a
refund already booked as a Journal Entry is booked a second time as a Payment
Entry. The two routes agree on the key and disagree on the doctype (#370).

This is NOT gated by the ``payment_entry_exists`` precondition that blocks
``process_reversal_webhook``: ``handle_refund_webhook`` never calls it.

**``handle_refund_webhook`` no longer books anything itself** -- it parses and
delegates to ``process_reversal_webhook``, so the artefact now follows the forward
booking rather than the route. The direct calls to ``create_refund_payment_entry``
below therefore no longer stand in for that endpoint; they exercise the guard
*inside* ``create_unified_payment_entry``, which is still reachable from the older
donation flow and is what stops the second booking at the last line of defence.

**The defect is symmetric, and closing one direction does not close the other.**
``_process_pending_refunds`` has no reversal-idempotency check of its own at all.
It is protected only by accident: ``_check_refund_processing_state`` builds
``pending_refunds`` from a **Payment-Entry-only** query, so a refund the sweep
itself booked as a Journal Entry is reported pending on every sweep, and the
duplicate is absorbed one layer down by the Bank-Transaction and Journal-Entry
creators, which each dedupe on their own key. Two blind checks covering each
other's blind spots -- and neither can see a *Payment Entry*. So when the refund
webhook wins the race, the sweep books BT + JE on top of the Payment Entry.

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_reversal_single_booking
"""

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import (
    AMBIGUOUS,
    find_booked_payment,
)
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_refund_payment_entry,
    create_unified_payment_entry,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)


def _ensure_mollie_named_bank_account():
    """Get-or-create an Account literally named "Mollie" on COMPANY.

    `create_unified_payment_entry` resolves its bank account in three steps:
    `Mollie Settings.mollie_bank_account`, then an Account named exactly
    "Mollie" on the company, then the company's `default_bank_account`. On a
    clean test site the first is `""` and the third is unset for
    `_Test Company 2`, so the middle one is the only route -- and if it is
    missing the creator returns None from its account-validation branch,
    which reads as "fixture problem" rather than as a missing account.

    Provided as an Account rather than by mutating Mollie Settings: that Single
    is shared with every co-tenant in the shard, and the sweep route reads a
    cached copy of it.

    Module-level and shared by both classes that need it, deliberately. It used
    to be inline in one class's setUp; the other class relied on it having
    already run, which is a dependency the captured-insert drain breaks -- the
    Account is created inside a test, so it is claimed and deleted at that
    test's teardown.
    """
    existing = frappe.get_value("Account", {"company": COMPANY, "account_name": "Mollie"}, "name")
    if existing:
        return existing
    parent = frappe.get_value(
        "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
    )
    acct = frappe.new_doc("Account")
    acct.account_name = "Mollie"
    acct.company = COMPANY
    acct.parent_account = parent
    acct.account_type = "Bank"
    acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
    acct.insert(ignore_permissions=True)
    return acct.name


class TestMollieReversalBooksOnce(_RefundFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Mode of Payment", "Mollie"):
            mop = frappe.new_doc("Mode of Payment")
            mop.mode_of_payment = "Mollie"
            mop.insert(ignore_permissions=True)
        if not frappe.db.exists("Mode of Payment", "Mollie Refund"):
            mop = frappe.new_doc("Mode of Payment")
            mop.mode_of_payment = "Mollie Refund"
            mop.insert(ignore_permissions=True)

        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)

        self.mollie_account = _ensure_mollie_named_bank_account()

        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )

        pin_verenigingen_settings(
            self, company=COMPANY, donation_receivable_account=self.receivable
        )
        # The sweep route books through get_mollie_bank_account_config(), which
        # reads Mollie Settings.
        pin_mollie_clearing_account(self, self.clearing_account)

        self.donor = self._make_donor()
        donor_doc = frappe.get_doc("Donor", self.donor)
        donor_doc.get_or_create_customer()

        self.payment_id = f"tr_dbl_{frappe.generate_hash(length=8)}"
        self.refund_id = f"re_dbl_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id

    def _artefacts_for(self, key):
        """Every submitted-or-draft ledger artefact booked under this reversal key."""
        jes = frappe.get_all(
            "Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        pes = frappe.get_all(
            "Payment Entry", filters={"reference_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        return jes, pes

    def test_refund_delivered_to_both_routes_books_exactly_once(self):
        """The sweep books a JE; the refund webhook must not then book a PE."""
        key = f"{self.payment_id}_refund_{self.refund_id}"

        # --- route 1: the payment-webhook sweep books Bank Transaction + Journal Entry
        bt = self._make_withdrawal_bank_transaction(100.0, key, self.bank_account)
        je_name = self._build_creator().create_refund_journal_entry(
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
            donation_doc=self.donation,
            original_payment_id=self.payment_id,
            bank_transaction_name=bt,
        )
        self.assertTrue(
            je_name, "sweep route did not book its Journal Entry - fixture problem, not the defect"
        )

        jes, pes = self._artefacts_for(key)
        self.assertEqual(len(jes), 1, "expected exactly one JE from the sweep route")
        self.assertEqual(len(pes), 0, "sweep route should not create a Payment Entry")

        # --- route 2: the Payment-Entry booker, the last line of defence
        create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )

        jes, pes = self._artefacts_for(key)
        total = len(jes) + len(pes)
        self.assertEqual(
            total,
            1,
            "the same refund was booked twice under one key "
            f"{key!r}: Journal Entries={jes}, Payment Entries={pes}. "
            "The Payment-Entry route's idempotency check looks only at Payment Entry, "
            "so it cannot see the Journal Entry the sweep already wrote (#370).",
        )

    def test_a_refund_with_no_prior_booking_does_create_a_payment_entry(self):
        """Control for the test above, and it is load-bearing.

        ``create_unified_payment_entry`` is wrapped end-to-end in
        ``except Exception: return None``. Without this control, the
        book-exactly-once assertion above passes just as happily when the Payment
        Entry route is *dead* -- a fixture problem, a missing account, any
        unrelated failure -- as when the new guard is doing its job. A test that
        cannot tell "the guard stopped it" from "it was never going to work"
        measures nothing.
        """
        key = f"{self.payment_id}_refund_{self.refund_id}"
        jes, pes = self._artefacts_for(key)
        self.assertEqual((len(jes), len(pes)), (0, 0), "nothing should be booked yet")

        pe = create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )

        self.assertIsNotNone(
            pe,
            "the Payment Entry route did not book with nothing in its way, so the "
            "book-exactly-once test proves nothing about the guard",
        )
        jes, pes = self._artefacts_for(key)
        self.assertEqual(len(pes), 1, f"expected exactly one Payment Entry, got {pes}")
        self.assertEqual(len(jes), 0, f"the Payment Entry route should not book a JE, got {jes}")

    def test_refund_booked_as_payment_entry_is_not_booked_again_by_the_sweep(self):
        """The other direction: the refund webhook wins, then the sweep runs.

        ``_process_pending_refunds`` never asks whether this reversal is already
        booked. Its Bank-Transaction and Journal-Entry creators each dedupe on
        their own doctype, and ``_check_refund_processing_state`` looks only at
        Payment Entry -- so a Payment Entry booked by the older donation flow is
        invisible to every layer, and the sweep books BT + JE on top of it.
        """
        key = f"{self.payment_id}_refund_{self.refund_id}"

        # --- route 2 first: the refund webhook books a Payment Entry
        pe = create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )
        self.assertIsNotNone(pe, "refund webhook route did not book - fixture problem, not the defect")

        jes, pes = self._artefacts_for(key)
        self.assertEqual(len(pes), 1, "expected exactly one Payment Entry from the refund webhook")
        self.assertEqual(len(jes), 0, "the refund webhook route should not create a Journal Entry")

        # --- route 1: the payment-webhook sweep now processes the same refund as pending
        results = UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation,
            self.payment_id,
            [{"refund_id": self.refund_id, "amount": 100.0, "refund_date": today()}],
        )

        jes, pes = self._artefacts_for(key)
        total = len(jes) + len(pes)
        self.assertEqual(
            total,
            1,
            "the same refund was booked twice under one key "
            f"{key!r}: Journal Entries={jes}, Payment Entries={pes}. "
            "_process_pending_refunds has no reversal-idempotency check of its own; "
            "it must ask find_booked_reversal, which sees every artefact rather than "
            "one doctype (#370).",
        )
        self.assertTrue(results, "the sweep should report what it did, not return silently")


class TestReversalMirrorsTheForwardArtefact(_RefundFixtureMixin, EnhancedTestCase):
    """A reversal must reverse what the forward payment actually posted.

    ``_book_donation_reversal``'s own docstring says "the reversal must mirror the
    artefact the forward payment created" -- but it derives that artefact,
    discards it, and books Bank Transaction + Journal Entry unconditionally.

    The two forward artefacts post different things:

    ==================  =====================================  ======================
    forward booking     GL posting                             recognises income?
    ==================  =====================================  ======================
    Journal Entry       Dr Mollie Clearing / Cr Donation Inc.  yes
    Payment Entry (Rcv) Dr Mollie Bank / Cr Receivable         **no**
    ==================  =====================================  ======================

    So reversing a Payment-Entry-booked donation with a Journal Entry debits
    income that this payment never recognised, and leaves the receivable it *did*
    clear still cleared. Donations booked as Payment Entries are not
    hypothetical: that was the older donation flow.
    """

    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.ensure_mode_of_payment("Mollie Refund", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        # Without this the forward `create_unified_payment_entry` call in this
        # class returns None and the tests fail as "fixture problem" -- which is
        # exactly how they failed in CI on 2026-08-19.
        self.mollie_account = _ensure_mollie_named_bank_account()

        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        pin_verenigingen_settings(
            self, company=COMPANY, donation_receivable_account=self.receivable
        )
        pin_mollie_clearing_account(self, self.clearing_account)

        self.donor = self._make_donor()
        frappe.get_doc("Donor", self.donor).get_or_create_customer()
        self.payment_id = f"tr_mirror_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id

    def _gl_by_account(self, payment_entry_name):
        """{account: (debit, credit)} for a submitted Payment Entry's GL rows."""
        rows = frappe.get_all(
            "GL Entry",
            filters={
                "voucher_type": "Payment Entry",
                "voucher_no": payment_entry_name,
                "is_cancelled": 0,
            },
            fields=["account", "debit", "credit"],
        )
        return {r["account"]: (flt(r["debit"]), flt(r["credit"])) for r in rows}

    def test_a_donation_booked_as_a_payment_entry_is_reversed_by_a_payment_entry(self):
        """The older donation flow booked a Receive PE. Reverse it in kind."""
        forward = create_unified_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            amount=100.0,
            payment_type="Receive",
        )
        self.assertIsNotNone(forward, "forward Payment Entry not booked - fixture problem, not the defect")

        booked = find_booked_payment(self.payment_id)
        self.assertEqual(
            booked,
            ("donation", "Payment Entry", forward.name),
            "the forward artefact should be derived as a donation booked as a Payment Entry",
        )

        refund_id = f"re_mirror_{frappe.generate_hash(length=8)}"
        result = UnifiedWebhookWrapperService().process_reversal_webhook(
            payment_id=self.payment_id,
            reversal_id=refund_id,
            amount=100.0,
            reversal_type="refund",
            reversal_date=today(),
        )
        self.assertEqual(result.get("status"), "success", f"reversal did not book: {result}")

        key = f"{self.payment_id}_refund_{refund_id}"
        jes = frappe.get_all(
            "Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        pes = frappe.get_all(
            "Payment Entry", filters={"reference_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        self.assertEqual(
            (len(pes), len(jes)),
            (1, 0),
            "a donation booked as a Payment Entry must be reversed by a Payment Entry, not a "
            f"Journal Entry that debits income the forward payment never recognised. "
            f"Payment Entries={pes}, Journal Entries={jes}",
        )

        # ---- the reversal must post BACKWARDS, and nothing else asserted that ----
        #
        # Booking the right doctype is not booking the right direction. Every other
        # test in this suite passes if `paid_from`/`paid_to` are swapped in the
        # creator's "Pay" branch, which would make every donation refund post
        # identically to the payment it reverses -- money never leaving, the
        # receivable never restored, and the GL quietly wrong.
        forward_gl = self._gl_by_account(forward.name)
        reversal_gl = self._gl_by_account(pes[0])

        self.assertTrue(forward_gl, "the forward Payment Entry posted no GL entries")
        self.assertEqual(
            set(forward_gl),
            set(reversal_gl),
            "the reversal must touch the same accounts as the payment it reverses",
        )
        for account, (fwd_dr, fwd_cr) in forward_gl.items():
            rev_dr, rev_cr = reversal_gl[account]
            self.assertEqual(
                (rev_dr, rev_cr),
                (fwd_cr, fwd_dr),
                f"on {account} the reversal must mirror the forward posting "
                f"(forward Dr {fwd_dr} / Cr {fwd_cr}, reversal Dr {rev_dr} / Cr {rev_cr})",
            )

        # And name the direction absolutely. These read the accounts from the FIXTURE,
        # not from `forward.paid_to`/`paid_from`: ERPNext always debits `paid_to` and
        # credits `paid_from`, so an assertion derived from the voucher's own fields
        # cannot fail independently of the mirror check above -- it would look
        # absolute and be tautological.
        self.assertGreater(
            reversal_gl[self.mollie_account][1],
            0,
            f"the reversal must CREDIT the bank {self.mollie_account} -- the money leaves",
        )
        self.assertGreater(
            reversal_gl[self.receivable][0],
            0,
            f"the reversal must DEBIT the receivable {self.receivable} -- the claim is restored",
        )

    def _make_forward_journal_entry(self):
        """A forward donation booking: Dr Mollie Clearing / Cr Donation Income."""
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = COMPANY
        je.posting_date = today()
        je.cheque_no = self.payment_id
        je.cheque_date = today()
        je.user_remark = "forward donation booking"
        cost_center = frappe.get_value("Company", COMPANY, "cost_center")
        for account, debit, credit in (
            (self.clearing_account, 100.0, 0),
            (self.income_account, 0, 100.0),
        ):
            je.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit,
                    "credit_in_account_currency": credit,
                    "cost_center": cost_center,
                },
            )
        je.insert(ignore_permissions=True)
        je.submit()
        self.track_test_record("Journal Entry", je.name)
        return je.name

    def test_a_chargeback_is_narrated_as_a_chargeback_and_carries_its_reason(self):
        """A chargeback filed under its own key but described as a REFUND is still unreadable.

        ``reversal_type`` reached the reference key and stopped there: every
        narration string was hardcoded to "REFUND". And ``description`` -- which is
        where the Mollie reason code and text arrive, the single most useful thing
        on a chargeback -- was accepted by the booker and never read.
        """
        self._make_forward_journal_entry()
        chargeback_id = f"chb_{frappe.generate_hash(length=8)}"

        result = UnifiedWebhookWrapperService().process_reversal_webhook(
            payment_id=self.payment_id,
            reversal_id=chargeback_id,
            amount=100.0,
            reversal_type="chargeback",
            reversal_date=today(),
            reason={"code": "AC04", "description": "Account closed"},
        )
        self.assertEqual(result.get("status"), "success", f"chargeback did not book: {result}")

        key = f"{self.payment_id}_chargeback_{chargeback_id}"
        je_name = frappe.db.get_value("Journal Entry", {"cheque_no": key, "docstatus": ["!=", 2]}, "name")
        self.assertTrue(je_name, f"no Journal Entry booked under {key!r}")
        remark = frappe.db.get_value("Journal Entry", je_name, "user_remark") or ""

        self.assertIn("CHARGEBACK", remark, f"chargeback narrated as something else: {remark!r}")
        self.assertNotIn("REFUND", remark, f"chargeback narrated as a refund: {remark!r}")
        self.assertIn("AC04", remark, f"Mollie reason code dropped from the entry: {remark!r}")
        self.assertIn("Account closed", remark, f"Mollie reason text dropped: {remark!r}")

    def test_a_reversal_whose_journal_entry_did_not_post_is_not_reported_as_success(self):
        """A submit that throws still leaves docstatus=1. Success needs a posted ledger.

        Frappe's ``Document.save()`` runs ``db_update()`` **before**
        ``run_post_save_methods()``, and ``on_submit`` is what triggers GL posting.
        So a Journal Entry whose submit raises is already at ``docstatus=1`` in the
        database -- and ``secure_document_operation`` catches the error without
        rolling back (``secure_operations.py:966-985``). The creator then logged
        "(draft)" (it is not a draft) and returned ``je.name`` regardless, so the
        caller's "did I get a name?" success test read a failed posting as success.

        That is not merely a wrong status. ``find_booked_reversal`` counts anything
        with ``docstatus != 2``, so the unposted entry claims the reversal key and
        every one of Mollie's ~10 redeliveries answers "already processed". The
        refund is reported done, permanently, having never reached the ledger.

        The failure is injected with a **group** income account, which ERPNext
        rejects in ``GLEntry.on_update`` -- after the GL row is inserted, which is
        exactly why this state arises at all.
        """
        group_income = frappe.get_value(
            "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
        )
        self.assertTrue(group_income, "need a group income account to make the posting fail")

        previous = frappe.db.get_single_value("Verenigingen Settings", "unrestricted_donation_account")
        frappe.db.set_single_value("Verenigingen Settings", "unrestricted_donation_account", group_income)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        self.addCleanup(frappe.clear_document_cache, "Verenigingen Settings", "Verenigingen Settings")
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Settings",
            "unrestricted_donation_account",
            previous,
        )

        self._make_forward_journal_entry()
        refund_id = f"re_unposted_{frappe.generate_hash(length=8)}"
        key = f"{self.payment_id}_refund_{refund_id}"

        result = UnifiedWebhookWrapperService().process_reversal_webhook(
            payment_id=self.payment_id,
            reversal_id=refund_id,
            amount=100.0,
            reversal_type="refund",
            reversal_date=today(),
        )

        self.assertNotEqual(
            result.get("status"),
            "success",
            f"the ledger was never posted, so this is not a success: {result}",
        )
        self.assertFalse(
            frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name"),
            "an unposted Journal Entry must not be left claiming the reversal key -- "
            "find_booked_reversal counts docstatus != 2, so it would answer "
            "'already processed' to every redelivery of a refund that never reached the ledger",
        )
        live = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": key, "docstatus": ["!=", 2]},
            pluck="name",
        )
        self.assertFalse(
            live,
            "the Journal Entry did not post, so its Bank Transaction must be withdrawn -- "
            f"a live row here is a phantom withdrawal on the clearing account: {live}",
        )

    def test_the_sweep_also_reverses_in_kind_not_always_with_a_journal_entry(self):
        """The payment-webhook sweep must dispatch on the forward artefact too.

        `process_reversal_webhook` was taught to mirror the forward booking, but
        `_process_pending_refunds` -- the route the **payment webhook** actually
        takes, via `_handle_fully_processed_payment` / `_handle_new_payment_processing`
        -- was only taught idempotency, and still books Bank Transaction + Journal
        Entry unconditionally.

        For a donation forward-booked as a Payment Entry that produces exactly the
        posting the dispatch fix exists to prevent: income debited that this payment
        never recognised, and the receivable it *did* clear left cleared. Which
        artefact you end up with is a race between this route and the refund
        webhook, and this one's is wrong.

        Booking once is not the same as booking correctly. `find_booked_reversal`
        gives the first; only dispatch gives the second.
        """
        forward = create_unified_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            amount=100.0,
            payment_type="Receive",
        )
        self.assertIsNotNone(forward, "forward Payment Entry not booked - fixture problem")

        refund_id = f"re_sweep_{frappe.generate_hash(length=8)}"
        key = f"{self.payment_id}_refund_{refund_id}"

        results = UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation,
            self.payment_id,
            [{"refund_id": refund_id, "amount": 100.0, "refund_date": today()}],
        )
        self.assertTrue(results, "the sweep should report what it did")

        jes = frappe.get_all(
            "Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        pes = frappe.get_all(
            "Payment Entry", filters={"reference_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        self.assertEqual(
            (len(pes), len(jes)),
            (1, 0),
            "the sweep reversed a Payment-Entry-booked donation with a Journal Entry: "
            f"Payment Entries={pes}, Journal Entries={jes}. That debits income the "
            "forward payment never recognised and leaves the receivable it cleared "
            "still cleared (#370).",
        )

    def test_withdrawing_a_bank_transaction_cancels_it_and_frees_its_reference(self):
        """The compensating write when a reversal's Journal Entry never arrives.

        The booker writes the Bank Transaction first, so a Journal Entry failure
        would otherwise leave a phantom withdrawal on the clearing account.

        Cancelled, not deleted. ``frappe.model.delete_doc`` runs
        ``check_permission_and_not_submitted`` *before* its ``if not force:`` guard,
        so ``force=True`` cannot remove a submitted document anyway -- and a cancelled
        row is auditable where a deleted one is not. What matters is that the
        reference is free again, so the next delivery books rather than adopting a
        withdrawal that was explicitly undone.

        SCOPE: this covers the compensating write itself. The end-to-end path is
        covered by the group-account test above.
        """
        reference = f"tr_withdraw_{frappe.generate_hash(length=8)}_refund_re_x"
        bt = self._make_withdrawal_bank_transaction(100.0, reference, self.bank_account)
        self.assertEqual(
            frappe.db.get_value("Bank Transaction", bt, "docstatus"),
            1,
            "the fixture must be submitted, or this proves nothing",
        )

        UnifiedWebhookWrapperService()._withdraw_bank_transaction(bt)

        self.assertEqual(
            frappe.db.get_value("Bank Transaction", bt, "docstatus"),
            2,
            f"Bank Transaction {bt} was not cancelled, so it remains a phantom withdrawal",
        )
        self.assertIsNone(
            get_bank_transaction_creator()._check_existing_by_reference(reference),
            "a cancelled Bank Transaction must not be adopted by the next delivery -- "
            "the Journal Entry would then reconcile against a cancelled document, and "
            "that failure is swallowed",
        )


class TestFindBookedPaymentAmbiguity(_RefundFixtureMixin, EnhancedTestCase):
    """Ambiguity must be refused whether or not a Donation exists.

    ``find_booked_payment`` refuses to guess when a Donation is present and both a
    Journal Entry and a Payment Entry claim the payment -- but with no Donation it
    falls through to ``if payment_entry: return ("dues", ...)``, silently
    preferring one artefact. That is the exact behaviour the AMBIGUOUS branch
    exists to prevent, and it misfiles the reversal as dues.
    """

    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.cost_center = frappe.get_value("Company", COMPANY, "cost_center")
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        self.donor = self._make_donor()
        self.customer = frappe.get_doc("Donor", self.donor).get_or_create_customer()

    def _make_balanced_forward_je(self, payment_id):
        """A forward donation booking: Dr Mollie Clearing / Cr Donation Income.

        Named for what it is rather than `_make_submitted_journal_entry`, which
        already exists in `mollie/tests/test_webhook_wrapper_unified_sweep.py` and
        builds something quite different -- an unbalanced single-row stub whose
        docstatus is forced in the DB to skip JE validation. Two builders with one
        name is what the duplicate-helper ratchet flags, and the honest fix is the
        name, since neither can be replaced by the other: this one has to post a
        real balanced entry because the ambiguity lookup reads its GL rows.
        """
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = COMPANY
        je.posting_date = today()
        je.cheque_no = payment_id
        je.cheque_date = today()
        je.user_remark = "forward donation booking (ambiguity fixture)"
        for account, debit, credit in (
            (self.clearing_account, 100.0, 0),
            (self.income_account, 0, 100.0),
        ):
            je.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit,
                    "credit_in_account_currency": credit,
                    "cost_center": self.cost_center,
                },
            )
        je.insert(ignore_permissions=True)
        je.submit()
        self.track_test_record("Journal Entry", je.name)
        return je.name

    def _make_submitted_receive_payment_entry(self, payment_id):
        """A forward donation booking by the older flow: Dr Bank / Cr Receivable."""
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.posting_date = today()
        pe.company = COMPANY
        pe.party_type = "Customer"
        pe.party = self.customer
        pe.paid_amount = 100.0
        pe.received_amount = 100.0
        pe.reference_no = payment_id
        pe.reference_date = today()
        pe.paid_from = self.receivable
        pe.paid_to = self.clearing_account
        pe.cost_center = self.cost_center
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.track_test_record("Payment Entry", pe.name)
        return pe.name

    def test_both_artefacts_without_a_donation_are_ambiguous_not_dues(self):
        payment_id = f"tr_amb_{frappe.generate_hash(length=8)}"
        self.assertFalse(
            frappe.db.exists("Donation", {"payment_id": payment_id}),
            "this test is about the no-Donation path",
        )

        je = self._make_balanced_forward_je(payment_id)
        pe = self._make_submitted_receive_payment_entry(payment_id)

        booked = find_booked_payment(payment_id)
        self.assertIsNotNone(booked, "both artefacts exist, so something is booked")
        self.assertEqual(
            booked[0],
            AMBIGUOUS,
            f"payment {payment_id} is booked as both Journal Entry {je} and Payment Entry {pe}; "
            f"reporting {booked[0]!r} picks one artefact by falling through, which is what the "
            "AMBIGUOUS branch exists to prevent",
        )
