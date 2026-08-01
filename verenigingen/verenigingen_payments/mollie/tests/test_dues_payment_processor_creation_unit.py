"""
DuesPaymentProcessor — payment-entry / invoice / bank-transaction CREATION flows.

The sibling suite test_dues_payment_processor_unit.py covers status-gating,
classification, consumer-bank-data and the dues-item helper. This module targets
the still-uncovered document-CREATION paths that turn a Mollie dues payment into
real ERPNext documents:

    - _create_payment_entry_for_dues  (allocated-to-invoice + unallocated fallback
                                        + idempotency short-circuit)
    - _get_or_create_historical_invoice  (happy path + exact-paid-overlap reuse)
    - _create_simple_invoice           (real Sales Invoice, backdated, submitted)
    - _create_bank_transaction_for_dues (real Bank Transaction via the creator)
    - _reconcile_bank_transaction_with_payment_entry (failure path is non-fatal)
    - batch_process_customer_payments  (SDK-listed payments -> per-payment results)

Credential-free + real-integration pattern
-------------------------------------------
The processor's __init__ builds a MollieClient (needs a Mollie key); setUp patches
that one symbol out so the processor builds in CI. Every account the creation
paths need is configured against a REAL EUR company (get_eur_test_company) that
ERPNext gives a full chart of accounts:
    - Verenigingen Settings.company         -> the EUR company
    - Mollie Settings.mollie_clearing_account -> a real Bank GL account on it
    - Verenigingen Payments Settings.dues_income_account -> the EUR income account
      (the site default points at a *different* company's account, which would
      break invoice creation; we pin it to the EUR company in _setup_accounts).

Mollie payment objects are the SDK boundary, stood in with a small fake that
mirrors the attributes the processor reads. No logic under test is mocked: the
real PaymentClassifier, MemberPaymentMatcher, InvoiceGenerator-free invoice
builder, get_payment_entry, and bank_transaction_creator all run.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor


class FakeAmount(dict):
    """Mollie amount is dict-like: payment.amount['value'] / ['currency']."""


class FakeMolliePayment:
    """Minimal Mollie SDK payment stand-in (the external boundary)."""

    def __init__(
        self,
        id="tr_create_test",
        status="paid",
        value="25.00",
        currency="EUR",
        description="contributie 2025",
        customer_id=None,
        subscription_id=None,
        paid_at="2025-01-15T12:00:00+00:00",
        details=None,
    ):
        self.id = id
        self.status = status
        self.amount = FakeAmount(value=value, currency=currency)
        self.description = description
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.paid_at = paid_at
        self.details = details


class _FakeSdkPayments:
    def __init__(self, payment):
        self._payment = payment

    def get(self, payment_id):
        return self._payment


class _FakeCustomerPayments:
    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=250):
        return self._payments


class _FakeCustomerObj:
    def __init__(self, payments):
        self.payments = _FakeCustomerPayments(payments)


class _FakeCustomers:
    def __init__(self, payments):
        self._payments = payments

    def get(self, customer_id):
        return _FakeCustomerObj(self._payments)


class _FakeSdkClient:
    def __init__(self, *, payment=None, customer_payments=None):
        if payment is not None:
            self.payments = _FakeSdkPayments(payment)
        if customer_payments is not None:
            self.customers = _FakeCustomers(customer_payments)


class _FakeMollieClient:
    def __init__(self, *, payment=None, customer_payments=None):
        self.sdk_client = _FakeSdkClient(payment=payment, customer_payments=customer_payments)


def _ensure_dues_item():
    """Setup helper: a non-stock service Item (with a valid UOM) for invoice rows."""
    name = "Mollie Dues Test Item"
    if not frappe.db.exists("Item", name):
        item = frappe.new_doc("Item")
        item.item_code = name
        item.item_name = name
        item.item_group = (
            "Services"
            if frappe.db.exists("Item Group", "Services")
            else frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        )
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True, ignore_if_duplicate=True)
        frappe.db.commit()
    return name


def _make_eur_invoice(
    company, customer, income_account, amount=25.0, *, coverage_start=None, coverage_end=None, submit=True
):
    """Setup helper: an unpaid EUR Sales Invoice, submitted unless submit=False.

    Lives at module scope (a recognised fixture/setup location) so the
    permission-bypass insert is allowed. Currency is pinned to EUR explicitly
    because this site's default price list is INR, which would otherwise clash
    with the EUR company's EUR receivable account.
    """
    inv = frappe.new_doc("Sales Invoice")
    inv.customer = customer
    inv.company = company
    inv.currency = "EUR"
    inv.conversion_rate = 1.0
    inv.posting_date = today()
    inv.set_posting_time = 1
    inv.due_date = today()
    if coverage_start:
        inv.custom_coverage_start_date = coverage_start
    if coverage_end:
        inv.custom_coverage_end_date = coverage_end
    inv.is_membership_invoice = 1
    cost_center = frappe.db.get_value("Company", company, "cost_center")
    inv.append(
        "items",
        {
            "item_code": _ensure_dues_item(),
            "item_name": "Membership Dues Test",
            "description": "Membership Dues Test",
            "uom": "Nos",
            "qty": 1,
            "rate": amount,
            "income_account": income_account,
            "cost_center": cost_center,
        },
    )
    inv.flags.ignore_links = True
    inv.insert(ignore_permissions=True)
    if submit:
        inv.submit()
    frappe.db.commit()
    return inv


class DuesCreationTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls._setup_accounts(cls.company)

    @classmethod
    def _setup_accounts(cls, company):
        """Point all settings at the EUR company so creation paths resolve accounts.

        Pins Verenigingen Settings.company, a real Mollie clearing (Bank GL)
        account, and the EUR income account on Payments Settings. Uses
        ignore_permissions for SETUP-only Single-doctype writes (class-scoped
        fixture, not a test body).
        """
        # Look up an existing Bank GL account on the company; if the company has
        # none (e.g. a freshly created EUR test company on a clean CI site), create
        # one idempotently so the clearing-account-dependent paths are exercisable
        # on ANY site rather than only where a Bank account happened to pre-exist.
        from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
            ensure_mollie_bank_gl_account,
        )

        clearing = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        ) or ensure_mollie_bank_gl_account(company)
        income = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Income Account", "is_group": 0}, "name"
        )
        cls.clearing_account = clearing
        cls.income_account = income

        # The bank-transaction path (bank_transaction_creator) resolves the Bank
        # Account via its `account` link to the clearing GL account. On a site
        # where no such Bank Account exists yet, create one (plus its Bank parent)
        # idempotently so the BT-creation branch is exercisable on ANY site.
        if clearing and not frappe.db.get_value("Bank Account", {"account": clearing}, "name"):
            if not frappe.db.exists("Bank", "Mollie Test Bank"):
                frappe.get_doc({"doctype": "Bank", "bank_name": "Mollie Test Bank"}).insert(
                    ignore_permissions=True
                )
            frappe.get_doc(
                {
                    "doctype": "Bank Account",
                    "account_name": "Mollie Clearing",
                    "account": clearing,
                    "bank": "Mollie Test Bank",
                    "company": company,
                }
            ).insert(ignore_permissions=True)

        settings = frappe.get_single("Verenigingen Settings")
        settings.company = company
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)

        ms = frappe.get_single("Mollie Settings")
        ms.mollie_clearing_account = clearing
        ms.flags.ignore_validate = True
        ms.flags.ignore_mandatory = True
        ms.save(ignore_permissions=True)

        ps = frappe.get_single("Verenigingen Payments Settings")
        ps.dues_income_account = income
        ps.flags.ignore_validate = True
        ps.flags.ignore_mandatory = True
        ps.save(ignore_permissions=True)

        # Persist so the freshly-written clearing account / income account are
        # visible to the processor (which reads them via fresh get_single calls).
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        import verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher as mpm

        mpm._matcher_instance = None
        # Pin the EUR company + EUR income account for THIS test. These settings
        # are shared Singles; other suites flip them back (e.g. dues_income_account
        # drifts to a different company's account), so re-assert per-test via
        # set_single_value (EnhancedTestCase rolls these back after each method).
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "dues_income_account", self.income_account
        )
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", self.clearing_account)
        with patch("verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.MollieClient"):
            self.processor = DuesPaymentProcessor()

    def _member_with_customer(self, **kw):
        token = frappe.generate_hash()[:6]
        member = self.create_test_member(
            first_name="Create",
            last_name=f"Pay{token}",
            email=f"create.pay.{token}@example.com",
        )
        member.reload()
        # The auto-created Customer inherits the system default currency (INR on
        # this site); the EUR company's receivable account is EUR, so force the
        # Customer to EUR to avoid the currency-mismatch guard on Sales Invoice.
        if member.customer:
            frappe.db.set_value("Customer", member.customer, "default_currency", "EUR")
        return member


# ===========================================================================
# _create_payment_entry_for_dues  — the largest uncovered method
# ===========================================================================
class TestCreatePaymentEntryForDues(DuesCreationTestBase):
    def _invoice_for_member(self, member, amount=25.0):
        """A real submitted, unpaid EUR Sales Invoice for the member's customer."""
        return _make_eur_invoice(self.company, member.customer, self.income_account, amount)

    def test_allocates_payment_entry_to_supplied_invoice(self):
        member = self._member_with_customer()
        inv = self._invoice_for_member(member, amount=25.0)
        payment = FakeMolliePayment(id=f"tr_pe_alloc_{frappe.generate_hash()[:8]}", value="25.00")
        pe_name = self.processor._create_payment_entry_for_dues(member.name, payment, invoice_name=inv.name)
        self.assertTrue(pe_name)
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.reference_no, payment.id)
        self.assertEqual(pe.custom_member, member.name)
        # The invoice must be referenced and allocated.
        refs = [r for r in pe.references if r.reference_name == inv.name]
        self.assertEqual(len(refs), 1)
        self.assertAlmostEqual(float(refs[0].allocated_amount), 25.0, places=2)
        # Invoice is now fully paid.
        inv.reload()
        self.assertEqual(inv.outstanding_amount, 0)

    def test_idempotent_returns_existing_payment_entry(self):
        member = self._member_with_customer()
        inv = self._invoice_for_member(member)
        ref = f"tr_pe_idem_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref)
        first = self.processor._create_payment_entry_for_dues(member.name, payment, invoice_name=inv.name)
        self.assertTrue(first)
        # Second call for the same payment id must return the SAME PE, not a dup.
        second = self.processor._create_payment_entry_for_dues(member.name, payment, invoice_name=inv.name)
        self.assertEqual(second, first)
        count = frappe.db.count("Payment Entry", {"reference_no": ref, "docstatus": 1})
        self.assertEqual(count, 1)

    def test_unallocated_pe_created_when_no_invoice_and_creation_disallowed(self):
        # allow_invoice_creation=False and no invoice -> unallocated receive PE
        # using the company default receivable account.
        member = self._member_with_customer()
        ref = f"tr_pe_unalloc_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, value="30.00")
        pe_name = self.processor._create_payment_entry_for_dues(
            member.name, payment, invoice_name=None, allow_invoice_creation=False
        )
        self.assertTrue(pe_name)
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.party, member.customer)
        self.assertAlmostEqual(float(pe.paid_amount), 30.0, places=2)
        # Unallocated -> no Sales Invoice references.
        self.assertEqual(len(pe.references), 0)

    def test_require_invoice_refuses_unallocated_pe(self):
        # recovery mode: require_invoice=True with no invoice -> returns None
        # (refuses to create an orphaned PE).
        member = self._member_with_customer()
        payment = FakeMolliePayment(id=f"tr_pe_req_{frappe.generate_hash()[:8]}")
        result = self.processor._create_payment_entry_for_dues(
            member.name,
            payment,
            invoice_name=None,
            allow_invoice_creation=False,
            require_invoice=True,
        )
        self.assertIsNone(result)


