"""
Supplemental real-integration coverage for
verenigingen/verenigingen_payments/utils/bank_transaction_reconciliation.py.

The sibling suite (verenigingen/tests/payment/test_bank_transaction_reconciliation.py)
covers the SEPA matching/reconciliation paths and the pain.002 parser. This module
targets the parts that suite explicitly left uncovered:

  * the Mollie *settlement* reconciliation pipeline
    (match_mollie_settlement live branch, process_mollie_settlement,
    _create_mollie_payment_entry, _create_mollie_fee_entry, and the
    create_reconciliation "mollie_settlement" branch); and
  * a handful of small module helpers / branches
    (resolve_invoice_from_reference, the MEMBER-ID description branch, the
    single-bound date filters, and the process_sepa_return_file accept/reject loop).

The Mollie SettlementsClient is the ONLY thing substituted, and only by swapping
the module-level class name for a hand-rolled stub that returns canned API
payloads (the same `_StubSettlementsClient` boundary pattern used in
test_bulk_transaction_importer_sweep.py). Everything downstream of that HTTP
boundary — invoice matching, Payment Entry creation, fee Journal Entries, amount
validation, duplicate tracking — runs for real against documents built by
SEPATestDataFactory. No business logic is mocked.

PRODUCT BUGS found + fixed here (all in the Mollie settlement pipeline, which
required a live Mollie SettlementsClient and so was never exercised by tests):

  1. _create_mollie_payment_entry set `paid_from = clearing_account`. For a
     "Receive" Payment Entry the party/receivable account IS `paid_from`, so this
     corrupted the party account and ERPNext rejected every settlement payment
     with "... is associated with Debtors, but Party Account is <clearing>". The
     clearing account is the destination, so it must be `paid_to`.
     See TestCreateMolliePaymentEntry.

  2. _create_mollie_fee_entry built a Journal Entry without the mandatory
     `company` field -> "Company is mandatory" whenever settlement fees are booked.
     Fixed by deriving the company from the clearing account's GL account.

  3. _create_mollie_fee_entry also omitted a `cost_center` on the P&L fees row,
     which ERPNext requires (it is NOT auto-filled from the company default during
     JE validation) -> "Cost Center is required for 'Profit and Loss' account ...".
     Fixed by stamping erpnext.get_default_cost_center(company) on each row.
     See TestCreateMollieFeeEntry.test_full_path_creates_balanced_journal_entry.

  4. _create_mollie_payment_entry inserted its Payment Entry unconditionally but
     submitted it only `if frappe.has_permission("Payment Entry", "submit")` (and
     _create_mollie_fee_entry did the same for the fee Journal Entry). Every
     duplicate guard here filters `docstatus: 1`, so the resulting drafts were
     invisible: the settlement read as "nothing posted", stayed retryable, and each
     run inserted another full set. Fixed by refusing the settlement up front, before
     any insert. See TestSettlementSubmitPermission.

DEAD CODE removed (#461): _get_payment_processing_fees_account's final fallback
queried Account with filters={"account_type": "Expense", ...}, but "Expense" is
not a valid ERPNext account_type (the options are "Expense Account",
"Direct Expense", "Indirect Expense", ...). That query could never match, so the
fallback always fell through to the frappe.throw. Since the fallback could never
resolve on any site, deleting it is behaviour-preserving; the method now throws
directly once the pattern-name search is exhausted.
"""

import contextlib
import unittest
from decimal import Decimal
from unittest import mock

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.tests.fixtures.mollie_account_fixtures import provisioned_mollie_settings
from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr


class _StubSettlementsClient:
    """HTTP/SDK boundary stand-in for the Mollie SettlementsClient.

    Only the two read methods the reconciliation code calls are implemented; both
    return canned, test-supplied payloads so the extraction / matching / PE-booking
    / fee logic downstream runs for real.
    """

    settlements = []
    payments = []
    #: One entry per get_settlements_by_date_range call, as (date_from, date_to).
    #: The COUNT is the subject of #546 -- the fetch used to run once per candidate
    #: transaction -- so it has to be observed, not reasoned about.
    windows = []

    def get_settlements_by_date_range(self, date_from, date_to):
        type(self).windows.append((str(date_from), str(date_to)))
        return list(type(self).settlements)

    def get_payments_for_settlement(self, _settlement_id):
        return list(type(self).payments)


class MollieBase(BTRBase):
    """Adds Mollie-settlement fixtures (clearing/fees accounts, client stub).

    Every test in this class books through a Mollie clearing account THIS MODULE
    OWNS on the EUR test company, pinned in `setUp`. That is not tidiness -- it is
    #640.

    Six settlement tests do not open their own `_mollie_settings(...)` context,
    so they used to book against whatever ambient `Mollie Settings` happened to
    hold. Measured on two sites the same day:

    | site | ambient `mollie_clearing_account` | outcome |
    |---|---|---|
    | `test_site_1` | `Mollie - _TC` (the INR `_Test Company`) | **6 failures** |
    | `test_site_2` | `Mollie - TPIC` (the EUR test company) | green |

    On the first, every settlement booking died with "Accounting Entry for
    Mollie - _TC can only be made in currency: INR" -- reported to the test only
    as `ok = False`, with the reason in the Error Log. So this module's result was
    decided by whichever co-tenant last wrote that Single, and CI shard packing
    (which re-packs whenever any test file is edited) chose the co-tenants. That
    is why it looked environment-specific for weeks.

    A test that opens its own `_mollie_settings(...)` still overrides the pin and
    restores back to it, so the nesting is safe.
    """

    def setUp(self):
        super().setUp()
        # Point Mollie Settings at a COHERENT provisioned account set for the whole
        # test, restored (and committed -- see `singleton_backup`) by addCleanup.
        # ExitStack rather than TestCase.enterContext, which is 3.11+; CI runs 3.10.
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self._mollie_accounts = stack.enter_context(provisioned_mollie_settings(company=self.company))
        self._assert_mollie_config_is_bookable()

    def _assert_mollie_config_is_bookable(self):
        """Fail HERE, naming the field, if the config the MANAGER will use cannot book.

        Read back through `self.mgr.config`, not from `self._mollie_accounts`:
        asserting the value the fixture just returned would restate the line above
        it. What can actually go wrong is the pin not reaching the manager --
        `Mollie Settings` is a Single, and the configuration service memoises it in
        `frappe.cache()` under `mollie_settings_cache` with a 300s TTL. That cache is
        site-wide Redis, shared across processes, and it SURVIVES the harness
        rollback, so a stale entry is a live hazard rather than a theoretical one.

        And it asserts in setUp because the failure it replaces surfaced several
        tests later as a bare `assertTrue(ok)` on a reconciliation result, with the
        cause ("can only be made in currency: INR") reachable only through the Error
        Log -- which is how #640 stayed open while the answer sat in one field.
        """
        company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        for label, read_effective, expected in (
            ("clearing", self.mgr.config.get_clearing_account, self._mollie_accounts["clearing_account"]),
            ("bank", self.mgr.config.get_bank_account_gl, self._mollie_accounts["bank_account"]),
            ("fees", self.mgr.config.get_fees_account, self._mollie_accounts["fees_account"]),
        ):
            effective = read_effective()
            self.assertEqual(
                effective,
                expected,
                f"the provisioned {label} account did not reach the manager -- Mollie Settings "
                f"is a Single behind a Redis-cached config, so a write or a cache clear that "
                f"did not take leaves this suite booking against ambient configuration (#640)",
            )
            # Checked before the unpack below, which would otherwise raise
            # `cannot unpack non-iterable NoneType` -- and a vanished account is
            # exactly the drain scenario this pinning exists to survive.
            self.assertTrue(
                frappe.db.exists("Account", effective),
                f"the {label} account {effective} no longer exists",
            )
            owner, currency = frappe.db.get_value("Account", effective, ["company", "account_currency"])
            self.assertEqual(
                owner,
                self.company,
                f"the {label} account {effective} belongs to {owner}, but settlements book "
                f"into {self.company} -- this is #640",
            )
            self.assertIn(
                currency,
                (None, "", company_currency),
                f"the {label} account {effective} is in {currency}, but {self.company} books "
                f"in {company_currency} -- this is #640",
            )

    @contextlib.contextmanager
    def _stub_client(self, settlements=None, payments=None):
        """Swap the module-level SettlementsClient for the canned-payload stub."""
        _StubSettlementsClient.settlements = settlements or []
        _StubSettlementsClient.payments = payments or []
        _StubSettlementsClient.windows = []
        original = btr.SettlementsClient
        btr.SettlementsClient = _StubSettlementsClient
        try:
            yield
        finally:
            btr.SettlementsClient = original

    def _make_gl_account(self, name_prefix, root_type="Asset", account_type=None):
        """Create a leaf GL Account on the EUR test company."""
        company = self.company
        # A Bank leaf goes under the Bank group. Asking only for the newest
        # `root_type` group is the #581 class: 12 Asset groups exist and
        # `get_value` orders `creation DESC`, so it resolves `Temporary Accounts`.
        parent = None
        if account_type == "Bank":
            parent = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
            )
        parent = parent or frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": root_type}, "name"
        )
        acc = frappe.new_doc("Account")
        acc.account_name = f"{name_prefix} {frappe.generate_hash(length=5)}"
        acc.company = company
        acc.parent_account = parent
        acc.account_currency = "EUR"
        if account_type:
            acc.account_type = account_type
        acc.insert(ignore_permissions=True)
        return acc.name

    def _make_party_bank_account(self, gl_account):
        """A NON-company Bank Account on `gl_account`, newer than any existing one.

        Insertable precisely because ERPNext's one-per-GL-account check is gated on
        `is_company_account` -- see the caller.
        """
        bank_name = f"Party Bank {frappe.generate_hash(length=6)}"
        bank = frappe.new_doc("Bank")
        bank.bank_name = bank_name
        bank.insert(ignore_permissions=True)
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Party Acct {frappe.generate_hash(length=6)}"
        ba.bank = bank_name
        ba.is_company_account = 0
        ba.account = gl_account
        ba.insert(ignore_permissions=True)
        return ba.name

    def _ensure_eur_company_cost_center(self):
        """Ensure the EUR test company has a default cost center.

        NOT named ``_ensure_company_cost_center``: ``EnhancedTestCase`` defines a
        method of that name and calls it as ``self._ensure_company_cost_center(
        company_name)`` from ``_ensure_master_data``, which every ``setUp`` runs. A
        same-named helper here overrides it with an incompatible signature, so the
        harness raised "takes 1 positional argument but 2 were given" and EVERY test
        in this module errored in setUp -- the settlement regression tests included.

        ERPNext Journal Entry validation requires a cost center for P&L (Expense)
        accounts and auto-fills it from the company default. Real deployments set
        this; the fresh CI test company may not, so guarantee it here.
        """
        company = self.company
        existing = frappe.db.get_value("Company", company, "cost_center")
        if existing and frappe.db.exists("Cost Center", existing):
            return existing
        cc = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        if cc:
            frappe.db.set_value("Company", company, "cost_center", cc)
            # erpnext.get_default_cost_center reads the cached Company value; drop the
            # stale cache so the just-written default is visible this request.
            frappe.clear_document_cache("Company", company)
        return cc

    @contextlib.contextmanager
    def _mollie_settings(self, clearing_account=None, fees_account=None, bank_account=None):
        """Temporarily set Mollie Settings GL fields (and restore + clear cache)."""
        keys = {
            "mollie_clearing_account": clearing_account,
            "payment_processing_fees_account": fees_account,
            "mollie_bank_account": bank_account,
        }
        original = {k: frappe.db.get_value("Mollie Settings", "Mollie Settings", k) for k in keys}
        for k, v in keys.items():
            if v is not None:
                frappe.db.set_value("Mollie Settings", "Mollie Settings", k, v)
        self.mgr.config.clear_cache()
        try:
            yield
        finally:
            for k, v in original.items():
                frappe.db.set_value("Mollie Settings", "Mollie Settings", k, v)
            self.mgr.config.clear_cache()

    def _stated_costs(self, value, year="2026", month="08"):
        """Mollie's own statement of what it charged, in the API's shape.

        ``periods`` is nested by year and then by month, and each period carries a
        ``costs`` list of ``{description, amountNet: {value, currency}, ...}``. This is
        the only source `_settlement_stated_fee` reads: the fee cannot be derived by
        summing the settlement's payments, because that sum is
        ``fees + refunds + chargebacks``.
        """
        return {
            year: {
                month: {
                    "revenue": [],
                    "costs": [
                        {
                            "description": "Payment fees",
                            "amountNet": {"value": value, "currency": "EUR"},
                        }
                    ],
                }
            }
        }

    def _settlement_payload(self, settlement_id, value, reference=None):
        """A settlement in the API's raw dict shape, as the client returns it.

        ``reference`` is Mollie's own bank reference and is omitted ENTIRELY when
        None -- an absent key and a non-matching value are different states, and
        both have to stay non-postable (#547).
        """
        payload = {"id": settlement_id, "amount": {"value": value, "currency": "EUR"}}
        if reference is not None:
            payload["reference"] = reference
        return payload

    def _match(self, settlement_id, amount="30.00", stated_costs=None):
        """A ``mollie_settlement`` match as ``match_mollie_settlement`` returns one.

        ``stated_costs`` adds Mollie's stated fee to the settlement payload. Without it
        the payload carries no costs, which is a real state (`fee_stated` False) and not
        the same as a stated fee of zero -- so a test that expects a fee entry has to say
        what Mollie charged.
        """
        settlement_data = {"id": settlement_id, "amount": {"value": amount, "currency": "EUR"}}
        if stated_costs is not None:
            settlement_data["periods"] = self._stated_costs(stated_costs)
        return {
            "type": "mollie_settlement",
            "reference": settlement_id,
            "confidence": 0.98,
            "match_reason": "Mollie settlement exact match",
            "settlement_data": settlement_data,
        }

    def _payout_entries(self, settlement_id):
        """The payout legs for a settlement, matched on the tracking field.

        Keyed on ``voucher_type`` as well, because the fee entry carries the SAME
        ``custom_mollie_settlement_id``: the two are told apart by voucher type and
        nothing else.
        """
        return frappe.get_all(
            "Journal Entry",
            filters={
                "custom_mollie_settlement_id": settlement_id,
                "voucher_type": "Bank Entry",
                "docstatus": 1,
            },
            fields=["name", "total_debit"],
        )

    def _fee_entries(self, settlement_id):
        """The fee entry for a settlement. See `_payout_entries` for the discriminator.

        This replaced a `_fee_journal_entries` that matched ANY submitted Journal
        Entry whose free-text `user_remark` contained the settlement id. That was
        wrong twice: it counted the payout leg as a fee entry (so callers asserting
        "exactly one fee entry" broke the moment a complete Mollie configuration let
        the payout leg book at all), and a settlement id like `stl_MIX` carries `_`,
        a single-character LIKE wildcard, unescaped -- the bug class already fixed in
        `reversal_idempotency`, `sepa_mandate_manager` and
        `periodic_donation_operations`. Equality on the tracking field has neither
        problem.
        """
        return frappe.get_all(
            "Journal Entry",
            filters={
                "custom_mollie_settlement_id": settlement_id,
                "voucher_type": "Journal Entry",
                "docstatus": 1,
            },
            fields=["name", "total_debit"],
        )

    def _bt_comments(self, bank_transaction_name):
        return [
            (c.get("content") or "")
            for c in frappe.get_all(
                "Comment",
                filters={
                    "reference_doctype": "Bank Transaction",
                    "reference_name": bank_transaction_name,
                },
                fields=["content"],
            )
        ]

    def _mollie_payment(self, payment_id=None, value="25.00", invoice_id=None, description=None):
        p = {
            "id": payment_id or f"tr_{frappe.generate_hash(length=10)}",
            "amount": {"value": value, "currency": "EUR"},
        }
        if invoice_id is not None:
            p["metadata"] = {"invoice_id": invoice_id}
        if description is not None:
            p["description"] = description
        return p


