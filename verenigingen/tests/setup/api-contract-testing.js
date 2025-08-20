/**
 * @fileoverview API Contract Testing Infrastructure
 *
 * Validates JavaScript-to-Python API calls to ensure parameter structures,
 * data types, and contracts match what the Python backend expects.
 *
 * This catches integration issues that pure unit tests miss:
 * - Parameter name mismatches (JS sends 'member_id', Python expects 'member')
 * - Data type mismatches (JS sends string, Python expects object)
 * - Required parameter validation
 * - Response structure validation
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { setupServer } = require('msw/node');
const { rest } = require('msw');
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
			additionalProperties: true // Allow additional form fields
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
	},

	// E-Boekhouden API Methods
	'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.test_connection': {
		args: {
			type: 'object',
			properties: {},
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				message: { type: 'string' },
				connection_details: { type: 'object' }
			},
			required: ['success', 'message']
		}
	},

	// Termination API Methods
	'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_impact_preview': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string' }
			},
			required: ['member'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				financial_impact: { type: 'object' },
				volunteer_assignments: { type: 'array' },
				chapter_memberships: { type: 'array' },
				warnings: { type: 'array' }
			},
			required: ['financial_impact']
		}
	}
};

/**
 * Mock Server Setup
 * Creates a mock server that validates API calls against schemas
 */
class APIContractTestServer {
	constructor() {
		this.ajv = new Ajv({ allErrors: true });
		addFormats(this.ajv);
		this.server = null;
		this.setupHandlers();
	}

	setupHandlers() {
		const handlers = [];

		// Create handlers for each API method
		Object.entries(API_SCHEMAS).forEach(([method, schema]) => {
			const handler = rest.post(`/api/method/${method}`, (req, res, ctx) => {
				return this.validateAndRespond(method, req, res, ctx, schema);
			});
			handlers.push(handler);
		});

		// Generic Frappe API handler for unknown methods
		handlers.push(
			rest.post('/api/method/*', (req, res, ctx) => {
				const method = req.url.pathname.replace('/api/method/', '');
				console.warn(`API Contract Test: Unknown method ${method} - add schema for validation`);

				return res(ctx.json({
					message: {
						success: true,
						warning: `No contract validation for method: ${method}`
					}
				}));
			})
		);

		this.server = setupServer(...handlers);
	}

	validateAndRespond(method, req, res, ctx, schema) {
		const requestBody = req.body || {};

		// Validate request arguments
		const argsValidator = this.ajv.compile(schema.args);
		const argsValid = argsValidator(requestBody);

		if (!argsValid) {
			const errors = argsValidator.errors.map(error =>
				`${error.instancePath} ${error.message}`
			).join(', ');

			return res(
				ctx.status(417), // Expectation Failed - like Frappe does
				ctx.json({
					exc_type: 'ValidationError',
					message: `API Contract Violation for ${method}: ${errors}`,
					validation_errors: argsValidator.errors
				})
			);
		}

		// Generate valid response based on schema
		const mockResponse = this.generateMockResponse(schema.response);

		return res(ctx.json({ message: mockResponse }));
	}

	generateMockResponse(responseSchema) {
		// Generate a valid mock response based on the schema
		const response = {};

		if (responseSchema.properties) {
			Object.entries(responseSchema.properties).forEach(([key, propSchema]) => {
				if (responseSchema.required && responseSchema.required.includes(key)) {
					response[key] = this.generateMockValue(propSchema);
				}
			});
		}

		return response;
	}

	generateMockValue(schema) {
		switch (schema.type) {
			case 'boolean':
				return true;
			case 'string':
				if (schema.enum) { return schema.enum[0]; }
				if (schema.format === 'email') { return 'test@example.org'; }
				if (schema.format === 'uri') { return 'https://example.org/test'; }
				return 'mock-string';
			case 'number':
				return schema.minimum || 1;
			case 'array':
				return [];
			case 'object':
				return {};
			default:
				return null;
		}
	}

	start() {
		this.server.listen({
			onUnhandledRequest: 'warn'
		});
	}

	stop() {
		this.server.close();
	}

	reset() {
		this.server.resetHandlers();
	}
}

/**
 * API Contract Test Utilities
 */
class APIContractTester {
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
			throw new Error(`No API schema defined for method: ${method}`);
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
function createAPIContractMatcher() {
	return {
		toMatchAPIContract(received, method) {
			const tester = new APIContractTester();
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
						`Expected ${method} to match API contract.\n\n`
                        + `Validation errors:\n  ${errors}\n\n`
                        + `Received: ${JSON.stringify(received, null, 2)}\n`
                        + `Schema: ${JSON.stringify(result.schema, null, 2)}`,
					pass: false
				};
			}
		}
	};
}

module.exports = {
	API_SCHEMAS,
	APIContractTestServer,
	APIContractTester,
	createAPIContractMatcher
};
