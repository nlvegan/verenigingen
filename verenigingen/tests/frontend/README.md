# Verenigingen Frontend Test Suite

This comprehensive test suite provides robust coverage of JavaScript functionality in the Verenigingen association management system, prioritizing realistic data generation and business workflow validation over mocked behavior.

## Overview

The test suite is designed around the principle of **realistic data generation** rather than extensive mocking. Tests use actual business data patterns, Dutch association scenarios, and real-world edge cases to ensure the system functions correctly under production conditions.

## Test Architecture

### Test Categories

1. **DocType Tests** (`/doctypes/`) - Individual DocType functionality
2. **Integration Tests** (`/integration/`) - Cross-system business workflows  
3. **Unit Tests** (`/unit/`) - Isolated component testing
4. **Factories** (`/factories/`) - Test data generation utilities

### Test Data Strategy

- **Realistic Data Generation**: Uses actual Dutch postal codes, IBANs, names, and business patterns
- **Business Rule Compliance**: Generated data respects all validation rules and constraints
- **Deterministic Testing**: Seeded random generators ensure reproducible test results
- **Edge Case Coverage**: Includes boundary conditions and error scenarios with realistic data

## Running Tests

### Quick Commands

```bash
# Run all tests
npm test

# Run with coverage
npm run test:coverage

# Watch mode for development
npm run test:watch

# Run specific test categories
npm run test:doctypes        # All DocType tests
npm run test:integration     # Business workflow tests
npm run test:unit           # Unit tests only

# Run by priority tier
npm run test:tier1          # Tier 1: Member, Direct Debit, Chapter, Membership, E-Boekhouden Migration
npm run test:tier2          # Tier 2: SEPA Mandate, Volunteer, Donor, Termination Request, Donation Agreement
npm run test:tier3          # Tier 3: Volunteer Expense, Payment Retry, Donation, MT940, E-Boekhouden Settings
npm run test:tier4          # Tier 4: System Settings, Brand Settings, Mollie, Chapter Join, CSV Import
npm run test:tier5          # Tier 5: Amendment Request, Expulsion Report, Team, Audit Logs

# Run by functional area
npm run test:member         # Member DocType only
npm run test:payments       # Payment-related DocTypes (SEPA, Mollie, Payment Retry)
npm run test:donors         # Donor-related DocTypes (Donor, Donation, Periodic Agreement)
npm run test:settings       # All settings DocTypes (System, Brand, E-Boekhouden, Mollie)
npm run test:complete       # All 25 DocType tests

# Quick validation for CI/CD
npm run test:quick          # Fast unit tests only
npm run test:ci            # Full CI test suite
```

### Debugging Tests

```bash
# Debug mode with detailed output
npm run test:debug

# Run specific test file
npm test -- member.test.js

# Run specific test case
npm test -- --testNamePattern="should validate Dutch postal codes"

# Watch specific file during development
npm test -- --watch member.test.js
```

## Test Coverage

### Complete DocType Test Coverage (25 DocTypes)

**Tier 1 (Ultra-Critical) - ✅ COMPLETED**
- ✅ **Member** (3,241 lines JS) - Complete member lifecycle management
- ✅ **Direct Debit Batch** (842 lines) - SEPA payment processing
- ✅ **Chapter** (4,000+ lines) - Geographic organization and board management
- ✅ **Membership** (518 lines) - Membership lifecycle and billing management
- ✅ **E-Boekhouden Migration** (2,104 lines) - Dutch accounting integration

**Tier 2 (High Critical) - ✅ COMPLETED**  
- ✅ **SEPA Mandate** - European banking compliance and payment authorization
- ✅ **Volunteer** - Volunteer management and board assignments
- ✅ **Donor** (634 lines) - ANBI-compliant donation and donor management
- ✅ **Membership Termination Request** (538 lines) - Member termination workflows
- ✅ **Periodic Donation Agreement** (532 lines) - Multi-year donation commitments

