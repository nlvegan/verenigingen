# Service Migration Guide

## Overview

This guide provides step-by-step instructions for migrating existing Verenigingen code to the new service infrastructure. The migration follows the proven "literal extraction" pattern - moving code without rewrites to maintain safety and compatibility.

## Migration Strategy

### Phase-Based Approach

1. **Assessment Phase**: Identify code suitable for migration
2. **Extraction Phase**: Literal code extraction into service classes
3. **Integration Phase**: Register services with the infrastructure
4. **Validation Phase**: Test and validate functionality
5. **Optimization Phase**: Enhance with service infrastructure features

## Pre-Migration Assessment

### Identifying Migration Candidates

#### ✅ **Good Candidates for Migration**

```python
# 1. Business logic functions (>50 lines)
def process_membership_application(application_data):
    # Complex business logic
    # Multiple validation steps
    # External service calls
    # Data transformations
    pass

# 2. Data access patterns with multiple queries
def get_member_dashboard_data(member_name):
    member = frappe.get_doc("Member", member_name)
    memberships = frappe.get_all("Membership", filters={"member": member_name})
    # Multiple related data fetches
    pass

# 3. External API integrations
def sync_with_eboekhouden(invoice_data):
    # External API calls
    # Error handling
    # Rate limiting logic
    pass

# 4. Calculation-heavy functions
def calculate_complex_membership_fees(member_data, chapter_data):
    # Mathematical calculations
    # Business rule applications
    # Fee computations
    pass
```

#### ❌ **Avoid Migrating**

```python
# 1. Simple utility functions (<10 lines)
def format_postal_code(postal_code):
    return postal_code.replace(" ", "").upper()

# 2. Frappe framework hooks
def validate(doc, method):
    # Keep as hooks
    pass

# 3. DocType controller methods
def before_save(self):
    # Keep in DocType controllers
    pass

# 4. Single-line operations
def get_member_email(member_name):
    return frappe.db.get_value("Member", member_name, "email")
```

### Migration Assessment Checklist

```python
def assess_migration_candidate(function_name, file_path):
    """Assessment checklist for migration candidates."""
    criteria = {
        "line_count": 0,          # >50 lines preferred
        "complexity": "simple",   # complex/medium/simple
        "external_deps": False,   # has external dependencies
        "business_logic": False,  # contains business rules
        "data_access": False,     # multiple database operations
        "error_handling": False,  # has error handling
        "reusability": False,     # used in multiple places
    }

    # Score: 0-10 (>6 recommended for migration)
    migration_score = calculate_migration_score(criteria)
    return migration_score > 6
```

## Step-by-Step Migration Process

### Step 1: Code Extraction

#### Example: Migrating Member Processing Logic

**Before (in member.py):**
```python
def process_new_member_onboarding(member_name, chapter_assignment=None):
    """Process new member onboarding workflow."""
    try:
        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Validate member data
        if not member.email:
            frappe.throw("Email is required for onboarding")

        # Create customer record
        customer = create_customer_for_member(member)

        # Assign to chapter
        if chapter_assignment:
            assign_member_to_chapter(member, chapter_assignment)

        # Setup SEPA mandate if needed
        if member.payment_method == "Direct Debit":
            setup_sepa_mandate(member, customer)

        # Send welcome communications
        send_welcome_package(member)

        # Create initial membership
        create_initial_membership(member)

        return {
            "success": True,
            "member_name": member_name,
            "customer_id": customer.name,
            "onboarding_complete": True
        }

    except Exception as e:
        frappe.log_error(f"Member onboarding failed: {str(e)}", "Member Onboarding")
        return {
            "success": False,
            "error": str(e)
        }

# Helper functions
def create_customer_for_member(member):
    # Customer creation logic
    pass

def assign_member_to_chapter(member, chapter):
    # Chapter assignment logic
    pass

def setup_sepa_mandate(member, customer):
    # SEPA setup logic
    pass

def send_welcome_package(member):
    # Communication logic
    pass

def create_initial_membership(member):
    # Membership creation logic
    pass
```

