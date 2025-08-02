"""
Streamlined Test Data Factory for Verenigingen
==============================================

Legacy test data factory that provides comprehensive test data creation capabilities
for the Verenigingen association management system. This factory focuses on volume
and convenience over validation, making it suitable for integration testing and
performance scenarios.

Evolution and Architecture
-------------------------
This factory was created during Phase 4.3 Factory Method Streamlining to reduce
complexity while maintaining comprehensive test data creation capabilities. It has
since been superseded by the EnhancedTestDataFactory for most use cases.

Design Philosophy
----------------
- **Volume over Validation**: Prioritizes creating large amounts of test data quickly
- **Convenience over Safety**: Uses ignore_permissions=True for speed (now discouraged)
- **Faker Integration**: Generates realistic but deterministic test data
- **Context Manager Support**: Provides automatic cleanup via context managers
- **Scenario Building**: Includes pre-built scenarios for common testing needs

Core Capabilities
----------------
1. **Core Business Objects**: Creates all major DocTypes (Member, Chapter, Volunteer, etc.)
2. **Relationship Management**: Handles complex relationships between DocTypes
3. **Scenario Generation**: Provides complete business scenarios for testing
4. **Edge Case Creation**: Generates edge case data for comprehensive testing
5. **Stress Testing**: Creates large datasets for performance testing
6. **Cleanup Management**: Automatic cleanup of created test data

Key Features
-----------
- **Deterministic Generation**: Uses configurable seeds for reproducible data
- **Intelligent Defaults**: Provides sensible defaults for all required fields
- **Bulk Creation**: Efficiently creates multiple related records
- **Status Distribution**: Creates realistic status distributions across entities
- **Team Role Management**: Handles complex team role assignments
- **SEPA Integration**: Creates valid SEPA mandates with test IBANs

Usage Patterns
-------------
```python
# Basic usage with context manager (recommended)
with StreamlinedTestDataFactory(cleanup_on_exit=True) as factory:
    member = factory.create_test_member()
    volunteer = factory.create_test_volunteer(member=member)

# Complete scenario creation
scenario = factory.create_complete_test_scenario(member_count=50)

# Edge case testing
edge_cases = factory.create_edge_case_data()

# Performance testing
stress_data = factory.create_stress_test_data(scale="large")
```

Migration Considerations
-----------------------
**Important**: This factory is being phased out in favor of EnhancedTestDataFactory
for new tests. Key differences:

- **Legacy Factory**: Uses ignore_permissions=True (security bypass)
- **Enhanced Factory**: Uses proper permissions and validation
- **Legacy Factory**: Optimized for speed and volume
- **Enhanced Factory**: Optimized for safety and validation

**Migration Path**:
1. Use EnhancedTestDataFactory for new tests requiring validation
2. Keep StreamlinedTestDataFactory for performance tests and bulk data
3. Gradually migrate existing tests to use enhanced validation

Performance Characteristics
--------------------------
- **Creation Speed**: Very fast due to permission bypasses
- **Memory Usage**: Moderate due to caching of common objects
- **Cleanup Efficiency**: Good due to reverse dependency tracking
- **Scale Support**: Excellent - can create thousands of records efficiently

Data Quality and Validation
---------------------------
**Strengths**:
- Generates realistic data using Faker library
- Maintains referential integrity between related records
- Provides comprehensive edge case scenarios
- Includes proper IBAN generation with checksums

**Limitations**:
- Bypasses Frappe validation (ignore_permissions=True)
- Does not validate business rules during creation
- May create data that wouldn't be valid in production
- Requires manual validation of business rule compliance

Cleanup and Resource Management
------------------------------
The factory includes comprehensive cleanup capabilities:

- **Dependency Tracking**: Tracks all created records for cleanup
- **Reverse Order Cleanup**: Deletes records in reverse dependency order
- **Context Manager Support**: Automatic cleanup when used as context manager
- **Manual Cleanup**: Explicit cleanup() method for fine-grained control

Test Scenario Capabilities
--------------------------
1. **Complete Business Scenarios**: Full member lifecycle with all relationships
2. **Edge Case Data**: Extreme values and boundary conditions
3. **Conflict Scenarios**: Data designed to trigger validation errors
4. **Status Distribution**: Realistic distributions of entity statuses
5. **Team Management**: Complex team structures with role hierarchies
6. **Billing Scenarios**: Various billing frequency and amount combinations

Integration with Testing Infrastructure
--------------------------------------
The factory integrates with:

- Frappe's permission system (though bypassed for speed)
- Faker library for realistic data generation
- Test cleanup mechanisms
- Performance measurement tools
- Bulk testing frameworks

IBAN and Banking Test Data
--------------------------
Includes sophisticated banking test data generation:

- **Valid IBAN Generation**: Creates IBANs with proper MOD-97 checksums
- **BIC Derivation**: Generates corresponding BIC codes
- **Test Bank Codes**: Uses reserved bank codes (TEST, MOCK, DEMO)
- **SEPA Compliance**: Creates SEPA-compliant mandate structures

Security Considerations
----------------------
**Warning**: This factory uses security bypasses for performance:

- `ignore_permissions=True` bypasses Frappe's permission system
- `force=True` bypasses deletion constraints
- Test data may not respect production security rules

**Recommendations**:
- Use only in isolated test environments
- Do not use patterns from this factory in production code
- Migrate to EnhancedTestDataFactory for security-conscious testing

Maintenance and Evolution
------------------------
**Current Status**: Legacy but maintained for compatibility
**Future Direction**: Gradual migration to EnhancedTestDataFactory
**Deprecation Timeline**: No immediate deprecation planned due to performance needs

**Maintenance Guidelines**:
- Bug fixes only - no new features
- Performance optimizations acceptable
- Security improvements encouraged
- Documentation updates as needed

Testing and Quality Assurance
-----------------------------
The factory includes self-testing capabilities:

- Validation of generated IBAN checksums
- Verification of relationship consistency
- Edge case scenario validation
- Performance benchmarking support

Version History
--------------
- Phase 4.3: Created during factory method streamlining
- Enhanced with scenario builders and edge case support
- Added team role management and SEPA integration
- Improved cleanup mechanisms and context manager support
"""