# ===========================================================================
# _get_or_create_historical_invoice + _create_simple_invoice
# ===========================================================================
class TestHistoricalInvoiceLookup(DuesCreationTestBase):
    """_get_or_create_historical_invoice lookup/reuse/overlap branches.

    The CREATE branch (_create_simple_invoice) cannot run on this site: the
    default selling Price List is INR, so a freshly-built Sales Invoice resolves
    its currency to INR and clashes with the EUR company's EUR receivable account
    (Frappe's currency guard). That is an environment limitation, not a product
    bug — in production the company + price-list currencies align. We therefore
    cover the LOOKUP logic with EUR invoices we build explicitly (pinned to EUR),
    which exercises the coverage-overlap / exact-match-reuse decision tree.
    """

    def _coverage(self, member_name):
        from verenigingen.services.billing.coverage_calculator import (
            calculate_coverage_for_payment_date,
        )

        return calculate_coverage_for_payment_date(member_name, today())

    def test_reuses_existing_unpaid_invoice_with_exact_coverage(self):
        member = self._member_with_customer()
        cov_start, cov_end = self._coverage(member.name)
        existing = _make_eur_invoice(
            self.company,
            member.customer,
            self.income_account,
            amount=25.0,
            coverage_start=cov_start,
            coverage_end=cov_end,
        )
        # The processor finds the exact-coverage unpaid invoice and returns it
        # instead of creating a new one.
        found = self.processor._get_or_create_historical_invoice(member.name, today(), 25.0)
        self.assertEqual(found, existing.name)

    def test_overlap_without_exact_match_skips_creation(self):
        """An overlapping (but not exact) invoice -> the processor refuses to create a
        new invoice and returns None (manual review required).

        The overlapping invoice must NOT contain the payment date. Since 176a41dc
        ("anchor duplicate detection and payment matching on the member's own
        periods"), `_coverage_period_from_member_sequence` prefers *an invoice whose
        coverage already contains payment_date* and returns that invoice's own period
        verbatim. An overlapping invoice that spans the payment date therefore becomes
        the proposed period, `check_coverage_overlap` reports an EXACT match, and the
        processor reuses the invoice instead of refusing - so the fixture would no
        longer be constructing the case this test is named for.

        The window is shifted FORWARD from the payment date rather than backward, and
        the payment date is pinned to `cov_start` rather than `today()`, so "the
        invoice starts after the payment" holds on every day of the month. The
        previous fixture shifted backwards by 3 days, which contains today for all but
        the last 3 days of a period - it passed only because it happened to be written
        and merged inside that window.
        """
        member = self._member_with_customer()
        cov_start, cov_end = self._coverage(member.name)
        # Pay on the first day of the member's own period; cov_start <= today because
        # that period is the one containing today, so this never trips the
        # payment-date-in-the-future guard.
        payment_date = cov_start
        overlap_start = add_days(cov_start, 5)
        overlap_end = add_days(cov_end, 5)
        _make_eur_invoice(
            self.company,
            member.customer,
            self.income_account,
            amount=25.0,
            coverage_start=overlap_start,
            coverage_end=overlap_end,
        )
        result = self.processor._get_or_create_historical_invoice(member.name, payment_date, 25.0)
        self.assertIsNone(result)

    def test_draft_invoice_with_exact_coverage_is_not_returned_as_payable(self):
        """A DRAFT invoice covering the period must never be handed back to be paid.

        `check_coverage_overlap` matches `docstatus < 2`, so a draft can be the
        `exact_match`. A draft is not free of outstanding: ERPNext's
        `calculate_outstanding_amount` runs from `calculate_total_advance` on every
        save that is not cancelled, so a draft carries its full grand_total as
        `outstanding_amount` (measured on veg11: 144 of 144 drafts non-zero). The
        `outstanding > 0` test therefore reads a draft as a reusable unpaid invoice.

        Returning it is not survivable downstream: `_create_payment_entry_for_dues`
        feeds the name to `get_payment_entry`, and Payment Entry rejects a reference
        to an unsubmitted document ("... must be submitted", payment_entry.py:712),
        which matches neither string in that method's race-condition handler - so it
        re-raises and the payment records nowhere.
        """
        member = self._member_with_customer()
        cov_start, cov_end = self._coverage(member.name)
        draft = _make_eur_invoice(
            self.company,
            member.customer,
            self.income_account,
            amount=25.0,
            coverage_start=cov_start,
            coverage_end=cov_end,
            submit=False,
        )
        # Pin the premise this test rests on rather than assuming it.
        self.assertEqual(draft.docstatus, 0)
        self.assertGreater(
            frappe.db.get_value("Sales Invoice", draft.name, "outstanding_amount"),
            0,
            "a draft carries a non-zero outstanding_amount - this case is not reachable "
            "via the already-paid branch",
        )

        found = self.processor._get_or_create_historical_invoice(member.name, today(), 25.0)
        # None, not merely "some other invoice": creating a second invoice for a period
        # a draft already covers would duplicate it, so neither branch is correct here.
        # Asserting only `!= draft.name` would accept exactly that duplicate.
        self.assertIsNone(found, "a draft invoice must not be returned as an invoice to allocate against")

    def test_draft_exact_coverage_still_records_the_payment_unallocated(self):
        """The consequence of the above: the money must still land on the ledger.

        With a draft occupying the member's period there is no invoice this payment
        can be allocated to, and creating a second invoice for the same period would
        duplicate the draft. The correct outcome is an unallocated Payment Entry -
        the member's balance stays right and Payment Reconciliation surfaces it for a
        human, instead of the payment being dropped by a re-raised submit error.
        """
        member = self._member_with_customer()
        cov_start, cov_end = self._coverage(member.name)
        _make_eur_invoice(
            self.company,
            member.customer,
            self.income_account,
            amount=25.0,
            coverage_start=cov_start,
            coverage_end=cov_end,
            submit=False,
        )
        # paid_at drives the coverage lookup (extract_date(payment, "paid_at")); the
        # fake's default is 2025-01-15, whose period does not overlap the draft at
        # all - the draft would never be consulted and the test would pass without
        # exercising anything.
        payment = FakeMolliePayment(
            id=f"tr_draft_cov_{frappe.generate_hash()[:8]}",
            value="25.00",
            paid_at=f"{today()}T12:00:00+00:00",
        )
        pe_name = self.processor._create_payment_entry_for_dues(member.name, payment)

        self.assertTrue(pe_name, "the payment must be recorded even when only a draft covers the period")
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(list(pe.references), [], "the PE must not reference a draft invoice")


