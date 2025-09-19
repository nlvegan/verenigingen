# Mollie Donation Flow E2E Testing Guide

## Overview

This comprehensive end-to-end testing suite validates the complete Mollie donation flow from form submission through payment processing and database updates. The test suite provides production-ready validation of the entire donation workflow with realistic Dutch test data.

## Architecture

### Test Components

```
tests/
├── e2e/
│   └── mollie-donation-flow.spec.js    # Main E2E test suite
├── support/
│   ├── dutch-test-data.js              # Dutch test data generation
│   ├── mollie-test-helpers.js          # Mollie payment simulation
│   ├── database-validator.js           # Database validation utilities
│   ├── webhook-simulator.js            # Webhook testing tools
│   ├── global-setup.js                 # Test environment setup
│   └── global-teardown.js              # Test cleanup and reporting
├── playwright.config.js                # Playwright configuration
└── run_mollie_e2e_tests.sh            # Test execution script
```

### Key Features

- **Complete Flow Testing**: From donation form to database updates
- **Realistic Dutch Data**: Names with tussenvoegsel, valid postal codes, test phone numbers
- **Payment Simulation**: Comprehensive Mollie test environment integration
- **Database Validation**: Verifies all expected records are created with correct field values
- **Webhook Processing**: Tests complete webhook pipeline with signature verification
- **Error Scenarios**: Validates error handling and edge cases
- **Performance Testing**: Concurrent donation processing validation
- **Comprehensive Reporting**: Detailed HTML reports with screenshots and videos

## Test Coverage

### Happy Path Scenarios

- ✅ Complete recurring donation flow
- ✅ Single donation processing
- ✅ Mollie payment page redirect and completion
- ✅ Webhook processing and database updates
- ✅ Payment history tracking
- ✅ Sales invoice generation
- ✅ Mollie integration field population

### Error Scenarios

- ✅ Form validation errors
- ✅ Invalid email format handling
- ✅ Payment failure processing
- ✅ Webhook signature verification failures
- ✅ Database transaction rollbacks
- ✅ Rate limiting and security validation

### Performance Testing

- ✅ Concurrent donation processing
- ✅ Webhook processing under load
- ✅ Database performance validation
- ✅ Memory usage monitoring

## Quick Start

### Prerequisites

1. **Development Environment**: Ensure dev.veganisme.net is accessible
2. **Mollie Configuration**: Test API key configured in Mollie Settings
3. **Node.js**: Version 16+ installed
4. **Playwright**: Will be auto-installed if missing

### Basic Usage

```bash
# Run complete test suite
./run_mollie_e2e_tests.sh --full

# Quick validation (essential tests only)
./run_mollie_e2e_tests.sh --quick

# Debug mode with detailed logging
./run_mollie_e2e_tests.sh --debug

# Headless mode for CI/CD
./run_mollie_e2e_tests.sh --headless --ci
```

## Test Execution Modes

### Full Test Suite (`--full`)

Executes all test scenarios including:

- Complete recurring donation flow (Happy Path)
- Single donation processing
- Error scenario validation
- Performance testing with concurrent donations
- Comprehensive webhook processing validation

**Duration**: ~8-12 minutes
**Coverage**: Complete validation of all functionality

### Quick Test Suite (`--quick`)

Essential tests for rapid validation:

- Basic happy path donation flow
- Single donation processing
- Core error scenarios

**Duration**: ~3-5 minutes
**Coverage**: Core functionality validation

### Smoke Tests (`--smoke`)

Minimal validation for basic functionality:

- Happy path recurring donation only

**Duration**: ~2-3 minutes
**Coverage**: Basic system validation

### Specialized Test Modes

```bash
# Webhook-specific testing
./run_mollie_e2e_tests.sh --webhook

# Performance testing only
./run_mollie_e2e_tests.sh --performance

# Mobile browser testing
./run_mollie_e2e_tests.sh --browser mobile
```

## Browser Support

### Supported Browsers

- **Chrome** (Desktop) - Default, most comprehensive testing
- **Firefox** (Desktop) - Cross-browser validation
- **Mobile Safari** (iPhone 13) - Mobile responsiveness testing

