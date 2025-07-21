# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Enhanced Base Test Infrastructure for Verenigingen
Provides a hierarchy of test case classes for different testing scenarios
"""

import json
import os
from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase


class VereningingenTestCase(FrappeTestCase):
    """
    Base test case for all Verenigingen tests.
    Provides common utilities and setup/teardown logic.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class-level test environment"""
        super().setUpClass()
        cls._ensure_test_environment()
        cls._track_created_docs = []

    @classmethod
    def tearDownClass(cls):
        """Clean up class-level test data"""
        cls._cleanup_tracked_docs()
        super().tearDownClass()

    def setUp(self):
        """Set up test-specific environment"""
        super().setUp()
        self._test_docs = []
        self._original_session_user = frappe.session.user

    def tearDown(self):
        """Clean up test-specific data"""
        # Restore original session user
        frappe.session.user = self._original_session_user

        # Clean up customers linked to members BEFORE deleting members
        self._cleanup_member_customers()

        # Clean up test docs
        for doc_info in reversed(self._test_docs):
            try:
                if frappe.db.exists(doc_info["doctype"], doc_info["name"]):
                    frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)
            except Exception as e:
                print(f"Error cleaning up {doc_info['doctype']} {doc_info['name']}: {e}")

        super().tearDown()

    @classmethod
    def _ensure_test_environment(cls):
        """Ensure required test environment setup"""
        # Create required doctypes if they don't exist
        cls._ensure_required_doctypes()

    @classmethod
    def _ensure_required_doctypes(cls):
        """Ensure required master data exists"""
        # Ensure test Item Group exists
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Membership",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0}
            )
            item_group.insert(ignore_permissions=True)

        # Ensure test Region exists
        # Check if region with code TR already exists (which is our test region)
        existing_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
        if not existing_region:
            region = frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": "Test Region",
                    "region_code": "TR",
                    "country": "Netherlands",
                    "is_active": 1}
            )
            region.insert(ignore_permissions=True)
            # Store the actual name that was generated
            existing_region = region.name

        # Store the region name for use in tests
        cls._test_region_name = existing_region

        # Ensure test Membership Type exists
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "payment_interval": "Monthly",
                    "amount": 10.00,
                    "is_active": 1}
            )
            membership_type.insert(ignore_permissions=True)

        # Ensure test Chapter exists
        if not frappe.db.exists("Chapter", "Test Chapter"):
            # Get the actual region name after insert
            region_name = frappe.db.get_value("Region", {"region_code": "TR"}, "name") or "test-region"
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "Test Chapter",  # Set name explicitly for prompt autoname
                    "chapter_name": "Test Chapter",
                    "region": region_name,
                    "is_active": 1}
            )
            chapter.insert(ignore_permissions=True)

    def track_doc(self, doctype, name):
        """Track a document for cleanup"""
        self._test_docs.append({"doctype": doctype, "name": name})
    
    def _cleanup_member_customers(self):
        """Clean up customers created for tracked members"""
        # Find all tracked members and their customers
        customers_to_delete = set()
        
        # Method 1: Find customers via Member.customer field
        for doc_info in self._test_docs:
            if doc_info["doctype"] == "Member":
                try:
                    if frappe.db.exists("Member", doc_info["name"]):
                        customer = frappe.db.get_value("Member", doc_info["name"], "customer")
                        if customer:
                            customers_to_delete.add(customer)
                except Exception:
                    pass
            elif doc_info["doctype"] == "Membership Application":
                try:
                    if frappe.db.exists("Membership Application", doc_info["name"]):
                        member = frappe.db.get_value("Membership Application", doc_info["name"], "member")
                        if member and frappe.db.exists("Member", member):
                            customer = frappe.db.get_value("Member", member, "customer")
                            if customer:
                                customers_to_delete.add(customer)
                except Exception:
                    pass
        
        # Method 2: Find customers via new Customer.member field (backup method)
        for doc_info in self._test_docs:
            if doc_info["doctype"] == "Member":
                try:
                    # Use direct customer.member link
                    customer = frappe.db.get_value("Customer", {"member": doc_info["name"]}, "name")
                    if customer:
                        customers_to_delete.add(customer)
                except Exception:
                    pass
        
        # Clean up customer dependencies and then customers
        for customer in customers_to_delete:
            try:
                if frappe.db.exists("Customer", customer):
                    # Clean up related documents first
                    self._cleanup_customer_dependencies(customer)
                    # Delete customer
                    frappe.delete_doc("Customer", customer, force=True, ignore_permissions=True)
                    print(f"✅ Cleaned up customer: {customer}")
            except Exception as e:
                print(f"⚠️ Error cleaning up customer {customer}: {e}")
    
    def _cleanup_customer_dependencies(self, customer_name):
        """Clean up documents that depend on a customer"""
        # Cancel and delete Sales Invoices
        for invoice in frappe.get_all("Sales Invoice", filters={"customer": customer_name}):
            try:
                doc = frappe.get_doc("Sales Invoice", invoice.name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, ignore_permissions=True)
            except:
                pass
        
        # Cancel and delete Payment Entries
        for payment in frappe.get_all("Payment Entry", filters={"party": customer_name, "party_type": "Customer"}):
            try:
                doc = frappe.get_doc("Payment Entry", payment.name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", payment.name, force=True, ignore_permissions=True)
            except:
                pass
        
        # Delete SEPA Mandates (linked to members, not customers directly)
        # Find member linked to this customer and delete their SEPA Mandates
        try:
            member = frappe.db.get_value("Member", {"customer": customer_name}, "name")
            if member:
                for mandate in frappe.get_all("SEPA Mandate", filters={"member": member}):
                    try:
                        frappe.delete_doc("SEPA Mandate", mandate.name, force=True, ignore_permissions=True)
                    except:
                        pass
        except:
            pass
    
    @staticmethod
    def get_test_region_name():
        """Get the actual test region name from database"""
        return frappe.db.get_value("Region", {"region_code": "TR"}, "name") or "test-region"

    @classmethod
    def track_class_doc(cls, doctype, name):
        """Track a document for class-level cleanup"""
        cls._track_created_docs.append({"doctype": doctype, "name": name})

    @classmethod
    def _cleanup_tracked_docs(cls):
        """Clean up all tracked documents"""
        for doc_info in reversed(cls._track_created_docs):
            try:
                if frappe.db.exists(doc_info["doctype"], doc_info["name"]):
                    frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)
            except Exception as e:
                print(f"Error cleaning up {doc_info['doctype']} {doc_info['name']}: {e}")

    @contextmanager
    def as_user(self, user_email):
        """Context manager to execute code as a specific user"""
        original_user = frappe.session.user
        frappe.set_user(user_email)
        try:
            yield
        finally:
            frappe.set_user(original_user)

    def assert_field_value(self, doc, field, expected_value, message=None):
        """Assert that a document field has the expected value"""
        actual_value = doc.get(field)
        if message is None:
            message = f"Expected {doc.doctype}.{field} to be {expected_value}, got {actual_value}"
        self.assertEqual(actual_value, expected_value, message)

    def assert_doc_exists(self, doctype, filters, message=None):
        """Assert that a document exists with given filters"""
        exists = frappe.db.exists(doctype, filters)
        if message is None:
            message = f"Expected {doctype} to exist with filters {filters}"
        self.assertTrue(exists, message)

    def assert_doc_not_exists(self, doctype, filters, message=None):
        """Assert that a document does not exist with given filters"""
        exists = frappe.db.exists(doctype, filters)
        if message is None:
            message = f"Expected {doctype} to not exist with filters {filters}"
        self.assertFalse(exists, message)

    def create_test_member(self, **kwargs):
        """Create a test member with default values"""
        defaults = {
            "first_name": "Test",
            "last_name": "Member",
            "email": f"test.member.{frappe.generate_hash(length=6)}@example.com",
            "member_since": frappe.utils.today(),
            "address_line1": "123 Test Street",
            "postal_code": "1234AB",
            "city": "Test City",
            "country": "Netherlands"
        }
        defaults.update(kwargs)
        
        member = frappe.new_doc("Member")
        for key, value in defaults.items():
            setattr(member, key, value)
        
        member.save()
        self.track_doc("Member", member.name)
        return member

    def create_test_membership_type(self, **kwargs):
        """Create a test membership type with default values"""
        defaults = {
            "membership_type_name": f"Test Type {frappe.generate_hash(length=6)}",
            "amount": 25.0,
            "is_active": 1,
            "contribution_mode": "Calculator",
            "enable_income_calculator": 1,
            "income_percentage_rate": 0.75
        }
        defaults.update(kwargs)
        
        membership_type = frappe.new_doc("Membership Type")
        for key, value in defaults.items():
            setattr(membership_type, key, value)
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type

    def create_test_membership(self, **kwargs):
        """Create a test membership with default values"""
        # Get a test membership type
        membership_type = frappe.db.get_value("Membership Type", {"name": ["like", "%Test%"]}, "name")
        if not membership_type:
            membership_type = frappe.db.get_value("Membership Type", {}, "name")
        
        defaults = {
            "membership_type": membership_type,
            "status": "Active",
            "docstatus": 1,
            "start_date": frappe.utils.today(),
            "from_date": frappe.utils.today(),
            "to_date": frappe.utils.add_months(frappe.utils.today(), 12)
        }
        defaults.update(kwargs)
        
        membership = frappe.new_doc("Membership")
        for key, value in defaults.items():
            setattr(membership, key, value)
        
        membership.save()
        # Only submit if the original default was used (submit by default unless explicitly set to 0)
        if membership.docstatus == 0 and kwargs.get("docstatus", 1) != 0:
            membership.submit()
        self.track_doc("Membership", membership.name)
        return membership

    def create_test_dues_schedule(self, **kwargs):
        """Create a test dues schedule with default values"""
        # If member is provided, create instance from template
        if "member" in kwargs:
            member_name = kwargs["member"]
            membership_type_name = kwargs.get("membership_type")
            
            # Use factory method to create from template
            return self.factory.create_dues_schedule_for_member(member_name, membership_type_name)
        
        # Otherwise create a template (for backward compatibility)
        membership_type = kwargs.get("membership_type")
        if not membership_type:
            membership_type = frappe.db.get_value("Membership Type", {"name": ["like", "%Test%"]}, "name")
            if not membership_type:
                membership_type = frappe.db.get_value("Membership Type", {}, "name")
        
        # Create template
        defaults = {
            "is_template": 1,
            "schedule_name": f"Test-Template-{membership_type}",
            "membership_type": membership_type,
            "amount": 15.00,
            "contribution_mode": "Calculator",
            "status": "Active",
            "auto_generate": 1,
            "minimum_amount": 5.00,
            "suggested_amount": 15.00}
        defaults.update(kwargs)
        
        # Remove deprecated fields if they were passed
        deprecated_fields = ["payment_method", "current_coverage_start", "effective_date", "test_mode"]
        for field in deprecated_fields:
            defaults.pop(field, None)
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        for key, value in defaults.items():
            setattr(dues_schedule, key, value)
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule

    def create_test_chapter(self, **kwargs):
        """Create a test chapter with default values including required region"""
        defaults = {
            "chapter_name": f"Test Chapter {frappe.generate_hash(length=6)}",
            "region": self.get_test_region_name(),  # Use existing test region
            "introduction": "Test chapter for automated testing",
            "status": "Active",
            "establishment_date": frappe.utils.today(),
            "city": "Test City"
        }
        defaults.update(kwargs)
        
        # Generate unique name if not provided
        if "name" not in defaults:
            defaults["name"] = defaults["chapter_name"]
        
        chapter = frappe.new_doc("Chapter")
        for key, value in defaults.items():
            setattr(chapter, key, value)
        
        chapter.save()
        self.track_doc("Chapter", chapter.name)
        return chapter

    def create_test_volunteer_team(self, **kwargs):
        """Create a test volunteer team with default values"""
        defaults = {
            "team_name": f"Test Team {frappe.generate_hash(length=6)}",
            "team_code": f"T{frappe.generate_hash(length=3)}",
            "description": "Test volunteer team for automated testing",
            "team_leader": f"leader.{frappe.generate_hash(length=4)}@example.com",
            "is_active": 1,
            "requires_background_check": 0,
            "minimum_member_status": "Active"
        }
        defaults.update(kwargs)
        
        team = frappe.new_doc("Volunteer Team")
        for key, value in defaults.items():
            setattr(team, key, value)
        
        team.save()
        self.track_doc("Volunteer Team", team.name)
        return team

    def create_test_volunteer_expense(self, **kwargs):
        """Create a test volunteer expense with default values"""
        # Create a volunteer first if not provided
        if "volunteer" not in kwargs:
            volunteer = self.create_test_volunteer()
            kwargs["volunteer"] = volunteer.name
        
        # Get first available expense category
        existing_categories = frappe.get_all("Expense Category", limit=1, pluck="name")
        expense_category = existing_categories[0] if existing_categories else "Reiskosten"
        
        defaults = {
            "expense_date": frappe.utils.today(),
            "description": "Test volunteer expense",
            "amount": 25.00,
            "category": expense_category,
            "organization_type": "Chapter",
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0],
            "status": "Submitted"
        }
        defaults.update(kwargs)
        
        expense = frappe.new_doc("Volunteer Expense")
        for key, value in defaults.items():
            setattr(expense, key, value)
        
        expense.save()
        self.track_doc("Volunteer Expense", expense.name)
        return expense

    def create_test_event(self, **kwargs):
        """Create a test event with default values"""
        defaults = {
            "subject": f"Test Event {frappe.generate_hash(length=6)}",
            "event_type": "Public",
            "starts_on": frappe.utils.add_days(frappe.utils.today(), 30),
            "ends_on": frappe.utils.add_days(frappe.utils.today(), 30),
            "description": "Test event for automated testing"
        }
        defaults.update(kwargs)
        
        event = frappe.new_doc("Event")
        for key, value in defaults.items():
            setattr(event, key, value)
        
        event.save()
        self.track_doc("Event", event.name)
        return event

    def create_test_sepa_mandate(self, **kwargs):
        """Create a test SEPA mandate with default values"""
        # Create a member first if not provided
        if "party" not in kwargs and "member" in kwargs:
            member = frappe.get_doc("Member", kwargs["member"])
            # Ensure member has a customer
            if not member.customer:
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{member.first_name} {member.last_name}"
                customer.customer_type = "Individual"
                customer.member = member.name  # Direct link to member
                customer.save()
                member.customer = customer.name
                member.save()
                self.track_doc("Customer", customer.name)
            kwargs["party"] = member.customer
            kwargs["party_type"] = "Customer"
        
        defaults = {
            "party_type": "Customer",
            "iban": "NL91ABNA0417164300",  # Valid test IBAN
            "account_holder": "Test Account Holder",
            "mandate_type": "RCUR",
            "status": "Active",
            "consent_date": frappe.utils.today(),
            "consent_method": "Online Portal"
        }
        defaults.update(kwargs)
        
        mandate = frappe.new_doc("SEPA Mandate")
        for key, value in defaults.items():
            setattr(mandate, key, value)
        
        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    def create_test_membership_application(self, **kwargs):
        """Create a test membership application with default values"""
        defaults = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": f"applicant.{frappe.generate_hash(length=6)}@example.com",
            "membership_type": "Test Membership",
            "status": "Pending",
            "address_line1": "123 Test Street",
            "postal_code": "1234AB",
            "city": "Test City",
            "country": "Netherlands",
            "application_date": frappe.utils.today()
        }
        defaults.update(kwargs)
        
        application = frappe.new_doc("Membership Application")
        for key, value in defaults.items():
            setattr(application, key, value)
        
        application.save()
        self.track_doc("Membership Application", application.name)
        return application

    def create_test_sales_invoice(self, **kwargs):
        """Create a test sales invoice with default values"""
        # Ensure we have a customer
        if "customer" not in kwargs:
            if "member" in kwargs:
                member = frappe.get_doc("Member", kwargs["member"])
                if not member.customer:
                    customer = frappe.new_doc("Customer")
                    customer.customer_name = f"{member.first_name} {member.last_name}"
                    customer.customer_type = "Individual"
                    customer.member = member.name  # Direct link to member
                    customer.save()
                    member.customer = customer.name
                    member.save()
                    self.track_doc("Customer", customer.name)
                kwargs["customer"] = member.customer
            else:
                # Create a test customer
                customer = frappe.new_doc("Customer")
                customer.customer_name = "Test Customer"
                customer.customer_type = "Individual"
                customer.save()
                self.track_doc("Customer", customer.name)
                kwargs["customer"] = customer.name
        
        defaults = {
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "is_membership_invoice": 1,
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0]
        }
        defaults.update(kwargs)
        
        invoice = frappe.new_doc("Sales Invoice")
        for key, value in defaults.items():
            setattr(invoice, key, value)
        
        # Add a default item if no items provided
        if not invoice.items:
            invoice.append("items", {
                "item_code": "MEMBERSHIP-MONTHLY",
                "qty": 1,
                "rate": 25.0,
                "income_account": "Sales - TC"
            })
        
        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def create_test_donor(self, **kwargs):
        """Create a test donor with default values"""
        defaults = {
            "donor_name": f"Test Donor {frappe.generate_hash(length=6)}",
            "donor_email": f"donor.{frappe.generate_hash(length=6)}@example.com",
            "donor_type": "Individual",
            "is_anbi_eligible": 1
        }
        defaults.update(kwargs)
        
        donor = frappe.new_doc("Donor")
        for key, value in defaults.items():
            setattr(donor, key, value)
        
        donor.save()
        self.track_doc("Donor", donor.name)
        return donor

    def create_test_periodic_donation_agreement(self, **kwargs):
        """Create a test periodic donation agreement with default values"""
        # Create a donor first if not provided
        if "donor" not in kwargs:
            donor = self.create_test_donor()
            kwargs["donor"] = donor.name
        
        defaults = {
            "start_date": frappe.utils.today(),
            "annual_amount": 1200,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "agreement_duration_years": "5 Years (ANBI Minimum)",
            "anbi_eligible": 1,
            "status": "Draft"
        }
        defaults.update(kwargs)
        
        agreement = frappe.new_doc("Periodic Donation Agreement")
        for key, value in defaults.items():
            setattr(agreement, key, value)
        
        agreement.save()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        return agreement

    def create_test_donation(self, **kwargs):
        """Create a test donation with default values"""
        # Create a donor first if not provided
        if "donor" not in kwargs:
            donor = self.create_test_donor()
            kwargs["donor"] = donor.name
        
        defaults = {
            "date": frappe.utils.today(),
            "amount": 100.0,
            "payment_method": "Bank Transfer",
            "donor_type": "Individual",
            "currency": "EUR",
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0]
        }
        defaults.update(kwargs)
        
        donation = frappe.new_doc("Donation")
        for key, value in defaults.items():
            setattr(donation, key, value)
        
        donation.save()
        self.track_doc("Donation", donation.name)
        return donation

    def create_anbi_compliant_agreement(self, **kwargs):
        """Create an ANBI-compliant donation agreement (5+ years)"""
        defaults = {
            "agreement_duration_years": "5 Years (ANBI Minimum)",
            "anbi_eligible": 1,
            "annual_amount": 1200
        }
        defaults.update(kwargs)
        return self.create_test_periodic_donation_agreement(**defaults)

    def create_non_anbi_pledge(self, **kwargs):
        """Create a non-ANBI pledge (1-4 years)"""
        defaults = {
            "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
            "anbi_eligible": 0,
            "annual_amount": 600
        }
        defaults.update(kwargs)
        return self.create_test_periodic_donation_agreement(**defaults)

    def create_test_payment_entry(self, **kwargs):
        """Create a test payment entry with default values"""
        # Ensure we have a party (customer or supplier)
        if "party" not in kwargs:
            if "member" in kwargs:
                member = frappe.get_doc("Member", kwargs["member"])
                if not member.customer:
                    customer = frappe.new_doc("Customer")
                    customer.customer_name = f"{member.first_name} {member.last_name}"
                    customer.customer_type = "Individual"
                    customer.member = member.name  # Direct link to member
                    customer.save()
                    member.customer = customer.name
                    member.save()
                    self.track_doc("Customer", customer.name)
                kwargs["party"] = member.customer
                kwargs["party_type"] = "Customer"
            else:
                # Create a test customer
                customer = frappe.new_doc("Customer")
                customer.customer_name = "Test Payment Customer"
                customer.customer_type = "Individual"
                customer.save()
                self.track_doc("Customer", customer.name)
                kwargs["party"] = customer.name
                kwargs["party_type"] = "Customer"
        
        defaults = {
            "payment_type": "Receive",
            "posting_date": frappe.utils.today(),
            "paid_amount": 100.0,
            "received_amount": 100.0,
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0],
            "mode_of_payment": "Bank Transfer"
        }
        defaults.update(kwargs)
        
        payment = frappe.new_doc("Payment Entry")
        for key, value in defaults.items():
            setattr(payment, key, value)
        
        payment.save()
        self.track_doc("Payment Entry", payment.name)
        return payment

    def create_test_direct_debit_batch(self, **kwargs):
        """Create a test direct debit batch with default values"""
        defaults = {
            "batch_name": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "collection_date": frappe.utils.add_days(frappe.utils.today(), 3),
            "batch_status": "Draft",
            "payment_method": "SEPA Direct Debit",
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0]
        }
        defaults.update(kwargs)
        
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        
        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)
        return batch

    def create_test_chapter_role(self, **kwargs):
        """Create a test chapter role with default values"""
        defaults = {
            "role_name": f"Test Role {frappe.generate_hash(length=6)}",
            "description": "Test role for automated testing",
            "permissions_level": "Basic",  # Valid options: Basic/Financial/Admin
            "is_chair": 0,
            "is_unique": 0,
            "is_active": 1
        }
        defaults.update(kwargs)
        
        role = frappe.new_doc("Chapter Role")
        for key, value in defaults.items():
            setattr(role, key, value)
        
        role.save()
        self.track_doc("Chapter Role", role.name)
        return role

    def create_test_volunteer(self, **kwargs):
        """Create a test volunteer with default values"""
        # Create a member first if not provided
        if "member" not in kwargs:
            member = self.create_test_member()
            kwargs["member"] = member.name
        
        defaults = {
            "volunteer_name": f"Test Volunteer {frappe.generate_hash(length=6)}",  # Required field
            "email": f"volunteer.{frappe.generate_hash(length=6)}@example.com",    # Required, unique field
            "status": "Active",
            "start_date": frappe.utils.today()
        }
        defaults.update(kwargs)
        
        volunteer = frappe.new_doc("Volunteer")
        for key, value in defaults.items():
            setattr(volunteer, key, value)
        
        volunteer.save()
        self.track_doc("Volunteer", volunteer.name)
        return volunteer

    def add_board_member_to_chapter(self, chapter, volunteer, chapter_role, **kwargs):
        """Add a board member to a chapter with proper validation"""
        defaults = {
            "volunteer": volunteer.name if hasattr(volunteer, 'name') else volunteer,
            "chapter_role": chapter_role.name if hasattr(chapter_role, 'name') else chapter_role,
            "from_date": frappe.utils.today(),
            "is_active": 1
        }
        defaults.update(kwargs)
        
        chapter.append("board_members", defaults)
        chapter.save()
        
        return chapter

    def create_test_user(self, email, roles=None, password="test123"):
        """Create a test user with specified roles"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Test",
                    "last_name": "User",
                    "enabled": 1,
                    "new_password": password}
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", email)

        if roles:
            user.roles = []
            for role in roles:
                user.append("roles", {"role": role})
            user.save(ignore_permissions=True)

        return user

    def get_test_data_path(self, filename):
        """Get path to test data file"""
        return os.path.join(os.path.dirname(__file__), "..", "fixtures", filename)

    def load_test_data(self, filename):
        """Load test data from JSON file"""
        with open(self.get_test_data_path(filename), "r") as f:
            return json.load(f)


