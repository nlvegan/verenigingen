#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Test Data Factory
Builds on Frappe's FrappeTestCase to provide business rule validation and field safety
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from faker import Faker

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_days, add_months, getdate, random_string

from .field_validator import FieldValidator, validate_field


class BusinessRuleError(Exception):
    """Raised when business rule validation fails"""
    pass


class EnhancedTestDataFactory:
    """
    Enhanced test data factory that builds on Frappe's testing infrastructure
    
    Key features:
    - Inherits FrappeTestCase benefits: automatic rollback, query monitoring, state isolation
    - Adds business rule validation to prevent impossible test scenarios
    - Uses Faker for realistic but clearly marked test data
    - Schema-aware field validation
    - Deterministic data generation with seeds
    """
    
    def __init__(self, seed: int = 12345, use_faker: bool = True):
        """
        Initialize enhanced test data factory
        
        Args:
            seed: Random seed for deterministic data generation
            use_faker: Whether to use Faker for realistic test data
        """
        # Set deterministic seed
        random.seed(seed)
        
        # Initialize Faker with deterministic seed
        # Create a new instance for each factory to ensure independence
        Faker.seed(seed)
        self.fake = Faker()
        self.fake.seed_instance(seed)
        self.use_faker = use_faker
        
        # Initialize validators
        self.field_validator = FieldValidator()
        
        # Track sequence counters for deterministic IDs
        self.sequence_counters = {}
        
        # Generate unique test run ID with microseconds for better uniqueness
        now = datetime.now()
        self.test_run_id = f"TEST-{random_string(8)}-{int(now.timestamp())}-{now.microsecond:06d}"
        
    def get_next_sequence(self, prefix: str) -> int:
        """Get next sequence number for deterministic data"""
        self.sequence_counters[prefix] = self.sequence_counters.get(prefix, 0) + 1
        return self.sequence_counters[prefix]
        
    def generate_test_email(self, purpose: str = "member") -> str:
        """Generate clearly marked test email"""
        seq = self.get_next_sequence(f'email_{purpose}')  # Purpose-specific sequence
        timestamp = int(datetime.now().timestamp())
        # Add microseconds for additional uniqueness within the same second
        microseconds = datetime.now().microsecond
        
        if self.use_faker:
            # Use Faker but clearly mark as test
            base_email = self.fake.email()
            username, domain = base_email.split('@')
            # Add sequence number, timestamp, microseconds, and test run ID to ensure uniqueness
            return f"TEST_{purpose}_{seq:04d}_{timestamp}_{microseconds:06d}_{username}_{self.test_run_id}@test.invalid"
        else:
            return f"TEST_{purpose}_{seq:04d}_{timestamp}_{microseconds:06d}_{self.test_run_id}@test.invalid"
            
    def generate_test_name(self, type_name: str = "Person") -> str:
        """Generate clearly marked test name"""
        if self.use_faker:
            fake_name = self.fake.name()
            return f"TEST {fake_name} [{type_name}]"
        else:
            seq = self.get_next_sequence('name')
            return f"TEST {type_name} {seq:04d}"
            
    def generate_test_phone(self) -> str:
        """Generate test phone number using reserved ranges"""
        # Generate a valid Dutch mobile number for testing
        # Format: +31 6 XXXXXXXX (8 digits after 6)
        seq = self.get_next_sequence('phone')
        # Use 90000000-99999999 range for test numbers
        test_number = 90000000 + seq
        return f"+31 6 {test_number}"
            
    def validate_field_exists(self, doctype: str, fieldname: str) -> bool:
        """Validate that field exists in doctype schema"""
        return self.field_validator.validate_field_exists(doctype, fieldname)
        
    def validate_member_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate member data against business rules"""
        if "birth_date" in data:
            birth_date = getdate(data["birth_date"])
            today = getdate()
            age = (today - birth_date).days / 365.25
            
            if age < 16:
                raise BusinessRuleError(f"Members must be 16+ years old (age: {age:.1f})")
            if age > 120:
                raise BusinessRuleError(f"Invalid birth date - age {age:.1f} years")
            if birth_date > today:
                raise BusinessRuleError("Birth date cannot be in the future")
                
        if "email" in data:
            email = data["email"]
            if not email or "@" not in email:
                raise BusinessRuleError("Valid email address required")
                
        return data
        
    def validate_volunteer_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate volunteer data against business rules"""
        if "start_date" in data and "member" in data:
            start_date = getdate(data["start_date"])
            member = frappe.get_doc("Member", data["member"])
            
            if member.birth_date:
                member_age_at_start = (start_date - getdate(member.birth_date)).days / 365.25
                if member_age_at_start < 16:
                    raise BusinessRuleError("Volunteers must be 16+ years old at start date")
                    
            # Volunteers must be 16+ at start date, so check age at start date
            # (This is the actual business rule, not join date)
                
        return data
        
    def validate_membership_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate membership data against business rules"""
        if "start_date" in data and "member" in data:
            start_date = getdate(data["start_date"])
            member = frappe.get_doc("Member", data["member"])
            
            if member.birth_date and start_date < getdate(member.birth_date):
                raise BusinessRuleError("Membership cannot start before member birth date")
                
        return data
        
    def create_member(self, **kwargs):
        """Create member with business rule and field validation"""
        # Fields that might be custom or runtime fields
        skip_validation_fields = {
            'chapter', 'suspension_reason', 'termination_reason', 
            'termination_date', 'join_date'
        }
        
        # Validate fields exist in Member doctype
        for field in kwargs.keys():
            if field not in skip_validation_fields:
                self.validate_field_exists("Member", field)
            
        # Set intelligent defaults
        defaults = {
            "first_name": self.generate_test_name("Member").split()[1],  # Just the first name part
            "last_name": self.generate_test_name("Member").split()[2],   # Just the last name part
            "email": self.generate_test_email("member"),
            "birth_date": add_days(getdate(), -random.randint(6570, 25550)),  # 18-70 years old
            "status": "Active",
            "contact_number": self.generate_test_phone()
        }
        
        # Merge with provided kwargs
        data = {**defaults, **kwargs}
        
        # Validate business rules
        data = self.validate_member_business_rules(data)
        
        # Validate required fields using meta
        try:
            meta = frappe.get_meta("Member")
            for field in meta.fields:
                if field.reqd and field.fieldname not in data:
                    if field.fieldtype == "Data":
                        data[field.fieldname] = f"Test-{field.fieldname}"
                    elif field.fieldtype == "Select" and field.options:
                        data[field.fieldname] = field.options.split("\n")[0]
        except (frappe.DoesNotExistError, AttributeError) as e:
            frappe.log_error(f"Failed to get Member meta for field validation: {e}", "EnhancedTestFactory")
            # Continue without meta validation - let document validation catch issues
        
        try:
            member = frappe.get_doc({
                "doctype": "Member",
                **data
            })
            
            # Insert using proper permissions (no ignore_permissions bypass)
            member.insert()
            return member
        except Exception as e:
            raise Exception(f"Failed to create member: {e}")
            
    def create_volunteer(self, member_name: str = None, **kwargs):
        """Create volunteer with business rule and field validation"""
        # Create member if not provided
        if not member_name:
            member = self.create_member()
            member_name = member.name
            
        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("Volunteer", field)
            
        # Set intelligent defaults
        defaults = {
            "volunteer_name": self.generate_test_name("Volunteer"),
            "email": self.generate_test_email("volunteer"),
            "member": member_name,
            "status": "Active",
            "start_date": getdate()
        }
        
        data = {**defaults, **kwargs}
        
        # Validate business rules
        data = self.validate_volunteer_business_rules(data)
        # Validate required fields using meta
        try:
            meta = frappe.get_meta("Volunteer")
            for field in meta.fields:
                if field.reqd and field.fieldname not in data:
                    if field.fieldtype == "Data":
                        data[field.fieldname] = f"Test-{field.fieldname}"
                    elif field.fieldtype == "Select" and field.options:
                        data[field.fieldname] = field.options.split("\n")[0]
        except (frappe.DoesNotExistError, AttributeError) as e:
            frappe.log_error(f"Failed to get Volunteer meta for field validation: {e}", "EnhancedTestFactory")
            # Continue without meta validation - let document validation catch issues
        
        try:
            volunteer = frappe.get_doc({
                "doctype": "Volunteer",
                **data
            })
            
            volunteer.insert()
            return volunteer
        except Exception as e:
            raise Exception(f"Failed to create volunteer: {e}")
            
    def create_chapter(self, **kwargs):
        """Create chapter with validation"""
        for field in kwargs.keys():
            self.validate_field_exists("Chapter", field)
            
        defaults = {
            "name": f"TEST-Chapter-{self.get_next_sequence('chapter')}-{self.test_run_id[:8]}",
            "region": self.fake.state() if self.use_faker else f"TestRegion-{self.get_next_sequence('region')}",
            "postal_codes": f"{1000 + self.get_next_sequence('postal'):04d}",
            "introduction": f"Test chapter created by EnhancedTestDataFactory - {self.test_run_id}"
        }
        
        data = {**defaults, **kwargs}
        # Validate required fields using meta
        try:
            meta = frappe.get_meta("Chapter")
            for field in meta.fields:
                if field.reqd and field.fieldname not in data:
                    if field.fieldtype == "Data":
                        data[field.fieldname] = f"Test-{field.fieldname}"
                    elif field.fieldtype == "Select" and field.options:
                        data[field.fieldname] = field.options.split("\n")[0]
        except (frappe.DoesNotExistError, AttributeError) as e:
            frappe.log_error(f"Failed to get Chapter meta for field validation: {e}", "EnhancedTestFactory")
            # Continue without meta validation - let document validation catch issues
        
        try:
            chapter = frappe.get_doc({
                "doctype": "Chapter",
                **data
            })
            
            chapter.insert()
            return chapter
        except Exception as e:
            raise Exception(f"Failed to create chapter: {e}")
            
    def create_volunteer_skill(self, volunteer_name: str, skill_data: Dict[str, Any]):
        """Create volunteer skill with validation"""
        # Validate required skill data fields
        required_skill_fields = ["skill_category", "volunteer_skill"]
        for field in required_skill_fields:
            if field not in skill_data:
                raise ValueError(f"Required skill field '{field}' missing")
                
        # Validate fields exist
        for field in skill_data.keys():
            self.validate_field_exists("Volunteer Skill", field)
            
        defaults = {
            "proficiency_level": "3 - Intermediate",
            "experience_years": 1,
            "certifications": ""
        }
        
        data = {**defaults, **skill_data}
        # Validate required fields using meta
        try:
            meta = frappe.get_meta("Volunteer Skill")
            for field in meta.fields:
                if field.reqd and field.fieldname not in data:
                    if field.fieldtype == "Data":
                        data[field.fieldname] = f"Test-{field.fieldname}"
                    elif field.fieldtype == "Select" and field.options:
                        data[field.fieldname] = field.options.split("\n")[0]
        except (frappe.DoesNotExistError, AttributeError) as e:
            frappe.log_error(f"Failed to get Volunteer Skill meta for field validation: {e}", "EnhancedTestFactory")
            # Continue without meta validation - let document validation catch issues
        
        try:
            skill = frappe.get_doc({
                "doctype": "Volunteer Skill",
                "parent": volunteer_name,
                "parenttype": "Volunteer",
                "parentfield": "skills_and_qualifications",
                **data
            })
            
            skill.insert()
            return skill
        except Exception as e:
            raise Exception(f"Failed to create volunteer skill: {e}")
            
    def create_application_data(self, with_volunteer_skills: bool = True) -> Dict[str, Any]:
        """Create deterministic membership application data"""
        seq = self.get_next_sequence('application')
        
        base_data = {
            "first_name": self.fake.first_name() if self.use_faker else f"AppTest{seq:04d}",
            "last_name": self.fake.last_name() if self.use_faker else f"Member-{self.test_run_id[:8]}",
            "email": self.generate_test_email("application"),
            "birth_date": "1990-01-01",
            "address_line1": self.fake.street_address() if self.use_faker else f"{seq} Test Street",
            "city": self.fake.city() if self.use_faker else "Test City",
            "country": "Netherlands",
            "postal_code": f"{1000 + seq:04d}AB"
        }
        
        if with_volunteer_skills:
            # Deterministic skill selection
            all_skills = [
                "Technical|Web Development",
                "Technical|Graphic Design", 
                "Communication|Writing",
                "Leadership|Team Leadership",
                "Financial|Fundraising",
                "Organizational|Event Planning",
                "Other|Photography"
            ]
            
            # Select skills deterministically based on sequence
            num_skills = (seq % 3) + 4  # 4-6 skills
            skills = all_skills[:num_skills]
            
            volunteer_data = {
                "interested_in_volunteering": True,
                "volunteer_availability": ["Weekly", "Monthly", "Quarterly"][seq % 3],
                "volunteer_experience_level": ["Beginner", "Intermediate", "Experienced"][seq % 3],
                "volunteer_areas": ["events", "communications"],
                "volunteer_skills": skills,
                "volunteer_skill_level": str(((seq % 5) + 1)),  # 1-5
                "volunteer_availability_time": "Weekends and evenings",
                "volunteer_comments": f"Test volunteer application {seq}"
            }
            
            base_data.update(volunteer_data)
            
        return base_data
        
    def create_test_iban(self, bank_code: str = None) -> str:
        """Generate deterministic test IBAN"""
        if not bank_code:
            # Use deterministic selection instead of random
            bank_codes = ["TEST", "MOCK", "DEMO"]
            bank_code = bank_codes[self.get_next_sequence('bank') % len(bank_codes)]
            
        # Generate deterministic account number
        account_number = f"{self.get_next_sequence('account'):010d}"
        
        try:
            from verenigingen.utils.iban_validator import generate_test_iban
            return generate_test_iban(bank_code, account_number)
        except ImportError:
            # Fallback if IBAN validator not available
            return f"NL{self.get_next_sequence('fallback_iban'):02d}{bank_code}0{account_number[:10]}"
    
    def ensure_test_chapter(self, chapter_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a test chapter exists, create if not"""
        if frappe.db.exists("Chapter", chapter_name):
            return frappe.get_doc("Chapter", chapter_name)
        
        # Check if region exists, if not use a default one
        region = attributes.get("region") if attributes else None
        if not region:
            # Try to find an existing region
            existing_regions = frappe.get_all("Region", limit=1)
            if existing_regions:
                region = existing_regions[0].name
            else:
                # Create a test region if none exist
                test_region = frappe.get_doc({
                    "doctype": "Region",
                    "region_name": "Test Region"
                })
                test_region.insert()
                region = test_region.name
        
        chapter_data = {
            "doctype": "Chapter",
            "name": chapter_name,
            "chapter_name": chapter_name,
            "short_name": attributes.get("short_name", "TST") if attributes else "TST",
            "country": attributes.get("country", "Netherlands") if attributes else "Netherlands",
            "published": attributes.get("published", 1) if attributes else 1,
            # Required fields for chapter
            "introduction": attributes.get("introduction", "Test chapter for automated testing") if attributes else "Test chapter for automated testing",
            "contact_email": attributes.get("contact_email", "test@example.com") if attributes else "test@example.com"
        }
        
        if region:
            chapter_data["region"] = region
        
        if attributes:
            # Don't override the defaults we just set
            for key, value in attributes.items():
                if key not in ['introduction', 'contact_email'] or value:
                    chapter_data[key] = value
        
        chapter = frappe.get_doc(chapter_data)
        chapter.insert()
        return chapter
    
    def ensure_membership_type(self, type_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a membership type exists, create if not"""
        if frappe.db.exists("Membership Type", type_name):
            return frappe.get_doc("Membership Type", type_name)
        
        type_data = {
            "doctype": "Membership Type",
            "membership_type_name": type_name,
            "amount": attributes.get("amount", 50.00) if attributes else 50.00,
            "currency": attributes.get("currency", "EUR") if attributes else "EUR",
            "is_active": attributes.get("is_active", 1) if attributes else 1,
            "membership_fee": attributes.get("amount", 50.00) if attributes else 50.00  # Some systems use this field
        }
        
        if attributes:
            type_data.update(attributes)
        
        membership_type = frappe.get_doc(type_data)
        membership_type.insert()
        return membership_type
    
    def ensure_chapter_role(self, role_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a chapter role exists, create if not"""
        if frappe.db.exists("Chapter Role", role_name):
            return frappe.get_doc("Chapter Role", role_name)
        
        role_data = {
            "doctype": "Chapter Role",
            "role_name": role_name,
            "permissions_level": attributes.get("permissions_level", "Basic") if attributes else "Basic",
            "is_chair": attributes.get("is_chair", 0) if attributes else 0,
            "is_unique": attributes.get("is_unique", 0) if attributes else 0,
            "is_active": attributes.get("is_active", 1) if attributes else 1
        }
        
        if attributes:
            role_data.update(attributes)
        
        role = frappe.get_doc(role_data)
        role.insert()
        return role
    
    def ensure_team_role(self, role_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a team role exists, create if not"""
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        
        # Default team role configurations
        role_configs = {
            "Team Leader": {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1},
            "Team Member": {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0},
            "Coordinator": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0},
            "Secretary": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1},
            "Treasurer": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1}
        }
        
        config = role_configs.get(role_name, {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0})
        
        role_data = {
            "doctype": "Team Role",
            "role_name": role_name,
            "description": f"{role_name} role for team management",
            "is_active": 1,
            **config
        }
        
        if attributes:
            role_data.update(attributes)
        
        role = frappe.get_doc(role_data)
        role.insert()
        return role
    
    def create_team(self, **kwargs):
        """Create team with validation"""
        for field in kwargs.keys():
            self.validate_field_exists("Team", field)
            
        defaults = {
            "team_name": f"TEST-Team-{self.get_next_sequence('team')}-{self.test_run_id[:8]}",
            "status": "Active",
            "team_type": "Project Team",
            "start_date": frappe.utils.today(),
            "description": f"Test team created by EnhancedTestDataFactory - {self.test_run_id}"
        }
        
        data = {**defaults, **kwargs}
        
        # Validate required fields using meta
        try:
            meta = frappe.get_meta("Team")
            for field in meta.fields:
                if field.reqd and field.fieldname not in data:
                    if field.fieldtype == "Data":
                        data[field.fieldname] = f"Test-{field.fieldname}"
                    elif field.fieldtype == "Select" and field.options:
                        data[field.fieldname] = field.options.split("\n")[0]
        except (frappe.DoesNotExistError, AttributeError) as e:
            frappe.log_error(f"Failed to get Team meta for field validation: {e}", "EnhancedTestFactory")
        
        try:
            team = frappe.get_doc({
                "doctype": "Team",
                **data
            })
            
            team.insert()
            return team
        except Exception as e:
            raise Exception(f"Failed to create team: {e}")
    
    def create_team_member(self, team_name: str, volunteer_name: str, team_role_name: str = "Team Member", **kwargs):
        """Create team member with new team_role field structure"""
        # Ensure team role exists
        team_role = self.ensure_team_role(team_role_name)
        
        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("Team Member", field)
            
        defaults = {
            "volunteer": volunteer_name,
            "team_role": team_role.name,  # Use new team_role field
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active"
        }
        
        data = {**defaults, **kwargs}
        
        # Get team and add member
        team = frappe.get_doc("Team", team_name)
        team.append("team_members", data)
        team.save()
        
        return team.team_members[-1]  # Return the added team member record


class EnhancedTestCase(FrappeTestCase):
    """
    Enhanced test case that combines FrappeTestCase benefits with our enhancements
    
    Provides:
    - Automatic database rollback (from FrappeTestCase)
    - Query count monitoring (from FrappeTestCase)
    - Permission testing support (from FrappeTestCase)
    - Global state isolation (from FrappeTestCase)
    - Business rule validation (our addition)
    - Field validation (our addition)
    - Realistic test data (our addition)
    """
    
    def setUp(self):
        super().setUp()
        self.factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        
    def create_test_member(self, **kwargs):
        """Convenience method for creating test members"""
        return self.factory.create_member(**kwargs)
        
    def create_test_volunteer(self, member_name=None, **kwargs):
        """Convenience method for creating test volunteers"""
        return self.factory.create_volunteer(member_name, **kwargs)
        
    def create_test_application_data(self, with_skills=True):
        """Convenience method for creating application data"""
        return self.factory.create_application_data(with_volunteer_skills=with_skills)
        
    def create_test_team(self, **kwargs):
        """Convenience method for creating test teams"""
        return self.factory.create_team(**kwargs)
        
    def create_test_team_member(self, team_name, volunteer_name, team_role_name="Team Member", **kwargs):
        """Convenience method for creating test team members"""
        return self.factory.create_team_member(team_name, volunteer_name, team_role_name, **kwargs)
        
    def ensure_team_role(self, role_name, attributes=None):
        """Convenience method for ensuring team roles exist"""
        return self.factory.ensure_team_role(role_name, attributes)
        
    def assertBusinessRuleViolation(self, callable_obj, *args, **kwargs):
        """Assert that a business rule violation occurs"""
        with self.assertRaises(BusinessRuleError):
            callable_obj(*args, **kwargs)
            
    def assertFieldValidationError(self, callable_obj, *args, **kwargs):
        """Assert that a field validation error occurs"""
        from verenigingen.tests.fixtures.field_validator import FieldValidationError
        with self.assertRaises(FieldValidationError):
            callable_obj(*args, **kwargs)


# Convenience decorators
def with_enhanced_test_data(seed=12345, use_faker=True):
    """Decorator for test methods that need enhanced test data"""
    def decorator(test_method):
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, 'factory'):
                self.factory = EnhancedTestDataFactory(seed=seed, use_faker=use_faker)
            return test_method(self, *args, **kwargs)
        return wrapper
    return decorator


def validate_business_rules(doctype):
    """Decorator to ensure business rule validation is performed"""
    def decorator(test_method):
        def wrapper(self, *args, **kwargs):
            # This decorator could add additional validation
            # For now, it's a placeholder for future enhancements
            return test_method(self, *args, **kwargs)
        return wrapper
    return decorator


if __name__ == "__main__":
    # Example usage and testing
    print("Testing EnhancedTestDataFactory...")
    
    try:
        factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        
        # Test business rule validation
        print("Testing business rule validation...")
        
        # This should work
        member = factory.create_member(
            first_name="Test",
            last_name="User",
            birth_date="1990-01-01"
        )
        print(f"✅ Created valid member: {member.name}")
        
        # This should fail - too young
        try:
            factory.create_member(birth_date="2020-01-01")
            print("❌ Should have failed for too young member")
        except BusinessRuleError as e:
            print(f"✅ Correctly caught business rule violation: {e}")
            
        # Test field validation
        print("Testing field validation...")
        try:
            factory.create_member(nonexistent_field="value")
            print("❌ Should have failed for nonexistent field")
        except Exception as e:
            print(f"✅ Correctly caught field validation error: {e}")
            
        print("✅ EnhancedTestDataFactory validation completed successfully")
        
    except Exception as e:
        print(f"❌ EnhancedTestDataFactory test failed: {e}")
        raise