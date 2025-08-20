/**
 * @fileoverview Comprehensive Donation Controller Tests
 *
 * Tests the Donation DocType JavaScript controller, focusing on payment entry workflows,
 * UI button management, and financial integration features using the centralized
 * controller testing infrastructure.
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 */

/* global describe, it, expect, jest, beforeEach, afterEach, beforeAll */

// Import centralized test infrastructure
const { createControllerTestSuite } = require('../../setup/controller-test-base');
const { createDomainTestBuilder } = require('../../setup/domain-test-builders');

// Initialize test environment
require('../../setup/frappe-mocks').setupTestMocks();

// Controller configuration
const donationConfig = {
	doctype: 'Donation',
	controllerPath: '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/donation/donation.js',
	expectedHandlers: ['refresh', 'make_payment_entry'],
	defaultDoc: {
		doctype: 'Donation',
		name: 'DON-2024-TEST-001',
		docstatus: 1, // Submitted
		paid: 0, // Unpaid - eligible for payment entry creation
		donor_name: 'Test Donor',
		amount: 100.00,
		currency: 'EUR',
		donation_date: '2024-07-15',
		donation_type: 'one-time',
		payment_method: 'SEPA Direct Debit',
		remarks: 'Test donation for controller testing'
	},
	// Custom field setup for Donation controller
	createMockForm(baseTest, overrides = {}) {
		const form = baseTest.createMockForm(overrides);

		// Set up payment utilities mocks
		global.frappe.call = jest.fn();
		global.frappe.model.sync = jest.fn();
		global.frappe.set_route = jest.fn();

		// Add donation-specific field structures
		form.fields_dict = {
			...form.fields_dict,
			// Donation basic fields
			donor_name: { df: { fieldtype: 'Data' } },
			amount: { df: { fieldtype: 'Currency' } },
			currency: { df: { fieldtype: 'Link' } },
			donation_date: { df: { fieldtype: 'Date' } },
			donation_type: { df: { fieldtype: 'Select' } },
			payment_method: { df: { fieldtype: 'Select' } },
			remarks: { df: { fieldtype: 'Text' } },

			// Payment status fields
			paid: { df: { fieldtype: 'Check' } },
			payment_entry: { df: { fieldtype: 'Link' } },

			// Financial integration fields
			project: { df: { fieldtype: 'Link' } },
			cost_center: { df: { fieldtype: 'Link' } },
			company: { df: { fieldtype: 'Link' } }
		};

		return form;
	}
};

