"""
ERPNext Integration Comprehensive Tests
Complete validation of ERPNext integration including multi-organization accounting,
VAT/BTW compliance, chart of accounts synchronization, and GL Entry validation
"""

import frappe
from frappe.utils import today, add_days, add_months, flt, nowdate
from verenigingen.tests.utils.base import VereningingenTestCase
from decimal import Decimal
import json


class TestERPNextIntegrationComprehensive(VereningingenTestCase):
    """Comprehensive ERPNext integration testing covering complete accounting workflows"""

    def setUp(self):
        """Set up test data for ERPNext integration tests"""
        super().setUp()

        # Create test organizations
        self.company_main = self._ensure_test_company("Test Company Main", "EUR")
        self.company_branch = self._ensure_test_company("Test Company Branch", "EUR")

        # Create test chapters for multi-organization testing
        self.chapter_main = self.factory.create_test_chapter(
            chapter_name="Main Chapter",
            organization=self.company_main
        )

        self.chapter_branch = self.factory.create_test_chapter(
            chapter_name="Branch Chapter",
            organization=self.company_branch
        )

        # Create membership types for different organizations
        self.membership_main = self.factory.create_test_membership_type(
            membership_type_name="Main Membership",
            minimum_amount=50.00,
            billing_period="Annual",
            company=self.company_main
        )

        self.membership_branch = self.factory.create_test_membership_type(
            membership_type_name="Branch Membership",
            minimum_amount=30.00,
            billing_period="Monthly",
            company=self.company_branch
        )

    def _ensure_test_company(self, company_name, currency="EUR"):
        """Ensure test company exists with proper setup"""
        if not frappe.db.exists("Company", company_name):
            company = frappe.new_doc("Company")
            company.company_name = company_name
            company.default_currency = currency
            company.country = "Netherlands"
            company.save()
            self.track_doc("Company", company.name)
            return company.name
        return company_name

    def test_multi_organization_accounting_isolation(self):
        """Test that accounting data is properly isolated between organizations"""
        # Create members in different organizations
        member_main = self.factory.create_test_member(
            first_name="Main",
            last_name="Member",
            email=f"main.member.{self.factory.test_run_id}@example.com",
            company=self.company_main
        )

        member_branch = self.factory.create_test_member(
            first_name="Branch",
            last_name="Member",
            email=f"branch.member.{self.factory.test_run_id}@example.com",
            company=self.company_branch
        )

        # Create memberships in different organizations
        membership_main = self.factory.create_test_membership(
            member=member_main.name,
            membership_type=self.membership_main.name
        )

        membership_branch = self.factory.create_test_membership(
            member=member_branch.name,
            membership_type=self.membership_branch.name
        )

        # Create invoices for both members
        invoice_main = self.factory.create_test_sales_invoice(
            customer=member_main.customer,
            company=self.company_main,
            is_membership_invoice=1,
            membership=membership_main.name
        )

        invoice_branch = self.factory.create_test_sales_invoice(
            customer=member_branch.customer,
            company=self.company_branch,
            is_membership_invoice=1,
            membership=membership_branch.name
        )

        # Submit invoices to generate GL Entries
        invoice_main.submit()
        invoice_branch.submit()

        # Verify GL Entries are company-specific
        gl_entries_main = frappe.get_all(
            "GL Entry",
            filters={
                "voucher_no": invoice_main.name,
                "company": self.company_main
            },
            fields=["account", "debit", "credit", "company"]
        )

        gl_entries_branch = frappe.get_all(
            "GL Entry",
            filters={
                "voucher_no": invoice_branch.name,
                "company": self.company_branch
            },
            fields=["account", "debit", "credit", "company"]
        )

        # Assertions for proper isolation
        self.assertGreater(len(gl_entries_main), 0, "Main company should have GL entries")
        self.assertGreater(len(gl_entries_branch), 0, "Branch company should have GL entries")

        # Verify no cross-company contamination
        for entry in gl_entries_main:
            self.assertEqual(entry.company, self.company_main)

        for entry in gl_entries_branch:
            self.assertEqual(entry.company, self.company_branch)

        # Verify accounts are company-specific
        main_accounts = set(entry.account for entry in gl_entries_main)
        branch_accounts = set(entry.account for entry in gl_entries_branch)

        # Accounts should be different (company-specific)
        self.assertTrue(main_accounts.isdisjoint(branch_accounts) or
                       any(self.company_main in acc for acc in main_accounts))

    def test_vat_btw_compliance_automation(self):
        """Test automated Dutch VAT/BTW compliance across transaction types"""
        # Create member for VAT testing
        member = self.factory.create_test_member(
            first_name="VAT",
            last_name="Compliance",
            email=f"vat.compliance.{self.factory.test_run_id}@example.com"
        )

        # Test scenario data with different VAT rates
        test_scenarios = [
            {
                "description": "Membership Fee (VAT Exempt)",
                "item_name": "Annual Membership",
                "rate": 60.00,
                "vat_rate": 0,
                "account": self._get_or_create_account("Membership Income", self.company_main),
                "expected_vat": 0.00
            },
            {
                "description": "Merchandise (21% VAT)",
                "item_name": "Association T-Shirt",
                "rate": 25.00,
                "vat_rate": 21,
                "account": self._get_or_create_account("Merchandise Sales", self.company_main),
                "expected_vat": 5.25
            },
            {
                "description": "Educational Material (9% VAT)",
                "item_name": "Vegan Cookbook",
                "rate": 30.00,
                "vat_rate": 9,
                "account": self._get_or_create_account("Educational Sales", self.company_main),
                "expected_vat": 2.70
            },
            {
                "description": "Food/Beverages (9% VAT)",
                "item_name": "Event Catering",
                "rate": 50.00,
                "vat_rate": 9,
                "account": self._get_or_create_account("Catering Income", self.company_main),
                "expected_vat": 4.50
            }
        ]

        vat_summary = {
            "period": today().strftime("%B %Y"),
            "total_exempt": 0,
            "total_21_percent": 0,
            "total_9_percent": 0,
            "vat_21_collected": 0,
            "vat_9_collected": 0
        }

        # Process each VAT scenario
        for scenario in test_scenarios:
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer
            invoice.company = self.company_main
            invoice.posting_date = today()

            # Add item
            invoice.append("items", {
                "item_name": scenario["item_name"],
                "description": scenario["description"],
                "qty": 1,
                "rate": scenario["rate"],
                "income_account": scenario["account"]
            })

            # Add VAT if applicable
            if scenario["vat_rate"] > 0:
                vat_account = self._get_or_create_vat_account(scenario["vat_rate"], self.company_main)
                invoice.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": vat_account,
                    "rate": scenario["vat_rate"],
                    "description": f"BTW {scenario['vat_rate']}%"
                })

            invoice.save()
            self.track_doc("Sales Invoice", invoice.name)

            # Verify VAT calculation
            actual_vat = flt(invoice.total_taxes_and_charges, 2)
            self.assertEqual(actual_vat, scenario["expected_vat"],
                           f"VAT calculation incorrect for {scenario['description']}")

            # Update summary
            if scenario["vat_rate"] == 0:
                vat_summary["total_exempt"] += scenario["rate"]
            elif scenario["vat_rate"] == 21:
                vat_summary["total_21_percent"] += scenario["rate"]
                vat_summary["vat_21_collected"] += actual_vat
            elif scenario["vat_rate"] == 9:
                vat_summary["total_9_percent"] += scenario["rate"]
                vat_summary["vat_9_collected"] += actual_vat

        # Verify summary totals
        self.assertEqual(vat_summary["total_exempt"], 60.00)
        self.assertEqual(vat_summary["total_21_percent"], 25.00)
        self.assertEqual(vat_summary["total_9_percent"], 80.00)  # 30 + 50
        self.assertEqual(vat_summary["vat_21_collected"], 5.25)
        self.assertEqual(vat_summary["vat_9_collected"], 7.20)  # 2.70 + 4.50

        # Verify total VAT collected
        total_vat = vat_summary["vat_21_collected"] + vat_summary["vat_9_collected"]
        self.assertEqual(total_vat, 12.45)

    def test_chart_of_accounts_synchronization(self):
        """Test synchronization and consistency of chart of accounts across companies"""
        # Define standard account structure for verenigingen
        standard_accounts = [
            {"name": "Assets", "type": "Asset", "is_group": 1},
            {"name": "Current Assets", "type": "Asset", "is_group": 1, "parent": "Assets"},
            {"name": "Bank Accounts", "type": "Bank", "is_group": 1, "parent": "Current Assets"},
            {"name": "Receivables", "type": "Receivable", "is_group": 1, "parent": "Current Assets"},

            {"name": "Liabilities", "type": "Liability", "is_group": 1},
            {"name": "Current Liabilities", "type": "Liability", "is_group": 1, "parent": "Liabilities"},
            {"name": "VAT Payable", "type": "Tax", "is_group": 1, "parent": "Current Liabilities"},

            {"name": "Income", "type": "Income", "is_group": 1},
            {"name": "Membership Income", "type": "Income", "is_group": 0, "parent": "Income"},
            {"name": "Donation Income", "type": "Income", "is_group": 0, "parent": "Income"},

            {"name": "Expenses", "type": "Expense", "is_group": 1},
            {"name": "Operating Expenses", "type": "Expense", "is_group": 1, "parent": "Expenses"}
        ]

        # Create accounts for both companies
        created_accounts = {"main": [], "branch": []}

        for company_key, company_name in [("main", self.company_main), ("branch", self.company_branch)]:
            for account_def in standard_accounts:
                account = self._create_test_account(account_def, company_name)
                created_accounts[company_key].append(account)

        # Verify account structure consistency
        for account_def in standard_accounts:
            main_account = next((acc for acc in created_accounts["main"]
                               if acc.account_name == account_def["name"]), None)
            branch_account = next((acc for acc in created_accounts["branch"]
                                 if acc.account_name == account_def["name"]), None)

            self.assertIsNotNone(main_account, f"Main company missing {account_def['name']}")
            self.assertIsNotNone(branch_account, f"Branch company missing {account_def['name']}")

            # Verify account properties match
            self.assertEqual(main_account.account_type, branch_account.account_type)
            self.assertEqual(main_account.is_group, branch_account.is_group)

            # Companies should be different
            self.assertNotEqual(main_account.company, branch_account.company)

        # Test account hierarchy consistency
        main_membership = next((acc for acc in created_accounts["main"]
                              if acc.account_name == "Membership Income"), None)
        branch_membership = next((acc for acc in created_accounts["branch"]
                                if acc.account_name == "Membership Income"), None)

        # Both should have Income as parent (with company suffix)
        self.assertIn("Income", main_membership.parent_account)
        self.assertIn("Income", branch_membership.parent_account)

    def test_gl_entry_validation_comprehensive(self):
        """Test comprehensive GL Entry validation across all transaction types"""
        # Create test member and membership
        member = self.factory.create_test_member(
            first_name="GL",
            last_name="Test",
            email=f"gl.test.{self.factory.test_run_id}@example.com"
        )

        self.factory.create_test_membership(
            member=member.name,
            membership_type=self.membership_main.name
        )

        # Test Case 1: Sales Invoice GL Entries
        invoice = self.factory.create_test_sales_invoice(
            customer=member.customer,
            company=self.company_main
        )

        # Add custom item with specific accounts
        self._get_or_create_receivable_account(self.company_main)
        income_account = self._get_or_create_account("Test Income", self.company_main)

        invoice.items[0].income_account = income_account
        invoice.save()
        invoice.submit()

        # Verify GL entries for Sales Invoice
        gl_entries = frappe.get_all(
            "GL Entry",
            filters={"voucher_no": invoice.name},
            fields=["account", "debit", "credit", "party", "party_type"],
            order_by="debit desc"
        )

        self.assertEqual(len(gl_entries), 2, "Sales Invoice should create 2 GL entries")

        # Verify debit entry (Receivable)
        debit_entry = gl_entries[0]
        self.assertGreater(debit_entry.debit, 0)
        self.assertEqual(debit_entry.credit, 0)
        self.assertEqual(debit_entry.party_type, "Customer")
        self.assertEqual(debit_entry.party, member.customer)

        # Verify credit entry (Income)
        credit_entry = gl_entries[1]
        self.assertEqual(credit_entry.debit, 0)
        self.assertGreater(credit_entry.credit, 0)
        self.assertEqual(credit_entry.account, income_account)

        # Verify accounting equation balance
        total_debits = sum(entry.debit for entry in gl_entries)
        total_credits = sum(entry.credit for entry in gl_entries)
        self.assertEqual(total_debits, total_credits, "Debits should equal credits")

        # Test Case 2: Payment Entry GL Entries
        payment = self.factory.create_test_payment_entry(
            party=member.customer,
            party_type="Customer",
            paid_amount=invoice.grand_total,
            company=self.company_main
        )

        # Link payment to invoice
        payment.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": invoice.grand_total
        })

        payment.save()
        payment.submit()

        # Verify Payment Entry GL entries
        payment_gl_entries = frappe.get_all(
            "GL Entry",
            filters={"voucher_no": payment.name},
            fields=["account", "debit", "credit", "party", "party_type"]
        )

        self.assertEqual(len(payment_gl_entries), 2, "Payment Entry should create 2 GL entries")

        # Verify accounting equation for payment
        payment_debits = sum(entry.debit for entry in payment_gl_entries)
        payment_credits = sum(entry.credit for entry in payment_gl_entries)
        self.assertEqual(payment_debits, payment_credits, "Payment debits should equal credits")

        # Test Case 3: Period totals validation
        # Get all GL entries for the company in current month
        month_start = today().replace(day=1)
        month_gl_entries = frappe.get_all(
            "GL Entry",
            filters={
                "company": self.company_main,
                "posting_date": [">=", month_start]
            },
            fields=["debit", "credit"]
        )

        month_total_debits = sum(entry.debit for entry in month_gl_entries)
        month_total_credits = sum(entry.credit for entry in month_gl_entries)

        self.assertEqual(month_total_debits, month_total_credits,
                        "Monthly totals: debits should equal credits")

    def test_financial_report_integration(self):
        """Test integration with ERPNext financial reports"""
        # Create test transactions for report validation
        member = self.factory.create_test_member(
            first_name="Report",
            last_name="Test",
            email=f"report.test.{self.factory.test_run_id}@example.com"
        )

        # Create multiple transaction types
        transactions = []

        # Membership invoice
        membership_invoice = self.factory.create_test_sales_invoice(
            customer=member.customer,
            company=self.company_main,
            items=[{
                "item_name": "Membership Fee",
                "rate": 50.00,
                "income_account": self._get_or_create_account("Membership Income", self.company_main)
            }]
        )
        membership_invoice.submit()
        transactions.append(membership_invoice)

        # Donation invoice
        donation_invoice = self.factory.create_test_sales_invoice(
            customer=member.customer,
            company=self.company_main,
            items=[{
                "item_name": "General Donation",
                "rate": 100.00,
                "income_account": self._get_or_create_account("Donation Income", self.company_main)
            }]
        )
        donation_invoice.submit()
        transactions.append(donation_invoice)

        # Expense (Journal Entry)
        expense_account = self._get_or_create_account("Program Expenses", self.company_main)
        cash_account = self._get_or_create_account("Cash", self.company_main)

        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.company = self.company_main
        journal_entry.posting_date = today()
        journal_entry.voucher_type = "Journal Entry"

        journal_entry.append("accounts", {
            "account": expense_account,
            "debit_in_account_currency": 75.00,
            "credit_in_account_currency": 0
        })

        journal_entry.append("accounts", {
            "account": cash_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": 75.00
        })

        journal_entry.save()
        self.track_doc("Journal Entry", journal_entry.name)
        journal_entry.submit()

        # Test Financial Statement Integration
        # Verify Profit & Loss shows correct income
        income_accounts = frappe.get_all(
            "GL Entry",
            filters={
                "company": self.company_main,
                "posting_date": today(),
                "account": ["in", [
                    self._get_or_create_account("Membership Income", self.company_main),
                    self._get_or_create_account("Donation Income", self.company_main)
                ]]
            },
            fields=["account", "credit"],
            group_by="account"
        )

        total_income = sum(entry.credit for entry in income_accounts)
        self.assertEqual(total_income, 150.00, "Total income should be 150.00")

        # Verify Balance Sheet shows correct receivables
        receivable_balance = frappe.db.sql("""
            SELECT SUM(debit - credit) as balance
            FROM `tabGL Entry`
            WHERE company = %s
            AND account LIKE '%%Receivable%%'
            AND posting_date <= %s
        """, (self.company_main, today()), as_dict=True)[0]

        expected_receivable = membership_invoice.grand_total + donation_invoice.grand_total
        self.assertEqual(receivable_balance.balance, expected_receivable,
                        "Receivable balance should match invoice totals")

    def _create_test_account(self, account_def, company):
        """Create a test account with proper structure"""
        account_name_with_company = f"{account_def['name']} - {company}"

        if frappe.db.exists("Account", account_name_with_company):
            return frappe.get_doc("Account", account_name_with_company)

        account = frappe.new_doc("Account")
        account.account_name = account_def["name"]
        account.company = company
        account.account_type = account_def.get("type")
        account.is_group = account_def.get("is_group", 0)

        # Set root type based on account type
        root_type_mapping = {
            "Asset": "Asset",
            "Liability": "Liability",
            "Income": "Income",
            "Expense": "Expense",
            "Bank": "Asset",
            "Receivable": "Asset",
            "Tax": "Liability"
        }
        account.root_type = root_type_mapping.get(account_def.get("type"), "Asset")

        # Set parent if specified
        if account_def.get("parent"):
            parent_name = f"{account_def['parent']} - {company}"
            if frappe.db.exists("Account", parent_name):
                account.parent_account = parent_name

        account.save()
        self.track_doc("Account", account.name)
        return account

    def _get_or_create_account(self, account_name, company):
        """Get or create account with company suffix"""
        account_full_name = f"{account_name} - {company}"

        if frappe.db.exists("Account", account_full_name):
            return account_full_name

        # Create basic account
        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company
        account.account_type = "Income Account"  # Default to income
        account.root_type = "Income"
        account.is_group = 0
        account.save()
        self.track_doc("Account", account.name)
        return account.name

    def _get_or_create_vat_account(self, vat_rate, company):
        """Get or create VAT account for specific rate"""
        if vat_rate == 21:
            account_name = f"BTW 21% - {company}"
        elif vat_rate == 9:
            account_name = f"BTW 9% - {company}"
        else:
            account_name = f"BTW {vat_rate}% - {company}"

        if frappe.db.exists("Account", account_name):
            return account_name

        account = frappe.new_doc("Account")
        account.account_name = account_name.replace(f" - {company}", "")
        account.company = company
        account.account_type = "Tax"
        account.root_type = "Liability"
        account.is_group = 0
        account.save()
        self.track_doc("Account", account.name)
        return account.name

    def _get_or_create_receivable_account(self, company):
        """Get or create receivable account"""
        account_name = f"Accounts Receivable - {company}"

        if frappe.db.exists("Account", account_name):
            return account_name

        account = frappe.new_doc("Account")
        account.account_name = "Accounts Receivable"
        account.company = company
        account.account_type = "Receivable"
        account.root_type = "Asset"
        account.is_group = 0
        account.save()
        self.track_doc("Account", account.name)
        return account.name


def run_erpnext_integration_tests():
    """Run ERPNext integration comprehensive tests"""
    print("🏢 Running ERPNext Integration Comprehensive Tests...")

    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestERPNextIntegrationComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All ERPNext integration tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_erpnext_integration_tests()