**After (literal extraction to service):**
```python
# File: verenigingen/services/member/member_onboarding_service.py
from verenigingen.services.infrastructure.base_service import StatefulService

class MemberOnboardingService(StatefulService):
    """Service for processing new member onboarding workflows."""

    def __init__(self, service_name: str = None):
        super().__init__(service_name or "member_onboarding")

    def process_new_member_onboarding(self, member_name: str, chapter_assignment=None) -> Dict[str, Any]:
        """Process new member onboarding workflow."""
        try:
            # LITERAL EXTRACTION - same logic as before
            member = frappe.get_doc("Member", member_name)

            if not member.email:
                return self.create_result(
                    success=False,
                    error="Email is required for onboarding",
                    error_code="MISSING_EMAIL"
                )

            # Create customer record
            customer = self._create_customer_for_member(member)

            # Assign to chapter
            if chapter_assignment:
                self._assign_member_to_chapter(member, chapter_assignment)

            # Setup SEPA mandate if needed
            if member.payment_method == "Direct Debit":
                self._setup_sepa_mandate(member, customer)

            # Send welcome communications
            self._send_welcome_package(member)

            # Create initial membership
            self._create_initial_membership(member)

            return self.create_result(
                success=True,
                data={
                    "member_name": member_name,
                    "customer_id": customer.name,
                    "onboarding_complete": True
                }
            )

        except Exception as e:
            frappe.log_error(f"Member onboarding failed: {str(e)}", "Member Onboarding")
            return self.create_result(
                success=False,
                error=str(e),
                context={"member_name": member_name}
            )

    # LITERAL EXTRACTION of helper methods (same code, private methods)
    def _create_customer_for_member(self, member):
        # EXACT same logic as before
        pass

    def _assign_member_to_chapter(self, member, chapter):
        # EXACT same logic as before
        pass

    def _setup_sepa_mandate(self, member, customer):
        # EXACT same logic as before
        pass

    def _send_welcome_package(self, member):
        # EXACT same logic as before
        pass

    def _create_initial_membership(self, member):
        # EXACT same logic as before
        pass
```

### Step 2: Service Registration

```python
# File: verenigingen/services/member/__init__.py
from verenigingen.services.infrastructure.service_factory import get_service_factory
from .member_onboarding_service import MemberOnboardingService

def register_member_services():
    """Register all member-related services."""
    factory = get_service_factory()

    # Register onboarding service as singleton (maintains state)
    factory.register_service(
        name="member_onboarding",
        service_class=MemberOnboardingService,
        config={
            "enable_metrics": True,
            "health_check_interval": 60
        },
        singleton=True
    )

# Call during app initialization
register_member_services()
```

### Step 3: Update Usage Points

**Before (direct function calls):**
```python
# In member.py or other files
result = process_new_member_onboarding("MEMBER-001", "Chapter-Amsterdam")
```

**After (service-based calls):**
```python
# In member.py or other files
from verenigingen.services.infrastructure.service_factory import get_service_factory

def trigger_member_onboarding(member_name, chapter_assignment=None):
    """Trigger member onboarding via service."""
    factory = get_service_factory()
    onboarding_service = factory.get_service("member_onboarding")

    if not onboarding_service:
        frappe.throw("Member onboarding service not available")

    return onboarding_service.process_new_member_onboarding(member_name, chapter_assignment)
```

### Step 4: Add API Endpoints

```python
# File: vereinigengen/api/member_onboarding.py
from verenigingen.utils.security_decorators import standard_api
from vereinigengen.utils.security_enums import OperationType
from verenigingen.services.infrastructure.service_factory import get_service_factory

@standard_api(operation_type=OperationType.MEMBER_MANAGEMENT)
def process_member_onboarding_api(member_name: str, chapter_assignment: str = None) -> Dict[str, Any]:
    """API endpoint for member onboarding."""
    factory = get_service_factory()
    service = factory.get_service("member_onboarding")

    if not service:
        return {"success": False, "error": "Service not available"}

    return service.process_new_member_onboarding(member_name, chapter_assignment)
```

## Migration Patterns by Service Type

### Pattern 1: Data Processing Services

#### Candidate Identification
```python
# Functions with multiple database operations
def get_member_financial_summary(member_name):
    member = frappe.get_doc("Member", member_name)
    invoices = frappe.get_all("Sales Invoice", filters={"customer": member.customer})
    payments = frappe.get_all("Payment Entry", filters={"party": member.customer})
    # Multiple queries and data aggregation
```

