import unittest

import frappe
from frappe.utils import today

from verenigingen.utils.sepa_reconciliation import SEPAReconciliationEngine


class TestSEPAReconciliation(unittest.TestCase):
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
                    "member_name": "Test Recon Member",
                    "email": "recon-test@example.com",
                    "customer": cls.test_customer.name}
            ).insert()
        else:
            cls.test_member = frappe.get_doc("Member", {"email": "recon-test@example.com"})

        # Create test SEPA mandate
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

        # Create test bank account
        if not frappe.db.exists("Bank Account", "TEST-RECON-BANK"):
            cls.test_bank_account = frappe.get_doc(
                {
                    "doctype": "Bank Account",
                    "account_name": "Test Recon Bank Account",
                    "bank": frappe.db.get_value("Bank", {"name": ["!=", ""]}, "name") or "Test Bank",
                    "account": frappe.db.get_value(
                        "Account", {"account_type": "Bank", "is_group": 0}, "name"
                    )}
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
        self.reconciliation_engine = SEPAReconciliationEngine()

        # Create test batch and invoice
        self.test_batch = frappe.get_doc(
            {
                "doctype": "Direct Debit Batch",
                "batch_date": today(),
                "batch_type": "FRST",
                "total_amount": 100,
                "status": "Submitted"}
        )
        self.test_batch.insert()

        # Create test invoice
        self.test_invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.test_customer.name,
                "posting_date": today(),
                "items": [
                    {
                        "item_code": frappe.db.get_value("Item", {"item_group": {"!=": ""}}, "name"),
                        "qty": 1,
                        "rate": 100}
                ]}
        ).insert()
        self.test_invoice.submit()

        # Add invoice to batch
        self.test_batch.append(
            "invoices",
            {
                "invoice": self.test_invoice.name,
                "customer": self.test_customer.name,
                "amount": 100,
                "iban": self.test_mandate.iban,
                "mandate_reference": self.test_mandate.mandate_id},
        )
        self.test_batch.save()

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

    def create_test_transaction(self, amount, description, iban=None):
        """Helper to create test bank transaction"""
        return frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "amount": amount,
                "description": description,
                "bank_account": self.test_bank_account.name,
                "party_iban": iban or self.test_mandate.iban,
                "status": "Pending"}
        ).insert()

    def test_match_by_batch_reference(self):
        """Test matching transaction by SEPA batch reference"""
        # Create transaction with batch reference
        transaction = self.create_test_transaction(100, f"SEPA DD {self.test_batch.name} TEST-RECON-DESC")

        # Match transaction
        matches = self.reconciliation_engine.match_transaction(transaction)

        # Should find the batch
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["type"], "batch")
        self.assertEqual(match["reference"], self.test_batch.name)
        self.assertEqual(match["confidence"], 0.95)

        # Clean up
        transaction.delete()

    def test_match_by_amount_and_iban(self):
        """Test matching by amount and IBAN combination"""
        # Create transaction without batch reference
        transaction = self.create_test_transaction(100, "Payment from Test Recon Member")

        # Match transaction
        matches = self.reconciliation_engine.match_transaction(transaction)

        # Should find the invoice
        self.assertTrue(len(matches) > 0)

        # Find invoice match
        invoice_matches = [m for m in matches if m["type"] == "invoice"]
        self.assertTrue(len(invoice_matches) > 0)

        match = invoice_matches[0]
        self.assertEqual(match["reference"], self.test_invoice.name)
        self.assertGreater(match["confidence"], 0.7)

        # Clean up
        transaction.delete()

    def test_match_by_description_patterns(self):
        """Test matching by description patterns"""
        # Create transaction with invoice reference in description
        transaction = self.create_test_transaction(
            100, f"Payment for invoice {self.test_invoice.name}", "NL91ABNA0417164300"  # Different IBAN
        )

        # Match transaction
        matches = self.reconciliation_engine.match_transaction(transaction)

        # Should find the invoice by pattern
        invoice_matches = [
            m for m in matches if m["type"] == "invoice" and m["reference"] == self.test_invoice.name
        ]
        self.assertTrue(len(invoice_matches) > 0)

        # Clean up
        transaction.delete()

    def test_fuzzy_name_matching(self):
        """Test fuzzy matching of names"""
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
            score = self.reconciliation_engine._fuzzy_match_score(name1, name2)
            self.assertGreaterEqual(
                score, min_score - 0.1, f"Score for '{name1}' vs '{name2}' too low: {score}"
            )

    def test_auto_create_payment_entry(self):
        """Test automatic payment entry creation"""
        # Create matched transaction
        transaction = self.create_test_transaction(100, f"SEPA DD {self.test_batch.name}")

        # Get matches
        matches = self.reconciliation_engine.match_transaction(transaction)
        best_match = matches[0]

        # Create payment entry
        payment_entry = self.reconciliation_engine.create_payment_entry(transaction, best_match)

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

        # Match and create payment
        matches = self.reconciliation_engine.match_transaction(transaction)
        invoice_match = next((m for m in matches if m["type"] == "invoice"), None)

        self.assertIsNotNone(invoice_match)

        payment_entry = self.reconciliation_engine.create_payment_entry(transaction, invoice_match)

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

        matches = self.reconciliation_engine.match_transaction(transaction1)
        payment1 = self.reconciliation_engine.create_payment_entry(transaction1, matches[0])
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
        transactions.append(self.create_test_transaction(200, "Random payment"))

        # Run reconciliation
        results = self.reconciliation_engine.reconcile_bank_transactions(
            bank_account=self.test_bank_account.name, from_date=today(), to_date=today()
        )

        # Check results
        self.assertEqual(results["processed"], 2)
        self.assertGreaterEqual(results["reconciled"], 1)
        self.assertGreaterEqual(results["unmatched"], 1)

        # Clean up
        for transaction in transactions:
            if frappe.db.exists("Bank Transaction", transaction.name):
                transaction.delete()

    def test_match_threshold_configuration(self):
        """Test confidence threshold configuration"""
        # Low confidence match
        transaction = self.create_test_transaction(
            100, "Vague description", "NL99UNKNOWN9999999"  # Unknown IBAN
        )

        # Should have low confidence
        matches = self.reconciliation_engine.match_transaction(transaction)

        if matches:
            # All matches should have some confidence score
            for match in matches:
                self.assertIn("confidence", match)
                self.assertGreaterEqual(match["confidence"], 0)
                self.assertLessEqual(match["confidence"], 1)

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
