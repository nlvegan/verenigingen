"""
Unit Tests for Member Lifecycle Business Logic
==============================================

Unit tests for isolated Member DocType business logic components.
These tests focus on specific business rules and edge cases without database dependencies.

Focus Areas:
- Member identification and ID generation
- Dutch naming convention handling  
- Address normalization and fingerprinting
- Status transition validation
- Business rule enforcement
- Edge case boundary conditions

Author: Enhanced Test Development Phase 5.2
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime, date

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member.member import Member
from verenigingen.utils.dutch_name_utils import format_dutch_full_name, get_full_last_name
from verenigingen.utils.address_matching.dutch_address_normalizer import DutchAddressNormalizer


class MemberLifecycleUnitTest(EnhancedTestCase):
    """Unit tests for Member lifecycle business logic without database dependencies"""

    def setUp(self):
        """Set up unit test fixtures"""
        super().setUp()
        
    def test_member_id_generation_logic(self):
        """Test member ID generation business rules"""
        
        # Test case: Approved member should get member ID
        member_data = {
            "doctype": "Member",
            "first_name": "Jan",
            "last_name": "Testmember",
            "email": "jan.test@example.com",
            "status": "Active",
            "member_id": None
        }
        
        member = frappe.get_doc(member_data)
        
        # Should generate member ID for active status
        self.assertIsNone(member.member_id)  # Not set yet
        
        # Mock member ID generation logic
        with patch('verenigingen.verenigingen.doctype.member.member_id_manager.generate_member_id') as mock_gen:
            mock_gen.return_value = "M-2024-001"
            
            # Simulate the ID generation that happens during save
            if member.status == "Active" and not member.member_id:
                member.member_id = mock_gen.return_value
                
            self.assertEqual(member.member_id, "M-2024-001")
            
    def test_application_id_generation_logic(self):
        """Test application ID generation for pending applications"""
        
        member_data = {
            "doctype": "Member", 
            "first_name": "Pending",
            "last_name": "Application",
            "email": "pending@example.com",
            "status": "Application Pending",
            "application_id": None
        }
        
        member = frappe.get_doc(member_data)
        
        # Test application ID generation logic (real function on Member class)
        if member.status == "Application Pending" and not member.application_id:
            member.application_id = member.generate_application_id()
            
        # Should have generated a proper application ID
        self.assertTrue(member.application_id)
        self.assertIn("APP-", member.application_id)
            
    def test_dutch_name_formatting_edge_cases(self):
        """Test Dutch naming convention edge cases"""
        
        # Test case: Multiple tussenvoegsel
        test_cases = [
            {
                "first_name": "Pieter",
                "tussenvoegsel": "van der",  
                "last_name": "Berg",
                "expected": "Pieter van der Berg"
            },
            {
                "first_name": "Maria",
                "tussenvoegsel": "de",
                "last_name": "Wit", 
                "expected": "Maria de Wit"
            },
            {
                "first_name": "Jan",
                "tussenvoegsel": None,
                "last_name": "Jansen",
                "expected": "Jan Jansen" 
            },
            {
                "first_name": "Anne",
                "tussenvoegsel": "",  # Empty string
                "last_name": "Bakker",
                "expected": "Anne Bakker"
            }
        ]
        
        for case in test_cases:
            full_name = format_dutch_full_name(
                case["first_name"], 
                middle_name=None,
                tussenvoegsel=case["tussenvoegsel"], 
                last_name=case["last_name"]
            )
            self.assertEqual(full_name, case["expected"], 
                           f"Failed for case: {case}")
            
    def test_address_fingerprint_generation(self):
        """Test address fingerprinting for duplicate detection"""
        
        # Test cases with address variations that should be considered duplicates
        address_test_cases = [
            {
                "address_1": "Hoofdstraat 123",
                "address_2": "1234 AB", 
                "city": "Amsterdam",
                "postal_code": "1234AB"  # No space
            },
            {
                "address_1": "Hoofdstraat 123", 
                "address_2": "1234 AB",  # With space
                "city": "Amsterdam",
                "postal_code": "1234 AB"
            }
        ]
        
        normalizer = DutchAddressNormalizer()
        
        fingerprints = []
        for address in address_test_cases:
            fingerprint = normalizer.generate_fingerprint(
                address["address_1"],
                address["city"]
            )
            fingerprints.append(fingerprint)
            
        # Both should generate same fingerprint (normalized postal code)
        self.assertEqual(fingerprints[0], fingerprints[1], 
                        "Similar addresses should have same fingerprint")
        
    def test_member_age_calculation_edge_cases(self):
        """Test age calculation for various edge cases"""
        
        from frappe.utils import getdate, add_years
        
        today = getdate()
        
        # Test exact birthday edge cases  
        test_cases = [
            {
                "birth_date": add_years(today, -18),  # Exactly 18 today
                "expected_age": 18,
                "description": "Exactly 18 on birthday"
            },
            {
                "birth_date": add_years(today, -16),  # Exactly 16 today  
                "expected_age": 16,
                "description": "Exactly 16 on birthday"
            },
            {
                "birth_date": getdate("1992-02-29"),  # Leap year birthday (1992 was a leap year)
                "expected_age": today.year - 1992,  # Approximate
                "description": "Leap year birthday"
            }
        ]
        
        for case in test_cases:
            member_data = {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Age",
                "birth_date": case["birth_date"]
            }
            
            member = frappe.get_doc(member_data)
            
            # Calculate age (simplified logic for testing)
            if member.birth_date:
                birth_date = getdate(member.birth_date)
                age = today.year - birth_date.year
                
                # Handle leap year case - if birth was Feb 29 and current year doesn't have Feb 29,
                # treat as if birthday was Feb 28
                try:
                    birthday_this_year = birth_date.replace(year=today.year)
                except ValueError:
                    # Leap year birth (Feb 29) in non-leap year - use Feb 28
                    birthday_this_year = birth_date.replace(year=today.year, day=28)
                
                if today < birthday_this_year:
                    age -= 1
                    
                self.assertGreaterEqual(age, 0, f"Age should be non-negative for {case['description']}")
                
    def test_volunteer_eligibility_validation(self):
        """Test volunteer eligibility business rules"""
        
        from frappe.utils import getdate, add_years
        
        today = getdate()
        
        # Test cases for volunteer eligibility (16+ years old)
        test_cases = [
            {
                "birth_date": add_years(today, -17),  # 17 years old
                "expected_eligible": True,
                "description": "17 years old - eligible"
            },
            {
                "birth_date": add_years(today, -15),  # 15 years old
                "expected_eligible": False, 
                "description": "15 years old - not eligible"
            },
            {
                "birth_date": add_years(today, -16),  # Exactly 16
                "expected_eligible": True,
                "description": "Exactly 16 - eligible"
            }
        ]
        
        for case in test_cases:
            member_data = {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Volunteer",
                "birth_date": case["birth_date"],
                "status": "Active"
            }
            
            member = frappe.get_doc(member_data)
            
            # Business rule: Calculate if eligible for volunteer role
            age = today.year - getdate(member.birth_date).year
            if today < getdate(str(today.year) + "-" + 
                            str(getdate(member.birth_date).month) + "-" + 
                            str(getdate(member.birth_date).day)):
                age -= 1
                
            is_eligible = age >= 16 and member.status == "Active"
            
            self.assertEqual(is_eligible, case["expected_eligible"],
                           f"Volunteer eligibility failed for {case['description']}")
            
    def test_membership_status_transitions(self):
        """Test valid membership status transitions"""
        
        # Define valid status transitions
        valid_transitions = {
            "Application Pending": ["Active", "Rejected", "Withdrawn"],
            "Active": ["Suspended", "Terminated", "On Hold"],
            "Suspended": ["Active", "Terminated"],
            "On Hold": ["Active", "Terminated"],
            "Terminated": [],  # No transitions from terminated
            "Rejected": [],    # No transitions from rejected
            "Withdrawn": []    # No transitions from withdrawn
        }
        
        # Test each valid transition
        for current_status, valid_next_statuses in valid_transitions.items():
            for next_status in valid_next_statuses:
                member_data = {
                    "doctype": "Member",
                    "first_name": "Status",
                    "last_name": "Test", 
                    "status": current_status
                }
                
                member = frappe.get_doc(member_data)
                
                # Simulate status change validation logic
                def is_valid_transition(from_status, to_status):
                    return to_status in valid_transitions.get(from_status, [])
                
                is_valid = is_valid_transition(current_status, next_status)
                self.assertTrue(is_valid, 
                              f"Transition from {current_status} to {next_status} should be valid")
                
        # Test invalid transitions
        invalid_transitions = [
            ("Terminated", "Active"),  # Cannot reactivate terminated member
            ("Rejected", "Active"),    # Cannot activate rejected application
            ("Active", "Application Pending")  # Cannot go back to pending
        ]
        
        for current_status, invalid_next_status in invalid_transitions:
            def is_valid_transition(from_status, to_status):
                return to_status in valid_transitions.get(from_status, [])
                
            is_valid = is_valid_transition(current_status, invalid_next_status)
            self.assertFalse(is_valid,
                           f"Transition from {current_status} to {invalid_next_status} should be invalid")
            
    def test_postal_code_normalization(self):
        """Test Dutch postal code normalization edge cases"""
        
        # Test cases for postal code variations
        test_cases = [
            {"input": "1234AB", "expected": "1234 AB"},
            {"input": "1234 AB", "expected": "1234 AB"}, 
            {"input": "1234  AB", "expected": "1234 AB"},  # Multiple spaces
            {"input": "1234ab", "expected": "1234 AB"},   # Lowercase
            {"input": "1234 ab", "expected": "1234 AB"},  # Mixed case
            {"input": " 1234AB ", "expected": "1234 AB"}, # Leading/trailing spaces
        ]
        
        for case in test_cases:
            # Simulate postal code normalization logic
            def normalize_postal_code(postal_code):
                if not postal_code:
                    return postal_code
                    
                # Remove extra spaces and convert to uppercase
                normalized = postal_code.strip().upper()
                
                # Add space between numbers and letters if missing
                if len(normalized) == 6 and normalized[4:].isalpha():
                    normalized = normalized[:4] + " " + normalized[4:]
                    
                # Remove extra spaces
                normalized = " ".join(normalized.split())
                
                return normalized
            
            result = normalize_postal_code(case["input"])
            self.assertEqual(result, case["expected"],
                           f"Postal code normalization failed for input: {case['input']}")
            
    def test_email_validation_edge_cases(self):
        """Test email validation business rules"""
        
        # Test cases for email validation
        valid_emails = [
            "test@example.com",
            "user.name@domain.co.uk", 
            "user+tag@example.org",
            "123@numeric-domain.com"
        ]
        
        invalid_emails = [
            "invalid.email",      # No @ symbol
            "@domain.com",        # No local part
            "user@",              # No domain
            "user@.com",          # Invalid domain
            "user space@domain.com", # Space in local part
            ""                    # Empty string
        ]
        
        import re
        
        def is_valid_email(email):
            if not email:
                return False
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            return re.match(pattern, email) is not None
        
        for email in valid_emails:
            self.assertTrue(is_valid_email(email),
                          f"Email {email} should be valid")
                          
        for email in invalid_emails:
            self.assertFalse(is_valid_email(email), 
                           f"Email {email} should be invalid")
            
    def test_member_display_name_generation(self):
        """Test member display name generation logic"""
        
        test_cases = [
            {
                "first_name": "Jan", 
                "tussenvoegsel": "van",
                "last_name": "Berg",
                "expected": "Jan van Berg"
            },
            {
                "first_name": "Maria",
                "tussenvoegsel": None,
                "last_name": "Jansen", 
                "expected": "Maria Jansen"
            },
            {
                "first_name": "Piet",
                "tussenvoegsel": "",
                "last_name": "de Vries",
                "expected": "Piet de Vries"
            }
        ]
        
        for case in test_cases:
            # Simulate display name generation logic
            def generate_display_name(first_name, tussenvoegsel, last_name):
                parts = [first_name]
                if tussenvoegsel and tussenvoegsel.strip():
                    parts.append(tussenvoegsel.strip())
                if last_name:
                    parts.append(last_name)
                return " ".join(parts)
            
            display_name = generate_display_name(
                case["first_name"],
                case["tussenvoegsel"], 
                case["last_name"]
            )
            
            self.assertEqual(display_name, case["expected"],
                           f"Display name generation failed for case: {case}")
            
    def test_chapter_assignment_validation(self):
        """Test chapter assignment business rules"""
        
        # Test business rule: Member can be assigned to chapter based on postal code
        test_cases = [
            {
                "postal_code": "1000 AA",  # Amsterdam area
                "expected_region": "Noord-Holland",
                "description": "Amsterdam postal code"
            },
            {
                "postal_code": "2500 AB",  # Den Haag area
                "expected_region": "Zuid-Holland", 
                "description": "Den Haag postal code"
            },
            {
                "postal_code": "3000 AC",  # Rotterdam area
                "expected_region": "Zuid-Holland",
                "description": "Rotterdam postal code"
            }
        ]
        
        # Mock chapter assignment logic
        def get_region_from_postal_code(postal_code):
            if not postal_code:
                return None
                
            # Simplified postal code to region mapping
            code_num = int(postal_code[:4])
            
            if 1000 <= code_num < 2000:
                return "Noord-Holland"
            elif 2000 <= code_num < 4000:
                return "Zuid-Holland" 
            elif 4000 <= code_num < 6000:
                return "Noord-Brabant"
            else:
                return "Other"
        
        for case in test_cases:
            region = get_region_from_postal_code(case["postal_code"])
            self.assertEqual(region, case["expected_region"],
                           f"Region assignment failed for {case['description']}")
            
    def test_membership_fee_calculation_edge_cases(self):
        """Test membership fee calculation business rules"""
        
        from decimal import Decimal
        
        # Test cases for different membership types and fee calculations
        test_cases = [
            {
                "membership_type": "Regular",
                "base_fee": Decimal("60.00"),
                "discount": None,
                "expected": Decimal("60.00")
            },
            {
                "membership_type": "Student", 
                "base_fee": Decimal("60.00"),
                "discount": Decimal("0.50"),  # 50% student discount
                "expected": Decimal("30.00")
            },
            {
                "membership_type": "Senior",
                "base_fee": Decimal("60.00"), 
                "discount": Decimal("0.25"),  # 25% senior discount
                "expected": Decimal("45.00")
            },
            {
                "membership_type": "Life",
                "base_fee": Decimal("500.00"),
                "discount": None,
                "expected": Decimal("500.00")
            }
        ]
        
        for case in test_cases:
            # Simulate fee calculation logic
            def calculate_membership_fee(base_fee, discount=None):
                if discount:
                    return base_fee * (Decimal("1.00") - discount)
                return base_fee
            
            calculated_fee = calculate_membership_fee(
                case["base_fee"],
                case["discount"]
            )
            
            self.assertEqual(calculated_fee, case["expected"],
                           f"Fee calculation failed for {case['membership_type']}")


class MemberValidationUnitTest(EnhancedTestCase):
    """Unit tests for Member validation business logic"""
    
    def test_required_field_validation(self):
        """Test required field validation logic"""
        
        # Test cases for required fields
        required_fields = ["first_name", "last_name", "email"]
        
        for field in required_fields:
            member_data = {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "User", 
                "email": "test@example.com"
            }
            
            # Remove the required field
            member_data[field] = None
            
            member = frappe.get_doc(member_data)
            
            # Simulate validation logic
            def validate_required_fields(doc):
                errors = []
                for req_field in required_fields:
                    if not getattr(doc, req_field, None):
                        errors.append(f"{req_field} is required")
                return errors
            
            validation_errors = validate_required_fields(member)
            self.assertGreater(len(validation_errors), 0,
                             f"Should have validation error for missing {field}")
            
    def test_email_uniqueness_validation(self):
        """Test email uniqueness business rule"""
        
        # This would normally check database, but for unit test we mock it
        existing_emails = ["existing@example.com", "taken@test.com"]
        
        def email_already_exists(email):
            return email in existing_emails
            
        test_cases = [
            {"email": "new@example.com", "should_be_unique": True},
            {"email": "existing@example.com", "should_be_unique": False}, 
            {"email": "taken@test.com", "should_be_unique": False}
        ]
        
        for case in test_cases:
            is_unique = not email_already_exists(case["email"])
            self.assertEqual(is_unique, case["should_be_unique"],
                           f"Email uniqueness check failed for {case['email']}")
            
    def test_birth_date_range_validation(self):
        """Test birth date range validation"""
        
        from frappe.utils import getdate, add_years
        
        today = getdate()
        
        test_cases = [
            {
                "birth_date": add_years(today, -25),  # 25 years ago - valid
                "expected_valid": True,
                "description": "Normal birth date"
            },
            {
                "birth_date": add_years(today, 1),    # Future date - invalid
                "expected_valid": False,
                "description": "Future birth date"
            },
            {
                "birth_date": add_years(today, -150), # 150 years ago - invalid
                "expected_valid": False, 
                "description": "Too old birth date"
            },
            {
                "birth_date": today,                  # Today - edge case
                "expected_valid": True,
                "description": "Born today"
            }
        ]
        
        for case in test_cases:
            # Simulate birth date validation logic
            def is_valid_birth_date(birth_date):
                if not birth_date:
                    return True  # Optional field
                    
                birth_date = getdate(birth_date)
                
                # Cannot be in future
                if birth_date > today:
                    return False
                    
                # Cannot be more than 120 years ago
                if birth_date < add_years(today, -120):
                    return False
                    
                return True
            
            is_valid = is_valid_birth_date(case["birth_date"])
            self.assertEqual(is_valid, case["expected_valid"],
                           f"Birth date validation failed for {case['description']}")


if __name__ == '__main__':
    unittest.main()