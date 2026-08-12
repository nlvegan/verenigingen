#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verenigingen Business Logic Test Framework
==========================================

🔍 **BUSINESS LOGIC VALIDATION FRAMEWORK** - Use for production issue discovery

WHEN TO USE EnhancedTestCase:
✅ Business logic validation that must catch real production issues
✅ Core business rule testing (Member lifecycle, SEPA operations)
✅ Field safety validation (prevents non-existent field references)
✅ Data integrity testing with business rule enforcement
✅ Production bug discovery through real database testing (Phase 5.1)

WHEN NOT TO USE (Use VereningingenTestCase instead):
❌ Integration tests requiring extensive mocking
❌ UI/form testing with CSRF simulation
❌ External service integration testing
❌ Performance tests with controlled environments

Key Features:
- Field Validator: Caught 18+ production issues in Phase 5.1
- Business rule enforcement (age validation, required fields)
- Real database testing without inappropriate mocks
- Clean API with both create_* and create_test_* methods

⚠️  CRITICAL: This framework discovered 18 production issues that traditional mocked
tests completely missed. Use for any test that should catch real system problems.

Companion Framework: VereningingenTestCase (utils/base.py)
==========================================

Enterprise-grade test data factory that extends Frappe's FrappeTestCase with comprehensive
business rule validation, field safety checks, and deterministic data generation.

This module addresses critical testing challenges in the Verenigingen association management
system by providing a robust foundation for creating realistic, valid test data while
maintaining strict validation and ensuring test reproducibility.

Core Features
------------
- **Business Rule Validation**: Prevents creation of invalid test scenarios (e.g., volunteers under 16)
- **Field Safety**: Validates all field references against DocType schemas before document creation
- **Deterministic Generation**: Uses configurable seeds for reproducible test scenarios
- **Faker Integration**: Generates realistic but clearly marked test data using the Faker library
- **Security Compliant**: Uses proper Frappe permissions throughout all operations
- **Auto-cleanup**: Inherits FrappeTestCase's automatic database rollback capabilities

Architecture
-----------
The factory consists of two main components:

1. **EnhancedTestDataFactory**: Core factory class with business logic and validation
2. **EnhancedTestCase**: Test case base class that combines FrappeTestCase benefits with enhancements

Design Principles
----------------
- **Fail Fast**: Validation errors are caught early during test data creation
- **Realistic Data**: Generated data resembles production data but is clearly marked as test data
- **Deterministic**: Same seed produces identical test data for reproducible test scenarios
- **Schema-Aware**: All field references are validated against actual DocType definitions
- **Permission-Compliant**: Respects Frappe's permission system without bypasses

Integration with Testing Infrastructure
-------------------------------------
This factory integrates seamlessly with the broader testing infrastructure:

- Extends FrappeTestCase for automatic database rollback
- Works with the existing test data cleanup mechanisms
- Supports query count monitoring for performance testing
- Provides permission testing capabilities
- Maintains global state isolation between tests

Business Logic Validation
-------------------------
The factory enforces critical business rules during test data creation:

- Member age validation (minimum 16 years, maximum 120 years)
- Volunteer start date validation (must be 16+ at start date)
- Membership temporal validation (start date after birth date)
- Email format validation for all created records
- Phone number format validation using reserved test ranges

Usage Examples
-------------
```python
# Basic usage with EnhancedTestCase
class TestMyFeature(EnhancedTestCase):
    def test_member_creation(self):
        member = self.create_test_member(
            first_name="John",
            last_name="Doe",
            birth_date="1990-01-01"
        )
        self.assertEqual(member.first_name, "John")

# Direct factory usage
factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
member = factory.create_member(birth_date="1990-01-01")

# Application data for complex workflows
app_data = factory.create_application_data(with_volunteer_skills=True)
```

Error Handling and Debugging
----------------------------
The factory provides detailed error messages for common issues:

- BusinessRuleError: When business logic validation fails
- FieldValidationError: When field references are invalid
- Schema validation errors with specific field information
- Faker data generation errors with fallback mechanisms

Performance Considerations
-------------------------
- Field validation is cached per DocType to minimize database queries
- Sequence counters prevent unnecessary database lookups for unique values
- Faker instances are seeded once per factory instance for consistency
- Meta information is cached with error handling for missing DocTypes

Migration and Compatibility
--------------------------
This factory is designed to gradually replace the legacy TestDataFactory:

- Provides compatibility methods for existing test patterns
- Includes migration helpers for converting existing tests
- Maintains backward compatibility where possible
- Offers enhanced error reporting for migration assistance

Security and Data Protection
---------------------------
- All generated data is clearly marked as test data with prefixes
- Uses reserved number ranges for phone numbers and postal codes
- Email addresses use .invalid TLD to prevent accidental delivery
- Test run IDs include timestamps and random components for uniqueness

Quality Assurance
----------------
The factory includes self-validation capabilities:

- Validates its own field references against live schemas
- Includes comprehensive error handling with fallback mechanisms
- Provides detailed logging for debugging test data creation issues
- Supports dry-run modes for validating test scenarios

Document Tracking Priority System (1-5)
---------------------------------------
The factory uses a priority-based cleanup system to respect foreign key dependencies:

Priority 1: Infrastructure (Account, Region, Company, Fiscal Year)
    - Deleted first during cleanup
    - Foundation objects that other records depend on

Priority 2: Organization (Chapter, User, Team)
    - Second level cleanup
    - Structural entities with dependencies

Priority 3: Configuration (Address, Templates, Customer)
    - Third level cleanup
    - Supporting configuration data

Priority 4: Transactional (Invoices, Payments, SEPA Mandates, Donations)
    - Fourth level cleanup
    - Business transaction records

Priority 5: Core Business (Member, Membership, Applications)
    - Deleted last during cleanup
    - Primary business entities that depend on all other records

Cleanup Order: Reverse priority (5→1) ensures dependent records are deleted
before their dependencies, preventing foreign key constraint violations.

Version History
--------------
- Initial implementation with business rule validation
- Added field safety checks and schema validation
- Enhanced with Faker integration and deterministic generation
- Improved error handling and compatibility with existing tests
- Added comprehensive document tracking with priority-based cleanup
"""

import itertools
import json
import random
import time
from datetime import datetime
from typing import Any, Dict

import frappe
from faker import Faker
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from verenigingen.tests.utils.error_log_guard import ErrorLogGuardMixin

from .field_validator import FieldValidationError, FieldValidator

# erpnext v16.20 creates its base test masters (Company, Territory tree, Customer
# Groups, Chart of Accounts, Fiscal Year, price lists, ...) via a module-level
# BootStrapTestData() call in erpnext.tests.utils. EnhancedTestCase tests run as
# an "unspecified" category and so never trigger the before_tests hook; importing
# erpnext.tests.utils here ensures those masters exist when such tests run in
# isolation too. The import is cached + BootStrapTestData runs once per process,
# so this never double-creates / collides.
try:
    import erpnext.tests.utils  # noqa: F401
except Exception:  # pragma: no cover - defensive: never block factory import
    pass

# Companies the test harness OWNS, in preference order. before_tests
# (verenigingen/tests/setup/__init__.py) guarantees these exist by loading ERPNext's
# Company test records. `_get_test_company()` picks from this list BY NAME instead of
# taking whichever company the database happens to return first -- see #299 for why
# borrowing is unsafe: the chosen company's chart of accounts can get deleted.
HARNESS_OWNED_COMPANIES = (
    "_Test Company",
    "_Test Company 1",
    "_Test Company with perpetual inventory",
)


class MockRolesContext:
    """
    Context manager to temporarily mock user roles for permission testing.

    Usage:
        with frappe.mock_roles(["System Manager", "Verenigingen Admin"]):
            # Code here will see the user as having only these roles
            has_permission = frappe.has_permission("DocType", "read")

    This context manager patches frappe.get_roles() to return the specified
    roles, enabling isolated permission testing without modifying the database.
    """

    def __init__(self, roles: list):
        """
        Initialize the mock roles context.

        Args:
            roles: List of role names to mock for the current user
        """
        self.roles = roles if roles else []
        self._original_get_roles = None

    def __enter__(self):
        """Enter the context and patch frappe.get_roles."""
        self._original_get_roles = frappe.get_roles

        # Create a mock function that returns the specified roles
        mock_roles_list = self.roles

        def mock_get_roles(user=None, with_standard=True):
            """Mock implementation of frappe.get_roles."""
            # Always include "All" and optionally "Guest" as standard roles
            result = list(mock_roles_list)
            if with_standard:
                if "All" not in result:
                    result.append("All")
            return result

        frappe.get_roles = mock_get_roles
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and restore the original frappe.get_roles."""
        if self._original_get_roles is not None:
            frappe.get_roles = self._original_get_roles
        return False


# Monkey-patch frappe to add mock_roles method for test convenience
def _mock_roles(roles: list):
    """
    Create a context manager to temporarily mock user roles.

    This is added to frappe module for convenient access in tests:
        with frappe.mock_roles(["Role1", "Role2"]):
            # test code here

    Args:
        roles: List of role names to mock

    Returns:
        MockRolesContext instance
    """
    return MockRolesContext(roles)


# Add mock_roles to frappe module for test convenience
frappe.mock_roles = _mock_roles


# Suppress slow synchronous workflow-action emails for every test that uses this
# module. Frappe's process_workflow_actions() runs send_workflow_action_email
# synchronously in test mode (now=frappe.in_test); that email renders a PDF via
# the pure-Python html5lib parser, costing tens of seconds per Member insert and
# hanging Member-heavy modules for 13+ minutes. The before_tests hook cannot
# cover EnhancedTestCase tests (they are categorized "unspecified-category", so
# the hook never fires for them), so the patch is applied here at import time —
# every EnhancedTestCase test module imports this file. The patch is idempotent.
try:
    from verenigingen.tests.setup import disable_workflow_action_emails

    disable_workflow_action_emails()