class VereningingenUnitTestCase(VereningingenTestCase):
    """
    Test case for isolated unit tests.
    Provides utilities for mocking and isolated testing.
    """

    def setUp(self):
        """Set up unit test environment"""
        super().setUp()
        self._mocked_functions = {}

    def tearDown(self):
        """Restore mocked functions"""
        for func_path, original in self._mocked_functions.items():
            module_path, func_name = func_path.rsplit(".", 1)
            module = self._get_module(module_path)
            setattr(module, func_name, original)
        super().tearDown()

    def mock_function(self, function_path, mock_implementation):
        """Mock a function for testing"""
        module_path, func_name = function_path.rsplit(".", 1)
        module = self._get_module(module_path)

        # Store original function
        self._mocked_functions[function_path] = getattr(module, func_name)

        # Replace with mock
        setattr(module, func_name, mock_implementation)

    def _get_module(self, module_path):
        """Get module from dotted path"""
        parts = module_path.split(".")
        module = __import__(parts[0])
        for part in parts[1:]:
            module = getattr(module, part)
        return module

    @contextmanager
    def assert_validates(self):
        """Context manager to assert that code validates without errors"""
        try:
            yield
        except frappe.ValidationError as e:
            self.fail(f"Unexpected validation error: {e}")

    @contextmanager
    def assert_validation_error(self, expected_message=None):
        """Context manager to assert that code raises a validation error"""
        try:
            yield
            self.fail("Expected ValidationError but none was raised")
        except frappe.ValidationError as e:
            if expected_message:
                self.assertIn(expected_message, str(e))


