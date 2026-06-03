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
        """Generate a checksum-valid Dutch test IBAN.

        Delegates to the canonical generator (verenigingen.utils.validation.
        iban_validator.generate_test_iban) so the MOD-97 check digits are correct.
        The previous implementation concatenated a base + suffix without valid
        check digits, so every IBAN it produced failed the production validator.
        """
        from verenigingen.utils.validation.iban_validator import generate_test_iban as _generate

        if bank_bic:
            bank = next((b for b in self.dutch_banks if b["bic"] == bank_bic), None)
            bic = bank["bic"] if bank else self.dutch_banks[0]["bic"]
        else:
            bic = random.choice(self.dutch_banks)["bic"]

        bank_code = bic[:4]  # e.g. "INGBNL2A" -> "INGB" (all in the validator's bank set)
        # Unique 10-digit account number from the factory sequence
        seq = self.get_next_sequence("iban")
        return _generate(bank_code=bank_code, account_number=f"{seq:010d}")
    
    def generate_mandate_id(self) -> str:
        """Generate test mandate ID following Dutch conventions with timestamp uniqueness"""
        import time
        # Combine sequence with microsecond timestamp for uniqueness across factory instances
        seq = self.get_next_sequence('mandate')
        # Use last 3 digits of microseconds for sub-second uniqueness
        timestamp_suffix = int(time.time() * 1000) % 1000
        return f"TST{seq:03d}{timestamp_suffix:03d}"  # TST prefix with seq + timestamp
    
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
                                           payment_terms_template: str = "default",
                                           billing_frequency: str = "Monthly",
                                           dues_rate: float = 25.0,
                                           **kwargs) -> Document:
        """Create test membership dues schedule for SEPA testing

        Args:
            payment_terms_template: Payment terms template name. Use "default" for SEPA Direct Debit,
                                  None to omit the field, or a specific template name.
        """
        if not member:
            test_member = self.create_test_member()
            member = test_member.name

        # membership_type is mandatory on Membership Dues Schedule under v16; derive it
        # from the member's membership when the caller did not pass it explicitly.
        if "membership_type" not in kwargs:
            derived_type = frappe.db.get_value(
                "Membership", {"member": member, "docstatus": 1}, "membership_type"
            ) or frappe.db.get_value("Membership", {"member": member}, "membership_type")
            if derived_type:
                kwargs["membership_type"] = derived_type

        # Only set SEPA default if explicitly requested with "default"
        if payment_terms_template == "default":
            payment_terms_template = "SEPA Direct Debit"

        # The "SEPA Direct Debit" Payment Terms Template is a production master that
        # fresh test sites lack; get-or-create it so the schedule's link validates.
        if payment_terms_template == "SEPA Direct Debit":
            from verenigingen.tests.support.sepa_test_company import ensure_sepa_payment_terms_template

            ensure_sepa_payment_terms_template()

        # Validate required fields
        self.validate_field_exists("Membership Dues Schedule", "member")
        self.validate_field_exists("Membership Dues Schedule", "payment_terms_template")

        # Production enforces one active dues schedule per member; a Membership
        # created earlier in the test auto-creates one via after_insert. Inserting a
        # second active schedule raises "already has an active dues schedule", so
        # reuse the existing one and attach the requested payment terms instead.
        if kwargs.get("status", "Active") == "Active":
            existing = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member, "is_template": 0, "status": "Active"},
                "name",
            )
            if existing:
                schedule = frappe.get_doc("Membership Dues Schedule", existing)
                if payment_terms_template is not None:
                    schedule.payment_terms_template = payment_terms_template
                    schedule.save()
                return schedule

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule_data = {
            # schedule_name is the autoname (field:schedule_name), reqd + unique, and
            # is NOT auto-populated on a raw factory insert (only the production
            # create_from_template path generates it) -> set a unique default here.
            "schedule_name": f"TEST-DUES-{member}-{frappe.generate_hash(length=8)}",
            "member": member,
            "billing_frequency": billing_frequency,
            "dues_rate": dues_rate,
            "status": kwargs.get("status", "Active"),
            "auto_generate": kwargs.get("auto_generate", 1),
            "next_invoice_date": kwargs.get("next_invoice_date", today()),
            "contribution_mode": kwargs.get("contribution_mode", "Tier"),  # Valid options: Tier, Calculator, Custom
            **kwargs
        }

        # Only set payment_terms_template if not None
        if payment_terms_template is not None:
            schedule_data["payment_terms_template"] = payment_terms_template

        schedule.update(schedule_data)
        
        schedule.insert()
        return schedule
    
    def create_test_sales_invoice(self, customer: str = None, member: str = None,
                                membership: str = None, status: str = "Unpaid",
                                grand_total: float = 25.0, **kwargs) -> Document:
        """Create test sales invoice for SEPA batch processing"""
        # Pop control flags BEFORE they reach invoice.update(**kwargs): a `submit`
        # key would be set as a doc attribute, clobbering the submit() method
        # (invoice.submit() then raises "'bool' object is not callable").
        submit_flag = kwargs.pop("submit", False)

        if not customer:
            test_customer = self.create_test_customer()
            customer = test_customer.name
            
        # Validate required fields
        self.validate_field_exists("Sales Invoice", "customer")
        
        # get_party_account requires an explicit company (it does NOT consult Global
        # Defaults), and SEPA validation requires EUR -> use the EUR test company.
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        company = kwargs.pop("company", None) or get_eur_test_company()

        invoice = frappe.new_doc("Sales Invoice")
        invoice.update({
            "customer": customer,
            "company": company,
            "posting_date": kwargs.get("posting_date", today()),
            "due_date": kwargs.get("due_date", add_days(today(), 14)),
            "status": status,
            "currency": kwargs.get("currency", "EUR"),
            "grand_total": grand_total,
            "outstanding_amount": grand_total if status in ["Unpaid", "Overdue"] else 0,
            **kwargs
        })
        
        # Link the member via the real custom field ("member"); there is no
        # custom_member/custom_membership field on Sales Invoice. Use meta.has_field
        # (non-raising) rather than validate_field_exists (which throws on absence).
        si_meta = frappe.get_meta("Sales Invoice")
        if member and si_meta.has_field("member"):
            invoice.member = member

        if self.validate_field_exists("Sales Invoice", "membership_dues_schedule_display"):
            invoice.membership_dues_schedule_display = kwargs.get("membership_dues_schedule_display")
        
        # Add a simple item (get-or-create; fresh sites lack this Item)
        item_code = kwargs.get("item_code", "MEMBERSHIP-DUES")
        if not frappe.db.exists("Item", item_code):
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = "Membership Dues"
            item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            item.stock_uom = "Nos"
            item.is_stock_item = 0
            item.is_sales_item = 1
            item.insert(ignore_permissions=True)
        invoice.append("items", {
            "item_code": item_code,
            "item_name": "Membership Dues",
            "qty": 1,
            "rate": grand_total,
            "amount": grand_total
        })
        
        invoice.insert()
        if submit_flag:
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
            "memberships": [],
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
            
            # Reuse the Customer that create_test_member already auto-created and linked
            # (Customer.member is UNIQUE, so creating a second customer for the same
            # member would violate it). The Customer.member back-link is what
            # set_member_from_customer (Sales Invoice before_validate) reads to populate
            # invoice.member; without it the batch optimizer skips every invoice.
            customer_name = member.customer
            if not customer_name:
                customer_name = self.create_test_customer(
                    customer_name=f"Customer {member.full_name}"
                ).name
                member.db_set("customer", customer_name)
            frappe.db.set_value("Customer", customer_name, "member", member.name)
            
            # Create SEPA mandate
            mandate = self.create_test_sepa_mandate(member=member.name)
            
            # Create membership
            membership = self.create_test_membership(member=member.name)
            
            # Create dues schedule
            schedule = self.create_test_membership_dues_schedule(
                member=member.name,
                payment_terms_template="SEPA Direct Debit"
            )
            
            # Create invoice
            invoice = self.create_test_sales_invoice(
                customer=customer_name,
                member=member.name,
                membership=membership.name,
                membership_dues_schedule_display=schedule.name,
                submit=True
            )
            
            # Store in scenario data
            scenario_data["members"].append(member)
            scenario_data["mandates"].append(mandate)
            scenario_data["memberships"].append(membership)
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
            for i, (member, mandate, membership, invoice) in enumerate(zip(
                scenario_data["members"],
                scenario_data["mandates"],
                scenario_data["memberships"],
                scenario_data["invoices"]
            )):
                amount = 25.0
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
                    # First usage of a freshly-created mandate must be FRST; the SEPA
                    # sequence-type validation flags RCUR-on-first-use as a critical error.
                    "sequence_type": "FRST"
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