**Tier 3 (Important) - ✅ COMPLETED**
- ✅ **Volunteer Expense** (406 lines) - Expense submission and approval workflows
- ✅ **SEPA Payment Retry** (462 lines) - Payment retry logic and failure handling
- ✅ **Donation** - Tax-compliant donation processing and receipt management
- ✅ **MT940 Import** - Bank statement import and transaction reconciliation
- ✅ **E-Boekhouden Settings** (455 lines) - API configuration and sync management

**Tier 4 (Configuration) - ✅ COMPLETED**
- ✅ **Verenigingen Settings** (293 lines) - System configuration and business rules
- ✅ **Brand Settings** (336 lines) - Branding and UI customization
- ✅ **Mollie Settings** - Payment gateway configuration and security
- ✅ **Chapter Join Request** - Chapter membership request workflows
- ✅ **Member CSV Import** (239 lines) - Bulk member data import and validation

**Tier 5 (Administrative) - ✅ COMPLETED**
- ✅ **Contribution Amendment Request** (327 lines) - Fee adjustment workflows
- ✅ **Expulsion Report Entry** (596 lines) - Disciplinary reporting and audit trails
- ✅ **Team** - Team management and organizational structure
- ✅ **SEPA Audit Log** - Payment compliance and audit trail management
- ✅ **API Audit Log** - API security monitoring and access tracking

**Integration Workflows**
- ✅ **Member Onboarding** - Complete registration to active membership
- ✅ **Payment Processing** - SEPA setup, invoicing, and collection
- ✅ **Chapter Organization** - Geographic assignment and board management
- ✅ **Volunteer Management** - Profile creation and role assignments
- ✅ **Financial Operations** - Invoicing, payments, and reconciliation
- ✅ **Termination Workflows** - Membership cancellation and cleanup

### Coverage Metrics

Current coverage targets:
- **Branches**: 70%
- **Functions**: 70% 
- **Lines**: 70%
- **Statements**: 70%

## Test Data Patterns

### Dutch Association Scenarios

The test factory generates realistic Dutch association data:

```javascript
// Realistic member data
const member = testFactory.createMemberData({
  first_name: 'Jan',           // Common Dutch names
  tussenvoegsel: 'van der',    // Dutch naming particles
  last_name: 'Berg',
  email: 'jan.vandeberg@example.nl',
  iban: 'NL91 ABNA 0417 1643 00', // Valid Dutch IBAN
  postal_code: '1234 AB'       // Dutch postal format
});

// SEPA mandate with compliance
const mandate = testFactory.createSEPAMandateData(member.name, {
  mandate_type: 'RCUR',        // Recurring payments
  sequence_type: 'FRST',       // First collection
  creditor_id: 'NL98ZZZ999999999999' // Valid creditor ID
});

// Chapter with geographic coverage
const chapter = testFactory.createChapterData({
  postal_code_ranges: '1000-1999, 2000-2500', // Amsterdam region
  region: 'Noord-Holland'
});
```

### Business Rule Validation

Tests validate critical business rules:

- **Age Requirements**: Volunteers must be 16+, board members 18+
- **IBAN Validation**: European banking format compliance
- **Dutch Postal Codes**: 1234 AB format validation
- **SEPA Compliance**: Payment authorization and processing rules
- **Chapter Assignment**: Geographic postal code range matching

### Edge Cases and Error Scenarios

Comprehensive edge case testing:

```javascript
// Edge case scenarios
const underageVolunteer = testFactory.createEdgeCaseScenario('minimum_age_volunteer');
const maxLengthNames = testFactory.createEdgeCaseScenario('maximum_length_names');
const internationalMember = testFactory.createEdgeCaseScenario('international_member');
const expiredMembership = testFactory.createEdgeCaseScenario('expired_membership');
```

## Test File Structure

```
verenigingen/tests/frontend/
├── doctypes/                    # DocType-specific tests
│   ├── member.test.js          # Member DocType (3,241 lines coverage)
│   ├── direct-debit-batch.test.js # SEPA batch processing
│   ├── chapter.test.js         # Chapter management
│   ├── sepa-mandate.test.js    # European banking compliance
│   └── [other-doctypes].test.js
├── integration/                 # Cross-system workflows
│   └── business-workflows.test.js # End-to-end business processes
├── unit/                       # Component unit tests
│   ├── member-validation.test.js
│   └── sepa-utils.test.js
├── factories/                  # Test data generation
│   └── test-data-factory.js   # Realistic data factory
├── setup.js                   # Global test configuration
└── README.md                  # This documentation
```

