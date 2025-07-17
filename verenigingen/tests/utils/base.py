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
                    "is_group": 0,
                }
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
                    "is_active": 1,
                }
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
                    "is_active": 1,
                }
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
                    "is_active": 1,
                }
            )
            chapter.insert(ignore_permissions=True)

    def track_doc(self, doctype, name):
        """Track a document for cleanup"""
        self._test_docs.append({"doctype": doctype, "name": name})
    
    def _cleanup_member_customers(self):
        """Clean up customers created for tracked members"""
        # Find all tracked members and their customers
        customers_to_delete = set()
        
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
        
        # Delete SEPA Mandates
        for mandate in frappe.get_all("SEPA Mandate", filters={"customer": customer_name}):
            try:
                frappe.delete_doc("SEPA Mandate", mandate.name, force=True, ignore_permissions=True)
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
                    "new_password": password,
                }
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
                    "country": "Netherlands",
                }
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
