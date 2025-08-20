# API Contract Testing Guide

## Overview

The API Contract Testing infrastructure validates JavaScript-to-Python API calls to ensure parameter structures, data types, and contracts match what the Python backend expects. This catches integration issues that pure unit tests miss.

## Why API Contract Testing?

Traditional unit tests mock JavaScript controllers and Python API methods separately. This can miss critical integration issues:

- **Parameter name mismatches**: JS sends `member_id`, Python expects `member`
- **Data type mismatches**: JS sends string `"25.00"`, Python expects number `25.00`
- **Required parameter validation**: Missing required fields in API calls
- **Response structure validation**: Incorrect assumptions about response format

## Implementation

### Core Infrastructure

```javascript
// Simple API contract validation
const { SimpleAPIContractTester } = require('../setup/api-contract-simple');

const tester = new SimpleAPIContractTester();
const result = tester.validateFrappeCall({
    method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
    args: { member: 'ASSOC-MEMBER-2025-001' }
});

console.log(result.valid); // true
```

### Jest Matcher Integration

```javascript
// Add custom Jest matcher
const { createSimpleAPIContractMatcher } = require('../setup/api-contract-simple');
expect.extend(createSimpleAPIContractMatcher());

// Use in tests
expect({ member: 'ASSOC-MEMBER-2025-001' }).toMatchAPIContract(
    'verenigingen.verenigingen.doctype.member.member.process_payment'
);
```

### Controller Test Integration

```javascript
const memberApiContractTests = {
    'API Contract Validation': (getControllerTest) => {
        it('should validate API calls', () => {
            const controllerTest = getControllerTest();
            
            // Track API calls made by controller
            const capturedCalls = [];
            global.frappe.call = jest.fn((options) => {
                capturedCalls.push({
                    method: options.method,
                    args: options.args || {}
                });
            });
            
            // Trigger controller events
            controllerTest.testEvent('refresh');
            
            // Validate all captured API calls
            capturedCalls.forEach(call => {
                expect(call.args).toMatchAPIContract(call.method);
            });
        });
    }
};
```

## API Schema Definitions

Schemas are defined in `api-contract-simple.js`:

```javascript
const API_SCHEMAS = {
    'verenigingen.verenigingen.doctype.member.member.process_payment': {
        args: {
            type: 'object',
            properties: {
                member: { type: 'string', pattern: '^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$' }
            },
            required: ['member'],
            additionalProperties: false
        },
        response: {
            type: 'object',
            properties: {
                success: { type: 'boolean' },
                message: { type: 'string' },
                payment_data: { type: 'object' }
            },
            required: ['success']
        }
    }
};
```

### Supported Validations

- **Member IDs**: `^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$` pattern
- **Dutch IBANs**: `^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$` format
- **Email addresses**: Standard email format validation
- **BIC codes**: `^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$` pattern
- **Required parameters**: Ensures all required fields are present
- **Data types**: Validates string, number, boolean, object, array types

## Available API Methods

Current schema coverage includes:

### Member APIs
- `verenigingen.verenigingen.doctype.member.member.process_payment`
- `verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details`
- `verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban`
- `verenigingen.verenigingen.doctype.member.member.validate_mandate_creation`

### Chapter APIs
- `verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup`

### Donation APIs
- `verenigingen.templates.pages.donate.submit_donation`

## Usage Examples

### Basic Validation

```javascript
it('should validate member payment API call', () => {
    const validArgs = { member: 'ASSOC-MEMBER-2025-001' };
    
    expect(validArgs).toMatchAPIContract(
        'verenigingen.verenigingen.doctype.member.member.process_payment'
    );
});
```

### Test Data Generation

```javascript
it('should generate valid test data', () => {
    const testData = tester.generateValidTestData(
        'verenigingen.verenigingen.doctype.member.member.process_payment'
    );
    
    expect(testData.member).toMatch(/^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$/);
});
```

### Error Detection

```javascript
it('should detect parameter mismatches', () => {
    const invalidArgs = { member_id: 'WRONG-PARAM' }; // Should be 'member'
    
    expect(() => {
        expect(invalidArgs).toMatchAPIContract(
            'verenigingen.verenigingen.doctype.member.member.process_payment'
        );
    }).toThrow('required');
});
```