# =============================================================================
# match_mollie_settlement — live (stubbed) settlement-fetch branch (383-417)
# =============================================================================
class TestMatchMollieSettlementLive(MollieBase):
    def test_amount_match_returns_settlement_match(self):
        """An exact amount on a settlement the bank named -> 0.98.

        The description carries the settlement's `reference`, which is what makes
        the match auto-postable at all (#547). Before that gate this test passed on
        the keyword alone; the tier it is really about -- exact 0.98 vs
        within-tolerance 0.92 -- is unchanged, it just applies to CONFIRMED matches
        now. The unconfirmed tier is TestSettlementReferenceGate's subject.
        """
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=123.45,
            description="Mollie settlement payout REF T13606591.2510.01",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        txn = self._txn_dict(bt)
        settlement = {
            "id": "stl_TESTMATCH",
            "amount": {"value": "123.45", "currency": "EUR"},
            "reference": "13606591.2510.01",
        }
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                match = self.mgr.match_mollie_settlement(txn)
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "mollie_settlement")
        self.assertEqual(match["reference"], "stl_TESTMATCH")
        self.assertEqual(match["confidence"], 0.98)
        self.assertEqual(match["settlement_data"], settlement)

    def test_within_tolerance_lower_confidence(self):
        """A confirmed match still drops 0.98 -> 0.92 when the amount is only
        within tolerance. As above, the description carries the reference so the
        tier under test is the amount tier, not the confirmation gate (#547)."""
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=1000.00,
            description="mollie payout REF T13606591.2510.02",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        txn = self._txn_dict(bt)
        # 0.5 off 1000 is within the 0.1% tolerance window (1.0) -> within_tolerance.
        settlement = {
            "id": "stl_TOL",
            "amount": {"value": "1000.50", "currency": "EUR"},
            "reference": "13606591.2510.02",
        }
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                match = self.mgr.match_mollie_settlement(txn)
        self.assertIsNotNone(match)
        self.assertEqual(match["confidence"], 0.92)

    def test_no_settlement_amount_match_returns_none(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=50.00, description="mollie settlement", date=today(), bank_account=self._eur_bank_account
        )
        txn = self._txn_dict(bt)
        settlement = {"id": "stl_NOPE", "amount": {"value": "9999.00", "currency": "EUR"}}
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))

    def test_zero_deposit_returns_none(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=0.0,
            withdrawal=5.0,
            description="mollie",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        txn = self._txn_dict(bt)
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[{"id": "x", "amount": {"value": "5.00"}}]):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))

    # =============================================================================
    # process_mollie_settlement — the full payment breakdown pipeline (817-979)

    def test_a_later_party_bank_account_does_not_capture_the_gl_account(self):
        """A second Bank Account on the same GL account must not shadow the first (#544).

        ERPNext enforces one Bank Account per GL account in `validate_account()`, which is
        reachable only from `validate_is_company_account()` and so gated on
        `if self.is_company_account:`. `account` carries no `unique` flag and no index.
        Measured: flag=1 then flag=0 against one GL account both insert, while a second
        flag=1 is rejected -- the control. `Bank Account` sorts `creation DESC`.

        So a gate that RESOLVES one docname reads the newest row, and a transaction on the
        older one silently stops matching: #523 reinstated with no signal. Six places in
        this app create Bank Accounts, some for parties.

        This reddens under the resolving form, and also under the
        `is_company_account: 1` filter that looks like the fix -- on test_site_4 the only
        Bank Account on this GL account has that flag clear, so filtering returns None and
        closes the gate outright. Membership survives both.
        """
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        # Created AFTER the suite's own account, so `creation DESC` prefers it.
        party_ba_name = self._make_party_bank_account(bank_gl)
        self.assertEqual(
            frappe.db.get_value("Bank Account", {"account": bank_gl}, "name"),
            party_ba_name,
            "precondition: the resolving lookup must now return the party row, or this "
            "test cannot detect what it exists to detect",
        )

        bt = self._make_bank_transaction(
            deposit=88.88,
            description="Mollie settlement payout",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        settlement = {"id": "stl_PARTY", "amount": {"value": "88.88", "currency": "EUR"}}
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                match = self.mgr.match_mollie_settlement(self._txn_dict(bt))

        self.assertIsNotNone(match, "a later party Bank Account captured the GL account and closed the gate")
        self.assertEqual(match["reference"], "stl_PARTY")

    def test_an_accountless_transaction_is_not_matched(self):
        """`Bank Transaction.bank_account` is not mandatory, so NULL must not match.

        This passes on `develop` too, via the unlinked-account guard, so it is not evidence
        of a live defect -- it pins the `not in` semantics against #538's claim that that
        guard is "behaviourally REDUNDANT". It is not: with the guard removed and a bare
        `!=`, `None != None` is False and an accountless transaction falls through to be
        matched at 0.98 confidence (measured). `not in` holds with an empty set, so the two
        together are defence in depth rather than one of them being spare.
        """
        self.expectErrorLog("No Bank Account record is linked")
        orphan_gl = self._make_gl_account("Mollie Unlinked GL", root_type="Asset", account_type="Bank")
        self.assertIsNone(
            frappe.db.get_value("Bank Account", {"account": orphan_gl}, "name"),
            "precondition: nothing is linked to this GL account",
        )
        bt = self._make_bank_transaction(deposit=77.77, description="Mollie settlement payout", date=today())
        txn = self._txn_dict(bt)
        txn["bank_account"] = None  # the accountless shape

        with self._mollie_settings(bank_account=orphan_gl):
            with self._stub_client(settlements=[{"id": "stl_NULLACCT", "amount": {"value": "77.77"}}]):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))

    def test_the_account_gate_compares_bank_accounts_not_gl_accounts(self):
        """The gate must resolve the configured GL account to its Bank Account.

        ``reconcile_bank_transactions`` selects ``Bank Transaction.bank_account``, which is
        a Link to **Bank Account** (a docname like ``BTR Test Company Account - BTR Test
        Bank``). ``config.get_bank_account_gl()`` returns ``Mollie Settings.mollie_bank_
        account``, which is a **GL Account** name (``10440 - Triodos 1 - TPIC``). Comparing
        them directly can only be equal by naming coincidence: ``Bank Account`` autonames
        ``account_name + " - " + bank`` and ``Account`` autonames
        ``account_name + " - " + abbr``. Measured on veg11: 409 Bank Accounts, **zero**
        where ``name == account``, and zero settlement vouchers across 7,664 Bank
        Transactions -- the gate had never once passed (#523).

        Both directions are asserted, because either one alone is satisfied in the buggy
        world too: under the old code the GL name matched and the Bank Account name did
        not, so a test asserting only "the Bank Account name matches" would look like a
        fixture problem, and one asserting only "the GL name does not match" passed before
        the fix. Together they pin the namespace.
        """
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        linked_bank_account = frappe.db.get_value("Bank Account", {"account": bank_gl}, "name")
        self.assertEqual(
            linked_bank_account,
            self._eur_bank_account,
            "precondition: the suite's Bank Account is the one linked to this GL account",
        )
        self.assertNotEqual(linked_bank_account, bank_gl, "precondition: the two namespaces really do differ")

        settlement = {"id": "stl_NAMESPACE", "amount": {"value": "77.00", "currency": "EUR"}}
        bt = self._make_bank_transaction(
            deposit=77.00,
            description="Mollie settlement payout",
            date=today(),
            bank_account=self._eur_bank_account,
        )

        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                # The real shape: the transaction carries a Bank Account docname.
                on_bank_account = self.mgr.match_mollie_settlement(self._txn_dict(bt))

                # And a transaction whose account is the GL NAME is not this account.
                as_gl_name = self._txn_dict(bt)
                as_gl_name["bank_account"] = bank_gl
                on_gl_name = self.mgr.match_mollie_settlement(as_gl_name)

        self.assertIsNotNone(
            on_bank_account,
            "a deposit on the Bank Account linked to the configured Mollie GL account "
            "must match; comparing the GL account name against Bank Transaction."
            "bank_account never matches, so this gate rejected every transaction",
        )
        self.assertEqual(on_bank_account["reference"], "stl_NAMESPACE")
        self.assertIsNone(
            on_gl_name,
            "a GL account name is not a Bank Account docname and must not match -- if it "
            "does, the comparison is still being made in the wrong namespace",
        )

    def test_a_configured_gl_account_with_no_bank_account_record_is_reported(self):
        """A GL account with no Bank Account record must SAY so, not fail silently.

        The guard is behaviourally redundant -- with no Bank Account resolved, the
        comparison against the transaction's own account returns None either way -- so its
        only effect is the Error Log row, and that is what this asserts. A silent gate is
        exactly how #523 survived: the pipeline simply never matched anything and nothing
        anywhere said why.

        Asserted by querying Error Log directly. ``expectErrorLog`` is a tearDown
        TOLERANCE, not an assertion -- it permits a row, it does not require one -- so it
        cannot stand in for this.
        """
        self.expectErrorLog("No Bank Account record is linked")
        orphan_gl = self._make_gl_account("Mollie Orphan GL", root_type="Asset", account_type="Bank")
        self.assertIsNone(
            frappe.db.get_value("Bank Account", {"account": orphan_gl}, "name"),
            "precondition: nothing is linked to this GL account",
        )
        bt = self._make_bank_transaction(
            deposit=55.00,
            description="Mollie settlement payout",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        marker = frappe.utils.now_datetime()

        with self._mollie_settings(bank_account=orphan_gl):
            with self._stub_client(settlements=[{"id": "stl_ORPHAN", "amount": {"value": "55.00"}}]):
                self.assertIsNone(self.mgr.match_mollie_settlement(self._txn_dict(bt)))

        rows = [
            r
            for r in frappe.get_all(
                "Error Log", filters={"creation": [">=", marker]}, fields=["method", "error"]
            )
            if orphan_gl in f"{r.method}\n{r.error}"
        ]
        self.assertTrue(
            rows,
            "nothing recorded that the configured Mollie bank account has no Bank Account "
            "record, so an operator has no way to learn why settlements never match",
        )


# =============================================================================
class TestProcessMollieSettlement(MollieBase):
    def test_success_invoice_match_books_payment_entry(self):
        it = self._make_member_with_invoice(first_name="MollieSettleOK", grand_total=25.0)
        invoice_name = it["invoice"].name
        bt = self._make_bank_transaction(deposit=25.0, date=today(), bank_account=self._eur_bank_account)
        payment = self._mollie_payment(value="25.00", invoice_id=invoice_name)
        settlement_data = {"id": "stl_OK", "amount": {"value": "25.00", "currency": "EUR"}}
        with self._stub_client(payments=[payment]):
            result = self.mgr.process_mollie_settlement(bt, "stl_OK", settlement_data)
        self.assertEqual(result["type"], "mollie_settlement")
        self.assertEqual(result["total_payments"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["details"][0]["status"], "success")
        # A real submitted Payment Entry now references the invoice.
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_name},
            fields=["parent"],
        )
        self.assertTrue(refs, "Mollie settlement should book a Payment Entry for the invoice")

    def test_mixed_payments_classify_each_outcome(self):
        ok = self._make_member_with_invoice(first_name="MollieMixOK", grand_total=40.0)
        mismatch = self._make_member_with_invoice(first_name="MollieMixBad", grand_total=40.0)
        dup_pid = f"tr_{frappe.generate_hash(length=10)}"
        # Pre-mark one payment id processed so the duplicate branch fires.
        self.mgr._mark_mollie_payment_processed(dup_pid)

        payments = [
            {"amount": {"value": "1.00"}},  # missing id -> error
            self._mollie_payment(
                payment_id=dup_pid, value="5.00", invoice_id=ok["invoice"].name
            ),  # duplicate
            self._mollie_payment(value="40.00", invoice_id=ok["invoice"].name),  # success
            self._mollie_payment(value="5.00", description="Invoice: SINV-NOPE-XYZ-9"),  # invoice_not_found
            self._mollie_payment(value="999.00", invoice_id=mismatch["invoice"].name),  # amount_mismatch
            self._mollie_payment(value="3.00", description="grocery store purchase"),  # no_invoice_match
        ]
        # Settlement value == successful reconciled total (40) so the fee branch is skipped.
        settlement_data = {"id": "stl_MIX", "amount": {"value": "40.00", "currency": "EUR"}}
        with self._stub_client(payments=payments):
            bt = self._make_bank_transaction(deposit=40.0, date=today(), bank_account=self._eur_bank_account)
            result = self.mgr.process_mollie_settlement(bt, "stl_MIX", settlement_data)

        statuses = [d["status"] for d in result["details"]]
        self.assertEqual(result["total_payments"], 6)
        self.assertEqual(result["processed_count"], 1)
        self.assertIn("error", statuses)  # missing id
        self.assertIn("duplicate", statuses)
        self.assertIn("success", statuses)
        self.assertIn("invoice_not_found", statuses)
        self.assertIn("amount_mismatch", statuses)
        self.assertIn("no_invoice_match", statuses)
        self.assertEqual(result["total_reconciled"], "40.00")

    def test_empty_settlement_returns_zero_counts(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        settlement_data = {"id": "stl_EMPTY", "amount": {"value": "0.00"}}
        with self._stub_client(payments=[]):
            result = self.mgr.process_mollie_settlement(bt, "stl_EMPTY", settlement_data)
        self.assertEqual(result["total_payments"], 0)
        self.assertEqual(result["processed_count"], 0)

    def test_client_error_propagates(self):
        class _BoomClient:
            def get_payments_for_settlement(self, _sid):
                raise RuntimeError("mollie api down")

        original = btr.SettlementsClient
        btr.SettlementsClient = _BoomClient
        try:
            bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
            with self.assertRaises(RuntimeError):
                self.mgr.process_mollie_settlement(
                    bt, "stl_BOOM", {"id": "stl_BOOM", "amount": {"value": "0"}}
                )
        finally:
            btr.SettlementsClient = original


# =============================================================================
# create_reconciliation — the "mollie_settlement" match branch (586-616)
# =============================================================================
class TestCreateReconciliationMollieBranch(MollieBase):
    def test_mollie_settlement_branch_reconciles(self):
        it = self._make_member_with_invoice(first_name="MollieRecon", grand_total=30.0)
        bt = self._make_bank_transaction(deposit=30.0, date=today(), bank_account=self._eur_bank_account)
        settlement_data = {"id": "stl_RECON", "amount": {"value": "30.00", "currency": "EUR"}}
        match = {
            "type": "mollie_settlement",
            "reference": "stl_RECON",
            "confidence": 0.98,
            "match_reason": "Mollie settlement exact match",
            "settlement_data": settlement_data,
        }
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertTrue(ok)
        bt.reload()
        self.assertEqual(bt.status, "Reconciled")


# =============================================================================
# create_reconciliation "mollie_settlement" branch under PRODUCTION validation
# =============================================================================
class TestCreateReconciliationMollieBranchProduction(MollieBase):
    """The Mollie branch with ``frappe.flags.in_import`` False, as production runs it.

    ``EnhancedTestCase.setUp`` sets ``in_import = True`` (to bypass user-creation
    throttling). ``BaseDocument._validate_selects()`` early-returns on that flag, so
    the sibling class above never checks that the value the branch writes to
    ``custom_processing_status`` is one of the Custom Field's Select options. In
    production the flag is False and an out-of-options value raises on ``save()`` --
    AFTER ``process_mollie_settlement`` has already inserted and SUBMITTED the
    Payment Entries and the fee Journal Entry, which are not rolled back.
    """

    @contextlib.contextmanager
    def _boom_client(self, message="mollie api down"):
        """Mollie API outage: the settlement fetch fails, so NOTHING is posted."""

        class _BoomClient:
            def get_payments_for_settlement(self, _sid):
                raise RuntimeError(message)

        original = btr.SettlementsClient
        btr.SettlementsClient = _BoomClient
        try:
            yield
        finally:
            btr.SettlementsClient = original

    @contextlib.contextmanager
    def _select_option_not_deployed(self):
        """Reproduce a deploy whose fixtures have not been synced yet: the
        "Mollie Settlement Processed" Select option is absent, so the branch's
        ``save()`` raises -- AFTER ``process_mollie_settlement`` has submitted the
        Payment Entries. This is the exact production incident 4db12397 fixed."""
        field = "Bank Transaction-custom_processing_status"
        original = frappe.db.get_value("Custom Field", field, "options")
        stripped = "\n".join(
            line for line in (original or "").split("\n") if line != "Mollie Settlement Processed"
        )
        frappe.db.set_value("Custom Field", field, "options", stripped, update_modified=False)
        frappe.clear_cache(doctype="Bank Transaction")
        try:
            yield
        finally:
            frappe.db.set_value("Custom Field", field, "options", original, update_modified=False)
            frappe.clear_cache(doctype="Bank Transaction")

    @contextlib.contextmanager
    def _capture_error_logs(self):
        """Collect the Error Log rows written inside the block."""
        marker = frappe.utils.now_datetime()
        before = {
            r.name for r in frappe.get_all("Error Log", filters={"creation": [">=", marker]}, fields=["name"])
        }
        rows = []
        yield rows
        rows.extend(
            r
            for r in frappe.get_all(
                "Error Log",
                filters={"creation": [">=", marker]},
                fields=["name", "method", "error"],
            )
            if r.name not in before
        )

    def test_settlement_reconciles_and_persists_processing_status(self):
        """The happy path must actually reconcile -- and actually book the accounting.

        Every per-payment failure inside ``process_mollie_settlement`` is swallowed
        into the result's ``details`` and the branch still returns True, so status
        assertions alone stay green in a world where ZERO Payment Entries were booked.
        """
        it = self._make_member_with_invoice(first_name="MollieProd", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_PROD")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            # Only the reconciliation call runs with production validation; the
            # fixtures above create Users, which throttle when in_import is False.
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        bt.reload()
        self.assertTrue(
            ok,
            "Mollie settlement reconciliation returned False. Bank Transaction "
            f"status={bt.status!r} custom_processing_status="
            f"{bt.custom_processing_status!r}; comments={self._bt_comments(bt.name)}",
        )
        self.assertEqual(bt.status, "Reconciled")
        self.assertEqual(bt.custom_processing_status, "Mollie Settlement Processed")

        # The deploy-critical artifact: the option must exist on the DEPLOYED Custom
        # Field, not merely in the working copy of fixtures/custom_field.json. On a
        # long-lived site the doc keeps validating against whatever was last synced,
        # so reverting the fixture would otherwise leave this suite green.
        self.assertIn(
            "Mollie Settlement Processed",
            frappe.db.get_value("Custom Field", "Bank Transaction-custom_processing_status", "options"),
        )

        # The accounting really happened.
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            f"no SUBMITTED Payment Entry for Mollie payment {payment['id']}",
        )
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", it["invoice"].name, "outstanding_amount")),
            0.0,
            "the settlement's Payment Entry did not clear the invoice",
        )
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any("Processed 1/1 payments" in c for c in comments),
            f"settlement summary does not report every payment as processed; comments={comments}",
        )

    def test_failure_error_log_keeps_the_traceback(self):
        """``frappe.utils.error.log_error`` takes ``title`` FIRST and, when a second
        argument is given, uses it AS the traceback -- ``frappe.get_traceback()`` is
        never called. ``log_error(f"...{e}", "Some Title")`` therefore writes an Error
        Log row whose stack trace is the literal title string, and swaps the two the
        moment the exception text contains a newline. The stack is the only thing that
        says WHERE a swallowed failure came from."""
        self.expectErrorLog("mollie api down")
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        with self._capture_error_logs() as rows:
            with self._boom_client():
                with self.production_validation():
                    self.mgr.create_reconciliation(self._txn_dict(bt), self._match("stl_TRACE"))

        handler_rows = [r for r in rows if "Mollie Settlement Reconciliation" in f"{r.method}\n{r.error}"]
        self.assertTrue(
            handler_rows,
            f"the Mollie branch handler logged nothing; rows={[r.method for r in rows]}",
        )
        for row in handler_rows:
            # "most recent call last" matches both the plain and the with_context
            # ("Traceback with variables ...") header frappe.get_traceback emits.
            self.assertIn(
                "most recent call last",
                row.error or "",
                f"Error Log row {row.method!r} carries no stack frame -- its 'error' field is "
                f"{row.error!r}, i.e. log_error's title/message arguments were used as the traceback",
            )
            self.assertIn("bank_transaction_reconciliation.py", row.error or "")
            self.assertIn("mollie api down", row.error or "")

    def test_transient_failure_before_posting_stays_retryable(self):
        """A Mollie API outage fails BEFORE anything is posted.

        ``reconcile_bank_transactions`` only ever selects ``{"status": "Pending"}``
        and nothing anywhere moves a Bank Transaction back out of "Unreconciled", so
        marking it Unreconciled removes the deposit from auto-reconciliation forever.
        For a failure that posted no accounting the next run would simply have
        succeeded, so the status must be left alone and only the reason recorded."""
        self.expectErrorLog("mollie api down")
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        with self._boom_client():
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), self._match("stl_RETRY"))

        self.assertFalse(ok)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"custom_mollie_settlement_id": "stl_RETRY"}),
            "staging error: this must be the nothing-was-posted case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Pending",
            "a settlement that failed before posting anything must stay in the "
            "'Pending' auto-reconciliation pool; nothing ever moves an 'Unreconciled' "
            "transaction back, so marking it here makes a transient outage permanent",
        )
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any("mollie api down" in c for c in comments),
            f"no Comment records why the settlement failed; comments={comments}",
        )

    def test_failure_after_posting_marks_unreconciled_without_success_comment(self):
        """The settlement HAS posted (and submitted) its Payment Entries and then the
        save() fails because the Select option is not deployed. The transaction must
        NOT stay retryable -- a re-run cannot re-post the payments (the dedup guard
        skips them), and precisely because of that its fee Journal Entry would be for
        the ENTIRE settlement amount rather than the fees (every payment goes to the
        ``duplicate`` branch, which never adds to ``total_reconciled``) -- and the
        misleading success comment must not be persisted next to the failure."""
        self.expectErrorLog("custom_processing_status", "Mollie Settlement Reconciliation")
        it = self._make_member_with_invoice(first_name="MollieAfterPost", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_AFTERPOST")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            with self._select_option_not_deployed():
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        self.assertFalse(ok)
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            "staging error: nothing was posted, so this is not the after-posting case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Unreconciled",
            "a settlement whose accounting was already posted must be taken out of the "
            "retry pool and put in front of an operator",
        )
        comments = self._bt_comments(bt.name)
        self.assertFalse(
            any("Auto-reconciled" in c for c in comments),
            "add_comment() inserts immediately and is not rolled back by the failing "
            f"save(), so an 'Auto-reconciled' comment ends up directly above "
            f"'Reconciliation failed'; comments={comments}",
        )
        # ...but the settlement summary is factually TRUE on this path -- those Payment
        # Entries really were submitted -- and this is the one place an operator needs
        # to read what got booked before the failure. Suppressing it along with the
        # misleading "Auto-reconciled" line threw away the only record.
        self.assertTrue(
            any("Processed 1/1 payments" in c for c in comments),
            "the failure path lost the settlement summary; an operator looking at an "
            "Unreconciled transaction has no record of the Payment Entries that WERE "
            f"submitted; comments={comments}",
        )

    def test_fee_entry_failure_after_posting_marks_unreconciled(self):
        """The other after-posting shape: ``process_mollie_settlement`` itself raises
        (the fee Journal Entry cannot be booked) AFTER submitting the Payment Entries,
        so it never returns and its result is never bound. Retryability must be decided
        on whether accounting was posted, not on whether that call returned."""
        self.expectErrorLog("stl_FEEBOOM", "Mollie Settlement Reconciliation")
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing FeeBoom", root_type="Asset", account_type="Bank")
        it = self._make_member_with_invoice(first_name="MollieFeeBoom", grand_total=30.0)
        # Mollie kept 1.50 in fees, so the settlement payout is 28.50 -> the fee
        # Journal Entry branch fires, and its fees account does not exist.
        bt = self._make_bank_transaction(
            deposit=28.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_FEEBOOM", amount="28.50", stated_costs="1.50")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._mollie_settings(
            clearing_account=clearing, fees_account="Mollie Fees Account That Does Not Exist"
        ):
            with self._stub_client(payments=[payment]):
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        self.assertFalse(ok)
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            "staging error: nothing was posted, so this is not the after-posting case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Unreconciled",
            "the Payment Entries were already submitted, so this settlement must not "
            "go back into the auto-reconciliation pool",
        )


