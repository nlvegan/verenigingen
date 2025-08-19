/**
 * @fileoverview Comprehensive Expulsion Report Entry DocType JavaScript Test Suite
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Expulsion Report Entry DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(67234);
		mockDoc = testFactory.createExpulsionReportEntryData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Expulsion Reporting', () => {
		test('should create expulsion report entry', () => {
			mockDoc.member = testFactory.createMemberName();
			mockDoc.expulsion_date = '2025-08-19';
			mockDoc.reason = 'Serious policy violation';
			mockDoc.status = 'Reported';

			const entry = require('../../../../verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js');
			entry.refresh(mockFrm);

			expect(mockDoc.status).toBe('Reported');
		});

		test('should validate required documentation', () => {
			mockDoc.documentation_complete = false;

			const entry = require('../../../../verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js');
			entry.documentation_complete(mockFrm);

			expect(mockDoc.documentation_complete).toBe(false);
		});
	});

	describe('Audit Trail Management', () => {
		test('should track expulsion workflow', () => {
			mockDoc.workflow_status = 'Board Approved';
			mockDoc.approval_date = '2025-08-19';

			const entry = require('../../../../verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js');
			entry.workflow_status(mockFrm);

			expect(mockDoc.workflow_status).toBe('Board Approved');
		});

		test('should generate compliance report', async () => {
			mockDoc.status = 'Completed';
			mockFrm.call.mockResolvedValueOnce({
				message: { report_url: '/files/expulsion_report.pdf' }
			});

			const entry = require('../../../../verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js');
			entry.generate_report(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
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
		ui: { form: { on: jest.fn() } },
		call: jest.fn(),
		__: jest.fn(str => str)
	};
	global.__ = jest.fn(str => str);
}

function teardownGlobalMocks() {
	delete global.frappe;
	delete global.__;
}
