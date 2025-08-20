/**
 * @fileoverview Member Controller Simple API Contract Integration Tests
 *
 * Demonstrates practical integration of API contract testing with controller testing
 * using the simplified approach (without MSW complexity).
 *
 * This validates that JavaScript controllers make correct API calls to Python backend.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { createControllerTestSuite } = require('../../setup/controller-test-base');
const {
	SimpleAPIContractTester,
	createSimpleAPIContractMatcher
} = require('../../setup/api-contract-simple');

require('../../setup/frappe-mocks').setupTestMocks();

// Add custom Jest matcher for API contract validation
expect.extend(createSimpleAPIContractMatcher());

// Configuration for Member controller with API contract testing
const memberControllerConfig = {
	doctype: 'Member',
	controllerPath: '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.js',
	expectedHandlers: ['refresh', 'validate', 'member_since', 'first_name', 'tussenvoegsel', 'last_name'],
	defaultDoc: {
		name: 'ASSOC-MEMBER-2025-001',
		status: 'Active',
		first_name: 'Jan',
		tussenvoegsel: 'van der',
		last_name: 'Berg',
		email: 'jan.vandeberg@example.org',
		phone: '+31612345678',
		birth_date: '1985-03-15',
		member_since: '2025-01-01'
	},
	mockServerCallThreshold: 20
};

describe('Member Controller Simple API Contract Integration', () => {
	let apiTester;
	let capturedApiCalls = [];

	beforeAll(() => {
		apiTester = new SimpleAPIContractTester();

		// Enhanced frappe.call mock to capture API calls for contract validation
		const originalFrappeCall = global.frappe.call;
		global.frappe.call = jest.fn((options) => {
			// Capture the API call for contract validation
			capturedApiCalls.push({
				method: options.method,
				args: options.args || {},
				callback: options.callback,
				error: options.error
			});

			// Validate against contract if we have a schema
			try {
				if (apiTester.getMethodSchema(options.method)) {
					const result = apiTester.validateFrappeCall({
						method: options.method,
						args: options.args || {}
					});

					if (!result.valid) {
						console.warn(`⚠️  API Contract Violation in ${options.method}:`,
							result.errors.map(e => e.message).join(', '));
					}
				}
			} catch (contractError) {
				console.warn(`⚠️  API Contract Error for ${options.method}:`, contractError.message);
			}

			// Call original behavior for controller functionality
			if (originalFrappeCall) {
				return originalFrappeCall.call(global.frappe, options);
			}

			// Provide sensible mock responses for contract validation
			if (options.callback) {
				setImmediate(() => {
					let mockResponse = { success: true };

					if (options.method.includes('get_current_dues_schedule_details')) {
						mockResponse = {
							has_schedule: true,
							schedule_name: 'SCHED-001',
							dues_rate: 25.00,
							frequency: 'Monthly'
						};
					} else if (options.method.includes('derive_bic_from_iban')) {
						mockResponse = {
							bic: 'ABNANL2A',
							bank_name: 'ABN AMRO Bank N.V.'
						};
					} else if (options.method.includes('validate_mandate_creation')) {
						mockResponse = {
							valid: true,
							errors: [],
							warnings: []
						};
					}

					options.callback(mockResponse);
				});
			}
		});
	});

	beforeEach(() => {
		capturedApiCalls = [];
	});

	const memberApiContractTests = {
		'API Contract Validation Integration': (getControllerTest) => {
			it('should validate captured API calls against contracts', () => {
				const controllerTest = getControllerTest();

				// Trigger controller events that make API calls
				controllerTest.testEvent('refresh');

				// Validate all captured API calls
				capturedApiCalls.forEach(apiCall => {
					if (apiTester.getMethodSchema(apiCall.method)) {
						expect(apiCall.args).toMatchAPIContract(apiCall.method);
					}
				});

				// Log contract validation results for visibility
				const validatedCalls = capturedApiCalls.filter(call =>
					apiTester.getMethodSchema(call.method)
				);

				console.log(`✅ Validated ${validatedCalls.length} API calls against contracts`);
			});

			it('should use contract-compliant test data', () => {
				const controllerTest = getControllerTest();

				// Generate contract-compliant test data
				const memberTestData = apiTester.generateValidTestData(
					'verenigingen.verenigingen.doctype.member.member.process_payment'
				);

				const ibanTestData = apiTester.generateValidTestData(
					'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
				);

				// Update controller with valid test data
				controllerTest.mockForm.doc.name = memberTestData.member_id || memberTestData.member;
				controllerTest.mockForm.doc.iban = ibanTestData.iban;

				// Controller should work with contract-compliant data
				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();

				// Verify data format compliance
				expect(controllerTest.mockForm.doc.name).toBeDefined();
				expect(controllerTest.mockForm.doc.name).toMatch(/^(Assoc-)?Member-\d{4}-\d{2}-\d{4}$/);
				expect(controllerTest.mockForm.doc.iban).toMatch(/^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$/);
			});

			it('should detect parameter mismatches in API calls', () => {
				const controllerTest = getControllerTest();

				// Mock frappe.call to simulate parameter mismatch
				const callsWithErrors = [];
				global.frappe.call = jest.fn((options) => {
					// Simulate common parameter naming errors
					if (options.args && options.args.member_id) {
						// JavaScript sends 'member_id' but Python expects 'member'
						const result = apiTester.validateFrappeCall({
							method: options.method,
							args: { member_id: options.args.member_id } // Wrong parameter name
						});

						if (!result.valid) {
							callsWithErrors.push({
								method: options.method,
								error: result.errors[0].message
							});
						}
					}
				});

				// Simulate API call with wrong parameter names
				global.frappe.call({
					method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
					args: { member_id: 'WRONG-PARAM-NAME' } // Should be 'member' not 'member_id'
				});

				// Verify that parameter mismatches are detected
				expect(callsWithErrors.length).toBeGreaterThan(0);
				expect(callsWithErrors[0].error).toContain('required');
			});
		},

		'Contract-Based Mock Responses': (getControllerTest) => {
			it('should provide contract-compliant mock responses', () => {
				const controllerTest = getControllerTest();

				// Mock API responses based on contract schemas
				global.frappe.call = jest.fn((options) => {
					if (options.method.includes('get_current_dues_schedule_details')) {
						const schema = apiTester.getMethodSchema(options.method);

						// Generate mock response matching the schema
						const mockResponse = {
							has_schedule: true, // Required field
							schedule_name: 'SCHED-001',
							dues_rate: 25.00,
							frequency: 'Monthly'
						};

						// Verify our mock response matches contract
						expect(mockResponse).toEqual(
							expect.objectContaining({
								has_schedule: expect.any(Boolean)
							})
						);

						if (options.callback) {
							options.callback(mockResponse);
						}
					}
				});

				// Trigger controller code that makes API calls
				controllerTest.testEvent('refresh');

				// Verify API calls were made with proper mock responses
				expect(global.frappe.call).toHaveBeenCalled();
			});
		},

		'Contract Coverage Analysis': (getControllerTest) => {
			it('should analyze API contract coverage', () => {
				const controllerTest = getControllerTest();

				// Get all available API methods with schemas
				const availableMethods = apiTester.getAvailableMethods();
				const memberRelatedMethods = availableMethods.filter(method =>
					method.includes('member.member')
				);

				console.log('📊 Available Member API Contract Methods:', memberRelatedMethods.length);
				memberRelatedMethods.forEach(method => {
					console.log(`   - ${method}`);
				});

				// Trigger controller to capture actual API usage
				controllerTest.testEvent('refresh');

				// Analyze which contracts are actually used vs available
				const usedMethods = capturedApiCalls.map(call => call.method);
				const contractCovered = usedMethods.filter(method =>
					memberRelatedMethods.includes(method)
				);

				console.log('📈 Contract Coverage Report:');
				console.log(`   Used Methods: ${usedMethods.length}`);
				console.log(`   Contract Covered: ${contractCovered.length}`);
				console.log(`   Coverage Rate: ${((contractCovered.length / usedMethods.length) * 100).toFixed(1)}%`);

				// Ensure at least some contract coverage
				expect(memberRelatedMethods.length).toBeGreaterThan(0);
			});
		}
	};

	// Create the controller test suite with API contract integration
	describe('Member Controller with Simple API Contracts',
		createControllerTestSuite(memberControllerConfig, memberApiContractTests)
	);
});