// Custom test suites specific to Donation controller
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

		it('should not show Create Payment Entry button for paid donations', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.docstatus = 1; // Submitted
			controllerTest.mockForm.doc.paid = 1; // Paid

			// Reset mock to check for no calls
			controllerTest.mockForm.add_custom_button.mockClear();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify payment entry button is NOT added
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
		});

		it('should not show Create Payment Entry button for draft donations', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.docstatus = 0; // Draft
			controllerTest.mockForm.doc.paid = 0;

			// Reset mock to check for no calls
			controllerTest.mockForm.add_custom_button.mockClear();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify payment entry button is NOT added
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
		});

		it('should handle payment entry creation workflow', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.name = 'DON-2024-07-0004';
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;

			// Mock successful payment entry creation
			const mockPaymentEntry = {
				doctype: 'Payment Entry',
				name: 'PE-2024-07-0001',
				party_type: 'Customer',
				paid_amount: 125.00
			};

			global.frappe.call.mockImplementation(({ callback }) => {
				if (callback) {
					callback({ message: mockPaymentEntry });
				}
				return Promise.resolve({ message: mockPaymentEntry });
			});

			global.frappe.model.sync.mockReturnValue([mockPaymentEntry]);

			// Trigger make_payment_entry event
			controllerTest.testEvent('make_payment_entry');

			// Verify API call was made
			expect(global.frappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.utils.payment_utils.get_donation_payment_entry',
				args: {
					dt: 'Donation',
					dn: 'DON-2024-07-0004'
				},
				callback: expect.any(Function)
			});

			// Verify payment entry was synced
			expect(global.frappe.model.sync).toHaveBeenCalledWith(mockPaymentEntry);

			// Verify navigation to payment entry
			expect(global.frappe.set_route).toHaveBeenCalledWith('Form', 'Payment Entry', 'PE-2024-07-0001');
		});

		it('should handle different donation statuses correctly', () => {
			const controllerTest = getControllerTest();
			const testCases = [
				{ name: 'Draft donation', docstatus: 0, paid: 0, expectButton: false },
				{ name: 'Submitted unpaid donation', docstatus: 1, paid: 0, expectButton: true },
				{ name: 'Submitted paid donation', docstatus: 1, paid: 1, expectButton: false },
				{ name: 'Cancelled donation', docstatus: 2, paid: 0, expectButton: false }
			];

			testCases.forEach(testCase => {
				// Reset form and mock for each test case
				controllerTest.mockForm.doc.docstatus = testCase.docstatus;
				controllerTest.mockForm.doc.paid = testCase.paid;
				controllerTest.mockForm.add_custom_button.mockClear();

				// Trigger refresh event
				controllerTest.testEvent('refresh');

				if (testCase.expectButton) {
					expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
				} else {
					expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
				}
			});
		});
	},

	'Form State Management': (getControllerTest) => {
		it('should handle edge cases with missing or invalid data', () => {
			const controllerTest = getControllerTest();
			const edgeCases = [
				{ description: 'Missing paid field', data: { docstatus: 1 } },
				{ description: 'Missing docstatus field', data: { paid: 0 } },
				{ description: 'Zero amount donation', data: { docstatus: 1, paid: 0, amount: 0 } },
				{ description: 'Negative amount donation', data: { docstatus: 1, paid: 0, amount: -50 } }
			];

			edgeCases.forEach(edgeCase => {
				// Apply edge case data
				Object.assign(controllerTest.mockForm.doc, edgeCase.data);

				// Should not throw errors
				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();
			});
		});

		it('should handle complex donation data structures', () => {
			const controllerTest = getControllerTest();

			// Set up complex donation data
			controllerTest.mockForm.doc = {
				...controllerTest.mockForm.doc,
				docstatus: 1,
				paid: 0,
				donor_name: 'Complex Test Donor',
				amount: 750.50,
				currency: 'EUR',
				donation_date: '2024-07-15',
				project: 'Environmental Campaign',
				cost_center: 'Rotterdam Chapter',
				company: 'Vereniging Nederland',
				remarks: 'Monthly recurring donation for climate action',
				// Additional custom fields that might exist
				tax_deduction: true,
				donor_category: 'Major Donor'
			};

			// Should handle complex data without errors
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();

			// Button should still be shown for eligible donations
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
		});
	},

	'Integration Testing': (getControllerTest) => {
		it('should integrate properly with payment utilities API', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.name = 'DON-INTEGRATION-001';
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;

			// Mock realistic payment entry response
			const paymentResponse = {
				doctype: 'Payment Entry',
				name: 'PE-INTEGRATION-001',
				party_type: 'Customer',
				paid_amount: 300.00,
				received_amount: 300.00,
				reference_no: 'DON-INTEGRATION-001',
				reference_date: '2024-07-15'
			};

			global.frappe.call.mockImplementation(({ callback }) => {
				if (callback) {
					callback({ message: paymentResponse });
				}
				return Promise.resolve({ message: paymentResponse });
			});

			global.frappe.model.sync.mockReturnValue([paymentResponse]);

			// Trigger make_payment_entry workflow
			controllerTest.testEvent('make_payment_entry');

			// Verify correct API method called
			expect(global.frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: 'verenigingen.utils.payment_utils.get_donation_payment_entry'
				})
			);

			// Verify correct arguments passed
			const callArgs = global.frappe.call.mock.calls[0][0];
			expect(callArgs.args).toEqual({
				dt: 'Donation',
				dn: 'DON-INTEGRATION-001'
			});
		});

		it('should call payment entry API with correct parameters', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.name = 'DON-API-001';
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;

			// Mock successful API response
			global.frappe.call.mockImplementation(({ callback }) => {
				if (callback) {
					callback({ message: { name: 'PE-TEST-001', doctype: 'Payment Entry' } });
				}
			});

			global.frappe.model.sync.mockReturnValue([{ name: 'PE-TEST-001', doctype: 'Payment Entry' }]);

			// Should execute without errors
			expect(() => {
				controllerTest.testEvent('make_payment_entry');
			}).not.toThrow();

			// Verify API call was made with correct parameters
			expect(global.frappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.utils.payment_utils.get_donation_payment_entry',
				args: {
					dt: 'Donation',
					dn: 'DON-API-001'
				},
				callback: expect.any(Function)
			});
		});
	},

	'Error Handling': (getControllerTest) => {
		it('should handle undefined donation fields gracefully', () => {
			const controllerTest = getControllerTest();
			delete controllerTest.mockForm.doc.docstatus; // Remove docstatus
			delete controllerTest.mockForm.doc.paid; // Remove paid status

			// Should not throw errors
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Performance and Reliability': (getControllerTest) => {
		it('should handle multiple rapid refresh events efficiently', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;

			const startTime = performance.now();

			// Trigger multiple refresh events rapidly
			for (let i = 0; i < 5; i++) {
				controllerTest.testEvent('refresh');
			}

			const endTime = performance.now();
			const executionTime = endTime - startTime;

			// Should complete within reasonable time (less than 100ms)
			expect(executionTime).toBeLessThan(100);

			// Button should be added for each refresh
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
		});

		it('should maintain state consistency across multiple operations', () => {
			const controllerTest = getControllerTest();

			// Start with eligible donation
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;

			// First refresh - should show button
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();

			// Change to paid - should not show button
			controllerTest.mockForm.doc.paid = 1;
			controllerTest.mockForm.add_custom_button.mockClear();
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();

			// Back to unpaid - should show button again
			controllerTest.mockForm.doc.paid = 0;
			controllerTest.mockForm.add_custom_button.mockClear();
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
		});
	}
};

// Create and export the test suite
describe('Donation Controller (Comprehensive Tests)', createControllerTestSuite(donationConfig, customDonationTests));

// Export test utilities for reuse
module.exports = {
	donationConfig,
	customDonationTests
};
