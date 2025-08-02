#!/usr/bin/env python3
"""
Payment History Scalability Test Data Factory
==============================================

Specialized test data factory optimized for payment history scalability testing.
Builds on StreamlinedTestDataFactory with enhanced capabilities for creating
realistic payment scenarios at scale.

Features:
- Deterministic payment history generation with configurable patterns
- Realistic payment failure and retry scenarios
- SEPA mandate integration with various states
- Bulk data generation optimized for performance
- Payment reconciliation and unreconciled payment scenarios
- Multi-frequency billing patterns (Monthly, Quarterly, Annual)
- Edge case scenario generation (missing customers, failed payments, etc.)

Usage:
    factory = PaymentHistoryTestDataFactory(seed=42)
    
    # Create single member with payment history
    member_data = factory.create_member_with_payment_history(
        payment_months=12,
        payment_frequency="Monthly",
        failure_rate=0.1
    )
    
    # Create bulk members for scalability testing
    members_data = factory.create_bulk_members_with_histories(
        member_count=1000,
        max_payment_months=24
    )
"""

import random
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple

import frappe
from frappe.utils import add_days, add_months, today, flt, random_string

from verenigingen.tests.fixtures.test_data_factory import StreamlinedTestDataFactory


class PaymentHistoryTestDataFactory(StreamlinedTestDataFactory):
    """Enhanced test data factory for payment history scalability testing"""
    
    def __init__(self, cleanup_on_exit=True, seed=None):
        """Initialize with enhanced configuration for payment history testing"""
        super().__init__(cleanup_on_exit=cleanup_on_exit, seed=seed)
        
        # Payment pattern configurations
        self.payment_patterns = {
            "Monthly": {"interval_months": 1, "variance_days": 3},
            "Quarterly": {"interval_months": 3, "variance_days": 7},
            "Semi-Annual": {"interval_months": 6, "variance_days": 14},
            "Annual": {"interval_months": 12, "variance_days": 30}
        }
        
        # Payment failure scenarios
        self.failure_scenarios = [
            {"code": "AM04", "description": "Insufficient funds", "retry_eligible": True},
            {"code": "AC04", "description": "Account closed", "retry_eligible": False},
            {"code": "AM02", "description": "No valid mandate", "retry_eligible": False},
            {"code": "MS02", "description": "Bank system error", "retry_eligible": True},
            {"code": "AG01", "description": "Transaction forbidden", "retry_eligible": False}
        ]
        
        # Member payment behavior profiles
        self.payment_profiles = {
            "reliable": {"on_time_rate": 0.95, "failure_rate": 0.02, "retry_success_rate": 0.9},
            "typical": {"on_time_rate": 0.80, "failure_rate": 0.10, "retry_success_rate": 0.7},
            "problematic": {"on_time_rate": 0.60, "failure_rate": 0.25, "retry_success_rate": 0.5},
            "sporadic": {"on_time_rate": 0.40, "failure_rate": 0.35, "retry_success_rate": 0.3}
        }
        
    def create_member_with_payment_history(self, 
                                         payment_months: int = 12,
                                         payment_frequency: str = "Monthly",
                                         payment_profile: str = "typical",
                                         include_sepa_mandate: bool = True,
                                         include_unreconciled: bool = False,
                                         membership_type_override: Dict = None) -> Dict[str, Any]:
        """
        Create a member with comprehensive payment history
        
        Args:
            payment_months: Number of months of payment history to generate
            payment_frequency: Billing frequency (Monthly, Quarterly, Semi-Annual, Annual)
            payment_profile: Payment behavior profile (reliable, typical, problematic, sporadic)
            include_sepa_mandate: Whether to create SEPA mandate
            include_unreconciled: Whether to include unreconciled payments
            membership_type_override: Override membership type configuration
            
        Returns:
            Dictionary containing all created documents and metadata
        """
        
        # Create core member and membership
        member = self.create_test_member()
        
        membership_type_config = membership_type_override or {
            "amount": random.uniform(25.0, 150.0),
            "billing_frequency": payment_frequency
        }
        
        membership_type = self.create_test_membership_type(**membership_type_config)
        membership = self.create_test_membership(
            member=member,
            membership_type=membership_type
        )
        
        # Create SEPA mandate if requested
        sepa_mandate = None
        if include_sepa_mandate:
            mandate_status = random.choice(["Active", "Suspended", "Expired"]) if random.random() < 0.1 else "Active"
            sepa_mandate = self.create_test_sepa_mandate(
                member=member,
                status=mandate_status
            )
        
        # Generate payment history based on profile and frequency
        payment_data = self._generate_payment_history(
            member=member,
            membership=membership,
            sepa_mandate=sepa_mandate,
            payment_months=payment_months,
            payment_frequency=payment_frequency,
            payment_profile=payment_profile
        )
        
        # Add unreconciled payments if requested
        unreconciled_payments = []
        if include_unreconciled:
            unreconciled_count = random.randint(1, 3)
            for _ in range(unreconciled_count):
                unreconciled_payment = self._create_unreconciled_payment(member)
                unreconciled_payments.append(unreconciled_payment)
        
        return {
            "member": member,
            "membership": membership,
            "membership_type": membership_type,
            "sepa_mandate": sepa_mandate,
            "invoices": payment_data["invoices"],
            "payments": payment_data["payments"],
            "failed_payments": payment_data["failed_payments"],
            "unreconciled_payments": unreconciled_payments,
            "payment_months": payment_months,
            "payment_frequency": payment_frequency,
            "payment_profile": payment_profile,
            "statistics": self._calculate_payment_statistics(payment_data)
        }
    
    def create_bulk_members_with_histories(self, 
                                         member_count: int,
                                         max_payment_months: int = 12,
                                         distribution_config: Dict = None) -> List[Dict[str, Any]]:
        """
        Create multiple members with varied payment histories for scalability testing
        
        Args:
            member_count: Number of members to create
            max_payment_months: Maximum months of payment history
            distribution_config: Configuration for distributing member characteristics
            
        Returns:
            List of member data dictionaries
        """
        
        print(f"🏭 Creating {member_count} members with payment histories...")
        
        # Default distribution configuration
        default_distribution = {
            "payment_profiles": {
                "reliable": 0.40,    # 40% reliable payers
                "typical": 0.40,     # 40% typical payers  
                "problematic": 0.15, # 15% problematic payers
                "sporadic": 0.05     # 5% sporadic payers
            },
            "payment_frequencies": {
                "Monthly": 0.70,     # 70% monthly billing
                "Quarterly": 0.20,   # 20% quarterly billing
                "Semi-Annual": 0.07, # 7% semi-annual billing
                "Annual": 0.03       # 3% annual billing
            },
            "sepa_mandate_rate": 0.75,    # 75% have SEPA mandates
            "unreconciled_rate": 0.30     # 30% have unreconciled payments
        }
        
        config = distribution_config or default_distribution
        
        members_data = []
        batch_size = 100
        
        for batch_start in range(0, member_count, batch_size):
            batch_end = min(batch_start + batch_size, member_count)
            batch_size_actual = batch_end - batch_start
            
            print(f"  Processing batch {batch_start + 1}-{batch_end}...")
            
            batch_data = self._create_member_batch(
                batch_start=batch_start,
                batch_size=batch_size_actual,
                max_payment_months=max_payment_months,
                config=config
            )
            
            members_data.extend(batch_data)
            
            # Memory management - commit and cleanup every batch
            frappe.db.commit()
            
        print(f"✅ Created {len(members_data)} members with payment histories")
        return members_data
    
    def create_edge_case_payment_scenarios(self) -> Dict[str, List[Dict[str, Any]]]:
        """Create specific edge case scenarios for testing robustness"""
        
        edge_cases = {}
        
        # 1. Members with missing customer records
        print("Creating edge case: Missing customer records...")
        missing_customers = []
        for i in range(10):
            member = self.create_test_member()
            # Remove customer reference to simulate edge case
            original_customer = member.customer
            member.customer = None
            member.save()
            
            missing_customers.append({
                "member": member,
                "original_customer": original_customer,
                "scenario": "missing_customer"
            })
        edge_cases["missing_customers"] = missing_customers
        
        # 2. Members with corrupted payment history
        print("Creating edge case: Corrupted payment data...")
        corrupted_data = []
        for i in range(5):
            member_data = self.create_member_with_payment_history(
                payment_months=6,
                payment_profile="typical"
            )
            
            # Simulate data corruption by creating invalid references
            corrupted_invoice = self._create_corrupted_invoice(member_data["member"])
            
            corrupted_data.append({
                **member_data,
                "corrupted_invoice": corrupted_invoice,
                "scenario": "corrupted_data"
            })
        edge_cases["corrupted_data"] = corrupted_data
        
        # 3. Members with extreme payment volumes
        print("Creating edge case: Extreme payment volumes...")
        high_volume = []
        for i in range(3):
            member_data = self.create_member_with_payment_history(
                payment_months=36,  # 3 years of monthly payments
                payment_frequency="Monthly",
                payment_profile="reliable"
            )
            
            # Add additional payments to simulate high volume
            extra_payments = self._create_additional_payments(
                member_data["member"],
                count=50
            )
            
            high_volume.append({
                **member_data,
                "extra_payments": extra_payments,
                "scenario": "high_volume"
            })
        edge_cases["high_volume"] = high_volume
        
        # 4. Members with complex payment failures
        print("Creating edge case: Complex payment failures...")
        complex_failures = []
        for i in range(8):
            member_data = self.create_member_with_payment_history(
                payment_months=12,
                payment_profile="problematic"
            )
            
            # Add complex failure scenarios
            failure_chain = self._create_payment_failure_chain(member_data["member"])
            
            complex_failures.append({
                **member_data,
                "failure_chain": failure_chain,
                "scenario": "complex_failures"
            })
        edge_cases["complex_failures"] = complex_failures
        
        return edge_cases
    
    def _generate_payment_history(self, member, membership, sepa_mandate, 
                                payment_months: int, payment_frequency: str, 
                                payment_profile: str) -> Dict[str, List]:
        """Generate realistic payment history based on parameters"""
        
        profile_config = self.payment_profiles[payment_profile]
        pattern_config = self.payment_patterns[payment_frequency]
        
        invoices = []
        payments = []
        failed_payments = []
        
        # Calculate payment dates
        payment_dates = self._calculate_payment_dates(
            payment_months, 
            payment_frequency,
            pattern_config["variance_days"]
        )
        
        base_amount = membership.membership_type.amount if hasattr(membership.membership_type, 'amount') else 50.0
        
        for i, expected_date in enumerate(payment_dates):
            # Create invoice
            invoice_amount = base_amount * random.uniform(0.9, 1.1)  # ±10% variance
            invoice = self._create_payment_invoice(
                member=member,
                membership=membership,
                posting_date=expected_date,
                amount=invoice_amount,
                invoice_number=f"INV-{member.name}-{i+1:03d}"
            )
            invoices.append(invoice)
            
            # Determine if payment succeeds based on profile
            payment_succeeds = random.random() < (1 - profile_config["failure_rate"])
            
            if payment_succeeds:
                # Create successful payment
                payment_delay = 0 if random.random() < profile_config["on_time_rate"] else random.randint(1, 14)
                payment_date = add_days(expected_date, payment_delay)
                
                payment = self._create_successful_payment(
                    member=member,
                    invoice=invoice,
                    sepa_mandate=sepa_mandate,
                    payment_date=payment_date
                )
                payments.append(payment)
                
            else:
                # Create failed payment scenario
                failure_scenario = random.choice(self.failure_scenarios)
                failed_payment = self._create_failed_payment(
                    member=member,
                    invoice=invoice,
                    sepa_mandate=sepa_mandate,
                    failure_scenario=failure_scenario,
                    expected_date=expected_date
                )
                failed_payments.append(failed_payment)
                
                # Check if retry is eligible and succeeds
                if (failure_scenario["retry_eligible"] and 
                    random.random() < profile_config["retry_success_rate"]):
                    
                    # Create successful retry payment
                    retry_date = add_days(expected_date, random.randint(7, 21))
                    retry_payment = self._create_successful_payment(
                        member=member,
                        invoice=invoice,
                        sepa_mandate=sepa_mandate,
                        payment_date=retry_date,
                        is_retry=True
                    )
                    payments.append(retry_payment)
        
        return {
            "invoices": invoices,
            "payments": payments,
            "failed_payments": failed_payments
        }
    
    def _create_member_batch(self, batch_start: int, batch_size: int, 
                           max_payment_months: int, config: Dict) -> List[Dict[str, Any]]:
        """Create a batch of members with optimized database operations"""
        
        batch_data = []
        
        for i in range(batch_size):
            member_index = batch_start + i
            
            # Determine member characteristics based on distribution
            payment_profile = self._select_from_distribution(config["payment_profiles"])
            payment_frequency = self._select_from_distribution(config["payment_frequencies"])
            payment_months = random.randint(1, max_payment_months)
            
            include_sepa = random.random() < config["sepa_mandate_rate"]
            include_unreconciled = random.random() < config["unreconciled_rate"]
            
            # Create member data
            member_data = self.create_member_with_payment_history(
                payment_months=payment_months,
                payment_frequency=payment_frequency,
                payment_profile=payment_profile,
                include_sepa_mandate=include_sepa,
                include_unreconciled=include_unreconciled
            )
            
            # Add batch metadata
            member_data["batch_info"] = {
                "batch_start": batch_start,
                "member_index": member_index,
                "created_at": datetime.now().isoformat()
            }
            
            batch_data.append(member_data)
        
        return batch_data
    
    def _select_from_distribution(self, distribution: Dict[str, float]) -> str:
        """Select item from weighted distribution"""
        
        rand_value = random.random()
        cumulative = 0.0
        
        for item, weight in distribution.items():
            cumulative += weight
            if rand_value <= cumulative:
                return item
                
        # Return last item if no match (shouldn't happen with proper distributions)
        return list(distribution.keys())[-1]
    
    def _calculate_payment_dates(self, months: int, frequency: str, variance_days: int) -> List[str]:
        """Calculate realistic payment dates with variance"""
        
        dates = []
        base_date = add_days(today(), -months * 30)  # Start from months ago
        
        if frequency == "Monthly":
            for i in range(months):
                date = add_months(base_date, i)
                # Add random variance
                date = add_days(date, random.randint(-variance_days, variance_days))
                dates.append(str(date))
                
        elif frequency == "Quarterly":
            quarters = (months + 2) // 3  # Round up to cover the period
            for i in range(quarters):
                date = add_months(base_date, i * 3)
                date = add_days(date, random.randint(-variance_days, variance_days))
                dates.append(str(date))
                
        elif frequency == "Semi-Annual":
            periods = (months + 5) // 6  # Round up
            for i in range(periods):
                date = add_months(base_date, i * 6)
                date = add_days(date, random.randint(-variance_days, variance_days))
                dates.append(str(date))
                
        elif frequency == "Annual":
            years = (months + 11) // 12  # Round up
            for i in range(years):
                date = add_months(base_date, i * 12)
                date = add_days(date, random.randint(-variance_days, variance_days))
                dates.append(str(date))
        
        return dates
    
    def _create_payment_invoice(self, member, membership, posting_date, amount, invoice_number) -> Any:
        """Create invoice for payment history"""
        
        # Ensure member has customer
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.insert(ignore_permissions=True)
            member.customer = customer.name
            member.save(ignore_permissions=True)
            self.track_doc("Customer", customer.name)
        
        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.posting_date = posting_date
        invoice.due_date = add_days(posting_date, 30)
        invoice.membership = membership.name
        invoice.is_membership_invoice = 1
        
        # Add invoice item
        invoice.append("items", {
            "item_code": self._get_or_create_membership_item(),
            "qty": 1,
            "rate": amount,
            "amount": amount
        })
        
        invoice.insert(ignore_permissions=True)
        self.track_doc("Sales Invoice", invoice.name)
        
        return invoice
    
    def _create_successful_payment(self, member, invoice, sepa_mandate, payment_date, is_retry=False) -> Any:
        """Create successful payment entry"""
        
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.party_type = "Customer"
        payment.party = member.customer
        payment.posting_date = payment_date
        payment.paid_amount = invoice.grand_total
        payment.received_amount = invoice.grand_total
        
        # Set payment method based on SEPA mandate
        if sepa_mandate and sepa_mandate.status == "Active":
            payment.mode_of_payment = "SEPA Direct Debit"
            payment.reference_no = sepa_mandate.mandate_id
        else:
            payment.mode_of_payment = random.choice(["Bank Transfer", "Cash", "Credit Card"])
        
        # Link to invoice
        payment.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": invoice.grand_total
        })
        
        payment.insert(ignore_permissions=True)
        payment.submit()
        self.track_doc("Payment Entry", payment.name)
        
        return payment
    
    def _create_failed_payment(self, member, invoice, sepa_mandate, failure_scenario, expected_date) -> Dict[str, Any]:
        """Create failed payment record (for tracking purposes)"""
        
        # This would typically be stored in a payment failure log table
        # For testing purposes, we'll return a dictionary with failure details
        
        failed_payment = {
            "member": member.name,
            "invoice": invoice.name,
            "sepa_mandate": sepa_mandate.name if sepa_mandate else None,
            "expected_date": expected_date,
            "failure_code": failure_scenario["code"],
            "failure_description": failure_scenario["description"],
            "retry_eligible": failure_scenario["retry_eligible"],
            "created_at": datetime.now().isoformat()
        }
        
        return failed_payment
    
    def _create_unreconciled_payment(self, member) -> Any:
        """Create unreconciled payment entry"""
        
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.party_type = "Customer"  
        payment.party = member.customer
        payment.posting_date = add_days(today(), -random.randint(1, 60))
        payment.paid_amount = random.uniform(10.0, 100.0)
        payment.received_amount = payment.paid_amount
        payment.mode_of_payment = "Bank Transfer"
        payment.reference_no = f"UNREC-{random_string(8)}"
        
        # No references - makes it unreconciled
        
        payment.insert(ignore_permissions=True)
        payment.submit()
        self.track_doc("Payment Entry", payment.name)
        
        return payment
    
    def _create_corrupted_invoice(self, member) -> Any:
        """Create invoice with intentionally corrupted data for edge case testing"""
        
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        # Add item with corrupted reference
        invoice.append("items", {
            "item_code": "NONEXISTENT-ITEM",  # Invalid item code
            "qty": 1,
            "rate": 50.0,
            "amount": 50.0
        })
        
        try:
            invoice.insert(ignore_permissions=True)
            self.track_doc("Sales Invoice", invoice.name)
            return invoice
        except:
            # Return None if creation fails (expected for corrupted data)
            return None
    
    def _create_additional_payments(self, member, count: int) -> List[Any]:
        """Create additional payments for high-volume testing"""
        
        payments = []
        
        for i in range(count):
            payment = frappe.new_doc("Payment Entry")
            payment.payment_type = "Receive"
            payment.party_type = "Customer"
            payment.party = member.customer
            payment.posting_date = add_days(today(), -random.randint(1, 365))
            payment.paid_amount = random.uniform(5.0, 50.0)
            payment.received_amount = payment.paid_amount
            payment.mode_of_payment = random.choice(["Bank Transfer", "Cash"])
            payment.reference_no = f"EXTRA-{random_string(6)}-{i}"
            
            payment.insert(ignore_permissions=True)
            payment.submit()
            self.track_doc("Payment Entry", payment.name)
            
            payments.append(payment)
        
        return payments
    
    def _create_payment_failure_chain(self, member) -> List[Dict[str, Any]]:
        """Create complex payment failure chain for edge case testing"""
        
        failure_chain = []
        
        # Create a series of related failures
        base_amount = 75.0
        
        for i in range(5):
            # Create invoice
            invoice = self._create_payment_invoice(
                member=member,
                membership=frappe.get_doc("Membership", {"member": member.name}),
                posting_date=add_days(today(), -(30 * (5-i))),
                amount=base_amount,
                invoice_number=f"FAIL-CHAIN-{i+1}"
            )
            
            # Create failure scenario
            failure_scenarios = [
                {"code": "AM04", "description": "Insufficient funds", "retry_eligible": True},
                {"code": "MS02", "description": "Bank system error", "retry_eligible": True},
                {"code": "AM04", "description": "Insufficient funds (retry)", "retry_eligible": True},
                {"code": "AC04", "description": "Account closed", "retry_eligible": False},
                {"code": "AG01", "description": "Transaction forbidden", "retry_eligible": False}
            ]
            
            failure = {
                "invoice": invoice,
                "failure_scenario": failure_scenarios[i],
                "attempt_number": i + 1,
                "chain_position": i
            }
            
            failure_chain.append(failure)
        
        return failure_chain
    
    def _calculate_payment_statistics(self, payment_data: Dict[str, List]) -> Dict[str, Any]:
        """Calculate statistics for generated payment data"""
        
        total_invoices = len(payment_data["invoices"])
        total_payments = len(payment_data["payments"])
        total_failures = len(payment_data["failed_payments"])
        
        success_rate = (total_payments / total_invoices) if total_invoices > 0 else 0.0
        failure_rate = (total_failures / total_invoices) if total_invoices > 0 else 0.0
        
        # Calculate amounts
        total_invoiced = sum(inv.grand_total for inv in payment_data["invoices"])
        total_paid = sum(pay.paid_amount for pay in payment_data["payments"])
        
        return {
            "total_invoices": total_invoices,
            "total_payments": total_payments,
            "total_failures": total_failures,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "total_invoiced_amount": total_invoiced,
            "total_paid_amount": total_paid,
            "collection_rate": (total_paid / total_invoiced) if total_invoiced > 0 else 0.0
        }
    
    def _get_or_create_membership_item(self) -> str:
        """Get or create membership item for invoices"""
        
        item_code = "MEMBERSHIP-DUES"
        
        if not frappe.db.exists("Item", item_code):
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = "Membership Dues"
            item.item_group = "Services"
            item.is_sales_item = 1
            item.is_service_item = 1
            item.standard_rate = 50.0
            
            item.insert(ignore_permissions=True)
            self.track_doc("Item", item.name)
        
        return item_code