# =============================================================================
# Settlement-level idempotency + retry bound
# =============================================================================
class TestSettlementIdempotency(MollieBase):
    """A settlement must book its fee Journal Entry AT MOST ONCE, ever.

    ``mollie_fees = total_reconciled - settlement_amount`` and ``total_reconciled``
    is only incremented on the per-payment SUCCESS path. Every other outcome
    (``no_invoice_match``, ``invoice_not_found``, ``amount_mismatch``, and -- on a
    re-run -- ``duplicate``) leaves it at 0, so ``mollie_fees`` becomes
    ``-settlement_amount``, ``abs(...) > 0.01`` passes, and ``_create_mollie_fee_entry``
    inserts and SUBMITS a Journal Entry for the ENTIRE settlement amount booked
    against the payment-processing-fees expense account.

    Before the retryability change this was bounded at one occurrence: any failure
    marked the Bank Transaction "Unreconciled", which permanently removed it from
    the ``{"status": "Pending"}`` pool ``reconcile_bank_transactions`` selects. Now a
    failure that posted nothing stays "Pending", and ``reconcile_bank_transactions``
    is scheduled with no date bound while ``match_mollie_settlement`` re-fetches
    settlements in a +/-3 day window -- so the same settlement is re-matched and the
    bogus Journal Entry re-booked on every run.
    """

    def test_unmatched_settlement_never_books_a_fee_entry(self):
        """No payment resolved to an invoice -> nothing was reconciled -> there are no
        fees to book. The arithmetic says otherwise: ``0 - 30.00`` is a 30.00 "fee",
        i.e. the WHOLE settlement expensed as Mollie charges, once per scheduled run."""
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing NoMatch", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees NoMatch", root_type="Expense")
        settlement_id = f"stl_NOMATCH_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        # A payment whose description carries no invoice reference -> no_invoice_match.
        payment = self._mollie_payment(value="30.00", description="grocery store purchase")

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=[payment]):
                self.mgr.create_reconciliation(self._txn_dict(bt), self._match(settlement_id, "30.00"))
                after_first = self._fee_entries(settlement_id)
                # A second scheduled run re-matches the same settlement.
                btr.PaymentReconciliationManager().create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "30.00")
                )
                after_second = self._fee_entries(settlement_id)

        self.assertEqual(
            after_first,
            [],
            "zero payments were reconciled, so there are no Mollie fees; the entries "
            f"booked expense the full settlement amount: {after_first}",
        )
        self.assertEqual(
            len(after_second),
            len(after_first),
            "the second run booked another fee Journal Entry for the same settlement -- "
            f"unbounded, once per scheduled run: {after_second}",
        )

    def test_rerun_of_processed_settlement_books_exactly_one_fee_entry(self):
        """The settlement really did reconcile (invoice 30.00, payout 28.50 -> 1.50 of
        fees). On a re-run every payment is skipped as a ``duplicate``, which does NOT
        add to ``total_reconciled``, so the fee arithmetic re-books the full 28.50."""
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Rerun", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Rerun", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieRerun", grand_total=30.0)
        settlement_id = f"stl_RERUN_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=28.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=[payment]):
                ok = self.mgr.create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "28.50", stated_costs="1.50")
                )
                self.assertTrue(ok)
                after_first = self._fee_entries(settlement_id)
                # A fresh manager, as the next scheduled run would use (the in-memory
                # dedup set is empty; the DB-backed guard still sees the submitted PE).
                btr.PaymentReconciliationManager().create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "28.50", stated_costs="1.50")
                )
                after_second = self._fee_entries(settlement_id)

        self.assertEqual(len(after_first), 1, f"the first run must book the 1.50 fee once: {after_first}")
        self.assertEqual(
            len(after_second),
            1,
            "re-running the settlement booked a SECOND fee Journal Entry, this one for "
            f"the entire 28.50 payout: {after_second}",
        )
        self.assertEqual(
            frappe.db.get_value("Journal Entry", after_first[0].name, "custom_mollie_settlement_id"),
            settlement_id,
            "the fee Journal Entry must carry the settlement id as a queryable field -- "
            "free-text user_remark is invisible to both the idempotency guard and the "
            "posted-accounting discriminator in _record_settlement_failure",
        )

    def test_repeated_pre_posting_failure_eventually_stops_retrying(self):
        """Leaving a failed-before-posting settlement "Pending" is right for a transient
        outage, but with no cap a permanently broken settlement re-runs -- and re-comments
        -- forever. After a handful of attempts it must be handed to an operator."""
        self.expectErrorLog("mollie api down")
        settlement_id = f"stl_CAP_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )

        class _BoomClient:
            def get_payments_for_settlement(self, _sid):
                raise RuntimeError("mollie api down")

        original = btr.SettlementsClient
        btr.SettlementsClient = _BoomClient
        try:
            for _ in range(5):
                btr.PaymentReconciliationManager().create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "30.00")
                )
        finally:
            btr.SettlementsClient = original

        bt.reload()
        comments = self._bt_comments(bt.name)
        self.assertEqual(
            bt.status,
            "Unreconciled",
            "a settlement that has failed on every attempt must eventually leave the "
            f"retry pool; comments={comments}",
        )
        self.assertTrue(
            any("giving up" in c.lower() for c in comments),
            f"nothing tells the operator the retries were abandoned; comments={comments}",
        )
        retry_comments = [c for c in comments if "will retry" in c]
        self.assertLessEqual(
            len(retry_comments),
            btr.PaymentReconciliationManager.MAX_SETTLEMENT_RETRIES,
            f"one 'will retry' comment per run, unbounded; comments={comments}",
        )


