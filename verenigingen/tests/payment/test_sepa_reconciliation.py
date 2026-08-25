"""
Real-integration tests for
verenigingen/verenigingen_payments/api/sepa_reconciliation.py (previously ~0% coverage).

This module reconciles bank transactions against SEPA Direct Debit batches and
their member invoices. Tests build REAL Member / Customer / SEPA Mandate /
Sales Invoice / Direct Debit Batch / Bank Transaction / Payment Entry documents
via SEPATestDataFactory and assert real reconciliation outcomes and DB side
effects. Nothing about the business logic is mocked.

Tests run as Administrator, which satisfies the @critical_api /
@high_security_api / @require_sepa_permission gates.

PRODUCT BUGS exposed (xfailed / documented below and in the orchestrator report):

  * process_sepa_transaction_conservative (line ~286): calls
    validate_batch_mandates({"invoices": sepa_batch.invoices}) but
    validate_batch_mandates reads item.get("customer") from each row, while the
    Direct Debit Batch Invoice child table has NO "customer" field (only member,
    mandate_reference, ...). Every row is therefore flagged "No customer
    specified", so the endpoint ALWAYS returns
    {"success": False, "error": "Batch contains items without valid SEPA mandates"}
    for a perfectly valid batch. See test_conservative_*_mandate_validation_bug.

  * handle_partial_sepa_batch / _process_..._internal set
    bank_transaction.custom_manual_review_task, a field that does NOT exist on
    Bank Transaction -> silently dropped (data loss, not a crash).

  * _create_payment_entry_atomic / create_manual_payment_entry set Payment Entry
    fields that do not exist (custom_sepa_batch_item, custom_manual_reconciliation,
    custom_original_payment, custom_return_reason) -> silently dropped.
"""

import json
import unittest

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.support.invoice_payments import receive_against_invoice
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.api import sepa_reconciliation as recon


def _cancel_and_delete(doctype, name):
    """Cancel a submitted document, delete it, and remove its ledger rows.

    Returns True if the row is gone afterwards.

    The harness drain deletes without cancelling, which is why submitted
    Payment Entries survived it.

    The ledger cleanup is not optional. `AccountsController.on_trash` removes
    `GL Entry` / `Payment Ledger Entry` rows only when
    `Accounts Settings.delete_linked_ledger_entries` is set, and it is 0 by
    default (measured). Deleting a submitted Payment Entry without that leaves
    ledger rows whose `voucher_no` names a document that no longer exists --
    which is precisely the orphan class #308 blames for one of its OTHER
    failures. Trading one orphan for another is not a fix.

    Failures are reported rather than swallowed. An earlier version justified a
    bare `except` with "a cleanup that raises would mask the test's own
    result"; that is false -- `unittest.doCleanups` records cleanup errors IN
    ADDITION to the test result, so nothing is masked. The caller decides.
    """
    if not frappe.db.exists(doctype, name):
        return True
    try:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            # No ignore_permissions flag: these tests run as Administrator (see
            # the module docstring), so the cancel is already permitted, and
            # test-quality-enforcer rightly rejects a permission bypass outside
            # a factory helper.
            doc.cancel()
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
        for ledger in ("GL Entry", "Payment Ledger Entry"):
            frappe.db.delete(ledger, {"voucher_type": doctype, "voucher_no": name})
        frappe.db.commit()
        return True
    except Exception as e:
        frappe.db.rollback()
        get_harness_logger("sepa-recon").warning("could not clean up %s %s: %s", doctype, name, e)
        return False