### Browser-Specific Testing

```bash
# Chrome (default)
./run_mollie_e2e_tests.sh --browser chrome

# Firefox
./run_mollie_e2e_tests.sh --browser firefox

# Mobile testing
./run_mollie_e2e_tests.sh --browser mobile
```

## Test Data Generation

### Dutch Test Data Features

The test suite generates realistic Dutch test data:

```javascript
// Example generated data
{
  firstName: "Pieter",
  tussenvoegsel: "van der",
  lastName: "Berg",
  fullName: "Pieter van der Berg",
  email: "pieter.berg.1234@test-verenigingen.nl",
  phone: "06-12341234",
  address: {
    street: "Hoofdstraat 42",
    postalCode: "1234 AB",
    city: "Amsterdam",
    country: "Nederland"
  },
  birthDate: "1985-03-15"
}
```

### Data Validation

- **Business Rules**: Age validation, required fields, format checking
- **Field Safety**: Validates against actual DocType schemas
- **Cleanup**: Automatic test data removal after execution

## Database Validation

### Comprehensive Record Verification

The test suite validates creation and updates of:

- **Donor Records**: Personal information, contact details
- **Donation Records**: Amount, status, Mollie integration fields
- **Payment Entries**: Payment processing, reference numbers
- **Payment History**: Transaction tracking
- **Sales Invoices**: Accounting integration
- **Webhook Processing Logs**: Audit trail

### Validation Example

```javascript
// Verify complete donation processing chain
const results = await dbValidator.verifyCompleteDonationChain({
  email: testData.email,
  amount: 25.0,
  donationType: "recurring",
  molliePaymentId: paymentResult.id,
  paymentCompleted: true,
});

// Results include all created records with validation
expect(results.validationErrors).toHaveLength(0);
expect(results.donation.mollie_customer_id).toBeTruthy();
expect(results.donation.mollie_subscription_id).toBeTruthy();
```

## Webhook Processing Testing

### Comprehensive Webhook Validation

- **Signature Verification**: HMAC SHA256 validation
- **Payload Processing**: Complete webhook data handling
- **Database Updates**: Record creation and field updates
- **Error Handling**: Invalid signatures, malformed data
- **Rate Limiting**: DDoS protection validation

### Webhook Test Features

```javascript
// Simulate webhook with comprehensive data
const webhookResult = await webhookSimulator.sendMollieWebhook({
  paymentId: "tr_test_12345",
  status: "paid",
  amount: 25.0,
  metadata: {
    donor_email: testData.email,
    donation_type: "recurring",
  },
});

expect(webhookResult.processed).toBe(true);
```

## Performance Testing

### Concurrent Processing

Tests system behavior under load:

- Multiple simultaneous donations
- Concurrent webhook processing
- Database performance validation
- Memory usage monitoring

### Performance Metrics

- **Throughput**: Donations processed per minute
- **Response Time**: Average processing duration
- **Error Rate**: Failed transactions under load
- **Resource Usage**: Memory and CPU utilization

## Error Scenarios

### Comprehensive Error Coverage

- **Form Validation**: Required fields, format validation
- **Payment Failures**: Mollie payment processing errors
- **Webhook Errors**: Invalid signatures, processing failures
- **Database Errors**: Transaction rollbacks, constraint violations
- **Network Issues**: Timeout handling, retry mechanisms

### Error Recovery Testing

- **Automatic Retries**: Failed payment retry logic
- **Data Consistency**: Transaction rollback validation
- **User Experience**: Error message display and handling

## Reporting and Debugging

### Test Results

After test execution, comprehensive reports are generated:

```
test-results/
├── html-report/              # Interactive HTML report with screenshots
├── test-results.json         # Machine-readable test results
├── test-summary.json         # Executive summary with metrics
├── junit.xml                 # CI/CD integration format
└── playwright-output/        # Videos, traces, artifacts
```

### Debug Mode Features

```bash
# Enable comprehensive debugging
./run_mollie_e2e_tests.sh --debug

# Features enabled in debug mode:
# - Video recording of all tests
# - Screenshot capture at each step
# - Detailed console logging
# - Extended timeouts for manual inspection
# - Playwright trace generation
```