# =============================================================================
# A settlement only PARTLY allocated to invoices (residual of issue #194)
# =============================================================================
class TestPartiallyAllocatedSettlement(MollieBase):
    """A settlement whose payments are only partly matched to invoices must book no
    fees and must not be reported as reconciled.

    ``mollie_fees = total_reconciled - settlement_amount`` and ``total_reconciled``
    counts only the payments THIS run matched to an invoice. 292a8d5c closed the
    degenerate all-or-nothing case (``processed_count == 0`` no longer books an
    entry), but the partial case is the same arithmetic: with 1 of 2 payments
    matched, the value of the UNMATCHED payment is indistinguishable from a Mollie
    charge, and the difference is inserted and SUBMITTED as a
    payment-processing-fees expense.

    It compounds, because that Journal Entry is the settlement-level idempotency
    key (``_existing_settlement_fee_entry``): once the fabricated entry is on the
    ledger the settlement short-circuits forever, so the payments that never
    matched can never be booked.

    The real fee is a fact about the settlement -- what Mollie was paid minus what
    Mollie paid out -- and is knowable from the settlement payload regardless of
    which invoices we found. What invoice matching decides is whether the
    settlement is COMPLETE, and therefore whether it is safe to close it out.
    """

    def _partial_setup(self, tag):
        """Two payments worth 50.00, payout 48.50, and Mollie states 1.50 of costs.
        Only the 30.00 payment carries a resolvable invoice reference.

        The stated fee is the point: it is real and knowable on every run, so a test
        that finds no fee Journal Entry is saying something about the completeness gate
        rather than about missing data."""
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account(f"Mollie Clearing {tag}", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account(f"Payment Processing Fees {tag}", root_type="Expense")
        matched = self._make_member_with_invoice(first_name=f"MolliePart{tag}", grand_total=30.0)
        settlement_id = f"stl_{tag}_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=48.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        return clearing, fees, matched, settlement_id, bt

    def test_partial_settlement_books_no_fee_entry(self):
        """1 of 2 payments matched -> the 20.00 that did not match is booked as
        18.50 of "Mollie fees" (30.00 reconciled - 48.50 payout). The real fee is
        1.50, and it cannot be booked yet because the settlement is not complete."""
        clearing, fees, matched, settlement_id, bt = self._partial_setup("NOFEE")
        payments = [
            self._mollie_payment(value="30.00", invoice_id=matched["invoice"].name),
            self._mollie_payment(value="20.00", description="grocery store purchase"),
        ]

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=payments):
                result = self.mgr.process_mollie_settlement(
                    bt,
                    settlement_id,
                    self._match(settlement_id, "48.50", stated_costs="1.50")["settlement_data"],
                )

        self.assertEqual(result["processed_count"], 1)
        booked = self._fee_entries(settlement_id)
        self.assertEqual(
            booked,
            [],
            "one payment of two was matched, so the settlement is not closed out and "
            "there is nothing to book; the entries here expense the unmatched payment "
            f"as a Mollie charge: {booked}",
        )

    def test_partial_settlement_is_not_reported_as_reconciled(self):
        """The deposit is marked Reconciled even though only 30.00 of the 48.50 was
        allocated. The SEPA batch branch of the same method gates exactly this
        (``allocated_total == deposit_total``); the settlement branch does not."""
        clearing, fees, matched, settlement_id, bt = self._partial_setup("STATUS")
        payments = [
            self._mollie_payment(value="30.00", invoice_id=matched["invoice"].name),
            self._mollie_payment(value="20.00", description="grocery store purchase"),
        ]

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=payments):
                ok = self.mgr.create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "48.50", stated_costs="1.50")
                )

        bt.reload()
        comments = self._bt_comments(bt.name)
        self.assertFalse(
            ok,
            "create_reconciliation reported success for a settlement it only partly allocated",
        )
        self.assertNotEqual(
            bt.status,
            "Reconciled",
            "a deposit whose payments are only partly allocated to invoices must stay "
            f"visible; comments={comments}",
        )
        self.assertTrue(
            any(btr.PaymentReconciliationManager.RETRY_COMMENT_MARKER in c for c in comments),
            f"nothing on the transaction says the settlement is incomplete; comments={comments}",
        )
        self.assertEqual(
            frappe.db.get_value("Bank Transaction", bt.name, "custom_processing_status"),
            "Partial - Manual Review Required",
            "an operator has to be able to FILTER for these, not read every Comment",
        )

    def test_completing_a_partial_settlement_books_the_true_fee_once(self):
        """Run 1 matches only the 30.00 payment; run 2, with the second reference now
        resolvable, matches the 20.00 one. On run 2 the first payment is a
        ``duplicate``, so ``total_reconciled`` sees 20.00 alone and the arithmetic
        gives a 28.50 "fee". The settlement's fee is 1.50 -- gross 50.00 minus the
        48.50 payout -- and must be booked exactly once, when it completes.

        Only the stub's payload changes between runs, and the payment ids do not:
        the second payment's invoice reference is unresolvable on run 1 and
        resolvable on run 2, which is what "the invoice showed up later" looks like
        at this boundary.
        """
        clearing, fees, matched, settlement_id, bt = self._partial_setup("COMPLETE")
        late = self._make_member_with_invoice(first_name="MollieLate", grand_total=20.0)
        first = self._mollie_payment(value="30.00", invoice_id=matched["invoice"].name)
        second_id = f"tr_{frappe.generate_hash(length=10)}"
        unresolved = self._mollie_payment(
            payment_id=second_id, value="20.00", description="grocery store purchase"
        )
        resolved = self._mollie_payment(payment_id=second_id, value="20.00", invoice_id=late["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=[first, unresolved]):
                self.mgr.create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "48.50", stated_costs="1.50")
                )
            after_first = self._fee_entries(settlement_id)
            with self._stub_client(payments=[first, resolved]):
                # A fresh manager, as the next scheduled run would use.
                btr.PaymentReconciliationManager().create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "48.50", stated_costs="1.50")
                )
            after_second = self._fee_entries(settlement_id)

        self.assertEqual(after_first, [], f"nothing to book while the settlement is partial: {after_first}")
        self.assertEqual(
            len(after_second),
            1,
            f"the completing run must book the settlement fee exactly once: {after_second}",
        )
        self.assertEqual(
            flt(after_second[0].total_debit, 2),
            1.50,
            "the fee is the settlement gross (50.00) minus the payout (48.50); the "
            "amount booked here is whatever the LAST run happened to reconcile: "
            f"{after_second}",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Reconciled",
            f"the completed settlement must close the deposit; comments={self._bt_comments(bt.name)}",
        )


# =============================================================================
# Where the fee AMOUNT comes from
# =============================================================================
class TestSettlementFeeSource(MollieBase):
    """The fee is read from the settlement, not derived from its payments.

    Summing the payments and subtracting the payout looks equivalent, and on a
    settlement of nothing but payments it is. It stops being equivalent the moment the
    settlement carries a refund or a chargeback: those are separate Mollie endpoints
    (``list_settlement_refunds`` / ``list_settlement_chargebacks``) and never appear in
    ``get_payments_for_settlement``, so ``sum(payments) - payout`` is
    ``fees + refunds + chargebacks``. The refunded amount would be expensed as a payment
    processing fee -- and because the fee Journal Entry is the settlement-level
    idempotency key, no later run can correct it.

    This test exists because every other test in this file has a settlement whose
    payments minus payout happens to EQUAL the stated fee, so all of them stay green
    under the wrong arithmetic. Verified: replacing ``_settlement_stated_fee`` with
    ``sum(payments) - payout`` leaves the other 41 tests passing and fails only this one.
    """

    def test_a_refund_in_the_settlement_is_not_expensed_as_a_fee(self):
        """500.00 of payments, a 200.00 refund of an earlier payment, 7.50 of Mollie
        costs -> a 292.50 payout. Both payments match their invoices, so the settlement
        is complete and the fee is booked. It must be the 7.50 Mollie states, not the
        207.50 the payout is short."""
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Refund", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Refund", root_type="Expense")
        first = self._make_member_with_invoice(first_name="MollieRefundA", grand_total=250.0)
        second = self._make_member_with_invoice(first_name="MollieRefundB", grand_total=250.0)
        settlement_id = f"stl_REFUND_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=292.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payments = [
            self._mollie_payment(value="250.00", invoice_id=first["invoice"].name),
            self._mollie_payment(value="250.00", invoice_id=second["invoice"].name),
        ]

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=payments):
                result = self.mgr.create_reconciliation(
                    self._txn_dict(bt), self._match(settlement_id, "292.50", stated_costs="7.50")
                )

        self.assertTrue(result, f"the settlement is complete; comments={self._bt_comments(bt.name)}")
        booked = self._fee_entries(settlement_id)
        self.assertEqual(len(booked), 1, f"one fee entry for a completed settlement: {booked}")
        self.assertEqual(
            flt(booked[0].total_debit, 2),
            7.50,
            "the fee must be what Mollie stated it charged. 207.50 here means it was "
            "derived as payments-minus-payout, which books the refunded 200.00 as a "
            f"processing fee: {booked}",
        )


