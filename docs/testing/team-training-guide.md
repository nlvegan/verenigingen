# JavaScript Controller Testing - Comprehensive Team Training Guide

## Executive Summary

This guide provides comprehensive training for the Verenigingen development team on our sophisticated JavaScript controller testing infrastructure. Our testing approach enables real-time testing of DocType controllers in their runtime environment, providing superior coverage compared to traditional unit testing with mocks.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Getting Started](#getting-started)
3. [Test Infrastructure Components](#test-infrastructure-components)
4. [Writing Controller Tests](#writing-controller-tests)
5. [Domain-Specific Testing Patterns](#domain-specific-testing-patterns)
6. [API Contract Testing](#api-contract-testing)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Techniques](#advanced-techniques)
10. [Maintenance and Evolution](#maintenance-and-evolution)

---

## Architecture Overview

### Philosophy

Our JavaScript controller testing infrastructure is built around these core principles:

**1. Real Runtime Environment**: Controllers are tested in their actual execution environment, not mocked
**2. Business Logic Focus**: Tests validate Dutch association management business rules
**3. Centralized Infrastructure**: Shared components reduce duplication and ensure consistency
**4. Domain-Specific Patterns**: Financial, association, and workflow domains have specialized builders
**5. Production Ready**: Tests are designed for enterprise deployment with comprehensive error handling

### Technology Stack

- **Jest**: JavaScript testing framework with comprehensive matchers
- **Frappe Framework Integration**: Real controller loading and execution
- **AJV Schema Validation**: API contract testing with JSON Schema
- **Dutch Business Logic Validators**: IBAN, postal codes, name components
- **Enhanced Test Factory Integration**: Python-JavaScript bridge for realistic data

### Testing Categories

**High Priority (Financial & Core Operations)**
- SEPA Mandate Controller
- Direct Debit Batch Controller
- Member Payment History Controller
- Membership Dues Schedule Controller
- Sales Invoice Controller
- Member Controller

**Medium Priority (Reporting & Administration)**
- Chapter Controller
- Volunteer Team Controller
- Verenigingen Settings Controller
- Member Application Controller
- Chapter Board Member Controller

**Lower Priority (Extended Functionality)**
- Event Controller
- Campaign Controller
- Volunteer Expense Controller
- Plus 12+ additional specialized controllers

---

## Getting Started

### Prerequisites

Ensure your development environment has these components:

```bash
# Verify Node.js and npm
node --version  # Should be 16+
npm --version   # Should be 8+

# Verify Jest installation
npx jest --version

# Verify Frappe development environment
bench --version
```

### Running Your First Test

```bash
# Navigate to the project root
cd /home/frappe/frappe-bench/apps/verenigingen

# Run a single controller test
npm test -- verenigingen/tests/unit/doctype/test_donation_controller_comprehensive.test.js

# Run all controller tests
npm test

# Run with coverage reporting
npm run test:coverage

# Run in watch mode for development
npm test -- --watch
```

### Project Structure

```
verenigingen/tests/
├── setup/                              # Core infrastructure
│   ├── controller-test-base.js         # Centralized test suite builder
│   ├── domain-test-builders.js         # Domain-specific test patterns
│   ├── dutch-validators.js             # Business logic validators
│   ├── frappe-mocks.js                # Frappe environment mocks
│   └── api-contract-simple.js          # API contract validation
├── unit/
│   ├── doctype/                        # Controller tests
│   │   ├── test_donation_controller_comprehensive.test.js
│   │   ├── test_volunteer_expense_controller_comprehensive.test.js
│   │   ├── test_membership_termination_request_controller_comprehensive.test.js
│   │   └── [...25+ other controller tests]
│   └── api-contract-simple.test.js     # API contract examples
└── fixtures/                           # Test data and utilities
```

---

## Test Infrastructure Components

### 1. Controller Test Base (`controller-test-base.js`)

The foundation of our testing system. Provides:

- **Real Controller Loading**: Loads actual JavaScript controllers from the filesystem
- **Mock Form Environment**: Comprehensive Frappe form mocking with field dictionaries
- **Event Testing**: Validates controller event handlers (refresh, field changes, etc.)
- **Error Handling**: Graceful handling of controller loading failures
- **Performance Monitoring**: Built-in timing and performance validation

**Key Functions:**
```javascript
const { createControllerTestSuite } = require('../../setup/controller-test-base');

// Creates a complete test suite for a DocType controller
const testSuite = createControllerTestSuite(controllerConfig, customTests);
```

### 2. Domain Test Builders (`domain-test-builders.js`)

Specialized test builders for different business domains:

**FinancialControllerTestBuilder**
- SEPA compliance validation (Dutch IBAN format, BIC codes)
- Payment method configuration testing
- Mandate status transitions
- European banking compliance

**AssociationControllerTestBuilder**
- Dutch business logic (postal codes, name components with tussenvoegsel)
- Membership lifecycle workflows
- Geographic organization (chapters, postal code regions)
- Volunteer management (age requirements, role assignments)

**WorkflowControllerTestBuilder**
- Document state transitions
- Approval workflow testing
- Multi-level authorization

### 3. Dutch Validators (`dutch-validators.js`)

Business-specific validation functions:

```javascript
const { validateDutchIBAN, validateDutchPostalCode, validateDutchEmail } = require('./dutch-validators');

// Dutch IBAN validation
const ibanResult = validateDutchIBAN('NL91ABNA0417164300');
// Returns: { valid: true, normalized: 'NL91ABNA0417164300', bank: 'ABNA' }

// Postal code validation
const postalResult = validateDutchPostalCode('1012 AB');
// Returns: { valid: true, formatted: '1012 AB', region: 'Amsterdam' }
```

### 4. API Contract Testing (`api-contract-simple.js`)

Validates JavaScript-to-Python API calls:

```javascript
const { SimpleAPIContractTester } = require('../setup/api-contract-simple');

const tester = new SimpleAPIContractTester();

// Validate API call structure
expect(apiCall).toMatchAPIContract('verenigingen.doctype.member.member.process_payment');
```

---

## Writing Controller Tests

### Basic Controller Test Structure

Every controller test follows this pattern:

```javascript
/**
 * @fileoverview Comprehensive [DocType] Controller Tests
 */

const { createControllerTestSuite } = require('../../setup/controller-test-base');
require('../../setup/frappe-mocks').setupTestMocks();

// 1. Controller Configuration
const controllerConfig = {
    doctype: 'Your DocType',
    controllerPath: '/path/to/controller.js',
    expectedHandlers: ['refresh', 'field_name', 'other_event'],
    defaultDoc: {
        // Default document structure
        doctype: 'Your DocType',
        name: 'TEST-001',
        // ... other fields
    },
    createMockForm(baseTest, overrides = {}) {
        const form = baseTest.createMockForm(overrides);

        // Add DocType-specific fields
        form.fields_dict = {
            ...form.fields_dict,
            your_field: { df: { fieldtype: 'Data' } },
            // ... other fields
        };

        return form;
    }
};

// 2. Custom Test Suites
const customTests = {
    'Test Category Name': (getControllerTest) => {
        it('should do something specific', () => {
            const controllerTest = getControllerTest();

            // Set up test scenario
            controllerTest.mockForm.doc.field_name = 'test_value';

            // Trigger controller event
            controllerTest.testEvent('refresh');

            // Verify expected behavior
            expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
        });
    }
};

// 3. Create Test Suite
describe('Your DocType Controller (Comprehensive Tests)',
    createControllerTestSuite(controllerConfig, customTests));
```

### Example: Donation Controller Test

Let's examine a real controller test:

```javascript
const donationConfig = {
    doctype: 'Donation',
    controllerPath: '/path/to/donation.js',
    expectedHandlers: ['refresh', 'make_payment_entry'],
    defaultDoc: {
        doctype: 'Donation',
        name: 'DON-2024-TEST-001',
        docstatus: 1, // Submitted
        paid: 0, // Unpaid - eligible for payment entry
        amount: 100.00,
        // ... other fields
    }
};

const customDonationTests = {
    'Payment Entry Workflow': (getControllerTest) => {
        it('should show Create Payment Entry button for submitted unpaid donations', () => {
            const controllerTest = getControllerTest();
            controllerTest.mockForm.doc.docstatus = 1; // Submitted
            controllerTest.mockForm.doc.paid = 0; // Unpaid

            // Trigger refresh event
            controllerTest.testEvent('refresh');

            // Verify payment entry button is added
            expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
                expect.stringContaining('Create Payment Entry'),
                expect.any(Function)
            );
        });
    }
};
```

### Testing Different Event Types

**refresh Event**
- Tests UI button visibility based on document state
- Validates field property changes (read-only, hidden, etc.)
- Checks authorization-based feature access

**Field Change Events**
- Tests cascading field updates
- Validates business rule enforcement
- Checks field clearing/setting logic

**Custom Events**
- Tests API integration workflows
- Validates complex business processes
- Checks error handling and recovery

### Mock Setup Best Practices

**1. Comprehensive Field Dictionaries**
```javascript
form.fields_dict = {
    ...form.fields_dict,
    // Basic data fields
    name: { df: { fieldtype: 'Data' } },
    status: { df: { fieldtype: 'Select' } },

    // Financial fields
    amount: { df: { fieldtype: 'Currency' } },
    currency: { df: { fieldtype: 'Link' } },

    // Date/time fields
    transaction_date: { df: { fieldtype: 'Date' } },
    created_at: { df: { fieldtype: 'Datetime' } },

    // Link fields with proper targets
    customer: { df: { fieldtype: 'Link', options: 'Customer' } },
    member: { df: { fieldtype: 'Link', options: 'Member' } }
};
```

**2. Global Function Mocking**
```javascript
// Mock Frappe globals
global.frappe.call = jest.fn();
global.frappe.user.has_role = jest.fn();
global.frappe.msgprint = jest.fn();
global.__ = jest.fn((text) => text); // Translation mock

// Mock controller-specific functions
global.set_status_indicator = jest.fn();
global.validate_required_fields = jest.fn();
global.auto_set_organization = jest.fn();
```

**3. API Call Mocking**
```javascript
// Mock successful API responses
global.frappe.call.mockImplementation(({ method, callback }) => {
    if (method === 'your.api.method') {
        if (callback) {
            callback({ message: expectedResponse });
        }
    }
    return Promise.resolve({ message: expectedResponse });
});

// Mock API errors
global.frappe.call.mockRejectedValue(new Error('API Error'));
```

---

## Domain-Specific Testing Patterns

### Financial Domain Testing

For SEPA, payment processing, and financial workflow controllers:

```javascript
const { createDomainTestBuilder } = require('../../setup/domain-test-builders');

const customFinancialTests = {
    'SEPA Compliance': (getControllerTest) => {
        const financialBuilder = createDomainTestBuilder(getControllerTest(), 'financial');

        // Add SEPA-specific tests
        Object.assign(this, financialBuilder.createSEPATests());
        Object.assign(this, financialBuilder.createPaymentTests());
        Object.assign(this, financialBuilder.createMandateTests());
    }
};
```

### Association Management Testing

For member, chapter, and volunteer controllers:

```javascript
const customAssociationTests = {
    'Dutch Business Logic': (getControllerTest) => {
        const associationBuilder = createDomainTestBuilder(getControllerTest(), 'association');

        // Add Dutch validation tests
        Object.assign(this, associationBuilder.createDutchValidationTests());
        Object.assign(this, associationBuilder.createMembershipTests());
        Object.assign(this, associationBuilder.createGeographicalTests());
    }
};
```

### Workflow Testing

For approval processes and document state management:

```javascript
const customWorkflowTests = {
    'Approval Workflow': (getControllerTest) => {
        const workflowBuilder = createDomainTestBuilder(getControllerTest(), 'workflow');

        // Add workflow-specific tests
        Object.assign(this, workflowBuilder.createWorkflowTests());
    }
};
```

---

## API Contract Testing

### Overview

API contract testing validates the structure and types of JavaScript-to-Python API calls, ensuring compatibility between frontend controllers and backend methods.

### Basic Usage

```javascript
const { SimpleAPIContractTester, createSimpleAPIContractMatcher } = require('../setup/api-contract-simple');

// Add custom Jest matcher
expect.extend(createSimpleAPIContractMatcher());

describe('API Contract Tests', () => {
    it('should validate member payment API call', () => {
        const validArgs = {
            member_id: 'Assoc-Member-2025-07-0001',
            payment_amount: 25.00,
            payment_method: 'SEPA Direct Debit'
        };

        expect(validArgs).toMatchAPIContract(
            'verenigingen.verenigingen.doctype.member.member.process_payment'
        );
    });
});
```

### Available API Methods

Our contract testing covers these critical API endpoints:

**Member Management**
- `verenigingen.verenigingen.doctype.member.member.process_payment`
- `verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban`
- `verenigingen.verenigingen.doctype.member.member.update_membership_status`

**Chapter Management**
- `verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup`
- `verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_statistics`

**Financial Operations**
- `verenigingen.templates.pages.donate.submit_donation`
- `verenigingen.utils.payment_utils.get_donation_payment_entry`

### Schema Validation

Contract schemas validate:
- **Required Parameters**: Ensures all mandatory fields are present
- **Data Types**: Validates correct parameter types (string, number, boolean)
- **Format Validation**: Dutch-specific formats (IBAN, postal codes, member IDs)
- **Business Rules**: Association management-specific validation

---

## Best Practices

### 1. Test Organization

**Group Related Tests**
```javascript
const customTests = {
    'Authorization and Permissions': (getControllerTest) => {
        // All permission-related tests here
    },

    'Field Validation': (getControllerTest) => {
        // All validation tests here
    },

    'Workflow Management': (getControllerTest) => {
        // All workflow tests here
    }
};
```

**Use Descriptive Test Names**
```javascript
it('should show Create Payment Entry button for submitted unpaid donations', () => {
    // Clear, specific description of expected behavior
});

it('should not show approval buttons when user lacks approval permissions', () => {
    // Describes both the action and the condition
});
```

### 2. Test Data Management

**Use Domain-Appropriate Test Data**
```javascript
// Dutch association management data
const testMember = {
    first_name: 'Jan',
    tussenvoegsel: 'van der', // Dutch name component
    last_name: 'Berg',
    postal_code: '1012 AB', // Valid Dutch format
    iban: 'NL91ABNA0417164300' // Valid Dutch IBAN
};
```

**Create Realistic Scenarios**
```javascript
// Complex approval scenario
controllerTest.mockForm.doc = {
    ...controllerTest.mockForm.doc,
    termination_type: 'Expulsion',
    disciplinary_documentation: 'Detailed evidence of policy violation...',
    secondary_approver: 'board.member@example.org',
    status: 'Pending'
};
```

### 3. Error Handling

**Test Both Success and Failure Paths**
```javascript
it('should handle API call errors gracefully', () => {
    const apiError = new Error('Network timeout');
    global.frappe.call.mockRejectedValue(apiError);

    // Should not throw errors (graceful error handling)
    expect(() => {
        controllerTest.testEvent('refresh');
    }).not.toThrow();
});
```

**Test Edge Cases**
```javascript
it('should handle undefined document fields gracefully', () => {
    delete controllerTest.mockForm.doc.status; // Remove status field

    expect(() => {
        controllerTest.testEvent('refresh');
    }).not.toThrow();
});
```

### 4. Performance Testing

**Monitor Execution Time**
```javascript
it('should handle multiple rapid events efficiently', () => {
    const startTime = performance.now();

    // Execute multiple operations
    for (let i = 0; i < 5; i++) {
        controllerTest.testEvent('refresh');
    }

    const executionTime = performance.now() - startTime;
    expect(executionTime).toBeLessThan(100); // Should complete within 100ms
});
```

### 5. Mock Management

**Reset Mocks Between Tests**
```javascript
beforeEach(() => {
    global.frappe.call.mockClear();
    global.frappe.msgprint.mockClear();
    // Reset other mocks as needed
});
```

**Use Appropriate Mock Return Values**
```javascript
// Mock successful authorization
global.frappe.user.has_role.mockImplementation((roles) => {
    return roles.includes('Verenigingen Administrator');
});

// Mock API responses realistically
global.frappe.call.mockImplementation(({ method, callback }) => {
    const responses = {
        'check_permission_method': { message: true },
        'get_data_method': { message: { data: 'realistic_data' } }
    };

    if (callback && responses[method]) {
        callback(responses[method]);
    }
});
```

---

## Troubleshooting

### Common Issues and Solutions

**1. Controller Loading Failures**
```
Error: Cannot find module 'controller_path'
```
**Solution**: Verify the `controllerPath` in your test configuration points to the actual controller file:
```javascript
const config = {
    controllerPath: '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/your_doctype/your_doctype.js'
};
```

**2. Missing Field Definitions**
```
Error: Cannot read property 'df' of undefined
```
**Solution**: Add missing fields to your mock form's `fields_dict`:
```javascript
form.fields_dict = {
    ...form.fields_dict,
    missing_field: { df: { fieldtype: 'Data' } }
};
```

**3. Global Function Not Defined**
```
ReferenceError: some_function is not defined
```
**Solution**: Mock the missing global function:
```javascript
global.some_function = jest.fn();
```

**4. API Contract Validation Failures**
```
Contract validation failed: parameter 'field_name' is required
```
**Solution**: Check your API call structure matches the expected schema:
```javascript
// Ensure all required fields are present
const apiCall = {
    member_id: 'required_field', // Not just 'member'
    payment_amount: 25.00,       // Number, not string
    payment_method: 'SEPA Direct Debit'
};
```

### Debugging Techniques

**1. Console Logging in Tests**
```javascript
it('should debug controller behavior', () => {
    const controllerTest = getControllerTest();

    console.log('Document before:', controllerTest.mockForm.doc);
    controllerTest.testEvent('refresh');
    console.log('Calls made:', global.frappe.call.mock.calls);
});
```

**2. Mock Call Inspection**
```javascript
// Check what API calls were made
expect(global.frappe.call).toHaveBeenCalledTimes(1);
const callArgs = global.frappe.call.mock.calls[0][0];
console.log('API call arguments:', callArgs);
```

**3. Step-by-Step Event Testing**
```javascript
it('should test step by step', () => {
    const controllerTest = getControllerTest();

    // Step 1: Initial state
    expect(controllerTest.mockForm.doc.status).toBe('Draft');

    // Step 2: Trigger event
    controllerTest.testEvent('refresh');

    // Step 3: Check intermediate state
    expect(global.set_status_indicator).toHaveBeenCalled();

    // Step 4: Verify final state
    expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
});
```

---

## Advanced Techniques

### 1. Dynamic Test Generation

Generate multiple test cases from data:

```javascript
const statusScenarios = [
    { status: 'Draft', expectButton: false },
    { status: 'Submitted', expectButton: true },
    { status: 'Approved', expectButton: false }
];

statusScenarios.forEach(scenario => {
    it(`should handle ${scenario.status} status correctly`, () => {
        controllerTest.mockForm.doc.status = scenario.status;
        controllerTest.testEvent('refresh');

        if (scenario.expectButton) {
            expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
        } else {
            expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
        }
    });
});
```

### 2. Custom Matchers

Create domain-specific Jest matchers:

```javascript
expect.extend({
    toHaveDutchIBANFormat(received) {
        const pass = /^NL[0-9]{2}[A-Z]{4}[0-9]{10}$/.test(received);
        return {
            pass,
            message: () => `Expected ${received} to be a valid Dutch IBAN format`
        };
    }
});

// Usage
expect('NL91ABNA0417164300').toHaveDutchIBANFormat();
```

### 3. Test Helpers

Create reusable test utilities:

```javascript
const TestHelpers = {
    setupApprovedExpense(controllerTest) {
        controllerTest.mockForm.doc.status = 'Approved';
        controllerTest.mockForm.doc.__islocal = 0;
        global.frappe.user.has_role.mockReturnValue(true);
    },

    triggerAndVerifyButtons(controllerTest, expectedButtons) {
        controllerTest.testEvent('refresh');
        expectedButtons.forEach(buttonText => {
            expect(controllerTest.mockForm.add_custom_button)
                .toHaveBeenCalledWith(buttonText, expect.any(Function), expect.any(String));
        });
    }
};
```

### 4. Integration Testing Patterns

Test controller integration with other components:

```javascript
it('should integrate with payment processing workflow', () => {
    const controllerTest = getControllerTest();

    // Mock payment API response
    const paymentEntry = { name: 'PE-001', status: 'Submitted' };
    global.frappe.call.mockResolvedValue({ message: paymentEntry });

    // Simulate payment entry creation button click
    let paymentCallback;
    controllerTest.mockForm.add_custom_button.mockImplementation((text, callback) => {
        if (text.includes('Payment Entry')) {
            paymentCallback = callback;
        }
    });

    // Trigger refresh to add button
    controllerTest.testEvent('refresh');

    // Simulate button click
    if (paymentCallback) {
        paymentCallback();
    }

    // Verify integration
    expect(global.frappe.call).toHaveBeenCalledWith(
        expect.objectContaining({
            method: 'verenigingen.utils.payment_utils.get_donation_payment_entry'
        })
    );
    expect(global.frappe.set_route).toHaveBeenCalledWith('Form', 'Payment Entry', 'PE-001');
});
```

---

## Maintenance and Evolution

### 1. Adding New Controller Tests

When adding a new DocType controller:

**Step 1: Create Test Configuration**
```javascript
const newControllerConfig = {
    doctype: 'New DocType',
    controllerPath: '/path/to/new_doctype.js',
    expectedHandlers: ['refresh', 'field1', 'field2'],
    defaultDoc: {
        doctype: 'New DocType',
        name: 'ND-TEST-001',
        // Add default field values
    },
    createMockForm(baseTest, overrides = {}) {
        // Add DocType-specific mock setup
    }
};
```

**Step 2: Identify Test Categories**
```javascript
const customNewTests = {
    'Basic Functionality': (getControllerTest) => {
        // Test basic controller features
    },
    'Business Logic': (getControllerTest) => {
        // Test domain-specific rules
    },
    'Integration': (getControllerTest) => {
        // Test API interactions
    }
};
```

**Step 3: Add to Test Suite**
Create `/tests/unit/doctype/test_new_doctype_controller_comprehensive.test.js`

### 2. Updating Existing Tests

When controller logic changes:

**1. Review Test Coverage**: Ensure new functionality is tested
**2. Update Mock Setup**: Add new fields to `fields_dict`
**3. Add New Test Cases**: Cover new business logic
**4. Update API Contracts**: If new APIs are added
**5. Run Full Suite**: Ensure no regressions

### 3. Performance Optimization

Monitor and optimize test performance:

```javascript
// Add performance monitoring to critical tests
it('should complete complex workflow efficiently', () => {
    const startTime = performance.now();

    // Execute test logic
    controllerTest.testComplexWorkflow();

    const duration = performance.now() - startTime;
    expect(duration).toBeLessThan(targetTime);

    // Log performance data for monitoring
    if (process.env.LOG_PERFORMANCE) {
        console.log(`Test duration: ${duration}ms`);
    }
});
```

### 4. Test Data Evolution

Keep test data current with business requirements:

```javascript
// Use configuration for test data patterns
const TestDataConfig = {
    memberIdPattern: /^(Assoc-)?Member-\d{4}-\d{2}-\d{4}$/,
    dutchIBANPattern: /^NL[0-9]{2}[A-Z]{4}[0-9]{10}$/,
    postalCodePattern: /^\d{4}\s[A-Z]{2}$/
};

// Update patterns as business rules evolve
function validateMemberID(id) {
    return TestDataConfig.memberIdPattern.test(id);
}
```

---

## Team Training Exercises

### Exercise 1: Basic Controller Test

**Objective**: Create a test for a simple DocType controller

**Task**: Create a test for a "Newsletter Subscription" controller that:
1. Shows an "Unsubscribe" button for active subscriptions
2. Shows a "Resubscribe" button for inactive subscriptions
3. Validates email format on the email field

**Template**:
```javascript
const newsletterConfig = {
    doctype: 'Newsletter Subscription',
    // Complete the configuration...
};

const customTests = {
    'Subscription Management': (getControllerTest) => {
        // Write your tests here...
    }
};
```

### Exercise 2: API Contract Testing

**Objective**: Create API contract tests for a new endpoint

**Task**: Write contract tests for `verenigingen.newsletter.subscribe` that expects:
- `email` (required, valid email format)
- `subscription_type` (required, one of: 'weekly', 'monthly', 'events')
- `language` (optional, default 'nl')

### Exercise 3: Domain-Specific Testing

**Objective**: Use domain builders for specialized testing

**Task**: Create tests for a "Bank Transfer" controller using the financial domain builder to:
1. Validate Dutch IBAN format
2. Test SEPA compliance
3. Handle different payment methods

### Exercise 4: Error Handling

**Objective**: Implement comprehensive error handling

**Task**: Add error handling tests to an existing controller test for:
1. Network timeouts during API calls
2. Missing required fields
3. Invalid data formats
4. Permission denied scenarios

---

## Conclusion

This testing infrastructure represents a sophisticated, production-ready approach to JavaScript controller testing in the Frappe Framework. By following these guidelines and best practices, the team can maintain high code quality while efficiently testing complex business logic.

### Key Takeaways

1. **Real Environment Testing**: Controllers are tested in their actual runtime environment
2. **Domain-Specific Patterns**: Use specialized builders for financial, association, and workflow testing
3. **Comprehensive Coverage**: Test success paths, error paths, edge cases, and performance
4. **Dutch Business Logic**: Built-in validation for association management requirements
5. **API Contract Validation**: Ensure JavaScript-Python integration integrity
6. **Production Ready**: Enterprise-quality error handling and performance monitoring

### Next Steps

1. **Practice**: Work through the training exercises
2. **Apply**: Create tests for your assigned DocTypes
3. **Review**: Participate in code reviews using these standards
4. **Contribute**: Suggest improvements and new patterns
5. **Maintain**: Keep tests updated as business requirements evolve

For questions or support, refer to the troubleshooting section or consult with the testing infrastructure maintainers.

---

*This guide represents the current state of our testing infrastructure as of January 2025. It will be updated as the system evolves.*