#### Migration Template
```python
class MemberFinancialService(DataService):
    """Service for member financial data operations."""

    def get_member_financial_summary(self, member_name: str) -> Dict[str, Any]:
        """Get comprehensive financial summary for member."""
        try:
            # Validate fields before use
            member_fields = ["name", "customer", "full_name"]
            validation_result = self.validate_query_fields("Member", member_fields)
            if not validation_result["success"]:
                return self.create_result(
                    success=False,
                    error="Field validation failed",
                    context=validation_result["errors"]
                )

            # LITERAL EXTRACTION of original logic
            member = frappe.get_doc("Member", member_name)
            invoices = self.safe_query(
                "Sales Invoice",
                fields=["name", "grand_total", "outstanding_amount"],
                filters={"customer": member.customer}
            )
            # ... rest of original logic

            return self.create_result(
                success=True,
                data={"summary": financial_data}
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error=str(e),
                context={"member_name": member_name}
            )
```

### Pattern 2: Calculation Services

#### Candidate Identification
```python
# Complex calculation functions
def calculate_membership_dues_with_discounts(member_data, chapter_data, period_data):
    # Complex business rules
    # Mathematical calculations
    # Discount applications
    # Multi-step computations
```

#### Migration Template
```python
class MembershipDuesCalculationService(StatelessService):
    """Service for membership dues calculations."""

    def calculate_dues_with_discounts(self, member_data: dict, chapter_data: dict, period_data: dict) -> Dict[str, Any]:
        """Calculate membership dues with all applicable discounts."""
        try:
            # Input validation
            required_fields = ["member_type", "base_fee"]
            if not all(field in member_data for field in required_fields):
                return self.create_result(
                    success=False,
                    error="Missing required member data fields",
                    context={"required": required_fields, "provided": list(member_data.keys())}
                )

            # LITERAL EXTRACTION of calculation logic
            base_fee = member_data["base_fee"]
            member_type = member_data["member_type"]

            # Apply discounts (same logic as original)
            discount_rate = self._calculate_discount_rate(member_type, chapter_data)
            discounted_fee = base_fee * (1 - discount_rate)

            # Apply period adjustments (same logic as original)
            final_fee = self._apply_period_adjustments(discounted_fee, period_data)

            return self.create_result(
                success=True,
                data={
                    "base_fee": base_fee,
                    "discount_rate": discount_rate,
                    "discounted_fee": discounted_fee,
                    "final_fee": final_fee,
                    "calculation_details": self._get_calculation_breakdown()
                }
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error=str(e),
                context={"member_data": member_data}
            )

    def _calculate_discount_rate(self, member_type, chapter_data):
        # LITERAL EXTRACTION of original discount logic
        pass

    def _apply_period_adjustments(self, fee, period_data):
        # LITERAL EXTRACTION of original period logic
        pass
```

### Pattern 3: External Integration Services

#### Candidate Identification
```python
# Functions with external API calls
def sync_invoice_to_eboekhouden(invoice_data):
    # API authentication
    # Data transformation
    # HTTP requests
    # Error handling
    # Retry logic
```

#### Migration Template
```python
class EboekhoudenIntegrationService(APIService):
    """Service for eBoekhouden API integration."""

    def sync_invoice(self, invoice_data: dict) -> Dict[str, Any]:
        """Sync invoice data to eBoekhouden."""
        try:
            # LITERAL EXTRACTION with enhanced error handling
            api_url = self._get_api_endpoint("invoices")
            headers = self._get_api_headers()

            # Transform data (same logic as original)
            transformed_data = self._transform_invoice_data(invoice_data)

            # Make API call with retry logic
            response = self._make_api_request(
                method="POST",
                url=api_url,
                headers=headers,
                data=transformed_data,
                timeout=30
            )

            # Process response (same logic as original)
            if response.status_code == 200:
                sync_result = self._process_api_response(response.json())
                return self.create_result(
                    success=True,
                    data=sync_result
                )
            else:
                return self.create_result(
                    success=False,
                    error=f"API call failed with status {response.status_code}",
                    context={"response": response.text}
                )

        except Exception as e:
            return self.create_result(
                success=False,
                error=str(e),
                context={"invoice_data": invoice_data}
            )

    def _transform_invoice_data(self, invoice_data):
        # LITERAL EXTRACTION of transformation logic
        pass

    def _make_api_request(self, method, url, headers, data, timeout):
        # LITERAL EXTRACTION with added retry logic
        import requests
        return requests.request(method, url, headers=headers, json=data, timeout=timeout)
```

## Testing Migrated Services

### Test Migration Template

**Before (function testing):**
```python
def test_member_onboarding():
    # Create test member
    member = create_test_member()

    # Test function directly
    result = process_new_member_onboarding(member.name)

    # Assert results
    assert result["success"] == True
```

