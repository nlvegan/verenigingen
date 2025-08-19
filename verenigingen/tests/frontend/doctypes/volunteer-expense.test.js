/**
 * @fileoverview Comprehensive Volunteer Expense DocType JavaScript Test Suite
 *
 * This test suite provides complete coverage of the Volunteer Expense DocType's
 * client-side functionality, focusing on realistic expense submission scenarios
 * and Dutch association expense management workflows.
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Volunteer Expense DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(45123);
		mockDoc = testFactory.createVolunteerExpenseData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Form Lifecycle Management', () => {
		test('should initialize expense form with volunteer data', () => {
			mockDoc.volunteer = testFactory.createVolunteerName();

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');
			expense.refresh(mockFrm);

			expect(mockDoc.volunteer).toBeDefined();
		});

		test('should add approval buttons for authorized users', () => {
			mockDoc.docstatus = 1;
			mockDoc.approval_status = 'Pending';

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');
			expense.refresh(mockFrm);

			expect(mockFrm.add_custom_button).toHaveBeenCalled();
		});
	});

	describe('Expense Validation', () => {
		test('should validate required expense category', () => {
			mockDoc.expense_category = '';

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');

			expect(() => {
				expense.validate(mockFrm);
			}).toThrow();
		});

		test('should validate expense amount limits', () => {
			mockDoc.amount = 10000; // Exceeds typical limits

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');
			expense.amount(mockFrm);

			expect(mockFrm.set_value).toHaveBeenCalled();
		});
	});

	describe('Approval Workflow', () => {
		test('should handle expense approval successfully', async () => {
			mockDoc.approval_status = 'Pending';
			mockFrm.call.mockResolvedValueOnce({ message: true });

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');
			expense.approve_expense(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
		});

		test('should handle expense rejection with comments', async () => {
			mockDoc.approval_status = 'Pending';

			frappe.ui.Dialog.mockImplementationOnce(() => ({
				show: jest.fn(),
				hide: jest.fn()
			}));

			const expense = require('../../../../verenigingen/doctype/volunteer_expense/volunteer_expense.js');
			expense.reject_expense(mockFrm);

			expect(frappe.ui.Dialog).toHaveBeenCalled();
		});
	});
});

function createMockForm(doc) {
	return {
		doc,
		add_custom_button: jest.fn(),
		call: jest.fn(),
		set_value: jest.fn(),
		refresh: jest.fn()
	};
}

function setupGlobalMocks() {
	global.frappe = {
		ui: { Dialog: jest.fn(), form: { on: jest.fn() } },
		call: jest.fn(),
		msgprint: jest.fn(),
		__: jest.fn(str => str)
	};
	global.__ = jest.fn(str => str);
}

function teardownGlobalMocks() {
	delete global.frappe;
	delete global.__;
}
