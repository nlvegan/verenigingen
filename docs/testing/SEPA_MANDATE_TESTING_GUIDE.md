# SEPA Mandate Comprehensive Testing Guide

## Overview

This guide provides comprehensive documentation for testing SEPA mandate functionality in the Verenigingen association management system. The testing framework ensures compliance with European banking regulations, Dutch financial standards, and provides robust validation for critical financial operations.

## Quick Start

### Running the Complete Test Suite

```bash
# Run all SEPA mandate tests via Frappe
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_sepa_mandate_runner

# Run specific test categories
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.doctype.sepa_mandate.test_sepa_mandate_comprehensive

# Run original tests (backward compatibility)
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.doctype.sepa_mandate.test_sepa_mandate
```

### Quick Python Usage

```python
from verenigingen.tests.test_sepa_mandate_runner import run_sepa_mandate_tests

# Run all tests
results = run_sepa_mandate_tests()

# Run specific categories
from verenigingen.tests.test_sepa_mandate_runner import SEPAMandateTestSuite
SEPAMandateTestSuite.run_compliance_tests()
SEPAMandateTestSuite.run_validation_tests()
```

## Test Architecture

### Core Components

1. **ComprehensiveSEPAMandateTests**: Main test suite with full coverage
2. **SEPAMandateTestDataFactory**: Realistic Dutch banking data generation
3. **SEPAMandateTestMixin**: Reusable testing capabilities
4. **Test Runner Categories**: Organized test execution

### Test Categories

#### 1. Validation Tests (`SEPAMandateValidationTests`)
- Field validation and business rule enforcement
- Enhanced Test Factory integration
- Realistic data generation
- Error handling scenarios

#### 2. Compliance Tests (`SEPAMandateComplianceTests`)
- PSD2 (Payment Services Directive 2) compliance
- GDPR data protection requirements
- Dutch Central Bank (DNB) regulations
- SEPA mandate lifecycle compliance

#### 3. Integration Tests (`SEPAMandateIntegrationTests`)
- Member management system integration
- Payment processing workflows
- Mollie payment gateway compatibility
- Performance optimization validation

#### 4. Comprehensive Tests (`ComprehensiveSEPAMandateTests`)
- Complete end-to-end scenarios
- Security and permission validation
- Dutch banking specific requirements
- European banking regulation compliance

## Testing Features

### Realistic Data Generation

The testing framework generates realistic Dutch banking data:

```python
from verenigingen.tests.fixtures.sepa_mandate_test_factory import SEPAMandateTestDataFactory

factory = SEPAMandateTestDataFactory(seed=12345)

# Get realistic Dutch IBAN
iban = factory.get_random_dutch_iban(bank_code="ABNA")  # ABN AMRO
# Result: "NL91ABNA0417164300"

# Get corresponding bank information
bank_info = factory.get_bank_info_for_iban(iban)
# Result: {"bic": "ABNANL2A", "bank_name": "ABN AMRO Bank N.V.", ...}
```

### Dutch Banking Support

The framework includes comprehensive Dutch banking data:

- **ABN AMRO** (ABNANL2A)
- **ING Bank** (INGBNL2A)
- **Rabobank** (RABONL2U)
- **SNS Bank** (SNSBNL2A)
- **Triodos Bank** (TRIONL2U)
- **ASN Bank** (ASNBNL21)

### European Cross-Border Testing

Support for European IBANs from multiple countries:

```python
# German IBAN
de_iban = factory.get_random_european_iban("DE")

# French IBAN
fr_iban = factory.get_random_european_iban("FR")

# Belgian IBAN
be_iban = factory.get_random_european_iban("BE")
```

## Test Usage Examples

### Basic SEPA Mandate Testing

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_mandate_test_factory import SEPAMandateTestMixin