### Viewing Results

```bash
# Open HTML report
npx playwright show-report test-results/html-report

# View test summary (requires jq)
jq '.' test-results/test-summary.json
```

## CI/CD Integration

### Automated Testing

```bash
# CI mode configuration
./run_mollie_e2e_tests.sh --ci

# Features:
# - Headless execution
# - No interactive prompts
# - JUnit XML generation
# - Artifact archiving
# - Exit code propagation
```

### GitHub Actions Example

```yaml
name: Mollie E2E Tests
on: [push, pull_request]

jobs:
  e2e-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: "18"

      - name: Install dependencies
        run: npm install

      - name: Run E2E tests
        run: ./run_mollie_e2e_tests.sh --ci --quick
        env:
          MOLLIE_TEST_API_KEY: ${{ secrets.MOLLIE_TEST_API_KEY }}

      - name: Upload test results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: test-results
          path: test-results/
```

## Environment Configuration

### Required Settings

```bash
# Environment variables
export MOLLIE_TEST_API_KEY="test_dHar4XY7LxsDOtmnkVtjNVWXLSlXsM"
export MOLLIE_WEBHOOK_SECRET="test_webhook_secret_key"
export NODE_ENV="testing"
```

### Mollie Settings Configuration

1. Navigate to **Verenigingen Payments → Mollie Settings**
2. Enable **Test Mode**
3. Configure **Test API Key**
4. Verify **Webhook URL** configuration

## Troubleshooting

### Common Issues

#### Test Environment Not Accessible

```bash
# Verify development server is running
curl -k https://dev.veganisme.net

# Start development server if needed
bench start
```

#### Mollie Configuration Issues

```bash
# Check Mollie settings via console
bench --site dev.veganisme.net console
>>> frappe.get_doc('Mollie Settings', 'Mollie Settings')
```

#### Test Data Cleanup Issues

```bash
# Manual cleanup if needed
./run_mollie_e2e_tests.sh --no-setup --no-report
```

### Debug Information

- **Test Artifacts**: Screenshots and videos in `test-results/`
- **Console Logs**: Detailed execution logs in debug mode
- **Database State**: Pre/post test database validation
- **Network Traffic**: Request/response logging

## Advanced Usage

### Custom Test Data

```javascript
// Generate specific test scenarios
const testDataGenerator = new DutchTestDataGenerator({ seed: 12345 });
const customData = testDataGenerator.generateDonorData({
  includeDetails: true,
  donationType: "recurring",
  useTussenvoegsel: true,
});
```

### Extended Validation

```javascript
// Custom validation chains
const validationResult = await dbValidator.verifyCompleteDonationChain({
  email: "custom@test.nl",
  amount: 50.0,
  requiresMollie: true,
  validateAccountingIntegration: true,
});
```

### Performance Monitoring

```javascript
// Performance test configuration
const performanceTests = await webhookSimulator.runComprehensiveWebhookTests();
console.log(`Processing rate: ${performanceTests.averageProcessingTime}ms`);
```

## Integration with Enhanced Test Factory

The E2E tests integrate seamlessly with the existing Enhanced Test Factory:

```python
# Python test integration
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestMollieIntegration(EnhancedTestCase):
    def test_e2e_validation(self):
        # Create test data using Enhanced Test Factory
        member = self.create_test_member(
            first_name="Playwright",
            last_name="Test"
        )

        # E2E tests will validate this data through the web interface
```

## Conclusion

This comprehensive E2E testing suite provides production-ready validation of the complete Mollie donation flow. With realistic test data, comprehensive error scenarios, and detailed reporting, it ensures the donation system functions correctly under all conditions.

The test suite is designed for:

- **Development Teams**: Local testing and debugging
- **QA Teams**: Comprehensive validation and regression testing
- **CI/CD Pipelines**: Automated testing and deployment validation
- **Production Monitoring**: Continuous validation of system health

For questions or issues, refer to the troubleshooting section or examine the detailed test artifacts generated after each run.