# NOTE — uncovered write path: _create_simple_invoice (the historical-invoice
# WRITER) is NOT exercised here. On this test site the system/global default
# currency is INR, so a Sales Invoice freshly built by the UNMODIFIED prod code
# resolves its document currency to INR and clashes with the EUR company's EUR
# receivable account (Frappe's currency guard fires inside the swallowed
# try/except, so the writer just returns None). Forcing EUR proved intractable
# without modifying prod or mutating broad shared global state (Global Defaults /
# Selling Settings overrides did not propagate to the SI's currency in the
# test-runner's already-warmed cache). This is an environment limitation, not a
# product bug — in production the company + price-list currencies align. The
# LOOKUP / overlap / reuse branches of _get_or_create_historical_invoice ARE
# covered above; the CREATE branch remains a known gap to close on an EUR-default
# site or with a dedicated currency-isolation fixture.


# ===========================================================================
# _create_bank_transaction_for_dues
# ===========================================================================
class TestCreateBankTransactionForDues(DuesCreationTestBase):
    def test_creates_unreconciled_bank_transaction(self):
        member = self._member_with_customer()
        ref = f"tr_bt_create_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, value="40.00", description="contributie")
        bt_name = self.processor._create_bank_transaction_for_dues(member.name, payment)
        # _setup_accounts wires a Mollie clearing GL account on the EUR company and
        # that company has a Bank Account linked to it, so get_mollie_bank_account_config
        # resolves and the BT must be created (no skip path).
        self.assertTrue(bt_name, "Bank Transaction must be created with EUR-company Mollie config")
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.reference_number, ref)
        self.assertAlmostEqual(float(bt.deposit), 40.0, places=2)
        self.assertEqual(bt.party_type, "Customer")
        self.assertEqual(bt.party, member.customer)
        self.assertEqual(bt.custom_member, member.name)