**After (service testing):**
```python
class TestMemberOnboardingService(EnhancedTestCase):
    """Test cases for migrated member onboarding service."""

    def setUp(self):
        super().setUp()
        self.factory = get_service_factory()
        self.onboarding_service = self.factory.get_service("member_onboarding")

    def test_member_onboarding_success(self):
        """Test successful member onboarding."""
        # Create test member using Enhanced Test Factory
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            email="test@example.com"
        )

        # Test service method
        result = self.onboarding_service.process_new_member_onboarding(member.name)

        # Validate service response format
        self.assertTrue(result["success"])
        self.assertIn("data", result)
        self.assertEqual(result["data"]["member_name"], member.name)

    def test_member_onboarding_missing_email(self):
        """Test onboarding failure with missing email."""
        # Create member without email
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            email=""  # Missing email
        )

        # Test service error handling
        result = self.onboarding_service.process_new_member_onboarding(member.name)

        # Validate error response
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["error_code"], "MISSING_EMAIL")

    def test_service_health_monitoring(self):
        """Test that service health monitoring works."""
        # Check service health
        self.assertTrue(self.onboarding_service.is_healthy())

        # Get service metrics
        metrics = self.onboarding_service.get_metrics()
        self.assertIsInstance(metrics, dict)
```

## Migration Safety Checklist

### Pre-Migration Validation

- [ ] **Backup Original Code**: Create git branch before changes
- [ ] **Identify Dependencies**: Map all functions that call the target code
- [ ] **Test Coverage**: Ensure existing tests cover the functionality
- [ ] **Field Validation**: Verify all DocType fields used are valid
- [ ] **Security Review**: Check permission requirements

### During Migration Validation

- [ ] **Literal Extraction**: No logic changes during extraction
- [ ] **Error Handling**: Maintain or improve error handling
- [ ] **Return Format**: Use service result format consistently
- [ ] **Logging**: Preserve or enhance logging
- [ ] **Configuration**: Extract hardcoded values to configuration

### Post-Migration Validation

- [ ] **Functionality Testing**: All original functionality works
- [ ] **Performance Testing**: No performance regression
- [ ] **Integration Testing**: All dependent code works
- [ ] **Health Monitoring**: Service health checks work
- [ ] **Error Scenarios**: Error handling works correctly

## Common Migration Pitfalls

### 1. Changing Logic During Migration

❌ **Wrong:**
```python
# Original function
def calculate_fee(base_amount):
    return base_amount * 1.21  # 21% VAT

# Migration with logic change (WRONG!)
class FeeService(StatelessService):
    def calculate_fee(self, base_amount):
        vat_rate = 0.21  # "Improving" the code
        return base_amount * (1 + vat_rate)
```

✅ **Correct:**
```python
# Literal extraction - same logic
class FeeService(StatelessService):
    def calculate_fee(self, base_amount):
        return base_amount * 1.21  # EXACT same calculation
```

### 2. Breaking Function Signatures

❌ **Wrong:**
```python
# Original function
def process_member(member_name, chapter=None, send_email=True):
    pass

# Migration breaking signature (WRONG!)
class MemberService(StatelessService):
    def process_member(self, member_data: dict):  # Changed signature!
        pass
```

✅ **Correct:**
```python
# Preserve original signature
class MemberService(StatelessService):
    def process_member(self, member_name: str, chapter=None, send_email=True):
        # Same signature, same behavior
        pass
```

### 3. Missing Error Context

❌ **Wrong:**
```python
class BadService(StatelessService):
    def process_data(self, data):
        try:
            # ... processing ...
            return self.create_result(success=True, data=result)
        except Exception as e:
            return self.create_result(success=False, error=str(e))  # Missing context!
```

✅ **Correct:**
```python
class GoodService(StatelessService):
    def process_data(self, data):
        try:
            # ... processing ...
            return self.create_result(success=True, data=result)
        except Exception as e:
            return self.create_result(
                success=False,
                error=str(e),
                context={"input_data": data, "operation": "process_data"}  # Rich context
            )
```

## Rollback Strategy

### Preparation for Rollback

