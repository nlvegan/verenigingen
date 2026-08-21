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

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, shared_fixture
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
    def list(self):
        # No chargebacks -> iterable, nothing pending.
        return []


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
    # These three build shared accounting masters on a shared company: two GL
    # accounts, a Bank and the Bank Account linked to the clearing account. The
    # captured-insert drain claims every row a test inserts and deletes it at
    # teardown, so an undecorated build site hands the whole set to whichever test
    # ran first and takes it from every later class in the shard (#330, #444).
    #
    # Measured on a purged `test_site_4`, same fixtures, same names:
    #
    #   this module, undecorated       -> 17/17 green, all three fixtures GONE
    #   test_recurring_donation_charge -> 37/37 green, all three SURVIVE
    #                                     (its copies already carry the decorator)
    #
    # The decorator was the only difference.
    @shared_fixture
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

    @shared_fixture
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

    @shared_fixture
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
