"""
Payment Processors — additional coverage
=========================================

Covers the parts of payment_processors.py not exercised by
test_payment_processors.py, against REAL DocTypes (no mocking of the logic under
test):

  - AbstractPaymentProcessor.extract_mollie_payment_data (dict + object payloads)
  - MembershipPaymentProcessor._link_to_membership_invoice
      (linked / no-customer / no-unpaid-invoice branches)
  - MembershipPaymentProcessor.process_failed_payment (records a Cancelled entry)
  - MembershipPaymentProcessor.check_idempotency
  - MembershipPaymentProcessor.process_successful_payment end-to-end through the
    REAL (now-fixed) PaymentEntryFactory — regression for the custom_member bug
  - DonationPaymentProcessor._ensure_customer_bank_account /
    _extract_and_save_consumer_bank_data (Bank Account link creation)
  - DonationPaymentProcessor._create_bank_transaction_for_donation
      (no-donor / no-customer early returns)
  - DonationPaymentProcessor.process_failed_payment

The Mollie SDK is never contacted; mollie_data is a plain dict and payment_data
is a types.SimpleNamespace shaped like a Mollie payment object.
"""

import types

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.payment_processors import (
    DonationPaymentProcessor,
    MembershipPaymentProcessor,
    PaymentStatus,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    customer_for_member,
    ensure_bank_account_for_company,
    ensure_mollie_bank_gl_account,
    ensure_mollie_mode_of_payment,
    ensure_service_item,
    get_test_company,
)


class TestExtractMolliePaymentData(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.processor = MembershipPaymentProcessor()

    def test_extract_from_object_like_payment(self):
        payment = types.SimpleNamespace(
            id="tr_extract_obj_001",
            status="paid",
            amount={"value": "12.34", "currency": "EUR"},
            method="ideal",
            customer_id="cst_x",
            mandate_id="mdt_x",
            subscription_id="sub_x",
            created_at="2025-01-01T00:00:00+00:00",
            paid_at="2025-01-02T00:00:00+00:00",
            description="membership dues",
            metadata={"record_id": "INV-1"},
            sequence_type="recurring",
        )
        data = self.processor.extract_mollie_payment_data(payment)
        self.assertEqual(data["payment_id"], "tr_extract_obj_001")
        self.assertEqual(data["status"], "paid")
        self.assertEqual(float(data["amount"]), 12.34)
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["method"], "ideal")
        self.assertEqual(data["customer_id"], "cst_x")
        self.assertEqual(data["subscription_id"], "sub_x")
        self.assertEqual(data["sequence_type"], "recurring")
        self.assertEqual(data["metadata"], {"record_id": "INV-1"})


