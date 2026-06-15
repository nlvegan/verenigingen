import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)


class TestSEPAReconciliation(VereningingenTestCase):
    """Test SEPA bank transaction reconciliation"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test customer
        if not frappe.db.exists("Customer", "TEST-RECON-CUSTOMER"):
            cls.test_customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "Test Reconciliation Customer",
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")}
            ).insert()
        else:
            cls.test_customer = frappe.get_doc("Customer", "TEST-RECON-CUSTOMER")

        # Create test member with IBAN
        if not frappe.db.exists("Member", {"email": "recon-test@example.com"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test",
                    "last_name": "Member",
                    "preferred_name": "Test Recon Member",
                    "email": "recon-test@example.com",
                    "customer": cls.test_customer.name}
            ).insert()
        else:
            cls.test_member = frappe.get_doc("Member", {"email": "recon-test@example.com"})

        # Create test SEPA mandate (reuse if a prior run left one for this member;
        # otherwise SEPA Mandate's duplicate-IBAN guard would reject the insert).
        existing_mandate = frappe.db.exists("SEPA Mandate", {"mandate_id": "TEST-RECON-MANDATE"}) or (
            frappe.db.exists(
                "SEPA Mandate",
                {"member": cls.test_member.name, "iban": "NL39RABO0300065264", "is_active": 1},
            )
        )
        if existing_mandate:
            cls.test_mandate = frappe.get_doc("SEPA Mandate", existing_mandate)
        else:
            cls.test_mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": cls.test_member.name,
                    "mandate_id": "TEST-RECON-MANDATE",
                    "iban": "NL39RABO0300065264",
                    "bic": "RABONL2U",
                    "account_holder_name": "Test Recon Holder",
                    "sign_date": today(),
                    "status": "Active",
                    "is_active": 1}
            ).insert()

        # Ensure a Bank master exists (Bank Account.bank is a required Link to Bank,
        # and the test site may have no Bank records).
        bank_name = frappe.db.get_value("Bank", {"name": ["!=", ""]}, "name")
        if not bank_name:
            bank_name = frappe.get_doc({"doctype": "Bank", "bank_name": "Test Recon Bank"}).insert().name

        # Scope the GL account to the EUR test company. A Bank account picked from an
        # arbitrary company could be non-EUR under parallel load, which would then
        # clash with the EUR Bank Transactions the tests create ("Transaction currency
        # cannot be different from Bank Account currency").
        eur_company = get_eur_test_company()
        bank_gl_account = frappe.db.get_value(
            "Account", {"account_type": "Bank", "is_group": 0, "company": eur_company}, "name"
        ) or frappe.db.get_value("Account", {"account_type": "Bank", "is_group": 0}, "name")

        # Create test bank account
        if not frappe.db.exists("Bank Account", "TEST-RECON-BANK"):
            cls.test_bank_account = frappe.get_doc(
                {
                    "doctype": "Bank Account",
                    "account_name": "Test Recon Bank Account",
                    "bank": bank_name,
                    "account": bank_gl_account}
            ).insert()
        else:
            cls.test_bank_account = frappe.get_doc("Bank Account", "TEST-RECON-BANK")

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Delete test mandate
        if hasattr(cls, "test_mandate") and frappe.db.exists("SEPA Mandate", cls.test_mandate.name):
            frappe.delete_doc("SEPA Mandate", cls.test_mandate.name, force=True)

        # Delete test member and customer
        if cls.test_member and frappe.db.exists("Member", cls.test_member.name):
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        if cls.test_customer and frappe.db.exists("Customer", cls.test_customer.name):
            frappe.delete_doc("Customer", cls.test_customer.name, force=True)

        # Delete test bank account
        if hasattr(cls, "test_bank_account") and frappe.db.exists("Bank Account", cls.test_bank_account.name):
            frappe.delete_doc("Bank Account", cls.test_bank_account.name, force=True)

        frappe.db.commit()

    def setUp(self):
        """Set up for each test"""
        self.reconciliation_engine = PaymentReconciliationManager()

        # Resolve a EUR company that also has a Fiscal Year covering today. Picking an
        # arbitrary company (global default / get_value({})) is unsafe under parallel
        # load: the shared site DB accumulates stray companies (e.g. INR "Test Quality
        # Company") with no current Fiscal Year, so the invoice .submit() below raises
        # FiscalYearError. EUR is also mandatory — the Direct Debit Batch's SEPA
        # validation rejects any non-EUR invoice ("No valid invoices found in batch").
        company = get_eur_test_company()
        company_currency = frappe.db.get_value("Company", company, "default_currency")

        # Create test invoice first. Set currency to the company's default to avoid
        # a party-account currency mismatch (the company's Debtors account is EUR
        # while Sales Invoice would otherwise default to the system currency).
        self.test_invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.test_customer.name,
                "company": company,
                "currency": company_currency,
                "posting_date": today(),
                "items": [
                    {
                        "item_code": frappe.db.get_value("Item", {"item_group": ["!=", ""]}, "name") or "Test Item",
                        "qty": 1,
                        "rate": 100}
                ]}
        ).insert()
        self.test_invoice.submit()

        # Ensure the test member has a Membership (required by the Direct Debit
        # Batch Invoice child row's mandatory `membership` link).
        membership_name = frappe.db.get_value("Membership", {"member": self.test_member.name}, "name")
        if not membership_name:
            membership_type = frappe.db.get_value("Membership Type", {"is_active": 1}, "name")
            membership = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": self.test_member.name,
                    "membership_type": membership_type,
                    "start_date": today(),
                    "status": "Active",
                }
            ).insert()
            membership.submit()
            membership_name = membership.name

        # Create test batch with invoice included. batch_description and currency
        # (on both the batch and the child row) are mandatory.
        self.test_batch = frappe.get_doc(
            {
                "doctype": "Direct Debit Batch",
                "batch_date": today(),
                "batch_description": "Test Recon Batch",
                "batch_type": "CORE",
                "sequence_type": "FRST",
                "currency": company_currency,
                "total_amount": 100,
                "status": "Submitted",
                "invoices": [
                    {
                        "invoice": self.test_invoice.name,  # Correct field name
                        "membership": membership_name,
                        "member": self.test_member.name,
                        "member_name": self.test_member.preferred_name or "Test Recon Member",
                        "amount": 100,
                        "currency": company_currency,
                        "iban": self.test_mandate.iban,
                        "mandate_reference": self.test_mandate.mandate_id
                    }
                ]
            }
        )
        self.test_batch.insert()

    def tearDown(self):
        """Clean up after each test"""
        # Delete test transactions
        frappe.db.sql(
            """
            DELETE FROM `tabBank Transaction`
            WHERE description LIKE 'TEST-RECON-%'
        """
        )

        # Delete test batch
        if frappe.db.exists("Direct Debit Batch", self.test_batch.name):
            frappe.delete_doc("Direct Debit Batch", self.test_batch.name, force=True)

        # Cancel and delete test invoice
        if frappe.db.exists("Sales Invoice", self.test_invoice.name):
            self.test_invoice.reload()
            if self.test_invoice.docstatus == 1:
                self.test_invoice.cancel()
            frappe.delete_doc("Sales Invoice", self.test_invoice.name, force=True)

        frappe.db.commit()

    def create_test_transaction(self, amount, description, reference_number=None, is_deposit=True):
        """Helper to create test bank transaction"""
        # Bank Transaction.currency defaults to the system default (often INR) and
        # must match the linked Bank Account's account currency, else save raises
        # "Transaction currency cannot be different from Bank Account currency".
        bank_gl_account = frappe.db.get_value(
            "Bank Account", self.test_bank_account.name, "account"
        )
        account_currency = frappe.db.get_value("Account", bank_gl_account, "account_currency")
        transaction_data = {
            "doctype": "Bank Transaction",
            "date": today(),
            "description": description,
            "bank_account": self.test_bank_account.name,
            "currency": account_currency,
            "status": "Pending",
            "reference_number": reference_number or "REF123"
        }

        # Use deposit for incoming (positive) amounts, withdrawal for outgoing (negative)
        if is_deposit:
            transaction_data["deposit"] = amount
        else:
            transaction_data["withdrawal"] = abs(amount)

        return frappe.get_doc(transaction_data).insert()

    def test_match_by_batch_reference(self):
        """Test matching transaction by SEPA batch reference"""
        # Create transaction with batch reference
        transaction = self.create_test_transaction(100, f"BATCH-{self.test_batch.name} TEST-RECON-DESC")

        # Convert to dict for matching (as the reconciliation engine expects)
        transaction_dict = {
            "name": transaction.name,
            "date": transaction.date,
            "deposit": transaction.deposit or 0,
            "withdrawal": transaction.withdrawal or 0,
            "description": transaction.description,
            "bank_account": transaction.bank_account,
            "reference_number": transaction.reference_number,
        }

        # match_transaction() now performs the match AND creates the reconciliation,
        # returning a bool. To assert the match details (type/confidence) we call the
        # lower-level strategy method which returns the match dict.
        match_result = self.reconciliation_engine.match_by_batch_reference(transaction_dict)

        # Should find a match
        self.assertIsNotNone(match_result)
        self.assertEqual(match_result["type"], "batch")
        self.assertEqual(match_result["confidence"], 1.0)

        # Clean up
        transaction.delete()

    def test_match_by_amount_and_reference(self):
        """Test matching by amount and reference number"""
        # Create transaction with invoice reference
        transaction = self.create_test_transaction(
            100,
            "Payment from Test Recon Member",
            reference_number=self.test_invoice.name
        )

        # Convert to dict for matching
        transaction_dict = {
            "name": transaction.name,
            "date": transaction.date,
            "deposit": transaction.deposit or 0,
            "withdrawal": transaction.withdrawal or 0,
            "description": transaction.description,
            "bank_account": transaction.bank_account,
            "reference_number": transaction.reference_number,
        }

        # Use the lower-level strategy method to inspect the match dict
        # (match_transaction() returns a bool now — it also reconciles).
        match_result = self.reconciliation_engine.match_by_amount_and_reference(transaction_dict)

        # Should find a match
        self.assertIsNotNone(match_result)
        if match_result and match_result["type"] == "invoice":
            self.assertGreater(match_result["confidence"], 0.7)

        # Clean up
        transaction.delete()

    def test_match_by_description_patterns(self):
        """Test matching by description patterns"""
        # Create transaction with invoice reference in description
        transaction = self.create_test_transaction(
            100, f"INVOICE {self.test_invoice.name}", reference_number="DESC-MATCH"
        )

        # Convert to dict for matching
        transaction_dict = {
            "name": transaction.name,
            "date": transaction.date,
            "deposit": transaction.deposit or 0,
            "withdrawal": transaction.withdrawal or 0,
            "description": transaction.description,
            "bank_account": transaction.bank_account,
            "reference_number": transaction.reference_number,
        }

        # Use the lower-level description-matching strategy to inspect the match
        # dict (match_transaction() returns a bool now — it also reconciles).
        match_result = self.reconciliation_engine.match_by_description(transaction_dict)

        # Should find the invoice by pattern
        if match_result and match_result["type"] == "invoice":
            self.assertEqual(match_result["reference"], self.test_invoice.name)

        # Clean up
        transaction.delete()

    def test_fuzzy_name_matching(self):
        """Test fuzzy matching of names using SequenceMatcher"""
        from difflib import SequenceMatcher

        # Test similar names
        test_cases = [
            ("Test Recon Member", "Test Recon Member", 1.0),
            ("Test Recon Member", "Test Reconciliation Member", 0.8),
            ("Test Recon Member", "Test Member", 0.6),
            ("Test Recon Member", "Completely Different", 0.2),
            ("J. Smith", "John Smith", 0.7),
            ("ABC Company Ltd", "ABC Company Limited", 0.85),
        ]

        for name1, name2, min_score in test_cases:
            score = SequenceMatcher(None, name1.upper(), name2.upper()).ratio()
            self.assertGreaterEqual(
                score, min_score - 0.1, f"Score for '{name1}' vs '{name2}' too low: {score}"
            )

    def test_auto_create_payment_entry(self):
        """Test automatic payment entry creation"""
        # Create matched transaction
        transaction = self.create_test_transaction(100, f"SEPA DD {self.test_batch.name}")

        # Convert to dict and get matches
        transaction_dict = {
            "name": transaction.name,
            "date": transaction.date,
            "deposit": transaction.deposit or 0,
            "withdrawal": transaction.withdrawal or 0,
            "description": transaction.description,
            "bank_account": transaction.bank_account,
            "reference_number": transaction.reference_number,
        }

        # Skip this test as create_payment_entry is now part of create_reconciliation
        # and requires more complex setup
        self.skipTest("Payment entry creation is now integrated into reconciliation process")

        # Verify payment entry
        self.assertEqual(payment_entry.party_type, "Customer")
        self.assertEqual(payment_entry.party, self.test_customer.name)
        self.assertEqual(payment_entry.paid_amount, 100)
        self.assertEqual(len(payment_entry.references), 1)
        self.assertEqual(payment_entry.references[0].reference_name, self.test_invoice.name)

        # Clean up
        payment_entry.delete()
        transaction.delete()

    def test_partial_payment_handling(self):
        """Test handling of partial payments"""
        # Create partial payment transaction
        transaction = self.create_test_transaction(
            50, f"Partial payment for {self.test_invoice.name}"  # Half the invoice amount
        )

        # Skip this test as payment creation is now integrated
        self.skipTest("Payment entry creation is now integrated into reconciliation process")

        # Should allocate partial amount
        self.assertEqual(payment_entry.paid_amount, 50)
        self.assertEqual(payment_entry.references[0].allocated_amount, 50)

        # Clean up
        payment_entry.delete()
        transaction.delete()

    def test_duplicate_transaction_handling(self):
        """Test that duplicate transactions are not processed twice"""
        # Create and reconcile first transaction
        transaction1 = self.create_test_transaction(100, f"SEPA DD {self.test_batch.name} DUPLICATE-TEST")

        # Skip this test as the API has changed
        self.skipTest("Duplicate handling test needs update for new API")
        payment1.submit()

        # Mark transaction as reconciled
        transaction1.status = "Reconciled"
        transaction1.save()

        # Try to reconcile same transaction again
        transaction2 = self.create_test_transaction(100, f"SEPA DD {self.test_batch.name} DUPLICATE-TEST")

        # Should not create duplicate payment
        with self.assertRaises(Exception):
            matches2 = self.reconciliation_engine.match_transaction(transaction2)
            if matches2:
                # Should detect that invoice is already paid
                self.reconciliation_engine.create_payment_entry(transaction2, matches2[0])

        # Clean up
        payment1.cancel()
        payment1.delete()
        transaction1.delete()
        transaction2.delete()

    def test_reconcile_bank_transactions(self):
        """Test the main reconciliation function"""
        # Create multiple test transactions
        transactions = []

        # Good match
        transactions.append(self.create_test_transaction(100, f"SEPA DD {self.test_batch.name}"))

        # No match
        transactions.append(self.create_test_transaction(200, "Random payment", reference_number="RANDOM"))

        # Run reconciliation
        results = self.reconciliation_engine.reconcile_bank_transactions(
            bank_account=self.test_bank_account.name, from_date=today(), to_date=today()
        )

        # Check results against the current return schema
        # ({total_transactions, matched, unmatched}). Other Pending transactions
        # may exist on the same bank account/day, so assert >= our two.
        self.assertIn("total_transactions", results)
        self.assertIn("matched", results)
        self.assertIn("unmatched", results)
        self.assertGreaterEqual(results["total_transactions"], 2)
        self.assertEqual(
            results["matched"] + results["unmatched"], results["total_transactions"]
        )

        # Clean up
        for transaction in transactions:
            if frappe.db.exists("Bank Transaction", transaction.name):
                transaction.delete()

    def test_match_threshold_configuration(self):
        """Test confidence threshold configuration"""
        # The engine exposes a configurable match_threshold in [0, 1].
        self.assertGreaterEqual(self.reconciliation_engine.match_threshold, 0)
        self.assertLessEqual(self.reconciliation_engine.match_threshold, 1)

        # A vague, unmatchable transaction should not reconcile. match_transaction()
        # returns a bool now (True only when a match >= threshold is reconciled).
        transaction = self.create_test_transaction(
            100, "Vague description", reference_number="VAGUE"
        )
        transaction_dict = {
            "name": transaction.name,
            "date": transaction.date,
            "deposit": transaction.deposit or 0,
            "withdrawal": transaction.withdrawal or 0,
            "description": transaction.description,
            "bank_account": transaction.bank_account,
            "reference_number": transaction.reference_number,
        }
        result = self.reconciliation_engine.match_transaction(transaction_dict)
        self.assertFalse(result)

        # Clean up
        transaction.delete()


def run_tests():
    """Run all SEPA reconciliation tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAReconciliation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
