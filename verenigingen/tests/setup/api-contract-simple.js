/**
 * @fileoverview Simplified API Contract Testing Infrastructure
 * 
 * Validates JavaScript-to-Python API calls without complex mock server setup.
 * Focuses on parameter validation and schema matching.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const Ajv = require('ajv');
const addFormats = require('ajv-formats');

/**
 * API Contract Schema Definitions
 * These schemas define what the Python backend expects
 */
const API_SCHEMAS = {
    // Member API Methods
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
    },
    
    'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details': {
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
                has_schedule: { type: 'boolean' },
                schedule_name: { type: 'string' },
                dues_rate: { type: 'number' },
                frequency: { type: 'string' }
            },
            required: ['has_schedule']
        }
    },
    
    'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban': {
        args: {
            type: 'object',
            properties: {
                iban: { type: 'string', pattern: '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$' }
            },
            required: ['iban'],
            additionalProperties: false
        },
        response: {
            type: 'object',
            properties: {
                bic: { type: 'string', pattern: '^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$' },
                bank_name: { type: 'string' }
            },
            required: ['bic']
        }
    },
    
    'verenigingen.verenigingen.doctype.member.member.validate_mandate_creation': {
        args: {
            type: 'object',
            properties: {
                member: { type: 'string' },
                iban: { type: 'string', pattern: '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$' },
                mandate_id: { type: 'string' }
            },
            required: ['member', 'iban'],
            additionalProperties: false
        },
        response: {
            type: 'object',
            properties: {
                valid: { type: 'boolean' },
                errors: { type: 'array', items: { type: 'string' } },
                warnings: { type: 'array', items: { type: 'string' } }
            },
            required: ['valid']
        }
    },
    
    // Chapter API Methods
    'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup': {
        args: {
            type: 'object',
            properties: {
                member: { type: 'string' },
                chapter: { type: 'string' },
                note: { type: 'string' }
            },
            required: ['member', 'chapter'],
            additionalProperties: false
        },
        response: {
            type: 'object',
            properties: {
                success: { type: 'boolean' },
                message: { type: 'string' },
                previous_chapters: { type: 'array' }
            },
            required: ['success']
        }
    },
    
    // Donation API Methods
    'verenigingen.templates.pages.donate.submit_donation': {
        args: {
            type: 'object',
            properties: {
                donor_name: { type: 'string', minLength: 1 },
                email: { type: 'string', format: 'email' },
                amount: { type: 'number', minimum: 1 },
                donation_type: { type: 'string', enum: ['one-time', 'recurring'] },
                anbi_consent: { type: 'boolean' }
            },
            required: ['donor_name', 'email', 'amount'],
            additionalProperties: true  // Allow additional form fields
        },
        response: {
            type: 'object',
            properties: {
                success: { type: 'boolean' },
                donation_id: { type: 'string' },
                payment_url: { type: 'string', format: 'uri' }
            },
            required: ['success']
        }
    }
};

/**
 * Simple API Contract Validator
 */
class SimpleAPIContractTester {
    constructor() {
        this.ajv = new Ajv({ allErrors: true });
        addFormats(this.ajv);
    }
    
    /**
     * Validate a frappe.call() against expected schema
     */
    validateFrappeCall(callArgs) {
        const { method, args = {} } = callArgs;
        
        if (!API_SCHEMAS[method]) {
            return {
                valid: false,
                errors: [{ message: `No API schema defined for method: ${method}` }],
                method,
                args
            };
        }
        
        const schema = API_SCHEMAS[method];
        const validator = this.ajv.compile(schema.args);
        const isValid = validator(args);
        
        return {
            valid: isValid,
            errors: validator.errors || [],
            method,
            args,
            schema: schema.args
        };
    }
    
    /**
     * Generate test data that matches a schema
     */
    generateValidTestData(method) {
        if (!API_SCHEMAS[method]) {
            throw new Error(`No API schema defined for method: ${method}`);
        }
        
        const schema = API_SCHEMAS[method].args;
        const testData = {};
        
        if (schema.properties) {
            Object.entries(schema.properties).forEach(([key, propSchema]) => {
                if (schema.required && schema.required.includes(key)) {
                    testData[key] = this.generateTestValue(propSchema);
                }
            });
        }
        
        return testData;
    }
    
    generateTestValue(schema) {
        switch (schema.type) {
            case 'string':
                if (schema.pattern === '^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$') {
                    return 'MEMBER-TEST-001-001';
                }
                if (schema.pattern === '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$') {
                    return 'NL91ABNA0417164300';
                }
                if (schema.format === 'email') {
                    return 'test@example.org';
                }
                if (schema.enum) {
                    return schema.enum[0];
                }
                return 'test-value';
            case 'number':
                return schema.minimum || 1;
            case 'boolean':
                return true;
            case 'object':
                return {};
            case 'array':
                return [];
            default:
                return null;
        }
    }
    
    /**
     * Get all available API methods for testing
     */
    getAvailableMethods() {
        return Object.keys(API_SCHEMAS);
    }
    
    /**
     * Get schema for a specific method
     */
    getMethodSchema(method) {
        return API_SCHEMAS[method];
    }
}

/**
 * Jest integration utilities
 */
function createSimpleAPIContractMatcher() {
    return {
        toMatchAPIContract(received, method) {
            const tester = new SimpleAPIContractTester();
            const result = tester.validateFrappeCall({
                method,
                args: received
            });
            
            if (result.valid) {
                return {
                    message: () => `Expected ${method} NOT to match API contract`,
                    pass: true
                };
            } else {
                const errors = result.errors.map(error => 
                    `${error.instancePath} ${error.message}`
                ).join('\n  ');
                
                return {
                    message: () => 
                        `Expected ${method} to match API contract.\n\n` +
                        `Validation errors:\n  ${errors}\n\n` +
                        `Received: ${JSON.stringify(received, null, 2)}\n` +
                        `Schema: ${JSON.stringify(result.schema, null, 2)}`,
                    pass: false
                };
            }
        }
    };
}

module.exports = {
    API_SCHEMAS,
    SimpleAPIContractTester,
    createSimpleAPIContractMatcher
};