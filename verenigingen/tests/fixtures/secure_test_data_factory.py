#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Secure Test Data Factory
Enhanced test data factory with proper security, validation, and reliability
"""

import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import frappe
from frappe.utils import now_datetime, add_days, add_months, getdate, random_string

# Note: Base TestDataFactory available but not importing to avoid dependency issues


class TestCleanupError(Exception):
    """Raised when test data cleanup fails"""
    pass


class SchemaValidationError(Exception):
    """Raised when field validation fails"""
    pass


class SecureTestDataFactory:
    """
    Enhanced test data factory with security, validation, and deterministic data generation
    
    Key improvements:
    - Proper permission handling without bypassing security
    - Schema-aware field validation
    - Deterministic data generation
    - Robust cleanup with verification
    - Field reference safety
    """
    
    def __init__(self, 
                 test_user: str = "Administrator", 
                 seed: int = 12345,
                 cleanup_on_exit: bool = True):
        """
        Initialize secure test data factory
        
        Args:
            test_user: User to impersonate for test data creation
            seed: Random seed for deterministic data generation
            cleanup_on_exit: Whether to automatically cleanup on exit
        """
        self.original_user = frappe.session.user
        self.test_user = test_user
        self.cleanup_on_exit = cleanup_on_exit
        self.created_records = []
        self.sequence_counters = {}
        self.doctype_schemas = {}
        
        # Set deterministic seed for reproducible tests
        random.seed(seed)
        
        # Set test user (but don't bypass permissions)
        frappe.set_user(self.test_user)
        
        # Generate unique test run ID
        self.test_run_id = f"TEST-{random_string(8)}-{int(datetime.now().timestamp())}"
        
    def __enter__(self):
        """Context manager entry"""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        if self.cleanup_on_exit:
            self.cleanup_with_verification()
        
        # Restore original user
        frappe.set_user(self.original_user)
        
    def get_schema(self, doctype: str) -> Dict[str, Any]:
        """Get cached schema for doctype"""
        if doctype not in self.doctype_schemas:
            try:
                meta = frappe.get_meta(doctype)
                self.doctype_schemas[doctype] = {
                    f.fieldname: f for f in meta.fields
                }
            except Exception as e:
                raise SchemaValidationError(f"Could not load schema for {doctype}: {e}")
                
        return self.doctype_schemas[doctype]
        
    def validate_field_exists(self, doctype: str, fieldname: str) -> bool:
        """Validate that field exists in doctype schema"""
        schema = self.get_schema(doctype)
        if fieldname not in schema:
            raise SchemaValidationError(f"Field '{fieldname}' doesn't exist in {doctype}")
        return True
        
    def validate_required_fields(self, doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required fields have values"""
        try:
            meta = frappe.get_meta(doctype)
            required_fields = [f.fieldname for f in meta.fields if f.reqd]
            
            for field in required_fields:
                if field not in data or data[field] is None:
                    default_value = self.get_default_value_for_field(doctype, field)
                    if default_value is not None:
                        data[field] = default_value
                        
            return data
        except Exception as e:
            raise SchemaValidationError(f"Required field validation failed for {doctype}: {e}")
            
    def get_default_value_for_field(self, doctype: str, fieldname: str) -> Any:
        """Get appropriate default value for field based on type"""
        try:
            schema = self.get_schema(doctype)
            if fieldname not in schema:
                return None
                
            field = schema[fieldname]
            fieldtype = field.fieldtype
            
            # Provide sensible defaults based on field type
            defaults = {
                'Data': f"Test-{self.get_next_sequence('data')}",
                'Text': f"Test text content {self.get_next_sequence('text')}",
                'Check': 0,
                'Int': 0,
                'Float': 0.0,
                'Currency': 0.0,
                'Date': getdate(),
                'Datetime': now_datetime(),
                'Select': field.options.split('\n')[0] if field.options else '',
                'Link': None,  # Links require special handling
                'Email': f"test{self.get_next_sequence('email')}@example.com"
            }
            
            return defaults.get(fieldtype, None)
        except Exception:
            return None
            
    def get_next_sequence(self, prefix: str) -> int:
        """Get next sequence number for deterministic data"""
        self.sequence_counters[prefix] = self.sequence_counters.get(prefix, 0) + 1
        return self.sequence_counters[prefix]
        
    def track_record(self, doctype: str, name: str):
        """Track created record for cleanup"""
        self.created_records.append({"doctype": doctype, "name": name})
        
    def create_member(self, **kwargs):
        """Create member with schema validation and proper permissions"""
        # Validate fields exist in Member doctype
        for field in kwargs.keys():
            self.validate_field_exists("Member", field)
            
        # Set default required fields
        defaults = {
            "first_name": f"TestMember{self.get_next_sequence('member')}",
            "last_name": f"Generated-{self.test_run_id[:8]}",
            "email": f"testmember{self.get_next_sequence('email')}_{self.test_run_id}@test.example",
            "birth_date": add_days(getdate(), -9000),  # ~25 years old
            "status": "Active"
        }
        
        # Merge with provided kwargs
        data = {**defaults, **kwargs}
        
        # Validate required fields
        data = self.validate_required_fields("Member", data)
        
        try:
            member = frappe.get_doc({
                "doctype": "Member",
                **data
            })
            
            # Insert without bypassing permissions
            member.insert()
            self.track_record("Member", member.name)
            
            return member
        except Exception as e:
            raise Exception(f"Failed to create member: {e}")
            
    def create_volunteer(self, member_name: str = None, **kwargs):
        """Create volunteer with schema validation"""
        # Create member if not provided
        if not member_name:
            member = self.create_member()
            member_name = member.name
            
        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("Volunteer", field)
            
        # Set defaults
        defaults = {
            "volunteer_name": f"TestVolunteer{self.get_next_sequence('volunteer')}",
            "email": f"volunteer{self.get_next_sequence('vol_email')}_{self.test_run_id}@test.example",
            "member": member_name,
            "status": "Active",
            "start_date": getdate()
        }
        
        data = {**defaults, **kwargs}
        data = self.validate_required_fields("Verenigingen Volunteer", data)
        
        try:
            volunteer = frappe.get_doc({
                "doctype": "Volunteer",
                **data
            })
            
            volunteer.insert()
            self.track_record("Verenigingen Volunteer", volunteer.name)
            
            return volunteer
        except Exception as e:
            raise Exception(f"Failed to create volunteer: {e}")
            
    def create_chapter(self, **kwargs):
        """Create chapter with validation"""
        for field in kwargs.keys():
            self.validate_field_exists("Chapter", field)
            
        defaults = {
            "name": f"TestChapter-{self.get_next_sequence('chapter')}-{self.test_run_id[:8]}",
            "region": f"TestRegion-{self.get_next_sequence('region')}",
            "postal_codes": f"{1000 + self.get_next_sequence('postal'):04d}",
            "introduction": f"Test chapter created by SecureTestDataFactory - {self.test_run_id}"
        }
        
        data = {**defaults, **kwargs}
        data = self.validate_required_fields("Chapter", data)
        
        try:
            chapter = frappe.get_doc({
                "doctype": "Chapter",
                **data
            })
            
            chapter.insert()
            self.track_record("Chapter", chapter.name)
            
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
        data = self.validate_required_fields("Volunteer Skill", data)
        
        try:
            skill = frappe.get_doc({
                "doctype": "Volunteer Skill",
                "parent": volunteer_name,
                "parenttype": "Verenigingen Volunteer",
                "parentfield": "skills_and_qualifications",
                **data
            })
            
            skill.insert()
            self.track_record("Volunteer Skill", skill.name)
            
            return skill
        except Exception as e:
            raise Exception(f"Failed to create volunteer skill: {e}")
            
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
            
    def cleanup_with_verification(self) -> None:
        """Clean up all created records with verification"""
        print(f"🧹 Cleaning up {len(self.created_records)} test records...")
        
        failed_deletions = []
        successful_deletions = 0
        
        # Clean up in reverse order to respect dependencies
        for record in reversed(self.created_records):
            try:
                if frappe.db.exists(record["doctype"], record["name"]):
                    frappe.delete_doc(record["doctype"], record["name"])
                    
                    # Verify deletion
                    if frappe.db.exists(record["doctype"], record["name"]):
                        failed_deletions.append(record)
                    else:
                        successful_deletions += 1
                else:
                    # Record already deleted
                    successful_deletions += 1
                    
            except Exception as e:
                failed_deletions.append({**record, "error": str(e)})
                
        # Commit deletions
        frappe.db.commit()
        
        # Report results
        print(f"✅ Successfully deleted {successful_deletions} records")
        
        if failed_deletions:
            print(f"⚠️  Failed to delete {len(failed_deletions)} records:")
            for failure in failed_deletions:
                error = failure.get("error", "Unknown error")
                print(f"   - {failure['doctype']} {failure['name']}: {error}")
            
            raise TestCleanupError(f"Failed to delete {len(failed_deletions)} records")
            
        self.created_records = []
        
    def create_application_data(self, with_volunteer_skills: bool = True) -> Dict[str, Any]:
        """Create deterministic membership application data"""
        seq = self.get_next_sequence('application')
        
        base_data = {
            "first_name": f"AppTest{seq:04d}",
            "last_name": f"Member-{self.test_run_id[:8]}",
            "email": f"app{seq:04d}_{self.test_run_id}@test.example",
            "birth_date": "1990-01-01",
            "address_line1": f"{seq} Test Street",
            "city": "Test City",
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
            num_skills = (seq % 3) + 4  # 4-6 skills to include Financial|Fundraising
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


class SecureTestContext:
    """Context manager for secure test data with automatic cleanup"""
    
    def __init__(self, test_user: str = "Administrator", seed: int = 12345):
        self.test_user = test_user
        self.seed = seed
        self.factory = None
        
    def __enter__(self) -> SecureTestDataFactory:
        self.factory = SecureTestDataFactory(
            test_user=self.test_user,
            seed=self.seed,
            cleanup_on_exit=True
        )
        return self.factory
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.factory:
            self.factory.cleanup_with_verification()


# Convenience functions
def create_secure_factory(test_user: str = "Administrator", seed: int = 12345) -> SecureTestDataFactory:
    """Create secure test data factory"""
    return SecureTestDataFactory(test_user=test_user, seed=seed)


def with_secure_test_data(test_user: str = "Administrator", seed: int = 12345):
    """Decorator for test methods that need secure test data"""
    def decorator(test_method):
        def wrapper(self, *args, **kwargs):
            with SecureTestContext(test_user=test_user, seed=seed) as factory:
                return test_method(self, factory, *args, **kwargs)
        return wrapper
    return decorator


if __name__ == "__main__":
    # Example usage
    print("Testing SecureTestDataFactory...")
    
    try:
        with SecureTestContext(seed=12345) as factory:
            # Create test data
            member = factory.create_member(first_name="Secure", last_name="Test")
            print(f"Created member: {member.name}")
            
            volunteer = factory.create_volunteer(member.name, volunteer_name="Secure Volunteer")
            print(f"Created volunteer: {volunteer.name}")
            
            # Create application data
            app_data = factory.create_application_data()
            print(f"Created application data for: {app_data['email']}")
            
            # Test will automatically cleanup on exit
            
        print("✅ SecureTestDataFactory test completed successfully")
        
    except Exception as e:
        print(f"❌ SecureTestDataFactory test failed: {e}")
        raise