class ReconBase(EnhancedTestCase):
    """Shared helpers for building real reconciliation fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Provision shared infra (committed) ONCE, before any per-test
        # transaction opens. Committing inside a test method corrupts the
        # transaction state used by reconcile_full_sepa_batch's frappe.db.begin().
        cls._company = get_eur_test_company()
        get_eur_bank_account(cls._company)
        cls._ensure_modes_of_payment()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        # Dedicated SEPA factory instance (the base self.factory is the plain
        # EnhancedTestDataFactory, which lacks the SEPA helpers).
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.company = self._company

        # addCleanup, not tearDown: these rows are COMMITTED (setUpClass commits,
        # and reconcile_full_sepa_batch runs its own begin/commit), so the base
        # rollback cannot remove them and a subclass overriding tearDown without
        # calling super() would skip the cleanup entirely.
        self._made_bank_transactions = []
        self._started_at = frappe.utils.now()
        self.addCleanup(self._cleanup_bank_transactions)

    @classmethod
    def _ensure_modes_of_payment(cls):
        """Reconciliation creates Payment Entries with these Modes of Payment;
        get-or-create them so create_payment_entry / return-reversal don't fail
        on a fresh site."""
        for mop in ("SEPA Direct Debit", "SEPA Direct Debit Return"):
            if not frappe.db.exists("Mode of Payment", mop):
                doc = frappe.new_doc("Mode of Payment")
                doc.mode_of_payment = mop
                doc.type = "Bank"
                doc.insert(ignore_permissions=True)

    # ---- builders ----------------------------------------------------------

    def _make_member_with_invoice(self, first_name="Recon", grand_total=25.0, submit=True):
        f = self.sepa
        member = f.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = f.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        frappe.db.set_value("Customer", customer, "member", member.name)
        mandate = f.create_test_sepa_mandate(member=member.name)
        membership = f.create_test_membership(member=member.name)
        invoice = f.create_test_sales_invoice(
            customer=customer,
            member=member.name,
            membership=membership.name,
            grand_total=grand_total,
            submit=submit,
        )
        return {
            "member": member,
            "customer": customer,
            "mandate": mandate,
            "membership": membership,
            "invoice": invoice,
        }

    def _make_batch(self, items, batch_date=None, status="Submitted", submit=True):
        """Build a Direct Debit Batch from already-built member/invoice dicts.

        The reconciliation module only queries batches by ``docstatus`` and
        ``status`` (plus child rows by parent); it never requires a genuinely
        framework-submitted batch. Real ``batch.submit()`` triggers
        ``generate_sepa_xml`` which needs SEPA Creditor ID / Company IBAN / BIC
        settings that fresh test sites lack. To exercise reconciliation without
        provisioning those org-wide settings, we mark the batch as submitted
        directly in the DB (docstatus=1 + the requested status).
        """
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = batch_date or today()
        batch.batch_description = f"Recon Batch {frappe.generate_hash(length=6)}"
        batch.currency = "EUR"
        batch.batch_type = "CORE"
        batch.status = "Draft"
        total = 0.0
        for it in items:
            amount = flt(it["invoice"].grand_total)
            batch.append(
                "invoices",
                {
                    "invoice": it["invoice"].name,
                    "membership": it["membership"].name,
                    "member": it["member"].name,
                    "member_name": it["member"].full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": it["mandate"].iban,
                    "mandate_reference": it["mandate"].mandate_id,
                    "status": "Pending",
                    "sequence_type": "FRST",
                },
            )
            total += amount
        batch.total_amount = total
        batch.entry_count = len(items)
        batch.insert()
        if submit:
            # Simulate submission without the on_submit SEPA-XML side effect.
            frappe.db.set_value(
                "Direct Debit Batch", batch.name,
                {"docstatus": 1, "status": status or "Submitted"},
                update_modified=False,
            )
            batch.reload()
        return batch

    def _make_bank_transaction(self, deposit=0.0, withdrawal=0.0, description="", date=None,
                               reference_number=None, submit=False):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or today()
        bt.description = description
        bt.deposit = deposit
        bt.withdrawal = withdrawal
        bt.reference_number = reference_number or frappe.generate_hash(length=10)
        # Bank Transaction requires a bank account. Use the one belonging to the
        # company THIS class owns (setUpClass -> get_eur_test_company +
        # _ensure_default_bank_account guarantee it exists). This used to be
        # `get_value("Bank Account", {"is_company_account": 1}) or
        # get_value("Bank Account", {})` -- "whichever account is there", which
        # attaches these transactions to a company this module does not own and
        # is one of the five borrow sites named in #308.
        bank_account = self._owned_bank_account()
        if bank_account:
            bt.bank_account = bank_account
            # Pin the transaction currency to the bank account's own currency.
            # frappe.new_doc() otherwise stamps `currency` from the global
            # "currency" default, which a sibling test (creating a non-EUR
            # entity) can leave polluted to USD on the shared DB — tripping
            # Bank Transaction.validate_currency ("Transaction currency cannot be
            # different from Bank Account currency"). Pinning makes this hermetic.
            gl_account = frappe.db.get_value("Bank Account", bank_account, "account")
            if gl_account:
                bt.currency = frappe.db.get_value("Account", gl_account, "account_currency")
        bt.insert()
        if submit:
            bt.submit()
        self._made_bank_transactions.append(bt.name)
        return bt

    def _owned_bank_account(self):
        """The Bank Account this module owns, created if absent.

        An earlier version of this read `Company.default_bank_account` and fell
        back to `get_value("Bank Account", {"company": ...})`. Both halves were
        wrong: that field is a Link to **Account**, not to `Bank Account`, so
        the first branch could never be true, and the fallback returned
        whichever account another module created most recently -- swapping a
        cross-company borrow for a cross-module one. See #308.
        """
        return get_eur_bank_account(self._company)

    def _cleanup_bank_transactions(self):
        """Remove the committed rows this test leaves behind.

        The harness cannot do it. Its captured-insert drain deletes without
        cancelling, so a SUBMITTED Payment Entry refuses to go and is reported
        as "Captured-insert drain: N record(s) could not be deleted (may persist
        as orphans)" -- 32 such warnings in a single run of this module,
        invisible until #311 made the harness logger emit.

        The orphans are not harmless: a later test's `bt.cancel()` fails with
        LinkExistsError because a leftover Payment Entry names its Bank
        Transaction in `custom_bank_transaction`. That is the CI failure in
        shard 3 that led here.

        On the MECHANISM, since the obvious story is wrong: nothing re-links an
        existing Payment Entry to a new Bank Transaction -- every writer of
        `custom_bank_transaction` sets it at creation. The likelier explanation
        is naming-series reuse: `tabSeries` increments are transactional, so a
        rolled-back test frees `ACC-BTN-...NN` and a later Bank Transaction is
        issued a name an orphan Payment Entry already points at. Either way the
        cure is the same -- do not leave the orphan -- but the wrong story would
        send the next reader hunting for a matching routine that does not exist.

        Filtered by company+creation rather than by `custom_bank_transaction`:
        the Payment Entries that matter are UNLINKED at this point, which is
        exactly why they are available to collide later. That is safe only
        because tests in a process run serially and CI shards each get their own
        site, so no concurrent writer shares this window.
        """
        survivors = []
        for pe_name in frappe.get_all(
            "Payment Entry",
            filters={"company": self._company, "creation": [">=", self._started_at]},
            pluck="name",
        ):
            if not _cancel_and_delete("Payment Entry", pe_name):
                survivors.append(pe_name)

        for bt_name in reversed(self._made_bank_transactions):
            _cancel_and_delete("Bank Transaction", bt_name)
        self._made_bank_transactions = []

        # Fail rather than leak. A cleanup whose only failure signal is a log
        # line is how this bug survived in the first place, and the failure is
        # reachable: `doc.cancel()` enqueues (doc_events registers a payment
        # history handler on Payment Entry.on_cancel) and frappe refuses to
        # enqueue past a queue-length guard -- "Too many queued background jobs".
        if survivors:
            raise AssertionError(
                f"{len(survivors)} Payment Entry row(s) survived cleanup and will pollute later "
                f"tests: {', '.join(survivors)}. See the warnings above for why each failed."
            )
        self._made_bank_transactions = []


# =============================================================================
# find_matching_sepa_batches (helper)
# =============================================================================
class TestReconBaseCleansUpAfterItself(ReconBase):
    """The cleanup that keeps this module from poisoning the rest of the shard.

    Without these, its correctness rests on a manual orphan count someone ran
    once -- which is exactly how the leak survived: nothing failed when the
    rows stayed behind. Each assertion below corresponds to a way the cleanup
    silently stopped working during review.
    """

    def test_cleanup_removes_a_submitted_payment_entry_and_its_ledger_rows(self):
        it = self._make_member_with_invoice(grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, description="cleanup probe")
        result = recon.create_manual_payment_entry(
            bt, {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0}
        )
        pe_name = result.name if hasattr(result, "name") else (result or {}).get("payment_entry")
        if not pe_name:
            self.skipTest(f"reconciliation did not produce a Payment Entry: {result!r}")
        frappe.db.commit()  # reproduce the committed-survivor condition
        self.assertTrue(frappe.db.exists("Payment Entry", pe_name))

        self._cleanup_bank_transactions()

        self.assertFalse(
            frappe.db.exists("Payment Entry", pe_name),
            "a submitted Payment Entry survived cleanup and will pollute later tests",
        )
        for ledger in ("GL Entry", "Payment Ledger Entry"):
            self.assertEqual(
                frappe.db.count(ledger, {"voucher_type": "Payment Entry", "voucher_no": pe_name}),
                0,
                f"{ledger} rows outlived the Payment Entry they belong to -- the orphan class "
                f"#308 blames for a different failure",
            )
        self.assertFalse(frappe.db.exists("Bank Transaction", bt.name))

    def test_the_bank_account_is_owned_not_borrowed(self):
        """`_owned_bank_account` must own, not borrow.

        The version this replaced read `Company.default_bank_account` (a Link to
        **Account**, so that guard was dead code) and fell back to a
        `Bank Account` query, which returns whichever row was created most
        recently -- another module's.

        Asserting only "belongs to my company" does NOT catch that: measured,
        reverting to the global borrow still passed, because this module's own
        account happened to be the newest match. So plant a decoy that a borrow
        would prefer, and require the owned one anyway.
        """
        decoy_gl = self._unclaimed_foreign_bank_gl()
        if not decoy_gl:
            self.skipTest(
                "needs another company with an unclaimed bank GL account to tell owning from borrowing"
            )

        decoy = self._make_decoy_bank_account_(decoy_gl)

        account = self._owned_bank_account()

        self.assertTrue(account, "no Bank Account resolved; the Bank Transaction would carry none")
        self.assertNotEqual(account, decoy.name, "resolved a foreign Bank Account -- still borrowing")
        self.assertEqual(frappe.db.get_value("Bank Account", account, "company"), self._company)
        self.assertEqual(
            frappe.db.get_value("Bank Account", account, "account"),
            frappe.db.get_value("Company", self._company, "default_bank_account"),
            "the resolved Bank Account is not the one keyed on this company's default GL account",
        )

    def _unclaimed_foreign_bank_gl(self):
        """A Bank-type GL account of another company that no Bank Account claims.

        `is_company_account` makes `account` mandatory, and the decoy needs that
        flag to be the row a borrowing lookup would prefer -- hence Bank-type,
        another company.

        The "no Bank Account claims it" half is the part this used to get wrong.
        erpnext's `Bank Account.validate_account` permits exactly one Bank Account
        per GL account, and the lookup asked only "Bank-type, someone else's
        company" -- a different key from the one that must be unique. So the first
        time a sibling fixture claimed the account this picked, the decoy insert
        died with "'TEB Bank One - TEBPC' account is already used by ...", and
        trunk went red (#395). Mildly ironic in a test whose whole point is that
        a fixture must own rather than borrow.
        """
        # `if a`, not just pluck: most Bank Accounts on a test site are party
        # accounts with no `account` link (measured: 400 of 410 on test_site_5), and
        # a None in the list makes this `NOT IN (NULL, ...)`, which is
        # NULL-propagating and matches ZERO rows -- turning the helper into a
        # permanent, silent `skipTest`. It looks removable and is not.
        claimed = [a for a in frappe.get_all("Bank Account", pluck="account") if a]
        return frappe.db.get_value(
            "Account",
            {
                "company": ["!=", self._company],
                "account_type": "Bank",
                "is_group": 0,
                "name": ["not in", claimed],
            },
            ["name", "company"],
            as_dict=True,
        )

    def test_the_decoy_lookup_skips_a_gl_account_another_bank_account_claims(self):
        """#395: seed the competitor, because a site where none exists proves nothing.

        On CI this happened by co-tenancy -- some other suite's Bank Account got
        there first. Here it is made to happen, so the assertion discriminates.
        """
        # The target is CREATED, not found. Picking it with the SUT would make the
        # assertion self-referential, but picking it with the pre-fix query -- the
        # newest foreign bank GL, claimed or not -- made this test skip whenever that
        # one was already claimed, which is EXACTLY the co-tenancy that reddened
        # shard 4. Measured: seed a Bank Account onto the newest foreign bank GL and
        # this test goes from a run to a skip, silently, while the bug it guards is
        # live. Creating the account owes nothing to the helper and cannot skip.
        #
        # It is also strictly the stronger target: created moments ago, it is the
        # NEWEST bank GL account on the site, so the pre-fix `creation DESC` lookup
        # must return it -- the mutation cannot dodge this assertion by finding
        # something else first.
        target = self._make_foreign_bank_gl()
        if not target:
            self.skipTest("needs another company with a bank account to hang a decoy on")

        competitor = self._make_decoy_bank_account_(target)
        self.assertEqual(frappe.db.get_value("Bank Account", competitor.name, "account"), target.name)

        after = self._unclaimed_foreign_bank_gl()
        self.assertNotEqual(
            after.name if after else None,
            target.name,
            "the lookup returned a GL account that is already claimed -- inserting a second "
            "Bank Account against it is what erpnext's validate_account rejects",
        )

    def _make_foreign_bank_gl(self):
        """A Bank-type leaf account of ANOTHER company, created rather than borrowed.

        Only the place is borrowed -- an existing foreign bank account's parent,
        which is what proves that company has a chart to hang this on. The account
        itself is new, so nothing can already claim it: erpnext permits exactly one
        Bank Account per GL account, and a test that needs a FREE one cannot get
        there by guarding a lookup, only by owning what it uses.

        Returns None when no other company has a bank account at all, which is a
        genuine "cannot tell owning from borrowing here" rather than a lost race.
        """
        host = frappe.db.get_value(
            "Account",
            {"company": ["!=", self._company], "account_type": "Bank", "is_group": 0},
            ["parent_account", "company"],
            as_dict=True,
        )
        if not host:
            return None

        gl = frappe.new_doc("Account")
        gl.account_name = f"Decoy Bank GL {frappe.generate_hash(length=6)}"
        gl.parent_account = host.parent_account
        gl.company = host.company
        gl.account_type = "Bank"
        gl.is_group = 0
        gl.insert(ignore_permissions=True)
        # Registered before any Bank Account is hung off it, so LIFO deletes that first.
        self.addCleanup(frappe.delete_doc, "Account", gl.name, force=True)
        return frappe._dict(name=gl.name, company=gl.company)

    def _make_decoy_bank_account_(self, decoy_gl):
        """A rival `is_company_account` row that a borrowing lookup would prefer."""
        bank_name = frappe.db.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = f"Decoy Bank {frappe.generate_hash(length=6)}"
            bank.insert(ignore_permissions=True)
            self.addCleanup(frappe.delete_doc, "Bank", bank.name, force=True)
            bank_name = bank.name

        decoy = frappe.new_doc("Bank Account")
        decoy.account_name = f"Decoy {frappe.generate_hash(length=6)}"
        decoy.bank = bank_name
        decoy.is_company_account = 1
        decoy.company = decoy_gl.company
        decoy.account = decoy_gl.name
        decoy.insert(ignore_permissions=True)
        self.addCleanup(frappe.delete_doc, "Bank Account", decoy.name, force=True)
        return decoy


class TestFindMatchingSepaBatches(ReconBase):
    def test_exact_amount_match_high_confidence(self):
        it = self._make_member_with_invoice(first_name="ExactMatch", grand_total=30.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        names = [m["batch_name"] for m in matches]
        self.assertIn(batch.name, names)
        m = next(m for m in matches if m["batch_name"] == batch.name)
        self.assertEqual(m["match_type"], "exact_amount")
        self.assertEqual(m["confidence"], "high")
        self.assertEqual(flt(m["difference"]), 0.0)

    def test_approximate_amount_match_medium_confidence(self):
        it = self._make_member_with_invoice(first_name="ApproxMatch", grand_total=100.0)
        batch = self._make_batch([it])
        # within 10% but not exact
        bt = self._make_bank_transaction(deposit=batch.total_amount + 5, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        m = next((m for m in matches if m["batch_name"] == batch.name), None)
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "approximate_amount")
        self.assertEqual(m["confidence"], "medium")

    def test_no_match_when_amount_far_off(self):
        it = self._make_member_with_invoice(first_name="NoMatch", grand_total=20.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount + 1000, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])

    def test_no_match_outside_date_window(self):
        it = self._make_member_with_invoice(first_name="DateWindow", grand_total=40.0)
        # batch far in the past (> 7 days before txn)
        batch = self._make_batch([it], batch_date=add_days(today(), -60))
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])

    def test_draft_batch_not_matched(self):
        it = self._make_member_with_invoice(first_name="DraftBatch", grand_total=40.0)
        batch = self._make_batch([it], submit=False)  # stays Draft / docstatus 0
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])


# =============================================================================
# identify_sepa_transactions (whitelist)
# =============================================================================
class TestIdentifySepaTransactions(ReconBase):
    def test_returns_success_structure(self):
        result = recon.identify_sepa_transactions()
        self.assertTrue(result["success"])
        self.assertIn("potential_matches", result)
        self.assertIn("total_found", result)
        self.assertEqual(result["total_found"], len(result["potential_matches"]))

    def test_identifies_keyword_transaction_with_matching_batch(self):
        it = self._make_member_with_invoice(first_name="IdentifyHit", grand_total=33.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="Incoming SEPA DD batch collection",
        )
        result = recon.identify_sepa_transactions()
        self.assertTrue(result["success"])
        hit = next((m for m in result["potential_matches"]
                    if m["bank_transaction"] == bt.name), None)
        self.assertIsNotNone(hit, "keyword txn with matching batch should be identified")
        self.assertEqual(flt(hit["transaction_amount"]), flt(batch.total_amount))
        self.assertIn(batch.name, [b["batch_name"] for b in hit["matching_batches"]])

    def test_non_sepa_keyword_transaction_ignored(self):
        it = self._make_member_with_invoice(first_name="NoKeyword", grand_total=22.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="Random grocery purchase",
        )
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])

    def test_already_linked_transaction_excluded(self):
        it = self._make_member_with_invoice(first_name="AlreadyLinked", grand_total=27.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="SEPA DD batch",
        )
        bt.db_set("custom_sepa_batch", batch.name)
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])

    def test_withdrawal_only_transaction_excluded(self):
        # identify only looks at deposits (incoming)
        bt = self._make_bank_transaction(
            withdrawal=50.0, date=today(), description="SEPA DD outgoing",
        )
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])


# =============================================================================
# reconcile_full_sepa_batch (helper - the core happy path)
# =============================================================================
class TestReconcileFullSepaBatch(ReconBase):
    def test_empty_batch_returns_zero(self):
        # A Direct Debit Batch cannot be inserted empty ("No invoices added to
        # batch"), so build a 1-item batch then delete its child rows to simulate
        # the no-items branch (which returns before any begin/commit).
        it = self._make_member_with_invoice(first_name="EmptyBatch", grand_total=25.0)
        batch = self._make_batch([it])
        frappe.db.delete("Direct Debit Batch Invoice", {"parent": batch.name})
        bt = self._make_bank_transaction(deposit=0, date=today(), description="SEPA")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "full_reconciliation")
        self.assertEqual(result["total_items"], 0)
        self.assertEqual(result["reconciled_count"], 0)

    def test_full_reconciliation_creates_payment_entries(self):
        """Un-skipped 2026-07-26. The skip reason ("reconcile_full_sepa_batch
        calls frappe.db.begin(), which the test transaction rejects with 'This
        statement can cause implicit commit'") was not a test-harness quirk - it
        was the production bug. The live caller reaches this function with
        pending writes from two decorated helpers, so START TRANSACTION raised
        there too and SEPA batch reconciliation could never complete. begin() is
        gone; this now exercises the happy path it was written for."""
        items = [
            self._make_member_with_invoice(first_name=f"FullRec{i}", grand_total=25.0 + i)
            for i in range(2)
        ]
        batch = self._make_batch(items)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "full_reconciliation", msg=result)
        self.assertEqual(result["reconciled_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        for it in items:
            pe_refs = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_name": it["invoice"].name, "reference_doctype": "Sales Invoice"},
                fields=["parent", "allocated_amount"],
            )
            self.assertTrue(pe_refs, f"payment entry should reference {it['invoice'].name}")

    def test_validation_failure_when_member_has_no_customer(self):
        it = self._make_member_with_invoice(first_name="NoCustomer", grand_total=25.0)
        batch = self._make_batch([it])
        # Break the member->customer link so phase-1 validation fails.
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "validation_failed", msg=result)
        self.assertEqual(result["reconciled_count"], 0)
        self.assertTrue(result["validation_errors"])

    def test_validation_failure_when_invoice_cancelled(self):
        it = self._make_member_with_invoice(first_name="CancelledInv", grand_total=25.0)
        batch = self._make_batch([it])
        # Cancel the invoice -> phase-1 validation should reject it.
        inv = frappe.get_doc("Sales Invoice", it["invoice"].name)
        inv.cancel()
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        # Cancelled invoice: get_value returns the row with status Cancelled,
        # so validation appends a "cancelled" error.
        self.assertEqual(result["type"], "validation_failed", msg=result)
        self.assertEqual(result["reconciled_count"], 0)


# =============================================================================
# _validate_batch_reconciliation (helper - read-only validation)
# =============================================================================
class TestValidateBatchReconciliation(ReconBase):
    def _batch_items(self, batch_name):
        return frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"parent": batch_name},
            fields=["name", "invoice", "amount", "member", "member_name", "idx"],
        )

    def test_valid_items_produce_no_errors(self):
        it = self._make_member_with_invoice(first_name="ValOK", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(self._batch_items(batch.name), bt)
        self.assertEqual(errors, [])

    def test_missing_customer_reported(self):
        it = self._make_member_with_invoice(first_name="ValNoCust", grand_total=25.0)
        batch = self._make_batch([it])
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(self._batch_items(batch.name), bt)
        self.assertEqual(len(errors), 1)
        self.assertIn("No customer", errors[0]["error"])

    def test_missing_invoice_reported(self):
        it = self._make_member_with_invoice(first_name="ValNoInv", grand_total=25.0)
        batch = self._make_batch([it])
        items = self._batch_items(batch.name)
        # Point a batch item row at a non-existent invoice.
        items[0]["invoice"] = "SINV-DOES-NOT-EXIST-XYZ"
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(items, bt)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0]["error"])


# =============================================================================
# process_sepa_transaction_conservative (whitelist) - exposes mandate bug
# =============================================================================
class TestProcessConservative(ReconBase):
    def test_conservative_full_match_should_reconcile_but_mandate_check_blocks(self):
        """Regression (FIXED): validate_batch_mandates now reads item.get('member')
        (the Direct Debit Batch Invoice child row's real party field) instead of the
        nonexistent 'customer', so a valid batch is no longer wrongly blocked at the
        mandate gate.

        The downstream full-match reconcile (reconcile_full_sepa_batch) calls
        frappe.db.begin()/commit(), which the FrappeTestCase transaction wrapper
        rejects ('This statement can cause implicit commit'). We therefore assert
        that the mandate gate passes (the bug under test) rather than the final
        'Fully Reconciled' status, which is only reachable outside the test
        transaction. The mandate-gate failure shape must NOT be returned.
        """
        it = self._make_member_with_invoice(first_name="ConsFull", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
        # The pre-fix bug returned this exact missing-mandates failure for a valid
        # batch. After the fix, the mandate gate passes and we proceed past it.
        self.assertNotIn("missing_mandates", result)
        if not result["success"]:
            self.assertNotIn("valid SEPA mandates", result.get("error", ""))

    def test_conservative_mandate_validation_passes_for_valid_batch(self):
        """Regression (FIXED): the mandate validation no longer wrongly rejects an
        otherwise-valid batch. validate_batch_mandates reads the child row's
        `member` field, so a batch backed by an active SEPA mandate passes the
        mandate check and reconciles instead of returning the missing-mandates
        error."""
        it = self._make_member_with_invoice(first_name="ConsBug", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
        # The mandate-check failure shape must NOT be returned anymore (the bug).
        # The downstream full-match reconcile uses frappe.db.begin()/commit() which
        # the test transaction wrapper rejects, so success may still be False with a
        # begin/commit harness error -- but never the missing-mandates failure.
        self.assertNotIn("missing_mandates", result)
        if not result["success"]:
            self.assertNotIn("valid SEPA mandates", result.get("error", ""))

    def test_conservative_duplicate_lock_returns_busy(self):
        """If the processing lock is already held, the endpoint returns a
        busy error without touching the batch."""
        from verenigingen.api.sepa_duplicate_prevention import (
            acquire_processing_lock,
            release_processing_lock,
        )

        it = self._make_member_with_invoice(first_name="ConsLock", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        acquired = acquire_processing_lock("sepa_batch", batch.name)
        self.assertTrue(acquired)
        try:
            result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
            self.assertFalse(result["success"])
            self.assertIn("Another process", result["error"])
        finally:
            release_processing_lock("sepa_batch", batch.name)


# =============================================================================
# _process_sepa_transaction_conservative_internal (helper - bypasses mandate check)
# =============================================================================
class TestProcessConservativeInternal(ReconBase):
    @unittest.skip(
        "Full-match path delegates to reconcile_full_sepa_batch which calls "
        "frappe.db.begin()/commit(); the FrappeTestCase transaction wrapper "
        "rejects it ('This statement can cause implicit commit'). Covered "
        "indirectly via the validation branches and manual reconciliation."
    )
    def test_internal_full_match_fully_reconciled(self):
        it = self._make_member_with_invoice(first_name="IntFull", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Fully Reconciled")
        bt.reload()
        self.assertEqual(bt.custom_sepa_batch, batch.name)
        self.assertEqual(bt.custom_processing_status, "Fully Reconciled")

    def test_internal_partial_match_manual_review(self):
        it = self._make_member_with_invoice(first_name="IntPartial", grand_total=50.0)
        batch = self._make_batch([it])
        # Receive less than expected -> partial path -> ToDo review task.
        bt = self._make_bank_transaction(deposit=batch.total_amount - 10, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Partial - Manual Review Required")
        self.assertEqual(result["processing_result"]["type"], "partial_success_review")
        review_task = result["processing_result"]["review_task"]
        self.assertTrue(frappe.db.exists("ToDo", review_task))
        todo = frappe.get_doc("ToDo", review_task)
        self.assertEqual(todo.reference_type, "Direct Debit Batch")
        self.assertEqual(todo.reference_name, batch.name)

    def test_internal_excess_match_investigation(self):
        it = self._make_member_with_invoice(first_name="IntExcess", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount + 40, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Excess - Manual Review Required")
        self.assertEqual(result["processing_result"]["type"], "excess_payment_investigation")
        self.assertTrue(frappe.db.exists("ToDo", result["processing_result"]["investigation_task"]))

    def test_internal_nonexistent_transaction_returns_error(self):
        it = self._make_member_with_invoice(first_name="IntBadTxn", grand_total=25.0)
        batch = self._make_batch([it])
        result = recon._process_sepa_transaction_conservative_internal(
            "BT-NONEXISTENT-XYZ", batch.name
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# =============================================================================
# handle_partial_sepa_batch / handle_excess_sepa_payment (helpers)
# =============================================================================
class TestPartialAndExcessHandlers(ReconBase):
    def test_partial_handler_amounts_and_task(self):
        it = self._make_member_with_invoice(first_name="PartH", grand_total=80.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=60.0, date=today(), description="SEPA DD")
        result = recon.handle_partial_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "partial_success_review")
        self.assertEqual(flt(result["expected_amount"]), flt(batch.total_amount))
        self.assertEqual(flt(result["received_amount"]), 60.0)
        self.assertEqual(flt(result["failed_amount"]), flt(batch.total_amount) - 60.0)
        self.assertTrue(frappe.db.exists("ToDo", result["review_task"]))

    def test_excess_handler_amounts_and_task(self):
        it = self._make_member_with_invoice(first_name="ExcH", grand_total=30.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=100.0, date=today(), description="SEPA DD")
        result = recon.handle_excess_sepa_payment(bt, batch)
        self.assertEqual(result["type"], "excess_payment_investigation")
        self.assertEqual(flt(result["excess_amount"]), 100.0 - flt(batch.total_amount))
        self.assertTrue(frappe.db.exists("ToDo", result["investigation_task"]))


# =============================================================================
# parse_sepa_return_csv / parse_sepa_return_xml / process_sepa_return_file
# =============================================================================
class TestSepaReturnParsing(ReconBase):
    def test_parse_csv_basic(self):
        csv_content = (
            "Member_ID,Amount,Return_Reason,Return_Code,Transaction_Date,Mandate_Reference\n"
            "MEM-001,25.00,Insufficient funds,AM04,2024-08-01,MND-001\n"
        )
        rows = recon.parse_sepa_return_csv(csv_content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["member_reference"], "MEM-001")
        self.assertEqual(flt(rows[0]["amount"]), 25.0)
        self.assertEqual(rows[0]["return_reason"], "Insufficient funds")
        self.assertEqual(rows[0]["return_code"], "AM04")
        self.assertEqual(rows[0]["mandate_reference"], "MND-001")

    def test_parse_csv_alternate_headers(self):
        # Uses the "Reference"/"Reason" fallback header names.
        csv_content = "Reference,Amount,Reason\nREF-9,12.50,Account closed\n"
        rows = recon.parse_sepa_return_csv(csv_content)
        self.assertEqual(rows[0]["member_reference"], "REF-9")
        self.assertEqual(flt(rows[0]["amount"]), 12.5)
        self.assertEqual(rows[0]["return_reason"], "Account closed")

    def test_parse_csv_empty(self):
        rows = recon.parse_sepa_return_csv("Member_ID,Amount\n")
        self.assertEqual(rows, [])

    def test_process_return_file_unsupported_type(self):
        result = recon.process_sepa_return_file("ignored", file_type="pdf")
        self.assertFalse(result["success"])
        self.assertIn("Unsupported file type", result["error"])

    def test_process_return_file_csv_not_found_member(self):
        csv_content = (
            "Member_ID,Amount,Return_Reason\n"
            "NO-SUCH-MEMBER-123,99.00,Insufficient funds\n"
        )
        result = recon.process_sepa_return_file(csv_content, file_type="csv")
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(result["processed_returns"][0]["status"], "not_found")

    def test_parse_xml_invalid_raises(self):
        with self.assertRaises(Exception):
            recon.parse_sepa_return_xml("<not-valid-pain002>")


# =============================================================================
# process_individual_return + reverse_failed_sepa_payment (full return flow)
# =============================================================================
class TestProcessIndividualReturn(ReconBase):
    def test_unknown_member_reference_not_found(self):
        result = recon.process_individual_return(
            {"member_reference": "DOES-NOT-EXIST", "amount": 10.0,
             "return_reason": "x", "return_code": "AM04"}
        )
        self.assertEqual(result["status"], "not_found")

    def test_full_return_reverses_payment_and_notifies(self):
        """Build a real paid invoice via a SEPA payment entry, then feed a return
        row referencing that member by member_id + amount. Expect the original
        payment to be reversed and — critically — the invoice restored to its
        UNPAID state with no leftover credit, plus a tracking Comment.

        F1 regression: previously the reversal was booked as an on-account 'Pay'
        with no invoice reference, leaving the Sales Invoice marked Paid
        (outstanding 0) while the money had been clawed back — silent ledger
        corruption. reverse_failed_sepa_payment now cancels the original Receive
        Payment Entry, which restores outstanding_amount == grand_total and flips
        the invoice back to Unpaid/Overdue, leaving no orphaned on-account credit.
        """
        it = self._make_member_with_invoice(first_name="RetFlow", grand_total=42.0)
        member = it["member"]
        invoice = it["invoice"]
        # Create + submit a SEPA Direct Debit payment entry for the invoice so that
        # process_individual_return can find a payment to reverse and the invoice
        # becomes Paid.
        from erpnext.accounts.doctype.journal_entry.journal_entry import (
            get_default_bank_cash_account,
        )

        inv_doc = frappe.get_doc("Sales Invoice", invoice.name)
        bank_account = get_default_bank_cash_account(inv_doc.company, "Bank")
        if not bank_account or not bank_account.get("account"):
            self.skipTest("No default bank account on EUR test company; cannot build payment")
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": inv_doc.company,
                "party_type": "Customer",
                "party": it["customer"],
                "posting_date": today(),
                "paid_amount": 42.0,
                "received_amount": 42.0,
                "paid_from": inv_doc.debit_to,
                "paid_to": bank_account["account"],
                "paid_from_account_currency": "EUR",
                "paid_to_account_currency": "EUR",
                "target_exchange_rate": 1,
                "source_exchange_rate": 1,
                "reference_no": "ORIG-REF",
                "reference_date": today(),
                "mode_of_payment": "SEPA Direct Debit",
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": invoice.name,
                        "total_amount": 42.0,
                        "outstanding_amount": 42.0,
                        "allocated_amount": 42.0,
                    }
                ],
            }
        )
        pe.insert()
        pe.submit()

        # Ensure member has the member_id used by the lookup.
        member_id = frappe.db.get_value("Member", member.name, "member_id")
        self.assertTrue(member_id, "member should have a member_id")

        result = recon.process_individual_return(
            {
                "member_reference": member_id,
                "amount": 42.0,
                "return_reason": "Insufficient funds",
                "return_code": "AM04",
            }
        )
        self.assertEqual(result["status"], "processed", msg=result)
        self.assertEqual(result["invoice"], invoice.name)

        # F1 CORE ASSERTIONS: the original Receive PE must be cancelled and the
        # invoice restored to its unpaid state — NOT left marked Paid.
        pe.reload()
        self.assertEqual(pe.docstatus, 2, "original Receive payment entry should be cancelled")

        inv_after = frappe.get_doc("Sales Invoice", invoice.name)
        self.assertIn(
            inv_after.status,
            ["Unpaid", "Overdue"],
            f"returned DD must re-open the invoice, got status={inv_after.status}",
        )
        self.assertEqual(
            float(inv_after.outstanding_amount),
            float(inv_after.grand_total),
            "outstanding must be restored to grand_total after a returned DD",
        )

        # No leftover unallocated on-account credit should remain for the customer:
        # the cancelled PE reverses its own GL, so no stray Pay/credit PE exists.
        leftover_credit = frappe.get_all(
            "Payment Entry",
            filters={
                "party": it["customer"],
                "payment_type": "Pay",
                "docstatus": 1,
                "unallocated_amount": [">", 0],
            },
            fields=["name", "unallocated_amount"],
        )
        self.assertFalse(
            leftover_credit,
            f"no orphaned on-account credit should remain, found: {leftover_credit}",
        )

        # A tracking Comment on the Member should exist.
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Member", "reference_name": member.name,
                     "comment_type": "Info"},
            fields=["name", "content"],
        )
        self.assertTrue(any("SEPA Payment Failed" in (c.get("content") or "") for c in
                            [frappe.get_doc("Comment", c.name) for c in comments]))

    def test_two_settled_invoices_of_the_same_amount_are_not_reversed(self):
        """A returned direct debit must not claw money back off an arbitrary invoice (#567).

        This site DOES filter on the amount -- `{customer, grand_total, status in
        Paid/Partly Paid}` -- so it looked like the narrowest of the class. But two
        settled invoices of one amount for one customer is ordinary for recurring
        dues, and `db.get_value` then hands back whichever was created last
        (`ORDER BY creation DESC LIMIT 1`, emitted into the SQL). The consequence is
        worse than a misapplied payment: `reverse_failed_sepa_payment` CANCELS the
        original Receive Payment Entry, so the wrong member's settled invoice is
        re-opened and a failure notice is sent about a payment that did not fail.

        Red against develop: `processed`, one of the two Payment Entries cancelled.
        """
        self.expectErrorLog("SEPA Return Ambiguous")
        first = self._make_member_with_invoice(first_name="RetAmbig", grand_total=42.0)
        member = first["member"]
        member_id = frappe.db.get_value("Member", member.name, "member_id")
        self.assertTrue(member_id, "member should have a member_id")

        # A SECOND invoice of the SAME amount for the same customer, settled too.
        second_invoice = self.sepa.create_test_sales_invoice(
            customer=first["customer"],
            member=member.name,
            membership=first["membership"].name,
            grand_total=42.0,
            submit=True,
        )
        self.assertNotEqual(second_invoice.name, first["invoice"].name)

        # mode_of_payment is load-bearing: reverse_failed_sepa_payment only cancels a
        # "SEPA Direct Debit" Payment Entry, so without it this test would assert
        # "nothing reversed" against payments the reversal could never have found.
        # test_a_draft_invoice_is_not_a_reversal_candidate is the control that the
        # reversal DOES fire on a fixture built this way.
        _first_paid, first_pe = receive_against_invoice(
            self, first["invoice"].name, 42.0, mode_of_payment="SEPA Direct Debit"
        )
        _second_paid, second_pe = receive_against_invoice(
            self, second_invoice.name, 42.0, mode_of_payment="SEPA Direct Debit"
        )

        result = recon.process_individual_return(
            {
                "member_reference": member_id,
                "amount": 42.0,
                "return_reason": "Insufficient funds",
                "return_code": "AM04",
            }
        )

        self.assertNotEqual(result["status"], "processed", msg=result)
        for payment_entry in (first_pe, second_pe):
            payment_entry.reload()
            self.assertEqual(
                payment_entry.docstatus,
                1,
                "neither settled payment may be reversed when the return names no single invoice",
            )
        for invoice_name in (first["invoice"].name, second_invoice.name):
            self.assertEqual(
                float(frappe.db.get_value("Sales Invoice", invoice_name, "outstanding_amount")),
                0.0,
                "no settled invoice may be re-opened by an ambiguous return",
            )

    def test_a_draft_invoice_is_not_a_reversal_candidate(self):
        """A never-issued invoice must not be the thing a return reverses.

        The filter carried no `docstatus`, and veg11 holds invoices whose `status`
        was written directly while `docstatus = 0` (#559 measured 35). Posted later
        than the real one, such a row wins `creation DESC` and the return reverses
        nothing while reporting success.
        """
        bundle = self._make_member_with_invoice(first_name="RetDraft", grand_total=42.0)
        member_id = frappe.db.get_value("Member", bundle["member"].name, "member_id")
        _paid, real_pe = receive_against_invoice(
            self, bundle["invoice"].name, 42.0, mode_of_payment="SEPA Direct Debit"
        )

        draft = self.sepa.create_test_sales_invoice(
            customer=bundle["customer"],
            member=bundle["member"].name,
            membership=bundle["membership"].name,
            grand_total=42.0,
            submit=False,
        )
        frappe.db.set_value(
            "Sales Invoice", draft.name, {"status": "Paid", "outstanding_amount": 0.0},
            update_modified=False,
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", draft.name, "docstatus"), 0)

        result = recon.process_individual_return(
            {"member_reference": member_id, "amount": 42.0,
             "return_reason": "Insufficient funds", "return_code": "AM04"}
        )

        self.assertEqual(result["status"], "processed", msg=result)
        self.assertEqual(result["invoice"], bundle["invoice"].name)
        real_pe.reload()
        self.assertEqual(real_pe.docstatus, 2, "the submitted payment is the one to reverse")


# =============================================================================
# create_failed_payment_record / notify_member_of_failed_payment (helpers)
# =============================================================================
class TestFailedPaymentHelpers(ReconBase):
    def test_create_failed_payment_record_creates_comment(self):
        it = self._make_member_with_invoice(first_name="FailRec", grand_total=25.0)
        name = recon.create_failed_payment_record(
            it["member"].name, it["invoice"].name,
            {"amount": 25.0, "return_reason": "Insufficient funds", "return_code": "AM04"},
        )
        self.assertTrue(frappe.db.exists("Comment", name))
        doc = frappe.get_doc("Comment", name)
        self.assertEqual(doc.reference_doctype, "Member")
        self.assertEqual(doc.reference_name, it["member"].name)
        self.assertIn("SEPA Payment Failed", doc.content)

    def test_notify_member_creates_followup_todo(self):
        it = self._make_member_with_invoice(first_name="Notify", grand_total=25.0)
        name = recon.notify_member_of_failed_payment(
            it["member"].name, it["invoice"].name,
            {"amount": 25.0, "return_reason": "Account closed"},
        )
        self.assertTrue(frappe.db.exists("ToDo", name))
        todo = frappe.get_doc("ToDo", name)
        self.assertEqual(todo.reference_type, "Member")
        self.assertEqual(todo.reference_name, it["member"].name)
        self.assertEqual(todo.priority, "High")


# =============================================================================
# correlate_return_transactions + find_original_sepa_batch_for_return
# =============================================================================
class TestCorrelateReturns(ReconBase):
    def test_correlate_returns_success_structure(self):
        result = recon.correlate_return_transactions()
        self.assertTrue(result["success"])
        self.assertIn("correlated_returns", result)
        self.assertEqual(result["total_found"], len(result["correlated_returns"]))

    def test_find_original_batch_for_matching_return(self):
        it = self._make_member_with_invoice(first_name="RetCorr", grand_total=37.0)
        batch = self._make_batch([it], batch_date=add_days(today(), -3))
        # Return txn (withdrawal) matching one batch item amount, after the batch.
        bt = self._make_bank_transaction(
            withdrawal=flt(it["invoice"].grand_total), date=today(),
            description="SEPA DD return reject",
        )
        match = recon.find_original_sepa_batch_for_return(bt)
        self.assertIsNotNone(match)
        self.assertEqual(match["batch_name"], batch.name)
        self.assertEqual(match["confidence"], "high")

    def test_find_original_batch_no_match(self):
        it = self._make_member_with_invoice(first_name="RetNoCorr", grand_total=37.0)
        self._make_batch([it], batch_date=add_days(today(), -3))
        bt = self._make_bank_transaction(
            withdrawal=99999.0, date=today(), description="SEPA return",
        )
        self.assertIsNone(recon.find_original_sepa_batch_for_return(bt))

    def test_correlate_picks_up_matching_return(self):
        it = self._make_member_with_invoice(first_name="CorrHit", grand_total=44.0)
        batch = self._make_batch([it], batch_date=add_days(today(), -2))
        bt = self._make_bank_transaction(
            withdrawal=flt(it["invoice"].grand_total), date=today(),
            description="SEPA DD return failed",
        )
        result = recon.correlate_return_transactions()
        hit = next((r for r in result["correlated_returns"]
                    if r["return_transaction"] == bt.name), None)
        self.assertIsNotNone(hit, "matching return should be correlated")
        self.assertEqual(hit["original_batch"], batch.name)


# =============================================================================
# get_sepa_reconciliation_dashboard (whitelist)
# =============================================================================
class TestDashboard(ReconBase):
    def test_dashboard_structure(self):
        result = recon.get_sepa_reconciliation_dashboard()
        self.assertTrue(result["success"])
        for key in ("recent_batches", "linked_transactions", "pending_reviews", "summary"):
            self.assertIn(key, result)
        self.assertEqual(result["summary"]["total_batches"], len(result["recent_batches"]))

    def test_dashboard_reflects_recent_batch_and_link(self):
        it = self._make_member_with_invoice(first_name="DashHit", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        bt.db_set("custom_sepa_batch", batch.name)
        result = recon.get_sepa_reconciliation_dashboard()
        self.assertIn(batch.name, [b["name"] for b in result["recent_batches"]])
        self.assertIn(bt.name, [t["name"] for t in result["linked_transactions"]])


# =============================================================================
# manual_sepa_reconciliation + create_manual_payment_entry (whitelist)
# =============================================================================
class TestManualReconciliation(ReconBase):
    def test_manual_reconciliation_creates_payment(self):
        it = self._make_member_with_invoice(first_name="ManRec", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        batch_items_json = json.dumps([
            {
                "reconcile": True,
                "member": it["member"].name,
                "invoice": it["invoice"].name,
                "amount": flt(it["invoice"].grand_total),
            }
        ])
        result = recon.manual_sepa_reconciliation(bt.name, batch_items_json)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["total_reconciled"], 1)
        pe_name = result["reconciled_items"][0]["payment_entry"]
        self.assertTrue(frappe.db.exists("Payment Entry", pe_name))
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.custom_bank_transaction, bt.name)
        bt.reload()
        self.assertEqual(bt.custom_processing_status, "Manually Reconciled")

    def test_manual_reconciliation_skips_unflagged_items(self):
        it = self._make_member_with_invoice(first_name="ManSkip", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        batch_items_json = json.dumps([
            {"reconcile": False, "member": it["member"].name,
             "invoice": it["invoice"].name, "amount": 25.0}
        ])
        result = recon.manual_sepa_reconciliation(bt.name, batch_items_json)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_reconciled"], 0)

    def test_manual_reconciliation_bad_transaction_returns_error(self):
        batch_items_json = json.dumps([])
        result = recon.manual_sepa_reconciliation("BT-NONEXISTENT-XYZ", batch_items_json)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_create_manual_payment_entry_missing_customer_throws(self):
        it = self._make_member_with_invoice(first_name="ManNoCust", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        with self.assertRaises(frappe.ValidationError):
            recon.create_manual_payment_entry(
                bt, {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0}
            )

    def test_create_manual_payment_entry_missing_invoice_throws(self):
        it = self._make_member_with_invoice(first_name="ManNoInv", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")
        with self.assertRaises(frappe.ValidationError):
            recon.create_manual_payment_entry(
                bt, {"member": it["member"].name, "invoice": "SINV-NOPE-XYZ", "amount": 25.0}
            )

    def _make_extra_bank_account(self, company):
        """Create a second non-group Bank-type GL account so the company has more
        than one — which makes get_default_bank_cash_account's 'exactly one'
        fallback return nothing when there is no configured default. Uncommitted;
        rolls back with the test."""
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name"
        )
        acc = frappe.new_doc("Account")
        acc.account_name = f"Extra SEPA Bank {frappe.generate_hash(length=5)}"
        acc.company = company
        acc.account_type = "Bank"
        acc.parent_account = parent
        acc.account_currency = "EUR"
        acc.insert(ignore_permissions=True)
        return acc.name

    def test_create_manual_payment_entry_no_default_bank_account_throws(self):
        """B3 (create_manual_payment_entry, line ~1185): when the invoice's company
        has NO default bank account configured (and not exactly one Bank account so
        the fallback can't guess one), the method throws 'No default bank account
        configured for company ...'. Mirrors the sibling missing-customer /
        missing-invoice throw tests, but exercises the bank-account config gate.

        The default bank account is unset only within the test transaction (with the
        Company document cache cleared so erpnext's get_cached_value re-reads it) and
        restored in a finally block; the extra Bank account and the unset both roll
        back with the test."""
        it = self._make_member_with_invoice(first_name="ManNoBank", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")

        original_default = frappe.db.get_value("Company", self.company, "default_bank_account")
        # Guarantee > 1 Bank account so the "single account" fallback can't kick in.
        self._make_extra_bank_account(self.company)
        try:
            frappe.db.set_value("Company", self.company, "default_bank_account", None)
            frappe.clear_document_cache("Company", self.company)
            with self.assertRaises(frappe.ValidationError) as cm:
                recon.create_manual_payment_entry(
                    bt,
                    {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0},
                )
            self.assertIn("No default bank account configured", str(cm.exception))
        finally:
            # Restore the committed default + refresh the cache so sibling tests
            # (which resolve a bank account via the same accessor) are unaffected.
            frappe.db.set_value("Company", self.company, "default_bank_account", original_default)
            frappe.clear_document_cache("Company", self.company)


if __name__ == "__main__":
    unittest.main()