### Controller Integration

```javascript
// In controller test
const memberControllerConfig = {
    doctype: 'Member',
    controllerPath: '/path/to/member.js',
    // ... other config
};

const apiContractTests = {
    'API Validation': (getControllerTest) => {
        it('validates controller API calls', () => {
            const test = getControllerTest();
            
            // Mock and capture API calls
            const calls = [];
            global.frappe.call = jest.fn((opts) => calls.push(opts));
            
            // Trigger controller
            test.testEvent('refresh');
            
            // Validate contracts
            calls.forEach(call => {
                if (tester.getMethodSchema(call.method)) {
                    expect(call.args).toMatchAPIContract(call.method);
                }
            });
        });
    }
};

describe('Member Controller', 
    createControllerTestSuite(memberControllerConfig, apiContractTests)
);
```

## Running API Contract Tests

```bash
# Run all API contract tests
npm test -- --testPathPattern="api-contract"

# Run specific contract test
npm test -- --testPathPattern="api-contract-simple.test.js"

# Run controller integration tests with contracts
npm test -- --testPathPattern="simple_contracts.test.js"
```

## Benefits

### Catches Real Integration Issues

- ✅ **Parameter name mismatches** between JavaScript and Python
- ✅ **Data type mismatches** (string vs number, object vs array)
- ✅ **Missing required parameters** in API calls
- ✅ **Invalid data formats** (IBAN, email, member IDs)
- ✅ **Response structure assumptions** that don't match backend

### Improves Code Quality

- ✅ **Early error detection** before integration testing
- ✅ **Documentation** of expected API contracts
- ✅ **Consistency** across JavaScript controller implementations
- ✅ **Regression prevention** when API contracts change

### Developer Experience

- ✅ **Clear error messages** showing exactly what's wrong
- ✅ **Test data generation** for valid API parameters
- ✅ **Coverage analysis** showing which contracts are tested
- ✅ **Integration** with existing Jest test infrastructure

## Adding New API Schemas

1. **Identify the API method** in Python backend
2. **Analyze parameter structure** and types
3. **Add schema definition** to `API_SCHEMAS`
4. **Write validation tests** for the new schema
5. **Update documentation** with the new API method

Example:
```javascript
'verenigingen.new_module.new_api_method': {
    args: {
        type: 'object',
        properties: {
            param1: { type: 'string', minLength: 1 },
            param2: { type: 'number', minimum: 0 }
        },
        required: ['param1'],
        additionalProperties: false
    },
    response: {
        type: 'object',
        properties: {
            result: { type: 'boolean' }
        },
        required: ['result']
    }
}
```

## Best Practices

1. **Start with critical APIs** that handle financial or member data
2. **Use realistic test data** that matches actual patterns
3. **Include negative tests** for invalid parameters
4. **Monitor contract coverage** to ensure comprehensive testing
5. **Update schemas** when Python API contracts change
6. **Integrate with CI/CD** to catch contract violations early

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| "No API schema defined" | Add schema to `API_SCHEMAS` |
| "Pattern does not match" | Check data format (IBAN, member ID, etc.) |
| "Additional properties not allowed" | Remove unexpected parameters |
| "Required parameter missing" | Ensure all required fields are provided |

### Debug Mode

```javascript
// Enable detailed validation output
process.env.DEBUG_API_CONTRACTS = 'true';

// Manual validation with full error details
const result = tester.validateFrappeCall({
    method: 'my.api.method',
    args: { /* test args */ }
});

console.log('Validation result:', result);
if (!result.valid) {
    console.log('Errors:', result.errors);
}
```

## Future Enhancements

- **Mock Service Worker integration** for full HTTP contract testing
- **Auto-schema generation** from Python docstrings
- **Contract versioning** for API evolution
- **Performance benchmarking** of contract validation
- **IDE integration** for real-time contract checking

---

**API Contract Testing represents a significant advancement in integration testing for Frappe applications, providing confidence that JavaScript controllers correctly communicate with Python backends.**

*For questions or contributions, contact the Verenigingen Development Team.*

**Last Updated**: January 2025  
**Version**: 1.0.0  
**Status**: Production Ready