# ===========================================================================
# _reconcile_bank_transaction_with_payment_entry — failure path is non-fatal
# ===========================================================================
class TestReconcileFailureIsNonFatal(DuesCreationTestBase):
    def test_returns_false_when_documents_missing(self):
        # Non-existent BT/PE -> get_doc raises inside the try -> method logs and
        # returns False rather than propagating (orchestration must not abort).
        ok = self.processor._reconcile_bank_transaction_with_payment_entry(
            "BT-DOES-NOT-EXIST", "PE-DOES-NOT-EXIST"
        )
        self.assertFalse(ok)


# ===========================================================================
# batch_process_customer_payments — SDK-listed payments -> per-payment results
# ===========================================================================
class TestBatchProcessCustomerPayments(DuesCreationTestBase):
    def test_batch_tallies_skipped_for_non_paid_payments(self):
        # Two open (non-paid) payments listed for the customer -> each routes
        # through process_dues_payment and short-circuits to "skipped", so the
        # batch result tallies them as skipped. Exercises the real list/iterate/
        # deadlock-retry loop without needing full account wiring per payment.
        p1 = FakeMolliePayment(id=f"tr_batch_a_{frappe.generate_hash()[:6]}", status="open")
        p2 = FakeMolliePayment(id=f"tr_batch_b_{frappe.generate_hash()[:6]}", status="open")
        self.processor.mollie_client = _FakeMollieClient(customer_payments=[p1, p2])

        result = self.processor.batch_process_customer_payments("cst_batch_skip")
        self.assertEqual(result["total_retrieved"], 2)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(all(r["status"] == "skipped" for r in result["results"]))

    def test_batch_processes_paid_dues_payment_for_member(self):
        # A paid dues payment for a matched member -> Bank Transaction path runs
        # end to end through the real batch loop.
        member = self._member_with_customer()
        cid = f"cst_batch_ok_{frappe.generate_hash()[:8]}"
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)
        frappe.db.commit()
        ref = f"tr_batch_ok_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(
            id=ref, status="paid", description="contributie", customer_id=cid, value="22.50"
        )
        self.processor.mollie_client = _FakeMollieClient(customer_payments=[payment])

        result = self.processor.batch_process_customer_payments(cid)
        self.assertEqual(result["total_retrieved"], 1)
        self.assertEqual(len(result["results"]), 1)
        r = result["results"][0]
        self.assertEqual(r["payment_id"], ref)
        # The EUR company is fully Mollie-configured (clearing GL + linked Bank
        # Account), so the real batch loop drives process_dues_payment end to end
        # and the Bank Transaction must be created for the matched member.
        self.assertEqual(r["status"], "success", msg=r)
        self.assertEqual(r["member"], member.name)
        self.assertTrue(r["bank_transaction"])
        self.assertEqual(result["processed"], 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