class VereningingenIntegrationTestCase(VereningingenTestCase):
    """
    Test case for integration tests.
    Provides utilities for testing component interactions.
    """

    def setUp(self):
        """Set up integration test environment"""
        super().setUp()
        self._ensure_integration_environment()

    def _ensure_integration_environment(self):
        """Ensure integration test environment is ready"""
        # Ensure ERPNext required data
        self._ensure_erpnext_setup()

    def _ensure_erpnext_setup(self):
        """Ensure ERPNext is properly set up for testing"""
        # Ensure default company
        if not frappe.db.exists("Company", "Test Company"):
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Company",
                    "default_currency": "EUR",
                    "country": "Netherlands"}
            )
            company.insert(ignore_permissions=True)

        # Ensure default customer group
        if not frappe.db.exists("Customer Group", "All Customer Groups"):
            customer_group = frappe.get_doc(
                {"doctype": "Customer Group", "customer_group_name": "All Customer Groups", "is_group": 1}
            )
            customer_group.insert(ignore_permissions=True)

    def execute_workflow_stage(self, workflow_name, stage_name, context):
        """Execute a specific workflow stage"""
        # This would integrate with actual workflow engine

    def assert_integration_state(self, expected_state):
        """Assert that integrations are in expected state"""
        # Check ERPNext integration state
        # Check email queue state
        # Check payment gateway state


