# JavaScript Controller Testing - Quick Reference Card

## Essential Commands

```bash
# Run single controller test
npm test -- verenigingen/tests/unit/doctype/test_donation_controller_comprehensive.test.js

# Run all controller tests
npm test

# Run with coverage
npm run test:coverage

# Watch mode for development
npm test -- --watch

# Run specific test pattern
npm test -- --testNamePattern="Payment Entry"
```

## Basic Test Structure

```javascript
const { createControllerTestSuite } = require('../../setup/controller-test-base');
require('../../setup/frappe-mocks').setupTestMocks();

const controllerConfig = {
    doctype: 'Your DocType',
    controllerPath: '/path/to/controller.js',
    expectedHandlers: ['refresh', 'field_event'],
    defaultDoc: {
        doctype: 'Your DocType',
        name: 'TEST-001',
        status: 'Draft'
    },
    createMockForm(baseTest, overrides = {}) {
        const form = baseTest.createMockForm(overrides);
        form.fields_dict = {
            ...form.fields_dict,
            your_field: { df: { fieldtype: 'Data' } }
        };
        return form;
    }
};

const customTests = {
    'Test Category': (getControllerTest) => {
        it('should do something', () => {
            const controllerTest = getControllerTest();
            controllerTest.testEvent('refresh');
            expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
        });
    }
};

describe('Your DocType Controller', createControllerTestSuite(controllerConfig, customTests));
```

## Common Mock Setups

```javascript
// Global mocks
global.frappe.call = jest.fn();
global.frappe.user.has_role = jest.fn().mockReturnValue(false);
global.frappe.msgprint = jest.fn();
global.__ = jest.fn((text) => text);

// API response mock
global.frappe.call.mockImplementation(({ method, callback }) => {
    if (method === 'your.api.method') {
        if (callback) callback({ message: 'success' });
    }
});

// API error mock
global.frappe.call.mockRejectedValue(new Error('API Error'));
```

## Field Types Reference

```javascript
form.fields_dict = {
    // Basic types
    name: { df: { fieldtype: 'Data' } },
    status: { df: { fieldtype: 'Select' } },
    description: { df: { fieldtype: 'Text' } },
    amount: { df: { fieldtype: 'Currency' } },

    // Date/time
    date_field: { df: { fieldtype: 'Date' } },
    datetime_field: { df: { fieldtype: 'Datetime' } },

    // Links
    customer: { df: { fieldtype: 'Link', options: 'Customer' } },
    member: { df: { fieldtype: 'Link', options: 'Member' } },

    // Checkboxes
    is_active: { df: { fieldtype: 'Check' } }
};
```

## Domain Test Builders

```javascript
const { createDomainTestBuilder } = require('../../setup/domain-test-builders');

// Financial domain
const financialBuilder = createDomainTestBuilder(controllerTest, 'financial');
Object.assign(tests, financialBuilder.createSEPATests());

// Association domain
const associationBuilder = createDomainTestBuilder(controllerTest, 'association');
Object.assign(tests, associationBuilder.createDutchValidationTests());

// Workflow domain
const workflowBuilder = createDomainTestBuilder(controllerTest, 'workflow');
Object.assign(tests, workflowBuilder.createWorkflowTests());
```

## API Contract Testing

```javascript
const { SimpleAPIContractTester } = require('../setup/api-contract-simple');
expect.extend(createSimpleAPIContractMatcher());

// Test API call structure
expect(apiArgs).toMatchAPIContract('verenigingen.doctype.member.member.process_payment');

// Generate test data
const tester = new SimpleAPIContractTester();
const testData = tester.generateValidTestData('api.method.name');
```

## Common Test Patterns

### Button Visibility Test
```javascript
it('should show button for specific conditions', () => {
    controllerTest.mockForm.doc.status = 'Submitted';
    controllerTest.testEvent('refresh');

    expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
        'Button Text',
        expect.any(Function),
        'Group Name'
    );
});
```

