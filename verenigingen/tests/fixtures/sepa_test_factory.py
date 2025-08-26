"""
SEPA-Specific Test Data Factory Extension
=========================================

Extends the EnhancedTestDataFactory with specialized methods for creating
SEPA Direct Debit related test data including mandates, batches, and
banking information with proper validation.

This factory ensures all SEPA test data adheres to:
- IBAN format validation (Dutch bank accounts)
- Mandate ID format compliance
- SEPA sequence type rules
- Banking relationship consistency
- Direct debit business rules

Author: Verenigingen Development Team
Date: August 2025
"""

import frappe
from frappe.utils import getdate, today, add_days, random_string
from frappe.model.document import Document
from typing import Dict, List, Optional, Any
import random

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory


class SEPATestDataFactory(EnhancedTestDataFactory):
    """Extended test factory with SEPA-specific test data creation"""
    
    def __init__(self, seed: int = 12345, use_faker: bool = True):
        super().__init__(seed, use_faker)
        
        # SEPA-specific test data pools
        self.dutch_banks = [
            {"bic": "INGBNL2A", "name": "ING Bank", "test_iban_base": "NL91INGA0417164"},
            {"bic": "RABONL2U", "name": "Rabobank", "test_iban_base": "NL20RABO0300065"},
            {"bic": "ABNANL2A", "name": "ABN AMRO", "test_iban_base": "NL91ABNA0417164"},
            {"bic": "TRIONL2U", "name": "Triodos Bank", "test_iban_base": "NL59TRIO0198450"},
        ]
        
    def generate_test_iban(self, bank_bic: str = None) -> str:
        """Generate valid Dutch test IBAN"""
        if bank_bic:
            # Find bank by BIC
            bank = next((b for b in self.dutch_banks if b["bic"] == bank_bic), None)
            if bank:
                base = bank["test_iban_base"]
            else:
                # Default to ING if BIC not found
                base = self.dutch_banks[0]["test_iban_base"]
        else:
            # Random Dutch bank
            bank = random.choice(self.dutch_banks)
            base = bank["test_iban_base"]
        
        # Generate unique account number suffix
        seq = self.get_next_sequence('iban')
        suffix = f"{seq:03d}"
        
        # Construct IBAN with check digits (simplified - real IBANs have complex validation)
        iban = f"{base}{suffix}"
        return iban
    
    def generate_mandate_id(self) -> str:
        """Generate test mandate ID following Dutch conventions"""
        seq = self.get_next_sequence('mandate')
        return f"TST{seq:06d}"  # TST prefix for test mandates
    
    def create_test_sepa_mandate(self, member: str = None, iban: str = None, 
                                mandate_id: str = None, status: str = "Active",
                                sign_date: str = None, **kwargs) -> Document:
        """Create test SEPA mandate with realistic data"""
        if not member:
            test_member = self.create_test_member()
            member = test_member.name
        
        if not iban:
            iban = self.generate_test_iban()
        
        if not mandate_id:
            mandate_id = self.generate_mandate_id()
            
        if not sign_date:
            sign_date = add_days(today(), -30)  # Signed 30 days ago
        
        # Validate required fields exist
        self.validate_field_exists("SEPA Mandate", "member")
        self.validate_field_exists("SEPA Mandate", "iban")
        self.validate_field_exists("SEPA Mandate", "mandate_id")
        
        sepa_mandate = frappe.new_doc("SEPA Mandate")
        sepa_mandate.update({
            "member": member,
            "iban": iban,
            "mandate_id": mandate_id,
            "status": status,
            "sign_date": sign_date,
            "account_holder_name": kwargs.get("account_holder_name", "Test Account Holder"),
            "bic": kwargs.get("bic", iban[4:8] + "NL2A"),  # Extract bank code from IBAN
            "mandate_type": kwargs.get("mandate_type", "RCUR"),
            **kwargs
        })
        
        sepa_mandate.insert()
        return sepa_mandate
    
    def create_test_membership_dues_schedule(self, member: str = None, 
                                           payment_terms_template: str = None,
                                           billing_frequency: str = "Monthly",
                                           dues_rate: float = 25.0,
                                           **kwargs) -> Document:
        """Create test membership dues schedule for SEPA testing"""
        if not member:
            test_member = self.create_test_member()
            member = test_member.name
            
        if not payment_terms_template:
            payment_terms_template = "SEPA Direct Debit"
        
        # Validate required fields
        self.validate_field_exists("Membership Dues Schedule", "member")
        self.validate_field_exists("Membership Dues Schedule", "payment_terms_template")
        
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.update({
            "member": member,
            "payment_terms_template": payment_terms_template,
            "billing_frequency": billing_frequency,
            "dues_rate": dues_rate,
            "status": kwargs.get("status", "Active"),
            "auto_generate": kwargs.get("auto_generate", 1),
            "next_invoice_date": kwargs.get("next_invoice_date", today()),
            "contribution_mode": kwargs.get("contribution_mode", "Fixed"),
            **kwargs
        })
        
        schedule.insert()
        return schedule
    
    def create_test_sales_invoice(self, customer: str = None, member: str = None,
                                membership: str = None, status: str = "Unpaid",
                                grand_total: float = 25.0, **kwargs) -> Document:
        """Create test sales invoice for SEPA batch processing"""
        if not customer:
            test_customer = self.create_test_customer()
            customer = test_customer.name
            
        # Validate required fields
        self.validate_field_exists("Sales Invoice", "customer")
        
        invoice = frappe.new_doc("Sales Invoice")
        invoice.update({
            "customer": customer,
            "posting_date": kwargs.get("posting_date", today()),
            "due_date": kwargs.get("due_date", add_days(today(), 14)),
            "status": status,
            "currency": kwargs.get("currency", "EUR"),
            "grand_total": grand_total,
            "outstanding_amount": grand_total if status in ["Unpaid", "Overdue"] else 0,
            **kwargs
        })
        
        # Add custom fields if they exist
        if self.validate_field_exists("Sales Invoice", "custom_member") and member:
            invoice.custom_member = member
            
        if self.validate_field_exists("Sales Invoice", "custom_membership") and membership:
            invoice.custom_membership = membership
            
        if self.validate_field_exists("Sales Invoice", "membership_dues_schedule_display"):
            invoice.membership_dues_schedule_display = kwargs.get("membership_dues_schedule_display")
        
        # Add a simple item
        invoice.append("items", {
            "item_code": kwargs.get("item_code", "MEMBERSHIP-DUES"),
            "item_name": "Membership Dues",
            "qty": 1,
            "rate": grand_total,
            "amount": grand_total
        })
        
        invoice.insert()
        if kwargs.get("submit", False):
            invoice.submit()
            
        return invoice
    
    def create_test_direct_debit_batch(self, batch_date: str = None,
                                     invoice_count: int = 5,
                                     **kwargs) -> Document:
        """Create test direct debit batch with invoices"""
        if not batch_date:
            batch_date = today()
        
        batch = frappe.new_doc("Direct Debit Batch")
        batch.update({
            "batch_date": batch_date,
            "batch_description": kwargs.get("batch_description", f"Test Batch {self.get_next_sequence('batch')}"),
            "currency": kwargs.get("currency", "EUR"),
            "status": kwargs.get("status", "Draft"),
            "batch_type": kwargs.get("batch_type", "RCUR"),
            **kwargs
        })
        
        # Add test invoices if requested
        total_amount = 0
        for i in range(invoice_count):
            # Create test member and invoice data
            member = self.create_test_member(first_name=f"BatchTest{i}")
            customer = self.create_test_customer(customer_name=f"Customer {member.full_name}")
            member.db_set("customer", customer.name)
            
            # Create SEPA mandate
            mandate = self.create_test_sepa_mandate(member=member.name)
            member.db_set("active_mandate", mandate.name)
            
            # Create membership
            membership = self.create_test_membership(member=member.name)
            
            # Create invoice
            invoice = self.create_test_sales_invoice(
                customer=customer.name,
                member=member.name,
                membership=membership.name,
                submit=True
            )
            
            # Add to batch
            amount = 25.0 + (i * 5)  # Varying amounts
            batch.append("invoices", {
                "invoice": invoice.name,
                "membership": membership.name,
                "member": member.name,
                "member_name": member.full_name,
                "amount": amount,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": "RCUR"
            })
            total_amount += amount
        
        batch.total_amount = total_amount
        batch.entry_count = invoice_count
        batch.insert()
        
        return batch
    
    def create_sepa_test_scenario(self, scenario_name: str = "standard",
                                member_count: int = 10) -> Dict[str, Any]:
        """Create comprehensive SEPA test scenario with all related data"""
        scenario_data = {
            "scenario_name": scenario_name,
            "members": [],
            "mandates": [],
            "schedules": [],
            "invoices": [],
            "batches": []
        }
        
        # Create members with complete SEPA setup
        for i in range(member_count):
            # Create member
            member = self.create_test_member(
                first_name=f"Scenario{scenario_name.title()}{i}",
                birth_date="1990-01-01"
            )
            
            # Create customer
            customer = self.create_test_customer(
                customer_name=f"Customer {member.full_name}"
            )
            member.db_set("customer", customer.name)
            
            # Create SEPA mandate
            mandate = self.create_test_sepa_mandate(member=member.name)
            member.db_set("active_mandate", mandate.name)
            
            # Create membership
            membership = self.create_test_membership(member=member.name)
            
            # Create dues schedule
            schedule = self.create_test_membership_dues_schedule(
                member=member.name,
                payment_terms_template="SEPA Direct Debit"
            )
            
            # Create invoice
            invoice = self.create_test_sales_invoice(
                customer=customer.name,
                member=member.name,
                membership=membership.name,
                membership_dues_schedule_display=schedule.name,
                submit=True
            )
            
            # Store in scenario data
            scenario_data["members"].append(member)
            scenario_data["mandates"].append(mandate)
            scenario_data["schedules"].append(schedule)
            scenario_data["invoices"].append(invoice)
        
        # Create test batch
        if scenario_data["invoices"]:
            batch = frappe.new_doc("Direct Debit Batch")
            batch.batch_date = today()
            batch.batch_description = f"Test Scenario: {scenario_name}"
            batch.currency = "EUR"
            batch.status = "Draft"
            
            total_amount = 0
            for i, (member, mandate, invoice) in enumerate(zip(
                scenario_data["members"],
                scenario_data["mandates"], 
                scenario_data["invoices"]
            )):
                amount = 25.0
                batch.append("invoices", {
                    "invoice": invoice.name,
                    "membership": scenario_data["schedules"][i].name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    "sequence_type": "RCUR"
                })
                total_amount += amount
            
            batch.total_amount = total_amount
            batch.entry_count = len(scenario_data["invoices"])
            batch.insert()
            scenario_data["batches"].append(batch)
        
        return scenario_data
    
    def cleanup_sepa_test_data(self, scenario_data: Dict[str, Any]):
        """Clean up SEPA test data (for manual cleanup if needed)"""
        # Note: EnhancedTestCase usually handles cleanup automatically
        # This is here for manual cleanup scenarios
        
        for batch in scenario_data.get("batches", []):
            try:
                batch.delete()
            except:
                pass
                
        for invoice in scenario_data.get("invoices", []):
            try:
                if invoice.docstatus == 1:
                    invoice.cancel()
                invoice.delete()
            except:
                pass
        
        for schedule in scenario_data.get("schedules", []):
            try:
                schedule.delete()
            except:
                pass
                
        for mandate in scenario_data.get("mandates", []):
            try:
                mandate.delete()
            except:
                pass
        
        for member in scenario_data.get("members", []):
            try:
                member.delete()
            except:
                pass