import random
from datetime import datetime, date
from typing import Dict, List, Optional, Any

import frappe
from frappe.utils import add_days, random_string, today, flt
from faker import Faker


class StreamlinedTestDataFactory:
    """Streamlined factory for creating consistent test data with intelligent defaults"""

    def __init__(self, cleanup_on_exit=True, seed=None):
        """Initialize factory with optional seed for reproducible data"""
        self.cleanup_on_exit = cleanup_on_exit
        self.created_records = []
        self.test_run_id = f"{random_string(8)}-{int(datetime.now().timestamp())}"
        
        # Initialize Faker with seed for reproducible data
        self.fake = Faker()
        if seed:
            Faker.seed(seed)
            random.seed(seed)
        
        # Cache for frequently used test data
        self._test_chapters = None
        self._test_membership_types = None
        self._test_region = None

    def cleanup(self):
        """Clean up all created test data in reverse dependency order"""
        print(f"🧹 Cleaning up {len(self.created_records)} test records...")

        # Clean up in reverse order to respect dependencies
        for record in reversed(self.created_records):
            try:
                if frappe.db.exists(record["doctype"], record["name"]):
                    doc = frappe.get_doc(record["doctype"], record["name"])
                    doc.delete(ignore_permissions=True, force=True)
            except Exception as e:
                print(f"⚠️  Failed to delete {record['doctype']} {record['name']}: {e}")

        self.created_records = []

    def track_doc(self, doctype: str, name: str):
        """Track a created record for cleanup"""
        self.created_records.append({"doctype": doctype, "name": name})

    # HELPER METHOD: Region Creation
    def create_test_region(self, **kwargs):
        """Create a test region required for chapter creation"""
        region_name = f"Test Region {self.fake.state()} - {self.test_run_id}"
        region_code = f"TR{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=2))}"
        
        # Ensure region code is unique
        counter = 1
        base_code = region_code
        while frappe.db.exists("Region", {"region_code": region_code}):
            region_code = f"{base_code}{counter}"
            counter += 1
        
        defaults = {
            "region_name": region_name,
            "region_code": region_code,
            "country": "Netherlands",
            "is_active": 1,
            "description": f"Test region created for automated testing - {self.test_run_id}",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam"
        }
        defaults.update(kwargs)
        
        region = frappe.get_doc({"doctype": "Region", **defaults})
        region.insert(ignore_permissions=True)
        self.track_doc("Region", region.name)
        return region

    def get_or_create_test_region(self):
        """Get cached test region or create new one"""
        if self._test_region is None:
            # Try to find existing test region first
            existing_regions = frappe.get_all("Region", 
                filters={"region_code": "TRTX"}, 
                limit=1)
            
            if existing_regions:
                self._test_region = frappe.get_doc("Region", existing_regions[0].name)
            else:
                self._test_region = self.create_test_region()
        return self._test_region

    # CORE METHOD 1: Chapter Creation
    def create_test_chapter(self, **kwargs):
        """Create a single test chapter with intelligent defaults"""
        # Generate unique chapter name for Frappe's prompt autoname
        chapter_name = f"Test Chapter {self.fake.city()} - {self.test_run_id}"
        
        # Ensure we have a test region available
        test_region = self.get_or_create_test_region()
        
        defaults = {
            "chapter_name": chapter_name,
            "region": test_region.name,  # Use actual test region
            "postal_codes": "1000-1099",  # Use valid Dutch postal code range for testing
            "introduction": f"Test chapter created for automated testing - {self.test_run_id}",
            "email": self.fake.email(),
            "phone": self.fake.phone_number()[:15]  # Frappe field limit
        }
        defaults.update(kwargs)
        
        chapter = frappe.get_doc({"doctype": "Chapter", **defaults})
        # Set explicit name for prompt autoname doctype
        chapter.name = chapter_name
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)
        return chapter

    def create_test_chapters(self, count: int = 5, **kwargs):
        """Create multiple test chapters"""
        return [self.create_test_chapter(**kwargs) for _ in range(count)]

    # CORE METHOD 2: Member Creation
    def create_test_member(self, chapter=None, **kwargs):
        """Create a single test member with intelligent defaults"""
        if chapter is None:
            chapter = self.get_or_create_test_chapter()
        
        defaults = {
            "first_name": self.fake.first_name(),
            "last_name": self.fake.last_name(),
            "email": self.fake.email(),
            "birth_date": self.fake.date_of_birth(minimum_age=18, maximum_age=80),
            "phone": self.fake.phone_number()[:15],
            "status": "Active",
            # Address fields
            "address_line_1": self.fake.street_address(),
            "city": self.fake.city(),
            "postal_code": self.fake.zipcode(),
            "country": "Netherlands"
        }
        defaults.update(kwargs)
        
        member = frappe.get_doc({"doctype": "Member", **defaults})
        member.insert(ignore_permissions=True)
        self.track_doc("Member", member.name)
        
        # Create chapter membership relationship
        if chapter:
            chapter_name = chapter.name if hasattr(chapter, 'name') else chapter
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            chapter_doc.append("members", {
                "member": member.name,
                "enabled": 1,
                "chapter_join_date": frappe.utils.today(),
                "status": "Active"
            })
            chapter_doc.save(ignore_permissions=True)
        
        return member

    def create_test_members(self, count: int = 10, chapters=None, **kwargs):
        """Create multiple test members distributed across chapters"""
        if chapters is None:
            chapters = self.get_or_create_test_chapters(max(1, count // 5))
        
        members = []
        for i in range(count):
            chapter = chapters[i % len(chapters)]
            member = self.create_test_member(chapter=chapter, **kwargs)
            members.append(member)
        
        return members

    def create_test_memberships(self, count: int = 10, members=None, **kwargs):
        """Create multiple test memberships for bulk testing"""
        if members is None:
            members = self.create_test_members(count=count)
        
        memberships = []
        membership_type = self.get_or_create_test_membership_type()
        
        for i, member in enumerate(members[:count]):
            membership = self.create_test_membership(
                member=member,
                membership_type=membership_type,
                **kwargs
            )
            memberships.append(membership)
        
        return memberships

    # CORE METHOD 3: Membership Creation
    def create_test_membership(self, member=None, membership_type=None, **kwargs):
        """Create a single test membership with intelligent defaults"""
        if member is None:
            member = self.create_test_member()
        if membership_type is None:
            membership_type = self.get_or_create_test_membership_type()
        
        defaults = {
            "member": member.name if hasattr(member, 'name') else member,
            "membership_type": membership_type.name if hasattr(membership_type, 'name') else membership_type,
            "status": "Active",
            "start_date": today(),
            "end_date": add_days(today(), 365)
        }
        defaults.update(kwargs)
        
        membership = frappe.get_doc({"doctype": "Membership", **defaults})
        membership.insert(ignore_permissions=True)
        self.track_doc("Membership", membership.name)
        return membership

    # CORE METHOD 4: Membership Type Creation  
    def create_test_membership_type(self, **kwargs):
        """Create membership type with intelligent defaults"""
        # Use existing template if not provided
        if 'dues_schedule_template' not in kwargs:
            # Find an existing template we can use
            existing_template = frappe.db.get_value(
                "Membership Dues Schedule", 
                {"is_template": 1}, 
                "name", 
                order_by="creation desc"
            )
            if existing_template:
                kwargs['dues_schedule_template'] = existing_template
            else:
                # Fallback - this shouldn't happen in production data
                kwargs['dues_schedule_template'] = "Template-Annual"
        
        defaults = {
            "membership_type_name": f"Test Type {self.fake.word().title()} - {self.test_run_id}",
            "minimum_amount": flt(self.fake.random_int(min=25, max=200)),
            "is_active": 1,
            "billing_period": "Annual"
        }
        defaults.update(kwargs)
        
        membership_type = frappe.get_doc({"doctype": "Membership Type", **defaults})
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)
        return membership_type

    # CORE METHOD 5: Volunteer Creation
    def create_test_volunteer(self, member=None, **kwargs):
        """Create test volunteer with intelligent defaults"""
        if member is None:
            member = self.create_test_member()
        
        defaults = {
            "member": member.name if hasattr(member, 'name') else member,
            "volunteer_name": f"{member.first_name} {member.last_name}" if hasattr(member, 'first_name') else self.fake.name(),
            "email": self.fake.email(),
            "status": "Active",
            "start_date": today(),
            "skills": self.fake.sentence(nb_words=3)
        }
        defaults.update(kwargs)
        
        volunteer = frappe.get_doc({"doctype": "Volunteer", **defaults})
        volunteer.insert(ignore_permissions=True)
        self.track_doc("Volunteer", volunteer.name)
        return volunteer

    # CORE METHOD: Team Creation with Team Role Support
    def create_test_team(self, **kwargs):
        """Create test team with intelligent defaults"""
        team_name = f"Test Team {self.fake.company()} - {self.test_run_id}"
        
        defaults = {
            "team_name": team_name,
            "status": "Active", 
            "team_type": "Project Team",
            "start_date": today(),
            "description": f"Test team created for automated testing - {self.test_run_id}"
        }
        defaults.update(kwargs)
        
        team = frappe.get_doc({"doctype": "Team", **defaults})
        team.insert(ignore_permissions=True)
        self.track_doc("Team", team.name)
        return team

    def get_or_create_team_role(self, role_name="Team Member"):
        """Get existing team role or ensure fixture roles exist"""
        # Check if role exists
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        
        # If not exists, try installing fixtures
        try:
            from frappe.core.doctype.data_import.data_import import import_doc
            # This will ensure fixtures are loaded
            frappe.get_doc("Data Import", {}).import_doc()
        except:
            pass
            
        # Try again after fixture loading
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        
        # Fallback: create the role if it still doesn't exist
        role_data = {
            "Team Leader": {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1},
            "Team Member": {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0},
            "Coordinator": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0},
            "Secretary": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1},
            "Treasurer": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1}
        }.get(role_name, {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0})
        
        team_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": role_name,
            "description": f"Test {role_name} role",
            "is_active": 1,
            **role_data
        })
        team_role.insert(ignore_permissions=True)
        self.track_doc("Team Role", team_role.name)
        return team_role

    def create_test_team_member(self, team=None, volunteer=None, team_role_name="Team Member", **kwargs):
        """Create team member with new team_role field structure"""
        if team is None:
            team = self.create_test_team()
        if volunteer is None:
            volunteer = self.create_test_volunteer()
        
        # Get or create the team role
        team_role = self.get_or_create_team_role(team_role_name)
        
        # Add team member to team
        team_doc = frappe.get_doc("Team", team.name if hasattr(team, 'name') else team)
        
        member_defaults = {
            "volunteer": volunteer.name if hasattr(volunteer, 'name') else volunteer,
            "team_role": team_role.name,  # Use new team_role field
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        }
        member_defaults.update(kwargs)
        
        team_doc.append("team_members", member_defaults)
        team_doc.save(ignore_permissions=True)
        
        return team_doc.team_members[-1]  # Return the added team member record

    # CORE METHOD 6: SEPA Mandate Creation
    def create_test_sepa_mandate(self, member=None, **kwargs):
        """Create SEPA mandate with test bank account"""
        if member is None:
            member = self.create_test_member()
        
        test_iban = self.generate_test_iban()
        # Get member name for account holder
        member_name = member.name if hasattr(member, 'name') else member
        member_doc = frappe.get_doc("Member", member_name) if isinstance(member_name, str) else member
        account_holder_name = f"{member_doc.first_name} {member_doc.last_name}"
        
        defaults = {
            "member": member_name,
            "iban": test_iban,
            "bic": self.derive_bic_from_test_iban(test_iban),
            "status": "Active",
            "mandate_type": "RCUR",  # Required field - use valid option
            "scheme": "SEPA",  # Required field
            "account_holder_name": account_holder_name,  # Required field
            "sign_date": today(),  # Required field (renamed from mandate_date)
            "mandate_id": f"TEST-{random_string(8)}"  # Required field
        }
        defaults.update(kwargs)
        
        mandate = frappe.get_doc({"doctype": "SEPA Mandate", **defaults})
        mandate.insert(ignore_permissions=True)
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    # CORE METHOD 7: Expense Creation
    def create_test_expense(self, volunteer=None, **kwargs):
        """Create test volunteer expense"""
        if volunteer is None:
            volunteer = self.create_test_volunteer()
        
        defaults = {
            "volunteer": volunteer.name if hasattr(volunteer, 'name') else volunteer,
            "expense_date": today(),
            "description": f"Test expense - {self.fake.sentence(nb_words=4)}",
            "amount": flt(self.fake.random_int(min=10, max=500)),
            "status": "Draft"
        }
        defaults.update(kwargs)
        
        expense = frappe.get_doc({"doctype": "Volunteer Expense", **defaults})
        expense.insert(ignore_permissions=True)
        self.track_doc("Volunteer Expense", expense.name)
        return expense

    # CORE METHOD 8: Complete Business Scenario
    def create_complete_test_scenario(self, member_count: int = 10):
        """Create complete test scenario with all related documents"""
        print(f"🏗️  Creating complete test scenario with {member_count} members...")
        
        # Create supporting data
        chapters = self.create_test_chapters(count=max(1, member_count // 5))
        membership_types = [self.create_test_membership_type() for _ in range(3)]
        
        # Create members and related data
        members = self.create_test_members(count=member_count, chapters=chapters)
        memberships = [self.create_test_membership(member=member, membership_type=random.choice(membership_types)) 
                      for member in members]
        
        # Create volunteers (30% of members)
        volunteers = [self.create_test_volunteer(member=member) 
                     for member in random.sample(members, max(1, member_count // 3))]
        
        # Create SEPA mandates (60% of members)
        mandates = [self.create_test_sepa_mandate(member=member) 
                   for member in random.sample(members, max(1, (member_count * 6) // 10))]
        
        # Create some expenses
        expenses = []
        for volunteer in volunteers:
            expense_count = random.randint(1, 3)
            expenses.extend([self.create_test_expense(volunteer=volunteer) for _ in range(expense_count)])
        
        return {
            "chapters": chapters,
            "membership_types": membership_types,
            "members": members,
            "memberships": memberships,
            "volunteers": volunteers,
            "mandates": mandates,
            "expenses": expenses
        }

    # UTILITY METHODS (Enhanced)
    def generate_test_iban(self, bank_code: str = None) -> str:
        """Generate valid test IBAN with proper checksum"""
        if bank_code is None:
            bank_code = random.choice(["TEST", "MOCK", "DEMO"])
        
        # Generate account number
        account_number = f"{random.randint(1000000000, 9999999999)}"
        
        # Calculate MOD-97 checksum for valid IBAN
        temp_iban = f"NL00{bank_code}{account_number}"
        
        # MOD-97 calculation
        numeric_string = ""
        for char in temp_iban[4:] + "NL00":
            if char.isdigit():
                numeric_string += char
            else:
                numeric_string += str(ord(char) - ord('A') + 10)
        
        checksum = 98 - (int(numeric_string) % 97)
        return f"NL{checksum:02d}{bank_code}{account_number}"

    def derive_bic_from_test_iban(self, iban: str) -> str:
        """Derive BIC from test IBAN"""
        bank_code = iban[4:8]
        return f"{bank_code}NL2A"

    def get_or_create_test_chapter(self):
        """Get cached test chapter or create new one"""
        if self._test_chapters is None:
            self._test_chapters = [self.create_test_chapter()]
        return self._test_chapters[0]

    def get_or_create_test_chapters(self, count: int = 3):
        """Get cached test chapters or create new ones"""
        if self._test_chapters is None or len(self._test_chapters) < count:
            self._test_chapters = self.create_test_chapters(count=count)
        return self._test_chapters[:count]

    def get_or_create_test_membership_type(self):
        """Get cached test membership type or create new one"""
        if self._test_membership_types is None:
            self._test_membership_types = [self.create_test_membership_type()]
        return self._test_membership_types[0]


    # CONTEXT MANAGER SUPPORT
    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        if self.cleanup_on_exit:
            self.cleanup()

    # SCENARIO BUILDERS (Restored from Phase 4 removal)
    def create_team_with_multiple_roles(self, member_count=5):
        """Create team with various roles for comprehensive testing"""
        team = self.create_test_team()
        volunteers = [self.create_test_volunteer() for _ in range(member_count)]
        
        role_assignments = [
            "Team Leader",    # Unique role
            "Secretary",      # Unique role  
            "Treasurer",      # Unique role
            "Coordinator",    # Non-unique role
            "Team Member"     # Non-unique role
        ]
        
        team_members = []
        for i, volunteer in enumerate(volunteers):
            role_name = role_assignments[i % len(role_assignments)]
            # Avoid duplicate unique roles
            if role_name in ["Team Leader", "Secretary", "Treasurer"] and i >= 3:
                role_name = "Team Member"  # Fallback to non-unique role
                
            member = self.create_test_team_member(
                team=team,
                volunteer=volunteer, 
                team_role_name=role_name
            )
            team_members.append(member)
            
        return {
            "team": team,
            "volunteers": volunteers,
            "team_members": team_members,
            "roles_used": list(set(role_assignments[:member_count]))
        }

    def create_edge_case_data(self):
        """Create comprehensive edge case scenario data for testing"""
        print("🔧 Creating edge case test scenario...")
        
        # Create members with edge case characteristics
        edge_members = []
        
        # Member with very old birth date
        old_member = self.create_test_member(
            first_name="VeryOld",
            last_name="EdgeCase",
            email="old.edge@example.com",
            birth_date="1920-01-01"
        )
        edge_members.append(old_member)
        
        # Member with recent birth date (just turned 18)
        from frappe.utils import add_years
        young_member = self.create_test_member(
            first_name="JustEighteen",
            last_name="EdgeCase", 
            email="young.edge@example.com",
            birth_date=add_years(today(), -18)
        )
        edge_members.append(young_member)
        
        # Member with special characters in name
        special_member = self.create_test_member(
            first_name="José-María",
            last_name="van der Berg-O'Connor",
            email="special.chars@example.com"
        )
        edge_members.append(special_member)
        
        # Create edge case memberships
        edge_memberships = []
        
        # Zero-rate membership (scholarship)
        zero_type = self.create_test_membership_type(
            membership_type_name="Zero Rate Scholarship",
            amount=0.00,
            billing_frequency="Annual"
        )
        
        zero_membership = self.create_test_membership(
            member=edge_members[0],
            membership_type=zero_type
        )
        edge_memberships.append(zero_membership)
        
        # High-rate membership
        premium_type = self.create_test_membership_type(
            membership_type_name="Premium Edge Case",
            amount=9999.99,
            billing_frequency="Annual"
        )
        
        premium_membership = self.create_test_membership(
            member=edge_members[1],
            membership_type=premium_type
        )
        edge_memberships.append(premium_membership)
        
        return {
            "members": edge_members,
            "memberships": edge_memberships,
            "membership_types": [zero_type, premium_type],
            "scenario_type": "edge_cases"
        }
    
    def create_billing_conflict_scenario(self):
        """Create billing frequency conflict scenario for testing validation"""
        print("💰 Creating billing conflict test scenario...")
        
        # Create member and membership
        conflict_member = self.create_test_member(
            first_name="Conflict",
            last_name="TestMember",
            email="conflict.test@example.com"
        )
        
        membership = self.create_test_membership(member=conflict_member)
        
        # Create conflicting dues schedules (using basic creation method)
        monthly_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Monthly-Conflict-{self.test_run_id}",
            "member": conflict_member.name,
            "dues_rate": 25.00,
            "billing_frequency": "Monthly",
            "status": "Active",
            "is_template": 0
        })
        monthly_schedule.insert(ignore_permissions=True)
        self.track_doc("Membership Dues Schedule", monthly_schedule.name)
        
        annual_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Annual-Conflict-{self.test_run_id}",
            "member": conflict_member.name,
            "dues_rate": 250.00,
            "billing_frequency": "Annual",
            "status": "Active",
            "is_template": 0
        })
        annual_schedule.insert(ignore_permissions=True)
        self.track_doc("Membership Dues Schedule", annual_schedule.name)
        
        return {
            "member": conflict_member,
            "membership": membership,
            "monthly_schedule": monthly_schedule,
            "annual_schedule": annual_schedule,
            "conflict_type": "billing_frequency",
            "expected_validation_error": True
        }
    
    def create_stress_test_data(self, scale="medium"):
        """Create stress test data for performance validation"""
        scales = {
            "small": {"members": 50, "chapters": 5},
            "medium": {"members": 200, "chapters": 10},
            "large": {"members": 1000, "chapters": 25}
        }
        
        config = scales.get(scale, scales["medium"])
        print(f"🏋️ Creating {scale} stress test scenario ({config['members']} members)...")
        
        # Create chapters
        chapters = self.create_test_chapters(count=config["chapters"])
        
        # Create members distributed across chapters
        members = []
        for i in range(config["members"]):
            chapter = chapters[i % len(chapters)]
            member = self.create_test_member(
                first_name=f"Stress{i:04d}",
                last_name="TestMember",
                email=f"stress{i:04d}@example.com",
                chapter=chapter
            )
            members.append(member)
        
        # Create memberships for all members
        memberships = []
        membership_types = [self.create_test_membership_type() for _ in range(3)]
        
        for i, member in enumerate(members):
            membership_type = membership_types[i % len(membership_types)]
            membership = self.create_test_membership(
                member=member,
                membership_type=membership_type
            )
            memberships.append(membership)
        
        # Create volunteers (30% of members)
        volunteer_count = config["members"] // 3
        volunteers = []
        for i in range(volunteer_count):
            volunteer = self.create_test_volunteer(member=members[i])
            volunteers.append(volunteer)
        
        return {
            "chapters": chapters,
            "members": members,
            "memberships": memberships,
            "membership_types": membership_types,
            "volunteers": volunteers,
            "scale": scale,
            "stats": {
                "member_count": len(members),
                "chapter_count": len(chapters),
                "volunteer_count": len(volunteers)
            }
        }
    
    def create_test_members_with_status_distribution(self, total_count=20, status_ratios=None):
        """Create members with realistic status distribution for testing"""
        if status_ratios is None:
            status_ratios = {
                "Active": 0.70,      # 70% active
                "Suspended": 0.15,   # 15% suspended
                "Terminated": 0.10,  # 10% terminated
                "Pending": 0.05      # 5% pending
            }
        
        members_by_status = {}
        
        for status, ratio in status_ratios.items():
            count = int(total_count * ratio)
            if count == 0 and ratio > 0:
                count = 1  # Ensure at least one member per status
            
            status_members = []
            for i in range(count):
                member = self.create_test_member(
                    first_name=f"{status}{i:02d}",
                    last_name="DistributionTest",
                    email=f"{status.lower()}{i:02d}@example.com",
                    status=status
                )
                status_members.append(member)
            
            members_by_status[status] = status_members
        
        return {
            "members_by_status": members_by_status,
            "total_count": sum(len(members) for members in members_by_status.values()),
            "status_distribution": status_ratios,
            "scenario_type": "status_distribution"
        }
    
    def create_test_members_with_volunteer_ratio(self, member_count=30, volunteer_ratio=0.4):
        """Create members with specified volunteer participation ratio"""
        # Create members
        members = self.create_test_members(count=member_count)
        
        # Calculate volunteer count
        volunteer_count = int(member_count * volunteer_ratio)
        
        # Create volunteers from subset of members
        volunteers = []
        for i in range(volunteer_count):
            volunteer = self.create_test_volunteer(member=members[i])
            volunteers.append(volunteer)
        
        return {
            "members": members,
            "volunteers": volunteers,
            "non_volunteers": members[volunteer_count:],
            "volunteer_ratio": volunteer_count / member_count,
            "stats": {
                "total_members": len(members),
                "volunteer_count": len(volunteers),
                "non_volunteer_count": len(members) - len(volunteers)
            }
        }


# CONVENIENCE FUNCTIONS
def create_test_data_set(data_type: str = "minimal", **kwargs):
    """Create standardized test data sets"""
    with StreamlinedTestDataFactory(cleanup_on_exit=False) as factory:
        if data_type == "minimal":
            return {
                "chapter": factory.create_test_chapter(),
                "member": factory.create_test_member(),
                "membership_type": factory.create_test_membership_type()
            }
        elif data_type == "comprehensive":
            return factory.create_complete_test_scenario(member_count=kwargs.get('member_count', 20))
        elif data_type == "performance":
            return factory.create_complete_test_scenario(member_count=kwargs.get('member_count', 100))
        else:
            raise ValueError(f"Unknown data_type: {data_type}")


# BACKWARD COMPATIBILITY ALIAS
TestDataFactory = StreamlinedTestDataFactory

# Additional convenience methods for Team Role testing
def create_test_team_scenario(member_count=5, cleanup_on_exit=True):
    """Create complete team scenario with various roles"""
    with StreamlinedTestDataFactory(cleanup_on_exit=cleanup_on_exit) as factory:
        return factory.create_team_with_multiple_roles(member_count=member_count)

def get_available_team_roles():
    """Get list of available team roles for testing"""
    return ["Team Leader", "Team Member", "Coordinator", "Secretary", "Treasurer"]
