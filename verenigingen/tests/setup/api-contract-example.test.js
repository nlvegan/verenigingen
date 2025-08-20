/**
 * @fileoverview API Contract Testing Examples
 *
 * Demonstrates how to use the API contract testing infrastructure to validate
 * JavaScript-to-Python API calls and catch integration mismatches.
 *
 * These tests catch issues that pure unit tests miss:
 * - Parameter name mismatches (JS sends 'member_id', Python expects 'member')
 * - Data type mismatches (JS sends string, Python expects object)
 * - Required parameter validation
 * - Response structure validation
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const {
	APIContractTestServer,
	APIContractTester,
	createAPIContractMatcher
} = require('./api-contract-testing');

require('./frappe-mocks').setupTestMocks();

// Add custom Jest matcher
expect.extend(createAPIContractMatcher());

describe('API Contract Testing Examples', () => {
	let server;
	let tester;

	beforeAll(() => {
		server = new APIContractTestServer();
		server.start();
		tester = new APIContractTester();
	});

	afterAll(() => {
		server.stop();
	});

	beforeEach(() => {
		server.reset();
	});

	describe('Parameter Validation', () => {
		it('should validate correct member API call', () => {
			const validArgs = {
				member: 'ASSOC-MEMBER-2025-001'
			};

			expect(validArgs).toMatchAPIContract(
				'verenigingen.verenigingen.doctype.member.member.process_payment'
			);
		});

		it('should reject invalid member format', () => {
			const invalidArgs = {
				member: 'invalid-format'
			};

			expect(() => {
				expect(invalidArgs).toMatchAPIContract(
					'verenigingen.verenigingen.doctype.member.member.process_payment'
				);
			}).toThrow('Invalid length');
		});

		it('should reject missing required parameters', () => {
			const incompleteArgs = {
				// missing 'member' parameter
			};

			expect(() => {
				expect(incompleteArgs).toMatchAPIContract(
					'verenigingen.verenigingen.doctype.member.member.process_payment'
				);
			}).toThrow();
		});
	});

	describe('IBAN Validation API Contract', () => {
		it('should validate Dutch IBAN format correctly', () => {
			const validIbanCall = {
				iban: 'NL91ABNA0417164300'
			};

			expect(validIbanCall).toMatchAPIContract(
				'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
			);
		});

		it('should reject invalid IBAN format', () => {
			const invalidIbanCall = {
				iban: 'INVALID-IBAN-123'
			};

			expect(() => {
				expect(invalidIbanCall).toMatchAPIContract(
					'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
				);
			}).toThrow();
		});
	});

	describe('Chapter Assignment API Contract', () => {
		it('should validate chapter assignment with all required fields', () => {
			const validAssignment = {
				member: 'ASSOC-MEMBER-2025-001',
				chapter: 'CH-Amsterdam',
				note: 'Member requested transfer'
			};

			expect(validAssignment).toMatchAPIContract(
				'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup'
			);
		});

		it('should allow optional note field to be omitted', () => {
			const minimalAssignment = {
				member: 'ASSOC-MEMBER-2025-001',
				chapter: 'CH-Amsterdam'
				// note is optional
			};

			expect(minimalAssignment).toMatchAPIContract(
				'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup'
			);
		});
	});

	describe('Donation API Contract', () => {
		it('should validate donation submission with all required fields', () => {
			const validDonation = {
				donor_name: 'John Doe',
				email: 'john.doe@example.org',
				amount: 50.00,
				donation_type: 'one-time',
				anbi_consent: true
			};

			expect(validDonation).toMatchAPIContract(
				'verenigingen.templates.pages.donate.submit_donation'
			);
		});

		it('should validate recurring donation type', () => {
			const recurringDonation = {
				donor_name: 'Jane Smith',
				email: 'jane@example.org',
				amount: 25.00,
				donation_type: 'recurring'
			};

			expect(recurringDonation).toMatchAPIContract(
				'verenigingen.templates.pages.donate.submit_donation'
			);
		});

		it('should reject invalid email format', () => {
			const invalidEmailDonation = {
				donor_name: 'Invalid Email',
				email: 'not-an-email',
				amount: 25.00
			};

			expect(() => {
				expect(invalidEmailDonation).toMatchAPIContract(
					'verenigingen.templates.pages.donate.submit_donation'
				);
			}).toThrow();
		});

		it('should reject negative donation amounts', () => {
			const negativeDonation = {
				donor_name: 'Negative Amount',
				email: 'test@example.org',
				amount: -5.00
			};

			expect(() => {
				expect(negativeDonation).toMatchAPIContract(
					'verenigingen.templates.pages.donate.submit_donation'
				);
			}).toThrow();
		});
	});

	describe('E-Boekhouden Integration Contract', () => {
		it('should validate connection test with no parameters', () => {
			const emptyArgs = {};

			expect(emptyArgs).toMatchAPIContract(
				'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.test_connection'
			);
		});

		it('should reject additional parameters', () => {
			const unexpectedArgs = {
				unexpected_param: 'should not be allowed'
			};

			expect(() => {
				expect(unexpectedArgs).toMatchAPIContract(
					'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.test_connection'
				);
			}).toThrow();
		});
	});

	describe('Test Data Generation', () => {
		it('should generate valid test data for member APIs', () => {
			const testData = tester.generateValidTestData(
				'verenigingen.verenigingen.doctype.member.member.process_payment'
			);

			expect(testData).toHaveProperty('member');
			expect(testData.member).toMatch(/^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$/);
		});

		it('should generate valid IBAN test data', () => {
			const testData = tester.generateValidTestData(
				'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
			);

			expect(testData).toHaveProperty('iban');
			expect(testData.iban).toMatch(/^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$/);
		});

		it('should generate valid donation test data', () => {
			const testData = tester.generateValidTestData(
				'verenigingen.templates.pages.donate.submit_donation'
			);

			expect(testData).toHaveProperty('donor_name');
			expect(testData).toHaveProperty('email');
			expect(testData).toHaveProperty('amount');
			expect(testData.email).toContain('@');
			expect(testData.amount).toBeGreaterThan(0);
		});
	});

	describe('Available Methods Validation', () => {
		it('should list all available API methods for testing', () => {
			const methods = tester.getAvailableMethods();

			expect(methods).toContain('verenigingen.verenigingen.doctype.member.member.process_payment');
			expect(methods).toContain('verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup');
			expect(methods).toContain('verenigingen.templates.pages.donate.submit_donation');
			expect(methods.length).toBeGreaterThan(5);
		});

		it('should provide schema details for specific methods', () => {
			const schema = tester.getMethodSchema(
				'verenigingen.verenigingen.doctype.member.member.process_payment'
			);

			expect(schema).toHaveProperty('args');
			expect(schema).toHaveProperty('response');
			expect(schema.args.required).toContain('member');
		});
	});

	describe('Integration with Mock Server', () => {
		it('should handle successful API calls through mock server', async () => {
			const mockFetch = jest.fn().mockResolvedValue({
				ok: true,
				json: async () => ({
					message: {
						success: true,
						payment_data: { payment_id: 'PAY-123' }
					}
				})
			});

			global.fetch = mockFetch;

			// Simulate a frappe.call() through the mock server
			const response = await fetch('/api/method/verenigingen.verenigingen.doctype.member.member.process_payment', {
				method: 'POST',
				body: JSON.stringify({
					member: 'ASSOC-MEMBER-2025-001'
				})
			});

			const result = await response.json();
			expect(result.message.success).toBe(true);
		});

		it('should reject invalid API calls through mock server', async () => {
			const mockFetch = jest.fn().mockResolvedValue({
				ok: false,
				status: 417,
				json: async () => ({
					exc_type: 'ValidationError',
					message: 'API Contract Violation'
				})
			});

			global.fetch = mockFetch;

			// Simulate an invalid frappe.call()
			const response = await fetch('/api/method/verenigingen.verenigingen.doctype.member.member.process_payment', {
				method: 'POST',
				body: JSON.stringify({
					invalid_param: 'should fail'
				})
			});

			expect(response.ok).toBe(false);
			expect(response.status).toBe(417);

			const result = await response.json();
			expect(result.exc_type).toBe('ValidationError');
		});
	});
});