# =============================================================================
# Settlement processing when the acting user cannot SUBMIT (issue #210)
# =============================================================================
class TestSettlementSubmitPermission(MollieBase):
    """A settlement must post everything or nothing -- never inserted-but-unsubmitted.

    ``_create_mollie_payment_entry`` used to ``insert()`` unconditionally and
    ``submit()`` only ``if frappe.has_permission("Payment Entry", "submit")``, and
    ``_create_mollie_fee_entry`` had the same shape for the fee Journal Entry. Every
    guard downstream filters ``docstatus: 1`` -- ``_is_mollie_payment_processed``,
    ``_existing_settlement_fee_entry`` and ``_settlement_has_posted_accounting`` --
    so a draft is invisible to all of them. Run 1 inserted N drafts and left the
    transaction retryable; run 2 saw "nothing posted" and inserted another N. No GL
    impact until someone bulk-submits them, at which point the invoices are
    over-allocated.

    The permission is simulated for real: a User with ``System Manager`` (Mollie
    Settings access + Bank Transaction write) and ``Accounts User`` (Payment Entry
    create), with SUBMIT revoked from that role through the same Custom DocPerm
    mechanism the Role Permission Manager uses. That is an ordinary "clerks prepare,
    managers submit" setup, not a patched ``frappe.has_permission``.
    """

    # The role that carries Payment Entry / Journal Entry create+submit in ERPNext.
    # Revoking only its `submit` is what an administrator does to split preparation
    # from posting.
    NO_SUBMIT_ROLE = "Accounts User"

    def _clerk_user(self):
        """A real User who may CREATE the settlement's documents but not SUBMIT them."""
        email = f"mollie.clerk.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Mollie"
        user.last_name = "Clerk"
        user.enabled = 1
        user.send_welcome_email = 0
        # System Manager: Mollie Settings (MollieConfigurationService.ALLOWED_ROLES)
        # and Bank Transaction write. Accounts User: Payment Entry create.
        user.append("roles", {"role": "System Manager"})
        user.append("roles", {"role": self.NO_SUBMIT_ROLE})
        user.insert()
        return email

    @contextlib.contextmanager
    def _submit_revoked(self, doctype, user):
        """Actually revoke SUBMIT on *doctype* from every role *user* holds.

        ``setup_custom_perms`` is what the Role Permission Manager calls before any
        customisation: it copies the standard DocPerms into Custom DocPerm rows (and
        is a no-op when the DocType is already customised, which both Payment Entry
        and Journal Entry are in this app). Flipping ``submit`` on the rows is then
        exactly what an administrator does in the UI.

        Every one of the user's roles has to be covered, not just the accounting one:
        this app ships a ``Custom DocPerm-Journal Entry-System Manager`` row with
        ``submit`` set, so revoking only ``Accounts User`` would leave the right
        intact and the test would silently stop testing anything.
        """
        from frappe.permissions import setup_custom_perms

        setup_custom_perms(doctype)
        user_roles = set(frappe.get_roles(user))
        rows = [
            row.name
            for row in frappe.get_all(
                "Custom DocPerm", filters={"parent": doctype, "submit": 1}, fields=["name", "role"]
            )
            if row.role in user_roles
        ]
        self.assertTrue(rows, f"staging error: {user} holds no SUBMIT right on {doctype} to revoke")
        for name in rows:
            frappe.db.set_value("Custom DocPerm", name, "submit", 0)
        frappe.clear_cache(doctype=doctype)
        # The DB writes are undone by the per-test rollback, but the meta cache is
        # rebuilt lazily; clear it again after that rollback so no later test in the
        # shard inherits a customised permission set.
        self.addCleanup(frappe.clear_cache, doctype=doctype)
        try:
            yield
        finally:
            for name in rows:
                frappe.db.set_value("Custom DocPerm", name, "submit", 1)
            frappe.clear_cache(doctype=doctype)

    @contextlib.contextmanager
    def _as(self, user):
        original = frappe.session.user
        frappe.set_user(user)
        try:
            yield
        finally:
            frappe.set_user(original)

    def _settlement_entries(self, settlement_id):
        """EVERY document this settlement booked, at ANY docstatus.

        Deliberately unfiltered by ``docstatus``: the whole defect is that the
        production guards cannot see docstatus 0, so a test that filtered the same
        way would be blind to exactly the rows it must catch.
        """
        found = []
        for doctype in ("Payment Entry", "Journal Entry"):
            found.extend(
                (doctype, row.name, row.docstatus)
                for row in frappe.get_all(
                    doctype,
                    filters={"custom_mollie_settlement_id": settlement_id},
                    fields=["name", "docstatus"],
                )
            )
        return sorted(found)

    def test_without_payment_entry_submit_rights_nothing_is_posted_or_multiplied(self):
        """The reported defect. Two runs by a user who cannot submit Payment Entries
        must leave ZERO settlement documents behind -- not N drafts, and certainly not
        2N."""
        self.expectErrorLog("Insufficient permissions to submit")
        it = self._make_member_with_invoice(first_name="MollieNoSubmit", grand_total=30.0)
        clerk = self._clerk_user()
        settlement_id = f"stl_NOSUBMIT_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._stub_client(payments=[payment]):
            with self._submit_revoked("Payment Entry", clerk):
                with self._as(clerk):
                    self.assertTrue(
                        frappe.has_permission("Payment Entry", "create"),
                        "staging error: the clerk must be able to CREATE Payment Entries, "
                        "otherwise create_reconciliation refuses before the settlement runs "
                        "and this test proves nothing",
                    )
                    self.assertFalse(
                        frappe.has_permission("Payment Entry", "submit"),
                        "staging error: SUBMIT was not actually revoked",
                    )
                    with self.production_validation():
                        first = btr.PaymentReconciliationManager().create_reconciliation(
                            self._txn_dict(bt), self._match(settlement_id)
                        )
                        after_first = self._settlement_entries(settlement_id)
                        # The next scheduled run: a fresh manager, so the in-memory
                        # `_processed_mollie_payments` set is empty and only the
                        # DB-backed guards stand between it and a duplicate.
                        btr.PaymentReconciliationManager().create_reconciliation(
                            self._txn_dict(bt), self._match(settlement_id)
                        )
                        after_second = self._settlement_entries(settlement_id)

        self.assertEqual(
            after_first,
            [],
            "the settlement inserted documents it could not submit; every duplicate "
            "guard filters docstatus 1, so these are invisible and will be re-created "
            f"on every run until someone bulk-submits them: {after_first}",
        )
        self.assertEqual(
            after_second,
            after_first,
            f"a second run booked another set of entries for the same settlement: {after_second}",
        )
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", it["invoice"].name, "outstanding_amount")),
            30.0,
            "the invoice was allocated against by a settlement that never posted",
        )
        self.assertFalse(first, "a settlement that posted nothing must not report success")
        bt.reload()
        self.assertNotEqual(
            bt.status,
            "Reconciled",
            "the deposit was marked Reconciled although no accounting was booked",
        )
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any("Insufficient permissions to submit" in c for c in comments),
            f"nothing tells the operator WHY the settlement was refused; comments={comments}",
        )

    def test_missing_journal_entry_submit_refuses_before_any_payment_entry(self):
        """The fee Journal Entry is booked LAST, after every Payment Entry is already
        submitted. Checking its permission only when it is reached would refuse a
        settlement that has ALREADY posted -- the exact half-posted state this fix
        exists to prevent -- so the check has to be a precondition."""
        self.expectErrorLog("Insufficient permissions to submit")
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing NoJESubmit", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees NoJESubmit", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieNoJESubmit", grand_total=30.0)
        clerk = self._clerk_user()
        settlement_id = f"stl_NOJE_{frappe.generate_hash(length=6)}"
        # Mollie kept 1.50, so the payout is 28.50 and the fee Journal Entry branch fires.
        bt = self._make_bank_transaction(
            deposit=28.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            with self._stub_client(payments=[payment]):
                with self._submit_revoked("Journal Entry", clerk):
                    with self._as(clerk):
                        self.assertTrue(
                            frappe.has_permission("Payment Entry", "submit"),
                            "staging error: only the Journal Entry submit right may be missing here",
                        )
                        self.assertFalse(
                            frappe.has_permission("Journal Entry", "submit"),
                            "staging error: Journal Entry SUBMIT was not actually revoked",
                        )
                        with self.production_validation():
                            ok = btr.PaymentReconciliationManager().create_reconciliation(
                                self._txn_dict(bt), self._match(settlement_id, amount="28.50")
                            )

        self.assertEqual(
            self._settlement_entries(settlement_id),
            [],
            "the settlement submitted its Payment Entries and only then discovered it "
            "could not submit the fee Journal Entry, leaving the ledger half-posted and "
            "a draft JE that defeats _existing_settlement_fee_entry",
        )
        self.assertFalse(ok, "a settlement that posted nothing must not report success")
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", it["invoice"].name, "outstanding_amount")),
            30.0,
            "the invoice was paid by a settlement that could not be completed",
        )

    def test_leftover_draft_from_an_earlier_run_blocks_reprocessing(self):
        """Drafts already on disk from a pre-fix run are not fixed by the precondition.

        The permission check stops NEW drafts, but the ``docstatus: 1`` guards still
        cannot see the old ones, so a later fully-privileged run would book a complete
        second set beside them. Rather than teaching those guards to count drafts as
        "processed" -- which would make ``_settlement_has_posted_accounting`` claim a
        settlement posted when it did not, and let one abandoned draft block a payment
        forever -- the settlement is refused until a human deals with them."""
        self.expectErrorLog("still has unsubmitted entries")
        it = self._make_member_with_invoice(first_name="MollieLeftover", grand_total=30.0)
        settlement_id = f"stl_LEFTOVER_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        # Exactly what the pre-fix code left behind: the same Payment Entry
        # _create_mollie_payment_entry builds, inserted and never submitted. Built here
        # rather than through the (now-fixed) helper so the fixture does not depend on
        # the code under test.
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        stale = get_payment_entry(dt="Sales Invoice", dn=it["invoice"].name, party_amount=Decimal("30.00"))
        stale.posting_date = bt.date
        stale.reference_no = payment["id"]
        stale.reference_date = bt.date
        stale.mode_of_payment = "Mollie"
        stale.custom_mollie_payment_id = payment["id"]
        stale.custom_mollie_settlement_id = settlement_id
        stale.custom_bank_transaction = bt.name
        stale.insert()

        with self._stub_client(payments=[payment]):
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), self._match(settlement_id))

        self.assertEqual(
            self._settlement_entries(settlement_id),
            [("Payment Entry", stale.name, 0)],
            "the run booked a second set of entries alongside the leftover draft",
        )
        self.assertFalse(ok, "a settlement that posted nothing must not report success")
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any(stale.name in c for c in comments),
            f"the operator is not told WHICH documents block the settlement; comments={comments}",
        )

    def test_leftover_draft_beside_a_submitted_fee_entry_is_still_refused(self):
        """The state a pre-fix run ACTUALLY leaves: draft Payment Entries AND a
        submitted fee Journal Entry.

        This is not a variant of the test above, it is the common case. The pre-fix
        loop counted a draft Payment Entry as a success and incremented
        ``total_reconciled``, so ``processed_count`` was non-zero and the fee entry was
        booked -- and submitted, because the shipped Custom DocPerms grant Journal
        Entry submit to System Manager while Payment Entry submit comes only from
        Accounts User. So the clerk who cannot post Payment Entries CAN post the fee
        entry, and leaves both behind.

        With the draft scan running after the idempotency short-circuit, that state
        reads as "already processed": success, no mention of the drafts, and the
        deposit permanently out of the retry pool. The drafts then sit there until
        someone bulk-submits them and over-allocates the invoice."""
        self.expectErrorLog("still has unsubmitted entries")
        it = self._make_member_with_invoice(first_name="MollieLeftoverFee", grand_total=30.0)
        settlement_id = f"stl_LEFTOVERFEE_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        stale = get_payment_entry(dt="Sales Invoice", dn=it["invoice"].name, party_amount=Decimal("30.00"))
        stale.posting_date = bt.date
        stale.reference_no = payment["id"]
        stale.reference_date = bt.date
        stale.mode_of_payment = "Mollie"
        stale.custom_mollie_payment_id = payment["id"]
        stale.custom_mollie_settlement_id = settlement_id
        stale.custom_bank_transaction = bt.name
        stale.insert()

        # The submitted fee entry from that same pre-fix run. Built by hand rather than
        # through _create_mollie_fee_entry so the fixture does not depend on the code
        # under test; two balance-sheet accounts keep it out of the cost-centre rules
        # that only apply to P&L rows. All the idempotency key reads is the settlement
        # id at docstatus 1.
        debit_account = self._make_gl_account("Mollie Leftover Clearing", account_type="Bank")
        credit_account = self._make_gl_account("Mollie Leftover Holding", account_type="Bank")
        fee_je = frappe.new_doc("Journal Entry")
        fee_je.posting_date = bt.date
        fee_je.company = self.company
        fee_je.custom_mollie_settlement_id = settlement_id
        fee_je.append("accounts", {"account": debit_account, "debit_in_account_currency": 1.5})
        fee_je.append("accounts", {"account": credit_account, "credit_in_account_currency": 1.5})
        fee_je.insert()
        fee_je.submit()

        with self._stub_client(payments=[payment]):
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), self._match(settlement_id))

        self.assertEqual(
            self._settlement_entries(settlement_id),
            sorted([("Payment Entry", stale.name, 0), ("Journal Entry", fee_je.name, 1)]),
            "the run booked new entries instead of refusing the leftover draft",
        )
        self.assertFalse(ok, "a settlement carrying leftover drafts must not report success")
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any(stale.name in c for c in comments),
            "the submitted fee entry short-circuited the run, so the operator was never "
            f"told about the draft that still needs handling; comments={comments}",
        )

    def test_a_payment_entry_whose_submit_fails_leaves_no_draft_behind(self):
        """``_require_submit_permission`` is a doctype-level check, so it cannot see the
        reasons a submit fails at DOCUMENT level.

        ``insert()`` and ``submit()`` are two statements. The permission precondition
        stops the case where submit was never attempted, but a submit that IS attempted
        and throws -- a frozen account, a closed period, a Company User Permission --
        leaves the inserted row behind, and the per-payment ``except`` swallows the
        error and lets the loop continue. The draft is then invisible to every
        ``docstatus: 1`` guard, so it survives both the leftover-draft scan (which runs
        on the NEXT run, and only if the settlement is retried at all) and any duplicate
        check. Whatever the settlement then reports, the row is on disk.

        The failure is injected rather than provoked, for the same reason
        ``tests/chapter/test_board_role_failure_propagation.py`` injects its deadlocks:
        what is under test is this module's insert/submit atomicity, not ERPNext's
        enforcement of any particular submit-time rule. Raising from ``submit()`` is
        precisely the branch that matters and is indifferent to which real condition
        (frozen account, closed period, restricted company) produced it. Nothing else
        is stubbed -- the real insert runs, and the real per-payment handler swallows."""
        self.expectErrorLog("submit refused")
        it = self._make_member_with_invoice(first_name="MollieSubmitFail", grand_total=30.0)
        settlement_id = f"stl_SUBMITFAIL_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with mock.patch(
            "erpnext.accounts.doctype.payment_entry.payment_entry.PaymentEntry.submit",
            side_effect=frappe.ValidationError("submit refused at document level"),
        ):
            with self._stub_client(payments=[payment]):
                with self.production_validation():
                    self.mgr.create_reconciliation(self._txn_dict(bt), self._match(settlement_id))

        self.assertEqual(
            self._settlement_entries(settlement_id),
            [],
            "the submit failed but its inserted Payment Entry survived as a draft, "
            "invisible to every docstatus:1 guard",
        )


# =============================================================================
# _create_mollie_payment_entry — direct (1021-1052)
# =============================================================================
class TestCreateMolliePaymentEntry(MollieBase):
    def test_creates_payment_entry_with_mollie_fields(self):
        it = self._make_member_with_invoice(first_name="MolliePE", grand_total=22.0)
        bt = self._make_bank_transaction(deposit=22.0, date=today(), bank_account=self._eur_bank_account)
        pid = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._mollie_payment(payment_id=pid, value="22.00")
        settlement_data = {"id": "stl_PE"}
        pe = self.mgr._create_mollie_payment_entry(bt, it["invoice"].name, payment, settlement_data)
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))
        self.assertEqual(pe.mode_of_payment, "Mollie")
        self.assertEqual(pe.reference_no, pid)
        self.assertEqual(pe.custom_mollie_payment_id, pid)
        self.assertEqual(pe.custom_mollie_settlement_id, "stl_PE")
        self.assertEqual(pe.custom_bank_transaction, bt.name)

    def test_uses_clearing_account_when_configured(self):
        it = self._make_member_with_invoice(first_name="MolliePEClr", grand_total=18.0)
        clearing = self._make_gl_account("Mollie Clearing", root_type="Asset", account_type="Bank")
        bt = self._make_bank_transaction(deposit=18.0, date=today(), bank_account=self._eur_bank_account)
        payment = self._mollie_payment(value="18.00")
        with self._mollie_settings(clearing_account=clearing):
            pe = self.mgr._create_mollie_payment_entry(bt, it["invoice"].name, payment, {"id": "stl_C"})
        # For a Receive PE the clearing account is the destination (paid_to); paid_from
        # stays the invoice's receivable (party) account.
        self.assertEqual(pe.paid_to, clearing)