```python
# Keep original function as backup during transition
def process_new_member_onboarding_legacy(member_name, chapter_assignment=None):
    """Legacy function - keep during migration period."""
    # Original implementation unchanged
    pass

# New service-based wrapper
def process_new_member_onboarding(member_name, chapter_assignment=None):
    """Main function - routes to service or legacy based on configuration."""

    # Configuration flag for gradual rollout
    use_service_infrastructure = frappe.conf.get("use_member_onboarding_service", False)

    if use_service_infrastructure:
        try:
            factory = get_service_factory()
            service = factory.get_service("member_onboarding")

            if service and service.is_healthy():
                result = service.process_new_member_onboarding(member_name, chapter_assignment)
                if result["success"]:
                    return result["data"]
                else:
                    # Fallback to legacy on service error
                    frappe.log_error(f"Service failed, using legacy: {result['error']}", "Migration Fallback")
                    return process_new_member_onboarding_legacy(member_name, chapter_assignment)
            else:
                # Service not available, use legacy
                return process_new_member_onboarding_legacy(member_name, chapter_assignment)

        except Exception as e:
            # Any service error, fallback to legacy
            frappe.log_error(f"Service infrastructure error, using legacy: {str(e)}", "Migration Fallback")
            return process_new_member_onboarding_legacy(member_name, chapter_assignment)
    else:
        # Configuration disabled, use legacy
        return process_new_member_onboarding_legacy(member_name, chapter_assignment)
```

### Gradual Migration Configuration

```python
# site_config.json additions for gradual rollout
{
    "use_member_onboarding_service": false,  # Start disabled
    "service_migration_log_level": "INFO",
    "service_fallback_enabled": true
}

# Enable for testing
{
    "use_member_onboarding_service": true,   # Enable for testing
    "service_migration_log_level": "DEBUG",
    "service_fallback_enabled": true
}

# Full migration
{
    "use_member_onboarding_service": true,   # Fully enabled
    "service_migration_log_level": "ERROR",
    "service_fallback_enabled": false       # No fallback needed
}
```

## Migration Timeline Template

### Week 1: Assessment and Planning
- [ ] Identify migration candidates using assessment criteria
- [ ] Create migration priority list
- [ ] Set up git branch for migration work
- [ ] Document current functionality and test coverage

### Week 2: First Service Migration
- [ ] Select highest-priority, lowest-risk candidate
- [ ] Perform literal extraction to service
- [ ] Create comprehensive tests
- [ ] Deploy with fallback mechanism enabled

### Week 3: Validation and Iteration
- [ ] Monitor service performance and errors
- [ ] Collect feedback from team
- [ ] Refine migration process based on learnings
- [ ] Plan next migration batch

### Week 4: Batch Migration
- [ ] Migrate 2-3 related services
- [ ] Update API endpoints
- [ ] Update documentation
- [ ] Performance testing

### Ongoing: Optimization Phase
- [ ] Add service infrastructure features (caching, monitoring)
- [ ] Remove legacy fallback code
- [ ] Performance optimization
- [ ] Team training on service usage

## Success Metrics

### Technical Metrics
- **Migration Success Rate**: >95% of migrated functions work correctly
- **Performance Impact**: <5% performance degradation acceptable
- **Error Rate**: <1% increase in error rate during migration
- **Test Coverage**: Maintain or improve test coverage

### Operational Metrics
- **Service Health**: >99% service availability
- **Response Time**: Track service response times
- **Error Recovery**: Automatic fallback success rate
- **Team Adoption**: Developer satisfaction with new patterns

### Tracking Progress

```python
# Migration tracking in code
MIGRATION_STATUS = {
    "member_onboarding": {
        "status": "completed",
        "migrated_date": "2025-09-21",
        "performance_impact": "-2%",  # 2% improvement
        "error_rate": "0.1%"
    },
    "financial_calculations": {
        "status": "in_progress",
        "target_date": "2025-10-01",
        "complexity": "high"
    },
    "eboekhouden_sync": {
        "status": "planned",
        "target_date": "2025-10-15",
        "dependencies": ["financial_calculations"]
    }
}
```

## Conclusion

This migration guide provides a systematic approach to transitioning existing Verenigingen code to the service infrastructure while maintaining safety, reliability, and backward compatibility. The literal extraction pattern ensures minimal risk while gaining the benefits of the service architecture including health monitoring, field validation, and enhanced error handling.

**Key Success Factors:**
- Follow literal extraction pattern (no logic changes during migration)
- Maintain comprehensive test coverage
- Use gradual rollout with fallback mechanisms
- Monitor performance and error rates closely
- Provide team training and documentation

The service infrastructure provides a solid foundation for maintainable, scalable code that can grow with the Verenigingen application's needs.
