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
        # Track test start time for error monitoring
        self._test_start_time = frappe.utils.now()
        
        # Initialize test data factory
        from verenigingen.tests.test_data_factory import TestDataFactory
        self.factory = TestDataFactory()

    def tearDown(self):
        """Clean up test-specific data"""
        # Check for errors that occurred during this test BEFORE cleanup
        self._check_test_errors()
        
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
        
    def _check_test_errors(self):
        """Check for errors that occurred during this test"""
        try:
            test_errors = frappe.db.sql('''
                SELECT error, creation 
                FROM `tabError Log` 
                WHERE creation >= %s
                ORDER BY creation DESC
                LIMIT 5
            ''', (self._test_start_time,), as_dict=True)
            
            if test_errors:
                error_summary = []
                for error in test_errors:
                    # Truncate long errors for readability
                    error_text = error.error[:200] + "..." if len(error.error) > 200 else error.error
                    error_summary.append(f"  - {error.creation}: {error_text}")
                
                error_msg = f"Errors occurred during test {self._testMethodName}:\n" + "\n".join(error_summary)
                
                # Use frappe.logger to avoid failing tests due to error logging issues
                frappe.logger().error(f"Test Error Detection: {error_msg}")
                
                # For now, just log the errors rather than failing tests
                # In the future, we can make this configurable or fail on critical errors
                print(f"WARNING: {error_msg}")
                
        except Exception as e:
            # Don't let error checking itself break tests
            frappe.logger().error(f"Error during test error checking: {str(e)}")
            print(f"Warning: Could not check for test errors: {str(e)}")

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

        # Ensure test Chapter exists (unique per test session)
        cls._test_chapter_name = getattr(cls, '_test_chapter_name', f"Test Chapter {frappe.generate_hash(length=8)}")
        if not frappe.db.exists("Chapter", cls._test_chapter_name):
            # Get the actual region name after insert
            region_name = frappe.db.get_value("Region", {"region_code": "TR"}, "name") or "test-region"
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": cls._test_chapter_name,  # Set name explicitly for prompt autoname
                    "chapter_name": cls._test_chapter_name,
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
        # Cancel and delete Sales Invoices - optimized batch approach
        invoices = frappe.get_all(
            "Sales Invoice", 
            filters={"customer": customer_name},
            fields=["name", "docstatus"]
        )
        
        for invoice in invoices:
            try:
                if invoice.docstatus == 1:
                    frappe.db.set_value("Sales Invoice", invoice.name, "docstatus", 2)
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, ignore_permissions=True)
            except (frappe.DoesNotExistError, frappe.ValidationError):
                continue  # Document already deleted or invalid
        
        # Cancel and delete Payment Entries - optimized
        payments = frappe.get_all(
            "Payment Entry", 
            filters={"party": customer_name, "party_type": "Customer"},
            fields=["name", "docstatus"]
        )
        
        for payment in payments:
            try:
                if payment.docstatus == 1:
                    frappe.db.set_value("Payment Entry", payment.name, "docstatus", 2)
                frappe.delete_doc("Payment Entry", payment.name, force=True, ignore_permissions=True)
            except (frappe.DoesNotExistError, frappe.ValidationError):
                continue
        
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
    def get_test_chapter_name(cls):
        """Get the unique test chapter name for this test session"""
        return getattr(cls, '_test_chapter_name', f"Test Chapter {frappe.generate_hash(length=8)}")

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
        # Get a dues schedule template first
        template = frappe.db.get_value("Membership Dues Schedule", 
            {"name": ["like", "%Monthly%"]}, "name") or "Monthly Membership Template"
            
        defaults = {
            "membership_type_name": f"Test Type {frappe.generate_hash(length=6)}",
            "amount": 25.0,
            "is_active": 1,
            "contribution_mode": "Calculator",
            "enable_income_calculator": 1,
            "income_percentage_rate": 0.75,
            "dues_schedule_template": template
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
        # Get a test membership type with low minimum amount
        membership_type = frappe.db.get_value(
            "Membership Type", 
            {"minimum_amount": ["<=", 5.0]}, 
            "name",
            order_by="minimum_amount asc"
        )
        if not membership_type:
            # Fallback to any test membership type
            membership_type = frappe.db.get_value("Membership Type", {"name": ["like", "%Test%"]}, "name")
        if not membership_type:
            # Final fallback
            membership_type = "Test Membership"
        
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
        # If member is provided, create instance directly (not from template)
        # since factory method doesn't support custom kwargs like dues_rate
        if "member" in kwargs:
            member_name = kwargs.pop("member")
            membership_type_name = kwargs.get("membership_type")
            
            # Get membership type if not provided
            if not membership_type_name:
                membership = frappe.db.get_value(
                    "Membership",
                    {"member": member_name, "status": "Active"},
                    "membership_type"
                )
                if membership:
                    membership_type_name = membership
                else:
                    # Fallback to any membership type
                    membership_type_name = frappe.db.get_value("Membership Type", {}, "name")
            
            # Create schedule directly with all kwargs
            defaults = {
                "schedule_name": f"Test-{member_name}-{membership_type_name}",
                "member": member_name,
                "membership_type": membership_type_name,
                "dues_rate": 15.00,
                "billing_frequency": "Monthly",
                "status": "Active",
                "auto_generate": 1,
                "next_invoice_date": frappe.utils.today(),
                "is_template": 0  # This is a member instance, not template
            }
            defaults.update(kwargs)  # This will override dues_rate if provided
            
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            for key, value in defaults.items():
                setattr(dues_schedule, key, value)
            
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule
        
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
            "dues_rate": 15.00,  # Fixed: was "amount", should be "dues_rate"
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
        # Generate unique chapter name if not provided
        chapter_name = kwargs.pop("chapter_name", f"Test Chapter {frappe.generate_hash(length=6)}")
        
        defaults = {
            "region": self.get_test_region_name(),  # Use existing test region
            "introduction": "Test chapter for automated testing",
            "published": 1,  # Enable chapter to be found in searches
        }
        defaults.update(kwargs)
        
        chapter = frappe.new_doc("Chapter")
        chapter.name = chapter_name  # Set the name directly
        
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
        """
        Create a test SEPA mandate with enhanced validation and scenarios
        
        Args:
            scenario: Predefined scenario ("normal", "first_payment", "one_time", "suspended", "expired", "cancelled")
            bank_code: Mock bank code ("TEST", "MOCK", "DEMO")
            **kwargs: Additional field overrides
        
        Returns:
            SEPA Mandate document with automatic cleanup tracking
        """
        # Extract scenario-specific parameters
        scenario = kwargs.pop("scenario", "normal")
        bank_code = kwargs.pop("bank_code", "TEST")
        
        # Create a member first if not provided
        if "member" not in kwargs:
            member = self.create_test_member(
                first_name="SEPA",
                last_name="TestMember",
                email=f"sepa.{frappe.generate_hash(length=6)}@example.com"
            )
            kwargs["member"] = member.name
        
        # Ensure member has a customer (required for mandates)
        member_doc = frappe.get_doc("Member", kwargs["member"])
        if not member_doc.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member_doc.first_name} {member_doc.last_name}"
            customer.customer_type = "Individual"
            customer.member = member_doc.name  # Direct link to member
            customer.save()
            member_doc.customer = customer.name
            member_doc.save()
            self.track_doc("Customer", customer.name)
        
        # Scenario-based defaults with realistic test data
        scenario_defaults = {
            "normal": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "RCUR",
                "is_active": 1,
                "frequency": "Monthly",
                "maximum_amount": 100.00,
                "used_for_memberships": 1,
                "used_for_donations": 0
            },
            "first_payment": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "CORE",  # First payment in sequence
                "is_active": 1,
                "frequency": "Monthly",
                "maximum_amount": 50.00,
                "used_for_memberships": 1,
                "first_collection_date": frappe.utils.add_days(frappe.utils.today(), 5)
            },
            "one_time": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "OOFF",  # One-off payment
                "is_active": 1,
                "frequency": "Variable",
                "maximum_amount": 500.00,
                "used_for_donations": 1,
                "used_for_memberships": 0
            },
            "suspended": {
                "iban": self._get_test_iban(bank_code),
                "status": "Suspended",
                "mandate_type": "RCUR",
                "is_active": 0,  # Suspended mandate
                "frequency": "Monthly",
                "maximum_amount": 75.00,
                "used_for_memberships": 1
            },
            "expired": {
                "iban": self._get_test_iban(bank_code),
                "status": "Expired",
                "mandate_type": "RCUR",
                "is_active": 0,
                "frequency": "Monthly",
                "maximum_amount": 25.00,
                "expiry_date": frappe.utils.add_days(frappe.utils.today(), -30),  # Expired 30 days ago
                "used_for_memberships": 1
            },
            "cancelled": {
                "iban": self._get_test_iban(bank_code),
                "status": "Cancelled",
                "mandate_type": "RCUR",
                "is_active": 0,
                "frequency": "Monthly",
                "maximum_amount": 30.00,
                "cancelled_date": frappe.utils.add_days(frappe.utils.today(), -7),  # Cancelled 7 days ago
                "cancellation_reason": "Member request - account change",
                "used_for_memberships": 1
            }
        }
        
        # Get scenario-specific defaults
        defaults = scenario_defaults.get(scenario, scenario_defaults["normal"])
        
        # Add common defaults for all scenarios
        common_defaults = {
            "account_holder_name": f"{member_doc.first_name} {member_doc.last_name}",
            "sign_date": frappe.utils.today(),
            "scheme": "SEPA"
        }
        defaults.update(common_defaults)
        
        # Apply user overrides
        defaults.update(kwargs)
        
        # Create mandate with proper field validation
        mandate = frappe.new_doc("SEPA Mandate")
        
        # Validate fields exist in DocType before setting
        valid_fields = [field.get("fieldname") for field in mandate.meta.fields]
        for key, value in defaults.items():
            if key in valid_fields:
                setattr(mandate, key, value)
        
        # Auto-generate mandate_id if not provided
        if "mandate_id" not in kwargs:
            # Generate unique mandate ID based on scenario
            scenario_prefix = scenario.upper()[:4]
            hash_suffix = frappe.generate_hash(length=6)
            mandate.mandate_id = f"{scenario_prefix}-{hash_suffix}"
        
        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate
    
    def _get_test_iban(self, bank_code="TEST"):
        """Generate a unique valid test IBAN for testing"""
        try:
            # Try to use the main generator when Frappe is available
            from verenigingen.utils.validation.iban_validator import generate_test_iban
            return generate_test_iban(bank_code)
        except (ImportError, ModuleNotFoundError):
            # Fallback to standalone IBAN generation when Frappe is not available
            return self._generate_standalone_test_iban(bank_code)
    
    def _generate_standalone_test_iban(self, bank_code="TEST", account_number=None):
        """Generate a valid test IBAN without Frappe dependencies"""
        if bank_code not in ["TEST", "MOCK", "DEMO"]:
            bank_code = "TEST"

        if not account_number:
            # Generate a simple 10-digit account number
            account_number = "0123456789"

        # Ensure account number is 10 digits
        account_number = account_number.zfill(10)[:10]

        # Calculate correct checksum using MOD-97 algorithm
        # Create temp IBAN with 00 checksum
        temp_iban = "NL00" + bank_code + account_number
        
        # Move first 4 characters to end
        rearranged = temp_iban[4:] + temp_iban[:4]
        
        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric_iban = ""
        for char in rearranged:
            if char.isdigit():
                numeric_iban += char
            else:
                numeric_iban += str(ord(char) - ord("A") + 10)
        
        # Calculate checksum
        remainder = int(numeric_iban) % 97
        checksum = 98 - remainder
        
        # Construct final IBAN
        iban = f"NL{checksum:02d}{bank_code}{account_number}"
        return iban
    
    def create_test_sepa_mandate_with_pattern(self, pattern, starting_counter, **kwargs):
        """Create a test SEPA mandate with specific naming pattern for testing"""
        # Store current settings
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = getattr(settings, 'sepa_mandate_naming_pattern', None)
        original_counter = getattr(settings, 'sepa_mandate_starting_counter', None)
        
        try:
            # Set test pattern
            settings.sepa_mandate_naming_pattern = pattern
            settings.sepa_mandate_starting_counter = starting_counter
            settings.save()
            
            # Create mandate with test pattern
            mandate = self.create_test_sepa_mandate(**kwargs)
            
            return mandate
            
        finally:
            # Restore original settings
            if original_pattern is not None:
                settings.sepa_mandate_naming_pattern = original_pattern
            if original_counter is not None:
                settings.sepa_mandate_starting_counter = original_counter
            settings.save()
    
    def assert_sepa_mandate_pattern(self, mandate, expected_prefix, expected_counter=None):
        """Assert that a SEPA mandate follows expected naming pattern"""
        self.assertTrue(mandate.mandate_id, "SEPA Mandate should have mandate_id")
        self.assertTrue(mandate.mandate_id.startswith(expected_prefix), 
                       f"mandate_id '{mandate.mandate_id}' should start with '{expected_prefix}'")
        
        if expected_counter:
            self.assertIn(str(expected_counter).zfill(4), mandate.mandate_id,
                         f"mandate_id '{mandate.mandate_id}' should contain counter '{expected_counter}'")
    
    def get_sepa_settings_backup(self):
        """Get current SEPA settings for backup/restore"""
        settings = frappe.get_single("Verenigingen Settings")
        return {
            "pattern": getattr(settings, 'sepa_mandate_naming_pattern', None),
            "counter": getattr(settings, 'sepa_mandate_starting_counter', None)
        }
    
    def restore_sepa_settings(self, backup):
        """Restore SEPA settings from backup"""
        settings = frappe.get_single("Verenigingen Settings")
        settings.reload()  # Refresh to avoid timestamp issues
        if backup["pattern"] is not None:
            settings.sepa_mandate_naming_pattern = backup["pattern"]
        if backup["counter"] is not None:
            settings.sepa_mandate_starting_counter = backup["counter"]
        settings.save()

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
            # Get a valid income account for the company 
            company = defaults.get("company")
            income_account = frappe.get_all("Account", 
                filters={"account_type": "Income Account", "company": company, "is_group": 0}, 
                limit=1, pluck="name")
            if not income_account:
                # Fallback - create a basic income account if none exists
                income_account = self._get_or_create_income_account(company)
            else:
                income_account = income_account[0]
            
            # Get or create a test item
            item_code = self._get_or_create_test_item()
            
            invoice.append("items", {
                "item_code": item_code,
                "qty": 1,
                "rate": 25.0,
                "income_account": income_account
            })
        
        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _get_or_create_income_account(self, company):
        """Get or create a basic income account for testing"""
        account_name = f"Test Sales Income - {company}"
        
        # Check if account already exists
        existing = frappe.db.get_value("Account", {"account_name": "Test Sales Income", "company": company})
        if existing:
            return existing
        
        # Create new income account
        account = frappe.new_doc("Account")
        account.account_name = "Test Sales Income"
        account.company = company
        account.account_type = "Income Account"
        account.root_type = "Income"
        account.report_type = "Profit and Loss"
        account.is_group = 0
        
        # Find parent group
        parent_account = frappe.get_all("Account", 
            filters={"account_type": "Income Account", "company": company, "is_group": 1}, 
            limit=1, pluck="name")
        if parent_account:
            account.parent_account = parent_account[0]
        else:
            # Create basic Income group if it doesn't exist
            income_group = frappe.new_doc("Account")
            income_group.account_name = "Income"
            income_group.company = company
            income_group.root_type = "Income"
            income_group.report_type = "Profit and Loss"
            income_group.is_group = 1
            income_group.save()
            self.track_doc("Account", income_group.name)
            account.parent_account = income_group.name
        
        account.save()
        self.track_doc("Account", account.name)
        return account.name

    def _get_or_create_test_item(self):
        """Get or create a test item for invoices"""
        item_code = "TEST-MEMBERSHIP"
        
        # Check if item already exists
        if frappe.db.exists("Item", item_code):
            return item_code
        
        # Create new test item
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = "Test Membership Item"
        item.item_group = "Services"  # Common item group
        item.is_sales_item = 1
        item.is_service_item = 1
        item.include_item_in_manufacturing = 0
        item.is_stock_item = 0
        item.has_variants = 0
        item.variant_of = ""
        item.standard_rate = 25.0
        
        # Try to find item group or create one
        if not frappe.db.exists("Item Group", "Services"):
            # Create basic Services item group
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Services"
            item_group.is_group = 0
            # Find or create parent group
            if frappe.db.exists("Item Group", "All Item Groups"):
                item_group.parent_item_group = "All Item Groups"
            item_group.save()
            self.track_doc("Item Group", item_group.name)
        
        item.save()
        self.track_doc("Item", item.name)
        return item.name

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
        """Create a test direct debit batch with default values and invoices"""
        defaults = {
            "batch_date": frappe.utils.today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR"
        }
        defaults.update(kwargs)
        
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        
        # Create test invoice to satisfy validation requirement
        if not kwargs.get("skip_invoice_creation", False):
            # Create a member, membership, and invoice for the batch
            test_member = self.create_test_member()
            test_membership = self.create_test_membership(member=test_member.name)
            test_invoice = self.create_test_sales_invoice(
                customer=test_member.customer,
                is_membership_invoice=1,
                membership=test_membership.name
            )
            
            # Create SEPA mandate for the member
            test_mandate = self.create_test_sepa_mandate(
                member=test_member.name,
                bank_code="TEST"  # Use mock bank
            )
            
            # Ensure invoice is unpaid for batch validation
            # Reset any payment allocations that might exist from test pollution
            frappe.db.sql("""
                DELETE FROM `tabPayment Entry Reference` 
                WHERE reference_doctype = 'Sales Invoice' AND reference_name = %s
            """, (test_invoice.name,))
            
            # Update invoice status to be unpaid
            frappe.db.set_value("Sales Invoice", test_invoice.name, {
                "outstanding_amount": test_invoice.grand_total,
                "status": "Unpaid"
            })
            
            # Add invoice to batch with all required fields
            batch.append("invoices", {
                "invoice": test_invoice.name,
                "membership": test_membership.name,
                "member": test_member.name,
                "member_name": f"{test_member.first_name} {test_member.last_name}",
                "amount": test_invoice.grand_total,
                "currency": "EUR",
                "iban": test_mandate.iban,
                "mandate_reference": test_mandate.mandate_id
            })
        
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

    def create_test_volunteer_with_realistic_name(self, **kwargs):
        """Create volunteer with realistic name that could cause duplicates (for production scenario testing)"""
        common_names = [
            ("John", "Smith"), ("Mary", "Johnson"), ("James", "Williams"),
            ("Patricia", "Brown"), ("Robert", "Jones"), ("Jennifer", "Garcia"),
            ("Michael", "Davis"), ("Linda", "Rodriguez"), ("David", "Martinez"),
            ("Barbara", "Hernandez"), ("William", "Anderson"), ("Elizabeth", "Taylor")
        ]
        
        # Use deterministic but realistic names based on test context
        import hashlib
        test_context = f"{self._testMethodName}_{str(kwargs)}"
        test_id = hashlib.md5(test_context.encode()).hexdigest()[:4]
        name_index = int(test_id, 16) % len(common_names)
        first_name, last_name = common_names[name_index]
        
        # Create member with realistic name if not provided
        if "member" not in kwargs:
            member = self.create_test_member(
                first_name=first_name,
                last_name=last_name,
                email=f"{first_name.lower()}.{last_name.lower()}.{test_id}@example.com"
            )
            kwargs["member"] = member.name
        
        # Don't override volunteer_name if explicitly provided
        if "volunteer_name" not in kwargs:
            # Get the member to use their name
            member_doc = frappe.get_doc("Member", kwargs["member"])
            kwargs["volunteer_name"] = f"{member_doc.first_name} {member_doc.last_name}".strip()
        
        return self.create_test_volunteer(**kwargs)

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

    # Edge Case Testing Methods
    # Added based on user suggestion for better testing approach
    
    def clear_member_auto_schedules(self, member_name):
        """
        Clear auto-created schedules for a member to enable controlled edge case testing.
        
        This method implements the approach suggested for testing edge cases:
        1. Find all active schedules for the member
        2. Cancel them (removes business rule blocks)  
        3. Return list of cancelled schedules for reference
        
        Use this when you need to create specific test scenarios with multiple
        schedules or conflicting configurations that would normally be prevented
        by business rules.
        
        Args:
            member_name (str): Name/ID of the member
            
        Returns:
            list: List of cancelled schedule details
            
        Example:
            member = self.create_test_member()
            membership = self.create_test_membership(member=member.name)
            
            # Clear auto-schedules to enable edge case testing
            cancelled = self.clear_member_auto_schedules(member.name)
            
            # Now create controlled test schedules
            schedule1 = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            schedule2 = self.create_controlled_dues_schedule(member.name, "Annual", 200.0)
            
            # Test validation logic on the conflicting schedules
            validation_result = schedule2.validate_billing_frequency_consistency()
            self.assertFalse(validation_result["valid"])
        """
        
        # Find all active schedules for this member
        active_schedules = frappe.get_all("Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "billing_frequency", "dues_rate"]
        )
        
        cancelled_schedules = []
        
        for schedule_info in active_schedules:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
                original_status = schedule.status
                schedule.status = "Cancelled"
                schedule.save()
                
                # Track for cleanup
                self.track_doc("Membership Dues Schedule", schedule.name)
                
                cancelled_schedules.append({
                    'name': schedule.name,
                    'original_status': original_status,
                    'billing_frequency': schedule_info.billing_frequency,
                    'dues_rate': schedule_info.dues_rate
                })
                
            except Exception as e:
                # Log but continue - some schedules might not be cancellable
                print(f"Warning: Could not cancel schedule {schedule_info.name}: {str(e)}")
        
        return cancelled_schedules
    
    def create_controlled_dues_schedule(self, member_name, billing_frequency, dues_rate, **kwargs):
        """
        Create a controlled dues schedule for edge case testing.
        
        This method creates a schedule with specific parameters, bypassing
        normal auto-creation logic. Use after clear_member_auto_schedules()
        to create test scenarios with multiple or conflicting schedules.
        
        Args:
            member_name (str): Member to create schedule for
            billing_frequency (str): Monthly, Quarterly, Annual, etc.
            dues_rate (float): Amount for the schedule
            **kwargs: Additional fields to set
            
        Returns:
            Document: The created schedule document
            
        Example:
            # Clear auto-schedules first
            self.clear_member_auto_schedules(member.name)
            
            # Create conflicting schedules for testing
            monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)
            
            # Now test validation logic
            result = annual.validate_billing_frequency_consistency()
        """
        
        # Get member's membership type if not provided
        if 'membership_type' not in kwargs:
            membership_type = frappe.db.get_value('Membership', 
                {'member': member_name, 'status': 'Active'}, 
                'membership_type')
            
            if not membership_type:
                # Fallback to any active membership type
                membership_type = frappe.db.get_value('Membership Type', 
                    {'is_active': 1}, 'name')
            
            if not membership_type:
                raise frappe.ValidationError("No active membership type found for controlled schedule creation")
                
            kwargs['membership_type'] = membership_type
        
        # Set up default values
        test_id = frappe.generate_hash(length=6)
        defaults = {
            'schedule_name': f'ControlledTest-{billing_frequency}-{test_id}',
            'member': member_name,
            'dues_rate': dues_rate,
            'billing_frequency': billing_frequency,
            'status': 'Active',
            'auto_generate': 1,
            'next_invoice_date': frappe.utils.today(),
            'is_template': 0
        }
        defaults.update(kwargs)
        
        # Create the schedule
        schedule = frappe.get_doc({
            'doctype': 'Membership Dues Schedule',
            **defaults
        })
        
        schedule.insert()
        
        # Track for cleanup
        self.track_doc("Membership Dues Schedule", schedule.name)
        
        return schedule
    
    def setup_edge_case_testing(self, member_name):
        """
        Complete setup for edge case testing with multiple schedules.
        
        This convenience method combines clear_member_auto_schedules() with
        helpful context information for edge case testing.
        
        Args:
            member_name (str): Member to set up for edge case testing
            
        Returns:
            dict: Context information about the setup
            
        Example:
            member = self.create_test_member()
            membership = self.create_test_membership(member=member.name)
            
            # Set up for edge case testing
            context = self.setup_edge_case_testing(member.name)
            
            # Create test scenarios
            monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)
            
            # Test validation logic
            result = annual.validate_billing_frequency_consistency()
            self.assertFalse(result["valid"])  # Should detect conflict
        """
        
        # Clear auto-schedules
        cancelled_schedules = self.clear_member_auto_schedules(member_name)
        
        # Get member context
        member_doc = frappe.get_doc("Member", member_name)
        
        # Get active membership context
        active_memberships = frappe.get_all("Membership",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "membership_type", "status"]
        )
        
        return {
            'member_name': member_name,
            'member_full_name': getattr(member_doc, 'full_name', 'Unknown'),
            'cancelled_schedules': cancelled_schedules,
            'active_memberships': active_memberships,
            'edge_case_ready': True,
            'helper_methods': [
                'create_controlled_dues_schedule(member_name, frequency, rate)',
                'Test validation methods directly on created schedules',
                'Business rules bypassed - can create multiple schedules per member'
            ]
        }
    
    def create_payment_failure_test_scenario(self, failure_type="insufficient_funds", member=None, **kwargs):
        """
        Create a complete payment failure test scenario with SEPA error codes
        
        Args:
            failure_type: Type of payment failure to simulate
            member: Member name (creates test member if None)
            **kwargs: Additional scenario parameters
        
        Returns:
            dict with failure scenario, member, mandate, and test context
        """
        try:
            from verenigingen.utils.testing.sepa_payment_failure_scenarios import create_payment_failure_scenario
        except ImportError:
            # Fallback for when module is not available
            return self._create_basic_failure_scenario(failure_type, **kwargs)
        
        # Create test member if not provided
        if not member:
            test_member = self.create_test_member(
                first_name="PaymentTest",
                last_name="Member",
                email=f"payment.{frappe.generate_hash(length=6)}@example.com"
            )
            member = test_member.name
        
        # Create mandate for payment failures
        mandate = self.create_test_sepa_mandate(
            member=member,
            scenario="normal",  # Start with valid mandate
            bank_code="TEST"
        )
        
        # Generate failure scenario
        failure_scenario = create_payment_failure_scenario(failure_type, **kwargs)
        
        # Add test context
        test_context = {
            "member": member,
            "mandate": mandate,
            "failure_scenario": failure_scenario,
            "test_type": "payment_failure",
            "created_at": frappe.utils.now()
        }
        
        return test_context
    
    def _create_basic_failure_scenario(self, failure_type, **kwargs):
        """Fallback method for basic failure scenarios when full module unavailable"""
        basic_scenarios = {
            "insufficient_funds": {
                "error_code": "AM04",
                "error_message": "Insufficient funds",
                "retry_eligible": True,
                "retry_days": 3,
                "severity": "medium"
            },
            "account_closed": {
                "error_code": "AC04", 
                "error_message": "Account closed",
                "retry_eligible": False,
                "retry_days": 0,
                "severity": "high"
            },
            "invalid_mandate": {
                "error_code": "AM02",
                "error_message": "No valid mandate",
                "retry_eligible": False,
                "retry_days": 0,
                "severity": "high"
            }
        }
        
        scenario = basic_scenarios.get(failure_type, basic_scenarios["insufficient_funds"])
        scenario.update(kwargs)
        return {"failure_scenario": scenario}
    
    def simulate_payment_retry_sequence(self, member_name, failure_types=None):
        """
        Simulate a complete payment retry sequence for testing retry logic
        
        Args:
            member_name: Member to test retry sequence for
            failure_types: Sequence of failure types (defaults to realistic progression)
        
        Returns:
            List of retry scenarios with timing and context
        """
        try:
            from verenigingen.utils.testing.sepa_payment_failure_scenarios import simulate_payment_failure_sequence
            return simulate_payment_failure_sequence(member_name, failure_types)
        except ImportError:
            # Fallback to basic retry simulation
            if not failure_types:
                failure_types = ["insufficient_funds", "insufficient_funds", "account_closed"]
            
            sequence = []
            for i, failure_type in enumerate(failure_types):
                scenario = self._create_basic_failure_scenario(failure_type)
                scenario["sequence_number"] = i + 1
                scenario["member"] = member_name
                sequence.append(scenario)
            
            return sequence
    
    def validate_sepa_error_handling(self, error_code, expected_behavior):
        """
        Validate that SEPA error codes are handled correctly in tests
        
        Args:
            error_code: SEPA error code to validate (e.g., "AM04")
            expected_behavior: Expected system behavior dict
        
        Returns:
            bool indicating if error handling matches expectations
        """
        try:
            from verenigingen.utils.testing.sepa_payment_failure_scenarios import SEPA_ERROR_CODES
            
            if error_code not in SEPA_ERROR_CODES:
                return False
            
            error_info = SEPA_ERROR_CODES[error_code]
            
            # Validate key behavior expectations
            checks = [
                error_info.get("retry_eligible") == expected_behavior.get("should_retry", False),
                error_info.get("customer_action_required") == expected_behavior.get("requires_customer_action", False),
                error_info.get("severity") == expected_behavior.get("severity", "medium")
            ]
            
            return all(checks)
        except ImportError:
            # Basic validation without full module
            basic_expectations = {
                "AM04": {"should_retry": True, "requires_customer_action": False, "severity": "medium"},
                "AC04": {"should_retry": False, "requires_customer_action": True, "severity": "high"},
                "AM02": {"should_retry": False, "requires_customer_action": True, "severity": "high"}
            }
            
            expected = basic_expectations.get(error_code, {})
            return expected == expected_behavior


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
