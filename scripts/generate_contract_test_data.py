#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Contract Test Data Generator
================================

Generates comprehensive, business-rule-compliant test data for JavaScript API contract tests
using the Enhanced Test Factory. This ensures consistency between Python and JavaScript tests
and leverages the rich business logic validation in the Python test factory.

Usage:
    python scripts/generate_contract_test_data.py
    
Output:
    verenigingen/tests/fixtures/api_contract_test_data.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List

# Add the Frappe bench path to Python path
frappe_bench_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.append(frappe_bench_path)

# Add the app path
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(app_path)

import frappe
from frappe.utils import getdate, add_days, add_months
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory, BusinessRuleError


class APIContractTestDataGenerator:
    """Generates test data for all API contract schemas using the Enhanced Test Factory"""
    
    def __init__(self, seed: int = 42):
        """Initialize with deterministic seed for reproducible data"""
        self.factory = EnhancedTestDataFactory(seed=seed, use_faker=True)
        self.generated_data = {}
        
    def initialize_frappe(self, site: str = "dev.veganisme.net"):
        """Initialize Frappe context"""
        try:
            if not frappe.local.db:
                frappe.init(site=site)
                frappe.connect()
            print(f"✅ Connected to Frappe site: {site}")
        except Exception as e:
            print(f"❌ Failed to connect to Frappe: {e}")
            # Try alternative approach
            try:
                frappe.init(site=site, sites_path='/home/frappe/frappe-bench/sites')
                frappe.connect()
                print(f"✅ Connected using alternative method")
            except Exception as e2:
                print(f"❌ Alternative connection also failed: {e2}")
                sys.exit(1)
    
    def cleanup_frappe(self):
        """Clean up Frappe context"""
        try:
            frappe.destroy()
            print("✅ Frappe context cleaned up")
        except:
            pass
    
    def generate_sepa_mandate_data(self) -> Dict[str, Any]:
        """Generate test data for SEPA mandate APIs"""
        print("📋 Generating SEPA mandate test data...")
        
        # Create a test member first
        member = self.factory.create_member(
            first_name="Jan",
            last_name="van der Berg", 
            birth_date="1985-03-15"
        )
        
        return {
            "create_sepa_mandate": {
                "valid_request": {
                    "member": member.name,
                    "iban": "NL91ABNA0417164300",
                    "bic": "ABNANL2A", 
                    "mandate_type": "RCUR",
                    "debtor_name": f"{member.first_name} {member.last_name}"
                },
                "valid_response": {
                    "success": True,
                    "mandate_reference": "SEPA-2024-07-0001",
                    "status": "Active",
                    "message": "SEPA mandate created successfully",
                    "audit_log_id": "AL-2024-07-0001"
                }
            },
            "validate_iban": {
                "valid_request": {
                    "iban": "NL91ABNA0417164300",
                    "country_code": "NL"
                },
                "valid_response": {
                    "valid": True,
                    "country": "Netherlands",
                    "bank_code": "ABNA",
                    "bank_name": "ABN AMRO Bank N.V.",
                    "branch_code": "0417",
                    "account_number": "164300",
                    "check_digits": "91",
                    "formatted_iban": "NL91 ABNA 0417 1643 00"
                }
            }
        }
    
    def generate_mollie_payment_data(self) -> Dict[str, Any]:
        """Generate test data for Mollie payment APIs"""
        print("💳 Generating Mollie payment test data...")
        
        # Create test invoice
        member = self.factory.create_member(
            first_name="Maria", 
            last_name="de Jong",
            birth_date="1990-07-22"
        )
        
        return {
            "make_payment": {
                "valid_request": {
                    "amount": {
                        "value": "25.00",
                        "currency": "EUR"
                    },
                    "description": "Vereniging membership dues - July 2024",
                    "reference_doctype": "Sales Invoice",
                    "reference_docname": "SI-2024-07-0001",
                    "payment_method": ["ideal", "creditcard"],
                    "redirect_url": "https://dev.veganisme.net/payment/success",
                    "webhook_url": "https://dev.veganisme.net/api/method/verenigingen.mollie_webhook",
                    "metadata": {
                        "member_id": member.name,
                        "membership_type": "Regular"
                    }
                },
                "valid_response": {
                    "success": True,
                    "payment_id": "tr_WDqYK6vllg",
                    "checkout_url": "https://www.mollie.com/payscreen/select-method/WDqYK6vllg",
                    "status": "open",
                    "expires_at": "2024-07-15T12:30:00Z"
                }
            },
            "create_customer": {
                "valid_request": {
                    "name": f"{member.first_name} {member.last_name}",
                    "email": member.email,
                    "locale": "nl_NL",
                    "metadata": {
                        "member_id": member.name,
                        "customer_id": f"Customer-{member.name.split('-')[1]}-{member.name.split('-')[2]}-{member.name.split('-')[3]}"
                    }
                },
                "valid_response": {
                    "success": True,
                    "customer_id": "cst_8wmqcHMN4U",
                    "mode": "test",
                    "created_at": "2024-07-15T10:15:00Z"
                }
            }
        }
    
    def generate_member_lifecycle_data(self) -> Dict[str, Any]:
        """Generate test data for member lifecycle APIs"""
        print("👤 Generating member lifecycle test data...")
        
        # Create comprehensive member data
        member = self.factory.create_member(
            first_name="Pieter", 
            last_name="van den Berg",
            tussenvoegsel="van den",
            birth_date="1982-11-08",
            email=self.factory.generate_test_email("member"),
            postal_code="1012 AB",
            city="Amsterdam",
            phone=self.factory.generate_test_phone(),
            membership_type="Regular"
        )
        
        return {
            "create_member": {
                "valid_request": {
                    "first_name": "Sophie",
                    "last_name": "Vermeulen", 
                    "tussenvoegsel": "",
                    "email": self.factory.generate_test_email("member"),
                    "birth_date": "1995-04-12",
                    "postal_code": "2000 AA",
                    "city": "Haarlem",
                    "phone": self.factory.generate_test_phone(),
                    "membership_type": "Student",
                    "preferred_language": "nl"
                },
                "valid_response": {
                    "success": True,
                    "member_id": "Assoc-Member-2024-07-0002",
                    "customer_id": "Assoc-Customer-2024-07-0002", 
                    "status": "Active",
                    "member_since": "2024-07-15",
                    "next_invoice_date": "2024-08-15",
                    "validation_warnings": []
                }
            },
            "process_payment": {
                "valid_request": {
                    "member_id": member.name,
                    "payment_amount": 25.00,
                    "payment_method": "SEPA Direct Debit",
                    "payment_date": "2024-07-15",
                    "reference": "Monthly dues July 2024",
                    "invoice_id": "SI-2024-07-0001"
                },
                "valid_response": {
                    "success": True,
                    "payment_entry_id": "PE-2024-07-0001",
                    "invoice_status": "Paid",
                    "outstanding_amount": 0.00,
                    "payment_history_updated": True,
                    "member_status_updated": True,
                    "next_payment_due": "2024-08-15"
                }
            },
            "get_payment_history": {
                "valid_request": {
                    "member_id": member.name,
                    "date_range": {
                        "from": "2024-01-01",
                        "to": "2024-07-31"
                    },
                    "payment_status": ["Paid"],
                    "limit": 20
                },
                "valid_response": {
                    "success": True,
                    "total_count": 7,
                    "payment_history": [
                        {
                            "date": "2024-07-15",
                            "amount": 25.00,
                            "payment_method": "SEPA Direct Debit",
                            "status": "Paid",
                            "invoice_id": "SI-2024-07-0001",
                            "reference": "Monthly dues July 2024",
                            "gateway_transaction_id": "TXN-SEPA-12345"
                        }
                    ],
                    "summary": {
                        "total_paid": 175.00,
                        "total_failed": 0.00,
                        "average_payment": 25.00,
                        "payment_frequency": "Monthly"
                    }
                }
            }
        }
    
    def generate_chapter_management_data(self) -> Dict[str, Any]:
        """Generate test data for chapter management APIs"""
        print("🏢 Generating chapter management test data...")
        
        member = self.factory.create_member(
            first_name="Lisa",
            last_name="Jansen",
            birth_date="1988-09-03",
            postal_code="3000 AA",
            city="Rotterdam"
        )
        
        return {
            "join_chapter": {
                "valid_request": {
                    "member_id": member.name,
                    "chapter": "Rotterdam",
                    "role": "Member",
                    "start_date": "2024-07-15"
                },
                "valid_response": {
                    "success": True,
                    "chapter_membership_id": "CM-2024-07-0001",
                    "status": "Active",
                    "requires_approval": False,
                    "approval_status": "Approved"
                }
            },
            "assign_member_to_chapter": {
                "valid_request": {
                    "member": member.name,
                    "chapter": "Rotterdam",
                    "note": "Member requested transfer from Amsterdam chapter"
                },
                "valid_response": {
                    "success": True,
                    "message": "Member assigned to chapter successfully",
                    "previous_chapters": ["Amsterdam"]
                }
            }
        }
    
    def generate_donation_data(self) -> Dict[str, Any]:
        """Generate test data for donation APIs"""  
        print("💰 Generating donation test data...")
        
        return {
            "submit_donation": {
                "valid_request": {
                    "donor_name": "TEST Anonymous Donor",
                    "email": self.factory.generate_test_email("donor"),
                    "amount": 50.00,
                    "donation_type": "one-time",
                    "anbi_consent": True
                },
                "valid_response": {
                    "success": True,
                    "donation_id": "DON-2024-07-0001", 
                    "payment_url": "https://www.mollie.com/payscreen/donation/xyz123"
                }
            }
        }
    
    def generate_all_test_data(self) -> Dict[str, Any]:
        """Generate comprehensive test data for all API contracts"""
        print("🚀 Generating comprehensive API contract test data...")
        print("=" * 50)
        
        try:
            self.generated_data = {
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "generator_version": "1.0.0", 
                    "frappe_site": frappe.local.site,
                    "seed": self.factory.seed,
                    "description": "Auto-generated test data for API contract validation"
                },
                "sepa_apis": self.generate_sepa_mandate_data(),
                "mollie_apis": self.generate_mollie_payment_data(), 
                "member_apis": self.generate_member_lifecycle_data(),
                "chapter_apis": self.generate_chapter_management_data(),
                "donation_apis": self.generate_donation_data()
            }
            
            print("✅ All test data generated successfully")
            return self.generated_data
            
        except BusinessRuleError as e:
            print(f"❌ Business rule validation failed: {e}")
            raise
        except Exception as e:
            print(f"❌ Unexpected error during test data generation: {e}")
            raise
    
    def save_to_file(self, output_path: str):
        """Save generated test data to JSON file"""
        try:
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.generated_data, f, indent=2, ensure_ascii=False, default=str)
            
            file_size = os.path.getsize(output_path)
            print(f"✅ Test data saved to: {output_path}")
            print(f"📊 File size: {file_size:,} bytes")
            print(f"📈 API schemas covered: {len(self.generated_data) - 1}")  # -1 for metadata
            
        except Exception as e:
            print(f"❌ Failed to save test data: {e}")
            raise


def main():
    """Main entry point"""
    print("🎯 API Contract Test Data Generator")
    print("=" * 40)
    
    # Determine output path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "..", "verenigingen", "tests", "fixtures", "api_contract_test_data.json")
    output_path = os.path.abspath(output_path)
    
    generator = APIContractTestDataGenerator(seed=42)
    
    try:
        # Initialize Frappe
        generator.initialize_frappe()
        
        # Generate test data
        generator.generate_all_test_data()
        
        # Save to file
        generator.save_to_file(output_path)
        
        print("\n🎉 Test data generation completed successfully!")
        print(f"📁 Output location: {output_path}")
        print("\n💡 Next steps:")
        print("1. Update JavaScript tests to use this generated data")
        print("2. Run npm test to verify integration")
        print("3. Commit the generated test data file")
        
    except Exception as e:
        print(f"\n❌ Test data generation failed: {e}")
        sys.exit(1)
    finally:
        generator.cleanup_frappe()


if __name__ == "__main__":
    main()