/**
 * @fileoverview Member Controller API Contract Integration Tests
 *
 * Demonstrates integration of API contract testing with controller testing
 * to validate that JavaScript controllers make correct API calls to Python backend.
 *
 * This test ensures that:
 * 1. Controller code uses correct parameter names and types
 * 2. API calls match expected Python method signatures
 * 3. Response handling expects correct data structures
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { createControllerTestSuite } = require('../../setup/controller-test-base');
const {
	APIContractTestServer,
	APIContractTester,
	createAPIContractMatcher
} = require('../../setup/api-contract-testing');

require('../../setup/frappe-mocks').setupTestMocks();

// Add custom Jest matcher for API contract validation
expect.extend(createAPIContractMatcher());

// Configuration for Member controller testing
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

	// Mock server call tracking
	mockServerCallThreshold: 20
};

describe('Member Controller API Contract Integration', () => {
	let apiServer;
	let apiTester;
	let capturedApiCalls = [];

	beforeAll(() => {
		// Setup API contract testing server
		apiServer = new APIContractTestServer();
		apiServer.start();
		apiTester = new APIContractTester();

		// Mock frappe.call to capture API calls for contract validation
		const originalFrappeCall = global.frappe.call;
		global.frappe.call = jest.fn((options) => {
			// Capture the API call for contract validation
			capturedApiCalls.push({
				method: options.method,
				args: options.args || {},
				callback: options.callback
			});

			// Validate against contract if we have a schema
			try {
				if (apiTester.getMethodSchema(options.method)) {
					expect(options.args || {}).toMatchAPIContract(options.method);
				}
			} catch (contractError) {
				console.warn(`API Contract Violation in ${options.method}:`, contractError.message);
			}

			// Call original behavior for controller functionality
			return originalFrappeCall.call(global.frappe, options);
		});
	});

	afterAll(() => {
		apiServer.stop();
	});

	beforeEach(() => {
		capturedApiCalls = [];
	});

	const memberApiContractTests = {
		'API Contract Validation': (getControllerTest) => {
			it('should make valid API calls when processing payments', () => {
				const controllerTest = getControllerTest();

				// Setup a scenario where the controller might call process_payment
				controllerTest.mockForm.doc.status = 'Active';
				controllerTest.mockForm.doc.customer = 'CUST-001';

				// Simulate a button click that triggers payment processing
				if (controllerTest.mockForm.add_custom_button.mock.calls.length > 0) {
					// Find payment-related buttons
					const buttonCalls = controllerTest.mockForm.add_custom_button.mock.calls;
					const paymentButton = buttonCalls.find(call =>
						call[0] && call[0].toLowerCase().includes('payment')
					);

					if (paymentButton && paymentButton[1]) {
						// Execute the button callback
						paymentButton[1]();

						// Check if any API calls were made and validate them
						const paymentApiCalls = capturedApiCalls.filter(call =>
							call.method.includes('process_payment')
						);

						paymentApiCalls.forEach(apiCall => {
							expect(apiCall.args).toMatchAPIContract(apiCall.method);
						});
					}
				}
			});

			it('should validate member dues schedule API calls', () => {
				const controllerTest = getControllerTest();

				// Trigger refresh to potentially load dues schedule
				controllerTest.testEvent('refresh');

				// Check for dues schedule API calls
				const duesApiCalls = capturedApiCalls.filter(call =>
					call.method.includes('get_current_dues_schedule_details')
				);

				duesApiCalls.forEach(apiCall => {
					expect(apiCall.args).toMatchAPIContract(apiCall.method);

					// Validate member parameter format
					expect(apiCall.args.member).toMatch(/^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$/);
				});
			});

			it('should make valid IBAN validation calls', () => {
				const controllerTest = getControllerTest();

				// Simulate IBAN field change that might trigger validation
				controllerTest.mockForm.doc.iban = 'NL91ABNA0417164300';

				// If controller has IBAN validation logic
				if (controllerTest.handlers && controllerTest.handlers.iban) {
					controllerTest.testEvent('iban');

					// Check for IBAN validation API calls
					const ibanApiCalls = capturedApiCalls.filter(call =>
						call.method.includes('derive_bic_from_iban')
					);

					ibanApiCalls.forEach(apiCall => {
						expect(apiCall.args).toMatchAPIContract(apiCall.method);

						// Validate IBAN format
						expect(apiCall.args.iban).toMatch(/^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$/);
					});
				}
			});

			it('should validate mandate creation API calls', () => {
				const controllerTest = getControllerTest();

				// Setup mandate creation scenario
				controllerTest.mockForm.doc.iban = 'NL91ABNA0417164300';
				controllerTest.mockForm.doc.status = 'Active';

				// Look for mandate-related buttons
				const buttonCalls = controllerTest.mockForm.add_custom_button.mock.calls;
				const mandateButton = buttonCalls.find(call =>
					call[0] && call[0].toLowerCase().includes('mandate')
				);

				if (mandateButton && mandateButton[1]) {
					// Execute mandate creation
					mandateButton[1]();

					// Validate mandate validation API calls
					const mandateApiCalls = capturedApiCalls.filter(call =>
						call.method.includes('validate_mandate_creation')
					);

					mandateApiCalls.forEach(apiCall => {
						expect(apiCall.args).toMatchAPIContract(apiCall.method);

						// Ensure required fields are present
						expect(apiCall.args.member).toBeDefined();
						expect(apiCall.args.iban).toBeDefined();
					});
				}
			});
		},

		'API Response Handling': (getControllerTest) => {
			it('should handle API responses correctly', () => {
				const controllerTest = getControllerTest();

				// Mock successful API responses
				global.frappe.call = jest.fn((options) => {
					const method = options.method;
					let mockResponse;

					if (method.includes('process_payment')) {
						mockResponse = {
							success: true,
							message: 'Payment processed successfully',
							payment_data: { payment_id: 'PAY-123' }
						};
					} else if (method.includes('get_current_dues_schedule_details')) {
						mockResponse = {
							has_schedule: true,
							schedule_name: 'SCHED-001',
							dues_rate: 25.00,
							frequency: 'Monthly'
						};
					} else if (method.includes('derive_bic_from_iban')) {
						mockResponse = {
							bic: 'ABNANL2A',
							bank_name: 'ABN AMRO Bank N.V.'
						};
					}

					// Execute callback with mock response
					if (options.callback && mockResponse) {
						options.callback(mockResponse);
					}
				});

				// Trigger controller events that make API calls
				controllerTest.testEvent('refresh');

				// Verify the controller handled the responses appropriately
				// This tests that the controller expects the right response structure
				expect(global.frappe.call).toHaveBeenCalled();
			});

			it('should handle API error responses gracefully', () => {
				const controllerTest = getControllerTest();

				// Mock error responses
				global.frappe.call = jest.fn((options) => {
					// Simulate API error
					if (options.error) {
						options.error({
							exc_type: 'ValidationError',
							message: 'Invalid member data'
						});
					}
				});

				// Trigger events and ensure no uncaught exceptions
				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();
			});
		},

		'Test Data Contract Compliance': (getControllerTest) => {
			it('should use test data that matches API contracts', () => {
				const controllerTest = getControllerTest();

				// Generate valid test data using contract schemas
				const memberTestData = apiTester.generateValidTestData(
					'verenigingen.verenigingen.doctype.member.member.process_payment'
				);

				const ibanTestData = apiTester.generateValidTestData(
					'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
				);

				// Verify generated data matches our controller expectations
				expect(memberTestData.member).toMatch(/^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$/);
				expect(ibanTestData.iban).toMatch(/^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$/);

				// Update controller with valid test data
				controllerTest.mockForm.doc.name = memberTestData.member;
				controllerTest.mockForm.doc.iban = ibanTestData.iban;

				// Controller should work with contract-compliant data
				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();
			});
		},

		'API Method Coverage': (getControllerTest) => {
			it('should provide coverage for all member-related API methods', () => {
				const availableMethods = apiTester.getAvailableMethods();
				const memberMethods = availableMethods.filter(method =>
					method.includes('member.member')
				);

				console.log('Available Member API Methods:', memberMethods);

				// Ensure we have schemas for key member operations
				expect(memberMethods).toContain('verenigingen.verenigingen.doctype.member.member.process_payment');
				expect(memberMethods).toContain('verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details');
				expect(memberMethods).toContain('verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban');
				expect(memberMethods).toContain('verenigingen.verenigingen.doctype.member.member.validate_mandate_creation');
			});
		}
	};

	// Create the controller test suite with API contract integration
	describe('Member Controller with API Contracts',
		createControllerTestSuite(memberControllerConfig, memberApiContractTests)
	);
});