# =============================================================================
# _create_mollie_fee_entry — direct (1057-1100) + the company bug
# =============================================================================
class TestCreateMollieFeeEntry(MollieBase):
    def test_tiny_fee_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        self.assertIsNone(self.mgr._create_mollie_fee_entry(bt, Decimal("0.005"), {"id": "stl_T"}))

    def test_no_clearing_account_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=""):
            self.assertIsNone(self.mgr._create_mollie_fee_entry(bt, Decimal("1.50"), {"id": "stl_N"}))

    def _gl_rows(self, voucher_no):
        """GL Entry rows for a voucher, keyed by account.

        Asserted on instead of the Journal Entry's own child rows because
        ``db_update()`` runs BEFORE ``on_submit``, so a throwing submit still leaves
        ``docstatus = 1`` and a full ``accounts`` table behind (#382). A GL row exists
        only if the entry actually posted.
        """
        return {
            r.account: r
            for r in frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Journal Entry", "voucher_no": voucher_no, "is_cancelled": 0},
                fields=["account", "debit", "credit"],
            )
        }

    def test_a_mollie_fee_debits_the_expense_account(self):
        """A fee is a cost, so it DEBITS the expense account and CREDITS clearing.

        The direction is not a matter of taste here, and it does not need the bank leg to
        settle. This app states the clearing convention in words in two places:
        ``donation_journal_entry_creator`` -- "Debit: Mollie Clearing Account (asset
        increases - we received money)" -- and ``donation_refund_journal_entry_creator``
        -- "Credit: Mollie Clearing Account (money leaves the clearing account)". A Mollie
        fee is money that leaves: Mollie keeps it out of the payout. So clearing is
        credited and the expense account is debited.

        It also follows from the surrounding entries. ``_create_mollie_payment_entry``
        sets ``paid_to = clearing``, so every matched payment DEBITS clearing by its
        gross; with the deposit crediting clearing by the payout, the residual left in
        clearing is a debit equal to the fee, and clearing must be CREDITED to clear it.
        The pre-fix code debited it a second time, so clearing drifted by twice the fee
        per settlement while the expense account accumulated a credit balance (#501).

        Asserted on GL rows rather than the Journal Entry's own child table -- see
        ``_gl_rows``.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing JE", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees JE", root_type="Expense")
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            je = self.mgr._create_mollie_fee_entry(bt, Decimal("2.50"), {"id": "stl_FEE"})
        self.assertIsNotNone(je)
        self.assertEqual(je.total_debit, je.total_credit)

        gl = self._gl_rows(je.name)
        self.assertEqual(set(gl), {clearing, fees}, f"the fee entry must post exactly two GL rows: {gl}")
        self.assertEqual(
            flt(gl[fees].debit, 2),
            2.50,
            f"a cost debits its expense account; crediting one books negative expense: {gl}",
        )
        self.assertEqual(flt(gl[fees].credit, 2), 0.0, f"the expense account is not credited: {gl}")
        self.assertEqual(
            flt(gl[clearing].credit, 2),
            2.50,
            f"the fee LEAVES clearing, which is a credit -- Mollie kept it: {gl}",
        )
        self.assertEqual(flt(gl[clearing].debit, 2), 0.0, f"clearing is not debited again: {gl}")

    def test_a_negative_fee_is_the_exact_inverse(self):
        """Mollie crediting a fee back is money arriving, so it debits clearing.

        ``_settlement_stated_fee`` reads Mollie's stated costs, and a negative cost is a
        fee being refunded to us. That is the mirror of the case above, and it has to be
        the mirror: a sign convention that is not symmetric leaves one direction
        unbalanced against the other.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Neg", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Neg", root_type="Expense")
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            je = self.mgr._create_mollie_fee_entry(bt, Decimal("-1.75"), {"id": "stl_NEG"})
        self.assertIsNotNone(je)

        gl = self._gl_rows(je.name)
        self.assertEqual(flt(gl[clearing].debit, 2), 1.75, f"money arriving debits clearing: {gl}")
        self.assertEqual(flt(gl[fees].credit, 2), 1.75, f"a refunded cost credits the expense account: {gl}")


