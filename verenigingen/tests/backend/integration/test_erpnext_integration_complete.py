# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Complete ERPNext Integration Tests
Tests for all ERPNext integration points including accounting, inventory, and projects
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, add_months, flt, nowdate
from decimal import Decimal
import json


class TestERPNextIntegrationComplete(FrappeTestCase):
    """Test complete ERPNext integration"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        
        # Ensure test company exists
        cls.company = cls._ensure_test_company()
        
        # Create test accounts
        cls.test_accounts = cls._create_test_accounts()
        
        # Create test cost centers
        cls.cost_centers = cls._create_test_cost_centers()
        
        # Create test member and volunteer
        cls.test_member = cls._create_test_member()
        cls.test_volunteer = cls._create_test_volunteer()
        
    @classmethod
    def _ensure_test_company(cls):
        """Ensure test company exists"""
        company_name = "Test Association ERPNext"
        
        if not frappe.db.exists("Company", company_name):
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "country": "Netherlands",
                "default_currency": "EUR",
                "create_chart_of_accounts_based_on": "Standard Template",
                "chart_of_accounts": "Standard"
            })
            company.insert()
            return company
        return frappe.get_doc("Company", company_name)
        
    @classmethod
    def _create_test_accounts(cls):
        """Create test accounts for integration"""
        accounts = {}
        
        # Get or create required accounts
        account_types = {
            "membership_income": {
                "account_name": "Membership Income",
                "parent_account": f"Income - {cls.company.abbr}",
                "account_type": "Income Account"
            },
            "donation_income": {
                "account_name": "Donation Income",
                "parent_account": f"Income - {cls.company.abbr}",
                "account_type": "Income Account"
            },
            "expense_reimbursement": {
                "account_name": "Volunteer Expense Reimbursement",
                "parent_account": f"Expenses - {cls.company.abbr}",
                "account_type": "Expense Account"
            }
        }
        
        for key, account_data in account_types.items():
            account_name = f"{account_data['account_name']} - {cls.company.abbr}"
            
            if not frappe.db.exists("Account", account_name):
                account = frappe.get_doc({
                    "doctype": "Account",
                    "account_name": account_data["account_name"],
                    "parent_account": account_data["parent_account"],
                    "account_type": account_data["account_type"],
                    "company": cls.company.name
                })
                account.insert()
                accounts[key] = account.name
            else:
                accounts[key] = account_name
                
        return accounts
        
    @classmethod
    def _create_test_cost_centers(cls):
        """Create test cost centers"""
        cost_centers = {}
        
        # Main cost center
        main_cc = f"Main - {cls.company.abbr}"
        if not frappe.db.exists("Cost Center", main_cc):
            cc = frappe.get_doc({
                "doctype": "Cost Center",
                "cost_center_name": "Main",
                "company": cls.company.name,
                "is_group": 0
            })
            cc.insert()
            
        cost_centers["main"] = main_cc
        
        # Chapter cost center
        chapter_cc = f"Amsterdam Chapter - {cls.company.abbr}"
        if not frappe.db.exists("Cost Center", chapter_cc):
            cc = frappe.get_doc({
                "doctype": "Cost Center",
                "cost_center_name": "Amsterdam Chapter",
                "company": cls.company.name,
                "parent_cost_center": main_cc,
                "is_group": 0
            })
            cc.insert()
            
        cost_centers["chapter"] = chapter_cc
        
        return cost_centers
        
    @classmethod
    def _create_test_member(cls):
        """Create test member"""
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "ERPNext",
            "last_name": "TestMember",
            "email": f"erpnext.test.{frappe.utils.random_string(6)}@example.com",
            "phone": "+31612345678",
            "status": "Active"
        })
        member.insert()
        
        # Create customer
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": member.full_name,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        })
        customer.insert()
        
        member.customer = customer.name
        member.save()
        
        return member
        
    @classmethod
    def _create_test_volunteer(cls):
        """Create test volunteer"""
        volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": cls.test_member.full_name,
            "email": cls.test_member.email,
            "member": cls.test_member.name,
            "status": "Active"
        })
        volunteer.insert()
        return volunteer
        
    def test_sales_invoice_creation_flow(self):
        """Test complete sales invoice creation flow"""
        # Create membership invoice
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "due_date": add_days(today(), 30),
            "items": [{
                "item_code": self._get_or_create_membership_item(),
                "description": "Annual Membership Fee",
                "qty": 1,
                "rate": 100.00,
                "income_account": self.test_accounts["membership_income"]
            }],
            "cost_center": self.cost_centers["main"]
        })
        
        invoice.insert()
        invoice.submit()
        
        # Verify invoice
        self.assertEqual(invoice.docstatus, 1)  # Submitted
        self.assertEqual(invoice.grand_total, 100.00)
        self.assertEqual(invoice.outstanding_amount, 100.00)
        
        # Link to member
        if hasattr(self.test_member, 'invoices'):
            self.test_member.append("invoices", {
                "invoice": invoice.name,
                "amount": invoice.grand_total,
                "status": invoice.status
            })
            self.test_member.save()
            
    def _get_or_create_membership_item(self):
        """Get or create membership item"""
        item_code = "MEMBERSHIP-ANNUAL"
        
        if not frappe.db.exists("Item", item_code):
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": "Annual Membership",
                "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_sales_item": 1,
                "is_service_item": 1
            })
            item.insert()
            
        return item_code
        
    def test_payment_entry_reconciliation(self):
        """Test payment entry and reconciliation"""
        # First create an invoice
        invoice = self._create_test_invoice(150.00)
        
        # Create payment entry
        payment = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "paid_amount": 150.00,
            "received_amount": 150.00,
            "paid_from": frappe.db.get_value("Account", 
                                            {"account_type": "Receivable", "company": self.company.name}, 
                                            "name"),
            "paid_to": frappe.db.get_value("Account", 
                                         {"account_type": "Bank", "company": self.company.name}, 
                                         "name"),
            "reference_no": f"PAY-{frappe.utils.random_string(6)}",
            "reference_date": today(),
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "allocated_amount": 150.00
            }]
        })
        
        payment.insert()
        payment.submit()
        
        # Verify payment
        self.assertEqual(payment.docstatus, 1)
        self.assertEqual(payment.paid_amount, 150.00)
        
        # Verify invoice is paid
        invoice.reload()
        self.assertEqual(invoice.outstanding_amount, 0)
        self.assertEqual(invoice.status, "Paid")
        
    def _create_test_invoice(self, amount):
        """Helper to create test invoice"""
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "items": [{
                "item_code": self._get_or_create_membership_item(),
                "qty": 1,
                "rate": amount,
                "income_account": self.test_accounts["membership_income"]
            }]
        })
        invoice.insert()
        invoice.submit()
        return invoice
        
    def test_journal_entry_workflows(self):
        """Test journal entry creation for various scenarios"""
        # Test donation recording
        donation_je = frappe.get_doc({
            "doctype": "Journal Entry",
            "company": self.company.name,
            "posting_date": today(),
            "accounts": [
                {
                    "account": frappe.db.get_value("Account", 
                                                 {"account_type": "Bank", "company": self.company.name}, 
                                                 "name"),
                    "debit_in_account_currency": 500.00,
                    "cost_center": self.cost_centers["main"]
                },
                {
                    "account": self.test_accounts["donation_income"],
                    "credit_in_account_currency": 500.00,
                    "cost_center": self.cost_centers["main"],
                    "party_type": "Customer",
                    "party": self.test_member.customer
                }
            ],
            "user_remark": f"Donation from {self.test_member.full_name}"
        })
        
        donation_je.insert()
        donation_je.submit()
        
        # Verify journal entry
        self.assertEqual(donation_je.docstatus, 1)
        self.assertEqual(donation_je.total_debit, 500.00)
        self.assertEqual(donation_je.total_credit, 500.00)
        
    def test_multi_currency_handling(self):
        """Test multi-currency transactions"""
        # Create invoice in USD
        usd_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "currency": "USD",
            "conversion_rate": 0.85,  # 1 USD = 0.85 EUR
            "posting_date": today(),
            "items": [{
                "item_code": self._get_or_create_membership_item(),
                "qty": 1,
                "rate": 100.00,  # 100 USD
                "income_account": self.test_accounts["membership_income"]
            }]
        })
        
        usd_invoice.insert()
        
        # Verify conversion
        self.assertEqual(usd_invoice.grand_total, 100.00)  # In USD
        self.assertEqual(usd_invoice.base_grand_total, 85.00)  # In EUR
        
    def test_fiscal_year_transitions(self):
        """Test handling of fiscal year transitions"""
        # Get current fiscal year
        current_fy = frappe.db.get_value("Fiscal Year", 
                                       {"year_start_date": ["<=", today()], 
                                        "year_end_date": [">=", today()]}, 
                                       "name")
        
        self.assertIsNotNone(current_fy)
        
        # Test period closing entries
        # Would normally test year-end closing but simplified for unit test
        fiscal_year_doc = frappe.get_doc("Fiscal Year", current_fy)
        
        self.assertIsNotNone(fiscal_year_doc.year_start_date)
        self.assertIsNotNone(fiscal_year_doc.year_end_date)
        
    def test_expense_claim_integration(self):
        """Test volunteer expense to expense claim integration"""
        # Create volunteer expense
        expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "expense_date": today(),
            "amount": 75.50,
            "description": "Travel expenses for event",
            "status": "Approved",
            "organization_type": "Association",
            "category": self._get_or_create_expense_category()
        })
        expense.insert()
        
        # Create expense claim from volunteer expense
        if frappe.db.exists("DocType", "Expense Claim"):
            expense_claim = frappe.get_doc({
                "doctype": "Expense Claim",
                "employee": self._get_or_create_volunteer_employee(),
                "expense_approver": frappe.session.user,
                "posting_date": today(),
                "company": self.company.name,
                "expenses": [{
                    "expense_date": expense.expense_date,
                    "expense_type": "Travel",
                    "description": expense.description,
                    "amount": expense.amount,
                    "sanctioned_amount": expense.amount,
                    "cost_center": self.cost_centers["main"]
                }]
            })
            
            expense_claim.insert()
            expense_claim.submit()
            
            # Verify expense claim
            self.assertEqual(expense_claim.total_claimed_amount, 75.50)
            self.assertEqual(expense_claim.total_sanctioned_amount, 75.50)
            
    def _get_or_create_expense_category(self):
        """Get or create expense category"""
        category_name = "Event Expenses"
        
        if not frappe.db.exists("Expense Category", category_name):
            category = frappe.get_doc({
                "doctype": "Expense Category",
                "category_name": category_name,
                "expense_account": self.test_accounts["expense_reimbursement"]
            })
            category.insert()
            
        return category_name
        
    def _get_or_create_volunteer_employee(self):
        """Get or create employee for volunteer"""
        employee_name = f"VOL-{self.test_volunteer.name}"
        
        if not frappe.db.exists("Employee", employee_name):
            employee = frappe.get_doc({
                "doctype": "Employee",
                "employee_name": self.test_volunteer.volunteer_name,
                "first_name": "Volunteer",
                "last_name": self.test_member.last_name,
                "company": self.company.name,
                "date_of_joining": today(),
                "status": "Active"
            })
            employee.insert()
            return employee.name
            
        return employee_name
        
    def test_project_tracking_integration(self):
        """Test project-based tracking for events and campaigns"""
        # Create project for an event
        project = frappe.get_doc({
            "doctype": "Project",
            "project_name": f"Annual Gala {frappe.utils.random_string(4)}",
            "company": self.company.name,
            "expected_start_date": today(),
            "expected_end_date": add_days(today(), 30),
            "status": "Open",
            "project_type": "External"
        })
        project.insert()
        
        # Link transactions to project
        # Create invoice with project
        project_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "project": project.name,
            "posting_date": today(),
            "items": [{
                "item_code": self._get_or_create_event_ticket_item(),
                "qty": 2,
                "rate": 50.00,
                "income_account": self.test_accounts["donation_income"]
            }]
        })
        project_invoice.insert()
        
        # Verify project linking
        self.assertEqual(project_invoice.project, project.name)
        
        # Check project profitability
        income = frappe.db.sql("""
            SELECT SUM(grand_total) 
            FROM `tabSales Invoice` 
            WHERE project = %s AND docstatus = 1
        """, project.name)[0][0] or 0
        
        self.assertEqual(income, 0)  # Not submitted yet
        
    def _get_or_create_event_ticket_item(self):
        """Get or create event ticket item"""
        item_code = "EVENT-TICKET"
        
        if not frappe.db.exists("Item", item_code):
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": "Event Ticket",
                "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_sales_item": 1
            })
            item.insert()
            
        return item_code
        
    def test_tax_handling(self):
        """Test Dutch tax (BTW) handling"""
        # Create tax template
        tax_template = self._get_or_create_tax_template()
        
        # Create invoice with tax
        tax_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "taxes_and_charges": tax_template,
            "items": [{
                "item_code": self._get_or_create_membership_item(),
                "qty": 1,
                "rate": 100.00,
                "income_account": self.test_accounts["membership_income"]
            }]
        })
        
        tax_invoice.insert()
        
        # Verify tax calculation (21% BTW)
        self.assertEqual(tax_invoice.total, 100.00)
        self.assertAlmostEqual(tax_invoice.total_taxes_and_charges, 21.00, places=2)
        self.assertAlmostEqual(tax_invoice.grand_total, 121.00, places=2)
        
    def _get_or_create_tax_template(self):
        """Get or create tax template"""
        template_name = f"BTW 21% - {self.company.abbr}"
        
        if not frappe.db.exists("Sales Taxes and Charges Template", template_name):
            # Create tax account first
            tax_account = f"BTW 21% - {self.company.abbr}"
            if not frappe.db.exists("Account", tax_account):
                account = frappe.get_doc({
                    "doctype": "Account",
                    "account_name": "BTW 21%",
                    "parent_account": f"Duties and Taxes - {self.company.abbr}",
                    "account_type": "Tax",
                    "company": self.company.name
                })
                account.insert()
                
            # Create template
            template = frappe.get_doc({
                "doctype": "Sales Taxes and Charges Template",
                "title": template_name,
                "company": self.company.name,
                "taxes": [{
                    "charge_type": "On Net Total",
                    "account_head": tax_account,
                    "description": "BTW 21%",
                    "rate": 21
                }]
            })
            template.insert()
            
        return template_name
        
    def test_accounting_dimensions(self):
        """Test accounting dimensions (cost center, project, etc.)"""
        # Create invoice with multiple dimensions
        dimensional_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "cost_center": self.cost_centers["chapter"],
            "items": [{
                "item_code": self._get_or_create_membership_item(),
                "qty": 1,
                "rate": 200.00,
                "income_account": self.test_accounts["membership_income"],
                "cost_center": self.cost_centers["chapter"]
            }]
        })
        
        dimensional_invoice.insert()
        
        # Verify dimensions are set
        self.assertEqual(dimensional_invoice.cost_center, self.cost_centers["chapter"])
        self.assertEqual(dimensional_invoice.items[0].cost_center, self.cost_centers["chapter"])
        
    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up in reverse order of dependencies
        try:
            # Delete transactions first
            for doctype in ["Payment Entry", "Sales Invoice", "Journal Entry", "Expense Claim"]:
                test_docs = frappe.get_all(doctype, 
                                         filters={"company": cls.company.name},
                                         pluck="name")
                for doc in test_docs:
                    try:
                        doc_obj = frappe.get_doc(doctype, doc)
                        if doc_obj.docstatus == 1:
                            doc_obj.cancel()
                        frappe.delete_doc(doctype, doc, force=True)
                    except:
                        pass
                        
            # Delete master data
            frappe.delete_doc("Volunteer", cls.test_volunteer.name, force=True)
            frappe.delete_doc("Customer", cls.test_member.customer, force=True)
            frappe.delete_doc("Member", cls.test_member.name, force=True)
            
        except:
            pass
            
        super().tearDownClass()