class TestMembershipInvoiceLinking(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.processor = MembershipPaymentProcessor()
        self.company = get_test_company()
        self.mollie_account = ensure_mollie_bank_gl_account(self.company)
        ensure_mollie_mode_of_payment()

    def _make_sales_invoice(self, customer, amount, posting_date=None, submit=True):
        """Fixtures helper: create+submit an unpaid Sales Invoice for the customer.

        `posting_date` is exposed because the defect being tested ordered on it;
        `submit=False` leaves a DRAFT, which is what the old `status != "Cancelled"`
        filter wrongly admitted.
        """
        income = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Income Account", "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Income", "is_group": 0}, "name"
        )
        cost_center = frappe.db.get_value("Company", self.company, "cost_center") or frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 0}, "name"
        )
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": self.company,
                "posting_date": posting_date or frappe.utils.today(),
                "set_posting_time": 1,
                "due_date": posting_date or frappe.utils.today(),
                "items": [
                    {
                        "item_code": ensure_service_item(),
                        "description": "Membership Dues",
                        "qty": 1,
                        "rate": amount,
                        "income_account": income,
                        "cost_center": cost_center,
                    }
                ],
            }
        )
        si.insert(ignore_permissions=True)
        if submit:
            si.submit()
        return si

    def test_link_no_customer_returns_no_customer(self):
        member = self.create_test_member(
            first_name="NoCust", last_name="Link", email="nocust.link@example.com"
        )
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()
        result = self.processor._link_to_membership_invoice(member, {"amount": "10.00"}, object())
        self.assertEqual(result["status"], "no_customer")

    def test_link_no_unpaid_invoices(self):
        member = self.create_test_member(first_name="NoInv", last_name="Link", email="noinv.link@example.com")
        customer_for_member(member)
        member.reload()
        result = self.processor._link_to_membership_invoice(member, {"amount": "10.00"}, object())
        self.assertEqual(result["status"], "no_unpaid_invoices")

    def test_link_allocates_against_unpaid_invoice(self):
        member = self.create_test_member(
            first_name="Linkable", last_name="Inv", email="linkable.inv@example.com"
        )
        customer = customer_for_member(member)
        member.reload()
        si = self._make_sales_invoice(customer, 25.0)

        # Build a real Payment Entry to allocate against the invoice.
        pe = self.create_test_payment_entry(
            paid_amount=25.0, reference_no=f"tr_link_{frappe.generate_hash()[:8]}", party=customer
        )
        result = self.processor._link_to_membership_invoice(member, {"amount": "25.00"}, pe)

        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["invoice"], si.name)
        self.assertAlmostEqual(float(result["allocated_amount"]), 25.0, places=2)
        # The PE now references the invoice.
        pe.reload()
        ref_invoices = [r.reference_name for r in pe.references]
        self.assertIn(si.name, ref_invoices)

    def test_two_unpaid_invoices_and_nothing_to_choose_on_is_refused(self):
        """`posting_date desc limit 1`, and NO amount comparison at all (#567).

        Unlike the subscription path, this site never computed the discriminator --
        it took the most recently posted invoice with an outstanding balance and
        appended a Payment Entry reference against it. A member with two open dues
        invoices had a Mollie payment allocated to whichever was posted later.

        Red against develop: `linked`, against the 90.00 invoice, for a 17.50 payment.
        """
        self.expectErrorLog("Mollie Membership Payment Ambiguous")
        member = self.create_test_member(
            first_name="AmbigTwo", last_name="Link", email="ambigtwo.link@example.com"
        )
        customer = customer_for_member(member)
        member.reload()
        older = self._make_sales_invoice(customer, 25.0, posting_date=add_days(today(), -10))
        newer = self._make_sales_invoice(customer, 90.0)
        pe = self.create_test_payment_entry(
            paid_amount=17.50, reference_no=f"tr_ambig_{frappe.generate_hash()[:8]}", party=customer
        )

        result = self.processor._link_to_membership_invoice(member, {"amount": "17.50"}, pe)

        self.assertNotEqual(result["status"], "linked", msg=result)
        pe.reload()
        referenced = [r.reference_name for r in pe.references]
        for invoice in (older, newer):
            self.assertNotIn(
                invoice.name,
                referenced,
                "no reference may be appended when the invoice is a choice, not a match",
            )

    def test_the_invoice_matching_the_amount_is_chosen(self):
        """The matching invoice is deliberately the OLDER one.

        So `posting_date desc limit 1` picks the other one deterministically -- with
        both invoices posted today the tie-break is unspecified and the test could
        pass against the bug by luck.
        """
        member = self.create_test_member(
            first_name="MatchTwo", last_name="Link", email="matchtwo.link@example.com"
        )
        customer = customer_for_member(member)
        member.reload()
        wanted = self._make_sales_invoice(customer, 25.0, posting_date=add_days(today(), -10))
        decoy = self._make_sales_invoice(customer, 90.0)
        self.assertGreater(getdate(decoy.posting_date), getdate(wanted.posting_date))
        pe = self.create_test_payment_entry(
            paid_amount=25.0, reference_no=f"tr_match_{frappe.generate_hash()[:8]}", party=customer
        )

        result = self.processor._link_to_membership_invoice(member, {"amount": "25.00"}, pe)

        self.assertEqual(result["status"], "linked", msg=result)
        self.assertEqual(result["invoice"], wanted.name)

    def test_a_draft_invoice_is_not_a_candidate(self):
        """`status != "Cancelled"` admits DRAFTS; the filter has to be `docstatus: 1`.

        Reproduces the state veg11 actually carries: #559 measured 35 Sales Invoices
        with an Unpaid/Overdue status and `docstatus = 0`, 28 of them with a member --
        a state `SalesInvoice.set_status` cannot produce, so something writes `status`
        directly. The forgery below is that state, not an invented one.

        Red against develop: the draft is posted later, so it wins `posting_date desc`
        and the payment is referenced against an invoice that was never issued.
        """
        member = self.create_test_member(
            first_name="DraftCand", last_name="Link", email="draftcand.link@example.com"
        )
        customer = customer_for_member(member)
        member.reload()
        real = self._make_sales_invoice(customer, 25.0, posting_date=add_days(today(), -10))
        draft = self._make_sales_invoice(customer, 25.0, submit=False)
        frappe.db.set_value(
            "Sales Invoice",
            draft.name,
            {"status": "Unpaid", "outstanding_amount": 25.0},
            update_modified=False,
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", draft.name, "docstatus"), 0)
        pe = self.create_test_payment_entry(
            paid_amount=25.0, reference_no=f"tr_draft_{frappe.generate_hash()[:8]}", party=customer
        )

        result = self.processor._link_to_membership_invoice(member, {"amount": "25.00"}, pe)

        self.assertEqual(result["status"], "linked", msg=result)
        self.assertEqual(
            result["invoice"], real.name, "an unsubmitted invoice is not a payable candidate"
        )


class TestMembershipProcessorFlows(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.processor = MembershipPaymentProcessor()
        self.company = get_test_company()
        ensure_mollie_bank_gl_account(self.company)
        ensure_mollie_mode_of_payment()
        self.member = self.create_test_member(
            first_name="Flow", last_name="Member", email="flow.member@example.com"
        )
        self.context = PaymentContext("membership", "Member", self.member.name)

    def test_process_failed_payment_records_cancelled_entry(self):
        payment_data = types.SimpleNamespace(status="failed", amount={"value": "30.00"})
        mollie_data = {"payment_id": "tr_failed_mem_001", "amount": "30.00"}
        result = self.processor.process_failed_payment(self.context, payment_data, mollie_data)
        self.assertTrue(result.success)
        member = frappe.get_doc("Member", self.member.name)
        # The Member Payment History child table has no mollie_payment_id field;
        # the payment id is recorded in `notes`. Match on that.
        cancelled = [
            r
            for r in member.payment_history
            if r.payment_status == PaymentStatus.CANCELLED and "tr_failed_mem_001" in (r.notes or "")
        ]
        self.assertTrue(cancelled, "a Cancelled membership payment-history row must be recorded")

    def test_check_idempotency_unprocessed(self):
        status = self.processor.check_idempotency(self.context, "tr_never_seen_mem")
        self.assertFalse(status["payment_entry_created"])
        self.assertFalse(status["payment_history_exists"])
        self.assertFalse(status["all_complete"])

    def test_process_successful_payment_end_to_end_real_factory(self):
        """Drives the REAL PaymentEntryFactory (regression for custom_member bug).

        Previously _create_customer_for_member queried a non-existent
        custom_member column; the factory returned None and this would raise
        'Failed to create Payment Entry'. With the fix the PE is created.
        """
        customer = customer_for_member(self.member)
        self.member.reload()
        payment_id = f"tr_mem_e2e_{frappe.generate_hash()[:10]}"
        mollie_data = {
            "payment_id": payment_id,
            "amount": "25.00",
            "method": "directdebit",
            "paid_at": "2025-03-01T00:00:00+00:00",
        }
        result = self.processor.process_successful_payment(self.context, types.SimpleNamespace(), mollie_data)
        self.assertTrue(result.success, f"unexpected failure: {result.message}")
        self.assertTrue(result.data.get("payment_entry"))
        # A real submitted Payment Entry exists with our reference.
        pe_name = frappe.db.get_value("Payment Entry", {"reference_no": payment_id}, "name")
        self.assertTrue(pe_name)
        self.assertEqual(frappe.db.get_value("Payment Entry", pe_name, "party"), customer)
        # Member payment history recorded the Mollie payment (the payment id is
        # carried in `notes`; the child table has no mollie_payment_id field).
        member = frappe.get_doc("Member", self.member.name)
        paid_rows = [
            r
            for r in member.payment_history
            if r.payment_status == PaymentStatus.PAID and payment_id in (r.notes or "")
        ]
        self.assertTrue(paid_rows, "a Paid membership payment-history row must reference the payment id")


class TestDonationBankDataAndTransaction(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.processor = DonationPaymentProcessor()
        self.company = get_test_company()

    def test_ensure_customer_bank_account_creates_link(self):
        member = self.create_test_member(
            first_name="BankLink", last_name="Cust", email="banklink.cust@example.com"
        )
        customer = customer_for_member(member)
        iban = "NL91ABNA0417164300"
        self.processor._ensure_customer_bank_account(customer, iban)
        ba = frappe.db.get_value("Bank Account", {"iban": iban}, ["party_type", "party"], as_dict=True)
        self.assertIsNotNone(ba)
        self.assertEqual(ba.party_type, "Customer")
        self.assertEqual(ba.party, customer)

    def test_extract_and_save_consumer_bank_data_from_details(self):
        member = self.create_test_member(
            first_name="Consumer", last_name="Bank", email="consumer.bank@example.com"
        )
        customer = customer_for_member(member)
        payment_data = types.SimpleNamespace(details={"consumerAccount": "NL91ABNA0417164300"})
        self.processor._extract_and_save_consumer_bank_data(customer, payment_data)
        exists = frappe.db.exists("Bank Account", {"iban": "NL91ABNA0417164300", "party": customer})
        self.assertTrue(exists)

    def test_extract_and_save_consumer_bank_data_invalid_iban_is_noop(self):
        member = self.create_test_member(
            first_name="BadIban", last_name="Bank", email="badiban.bank@example.com"
        )
        customer = customer_for_member(member)
        payment_data = types.SimpleNamespace(details={"consumerAccount": "NOT-AN-IBAN"})
        # Should not raise and should not create a Bank Account.
        self.processor._extract_and_save_consumer_bank_data(customer, payment_data)
        self.assertFalse(frappe.db.exists("Bank Account", {"iban": "NOT-AN-IBAN"}))

    def test_create_bank_transaction_no_donor_returns_none(self):
        donation = types.SimpleNamespace(name="DON-NO-DONOR", donor=None)
        result = self.processor._create_bank_transaction_for_donation(
            donation, {"payment_id": "tr_x", "amount": "10.00"}
        )
        self.assertIsNone(result)

    def test_create_bank_transaction_donor_without_customer_returns_none(self):
        donor = self.create_test_donor(donor_email="nocust.donor@example.com")
        # Donor intentionally has no linked customer.
        donation = types.SimpleNamespace(name="DON-NO-CUST", donor=donor.name)
        result = self.processor._create_bank_transaction_for_donation(
            donation, {"payment_id": "tr_y", "amount": "10.00"}
        )
        self.assertIsNone(result)

    def test_create_bank_transaction_missing_config_returns_none(self):
        """When Mollie bank config is missing/invalid, BT creation returns None
        (does not raise) — the donor/customer are present so we get past the
        early returns and reach the config-error branch."""
        member = self.create_test_member(
            first_name="BTDonor", last_name="Test", email="btdonor.test@example.com"
        )
        customer = customer_for_member(member)
        donor = self.create_test_donor(donor_email="bt.donor@example.com")
        frappe.db.set_value("Donor", donor.name, "customer", customer)
        donor.reload()
        donation = self.create_test_donation(donor=donor.name, amount=15.0, paid=0)
        mollie_data = {
            "payment_id": f"tr_bt_{frappe.generate_hash()[:10]}",
            "amount": "15.00",
            "currency": "EUR",
            "paid_at": "2025-03-05T00:00:00+00:00",
        }
        # Force the config helper to report an error to deterministically exercise
        # the config-error branch (rather than depending on site Mollie config).
        from unittest.mock import patch

        with patch.object(
            self.processor.bank_tx_creator,
            "get_mollie_bank_account_config",
            return_value={"error": "no clearing account configured"},
        ):
            result = self.processor._create_bank_transaction_for_donation(donation, mollie_data)
        self.assertIsNone(result)

    def test_process_failed_donation_payment(self):
        member = self.create_test_member(
            first_name="FailDon", last_name="Test", email="faildon.test@example.com"
        )
        customer = customer_for_member(member)
        donor = self.create_test_donor(donor_email="faildon.donor@example.com")
        frappe.db.set_value("Donor", donor.name, "customer", customer)
        donation = self.create_test_donation(donor=donor.name, amount=20.0, paid=0)
        # Reset to draft so the processor can append + save.
        donation.reload()
        if donation.docstatus == 1:
            frappe.db.set_value("Donation", donation.name, "docstatus", 0)
            donation.reload()

        context = PaymentContext("donation", "Donation", donation.name)
        payment_data = types.SimpleNamespace(status="failed")
        mollie_data = {"payment_id": "tr_failed_don_001", "amount": "20.00"}
        result = self.processor.process_failed_payment(context, payment_data, mollie_data)
        self.assertTrue(result.success)
        updated = frappe.get_doc("Donation", donation.name)
        cancelled = [
            r
            for r in updated.payments
            if getattr(r, "mollie_payment_id", None) == "tr_failed_don_001"
            and r.payment_status == PaymentStatus.CANCELLED
        ]
        self.assertTrue(cancelled)