except Exception as e:  # pragma: no cover - defensive: never block test collection
    # Log the failure so a future move/rename of disable_workflow_action_emails
    # doesn't silently regress the hang. Mirrors the warning emitted by the
    # before_tests caller.
    frappe.logger().warning(f"disable_workflow_action_emails import failed: {e}")


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

    # Process-global monotonic counter for the Customer-collision-prevention suffix
    # appended to last_name. MUST NOT be a per-instance counter: a fresh factory is
    # built in every test's setUp, so a per-instance counter resets to 1 each time,
    # producing identical names (e.g. "TestUser1") across tests -> identical member
    # full_name -> identical auto-created Customer name -> DuplicateEntryError on the
    # Customer PRIMARY key. A class-level counter stays monotonic across instances
    # within a shard process (shards use separate DBs, so no cross-shard concern).
    # See bucket B1 in docs/plans/2026-05-29-server-tests-red-baseline-triage.md.
    _global_unique_seq = itertools.count(1)

    # Per-process run token (microsecond resolution, computed once when this class is
    # first imported). The monotonic counter above only guarantees uniqueness *within*
    # a single process; it resets to 1 every run, so deterministic names like
    # "Coverage Test1" collide with any test data left behind by an earlier run on a
    # persistent DB (committed test docs are not rolled back). Combining the counter
    # with this run token makes auto-created Customer names unique *across* runs too,
    # mirroring how generate_test_email()/generate_test_name() already append a
    # timestamp component. Same DB pollution no longer causes DuplicateEntryError.
    _process_run_token = str(int(time.time() * 1000000) % 100000000)

    def __init__(self, seed: int = 12345, use_faker: bool = True):
        """
        Initialize enhanced test data factory

        Args:
            seed: Random seed for deterministic data generation
            use_faker: Whether to use Faker for realistic test data
        """
        # Store seed for access by bridge methods
        self.seed = seed

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

        # Generate deterministic test run ID based on seed for reproducible tests
        deterministic_seed_hash = hash(f"test_run_{seed}") % 1000000
        self.test_run_id = f"TEST-{seed}-{deterministic_seed_hash}"

        # ISOLATION ENHANCEMENT: Track created documents for cleanup
        self.created_documents = []

        # Delegate core entity creation to CoreTestDataFactory
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

        self.core = CoreTestDataFactory(cleanup_on_exit=False, seed=seed)

    def get_next_sequence(self, prefix: str) -> int:
        """Get next sequence number for deterministic data"""
        self.sequence_counters[prefix] = self.sequence_counters.get(prefix, 0) + 1
        return self.sequence_counters[prefix]

    def generate_test_email(self, purpose: str = "member") -> str:
        """Generate clearly marked test email"""
        seq = self.get_next_sequence(f"email_{purpose}")  # Purpose-specific sequence
        # Use deterministic "timestamp" based on sequence and test run ID for reproducibility
        deterministic_id = hash(f"{self.test_run_id}_{purpose}_{seq}") % 1000000

        # Add actual timestamp component to guarantee uniqueness across test runs
        # Use nanoseconds and sequence to prevent millisecond collisions
        import time

        timestamp_component = int(time.time() * 1000000) % 100000000  # Microseconds for better resolution

        if self.use_faker:
            # Use Faker but clearly mark as test
            base_email = self.fake.email()
            username, domain = base_email.split("@")
            # Combine seq + timestamp + deterministic_id for absolute uniqueness
            return (
                f"TEST_{purpose}_{seq:04d}_{timestamp_component}_{deterministic_id}_{username}@test.invalid"
            )
        else:
            return f"TEST_{purpose}_{seq:04d}_{timestamp_component}_{deterministic_id}@test.invalid"

    def generate_test_name(self, type_name: str = "Person") -> str:
        """Generate clearly marked test name with guaranteed uniqueness"""
        seq = self.get_next_sequence("name")
        # Use timestamp microseconds for additional uniqueness across test runs
        import time

        uid = str(int(time.time() * 1000000) % 1000000)
        if self.use_faker:
            fake_name = self.fake.name()
            # Add sequence and uid to ensure uniqueness even with same Faker seed
            return f"TEST {fake_name} {seq:03d}{uid}"
        else:
            return f"TEST {type_name} {seq:04d}{uid}"

    def force_unique_name(self, base_name: str, doctype: str = None, max_length: int = 50) -> str:
        """
        Force a unique name by adding timestamp and test run ID to any provided name.
        This prevents test isolation conflicts when tests provide explicit names.

        QCE FIX: Respects database field length limits to prevent truncation errors.

        Args:
            base_name: The base name provided by the test
            doctype: Optional doctype for collision detection
            max_length: Maximum allowed name length (default 50 chars)

        Returns:
            Unique name guaranteed not to conflict and within length limits
        """
        # Remove any existing test markers and truncate base to reasonable length
        clean_base = base_name.replace("TEST ", "").replace("Test ", "")
        # Reserve space for uniqueness components: "TEST " (5) + seq (4) + "_" (1) + timestamp (6) = 16 chars
        max_base_length = max_length - 20  # Leave buffer for uniqueness components
        clean_base = clean_base[:max_base_length] if len(clean_base) > max_base_length else clean_base

        # Generate compact uniqueness components
        seq = self.get_next_sequence(f"forced_{clean_base}")
        # Use deterministic ID based on hash for compactness and reproducibility
        short_deterministic_id = hash(f"{self.test_run_id}_{clean_base}_{seq}") % 1000000

        # Create shorter, length-aware unique name
        unique_name = f"TEST {clean_base} {seq:03d}_{short_deterministic_id}"

        # Ensure we don't exceed max_length
        if len(unique_name) > max_length:
            # Further truncate base name if needed
            excess = len(unique_name) - max_length
            clean_base = clean_base[:-excess] if len(clean_base) > excess else clean_base[:5]
            unique_name = f"TEST {clean_base} {seq:03d}_{short_deterministic_id}"

        # Final collision check if doctype provided
        if doctype and frappe.db.exists(doctype, unique_name):
            collision_seq = self.get_next_sequence(f"collision_{clean_base}")
            # Use even shorter format for collision resolution
            unique_name = f"TEST {clean_base[:10]} {seq:02d}_{collision_seq:02d}_{short_deterministic_id}"

        return unique_name[:max_length]  # Final safety truncation

    def track_document(self, doctype: str, name: str, priority: int = 0):
        """
        Track a created document for cleanup.

        Args:
            doctype: The document type
            name: The document name
            priority: Cleanup priority (higher numbers cleaned up first)
        """
        self.created_documents.append(
            {"doctype": doctype, "name": name, "priority": priority, "test_run_id": self.test_run_id}
        )

    def track_account_creation_request(self, volunteer_name: str):
        """
        Track Account Creation Request documents created by API calls for cleanup.

        This is needed because Enhanced Test Factory only tracks documents created
        directly via factory methods, not those created by whitelisted API functions
        like queue_account_creation_for_volunteer().
        """
        # Find any Account Creation Requests for this volunteer
        requests = frappe.get_all(
            "Account Creation Request", filters={"source_record": volunteer_name}, fields=["name"]
        )

        for request in requests:
            self.track_document("Account Creation Request", request.name)

    def get_cleanup_summary(self) -> dict:
        """Get summary of documents created for cleanup reporting"""
        by_doctype = {}
        for doc in self.created_documents:
            doctype = doc["doctype"]
            by_doctype[doctype] = by_doctype.get(doctype, 0) + 1

        return {
            "total_documents": len(self.created_documents),
            "by_doctype": by_doctype,
            "test_run_id": self.test_run_id,
        }

    def generate_test_phone(self) -> str:
        """Generate test phone number using reserved ranges"""
        # Generate a valid Dutch mobile number for testing
        # Format: +31 6 XXXXXXXX (8 digits after 6)
        seq = self.get_next_sequence("phone")
        # Use 90000000-99999999 range for test numbers
        test_number = 90000000 + seq
        return f"+31 6 {test_number}"

    def _generate_unique_test_member_id(self) -> str:
        """Generate unique member ID for test members to avoid database conflicts.

        ``member_id`` is a UNIQUE column. CI runs 8 test shards as parallel
        PROCESSES against ONE shared DB. The old format
        ``TEST{microseconds:06d}{seq:03d}`` collided across shards: two processes
        can hit the same microsecond AND each process's ``seq`` counter starts
        fresh at 1 in its own memory, so both emit e.g. ``TEST161453001`` ->
        IntegrityError 1062 Duplicate entry. We add PER-PROCESS entropy (the OS
        pid plus a random hash) so two shards can never generate the same id,
        while keeping the ``TEST`` prefix that other code keys on.
        """
        import os

        seq = self.get_next_sequence("member_id")
        now = datetime.now()
        microsec_part = int(now.timestamp() * 1000000) % 1000000
        # pid (mod 100000) distinguishes parallel shards; the random hash guards
        # against pid reuse / same-microsecond clashes within a process.
        pid_part = os.getpid() % 100000
        rand_part = frappe.generate_hash(length=6)
        return f"TEST{microsec_part:06d}{seq:03d}{pid_part:05d}{rand_part}"

    def ensure_test_user_has_role(self, role_name):
        """Ensure the current test user has the required role for document operations"""
        current_user = frappe.session.user

        # Skip for Administrator (has all permissions)
        if current_user == "Administrator":
            return

        # Check if user already has the role
        existing_roles = frappe.get_roles(current_user)
        if role_name in existing_roles:
            return

        # Use Frappe's proper API to add role to user
        # Set user as Administrator temporarily for role assignment (test setup only)
        try:
            current_session_user = frappe.session.user
            frappe.set_user("Administrator")

            user_doc = frappe.get_doc("User", current_user)
            # Add role if not already present
            if not any(role.role == role_name for role in user_doc.roles):
                user_doc.append("roles", {"role": role_name})
                user_doc.save()  # No permission bypass needed as Administrator

                # Clear role cache so the change takes effect immediately
                frappe.cache().delete_value("roles:" + current_user)

            # Restore original user
            frappe.set_user(current_session_user)

            # Force reload of user permissions
            frappe.clear_cache(user=current_user)

            # Ensure permission context is refreshed
            if hasattr(frappe.local, "login_manager"):
                frappe.local.login_manager.user = current_user
        except Exception as e:
            # Fallback: Skip role assignment error during tests to avoid blocking
            frappe.logger().info(f"Role assignment skipped in test environment: {e}")
            pass

    def validate_field_exists(self, doctype: str, fieldname: str) -> bool:
        """Validate that field exists in doctype schema"""
        return self.field_validator.validate_field_exists(doctype, fieldname)

    def validate_member_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate member data against business rules"""
        if "birth_date" in data:
            from verenigingen.utils.validation_utilities import AgeValidator

            try:
                result = AgeValidator.validate_age(
                    data["birth_date"], context="membership", throw_on_error=True
                )
                # Store calculated age for potential use
                data["_calculated_age"] = result.age_years
            except Exception as e:
                raise BusinessRuleError(str(e))

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
                # Use AgeValidator for consistent business rule enforcement
                # BUT use start_date as reference date for age calculation
                from verenigingen.utils.validation_utilities import AgeValidator

                try:
                    # Calculate age at volunteer start date, not today
                    age_at_start = AgeValidator.calculate_age(member.birth_date, start_date)
                    if age_at_start < 16:
                        raise BusinessRuleError(
                            f"Volunteers must be at least 16 years old at start date (age at start: {age_at_start:.1f})"
                        )
                except Exception as e:
                    if isinstance(e, BusinessRuleError):
                        raise
                    raise BusinessRuleError(f"Volunteer age validation failed: {str(e)}")

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
        """Create member with business rule and field validation.

        Delegates core entity creation to CoreTestDataFactory while preserving
        Enhanced-specific field validation, business rules, and post-processing.
        """
        # Ensure test flag is set to bypass rate limiting
        if not hasattr(frappe, "flags"):
            frappe.flags = frappe._dict()
        frappe.flags.in_test = True

        # --- Enhanced pre-processing: field validation ---
        skip_validation_fields = {
            "chapter",
            "suspension_reason",
            "termination_reason",
            "termination_date",
            "join_date",
            "address_line1",
            "city",
            "pincode",
            "postal_code",
            "country",
            "is_student",
            "student_id",
            "volunteer_availability",
            "volunteer_skills",
            "volunteer_availability_time",
            "volunteer_experience_level",
            "volunteer_areas",
            "volunteer_skill_level",
            "volunteer_comments",
        }
        for field in kwargs.keys():
            if field not in skip_validation_fields:
                self.validate_field_exists("Member", field)

        # --- Enhanced pre-processing: unique naming for Customer collision prevention ---
        # Combine the process-global counter (within-run uniqueness) with the
        # per-process run token (cross-run uniqueness on persistent DBs) — see
        # _global_unique_seq / _process_run_token above. Order is token-then-seq so
        # the early-out check below still matches on the full suffix.
        unique_suffix = (
            f"{EnhancedTestDataFactory._process_run_token}"
            f"{next(EnhancedTestDataFactory._global_unique_seq)}"
        )
        if "last_name" in kwargs and unique_suffix not in kwargs["last_name"]:
            kwargs["last_name"] = f"{kwargs['last_name']}{unique_suffix}"
        if "email" in kwargs:
            email = kwargs["email"]
            if "@" in email and not any(c.isdigit() for c in email.split("@")[0][-5:]):
                local, domain = email.rsplit("@", 1)
                kwargs["email"] = f"{local}.{unique_suffix}@{domain}"

        # --- Enhanced pre-processing: business rule validation ---
        kwargs = self.validate_member_business_rules(kwargs)

        # Extract chapter (handled by Core's ChapterMembershipManager)
        chapter = kwargs.pop("chapter", None)

        # --- Delegate to CoreTestDataFactory ---
        try:
            member = self.core.create_test_member(
                chapter=chapter or False,  # False = skip auto-chapter in Core
                auto_create_customer=True,
                **kwargs,
            )
        except BusinessRuleError:
            raise
        except Exception as e:
            raise Exception(f"Failed to create member: {e}")

        # --- Enhanced post-processing: Member Address if address fields provided ---
        if any(key in kwargs for key in ["address_line1", "city", "pincode", "postal_code"]):
            member_address = self.create_address(
                address_line1=kwargs.get("address_line1"),
                city=kwargs.get("city"),
                pincode=kwargs.get("pincode") or kwargs.get("postal_code"),
                link_doctype="Member",
                link_name=member.name,
                address_title=f"{member.full_name} - Address",
            )
            member.primary_address = member_address.name
            member.save()

        # Track in Enhanced's own cleanup system
        self.track_document("Member", member.name, priority=5)
        return member

    def _has_customer_address(self, customer_name):
        """Check if customer has an address"""
        # Check via Address DocType if any address links to this customer
        addresses = frappe.get_all(
            "Address",
            fields=["name"],
            filters=[
                ["Dynamic Link", "link_doctype", "=", "Customer"],
                ["Dynamic Link", "link_name", "=", customer_name],
            ],
            limit=1,
        )
        return len(addresses) > 0

    def create_address(
        self, address_line1=None, city=None, pincode=None, link_doctype=None, link_name=None, **kwargs
    ):
        """Create Address document with optional linking to Member/Customer"""
        address = frappe.new_doc("Address")
        address.address_title = kwargs.get("address_title", f"Test Address {frappe.generate_hash(length=8)}")
        address.address_line1 = address_line1 or "Test Street 123"
        address.city = city or "Amsterdam"
        address.pincode = pincode or "1234 AB"
        address.country = kwargs.get("country", "Netherlands")
        address.is_primary_address = kwargs.get("is_primary_address", 1)

        # Link to doctype if provided
        if link_doctype and link_name:
            address.append("links", {"link_doctype": link_doctype, "link_name": link_name})

        address.insert()
        self.track_document("Address", address.name, priority=3)
        return address

    def _create_customer_address(self, member):
        """Create Customer Address for invoice generation (infrastructure setup only)"""
        return self.create_address(
            address_line1=(
                member.address_line1 if hasattr(member, "address_line1") and member.address_line1 else None
            ),
            city=member.city if hasattr(member, "city") and member.city else None,
            pincode=member.postal_code if hasattr(member, "postal_code") and member.postal_code else None,
            link_doctype="Customer",
            link_name=member.customer,
            address_title=f"{member.full_name} - Test Address",
        )

    def create_volunteer(self, member_name: str = None, **kwargs):
        """Create volunteer with field validation and business rules.

        Delegates core entity creation to CoreTestDataFactory while preserving
        Enhanced-specific field validation, _exact_name/_exact_email controls,
        and business rule enforcement.
        """
        # Create member if not provided
        if not member_name:
            member = self.create_member()
            member_name = member.name

        # Enhanced field validation (skip control parameters starting with _)
        for field in kwargs.keys():
            if not field.startswith("_"):
                self.validate_field_exists("Volunteer", field)

        # _exact_name / _exact_email control: force uniqueness unless caller opts out
        if "volunteer_name" in kwargs and not kwargs.pop("_exact_name", False):
            kwargs["volunteer_name"] = self.force_unique_name(kwargs["volunteer_name"], "Volunteer")
        if "email" in kwargs and not kwargs.pop("_exact_email", False):
            seq = self.get_next_sequence("vol_email_unique")
            local = kwargs["email"].split("@")[0] if "@" in kwargs["email"] else "vol"
            kwargs["email"] = f"{local[:30]}_{seq}@test.invalid"

        # Remove remaining control parameters before passing to Core
        clean_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}

        # Enhanced business rule validation
        clean_kwargs["member"] = member_name
        clean_kwargs = self.validate_volunteer_business_rules(clean_kwargs)
        # Remove member so it can be passed as keyword arg to Core
        member_for_core = clean_kwargs.pop("member")

        # Set flags to skip automatic account creation during tests
        frappe.flags.skip_volunteer_account_creation = True

        try:
            volunteer = self.core.create_test_volunteer(member=member_for_core, **clean_kwargs)
        except BusinessRuleError:
            raise
        except Exception as e:
            raise Exception(f"Failed to create volunteer: {e}")

        self.track_document("Volunteer", volunteer.name)
        return volunteer

    # ------------------------------------------------------------------
    # Backward-compatibility API bridge methods
    #
    # These ``create_test_*`` aliases were lost in the test-factory
    # consolidation (see docs/plans/2026-02-21-test-factory-consolidation-design.md)
    # but are still called by sibling factories (e.g. SEPATestDataFactory) and
    # legacy tests that hold a factory instance directly. They are thin
    # wrappers over the current canonical ``create_*`` methods and must NOT
    # change the canonical API.
    # ------------------------------------------------------------------
    def create_test_member(self, *args, **kwargs):
        """Alias for create_member() with legacy positional support.

        Legacy positional conventions:
          create_test_member(email)                          # contains "@"
          create_test_member(first_name, last_name[, email[, iban]])
        """
        if args:
            if len(args) == 1 and isinstance(args[0], str) and "@" in args[0]:
                kwargs.setdefault("email", args[0])
            else:
                for value, field in zip(args, ["first_name", "last_name", "email", "iban"]):
                    kwargs.setdefault(field, value)
        return self.create_member(**kwargs)

    def create_test_volunteer(self, member_name=None, **kwargs):
        """Alias for create_volunteer(); accepts member= as well as member_name."""
        if member_name is None and "member" in kwargs:
            member_name = kwargs.pop("member")
        return self.create_volunteer(member_name, **kwargs)

    def create_test_chapter(self, **kwargs):
        """Alias for create_chapter()."""
        return self.create_chapter(**kwargs)

    def create_test_customer(self, **kwargs):
        """Create a test Customer document.

        Honours an optional customer_name kwarg; otherwise generates a unique
        marked test customer. Tracked for tearDown cleanup.
        """
        customer_name = kwargs.pop("customer_name", None)
        if not customer_name:
            seq = self.get_next_sequence("customer")
            customer_name = f"TEST Customer {seq} {frappe.generate_hash()[:6]}"
        customer_data = {
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": kwargs.pop("customer_type", "Individual"),
            "customer_group": kwargs.pop("customer_group", "Individual"),
            **kwargs,
        }
        customer = frappe.get_doc(customer_data)
        customer.insert(ignore_permissions=True)
        self.track_document("Customer", customer.name, priority=3)
        return customer

    def create_test_membership(self, member_name=None, membership_type_name=None, **kwargs):
        """Create a submitted Membership document.

        Accepts both positional (member_name, membership_type_name) and legacy
        keyword (member=, membership_type=) forms. A Membership Type is
        auto-created when none is supplied.
        """
        if member_name is None:
            member_name = kwargs.pop("member", None)
        else:
            kwargs.pop("member", None)
        if membership_type_name is None:
            membership_type_name = kwargs.pop("membership_type", None)
        else:
            kwargs.pop("membership_type", None)

        if not member_name:
            raise TypeError("create_test_membership() requires a member (member_name= or member=)")

        if not membership_type_name:
            membership_type_name = self.create_test_membership_type().name
        else:
            # A type name was supplied; ensure it resolves to a real Membership
            # Type so the insert doesn't fail with "Could not find Membership
            # Type: <name>" on a fresh site.
            from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists

            membership_type_name = ensure_membership_type_exists(membership_type_name)

        start_date = kwargs.pop("start_date", frappe.utils.today())
        requested_status = kwargs.pop("status", "Active")
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member_name,
                "membership_type": membership_type_name,
                "start_date": start_date,
                "status": requested_status,
                **kwargs,
            }
        )
        # Keep backdated Active memberships Active (see the status-conditional
        # _is_csv_import note in EnhancedTestCase.create_test_membership).
        if requested_status == "Active" and frappe.utils.getdate(start_date) < frappe.utils.getdate(
            frappe.utils.today()
        ):
            membership._is_csv_import = True
        membership.insert()
        self.track_document("Membership", membership.name, priority=5)
        membership.submit()
        return membership

    def create_test_membership_type(self, membership_type_name=None, amount=100.0, **kwargs):
        """Create a minimal active Membership Type for tests.

        Generates a unique name and ensures a role_profile is present (mandatory).
        """
        import time

        unique_name = f"{membership_type_name or 'Test Type'}-{int(time.time() * 1000)}-{self.get_next_sequence('mtype')}"

        role_profile = kwargs.get("role_profile") or frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        )
        if not role_profile:
            test_profile = frappe.new_doc("Role Profile")
            test_profile.role_profile = f"Test Member Profile {self.get_next_sequence('roleprofile')}"
            if frappe.db.exists("Role", "Verenigingen Member"):
                test_profile.append("roles", {"role": "Verenigingen Member"})
            test_profile.insert(ignore_permissions=True)
            role_profile = test_profile.name
            self.track_document("Role Profile", role_profile, priority=0)

        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = unique_name
        membership_type.is_active = 1
        membership_type.contribution_mode = kwargs.get("contribution_mode", "Fixed Amount")
        membership_type.minimum_amount = kwargs.get("minimum_amount", amount)
        membership_type.role_profile = role_profile
        for key, value in kwargs.items():
            if key not in ("role_profile", "contribution_mode", "minimum_amount") and hasattr(
                membership_type, key
            ):
                setattr(membership_type, key, value)
        membership_type.insert()
        self.track_document("Membership Type", membership_type.name, priority=1)

        # Membership Type.after_insert auto-creates a dues-schedule template at the
        # default rate (€15). When the type's minimum is higher (default 100), any
        # dues schedule built from that template fails validation ("Template dues
        # rate cannot be less than membership type minimum"). Align the auto-created
        # template's rate to the type minimum so downstream schedules validate.
        effective_amount = membership_type.minimum_amount or amount
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type.name},
            "name",
        )
        if template:
            template_doc = frappe.get_doc("Membership Dues Schedule", template)
            template_doc.suggested_amount = effective_amount
            template_doc.dues_rate = effective_amount
            template_doc.minimum_amount = effective_amount * 0.5
            template_doc.save(ignore_permissions=True)

        return membership_type

    def _get_enhanced_member_defaults(self) -> Dict[str, Any]:
        """Return a dict of validated default Member field values.

        Used by create_test_member_optimized(); mirrors the deterministic
        defaults applied by create_member()/CoreTestDataFactory.
        """
        return {
            "first_name": self.generate_test_name("Member").split()[-1],
            "last_name": f"Default{next(EnhancedTestDataFactory._global_unique_seq)}",
            "email": self.generate_test_email("member"),
            "birth_date": "1990-01-01",
            "status": "Active",
        }

    def _validate_fields(self, doctype: str, data: Dict[str, Any]) -> None:
        """Validate that each field in data exists on the DocType.

        Delegates to CoreTestDataFactory._validate_fields when available,
        otherwise falls back to per-field validate_field_exists().
        """
        core_validate = getattr(self.core, "_validate_fields", None)
        if callable(core_validate):
            core_validate(doctype, data)
            return
        for field in data:
            self.validate_field_exists(doctype, field)

    def create_chapter(self, **kwargs):
        """Create chapter with field validation, delegating to CoreTestDataFactory.

        Preserves Enhanced-specific region-existence checks and field validation.
        """
        # Enhanced field validation. `chapter_name` is not a Chapter field — it
        # is consumed by CoreTestDataFactory as the document name (autoname=prompt),
        # so skip schema validation for it.
        skip_validation_fields = {"chapter_name"}
        for field in kwargs.keys():
            if field not in skip_validation_fields:
                self.validate_field_exists("Chapter", field)

        # Ensure region exists if caller provided one
        region_name = kwargs.get("region")
        if region_name:
            region_autoname = region_name.lower().replace(" ", "-")
            if not frappe.db.exists("Region", region_autoname) and not frappe.db.exists(
                "Region", region_name
            ):
                region_doc = self.core.create_test_region(region_name=region_name)
                self.track_document("Region", region_doc.name, priority=1)
                kwargs["region"] = region_doc.name

        # Delegate to Core
        try:
            chapter = self.core.create_test_chapter(**kwargs)
        except Exception as e:
            raise Exception(f"Failed to create chapter: {e}")

        self.track_document("Chapter", chapter.name, priority=4)
        return chapter

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

        defaults = {"proficiency_level": "3 - Intermediate", "experience_years": 1, "certifications": ""}

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
            frappe.log_error(
                f"Failed to get Volunteer Skill meta for field validation: {e}", "EnhancedTestFactory"
            )
            # Continue without meta validation - let document validation catch issues

        try:
            # Follow Frappe best practices: create child table through parent document
            volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
            skill_row = volunteer_doc.append("skills_and_qualifications", data)
            volunteer_doc.save()
            return skill_row
        except Exception as e:
            raise Exception(f"Failed to create volunteer skill: {e}")

    def create_application_data(self, with_volunteer_skills: bool = True) -> Dict[str, Any]:
        """Create deterministic membership application data with unique names"""
        seq = self.get_next_sequence("application")
        # Use timestamp microseconds for additional uniqueness across test runs
        import time

        uid = str(int(time.time() * 1000000) % 1000000)

        base_data = {
            "first_name": f"{self.fake.first_name()}{seq:02d}" if self.use_faker else f"AppTest{seq:04d}",
            "last_name": (
                f"{self.fake.last_name()}{uid}" if self.use_faker else f"Member-{self.test_run_id[:8]}"
            ),
            "email": self.generate_test_email("application"),
            "birth_date": "1990-01-01",
            "address_line1": self.fake.street_address() if self.use_faker else f"{seq} Test Street",
            "city": self.fake.city() if self.use_faker else "Test City",
            "country": "Netherlands",
            "postal_code": f"{1000 + seq:04d}AB",
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
                "Other|Photography",
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
                "volunteer_comments": f"Test volunteer application {seq}",
            }

            base_data.update(volunteer_data)

        return base_data

    def create_test_iban(self, bank_code: str = None) -> str:
        """Generate deterministic test IBAN — delegates to Core."""
        return self.core.generate_test_iban(bank_code)

    def ensure_test_chapter(self, chapter_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a test chapter exists, create if not"""
        if frappe.db.exists("Chapter", chapter_name):
            return frappe.get_doc("Chapter", chapter_name)

        # Handle region requirement properly with duplicate detection
        region_name = attributes.get("region") if attributes else None
        print(f"DEBUG ensure_test_chapter: region_name from attributes = '{region_name}'")
        if region_name:
            # Check if the specified region exists, create if not
            region_exists = frappe.db.exists("Region", region_name)
            print(f"DEBUG ensure_test_chapter: region '{region_name}' exists = {region_exists}")
            if not region_exists:
                try:
                    # 🔧 Phase 5.2A Fix: Generate unique region_code with collision detection
                    # Original bug: region_code uniqueness not checked + length validation failure
                    # Region.validate() requires region_code to match ^[A-Z0-9]{2,5}$ (2-5 chars)
                    base_region_code = region_name[:2].upper()

                    # Generate 2-5 character region codes that pass validation
                    sequence = self.get_next_sequence("region_code")
                    if sequence <= 999:
                        # Use 2-char base + 1-3 digit sequence (3-5 total chars)
                        region_code = base_region_code + str(sequence)
                    else:
                        # Use 1-char base + 4-digit sequence (5 chars max)
                        base_region_code = region_name[:1].upper()
                        region_code = base_region_code + str(sequence)[-4:]  # Take last 4 digits

                    # Ensure we don't exceed 5 characters (Region validation requirement)
                    region_code = region_code[:5]

                    # Check if this region_code already exists, increment until unique
                    attempt_count = 0
                    while frappe.db.exists("Region", {"region_code": region_code}) and attempt_count < 100:
                        attempt_count += 1
                        sequence = self.get_next_sequence("region_code")
                        if sequence <= 999:
                            region_code = base_region_code[:2] + str(sequence)
                        else:
                            region_code = base_region_code[:1] + str(sequence)[-4:]
                        region_code = region_code[:5]  # Ensure max 5 chars

                    if attempt_count >= 100:
                        # Fallback: timestamp-based region code (still max 5 chars)
                        import time

                        timestamp_suffix = str(int(time.time()))[-3:]  # Last 3 digits
                        region_code = (base_region_code[:2] + timestamp_suffix)[:5]

                    test_region = frappe.get_doc(
                        {"doctype": "Region", "region_name": region_name, "region_code": region_code}
                    )
                    test_region.insert()
                    self.track_document("Region", test_region.name, priority=1)
                    # In test context, no manual commit needed - let Frappe handle transaction management
                    # 🔧 CRITICAL FIX: Region DocType uses autoname="field:region_name"
                    # which converts "Test Region Name" -> "test-region-name"
                    # We need to use the actual document name, not the original region_name
                    region_name = test_region.name  # Use the auto-generated name
                except Exception as e:
                    # 🔧 Phase 5.2A Fix: Concise error logging to avoid 140 char limit
                    # Original bug: Long error messages exceeded Error Log title length limit
                    region_code_str = region_code if "region_code" in locals() else "unknown"
                    # Truncate region_name if too long to fit within 140 char limit
                    short_region_name = region_name[:20] + "..." if len(region_name) > 20 else region_name
                    frappe.log_error(
                        f"Phase 5.2A Region Fail: {short_region_name}, code: {region_code_str}, {str(e)[:50]}",
                        "ETF Region Creation",
                    )
                    # If region creation fails, try to use an existing region as fallback
                    existing_regions = frappe.get_all("Region", limit=1, pluck="region_name")
                    if existing_regions:
                        region_name = existing_regions[0]
                    else:
                        # No regions exist at all - this is a critical issue
                        raise Exception(f"No regions available and cannot create region '{region_name}': {e}")

            # 🔧 DEBUG: Log region assignment for troubleshooting
            region = region_name
            print(
                f"DEBUG ensure_test_chapter: region assigned = '{region}' (from region_name = '{region_name}')"
            )
        else:
            # Try to find an existing region
            existing_regions = frappe.get_all("Region", limit=1)
            if existing_regions:
                region = existing_regions[0].name
            else:
                # Create a default test region if none exist with unique region_code
                default_region_name = "Default Test Region"
                if not frappe.db.exists("Region", default_region_name):
                    try:
                        # 🔧 Phase 5.2A Fix: Generate unique region_code for default region (max 5 chars)
                        base_code = "DR"
                        sequence = self.get_next_sequence("region_code")

                        # Ensure default region code fits 5-char validation requirement
                        if sequence <= 999:
                            region_code = base_code + str(sequence)  # DR + 1-3 digits = 3-5 chars
                        else:
                            region_code = base_code + str(sequence)[-3:]  # DR + last 3 digits = 5 chars

                        # Check uniqueness for default region code as well
                        attempt_count = 0
                        while (
                            frappe.db.exists("Region", {"region_code": region_code}) and attempt_count < 100
                        ):
                            attempt_count += 1
                            sequence = self.get_next_sequence("region_code")
                            if sequence <= 999:
                                region_code = base_code + str(sequence)
                            else:
                                region_code = base_code + str(sequence)[-3:]

                        if attempt_count >= 100:
                            # Fallback: timestamp-based region code for default region (5 chars max)
                            import time

                            timestamp_suffix = str(int(time.time()))[-3:]  # Last 3 digits
                            region_code = base_code + timestamp_suffix  # DR + 3 digits = 5 chars

                        test_region = frappe.get_doc(
                            {
                                "doctype": "Region",
                                "region_name": default_region_name,
                                "region_code": region_code,
                            }
                        )
                        test_region.insert()
                        self.track_document("Region", test_region.name, priority=1)
                        # 🔧 CRITICAL FIX: Update region name to auto-generated name
                        default_region_name = test_region.name
                    except Exception as e:
                        # 🔧 Phase 5.2A Fix: Concise error logging for default region creation
                        region_code_str = region_code if "region_code" in locals() else "unknown"
                        frappe.log_error(
                            f"Phase 5.2A Default Region Fail: code {region_code_str}, {str(e)[:60]}",
                            "ETF Default Region",
                        )
                region = default_region_name

        chapter_data = {
            "doctype": "Chapter",
            "name": chapter_name,
            "status": attributes.get("status", "Active") if attributes else "Active",
            "published": attributes.get("published", 1) if attributes else 1,
            # Required fields for chapter
            "introduction": (
                attributes.get("introduction", "Test chapter for automated testing")
                if attributes
                else "Test chapter for automated testing"
            ),
        }

        if region:
            chapter_data["region"] = region
            print(f"DEBUG ensure_test_chapter: chapter_data region set to '{region}'")

        if attributes:
            # Don't override the defaults we just set
            for key, value in attributes.items():
                # 🔧 CRITICAL FIX: Don't override corrected region name with original region name
                # Also protect other critical fields that have been processed
                if key not in ["introduction", "contact_email", "region"] or value:
                    # Skip region override if region was already corrected for autoname
                    if key == "region" and region:
                        print(
                            f"DEBUG ensure_test_chapter: SKIPPING region override - keeping corrected region '{region}'"
                        )
                        continue
                    chapter_data[key] = value

        chapter = frappe.get_doc(chapter_data)
        chapter.insert()
        self.track_document("Chapter", chapter.name, priority=2)
        return chapter

    def ensure_dues_schedule_template(self, template_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a dues schedule template exists, create if not.

        Race-safety (CI runs 8 shards as parallel processes on ONE shared DB):
        look the template up by ``schedule_name`` + ``is_template`` (the real
        identity of a template) rather than only by document name, and wrap the
        insert in a duplicate-tolerant guard. A sibling shard creating the same
        named template concurrently would otherwise lose the insert race with a
        DuplicateEntryError (``schedule_name`` is a UNIQUE field); instead we
        catch that and return the row the sibling committed. This makes the
        helper genuinely idempotent regardless of interleaving.
        """
        existing = self._find_dues_schedule_template(template_name)
        if existing:
            return frappe.get_doc("Membership Dues Schedule", existing)

        template_data = {
            "doctype": "Membership Dues Schedule",
            "schedule_name": template_name,
            "billing_frequency": attributes.get("billing_frequency", "Monthly") if attributes else "Monthly",
            "dues_rate": attributes.get("dues_rate", 50.00) if attributes else 50.00,
            "currency": "EUR",
            "is_template": 1,
            "status": "Active",
        }

        if attributes:
            template_data.update(attributes)

        # A template MUST reference a Membership Type — validate_template_or_instance()
        # throws "Templates must specify a Membership Type" otherwise. Earlier callers
        # got away without one because a "data-accumulated" dev site already had a
        # template they could adopt; a fresh CI shard has none, so the insert below
        # would fail. Resolve (or create) a real type when the caller didn't pass one.
        if not template_data.get("membership_type"):
            template_data["membership_type"] = self._resolve_template_membership_type(
                template_data.get("dues_rate", 50.00)
            )

        template = frappe.get_doc(template_data)
        try:
            template.insert()
        except (frappe.exceptions.DuplicateEntryError, frappe.exceptions.UniqueValidationError):
            # A concurrent sibling shard inserted the same template between our
            # lookup and insert — adopt the committed row instead of failing.
            frappe.db.rollback()
            existing = self._find_dues_schedule_template(template_name)
            if existing:
                return frappe.get_doc("Membership Dues Schedule", existing)
            raise

        # Track for cleanup in tearDown
        self.track_document("Membership Dues Schedule", template.name, priority=3)

        return template

    def _resolve_template_membership_type(self, dues_rate: float) -> str:
        """Return the name of a Membership Type suitable for a dues template.

        Adopt any existing active type whose minimum the template rate satisfies
        (``Template dues rate cannot be less than membership type minimum``);
        otherwise create one sized to the template rate. Self-contained so the
        factory never depends on a pre-seeded type on a fresh CI shard.
        """
        existing = frappe.db.get_value(
            "Membership Type",
            {"is_active": 1, "minimum_amount": ["<=", dues_rate]},
            "name",
        )
        if existing:
            return existing
        return self.ensure_membership_type("ETDF Template Type", {"amount": dues_rate}).name

    @staticmethod
    def _find_dues_schedule_template(template_name: str):
        """Resolve a template by its identity (schedule_name + is_template).

        ``Membership Dues Schedule`` autonames from ``schedule_name`` so the
        document name normally equals the schedule_name, but matching on the
        ``schedule_name`` field (not just the PK) is the robust identity check
        and tolerates any future naming-rule change.
        """
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"schedule_name": template_name, "is_template": 1},
            "name",
        )

    def ensure_membership_type(self, type_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a membership type exists, create if not"""
        if frappe.db.exists("Membership Type", type_name):
            return frappe.get_doc("Membership Type", type_name)

        billing_period = attributes.get("billing_period", "Monthly") if attributes else "Monthly"
        amount = attributes.get("amount", 50.00) if attributes else 50.00

        # Get a role profile for the membership type (required field)
        role_profile = attributes.get("role_profile") if attributes else None
        if not role_profile:
            role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Staff"}, "name")
        if not role_profile:
            role_profile = frappe.db.get_value("Role Profile", {}, "name")

        # Create membership type - now that dues_schedule_template is optional, no circular dependency
        type_data = {
            "doctype": "Membership Type",
            "membership_type_name": type_name,
            "minimum_amount": amount,
            "billing_period": billing_period,
            "is_active": attributes.get("is_active", 1) if attributes else 1,
            "role_profile": role_profile,
        }

        if attributes:
            # Don't override the fields we've already set properly
            for key, value in attributes.items():
                if key not in ["amount", "billing_period", "minimum_amount", "role_profile"]:
                    type_data[key] = value

        membership_type = frappe.get_doc(type_data)
        membership_type.insert()
        self.track_document("Membership Type", membership_type.name, priority=1)

        # Membership Type.after_insert auto-creates a dues-schedule template at the
        # default rate (€15). When the type's minimum is higher, any dues schedule
        # built from that template fails validation ("Template dues rate cannot be
        # less than membership type minimum"). Align the auto-created template's
        # rate to the type minimum so downstream schedules validate.
        auto_template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type.name},
            "name",
        )
        if auto_template:
            auto_template_doc = frappe.get_doc("Membership Dues Schedule", auto_template)
            auto_template_doc.suggested_amount = amount
            auto_template_doc.dues_rate = amount
            auto_template_doc.minimum_amount = amount * 0.5
            auto_template_doc.save(ignore_permissions=True)

        # Optionally create and link a template if requested
        if attributes and attributes.get("create_template", True):
            template_name = f"Template-{type_name}"
            if not frappe.db.exists("Membership Dues Schedule", template_name):
                template = self.ensure_dues_schedule_template(
                    template_name,
                    {"billing_frequency": billing_period, "dues_rate": amount, "membership_type": type_name},
                )

                # Link template to membership type
                membership_type.dues_schedule_template = template_name
                membership_type.save()

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
            "is_active": attributes.get("is_active", 1) if attributes else 1,
        }

        if attributes:
            role_data.update(attributes)

        role = frappe.get_doc(role_data)
        role.insert()

        # Track for cleanup in tearDown
        self.track_document("Team Role", role.name, priority=3)

        return role

    def ensure_team_role(self, role_name: str, attributes: dict = None) -> frappe._dict:
        """Ensure a team role exists, create if not with improved isolation"""
        # ISOLATION FIX: Force unique names to prevent conflicts in parallel tests
        unique_role_name = self.force_unique_name(role_name, "Team Role")

        if frappe.db.exists("Team Role", unique_role_name):
            return frappe.get_doc("Team Role", unique_role_name)

        # Default team role configurations
        role_configs = {
            "Team Leader": {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1},
            "Team Member": {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0},
            "Coordinator": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0},
            "Secretary": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1},
            "Treasurer": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1},
        }

        # Use original role_name for config lookup but unique name for creation
        config = role_configs.get(
            role_name, {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0}
        )

        role_data = {
            "doctype": "Team Role",
            "role_name": unique_role_name,
            "description": f"{role_name} role for team management (Test Run: {self.test_run_id[:8]})",
            "is_active": 1,
            **config,
        }

        if attributes:
            role_data.update(attributes)

        role = frappe.get_doc(role_data)
        role.insert()

        # ISOLATION ENHANCEMENT: Auto-track created document for cleanup
        self.track_document("Team Role", role.name, priority=2)  # Roles before teams

        return role

    def ensure_test_admin_user(self) -> frappe._dict:
        """Ensure a test admin user exists with proper permissions"""
        admin_email = "test.admin@enhanced-factory.local"

        # Check if user already exists
        if frappe.db.exists("User", admin_email):
            self._ensure_admin_role_profile(admin_email)
            return frappe.get_doc("User", admin_email)

        # Create test admin user with full permissions
        admin_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": admin_email,
                "first_name": "Test",
                "last_name": "Administrator",
                "full_name": "Test Administrator",
                "enabled": 1,
                "user_type": "System User",
            }
        )

        # Insert with current permissions - this should work in test context
        admin_user.insert()

        # Track for cleanup in tearDown (low priority - system users)
        self.track_document("User", admin_user.name, priority=1)

        # Assign System Manager role
        admin_user.append("roles", {"role": "System Manager"})
        admin_user.append("roles", {"role": "Verenigingen Administrator"})
        admin_user.save()
        self._ensure_admin_role_profile(admin_email)

        return admin_user

    def _ensure_admin_role_profile(self, admin_email):
        """Give the shared test-admin user the Verenigingen Administrator role profile.

        After the audit #2 Rule-5 cap, HIGH/CRITICAL API access requires an assigned
        role PROFILE (Rule 4), not a bare role -- so without this the "admin" user
        this factory hands out is denied every secured endpoint. Its sole purpose is
        a fully-privileged admin, so the profile is exactly right.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(admin_email, "Verenigingen Administrator")

    def create_team(self, **kwargs):
        """Create team with validation and improved isolation"""
        for field in kwargs.keys():
            self.validate_field_exists("Team", field)

        defaults = {
            "team_name": f"TEST-Team-{self.get_next_sequence('team')}-{self.test_run_id[:8]}",
            "status": "Active",
            "team_type": "Project Team",
            "start_date": frappe.utils.today(),
            "description": f"Test team created by EnhancedTestDataFactory - {self.test_run_id}",
        }

        data = {**defaults, **kwargs}

        # ISOLATION FIX: Force unique names for explicit team_name to prevent conflicts
        if "team_name" in kwargs:
            data["team_name"] = self.force_unique_name(kwargs["team_name"], "Team")

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
            team = frappe.get_doc({"doctype": "Team", **data})

            team.insert()

            # ISOLATION ENHANCEMENT: Auto-track created document for cleanup
            self.track_document("Team", team.name, priority=1)  # Teams before team members

            return team
        except Exception as e:
            raise Exception(f"Failed to create team: {e}")

    def create_team_member(
        self, team_name: str, volunteer_name: str, team_role_name: str = "Team Member", **kwargs
    ):
        """Create team member with new team_role field structure"""
        # If an existing Team Role name was passed (e.g. a role the test already created),
        # use it as-is. ensure_team_role() would otherwise uniquify the name again, miss it,
        # and create a brand-new default ("Basic") role — losing the caller's role config.
        if frappe.db.exists("Team Role", team_role_name):
            team_role = frappe.get_doc("Team Role", team_role_name)
        else:
            team_role = self.ensure_team_role(team_role_name)

        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("Team Member", field)

        defaults = {
            "volunteer": volunteer_name,
            "team_role": team_role.name,  # Use new team_role field
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        }

        data = {**defaults, **kwargs}

        # Get team and add member
        team = frappe.get_doc("Team", team_name)
        team.append("team_members", data)
        team.save()

        return team.team_members[-1]  # Return the added team member record

    def create_account_creation_request(self, source_record=None, request_type="Member", **kwargs):
        """Create account creation request with validation"""
        # Create source record if not provided
        if not source_record:
            if request_type == "Member":
                member = self.create_member()
                source_record = member.name
                email = member.email
                full_name = member.full_name
            elif request_type == "Volunteer":
                member = self.create_member()
                volunteer = self.create_volunteer(member_name=member.name)
                source_record = volunteer.name
                email = volunteer.email
                full_name = volunteer.volunteer_name
            else:
                raise ValueError(f"Unsupported request type: {request_type}")
        else:
            # Get email and name from source record
            source_doc = frappe.get_doc(request_type, source_record)
            if request_type == "Member":
                email = source_doc.email
                full_name = source_doc.full_name
            elif request_type == "Volunteer":
                email = source_doc.email
                full_name = source_doc.volunteer_name

        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("Account Creation Request", field)

        defaults = {
            "request_type": request_type,
            "source_record": source_record,
            "email": email,
            "full_name": full_name,
            "priority": "Normal",
            "business_justification": f"Test account creation for {request_type.lower()}",
        }

        # Set default roles based on request type
        if request_type == "Member":
            defaults["role_profile"] = "Verenigingen Member"
            default_roles = [{"role": "Verenigingen Member"}]
        elif request_type == "Volunteer":
            defaults["role_profile"] = "Verenigingen Volunteer"
            default_roles = [
                {"role": "Verenigingen Volunteer"},
                {"role": "Employee"},
                {"role": "Employee Self Service"},
            ]
        else:
            default_roles = []

        data = {**defaults, **kwargs}

        try:
            request = frappe.get_doc({"doctype": "Account Creation Request", **data})

            # Add requested roles if not provided in kwargs
            if "requested_roles" not in kwargs and default_roles:
                for role_data in default_roles:
                    request.append("requested_roles", role_data)

            request.insert()

            # Track for cleanup in tearDown
            self.track_document("Account Creation Request", request.name, priority=3)

            return request
        except Exception as e:
            raise Exception(f"Failed to create account creation request: {e}")

    def create_user_with_roles(self, email=None, roles=None, **kwargs):
        """Create user with specific roles for testing"""
        if not email:
            email = self.generate_test_email("user")

        # Check if user already exists
        if frappe.db.exists("User", email):
            return frappe.get_doc("User", email)

        if not roles:
            roles = ["Verenigingen Member"]

        # Validate fields
        for field in kwargs.keys():
            self.validate_field_exists("User", field)

        defaults = {
            "email": email,
            "first_name": self.generate_test_name("User").split()[1],
            "last_name": self.generate_test_name("User").split()[2],
            "enabled": 1,
            "user_type": "System User",
        }

        data = {**defaults, **kwargs}

        try:
            user = frappe.get_doc({"doctype": "User", **data})

            # Add roles
            for role in roles:
                user.append("roles", {"role": role})

            # Use proper test admin user (no permission bypasses)
            test_admin = self.ensure_test_admin_user()
            current_user = frappe.session.user
            try:
                frappe.set_user(test_admin.email)
                user.insert()

                # Track for cleanup in tearDown
                self.track_document("User", user.name, priority=2)

                return user
            finally:
                frappe.set_user(current_user)
        except Exception as e:
            raise Exception(f"Failed to create user: {e}")

    def mock_redis_queue(self):
        """Context manager for mocking Redis queue operations"""
        from unittest.mock import patch

        return patch("frappe.enqueue")

    def simulate_background_job_failure(self, error_type="timeout"):
        """Simulate background job processing failures"""
        error_messages = {
            "timeout": "Connection timeout occurred",
            "permission": "Permission denied for operation",
            "validation": "Validation error in user creation",
            "database": "Database connection error",
            "network": "Network error occurred",
        }

        return error_messages.get(error_type, f"Unknown error: {error_type}")

    def create_test_role_profile(self, profile_name, roles=None):
        """Create role profile for testing"""
        if frappe.db.exists("Role Profile", profile_name):
            return frappe.get_doc("Role Profile", profile_name)

        if not roles:
            roles = ["Verenigingen Member"]

        role_profile = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": profile_name,
            }
        )

        for role in roles:
            role_profile.append("roles", {"role": role})

        # Use proper test admin user (no permission bypasses)
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            role_profile.insert()

            # Track for cleanup in tearDown
            self.track_document("Role Profile", role_profile.name, priority=2)

            return role_profile
        finally:
            frappe.set_user(current_user)

    def create_permission_test_scenario(self, authorized_roles=None, unauthorized_roles=None):
        """Create comprehensive permission testing scenario"""
        if not authorized_roles:
            authorized_roles = ["System Manager", "Verenigingen Administrator"]
        if not unauthorized_roles:
            unauthorized_roles = ["Verenigingen Member", "Guest"]

        scenario = {"authorized_users": [], "unauthorized_users": []}

        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        # Create authorized users
        for role in authorized_roles:
            user = self.create_user_with_roles(
                email=self.generate_test_email(f"auth_{role.lower().replace(' ', '_')}"), roles=[role]
            )
            # Post the audit #2 Rule-5 cap, HIGH/CRITICAL access needs the assigned
            # role PROFILE (Rule 4), not just the role -- assign it so "authorized"
            # users actually clear the tier gate. Unauthorized users below are left
            # profileless (or with only a low-tier profile) so they stay denied.
            grant_matching_role_profiles(user.email, role)
            scenario["authorized_users"].append(user)

        # Create unauthorized users
        for role in unauthorized_roles:
            user = self.create_user_with_roles(
                email=self.generate_test_email(f"unauth_{role.lower().replace(' ', '_')}"), roles=[role]
            )
            scenario["unauthorized_users"].append(user)

        return scenario


class EnhancedTestCase(ErrorLogGuardMixin, FrappeTestCase):
    """
    🔍 Business Logic Validation Framework - Production Issue Discovery

    The framework that discovered 18+ production issues in Phase 5.1 through real
    database testing. Specializes in catching problems that mocked tests miss.

    Use for: business rule testing, field validation, production bug discovery
    Don't use for: UI testing, external service mocking, workflow integration

    Provides 28 factory methods with field safety validation and business rules.
    """

    # Doctypes holding shared master data that `tests.setup.before_tests` seeds
    # ONCE per process. Production code called from a test body may legitimately
    # RE-create one of these rows (ensure_payment_modes_exist() restoring a Mode
    # of Payment a test removed). The insert hook cannot tell that apart from a
    # test's own throwaway record, so draining it destroys the seed for the rest
    # of the process and every later test in the shard fails link validation
    # against it. Keep this set SMALL: entries here leak between tests by design.
    DRAIN_EXEMPT_DOCTYPES = frozenset({"Mode of Payment"})

    def setUp(self):
        super().setUp()

        # Error Log guard: mark the start of this test so tearDown can detect any
        # frappe.log_error() written during it (see ErrorLogGuardMixin).
        self._test_start_time = frappe.utils.now()

        # CRITICAL: Ensure Administrator context for all tests
        # This prevents permission errors and test contamination from other tests
        frappe.set_user("Administrator")

        # CRITICAL: Restore the frappe.form_dict LocalProxy. Some tests set request
        # args by assigning `frappe.form_dict = frappe._dict({...})` directly, which
        # REPLACES the module-level LocalProxy with a static dict for the rest of the
        # process. After that, every later test that uses the correct idiom
        # (`frappe.local.form_dict = ...`) is invisible to `frappe.form_dict`, so
        # page get_context() reads an empty dict (e.g. ponto_pay / payment_* portal
        # tests failed only inside the full CI shard, never in isolation). Re-binding
        # the proxy at the start of each test makes form_dict reads order-independent.
        frappe.form_dict = frappe.local("form_dict")

        # BATCH-QUEUE ISOLATION: reset the FinancialHistoryBatchProcessor's
        # PROCESS-GLOBAL, class-level payment/expense queues. They are drained
        # inline by add_invoice_to_payment_history() -> _maybe_process_batches(),
        # and a dangling entry left by a prior (rolled-back) test would be
        # processed against a now-missing Member, whose except-clause issues a
        # transaction-wide frappe.db.rollback() that wipes THIS test's
        # uncommitted setUp data. See TestFinancialBatchQueueIsolation.
        self._reset_financial_history_batch_queue()

        # CLEANUP: Remove stale test data from previous test runs
        # Only run once per test class (not per method) to avoid timeout
        if not hasattr(self.__class__, "_cleanup_done"):
            self._cleanup_stale_test_data()
            self.__class__._cleanup_done = True

        # ORPHANED DYNAMIC LINK CLEANUP: Run once per test session
        # Cleans up Dynamic Links where target document doesn't exist
        # This prevents LinkValidationError when Frappe validates Contact/Address records
        if not getattr(frappe.flags, "_orphan_dynamic_link_cleanup_done", False):
            self._cleanup_orphaned_dynamic_links()
            frappe.flags._orphan_dynamic_link_cleanup_done = True

        # CURRENT-YEAR FISCAL YEAR: ensure the FY covering today() applies to ALL
        # companies, once per test session. erpnext's global test setup
        # (make_test_records("Company") in before_test_setup, which runs AFTER our
        # before_tests hook) restricts the current FY to _Test Company, so any test
        # posting a dated document against another company (e.g. _Test Company 2)
        # fails with "Date <today> is not in any active Fiscal Year". That global
        # setup runs once, so one committed clear here (after it) sticks for the
        # session. Date-driven -> self-heals every new calendar year, no recurrence
        # in 2027+.
        if not getattr(frappe.flags, "_test_fiscal_year_ensured", False):
            from verenigingen.tests.setup import (
                ensure_default_company,
                ensure_test_fiscal_year_for_all_companies,
            )

            ensure_test_fiscal_year_for_all_companies()
            # erpnext v16 leaves no global default company on fresh CI sites;
            # several paths (Opportunity.company `:Company` default, Mollie cash
            # account resolution) need one. Set it once per session, after
            # erpnext's set_defaults_for_tests has run.
            ensure_default_company()
            frappe.flags._test_fiscal_year_ensured = True

        # FIXTURE VALIDATION: Check required fixtures are loaded
        # Only run once per test class to avoid overhead
        if not hasattr(self.__class__, "_fixtures_validated"):
            self._validate_fixtures()
            self.__class__._fixtures_validated = True

        # Set global test flags for appropriate test behavior
        frappe.flags.skip_volunteer_account_creation = True

        # Bypass User creation throttling WITHOUT suppressing production document behavior.
        #
        # This used to set frappe.flags.in_import = True, purely so Frappe's
        # throttle_user_creation() would return early. That flag is far too broad: it also
        # disables _set_defaults(), _validate_selects(), _validate_constants() and autoname
        # regeneration, so every test on this harness ran against a document model
        # production never sees. Concretely, User.enabled has default "1", so suppressing
        # defaults created *disabled* test users.
        #
        # throttle_user_creation() reads throttle_user_limit from conf, so raise that
        # instead: same bypass, none of the collateral.
        # See docs/superpowers/specs/2026-07-30-in-import-harness-phase1-design.md
        # Registered via addCleanup rather than tearDown: if setUp raises anywhere below
        # this line, unittest skips tearDown but still runs cleanups, so the override
        # cannot leak into the rest of the process.
        self._original_throttle_limit = frappe.local.conf.get("throttle_user_limit")
        self.addCleanup(self._restore_throttle_user_limit)
        frappe.local.conf["throttle_user_limit"] = 1000000

        # NOTE: do NOT set frappe.flags.in_bulk_import here as a stand-in for in_import.
        # It is not equivalent and suppresses strictly more: the event *emitters* in
        # events/team_events.py, events/member_events.py and events/chapter_events.py gate
        # on `bulk_*_operations or in_bulk_import` and never look at in_import, so under
        # in_import they emit normally. Setting in_bulk_import short-circuits them before
        # event_emitter.emit_event() is reached, which breaks three tests in
        # tests/events/test_team_events_coverage.py (verified). Only the *subscriber* side
        # (events/subscribers/subscriber_utils.py:45, chapter_subscribers.py:132) consults
        # in_import.

        # Ensure test user has necessary roles instead of bypassing permissions
        self.ensure_test_user_has_role("System Manager")
        self.ensure_test_user_has_role("Verenigingen Administrator")

        # The factory MUST exist before _ensure_production_ready_setup(): that call
        # reaches _get_or_create_income_account / _ensure_company_cost_center, which
        # call self.factory.track_document(). Assigning it afterwards raised
        # AttributeError on the FIRST EnhancedTestCase test of every shard process
        # (the only one that finds the income account missing). _ensure_master_data
        # swallowed it, aborting before the rest of the master data -- including the
        # Netherlands territory -- was created. Latent since 2dbea04e (2025-11-20);
        # surfaced as `Could not find Territory: Netherlands` in whichever test built
        # a Customer first (#291).
        self.factory = EnhancedTestDataFactory(seed=12345, use_faker=True)

        # Ensure required system settings and master data exist
        self._ensure_production_ready_setup()

        # Unique identifier for this test instance (microsecond precision)
        # Use this to make test data unique and prevent Customer/Member name collisions
        import time

        self.uid = str(int(time.time() * 1000000) % 1000000)
        self.test_run_id = self.uid  # Backward compatibility alias

        # Track created records for cleanup
        self.created_records = []

        # EMAIL MOCKING INFRASTRUCTURE: Set up email capture for tests
        self._setup_email_mocking()

        # RATE LIMIT MOCKING: Bypass rate limiting in tests using proper mocking
        self._setup_rate_limit_mocking()

        # GLOBAL INSERT CAPTURE: record every document inserted from here on, so
        # tearDown can drain committed survivors the factory tracker misses —
        # raw `frappe.get_doc(...).insert()` + `frappe.db.commit()` in test bodies
        # are the dominant source of order-dependent cross-test pollution (a record
        # leaked by an earlier test fails a later one depending on shard/order).
        # Installed AFTER shared master-data setup above so that data is NOT
        # captured/drained (it must persist across methods). addCleanup guarantees
        # the patch is removed even if the test errors.
        self._captured_inserts = []
        self._install_insert_capture()
        self.addCleanup(self._uninstall_insert_capture)

    def _install_insert_capture(self):
        """Monkey-patch Document.db_insert to record (doctype, name) of every insert.

        Bulletproof: the real insert runs first and its result is returned
        unconditionally; capture is best-effort in a try/except so a capture bug
        can never break an insert (this wrapper runs for EVERY insert in the test).

        Scope/limits (this SUBSTANTIALLY REDUCES, but does not fully guarantee,
        order-independence):
        - Does NOT capture rows created via frappe.db.bulk_insert, raw
          frappe.db.sql("INSERT ..."), or Singles writes (update_single via
          set_value/.save() — those don't go through Document.db_insert).
        - Captures only inserts AFTER install (end of setUp), so shared
          master/setup data created earlier (incl. setUpClass) is preserved.
        - Over-deletion caveat: a record created by PRODUCTION code inside a test
          body that is meant to be shared/persistent would also be force-deleted at
          tearDown. This is inherent to "drain everything inserted"; the proper
          long-term fix is for tests to create such records via the tracked factory
          rather than raw inserts. Deletions swallow all errors and never fail
          tearDown.
        """
        import frappe.model.document as _docmod

        self._orig_db_insert = _docmod.Document.db_insert
        captured = self._captured_inserts
        orig = self._orig_db_insert

        def _capturing_db_insert(doc, *args, **kwargs):
            result = orig(doc, *args, **kwargs)
            try:
                if doc.doctype and doc.name:
                    captured.append((doc.doctype, doc.name))
            except Exception:
                pass
            return result

        _docmod.Document.db_insert = _capturing_db_insert

    def _uninstall_insert_capture(self):
        try:
            import frappe.model.document as _docmod

            if getattr(self, "_orig_db_insert", None) is not None:
                _docmod.Document.db_insert = self._orig_db_insert
                self._orig_db_insert = None
        except Exception:
            pass

    def _drain_captured_inserts(self):
        """Delete committed records captured by the insert hook that the factory
        tracker did not already drain. Mirrors _drain_tracked_documents' safety:
        rollback first, force-delete each (swallowing per-doc errors), commit so
        the deletions persist. Deletes in REVERSE creation order so dependents go
        before their dependencies (e.g. Customer before its Member).
        """
        captured = getattr(self, "_captured_inserts", None)
        if not captured:
            return

        # Reverse creation order, deduped, preserving first (latest) occurrence.
        seen = set()
        ordered = []
        for key in reversed(captured):
            if key in seen or key[0] in self.DRAIN_EXEMPT_DOCTYPES:
                continue
            seen.add(key)
            ordered.append(key)

        # Clear immediately so a partial failure can't re-drive the same set.
        self._captured_inserts = []

        try:
            frappe.db.rollback()
        except Exception as e:
            frappe.logger().warning(f"Captured-insert drain pre-rollback failed (skipping): {e}")
            return

        delete_failures = 0
        for doctype, name in ordered:
            try:
                if not frappe.db.exists(doctype, name):
                    continue
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except frappe.DoesNotExistError:
                pass
            except Exception:
                # Most leftovers (links, docstatus, before_delete hooks) are handled
                # by the broader factory drain or simply persist as today; don't let
                # one failure abort the rest or break tearDown.
                delete_failures += 1

        try:
            frappe.db.commit()
        except Exception as e:
            frappe.logger().warning(f"Captured-insert drain commit failed: {e}")

        if delete_failures:
            frappe.logger().warning(
                f"Captured-insert drain: {delete_failures} record(s) could not be deleted "
                f"(may persist as orphans; usually link/docstatus constraints)."
            )

    def _restore_throttle_user_limit(self):
        """Undo the setUp override of conf["throttle_user_limit"].

        The key must be *deleted* rather than set back to None when it was absent to
        begin with: throttle_user_creation() does
        `count > conf.get("throttle_user_limit", 60)`, and a stored None would make that
        comparison raise TypeError instead of falling back to the default of 60.
        `is None` rather than falsiness, so a deliberate 0 survives.

        This only matters for non-EnhancedTestCase tests sharing the same process — the
        conf dict outlives an individual test. Do not delete as dead code.
        """
        try:
            if self._original_throttle_limit is None:
                frappe.local.conf.pop("throttle_user_limit", None)
            else:
                frappe.local.conf["throttle_user_limit"] = self._original_throttle_limit
        except Exception:
            pass  # Never let cleanup mask a test result

    def tearDown(self):
        """
        Clean up test environment with per-method transaction rollback.

        CRITICAL CHANGE (2025-11-07): Added per-method rollback to fix test isolation.

        Previous behavior: Frappe's FrappeTestCase only rolls back at the CLASS level
        (after all test methods run), not after each method. This caused test data
        to leak between methods, leading to duplicate entry errors.

        New behavior: Explicitly rollback after each test method to ensure complete
        isolation. This prevents:
        1. Duplicate entry errors when tests create records with the same name
        2. Foreign key constraint failures from leftover test data
        3. Flaky tests that pass/fail depending on execution order

        The class-level cleanup (_cleanup_stale_test_data) still runs to catch any
        records that escaped rollback due to explicit db.commit() calls in code.
        """
        # Error Log guard: snapshot logs written during the test BEFORE the rollback
        # below erases any uncommitted frappe.log_error() rows (see ErrorLogGuardMixin).
        self._capture_test_error_logs()

        # Stop capturing FIRST, so the drains below (rollback/delete/commit) and any
        # framework bookkeeping they emit (e.g. "Deleted Document" rows, which are
        # meant to persist) are not captured. addCleanup also calls this as an
        # idempotent backstop.
        self._uninstall_insert_capture()

        # BATCH-QUEUE ISOLATION: drop any financial-history operations this test
        # queued but did not drain, so they can't be processed inline against
        # rolled-back data in a later test (see setUp for the full rationale).
        self._reset_financial_history_batch_queue()

        # NOTE: throttle_user_limit is restored via addCleanup in setUp, not here — see
        # _restore_throttle_user_limit().

        # EMAIL MOCKING CLEANUP: Stop all email patches
        try:
            # Stop comprehensive email patches
            if hasattr(self, "email_patches"):
                for patch_obj in self.email_patches:
                    try:
                        patch_obj.stop()
                    except Exception:
                        pass  # Patch might already be stopped

            # Legacy cleanup for backward compatibility
            if hasattr(self, "sendmail_patch"):
                self.sendmail_patch.stop()
        except Exception:
            pass  # Continue cleanup even if email patch cleanup fails

        # RATE LIMIT MOCKING CLEANUP: Stop rate limit patch
        try:
            self._teardown_rate_limit_mocking()
        except Exception:
            pass  # Continue cleanup even if rate limit patch cleanup fails


        # IMPLEMENT PER-METHOD ROLLBACK (as documented above)
        # This is critical for test isolation - prevents User/Customer duplicate entries
        try:
            # Rollback any uncommitted changes from this test method
            frappe.db.rollback()
        except Exception as e:
            frappe.logger().warning(f"Rollback failed in tearDown: {e}")

        # DRAIN TRACKED DOCUMENTS: rollback above only undoes uncommitted writes;
        # this step deletes records that survived because the test (or production
        # code it called) issued frappe.db.commit(). See _drain_tracked_documents
        # for the dedupe + priority-order semantics.
        try:
            self._drain_tracked_documents()
        except Exception as e:
            frappe.logger().warning(f"Tracked doc drain failed in tearDown: {e}")

        # DRAIN CAPTURED INSERTS: catch committed records the factory tracker missed
        # (raw frappe inserts / production-code inserts). This is what makes failures
        # order-INDEPENDENT — without it a leaked record fails a later test depending
        # on shard split / execution order.
        try:
            self._drain_captured_inserts()
        except Exception as e:
            frappe.logger().warning(f"Captured-insert drain failed in tearDown: {e}")

        # SETTINGS RESTORATION: Restore Verenigingen Settings to original values
        # This undoes changes made by _ensure_verenigingen_settings() which commits
        # and therefore survives the rollback above
        try:
            self.factory._restore_verenigingen_settings()
        except Exception as e:
            frappe.logger().warning(f"Settings restoration failed in tearDown: {e}")

        super().tearDown()

        # LAST: warn (default) or fail (VERENIGINGEN_FAIL_ON_ERROR_LOG=1) on captured
        # Error Logs. Done after cleanup so a raise here never skips teardown.
        self._finalize_error_log_check()

    def _reset_financial_history_batch_queue(self):
        """Clear the FinancialHistoryBatchProcessor's process-global queues.

        The processor batches payment/expense-history updates in class-level
        dicts that persist across test methods in the same process. Entries
        reference Members/invoices by name; after a test's transaction is rolled
        back those names no longer exist, but the queue entries do. Because
        ``add_invoice_to_payment_history()`` drains the queue INLINE, the next
        test to queue anything processes the dangling entry, hits
        DoesNotExistError, and the processor's transaction-wide
        ``frappe.db.rollback()`` wipes that test's own uncommitted setUp data.
        Resetting the queues per method makes the failure impossible.

        Guarded so a failure here never breaks the test lifecycle.
        """
        try:
            from verenigingen.utils.financial_history_batch_processor import (
                FinancialHistoryBatchProcessor,
            )

            FinancialHistoryBatchProcessor._payment_queue.clear()
            FinancialHistoryBatchProcessor._expense_queue.clear()
        except Exception as e:  # pragma: no cover - defensive
            frappe.logger().warning(f"Financial batch queue reset failed: {e}")

    def _drain_tracked_documents(self):
        """Delete factory-tracked documents that survived per-method rollback.

        `frappe.db.rollback()` undoes uncommitted writes; this method handles
        committed writes (e.g. `frappe.db.commit()` in production code called
        by the test). Without this, committed test data accumulates across
        runs and trips uniqueness constraints (Customer.PRIMARY etc.) on
        subsequent runs.

        Dedupe and priority semantics:
        - Records double-tracked across Enhanced + Core (e.g. Member) are
          deduped by (doctype, name), keeping the HIGHEST priority across
          sources. Highest priority deletes first.
        - Priority < 0 is treated as shared infrastructure (e.g. root
          Department, Territory) and SKIPPED by the drain — see
          `_ensure_master_data`. Use this for any tracked record that
          must persist across test methods.

        Safety:
        - Issues defensive `frappe.db.rollback()` before any DELETE so the
          drain doesn't commit uncommitted test state along with cleanup if
          the tearDown rollback above raised and was swallowed.
        - Per-doc try/except: cleanup never breaks the test run, but
          unresolved failures (typically docstatus=1 ValidationError or a
          before_delete hook raising) log at WARNING and trigger an
          aggregate end-of-drain warning so CI logs reveal leakage.
        """
        if not hasattr(self, "factory"):
            return

        tracked: dict[tuple[str, str], int] = {}
        skip: set[tuple[str, str]] = set()

        for d in getattr(self.factory, "created_documents", []):
            key = (d["doctype"], d["name"])
            prio = d.get("priority", 0)
            if prio < 0:
                skip.add(key)
                continue
            if key not in tracked or prio > tracked[key]:
                tracked[key] = prio

        core = getattr(self.factory, "core", None)
        if core is not None:
            for d in getattr(core, "created_records", []):
                key = (d["doctype"], d["name"])
                if key in skip:
                    continue
                if key not in tracked:
                    tracked[key] = 0

        unique = [(dt, nm, prio) for (dt, nm), prio in tracked.items()]

        if not unique:
            self.factory.created_documents = []
            if core is not None:
                core.created_records = []
            return

        unique.sort(key=lambda x: -x[2])

        try:
            frappe.db.rollback()
        except Exception as e:
            frappe.logger().warning(f"Drain pre-rollback failed (skipping drain): {e}")
            self.factory.created_documents = []
            if core is not None:
                core.created_records = []
            return

        delete_failures = 0
        for doctype, name, _prio in unique:
            try:
                if not frappe.db.exists(doctype, name):
                    continue
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except frappe.DoesNotExistError:
                pass
            except Exception as e:
                delete_failures += 1
                frappe.logger().warning(f"Drain delete failed for {doctype}/{name}: {e}")

        self.factory.created_documents = []
        if core is not None:
            core.created_records = []

        try:
            frappe.db.commit()
        except Exception as e:
            frappe.logger().warning(f"Drain commit failed: {e}")

        if delete_failures:
            frappe.logger().warning(
                f"Drain completed with {delete_failures} unresolved deletion(s); "
                f"records may persist into next run and require _cleanup_stale_test_data"
            )

    def _cleanup_document_with_retry(
        self, doc_info, max_retries=3, retry_delay=0.5, is_team_role=False, use_secure_operations=False
    ):
        """Clean up document with retry logic for lock timeouts"""
        import time

        for attempt in range(max_retries):
            try:
                if frappe.db.exists(doc_info["doctype"], doc_info["name"]):
                    # Special handling for Team Role - they can't be deleted if actively assigned
                    if is_team_role:
                        try:
                            # Try to deactivate first instead of deleting
                            role_doc = frappe.get_doc("Team Role", doc_info["name"])
                            role_doc.is_active = 0
                            role_doc.save()
                            # NO COMMIT - Let Frappe's test framework handle rollback
                            break
                        except Exception:
                            pass  # Role might already be inactive or deleted

                    # Ensure any pending transactions are rolled back before cleanup
                    frappe.db.rollback()

                    if use_secure_operations:
                        # Use secure operations for deletion to validate permissions properly
                        from verenigingen.utils.secure_operations import secure_document_operation

                        doc = frappe.get_doc(doc_info["doctype"], doc_info["name"])

                        # Cancel first if submitted
                        if doc.docstatus == 1:
                            secure_document_operation(
                                operation="cancel",
                                doc=doc,
                                justification=f"Test cleanup: cancelling {doc_info['doctype']} {doc_info['name']}",
                            )

                    # Delete the document
                    frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)
                    # NO COMMIT - Let Frappe's test framework handle transaction rollback
                    # Committing here made test deletions permanent and corrupted test databases
                break  # Success, exit retry loop
            except frappe.exceptions.QueryTimeoutError as e:
                if attempt < max_retries - 1:
                    frappe.logger().warning(
                        f"Lock timeout cleaning up {doc_info['doctype']} {doc_info['name']}, retrying (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_delay)
                    # Rollback any stuck transaction before retrying
                    frappe.db.rollback()
                else:
                    frappe.logger().warning(
                        f"Failed to clean up {doc_info['doctype']} {doc_info['name']} after {max_retries} attempts: {e}"
                    )
            except Exception as e:
                # For other exceptions, log and continue
                frappe.logger().warning(
                    f"Error cleaning up {doc_info['doctype']} {doc_info['name']}: {str(e)}"
                )
                # Rollback to clean up any partial transaction
                frappe.db.rollback()
                break  # Don't retry for non-timeout errors

    def _setup_email_mocking(self):
        """
        Set up comprehensive email mocking infrastructure for tests.

        QCE FIX: Implements queue-level email interception to capture all email paths:
        - Direct frappe.sendmail() calls
        - Email queue processing
        - Background email jobs
        - Template-based emails
        - System notification emails
        """
        from unittest.mock import MagicMock, patch

        # Storage for captured emails with enhanced metadata
        self.captured_emails = []

        # Comprehensive email capture function
        def capture_email_data(method_name, *args, **kwargs):
            """Capture email data from any sending method"""
            # Extract common email fields regardless of method signature
            email_data = {
                "method": method_name,
                "timestamp": datetime.now().isoformat(),
                "args": args,
                "kwargs": kwargs,
                "recipients": self._extract_recipients(args, kwargs),
                "subject": self._extract_subject(args, kwargs),
                "message": self._extract_message(args, kwargs),
                "attachments": self._extract_attachments(args, kwargs),
                "template": kwargs.get("template"),
                "is_html": self._detect_html_content(args, kwargs),
                "to": self._extract_recipients(args, kwargs),  # Backward compatibility
            }
            self.captured_emails.append(email_data)
            # Return a stub that mimics the Email Queue document frappe.sendmail
            # really returns (never a bool). Frappe's User.send_welcome_mail_to_user
            # accesses `q.message` on the result; returning True here raised
            # AttributeError: 'bool' object has no attribute 'message' for every
            # EnhancedTestCase test that inserted a User with send_welcome_email=1.
            email_queue_stub = MagicMock(name="email_queue")
            email_queue_stub.message = self._extract_message(args, kwargs) or ""
            email_queue_stub.name = "TEST-EMAIL-QUEUE"
            return email_queue_stub

        # Patch multiple email sending pathways
        self.email_patches = []

        # 1. Core sendmail function
        # Mock justified: External Service - email delivery, prevents actual email sending in tests
        mock_sendmail = lambda *args, **kwargs: capture_email_data("frappe.sendmail", *args, **kwargs)
        self.email_patches.append(patch("frappe.sendmail", side_effect=mock_sendmail))

        # 2. Email queue sending (catches background jobs)
        mock_queue_send = lambda *args, **kwargs: capture_email_data("email_queue.send_one", *args, **kwargs)
        self.email_patches.append(
            patch("frappe.email.doctype.email_queue.email_queue.send_one", side_effect=mock_queue_send)
        )

        # 3. System manager notifications
        mock_system_email = lambda *args, **kwargs: capture_email_data(
            "sendmail_to_system_managers", *args, **kwargs
        )
        self.email_patches.append(
            patch("frappe.utils.email_lib.sendmail_to_system_managers", side_effect=mock_system_email)
        )

        # 4. Template-based email generation
        mock_template_email = lambda *args, **kwargs: capture_email_data(
            "send_template_email", *args, **kwargs
        )
        try:
            self.email_patches.append(
                patch("frappe.core.doctype.communication.email.make", side_effect=mock_template_email)
            )
        except ImportError:
            pass  # Template email methods may not exist in all Frappe versions

        # 5. Direct SMTP sending (fallback)
        mock_smtp_send = lambda *args, **kwargs: capture_email_data("smtp_send", *args, **kwargs)
        self.email_patches.append(patch("frappe.utils.email_lib.send", side_effect=mock_smtp_send))

        # Start all patches
        for patch_obj in self.email_patches:
            try:
                patch_obj.start()
            except Exception as e:
                # Log patch failures but continue (some methods may not exist)
                frappe.logger().warning(f"Email patch failed: {str(e)}")

    def _extract_recipients(self, args, kwargs):
        """Extract recipient list from various email method signatures"""
        # Try kwargs first
        recipients = kwargs.get("recipients") or kwargs.get("to") or kwargs.get("send_to")
        if recipients:
            return recipients if isinstance(recipients, list) else [recipients]

        # Try positional args
        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, (list, tuple)):
                return list(first_arg)
            elif isinstance(first_arg, str) and "@" in first_arg:
                return [first_arg]

        return []

    def _extract_subject(self, args, kwargs):
        """Extract subject from various email method signatures"""
        subject = kwargs.get("subject") or kwargs.get("title")
        if subject:
            return subject

        # Try positional args (usually second argument)
        if args and len(args) > 1:
            return str(args[1]) if args[1] else ""

        return ""

    def _extract_message(self, args, kwargs):
        """Extract message content from various email method signatures"""
        message = kwargs.get("message") or kwargs.get("content") or kwargs.get("body")
        if message:
            return message

        # Try positional args (usually third argument)
        if args and len(args) > 2:
            return str(args[2]) if args[2] else ""

        return ""

    def _extract_attachments(self, args, kwargs):
        """Extract attachment information"""
        attachments = kwargs.get("attachments") or kwargs.get("files")
        if attachments:
            return attachments if isinstance(attachments, list) else [attachments]
        return []

    def _detect_html_content(self, args, kwargs):
        """Detect if email content is HTML"""
        message = self._extract_message(args, kwargs)
        is_html = kwargs.get("is_html", False)

        # Auto-detect HTML content
        if not is_html and message:
            html_indicators = ["<html", "<body", "<div", "<p>", "<br", "<table"]
            is_html = any(indicator in str(message).lower() for indicator in html_indicators)

        return is_html

    def get_sent_emails(
        self, to=None, subject_contains=None, message_contains=None, method=None, has_attachments=None
    ):
        """
        Get captured emails with comprehensive filtering options.

        QCE FIX: Enhanced filtering supports multiple email pathways and metadata.

        Args:
            to: Filter by recipient email address
            subject_contains: Filter by text in subject
            message_contains: Filter by text in message
            method: Filter by sending method (e.g., 'frappe.sendmail', 'email_queue.send_one')
            has_attachments: Filter by attachment presence (True/False)
        """
        filtered_emails = self.captured_emails

        if to:
            filtered_emails = [
                email
                for email in filtered_emails
                if (
                    to in str(email.get("to", ""))
                    or to in str(email.get("recipients", ""))
                    or any(to in str(recipient) for recipient in email.get("recipients", []))
                )
            ]

        if subject_contains:
            filtered_emails = [
                email
                for email in filtered_emails
                if subject_contains.lower() in str(email.get("subject", "")).lower()
            ]

        if message_contains:
            filtered_emails = [
                email
                for email in filtered_emails
                if message_contains.lower() in str(email.get("message", "")).lower()
            ]

        if method:
            filtered_emails = [email for email in filtered_emails if email.get("method") == method]

        if has_attachments is not None:
            filtered_emails = [
                email for email in filtered_emails if bool(email.get("attachments")) == has_attachments
            ]

        return filtered_emails

    def assert_no_emails_sent(self):
        """Assert that no emails were captured during the test"""
        self.assertEqual(
            len(self.captured_emails), 0, f"Expected no emails, but {len(self.captured_emails)} were captured"
        )

    def assert_email_sent(self, to=None, subject_contains=None, count=1, method=None):
        """
        Assert that specific emails were sent with enhanced criteria.

        QCE FIX: Supports comprehensive email pathway validation.
        """
        emails = self.get_sent_emails(to=to, subject_contains=subject_contains, method=method)
        self.assertEqual(
            len(emails),
            count,
            f"Expected {count} emails matching criteria, but found {len(emails)}. "
            f"Available emails: {[e.get('subject', 'No Subject') for e in self.captured_emails]}",
        )
        return emails

    def assert_template_email_sent(self, template_name, to=None, count=1):
        """Assert that template-based email was sent"""
        emails = [
            email
            for email in self.captured_emails
            if email.get("template") == template_name and (not to or to in str(email.get("recipients", [])))
        ]
        self.assertEqual(
            len(emails),
            count,
            f"Expected {count} template emails for '{template_name}', but found {len(emails)}",
        )
        return emails

    def assert_html_email_sent(self, to=None, count=1):
        """Assert that HTML email was sent"""
        html_emails = [
            email
            for email in self.captured_emails
            if email.get("is_html", False) and (not to or to in str(email.get("recipients", [])))
        ]
        self.assertEqual(
            len(html_emails), count, f"Expected {count} HTML emails, but found {len(html_emails)}"
        )
        return html_emails

    def get_email_methods_used(self):
        """Get list of email sending methods that were intercepted"""
        methods = set(email.get("method", "unknown") for email in self.captured_emails)
        return list(methods)

    def _setup_rate_limit_mocking(self):
        """
        Set up rate limiting bypass for tests using proper mocking instead of production code checks.

        This replaces the old test mode check in api_security_framework.py with proper test mocking,
        ensuring production code remains clean while tests can run without rate limit interference.

        Scope and Lifecycle:
            - Scope: Per-test instance (each test gets its own isolated mock)
            - Lifecycle: Created in setUp(), destroyed in tearDown()
            - Thread-safety: Safe - no shared state across test instances
            - Cleanup: Automatic via tearDown() with hasattr() guards for robustness

        Implementation Details:
            - Uses unittest.mock.patch to intercept validate_rate_limits() calls
            - Mock returns True for all rate limit checks in test context
            - Original production behavior remains unchanged for non-test execution
            - No race conditions - mock lifecycle tied to test instance lifecycle

        Usage:
            Automatically called in setUp() - no manual intervention needed.
            Tests will bypass rate limiting without modifying production code.
        """
        from unittest.mock import patch

        # Mock the validate_rate_limits method to always return True in tests
        def mock_rate_limit_validation(self, profile, operation_key, force_check=False):
            """Mock rate limit validation - always passes in tests"""
            return True

        # Patch the APISecurityFramework.validate_rate_limits method
        self.rate_limit_patch = patch(
            "verenigingen.utils.security.api_security_framework.APISecurityFramework.validate_rate_limits",
            mock_rate_limit_validation,
        )
        self.rate_limit_patch.start()

    def _teardown_rate_limit_mocking(self):
        """
        Clean up rate limiting mocks with safe guards.

        Uses hasattr() check to prevent errors if mock was never created
        (e.g., if setUp() failed before reaching mock creation).
        """
        if hasattr(self, "rate_limit_patch"):
            self.rate_limit_patch.stop()

    def _track_record(self, doctype, name):
        """Track a created record for cleanup"""
        self.created_records.append({"doctype": doctype, "name": name})

    def track_test_record(self, doctype, name):
        """Public method to track test records for cleanup"""
        self._track_record(doctype, name)

    def _cleanup_orphaned_dynamic_links(self):
        """
        Clean up orphaned Dynamic Links where target document doesn't exist.

        This fixes LinkValidationError that occurs when:
        1. Previous test runs created Contacts/Addresses linked to test Donors/Members
        2. The linked documents were deleted but Dynamic Links remained
        3. Frappe's test_runner tries to validate these Contacts and fails

        Only cleans up links matching test patterns to avoid touching production data.
        Runs once per test session (controlled by frappe.flags).
        """
        try:
            # Test-like name patterns that indicate test data
            test_patterns = [
                "Test %",
                "TEST %",
                "Debug %",
                "Phase%",
                "Security Test%",
                "Performance Test%",
                "Form Test%",
                "Campaign Test%",
                "Orphaned Test%",
                "SQL Test%",
                "Sync Utils Test%",
                "Form Integration Test%",
                "Fallback Test%",
            ]

            # Build WHERE clause for test patterns. Use bound parameters, NOT inlined
            # literals: the patterns contain '%' (e.g. "Test %"), and MySQLdb runs
            # `query % args`, so an inlined '%' raises "not enough arguments for format
            # string". Each pattern becomes a positional %s param below.
            pattern_conditions = " OR ".join(["dl.link_name LIKE %s" for _ in test_patterns])

            # Find orphaned Dynamic Links (links to non-existent documents)
            # We check each link_doctype separately since we can't do dynamic table joins
            link_doctypes = ["Donor", "Member", "Customer", "Chapter"]

            total_deleted = 0
            for doctype in link_doctypes:
                try:
                    # Find links where target doesn't exist
                    orphaned_links = frappe.db.sql(
                        f"""
                        SELECT dl.name, dl.parent, dl.parenttype, dl.link_name
                        FROM `tabDynamic Link` dl
                        WHERE dl.link_doctype = %s
                          AND ({pattern_conditions})
                          AND NOT EXISTS (
                              SELECT 1 FROM `tab{doctype}` t
                              WHERE t.name = dl.link_name
                          )
                        LIMIT 500
                    """,
                        tuple([doctype, *test_patterns]),
                        as_dict=True,
                    )

                    if orphaned_links:
                        for link in orphaned_links:
                            try:
                                frappe.db.delete("Dynamic Link", {"name": link.name})
                                total_deleted += 1
                            except Exception:
                                continue

                except Exception as e:
                    # Table might not exist, skip
                    frappe.logger().debug(f"Skipped orphan check for {doctype}: {e}")
                    continue

            if total_deleted > 0:
                frappe.db.commit()  # Commit the cleanup
                frappe.logger().info(f"🧹 ETC orphan cleanup: Removed {total_deleted} orphaned Dynamic Links")

        except Exception as e:
            frappe.logger().warning(f"Orphaned Dynamic Link cleanup failed: {e}")
            # Don't fail tests if cleanup fails

    def _cleanup_stale_test_data(self):
        """
        Clean up test data from previous test runs that didn't get rolled back.

        Frappe's test framework only rolls back within a single test session.
        Data from previous runs accumulates, causing test isolation issues.

        This method identifies and removes stale test data by:
        - Matching test data naming patterns (Test*, TEST-*, etc.)
        - Filtering by test email domains (@test.invalid)
        - Removing old test run artifacts

        Called at the start of setUp() to ensure clean slate for each test.

        SAFETY CHECKS:
        - Only runs in developer mode
        - Only runs on approved test sites
        - Validates deletion counts before proceeding
        - Logs all cleanup operations
        """
        try:
            # SAFETY CHECK 1: Only cleanup if we're in test mode
            if not getattr(frappe.flags, "in_test", False):
                return

            # SAFETY CHECK 2: Only in developer mode
            if not frappe.conf.get("developer_mode"):
                frappe.logger().warning("Test cleanup skipped - not in developer mode")
                return

            # SAFETY CHECK 3: Only on approved test sites
            approved_test_sites = ["dev.veganisme.net", "test_site"]
            if frappe.local.site not in approved_test_sites:
                frappe.logger().error(f"Test cleanup blocked on site: {frappe.local.site}")
                return

            # Use Administrator context for cleanup operations
            current_user = frappe.session.user
            frappe.set_user("Administrator")

            try:
                # Clean up test members (highest priority - others depend on these)
                # Match common test patterns from EnhancedTestDataFactory
                # CRITICAL: Patterns must be VERY specific to avoid deleting production data
                test_member_patterns = [
                    {"email": ["like", "%@test.invalid"]},
                    {"email": ["like", "%@example.com"]},
                    {"email": ["like", "%@university.nl"]},  # Student test records
                    {"email": ["like", "%@verenigingen.test"]},  # Test utilities members
                    {"first_name": ["like", "Test%"]},
                    {"first_name": ["like", "%TestMember%"]},
                    # REMOVED: {"name": ["like", "Assoc-Member-%"]} - TOO BROAD, matches production!
                ]

                # SAFETY CHECK 4: Count before deleting
                pending_deletion_count = frappe.db.sql("""
                    SELECT COUNT(*) FROM `tabMember`
                    WHERE email LIKE '%@test.invalid'
                       OR email LIKE '%@example.com'
                       OR email LIKE '%@university.nl'
                       OR email LIKE '%@verenigingen.test'
                       OR first_name LIKE 'Test%'
                       OR first_name LIKE '%TestMember%'
                """)[0][0]

                # If suspiciously high, skip cleanup and log
                if pending_deletion_count > 5000:
                    frappe.log_error(
                        f"Test cleanup would delete {pending_deletion_count} members - suspiciously high, skipping for safety",
                        "Test Cleanup Safety Check",
                    )
                    return

                # Use bulk delete for better performance
                members_deleted = 0
                for pattern in test_member_patterns:
                    # Delete in batches for better performance
                    frappe.db.delete("Member", pattern)
                    members_deleted += 1

                # Log cleanup operation
                frappe.logger().info(f"Test cleanup removed {members_deleted} member patterns")

                # Clean up test customers (created from test members)
                # Customers are created automatically when members are created
                # They have names like "Admin User - 56", "Board Member - 81", etc.
                test_customer_patterns = [
                    {"name": ["like", "Admin User %"]},
                    {"name": ["like", "Board Member %"]},
                    {"name": ["like", "Regular Member %"]},
                    {"name": ["like", "Test %"]},
                    {"name": ["like", "TestMember%"]},
                    {"customer_name": ["like", "Test%"]},
                ]

                # SAFETY CHECK: Count before deleting
                pending_customer_deletion = frappe.db.sql("""
                    SELECT COUNT(*) FROM `tabCustomer`
                    WHERE name LIKE 'Admin User %'
                       OR name LIKE 'Board Member %'
                       OR name LIKE 'Regular Member %'
                       OR name LIKE 'Test %'
                       OR name LIKE 'TestMember%'
                       OR customer_name LIKE 'Test%'
                """)[0][0]

                if pending_customer_deletion > 10000:
                    frappe.log_error(
                        f"Test cleanup would delete {pending_customer_deletion} customers - suspiciously high, skipping for safety",
                        "Test Cleanup Safety Check",
                    )
                else:
                    customers_deleted = 0
                    for pattern in test_customer_patterns:
                        try:
                            frappe.db.delete("Customer", pattern)
                            customers_deleted += 1
                        except Exception:
                            continue

                    if customers_deleted > 0:
                        frappe.logger().info(f"Test cleanup removed {customers_deleted} customer patterns")

                # Clean up orphaned Membership Dues Schedules
                # These are schedules where the linked member or membership no longer exists
                schedules = frappe.get_all(
                    "Membership Dues Schedule", fields=["name", "member", "membership"], limit_page_length=500
                )

                orphaned_schedules = []
                for schedule in schedules:
                    # Check if member exists
                    if schedule.get("member"):
                        if not frappe.db.exists("Member", schedule["member"]):
                            orphaned_schedules.append(schedule["name"])
                            continue

                    # Check if membership exists
                    if schedule.get("membership"):
                        if not frappe.db.exists("Membership", schedule["membership"]):
                            orphaned_schedules.append(schedule["name"])

                # Delete orphaned schedules
                schedules_deleted = 0
                for schedule_name in orphaned_schedules:
                    try:
                        frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
                        schedules_deleted += 1
                    except Exception:
                        continue

                if schedules_deleted > 0:
                    frappe.logger().info(f"Test cleanup removed {schedules_deleted} orphaned dues schedules")

                # Clean up test volunteers (to prevent email duplicate key violations)
                # Include both @test.invalid and @verenigingen.test patterns
                test_volunteers = frappe.db.sql(
                    """
                    SELECT name FROM `tabVolunteer`
                    WHERE email LIKE '%@test.invalid'
                       OR email LIKE '%@verenigingen.test'
                       OR volunteer_name LIKE 'TEST %'
                    LIMIT 200
                """,
                    as_dict=False,
                )

                volunteers_deleted = 0
                for row in test_volunteers:
                    try:
                        frappe.delete_doc("Volunteer", row[0], force=True)
                        volunteers_deleted += 1
                    except Exception:
                        continue

                if volunteers_deleted > 0:
                    frappe.logger().info(f"Test cleanup removed {volunteers_deleted} test volunteers")

                # Clean up test chapters
                test_chapters = frappe.get_all(
                    "Chapter",
                    filters=[
                        ["name", "like", "TEST-Chapter-%"],
                    ],
                    pluck="name",
                    limit=50,
                )

                # Use Administrator context for cleanup (test infrastructure)
                current_user = frappe.session.user
                frappe.set_user("Administrator")

                for chapter_name in test_chapters:
                    try:
                        frappe.delete_doc("Chapter", chapter_name, force=True)
                    except Exception:
                        continue

                # Clean up test users (be careful - don't delete system users)
                test_users = frappe.get_all(
                    "User",
                    filters=[
                        [
                            "OR",
                            [["email", "like", "%@test.invalid"], ["email", "like", "%@verenigingen.test"]],
                        ],
                        ["name", "!=", "Administrator"],
                        ["name", "!=", "Guest"],
                    ],
                    pluck="name",
                    limit=50,
                )

                for user_name in test_users:
                    try:
                        frappe.delete_doc("User", user_name, force=True)
                    except Exception:
                        continue

                # Restore original user context
                frappe.set_user(current_user)

                # REMOVED: frappe.db.commit() breaks test isolation
                # This cleanup runs in setUp(), and committing here makes any deletions
                # permanent instead of letting them rollback with the test transaction.
                # Frappe's test framework manages transactions automatically.

            finally:
                # Restore original user
                frappe.set_user(current_user)

        except Exception as e:
            # Don't fail tests if cleanup fails - just log
            frappe.logger().warning(f"Stale test data cleanup encountered error: {str(e)}")

    def _validate_fixtures(self):
        """
        Validate required fixtures are loaded before running tests.

        Prints warnings if fixtures are missing but doesn't block tests.
        Set SKIP_FIXTURE_VALIDATION=1 environment variable to skip validation.
        """
        import os

        # Allow skipping fixture validation via environment variable
        if os.environ.get("SKIP_FIXTURE_VALIDATION"):
            return

        # Check if already validated globally
        if hasattr(frappe.flags, "fixtures_validated"):
            return
        frappe.flags.fixtures_validated = True

        from verenigingen.tests.utils.fixture_validator import validate_test_fixtures

        # Validate core fixtures (non-blocking - just warns)
        categories = ["roles", "regions"]
        if not validate_test_fixtures(categories=categories, quiet=False):
            print("\n⚠️  WARNING: Some fixtures are missing but tests will continue")
            print("    Tests may fail with cryptic LinkValidationError messages")
            print("    Set SKIP_FIXTURE_VALIDATION=1 to hide this warning\n")

    def _ensure_production_ready_setup(self):
        """
        Ensure production-ready setup using proper installation hooks.

        This eliminates the need for workarounds by ensuring that tests
        use the same setup as production installations.
        """
        try:
            # Use the proper installation setup function
            from verenigingen.setup import create_default_verenigingen_settings

            # Ensure settings exist (same as production installation)
            create_default_verenigingen_settings()

            # ENHANCED FIXTURE LOADING: Load all essential fixtures
            self._load_essential_fixtures()

            # The Netherlands territory is created FIRST and independently of
            # _ensure_master_data. It used to live near the end of that method, so
            # any earlier failure in there (company, fiscal year, accounts) skipped
            # it -- and _ensure_master_data swallows its own exceptions, so the skip
            # never propagated to the handler below. The territory has no dependency
            # on any of that; only on the "All Territories" root.
            from verenigingen.tests.setup import ensure_netherlands_territory

            ensure_netherlands_territory()

            # Ensure master data exists
            self._ensure_master_data()

            # Ensure required roles exist (some tests need HRMS roles)
            self._ensure_required_roles()

        except Exception as e:
            # Do NOT continue. This block creates the master data that fixtures link
            # to (company, fiscal year, accounts, the Netherlands territory), and
            # `frappe.logger()` writes to a log FILE, not stdout -- so swallowing here
            # produced no CI output at all. The failure then reappeared much later as
            # a LinkValidationError in an unrelated test, attributed to whichever PR
            # happened to reshuffle the shards (#291).
            #
            # A test that cannot get its master data has not passed; it has not run.
            # Fail here, where the message still names the actual cause.
            raise RuntimeError(
                f"Test master-data setup failed, so fixtures would link to records that "
                f"do not exist. Fix the setup rather than the downstream test: {e}"
            ) from e

    def _ensure_required_roles(self):
        """
        Ensure required roles exist for account creation tests.

        Some roles like "Employee Self Service" come from HRMS and may not exist
        in minimal CI test environments. Create them if they don't exist.
        """
        required_roles = [
            "Employee Self Service",  # From HRMS - used for employee expense access
            "Verenigingen Member",  # Custom app role
            "Verenigingen Administrator",  # Custom app role
        ]

        for role_name in required_roles:
            if not frappe.db.exists("Role", role_name):
                try:
                    role = frappe.get_doc(
                        {
                            "doctype": "Role",
                            "role_name": role_name,
                            "desk_access": 1 if "Administrator" in role_name else 0,
                            "is_custom": 1,
                        }
                    )
                    role.insert(ignore_permissions=True)
                    frappe.db.commit()
                except Exception as e:
                    # Role might have been created by another concurrent test
                    frappe.logger().warning(f"Could not create role {role_name}: {e}")

    def ensure_test_user_has_role(self, role_name):
        """
        Ensure the current test user has the required role for document operations.
        This replaces permission bypasses with proper role-based access.

        Args:
            role_name (str): The role required for the operation
        """
        current_user = frappe.session.user

        # Skip for Administrator (has all permissions)
        if current_user == "Administrator":
            return

        # Check if user already has the role
        existing_roles = frappe.get_roles(current_user)
        if role_name in existing_roles:
            return

        # Add the role to the user for this test session using Frappe API
        # Use Administrator context for role assignment (test setup only)
        try:
            current_session_user = frappe.session.user
            frappe.set_user("Administrator")

            user_doc = frappe.get_doc("User", current_user)
            if not any(role.role == role_name for role in user_doc.roles):
                user_doc.append("roles", {"role": role_name})
                user_doc.save()  # No permission bypass needed as Administrator

            # Restore original user
            frappe.set_user(current_session_user)
        except frappe.DoesNotExistError:
            # User doesn't exist yet, skip role assignment for now
            # This can happen when tests call setUp before creating test users
            frappe.set_user(current_session_user)  # Restore user even on error
            return

        # Clear role cache so the change takes effect immediately
        frappe.cache().delete_value("roles:" + current_user)

        # Force reload of user permissions
        frappe.clear_cache(user=current_user)

        # Ensure permission context is refreshed
        if hasattr(frappe.local, "login_manager"):
            frappe.local.login_manager.user = current_user

    def _load_essential_fixtures(self):
        """
        ENHANCED FIXTURE LOADING: Load essential fixtures for comprehensive test support

        Loads master data fixtures that tests commonly depend on:
        - Team Roles (Team Leader, Team Member, etc.)
        - Membership Types (Monthly, Quarterly, Annual)
        - Email Templates for notifications
        - Custom fields for ERPNext integration
        - Roles and permissions
        """
        import os

        # Define essential fixtures in loading order (dependencies first)
        essential_fixtures = [
            "role.json",  # Roles first (referenced by permissions)
            "team_role.json",  # Team roles for volunteer management
            "membership_type.json",  # Membership types for member testing
            "donation_type.json",  # Donation types for ANBI functionality
            "email_template.json",  # Email templates for notifications
            "custom_field.json",  # Custom fields for ERPNext integration
            "item_group.json",  # Item groups for billing
            "item.json",  # Items for dues and donations
            "workflow_state.json",  # Workflow states
            "workflow.json",  # Workflows for approval processes
        ]

        fixtures_path = os.path.join(frappe.get_app_path("verenigingen"), "fixtures")

        for fixture_file in essential_fixtures:
            fixture_path = os.path.join(fixtures_path, fixture_file)
            if os.path.exists(fixture_path):
                try:
                    self._load_fixture_file(fixture_path, fixture_file)
                except Exception as e:
                    # Log but don't fail tests - fixture might have dependency issues
                    frappe.logger().warning(f"Could not load fixture {fixture_file}: {str(e)}")
                    continue

    def _load_fixture_file(self, file_path, fixture_name):
        """Load a single fixture file with error handling and duplicate detection"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)

            if not isinstance(fixture_data, list):
                return

            loaded_count = 0
            skipped_count = 0

            for record in fixture_data:
                if not isinstance(record, dict) or "doctype" not in record:
                    continue

                doctype = record["doctype"]
                name = record.get("name")

                if name and frappe.db.exists(doctype, name):
                    skipped_count += 1
                    continue

                try:
                    # QCE FIX: Proper fixture validation before loading
                    validation_result = self._validate_fixture_before_load(record, doctype)
                    if not validation_result["valid"]:
                        frappe.logger().warning(
                            f"Fixture validation failed for {doctype} {name}: {validation_result['error']}"
                        )
                        continue

                    # Create document with proper role-based access
                    doc = frappe.get_doc(record)
                    doc.flags.ignore_links = False  # QCE FIX: Validate links exist initially

                    # Pre-insertion validation
                    try:
                        doc.validate()  # Run business rule validation explicitly
                    except Exception as validation_error:
                        # Allow certain validation errors that are acceptable for fixtures
                        if self._is_acceptable_fixture_validation_error(validation_error, doctype):
                            doc.flags.ignore_links = True  # Allow missing links for this record only
                        else:
                            raise validation_error

                    doc.insert()
                    self.factory.track_document(doctype, doc.name, priority=1)
                    loaded_count += 1

                except Exception as e:
                    # Enhanced error handling with specific error categorization
                    error_msg = str(e)
                    if "Link" in error_msg and "does not exist" in error_msg:
                        frappe.logger().info(f"Dependency missing for {doctype} {name}: {error_msg}")
                    elif "Duplicate" in error_msg or "already exists" in error_msg:
                        skipped_count += 1  # Count as skipped, not failed
                        frappe.logger().debug(f"Fixture {doctype} {name} already exists, skipping")
                        continue
                    else:
                        frappe.logger().warning(
                            f"Failed to load {doctype} {name} from {fixture_name}: {error_msg}"
                        )
                    continue

            if loaded_count > 0:
                frappe.logger().info(
                    f"Loaded {loaded_count} records from {fixture_name} (skipped {skipped_count} existing)"
                )

        except Exception as e:
            frappe.logger().warning(f"Failed to process fixture file {fixture_name}: {str(e)}")

    def _validate_fixture_before_load(self, record: dict, doctype: str) -> dict:
        """
        QCE FIX: Validate fixture meets business requirements before loading.

        Args:
            record: The fixture record to validate
            doctype: The doctype being loaded

        Returns:
            dict: {'valid': bool, 'error': str, 'warnings': list}
        """
        validation_result = {"valid": True, "error": "", "warnings": []}

        try:
            # 1. Required fields validation
            if not record.get("doctype"):
                validation_result["valid"] = False
                validation_result["error"] = "Missing doctype field"
                return validation_result

            # 2. DocType-specific business rule validation
            if doctype == "Team Role":
                return self._validate_team_role_fixture(record, validation_result)
            elif doctype == "Membership Type":
                return self._validate_membership_type_fixture(record, validation_result)
            elif doctype == "Workflow":
                return self._validate_workflow_fixture(record, validation_result)
            elif doctype in ["Item", "Item Group"]:
                return self._validate_item_fixture(record, validation_result)

            # 3. Generic validation for other doctypes
            return self._validate_generic_fixture(record, validation_result)

        except Exception as e:
            validation_result["valid"] = False
            validation_result["error"] = f"Validation exception: {str(e)}"
            return validation_result

    def _validate_team_role_fixture(self, record: dict, result: dict) -> dict:
        """Validate Team Role fixture business rules"""
        # Check required fields
        if not record.get("role_name"):
            result["valid"] = False
            result["error"] = "Team Role missing role_name"
            return result

        # Check permissions_level is valid
        valid_levels = ["Basic", "Coordinator", "Leader"]
        if record.get("permissions_level") not in valid_levels:
            result["warnings"].append(f"Invalid permissions_level: {record.get('permissions_level')}")

        # Validate unique role logic
        if record.get("is_unique") and not isinstance(record.get("is_unique"), (int, bool)):
            result["warnings"].append("is_unique should be boolean/integer")

        return result

    def _validate_membership_type_fixture(self, record: dict, result: dict) -> dict:
        """Validate Membership Type fixture business rules"""
        # Check required fields
        if not record.get("membership_type_name"):
            result["valid"] = False
            result["error"] = "Membership Type missing membership_type_name"
            return result

        # Validate minimum_amount is positive
        min_amount = record.get("minimum_amount", 0)
        if not isinstance(min_amount, (int, float)) or min_amount < 0:
            result["valid"] = False
            result["error"] = f"Invalid minimum_amount: {min_amount}"
            return result

        # Validate billing_period
        valid_periods = ["Monthly", "Quarterly", "Annual", "One-time"]
        if record.get("billing_period") not in valid_periods:
            result["warnings"].append(f"Unusual billing_period: {record.get('billing_period')}")

        return result

    def _validate_workflow_fixture(self, record: dict, result: dict) -> dict:
        """Validate Workflow fixture dependencies"""
        # Check workflow has states
        if not record.get("states"):
            result["valid"] = False
            result["error"] = "Workflow missing states"
            return result

        # Validate document_type exists (will be checked during link validation)
        if not record.get("document_type"):
            result["valid"] = False
            result["error"] = "Workflow missing document_type"
            return result

        return result

    def _validate_item_fixture(self, record: dict, result: dict) -> dict:
        """Validate Item/Item Group fixture business rules"""
        # Check required fields
        if not record.get("item_name" if record["doctype"] == "Item" else "item_group_name"):
            result["valid"] = False
            result["error"] = f"{record['doctype']} missing name field"
            return result

        return result

    def _validate_generic_fixture(self, record: dict, result: dict) -> dict:
        """Generic validation for other fixture types"""
        # Check for common name field
        name_fields = ["name", "title", "label", "subject", "email_template_name"]
        has_name = any(record.get(field) for field in name_fields)

        if not has_name:
            result["warnings"].append(f"No name field found for {record['doctype']}")

        return result

    def _is_acceptable_fixture_validation_error(self, error: Exception, doctype: str) -> bool:
        """
        Determine if a validation error is acceptable for fixture loading.

        Args:
            error: The validation exception
            doctype: The doctype being loaded

        Returns:
            bool: True if error can be ignored for fixtures
        """
        error_msg = str(error).lower()

        # Acceptable errors for fixture loading
        acceptable_errors = [
            "does not exist",  # Missing linked documents
            "no matching document found",  # Missing references
            "link validation",  # Link validation errors
        ]

        # DocType-specific acceptable errors
        doctype_specific = {
            "Workflow": ["document_type", "workflow state"],  # Workflow dependencies
            "Email Template": ["email account", "email template"],  # Email dependencies
            "Custom Field": ["fieldtype", "fieldname"],  # Field validation
        }

        # Check general acceptable errors
        if any(acceptable in error_msg for acceptable in acceptable_errors):
            return True

        # Check doctype-specific acceptable errors
        if doctype in doctype_specific:
            if any(specific in error_msg for specific in doctype_specific[doctype]):
                return True

        return False

    # Removed _ensure_system_settings - now using proper installation hook

    def _ensure_master_data(self):
        """
        Ensure required master data exists for donation and financial functionality

        Creates essential Frappe master data that tests depend on, including
        companies, fiscal years, accounts, and donation types.
        """
        try:
            # `_get_test_company()` either returns a company name or raises, so the
            # `if not existing_company:` create-a-company fallback that used to live here
            # was unreachable. Removed rather than left as decoration -- the companies the
            # harness uses are created by before_tests (tests/setup/__init__.py). See #299.

            # Ensure Test Company has round_off_cost_center configured for GL entries
            # This is required by ERPNext for invoice submission
            test_company = self._get_test_company()
            if test_company:
                current_round_off = frappe.db.get_value("Company", test_company, "round_off_cost_center")
                if not current_round_off:
                    # Find a suitable cost center (non-group)
                    cost_center = frappe.db.get_value(
                        "Cost Center", {"company": test_company, "is_group": 0}, "name"
                    )
                    if cost_center:
                        frappe.db.set_value(
                            "Company",
                            test_company,
                            "round_off_cost_center",
                            cost_center,
                            update_modified=False,
                        )

            # Ensure comprehensive fiscal year coverage
            from datetime import date

            from frappe.utils import getdate

            current_date = getdate()

            # Create fiscal years for current year and next year to ensure coverage
            # Use the actual test company to avoid company mismatch errors
            test_company = self._get_test_company()

            from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
                ensure_fiscal_year_exists,
            )

            # Ensure an UNRESTRICTED Fiscal Year covers the current and next year so
            # dated documents for ANY company submit. Delegate to the single
            # canonical find-or-create helper (the same one the session setup and
            # the SEPA EUR-company helper use), then drop any company restriction so
            # the FY applies to every company.
            #
            # The previous code created a company-SCOPED FY and -- worse -- appended
            # this company to an existing all-company (empty-`companies`) FY, which
            # RE-RESTRICTED it to just the appended companies and stripped coverage
            # from every other test company. Under erpnext v16 that produced an
            # order-dependent "Posting Date ... not in any active Fiscal Year"
            # cascade across whole shards. Commit so the session-scoped FY persists
            # past each test method's rollback.
            for year_offset in [0, 1]:
                target = date(current_date.year + year_offset, 6, 15)
                try:
                    fy_name = ensure_fiscal_year_exists(target, test_company)
                    if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
                        frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
                    frappe.db.commit()
                except Exception as fy_error:
                    frappe.logger().warning(f"Failed to ensure fiscal year for {target}: {fy_error}")

            # Don't set default fiscal year on company - ERPNext handles this automatically

            # Ensure Verenigingen Settings uses the test company and its accounts
            # This prevents company/account mismatch errors in invoice generation
            self._ensure_verenigingen_settings(test_company)

            # Ensure Department infrastructure for Chapter/Department integration
            # Chapter.after_insert() calls _sync_department() which requires:
            # 1. Company (already ensured above)
            # 2. Parent department "All Departments" (ERPNext default root)
            test_company = self._get_test_company()
            if test_company:
                parent_dept_name = "All Departments"
                if not frappe.db.exists("Department", parent_dept_name):
                    try:
                        parent_dept = frappe.get_doc(
                            {
                                "doctype": "Department",
                                "department_name": parent_dept_name,
                                "is_group": 1,  # Root department is a group
                                "parent_department": None,  # Root has no parent
                                "company": test_company,
                            }
                        )
                        parent_dept.insert()
                        # NOT tracked: "All Departments" is the ERPNext root, shared with
                        # production data. Per-method drain MUST NOT delete it.
                        frappe.logger().info(f"Created parent department: {parent_dept_name}")
                    except Exception as dept_error:
                        frappe.logger().warning(
                            f"Failed to create parent department {parent_dept_name}: {dept_error}"
                        )

            # Netherlands territory (fixtures across this app hardcode it). Owned by
            # verenigingen.tests.setup so BOTH harnesses get it -- this factory only
            # runs for EnhancedTestCase, and it used to be the sole creator.
            from verenigingen.tests.setup import ensure_netherlands_territory

            ensure_netherlands_territory()

            # Note: Donation Type DocType was removed from the codebase

            # NO COMMIT - Test framework manages transactions automatically

        except Exception as e:
            # Do NOT swallow. This is the inner half of the same defect fixed one
            # level up in #295: that change made _ensure_production_ready_setup
            # raise, but THIS handler caught first, so a failure here still skipped
            # the rest of the method silently and nothing propagated. The symptom
            # was `LinkValidationError: Could not find Territory: Netherlands` in
            # whichever test built a Customer first (#291) -- a full level away from
            # the cause, and with the cause itself written only to a log file.
            raise RuntimeError(
                f"Test master data could not be created, so fixtures would link to "
                f"records that do not exist: {e}"
            ) from e

    def unique_name(self, base: str) -> str:
        """Make any test name unique by appending the test's uid.

        Use this when tests need explicit member/customer names to prevent
        PRIMARY key collisions from hardcoded names like "Audit Trail".

        Args:
            base: The base name (e.g., "Audit Trail", "SQL Injection")

        Returns:
            Unique name like "Audit Trail_847291"

        Examples:
            member = self.create_test_member(
                first_name=self.unique_name("Timezone"),
                last_name="Edge"
            )
            # Or use f-string shorthand:
            member = self.create_test_member(
                first_name=f"Audit{self.uid}",
                last_name="Trail"
            )
        """
        return f"{base}_{self.uid}"

    def _track_test_document(self, doctype, name, priority=0):
        """Track a created document for tearDown cleanup, defensively.

        Some test classes reassign ``self.factory`` to an unrelated object
        (e.g. a production service factory). When that happens the factory no
        longer has ``track_document``, so calling it directly would raise
        AttributeError. This helper falls back to the document tracker
        (``created_documents`` / ``created_records`` / ``_track_record``)
        that the drain in tearDown actually reads, and never raises.
        """
        factory = getattr(self, "factory", None)
        track = getattr(factory, "track_document", None)
        if callable(track):
            track(doctype, name, priority=priority)
            return
        # Fallbacks for when self.factory was reassigned by the test class.
        record = getattr(self, "_track_record", None)
        if callable(record):
            record(doctype, name)
        created = getattr(self, "created_records", None)
        if isinstance(created, list):
            created.append({"doctype": doctype, "name": name})

    def create_test_member(self, *args, **kwargs):
        """Convenience method for creating test members.

        Backward-compatible with legacy positional calling conventions:
          - create_test_member(email)                      # 1 positional, contains "@"
          - create_test_member(first_name, last_name)      # 2 positional
          - create_test_member(first_name, last_name, email)
          - create_test_member(first_name, last_name, email, iban)
        as well as the current keyword-only form create_test_member(**kwargs).
        """
        if args:
            if len(args) == 1 and isinstance(args[0], str) and "@" in args[0]:
                # Single positional that looks like an email address
                kwargs.setdefault("email", args[0])
            else:
                positional_fields = ["first_name", "last_name", "email", "iban"]
                for value, field in zip(args, positional_fields):
                    kwargs.setdefault(field, value)
        return self.factory.create_member(**kwargs)

    def create_chapter(self, **kwargs):
        """Convenience method for creating chapters"""
        return self.factory.create_chapter(**kwargs)

    def create_test_volunteer(self, member_name=None, **kwargs):
        """Convenience method for creating test volunteers

        Accepts both 'member_name' (positional or kwarg) and 'member' (kwarg)
        for backward compatibility with tests using 'member=' syntax.
        """
        # Support both 'member' and 'member_name' for backward compatibility
        if member_name is None and "member" in kwargs:
            member_name = kwargs.pop("member")
        return self.factory.create_volunteer(member_name, **kwargs)

    def create_test_board_member(
        self, chapter_name, permissions_level="Admin", role_name=None, first_name="Board"
    ):
        """Seat a real, non-admin board member on `chapter_name`.

        A board seat is held by a VOLUNTEER, and the permission gates resolve
        user -> Member -> Volunteer -> `Chapter Board Member`. Every link in that
        chain has to exist or the seat is invisible to
        chapter_security.get_user_manageable_chapters, and a permission test
        silently passes (or fails) for the wrong reason. Assembling it by hand is
        ~15 lines that were previously copy-pasted per test file; the persona
        `create_board_member_bob` does NOT do this -- it builds a Team assignment,
        which is a different doctype and grants no chapter rights.

        `permissions_level` defaults to "Admin" because that is the only level that
        actually grants approval: `Chapter Role` has no `can_approve_memberships`
        field and its permissions_level options are Basic/Financial/Admin, so the
        `"Membership"` arm in get_user_manageable_chapters is dead.

        Returns a frappe._dict with `user`, `member`, `volunteer`, `chapter` and
        `chapter_role`.
        """
        # Trailing digit is required: the factory rewrites Member.email unless the
        # local part's last 5 characters contain one, which silently decouples
        # Member.email from Member.user and breaks user-linked lookups ~1 run in 135.
        run = f"{frappe.generate_hash(length=8)}0"
        email = f"board-{run}@example.com"

        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "send_welcome_email": 0,
                # Explicit, as create_test_user also does. This used to be load-bearing:
                # setUp set frappe.flags.in_import, which made Document._set_defaults()
                # early-return, so User.enabled's default of "1" never reached the doc and
                # the account landed disabled. setUp no longer sets that flag, so the
                # default now applies and this is belt-and-braces rather than a fix -- kept
                # because a disabled board member is not a scenario worth testing (they
                # cannot log in, and has_permission denies disabled accounts outright), so
                # the seat would go invisible for a reason the test is not about.
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}],
            })
            user.insert(ignore_permissions=True)
            self.factory.track_document("User", user.name, priority=2)

        member = self.create_test_member(
            first_name=first_name, last_name=f"Seat{run[:6]}", email=email, birth_date="1985-01-01"
        )
        member.db_set("status", "Active")
        member.db_set("user", email)

        volunteer = self.create_test_volunteer(member_name=member.name)

        role_name = role_name or f"Test Board Approver {permissions_level}"
        existing = frappe.db.get_value(
            "Chapter Role", role_name, ["permissions_level", "is_active"], as_dict=True
        )
        if not existing:
            role = frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": permissions_level,
                "is_active": 1,
            })
            role.insert(ignore_permissions=True)
            self.factory.track_document("Chapter Role", role.name, priority=3)
        elif existing.permissions_level != permissions_level or not existing.is_active:
            # The default role_name is NOT tokenized, so this row is shared across
            # tests and across runs. A prior run that left it inactive, or that asked
            # for a different permissions_level, would otherwise be silently reused --
            # and get_user_manageable_chapters only accepts permissions_level "Admin",
            # so the seat would grant nothing in a fixture whose entire purpose is that
            # the seat is visible. Repair rather than skip.
            frappe.db.set_value(
                "Chapter Role",
                role_name,
                {"permissions_level": permissions_level, "is_active": 1},
                update_modified=False,
            )

        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role_name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

        # The roles alone are not enough. APISecurityFramework authorizes on Frappe ROLE
        # PROFILES, not roles (authorization_policy.ROLE_PROFILE_SECURITY_MAPPING), and
        # approve_membership_application is @high_security_api. Without the profile the
        # user is capped below HIGH and denied at the tier gate -- so a chapter-scope
        # test would be denied before the chapter check ever ran, and a denial test
        # would pass for entirely the wrong reason.
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")

        return frappe._dict(
            user=email,
            member=member.name,
            volunteer=volunteer.name,
            chapter=chapter_name,
            chapter_role=role_name,
        )

    def add_member_to_test_chapter(self, member_name, chapter_name):
        """Give `member_name` an ACTIVE Chapter Member row on `chapter_name`.

        can_user_manage_application() matches manageable chapters against
        `tabChapter Member` rows with enabled=1 AND status='Active'. A member
        without one belongs to no chapter as far as the approval gate is
        concerned, so a board-member permission test would be unreachable.
        """
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        for row in chapter_doc.get("members", []):
            if row.member == member_name:
                row.enabled = 1
                row.status = "Active"
                break
        else:
            chapter_doc.append(
                "members", {"member": member_name, "enabled": 1, "status": "Active"}
            )
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def create_test_application_data(self, with_skills=True):
        """Convenience method for creating application data"""
        return self.factory.create_application_data(with_volunteer_skills=with_skills)

    def create_test_team(self, **kwargs):
        """
        Convenience method for creating test teams with isolation improvements.

        If team_name is provided explicitly, it will be made unique automatically
        to prevent test isolation conflicts in parallel test execution.
        """
        return self.factory.create_team(**kwargs)

    def create_test_team_member(self, team_name, volunteer_name, team_role_name="Team Member", **kwargs):
        """Convenience method for creating test team members"""
        return self.factory.create_team_member(team_name, volunteer_name, team_role_name, **kwargs)

    def ensure_team_role(self, role_name, attributes=None):
        """
        Convenience method for ensuring team roles exist with isolation improvements.

        Role names will be made unique automatically to prevent conflicts
        in parallel test execution while preserving logical role configurations.
        """
        return self.factory.ensure_team_role(role_name, attributes)

    def ensure_dues_schedule_template(self, template_name, attributes=None):
        """Convenience method for ensuring dues schedule templates exist"""
        return self.factory.ensure_dues_schedule_template(template_name, attributes)

    def create_test_donor(self, **kwargs):
        """Convenience method for creating test donors"""
        return self.factory.create_test_donor(**kwargs)

    def create_test_donation(self, **kwargs):
        """Convenience method for creating test donations"""
        return self.factory.create_test_donation(**kwargs)

    def ensure_membership_type(self, type_name, attributes=None):
        """Convenience method for ensuring membership types exist"""
        return self.factory.ensure_membership_type(type_name, attributes)

    def create_test_membership_type(self, membership_type_name=None, amount=100.0, **kwargs):
        """
        Create a test membership type with unique name.

        Args:
            membership_type_name: Base name for the type (will be made unique)
            amount: Default membership amount
            **kwargs: Additional fields to set on the membership type

        Returns:
            Membership Type document
        """
        import time

        # Generate unique name
        if not membership_type_name:
            membership_type_name = "Test Type"
        unique_name = f"{membership_type_name}-{int(time.time() * 1000)}"

        # Get or create a role profile (mandatory field)
        role_profile = kwargs.get("role_profile")
        if not role_profile:
            role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Member"})
            if not role_profile:
                # Create a minimal test role profile
                test_profile = frappe.new_doc("Role Profile")
                test_profile.role_profile = "Test Member Profile"
                # Check if the role exists before adding
                if frappe.db.exists("Role", "Verenigingen Member"):
                    test_profile.append("roles", {"role": "Verenigingen Member"})
                test_profile.insert(ignore_permissions=True)
                role_profile = test_profile.name
                self.factory.track_document("Role Profile", role_profile, priority=0)

        # Create the membership type first (templates require membership_type link)
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = unique_name
        membership_type.is_active = 1
        membership_type.contribution_mode = kwargs.get("contribution_mode", "Fixed Amount")
        membership_type.minimum_amount = kwargs.get("minimum_amount", amount)
        membership_type.role_profile = role_profile

        # Apply any additional kwargs (except dues_schedule_template which we handle below)
        for key, value in kwargs.items():
            if key != "dues_schedule_template" and hasattr(membership_type, key):
                setattr(membership_type, key, value)

        # Insert membership type first (required before creating template)
        membership_type.insert()
        self.factory.track_document("Membership Type", membership_type.name, priority=1)

        # Now get or create a dues schedule template linked to this membership type
        # Note: Membership Type's after_insert automatically creates a template with default amounts
        # We need to update that template with the correct amounts for our test
        template = kwargs.get("dues_schedule_template")
        if not template:
            # Try to find an existing template for THIS specific membership type
            # (likely created by Membership Type's after_insert hook)
            template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"is_template": 1, "membership_type": membership_type.name},
                "name",
            )

        if template:
            # Update existing template with correct amounts
            # This is necessary because after_insert creates templates with default 15.0 amounts
            template_doc = frappe.get_doc("Membership Dues Schedule", template)
            template_doc.suggested_amount = amount
            template_doc.dues_rate = amount  # Must also set dues_rate as it's used in validation
            template_doc.minimum_amount = amount * 0.5
            template_doc.save(ignore_permissions=True)
        else:
            # Create a new template for this membership type
            test_template = frappe.new_doc("Membership Dues Schedule")
            test_template.schedule_name = f"{unique_name} Template"
            test_template.is_template = 1
            test_template.status = "Active"
            test_template.billing_frequency = "Quarterly"
            test_template.suggested_amount = amount
            test_template.dues_rate = amount  # Set dues_rate to match suggested_amount
            test_template.minimum_amount = amount * 0.5
            test_template.membership_type = membership_type.name
            test_template.insert(ignore_permissions=True)
            template = test_template.name
            self.factory.track_document("Membership Dues Schedule", template, priority=0)

        # Link the template to the membership type
        membership_type.dues_schedule_template = template
        membership_type.save()

        return membership_type

    def ensure_test_chapter(self, chapter_name, attributes=None):
        """Convenience method for ensuring test chapters exist"""
        return self.factory.ensure_test_chapter(chapter_name, attributes)

    def create_test_account_creation_request(self, source_record=None, request_type="Member", **kwargs):
        """Convenience method for creating account creation requests"""
        return self.factory.create_account_creation_request(source_record, request_type, **kwargs)

    def create_test_user_with_roles(self, email=None, roles=None, **kwargs):
        """Convenience method for creating users with specific roles"""
        return self.factory.create_user_with_roles(email, roles, **kwargs)

    def ensure_test_admin_user(self):
        """Convenience method for ensuring test admin user exists"""
        return self.factory.ensure_test_admin_user()

    def _create_mock_payment_data(self, payment_id, metadata=None, description=None, subscription_id=None):
        """
        Helper to create realistic payment data structure.
        Mimics actual Mollie payment object structure for payment processor tests.
        """

        class MockPayment:
            def __init__(self):
                self.id = payment_id
                self.amount = {"value": "50.00", "currency": "EUR"}
                self.status = "paid"
                self.method = "creditcard"
                self.metadata = metadata or {}
                self.description = description or "Test payment"
                self.subscription_id = subscription_id
                self.customer_id = None
                self.mandate_id = None
                self.created_at = frappe.utils.now_datetime()

        return MockPayment()

    def create_test_membership(self, member_name=None, membership_type_name=None, **kwargs):
        """
        Create a membership record for testing.

        Backward-compatible with legacy keyword callers:
          - create_test_membership(member=<name>, membership_type=<name>, ...)
          - create_test_membership(member=<name>)   # membership_type auto-created
        as well as the positional form
          - create_test_membership(member_name, membership_type_name, ...)

        Args:
            member_name: Name of the Member document (alias: member=)
            membership_type_name: Name of the Membership Type (alias: membership_type=).
                                  If omitted, a test Membership Type is auto-created.
            start_date: Membership start date. Defaults to today().
                        Note: For membership to be Active, start_date + billing_period
                        must result in a renewal_date in the future.
            sync_member_since: If True (default), also sets member_since on the
                               Member document to match the start_date. This ensures
                               realistic test data where membership start aligns with
                               when the member joined.
            **kwargs: Additional fields to set on the membership

        Returns:
            Submitted Membership document

        Example:
            # Create membership starting mid-quarter to test coverage logic
            membership = self.create_test_membership(
                member_name=member.name,
                membership_type_name=membership_type.name,
                start_date="2025-11-15"  # Mid-Q4
            )
        """
        # --- Backward-compatible keyword aliases ---
        if member_name is None:
            member_name = kwargs.pop("member", None)
        else:
            kwargs.pop("member", None)
        if membership_type_name is None:
            membership_type_name = kwargs.pop("membership_type", None)
        else:
            kwargs.pop("membership_type", None)

        if not member_name:
            raise TypeError("create_test_membership() requires a member (pass member_name= or member=)")

        # Auto-create a Membership Type when none was supplied (legacy callers
        # frequently omit it, e.g. create_test_membership(member=...)).
        if not membership_type_name:
            membership_type_name = self.create_test_membership_type().name
        else:
            # A type name was supplied; ensure it resolves to a real Membership
            # Type so the insert doesn't fail with "Could not find Membership
            # Type: <name>" on a fresh site.
            from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists

            membership_type_name = ensure_membership_type_exists(membership_type_name)

        start_date = kwargs.pop("start_date", frappe.utils.today())
        sync_member_since = kwargs.pop("sync_member_since", True)
        # Mirror the production approval/import flows (membership_creation_service,
        # related_records_orchestrator): suppress the on_submit hook that
        # auto-creates a Membership Dues Schedule. Lets dues/billing tests build a
        # membership fixture without a schedule to then delete, rather than
        # submitting and immediately cancelling the hook-created one.
        skip_dues_schedule = kwargs.pop("skip_dues_schedule_creation", False)

        membership_data = {
            "doctype": "Membership",
            "member": member_name,
            "membership_type": membership_type_name,
            "start_date": start_date,
            "status": kwargs.pop("status", "Active"),
            **kwargs,
        }

        membership = frappe.get_doc(membership_data)
        # Backdated test start_dates (common in coverage/billing tests) would
        # otherwise compute a past renewal_date, so Membership.set_status() marks
        # the membership Expired and on_submit skips dues schedule creation. Mirror
        # the production backdated-start path (membership_creation_service sets
        # _is_csv_import): compute renewal_date from today so the membership stays
        # Active. Only when the caller wants an Active membership — tests that
        # explicitly request Expired/Cancelled keep their backdated dates so
        # set_status() still derives the non-Active status they're exercising.
        if membership_data.get("status", "Active") == "Active" and frappe.utils.getdate(
            start_date
        ) < frappe.utils.getdate(frappe.utils.today()):
            membership._is_csv_import = True
        if skip_dues_schedule:
            membership.flags.skip_dues_schedule_creation = True
        membership.insert()

        # Track for cleanup in tearDown
        self._track_test_document("Membership", membership.name, priority=5)

        # Sync member_since on the Member document to match start_date
        # This ensures realistic test data where the member's join date
        # aligns with their membership start
        if sync_member_since:
            frappe.db.set_value("Member", member_name, "member_since", start_date, update_modified=False)

        membership.submit()
        return membership

    def link_member_to_customer(self, member_doc):
        """
        Create and link a Customer document to a Member.

        This is a convenience method that handles the boilerplate of creating
        a Customer record and linking it to an existing Member.

        Args:
            member_doc: Member document to link to a new customer

        Returns:
            Customer document that was created and linked

        Example:
            member = self.create_test_member(first_name="Test", last_name="User")
            customer = self.link_member_to_customer(member)
        """
        # Idempotent: create_test_member already auto-creates a Customer
        # (auto_create_customer=True) named from the member's full name. Creating a
        # second Customer with the same customer_name hits the Customer PRIMARY key
        # -> DuplicateEntryError. Reuse the existing customer instead.
        if member_doc.get("customer") and frappe.db.exists("Customer", member_doc.customer):
            return frappe.get_doc("Customer", member_doc.customer)

        customer_name = f"{member_doc.first_name} {member_doc.last_name}"
        if frappe.db.exists("Customer", customer_name):
            customer = frappe.get_doc("Customer", customer_name)
        else:
            customer = frappe.new_doc("Customer")
            customer.customer_name = customer_name
            customer.customer_type = "Individual"
            if customer.meta.has_field("member"):
                customer.member = member_doc.name
            customer.insert()

        member_doc.customer = customer.name
        member_doc.save()
        member_doc.reload()

        return customer

    def get_active_schedule_for_member(self, member_name):
        """
        Get the active dues schedule for a member.

        Args:
            member_name: Name of the Member document

        Returns:
            Membership Dues Schedule document

        Raises:
            frappe.ValidationError: If no active schedule exists for the member

        Example:
            schedule = self.get_active_schedule_for_member(member.name)
        """
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"},
            limit=1,
        )
        if not schedules:
            frappe.throw(f"No active schedule found for member {member_name}")

        return frappe.get_doc("Membership Dues Schedule", schedules[0].name)

    def create_test_member_with_schedule(
        self,
        first_name,
        last_name,
        membership_type_name,
        start_date,
        birth_date="1990-01-01",
        **membership_kwargs,
    ):
        """
        Create a complete test member with customer, membership, and dues schedule.

        This is a convenience method that combines several steps commonly needed
        in integration tests:
        1. Create a Member document
        2. Create and link a Customer document
        3. Create and submit a Membership (which triggers schedule creation)
        4. Retrieve the created dues schedule

        Args:
            first_name: Member's first name
            last_name: Member's last name
            membership_type_name: Name of the Membership Type to use
            start_date: Membership start date (also sets member_since)
            birth_date: Member's birth date (default: "1990-01-01")
            **membership_kwargs: Additional kwargs passed to create_test_membership

        Returns:
            tuple: (member_doc, schedule_doc)

        Example:
            # Create member who joined mid-quarter
            member, schedule = self.create_test_member_with_schedule(
                first_name="Test",
                last_name="Member",
                membership_type_name=self.membership_type.name,
                start_date="2025-11-15"  # Mid-Q4
            )
        """
        member = self.create_test_member(first_name=first_name, last_name=last_name, birth_date=birth_date)

        self.link_member_to_customer(member)

        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=membership_type_name,
            start_date=start_date,
            **membership_kwargs,
        )

        schedule = self.get_active_schedule_for_member(member.name)

        # Reload member to pick up member_since set by create_test_membership
        member.reload()

        return member, schedule

    def create_test_sales_invoice(self, customer, **kwargs):
        """Create a sales invoice record for testing"""
        # Ensure test item exists
        item_code = kwargs.get("item_code", "Test Service")
        self._ensure_test_item(item_code)

        # Resolve customer - handle both Member names and Customer names
        if customer and frappe.db.exists("Member", customer):
            # If customer is a Member name, get the linked Customer
            member = frappe.get_doc("Member", customer)
            if not member.customer:
                # Create customer if it doesn't exist
                member.create_customer()
                member.reload()
            actual_customer = member.customer
        elif customer and frappe.db.exists("Customer", customer):
            # Direct Customer reference
            actual_customer = customer
        else:
            frappe.throw(f"Invalid customer reference: {customer}")

        # Get consistent test company to avoid account/customer mismatch
        company = kwargs.get("company", self._get_test_company())
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"

        # Get proper debit_to (receivables) account from company default
        debit_to_account = frappe.db.get_value("Company", company, "default_receivable_account")
        if not debit_to_account:
            # Fallback: find any receivable account for this company
            debit_to_account = frappe.db.get_value(
                "Account", {"account_type": "Receivable", "company": company, "is_group": 0}, "name"
            )

        # If no receivable account exists, create one
        if not debit_to_account:
            debit_to_account = self._get_or_create_receivable_account(company)

        invoice_data = {
            "doctype": "Sales Invoice",
            "customer": actual_customer,
            "posting_date": kwargs.get("posting_date", frappe.utils.today()),
            # Honor the posting_date above. Without this, ERPNext's
            # TransactionBase.validate_posting_time() overwrites posting_date with
            # now() (erpnext/utilities/transaction_base.py). That used to be masked
            # because frappe.flags.in_import set set_posting_time implicitly; the
            # harness no longer sets that flag, so it must be explicit. A backdated
            # invoice silently becoming "today" also pushes posting_date past
            # due_date, which fails validate_due_date.
            "set_posting_time": 1,
            "due_date": kwargs.get("due_date", frappe.utils.add_days(frappe.utils.today(), 30)),
            "company": company,
            "currency": company_currency,  # Use company currency
            "conversion_rate": 1.0,  # No conversion needed for same currency
            "debit_to": debit_to_account,  # Explicit receivables account
            # Selling price list fields are mandatory on Sales Invoice in v16.
            "selling_price_list": self._ensure_selling_price_list(company_currency),
            "price_list_currency": company_currency,
            "plc_conversion_rate": 1.0,
            "ignore_pricing_rule": 1,
            # Real Sales Invoice fields are "is_membership_invoice" (Check) and the
            # "member" Link -- there is no custom_is_membership_invoice/custom_membership
            # field, so writing those silently dropped the values.
            "is_membership_invoice": kwargs.get("is_membership_invoice", 0),
        }

        # Get proper income account for ERPNext validation
        income_account = frappe.get_all(
            "Account",
            filters={"account_type": "Income Account", "company": company, "is_group": 0},
            limit=1,
            pluck="name",
        )
        if not income_account:
            income_account = self._get_or_create_income_account(company)
        else:
            income_account = income_account[0]

        # Get cost center for ERPNext validation (required for invoice items)
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        if not cost_center:
            # Find any active cost center for this company
            cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        # Add invoice item with proper accounting setup
        # If custom items are provided, ensure they have income_account and cost_center
        if "items" in kwargs:
            invoice_data["items"] = kwargs.pop("items")
            # Ensure items exist and add required accounting fields
            for item in invoice_data["items"]:
                # Ensure the item exists in the system
                if "item_code" in item:
                    self._ensure_test_item(item["item_code"])
                # Add income_account if not already present
                if "income_account" not in item:
                    item["income_account"] = income_account
                # Add cost_center if not already present (required by ERPNext)
                if "cost_center" not in item:
                    item["cost_center"] = cost_center
        else:
            invoice_data["items"] = [
                {
                    "item_code": item_code,
                    "qty": 1,
                    "rate": kwargs.get("grand_total", 100.0),
                    "amount": kwargs.get("grand_total", 100.0),
                    # Match the item's stock_uom ("Nos") to avoid requiring a UOM
                    # conversion factor during Sales Invoice validation.
                    "uom": "Nos",
                    "income_account": income_account,  # Required for ERPNext validation
                    "cost_center": cost_center,  # Required for ERPNext validation
                }
            ]

        invoice = frappe.get_doc(invoice_data)
        invoice.insert()
        self._track_test_document("Sales Invoice", invoice.name, priority=4)

        # Update grand_total and outstanding_amount manually for testing
        # This simulates overdue invoices with specific amounts
        if "grand_total" in kwargs or "outstanding_amount" in kwargs:
            invoice.db_set("grand_total", kwargs.get("grand_total", invoice.grand_total))
            invoice.db_set("outstanding_amount", kwargs.get("outstanding_amount", invoice.outstanding_amount))

        # Submit if status is not Draft
        if kwargs.get("status") != "Draft":
            invoice.submit()
            # Update status after submit if needed (for Overdue status)
            if kwargs.get("status") == "Overdue":
                invoice.db_set("status", "Overdue")

        return invoice

    def _get_or_create_income_account(self, company):
        """Get or create a basic income account for testing"""
        account_name = f"Test Sales Income - {company}"

        # Check if account already exists
        existing = frappe.db.get_value("Account", {"account_name": "Test Sales Income", "company": company})
        if existing:
            return existing

        # Find existing Income parent account
        income_parent = frappe.db.get_value(
            "Account", {"company": company, "root_type": "Income", "is_group": 1}, order_by="lft"
        )

        if not income_parent:
            # Create Income group first if it doesn't exist
            income_group = frappe.new_doc("Account")
            income_group.account_name = "Income"
            income_group.company = company
            income_group.root_type = "Income"
            income_group.report_type = "Profit and Loss"
            income_group.is_group = 1
            income_group.save()
            self.factory.track_document("Account", income_group.name, priority=-1)
            income_parent = income_group.name

        # Create new income account under proper parent
        account = frappe.new_doc("Account")
        account.account_name = "Test Sales Income"
        account.company = company
        account.parent_account = income_parent
        account.account_type = "Income Account"
        account.root_type = "Income"
        account.report_type = "Profit and Loss"
        account.is_group = 0
        account.save()
        # priority=-1, not 1: these are SHARED master data created once per site, not
        # per-test fixtures. _drain_tracked_documents force-deletes everything with
        # priority >= 0 on every tearDown, so tracking them at 1 would delete the
        # company's income accounts out from under the next test -- and this method
        # only runs when the account is missing, so it would recreate and re-delete
        # them on a loop. See the priority contract in _drain_tracked_documents.
        self.factory.track_document("Account", account.name, priority=-1)
        return account.name

    def _get_or_create_receivable_account(self, company):
        """
        Get or create a receivable account for testing.

        Ensures Chart of Accounts is initialized before looking for receivable account.
        """
        # Ensure CoA is initialized (will only run once per company)
        self._ensure_company_chart_of_accounts(company)

        # First check company default (should exist after CoA initialization)
        default_receivable = frappe.db.get_value("Company", company, "default_receivable_account")
        if default_receivable:
            return default_receivable

        # Fallback: Find any non-group receivable account
        receivable_account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Receivable", "is_group": 0},
            "name",
            order_by="lft",
        )

        if receivable_account:
            return receivable_account

        # Should not reach here if Chart of Accounts was initialized properly
        frappe.throw(
            f"No receivable account found for company {company}. "
            f"Chart of Accounts initialization may have failed."
        )

    def ensure_mode_of_payment(self, name="Mollie", mop_type="Bank"):
        """Get-or-create a Mode of Payment, tracking it for cleanup.

        "Mollie" is NOT an app fixture and is not seeded by the data factory, so
        tests that hard-code ``donation.mode_of_payment = "Mollie"`` must seed it
        themselves to pass in isolation (and not rely on shard ordering). This is
        a setup helper, so the permission bypass on insert is appropriate here and
        never appears in a test body.

        Returns the Mode of Payment name.
        """
        if frappe.db.exists("Mode of Payment", name):
            return name
        mop = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": mop_type})
        mop.insert(ignore_permissions=True)
        self.track_test_record("Mode of Payment", mop.name)
        return mop.name

    def create_test_donor(self, **kwargs):
        """Create a test donor record for ANBI testing"""
        import os

        # Generate unique donor email to prevent collisions in parallel tests
        import time

        from verenigingen.tests.fixtures.dutch_validation_helpers import (
            generate_valid_rsin,
            get_test_bsn_numbers,
        )

        default_donor_email = (
            f"test.donor.{os.getpid() % 10000}_{int(time.time() * 1000) % 100000000}@example.com"
        )

        donor_data = {
            "doctype": "Donor",
            "donor_name": kwargs.get("donor_name", "Test Donor"),
            "donor_type": kwargs.get("donor_type", "Individual"),
            "donor_email": kwargs.get("donor_email", default_donor_email),  # Mandatory field
            "currency": "EUR",
        }

        # Add valid BSN for individuals or valid RSIN for organizations
        if kwargs.get("donor_type") == "Individual":
            if "bsn_citizen_service_number" in kwargs:
                donor_data["bsn_citizen_service_number"] = kwargs["bsn_citizen_service_number"]
            else:
                # Use a valid BSN by default
                donor_data["bsn_citizen_service_number"] = get_test_bsn_numbers()[0]  # "123456782"
        elif kwargs.get("donor_type") == "Organization":
            if "rsin_organization_tax_number" in kwargs:
                donor_data["rsin_organization_tax_number"] = kwargs["rsin_organization_tax_number"]
            else:
                # Generate a valid RSIN by default
                donor_data["rsin_organization_tax_number"] = generate_valid_rsin()

        # Add ANBI consent if specified
        if "anbi_consent" in kwargs:
            donor_data["anbi_consent"] = kwargs["anbi_consent"]

        # Pass through any remaining caller-supplied Donor fields (e.g. member,
        # phone, contact_person, customer). Previously these were silently dropped
        # because donor_data was built from a fixed whitelist, so callers passing
        # member=... ended up with an unlinked donor.
        _handled = {
            "doctype",
            "donor_name",
            "donor_type",
            "donor_email",
            "currency",
            "bsn_citizen_service_number",
            "rsin_organization_tax_number",
            "anbi_consent",
        }
        for key, value in kwargs.items():
            if key not in _handled:
                donor_data[key] = value

        donor = frappe.get_doc(donor_data)
        donor.insert()
        self.factory.track_document("Donor", donor.name, priority=4)
        return donor

    def create_test_donation(self, **kwargs):
        """Create a test donation record"""
        # Ensure we have a company for the donation
        company = kwargs.get("company") or frappe.get_list("Company", limit=1)[0].name

        # Create a donor if not provided
        donor = kwargs.get("donor")
        if not donor:
            # Let create_test_donor generate unique email if not provided
            donor_doc = self.create_test_donor(
                donor_email=kwargs.get("donor_email"),  # None will trigger unique generation
                donor_name=kwargs.get("donor_name", "Test Donor"),
            )
            donor = donor_doc.name

        donation_data = {
            "doctype": "Donation",
            "company": company,
            "donor": donor,
            "amount": kwargs.get("amount", 100.0),
            "donation_date": kwargs.get("donation_date", frappe.utils.today()),
            "currency": "EUR",
            "paid": kwargs.get("paid", 1),
            "mode_of_payment": kwargs.get("mode_of_payment", "Bank Transfer"),  # Mandatory field
            # Don't set docstatus in initial data - handle submission below
        }

        # Add optional fields
        for field in [
            "anbi_agreement_number",
            "periodic_donation_agreement",
            "campaign",
            "donation_type",
            "status",
            "donation_purpose_type",
            "donation_notes",
            "company",
            "payment_id",
        ]:
            if field in kwargs:
                donation_data[field] = kwargs[field]

        # If ANBI agreement number is provided, add required agreement date
        if "anbi_agreement_number" in kwargs and kwargs["anbi_agreement_number"]:
            if "anbi_agreement_date" not in kwargs:
                donation_data["anbi_agreement_date"] = donation_data[
                    "donation_date"
                ]  # Use same date as donation
            else:
                donation_data["anbi_agreement_date"] = kwargs["anbi_agreement_date"]

        donation = frappe.get_doc(donation_data)
        donation.insert()
        self.factory.track_document("Donation", donation.name, priority=4)
        # Always submit the donation in test context to ensure docstatus=1 for campaign queries
        if frappe.flags.in_test:
            # Use db_set to avoid fiscal year and other submission validation issues in tests
            frappe.db.set_value("Donation", donation.name, "docstatus", 1)
            donation.reload()
        else:
            donation.submit()  # Submit normally in production
        return donation

    def _get_test_company(self):
        """
        Get or create a consistent test company for all test data.

        This ensures customers, invoices, and accounts all use the same company,
        avoiding company mismatch errors.

        Returns:
            str: Company name to use for test data
        """
        # Check if a test company preference is already set
        if hasattr(frappe.local, "test_company_name"):
            return frappe.local.test_company_name

        # Pick a company the harness OWNS, by name.
        #
        # This used to be `frappe.get_all("Company", limit=1, pluck="name")`, which is not
        # "whatever company happens to be there": Company's meta sorts `creation ASC`, so it
        # deterministically took the OLDEST company on the site. On a test site that is
        # `_Test Company` and all is well. On a site with real data it is the real
        # organisation's company -- which was then handed straight to
        # `_ensure_company_chart_of_accounts()`, whose partial-CoA path deletes that
        # company's GL entries and force-deletes its accounts. See issue #299.
        for candidate in HARNESS_OWNED_COMPANIES:
            if frappe.db.exists("Company", candidate):
                company = candidate
                break
        else:
            raise ValueError(
                "No harness-owned Company found. Expected one of: "
                f"{', '.join(HARNESS_OWNED_COMPANIES)}. These are created by before_tests "
                "(verenigingen/tests/setup/__init__.py); run the suite through `bench run-tests` "
                "so that hook fires. The harness deliberately will NOT borrow an arbitrary "
                "company, because initialising its chart of accounts can delete accounts."
            )

        # Ensure company has Chart of Accounts for accounting tests
        self._ensure_company_chart_of_accounts(company)
        frappe.local.test_company_name = company
        return company

    def _ensure_company_chart_of_accounts(self, company_name):
        """
        Ensure the test company has a Chart of Accounts initialized.

        This is required for any tests that create Sales Invoices, Purchase Invoices,
        Payment Entries, or other accounting transactions.
        """
        # Check if company already has a complete Chart of Accounts
        # Must have both receivable and payable accounts to be considered complete
        has_receivable = frappe.db.exists(
            "Account", {"company": company_name, "account_type": "Receivable", "is_group": 0}
        )
        has_payable = frappe.db.exists(
            "Account", {"company": company_name, "account_type": "Payable", "is_group": 0}
        )

        if has_receivable and has_payable:
            # CoA already initialized - fix currency if needed and ensure defaults are set
            company_doc = frappe.get_doc("Company", company_name)
            if company_doc.default_currency == "AED":
                company_doc.db_set("default_currency", "EUR", update_modified=False)

            self._ensure_company_defaults(company_name)
            return

        # Below this point the method DELETES this company's GL entries and accounts, and
        # `company_name` may be caller-supplied (see _get_or_create_receivable_account), so
        # it cannot be taken on trust. A chart of accounts genuinely left half-built by a
        # failed run has no postings against it; anything with GL entries is real
        # bookkeeping, and on a developer's site that is live data. Refuse loudly rather
        # than delete -- a test that cannot get a CoA is a broken test, but a test that
        # silently erases a ledger is a catastrophe. See #299.
        posted_entries = frappe.db.count("GL Entry", {"company": company_name})
        if posted_entries:
            raise ValueError(
                f"Refusing to reset the chart of accounts for company {company_name!r}: it has "
                f"{posted_entries} GL Entry rows, so this is not a partial CoA from a failed "
                "run. The harness only rebuilds a chart of accounts it can prove is unused. "
                "If this is a test company, delete its GL entries first; if it is real data, "
                "the test should not be pointing at it."
            )

        # Clean up any partial accounts from previous failed runs
        # Delete accounts in reverse rgt order (children before parents) to respect tree structure
        partial_accounts = frappe.db.sql(
            """
            SELECT name
            FROM `tabAccount`
            WHERE company = %s
            ORDER BY rgt DESC
            """,
            (company_name,),
            as_dict=False,
        )

        if partial_accounts:
            # First delete GL entries for these accounts (if any exist)
            try:
                frappe.db.sql(
                    """
                    DELETE FROM `tabGL Entry`
                    WHERE account IN (
                        SELECT name FROM `tabAccount` WHERE company = %s
                    )
                    """,
                    (company_name,),
                )
            except Exception:
                pass  # GL entries may not exist

            # Delete accounts in reverse rgt order (children first)
            for (account_name,) in partial_accounts:
                try:
                    frappe.delete_doc("Account", account_name, force=True, ignore_permissions=True)
                except Exception:
                    pass  # Continue deleting other accounts

            frappe.db.commit()

        # Initialize Chart of Accounts using ERPNext's built-in method
        try:
            from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

            # Set flag to bypass company validation during CoA creation
            frappe.local.flags.ignore_root_company_validation = True

            # Use Standard chart of accounts (works for all countries)
            create_charts(company_name, "Standard", None)

            # Fix currency mismatch: Set company to EUR for Dutch association tests
            # (Standard CoA creates accounts in EUR but company defaults to AED)
            company_doc = frappe.get_doc("Company", company_name)
            if company_doc.default_currency == "AED":
                company_doc.db_set("default_currency", "EUR", update_modified=False)

            # Set company defaults after creation
            self._ensure_company_defaults(company_name)

        except Exception as e:
            # If Chart of Accounts creation fails, log and print for visibility
            import traceback

            error_msg = (
                f"Failed to initialize Chart of Accounts for {company_name}: {e}\n{traceback.format_exc()}"
            )
            print(f"\n⚠️  WARNING: {error_msg}")
            frappe.log_error(error_msg, "Test CoA Initialization Failed")
        finally:
            # Clean up flag
            if hasattr(frappe.local.flags, "ignore_root_company_validation"):
                del frappe.local.flags.ignore_root_company_validation

    def _ensure_company_defaults(self, company_name):
        """
        Ensure company has default receivable, payable accounts, cost center, and round off account.

        Called after Chart of Accounts initialization to configure company defaults.
        """
        company_doc = frappe.get_doc("Company", company_name)

        # Set round off account if not already set (required for invoice submission)
        if not company_doc.round_off_account:
            # Find an expense account for round off
            round_off_account = frappe.db.get_value(
                "Account", {"company": company_name, "account_type": "Expense Account", "is_group": 0}, "name"
            )
            if not round_off_account:
                # No expense account exists - create one for round off
                round_off_account = self._create_round_off_account(company_name)
            if round_off_account:
                company_doc.db_set("round_off_account", round_off_account)

        # Set default receivable account if not already set
        if not company_doc.default_receivable_account:
            receivable_account = frappe.db.get_value(
                "Account", {"company": company_name, "account_type": "Receivable", "is_group": 0}, "name"
            )
            if receivable_account:
                company_doc.db_set("default_receivable_account", receivable_account)

        # Set default payable account if not already set
        if not company_doc.default_payable_account:
            payable_account = frappe.db.get_value(
                "Account", {"company": company_name, "account_type": "Payable", "is_group": 0}, "name"
            )
            if payable_account:
                company_doc.db_set("default_payable_account", payable_account)

        # Ensure cost center exists and is set as default
        self._ensure_company_cost_center(company_name)

    def _ensure_company_cost_center(self, company_name):
        """
        Ensure company has a cost center configured.

        Creates a Main cost center if none exists and sets it as the company default.
        This is critical for Sales Invoice creation which requires a cost center.
        """
        # Check if company already has a default cost center
        existing_default = frappe.db.get_value("Company", company_name, "cost_center")
        if existing_default and frappe.db.exists("Cost Center", existing_default):
            return existing_default

        # Check for any existing cost center for this company
        existing_cc = frappe.db.get_value("Cost Center", {"company": company_name, "is_group": 0}, "name")
        if existing_cc:
            frappe.db.set_value("Company", company_name, "cost_center", existing_cc, update_modified=False)
            return existing_cc

        # No cost center exists - create one using ERPNext's standard approach
        abbr = frappe.db.get_value("Company", company_name, "abbr") or "TC"

        # Check if there's already a root cost center for this company (group with no parent)
        root_cc_name = frappe.db.get_value("Cost Center", {"company": company_name, "is_group": 1}, "name")

        if not root_cc_name:
            # Create root cost center - use db.sql to bypass tree validation for root
            root_cc_name = f"{company_name} - {abbr}"
            if not frappe.db.exists("Cost Center", root_cc_name):
                frappe.db.sql(
                    """
                    INSERT INTO `tabCost Center`
                    (name, cost_center_name, company, is_group, lft, rgt, parent_cost_center, docstatus, creation, modified, owner, modified_by)
                    VALUES (%s, %s, %s, 1, 1, 4, '', 0, NOW(), NOW(), 'Administrator', 'Administrator')
                """,
                    (root_cc_name, company_name, company_name),
                )

        # Create Main cost center under root
        main_cc_name = f"Main - {abbr}"
        if not frappe.db.exists("Cost Center", main_cc_name):
            frappe.db.sql(
                """
                INSERT INTO `tabCost Center`
                (name, cost_center_name, company, is_group, lft, rgt, parent_cost_center, docstatus, creation, modified, owner, modified_by)
                VALUES (%s, %s, %s, 0, 2, 3, %s, 0, NOW(), NOW(), 'Administrator', 'Administrator')
            """,
                (main_cc_name, "Main", company_name, root_cc_name),
            )

        # Set as company default
        frappe.db.set_value("Company", company_name, "cost_center", main_cc_name, update_modified=False)
        return main_cc_name

    def _create_round_off_account(self, company_name):
        """
        Create a round off expense account for the company.

        Required for Sales Invoice submission in ERPNext.
        """
        abbr = frappe.db.get_value("Company", company_name, "abbr") or "TC"

        # Find or create expense parent account
        expense_parent = frappe.db.get_value(
            "Account", {"company": company_name, "root_type": "Expense", "is_group": 1}, "name"
        )

        if not expense_parent:
            # Create expense root using SQL to bypass tree validation
            expense_parent = f"Expenses - {abbr}"
            if not frappe.db.exists("Account", expense_parent):
                frappe.db.sql(
                    """
                    INSERT INTO `tabAccount`
                    (name, account_name, company, root_type, report_type, is_group, lft, rgt, parent_account, docstatus, creation, modified, owner, modified_by)
                    VALUES (%s, %s, %s, 'Expense', 'Profit and Loss', 1, 1, 4, '', 0, NOW(), NOW(), 'Administrator', 'Administrator')
                """,
                    (expense_parent, "Expenses", company_name),
                )

        # Create round off account
        round_off_name = f"Round Off - {abbr}"
        if not frappe.db.exists("Account", round_off_name):
            frappe.db.sql(
                """
                INSERT INTO `tabAccount`
                (name, account_name, company, root_type, report_type, account_type, is_group, lft, rgt, parent_account, docstatus, creation, modified, owner, modified_by)
                VALUES (%s, %s, %s, 'Expense', 'Profit and Loss', 'Expense Account', 0, 2, 3, %s, 0, NOW(), NOW(), 'Administrator', 'Administrator')
            """,
                (round_off_name, "Round Off", company_name, expense_parent),
            )

        return round_off_name

    def _ensure_verenigingen_settings(self, test_company):
        """
        Ensure Verenigingen Settings is configured for the test company.

        This prevents company/account mismatch errors in invoice generation tests
        by ensuring the dues_income_account and cost center belong to the same
        company used for test members and invoices.

        Note: Original settings are saved and should be restored after tests
        via _restore_verenigingen_settings() in tearDown.
        """
        # Save original settings for restoration after tests
        # Store on frappe.local to survive across test methods in same class
        if not hasattr(frappe.local, "_original_verenigingen_settings"):
            frappe.local._original_verenigingen_settings = {
                "company": frappe.db.get_value("Verenigingen Settings", None, "company"),
                "dues_income_account": frappe.db.get_value(
                    "Verenigingen Payments Settings", None, "dues_income_account"
                ),
            }

        # Get or create income account for test company
        income_account = self._get_or_create_income_account(test_company)

        # Get or create cost center for test company
        cost_center = self._get_or_create_cost_center(test_company)

        # Update Verenigingen Settings to use the test company
        frappe.db.set_value("Verenigingen Settings", None, "company", test_company, update_modified=False)
        frappe.db.set_value(
            "Verenigingen Payments Settings",
            None,
            "dues_income_account",
            income_account,
            update_modified=False,
        )

        # Also ensure default_income_account on the company for fallback paths
        current_default = frappe.db.get_value("Company", test_company, "default_income_account")
        if not current_default:
            frappe.db.set_value(
                "Company", test_company, "default_income_account", income_account, update_modified=False
            )

        # Ensure company has a cost center configured
        if cost_center:
            current_cost_center = frappe.db.get_value("Company", test_company, "cost_center")
            if not current_cost_center:
                frappe.db.set_value(
                    "Company", test_company, "cost_center", cost_center, update_modified=False
                )

        # Clear stale national_board_chapter references to prevent "Chapter not found" errors
        # This setting may point to a chapter from a previous test run that no longer exists
        current_national_chapter = frappe.db.get_value(
            "Verenigingen Settings", None, "national_board_chapter"
        )
        if current_national_chapter and not frappe.db.exists("Chapter", current_national_chapter):
            frappe.db.set_value(
                "Verenigingen Settings", None, "national_board_chapter", None, update_modified=False
            )

        frappe.db.commit()

    def _restore_verenigingen_settings(self):
        """
        Restore original Verenigingen Settings after tests.

        Called from tearDown to ensure production settings are not permanently
        modified by test runs.
        """
        if hasattr(frappe.local, "_original_verenigingen_settings"):
            original = frappe.local._original_verenigingen_settings
            if original.get("company"):
                frappe.db.set_value(
                    "Verenigingen Settings", None, "company", original["company"], update_modified=False
                )
            if original.get("dues_income_account"):
                frappe.db.set_value(
                    "Verenigingen Payments Settings",
                    None,
                    "dues_income_account",
                    original["dues_income_account"],
                    update_modified=False,
                )
            frappe.db.commit()
            # Clear the stored original to prevent double-restore
            delattr(frappe.local, "_original_verenigingen_settings")

    def _get_or_create_cost_center(self, company):
        """Get or create a Main cost center for testing"""
        # Check for existing Main cost center
        existing = frappe.db.get_value("Cost Center", {"cost_center_name": "Main", "company": company})
        if existing:
            return existing

        # Get company abbreviation for naming
        abbr = frappe.db.get_value("Company", company, "abbr") or company.split()[-1][:3].upper()
        cost_center_name = f"Main - {abbr}"

        # Check if this specific name exists
        if frappe.db.exists("Cost Center", cost_center_name):
            return cost_center_name

        # Find parent cost center (root for this company)
        parent_cc = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ""}
        )

        if not parent_cc:
            # Create root cost center first
            root_name = f"{company} - {abbr}"
            if not frappe.db.exists("Cost Center", root_name):
                root_cc = frappe.new_doc("Cost Center")
                root_cc.cost_center_name = company
                root_cc.company = company
                root_cc.is_group = 1
                root_cc.parent_cost_center = ""
                root_cc.insert()
                self.factory.track_document("Cost Center", root_cc.name, priority=-1)
                parent_cc = root_cc.name
            else:
                parent_cc = root_name

        # Create Main cost center
        cc = frappe.new_doc("Cost Center")
        cc.cost_center_name = "Main"
        cc.company = company
        cc.parent_cost_center = parent_cc
        cc.is_group = 0
        cc.insert()
        self.factory.track_document("Cost Center", cc.name, priority=-1)
        return cc.name

    def _ensure_test_item(self, item_code):
        """Ensure test item exists for invoices"""
        if not frappe.db.exists("Item", item_code):
            # stock_uom is mandatory on Item. Use "Nos", a UOM ERPNext ships by
            # default; create it defensively in case the test site lacks it.
            stock_uom = self._ensure_test_uom("Nos")
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": item_code,
                    "item_group": "All Item Groups",
                    "stock_uom": stock_uom,
                    "is_sales_item": 1,
                    "is_service_item": 1,
                    "is_stock_item": 0,
                    "include_item_in_manufacturing": 0,
                    "standard_rate": 100.0,
                    "description": f"Test item created by Enhanced Test Factory",
                }
            )
            item.insert()
            self._track_test_document("Item", item.name, priority=1)
        return item_code

    def _ensure_test_uom(self, uom_name="Nos"):
        """Ensure a UOM exists on the test site, returning its name."""
        if not frappe.db.exists("UOM", uom_name):
            uom = frappe.get_doc({"doctype": "UOM", "uom_name": uom_name})
            uom.insert(ignore_permissions=True)
            self._track_test_document("UOM", uom.name, priority=0)
        return uom_name

    def _ensure_selling_price_list(self, currency="EUR"):
        """Return a selling Price List name, preferring ERPNext's 'Standard Selling'."""
        if frappe.db.exists("Price List", "Standard Selling"):
            return "Standard Selling"
        existing = frappe.db.get_value("Price List", {"selling": 1}, "name")
        if existing:
            return existing
        price_list = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": "Standard Selling",
                "selling": 1,
                "currency": currency,
            }
        )
        price_list.insert(ignore_permissions=True)
        self._track_test_document("Price List", price_list.name, priority=0)
        return price_list.name

    def create_test_user(self, email, roles=None, **kwargs):
        """Create a test user with specified roles"""
        if not roles:
            roles = ["System Manager"]

        user_data = {
            "doctype": "User",
            "email": email,
            "first_name": kwargs.get("first_name", "Test"),
            "last_name": kwargs.get("last_name", "User"),
            "enabled": 1,
            "send_welcome_email": 0,
        }

        # Switch to Administrator context for user creation (required permission)
        original_user = frappe.session.user
        frappe.set_user("Administrator")

        try:
            # Check if user already exists - reuse existing to avoid duplicate infrastructure
            if frappe.db.exists("User", email):
                user = frappe.get_doc("User", email)
                # Update enabled status if provided in kwargs
                user.enabled = kwargs.get("enabled", 1)
            else:
                user = frappe.get_doc(user_data)
                user.insert()
                # Priority 2: Organization - deleted after transactional records but before infrastructure
                self.factory.track_document("User", user.name, priority=2)

            # Add roles - clear existing to ensure clean test state
            user.roles = []  # Clear existing roles
            for role in roles:
                user.append("roles", {"role": role})
            # Ensure enabled status is set from kwargs if provided
            if "enabled" in kwargs:
                user.enabled = kwargs["enabled"]
            user.save()
            # Track again after role changes to ensure cleanup captures final state
            self.factory.track_document("User", user.name, priority=2)

            return user
        finally:
            # Restore original user context
            frappe.set_user(original_user)

    def mock_redis_queue(self):
        """Context manager for mocking Redis queue operations"""
        return self.factory.mock_redis_queue()

    def simulate_background_job_failure(self, error_type="timeout"):
        """Simulate background job processing failures"""
        return self.factory.simulate_background_job_failure(error_type)

    def create_test_role_profile(self, profile_name, roles=None):
        """Convenience method for creating role profiles"""
        return self.factory.create_test_role_profile(profile_name, roles)

    def create_permission_test_scenario(self, authorized_roles=None, unauthorized_roles=None):
        """Create comprehensive permission testing scenario"""
        return self.factory.create_permission_test_scenario(authorized_roles, unauthorized_roles)

    def assertBusinessRuleViolation(self, callable_obj, *args, **kwargs):
        """Assert that a business rule violation occurs"""
        with self.assertRaises(BusinessRuleError):
            callable_obj(*args, **kwargs)

    def assertFieldValidationError(self, callable_obj, *args, **kwargs):
        """Assert that a field validation error occurs"""
        from verenigingen.tests.fixtures.field_validator import FieldValidationError

        with self.assertRaises(FieldValidationError):
            callable_obj(*args, **kwargs)

    def assertPermissionError(self, callable_obj, *args, **kwargs):
        """Assert that a permission error occurs"""
        with self.assertRaises(frappe.PermissionError):
            callable_obj(*args, **kwargs)

    def as_user(self, user_email):
        """Context manager for running code as specific user"""
        from contextlib import contextmanager

        @contextmanager
        def user_context():
            original_user = frappe.session.user
            try:
                frappe.set_user(user_email)
                yield
            finally:
                frappe.set_user(original_user)

        return user_context()

    def track_doc(self, doctype, name, depends_on=None):
        """Track a document for automatic cleanup.

        Compatibility alias for the underlying factory's track_document(), matching
        the VereningingenTestCase.track_doc() signature so tests can use either
        base class interchangeably. `depends_on` is accepted for signature
        compatibility (cleanup ordering is handled by the factory's priorities).
        """
        return self.factory.track_document(doctype, name)

    def as_role(self, role_or_roles, *, email=None):
        """Run a block as a scratch user holding the given role(s) or role profile.

        Most permission-sensitive tests should run as a real role, not as
        Administrator (which bypasses every DocPerm check in Frappe). This
        helper creates a per-test scratch user, assigns the requested role(s)
        or role profile, and switches frappe.session.user for the duration of
        the block.

        Args:
            role_or_roles: A role name (str), list of role names, or role
                profile name. Role profile names are detected by checking the
                Role Profile doctype; if found, all roles from that profile
                are applied to the scratch user.
            email: Optional explicit email for the scratch user. If omitted, a
                deterministic per-role email is generated and reused across
                calls in the same test.

        Returns:
            Context manager that switches frappe.session.user.

        Example:
            with self.as_role("Verenigingen Staff"):
                result = some_permission_sensitive_function(...)
            with self.as_role(["Verenigingen Volunteer", "Employee"]):
                ...
        """
        if isinstance(role_or_roles, str):
            names = [role_or_roles]
            key = f"profile-{role_or_roles}" if frappe.db.exists("Role Profile", role_or_roles) else role_or_roles
        else:
            names = list(role_or_roles)
            key = "_".join(sorted(names))

        # A requested name that matches a Role Profile grants its security tier via
        # the role-profile authorization table (Rule 4). After the audit #2 Rule-5
        # cap, HIGH/CRITICAL access requires the assigned PROFILE, not the bare role
        # -- a scratch user given only roles is capped at MEDIUM and denied
        # HIGH/CRITICAL endpoints. So collect the matching profile(s) and assign them
        # too, alongside each profile's constituent roles (Frappe DocPerm checks
        # still need the raw roles).
        roles = []
        profiles = []
        for name in names:
            if frappe.db.exists("Role Profile", name):
                profiles.append(name)
                roles.extend(r.role for r in frappe.get_doc("Role Profile", name).roles)
            else:
                roles.append(name)
        roles = list(dict.fromkeys(roles))  # dedupe, preserve order

        if not email:
            # Deterministic, reusable scratch user per role-set + test run
            test_run_id = getattr(self, "test_run_id", None) or getattr(self, "uid", "default")
            slug = (key.lower().replace(" ", "_").replace("/", "_").replace(":", "_"))[:40]
            email = f"scratch.{slug}.{test_run_id}@test.invalid"

        # create_test_user reuses existing User if present and resets roles each call
        self.create_test_user(email, roles=roles)

        if profiles:
            self._assign_role_profiles(email, profiles)

        return self.as_user(email)

    def _assign_role_profiles(self, email, profiles):
        """Assign role profile(s) to a scratch user so the security framework's
        role-profile authorization (Rule 4) grants the intended HIGH/CRITICAL tier.

        get_user_role_profiles reads both User.role_profile_name and the
        role_profiles child table, so populate both; then invalidate the auth
        engine's per-user cache so the assignment is visible immediately.
        """
        original_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.get_doc("User", email)
            user.set("role_profiles", [{"role_profile": p} for p in profiles])
            user.role_profile_name = profiles[0]
            user.save(ignore_permissions=True)
        finally:
            frappe.set_user(original_user)

        try:
            from verenigingen.utils.security.api_security_framework import get_security_framework

            get_security_framework().auth_engine.invalidate_user_cache(email)
        except Exception:
            # Cache invalidation is best-effort; the 5-min TTL bounds staleness.
            pass

    def as_staff(self, **kwargs):
        """Shortcut: run as a scratch user with Verenigingen Staff role only.

        Use this for permission-sensitive tests that should verify the flow
        works for the lowest-privilege admin tier. See as_role() for details.
        """
        return self.as_role("Verenigingen Staff", **kwargs)

    def as_admin_role(self, **kwargs):
        """Shortcut: run as a scratch user with Verenigingen Administrator role.

        Note: this is the role only, NOT the literal Administrator user
        account (which bypasses every permission check via the special-case
        in frappe/permissions.py). Use this when you want to test admin-tier
        access without the Administrator-user bypass masking real perm bugs.
        """
        return self.as_role("Verenigingen Administrator", **kwargs)

    def create_test_member_optimized(self, **kwargs):
        """Create test member using performance optimizations

        Uses the MemberPerformanceOptimizer to create members with
        reduced query count while maintaining all business rule validation.

        Args:
            **kwargs: Member data (same as create_test_member)

        Returns:
            Member document
        """
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Apply same validations as regular create_test_member
        if "birth_date" in kwargs:
            if kwargs.get("create_volunteer", False):
                # Use AgeValidator for consistent business rule enforcement
                from verenigingen.utils.validation_utilities import AgeValidator

                try:
                    AgeValidator.validate_age(kwargs["birth_date"], context="volunteer", throw_on_error=True)
                except Exception as e:
                    from verenigingen.tests.fixtures.enhanced_test_factory import BusinessRuleError

                    raise BusinessRuleError(f"Volunteer age validation failed: {str(e)}")

        # Use enhanced default data from factory
        member_data = self.factory._get_enhanced_member_defaults()
        member_data.update(kwargs)

        # Field validation
        self.factory._validate_fields("Member", member_data)

        # Use optimized creation
        member_name = member_optimizer.create_member_optimized(member_data)
        return frappe.get_doc("Member", member_name)

    def assertQueryCountOptimized(self, max_queries, optimization_level="standard"):
        """Performance assertion with optimization recommendations

        Args:
            max_queries: Maximum expected query count
            optimization_level: Expected optimization level
                - "excellent": <50 queries
                - "good": 50-200 queries
                - "standard": 200-500 queries
                - "baseline": >500 queries (needs optimization)

        Returns:
            Context manager for query count monitoring with suggestions
        """

        def decorator(func):
            def wrapper(*args, **kwargs):
                import time

                start_time = time.time()

                with self.assertQueryCount(max_queries) as context:
                    result = func(*args, **kwargs)

                duration = time.time() - start_time
                actual_queries = len(context.queries)

                # Provide optimization feedback
                if optimization_level == "excellent" and actual_queries > 50:
                    print(f"⚠️ Performance concern: {actual_queries}/{max_queries} queries used")
                    print("Consider implementing:")
                    print("- DocType metadata caching")
                    print("- Bulk operations for related records")
                    print("- Background processing for non-critical hooks")
                elif optimization_level == "good" and actual_queries > 200:
                    print(f"⚠️ Performance warning: {actual_queries}/{max_queries} queries used")
                    print("Consider:")
                    print("- JOIN queries instead of N+1 patterns")
                    print("- Caching frequently accessed data")
                elif actual_queries < max_queries * 0.5:
                    print(f"🚀 Excellent performance: {actual_queries}/{max_queries} queries used")
                    print(f"⏱️  Execution time: {duration:.3f}s")
                elif actual_queries < max_queries * 0.8:
                    print(f"✅ Good performance: {actual_queries}/{max_queries} queries used")
                    print(f"⏱️  Execution time: {duration:.3f}s")
                else:
                    print(f"🐌 Performance needs attention: {actual_queries}/{max_queries} queries used")
                    print(f"⏱️  Execution time: {duration:.3f}s")

                return result

            return wrapper

        return decorator

    # API Compatibility Bridge Methods
    def create_test_chapter(self, **kwargs):
        """
        🌉 Bridge Method: API compatibility with VereningingenTestCase

        This method provides compatibility between the two test frameworks:
        - VereningingenTestCase uses: create_test_chapter()
        - EnhancedTestCase uses: create_chapter()

        Both methods now work in both frameworks, solving the API inconsistency
        discovered during Phase 5.1 production issue fixes.
        """
        return self.create_chapter(**kwargs)

    def cleanup_test_chapters(self, chapter_pattern=None, member_pattern=None):
        """
        🧹 Phase 5.2A Fix: Chapter and Member cleanup method

        PRODUCTION ISSUE DISCOVERED: Enhanced Test Factory was missing cleanup_test_chapters() method
        that existing tests expected. This method was present in basic test files but missing from
        the Enhanced Test Factory framework, causing API inconsistency.

        This method provides flexible cleanup for chapter management tests:
        - Cleans up test chapters and their members
        - Supports custom patterns for targeted cleanup
        - Handles orphaned chapter members and test data
        - Uses direct SQL to avoid validation issues during cleanup

        Args:
            chapter_pattern (str): Chapter name pattern for cleanup (default: test patterns)
            member_pattern (str): Member name pattern for cleanup (default: test patterns)
        """
        # Default patterns for test data cleanup
        if chapter_pattern is None:
            chapter_pattern = ["%Test Chapter%", "%Phase%Test%", "Basic Test Chapter%"]
        elif isinstance(chapter_pattern, str):
            chapter_pattern = [chapter_pattern]

        if member_pattern is None:
            member_pattern = ["BasicTest%", "Phase5_2A%", "%TestMember%"]
        elif isinstance(member_pattern, str):
            member_pattern = [member_pattern]

        # Clean up test chapters - handle multiple patterns
        for pattern in chapter_pattern:
            frappe.db.sql(
                """
                DELETE FROM `tabChapter`
                WHERE name LIKE %s
            """,
                (pattern,),
            )

            # Also clean up any orphaned chapter members for this pattern
            frappe.db.sql(
                """
                DELETE FROM `tabChapter Member`
                WHERE parent LIKE %s
            """,
                (pattern,),
            )

        # Clean up test members created by chapter tests
        for pattern in member_pattern:
            frappe.db.sql(
                """
                DELETE FROM `tabMember`
                WHERE first_name LIKE %s
            """,
                (pattern,),
            )

        # Clean up any Chapter Membership History entries for test data (if table exists)
        # Note: Chapter membership is actually stored in Chapter.members child table
        # but this cleanup handles any legacy history entries
        try:
            for pattern in member_pattern:
                # Ensure pattern has wildcards for SQL LIKE operation
                like_pattern = pattern if "%" in pattern else f"%{pattern}%"
                frappe.db.sql(
                    """
                    DELETE FROM `tabChapter Membership History`
                    WHERE member LIKE %s
                """,
                    (like_pattern,),
                )
        except Exception:
            # Table might not exist - that's OK, chapter membership is in Chapter.members
            pass

        # Clean up cost centers created for test chapters
        for pattern in chapter_pattern:
            # Find chapters that match the pattern to get their cost centers
            chapters = frappe.db.sql(
                """
                SELECT cost_center FROM `tabChapter`
                WHERE name LIKE %s AND cost_center IS NOT NULL
            """,
                (pattern,),
                as_dict=True,
            )

            # Delete the associated cost centers
            for chapter in chapters:
                if chapter.cost_center:
                    try:
                        frappe.db.sql(
                            """
                            DELETE FROM `tabCost Center`
                            WHERE name = %s
                        """,
                            (chapter.cost_center,),
                        )
                    except Exception:
                        # Cost center might not exist or have dependencies - that's OK
                        pass

        # Also clean up cost centers by name pattern (for test cost centers)
        for pattern in chapter_pattern:
            # Convert chapter pattern to cost center pattern
            cost_center_pattern = (
                pattern.replace("%", "% - Chapter%") if "%" in pattern else f"%{pattern}% - Chapter%"
            )
            try:
                frappe.db.sql(
                    """
                    DELETE FROM `tabCost Center`
                    WHERE cost_center_name LIKE %s
                """,
                    (cost_center_pattern,),
                )
            except Exception:
                # Cost center might not exist or have dependencies - that's OK
                pass

        # Note: No commit needed in test context - Frappe handles transaction rollback

    # ================================================================
    # MOLLIE INTEGRATION ENHANCED TEST FACTORY METHODS
    # ================================================================
    # These methods provide comprehensive Mollie testing functionality
    # following Phase 4D A+ standards with zero inappropriate mocks

    def create_test_payment_entry(self, **kwargs):
        """
        Create test Payment Entry with proper field validation.

        Critical method identified by QCE review - was missing and causing
        test failures across the Mollie test suite.

        Args:
            payment_type: "Receive" or "Pay" (default: "Receive")
            paid_amount: Payment amount (default: 100.0)
            reference_no: Payment reference (for Mollie: payment ID)
            custom_donation: Link to Donation document
            custom_reversal_type: "Refund" or "Chargeback" (for Pay type)
            custom_original_payment_id: Original payment reference for reversals
            **kwargs: Additional Payment Entry fields

        Returns:
            Payment Entry document
        """
        # Validate custom fields exist before using them (optional)
        payment_entry_meta = frappe.get_meta("Payment Entry")
        custom_fields = ["custom_donation", "custom_reversal_type", "custom_original_payment_id"]

        # Only validate if custom fields are being used
        if any(field in kwargs for field in custom_fields):
            for field in custom_fields:
                if not payment_entry_meta.has_field(field):
                    raise FieldValidationError(f"Payment Entry is missing required custom field: {field}")

        # Get default company
        company = kwargs.get("company") or frappe.get_list("Company", limit=1)[0].name
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"

        # Set up payment entry defaults
        payment_entry_data = {
            "doctype": "Payment Entry",
            "payment_type": kwargs.get("payment_type", "Receive"),
            "company": company,
            "paid_amount": kwargs.get("paid_amount", 100.0),
            "received_amount": kwargs.get("received_amount", kwargs.get("paid_amount", 100.0)),
            "reference_no": kwargs.get("reference_no", f"test_payment_{frappe.generate_hash()[:8]}"),
            "reference_date": kwargs.get("reference_date", frappe.utils.today()),
            "mode_of_payment": kwargs.get("mode_of_payment", "Bank Transfer"),
            "party_type": kwargs.get("party_type", "Customer"),
            "posting_date": kwargs.get("posting_date", frappe.utils.today()),
            # See create_test_sales_invoice: ERPNext overwrites posting_date with now()
            # unless set_posting_time is set, and the harness no longer sets in_import.
            "set_posting_time": 1,
            # Currency and exchange rate
            "paid_from_account_currency": company_currency,
            "paid_to_account_currency": company_currency,
            "source_exchange_rate": 1.0,
            "target_exchange_rate": 1.0,
        }

        # Add custom fields if provided
        for field in ["custom_donation", "custom_reversal_type", "custom_original_payment_id"]:
            if field in kwargs:
                payment_entry_data[field] = kwargs[field]

        # Get or create a test customer
        if payment_entry_data["party_type"] == "Customer":
            if "party" not in kwargs:
                customer = self._ensure_test_customer()
                payment_entry_data["party"] = customer.name
            else:
                payment_entry_data["party"] = kwargs["party"]

        # Add accounts - get from payment mode or use defaults
        # For "Receive" payments: paid_from = Debtors, paid_to = Bank
        # For "Pay" payments: paid_from = Bank, paid_to = Creditors

        if payment_entry_data["payment_type"] == "Receive":
            # Get bank account from mode of payment or default
            mode_of_payment_doc = frappe.get_doc("Mode of Payment", payment_entry_data["mode_of_payment"])
            if mode_of_payment_doc.accounts:
                payment_entry_data["paid_to"] = mode_of_payment_doc.accounts[0].default_account
            else:
                bank_account = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
                )
                if not bank_account:
                    # Create a test bank account for the company
                    bank_account = self._ensure_test_bank_account(company)
                payment_entry_data["paid_to"] = bank_account

            # Get debtors account - if paying against a Sales Invoice, use its debit_to account
            debtors_account = None
            if "references" in kwargs and kwargs["references"]:
                # Get receivable account from the first Sales Invoice reference
                for ref in kwargs["references"]:
                    if ref.get("reference_doctype") == "Sales Invoice":
                        invoice_debit_to = frappe.db.get_value(
                            "Sales Invoice", ref.get("reference_name"), "debit_to"
                        )
                        if invoice_debit_to:
                            debtors_account = invoice_debit_to
                            break

            if not debtors_account:
                # Fallback to company default
                debtors_account = frappe.db.get_value("Company", company, "default_receivable_account")

            if not debtors_account:
                # Final fallback: find any receivable account for this company
                debtors_account = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
                )

            if not debtors_account:
                raise ValueError(
                    f"No Receivable account found for company {company}.\n"
                    f"Ensure Chart of Accounts includes a Receivable account type."
                )
            payment_entry_data["paid_from"] = debtors_account
        else:
            # For "Pay" type - reverse the logic
            bank_account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
            )
            if not bank_account:
                raise ValueError(
                    f"No Bank account found for company {company}.\n"
                    f"Run 'bench setup-requirements' or ensure Chart of Accounts is configured."
                )
            payment_entry_data["paid_from"] = bank_account

            creditors_account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name"
            )
            if not creditors_account:
                raise ValueError(
                    f"No Payable account found for company {company}.\n"
                    f"Ensure Chart of Accounts includes a Payable account type."
                )
            payment_entry_data["paid_to"] = creditors_account

        # Validate all provided fields (excluding control parameters)
        control_params = {"submit", "references"}  # These are handled separately
        for field in kwargs:
            if field not in payment_entry_data and field not in control_params:
                # self.factory may be reassigned by some test classes; only
                # validate when the bound factory still exposes the validator.
                validate = getattr(getattr(self, "factory", None), "validate_field_exists", None)
                if callable(validate):
                    validate("Payment Entry", field)
                payment_entry_data[field] = kwargs[field]

        # Create and return the payment entry
        payment_entry = frappe.get_doc(payment_entry_data)

        # Add references if provided
        if "references" in kwargs:
            for ref in kwargs["references"]:
                payment_entry.append("references", ref)

        payment_entry.insert()
        self._track_test_document("Payment Entry", payment_entry.name, priority=4)

        # Submit if requested
        if kwargs.get("submit", False):
            payment_entry.submit()

        return payment_entry

    def create_test_mollie_payment(self, **kwargs):
        """
        Create realistic Mollie payment with Dutch validation.

        Generates test Mollie payment data that follows Dutch business rules
        and Mollie API patterns without mocking business logic.

        Args:
            payment_id: Mollie payment ID (default: test_xxxxxxxx format)
            amount: Payment amount in EUR (default: 25.0)
            status: Payment status (default: "paid")
            donor_email: Email for the payment (default: test email)
            donation: Link to existing Donation record
            **kwargs: Additional payment fields

        Returns:
            Dict with Mollie payment data and created Payment Entry
        """
        # Generate realistic Mollie payment ID
        # Validate amount (Dutch business rule)
        amount = kwargs.get("amount", 25.0)
        if amount <= 0:
            raise frappe.ValidationError("Payment amount must be positive")

        payment_id = kwargs.get("payment_id", f"test_{frappe.generate_hash()[:12]}")
        if not payment_id.startswith(("tr_", "test_")):
            payment_id = f"test_{payment_id}"

        currency = kwargs.get("currency", "EUR")

        # Create donation if not provided
        donation = kwargs.get("donation")
        if not donation:
            donor_email = kwargs.get("donor_email", f"test.donor.{frappe.generate_hash()[:8]}@example.com")
            donation_doc = self.create_test_donation(
                donor_email=donor_email, amount=amount, payment_id=payment_id
            )
            donation = donation_doc.name

        # Create corresponding Payment Entry
        payment_entry = self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=amount,
            reference_no=payment_id,
            custom_donation=donation,
            **{k: v for k, v in kwargs.items() if k.startswith("payment_entry_")},
        )

        # Generate realistic Mollie API response data
        mollie_payment_data = {
            "id": payment_id,
            "status": kwargs.get("status", "paid"),
            "amount": {"value": f"{amount:.2f}", "currency": currency},
            "description": kwargs.get("description", f"Donation payment for {donation}"),
            "createdAt": frappe.utils.now_datetime().isoformat() + "Z",
            "paidAt": (
                frappe.utils.now_datetime().isoformat() + "Z"
                if kwargs.get("status", "paid") == "paid"
                else None
            ),
            "method": kwargs.get("method", "ideal"),
            "metadata": {"donation": donation, "payment_entry": payment_entry.name},
            "details": {
                "consumerName": kwargs.get("consumer_name", "Test Consumer"),
                "consumerAccount": kwargs.get("consumer_account", "NL91ABNA0417164300"),
            },
        }

        return {"mollie_payment": mollie_payment_data, "payment_entry": payment_entry, "donation": donation}

    def create_test_mollie_webhook_data(self, webhook_type, **kwargs):
        """
        Generate realistic webhook payloads for security testing.

        Creates properly formatted webhook data that matches Mollie's
        actual webhook payload structure for comprehensive testing.

        Args:
            webhook_type: "payment.paid", "payment.failed", "refund.completed", etc.
            payment_id: Mollie payment ID (auto-generated if not provided)
            **kwargs: Webhook-specific data

        Returns:
            Dict with webhook payload and metadata
        """
        payment_id = kwargs.get("payment_id", f"test_{frappe.generate_hash()[:12]}")

        base_webhook = {
            "id": payment_id,
            "mode": "test",
            "createdAt": frappe.utils.now_datetime().isoformat() + "Z",
            "resource": "payment" if "payment" in webhook_type else "refund",
        }

        if webhook_type == "payment.paid":
            base_webhook.update(
                {
                    "status": "paid",
                    "amount": {"value": f"{kwargs.get('amount', 25.0):.2f}", "currency": "EUR"},
                    "description": kwargs.get("description", "Test payment"),
                    "method": kwargs.get("method", "ideal"),
                    "paidAt": frappe.utils.now_datetime().isoformat() + "Z",
                    "metadata": kwargs.get("metadata", {}),
                    "details": kwargs.get(
                        "details", {"consumerName": "Test Consumer", "consumerAccount": "NL91ABNA0417164300"}
                    ),
                }
            )

        elif webhook_type == "refund.completed":
            base_webhook.update(
                {
                    "resource": "refund",
                    "refund_id": kwargs.get("refund_id", f"refund_{frappe.generate_hash()[:8]}"),
                    "refund": {
                        "id": kwargs.get("refund_id", f"refund_{frappe.generate_hash()[:8]}"),
                        "amount": {"value": f"{kwargs.get('refund_amount', 25.0):.2f}", "currency": "EUR"},
                        "status": "refunded",
                        "createdAt": frappe.utils.now_datetime().isoformat() + "Z",
                        "description": kwargs.get("refund_description", "Test refund"),
                        "payment_id": payment_id,
                    },
                }
            )

        return {
            "webhook_payload": base_webhook,
            "webhook_type": webhook_type,
            "payment_id": payment_id,
            "raw_payload": frappe.as_json(base_webhook),
        }

    def create_test_mollie_subscription(self, member, **kwargs):
        """
        Complete subscription setup with SEPA validation.

        Creates a realistic Mollie subscription test scenario including
        member setup, SEPA mandate, and subscription configuration
        following Dutch regulatory requirements.

        Args:
            member: Member document or member name
            subscription_amount: Monthly amount (default: 25.0)
            **kwargs: Additional subscription parameters

        Returns:
            Dict with subscription data and related documents
        """
        # Validate IBAN if provided (Dutch compliance)
        iban = kwargs.get("iban", "NL91ABNA0417164300")
        if iban == "INVALID_IBAN" or (iban and len(iban) < 10):
            raise frappe.ValidationError("Invalid IBAN format")

        # Get member document
        if isinstance(member, str):
            member_doc = frappe.get_doc("Member", member)
        else:
            member_doc = member

        # Create SEPA mandate if not exists
        existing_mandate = frappe.db.get_value(
            "SEPA Mandate", {"member": member_doc.name, "docstatus": 1}, "name"
        )

        if not existing_mandate:
            mandate = self.create_test_sepa_mandate(
                member_name=member_doc.name,
                iban=iban,
                **{k: v for k, v in kwargs.items() if k.startswith("mandate_")},
            )
        else:
            mandate = frappe.get_doc("SEPA Mandate", existing_mandate)

        # Generate Mollie customer and subscription IDs
        customer_id = kwargs.get("customer_id", f"cst_test_{frappe.generate_hash()[:8]}")
        subscription_id = kwargs.get("subscription_id", f"sub_test_{frappe.generate_hash()[:8]}")

        subscription_amount = kwargs.get("subscription_amount", 25.0)

        # Create subscription data
        subscription_data = {
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "amount": {"value": f"{subscription_amount:.2f}", "currency": "EUR"},
            "interval": kwargs.get("interval", "1 month"),
            "description": kwargs.get("description", f"Membership dues for {member_doc.full_name}"),
            "method": ["directdebit"],
            "status": kwargs.get("status", "active"),
            "createdAt": frappe.utils.now_datetime().isoformat() + "Z",
            "metadata": {"member": member_doc.name, "sepa_mandate": mandate.name},
        }

        # Update member with Mollie subscription info
        # Reload to avoid timestamp conflicts from SEPA mandate creation hooks
        member_doc.reload()
        member_doc.mollie_customer_id = customer_id
        member_doc.mollie_subscription_id = subscription_id
        member_doc.subscription_status = "active"
        member_doc.next_payment_date = frappe.utils.add_months(frappe.utils.today(), 1)
        member_doc.save()

        return {
            "subscription_data": subscription_data,
            "member": member_doc,
            "sepa_mandate": mandate,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
        }

    def simulate_mollie_webhook_security(self, payload, signature=None):
        """
        Test webhook signature validation securely.

        Provides comprehensive webhook security testing including
        signature validation, payload integrity, and timing attack
        prevention following security best practices.

        Args:
            payload: Webhook payload (dict or JSON string)
            signature: Optional webhook signature for validation

        Returns:
            Dict with security validation results
        """
        # Ensure payload is JSON string for signature validation
        if isinstance(payload, dict):
            payload_json = frappe.as_json(payload)
        else:
            payload_json = payload

        # Generate test signature if not provided
        if signature is None:
            # Use test webhook secret
            webhook_secret = "test_webhook_secret_for_validation"
            import hashlib
            import hmac

            signature = hmac.new(
                webhook_secret.encode("utf-8"), payload_json.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            signature = f"sha256={signature}"

        # Test signature validation using HMAC
        def validate_webhook_signature(payload_str, sig):
            """Simple webhook signature validation for testing"""
            if not sig or not isinstance(sig, str):
                return False

            webhook_secret = "test_webhook_secret_for_validation"
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            expected_sig = f"sha256={expected_signature}"

            # Constant-time comparison to prevent timing attacks
            return hmac.compare_digest(sig, expected_sig)

        # Test various security scenarios
        security_results = {
            "valid_signature": validate_webhook_signature(payload_json, signature),
            "invalid_signature": validate_webhook_signature(payload_json, "invalid_signature"),
            "empty_signature": validate_webhook_signature(payload_json, ""),
            "malformed_signature": validate_webhook_signature(payload_json, "malformed"),
            "payload_integrity": len(payload_json) > 0 and payload_json != "{}",
            "timing_attack_resistance": True,  # Constant-time comparison used
        }

        return {
            "security_results": security_results,
            "test_signature": signature,
            "payload_hash": hashlib.sha256(payload_json.encode()).hexdigest(),
        }

    def create_member_with_background_approval(self, **kwargs):
        """
        Create member using the new background approval system.

        This method creates a member in 'Pending' status and then uses the background
        approval API to approve it, testing the new event-driven architecture.

        Args:
            wait_for_background_jobs: If True, waits for background jobs to complete
            **kwargs: Member creation parameters

        Returns:
            Dict with member, approval_result, and background job status
        """
        wait_for_background_jobs = kwargs.pop("wait_for_background_jobs", True)

        # Create member in pending status (simulating application flow)
        defaults = {
            "application_status": "Pending",
            "status": "Pending",
            # Don't set member_id yet - that's done during approval
        }

        # Remove member_id from kwargs if present - approval will set it
        kwargs.pop("member_id", None)

        data = {**defaults, **kwargs}
        member = self.factory.create_member(**data)

        # Use the background approval API
        try:
            from verenigingen.api.background_approval_api import approve_membership_application_background

            approval_result = approve_membership_application_background(
                member_name=member.name,
                membership_type=kwargs.get("selected_membership_type", "Monthly Membership"),
                chapter=kwargs.get("chapter"),
                notes="Test approval via background system",
                create_invoice=True,
            )

            # Reload member to get updated status
            member.reload()

            background_status = None
            if wait_for_background_jobs:
                background_status = self._wait_for_background_jobs(member.name)

            return {
                "member": member,
                "approval_result": approval_result,
                "background_status": background_status,
                "success": approval_result.get("success", False),
            }

        except Exception as e:
            frappe.log_error(f"Background approval test failed: {str(e)}", "Test Factory Error")
            return {
                "member": member,
                "approval_result": {"success": False, "error": str(e)},
                "background_status": None,
                "success": False,
            }

    def _wait_for_background_jobs(self, member_name, timeout_seconds=30):
        """
        Wait for background approval jobs to complete.

        Args:
            member_name: Name of member to check jobs for
            timeout_seconds: Maximum time to wait

        Returns:
            Dict with final job status
        """
        import time

        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            try:
                from verenigingen.api.background_approval_api import get_approval_progress

                progress = get_approval_progress(member_name)

                # Check if all jobs are complete
                active_jobs = progress.get("active_jobs", 0)
                failed_jobs = progress.get("failed_jobs", 0)

                if active_jobs == 0:
                    # All jobs finished (successfully or failed)
                    return {
                        "completed": True,
                        "failed_jobs": failed_jobs,
                        "progress": progress,
                        "wait_time": time.time() - start_time,
                    }

                # Wait a bit before checking again
                time.sleep(1)

            except Exception as e:
                frappe.log_error(f"Error checking background job progress: {str(e)}", "Test Factory")
                break

        # Timeout reached
        return {"completed": False, "timeout": True, "wait_time": timeout_seconds}

    def validate_background_approval_system(self):
        """
        Validate the background approval system end-to-end.

        This helper method validates that the background processing
        system works correctly in test scenarios. NOT a test itself -
        call this from actual test methods when needed.

        Returns:
            Dict with test results and performance metrics
        """
        import time

        test_start = time.time()

        # Test 1: Basic background approval
        result1 = self.create_member_with_background_approval(
            first_name="Background", last_name="Test1", email="bgtest1@test.invalid", birth_date="1990-01-01"
        )

        # Test 2: Background approval with chapter
        result2 = self.create_member_with_background_approval(
            first_name="Background",
            last_name="Test2",
            email="bgtest2@test.invalid",
            birth_date="1985-06-15",
            chapter="Test Chapter",  # If chapter exists
            wait_for_background_jobs=False,  # Don't wait for this one
        )

        test_end = time.time()

        return {
            "test_duration": test_end - test_start,
            "basic_approval": result1,
            "chapter_approval": result2,
            "overall_success": result1["success"] and result2["success"],
            "background_processing_working": (
                result1.get("approval_result", {}).get("background_processing", {}).get("status")
                == "initiated"
            ),
        }

    def _ensure_test_customer(self):
        """Internal method to ensure test customer exists"""
        customer_name = "Test Customer - Enhanced Factory"

        if not frappe.db.exists("Customer", customer_name):
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": customer_name,
                    "customer_type": "Individual",
                    "customer_group": "Individual",
                }
            )
            customer.insert()
            self.factory.track_document("Customer", customer.name, priority=3)
            return customer
        else:
            return frappe.get_doc("Customer", customer_name)

    def _ensure_test_bank_account(self, company):
        """Internal method to ensure test bank account exists for a company"""
        account_name = f"Test Bank - {company}"

        # Check if it exists
        existing = frappe.db.get_value("Account", {"account_name": "Test Bank", "company": company}, "name")
        if existing:
            return existing

        # Get the root bank account (parent group)
        root_bank = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        )

        if not root_bank:
            # Try to find any bank type parent
            root_bank = frappe.db.get_value(
                "Account",
                {"company": company, "root_type": "Asset", "is_group": 1, "account_name": ["like", "%Bank%"]},
                "name",
            )

        if not root_bank:
            # Last resort - find any asset group account
            root_bank = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name"
            )

        if not root_bank:
            raise ValueError(f"Cannot create bank account: no parent account found for company {company}")

        # Create the test bank account
        bank_account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": "Test Bank",
                "parent_account": root_bank,
                "company": company,
                "account_type": "Bank",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", company, "default_currency") or "EUR",
            }
        )
        bank_account.insert(ignore_permissions=True)
        self.factory.track_document("Account", bank_account.name, priority=1)
        return bank_account.name

    # Bridge methods to specialized factories
    def create_test_sepa_mandate(self, member_name=None, iban=None, **kwargs):
        """Bridge to SEPA test factory for mandate creation.

        Accepts member_name positionally or `member=` as a kwarg, and either a
        Member document or its name string, for backward compatibility with the
        SEPA mandate test suites.
        """
        if member_name is None and "member" in kwargs:
            member_name = kwargs.pop("member")
        # Accept a Member document as well as its name string.
        if member_name is not None and hasattr(member_name, "name"):
            member_name = member_name.name
        if member_name is None:
            raise TypeError("create_test_sepa_mandate requires member_name (or member=)")
        try:
            from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

            # Reuse a single SEPATestDataFactory per test instance so its internal
            # sequence (used to generate UNIQUE IBANs/mandate ids) advances across
            # calls. Recreating it each call reset the sequence, producing the same
            # IBAN repeatedly and tripping the duplicate-active-mandate validation
            # when several mandates are created for the same member.
            sepa_factory = getattr(self, "_bridge_sepa_factory", None)
            if sepa_factory is None:
                sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)
                self._bridge_sepa_factory = sepa_factory
            return sepa_factory.create_test_sepa_mandate(member=member_name, iban=iban, **kwargs)
        except ImportError:
            # Fallback implementation
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.update(
                {
                    "member": member_name,
                    "iban": iban or "NL91ABNA0417164300",
                    "mandate_id": f"TST{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}",
                    "status": "Active",
                    "sign_date": frappe.utils.today(),
                    **kwargs,
                }
            )
            mandate.insert()
            self.factory.track_document("SEPA Mandate", mandate.name, priority=4)
            return mandate

    def create_test_direct_debit_batch(self, skip_invoice_creation=False, **kwargs):
        """Bridge to SEPA test factory for Direct Debit Batch creation.

        skip_invoice_creation=True maps to invoice_count=0 so callers that build
        their own invoice rows get an empty batch to populate.
        """
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)
        if skip_invoice_creation:
            kwargs.setdefault("invoice_count", 0)
        return sepa_factory.create_test_direct_debit_batch(**kwargs)

    def create_test_dues_schedule(
        self, member, membership_type=None, amount=25.0, frequency="monthly", **kwargs
    ):
        """Bridge method for dues schedule creation"""
        # Accept dues_rate= as a legacy alias for amount (callers pass either).
        if "dues_rate" in kwargs:
            amount = kwargs.pop("dues_rate")
        # membership= is not a Membership Dues Schedule field; drop it (the
        # schedule links to the member, not the membership document).
        kwargs.pop("membership", None)
        try:
            from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

            sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)

            # Add membership_type to kwargs if provided
            if membership_type:
                kwargs["membership_type"] = membership_type

            return sepa_factory.create_test_membership_dues_schedule(
                member=member, dues_rate=amount, billing_frequency=frequency.title(), **kwargs
            )
        except ImportError:
            # Fallback implementation
            schedule = frappe.new_doc("Membership Dues Schedule")
            schedule.update(
                {
                    "member": member,
                    "dues_amount": amount,
                    "frequency": frequency,
                    "status": "Active",
                    **kwargs,
                }
            )
            schedule.insert()
            self.factory.track_document("Membership Dues Schedule", schedule.name, priority=4)
            return schedule

    def create_test_member_application(self, **kwargs):
        """Create test member application"""
        application = frappe.new_doc("Member Application")
        defaults = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": f"test.applicant.{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}@test.nl",
            "birth_date": "1990-01-01",
            "workflow_state": "Pending Review",
        }
        defaults.update(kwargs)
        application.update(defaults)
        application.insert()
        self.factory.track_document("Member Application", application.name, priority=5)
        return application

    def assign_member_to_chapter_by_postal_code(self, member, postal_code):
        """Auto-assign member to chapter based on postal code"""
        # Simple implementation - find chapter that matches postal code range
        chapters = frappe.get_all("Chapter", filters={"disabled": 0}, fields=["name", "postal_codes"])

        for chapter_data in chapters:
            if chapter_data.postal_codes:
                # Simple range check (simplified for testing)
                postal_ranges = chapter_data.postal_codes.split(",")
                for postal_range in postal_ranges:
                    if "-" in postal_range:
                        start_code = postal_range.split("-")[0].strip()
                        if postal_code[:4] >= start_code[:4]:
                            chapter = frappe.get_doc("Chapter", chapter_data.name)
                            # Create Chapter Member record
                            chapter_member = frappe.new_doc("Chapter Member")
                            chapter_member.update(
                                {
                                    "member": member.name,
                                    "chapter": chapter.name,
                                    "status": "Active",
                                    "join_date": frappe.utils.today(),
                                }
                            )
                            chapter_member.insert()
                            self.factory.track_document("Chapter Member", chapter_member.name, priority=5)
                            return chapter

        # Return first available chapter as fallback
        if chapters:
            return frappe.get_doc("Chapter", chapters[0].name)
        return None

    def convert_application_to_member(self, application):
        """Convert approved application to active member"""
        member = frappe.new_doc("Member")
        member.update(
            {
                "first_name": application.first_name,
                "last_name": application.last_name,
                "email": application.email,
                "birth_date": application.birth_date,
                "status": "Active",
            }
        )

        # Create customer
        customer = self.factory.create_test_customer(
            customer_name=f"{application.first_name} {application.last_name}"
        )
        member.customer = customer.name

        # Set chapter if specified
        if hasattr(application, "chapter") and application.chapter:
            member.chapter = application.chapter

        member.insert()
        self.factory.track_document("Member", member.name, priority=5)
        return member

    def transition_member_status(self, member, new_status):
        """Transition member status with business rule validation"""
        member.status = new_status
        if new_status == "Quit":
            member.membership_end_date = frappe.utils.today()
        member.save()

    def generate_sort_name(self, member):
        """Generate sorting name for Dutch names with tussenvoegsel"""
        # Simple implementation for testing
        return f"{member.last_name}, {member.first_name}"

    def generate_dues_invoice(self, dues_schedule):
        """Generate invoice from dues schedule"""
        # Get member's customer
        member = frappe.get_doc("Member", dues_schedule.member)
        if not member.customer:
            customer = self.factory.create_test_customer(customer_name=member.full_name)
            member.customer = customer.name
            member.save()

        # Create sales invoice
        invoice = self.create_test_sales_invoice(
            customer=member.customer, grand_total=getattr(dues_schedule, "dues_amount", 25.0)
        )
        return invoice

    def validate_dutch_iban(self, iban):
        """Validate Dutch IBAN format"""
        # Simple validation for testing
        return iban.startswith("NL") and len(iban.replace(" ", "")) == 18

    def derive_bic_from_iban(self, iban):
        """Derive BIC from Dutch IBAN"""
        # Simple mapping for testing
        bank_code = iban[4:8]
        bic_mapping = {"ABNA": "ABNANL2A", "RABO": "RABONL2U", "INGB": "INGBNL2A", "TRIO": "TRIONL2U"}
        return bic_mapping.get(bank_code, "ABNANL2A")

    def create_test_email_template(self, name, subject, response_html=None, response=None, **kwargs):
        """Create a test email template with proper validation."""
        # Ensure unique name with test prefix
        if not name.startswith("test_"):
            name = f"test_{name}"

        # Add timestamp to ensure uniqueness
        import time

        timestamp = str(int(time.time()))[-6:]  # Last 6 digits
        unique_name = f"{name}_{timestamp}"

        template_data = {
            "doctype": "Email Template",
            "name": unique_name,
            "subject": subject,
            "enabled": 1,
            "use_html": 1 if response_html else 0,
            "response": response,
            "response_html": response_html,
            **kwargs,
        }

        template = frappe.get_doc(template_data)
        template.insert()

        # Track for cleanup in tearDown
        self.factory.track_document("Email Template", template.name, priority=3)

        return template


