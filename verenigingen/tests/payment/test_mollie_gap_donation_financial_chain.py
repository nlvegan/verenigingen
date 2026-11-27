"""
Integration test closing the donation-payment financial-entry coverage gap in
the unified Mollie webhook wrapper.

Target: ``verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py``
        ``UnifiedWebhookWrapperService.process_payment_webhook`` ->
        ``_handle_new_payment_processing`` ->
        ``_create_donation_financial_entries`` (and the donation status /
        payment-history updates it drives).

Prior sweeps covered the routing/branch logic and STUBBED
``_create_donation_financial_entries``. This test stands up the minimal REAL
fixtures (Mollie clearing GL account + linked Bank Account on a EUR company,
Mollie Settings pointing at them, a real Donor + Donation keyed by the Mollie
payment id) and drives ONE end-to-end SUCCESS path so the financial-entry-
creation lines actually execute. It then asserts the REAL documents:

    - a submitted Journal Entry with ``cheque_no == payment_id``
      (Debit clearing / Credit donation income), linked back onto the Donation
    - a Bank Transaction (deposit) reconciled against that Journal Entry
    - the Donation's ``paid`` flag / payment-history child row updated

plus idempotency (a second identical webhook creates NO duplicate Journal
Entry / Bank Transaction).

Only the Mollie SDK/HTTP boundary is faked -- NO business logic is mocked.
There are FOUR independent fetch points along this chain; all are routed to a
single in-memory fake payment object so no live HTTP occurs:

    1. PaymentTypeRouter.fetch_payment           -> MollieClient.sdk_client
    2. UnifiedIdempotencyManager refund/chargeback checks (include_mollie_api)
    3. _fetch_payment_from_mollie                -> MollieSettings.get_mollie_client()
    4. _create_donation_financial_entries        -> mollie.api.client.Client()

Run with:
    bench --site test_site_4 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_gap_donation_financial_chain
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)

# Use a EUR company. Mollie payments are EUR; the donation Journal Entry posts a
# single-currency entry (Debit clearing / Credit income) and ERPNext's Bank
# Transaction + Journal Entry validations require the account/transaction
# currency to match the company currency unless multi-currency is enabled.
# ``_Test Company`` defaults to INR on the test site, which would force a
# multi-currency JE; ``_Test Company 2`` is EUR, matching the real organization.
COMPANY = "_Test Company 2"


# ---------------------------------------------------------------------------
# Mollie SDK fake (HTTP boundary only)
# ---------------------------------------------------------------------------
class _FakeRefundsResource:
    def list(self):
        # No refunds in Mollie SSOT -> idempotency check finds nothing pending.
        return {"_embedded": {"refunds": []}}


class _FakeChargebacksResource:
    def __init__(self, chargebacks=()):
        self._chargebacks = list(chargebacks)

    def list(self):
        # Default: no chargebacks -> iterable, nothing pending.
        return list(self._chargebacks)


class _FakePayment:
    """Mirrors the attributes the production code reads off a Mollie payment
    object (object-format branch of _fetch_payment_from_mollie and the
    PaymentDataExtractor used by the Bank Transaction creator)."""

    def __init__(self, payment_id, amount_value, donation_name):
        self.id = payment_id
        self.status = "paid"
        # PaymentDataExtractor / _fetch_payment_from_mollie read amount as a
        # dict with value/currency.
        self.amount = {"value": amount_value, "currency": "EUR"}
        self.description = f"Donation payment {donation_name}"
        # metadata carries the donation reference (UNKNOWN classification ->
        # falls through to the donation processor, which resolves the donation
        # from the Donation.payment_id index, not metadata).
        self.metadata = {"donation": donation_name}
        self.created_at = "2025-04-10T09:00:00+00:00"
        self.paid_at = "2025-04-10T09:00:00+00:00"
        self.method = "ideal"
        self.subscription_id = None
        self.customer_id = None
        self.refunds = _FakeRefundsResource()
        self.chargebacks = _FakeChargebacksResource()


class _FakeSDKClient:
    """Stand-in for the Mollie SDK Client. ``.payments.get`` returns our fake
    payment regardless of id; ``set_api_key`` is a no-op."""

    def __init__(self, payment):
        self._payment = payment
        self.payments = SimpleNamespace(get=lambda pid: self._payment)

    def set_api_key(self, _key):
        return None


class TestMollieDonationFinancialChain(EnhancedTestCase):
    # Settings singles ("Verenigingen Settings", "Mollie Settings") are global
    # state, and the webhook commits mid-flow (Bank Transaction reconciliation),
    # so per-test settings writes leak across the transaction rollback. Capture
    # the true pre-suite values ONCE at the class level so the restore in
    # tearDown is immune to per-test pollution.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._orig_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        cls._orig_donation_account = frappe.db.get_single_value(
            "Verenigingen Settings", "unrestricted_donation_account"
        )
        cls._orig_ms_clearing = frappe.db.get_single_value("Mollie Settings", "mollie_clearing_account")
        cls._orig_ms_bank = frappe.db.get_single_value("Mollie Settings", "mollie_bank_account")

    @classmethod
    def tearDownClass(cls):
        # Restore the global Settings singles to their pre-suite values + commit.
        frappe.db.set_single_value(
            "Verenigingen Settings", "unrestricted_donation_account", cls._orig_donation_account
        )
        frappe.db.set_single_value("Verenigingen Settings", "company", cls._orig_company)
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", cls._orig_ms_clearing)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", cls._orig_ms_bank)
        frappe.db.commit()
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.service = UnifiedWebhookWrapperService()

        # Point Verenigingen Settings at the EUR company so the Bank Transaction
        # creator's get_default_company() and the donation JE creator both
        # resolve the same EUR company. Restored in tearDownClass.
        # Use db writes (the config/JE services read these single values
        # directly); a full save would re-validate every link on the Settings
        # single, including the donation account, against the toggled company.
        frappe.db.set_single_value("Verenigingen Settings", "company", COMPANY)

        # --- Accounting fixtures on the EUR company ---
        self.clearing_account = self._setup_mollie_clearing_account()
        self.bank_account = self._setup_mollie_bank_account(self.clearing_account)
        self.income_account = self._setup_donation_income_account()
        self._setup_mollie_settings(self.clearing_account)

        # --- Donor + Donation keyed by Mollie payment id ---
        self.payment_id = f"tr_{frappe.generate_hash(length=12)}"
        self.amount = 25.00
        self.donor = self._setup_donor()
        self.donation_name = self._setup_donation(self.donor, self.payment_id, self.amount)

        # Fake payment + SDK seam
        self.fake_payment = _FakePayment(self.payment_id, f"{self.amount:.2f}", self.donation_name)
        self.fake_sdk = _FakeSDKClient(self.fake_payment)

    # ------------------------------------------------------------------ setup
    def _setup_mollie_clearing_account(self):
        """Create/find a Bank-type GL account to act as the Mollie clearing
        account on the EUR test company (config validation requires Bank type;
        the linked Bank Account currency must match the EUR Mollie payment)."""
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing Gap Test"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing Gap Test"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _setup_mollie_bank_account(self, gl_account):
        """Create the ERPNext Bank Account linked to the clearing GL account so
        BankTransactionCreator.get_mollie_bank_account_config() resolves it."""
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "Gap Test Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "Mollie Gap Test"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def _setup_donation_income_account(self):
        """Create/find a donation income account (company currency) and point
        Verenigingen Settings.unrestricted_donation_account at it so the JE
        creator's credit leg resolves deterministically."""
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income Gap Test"}, "name"
        )
        if not name:
            parent = frappe.get_value(
                "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
            )
            acct = frappe.new_doc("Account")
            acct.account_name = "Donation Income Gap Test"
            acct.company = COMPANY
            acct.parent_account = parent
            acct.account_type = "Income Account"
            acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
            acct.insert(ignore_permissions=True)
            name = acct.name
        # Set via db (the JE creator reads this single value); avoids the link
        # field's company-filtered validation on the freshly created account.
        frappe.db.set_single_value("Verenigingen Settings", "unrestricted_donation_account", name)
        return name

    def _setup_mollie_settings(self, clearing_account):
        """Configure Mollie Settings clearing/bank GL accounts and clear the
        cached MollieConfigurationService snapshot so the new values are read.

        Uses db writes (the config service reads these single values directly),
        avoiding full-document link revalidation on the Settings single."""
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", clearing_account)
        # settlement bank validation is skipped for payment processing
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()

    def _setup_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Gap Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"gap.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_donation(self, donor_name, payment_id, amount):
        # Donation is NOT submittable; the webhook's _update_donation_status sets
        # paid=1 via a plain save(), so the fixture stays in the normal saved
        # state (no submit) matching the real pre-webhook donation record.
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = "2025-04-10"
        donation.amount = amount
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.company = COMPANY
        donation.payment_id = payment_id
        donation.paid = 0
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation.name

    # --------------------------------------------------------------- patching
    def _run_webhook(self):
        """Invoke the real webhook chain with every Mollie HTTP fetch point
        routed to the in-memory fake. Returns the wrapper's result dict."""
        with (
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=self.fake_sdk,
            ),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_api_key",
                return_value="test_dummy_key_for_tests",
            ),
            patch(
                "mollie.api.client.Client",
                return_value=self.fake_sdk,
            ),
        ):
            with self.set_user("Administrator"):
                return self.service.process_payment_webhook(self.payment_id, {"id": self.payment_id})

    # ------------------------------------------------------------------ tests
    def test_success_chain_creates_je_bank_transaction_and_updates_donation(self):
        result = self._run_webhook()

        # 1. Wrapper reports success and surfaces the created documents.
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        self.assertEqual(result["donation_id"], self.donation_name)
        je_name = result.get("journal_entry")
        bt_name = result.get("bank_transaction")
        self.assertTrue(je_name, f"No journal_entry in result: {result}")
        self.assertTrue(bt_name, f"No bank_transaction in result: {result}")

        # 2. REAL Journal Entry exists, submitted, keyed by payment id in cheque_no.
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1, "Journal Entry should be submitted")
        self.assertEqual(je.cheque_no, self.payment_id, "JE must carry the Mollie payment id in cheque_no")
        self.assertEqual(je.company, COMPANY)
        # Debit the clearing account, credit the income account, balanced at amount.
        debit_total = sum(float(a.debit_in_account_currency) for a in je.accounts)
        credit_total = sum(float(a.credit_in_account_currency) for a in je.accounts)
        self.assertEqual(debit_total, self.amount)
        self.assertEqual(credit_total, self.amount)
        clearing_rows = [a for a in je.accounts if a.account == self.clearing_account]
        income_rows = [a for a in je.accounts if a.account == self.income_account]
        self.assertTrue(clearing_rows, "Expected a JE line on the Mollie clearing account")
        self.assertTrue(income_rows, "Expected a JE line on the donation income account")
        self.assertEqual(float(clearing_rows[0].debit_in_account_currency), self.amount)
        self.assertEqual(float(income_rows[0].credit_in_account_currency), self.amount)

        # 3. REAL Bank Transaction exists for this payment (deposit) and is
        #    reconciled against the Journal Entry.
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.reference_number, self.payment_id)
        self.assertEqual(float(bt.deposit), self.amount)
        self.assertEqual(bt.bank_account, self.bank_account)
        je_links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertTrue(je_links, "Bank Transaction should be reconciled with the donation Journal Entry")

        # 4. Donation updated: paid flag set, journal_entry linked back, and a
        #    payment-history child row recorded for this Mollie payment.
        donation = frappe.get_doc("Donation", self.donation_name)
        self.assertEqual(donation.paid, 1, "Donation should be marked paid")
        self.assertEqual(donation.journal_entry, je_name, "Donation should link back to the JE")
        history = [p for p in (donation.payments or []) if p.mollie_payment_id == self.payment_id]
        self.assertTrue(history, "Donation should have a payment-history row for the Mollie payment")
        self.assertEqual(history[0].journal_entry, je_name)
        self.assertEqual(float(history[0].amount), self.amount)
        self.assertEqual(history[0].payment_status, "Paid")

    def test_second_identical_webhook_is_idempotent(self):
        first = self._run_webhook()
        self.assertEqual(first["status"], "success", f"First call failed: {first}")
        je_name = first["journal_entry"]

        # Counts after first processing.
        je_count_1 = frappe.db.count("Journal Entry", {"cheque_no": self.payment_id, "docstatus": ["!=", 2]})
        bt_count_1 = frappe.db.count("Bank Transaction", {"reference_number": self.payment_id})
        self.assertEqual(je_count_1, 1)
        self.assertEqual(bt_count_1, 1)

        # Second identical webhook MUST NOT create duplicates.
        second = self._run_webhook()
        self.assertIn(second["status"], ("success", "skipped"), f"Second call: {second}")

        je_count_2 = frappe.db.count("Journal Entry", {"cheque_no": self.payment_id, "docstatus": ["!=", 2]})
        bt_count_2 = frappe.db.count("Bank Transaction", {"reference_number": self.payment_id})
        self.assertEqual(je_count_2, 1, "Second webhook must not create a duplicate Journal Entry")
        self.assertEqual(bt_count_2, 1, "Second webhook must not create a duplicate Bank Transaction")

        # Donation still links to the same single JE and history has no duplicate row.
        donation = frappe.get_doc("Donation", self.donation_name)
        self.assertEqual(donation.journal_entry, je_name)
        history = [p for p in (donation.payments or []) if p.mollie_payment_id == self.payment_id]
        self.assertEqual(len(history), 1, "Payment-history row must not be duplicated")

    def test_donation_journal_entry_link_is_persisted(self):
        """Regression: the Donation.journal_entry link must survive the webhook.

        The donation Journal Entry creator writes Donation.journal_entry via
        frappe.db.set_value (DB only). The very next step,
        _update_donation_status, then calls donation.save() on the in-memory
        donation object -- which, without an intervening reload(), still has
        journal_entry == None and silently writes that None back, dropping the
        JE link from the donation record. This test pins that the link is
        actually present on the reloaded Donation after processing.
        """
        result = self._run_webhook()
        self.assertEqual(result["status"], "success", f"Unexpected result: {result}")
        je_name = result["journal_entry"]
        self.assertTrue(je_name)

        # Read straight from the database (not the result dict) so we catch the
        # clobber: the JE is created but the link is wiped from the Donation.
        persisted = frappe.db.get_value("Donation", self.donation_name, "journal_entry")
        self.assertEqual(
            persisted,
            je_name,
            "Donation.journal_entry must be persisted (not clobbered by the status save)",
        )