# =============================================================================
# The settlement's bank leg (#508)
# =============================================================================
class TestSettlementBankLeg(MollieBase):
    """A settled payout must leave the clearing account at zero.

    ``process_mollie_settlement``'s own docstring names three legs:

        - The bulk settlement deposit in your bank -> Mollie Clearing Account
        - Individual payments in Clearing Account -> Customer invoices
        - Processing fees as expenses

    The middle one is the Payment Entries and the last is the fee Journal Entry. The
    FIRST -- the payout actually arriving in the physical bank -- was never
    implemented, so clearing accumulated a debit balance of gross-minus-fees per
    settlement and the bank account never recorded the money through this path (#508).

    The property is asserted on the clearing account's own balance rather than on the
    presence of a voucher, because that is the thing that has to be true regardless of
    how the leg is booked. Each test builds a FRESH clearing account, so every GL row
    on it belongs to this settlement and the net is exact.

    SCOPE of "nets to zero": it holds for a settlement whose components are payments and
    Mollie's stated costs, which is what these tests build. It is NOT the general
    invariant. A settlement containing refunds or chargebacks nets those off the payout,
    and this pipeline books neither -- `_settlement_stated_fee`'s own docstring notes they
    arrive on separate endpoints -- so clearing legitimately retains them. Nor does it
    hold while Mollie has not yet stated its costs (see the re-run test, which asserts
    the fee residual instead). The general form is

        gross - stated_fee - payout == refunds + chargebacks + tolerance slack

    and zero is the case where the right-hand side is empty. Stated because a test named
    for an invariant is how the next reader learns what the invariant is, and this one is
    narrower than its name.
    """

    def _clearing_net(self, account):
        """Signed clearing balance: positive = debit-heavy (money still stuck there)."""
        rows = frappe.get_all(
            "GL Entry",
            filters={"account": account, "is_cancelled": 0},
            fields=["debit", "credit"],
        )
        return flt(sum(flt(r.debit) - flt(r.credit) for r in rows), 2)

    def _gl_totals(self, account):
        rows = frappe.get_all(
            "GL Entry",
            filters={"account": account, "is_cancelled": 0},
            fields=["debit", "credit"],
        )
        return flt(sum(flt(r.debit) for r in rows), 2), flt(sum(flt(r.credit) for r in rows), 2)

    def test_a_settled_payout_leaves_the_clearing_account_at_zero(self):
        """Gross in, fees out, payout out -- clearing nets to zero.

        NOT asserted as "the net is zero" alone: a run that posts NOTHING AT ALL also
        nets to zero, and that is the shape of defect this suite has shipped before
        (a test satisfied before the code under test runs, #475). So the gross debit
        and the bank-side debit are asserted too. All three have to hold together:
        the payments booked, the payout left clearing, and it landed in the bank.

        This settlement is payments-plus-fee only, which is the case where zero is the
        right answer -- see the class docstring for why that is narrower than it sounds.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Leg", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Leg", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Leg", root_type="Expense")

        it = self._make_member_with_invoice(first_name="MollieBankLeg", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        # Gross 30.00, Mollie keeps 2.50, so 27.50 is paid out.
        match = self._match("stl_BANKLEG", amount="27.50", stated_costs="2.50")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        self.assertTrue(ok, f"settlement did not reconcile; comments={self._bt_comments(bt.name)}")

        clearing_debit, clearing_credit = self._gl_totals(clearing)
        self.assertEqual(
            clearing_debit,
            30.00,
            "the matched payment must DEBIT clearing by its gross -- without this the "
            f"net-zero assertion below is vacuous. clearing debit/credit={clearing_debit}/{clearing_credit}",
        )

        bank_debit, _bank_credit = self._gl_totals(bank)
        self.assertEqual(
            bank_debit,
            27.50,
            "the payout must DEBIT the physical bank account: this is the leg "
            f"process_mollie_settlement's docstring promises and never booked (#508). bank debit={bank_debit}",
        )

        self.assertEqual(
            self._clearing_net(clearing),
            0.0,
            "clearing must net to ZERO once a settlement is fully booked: gross in "
            f"(30.00), fees out (2.50), payout out (27.50). Residual debit means the "
            f"payout was never booked. debit={clearing_debit} credit={clearing_credit}",
        )

    def _run_settlement(self, bt, settlement_id, payment, amount, stated_costs=None):
        """One scheduled run, with a fresh manager as the next run would use."""
        return btr.PaymentReconciliationManager().create_reconciliation(
            self._txn_dict(bt), self._match(settlement_id, amount, stated_costs=stated_costs)
        )

    def test_a_rerun_books_exactly_one_payout_leg(self):
        """Re-running a settled settlement must not credit clearing a second time.

        A duplicated payout leg would push clearing NEGATIVE by the payout and
        double-count the money arriving in the bank, so this is the same class of
        defect as the fee entry's own re-run bug (#194).

        Deliberately run with NO stated fee. With one, ``_existing_settlement_fee_entry``
        short-circuits the second run before the payout code is reached, so the payout
        leg's own idempotency guard is never exercised and deleting it leaves this test
        green -- measured: it reddened the fee-guard test instead. Without a fee entry
        there is nothing else standing in the way, so this test is the guard's control.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Once", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Once", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Once", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieOnce", grand_total=30.0)
        settlement_id = f"stl_ONCE_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                self.assertTrue(self._run_settlement(bt, settlement_id, payment, "27.50", stated_costs=None))
                after_first = self._payout_entries(settlement_id)
                self._run_settlement(bt, settlement_id, payment, "27.50", stated_costs=None)
                after_second = self._payout_entries(settlement_id)

        self.assertEqual(len(after_first), 1, f"the first run must book the payout once: {after_first}")
        self.assertEqual(
            len(after_second),
            1,
            f"re-running the settlement booked a SECOND payout leg: {after_second}",
        )
        # Mollie has not stated its costs, so the 2.50 it kept legitimately remains in
        # clearing: 30.00 gross in, 27.50 paid out. A second payout leg would credit
        # 27.50 again and drive this to -25.00.
        self.assertEqual(
            self._clearing_net(clearing),
            2.50,
            "clearing must hold exactly the not-yet-stated fee after a re-run; a "
            "negative balance means the payout was credited twice",
        )

    def test_the_payout_leg_is_not_mistaken_for_the_fee_entry(self):
        """A settlement whose fee Mollie has not yet stated must still book its fee later.

        ``_existing_settlement_fee_entry`` is the settlement-level idempotency key and it
        matched ANY submitted Journal Entry carrying the settlement id. The payout leg
        carries that same id, so once it exists the guard reports the fee as already
        booked -- and a settlement that reconciled before Mollie stated its costs would
        never book them at all. The two entries are distinguished by voucher type.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Late", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Late", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Late", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieLate", grand_total=30.0)
        settlement_id = f"stl_LATE_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                # Run 1: Mollie has not stated its costs yet, so no fee entry is due.
                self._run_settlement(bt, settlement_id, payment, "27.50", stated_costs=None)
                self.assertEqual(
                    len(self._fee_entries(settlement_id)),
                    0,
                    "no fee is bookable before Mollie states its costs",
                )
                self.assertEqual(
                    len(self._payout_entries(settlement_id)), 1, "the payout leg must still be booked"
                )
                # Run 2: the costs have arrived.
                self._run_settlement(bt, settlement_id, payment, "27.50", stated_costs="2.50")

        self.assertEqual(
            len(self._fee_entries(settlement_id)),
            1,
            "the fee was never booked: the payout leg was taken for the fee entry by "
            "_existing_settlement_fee_entry, which matches any Journal Entry with this "
            "settlement id",
        )
        self.assertEqual(
            len(self._payout_entries(settlement_id)), 1, "and the payout must not be booked twice"
        )

    def test_the_deposit_is_allocated_to_the_payout_leg(self):
        """A deposit marked Reconciled must actually be allocated.

        ``reconcile_bank_transactions`` picks up transactions on
        ``allocated_amount in (0, None)``, and ERPNext's own bank reconciliation view
        calls a deposit with ``allocated_amount = 0`` unreconciled however this app's
        ``status`` field reads. The settlement branch set ``status = "Reconciled"`` and
        allocated nothing, so the two disagreed (#508).

        ERPNext derives ``allocated_amount`` from the ``payment_entries`` child table in
        ``before_validate``, so the row has to be appended before the branch saves.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Alloc", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Alloc", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Alloc", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieAlloc", grand_total=30.0)
        settlement_id = f"stl_ALLOC_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(
                        self._txn_dict(bt), self._match(settlement_id, "27.50", stated_costs="2.50")
                    )

        self.assertTrue(ok, f"settlement did not reconcile; comments={self._bt_comments(bt.name)}")
        bt.reload()
        payout = self._payout_entries(settlement_id)
        self.assertEqual(len(payout), 1, f"expected exactly one payout leg: {payout}")
        self.assertEqual(
            flt(bt.allocated_amount, 2),
            27.50,
            f"the deposit is marked {bt.status!r} with allocated_amount="
            f"{bt.allocated_amount!r}: ERPNext reads that as unreconciled",
        )
        self.assertEqual(
            [(r.payment_document, r.payment_entry) for r in bt.payment_entries],
            [("Journal Entry", payout[0].name)],
            "the payout leg must be the voucher the deposit is allocated to",
        )
        # ERPNext will not set this itself: `clear_linked_payment_entry` is reached only
        # from `allocate_payment_entries`, which skips a row that already carries a
        # non-zero allocation -- and even with a zero row, `should_clear` refuses a
        # voucher whose other leg is itself an `account_type = "Bank"` account. Without
        # the explicit stamp the payout sits on the Bank Reconciliation Statement as an
        # outstanding item forever while the Bank Transaction reads Reconciled.
        self.assertEqual(
            frappe.db.get_value("Journal Entry", payout[0].name, "clearance_date"),
            getdate(bt.date),
            "the payout leg must carry a clearance_date, or ERPNext's Bank "
            "Reconciliation Statement lists it as uncleared indefinitely",
        )

    def test_one_account_configured_as_both_sides_needs_no_payout_leg(self):
        """clearing == bank needs no payout leg, because the ledger is ALREADY right.

        veg11's Mollie Settings holds exactly this today: ``mollie_clearing_account`` and
        ``mollie_bank_account`` are the same account. With one account there is no
        intermediate to drain -- ``_create_mollie_payment_entry`` sets
        ``paid_to = clearing``, so the payments land directly in the bank account and the
        fee reduces it, leaving exactly the deposit. A transfer from an account to itself
        would post two rows that cancel.

        So this asserts the ACCOUNTING, not merely that a voucher was skipped: the single
        account must end at the deposit. Asserting only "no payout leg" would pass just as
        well if the skip were wrong for the reason the code originally claimed (a
        misconfiguration to be logged and warned about) as if it were right.
        """
        self._ensure_eur_company_cost_center()
        one = self._make_gl_account("Mollie One Account", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees One", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieSame", grand_total=30.0)
        settlement_id = f"stl_SAME_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=one, fees_account=fees, bank_account=one):
            with self._stub_client(payments=[payment]):
                self._run_settlement(bt, settlement_id, payment, "27.50", "2.50")

        self.assertEqual(
            self._payout_entries(settlement_id),
            [],
            "a transfer from an account to itself must not be booked",
        )
        # 30.00 gross debited by the Payment Entry, 2.50 credited by the fee entry.
        self.assertEqual(
            self._clearing_net(one),
            27.50,
            "with a single account the payments land straight in the bank account and "
            "the fee reduces it, so it must already hold exactly the deposit -- there is "
            "nothing for a payout leg to move",
        )

    def test_a_payout_leg_alone_counts_as_posted_accounting(self):
        """A settlement that booked only its payout leg has written to the ledger.

        ``_record_settlement_failure`` uses ``_settlement_has_posted_accounting`` to
        decide whether a failure is retryable: a settlement that posted nothing stays
        Pending, one that posted anything is handed to an operator. That discriminator
        read the FEE entry, and the fee guard no longer matches the payout leg -- so a
        settlement that reconciled before Mollie stated its costs and then failed would
        be read as "posted nothing" and re-run against a ledger it had already written
        to.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Posted", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Posted", root_type="Asset", account_type="Bank")
        settlement_id = f"stl_POSTED_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )

        self.assertFalse(
            self.mgr._settlement_has_posted_accounting(settlement_id),
            "nothing is posted yet",
        )

        with self._mollie_settings(clearing_account=clearing, bank_account=bank):
            je = self.mgr._book_settlement_payout(bt, {"id": settlement_id})

        self.assertIsNotNone(je, "the payout leg must have been booked for this test to mean anything")
        self.assertEqual(
            self._fee_entries(settlement_id), [], "and it must NOT be a fee entry -- that is the point"
        )
        self.assertTrue(
            self.mgr._settlement_has_posted_accounting(settlement_id),
            f"payout leg {je.name} is on the ledger but the settlement reads as having "
            "posted nothing, so a failure after it would be treated as retryable",
        )

    def test_a_failed_payout_leg_does_not_close_out_the_settlement(self):
        """A payout leg that fails must leave the settlement recoverable.

        The fee entry is the settlement-level idempotency key
        (``_existing_settlement_fee_entry`` -> ``_already_processed_result``), and the
        payout leg deliberately is NOT (they are told apart by ``voucher_type``). So
        whichever is written first, a failure in the second one leaves the first on the
        ledger -- and if the first is the FEE, the next run short-circuits on it, returns
        "already processed", and ``create_reconciliation`` marks the deposit Reconciled
        with the payout never booked. That is verbatim the #508 symptom this change exists
        to remove, reached through the failure path instead.

        `create_reconciliation` swallows the exception, so nothing rolls back: the fee
        entry really does persist.

        The failure is induced with a real misconfiguration rather than a mock: a GROUP
        account cannot be posted to, which is exactly what an operator picking the parent
        node in Mollie Settings would produce.
        """
        self.expectErrorLog("")
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Recover", root_type="Asset", account_type="Bank")
        good_bank = self._make_gl_account(
            "Mollie Payout Bank Recover", root_type="Asset", account_type="Bank"
        )
        fees = self._make_gl_account("Payment Processing Fees Recover", root_type="Expense")
        group_bank = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
        )
        self.assertIsNotNone(group_bank, "need a group Asset account to induce the failure")

        it = self._make_member_with_invoice(first_name="MollieRecover", grand_total=30.0)
        settlement_id = f"stl_RECOVER_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._stub_client(payments=[payment]):
            # Run 1: the payout leg cannot post.
            with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=group_bank):
                self._run_settlement(bt, settlement_id, payment, "27.50", "2.50")
            self.assertEqual(self._payout_entries(settlement_id), [], "the payout leg cannot have posted")
            # Run 2: the misconfiguration is corrected.
            with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=good_bank):
                self._run_settlement(bt, settlement_id, payment, "27.50", "2.50")

        bt.reload()
        self.assertEqual(
            len(self._payout_entries(settlement_id)),
            1,
            "the corrected run booked no payout leg: the first run's FEE entry satisfied "
            "_existing_settlement_fee_entry, so process_mollie_settlement short-circuited "
            "into _already_processed_result and never reached the payout. The deposit is "
            f"now {bt.status!r} with allocated_amount={flt(bt.allocated_amount, 2)} and "
            f"{self._clearing_net(clearing)} stranded in clearing -- the #508 symptom, "
            "reached through the failure path",
        )
        self.assertEqual(self._clearing_net(clearing), 0.0, "clearing must end at zero once recovered")
        self.assertEqual(flt(bt.allocated_amount, 2), 27.50, "and the deposit must end up allocated")

    def test_the_payout_follows_the_bank_not_the_settlement_amount(self):
        """The leg is booked for what the BANK received, not what Mollie said it sent.

        This is the design claim the method's docstring argues for, and until this test
        existed nothing discriminated it: every other test sets
        ``deposit == settlement amount``, so substituting
        ``settlement_data["amount"]["value"]`` for ``bank_trans.deposit`` left the module
        green. The matcher admits a settlement within 0.1%, so the two figures really can
        differ in production.

        Mollie states a 27.52 payout; 27.50 actually arrived. The physical bank account
        must equal the statement, and the 0.02 must not be absorbed into a leg claiming
        to be the payout.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Bankfig", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Bankfig", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Bankfig", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieBankfig", grand_total=30.0)
        settlement_id = f"stl_BANKFIG_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                # Settlement says 27.52; the bank says 27.50.
                self._run_settlement(bt, settlement_id, payment, "27.52", "2.50")

        bank_debit, _ = self._gl_totals(bank)
        self.assertEqual(
            bank_debit,
            27.50,
            "the bank account must hold what the STATEMENT says arrived; booking the "
            "settlement's stated 27.52 would put a number the bank never received into "
            "the one account that has to reconcile against a statement",
        )
        self.assertEqual(
            self._clearing_net(clearing),
            0.0,
            "and the difference must not be absorbed into the payout leg",
        )

    def test_a_zero_deposit_books_no_payout_leg_and_does_not_fail_the_settlement(self):
        """The amount guard must REFUSE, not post a zero-amount voucher.

        Asserted on the return value, not on the absence of a leg: "no payout leg" is
        true whether the guard refuses or a zero-amount Journal Entry throws and takes
        the whole settlement down with it. Only the return value tells those apart.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Zero", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Zero", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Zero", root_type="Expense")
        it = self._make_member_with_invoice(first_name="MollieZero", grand_total=30.0)
        settlement_id = f"stl_ZERO_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=0.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)

        with self._mollie_settings(clearing_account=clearing, fees_account=fees, bank_account=bank):
            with self._stub_client(payments=[payment]):
                ok = self._run_settlement(bt, settlement_id, payment, "0.00", "2.50")

        self.assertTrue(
            ok,
            "a zero deposit must be refused by the amount guard, not turned into a "
            "zero-amount Journal Entry whose submit failure fails the settlement",
        )
        self.assertEqual(self._payout_entries(settlement_id), [], "and no leg is booked")

    def test_a_rerun_repairs_an_allocation_the_first_run_never_persisted(self):
        """A payout leg on the ledger with no allocation must be repaired, not skipped.

        `_book_settlement_payout` appends the child row to the caller's IN-MEMORY
        document; `create_reconciliation` persists it. So a first run can insert and
        submit the Journal Entry and then die before that save -- the entry is on the
        ledger and the deposit is left unallocated. Returning early on the idempotency
        key alone made that permanent, because nothing else ever appends the row.

        Reproduced by reloading the document between the two calls, which discards the
        in-memory row exactly as an unsaved run would. Asserting on the recovery path
        rather than on a second failure injection keeps the test about the repair.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Repair", root_type="Asset", account_type="Bank")
        bank = self._make_gl_account("Mollie Payout Bank Repair", root_type="Asset", account_type="Bank")
        settlement_id = f"stl_REPAIR_{frappe.generate_hash(length=6)}"
        bt = self._make_bank_transaction(
            deposit=27.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )

        with self._mollie_settings(clearing_account=clearing, bank_account=bank):
            je = self.mgr._book_settlement_payout(bt, {"id": settlement_id})
            self.assertIsNotNone(je, "the first run must book the payout leg")

            # The first run died before `create_reconciliation` could save: the Journal
            # Entry is submitted, the child row was only ever in memory.
            bt.reload()
            self.assertEqual(
                [(r.payment_document, r.payment_entry) for r in bt.payment_entries],
                [],
                "precondition: nothing was persisted",
            )

            self.mgr._book_settlement_payout(bt, {"id": settlement_id})

        self.assertEqual(
            [(r.payment_document, r.payment_entry) for r in bt.payment_entries],
            [("Journal Entry", je.name)],
            "the re-run returned early on the idempotency key and left the deposit "
            "unallocated against a payout leg that is already on the ledger",
        )
        self.assertEqual(len(self._payout_entries(settlement_id)), 1, "and it must not book a second leg")


# =============================================================================
# resolve_invoice_from_reference (module helper, 1346-1359)
# =============================================================================
class TestResolveInvoiceFromReference(MollieBase):
    def test_direct_invoice_name_match(self):
        it = self._make_member_with_invoice(first_name="ResolveDirect", grand_total=15.0)
        self.assertEqual(btr.resolve_invoice_from_reference(it["invoice"].name), it["invoice"].name)

    def test_embedded_pattern_match(self):
        it = self._make_member_with_invoice(first_name="ResolveEmbed", grand_total=15.0)
        name = it["invoice"].name
        self.assertEqual(btr.resolve_invoice_from_reference(f"payment ref {name} received"), name)

    def test_empty_reference_returns_none(self):
        self.assertIsNone(btr.resolve_invoice_from_reference(""))
        self.assertIsNone(btr.resolve_invoice_from_reference(None))

    def test_unknown_reference_returns_none(self):
        self.assertIsNone(btr.resolve_invoice_from_reference("SINV-0000000-DOES-NOT-EXIST"))


# =============================================================================
# match_by_description — MEMBER ID branch (333-342)
# =============================================================================
class TestMatchByDescriptionMemberBranch(MollieBase):
    def test_member_id_pattern_resolves_unpaid_invoice(self):
        it = self._make_member_with_invoice(first_name="DescMemberId", grand_total=27.0)
        frappe.db.set_value(
            "Sales Invoice",
            it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 27.0},
            update_modified=False,
        )
        bt = self._make_bank_transaction(deposit=27.0, description=f"MEMBER ID: {it['member'].name}")
        match = self.mgr.match_by_description(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "member")
        self.assertEqual(match["reference"], it["invoice"].name)
        self.assertEqual(match["confidence"], 0.8)


# =============================================================================
# Single-bound date filters (124-128, 1408, 1410)
# =============================================================================
class TestDateFilterBranches(MollieBase):
    def test_reconcile_from_date_only(self):
        result = self.mgr.reconcile_bank_transactions(from_date=today())
        self.assertIn("total_transactions", result)

    def test_reconcile_to_date_only(self):
        result = self.mgr.reconcile_bank_transactions(to_date=today())
        self.assertIn("total_transactions", result)

    def test_summary_from_date_only(self):
        result = btr.get_reconciliation_summary(from_date=today())
        self.assertIn("total_transactions", result)

    def test_summary_to_date_only(self):
        result = btr.get_reconciliation_summary(to_date=today())
        self.assertIn("total_transactions", result)


# =============================================================================
# process_sepa_return_file — accept/reject dispatch loop (1223-1233)
# =============================================================================
class TestProcessSepaReturnFileLoop(MollieBase):
    def test_accepted_status_marks_payment(self):
        it = self._make_member_with_invoice(first_name="SepaAccept", grand_total=25.0)
        frappe.db.set_value("Sales Invoice", it["invoice"].name, "status", "Unpaid", update_modified=False)
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
  <CstmrPmtStsRpt>
    <OrgnlPmtInfAndSts>
      <TxInfAndSts>
        <OrgnlEndToEndId>E2E-{it['invoice'].name}</OrgnlEndToEndId>
        <TxSts>ACSP</TxSts>
      </TxInfAndSts>
    </OrgnlPmtInfAndSts>
  </CstmrPmtStsRpt>
