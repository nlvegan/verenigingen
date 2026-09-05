# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Complete ERPNext Integration Tests
Tests for all ERPNext integration points including accounting, inventory, and projects
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from frappe.utils import today, add_days, add_months, flt, nowdate
from decimal import Decimal
import json


class TestERPNextIntegrationComplete(EnhancedTestCase):
    """Test complete ERPNext integration"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        
        # Ensure test company exists
        cls.company = cls._ensure_test_company()

        # Pin the document currency to the company's own. Left unset, a Sales
        # Invoice takes its currency from the customer / the site's default price
        # list -- which on a CI site is INR from the ERPNext fixtures -- while the
        # party account (Debtors - TPIC) is EUR, and ERPNext rejects the pair:
        # "Party Account Debtors - TPIC currency (EUR) and document currency (INR)
        # should be same".
        #
        # This was previously invisible because the company was BORROWED: on a
        # fresh shard the old lookup fell through to `get_all("Company", limit=1)`,
        # which returns the OLDEST company (_Test Company, INR), so an INR invoice
        # under an INR company happened to agree. Owning a EUR company makes the
        # currency an explicit decision rather than a coincidence.
        cls.currency = frappe.db.get_value("Company", cls.company.name, "default_currency")
        
        # Create test accounts
        cls.test_accounts = cls._create_test_accounts()
        
        # Create test cost centers
        cls.cost_centers = cls._create_test_cost_centers()
        
        # Ensure a selling price list in the company currency exists. ERPNext
        # v16 makes selling_price_list / price_list_currency / plc_conversion_rate
        # mandatory on Sales Invoice; without a matching price list the framework
        # cannot derive them and insert() raises MandatoryError.
        cls.selling_price_list = cls._ensure_own_selling_price_list()

        # Create test member and volunteer
        cls.test_member = cls._create_test_member()
        cls.test_volunteer = cls._create_test_volunteer()

    @classmethod
    def _ensure_own_selling_price_list(cls):
        """Ensure a selling Price List in the company's currency exists.

        Renamed from `_ensure_selling_price_list` (#496): that name shadows
        `EnhancedTestCase._ensure_selling_price_list(currency="EUR")`, which
        `create_test_sales_invoice()` calls internally as
        `self._ensure_selling_price_list(company_currency)`. This classmethod
        takes no arguments, so that call would raise TypeError ("too many
        positional arguments") -- latent because this class never calls
        `create_test_sales_invoice()` today.
        """
        currency = frappe.db.get_value("Company", cls.company.name, "default_currency") or "EUR"

        # Named, not queried. Asking for "any enabled selling price list in this
        # currency" is the same borrow as the company one directly above: it
        # answers with whatever another test left behind, and a neighbour that
        # disables or reprices that list changes this class's results. The list
        # below is created here if absent, so it is this class's own.
        price_list_name = f"Test Selling {currency}"
        if not frappe.db.exists("Price List", price_list_name):
            frappe.get_doc(
                {
                    "doctype": "Price List",
                    "price_list_name": price_list_name,
                    "selling": 1,
                    "enabled": 1,
                    "currency": currency,
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()
        return price_list_name

    @classmethod
    def _ensure_test_company(cls):
        """Return the app's own EUR test company. Never borrows another test's.

        This used to walk a hardcoded preference list ("Test Company", "Ned Ver
        Vegan", ...) and then fall back to ``get_all("Company", limit=1)``,
        creating nothing. That is an INVERTED dependency: it passes only while a
        suitable company happens to exist, and it broke when one did — an EUR
        ``Test Company`` created three positions earlier in the same shard by
        ``tests/utils/base.py`` reddened ``test_accounting_dimensions``,
        ``test_project_tracking_integration`` and
        ``test_sales_invoice_creation_flow`` (#291 round 1, shard 11; #308).

        ``get_all(..., limit=1)`` is worse than it looks: the order is META
        driven, and ``Company``'s sort_field is creation ASC, so it answers with
        the OLDEST company on the site — whichever unrelated test or fixture got
        there first.

        ``get_eur_test_company()`` owns ``TEST-Payment-Integration-Company`` and
        guarantees the three things this class actually needs: EUR currency, a
        Fiscal Year covering today, and a usable Chart of Accounts. The account
        and cost-center lookups below all scope by ``cls.company.name``, so they
        become deterministic once the company is.
        """
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        return frappe.get_doc("Company", get_eur_test_company())


    @classmethod
    def _create_test_accounts(cls):
        """Get existing accounts from company's chart of accounts"""
        accounts = {}

        # Get any existing Income account for this company
        income_account = frappe.db.get_value(
            "Account",
            {"company": cls.company.name, "account_type": "Income Account", "is_group": 0},
            "name"
        )
        if not income_account:
            # Fallback: Get any account with 'Income' or 'Revenue' in name
            income_account = frappe.db.get_value(
                "Account",
                {"company": cls.company.name, "account_name": ["like", "%Income%"], "is_group": 0},
                "name"
            ) or frappe.db.get_value(
                "Account",
                {"company": cls.company.name, "root_type": "Income", "is_group": 0},
                "name"
            )

        accounts["membership_income"] = income_account
        accounts["donation_income"] = income_account  # Use same account for simplicity

        # Get any existing Expense account
        expense_account = frappe.db.get_value(
            "Account",
            {"company": cls.company.name, "account_type": "Expense Account", "is_group": 0},
            "name"
        )
        if not expense_account:
            expense_account = frappe.db.get_value(
                "Account",
                {"company": cls.company.name, "root_type": "Expense", "is_group": 0},
                "name"
            )

        accounts["expense_reimbursement"] = expense_account

        return accounts
        
    @classmethod
    def _create_test_cost_centers(cls):
        """Get or create test cost centers - use existing where possible"""
        cost_centers = {}

        # Get existing root cost center for this company (created with company)
        root_cc = frappe.db.get_value(
            "Cost Center",
            {"company": cls.company.name, "is_group": 1, "parent_cost_center": ""},
            "name"
        )

        if not root_cc:
            # Fallback: try company name pattern
            root_cc = f"{cls.company.name} - {cls.company.abbr}"
            if not frappe.db.exists("Cost Center", root_cc):
                root_cc = frappe.db.get_value("Cost Center", {"company": cls.company.name}, "name")

        # Use root/main cost center
        cost_centers["main"] = root_cc or f"Main - {cls.company.abbr}"

        # For chapter cost center, use any existing child or the main one
        child_cc = frappe.db.get_value(
            "Cost Center",
            {"company": cls.company.name, "is_group": 0},
            "name"
        )
        cost_centers["chapter"] = child_cc or cost_centers["main"]

        return cost_centers
        
    @classmethod
    def _create_test_member(cls):
        """Create test member with ERPNext customer"""
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
        factory = CoreTestDataFactory()
        return factory.create_test_member(
            first_name="ERPNext",
            last_name="TestMember",
            phone="+31612345678",
            auto_create_customer=True,
        )

    @classmethod
    def _create_test_volunteer(cls):
        """Create test volunteer"""
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
        factory = CoreTestDataFactory()
        return factory.create_test_volunteer(member=cls.test_member)
        
    def test_company_is_owned_not_borrowed(self):
        """This class must resolve its own company, not whatever the shard left behind.

        Two assertions, because neither is sufficient alone:

        * The identity check catches a reintroduced borrow *deterministically*,
          on any site. The three failures behind #291 round 1 came from
          ``_ensure_test_company`` returning a neighbour's ``Test Company``.
        * The usability checks are what the borrow actually got wrong — a company
          can exist and still have no Income account or a non-EUR currency, which
          is how #237's 101 failures happened. These would pass under a borrow on
          a warm site like test_site_1, where ``Test Company`` has a committed
          chart of accounts; that is exactly why the identity check is here too.
        """
        from verenigingen.tests.support.sepa_test_company import _PREFERRED_EUR_COMPANY

        self.assertEqual(
            self.company.name,
            _PREFERRED_EUR_COMPANY,
            "the test company was borrowed rather than owned; see #308",
        )
        self.assertEqual(self.company.default_currency, "EUR")

        # root_type, not account_type: income GROUP accounts carry no account_type,
        # so filtering on it silently misses a usable chart of accounts.
        self.assertTrue(
            frappe.db.exists(
                "Account",
                {"company": self.company.name, "root_type": "Income", "is_group": 0},
            ),
            f"{self.company.name} has no leaf Income account; its chart of accounts is unusable",
        )
        self.assertTrue(
            frappe.db.exists(
                "Account",
                {"company": self.company.name, "account_type": "Receivable", "is_group": 0},
            ),
            f"{self.company.name} has no Receivable account; Sales Invoice cannot resolve Debit To",
        )

    def test_sales_invoice_creation_flow(self):
        """Test sales invoice creation (draft mode - full submission requires accounting setup)"""
        # Skip if income account not available
        if not self.test_accounts.get("membership_income"):
            self.skipTest("No income account available for testing")

        # Create membership invoice
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "selling_price_list": self.selling_price_list,
            "currency": self.currency,
            "conversion_rate": 1,
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

        # Verify invoice creation (draft mode). Assert on net_total (pre-tax line
        # total) rather than grand_total: the seeded test company may carry a
        # default sales-tax template, inflating grand_total environment-
        # dependently. net_total reflects the qty*rate the test controls.
        self.assertEqual(invoice.docstatus, 0)  # Draft
        self.assertEqual(invoice.net_total, 100.00)
        self.assertIsNotNone(invoice.name)
            
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
        """Test payment entry creation (draft mode - full reconciliation requires accounting setup)"""
        # Get required accounts
        receivable_account = frappe.db.get_value(
            "Account",
            {"account_type": "Receivable", "company": self.company.name},
            "name"
        )
        bank_account = frappe.db.get_value(
            "Account",
            {"account_type": "Bank", "company": self.company.name},
            "name"
        )

        if not receivable_account or not bank_account:
            self.skipTest("Required accounts (Receivable/Bank) not available")

        # Create payment entry (draft mode)
        payment = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": self.test_member.customer,
            "company": self.company.name,
            "posting_date": today(),
            "paid_amount": 150.00,
            "received_amount": 150.00,
            "paid_from": receivable_account,
            "paid_to": bank_account,
            "reference_no": f"PAY-{frappe.utils.random_string(6)}",
            "reference_date": today()
        })

        payment.insert()

        # Verify payment creation (draft mode)
        self.assertEqual(payment.docstatus, 0)  # Draft
        self.assertEqual(payment.paid_amount, 150.00)
        self.assertIsNotNone(payment.name)
        
    def _create_test_invoice(self, amount):
        """Helper to create test invoice"""
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "selling_price_list": self.selling_price_list,
            "currency": self.currency,
            "conversion_rate": 1,
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
        """Test journal entry creation (draft mode - submission requires GL setup)"""
        # Get required accounts
        bank_account = frappe.db.get_value(
            "Account",
            {"account_type": "Bank", "company": self.company.name},
            "name"
        )
        income_account = self.test_accounts.get("donation_income")

        if not bank_account or not income_account:
            self.skipTest("Required accounts (Bank/Income) not available")

        # Test journal entry creation
        donation_je = frappe.get_doc({
            "doctype": "Journal Entry",
            "company": self.company.name,
            # voucher_type (Entry Type) is mandatory on Journal Entry in ERPNext v16.
            "voucher_type": "Journal Entry",
            "posting_date": today(),
            "accounts": [
                {
                    "account": bank_account,
                    "debit_in_account_currency": 500.00,
                    "cost_center": self.cost_centers["main"]
                },
                {
                    "account": income_account,
                    "credit_in_account_currency": 500.00,
                    "cost_center": self.cost_centers["main"]
                }
            ],
            "user_remark": f"Donation from {self.test_member.full_name}"
        })

        donation_je.insert()

        # Verify journal entry creation (draft mode)
        self.assertEqual(donation_je.docstatus, 0)
        self.assertEqual(donation_je.total_debit, 500.00)
        self.assertEqual(donation_je.total_credit, 500.00)
        
    def test_multi_currency_handling(self):
        """Test multi-currency transactions"""
        # Multi-currency invoices require a USD debtors account set up for the customer
        # This test is skipped because it requires complex multi-currency configuration
        # including a separate receivables account for each currency
        self.skipTest("Multi-currency tests require complex receivables account setup")
        
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
        # Skip: Expense Claims require Expense Claim Types with default accounts configured
        # This is complex HRMS setup that's not practical to create programmatically
        # The test would need to configure HR Settings, Expense Claim Types with accounts, etc.
        self.skipTest("Expense Claim integration requires complex HRMS configuration")
            
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
                "first_name": "Verenigingen Volunteer",
                "last_name": self.test_member.last_name,
                "company": self.company.name,
                "date_of_joining": today(),
                "date_of_birth": "1990-01-01",  # Required field
                "gender": "Other",  # Required field - ERPNext mandates this
                "status": "Active"
            })
            employee.insert()
            return employee.name

        return employee_name
        
    def test_project_tracking_integration(self):
        """Test project-based tracking for events and campaigns"""
        # Skip if required accounts/cost centers not available
        if not self.test_accounts.get("donation_income"):
            self.skipTest("Income account not available for test")
        if not self.cost_centers.get("main"):
            self.skipTest("Cost center not available for test")

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
            "selling_price_list": self.selling_price_list,
            "currency": self.currency,
            "conversion_rate": 1,
            "project": project.name,
            "posting_date": today(),
            "cost_center": self.cost_centers["main"],
            "items": [{
                "item_code": self._get_or_create_event_ticket_item(),
                "qty": 2,
                "rate": 50.00,
                "income_account": self.test_accounts["donation_income"],
                "cost_center": self.cost_centers["main"]
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
        # Skip: Tax handling requires a properly configured chart of accounts with
        # tax accounts and Sales Taxes and Charges Templates. This is complex setup
        # that varies between ERPNext installations and is not practical for unit tests.
        self.skipTest("Tax handling requires complex accounting configuration")
        
    def _get_or_create_tax_template(self):
        """Get or create tax template - returns None if unable to create"""
        template_name = f"BTW 21% - {self.company.abbr}"

        # Check if template already exists
        if frappe.db.exists("Sales Taxes and Charges Template", template_name):
            return template_name

        # First, look for existing tax template for this company (any template)
        existing_template = frappe.db.get_value(
            "Sales Taxes and Charges Template",
            {"company": self.company.name},
            "name"
        )
        if existing_template:
            return existing_template

        # Try to find an existing non-group tax account
        tax_account = frappe.db.get_value(
            "Account",
            {"company": self.company.name, "account_type": "Tax", "is_group": 0},
            "name"
        )

        if not tax_account:
            # Try to find the "Duties and Taxes" parent account (it's a group)
            parent_account = f"Duties and Taxes - {self.company.abbr}"
            if not frappe.db.exists("Account", parent_account):
                # Try fallback patterns
                parent_account = frappe.db.get_value(
                    "Account",
                    {"company": self.company.name, "account_name": ["like", "%Duties%Tax%"], "is_group": 1},
                    "name"
                )

            if not parent_account:
                # Cannot create tax account without proper parent - return None
                return None

            # Create tax account under the parent
            tax_account_name = f"BTW 21% - {self.company.abbr}"
            try:
                account = frappe.get_doc({
                    "doctype": "Account",
                    "account_name": "BTW 21%",
                    "parent_account": parent_account,
                    "account_type": "Tax",
                    "company": self.company.name,
                    "is_group": 0
                })
                account.insert()
                tax_account = account.name
            except Exception as e:
                # Failed to create - return None
                return None

        # Create template
        try:
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
        except Exception as e:
            return None

        return template_name
        
    def test_accounting_dimensions(self):
        """Test accounting dimensions (cost center, project, etc.)"""
        # Skip if required accounts/cost centers are not available
        if not self.test_accounts.get("membership_income"):
            self.skipTest("Income account not available for test")
        if not self.cost_centers.get("chapter"):
            self.skipTest("Chapter cost center not available for test")

        # Create invoice with multiple dimensions
        dimensional_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.test_member.customer,
            "company": self.company.name,
            "selling_price_list": self.selling_price_list,
            "currency": self.currency,
            "conversion_rate": 1,
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