class TestMyFeature(EnhancedTestCase, SEPAMandateTestMixin):
    def test_mandate_creation(self):
        # Create test member with Enhanced Test Factory
        member = self.create_test_member(
            first_name="Jan",
            last_name="van der Berg",
            birth_date="1990-01-01"
        )

        # Create SEPA mandate with realistic data
        mandate = self.create_test_sepa_mandate(
            member=member,
            status="Active",
            frequency="Monthly",
            maximum_amount=50.00
        )

        # Validate mandate
        self.assert_sepa_mandate_valid(mandate)
        self.assertEqual(mandate.status, "Active")
```

### Compliance Testing

```python
class TestSEPACompliance(EnhancedTestCase, SEPAMandateTestMixin):
    def test_psd2_compliance(self):
        member = self.create_test_member(birth_date="1990-01-01")

        # Create PSD2 compliant mandate
        mandate = self.create_compliance_test_mandate(
            scenario="psd2_sca_compliance",
            member=member
        )

        # Validate PSD2 compliance
        self.assert_mandate_compliance(mandate, "psd2_sca_compliance")

    def test_dutch_banking_compliance(self):
        member = self.create_test_member(birth_date="1990-01-01")

        # Create DNB compliant mandate
        mandate = self.create_compliance_test_mandate(
            scenario="dnb_dutch_banking",
            member=member
        )

        # Validate Dutch banking compliance
        self.assert_mandate_compliance(mandate, "dnb_dutch_banking")
        self.assertTrue(mandate.iban.startswith("NL"))
```

### Usage History Testing

```python
def test_mandate_usage_scenarios(self):
    member = self.create_test_member(birth_date="1990-01-01")

    # Test different usage patterns
    scenarios = ["regular", "irregular", "failed"]

    for scenario in scenarios:
        mandate = self.create_test_sepa_mandate_with_usage(
            member=member,
            usage_scenario=scenario,
            status="Active"
        )

        # Validate usage history
        self.assertGreater(len(mandate.usage_history), 0)

        # Check FRST/RCUR sequence types
        first_usage = mandate.usage_history[0]
        self.assertEqual(first_usage.sequence_type, "FRST")
```

## Compliance Validation

### PSD2 Compliance

The framework validates PSD2 (Payment Services Directive 2) requirements:

- Strong Customer Authentication (SCA)
- Maximum amount enforcement
- Pre-notification requirements
- Consent management

### GDPR Compliance

GDPR (General Data Protection Regulation) validation includes:

- Data minimization principles
- Explicit consent recording
- Retention period enforcement
- Right to erasure preparation

### Dutch Banking (DNB) Compliance

Dutch Central Bank compliance validation:

- Dutch IBAN requirements (NL prefix)
- BIC validation for Dutch banks
- SEPA scheme compliance
- Dutch banking standards

### SEPA Mandate Lifecycle

SEPA-specific lifecycle compliance:

- Mandate signing process
- First collection date rules (14-day pre-notification)
- Pre-notification periods
- Status transition validation

## Field Validation

### Automatic Field Safety

The Enhanced Test Factory integration provides automatic field validation:

```python
# This will validate that all field names exist in the SEPA Mandate DocType
mandate = self.create_test_sepa_mandate(
    member=member,
    mandate_type="RCUR",     # ✓ Valid field
    status="Active",         # ✓ Valid field
    frequency="Monthly",     # ✓ Valid field
    # invalid_field="test"   # ✗ Would raise FieldValidationError
)
```

### Business Rule Validation

Automatic enforcement of business rules:

- IBAN format validation and formatting
- BIC derivation from IBAN
- Date validation (sign date, expiry date)
- Status consistency checks
- Maximum amount validation

## Performance Testing

### Query Count Monitoring

```python
def test_performance(self):
    member = self.create_test_member(birth_date="1990-01-01")

    # Create multiple mandates
    for i in range(10):
        self.create_test_sepa_mandate(member=member, status="Active")

    # Monitor query performance
    with self.assertQueryCount(5):  # Should be efficient
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member.name, "status": "Active"},
            fields=["name", "mandate_id", "status"]
        )