</Document>"""
        result = btr.process_sepa_return_file(xml, file_type="pain.002")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["processed"], 1)
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Sales Invoice", "reference_name": it["invoice"].name},
            fields=["content"],
        )
        self.assertTrue(any("SEPA payment accepted" in (c.get("content") or "") for c in comments))


# =============================================================================
# match_mollie_settlement — the bank reference is the discriminator (#547)
# =============================================================================
class TestSettlementReferenceGate(MollieBase):
    """Amount + date + keyword must not be enough to auto-post accounting (#547).

    The matcher used to return 0.98 (exact amount) or 0.92 (within a 0.1% window)
    against a ``match_threshold`` of 0.85, on three criteria: amount, a +/-3 day
    date window, and the description containing one of ``mollie|settlement|payout``.
    Nothing identified the *counterparty* or the *settlement*, and
    ``create_reconciliation`` books Payment Entries and a fee Journal Entry against
    whichever settlement it is handed -- so a coincidence posted accounting.

    The discriminator was already in the string the keyword check reads. Measured on
    veg11's own ``tabBank Transaction``, over the 102 rows with a real Mollie
    counterparty, the settlement ``reference`` is in the description:

        NL70CITI2032329018 CITINL2X Stichting Mollie Payments
        T13606591.2510.01 REF T13606591.2510.01 Mollie betalingen      (deposit 125.71)

    ``13606591.2510.01`` is ``Settlement.reference`` (``<merchantId>.<yyMM>.<seq>``,
    core/models/settlement.py:74). So the reference gates the auto-post, and an
    unconfirmed candidate is returned BELOW the threshold instead of being reconciled
    unattended.

    NOT "verbatim in every payout" -- that claim was made here on the strength of 25
    rows and is false. One real payout has the reference broken across the bank's
    line wrap, which is why the comparison squashes whitespace; see
    ``test_a_reference_broken_across_a_line_wrap_still_auto_reconciles``.
    """

    #: The reference and description shapes above, copied from veg11.
    REAL_REFERENCE = "13606591.2510.01"
    REAL_DESCRIPTION = (
        "NL70CITI2032329018 CITINL2X Stichting Mollie Payments "
        "T13606591.2510.01 REF T13606591.2510.01 Mollie betalingen"
    )

    def _match_on_mollie_account(self, *, deposit, description, settlements):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=deposit,
            description=description,
            date=today(),
            bank_account=self._eur_bank_account,
        )
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=settlements):
                return self.mgr.match_mollie_settlement(self._txn_dict(bt))

    def test_amount_and_keyword_alone_do_not_clear_the_auto_match_threshold(self):
        """The #547 case: a coincidence must not auto-post.

        Exact amount, a mollie keyword, inside the date window -- and a settlement
        whose reference is NOT in the description. Before the fix this returned 0.98
        and reconciled unattended.
        """
        match = self._match_on_mollie_account(
            deposit=123.45,
            description="Incoming payout from a customer",
            settlements=[self._settlement_payload("stl_NOREF", "123.45", reference="13606591.2509.01")],
        )
        self.assertIsNotNone(match, "the candidate is still reported, just not auto-postable")
        self.assertLess(
            match["confidence"],
            self.mgr.match_threshold,
            "amount+date+keyword with no reference must stay below the auto-match "
            "threshold, or create_reconciliation books accounting on a coincidence",
        )

    def test_a_settlement_carrying_no_reference_at_all_cannot_clear_the_threshold(self):
        """An absent `reference` key is not the same as a non-matching one, and
        neither identifies the deposit."""
        match = self._match_on_mollie_account(
            deposit=500.00,
            description="mollie settlement payout",
            settlements=[self._settlement_payload("stl_NOKEY", "500.00")],
        )
        self.assertIsNotNone(match)
        self.assertLess(match["confidence"], self.mgr.match_threshold)

    def test_the_bank_reference_in_the_description_clears_the_threshold(self):
        """The real veg11 payout shape still auto-reconciles.

        NOT a discriminating test on its own -- develop returns 0.98 here too. It
        pins that the gate does not close on the traffic it exists to match, which
        is the failure mode the `is_company_account` filter had (#544).
        """
        match = self._match_on_mollie_account(
            deposit=125.71,
            description=self.REAL_DESCRIPTION,
            settlements=[self._settlement_payload("stl_REAL", "125.71", reference=self.REAL_REFERENCE)],
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match["confidence"], self.mgr.match_threshold)
        self.assertEqual(match["reference"], "stl_REAL")

    def test_the_referenced_settlement_wins_over_an_earlier_amount_twin(self):
        """Two settlements, same amount, one referenced in the description.

        Develop returns the FIRST amount match in list order, so ordering the
        unreferenced twin first makes this fail against develop -- it picks
        `stl_TWIN` and posts against the wrong settlement. Same class of ambiguity
        as #544, one layer in.
        """
        match = self._match_on_mollie_account(
            deposit=250.00,
            description=self.REAL_DESCRIPTION,
            settlements=[
                self._settlement_payload("stl_TWIN", "250.00", reference="13606591.2509.01"),
                self._settlement_payload("stl_NAMED", "250.00", reference=self.REAL_REFERENCE),
            ],
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            match["reference"],
            "stl_NAMED",
            "the settlement the bank actually named must win over an amount twin",
        )
        self.assertGreaterEqual(match["confidence"], self.mgr.match_threshold)

    def test_a_named_settlement_with_a_mismatched_amount_is_reported_not_dropped(self):
        """The bank named this settlement and the amounts disagree.

        Not a match -- it must not post -- but not nothing either: it is the most
        actionable thing this matcher can say, so it comes back below the threshold
        with both figures in the reason. Returning None here (the first version of
        this change) threw the signal away.

        Not hypothetical: on veg11 six settlement references each appear on TWO bank
        lines -- a payout plus a separate donation credit on the same reference -- so
        at most one of each pair can equal the settlement amount and the other lands
        in exactly this branch, every month.
        """
        match = self._match_on_mollie_account(
            deposit=125.71,
            description=self.REAL_DESCRIPTION,
            settlements=[self._settlement_payload("stl_WRONGAMT", "9999.00", reference=self.REAL_REFERENCE)],
        )
        self.assertIsNotNone(match, "a named settlement with a wrong amount must not vanish")
        self.assertEqual(match["reference"], "stl_WRONGAMT")
        self.assertLess(match["confidence"], self.mgr.match_threshold)
        self.assertIn("amounts differ", match["match_reason"])
        self.assertIn("9999", match["match_reason"], "the reason must carry both figures")

    def test_a_named_settlement_outranks_an_amount_twin_that_is_not_named(self):
        """Priority between the two sub-threshold outcomes.

        A named-but-discrepant settlement is more informative than an unnamed
        amount coincidence, so it must be the one reported when both exist.
        """
        match = self._match_on_mollie_account(
            deposit=125.71,
            description=self.REAL_DESCRIPTION,
            settlements=[
                self._settlement_payload("stl_COINCIDENCE", "125.71", reference="13606591.2509.01"),
                self._settlement_payload("stl_NAMEDBADAMT", "9999.00", reference=self.REAL_REFERENCE),
            ],
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["reference"], "stl_NAMEDBADAMT")
        self.assertLess(match["confidence"], self.mgr.match_threshold)

    def test_a_reference_broken_across_a_line_wrap_still_auto_reconciles(self):
        """The real veg11 row whose reference the bank split (S1).

        Verbatim from `tabBank Transaction` ACC-BTN-2026-17556, 2023-10-02, deposit
        93.22 -- the remittance text is wrapped at a fixed column and the break
        landed INSIDE the reference, giving `T13606591.231 0.01`. Plain containment
        returns False on it, so the first version of this change silently stopped
        auto-reconciling that payout. 1 of the 102 real Mollie-counterparty rows on
        veg11; the same wrap lands in "Mo llie betalingen" in other months, so the
        column is fixed and the token it splits varies.
        """
        match = self._match_on_mollie_account(
            deposit=93.22,
            description=(
                "NL70CITI2032329018 CITINL2X STICHTING MOLLIE PAYMENTS "
                "509081651a68d4db7864.22175631 REF T13606591.231 0.01 Mollie betalingen"
            ),
            settlements=[self._settlement_payload("stl_WRAPPED", "93.22", reference="13606591.2310.01")],
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(
            match["confidence"],
            self.mgr.match_threshold,
            "a reference broken by the bank's line wrap is still the bank naming it",
        )
        self.assertEqual(match["reference"], "stl_WRAPPED")

    def test_a_degenerate_short_reference_is_not_an_identifier(self):
        """The reference IS the security property, so it cannot be trusted blind.

        A one- or two-character reference is contained in almost any description,
        which would make the gate vacuous exactly when the upstream data is
        degenerate. Below MIN_SETTLEMENT_REFERENCE_LENGTH it does not confirm.
        """
        match = self._match_on_mollie_account(
            deposit=64.00,
            description="mollie payout 0",
            settlements=[self._settlement_payload("stl_SHORTREF", "64.00", reference="0")],
        )
        self.assertIsNotNone(match)
        self.assertLess(
            match["confidence"],
            self.mgr.match_threshold,
            "a 1-character reference must not be accepted as identification",
        )

    def test_an_unnamed_within_tolerance_match_is_also_below_the_threshold(self):
        """The 0.92 tier, unconfirmed. Both other sub-threshold tests use exact
        amounts, so without this the within-tolerance path is never exercised
        against the gate."""
        match = self._match_on_mollie_account(
            deposit=1000.00,
            description="mollie payout",
            settlements=[self._settlement_payload("stl_TOLNOREF", "1000.50", reference="13606591.2509.01")],
        )
        self.assertIsNotNone(match)
        self.assertLess(match["confidence"], self.mgr.match_threshold)

    def test_match_transaction_does_not_reconcile_a_keyword_only_settlement_deposit(self):
        """End-to-end: the outcome, not the confidence number.

        `match_transaction` takes the max confidence across strategies and reconciles
        above the threshold, so this is what decides whether accounting is posted.
        Fully staged so that the ONLY thing stopping the post is the gate: a clearing
        account, a member invoice, and a Mollie payment that covers it, i.e. exactly
        the fixture `TestCreateReconciliationMollieBranch` uses to reconcile
        successfully. Against develop this books a Payment Entry and marks the
        transaction Reconciled.

        An earlier version of this test asserted the same thing with no payments in
        the settlement, and passed against develop -- not because the match was
        refused but because there was nothing to book. It proved nothing.
        """
        self._ensure_eur_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing RefGate", root_type="Asset", account_type="Bank")
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        it = self._make_member_with_invoice(first_name="Zzqref", grand_total=777.13)
        bt = self._make_bank_transaction(
            deposit=777.13,
            description="mollie payout received",
            date=today(),
            bank_account=self._eur_bank_account,
            status="Pending",
        )
        txn = self._txn_dict(bt)
        # Settlement amount matches the deposit exactly; its reference does not appear
        # in the description.
        settlements = [self._settlement_payload("stl_NOTMINE", "777.13", reference="13606591.2509.01")]
        payment = self._mollie_payment(value="777.13", invoice_id=it["invoice"].name)
        with self._mollie_settings(clearing_account=clearing, bank_account=bank_gl):
            with self._stub_client(settlements=settlements, payments=[payment]):
                candidate = self.mgr.match_mollie_settlement(txn)
                reconciled = self.mgr.match_transaction(txn)

        # Staging check: the settlement WAS found and amount-matched, so the gate is
        # the only thing between it and create_reconciliation.
        self.assertIsNotNone(candidate, "staging error: no settlement candidate, so nothing was gated")
        self.assertEqual(candidate["reference"], "stl_NOTMINE")

        self.assertFalse(reconciled, "a keyword-only settlement deposit must not reconcile")
        self.assertEqual(
            frappe.db.get_value("Bank Transaction", bt.name, "status"),
            "Pending",
            "the transaction must be left for a human, not marked reconciled",
        )
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"]}),
            "no Payment Entry may be booked against a settlement nothing identified",
        )


# =============================================================================
# match_mollie_settlement — one settlement fetch per run, not per transaction (#546)
# =============================================================================
class TestSettlementWindowFetchedOncePerRun(MollieBase):
    """`get_settlements_by_date_range` pages Mollie's ENTIRE settlement history and
    filters in memory (clients/settlements_client.py: `self.get("settlements",
    paginated=True)`), and unlike its two siblings `get_settlement` /
    `list_settlements` it does not go through `get_cached`. It was called once per
    candidate transaction from inside `match_mollie_settlement`, so a reconciliation
    run downloaded that history N times (#546).
    """

    def test_the_settlement_window_is_fetched_once_for_transactions_sharing_a_date(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        # Amounts deliberately match no settlement: the fetch happens BEFORE the
        # amount comparison, so this measures the fetch count without letting any
        # transaction reconcile and post accounting either side of the fix.
        for amount in (11.11, 22.22, 33.33):
            self._make_bank_transaction(
                deposit=amount,
                description="mollie settlement payout",
                date=today(),
                bank_account=self._eur_bank_account,
                status="Pending",
            )
        settlements = [self._settlement_payload("stl_MISS", "9999.00")]
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=settlements):
                result = self.mgr.reconcile_bank_transactions(
                    bank_account=self._eur_bank_account, from_date=today(), to_date=today()
                )
                windows = list(_StubSettlementsClient.windows)
        self.assertGreaterEqual(
            result["total_transactions"], 3, "precondition: the three transactions were candidates"
        )
        self.assertEqual(
            len(windows),
            1,
            f"the settlement history must be downloaded once per run, not once per "
            f"transaction; windows requested: {windows}",
        )

    def test_a_second_window_is_still_fetched(self):
        """The control: the cache is keyed on the window, so it must not serve one
        window's settlements for another. Without this, `len(windows) == 1` above is
        equally consistent with "fetches once" and "never fetches again"."""
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        early = add_days(today(), -30)
        for date in (today(), early):
            self._make_bank_transaction(
                deposit=44.44,
                description="mollie settlement payout",
                date=date,
                bank_account=self._eur_bank_account,
                status="Pending",
            )
        settlements = [self._settlement_payload("stl_MISS2", "9999.00")]
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=settlements):
                self.mgr.reconcile_bank_transactions(
                    bank_account=self._eur_bank_account, from_date=early, to_date=today()
                )
                windows = list(_StubSettlementsClient.windows)
        # Asserting `len(set(windows)) == 2` would be pollution-fragile: this runs
        # against a SHARED bank account, so any leftover Pending transaction with a
        # third date inside the 30-day range adds a window and reds the test on a
        # co-tenanted shard. Assert the two windows are present, and separately that
        # nothing was fetched twice -- which also upgrades this from a pure control
        # into a discriminator for the cache KEY.
        expected = {(str(add_days(d, -3)), str(add_days(d, 3))) for d in (today(), early)}
        self.assertLessEqual(expected, set(windows), f"both date windows must be fetched; got {windows}")
        self.assertEqual(len(windows), len(set(windows)), f"a window was fetched more than once: {windows}")


if __name__ == "__main__":
    unittest.main()
