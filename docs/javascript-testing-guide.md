# JavaScript Testing Guide for Verenigingen Doctypes

## Overview

This guide covers the JavaScript testing infrastructure for the Verenigingen app's doctype forms, including unit tests, integration tests, and best practices.

## Test Structure

### Unit Tests
Located in `/tests/unit/`, these test individual form components in isolation:

- `chapter-form.spec.js` - Tests for Chapter doctype JavaScript
- `member-form.spec.js` - Tests for Member doctype JavaScript
- `membership-form.spec.js` - Tests for Membership doctype JavaScript
- `volunteer-form.spec.js` - Tests for Volunteer doctype JavaScript

### Integration Tests
Located in `/tests/integration/`, these test interactions between doctypes:

- `test_doctype_js_integration.js` - Cross-doctype workflow tests

## Running Tests

### Install Dependencies
```bash
cd /home/frappe/frappe-bench/apps/verenigingen
npm install --save-dev jest @types/jest jest-environment-jsdom
```

### Run All Tests
```bash
node tests/run-js-tests.js
```

### Run Specific Test Suites
```bash
# Run only unit tests
node tests/run-js-tests.js unit

# Run only integration tests
node tests/run-js-tests.js integration

# Run tests for specific doctype
node tests/run-js-tests.js member
node tests/run-js-tests.js chapter
node tests/run-js-tests.js volunteer
node tests/run-js-tests.js membership
```

### Run with Coverage
```bash
npx jest --coverage
```

## Test Coverage Areas

### 1. Chapter Form Tests
- **Board Member Management**
  - Adding/removing board members
  - Date validation for terms
  - Role conflict prevention
  - Timeline visualization

- **Postal Code Management**
  - Regex pattern validation
  - Region-based suggestions
  - Distribution analysis

- **Volunteer Integration**
  - Board member to volunteer sync
  - Profile creation

### 2. Member Form Tests
- **IBAN Validation**
  - Mod-97 checksum validation
  - BIC auto-derivation
  - Bank name identification

- **SEPA Mandate Management**
  - Mandate creation dialog
  - Validation and status checks

- **Payment Processing**
  - Payment method changes
  - Payment history updates

- **Chapter Integration**
  - Chapter assignment
  - Postal code suggestions

- **Address Members**
  - Other members at same address
  - Click navigation

- **Application Review**
  - Approval/rejection workflows
  - Status transitions

### 3. Membership Form Tests
- **Type Selection**
  - Amount updates
  - Custom amounts

- **Renewal Calculations**
  - Annual/monthly/lifetime
  - Date validations

- **Payment Integration**
  - SEPA mandate requirements
  - Payment method handling

### 4. Volunteer Form Tests
- **Member Integration**
  - Data inheritance
  - Email generation

- **Activity Management**
  - Add/end activities
  - Date validations

- **Assignment Management**
  - Team/chapter assignments
  - Aggregation display

- **Skills Tracking**
  - Proficiency levels
  - Skill validation

- **Reporting**
  - Timeline generation
  - Export functionality

### 5. Integration Tests
- **Cross-Doctype Workflows**
  - Member → Chapter assignment
  - Member → Volunteer creation
  - Membership → Payment → History
  - Application → Member → Membership

- **Board Management Lifecycle**
  - Appointment → Role change → Term end

- **Validation Cascades**
  - Multi-field validation
  - Error aggregation

## Writing New Tests

### Test Structure Template
```javascript
describe('Feature Name', () => {
    let frm;
    let frappe;

    beforeEach(() => {
        // Set up mocks
        frappe = {
            call: jest.fn(),
            msgprint: jest.fn(),
            // ... other mocks
        };

        frm = {
            doc: { /* test data */ },
            set_value: jest.fn(),
            // ... other form methods
        };
    });

    it('should do something specific', async () => {
        // Arrange
        frappe.call.mockResolvedValue({
            message: { /* expected response */ }
        });

        // Act
        await functionToTest(frm);

        // Assert
        expect(frappe.call).toHaveBeenCalledWith(
            expect.objectContaining({ /* expected args */ })
        );
    });
});
```

### Mocking Best Practices

1. **Mock Frappe Framework**
```javascript
global.frappe = {
    call: jest.fn(),
    model: {
        set_value: jest.fn(),
        get_value: jest.fn()
    },
    datetime: {
        get_today: jest.fn(() => '2024-01-01')
    }
};
```

2. **Mock Form Object**
```javascript
const frm = {
    doc: { /* document data */ },
    fields_dict: { /* field references */ },
    set_value: jest.fn(),
    add_custom_button: jest.fn()
};
```

3. **Mock jQuery**
```javascript
global.$ = jest.fn(() => ({
    html: jest.fn(),
    on: jest.fn(),
    find: jest.fn().mockReturnThis()
}));
```

## Common Testing Patterns

### 1. Testing Async Operations
```javascript
it('should handle async call', async () => {
    frappe.call.mockResolvedValue({
        message: { success: true }
    });

    await someAsyncFunction();

    expect(frappe.call).toHaveBeenCalled();
});
```

### 2. Testing Validation
```javascript
it('should validate input', () => {
    expect(() => {
        validateFunction('invalid input');
    }).toThrow('Expected error message');
});
```

### 3. Testing UI Updates
```javascript
it('should update UI element', () => {
    const mockElement = { html: jest.fn() };
    $.mockReturnValue(mockElement);

    updateUIFunction();

    expect(mockElement.html).toHaveBeenCalledWith(
        expect.stringContaining('expected content')
    );
});
```

### 4. Testing Event Handlers
```javascript
it('should handle field change', () => {
    frm.doc.field_name = 'new value';

    formEvents.field_name(frm);

    expect(frm.set_value).toHaveBeenCalled();
});
```

## Debugging Tests

### View Test Output
```bash
# Verbose output
npx jest --verbose

# Watch mode for development
npx jest --watch

# Debug specific test
npx jest --testNamePattern="should validate IBAN"
```

### Common Issues

1. **Module Not Found**
   - Ensure test file paths are correct
   - Check mock implementations

2. **Async Timeout**
   - Increase timeout: `jest.setTimeout(10000)`
   - Ensure promises are resolved/rejected

3. **Mock Not Working**
   - Clear mocks between tests: `jest.clearAllMocks()`
   - Check mock implementation returns

## CI/CD Integration

The tests can be integrated into GitHub Actions:

```yaml
- name: Run JavaScript Tests
  run: |
    cd apps/verenigingen
    npm install
    npm test
```

## Future Improvements

1. **Visual Regression Testing**
   - Add screenshot testing for complex UI components
   - Test responsive layouts

2. **E2E Testing**
   - Add Cypress tests for full workflows
   - Test actual form interactions

3. **Performance Testing**
   - Add benchmarks for heavy operations
   - Monitor render performance

4. **Accessibility Testing**
   - Add aria-label testing
   - Keyboard navigation tests

## Contributing

When adding new features:

1. Write tests first (TDD approach)
2. Ensure existing tests pass
3. Add integration tests for cross-doctype features
4. Update this documentation

## Resources

- [Jest Documentation](https://jestjs.io/)
- [Testing Library](https://testing-library.com/)
- [Frappe Framework Docs](https://frappeframework.com/)