### Field Validation Test
```javascript
it('should validate field correctly', () => {
    controllerTest.mockForm.doc.field_name = 'invalid_value';
    controllerTest.testEvent('field_name');

    expect(global.frappe.msgprint).toHaveBeenCalledWith('Error message');
    expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('field_name', '');
});
```

### Permission Test
```javascript
it('should check permissions appropriately', () => {
    global.frappe.user.has_role.mockImplementation(roles =>
        roles.includes('Required Role'));

    controllerTest.testEvent('refresh');
    expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
});
```

### API Integration Test
```javascript
it('should handle API integration', () => {
    const mockResponse = { name: 'DOC-001', status: 'Success' };
    global.frappe.call.mockResolvedValue({ message: mockResponse });

    controllerTest.testEvent('api_event');

    expect(global.frappe.call).toHaveBeenCalledWith({
        method: 'api.method.name',
        args: { doc: controllerTest.mockForm.doc },
        callback: expect.any(Function)
    });
});
```

### Error Handling Test
```javascript
it('should handle errors gracefully', () => {
    global.frappe.call.mockRejectedValue(new Error('Network Error'));

    expect(() => {
        controllerTest.testEvent('api_event');
    }).not.toThrow();

    expect(global.frappe.call).toHaveBeenCalled();
});
```

## Dutch Business Logic Patterns

```javascript
// IBAN validation
const { validateDutchIBAN } = require('../../setup/dutch-validators');
const result = validateDutchIBAN('NL91ABNA0417164300');
expect(result.valid).toBe(true);

// Postal code validation
const { validateDutchPostalCode } = require('../../setup/dutch-validators');
const postal = validateDutchPostalCode('1012 AB');
expect(postal.valid).toBe(true);

// Name with tussenvoegsel
const memberData = {
    first_name: 'Jan',
    tussenvoegsel: 'van der',
    last_name: 'Berg'
};
```

## Performance Testing

```javascript
it('should complete within time limit', () => {
    const startTime = performance.now();

    // Execute test operations
    controllerTest.testEvent('refresh');

    const duration = performance.now() - startTime;
    expect(duration).toBeLessThan(100); // 100ms limit
});
```

## Debugging Tips

```javascript
// Log mock calls
console.log('API calls:', global.frappe.call.mock.calls);
console.log('Button calls:', controllerTest.mockForm.add_custom_button.mock.calls);

// Inspect document state
console.log('Document:', controllerTest.mockForm.doc);

// Check field dictionary
console.log('Fields:', Object.keys(controllerTest.mockForm.fields_dict));
```

## Common Assertions

```javascript
// Button assertions
expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
    'Button Text', expect.any(Function), 'Group'
);

// API assertions
expect(global.frappe.call).toHaveBeenCalled();
expect(global.frappe.call).toHaveBeenCalledTimes(1);
expect(global.frappe.call).toHaveBeenCalledWith(
    expect.objectContaining({ method: 'api.method' })
);

// Field value assertions
expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('field', 'value');
expect(controllerTest.mockForm.toggle_display).toHaveBeenCalledWith('field', true);

// Message assertions
expect(global.frappe.msgprint).toHaveBeenCalledWith('Message text');

// Navigation assertions
expect(global.frappe.set_route).toHaveBeenCalledWith('Form', 'DocType', 'name');
```

## File Locations

```
verenigingen/tests/
├── setup/
│   ├── controller-test-base.js     # Core infrastructure
│   ├── domain-test-builders.js     # Domain patterns
│   ├── dutch-validators.js         # Business validators
│   ├── frappe-mocks.js            # Environment mocks
│   └── api-contract-simple.js     # API contracts
└── unit/doctype/                  # Controller tests
    └── test_[doctype]_controller_comprehensive.test.js
```

## Environment Variables

```bash
# Enable performance logging
LOG_PERFORMANCE=true npm test

# Increase Jest timeout
JEST_TIMEOUT=10000 npm test

# Run specific test suite
TEST_SUITE=donation npm test
```
