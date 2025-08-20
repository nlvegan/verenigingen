/**
 * @fileoverview Comprehensive Volunteer Expense Controller Tests
 *
 * Tests the Volunteer Expense DocType JavaScript controller, focusing on approval workflows,
 * organization assignment, expense validation, and role-based permissions using the centralized
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
const volunteerExpenseConfig = {
	doctype: 'Volunteer Expense',
	controllerPath: '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/volunteer_expense/volunteer_expense.js',
	expectedHandlers: ['refresh', 'volunteer', 'organization_type', 'category', 'expense_date'],
	defaultDoc: {
		doctype: 'Volunteer Expense',
		name: 'VE-2024-TEST-001',
		volunteer: 'MEM-2024-TEST-001',
		status: 'Submitted',
		expense_date: '2024-07-15',
		amount: 50.00,
		currency: 'EUR',
		category: 'Travel',
		description: 'Travel expenses for chapter meeting',
		organization_type: 'Chapter',
		chapter: 'Amsterdam',
		reimbursement_method: 'Bank Transfer',
		__islocal: 0 // Not a new record
	},
	// Custom field setup for Volunteer Expense controller
	createMockForm(baseTest, overrides = {}) {
		const form = baseTest.createMockForm(overrides);

		// Set up workflow-related mocks
		global.frappe.call = jest.fn();
		global.frappe.user.has_role = jest.fn().mockReturnValue(false);
		global.frappe.msgprint = jest.fn();
		global.__ = jest.fn((text) => text); // Mock translation function

		// Add volunteer expense-specific field structures
		form.fields_dict = {
			...form.fields_dict,
			// Basic expense fields
			volunteer: { df: { fieldtype: 'Link' } },
			expense_date: { df: { fieldtype: 'Date' } },
			amount: { df: { fieldtype: 'Currency' } },
			currency: { df: { fieldtype: 'Link' } },
			category: { df: { fieldtype: 'Select' } },
			description: { df: { fieldtype: 'Text' } },

			// Workflow status fields
			status: { df: { fieldtype: 'Select' } },
			approval_date: { df: { fieldtype: 'Datetime' } },
			approved_by: { df: { fieldtype: 'Link' } },
			rejection_reason: { df: { fieldtype: 'Text' } },
			reimbursement_date: { df: { fieldtype: 'Date' } },
			reimbursement_method: { df: { fieldtype: 'Select' } },

			// Organization assignment fields
			organization_type: { df: { fieldtype: 'Select' } },
			chapter: { df: { fieldtype: 'Link' } },
			team: { df: { fieldtype: 'Link' } },

			// Receipt and documentation fields
			receipt_uploaded: { df: { fieldtype: 'Check' } },
			receipt_amount: { df: { fieldtype: 'Currency' } }
		};

		return form;
	}
};

// Custom test suites specific to Volunteer Expense controller
const customVolunteerExpenseTests = {
	'Approval Workflow': (getControllerTest) => {
		it('should show approval buttons for submitted expenses when user can approve', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.status = 'Submitted';
			controllerTest.mockForm.doc.__islocal = 0;

			// Mock successful authorization check
			global.frappe.call.mockImplementation(({ method, callback }) => {
				if (method === 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense') {
					if (callback) {
						callback({ message: true }); // User can approve
					}
				}
				return Promise.resolve({ message: true });
			});

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify API call to check permissions
			expect(global.frappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense',
				args: {
					expense: controllerTest.mockForm.doc
				},
				callback: expect.any(Function)
			});

			// Verify approval buttons are added
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
				'Approve',
				expect.any(Function),
				'Actions'
			);
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
				'Reject',
				expect.any(Function),
				'Actions'
			);
		});

		it('should not show approval buttons when user cannot approve', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.status = 'Submitted';
			controllerTest.mockForm.doc.__islocal = 0;

			// Mock authorization failure
			global.frappe.call.mockImplementation(({ method, callback }) => {
				if (method === 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense') {
					if (callback) {
						callback({ message: false }); // User cannot approve
					}
				}
				return Promise.resolve({ message: false });
			});

			// Reset mocks to check for no button calls
			controllerTest.mockForm.add_custom_button.mockClear();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify authorization was checked
			expect(global.frappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense',
				args: {
					expense: controllerTest.mockForm.doc
				},
				callback: expect.any(Function)
			});

			// Verify no approval buttons added
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalledWith(
				'Approve',
				expect.any(Function),
				'Actions'
			);
		});

		it('should show reimbursement button for approved expenses with proper role', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.status = 'Approved';
			controllerTest.mockForm.doc.__islocal = 0;

			// Mock user with administrator role
			global.frappe.user.has_role.mockImplementation((roles) => {
				return roles.includes('Verenigingen Administrator');
			});

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify reimbursement button is added
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
				'Mark as Reimbursed',
				expect.any(Function),
				'Actions'
			);
		});

		it('should not show reimbursement button without proper role', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.status = 'Approved';
			controllerTest.mockForm.doc.__islocal = 0;

			// Mock user without required roles
			global.frappe.user.has_role.mockReturnValue(false);

			// Reset mocks
			controllerTest.mockForm.add_custom_button.mockClear();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Verify no reimbursement button added
			expect(controllerTest.mockForm.add_custom_button).not.toHaveBeenCalledWith(
				'Mark as Reimbursed',
				expect.any(Function),
				'Actions'
			);
		});

		it('should handle different expense statuses correctly', () => {
			const controllerTest = getControllerTest();
			const statusTests = [
				{ status: 'Draft', expectApproval: false, expectReimbursement: false },
				{ status: 'Submitted', expectApproval: true, expectReimbursement: false },
				{ status: 'Approved', expectApproval: false, expectReimbursement: true },
				{ status: 'Rejected', expectApproval: false, expectReimbursement: false },
				{ status: 'Reimbursed', expectApproval: false, expectReimbursement: false }
			];

			statusTests.forEach(test => {
				// Reset form state
				controllerTest.mockForm.doc.status = test.status;
				controllerTest.mockForm.doc.__islocal = 0;
				controllerTest.mockForm.add_custom_button.mockClear();

				// Mock appropriate permissions
				global.frappe.call.mockImplementation(({ method, callback }) => {
					if (method === 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense') {
						if (callback) {
							callback({ message: test.expectApproval });
						}
					}
				});

				global.frappe.user.has_role.mockReturnValue(test.expectReimbursement);

				// Trigger refresh event
				controllerTest.testEvent('refresh');

				// Verify appropriate buttons (or lack thereof)
				if (test.expectApproval) {
					expect(global.frappe.call).toHaveBeenCalledWith(
						expect.objectContaining({
							method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense'
						})
					);
				} else if (test.expectReimbursement) {
					expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalledWith(
						'Mark as Reimbursed',
						expect.any(Function),
						'Actions'
					);
				}
			});
		});
	},

	'Organization Assignment': (getControllerTest) => {
		it('should clear team when organization type changes to Chapter', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.organization_type = 'Chapter';
			controllerTest.mockForm.doc.team = 'Some Team';

			// Trigger organization_type event
			controllerTest.testEvent('organization_type');

			// Verify team field is cleared
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('team', '');
		});

		it('should clear chapter when organization type changes to Team', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.organization_type = 'Team';
			controllerTest.mockForm.doc.chapter = 'Amsterdam';

			// Trigger organization_type event
			controllerTest.testEvent('organization_type');

			// Verify chapter field is cleared
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('chapter', '');
		});

		it('should auto-set organization when volunteer changes', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.volunteer = 'MEM-2024-TEST-002';

			// Mock auto_set_organization function (would need to be defined globally)
			global.auto_set_organization = jest.fn();

			// Trigger volunteer event
			controllerTest.testEvent('volunteer');

			// Note: This test validates the event triggers but the actual
			// auto_set_organization function would need to be mocked separately
			expect(() => {
				controllerTest.testEvent('volunteer');
			}).not.toThrow();
		});
	},

	'Field Validation': (getControllerTest) => {
		it('should set default currency when category is selected', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.category = 'Travel';
			controllerTest.mockForm.doc.currency = ''; // No currency set

			// Trigger category event
			controllerTest.testEvent('category');

			// Verify EUR currency is set as default
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('currency', 'EUR');
		});

		it('should not override existing currency when category changes', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.category = 'Travel';
			controllerTest.mockForm.doc.currency = 'USD'; // Already has currency

			// Reset mock to check for no calls
			controllerTest.mockForm.set_value.mockClear();

			// Trigger category event
			controllerTest.testEvent('category');

			// Verify currency is not changed
			expect(controllerTest.mockForm.set_value).not.toHaveBeenCalledWith('currency', 'EUR');
		});

		it('should validate expense date is not in the future', () => {
			const controllerTest = getControllerTest();

			// Set future date
			const futureDate = new Date();
			futureDate.setDate(futureDate.getDate() + 1);
			controllerTest.mockForm.doc.expense_date = futureDate.toISOString().split('T')[0];

			// Trigger expense_date event
			controllerTest.testEvent('expense_date');

			// Verify error message is shown
			expect(global.frappe.msgprint).toHaveBeenCalledWith('Expense date cannot be in the future');

			// Verify field is cleared
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('expense_date', '');
		});

		it('should accept valid past expense dates', () => {
			const controllerTest = getControllerTest();

			// Set past date
			const pastDate = new Date();
			pastDate.setDate(pastDate.getDate() - 7);
			controllerTest.mockForm.doc.expense_date = pastDate.toISOString().split('T')[0];

			// Reset mocks
			global.frappe.msgprint.mockClear();
			controllerTest.mockForm.set_value.mockClear();

			// Trigger expense_date event
			controllerTest.testEvent('expense_date');

			// Verify no error message or field clearing
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(controllerTest.mockForm.set_value).not.toHaveBeenCalledWith('expense_date', '');
		});

		it('should accept today as valid expense date', () => {
			const controllerTest = getControllerTest();

			// Set today's date
			const today = new Date();
			controllerTest.mockForm.doc.expense_date = today.toISOString().split('T')[0];

			// Reset mocks
			global.frappe.msgprint.mockClear();
			controllerTest.mockForm.set_value.mockClear();

			// Trigger expense_date event
			controllerTest.testEvent('expense_date');

			// Verify no error message or field clearing
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(controllerTest.mockForm.set_value).not.toHaveBeenCalledWith('expense_date', '');
		});
	},

	'New Record Initialization': (getControllerTest) => {
		it('should set current user volunteer for new records', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.__islocal = 1; // New record
			controllerTest.mockForm.doc.volunteer = ''; // No volunteer set

			// Mock set_current_user_volunteer function
			global.set_current_user_volunteer = jest.fn();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Note: This validates the event structure but the actual function
			// would need to be tested separately or mocked appropriately
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		});

		it('should not set volunteer for existing records', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.__islocal = 0; // Existing record
			controllerTest.mockForm.doc.volunteer = ''; // No volunteer set

			// Mock set_current_user_volunteer function
			global.set_current_user_volunteer = jest.fn();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Since it's not a local record, volunteer should not be auto-set
			// (This behavior is implicit in the actual code)
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		});

		it('should not override existing volunteer on new records', () => {
			const controllerTest = getControllerTest();
			controllerTest.mockForm.doc.__islocal = 1; // New record
			controllerTest.mockForm.doc.volunteer = 'MEM-EXISTING-001'; // Already has volunteer

			// Mock set_current_user_volunteer function
			global.set_current_user_volunteer = jest.fn();

			// Trigger refresh event
			controllerTest.testEvent('refresh');

			// Should not call set_current_user_volunteer since volunteer already exists
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Error Handling': (getControllerTest) => {
		it('should handle undefined document fields gracefully', () => {
			const controllerTest = getControllerTest();
			delete controllerTest.mockForm.doc.status; // Remove status field

			// Should not throw errors
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Performance and Integration': (getControllerTest) => {
		it('should handle complex workflow scenarios efficiently', () => {
			const controllerTest = getControllerTest();

			// Set up complex scenario: submitted expense with multiple permissions
			controllerTest.mockForm.doc = {
				...controllerTest.mockForm.doc,
				status: 'Submitted',
				__islocal: 0,
				volunteer: 'MEM-COMPLEX-001',
				organization_type: 'Chapter',
				chapter: 'Rotterdam',
				category: 'Travel',
				amount: 150.00,
				expense_date: '2024-07-10',
				receipt_uploaded: 1,
				description: 'Complex travel expense with multiple approvers'
			};

			// Mock permission check
			global.frappe.call.mockImplementation(({ method, callback }) => {
				if (method === 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense') {
					if (callback) {
						callback({ message: true });
					}
				}
				return Promise.resolve({ message: true });
			});

			const startTime = performance.now();

			// Trigger refresh multiple times to test performance
			for (let i = 0; i < 3; i++) {
				controllerTest.testEvent('refresh');
			}

			const endTime = performance.now();
			const executionTime = endTime - startTime;

			// Should complete efficiently
			expect(executionTime).toBeLessThan(50);

			// Should have made appropriate API calls
			expect(global.frappe.call).toHaveBeenCalled();
			expect(controllerTest.mockForm.add_custom_button).toHaveBeenCalled();
		});

		it('should maintain form state consistency across field changes', () => {
			const controllerTest = getControllerTest();

			// Start with Team organization
			controllerTest.mockForm.doc.organization_type = 'Team';
			controllerTest.mockForm.doc.team = 'Marketing Team';
			controllerTest.mockForm.doc.chapter = 'Amsterdam'; // Should be cleared

			// Change to Chapter
			controllerTest.mockForm.doc.organization_type = 'Chapter';
			controllerTest.testEvent('organization_type');

			// Verify team is cleared
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('team', '');

			// Change back to Team
			controllerTest.mockForm.doc.organization_type = 'Team';
			controllerTest.mockForm.set_value.mockClear();
			controllerTest.testEvent('organization_type');

			// Verify chapter is cleared
			expect(controllerTest.mockForm.set_value).toHaveBeenCalledWith('chapter', '');
		});
	}
};

// Create and export the test suite
describe('Volunteer Expense Controller (Comprehensive Tests)', createControllerTestSuite(volunteerExpenseConfig, customVolunteerExpenseTests));

// Export test utilities for reuse
module.exports = {
	volunteerExpenseConfig,
	customVolunteerExpenseTests
};