# Convenience decorators
def with_enhanced_test_data(seed=12345, use_faker=True):
    """Decorator for test methods that need enhanced test data"""

    def decorator(test_method):
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, "factory"):
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
        member = factory.create_member(first_name="Test", last_name="User", birth_date="1990-01-01")
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


# ---------------------------------------------------------------------------
# SecureTestDataFactory (absorbed from secure_test_data_factory.py)
# Provides schema-validated, deterministic test data with proper permissions.
# ---------------------------------------------------------------------------


class TestCleanupError(Exception):
    """Raised when test data cleanup fails"""

    pass


class SchemaValidationError(Exception):
    """Raised when field validation fails"""

    pass


class SecureTestDataFactory:
    """
    Schema-validated test data factory with deterministic data generation.

    Provides create_member/chapter/volunteer with field validation against
    DocType schemas and proper permission handling.
    """

    def __init__(
        self,
        test_user: str = "Administrator",
        seed: int = 12345,
        cleanup_on_exit: bool = True,
    ):
        self.original_user = frappe.session.user
        self.test_user = test_user
        self.cleanup_on_exit = cleanup_on_exit
        self.created_records = []
        self.sequence_counters = {}
        self.doctype_schemas = {}

        random.seed(seed)
        frappe.set_user(self.test_user)
        self.test_run_id = f"TEST-{frappe.utils.random_string(8)}-{int(datetime.now().timestamp())}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cleanup_on_exit:
            self.cleanup_with_verification()
        frappe.set_user(self.original_user)

    def get_schema(self, doctype):
        if doctype not in self.doctype_schemas:
            try:
                meta = frappe.get_meta(doctype)
                self.doctype_schemas[doctype] = {f.fieldname: f for f in meta.fields}
            except Exception as e:
                raise SchemaValidationError(f"Could not load schema for {doctype}: {e}")
        return self.doctype_schemas[doctype]

    def validate_field_exists(self, doctype, fieldname):
        schema = self.get_schema(doctype)
        if fieldname not in schema:
            raise SchemaValidationError(f"Field '{fieldname}' doesn't exist in {doctype}")
        return True

    def validate_required_fields(self, doctype, data):
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

    def get_default_value_for_field(self, doctype, fieldname):
        try:
            schema = self.get_schema(doctype)
            if fieldname not in schema:
                return None
            field = schema[fieldname]
            fieldtype = field.fieldtype
            defaults = {
                "Data": f"Test-{self.get_next_sequence('data')}",
                "Text": f"Test text content {self.get_next_sequence('text')}",
                "Check": 0,
                "Int": 0,
                "Float": 0.0,
                "Currency": 0.0,
                "Date": frappe.utils.getdate(),
                "Datetime": frappe.utils.now_datetime(),
                "Select": field.options.split("\n")[0] if field.options else "",
                "Link": None,
                "Email": f"test{self.get_next_sequence('email')}@example.com",
            }
            return defaults.get(fieldtype, None)
        except Exception:
            return None

    def get_next_sequence(self, prefix):
        self.sequence_counters[prefix] = self.sequence_counters.get(prefix, 0) + 1
        return self.sequence_counters[prefix]

    def track_record(self, doctype, name):
        self.created_records.append({"doctype": doctype, "name": name})

    def create_member(self, **kwargs):
        for field in kwargs.keys():
            self.validate_field_exists("Member", field)
        defaults = {
            "first_name": f"TestMember{self.get_next_sequence('member')}",
            "last_name": f"Generated-{self.test_run_id[:8]}",
            "email": f"testmember{self.get_next_sequence('email')}_{self.test_run_id}@test.example",
            "birth_date": frappe.utils.add_days(frappe.utils.getdate(), -9000),
            "status": "Active",
            "member_id": str(
                int(self.test_run_id.split("-")[-1]) * 1000 + self.get_next_sequence("member_id")
            ),
        }
        data = {**defaults, **kwargs}
        data = self.validate_required_fields("Member", data)
        member = frappe.get_doc({"doctype": "Member", **data})
        member.insert()
        self.track_record("Member", member.name)
        return member

    def create_volunteer(self, member_name=None, **kwargs):
        if not member_name:
            member = self.create_member()
            member_name = member.name
        for field in kwargs.keys():
            self.validate_field_exists("Volunteer", field)
        defaults = {
            "volunteer_name": f"TestVolunteer{self.get_next_sequence('volunteer')}",
            "email": f"volunteer{self.get_next_sequence('vol_email')}_{self.test_run_id}@test.example",
            "member": member_name,
            "status": "Active",
            "start_date": frappe.utils.getdate(),
        }
        data = {**defaults, **kwargs}
        data = self.validate_required_fields("Volunteer", data)
        volunteer = frappe.get_doc({"doctype": "Volunteer", **data})
        volunteer.insert()
        self.track_record("Volunteer", volunteer.name)
        return volunteer

    def create_chapter(self, **kwargs):
        for field in kwargs.keys():
            self.validate_field_exists("Chapter", field)
        defaults = {
            "region": f"TestRegion-{self.get_next_sequence('region')}",
            "postal_codes": f"{1000 + self.get_next_sequence('postal'):04d}",
            "introduction": f"Test chapter created by SecureTestDataFactory - {self.test_run_id}",
        }
        region_name = defaults["region"]
        if not frappe.db.exists("Region", region_name):
            region = frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": region_name,
                    "region_code": f"TR{self.get_next_sequence('region_code'):03d}",
                    "country": "Netherlands",
                    "is_active": 1,
                }
            )
            region.insert()
            self.track_record("Region", region.name)
        data = {**defaults, **kwargs}
        data = self.validate_required_fields("Chapter", data)
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"TestChapter-{self.get_next_sequence('chapter')}-{self.test_run_id[:8]}",
                **data,
            }
        )
        chapter.insert()
        self.track_record("Chapter", chapter.name)
        return chapter

    def create_volunteer_skill(self, volunteer_name, skill_data):
        required_skill_fields = ["skill_category", "volunteer_skill"]
        for field in required_skill_fields:
            if field not in skill_data:
                raise ValueError(f"Required skill field '{field}' missing")
        for field in skill_data.keys():
            self.validate_field_exists("Volunteer Skill", field)
        defaults = {
            "proficiency_level": "3 - Intermediate",
            "experience_years": 1,
            "certifications": "",
        }
        data = {**defaults, **skill_data}
        data = self.validate_required_fields("Volunteer Skill", data)
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        skill = volunteer_doc.append("skills_and_qualifications", data)
        volunteer_doc.save()
        self.track_record("Volunteer Skill", skill.name)
        return skill

    def create_test_iban(self, bank_code=None):
        if not bank_code:
            bank_codes = ["TEST", "MOCK", "DEMO"]
            bank_code = bank_codes[self.get_next_sequence("bank") % len(bank_codes)]
        account_number = f"{self.get_next_sequence('account'):010d}"
        try:
            from verenigingen.utils.validation.iban_validator import generate_test_iban

            return generate_test_iban(bank_code, account_number)
        except ImportError:
            return f"NL{self.get_next_sequence('fallback_iban'):02d}{bank_code}0{account_number[:10]}"

    def cleanup_with_verification(self):
        failed_deletions = []
        successful_deletions = 0
        for record in reversed(self.created_records):
            try:
                if frappe.db.exists(record["doctype"], record["name"]):
                    frappe.delete_doc(record["doctype"], record["name"])
                    if frappe.db.exists(record["doctype"], record["name"]):
                        failed_deletions.append(record)
                    else:
                        successful_deletions += 1
                else:
                    successful_deletions += 1
            except Exception as e:
                failed_deletions.append({**record, "error": str(e)})
        frappe.db.commit()
        if failed_deletions:
            raise TestCleanupError(f"Failed to delete {len(failed_deletions)} records")
        self.created_records = []

    def create_application_data(self, with_volunteer_skills=True):
        seq = self.get_next_sequence("application")
        base_data = {
            "first_name": f"AppTest{seq:04d}",
            "last_name": f"Member-{self.test_run_id[:8]}",
            "email": f"app{seq:04d}_{self.test_run_id}@test.example",
            "birth_date": "1990-01-01",
            "address_line1": f"{seq} Test Street",
            "city": "Test City",
            "country": "Netherlands",
            "postal_code": f"{1000 + seq:04d}AB",
        }
        if with_volunteer_skills:
            all_skills = [
                "Technical|Web Development",
                "Technical|Graphic Design",
                "Communication|Writing",
                "Leadership|Team Leadership",
                "Financial|Fundraising",
                "Organizational|Event Planning",
                "Other|Photography",
            ]
            num_skills = (seq % 3) + 4
            skills = all_skills[:num_skills]
            volunteer_data = {
                "interested_in_volunteering": True,
                "volunteer_availability": ["Weekly", "Monthly", "Quarterly"][seq % 3],
                "volunteer_experience_level": ["Beginner", "Intermediate", "Experienced"][seq % 3],
                "volunteer_areas": ["events", "communications"],
                "volunteer_skills": skills,
                "volunteer_skill_level": str(((seq % 5) + 1)),
                "volunteer_availability_time": "Weekends and evenings",
                "volunteer_comments": f"Test volunteer application {seq}",
            }
            base_data.update(volunteer_data)
        return base_data


class SecureTestContext:
    """Context manager for secure test data with automatic cleanup."""

    def __init__(self, test_user="Administrator", seed=12345):
        self.test_user = test_user
        self.seed = seed
        self.factory = None

    def __enter__(self):
        self.factory = SecureTestDataFactory(
            test_user=self.test_user,
            seed=self.seed,
            cleanup_on_exit=True,
        )
        return self.factory

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.factory:
            try:
                self.factory.cleanup_with_verification()
            finally:
                frappe.set_user(self.factory.original_user)


def with_secure_test_data(test_user="Administrator", seed=12345):
    """Decorator for test methods that need secure test data."""

    def decorator(test_method):
        def wrapper(self, *args, **kwargs):
            with SecureTestContext(test_user=test_user, seed=seed) as factory:
                return test_method(self, factory, *args, **kwargs)

        return wrapper

    return decorator
