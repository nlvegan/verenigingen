/* eslint-env jest */
/**
 * @fileoverview Comprehensive Donation Controller Tests
 *
 * Tests the Donation DocType JavaScript controller.
 *
 * This suite used to exercise a "Create Payment Entry" button. That button was a
 * fossil of the ERPNext Non Profit module, where Donation was submittable and
 * settled via Payment Entry. This app's Donation has never carried
 * `is_submittable`, so the button's `docstatus === 1` gate never fired, and
 * donation payments post as Bank Transaction -> Journal Entry instead. Button
 * and handler are gone.
 *
 * The suite now pins the negative property: the Donation form offers no Payment
 * Entry affordance, in any document state. Reintroducing the button turns this
 * suite red.
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
	controllerPath:
		'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/donation/donation.js',
	expectedHandlers: ['refresh'],
	defaultDoc: {
		doctype: 'Donation',
		name: 'DON-2024-TEST-001',
		docstatus: 1, // Submitted
		paid: 0, // Unpaid - eligible for payment entry creation
		donor_name: 'Test Donor',
		amount: 100.0,
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
	'No Payment Entry affordance': (getControllerTest) => {
		it('exposes no make_payment_entry handler', () => {
			const controllerTest = getControllerTest();

			expect(controllerTest.handlers.make_payment_entry).toBeUndefined();
		});

		it('adds no button in any docstatus/paid combination', () => {
			const controllerTest = getControllerTest();
			// The full matrix, including the docstatus=1 state the old button was
			// gated on. Donation is not submittable, so 1 and 2 are only reachable
			// by direct db writes — but the form must offer nothing in any of them.
			const states = [
				{ name: 'draft unpaid', docstatus: 0, paid: 0 },
				{ name: 'draft paid', docstatus: 0, paid: 1 },
				{ name: 'submitted unpaid', docstatus: 1, paid: 0 },
				{ name: 'submitted paid', docstatus: 1, paid: 1 },
				{ name: 'cancelled unpaid', docstatus: 2, paid: 0 }
			];

			states.forEach((state) => {
				controllerTest.mockForm.doc.docstatus = state.docstatus;
				controllerTest.mockForm.doc.paid = state.paid;
				controllerTest.mockForm.add_custom_button.mockClear();

				controllerTest.testEvent('refresh');

				expect({
					state: state.name,
					calls: controllerTest.mockForm.add_custom_button.mock.calls.length
				}).toEqual({ state: state.name, calls: 0 });
			});
		});

		it('never calls the ERPNext get_payment_entry endpoint', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;
			global.frappe.call.mockClear();

			controllerTest.testEvent('refresh');

			// A Donation is settled as Bank Transaction -> Journal Entry. Any
			// client-side round trip to the Payment Entry builder is a regression.
			const methodsCalled = global.frappe.call.mock.calls.map((args) => args[0] && args[0].method);
			expect(methodsCalled).not.toContain(
				'erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry'
			);
			expect(methodsCalled).toEqual([]);
		});
	},

	'Form State Management': (getControllerTest) => {
		it('should handle edge cases with missing or invalid data', () => {
			const controllerTest = getControllerTest();
			const edgeCases = [
				{ description: 'Missing paid field', data: { docstatus: 1 } },
				{ description: 'Missing docstatus field', data: { paid: 0 } },
				{
					description: 'Zero amount donation',
					data: { docstatus: 1, paid: 0, amount: 0 }
				},
				{
					description: 'Negative amount donation',
					data: { docstatus: 1, paid: 0, amount: -50 }
				}
			];

			edgeCases.forEach((edgeCase) => {
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
				amount: 750.5,
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
			controllerTest.mockForm.add_custom_button.mockClear();
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();

			// ...and still offer no Payment Entry affordance
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
		});
	},

	'Integration Testing': (getControllerTest) => {
		it('never routes the user to a Payment Entry form', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.name = 'DON-INTEGRATION-001';
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;
			global.frappe.set_route.mockClear();
			global.frappe.model.sync.mockClear();

			controllerTest.testEvent('refresh');

			// The deleted handler synced a Payment Entry and routed to its form.
			expect(global.frappe.model.sync).not.toHaveBeenCalled();
			expect(global.frappe.set_route).not.toHaveBeenCalled();
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

			// ...and no refresh should have added a button
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
		});

		it('should maintain state consistency across multiple operations', () => {
			const controllerTest = getControllerTest();

			// Toggling paid used to flip the button on and off. Nothing should
			// appear now, in either direction.
			controllerTest.mockForm.doc.docstatus = 1;
			controllerTest.mockForm.doc.paid = 0;
			controllerTest.mockForm.add_custom_button.mockClear();
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();

			controllerTest.mockForm.doc.paid = 1;
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();

			controllerTest.mockForm.doc.paid = 0;
			controllerTest.testEvent('refresh');
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalled();
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