```

### Bulk Operations

Test performance with realistic data volumes:

```python
def test_bulk_mandate_operations(self):
    # Create multiple members and mandates
    members = [self.create_test_member(birth_date="1990-01-01") for _ in range(50)]

    # Test bulk mandate creation performance
    start_time = time.time()
    for member in members:
        self.create_test_sepa_mandate(member=member, status="Active")
    duration = time.time() - start_time

    # Validate performance expectations
    self.assertLess(duration, 30.0, "Bulk operations should complete within 30 seconds")
```

## Security Testing

### Permission Validation

```python
def test_mandate_permissions(self):
    member = self.create_test_member(birth_date="1990-01-01")
    mandate = self.create_test_sepa_mandate(member=member, status="Active")

    # Test member can access own mandate
    frappe.set_user(member.email)
    try:
        own_mandate = frappe.get_doc("SEPA Mandate", mandate.name)
        self.assertEqual(own_mandate.member, member.name)
    except frappe.PermissionError:
        self.fail("Member should access own mandate")
    finally:
        frappe.set_user("Administrator")
```

### Data Protection

```python
def test_sensitive_data_handling(self):
    mandate = self.create_test_sepa_mandate(status="Active")

    # Verify sensitive data is properly handled
    self.assertIsNotNone(mandate.iban)
    self.assertIsNotNone(mandate.account_holder_name)

    # Audit trail validation
    # (Implementation depends on audit logging system)
```

## Error Handling

### Invalid Data Testing

```python
def test_invalid_iban_handling(self):
    member = self.create_test_member(birth_date="1990-01-01")

    # Test invalid IBAN rejection
    with self.assertRaises(frappe.ValidationError):
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": member.name,
            "iban": "INVALID_IBAN",
            "account_holder_name": "Test User",
            "sign_date": frappe.utils.today()
        })
        mandate.insert()
```

### Date Validation

```python
def test_date_validation(self):
    member = self.create_test_member(birth_date="1990-01-01")

    # Test future sign date rejection
    with self.assertRaises(frappe.ValidationError):
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": member.name,
            "iban": "NL91ABNA0417164300",
            "account_holder_name": "Test User",
            "sign_date": frappe.utils.add_days(frappe.utils.today(), 30)
        })
        mandate.insert()
```

## Integration Testing

### Member Integration

```python
def test_member_mandate_relationship(self):
    member = self.create_test_member(birth_date="1990-01-01")
    mandate = self.create_test_sepa_mandate(member=member, status="Active")

    # Verify relationship creation
    member.reload()
    sepa_mandates = member.get("sepa_mandates", [])

    mandate_found = any(
        m.sepa_mandate == mandate.name for m in sepa_mandates
    )
    self.assertTrue(mandate_found, "Mandate should link to member")
```

### Payment Processing Integration

```python
def test_payment_integration(self):
    member = self.create_test_member(birth_date="1990-01-01")
    mandate = self.create_test_sepa_mandate(
        member=member,
        status="Active",
        maximum_amount=100.00
    )

    # Test payment amount validation
    payment_amount = 50.00
    self.assertLessEqual(
        payment_amount,
        mandate.maximum_amount,
        "Payment should not exceed mandate maximum"
    )
```

## Continuous Integration

### CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run SEPA Mandate Tests
  run: |
    bench --site test_site run-tests \
      --module verenigingen.tests.test_sepa_mandate_runner \
      --coverage
```

### Test Reporting

Generate test reports:

```bash
# Run with coverage
bench --site dev.veganisme.net run-tests \
  --module verenigingen.tests.test_sepa_mandate_runner \
  --coverage

# Generate HTML coverage report
coverage html --include="apps/verenigingen/verenigingen/verenigingen_payments/doctype/sepa_mandate/*"
```

## Troubleshooting

### Common Issues

#### FieldValidationError

```python
# Error: Field 'invalid_field' does not exist in SEPA Mandate DocType
# Solution: Check field names in sepa_mandate.json
```

#### Enhanced Test Factory Not Available

```python
# Error: ImportError for Enhanced Test Factory
# Solution: Tests fall back to standard FrappeTestCase automatically
```

