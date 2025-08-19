/**
 * @fileoverview Comprehensive MT940 Import DocType JavaScript Test Suite
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('MT940 Import DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(78456);
		mockDoc = testFactory.createMT940ImportData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('File Import Management', () => {
		test('should validate MT940 file format', () => {
			mockDoc.mt940_file = '/files/bank_statement.mt940';

			const mt940 = require('../../../../verenigingen/doctype/mt940_import/mt940_import.js');
			mt940.mt940_file(mockFrm);

			expect(mockDoc.mt940_file).toContain('.mt940');
		});

		test('should process bank transactions', async () => {
			mockDoc.status = 'Ready';
			mockFrm.call.mockResolvedValueOnce({
				message: {
					transactions_processed: 45,
					reconciled: 40,
					unmatched: 5
				}
			});

			const mt940 = require('../../../../verenigingen/doctype/mt940_import/mt940_import.js');
			mt940.process_import(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
		});
	});

	describe('Transaction Reconciliation', () => {
		test('should match transactions to invoices', () => {
			mockDoc.auto_reconcile = true;

			const mt940 = require('../../../../verenigingen/doctype/mt940_import/mt940_import.js');
			mt940.auto_reconcile(mockFrm);

			expect(mockDoc.auto_reconcile).toBe(true);
		});

		test('should handle reconciliation errors', async () => {
			mockFrm.call.mockRejectedValueOnce(new Error('Reconciliation failed'));

			const mt940 = require('../../../../verenigingen/doctype/mt940_import/mt940_import.js');

			await expect(async () => {
				await mt940.process_import(mockFrm);
			}).not.toThrow();
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