class TestMollieDonationChargebackBooking638(TestMollieDonationFinancialChain):
    """#638: a chargeback announced on a donation's payment webhook must be BOOKED.

    Inherits the real fixtures (company, clearing/bank/income accounts, Donor, Donation).
    Only the Mollie HTTP/SDK boundary is faked (``_FakePayment``); the chargeback is a
    Mollie-shaped dict served by ``payment.chargebacks.list()``.

    The inherited tests are re-run under this class on purpose: they are the control
    that the forward path still books exactly as before.
    """

    CHARGEBACK_AMOUNT = 10.00

    def _announce_chargeback(
        self, chargeback_id=None, amount=None, created_at="2025-04-20T09:00:00+00:00", reversed_at=None
    ):
        chargeback_id = chargeback_id or f"chb_{frappe.generate_hash(length=10)}"
        amount = self.CHARGEBACK_AMOUNT if amount is None else amount
        self.fake_payment.chargebacks = _FakeChargebacksResource(
            [
                {
                    "id": chargeback_id,
                    "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
                    "reason": {"code": "AC01", "description": "Account closed"},
                    "createdAt": created_at,
                    "reversedAt": reversed_at,
                }
            ]
        )
        self.fake_payment.amount_charged_back = {"value": f"{amount:.2f}", "currency": "EUR"}
        return chargeback_id

    def _forward_booked(self):
        first = self._run_webhook()
        self.assertEqual(first["status"], "success", f"forward booking failed: {first}")
        return first["journal_entry"]

    def _reversal_jes(self, chargeback_id):
        key = f"{self.payment_id}_chargeback_{chargeback_id}"
        return frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name")

    def _gl(self, voucher_no):
        return frappe.get_all(
            "GL Entry",
            filters={"voucher_no": voucher_no, "is_cancelled": 0},
            fields=["account", "debit", "credit"],
        )

    def test_a_chargeback_is_booked_as_a_reversing_entry_and_recorded_on_the_donation(self):
        forward_je = self._forward_booked()
        chargeback_id = self._announce_chargeback()

        result = self._run_webhook()

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        reversals = self._reversal_jes(chargeback_id)
        self.assertEqual(len(reversals), 1, f"expected one reversing Journal Entry, got {reversals}")
        gl = self._gl(reversals[0])
        income = [g for g in gl if g.account == self.income_account]
        clearing = [g for g in gl if g.account == self.clearing_account]
        self.assertEqual(sum(g.debit for g in income), self.CHARGEBACK_AMOUNT, gl)
        self.assertEqual(sum(g.credit for g in clearing), self.CHARGEBACK_AMOUNT, gl)
        # The original is reversed, not cancelled.
        self.assertEqual(frappe.db.get_value("Journal Entry", forward_je, "docstatus"), 1)
        rows = [
            p
            for p in frappe.get_doc("Donation", self.donation_name).payments
            if p.payment_status == "Chargeback"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mollie_payment_id, chargeback_id)
        self.assertEqual(rows[0].journal_entry, reversals[0])
        self.assertEqual(float(rows[0].amount), -self.CHARGEBACK_AMOUNT)

    def test_a_redelivered_chargeback_books_nothing_new(self):
        self._forward_booked()
        chargeback_id = self._announce_chargeback()
        self.assertEqual(self._run_webhook()["status"], "success")
        before_bt = frappe.db.count("Bank Transaction", {"reference_number": ["like", f"%{chargeback_id}%"]})

        again = self._run_webhook()

        self.assertEqual(again["status"], "success", f"redelivery: {again}")
        self.assertEqual(len(self._reversal_jes(chargeback_id)), 1)
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": ["like", f"%{chargeback_id}%"]}),
            before_bt,
        )
        rows = [
            p for p in frappe.get_doc("Donation", self.donation_name).payments if p.payment_status == "Chargeback"
        ]
        self.assertEqual(len(rows), 1)

    def test_a_chargeback_that_cannot_be_booked_answers_an_error_so_mollie_retries(self):
        """Fault: the company's books are frozen AFTER the forward booking, so the reversal
        Journal Entry is refused by ERPNext. The forward booking is already done and
        idempotent, so the reversal is the only thing that can fail."""
        self._forward_booked()
        chargeback_id = self._announce_chargeback()
        self.expectErrorLog("Mollie Reversal Booking Failed", "Secure Operation Failed", "Mollie Journal Entry", "financial_entry_error")
        frappe.db.set_value("Company", COMPANY, "accounts_frozen_till_date", frappe.utils.today())
        try:
            result = self._run_webhook()
        finally:
            frappe.db.set_value("Company", COMPANY, "accounts_frozen_till_date", None)

        self.assertEqual(result["status"], "error", f"a failed booking answered success: {result}")
        self.assertEqual(self._reversal_jes(chargeback_id), [])
        self.assertEqual(result["chargeback_failures"][0]["status"], "error")

    def test_a_refund_and_a_chargeback_on_one_payment_both_book(self):
        """Control: the chargeback path must not displace the refund path."""
        self._forward_booked()
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        self.fake_payment.refunds = SimpleNamespace(
            list=lambda: {
                "_embedded": {
                    "refunds": [
                        {
                            "id": refund_id,
                            "status": "refunded",
                            "amount": {"value": "5.00", "currency": "EUR"},
                            "createdAt": "2025-04-18T09:00:00+00:00",
                        }
                    ]
                }
            }
        )
        chargeback_id = self._announce_chargeback()

        result = self._run_webhook()

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        self.assertEqual(len(self._reversal_jes(chargeback_id)), 1)
        refund_jes = frappe.get_all(
            "Journal Entry",
            filters={"cheque_no": f"{self.payment_id}_refund_{refund_id}", "docstatus": ["!=", 2]},
        )
        self.assertEqual(len(refund_jes), 1)

    def test_the_fully_processed_branch_books_a_pending_chargeback_too(self):
        """``_handle_fully_processed_payment`` carried the ``# TODO`` this issue replaces. It is
        unreachable for donations today (#344: ``is_fully_processed()`` is never true), so it is
        driven directly with the REAL state the idempotency manager computes."""
        self._forward_booked()
        chargeback_id = self._announce_chargeback()
        with (
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=self.fake_sdk,
            ),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_api_key",
                return_value="test_dummy_key_for_tests",
            ),
            self.set_user("Administrator"),
        ):
            state = self.service.idempotency_manager.check_payment_processing_state(
                self.payment_id, include_mollie_api=True
            )
            self.assertEqual([c["chargeback_id"] for c in state.pending_chargebacks], [chargeback_id])
            result = self.service._handle_fully_processed_payment(self.payment_id, state, 0.0)

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        self.assertEqual(len(self._reversal_jes(chargeback_id)), 1)

    # ---- a chargeback Mollie reports as REVERSED (#638 ruling) ---------------------------

    REVERSED_AT = "2025-05-02T09:00:00+00:00"

    def _donation_chargeback_rows(self):
        return [
            p
            for p in frappe.get_doc("Donation", self.donation_name).payments
            if p.payment_status == "Chargeback"
        ]

    def _income_balance(self):
        return sum(
            g.credit - g.debit
            for g in frappe.get_all(
                "GL Entry",
                filters={"account": self.income_account, "is_cancelled": 0},
                fields=["credit", "debit"],
            )
        )

    def test_a_chargeback_reversed_at_first_sight_books_nothing(self):
        self._forward_booked()
        income_before = self._income_balance()
        chargeback_id = self._announce_chargeback(reversed_at=self.REVERSED_AT)

        result = self._run_webhook()

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        self.assertEqual(self._reversal_jes(chargeback_id), [])
        self.assertEqual(self._donation_chargeback_rows(), [], "something was recorded as booked")
        self.assertEqual(self._income_balance(), income_before)

    def test_a_booked_chargeback_that_is_later_reversed_is_countered_once(self):
        forward_je = self._forward_booked()
        chargeback_id = self._announce_chargeback()
        self.assertEqual(self._run_webhook()["status"], "success")
        booked = self._reversal_jes(chargeback_id)
        self.assertEqual(len(booked), 1)
        income_after_chargeback = self._income_balance()

        self._announce_chargeback(chargeback_id=chargeback_id, reversed_at=self.REVERSED_AT)
        result = self._run_webhook()

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        counters = frappe.get_all(
            "Journal Entry",
            filters={"cheque_no": f"{self.payment_id}_chargeback_{chargeback_id}_reversed", "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(counters), 1, f"expected one counter-entry, got {counters}")
        gl = self._gl(counters[0])
        self.assertEqual(sum(g.credit for g in gl if g.account == self.income_account), self.CHARGEBACK_AMOUNT, gl)
        self.assertEqual(sum(g.debit for g in gl if g.account == self.clearing_account), self.CHARGEBACK_AMOUNT, gl)
        self.assertEqual(self._income_balance(), income_after_chargeback + self.CHARGEBACK_AMOUNT)
        # Both the forward entry and the chargeback entry stay submitted: countered, not cancelled.
        self.assertEqual(frappe.db.get_value("Journal Entry", forward_je, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Journal Entry", booked[0], "docstatus"), 1)
        rows = self._donation_chargeback_rows()
        self.assertEqual(sorted(float(r.amount) for r in rows), [-self.CHARGEBACK_AMOUNT, self.CHARGEBACK_AMOUNT])
        self.assertEqual({r.journal_entry for r in rows}, {booked[0], counters[0]})

        again = self._run_webhook()

        self.assertEqual(again["status"], "success", f"redelivery: {again}")
        self.assertEqual(
            frappe.db.count(
                "Journal Entry", {"cheque_no": f"{self.payment_id}_chargeback_{chargeback_id}_reversed"}
            ),
            1,
            "the redelivery booked a second counter-entry",
        )
        self.assertEqual(len(self._donation_chargeback_rows()), 2)
        self.assertEqual(self._income_balance(), income_after_chargeback + self.CHARGEBACK_AMOUNT)