class VereningingenWorkflowTestCase(VereningingenIntegrationTestCase):
    """
    Test case for multi-stage workflow tests.
    Provides utilities for testing complex business processes.
    """

    def setUp(self):
        """Set up workflow test environment"""
        super().setUp()
        self._workflow_context = {}
        self._workflow_stages = []

    def define_workflow(self, stages):
        """Define workflow stages for testing"""
        self._workflow_stages = stages

    def execute_workflow(self):
        """Execute all workflow stages"""
        for stage in self._workflow_stages:
            self._execute_stage(stage)

    def _execute_stage(self, stage):
        """Execute a single workflow stage"""
        stage.get("name")
        stage_func = stage.get("function")
        validations = stage.get("validations", [])

        # Execute stage function
        result = stage_func(self._workflow_context)

        # Update context
        if isinstance(result, dict):
            self._workflow_context.update(result)

        # Run validations
        for validation in validations:
            validation(self._workflow_context)

    def assert_workflow_state(self, field, expected_value):
        """Assert workflow context state"""
        actual_value = self._workflow_context.get(field)
        self.assertEqual(
            actual_value,
            expected_value,
            f"Expected workflow.{field} to be {expected_value}, got {actual_value}",
        )

    def get_workflow_context(self, field=None):
        """Get workflow context or specific field"""
        if field:
            return self._workflow_context.get(field)
        return self._workflow_context

    @contextmanager
    def workflow_transaction(self):
        """Execute workflow stages within a transaction"""
        # Note: Frappe doesn't allow explicit transactions in test context
        # Using try/except for error handling instead
        try:
            yield
        except Exception:
            # Clean up any partial data
            frappe.db.rollback()
            raise
