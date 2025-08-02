#!/usr/bin/env python3
"""
Payment History Test Data Factory for Scalability Testing
========================================================

This factory extends the StreamlinedTestDataFactory to create realistic payment 
scenarios for testing payment history system scalability. It generates:

- Members with diverse payment patterns
- Sales invoices with varying amounts and dates
- Payment entries with different methods and statuses
- SEPA mandates with realistic banking data
- Member payment history records spanning multiple months

Key Features:
- Realistic temporal distribution of payments
- Multiple payment methods (SEPA, bank transfer, cash)
- Failed payment scenarios and retries
- Bulk data creation optimized for performance testing
- Proper cleanup of large test datasets

Usage:
    factory = PaymentHistoryTestFactory()
    batch = factory.create_payment_history_batch(
        member_count=1000,
        months_history=6,
        avg_payments_per_month=2
    )
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import math

import frappe
from frappe.utils import add_days, add_months, random_string, today, flt, get_datetime

from verenigingen.tests.fixtures.test_data_factory import StreamlinedTestDataFactory


class PaymentHistoryTestFactory(StreamlinedTestDataFactory):
    """Extended factory for creating payment history test data at scale"""

    def __init__(self, cleanup_on_exit=True, seed=None):
        """Initialize with enhanced caching for payment scenarios"""
        super().__init__(cleanup_on_exit, seed)
        
        # Payment-specific caches
        self._test_companies = None
        self._test_accounts = None
        self._payment_methods = None
        self._invoice_items = None
        
        # Performance tracking
        self.performance_metrics = {
            "member_creation_time": 0,
            "invoice_creation_time": 0,
            "payment_creation_time": 0,
            "total_records_created": 0
        }

    def create_payment_history_batch(
        self, 
        member_count: int = 100,
        months_history: int = 6,
        avg_payments_per_month: float = 1.5,
        payment_methods_distribution: Dict[str, float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a comprehensive payment history test batch
        
        Args:
            member_count: Number of members to create
            months_history: How many months of payment history to generate
            avg_payments_per_month: Average payments per member per month
            payment_methods_distribution: Distribution of payment methods
            
        Returns:
            Dictionary containing all created test data and metrics
        """
        print(f"🏗️ Creating payment history batch: {member_count} members, {months_history} months")
        
        start_time = datetime.now()
        
        # Default payment method distribution
        if payment_methods_distribution is None:
            payment_methods_distribution = {
                "SEPA Direct Debit": 0.70,  # 70% SEPA
                "Bank Transfer": 0.25,      # 25% manual transfers
                "Cash": 0.05                # 5% cash payments
            }
        
        # Phase 1: Create supporting infrastructure
        self._ensure_payment_infrastructure()
        
        # Phase 2: Create members with realistic profiles
        members = self._create_payment_test_members(member_count)
        print(f"✅ Created {len(members)} members")
        
        # Phase 3: Create SEPA mandates for SEPA-enabled members
        sepa_member_count = int(member_count * payment_methods_distribution.get("SEPA Direct Debit", 0.7))
        sepa_mandates = self._create_sepa_mandates_for_members(members[:sepa_member_count])
        print(f"✅ Created {len(sepa_mandates)} SEPA mandates")
        
        # Phase 4: Generate payment history
        payment_data = self._generate_payment_history(
            members,
            months_history,
            avg_payments_per_month,
            payment_methods_distribution
        )
        print(f"✅ Generated payment history: {payment_data['total_invoices']} invoices, {payment_data['total_payments']} payments")
        
        # Phase 5: Create member payment history records
        history_records = self._create_member_payment_history_records(members)
        print(f"✅ Created {len(history_records)} payment history records")
        
        end_time = datetime.now()
        creation_time = (end_time - start_time).total_seconds()
        
        # Compile results with comprehensive metrics
        result = {
            "members": members,
            "sepa_mandates": sepa_mandates,
            "invoices": payment_data["invoices"],
            "payments": payment_data["payments"],
            "payment_history_records": history_records,
            "metrics": {
                "creation_time_seconds": creation_time,
                "members_per_second": member_count / creation_time if creation_time > 0 else 0,
                "total_records": (
                    len(members) + len(sepa_mandates) + 
                    payment_data["total_invoices"] + payment_data["total_payments"] +
                    len(history_records)
                ),
                "member_count": len(members),
                "sepa_mandate_count": len(sepa_mandates),
                "invoice_count": payment_data["total_invoices"],
                "payment_count": payment_data["total_payments"],
                "history_record_count": len(history_records),
                "months_covered": months_history,
                "avg_payments_per_member": payment_data["total_payments"] / len(members) if members else 0
            },
            "test_configuration": {
                "member_count": member_count,
                "months_history": months_history,
                "avg_payments_per_month": avg_payments_per_month,
                "payment_methods_distribution": payment_methods_distribution
            }
        }
        
        print(f"🎯 Batch creation completed in {creation_time:.2f}s")
        print(f"📊 Performance: {result['metrics']['members_per_second']:.1f} members/second")
        
        return result

    def _ensure_payment_infrastructure(self):
        """Ensure all required payment infrastructure exists"""
        # Ensure test company exists
        if not self._test_companies:
            self._test_companies = self._get_or_create_test_companies()
        
        # Ensure payment accounts exist
        if not self._test_accounts:
            self._test_accounts = self._get_or_create_test_accounts()
            
        # Ensure payment methods exist
        if not self._payment_methods:
            self._payment_methods = self._get_or_create_payment_methods()
            
        # Ensure test items exist
        if not self._invoice_items:
            self._invoice_items = self._get_or_create_invoice_items()

    def _get_or_create_test_companies(self) -> List[str]:
        """Get or create test companies for payment processing"""
        companies = frappe.get_all("Company", filters={"company_name": ["like", "Test%"]}, pluck="name")
        
        if not companies:
            # Create a test company
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": f"Test Company {self.test_run_id}",
                "default_currency": "EUR",
                "country": "Netherlands"
            })
            company.insert(ignore_permissions=True)
            self.track_doc("Company", company.name)
            companies = [company.name]
            
        return companies

    def _get_or_create_test_accounts(self) -> Dict[str, str]:
        """Get or create test accounts for payment processing"""
        company = self._test_companies[0]
        accounts = {}
        
        # Find or create receivable account
        receivable = frappe.db.get_value("Account", {
            "company": company,
            "account_type": "Receivable",
            "is_group": 0
        })
        
        if not receivable:
            receivable = self._create_test_account(
                company, "Test Receivables", "Receivable", "Asset"
            )
            
        accounts["receivable"] = receivable
        
        # Find or create cash account
        cash = frappe.db.get_value("Account", {
            "company": company,
            "account_type": "Cash",
            "is_group": 0
        })
        
        if not cash:
            cash = self._create_test_account(
                company, "Test Cash Account", "Cash", "Asset"
            )
            
        accounts["cash"] = cash
        
        return accounts

    def _create_test_account(self, company: str, account_name: str, account_type: str, root_type: str) -> str:
        """Create a test account"""
        account = frappe.get_doc({
            "doctype": "Account",
            "account_name": account_name,
            "company": company,
            "account_type": account_type,
            "root_type": root_type,
            "is_group": 0
        })
        account.insert(ignore_permissions=True)
        self.track_doc("Account", account.name)
        return account.name

    def _get_or_create_payment_methods(self) -> List[str]:
        """Get or create payment methods"""
        methods = ["SEPA Direct Debit", "Bank Transfer", "Cash"]
        existing_methods = []
        
        for method in methods:
            if frappe.db.exists("Mode of Payment", method):
                existing_methods.append(method)
            else:
                # Create the payment method
                payment_method = frappe.get_doc({
                    "doctype": "Mode of Payment",
                    "mode_of_payment": method,
                    "type": "Bank" if method != "Cash" else "Cash",
                    "enabled": 1
                })
                payment_method.insert(ignore_permissions=True)
                self.track_doc("Mode of Payment", payment_method.name)
                existing_methods.append(method)
                
        return existing_methods

    def _get_or_create_invoice_items(self) -> List[str]:
        """Get or create items for invoicing"""
        items = ["Membership Fee", "Donation", "Event Fee"]
        existing_items = []
        
        for item_name in items:
            item_code = item_name.replace(" ", "_").upper()
            
            if frappe.db.exists("Item", item_code):
                existing_items.append(item_code)
            else:
                # Create the item
                item = frappe.get_doc({
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": item_name,
                    "item_group": "Services",
                    "is_sales_item": 1,
                    "is_service_item": 1,
                    "is_stock_item": 0,
                    "standard_rate": 25.0
                })
                item.insert(ignore_permissions=True)
                self.track_doc("Item", item.name)
                existing_items.append(item_code)
                
        return existing_items

    def _create_payment_test_members(self, count: int) -> List[Any]:
        """Create members optimized for payment testing"""
        members = []
        
        for i in range(count):
            # Create member with realistic payment profile
            member = self.create_test_member(
                first_name=f"PayTest{i:04d}",
                last_name="Member",
                email=f"paytest{i:04d}@example.com",
                member_since=add_days(today(), -random.randint(30, 1095)),  # Member 1 month to 3 years
                status="Active"
            )
            
            # Ensure member has customer record for payments
            if not member.customer:
                customer = frappe.get_doc({
                    "doctype": "Customer",
                    "customer_name": f"{member.first_name} {member.last_name}",
                    "customer_type": "Individual",
                    "member": member.name
                })
                customer.insert(ignore_permissions=True)
                self.track_doc("Customer", customer.name)
                
                member.customer = customer.name
                member.save(ignore_permissions=True)
            
            members.append(member)
            
        return members

    def _create_sepa_mandates_for_members(self, members: List[Any]) -> List[Any]:
        """Create SEPA mandates for specified members"""
        mandates = []
        
        for member in members:
            mandate = self.create_test_sepa_mandate(
                member=member.name,
                scenario="normal",
                bank_code="TEST"
            )
            mandates.append(mandate)
            
        return mandates

    def _generate_payment_history(
        self,
        members: List[Any],
        months_history: int,
        avg_payments_per_month: float,
        payment_methods_distribution: Dict[str, float]
    ) -> Dict[str, Any]:
        """Generate realistic payment history for members"""
        invoices = []
        payments = []
        
        # Calculate start date for history
        history_start_date = add_months(today(), -months_history)
        
        for member in members:
            # Determine payment pattern for this member
            member_monthly_payments = max(1, int(random.gauss(avg_payments_per_month, 0.5)))
            
            # Generate payments for each month
            for month_offset in range(months_history):
                month_start = add_months(history_start_date, month_offset)
                
                # Create payments for this month
                for payment_num in range(member_monthly_payments):
                    # Random date within the month
                    payment_date = add_days(month_start, random.randint(1, 28))
                    
                    # Create invoice
                    invoice = self._create_test_invoice(member, payment_date)
                    invoices.append(invoice)
                    
                    # Determine payment method based on distribution
                    payment_method = self._select_payment_method(payment_methods_distribution)
                    
                    # Create payment (90% success rate)
                    if random.random() < 0.9:
                        payment = self._create_test_payment(
                            member, invoice, payment_date, payment_method
                        )
                        payments.append(payment)
        
        return {
            "invoices": invoices,
            "payments": payments,
            "total_invoices": len(invoices),
            "total_payments": len(payments)
        }

    def _create_test_invoice(self, member: Any, invoice_date: str) -> Any:
        """Create a test sales invoice for member"""
        company = self._test_companies[0]
        item_code = random.choice(self._invoice_items)
        amount = round(random.uniform(15.0, 150.0), 2)
        
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": member.customer,
            "posting_date": invoice_date,
            "due_date": add_days(invoice_date, 30),
            "company": company,
            "is_membership_invoice": 1,
            "items": [{
                "item_code": item_code,
                "qty": 1,
                "rate": amount,
                "amount": amount
            }]
        })
        
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        return invoice

    def _create_test_payment(
        self, 
        member: Any, 
        invoice: Any, 
        payment_date: str,
        payment_method: str
    ) -> Any:
        """Create a test payment entry"""
        company = self._test_companies[0]
        
        payment = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": member.customer,
            "posting_date": payment_date,
            "paid_amount": invoice.grand_total,
            "received_amount": invoice.grand_total,
            "mode_of_payment": payment_method,
            "company": company,
            "paid_from": self._test_accounts["receivable"],
            "paid_to": self._test_accounts["cash"],
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "allocated_amount": invoice.grand_total
            }]
        })
        
        payment.insert(ignore_permissions=True)
        payment.submit()
        self.track_doc("Payment Entry", payment.name)
        
        return payment

    def _select_payment_method(self, distribution: Dict[str, float]) -> str:
        """Select payment method based on distribution"""
        rand = random.random()
        cumulative = 0
        
        for method, probability in distribution.items():
            cumulative += probability
            if rand <= cumulative:
                return method
                
        # Fallback
        return list(distribution.keys())[0]

    def _create_member_payment_history_records(self, members: List[Any]) -> List[Any]:
        """Create member payment history records by triggering the update mechanism"""
        history_records = []
        
        print("🔄 Updating member payment histories...")
        
        for i, member in enumerate(members):
            try:
                # Trigger payment history update
                member_doc = frappe.get_doc("Member", member.name)
                member_doc.load_payment_history()
                member_doc.save(ignore_permissions=True)
                
                # Get the created history records
                member_history = frappe.get_all(
                    "Member Payment History",
                    filters={"parent": member.name},
                    fields=["name"]
                )
                
                history_records.extend([record.name for record in member_history])
                
                # Progress indicator
                if (i + 1) % 100 == 0:
                    print(f"  Processed {i + 1}/{len(members)} members")
                    
            except Exception as e:
                frappe.log_error(f"Failed to update payment history for member {member.name}: {str(e)}")
                continue
        
        return history_records

    def create_payment_stress_test_scenario(
        self, 
        scale: str = "medium",
        **kwargs
    ) -> Dict[str, Any]:
        """Create payment-focused stress test scenarios"""
        
        scale_configs = {
            "small": {
                "member_count": 100,
                "months_history": 3,
                "avg_payments_per_month": 1.2
            },
            "medium": {
                "member_count": 500,
                "months_history": 6,
                "avg_payments_per_month": 1.5
            },
            "large": {
                "member_count": 1000,
                "months_history": 12,
                "avg_payments_per_month": 2.0
            },
            "xlarge": {
                "member_count": 2500,
                "months_history": 12,
                "avg_payments_per_month": 2.5
            },
            "xxlarge": {
                "member_count": 5000,
                "months_history": 12,
                "avg_payments_per_month": 3.0
            }
        }
        
        config = scale_configs.get(scale, scale_configs["medium"])
        config.update(kwargs)
        
        print(f"🏋️ Creating {scale} payment stress test scenario")
        
        return self.create_payment_history_batch(**config)

    def create_failed_payment_scenario(
        self,
        member_count: int = 50,
        failure_rate: float = 0.3
    ) -> Dict[str, Any]:
        """Create scenario with payment failures for retry testing"""
        
        # Create base payment scenario
        scenario = self.create_payment_history_batch(
            member_count=member_count,
            months_history=3,
            avg_payments_per_month=2.0
        )
        
        # Randomly mark some payments as failed
        failed_payments = []
        total_payments = len(scenario["payments"])
        failure_count = int(total_payments * failure_rate)
        
        failed_payment_indices = random.sample(range(total_payments), failure_count)
        
        for idx in failed_payment_indices:
            payment = scenario["payments"][idx]
            # Cancel the payment to simulate failure
            payment_doc = frappe.get_doc("Payment Entry", payment.name)
            payment_doc.cancel()
            failed_payments.append(payment)
        
        scenario["failed_payments"] = failed_payments
        scenario["failure_metrics"] = {
            "total_payments": total_payments,
            "failed_payments": len(failed_payments),
            "failure_rate": len(failed_payments) / total_payments if total_payments > 0 else 0
        }
        
        return scenario

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary"""
        return {
            "factory_performance": self.performance_metrics,
            "total_records_tracked": len(self.created_records),
            "memory_usage_estimate_mb": len(self.created_records) * 0.001,  # Rough estimate
            "cleanup_complexity": len(self.created_records)
        }