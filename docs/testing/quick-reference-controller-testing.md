# Quick Reference: Controller Testing

## TL;DR - Get Started Fast

### 1. Create a New Controller Test

```javascript
// test_my_controller_refactored.test.js
const { createControllerTestSuite } = require('../../setup/controller-test-base');

const config = {
    doctype: 'MyDocType',
    controllerPath: '/full/path/to/my_controller.js',
    expectedHandlers: ['refresh', 'validate'], // Events your controller handles
    defaultDoc: {
        name: 'TEST-001',
        status: 'Active'
        // Add your test data here
    }
};

const customTests = {
    'My Feature': (getControllerTest) => {
        it('should do something', () => {
            getControllerTest().mockForm.doc.field = 'value';
            getControllerTest().testEvent('refresh');
            expect(getControllerTest().mockForm.doc.field).toBe('expected');
        });
    }
};

describe('My Controller', createControllerTestSuite(config, customTests));
```

### 2. Run the Test

```bash
npm test -- --testPathPattern="test_my_controller_refactored.test.js"
```

### 3. Debug Issues

```bash
node verenigingen/tests/utils/debug_controller_loading.js
```

---

## Common Patterns

### Dutch Validation Tests

```javascript
it('should validate Dutch postal codes', () => {
    const associationBuilder = createDomainTestBuilder(getControllerTest(), 'association');
    const tests = associationBuilder.createDutchValidationTests();
    tests['should validate Dutch postal codes']();
});
```

### SEPA Banking Tests

```javascript
it('should validate IBAN', () => {
    const financialBuilder = createDomainTestBuilder(getControllerTest(), 'financial');
    const tests = financialBuilder.createSEPATests();
    tests['should validate Dutch IBAN correctly']();
});
```

### Grid Field Mocking

```javascript
createMockForm: function(baseTest, overrides = {}) {
    const form = baseTest.createMockForm(overrides);

    form.fields_dict.my_grid = {
        grid: {
            get_field: jest.fn(() => ({ get_query: null })),
            add_custom_button: jest.fn(),
            refresh: jest.fn()
        }
    };

    return form;
}
```

---

## Troubleshooting Quick Fixes

| Error | Quick Fix |
|-------|----------|
| `No handlers found` | Check file path and ensure `frappe.ui.form.on` exists |
| `Cannot read property 'grid'` | Add grid mock in `createMockForm` |
| `Cannot read property '1' of undefined` | Add `form.perm = [{read:1, write:1}, {read:1, write:1}]` |
| `setTimeout is not defined` | Already fixed in controller-loader.js |
| `Script execution timed out` | Check for infinite loops, increase timeout if needed |

---

## Test Structure Template

```javascript
const { createControllerTestSuite } = require('../../setup/controller-test-base');
const { createDomainTestBuilder } = require('../../setup/domain-test-builders');

require('../../setup/frappe-mocks').setupTestMocks();

const myConfig = {
    doctype: 'MyDocType',
    controllerPath: '/path/to/controller.js',
    expectedHandlers: ['refresh'],
    defaultDoc: { /* test data */ },

    // Optional: Custom form mocking
    createMockForm: function(baseTest, overrides = {}) {
        const form = baseTest.createMockForm(overrides);
        // Add controller-specific mocks
        return form;
    },

    // Optional: Adjust for heavy controllers
    mockServerCallThreshold: 15
};

const customTests = {
    'Feature Group': (getControllerTest) => {
        beforeEach(() => {
            // Setup mocks for this group
        });

        it('should test something', () => {
            // Test implementation
        });
    }
};

describe('My Controller', createControllerTestSuite(myConfig, customTests));
```

---

## Available Domain Builders

```javascript
// Financial domain
const financialBuilder = createDomainTestBuilder(controllerTest, 'financial');
const sepaTests = financialBuilder.createSEPATests();
const bankingTests = financialBuilder.createBankingTests();
const paymentTests = financialBuilder.createPaymentProcessingTests();

// Association domain
const associationBuilder = createDomainTestBuilder(controllerTest, 'association');
const dutchTests = associationBuilder.createDutchValidationTests();
const membershipTests = associationBuilder.createMembershipTests();
const chapterTests = associationBuilder.createChapterTests();

// Workflow domain
const workflowBuilder = createDomainTestBuilder(controllerTest, 'workflow');
const statusTests = workflowBuilder.createStatusTransitionTests();
const approvalTests = workflowBuilder.createApprovalWorkflowTests();
```

---

## File Locations

```
verenigingen/tests/
├── setup/
│   ├── controller-test-base.js      # Main infrastructure
│   ├── controller-loader.js         # Secure controller loading
│   ├── frappe-mocks.js             # Framework mocking
│   └── domain-test-builders.js     # Domain-specific patterns
├── unit/doctype/
│   └── test_*_controller_refactored.test.js  # Controller tests
└── utils/
    └── debug_controller_loading.js  # Debug utility
```

---

## Performance Tips

- Keep test data minimal
- Use `mockServerCallThreshold` for heavy controllers
- Mock expensive operations in `beforeEach`
- Clean up resources in `afterEach`

---

*For detailed information, see the full [Architecture Documentation](javascript-controller-testing-architecture.md)*