## Writing New Tests

### Test Structure Guidelines

1. **Use Realistic Data**: Always use the test factory for data generation
2. **Test Business Logic**: Focus on business rules and workflows
3. **Include Edge Cases**: Test boundary conditions with realistic scenarios
4. **Minimize Mocking**: Mock only external dependencies, use real data for internal logic
5. **Clear Documentation**: Document business context and test purpose

### Example Test Pattern

```javascript
describe('Member DocType - Payment Integration', () => {
  let testFactory;
  let mockFrm;

  beforeEach(() => {
    testFactory = new TestDataFactory(12345); // Deterministic seed
    mockFrm = createMockForm(testFactory.createMemberData());
    setupGlobalMocks();
  });

  test('should create SEPA mandate for Dutch bank account', async () => {
    // Arrange - Use realistic data
    const memberData = testFactory.createMemberData({
      payment_method: 'SEPA Direct Debit',
      iban: testFactory.generateDutchIBAN(), // Valid Dutch IBAN
      bank_account_name: 'Jan van der Berg'
    });

    // Act - Test actual business logic
    const result = await createSEPAMandate(memberData);

    // Assert - Validate business outcomes
    expect(result.mandate_id).toMatch(/^SEPA-\d{6}$/);
    expect(result.creditor_id).toBe('NL98ZZZ999999999999');
    expect(result.status).toBe('Active');
  });
});
```

### Adding New DocType Tests

1. Create test file: `verenigingen/tests/frontend/doctypes/[doctype-name].test.js`
2. Use existing patterns from member.test.js as template
3. Add realistic test data generation in test factory
4. Update package.json scripts for new test categories
5. Document business context and test coverage

## Integration with CI/CD

### GitHub Actions Integration

The test suite integrates with CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Run JavaScript Tests
  run: |
    npm run test:ci
    npm run test:coverage

- name: Upload Coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage/lcov.info
```

### Quality Gates

- **Coverage Threshold**: Minimum 70% across all metrics
- **Test Execution**: All tests must pass before deployment
- **Performance**: Tests complete within 2 minutes
- **Security**: ESLint security plugin validates test code

## Best Practices

### Data Generation
- Always use TestDataFactory for consistent, realistic data
- Seed random generators for reproducible tests
- Include edge cases with realistic boundary data
- Respect business rules in generated data

### Test Organization
- Group related tests in describe blocks
- Use clear, descriptive test names
- Document business context in test descriptions
- Separate unit tests from integration tests

### Mocking Strategy
- Mock external APIs and services only
- Use real data for internal business logic
- Mock Frappe framework components minimally
- Prefer dependency injection over global mocks

### Performance Optimization
- Use deterministic test data for fast execution
- Implement parallel test execution where possible
- Cache test setup data for repeated use
- Monitor test execution time and optimize slow tests

## Troubleshooting

### Common Issues

**Test timeouts**
```bash
# Increase timeout for complex workflows
npm test -- --testTimeout=10000
```

**Module resolution errors**
```bash
# Check Jest configuration in jest.config.js
# Verify setupFilesAfterEnv includes setup.js
```

**Coverage issues**
```bash
# Check coverage configuration in package.json
# Ensure collectCoverageFrom includes correct patterns
```

### Debugging Test Failures

1. **Use descriptive test names** to identify failing tests quickly
2. **Add console.log statements** in test factories for data inspection
3. **Run individual tests** to isolate failures
4. **Check mock implementations** for correct return values
5. **Validate test data** matches expected business rules

## Contributing

When contributing new tests:

1. Follow existing patterns and conventions
2. Add realistic test scenarios using the test factory
3. Document business context and test purpose
4. Update this README with new test categories
5. Ensure tests pass in CI/CD environment

For questions or assistance, refer to the existing test files or contact the Verenigingen development team.