# Convenience functions for direct usage

def create_payment_history_test_data(scale: str = "small", **kwargs) -> Dict[str, Any]:
    """
    Create standardized payment history test data sets
    
    Args:
        scale: Test scale ("small", "medium", "large", "xl")
        **kwargs: Additional configuration options
        
    Returns:
        Dictionary with created test data
    """
    
    scale_configs = {
        "small": {"member_count": 50, "max_payment_months": 6},
        "medium": {"member_count": 200, "max_payment_months": 12},
        "large": {"member_count": 1000, "max_payment_months": 18},
        "xl": {"member_count": 2500, "max_payment_months": 24}
    }
    
    config = scale_configs.get(scale, scale_configs["small"])
    config.update(kwargs)
    
    factory = PaymentHistoryTestDataFactory(cleanup_on_exit=False, seed=42)
    
    try:
        members_data = factory.create_bulk_members_with_histories(
            member_count=config["member_count"],
            max_payment_months=config["max_payment_months"]
        )
        
        return {
            "factory": factory,
            "members_data": members_data,
            "scale": scale,
            "config": config,
            "statistics": _calculate_bulk_statistics(members_data)
        }
        
    except Exception as e:
        factory.cleanup() 
        raise e


def _calculate_bulk_statistics(members_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate statistics for bulk member data"""
    
    total_members = len(members_data)
    total_invoices = sum(len(md["invoices"]) for md in members_data)
    total_payments = sum(len(md["payments"]) for md in members_data)
    total_failures = sum(len(md["failed_payments"]) for md in members_data)
    
    # Payment profile distribution
    profile_distribution = {}
    for md in members_data:
        profile = md["payment_profile"]
        profile_distribution[profile] = profile_distribution.get(profile, 0) + 1
    
    # Frequency distribution
    frequency_distribution = {}
    for md in members_data:
        frequency = md["payment_frequency"]
        frequency_distribution[frequency] = frequency_distribution.get(frequency, 0) + 1
    
    return {
        "total_members": total_members,
        "total_invoices": total_invoices,
        "total_payments": total_payments,
        "total_failures": total_failures,
        "overall_success_rate": (total_payments / total_invoices) if total_invoices > 0 else 0.0,
        "profile_distribution": profile_distribution,
        "frequency_distribution": frequency_distribution,
        "avg_invoices_per_member": total_invoices / total_members if total_members > 0 else 0.0,
        "avg_payments_per_member": total_payments / total_members if total_members > 0 else 0.0
    }