#### IBAN Validator Not Available

```python
# Error: ImportError for IBAN validator
# Solution: IBAN validation tests are skipped automatically
```

### Debug Mode

Enable verbose test output:

```python
# Set test verbosity
unittest.TextTestRunner(verbosity=2)

# Enable Frappe debug mode
frappe.flags.in_test = True
frappe.set_user("Administrator")
```

## Advanced Usage

### Custom Test Scenarios

```python
def create_custom_scenario(self):
    """Create custom test scenario for specific business needs."""

    # Custom Dutch bank data
    custom_bank_data = {
        "iban": "NL25TRIO0123456789",  # Triodos Bank
        "bic": "TRIONL2U",
        "bank_name": "Triodos Bank N.V."
    }

    # Create mandate with custom data
    member = self.create_test_member(birth_date="1985-05-15")
    mandate = self.create_test_sepa_mandate(
        member=member,
        **custom_bank_data,
        status="Active",
        mandate_type="RCUR",
        frequency="Quarterly",
        maximum_amount=75.00,
        used_for_donations=1
    )

    return mandate
```

### Extension Points

```python
class CustomSEPAMandateTests(EnhancedTestCase, SEPAMandateTestMixin):
    """Custom SEPA mandate tests for organization-specific requirements."""

    def setUp(self):
        super().setUp()
        # Custom setup logic
        self.custom_config = {
            "default_bank": "RABO",
            "test_amounts": [25.00, 50.00, 75.00, 100.00]
        }

    def test_organization_specific_requirements(self):
        """Test organization-specific SEPA mandate requirements."""
        # Custom test implementation
        pass
```

## Best Practices

### 1. Use Enhanced Test Factory

Always prefer Enhanced Test Factory for business logic validation:

```python
# ✓ Good - Uses Enhanced Test Factory
class TestFeature(EnhancedTestCase, SEPAMandateTestMixin):
    def test_mandate_creation(self):
        member = self.create_test_member(birth_date="1990-01-01")
        mandate = self.create_test_sepa_mandate(member=member)

# ✗ Avoid - Manual test data creation
class TestFeature(unittest.TestCase):
    def test_mandate_creation(self):
        # Manual, error-prone test data creation
```

### 2. Test Realistic Scenarios

Use realistic Dutch banking data and business scenarios:

```python
# ✓ Good - Realistic scenario
def test_dutch_membership_payment(self):
    member = self.create_test_member(
        first_name="Pieter",
        last_name="van der Berg",
        birth_date="1985-03-15"
    )

    mandate = self.create_test_sepa_mandate(
        member=member,
        iban=self.sepa_factory.get_random_dutch_iban("RABO"),  # Rabobank
        frequency="Monthly",
        maximum_amount=25.00  # Typical membership fee
    )
```

### 3. Validate Compliance

Always include compliance validation:

```python
def test_mandate_with_compliance(self):
    mandate = self.create_compliance_test_mandate(
        scenario="psd2_sca_compliance"
    )

    # Validate business logic
    self.assert_sepa_mandate_valid(mandate)

    # Validate compliance
    self.assert_mandate_compliance(mandate, "psd2_sca_compliance")
```

### 4. Test Error Scenarios

Include comprehensive error handling tests:

```python
def test_comprehensive_error_handling(self):
    # Test invalid IBAN
    with self.assertRaises(frappe.ValidationError):
        self.create_test_sepa_mandate(iban="INVALID")

    # Test future sign date
    with self.assertRaises(frappe.ValidationError):
        self.create_test_sepa_mandate(
            sign_date=frappe.utils.add_days(frappe.utils.today(), 30)
        )
```

## Conclusion

The SEPA Mandate comprehensive testing framework provides robust validation for critical financial functionality while ensuring compliance with European banking regulations and Dutch financial standards. Use this guide to implement thorough testing for SEPA mandate operations in your Verenigingen system.

For additional support or questions about the testing framework, refer to the source code documentation or contact the development team.
